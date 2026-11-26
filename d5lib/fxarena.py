"""The vertex arena and the runtime's on-demand effect loads (POOLLEAK1, 2026-11-20).

Every 3D model the game builds (effect models, map objects) takes one block from a fixed arena: 1024 block records
(24 bytes: block, size, alignment) in front of a 25 MB block, set up once at start.  The allocator scans the records
for a free one and writes through NULL when there is none (LIVE1120G crash in the 9460a641 build: write fault in the
record scan, ~650 on-demand loads into a session).  The model build step (FX_FINISH, 0x1402fa580 in the kit's
build) takes the block and stores it in the manager slot (+0x12528); the release (FX_RELEASE 0x1404001f0 -> model
free) frees the block stored there.  The loader the runtime calls (FX_LOAD 0x140306c40) already ends with the build
step, so a second build orphans the first block for good.

This module checks that, offline:
  exe_facts(exe)          what the exe's load / build / release code does (capstone; addresses via exemap)
  emulate(exe, n, extra)  runs the game's own build step and release n times in Unicorn, with the runtime's
                          sequence (extra=True: loader-equivalent build + FX_FINISH, the old runtime; False: once),
                          and returns the arena's record count after each cycle, and the fault if the allocator
                          writes through NULL
  runtime_policy(src)     whether d5fx.inc.c's fx_load calls FX_FINISH only when the loader took no block
  simulate(...)           a session of casts against the runtime's cache (room, release of the oldest unused):
                          arena records in use after each cast, for the old and the new load sequence
"""
import re
import struct

FX_LOAD_VA = 0x140306C40
FX_FINISH_VA = 0x1402FA580
FX_RELEASE_VA = 0x1404001F0
FX_MGR_VA = 0x146A34BF8
ARENA_RECORDS = 0x400
REC_SIZE = 24
SLOT_STRIDE = 0xD0
SLOT_BASE = 0x12478                       # manager + slot * 0xd0 + SLOT_BASE: the slot's record (0xd0 bytes)
SLOT_BLOCK = 0x12528                      # ... the vertex block's arena record
FX_SLOT_BASE = 700
CACHE_ROOM = 400                          # d5fx.inc.c g_fx_room default (slots 700..1099)


def _cs():
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    return md


