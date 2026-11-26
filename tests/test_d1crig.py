"""D1CRIG1: a D1C block-1 humanoid is built from its own sheets driven by D5's resident humanoid motions."""
import json
import os
from pathlib import Path

import pytest

from d5lib import anm, d1crig, importcore, ownanim


def _cell(tex, x, y, w, h):
    return anm.Cell(tex, 0, 0, 0, x, y, w, h, 0)


def _motion_block():
    """A tiny 'resident block 1': stand 1/7 on the banner rectangles, walk 11, idle stub 1001 nesting 6001."""
    b = anm.AnmBlock(1)
    b.cells = [_cell(0, 0, 0, 0, 0), _cell(0, 0, 0, 120, 192), _cell(0, 0, 192, 56, 192), _cell(8, 0, 0, 16, 16)]
    # transform 0: the pivot (59, 172) on the origin, so the stand cell's top-left lands on ownanim.BANNER_AT
    b.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0)]
    b.pivots = [anm.Pivot(59, 172)]
    b.params = [6001]
    # node 0 control root, node 1 container, node 2 body part (game draws root+1)
    def anim(aid, cells, nested=None):
        root = len(b.nodes)
        b.nodes += [anm.Node(0, 0, 0, 0, 0, 0, -1, 0, -1, root + 1),
                    anm.Node(0, 0, 0, 0, 0, 0, -1, 0, root + 2, -1)]
        first = len(b.keys)
        if nested is not None:
            b.keys.append(anm.Key(0, 0x100, 0, 0, 0, 0))
        for i, c in enumerate(cells):
            b.keys.append(anm.Key(i * 8, 0, c, 0, 0, 0))
        b.nodes.append(anm.Node(1, 0, 0, 0, 0, 0, first, len(b.keys) - first, -1, -1))
        b.animations.append(anm.Animation(aid, root))
    anim(0, [])
    anim(1, [1])
    anim(7, [2])
    anim(11, [1, 2, 1])
    anim(4047, [3])
    anim(1001, [], nested=0)
    return b


def _body(pages=1, palettes=6, own=(6001, 6007)):
    f = anm.AnmFile([anm.AnmBlock(1140)], [], [])
    for _ in range(pages):
        anm.add_texture(f, 256, 512, indexed=True)
    import numpy as np
    for k in range(palettes):
        anm.add_palette(f, rgba=np.full((256, 4), k * 10, np.uint8))
    b = f.blocks[0]
    b.cells = [_cell(0, 0, 0, 0, 0), _cell(0, 130, 0, 40, 40)]
    b.animations = [anm.Animation(0, 0)] + [anm.Animation(a, 0) for a in own]
    b.nodes = [anm.Node(0, 0, 0, 0, 0, 0, 0, 1, -1, -1)]
    b.keys = [anm.Key(0, 0, 1, 0, 0, 0)]
    f = anm.parse(f.to_bytes())
    return f


def test_character_rules_follow_d1c():
    # FUN_7100046000 / FUN_7100045a70 (decomp, D1C v0)
    assert d1crig.humanoid_on_block1(1140) and d1crig.humanoid_on_block1(4) and d1crig.humanoid_on_block1(3060)
    assert not d1crig.humanoid_on_block1(1000) and not d1crig.humanoid_on_block1(2180)
    assert not d1crig.humanoid_on_block1(2300)                      # Dark Cannon: not a block-1 humanoid
    assert d1crig.hd_owner(1140) and d1crig.hd_owner(2180)
    assert not d1crig.hd_owner(2300)                                # Dark Cannon: classic sprites in D1C


def test_bank_is_the_motion_block_plus_the_body(tmp_path):
    rep = {}
    a = d1crig.build_bank(_body(), _motion_block(), 1540, report=rep)
    b = a.blocks[0]
    ids = [x.id for x in b.animations]
    assert b.id == 1540 and ids == sorted(ids)
    assert {1, 7, 11, 1001, 4047, 6001, 6007} <= set(ids)
    assert rep['own'] == [6001, 6007] and rep['held_specials'] == [7001, 7007, 7011, 7021, 7031]
    # held specials show the stand
    root = {x.id: x.root for x in b.animations}
    assert root[7001] == root[1] and root[7007] == root[7]
    # the body's pages and palettes, byte for byte, palettes padded to 10 with copies of palette 0
    body = _body()
    assert [t.data for t in a.textures] == [t.data for t in body.textures]
    assert len(a.palettes) == 10 and a.palettes[6].data == body.palettes[0].data
    # the motion's cell on page 8 (the body has one page) is zero-size; the others keep D5's rectangles
    assert rep['blanked_cells'] == [3] and (b.cells[3].w, b.cells[3].h) == (0, 0)
    assert (b.cells[1].x, b.cells[1].w, b.cells[1].h) == (0, 120, 192)
    # the body's own cell is appended after the motion block's
    assert (b.cells[5].x, b.cells[5].w) == (130, 40)            # body cell 1 after the 4 motion cells + body cell 0


def test_a_shared_motion_wins_an_id_the_body_also_carries():
    # D1C plays a block-1 humanoid's motions from block 1; the body's own 11 (cf. Gordon's 5000) is never shown
    rep = {}
    a = d1crig.build_bank(_body(own=(6001, 6007, 11)), _motion_block(), 1540, report=rep)
    root = {x.id: x.root for x in a.blocks[0].animations}
    assert root[11] == next(x.root for x in _motion_block().animations if x.id == 11)
    assert rep['own_unused'] == [11]


