"""DRPG 3-character sample: build three Kit special characters from the RPG tables (offline).

Each character gets a char.dat row (new unique id leased from the ownership manifest's kit band), the
appearance of its Disgaea RPG unit drawn with a vanilla D5 animation set, its RPG looks as outfit rows, a
learnset of the D5 skills the RPG command map names, and the RPG leader skill as an evility with real Kit
behaviour (patches/evilities/evilities.json, the `.d5el` table).

Nothing is installed, nothing is written into the game or the installed kit: the game data is read from a
plain copy of the (pre-mod) game folder, and every write is checked to land inside `--out`.

    python3 tools/build_drpg_sample.py --game "<game copy>" --drpg-root "<DRPG sprite root>" --out <dir>

Output: <out>/mods/<mod id>/..., <out>/drpg-sample-claims.json, <out>/drpg-sample-receipt.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from d5lib import importcore  # noqa: E402

DB0 = "Database/Database_0.dat/"

# ----------------------------------------------------------------------------------------------- the sample
# Character rows are NOT pinned here: a build allocates them from the kit's own free-id pool inside the
# manifest's kit band (ROW_BAND 223..403), after subtracting every id that any installed mod folder claims
# (d5lib.modclaims; `--mods-root`), so a pack cannot take a row another mod already has.  The first pinned
# values, 233-235, were both wrong: 233 is D4_Unique_180's row and 491-495 were DRPG_Outfits_Majorita's
# outfit slots (DUPFIX-REPORT.md).  Sprite blocks come from `sprite_blocks` in the same band.  Evility ids
# 7100-7121 are in the kit's 7000-7999 evility band and are checked with the other claims.
SPECS = [
    dict(
        mod="DRPG_Sample_Melodia", name="Melodia", rpg=106, unit=106, row=None, sprite=None,
        template=40,                      # 'moves like' Seraphina: a humanoid with a learned own-pose map
        title="Musical Princess",
        skills=[(1501, 24), (10012, 24), (10582, 24), (10592, 24), (10712, 24), (10742, 24)],
        desc=("A princess from a musical world who waits for her prince.",
              "Sings and dances: her song-line skills are D5's own nearest skills.",
              "From Disgaea RPG (character 106)."),
        quest=dict(title="A Song from Beyond", client="Melodia",
                   text="A princess from a musical world wants to join your army."),
        outfits=[(211, "Priestess"), (270, "School Uniform"), (296, "Beach"),
                 (423, "Princess Kaguya")],
        evilities={7100: dict(
            family=["stats", "aura"],
            effects=[{"stat": "spd", "value": 7}],
            condition={"kind": "near_has", "of": 1, "radius": 30, "id": 7100},   # 30 panels ~ the whole map
            note="RPG leader skill 1061: party SPD +7%")},
        leader="1061 -> 7100 (party SPD +7%)",
    ),
    dict(
        mod="DRPG_Sample_Citri", name="Citri Smart", rpg=311, unit=311, row=None, sprite=None,
        template=40, title="Apothecary of House Smart",
        skills=[(10742, 24), (1503, 24)],
        desc=("The Smart family's pharmacist, a gunner who brews her own water rounds.",
              "From Disgaea RPG (character 311).", ""),
        quest=dict(title="A Pharmacist's Request", client="Citri Smart",
                   text="Citri Smart needs a battlefield that tests her remedies."),
        outfits=[],                        # RPG gives her one look
        evilities={7110: dict(
            family=["stats", "aura"],
            effects=[{"stat": "all", "value": 16}],
            condition={"kind": "near_has", "of": 1, "radius": 30, "id": 7110},   # 30 panels ~ the whole map
            note="RPG leader skill 3111: party non-HP base stats +16%")},
        leader="3111 -> 7110 (party stats +16%, exact stat set/scope)",
    ),
    dict(
        mod="DRPG_Sample_Noel", name="Noel", rpg=55, unit=55, row=None, sprite=None,
        template=40, title="Santa in Training",
        skills=[(1403, 24), (10012, 24), (10742, 24), (1503, 24)],
        desc=("A magician training to be Santa Claus.",
              "Her leader skill heals the party every round; the Kit gives her",
              "a self heal and an adjacent-ally damage guard instead (see SAMPLE-REPORT)."),
        quest=dict(title="A Present for the Netherworld", client="Noel",
                   text="Noel wants to hand out presents on a real battlefield."),
        outfits=[(208, "Dark Santa"), (263, "Casualwear")],
        evilities={
            7120: dict(family="regen", effects=[{"stat": "hp", "value": 8}],
                       note="RPG leader skill 551: 8% of max HP per round - SELF only; "
                            "the Kit's regen family has no party/aura scope (gap)"),
            7121: dict(family=["taken", "aura"], effects=[{"value": -15}],
                       condition={"kind": "near_has", "of": 1, "radius": 30, "id": 7121},
                       note="RPG leader skill 554: party takes -15% damage from normal attacks"),
        },
        leader="551 (party regen) + 554 (party damage guard -> 7121 aura)",
    ),
]

CREDIT = [{"author": "Cryswar", "work": "Disgaea 5 Overlord Edition (reference designs)",
           "licence": "The Unlicense",
           "what": "effect vocabulary for the aura/regen rows; no code or data copied into this mod"}]


# ----------------------------------------------------------------------------------------------- guards
def offline_guard(allowed: Path):
    """Writes only inside `allowed`; no subprocess, no network (the kit's Zig build is not needed here)."""
    def check(path):
        if isinstance(path, int):
            return
        p = Path(os.fsdecode(path)).resolve()
        if not (p.is_relative_to(allowed) or p.is_relative_to(KIT)):
            raise RuntimeError("offline sample build refused write outside output/worktree: " + str(p))

    def audit(event, values):
        if event == "open":
            path, mode, flags = values
            if (mode and any(c in mode for c in "wax+")) or flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                check(path)
        elif event == "os.mkdir" and not isinstance(values[0], int) and os.path.isdir(os.fsdecode(values[0])):
            return
        elif event in ("os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"):
            check(values[0])
        elif event in ("os.rename", "os.link"):
            check(values[0])
            check(values[1])
        elif event == "os.symlink":
            check(values[1])                       # the link target is only read
        elif event in ("subprocess.Popen", "os.system", "socket.connect", "socket.bind"):
            raise RuntimeError("offline sample build blocks subprocess/network: " + event)
    sys.addaudithook(audit)


def drpg_root(root: Path) -> Path:
    """The DRPG sprite root in the kit's `Characters/Sprites/{front,back,wait_front,wait_back}` layout.

    A decoded-client tree (`tex/atlas/chara/battle/...`, faces in `tex/images/chara/face`) is linked into
    `--out` once, so the kit's readers see the layout they expect.
    """
    from d5lib import drpgsource
    found = drpgsource.looks_like_drpg_root(str(root))
    if found:
        return Path(found)
    battle = root / "atlas/chara/battle"
    if not (battle / "front").is_dir():
        raise SystemExit(f"no DRPG sprites under {root} (need Characters/Sprites or atlas/chara/battle)")
    staged = Path(SAMPLE_OUT) / "drpg-assets" / "DRPG Assets (Sample)"
    pairs = (("Sprites/front", "front"), ("Sprites/back", "back"), ("Sprites/wait_front", "wait_front"),
             ("Sprites/wait_back", "wait_back"))
    for sub, src in pairs:
        d = staged / "Characters" / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in sorted((battle / src).glob("*.png")):
            if "_" in f.stem:                      # the *_inversion recolour banks are not unit sheets
                continue
            target = d / f.name
            if not target.exists():
                os.symlink(f, target)
    for sub, src in (("Icons", "images/chara/face"), ("Cut-Ins", "images/chara/ci")):
        d = staged / "Characters" / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in sorted((root / src).glob("*.png")):
            target = d / f.name
            if not target.exists():
                os.symlink(f, target)
    return staged


# ----------------------------------------------------------------------------------------------- patches
def evility_row(src, evid, char_id, name, desc):
    """A Skill.dat row for our own evility: no native effect (effect_group 0), the `.d5el` table does the work."""
    from d5lib import textfmt
    r = dict(src)
    desc = textfmt.format_text(desc)
    for lang in ("JP", "EN", "FR", "CHN", "KOR"):
        r[f"name_{lang}"] = name
        r[f"desc_{lang}"] = desc
    r.update(id=evid, slot_cost=0, mana_cost=0, owner=char_id, kind=2, effect_group=0,
             value1=0, value2=0, shop_rank=0, class_order=0)
    return r


def patch_char(mod, row_id, vanilla, **fields):
    """The row create_drpg_character wrote: an appended row carries its id, an in-place row does not (the
    patch stores changed fields only), so the in-place case is matched through the vanilla row at that index."""
    patch = mod.load_patch("db", "char.dat.json") or {}
    hit = next((r for r in patch.get("added") or [] if int(r.get("id", -1)) == row_id), None)
    if hit is None:
        for idx, r in (patch.get("rows") or {}).items():
            vid = vanilla.rows[int(idx)]["id"]
            if int(r.get("id", vid)) == row_id:
                hit = r
                break
    if hit is None:
        raise RuntimeError(f"char.dat patch has no row {row_id}")
    hit.update(fields)
    mod.save_patch("db", "char.dat.json", patch)
    return hit


def add_skill_rows(mod, rows):
    patch = mod.load_patch("db", "Skill.dat.json") or {"table": "Skill.dat", "added": []}
    have = {int(r["id"]) for r in patch.get("added") or []}
    patch.setdefault("added", []).extend(r for r in rows if int(r["id"]) not in have)
    patch["added"].sort(key=lambda r: int(r["id"]))
    mod.save_patch("db", "Skill.dat.json", patch)


# rows the D4 unique pack and the older cross-imports already hold (bands are manifest-owned by the kit)
D4_ROWS = {70, 170, 180, 190, 210, 220, 230, 240, 250, 300, 310, 320, 340, 350, 360, 393, 396,
           410, 420, 430, 440, 450, 460, 470, 490, 510, 520, 610}


def sprite_blocks(fs, count, low=223, high=404):
    """`count` blocks of three consecutive free sprite numbers in [low, high).

    A sprite block is (N, N+1, N+2): the body, its copy and the small standing picture; the portrait/cut-in
    bank is N + 10000.  A number is free when none of those keys is taken by the game (sprites.used_sprite_numbers).
    """
    from d5lib import sprites
    used = sprites.used_sprite_numbers(fs)
    free = {i for i in range(low, high)
            if not ({i, i + 1, i + 2, i + 10000, i + 10001} & used) and i not in D4_ROWS}
    out, i = [], low
    while i + 2 < high and len(out) < count:
        if {i, i + 1, i + 2} <= free:
            out.append(i)
            i += 3
        else:
            i += 1
    if len(out) < count:
        raise RuntimeError(f"only {len(out)} free sprite blocks in {low}..{high}, needed {count}")
    return out


def free_slots(mods_root: Path) -> dict:
    """outfit slots and sprite numbers already taken by the mods installed next to the game (read only).

    Char.dat ids come from d5lib.modclaims, which reads every installed mod's `patches/db` (added rows by
    id and row patches), not only the files this builder happens to write -- the 491-495 collision was
    two mods' outfit rows landing on the same ids because only one pack was ever looked at.
    """
    slots, sprites = set(), set()
    if not mods_root.is_dir():
        return dict(slots=slots, sprites=sprites)
    for d in sorted(mods_root.iterdir()):
        if not d.is_dir():
            continue
        p = d / "patches/outfits/outfits.json"
        if p.is_file():
            for a, b in (json.loads(p.read_text()).get("pairs") or []):
                slots.update((int(a), int(b)))
        for f in d.rglob("anm*.lzs"):
            n = f.name[3:8]
            if n.isdigit():
                sprites.add(int(n))
    from d5lib import modclaims
    slots |= {rid for ids in modclaims.scan_mods(str(mods_root)).added.values() for rid in ids}
    return dict(slots=slots, sprites=sprites)


ROW_BAND = (223, 403)          # the manifest's kit band for unique character rows (char_dat_row 223-403)


def take_rows(pool, count, first=ROW_BAND[0], last=ROW_BAND[1], spacing=3):
    """`count` ids out of an ordered pool of free ids, inside [first, last], at least `spacing` apart.

    Rows are kept three apart because a unique's sprite set is row .. row + 2 in the manifest's shape;
    a row closer than that would share a keyed anm number with its neighbour.
    """
    out = []
    for i in pool:
        if not first <= i <= last or i in out:
            continue
        if all(abs(i - j) >= spacing for j in out):
            out.append(i)
        if len(out) == count:
            return out
    raise RuntimeError(f"only {len(out)} free rows in {first}..{last} (need {count}, {spacing} apart)")


def allocate_rows(fs, taken, count):
    """Character rows: the kit's own unique-id pool (`slots.unique_pool`: dummy families first, then free
    ids whose keyed anm numbers are the game's own), minus everything the installed mods already claim."""
    from d5lib import slots as slotlib
    pool = [i for i in slotlib.unique_pool(fs) if i not in taken]
    return take_rows(pool, count)


def allocate_outfit_slots(fs, taken, count, rows=()):
    """Outfit slots: the same free pool, three apart from each other and from every allocated row.

    The game's empty dummy families come first in the pool, but the installed outfit mods have taken
    almost all of 470-499 and 950-999 (149 outfit rows), so this can fall back to the ascending free
    ids -- whatever comes out is still absent from vanilla, from every installed mod and from the
    kit's used-anm set.
    """
    from d5lib import slots as slotlib
    blocked = {j for r in rows for j in (r - 2, r - 1, r, r + 1, r + 2)}
    pool = [i for i in slotlib.unique_pool(fs) if i not in taken and i not in blocked]
    out = []
    for i in pool:
        if all(abs(i - j) >= 3 for j in out):
            out.append(i)
        if len(out) == count:
            return out
    raise RuntimeError(f"only {len(out)} free outfit slots, needed {count}")



# ----------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, type=Path, help="read-only copy of the game folder")
    ap.add_argument("--drpg-root", required=True, type=Path,
                    help="DRPG sprites: Characters/Sprites layout or a decoded client tree (tex/)")
    ap.add_argument("--out", required=True, type=Path, help="output root outside the repo")
    ap.add_argument("--mods-root", type=Path, default=None,
                    help="installed mods folder, read only, so outfit slots/sprite numbers do not collide")
    ap.add_argument("--only", default=None, help="comma separated RPG character ids")
    args = ap.parse_args()

    out = args.out.resolve()
    if not out.parent.is_dir():
        raise SystemExit("output parent must exist")
    if str(out).startswith("/Volumes/Data/Projects/D5"):
        raise SystemExit("refusing to write outside the scratch area")
    out.mkdir(parents=True, exist_ok=True)
    global SAMPLE_OUT
    SAMPLE_OUT = str(out)
    offline_guard(out)
    tempfile.tempdir = str(out)

    from d5lib import (drpgsource, modsys, outfits, slots, sprites, evility, ownership, database, gamefs,
                       drpg, modclaims)
    drpg.ROOTS[:] = [str(drpg_root(args.drpg_root))]
    # kit caches stay with this build
    sprites.CACHE_DIR = str(out / "cache")
    fs = gamefs.GameFS(str(args.game))
    vanilla_skill = {r["id"]: r for r in database.load_table("Skill.dat", fs.read(DB0 + "Skill.dat")).rows}
    vanilla_char = database.load_table("char.dat", fs.read(DB0 + "char.dat"))
    taken = free_slots(args.mods_root) if args.mods_root else dict(slots=set(), sprites=set())
    installed_scan = modclaims.scan_mods(str(args.mods_root)) if args.mods_root else modclaims.Scan()
    # an installed mod that *patches* a row claims that row's id too (row index -> id through vanilla)
    for index in installed_scan.patched.get("char.dat", {}):
        if int(index) < len(vanilla_char.rows):
            taken["slots"].add(int(vanilla_char.rows[int(index)]["id"]))
    used_slots = set(taken["slots"])
    used_sprites = set(taken["sprites"])

    specs_needed = [s for s in SPECS if not args.only or s["rpg"] in {int(x) for x in args.only.split(",")}]
    blocks = sprite_blocks(fs, len(specs_needed) + sum(len(s["outfits"]) for s in specs_needed))
    # character rows and outfit slots are allocated, never hardcoded: both come from the kit's own free-id
    # pool minus every id an installed mod folder already claims (d5lib.modclaims)
    char_rows = allocate_rows(fs, taken["slots"], len(specs_needed))
    outfit_slot_list = allocate_outfit_slots(fs, taken["slots"] | set(char_rows),
                                             sum(len(s["outfits"]) for s in specs_needed), rows=char_rows)
    receipt_alloc = dict(char_rows=list(char_rows), outfit_slots=list(outfit_slot_list))
    for spec in specs_needed:
        spec["row"] = char_rows.pop(0)
        spec["sprite"] = blocks.pop(0)
    outfit_sprites = iter(blocks)
    outfit_slots = iter(outfit_slot_list)
    specs = [s for s in SPECS if not args.only or s["rpg"] in {int(x) for x in args.only.split(",")}]
    receipt: dict = dict(schema="drpg-sample-build/1", game=str(args.game), drpg=str(drpg_root(args.drpg_root)),
                   drpg_roots=list(drpg.ROOTS), allocated=receipt_alloc,
                   mods_root=str(args.mods_root) if args.mods_root else None,
                   characters=[], skipped=[])
    claims = []
    try:
        for spec in specs:
            folder = out / "mods" / spec["mod"]
            if folder.exists():
                import shutil
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
            mod = modsys.Mod(str(folder))
            mod.meta.update({
                "name": f"{spec['name']} (DRPG sample)", "author": "D5 project (DRPG sample lane)",
                "version": "0.1.0-private", "category": "characters",
                "description": (f"{spec['name']} from Disgaea RPG (character {spec['rpg']}), built as a Kit "
                                f"special character: DRPG appearance on a D5 animation set, "
                                f"{len(spec['outfits'])} RPG looks as outfits, the RPG commands as D5 skills "
                                f"and the RPG leader skill as a Kit evility with real behaviour."),
                "credit": CREDIT,
                "source_import": {
                    "source": {"game": "drpg", "edition": "Disgaea RPG (JP client masters)",
                               "character_id": spec["rpg"], "name": spec["name"], "licence": "reference only"},
                    "fidelity": "hybrid",
                    "leased_ids": {"char_row": spec["row"], "sprite": spec["sprite"],
                                   "evilities": sorted(spec["evilities"])},
                    "yield_source": importcore.donor_yield(importcore.NO_YIELD_FIELD_NOTE.format("DRPG")),
                },
            })
            mod.save_meta()

            vanilla_char = database.load_table("char.dat", fs.read(DB0 + "char.dat"))
            if spec["row"] in {r["id"] for r in vanilla_char.rows}:
                raise RuntimeError(f"{spec['name']}: leased row {spec['row']} exists in vanilla char.dat")
            # the kit hands out the first free id; pin it to the leased character row first and to the shared
            # outfit-slot queue after it (free_slot asks the same allocator, once per outfit)
            first = [True]

            def pinned_ids(*a, **k):
                if first[0]:
                    first[0] = False
                    return [spec["row"]]
                return [next(outfit_slots)]

            slots.free_unique_ids = pinned_ids
            outfit_sprites_first = [True]

            def pinned_sprites(fs_, mod_):
                if outfit_sprites_first[0]:
                    outfit_sprites_first[0] = False
                    return spec["sprite"]
                return next(outfit_sprites)

            outfits._free_sprite = pinned_sprites

            t = {}
            import time
            t0 = time.time()
            res = outfits.create_drpg_character(
                fs, mod, 40, spec["template"], spec["unit"], spec["name"], spec.get("title"),
                [tuple(s) for s in spec["skills"]], spec.get("desc", ()), spec.get("quest"),
                log=lambda s: receipt.setdefault("log", []).append(s), stats_from=None)
            if int(res["id"]) != spec["row"]:
                raise RuntimeError(f"{spec['name']}: got char id {res['id']}, expected the leased {spec['row']}")
            t["character_s"] = round(time.time() - t0)

            # the evilities: Skill.dat rows owned by the character + their .d5el behaviour
            src_ev = vanilla_skill[1235]
            rows = [evility_row(src_ev, evid, spec["row"], f"{spec['name']} leader skill",
                                {"7100": "Party SPD up (RPG leader skill 1061)",
                                 "7110": "Party stats up (RPG leader skill 3111)",
                                 "7120": "Heals own HP each round (RPG leader skill 551)",
                                 "7121": "Party takes less damage (RPG leader skill 554)"}[str(evid)])
                    for evid in sorted(spec["evilities"])]
            add_skill_rows(mod, rows)
            ids = sorted(spec["evilities"])
            patch_char(mod, spec["row"], vanilla_char, evility1=ids[0],
                       evility2=ids[1] if len(ids) > 1 else 0,
                       evility3=0, evility4=0, evility_count=len(ids))
            behaviour = evility.load(mod)
            for evid, row in spec["evilities"].items():
                behaviour.setdefault("evilities", {})[str(evid)] = {k: v for k, v in row.items() if k != "note"}
            evility.save(mod, behaviour)

            # the RPG looks as outfits of this character
            built = []
            for uid, label in spec["outfits"]:
                t1 = time.time()
                try:
                    r = outfits.create_drpg_outfit(fs, mod, spec["row"], uid, label, template=spec["template"],
                                                   log=lambda s: None)
                except Exception as exc:                       # recorded, not hidden
                    built.append(dict(unit=uid, name=label, error=f"{type(exc).__name__}: {exc}"))
                    continue
                built.append(dict(unit=uid, name=label, slot=r["slot"], sprite=r["sprite"],
                                  cells=r["report"].get("cells"), missing=len(r["report"].get("missing", ())),
                                  seconds=round(time.time() - t1)))
                used_slots.add(r["slot"])
                used_sprites.update({r["sprite"], r["sprite"] + 1, r["sprite"] + 2})
            t["total_s"] = round(time.time() - t0)

            entry = dict(mod=spec["mod"], name=spec["name"], rpg=spec["rpg"], unit=spec["unit"],
                         char_row=spec["row"], sprite=spec["sprite"], evilities=ids,
                         leader=spec["leader"], outfits=built, seconds=t)
            receipt["characters"].append(entry)
            claims += claims_for(spec, built)

        man = ownership.load()
        findings = ownership.check_claims(man, claims)
        receipt["ownership"] = dict(claims=[c.as_dict() for c in claims],
                                    errors=[f.as_dict() for f in ownership.errors(findings)],
                                    findings=[f.as_dict() for f in findings],
                                    manifest_errors=[f.as_dict() for f in ownership.check_manifest(man)])
        (out / "drpg-sample-claims.json").write_text(json.dumps(
            {"schema": "ownership-claims/1", "holder": HOLDER, "claims": [c.as_dict() for c in claims]},
            indent=1) + "\n")
        # the gate the 491-495 collision needed: this pack's own claims against EVERY installed mod folder's,
        # with the mods this build replaces left out (the rebuild supersedes them, it does not join them)
        replaced = {s["mod"] for s in specs}
        installed_claims = [c for c in modclaims.claims(installed_scan, holder_prefix="installed")
                            if c.holder.split(":", 1)[1] not in replaced]
        built_claims = modclaims.claims(modclaims.scan_mods(str(out / "mods")))
        usage = ownership.check_usage(man, installed_claims + built_claims)
        # only what the pack is part of fails the build; duplicates between two *installed* mods are
        # recorded (they are DUPFIX-REPORT.md §3) but are not this pack's to fix
        mine = [f for f in ownership.errors(usage) if "mod:" in f.holder]
        theirs = [f for f in ownership.errors(usage) if "mod:" not in f.holder]
        receipt["duplicates"] = dict(installed_mods=len(installed_scan.mods),
                                     installed_claims=len(installed_claims),
                                     pack_claims=len(built_claims),
                                     errors=[f.as_dict() for f in mine],
                                     installed_conflicts=[f.as_dict() for f in theirs],
                                     findings=[f.as_dict() for f in usage])
        receipt["ok"] = not receipt["ownership"]["errors"] and not receipt["duplicates"]["errors"]
    finally:
        fs.reset()
    (out / "drpg-sample-receipt.json").write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k in ("ok", "characters", "skipped")},
                     indent=1, ensure_ascii=False)[:4000])
    return 0 if receipt.get("ok") else 1


