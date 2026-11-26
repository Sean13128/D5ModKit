"""Offline proof for the class-mastery extension (EX-07).

Everything runs in Unicorn over the *pinned original* exe (sha256 49a7530b...db282ce) plus the extension's own
section; no game process, install, save or live state is touched.  Four questions are answered with executed native
instructions:

  1. vanilla identical  -- every redirected mapper call site answers exactly what the unpatched game answers for
                           every vanilla id, and the native award writer leaves a vanilla unit byte-identical to
                           the unpatched build.
  2. custom XP          -- the real award writer (0x14015F480) with a custom class gives the family's own six
                           counters in its spare slot and nothing else, while the same call on the unpatched build
                           writes nothing at all.
  3. sub-class honored  -- the patched selected-award gate passes a configured sub-class id to the writer instead
                           of falling back to the unit's own class, and keeps every vanilla behavior.
  4. listed             -- the sub-class screen's patched family fetch returns the configured families for indices
                           47.., the vanilla stack array for 0..46, and nothing once the screen's 47 rows are used;
                           the native availability gate then says yes for a custom family.

`--build-only` builds and validates every fixture without importing Unicorn.
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

KIT = Path(os.environ.get("D5_KIT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))

ORIGINAL_SHA = "49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce"
VANILLA = tuple(range(1010, 1270, 10)) + tuple(range(2010, 2220, 10))

PAGE = 0x1000
STACK, STACK_SIZE = 0x100000000, 0x200000
SP = STACK + STACK_SIZE - 0x1000
UNIT, JOBRANK, CHARDAT, SCREEN, ARRAY = (0x400000000, 0x400100000, 0x400200000,
                                         0x400300000, 0x400400000)
SENTINEL = 0x400000000000

U_CLASS, U_FLAG, U_SUBCLASS, U_SERIAL = 0x2E04, 0x2E32, 0x35AC, 0x3060
U_COUNTERS, U_BONUS = 0x30A4, 0x359C
G_MIN, G_MAX = 0x140A18750, 0x140A18758       # award amount clamp
G_ENABLED, G_NOTIFY = 0x145574B28, 0x140BDFD08  # writer gate; notify block (kind 5 only)
G_JOBRANK, G_JOBRANK_COUNT = 0x140A03B38, 0x140A03B40


def counter_offset(slot, rank=0):
    return U_COUNTERS + slot * 0x18 + rank * 4


# ------------------------------------------------------------------------------------------ image/emulation
class Image:
    """the patched exe mapped as the game would map it (sections at their RVAs, image base 0x140000000)"""

    def __init__(self, exe):
        import pefile
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
        self.pe = pefile.PE(data=exe, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        size = (self.pe.OPTIONAL_HEADER.SizeOfImage + PAGE - 1) & -PAGE
        self.uc.mem_map(self.base, size)
        self.mapped.add(("img", self.base, size))
        for s in self.pe.sections:
            data = self.pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)
            self.uc.mem_write(self.base + s.VirtualAddress, bytes(data))
        self.write(STACK, bytes(STACK_SIZE))

    def write(self, address, data):
        for page in range(address & -PAGE, (address + len(data) + PAGE - 1) & -PAGE, PAGE):
            if not any(a <= page < a + n for _, a, n in self.mapped):
                self.uc.mem_map(page, PAGE)
                self.mapped.add(("o", page, PAGE))
        self.uc.mem_write(address, bytes(data))

    def read(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    def offset(self, va):
        return self.pe.get_offset_from_rva(va - self.base)


REGS = None


def _regs():
    global REGS
    if REGS is None:
        from unicorn import x86_const as X
        REGS = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in
                ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9", "r10", "r11",
                 "r12", "r13", "r14", "r15", "rip")}
    return REGS


def run(exe, start, args=(), stop=None, setup=None, instruction_max=200000, stack_args=(), regs_extra=()):
    """execute from `start` with the Windows x64 argument registers; stop at `stop` (a VA) or when the sentinel is
    returned to.  `setup(write)` maps fixtures.  Returns {rax, rcx, rdx, rip, instructions, image...}"""
    img = Image(exe)
    uc = img.uc
    if setup:
        setup(img.write)
    regs = _regs()
    if stop is None:
        img.write(SP, struct.pack("<Q", SENTINEL))
        img.write(SENTINEL, b"\xf4")                        # hlt: never executed, only a stop address
        stop = SENTINEL
    for i, value in enumerate(args):
        uc.reg_write(regs[("rcx", "rdx", "r8", "r9")[i]], value)
    for name, value in regs_extra:
        uc.reg_write(regs[name], value)
    for i, value in enumerate(stack_args):
        img.write(SP + 0x28 + i * 8, struct.pack("<Q", value))
    uc.reg_write(regs["rsp"], SP)
    state = {"instructions": 0, "error": None}

    def on_code(uc_, address, size, _):
        state["instructions"] += 1
        if address == stop:
            uc_.emu_stop()

    from unicorn import UC_HOOK_CODE
    uc.hook_add(UC_HOOK_CODE, on_code)
    try:
        uc.emu_start(start, stop, timeout=30000000, count=instruction_max)
    except Exception as exc:                                 # unicorn reports faults as exceptions
        state["error"] = f"{type(exc).__name__}: {exc}"
    out = {n: uc.reg_read(regs[n]) for n in ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "r8", "r9",
                                             "r10", "r11", "r12", "r13", "r14", "r15", "rip")}
    out["instructions"] = state["instructions"]
    out["error"] = state["error"]
    out["image"] = img
    return out


# ------------------------------------------------------------------------------------------ fixtures
def jobrank(rows):
    """rows: {class id: threshold}; 20-byte rows, key +0, threshold +4, eight bonus bytes +0xa..+0x11"""
    data = bytearray()
    for cls, threshold in sorted(rows.items()):
        row = bytearray(20)
        struct.pack_into("<II", row, 0, cls, threshold)
        struct.pack_into("<8B", row, 10, *([1, 2, 3, 4, 5, 6, 7, 8]))
        data += row
    return bytes(data)


def unit(*, cls=1010, subclass=0, serial=0x10001, flag=1, counters=(), bonuses=()):
    b = bytearray(0x4800)
    struct.pack_into("<i", b, U_CLASS, cls)
    struct.pack_into("<h", b, U_SUBCLASS, subclass)
    struct.pack_into("<Q", b, U_SERIAL, serial)
    b[U_FLAG] = flag
    for slot, rank, value in counters:
        struct.pack_into("<I", b, counter_offset(slot, rank), value)
    for i, value in enumerate(bonuses):
        struct.pack_into("<H", b, U_BONUS + i * 2, value)
    return b


def world(job_rows, **kw):
    """the globals a mastery call reads: the JobRank table, the award clamp and the writer's gate"""
    def setup(write):
        write(JOBRANK, jobrank(job_rows))
        write(G_MIN, struct.pack("<q", 0))
        write(G_MAX, struct.pack("<q", 999999))
        write(G_ENABLED, struct.pack("<I", 1))
        write(G_NOTIFY, bytes(0x40))                        # kind != 5: no notification path
        write(G_JOBRANK, struct.pack("<Q", JOBRANK))
        write(G_JOBRANK_COUNT, struct.pack("<I", len(job_rows)))
        write(CHARDAT, bytes(0x4000))
        for address, data in kw.get("regions", ()):
            write(address, data)
        if "unit" in kw:
            write(UNIT, kw["unit"])
    return setup


