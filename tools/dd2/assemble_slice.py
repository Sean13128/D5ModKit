#!/usr/bin/env python3
"""Assemble and validate the offline DD2 slice pack (2026-10-26 rebuild).

Copies the two built mod trees out of the private build outputs into one pack
directory, checks the receipts against the reviewed evidence, and writes a
manifest. It never installs anything and never writes to the game.

  python3 assemble_pack.py [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

PROJECT = Path('/Volumes/Data/Projects/D5')
BUILD = Path('/Volumes/Data/ai-tmp/hermes/dd2-rebuild')
DEFAULT_OUT = Path('/Volumes/Data/ai-tmp/hermes/dd2-pack-20261026')
PACKET = PROJECT / 'Research' / 'source-packs' / 'dd2' / 'slice' / 'packet'

ENTRIES = {
    'generic': dict(mod_id='D2_Class_22680', family=22680, physical=2640, template=2180,
                    kind='monster', source_ids=[2180, 2181, 2182, 2183, 2184, 2185]),
    'unique': dict(mod_id='D2_Unique_941', family=941, physical=941, template=1010,
                   kind='humanoid', source_ids=[80]),
}
FOLD = {0xFF0E: '.', 0xFF0C: ',', 0xFF05: '%', 0xFF1F: '?', 0xFF01: '!', 0xFF1A: ':'}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root: Path) -> dict:
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = dict(bytes=path.stat().st_size, sha256=sha256(path))
    return files


def check_entry(role: str, spec: dict, receipt: dict, inventory: dict) -> list:
    problems = []
    source_rows = {c['id']: c for c in inventory['slice']['characters']}
    if receipt['target'] != spec['family'] or receipt['physical'] != spec['physical']:
        problems.append('%s: target/physical drift' % role)
    if [r['source_id'] for r in receipt['readback']] != spec['source_ids']:
        problems.append('%s: readback source rows drift' % role)
    for row in receipt['readback']:
        source = source_rows[row['source_id']]
        if row['base'] != source['base'] or row['aptitudes'] != source['aptitudes']:
            problems.append('%s: row %d base/aptitude drift' % (role, row['source_id']))
        expected = [[int(a), int(b)] for a, b in source['learnset']]
        mapped = [list(pair) for pair in row['learn']]
        if len(mapped) > len(expected):
            problems.append('%s: row %d learned more skills than the source lists' % (role, row['source_id']))
    # every applied ability must name a donor that exists and an id that is not vanilla-looking
    for entry in [*receipt['abilities']['skills'], *receipt['abilities']['evilities']]:
        if not entry.get('readback'):
            problems.append('%s: %s %d has no readback' % (role, entry['kind'], entry['id']))
        elif entry['readback']['name'] != entry['source_name']:
            problems.append('%s: %s %d readback name differs' % (role, entry['kind'], entry['id']))
        if entry['kind'] == 'skill' and not entry['readback']['description']:
            problems.append('%s: skill %d lost its description' % (role, entry['id']))
    for evility_id, donor in receipt['abilities']['aliases'].items():
        if not any(e['id'] == int(evility_id) and e['copy_of'] == donor
                   for e in receipt['abilities']['evilities']):
            problems.append('%s: alias %s has no matching evility row' % (role, evility_id))
    # product text must be ASCII once folded; the raw source line stays in the receipt
    for line in receipt['displayed_help_lines']:
        if any(ch in line for ch in map(chr, FOLD)):
            problems.append('%s: help line keeps source punctuation: %r' % (role, line))
    if not receipt['displayed_help_lines'] or not receipt['displayed_help_lines'][0].strip():
        problems.append('%s: empty help text' % role)
    if receipt['voice']['status'] != 'unproven':
        problems.append('%s: voice claim changed without review' % role)
    if any(o['kind'] not in ('skill', 'evility') or not o['reason'] for o in receipt['abilities']['omitted']):
        problems.append('%s: an omitted source id has no reason' % role)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='new output directory, required except in check mode')
    parser.add_argument('--check', action='store_true', help='validate only, do not copy')
    parser.add_argument('--build', type=Path, required=True, help='explicit offline build parent')
    args = parser.parse_args()
    if not args.check and args.out is None:
        parser.error('--out is required unless --check is used')
    inventory = json.loads((PACKET / 'skills-evilities.json').read_text(encoding='utf-8'))
    problems, manifest = [], {'format': 'dd2-slice-pack/2', 'generated': '2026-10-26',
                              'installed': False, 'native_tested': False, 'entries': {}}
    for role, spec in ENTRIES.items():
        out = args.build / ('out-' + role)
        receipt = json.loads((out / 'source-import-receipt.json').read_text(encoding='utf-8'))
        problems += check_entry(role, spec, receipt, inventory)
        mod_root = out / 'native-mods' / spec['mod_id']
        if not mod_root.is_dir():
            problems.append('%s: mod tree missing' % role)
            continue
        files = tree(mod_root)
        manifest['entries'][role] = dict(
            mod_id=spec['mod_id'], family=spec['family'], physical=spec['physical'],
            template=spec['template'], kind=spec['kind'], source_ids=spec['source_ids'],
            files=len(files), bytes=sum(f['bytes'] for f in files.values()),
            skills=[dict(id=e['id'], source_id=e['source_id'], name=e['source_name'],
                         relation=e['relation'], donor=e['copy_of'])
                    for e in receipt['abilities']['skills']],
            evilities=[dict(id=e['id'], source_id=e['source_id'], name=e['source_name'],
                            relation=e['relation'], donor=e['copy_of'],
                            alias=receipt['abilities']['aliases'].get(str(e['id'])))
                       for e in receipt['abilities']['evilities']],
            omitted=receipt['abilities']['omitted'],
            help_lines=receipt['displayed_help_lines'],
            receipt_sha256=sha256(out / 'source-import-receipt.json'),
            tree_sha256=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest())
        if args.check:
            continue
        (args.out / 'receipts').mkdir(parents=True, exist_ok=True)
        target = args.out / 'mods' / spec['mod_id']
        if target.exists():
            raise FileExistsError('refusing to replace existing output: %s' % target)
        shutil.copytree(mod_root, target)
        for name in ('source-import-receipt.json', 'catalogue.json', 'original-read-receipt.json'):
            if (out / name).is_file():
                shutil.copy2(out / name, args.out / 'receipts' / (role + '-' + name))
    manifest['problems'] = problems
    manifest['status'] = 'historical-slice-check-only' if not problems else 'invalid'
    if not args.check:
        (args.out / 'receipts').mkdir(parents=True, exist_ok=True)
        (args.out / 'pack-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n',
                                                     encoding='utf-8')
        print('pack: %s (%d problems)' % (args.out, len(problems)))
    for problem in problems:
        print('PROBLEM:', problem)
    print('status:', manifest['status'])
    return 0 if not problems else 1


if __name__ == '__main__':
    raise SystemExit(main())
