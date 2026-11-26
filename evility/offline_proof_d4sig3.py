"""D4SIG3: support_magic_percent (Chief, Medical Insertion 304) through the REAL game code, at both real call sites, under
Unicorn, normal and --abi.  Offline, read-only.

The wrapped function is FUN_1401FEFA0 (D5's Medical Insertion 1180: *value *= the 1180 row's +0x38 when the skill is support
magic).  Its two static callers are wrapped (wrap_support): the proof runs the game's own instructions of each caller around
the CALL (0x1401C0067..0x1401C007B in damage_buff_compute_buff, 0x140201EF6..0x140201F0C in FUN_140201D90) with the real
magic.dat / Skill.dat tables of the installed game, so the real FUN_1401FEFA0 body and the real magic-row lookup run too.

  * the row is read verbatim from d5lib/importers/d4-evility-overlay.json (D4_Unique_5301, row 8304);
  * controls: the installed (unpatched) exe gives the game's own x(1180 row) result, the kit build leaves every unit without a
    support_magic_percent row exactly as the game does;
  * --abi: at each redirected CALL the stack is 16-byte aligned, rbx rbp rsi rdi r12-r15 xmm6-15 rsp come back unchanged,
    and every CALL executed inside the .d5el section is aligned;
  * --control gate|formula|row: build a deliberately broken wrapper / row; the proof must then FAIL (exit 1).

D5Modkit/.venv-macos/bin/python evility/offline_proof_d4sig3.py [--abi] [--control gate|formula|row]
"""
import argparse
import hashlib
import json
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(KIT), str(KIT / "tools"), str(KIT / "evility")]
from d5lib import database, evility as ev          # noqa: E402
import stat_oracle as so                            # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA   # noqa: E402

GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
SCRATCH = Path("/Volumes/Data/ai-tmp/claude/d4sig3")
MEDICAL, CHIEF = 1180, 8304
SUPPORT_SKILL, ATTACK_SKILL = 1499, 1                 # magic.dat rows with +0x3F6 == 5 and != 5 (checked below)
EXTRA = 27901                                         # a second row, +20
SITES = {  # name: (start, call site, end, where the value lives after the call)
    'damage_buff_compute_buff': (0x1401C0067, 0x1401C0076, 0x1401C007B),
    'skill value preview': (0x140201EF6, 0x140201F03, 0x140201F0C),
}


def chief_row():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    return mods['D4_Unique_5301']['behaviors']['evilities'][str(CHIEF)]


def emu(exe):
    db = database.load_database(str(GAME / 'Data/Database/Database_0.dat'))
    return so.Emu(exe_path=exe, db=db)


