"""D4FACE1: the face the game draws for a D4 character row (rule D4-FACE-02, FUN_14047bfb0 / FUN_1401b1430)."""
import importlib.util
from pathlib import Path

import pytest

from d5lib import d4screenart, sourceimports


def test_class_and_rank_rows_use_the_class_face():
    # Armor Knight 1081 -> swf1080; Medic 1241 -> swf1240 (exists); Death 2125 -> swf2120
    assert d4screenart.game_face_number(1081, 1081) == 1080
    assert d4screenart.game_face_number(1085, 1085) == 1080
    assert d4screenart.game_face_number(1241, 1241) == 1240
    assert d4screenart.game_face_number(2125, 2125) == 2120


def test_npc_rows_use_their_class_face():
    # D4-PROOF: Chief 1154 -> 1150, Kojiro 1142 -> 1140, Arsailles 2144 -> 2140, Tromayer 1014 -> 1010
    for row, colour, face in ((5301, 1154, 1150), (4390, 1142, 1140), (5308, 2144, 2140), (5305, 1014, 1010),
                              (5307, 1034, 1030), (5309, 1134, 1130), (5310, 1104, 1100), (5388, 1184, 1180),
                              (5306, 1084, 1080)):
        assert d4screenart.game_face_number(row, colour) == face


def test_low_ids_keep_their_colour_id():
    assert d4screenart.game_face_number(180, 54) == 54          # Des X
    assert d4screenart.game_face_number(220, 74) == 74          # Nemo
    assert d4screenart.game_face_number(170, 170) == 170
    assert d4screenart.game_face_number(0, 54) == -1


def test_the_special_id_range_flips_the_rule():
    assert d4screenart.uses_own_colour_face(0x1520) is True     # 0x1518..0x157b ...
    assert d4screenart.uses_own_colour_face(0x1535) is False    # ... except 0x1530..0x1539
    assert d4screenart.game_face_number(0x1535, 1237) == 1230
    assert d4screenart.game_face_number(0x1520, 1237) == 1237


def test_matches_the_goal1_reader_over_a_wide_range():
    """Ground truth: the Goal 1 reader's selection.py (Unicorn-proven, 154,613 cases); loaded by path, never imported
    by the kit.  Skipped when the project's Tools folder is not next to the kit."""
    ref = Path(__file__).resolve().parents[2] / "Tools" / "source_readers" / "d4" / "selection.py"
    if not ref.is_file():
        for up in Path(__file__).resolve().parents:
            if (up / "Tools" / "source_readers" / "d4" / "selection.py").is_file():
                ref = up / "Tools" / "source_readers" / "d4" / "selection.py"
                break
    if not ref.is_file():
        ref = Path("/Volumes/Data/Projects/D5/Tools/source_readers/d4/selection.py")
    if not ref.is_file():
        pytest.skip("reader selection.py not available")
    spec = importlib.util.spec_from_file_location("goal1_selection", ref)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for cid in list(range(-50, 6000)) + list(range(0x1500, 0x1600)) + [70000]:
        for colour in (0, 7, 54, 74, 1081, 1154, 2144, 5):
            for flag in (0, 1):
                assert d4screenart.game_face_number(cid, colour, flag) == mod.face_number(cid, colour, flag), (cid, colour, flag)


def test_class_face_files_puts_the_class_face_on_every_slot():
    assert sourceimports.class_face_files("f.png", 1240, True, True) == ["f.png"] * 10
    assert sourceimports.class_face_files("f.png", 1240, False, True) == ["f.png"]    # no D4 source: one face


def test_old_path_keeps_the_colour_variants(monkeypatch):
    monkeypatch.setattr(sourceimports, "colour_variants", lambda p, b, c=10: [f"swf{b + k}.png" for k in range(c)])
    assert sourceimports.class_face_files("swf1080.png", 1080, True, False)[3] == "swf1083.png"
    monkeypatch.setattr(sourceimports, "colour_variants", lambda p, b, c=10: None)       # Medic: swf1241 does not exist
    assert sourceimports.class_face_files("swf1240.png", 1240, True, False) == ["swf1240.png"]


def test_npc_art_ids_face_rule(monkeypatch):
    from d5lib.importers import d4 as d4imp

    class Files:
        def data(self, lang="EN"):
            class Data:
                chars = {5301: {"color_id": 1154}}
            return Data()

    imp = d4imp.Importer()
    monkeypatch.setattr(d4imp.Importer, "_npc_lease", staticmethod(lambda sid: {"npc": True}))
    monkeypatch.setattr(imp, "source", lambda *a, **k: Files())
    assert imp._art_ids(5301) == ([1150], [1154])                                   # face rounded, cut-in colour key
    assert imp._art_ids(5301, {"d4_face_rule": True}) == ([1150], [1154])
    assert imp._art_ids(5301, {"d4_face_rule": False}) == ([1154], [1154])           # old path


def test_the_option_is_recorded_and_defaults_on():
    from d5lib import importcore
    assert "d4_face_rule" in importcore.RECORDED_OPTIONS["d4"]


# ------------------------------------------------------------------ the audit (tools/d4_face_audit.py)
def _audit_module():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import d4_face_audit
    return d4_face_audit


class _FakeSource:
    """Two faces: swf1080 (red) and swf1081 (blue); rows 1080..1085 of a class whose colour id is the row id."""

    def __init__(self):
        from PIL import Image
        self.images = {1080: Image.new("RGBA", (32, 32), (200, 20, 20, 255)),
                       1081: Image.new("RGBA", (32, 32), (20, 20, 200, 255))}

    def face(self, n):
        return self.images.get(n) or self.images[1080]

    def row(self, sid):
        return {"color_id": sid}


def _class_pack(tmp_path, per_slot):
    import json
    pack = tmp_path / "D4_Class_1080"
    classes = pack / "patches" / "classes"
    classes.mkdir(parents=True)
    (pack / "mod.json").write_text(json.dumps({"source_import": {"source_ranks": [{"id": 1080 + k} for k in range(6)]}}))
    (classes / "class_14080.json").write_text(json.dumps({"family": 14080}))
    for k, image in per_slot.items():
        image.save(classes / ("face_14080.png" if k == 0 else f"face_14080_{k}.png"))
    return pack


def test_face_audit_passes_the_class_face_and_catches_rank_colour_faces(tmp_path):
    audit = _audit_module()
    src = _FakeSource()
    good = _class_pack(tmp_path / "good", {k: src.images[1080] for k in range(6)})
    rows = audit.audit_pack(src, good)
    assert [r["status"] for r in rows] == ["equal"] * 6 and not audit.gate(rows)
    # negative control: the old per-colour layout (slot 1 holds swf1081, the rank colour's face)
    bad = _class_pack(tmp_path / "bad", {0: src.images[1080], 1: src.images[1081]})
    rows = audit.audit_pack(src, bad)
    assert rows[1]["status"] == "differs" and audit.gate(rows)


def test_face_audit_reads_a_missing_slot_through_the_kit_fallback(tmp_path):
    audit = _audit_module()
    src = _FakeSource()
    only0 = _class_pack(tmp_path, {0: src.images[1080]})
    rows = audit.audit_pack(src, only0)
    assert [r["status"] for r in rows] == ["equal"] + ["fallback"] * 5 and not audit.gate(rows)
