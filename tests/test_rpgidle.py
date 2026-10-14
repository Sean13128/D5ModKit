import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from d5lib import anm, rpgclips, rpgidle


def fixture(folder):
    palette = np.zeros((256, 4), np.uint8)
    palette[1] = (190, 40, 30, 255)
    palette[2] = (220, 190, 50, 255)
    texture = np.zeros((64, 64), np.uint8)
    images = []
    cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0)]
    for pose in range(5):
        indices = np.zeros((32, 16), np.uint8)
        indices[10:26, 5:11] = 1
        indices[6 + pose : 9 + pose, 1:7] = 1
        indices[26:29, 3:7] = 2
        indices[26:29, 10:14] = 2
        images.append(Image.fromarray(palette[indices], "RGBA"))
        if pose < 4:
            x, y = (pose % 4) * 16, 0
            texture[y : y + 32, x : x + 16] = indices
            cells.append(anm.Cell(0, 0, 0, 0, x, y, 16, 32, 0))
    block = anm.AnmBlock(10000)
    block.texture_infos = [anm.TextureInfo(0, 64, 64, 8, 16, 16, 0)]
    block.palette_infos = [anm.PaletteInfo(0, 256, 0)]
    block.cells = cells
    block.pivots = [anm.Pivot(0, 0)]
    block.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0)]
    block.colors = [anm.Color((128, 128, 128, 255) * 5)]
    block.params = [0]

    def node(name, keys, child=-1, next_node=-1):
        start = len(block.keys) if keys else -1
        block.keys.extend(keys)
        block.nodes.append(
            anm.Node(name, 0, 0, 0, 0, 0, start, len(keys), child, next_node)
        )

    for aid in (6001, 6007):
        base = len(block.nodes)
        block.animations.append(anm.Animation(aid, base))
        node(
            0,
            [anm.Key(0, 1, 0, 0, 0, 0), anm.Key(31, 2, 0, 0, 0, 0)],
            next_node=base + 1,
        )
        node(0, [], child=base + 2)
        # Deliberately shuffled donor, four distinct pictures, missing source fifth.
        node(
            0,
            [anm.Key(t, 0, c, 0, 0, 0) for t, c in zip((0, 8, 16, 24), (1, 4, 2, 3))],
            next_node=base + 3,
        )
        node(111, [anm.Key(0, 256, 1, 0, 0, 0), anm.Key(16, 0, 2, 0, 0, 0)])
    base = len(block.nodes)
    block.animations.append(anm.Animation(21, base))
    node(0, [anm.Key(0, 5, 0, 0, 0, 0)], next_node=base + 1)
    node(0, [anm.Key(0, 0, 1, 0, 0, 0)])
    sprite = anm.AnmFile(
        [block],
        [anm.Image8(bytes((9, 1, 1, 1)), 64, 64, 1, texture.tobytes())],
        [
            anm.Image8(
                bytes((0, 1, 1, 1)), 256, 1, 1, anm._rgba_to_argb(palette).tobytes()
            )
        ],
    )
    facings = {}
    for view in ("front", "back"):
        switches = []
        for i, image in enumerate(images):
            path = folder / f"{view}_wait{i + 1}.png"
            image.save(path)
            switches.append(
                {"ticks60": i * 10, "sprite_name": f"wait{i + 1}", "png": str(path)}
            )
        switches.append(dict(switches[0], ticks60=50))
        facings[view] = {"duration_ticks60": 51, "switches": switches}
    return sprite, {"facings": facings}


