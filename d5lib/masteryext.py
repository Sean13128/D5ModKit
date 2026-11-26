"""Class mastery for custom class families (engine extension, section ".d5cm").

A class mod's own families have char.dat rows, JobRank rows and unlock flags (d5lib.newclasses), so the Class tab
shows their stars.  They still never gained class experience: the game's family -> mastery-slot mapper
(`0x14021EBE0`) answers -1 for any family outside the 47 vanilla ones, and every award/read consumer refuses an
invalid slot.  A subclass chosen on such a family was ignored for the same reason (`0x140160E20` only accepts
1000..1310 / 2010..2300 as a sub-class id), and the Strategy Assembly's sub-class screen (`0x1404707E0`) builds its
candidate rows from a hard-coded 47-family list on its own stack.

Three hooks, all inside the kit's own section, fix that without touching vanilla behavior:

  * mastery slots (`0x14021EBE0`, all 16 call sites): a configured family's ranks return one of the **six spare
    per-unit mastery slots 47..52**.  The native writer (`0x14015F480`), the reader (`0x140217230`), the stars
    panel, the six-counter readers and the transformation copy already accept any index below 53, so they need no
    change at all -- the XP lands in the unit's own record (`unit+0x30A4 + 24*slot + 4*rank`) and is therefore saved,
    loaded and copied by the game itself.
  * sub-class ids (`0x140160E79`): the last gate of the selected-award wrapper accepts a configured family's ranks,
    so `award` follows the chosen sub-class instead of falling back to the unit's own class.
  * the sub-class screen's family list (`0x140470BD0` fetch + `0x140470DB7` bound): the 47 vanilla families stay
    exactly as they were; configured families follow them, limited by the screen object's own row capacity (47 rows
    of 0x238 bytes at `+0x2768`, object size 0x8FC0 -- a row is only started while fewer than 47 exist).

Where the progress lives: nowhere new.  The unit record is 0x4750 bytes inside the game state blob (0x89B8C8) that
the save file stores verbatim, `unit+0x30A4` .. `+0x359B` is the 53-slot x 6-counter mastery array, `+0x359C` ..
`+0x35AB` are the eight completion-bonus words and `+0x35AC` the sub-class.  Slots 47..52 exist in the array, are
zero in every existing save, and are copied/refused/clamped exactly like the vanilla ones.  Existing saves keep
working (their spare slots read 0 = no progress) and no file format changes.  Six families can hold their own
progress at once; `d5lib.classmastery` keeps the (inactive) side-table codec for a future seventh family and beyond.

Mod data (patches/classes/mastery.json):
  {"mastery": {"families": [1350, 1360]}}
Only a modded family that already has classes (a slot or a registry lease) can be listed; at most six families.
"""
import json
import os
import struct
import time

from .exepatch import add_code_section, code_base
from .gamefs import EXE_FILE
from .modsys import register_finalizer, register_patch_handler

FOLDER = "classes"
DATA_FILE = "mastery.json"
SECTION_NAME = b".d5cm"
CLAIM = b"D5CM"                     # first bytes of the section, so a rebuild and the tests can find it again

# The game's family -> mastery slot mapper (RVA 0x21EBE0) and every direct call of it in the pinned build
# (sha256 49a7530b...db282ce).  A call the compiler made indirect would be missed; build_patch checks each site's
# bytes, so a different exe build fails instead of hooking something else.
MAPPER = 0x14021EBE0
MAPPER_CALLS = (0x1400B3CE8, 0x14015F500, 0x140217241, 0x140217326, 0x1402A3A5D, 0x1402A3B00,
                0x1402A3DD5, 0x1402A3E84, 0x1402A3F34, 0x1402A3FE4, 0x1402A4094, 0x1402A4144,
                0x1402A43CC, 0x14047FFC8, 0x1407CDA8C, 0x1407CDAD9)
