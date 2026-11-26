"""Put one damaged archive member back from a verified vanilla copy of the same archive.

    python tools/repair_archive_member.py --archive "Anime/ANM_HI_JP.dat" --member anm00010.lzs \\
        --pristine "/path/to/vanilla/ANM_HI_JP.dat" [--game PATH] [--dry-run]

The member is appended at the end of the archive and its directory entry is repointed, exactly as an
install appends a changed member -- nothing else in the archive moves, no other member's offset changes.
The appended bytes are re-read and decoded before the tool says it worked.

--pristine must be the same archive from an unmodded game (Sean's own pre-mod backup, a Steam depot copy,
or any folder whose Data/Anime holds the untouched archive).  The tool refuses a pristine member that does
not decode, and refuses to write when the member already decodes (nothing to do).

Read-only on the pristine file.  The archive is only written after every check has passed, and its current
name directory is saved next to the kit's backups as <archive>__<member>.hdr.repair-before.
"""
import argparse
import json
import os
import struct
import sys
import time

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import crypt, lzs, modsys, paths  # noqa: E402
from d5lib.nispack import ALIGN, ENTRY_SIZE, NisPack  # noqa: E402


def read_entries(path):
    with open(path, "rb") as f:
        head = crypt.decode(f.read(16))
        if head[:8] != b"NISPACK\0":
            raise SystemExit(f"{path}: not a NISPACK archive")
        unk, count = struct.unpack_from("<II", head, 8)
        table = crypt.decode(f.read(count * ENTRY_SIZE))
    entries = []
    for i in range(count):
        name, off, size, stamp = struct.unpack_from("<32sIII", table, i * ENTRY_SIZE)
        entries.append([name.split(b"\0")[0].decode("ascii", "replace"), off, size, stamp])
    return unk, entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True, help='virtual path ("Anime/ANM_HI_JP.dat") or a real path')
    ap.add_argument("--member", required=True, help="member name inside the archive, e.g. anm00010.lzs")
    ap.add_argument("--pristine", required=True, help="the same archive from an unmodded game")
    ap.add_argument("--game")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    game = a.game or paths.require_game_dir()
    target = a.archive if os.path.isabs(a.archive) or os.path.exists(a.archive) else \
        os.path.join(game, "Data", a.archive.replace("/", os.sep))

    # 1. the replacement: stored bytes from the pristine archive, which must decode
    np = NisPack(a.pristine)
    if a.member.lower() not in np.by_name:
        raise SystemExit(f"{a.pristine}: no member {a.member}")
    data = np.read(a.member)
    np.close()
    try:
        plain = lzs.decompress(data)
    except Exception as exc:                          # noqa: BLE001
        raise SystemExit(f"{a.pristine}: its {a.member} does not decode either ({exc}) -- not a vanilla copy")

    # 2. the target: does it need this at all?
    try:
        now = NisPack(target).read(a.member)
        lzs.decompress(now)
        print(f"{target}: {a.member} already decodes ({len(now)} stored); nothing to do")
        return 0
    except KeyError:
        raise SystemExit(f"{target}: no member {a.member}")
    except Exception as exc:                          # noqa: BLE001
        print(f"{target}: {a.member} is damaged ({exc}); repairing from {a.pristine}")

    unk, entries = read_entries(target)
    entry = next(e for e in entries if e[0].lower() == a.member.lower())
    size = os.path.getsize(target)
    end = (size + ALIGN - 1) // ALIGN * ALIGN
    print(f"  appending {len(data)} stored bytes ({len(plain)} decoded) at {end}; entry {entry[1]}+{entry[2]}"
          f" -> {end}+{len(data)}")
    if a.dry_run:
        print("  --dry-run: nothing written")
        return 0

    mine = modsys.game_state_dir(game, KIT)
    os.makedirs(mine, exist_ok=True)
    keep = os.path.join(mine, "backups", os.path.basename(target) + f"__{a.member}.repair-before")
    os.makedirs(os.path.dirname(keep), exist_ok=True)
    with open(target, "rb") as f:
        before = f.read(16 + len(entries) * ENTRY_SIZE)
    with open(keep, "wb") as f:
        f.write(before)

    with open(target, "r+b") as f:
        f.seek(end)
        f.write(crypt.encode(data))
        pad = ((end + len(data) + ALIGN - 1) // ALIGN * ALIGN) - (end + len(data))
        if pad:
            f.write(crypt.encode(b"\0" * pad))
        f.truncate(end + len(data) + pad)
        entry[1], entry[2] = end, len(data)
        table = b"".join(struct.pack("<32sIII", e[0].encode("ascii")[:32], e[1], e[2], e[3])
                         for e in entries)
        f.seek(0)
        f.write(crypt.encode(b"NISPACK\0" + struct.pack("<II", unk, len(entries)) + table))

    # 3. prove it, by reading the archive the game will read
    np = NisPack(target)
    again = np.read(a.member)
    np.close()
    assert again == data, "the appended member does not read back byte-identical"
    assert lzs.decompress(again) == plain, "the appended member does not decode to the pristine content"
    print(f"  repaired: {a.member} reads back byte-identical and decodes to {len(plain)} bytes")
    print(f"  previous name directory saved as {keep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
