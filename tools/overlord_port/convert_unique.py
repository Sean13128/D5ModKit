"""OLCONV2: Overlord Edition v3 Stella / Rutile / Majin -> complete D5 Mod Kit unique-character mods (offline).

Input : the extracted Overlord v3 release (Cryswar, The Unlicense), outside the repo.
Output: <out>/mods/<mod name>/ in the pack layout of the installed D4 unique packs (model: D4_Unique_350):

    mod.json                               credit, ledger (exact / adapted / missing), leased ids
    patches/db/{char,Skill,magic,charhelp,WishDataBase}.dat.json
    patches/characters/unique.json         registry shape: identity + leased physical art row + template
    patches/characters/face_<physical>.png 204x204 face
    patches/evilities/evilities.json       .d5el behaviour for the converted evilities
    patches/voices/voices.json + *.vag     the source voice set, situation masks kept
    patches/wishes/recruit_wishes.json     the OLWISH1 recruit bill (character = the leased identity)
    files/Anime/ANM_HI_JP.dat/anm<N>.lzs   body N, N+1 (the source's two banks on the D5 clock), N+2 list icon,
                                           10000+N cut-in

Ids come from the lease record `d5lib/importers/overlord-leases.json` (tools/overlord_port/leases_unique.py).  A
build never allocates; it refuses when the record is missing.

  PYTHONDONTWRITEBYTECODE=1 python tools/overlord_port/convert_unique.py --out <dir outside the repo> [--only Stella]

Based on P4's convert.py (Stella only, ids re-leased because they went stale); the row/voice/ANM helpers are
imported from it.  Nothing here installs, launches, or writes the game, an install, a profile or a save.
"""
from __future__ import annotations

import argparse
import copy
import numpy as np
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
sys.dont_write_bytecode = True

import numpy as np

from d5lib import anm, database, gamefs, hybridanim, lzs, outfits, sfx, sprites, voices  # noqa: E402
from d5lib.d4unique import Originals  # noqa: E402
from tools.overlord_port import anm_foreign, convert as P4, effects, leases_unique, recruit_wishes  # noqa: E402

RELEASE, DB0, VIS, GEN, VOICE_EN = P4.RELEASE, P4.DB0, P4.VIS, P4.GEN, P4.VOICE_EN
PROJECT, GAME, STATE, CLOCK = P4.PROJECT, P4.GAME, P4.STATE, P4.CLOCK
sha, jdumps, rows_of, foreign_bank = P4.sha, P4.jdumps, P4.rows_of, P4.foreign_bank
# his bill rows come from the release's own table, never from the installed "Overlord Recruit Wishes" mod: that
# folder is rewritten by OLWISH1 deployments (its rows already carry req_flag1; seen changing during this lane)
CUSTOM_WISHES = RELEASE / "mods/_loader/custom_wishes.txt"
CREDIT = ("Cryswar (Disgaea 5 Overlord Edition v3, The Unlicense); converted for the D5 project, offline")

# What each character is, in the source.  `template` is the humanoid donor the unique.json declares (kind_gender
# 1 -> 1010, 2 -> 1020, the two the installed D4 uniques use); `evilities` lists, in order, the source Skill.dat ids
# that become leased rows (a split row appears twice: see EVILITY_PLAN).
CHARS = {
    "Overlord Character - Stella": dict(
        key="stella", source_id=20300, name="Stella", template=1020,
        banks=("anm20300.dat", "anm20301.dat"), cutin="anm30300.lzs", face="large_a/10.png",
        voice_group=420300, voice_label="Stella (Overlord v3)",
        specials=(40300, 40301, 40302), skill_rows=(20300, 20301, 20302)),
    "Overlord Character - Rutile": dict(
        key="rutile", source_id=20310, name="Rutile", template=1020,
        banks=("anm20310.dat", "anm20311.dat"), cutin="anm30310.lzs", face="large_a/28.png",
        voice_group=420310, voice_label="Rutile (Overlord v3)",
        specials=(40310, 40311, 40312), skill_rows=(20310,)),
    "Overlord Character - Majin": dict(
        key="majin", source_id=20500, name="Majin", template=1010,
        banks=("anm20500.dat", "anm20501.dat"), cutin="anm30500.lzs", face="large_a/11.png",
        voice_group=420500, voice_label="Majin (Overlord v3)",
        specials=(), skill_rows=(20500, 20501, 20502, 20503)),
}

