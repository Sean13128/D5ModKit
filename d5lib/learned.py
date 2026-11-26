"""Learned-evility capacity: a per-unit learned-id store for positions beyond the native bitmap (section .d5lc).

The game records a unit's learned evilities as one bit per **Skill.dat row position**: 125 bytes at unit
record +0x2E70 (1,000 bits), with the position found by a binary search over the id-sorted key array
(0x140A04E48 / max index 0x140A04E38) and the bit built as `1 << (index & 7)`.  Both ends of that mapping
refuse an index >= 1000: the getter 0x14015E630 answers "not learned" and the setter 0x14015E6D0 returns -1.

This module adds the Kit's answer, without touching the bitmap or any existing bit:

* Every static call site of those two functions (20 + 123 in the pinned build, see GET_SITES / SET_SITES)
  is redirected to a wrapper in a new code section.  The wrapper calls the original first, so positions
  0..999 behave exactly as before; only an id the game refused is considered by the extension.
* The extension's own learning lives in a per-unit set (unit serial + evility id) in the section's data.
* The section carries the ordered ids the build was made against (`base_ids`, up to 1000 of them, the ids
  that own the bitmap's bits).  On first use the wrapper compares them with the live key array and answers
  nothing at all if they differ, so a Skill.dat that shifted a row's position can never silently
  reinterpret an old save's learning.  The bitmap is never written, so old saves keep their evilities.

Adding evility rows is therefore append-only-safe: a row whose id sorts at position 1000 or later costs no
existing bit, and it can be learned because the setter wrapper records it in the store.

Install: the finalizer reads the **finished** Skill.dat member (every mod's rows in, after `dbpatch` put the
table in id order) and rebuilds the section from it, so the guard describes the table actually installed.
"""
import json
import os
import struct

from .exepatch import add_code_section, code_base
from .gamefs import EXE_FILE
from .modsys import register_finalizer

SECTION = b".d5lc"
HERE = os.path.dirname(os.path.abspath(__file__))
ASM_FILE = os.path.join(HERE, "native", "d5learn.inc.asm")

GETTER = 0x14015E630        # FUN_14015e630: id -> learned?  (binary search + bit test)
SETTER = 0x14015E6D0        # unitstats_set_clear_bit_idx_skill
MAKE_HEADER = 0x1407436D0   # data_save_io_make_header: formats the slot path, fopen + fwrite x2 + fclose
DECODE_SLOT = 0x140743130   # savefile_decode_slot (rcx = destination, edx = slot, 0 = AutoSave)
SAVE_DIR = 0x147B58F20      # the game's save-folder string ("%s/Save_%03d.sav" is built from it)
KEY_ARRAY = 0x140A04E48     # the live sorted u32 id array (a pointer)
KEY_MAXI = 0x140A04E38      # its u16 max index
BIT_CAPACITY = 1000         # positions the 125-byte bitmap can hold (record +0x2E70..+0x2EEC)
# The store is sized for the whole content plan, not for today's table: 128 roster slots x up to 768
# extension evilities each = 98,304 live pairs (three quarters of the table), i.e. more headroom than the
# plan can produce (its extension rows are counted in the hundreds, not the thousands) while a single probe
# still walks at most 64 slots at a 75% load factor.  See EVCAP3-REPORT.md.
STORE_CAPACITY = 131072     # slots in the extension's own table (2 MiB of section data)
STORE_MAX_USED = 98304      # refuse to fill past three quarters (bounded probes stay bounded)
PROBE = 128                 # slots a single probe walks (matches d5learn.inc.asm)
UID_OFFSET = 0x3060         # unit record: the u64 serial the store keys a unit by
SLOT_SHIFT = 64 - (STORE_CAPACITY.bit_length() - 1)   # the store's hash keeps the high bits of a 64-bit mix
# The two `call`s of the game's slot writer (EVCAP4).  0x140754C5C is inside FUN_140754C30, the manual save
# of the slot at [ctx+0x8a7618]; 0x140744FE2 is inside FUN_140744F20, the autosave (slot 0).  Both hand the
# writer the slot in r8d, i.e. the number it puts in the file name, and it answers 0 only when the header and
# the encoded block were both written and the file closed.  The relay publishes that slot on success.
SAVE_SITES = (0x140744FE2, 0x140754C5C)   # autosave (FUN_140744F20), manual save (FUN_140754C30)
LOAD_SITES = (0x14074D846,)  # call -> DECODE_SLOT inside FUN_14074d830 (the game's own load of a slot)
# The site EVCAP3 bound the companion to (0x14074749E, in FUN_140747420) calls WRITE_SLOT, which is really
# DeleteFileW's wrapper and answers 0 on a *successful delete* (INTEG12-REPORT.md finding 1).  It is no
# longer patched; both stay named here so the audit and the tests can prove nothing redirects it any more.
DELETE_SITE = 0x14074749E
WRITE_SLOT = 0x1401194EC    # what DELETE_SITE calls: DeleteFileW, not a writer

