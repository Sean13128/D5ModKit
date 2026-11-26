"""Character identity for units in outfits (exe section .d5id).

An outfit turns its unit into another class id (the outfit's slot), but the game recognises its characters by class
id: "is this Killia (10)?", "find the unit of class X".  95 such checks (d5lib/data/identity_sites.json, found by
_research/find_identity_sites.py) see a unit in an outfit as nobody: character-specific features don't happen, and
the Killia lookup at 0x1401cdc90 (on the way back to the hub after a battle) reads through a null pointer when
Killia wears an outfit -- a crash.

Each site gets a stub that compares the unit's BASE class instead: the outfit slot (and the legacy rows that lead
back to a character) -> the character, by a table built at install from the outfit groups.  Find-a-unit loops map
both sides.  Unit setup / copy code that needs the exact class is left alone (see the finder's EXCLUDE).

One more check is not a +0x2E04 compare, so the finder cannot see it: the story title override (Sorrow's
lifecycle_collab_class_title_override, Steam 0x1401C3A90) takes the class id as its argument and switches on it
(Killia 10 -> "Cryo Blood Overlord" once the story flag is set, else "Wanderer"; 0x3C, 0x46, 100, 0x78, 0xBE, 0xDC and
five more likewise).  Its callers first copy the ROW's title into the unit (+0xBFC) -- data_lifecycle_refresh_class_titles
does it for every roster unit on every save load and base entry -- so a unit in an outfit came back as the row's
plain title (OUTFITTITLE1).  The stub maps the argument at the function's entry (title_site), found in the exe by its
bytes, so every caller sees the character.
"""
import re
import json
import os

from . import exepatch

SECTION = b".d5id"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "identity_sites.json")


def class_map(records, bases):
    """{class id: base class id} from the outfit menu records [(group, class, label)] (outfits._groups).  Legacy rows
    (label 0) and numbers the game's scripts spawn helper actors with stay out: a helper must never pass for a
    character."""
    from .sprites import script_spawn_ids
    spawn = script_spawn_ids()
    out = {}
    for g, cls, label in records:
        base = bases[g]
        if int(cls) != int(base) and label and int(cls) not in spawn:
            out[int(cls)] = int(base)
    return out


def _shared(mapping):
    """map: eax = class id -> eax = its character's base class id (all other registers kept)"""
    rows = sorted(mapping.items())
    src = ["push rcx", "push rdx", "lea rcx, [rip + id_table]", f"mov edx, {len(rows)}",
           "id_loop:", "test edx, edx", "je id_done", "cmp eax, dword ptr [rcx]", "jne id_next",
           "mov eax, dword ptr [rcx + 4]", "jmp id_done",
           "id_next:", "add rcx, 8", "dec edx", "jmp id_loop",
           "id_done:", "pop rdx", "pop rcx", "ret", ".align 4", "id_table:"]
    src += [f".long {a}, {b}" for a, b in rows]
    return "\n".join(src)


def sites():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)["sites"]


# lifecycle_collab_class_title_override(class id ecx, title rdx): prologue, then "mov r8, rdx; cmp ecx, 0xdc; jg; je;
# add ecx, -10; cmp ecx, 0xb4" (its switch).  The hook replaces "mov r8, rdx; cmp ecx, 0xdc" (9 bytes).
_TITLE_RE = re.compile(re.escape(bytes.fromhex("48895c2408" "4889742410" "48897c2418")) + b"(" +
                       re.escape(bytes.fromhex("4c8bc2" "81f9dc000000")) + b")" +
                       re.escape(b"\x0f\x8f") + b"....\x0f\x84...." + re.escape(bytes.fromhex("83c1f6" "81f9b4000000")),
                       re.S)
TITLE_ORIG = bytes.fromhex("4c8bc281f9dc000000")


def title_site(exe: bytes, pe=None):
    """the va of the title override's "mov r8, rdx; cmp ecx, 0xdc" in this exe (one match in the game's own
    sections), or None"""
    import pefile
    pe = pe or pefile.PE(data=exe, fast_load=True)
    hits = []
    for sec in pe.sections:
        if sec.Name.startswith(exepatch.KIT_SECTION_PREFIX) or not sec.Characteristics & 0x20000000:      # game code only
            continue
        raw = exe[sec.PointerToRawData:sec.PointerToRawData + sec.SizeOfRawData]
        hits += [exepatch.IMAGE_BASE + sec.VirtualAddress + m.start(1) for m in _TITLE_RE.finditer(raw)]
    return hits[0] if len(hits) == 1 else None


def _title_src(va):
    # flags of the cmp survive the pop; the jump back is written in decimal (a native address: no translation)
    return "\n".join(["push rax", "mov eax, ecx", "call {shared}", "mov ecx, eax", "pop rax",
                      "mov r8, rdx", "cmp ecx, 0xdc", f"jmp {va + len(TITLE_ORIG)}"])


def patch(exe: bytes, mapping, log=print) -> bytes:
    """exe with the identity stubs (only when some class maps to another)"""
    if not mapping:
        return exe
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    hooks, missing = [], []
    from . import exemap
    T = exemap.ACTIVE
    for s in sites():
        va, orig = int(s["va"], 16), bytes.fromhex(s["orig"])
        nva = T(va) if T.has(va) else None
        if nva is None or not exemap.same_code(T, va, orig, nva, pe.get_data(nva - exepatch.IMAGE_BASE, len(orig))):
            missing.append(s["va"])          # another patch owns these bytes (or this build lacks it): left alone
            continue
        hooks.append((va, orig, s["src"], 0xE9))
    tva = title_site(exe, pe)
    if tva is None:
        log("  identity: story title override not found in this exe: outfits show their row's title")
    else:
        hooks.append((exemap.Native(tva), TITLE_ORIG, _title_src(tva), 0xE9))
    if missing:
        log(f"  identity: {len(missing)} site(s) already patched elsewhere, left alone: {', '.join(missing)}")
    log(f"  identity: {len(hooks)} character checks see outfits as their character ({len(mapping)} classes)")
    return exepatch.add_hook_section(exe, SECTION, hooks, _shared(mapping))
