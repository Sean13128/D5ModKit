"""EVILGAP1b: the two EVILGAP1 kit-family rows, taken verbatim from d4-evility-additions.json, run through the
real patched CALL sites (Unicorn), normal and --abi, with the same harness as EX-05c / EX-06.

  8894 Favorite Mark       dealt +15, attack_skill + attack_phys  (physical skill fires; magic skill, normal attack,
                           and an unlearned unit do not)
  8882 Human Modification  conversion ATK<-DEF 30%, INT<-RES 30%  (both from BASE stats, no feedback)

D5_KIT=<worktree> <unicorn python> evility/offline_proof_evilgap1.py [--abi] [--json OUT]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
from abi_engine_ex05c import ACTION, execute          # noqa: E402
import offline_proof_ex05c as c5                        # noqa: E402
import offline_proof_ex06 as c6                         # noqa: E402

ROW = 0x4000B0000                                       # a synthetic Skill.dat row; +1014 = effect type
ADD = json.loads((KIT / 'd5lib/importers/d4-evility-additions.json').read_text())['mods']


def skill_fixture(skill, etype, ids=(8894,)):
    base = c6.dealt(skill=skill, ids=ids)

    def setup(write):
        base(write)
        if etype is not None:
            row = bytearray(1100)
            row[1014] = etype
            write(ROW, bytes(row))
            write(ACTION + 0x27678, struct.pack('<Q', ROW))
    return setup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    from d5lib import evility as ev
    original = c6.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == c6.ORIGINAL_SHA
    rows = {}
    rows.update(ADD['D4_Unique_490']['behaviors'])
    rows.update(ADD['D4_Unique_460']['behaviors'])
    patched = ev.build_patch(original, rows, {})
    info = ev.section_info(patched)
    specs = [(n, t, s) for n, (_, t, s) in ((n, ev.wrapper(n)) for n in ('dealt', 'conversion'))]
    base = [100, 200, 300, 301, 500, 600, 701, 803]
    init = [1000] * 8
    def conv(learned):
        exp = init.copy()
        if learned:
            exp[2] = 1000 + 301 * 30 // 100        # ATK += 30% of base DEF (301)
            exp[4] = 1000 + 600 * 30 // 100        # INT += 30% of base RES (600)
        return dict(family='conversion', ids=learned, field='final_stats', expected=exp,
                    fixture=c5.fixture(own=c5.unit(learned, base=base, maxima=init)))
    checks = [
        dict(name='favorite-mark-physical-skill', family='dealt', ids=(8894,), expected=15,
             fixture=skill_fixture(500, 2)),
        dict(name='favorite-mark-magic-skill', family='dealt', ids=(8894,), expected=0,
             fixture=skill_fixture(500, 3)),
        dict(name='favorite-mark-normal-attack', family='dealt', ids=(8894,), expected=0,
             fixture=skill_fixture(0, None)),
        dict(name='favorite-mark-unlearned', family='dealt', ids=(), expected=0,
             fixture=skill_fixture(500, 2, ())),
        dict(name='human-modification-learned', **conv((8882,))),
        dict(name='human-modification-unlearned', **conv(())),
    ]
    results = []
    for case in checks:
        _, target, sites = next(s for s in specs if s[0] == case['family'])
        for site in sites:
            try:
                d = execute(patched, info, specs, case['family'], target, site, ids=case['ids'], abi=a.abi,
                            fixture=case['fixture'], out_value=50)
                got = d[case.get('field', 'output')]
                assert got == case['expected'], (got, case['expected'])
                results.append(dict(name=case['name'], site=hex(site), ok=True))
            except Exception as exc:                 # noqa: BLE001
                results.append(dict(name=case['name'], site=hex(site), ok=False, error=f'{type(exc).__name__}: {exc}'))
            r = results[-1]
            print(('PASS ' if r['ok'] else 'FAIL ') + r['name'] + ' ' + r['site'] + ('' if r['ok'] else ' ' + r['error']))
    ok = all(r['ok'] for r in results)
    if a.json:
        a.json.write_text(json.dumps(dict(mode='abi' if a.abi else 'behavior', passed=ok, checks=results), indent=1) + '\n')
    print(f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