# Every static `call` of the two functions in the pinned build (49a7530b…), found by scanning .text for
# E8 with that rel32 target.  `tests/test_evcap.py` re-runs the scan and fails if these lists drift.
GET_SITES = (
    0x14018A537, 0x1401AFC6D, 0x1401D230C, 0x1402890E1, 0x140294BED,
    0x1402C0359, 0x1402C0451, 0x1407CD986, 0x1407CDB08, 0x1407CDC2C,
    0x1407D0513, 0x1407D1525, 0x1407D43D1, 0x14080A1DE, 0x1408321DC,
    0x14083221F, 0x140833265, 0x1408422DE, 0x14084F1EC, 0x14084F22E,
)
SET_SITES = (
    0x14018A54C, 0x1401AFC85, 0x1401D2321, 0x1401DADAD, 0x1401DADD5,
    0x1401DADE6, 0x1401DAE09, 0x140218D51, 0x1402194FE, 0x1402890F3,
    0x1403BF08F, 0x1403BF0B5, 0x1403BF0DB, 0x1403BF101, 0x1403BF127,
    0x1403BF14D, 0x1403BF173, 0x1403BF199, 0x1403BF1BF, 0x1403BF1E5,
    0x1403D1A8A, 0x1403D1AAF, 0x1403D1AD4, 0x1403D1AF9, 0x1403D1BD6,
    0x1403D1C86, 0x1404D3B11, 0x1404D620B, 0x1404D6257, 0x1404D62B2,
    0x1404D62FE, 0x1404D634A, 0x1404D639D, 0x1404D63F8, 0x1404D6444,
    0x1404D6490, 0x1404D64EB, 0x1404D6537, 0x1404D6583, 0x1404D65D6,
    0x1404D6631, 0x1404D667D, 0x1404D66D8, 0x1404D6724, 0x1404D677A,
    0x1404D6796, 0x1404D67F1, 0x1404D683D, 0x1404D6898, 0x1404D68E4,
    0x1404D693F, 0x1404D6987, 0x1404D69DA, 0x1404D6A2D, 0x1404D6A80,
    0x1404D6AD3, 0x1404D6AF8, 0x1404D6B53, 0x1404D6B78, 0x1404D6BC4,
    0x1404D6BE9, 0x1404D6C35, 0x1404D6C5A, 0x1404D6CB1, 0x1404D6CD6,
    0x1404D6CFB, 0x1404D6D5B, 0x1404D6D80, 0x1404D6DA5, 0x1404D6DCA,
    0x1404D6DEF, 0x1404D6E14, 0x1404D6E39, 0x1404D6E5E, 0x1404D6E83,
    0x1404D6EA8, 0x1404D6ECD, 0x1404D6EF2, 0x1404D6F0F, 0x1404D6F34,
    0x1404D6F59, 0x1404D6FAC, 0x1404D703D, 0x1404D7093, 0x1404D70B8,
    0x1404D70DD, 0x1404D711F, 0x1404D7144, 0x1404D7169, 0x1404D71AB,
    0x1404D71D0, 0x1404D71F5, 0x1404D7237, 0x1404D725C, 0x1404D7281,
    0x1404D72C3, 0x1404D72E8, 0x1404D730D, 0x1404D734C, 0x1404D7371,
    0x1404D7396, 0x1404D7427, 0x1404D744C, 0x1404D7471, 0x1405530DC,
    0x140553101, 0x140553115, 0x14055313A, 0x1406A0CCC, 0x1406A0E1C,
    0x1407C0BD9, 0x1407C0BF6, 0x1407C0C69, 0x1407C0C86, 0x1407C0EA9,
    0x1407C0EB6, 0x1407C156B, 0x1407C1588, 0x1407C15F2, 0x1407CFAC9,
    0x1407D3999, 0x140809F29, 0x14085A2DB,
)

