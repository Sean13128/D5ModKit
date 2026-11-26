"""REPROFIX3: the hold pass runs on D4 and DD2 too, the held ids are recorded for no-install builds,
and D4_Unique_5305's installed evility row is in the overlay.

REPROFIX2 held BLANKKEYS1's blank key times in the D1C importer, decided by the installed pack.  The
same rule now lives in ``d5lib/holdblank.py`` and runs in ``importers/d4.py`` and ``dd2.py``
(Politan anm00506, Pringer Z anm00676, Baal Slave anm00683).  A machine with no installed pack holds
the ids recorded in ``held-blank-keys.json`` instead, so both paths hold the same animations.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import anm, holdblank, importcore
from d5lib.importers import d1c, d4, dd2

ANIME = Path("files/Anime/ANM_HI_JP.dat")
PACKS = Path(__file__).resolve().parents[1] / "d5lib/importers"


def _bank_anm(blank_at=None):
    """A sprite bank with the two page ids motion_banks() looks for (1001 front, 1007 back).

    1001 draws on every key time.  1007 draws on key 0, and on 20 only when ``blank_at`` is not 20 --
    the shape a whole-body import leaves behind when the donor's body moved on another track."""
    node = lambda first, count, child=-1, nxt=-1, id_=0: anm.Node(id_, 0, 0, 0, 0, 0, first, count, child, nxt)
    k20 = anm.Key(20, 0, 0, 0, 0, 0) if blank_at == 20 else anm.Key(20, 0, 1, 3, 0, 0)
    keys = [anm.Key(0, 1, 0, 0, 0, 0), anm.Key(40, 2, 0, 0, 0, 0),
            anm.Key(0, 0, 1, 3, 0, 0), anm.Key(40, 0, 1, 3, 0, 0),
            anm.Key(0, 1, 0, 0, 0, 0), anm.Key(40, 2, 0, 0, 0, 0),
            anm.Key(0, 0, 1, 3, 0, 0), k20]
    nodes = [node(0, 2, child=1), node(2, 2), node(4, 2, child=3), node(6, 2)]
    anims = [anm.Animation(1001, 0), anm.Animation(1007, 2)]
    cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 8, 8, 0)]
    return anm.AnmFile([anm.AnmBlock(1, animations=anims, nodes=nodes, keys=keys, cells=cells)], [], [])


def _write(root, folder, bank="anm00506.lzs", blank_at=None):
    d = Path(root) / folder / ANIME
    d.mkdir(parents=True, exist_ok=True)
    f = d / bank
    f.write_bytes(anm.lzs_compress(_bank_anm(blank_at).to_bytes()))
    return f


def _ids(path):
    return sorted({a.id for a in anm.load(path).blocks[0].animations})


def _reference(tmp_path, game, folder, banks):
    doc = {"schema": "held-blank-keys/1", "games": {game: {folder: banks}}}
    f = tmp_path / "held-blank-keys.json"
    f.write_text(json.dumps(doc))
    return f


def test_d4_holds_the_installed_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("D5_INSTALLED_MODS", str(tmp_path / "installed"))
    built = _write(tmp_path / "build", "D4_Unique_999999", blank_at=20)
    _write(tmp_path / "installed", "D4_Unique_999999")
    held, source = d4.Importer()._hold_blank_keys(
        SimpleNamespace(mod_folder="D4_Unique_999999"), built.parents[3], {"installed_reference": True})
    assert source == "installed"
    assert held == {"anm00506.lzs": {1007: 2}}, held


def test_dd2_holds_the_installed_reference(tmp_path):
    built = _write(tmp_path / "build", "DD2_Unique_999998", blank_at=20)
    _write(tmp_path / "installed", "DD2_Unique_999998")
    held, source = dd2.Importer()._hold_blank_keys(
        SimpleNamespace(mod_folder="DD2_Unique_999998"), built.parents[3],
        {"installed_root": tmp_path / "installed"})
    assert source == "installed"
    assert held == {"anm00506.lzs": {1007: 2}}, held


def test_no_install_holds_the_recorded_ids(tmp_path, monkeypatch):
    """INSTALLED_MODS at an empty folder holds the same ids as a build against the install."""
    monkeypatch.setenv("D5_INSTALLED_MODS", str(tmp_path / "installed"))
    ref = _write(tmp_path / "reference", "D4_Unique_999997", blank_at=20)
    _write(tmp_path / "installed", "D4_Unique_999997")
    entry = SimpleNamespace(mod_folder="D4_Unique_999997")
    with_install, source = d4.Importer()._hold_blank_keys(entry, ref.parents[3], {"installed_reference": True})
    assert source == "installed" and with_install

    no_install = _write(tmp_path / "empty-build", "D4_Unique_999997", blank_at=20)
    monkeypatch.setattr(holdblank, "REFERENCE_FILE",
                        _reference(tmp_path, "d4", "D4_Unique_999997",
                                   {"anm00506.lzs": sorted(with_install["anm00506.lzs"])}))
    monkeypatch.setattr(holdblank, "_REFERENCE", None)
    monkeypatch.setenv("D5_INSTALLED_MODS", str(tmp_path / "no-install-here"))
    held, source = d4.Importer()._hold_blank_keys(entry, no_install.parents[3])
    assert source == "reference"
    assert sorted(held["anm00506.lzs"]) == sorted(with_install["anm00506.lzs"])