WRITER, READER, GATE = 0x14015F480, 0x140217230, 0x1401C6110
# The writer continues here after its mapper call; that is the only caller that re-reads the target id (r10) it kept
# across the call, so it is the only site whose target the wrapper reduces to the family base.
WRITER_MAPPER_SITE = 0x14015F500
WRITER_RET = WRITER_MAPPER_SITE + 5
RANK_SLOTS = 53                     # the reader's own bound (`cmp eax, 0x35`) and the transformation's 318 u32 copy
SLOT_FIRST, SLOT_COUNT = 47, 6      # the free tail of the per-unit array

# The selected-award wrapper's last sub-class gate: `mov ebx, 0x3e8 / movzwl cx / sub bx, ax / cmp di, ax / ja
# fallback`.  Replaced by `call stub / test al, al / je fallback` + nops; the accept path follows at +0x10.
SUBCLASS_SITE = 0x140160E79
SUBCLASS_ORIG = bytes.fromhex("bbe80300000fb7c1662bc3663bc77703")
SUBCLASS_ACCEPT, SUBCLASS_REJECT = 0x140160E89, 0x140160E8C

# The sub-class screen's family fetch (`mov r15d, [rbp + r13*4 - 0x70]`, the 47-entry stack array) and its loop bound
FETCH_SITE, FETCH_ORIG = 0x140470BD0, bytes.fromhex("468b7cad90")
BOUND_SITE, BOUND_ORIG = 0x140470DB7, bytes.fromhex("4983fd2f")
ROW_CAP = 47                        # rows of 0x238 at +0x2768; the object is 0x8FC0 bytes
COUNT_OFFSET = 0x8C                 # rows in use (`*(int *)(screen + 0x8c)`)
NATIVE_FAMILIES = tuple(range(1010, 1270, 10)) + tuple(range(2010, 2220, 10))
RANKS = 6                           # ranks a family has in JobRank.dat
FAMILY_SPAN = 10                    # the wrapper's claim test (`target - family <= 9`); six of those ids exist


# ------------------------------------------------------------------------------------------ mod data
def load(mod):
    """a mod's mastery families ({"mastery": {"families": [...]}}); empty when it has none"""
    return mod.load_patch(FOLDER, DATA_FILE) or {}


def families_from(data, specs=(), require_declared=False, limit=True):
    """the configured family bases, validated, in slot order

    `specs` are the mod's class specs ({family: spec}); a family must be one of them (or a dummy family the kit
    fills), so mastery can never be declared for a class the build does not create.  `require_declared` is the
    final-build check: with it, a configured family that the build has no class for is an error even when the build
    knows no classes at all (a mastery-only mod with a missing or failed class load used to pass validation and get
    a mapping for an absent class).
    """
    declared = {int(k) for k in (specs or {})}
    if require_declared and not declared:
        raise ValueError("mastery families configured but this build has no classes: "
                         "add the class_<family>.json files (or turn the mastery block off)")
    block = (data or {}).get("mastery")
    raw = (block if isinstance(block, dict) else data or {}).get("families") if data else None
    if not raw:
        return []
    fams = []
    for value in raw:
        fam = int(value)
        if fam % 10:
            raise ValueError(f"mastery family {fam} is not a family base (id % 10 must be 0)")
        if not 1000 <= fam <= 32760 or 20000 <= fam < 22000:
            raise ValueError(f"mastery family {fam} is reserved or out of range")
        if fam in NATIVE_FAMILIES:
            raise ValueError(f"mastery family {fam} is a vanilla family: it already has mastery slots")
        if declared and fam not in declared:
            raise ValueError(f"mastery family {fam} has no class in this build (add its class_<family>.json)")
        if fam in fams:
            raise ValueError(f"mastery family {fam} is listed twice")
        fams.append(fam)
    fams.sort()
    if limit and len(fams) > SLOT_COUNT:
        raise ValueError(f"{len(fams)} mastery families: at most {SLOT_COUNT} share the free per-unit slots "
                         f"{SLOT_FIRST}..{SLOT_FIRST + SLOT_COUNT - 1} (packed mastery, more than six families, "
                         f"is chosen by d5lib.packedmasteryhook.mode_for -- pass limit=False for it)")
    return fams