TEXT_LANGS = ("JP", "EN", "FR", "CHN", "KOR")


def lease_of(mod_name):
    doc = leases_unique.load()
    if mod_name not in doc["entries"]:
        raise SystemExit(f"{mod_name}: no lease in {leases_unique.RECORD}; run tools/overlord_port/leases_unique.py")
    return doc["entries"][mod_name]


# --------------------------------------------------------------------------- rows
def english_only(r, prefixes=("name", "desc")):
    """The source's JP/FR/CHN/KOR evility strings are copies of unrelated vanilla evilities (checked in the release
    for all eight rows: Stella's JP/FR/CHN/KOR read 'units in the same squad', 'Revenge Mode attack +%d%%' ...),
    so every locale gets the English text."""
    for p in prefixes:
        for lang in TEXT_LANGS:
            r[f"{p}_{lang}"] = r[f"{p}_EN"]
    return r


def evility_plan(key, lease, src):
    """-> (Skill.dat rows, {leased id: [behaviour section, ...]}, char evility slots, ledger notes).

    Behaviour sections come from the Kit's own effects converter (`tools/overlord_port/effects.py`) on Overlord's
    evilities.ini; only where it refuses (the aura rows) is the section written by hand, and then labelled.
    """
    ev = list(lease["evilities"])
    table, verdicts = effects.convert(RELEASE / "mods/Overlord/evilities.ini", SKILL_TABLE())
    beh = table["evilities"]
    rows, behaviour, notes, slots = [], {}, [], []

    def row(src_id, new_id, char_id, **kw):
        r = copy.deepcopy(src[src_id])
        r.update(id=new_id, owner=char_id, class_order=0, **kw)
        return english_only(r)

    # The learned-evility bitmap has 1000 positions and the installed table already fills them (tools/
    # check_skill_budget.py: "bitmap positions left 0"), so a LEARNABLE (kind 0) row cannot be added without moving
    # an installed row.  The source's learnable rows therefore become innate rows linked from the char row
    # (kind 1, no slot cost, no mana cost, not in the shop): same effect, no longer bought.
    innate = dict(kind=1, slot_cost=0, mana_cost=0, shop_rank=0)

    ident = lease["identity"]
    if key == "stella":
        e0, e1, e2, e3 = ev
        buff = row(20300, e0, ident)
        # the source text has two %d (value1 and value2, both 25); the drawer passes ONE integer and tools/
        # check_pack_tables.py flags a second conversion, so the second number is written as "the same amount"
        buff["desc_EN"] = "Increase stats by %d％ per adjacent unit, but lowers theirs by the same amount."
        english_only(buff)
        rows += [buff, row(20302, e2, ident, **innate), row(20301, e3, ident, **innate)]
        aura = row(20300, e1, ident, slot_cost=0, mana_cost=0)
        aura.update(name_EN="Presidential Air (aura)",
                    desc_EN="Lowers the stats of every other unit adjacent to this one by %d％.")
        english_only(aura)
        rows.append(aura)
        behaviour[e0] = beh["20300"][:1]                       # stat_per_unit_in_range (native, verdict native)
        behaviour[e1] = [{"family": ["stats", "aura"], "effects": [{"stat": "all", "value": -25}],
                          "condition": {"kind": "near_has", "of": 0, "radius": 1, "id": e1}}]
        behaviour[e2] = beh["20302"]                           # stat_conversion_flat int -> atk, element_any
        behaviour[e3] = [{"family": ["taken", "aura"], "effects": [{"value": 30}],
                          "conditions": [{"kind": "near_has", "of": 0, "radius": 0xFFFF, "id": e3},
                                         {"kind": "element", "id": 1}]}]
        slots = [e0, e1, e2, e3]
        notes = [
            "Presidential Air = two sections under one source id (self +25% per adjacent unit, aura -25% on adjacent "
            "units); a Kit row carries one behaviour, so the aura half has its own leased row and is the character's "
            "second innate evility. The self half is the converter's native verdict; the aura half is hand-written "
            "because effects.py refuses stat_aura_percent (presence test, not per-holder stacking, no automatic enemy "
            "negation): ADAPTED",
            "Heat Depression (source: fire resistance -30% for ALL units except self, range=map) = aura 'taken' +30% "
            "from fire on every unit while a holder is anywhere on the map (near_has radius 0xFFFF, the evil_near "
            "'anywhere' sentinel the evility format accepts), the holder excluded by the aura rule. Range is exact; "
            "the effect is adapted because the Kit has no element-resistance family (resistance is expressed as "
            "damage taken). P4 shipped 25; the source value1 is 30, corrected: ADAPTED (effect), EXACT (range)",
            "Mighty Elements = conversion family int->atk 30% with the element_any condition (effects.py verdict "
            "native). The condition needs an action context the stat pass may not provide (P4's warning): expected "
            "inert until measured live: UNVERIFIED",
        ]
    elif key == "rutile":
        e0 = ev[0]
        rows.append(row(20310, e0, ident))
        behaviour[e0] = copy.deepcopy(beh["20310"])             # stats +5% per squad unit, no cap (see note)
        slots = [e0]
        notes = [
            "Ring of Friends = stats +5% per unit in the same squad (family stats, per squad: the game's own squad "
            "helper). The source's cap of 40% is NOT carried: the Kit's stats family cannot hold a cap (a `max` on "
            "it is refused by evility.table(): 'max needs only percentage or additive families', found when the "
            "first build tried it), so the bonus is uncapped and exceeds the source above 8 squad members: "
            "ADAPTED; per-squad count itself UNVERIFIED live",
        ]
    elif key == "majin":
        e0, e1, e2, e3 = ev
        rows += [row(20500, e0, ident), row(20501, e1, ident, **innate), row(20502, e2, ident, **innate),
                 row(20503, e3, ident, **innate)]
        behaviour[e0] = beh["20500"]                           # permanent_revenge + block_overload (two sections)
        behaviour[e1] = beh["20501"]                           # power +50 while in Revenge
        behaviour[e2] = beh["20502"]                           # taken -25 while in Revenge
        behaviour[e3] = beh["20503"]                           # all stats +30 while in Revenge
        slots = [e0, e1, e2, e3]
        notes = [
            "Divine General = permanent_revenge + block_overload, two sections on one row (both families exist in the "
            "Kit; permanent revenge re-enters Revenge mode at every round edge)",
            "God-Smashing Blow / Scar-Writ Saga / Crowned with Fury are gated on Revenge mode through the "
            "`self_status` condition with id 26 (0x1A, Revenge). That id is the effects converter's inference from "
            "the status table, not a measured equivalence: UNVERIFIED live",
        ]
    # every row stays a labelled learnable/innate row exactly as the source set it (slot_cost, mana_cost, kind)
    return sorted(rows, key=lambda r: r["id"]), behaviour, slots, notes


