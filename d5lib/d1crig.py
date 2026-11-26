"""D1C humanoid source rig: the body's own sheets driven by D5's own humanoid motions (D1CRIG1, 2026-11-23).

Disgaea 1 Complete draws an HD humanoid with D5's ANM module: the body block supplies textures, palettes and its
own idle 6001/6007; every other motion is the game's shared block 1 bound to the body (binding key 1).  That block
is D5's ``anm_resident`` block 1 renumbered: 124 of its cell rectangles are D5's, and 93 of its 105 motions equal a
D5 resident motion key for key (Research/import-checklist/scout-1140/D1C-RENDER-PIPELINE.md, D1CRIG1-REPORT.md).
So a D1C humanoid body is a D5 humanoid body: D5's resident motions draw it exactly as D1C does.

This module builds that bank, instead of composing whole-figure pictures onto a donor's tracks (``d1cart.poses`` +
``ownanim.build``, the flattened path that holds or slides one standing picture for most motions):

* block = a copy of D5's resident humanoid block 1 (all 135 motions, every key, cell, transform and weapon node
  unchanged) + the body's own animations (6001/6007 idle, 7001.. specials when the body has them), ids as in D5;
* textures and palettes = the body's own, byte for byte (8-bit indexed, no compositing, no re-quantising, no
  resampling); palettes padded to ``PALETTES`` with copies of palette 0 (the shape every D1C pack has today);
* special poses the body does not carry (7001/7007/7011/7021/7031: D5 scripts play motion 150 -> 7001, 151 -> 7011)
  are the plain stand (resident 1 / 7), disclosed as held;
* resident cells on a texture page the body does not have (D5 cell 124 on page 8, used by 4047 at one key) are made
  zero-size so no key draws from a missing page (``importcore.cell_page_gate``); nothing else is drawn differently.

The merge itself is ANIMALL2's D4 humanoid merger (``tools/animall2_tracks.build`` with D4CELL1's off-page rule),
reused with D5's block in place of D4's; its monster twin ``build_monster`` is the same route for a D1C monster
body, which already carries its own D5-numbered motion set (not used here: D1CRIG1 covers block-1 humanoids).

The bank is registered as an own-animation sprite like every kit sprite (``outfits.json`` ``own_sprites``), so the
game plays these copied motions from the bank itself (exe hook 0x14014d354), the same path the installed D1C packs
already use.  ``build_bank`` needs no game install: the caller passes D5's resident block 1 and the body file.
"""
from __future__ import annotations

import copy

from . import anm

PALETTES = 10
# D5 resident block-1 motion id -> the D1C shared block-1 motion that is the same motion key for key (cell rectangles,
# key times, transforms; stubs compared by what they show).  Measured 2026-11-23 on body 1140 (tools/d1c_motion_audit.py
# --twins re-derives it).  D5 ids not listed have no D1C twin: D1C's logic never plays them, D5's does, and on a rig
# bank they draw the body's own pictures at D5's cells.  D1C-only ids (1071/1077, 2071/2077, 2131/2137, 2151/2157,
# 2171-2187) are not reachable from D5's logic and are not shipped.
D5_TO_D1C = {0: 0, 1: 1, 7: 7, 11: 11, 17: 17, 21: 21, 27: 27, 101: 1, 107: 7, 1001: 1001, 1007: 1007,
             1011: 1011, 1017: 1017, 1021: 1021, 1027: 1027, 1031: 1031, 1037: 1037, 1041: 1041, 1047: 1047,
             1051: 1051, 1057: 1057, 1061: 1061, 1067: 1067, 1101: 1091, 1107: 1097, 1111: 1091, 1117: 1097,
             1131: 2671, 1137: 2677, 2001: 1501, 2007: 1507, 2011: 2521, 2017: 2527, 2021: 2531, 2027: 2537,
             2031: 2541, 2037: 2547, 2041: 2551, 2047: 2557, 2051: 2571, 2057: 2577, 3001: 2511, 3007: 2517,
             3011: 2661, 3017: 2567, 3021: 2561, 3031: 2641, 3037: 2647, 4001: 1601, 4007: 1607, 4021: 2111,
             4027: 2107, 4031: 2141, 4037: 2147, 4041: 2161, 4047: 2167, 4051: 2101, 5000: 5000}
SPECIALS = ((7001, 1), (7007, 7), (7011, 1), (7021, 1), (7031, 1))   # id, the stand it holds when the body lacks it
# D5 resident block-1 cells a D1C humanoid body may leave empty: 3 (empty in D1C's own block-1 motions too),
# 105-108 (used only by D5 4007), 124 (page 8, absent), 1 (an 8x8 marker, empty on several bodies).
ALLOWED_EMPTY = frozenset({1, 3, 105, 106, 107, 108, 124})
MAX_OWN_ANIMATIONS = 20          # a body with more carries its own motion set (a D1C monster), not the shared one