LEASE_VERSION = 1
LEASE_FILE = "mastery_slots.json"


class SlotLeases:
    """family -> mastery slot, persisted next to the game's backups and never given to another family.

    The save holds six anonymous counter arrays: a slot does not say which family it belongs to.  Deriving the
    mapping from the sorted enabled set therefore moved saved progress to a different family whenever a family was
    added or removed (enable 1350 next to 1360 and 1360's counters were read as 1350's).  A lease records the
    family, keeps it for good, and a family that leaves the build keeps its slot *reserved* rather than surrendering
    it: re-enabling it later finds its own progress again.
    """

    def __init__(self, path=None, log=print):
        self.path = path
        self.log = log
        self.slots = {}          # family -> slot, live
        self.retired = {}        # family -> slot, not in this build but never reused
        # {"families": [...], "at": ...}: the families whose saved six-slot counters an operator accepted to give up
        # when a packed (.d5pm) install replaced this mapping (tools/accept_packed_mastery.py writes it).  A packed
        # build never assigns, retires or moves a lease; it only reads this acknowledgement.
        self.packed_ack = {}

    @classmethod
    def load(cls, path, log=print):
        self = cls(path, log)
        if not path or not os.path.exists(path):
            return self
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            raise ValueError(f"{path} is not readable: the mastery slots cannot be rebuilt safely "
                             f"(restore it from a backup or delete it to start a new mapping)") from None
        if int(d.get("version", 0)) != LEASE_VERSION:
            raise ValueError(f"{path}: unknown mastery-lease version {d.get('version')!r}")
        self.slots = {int(f): int(s) for f, s in (d.get("slots") or {}).items()}
        self.retired = {int(f): int(s) for f, s in (d.get("retired") or {}).items()}
        ack = d.get("packed_ack") or {}
        self.packed_ack = dict(ack) if isinstance(ack, dict) else {}
        self._check()
        return self

    def _check(self):
        seen = {}
        for fam, slot in list(self.slots.items()) + list(self.retired.items()):
            if not SLOT_FIRST <= slot < SLOT_FIRST + SLOT_COUNT:
                raise ValueError(f"mastery lease {fam} -> slot {slot} is outside {SLOT_FIRST}.."
                                 f"{SLOT_FIRST + SLOT_COUNT - 1}")
            if slot in seen:
                raise ValueError(f"mastery families {seen[slot]} and {fam} both hold slot {slot}")
            seen[slot] = fam

    def adopt(self, families):
        """seed the leases from a mapping the installed exe already carries (upgrading from a kit that had none)"""
        for fam, slot in families.items():
            self.slots.setdefault(int(fam), int(slot))
        self._check()

    def assign(self, families):
        """{family: slot} for `families`: a family keeps its slot, a new one takes a never-used slot, and a family
        that is no longer built keeps its slot reserved."""
        live = sorted({int(f) for f in families})
        for fam in list(self.slots):
            if fam not in live:
                self.retired[fam] = self.slots.pop(fam)
        used = set(self.slots.values()) | set(self.retired.values())
        for fam in live:
            if fam in self.slots:
                continue
            if fam in self.retired:              # re-enabled: it had this slot before
                self.slots[fam] = self.retired.pop(fam)
                continue
            free = [s for s in range(SLOT_FIRST, SLOT_FIRST + SLOT_COUNT) if s not in used]
            if not free:
                held = ", ".join(f"{f} (slot {s}{', retired' if f in self.retired else ''})"
                                 for f, s in sorted({**self.slots, **self.retired}.items(),
                                                    key=lambda kv: kv[1]))
                raise ValueError(
                    f"no free mastery slot for family {fam}: all {SLOT_COUNT} spare slots are leased and a slot is "
                    f"never given to a second family (that would hand it another family's saved progress).  "
                    f"Held: {held}.  Re-enable the mod that family belongs to, or release a slot in {self.path} "
                    f"only if no save holds progress for that family.")
            self.slots[fam] = free[0]
            used.add(free[0])
        self._check()
        return {fam: self.slots[fam] for fam in live}

    def acknowledge_packed(self, families, at=None, note=None):
        """record that these families' saved six-slot counters may be given up to a packed (.d5pm) install"""
        self.packed_ack = {"families": sorted({int(f) for f in families}),
                          "at": at or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                          "note": note or ("packed mastery reuses slots 47..52; these six-slot counters are no "
                                           "longer read. Migrate a *copy* of the save (d5lib/masterymigration.py)")}
        return self.packed_ack

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        record = {"version": LEASE_VERSION,
                  "slots": {str(f): s for f, s in sorted(self.slots.items())},
                  "retired": {str(f): s for f, s in sorted(self.retired.items())}}
        if self.packed_ack:
            record["packed_ack"] = self.packed_ack
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


