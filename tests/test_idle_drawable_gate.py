"""NODRAW1: importcore.idle_drawable_gate fails a bank whose idle motions draw nothing (built in code, no game data)."""
import json

from d5lib import anm, importcore


def _bank(block_id, anim_ids, cell_w=8):
    f = anm.AnmFile([anm.AnmBlock(block_id)], [], [])
    anm.add_texture(f, 32, 32, indexed=True)
    f.textures[0].data = bytes([1]) * (32 * 32)                      # opaque palette index 1
    anm.set_palette(f, 0, [(0, 0, 0, 0), (200, 40, 40, 255)] + [(0, 0, 0, 0)] * 254)
    b = f.blocks[0]
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, cell_w, 8, 0)]
    b.nodes = [anm.Node(1, 0x100, 0, 0, 0, 0, 0, 1, -1, -1)]
    b.keys = [anm.Key(0, 0, 1, 0, 0, 0)]
    b.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0)]
    b.pivots = [anm.Pivot(0, 0)]
    b.colors = [anm.Color((128, 128, 128, 255) * 5)]
    b.animations = [anm.Animation(a, 0) for a in anim_ids]
    return f


def _mod(tmp_path, bank, sprite=16730):
    mod = tmp_path / "DRPG_Core_Test"
    (mod / "patches/db").mkdir(parents=True)
    (mod / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 743, "sprite_id": sprite}]}))
    d = mod / "files/Anime/ANM_HI_JP.dat"
    d.mkdir(parents=True)
    for n in (sprite, sprite + 1):
        (d / f"anm{n:05d}.lzs").write_bytes(bank.to_bytes())
    return mod


def test_drawing_bank_passes(tmp_path):
    assert importcore.idle_drawable_gate(_mod(tmp_path, _bank(16730, [0, 1001, 1007]))) == (True, "")


def test_missing_idle_motion_fails(tmp_path):
    ok, why = importcore.idle_drawable_gate(_mod(tmp_path, _bank(16730, [0, 1001])))
    assert not ok and "no animation 1007" in why


def test_empty_idle_frame_fails(tmp_path):
    ok, why = importcore.idle_drawable_gate(_mod(tmp_path, _bank(16730, [0, 1001, 1007], cell_w=0)))
    assert not ok and "motion 1001 draws no pixel" in why


def test_mod_without_its_own_bank_is_skipped(tmp_path):
    mod = tmp_path / "D4_Class_x"
    (mod / "patches/db").mkdir(parents=True)
    (mod / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 1, "sprite_id": 5}]}))
    assert importcore.idle_drawable_gate(mod) == (True, "")
