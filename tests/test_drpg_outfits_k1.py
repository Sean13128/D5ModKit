"""DRPG-K1: declared costume looks in the outfit builder (offline, synthetic tables only).

A declared look is one char.dat row owned by a low base, at a high class id, whose art is a high N with
sprite_id == color_id == N.  Nothing here reads the game, the installed kit or private art.
"""
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from d5lib import colorvariants, database, drpg, drpgmap, modsys, outfits, ownanim
from d5lib.importers import _drpg_build as worker
from d5lib.importers import _drpg_namespaces as namespaces
from d5lib.importers import drpg_leases


class Row(dict):
    def set(self, key, value):
        self[key] = value

    def copy(self):
        return Row(self)


class Table:
    def __init__(self, rows=()):
        self.rows = [Row(r) for r in rows]

    def find(self, uid):
        return next((r for r in self.rows if r["id"] == uid), None)


def row(cid, sprite=None, colour=None, body=0):
    return {"id": cid, "sprite_id": sprite if sprite is not None else cid,
            "color_id": colour if colour is not None else cid, "body_type": body,
            "name_EN": f"row{cid}"}


class TemporaryTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="drpgk1-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)


class GroupTests(unittest.TestCase):
    """_groups: a declared look is ONE look; a high id alone no longer makes it a rank family."""

    def test_declared_high_slot_is_one_look(self):
        rows = {11: row(11), 30000: row(30000, sprite=14600, colour=14600)}
        records, _, bases, members, key_of = outfits._groups([[11, 30000]], {}, rows, declared={30000})
        self.assertEqual(bases, [11])
        self.assertEqual(members[11], [30000])
        self.assertEqual([c for _, c, _ in records], [11, 30000])
        self.assertEqual(key_of[30000], 30000)

    def test_undeclared_generic_pair_still_expands_to_its_ranks(self):
        rows = {11000 + k: row(11000 + k) for k in range(10)}
        records, _, bases, members, _ = outfits._groups([[11000, 12000]], {}, rows)
        self.assertEqual(len(bases), 10)                   # unchanged Kit behaviour for a real family
        declared, _, _, one, _ = outfits._groups([[11000, 12000]], {}, rows, declared={12000})
        self.assertEqual(one[11000], [12000])              # a declared pair is one look even when both ids are high
        self.assertEqual(len(one[11000]), 1)


class OwnVoiceTests(TemporaryTree):
    """VOICE1b: an outfit follows its character's voice unless its pack declares the outfit's own."""

    def rows(self):
        return {r["id"]: Row(dict(r, voice_id=v, hp=h)) for r, v, h in
                ((row(22), 7003, 10), (row(30000, 14600, 14600), 7015, 1), (row(30001, 14610, 14610), 7016, 1))}

    def test_declared_outfit_keeps_its_voice_and_undeclared_follows(self):
        rows = self.rows()
        outfits._follow_base(rows, [[22, 30000], [22, 30001]], {30000})
        self.assertEqual((rows[30000]["voice_id"], rows[30001]["voice_id"]), (7015, 7003))
        self.assertEqual((rows[30000]["hp"], rows[30001]["hp"]), (10, 10))        # everything else still follows
        self.assertEqual(rows[30000]["sprite_id"], 14600)

    def test_no_declaration_is_todays_behaviour(self):
        rows = self.rows()
        outfits._follow_base(rows, [[22, 30000], [22, 30001]])
        self.assertEqual((rows[30000]["voice_id"], rows[30001]["voice_id"]), (7003, 7003))

    def test_declaration_is_read_saved_and_limited_to_the_packs_outfits(self):
        mod = modsys.Mod(str(self.root / "pack"))
        outfits.save(mod, [[22, 30000], [22, 30001]], own_sprites=[14600])
        self.assertEqual(outfits.load_own_voice(mod), [])
        self.assertEqual(outfits.set_own_voice(mod, [30000, 99999]), [30000])
        outfits.save(mod, outfits.load(mod))                                    # an editor save keeps the marker
        self.assertEqual(outfits.load_own_voice(mod), [30000])
        outfits.save(mod, [[22, 30001]])                                        # the outfit is gone: so is its marker
        self.assertEqual(outfits.load_own_voice(mod), [])


