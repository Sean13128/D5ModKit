"""Development shortcut: build every enabled mod in memory and re-install ONLY some archives (default: the exe and
the database) -- for exe-code / database changes right after a full install, without re-writing the big sprite
archives (a full install re-compresses them: ~25 min with many outfits).  Everything else must already be
installed from the same mods.

    python tools/install_exe_only.py [ARCHIVE ...]      default: EXE/disgaea5.exe Database/Database_0.dat
"""
import os
import sys
import time

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import modsys                                   # noqa: E402
from d5lib.gamefs import GameFS, EXE_FILE                  # noqa: E402

want = sys.argv[1:] or [EXE_FILE, "Database/Database_0.dat"]
game = paths.require_game_dir()
inst = modsys.Installer(game, KIT, log=print)
fs = GameFS(game, backup_resolver=inst.backup_resolver)
t = time.time()
ctx = modsys.build(fs, modsys.ModManager(KIT).enabled_mods(), log=lambda *a: None)
print(f"built in {time.time() - t:.0f}s")
groups = modsys._group_outputs(ctx)
for archive in want:
    changes = groups.get(archive)
    if not changes:
        print(f"{archive}: no changes")
        continue
    if archive == EXE_FILE:
        inst._ensure_backup(archive, "full")
        with open(inst.apath(archive), "wb") as f:
            f.write(changes[()])
    elif fs.archive_kind(archive) == "nispack":
        inst.restore(archive)
        fs.reset()
        per_member = {}
        for parts, data in changes.items():
            per_member.setdefault(parts[0], {})[parts[1:]] = data
        raw = {m: modsys._assemble_member(fs, archive, m, ch) for m, ch in per_member.items()}
        inst._ensure_backup(archive, "append")
        inst._append_patch(archive, raw)
        inst.index[archive]["modified"] = True
        inst._save_index()
        fs.reset()
    else:
        raise SystemExit(f"{archive}: not supported here (run a full install)")
    print(f"installed {archive}: {len(changes)} change(s)")