HOLDER = "kit:DRPG_Sample"
# Outfit slots used to be pinned to [490..497].  They are allocated now (allocate_outfit_slots): that list
# collided with DRPG_Outfits_Majorita (489, 491-495) and DRPG_Outfits_Asagi (496, 497), and nothing in the
# builder could see it because only its own three mods were ever scanned.


def claims_for(spec, outfits=()):
    from d5lib import ownership
    out = [ownership.Claim(HOLDER, "char_dat_row", spec["row"], spec["row"],
                           label=f"{spec['name']} (DRPG {spec['rpg']}) character row"),
           ownership.Claim(HOLDER, "job_class_id", spec["row"], spec["row"], label="unique: class id = row id"),
           ownership.Claim(HOLDER, "anm_id", spec["sprite"], spec["sprite"] + 2, label="sprite + companion + icon"),
           ownership.Claim(HOLDER, "anm_id", spec["sprite"] + 10000, spec["sprite"] + 10000,
                           label="portrait / cut-in bank"),
           ownership.Claim(HOLDER, "evility_id", min(spec["evilities"]), max(spec["evilities"]),
                           label=f"{spec['name']} leader-skill evilities")]
    for o in outfits:
        if o.get("sprite") and not o.get("error"):
            out.append(ownership.Claim(HOLDER, "anm_id", o["sprite"], o["sprite"] + 2,
                                       label=f"{spec['name']} outfit {o['name']} sprite bank"))
            out.append(ownership.Claim(HOLDER, "anm_id", o["sprite"] + 10000, o["sprite"] + 10000,
                                       label=f"{spec['name']} outfit {o['name']} portrait"))
    for m in ("char.dat", "Skill.dat", "charhelp.dat", "Quest.dat"):
        out.append(ownership.Claim(HOLDER, "database_member", member=m, label=f"row-level patch to {m}"))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
