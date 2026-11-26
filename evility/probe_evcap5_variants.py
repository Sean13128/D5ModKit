#!/usr/bin/env python3
"""EVCAP5: the same fix, proven on both Kit lines' dbpatch.py.

`Builds/LIVE5_TEST16-20261030` ships dbpatch.py 5c931430 (25,353 B) and
`Builds/LIVE5_TEST18B-20261030` ships 819818b5 (31,408 B); the installed kit currently holds the
31,408 B one.  The overlay carries a variant for each.  This script imports each file by path and
runs the same three checks, so "applies on TEST18B" is measured, not assumed.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get('D5_KIT', os.path.dirname(HERE))
sys.path.insert(0, KIT)

from d5lib import database  # noqa: E402

VANILLA = os.environ.get('D5_VANILLA', '/Volumes/Data/ai-tmp/magichange/vanilla/Database_0.dat')
VARIANTS = {
    'TEST16 base 5c931430 (Builds/LIVE5_TEST16-20261030)':
        os.environ.get('D5_VARIANT_16', os.path.join(HERE, '..', 'd5lib', 'dbpatch.py')),
    'TEST18B base 819818b5 (Builds/LIVE5_TEST18B-20261030)':
        os.environ.get('D5_VARIANT_18B', '/Volumes/Data/ai-tmp/evcap5/bases/dbpatch-test18b.py'),
    'installed kit base 1dde5c0c':
        os.environ.get('D5_VARIANT_INSTALLED', '/Volumes/Data/ai-tmp/evcap5/bases/dbpatch-installed.py'),
}


def load(path):
    spec = importlib.util.spec_from_file_location('d5lib.dbpatch_' + str(abs(hash(path))), path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def checks(mod):
    out = {}
    db = database.load_database(VANILLA)
    table = database.load_table('Skill.dat', db.table('Skill.dat').to_bytes())
    patch = {'table': 'Skill.dat',
             'added': [{'id': 9901, 'kind': 0, 'mana_cost': 1000, 'category': 0,
                        'effect_group': 9, 'slot_cost': 2, 'name_EN': 'EVCAP5 Common'},
                       {'id': 9902, 'kind': 1, 'mana_cost': 0, 'category': 0,
                        'effect_group': 9, 'slot_cost': 0, 'name_EN': 'EVCAP5 Unique'},
                       {'id': 9903, 'kind': 0, 'mana_cost': 1000, 'category': 7,
                        'effect_group': 3, 'slot_cost': 2, 'name_EN': 'EVCAP5 Named'}]}
    mod.apply_patch(table, patch)
    rows = {r['id']: r for r in table.rows}
    out['learnable_added_gets_group_category'] = (
        rows[9901]['category'] == mod.EVILITY_CATEGORY[9])
    out['unique_added_untouched'] = rows[9902]['category'] == 0
    out['named_category_kept'] = rows[9903]['category'] == 7
    left = [r['id'] for r in table.rows if r['kind'] == 0 and r['mana_cost'] > 0 and not r['category']]
    out['no_learnable_row_left_at_zero'] = left == []
    out['vanilla_learnable_rows_still_categorised'] = all(
        r['category'] for r in table.rows
        if r['kind'] == 0 and r['mana_cost'] > 0 and r['id'] < 8000)
    return out


def main():
    results = {}
    for name, path in VARIANTS.items():
        path = os.path.abspath(path)
        if not os.path.exists(path):
            results[name] = {'error': 'file not found: ' + path}
            continue
        mod = load(path)
        res = checks(mod)
        res['file'] = path
        res['bytes'] = os.path.getsize(path)
        res['all_pass'] = all(v for k, v in res.items() if isinstance(v, bool))
        results[name] = res
        print(json.dumps({name: res}, indent=1))
    json.dump(results, open(os.path.join(HERE, 'results', 'evcap5-variants.json'), 'w'), indent=1)
    ok = all(r.get('all_pass') for r in results.values())
    print('ALL VARIANTS PASS' if ok else 'VARIANT FAILURE')


if __name__ == '__main__':
    main()
