"""Finding the kit's patch sites in another build of disgaea5.exe.

The kit's exe patches and its runtime (d5lib/native) name game code and data by address -- addresses of the build
the kit was made on (KNOWN_SHA1, October 2018).  Another build moves code and data around.  This module finds every
address the kit uses in another exe, without shipping anything of the game:

    reference (made once on the known build, data/exe_ref.json.gz): for every address the kit's sources name, the
    function it lies in (from .pdata), that function's size and fingerprint -- its bytes with everything that
    depends on where code and data lie masked out (rip-relative displacements, rel32 branch targets, absolute
    image addresses) -- and the offset in it; with the fingerprints of the functions around it, to tell identical
    functions apart.  An address in data: the instructions that reference it (function fingerprint, instruction
    offset, the address's distance from the referenced spot).

    locate(exe): fingerprints the other exe's functions of the sizes needed and maps every reference address to its
    place there -> {old va: new va}, and what could not be found.

An exe wrapped by Steam's DRM (its code encrypted on disk, section .bind) can't be read this way: report() says so.
"""
import gzip
import hashlib
import json
import os
import re
import struct

IMAGE_BASE = 0x140000000
KNOWN_SHA1 = "436eefd2a29466e2ecaa5a57fd65255009896581"
REF_PATH = os.path.join(os.path.dirname(__file__), "data", "exe_ref.json.gz")
# a game address as written in Python, assembly or C (0x140455e93ULL: the C suffix is left out of the match)
ADDR_RE = re.compile(r"0x14[0-9a-fA-F]{7}(?=[uUlL]*\b)")
NEIGHBOURS = 2


