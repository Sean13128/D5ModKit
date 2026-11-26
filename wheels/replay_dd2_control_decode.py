"""Replay the exact TEST18B instruction that decides a class preview's control code, per wheel family.

    python wheels/replay_dd2_control_decode.py --payload EXE --before MODS --after MODS --out FILE

What it runs: `anm_actor_advance` (`0x1402f4f70`, the function the Recruiter's class preview calls every
frame through `anm_owner`/`anm_actor_select_motion`), from the **real bytes of the TEST18B image**, with
the **real key table** of each class's own animation bank and a fabricated (but fully specified) actor:

    [actor+0x68] -> anim record, u16 at +2 = animation root index
    [actor+0x60] -> { +0x50: anim table (20 B/row), +0x58: key table (12 B/row) }
    [actor+0x58] -> the animation's first control key (the root node's first key)
    [actor+0x2a] -> that key's time      [actor+0x28] -> Q16 time
    [actor+0x30] = [actor+0x40] = 0x00100000 (16 steps of budget; [mask] is the game's own global)
    [actor+0x2c] = -1 (no lifetime), [actor+0x48] = 0 (no node tree: the two dispatch calls are skipped,
    so nothing is stubbed and every instruction executed is the game's own)

It records, at `0x1402f5002` (`movsx ecx, byte ptr [rdx+2]`), every control code the engine decodes, and
counts the loop passes (`0x1402f4ff0`).  A code in 1..5 is a control action (loop marker / loop back /
conditional / wait / hold) and the function returns after that pass; code 0 is "no control action" and the
pass repeats until the budget is gone - the preview never holds.

The wheel lays families `(cursor + i) % count` for i = -5..5 out on its first frame, so the last five
entries of the 110-family list are on screen when it opens: with all nine DD2 class packs enabled those
are DD2 families, i.e. exactly the banks this replay walks.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn.x86_const import (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_RSP,
                               UC_X86_REG_RIP, UC_X86_REG_RBX, UC_X86_REG_RBP,
                               UC_X86_REG_RSI, UC_X86_REG_RDI, UC_X86_REG_RAX)

KIT = "/Volumes/Data/Projects/D5/Local/Worktrees/dd2wheel"
sys.path.insert(0, KIT)
from d5lib import anm  # noqa: E402

ADVANCE = 0x1402F4F70
DECODE = 0x1402F5002      # movsx ecx, byte ptr [rdx+2]
LOOP_TOP = 0x1402F4FF0
SCREEN = 0x10000000
STACK = 0x20000000
ACTOR = 0x30000000
ANIMREC = 0x30100000
ANIMTAB = 0x30200000
KEYTAB = 0x30300000
MAXSTEPS = 400000


class Machine:
    def __init__(self, payload):
        self.pe = pefile.PE(payload, fast_load=True)
        self.ib = self.pe.OPTIONAL_HEADER.ImageBase
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        for s in self.pe.sections:
            va = self.ib + s.VirtualAddress
            size = max(s.Misc_VirtualSize, s.SizeOfRawData)
            if not size:
                continue
            self.uc.mem_map(va & ~0xFFF, ((va & 0xFFF) + size + 0xFFF) & ~0xFFF, 7)
            self.uc.mem_write(va, s.get_data()[:s.SizeOfRawData])
        for base, size in ((SCREEN, 0x10000), (STACK, 0x20000), (ACTOR, 0x1000),
                           (ANIMREC, 0x1000), (ANIMTAB, 0x10000), (KEYTAB, 0x40000)):
            self.uc.mem_map(base, size)
        # the game's per-frame step mask (global, zero in the file): the advance loop's budget is
        # `[actor+0x40] & [actor+0x30] & this`.  Set explicitly so the loop has budget to run.
        self.mask_address = 0x140A02B30
        self.uc.mem_write(self.mask_address, struct.pack("<I", 0xFFFFFFFF))
        self.codes = []
        self.passes = 0
        self.steps = 0
        self.uc.hook_add(UC_HOOK_CODE, self._code, begin=ADVANCE, end=ADVANCE + 0x800)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._bad)

    def _bad(self, uc, access, address, size, value, data):
        raise RuntimeError("unmapped %s at %#x" % (access, address))

    def _code(self, uc, address, size, data):
        if address == DECODE:
            ptr = uc.reg_read(UC_X86_REG_RDX)
            self.codes.append(uc.mem_read(ptr + 2, 1)[0])
        elif address == LOOP_TOP:
            self.passes += 1
        self.steps += 1
        if self.steps > MAXSTEPS:
            raise RuntimeError("step budget exceeded")

    def run(self, keys, root_first, root_count, key_time):
        """keys: [(time, flags, cell, xform, color, param)]; returns dict."""
        self.codes, self.passes, self.steps = [], 0, 0
        uc = self.uc
        # key table
        blob = b"".join(struct.pack("<HHHHHH", *k) for k in keys)
        uc.mem_write(KEYTAB + root_first * 12, blob)
        # anim table: 20-byte rows; root at +2, first_key at +0xc, num_keys at +0xe
        row = bytearray(20)
        struct.pack_into("<H", row, 2, 0)          # root index (anim record index is not used)
        struct.pack_into("<h", row, 0xC, root_first)
        struct.pack_into("<H", row, 0xE, root_count)
        uc.mem_write(ANIMTAB, bytes(row))
        # anim record: u16 at +2 = root index
        uc.mem_write(ANIMREC, struct.pack("<HH", 0, 0))
        # actor
        actor = bytearray(0x1000)
        struct.pack_into("<Q", actor, 0x68, ANIMREC)
        struct.pack_into("<Q", actor, 0x60, ANIMREC + 0x800)   # -> {0x50: animtab, 0x58: keytab}
        uc.mem_write(ANIMREC + 0x850, struct.pack("<Q", ANIMTAB))
        uc.mem_write(ANIMREC + 0x858, struct.pack("<Q", KEYTAB))
        struct.pack_into("<Q", actor, 0x58, KEYTAB + root_first * 12)
        struct.pack_into("<H", actor, 0x2A, key_time & 0xFFFF)
        struct.pack_into("<i", actor, 0x28, 0)
        struct.pack_into("<i", actor, 0x2C, -1)
        struct.pack_into("<i", actor, 0x30, 0x00100000)
        struct.pack_into("<i", actor, 0x40, 0x00100000)
        struct.pack_into("<Q", actor, 0x48, 0)
        uc.mem_write(ACTOR, bytes(actor))
        uc.mem_write(STACK, b"\x00" * 0x20000)
        uc.reg_write(UC_X86_REG_RCX, ACTOR)
        uc.reg_write(UC_X86_REG_RSP, STACK + 0x10000)
        uc.mem_write(STACK + 0x10000, struct.pack("<Q", SCREEN))  # return address
        try:
            uc.emu_start(ADVANCE, SCREEN, count=MAXSTEPS)
            ret = "returned"
        except Exception as exc:  # noqa: BLE001
            ret = "%s: %s" % (type(exc).__name__, exc)
        return {"codes": self.codes, "passes": self.passes,
                "control_action": any(1 <= c <= 5 for c in self.codes),
                "exit": ret, "ip": uc.reg_read(UC_X86_REG_RIP)}


def bank_of(pack):
    """The class's own stand bank (the anm0 member the wheel's preview draws)."""
    folder = os.path.join(pack, "files", "Anime", "ANM_HI_JP.dat")
    files = sorted(f for f in os.listdir(folder) if f.startswith("anm0") and f.endswith(".lzs"))
    return os.path.join(folder, files[0])


def probe(machine, pack, anim_ids):
    path = bank_of(pack)
    parsed = anm.load(path)
    block = parsed.blocks[0]
    byid = {a.id: a for a in block.animations}
    out = {}
    for aid in anim_ids:
        anim = byid.get(aid)
        if anim is None or not (0 <= anim.root < len(block.nodes)):
            out[str(aid)] = {"missing": True}
            continue
        node = block.nodes[anim.root]
        keys = [(k.time, k.flags, k.cell, k.xform, k.color, k.param)
                for k in block.node_keys(node)]
        if not keys:
            out[str(aid)] = {"no_keys": True}
            continue
        res = machine.run(keys, node.first_key, node.num_keys, keys[0][0])
        res["root_flags"] = ["%#06x" % k[1] for k in keys[:4]]
        out[str(aid)] = res
    return {"bank": os.path.basename(path), "anims": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    ap.add_argument("--before", required=True, help="mods dir with the shipped 9 DD2 class packs")
    ap.add_argument("--after", required=True, help="mods dir with the rebuilt packs")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    m = Machine(args.payload)
    packs = sorted(d for d in os.listdir(args.before)
                   if d.startswith("DD2_Class_") and os.path.isdir(os.path.join(args.before, d)))
    receipt = {"payload": os.path.basename(args.payload), "packs": {}, "anims": [1, 101, 1001, 1007]}
    failures = []
    for name in packs:
        before = probe(m, os.path.join(args.before, name), receipt["anims"])
        after = probe(m, os.path.join(args.after, name), receipt["anims"])
        receipt["packs"][name] = {"before": before, "after": after}
        for aid, rec in after["anims"].items():
            if rec.get("missing") or rec.get("no_keys"):
                continue
            if not rec["control_action"]:
                failures.append("%s anim %s: still no control action after the rebuild" % (name, aid))
        for aid, rec in before["anims"].items():
            if rec.get("missing") or rec.get("no_keys"):
                continue
            if rec["control_action"]:
                failures.append("%s anim %s: the SHIPPED bank already had a control action" % (name, aid))
        line = []
        for aid in ("1", "1001"):
            b, a = before["anims"].get(aid, {}), after["anims"].get(aid, {})
            if b and a and not b.get("missing"):
                line.append("anim %s: shipped codes=%s passes=%d -> rebuilt codes=%s passes=%d"
                            % (aid, b["codes"][:4], b["passes"], a["codes"][:4], a["passes"]))
        print(name)
        for l in line:
            print("   ", l)
    receipt["failures"] = failures
    with open(args.out, "w") as fh:
        json.dump(receipt, fh, indent=1)
    print("A/B failures:", len(failures))
    for f in failures[:8]:
        print("  -", f)
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
