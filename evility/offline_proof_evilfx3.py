"""EVILFX3: condition not_moved (65) and the rows EVILFX3 writes, verbatim from the importers' data, through the real
patched CALL sites (Unicorn), normal and --abi.  No new call site.

D5_KIT=<worktree> <unicorn python> evility/offline_proof_evilfx3.py [--abi]
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_evilfx2 as p                       # noqa: E402
from abi_engine_ex05c import execute                    # noqa: E402

h, unit, fixture, agg = p.h, p.unit, p.fixture, p.agg
MOVED = lambda n: [(h.BATTLE_TABLE + 0x61c, struct.pack('<h', n))]        # noqa: E731  the subject's panels-moved counter


def rows():
    imp = KIT / 'd5lib/importers'
    d4 = json.loads((imp / 'd4-evility-overlay.json').read_text())['mods']
    dd2 = json.loads((imp / 'dd2-innate-evilities.json').read_text())['packs']
    out = {7950: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 9}], 'conditions': [{'kind': 'not_moved'}]}}
    for pack, rid in (('D4_Class_1170', 27690), ('D4_Class_2130', 27692), ('D4_Class_2190', 27693), ('D4_Class_1220', 8840)):
        out[rid] = d4[pack]['behaviors']['evilities'][str(rid)]
    for pack in ('DD2_Class_22590', 'DD2_Unique_430'):
        out[dd2[pack]['id']] = dd2[pack]['behavior']
    return out


def cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    foe = lambda: unit((), team=1)               # noqa: E731
    return [
        run('not-moved-counter-0', 'stats', 'aggregate', agg(atk=9), ids=(7950,), fixture=fixture(unit((7950,)))),
        run('not-moved-counter-3', 'stats', 'aggregate', agg(), ids=(7950,), fixture=fixture(unit((7950,)), regions=MOVED(3))),
        run('not-moved-off-the-map', 'stats', 'aggregate', agg(), ids=(7950,), fixture=fixture(unit((7950,)), on_map=False)),
        run('27690-speedy-move-4-panels', 'stats', 'aggregate', agg(spd=20), ids=(27690,),
            fixture=fixture(unit((27690,)), regions=MOVED(4))),
        run('27690-speedy-move-not-moved', 'stats', 'aggregate', agg(), ids=(27690,), fixture=fixture(unit((27690,)))),
        run('27692-accel-element-3-panels-fire', 'dealt', 'output', 30, ids=(27692,),
            fixture=fixture(unit((27692,)), other=unit(), action_skill=392, action_element=1, regions=MOVED(3))),
        run('27692-accel-element-3-panels-no-element', 'dealt', 'output', 0, ids=(27692,),
            fixture=fixture(unit((27692,)), other=unit(), action_skill=392, action_element=0, regions=MOVED(3))),
        run('27692-accel-element-not-moved', 'dealt', 'output', 0, ids=(27692,),
            fixture=fixture(unit((27692,)), other=unit(), action_skill=392, action_element=1)),
        run('27693-invincible-ruler-not-moved', 'dealt', 'output', 50, ids=(27693,),
            fixture=fixture(unit((27693,)), other=unit())),
        run('27693-invincible-ruler-moved-1', 'dealt', 'output', 0, ids=(27693,),
            fixture=fixture(unit((27693,)), other=unit(), regions=MOVED(1))),
        run('27693-invincible-ruler-unlearned', 'dealt', 'output', 0, ids=(), fixture=fixture(unit(()), other=unit())),
        run('26302-stone-statue-not-moved', 'stats', 'aggregate', agg(**{'def': 100}), ids=(26302,), fixture=fixture(unit((26302,)))),
        run('26302-stone-statue-moved', 'stats', 'aggregate', agg(), ids=(26302,), fixture=fixture(unit((26302,)), regions=MOVED(2))),
        # Demon Experiments: allies within 3 panels deal +10, enemies within 3 take +10 (50 in -> 55)
        run('26303-ally-within-3-deals-more', 'dealt', 'output', 10, ids=(),
            fixture=fixture(unit(()), other=foe(), others=((unit((26303,)), (5, 8), 2),))),
        run('26303-ally-4-panels-away', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=foe(), others=((unit((26303,)), (5, 9), 2),))),
        run('26303-mao-himself-is-not-his-own-ally', 'dealt', 'output', 0, ids=(26303,),
            fixture=fixture(unit((26303,)), other=foe())),
        run('26303-enemy-within-3-takes-more', 'taken', 'output', 55, ids=(),
            fixture=fixture(unit((), team=1), subject_is_other=True, other=unit(), others=((unit((26303,)), (5, 8), 2),))),
        run('26303-enemy-4-panels-away', 'taken', 'output', 50, ids=(),
            fixture=fixture(unit((), team=1), subject_is_other=True, other=unit(), others=((unit((26303,)), (5, 9), 2),))),
        run('26303-an-ally-does-not-take-more', 'taken', 'output', 50, ids=(),
            fixture=fixture(unit(()), subject_is_other=True, other=foe(), others=((unit((26303,)), (5, 8), 2),))),
        # Friends on a class rank row: the row moved packs, the rule did not
        run('8840-friends-no-squad-gives-nothing', 'stats', 'aggregate', agg(), ids=(8840,), fixture=fixture(unit((8840,)))),
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