# ------------------------------------------------------------------------------------------------- the exe
class Exe:
    def __init__(self, data):
        import pefile
        self.data = data
        self.pe = pefile.PE(data=data, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.sections = [(s.Name.rstrip(b"\0").decode("latin1"), s.VirtualAddress, s.Misc_VirtualSize,
                          s.PointerToRawData, s.SizeOfRawData, s.Characteristics) for s in self.pe.sections]
        self._funcs = None
        self._cs = None

    def section_of(self, rva):
        for s in self.sections:
            if s[1] <= rva < s[1] + max(s[2], s[4]):
                return s
        return None

    def read(self, rva, n):
        s = self.section_of(rva)
        if s is None:
            return b""
        off = s[3] + rva - s[1]
        return self.data[off:off + n]

    def functions(self):
        """[(start rva, end rva)]: the functions of .pdata (RUNTIME_FUNCTION) and, in the code between them, the leaf
        functions (no unwind info), told apart by the int3 padding before 16-byte boundaries; sorted"""
        if self._funcs is None:
            out = set()
            for name, va, vs, raw, rs, ch in self.sections:
                if name == ".pdata":
                    blob = self.data[raw:raw + min(vs, rs)]
                    for k in range(0, len(blob) - 11, 12):
                        b, e, u = struct.unpack_from("<III", blob, k)
                        if b and e > b:
                            out.add((b, e))
            listed = sorted(out)
            self._listed = listed
            text = next((x for x in self.sections if x[0] == ".text"), None)
            if text is not None:
                cur = text[1]
                for b, e in listed + [(text[1] + text[2], text[1] + text[2])]:
                    if b > cur:
                        out.update(self._leaves(cur, b))
                    cur = max(cur, e)
            self._funcs = sorted(out)
        return self._funcs

    def _leaves(self, start, end):
        """code blocks in [start, end) between int3 paddings (a block starts on a 16-byte boundary)"""
        blob = self.read(start, end - start)
        out = []
        i = 0
        n = len(blob)
        while i < n:
            while i < n and (blob[i] == 0xCC or (start + i) % 16):
                if blob[i] != 0xCC and (start + i) % 16:
                    break
                i += 1
            if i >= n:
                break
            j = i
            while j < n and not (blob[j] == 0xCC and all(c == 0xCC for c in blob[j:min(n, (start + j + 16) // 16 * 16 - start)])):
                j += 1
            if j - i >= 4:
                out.append((start + i, start + j))
            i = max(j, i + 1)
            while i < n and blob[i] == 0xCC:
                i += 1
        return out

    def imports(self):
        """{iat slot rva: "dll!function"} of the import table"""
        if getattr(self, "_imports", None) is None:
            out = {}
            try:
                self.pe.parse_data_directories(directories=[1])           # IMAGE_DIRECTORY_ENTRY_IMPORT
                for d in getattr(self.pe, "DIRECTORY_ENTRY_IMPORT", []):
                    for imp in d.imports:
                        name = imp.name.decode() if imp.name else f"#{imp.ordinal}"
                        out[imp.address - self.base] = f"{d.dll.decode().lower()}!{name}"
            except Exception:
                pass
            self._imports = out
        return self._imports

    def wrapped(self):
        """Steam DRM wrapper: its own section, the code encrypted on disk"""
        return any(s[0] == ".bind" for s in self.sections)

    def _capstone(self):
        if self._cs is None:
            from capstone import Cs, CS_ARCH_X86, CS_MODE_64
            self._cs = Cs(CS_ARCH_X86, CS_MODE_64)
            self._cs.detail = True
        return self._cs

    def fingerprint(self, start, end):
        """(hex digest of the function's position-independent bytes, [(insn offset, rip-relative target rva)])"""
        from capstone.x86 import X86_OP_MEM, X86_OP_IMM, X86_REG_RIP, X86_REG_INVALID
        code = bytearray(self.read(start, end - start))
        refs = []
        cs = self._capstone()
        pos = 0
        image = self.pe.OPTIONAL_HEADER.SizeOfImage
        for ins in cs.disasm(bytes(code), self.base + start):
            o = ins.address - self.base - start
            pos = o + ins.size
            for op in ins.operands:
                if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP and ins.disp_size:
                    d = o + ins.disp_offset
                    code[d:d + ins.disp_size] = b"\0" * ins.disp_size
                    refs.append((o, ins.address + ins.size + op.mem.disp - self.base))
                elif (op.type == X86_OP_MEM and op.mem.index != X86_REG_INVALID and ins.disp_size == 4
                      and 0x1000 <= op.mem.disp < image):
                    # [image base + index * n + table rva]: a switch's jump / index table
                    d = o + ins.disp_offset
                    code[d:d + 4] = b"\0" * 4
                    refs.append((o, op.mem.disp))
                elif op.type == X86_OP_IMM:
                    imm = op.imm & 0xFFFFFFFFFFFFFFFF
                    if ins.group(1) or ins.group(7) or ins.mnemonic.startswith("j") or ins.mnemonic == "call":
                        if ins.imm_size == 4:             # rel32: where the target lies
                            d = o + ins.imm_offset
                            code[d:d + 4] = b"\0" * 4
                    elif self.base <= imm < self.base + 0x10000000 and ins.imm_size in (4, 8):
                        d = o + ins.imm_offset
                        code[d:d + ins.imm_size] = b"\0" * ins.imm_size
        if pos < len(code):                               # undecodable tail (data in code): kept as it is
            pass
        return hashlib.sha1(bytes(code)).hexdigest()[:20], refs


# ------------------------------------------------------------------------------------------------- reference
def kit_addresses(kit_dir):
    """every game address (0x14xxxxxxx) the kit's sources name"""
    out = set()
    for root, _, files in os.walk(kit_dir):
        if any(p in root for p in ("__pycache__", os.sep + "mods", os.sep + "state", os.sep + "runtime",
                                   os.sep + "_research", os.sep + "_extracted")):
            continue
        for f in files:
            if f.endswith((".py", ".c", ".h")) or (f.endswith((".json", ".tsv")) and os.path.basename(root) == "data"
                                                   and not f.startswith("exe_") and f != "script_opcodes.tsv"):
                with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                    out.update(int(m.group(0), 16) for m in ADDR_RE.finditer(fh.read()))
    return sorted(out)


def _containing(funcs, rva):
    import bisect
    i = bisect.bisect_right(funcs, (rva, 1 << 62)) - 1
    if i >= 0 and funcs[i][0] <= rva < funcs[i][1]:
        return i
    return None


def build_reference(exe_data, addresses, log=print):
    """the reference of the known build (see the module doc) -> dict"""
    import bisect
    ex = Exe(exe_data)
    funcs = ex.functions()
    log(f"  fingerprinting {len(funcs)} functions ...")
    fps = [ex.fingerprint(s, e) for s, e in funcs]
    count = {}
    for h, _ in fps:
        count[h] = count.get(h, 0) + 1

    def near(i):
        return [fps[j][0] if 0 <= j < len(funcs) else None for j in range(i - NEIGHBOURS, i + NEIGHBOURS + 1)
                if j != i]

    def anchor(i):
        """the nearest function before i whose fingerprint is unique: [fp, size, distance]"""
        for j in range(i - 1, max(-1, i - 400), -1):
            if count[fps[j][0]] == 1:
                return [fps[j][0], funcs[j][1] - funcs[j][0], funcs[i][0] - funcs[j][0]]
        return None
    sites = {}
    data_targets = {}
    imports = ex.imports()
    referenced = {t for _, rr in fps for _, t in rr}
    for va in addresses:
        rva = va - IMAGE_BASE
        if ex.section_of(rva) is None:
            continue
        if rva in imports:                                   # an import slot: found by name
            sites[hex(va)] = {"kind": "import", "name": imports[rva]}
            continue
        in_listed = _containing(ex._listed, rva) is not None
        if not in_listed and rva in referenced:              # data in the code section (a switch's tables)
            data_targets[rva] = va
            continue
        i = _containing(funcs, rva)
        if i is not None:
            s, e = funcs[i]
            site = {"kind": "code", "size": e - s, "fp": fps[i][0], "off": rva - s, "near": near(i)}
            if count[fps[i][0]] > 1:
                site["anchor"] = anchor(i)
            sites[hex(va)] = site
        else:
            data_targets[rva] = va
    if data_targets:
        # instructions of functions found unambiguously that reference the data addresses (or a spot shortly
        # before them: a field of a structure)
        keys = sorted(data_targets)
        refs = {va: [] for va in data_targets.values()}
        for i in range(len(funcs)):
            h, rr = fps[i]
            if count[h] != 1:
                continue
            for o, t in rr:
                k = bisect.bisect_right(keys, t + 0x400) - 1
                while k >= 0 and keys[k] >= t:
                    va = data_targets[keys[k]]
                    if len(refs[va]) < 6:
                        s, e = funcs[i]
                        refs[va].append([h, e - s, o, keys[k] - t])
                    k -= 1
        for va, rr in refs.items():
            sites[hex(va)] = {"kind": "data", "refs": rr, "section": ex.section_of(va - IMAGE_BASE)[0]}
    return {"build": KNOWN_SHA1, "sites": sites}


def load_reference(path=REF_PATH):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def save_reference(ref, path=REF_PATH):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(ref, f, separators=(",", ":"))


# ------------------------------------------------------------------------------------------------- locate
def locate(exe_data, ref=None, log=None):
    """the reference's addresses in another exe -> (map {old va: new va}, missing [old va], details)"""
    ref = ref or load_reference()
    ex = Exe(exe_data)
    funcs = ex.functions()
    sizes = {}
    for i, (s, e) in enumerate(funcs):
        sizes.setdefault(e - s, []).append(i)
    fp_cache = {}

    def fp(i):
        if i not in fp_cache:
            fp_cache[i] = ex.fingerprint(*funcs[i])
        return fp_cache[i]

    def find(size, h, near=None):
        """function index in the new exe with this size and fingerprint (neighbours break ties) or None"""
        cands = [i for i in sizes.get(size, []) if fp(i)[0] == h]
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1 and near:
            def score(i):
                got = [fp(j)[0] if 0 <= j < len(funcs) else None
                       for j in range(i - NEIGHBOURS, i + NEIGHBOURS + 1) if j != i]
                return sum(1 for a, b in zip(got, near) if a == b and a is not None)
            best = sorted(cands, key=score, reverse=True)
            if score(best[0]) > score(best[1]):
                return best[0]
        return None
    out, missing, details = {}, [], {}
    by_name = {v: k for k, v in ex.imports().items()}
    for key, s in ref["sites"].items():
        va = int(key, 16)
        if s["kind"] == "import":
            if s["name"] in by_name:
                out[va] = ex.base + by_name[s["name"]]
            else:
                missing.append(va)
            continue
        if s["kind"] == "code":
            i = find(s["size"], s["fp"], s.get("near"))
            if i is None and s.get("anchor"):
                # one of several identical functions: found from the nearest unique function before it
                ah, asize, dist = s["anchor"]
                j = find(asize, ah)
                if j is not None:
                    k = _containing(funcs, funcs[j][0] + dist)
                    if k is not None and funcs[k][0] == funcs[j][0] + dist and fp(k)[0] == s["fp"]:
                        i = k
            if i is None:
                missing.append(va)
                continue
            out[va] = ex.base + funcs[i][0] + s["off"]
        else:
            votes = {}
            for r in s["refs"]:
                h, size, o, delta = r[:4]
                i = find(size, h, r[4] if len(r) > 4 else None)
                if i is None:
                    continue
                for oo, t in fp(i)[1]:
                    if oo == o:
                        nv = ex.base + t + delta
                        votes[nv] = votes.get(nv, 0) + 1
            if votes:
                nv, n = max(votes.items(), key=lambda kv: kv[1])
                out[va] = nv
                details[va] = {"votes": n, "of": len(s["refs"]), "agree": n == sum(votes.values())}
            else:
                missing.append(va)
    if log:
        log(f"  {len(out)} of {len(ref['sites'])} kit addresses found, {len(missing)} not")
    return out, sorted(missing), details


def report(exe_path, ref=None):
    """a plain-text compatibility report of an exe (for a player to paste: nothing of the game in it)"""
    import datetime
    with open(exe_path, "rb") as f:
        data = f.read()
    ex = Exe(data)
    sha1 = hashlib.sha1(data).hexdigest()
    ts = ex.pe.FILE_HEADER.TimeDateStamp
    lines = [f"disgaea5.exe sha1 {sha1}  size {len(data)}",
             f"built {datetime.datetime.utcfromtimestamp(ts):%Y-%m-%d %H:%M} UTC  "
             f"entry {ex.pe.OPTIONAL_HEADER.AddressOfEntryPoint:#x}  image {ex.pe.OPTIONAL_HEADER.SizeOfImage:#x}",
             "sections: " + ", ".join(f"{n} {va:#x}+{vs:#x}" for n, va, vs, *_ in ex.sections),
             f"functions (.pdata): {len(ex.functions())}"]
    if sha1 == KNOWN_SHA1:
        lines.append("this is the build the kit was made on")
    if ex.wrapped():
        lines.append("WRAPPED: Steam DRM section .bind present (code encrypted on disk)")
    try:
        found, missing, details = locate(data, ref)
        total = len(found) + len(missing)
        lines.append(f"kit addresses found: {len(found)} of {total}")
        moved = sum(1 for a, b in found.items() if a != b)
        lines.append(f"moved: {moved}   same place: {len(found) - moved}")
        if missing:
            lines.append("not found: " + " ".join(f"{a:#x}" for a in missing[:400]))
    except Exception as e:
        lines.append(f"locate failed: {e}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------- translation
class Unmapped(KeyError):
    """a game address the kit uses that this build of the game doesn't have (the feature can't be installed)"""


class Translator:
    """old (known build) va -> this build's va.  identity for the known build; else the shipped map
    (data/exe_map_<sha1[:12]>.json, made by tools/exe_port.py and checked) or one found by locate()"""

    def __init__(self, sha1, mapping=None, source="identity", image_end=None):
        self.sha1 = sha1
        self.map = mapping
        self.source = source
        self.image_end = image_end          # va where this build's own image ends: kit sections lie past it

    @property
    def identity(self):
        return self.map is None

    @property
    def id(self):
        return "launch" if self.identity else self.sha1[:12]

    def has(self, va):
        return self.identity or int(va) in self.map

    def __call__(self, va):
        va = int(va)
        if self.identity:
            return va
        try:
            return self.map[va]
        except KeyError:
            raise Unmapped(f"game address {va:#x} is not known for this build of the game ({self.sha1[:12]})")

    def text(self, src, strict=True):
        """every game address written in a source (assembly, C) translated; strict: one this build lacks raises
        Unmapped.  Addresses past this build's image (the kit's own sections) are left as they are."""
        if self.identity:
            return src
        end = self.image_end or (IMAGE_BASE + 0x10000000)

        def sub(m):
            va = int(m.group(0), 16)
            if va >= end or va <= IMAGE_BASE:          # the image base itself is the same in every build
                return m.group(0)
            if va in self.map:
                return f"{self.map[va]:#x}"
            if strict:
                raise Unmapped(f"game address {va:#x} is not known for this build of the game ({self.sha1[:12]})")
            return m.group(0)
        return ADDR_RE.sub(sub, src)


def _strip_c_comments(src):
    # same length (blanks, newlines kept): positions in the stripped text are positions in the source
    return re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src, flags=re.S)


def translate_c(t, src):
    """a C source for this build: addresses in the code translated (strictly), those in comments left alone"""
    if t.identity:
        return src
    code = _strip_c_comments(src)
    out, last = [], 0
    for m in ADDR_RE.finditer(code):
        out.append(src[last:m.start()])
        out.append(t.text(m.group(0)))
        last = m.end()
    out.append(src[last:])
    return "".join(out)


_translators = {}
ACTIVE = Translator(KNOWN_SHA1)


def shipped_maps():
    """the address maps the kit ships (d5lib/data/exe_map_<sha1[:12]>.json): one per checked build of the game"""
    d = os.path.dirname(REF_PATH)
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.startswith("exe_map_") and f.endswith(".json"))


def translator_from_map(path, image_end=None):
    """the Translator of a shipped map (its hand-checked entries win)"""
    with open(path) as f:
        d = json.load(f)
    m = {int(a, 16): int(b, 16) for a, b in d["map"].items()}
    m.update({int(a, 16): int(b, 16) for a, b in d.get("manual", {}).items()})
    end = image_end or (int(d["image_end"], 16) if "image_end" in d else None)
    return Translator(d["to"], m, "map", end)


def translator_for(exe_data, log=None):
    """the Translator of an original (unpatched) exe"""
    sha1 = hashlib.sha1(exe_data).hexdigest()
    if sha1 in _translators:
        return _translators[sha1]
    if sha1 == KNOWN_SHA1:
        t = Translator(sha1)
    else:
        ex = Exe(exe_data)
        end = ex.base + ex.pe.OPTIONAL_HEADER.SizeOfImage
        path = os.path.join(os.path.dirname(REF_PATH), f"exe_map_{sha1[:12]}.json")
        if os.path.exists(path):
            t = translator_from_map(path, end)
        else:
            found, missing, _ = locate(exe_data)
            t = Translator(sha1, found, "located", end)
            if log:
                log(f"  this game build ({sha1[:12]}) is not one the kit knows: {len(found)} of "
                    f"{len(found) + len(missing)} addresses found automatically")
    _translators[sha1] = t
    return t


def use(t):
    """make t the translator every exe patch and the runtime build use"""
    global ACTIVE
    ACTIVE = t
    return t


_cs_plain = None


def _target(ins):
    """absolute target of a rel32 branch / call or a rip-relative operand, and the field's (offset, size)"""
    from capstone.x86 import X86_OP_MEM, X86_OP_IMM, X86_REG_RIP
    for op in ins.operands:
        if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP and ins.disp_size:
            return ins.address + ins.size + op.mem.disp, (ins.disp_offset, ins.disp_size)
        if op.type == X86_OP_IMM and (ins.mnemonic.startswith("j") or ins.mnemonic == "call") and ins.imm_size == 4:
            return op.imm & 0xFFFFFFFFFFFFFFFF, (ins.imm_offset, 4)
    return None, None


def same_code(t, old_va, orig, new_va, new_bytes):
    """are new_bytes at new_va the instructions orig were at old_va (the known build)?  Equal bytes, except the
    displacement of a branch / call / rip-relative operand, which must point at the place its old target maps to"""
    if t.identity or orig == new_bytes:
        return orig == new_bytes
    if len(orig) != len(new_bytes):
        return False
    global _cs_plain
    if _cs_plain is None:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64
        _cs_plain = Cs(CS_ARCH_X86, CS_MODE_64)
        _cs_plain.detail = True
    a = list(_cs_plain.disasm(orig, old_va))
    b = list(_cs_plain.disasm(new_bytes, new_va))
    if sum(i.size for i in a) != len(orig) or len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.size != y.size or x.mnemonic != y.mnemonic:
            return False
        if x.bytes == y.bytes:
            continue
        tx, fx = _target(x)
        ty, fy = _target(y)
        if tx is None or ty is None or fx != fy:
            return False
        o, n = fx
        if x.bytes[:o] + x.bytes[o + n:] != y.bytes[:o] + y.bytes[o + n:]:
            return False
        if t.has(tx) and t(tx) != ty:
            return False
    return True


def site(pe, va, orig, what="patch site"):
    """the translated address of a hook site whose original instructions are `orig` (checked) -> new va"""
    t = ACTIVE
    nva = t(va)
    cur = pe.get_data(nva - IMAGE_BASE, len(orig))
    if not same_code(t, va, orig, nva, cur):
        raise ValueError(f"unexpected exe version: {what} {va:#x} doesn't match"
                         + ("" if t.identity else f" in this build of the game ({t.sha1[:12]})"))
    return nva


def at(va, plus=0):
    """the address in the game build being patched of a known-build address (+ plus), written for an assembly source
    in decimal: the translation of the source (Translator.text) leaves it as it is"""
    return str(ACTIVE(va) + plus)


def variant(table, default=None):
    """the build-specific form of a hook (its original bytes, the registers the code keeps things in) for the game
    build being patched: table {sha1[:12]: form}; the known build, and a build the table doesn't name, get default.
    A hook site's original bytes given as the form's own bytes pass site() as they are."""
    return default if ACTIVE.identity else table.get(ACTIVE.sha1[:12], default)
