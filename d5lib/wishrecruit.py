"""Recruit wishes: a Dark Assembly (Strategy) bill whose effect is "this character joins" (exe section .d5wr).

A port of Cryswar's Overlord "direct recruit" wishes (overlord/03_subclass_wishes.c: hook_wish_visibility and
resolve_post_vote_wish, The Unlicense -- thanks, Cryswar), made Kit-native and smaller:

* The bill is an ordinary WishDataBase.dat row a mod adds (name, text, mana cost, difficulty, its own
  req_flag1..4 / block_flag1..4 / set_flag1..4 / clear_flag1..4).  This module only adds what the row cannot
  say: which character joins, at which level, and whether a second copy may join.  A mod lists them in
  patches/wishes/recruit_wishes.json:

      {"recruits": {"20300": {"character": 20300, "level": 10},
                    "20000": {"character": 20000, "level": 50, "duplicates": true}}}

  PACKS (RECRUIT2): the value may be a list of such objects; one passed bill then creates every member, each at
  its own level ("2700": [{"character": 3001, "level": 20}, {"character": 3002, "level": 30}]).  The table holds
  one row per member and both hooks scan the whole table (no stop at the first match).  The predicate hides the
  bill unless army + reserve + members <= 128 and no member without "duplicates" is already in the army.
  Refused: an empty pack, a pack over 128, one class twice (unless both say duplicates), one bad member.

* Two hooks, both at Overlord's own sites (re-checked against the decomp of the Steam build, sha1 9460a641...):

  - the Strategy Assembly's bill predicate 0x14044A730 (row in rdx; both Strategy list builders 0x140442BC0 and
    0x1404449A0 call it for every WishDataBase row).  For a listed bill it HIDES the bill when the roster is full
    (army + reserve >= 128: roster_create_unit's own guard) or, unless duplicates are allowed, when a unit of that
    class is already in the army; otherwise it runs the game's own predicate, which applies the row's req/block
    flags.  It never makes visible a bill the game would hide.  (Overlord returns "visible" itself and carries
    the unlock flag in his ini; here the flag is the row's own req_flag1.)
  - the bill's effect, after the vote passes, 0x140221793 in the effect function 0x140221090 (r15 = the passed
    WishDataBase row).  For a listed bill it calls roster_create_unit(character, 0, level) -- the same call
    Overlord makes (RECRUIT_CHARACTER_RVA) and the quest reward hook (d5lib.questpatch) makes -- and then runs
    the game's code unchanged, so the row's set/clear flags apply as for any bill.  roster_create_unit is
    0x1402EA3E0 in the Steam build (decomp, Sorrow's name); the source below names it CREATE_UNIT = 0x1402EA890,
    its address in the Kit's known build, which d5lib.exemap translates to 0x1402EA3E0 when the hook is built.
    (In the Steam build 0x1402EA890 is script_actor_lookup 0x1402EA760 + 0x130: an untranslated call would land
    mid-function.  tools/proof_wishrecruit.py runs the built hook and sees the call reach 0x1402EA3E0.)
    The effect function keeps no xmm value live across the site (RECRUITCHK1: its only xmm use is a 32-byte
    store at 0x1402213FF..0x140221421, before it; proof --abi checks this), so the hook saves no xmm register.

* Bill ids must be >= 2000.  The game's Item Assembly predicate 0x14068FE40 lists exactly the ids 1000..1999
  (and 1), and the Strategy predicate hides that range; Overlord's recruit bills 1049..1057 sit in it, which is
  why his v0.34 runtime needed a live filter on the Item Assembly renderer (0x14043BAE4).  Keeping recruit
  bills at 2000+ removes that need, and keeps them clear of the ids the effect function switches on
  (0x3F3..0x418, 0x7C..0x7E).

* The hook sites are Steam-build addresses (native hooks: exact original bytes, no translation); the game
  addresses the code names (roster_create_unit, the army/reserve counts, the roster) are the Kit's known-build
  names, translated by d5lib.exemap like every other Kit hook.  Another exe build is refused with a reason.

* The two sites are registered as contested in d5lib.overlord_compat.SITES (WISH_VISIBILITY, WISH_EFFECT).  When
  Overlord's runtime is part of the install and his wish hooks can occupy them (mod.json overlord_package.wishes
  is not false), `filter_hooks(..., native=True)` drops them, and this module writes neither (all or nothing)
  and says so.  Other modules are unaffected.
"""
import struct

from . import database, exepatch
from .dbpatch import DB_ARCHIVE
from .gamefs import EXE_FILE
from .modsys import register_finalizer, register_patch_handler

SECTION_NAME = b".d5wr"
FOLDER = "wishes"
DATA_FILE = "recruit_wishes.json"

