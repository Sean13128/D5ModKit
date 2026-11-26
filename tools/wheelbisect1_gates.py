"""WHEELBISECT1 gates: structure + render for the two bank-patched variants.

Receipts go to Builds/WHEELBISECT1-20261102/evidence/.

  * structure, baseline-relative (anm.compare_structure): BS-NOSTUB and BS-DARK against SLIM29
    (their base) and against TEST28 must report no new findings.
  * render (tools/striderlift_render_diff.py, kit renderer, six rank palettes):
      A  BS-DARK  vs TEST28      -> 0 differences, the two moved ids are the only extras
      B  BS-NOSTUB vs SLIM29     -> differences only in the four stubs (exempted), copies are extras
      C  BS-NOSTUB vs TEST28     -> the four stubs must NOT differ (they show TEST28's picture)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
OUT = ROOT / 'Builds/WHEELBISECT1-20261102'
EV = OUT / 'evidence'
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
T28 = {m: base.base_dir(m) / m for m in ('D1C_Class_11390', 'D1C_Class_11400')}
DIFF = KIT / 'tools' / 'striderlift_render_diff.py'
STUBS = [1011, 1017, 5001, 5021]


def structure(baseline_path, rebuilt_path, label):
    a = anm.load(Path(baseline_path).read_bytes())
    b = anm.load(Path(rebuilt_path).read_bytes())
    res = anm.compare_structure(a, b)
    problems = res['structural_problems']
    print(f'  structure {label}: {len(problems)} new findings', flush=True)
    (EV / f'structure-{label}.json').write_text(json.dumps(res, indent=1) + '\n')
    return problems


def render(baseline, rebuilt, receipt, *extra):
    cmd = [sys.executable, str(DIFF), str(baseline), str(rebuilt), str(EV / receipt),
           '--baseline-label', 'BASELINE', *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.splitlines() if ln.startswith(('PASS', 'FAIL', 'refusing'))]
    print(f'  render {receipt}: {tail or r.stdout.strip().splitlines()[-1:]} '
          f'(rc {r.returncode})', flush=True)
    if r.returncode not in (0,):
        print(r.stdout[-2000:], r.stderr[-2000:], flush=True)
    return r.returncode, json.loads((EV / receipt).read_text())


def main():
    EV.mkdir(parents=True, exist_ok=True)
    ok = True
    banks = [(m, b) for m in T28 for b in base.manifest()['banks'][m]]
    for variant, base_mods in (('bs_nostub', SLIM), ('bs_dark', SLIM)):
        for mod, bank in banks:
            built = OUT / variant / 'mods' / mod / base.REL / bank
            for label, ref in (('slim29', base_mods / mod / base.REL / bank),
                               ('test28', T28[mod] / base.REL / bank)):
                problems = structure(ref, built, f'{variant}-{mod}-{bank}-vs-{label}')
                if problems and len(problems) > 0:
                    added = {p.get('animation_id') for p in problems}
                    print('    findings by animation:', sorted(x for x in added if x))
                ok &= not problems

    # A: DARK vs TEST28 -- 0 differences, the moved ids are the only extras
    for mod, bank in banks:
        rc, rec = render(T28[mod] / base.REL / bank, OUT / 'bs_dark/mods' / mod / base.REL / bank,
                         f'render-dark-{mod}-{bank}-vs-test28.json',
                         '--expect-extra', '64001', '64011')
        ok &= rc == 0 and not rec['differences'] and rec['extra_ids'] == [64001, 64011]

    # B: NOSTUB vs SLIM29 -- only the four stubs differ (exempted); copies are extras
    for mod, bank in banks:
        rc, rec = render(SLIM / mod / base.REL / bank, OUT / 'bs_nostub/mods' / mod / base.REL / bank,
                         f'render-nostub-{mod}-{bank}-vs-slim29.json',
                         '--exempt', *[str(x) for x in STUBS],
                         '--expect-extra', '64031', '64041', '64051', '64061', '64071')
        ok &= rc == 0 and not rec['differences']

    # C: NOSTUB vs TEST28 -- the four stubs must not appear among the differences
    for mod, bank in banks:
        rc, rec = render(T28[mod] / base.REL / bank, OUT / 'bs_nostub/mods' / mod / base.REL / bank,
                         f'render-nostub-{mod}-{bank}-vs-test28.json')
        stub_diffs = sorted({d['id'] for d in rec['differences'] if d['id'] in STUBS})
        differing = sorted({d['id'] for d in rec['differences']})
        print(f'    nostub vs test28 {mod}/{bank}: {len(differing)} ids differ, '
              f'stubs among them: {stub_diffs}', flush=True)
        ok &= not stub_diffs

    (EV / 'gate-summary.json').write_text(json.dumps({'pass': bool(ok)}, indent=1) + '\n')
    print('GATES', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
