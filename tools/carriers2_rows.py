#!/usr/bin/env python3
"""Write the CARRIERS2 lane's D4 evility rows into a mods tree (a bundle, never a source pack).

One source: `evility/carriers2-content.json`.  For every entry and every target pack it owns

  <mod>/patches/db/Skill.dat.json           the row itself (8000 + the D4 id), D4's name, D4's own text in
                                            all five locales, D4's mana, the D5 slot shape for that mana
  <mod>/patches/evilities/evilities.json    the .d5el rule the row's id plays (`classes` and `filter`
                                            included; d5lib.evility is the only authority on their shape)
  <mod>/mod.json                            the `evility <name> (<id>):` adaptation line

and it refuses to run when the row id is already claimed by another mod in the same tree (the ids are
Skill.dat row ids, a naming space shared by every installed pack), when a rule does not compile, or when a
description is not a printable format (the C1 crash class).

  python tools/carriers2_rows.py --check /path/to/Builds/<bundle>/mods   (default, reports)
  python tools/carriers2_rows.py --write /path/to/Builds/<bundle>/mods

Exit status: 1 when --check finds a difference or a problem, so it can gate a bundle.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from d5lib import evility as ev          # noqa: E402
from d5lib import textfmt                # noqa: E402

try:                                     # the reviewed slot shape (D5's own mana -> slot-cost table)
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        'd4pilotfix', HERE.parent.parent / 'd4-evility-import/d5lib/d4pilotfix.py')
    _d4pilotfix = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_d4pilotfix)
    slot_cost_for_mana = _d4pilotfix.slot_cost_for_mana
except Exception:                        # offline fallback, same table as d4pilotfix.SLOT_BY_MANA
    def slot_cost_for_mana(mana):
        for bound, cost in ((100, 2), (250, 2), (1000, 3), (2500, 4), (5000, 4)):
            if int(mana or 0) <= bound:
                return cost
        return 5

CONTENT = HERE.parent / 'evility/carriers2-content.json'
LOCALES = ('JP', 'EN', 'FR', 'CHN', 'KOR')
FIELDS = ['id', 'name_JP', 'name_EN', 'name_FR', 'name_CHN', 'name_KOR', 'slot_cost',
          'desc_JP', 'desc_EN', 'desc_FR', 'desc_CHN', 'desc_KOR', 'kind', 'effect_group',
          'value1', 'value2', 'source', 'category', 'subcategory', 'mana_cost', 'shop_rank',
          'owner', 'class_order', 'version_group']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + '\n',
                          encoding='utf-8')


def claimed(mods_root, skip_pack, row_id):
    """every other mod that already writes this Skill.dat row id"""
    hits = []
    for mod in sorted(os.listdir(mods_root)):
        if mod == skip_pack:
            continue
        p = Path(mods_root) / mod / 'patches/db/Skill.dat.json'
        if not p.is_file():
            continue
        patch = read(p)
        for r in patch.get('added', []):
            if int(r['id']) == row_id:
                hits.append(mod)
        for key in (patch.get('rows') or {}):
            if int(key) == row_id:
                hits.append(mod)
    return sorted(set(hits))


def skill_row(entry, target):
    row = {k: 0 for k in FIELDS}
    for loc in LOCALES:
        row[f'name_{loc}'] = entry['d4_name']
        row[f'desc_{loc}'] = entry['desc']
    row.update(id=int(entry['row_id']), kind=0 if target['role'] == 'learnable' else 1,
               source=4, version_group=100, owner=int(target['class_row']), class_order=0,
               value1=int(entry['value1']), value2=int(entry.get('value2') or 0),
               mana_cost=int(entry['mana']),
               slot_cost=0 if target['role'] != 'learnable' else slot_cost_for_mana(entry['mana']))
    return row


def rule(entry):
    r = {'family': entry['family'], 'effects': entry['effects']}
    if entry.get('condition'):
        r['condition'] = entry['condition']
    if entry.get('classes'):
        r['classes'] = list(entry['classes'])
    return r


def adaptation_line(entry):
    return (f"evility {entry['d4_name']} ({entry['d4_id']}): adapted -> own .d5el row "
            f"{entry['row_id']} at D4's number (filtered map count / counted evility predicate carrier)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mods_root')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--check', action='store_true', help='accepted for symmetry (the default)')
    ap.add_argument('--content', default=str(CONTENT))
    args = ap.parse_args()
    root = Path(args.mods_root)
    content = read(args.content)
    problems, changes = [], []

    # every rule must compile before anything is written (one table, every row of every pack)
    per_pack = {}
    for entry in content['rows']:
        if textfmt.bad_format(entry['desc']):
            problems.append(f"{entry['d4_name']}: desc is not a printable format")
        for target in entry['targets']:
            per_pack.setdefault(target['pack'], {})[int(entry['row_id'])] = rule(entry)
    for pack, rows in per_pack.items():
        try:
            ev.table(rows)               # raises on a bad family / stat / condition / filter
        except ValueError as exc:
            problems.append(f'{pack}: {exc}')

    for entry in content['rows']:
        for target in entry['targets']:
            pack_name = target['pack']
            pack = root / pack_name
            if not (pack / 'mod.json').is_file():
                problems.append(f"{pack_name}: not a mod folder under {root}")
                continue
            others = claimed(root, pack_name, int(entry['row_id']))
            if others:
                problems.append(f"row {entry['row_id']} ({entry['d4_name']}) is already claimed by "
                                f"{', '.join(others)}")
            want = skill_row(entry, target)
            sp = pack / 'patches/db/Skill.dat.json'
            patch = read(sp) if sp.is_file() else {'table': 'Skill.dat', 'added': []}
            added = {int(r['id']): r for r in patch.get('added', [])}
            if added.get(want['id']) != want:
                changes.append(f"{pack_name}: Skill.dat row {want['id']} {entry['d4_name']}")
                added[want['id']] = want
                patch['added'] = [added[k] for k in sorted(added)]
            ep = pack / 'patches/evilities/evilities.json'
            rules = read(ep)['evilities'] if ep.is_file() else {}
            r = rule(entry)
            if rules.get(str(want['id'])) != r:
                changes.append(f"{pack_name}: evilities.json {want['id']}")
                rules[str(want['id'])] = r
            mp = pack / 'mod.json'
            meta = read(mp)
            line = adaptation_line(entry)
            adaptations = meta.get('source_import', {}).get('adaptations', [])
            old = [a for a in adaptations if a.startswith(f"evility {entry['d4_name']} ({entry['d4_id']}):")]
            if old != [line]:
                changes.append(f"{pack_name}: mod.json adaptation line")
                adaptations = [a for a in adaptations if a not in old]
                adaptations.append(line)
                meta.setdefault('source_import', {})['adaptations'] = adaptations
            if args.write:
                dump(sp, patch)
                dump(ep, {'evilities': rules})
                dump(mp, meta)

    for line in changes:
        print(('WROTE ' if args.write else 'WOULD WRITE ') + line)
    for line in problems:
        print('PROBLEM ' + line)
    print(f"{len(changes)} change(s), {len(problems)} problem(s), "
          f"{len(content['rows'])} row(s) in {args.content}")
    if problems or (changes and not args.write):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
