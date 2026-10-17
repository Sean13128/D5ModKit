"""High-level sprite helpers built on d5lib.anm (character lookup, shared motion set, save/clone)."""
import os
import pickle
import struct

from . import anm
from .gamefs import GameFS

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_DIR = os.path.join(KIT, "cache")
ANIME = "anime"


def anm_name(num: int) -> str:
    return "anm%05d.lzs" % num


def sprite_vpath(fs: GameFS, num: int, lang="EN") -> str:
    name = anm_name(num)
    return f"{fs.resolve(ANIME, name, lang)}/{name}"


def all_sprite_numbers(fs: GameFS):
    out = []
    for n in fs.list_members("Anime/ANM_HI_JP.dat"):
        s = n[3:8]
        if n.startswith("anm") and s.isdigit():
            out.append(int(s))
    return sorted(out)


def resident_block_ids(fs: GameFS):
    """Block ids inside anm_resident (cached on disk).  The anm cache looks there before the loose files, so a
    sprite number that is also a resident block shows the resident picture (vanilla 9030-9032 are effects)."""
    path = os.path.join(CACHE_DIR, "resident_ids.pickle")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    res = anm.parse(fs.read("Anime/ANM_HI_JP.dat/anm_resident.lzs"))
    ids = sorted(b.id for b in res.blocks)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(ids, f)
    return ids


SPAWN_IDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "script_spawn_ids.json")


def script_spawn_ids():
    """Numbers the game's skill scripts spawn helper actors with (cmd_6402 / 6403 / 6405 / 640d; made by
    _research/find_spawn_ids.py).  A number the game has no row / sprite for is an invisible helper: a character row or
    sprite a mod adds with it shows up inside those skills (Tri-Burst drew Girl Laharl through row 9002)."""
    import json
    try:
        with open(SPAWN_IDS, encoding="utf-8") as f:
            return set(json.load(f)["ids"])
    except (OSError, ValueError, KeyError):
        return set()


def used_sprite_numbers(fs: GameFS):
    """Every anm number the game already resolves (loose files and resident blocks) and every number its scripts
    spawn helpers with: none of them may become a new sprite, outfit slot or character id."""
    return set(all_sprite_numbers(fs)) | set(resident_block_ids(fs)) | script_spawn_ids()


_motion_cache = {}


def motion_block(fs: GameFS, block_id=1, progress=None):
    """Shared humanoid motion block from anm_resident (cached on disk after first extraction)."""
    if block_id in _motion_cache:
        return _motion_cache[block_id]
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"motion_block_{block_id}.pickle")
    if os.path.exists(path):
        with open(path, "rb") as f:
            blk = pickle.load(f)
    else:
        if progress:
            progress("Extracting shared motion set from anm_resident (one time, ~15 s)…")
        res = anm.parse(fs.read("Anime/ANM_HI_JP.dat/anm_resident.lzs"))
        blocks = {b.id: b for b in res.blocks}
        for bid, b in blocks.items():  # cache all motion blocks at once
            with open(os.path.join(CACHE_DIR, f"motion_block_{bid}.pickle"), "wb") as f:
                pickle.dump(b, f)
        blk = blocks[block_id]
    _motion_cache[block_id] = blk
    return blk


def needs_motion_set(a: anm.AnmFile) -> bool:
    """Humanoid battle sprites (anm < 10000) keep only a few own animations and use the shared
    motion block; portraits / cut-ins (anm >= 10000) and monsters carry their own."""
    ids = [b.id for b in a.blocks]
    if any(i >= 10000 for i in ids):
        return False
    return sum(len(b.animations) for b in a.blocks) < 20 and len(a.textures) > 0


def preview_file(fs: GameFS, a: anm.AnmFile, progress=None) -> anm.AnmFile:
    """AnmFile to use for animation preview (binds the shared humanoid motions if needed)."""
    if needs_motion_set(a):
        try:
            blk = motion_block(fs, 1, progress)
            return anm.bind_motion_set(anm.AnmFile([blk], [], []), 0, a)
        except Exception:
            return a
    return a


def stand_height(fs: GameFS, a: anm.AnmFile) -> int:
    """how tall the sprite's standing drawing is in pixels (the visible part, not its cell): what a sprite sheet's
    drawings are scaled to"""
    try:
        v = preview_file(fs, a)
        info = next(x for x in anm.list_animations(v) if x["id"] == 1)
        img, _ = anm.render_items(v, anm.evaluate(v, info["index"], 0), 0)
        box = img.getchannel("A").point(lambda p: 255 if p > 40 else 0).getbbox()
        return (box[3] - box[1]) if box else 0
    except Exception:
        return 0


def companion(num: int) -> int:
    """anmNNNN0 <-> anmNNNN1 (the reduced copy that shares the same sheets & palettes)."""
    return num + 1 if num % 10 == 0 else num - 1 if num % 10 == 1 else None


def copy_images(src: anm.AnmFile, dst: anm.AnmFile) -> bool:
    """Copy texture pixels and palettes from src into dst if their layout matches."""
    if len(src.textures) != len(dst.textures):
        return False
    for s, d in zip(src.textures, dst.textures):
        if s.fmt != d.fmt:
            return False
    for i, (s, d) in enumerate(zip(src.textures, dst.textures)):
        d.width, d.height, d.data = s.width, s.height, s.data
        for b in dst.blocks:
            li = i - b.tex_base
            if 0 <= li < len(b.texture_infos):
                b.texture_infos[li].width, b.texture_infos[li].height = s.width, s.height
    n = min(len(src.palettes), len(dst.palettes))
    for i in range(n):
        dst.palettes[i].data = src.palettes[i].data
    for i in range(len(dst.palettes), len(src.palettes)):
        anm.add_palette(dst, anm.get_palette(src, i))
    return True


def free_sprite_numbers(fs: GameFS, start=9000, count=1):
    used = set(all_sprite_numbers(fs))
    out = []
    n = start - start % 10
    while len(out) < count:
        if n not in used and n + 1 not in used:
            out.append(n)
        n += 10
    return out
