"""D4SIG1: the kit row this lane added that still runs here (Pirohiko 27881; Nagi 27892 moved to evility/offline_proof_d4sig4.py), verbatim from the D4 overlay, through the real
patched CALL sites (Unicorn), normal and --abi.  No new runtime code; the two alias rows (27691 Mind Killer, 27851 Jet
Black Sword) run D5's own code and have no kit row, so there is nothing of ours to execute for them.

D5_KIT=<worktree> <unicorn python> evility/offline_proof_d4sig1.py [--abi]
"""
import hashlib
import json
import os
from pathlib import Path
import sys

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_evilfx2 as p                       # noqa: E402
from abi_engine_ex05c import execute                    # noqa: E402

h, unit, fixture, agg = p.h, p.unit, p.fixture, p.agg
ROUND = 0x145574AA8                                      # the battle round counter (i16) turn_max reads
NAGI, ROAR = 27892, 27881


def rnd(n):
    return [(ROUND, n.to_bytes(2, 'little'))]


def rows():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    return {ROAR: mods['D4_Unique_460']['behaviors']['evilities'][str(ROAR)]}


def cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    base, up = [50] * 8, [60] * 8                        # unit() starts every potency word at 50; +10 on all eight
    prov = lambda team=0: unit((NAGI,), team=team)       # noqa: E731
    return [
        # Everyone's Mechanic moved to the weapon_percent family in D4SIG4: evility/offline_proof_d4sig4.py
        # Unlosing Mode: stats +50% while the round counter is at most 3
        run('roar-round-0', 'stats', 'aggregate', agg(atk=50, **{'def': 50}, int=50, res=50, hit=50, spd=50),
            ids=(ROAR,), fixture=fixture(unit((ROAR,)), regions=rnd(0))),
        run('roar-round-3', 'stats', 'aggregate', agg(atk=50, **{'def': 50}, int=50, res=50, hit=50, spd=50),
            ids=(ROAR,), fixture=fixture(unit((ROAR,)), regions=rnd(3))),
        run('roar-round-4-over', 'stats', 'aggregate', agg(), ids=(ROAR,), fixture=fixture(unit((ROAR,)), regions=rnd(4))),
        run('roar-round-1-unlearned', 'stats', 'aggregate', agg(), ids=(), fixture=fixture(unit(()), regions=rnd(1))),
        run('roar-does-not-touch-potency', 'potency', 'potency', base, ids=(ROAR,),
            fixture=fixture(unit((ROAR,)), regions=rnd(1))),
    ]


def main():
    abi = '--abi' in sys.argv
    from d5lib import evility as ev
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    patched = ev.build_patch(original, rows())
    info = ev.section_info(patched)
    specs = [(ev.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in ev.WRAPPERS]
    ok = n = 0
    for case in cases():
        _, target, sites = next(s for s in specs if s[0] == case['family'])
        for site in sites:
            n += 1
            try:
                d = execute(patched, info, specs, case['family'], target, site, ids=case.get('ids', ()), abi=abi,
                            fixture=case['fixture'], out_value=50, original_rax=0)
                got = d[case['field']]
                if isinstance(got, list):
                    got = [x - (1 << 16) if (1 << 15) <= x < (1 << 16) else x for x in got]
                assert got == case['expected'], (got, case['expected'])
                ok += 1
                print('PASS', case['name'], hex(site))
            except Exception as exc:                 # noqa: BLE001
                print('FAIL', case['name'], hex(site), f'{type(exc).__name__}: {exc}')
    print(f'{ok}/{n} checks passed')
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