def counters_of(write_or_read, unit_bytes):
    return [struct.unpack_from("<I", unit_bytes, counter_offset(slot, rank))[0]
            for slot in range(53) for rank in range(6)]


def widen_generic(exe):
    """the class lane's in-place widening of the two generic human-class tests (1000..1310 -> 1000..1999).

    d5lib.newclasses does this at install when no registry (>= 10000) family is used; the mastery checks below use
    it so the sub-class screen's availability gate can be exercised the way a real class mod makes it behave."""
    from d5lib import newclasses
    out = bytearray(exe)
    mon, hum_reg, hum_imm = newclasses._generic_sites(exe, human_sites=False)
    for off in hum_imm:
        out[off:off + 4] = newclasses.GEN_HUM_SPAN.to_bytes(4, "little")
    return bytes(out)


# ------------------------------------------------------------------------------------------ cases
def cases(orig, patched, m):
    """[(name, callable)] -- each returns a detail dict; raises AssertionError on a wrong answer"""
    vanilla = {fam + r: fam for fam in VANILLA for r in range(6)}
    job_rows = {fam + r: 64 * (4 ** r) for fam in VANILLA for r in range(6)}
    job_rows.update({1350 + r: 64 * (4 ** r) for r in range(6)})
    job_rows.update({1360 + r: 64 * (4 ** r) for r in range(6)})

    def standard(setup_unit):
        return world(job_rows, unit=setup_unit)

    results = []

    # 1 -- the mapper: vanilla answers unchanged, configured families get their own slot
    def mapper():
        img = Image(patched)
        wrapper = set()
        for va in m.MAPPER_CALLS:
            off = img.offset(va)
            assert patched[off] == 0xE8, f"{va:#x} is not a call"
            wrapper.add(va + 5 + struct.unpack_from("<i", patched, off + 1)[0])
        assert len(wrapper) == 1, wrapper                     # all 16 sites share one wrapper
        entry = wrapper.pop()
        assert entry == m.section_info(patched)["code"], hex(entry)
        seen = 0
        # every vanilla rank plus ids the extension does not claim; the configured families are checked below
        for cls in list(vanilla) + [0, 1, 999, 1300, 1320, 1999, 2000, 2310, 2460, 9000, 1344, 1349, 1371, 32760]:
            want = run(orig, m.MAPPER, (cls,))
            got = run(patched, entry, (cls,))
            assert not got["error"], f"{cls}: {got['error']}"
            assert got["rax"] & 0xFFFFFFFF == want["rax"] & 0xFFFFFFFF, (cls, hex(got["rax"]), hex(want["rax"]))
            seen += 1
        slots = m.slots([1350, 1360])
        for cls, want in ((1350, slots[1350]), (1355, slots[1350]), (1356, slots[1350]), (1359, slots[1350]),
                          (1360, slots[1360]), (1365, slots[1360]), (1370, 0xFFFFFFFF), (1349, 0xFFFFFFFF),
                          (1000, 0xFFFFFFFF), (2460, 0xFFFFFFFF)):
            got = run(patched, entry, (cls,))["rax"] & 0xFFFFFFFF
            assert got == want, (cls, got, want)
        return dict(sites=len(m.MAPPER_CALLS), comparisons=seen, slots=slots)

    results.append(("mapper-vanilla-identical-and-custom-slots", mapper))

    # 2 -- the real award writer: a custom class gains its own XP, vanilla is byte-identical
    def award():
        detail = {}
        for label, exe in (("unpatched", orig), ("patched", patched)):
            u = unit(cls=1010, counters=[(0, 0, 99)], bonuses=[10, 0, 0, 0, 0, 0, 0, 0])
            got = run(exe, m.WRITER, (UNIT, 1350, 8, 0), setup=standard(u), stack_args=(0,))
            assert not got["error"], got["error"]
            after = got["image"].read(UNIT, 0x3600)
            detail[label] = dict(
                slot47=list(struct.unpack("<6I", after[counter_offset(47):counter_offset(47) + 24])),
                slot0=list(struct.unpack("<6I", after[counter_offset(0):counter_offset(0) + 24])),
                bonuses=list(struct.unpack("<8H", after[U_BONUS:U_BONUS + 16])),
                instructions=got["instructions"])
        assert detail["unpatched"]["slot47"] == [0] * 6
        assert detail["unpatched"]["slot0"] == [99, 0, 0, 0, 0, 0]
        assert detail["patched"]["slot47"] == [8, 0, 0, 0, 0, 0], detail["patched"]["slot47"]
        assert detail["patched"]["slot0"] == [99, 0, 0, 0, 0, 0], detail["patched"]["slot0"]
        assert detail["patched"]["bonuses"] == [10, 0, 0, 0, 0, 0, 0, 0]
        # a vanilla family awards identically before and after the extension
        same = {}
        for label, exe in (("unpatched", orig), ("patched", patched)):
            # the unit's own class differs from the target, so the writer does not run the current-class refresh
            u = unit(cls=2010, counters=[(0, 0, 60)], bonuses=[3, 0, 0, 0, 0, 0, 0, 0])
            got = run(exe, m.WRITER, (UNIT, 1015, 8, 0), setup=standard(u), stack_args=(0,))
            assert not got["error"], got["error"]
            same[label] = got["image"].read(UNIT, 0x3600)
        assert same["unpatched"] == same["patched"], "vanilla award changed"
        # crossing the threshold adds the row's bonus bytes exactly once, and the writer's own completion path
        # carries the 4 left over into the next star (rank-5 target -> family base -> rank 0 first)
        u = unit(cls=1010, counters=[(47, 0, 60)])
        got = run(patched, m.WRITER, (UNIT, 1355, 8, 0), setup=standard(u), stack_args=(0,))
        assert not got["error"], got["error"]
        after = got["image"].read(UNIT, 0x3600)
        assert list(struct.unpack("<6I", after[counter_offset(47):counter_offset(47) + 24])) == [64, 4, 0, 0, 0, 0]
        assert list(struct.unpack("<8H", after[U_BONUS:U_BONUS + 16])) == [1, 2, 3, 4, 5, 6, 7, 8]
        detail["threshold"] = dict(counters=[64, 4, 0, 0, 0, 0], bonuses=[1, 2, 3, 4, 5, 6, 7, 8])
        return detail

    results.append(("award-custom-family-gets-xp-vanilla-identical", award))

    # 3 -- the selected-award gate: a configured sub-class is passed to the writer
    def subclass():
        combined = widen_generic(patched)
        stop = 0x140160E9B                                # the `call 0x14015f480`
        cases_ = [("native class, custom subclass", 1010, 1350, 1350),
                  ("native class, vanilla subclass", 1010, 1030, 1030),
                  ("native class, subclass 0", 1010, 0, 1010),
                  ("native class, unconfigured 1370", 1010, 1370, 1010),
                  ("native class, monster subclass", 1010, 2015, 2015),
                  # the game's own behavior for a unit whose class is outside the vanilla ids is unchanged: the
                  # sub-class id is passed as it stands (the class lane's generic widening owns that test)
                  ("custom class, subclass 0 (unchanged)", 1350, 0, 0)]
        detail = {}
        for name, cls, sub, want in cases_:
            u = unit(cls=cls, subclass=sub)
            got = run(combined, 0x140160E20, (UNIT, 8, 0, 0), stop=stop, setup=standard(u))
            assert not got["error"], got["error"]
            assert got["rdx"] & 0xFFFFFFFF == want, (name, hex(got["rdx"]), hex(want))
            detail[name] = got["rdx"] & 0xFFFFFFFF
        return detail

    results.append(("subclass-passed-to-writer", subclass))

    # 4 -- the sub-class screen: our families follow the vanilla 47, within the screen's row capacity
    def listed():
        fams = [1350, 1360]
        array = bytearray(0x70 + 48 * 4)                     # rbp-0x70 .. rbp+0x50
        for i, fam in enumerate(VANILLA):
            struct.pack_into("<i", array, i * 4, fam)
        rbp = ARRAY + 0x70

        def setup(count):
            def inner(write):
                write(ARRAY, bytes(array))
                screen = bytearray(0x8FC0)
                struct.pack_into("<i", screen, m.COUNT_OFFSET, count)
                write(SCREEN, screen)
            return inner

        detail = {"vanilla": 0, "extended": {}, "row_cap": {}}
        for index in range(47):
            want = struct.unpack_from("<i", array, index * 4)[0]
            got = run(patched, m.FETCH_SITE, (0,), stop=0x140470BD5, setup=setup(0),
                      regs_extra=(("rsi", SCREEN), ("rbp", rbp), ("r13", index)))
            assert not got["error"], got["error"]
            assert got["r15"] & 0xFFFFFFFF == want, (index, got["r15"] & 0xFFFFFFFF, want)
            vanilla = run(orig, m.FETCH_SITE, (0,), stop=0x140470BD5, setup=setup(0),
                          regs_extra=(("rsi", SCREEN), ("rbp", rbp), ("r13", index)))
            assert vanilla["r15"] == got["r15"], f"vanilla index {index} changed"
            detail["vanilla"] += 1
        for index, want in ((47, fams[0]), (48, fams[1]), (49, 0), (60, 0)):
            got = run(patched, m.FETCH_SITE, (0,), stop=0x140470BD5, setup=setup(0),
                      regs_extra=(("rsi", SCREEN), ("rbp", rbp), ("r13", index)))
            assert not got["error"], got["error"]
            assert got["r15"] & 0xFFFFFFFF == want, (index, got["r15"] & 0xFFFFFFFF, want)
            detail["extended"][index] = got["r15"] & 0xFFFFFFFF
        for index in (47, 48):
            got = run(patched, m.FETCH_SITE, (0,), stop=0x140470BD5, setup=setup(47),
                      regs_extra=(("rsi", SCREEN), ("rbp", rbp), ("r13", index)))
            assert not got["error"], got["error"]
            assert got["r15"] & 0xFFFFFFFF == 0, got["r15"]
            detail["row_cap"][index] = 0
        # the loop bound now covers our indices, and the native availability gate accepts a custom family once the
        # class lane's generic widening is in place (d5lib.newclasses)
        combined = widen_generic(patched)
        off = Image(combined).offset(m.BOUND_SITE)
        assert combined[off + 3] == 0x2F + len(fams), combined[off:off + 4].hex()
        gate = {}
        for cls in (1010, 1320, 1350, 1355, 1360, 1370):
            got = run(combined, m.GATE, (cls,), setup=_gate_setup(combined))
            assert not got["error"], got["error"]
            gate[cls] = got["rax"] & 0xFF
        # the configured families pass the native availability gate; 1370 (inside the class lane's widened
        # 1000..1999 window but with no char.dat row) also passes the gate, so the list row is what filters it out
        assert gate[1010] == 1 and gate[1350] == 1 and gate[1355] == 1 and gate[1360] == 1, gate
        before = run(orig, m.GATE, (1350,), setup=_gate_setup(orig))
        detail["gate"] = gate
        detail["gate_unwidened_1350"] = before["rax"] & 0xFF
        detail["bound"] = 0x2F + len(fams)
        return detail

    results.append(("subclass-list-extended", listed))
    return results


