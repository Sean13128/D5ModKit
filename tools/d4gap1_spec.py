#!/usr/bin/env python3
"""D4GAP1: write the live-acceptance install spec for the 9 NPC uniques + 7 classes (offline; nothing installed).

    python tools/d4gap1_spec.py OUT.json [--kit-worktree REL --kit-commit SHA]

Modelled on INSTALL4.json / D4INSTALL2.json.  All 16 folders are ADDITIONS (no installed copy).  Base = MAIN after
INSTALL4 and DRPG B1..B5 (161 + 144 = 305 entries, from tools make_drpg_batch_specs); the lane re-pins base.mods and the
exe at launch.  kitcode.commit is 'COORDINATOR-SETS' until the branch is merged.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Volumes/Data/Projects/D5")
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
BUILD = "Builds/D4GAP1-20261109"
NPC = [4390, 5301, 5305, 5306, 5307, 5308, 5309, 5310, 5388]
CLASSES = [1170, 2050, 2090, 2120, 2150, 2170]            # classes7 (2190 comes from class2190)
BASE_MODS = 305
MONSTER_BANKS = {"unique 5308 Arsailles": 833, "class 2050": 2260, "class 2090": 2300, "class 2120": 2330,
                 "class 2150": 2360, "class 2170": 2380, "class 2190": 2840}


def folders():
    return ([f"{BUILD}/npc9/d4/mods/D4_Unique_{n}" for n in NPC] +
            [f"{BUILD}/classes7/d4/mods/D4_Class_{n}" for n in CLASSES] +
            [f"{BUILD}/class2190/d4/mods/D4_Class_2190"])


def banks(paths):
    import hashlib
    from d5lib import anm
    rows = []
    for p in paths:
        folder = Path(p).name
        for f in sorted((ROOT / p / "files/Anime/ANM_HI_JP.dat").glob("anm*.lzs")):
            a = anm.load(str(f))
            rows.append({"bank": f"mods/{folder}/files/Anime/ANM_HI_JP.dat/{f.name}", "palettes": len(a.palettes),
                         "headers": len(a.palettes) + len(a.textures),
                         "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--kit-worktree", default="Local/Worktrees/integ-2026-11")
    ap.add_argument("--kit-commit", default="COORDINATOR-SETS")
    a = ap.parse_args(argv)
    spec = json.loads((ROOT / "Subprojects/Engine-Extensions/live-harness/pipeline/specs/D4INSTALL2.json").read_text())
    fl = folders()
    changed = subprocess.run(["git", "-C", str(KIT), "diff", "--name-only", "e7c919a", "HEAD", "--", "d5lib"],
                             capture_output=True, text=True).stdout.split()
    spec["lane"] = "D4GAP1"
    spec["build"] = f"{BUILD} (npc9 + classes7 + class2190)"
    spec["notes"] = (
        "D4GAP1 (prepared offline 2026-11-09, NOT run): ADD 16 folders, replace none: 9 NPC uniques (Senator Kojiro 4390, "
        "Chief 5301, Tromayer 5305, Baltis 5306, Garatea 5307, Arsailles 5308 [monster], Graceus 5309, Reprachon 5310, "
        "Psylos 5388; identity 18210-18290, art 646 653 656 823 826 833 836 843 846) + 7 D4 classes (1170, 2050, 2090, "
        "2120, 2150, 2170, 2190 on sprite family 2840). All gates in the importer run; check_used_ids 0 collisions vs "
        "everything not yet installed. Runs after INSTALL4 and DRPG B1..B5 (base.mods 305 assumes all kept; re-pin at "
        "launch). The D4 wheel gains 7 class pages entries (soak page below, derived with live_accept --derive-page d4). "
        "Soak page: the D4 wheel (LSHIFT+2), 18 class ids. Layer 2: recruit Tromayer (5305) via quest 437, read class "
        "u32 +0x2E04 (= 18230), palette u8 +0x2E2C (D4 bank 4 is rotated to slot 0, so palette 0), graphics id "
        "u16 +0x2E36 (= 656). Resident-placeholder check for every monster-kind entry (layer2.resident_placeholder). "
        "After a KEPT install run Tools/build_packs.py --write (pack display layer only). Saves: new quest slots "
        "782-790 are clear of every dirty slot in Local/save-backups/20261109-0511-D4INSTALL1c-holds-d4.")
    spec["re_pin_at_launch"] = ("RE-PIN: base.mods 305 assumes INSTALL4 and DRPG B1..B5 were kept; base.exe_sha256 is a "
                                "placeholder (every install rebuilds the exe). Read both from the live kit before the run.")
    spec["base"] = {"profile": "MAIN", "mods": BASE_MODS, "exe_sha256": "RE-PIN-AT-LAUNCH", "banks": {}}
    spec["kitcode"] = {"worktree": a.kit_worktree, "commit": a.kit_commit, "force": False, "runtime_core": False,
                       "modules": sorted(p.split("d5lib/", 1)[1] for p in changed)}
    spec["kitcode_note"] = ("kitcode.commit = the commit d4gap1 ends on once the coordinator merges it (set at launch). "
                            "modules = the d5lib files this branch changes; importer-only files are offline tools and "
                            "need not deploy, but data/ownership_manifest.json and sourcemaps/d4.json do.")
    spec["folders"] = fl
    spec["expect"] = {"mods_after": BASE_MODS + len(fl), "banks": banks(fl)}
    spec["layer2"] = {
        "base": 5305, "pack": "D4_Unique_5305", "quest_id": 437, "class_row": 18230, "art": 656, "quest_slot": 784,
        "alternate": {"base": 4390, "pack": "D4_Unique_4390", "quest_id": 435, "class_row": 18210, "art": 646,
                      "quest_slot": 782},
        "command": ("python live-harness/pipeline/drpgk6_steps.py --boot --slot '(01)' --class 18230 --row 18230 "
                    "--art 656 --quest 437"),
        "read": "class u32 +0x2E04, palette u8 +0x2E2C, graphics id u16 +0x2E36 of the new roster record",
        "expect": {"class": 18230, "palette": 0, "graphics_id": 656},
        "resident_placeholder": {
            "why": "a monster body is bound to anim N+2 while bank N loads and is found only in anm_resident (D4BANK-ID)",
            "monster_banks": MONSTER_BANKS,
            "check": "after the kept install every N+2 (835, 2262, 2302, 2332, 2362, 2382, 2842) is a block of "
                     "anm_resident (importcore.resident_placeholder_gate with resident_ids from the installed pack)"},
        "after_boot": "state shows input_guard 1 and guard_kb/guard_pad present"}
    new_ids = sorted(json.loads(next((ROOT / f / "patches/classes").glob("class_*.json")).read_text())["family"]
                     for f in fl if "_Class_" in f)
    page = spec["soak"]["page"]
    page["ids"] = sorted(set(page["ids"]) | set(new_ids))      # D4INSTALL2's 11 + the 7 new class families
    page["count"], page["min_ids"] = len(page["ids"]), 7
    page["derived_from"] = ("D4INSTALL2's 11 ids + the family of each of the 7 new D4_Class folders (patches/classes/"
                            "class_*.json); cross-check with live_accept.py --derive-page d4. min_ids 7 = the 7-row window.")
    a.out.write_text(json.dumps(spec, indent=1) + "\n")
    print(a.out, len(fl), "folders", len(spec["expect"]["banks"]), "banks")


if __name__ == "__main__":
    main()
