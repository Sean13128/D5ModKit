"""D4-FIX4: reviewed evility overlay is internally consistent; compare names row ids."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib.importcore import evility_row_diff  # noqa: E402

OV = Path(__file__).resolve().parents[1] / "d5lib/importers/d4-evility-overlay.json"


def test_overlay_skill_ids_are_unique_across_packs():
    seen = {}
    for name, st in json.loads(OV.read_text())["mods"].items():
        for r in st.get("skill_rows", []):
            assert r["id"] not in seen, (r["id"], name, seen[r["id"]])
            seen[r["id"]] = name
    for must in (8391, 8392, 8075, 8094, 8173, 8841, 8891):
        assert must in seen


def test_compare_names_row_ids(tmp_path):
    def mk(d, ids):
        (d / "patches/db").mkdir(parents=True)
        (d / "patches/db/Skill.dat.json").write_text(json.dumps({"added": [{"id": i} for i in ids]}))
    a, b = tmp_path / "a", tmp_path / "b"
    mk(a, [8391, 8392]); mk(b, [7020, 7024])
    out = evility_row_diff(b, a)
    assert "installed-only [8391, 8392]" in out and "rebuild-only [7020, 7024]" in out
    assert evility_row_diff(a, a) == ""
