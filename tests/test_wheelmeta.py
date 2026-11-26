import pytest

from d5lib.wheelmeta import class_wheel


def test_source_defaults_and_explicit_override():
    for source in ("d4", "d1c", "dd2", "overlord"):
        mod = {"category": "classes", "source_import": {"identity": {"source": source}}}
        assert class_wheel(mod) == source
        assert class_wheel({**mod, "wheel": "d5"}) == "d5"
    assert class_wheel({"category": "classes"}) == "d5"
    assert class_wheel({"category": "classes", "source_import": {"source_game": "d4"}}) == "d4"


@pytest.mark.parametrize("mod", [
    {},
    {"category": "classes", "wheel": "D4"},
    {"category": "classes", "wheel": None},
    {"category": "classes", "source_import": {}},
    {"category": "classes", "source_import": {"identity": {"source": "unknown"}}},
    {"category": "classes", "source_import": []},
])
def test_invalid_metadata_fails_closed(mod):
    with pytest.raises(ValueError):
        class_wheel(mod)


def test_family_wheels_orders_and_deduplicates():
    from d5lib.wheelmeta import WHEELS, family_wheels
    pairs = [
        ({'category': 'classes', 'source_import': {'identity': {'source': 'd4'}}},
         [{'family': 14020}, {'family': 14010}]),
        ({'category': 'classes', 'wheel': 'dd2'}, [{'family': 15000}]),
        ({'category': 'classes', 'wheel': 'd4'}, [{'family': 14010}]),
        ({'category': 'characters'}, []),
    ]
    result = family_wheels(pairs)
    assert tuple(result) == WHEELS
    assert result == {'d5': [], 'd4': [14010, 14020], 'd1c': [], 'dd2': [15000], 'overlord': []}


def test_family_wheels_rejects_conflicting_definitions():
    from d5lib.wheelmeta import family_wheels
    with pytest.raises(ValueError, match='class family 14010 assigned to both d4 and d1c'):
        family_wheels([({'category': 'classes', 'wheel': 'd4'}, [{'family': 14010}]),
                       ({'category': 'classes', 'wheel': 'd1c'}, [{'family': 14010}])])


def test_inventory_respects_profile_and_reports_missing(tmp_path):
    import json
    from tools.wheel_contents import inventory, render
    folder = tmp_path / 'imported'
    specs = folder / 'patches' / 'classes'
    specs.mkdir(parents=True)
    (folder / 'mod.json').write_text(json.dumps({'category': 'classes', 'source_import': {'source_game': 'd4'}}))
    (specs / 'class_14010.json').write_text(json.dumps({'family': 14010, 'name': 'Warrior'}))
    (tmp_path / 'disabled').mkdir()
    groups, names, missing = inventory(tmp_path, ['imported', 'missing'])
    assert groups['d4'] == [14010]
    assert missing == ['missing']
    text = render(groups, names, missing)
    assert '14010: Warrior' in text and '- missing' in text
    assert 'disabled' not in text


def test_family_wheels_accepts_legacy_and_mixed_content_class_descriptors():
    from d5lib.wheelmeta import family_wheels
    result = family_wheels([({}, [{'family': 1350}]),
                            ({'category': 'characters', 'source_import': {'source_game': 'd4'}},
                             [{'family': 14010}])])
    assert result['d5'] == [1350]
    assert result['d4'] == [14010]


def test_runtime_entries_are_sorted_indexed_and_deduplicated():
    from d5lib.wheelmeta import runtime_entries
    pairs = [({'wheel': 'dd2'}, [{'family': 15000}]),
             ({'source_import': {'source_game': 'd4'}}, [{'family': '14020'}, {'family': 14010}]),
             ({'wheel': 'd4'}, [{'family': 14010}]),
             ({}, [{'family': 1350}])]
    assert runtime_entries(pairs) == [(1350, 0), (14010, 1), (14020, 1), (15000, 3)]


@pytest.mark.parametrize('family', [True, 1.5, None, '', -1, 0, 65536])
def test_runtime_entries_reject_unrepresentable_families(family):
    from d5lib.wheelmeta import runtime_entries
    with pytest.raises(ValueError):
        runtime_entries([({}, [{'family': family}])])


def test_runtime_entries_reject_conflicts_and_missing_family():
    from d5lib.wheelmeta import runtime_entries
    with pytest.raises(ValueError, match='assigned to both'):
        runtime_entries([({'wheel': 'd4'}, [{'family': 14010}]),
                         ({'wheel': 'd1c'}, [{'family': 14010}])])
    with pytest.raises(ValueError, match='identify a family'):
        runtime_entries([({}, [{}])])


def test_class_handler_keeps_metadata_and_rejects_cross_mod_conflict(tmp_path):
    import json
    from types import SimpleNamespace
    from d5lib import modsys, newclasses
    ctx = SimpleNamespace()
    for name, wheel in [('first', 'd4'), ('second', 'd1c')]:
        folder = tmp_path / name
        path = folder / 'patches' / 'classes'
        path.mkdir(parents=True)
        (folder / 'mod.json').write_text(json.dumps({'wheel': wheel}))
        (path / 'class_14010.json').write_text(json.dumps({'family': 14010}))
    newclasses._handler(ctx, modsys.Mod(str(tmp_path / 'first')), None)
    assert ctx._wheel_mod_specs[0][0]['wheel'] == 'd4'
    with pytest.raises(ValueError, match='assigned to both'):
        newclasses._handler(ctx, modsys.Mod(str(tmp_path / 'second')), None)
    assert len(ctx._wheel_mod_specs) == 1
