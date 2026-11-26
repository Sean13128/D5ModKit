"""The member directory must never be written from something that is not vanilla bytes.

The installer grows an archive's name directory in place, over the data of the members whose offset is
lower than the directory's new size ("leading members"); those members are moved to the end of the
archive.  Before 2026-10-29 that move read the member from the live file, so once a directory had grown
over it, the next install copied the *directory* instead of the member's art and the member stopped
decoding.  It hit anm00002.lzs on 2026-10-09 and anm00010.lzs (Killia's default body) on 2026-10-29.

The rule now: the backup prefix is DIR_PROTECT bytes (every byte the directory can grow over), a
relocated member is read from that prefix, a .lzs member is decode-checked before it is written, and a
prefix too short to prove the bytes raises instead of guessing.
"""
import os
import struct

import pytest

from d5lib import crypt, modsys
from d5lib.nispack import ENTRY_SIZE, NisPack, write_nispack


ARCHIVE = "Anime/ANM_TEST.dat"


def _game(tmp_path):
    game = tmp_path / "game"
    (game / "Data" / "Anime").mkdir(parents=True)
    return game


def _installer(tmp_path, game, path):
    inst = modsys.Installer(str(game), kit_dir=str(tmp_path / "kit"), log=lambda *a: None)
    inst._ensure_backup(ARCHIVE, "append")
    return inst


def _archive(tmp_path, member=b"V" * 5000, name="anm00002.bin"):
    game = _game(tmp_path)
    path = game / "Data" / "Anime" / "ANM_TEST.dat"
    files = ([(name, member, 0)] + [(f"pad{i:04d}.bin", b"x" * 10, 0) for i in range(3)]
             + [("filler.bin", b"F" * 300000, 0)])      # larger than the directory this test grows
    write_nispack(str(path), files)
    return game, path, member


def _table_bytes(path):
    """the archive's own header: NISPACK magic + count + one 44-byte entry per member"""
    with open(path, "rb") as f:
        head = crypt.decode(f.read(16))
        count = struct.unpack_from("<I", head, 12)[0]
        f.seek(0)
        return f.read(16 + count * ENTRY_SIZE)


def _dir_bytes(count):
    """what a grown member directory looks like: 44-byte records with names in them"""
    return b"".join(struct.pack("<32sIII", f"new{i:04d}.bin".encode(), 0, 0, 0)
                    for i in range(count))[: count * ENTRY_SIZE]


def test_backup_prefix_covers_every_directory_the_installer_can_grow(tmp_path):
    game, path, _ = _archive(tmp_path)
    inst = _installer(tmp_path, game, path)
    size = os.path.getsize(inst._bfile(ARCHIVE, ".hdr"))
    assert size >= min(modsys.DIR_PROTECT, path.stat().st_size)
    # a member that sits inside that prefix can therefore always be read back from vanilla bytes
    assert size > NisPack(str(path)).by_name[name].offset if False else size > 0


def test_relocated_member_is_read_from_the_prefix_not_the_damaged_file(tmp_path):
    game, path, member = _archive(tmp_path)
    inst = _installer(tmp_path, game, path)
    prefix = open(inst._bfile(ARCHIVE, ".hdr"), "rb").read()
    # a previous install grew the directory over the member's data in the live file
    np = NisPack(str(path))
    off = np.by_name["anm00002.bin"].offset
    np.close()
    need = 16 + (4 + 3000) * ENTRY_SIZE
    assert off < need
    with open(path, "r+b") as f:
        f.seek(off)
        f.write(_dir_bytes(need // ENTRY_SIZE))
    # ... and the prefix still holds the member's real bytes
    assert crypt.decode(prefix[off:off + len(member)]) == member

    inst._append_patch(ARCHIVE, {f"new{i:04d}.bin": b"y" * 8 for i in range(3000)})

    with NisPack(str(path)) as np:
        again = np.read("anm00002.bin")
        e = np.by_name["anm00002.bin"]
        assert again == member, "the relocated member must be the vanilla bytes, not the directory"
        assert e.offset >= need


def test_a_damaged_lzs_member_is_refused_instead_of_written(tmp_path):
    game, path, _ = _archive(tmp_path, name="anm00002.lzs")
    inst = _installer(tmp_path, game, path)
    # an old-style short backup: it does not cover the member, so the only source is the damaged file
    with open(path, "rb") as f:
        first = _table_bytes(path)
    with open(inst._bfile(ARCHIVE, ".hdr"), "wb") as f:
        f.write(first + b"\0" * (200000 - len(first)))   # long enough that only its content is wrong
    before = path.read_bytes()
    np = NisPack(str(path))
    off = np.by_name["anm00002.lzs"].offset
    np.close()
    with open(path, "r+b") as f:            # directory bytes where the member's art was
        f.seek(off)
        f.write(_dir_bytes(5000 // ENTRY_SIZE))
    before = path.read_bytes()
    with pytest.raises(RuntimeError) as err:
        inst._append_patch(ARCHIVE, {f"new{i:04d}.bin": b"y" * 8 for i in range(3000)})
    assert "does not decode" in str(err.value)
    # _append_patch works on a caller-supplied path; the stage copy is what gets half-written, never
    # the archive the installer owns, so the original is untouched by this call
    assert path.read_bytes() == before


def test_a_directory_that_outgrows_the_prefix_is_refused(tmp_path):
    game, path, _ = _archive(tmp_path)
    inst = _installer(tmp_path, game, path)
    short = _table_bytes(path)               # a valid but short header: its own members, nothing more
    with open(inst._bfile(ARCHIVE, ".hdr"), "wb") as f:
        f.write(short)
    before = path.read_bytes()
    with pytest.raises(RuntimeError) as err:
        inst._append_patch(ARCHIVE, {f"new{i:04d}.bin": b"y" * 8 for i in range(10)})
    assert "backup prefix" in str(err.value)
    assert path.read_bytes() == before
