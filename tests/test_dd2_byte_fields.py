"""DD2 stores a key's and a cell's two-byte fields as separate bytes, so D5 must see them swapped."""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import anm, dd2source
from d5lib.importers._dd2_baseline import decode_dd2

ROOT, LAYER = 0, 1


def _bank(*, key_flags=0x0100, key_cell=1, param=0, cell=(0, 0, 0x0002, 0x0100, 0, 0, 1, 1, 0x3596), mesh=1, params=(1,), word=0):
    """One big-endian DD2 block: animation 1 = a control root followed by one layer node."""
    tables = [
        struct.pack('>HH', 1, ROOT),
        struct.pack('>HHHHhHhh', 0, 0, 0, 0, 0, 1, -1, LAYER)
        + struct.pack('>HHHHhHhh', 0, word, 0, mesh, 1, 1, -1, -1),
        struct.pack('>6H', 0, 0x0500, 0, 0, 0, 0) + struct.pack('>6H', 0, key_flags, key_cell, 0, 0, param),
        b'', b'',
        struct.pack('>9H', *([0] * 9)) + struct.pack('>9H', *cell),
        struct.pack('>hhHHhhi', 0, 0, 0, 0, 100, 100, 0),
        struct.pack('>hh', 0, 0),
        bytes(20),
        b''.join(struct.pack('>i', p) for p in params),
    ]
    counts = [len(t) // s for t, s in zip(tables, anm.TABLE_SIZES)]
    counts[1] = 2
    offsets, at = [], 0x44
    for table in tables:
        offsets.append(at)
        at += len(table)
    size = (at + 15) & ~15
    block = struct.pack('>IHH', size, 7, counts[0]) + struct.pack('>10H', *(counts[1:] + [0]))
    block += struct.pack('>10I', *offsets) + b''.join(tables)
    block += bytes(size - len(block))
    return struct.pack('>5I', 32 + size - 16, 0, 0, 0, 1) + bytes(12) + block


def test_key_flag_bytes_reach_d5_order():
    bank = decode_dd2(_bank())
    keys = bank.blocks[0].keys
    assert keys[0].flags == 5, 'control code belongs in the low byte'
    assert keys[1].flags == 1, 'a D2 interpolate key must interpolate in D5'
    assert decode_dd2(_bank(key_flags=0x0001)).blocks[0].keys[1].flags == 0x100, 'a D2 attach key must attach in D5'


def test_cell_bytes_reach_d5_order():
    cell = decode_dd2(_bank()).blocks[0].cells[1]
    assert cell.unk8 & 0xFF == 0x35, 'depth group is the cell byte at +16'
    assert cell.unk2 == 0x0200, 'D2 word 0x0002 is blend 2: byte +5, the high byte in D5'
    assert cell.flags == 0x0001, 'D2 word 0x0100 is flip X: byte +6, the low byte in D5'


def test_mesh_mode_survives():
    nodes = decode_dd2(_bank()).blocks[0].nodes
    assert (nodes[0].mesh, nodes[1].mesh) == (0, 1)
    assert nodes[1].unk3 == 0


def test_node_word_reaches_d5_bitfield():
    """DD2DRAW1: D2 word 0x0001 is draw mode 1.  Copied raw, D5 reads asset id 0x10000 and skips the node's cell."""
    node = lambda word: decode_dd2(_bank(word=word)).blocks[0].nodes[1]
    n = node(0x0001)
    assert (n.id, n.flags) == (0, 0x1000), 'mode 1 is D5 bit 28; bits 0-23 stay 0, so the draw gate passes'
    n = node(0x6311)
    assert (n.id, n.flags) == (99, 0x1100), 'named node 99 with binding and mode, as D5 anm02070 stores it'
    assert (node(0x0110).id, node(0x0110).flags) == (1, 0x100), 'the D2 body part is D5 binding 1'


def test_attachment_without_a_target_stays_inert():
    bank = decode_dd2(_bank(key_flags=0x0001, key_cell=0, params=(6001,)))
    assert dd2source.drop_unresolved_attachments(bank) == 1
    assert bank.blocks[0].keys[1].flags == 0
    assert dd2source.drop_unresolved_attachments(bank) == 0


def test_attachment_with_a_target_is_kept():
    bank = decode_dd2(_bank(key_flags=0x0001, key_cell=0, params=(1,)))
    assert dd2source.drop_unresolved_attachments(bank) == 0
    assert bank.blocks[0].keys[1].flags == 0x100


def test_pose_table_keeps_source_facing(tmp_path):
    from d5lib.importers._dd2_baseline import source_facing_table
    table = tmp_path / 'poses.json'
    table.write_text(json.dumps(dict(format='f', common_sha256='s', teachers=[10], poses={
        'back/stand': dict(rectangle=8, flip_x=True, quarter_turns=1),
        'front/stand': dict(rectangle=3, flip_x=False, quarter_turns=0)})))
    out = json.loads(source_facing_table(table, tmp_path / 'scratch').read_text())
    assert out['poses']['back/stand'] == dict(rectangle=8, flip_x=False, quarter_turns=1), 'only the flip changes'
    assert out['poses']['front/stand']['flip_x'] is False
    assert (out['format'], out['common_sha256'], out['teachers']) == ('f', 's', [10])
    assert json.loads(table.read_text())['poses']['back/stand']['flip_x'] is True, 'the pinned table stays as it was'


def test_special_rows_used_only_when_prepared():
    from d5lib import ownanim
    assert ownanim.special_rows({('stand', 'front'): []}) == {}
    rows = ownanim.special_rows({('special', 'front'): [], ('special2', 'front'): []})
    assert rows == {7001: 'special', 7011: 'special2'}, 'front-only source poses map to their own ids'
    assert ownanim.special_rows({('special', 'back'): []}) == {7007: 'special'}


def test_special_poses_join_the_prepared_front_bundle(tmp_path):
    from PIL import Image
    from d5lib.importers._dd2_baseline import add_special_poses
    folder = tmp_path / 'prepared'
    (folder / 'front').mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps(dict(bundles=[dict(label='front', sprites=[])])))
    frames = {7001: ([Image.new('RGBA', (20, 30), (255, 0, 0, 255))] * 2, (10, 30)), 7011: ([], (0, 0))}
    assert add_special_poses(folder, frames) == {7001: 2}
    manifest = json.loads((folder / 'manifest.json').read_text())
    sprites = manifest['bundles'][0]['sprites']
    assert [s['name'] for s in sprites] == ['special01', 'special02']
    assert sprites[0]['pivot'] == {'x': 0.5, 'y': 0.0} and (folder / sprites[0]['png']).is_file()


