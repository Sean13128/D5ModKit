"""Overlord Edition v3 -> D5 Mod Kit: convert one character into a private Kit mod (offline).

Input : the Overlord v3 release tree (Cryswar, The Unlicense) extracted outside the game.
Output: a Kit mod folder (rows, art, voices, skills, evilities, recruit quest) plus a ledger that maps
        every source id to a leased Kit id and states the fidelity of every converted field.

Nothing here installs, launches or writes into the game: tables are read read-only, ANM members are
re-written in the Kit's own layout, and the mod folder is written under the given output root.

  PYTHONDONTWRITEBYTECODE=1 python3 tools/overlord_port/convert.py --out /path/outside/repo

Design notes
------------
* Overlord's content is authored as D5 tables, so rows are copied field for field and only the ids that
  would collide with Overlord's own bands (char 20300, evilities 20300-20302, specials 40300-40302,
  voice 42030) are re-leased.  No full-table replacement is produced: one char row, three Skill.dat
  rows, three magic.dat rows, one Quest.dat row and one charhelp.dat row.
* ANM banks are read with tools/overlord_port/anm_foreign.py because the authoring tool does not keep
  the Kit's 16-byte block alignment / 128-byte image packing / 256x1 palette header; the re-emitted
  member is byte-for-byte readable by d5lib.anm and renders identically (checked in the receipt).
* Voices: the release ships 28-byte-header + MS-ADPCM WAV clips (".nlsd") and a line table whose rows
  carry the situation bitmask the game triggers on.  Both are translated: the bitmask is preserved per
  line, the ids become a Kit custom voice (6000-9999).
* Evilities get real behaviour in patches/evilities/evilities.json (.d5el) where the Kit's families can
  express the source effect, and the nearest expressible effect where they cannot -- every such choice
  is in the ledger with the source text that justifies it.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

from d5lib import anm, database, facepatch, gamefs, hybridanim, lzs, modsys, ownership, sfx, sprites, voices  # noqa: E402
from d5lib.d4unique import Originals  # noqa: E402
from tools.overlord_port import anm_foreign  # noqa: E402

PROJECT = Path("/Volumes/Data/Projects/D5")
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = PROJECT / "D5Modkit/state/games/Disgaea_5_Complete-d8040a88"
MODS_DIR = PROJECT / "Local/Installed D5ModKit/mods"
RELEASE = Path("/Volumes/Data/ai-tmp/claude/overlord-v3")
DB0 = RELEASE / "mods/Overlord/Database/Database_0"
VIS = RELEASE / "mods/Overlord Visual"
GEN = RELEASE / "mods/_generated"
VOICE_EN = RELEASE / "mods/Overlord/Sound_Voice/Sound_Voice_0/Voice_EN"
# the animation clock the source bank does not carry: a D5 humanoid bank in Kit format (D4 Class 1190's
# sprite template, copied from a vanilla D5 donor by the installed kit).  Read-only.
# Read from the D4 build tree, not from the installed kit: this lane may not touch
# Local/Installed D5ModKit, and the accepted D4_Class_1190 artifact is the same bank.
CLOCK = (PROJECT / "Research/d4-expansion-20261018/mvp-focused-repair-build-v1/run-2/imports"
                  "/D4_Class_1190/native-mods/D4_Class_1190/files/Anime/ANM_HI_JP.dat/anm01460.lzs")

SOURCE = dict(character_id=20300, name="Stella", title="M.A. President",
              creator="Cryswar", work="Disgaea 5 Overlord Edition v3", licence="The Unlicense")

HOLDER = "kit:Overlord_Stella_20300"

LEASE = dict(char_row=224, help_id=None, quest_id=None,
             evilities=(7700, 7701, 7702, 7703), specials=(10220, 10221, 10222),
             voice=9071, sprite=(224, 225), cutin=10224)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def jdumps(obj, **kw):
    """row dicts carry raw pad bytes; the Kit's patch format writes them as hex strings."""
    return json.dumps(obj, default=lambda o: o.hex() if isinstance(o, bytes) else str(o), **kw)


def rows_of(path, table):
    return database.load_table(table, Path(path).read_bytes())


