"""REPROFIX2 run 2: every difference in the final 245-pack table carries the right reason.

``repro_compare`` labels a cut-in record in mod.json: the DRPGCUTIN2 overlay writes the cutin
path/provenance/sha256 (and the assets.provenance flip it causes) into the staged pack, not into the
importer, so a rebuild that does not carry the overlay is not different content.  ``repro_table``
names the content causes (DRPGPARTY1's D4 sub evilities the DRPGEVIL2 install predates; the
samples_untouched bases; BLANKKEYS1's held D4/DD2 banks; the D4 skill/voice rows) and the label-only
causes (REPROFIX1's importer_options, receipts).
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


table = _load("repro_table_tested", "tools/repro_table.py")
compare = _load("repro_compare_tested", "tools/repro_compare.py")


def _cmp(tmp_path, a, b):
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(a))
    pb.write_text(json.dumps(b))
    return compare.cmp_json(pa, pb, True)


def _cutin_modjson():
    look = {"id": 60019, "assets": {"provenance": "original",
                                    "files": {"cutin": {"path": "own-cutins/60019.png",
                                                        "sha256": "ab" * 32,
                                                        "provenance": "illustration"}}}}
    return {"source_import": {"leased_ids": {"looks": [look]}}}


def _no_cutin_modjson():
    look = {"id": 60019, "assets": {"provenance": "mixed-original-and-derived", "files": {}}}
    return {"source_import": {"leased_ids": {"looks": [look]}}}


def test_cutin_record_is_a_label_not_content(tmp_path):
    v, d = _cmp(tmp_path, _cutin_modjson(), _no_cutin_modjson())
    assert v == "label"
    assert "cut-in metadata" in d and "(0 content)" in d


def test_signature_evility_stays_content(tmp_path):
    v, _ = _cmp(tmp_path, {"source_import": {"signature_evility": "source"}}, {"source_import": {}})
    assert v == "content"


def test_old_record_cutin_only_detail_is_reclassified():
    """A record made before the carve-out (no marker) still reclassifies when every content leaf is cut-in."""
    detail = ("21 leaf path(s) (4 content): source_import.leased_ids.looks[id=60019].assets.files.cutin.path; "
              "source_import.leased_ids.looks[id=60019].assets.files.cutin.provenance; "
              "source_import.leased_ids.looks[id=60019].assets.files.cutin.sha256; "
              "source_import.leased_ids.looks[id=60019].assets.provenance; "
              "source_import.importer_options.entry")
    assert table.reclass(dict(verdict="content", kind="mod.json", file="mod.json", detail=detail)) == "label"


def test_old_record_with_a_real_content_leaf_stays_content():
    detail = ("2 leaf path(s) (1 content): source_import.signature_evility; "
              "source_import.importer_options.entry")
    assert table.reclass(dict(verdict="content", kind="mod.json", file="mod.json", detail=detail)) == "content"


def test_truncated_detail_is_not_reclassified():
    """When more content leaves exist than the detail lists, the tool must not guess."""
    detail = ("9 leaf path(s) (9 content): source_import.leased_ids.looks[id=1].assets.files.cutin.path; "
              "source_import.leased_ids.looks[id=1].assets.provenance")
    assert table.reclass(dict(verdict="content", kind="mod.json", file="mod.json", detail=detail)) == "content"


def _x(file, kind, detail=""):
    return dict(file=file, kind=kind, detail=detail)


def test_drpg_sample_and_core_evilities_are_named():
    sample = table.cause("DRPG_Sample_Citri", _x("patches/db/char.dat.json", "table"))
    core = table.cause("DRPG_Core_Bieko_116", _x("patches/evilities/evilities.json", "table"))
    assert sample == "SAMPLE" and core == "DRPGEVIL"


def test_held_d4_and_dd2_banks_are_hold_not_art():
    held = "art/structure: {'art': 3} of 62 animations; differing ids [2077, 3077, 4017]"
    assert table.cause("D4_Unique_610", _x("files/Anime/ANM_HI_JP.dat/anm00506.lzs", "bank", held)) == "HOLD"
    assert table.cause("DD2_Unique_300", _x("files/Anime/ANM_HI_JP.dat/anm00676.lzs", "bank", held)) == "HOLD"
    other = "art/structure: {'art': 3} of 62 animations; differing ids [1001, 1007]"
    assert table.cause("D4_Unique_610", _x("files/Anime/ANM_HI_JP.dat/anm00506.lzs", "bank", other)) == "ART"


def test_d4_skill_and_voice_rows_are_named():
    learn = "5 leaf path(s); rows ['18290']; fields ['learn1_skill']; first added[id=18290].learn1_skill"
    voice = "1 leaf path(s); rows ['10260']; fields ['voice_id']"
    assert table.cause("D4_Unique_5388", _x("patches/db/char.dat.json", "table", learn)) == "D4SKILL"
    assert table.cause("D4_Unique_5388", _x("patches/db/magic.dat.json", "table")) == "D4SKILL"
    assert table.cause("D4_Unique_210", _x("patches/db/char.dat.json", "table", voice)) == "D4VOICE"
    assert table.cause("D4_Unique_5305", _x("patches/db/Skill.dat.json", "table")) == "D4EVIL"


def test_label_causes():
    assert table.label_cause("D1C_Class_11390", _x("mod.json", "mod.json")) == "OPTIONS"
    assert table.label_cause("DRPG_Core_Bieko_116", _x("patches/voices/drpg-voice-receipt.json", "table")) == "RECEIPT"
    cutin = "13 leaf path(s) (4 content) (cut-in metadata: label): source_import.leased_ids.looks[id=1]..."
    assert table.label_cause("DRPG_Core_DarkLordValvolga_60025", _x("mod.json", "mod.json", cutin)) == "DRPGCUTIN"
