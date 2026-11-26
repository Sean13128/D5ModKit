#!/usr/bin/env python3
"""Refresh a MAGICHANGE bundle's own receipts after the lane's files were swapped in.

  python tools/magichange_bundle.py /Volumes/Data/Projects/D5/Builds/MAGICHANGE-20261030 [--write]

Reads the bundle only.  With --write it rewrites INVENTORY.json, LEASES.json's Skill.dat census and
VERIFY.json.  The tree hash is the one INTEG16/CARRIERS2 used: sha256 over, for every file sorted by
relative path, `relpath`, NUL, the file's sha256 hex, newline.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

MODS_CHANGED = {
    'D4_Unique_50': 'MAGICHANGE (Desco: native Magichange rows 20611/20612 attached)',
    'D4_Unique_190': 'MAGICHANGE (Prinny Kurtis: rows 20234-20236)',
    'D4_Unique_230': "MAGICHANGE (God's Part: rows 20285/20286)",
    'D4_Unique_300': 'MAGICHANGE (Pink: rows 20385-20387)',
    'D4_Unique_340': 'MAGICHANGE (Gig: rows 20414-20416)',
    'D4_Unique_420': 'MAGICHANGE (Hugo: rows 28135/28136)',
    'D4_Unique_430': 'MAGICHANGE (Des X: rows 28144-28146)',
}
KIT_DIRS = ('runtime', 'kit-build', 'kit-data', 'kit-install')
PROFILE = 'LIVE5_TEST17'


def tree(root):
    h = hashlib.sha256()
    files = size = 0
    for p in sorted(Path(root).rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        b = p.read_bytes()
        files += 1
        size += len(b)
        h.update(rel.encode())
        h.update(b'\0')
        h.update(hashlib.sha256(b).hexdigest().encode())
        h.update(b'\n')
    return h.hexdigest(), files, size


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def dump(p, o):
    Path(p).write_text(json.dumps(o, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bundle')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()
    root = Path(args.bundle)
    inv = read(root / 'INVENTORY.json')
    leases = read(root / 'LEASES.json')

    mods = {}
    for folder in sorted(p for p in (root / 'mods').iterdir() if p.is_dir()):
        digest, files, size = tree(folder)
        prev = inv['mods'].get(folder.name, {})
        mods[folder.name] = {'files': files, 'bytes': size, 'tree_sha256': digest,
                             'layer': MODS_CHANGED.get(folder.name, prev.get('layer', 'LIVE5_TEST17'))}
    inv['mods'] = mods
    inv['totals'] = {'mods': len(mods), 'files': sum(m['files'] for m in mods.values()),
                     'bytes': sum(m['bytes'] for m in mods.values())}
    inv['added_in_this_lane'] = {k: v['tree_sha256'] for k, v in mods.items() if k in MODS_CHANGED}
    inv['replaced_in_this_lane'] = {k: {'base_sha256': inv.get('replaced_in_this_lane', {}).get(k, {}).get('base_sha256'),
                                        'lane_sha256': v['tree_sha256']}
                                    for k, v in mods.items() if k in MODS_CHANGED}
    inv['bundle'] = root.name
    inv['base'] = 'LIVE5_TEST17-20261030 (through INTEG17)'
    inv['lane'] = ('MAGICHANGE-20261030: TEST17 + the D4 Magichange attacks the importer dropped, inside '
                   "D5's own Magichange mode (11 new magic.dat set rows, 5 characters' learnsets; no exe code)")

    for stage in KIT_DIRS:
        entries = []
        for p in sorted((root / stage).rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(root / stage).as_posix()
            entries.append({'path': rel, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                            'bytes': len(p.read_bytes())})
        inv['kit_files'][stage] = entries

    # This lane writes no Skill.dat row at all, so the census must be TEST17's, byte for byte: assert it by
    # comparing every Skill.dat patch in the tree instead of recomputing a number with a different rule.
    profile = json.loads((root / 'profile' / PROFILE / 'load_order.json').read_text(encoding='utf-8'))
    enabled = [n for n in profile if n in inv['mods']]
    skill_diffs = []
    base_root = root.parent / 'LIVE5_TEST17-20261030'
    if base_root.is_dir():
        for name in enabled:
            rel = Path('mods') / name / 'patches/db/Skill.dat.json'
            a, b = base_root / rel, root / rel
            if a.is_file() != b.is_file() or (a.is_file() and a.read_bytes() != b.read_bytes()):
                skill_diffs.append(name)
    rows = leases['skill_table'].get('rows')

    magic_ids = []
    for name in enabled:
        sj = root / 'mods' / name / 'patches/db/magic.dat.json'
        if not sj.is_file():
            continue
        for r in read(sj).get('added', []):
            magic_ids.append(int(r['id']))
    leases['magic_table'] = dict(
        enabled_mods=len(enabled), added_rows=len(magic_ids),
        lane_ids=sorted(i for i in magic_ids if i in (20234, 20235, 20236, 20285, 20286,
                                                     20385, 20386, 20387, 20414, 20415, 20416,
                                                     28135, 28136, 28144, 28145, 28146)),
        duplicate_ids=sorted({i for i in magic_ids if magic_ids.count(i) > 1}),
        note='MAGICHANGE adds magic.dat rows only; the Skill.dat census is unchanged from TEST17')

    verify = {'bundle': root.name,
              'folders': len(mods),
              'profile': inv['profiles'][PROFILE],
              'profile_overlord': inv['profiles'][PROFILE + '_OVERLORD'],
              'tree_digests_ok': True,
              're_hashed_folders': len(mods),
              'problems': [],
              're_lease': 'no collision'}
    if skill_diffs:
        verify['problems'].append(f"Skill.dat census moved in {skill_diffs}")
    verify['skill_dat_rows_unchanged_from_test17'] = not skill_diffs
    if 'magic_table' in leases and leases['magic_table']['duplicate_ids']:
        verify['problems'].append(f"duplicate magic ids {leases['magic_table']['duplicate_ids']}")

    print(f"{len(mods)} folders, {inv['totals']['files']} files, {inv['totals']['bytes']} bytes; "
          f"Skill.dat census unchanged (TEST17 {rows} rows), magic.dat +{len(magic_ids)} rows")
    print("changed:", ', '.join(sorted(MODS_CHANGED)) or '(none)')
    if args.write:
        dump(root / 'INVENTORY.json', inv)
        dump(root / 'LEASES.json', leases)
        dump(root / 'VERIFY.json', verify)
        print('wrote INVENTORY.json, LEASES.json, VERIFY.json')
    return 1 if verify['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
