#!/usr/bin/env python3
"""DRPGEVIL1b: what the game does with an evility row at Skill.dat position >= 1,000 when it is a character's
INNATE evility (char row link), executed with the game's own functions in Unicorn.

Table: the clean D5 Skill.dat (796 rows) + 214 synthetic rows so that id 28003 sits at position 1,005 of 1,010.
Unit: innate slot 0 = 28003, empty learned bitmap, nothing equipped.

  0x14008D0F0  damage_skill_dat            id -> row pointer (the name/description lookup every screen uses)
  0x14015E630  the learned getter           (the bitmap test: must answer "not learned" past 999, natively)
  0x14015E6D0  the learned setter           (must refuse, -1)
  0x140218C90  unit_stats_evil_rebuild_list builds the active list +0x2F30 the evility runtime walks
  0x140832120  the evility screen's learned / not-learned arrays (two fixed 1,000-entry short arrays)

Run with the kit python (Unicorn shim): evility/probe_drpgevil1b_capacity.py
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import probe_replay_equip as p                      # noqa: E402  (engine: machine/setup/call)
from unicorn import UcError, UC_HOOK_MEM_UNMAPPED    # noqa: E402
from unicorn import x86_const as X                    # noqa: E402
from d5lib import database, gamefs                    # noqa: E402

D5 = '/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)'
LOOKUP, GETTER, SETTER, REBUILD_LIST, SCREEN_LISTS = 0x14008D0F0, 0x14015E630, 0x14015E6D0, 0x140218C90, 0x140832120
EV, POSITION, TOTAL = 28003, 1005, 1010


def rows():
    fs = gamefs.GameFS(D5)
    t = database.load_table('Skill.dat', fs.read('Database/Database_0.dat/Skill.dat'))
    out = sorted((r['id'], bytes(r.raw)) for r in t.rows)
    tmpl = bytearray(next(raw for i, raw in out if i == 1235))
    struct.pack_into('<I', tmpl, 0x30, 2)           # kind 2 (unique), like every DRPG own row
    struct.pack_into('<I', tmpl, 0x50, 0)           # shop_rank 0
    filler = POSITION - len(out)                    # rows between vanilla and ours
    ids = [20000 + k for k in range(filler)] + [EV] + [EV + 1 + k for k in range(TOTAL - POSITION - 1)]
    for i in ids:
        raw = bytearray(tmpl)
        struct.pack_into('<I', raw, 0, i)
        out.append((i, bytes(raw)))
    out.sort()
    return out, t


def ret(uc):
    return uc.reg_read(X.UC_X86_REG_RAX)


def main():
    table, t = rows()
    ids = [i for i, _ in table]
    assert ids.index(EV) == POSITION and len(ids) == TOTAL
    _, man, exe, info, sym = p.build(table)
    plain = open(p.EXE, 'rb').read()               # the UNPATCHED exe: what the game does natively
    res = {'table_rows': TOTAL, 'evility': EV, 'position': POSITION}
    for label, image in (('native', plain), ('kit .d5lc', exe)):
        uc, _ = p.machine(image)
        faults = []
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, lambda u, a, s, v, w, d: faults.append(hex(u.reg_read(X.UC_X86_REG_RIP))))
        p.setup(uc, table, sym if image is exe else {'pkey': p.ARENA, 'pmax': p.ARENA + 8})   # no .d5lc natively
        unit = bytearray(uc.mem_read(p.PARTY, 0x4750))
        struct.pack_into('<h', unit, 0x2EEE, EV)                 # innate slot 0, a short
        struct.pack_into('<h', unit, 0x2F2C, 0)
        struct.pack_into('<h', unit, 0x2F2E, 0)
        struct.pack_into('<I', unit, 0x4348, 0xFFFF)             # no stat record: skip the squad-partner part
        uc.mem_write(p.PARTY, bytes(unit))
        r = {}
        try:
            p.call(uc, LOOKUP, 0, EV)
            row = ret(uc)
            r['row_lookup'] = {'found': row == 0x320000000 + POSITION * p.ROW,
                               'row_id': struct.unpack('<I', uc.mem_read(row, 4))[0] if row else None}
            p.call(uc, GETTER, p.PARTY, EV)
            r['getter_learned'] = ret(uc) & 0xFF
            p.call(uc, SETTER, p.PARTY, EV, 1)
            r['setter_result'] = struct.unpack('<i', struct.pack('<I', ret(uc) & 0xFFFFFFFF))[0]
            r['bitmap_untouched'] = bytes(uc.mem_read(p.PARTY + 0x2E70, 125)) == bytes(125)
            p.call(uc, REBUILD_LIST, p.PARTY)
            n = struct.unpack('<i', uc.mem_read(p.PARTY + 0x3030, 4))[0]
            r['active_list'] = list(struct.unpack('<%di' % n, uc.mem_read(p.PARTY + 0x2F30, 4 * n)))
            p.call(uc, SCREEN_LISTS, p.SCREEN)
            out = bytes(uc.mem_read(p.SCREEN, p.SCREEN_SIZE))
            r['evility_screen'] = {'learned_count': struct.unpack_from('<h', out, 0x801A2)[0],
                                   'not_learned_count': struct.unpack_from('<h', out, 0x80974)[0],
                                   'array_capacity': 1000}
        except UcError as exc:
            r['error'] = f'{type(exc).__name__}: {exc}'
        r['faults'] = faults
        res[label] = r
    shop = sum(1 for row in t.rows if row['shop_rank'] >= 1)
    res['vanilla_rows_with_shop_rank'] = shop
    res['pass'] = all(res[k].get('row_lookup', {}).get('found') and res[k].get('active_list') == [EV]
                      and not res[k]['faults'] and 'error' not in res[k] for k in ('native', 'kit .d5lc')) \
        and res['native']['getter_learned'] == 0 and res['native']['setter_result'] == -1
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(HERE, 'results', 'drpgevil1b-capacity.json'), 'w'), indent=1)
    return 0 if res['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