# Steam build (sha1 9460a6411699..., PE timestamp 0x5C4E7571): Overlord's RVAs + the image base
VIS_SITE = 0x14044A730            # bill predicate entry: mov [rsp+8],rbx / mov [rsp+0x10],rbp / mov [rsp+0x20],rsi
VIS_ORIG = bytes.fromhex("48895c240848896c24104889742420")
VIS_RET = 0x14044A73F             # push rdi (after the displaced prologue)
POST_SITE = 0x140221793           # mov eax,[r15] / mov ecx,eax / cmp eax,0x3e8 / jb 0x1402217af
POST_ORIG = bytes.fromhex("418b078bc83de8030000" "7210")
POST_BELOW = 0x1402217AF          # ids < 1000
POST_RANGE = 0x14022179F          # ids >= 1000: the 1000..1999 test

# known-build names (exemap.KNOWN_SHA1, Oct 2018; d5lib.questpatch uses the same), translated to the Steam build
# by d5lib/data/exe_map_9460a6411699.json -- the Steam address follows each.  Not interchangeable: never write the
# Steam address here (it would be translated as if it were a known-build one).
CREATE_UNIT = 0x1402EA890         # roster_create_unit(class, 0, level) -> unit, 0 when army + reserve >= 128; Steam 0x1402EA3E0
ARMY_COUNT = 0x1455A293C          # Steam 0x145574A9C
RESERVE_COUNT = 0x1455A293E       # Steam 0x145574A9E
UNIT_CLASS = 0x145238A5C          # roster unit 0 + 0x2e04; Steam roster 0x145207DB8 + 0x2e04
UNIT_SIZE = 0x4750
ROSTER_MAX = 0x80

MIN_ID = 2000
ENTRY = struct.Struct("<IIII")    # bill id, class, level, options (bit 0: duplicates allowed)
OPT_DUPLICATES = 1


# ------------------------------------------------------------------------------------------ the table
def _int(v, what):
    if isinstance(v, bool) or not isinstance(v, int):
        try:
            v = int(str(v), 10)
        except ValueError:
            raise ValueError(f"recruit wish: {what} {v!r} is not a whole number") from None
    return v


def _member(bill, e):
    if not isinstance(e, dict):
        raise ValueError(f"recruit wish {bill}: expected an object")
    unknown = set(e) - {"character", "level", "duplicates", "note"}
    if unknown:
        raise ValueError(f"recruit wish {bill}: unknown field(s) {', '.join(sorted(unknown))}")
    cls = _int(e.get("character"), "character")
    lvl = _int(e.get("level", 1), "level")
    if not 0 < cls <= 0x7FFFFFFF:
        raise ValueError(f"recruit wish {bill}: character {cls} is not a class id")
    if not 1 <= lvl <= 9999:
        raise ValueError(f"recruit wish {bill}: level {lvl} is outside 1..9999")
    return (bill, cls, lvl, OPT_DUPLICATES if e.get("duplicates") else 0)


def normalise(recruits):
    """{bill id: member | [member, ...]} from a mod's (or several mods') "recruits" -> [(bill, class, level,
    options)] sorted by bill, a pack's members in the order listed.  A member is {character, level, duplicates}.
    A list is a PACK (RECRUIT2): one passed bill creates every member, each at its own level.  Raises ValueError
    on anything the hooks could not honour."""
    out = {}
    for k, v in (recruits or {}).items():
        bill = _int(k, "bill id")
        if bill < MIN_ID or bill > 0x7FFFFFFF:
            raise ValueError(f"recruit wish {bill}: bill ids must be {MIN_ID} or more (the Item Assembly lists "
                             f"1000..1999 and the Strategy Assembly hides them; below 1000 are the game's own)")
        members = v if isinstance(v, list) else [v]
        if not members:
            raise ValueError(f"recruit wish {bill}: empty pack (list at least one character)")
        if len(members) > ROSTER_MAX:
            raise ValueError(f"recruit wish {bill}: pack of {len(members)} exceeds the roster ({ROSTER_MAX})")
        rows = [_member(bill, m) for m in members]
        seen = {}
        for r in rows:
            prev = seen.get(r[1])
            if prev is not None and not (prev[3] & r[3] & OPT_DUPLICATES):
                raise ValueError(f"recruit wish {bill}: class {r[1]} listed twice in the pack (set "
                                 f"\"duplicates\": true on both to allow copies)")
            seen[r[1]] = r
        out[bill] = rows
    return [r for b in sorted(out) for r in out[b]]


def packs(entries):
    """{bill: [entry, ...]} in order, from normalise() output"""
    d = {}
    for e in entries:
        d.setdefault(e[0], []).append(tuple(e))
    return d


