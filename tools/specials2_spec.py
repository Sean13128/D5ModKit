#!/usr/bin/env python3
"""SPECIALS2: write the install spec (offline).  109 D4 / D1C / DD2 packs replace installed folders; tables only.

    python tools/specials2_spec.py OUT.json      then live-harness/pipeline/replay_banks.py on the result (D4RB1)
Template: specs/INSTALL4-EVIL-L1.json (boot / load / soak settings).  No exe payload change.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d4gap1_spec as g                                   # noqa: E402

BUILD = "Builds/SPECIALS2-20261110"
PY, KIT = "D5Modkit/.venv-macos/bin/python", "Local/Worktrees/integ-2026-11"
MODULES = ["srcskills.py", "importers/specials2.py", "importers/specials2-leases.json", "importcore.py",
           "data/ownership_manifest.json"]


def main(out):
    specs = g.ROOT / "Subprojects/Engine-Extensions/live-harness/pipeline/specs"
    spec = json.loads((specs / "INSTALL4-EVIL-L1.json").read_text())
    fl = sorted(f"{BUILD}/mods/{p.name}" for p in (g.ROOT / BUILD / "mods").iterdir() if p.is_dir())
    kit = g.ROOT / "Local/Installed D5ModKit"
    exe = hashlib.sha256((kit.resolve().parent / "disgaea5.exe").read_bytes()).hexdigest()
    spec.update(
        lane="SPECIALS2", build=f"{BUILD}/mods ({len(fl)} packs: D4 31, D1C 51, DD2 27; table files only)",
        notes=("SPECIALS2 (restaged by SPECIALS2c 2026-11-10: DD2 power converted through shared moves, D4 stand-ins prefer the body own 40x tracks; NOT run, NOT dry-run: a live lane had the game). Source special "
               "attacks for the installed D4 / D1C / DD2 packs. Folders are APFS clones of the folders installed on "
               "2026-11-10 with only mod.json, patches/db/char.dat.json (learn fields), patches/db/magic.dat.json and "
               "patches/skills/skills.json changed; every other file is byte-identical (STAGE-RECEIPT-<game>.json). "
               "221 new magic.dat rows at 29000-29220 (d5lib/importers/specials2-leases.json), 38 installed rows "
               "rewritten in place with the source's numbers, no installed magic.dat id removed. Skill.dat, voices, art "
               "and the exe payload are untouched. Re-stage if any of these folders is installed again before this "
               "runs (tools/specials2.py stage)."),
        base={"profile": "MAIN", "mods": len(list((kit / "mods").iterdir())), "exe_sha256": exe, "banks": {}},
        re_pin_at_launch=f"pinned 2026-11-10 offline while a live lane ran: exe {exe[:8]}...; RE-PIN (mods count, exe) "
                         "and re-stage if anything was installed since.",
        kitcode={"worktree": KIT, "commit": "COORDINATOR-SETS", "force": False, "runtime_core": False, "modules": MODULES},
        kitcode_note="merge branch specials2 into the integ worktree and set commit. All five modules are build-time "
                     "only (the installer already applies magic.dat / skills.json patches); deploying them is needed "
                     "only so a later importer rebuild (--source-specials) reproduces these folders.",
        folders=fl)
    spec["expect"] = {
        "mods_after": spec["base"]["mods"], "banks": g.banks(fl),
        "readback_commands": [
            {"name": "skill_budget", "argv": [PY, f"{KIT}/tools/check_skill_budget.py", "Local/Installed D5ModKit/mods", f"{BUILD}/mods",
                                              "--installed", "Local/Installed D5ModKit/mods"]},
            {"name": "used_ids", "argv": [PY, f"{KIT}/tools/check_used_ids.py", f"{BUILD}/mods"]},
            {"name": "skill_motions", "argv": [PY, f"{KIT}/tools/check_skill_motions.py", f"{BUILD}/mods"]},
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
