"""SPECIALS2: the pure parts (no game data needed)."""
import json

from d5lib import srcskills
from d5lib.importers import specials2


def _conc(points):
    c = srcskills.Concordance.__new__(srcskills.Concordance)
    c.power, c.effect, c.pairs = {(2, v): ys for v, ys in points.items()}, {}, 0
    return c


def test_power_fit_is_monotone_and_interpolates():
    c = _conc({1: [0], 3: [10, 10], 5: [5], 10: [40], 20: [80]})
    got = [c.convert_power(2, v)[0] for v in (1, 3, 4, 5, 10, 15, 20, 99)]
    assert got == sorted(got) and got[0] == 0 and got[-1] == 80 and got[5] == 60


def test_power_is_refused_when_the_shared_skills_show_no_relation():
    c = _conc({5: [-10], 10: [120], 20: [5], 40: [-5], 80: [30], 100: [0]})
    value, why = c.convert_power(2, 50)
    assert value is None and "no usable relation" in why


def test_cursor_origin_cell_compares_equal():
    assert srcskills._plain({(0, 0, 3), (1, 0, 1)}) == srcskills._plain({(0, 0, 1), (1, 0, 1)})


def test_gate_catches_an_unresolved_learn_id_and_a_bad_row(tmp_path):
    class Survey:
        def check_mod(self, mod):
            return []

    class D5:
        rows, maps, survey = {101: {}}, {1: frozenset()}, Survey()

        def has_root(self, sid):
            return False
    mod = tmp_path / "D4_Unique_1"
    (mod / "patches/db").mkdir(parents=True)
    row = dict(id=40000, sp_cost=10, element=9, range=1, effect1_value=5, height_up=1, height_down=1,
               attack_map=77, base_skill=0, skill_group=7, name_EN="x")
    (mod / "patches/db/magic.dat.json").write_text(json.dumps(dict(added=[row])))
    (mod / "patches/db/char.dat.json").write_text(json.dumps(dict(added=[dict(
        id=1, learn_count=2, learn1_skill=101, learn2_skill=555)])))
    text = " ".join(specials2.gate(mod, D5()))
    for needle in ("555 resolves to no", "outside 10000..32767", "out of range", "AttackMap 77", "no choreography"):
        assert needle in text


def test_d1_pattern_maps_to_the_d5_twin_used_at_its_reach():
    """D1SCRIPT1: a D1 shape (landing cell dropped) picks the D5 shape D5 itself uses at that reach kind."""
    pats = json.loads(srcskills.D1_PATTERNS.read_text())["patterns"]
    assert len(pats) == 82 and pats["13"] == [[0, 1, 1], [0, 2, 2]]          # Triple Strike's shape = D5 1100
    ring = frozenset((x, y, 1) for x in (-1, 0, 1) for y in (-1, 0, 1) if x or y)

    class Table:
        rows = [dict(attack_map=8, range=3), dict(attack_map=8001, range=0)]

    class D5:
        maps, table = {8: ring, 8001: ring}, Table()
    src = dict(game="d1c", attack_map="d1:42", range=0)
    assert srcskills.shape_for(src, {"d1:42": ring}, D5())[0] == 8001
    assert srcskills.shape_for(dict(src, range=3), {"d1:42": ring}, D5())[0] is None   # a cursor shape needs kind 3


def _pack(tmp_path, block):
    mod = tmp_path / "D4_Unique_1"
    mod.mkdir()
    meta = {"name": "x"}
    if block is not None:
        meta["specials2"] = block
    (mod / "mod.json").write_text(json.dumps(meta))
    return mod


def test_relabel_moves_n_entries_out_of_entries_and_touches_only_the_block(tmp_path):
    """D4SPEC1: a source learn id with no skill is recorded as absent, never counted held or total."""
    block = dict(entries=[dict(src=1, label="A"), dict(src=2, label="H")], kept=[])
    mod = _pack(tmp_path, block)
    p = dict(source_character=7, kept=[], entries=[dict(src=1, label="A", level=5, notes=[]),
                                                    dict(src=2, label="N", level=9, name=None, notes=["no row"])])
    assert specials2.relabel(mod, p) is True
    got = json.loads((mod / "mod.json").read_text())
    assert got["name"] == "x" and [e["src"] for e in got["specials2"]["entries"]] == [1]
    assert got["specials2"]["source_absent"] == [dict(src=2, level=9, name=None, why="no row")]
    assert specials2.relabel(mod, p) is False                    # second run is a no-op


def test_relabel_marks_a_unit_with_an_empty_source_learn_list(tmp_path):
    mod = _pack(tmp_path, None)
    p = dict(source_character=5306, kept=[dict(d5_id=11011, level=10, name="Bulk Up", why="donor line")], entries=[])
    assert specials2.relabel(mod, p) is True
    block = json.loads((mod / "mod.json").read_text())["specials2"]
    assert block["source_has_none"] is True and block["entries"] == []
    assert specials2.relabel(mod, p) is False
