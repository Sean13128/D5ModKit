"""R7 (text bytes) and R8 (help link) of the class identity gate, and the repack helpers."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d5lib import classcheck, repack


def pack(tmp_path, family=11390, name="Strider", line1="Strider (Disgaea 1 Complete) - Strider",
         help_id=None, charhelp_ids=None):
    d = tmp_path / ("D1C_Class_%d" % family)
    (d / "patches" / "db").mkdir(parents=True)
    (d / "patches" / "classes").mkdir(parents=True)
    rows = [dict(id=family + r, help_id=family if help_id is None else help_id,
                 sprite_id=1540, color_id=1540 + r, name_EN=name, title_EN=name)
            for r in range(6)]
    (d / "patches" / "db" / "char.dat.json").write_text(
        json.dumps({"table": "char.dat", "added": rows}), encoding="utf-8")
    ids = [family] if charhelp_ids is None else charhelp_ids
    help_rows = [dict(id=i, char_id=i, line1_EN=line1, line1_JP=line1) for i in ids]
    (d / "patches" / "db" / "charhelp.dat.json").write_text(
        json.dumps({"table": "charhelp.dat", "added": help_rows}), encoding="utf-8")
    (d / "patches" / "db" / "charPersonal.dat.json").write_text(json.dumps(
        {"table": "charPersonal.dat",
         "added": [dict(id=family // 10 * 10 + r, voice_group=family // 10) for r in range(3)]}),
        encoding="utf-8")
    (d / "patches" / "classes" / ("class_%d.json" % family)).write_text(json.dumps(
        {"family": family, "kind": "humanoid", "sprite_family": 1540, "name": name,
         "hire_desc": line1, "unlocked": True, "unlocked_ranks": 6}), encoding="utf-8")
    (d / "patches" / "classes" / ("face_%d.png" % family)).write_bytes(b"\x89PNG\r\n")
    return d


def rules(findings, name):
    return [f for f in findings if f["rule"] == name]


# ------------------------------------------------------------------ R7
def test_ascii_pack_is_clean(tmp_path):
    d = pack(tmp_path)
    assert not rules(classcheck.check(d), "R7-text-bytes")
    assert not rules(classcheck.check(d), "R8-help-link")


def test_em_dash_in_charhelp_is_an_error(tmp_path):
    d = pack(tmp_path, line1="Strider (Disgaea 1 Complete) \u2014 Strider")
    found = rules(classcheck.check(d), "R7-text-bytes")
    latin = [f for f in found if f["field"] == "line1_EN"]
    assert latin and latin[0]["severity"] == "error"
    assert hex(0x2014) in latin[0]["codepoints"]
    # the CJK slot of the same fixture is a warning: those slots are UTF-8 in the vanilla table
    assert [f["severity"] for f in found if f["field"] == "line1_JP"] == ["warning"]


def test_em_dash_in_hire_desc_is_an_error(tmp_path):
    d = pack(tmp_path)
    spec = d / "patches" / "classes" / "class_11390.json"
    doc = json.loads(spec.read_text())
    doc["hire_desc"] = "Strider \u2014 6"
    spec.write_text(json.dumps(doc))
    found = rules(classcheck.check(d), "R7-text-bytes")
    assert any(f.get("field") == "hire_desc" for f in found)


def test_cjk_slot_is_a_warning_not_an_error(tmp_path):
    d = pack(tmp_path)
    p = d / "patches" / "db" / "charhelp.dat.json"
    doc = json.loads(p.read_text())
    doc["added"][0]["line1_JP"] = "\u30b9\u30c8\u30e9\u30a4\u30c0\u30fc"
    p.write_text(json.dumps(doc))
    found = rules(classcheck.check(d), "R7-text-bytes")
    assert found and all(f["severity"] == "warning" for f in found)


# ------------------------------------------------------------------ R8
def test_dangling_help_id_is_an_error(tmp_path):
    """The A/B probe defect: rows renumbered, charhelp moved, help_id left behind."""
    d = pack(tmp_path, family=11390, help_id=14080)
    found = rules(classcheck.check(d), "R8-help-link")
    assert len(found) == 6
    assert found[0]["help_id"] == 14080


def test_vanilla_help_id_is_accepted(tmp_path):
    d = pack(tmp_path, help_id=470)
    assert not rules(classcheck.check(d, vanilla_help_ids=[470]), "R8-help-link")
    assert rules(classcheck.check(d), "R8-help-link")


# ------------------------------------------------------------------ repack
def test_renumber_moves_every_derived_id(tmp_path):
    d = pack(tmp_path, family=11390)
    repack.renumber(d, {11390: 13210})
    rows = json.loads((d / "patches" / "db" / "char.dat.json").read_text())["added"]
    assert [r["id"] for r in rows] == list(range(13210, 13216))
    assert {r["help_id"] for r in rows} == {13210}
    help_rows = json.loads((d / "patches" / "db" / "charhelp.dat.json").read_text())["added"]
    assert [r["id"] for r in help_rows] == [13210] and help_rows[0]["char_id"] == 13210
    personal = json.loads((d / "patches" / "db" / "charPersonal.dat.json").read_text())["added"]
    assert {r["voice_group"] for r in personal} == {1321}
    spec = json.loads((d / "patches" / "classes" / "class_13210.json").read_text())
    assert spec["family"] == 13210 and spec["sprite_family"] == 1540
    assert not (d / "patches" / "classes" / "class_11390.json").exists()
    assert not rules(classcheck.check(d), "R8-help-link")


def test_renumber_keeps_the_art_keys(tmp_path):
    d = pack(tmp_path, family=11390)
    repack.renumber(d, {11390: 13210})
    rows = json.loads((d / "patches" / "db" / "char.dat.json").read_text())["added"]
    assert [r["sprite_id"] for r in rows] == [1540] * 6
    assert [r["color_id"] for r in rows] == [1540 + r for r in range(6)]
    spec = json.loads((d / "patches" / "classes" / "class_13210.json").read_text())
    assert spec["sprite_family"] == 1540


def test_renumber_refuses_a_non_multiple_of_ten(tmp_path):
    d = pack(tmp_path)
    with pytest.raises(ValueError):
        repack.renumber(d, {11390: 13215})


def test_ascii_text_rewrites_the_probe_text(tmp_path):
    d = pack(tmp_path, line1="Strider (Disgaea 1 Complete) \u2014 Strider")
    assert repack.ascii_text(d) == {"\u2014": 3}   # charhelp EN + JP slot and hire_desc
    assert not rules(classcheck.check(d), "R7-text-bytes")
    text = (d / "patches" / "db" / "charhelp.dat.json").read_text()
    assert "\u2014" not in text and " - Strider" in text


def test_ascii_text_refuses_an_unmapped_character(tmp_path):
    d = pack(tmp_path, line1="Strider \u2603")
    with pytest.raises(ValueError):
        repack.ascii_text(d)


# ------------------------------------------------------------------ R9
def test_a_description_that_overruns_the_menu_field_is_an_error(tmp_path):
    """255 bytes fit in the menu's 0x100 field; 256+ overwrite the fields after it (D1CFREEZE)."""
    long_text = "Strider (Disgaea 1 Complete). " + "x" * 300
    d = pack(tmp_path)
    spec_path = d / "patches" / "classes" / "class_11390.json"
    spec = json.loads(spec_path.read_text())
    spec["hire_desc"] = long_text
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    found = rules(classcheck.check(d), "R9-desc-length")
    assert found and found[0]["severity"] == "error"
    assert found[0]["bytes"] == len(long_text.encode()) and found[0]["max"] == classcheck.DESC_MAX


def test_the_shipped_d1c_descriptions_were_over_the_limit(tmp_path):
    """The exact lengths of the 13 TEST13 packs: 6 were past 255 and 11390 (273) froze LIVE10."""
    for n in (255, 256, 273, 280):
        d = pack(tmp_path / str(n), family=11390)
        spec_path = d / "patches" / "classes" / "class_11390.json"
        spec = json.loads(spec_path.read_text())
        spec["hire_desc"] = "a" * n
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        found = rules(classcheck.check(d), "R9-desc-length")
        assert bool(found) == (n > 255), n


def test_desc_text_bounds_and_marks_a_cut():
    from d5lib import newclasses
    assert newclasses.desc_text("short") == "short"
    text = "word " * 100
    cut = newclasses.desc_text(text)
    assert len(cut.encode()) <= classcheck.DESC_MAX and cut.endswith(" ...")
    assert cut.startswith("word word")
    # a cut lands on a word boundary, never mid-word
    assert not cut[:-4].endswith("wor")