class RigError(ValueError):
    pass


def humanoid_on_block1(character_id: int) -> bool:
    """D1C ``FUN_7100046000``: the character ids D1C draws as an HD humanoid on shared block 1."""
    p = int(character_id)
    u = lambda x: x & 0xffffffff                                         # noqa: E731 - the decomp's unsigned compares
    if u(p - 1) < 9:
        return True
    if 1 < u(p - 1000):
        if 999 < u(p - 1000) and p not in (0x96a, 0xa8c) and 8 < u(p - 0xb5b):
            if p < 0xc4e:
                if p not in (0xb61, 0xbf4):
                    return False
            elif ((0x1e < u(p - 0xc4e) or not (1 << (u(p - 0xc4e) & 0x1f)) & 0x40000401)
                  and p not in (0xdac, 0x15d6)):
                return False
        return True
    return False


def hd_owner(character_id: int) -> bool:
    """D1C ``FUN_7100045a70``: True when the character is drawn by the HD ANM owner (else classic sprites)."""
    p = int(character_id)
    u = lambda x: x & 0xffffffff                                         # noqa: E731 - the decomp's unsigned compares
    if not 8 < u(p - 1):
        return True
    if p in (100, 120, 200, 997):
        return True
    if 0xd8 < u(p - 2000) and 999 < u(p - 1000) and (p & ~1) != 0x3e6:
        if (p & ~1) == 0x8fc:
            return False
        if 0xb4 < u(p - 3000) and p != 0xb66 and 400 < u(p - 0x960) and 0x10 < u(p - 0xb54):
            if p < 0x899:
                if p < 0x34 and (1 << (p & 0x3f)) & 0x8020080200800:
                    return True
            elif p < 0xb61:
                if p in (0x899, 0x8ad, 0x9c5):
                    return True
            elif p in (0xb61, 0xc76, 0xdac):
                return True
            c1 = 0xd < u(p - 0x1390) and 5 < u(p - 0x138a) and p != 5000 and 0xd < u(p - 4000)
            c2 = 0x13 < u(p - 0x139e) or not (0x8003f >> (u(p - 0x139e) & 0x1f)) & 1
            c3 = 4 < u(p - 0x1519) and p != 0x150e and 7 < u(p - 0x14b5)
            c4 = 0xb < u(p - 0x13ed)
            c5 = (9 < u(p - 0x1451) and p not in (0x157d, 0x15d6) and 0x11 < u(p - 0x1645)
                  and 1 < u(p - 0x16a9))
            c6 = p not in (0x1771, 0x19c9, 0x1a2d, 0x1f41, 0x26ad) and 0xc < u(p - 0x1b59)
            if c1 and c2 and c3 and c4 and c5 and c6:
                return False
    return True


def empty_cells(body: anm.AnmFile, motion_block: anm.AnmBlock):
    """Indices of the motion block's drawn cells that have no pixel on this body's sheets."""
    out = []
    for i, c in enumerate(motion_block.cells):
        if i == 0 or not c.w or not c.h:
            continue
        if c.tex >= len(body.textures):
            out.append(i)
            continue
        idx = anm.texture_indices(body, c.tex)
        if c.y + c.h > idx.shape[0] or c.x + c.w > idx.shape[1] or not idx[c.y:c.y + c.h, c.x:c.x + c.w].any():
            out.append(i)
    return out


def eligible(character_id: int, body: anm.AnmFile, motion_block: anm.AnmBlock):
    """(True, '') when this D1C character is a humanoid D1C draws on shared block 1 and its body fills D5's
    humanoid sheet layout; else (False, why)."""
    if not hd_owner(character_id):
        return False, f'character {character_id} is drawn with classic sprites in D1C (FUN_7100045a70 = 0)'
    if not humanoid_on_block1(character_id):
        return False, f'character {character_id} is not a block-1 humanoid in D1C (FUN_7100046000 = 0)'
    if len(body.blocks) != 1:
        return False, 'body file is not one block'
    if len(body.blocks[0].animations) > MAX_OWN_ANIMATIONS:
        return False, 'body carries its own motion set'
    if not all(t.indexed for t in body.textures):
        return False, 'body has non-indexed pages'
    missing = sorted(set(empty_cells(body, motion_block)) - ALLOWED_EMPTY)
    if missing:
        return False, f'body leaves D5 humanoid cells empty: {missing[:12]}'
    return True, ''


