"""PALFIX1 gates: structure, render, post-install replay, and the palette/pixel proof.

  * structure: `d5lib.anm.compare_structure`, baseline-relative — the built class banks must report no
    NEW findings against TEST28 (their base) and against SLIM29 (their content).
  * render vs SLIM29: every id x every key time x the ten rank palettes, **no exemption** — the merge
    must be pixel-identical to the build it replaces, which is what proves the colour error is zero.
  * render vs TEST28: the same sweep with ids 21/27 and the four stub ids 1011/1017/5001/5021 exempt —
    TEST28's own poses must be untouched.
  * post-install replay: both comparisons again through the installer's `grips` finalizer.
  * palette proof: which palette entries differ from TEST28, and proof that none of them is indexed by
    a base cell's pixels (i.e. existing art cannot see the change).

Receipts: Builds/PALFIX1-20261102/evidence/.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
OUT = ROOT / 'Builds/PALFIX1-20261102/palmerge'
EV = ROOT / 'Builds/PALFIX1-20261102/evidence'
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
DIFF = KIT / 'tools' / 'striderlift_render_diff.py'
BANKS = [('D1C_Class_11390', b) for b in base.manifest()['banks']['D1C_Class_11390']] + \
        [('D1C_Class_11400', b) for b in base.manifest()['banks']['D1C_Class_11400']]
STUBS = [21, 27, 1011, 1017, 5001, 5021]


def structure(path_a, path_b, label):
    a, b = anm.load(Path(path_a).read_bytes()), anm.load(Path(path_b).read_bytes())
    res = anm.compare_structure(a, b)
    (EV / f'structure-{label}.json').write_text(json.dumps(res, indent=1) + '\n')
    n = len(res['structural_problems'])
    print(f'  structure {label}: {n} new findings', flush=True)
    return res['structural_problems']


def render(baseline, rebuilt, receipt, *extra):
    cmd = [sys.executable, str(DIFF), str(baseline), str(rebuilt), str(EV / receipt),
           '--ranks', '10', '--baseline-label', Path(baseline).parent.name, *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.splitlines()
    print(f'  render {receipt}: {lines[-1] if lines else r.stderr[-300:]}', flush=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:], flush=True)
    return r.returncode, json.loads((EV / receipt).read_text())


def palette_proof():
    rows = {}
    for mod, bank in BANKS:
        t28 = anm.load(base.bank_path(mod, bank))
        new = anm.load(OUT / 'mods' / mod / base.REL / bank)
        use = np.zeros(256, np.int64)
        for c in t28.block.cells:
            if c.w and c.h:
                tex = t28.textures[c.tex]
                m = np.frombuffer(tex.data, np.uint8).reshape(tex.height, tex.width)
                use += np.bincount(m[c.y:c.y + c.h, c.x:c.x + c.w].ravel(), minlength=256)
        changed = []
        for p in range(10):
            a = anm.get_palette(t28, p)
            b = anm.get_palette(new, p)
            d = np.nonzero((a != b).any(1))[0].tolist()
            assert not (set(d) & set(np.nonzero(use)[0].tolist())), (mod, bank, p, 'touched a used entry')
            changed.append(d)
        rows[f'{mod}/{bank}'] = {'entries_changed': changed,
                                 'all_outside_base_usage': True,
                                 'palettes': len(new.block.palette_infos),
                                 'palette_images': len(new.palettes),
                                 'images_total': len(new.palettes) + len(new.textures)}
        print(f'  palette {mod}/{bank}: entries changed per rank '
              f'{sorted({len(c) for c in changed})} of 256, all unused by base pixels; '
              f'{len(new.block.palette_infos)} palettes, {len(new.palettes) + len(new.textures)} image headers',
              flush=True)
    (EV / 'palette-proof.json').write_text(json.dumps(rows, indent=1) + '\n')


def main():
    EV.mkdir(parents=True, exist_ok=True)
    ok = True
    for mod, bank in BANKS:
        built = OUT / 'mods' / mod / base.REL / bank
        t28 = base.base_dir(mod) / mod / base.REL / bank
        slim = SLIM / mod / base.REL / bank
        ok &= not structure(t28, built, f'{mod}-{bank}-vs-test28')
        ok &= not structure(slim, built, f'{mod}-{bank}-vs-slim29')
        for tag, base_path, extra in (('slim29', slim, ('--exempt',)),
                                      ('test28', t28, ('--exempt', *map(str, STUBS)))):
            rc, rec = render(base_path, built, f'render-{mod}-{bank}-vs-{tag}.json', *extra)
            ok &= rc == 0 and not rec['differences'] and rec['extra_ids'] == []
            rc, rec = render(base_path, built, f'postinstall-{mod}-{bank}-vs-{tag}.json', *extra,
                             '--post-install', '--baseline-passes', 'grips',
                             '--rebuilt-passes', 'grips', '--confirm-member-local')
            ok &= rc == 0 and not rec['differences'] and rec['extra_ids'] == []
    palette_proof()
    (EV / 'gate-summary.json').write_text(json.dumps({'pass': bool(ok)}, indent=1) + '\n')
    print('GATES', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
