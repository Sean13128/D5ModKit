"""Offline proof of the packed mastery **award** path (section .d5pm, P2e step 2).

Everything runs in Unicorn over the *pinned original* exe (sha256 49a7530b...db282ce)
plus this extension's own section; no game process, install, save or live state is
touched.  The award is always the game's own writer (0x14015F480) executed from its
own entry, so its mapper call at 0x14015F500 goes through the hook exactly as it does
in the game, and every counter, bonus word, unlock call and sub-class field it writes
is written by the game's code.

Proven here, per check:

  award-one-family        1, 7 and 45 configured families: a rank-5 target with 7 XP
                          puts 7 into star 1 only ([7,0,0,0,0,0] in slot 52) and the
                          unpatched build awards nothing at all.
  award-six-ranks         six awards of 4 XP, one per rank id 1350..1355, move star 1
                          only ([24,0,0,0,0,0]): STARS-FIX's one-star-at-a-time order
                          through the packed mapper.
  award-completion        a completing award fills star 1, adds the eight JobRank bonus
                          words once, and carries its overflow into star 2.
  award-two-units         two units keep independent staged counters and pools.
  award-pool-full         a full pool answers -1 and the writer then writes *nothing*:
                          the 0x4800-byte record is byte-identical (counters, bonus
                          words, sub-class, unlock fields) and the reader still says 0.
  award-capacity-first    a switch that would not fit is refused before any side effect
                          (same record identity), so no award can be lost half-applied.
  award-round-trip        award -> switch to another family -> switch back restores the
                          exact counters; the game's own reader reports them from the
                          record bytes a save would hold, after a "reload".
  unlock-custom-noop      mark_character_seen (0x1C62A0) for a packed family's rank id
                          writes nothing at all (memory-write trace) and the global flag
                          bitmap is unchanged; a vanilla id still sets its bit, patched
                          and unpatched identically.
  award-vanilla-identical a vanilla family's award through the writer leaves the record
                          byte-identical, patched vs unpatched.

`--build-only` builds and validates the patch without importing Unicorn.
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
UNIT, JOBRANK, LOWMEM, FLAGS = 0x400000000, 0x400300000, 0x400400000, 0x400500000
SENTINEL = 0x400000000000

U_CLASS, U_FLAG, U_SUBCLASS, U_SERIAL = 0x2E04, 0x2E32, 0x35AC, 0x3060
U_COUNTERS, U_BONUS = 0x30A4, 0x359C
U_POOL, U_STAGE = 0x350C, 0x3584
RECORD = 0x4800
POOL_SIZE, STAGE_SIZE = 120, 24

G_MIN, G_MAX = 0x140A18750, 0x140A18758          # award amount clamp
G_ENABLED, G_NOTIFY = 0x145574B28, 0x140BDFD08   # writer gate; notification block
G_ROWS, G_COUNT = 0x140A03B38, 0x140A03B40
G_FLAGS = 0x144FCCB0E                            # &game_flags (0x1C62A0's flag bitmap)
FLAG_BYTES = 0x800

WRITER, READER, SEEN, WRAPPER = 0x14015F480, 0x140217230, 0x1401C62A0, 0x140160E20
WRITER_SITE = 0x14015F500


def counter_offset(slot, rank=0):
    return U_COUNTERS + slot * 0x18 + rank * 4


# ------------------------------------------------------------------------------ emulation
class Image:
    """the patched exe mapped as the game would map it, plus the fixtures a mastery call reads"""

    def __init__(self, exe, writes=None):
        import pefile
        from unicorn import UC_ARCH_X86, UC_HOOK_MEM_WRITE, UC_MODE_64, Uc
        self.pe = pefile.PE(data=exe, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        size = (self.pe.OPTIONAL_HEADER.SizeOfImage + PAGE - 1) & -PAGE
        self.uc.mem_map(self.base, size)
        self.mapped.add((self.base, size))
        for s in self.pe.sections:
            self.uc.mem_write(self.base + s.VirtualAddress, bytes(self.pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)))
        self.write(STACK, bytes(STACK_SIZE))
        self.write(UNIT, bytes(2 * RECORD))          # two unit records, so either one can be read back
        self.writes = writes

        def on_write(uc, access, address, length, value, _):
            self.writes.append((address, length))

        if writes is not None:
            self.uc.hook_add(UC_HOOK_MEM_WRITE, on_write)

    def write(self, address, data):
        for page in range(address & -PAGE, (address + len(data) + PAGE - 1) & -PAGE, PAGE):
            if not any(a <= page < a + n for a, n in self.mapped):
                self.uc.mem_map(page, PAGE)
                self.mapped.add((page, PAGE))
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


def run(exe, start, args=(), setup=None, stop=None, instruction_max=400000, stack_args=(),
        regs_extra=(), trace_writes=False):
    """execute from `start` with the Windows x64 argument registers; stop at `stop` or the sentinel"""
    writes = [] if trace_writes else None
    img = Image(exe, writes=writes)
    uc = img.uc
    if setup:
        setup(img)
    regs = _regs()
    if stop is None:
        img.write(SP, struct.pack("<Q", SENTINEL))
        img.write(SENTINEL, b"\xf4")
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
    except Exception as exc:                                   # unicorn reports faults as exceptions
        state["error"] = f"{type(exc).__name__}: {exc}"
    out = {n: uc.reg_read(regs[n]) for n in ("rax", "rbx", "rcx", "rdx", "r8", "r9", "r10", "r11",
                                             "r12", "r13", "r14", "r15", "rip")}
    out.update(instructions=state["instructions"], error=state["error"], image=img, writes=writes)
    return out


# ------------------------------------------------------------------------------ fixtures
def jobrank(rows):
    """{class id: threshold}: 20-byte rows, key +0, threshold +4, eight bonus bytes +0xa..+0x11"""
    data = bytearray()
    for cls, threshold in sorted(rows.items()):
        row = bytearray(20)
        struct.pack_into("<II", row, 0, cls, threshold)
        struct.pack_into("<8B", row, 10, *([1, 2, 3, 4, 5, 6, 7, 8]))
        data += row
    return bytes(data)


def rows_for(families, thresholds=None):
    rows = {}
    for fam in VANILLA:
        rows.update({fam + r: 64 * 4 ** r for r in range(6)})
    for fam in families:
        rows.update({fam + r: (thresholds or {}).get((fam, r), 64 * 4 ** r) for r in range(6)})
    return rows


def unit(*, cls=1010, flag=1, subclass=0, counters=(), bonuses=(), pool=b"", stage=b""):
    b = bytearray(RECORD)
    struct.pack_into("<i", b, U_CLASS, cls)
    struct.pack_into("<h", b, U_SUBCLASS, subclass)
    b[U_FLAG] = flag
    for slot, rank, value in counters:
        struct.pack_into("<I", b, counter_offset(slot, rank), value)
    for i, value in enumerate(bonuses):
        struct.pack_into("<H", b, U_BONUS + i * 2, value)
    b[U_POOL:U_POOL + len(pool)] = pool
    b[U_STAGE:U_STAGE + len(stage)] = stage
    return bytes(b)


def world(rows, *, unit_bytes=None, at=UNIT, flags=None, records=()):
    def setup(img):
        img.write(JOBRANK, jobrank(rows))
        img.write(G_ROWS, struct.pack("<Q", JOBRANK))
        img.write(G_COUNT, struct.pack("<I", len(rows)))
        img.write(G_MIN, struct.pack("<q", 0))
        img.write(G_MAX, struct.pack("<q", 999999))
        img.write(G_ENABLED, struct.pack("<I", 1))
        img.write(G_NOTIFY, bytes(0x40))
        img.write(LOWMEM, bytes(0x1000))
        if flags is not None:
            img.write(G_FLAGS, flags)
        for address, data in records:
            img.write(address, data)
        if unit_bytes is not None:
            img.write(at, unit_bytes)
    return setup


def spare(record):
    return record[U_POOL:U_POOL + POOL_SIZE + STAGE_SIZE]


def stage_of(record):
    return list(struct.unpack_from("<6I", record, U_STAGE))


def pool_of(record):
    return record[U_POOL:U_POOL + POOL_SIZE]


def award(exe, rows, record, target, amount, *, at=UNIT, flag_notify=0, flag=1, trace=False):
    """one award through the game's own writer; returns the run (record at run['image'])"""
    return run(exe, WRITER, (at, target, amount, flag_notify), setup=world(rows, unit_bytes=record, at=at),
               stack_args=(0,), trace_writes=trace)


