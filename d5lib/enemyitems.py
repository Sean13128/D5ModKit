"""Enemy equipment: the item level and the rarity of what a stage's units wear.

A .chr unit record (d5lib.mapfile) has five equipment slots: item.dat ids at +0x18 (u32 each) and, at +0x2C, one u16
per slot that the spawn (0x140525f20, the loop at 0x140526e62) writes into the item it makes as its level (item
+0x12c and +0x13e): the item level is the record's already.  The rarity is not: every enemy item is made with
0x1401c9ee0(item, id, 0, 5), and 5 asks 0x1401c97d0 -> 0x1401c7e00 for a random rarity (the game's rarity scale:
Common 0-24, Rare 25-49, Legendary 50-99, 100 the Item World's best; the rarity is also the % the item's stats rise).
A value of 1000 + n there gives rarity n exactly (items of rank % 100 >= 40 and a few special ids keep their fixed
rarity whatever is asked).

The kit keeps a unit's chosen rarities in the high 16 bits of its equipment ids (rarity + 1; 0 = the game's roll; no
item id is over 0xFFFF) and patches the spawn (code section ".d5ei") when an enabled mod's stages use them:
    * the id read (mov edx, [r12]) reads the low 16 bits only;
    * the rarity argument (mov r9d, 5) becomes 1000 + rarity for a slot with a rarity, 5 otherwise.
A mod's Stages page save lists its maps with rarities in patches/stages/item_rarity.json, and the install patches
the exe when any enabled mod has one (without the patch an id with high bits would be unknown: no item).
"""
from .exepatch import add_hook_section
from .gamefs import EXE_FILE
from .modsys import Mod, register_finalizer

SECTION = b".d5ei"
FILE = "item_rarity.json"
RARITY_MAX = 100
# the equipment loop of the spawn: mov edx, dword ptr [r12] / call 0x140061ec0 (item.dat index of an id)
ID_SITE = 0x140526E62
ID_ORIG = bytes.fromhex("418b1424e855b0b3ff")
ID_RET = 0x140526E6B
ITEM_INDEX = 0x140061EC0
# mov r9d, 5 / xor r8d, r8d (the arguments of 0x1401c9ee0: r9d = the rarity request)
RARITY_SITE = 0x140526F35
RARITY_ORIG = bytes.fromhex("41b9050000004533c0")
RARITY_RET = 0x140526F3E
BANDS = [(0, "Common"), (25, "Rare"), (50, "Legendary"), (100, "Best (100)")]


def band(r):
    """the rarity's name (Common / Rare / Legendary)"""
    name = BANDS[0][1]
    for lo, n in BANDS:
        if r >= lo:
            name = n
    return name


def _src_id():
    return "\n".join([
        "    movzx edx, word ptr [r12]",
        f"    call {ITEM_INDEX:#x}",
        f"    jmp {ID_RET:#x}",
    ])


def _src_rarity():
    return "\n".join([
        "    movzx r9d, word ptr [r12 + 2]",
        "    test r9d, r9d",
        "    jz ei_roll",
        "    add r9d, 999",
        "    jmp ei_go",
        "ei_roll:",
        "    mov r9d, 5",
        "ei_go:",
        "    xor r8d, r8d",
        f"    jmp {RARITY_RET:#x}",
    ])


def build(exe):
    return add_hook_section(exe, SECTION, [(ID_SITE, ID_ORIG, _src_id(), 0xE9),
                                           (RARITY_SITE, RARITY_ORIG, _src_rarity(), 0xE9)])


def is_patched(exe):
    return SECTION in exe[:0x400]


def maps_of(mod):
    """map numbers of a mod whose units have a rarity set"""
    d = mod.load_patch("stages", FILE) or {}
    return sorted(int(m) for m in d.get("maps", []))


def note_map(mod, map_id, uses):
    """the Stages page saved map `map_id` into `mod`: does a unit of it have a rarity?"""
    have = set(maps_of(mod))
    (have.add if uses else have.discard)(int(map_id))
    mod.save_patch("stages", FILE, {"maps": sorted(have)} if have else None)


def _finalize(ctx):
    mods = [Mod(f) for f in getattr(ctx, "mod_folders", []) or []]
    users = [m for m in mods if maps_of(m)]
    if not users:
        return
    exe = ctx.get(EXE_FILE)
    if is_patched(exe):
        return
    ctx.put(EXE_FILE, build(exe))
    ctx.log(f"  enemy equipment rarity: on ({', '.join(m.name for m in users)})")


register_finalizer(_finalize)