class _Image:
    def __init__(self, exe):
        import pefile
        self.pe = pefile.PE(data=exe, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.img = self.pe.get_memory_mapped_image()
        self.funcs = sorted((self.base + e.struct.BeginAddress, self.base + e.struct.EndAddress)
                            for e in self._pdata())

    def _pdata(self):
        self.pe.parse_data_directories(directories=[3])
        return getattr(self.pe, "DIRECTORY_ENTRY_EXCEPTION", [])

    def func_end(self, va):
        """end of the function at va, following chained .pdata entries (a range that starts where one ends)"""
        ends = {a: b for a, b in self.funcs}
        for a, b in self.funcs:
            if a <= va < b:
                while b in ends:
                    b = ends[b]
                return b
        return va + 0x400

    def code(self, va, n=None):
        n = n or (self.func_end(va) - va)
        return list(_cs().disasm(self.img[va - self.base:va - self.base + n], va))


def _target(ins):
    try:
        return int(ins.op_str, 16)
    except ValueError:
        return None


def _rip_target(ins):
    m = re.search(r"\[rip ([+-]) (0x[0-9a-f]+|\d+)\]", ins.op_str)
    if not m:
        return None
    d = int(m.group(2), 0)
    return ins.address + ins.size + (d if m.group(1) == "+" else -d)


def exe_facts(exe, translator=None):
    """{'load', 'finish', 'release', 'model_free', 'alloc', 'record_take', 'arena', 'loader_builds',
    'release_frees', 'job_builds_twice'} for this exe (addresses of this build)"""
    from . import exemap
    t = translator or exemap.translator_for(exe)
    im = _Image(exe)
    load, finish, release, mgr = t(FX_LOAD_VA), t(FX_FINISH_VA), t(FX_RELEASE_VA), t(FX_MGR_VA)
    out = {"load": load, "finish": finish, "release": release, "manager": mgr}
    fin = im.code(finish)
    # the build step's allocator call: lea rcx, [rip + arena] ... call alloc
    for i, ins in enumerate(fin[:40]):
        if ins.mnemonic == "lea" and ins.op_str.startswith("rcx, [rip"):
            for j in fin[i + 1:i + 6]:
                if j.mnemonic == "call":
                    out["arena"], out["alloc"] = _rip_target(ins), _target(j)
                    break
            if "arena" in out:
                break
    alloc = im.code(out["alloc"]) if out.get("alloc") else []
    takes = [_target(i) for i in alloc if i.mnemonic == "call"]
    out["record_take"] = takes[0] if takes else None
    # the loader: calls the build step on its only path (no branch skips the call)
    ld = im.code(load)
    calls = [i for i in ld if i.mnemonic == "call" and _target(i) == finish]
    out["loader_builds"] = len(calls)
    if calls:
        site = calls[0].address
        skipped = [i for i in ld if i.mnemonic.startswith("j") and i.address < site
                   and (_target(i) or 0) > site]
        out["loader_build_unconditional"] = not skipped
    # the release: calls the model free, which frees the block stored at +0x12528 (one 'dec dword [arena + 4]')
    rel = im.code(release)
    free = [_target(i) for i in rel if i.mnemonic == "call"]
    out["model_free"] = free[0] if free else None
    if out["model_free"]:
        mf = im.code(out["model_free"])
        decs = [i for i in mf if i.mnemonic == "dec" and _rip_target(i) == out.get("arena", -1) + 4]
        out["release_frees"] = len(decs)
        uses = [i for i in mf if "0x12528" in i.op_str]
        out["release_reads_slot_block"] = bool(uses)
    return out


# ----------------------------------------------------------------------------------------- emulation
class _Emu:
    STACK, STACK_N = 0x7FF000000000, 0x100000
    HEAP, HEAP_N = 0x7E0000000000, 0x4000000
    RET = 0x7FF000200000

    def __init__(self, exe, facts):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
        from unicorn.x86_const import UC_X86_REG_RSP
        self.f = facts
        self.im = _Image(exe)
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_64)
        size = (len(self.im.img) + 0xFFF) & ~0xFFF
        uc.mem_map(self.im.base, size)
        uc.mem_write(self.im.base, self.im.img)
        uc.mem_map(self.STACK, self.STACK_N)
        uc.mem_map(self.HEAP, self.HEAP_N)
        uc.mem_map(self.RET, 0x1000)
        uc.mem_write(self.RET, b"\xf4")
        self.bump = self.HEAP
        self.fault = None
        self._stubs = {}
        self._find_stubs()
        for va in self._stubs:
            uc.hook_add(UC_HOOK_CODE, self._on_stub, begin=va, end=va)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.rsp0 = self.STACK + self.STACK_N - 0x1000
        uc.reg_write(UC_X86_REG_RSP, self.rsp0)
        self._setup_arena()
        self._setup_manager()

    def malloc(self, n):
        p = self.bump
        self.bump += (max(int(n), 1) + 0xF) & ~0xF
        if self.bump > self.HEAP + self.HEAP_N:
            raise MemoryError("emulated heap full")
        return p

    def _find_stubs(self):
        """the callees of the build step, the model free and the release that are not the arena's own code"""
        f, im = self.f, self.im
        keep = {f["alloc"], f["record_take"], f["model_free"], f["finish"], f["release"]}
        roles = {}
        self.job_list = None
        for fn in (f["finish"], f["model_free"], f["release"]):
            code = im.code(fn)
            for k, ins in enumerate(code):
                if ins.mnemonic == "call":
                    t = _target(ins)
                    if t and t not in keep:
                        back = code[max(0, k - 3):k]
                        heap_arg = any(b.mnemonic == "mov" and b.op_str.startswith("rcx, qword ptr [rip")
                                       for b in back)
                        size_arg = any(b.op_str.startswith("edx,") for b in back)
                        if heap_arg and size_arg:
                            roles[t] = "malloc"            # mspace malloc(heap, n)
                        roles.setdefault(t, "ret0")
                if (fn == f["model_free"] and self.job_list is None and ins.mnemonic == "mov"
                        and ins.op_str.startswith("r15, qword ptr [rip")):
                    self.job_list = _rip_target(ins)     # the deferred-free job list (begin, end, capacity)
        # the per-thread allocator state: called twice in a row with no arguments in the model free
        mf = [i for i in im.code(f["model_free"]) if i.mnemonic == "call"]
        for a, b in zip(mf, mf[1:]):
            if _target(a) == _target(b) and roles.get(_target(a)) == "ret0":
                roles[_target(a)] = "tls"
        # memset: the callee given (dst, 0, n) right before the slot record is cleared (last call of the free)
        roles[_target(mf[-1])] = "memset"
        self._stubs = roles
        self.tls = None

    def _on_stub(self, uc, addr, size, _):
        from unicorn.x86_const import (UC_X86_REG_RAX, UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8,
                                       UC_X86_REG_RSP, UC_X86_REG_RIP)
        role = self._stubs[addr]
        rax = 0
        if role == "malloc":
            rax = self.malloc(uc.reg_read(UC_X86_REG_RDX) & 0xFFFFFFFF)
        elif role == "tls":
            if self.tls is None:
                self.tls = self.malloc(0x2100)
            rax = self.tls
        elif role == "memset":
            dst, val, n = uc.reg_read(UC_X86_REG_RCX), uc.reg_read(UC_X86_REG_RDX) & 0xFF, uc.reg_read(UC_X86_REG_R8)
            if dst and 0 < n < 0x1000000:
                uc.mem_write(dst, bytes([val]) * n)
            rax = dst
        rsp = uc.reg_read(UC_X86_REG_RSP)
        ret = struct.unpack("<Q", uc.mem_read(rsp, 8))[0]
        uc.reg_write(UC_X86_REG_RSP, rsp + 8)
        uc.reg_write(UC_X86_REG_RAX, rax)
        uc.reg_write(UC_X86_REG_RIP, ret)

    def _on_unmapped(self, uc, access, addr, size, value, _):
        from unicorn.x86_const import UC_X86_REG_RIP
        self.fault = (uc.reg_read(UC_X86_REG_RIP), addr, access)
        return False

    def q(self, va, v=None):
        if v is None:
            return struct.unpack("<Q", self.uc.mem_read(va, 8))[0]
        self.uc.mem_write(va, struct.pack("<Q", v))

    def d(self, va, v=None):
        if v is None:
            return struct.unpack("<i", self.uc.mem_read(va, 4))[0]
        self.uc.mem_write(va, struct.pack("<i", v))

    def _setup_arena(self):
        a = self.f["arena"]
        base = self.malloc(ARENA_RECORDS * REC_SIZE + 0x18FA000)
        self.d(a + 0x0, ARENA_RECORDS)
        self.d(a + 0x4, 0)
        self.d(a + 0x8, 0x18FA000)
        self.d(a + 0xC, 0)
        self.d(a + 0x10, 0)
        self.q(a + 0x18, base + ARENA_RECORDS * REC_SIZE)
        self.d(a + 0x20, 1)
        self.q(a + 0x28, base)
        self.q(a + 0x30, 0)
        self.d(a + 0x50, 0)
        vec = self.malloc(0x40)                 # the deferred-free job list: begin, end, capacity
        buf = self.malloc(0x100000)
        self.q(vec + 0, buf)
        self.q(vec + 8, buf)
        self.q(vec + 0x10, buf + 0x100000)
        self.q(self.job_list, vec)
        self.vec = vec

    def _setup_manager(self):
        self.mgr = self.malloc(SLOT_BASE + 1200 * SLOT_STRIDE)
        self.q(self.f["manager"], self.mgr)
        self.cache = self.malloc(0x30 * 512)
        self.src = self.malloc(0x24 * 64)
        self.zero = self.malloc(16)
        self.gpu = self.malloc(0x40)

    def arena_used(self):
        return self.d(self.f["arena"] + 4)

    def slot(self, s):
        return self.mgr + s * SLOT_STRIDE + SLOT_BASE

    def fill_slot(self, s, verts=4):
        r = self.slot(s)
        self.uc.mem_write(r, b"\0" * SLOT_STRIDE)
        self.q(r + 8, self.malloc(0x40))                       # the model data (the free returns early without)
        self.uc.mem_write(r + 0, b"\x00\x01\x01")              # +0 data not owned, +1 textures not owned, +2 kind 1
        self.d(r + (0x12508 - SLOT_BASE), verts)
        self.q(r + (0x12510 - SLOT_BASE), self.src)
        self.q(r + (0x12538 - SLOT_BASE), self.gpu)
        self.q(r + (0x12500 - SLOT_BASE), self.zero)
        self.q(r + (0x124F0 - SLOT_BASE), self.zero)
        self.q(self.vec + 8, self.q(self.vec + 0))            # the job list never fills

    def call(self, va, *args):
        from unicorn.x86_const import UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_RSP, UC_X86_REG_RAX
        uc = self.uc
        regs = (UC_X86_REG_RCX, UC_X86_REG_RDX)
        for r, v in zip(regs, args):
            uc.reg_write(r, v)
        rsp = self.rsp0 - 0x80
        uc.mem_write(rsp, struct.pack("<Q", self.RET))
        uc.reg_write(UC_X86_REG_RSP, rsp)
        self.fault = None
        from unicorn import UcError
        try:
            uc.emu_start(va, self.RET, count=2_000_000)
        except UcError:
            if self.fault is None:
                raise
            return None
        return uc.reg_read(UC_X86_REG_RAX)

    def cycle(self, slot, builds, release=True):
        """one on-demand load into `slot` (`builds` runs of the build step) and, optionally, its release"""
        self.fill_slot(slot)
        for _ in range(builds):
            if self.call(self.f["finish"], self.mgr, slot) is None and self.fault:
                return False
        if release:
            k = slot - FX_SLOT_BASE
            e = self.cache + k * 0x30
            self.uc.mem_write(e, b"\0" * 0x30)
            self.uc.mem_write(e, b"\x01")
            self.d(e + 4, 9000 + k)
            self.d(e + 8, slot)
            if self.call(self.f["release"], self.cache, k) is None and self.fault:
                return False
        return True