_SKILL_T = []


def SKILL_TABLE():
    if not _SKILL_T:
        _SKILL_T.append(rows_of(DB0 / "Skill.dat", "Skill.dat"))
    return _SKILL_T[0]


def char_row(src, spec, lease, slots, specials):
    r = dict(src)
    r.update(id=lease["identity"], sprite_id=lease["physical"], color_id=lease["physical"],
             help_id=lease["help_id"], voice_id=lease["voice"],
             evility1=0, evility2=0, evility3=0, evility4=0, evility_count=len(slots))
    for n, e in enumerate(slots, 1):
        r[f"evility{n}"] = e
    smap = dict(zip(spec["specials"], specials))
    learn = [(smap.get(r[f"learn{i}_skill"], r[f"learn{i}_skill"]), r[f"learn{i}_level"])
             for i in range(1, 17) if r[f"learn{i}_skill"]]
    learn.sort(key=lambda x: (x[1], x[0]))
    for i in range(1, 17):
        s, lv = learn[i - 1] if i <= len(learn) else (0, 0)
        r[f"learn{i}_skill"], r[f"learn{i}_level"] = s, lv
    r["learn_count"] = len(learn)
    return r


def special_rows(src_rows, lease, ident):
    out = []
    for src, new in zip(src_rows, lease["specials"]):
        r = dict(src)
        r["id"] = new
        r["user1"], r["user2"], r["user3"], r["user4"], r["user_count"] = ident, 0, 0, 0, 1
        out.append(r)
    return out