class ColourDeclarationTests(TemporaryTree):
    """outfits.json keeps the declared colour; nothing is declared for every existing mod."""

    def test_colours_round_trip_and_follow_the_pairs(self):
        mod = modsys.Mod(str(self.root / "mod"))
        outfits.save(mod, [[11, 30000]], names={30000: "Yukata"}, colours={30000: 14600})
        data = json.loads((self.root / "mod/patches/outfits/outfits.json").read_text())
        self.assertEqual(data["colours"], {"30000": 14600})
        self.assertEqual(outfits.load_colours(mod), {30000: 14600})
        # dropping the pair drops the declaration (a stale colour must not key anything)
        outfits.save(mod, [], names={}, colours=None)
        self.assertEqual(outfits.load_colours(mod), {})

    def test_existing_mod_without_colours_is_untouched(self):
        mod = modsys.Mod(str(self.root / "plain"))
        outfits.save(mod, [[10, 473]], names={473: "Swimsuit"})
        data = json.loads((self.root / "plain/patches/outfits/outfits.json").read_text())
        self.assertEqual(set(data), {"pairs", "names"})


class CreateDeclaredOutfitTests(TemporaryTree):
    """create_drpg_outfit's declared path: the leased row/colour, the art group only."""

    def setUp(self):
        super().setUp()
        self.mod = modsys.Mod(str(self.root / "mod"))
        self.fs = Mock()
        self.written = []
        self.clones = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        patcher = self.stack.enter_context
        self.ed = Table([row(11, sprite=11, colour=10)])
        patcher(patch.object(outfits, "_char_tables", side_effect=lambda fs, mod: (Table([row(11)]), self.ed)))
        patcher(patch.object(outfits.dbpatch, "diff_table", return_value={}))
        patcher(patch.object(drpg, "unit_sheets", return_value=None))
        patcher(patch.object(drpgmap, "own_map_path", return_value=str(Path(__file__))))
        patcher(patch.object(drpgmap, "load_hands", return_value={}))
        patcher(patch.object(outfits.sprites, "motion_block", return_value=None))
        patcher(patch.object(outfits.sprites, "sprite_vpath", return_value="Anime/anm.vp"))
        patcher(patch.object(outfits.anm, "parse", return_value=Mock()))
        patcher(patch.object(drpgmap, "build",
                             return_value=(Mock(to_bytes=lambda: b"body"), {"ok": True})))
        patcher(patch.object(ownanim, "with_id", return_value=Mock(to_bytes=lambda: b"copy")))
        patcher(patch.object(outfits, "save_source", return_value=None))
        patcher(patch.object(outfits, "_save_parts", return_value=None))
        patcher(patch.object(colorvariants, "repartition", return_value={}))
        patcher(patch.object(outfits, "_resident_icon", return_value=None))
        patcher(patch.object(drpg, "unit_extras", return_value={}))
        patcher(patch.object(outfits, "_clone", side_effect=self.clone))

    def clone(self, fs, mod, src, dst):
        self.clones.append((src, dst))
        return True

    def files(self):
        return sorted(p.name for p in (self.root / "mod").rglob("anm*.lzs"))

    def test_a_look_without_a_source_cut_in_labels_its_portrait_donor(self):
        """K2C / DECISIONS 2026-11-06: looks 426 and 60021 have no cut-in in the source.  The builder keeps the base's
        portrait but says so in the pack, so the receipt and the tracker never read it as the look's own art."""
        r = outfits.create_drpg_outfit(self.fs, self.mod, 11, 1001, "Halloween", log=lambda *_: None,
                                       slot=30000, colour=14600)
        self.assertEqual(outfits.load_portraits(self.mod), {30000: "donor"})
        self.assertEqual(outfits.PORTRAIT_DONOR, "donor (source has no cut-in)")
        # the declaration survives a later save() of the same pack (second look, rename ...)
        outfits.save(self.mod, outfits.load(self.mod))
        self.assertEqual(outfits.load_portraits(self.mod), {30000: "donor"})
        # and an explicit own portrait is recorded as own, not silence
        outfits.set_portrait(self.mod, 30000, "own")
        self.assertEqual(outfits.load_portraits(self.mod), {30000: "own"})

    def test_a_cut_in_made_from_the_looks_own_illustration_is_labelled_illustration(self):
        """DRPGCUTIN2: the portrait is labelled by where it came from: a file under an `own-cutins` folder is made
        from the look's illustration (not a source cut-in, not the donor's)"""
        own = self.root / "own-cutins"
        own.mkdir()
        (own / "1001.png").write_bytes(b"x")
        self.stack.enter_context(patch.object(drpg, "unit_extras", return_value={"cutin": str(own / "1001.png")}))
        self.stack.enter_context(patch.object(outfits, "set_cutin", return_value=None))
        outfits.create_drpg_outfit(self.fs, self.mod, 11, 1001, "Halloween", log=lambda *_: None, slot=30000, colour=14600)
        self.assertEqual(outfits.load_portraits(self.mod), {30000: "illustration"})

    def test_declared_look_writes_one_row_and_only_its_art_group(self):
        r = outfits.create_drpg_outfit(self.fs, self.mod, 11, 1001, "Yukata", log=lambda *_: None,
                                       slot=30000, colour=14600)
        self.assertEqual(r, {"slot": 30000, "sprite": 14600, "report": {"ok": True}})
        twin = self.ed.find(30000)
        self.assertEqual((twin["sprite_id"], twin["color_id"]), (14600, 14600))
        self.assertEqual(outfits.load(self.mod), [[11, 30000]])
        self.assertEqual(outfits.load_colours(self.mod), {30000: 14600})
        self.assertEqual(outfits.load_own(self.mod), [14600, 14601])
        # body set at the leased art number only: no slot-keyed (30002) and no 40000 portrait copies
        self.assertEqual(self.files(), ["anm14600.lzs", "anm14601.lzs"])
        self.assertEqual(self.clones, [(10010, 24600)])            # the base colour portrait -> N + 10000
        self.assertFalse(any(n in (30002, 40000) for _, n in self.clones))

    def test_undeclared_outfit_keeps_its_slot_keyed_copies(self):
        # the same builder without a declaration (every existing pack) still writes slot+2 / slot+10000
        self.stack.enter_context(patch.object(outfits, "free_slot", return_value=473))
        self.stack.enter_context(patch.object(outfits, "_free_sprite", return_value=9550))
        outfits.create_drpg_outfit(self.fs, self.mod, 11, 1001, "Old", log=lambda *_: None)
        self.assertEqual(outfits.load_colours(self.mod), {})
        self.assertIn((10010, 19550), self.clones)              # base colour portrait -> slot + 10000

    def test_declared_class_id_must_be_high_and_unused(self):
        with self.assertRaisesRegex(ValueError, "high class id"):
            outfits.create_drpg_outfit(self.fs, self.mod, 11, 1001, "x", log=lambda *_: None, slot=473, colour=14600)
        with self.assertRaisesRegex(ValueError, "step-10"):
            outfits.create_drpg_outfit(self.fs, self.mod, 11, 1001, "x", log=lambda *_: None, slot=30000, colour=14605)
        outfits.create_drpg_outfit(self.fs, self.mod, 11, 1001, "x", log=lambda *_: None, slot=30000, colour=14600)
        with self.assertRaisesRegex(ValueError, "already an outfit"):
            outfits.create_drpg_outfit(self.fs, self.mod, 11, 1003, "y", log=lambda *_: None, slot=30000, colour=14610)


