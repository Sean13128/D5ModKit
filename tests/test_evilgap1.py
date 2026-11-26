"""EVILGAP1: the added D4 signature evility rows are in the overlay, in the D4 exact band, owned once, compile, labelled."""
import json
from pathlib import Path

from d5lib import evility

DIR = Path(__file__).resolve().parents[1] / "d5lib/importers"
from d4rules import additions as _rule_additions
ADD = _rule_additions()["mods"]
from d4rules import mods as _rule_mods
OVER = _rule_mods()


def test_rows_in_overlay_once_in_band_and_labelled():
    seen = {}
    for pack, a in ADD.items():
        assert a["adaptations"], pack
        for r in a["skill_rows"]:
            assert r["id"] not in seen, r["id"]
            seen[r["id"]] = pack
            assert r in OVER[pack]["skill_rows"]
            if a.get("installed_rows"):
                # REPROFIX1: rows copied from an installed pack so a rebuild equals it.  They keep the installed id
                # and the aliased D5 evility's own text, so the band and placeholder rules for authored rows do not
                # apply; each must be an alias of a D5 evility instead.
                assert str(r["id"]) in a["aliases"], r["id"]
                continue
            late = a.get("late_ids", {}).get(str(r["id"] - 27000)) == r["id"]   # EVILFX2b: D4 late band, recorded
            assert 8187 < r["id"] < 9000 or late                      # above the learned-evility bitmap, D4 exact band
            assert "%d" not in r["desc_EN"]                    # no printf placeholder (C1 crash class)
    owners = [r["id"] for st in OVER.values() for r in st.get("skill_rows", [])]
    assert all(owners.count(i) == 1 for i in seen)


def test_behaviors_compile():
    for a in ADD.values():
        if a.get("behaviors"):
            evility.table(a["behaviors"])


# ---- EVILGAP1b: a shared row is a reference to its owner, never a second row
import importlib.util
import tempfile

from d5lib import importcore


def _builder():
    spec = importlib.util.spec_from_file_location("bdo", Path(__file__).resolve().parents[1] / "tools/build_d4_evility_overlay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_overlay_references_resolve_and_are_not_owners():
    assert _builder().problems({"mods": OVER}) == []
    refs = {n: st["refs"] for n, st in OVER.items() if st.get("refs")}
    assert set(refs) == {"D4_Unique_170", "D4_Unique_320", "D4_Unique_4390"}   # EVILFX2: Kojiro -> Bouncer's 8697; D4SIG1: Hugo -> Death's 27691             # only where the owner class is in scope and installed
    owned = [r["id"] for st in OVER.values() for r in st.get("skill_rows", [])]
    for n, rr in refs.items():
        for row, owner in rr.items():
            assert owned.count(int(row)) == 1                       # one owner, no second copy
            assert owner in OVER[n]["requires"]


def test_out_of_scope_owner_means_the_unique_owns_the_row():
    for pack, row in (("D4_Unique_5309", 8211), ("D4_Unique_5310", 8351), ("D4_Unique_310", 8625)):
        assert row in [r["id"] for r in OVER[pack]["skill_rows"]]
        assert str(row) in OVER[pack]["behaviors"]["evilities"]
        assert not OVER[pack].get("requires")
    assert not {"D4_Class_1100", "D4_Class_1130", "D4_Class_1210"} & set(OVER)


def test_reference_to_unowned_row_fails():
    bad = json.loads(json.dumps(OVER))
    bad["D4_Unique_320"]["refs"] = {"8181": "D4_Class_1100"}      # wrong owner, and not required
    msgs = _builder().problems({"mods": bad})
    assert any("does not own" in m for m in msgs) and any("does not require" in m for m in msgs)


def _pack(root, name, link, requires=None, rows=()):
    d = Path(root) / name
    (d / "patches/db").mkdir(parents=True)
    (d / "mod.json").write_text(json.dumps({"name": name, **({"requires": requires} if requires else {})}))
    (d / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 1, "evility1": link}]}))
    (d / "patches/db/Skill.dat.json").write_text(json.dumps({"added": [{"id": r} for r in rows]}))
    return d


def test_used_id_gate_reference_rule():
    with tempfile.TemporaryDirectory() as t:
        _pack(t, "Owner", 0, rows=(8211,))
        used = importcore.UsedIds.__new__(importcore.UsedIds)
        used.roots = [Path(t)]
        assert used.reference_problems(_pack(t, "Ok", 8211, ["Owner"])) == []
        assert used.reference_problems(_pack(t, "NoRequires", 8211)) == [8211]
        assert used.reference_problems(_pack(t, "WrongPack", 8211, ["Nobody"])) == [8211]
        assert used.reference_problems(_pack(t, "Own", 8211, rows=(8211,))) == []   # its own row is not a reference


def test_marona_phantom_lover_is_spirit_family_late_band_and_labelled():
    # EVILNEW2: 27875 counts the six D4 Spirit class ids, innate on Marona (18150); any-team count is labelled
    a = ADD["D4_Unique_440"]
    assert [r["id"] for r in a["skill_rows"]] == [27875] and a["char_links"]["18150"]["evility1"] == 27875
    b = a["behaviors"]["27875"]
    # EVILCAP1: allies only (map_class_ally), label and text follow the source
    assert b["classes"] == list(range(14550, 14556)) and b["effects"][0]["per"] == "map_class_ally"
    assert "APPROXIMATION" not in a["adaptations"][0] and "ally Spirit" in a["skill_rows"][0]["desc_EN"]
    assert evility.table({27875: b})                          # the runtime emitter accepts it
