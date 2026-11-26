"""FIXUP1: the used-id guard reads resident ids from the supplied FS, never from a legacy unkeyed cache."""
import pickle

from d5lib import anm, importcore, sprites


def _resident(ids):
    blocks = []
    for i in ids:
        b = anm.AnmBlock(i)
        b.animations = [anm.Animation(1, 0)]
        blocks.append(b)
    return anm.AnmFile(blocks, [], []).to_bytes()


class FS:
    def __init__(self, ids, loose=()):
        self.raw, self.loose = _resident(ids), ["anm%05d.lzs" % n for n in loose]

    def read(self, vpath):
        assert vpath.endswith("anm_resident.lzs")
        return self.raw

    def list_members(self, archive):
        return self.loose


def _mod(tmp_path, name, anm_ids):
    d = tmp_path / name / "files/Anime/ANM_HI_JP.dat"
    d.mkdir(parents=True)
    for n in anm_ids:
        (d / ("anm%05d.lzs" % n)).write_bytes(b"x")
    return tmp_path / name


def _used(fs, tmp_path):
    u = importcore.UsedIds(tmp_path, tmp_path)
    u._vanilla = ({}, sprites.used_sprite_numbers(fs))
    u._index = {}
    return u


def test_legacy_unkeyed_cache_is_ignored_and_real_collisions_still_fail(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "resident_ids.pickle").write_bytes(pickle.dumps([2022, 2322, 2342, 2372, 2632]))  # polluted legacy cache
    monkeypatch.setattr(sprites, "CACHE_DIR", str(cache))
    monkeypatch.setattr(sprites, "script_spawn_ids", lambda: {9500})
    clean = FS([2022, 612], loose=[100])
    four = _mod(tmp_path / "m", "D4_Class_2110", [2320, 2322])           # the four-pack case: N and its own N+2
    u = _used(clean, tmp_path)
    assert u.check(four)[0]
    assert not u.check(_mod(tmp_path / "m", "bad_res", [2022]))[0]       # a genuine resident block
    assert not u.check(_mod(tmp_path / "m", "bad_loose", [100]))[0]      # a genuine loose member
    assert not u.check(_mod(tmp_path / "m", "bad_spawn", [9500]))[0]     # a script-spawn id
    # a modded archive (placeholder block 2322 resident) gets its own ids, and the clean FS afterwards still does not
    assert 2322 in sprites.resident_block_ids(FS([2022, 2322]))
    assert 2322 not in sprites.resident_block_ids(clean)
    assert len(list(cache.glob("resident_ids-*.pickle"))) == 2