def merge(acc, recruits, where="a mod"):
    """add one mod's recruits to acc ({bill: [entry, ...]}); the same bill twice must give the same pack"""
    for bill, pack in packs(normalise(recruits)).items():
        have = acc.get(bill)
        if have is not None:
            have = [have] if isinstance(have, tuple) else list(have)
            if have != pack:
                raise ValueError(f"recruit wish {bill}: {where} gives it another character/level/pack than an "
                                 f"earlier mod")
        acc[bill] = pack
    return acc


def flatten(acc):
    """acc ({bill: entry | [entry, ...]}) -> entries sorted by bill"""
    out = []
    for b in sorted(acc):
        v = acc[b]
        out += [v] if isinstance(v, tuple) else list(v)
    return out


def table_bytes(entries):
    return b"".join(ENTRY.pack(*e) for e in entries)


# ------------------------------------------------------------------------------------------ the code
def _vis_src(n):
    # entered by `jmp` at the predicate's first byte: the stack is the caller's (return address on top), the
    # arguments are in rcx/rdx/r8.  A listed bill's check pushes what it uses and pops it before leaving.
    # A pack lists the bill several times: the bill is hidden unless army + reserve + (members) <= 128, and
    # hidden if any member that does not allow duplicates is already in the army.
    return "\n".join([
        "mov eax, dword ptr [rdx]",
        "lea r10, [rip + wr_table]",
        f"mov r11d, {n}",
        "wr_v_scan:",
        "cmp dword ptr [r10], eax",
        "je wr_v_listed",
        f"add r10, {ENTRY.size}",
        "dec r11d",
        "jne wr_v_scan",
        "wr_v_game:",
        "mov qword ptr [rsp + 8], rbx",
        "mov qword ptr [rsp + 0x10], rbp",
        "mov qword ptr [rsp + 0x20], rsi",
        f"jmp {VIS_RET}",                                   # decimal: already this build's address
        "wr_v_listed:",
        "push rbx", "push rcx", "push rdx", "push r8", "push r9",
        "movsx r8d, word ptr [rip + WR_ARMY]",
        "movsx r9d, word ptr [rip + WR_RESERVE]",
        "add r9d, r8d",                                     # r9d = army + reserve, grows by one per member
        "lea r10, [rip + wr_table]",
        f"mov r11d, {n}",
        "wr_v_member:",
        "cmp dword ptr [r10], eax",
        "jne wr_v_next",
        "inc r9d",
        f"cmp r9d, {ROSTER_MAX:#x}",
        "jg wr_v_hide",
        f"test byte ptr [r10 + 12], {OPT_DUPLICATES}",
        "jne wr_v_next",
        "mov ebx, dword ptr [r10 + 4]",
        "lea rcx, [rip + WR_UNIT_CLASS]",
        "mov edx, r8d",
        "test edx, edx",
        "jle wr_v_next",
        "wr_v_owned:",
        "cmp dword ptr [rcx], ebx",
        "je wr_v_hide",
        f"add rcx, {UNIT_SIZE:#x}",
        "dec edx",
        "jne wr_v_owned",
        "wr_v_next:",
        f"add r10, {ENTRY.size}",
        "dec r11d",
        "jne wr_v_member",
        "pop r9", "pop r8", "pop rdx", "pop rcx", "pop rbx",
        "jmp wr_v_game",
        "wr_v_hide:",
        "pop r9", "pop r8", "pop rdx", "pop rcx", "pop rbx",
        "xor eax, eax",
        "ret",
        f"WR_ARMY = {ARMY_COUNT:#x}",                       # symbols: keystone makes [rip + sym] rip-relative
        f"WR_RESERVE = {RESERVE_COUNT:#x}",
        f"WR_UNIT_CLASS = {UNIT_CLASS:#x}",
    ])


def _post_src(n):
    # entered by `jmp` in the middle of the effect function (rsp 16-aligned there, r15 = the passed row).  Every
    # register but rax/rcx (which the displaced code sets) leaves as it came, so the game's code after the site
    # runs unchanged; the call gets 32 bytes of home space at an aligned rsp, whatever the alignment was.
    # The scan does not stop at a match: every table entry for the bill creates its unit (a pack).
    return "\n".join([
        "push r10", "push r11", "push rcx", "push rdx", "push r8", "push r9", "push rbp", "push rsi", "push rdi",
        "mov rbp, rsp",
        "and rsp, -16",
        "sub rsp, 0x20",
        "lea rsi, [rip + wr_table]",
        f"mov edi, {n}",
        "wr_p_scan:",
        "mov eax, dword ptr [r15]",
        "cmp dword ptr [rsi], eax",
        "jne wr_p_next",
        "mov ecx, dword ptr [rsi + 4]",
        "xor edx, edx",
        "mov r8d, dword ptr [rsi + 8]",
        f"call {CREATE_UNIT:#x}",                          # rsi/rdi are callee-saved: the scan survives it
        "wr_p_next:",
        f"add rsi, {ENTRY.size}",
        "dec edi",
        "jne wr_p_scan",
        "mov rsp, rbp",
        "pop rdi", "pop rsi", "pop rbp", "pop r9", "pop r8", "pop rdx", "pop rcx",
        "mov eax, dword ptr [r15]",
        "pop r11",
        "pop r10",
        "mov ecx, eax",
        "cmp eax, 0x3e8",
        f"jb {POST_BELOW}",
        f"jmp {POST_RANGE}",
    ])


