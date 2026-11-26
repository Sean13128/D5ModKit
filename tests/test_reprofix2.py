"""REPROFIX2: the D1C build holds BLANKKEYS1's blank key times, decided by the installed reference.

The installed D1C packs carry BLANKKEYS1's held pose (Serpent 1501/1507/2071/3071/4011, Spirit 1527/1567/3071,
Living Armor 1527) but not everywhere (Lantern 1501/1507 keeps its trailing blank).  The importer did not hold, so a
rebuild differed from the install at exactly those key times.  ``d1c.Importer._hold_blank_keys`` is the build pass:
hold an animation when the installed bank of the same name draws on every key time and the rebuild does not
(default on, ``--no-d1c-hold-blank`` off, ``d1c_hold_blank`` recorded in mod.json).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import anm, importcore
from d5lib.importers import d1c

ANIME = Path("files/Anime/ANM_HI_JP.dat")


def _bank_anm(blank_at=None):
    """A sprite bank with the two page ids _motion_banks() looks for (1001 front, 1007 back).

    1001 draws on every key time.  1007 draws on key 0, and on 20 only when ``blank_at`` is not 20 -- the shape a
    whole-body import leaves behind when the donor's body moved on another track."""
    node = lambda first, count, child=-1, nxt=-1, id_=0: anm.Node(id_, 0, 0, 0, 0, 0, first, count, child, nxt)
    k20 = anm.Key(20, 0, 0, 0, 0, 0) if blank_at == 20 else anm.Key(20, 0, 1, 3, 0, 0)
    keys = [anm.Key(0, 1, 0, 0, 0, 0), anm.Key(40, 2, 0, 0, 0, 0),          # 0-1: 1001's control root
            anm.Key(0, 0, 1, 3, 0, 0), anm.Key(40, 0, 1, 3, 0, 0),          # 2-3: 1001 draws on both
            anm.Key(0, 1, 0, 0, 0, 0), anm.Key(40, 2, 0, 0, 0, 0),          # 4-5: 1007's control root
            anm.Key(0, 0, 1, 3, 0, 0), k20]                                 # 6-7: 1007's own keys
    nodes = [node(0, 2, child=1), node(2, 2), node(4, 2, child=3), node(6, 2)]
    anims = [anm.Animation(1001, 0), anm.Animation(1007, 2)]
    cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 8, 8, 0)]
    return anm.AnmFile([anm.AnmBlock(1, animations=anims, nodes=nodes, keys=keys, cells=cells)], [], [])


def _write(root, folder, blank_at=None):
    d = Path(root) / folder / ANIME
    d.mkdir(parents=True, exist_ok=True)
    f = d / "anm02720.lzs"
    f.write_bytes(anm.lzs_compress(_bank_anm(blank_at).to_bytes()))
    return f


def _draws_all(path, aid):
    fl = anm.load(path)
    return all(any(i.cell.w > 0 for i in anm.evaluate(fl, ("id", aid), t, nested=True))
               for t in anm.frame_times(fl, ("id", aid)))


def _importer(root):
    imp = d1c.Importer()
    imp._ctx = dict(installed_root=root, installed_reference=True)   # the explicit --installed-reference route
    return imp


def test_hold_follows_the_installed_reference(tmp_path, monkeypatch):
    """Installed draws on every key time -> the blank is held; installed is blank too -> left alone."""
    mine = _write(tmp_path / "build", "D1C_Class_999999", blank_at=20)
    _write(tmp_path / "installed", "D1C_Class_999999")                   # the reference holds
    held = _importer(tmp_path / "installed")._hold_blank_keys(mine.parents[3], lambda _s: None)
    # two keys filled: the blank key at 20, and key time 40 (no key of its own, blank behind the 20 key)
    assert held == {"anm02720.lzs": {1007: 2}}, held
    assert _draws_all(mine, 1007)
    assert _importer(tmp_path / "installed")._hold_blank_keys(mine.parents[3], lambda _s: None) == {}      # idempotent


def test_a_trailing_blank_the_install_keeps_is_not_held(tmp_path, monkeypatch):
    """Lantern 1501/1507: the install draws nothing at its last key, so the build must leave it blank."""
    mine = _write(tmp_path / "build", "D1C_Class_999998", blank_at=20)
    _write(tmp_path / "installed", "D1C_Class_999998", blank_at=20)
    before = mine.read_bytes()
    assert _importer(tmp_path / "installed")._hold_blank_keys(mine.parents[3], lambda _s: None) == {}
    assert mine.read_bytes() == before


def test_no_installed_pack_means_no_hold(tmp_path, monkeypatch):
    """A fresh user has no reference: a rebuild does not change animations nobody asked about."""
    mine = _write(tmp_path / "build", "D1C_Class_999997", blank_at=20)
    assert _importer(tmp_path / "installed")._hold_blank_keys(mine.parents[3], lambda _s: None) == {}


def test_hold_blank_option_is_recorded():
    assert "d1c_hold_blank" in importcore.RECORDED_OPTIONS["d1c"]