def read(exe, rows, record, cls, *, at=UNIT):
    got = run(exe, READER, (at, cls, 0, 0), setup=world(rows, unit_bytes=record, at=at))
    return got["rax"] & 0xFFFFFFFF, got


# ------------------------------------------------------------------------------ checks
def checks(orig, patched, pm):
    from d5lib import packedmastery as codec

    def thresholds(fams):
        return {fam: tuple(64 * 4 ** r for r in range(6)) for fam in fams}

    results = []

    def one_star_expectation(fams, target, amount, record):
        """the counters the writer must leave behind: star 1 only, native overflow upward"""
        proj, _ = codec_project(fams, target, amount, record)
        return proj

    def codec_project(fams, target, amount, record):
        """the offline model's projection of the same award, for an independent expectation"""
        fam = target - target % 10
        ts = thresholds(fams)
        area = spare(record)
        if not any(area):
            entries, staged, stage = {}, 0, (0,) * 6                     # a blank spare area starts empty
        else:
            entries, staged, stage = codec.decode_pool(area, ts)
        counters = list(stage) if staged == fam else list(entries.get(fam, (0,) * 6))
        from d5lib import masteryaward
        return masteryaward.project(counters, ts[fam], amount)

    # 1 -- 1, 7 and 45 families: a rank-5 target awards one star, the unpatched build nothing
    def award_one_family():
        detail = {}
        for count in (1, 7, 45):
            fams = [1350 + 10 * i for i in range(count)]
            target_fam = fams[len(fams) // 2]
            exe = pm.build_patch(orig, fams)                     # the real builder, per family count
            info = pm.section_info(exe)
            assert pm.read_families(exe) == fams, pm.read_families(exe)
            rows = rows_for(fams)
            before = unit(cls=1010)
            got = award(exe, rows, before, target_fam + 5, 7)
            assert not got["error"], got["error"]
            after = got["image"].read(UNIT, RECORD)
            assert stage_of(after) == [7, 0, 0, 0, 0, 0], (count, stage_of(after))
            assert pool_of(after)[:4] == b"\xc5\x01" + struct.pack("<H", target_fam // 10), pool_of(after)[:4].hex()
            # nothing else in the record changed except the pool header and slot 52
            mask = bytearray(before)
            mask[U_POOL:U_POOL + 4] = after[U_POOL:U_POOL + 4]
            mask[U_STAGE:U_STAGE + STAGE_SIZE] = after[U_STAGE:U_STAGE + STAGE_SIZE]
            assert bytes(mask) == after, f"{count} families: the award changed bytes outside the mastery area"
            plain = award(orig, rows, before, target_fam + 5, 7)
            assert not plain["error"], plain["error"]
            assert plain["image"].read(UNIT, RECORD) == before, "the unpatched build awarded something"
            detail[count] = dict(families=count, target=target_fam + 5, counters=stage_of(after),
                                 pool_header=pool_of(after)[:4].hex(), section_bytes=info["size"],
                                 patched_sha256=hashlib.sha256(exe).hexdigest(), unpatched_unchanged=True)
        return detail

    results.append(("award-one-family", award_one_family))

    # 2 -- six awards, one per rank id: star 1 keeps the progress (STARS-FIX order)
    def award_six_ranks():
        fams = [1350, 1360]
        rows = rows_for(fams)
        record = unit(cls=1010)
        for rank in range(6):
            got = award(patched, rows, record, 1350 + rank, 4)
            assert not got["error"], got["error"]
            record = got["image"].read(UNIT, RECORD)
            assert stage_of(record) == [4 * (rank + 1), 0, 0, 0, 0, 0], (rank, stage_of(record))
        # and the same sequence starts from rank 5 downwards (the imported-unit case)
        record2 = unit(cls=1010)
        for rank in (5, 4, 3, 2, 1, 0):
            got = award(patched, rows, record2, 1350 + rank, 4)
            record2 = got["image"].read(UNIT, RECORD)
        assert stage_of(record2) == [24, 0, 0, 0, 0, 0], stage_of(record2)
        return dict(from_rank_0=stage_of(record), from_rank_5=stage_of(record2), target_ids="1350..1355")

    results.append(("award-six-ranks", award_six_ranks))

    # 3 -- a completing award: star 1 fills, the eight bonus words are paid once, overflow goes to star 2
    def award_completion():
        fams = [1350]
        rows = rows_for(fams)
        got = award(patched, rows, unit(cls=1010), 1350, 100)
        assert not got["error"], got["error"]
        record = got["image"].read(UNIT, RECORD)
        assert stage_of(record) == [64, 36, 0, 0, 0, 0], stage_of(record)
        bonuses = list(struct.unpack_from("<8H", record, U_BONUS))
        assert bonuses == [1, 2, 3, 4, 5, 6, 7, 8], bonuses
        # a second award completing star 2 pays star 2's bonus bytes again, once
        got2 = award(patched, rows, record, 1355, 228)
        record2 = got2["image"].read(UNIT, RECORD)
        assert stage_of(record2) == [64, 256, 8, 0, 0, 0], stage_of(record2)
        assert list(struct.unpack_from("<8H", record2, U_BONUS)) == [2, 4, 6, 8, 10, 12, 14, 16]
        # the offline model agrees with the native result
        model, _ = codec_project(fams, 1350, 100, unit(cls=1010))
        assert list(model) == [64, 36, 0, 0, 0, 0], model
        return dict(after_first=stage_of(record), bonuses_first=bonuses,
                    after_second=stage_of(record2), model_agrees=list(model))

    results.append(("award-completion", award_completion))

    # 4 -- two units: each keeps its own stage and pool
    def award_two_units():
        fams = [1350, 1360]
        rows = rows_for(fams)
        second = UNIT + RECORD
        a = award(patched, rows, unit(cls=1010), 1350, 7)
        assert not a["error"], a["error"]
        rec_a = a["image"].read(UNIT, RECORD)
        # unit B's award runs in a fresh machine that also holds unit A's record as it is now
        b = run(patched, WRITER, (second, 1360, 9, 0), stack_args=(0,),
                setup=world(rows, unit_bytes=unit(cls=1010), at=second, records=[(UNIT, rec_a)]))
        assert not b["error"], b["error"]
        rec_a2 = b["image"].read(UNIT, RECORD)
        rec_b = b["image"].read(second, RECORD)
        assert rec_a2 == rec_a, "unit B's award changed unit A"
        assert stage_of(rec_b) == [9, 0, 0, 0, 0, 0], stage_of(rec_b)
        assert pool_of(rec_b)[:4] == b"\xc5\x01" + struct.pack("<H", 136), pool_of(rec_b)[:4].hex()
        return dict(unit_a=stage_of(rec_a), unit_b=stage_of(rec_b))

    results.append(("award-two-units", award_two_units))

    # 5 -- a full pool: -1, and the writer writes nothing at all
    def award_pool_full():
        fams = [1350] + [1400 + 10 * i for i in range(38)]
        ts = thresholds(fams)
        entries = {fam: (64, 0, 0, 0, 0, 0) for fam in fams[1:]}          # 38 completed stars: 3 bytes each
        area = codec.encode_pool(entries, ts, 1350, (5, 0, 0, 0, 0, 0))
        assert area[:2] == b"\xc5\x01"
        record = unit(cls=1010, pool=area[:POOL_SIZE], stage=area[POOL_SIZE:])
        rows = rows_for(fams)
        # the pool cannot take 1350 back (3 + 38*3 = 117 of 120 used by the entries alone)
        got = award(patched, rows, record, 1360, 8)
        assert not got["error"], got["error"]
        after = got["image"].read(UNIT, RECORD)
        assert after == record, "a full pool changed the record"
        assert read(patched, rows, after, 1360)[0] == 0
        # and the unpatched build is identical (nothing to award either)
        plain = award(orig, rows, record, 1360, 8)
        assert plain["image"].read(UNIT, RECORD) == record
        return dict(pool_entries=len(entries) + 1, record_unchanged=True, reader_answers=0)

    results.append(("award-pool-full", award_pool_full))

    # 6 -- capacity is checked before the writer's first side effect
    def award_capacity_first():
        fams = [1350, 1360]
        extra = [1400 + 10 * i for i in range(37)]
        ts = thresholds(fams + extra)
        entries = {fam: (64, 0, 0, 0, 0, 0) for fam in extra}
        entries[1360] = (64, 0, 0, 0, 0, 0)
        area = codec.encode_pool(entries, ts, 1350, (5, 0, 0, 0, 0, 0))   # 38 entries and a staged family
        record = unit(cls=1010, pool=area[:POOL_SIZE], stage=area[POOL_SIZE:])
        rows = rows_for(fams + extra)
        # 1350 is the staged family and the pool is full: staging 1360 needs 1350's 6 bytes packed back
        got = award(patched, rows, record, 1360, 100, flag=0)             # immaterial: the gate is bypassed
        assert not got["error"], got["error"]
        after = got["image"].read(UNIT, RECORD)
        assert after == record, "a refused switch still wrote something"
        assert stage_of(after) == [5, 0, 0, 0, 0, 0], stage_of(after)
        assert list(struct.unpack_from("<8H", after, U_BONUS)) == [0] * 8
        # the same award with room to spare does complete, so the refusal above is about capacity only
        roomy = unit(cls=1010, pool=codec.encode_pool({}, ts)[:POOL_SIZE],
                     stage=codec.encode_pool({}, ts)[POOL_SIZE:])
        ok = award(patched, rows, roomy, 1350, 100)
        assert stage_of(ok["image"].read(UNIT, RECORD)) == [64, 36, 0, 0, 0, 0]
        return dict(entries=len(entries), staged=1350, record_unchanged=True, control_award=[64, 36, 0, 0, 0, 0])

    results.append(("award-capacity-first", award_capacity_first))

    # 7 -- award, pack back, restore, and read the saved bytes back
    def award_round_trip():
        fams = [1350, 1360]
        rows = rows_for(fams)
        got = award(patched, rows, unit(cls=1010), 1350, 100)
        record = got["image"].read(UNIT, RECORD)
        assert stage_of(record) == [64, 36, 0, 0, 0, 0], stage_of(record)
        # switch to 1360 through the writer's own mapper call: 1350 is packed back
        switched = award(patched, rows, record, 1360, 3)
        record2 = switched["image"].read(UNIT, RECORD)
        assert stage_of(record2) == [3, 0, 0, 0, 0, 0], stage_of(record2)
        packed = pool_of(record2)
        assert packed[:4] == b"\xc5\x01" + struct.pack("<H", 136), packed[:4].hex()
        # header: family 135 | k=1 (star 1 complete) | n=1 (star 2 partial) -> 0x1A70... and the value 36
        header = int.from_bytes(packed[4:7], "little")
        assert header & 0x1FFF == 135 and (header >> 13) & 7 == 1 and (header >> 16) & 7 == 1, hex(header)
        assert int.from_bytes(packed[7:10], "little") == 36, packed[7:10].hex()
        # switch back: the exact counters return
        back = award(patched, rows, record2, 1350, 0)
        record3 = back["image"].read(UNIT, RECORD)
        assert stage_of(record3) == [64, 36, 0, 0, 0, 0], stage_of(record3)
        # the game's own reader, on the bytes a save would hold, after a reload
        saved = record3
        for cls, want in ((1350, 64), (1351, 36), (1352, 0), (1360, 3), (1361, 0)):
            value, _ = read(patched, rows, saved, cls)
            assert value == want, (cls, value, want)
            # the unpatched build reads 0 for the packed families from the same bytes
            assert read(orig, rows, saved, cls)[0] == 0
        return dict(after_award=stage_of(record), packed_header=hex(header), packed_value=36,
                    restored=stage_of(record3), reader={1350: 64, 1351: 36, 1360: 3},
                    unpatched_reads_zero=True)

    results.append(("award-round-trip", award_round_trip))

    # 8 -- the unlock path: a packed family's rank id is a clean no-op, a vanilla id still marks seen
    def unlock_custom_noop():
        def seen_once(exe, cls, flag_record=unit(cls=1010, flag=0)):
            """call mark_character_seen directly and list every memory write outside the stack"""
            got = run(exe, SEEN, (cls,), setup=world(rows_for([]), unit_bytes=flag_record), trace_writes=True)
            assert not got["error"], got["error"]
            outside = [(hex(a), n) for a, n in got["writes"]
                       if not (STACK <= a < STACK + STACK_SIZE)]
            return got, outside

        detail = {}
        custom = unit(cls=1350, flag=0)
        for cls in (1350, 1355, 1360, 1400):
            got, outside = seen_once(patched, cls, custom)
            assert outside == [], (cls, outside)
            detail[cls] = dict(writes_outside_stack=0, rax=got["rax"])
        # a vanilla id writes its flag bit, identically before and after the extension
        bits = {}
        for label, exe in (("unpatched", orig), ("patched", patched)):
            got, outside = seen_once(exe, 1010, unit(cls=1010, flag=0))
            assert outside, f"{label}: mark_character_seen(1010) wrote nothing"
            bits[label] = sorted(outside)
        assert bits["patched"] == bits["unpatched"], bits
        # through the real writer: a packed completion writes no global flag at all
        fams = [1350]
        rows = rows_for(fams)
        rec = unit(cls=1010, flag=0)
        got = award(patched, rows, rec, 1350, 100, flag=0, trace=True)
        assert not got["error"], got["error"]
        globals_written = [(hex(a), n) for a, n in got["writes"]
                           if not (STACK <= a < STACK + STACK_SIZE) and not (UNIT <= a < UNIT + RECORD)]
        assert globals_written == [], globals_written
        detail["writer_globals_written"] = 0
        detail["vanilla_flag_writes"] = len(bits["unpatched"])
        return detail

    results.append(("unlock-custom-noop", unlock_custom_noop))

    # 9 -- the writer's mapper call: r10 becomes the family base, and only there
    def writer_r10_and_vanilla():
        site = WRITER_SITE
        detail = {}
        # (target id, the value the wrapper must leave in r10): the family base for a configured
        # family, the caller's own value otherwise (the unpatched answer would have been id % 10)
        for cls, want in ((1355, 1350), (1350, 1350), (1015, 0x1234), (1300, 0x1234), (1370, 0x1234)):
            fams = [1350]
            rows = rows_for(fams)
            rec = unit(cls=1010)
            img = Image(patched)
            world(rows, unit_bytes=rec)(img)
            uc = img.uc
            regs = _regs()
            uc.reg_write(regs["rsp"], SP)
            uc.reg_write(regs["rcx"], cls)
            uc.reg_write(regs["rbx"], UNIT)
            uc.reg_write(regs["r10"], 0x1234)
            img.write(SP, bytes(0x100))
            stop = site + 5
            uc.emu_start(site, stop, count=200000)
            assert uc.reg_read(regs["rip"]) == stop, hex(uc.reg_read(regs["rip"]))
            got = uc.reg_read(regs["r10"]) & 0xFFFFFFFF
            assert got == want, (cls, hex(got), hex(want))
            detail[cls] = got
        # a vanilla award is byte-identical patched vs unpatched
        same = {}
        for label, exe in (("unpatched", orig), ("patched", patched)):
            rec = unit(cls=2010, counters=[(0, 0, 60)], bonuses=[3, 0, 0, 0, 0, 0, 0, 0])
            got = award(exe, rows_for([]), rec, 1015, 8)
            assert not got["error"], got["error"]
            same[label] = got["image"].read(UNIT, RECORD)
        assert same["unpatched"] == same["patched"], "a vanilla award changed"
        detail["vanilla_record_identical"] = True
        return detail

    results.append(("writer-r10-and-vanilla", writer_r10_and_vanilla))
    return results


def saves_byte(record, size):
    return record[:size]


def abi_cases(orig, patched, pm):
    """the writer's mapper call entered the way the writer enters it, plus the two sub-class
    sites the packed section now owns (they are .d5cm's generated bytes, entered from the
    game's own instructions)"""
    import abi_engine_packed as abi
    from d5lib import masteryext as mx
    info = pm.section_info(patched)
    rows = rows_for([1350])
    rec = unit(cls=1010)
    seeds = {n: 0x1111000000000000 + i for i, n in
             enumerate(("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "r8", "r9", "r10", "r11",
                        "r12", "r13", "r14", "r15"))}
    ARRAY, SCREEN = 0x400600000, 0x400700000

    def one(cls, expect_r10, expect_rax, expect=None):
        regs = dict(seeds)
        regs["rcx"] = cls
        regs["rbx"] = UNIT
        regs["r10"] = cls                       # what the writer's own `mov r10d, edx` left there

        def fixture(img):
            img(UNIT, rec)
            img(JOBRANK, jobrank(rows))
            img(G_ROWS, struct.pack("<Q", JOBRANK))
            img(G_COUNT, struct.pack("<I", len(rows)))

        preserve = {k: v for k, v in regs.items() if k not in ("rax", "r10")}
        got = abi.execute(patched, info, WRITER_SITE, kind="call", fixture=fixture, regs=regs,
                          stubs=[(pm.MAPPER, abi.clobbering_stub(-1))],
                          expect_args={"rcx": cls}, answer={"rax": expect_rax, "r10": expect_r10},
                          preserve=preserve, writable=[(UNIT, UNIT + RECORD)], probe=[(UNIT, RECORD)])
        if expect is not None:
            assert got["probed"][hex(UNIT)] == expect, "the record is not as expected"
        return got

    def writer_site():
        staged = unit(cls=1010, pool=b"\xc5\x01" + struct.pack("<H", 135) + bytes(POOL_SIZE - 4),
                      stage=struct.pack("<6I", 0, 0, 0, 0, 0, 0))
        got = one(1355, 1350, pm.STAGE_SLOT, expect=staged)
        vanilla = one(1015, 1015, 0xFFFFFFFF, expect=rec)   # the stub answers -1: the wrapper passes it through
        return dict(cases=2, packed_r10=got["answer"]["r10"], packed_answer=got["answer"]["rax"],
                    vanilla_r10=vanilla["answer"]["r10"], vanilla_answer=vanilla["answer"]["rax"],
                    registers_preserved_except_r10_at_the_writer_site=True,
                    max_instructions=max(got["instructions"], vanilla["instructions"]))

    def subclass_sites():
        # the gate: entered by the game's jump, leaves to the native accept/reject continuations
        gate = {}
        for cls, want in ((1350, mx.SUBCLASS_ACCEPT), (1015, mx.SUBCLASS_ACCEPT), (1370, mx.SUBCLASS_REJECT)):
            regs = dict(seeds)
            regs["rcx"] = cls
            got = abi.execute(patched, info, mx.SUBCLASS_SITE, kind="jmp", regs=regs,
                              stop=(mx.SUBCLASS_ACCEPT, mx.SUBCLASS_REJECT),
                              preserve={k: v for k, v in regs.items() if k != "rax"})
            assert got["stopped_at"] == hex(want), (hex(cls), got["stopped_at"])
            gate[cls] = got["stopped_at"]
        # the screen fetch: entered by the game's call for one index; r15d is the answer it writes
        array = bytearray(0x70 + 48 * 4)
        for i, fam in enumerate(VANILLA):
            struct.pack_into("<i", array, i * 4, fam)

        def fixture(img):
            img(ARRAY, bytes(array))
            screen = bytearray(0x8FC0)
            struct.pack_into("<i", screen, mx.COUNT_OFFSET, 0)
            img(SCREEN, screen)

        listed = {}
        for index, want in ((5, VANILLA[5]), (47, 1350), (48, 1360), (60, 0)):
            regs = dict(seeds)
            regs["rsi"] = SCREEN
            regs["rbp"] = ARRAY + 0x70
            regs["r13"] = index
            got = abi.execute(patched, info, mx.FETCH_SITE, kind="call", fixture=fixture, regs=regs,
                              answer={"r15": want}, outputs=("r15",),
                              preserve={k: v for k, v in regs.items() if k != "r15"})
            listed[index] = got["answer"]["r15"]
        return dict(gate={hex(k): v for k, v in gate.items()},
                    fetch={str(k): v for k, v in listed.items()},
                    max_instructions=max(got["instructions"], 1))

    return [("abi-writer-site-r10", writer_site), ("abi-subclass-sites", subclass_sites)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", type=Path, required=True)
    ap.add_argument("--families", default="1350,1360")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    from d5lib import packedmasteryhook as pm
    original = args.original.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, "not the pinned original exe"
    fams = [int(v) for v in args.families.split(",") if v.strip()]
    patched = pm.build_patch(original, fams)
    info = pm.section_info(patched)
    build = dict(families=fams, section=info["section"], base=hex(info["base"]), size=info["size"],
                 patched_sha256=hashlib.sha256(patched).hexdigest(), original_sha256=ORIGINAL_SHA)
    print(f"section {info['section']} at {info['base']:#x}; families {fams}")
    if args.build_only:
        build["note"] = "patch built; Unicorn not imported"
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(build, indent=1) + "\n")
        return 0
    plan = checks(original, patched, pm)
    if args.abi:
        plan += abi_cases(original, patched, pm)
    out, passed = [], True
    for name, fn in plan:
        try:
            detail = fn()
            out.append(dict(name=name, ok=True, detail=_jsonable(detail)))
            print(f"PASS {name}")
        except Exception as exc:
            passed = False
            import traceback
            out.append(dict(name=name, ok=False, error=f"{type(exc).__name__}: {exc}",
                            trace=traceback.format_exc().splitlines()[-6:]))
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    report = dict(mode="abi-site-entry" if args.abi else "behaviour", build=build, checks=out, passed=passed,
                  limitations=[
                      "The real writer (0x14015F480) and the real reader (0x140217230) are executed; the "
                      "JobRank rows, the unit records and the writer's global gates are fixtures.",
                      "mark_character_seen (0x1C62A0) is executed for its range gate only; the trophy and "
                      "achievement paths behind it belong to vanilla ids and are compared, not re-implemented.",
                      "--abi replaces the original mapper with a clobbering stub so the wrapper's own register "
                      "contract (and the r10 it hands the writer) is proven independently of the game's code.",
                      "Executed paths only: Windows unwind dispatch, the battle/menu frames above the writer "
                      "and native gameplay are not executed here.",
                      "The notification path (writer param 5) is not exercised: every run passes 0."])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    print(f"[{report['mode']}] {sum(c['ok'] for c in out)}/{len(out)} checks passed")
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