CLAIM = b"D5LC"
MAGIC = 0x4C43_5645_3531_3044          # "D510E VCL" laid out for a data scan: D5LC section marker
SECTION_VERSION = 3                    # 1 = EVCAP2 (store only), 2 = EVCAP3 (path-publishing relay),
                                       # 3 = EVCAP4 (save relay publishes the slot the writer was given)


# ------------------------------------------------------------------------------------- the manifest
def slot(serial, ident):
    """the store slot a (serial, evility id) pair lives in (the one hash the asm and the runtime use)"""
    h = ((int(serial) * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF) ^ \
        ((int(ident) * 0xC2B2AE3D27D4EB4F) & 0xFFFFFFFFFFFFFFFF)
    return (h >> SLOT_SHIFT) & (STORE_CAPACITY - 1)


def generation(ids):
    """a stable digest of an ordered Skill id list (the table generation a save was written against)"""
    import zlib
    return zlib.crc32(",".join(str(i) for i in ids).encode("ascii")) & 0xFFFFFFFF


def manifest(table_ids):
    """the guard for a finished Skill table: which ids own the bitmap bits, which are ours.

    `table_ids` is the *ordered* id list of the installed Skill.dat (the order the game binary-searches).
    The first `BIT_CAPACITY` ids own the bitmap's positions 0..999; anything after them can only be
    recorded by the extension.  An unsorted list is refused: the game's search would not find those ids at
    all, so the manifest would describe a table the game cannot use.
    """
    ids = [int(i) for i in table_ids]
    if ids != sorted(ids):
        raise ValueError("Skill.dat ids are not in ascending order: the game binary-searches this table, "
                         "so a manifest cannot describe it")
    if len(set(ids)) != len(ids):
        raise ValueError("Skill.dat has duplicate ids")
    base = ids[:BIT_CAPACITY]
    return {"base_ids": base, "base_count": len(base), "ext_ids": ids[BIT_CAPACITY:],
            "generation": generation(ids), "row_count": len(ids)}


# ------------------------------------------------------------------------------------- the section
HEADER = CLAIM + bytes([SECTION_VERSION])   # 16-byte header; the first routine starts right after it


def section_source(man):
    """the section source: 16-byte header, the code, then the guard, the store and the save/load state

    The data block is addressed by `data_symbols` here and, at run time, by d5lib/native/d5learn.inc.c with
    the same alignment arithmetic from the claim address.  Keep the two in step: the field order below is
    the layout both sides assume.
    """
    with open(ASM_FILE, "r", encoding="utf-8") as f:
        body = f.read()
    for token, value in (("%MASK%", f"{STORE_CAPACITY - 1:#x}"), ("%SHIFT%", str(SLOT_SHIFT)),
                         ("%PROBE%", str(PROBE)),
                         ("%MAXUSED%", str(STORE_MAX_USED)), ("%CLEARQ%", str(STORE_CAPACITY * 2)),
                         ("%CAP%", str(STORE_CAPACITY))):
        if token not in body:
            raise ValueError(f"learned extension: the asm lost its {token} placeholder")
        body = body.replace(token, value)
    nl = "\n"
    header = "    .byte " + ", ".join(str(b) for b in HEADER + b"\0" * (16 - len(HEADER)))
    data = ["    .align 16",
            "lc_magic:",
            f"    .quad {MAGIC:#x}",
            "lc_version:",
            f"    .long {SECTION_VERSION}",
            "lc_state:",                       # 0 not yet verified, 1 verified, 2 refused
            "    .long 0",
            "lc_base_count:",
            f"    .long {man['base_count']}",
            "lc_used:",
            "    .long 0",
            "lc_cap:",
            f"    .long {STORE_CAPACITY}",
            "lc_gen:",
            f"    .long {man['generation']}",
            "lc_uid_off:",
            f"    .long {UID_OFFSET:#x}",
            "    .long 0",
            "lc_pkey:",
            f"    .quad {KEY_ARRAY:#x}",
            "lc_pmax:",
            f"    .quad {KEY_MAXI:#x}",
            "lc_savedir:",
            f"    .quad {SAVE_DIR:#x}",
            "lc_fn_put:",
            "    .quad lc_put",                 # the runtime's store entry points (d5learn.inc.c)
            "lc_fn_clear:",
            "    .quad lc_clear",
            "    .align 16",
            "lc_prefix:"]
    data += ["    .long " + ", ".join(str(i) for i in man["base_ids"][i:i + 8]) for i in range(0, len(man["base_ids"]), 8)]
    if not man["base_ids"]:
        data.append("    .long 0")
    data += ["    .align 16", "lc_store:",
             f"    .space {STORE_CAPACITY * 16}, 0",
             "    .align 16",
             "lc_sv_slot:",                    # the slot the game's writer was given (0 = AutoSave.sav)
             "    .long 0",
             "lc_sv_seq:",                     # +1 on every successful write; the runtime acts on the change
             "    .long 0",
             "lc_ev_load:",                    # 1 = the game started a slot load
             "    .long 0",
             "lc_ev_slot:",                    # that slot (0 = AutoSave.sav)
             "    .long 0",
             "lc_ev_ok:",                      # 1 = the game's decode succeeded
             "    .long 0",
             "    .align 16"]
    return header + nl + "lc_code:" + nl + body + nl + "lc_data:" + nl + nl.join(data) + nl


def _assemble(src, base):
    """assemble at `base`; -> (code, {routine: address})

    Each routine starts with `mov r11d, tag` (0xE80001..0xE80006) exactly like the evility runtime's
    wrappers: keystone hands back an encoding, not a symbol table, so the tag bytes are what locate a
    routine's entry.  r11 is scratch in this code (every routine overwrites it anyway).
    """
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    ks = Ks(KS_ARCH_X86, KS_MODE_64)
    enc, _ = ks.asm(src, base)
    code = bytes(enc)
    labels = {}
    for name, tag in ROUTINE_TAGS.items():
        at = code.find(b"\x41\xbb" + struct.pack("<I", tag))
        if at < 0:
            raise ValueError(f"learned extension: routine {name} (tag {tag:#x}) not found in the section")
        labels[name] = base + at
    return code, labels


ROUTINE_TAGS = {"lc_get": 0xE80001, "lc_set": 0xE80002, "lc_verify": 0xE80003,
                "lc_position": 0xE80004, "lc_lookup": 0xE80005, "lc_store_set": 0xE80006,
                "lc_save_relay": 0xE80007, "lc_load_relay": 0xE80008, "lc_clear": 0xE80009,
                "lc_put": 0xE8000A}


def build_patch(exe: bytes, man) -> bytes:
    """the exe with section .d5lc and every getter/setter call site redirected into it"""
    src = section_source(man)
    base = code_base(exe, SECTION)
    code, labels = _assemble(src, base)
    patches = []
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    plan = ((GET_SITES, GETTER, labels["lc_get"]),
            (SET_SITES, SETTER, labels["lc_set"]),
            (SAVE_SITES, MAKE_HEADER, labels["lc_save_relay"]),
            (LOAD_SITES, DECODE_SLOT, labels["lc_load_relay"]))
    for sites, target, wrapper in plan:
        for va in sites:
            off = pe.get_offset_from_rva(va - IMAGE_BASE)
            orig = exe[off:off + 5]
            _check_site(va, orig, target)
            patches.append((va, orig, wrapper, 0xE8))
    return add_code_section(exe, SECTION, code, patches, writable=True)


def _check_site(va, orig, target):
    if len(orig) != 5 or orig[0] != 0xE8:
        raise ValueError(f"learned extension: call site {va:#x} is not a call (unexpected exe build)")
    dest = va + 5 + struct.unpack("<i", orig[1:])[0]
    if dest != target:
        raise ValueError(f"learned extension: call site {va:#x} calls {dest:#x}, expected {target:#x}")


def scan_sites(exe: bytes):
    """re-derive the two site lists from an exe (the test that keeps GET_SITES/SET_SITES honest)"""
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    out = {GETTER: [], SETTER: []}
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:
            continue
        va = IMAGE_BASE + s.VirtualAddress
        data = exe[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        i = data.find(b"\xe8")
        while i >= 0:
            if i + 5 <= len(data):
                dest = (va + i + 5 + struct.unpack_from("<i", data, i + 1)[0]) & 0xFFFFFFFFFFFFFFFF
                if dest in out:
                    out[dest].append(va + i)
            i = data.find(b"\xe8", i + 1)
    return {k: tuple(sorted(v)) for k, v in out.items()}


def scan_relay_sites(exe: bytes):
    """re-derive the save/load relay sites from an exe (the test that keeps SAVE_SITES/LOAD_SITES honest)

    Saving is bound to the game's own slot writer (MAKE_HEADER), loading to its own decode; the delete call
    EVCAP3 used is reported under DELETE_SITE so a test can prove nothing redirects it.
    """
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    out = {MAKE_HEADER: [], DECODE_SLOT: [], WRITE_SLOT: []}
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:
            continue
        va = IMAGE_BASE + s.VirtualAddress
        data = exe[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        i = data.find(b"\xe8")
        while i >= 0:
            if i + 5 <= len(data):
                dest = (va + i + 5 + struct.unpack_from("<i", data, i + 1)[0]) & 0xFFFFFFFFFFFFFFFF
                if dest in out:
                    out[dest].append(va + i)
            i = data.find(b"\xe8", i + 1)
    return {k: tuple(sorted(v)) for k, v in out.items()}


def section_info(exe: bytes):
    """where the installed section is: {base, size, data, section} (found by its claim bytes)"""
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    for s in pe.sections:
        data = pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)
        at = data.find(CLAIM)
        if at >= 0:
            base = IMAGE_BASE + s.VirtualAddress + at
            return {"base": base, "code": base + 16, "size": s.Misc_VirtualSize - at,
                    "data": data[at:], "section": s.Name.rstrip(b"\0").decode("ascii", "replace")}
    return None


def data_symbols(info):
    """the data area's field addresses out of an installed section ({magic, version, state, ...}).

    The proof and the verifier need the fields by address; the layout is the one `section_source` emits:
    a u64 magic, seven u32 fields, then the guard's two pointers, the id prefix and the store.
    """
    blob = info["data"]
    at = blob.find(struct.pack("<Q", MAGIC))
    if at < 0:
        raise ValueError("learned extension: the section has no data magic")
    base = info["base"] + at
    out = {"magic": base, "version": base + 8, "state": base + 12, "base_count": base + 16,
           "used": base + 20, "cap": base + 24, "generation": base + 28, "uid_offset": base + 32,
           "pkey": base + 40, "pmax": base + 48, "savedir": base + 56,
           "fn_put": base + 64, "fn_clear": base + 72}
    align16 = lambda x: (x + 15) // 16 * 16
    prefix = align16(base + 80)
    out["prefix"] = prefix
    base_count = struct.unpack_from("<I", blob, at + 16)[0]
    store = align16(prefix + 4 * base_count)
    out["store"], out["store_size"] = store, STORE_CAPACITY * 16
    ev = align16(store + STORE_CAPACITY * 16)
    out["sv_slot"], out["sv_seq"] = ev, ev + 4
    out["ev_load"], out["ev_slot"], out["ev_ok"] = ev + 8, ev + 12, ev + 16
    out["end"] = align16(ev + 20)
    return out


def manifest_from_member(member: bytes):
    """a manifest for a finished Skill.dat member (the bytes the installer is about to write)"""
    from . import database, ordercheck
    table = database.load_table("Skill.dat", member)
    ids = ordercheck._ids(table)
    if ids is None:
        raise ValueError("Skill.dat has no integer id key: cannot build a learned-evility manifest")
    return manifest(ids)


# ------------------------------------------------------------------- learned-set helpers + save sidecar
def learned_from_bitmap(bitmap: bytes, table_ids):
    """the set of evility ids a unit's 125 bitmap bytes mean, for a given ordered Skill table"""
    ids = set()
    for bit in range(min(BIT_CAPACITY, len(bitmap) * 8)):
        if bitmap[bit >> 3] & (1 << (bit & 7)):
            if bit < len(table_ids):
                ids.add(int(table_ids[bit]))
            else:
                raise ValueError(f"bit {bit} is set but the table has only {len(table_ids)} rows")
    return ids


SIDECAR_SUFFIX = ".d5learn.json"
SIDECAR_PREV = ".prev"
SIDECAR_REJECTED = ".rejected"
SIDECAR_SCHEMA = 2          # 1 = EVCAP2 (learning only); 2 adds the quarantine list and is what the game writes
SIDECAR_SCHEMAS_READ = (1, 2)


def sidecar_doc(save_path, table_ids, extra_learned=None, *, unit_names=None, quarantine=None):
    """the versioned companion for one save slot.

    `extra_learned` is {serial: [evility ids]} -- the learning that only the extension's store can hold
    (ids at table positions >= 1000).  `quarantine` keeps ids the table did not have, so a temporarily
    missing package never destroys learning.  The document binds itself to the exact native save bytes, so
    a companion can never be paired with a different save by accident.
    """
    import hashlib
    raw = open(save_path, "rb").read()
    units = {}
    for serial, ids in sorted((extra_learned or {}).items()):
        units[f"{int(serial):016x}"] = dict(learned=[int(i) for i in sorted(set(ids))],
                                            name=(unit_names or {}).get(int(serial)))
    return {
        "kind": "d5modkit.learned",
        "schema": SIDECAR_SCHEMA,
        "generation": generation(table_ids),
        "rows": len(table_ids),
        "bitmap_bits": BIT_CAPACITY,
        "save": {"name": os.path.basename(save_path), "size": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest()},
        "units": units,
        "quarantine": [dict(serial=int(q["serial"]), id=int(q["id"])) for q in (quarantine or [])],
    }


def sidecar_render(doc):
    """the exact text a companion file holds (the game writes the same document, one line)"""
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def sidecar_write(path, doc):
    """write a companion in place (temp + rename).  The game's runtime uses `sidecar_publish`."""
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(sidecar_render(doc))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def sidecar_publish(path, doc):
    """the game's transaction: stage, keep the previous generation as `.prev`, then rename into place.

    Two files can never be renamed atomically together, so the order is chosen so that no state can pair a
    companion with the wrong save: the staged file is complete before anything is moved, the previous
    companion is preserved, and the final name only ever holds a document that was fully written.  A crash
    between the two renames leaves `.prev` (whose save hash no longer matches) -- recoverable by hand,
    never silently paired.  -> (path, prev_path)
    """
    tmp = path + ".new"
    prev = path + SIDECAR_PREV
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(sidecar_render(doc))
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(path, prev)
    os.replace(tmp, path)
    return path, prev


def sidecar_read(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sidecar_validate(doc, save_path, table_ids):
    """(ok, problems, quarantine).  Damaged or mismatched companions are refused, never read as empty;
    ids the current table does not have are quarantined (kept, reported), never discarded."""
    import hashlib
    problems, quarantine = [], []
    if doc.get("kind") != "d5modkit.learned" or doc.get("schema") not in SIDECAR_SCHEMAS_READ:
        return False, [f"unknown companion format {doc.get('kind')!r} schema {doc.get('schema')!r}"], []
    if doc.get("generation") != generation(table_ids):
        problems.append("the companion was written for a different Skill table generation")
    if doc.get("bitmap_bits") != BIT_CAPACITY:
        problems.append(f"companion bitmap capacity {doc.get('bitmap_bits')} != {BIT_CAPACITY}")
    raw = open(save_path, "rb").read()
    want = doc.get("save") or {}
    if want.get("size") != len(raw) or want.get("sha256") != hashlib.sha256(raw).hexdigest():
        problems.append("the companion does not match these save bytes")
    known = set(int(i) for i in table_ids)
    clean = {}
    for key, unit in (doc.get("units") or {}).items():
        try:
            serial = int(key, 16)
        except ValueError:
            problems.append(f"unit key {key!r} is not a serial")
            continue
        ids = [int(i) for i in (unit.get("learned") or [])]
        good = [i for i in ids if i in known]
        quarantine += [dict(serial=serial, id=i) for i in ids if i not in known]
        clean[serial] = good
    quarantine += [dict(serial=int(q["serial"]), id=int(q["id"])) for q in (doc.get("quarantine") or [])]
    return not problems, problems, quarantine


def sidecar_plan(doc, table_ids):
    """what a valid companion means for the store: ({serial: [ids at positions >= 1000]}, native-owned, unknown)

    Mirrors d5learn.inc.c's learn_apply: ids the bitmap owns are dropped (the game already has them), ids
    the table lacks are quarantined, and only positions >= 1000 go into the store.
    """
    known = {int(i): pos for pos, i in enumerate(table_ids)}
    pairs, native, unknown = {}, [], []
    for key, unit in sorted((doc.get("units") or {}).items()):
        serial = int(key, 16)
        for i in (unit.get("learned") or []):
            i = int(i)
            pos = known.get(i)
            if pos is None:
                unknown.append(dict(serial=serial, id=i))
            elif pos < BIT_CAPACITY:
                native.append(dict(serial=serial, id=i))
            else:
                pairs.setdefault(serial, []).append(i)
    for q in (doc.get("quarantine") or []):
        unknown.append(dict(serial=int(q["serial"]), id=int(q["id"])))
    return pairs, native, unknown


# ------------------------------------------------------------------------------------- install
WARN_SHARE = 0.95            # warn when the table uses this share of the bitmap's positions
SHOP_ARRAY = 1000            # FUN_140832120 / FUN_14084EB50: two unchecked 1,000-entry short arrays
INNATE_MAX_ID = 32767        # innate / equipped evility ids are i16 in the unit record (+0x2EEE, +0x2EFC, +0x2F10)
INNATE_FREE = 9999           # ... and 9999 is the game's "free slot" marker there


def budget(rows):
    """DRPGEVIL1b: the Skill.dat position budget of a finished table.  rows = dicts with id, kind, shop_rank.

    What a position past 999 means (probe: evility/probe_drpgevil1b_capacity.py, decomp 140218c90 / 14008d0f0):
    an INNATE evility (kind 1/2, linked from a char row) never needs a bitmap bit -- the unit record holds its id
    as an i16, the active list and every name lookup go by id -- so it may sit anywhere.  A LEARNABLE row (kind 0)
    past 999 has no native bit: only the Kit's .d5lc store can hold it, and ten inlined game consumers
    (EVCAP2-REPORT s3 B) do not see the store.  The importer gate therefore fails on a learnable row past the
    bitmap; innate-only rows there are fine.  Also failed: more than 1,000 shop rows (the evility screen appends
    every row with shop_rank >= 1 to a fixed 1,000-entry array without a bound check) and an id the unit
    record cannot hold.  Returns {total, positions_left, learnable_past, innate_past, shop_rows, bad_ids,
    errors, warnings}.
    """
    rows = sorted(rows, key=lambda r: int(r["id"]))
    past = rows[BIT_CAPACITY:]
    learnable = [int(r["id"]) for r in past if int(r.get("kind", 0)) == 0]
    shop = sum(1 for r in rows if int(r.get("shop_rank", 0)) >= 1)
    bad = [int(r["id"]) for r in rows if int(r["id"]) > INNATE_MAX_ID or int(r["id"]) == INNATE_FREE]
    errors, warnings = [], []
    if learnable:
        errors.append(f"{len(learnable)} learnable evility row(s) past bitmap position {BIT_CAPACITY - 1} "
                      f"(first id {learnable[0]}): give learnable rows ids that sort before the innate-only rows")
    if shop > SHOP_ARRAY:
        errors.append(f"{shop} rows with shop_rank >= 1: the evility screen's {SHOP_ARRAY}-entry array would overflow")
    if bad:
        errors.append(f"evility id(s) the unit record cannot hold (above {INNATE_MAX_ID}, or {INNATE_FREE}): {bad[:8]}")
    n_learn = sum(1 for r in rows[:BIT_CAPACITY] if int(r.get("kind", 0)) == 0)
    if len(rows) >= WARN_SHARE * BIT_CAPACITY and not learnable:
        warnings.append(f"{len(rows)} rows: {min(len(rows), BIT_CAPACITY)} of {BIT_CAPACITY} bitmap positions used "
                        f"({n_learn} by learnable rows); a new learnable row must sort inside the first {BIT_CAPACITY}")
    return dict(total=len(rows), positions_left=max(0, BIT_CAPACITY - len(rows)), learnable_past=learnable,
                innate_past=len(past) - len(learnable), shop_rows=shop, bad_ids=bad, errors=errors, warnings=warnings)


def moved(installed, staged):
    """EVILFX2b save-safety gate: the installed LEARNABLE rows (kind 0) whose table position changes.

    A save holds learned evilities as one bit per Skill.dat row position, so an install that inserts or removes a
    row before an installed learnable row re-points that row's bit in every save.  `installed` / `staged` are the
    full tables (vanilla + mod rows) before and after; returns [(id, old position, new position or None)].
    """
    pos = lambda rows: {i: n for n, i in enumerate(sorted(int(r["id"]) for r in rows))}     # noqa: E731
    old, new = pos(installed), pos(staged)
    return [(int(r["id"]), old[int(r["id"])], new.get(int(r["id"]))) for r in sorted(installed, key=lambda r: int(r["id"]))
            if int(r.get("kind", 0)) == 0 and new.get(int(r["id"])) != old[int(r["id"])]]


def mastery_faults(rows, jobrank_ids):
    """SKILLTRAINERCRASH1: the rows that make the Skill Shop read a JobRank row that does not exist.

    The shop predicate FUN_1407CD9C0 runs over *every* Skill row for the chosen unit.  For a row sold by class
    mastery (source 3) it looks up JobRank `owner + 5` (kind 1) or `owner + class_order - 1` (kind 0) and reads the
    threshold at result + 4 without a NULL check.  Rows it never looks up: mana_cost < 1, version_group > 150, kind 2.
    rows = dicts (id, kind, source, owner, class_order, mana_cost, version_group).  -> [(id, kind, JobRank id)]
    """
    have = {int(i) for i in jobrank_ids} - {0}          # the game's lookup answers NULL for id 0
    signed = lambda v: int(v) - (1 << 32) if int(v) >= 1 << 31 else int(v)              # noqa: E731
    out = []
    for r in rows:
        g = lambda k: signed(r.get(k, 0) or 0)                                          # noqa: E731
        if g("source") != 3 or g("kind") not in (0, 1) or g("mana_cost") < 1 or g("version_group") > 150:
            continue
        key = (g("owner") + (5 if g("kind") == 1 else g("class_order") - 1)) & 0xFFFFFFFF
        if key not in have:
            out.append((g("id"), g("kind"), key))
    return out


def _guard_mastery(ctx):
    """The finished Skill.dat must hold no row of mastery_faults.  A unique row (kind 1) is made what it was meant to
    be, a character's own evility that no shop sells (source 4, no price); a learnable one (kind 0) has no safe
    reading and is refused.  Every installed pack is covered, whatever tool made it."""
    from . import database
    from .dbpatch import DB_ARCHIVE
    skill = f"{DB_ARCHIVE}/Skill.dat"
    try:
        member, ranks = ctx.get(skill), ctx.get(f"{DB_ARCHIVE}/JobRank.dat")
    except KeyError:
        return
    table = database.load_table("Skill.dat", member)
    faults = mastery_faults([r.to_dict() for r in table.rows],
                            [r["id"] for r in database.load_table("JobRank.dat", ranks).rows])
    if not faults:
        return
    refused = [f for f in faults if f[1] != 1]
    if refused:
        raise ValueError("evility rows sold by class mastery whose JobRank row does not exist (the Skill Shop would "
                         "crash): " + ", ".join(f"{i} (JobRank {k})" for i, _, k in refused[:8]))
    for i, _, key in faults:
        r = table.rows[table.index_of(i)]
        r.set("source", 4)
        r.set("mana_cost", 0)
        ctx.log(f"  WARNING: evility {i} was sold by class mastery but its class has no JobRank row {key} (the Skill "
                f"Shop would crash): installed as a character's own evility instead")
    ctx.put(skill, table.to_bytes())


def _finalize(ctx):
    """rebuild the section from the finished Skill table (every mod's rows in, already id-sorted)"""
    _guard_mastery(ctx)
    if not getattr(ctx, "learned_capacity", True):
        return
    from .dbpatch import DB_ARCHIVE
    try:
        member = ctx.get(f"{DB_ARCHIVE}/Skill.dat")
    except KeyError:
        return
    # DRPGEVIL1c: the position budget is a hard rule of the install.  A learnable row past the bitmap, an id a
    # unit record cannot hold, or a shop list past its array is refused here (ValueError stops the install
    # before anything is written); `D5_SKILL_BUDGET=warn` downgrades it for a deliberate test build.
    from . import database
    b = budget([r.to_dict() for r in database.load_table("Skill.dat", member).rows])
    for line in b["warnings"]:
        ctx.log("  note (skill budget): " + line)
    if b["errors"]:
        if os.environ.get("D5_SKILL_BUDGET") == "warn":
            for line in b["errors"]:
                ctx.log("  WARNING (skill budget, not enforced): " + line)
        else:
            raise ValueError("Skill.dat position budget: " + "; ".join(b["errors"])
                             + " (tools/check_skill_budget.py shows the table)")
    man = manifest_from_member(member)
    exe = ctx.get(EXE_FILE)
    ctx.put(EXE_FILE, build_patch(exe, man))
    ctx.log(f"  learned evilities: bitmap positions 0..{man['base_count'] - 1} native, "
            f"{len(man['ext_ids'])} row(s) beyond the bitmap in the per-unit store "
            f"(table generation {man['generation']:08x}; store {STORE_MAX_USED} pairs = "
            f"128 units x {STORE_MAX_USED // 128} rows)")
    if len(man["ext_ids"]) > STORE_MAX_USED // 128:
        ctx.log(f"  WARNING: {len(man['ext_ids'])} rows beyond the bitmap exceed the store's per-unit "
                f"ceiling of {STORE_MAX_USED // 128}; a unit learning more than that is refused (visible), "
                f"and d5lib.learned.STORE_CAPACITY has to be raised for the next build")


register_finalizer(_finalize)