def slots(families, leases=None):
    """{family: native mastery slot}.  With `leases` the mapping is the persisted one (stable per family across
    enabled-set changes); without one it is the plain sorted order, which is only safe when nothing was ever saved."""
    if leases is not None:
        return leases.assign(families)
    return {fam: SLOT_FIRST + i for i, fam in enumerate(sorted(families))}


# ------------------------------------------------------------------------------------------ the code
def in_family(target, families):
    """is `target` one of a configured family's rank ids (the same window the mapper wrapper claims)?"""
    return any(fam <= target < fam + FAMILY_SPAN for fam in families)


def award_target(target, families):
    """the class id the native writer should work from: the family base for a configured family, else `target`

    Pure policy, stated here so the tests can pin it independently of the assembly.  `target` is the class id an
    award was requested for (a family base plus its rank); the writer's own rank limit is `target % 10`, so handing
    it the base makes the native loop award rank 0 first and let its own overflow carry upwards.
    """
    return target - target % 10 if in_family(target, families) else target


def _mapper_src(fams, table=None):
    """the wrapper: the game's own answer first (vanilla families are untouched), then our families' slots.

    A CALL redirection puts the wrapper in the caller's place with entry RSP%16 == 8; `push rbx` + `sub rsp, 0x20`
    gives the original function its 32 bytes of home space and the alignment it expects, and keeps the id (the
    original mapper divides it by 10 and clobbers rcx).

    The writer (`0x14015F480`) keeps the target class id in `r10` across this call and re-reads it at `0x14015F51C`
    to ask the rank helper for the last rank to award.  When this call came from the writer (the pushed return
    address is `0x14015F505`), a configured family's saved id becomes the family base, which is what makes the award
    fill one star at a time; every other caller's `r10` is left alone.
    """
    # the original mapper clobbers rcx (it divides the id by 10), so the id is kept in a saved rbx
    table = table or {fam: SLOT_FIRST + i for i, fam in enumerate(fams)}
    lines = ["    push rbx", "    sub rsp, 0x20", "    mov ebx, ecx", f"    call {MAPPER:#x}",
             "    cmp eax, -1", "    jne mp_done"]
    for i, fam in enumerate(sorted(fams)):
        lines += [f"    lea edx, [rbx - {fam}]", "    cmp edx, 9", f"    jbe mp_{i}"]
    lines += ["    mov eax, -1", "    jmp mp_done"]
    for i, fam in enumerate(sorted(fams)):
        slot = table[int(fam)]
        lines += [f"mp_{i}:",
                  "    mov rax, qword ptr [rsp + 0x28]",     # the caller's return address (push 8 + frame 0x20)
                  f"    mov rdx, {WRITER_RET:#x}",
                  "    cmp rax, rdx",
                  f"    jne mp_slot_{i}",
                  f"    mov r10d, {fam}",                     # award order: rank limit 0, native overflow carries
                  f"mp_slot_{i}:",
                  f"    mov eax, {slot}",
                  "    jmp mp_done"]
    lines += ["mp_done:", "    add rsp, 0x20", "    pop rbx", "    ret"]
    return "\n".join(lines)


