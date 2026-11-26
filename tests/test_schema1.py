"""SCHEMA1: Sorrow's verified names (legacy names stay readable) and the three shared importcore gates."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from d5lib import database, importcore  # noqa: E402

RENAMES = {  # table -> (new name, legacy name, offset)
    "char.dat": [("torture_id", "unk_0CA", 202), ("exp_yield_weight", "unk_0E0", 224), ("is_unique", "unk_384", 900)],
    "Quest.dat": [("exclude_flag_id", "req_extra", 308), ("min_level", "unk_138", 312),
                  ("objective_param_2", "unk_12B8", 4792), ("objective_param_3", "unk_12BC", 4796),
                  ("bounty_target_mode", "unk_15E4", 5604), ("bounty_target_char_id", "unk_15E8", 5608),
                  ("bounty_drop_item_id", "unk_15EC", 5612), ("bounty_drop_permille", "unk_15F0", 5616),
                  ("bounty_stage_id", "unk_15F4", 5620), ("mode_restriction", "unk_15F8", 5624)],
}


@pytest.mark.parametrize("table", sorted(RENAMES))
def test_renamed_field_keeps_offset_and_legacy_name_reads_and_writes_the_same_bytes(table):
    sc = database.get_schema(table)
    assert not sc.check_coverage()
    row = database.Row(sc, bytes(sc.record_size))
    for new, old, off in RENAMES[table]:
        f = sc.by_name[new]
        assert f.offset == off and sc.alias[old] == new and old not in sc.by_name
        row[old] = 7                              # a pack built before the rename
        assert row[new] == 7 and row.get(old) == 7 and old in row
        assert bytes(row.raw[off:off + f.size]) == (7).to_bytes(f.size, "little")
        row[new] = 0
    assert not any(row.raw)
    assert not set(sc.alias) & set(sc.by_name)
    assert [k for k in row.keys() if k in sc.alias] == []     # to_dict / keys list canonical names only


def test_schema_sizes_and_unrenamed_offsets_are_untouched():
    assert database.get_schema("char.dat").record_size == 908
    assert database.get_schema("Quest.dat").record_size == 5636
    assert database.get_schema("item.dat").record_size == 1120
    assert database.get_schema("JobRank.dat").record_size == 20
    for t in ("char.dat", "Quest.dat", "item.dat", "JobRank.dat"):
        assert not database.get_schema(t).check_coverage()


# ----------------------------------------------------------------------- gates
def _mod(tmp_path, char=None, quest=None, source_import=None):
    mod = tmp_path / "M"
    (mod / "patches/db").mkdir(parents=True)
    (mod / "mod.json").write_text(json.dumps({"name": "M", "source_import": source_import or {}}))
    if char is not None:
        (mod / "patches/db/char.dat.json").write_text(json.dumps({"table": "char.dat", "added": char}))
    if quest is not None:
        (mod / "patches/db/Quest.dat.json").write_text(json.dumps({"table": "Quest.dat", "added": quest}))
    return mod


LABELS = {"yield_source": {"exp_yield_weight": "source", "mana_yield_rate": "approximation", "note": "D1C has no mana rate"}}


def test_yield_gate(tmp_path):
    row = {"id": 1, "unk_0E0": 4, "unk_0EC": 90}
    assert importcore.yield_gate(_mod(tmp_path / "a", char=[row], source_import=LABELS))[0]
    assert importcore.yield_gate(_mod(tmp_path / "b", char=[]))[0]                    # no imported char rows
    ok, why = importcore.yield_gate(_mod(tmp_path / "c", char=[row]))                 # negative: no label at all
    assert not ok and "exp_yield_weight unlabelled" in why and "mana_yield_rate unlabelled" in why
    no_note = {"yield_source": {"exp_yield_weight": "source", "mana_yield_rate": "approximation"}}
    assert "no note" in importcore.yield_gate(_mod(tmp_path / "d", char=[row], source_import=no_note))[1]
    kept = dict(LABELS, gameplay=[{"unchanged_fields": ["id", "unk_0E0"]}])           # negative: donor value kept
    ok, why = importcore.yield_gate(_mod(tmp_path / "e", char=[row], source_import=kept))
    assert not ok and "kept from the D5 donor" in why


def test_recruit_quest_gate(tmp_path):
    good = {"id": 9, "min_level": 0, "mode_restriction": 0}
    assert importcore.recruit_quest_gate(_mod(tmp_path / "a", quest=[good, {"id": 10, "unk_138": 30}]))[0]
    for i, (patch, frag) in enumerate([({"bounty_drop_item_id": 5}, "bounty_drop_item_id=5"),
                                       ({"unk_15E4": 2}, "bounty_target_mode=2"),     # legacy spelling still caught
                                       ({"min_level": 10000}, "min_level"), ({"min_level": -1}, "min_level"),
                                       ({"mode_restriction": 3}, "mode_restriction")]):
        ok, why = importcore.recruit_quest_gate(_mod(tmp_path / f"n{i}", quest=[dict(good, **patch)]))
        assert not ok and frag in why


def test_learn_skill_gate(tmp_path):
    ids = {100, 101}
    row = {"id": 1, "learn_count": 2, "learn1_skill": 100, "learn2_skill": 101, "learn3_skill": 999}
    assert importcore.learn_skill_gate(_mod(tmp_path / "a", char=[row]), ids)[0]       # slot 3 is beyond learn_count
    ok, why = importcore.learn_skill_gate(_mod(tmp_path / "b", char=[dict(row, learn_count=3)]), ids)
    assert not ok and "learn3_skill=999" in why                                        # negative: dangling id
    assert importcore.learn_skill_gate(_mod(tmp_path / "c", char=[dict(row, learn_count=3)]), ids | {999})[0]


def test_schema_gates_without_original_state_fail_loudly_only_when_needed(tmp_path):
    assert importcore.schema_gates(_mod(tmp_path / "a", char=[]), None)["learn_skills"][0]
    mod = _mod(tmp_path / "b", char=[{"id": 1, "learn_count": 1, "learn1_skill": 5}])
    assert importcore.schema_gates(mod, None)["learn_skills"] == (False, "magic.dat unreachable")


def test_donor_yield_label_passes_the_gate_even_with_the_donor_value_kept(tmp_path):
    kept = {"yield_source": importcore.donor_yield("test"), "gameplay": [{"unchanged_fields": ["exp_yield_weight", "unk_0EC"]}]}
    assert importcore.yield_gate(_mod(tmp_path / "a", char=[{"id": 1}], source_import=kept)) == (True, "")