def test_an_installed_bank_decides_alone(tmp_path, monkeypatch):
    """With an installed bank to compare, the recorded ids are not used: an install that is blank at the same key
    times means nothing is held, even when the file lists the animation."""
    monkeypatch.setenv("D5_INSTALLED_MODS", str(tmp_path / "installed-a"))
    ref = _write(tmp_path / "reference", "D4_Unique_999995", blank_at=20)
    _write(tmp_path / "installed-a", "D4_Unique_999995")
    entry = SimpleNamespace(mod_folder="D4_Unique_999995")
    listed, _ = d4.Importer()._hold_blank_keys(entry, ref.parents[3], {"installed_reference": True})
    assert listed                                                   # the ids the file will list

    monkeypatch.setattr(holdblank, "REFERENCE_FILE",
                        _reference(tmp_path, "d4", "D4_Unique_999995",
                                   {"anm00506.lzs": sorted(listed["anm00506.lzs"])}))
    monkeypatch.setattr(holdblank, "_REFERENCE", None)
    monkeypatch.setenv("D5_INSTALLED_MODS", str(tmp_path / "installed-b"))
    _write(tmp_path / "installed-b", "D4_Unique_999995", blank_at=20)    # the install is blank there too
    built = _write(tmp_path / "build", "D4_Unique_999995", blank_at=20)
    before = built.read_bytes()
    held, source = d4.Importer()._hold_blank_keys(entry, built.parents[3], {"installed_reference": True})
    assert held == {} and source is None
    assert built.read_bytes() == before


def test_a_pack_absent_from_the_file_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(holdblank, "REFERENCE_FILE",
                        _reference(tmp_path, "d4", "D4_Unique_1", {"anm00506.lzs": [1007]}))
    monkeypatch.setattr(holdblank, "_REFERENCE", None)
    monkeypatch.setenv("D5_INSTALLED_MODS", str(tmp_path / "no-install-here"))
    built = _write(tmp_path / "build", "D4_Unique_999996", blank_at=20)
    before = built.read_bytes()
    held, source = d4.Importer()._hold_blank_keys(
        SimpleNamespace(mod_folder="D4_Unique_999996"), built.parents[3])
    assert held == {} and source is None
    assert built.read_bytes() == before


def test_d1c_uses_the_file_when_no_pack_is_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(holdblank, "REFERENCE_FILE",
                        _reference(tmp_path, "d1c", "D1C_Class_999995", {"anm02720.lzs": [1007]}))
    monkeypatch.setattr(holdblank, "_REFERENCE", None)
    mine = _write(tmp_path / "build", "D1C_Class_999995", bank="anm02720.lzs", blank_at=20)
    imp = d1c.Importer()
    imp._ctx = dict(installed_root=tmp_path / "no-install-here", installed_reference=True)
    held = imp._hold_blank_keys(mine.parents[3], lambda _s: None)
    assert sorted(held["anm02720.lzs"]) == [1007], held


def test_held_blank_keys_file_records_the_measured_packs():
    doc = json.loads((PACKS / "held-blank-keys.json").read_text())
    assert doc["schema"] == "held-blank-keys/1"
    games = doc["games"]
    assert games["d1c"]["D1C_Class_11840"] == {"anm02720.lzs": [1501, 1507, 2071, 3071, 4011]}
    assert games["d4"]["D4_Unique_610"] == {"anm00506.lzs": [2077, 3077, 4017]}
    assert games["dd2"]["DD2_Unique_300"] == {"anm00676.lzs": [2077, 3077, 4017]}
    assert games["dd2"]["DD2_Unique_640"] == {"anm00683.lzs": [2077, 3077, 4017]}
    for packs in games.values():
        for banks in packs.values():
            for bank, ids in banks.items():                 # ids only: bank file name + animation ids
                assert bank.startswith("anm") and bank.endswith(".lzs")
                assert ids and all(isinstance(i, int) for i in ids)


def test_hold_options_are_recorded():
    assert "d4_hold_blank" in importcore.RECORDED_OPTIONS["d4"]
    assert "dd2_hold_blank" in importcore.RECORDED_OPTIONS["dd2"]


def test_d4_5305_installed_row_is_labelled_and_in_the_overlay():
    from d4rules import additions as _rule_additions, mods as _rule_mods
    add = _rule_additions()["mods"]["D4_Unique_5305"]
    over = _rule_mods()["D4_Unique_5305"]
    assert add["installed_rows"] is True and add["adaptations"]
    assert [r["id"] for r in add["skill_rows"]] == [7126]
    assert add["aliases"] == {"7126": 1010}
    assert add["char_links"]["18230"]["evility1"] == 7126
    assert "D5 evility 1010" in add["adaptations"][0]
    assert [r["id"] for r in over["skill_rows"]] == [7126]
    assert over["aliases"]["7126"] == 1010
    assert over["char_links"]["18230"]["evility1"] == 7126


def test_motion_banks_ignores_portrait_and_identity_banks(tmp_path):
    _write(tmp_path / "pack", "X", bank="anm00506.lzs")
    _write(tmp_path / "pack", "X", bank="anm10506.lzs")          # cut-in bank: id >= 10000
    found = [b.name for b, _ids in holdblank.motion_banks(tmp_path / "pack" / "X")]
    assert found == ["anm00506.lzs"]
