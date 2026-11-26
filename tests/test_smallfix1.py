"""SMALLFIX1: face template gate (blank portrait), DRPG class titles."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from d5lib import importcore  # noqa: E402
from d5lib.importers import drpg_titles  # noqa: E402


def _pack(tmp_path, rows, unique=None):
    (tmp_path / "patches/db").mkdir(parents=True)
    (tmp_path / "patches/db/char.dat.json").write_text(json.dumps({"table": "char.dat", "added": rows}))
    if unique is not None:
        (tmp_path / "patches/characters").mkdir(parents=True)
        (tmp_path / "patches/characters/unique.json").write_text(json.dumps(unique))
    return tmp_path


LOW = dict(id=931, sprite_id=931, color_id=931)


def test_low_row_without_template_fails(tmp_path):
    ok, why = importcore.face_template_gate(_pack(tmp_path, [LOW]))
    assert not ok and "931" in why


def test_low_row_with_declared_template_passes(tmp_path):
    u = dict(schema=1, identity=931, physical=931, template=2190, template_colour=2190, kind="monster")
    assert importcore.face_template_gate(_pack(tmp_path, [LOW], u))[0]


def test_registry_and_drpg_rows_are_not_flagged(tmp_path):
    rows = [dict(id=10620, sprite_id=516, color_id=516), dict(id=743, sprite_id=16730, color_id=16730)]
    assert importcore.face_template_gate(_pack(tmp_path, rows))[0]


def test_installed_style_shark_king_and_xenolith_fail_without_unique_json(tmp_path):
    for cid in (931, 941):
        d = tmp_path / str(cid)
        d.mkdir()
        assert not importcore.face_template_gate(_pack(d, [dict(id=cid, sprite_id=cid, color_id=cid)]))[0]


# ---- DRPG titles
def test_title_table_is_complete_and_fits_the_field():
    doc = drpg_titles.load()
    assert len(doc["titles"]) + len(doc["no_source_title"]) == 146
    for base, t in doc["titles"].items():
        assert t["jp"] and t["en"] and t["en"] != drpg_titles.PLACEHOLDER, base
        assert t["en"].isascii() and len(t["en"].encode()) <= 67 and len(t["jp"].encode()) <= 67, base
        assert t["en_source"].startswith(("provisional", "official", "community")), base


def _drpg_pack(tmp_path, rows):
    return _pack(tmp_path, rows)


def test_apply_replaces_the_group_label_and_gate_agrees(tmp_path):
    rows = [dict(id=743, title_EN="Disgaea RPG", title_FR="Disgaea RPG", title_JP="Disgaea RPG",
                 title_CHN="Disgaea RPG", title_KOR="Disgaea RPG"),
            dict(id=30410, title_EN="Disgaea RPG", title_FR="Disgaea RPG", title_JP="Disgaea RPG",
                 title_CHN="Disgaea RPG", title_KOR="Disgaea RPG")]
    pack = _drpg_pack(tmp_path, rows)
    base = int(next(iter(drpg_titles.load()["titles"])))
    assert not drpg_titles.gate(pack, base)[0]                  # placeholder fails the gate
    assert drpg_titles.apply(pack, base) == 2
    assert drpg_titles.gate(pack, base)[0]
    t = drpg_titles.title_of(base)
    got = json.loads((pack / "patches/db/char.dat.json").read_text())["added"]
    assert all(r["title_EN"] == t["en"] and r["title_FR"] == t["en"] and r["title_JP"] == t["jp"] for r in got)


def test_no_source_title_keeps_label_and_is_named(tmp_path):
    base = int(next(iter(drpg_titles.load()["no_source_title"])))
    rows = [dict(id=1, title_EN="Disgaea RPG", title_JP="Disgaea RPG")]
    pack = _drpg_pack(tmp_path, rows)
    assert drpg_titles.apply(pack, base) == 0
    assert drpg_titles.gate(pack, base)[0]
    assert not drpg_titles.gate(pack, 999999)[0]                # an unlisted character is not waved through