def job_table(families):
    """the JobRank rows a mastery call reads: every vanilla family's six ranks plus the configured ones"""
    rows = {fam + r: 64 * (4 ** r) for fam in VANILLA for r in range(6)}
    for fam in families:
        rows.update({fam + r: 64 * (4 ** r) for r in range(6)})
    return rows


def cases_more(orig, patched, m):
    """persistence, several families at once, an untouched vanilla save and the D4 pilot family"""
    results = []

    # 5 -- progress lives in the unit record the save stores verbatim, so it round-trips
    def persistence():
        table = job_table([1350, 1360])
        detail = {}
        # award through the real writer on a unit that already has progress in both spare slots
        u = unit(cls=1010, counters=[(47, 0, 10), (48, 3, 7)])
        got = run(patched, m.WRITER, (UNIT, 1350, 8, 0), setup=world(table, unit=u), stack_args=(0,))
        assert not got["error"], got["error"]
        saved = got["image"].read(UNIT, 0x4750)              # the record bytes a save would hold
        assert struct.unpack_from("<I", saved, counter_offset(47, 0))[0] == 18, saved[0x30A4:0x30C0].hex()
        assert struct.unpack_from("<I", saved, counter_offset(48, 3))[0] == 7

        def reloaded(write):
            world(table)(write)
            write(UNIT, saved)                               # exactly the bytes that were written out

        detail["saved_1350_rank0"] = struct.unpack_from("<I", saved, counter_offset(47, 0))[0]
        for cls, want in ((1350, 18), (1351, 0), (1363, 7), (1365, 0)):
            got = run(patched, m.READER, (UNIT, cls, 0, 0), setup=reloaded)
            assert not got["error"], got["error"]
            assert got["rax"] & 0xFFFFFFFF == want, (cls, hex(got["rax"]), want)
            detail[f"reloaded_{cls}"] = got["rax"] & 0xFFFFFFFF
            before = run(orig, m.READER, (UNIT, cls, 0, 0), setup=reloaded)
            assert before["rax"] & 0xFFFFFFFF == 0, (cls, hex(before["rax"]))
        # a vanilla read is the same before and after the extension, on the same saved bytes
        for cls in (1010, 1015, 2010):
            after = run(patched, m.READER, (UNIT, cls, 0, 0), setup=reloaded)["rax"] & 0xFFFFFFFF
            before = run(orig, m.READER, (UNIT, cls, 0, 0), setup=reloaded)["rax"] & 0xFFFFFFFF
            assert after == before, (cls, after, before)
            detail[f"vanilla_{cls}"] = after
        # a vanilla-only record's spare slots stay zero, so an old save reads "no progress"
        plain = unit(cls=1010, counters=[(0, 0, 55), (1, 2, 9)])
        got = run(patched, m.READER, (UNIT, 1350, 0, 0), setup=world(table, unit=plain))
        assert got["rax"] & 0xFFFFFFFF == 0, hex(got["rax"])
        detail["vanilla_save_custom_reads"] = 0
        # ... and the side table (inactive codec for a seventh family and beyond) round-trips its bytes
        detail["side_table"] = _side_table_round_trip()
        return detail

    results.append(("persistence-record-round-trip-and-side-table", persistence))

    # 6 -- six configured families at once, each in its own spare slot, no cross-talk
    def multifamily():
        fams = list(range(1350, 1410, 10))
        six = m.build_patch(orig, fams)
        entry = m.section_info(six)["code"]
        table = job_table(fams)
        slots = m.slots(fams)
        detail = {"slots": slots, "mapper": {}, "awarded": {}}
        for fam in fams:
            for cls in (fam, fam + 5):
                got = run(six, entry, (cls,))
                assert not got["error"], got["error"]
                assert got["rax"] & 0xFFFFFFFF == slots[fam], (cls, hex(got["rax"]), slots[fam])
            detail["mapper"][fam] = slots[fam]
        # one award per family, each on the record the previous award left behind
        record = unit(cls=1010)
        for fam in fams:
            got = run(six, m.WRITER, (UNIT, fam, 3, 0), setup=world(table, unit=record), stack_args=(0,))
            assert not got["error"], got["error"]
            record = got["image"].read(UNIT, 0x4750)
        for fam in fams:
            slot = slots[fam]
            counters = struct.unpack("<6I", record[counter_offset(slot):counter_offset(slot) + 24])
            assert list(counters) == [3, 0, 0, 0, 0, 0], (fam, counters)
            detail["awarded"][fam] = list(counters)
            got = run(six, m.READER, (UNIT, fam, 0, 0),
                      setup=lambda write, r=record: (world(table)(write), write(UNIT, r)))
            assert got["rax"] & 0xFFFFFFFF == 3, (fam, hex(got["rax"]))
        # the seventh family has no spare slot to land in
        try:
            m.build_patch(orig, fams + [1410])
        except ValueError as exc:
            assert "at most 6" in str(exc), exc
        else:
            raise AssertionError("a seventh family was accepted")
        detail["seventh_family"] = "refused"
        return detail

    results.append(("six-custom-families-independent-slots", multifamily))

    # 7 -- a vanilla-only save is untouched by the extension
    def vanilla_save():
        table = job_table([1350, 1360])
        session = [(1010, 5), (1020, 5), (1035, 5), (1150, 5), (2010, 5), (2100, 5)]
        records = {}
        for label, exe in (("unpatched", orig), ("patched", patched)):
            record = unit(cls=1010, counters=[(0, 0, 40)])
            for cls, amount in session:
                got = run(exe, m.WRITER, (UNIT, cls, amount, 0),
                          setup=world(table, unit=record), stack_args=(0,))
                assert not got["error"], got["error"]
                record = got["image"].read(UNIT, 0x4750)
            records[label] = record
        assert records["unpatched"] == records["patched"], "a vanilla save changed under the extension"
        spare = struct.unpack("<36I", records["patched"][counter_offset(47):counter_offset(53)])
        assert spare == (0,) * 36, spare
        return dict(identical=hashlib.sha256(records["patched"]).hexdigest(),
                    session=[f"{cls}+{amount}" for cls, amount in session],
                    spare_slots_zero=list(spare[:6]))

    results.append(("vanilla-only-save-untouched", vanilla_save))

    # 8 -- the D4 Armor Knight pilot family (1350..1355) end to end
    def d4_armor_knight():
        family = 1350
        one = m.build_patch(orig, [family])
        entry = m.section_info(one)["code"]
        table = job_table([family])
        record = unit(cls=1010)                              # a unit of the vanilla template class 1150's family
        detail = {"mapper": {}, "award": {}, "read": {}}
        # one award per rank of the family, 4 XP each: every award now starts at the earliest incomplete star, so all
        # 24 points land in star 1 and the five higher stars stay empty
        want = [4 * 6, 0, 0, 0, 0, 0]
        for delta in range(6):
            cls = family + delta
            got = run(one, entry, (cls,))
            assert got["rax"] & 0xFFFFFFFF == m.slots([family])[family], (cls, hex(got["rax"]))
            detail["mapper"][cls] = got["rax"] & 0xFFFFFFFF
            got = run(one, m.WRITER, (UNIT, cls, 4, 0), setup=world(table, unit=record), stack_args=(0,))
            assert not got["error"], got["error"]
            record = got["image"].read(UNIT, 0x4750)         # the game's own live record, carried forward
            detail["award"][cls] = list(struct.unpack("<6I", record[counter_offset(47):
                                                                   counter_offset(47) + 24]))
        counters = struct.unpack("<6I", record[counter_offset(47):counter_offset(47) + 24])
        assert list(counters) == want, counters
        assert record[counter_offset(48):counter_offset(48) + 24] == bytes(24)   # no neighbouring slot
        for delta in range(6):
            cls = family + delta
            got = run(one, m.READER, (UNIT, cls, 0, 0),
                      setup=lambda write, r=record: (world(table)(write), write(UNIT, r)))
            assert not got["error"], got["error"]
            assert got["rax"] & 0xFFFFFFFF == want[delta], (cls, hex(got["rax"]), want[delta])
            detail["read"][cls] = want[delta]
        # the same six-rank award sequence on a vanilla family keeps the game's own rank cascade, byte-identical
        # before and after the extension (the family-base rewrite never touches a vanilla id)
        vanilla_family = 1150
        slot = run(orig, m.MAPPER, (vanilla_family,))["rax"] & 0xFFFFFFFF
        cascaded = [4 * (6 - delta) for delta in range(6)]
        same = {}
        for label, exe in (("unpatched", orig), ("patched", one)):
            rec = unit(cls=1010)
            for delta in range(6):
                got = run(exe, m.WRITER, (UNIT, vanilla_family + delta, 4, 0),
                          setup=world(table, unit=rec), stack_args=(0,))
                assert not got["error"], got["error"]
                rec = got["image"].read(UNIT, 0x4750)
            same[label] = rec
        assert same["unpatched"] == same["patched"], "a vanilla family's award changed"
        assert list(struct.unpack("<6I", same["patched"][counter_offset(slot):counter_offset(slot) + 24])) \
            == cascaded
        detail["vanilla_family_identical"] = dict(family=vanilla_family, slot=slot, counters=cascaded)
        # the unpatched build awards nothing at all to the pilot family's ranks
        rec = unit(cls=1010)
        for delta in range(6):
            got = run(orig, m.WRITER, (UNIT, family + delta, 4, 0), setup=world(table, unit=rec), stack_args=(0,))
            assert not got["error"], got["error"]
            rec = got["image"].read(UNIT, 0x4750)
        assert struct.unpack("<6I", rec[counter_offset(47):counter_offset(47) + 24]) == (0,) * 6
        detail["unpatched_awards_nothing"] = True
        # the pilot family's ranks also pass the selected-award sub-class gate
        for cls in range(family, family + 6):
            got = run(one, 0x140160E20, (UNIT, 8, 0, 0), stop=0x140160E9B,
                      setup=world(table, unit=unit(cls=1010, subclass=cls)))
            assert not got["error"], got["error"]
            assert got["rdx"] & 0xFFFFFFFF == cls, (cls, hex(got["rdx"]))
        detail["subclass_gate"] = list(range(family, family + 6))
        # and the sub-class screen offers the family at index 47 of its list
        array = bytearray(0x70 + 48 * 4)
        for i, fam in enumerate(VANILLA):
            struct.pack_into("<i", array, i * 4, fam)

        def screen(write):
            write(ARRAY, bytes(array))
            write(SCREEN, bytes(0x8FC0))

        got = run(one, m.FETCH_SITE, (0,), stop=0x140470BD5, setup=screen,
                  regs_extra=(("rsi", SCREEN), ("rbp", ARRAY + 0x70), ("r13", 47)))
        assert got["r15"] & 0xFFFFFFFF == family, hex(got["r15"])
        detail["screen_index_47"] = got["r15"] & 0xFFFFFFFF
        return detail

    results.append(("d4-armor-knight-family-1350-1355", d4_armor_knight))

    # 9 -- award order: one star at a time with overflow carrying, on every path that reaches the writer
    def award_order():
        one = m.build_patch(orig, [1350, 1360])
        table = job_table([1350, 1360])
        slot = m.slots([1350, 1360])[1350]

        def writer(exe, target, amount, counters=(), bonuses=()):
            """the real writer, entered as its own callers enter it (unit record in rcx, target id in edx)"""
            u = unit(cls=1010, counters=list(counters), bonuses=list(bonuses))
            got = run(exe, m.WRITER, (UNIT, target, amount, 0), setup=world(table, unit=u), stack_args=(0,))
            assert not got["error"], got["error"]
            record = got["image"].read(UNIT, 0x3600)
            return (list(struct.unpack("<6I", record[counter_offset(slot):counter_offset(slot) + 24])),
                    list(struct.unpack("<8H", record[U_BONUS:U_BONUS + 16])), record)

        detail = {}
        # a. a rank-5 target with a small award grows star 1 only (before the fix: [7,7,7,7,7,7])
        got = writer(one, 1355, 7)
        assert got[0] == [7, 0, 0, 0, 0, 0], got[0]
        assert got[1] == [0] * 8, got[1]
        detail["rank5_partial"] = got[0]
        # the same call on the unpatched build writes nothing at all: the award never reaches the counters
        before = writer(orig, 1355, 7)
        assert before[0] == [0] * 6, before[0]
        # b. completion overflow: 100 into an empty star 1 fills it (threshold 64) and carries 36 into star 2
        got = writer(one, 1355, 100)
        assert got[0] == [64, 36, 0, 0, 0, 0], got[0]
        assert got[1] == [1, 2, 3, 4, 5, 6, 7, 8], got[1]          # one completion bonus, once
        detail["completion_overflow"] = got[0]
        # c. a second completion in the same award carries further: 400 -> 64, 256 (threshold), 80
        got = writer(one, 1355, 400)
        assert got[0] == [64, 256, 80, 0, 0, 0], got[0]
        assert got[1] == [2, 4, 6, 8, 10, 12, 14, 16], got[1]      # two rows' bonuses, once each
        detail["second_overflow"] = got[0]
        # d. an already complete star is walked over without touching it, and its overflow still carries
        got = writer(one, 1355, 8, counters=[(47, 0, 64), (47, 1, 250)])
        assert got[0] == [64, 256, 2, 0, 0, 0], got[0]
        assert got[1] == [1, 2, 3, 4, 5, 6, 7, 8], got[1]          # no second bonus for the old completion
        detail["walk_complete_star"] = got[0]
        # e. a record that already carries parallel partial bars keeps them; only the earliest incomplete star moves
        got = writer(one, 1355, 8, counters=[(47, 0, 60), (47, 1, 10), (47, 2, 5)])
        assert got[0] == [64, 14, 5, 0, 0, 0], got[0]
        detail["stale_parallel_retained"] = got[0]
        # f. the explicit award call 0x1401517FC (quest/reward XP, bypasses the selected-award wrapper) is covered,
        #    because the rewrite happens inside the writer's own mapper call
        u = unit(cls=1010)
        got = run(one, 0x1401517FC, (UNIT, 1355, 7, 1), stop=0x140151801,
                  setup=world(table, unit=u, regions=[(SP + 0x20, b"\x01")]))
        assert not got["error"], got["error"]
        record = got["image"].read(UNIT, 0x3600)
        explicit = list(struct.unpack("<6I", record[counter_offset(slot):counter_offset(slot) + 24]))
        assert explicit == [7, 0, 0, 0, 0, 0], explicit
        detail["explicit_call_0x1517fc"] = explicit
        # the same site on a vanilla target keeps the native cascade, byte-identical patched vs unpatched
        vanilla = {}
        for label, exe in (("unpatched", orig), ("patched", one)):
            u = unit(cls=1010)
            got = run(exe, 0x1401517FC, (UNIT, 1155, 7, 1), stop=0x140151801,
                      setup=world(table, unit=u, regions=[(SP + 0x20, b"\x01")]))
            assert not got["error"], got["error"]
            vanilla[label] = got["image"].read(UNIT, 0x4750)
        assert vanilla["unpatched"] == vanilla["patched"], "the explicit vanilla award path changed"
        vslot = run(orig, m.MAPPER, (1155,))["rax"] & 0xFFFFFFFF
        assert list(struct.unpack("<6I", vanilla["patched"][counter_offset(vslot):counter_offset(vslot) + 24])) \
            == [7] * 6
        detail["explicit_vanilla"] = dict(slot=vslot, counters=[7] * 6)
        # g. the selected-subclass path: a vanilla-class unit with custom sub-class 1355, run through the game's own
        #    selected-award wrapper (0x140160E20) into the real writer
        u = unit(cls=1010, subclass=1355)
        got = run(one, 0x140160E20, (UNIT, 7, 0, 0), stop=0x140160EA0, setup=world(table, unit=u))
        assert not got["error"], got["error"]
        record = got["image"].read(UNIT, 0x3600)
        subclass = list(struct.unpack("<6I", record[counter_offset(slot):counter_offset(slot) + 24]))
        assert subclass == [7, 0, 0, 0, 0, 0], subclass
        detail["selected_subclass_1355"] = subclass
        # h. the selected wrapper's own-class branch for an id above 1310 is NOT widened by this lane: its bound is
        #    the register pair (esi=0x122, edi=0x136), and the class lane's generic widening only patches immediates.
        #    Both builds therefore pass target 0 (nothing awarded) here; the own-class award that matters is the
        #    explicit call in (f). Asserted so the limit stays visible instead of being mistaken for proof.
        own = {}
        for label, exe in (("unpatched", orig), ("patched", one)):
            u = unit(cls=1355, subclass=0)
            got = run(exe, 0x140160E20, (UNIT, 7, 0, 0), stop=0x140160E9B, setup=world(table, unit=u))
            assert not got["error"], got["error"]
            own[label] = got["rdx"] & 0xFFFFFFFF
        assert own["unpatched"] == own["patched"] == 0, own
        detail["own_class_selected_wrapper_target"] = own["patched"]
        detail["own_class_path_note"] = "register bound 0x122/0x136 is the class lane's; explicit call (f) is the award path"
        return detail

    results.append(("award-order-one-star-at-a-time", award_order))

    # 10 -- the wrapper as it was before this round (rebuilt from the previous source) reproduces the owner's report
    def before_fix_cascade():
        def without_award_order(fams, table=None):      # the pre-fix signature is (fams); the port adds the table
            lines = ["    push rbx", "    sub rsp, 0x20", "    mov ebx, ecx", f"    call {m.MAPPER:#x}",
                     "    cmp eax, -1", "    jne mp_done"]
            labels = []
            for i, fam in enumerate(fams):
                lines += [f"    lea edx, [rbx - {fam}]", "    cmp edx, 9", f"    jbe mp_{i}"]
                labels.append((f"mp_{i}:", f"    mov eax, {m.SLOT_FIRST + i}"))
            lines += ["    mov eax, -1", "    jmp mp_done"]
            for label, body in labels:
                lines += [label, body, "    jmp mp_done"]
            lines += ["mp_done:", "    add rsp, 0x20", "    pop rbx", "    ret"]
            return "\n".join(lines)

        saved = m._mapper_src
        m._mapper_src = without_award_order
        try:
            old = m.build_patch(orig, [1350, 1360])
        finally:
            m._mapper_src = saved
        table = job_table([1350, 1360])

        def award(exe, amount, counters=()):
            u = unit(cls=1010, counters=list(counters))
            got = run(exe, m.WRITER, (UNIT, 1355, amount, 0), setup=world(table, unit=u), stack_args=(0,))
            assert not got["error"], got["error"]
            record = got["image"].read(UNIT, 0x3600)
            return list(struct.unpack("<6I", record[counter_offset(47):counter_offset(47) + 24]))

        detail = {}
        for label, amount, counters, want in (
                ("partial", 7, (), [7] * 6),
                ("one_completion", 100, (), [64, 36, 36, 36, 36, 36]),
                ("two_completions", 400, (), [64, 256, 80, 80, 80, 80]),
                ("stale_parallel", 8, ((47, 0, 60), (47, 1, 10), (47, 2, 5)), [64, 14, 9, 4, 4, 4])):
            got = award(old, amount, counters)
            assert got == want, (label, got, want)
            detail[label] = got
        detail["note"] = "the pre-fix wrapper is rebuilt here for the comparison; the fixed build is case 9"
        return detail

    results.append(("prefix-wrapper-reproduces-the-cascade", before_fix_cascade))
    return results


