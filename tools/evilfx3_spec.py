#!/usr/bin/env python3
"""EVILFX3: write the install spec (offline).  27 packs replace installed folders, table files only; the exe payload
changes (condition not_moved).  Run AFTER tonight's combined install (LIVE5-COMBINED): 26 folders are clones of it.

    python tools/evilfx3_spec.py OUT.json      then live-harness/pipeline/replay_banks.py on the result (D4RB1)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d4gap1_spec as g                                   # noqa: E402

BUILD = "Builds/EVILFX3-20261110"
PY, KIT = "D5Modkit/.venv-macos/bin/python", "Local/Worktrees/integ-2026-11"
MODS = "Local/Installed D5ModKit/mods"
MODULES = ["evility.py", "native/d5evil.inc.asm", "learned.py", "importcore.py", "gametruth.py", "data/ownership_manifest.json",
           "sourcemaps/d4.json", "importers/dd2.py", "importers/_dd2_innates.py", "importers/dd2-innate-evilities.json",
           "importers/d1c-donor-evilities.json", "importers/d4-evility-overlay.json", "importers/d4-evility-additions.json",
           "importers/drpg-evility-overlay.json", "importers/drpg-evility-names.json"]


def main(out):
    specs = g.ROOT / "Subprojects/Engine-Extensions/live-harness/pipeline/specs"
    spec = json.loads((specs / "EVILFX2.json").read_text())
    fl = sorted(f"{BUILD}/mods/{p.name}" for p in (g.ROOT / BUILD / "mods").iterdir() if p.is_dir())
    names = ",".join(Path(f).name for f in fl)
    spec.update(
        lane="EVILFX3", build=f"{BUILD}/mods ({len(fl)} packs: 14 D1C donors, 7 D4, 6 DD2; innate evility links)",
        notes=("EVILFX3 (prepared offline 2026-11-10, NOT run). RUN ONLY AFTER the combined install of 2026-11-10 "
               "(Builds/LIVE5-COMBINED-20261110): 26 of the 27 folders are clones of that stage, 1 of the installed folder, "
               "with table files only changed (STAGE-RECEIPT.json). THIS SPEC CHANGES THE EXE PAYLOAD: evility condition "
               "not_moved (65) is new, so kitcode must deploy evility.py + native/d5evil.inc.asm from a commit containing "
               "branch evilfx2 (EVILFX3 commits) first. What changes: every listed pack's char rows link an innate evility. "
               "D1C x14: a vanilla D5 donor evility (d1c-donor-evilities.json). D4: classes 1170 Masked Hero 27690, 1200 "
               "Android 27121 (alias 6059), 1220 Prism Ranger 8840 (the row moves here from D4_Unique_320, which now "
               "references it - install BOTH), 2130 Mystic Beast 27692, 2170 Dragon 27663 (alias 2065), 2190 Rifle Demon "
               "27693. DD2: Barbara 10100 (link only), Evil Dragon 26200 (alias 4015), Death 26300 (alias 1143), Living "
               "Armor 26301 (alias 2065), Gargoyle 26302, Mao 26303. New rows are innate only and sit in the late bands "
               "(27000+ / 26200+): no installed learnable row changes position (skill_budget --installed). Skill.dat "
               "reaches 1,017 rows, 17 innate-only rows past bitmap position 999."),
        base={"profile": "MAIN", "mods": "RE-PIN-AT-LAUNCH", "exe_sha256": "RE-PIN-AT-LAUNCH", "banks": {}},
        re_pin_at_launch="RE-PIN after the combined install: base.mods = folder count, base.exe_sha256 = the exe that install "
                         "left. The installer rebuilds the exe again here: record the new sha.",
        kitcode={"worktree": KIT, "commit": "COORDINATOR-SETS", "force": False, "runtime_core": False, "modules": MODULES},
        kitcode_note="evility.py + native/d5evil.inc.asm are the exe payload (needed at install: 3 packs use not_moved). The "
                     "rest is importer data / gates / the verifier (build-time). List made from this lane's changed d5lib "
                     "files; re-check against what the combined install deployed.",
        folders=fl)
    spec["expect"] = {
        "mods_after": "RE-PIN-AT-LAUNCH", "banks": g.banks(fl),
        "readback_commands": [
            {"name": "skill_budget_and_save_safety",
             "argv": [PY, f"{KIT}/tools/check_skill_budget.py", MODS, f"{BUILD}/mods", "--installed", MODS]},
            {"name": "used_ids", "argv": [PY, f"{KIT}/tools/check_used_ids.py", f"{BUILD}/mods"]},
            {"name": "outfit_voices_replay",
             "argv": [PY, f"{KIT}/tools/simulate_outfit_voices.py", "--clean", "Disgaea Source/Disgaea 5 Complete (Steam 803600)",
                      "--installed", MODS, "--order", "Local/Installed D5ModKit/profiles/MAIN/load_order.json",
                      "--staged", f"{BUILD}/mods"]},
            {"name": "voices", "after_install": True,
             "argv": [PY, f"{KIT}/tools/check_installed_voices.py", "--game", "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete",
                      "--mods", MODS, "--only", names]},
            {"name": "game_truth", "after_install": True,
             "argv": [PY, f"{KIT}/tools/game_truth.py", "--only", names]}]}
    Path(out).write_text(json.dumps(spec, indent=1) + "\n")
    print(out, len(fl), "folders", len(spec["expect"]["banks"]), "banks")


if __name__ == "__main__":
    main(sys.argv[1])