def _subclass_src(fams):
    """the selected-award wrapper's last sub-class gate, replaced as a whole (jmp in, jmp out; no return address,
    so nothing about the stack changes).  al/ax hold the game's own test, cx is the sub-class id, rdx the unit's own
    class: only eax is used here.  Accept follows the original accept path, reject the original fallback."""
    lines = ["    mov eax, ecx", "    sub eax, 2010", "    cmp eax, 0x122", "    jbe sc_yes",
             "    mov eax, ecx", "    sub eax, 1000", "    cmp eax, 0x136", "    jbe sc_yes"]
    for fam in fams:
        lines += [f"    lea eax, [rcx - {fam}]", f"    cmp eax, {RANKS - 1}", "    jbe sc_yes"]
    lines += [f"    jmp {SUBCLASS_REJECT:#x}", "sc_yes:", f"    jmp {SUBCLASS_ACCEPT:#x}"]
    return "\n".join(lines)


def _fetch_src(fams):
    """the sub-class screen's family for index r13: the game's own 47-entry stack array below 47, ours above it.

    rsi is still the screen object here (the native loop copies it to rcx on the next instruction) and r15 is the
    register the replaced instruction wrote, so nothing else changes.  A family is only offered while the screen has
    a free row (fewer than 47 rows started): family 0 makes the native availability test say no, i.e. skip.
    """
    lines = ["    cmp r13d, 0x2f", "    jae ft_extra", "    mov r15d, dword ptr [rbp + r13*4 - 0x70]", "    ret",
             "ft_extra:", f"    cmp dword ptr [rsi + {COUNT_OFFSET:#x}], 0x2f", "    jae ft_none"]
    for i, fam in enumerate(fams):
        lines += [f"    cmp r13d, {0x2f + i}", f"    je ft_{i}"]
    lines += ["    jmp ft_none", "ft_none:", "    xor r15d, r15d", "    ret"]
    for i, fam in enumerate(fams):
        lines += [f"ft_{i}:", f"    mov r15d, {fam}", "    ret"]
    return "\n".join(lines)


def _asm_sources(fams, table=None):
    """[(tag, source)]; the tags only matter to the tests."""
    return [("mapper", _mapper_src(fams, table)), ("subclass", _subclass_src(fams)), ("fetch", _fetch_src(fams))]


def _claim_header(offset, count):
    """the 16-byte claim: "D5CM", the (family, slot) table's offset and length, and the lease format version.  The
    table itself is written after the code: the section's unwind/stack audit decodes from `claim + 16`, so nothing
    but instructions may sit in front of the first routine."""
    return CLAIM + bytes(16 - len(CLAIM) - 12) + struct.pack("<III", int(offset), int(count), LEASE_VERSION)


def _mapping_bytes(table):
    """the family -> slot table (pairs of u32), written at the end of the section so it can be read back by the
    next build instead of that build guessing the mapping it is about to replace."""
    out = b""
    for fam, slot in sorted(table.items()):
        out += struct.pack("<II", int(fam), int(slot))
    return out


def read_mapping(exe):
    """{family: slot} recorded in the installed .d5cm section, or {} when there is none"""
    info = section_info(exe)
    if not info:
        return {}
    data = info["data"]
    try:
        offset, count, version = struct.unpack_from("<III", data, 4)
    except struct.error:
        return {}
    if version != LEASE_VERSION or not count:
        return {}
    table = {}
    for i in range(count):
        try:
            fam, slot = struct.unpack_from("<II", data, offset + i * 8)
        except struct.error:
            return {}
        table[int(fam)] = int(slot)
    return table


def _assemble(src, base):
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_64).asm(src, base)
    return bytes(enc)


def _offsets(exe):
    """one PE parse for every site: va -> file offset"""
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    return lambda va: pe.get_offset_from_rva(va - IMAGE_BASE)


