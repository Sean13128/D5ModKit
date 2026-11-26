"""REPROFIX4: the D4 importer writes the silent voice for characters the source game does not voice
(Pringer X 210, Politan 610; VOICESILENT1's rule), and D4_Unique_5388's installed magic rows are pinned."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import d4source, d4voices, drpgvoice
from d5lib.importers import d4

IMPORTERS = Path(__file__).resolve().parents[1] / "d5lib/importers"
NONE = dict(row=610, name="Politan", body=610, groups=[610],
            per_lang={l: dict(table_rows=0, archive_members=0, table_total=9, archive_total=9) for l in ("EN", "JP")})


def _pack(tmp_path):
    mod = tmp_path / "D4_Unique_610"
    (mod / "patches/db").mkdir(parents=True)
    (mod / "patches/voices").mkdir()
    (mod / "patches/voices/stale.vag").write_bytes(b"x")
    (mod / "patches/db/char.dat.json").write_text(json.dumps(
        {"table": "char.dat", "added": [{"id": 18190, "voice_id": 2020}]}, indent=1) + "\n")
    (mod / "mod.json").write_text(json.dumps({"name": "Politan", "source_import": {"source_id": 610}}, indent=2) + "\n")
    return mod


def _fake_source(monkeypatch):
    monkeypatch.setattr(d4source, "D4Data", lambda root, lang="EN", locate=None: SimpleNamespace(
        chars={610: {"voice_group_base": 610, "body": 610, "name": "Politan"}}))


def test_silent_when_the_source_has_no_voice(tmp_path, monkeypatch):
    _fake_source(monkeypatch)
    monkeypatch.setattr(d4voices, "source_voice_facts", lambda root, row, locate=None: NONE)
    called = []
    monkeypatch.setattr(d4voices, "import_d4_voice", lambda *a, **k: called.append(1))
    mod = _pack(tmp_path)
    d4.Importer()._voices(mod, 610, class_=False, source=tmp_path)
    row = json.loads((mod / "patches/db/char.dat.json").read_text())["added"][0]
    assert row["voice_id"] == drpgvoice.SILENT_VOICE_ID == 5999
    meta = json.loads((mod / "mod.json").read_text())
    assert meta["source_import"]["voice"].startswith("silent, as in the source game (Disgaea 4 Complete+: voice group 610")
    assert meta["source_import"]["source_id"] == 610
    assert (mod / "mod.json").read_text().startswith('{\n  "name"')          # indent 2 kept (keep_layout)
    assert not (mod / "patches/voices").exists() and not called
    assert d4.Importer()._features(mod)["voice"] == "silent"


def test_a_voiced_character_still_imports_its_own_voice(tmp_path, monkeypatch):
    _fake_source(monkeypatch)
    facts = json.loads(json.dumps(NONE))
    facts["per_lang"]["EN"]["table_rows"] = 12
    monkeypatch.setattr(d4voices, "source_voice_facts", lambda root, row, locate=None: facts)
    calls = []
    monkeypatch.setattr(d4voices, "import_d4_voice", lambda *a, **k: calls.append(k["source_language"]))
    mod = _pack(tmp_path)
    d4.Importer()._voices(mod, 610, class_=False, source=tmp_path, lease={"voice_id": 9100})
    assert calls == ["EN", "JP"]
    assert json.loads((mod / "patches/db/char.dat.json").read_text())["added"][0]["voice_id"] == 9100
    assert "voice" not in json.loads((mod / "mod.json").read_text())["source_import"]


def test_class_voices_never_go_silent(tmp_path, monkeypatch):
    _fake_source(monkeypatch)
    monkeypatch.setattr(d4voices, "source_voice_facts", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    monkeypatch.setattr(d4voices, "import_d4_voice", lambda *a, **k: None)
    monkeypatch.setattr(d4.Importer, "_voice_id", lambda self, *a, **k: 9000)
    mod = _pack(tmp_path)
    d4.Importer()._voices(mod, 610, class_=True, source=tmp_path)
    assert json.loads((mod / "patches/db/char.dat.json").read_text())["added"][0]["voice_id"] != 5999


def test_facts_helpers():
    assert not d4voices.source_has_voice(NONE)
    voiced = json.loads(json.dumps(NONE))
    voiced["per_lang"]["JP"]["archive_members"] = 1
    assert d4voices.source_has_voice(voiced)
    two = dict(NONE, groups=[210, 5405])
    assert "voice group 210 and 5405 not found" in d4voices.silent_why(two)


def test_5388_magic_rows_pin_to_the_installed_ids(tmp_path):
    built = tmp_path / "D4_Unique_5388"
    (built / "patches/db").mkdir(parents=True)
    (built / "patches/skills").mkdir(parents=True)
    (built / "patches/db/magic.dat.json").write_text(json.dumps(
        {"table": "magic.dat", "added": [{"id": i} for i in range(13003, 13008)]}))
    (built / "patches/skills/skills.json").write_text(json.dumps(
        {"skills": {str(i): {"x": 1} for i in (13004, 13005, 13007)}}))
    (built / "patches/db/char.dat.json").write_text(json.dumps(
        {"added": [{"id": 18290, **{f"learn{k}_skill": 13002 + k for k in range(1, 6)}}]}))
    pinned = json.loads((IMPORTERS / "d4-evility-overlay.json").read_text())["mods"]["D4_Unique_5388"]["magic_ids"]
    assert pinned == [13029, 13030, 13031, 13032, 13033]
    moved = d4.Importer._pin_magic_ids(built, pinned)
    assert moved == dict(zip(range(13003, 13008), pinned))
    char = json.loads((built / "patches/db/char.dat.json").read_text())["added"][0]
    assert [char[f"learn{k}_skill"] for k in range(1, 6)] == pinned
    assert sorted(json.loads((built / "patches/skills/skills.json").read_text())["skills"]) == ["13030", "13031", "13033"]
    assert [r["id"] for r in json.loads((built / "patches/db/magic.dat.json").read_text())["added"]] == pinned


def test_5388_additions_and_overlay_agree():
    add = json.loads((IMPORTERS / "d4-evility-additions.json").read_text())["mods"]["D4_Unique_5388"]
    ov = json.loads((IMPORTERS / "d4-evility-overlay.json").read_text())["mods"]["D4_Unique_5388"]
    assert add["magic_ids"] == ov["magic_ids"] == [13029, 13030, 13031, 13032, 13033]
