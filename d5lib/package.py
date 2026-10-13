"""Shareable mod packages: one self-contained installer .exe for players (no Python, no kit).

    export(game_dir, kit_dir, out_exe, title, description, mods=None)

The kit installs the chosen mods into this game first (Installer), then describes, per changed file, how to turn a
player's VANILLA copy into the installed one:

* big archives (NISPACK 'append', sound 'psfs' / 'fafs'): the kit only rewrites the header region and appends data
  after the vanilla end, so the package holds   head   (the new first H bytes)   +   ops for the tail.  Tail ops
  copy bytes from the player's own vanilla file (modified game members such as the 178 MB resident sprite pack are
  stored as small deltas against their vanilla member), copy bytes already written (an outfit sprite's companion
  copy, the second portrait copy), or insert new bytes (the mods' own content).
* whole files (the exe, script.dat): ops building the new file from the vanilla one (the exe patch = a few hook
  bytes + new code sections).
* new files (the runtime DLLs and their ini): their bytes.

Every vanilla file is checked first (size + SHA-1 of the region the package relies on) so a different game build is
refused, and the installer keeps its own backups (D5Mods\\backup) for a byte-exact uninstall.

Payload (appended to the installer stub d5lib/bin/d5pack_installer.exe, see d5lib/native_tools/d5pack_installer.c):
    "D5PKG1\\0\\0", u32 manifest length, manifest, blob data
    trailer at the very end of the exe: "D5PKTAIL", u64 payload offset, u64 payload length
Manifest (little endian):
    u32 version (1), str title, str description, str pack id, u32 file count, then per file:
        str path (relative to the game folder), u8 kind (1 append, 2 replace, 3 new)
        u64 vanilla size, u64 check length, 20-byte SHA-1 of the vanilla file's first `check length` bytes (with the
        ignored ranges zeroed), u32 n, n x (u64 offset, u64 length) ignored ranges (directory entries the kit
        repaired in its own game copy)
        u64 head offset (in the blob area), u64 head length               (append)
        u64 output size, 20-byte SHA-1 of the output (head + tail for append, the whole file otherwise)
        u32 op count, ops: u8 type (0 insert blob, 1 copy from the vanilla file, 2 copy from the output so far),
                         u64 source offset, u64 length
    str = u32 byte length + UTF-8
"""
import hashlib
import json
import os
import struct
import time

from . import crypt

MAGIC = b"D5PKG1\0\0"
TRAILER = b"D5PKTAIL"
KIND_APPEND, KIND_REPLACE, KIND_NEW = 1, 2, 3
OP_BLOB, OP_VANILLA, OP_OUT = 0, 1, 2
MIN_COPY = 48            # shorter matches are cheaper as inserted bytes
PROBE = 32               # resync probe length
STUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "d5pack_installer.exe")


# ------------------------------------------------------------------------------------------ delta
def _common(a, i, b, j, limit):
    """length of the common run a[i:] / b[j:] (memoryviews), at most limit"""
    n = 0
    step = 1 << 16
    while n < limit:
        k = min(step, limit - n)
        if a[i + n:i + n + k] == b[j + n:j + n + k]:
            n += k
            continue
        lo, hi = 0, k                       # a[i+n : i+n+lo] equal, +hi not
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if a[i + n:i + n + mid] == b[j + n:j + n + mid]:
                lo = mid
            else:
                hi = mid
        return n + lo
    return n


def _common_back(a, i, b, j, limit):
    """length of the common run ending just before a[i] / b[j], at most limit"""
    lo, hi = 0, limit + 1                   # a[i-lo:i] == b[j-lo:j]; hi not
    if limit and a[i - limit:i] == b[j - limit:j]:
        return limit
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if a[i - mid:i] == b[j - mid:j]:
            lo = mid
        else:
            hi = mid
    return lo


