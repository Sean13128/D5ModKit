"""Experimental D4 humanoid track merge for offline examination only.

Named nodes have separate native bindings; this does not establish that those
bindings, events, or attachments are compatible with D5. Never ship its output.
"""
import copy

from d5lib import anm


def build(body, shared, *, bank_id):
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
    # Own animations take precedence, as they describe class-specific actions.
    own_ids = {a.id for a in own.animations}
    b.animations = [a for a in b.animations if a.id not in own_ids]
    b.animations.extend(anm.Animation(a.id, a.root + no) for a in own.animations)
    b.animations.sort(key=lambda a: a.id)
    b.fix_virtual_offsets()
    out.blocks = [b]
    return anm.parse(out.to_bytes())