def test_donor_slots_never_reuse_a_donor_node_index():
    """DD2ROOT1: the donor's 1011 root index (here 1) is a layer of the import's own idle 1001."""
    from d5lib.importers._dd2_baseline import add_donor_slots
    node = lambda child=-1, nxt=-1: anm.Node(0, 0, 0, 0, 0, 0, -1, 0, child, nxt)
    block = anm.AnmBlock(7, animations=[anm.Animation(1001, 0)], nodes=[node(child=1), node(), node()])
    donor = anm.AnmBlock(2020, animations=[anm.Animation(1001, 0), anm.Animation(1011, 1)], nodes=[node(), node()])
    add_donor_slots(block, donor)
    slot = next(a for a in block.animations if a.id == 8011)
    idle = {i for i, _, _ in block.walk(0)}
    assert slot.root not in idle, 'the 80xx slot must not root inside the idle'
    assert block.node_keys(block.nodes[slot.root]) == [], 'an empty slot gives _fixed_passes no key to rewrite'


def test_dd2read1_images_stay_whole_until_d5_fit():
    """DD2READ1: decode_dd2 keeps a 256x4 palette and refuses nothing; to_d5_images fits D5's shapes."""
    from d5lib.importers._dd2_baseline import to_d5_images
    bank = decode_dd2(_bank())
    bank.palettes.append(anm.Image8(bytes([0, 1, 1, 1]), 256, 4, 1, bytes(range(256)) * 16))
    assert len(bank.palettes[0].data) == 4096
    to_d5_images(bank)
    pal = bank.palettes[0]
    assert (pal.width, pal.height, pal.data) == (256, 1, (bytes(range(256)) * 16)[:1024])
    bank.textures.append(anm.Image8(bytes([4, 1, 1, 1]), 4, 4, 1, bytes(16)))
    try:
        to_d5_images(bank)
    except ValueError as e:
        assert 'DXT5' in str(e)
    else:
        raise AssertionError('a DXT5 sheet has no D5 form')
