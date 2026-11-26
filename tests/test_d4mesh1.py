"""D4MESH1: D4 mesh nodes keep their stored vertices (rule D4-ANM-08)."""
import sys
from pathlib import Path

import pytest

from d5lib import anm, d4source

SOURCE = Path('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+')
needs_source = pytest.mark.skipif(not (SOURCE / 'Data' / 'DATA' / 'ANM_HI.dat').is_file(), reason='no D4 source copy')


def test_node_row_mesh_flag_moves_to_the_d5_mesh_word():
    row = (51, 0, 1, 0, 229, 13, -1, -1)
    old = d4source.d5_node(row)
    new = d4source.d5_node(row, mesh_nodes=True)
    assert (old.mesh, old.unk2) == (0, 1)                      # old path: flag left in unk2, drawn as a pivoted rectangle
    assert (new.mesh, new.unk2) == (1, 0)
    assert (new.first_key, new.num_keys, new.child, new.next) == (229, 13, -1, -1)
    plain = d4source.d5_node((7, 0x100, 0, 0, 3, 2, -1, 5), mesh_nodes=True)
    assert (plain.mesh, plain.unk2, plain.id, plain.flags) == (0, 0, 7, 0x100)


@needs_source
def test_mesh_option_draws_the_stored_vertices_of_death():
    data = d4source.D4Data(SOURCE, locate=lambda rel: SOURCE / rel)
    old, new = data.anm(2120), data.anm(2120, mesh_nodes=True)
    assert sum(n.mesh for n in old.blocks[0].nodes) == 0
    assert sum(n.mesh for n in new.blocks[0].nodes) == 8
    assert sum(n.unk2 for n in new.blocks[0].nodes) == 0
    mesh = {i for i, n in enumerate(new.blocks[0].nodes) if n.mesh}
    a = [it for it in anm.evaluate(old, ('id', 1051), 0, game=True) if it.node in mesh]
    b = [it for it in anm.evaluate(new, ('id', 1051), 0, game=True) if it.node in mesh]
    assert a and len(a) == len(b)
    # D4-PROOF (Unicorn): the old reading puts motion 1051's mesh quad one cell away from the game's
    assert max(abs(x.quad - y.quad).max() for x, y in zip(a, b)) > 50


@needs_source
def test_audit_source_side_reads_mesh_nodes_and_flags_the_old_bank():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import d4_motion_audit as audit
    src = audit.Source(SOURCE)
    assert sum(n.mesh for n in src.anm(2120).blocks[0].nodes) == 8
    # negative control: the same body read the old way (mesh 0) must differ from the source in motion 1051
    old = src.data.anm(2120)
    pa = audit.picture(src.anm(2120), 1051, 0, 0)
    pb = audit.picture(old, 1051, 0, 0)
    assert audit.diff_pct(pa, pb) > 1.0
