"""DRPGEVIL1c: instructions per wrapper call as the table grows (Unicorn, real patched call sites).

A battle with 20 deployed units; the subject has 4 learned ids; N aura rows in the table whose providers are NOT
on the map (the common case: most characters' auras are not in this battle) plus one that is.
    <kit python> evility/measure_scan_cost.py [N_AURA ...]
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_ex05e as h                         # noqa: E402
import abi_engine_ex05c as eng                          # noqa: E402


def battle(n_units, provider):
    table = bytearray(256 * h.STRIDE)
    table[0:h.STRIDE] = h.record(eng.UNIT, x=h.cell(5), z=h.cell(5), slot=0)
    for i in range(1, n_units):
        ptr = h.EXTRA[0] if i == 1 else eng.OTHER
        table[i * h.STRIDE:(i + 1) * h.STRIDE] = h.record(ptr, x=h.cell(5 + i % 6), z=h.cell(6 + i // 6), slot=i)
    return [(h.BATTLE_TABLE, bytes(table)), (h.EXTRA[0], bytes(provider))]


def measure(n_aura, family):
    from d5lib import evility as ev
    fam = [family, 'aura']
    fx = [{'stat': 'atk', 'value': 1}] if family == 'stats' else [{'value': 1}]
    rows = {40000 + i: {'family': fam, 'effects': fx,
                        'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 30, 'id': 40000 + i}]}
            for i in range(n_aura)}
    rows.update({30000 + i: {'family': family, 'effects': fx} for i in range(4)})
    original = h.ORIGINAL.read_bytes()
    patched = ev.build_patch(original, rows)
    info = ev.section_info(patched)
    specs = [(name, target, sites) for name, (_, target, sites) in zip(h.NAMES, ev.WRAPPERS)]
    _, target, sites = next(s for s in specs if s[0] == family)
    ids = tuple(30000 + i for i in range(4))
    provider = h.unit((40000 + n_aura // 2,)) if n_aura else h.unit(())
    fixture = h.fixture(h.unit(ids), other=h.unit(), regions=battle(20, provider))
    d = eng.execute(patched, info, specs, family, target, sites[0], ids=ids, abi=True, fixture=fixture, out_value=50)
    want = 4 + (1 if n_aura else 0)
    got = d['aggregate'][2] if family == 'stats' else d['output']
    return dict(family=family, aura_rows=n_aura, rows=len(rows), instructions=d['instructions'], value=got, expected=want,
                section_bytes=info['size'])


if __name__ == '__main__':
    out = []
    for n in [int(a) for a in sys.argv[1:]] or [0, 8, 64, 256, 1020]:
        for fam in ('stats', 'dealt'):
            try:
                out.append(measure(n, fam))
            except Exception as exc:        # noqa: BLE001
                out.append(dict(family=fam, aura_rows=n, error=f'{type(exc).__name__}: {str(exc)[:160]}'))
            print(json.dumps(out[-1]))
