"""WHEELFIX1 gates: structure + render (pre-install and post-install replay) for BS-WHEELFIX.

Claims, per class bank:

  structure   anm.compare_structure reports no NEW findings against SLIM29 (the base) and against
              TEST28 (the other reference) -- i.e. the five copies and the 11 re-pointed keys add
              nothing structurally wrong.
  render A    vs TEST28: the wheel-reachable closure {1, 7, 11, 101, 1001, 6001} renders exactly
              like TEST28 at every id x key time x 6 rank palettes. Every other difference must be
              an id that transitively nests 21/27 (its nested view still shows SLIM29's hurt art).
  render B    vs SLIM29: differences only in the three re-pointed owners {1, 101, 6001}; ids 7, 11,
              21, 27, 1001 and every non-wheel animation are pixel-identical to SLIM29 (so battle
              hurt is unchanged).
  post-install  the same two comparisons after replaying the installer's member-local `grips` pass
              on both sides.

Receipts: Builds/WHEELFIX1-20261102/evidence/.
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
OUT = ROOT / 'Builds/WHEELFIX1-20261102'
EV = OUT / 'evidence'
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
T28 = {m: base.base_dir(m) / m for m in ('D1C_Class_11390', 'D1C_Class_11400')}
DIFF = KIT / 'tools' / 'striderlift_render_diff.py'
WHEEL_CLOSURE = [1, 7, 11, 101, 1001, 6001]
REPOINTED = [1, 101, 6001]
HURT = (21, 27)
NESTED = 0x100


def structure(baseline, rebuilt, label):
    res = anm.compare_structure(anm.load(Path(baseline).read_bytes()),
                               anm.load(Path(rebuilt).read_bytes()))
    problems = res['structural_problems']
    (EV / f'structure-{label}.json').write_text(json.dumps(res, indent=1) + '\n')
    return problems


def nesting(bank_path):
    """{animation id: ids its nested tree reaches} for one bank."""
    b = anm.load(Path(bank_path).read_bytes()).block
    ids = {a.id for a in b.animations}
    e = {}
    for a in b.animations:
        seen, todo, tg = set(), [a.root], set()
        while todo:
            ni = todo.pop()
            if ni in seen or not 0 <= ni < len(b.nodes):
                continue
            seen.add(ni)
            n = b.nodes[ni]
            todo.extend((n.child, n.next))
            if n.first_key < 0:
                continue
            for ki in range(n.first_key, n.first_key + n.num_keys):
                k = b.keys[ki]
                if k.flags & NESTED and 0 <= k.param < len(b.params):
                    t = abs(b.params[k.param])
                    if t in ids and t != a.id:
                        tg.add(t)
        e[a.id] = tg
    reach = {}
    for aid in e:
        seen, todo = set(), [aid]
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            todo.extend(e.get(x, ()))
        reach[aid] = seen
    return reach


def render(baseline, rebuilt, receipt, *extra, post=False):
    cmd = [sys.executable, str(DIFF), str(baseline), str(rebuilt), str(EV / receipt),
           '--baseline-label', 'BASELINE', *extra]
    if post:
        cmd += ['--post-install', '--confirm-member-local',
                '--baseline-passes', 'grips', '--rebuilt-passes', 'grips']
    r = subprocess.run(cmd, capture_output=True, text=True)
    rec = json.loads((EV / receipt).read_text())
    assert rec.get('samples_compared', 0) > 0, (receipt, r.stdout[-1200:], r.stderr[-1200:])
    assert not rec['structural_problems'], (receipt, rec['structural_problems'])
    return rec


def main():
    EV.mkdir(parents=True, exist_ok=True)
    ok = True
    rows = []
    banks = [(m, b) for m in T28 for b in base.manifest()['banks'][m]]
    for mod, bank in banks:
        built = OUT / 'mods' / mod / base.REL / bank
        row = {'bank': f'{mod}/{bank}'}
        for label, ref in (('slim29', SLIM / mod / base.REL / bank),
                           ('test28', T28[mod] / base.REL / bank)):
            problems = structure(ref, built, f'wheelfix-{mod}-{bank}-vs-{label}')
            print(f'  structure vs {label} {mod}/{bank}: {len(problems)} new findings', flush=True)
            row[f'structure_vs_{label}'] = problems
            ok &= not problems

        reach = nesting(built)
        nests_hurt = sorted(a for a, r in reach.items() if r & set(HURT))
        copies = sorted({a.id for a in anm.load(built.read_bytes()).block.animations}
                        - {a.id for a in anm.load((SLIM / mod / base.REL / bank).read_bytes())
                           .block.animations})
        extra = [str(c) for c in copies]

        # A: vs TEST28 -- the wheel closure must be pixel-identical, the rest may differ only
        #    because it still nests SLIM29's 21/27
        rec = render(T28[mod] / base.REL / bank, built,
                     f'render-wheelfix-{mod}-{bank}-vs-test28.json', '--expect-extra', *extra)
        ids = sorted({d['id'] for d in rec['differences']})
        closure_diffs = sorted(set(ids) & set(WHEEL_CLOSURE))
        undeclared = sorted(set(ids) - set(nests_hurt) - set(HURT))
        closure_samples = sum(len(rec['animation_samples'].get(str(a), [])) * 6
                              for a in WHEEL_CLOSURE if str(a) in rec['animation_samples'])
        print(f'  render A {mod}/{bank}: {rec["samples_compared"]} samples, {len(rec["differences"])} '
              f'differences on {len(ids)} ids; closure ids differ: {closure_diffs}; '
              f'undeclared: {undeclared}', flush=True)
        row.update({'render_vs_test28': {'samples': rec['samples_compared'],
                                         'difference_ids': ids,
                                         'closure_ids_differing': closure_diffs,
                                         'undeclared_differing': undeclared,
                                         'closure_samples': closure_samples,
                                         'extra_ids': rec['extra_ids']}})
        ok &= not closure_diffs and not undeclared and rec['extra_ids'] == copies

        # B: vs SLIM29 -- only the re-pointed owners may move; 21/27 stay SLIM29's
        rec = render(SLIM / mod / base.REL / bank, built,
                     f'render-wheelfix-{mod}-{bank}-vs-slim29.json', '--expect-extra', *extra)
        ids = sorted({d['id'] for d in rec['differences']})
        hurt_diffs = sorted(set(ids) & set(HURT))
        print(f'  render B {mod}/{bank}: {len(rec["differences"])} differences on ids {ids}; '
              f'21/27 among them: {hurt_diffs}', flush=True)
        row.update({'render_vs_slim29': {'samples': rec['samples_compared'],
                                         'difference_ids': ids,
                                         'hurt_ids_differing': hurt_diffs,
                                         'extra_ids': rec['extra_ids']}})
        ok &= set(ids) <= set(REPOINTED) and not hurt_diffs and rec['extra_ids'] == copies

        # post-install replay of `grips` on both sides
        for name, ref in (('test28', T28[mod] / base.REL / bank),
                          ('slim29', SLIM / mod / base.REL / bank)):
            rec = render(ref, built, f'postgainstall-wheelfix-{mod}-{bank}-vs-{name}.json',
                         '--expect-extra', *extra, post=True)
            ids = sorted({d['id'] for d in rec['differences']})
            closure_diffs = sorted(set(ids) & set(WHEEL_CLOSURE))
            print(f'  post-install vs {name} {mod}/{bank}: {rec["samples_compared"]} samples, '
                  f'{len(rec["differences"])} differences on {len(ids)} ids; '
                  f'closure ids differ: {closure_diffs}', flush=True)
            row[f'postinstall_vs_{name}'] = {'samples': rec['samples_compared'],
                                             'difference_ids': ids,
                                             'closure_ids_differing': closure_diffs}
            ok &= not closure_diffs
        rows.append(row)

    (EV / 'gate-summary.json').write_text(json.dumps({'pass': bool(ok), 'banks': rows},
                                                     indent=1) + '\n')
    print('GATES', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