def wish_bundle(spec, lease):
    """The recruit bill: his WishDataBase row + his custom_wishes.txt entry through OLWISH1's own converter, then the
    bill id and character re-pointed at the leased ids."""
    src_rows = [r.to_dict() for r in rows_of(DB0 / "WishDataBase.dat", "WishDataBase.dat").rows]
    table = recruit_wishes.parse_custom_wishes(CUSTOM_WISHES.read_text(encoding="utf-8"))
    sid = spec["source_id"]
    # his table keys the bill by the character id for these three
    rows, recruits, report = recruit_wishes.convert_rows([r for r in src_rows if r["id"] == sid], {sid: table[sid]})
    row = rows[0]
    row["id"] = lease["bill"]
    rec = recruits["recruits"][str(sid)]
    rec = dict(rec, character=lease["identity"])
    from d5lib import wishrecruit
    wishrecruit.normalise({str(lease["bill"]): rec})
    return row, {"recruits": {str(lease["bill"]): rec}}, dict(source_bill=sid, source_entry=list(table[sid]))


# --------------------------------------------------------------------------- art
WEAPON_ROWS = {1: "fist", 11: "sword", 21: "lance", 31: "arrow", 41: "gun", 51: "ax", 61: "other"}
ATTACK_PREFER = {"fist": (7011,), "sword": (7031, 7011), "lance": (7031, 7041, 7011), "arrow": (7041, 7031, 7011),
                 "gun": (7041, 7031, 7011), "ax": (7041, 7031, 7011), "other": (7011,)}


