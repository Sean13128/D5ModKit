#!/usr/bin/env python3
"""EVILFX1: write the install spec that REPLACES 3 installed D4 unique packs AND changes the exe payload (offline).

    python tools/evilfx1_spec.py OUT.json

Template: specs/NODRAW2-EVILGAP1.json (base, boot/load/soak settings).  expect.banks here are the raw built-file
numbers; run live-harness/pipeline/replay_banks.py on the result (D4RB1) before use.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d4gap1_spec as g                                   # noqa: E402

BUILD = "Builds/EVILFX1-20261110/d4"
PACKS = [170, 210, 320]                                   # replace installed copies (170/320 supersede EVILGAP1's)
BASE_MODS = 321


def main(out):
    spec = json.loads((g.ROOT / "Subprojects/Engine-Extensions/live-harness/pipeline/specs/NODRAW2-EVILGAP1.json")
                      .read_text())
    fl = [f"{BUILD}/mods/D4_Unique_{n}" for n in PACKS]
    spec["lane"] = "EVILFX1"
    spec["build"] = f"{BUILD}/mods (3 rebuilt D4 uniques)"
    spec["notes"] = (
        "EVILFX1 (prepared offline 2026-11-10, NOT run). THIS SPEC CHANGES THE EXE PAYLOAD: the kit's evility runtime "
        "(d5lib/evility.py + d5lib/native/d5evil.inc.asm, section .d5el) gains scale 15 map_squad and family "
        "rearm_first_damage, so kitcode must deploy the evilfx1 commit and the installer rebuilds disgaea5.exe "
        "(no new hook site: map_squad is evaluator-only, rearm rides the existing round-edge wrapper at 0x1405F8FFC). "
        "REPLACE 3 installed D4 unique packs: Prism Red 320 (row 8840 Friends, stats +5% x deployed squad allies, "
        "innate, adapted Evil Area->squad; keeps refs 8181/8841 to D4_Class_1220), Pringer X 210 (row 8667 Tyrant "
        "Guard = alias 6047 First Impression + rearm_first_damage, innate), Hugo 170 (row 8215 Dismal Omen = alias "
        "D5 Evil Spirit 141, learnable, adapted; keeps EVILGAP1's 8873). 170 and 320 SUPERSEDE the EVILGAP1 folders "
        "of the same name (built from the same additions file plus these rows): install one or the other, not both. "
        "Art, stats, skills, quests identical to the installed copies (compare 'expected'; only mod.json, Skill.dat, "
        "char.dat evility fields and evilities/aliases differ). D4RB1: expect.banks replayed with replay_banks.py.")
    spec["base"] = {"profile": "MAIN", "mods": BASE_MODS, "exe_sha256": "RE-PIN-AT-LAUNCH", "banks": {}}
    spec["re_pin_at_launch"] = ("RE-PIN: base.mods = installed kit mods/ count at launch (321 on 2026-11-10); "
                                "base.exe_sha256 placeholder (the installer rebuilds the exe; record the new sha).")
    spec["kitcode"] = {"worktree": "Local/Worktrees/integ-2026-11", "commit": "COORDINATOR-SETS", "force": False,
                       "runtime_core": False, "modules": ["evility.py", "native/d5evil.inc.asm"]}
    spec["kitcode_note"] = ("merge branch evilfx1 into the integ worktree and set commit; the two modules are the exe "
                            "payload's evility runtime and MUST be deployed before the install, or the installer "
                            "refuses the new family/scale names in the three packs' evilities.json")
    spec["folders"] = fl
    spec["expect"] = {"mods_after": BASE_MODS, "banks": g.banks(fl)}
    spec["layer2"] = {
        "base": 210, "pack": "D4_Unique_210", "quest_id": 305, "class_row": 10260, "art": 643,
        "command": ("python live-harness/pipeline/drpgk6_steps.py --boot --slot '(01)' --class 10260 --row 10260 "
                    "--art 643 --quest 305"),
        "read": "class u32 +0x2E04 of the new roster record; the unit's learned list (+0x2F30, count +0x3030) holds "
                "8667 and 6047; in battle stat record (0x141067DC8 + idx*0xE98) +0xDF9 goes 0 -> 1 on the first hit "
                "and back to 0 after the round edge",
        "expect": {"class": 10260}}
    Path(out).write_text(json.dumps(spec, indent=1) + "\n")
    print(out, len(fl), "folders", len(spec["expect"]["banks"]), "banks")


if __name__ == "__main__":
    main(sys.argv[1])
