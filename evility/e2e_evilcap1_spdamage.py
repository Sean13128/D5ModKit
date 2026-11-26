"""EVILCAP1: sp_damage_percent through the REAL game code, not stubs.  Offline, read-only.

Runs the exe's own Habitual Licker (3011) block of FUN_1401ADA40 under Unicorn, from 0x1401ADD1F (the binary search
of the attacker's learned list for 0xBC3) to 0x1401ADE12 (r12 = the SP damage the game then applies to the target),
with the database tables of the installed game.  On the kit build the call at 0x1401ADDF0 is redirected to
wrap_spdmg, which runs the game's own damage_skill_dat (real Skill.dat rows) and then our rows.

    D5Modkit/.venv-macos/bin/python evility/e2e_evilcap1_spdamage.py [--abi]

--abi additionally checks, at every CALL executed inside the .d5el section, that rsp is 16-byte aligned, and that
the redirected call returns with rbx rbp rsi rdi r12-r15, xmm6-15 and rsp unchanged.

Not covered: the rest of FUN_1401ADA40 (the apply-damage call and its "SP absorb" sign flip are the game's own,
unchanged), whether FUN_1401B1BA0 reaches FUN_1401ADA40 for every hit in a live battle (decompiled, not run).
"""
import hashlib
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
START, END, SITE = 0x1401ADD1F, 0x1401ADE12, 0x1401ADDF0
LICKER = 3011
ROWS = {
    27691: {"family": "sp_damage_percent", "effects": [{"value": 50}]},                       # Mind Killer
    27801: {"family": "sp_damage_percent", "effects": [{"value": 40}], "conditions": [{"kind": "attack_skill"}]},
    27802: {"family": "sp_damage_percent", "effects": [{"value": 80, "max": 60}]},             # cap
}


def emu(exe):
    db = database.load_database(str(GAME / "Data/Database/Database_0.dat"))
    return so.Emu(exe_path=exe, db=db)


def run(e, attacker_ids, damage=1000, skill=0, defender_ids=(), abi=False, section=None):
    X = e.X
    mu = e.mu
    e.brk = e.heap_mark

    def unit(ids):
        u = bytearray(0x4800)
        ids = sorted(ids)
        struct.pack_into('<i', u, 0x3030, len(ids))
        for i, v in enumerate(ids):
            struct.pack_into('<i', u, 0x2F30 + 4 * i, v)
        struct.pack_into('<I', u, 0x4348, 0x28A)          # no stat record: nothing here reads one
        return e.alloc(u)

    def rec(u):
        r = bytearray(4704)
        struct.pack_into('<Q', r, 0x240, u)
        return e.alloc(r)

    atk, dfn = rec(unit(attacker_ids)), rec(unit(defender_ids))
    ctx = e.alloc(bytes(0x28000))
    struct.pack_into('<q', b := bytearray(8), 0, damage)
    mu.mem_write(ctx + 0x1328, bytes(b))                    # target entry 0: damage dealt
    mu.mem_write(ctx + 0x27670, struct.pack('<i', skill))   # the action's skill id (0 = normal attack)
    rsp = so.STACK + 0x100000 - 0x200     # FUN_1401ADA40's body runs with rsp 16-aligned (5 pushes, sub 0x1D0)
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    regs = {X.UC_X86_REG_RBX: atk, X.UC_X86_REG_R13: dfn, X.UC_X86_REG_R15: ctx, X.UC_X86_REG_R14: 0,
            X.UC_X86_REG_RDI: struct.unpack('<Q', e.read(atk + 0x240, 8))[0], X.UC_X86_REG_R12: 0,
            X.UC_X86_REG_RBP: 0x1111, X.UC_X86_REG_RSI: 0x2222}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.reg_write(X.UC_X86_REG_XMM6, struct.unpack('<I', struct.pack('<f', 100.0))[0])
    bad = []
    hooks = []
    if abi and section:
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        lo, hi = section
        nonvol = (X.UC_X86_REG_RBX, X.UC_X86_REG_RBP, X.UC_X86_REG_RSI, X.UC_X86_REG_RDI, X.UC_X86_REG_R12,
                  X.UC_X86_REG_R13, X.UC_X86_REG_R14, X.UC_X86_REG_R15, X.UC_X86_REG_RSP)
        xmms = [getattr(X, f'UC_X86_REG_XMM{i}') for i in range(6, 16)]
        saved = {}

        def code(uc, addr, size, _):
            if addr == SITE:
                saved.update({r: uc.reg_read(r) for r in nonvol + tuple(xmms)})
            elif addr == SITE + 5 and saved:
                for r, v in saved.items():
                    if uc.reg_read(r) != v:
                        bad.append(f'register {r} changed across the redirected call')
            if lo <= addr < hi:
                ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
                if ins.mnemonic == 'call' and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append(f'misaligned call at {addr:#x}')
        from unicorn import UC_HOOK_CODE
        hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.emu_start(START, END, count=2_000_000)
    finally:
        for h in hooks:
            mu.hook_del(h)
    assert not bad, bad
    return mu.reg_read(X.UC_X86_REG_R12)


