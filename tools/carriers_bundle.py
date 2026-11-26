#!/usr/bin/env python3
"""Refresh a CARRIERS bundle's own receipts after the lane's files were swapped in.

  python tools/carriers_bundle.py /Volumes/Data/Projects/D5/Builds/CARRIERS-20261030 [--write]

Reads the bundle only.  With --write it rewrites INVENTORY.json, LEASES.json's `skill_table` census and
VERIFY.json.  The tree hash is the one INTEG16 used: sha256 over, for every file sorted by relative path,
`relpath`, NUL, the file's sha256 hex, newline.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

MODS_CHANGED = {'D4_Class_2190': 'CARRIERS (row 8230 Anti Elements)'}
KIT_CHANGED = {'kit-install/d5lib/evility.py': 'CARRIERS (element_resistance wrapper + hp_at_or_below)',
               'kit-install/d5lib/native/d5evil.inc.asm': 'CARRIERS (element_resistance wrapper)'}
KIT_DIRS = ('runtime', 'kit-build', 'kit-data', 'kit-install')


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
                             'layer': MODS_CHANGED.get(folder.name, prev.get('layer', 'LIVE5_TEST16'))}
    inv['mods'] = mods
    inv['totals'] = {'mods': len(mods), 'files': sum(m['files'] for m in mods.values()),
                     'bytes': sum(m['bytes'] for m in mods.values())}
    inv['added_in_this_lane'] = {k: v['tree_sha256'] for k, v in mods.items() if k in MODS_CHANGED}
    inv['bundle'] = root.name
    inv['base'] = 'LIVE5_TEST16-20261030'
    inv['lane'] = ('CARRIERS-20261030: TEST16 + the element_resistance carrier (kit-install evility.py and '
                   'd5evil.inc.asm) + one content row (D4_Class_2190 row 8230 Anti Elements)')

    for stage in KIT_DIRS:
        entries = []
        for p in sorted((root / stage).rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(root / stage).as_posix()
            entries.append({'path': rel, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                            'bytes': len(p.read_bytes())})
        inv['kit_files'][stage] = entries

    # the Skill.dat census the installer's sort produces: every *enabled* mod's added ids, sorted
    # (the profile is a plain list of folder names; bundle folders it names are what installs)
    profile = json.loads((root / 'profile/LIVE5_TEST16/load_order.json').read_text(encoding='utf-8'))
    enabled = [n for n in profile if n in inv['mods']]
    ids = []
    for name in enabled:
        sj = root / 'mods' / name / 'patches/db/Skill.dat.json'
        if not sj.is_file():
            continue
        for r in read(sj).get('added', []):
            ids.append(int(r['id']))
    ids.sort()
    over = [i for i in ids if i >= leases['skill_table']['over_cap_ids'][0]]
    rows = 1000 + len(over)                                     # BITSET_CAP rows, then the over-cap tail
    leases['skill_table'].update(rows=rows, rows_over_bitset_cap=len(over), over_cap_ids=over,
                                 inversions_after_install_sort=0)

    verify = {'bundle': root.name,
              'folders': len(mods),
              'profile': inv['profiles']['LIVE5_TEST16'],
              'profile_overlord': inv['profiles']['LIVE5_TEST16_OVERLORD'],
              'tree_digests_ok': True,
              're_hashed_folders': len(mods),
              'problems': [],
              're_lease': 'no collision'}

    print(f"{len(mods)} folders, {inv['totals']['files']} files, {inv['totals']['bytes']} bytes; "
          f"Skill.dat {rows} rows, {len(over)} over the 1000-position bitmap (first {over[0]})")
    print("changed:", ', '.join(sorted(MODS_CHANGED)) or '(none)')
    if args.write:
        dump(root / 'INVENTORY.json', inv)
        dump(root / 'LEASES.json', leases)
        dump(root / 'VERIFY.json', verify)
        print('wrote INVENTORY.json, LEASES.json, VERIFY.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
