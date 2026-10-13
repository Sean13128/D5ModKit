"""Effect models without a limit.

The game preloads EVERY effect model of EffectTableDataBase at start (0x14070eda0 -> 0x1404002c0) into a cache of
512 entries whose models live in the resource manager's slots 700 + cache index; the manager has 1100 slots, so the
401st effect model crashed the game at start (0x1402fb302, 2026-10-12).  The script command that shows an effect
(cmd_3c00 -> 0x14018d9f0) and the other lookups (0x1401a8a40, 0x1401a8320, 0x14008ada0) only use models already in
the cache.

With mods that add effect models the installer
  * patches the start-up preload to leave out every model a script shows (cmd_3c00 with a literal id) and every
    mod's model: those are loaded on demand (the rest -- models only the game's code asks for -- stay preloaded);
  * writes d5fx.dat next to the exe: those models' data, and per script event the models its call tree shows;
  * the runtime (d5lib/native/d5fx.inc.c) loads a model when a script starts (prefetch) or when a lookup misses it,
    into a free cache entry with a manager slot below 1100, and when none is free it releases the model no live
    model instance uses (instance +0x180 slot, +0x218 active) that was asked for longest ago.
So any number of effect models works; at most ~400 can be on screen at the same moment.

d5fx.dat: 'D5FX', u32 version 1, u32 n, n x (u32 id, u32 offset, u32 size)   sorted by id
          u32 m, m x (u32 event, u32 first, u32 count)                       sorted by event
          u32 k, k x u32 id                                                    the events' lists
          then the models' data (the archive member: YKCMP-compressed .obf)
"""
import struct

from . import exepatch, script
from .modsys import register_finalizer

FILE_NAME = "d5fx.dat"
GAME_PREFIX = "GAME/"
SECTION = b".d5fx"
PRELOAD_CALL_VA = 0x14070EDD8          # call 0x1404002c0 (cache, effect id) for every table row
PRELOAD_VA = 0x1404002C0
CMD_SHOW_EFFECT = 0x3C00
MAX_PREFETCH = 128                     # models listed per event (more are still loaded when shown)


def _call_bytes(site, target):
    return b"\xE8" + struct.pack("<i", target - (site + 5))


def preload_patch(exe: bytes, lazy_ids) -> bytes:
    """the start-up preload skips `lazy_ids` (they load on demand)"""
    ids = sorted({int(i) for i in lazy_ids})
    nl = "\n"
    src = nl.join([
        "    lea r10, [rip + lazy_ids]",
        f"    mov r11d, {len(ids)}",
        "scan:",
        "    test r11d, r11d",
        "    je preload",
        "    cmp edx, dword ptr [r10]",
        "    je skip",
        "    add r10, 4",
        "    dec r11d",
        "    jmp scan",
        "skip:",
        "    xor eax, eax",
        "    ret",
        "preload:",
        f"    jmp {PRELOAD_VA:#x}",
        "    .align 4",
        "lazy_ids:",
        "    .long " + ", ".join(map(str, ids or [0])),
    ])
    return exepatch.add_hook_section(exe, SECTION, [(PRELOAD_CALL_VA, _call_bytes(PRELOAD_CALL_VA, PRELOAD_VA), src,
                                                     0xE8)])


def script_effects(sf):
    """({event id: effect ids it shows directly}, {event id: events it starts})"""
    direct, refs = {}, sf.references()
    for e in sf.events:
        ids = []
        for i in e.code:
            if i.cid == CMD_SHOW_EFFECT and len(i.args) > 1 and isinstance(i.args[1], int) and i.args[1] > 0:
                ids.append(int(i.args[1]))
        if ids:
            direct[e.id] = ids
    return direct, refs


def closures(direct, refs, cap=MAX_PREFETCH):
    """event id -> effect ids its whole call tree shows (first come first), for events with any"""
    memo = {}

    def walk(eid, stack):
        if eid in memo:
            return memo[eid]
        if eid in stack:
            return []
        stack.add(eid)
        out, seen = [], set()
        for x in direct.get(eid, []):
            if x not in seen:
                seen.add(x)
                out.append(x)
        for child in refs.get(eid, []):
            for x in walk(child, stack):
                if x not in seen and len(out) < cap:
                    seen.add(x)
                    out.append(x)
        stack.discard(eid)
        memo[eid] = out[:cap]
        return memo[eid]

    for eid in set(direct) | set(refs):
        walk(eid, set())
    return {e: v for e, v in memo.items() if v}


def build_file(models, lists):
    """models: {id: bytes}, lists: {event: [ids]} -> d5fx.dat"""
    ids = sorted(models)
    events = sorted(lists)
    flat = []
    heads = []
    for e in events:
        heads.append((e, len(flat), len(lists[e])))
        flat.extend(lists[e])
    head_len = 8 + 4 + 12 * len(ids) + 4 + 12 * len(events) + 4 + 4 * len(flat)
    out = bytearray(b"D5FX" + struct.pack("<I", 1) + struct.pack("<I", len(ids)))
    off = head_len
    blobs = []
    for i in ids:
        d = models[i]
        out += struct.pack("<III", i, off, len(d))
        blobs.append(d)
        off += len(d)
    out += struct.pack("<I", len(events))
    for e, first, n in heads:
        out += struct.pack("<III", e, first, n)
    out += struct.pack("<I", len(flat))
    out += struct.pack(f"<{len(flat)}I", *flat)
    assert len(out) == head_len
    for b in blobs:
        out += b
    return bytes(out)


def _finalize(ctx):
    from . import database, skills
    from .runtime import EXE_FILE
    table = database.load_table("EffectTableDataBase.dat", ctx.get(skills.EFFECT_TABLE))
    vanilla = database.load_table("EffectTableDataBase.dat", ctx.fs.read(skills.EFFECT_TABLE))
    all_ids = {int(r["effect_id"]) for r in table.rows}
    van_ids = {int(r["effect_id"]) for r in vanilla.rows}
    mod_ids = all_ids - van_ids
    if not mod_ids:
        return
    sf = ctx.parsed(skills.SCRIPT, script.ScriptFile.from_bytes)
    direct, refs = script_effects(sf)
    shown = {x for v in direct.values() for x in v}
    members = skills.effect_members(ctx.fs.read)            # the game's models
    lazy = {}
    for i in sorted((shown & all_ids) | mod_ids):
        vp = f"{skills.EFFECT_DAT}/{skills.effect_name(i)}"
        d = ctx.get(vp) if vp.lower() in ctx.outputs else members.get(skills.effect_name(i))   # a mod's own first
        if d is not None:
            lazy[i] = d
    lists = {e: [x for x in v if x in lazy] for e, v in closures(direct, refs).items()}
    lists = {e: v for e, v in lists.items() if v}
    ctx.put(GAME_PREFIX + FILE_NAME, build_file(lazy, lists))
    ctx.put(EXE_FILE, preload_patch(ctx.get(EXE_FILE), lazy))
    ctx.needs_runtime = True
    resident = len(all_ids) - len(lazy)
    ctx.log(f"  effect models: {len(all_ids)} ({len(mod_ids)} from mods); {len(lazy)} load when shown, "
            f"{resident} stay preloaded ({FILE_NAME}, {len(lists)} script event(s) prefetch theirs)")


register_finalizer(_finalize)