def emulate(exe, n, extra, facts=None, keep=0):
    """n load+release cycles through the game's build step and release, `keep` models left loaded first.
    extra=True: the old runtime (loader's build + FX_FINISH = two builds per load); False: one build.
    -> {'used': [arena records after each cycle], 'fault': (rip, address, access) or None, 'cycles': done}"""
    facts = facts or exe_facts(exe)
    emu = _Emu(exe, facts)
    for i in range(keep):
        emu.cycle(FX_SLOT_BASE + 100 + (i % 300), 2 if extra else 1, release=False)
    used = []
    for i in range(n):
        ok = emu.cycle(FX_SLOT_BASE + (i % 100), 2 if extra else 1)
        if not ok:
            return {"used": used, "fault": emu.fault, "cycles": i, "facts": facts}
        used.append(emu.arena_used())
    return {"used": used, "fault": None, "cycles": n, "facts": facts}


# ----------------------------------------------------------------------------------------- runtime source
def runtime_policy(src):
    """'once': fx_load calls FX_FINISH only when the loader took no arena block; 'twice': always (the leak);
    None: no FX_FINISH call found"""
    m = re.search(r"static int fx_load\(.*?\n}\n", src, re.S)
    body = m.group(0) if m else ""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if "G(FX_FINISH_VA)" in line:
            ctx = "\n".join(lines[max(0, i - 4):i])
            if re.search(r"if \(a && a->used > before\)", ctx) or "else {" in ctx and "used > before" in ctx:
                return "once"
            return "twice"
    return None