def run(e, site, ids, value, skill, abi=False, section=None, caster=True):
    """the game's own caller code around the call; returns the int the caller reads back"""
    X, mu = e.X, e.mu
    e.brk = e.heap_mark
    start, call, end = SITES[site]
    u = bytearray(0x4800)
    ids = sorted(ids)
    struct.pack_into('<i', u, 0x3030, len(ids))
    for i, v in enumerate(ids):
        struct.pack_into('<I', u, 0x2F30 + 4 * i, v)
    unit = e.alloc(u)
    rec_bytes = bytearray(4704)
    struct.pack_into('<Q', rec_bytes, 0x240, unit if caster else 0)
    rec = e.alloc(rec_bytes)
    sk = e.alloc(struct.pack('<i', skill) + bytes(12))
    rsp = so.STACK + 0x100000 - 0x200                    # 16-aligned, as at the real call sites
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    slot = rsp + (0x5C if site == 'damage_buff_compute_buff' else 0x50)
    mu.mem_write(slot, struct.pack('<i', value))
    regs = {X.UC_X86_REG_RBP: 0x1111, X.UC_X86_REG_RDI: 0x3333, X.UC_X86_REG_R13: 0x4444, X.UC_X86_REG_R15: 0x5555,
            X.UC_X86_REG_RDX: 0, X.UC_X86_REG_R9: 0, X.UC_X86_REG_RAX: 0, X.UC_X86_REG_RBX: 0x6666}
    if site == 'damage_buff_compute_buff':
        regs.update({X.UC_X86_REG_R12: rec, X.UC_X86_REG_RSI: sk, X.UC_X86_REG_R14: 0x7777})
    else:
        regs.update({X.UC_X86_REG_R14: rec, X.UC_X86_REG_RAX: sk, X.UC_X86_REG_RSI: 0x2222, X.UC_X86_REG_R12: 0x8888})
    for r, v in regs.items():
        mu.reg_write(r, v)
    for i in range(6, 16):
        mu.reg_write(getattr(X, f'UC_X86_REG_XMM{i}'), 0x1000 + i)
    bad, hooks = [], []
    if abi and section:
        import capstone
        from unicorn import UC_HOOK_CODE
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        lo, hi = section
        nonvol = (X.UC_X86_REG_RBX, X.UC_X86_REG_RBP, X.UC_X86_REG_RSI, X.UC_X86_REG_RDI, X.UC_X86_REG_R12,
                  X.UC_X86_REG_R13, X.UC_X86_REG_R14, X.UC_X86_REG_R15, X.UC_X86_REG_RSP)
        xmms = tuple(getattr(X, f'UC_X86_REG_XMM{i}') for i in range(6, 16))
        saved = {}

        def code(uc, addr, size, _):
            if addr == call:
                if uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append('site entered with a misaligned stack')
                saved.update({r: uc.reg_read(r) for r in nonvol + xmms})
            elif addr == call + 5 and saved:
                bad.extend(f'register {r} changed across the redirected call'
                           for r, v in saved.items() if uc.reg_read(r) != v)
            if lo <= addr < hi:
                ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
                if ins.mnemonic == 'call' and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append(f'misaligned call at {addr:#x}')
        hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.emu_start(start, end, count=2_000_000)
    finally:
        for h in hooks:
            mu.hook_del(h)
    assert not bad, bad
    return struct.unpack('<i', bytes(mu.mem_read(slot, 4)))[0]


def magic_categories(db):
    b = db.raw['magic.dat']
    n = struct.unpack('<H', b[:2])[0]
    body = b[4:]
    return {struct.unpack_from('<I', body, 1140 * i)[0]: body[1140 * i + 0x3F6] for i in range(n)}


def evil1180_value(db):
    """the +0x38 of Skill.dat row 1180, read from the raw table (the game's damage_skill_dat returns this row)"""
    b = db.raw['Skill.dat']
    n = struct.unpack('<H', b[:2])[0]
    for i in range(n):
        rec = b[4 + 96 * i:4 + 96 * (i + 1)]
        if struct.unpack_from('<I', rec, 0)[0] == MEDICAL:
            return struct.unpack_from('<i', rec, 0x38)[0]
    raise SystemExit('Skill.dat has no row 1180')


