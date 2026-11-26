#!/usr/bin/env python3
"""EVCAP5 end-to-end replay: the game's own evility list builders against the real
Kit section, on the unit record from Sean's Save_003.

Nothing is stubbed about the learned test: the pinned exe is patched by the Kit's own
`d5lib.learned.build_patch` (the .d5lc section plus the 145 CALL redirections), the
store is filled through the section's published `lc_fn_put` (the same entry point the
runtime's load path uses), and the two game functions then run for real:

  0x140832120  the evility screen's learned / not-learned rebuild
  0x1407CDB30  the learned-and-not-equipped pick list (16-byte entries at screen+0xFF48)

Fixture: the unit record exactly as Save_003 holds it (serial 0x2F3B, class 14085,
empty learned bitmap, no equipped common evilities) and the evility id that the save's
own companion carries (8228), which sits at table position >= 1000.
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get('D5_KIT', os.path.dirname(HERE))
sys.path.insert(0, KIT)
if os.path.isdir(os.path.join(KIT, 'tests')):
    sys.path.insert(0, os.path.join(KIT, 'tests'))
try:
    import unicorn_darwin_shim
    unicorn_darwin_shim.install()
except Exception:
    pass

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError, UC_HOOK_MEM_UNMAPPED, UC_HOOK_CODE
from unicorn import x86_const as X

from d5lib import database, learned

EXE = os.environ.get('D5_EXE', '/Volumes/Data/Projects/D5/D5ModKit/state/games/'
                     'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
DB = os.environ.get('D5_DB', '/Volumes/Data/SteamLibrary/steamapps/common/'
                    'Disgaea 5 Complete/Data/Database/Database_0.dat')
SAVE_DIR = os.environ.get('D5_SAVE', '/Volumes/Data/ai-tmp/evcap5/saves')

PAGE = 0x1000
REBUILD = 0x140832120
PICK = 0x1407CDB30
KEYS_PTR, KEYS_MAX, ROWS_PTR = 0x140A04E48, 0x140A04E38, 0x140A04E50
PARTY = 0x145207DB8
SCREEN, SCREEN_SIZE = 0x300000000, 0x90000
SCRATCH, VTABLE = 0x340000000, 0x350000000
ARENA = 0x360000000           # scratch for anything the UI helpers touch
TEB = 0x380000000             # a stand-in TEB so the game's __chkstk / cookie reads work
ROW = 0x60
SERIAL, EVILITY = 0x2F3B, 8228
PICK_CATEGORY = int(os.environ.get('D5_PICK_TAB', '1'))


def rows_from_db(path):
    member = os.environ.get('D5_SKILL')
    if member:
        table = database.load_table('Skill.dat', open(member, 'rb').read())
    else:
        table = database.load_database(path).table('Skill.dat')
    return sorted(((r['id'], bytes(r.raw)) for r in table.rows))


def patched_exe(man):
    return learned.build_patch(open(EXE, 'rb').read(), man)


def build(rows):
    ids = [i for i, _ in rows]
    man = learned.manifest(ids)
    exe = patched_exe(man)
    info = learned.section_info(exe)
    sym = learned.data_symbols(info)
    return ids, man, exe, info, sym


def machine(exe):
    pe = pefile.PE(data=exe, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    image = pe.get_memory_mapped_image()
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(base, (len(image) + PAGE - 1) & -PAGE)
    uc.mem_write(base, image)
    for address, size in ((0x200000000, 0x200000), (SCRATCH, 0x10000), (VTABLE, 0x1000),
                          (SCREEN, SCREEN_SIZE), (0x310000000, 0x100000),
                          (0x320000000, 0x100000), (ARENA, 0x400000), (TEB, 0x2000)):
        uc.mem_map(address, size)
    return uc, base


def setup(uc, rows, sym, unit_index=0, tab=0, sorted_flag=0):
    ids = [i for i, _ in rows]
    uc.mem_write(0x310000000, b''.join(struct.pack('<I', i) for i in ids))
    uc.mem_write(KEYS_PTR, struct.pack('<Q', 0x310000000))
    uc.mem_write(KEYS_MAX, struct.pack('<H', len(ids)))
    blob = bytearray(len(ids) * ROW)
    for i, (_, raw) in enumerate(rows):
        blob[i * ROW:(i + 1) * ROW] = raw
    uc.mem_write(0x320000000, bytes(blob))
    uc.mem_write(ROWS_PTR, struct.pack('<Q', 0x320000000))
    # the section's own guard/search pointers -> the fixtures
    globals_box = 0x370000000
    try:
        uc.mem_map(globals_box, PAGE)
    except UcError:
        pass
    uc.mem_write(globals_box, struct.pack('<Q', 0x310000000))
    uc.mem_write(sym['pkey'], struct.pack('<Q', globals_box))
    maxi_box = 0x370001000
    try:
        uc.mem_map(maxi_box, PAGE)
    except UcError:
        pass
    uc.mem_write(maxi_box, struct.pack('<H', len(ids)))
    uc.mem_write(sym['pmax'], struct.pack('<Q', maxi_box))
    # the unit record, as Save_003 holds it
    unit = bytearray(0x4750)
    struct.pack_into('<Q', unit, 0x3060, SERIAL)
    struct.pack_into('<I', unit, 0x2E04, 14085)
    struct.pack_into('<H', unit, 0x2DFC, 7999)
    for k in range(5):
        struct.pack_into('<h', unit, 0x2EEE + 2 * k, 8392 if k == 0 else 9999)
    struct.pack_into('<h', unit, 0x2EF8, 1)
    struct.pack_into('<h', unit, 0x2EFA, 1)
    for k in range(10):
        struct.pack_into('<h', unit, 0x2EFC + 2 * k, 9999)
        struct.pack_into('<h', unit, 0x2F10 + 2 * k, 9999)
    struct.pack_into('<h', unit, 0x2F2C, 10)
    struct.pack_into('<h', unit, 0x2F2E, 1)
    uc.mem_write(PARTY, bytes(unit))
    # screen object for the pick list: a stub vtable with two `ret`s
    uc.mem_write(SCRATCH, b'\xc3')
    uc.mem_write(SCRATCH + 0x100, b'\xc3')
    vtable = bytearray(0x200)
    struct.pack_into('<Q', vtable, 0xA8, SCRATCH)
    struct.pack_into('<Q', vtable, 0xB8, SCRATCH + 0x100)
    uc.mem_write(VTABLE, bytes(vtable))
    screen = bytearray(SCREEN_SIZE)
    struct.pack_into('<Q', screen, 0x1B840, PARTY)
    struct.pack_into('<i', screen, 0x1B850, tab)
    screen[0x1B858] = sorted_flag
    struct.pack_into('<i', screen, 0xB0, unit_index)
    struct.pack_into('<h', screen, 0x7F7EE, tab)
    struct.pack_into('<Q', screen, 0xFE70, VTABLE)
    uc.mem_write(SCREEN, bytes(screen))


def call(uc, address, *args, timeout=40000000):
    uc.mem_write(TEB + 0x10, struct.pack('<Q', 0))   # TEB.StackLimit/DeallocationStack slot
    uc.reg_write(X.UC_X86_REG_GS_BASE, TEB)
    sp = 0x200000000 + 0x200000 - 0x1000
    uc.reg_write(X.UC_X86_REG_RSP, sp)
    uc.mem_write(sp, struct.pack('<Q', 0xdeadbeef))
    for name, value in zip(('rcx', 'rdx', 'r8', 'r9'), list(args) + [0] * 4):
        uc.reg_write(getattr(X, 'UC_X86_REG_' + name.upper()), value)
    uc.emu_start(address, 0xdeadbeef, timeout=timeout)


def main():
    rows = rows_from_db(DB)
    ids = [i for i, _ in rows]
    position = ids.index(EVILITY)
    ids_f, man, exe, info, sym = build(rows)
    uc, base = machine(exe)
    setup(uc, rows, sym)
    faults = []
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, lambda uc_, a, s, v, u, value: faults.append(hex(uc_.reg_read(X.UC_X86_REG_RIP))))
    # the store entry the load path would put there
    call(uc, struct.unpack('<Q', uc.mem_read(sym['fn_put'], 8))[0], SERIAL, EVILITY)
    results = {'table_rows': len(ids), 'evility': EVILITY, 'table_position': position,
               'serial': hex(SERIAL), 'section': hex(info['code']),
               'put_called': True}

    # 1. the evility screen's learned / not-learned rebuild
    try:
        call(uc, REBUILD, SCREEN)
        out = bytes(uc.mem_read(SCREEN, SCREEN_SIZE))
        n = struct.unpack_from('<h', out, 0x801A2)[0]
        learned_ids = list(struct.unpack_from('<%dh' % max(0, n), out, 0x7F9D2)) if n > 0 else []
        results['rebuild'] = {'learned_count': n, 'ids': learned_ids[:12],
                              'evility_in_learned': EVILITY in learned_ids,
                              'not_learned_count': struct.unpack_from('<h', out, 0x80974)[0]}
    except UcError as exc:
        results['rebuild'] = {'error': f'{type(exc).__name__}: {exc}', 'faults': faults}

    # 2. the learned-and-not-equipped pick list, in every screen state a player can put it in
    picks = {}
    e9 = PICK_CATEGORY
    for label, tab, sorted_flag in (('default', 0, 0), ('sorted-by-cost', 0, 1),
                                    ('category tab 1', 1, 0), ('category tab 5', 5, 0),
                                    (f'category tab {e9} (its own)', e9, 0),
                                    (f'sorted + tab {e9}', e9, 1)):
        setup(uc, rows, sym, tab=tab, sorted_flag=sorted_flag)
        try:
            call(uc, PICK, SCREEN)
            out = bytes(uc.mem_read(SCREEN, SCREEN_SIZE))
            n = struct.unpack_from('<i', out, 0xFE7C)[0]
            entries = [struct.unpack_from('<QIIi', out, 0xFF48 + i * 16)[1]
                       for i in range(max(0, min(n, 256)))]
            picks[label] = {'count': n, 'head': entries[:8], 'evility_in_list': EVILITY in entries}
        except UcError as exc:
            picks[label] = {'error': f'{type(exc).__name__}: {exc}'}
    results['pick'] = picks
    print(json.dumps(results, indent=1))
    json.dump(results, open(os.path.join(HERE, 'results', 'evcap5-replay.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