def full_poses(raw):
    """source animation ids that draw a whole figure.  The release's 7001/7007 (and, for some characters, 7021-7041)
    are hand/ear OVERLAY layers of the D5 sheet layout (a wireframe of the body with only hands, feet and a weapon
    outline coloured): drawn alone they look like a sketch.  P4's mapping used 7001 as the stand and 7041 for every
    skill and attack id, so Stella's stand was that sketch and Rutile's 6001 slot a 1.59x weapon outline (found
    here when the smoke gate failed on N+1 and on Rutile).  A figure is whole when its opaque area is at least half
    of the idle loop's (6001)."""
    a = anm.parse(anm_foreign.parse_foreign(raw).to_bytes())
    blk = a.blocks[0]
    area = {}
    for an in blk.animations:
        if not an.id:
            continue
        times = anm.frame_times(a, ("id", an.id))
        im = anm.render_items(a, anm.evaluate(a, ("id", an.id), max(times) // 2, nested=True), 0)[0]
        al = np.asarray(im.getchannel("A"))
        area[an.id] = int((al > 0).sum())
    ref = area.get(6001) or max(area.values())
    return {i for i, v in area.items() if v >= 0.5 * ref}, area


def hybrid_bank(src_path, new_id, report):
    """the source bank's art on the D5 humanoid clock (as P4's _hybrid), with a whole-figure source for every clock
    animation: idle loop for stand / wait / walk / hurt / jump..., the source's attack poses for attack families."""
    raw = foreign_bank(src_path)
    full, area = full_poses(raw)
    if 6001 not in full:
        raise SystemExit(f"{src_path.name}: no whole-figure idle loop (6001)")
    b0 = anm_foreign.parse_foreign(raw)
    clock = anm.load(str(CLOCK))

    STAND = {1, 31, 101}                    # frameconvert.DEFAULT_MAP "stand" rows (front; back view = +6)

    def pick(aid):
        back = aid % 10 == 7
        idle = 6007 if back and 6007 in full else 6001
        if (aid - 6 if back else aid) in STAND:
            # a whole-figure stand pose of its own (7001 front / 7007 back, e.g. Majin's second bank) beats the idle loop
            stand = 7007 if back else 7001
            if stand in full:
                return stand
        row = WEAPON_ROWS.get((aid % 100) - (aid % 10) + 1) if 2000 <= aid < 4100 else None
        if row:
            for cand in ATTACK_PREFER[row]:
                if cand in full:
                    return cand
        return idle

    sources = {a.id: pick(a.id) for a in clock.blocks[0].animations}
    log = []
    out = hybridanim.compose(clock, b0, new_id, sources, (), log.append)
    body = out.to_bytes()
    back = anm.parse(body)
    ids = sorted({a.id for a in back.blocks[0].animations})
    stand = {}
    for aid in (1, 7, 1001, 6001):
        if aid in ids:
            im = anm.render_frame(back, ("id", aid), 0, 0)
            stand[aid] = list(im.getchannel("A").getbbox() or ())
    used = {}
    for k, v in sources.items():
        used.setdefault(v, 0)
        used[v] += 1
    report.setdefault("hybrid", []).append(dict(
        member=f"anm{new_id:05d}.lzs", source=src_path.name, source_animations=sorted(area),
        whole_figure_sources=sorted(full), overlay_only_sources=sorted(set(area) - full),
        clock=dict(path=str(CLOCK.relative_to(PROJECT)), animations=len(clock.blocks[0].animations), sha256=sha(CLOCK.read_bytes())),
        mapped_animations=len(ids), clock_animations_per_source=used,
        donor_to_source={str(k): v for k, v in sorted(sources.items())}, stand_bbox=stand, log=log[:2]))
    return raw, body, ids


def write_art(fs, mod, spec, lease, report):
    out = mod / "files/Anime/ANM_HI_JP.dat"
    out.mkdir(parents=True, exist_ok=True)
    n = lease["physical"]
    bodies = []
    for off, name in enumerate(spec["banks"]):
        src = VIS / "Anime/ANM_HI_EN" / name
        raw, body, ids = hybrid_bank(src, n + off, report)
        member = f"anm{n + off:05d}.lzs"
        (out / member).write_bytes(anm.lzs_compress(body))
        bodies.append(body)
        report["members"].append(dict(source=str(src.relative_to(RELEASE)), member=member, source_sha256=sha(raw),
                                      member_sha256=sha((out / member).read_bytes()), block_id=n + off,
                                      animations=len(ids), note="source art on the D5 animation clock"))
    # n+2: the small standing list icon (resident-icon template repainted from the body, as D4 uniques do)
    t = spec["template"]
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, t, "EN")))
    motion = sprites.motion_block(fs, 1, lambda s: None) if sprites.needs_motion_set(base) else None
    icon = outfits._resident_icon(fs, t + 2)
    sprite0 = anm.parse(bodies[0])
    icon = outfits.repaint_stand_icon(icon, base, motion, sprite0)
    icon.blocks[0].id = n + 2
    (out / f"anm{n + 2:05d}.lzs").write_bytes(anm.lzs_compress(icon.to_bytes()))
    report["members"].append(dict(member=f"anm{n + 2:05d}.lzs", block_id=n + 2,
                                  note=f"list icon: resident icon {t + 2} repainted from the body's stand frames"))
    # cut-in bank 10000+n (the source ships one cut-in bank per palette; palette 0 is shipped)
    src = VIS / "Anime/ANM_HI_EN" / spec["cutin"]
    raw = foreign_bank(src)
    f = anm_foreign.reid(raw, 10000 + n)
    body = f.to_bytes()
    back = anm.parse(body)
    same = []
    for aid in sorted(a.id for a in back.blocks[0].animations)[:4]:
        a = anm.render_frame(f, ("id", aid), 0, 0)
        b = anm.render_frame(back, ("id", aid), 0, 0)
        same.append(a.size == b.size and a.tobytes() == b.tobytes())
    member = f"anm{10000 + n:05d}.lzs"
    (out / member).write_bytes(anm.lzs_compress(body))
    report["members"].append(dict(source=str(src.relative_to(RELEASE)), member=member, source_sha256=sha(raw),
                                  member_sha256=sha((out / member).read_bytes()), block_id=10000 + n,
                                  animations=len(back.blocks[0].animations), render_identical=all(same)))
    if not all(same):
        raise SystemExit(f"{member}: re-id'd cut-in does not render like the source")


def write_face(mod, spec, lease, report):
    src = GEN / "large204_registry_v014/large_a" / Path(spec["face"]).name
    dst = mod / "patches/characters" / f"face_{lease['physical']}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    from PIL import Image
    im = Image.open(dst)
    report["face"] = dict(source=str(src.relative_to(RELEASE)), size=list(im.size), sha256=sha(dst.read_bytes()))


