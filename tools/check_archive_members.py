"""Decode-check the members of the game archives the installer writes.

    python tools/check_archive_members.py [ARCHIVE ...] [--game PATH] [--json OUT]

ARCHIVE   a virtual path ("Anime/ANM_HI_JP.dat") or a real path.  Without one, every archive the kit has a
          backup record for (state/games/<game>/backups.json) is checked.
--game    the game folder (default: the one the kit's finder guesses).

Why: the installer appends changed members at the end of an archive and moves the "leading" members whose
data the grown name directory would cover.  When that move read the live file instead of the backup it
copied directory bytes as a member's art, and the member stopped decoding -- anm00002.lzs (2026-10-09) and
anm00010.lzs, Killia's default body (2026-10-29: the unit drew as a shadow only).  LZS members decode or
they do not, so this check is exact and cheap (a few seconds per archive).

Read-only.  Exit status 1 when a member fails to decode, 0 otherwise.
"""
import argparse
import json
import os
import sys
import time

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import lzs, modsys, paths  # noqa: E402
from d5lib.nispack import NisPack  # noqa: E402


def archive_path(archive, game):
    if os.path.isabs(archive) or os.path.exists(archive):
        return archive
    return os.path.join(game, "Data", archive.replace("/", os.sep))


def backed_up_archives(game, kit_dir=None):
    """the archives this game folder's install has touched (and can restore)"""
    mine = modsys.game_state_dir(game, kit_dir or KIT)
    with open(os.path.join(mine, "backups.json"), encoding="utf-8") as f:
        index = json.load(f)
    return [a for a, rec in index.items()
            if rec.get("mode") in ("append", "psfs", "fafs") and a.lower().endswith(".dat")]


def check(path, skip=()):
    np = NisPack(path)
    bad, n = [], 0
    for name in np.names():
        if not name.lower().endswith(".lzs") or name in skip:
            continue
        n += 1
        try:
            lzs.decompress(np.read(name))
        except Exception as exc:                     # noqa: BLE001 - any failure is the finding
            bad.append({"archive": path, "member": name, "error": str(exc),
                        "stored": len(np.read(name))})
    np.close()
    return n, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="*")
    ap.add_argument("--game")
    ap.add_argument("--skip", action="append", default=[], metavar="MEMBER")
    ap.add_argument("--json")
    a = ap.parse_args()
    game = a.game or paths.require_game_dir()
    archives = a.archives or backed_up_archives(game)
    t0 = time.time()
    total, bad = 0, []
    for arc in archives:
        path = archive_path(arc, game)
        if not os.path.exists(path):
            print(f"{arc}: no such file")
            continue
        n, b = check(path, set(a.skip))
        total += n
        bad += b
        print(f"{arc}: {n} .lzs member(s), {len(b)} that do not decode")
        for f in b:
            print(f"  BAD {f['member']} ({f['stored']} stored): {f['error']}")
            bad[-1]["archive"] = arc
    print(f"{total} member(s) checked in {time.time() - t0:.1f}s; {len(bad)} damaged")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"checked": total, "bad": bad}, f, indent=1)
    if bad:
        print("\nA damaged member is art the installer moved with the wrong bytes, or a game file that was\n"
              "restored from a stale backup.  tools/repair_archive_member.py puts a member back from a\n"
              "verified vanilla archive; Steam › Verify integrity of game files is the other way.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
