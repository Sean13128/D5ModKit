"""The two track mergers ANIMALL used, kept in the worktree so this lane is reproducible.

They are prototypes: they retain D4 nodes, keys, controls and transforms and re-serialise into D5's
wider records.  They do not establish native binding, weapon, event or attachment compatibility.
"""
from __future__ import annotations

import copy

from d5lib import anm


def on_page(c, textures):
    """the cell's rectangle lies inside one of these pages"""
    return c.tex < len(textures) and c.x + c.w <= textures[c.tex].width and c.y + c.h <= textures[c.tex].height


def blank_off_page(cells, textures):
    """D4CELL1: zero the shared cells this body has no art for -> number blanked.

    D4's shared block (anm00001 block 0) indexes pages 0-16 of whatever body it is bound to; a 9/10-page
    D4 body has no art on pages 9-16 (nodes 31, 21, 1: 144 cells).  Left as they were, the cells dangle,
    and once the installer's banner_layout repacks the atlas onto more pages they draw unrelated art.
    D5's own humanoid block (anm_resident id 1) draws no such cell.  Same index kept, rectangle zeroed
    (a w=0 cell draws nothing: kit renderer, and D5's anm00002 ships zero cells on keys)."""
    n = 0
    for i, c in enumerate(cells):
        if c.w and c.h and not on_page(c, textures):
            cells[i] = anm.Cell(0, c.pal, c.unk2, c.flags, 0, 0, 0, 0, c.unk8)
            n += 1
    return n


def build(body, shared, *, bank_id):
    """Humanoid: the D4 shared block (anm00001 block 0) + the class body, own animations win."""
    if len(body.blocks) != 1 or not shared.blocks or not 0 <= bank_id <= 65535:
        raise ValueError('expected one body block, a shared block and a u16 bank id')
    out = copy.deepcopy(body)
    own = out.blocks[0]
    b = copy.deepcopy(shared.blocks[0])
    b.id = bank_id
    b.palette_infos = own.palette_infos
    b.texture_infos = own.texture_infos
    b.tex_base = b.pal_base = 0
    no, ko, ce, xo, po, co, pa = (len(b.nodes), len(b.keys), len(b.cells),
                                  len(b.transforms), len(b.pivots), len(b.colors), len(b.params))
    blank_off_page(b.cells, body.textures)
    for n in own.nodes:
        if n.first_key >= 0:
            n.first_key += ko
        if n.child >= 0:
            n.child += no
        if n.next >= 0:
            n.next += no
    for k in own.keys:
        if k.cell:
            k.cell += ce
        k.xform += xo
        k.color += co
        k.param += pa
    for x in own.transforms:
        x.pivot += po
    b.nodes.extend(own.nodes)
    b.keys.extend(own.keys)
    b.cells.extend(own.cells)
    b.transforms.extend(own.transforms)
    b.pivots.extend(own.pivots)
    b.colors.extend(own.colors)
    b.params.extend(own.params)
    own_ids = {a.id for a in own.animations}
    b.animations = [a for a in b.animations if a.id not in own_ids]
    b.animations.extend(anm.Animation(a.id, a.root + no) for a in own.animations)
    b.animations.sort(key=lambda a: a.id)
    b.fix_virtual_offsets()
    out.blocks = [b]
    return anm.parse(out.to_bytes())


def build_monster(body, *, bank_id):
    """Monster: the class carries its own animations; widen the records and keep the tracks."""
    if len(body.blocks) != 1 or not 0 <= bank_id <= 65535:
        raise ValueError('expected one body block and a u16 bank id')
    out = copy.deepcopy(body)
    b = out.blocks[0]
    b.id = bank_id
    b.fix_virtual_offsets()
    return anm.parse(out.to_bytes())


def disabled_view(a):
    """The kit evaluator's model of the initial disabled part bindings (node ids 21/31)."""
    a = copy.deepcopy(a)
    for b in a.blocks:
        for node in b.nodes:
            if node.id in (21, 31):
                for key in b.node_keys(node):
                    key.cell = 0
    return a
