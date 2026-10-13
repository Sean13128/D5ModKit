"""Custom colour slots (runtime feature of the kit's DLL, d5lib/native/d5color.inc.c) and Extra Color 4.

Every character gets three "Custom Color" slots in the Strategy Assembly: in "Change More Colors" (the precise
editor) a key saves the colours being edited into slot 1-3, and "Change Colors" lists the saved slots below
"Extra Color 1-3".  Slots belong to a class id (each outfit is its own class) and are shared by all saves; they
live in d5colors.bin next to the game (the save only keeps the colours a unit wears).

Extra Color 4: unique characters' sprites carry five palettes (Normal + 4 extra colours) but the colour list
(0x1404558c0, both "Change Colors" and the precise editor's base list) stops after Extra Color 3: entry n is
palette n and the unique branch skips n > 3 (0x1404560dc).  An exe hook lets n = 4 through ("Extra Color 4", the
game's own "Extra Color %d" text) for every unique class whose sprite really has a fifth palette (a missing palette
crashes the editor, see questpatch); Liezerota and Seraphina's Father (4 palettes) keep three.

Mod data: patches/customcolors/settings.json  {"key": "U", "pad": "R3", "extra_color_4": true}
"""
import json
import os
import struct

from . import database, exemap
from .dbpatch import DB_ARCHIVE
from .exepatch import add_hook_section
from .gamefs import EXE_FILE
from .modsys import KIT_DIR, register_finalizer, register_patch_handler

DEFAULTS = {"key": "U", "pad": "R3", "extra_color_4": True}

SECTION_NAME = b".d5c4"
EC4_VA = 0x1404560DC              # lea eax, [r15-1] / cmp eax, 2 / ja 0x140455e86   (r15 = entry, rsi = scene)
EC4_ORIG = bytes.fromhex("418d47ff83f8020f879dfdffff")
EC4_LABEL = 0x1404560E9           # "Extra Color %d" entry
EC4_SKIP = 0x140455E7C            # next entry (reloads rdx = the class bit mask the loop top tests)
# other builds of the game: the same code with other registers -> (original bytes, entry register, scene register)
EC4_BUILDS = {"9460a6411699": (bytes.fromhex("418d46ff83f8020f87b0fdffff"), "r14", "r15")}    # Steam, 2019-01
CACHE = os.path.join(KIT_DIR, "cache", "palette_counts.json")      # + the game folder: builds differ in sprites


def load_settings(mod):
    s = dict(DEFAULTS)
    s.update(mod.load_patch("customcolors", "settings.json") or {})
    return s


def _handler(ctx, mod, pdir):
    ctx.custom_colors = load_settings(mod)        # the runtime is built by d5lib.runtime's finalizer


def _palettes(data):
    from . import anm
    a = anm.load(data)
    return len(a.palettes)


def palette_counts(ctx, numbers):
    """{sprite number: palettes} as installed (modded files are read, the game's own ones cached on disk)"""
    from .modsys import game_state_dir
    cache_path = CACHE.replace(".json", "-" + os.path.basename(game_state_dir(ctx.fs.game_dir)).rsplit("-", 1)[-1]
                               + ".json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = {int(k): v for k, v in json.load(f).items()}
    except Exception:
        cache = {}
    out, changed = {}, False
    for n in numbers:
        vp = f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs"
        if vp.lower() in ctx.outputs:
            try:
                out[n] = _palettes(ctx.get(vp))
            except Exception:
                out[n] = 0
            continue
        if n not in cache:
            try:
                cache[n] = _palettes(ctx.fs.read(vp))
            except Exception:
                cache[n] = 0
            changed = True
        out[n] = cache[n]
    if changed:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in cache.items()}, f)
    return out


def _ec4_form():
    """(original bytes, entry register, scene register) in the game build being patched"""
    return exemap.variant(EC4_BUILDS, (EC4_ORIG, "r15", "rsi"))


def _ec4_src(deny):
    nl = chr(10)
    _, entry, scene = _ec4_form()
    return nl.join([
        f"    lea eax, [{entry} - 1]",
        "    cmp eax, 2",
        f"    jbe {EC4_LABEL:#x}",                       # Extra Color 1-3: as before
        f"    cmp {entry}d, 4",
        f"    jne {EC4_SKIP:#x}",
        f"    mov rax, qword ptr [{scene} + 0x47e0]",      # the unit shown
        "    mov eax, dword ptr [rax + 0x2e04]",
        "    lea rdx, [rip + deny]",
        f"    mov ecx, {len(deny)}",
        "deny_loop:",
        "    test ecx, ecx",
        f"    je {EC4_LABEL:#x}",                       # has a 5th palette: "Extra Color 4"
        "    cmp dword ptr [rdx], eax",
        f"    je {EC4_SKIP:#x}",
        "    add rdx, 4",
        "    dec ecx",
        "    jmp deny_loop",
        "    .align 4",
        "deny:",
        "    .long " + ", ".join(str(c) for c in (deny or [0])),
    ])


def _finalize(ctx):
    s = getattr(ctx, "custom_colors", None)
    if not s or not s.get("extra_color_4", True):
        return
    cpath = f"{DB_ARCHIVE}/char.dat"
    chars = database.load_table("char.dat", ctx.get(cpath))
    uniques = [(r["id"], r["sprite_id"]) for r in chars.rows if 0 < r["id"] < 1000 and r["sprite_id"]]
    counts = palette_counts(ctx, sorted({n for _, n in uniques}))
    deny = sorted({c for c, n in uniques if counts.get(n, 0) < 5})
    exe = ctx.get(EXE_FILE)
    if SECTION_NAME in exe[:0x400]:
        return
    ctx.put(EXE_FILE, add_hook_section(exe, SECTION_NAME, [(EC4_VA, _ec4_form()[0], _ec4_src(deny), 0xE9)]))
    ctx.log(f"  colours: Extra Color 4 for unique characters ({len(deny)} class(es) without a 5th palette keep 3)")


register_patch_handler("customcolors", _handler, order=55)
register_finalizer(_finalize)
