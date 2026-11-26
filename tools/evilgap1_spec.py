#!/usr/bin/env python3
"""EVILGAP1: write the install spec that REPLACES 7 installed D4 unique packs with their rebuilt copies (offline).

    python tools/evilgap1_spec.py OUT.json

Modelled on D4GAP1.json (same writer: tools/d4gap1_spec.py).  expect.banks here are the raw built-file numbers; run
live-harness/pipeline/replay_banks.py on the result (D4RB1) before use - the installer rewrites banks.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d4gap1_spec as g                                   # noqa: E402

BUILD = "Builds/EVILGAP1-20261110"
PACKS = [170, 220, 310, 320, 450, 460, 490, 5301, 5309, 5310]   # replace installed copies
CLASSES = []                                                       # EVILGAP1c: out-of-scope owner classes are NOT added
BASE_MODS = 321                                           # installed kit mods/ at 2026-11-10; all 7 are replacements


def main(out):
    spec = json.loads((g.ROOT / "Subprojects/Engine-Extensions/live-harness/pipeline/specs/D4GAP1.json").read_text())
    fl = [f"{BUILD}/mods/D4_Unique_{n}" for n in PACKS] + [f"{BUILD}/mods/D4_Class_{n}" for n in CLASSES]
    spec["lane"] = "EVILGAP1"
    spec["build"] = f"{BUILD}/mods (10 rebuilt uniques)"
    spec["notes"] = (
        "EVILGAP1+1b+1c (prepared offline 2026-11-10, NOT run): REPLACE 10 installed D4 unique packs (the 7 below, plus Prism Red 320, Graceus 5309 and Reprachon 5310). Prism Red's evility links point at rows 8181/8841 owned by the installed D4_Class_1220 (mod.json requires it); Graceus (8211), Reprachon (8351) and Main Hero B (8625) own their rows themselves because the D4 class packs 1130/1100/1210 are out of importer scope (EVILGAP1c). Original 7 packs with rebuilds that add "
        "signature evility rows (Skill.dat rows + evilities.json/aliases.json + char evility links): Nagi 490 (8894 dealt), "
        "Pirohiko 460 (8882 conversion), Nemo 220 (8872 alias Malicious Reflect), Ash 450 (8880 alias Hoarfrost Magic), "
        "Hugo 170 (8873 alias Death Spell, innate), Main Hero B 310 (8627 alias Medical Heal), Chief 5301 (8304 alias "
        "Medical Insertion, innate). Art, stats, skills, quests identical to the installed copies (only Skill.dat, "
        "evilities, char.dat evility fields and mod.json differ). Pure data: no kit code to deploy, no exe change beyond "
        "what the installer always rebuilds. Layer 2: boot, read Chief's roster record after recruiting (quest 436), then "
        "check evility ids on the unit. D4RB1: expect.banks replayed with replay_banks.py. Dry-run: live_accept.py --dry-run.")
    spec["base"] = {"profile": "MAIN", "mods": BASE_MODS, "exe_sha256": "RE-PIN-AT-LAUNCH", "banks": {}}
    spec["re_pin_at_launch"] = ("RE-PIN: base.mods 321 = installed kit mods/ on 2026-11-10; base.exe_sha256 is a placeholder "
                                "(every install rebuilds the exe). Read both from the live kit before the run.")
    spec["kitcode"] = {"worktree": "Local/Worktrees/integ-2026-11", "commit": "COORDINATOR-SETS", "force": False,
                       "runtime_core": False, "modules": []}
    spec["kitcode_note"] = ("data-only pack replacement: nothing under d5lib needs deploying (the importer/overlay "
                            "files are offline build tools). commit is set by the coordinator at launch.")
    spec["folders"] = fl
    spec["expect"] = {"mods_after": BASE_MODS + len(CLASSES), "banks": g.banks(fl)}
    spec["layer2"] = {
        "base": 5301, "pack": "D4_Unique_5301", "quest_id": 436, "class_row": 18220, "art": 653, "quest_slot": 783,
        "command": ("python live-harness/pipeline/drpgk6_steps.py --boot --slot '(01)' --class 18220 --row 18220 "
                    "--art 653 --quest 436"),
        "read": "class u32 +0x2E04, palette u8 +0x2E2C, graphics id u16 +0x2E36 of the new roster record; then "
                "evility list of the unit holds 8304/1180",
        "expect": {"class": 18220, "palette": 0, "graphics_id": 653}}
    base_ids = [14080, 14140, 14190, 14200, 14220, 14240, 14250, 14610, 14630, 14660, 14700]
    new_ids = [json.loads(next((g.ROOT / f / "patches/classes").glob("class_*.json")).read_text())["family"]
               for f in fl if "_Class_" in f]
    page = spec["soak"]["page"]
    page["ids"] = sorted(set(base_ids) | set(new_ids))
    page["count"] = len(page["ids"])
    page["derived_from"] = "D4INSTALL2's 11 ids + the family of each of the 3 owner class folders; cross-check with live_accept.py --derive-page d4"
    Path(out).write_text(json.dumps(spec, indent=1) + "\n")
    print(out, len(fl), "folders", len(spec["expect"]["banks"]), "banks")


if __name__ == "__main__":
    main(sys.argv[1])