def mutated_asm(control):
    """a copy of the asm source with one deliberate fault; ev._asm_source reads ev.ASM_FILE"""
    text = Path(ev.ASM_FILE).read_text()
    if control == 'gate':
        old = "    cmp byte ptr [rax + 0x3f6], 5\n    jne .sup_done\n"
        new = "    cmp byte ptr [rax + 0x3f6], 5\n"
    elif control == 'formula':
        old = "    add eax, 100\n    imul eax, dword ptr [rsp + 0x28]"
        new = "    add eax, 99\n    imul eax, dword ptr [rsp + 0x28]"
    else:
        return None
    assert text.count(old) == 1, control
    out = SCRATCH / f'd5evil-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('gate', 'formula', 'row'))
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    row = chief_row()
    assert row == {'family': 'support_magic_percent', 'effects': [{'value': 50}]}, row
    rows = {CHIEF: dict(row), EXTRA: {'family': 'support_magic_percent', 'effects': [{'value': 20}]}}
    if args.control == 'row':
        rows[CHIEF] = {'family': 'support_magic_percent', 'effects': [{'value': 49}]}
    if args.control in ('gate', 'formula'):
        ev.ASM_FILE = str(mutated_asm(args.control))
    patched = ev.build_patch(original, rows)
    info = ev.section_info(patched)
    tmp = Path(tempfile.mkdtemp(prefix='d4sig3-', dir=SCRATCH))
    (tmp / 'kit.exe').write_bytes(patched)
    kit = emu(tmp / 'kit.exe')
    installed = emu(ORIGINAL)       # D4SIG4: the pinned original exe; the live exe carries the kit's own runtime since the D4SIG3 install
    section = (info['code'], info['base'] + len(info['data']))
    cats = magic_categories(kit.db)
    assert cats[SUPPORT_SKILL] == 5 and cats[ATTACK_SKILL] != 5, (cats[SUPPORT_SKILL], cats[ATTACK_SKILL])
    x = evil1180_value(kit.db)
    assert x == 2, f'the game multiplies by the 1180 row value, expected 2 here, read {x}'
    # (name, emulator, ids, value, skill, caster present, expected)
    cases = [
        ('installed exe: Medical Insertion 1180 alone, support magic -> game x2', installed, (MEDICAL,), 100, SUPPORT_SKILL, True, 100 * x),
        ('installed exe: 1180 alone, not support magic -> untouched', installed, (MEDICAL,), 100, ATTACK_SKILL, True, 100),
        ('installed exe: no 1180 -> untouched', installed, (CHIEF,), 100, SUPPORT_SKILL, True, 100),
        ('kit: 1180 alone (no row) behaves as the game: x2', kit, (MEDICAL,), 100, SUPPORT_SKILL, True, 100 * x),
        ('kit: nobody with anything -> untouched', kit, (), 100, SUPPORT_SKILL, True, 100),
        ('kit: Chief 1180 + 8304, support magic 100 -> 150', kit, (MEDICAL, CHIEF), 100, SUPPORT_SKILL, True, 150),
        ('kit: 8304 alone (no 1180), support magic -> 150', kit, (CHIEF,), 100, SUPPORT_SKILL, True, 150),
        ('kit: 1180 + 8304, not support magic -> untouched (the game does nothing there)', kit, (MEDICAL, CHIEF), 100, ATTACK_SKILL, True, 100),
        ('kit: 8304 alone, not support magic -> untouched', kit, (CHIEF,), 100, ATTACK_SKILL, True, 100),
        ('kit: 33 x 150 / 100 truncates toward zero -> 49', kit, (MEDICAL, CHIEF), 33, SUPPORT_SKILL, True, 49),
        ('kit: 1 -> 1', kit, (CHIEF,), 1, SUPPORT_SKILL, True, 1),
        ('kit: -33 truncates toward zero like the signed divide in D4 -> -49', kit, (CHIEF,), -33, SUPPORT_SKILL, True, -49),
        ('kit: 0 stays 0', kit, (CHIEF,), 0, SUPPORT_SKILL, True, 0),
        ('kit: two rows add up (50 + 20 = 70) -> 170', kit, (CHIEF, EXTRA), 100, SUPPORT_SKILL, True, 170),
        ('kit: a large value (1000) -> 1500, no cap in this runtime', kit, (CHIEF,), 1000, SUPPORT_SKILL, True, 1500),
        ('kit: caster record without a unit pointer -> untouched, no fault', kit, (CHIEF,), 100, SUPPORT_SKILL, False, 100),
        ('kit: 40 ids around the row', kit, tuple(range(1, 41)) + (CHIEF,), 100, SUPPORT_SKILL, True, 150),
    ]
    if args.control == 'row':
        cases = [c for c in cases if 'Chief' in c[0] or '8304' in c[0] or 'truncates' in c[0]]
    checks = bad = 0
    for site in SITES:
        for name, e, ids, value, skill, caster, want in cases:
            got = run(e, site, ids, value, skill, abi=args.abi and e is kit, section=section, caster=caster)
            ok = got == want
            checks += 1
            bad += not ok
            print(f"{'ok  ' if ok else 'FAIL'} [{site}] {name}: {got} (expected {want})")
    mode = 'abi' if args.abi else 'behavior'
    print(f"{checks - bad}/{checks} {mode}; kit build sha256 {hashlib.sha256(patched).hexdigest()[:16]}, "
          f"installed exe {installed.exe_sha[:16]}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