def _side_table_round_trip():
    """the inactive companion codec: bytes in, the same snapshot out, and every mismatch refused"""
    from d5lib import classmastery as cm
    registry = cm.Registry(families=(10000, 11000, 12000), source_digest=bytes(range(32)))
    snapshot = cm.Snapshot(
        generation=7, native_digest=b"\x11" * 32,
        units=(cm.Unit(serial=0x10001, subclass=11003,
                       progress=(cm.Progress(10000, (10, 20, 30, 40, 50, 60), 0b101010),
                                 cm.Progress(11000, (1, 2, 3, 4, 5, 6), 0)),
                       completion_bonuses=(7, 0, 0, 0, 0, 0, 0, 0)),
               cm.Unit(serial=0x10002, progress=(cm.Progress(12000, (9, 0, 0, 0, 0, 0), 0),))))
    blob = cm.encode(snapshot, registry)
    assert cm.decode(blob, registry, native_digest=b"\x11" * 32, generation=7) == snapshot
    assert cm.encode(cm.decode(blob, registry, native_digest=b"\x11" * 32, generation=7), registry) == blob
    bad = bytearray(blob)
    bad[cm.HEADER_SIZE + 16] ^= 0x01                        # one counter byte
    for kwargs in (dict(native_digest=b"\x11" * 32, generation=7),
                   dict(native_digest=b"\x22" * 32, generation=7),
                   dict(native_digest=b"\x11" * 32, generation=8)):
        try:
            cm.decode(bytes(bad) if kwargs["native_digest"] == b"\x11" * 32 else blob,
                      registry, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"the codec accepted {kwargs}")
    try:
        cm.Registry(families=(1350,), source_digest=bytes(32))
    except ValueError as exc:
        assert "community family" in str(exc), exc
    else:
        raise AssertionError("the side table claimed a 1000-range family the native slots own")
    return dict(bytes=len(blob), units=len(snapshot.units), families=len(registry.families),
                native_range_refused=True, tamper_refused=True)


