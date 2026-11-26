"""Trace native wheel initialization ordering; resource operations are stand-ins.

This is evidence about existing game code, not a proof of a page-switch hook.
"""
import struct
import unicorn_darwin_shim
unicorn_darwin_shim.install(force=True)
import test_recruit_runtime as rt
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_RCX, UC_X86_REG_RSP, UC_X86_REG_RIP


def test_both_native_menus_reset_twelve_actors_before_redraw():
    rt.RealUnlockCodeTests.setUpClass()
    case = rt.RealUnlockCodeTests()
    try:
        for start, end in ((0x140662ce0, 0x140662d7d),
                           (0x140482470, 0x1404824f2)):
            for selection, expected in ((-1, 0), (3, 3), (17, 5)):
                mu, _, _ = case.machine(case.patched)
                mu.mem_write(rt.OBJECT + 0x84, struct.pack('<i', selection))
                mu.mem_write(rt.OBJECT + 0x208, struct.pack('<i', 6))
                mu.reg_write(UC_X86_REG_RSP, rt.STACK + 0x100008)
                mu.reg_write(UC_X86_REG_RCX, rt.OBJECT)
                seen = []
                def intercept(machine, addr, size, data):
                    if addr == end:
                        machine.emu_stop()
                        return
                    seen.append((addr, machine.reg_read(UC_X86_REG_RCX)))
                    sp = machine.reg_read(UC_X86_REG_RSP)
                    assert sp % 16 == 8  # Win64 callee entry; caller reserved home space
                    ret = struct.unpack('<Q', machine.mem_read(sp, 8))[0]
                    machine.reg_write(UC_X86_REG_RSP, sp + 8)
                    machine.reg_write(UC_X86_REG_RIP, ret)
                for addr in (0x14014f0e0, 0x14014f2c0, 0x140666920, 0x1406674f0, end):
                    mu.hook_add(UC_HOOK_CODE, intercept, begin=addr, end=addr)
                mu.emu_start(start, 0, count=10000)
                assert struct.unpack('<i', mu.mem_read(rt.OBJECT + 0x84, 4))[0] == expected
                expect = [(fn, rt.OBJECT + 0x210 + i * 0x3e0)
                          for i in range(12) for fn in (0x14014f0e0, 0x14014f2c0)]
                expect += [(0x140666920, rt.OBJECT), (0x1406674f0, rt.OBJECT)]
                assert seen == expect
    finally:
        rt.RealUnlockCodeTests.tearDownClass()


def test_native_teardown_releases_sprite_and_nonresident_model_loaders():
    """Follow real destructor branches; external managers are instrumented stand-ins."""
    from unicorn.x86_const import UC_X86_REG_RAX
    rt.RealUnlockCodeTests.setUpClass()
    case = rt.RealUnlockCodeTests()
    try:
        # 1 = sprite; 2 = model. Model 2 is resident and needs no OBF release.
        for kind, resource, expected in ((1, 50, 0x1403ffe60),
                                         (2, 50, 0x140407a30),
                                         (2, 2, None)):
            mu, _, _ = case.machine(case.patched)
            unit = rt.OBJECT + 0x210
            mu.mem_write(unit + 0x248, bytes([kind]))
            mu.mem_write(unit + 0x2a0, struct.pack('<i', resource))
            mu.reg_write(UC_X86_REG_RSP, rt.STACK + 0x100008)
            mu.reg_write(UC_X86_REG_RCX, unit)
            seen = []
            def intercept(machine, addr, size, data):
                if addr == 0x14014f2c0:
                    machine.emu_stop()
                    return
                seen.append(addr)
                sp = machine.reg_read(UC_X86_REG_RSP)
                assert sp % 16 == 8
                ret = struct.unpack('<Q', machine.mem_read(sp, 8))[0]
                machine.reg_write(UC_X86_REG_RAX, 0)
                machine.reg_write(UC_X86_REG_RSP, sp + 8)
                machine.reg_write(UC_X86_REG_RIP, ret)
            for addr in (0x1402e78f0, 0x1403ffe60, 0x140407a30, 0x14014f2c0):
                mu.hook_add(UC_HOOK_CODE, intercept, begin=addr, end=addr)
            mu.emu_start(0x14014f0e0, 0, count=10000)
            assert seen == [0x1402e78f0] + ([expected] if expected else [])
            assert struct.unpack('<i', mu.mem_read(unit + 0x2a0, 4))[0] == 0
    finally:
        rt.RealUnlockCodeTests.tearDownClass()
