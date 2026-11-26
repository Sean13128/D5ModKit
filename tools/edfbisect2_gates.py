"""EDFBISECT2 gates: structure + render for the four part-only EDF variants.

Receipts in Builds/EDFBISECT2-20261102/evidence/.

  * structure, baseline-relative (d5lib.anm.compare_structure, gatestruct1 1ffbe91): each variant's
    EDF bank must report no NEW findings against TEST28 (its base) and against BS-DARK (its delta
    source).
  * render (tools/striderlift_render_diff.py, kit renderer, six rank palettes): every reachable
    pose of every variant must be pixel-identical to TEST28. The variants keep TEST28's table 0
    and roots 74/92, so no id is added and none may differ.
  * post-install replay (--post-install --baseline-passes grips --rebuilt-passes grips
    --confirm-member-local): the same equality after the installer's `grips` finalizer.
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
OUT = ROOT / 'Builds/EDFBISECT2-20261102'
EV = OUT / 'evidence'
DARK = ROOT / 'Builds/WHEELBISECT1-20261102/bs_dark/mods'
DIFF = KIT / 'tools' / 'striderlift_render_diff.py'
EDF = 'D1C_Class_11400'
STRIDER = 'D1C_Class_11390'
VARIANTS = ('eb_pal', 'eb_pix', 'eb_tab', 'eb_tabpal')


def structure(baseline, rebuilt, label):
    a = anm.load(Path(baseline).read_bytes())
    b = anm.load(Path(rebuilt).read_bytes())
    res = anm.compare_structure(a, b)
    problems = res['structural_problems']
    print(f'  structure {label}: {len(problems)} new findings', flush=True)
    (EV / f'structure-{label}.json').write_text(json.dumps(res, indent=1) + '\n')
    return problems


def render(baseline, rebuilt, receipt, *extra):
    cmd = [sys.executable, str(DIFF), str(baseline), str(rebuilt), str(EV / receipt),
           '--baseline-label', 'TEST28', *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.splitlines() if ln.startswith(('PASS', 'FAIL', 'refusing'))]
    print(f'  render {receipt}: {tail or r.stdout.strip().splitlines()[-1:]} (rc {r.returncode})',
          flush=True)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:], flush=True)
    return r.returncode, json.loads((EV / receipt).read_text())


def main():
    EV.mkdir(parents=True, exist_ok=True)
    ok = True
    banks = [(EDF, b) for b in base.manifest()['banks'][EDF]]
    for variant in VARIANTS:
        for mod, bank in banks:
            built = OUT / variant / 'mods' / mod / base.REL / bank
            for label, ref in (('test28', base.base_dir(mod) / mod / base.REL / bank),
                               ('dark', DARK / mod / base.REL / bank)):
                problems = structure(ref, built, f'{variant}-{mod}-{bank}-vs-{label}')
                ok &= not problems
            # no id is exempt: the variants keep TEST28's table 0, roots and art, so every
            # sampled pose of every id (including the four lift ids) must be identical
            rc, rec = render(base.base_dir(mod) / mod / base.REL / bank, built,
                             f'render-{variant}-{mod}-{bank}-vs-test28.json', '--exempt')
            ok &= rc == 0 and not rec['differences'] and rec['extra_ids'] == []
            rc, rec = render(base.base_dir(mod) / mod / base.REL / bank, built,
                             f'postinstall-{variant}-{mod}-{bank}-vs-test28.json', '--exempt',
                             '--post-install', '--baseline-passes', 'grips',
                             '--rebuilt-passes', 'grips', '--confirm-member-local')
            ok &= rc == 0 and not rec['differences'] and rec['extra_ids'] == []
    (EV / 'gate-summary.json').write_text(json.dumps({'pass': bool(ok)}, indent=1) + '\n')
    print('GATES', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