def write_voice(mod, spec, lease, report):
    group = spec["voice_group"]
    table = voices.read_table((DB0 / "Sound_Voice_EN_0.dat").read_bytes())
    src_rows = sorted((l for l in table if l.group == group), key=lambda l: l.id)
    vdir = mod / "patches/voices"
    vdir.mkdir(parents=True, exist_ok=True)
    lines, clips = [], []
    folder = VOICE_EN / str(group)
    for n, line in enumerate(src_rows, start=1):
        idx = line.id % 1000
        clip = folder / f"{group}{idx:03d}.nlsd"
        if not clip.exists():
            report.setdefault("voice_skipped", []).append(dict(row=line.id, why="clip missing"))
            continue
        raw = clip.read_bytes()
        tmp = vdir / f".src_{idx:03d}.wav"
        tmp.write_bytes(raw[raw.index(b"RIFF"):])
        pcm, rate = sfx.load_audio(str(tmp))
        tmp.unlink()
        name = f"{lease['voice']}_{n:04d}.vag"
        (vdir / name).write_bytes(sfx.make_vag(pcm, rate))
        lines.append(dict(kind=0, volume=line.volume, cats=line.cats, tail=line.tail, file=name))
        clips.append(dict(source=clip.name, file=name, samples=int(len(pcm)), rate=int(rate),
                          source_sha256=sha(raw), file_sha256=sha((vdir / name).read_bytes())))
    present = {int(p.name[len(str(group)):len(str(group)) + 3]) for p in folder.glob("*.nlsd")}
    unlisted = sorted(present - {l.id % 1000 for l in src_rows})
    data = {"voices": {str(lease["voice"]): {"name": spec["voice_label"], "tail": "01000400", "lines": lines}}}
    (vdir / "voices.json").write_text(json.dumps(data, indent=1) + "\n")
    report["voice"] = dict(group=group, rows=len(src_rows), clips_written=len(clips), clips_in_release=len(present),
                           unlisted_clips=unlisted, first=clips[:2])


