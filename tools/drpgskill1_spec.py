#!/usr/bin/env python3
"""DRPGSKILL1: write the install spec (offline).  DRPG packs replace installed folders; table files only, no exe change.

    python tools/drpgskill1_spec.py OUT.json      then live-harness/pipeline/replay_banks.py on the result (D4RB1)
Template: specs/INSTALL4-EVIL-L1.json (boot / load / soak settings).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d4gap1_spec as g                                   # noqa: E402

BUILD = "Builds/DRPGSKILL1-20261110"
PY, KIT = "D5Modkit/.venv-macos/bin/python", "Local/Worktrees/integ-2026-11"
MODULES = ["importers/drpg_skills.py", "importers/drpg-skill-overlay.json", "importers/drpg-skill-names.json",
           "importers/_drpg_build.py", "data/ownership_manifest.json"]


def main(out):
    specs = g.ROOT / "Subprojects/Engine-Extensions/live-harness/pipeline/specs"
    spec = json.loads((specs / "INSTALL4-EVIL-L1.json").read_text())
    fl = sorted(f"{BUILD}/mods/{p.name}" for p in (g.ROOT / BUILD / "mods").iterdir() if p.is_dir())
    kit = g.ROOT / "Local/Installed D5ModKit"
    exe = hashlib.sha256((kit.resolve().parent / "disgaea5.exe").read_bytes()).hexdigest()
    rc = json.loads((g.ROOT / BUILD / "STAGE-RECEIPT.json").read_text())["counts"]
    spec.update(
        lane="DRPGSKILL1", build=f"{BUILD}/mods ({len(fl)} DRPG packs: own source skills; restaged from the installed folders)",
        notes=("DRPGSKILL1 (prepared offline 2026-11-10, NOT run). Table files only, no exe payload change, no new patch "
               "kind: the packs use the installer's existing db and skills handlers (magic.dat rows + patches/skills/skills.json "
               "choreography links, as the D4 specials do). Folders are clones of the folders installed on 2026-11-10 19:00 "
               f"(tools/stage_drpg_skills.py): {rc['own_rows']} new magic.dat rows 17000-17583 (id = 17000 + 4 * lease "
               f"position + n), {rc['own_links']} own learn links, {rc['identical_files']} files byte-identical to the installed "
               "ones (STAGE-RECEIPT.json, sha256 per file); only patches/db/char.dat.json (learn fields), "
               "patches/db/magic.dat.json (new), patches/skills/skills.json (new) and mod.json differ. Decisions M1 (spells) "
               "and C1 (drop costume lookalikes) are OFF. ORDER: these clones carry the evility files of the folders as "
               "installed at staging time. If EVILFX2 (or any spec that replaces DRPG_Core_* folders) is installed first, "
               "RESTAGE from the then-installed folders (one command, 40 s) before running this spec, or it rolls those "
               "packs' evility tables back. Learn levels are the source's (1 / 50 / 200): a unit below 200 does not have its "
               "second skill; units already holding the old lookalike keep it in their own list (stored per unit, by id)."),
        base={"profile": "MAIN", "mods": len(list((kit / "mods").iterdir())), "exe_sha256": exe, "banks": {}},
        re_pin_at_launch=f"pinned 2026-11-10 offline while a live lane had the game: exe {exe[:8]}...; RE-PIN if anything was "
                         "installed since. The installer rebuilds the exe: record the new sha.",
        kitcode={"worktree": KIT, "commit": "COORDINATOR-SETS", "force": False, "runtime_core": False, "modules": MODULES},
        kitcode_note="merge branch drpgskill1 into the integ worktree and set commit. All five files are build-time "
                     "(importer step, overlay, names, manifest band 17000-17599); the install itself needs no new kit code.",
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