class IdleTests(unittest.TestCase):
    def test_missing_pose_clock_and_equipment(self):
        with tempfile.TemporaryDirectory() as temporary:
            sprite, unit = fixture(Path(temporary))
            original = copy.deepcopy(sprite)
            repaired, audit = rpgidle.repair_sprite(sprite, unit)
            self.assertEqual(sprite, original)
            self.assertEqual([r["source_loop_ticks"] for r in audit], [51, 51])
            self.assertTrue(all(r["synthesized_frames"] == ["wait5"] for r in audit))
            block = repaired.blocks[0]
            for aid in (6001, 6007):
                anim = next(a for a in block.animations if a.id == aid)
                self.assertEqual(anm.animation_info(block, anim)["loop"], (0, 51))
                body = next(
                    i
                    for i, _, _ in block.walk(anim.root)
                    if block.nodes[i].id == 0
                    and any(k.cell for k in block.node_keys(block.nodes[i]))
                )
                keys = block.node_keys(block.nodes[body])
                self.assertEqual([k.time for k in keys], [0, 10, 20, 30, 40, 50])
                self.assertEqual(len({k.cell for k in keys}), 5)
                attachment = next(
                    i for i, _, _ in block.walk(anim.root) if block.nodes[i].id == 111
                )
                attached = block.node_keys(block.nodes[attachment])
                self.assertEqual([k.time for k in attached], [0, 10, 20, 30, 40, 50])
                self.assertEqual(attached[0].flags, 256)
            self.assertEqual(
                anm.render_frame(sprite, ("id", 21)).tobytes(),
                anm.render_frame(repaired, ("id", 21)).tobytes(),
            )
            self.assertEqual(
                anm.load(repaired.to_bytes()).blocks[0].nodes, repaired.blocks[0].nodes
            )

    def test_small_anonymous_overlay_does_not_replace_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            sprite, unit = fixture(Path(temporary))
            block = sprite.blocks[0]
            cell = len(block.cells)
            block.cells.append(anm.Cell(0, 0, 0, 0, 5, 12, 2, 2, 0))
            for animation in block.animations[:2]:
                body, parent = rpgidle.body_node(block, animation)
                attachment = block.nodes[body].next
                helper = len(block.nodes)
                first = len(block.keys)
                block.keys.append(anm.Key(0, 0, cell, 0, 0, 0))
                block.nodes.append(anm.Node(0, 0, 0, 0, 0, 0, first, 1, -1, -1))
                block.nodes[attachment].next = helper
                self.assertEqual(rpgidle.body_node(block, animation), (body, parent))
            repaired, audit = rpgidle.repair_sprite(sprite, unit)
            self.assertEqual(len(audit), 2)
            for animation in repaired.blocks[0].animations[:2]:
                body, _ = rpgidle.body_node(repaired.blocks[0], animation)
                self.assertEqual(
                    len(repaired.blocks[0].node_keys(repaired.blocks[0].nodes[body])), 6
                )

    def test_manifest_relocates_and_blocks_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, unit = fixture(root)
            for f in unit["facings"].values():
                for s in f["switches"]:
                    s["png"] = Path(s["png"]).name
            manifest = root / "rpg-idle-timings.json"
            manifest.write_text(json.dumps({"units": {"99": unit}}))
            loaded = rpgidle.load_units(manifest)
            self.assertTrue(
                Path(
                    loaded["99"]["facings"]["front"]["switches"][0]["png"]
                ).is_absolute()
            )
            unit["facings"]["front"]["switches"][0]["png"] = "../outside.png"
            manifest.write_text(json.dumps({"units": {"99": unit}}))
            with self.assertRaisesRegex(ValueError, "escapes"):
                rpgidle.load_units(manifest)

    def test_bad_clock_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            sprite, unit = fixture(Path(temporary))
            original = copy.deepcopy(sprite)
            unit["facings"]["front"]["switches"][1]["ticks60"] = 0
            with self.assertRaisesRegex(ValueError, "increasing"):
                rpgidle.repair_sprite(sprite, unit)
            self.assertEqual(sprite, original)


def stream_word_data(entries):
    raw = bytearray()
    for time, values in entries:
        raw.extend(struct.pack("<fI", time, len(values)))
        for index, value in values:
            raw.extend(struct.pack("<I4f", index, 0, 0, 0, value))
    return list(struct.unpack("<" + str(len(raw) // 4) + "I", raw))


class ClipTests(unittest.TestCase):
    def clip(self, declared=1):
        return {
            "m_ClipBindingConstant": {
                "genericBindings": [{"typeID": 114, "isPPtrCurve": 1, "attribute": 0}],
                "pptrCurveMapping": [
                    {"m_FileID": 1, "m_PathID": 10},
                    {"m_FileID": 1, "m_PathID": 20},
                ],
            },
            "m_MuscleClip": {
                "m_StartTime": 0,
                "m_StopTime": 0.85,
                "m_Clip": {
                    "data": {
                        "m_StreamedClip": {
                            "curveCount": declared,
                            "data": stream_word_data(
                                [(0, [(0, 0)]), (0.5, [(0, 1)]), (float("inf"), [])]
                            ),
                        },
                        "m_DenseClip": {"m_CurveCount": 0},
                        "m_ConstantClip": {"data": []},
                    }
                },
            },
        }

    def test_declared_and_excluded_pointer_banks(self):
        self.assertEqual(
            rpgclips.sprite_timelines(self.clip(0)),
            rpgclips.sprite_timelines(self.clip(1)),
        )
        self.assertEqual(
            [
                s["path_id"]
                for s in rpgclips.sprite_timelines(self.clip())[0]["switches"]
            ],
            ["10", "20"],
        )

    def test_unexplained_bank_count_fails(self):
        with self.assertRaisesRegex(ValueError, "discrepancy"):
            rpgclips.sprite_timelines(self.clip(5))

    def test_active_out_of_bounds_is_not_preroll(self):
        with self.assertRaisesRegex(ValueError, "outside bank"):
            rpgclips.streamed_frames(stream_word_data([(0, [(1, 0)])]), 1)
        frames = rpgclips.streamed_frames(
            stream_word_data([(-3e38, [(9, 0)]), (0, [(0, 0)])]), 1
        )
        self.assertEqual(frames[0][1], {})

    def test_truncated_stream_fails(self):
        with self.assertRaisesRegex(ValueError, "Truncated"):
            rpgclips.streamed_frames([0], 1)


if __name__ == "__main__":
    unittest.main()
