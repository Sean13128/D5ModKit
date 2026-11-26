"""PLUMEDIAG1: Plume's power aura through the REAL game code, not stubs.  Offline, read-only.

Runs the exe's own damage_attacker_bonus (0x1401C1940) under Unicorn, which calls the exe's own
damage_attack_bonus_rules -> the installed wrap_power hook -> the installed Plume row, on a minimal battle table
(three battle records, three unit records, the six defeat counters at 0x146A5F054).  Asserts the attacker bonus
A (the percent that enters damage as T*(100+A)/100 - U).

    D5Modkit/.venv-macos/bin/python evility/e2e_plume_installed.py [path/to/disgaea5.exe]

Default exe: the installed game.  What it does not cover: the rest of battle_damage_compute_target, real unit
records of a live battle, whether the game's defeat path increments the counters (decompiled, not run).
"""
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(KIT), str(KIT / "tools")]
from d5lib import database                      # noqa: E402
import stat_oracle as so                        # noqa: E402

GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
TABLE, STRIDE, COUNTERS, RID = 0x141BA33B0, 4704, 0x146A5F054, 26304


def main(exe):
    e = so.Emu(exe_path=exe, db=database.load_database(str(GAME / "Data/Database/Database_0.dat")))
    X = e.X

    def unit(ids, team, slot):
        u = bytearray(0x4800)
        ids = sorted(ids)
        struct.pack_into('<i', u, 0x3030, len(ids))
        for i in range(64):
            struct.pack_into('<i', u, 0x2F30 + 4 * i, ids[i] if i < len(ids) else -1)
        u[0x2E32] = team
        struct.pack_into('<I', u, 0x4348, slot)
        struct.pack_into('<q', u, 0x2CE8, 21)
        struct.pack_into('<qq', u, 0x2CC8, 100, 100)
        return e.alloc(u)

    def bonus(counts, plume=True, plume_team=0, nagi_ids=(), plume_ids=(RID,)):
        e.mu.mem_write(TABLE, bytes(8 * STRIDE))
        recs = [(0, unit(nagi_ids, 0, 0)), (2, unit((), 1, 2))] + ([(1, unit(plume_ids, plume_team, 1))] if plume else [])
        for i, u in recs:
            a = TABLE + i * STRIDE
            e.put(a + 0x240, u)
            e.mu.mem_write(a + 0x2E8, b'\1')
            e.mu.mem_write(a + 0x2EE, struct.pack('<h', -1))
        e.mu.mem_write(COUNTERS, struct.pack('<6H', *counts))
        ctx = e.alloc(bytes(0x28000))
        e.mu.mem_write(ctx + 0x1318, struct.pack('<h', 2))     # target entry 0 -> battle record 2
        rsp = so.STACK + 0x100000 - 0x100
        e.mu.mem_write(rsp, struct.pack('<Q', so.RET))
        e.mu.reg_write(X.UC_X86_REG_RSP, rsp)
        for r, v in ((X.UC_X86_REG_RCX, TABLE), (X.UC_X86_REG_RDX, ctx), (X.UC_X86_REG_R8, 0), (X.UC_X86_REG_R9, 1)):
            e.mu.reg_write(r, v)
        e.mu.emu_start(0x1401C1940, so.RET, count=5_000_000)
        return e.mu.reg_read(X.UC_X86_REG_RAX) & 0xFFFFFFFF

    rich = list(range(1, 41))
    cases = [("no provider, 0 defeats", dict(counts=(0,) * 6, plume=False), 0),
             ("0 defeats", dict(counts=(0,) * 6), 0),
             ("1 defeat (enemy slot)", dict(counts=(0, 1, 0, 0, 0, 0)), 10),
             ("3 defeats", dict(counts=(0, 3, 0, 0, 0, 0)), 30),
             ("5 defeats", dict(counts=(0, 5, 0, 0, 0, 0)), 50),
             ("one per team slot", dict(counts=(1,) * 6), 60),
             ("25 defeats -> cap", dict(counts=(0, 25, 0, 0, 0, 0)), 200),
             ("provider on the enemy team", dict(counts=(0, 3, 0, 0, 0, 0), plume_team=1), 0),
             ("provider absent", dict(counts=(0, 3, 0, 0, 0, 0), plume=False), 0),
             ("40 other ids on both units", dict(counts=(0, 3, 0, 0, 0, 0), nagi_ids=rich, plume_ids=rich[:20] + [RID]), 30)]
    bad = 0
    for name, kw, want in cases:
        got = bonus(**kw)
        bad += got != want
        print(f"{'ok  ' if got == want else 'FAIL'} {name:32} A = {got} (expected {want})")
    print("attacker bonus A: damage = floor(T*(100+A)/100) - U; Nagi ATK 21 -> T 21, A 10 -> 23, A 30 -> 27, A 200 -> 63")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else GAME / "disgaea5.exe"))