# ------------------------------------------------------------------------------------------ site-entry ABI
FLAG_READERS = ("j", "set", "cmov", "adc", "sbb", "loop", "lahf", "sahf")


def flags_consumed_within(exe, start, limit=24):
    """instructions up to the next legal flag clobber that would observe the (replaced) flags"""
    import capstone
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    eflags = capstone.x86_const.X86_REG_EFLAGS
    seen = []
    va = start
    for _ in range(limit):
        raw = pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, 15)
        ins = next(md.disasm(raw, va), None)
        assert ins is not None, hex(va)
        reads, writes = ins.regs_access()
        if eflags in writes or ins.mnemonic in ("call", "ret", "jmp"):
            return seen                                      # flags are dead from here on
        if eflags in reads or ins.mnemonic.startswith(FLAG_READERS):
            seen.append(f"{va:#x} {ins.mnemonic} {ins.op_str}")
            return seen
        va += ins.size
    return seen


def abi_cases(orig, patched, m):
    """every patched site entered exactly as its caller enters it"""
    import abi_engine_mastery as abi
    results = []

    # A -- the 16 mapper CALL sites
    def abi_mapper():
        info = m.section_info(patched)
        fams = [1350, 1360]

        def expected_r10(site, cls, stub_answer):
            """the wrapper rewrites the caller's r10 only when it is returning to the award writer, so only there
            does a configured family's target become the family base; everywhere else the stub's clobber survives
            (the wrapper never goes near r10)"""
            if site == m.WRITER_MAPPER_SITE and stub_answer == -1 and m.in_family(cls, fams):
                return m.award_target(cls, fams)
            return abi.TRASH["r10"]

        runs, worst = [], 0
        for site in m.MAPPER_CALLS:
            for cls, stub_answer, want in ((1350, -1, 47), (1355, -1, 47), (1300, -1, 0xFFFFFFFF), (1010, 12, 12)):
                want_r10 = expected_r10(site, cls, stub_answer)
                got = abi.execute(patched, info, site, kind="call",
                                  stubs=[(m.MAPPER, abi.clobbering_stub(stub_answer))],
                                  regs={"rcx": cls}, expect_args={"rcx": cls},
                                  answer={"rax": want, "r10": want_r10})
                answer = got["answer"]
                runs.append(dict(site=hex(site), cls=cls, want=want, got=answer["rax"],
                                 r10=answer["r10"], want_r10=want_r10,
                                 instructions=got["instructions"], calls=got["calls"]))
                worst = max(worst, got["instructions"])
        assert all(r["got"] == (r["want"] & 0xFFFFFFFF) for r in runs), runs
        assert all(r["r10"] == r["want_r10"] for r in runs), [r for r in runs if r["r10"] != r["want_r10"]]
        writer = [r for r in runs if r["site"] == hex(m.WRITER_MAPPER_SITE)]
        assert {r["cls"]: r["r10"] for r in writer} == {1350: 1350, 1355: 1350, 1300: abi.TRASH["r10"],
                                                         1010: abi.TRASH["r10"]}, writer
        return dict(sites=len(m.MAPPER_CALLS), runs=len(runs), max_instructions=worst,
                    answer_in_rax=True, writer_site=hex(m.WRITER_MAPPER_SITE),
                    writer_r10={r["cls"]: r["r10"] for r in writer},
                    other_sites_r10_untouched=all(r["r10"] == abi.TRASH["r10"] for r in runs
                                                  if r["site"] != hex(m.WRITER_MAPPER_SITE)
                                                  or r["cls"] in (1300, 1010)),
                    wrapper=hex(info["code"]), first=runs[:4])

    results.append(("abi-mapper-sites-call-entry", abi_mapper))

    # B -- the sub-class screen's family fetch (leaf: it must return to site+5 with RSP restored)
    def abi_fetch():
        info = m.section_info(patched)
        array = bytearray(0x70 + 48 * 4)
        for i, fam in enumerate(VANILLA):
            struct.pack_into("<i", array, i * 4, fam)

        def fixture(count):
            def inner(write):
                write(ARRAY, bytes(array))
                screen = bytearray(0x8FC0)
                struct.pack_into("<i", screen, m.COUNT_OFFSET, count)
                write(SCREEN, screen)
            return inner

        runs = []
        for index, count, want in ((0, 0, 1010), (25, 0, 1260), (26, 0, 2010), (46, 0, 2210), (47, 0, 1350),
                                   (48, 0, 1360), (49, 0, 0), (60, 0, 0), (47, 47, 0), (48, 47, 0)):
            # r15d is the instruction's own destination, so it is the only nonvolatile free to change
            state = dict(abi.poison_nonvolatiles())
            state.update({"rbp": ARRAY + 0x70, "rsi": SCREEN, "r13": index})
            got = abi.execute(patched, info, m.FETCH_SITE, kind="call", fixture=fixture(count),
                              regs=state, preserve={k: v for k, v in state.items() if k != "r15"},
                              outputs=("r15",), answer={"r15": want})
            runs.append(dict(index=index, rows_in_use=count, want=want, got=got["answer"]["r15"],
                             instructions=got["instructions"]))
        return dict(site=hex(m.FETCH_SITE), runs=runs, xmm_preserved=True,
                    writes_outside_stack=0, r15_is_the_only_output=True)

    results.append(("abi-fetch-site-call-entry", abi_fetch))

    # C -- the selected-award sub-class gate, entered by jump and left by jump
    def abi_subclass():
        info = m.section_info(patched)
        poison = abi.poison_nonvolatiles()
        # the native values at 0x140160E79: rsi 0x122, rdi 0x136, ebx 0x3e8 (scratch), r10 the unit,
        # rdx/rcx the unit's class and sub-class, r8b/r9b the wrapper's own flags
        base_regs = dict(poison)
        base_regs.update({"rsi": 0x122, "rdi": 0x136, "rbx": 0x3E8, "r10": UNIT,
                          "r8": 0x37, "r9": 0x26, "r11": 0x11111111})
        preserve = {k: v for k, v in base_regs.items() if k != "r15"}
        runs = []
        for sub, own, exit_address in ((1350, 1010, m.SUBCLASS_ACCEPT), (1355, 1010, m.SUBCLASS_ACCEPT),
                                       (1360, 1010, m.SUBCLASS_ACCEPT), (1010, 1010, m.SUBCLASS_ACCEPT),
                                       (2015, 1010, m.SUBCLASS_ACCEPT), (1370, 1010, m.SUBCLASS_REJECT),
                                       (1349, 1010, m.SUBCLASS_REJECT), (2460, 1010, m.SUBCLASS_REJECT),
                                       (0, 1010, m.SUBCLASS_REJECT)):
            regs = dict(base_regs)
            regs.update({"rcx": sub, "rdx": own})
            got = abi.execute(patched, info, m.SUBCLASS_SITE, kind="jump", regs=regs,
                              stop=(m.SUBCLASS_ACCEPT, m.SUBCLASS_REJECT),
                              preserve=dict(preserve, rcx=sub, rdx=own), answer={})
            assert got["stopped_at"] == hex(exit_address), (sub, got["stopped_at"], hex(exit_address))
            runs.append(dict(subclass=sub, exit=got["stopped_at"],
                             accept=exit_address == m.SUBCLASS_ACCEPT, instructions=got["instructions"]))
        # the replaced instructions set no flags anything reads, so the stub's own CMP is harmless
        flags = dict(accept=flags_consumed_within(patched, m.SUBCLASS_ACCEPT),
                     reject=flags_consumed_within(patched, m.SUBCLASS_REJECT),
                     fetch=flags_consumed_within(patched, m.FETCH_SITE + 5))
        assert not any(flags.values()), flags
        assert not flags_consumed_within(patched, m.FETCH_SITE + 5), flags
        return dict(site=hex(m.SUBCLASS_SITE), runs=runs, flags_unread=flags,
                    rsp_unchanged=True, no_call_edges=True)

    results.append(("abi-subclass-gate-jump-entry", abi_subclass))
    return results


