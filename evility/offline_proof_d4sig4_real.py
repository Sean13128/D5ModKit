"""D4SIG4, the real-code half: the game's own unit_recalc instructions around the first of the eight unit_stats_equip_stat calls
(0x14021D530..0x14021D541), with the REAL unit_stats_equip_stat body, the real Skill.dat of the installed game and the game's own
256-record battle table, under Unicorn, on the installed exe (control) and on the kit build (wrap_equip).  Offline, read-only.

For every case the kit result must equal trunc(installed result x (100 + percent) / 100) for a weapon-category slot and equal the
installed result otherwise; one absolute number is pinned (potency 50, item stat 1000 -> 500) so the control itself is checked.
It also prints how the kit's order (scale after D5's own later stages) compares with adding the percent to D5's own weapon-percent
evility 6035 inside the function, which is the rounding caveat written in the Nagi line.

<unicorn python> evility/offline_proof_d4sig4_real.py [--abi] [--control gate|cap|formula]
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
sys.path[:0] = [str(KIT), str(KIT / 'tools'), str(KIT / 'evility')]
from d5lib import database, evility as ev              # noqa: E402
import stat_oracle as so                                # noqa: E402
import offline_proof_ex05e as h                         # noqa: E402

GAME = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete')
SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig4')
NAGI, OWN20, OWN70 = 27892, 27990, 27992
WEAPON_PCT = 6035                                      # 0x1793: D5's own weapon-stat percent evility (Skill row +0x38)
START, END = 0x14021D530, 0x14021D541                  # lea r9 .. the instruction after the first call (stat 0 = HP)
CALL = 0x14021D53C
POTENCY, ITEM = 50, 1000


def emu(exe):
    db = database.load_database(str(GAME / 'Data/Database/Database_0.dat'))
    return so.Emu(exe_path=exe, db=db)


def skill_value(db, evid):
    b = db.raw['Skill.dat']
    for i in range(struct.unpack('<H', b[:2])[0]):
        rec = b[4 + 96 * i:4 + 96 * (i + 1)]
        if struct.unpack_from('<I', rec, 0)[0] == evid:
            return struct.unpack_from('<i', rec, 0x38)[0]
    raise SystemExit(f'Skill.dat has no row {evid}')


def make_unit(ids, category, slot, team=0, provider=False):
    u = bytearray(0x4800)
    ids = sorted(ids)
    struct.pack_into('<i', u, 0x3030, len(ids))
    for i, v in enumerate(ids):
        struct.pack_into('<I', u, 0x2F30 + 4 * i, v)
    struct.pack_into('<8H', u, 0x3068, *([POTENCY] * 8))
    # the subject has no stat record (the game skips its x1.5 stage); a provider needs one, evil_near ignores units without
    struct.pack_into('<I', u, 0x4348, 0 if provider else 0xFFFFFFFF)
    u[0x2e32] = team
    u[0x2e25] = 1                                          # type code and character id, as the synthetic fixtures set them
    struct.pack_into('<i', u, 0x2e04, 10)
    struct.pack_into('<i', u, slot * 600 + 0x138, 1)
    u[slot * 600 + 0x156] = category
    struct.pack_into('<8q', u, slot * 600 + 0xB8, *([ITEM] * 8))
    return u


def run(e, ids, category, slot=0, stat_slot_args=None, allies=(), abi=False, section=None):
    """returns rax after the call at 0x14021D53C (the slot's contribution to stat 0)"""
    X, mu = e.X, e.mu
    e.brk = e.heap_mark
    unit = e.alloc(make_unit(ids, category, slot))
    table = bytearray(256 * h.STRIDE)
    table[0:h.STRIDE] = h.record(unit, x=h.cell(5), z=h.cell(5), slot=0)
    for i, (provider_ids, team) in enumerate(allies):
        ptr = e.alloc(make_unit(provider_ids, 1, 0, team, provider=True))
        table[(i + 2) * h.STRIDE:(i + 3) * h.STRIDE] = h.record(ptr, x=h.cell(6 + i), z=h.cell(5), slot=i + 2)
    mu.mem_write(h.BATTLE_TABLE, bytes(table))
    tiers = e.alloc(bytes(64))                             # the tier-bonus ints (slot * 4): all zero
    rsp = so.STACK + 0x100000 - 0x200
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    mu.reg_write(X.UC_X86_REG_RBP, tiers + 0x10)           # [rbp - 0x10] is the tier array the game passes in r9
    mu.reg_write(X.UC_X86_REG_RBX, unit)
    mu.reg_write(X.UC_X86_REG_RSI, slot)
    for r, v in {X.UC_X86_REG_RDI: 0x3333, X.UC_X86_REG_R12: 0x4444, X.UC_X86_REG_R13: 0x5555, X.UC_X86_REG_R14: 0x6666,
                 X.UC_X86_REG_R15: 0x7777}.items():
        mu.reg_write(r, v)
    bad, hooks = [], []
    if abi and section:
        import capstone
        from unicorn import UC_HOOK_CODE
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        lo, hi = section
        nonvol = (X.UC_X86_REG_RBX, X.UC_X86_REG_RBP, X.UC_X86_REG_RSI, X.UC_X86_REG_RDI, X.UC_X86_REG_R12,
                  X.UC_X86_REG_R13, X.UC_X86_REG_R14, X.UC_X86_REG_R15, X.UC_X86_REG_RSP)
        saved = {}

        def code(uc, addr, size, _):
            if addr == CALL:
                if uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append('site entered with a misaligned stack')
                saved.update({r: uc.reg_read(r) for r in nonvol})
            elif addr == CALL + 5 and saved:
                bad.extend(f'register {r} changed across the redirected call' for r, v in saved.items()
                           if uc.reg_read(r) != v)
            if lo <= addr < hi:
                ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
                if ins.mnemonic == 'call' and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append(f'misaligned call at {addr:#x}')
        hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.emu_start(START, END, count=3_000_000)
    finally:
        for k in hooks:
            mu.hook_del(k)
    assert not bad, bad
    v = mu.reg_read(X.UC_X86_REG_RAX)
    return v - (1 << 64) if v >= 1 << 63 else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('gate', 'cap', 'formula'))
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if args.control:
        from offline_proof_d4sig4 import mutated_asm
        ev.ASM_FILE = str(mutated_asm(args.control))
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    rows = {NAGI: mods['D4_Unique_490']['behaviors']['evilities'][str(NAGI)],
            OWN20: {'family': 'weapon_percent', 'effects': [{'value': 20}]},
            OWN70: {'family': 'weapon_percent', 'effects': [{'value': 70}]}}
    patched = ev.build_patch(original, rows)
    info = ev.section_info(patched)
    tmp = Path(tempfile.mkdtemp(prefix='d4sig4-', dir=SCRATCH))
    (tmp / 'kit.exe').write_bytes(patched)
    kit, installed = emu(tmp / 'kit.exe'), emu(h.ORIGINAL)       # the control is the pinned original exe, not the live one
    section = (info['code'], info['base'] + len(info['data']))
    v6035 = skill_value(kit.db, WEAPON_PCT)
    # (name, ids, category, slot, allies [(ids, team)], percent the kit must add (None = nothing))
    cases = [
        ('no rows: kit == installed', (), 1, 0, (), None),
        ('own +20, weapon category 1', (OWN20,), 1, 0, (), 20),
        ('own +20, weapon category 9', (OWN20,), 9, 0, (), 20),
        ('own +20, category 10 (not a weapon): untouched', (OWN20,), 10, 0, (), None),
        ('own +20, a weapon in slot 1', (OWN20,), 1, 1, (), 20),
        ('own +70 and +20 stay under the cap: +90', (OWN70, OWN20), 1, 0, (), 90),
        ('Nagi: an ally holder on the map', (), 1, 0, (((NAGI,), 0),), 10),
        ('Nagi: the holder himself is not raised', (NAGI,), 1, 0, (), None),
        ('Nagi: an enemy holder does not raise us', (), 1, 0, (((NAGI,), 1),), None),
        ('Nagi: ally holder, the recipient wears armour (category 12)', (), 12, 0, (((NAGI,), 0),), None),
        ('Nagi + own +70 + own +20 = 100 (the cap)', (OWN70, OWN20), 1, 0, (((NAGI,), 0),), 100),
        (f'D5 weapon-percent evility {WEAPON_PCT} (+{v6035}) with Nagi: scaled after it', (WEAPON_PCT,), 1, 0, (((NAGI,), 0),), 10),
    ]
    pin = run(installed, (), 1)
    assert pin == POTENCY * ITEM // 100, f'the installed game gives {pin}, expected {POTENCY * ITEM // 100}'
    ok = n = 0
    for name, ids, cat, slot, allies, pct in cases:
        base = run(installed, ids, cat, slot, allies=allies)
        got = run(kit, ids, cat, slot, allies=allies, abi=args.abi, section=section)
        want = base if pct is None else int((100 + min(pct, 100)) * base / 100)
        good = got == want and (pct is None or base > 0)
        n += 1
        ok += good
        print(f"{'ok  ' if good else 'FAIL'} {name}: installed {base}, kit {got}, expected {want}")
    # the caveat, measured: D5's own 6035 plus Nagi, kit order versus adding the percents inside the function
    base = run(installed, (WEAPON_PCT,), 1)
    inside = ((100 + v6035 + 10) * (POTENCY * ITEM // 100)) // 100
    print(f'info: with {WEAPON_PCT} (+{v6035}) the game gives {base}; kit order gives {run(kit, (WEAPON_PCT,), 1, 0, allies=(((NAGI,), 0),))}, '
          f'percents added inside the function would give {inside}')
    print(f"{ok}/{n} {'abi' if args.abi else 'behavior'}; kit build sha256 {hashlib.sha256(patched).hexdigest()[:16]}, "
          f"installed exe {installed.exe_sha[:16]}")
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