class PortraitTests(TemporaryTree):
    """_portraits_for_sprites covers a declared look's high sprite instead of skipping every id >= 1000."""

    def test_declared_look_gets_its_sprite_portrait(self):
        vanilla = Table([row(11, sprite=14560, colour=10)])
        t = Table([row(11, sprite=14560, colour=10), row(30000, sprite=14600, colour=14600)])
        ctx = SimpleNamespace(outputs={}, log=lambda *_: None, fs=Mock())
        ctx.put = lambda vp, data: ctx.outputs.__setitem__(vp, data)
        copied = []
        with patch.object(outfits, "_anm_data", side_effect=lambda c, n: b"png" if n == 10010 else None), \
             patch.object(outfits, "_copy_anm", side_effect=lambda c, s, d: copied.append((s, d)) or True):
            filled = outfits._portraits_for_sprites(ctx, t, vanilla, {30000: 11})
        self.assertIn(14600, filled)
        self.assertIn((10010, 24600), copied)                   # from the base's colour portrait

    def test_plain_high_row_stays_out(self):
        vanilla = Table([row(11)])
        t = Table([row(30000, sprite=14600, colour=14600)])
        ctx = SimpleNamespace(outputs={}, log=lambda *_: None, fs=Mock())
        ctx.put = lambda vp, data: None
        with patch.object(outfits, "_anm_data", return_value=None), \
             patch.object(outfits, "_copy_anm", return_value=True):
            self.assertEqual(outfits._portraits_for_sprites(ctx, t, vanilla), [])


class IconOwnerTests(unittest.TestCase):
    def test_declared_look_claims_no_colour_derived_icon(self):
        rows = {11: row(11), 30000: row(30000, sprite=14600, colour=14600)}
        ctx = SimpleNamespace(_outfit_colours={30000: 14600})
        with patch.object(outfits, "_small_face_image", return_value=["cell"]), \
             patch.object(outfits, "base_face_image", return_value=["face"]):
            self.assertEqual(outfits._outfit_icon_owners(ctx, [[11, 30000]], rows, {}), [])
            self.assertEqual(len(outfits._outfit_icon_owners(SimpleNamespace(_outfit_colours={}),
                                                             [[11, 30000]], rows, {})), 1)


