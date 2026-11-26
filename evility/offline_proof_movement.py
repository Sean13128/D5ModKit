"""Movement-cost scale proof through existing patched game CALLs; no native gameplay claim."""
import argparse
import hashlib
import struct
from offline_proof_ex05d import (ORIGINAL, ORIGINAL_SHA, BATTLE_TABLE, UNIT, fixture, unit)
from abi_engine_ex05c import execute
from d5lib import evility as ev

p = argparse.ArgumentParser()
p.add_argument('--abi', action='store_true')
a = p.parse_args()
original = ORIGINAL.read_bytes()
assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
rows = {7700: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 5, 'per': 'movement_cost'}]}}
patched = ev.build_patch(original, rows)
info = ev.section_info(patched)
specs = [('stats', target, sites) for tag, target, sites in ev.WRAPPERS if tag == 0xE70002]
assert len(specs) == 1
_, target, sites = specs[0]
for value, on_map, expected in [(0, True, 0), (3, True, 15), (-1, True, 0), (3, False, 0)]:
    base = fixture(unit((7700,)), on_map=on_map)
    def setup(write, base=base, value=value, on_map=on_map):
        base(write)
        if on_map:
            write(BATTLE_TABLE + 0x61c, struct.pack('<h', value))
    for site in sites:
        detail = execute(patched, info, specs, 'stats', target, site, ids=(7700,), abi=a.abi, fixture=setup)
        assert detail['aggregate'][2] == expected, (value, on_map, detail['aggregate'])
        print(f'PASS movement cost={value} on_map={on_map} site={site:#x} abi={a.abi}')
print(f'{4 * len(sites)} checks passed')
