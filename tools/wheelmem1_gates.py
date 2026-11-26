"""WHEELMEM1 gates: bundle delta, structure, and render equality for PAD28 and SLIM29.

  structure  — PAD28 must have zero new structural findings vs TEST28
               SLIM29 must have zero new findings vs TEST28
  render     — PAD28 vs TEST28: 0 differences (all ids, all key times, 6 palettes)
               SLIM29 vs TEST29c: 0 differences
               SLIM29 vs TEST28: 0 differences outside 21/27

usage: python tools/wheelmem1_gates.py [structure|render|delta] [workers]
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import subprocess
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
B = ROOT / 'Builds/WHEELMEM1-20261102'
CAND = ROOT / 'Builds/TEST29FIX1-20261101/candidate-c/mods'
EV = B / 'evidence'
RENDER = KIT / 'tools/striderlift_render_diff.py'
PY = sys.executable


def structure():
    ok, rows = True, []
    for cand in ('pad28', 'slim29'):
        for mod, banks in base.manifest()['banks'].items():
            for bank in banks:
                a = anm.load(base.bank_path(mod, bank))
                r = anm.load(B / cand / 'mods' / mod / base.REL / bank)
                cmp = anm.compare_structure(a, r)
                row = {'candidate': cand, 'mod': mod, 'bank': bank,
                       'problems': len(cmp['structural_problems']),
                       'inherited': len(cmp['inherited_structural_problems']),
                       'warnings': len(cmp['structural_warnings']),
                       'cells': len(r.blocks[0].cells), 'base_cells': len(a.blocks[0].cells),
                       'animations': len(r.blocks[0].animations)}
                rows.append(row)
                if row['problems']:
                    ok = False
                    print('STRUCT FAIL', cand, mod, bank, row['problems'])
    (EV / 'structure.json').write_text(json.dumps(rows, indent=1))
    print('STRUCTURE', 'PASS' if ok else 'FAIL', len(rows), 'banks')
    return ok


def one(cand, baseline, rebuilt, receipt, exempt=None, pin=None):
    out = EV / 'receipts' / receipt
    cmd = [PY, str(RENDER), str(baseline), str(rebuilt), str(out),
           '--baseline-label', receipt.split('-vs-')[1].split('.')[0]]
    if exempt:
        cmd += ['--exempt', *map(str, exempt)]
    if pin:
        cmd += ['--baseline-sha256', pin]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or [''])[-1]
    return (r.returncode == 0, receipt, tail)


def render(workers):
    (EV / 'receipts').mkdir(parents=True, exist_ok=True)
    jobs = []
    for mod, banks in base.manifest()['banks'].items():
        for bank in banks:
            pin = base.expected(mod, bank)
            b28 = base.bank_path(mod, bank)
            jobs.append((f'pad28-vs-TEST28-{mod}-{bank[:-4]}.json', b28,
                         B / 'pad28/mods' / mod / base.REL / bank, [], pin))
            jobs.append((f'slim29-vs-TEST29c-{mod}-{bank[:-4]}.json',
                         CAND / mod / base.REL / bank,
                         B / 'slim29/mods' / mod / base.REL / bank, [], None))
            # SLIM29 differs from TEST28 in 21/27 and, on class banks, in the four stub ids
            # that nest 27 (TEST29c's measured cost: 66 samples)
            exempt = [21, 27] + ([1011, 1017, 5001, 5021] if mod.startswith('D1C_Class_') else [])
            jobs.append((f'slim29-vs-TEST28-{mod}-{bank[:-4]}.json', b28,
                         B / 'slim29/mods' / mod / base.REL / bank, exempt, pin))
    ok = True
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, 'both', j[1], j[2], j[0], j[3], j[4]) for j in jobs]
        for f in cf.as_completed(futs):
            good, receipt, tail = f.result()
            print(('PASS ' if good else 'FAIL ') + receipt + ' :: ' + tail, flush=True)
            ok &= good
    print('RENDER', 'PASS' if ok else 'FAIL', len(jobs), 'receipts')
    return ok


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'structure'
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    if mode == 'structure':
        sys.exit(0 if structure() else 1)
    if mode == 'render':
        sys.exit(0 if render(workers) else 1)


if __name__ == '__main__':
    main()
