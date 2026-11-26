"""D4-TEXT1: importcore.text_gate (no bare % in imported text rows) and the shared writers' textfmt.prose."""
import json
import tempfile
from pathlib import Path

from d5lib import importcore, textfmt


def _mod(rows, table="magic.dat.json", key="added"):
    d = Path(tempfile.mkdtemp()) / "m"
    (d / "patches/db").mkdir(parents=True)
    body = rows if key == "added" else {str(i): r for i, r in enumerate(rows)}
    (d / "patches/db" / table).write_text(json.dumps({"table": table[:-5], key: body}))
    return d


def test_gate_fails_bare_percent():
    ok, why = importcore.text_gate(_mod([{"id": 1, "desc_EN": "Physical damage and 30% Amnesia."}]))
    assert not ok and "1.desc_EN" in why


def test_gate_passes_valid_formats():
    ok, _ = importcore.text_gate(_mod([{"id": 1, "desc_EN": "%s hits 30％, %d%%, %2d, 100%% or %s"}]))
    assert ok


def test_gate_covers_changed_rows():
    assert not importcore.text_gate(_mod([{"line3_EN": "50% off"}], "charhelp.dat.json", "rows"))[0]


def test_prose_writer_rule():
    assert textfmt.prose("30% Amnesia, %s %d %2d, 5%%") == "30％ Amnesia, %s %d %2d, 5％"
    assert textfmt.prose(textfmt.prose("30% x")) == "30％ x"


def test_writers_use_prose():
    from d5lib import charstudio, newclasses

    class Row(dict):
        def set(self, k, v, truncate=False):
            self[k] = v
    for fn in (charstudio.set_langs, newclasses.set_langs):
        r = Row(desc_EN="")
        fn(r, "desc", "30% Amnesia")
        assert r["desc_EN"] == "30％ Amnesia"