def delta(new, old, old_base, kind=OP_VANILLA, window=1 << 20, span=1 << 16):
    """ops turning `old` (found at offset old_base of the source) into `new`: [(OP_BLOB, bytes) | (kind, offset, n)].
    Greedy: copy the common run; on a mismatch, find where `new` resumes in `old` -- probes of PROBE bytes over the
    next `span` bytes, searched within `window` of the current old position, then one probe against the whole of
    `old` -- and insert the bytes in between.  A run of new bytes with no resync doubles the span (long inserted
    regions, e.g. new face textures, are skipped quickly).  C-speed slicing and bytes.find throughout."""
    nv, ov = memoryview(new), memoryview(old)
    ob = bytes(old)
    out = []
    i = j = 0
    lit = 0
    N, M = len(new), len(old)
    sp = span
    while i < N:
        L = _common(nv, i, ov, j, min(N - i, M - j)) if j < M else 0
        if L >= MIN_COPY:
            if lit < i:
                out.append((OP_BLOB, bytes(nv[lit:i])))
            out.append((kind, old_base + j, L))
            i += L
            j += L
            lit = i
            sp = span
            continue
        p0 = p = i + max(1, L)
        if p0 > N - PROBE:
            break
        stop = min(N - PROBE, p0 + sp)
        found = None
        lo, hi = max(0, j - window), min(M, j + window + PROBE)
        stride = max(PROBE, sp // 256)          # sparse probes: a hit is extended backwards to the exact start
        while p <= stop:
            k = ob.find(bytes(nv[p:p + PROBE]), lo, hi)
            if k >= 0:
                found = (p, k)
                break
            p += stride
        if found is None:
            k = ob.find(bytes(nv[p0:p0 + PROBE]))
            if k >= 0:
                found = (p0, k)
        if found is None:
            i = stop + 1
            sp = min(sp * 4, 1 << 23)
            continue
        p, k = found
        back = _common_back(nv, p, ov, k, min(p - lit, k))
        i, j = p - back, k - back
    if lit < N:
        out.append((OP_BLOB, bytes(nv[lit:N])))
    return out


def _ops_size(ops):
    return sum(len(o[1]) if o[0] == OP_BLOB else 17 for o in ops)


# ------------------------------------------------------------------------------------------ NISPACK tables
ENTRY = 44


def _table(head_bytes):
    """[(name, offset, size, stamp)] of a NISPACK header (obfuscated or not)"""
    dec = crypt.decode if crypt.is_obfuscated_nispack(head_bytes[:16]) else (lambda b: b)
    count = struct.unpack_from("<I", dec(head_bytes[:16]), 12)[0]
    t = dec(bytes(head_bytes[16:16 + count * ENTRY]))
    out = []
    for i in range(count):
        o = i * ENTRY
        out.append((t[o:o + 32].split(b"\0")[0].decode("latin1"),) + struct.unpack_from("<III", t, o + 32))
    return out


def _read(path, off, n):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


# ------------------------------------------------------------------------------------------ export
class _Blobs:
    def __init__(self, path):
        self.f = open(path, "w+b")
        self.size = 0

    def add(self, data):
        off = self.size
        self.f.write(data)
        self.size += len(data)
        return off


def _sha1_file(path, n=None, chunk=1 << 24):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        left = os.path.getsize(path) if n is None else n
        while left > 0:
            b = f.read(min(chunk, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return h.digest()


def _append_entry(inst, archive, rec, blobs, log):
    """an append-style archive (NISPACK / psfs / fafs): head + tail ops"""
    path = inst.apath(archive)
    vsize = rec["vanilla_size"]
    hdr = open(inst._bfile(archive, ".hdr"), "rb").read()
    total = os.path.getsize(path)
    # the region the package relies on: everything before the first vanilla member (the true vanilla header; repairs
    # the kit made to this game's copy are undone for the check, see Installer.repairs)
    if rec["mode"] == "append":
        vt = _table(hdr)
        check_len = min(e[1] for e in vt) if vt else len(hdr)
    else:
        vt = []
        check_len = rec.get("hdr_len", len(hdr))
    check = bytearray(hdr[:check_len])
    ignore = []
    for name in (rec.get("repairs") or {}):          # directory entries the kit repaired in this game's copy: not
        for i, e in enumerate(vt):                    # compared (players have the original, this game the repair)
            if e[0] == name:
                ignore.append((16 + i * ENTRY, ENTRY))
    for o, n in ignore:
        check[o:o + n] = bytes(n)
    # head = every byte before the vanilla end that differs from vanilla: the (grown) directory region
    head_len = max(len(hdr), check_len)
    if rec["mode"] == "append":
        cur = _table(_read(path, 0, 16 + 0x200000))
        head_len = max(head_len, 16 + len(cur) * ENTRY)
    head = _read(path, 0, head_len)
    head_off = blobs.add(head)
    # tail: members appended after the vanilla end
    ops = []
    pos = vsize
    damaged = set((rec.get("repairs") or {}).keys())
    vby = {e[0].lower(): e for e in vt}
    written = {}                        # content hash -> output offset (identical members stored once)
    out_members = {}                    # name -> (output offset, size): bases for related members
    by_size = {}                        # size -> last member of that size (the two copies of an outfit portrait)
    if rec["mode"] == "append":
        cur = _table(head)
        tail_members = sorted((e for e in cur if e[1] >= vsize), key=lambda e: e[1])
    else:
        tail_members = []
    stats = dict(delta=0, dup=0, related=0, new=0)

    def put_bytes(off, data_ops):
        nonlocal pos
        for o in data_ops:
            if o[0] == OP_BLOB:
                ops.append((OP_BLOB, blobs.add(o[1]), len(o[1])))
                pos += len(o[1])
            else:
                ops.append(o)
                pos += o[2]

    for name, off, size, stamp in tail_members:
        if off > pos:                                              # alignment padding
            put_bytes(pos, [(OP_BLOB, _read(path, pos, off - pos))])
        data = _read(path, off, size)
        h = hashlib.sha1(data).digest()
        v = vby.get(name.lower())
        if h in written:
            put_bytes(off, [(OP_OUT, written[h], size)])
            stats["dup"] += 1
        elif v and name not in damaged and v[1] + v[2] <= vsize and v[1] >= check_len:
            d = delta(data, _read(path, v[1], v[2]), v[1])
            put_bytes(off, d)
            stats["delta"] += 1
        else:
            d = None
            for base in (_related(name, out_members), by_size.get(size)):
                if not base:
                    continue
                bo, bs = base
                d = delta(data, _read(path, bo, bs), bo, kind=OP_OUT)
                if _ops_size(d) <= 0.6 * size:
                    break
                d = None
            if d:
                put_bytes(off, d)
                stats["related"] += 1
            else:
                put_bytes(off, [(OP_BLOB, data)])
                stats["new"] += 1
        written.setdefault(h, off)
        out_members[name.lower()] = (off, size)
        by_size[size] = (off, size)
    if total > pos:                                                # anything after the last member
        if rec["mode"] == "append":
            put_bytes(pos, [(OP_BLOB, _read(path, pos, total - pos))])
        else:
            # sound archives: the appended packs / table as a whole, delta against nothing
            put_bytes(pos, [(OP_BLOB, _read(path, pos, total - pos))])
    out_sha = hashlib.sha1()
    out_sha.update(head)
    with open(path, "rb") as f:
        f.seek(vsize)
        while True:
            b = f.read(1 << 24)
            if not b:
                break
            out_sha.update(b)
    if log:
        log(f"  {archive}: head {head_len} bytes, tail {total - vsize} bytes -> {len(ops)} ops "
            f"({stats['delta']} game members as deltas, {stats['dup']} duplicates, {stats['related']} related, "
            f"{stats['new']} new)")
    return dict(kind=KIND_APPEND, vanilla_size=vsize, check_len=check_len, ignore=ignore,
                check_sha=hashlib.sha1(bytes(check)).digest(), head=(head_off, head_len),
                out_size=total, out_sha=out_sha.digest(), ops=ops)


def _related(name, members):
    """an earlier member this one is probably a near copy of: anmN+1 of anmN (the outfit sprite's companion)"""
    n = name.lower()
    if n.startswith("anm") and n[3:8].isdigit():
        k = int(n[3:8])
        return members.get(f"anm{k - 1:05d}{n[8:]}")
    return None


def _replace_entry(inst, archive, rec, blobs, log):
    path = inst.apath(archive)
    vpath = inst._bfile(archive, ".full")
    old = open(vpath, "rb").read()
    new = open(path, "rb").read()
    d = delta(new, old, 0)
    ops = [(OP_BLOB, blobs.add(o[1]), len(o[1])) if o[0] == OP_BLOB else o for o in d]
    if log:
        log(f"  {archive}: {len(new)} bytes -> {len(ops)} ops, {sum(o[2] for o in ops if o[0] == OP_BLOB)} new bytes")
    return dict(kind=KIND_REPLACE, vanilla_size=len(old), check_len=len(old), check_sha=hashlib.sha1(old).digest(),
                head=(0, 0), out_size=len(new), out_sha=hashlib.sha1(new).digest(), ops=ops)


def _new_entry(inst, archive, blobs, log):
    data = open(inst.apath(archive), "rb").read()
    off = blobs.add(data)
    return dict(kind=KIND_NEW, vanilla_size=0, check_len=0, check_sha=bytes(20), head=(0, 0), out_size=len(data),
                out_sha=hashlib.sha1(data).digest(), ops=[(OP_BLOB, off, len(data))])


def _rel_path(inst, archive):
    p = os.path.relpath(inst.apath(archive), inst.game_dir)
    return p.replace(os.sep, "\\")


def _s(text):
    b = text.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def build_payload(inst, title, description, pack_id, out_payload, log=print):
    """describe every archive the kit installed (Installer index) -> payload file"""
    tmp = out_payload + ".blobs"
    blobs = _Blobs(tmp)
    entries = []
    for archive, rec in sorted(inst.index.items()):
        if not rec.get("modified"):
            continue
        if rec["mode"] in ("append", "psfs", "fafs"):
            e = _append_entry(inst, archive, rec, blobs, log)
        elif rec["mode"] == "new":
            e = _new_entry(inst, archive, blobs, log)
        else:
            if archive.startswith("GAME/"):
                e = _new_entry(inst, archive, blobs, log)      # the kit's own runtime files: replaced as a whole
                e["kind"] = KIND_NEW
            else:
                e = _replace_entry(inst, archive, rec, blobs, log)
        e["path"] = _rel_path(inst, archive)
        entries.append(e)
    man = bytearray(struct.pack("<I", 1) + _s(title) + _s(description) + _s(pack_id) + struct.pack("<I", len(entries)))
    for e in entries:
        man += _s(e["path"]) + struct.pack("<BQQ", e["kind"], e["vanilla_size"], e["check_len"]) + e["check_sha"]
        ign = e.get("ignore") or []
        man += struct.pack("<I", len(ign)) + b"".join(struct.pack("<QQ", o, n) for o, n in ign)
        man += struct.pack("<QQQ", e["head"][0], e["head"][1], e["out_size"]) + e["out_sha"]
        man += struct.pack("<I", len(e["ops"]))
        man += b"".join(struct.pack("<BQQ", *o) for o in e["ops"])
    blobs.f.flush()
    with open(out_payload, "wb") as out:
        out.write(MAGIC + struct.pack("<I", len(man)) + man)
        blobs.f.seek(0)
        while True:
            b = blobs.f.read(1 << 24)
            if not b:
                break
            out.write(b)
    blobs.f.close()
    os.remove(tmp)
    if log:
        log(f"payload: {os.path.getsize(out_payload) / 1e6:.1f} MB ({len(entries)} files)")
    return entries


def write_installer(payload_path, out_exe, stub=STUB):
    """installer stub + payload + trailer -> one self-contained .exe"""
    with open(out_exe, "wb") as out:
        with open(stub, "rb") as f:
            out.write(f.read())
        off = out.tell()
        with open(payload_path, "rb") as f:
            while True:
                b = f.read(1 << 24)
                if not b:
                    break
                out.write(b)
        n = out.tell() - off
        out.write(TRAILER + struct.pack("<QQ", off, n))
    return out_exe


# ------------------------------------------------------------------------------------------ reading / verifying
def read_payload(path):
    """-> (title, description, pack id, [file entries], blob base offset) of a payload file or installer exe"""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(size - 24)
        t = f.read(24)
        base = 0
        if t[:8] == TRAILER:
            base = struct.unpack_from("<Q", t, 8)[0]
        f.seek(base)
        if f.read(8) != MAGIC:
            raise ValueError("not a D5 mod package")
        n = struct.unpack("<I", f.read(4))[0]
        m = f.read(n)
    blob_base = base + 12 + n
    pos = 0

    def u(fmt):
        nonlocal pos
        v = struct.unpack_from(fmt, m, pos)
        pos += struct.calcsize(fmt)
        return v

    def s():
        nonlocal pos
        n_ = u("<I")[0]
        v = m[pos:pos + n_].decode("utf-8")
        pos += n_
        return v
    u("<I")
    title, desc, pid = s(), s(), s()
    files = []
    for _ in range(u("<I")[0]):
        e = dict(path=s())
        e["kind"], e["vanilla_size"], e["check_len"] = u("<BQQ")
        e["check_sha"] = m[pos:pos + 20]
        pos += 20
        e["ignore"] = [u("<QQ") for _ in range(u("<I")[0])]
        ho, hl, e["out_size"] = u("<QQQ")
        e["head"] = (ho, hl)
        e["out_sha"] = m[pos:pos + 20]
        pos += 20
        e["ops"] = [u("<BQQ") for _ in range(u("<I")[0])]
        files.append(e)
    return title, desc, pid, files, blob_base


def vanilla_sources(inst):
    """{package path: the kit's vanilla backup copy} of the whole-file entries (exe, script.dat)"""
    return {_rel_path(inst, a): inst._bfile(a, ".full") for a, r in inst.index.items()
            if r.get("modified") and r["mode"] == "full" and not a.startswith("GAME/")}


def verify_against(path, game_dir, log=print, sources=None):
    """rebuild every output of the package from the files in game_dir (this game, mods installed: the vanilla
    regions the ops read are unchanged there; whole-file entries read the vanilla copy from `sources`,
    vanilla_sources) and compare with the expected hashes -> number of mismatches"""
    sources = sources or {}
    title, desc, pid, files, bb = read_payload(path)
    bad = 0
    with open(path, "rb") as pk:
        for e in files:
            gp = os.path.join(game_dir, e["path"])
            h = hashlib.sha1()
            out_pos = 0
            if e["kind"] == KIND_APPEND:
                pk.seek(bb + e["head"][0])
                head = pk.read(e["head"][1])
                h.update(head)
                out_pos = e["vanilla_size"]
            outbuf = bytearray()
            src_path = sources.get(e["path"], gp) if e["kind"] == KIND_REPLACE else gp
            with open(src_path, "rb") as src:
                for t, a, n in e["ops"]:
                    if t == OP_BLOB:
                        pk.seek(bb + a)
                        data = pk.read(n)
                    elif t == OP_OUT and e["kind"] != KIND_APPEND:
                        data = bytes(outbuf[a:a + n])
                    else:
                        src.seek(a)
                        data = src.read(n)
                    if e["kind"] != KIND_APPEND:
                        outbuf += data
                        if t == OP_VANILLA and e["kind"] == KIND_APPEND and a < max(e["check_len"], e["head"][1]):
                            raise ValueError(f"{e['path']}: an op reads the header region")
                    h.update(data)
                    out_pos += n
            ok = h.digest() == e["out_sha"] and (e["kind"] != KIND_APPEND or out_pos == e["out_size"])
            if e["kind"] == KIND_REPLACE:
                ok = ok  # replace ops read the vanilla file: checked by the installer, here only the hash chain
            bad += not ok
            if log:
                log(f"  {e['path']}: {'ok' if ok else 'MISMATCH'} ({len(e['ops'])} ops)")
    return bad
