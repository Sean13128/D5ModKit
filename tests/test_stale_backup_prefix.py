"""A stale backup prefix must be repaired by the installer, not by a human with a file manager.

LIVE11 (2026-10-30) could not install TEST16: Anime/ANM_HI_JP.dat's kit backup prefix was 167,348 B,
written by the *pre-PT1029* kit (it saved exactly the directory size of its day), while the 4,167-entry
member directory needs 183,364 B.  The lane rebuilt it by hand from a vanilla copy
(`/Volumes/Data/CharForge-Backup/.../Game before D5ModKit/Data/Anime/ANM_HI_JP.dat`) after verifying the
prefix bytes were identical to the vanilla file's first 167,348 B.

The installer now does that itself: given a pristine copy of the same archive (Installer(vanilla_dir=...)
or D5MODKIT_VANILLA_GAME), a prefix shorter than the 1 MiB protection is rebuilt from it -- but only when
the current prefix is a byte-exact prefix of that file, so the extra bytes are vanilla bytes and never
something a previous install wrote.  Without a pristine copy it still refuses, and now says *why*.
"""
import os
import shutil

import pytest

from d5lib import modsys
from d5lib.nispack import NisPack, write_nispack


ARCHIVE = "Anime/ANM_TEST.dat"


def _game(tmp_path):
    game = tmp_path / "game"
    (game / "Data" / "Anime").mkdir(parents=True)
    return game


def _archive(tmp_path):
    game = _game(tmp_path)
    path = game / "Data" / "Anime" / "ANM_TEST.dat"
    files = ([("anm00002.bin", b"V" * 5000, 0)]
             + [(f"pad{i:04d}.bin", b"x" * 10, 0) for i in range(3)]
             + [("filler.bin", b"F" * 300000, 0)])
    write_nispack(str(path), files)
    return game, path


def _vanilla(tmp_path, path):
    """a pristine copy laid out like a game folder"""
    root = tmp_path / "vanilla"
    dest = root / "Data" / "Anime" / "ANM_TEST.dat"
    dest.parent.mkdir(parents=True)
    shutil.copyfile(path, dest)
    return root


def _installer(tmp_path, game, vanilla_root=None):
    inst = modsys.Installer(str(game), kit_dir=str(tmp_path / "kit"), log=lambda *a: None,
                            vanilla_dir=str(vanilla_root) if vanilla_root else None)
    inst._ensure_backup(ARCHIVE, "append")
    return inst


def _make_stale(inst, archive=ARCHIVE):
    """what the pre-PT1029 kit left: a prefix that covers only the member directory of its day"""
    import struct

    from d5lib import crypt

    hp = inst._bfile(archive, ".hdr")
    with open(hp, "rb") as f:
        head = f.read()
    count = struct.unpack_from("<I", crypt.decode(head[:16]), 12)[0]
    keep = 16 + count * 44
    with open(hp, "wb") as f:
        f.write(head[:keep])
    return keep


def test_a_stale_prefix_is_rebuilt_from_a_pristine_copy_and_the_install_goes_through(tmp_path):
    game, path = _archive(tmp_path)
    vanilla = _vanilla(tmp_path, path)
    inst = _installer(tmp_path, game, vanilla)
    _make_stale(inst)
    stale, hlen = inst.stale_prefix(ARCHIVE)
    assert stale and hlen == 236

    rebuilt = inst._append_patch(ARCHIVE, {f"new{i:04d}.bin": b"y" * 8 for i in range(200)})

    hp = inst._bfile(ARCHIVE, ".hdr")
    assert os.path.getsize(hp) > hlen, "the prefix must be grown by the installer itself"
    # the whole vanilla archive: it is smaller than the 1 MiB protection, so the prefix is all of it
    assert os.path.getsize(hp) == os.path.getsize(vanilla / "Data" / "Anime" / "ANM_TEST.dat")
    # the old prefix is kept, not deleted
    kept = [n for n in os.listdir(inst.backup_dir) if os.path.basename(hp) + ".stale-" in n]
    assert kept, "the stale prefix must be kept as evidence"
    with open(os.path.join(inst.backup_dir, kept[0]), "rb") as f:
        assert len(f.read()) == hlen
    # and the member whose data the directory grows over is still the vanilla bytes
    with NisPack(str(path)) as np:
        assert np.read("anm00002.bin") == b"V" * 5000


def test_a_prefix_that_does_not_match_the_pristine_copy_is_not_guessed_at(tmp_path):
    game, path = _archive(tmp_path)
    vanilla = _vanilla(tmp_path, path)
    # a different archive at that path: same shape, different bytes
    other = tmp_path / "other.dat"
    write_nispack(str(other), [("anm00002.bin", b"Z" * 5000, 0), ("filler.bin", b"F" * 300000, 0)])
    shutil.copyfile(other, vanilla / "Data" / "Anime" / "ANM_TEST.dat")
    inst = _installer(tmp_path, game, vanilla)
    _make_stale(inst)
    hp = inst._bfile(ARCHIVE, ".hdr")
    with open(hp, "rb") as f:
        before = f.read()

    with pytest.raises(RuntimeError) as err:
        inst._append_patch(ARCHIVE, {f"new{i:04d}.bin": b"y" * 8 for i in range(3000)})
    assert "STALE" in str(err.value) and "backup prefix" in str(err.value)
    with open(hp, "rb") as f:
        assert f.read() == before, "a mismatched copy must leave the prefix alone"


def test_without_a_pristine_copy_the_refusal_names_the_stale_prefix(tmp_path):
    game, path = _archive(tmp_path)
    inst = _installer(tmp_path, game)
    _make_stale(inst)
    with pytest.raises(RuntimeError) as err:
        inst._append_patch(ARCHIVE, {f"new{i:04d}.bin": b"y" * 8 for i in range(3000)})
    msg = str(err.value)
    assert "STALE" in msg
    assert "D5MODKIT_VANILLA_GAME" in msg, "the message must name the way out"
    assert "hdr.stale-" in msg