def build_bank(body: anm.AnmFile, motion_block: anm.AnmBlock, sprite_id: int, palettes: int = PALETTES,
               report: dict | None = None) -> anm.AnmFile:
    """The D1C humanoid rig bank for ``sprite_id`` (see the module docstring).  ``body``: the D1C body block as a
    one-block AnmFile; ``motion_block``: D5 ``anm_resident`` block 1 (id 1).  Raises RigError when the body is not
    one indexed block."""
    if len(body.blocks) != 1 or not body.textures or not all(t.indexed for t in body.textures):
        raise RigError('the body must be one block of 8-bit indexed pages')
    if motion_block.id != 1:
        raise RigError(f'motion block id {motion_block.id} is not the resident humanoid block 1')
    # The merge is ANIMALL2's D4 humanoid merger (tools/animall2_tracks.build: shared block + the body's own
    # animations, own ids win, the body's cells appended after the shared ones, shared cells on a page the body
    # lacks zeroed by D4CELL1's blank_off_page); D1C needs only D5's block in place of D4's.
    from tools import animall2_tracks
    merged = animall2_tracks.build(body, anm.AnmFile([copy.deepcopy(motion_block)], [], []), bank_id=int(sprite_id))
    b = merged.blocks[0]
    shared_ids = {a.id for a in motion_block.animations}
    own_ids = [a.id for a in body.blocks[0].animations if a.id not in shared_ids]
    # ANIMALL2 lets the body's own animation win an id both carry (D4).  D1C plays a humanoid's motions from block 1
    # (the body block is only bound to key 1), so a body's own 5000/5001 (Gordon 40, Dark Flonne 30) is never the
    # one D1C shows for that id: the shared motion wins here (its nodes are unchanged at the front of the table).
    shared_root = {a.id: a.root for a in motion_block.animations}
    shadowed = []
    for a in b.animations:
        if a.id and a.id in shared_root and a.root != shared_root[a.id]:
            a.root = shared_root[a.id]
            shadowed.append(a.id)
    blanked = [i for i, (c, m) in enumerate(zip(b.cells, motion_block.cells)) if (c.w, c.h) != (m.w, m.h)]
    ids = {a.id for a in b.animations}
    held = []
    for aid, stand in SPECIALS:
        if aid not in ids:
            root = next(a.root for a in b.animations if a.id == stand)
            b.animations.append(anm.Animation(aid, root))
            held.append(aid)
    b.animations.sort(key=lambda a: a.id)
    textures = [copy.deepcopy(t) for t in body.textures]
    pals = [copy.deepcopy(p) for p in body.palettes]
    infos = [copy.deepcopy(p) for p in body.blocks[0].palette_infos]
    if not pals or len(infos) != len(pals):
        raise RigError('body palettes and palette rows disagree')
    while len(pals) < palettes:
        pals.append(copy.deepcopy(pals[0]))
        infos.append(copy.deepcopy(infos[0]))
    b.palette_infos = infos[:max(palettes, len(body.palettes))]
    b.texture_infos = [copy.deepcopy(t) for t in body.blocks[0].texture_infos]
    out = anm.AnmFile([b], textures, pals[:len(b.palette_infos)])
    b.fix_virtual_offsets()
    out = anm.parse(out.to_bytes())          # recompute offsets; proves the bank serialises
    if report is not None:
        report.update(sprite=int(sprite_id), motions=len(motion_block.animations), own=own_ids, own_unused=shadowed,
                      held_specials=held, blanked_cells=blanked, pages=[(t.width, t.height) for t in textures],
                      source_palettes=len(body.palettes), palettes=len(out.palettes),
                      animations=len(out.blocks[0].animations))
    return out


def standard_banner(a: anm.AnmFile) -> bool:
    """True when the bank's own stand (animation 1 at its first key) draws exactly what the Quest Shop's banner
    draws with the shared motion (texture-0 rectangles ownanim.BANNER_BODY / BANNER_BEHIND at the same place): a
    rig bank in D5's standard sheet layout, which ``ownanim.banner_layout`` must leave as it is."""
    from . import ownanim
    if len(a.blocks) != 1 or not anm.has_animation(a, 1):
        return False
    want = {(0,) + tuple(ownanim.BANNER_BODY), (0,) + tuple(ownanim.BANNER_BEHIND)}
    got = set()
    for it in anm.evaluate(a, ('id', 1), 0):
        c = it.cell
        if not c.w or not c.h:
            continue
        got.add((c.tex, c.x, c.y, c.w, c.h))
        x0, y0 = float(it.quad[:, 0].min()), float(it.quad[:, 1].min())
        if (c.tex, c.x, c.y, c.w, c.h) == (0,) + tuple(ownanim.BANNER_BODY) and (round(x0), round(y0)) != tuple(ownanim.BANNER_AT):
            return False
    return (0,) + tuple(ownanim.BANNER_BODY) in got and got <= want