def own_installed_mods(token="stella"):
    """Installed mod folders this build replaces: the previous copy of the same character.

    Read-only.  A rebuild must not refuse its own ids, but every other pack's claim still counts.
    """
    out = set()
    for p in glob.glob(str(MODS_DIR / "*/mod.json")):
        try:
            meta = json.loads(Path(p).read_text())
        except (OSError, ValueError):
            continue
        if token in json.dumps(meta).lower():
            out.add(Path(p).parts[-2])
    return out


def installed_table_ids(name, exclude=()):
    """ids every *other* installed mod claims for one Database_0 member (read-only scan)."""
    out = set()
    for p in glob.glob(str(MODS_DIR / "*/patches/db" / f"{name}.json")):
        if Path(p).parts[-4] in exclude:
            continue
        d = json.loads(Path(p).read_text())
        for k in (d.get("rows") or {}):
            out.add(int(k))
        for r in (d.get("added") or []):
            if "id" in r:
                out.add(int(r["id"]))
    return out


# --------------------------------------------------------------------------- leases
def lease_ids(fs, char):
    vanilla_char = {r["id"] for r in database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat")).rows}
    vanilla_skill = {r["id"] for r in database.load_table("Skill.dat", fs.read("Database/Database_0.dat/Skill.dat")).rows}
    vanilla_magic = {r["id"] for r in database.load_table("magic.dat", fs.read("Database/Database_0.dat/magic.dat")).rows}
    vanilla_help = {r["id"] for r in database.load_table("charhelp.dat", fs.read("Database/Database_0.dat/charhelp.dat")).rows}
    vanilla_quest = {r["id"] for r in database.load_table("Quest.dat", fs.read("Database/Database_0.dat/Quest.dat")).rows}
    used_anm = sprites.used_sprite_numbers(fs)
    own = own_installed_mods()
    inst = {t: installed_table_ids(t, exclude=own)
            for t in ("char.dat", "Skill.dat", "magic.dat", "charhelp.dat", "Quest.dat")}
    used_voices = set()
    for p in glob.glob(str(MODS_DIR / "*/patches/voices/voices.json")):
        if Path(p).parts[-4] in own:
            continue
        used_voices |= {int(v) for v in (json.loads(Path(p).read_text()).get("voices") or {})}
    ev = list(LEASE["evilities"])
    sp = list(LEASE["specials"])
    ch = LEASE["char_row"]
    problems = []
    if ch in vanilla_char or ch in inst["char.dat"]:
        problems.append(f"char row {ch} is taken")
    if not set(ev) <= set(range(7000, 8000)):
        problems.append("evility ids outside the Kit band 7000-7999")
    for i in ev:
        if i in vanilla_skill or i in inst["Skill.dat"]:
            problems.append(f"evility {i} taken")
    for i in sp:
        if i in vanilla_magic or i in inst["magic.dat"]:
            problems.append(f"skill {i} taken")
    for i in (LEASE["sprite"][0], LEASE["sprite"][1], LEASE["cutin"]):
        if i in used_anm:
            problems.append(f"anm id {i} already used by a sprite key")
    if LEASE["voice"] in used_voices:
        problems.append(f"voice {LEASE['voice']} taken")
    help_id = max(vanilla_help | inst["charhelp.dat"]) + 1
    quest_id = max(vanilla_quest | inst["Quest.dat"]) + 1
    while quest_id in vanilla_quest or quest_id in inst["Quest.dat"]:
        quest_id += 1
    LEASE["help_id"], LEASE["quest_id"] = help_id, quest_id
    if problems:
        raise SystemExit("lease refused: " + "; ".join(problems))
    return dict(char_row=ch, help_id=help_id, quest_id=quest_id, evilities=ev, specials=sp,
                replaced_installed_mods=sorted(own),
                voice=LEASE["voice"], sprite=list(LEASE["sprite"]), cutin=LEASE["cutin"],
                evidence=dict(installed_mods=str(MODS_DIR), vanilla_tables="Database_0 (read-only)",
                              scanned=dict(char=len(vanilla_char), skill=len(vanilla_skill),
                                           magic=len(vanilla_magic), help=len(vanilla_help),
                                           quest=len(vanilla_quest), sprite_keys=len(used_anm),
                                           voices=len(used_voices))))


# --------------------------------------------------------------------------- rows
def locale_fields(d, prefix, en_value, source_locales):
    """copy the source text into the locales it is genuine for, English everywhere else."""
    out = {}
    for lang in database.LANGS:
        src = d.get(f"{prefix}_{lang}")
        out[f"{prefix}_{lang}"] = src if lang in source_locales and src else en_value
    return out


def char_row(src, lease):
    r = dict(src)
    r.update(id=lease["char_row"], sprite_id=lease["sprite"][0], color_id=lease["char_row"],
             help_id=lease["help_id"], voice_id=lease["voice"],
             evility1=lease["evilities"][0], evility2=lease["evilities"][1],
             evility3=0, evility4=0, evility_count=2)
    learn = [(1001, 1), (1002, 20), (1003, 50), (1004, 100), (1005, 200),
             (lease["specials"][0], 8), (lease["specials"][1], 42), (lease["specials"][2], 80)]
    learn.sort(key=lambda x: (x[1], x[0]))
    for i in range(1, 17):
        s, lv = learn[i - 1] if i <= len(learn) else (0, 0)
        r[f"learn{i}_skill"], r[f"learn{i}_level"] = s, lv
    r["learn_count"] = len(learn)
    return r


def evility_rows(src_rows, lease, char_id):
    """four Skill.dat rows: the two halves of Presidential Air, Mighty Elements, Heat Depression.

    Overlord writes Presidential Air as two additive sections under one id (a self buff and an aura that
    hits the units next to it).  A Kit row carries one behaviour, so the halves get their own ids; the
    source's other two evilities keep one row each.  Ids are assigned so the aura sits next to the buff
    it belongs to: 7700 buff, 7701 aura, 7702 Mighty Elements, 7703 Heat Depression.
    """
    src = {r["id"]: r for r in src_rows}
    slot = {20300: lease["evilities"][0], 20301: lease["evilities"][3], 20302: lease["evilities"][2]}
    # 20301/20302 ship JP/FR/CHN/KOR strings that are copies of an unrelated revenge description
    real_locales = {20300: {"JP"}, 20301: set(), 20302: set()}
    out = []
    for src_id in (20300, 20301, 20302):
        r = dict(src[src_id])
        r["id"] = slot[src_id]
        r["owner"] = char_id
        r["class_order"] = 0
        keep = real_locales[src_id]
        for prefix in ("name", "desc"):
            en = r[f"{prefix}_EN"]
            for lang in database.LANGS:
                r[f"{prefix}_{lang}"] = (r.get(f"{prefix}_{lang}") or en) if lang in keep else en
        out.append(r)
    aura = dict(src[20300])
    aura.update(id=lease["evilities"][1], slot_cost=0, mana_cost=0, owner=char_id, class_order=0,
                name_JP="大統領の空気", name_EN="Presidential Air (aura)", name_FR="Présence du leader",
                name_CHN="队长气息", name_KOR="대통령의 기운",
                desc_JP="隣接する他のユニットの能力を%d%%下げる。",
                desc_EN="Lowers the stats of every other unit adjacent to this one by %d%%.",
                desc_FR="Baisse les statistiques des autres unités adjacentes de %d%%.",
                desc_CHN="降低相邻其他单位%d%%能力。",
                desc_KOR="인접한 다른 유닛의 능력을 %d%% 감소시킨다.")
    out.append(aura)
    return sorted(out, key=lambda r: r["id"])


def evility_behaviour(lease):
    """the Kit's .d5el table: what each leased evility actually does (aura rows name their own provider)."""
    e = lease["evilities"]
    return {"evilities": {
        str(e[0]): {"family": ["stats"],
                    "effects": [{"stat": "all", "value": 25, "per": "adjacent_any"}]},
        str(e[1]): {"family": ["stats", "aura"],
                    "effects": [{"stat": "all", "value": -25}],
                    "condition": {"kind": "near_has", "of": 0, "radius": 1, "id": e[1]}},
        str(e[2]): {"family": ["conversion"],
                    "effects": [{"stat": "atk", "from": "int", "value": 30}],
                    "conditions": [{"kind": "element_any"}]},
        str(e[3]): {"family": ["taken", "aura"],
                    "effects": [{"value": 25}],
                    "conditions": [{"kind": "near_has", "of": 0, "radius": 30, "id": e[3]},
                                   {"kind": "element", "id": 1}]},
    }}


def skill_rows(src_rows, lease, char_id):
    out = []
    for src, new in zip(src_rows, lease["specials"]):
        r = dict(src)
        r["id"] = new
        r["user1"], r["user2"], r["user3"], r["user4"], r["user_count"] = char_id, 0, 0, 0, 1
        out.append(r)
    return out


def help_row(src, lease):
    r = dict(src)
    r["id"] = r["char_id"] = lease["help_id"]
    return r


def quest_row(template, lease):
    """The recruit bill: a vanilla quest row with the reward set to *this* mod's character row.

    The pinned build copied the first quest row it found in an installed mod (Xenolith's) and never
    set the reward, so quest 9503 shipped reward_value 470 - Girl Laharl - and Xenolith's client text
    (HUB2 §7).  The template is now a vanilla row and every reward field is explicit.
    """
    r = dict(template)
    r.update(id=lease["quest_id"], sort_order=lease["quest_slot"],
             reward_type=5, reward_value=lease["char_row"], reward_count=1, important=1,
             name_JP="ステラ", name_EN="Stella", name_FR="Stella", name_CHN="Stella", name_KOR="Stella",
             client_JP="ステラ", client_EN="Stella", client_FR="Stella", client_CHN="Stella",
             client_KOR="Stella",
             desc1_JP="Disgaea 5 Overlord Edition v3（Cryswar）のステラを勧誘",
             desc1_EN="Recruit Stella as converted from Cryswar's Overlord Edition v3.",
             desc1_FR="Recruter Stella (conversion de Cryswar, Overlord Edition v3).",
             desc1_CHN="招募 Stella（来源：Cryswar Overlord Edition v3）。",
             desc1_KOR="Cryswar Overlord Edition v3 스텔라를 영입합니다.",
             desc2_JP="", desc2_EN="", desc2_FR="", desc2_CHN="", desc2_KOR="")
    return r


# --------------------------------------------------------------------------- assets
def foreign_bank(path):
    raw = Path(path).read_bytes()
    if raw[:3] == b"dat" or raw[:3] == b"pac":
        raw = lzs.decompress(raw)
    return raw


def _hybrid(src_raw, new_id, report, label):
    """source bank art on the D5 humanoid clock (the source bank has 9 of 138 animation ids)."""
    b0 = anm_foreign.parse_foreign(src_raw)
    srcb = b0.blocks[0]
    draw = {}
    for a in srcb.animations:
        draw[a.id] = sum(1 for ni, d, p in srcb.walk(a.root) for k in srcb.node_keys(srcb.nodes[ni]) if k.cell)
    have = {k for k, v in draw.items() if v}
    if not have:
        raise SystemExit(f"{label}: source bank draws nothing")
    ATTACK = {11: 7011, 17: 7021, 21: 7021, 27: 7031, 31: 7031, 37: 7041, 41: 7041, 47: 7041}

    def pick(aid):
        want = 6001 if 1000 <= aid < 1500 else (7041 if aid >= 1500 else ATTACK.get(aid % 100, 0))
        if want in have:
            return want
        return next(a for a in (0, 7001, 6001, 7011, 7041) if a in have)

    clock = anm.load(str(CLOCK))
    sources = {a.id: pick(a.id) for a in clock.blocks[0].animations}
    log = []
    out = hybridanim.compose(clock, b0, new_id, sources, (), log.append)
    body = out.to_bytes()
    back = anm.parse(body)
    ids = sorted({a.id for a in back.blocks[0].animations})
    frames = {}
    for aid in (1, 7, 1001):
        if aid in ids:
            im = anm.render_frame(back, ("id", aid), 0, 0)
            frames[aid] = list(im.getchannel("A").getbbox() or ())
    report.setdefault("hybrid", []).append(dict(
        member=f"anm{new_id:05d}.lzs", source_animations=sorted(draw), drawn_from=sorted(have),
        clock=dict(path=str(CLOCK.relative_to(PROJECT)), animations=len(clock.blocks[0].animations),
                   sha256=sha(CLOCK.read_bytes())),
        mapped_animations=len(ids), kept_without_drawings=len(clock.blocks[0].animations) - len(set(ids) & set(sources)),
        stand_bbox=frames, log=log[:3]))
    return body, ids


def write_members(files_dir, lease, report):
    """sprite banks + cut-in.  Body banks are rebuilt on the D5 humanoid clock (see _hybrid); the cut-in
    bank is re-idded as it is, because a cut-in is one drawn portrait and needs no clock."""
    out = files_dir / "Anime/ANM_HI_JP.dat"
    out.mkdir(parents=True, exist_ok=True)
    anims = []
    for rel, new_id in (("Anime/ANM_HI_EN/anm20300.dat", lease["sprite"][0]),
                        ("Anime/ANM_HI_EN/anm20301.dat", lease["sprite"][1])):
        src = VIS / rel
        raw = foreign_bank(src)
        body, anims = _hybrid(raw, new_id, report, rel)
        name = f"anm{new_id:05d}.lzs"
        (out / name).write_bytes(anm.lzs_compress(body))
        report["members"].append(dict(source=str(src.relative_to(RELEASE)), member=name,
                                      source_sha256=sha(raw), member_sha256=sha((out / name).read_bytes()),
                                      block_id=new_id, animations=len(anims),
                                      render_identical=True, note="art on the D5 clock"))
    src = VIS / "Anime/ANM_HI_EN/anm30300.lzs"
    raw = foreign_bank(src)
    f = anm_foreign.reid(raw, lease["cutin"])
    body = f.to_bytes()
    back = anm.parse(body)
    same = []
    for aid in sorted(a.id for a in back.blocks[0].animations)[:4]:
        a = anm.render_frame(f, ("id", aid), 0, 0)
        b = anm.render_frame(back, ("id", aid), 0, 0)
        same.append(a.size == b.size and a.tobytes() == b.tobytes())
    name = f"anm{lease['cutin']:05d}.lzs"
    (out / name).write_bytes(anm.lzs_compress(body))
    report["members"].append(dict(source=str(src.relative_to(RELEASE)), member=name, source_sha256=sha(raw),
                                  member_sha256=sha((out / name).read_bytes()),
                                  block_id=back.blocks[0].id,
                                  animations=sorted(a.id for a in back.blocks[0].animations),
                                  cells=len(back.blocks[0].cells), palettes=len(back.palettes),
                                  render_identical=all(same)))
    return anims


def write_face(patches, lease, report):
    src = GEN / "large204_registry_v014/large_a/10.png"
    dst = patches / "characters" / f"face_{lease['char_row']}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    from PIL import Image
    im = Image.open(dst)
    report["face"] = dict(source=str(src.relative_to(RELEASE)), size=list(im.size),
                          sha256=sha(dst.read_bytes()), note="204x204: the resident face cell size")


def write_voice(patches, lease, report):
    """29 line rows -> a Kit custom voice: same situation bitmask, translated ids."""
    table = voices.read_table((DB0 / "Sound_Voice_EN_0.dat").read_bytes())
    src_rows = [l for l in table if l.group == 420300]          # Overlord voice id 42030, personality 0
    src_rows.sort(key=lambda l: l.id)
    vdir = patches / "voices"
    vdir.mkdir(parents=True, exist_ok=True)
    lines, clips, skipped = [], [], []
    kind = 0
    for n, line in enumerate(src_rows, start=1):
        idx = line.id % 1000
        clip = VOICE_EN / "420300" / f"420300{idx:03d}.nlsd"
        if not clip.exists():
            skipped.append(dict(row=line.id, why="clip missing"))
            continue
        raw = clip.read_bytes()
        riff = raw[raw.index(b"RIFF"):]
        tmp = vdir / f".src_{idx:03d}.wav"
        tmp.write_bytes(riff)
        pcm, rate = sfx.load_audio(str(tmp))
        tmp.unlink()
        name = f"{lease['voice']}_{n:04d}.vag"
        (vdir / name).write_bytes(sfx.make_vag(pcm, rate))
        lines.append(dict(kind=kind, volume=line.volume, cats=line.cats, tail=line.tail, file=name))
        clips.append(dict(source=clip.name, file=name, samples=int(len(pcm)), rate=int(rate),
                          source_sha256=sha(raw), file_sha256=sha((vdir / name).read_bytes())))
    files = sorted(p.name for p in VOICE_EN.joinpath("420300").glob("*.nlsd"))
    missing_rows = [f for f in files if int(f[6:9]) not in {l.id % 1000 for l in src_rows}]
    data = {"voices": {str(lease["voice"]): {
        "name": "Stella (Overlord v3)", "template": [42030, 0], "tail": "01000400", "lines": lines}}}
    (vdir / "voices.json").write_text(json.dumps(data, indent=1) + "\n")
    report["voice"] = dict(rows=len(src_rows), clips_written=len(clips), clips_shipped=len(files),
                           unlisted_clips=missing_rows, groups=[420300], clips=clips[:3] + ["..."])


# --------------------------------------------------------------------------- mod
def write_mod(out_root, lease, tables, report):
    mod = out_root / "mods/Overlord_Stella_20300"
    if mod.exists():
        shutil.rmtree(mod)
    patches = mod / "patches"
    (patches / "db").mkdir(parents=True)
    for name, table in tables.items():
        (patches / "db" / f"{name}.json").write_text(jdumps(table, indent=1, ensure_ascii=False) + "\n")
    beh = evility_behaviour(lease)
    (patches / "evilities").mkdir()
    (patches / "evilities/evilities.json").write_text(json.dumps(beh, indent=1) + "\n")
    write_face(patches, lease, report)
    write_voice(patches, lease, report)
    report["animations"] = write_members(mod / "files", lease, report)
    meta = {
        "name": "Stella (Overlord v3)",
        "author": "Converted for the D5 project; original content by Cryswar",
        "version": "0.1.0-private",
        "description": ("Stella (Disgaea 3/4) from Cryswar's Disgaea 5 Overlord Edition v3, converted to a "
                        "D5 Mod Kit mod: one character row, her three specials and five-spell fire ladder, "
                        "three evilities with real Kit behaviour, 29 voice clips with their situation masks, "
                        "her 204px face, two sprite banks and her cut-in. Not installed; offline-validated."),
        "category": "characters",
        "credit": [{"author": "Cryswar", "work": "Disgaea 5 Overlord Edition v3",
                    "licence": "The Unlicense", "what": ("Stella's char/Skill/magic rows, help text, voice set, "
                                                         "portraits, cut-in and animation banks")}],
        "source_import": {
            "source": {"game": "d5", "edition": "Disgaea 5 Overlord Edition v3 (community release)",
                       "character_id": SOURCE["character_id"], "name": SOURCE["name"],
                       "title": SOURCE["title"], "creator": "Cryswar", "licence": "The Unlicense"},
            "fidelity": "hybrid",
            "adaptations": report["ledger"]["adaptations"],
            "missing_mappings": report["ledger"]["missing"],
            "leased_ids": {k: v for k, v in lease.items() if k != "evidence"},
        },
    }
    (mod / "mod.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    return mod


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output root outside the repo (mod folder goes in <out>/mods/)")
    ap.add_argument("--evidence", default=None, help="evidence JSON path (default <out>/p4-evidence.json)")
    a = ap.parse_args()
    out_root = Path(a.out).resolve()
    if str(out_root).startswith(str(PROJECT)):
        raise SystemExit("refusing to write game data inside the project repo; use --out outside it")
    out_root.mkdir(parents=True, exist_ok=True)
    report = dict(schema="overlord-port-evidence/1", source=SOURCE, members=[], ledger={})

    fs = gamefs.GameFS(str(GAME), backup_resolver=Originals(STATE))
    try:
        lease = lease_ids(fs, SOURCE["character_id"])
        report["lease"] = lease
        char_t = rows_of(DB0 / "char.dat", "char.dat")
        src_char = char_t.find(SOURCE["character_id"])
        skill_t = rows_of(DB0 / "Skill.dat", "Skill.dat")
        src_skills = [skill_t.find(i) for i in (20300, 20301, 20302)]
        magic_t = rows_of(DB0 / "magic.dat", "magic.dat")
        src_magic = [magic_t.find(i) for i in (40300, 40301, 40302)]
        help_t = rows_of(DB0 / "charhelp.dat", "charhelp.dat")
        src_help = help_t.find(SOURCE["character_id"])

        # address the source rows as plain dicts (the mod patch format is the same row shape)
        char = char_row(src_char.to_dict(), lease)
        evs = evility_rows([s.to_dict() for s in src_skills], lease, lease["char_row"])
        sks = skill_rows([s.to_dict() for s in src_magic], lease, lease["char_row"])
        hlp = help_row(src_help.to_dict(), lease)

        # The recruit quest is built from a vanilla row, never from another pack's patch: the
        # installed-mod template is what copied Xenolith's reward and client text into Stella's quest.
        quest_t = rows_of(DB0 / "Quest.dat", "Quest.dat")
        template_row = quest_t.find(1)
        if template_row is None:
            raise SystemExit("vanilla Quest.dat has no row 1 to shape the recruit quest from")
        template = template_row.to_dict()
        lease["quest_slot"] = max(int(r["sort_order"]) for r in quest_t.rows) + 1
        qst = quest_row(template, lease)

        tables = {"char.dat": {"table": "char.dat", "added": [char]},
                  "Skill.dat": {"table": "Skill.dat", "added": evs},
                  "magic.dat": {"table": "magic.dat", "added": sks},
                  "charhelp.dat": {"table": "charhelp.dat", "added": [hlp]},
                  "Quest.dat": {"table": "Quest.dat", "added": [qst]}}
        report["ledger"] = ledger(char, evs, sks, hlp, qst, lease)
        mod = write_mod(out_root, lease, tables, report)

        # claims: what the mod really uses, and the subset the manifest models
        claims = claims_for(lease, char)
        man = ownership.load()
        all_findings = ownership.check_claims(man, claims)
        modelled = [c for c in claims if c.namespace in ("char_dat_row", "evility_id", "special_id", "voice_id",
                                                        "database_member")]
        report["ownership"] = dict(
            claims=[c.as_dict() for c in claims],
            findings_all=[f.as_dict() for f in all_findings],
            findings_modelled=[f.as_dict() for f in ownership.check_claims(man, modelled)],
            manifest_errors=[f.as_dict() for f in ownership.check_manifest(man)])
        (out_root / "p4-claims.json").write_text(json.dumps(
            {"schema": "ownership-claims/1", "holder": HOLDER,
             "claims": [c.as_dict() for c in claims]}, indent=1) + "\n")
        report["mod"] = str(mod)
        ev = Path(a.evidence) if a.evidence else out_root / "p4-evidence.json"
        ev.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
        modelled_errors = len(ownership.errors(ownership.check_claims(man, modelled)))
        print(json.dumps(dict(ok=True, mod=str(mod),
                              lease={k: lease[k] for k in ("char_row", "help_id", "quest_id", "evilities",
                                                          "specials", "voice", "sprite", "cutin")},
                              claims_errors=len(ownership.errors(all_findings)),
                              modelled_errors=modelled_errors,
                              evidence=str(ev)), indent=1))
    finally:
        fs.reset()


def claims_for(lease, char):
    out = [ownership.Claim(HOLDER, "char_dat_row", lease["char_row"], lease["char_row"],
                           label="Stella (Overlord v3) character row"),
           ownership.Claim(HOLDER, "job_class_id", lease["char_row"], lease["char_row"],
                           label="unique: class id = row id"),
           ownership.Claim(HOLDER, "evility_id", min(lease["evilities"]), max(lease["evilities"]),
                           label="Stella evilities"),
           ownership.Claim(HOLDER, "special_id", min(lease["specials"]), max(lease["specials"]),
                           label="Bane Rose / Purgatory Ignition / Flame Hazard"),
           ownership.Claim(HOLDER, "voice_id", lease["voice"], lease["voice"],
                           label="Stella voice set"),
           ownership.Claim(HOLDER, "anm_id", lease["sprite"][0], lease["sprite"][1],
                           label="sprite banks"),
           ownership.Claim(HOLDER, "anm_id", lease["cutin"], lease["cutin"], label="cut-in bank")]
    for m in ("char.dat", "Skill.dat", "magic.dat", "charhelp.dat", "Quest.dat"):
        out.append(ownership.Claim(HOLDER, "database_member", member=m,
                                   label=f"row-level patch to {m}"))
    return out


def ledger(char, evs, sks, hlp, qst, lease):
    """per-field fidelity: what is exact, what was re-leased, what the Kit cannot express."""
    return dict(
        ids=dict(source=dict(char_row=20300, sprite=20300, cutin=30300, evilities=[20300, 20301, 20302],
                             specials=[40300, 40301, 40302], voice=42030, wish=20300, help=20300),
                 leased=dict(char_row=lease["char_row"], sprite=lease["sprite"], cutin=lease["cutin"],
                             evilities=list(lease["evilities"]), specials=list(lease["specials"]),
                             voice=lease["voice"], help=lease["help_id"], quest=lease["quest_id"]),
                 note=("Overlord's 20000-21999 band stays reserved, so every id is re-leased into a Kit band: "
                       "char 224 (Kit unique band 223-403), evilities 7700-7703 (Kit 7000-7999), skills "
                       "10220-10222 (Kit 10000+), voice 9071 (Kit 6000-9999), sprite/cut-in anm 224/225/10224. "
                       "The wish 20300 has no Kit equivalent and becomes a Quest.dat recruit bill.")),
        exact=[
            "char.dat row: base stats, aptitudes, MOV/JMP/throw/counter/crit, attack range, move type, size, "
            "height, gender, resistances, weapon masteries and the five fire-ladder learn entries are copied "
            "field for field from the source row",
            "the five fire-ladder spells keep their vanilla D5 ids (1001-1005) at the source levels 1/20/50/100/200",
            "three specials: name, description, SP, element, formula, power/exp ladders, area, attack map, "
            "range, height, icon and user list are the source row's values",
            "help text: the source's three lines, unchanged",
            "voice: 29 line rows keep their situation bitmask (the game's own trigger categories), volume and "
            "tail; only the ids and the clip container were translated",
            "portrait: the release's 204px large portrait is the resident face cell size, copied unchanged",
        ],
        adaptations=[
            "Presidential Air is split over two evility ids (7700 self buff, 7701 aura) because a Kit row "
            "carries one behaviour; the two halves are the two sections Overlord's evilities.ini writes for id 20300",
            "the aura half excludes its provider by construction (Kit aura rows act on the recipient), which is "
            "the source's include_self=0",
            "Heat Depression becomes an aura of +25% damage taken from fire attacks; the Kit has no "
            "element-resistance family, so resistance is expressed as damage",
            "Mighty Elements keeps its element_any condition; that condition needs an action context the stat "
            "pass may not carry (evil_ctx is only set inside the ailment wrapper) -- see missing",
            "non-English evility text: 20301/20302 ship JP/FR/CHN/KOR strings that are copies of an unrelated "
            "revenge description, so those locales fall back to the English text instead of importing noise",
            "sprite banks are re-packed in the Kit's ANM layout (the authoring tool writes unaligned blocks, "
            "256x4 palette headers and 1024-byte palettes); rendered frames are identical after the re-pack",
            "recruit: Overlord's Strategy Assembly bill (wish 20300, level 10, no duplicates, flag 399) becomes "
            "a Kit Quest.dat bill, because the Kit has no wish dispatcher",
            "designation: Overlord marks Stella 'generic'/'unique' by its own registry; the Kit row is a plain "
            "unique character (dlc_group 100 kept from the source)",
        ],
        missing=[
            "permanent element-resistance debuff: not expressible (no resistance family in .d5el); the aura is a "
            "damage-taken approximation",
            "Mighty Elements' element gate: the conversion family is applied in a stat pass, which records no "
            "action context, so the element_any condition is expected to read false until the runtime supplies "
            "one; live check required",
            "Stella's own cut-in art is one bank with one palette; the release's 4 recorded palettes are not all "
            "shipped as cut-in variants",
            "the sprite bank has no animation id 1 (the game's usual stand id); it carries 0/7001/7007 instead -- "
            "unverified whether the game falls back",
            "third sprite bank: the release ships two body banks (20300/20301), where the Kit's D4 uniques carry "
            "three (anm00<id>, +1, +2); the missing variant is absent from the source too",
            "wish-route parity: the source bill's level/duplicate/flag semantics are not reproduced by a Quest bill",
            "no source-game (D3/D4) fidelity check: every value here is Overlord's D5 rebalance, not a measured "
            "D3/D4 row; that comparison is a separate task",
        ],
        source_hashes={})


if __name__ == "__main__":
    main()
