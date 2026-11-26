"""Offline proof for the packed mastery mapper hook (section .d5pm, P2d step 1).

Everything runs in Unicorn over the *pinned original* exe (sha256 49a7530b...db282ce)
plus this extension's own section; no game process, install, save or live state is
touched.  The hook is always entered the way the game enters it: by executing the
real call instruction at one of the 16 mapper call sites, so the wrapper sees the
caller's real return address, registers and stack alignment.

What is proven, per check:

  vanilla-unchanged   every vanilla class id answers exactly what the unpatched
                      game answers from the same site, and the unit record is
                      byte-identical afterwards (nothing written).
  stage-*             a configured family is mapped to slot 52 of *that unit*,
                      the family's own progress is packed into the unit's pool,
                      switching back restores the exact counters, an identical
                      request writes nothing, and every one of the 16 sites
                      behaves identically (also with the two deref sites).
  model-format        after every switch the record's 144-byte area is byte-for-byte
                      what d5lib.packedmastery/d5lib.packedmapper (the offline spec)
                      computes for the same input, through a randomized walk.
  fail-closed         unknown/legacy bytes, malformed pools, a full pool, a missing
                      JobRank row, a counter above its threshold or beyond 24 bits,
                      and a null record all answer -1 and leave the record untouched.
  record-scope        two units keep independent pools and staged counters.

`--build-only` builds and validates the patch without importing Unicorn.
`--abi` additionally enters every patched site the way its caller does (caller
volatile and nonvolatile registers, home space, unwind-visible frame), which is
checked by mastery/abi_engine_packed.py.
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
FAMILIES = [1350, 1360]
OUT_OF_RANGE = (-1, 0, 999, 1000, 1019, 1269, 1271, 2009, 2219, 3000)

PAGE = 0x1000
STACK, STACK_SIZE = 0x100000000, 0x200000
SP = STACK + STACK_SIZE - 0x1000
UNIT, HOLDER, JOBRANK, LOWMEM = 0x400000000, 0x400200000, 0x400300000, 0x400400000
SENTINEL = 0x400000000000

U_POOL, U_STAGE = 0x350C, 0x3584
G_ROWS, G_COUNT = 0x140A03B38, 0x140A03B40
POOL_SIZE, STAGE_SIZE = 120, 24
SPARE = POOL_SIZE + STAGE_SIZE

SITE_REGS = {0x1400B3CED: ("r13", 0x228), 0x14015F505: ("rbx", 0),
             0x140217246: ("r10", 0), 0x14021732B: ("rdi", 0),
             0x1402A3A62: ("r10", 0), 0x1402A3B05: ("r9", 0)}
for _site in (0x1402A3DDA, 0x1402A3E89, 0x1402A3F39, 0x1402A3FE9, 0x1402A4099, 0x1402A4149,
              0x1402A43D1):
    SITE_REGS[_site] = ("rbp", 0)
SITE_REGS[0x14047FFCD] = ("r15", 0x1F1A8)
SITE_REGS[0x1407CDA91] = ("rbp", 0)
SITE_REGS[0x1407CDADE] = ("rbp", 0)


def sites():
    """[(call site va, return address, register, deref)] in exe order"""
    from d5lib import packedmasteryhook as pm
    out = []
    for va in pm.MAPPER_CALLS:
        reg, deref = SITE_REGS[va + 5]
        out.append((va, va + 5, reg, deref))
    return out


# ------------------------------------------------------------------------------------------ emulation
class Machine:
    """the patched (or unpatched) exe mapped as the loader would, plus the fixtures a mapper call needs"""

    def __init__(self, exe):
        import pefile
        from unicorn import Uc, UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_64
        self.pe = pefile.PE(data=exe, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.uc2 = None
        self.ranges = []
        size = (self.pe.OPTIONAL_HEADER.SizeOfImage + PAGE - 1) & -PAGE
        self.map(self.base, size)
        for s in self.pe.sections:
            self.write(self.base + s.VirtualAddress, bytes(self.pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)))
        self.map(STACK, STACK_SIZE)
        self.map(UNIT, 0x4800 * 2)
        self.map(HOLDER, PAGE)
        self.map(JOBRANK, PAGE)
        self.map(LOWMEM, PAGE)
        self.uc.hook_add(UC_HOOK_CODE, self._stop)

    # -- memory
    def map(self, address, size):
        start = address & -PAGE
        size = ((address + size + PAGE - 1) & -PAGE) - start
        if any(a <= start and start + size <= a + n for _, a, n in self.ranges):
            return
        self.uc.mem_map(start, size)
        self.ranges.append(("m", start, size))

    def map_any(self, address):
        """map the page containing `address` if the image does not cover it (bss globals are not in the file)"""
        page = address & -PAGE
        if not any(a <= page < a + n for _, a, n in self.ranges):
            self.uc.mem_map(page, PAGE)
            self.ranges.append(("m", page, PAGE))

    def write(self, address, data):
        self.map_any(address)
        self.map_any(address + len(data) - 1)
        self.uc.mem_write(address, bytes(data))

    def read(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    # -- one mapper call, entered by executing the real call instruction at `site`
    def run(self, site, reg, cls, unit, deref=0, at=UNIT, job_rows=None, rows_ptr=None,
            reg_value=None):
        """`unit` is the unit record placed at `at`; `deref` is the site's extra indirection (the register
        points at an object whose field holds the record).  Returns the record afterwards."""
        from unicorn import x86_const as X
        seeds = {name: 0x1111000000000000 + i for i, name in
                 enumerate(("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "r8", "r9", "r10", "r11",
                            "r12", "r13", "r14", "r15"))}
        r = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in (*seeds, "rsp", "rip")}
        for name, value in seeds.items():
            self.uc.reg_write(r[name], value)
        self.write(at, unit)
        if deref:
            self.write(HOLDER + deref, struct.pack("<Q", at))
        self.write(SP, bytes(0x100))
        if job_rows is not None:
            self.write(JOBRANK, job_rows)
            self.write(G_ROWS, struct.pack("<Q", rows_ptr if rows_ptr is not None else JOBRANK))
            self.write(G_COUNT, struct.pack("<I", len(job_rows) // 20))
        self.uc.reg_write(r["rsp"], SP)
        self.uc.reg_write(r["rcx"], cls & 0xFFFFFFFF)
        self.uc.reg_write(r[reg], reg_value if reg_value is not None else (HOLDER if deref else at))
        self.stop_at = site + 5
        self.uc.emu_start(site, 0, count=200000)
        answer = self.uc.reg_read(r["rax"])
        rec = self.read(at, 0x4800)
        kept = {n: self.uc.reg_read(r[n]) for n in ("rbx", "rbp", "rsi", "rdi", "r8", "r9", "r10",
                                                    "r11", "r12", "r13", "r14", "r15", "rdx")}
        return dict(eax=answer, unit=rec, regs=kept, expected=seeds)

    def _stop(self, uc, address, size, _):
        if address == self.stop_at:
            uc.emu_stop()


def job_rows(families, thresholds=None):
    """rows of 0x14 bytes, sorted by class id; default threshold 64 * 4**rank"""
    rows = {}
    for fam in families:
        for rank in range(6):
            rows[fam + rank] = (thresholds or {}).get((fam, rank), 64 * 4 ** rank)
    return b"".join(struct.pack("<II", cls, rows[cls]) + b"\x01" * 12 for cls in sorted(rows))


def unit(pool=b"", stage=b"", base=b"", spare=b""):
    b = bytearray(base or bytes(0x4800))
    b[U_POOL:U_POOL + len(pool)] = pool
    b[U_STAGE:U_STAGE + len(stage)] = stage
    b[U_POOL:U_POOL + len(spare)] = spare
    return bytes(b)


def spare(rec):
    return rec[U_POOL:U_POOL + SPARE]


def thresholds(families):
    return {fam: tuple(64 * 4 ** r for r in range(6)) for fam in families}


# ------------------------------------------------------------------------------------------ checks
def checks(orig, patched, pm):
    vanilla_ids = [fam + r for fam in VANILLA for r in range(6)] + list(OUT_OF_RANGE)
    jobs = job_rows(FAMILIES)
    plain = Machine(patched)
    base = Machine(orig)

    def run_both(site, reg, deref, cls, rec, **kw):
        a = plain.run(site, reg, cls, rec, deref=deref, job_rows=kw.get("jobs"))
        b = base.run(site, reg, cls, rec, deref=deref)
        return a, b

    def vanilla_unchanged():
        runs = 0
        diffs = []
        for site, _, reg, deref in sites():
            for cls in vanilla_ids:
                a, b = run_both(site, reg, deref, cls, unit(), jobs=jobs)
                runs += 1
                if a["eax"] != b["eax"] or a["unit"] != b["unit"]:
                    diffs.append(dict(site=hex(site), cls=cls, patched=a["eax"], vanilla=b["eax"],
                                      written=a["unit"] != unit()))
        assert not diffs, diffs[:5]
        return dict(ids=len(vanilla_ids), runs=runs, both_sites=True, differences=0)

    def stage_first():
        runs = []
        for site, _, reg, deref in sites():
            got = plain.run(site, reg, 1350, unit(), deref=deref, job_rows=jobs)
            area = spare(got["unit"])
            assert got["eax"] == pm.STAGE_SLOT, (hex(site), got["eax"])
            assert area[:4] == b"\xc5\x01\x87\x00", (hex(site), area[:4].hex())
            assert not any(area[4:]), area.hex()
            assert not any(got["unit"][U_STAGE:U_STAGE + STAGE_SIZE]), "stage not cleared"
            runs.append(hex(site))
        return dict(sites=len(runs), answer=pm.STAGE_SLOT, area="c5 01 87 00 + zeros", stage_zero=True)

    def stage_idempotent():
        first = plain.run(0x14015F500, "rbx", 1350, unit(), job_rows=jobs)
        second = plain.run(0x14015F500, "rbx", 1350, first["unit"], job_rows=jobs)
        assert second["eax"] == pm.STAGE_SLOT
        assert second["unit"] == first["unit"], "an already-staged family was rewritten"
        return dict(answer=second["eax"], record_unchanged=True)

    def stage_round_trip():
        """stage 1350 (through the progress-panel deref site), write counters, switch (writer site), come back"""
        counters = (10, 20, 0, 0, 0, 0)
        fresh = plain.run(0x14015F500, "rbx", 1350, unit(), job_rows=jobs)
        assert fresh["eax"] == pm.STAGE_SLOT
        rec = unit(base=fresh["unit"], stage=struct.pack("<6I", *counters))
        first = plain.run(0x1400B3CE8, "r13", 1350, rec, deref=0x228, job_rows=jobs)
        assert first["eax"] == pm.STAGE_SLOT
        assert struct.unpack_from("<6I", first["unit"], U_STAGE) == counters, "staging dropped the counters"
        switched = plain.run(0x1400B3CE8, "r13", 1360, first["unit"], deref=0x228, job_rows=jobs)
        assert switched["eax"] == pm.STAGE_SLOT
        area = spare(switched["unit"])
        assert area[:4] == b"\xc5\x01\x88\x00", area[:4].hex()
        assert area[4:7] == bytes([0x87, 0x00, 0x02]), area[4:7].hex()
        assert [int.from_bytes(area[7 + 3 * i:10 + 3 * i], "little") for i in range(2)] == [10, 20], \
            area[7:13].hex()
        assert not any(switched["unit"][U_STAGE:U_STAGE + STAGE_SIZE]), "1360's counters are not zero"
        back = plain.run(0x1407CDAD9, "rbp", 1350, switched["unit"], job_rows=jobs)
        assert back["eax"] == pm.STAGE_SLOT
        assert struct.unpack_from("<6I", back["unit"], U_STAGE) == counters, "round trip lost progress"
        assert spare(back["unit"])[:4] == b"\xc5\x01\x87\x00", spare(back["unit"])[:4].hex()
        return dict(counters=list(counters), entry=area[4:13].hex(), round_trip=True)

    def stage_completed_ranks():
        """three completed ranks cost no counter space: they are implied by the thresholds"""
        site = 0x140217241                                     # the reader helper's mapper call
        fresh = plain.run(site, "r10", 1355, unit(), job_rows=jobs)
        assert fresh["eax"] == pm.STAGE_SLOT, hex(fresh["eax"])
        rec = unit(base=fresh["unit"], stage=struct.pack("<6I", 64, 256, 1024, 7, 0, 0))
        first = plain.run(site, "r10", 1355, rec, job_rows=jobs)
        assert first["eax"] == pm.STAGE_SLOT, hex(first["eax"])
        switched = plain.run(site, "r10", 1360, first["unit"], job_rows=jobs)
        area = spare(switched["unit"])
        assert area[4:7] == bytes([0x87, 3 << 5, 0x01]), area[4:7].hex()   # fid, k=3, n=1
        assert int.from_bytes(area[7:10], "little") == 7, area[7:10].hex()
        back = plain.run(site, "r10", 1350, switched["unit"], job_rows=jobs)
        assert struct.unpack_from("<6I", back["unit"], U_STAGE) == (64, 256, 1024, 7, 0, 0)
        return dict(header=area[4:7].hex(), completed=3, stored=1, round_trip=True)

    def model_format():
        """a randomized walk: after every switch the record's 144-byte spare area must be byte-for-byte what
        the offline specification (d5lib.packedmapper + d5lib.packedmastery) computes from the same input"""
        from d5lib import packedmapper, packedmastery
        th = thresholds(FAMILIES)
        rng, fams = 0x20261027, [1350, 1360]
        rec = plain.run(0x14015F500, "rbx", 1350, unit(), job_rows=jobs)["unit"]
        staged, counters = 1350, [0] * 6
        steps, switches = 0, 0
        for step in range(60):
            rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
            if step % 3 == 0:                                  # the game writes counters into slot 52
                rank = rng % 6
                counters[rank] = min(counters[rank] + (rng >> 8) % 40, th[staged][rank])
                rec = unit(base=rec, stage=struct.pack("<6I", *counters))
            fam = fams[rng % 2]
            model = packedmapper.map_family(-1, fam + (rng % 6), set(fams), spare(rec), th)
            got = plain.run(0x14015F500, "rbx", fam + (rng % 6), rec, job_rows=jobs)
            assert got["eax"] == (pm.STAGE_SLOT if model.slot == 52 else 0xFFFFFFFF), \
                (step, fam, hex(got["eax"]), model.reason)
            assert spare(got["unit"]) == model.area, (step, fam, spare(got["unit"]).hex(), model.area.hex())
            if model.slot == 52:
                _, staged, values = packedmastery.decode_pool(model.area, th)
                counters = list(values)
                assert struct.unpack_from("<6I", got["unit"], U_STAGE) == values, (step, fam, values)
                switches += 1
            rec = got["unit"]
            steps += 1
        return dict(steps=steps, switches=switches, families=fams, byte_identical=True)

    def fail_closed():
        """every unusable spare area answers -1 and leaves the record byte-identical"""
        cases = []
        wide_fams = list(range(1350, 1350 + 10 * 45, 10))
        wide = Machine(pm.build_patch(orig, wide_fams))
        wide_jobs = job_rows(wide_fams)

        def expect_refused(name, rec, cls=1350, machine=plain, jobs_=jobs, site=0x14015F500, reg="rbx",
                           deref=0, reg_value=None):
            got = machine.run(site, reg, cls, rec, deref=deref, job_rows=jobs_, reg_value=reg_value)
            assert got["eax"] == 0xFFFFFFFF, (name, hex(got["eax"]))
            assert machine.read(UNIT, 0x4800) == rec, f"{name}: the record was written"
            cases.append(dict(case=name, answer=-1, written=0))

        expect_refused("unknown spare bytes", unit(spare=b"\x91" * SPARE))
        expect_refused("legacy six-slot counters", unit(stage=struct.pack("<6I", 1, 0, 0, 0, 0, 0)))
        bad_magic = bytearray(SPARE)
        bad_magic[0:2] = b"\xc5\x02"
        expect_refused("wrong pool version", unit(spare=bytes(bad_magic)))
        reserved = bytearray(SPARE)
        reserved[0:2] = b"\xc5\x01"
        reserved[4:7] = bytes([0x87, 0x00, 0x80])                # a reserved header bit
        expect_refused("reserved header bits", unit(spare=bytes(reserved)))
        dup = bytearray(SPARE)
        dup[0:2] = b"\xc5\x01"
        dup[4:7] = bytes([0x87, 0x80 | 0x01, 0x00])
        dup[7:8] = b"\x05"
        dup[8:11] = bytes([0x87, 0x80 | 0x01, 0x00])
        dup[11:12] = b"\x06"
        expect_refused("duplicate family entry", unit(spare=bytes(dup)))
        garbage = bytearray(SPARE)
        garbage[0:2] = b"\xc5\x01"
        garbage[10] = 0x55                                       # past the entry chain
        expect_refused("garbage after the entries", unit(spare=bytes(garbage)))
        # five six-counter entries fill 109 bytes; a sixth header then claims past the pool
        trunc = bytearray(SPARE)
        trunc[0:2] = b"\xc5\x01"
        pos = 4
        for k, fid in enumerate(range(135, 140)):
            trunc[pos:pos + 3] = struct.pack("<I", fid | (6 << 16))[:3]
            pos += 21
        trunc[pos:pos + 3] = struct.pack("<I", 140 | (6 << 16))[:3]
        assert pos == 109
        expect_refused("entry past the end of the pool", unit(spare=bytes(trunc)), machine=wide,
                       jobs_=wide_jobs)
        # 38 completed families leave four bytes: pack-back of the staged family needs six
        full = bytearray(SPARE)
        full[0:2] = b"\xc5\x01"
        full[2:4] = struct.pack("<H", 173)                        # 1730 stays staged
        pos = 4
        for fam in wide_fams[:38]:
            full[pos:pos + 3] = struct.pack("<I", fam // 10 | (6 << 13))[:3]
            pos += 3
        assert pos == 118, pos
        full[120:144] = struct.pack("<6I", 1, 0, 0, 0, 0, 0)      # 1730's counters, staged
        staged_rec = unit(spare=bytes(full))
        expect_refused("full pool", staged_rec, cls=1740, machine=wide, jobs_=wide_jobs)
        expect_refused("staged family not configured",
                       unit(spare=b"\xc5\x01" + struct.pack("<H", 999) + bytes(SPARE - 4)))
        # a counter above its threshold cannot be represented
        rec = plain.run(0x14015F500, "rbx", 1350, unit(), job_rows=jobs)["unit"]
        expect_refused("counter above threshold",
                       unit(base=rec, stage=struct.pack("<6I", 65, 0, 0, 0, 0, 0)), cls=1360)
        # a partial counter beyond 24 bits cannot be stored
        expect_refused("counter beyond 24 bits",
                       unit(base=rec, stage=struct.pack("<6I", 0x1000000, 0, 0, 0, 0, 0)), cls=1360)
        # a family without JobRank rows has no thresholds to pack its staged counters with
        expect_refused("missing JobRank rows",
                       unit(base=rec, stage=struct.pack("<6I", 1, 0, 0, 0, 0, 0)), cls=1360,
                       jobs_=job_rows([1360]))
        # a null record: the answer is the vanilla one and nothing is touched
        fixture = unit()
        expect_refused("null record", fixture, reg_value=0)
        return dict(cases=cases, refused=len(cases))

    def per_unit_scope():
        """the pool and slot 52 live in the unit's own record: two units never see each other's progress"""
        fresh = plain.run(0x14015F500, "rbx", 1350, unit(), job_rows=jobs)
        a = plain.run(0x1402A3A5D, "r10", 1350,
                      unit(base=fresh["unit"], stage=struct.pack("<6I", 11, 0, 0, 0, 0, 0)), job_rows=jobs)
        assert a["eax"] == pm.STAGE_SLOT, hex(a["eax"])
        b = plain.run(0x14015F500, "rbx", 1360, unit(), at=UNIT + 0x4800, job_rows=jobs)
        second = b["unit"]
        assert b["eax"] == pm.STAGE_SLOT, hex(b["eax"])
        assert second[U_POOL:U_POOL + 4] == b"\xc5\x01\x88\x00", second[U_POOL:U_POOL + 4].hex()
        assert not any(second[0x4:0x8]), second[0:8].hex()
        still = plain.read(UNIT, 0x4800)
        assert still == a["unit"], "unit A was written by unit B's call"
        assert struct.unpack_from("<6I", still, U_STAGE) == (11, 0, 0, 0, 0, 0)
        return dict(second_unit=hex(UNIT + 0x4800), independent=True)

    def register_preservation():
        """the wrapper saves every register a caller may keep live across the mapper call"""
        got = plain.run(0x140217241, "r10", 1350, unit(), job_rows=jobs)
        want = got["expected"]
        keep = ("rbx", "rbp", "rsi", "rdi", "r8", "r9", "r11", "r12", "r13", "r14", "r15", "rdx")
        bad = {n: (hex(got["regs"][n]), hex(want[n])) for n in keep if got["regs"][n] != want[n]}
        # r10 held the record and is restored too
        assert not bad, bad
        return dict(registers=len(keep) + 1, preserved=True)

    return [("vanilla-unchanged", vanilla_unchanged), ("stage-first", stage_first),
            ("stage-idempotent", stage_idempotent), ("stage-round-trip", stage_round_trip),
            ("stage-completed-ranks", stage_completed_ranks), ("model-format", model_format),
            ("fail-closed", fail_closed), ("per-unit-scope", per_unit_scope),
            ("register-preservation", register_preservation)]


def abi_cases(orig, patched, pm):
    """every patched site entered exactly as its caller enters it (ABI mode)"""
    import abi_engine_packed as abi
    info = pm.section_info(patched)
    jobs = job_rows(FAMILIES)
    runs = []
    staged_once = unit(spare=b"\xc5\x01\x87\x00" + bytes(SPARE - 4))

    def one(site, reg, deref, cls, rec, stub_answer, want, name, expect=None):
        seeds = {n: 0x1111000000000000 + i for i, n in
                 enumerate(("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "r8", "r9", "r10", "r11",
                            "r12", "r13", "r14", "r15"))}
        regs = dict(seeds)
        regs["rcx"] = cls
        regs[reg] = HOLDER if deref else UNIT
        # the award path: at the writer's own mapper call a configured family is handed the family
        # base in r10 (STARS-FIX); every other site and every vanilla/refused answer keeps r10
        award = site + 5 == pm.WRITER_RET and want == pm.STAGE_SLOT and stub_answer == -1

        def answer_for():
            out = {"rax": want}
            if award:
                # the wrapper writes the family base as a 32-bit move into the saved r10: the caller's
                # upper half survives, exactly like the writer's own `mov r10d, edx`
                out["r10"] = (seeds["r10"] & ~0xFFFFFFFF) | (cls - cls % 10)
            return out

        def preserve_for():
            return {k: v for k, v in regs.items() if k not in (("rax", "r10") if award else ("rax",))}

        def fixture(write):
            write(UNIT, rec)
            write(HOLDER + deref, struct.pack("<Q", UNIT))
            write(JOBRANK, jobs)
            write(G_ROWS, struct.pack("<Q", JOBRANK))
            write(G_COUNT, struct.pack("<I", len(jobs) // 20))

        got = abi.execute(patched, info, site, kind="call", fixture=fixture, regs=regs,
                          stubs=[(pm.MAPPER, abi.clobbering_stub(stub_answer))],
                          expect_args={"rcx": cls}, answer=answer_for(),
                          preserve=preserve_for(),
                          writable=[(UNIT, UNIT + 0x4800)], probe=[(UNIT, 0x4800)])
        assert got["stubs_entered"] == [hex(pm.MAPPER)], (name, got["stubs_entered"])
        if expect is not None:
            assert got["probed"][hex(UNIT)] == expect, f"{name} at {site:#x}: the record is not as expected"
        runs.append(dict(case=name, site=hex(site), cls=cls, answer=hex(got["answer"]["rax"]),
                         r10=hex(got["answer"]["r10"]),
                         instructions=got["instructions"], calls=got["calls"], writes=got["writes"]))
        return got

    for site, ret, reg, deref in sites():
        one(site, reg, deref, 1350, unit(), -1, pm.STAGE_SLOT, "stage", expect=staged_once)
        one(site, reg, deref, 1010, unit(), 12, 12, "vanilla-passthrough", expect=unit())
        one(site, reg, deref, 1350, unit(spare=b"\x91" * SPARE), -1, 0xFFFFFFFF, "refused",
            expect=unit(spare=b"\x91" * SPARE))

    def switch_case():
        """a real stage switch, ABI-entered: the same record the behaviour proof produces, byte for byte"""
        real = Machine(patched)
        fresh = real.run(0x14015F500, "rbx", 1350, unit(), job_rows=jobs)
        reference = unit(base=fresh["unit"], stage=struct.pack("<6I", 10, 20, 0, 0, 0, 0))
        behaviour = real.run(0x14015F500, "rbx", 1360, reference, job_rows=jobs)
        got = one(0x14015F500, "rbx", 0, 1360, reference, -1, pm.STAGE_SLOT, "stage-switch")
        abi_record = got["probed"][hex(UNIT)]
        assert abi_record == behaviour["unit"], "ABI and real-mapper runs disagree on the record"
        assert spare(abi_record)[:9] == b"\xc5\x01\x88\x00\x87\x00\x02\x0a\x00", spare(abi_record)[:9].hex()
        return dict(answer=pm.STAGE_SLOT, record_bytes=0x4800, identical_to_real_mapper=True)

    return [("abi-sites", lambda: dict(sites=len(pm.MAPPER_CALLS), runs=len(runs),
                                       cases=sorted({r["case"] for r in runs}),
                                       max_instructions=max(r["instructions"] for r in runs),
                                       calls_per_run=max(r["calls"] for r in runs),
                                       all_registers_preserved=True, first=runs[:3])),
            ("abi-stage-switch-bytes", switch_case)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", type=Path, required=True,
                    help="path to an offline copy of the pinned original executable")
    ap.add_argument("--build-only", action="store_true", help="build and validate the patch without importing Unicorn")
    ap.add_argument("--abi", "--site-entry", action="store_true",
                    help="additionally enter every patched .d5pm site the way its caller does")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    from d5lib import packedmasteryhook as pm
    original = args.original.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, "not the pinned original exe"
    patched = pm.build_patch(original, FAMILIES)
    info = pm.section_info(patched)
    build = dict(families=FAMILIES, section=info["section"], base=hex(info["base"]), size=info["size"],
                 mapper_sites=len(pm.MAPPER_CALLS), original_sha256=ORIGINAL_SHA,
                 patched_sha256=hashlib.sha256(patched).hexdigest(),
                 table=pm.read_families(patched))
    print(f"section {info['section']} at {info['base']:#x}, {info['size']} bytes; "
          f"{len(pm.MAPPER_CALLS)} mapper sites; families {pm.read_families(patched)}")
    if args.build_only:
        build["note"] = "fixtures and patch built; Unicorn not imported"
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(build, indent=1) + "\n")
        return 0
    checks_ = checks(original, patched, pm)
    if args.abi:
        checks_ += abi_cases(original, patched, pm)
    plan, passed = [], True
    for name, fn in checks_:
        try:
            detail = fn()
            plan.append(dict(name=name, ok=True, detail=_jsonable(detail)))
            print(f"PASS {name}")
        except Exception as exc:
            passed = False
            import traceback
            plan.append(dict(name=name, ok=False, error=f"{type(exc).__name__}: {exc}",
                             trace=traceback.format_exc().splitlines()[-6:]))
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    report = dict(mode="abi-site-entry" if args.abi else "behaviour", build=build, checks=plan, passed=passed,
                  limitations=[
                      "The original mapper is executed for real in the behaviour checks; --abi replaces it with a "
                      "clobbering stub to prove the wrapper's own register contract.",
                      "The wrapper is proven from the game's own call instructions (all 16 sites), not from its "
                      "entry: the return address it reads is the real one pushed by each caller.",
                      "The JobRank table and its two globals are fixtures; the game's real rows are not read here.",
                      "Executed paths only: Windows unwind dispatch and native gameplay are not executed.  The "
                      ".d5pm unwind records are checked structurally (static audit + exepatch), not by an exception.",
                      "No writer, award, unlock or UI path is patched in this step, so none is proven here."])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    print(f"[{report['mode']}] {sum(c['ok'] for c in plan)}/{len(plan)} checks passed")
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
