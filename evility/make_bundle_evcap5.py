#!/usr/bin/env python3
"""Build Builds/EVCAP5-<date>/ — the overlay that gives imported evilities a display category.

Two kit files, one per Kit line, plus rollback copies of what each line ships today, the probes'
receipts, INSTALL.md and LIVE-CHECK.md.  Writes VERIFY.json last: per-file hashes, the two
variants' behavioural check (from evility/probe_evcap5_variants.py), and the marker test that
both variants carry the same fix.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get('D5_KIT', os.path.dirname(HERE))
DATE = os.environ.get('D5_DATE', '20261030')
OUT = os.environ.get('D5_OUT', f'/Volumes/Data/Projects/D5/Builds/EVCAP5-{DATE}')
BASES = os.environ.get('D5_BASES', '/Volumes/Data/ai-tmp/evcap5/bases')
VARIANT_16 = os.path.join(BASES, 'dbpatch-test16.py')          # patched by evility/apply_evcap5.py
VARIANT_18B = os.path.join(BASES, 'dbpatch-test18b.py')
VARIANT_INSTALLED = os.path.join(BASES, 'dbpatch-installed.py')
ROLLBACK_16 = '/Volumes/Data/Projects/D5/Builds/LIVE5_TEST16-20261030/kit-install/d5lib/dbpatch.py'
ROLLBACK_18B = '/Volumes/Data/Projects/D5/Builds/LIVE5_TEST18B-20261030/kit-install/d5lib/dbpatch.py'
ROLLBACK_INSTALLED = '/Volumes/Data/Projects/D5/Local/Installed D5ModKit/d5lib/dbpatch.py'
RESULTS = os.path.join(HERE, 'results')
MARKERS = ('EVILITY_CATEGORY', 'def fix_evility_category', 'fix_evility_category(_row, table.name)')


def sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main():
    if os.path.isdir(OUT):
        raise SystemExit(f'{OUT} already exists; move it aside first')
    for rel in ('kit/d5lib', 'kit-18b/d5lib', 'kit-installed/d5lib', 'rollback/d5lib',
                'rollback-18b/d5lib', 'rollback-installed/d5lib', 'receipts', 'probes'):
        os.makedirs(os.path.join(OUT, rel), exist_ok=True)
    placed = {
        'kit/d5lib/dbpatch.py': VARIANT_16,
        'kit-18b/d5lib/dbpatch.py': VARIANT_18B,
        'kit-installed/d5lib/dbpatch.py': VARIANT_INSTALLED,
        'rollback/d5lib/dbpatch.py': ROLLBACK_16,
        'rollback-18b/d5lib/dbpatch.py': ROLLBACK_18B,
        'rollback-installed/d5lib/dbpatch.py': ROLLBACK_INSTALLED,
    }
    files = {}
    for rel, src in placed.items():
        if not os.path.exists(src):
            raise SystemExit(f'missing source for {rel}: {src}')
        dst = os.path.join(OUT, rel)
        shutil.copyfile(src, dst)
        files[rel] = {'bytes': os.path.getsize(dst), 'sha256': sha256(dst), 'from': src}
    for name in ('evcap5-replay-before.json', 'evcap5-replay-after.json',
                 'evcap5-listbuilder.json', 'evcap5-variants.json',
                 'evcap5-payload-invariance.json'):
        src = os.path.join(RESULTS, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(OUT, 'receipts', name))
            files[f'receipts/{name}'] = {'bytes': os.path.getsize(src), 'sha256': sha256(src),
                                         'from': src}
    for name in ('probe_evidence_list.py', 'probe_replay_equip.py', 'probe_build_table.py',
                 'probe_evcap5_variants.py', 'make_bundle_evcap5.py', 'apply_evcap5.py'):
        src = os.path.join(HERE, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(OUT, 'probes', name))
            files[f'probes/{name}'] = {'bytes': os.path.getsize(src), 'sha256': sha256(src),
                                       'from': src}
    # every variant carries the same three markers
    variants = {}
    for rel in ('kit/d5lib/dbpatch.py', 'kit-18b/d5lib/dbpatch.py', 'kit-installed/d5lib/dbpatch.py'):
        text = open(os.path.join(OUT, rel), encoding='utf-8').read()
        variants[rel] = {m: text.count(m) for m in MARKERS}
    markers_ok = all(all(v[m] >= 1 for m in MARKERS) for v in variants.values())
    receipt = os.path.join(OUT, 'receipts', 'evcap5-variants.json')
    variants_behaviour = json.load(open(receipt)) if os.path.exists(receipt) else {}
    verify = {
        'bundle': os.path.basename(OUT),
        'files': files,
        'variants': variants,
        'variants_carry_the_fix': markers_ok,
        'variants_behaviour_all_pass': all(r.get('all_pass') for r in variants_behaviour.values()),
        'rollback_is_the_base': {
            'TEST16': sha256(os.path.join(OUT, 'rollback/d5lib/dbpatch.py')) == sha256(ROLLBACK_16),
            'TEST18B': sha256(os.path.join(OUT, 'rollback-18b/d5lib/dbpatch.py')) == sha256(ROLLBACK_18B),
            'installed': sha256(os.path.join(OUT, 'rollback-installed/d5lib/dbpatch.py')) == sha256(ROLLBACK_INSTALLED),
        },
        'applies_to_any_version': 'probes/apply_evcap5.py',
        'problems': [],
    }
    if not markers_ok:
        verify['problems'].append('a variant is missing one of the fix markers')
    if not verify['variants_behaviour_all_pass']:
        verify['problems'].append('a variant failed the behavioural check')
    if not all(verify['rollback_is_the_base'].values()):
        verify['problems'].append('a rollback copy does not match its bundle')
    json.dump(verify, open(os.path.join(OUT, 'VERIFY.json'), 'w'), indent=1)
    json.dump(files, open(os.path.join(OUT, 'INVENTORY.json'), 'w'), indent=1)
    with open(os.path.join(OUT, 'INVENTORY.txt'), 'w') as fh:
        for rel, info in sorted(files.items()):
            fh.write(f'{info["sha256"]}  {info["bytes"]:>8}  {rel}\n')
    print(json.dumps({k: verify[k] for k in ('bundle', 'variants_carry_the_fix',
                                             'variants_behaviour_all_pass', 'rollback_is_the_base',
                                             'problems')}, indent=1))
    print('files', len(files))


if __name__ == '__main__':
    main()