def _gate_setup(exe):
    """the availability gate's own helpers (DLC gate, class -> index) are not what this proof is about: they are
    replaced in the emulated copy by always-true stubs, so the range test and the unlock bitmap are what runs."""
    def setup(write):
        write(0x140141DE0, b"\xb0\x01\xc3")                 # mov al, 1 / ret
        write(0x14008E0B0, b"\x31\xc0\xc3")                 # xor eax, eax / ret (index 0)
        write(0x140A1A4C4, b"\x01")                         # the mask for index 0: the game's own flag 0
        write(0x144FCCB0E, b"\xff" * 0x2000)                # the unlock flag bytes: every flag set
    return setup


def main():
    import hashlib
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", type=Path, required=True,
                    help="path to an offline copy of the pinned original executable")
    ap.add_argument("--build-only", action="store_true", help="build and validate the patch without importing Unicorn")
    ap.add_argument("--abi", "--site-entry", action="store_true",
                    help="additionally enter every patched .d5cm site the way its caller does")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    from d5lib import masteryext as m
    original = args.original.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, "not the pinned original exe"
    fams = [1350, 1360]
    patched = m.build_patch(original, fams)
    info = m.section_info(patched)
    build = dict(families=fams, slots=m.slots(fams), section=info["section"], base=hex(info["base"]),
                 size=info["size"], original_sha256=ORIGINAL_SHA,
                 patched_sha256=hashlib.sha256(patched).hexdigest(),
                 mapper_sites=len(m.MAPPER_CALLS))
    print(f"section {info['section']} at {info['base']:#x}, {info['size']} bytes; "
          f"{len(m.MAPPER_CALLS)} mapper sites; slots {m.slots(fams)}")
    if args.build_only:
        build["note"] = "fixtures and patch built; Unicorn not imported"
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(build, indent=1) + "\n")
        return 0
    checks, passed = [], True
    plan = cases(original, patched, m) + cases_more(original, patched, m)
    if args.abi:
        plan += abi_cases(original, patched, m)
    for name, fn in plan:
        try:
            detail = fn()
            checks.append(dict(name=name, ok=True, detail=_jsonable(detail)))
            print(f"PASS {name}")
        except Exception as exc:
            passed = False
            import traceback
            checks.append(dict(name=name, ok=False, error=f"{type(exc).__name__}: {exc}",
                               trace=traceback.format_exc().splitlines()[-6:]))
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    report = dict(mode="abi-site-entry" if args.abi else "behavior", build=build, checks=checks,
                  passed=passed,
                  limitations=["Original-game helpers that this proof replaces (DLC gate, class -> index, and in "
                               "--abi mode the original mapper and callee) are stubs in the emulated copy.",
                               "Executed paths only; Windows unwind and native gameplay are not executed. The "
                               ".d5cm unwind records are checked structurally (tests + exepatch), not by an "
                               "exception dispatch.",
                               "The sub-class screen's row capacity (47) is enforced by the extension's own guard; "
                               "a full screen lists the vanilla classes only.",
                               "The companion side-table codec (d5lib.classmastery) is exercised as bytes only; "
                               "nothing installs or reads it."])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    print(f"[{report['mode']}] {sum(c['ok'] for c in checks)}/{len(checks)} checks passed")
    return 0 if passed else 1


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


if __name__ == "__main__":
    sys.exit(main())
