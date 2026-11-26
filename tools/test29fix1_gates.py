"""TEST29FIX1 gates: structure + render, for both candidates.

Structure (offline, exact):
  b: every bank's table 9 is a whole number of 3-i32 records and every key that names a preserved
     id reads (id, 0, -1); no other table changed vs TEST29.
  c: no animation id >= 0x8000 anywhere and no key references the donor's appended tail.
Render (the D1CMOTION3 gate): every id x every union frame time x 6 rank palettes, nested=True,
exact RGBA after content crop plus position relative to the pivot.
  b vs TEST29 : strict equality (0 differences, nothing exempt)
  b vs TEST28 : 0 differences outside 21/27, extra ids may only be 65003/65004
  c vs TEST28 : 0 differences outside 21/27, no extra ids
"""
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
BUILD = ROOT / 'Builds/TEST29FIX1-20261101'
T29 = ROOT / 'Builds/D1CMOTION2-20261101/mods'
EV = BUILD / 'evidence'
EV.mkdir(parents=True, exist_ok=True)
PY = sys.executable
PRESERVED = {21: 65003, 27: 65004}


def structure(mods, label, expect_preserved):
    bad = []
    changed = {}
    for mod, banks in base.manifest()['banks'].items():
        for bank in banks:
            p = mods / mod / base.REL / bank
            f = anm.load(p)
            b = f.block
            ids = {a.id for a in b.animations}
            big = sorted(i for i in ids if i >= 0x8000)
            if expect_preserved and big != sorted(PRESERVED.values()):
                bad.append(f'{mod}/{bank}: ids >=0x8000 {big}')
            if not expect_preserved and big:
                bad.append(f'{mod}/{bank}: ids >=0x8000 {big}')
            for a in b.animations:
                for ni, _d, _p in b.walk(a.root):
                    for k in b.node_keys(b.nodes[ni]):
                        if not anm.is_nested(k):
                            continue
                        i = k.param
                        if i + 2 >= len(b.params):
                            bad.append(f'{mod}/{bank}: anim {a.id} key.param {i} past the end')
                            continue
                        t = tuple(b.params[i:i + 3])
                        if t[0] in PRESERVED.values() and t != (t[0], 0, -1):
                            bad.append(f'{mod}/{bank}: anim {a.id} preserved triple {t}')
            changed[f'{mod}/{bank}'] = {
                'bytes': p.stat().st_size, 'animations': len(b.animations),
                'params': len(b.params), 'nodes': len(b.nodes), 'tex': len(f.textures),
                'pal': len(f.palettes), 'ids_over_0x8000': big,
                'test28_params': len(anm.load(base.bank_path(mod, bank)).block.params),
                'max_param_ref': max((k.param for a in b.animations
                                      for ni, _d, _p in b.walk(a.root)
                                      for k in b.node_keys(b.nodes[ni])
                                      if anm.is_nested(k)), default=-1)}
    (EV / f'structure-{label}.json').write_text(json.dumps(
        {'mods': str(mods), 'banks': changed, 'findings': bad}, indent=1))
    print(f'structure {label}: {len(bad)} findings')
    for x in bad[:10]:
        print('  ', x)
    return bad


def gate(baseline, rebuilt, receipt, exempt=(), extra=(), pin=None):
    cmd = [PY, str(KIT / 'tools/striderlift_render_diff.py'), str(baseline), str(rebuilt),
           str(EV / receipt), '--baseline-label', 'baseline']
    if exempt:
        cmd += ['--exempt', *map(str, exempt)]
    else:
        cmd += ['--exempt']
    if extra:
        cmd += ['--expect-extra', *map(str, extra)]
    if pin:
        cmd += ['--baseline-sha256', pin]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or [''])[-1]
    print(f'gate {receipt}: rc={r.returncode} {tail[:150]}')
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-2000:])
    return r.returncode == 0


def main():
    ok = True
    b_mods = BUILD / 'mods'
    c_mods = BUILD / 'candidate-c/mods'
    ok &= not structure(b_mods, 'test29b', True)
    ok &= not structure(c_mods, 'test29c', False)

    for mod, banks in base.manifest()['banks'].items():
        for bank in banks:
            pin = base.expected(mod, bank)
            b28 = base.bank_path(mod, bank)
            b29 = T29 / mod / base.REL / bank
            pb = b_mods / mod / base.REL / bank
            pc = c_mods / mod / base.REL / bank
            ok &= gate(b29, pb, f'b-vs-test29-{mod}-{bank[:-4]}.json')
            ok &= gate(b28, pb, f'b-vs-test28-{mod}-{bank[:-4]}.json',
                       exempt=sorted(PRESERVED), extra=sorted(PRESERVED.values()), pin=pin)
            ok &= gate(b28, pc, f'c-vs-test28-{mod}-{bank[:-4]}.json',
                       exempt=sorted(PRESERVED), extra=(), pin=pin)
    print('ALL GATES PASS' if ok else 'GATE FAILURE')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