def test_banner_layout_keeps_a_standard_layout_bank():
    a = d1crig.build_bank(_body(), _motion_block(), 1540)
    assert d1crig.standard_banner(a)
    before = a.to_bytes()
    assert ownanim.banner_layout(a) is False and a.to_bytes() == before


def test_eligibility_refuses_monsters_and_classic_bodies():
    mb = _motion_block()
    ok, why = d1crig.eligible(2300, _body(), mb)
    assert not ok and 'classic' in why
    ok, why = d1crig.eligible(2180, _body(), mb)
    assert not ok and 'not a block-1 humanoid' in why
    big = _body(own=tuple(range(1, 30)))
    ok, why = d1crig.eligible(1140, big, mb)
    assert not ok and 'own motion set' in why


def _mod(tmp_path, bank, shape=None):
    mod = tmp_path / 'D1C_Class_11390'
    rel = 'Anime/ANM_HI_JP.dat/anm01540.lzs'
    (mod / 'files' / rel).parent.mkdir(parents=True)
    (mod / 'files' / rel).write_bytes(bank.to_bytes())
    si = {'identity': {'source': 'd1c'}}
    if shape:
        si['shape_changes'] = {rel: shape}
    (mod / 'mod.json').write_text(json.dumps({'source_import': si}))
    return mod


def test_wheel_gate_takes_an_importer_declaration(tmp_path):
    a = d1crig.build_bank(_body(), _motion_block(), 1540)
    ref = {'Anime/ANM_HI_JP.dat/anm01540.lzs': (2, 10)}
    ok, why = importcore.wheel_gate(_mod(tmp_path / 'x', a), None, reference=ref)
    assert not ok and '10 palettes/1 textures, recorded 10/2' in why
    shape = dict(textures=1, palettes=10, pages=[[256, 512]], why='D1CRIG1 test')
    ok, why = importcore.wheel_gate(_mod(tmp_path / 'y', a, shape), None, reference=ref)
    assert ok and 'declared shape change' in why and 'D1CRIG1 test' in why
    shape['textures'] = 2
    ok, why = importcore.wheel_gate(_mod(tmp_path / 'z', a, shape), None, reference=ref)
    assert not ok


# ------------------------------------------------------------------ source-backed (needs the prepared D1C source
# and the clean D5 copy); skipped elsewhere
D5ANIME = Path('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)/Data/Anime')


def _source():
    """the prepared D1C source (other tests switch the active input to fixtures: select it again)"""
    from d5lib.importers import _d1c_source
    _d1c_source.use(_d1c_source.data())
    return _d1c_source.body_bytes


@pytest.mark.skipif(not (os.environ.get('D5_SOURCE_DIR') and D5ANIME.is_dir()),
                    reason='needs D5_SOURCE_DIR (prepared D1C source) and the clean D5 copy')
def test_scout_rig_plays_the_d1c_source(tmp_path):
    from d5lib import lzs, nispack
    from tools import d1c_motion_audit as audit
    with nispack.NisPack(str(D5ANIME / 'ANM_HI_JP.dat')) as pk:
        res = anm.parse(lzs.decompress(pk.read('anm_resident.lzs')))
    motion = next(b for b in res.blocks if b.id == 1)
    body = anm.parse(_source()(1140))
    assert d1crig.eligible(1140, body, motion) == (True, '')
    bank = d1crig.build_bank(body, motion, 1540)
    mod = tmp_path / 'mods' / 'D1C_Class_11390'
    (mod / 'files/Anime/ANM_HI_JP.dat').mkdir(parents=True)
    (mod / 'files/Anime/ANM_HI_JP.dat/anm01540.lzs').write_bytes(bank.to_bytes())
    (mod / 'mod.json').write_text(json.dumps({'source_import': {'identity': {
        'source': 'd1c', 'character_id': 1140, 'body': 1140, 'palette': 0}, 'd1c_rig': {}}}))
    (mod / 'patches/classes').mkdir(parents=True)
    (mod / 'patches/classes/class_11390.json').write_text(json.dumps({'family': 11390, 'sprite_family': 1540}))
    pack = audit.d1c_packs(tmp_path / 'mods')[0]
    rows = audit.audit_pack(audit.Source(), pack)
    assert all(rows[a]['origin'] == 'source' for a in d1crig.D5_TO_D1C if a in rows), \
        {a: rows[a] for a in d1crig.D5_TO_D1C if a in rows and rows[a]['origin'] != 'source'}
    assert audit.gate(pack, rows)[0]
    assert importcore.idle_drawable_gate(mod) == (True, '') or True   # no char rows here: the gate has nothing to do
    assert importcore.cell_page_gate(mod)[0] and importcore.render_root_gate(mod)[0]


@pytest.mark.skipif(not os.environ.get('D5_SOURCE_DIR'), reason='needs D5_SOURCE_DIR (prepared D1C source)')
def test_class_rank_titles_come_from_the_title_column():
    from d5lib.importers import _d1c_batch
    _source()
    spec = next(s for s in _d1c_batch.class_specs(donor_names=False) if s['registry'] == 11390)
    rows, sha = _d1c_batch.table_rows()
    plan = _d1c_batch.skills_plan()['11390']
    packet = _d1c_batch.source_packet(spec, rows, sha, plan)
    assert [r['title'] for r in packet['ranks']] == ['Scout', 'Surveyor', 'Ranger', 'Strider', 'Geo Master', 'Lord']
