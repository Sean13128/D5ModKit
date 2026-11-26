#!/usr/bin/env python3
"""Offline bounded proof of D5 native move-commit counter; does not run the game.

The action-stack push callee is replaced in emulator memory by RET. Therefore this
proves only the counter arithmetic in 0x1404cf540 for the supplied fixture, not
the upstream path-cost calculation, undo or full gameplay.
"""
import argparse
import hashlib
import struct
from pathlib import Path
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_RSP

EXE = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
BASE, FUNC, PUSH = 0x140000000, 0x1404cf540, 0x140151630
STACK, UNIT, RETURN = 0x300000000, 0x400000000, 0x500000000

def run(raw, cost, previous, top=None):
    pe = pefile.PE(data=raw)
    u = Uc(UC_ARCH_X86, UC_MODE_64)
    image_size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xfff) & ~0xfff
    u.mem_map(BASE, image_size, UC_PROT_ALL)
    u.mem_write(BASE, pe.get_memory_mapped_image())
    u.mem_write(PUSH, b'\xc3')  # isolated stack-writer, does not update action stack
    u.mem_map(STACK, 0x10000); u.mem_map(UNIT, 0x2000); u.mem_map(RETURN, 0x1000)
    sp = STACK + 0x8008  # Windows x64 callee entry: 8 mod 16
    u.mem_write(sp, struct.pack('<Q', RETURN) + bytes(0x50))
    # parameters 5,6,7 occupy caller stack home + 0x28, +0x30, +0x38
    u.mem_write(sp + 0x28, struct.pack('<Q', 7))
    u.mem_write(sp + 0x30, struct.pack('<Q', previous))
    u.mem_write(sp + 0x38, struct.pack('<Q', cost & 0xffff))
    u.mem_write(UNIT + 0x61c, struct.pack('<h', previous))
    if top is not None:
        u.mem_write(UNIT + 0x1080, b'\x01')
        # top entry lives at +0xbbc + count*20; +16 facing, +18 old steps
        u.mem_write(UNIT + 0xbd0, struct.pack('<iII I hh', 2, 0, 0, 0, 7, top))
    for reg,val in [(UC_X86_REG_RCX,UNIT),(UC_X86_REG_RDX,0),(UC_X86_REG_R8,0),(UC_X86_REG_R9,0),(UC_X86_REG_RSP,sp)]:
        u.reg_write(reg,val)
    u.emu_start(FUNC, RETURN, count=500)
    return struct.unpack('<h', u.mem_read(UNIT + 0x61c, 2))[0]

def main():
    p=argparse.ArgumentParser(); p.add_argument('--exe',type=Path,default=EXE); a=p.parse_args()
    raw=a.exe.read_bytes(); assert hashlib.sha256(raw).hexdigest()==SHA, 'wrong executable'
    cases=[(3,0,None,3),(4,2,None,6),(0,2,None,2),(3,7,2,5),(0,7,2,2)]
    for cost, previous, top, expected in cases:
        got=run(raw,cost,previous,top)
        assert got==expected,(cost,previous,top,got,expected)
    print('PASS: 5 native commit counter cases; stack push stubbed; executable hash verified')
if __name__=='__main__': main()