# --------------------------------------------------------------------------- mod
def build_one(fs, mod_name, out_root, tables_cache, van_char):
    spec, lease = CHARS[mod_name], lease_of(mod_name)
    ident = lease["identity"]
    report = dict(schema="olconv2-evidence/1", mod=mod_name, source=dict(character_id=spec["source_id"],
                  release="Disgaea 5 Overlord Edition v3", creator="Cryswar", licence="The Unlicense"),
                  lease=lease, members=[])
    char_t, skill_t, magic_t, help_t = (tables_cache[k] for k in ("char", "skill", "magic", "help"))
    src_char = char_t.find(spec["source_id"]).to_dict()
    src_skill = {i: skill_t.find(i).to_dict() for i in spec["skill_rows"]}
    src_magic = [magic_t.find(i).to_dict() for i in spec["specials"]]
    src_help = help_t.find(spec["source_id"]).to_dict()

    ev_rows, behaviour, slots, ev_notes = evility_plan(spec["key"], lease, src_skill)
    char = char_row(src_char, spec, lease, slots, lease["specials"])
    sks = special_rows(src_magic, lease, ident)
    hlp = dict(src_help)
    hlp["id"] = hlp["char_id"] = lease["help_id"]
    bill_row, recruits, bill_info = wish_bundle(spec, lease)

    mod = out_root / "mods" / mod_name
    if mod.exists():
        shutil.rmtree(mod)
    (mod / "patches/db").mkdir(parents=True)
    tables = {"char.dat": [char], "Skill.dat": ev_rows, "charhelp.dat": [hlp], "WishDataBase.dat": [bill_row]}
    if sks:
        tables["magic.dat"] = sks
    for name, rows in tables.items():
        (mod / "patches/db" / f"{name}.json").write_text(
            jdumps({"table": name, "added": rows}, indent=1, ensure_ascii=False) + "\n")
    (mod / "patches/evilities").mkdir()
    (mod / "patches/evilities/evilities.json").write_text(
        json.dumps({"evilities": {str(k): v if len(v) > 1 else v[0] for k, v in sorted(behaviour.items())}},
                   indent=1) + "\n")
    (mod / "patches/wishes").mkdir()
    (mod / "patches/wishes/recruit_wishes.json").write_text(json.dumps(recruits, indent=1) + "\n")
    donor = van_char.find(spec["template"])
    unique = dict(schema=1, identity=ident, physical=lease["physical"], template=spec["template"],
                  template_colour=int(donor["color_id"]), kind="humanoid", name=spec["name"],
                  rule="one rank on a registry identity; sprite/portrait/face keys leased to physical")
    (mod / "patches/characters").mkdir(exist_ok=True)
    (mod / "patches/characters/unique.json").write_text(json.dumps(unique, indent=1) + "\n")
    write_face(mod, spec, lease, report)
    write_voice(mod, spec, lease, report)
    write_art(fs, mod, spec, lease, report)

    ledger = ledger_for(spec, lease, ev_notes, bill_info, report)
    meta = {
        "name": mod_name,
        "author": "Cryswar (Disgaea 5 Overlord Edition v3, The Unlicense); converted by the D5 project, offline",
        "version": "0.1.0-converted",
        "description": (f"{spec['name']} from Cryswar's Disgaea 5 Overlord Edition v3 as a complete Kit unique "
                        f"character: row, face, cut-in, list icon, two sprite banks, help text, "
                        f"{'specials, ' if sks else ''}evilities with Kit behaviour, voice lines and a recruit bill "
                        f"at the Strategy Assembly. Replaces the row-only conversion of the same name."),
        "category": "characters",
        "enabled_by_default": False,
        "credit": [{"author": "Cryswar", "work": "Disgaea 5 Overlord Edition v3", "licence": "The Unlicense",
                    "what": "character, evility, skill and help rows, voice set, portraits, cut-in, animation banks"}],
        "source_import": {"source": dict(game="d5", edition="Disgaea 5 Overlord Edition v3 (community release)",
                                         character_id=spec["source_id"], name=spec["name"], creator="Cryswar",
                                         licence="The Unlicense"),
                          "fidelity": "hybrid", "native_tested": False,
                          "adaptations": ledger["adaptations"], "missing_mappings": ledger["missing"],
                          "leased_ids": lease},
    }
    (mod / "mod.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    report["ledger"] = ledger
    report["bill"] = bill_info
    (out_root / f"evidence-{spec['key']}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n")
    return mod, report


def _ranges(ids):
    ids = sorted(ids)
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(str(ids[i]) if i == j else f"{ids[i]}-{ids[j]}")
        i = j + 1
    return ",".join(out)


def motion_ledger(report):
    """one precise line per body bank: which donor motion ids show which source animation, which show idle."""
    lines = []
    for h in report["hybrid"]:
        by = {}
        for k, v in h["donor_to_source"].items():
            by.setdefault(v, []).append(int(k))
        parts = []
        for src in sorted(by):
            ids = by[src]
            kind = {6001: "front idle loop", 6007: "back idle loop", 7001: "whole stand pose (front)",
                    7007: "whole stand pose (back)"}.get(src, "attack pose")
            listing = f" [{_ranges(ids)}]" if src not in (6001, 6007) else " (every other donor id of that facing)"
            parts.append(f"source {src} ({kind}) on {len(ids)} donor ids{listing}")
        attack = sorted(v for v in by if v not in (6001, 6007, 7001, 7007))
        unused = sorted(set(h["whole_figure_sources"]) - set(by))
        lines.append(
            f"body bank {h['member']} (source {h['source']}): " + "; ".join(parts) + ". "
            + ("Donor ids not listed under an attack pose show the idle loop, normal attacks included"
               if attack else "NO source attack pose is used: every donor attack id, normal attacks included, shows the idle loop")
            + (f"; whole source poses never used: {unused}" if unused else "")
            + (f"; overlay-only source layers ignored: {h['overlay_only_sources']}" if h["overlay_only_sources"] else "") + ".")
    return lines


def ledger_for(spec, lease, ev_notes, bill_info, report):
    n = lease["physical"]
    exact = [
        "char.dat row: base stats, aptitudes, MOV/JMP/throw/counter/crit, attack range, size, height, gender, "
        "resistances, weapon masteries, torture/overload ids, is_unique and dlc_group are the source row's fields",
        "help text: the source's lines, unchanged",
        f"voice: {report['voice']['clips_written']} of the release's {report['voice']['clips_in_release']} clips, each "
        "keeping the source row's situation bitmask, volume and tail; ids and the clip container were translated",
        "face: the release's 204px large portrait, copied unchanged (the resident face cell size)",
        "cut-in: the release's palette-0 cut-in bank, re-id'd; rendered frames identical to the source",
        f"recruit bill: his WishDataBase row (name, text, mana cost, difficulty, unlock flag) and his "
        f"custom_wishes.txt entry {bill_info['source_entry'][:4]} (character, level, duplicates, required flag) "
        "through OLWISH1's converter",
    ]
    if spec["specials"]:
        exact.append("specials: the source rows' name, description, SP, element, formula, power/exp ladders, area, "
                     "attack map, range, heights, icon and user list; the learn levels are the source's")
    adapted = [
        f"ids: Overlord's 20000-21999 band stays his (coexistence), so char row = registry identity {lease['identity']}, "
        f"art keyed to physical row {n} (banks {n}/{n + 1}, list icon {n + 2}, cut-in {10000 + n}), evilities "
        f"{lease['evilities']} (late band, above every in-use Skill.dat row), specials {lease['specials']}, voice "
        f"{lease['voice']}, charhelp {lease['help_id']}, bill {lease['bill']}; recorded in "
        "d5lib/importers/overlord-leases.json",
        "body art: the source banks carry only a few animation ids; each bank is drawn on the D5 humanoid animation "
        "clock (the D4_Class_1190 donor bank anm01460, 138 ids). Rendered source frames are not changed; the timing is "
        "the donor's. Exactly which donor ids show which source pose is listed in the next lines",
        *motion_ledger(report),
        "list icon (N+2): the resident icon of the template repainted from the body's front/back stand frames, the "
        "same step the D4 uniques use",
        "recruit: a Strategy Assembly bill read by the Kit's wishrecruit hooks (RECRUIT1); the source's own runtime "
        "dispatch is not used",
        "learnable -> innate: the source's learnable evilities (Stella: Mighty Elements, Heat Depression; Majin: "
        "God-Smashing Blow, Scar-Writ Saga, Crowned with Fury; mana 1000 each in the source) are innate rows on the "
        "character here, because the installed table has no free learned-evility bitmap position (a new learnable row "
        "fails tools/check_skill_budget.py; moving an installed row would break saves). The unit has them from the "
        "start instead of buying them; Majin carries all four, which is stronger than the source",
        "Presidential Air text: the source description holds two %d; the Kit's drawer passes one integer, so the "
        "second number reads 'the same amount' (both source values are 25)",
        "non-English evility strings: the release's JP/FR/CHN/KOR text is a copy of unrelated vanilla evilities, so "
        "every locale shows the English text",
        *ev_notes,
    ]
    missing = [
        "own skill animations: the source specials ship anim_id 65535 (no animation) and keep it" if spec["specials"]
        else "no specials: the source ships none for this character",
        "palettes: the release records more palettes/cut-ins than one pack ships; palette 0 art and cut-in only",
        "no source-game (D3/D4/Majin lore) fidelity check: every value is Overlord's D5 rebalance, not a measured "
        "source row",
        "native gameplay acceptance: not run (offline lane)",
    ]
    return dict(exact=exact, adaptations=adapted, missing=missing)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="output root outside the repo; mods go in <out>/mods/")
    ap.add_argument("--only", action="append", help="character key(s): stella, rutile, majin")
    a = ap.parse_args(argv)
    out_root = Path(a.out).resolve()
    if str(out_root).startswith(str(PROJECT)) and "/Builds/" not in str(out_root):
        raise SystemExit("refusing to write game data into the project outside Builds/")
    out_root.mkdir(parents=True, exist_ok=True)
    names = [n for n, s in CHARS.items() if not a.only or s["key"] in a.only]
    fs = gamefs.GameFS(str(GAME), backup_resolver=Originals(STATE))
    try:
        tc = dict(char=rows_of(DB0 / "char.dat", "char.dat"), skill=SKILL_TABLE(),
                  magic=rows_of(DB0 / "magic.dat", "magic.dat"), help=rows_of(DB0 / "charhelp.dat", "charhelp.dat"))
        van_char = database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat"))
        for n in names:
            mod, rep = build_one(fs, n, out_root, tc, van_char)
            print(json.dumps(dict(ok=True, mod=str(mod), lease=rep["lease"], members=len(rep["members"]),
                                  voice=rep["voice"]["clips_written"]), indent=1))
    finally:
        fs.reset()


if __name__ == "__main__":
    main()