def _check_sites(exe, at):
    """refuse a different exe build (or an exe another hook already changed): every redirect site must still hold
    the instruction this module was written for"""
    from . import packedmasteryhook
    if packedmasteryhook.section_info(exe):
        raise ValueError('the six-slot mastery extension (.d5cm) and packed mastery (.d5pm) map the same 16 '
                         'class-mastery calls: this exe already carries ".d5pm".  A build has one mapping '
                         'source -- keep the packed block for more than six families, or drop it for this one')
    for va in MAPPER_CALLS:
        orig = exe[at(va):at(va) + 5]
        if orig[:1] != b"\xe8" or va + 5 + struct.unpack("<i", orig[1:])[0] != MAPPER:
            raise ValueError(f"mastery extension: {va:#x} is not a call of {MAPPER:#x} "
                             f"(different exe build, or that site is already hooked)")
    for va, orig in ((SUBCLASS_SITE, SUBCLASS_ORIG), (FETCH_SITE, FETCH_ORIG), (BOUND_SITE, BOUND_ORIG)):
        if exe[at(va):at(va) + len(orig)] != orig:
            raise ValueError(f"mastery extension: {va:#x} does not hold the expected instruction "
                             f"(different exe build, or that site is already hooked)")


def build_patch(exe, families, table=None):
    """the exe with section .d5cm and the three hooks in place; `families` are family bases (already validated).
    `table` is the persisted {family: slot} mapping; without one the sorted order is used (only correct when no save
    holds mastery progress yet)."""
    fams = sorted({int(f) for f in families})
    if not fams:
        raise ValueError("no mastery families: nothing to extend")
    if len(fams) > SLOT_COUNT:
        raise ValueError(f"at most {SLOT_COUNT} mastery families")
    table = dict(table or {fam: SLOT_FIRST + i for i, fam in enumerate(fams)})
    if sorted(table) != fams or len(set(table.values())) != len(table):
        raise ValueError("mastery slot table does not match the configured families")
    at = _offsets(exe)
    _check_sites(exe, at)
    base = code_base(exe, SECTION_NAME)
    code = bytearray(_claim_header(0, len(table)))
    starts = {}
    for tag, src in _asm_sources(fams, table):
        code += b"\xcc" * (-len(code) % 16)
        starts[tag] = base + len(code)
        code += _assemble(src, base + len(code))
    code += b"\xcc" * (-len(code) % 4)
    code[0:16] = _claim_header(len(code), len(table))
    code += _mapping_bytes(table)
    patches = [(va, exe[at(va):at(va) + 5], starts["mapper"], 0xE8) for va in MAPPER_CALLS]
    patches.append((SUBCLASS_SITE, SUBCLASS_ORIG, starts["subclass"], 0xE9))
    patches.append((FETCH_SITE, FETCH_ORIG, starts["fetch"], 0xE8))
    out = add_code_section(exe, SECTION_NAME, bytes(code), patches)
    # the sub-class screen's loop bound (imm8 of `cmp r13, 0x2f`): our families follow the 47 vanilla ones
    off = _offsets(out)(BOUND_SITE)
    if out[off:off + 3] != BOUND_ORIG[:3]:
        raise ValueError("mastery extension: the sub-class loop bound changed under the section append")
    from . import exemap
    exemap.claim(BOUND_SITE + 3, 1, "sub-class loop bound")      # written in place below
    out = bytearray(out)
    out[off + 3] = 0x2F + len(fams)
    return bytes(out)


def section_info(exe):
    """where the installed section is ({base, code, size, data, section}) or None

    A section appended by add_code_section grows into the previous kit section when the exe has no room for another
    header, so the claim bytes are searched, not the section name."""
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    for s in pe.sections:
        data = pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)
        at = data.find(CLAIM)
        if at >= 0:
            return {"base": IMAGE_BASE + s.VirtualAddress + at, "code": IMAGE_BASE + s.VirtualAddress + at + 16,
                    "size": s.Misc_VirtualSize - at, "data": data[at:],
                    "section": s.Name.rstrip(b"\0").decode("ascii", "replace")}
    return None


# ------------------------------------------------------------------------------------------ install
def installed_mapping(ctx):
    """{family: slot} of the exe that is installed in this game folder right now ({} when there is none or it has no
    .d5cm section).  The build's own input exe is always pristine, so this is the only place the previous mapping
    can be read from."""
    game_dir = getattr(getattr(ctx, "fs", None), "game_dir", None)
    if not game_dir:
        return {}
    path = os.path.join(game_dir, "disgaea5.exe")
    try:
        with open(path, "rb") as f:
            return read_mapping(f.read())
    except OSError:
        return {}