# ----------------------------------------------------------------------------------------- session model
def simulate(casts, lists, policy, room=CACHE_ROOM, baseline=0, records=ARENA_RECORDS, spare=0):
    """casts: [event id started per cast]; lists: {event: [model ids it prefetches]}.  The cache keeps `room`
    on-demand models and releases the one asked for longest ago (d5fx.inc.c fx_free_index, FX_RECENT ignored).
    Each load takes 2 records with policy 'twice' (one orphaned), 1 with 'once'; a release frees 1.
    -> {'used': [records in use after each cast], 'orphans', 'loads', 'exhausted_at': cast index or None}"""
    cache, loads, orphans = [], 0, 0
    used, exhausted = [], None
    per_load = 2 if policy == "twice" else 1
    for n, ev in enumerate(casts):
        for mid in lists.get(ev, []):
            if mid in cache:
                cache.remove(mid)
                cache.append(mid)
                continue
            if len(cache) >= room:
                cache.pop(0)
            if baseline + len(cache) + orphans + per_load > records - spare:
                if exhausted is None:
                    exhausted = n
                if spare:
                    continue                    # the guard refuses the load
            cache.append(mid)
            loads += 1
            orphans += per_load - 1
        used.append(baseline + len(cache) + orphans)
    return {"used": used, "orphans": orphans, "loads": loads, "exhausted_at": exhausted}
