"""Starting weapon levels per class (Characters & Classes › Weapon mastery: the rank and the level next to it).

The game keeps no starting weapon level per class: a new unit gets the class's weapon ranks (char.dat mastery_*,
copied to unit + 0x2DAE + 8 x weapon by the unit setup 0x14021a970) and level 0 in every weapon.  Mods list levels
per class in patches/characters/weapon_levels.json:

    {"257": [fist, sword, spear, bow, gun, axe, staff, monster phys, monster mag, armor], ...}

The install hooks the unit setup right after the ranks are copied (0x14021ae0b; it creates recruits, story joins,
units made at the registrar) and calls the game's own 'set weapon level' (0x14015b980: the level and its experience,
300 x (L (L + 1) / 2 + 4 L)) for each weapon whose level is below the class's.  A unit that already has more keeps it.
Later mods in the load order win for a class they both list.
"""
import json
import os

from .exepatch import add_hook_section
from .gamefs import EXE_FILE
from .modsys import Mod, register_finalizer

SECTION = b".d5wl"
SITE_VA = 0x14021AE0B             # mov byte ptr [rbx + 0x35be], 0xff   (rbx = unit, r14 = the class's char.dat row)
SITE_ORIG = bytes.fromhex("c683be350000ff")
SITE_RET = 0x14021AE12
SET_LEVEL = 0x14015B980           # (rcx unit, dx weapon, r8w level)
WEAPONS = ["fist", "sword", "spear", "bow", "gun", "axe", "staff", "monster_phys", "monster_mag", "armor"]
MAX_LEVEL = 100                   # the game caps weapon experience at level 100's (0x18f2b8)
FILE = "weapon_levels.json"


def _path(mod):
    return os.path.join(mod.patches_dir, "characters", FILE)


def load(mod):
    """{class id: [10 levels]} of one mod"""
    try:
        with open(_path(mod), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in d.items():
        lv = [max(0, min(MAX_LEVEL, int(x))) for x in list(v)[:len(WEAPONS)]]
        out[int(k)] = lv + [0] * (len(WEAPONS) - len(lv))
    return out


def save(mod, table):
    """write the mod's table (classes with no level at all are left out)"""
    data = {str(c): [int(x) for x in v] for c, v in sorted(table.items()) if any(v)}
    p = _path(mod)
    if not data:
        if os.path.exists(p):
            os.remove(p)
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def merged(mods):
    """{class: levels} of these mods, later ones winning"""
    out = {}
    for m in mods:
        out.update(load(m))
    return {c: v for c, v in out.items() if any(v)}


def _src(table):
    """the hook: after the ranks are copied, raise each listed weapon to the class's starting level"""
    nl = chr(10)
    rows = []
    for c, v in sorted(table.items()):
        rows.append(f"    .long {int(c)}")
        rows.append("    .byte " + ", ".join(str(int(x)) for x in v) + ", 0, 0")
    return nl.join([
        "    mov byte ptr [rbx + 0x35be], 0xff",
        "    push rax",
        "    push rcx",
        "    push rdx",
        "    push r8",
        "    push r9",
        "    push r10",
        "    push r11",
        "    push r12",
        "    push r13",
        "    sub rsp, 0x28",
        "    movzx ecx, word ptr [r14 + 0xd0]",
        "    lea r12, [rip + wl_table]",
        f"    mov r13d, {len(table)}",
        "wl_find:",
        "    test r13d, r13d",
        "    je wl_done",
        "    cmp dword ptr [r12], ecx",
        "    je wl_found",
        "    add r12, 16",
        "    dec r13d",
        "    jmp wl_find",
        "wl_found:",
        "    add r12, 4",
        "    xor r13d, r13d",
        "wl_next:",
        f"    cmp r13d, {len(WEAPONS)}",
        "    jge wl_done",
        "    movzx r8d, byte ptr [r12 + r13]",
        "    test r8d, r8d",
        "    je wl_skip",
        "    movzx eax, byte ptr [rbx + r13*8 + 0x2dac]",
        "    cmp eax, r8d",
        "    jae wl_skip",
        "    mov rcx, rbx",
        "    mov edx, r13d",
        f"    call {SET_LEVEL:#x}",
        "wl_skip:",
        "    inc r13d",
        "    jmp wl_next",
        "wl_done:",
        "    add rsp, 0x28",
        "    pop r13",
        "    pop r12",
        "    pop r11",
        "    pop r10",
        "    pop r9",
        "    pop r8",
        "    pop rdx",
        "    pop rcx",
        "    pop rax",
        f"    jmp {SITE_RET:#x}",
        "    .align 4",
        "wl_table:",
    ] + rows)


def build(exe, table):
    """the exe with the starting-level hook for `table` ({class: levels})"""
    if not table:
        return exe
    return add_hook_section(exe, SECTION, [(SITE_VA, SITE_ORIG, _src(table), 0xE9)])


def _finalize(ctx):
    mods = [Mod(f) for f in getattr(ctx, "mod_folders", []) or []]
    table = merged(mods)
    if not table:
        return
    ctx.put(EXE_FILE, build(ctx.get(EXE_FILE), table))
    ctx.log("  weapon levels: starting levels for class(es) " + ", ".join(map(str, sorted(table))))


register_finalizer(_finalize)