def _with_table(src, entries):
    return src + "\n.align 4\nwr_table:\n.long " + ", ".join(str(v) for e in entries for v in e)


def _native_hooks(entries):
    n = len(entries)
    return [(VIS_SITE, VIS_ORIG, _with_table(_vis_src(n), entries), 0xE9),
            (POST_SITE, POST_ORIG, _with_table(_post_src(n), entries), 0xE9)]


def yielded_sites(entries=None):
    """the recruit-wish hook sites Overlord's runtime owns in this install (d5lib.overlord_compat.SITES).
    The two hooks are one feature: if his runtime owns either, the Kit writes neither."""
    from . import overlord_compat
    dropped = overlord_compat.filter_hooks(SECTION_NAME, _native_hooks(list(entries or [(0, 0, 0, 0)])), native=True)[1]
    return [hook[0] for hook in dropped]


def build_patch(exe: bytes, entries) -> bytes:
    """the exe with section .d5wr: both hooks, each carrying its own copy of the table.
    Returned unchanged when Overlord's runtime owns either site (all or nothing: a visible bill needs its effect)."""
    entries = list(entries)
    if not entries or yielded_sites(entries):
        return exe
    return exepatch.add_hook_section(exe, SECTION_NAME, [], native_hooks=_native_hooks(entries),
                                     digest={"recruits": [list(e) for e in entries]})


def is_hooked(exe: bytes) -> bool:
    return exepatch.has_feature(exe, SECTION_NAME)


# ------------------------------------------------------------------------------------------ install
def load(mod):
    return mod.load_patch(FOLDER, DATA_FILE) or {"recruits": {}}


def save(mod, d):
    mod.save_patch(FOLDER, DATA_FILE, d)


def _handler(ctx, mod, patch_dir):
    d = load(mod)
    rec = d.get("recruits") or {}
    if rec:
        acc = getattr(ctx, "_recruit_wishes", {})
        merge(acc, rec, f"mod {getattr(mod, 'name', '?')}")
        ctx._recruit_wishes = acc
        ctx.log(f"  recruit wishes: {len(rec)}")


def check_rows(entries, wish_table=None, char_table=None):
    """problems a build should refuse: a bill without its WishDataBase row, a class without its char.dat row"""
    problems = []
    if wish_table is not None:
        ids = {r["id"] for r in wish_table.rows}
        problems += [f"recruit wish {b}: no WishDataBase.dat row {b}" for b in dict.fromkeys(e[0] for e in entries)
                     if b not in ids]
    if char_table is not None:
        ids = {r["id"] for r in char_table.rows}
        problems += [f"recruit wish {b}: no char.dat row for class {c}" for b, c, *_ in entries if c not in ids]
    return problems


def _finalize(ctx):
    acc = getattr(ctx, "_recruit_wishes", {})
    if not acc:
        return
    taken = yielded_sites(flatten(acc))
    if taken:
        ctx.log(f"  recruit wishes: Overlord's runtime owns the wish hook site(s) "
                f"{', '.join(hex(v) for v in taken)}; the Kit writes no .d5wr hooks and "
                f"{len(acc)} Kit recruit wish(es) are left to his custom_wishes.txt")
        return
    entries = flatten(acc)

    def table(name):
        # ctx.get: the table as every earlier step left it (dbpatch's handler puts each mod's added char.dat /
        # WishDataBase rows; newclasses' and outfits' finalizers run before this one, HANDLER_MODULES), the vanilla
        # member when no mod changed it.  It also serializes a parsed-but-unflushed object first, which the old
        # `path in ctx.outputs` test did not see (RECRUITCHK1).
        return database.load_table(name, ctx.get(f"{DB_ARCHIVE}/{name}"))
    problems = check_rows(entries, table("WishDataBase.dat"), table("char.dat"))
    if problems:
        raise ValueError("; ".join(problems))
    ctx.put(EXE_FILE, build_patch(ctx.get(EXE_FILE), entries))
    ctx.log("  recruit wishes: " + ", ".join(f"bill {b} -> class {c} Lv{lv}{' (repeatable)' if o else ''}"
                                             for b, c, lv, o in entries))
    for b, pack in packs(entries).items():
        if len(pack) > 1:
            ctx.log(f"  recruit wish {b}: pack of {len(pack)}")


register_patch_handler(FOLDER, _handler, order=50)
register_finalizer(_finalize)
