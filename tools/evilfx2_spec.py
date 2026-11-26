#!/usr/bin/env python3
"""EVILFX2: write the install spec (offline).  7 DRPG + 2 D4 packs replace installed folders; the exe payload changes.

    python tools/evilfx2_spec.py OUT.json      then live-harness/pipeline/replay_banks.py on the result (D4RB1)
Template: specs/INSTALL4-EVIL-L1.json (boot / load / soak settings).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d4gap1_spec as g                                   # noqa: E402

BUILD = "Builds/EVILFX2-20261110"
PY, KIT = "D5Modkit/.venv-macos/bin/python", "Local/Worktrees/integ-2026-11"
MODULES = ["evility.py", "native/d5evil.inc.asm", "importers/drpg-evility-overlay.json", "importers/drpg-evility-names.json",
           "importers/d4-evility-overlay.json", "importers/d4-evility-additions.json",
           "learned.py", "data/ownership_manifest.json"]     # EVILFX2b: the save-safety gate and the late bands


def main(out):
    specs = g.ROOT / "Subprojects/Engine-Extensions/live-harness/pipeline/specs"
    spec = json.loads((specs / "INSTALL4-EVIL-L1.json").read_text())
    fl = sorted(f"{BUILD}/mods/{p.name}" for p in (g.ROOT / BUILD / "mods").iterdir() if p.is_dir())
    kit = g.ROOT / "Local/Installed D5ModKit"
    exe = hashlib.sha256((kit.resolve().parent / "disgaea5.exe").read_bytes()).hexdigest()
    spec.update(
        lane="EVILFX2", build=f"{BUILD}/mods ({len(fl)} packs: 7 DRPG restaged with switch L1 on, 2 D4 uniques)",
        notes=("EVILFX2 (prepared offline 2026-11-10, NOT run). THIS SPEC CHANGES THE EXE PAYLOAD: the evility runtime "
               "(d5lib/evility.py + native/d5evil.inc.asm, section .d5el) gains scales party_capped / hp_pct / hp_lost_pct, "
               "conditions self_buff, self_debuff, map_buff_min, map_debuff_min, enemy_map_max, other_weapon, side_top, "
               "side_bottom, provider_buff, regen as an aura, and passes the status index to the ailment_null predicate. "
               "No new hook site. kitcode must deploy the commit that contains branch evilfx2 BEFORE the install, or the "
               "installer refuses the new names in 7 packs' evilities.json. Folders are clones of the folders installed on "
               "2026-11-10 18:10 (after BACKVIEW1B; D4 tables restaged 19:00 for EVILFX2b) with table files only changed: DRPG Barbara, Ayame, Ivar, Liz Smart, "
               "Pringer V3, Pudding Desco, Sakuya (one more own evility each: rows 28002, 28031, 28099, 28299, 28438, "
               "28559, 28471); D4 Kojiro 4390 (innate link to row 8697 of D4_Class_1140, mod.json requires it) and Kyoko "
               "350 (new innate row 27844 in the D4 late band so no installed learnable row changes position, row 8845 provider id fixed). Every bank is byte-identical to the installed one "
               "(STAGE-RECEIPT.json; diff -rq). D1 / D2 / D3 stay OFF. Skill.dat reaches 1,007 rows: 7 innate-only rows "
               "sit past bitmap position 999 for the first time in a real install (Unicorn-probed only, DRPGEVIL1b)."),
        base={"profile": "MAIN", "mods": len(list((kit / "mods").iterdir())), "exe_sha256": exe, "banks": {}},
        re_pin_at_launch=f"pinned 2026-11-10 offline: exe {exe[:8]}..., installed d5lib = integ-next 5337bf5; RE-PIN if "
                         "anything was installed since. The installer rebuilds the exe: record the new sha.",
        kitcode={"worktree": KIT, "commit": "COORDINATOR-SETS", "force": False, "runtime_core": False, "modules": MODULES},
        kitcode_note="merge branch evilfx2 into the integ worktree and set commit. The first two modules are the exe "
                     "payload's evility runtime; the four importer data files, learned.py (save-safety gate) and the ownership manifest (late bands) are "
                     "build-time; files that VOICE2 changed on integ-next are not listed here (not this lane's).",
        folders=fl)
    spec["expect"] = {
        "mods_after": spec["base"]["mods"], "banks": g.banks(fl),
        "readback_commands": [
            {"name": "skill_budget", "argv": [PY, f"{KIT}/tools/check_skill_budget.py", "Local/Installed D5ModKit/mods", f"{BUILD}/mods",
                                              "--installed", "Local/Installed D5ModKit/mods"]},
            {"name": "used_ids", "argv": [PY, f"{KIT}/tools/check_used_ids.py", f"{BUILD}/mods"]},
            {"name": "outfit_voices_replay",
             "argv": [PY, f"{KIT}/tools/simulate_outfit_voices.py", "--clean", "Disgaea Source/Disgaea 5 Complete (Steam 803600)",
                      "--installed", "Local/Installed D5ModKit/mods", "--order", "Local/Installed D5ModKit/profiles/MAIN/load_order.json",
                      "--staged", f"{BUILD}/mods"]},
            {"name": "voices", "after_install": True,
             "argv": [PY, f"{KIT}/tools/check_installed_voices.py", "--game", "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete",
                      "--mods", "Local/Installed D5ModKit/mods", "--only", ",".join(Path(f).name for f in fl)]}]}
    spec.pop("layer2", None)
    Path(out).write_text(json.dumps(spec, indent=1) + "\n")
    print(out, len(fl), "folders", len(spec["expect"]["banks"]), "banks, base mods", spec["base"]["mods"], "exe", exe[:12])


if __name__ == "__main__":
    main(sys.argv[1])
