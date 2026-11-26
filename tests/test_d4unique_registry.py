"""The D4 unique importer on a registry identity (decision 2026-10-27).

A D4 unique is one rank on a registry class identity (>= 10000) whose char.dat row id equals that
identity, with its sprite / companion / standing picture / face / cut-in keyed to a low "physical"
row leased for it — the same shape the D1 Complete batch builds (d5lib/nativeimports.unique_identity).

These tests pin this importer's half of that contract: the shape it accepts, and the collisions it
must refuse before anything is written.  The finalizer's colour-key handling, classcheck R6 and the
ownership band are pinned by tests/test_unique_registry.py.
"""
import json
import os

import pytest

from d5lib import d4unique


# -------------------------------------------------------------------------------------------- the shape
def test_a_low_shape_is_the_legacy_one():
    assert d4unique.unique_shape(470) == dict(identity=470, physical=470, registry=False)


def test_a_registry_shape_leases_the_art_row():
    got = d4unique.unique_shape(470, 10220, 919)
    assert got["identity"] == 10220 and got["physical"] == 919 and got["registry"] is True
    assert got["keyed"] == [919, 920, 921, 10919, 10920]


@pytest.mark.parametrize("identity,physical", [
    (9990, 919),       # below the unique registry band
    (20000, 919),      # Overlord's reserved band
    (10225, 919),      # not a rank-0 multiple of ten
    (10220, 10220),    # the identity may not be its own art lease
    (10220, 1000),     # the art lease must be a low id
    (32770, 919),      # past the range the receiver accepts
])
def test_a_registry_shape_outside_the_contract_is_refused(identity, physical):
    with pytest.raises(ValueError):
        d4unique.unique_shape(470, identity, physical)


# ----------------------------------------------------------------------------------------- collisions
class _Table:
    """The two things check_conflicts reads from a char.dat table."""

    def __init__(self, ids):
        self.rows = [dict(id=i) for i in ids]

    def index_of(self, row_id):
        for k, row in enumerate(self.rows):
            if row["id"] == row_id:
                return k
        return -1


class _Mod:
    def __init__(self, folder, files=()):
        self.folder = folder
        self.id = os.path.basename(str(folder))
        self.patches_dir = os.path.join(str(folder), "patches")
        self._files = list(files)

    def load_patch(self, kind, name):
        path = os.path.join(self.patches_dir, kind, name)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list_files(self):
        return list(self._files)


def _tables(ids):
    return {"char.dat": _Table(ids)}


def test_a_clean_lease_passes(tmp_path):
    got = d4unique.check_conflicts(_tables([10, 470]), [], 10220, physical=919, graphics=())
    assert got["conflicts"] == [] and got["keyed_graphics"] == [919, 920, 921, 10919, 10920]


def test_an_answered_identity_is_refused():
    with pytest.raises(ValueError, match="already carries"):
        d4unique.check_conflicts(_tables([10, 10220]), [], 10220, physical=919)


def test_a_physical_row_that_is_a_real_character_is_refused():
    with pytest.raises(ValueError, match="would replace"):
        d4unique.check_conflicts(_tables([10, 919]), [], 10220, physical=919)


def test_art_keys_the_game_already_uses_are_refused():
    with pytest.raises(ValueError, match="allocation collision"):
        d4unique.check_conflicts(_tables([10]), [], 10220, physical=919, graphics=[10920])


def test_another_mod_claiming_the_identity_or_its_art_is_refused(tmp_path):
    folder = tmp_path / "Other_Mod"
    os.makedirs(folder / "patches" / "db")
    (folder / "patches" / "db" / "char.dat.json").write_text(
        json.dumps(dict(table="char.dat", added=[dict(id=10220)])), encoding="utf-8")
    with pytest.raises(ValueError, match="allocation collision"):
        d4unique.check_conflicts(_tables([10]), [_Mod(folder)], 10220, physical=919)
    (folder / "patches" / "db" / "char.dat.json").write_text(
        json.dumps(dict(table="char.dat", added=[dict(id=919)])), encoding="utf-8")
    with pytest.raises(ValueError, match="allocation collision"):
        d4unique.check_conflicts(_tables([10]), [_Mod(folder)], 10220, physical=919)


def test_another_mod_shipping_the_art_file_is_refused(tmp_path):
    folder = tmp_path / "Other_Mod"
    os.makedirs(folder / "patches")
    with pytest.raises(ValueError, match="allocation collision"):
        d4unique.check_conflicts(_tables([10]), [_Mod(folder, ["Anime/ANM_HI_JP.dat/anm00919.lzs"])],
                                 10220, physical=919)


def test_the_legacy_low_shape_is_unchanged():
    # A real (non-dummy) low row is refused; a kit dummy row is a legal legacy target.
    with pytest.raises(ValueError, match="unused low unique ID"):
        d4unique.check_conflicts(_tables([10, 470]), [], 10)
    got = d4unique.check_conflicts(_tables([10, 470]), [], 470)
    assert got["physical"] == 470 and got["keyed_graphics"] == [470, 471, 472, 10470, 10471]