def main():
    abi = '--abi' in sys.argv
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    patched = ev.build_patch(original, ROWS)
    info = ev.section_info(patched)
    tmp = Path(tempfile.mkdtemp(prefix='evilcap1-spd-', dir='/Volumes/Data/ai-tmp/claude/evilcap1'))
    (tmp / 'kit.exe').write_bytes(patched)
    kit = emu(tmp / 'kit.exe')
    section = (info['code'], info['base'] + len(info['data']))
    installed = emu(GAME / 'disgaea5.exe')
    cases = [
        ('installed exe: Habitual Licker alone (game control)', installed, dict(attacker_ids=(LICKER,)), 250),
        ('installed exe: no 3011, no SP damage', installed, dict(attacker_ids=(27691,)), 0),
        ('kit: 3011 alone is untouched (no row)', kit, dict(attacker_ids=(LICKER,)), 250),
        ('kit: 3011 + Mind Killer row 50', kit, dict(attacker_ids=(LICKER, 27691)), 500),
        ('kit: Mind Killer row without the 3011 alias does nothing', kit, dict(attacker_ids=(27691,)), 0),
        ('kit: 50 of 333 damage truncates like the game (166)', kit, dict(attacker_ids=(LICKER, 27691), damage=333), 166),
        ('kit: zero damage, nothing (game skips the lookup)', kit, dict(attacker_ids=(LICKER, 27691), damage=0), 0),
        ('kit: row on the defender, not the attacker', kit, dict(attacker_ids=(LICKER,), defender_ids=(27691, LICKER)), 250),
        ('kit: condition false (attack_skill on a normal attack)', kit, dict(attacker_ids=(LICKER, 27801)), 250),
        ('kit: condition true (attack_skill on a skill)', kit, dict(attacker_ids=(LICKER, 27801), skill=101), 400),
        ('kit: capped 80 at max 60', kit, dict(attacker_ids=(LICKER, 27802)), 600),
        ('kit: two rows add up (50 + 80 capped 60 = 110 %)', kit, dict(attacker_ids=(LICKER, 27691, 27802)), 1100),
        ('kit: 40 other ids around the row', kit, dict(attacker_ids=tuple(range(1, 41)) + (LICKER, 27691)), 500),
    ]
    bad = 0
    for name, e, kw, want in cases:
        got = run(e, abi=abi and e is kit, section=section, **kw)
        bad += got != want
        print(f"{'ok  ' if got == want else 'FAIL'} {name:60} SP damage {got} (expected {want})")
    print(f"{len(cases) - bad}/{len(cases)} {'abi' if abi else 'behavior'}; kit build sha256 "
          f"{hashlib.sha256(patched).hexdigest()[:16]}, installed exe {installed.exe_sha[:16]}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
