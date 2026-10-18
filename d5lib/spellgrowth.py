"""How a spell's reach and area grow with its level (found in disgaea5.exe, 2026-10-17).

Generic spells (Fire, Heal, Braveheart ...: magic.dat attack_map 0) take nothing from magic.dat's range / shape.
In battle the game turns the spell's level (the unit's skill list, +0xcc4 + 16 x i, level byte +5) into a tier:

    level  1   2-5   6-10   11-20   21-40   41-60   61-80   81-90   91+
    tier   1    2     3       4       5       6       7       8      9

and the tier is the spell's reach in panels (0x140160650: + 1 with a staff in hand, + the class's bonus byte, char
row + 0x54b; evilities add more; 0x1401d75e0 clamps the total to 1..18) and how many of the spell area shapes the
player may choose from: AttackMap.dat shapes 1..tier (1 = one panel, 3 = a line of three, 5 = the cross, 9 = 3 x 3;
the spell's power is scaled down for the bigger ones, 0x1401d6d30).  A second copy of the table, a small function
at 0x1401d7780 (level -> 0..8), serves the same purpose elsewhere.

A mod may move the thresholds (patches/spells/growth.json: {"levels": [1, 5, 10, 20, 40, 60, 80, 90]}, the level
up to which each tier lasts): the install hooks both copies with a table of its own.  The last enabled mod with a
table wins (it is one setting for every spell).  The shapes themselves are rows 1-9 of AttackMap.dat: edit them like
any other shape (every spell shares them).
"""
import json
import os

from .exepatch import add_hook_section
from .gamefs import EXE_FILE
from .modsys import Mod, register_finalizer

SECTION = b".d5sg"
DEFAULT_LEVELS = [1, 5, 10, 20, 40, 60, 80, 90]
TIERS = len(DEFAULT_LEVELS) + 1          # 9: reach 1..9, area shapes 1..9
SPELL_SHAPES = list(range(1, 10))
MAX_LEVEL = 99
# the inline table of the spell range (0x140160650): cmp cl, 1 / jle -> 5 bytes; the hook computes edx (the tier)
# from cl (the level) and continues at 0x140160714 (rbx and r11 untouched, rax / rcx / r8 / r9 are reset there)
RANGE_SITE = 0x1401606B4
RANGE_ORIG = bytes.fromhex("80f9017e56")
RANGE_RET = 0x140160714
# the helper (level in edx -> eax 0..8): cmp edx, 1 / jg -> 5 bytes; the hook is the whole function
TIER_SITE = 0x1401D7780
TIER_ORIG = bytes.fromhex("83fa017f03")
FILE = "growth.json"


def tier(level, levels=None):
    """1..9 for a spell level"""
    lv = levels or DEFAULT_LEVELS
    return 1 + sum(1 for t in lv if int(level) > int(t))


def reach_text(levels=None):
    lv = list(levels or DEFAULT_LEVELS)
    parts = []
    lo = 1
    for k, t in enumerate(lv, 1):
        parts.append(f"level {lo}" + (f"-{t}" if t > lo else "") + f": {k}")
        lo = t + 1
    parts.append(f"level {lo}+: {TIERS}")
    return "; ".join(parts)


def _path(mod):
    return os.path.join(mod.patches_dir, "spells", FILE)


def clean(levels):
    """8 increasing levels 1..99"""
    out = []
    last = 0
    for v in list(levels)[:len(DEFAULT_LEVELS)]:
        v = max(last + 1, min(MAX_LEVEL, int(v)))
        out.append(v)
        last = v
    while len(out) < len(DEFAULT_LEVELS):
        out.append(min(MAX_LEVEL, (out[-1] if out else 0) + 1))
    return out


def load(mod):
    """the mod's thresholds, or None"""
    try:
        with open(_path(mod), encoding="utf-8") as f:
            d = json.load(f)
        return clean(d["levels"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(mod, levels):
    """write the mod's thresholds (None or the game's own: the file goes)"""
    p = _path(mod)
    if levels is None or clean(levels) == DEFAULT_LEVELS:
        if os.path.exists(p):
            os.remove(p)
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"levels": clean(levels)}, f, indent=1)


def effective(mods):
    """(levels, mod) of the last mod with a table, else (DEFAULT_LEVELS, None)"""
    out = (list(DEFAULT_LEVELS), None)
    for m in mods:
        lv = load(m)
        if lv is not None:
            out = (lv, m)
    return out


def _table(levels):
    return "    .byte " + ", ".join(str(int(v)) for v in clean(levels))


def _src_range(levels):
    return "\n".join([
        "    movzx eax, cl",
        "    xor edx, edx",
        "    lea r8, [rip + sg_table]",
        "sg_loop:",
        f"    cmp edx, {len(DEFAULT_LEVELS)}",
        "    jge sg_done",
        "    movsx r9d, byte ptr [r8 + rdx]",
        "    cmp eax, r9d",
        "    jle sg_done",
        "    inc edx",
        "    jmp sg_loop",
        "sg_done:",
        "    inc edx",
        f"    jmp {RANGE_RET:#x}",
        "    .align 4",
        "sg_table:",
        _table(levels),
    ])


def _src_tier(levels):
    return "\n".join([
        "    xor eax, eax",
        "    lea r8, [rip + sg_table2]",
        "sg2_loop:",
        f"    cmp eax, {len(DEFAULT_LEVELS)}",
        "    jge sg2_done",
        "    movsx ecx, byte ptr [r8 + rax]",
        "    cmp edx, ecx",
        "    jle sg2_done",
        "    inc eax",
        "    jmp sg2_loop",
        "sg2_done:",
        "    ret",
        "    .align 4",
        "sg_table2:",
        _table(levels),
    ])


def build(exe, levels):
    """the exe with both tier tables replaced by `levels` (the game's own levels: unchanged)"""
    if clean(levels) == DEFAULT_LEVELS:
        return exe
    return add_hook_section(exe, SECTION, [(RANGE_SITE, RANGE_ORIG, _src_range(levels), 0xE9),
                                           (TIER_SITE, TIER_ORIG, _src_tier(levels), 0xE9)])


def _finalize(ctx):
    mods = [Mod(f) for f in getattr(ctx, "mod_folders", []) or []]
    levels, who = effective(mods)
    if who is None:
        return
    ctx.put(EXE_FILE, build(ctx.get(EXE_FILE), levels))
    ctx.log(f"  spells: reach and area tiers at levels {levels} ({who.name})")


register_finalizer(_finalize)
