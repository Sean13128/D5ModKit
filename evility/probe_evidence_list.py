#!/usr/bin/env python3
"""Execute the game's own evility-list builder (0x140832120) offline.

EVCAP5 evidence probe.  The evility screen's rebuild (FUN_140832120, and its big
twin FUN_14084EB50) walks the whole Skill.dat table and sorts every row into one
of two fixed 1000-entry short arrays:

    screen + 0x7F9D2   learned ids        count  screen + 0x801A2
    screen + 0x801A4   not-learned ids    count  screen + 0x80974     (both 1000 slots)

and tests "learned?" with the one function the Kit redirects, 0x14015E630.

This probe runs that function for real, from the pinned exe, with:
  * a real Skill.dat row set (from the installed database, read-only),
  * a unit record at the game's own party array address (DAT_145207DB8),
  * a stub in place of 0x14015E630 that answers exactly what the Kit's wrapper
    answers after a save load (learned for one id, 0 for everything else).

It reports, per case: the learned count, whether the id is in the learned array,
and how many shorts the not-learned array wrote PAST its 1000 slots (the table
has more than 1000 rows, which is the whole point of the over-cap work).

Read-only: the game folder is only opened to read the exe.  Nothing is written
outside the emulator.
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

import capstone
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError
from unicorn import x86_const as X

EXE = os.environ.get('D5_EXE', '/Volumes/Data/Projects/D5/D5ModKit/state/games/'
                     'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
DB = os.environ.get('D5_DB', '/Volumes/Data/SteamLibrary/steamapps/common/'
                    'Disgaea 5 Complete/Data/Database/Database_0.dat')

PAGE = 0x1000
BUILD = 0x140832120          # FUN_140832120: rebuild the learned / not-learned lists
GETTER = 0x14015E630         # FUN_14015e630: id -> learned?     (redirected by the Kit)
KEYS_PTR = 0x140A04E48       # qword holding the u32 key array
KEYS_MAX = 0x140A04E38       # u16 max index
ROWS_PTR = 0x140A04E50       # qword holding the 0x60-byte row array
PARTY = 0x145207DB8          # DAT_145207db8: unit records, 0x4750 bytes each
SCREEN = 0x300000000
SCREEN_SIZE = 0x90000
ROW = 0x60
LEARNED, LEARNED_N = 0x7F9D2, 0x801A2
UNKNOWN, UNKNOWN_N = 0x801A4, 0x80974
TAB = 0x7F7EE
UNIT_INDEX = 0xB0
CAP = 1000


def table_from_db(path):
    """The real Skill.dat rows, in id order: [(id, 96 raw bytes)]."""
    from d5lib import database
    member = os.environ.get('D5_SKILL')
    if member:
        return sorted(((r['id'], bytes(r.raw))
                       for r in database.load_table('Skill.dat', open(member, 'rb').read()).rows))
    db = database.load_database(path)
    table = db.table('Skill.dat')
    rows = sorted(((r['id'], bytes(r.raw)) for r in table.rows))
    return rows


def stub_getter(uc, learned_id):
    """A 0x14015E630 that answers exactly what the Kit wrapper answers after a load:
    1 for `learned_id`, 0 for everything else.  (The wrapper calls the game first and
    only for a position >= 1000 does it ask the store, so for our purposes the answer
    is 'learned' for that one id.)"""
    code = b''.join([
        b'\x81\xfa' + struct.pack('<I', learned_id),   # cmp edx, id
        b'\x75\x06',                                    # jne +6  -> xor eax,eax
        b'\xb8\x01\x00\x00\x00',                        # mov eax, 1
        b'\xc3',                                        # ret
        b'\x31\xc0',                                    # xor eax, eax
        b'\xc3',                                        # ret
    ])
    uc.mem_write(GETTER, code)


def run(rows, learned_id, tab=0, unit_learned_slots=0, verbose=False):
    pe = pefile.PE(data=open(EXE, 'rb').read(), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    image = pe.get_memory_mapped_image()
    size = (len(image) + PAGE - 1) & -PAGE
    uc.mem_map(base, size)
    uc.mem_write(base, image)
    stack, stack_size = 0x200000000, 0x100000
    uc.mem_map(stack, stack_size)
    sp = stack + stack_size - 0x1000

    def put(address, data):
        start = address & -PAGE
        end = (address + len(data) + PAGE - 1) & -PAGE
        for page in range(start, end, PAGE):
            try:
                uc.mem_map(page, PAGE)
            except UcError:
                pass
        uc.mem_write(address, bytes(data))

    # --- the Skill table, in the game's own shape: key array, max index, row array
    ids = [i for i, _ in rows]
    keys = b''.join(struct.pack('<I', i) for i in ids)
    key_array = 0x310000000
    put(key_array, keys)
    put(KEYS_PTR, struct.pack('<Q', key_array))
    put(KEYS_MAX, struct.pack('<H', len(ids)))
    row_array = 0x320000000
    blob = bytearray(len(ids) * ROW)
    for i, (_, raw) in enumerate(rows):
        blob[i * ROW:(i + 1) * ROW] = raw
    put(row_array, bytes(blob))
    put(ROWS_PTR, struct.pack('<Q', row_array))

    # --- the unit record, at the address the builder reads it from
    unit = bytearray(0x4750)
    struct.pack_into('<Q', unit, 0x3060, 0x2F3B)
    struct.pack_into('<I', unit, 0x2E04, 14085)
    for k in range(5):
        struct.pack_into('<h', unit, 0x2EEE + 2 * k, 9999)
    struct.pack_into('<h', unit, 0x2EF8, 0)
    for k in range(10):
        struct.pack_into('<h', unit, 0x2EFC + 2 * k, 9999)
        struct.pack_into('<h', unit, 0x2F10 + 2 * k, 9999)
    struct.pack_into('<h', unit, 0x2F2C, 10)     # common slots unlocked
    struct.pack_into('<h', unit, 0x2F2E, 0)
    put(PARTY, unit)

    # --- the screen object
    screen = bytearray(SCREEN_SIZE)
    struct.pack_into('<i', screen, UNIT_INDEX, 0)
    struct.pack_into('<h', screen, TAB, tab)
    put(SCREEN, screen)
    stub_getter(uc, learned_id)

    uc.reg_write(X.UC_X86_REG_RSP, sp)
    uc.mem_write(sp, struct.pack('<Q', 0xdeadbeef))       # return address
    uc.reg_write(X.UC_X86_REG_RCX, SCREEN)
    try:
        uc.emu_start(BUILD, 0xdeadbeef, timeout=20000000)
    except UcError as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}

    out = bytearray(bytes(uc.mem_read(SCREEN, SCREEN_SIZE)))
    learned_n = struct.unpack_from('<h', out, LEARNED_N)[0]
    unknown_n = struct.unpack_from('<h', out, UNKNOWN_N)[0]
    learned = list(struct.unpack_from('<%dh' % max(0, min(learned_n, 1100)), out, LEARNED))
    unknown_overflow = max(0, unknown_n - CAP)
    # what the not-learned array wrote past its 1000 slots, and over which bytes
    written = bytes(uc.mem_read(SCREEN + UNKNOWN + CAP * 2, 400))
    return {
        'rows': len(rows),
        'learned_id': learned_id,
        'tab': tab,
        'learned_count': learned_n,
        'id_in_learned': learned_id in learned,
        'learned_head': learned[:8],
        'unknown_count': unknown_n,
        'unknown_overflow_shorts': unknown_overflow,
        'past_array_first64': written[:64].hex(),
        'count_after_run': struct.unpack_from('<h', out, UNKNOWN_N)[0],
        'screen_bytes_written_past_count': sum(1 for b in written[:200] if b not in (0,)),
    }


def main():
    rows = table_from_db(DB)
    print(json.dumps({'table_rows': len(rows), 'ids_at_1000+': [i for i, _ in rows][1000:]},
                     indent=1)[:800])
    cases = []
    # the real case: one id past position 1000, learned only in the Kit's store
    order = [i for i, _ in rows]
    target = 8228 if 8228 in order else order[-1]
    pos = order.index(target)
    cases.append(('over-cap id, learned via the store', target, pos))
    # control: an id inside the bitmap's 1000 positions that this screen's own filter admits
    import sys as _sys
    def admitted(ident, raw):
        kind, src, shop = struct.unpack_from('<I', raw, 0x30)[0], struct.unpack_from('<I', raw, 0x40)[0], struct.unpack_from('<I', raw, 0x50)[0]
        born = struct.unpack_from('<I', raw, 0x4C)[0]
        return kind == 0 and born > 0 and (src in (3, 4) or (src == 0 and shop == 0)) and shop <= 1
    inside = next(i for pos, (i, raw) in enumerate(rows) if pos < 1000 and admitted(i, raw))
    cases.append(('in-bitmap id, learned natively', inside, order.index(inside)))
    results = []
    for name, ident, position in cases:
        r = run(rows, ident)
        r['case'] = name
        r['table_position'] = position
        results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != 'past_array_first64'}, indent=1))
    json.dump(results, open(os.path.join(HERE, 'results', 'evcap5-listbuilder.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
