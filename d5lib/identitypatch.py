"""Character identity for units in outfits (exe section .d5id).

An outfit turns its unit into another class id (the outfit's slot), but the game recognises its characters by class
id: "is this Killia (10)?", "find the unit of class X".  95 such checks (d5lib/data/identity_sites.json, found by
_research/find_identity_sites.py) see a unit in an outfit as nobody: character-specific features don't happen, and
the Killia lookup at 0x1401cdc90 (on the way back to the hub after a battle) reads through a null pointer when
Killia wears an outfit -- a crash.

Each site gets a stub that compares the unit's BASE class instead: the outfit slot (and the legacy rows that lead
back to a character) -> the character, by a table built at install from the outfit groups.  Find-a-unit loops map
both sides.  Unit setup / copy code that needs the exact class is left alone (see the finder's EXCLUDE).
"""
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
    if missing:
        log(f"  identity: {len(missing)} site(s) already patched elsewhere, left alone: {', '.join(missing)}")
    log(f"  identity: {len(hooks)} character checks see outfits as their character ({len(mapping)} classes)")
    return exepatch.add_hook_section(exe, SECTION, hooks, _shared(mapping))