def entry(base, looks):
    return SimpleNamespace(id=f"drpg:{base}", mod_folder=f"Mod_{base}", source_ref={
        "best_base_look": looks[0]["id"],
        "character": {"base_id": base, "looks": looks}})


MANIFEST = {
    "schema": "drpg-leases/2",
    "bases": [{"lease": "drpg:1", "class_id": 11, "art": 14560, "sprite_id": 14560, "color_id": 14560}],
    "costumes": [{"lease": "drpg:1001", "owner": "drpg:1", "class_id": 30000, "art": 14600,
                  "sprite_id": 14600, "color_id": 14600}],
}


class PlanTests(TemporaryTree):
    """plan() reads the v2 manifest: the base keeps its independent leased sprite (K0: 193 vs 102 rows)."""

    def setUp(self):
        super().setUp()
        installed = self.root / "installed"
        installed.mkdir()
        self.ctx = {"installed_root": installed, "game_path": self.root / "game",
                    "source_root": self.root / "source", "output_root": self.root / "out"}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        p = self.stack.enter_context
        p(patch.object(worker, "_PLAN", {}))
        p(patch.object(worker, "source_fs", return_value=Mock()))
        p(patch.object(worker, "source_data", return_value=Mock()))
        p(patch.object(worker.database, "load_table", return_value=Table()))
        p(patch.object(worker, "distinct_looks",
                       side_effect=lambda c, best, source_root=None: copy.deepcopy(c["looks"])))
        p(patch.object(worker.sprites, "used_sprite_numbers", return_value=set()))
        # an empty pool: only the manifest can supply rows/sprites
        p(patch.object(worker.slots, "unique_pool", return_value=[]))
        p(patch.object(worker.modsys, "Mod", return_value=SimpleNamespace()))
        p(patch.object(worker.outfits, "_char_tables", return_value=(Table(), Table())))
        p(patch.object(worker.outfits, "load", return_value=[]))
        p(patch.object(namespaces, "reserve", return_value={}))
        p(patch.object(namespaces, "reserve_evilities", return_value={}))

    def test_base_uses_its_leased_sprite_not_its_row(self):
        lease = worker.plan([entry(1, [{"id": 1}])], self.ctx, leases=MANIFEST)["drpg:1"]
        self.assertEqual((lease["row"], lease["sprite"]), (11, 14560))
        self.assertNotEqual(lease["row"], lease["sprite"])

    def test_costume_takes_its_high_class_id_and_colour(self):
        lease = worker.plan([entry(1, [{"id": 1}, {"id": 1001}])], self.ctx, leases=MANIFEST)["drpg:1"]
        self.assertEqual(lease["costumes"],
                         [{"row": 30000, "sprite": 14600, "colour": 14600, "look": 1001}])

    def test_missing_costume_lease_fails_instead_of_inventing_one(self):
        with self.assertRaisesRegex(ValueError, "no costume 1002"):
            worker.plan([entry(1, [{"id": 1}, {"id": 1002}])], self.ctx, leases=MANIFEST)

    def test_manifest_with_sprite_equal_to_row_is_rejected(self):
        bad = copy.deepcopy(MANIFEST)
        bad["bases"][0].update(art=11, sprite_id=11, color_id=11)      # the K0 regression
        self.assertTrue(drpg_leases.verify(bad))
        self.assertEqual(drpg_leases.verify(MANIFEST), [])

    def test_costume_with_a_low_class_id_is_rejected(self):
        bad = copy.deepcopy(MANIFEST)
        bad["costumes"][0]["class_id"] = 473
        self.assertTrue(any("not high" in p for p in drpg_leases.verify(bad)))


class ShippedManifestTests(unittest.TestCase):
    def test_shipped_manifest_is_readable_and_consistent(self):
        manifest = drpg_leases.load()
        self.assertEqual(drpg_leases.verify(manifest), [])
        bases, costumes = drpg_leases.index(manifest)
        self.assertEqual((len(bases), len(costumes)), (146, 89))
        self.assertTrue(all(b["class_id"] < 1000 for b in bases.values()))
        self.assertTrue(all(c["class_id"] >= 1000 and c["sprite_id"] == c["color_id"] == c["art"]
                            for c in costumes.values()))


if __name__ == "__main__":
    unittest.main()
