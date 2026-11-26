"""Offline D4-to-D5 ANM format experiment; never use for installation.

This preserves D4 records. It does not establish D5 gameplay compatibility,
attachment semantics, source clock rate, or D4-to-D5 action mappings.
"""
import copy

from d5lib import anm


def build(body, shared=None, *, bank_id):
    """Widen D4 node records while retaining the original body tracks.

    Shared motions are unsupported until their texture and attachment references
    are resolved. Multi-block bodies fail before producing bytes.
    """
    if len(body.blocks) != 1 or not 0 <= bank_id <= 65535:
        raise ValueError('expected one body block and a u16 bank id')
    out = copy.deepcopy(body)
    b = out.blocks[0]
    b.id = bank_id
    if shared is not None:
        raise ValueError('shared humanoid textures and attachments are not resolved')
    b.fix_virtual_offsets()
    raw = out.to_bytes()
    return anm.parse(raw)