def lease_path(ctx):
    """where this game folder's family -> slot leases live (next to its backups, so the mapping travels with the
    installed build it describes).  None when the build has no game folder (tests, dry runs)."""
    override = os.environ.get("D5_MASTERY_LEASE_DIR")   # offline builders: keep the kit's state out of the build
    if override:
        return os.path.join(override, LEASE_FILE)
    game_dir = getattr(getattr(ctx, "fs", None), "game_dir", None)
    if not game_dir:
        return None
    from .modsys import game_state_dir
    return os.path.join(game_state_dir(game_dir), LEASE_FILE)


def _handler(ctx, mod, patch_dir):
    # only collect here: whether the family exists in the build is decided once every mod was read (P2, see
    # families_from(require_declared=True))
    from . import packedmasteryhook
    data = load(mod)
    fams = families_from(data, limit=False)       # the six-family cap depends on the mapping source (the finalizer)
    if fams:
        acc = dict(getattr(ctx, "_mastery_families", {}))
        for fam in fams:
            acc[int(fam)] = True
        ctx._mastery_families = acc
        ctx.log(f"  class mastery: {len(acc)} families")
    requested = packedmasteryhook.requested_mode(data)
    if requested:
        previous = getattr(ctx, "_mastery_mode", None)
        if previous and previous != requested:
            raise ValueError(f"mastery mode: mod '{getattr(mod, 'id', mod)}' asks for '{requested}' and another mod "
                             f"asks for '{previous}': a build has one mapping source (.d5cm or .d5pm, never both)")
        ctx._mastery_mode = requested
        ctx.log(f"  class mastery: mapping source {requested} (declared by the mod)")


def _finalize(ctx):
    fams = sorted(getattr(ctx, "_mastery_families", {}))
    if not fams:
        return
    specs = getattr(ctx, "_class_specs", {})
    fams = families_from({"mastery": {"families": fams}}, specs, require_declared=True, limit=False)
    from . import packedmasteryhook
    mode = packedmasteryhook.mode_for(fams, requested=getattr(ctx, "_mastery_mode", None))
    if mode == packedmasteryhook.MODE_PACKED:
        # more than six families: the packed pool replaces the six native slots.  The lease file is not touched
        # (a packed build neither assigns nor retires a lease); existing six-slot progress must be acknowledged.
        packedmasteryhook.install(ctx, fams)
        return
    path = lease_path(ctx)
    leases = SlotLeases.load(path, ctx.log)
    previous = installed_mapping(ctx)
    if previous and not leases.slots and not leases.retired:
        # upgrading an install made before the leases existed: its mapping was the sorted order, which is exactly
        # what the section records, so adopt it instead of renumbering the families (that would move saved progress)
        leases.adopt(previous)
        ctx.log(f"  class mastery: adopted the slot mapping of the installed build ({len(previous)} families)")
    table = leases.assign(fams)
    moved = {fam: (previous[fam], table[fam]) for fam in table if fam in previous and previous[fam] != table[fam]}
    if moved:
        raise ValueError("mastery slots would move saved progress: "
                         + ", ".join(f"{fam} {old} -> {new}" for fam, (old, new) in sorted(moved.items()))
                         + f" (fix {path or 'the lease file'})")
    exe = build_patch(ctx.get(EXE_FILE), fams, table)
    leases.save()                # the mapping is durable before the exe that uses it is written
    ctx.put(EXE_FILE, exe)
    ctx.log("  class mastery: " + ", ".join(f"{fam} -> slot {slot}" for fam, slot in sorted(table.items()))
            + f" (of {RANK_SLOTS} per-unit slots; saved with the unit record; leases in "
            + (path or "memory (no game folder in this build)") + ")")


register_patch_handler(FOLDER, _handler, order=46)
register_finalizer(_finalize)
