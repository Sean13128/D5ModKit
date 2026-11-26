"""Structural gate for reachable attachment records and node references."""
from d5lib import anm


def make_bank():
    b = anm.AnmBlock(1)
    b.animations = [anm.Animation(1, 0), anm.Animation(2, 1)]
    b.nodes = [anm.Node(0, 0, 0, 0, 0, 0, 0, 1, -1, -1),
               anm.Node(0, 0, 0, 0, 0, 0, -1, 0, -1, -1)]
    b.keys = [anm.Key(0, anm.NESTED, 0, 0, 0, 0)]
    b.params = [2, 0, -1]
    return anm.AnmFile([b], [], [])


def test_reachable_record_and_unreachable_leftovers():
    f = make_bank()
    f.blocks[0].params.extend([999, 999])
    assert anm.check_structure(f) == []
    f.blocks[0].keys[0].param = 3
    problems = anm.check_structure(f)
    assert len(problems) == 1
    assert 'record_out_of_range' in problems[0]['reasons']
    assert 'missing_target' in problems[0]['reasons']


def test_bad_timing_and_indices():
    f = make_bank()
    b = f.blocks[0]
    b.params[1:] = [65003, 65003]
    b.nodes[0].child = 9
    problems = anm.check_structure(f)
    assert {p['kind'] for p in problems} == {'nested_record', 'node_link_out_of_range'}
    assert 'invalid_timing' in problems[-1]['reasons']
    b.animations[0].root = 9
    assert any(p['kind'] == 'root_out_of_range' for p in anm.check_structure(f))


def test_valid_nonzero_start_and_external_binding():
    f = make_bank()
    b = f.blocks[0]
    b.nodes[1].first_key = 1
    b.nodes[1].num_keys = 1
    b.keys.append(anm.Key(10, 0, 0, 0, 0, 0))
    b.params[1:] = [1, -1]
    assert anm.check_structure(f) == []
    b.nodes[0].id, b.nodes[0].flags = 14, 0x100
    b.params[:] = [999, 1, -1]
    assert anm.check_structure(f) == []  # dynamically bound bank is unavailable here
    b.params[1] = 65003
    assert 'invalid_timing' in anm.check_structure(f)[0]['reasons']


def test_alignment_and_missing_target():
    f = make_bank()
    b = f.blocks[0]
    b.params = [0, 999, 0, -1]
    b.keys[0].param = 1
    reasons = anm.check_structure(f)[0]['reasons']
    assert 'missing_target' in reasons
    assert 'misaligned' in anm.check_structure(f)[0]['warnings']


def test_cycle_and_count_overflow():
    f = make_bank()
    b = f.blocks[0]
    b.nodes[0].child = 0
    assert anm.check_structure(f) == []  # traversal terminates on cyclic links
    b.params.extend([0] * 0x10000)
    assert any(p['kind'] == 'count_overflow' and p['table'] == 'params'
               for p in anm.check_structure(f))


def test_valid_positive_lifetime():
    f = make_bank()
    f.blocks[0].params[2] = 12  # lifetime is independent of child-motion length
    assert anm.check_structure(f) == []


def test_baseline_relative_findings_and_warnings():
    old, new = make_bank(), make_bank()
    old.blocks[0].params = [0, 2, -2, -1]
    new.blocks[0].params = old.blocks[0].params[:]
    old.blocks[0].keys[0].param = new.blocks[0].keys[0].param = 1
    result = anm.compare_structure(old, new)
    assert not result['structural_problems']
    assert len(result['inherited_structural_problems']) == 1
    assert result['structural_warnings'][0]['warnings'] == ['misaligned']
    new.blocks[0].params[2] = -3
    assert 'invalid_timing' in anm.compare_structure(old, new)['structural_problems'][0]['reasons']


def test_changed_overlapping_reachable_record_fails():
    old, new = make_bank(), make_bank()
    for f in (old, new):
        b = f.blocks[0]
        b.nodes[0].num_keys = 2
        b.keys.append(anm.Key(0, anm.NESTED, 0, 0, 0, 1))
        b.params = [2, 2, 0, -1]
    # Both readings were already overlapping; changing one changes the other's reading.
    new.blocks[0].params[1] = 1
    findings = anm.compare_structure(old, new)['structural_problems']
    assert any('overlap_changed_reading' in p['reasons'] for p in findings)
    assert not any('overlap_changed_reading' in p['reasons']
                   for p in anm.compare_structure(old, old)['structural_problems'])


def test_shared_key_is_compared_for_each_animation_path():
    old, new = make_bank(), make_bank()
    for f in (old, new):
        f.blocks[0].animations[1].root = 0
        f.blocks[0].params[1] = -2
    new.blocks[0].animations[1].root = 1
    result = anm.compare_structure(old, new)
    assert not result['structural_problems']
    assert [path['animation_id'] for p in result['inherited_structural_problems'] for path in p['reachable_paths']] == [1]
    new.blocks[0].animations[1].root = 0
    new.blocks[0].params[1] = -3
    assert {path['animation_id'] for p in anm.compare_structure(old, new)['structural_problems'] for path in p['reachable_paths']} == {1, 2}


def test_inherited_and_new_bad_links_and_short_record():
    old, new = make_bank(), make_bank()
    for f in (old, new):
        f.blocks[0].nodes[0].child = 9
        f.blocks[0].params.pop()
    result = anm.compare_structure(old, new)
    assert not result['structural_problems']
    assert {p['kind'] for p in result['inherited_structural_problems']} == {
        'node_link_out_of_range', 'nested_record'}
    new.blocks[0].nodes[0].child = 10
    result = anm.compare_structure(old, new)
    assert [p['kind'] for p in result['structural_problems']] == ['node_link_out_of_range']


def test_new_overlapping_key_changes_existing_reading():
    old, new = make_bank(), make_bank()
    b = new.blocks[0]
    b.nodes[0].num_keys = 2
    b.keys.append(anm.Key(0, anm.NESTED, 0, 0, 0, 1))
    b.params = [2, 1, -1, -1]
    problems = anm.compare_structure(old, new)['structural_problems']
    assert any(p['key'] == 0 and 'overlap_changed_reading' in p['reasons'] for p in problems)
