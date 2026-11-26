"""D4SIG4: weapon_percent (Nagi, Everyone's Mechanic 892) through the REAL patched CALL sites of unit_stats_equip_stat (the eight
calls in unit_recalc), Unicorn, normal and --abi.  Offline, read-only.

The wrapped game function is stubbed (it returns `original_rax`, a fixed base value); everything the extension does around it
runs: the weapon-category test on the slot's 600-byte entry, the unit's own rows and the allies' aura rows (the game's own
256-record battle table), the cap, the formula.  Row 27892 is read verbatim from d5lib/importers/d4-evility-overlay.json.

  * --control gate|cap|formula|row : a deliberately broken wrapper / row; the proof must then FAIL (exit 1).

<unicorn python> evility/offline_proof_d4sig4.py [--abi] [--control gate|cap|formula|row]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_evilfx2 as p                       # noqa: E402
from abi_engine_ex05c import execute, UNIT              # noqa: E402

h, unit, fixture = p.h, p.unit, p.fixture
SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig4')
NAGI = 27892
SELF20, SELF60, SELF70 = 27990, 27991, 27992             # plain rows on their own holder: +20, +60, +70
BASE = 1000


def nagi_row():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    row = mods['D4_Unique_490']['behaviors']['evilities'][str(NAGI)]
    assert row == {'family': ['weapon_percent', 'aura'], 'effects': [{'value': 10}],
                   'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 65535, 'id': NAGI}]}, row
    return row


def rows(control=None):
    r = {NAGI: dict(nagi_row()),
         SELF20: {'family': 'weapon_percent', 'effects': [{'value': 20}]},
         SELF60: {'family': 'weapon_percent', 'effects': [{'value': 60}]},
         SELF70: {'family': 'weapon_percent', 'effects': [{'value': 70}]}}
    if control == 'row':
        r[NAGI]['effects'] = [{'value': 11}]
    return r


def slot_item(u, slot, category):
    """an item in `slot` (entry size 600: id +0x138, category +0x156)"""
    struct.pack_into('<i', u, slot * 600 + 0x138, 1)
    u[slot * 600 + 0x156] = category
    return u


def holder(ids, category=1, slot=0, team=0):
    return slot_item(unit(ids, team=team), slot, category)


def cases():
    def run(name, expected, ids=(), fx=None, *, slot=0, stat=0, base=BASE, category=1, team=0, others=()):
        subject = holder(ids, category, slot, team)
        return dict(name=name, expected=expected, ids=ids, slot=slot, stat=stat, base=base,
                    fixture=fx or fixture(subject, others=others))
    prov = lambda team=0: holder((NAGI,), team=team)     # noqa: E731
    ally = lambda i=0: (prov(), (5 + i, 6), 2 + i)       # noqa: E731  (unit, cell, battle-table slot)
    out = [
        run('no row: the game result is returned as is', BASE),
        run('own +20 row, weapon category 1 -> x1.2', 1200, (SELF20,)),
        run('own +20 row, weapon category 9 (the last weapon category) -> x1.2', 1200, (SELF20,), category=9),
        run('own +20 row, category 10 (not a weapon) -> untouched', BASE, (SELF20,), category=10),
        run('own +20 row, category 0 -> untouched', BASE, (SELF20,), category=0),
        run('own +20 row, category 0x13 -> untouched', BASE, (SELF20,), category=0x13),
        run('own +20 row, a weapon in slot 1 -> x1.2 (the category decides, not the slot number)', 1200, (SELF20,), slot=1),
        run('own +20 row, slot 3 holds a non-weapon -> untouched', BASE, (SELF20,), slot=3, category=12),
        run('own +20 row, stat 7 -> x1.2 (every stat)', 1200, (SELF20,), stat=7),
        run('own +20 row, the game returns 0 (empty slot) -> 0', 0, (SELF20,), base=0),
        run('own +20 row, 33 -> 39 (39.6 truncated)', 39, (SELF20,), base=33),
        run('own +20 row, 1 -> 1', 1, (SELF20,), base=1),
        run('own +20 row, -33 -> -39 (toward zero, like D4 signed divide)', -39, (SELF20,), base=-33),
        run('own +60 and +70 rows: the sum 130 stops at the source cap 100 -> x2', 2000, (SELF60, SELF70)),
        run('own +60 and +20 rows add -> x1.8', 1800, (SELF60, SELF20)),
        # Everyone's Mechanic, the verbatim row
        run('Nagi row: an ally Nagi on the map -> weapon x1.1', 1100, fx=None, others=(ally(),)),
        run('Nagi row: the ally is 100 panels away -> x1.1', 1100, others=((prov(), (5, 105), 2),)),
        run('Nagi row: ally Nagi, the recipient wears armour (category 12) -> untouched', BASE, category=12, others=(ally(),)),
        run('Nagi row: ally Nagi, weapon in slot 1 -> x1.1', 1100, slot=1, others=(ally(),)),
        run('Nagi row: two holders count once (the kit evaluates an aura row once) -> x1.1', 1100, others=(ally(0), ally(1))),
        run('Nagi row: base 33 -> 36 (36.3 truncated)', 36, base=33, others=(ally(),)),
        run('Nagi row + an own +60 and +20 row = 90 -> x1.9', 1900, (SELF60, SELF20), others=(ally(),)),
        run('Nagi row + an own +70 and +20 row = exactly 100 -> x2', 2000, (SELF70, SELF20), others=(ally(),)),
        run('Nagi row + an own +70 and +60 row = 140 stop at the cap -> x2', 2000, (SELF70, SELF60), others=(ally(),)),
        run('Nagi row: an enemy Nagi does not raise us', BASE, others=((prov(1), (5, 6), 2),)),
        run('Nagi row: the recipient is an enemy of the only Nagi', BASE, team=1, others=((prov(0), (5, 6), 2),)),
        run('Nagi row: Nagi not deployed -> untouched', BASE, others=()),
        run('Nagi row: Nagi himself is not raised by his own row', BASE, (NAGI,), others=()),
        run('Nagi row: Nagi with an own +20 row and an ally Nagi -> x1.3', 1300, (SELF20,), others=(ally(),)),
        run('Nagi row, 51 learned ids around the row cannot hide it', 1100,
            others=((holder(tuple(range(100, 150)) + (NAGI,)), (5, 6), 2),)),
    ]
    return out


def mutated_asm(control):
    from d5lib import evility as ev
    text = Path(ev.ASM_FILE).read_text()
    old, new = {
        'gate': ("    cmp eax, 9\n    jae .eq_done                        // not a weapon category\n", "    cmp eax, 99\n    jae .eq_done\n"),
        'cap': ("    cmovg eax, ecx                      // the source cap: the summed percent stops at 100\n", "\n"),
        'formula': ("    add eax, 100\n    cdqe\n    imul rax, qword ptr [rsp + 0x20]", "    add eax, 99\n    cdqe\n    imul rax, qword ptr [rsp + 0x20]"),
    }[control]
    assert text.count(old) == 1, control
    out = SCRATCH / f'd5evil-d4sig4-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('gate', 'cap', 'formula', 'row'))
    args = ap.parse_args()
    from d5lib import evility as ev
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if args.control in ('gate', 'cap', 'formula'):
        ev.ASM_FILE = str(mutated_asm(args.control))
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    patched = ev.build_patch(original, rows(args.control))
    info = ev.section_info(patched)
    specs = [(ev.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in ev.WRAPPERS]
    _, target, sites = next(s for s in specs if s[0] == 'equip_weapon')
    assert len(sites) == 8 and target == 0x140219630
    ok = n = 0
    for case in cases():
        for site in sites:
            n += 1
            try:
                d = execute(patched, info, specs, 'equip', target, site, ids=case['ids'], abi=args.abi,
                            fixture=case['fixture'], original_rax=case['base'] & (2**64 - 1),
                            call_args=(UNIT, case['slot'], case['stat'], 0))
                got = d['output']
                got = got - (1 << 32) if got >= 1 << 31 else got
                assert got == case['expected'], (got, case['expected'])
                ok += 1
                print('PASS', case['name'], hex(site))
            except Exception as exc:                 # noqa: BLE001
                print('FAIL', case['name'], hex(site), f'{type(exc).__name__}: {exc}')
    print(f'{ok}/{n} checks passed')
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
