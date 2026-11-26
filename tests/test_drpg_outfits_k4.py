"""DRPG-K4: mixed-body costumes and attack roots (offline, synthetic tables only).

A look that changes body kind owns its body set: a monster costume of a humanoid character gets the monster body
fields, motion set and companion, and the monster normal-attack script copies; a humanoid costume of a monster
character gets the humanoid body fields and the Kit's own-animation path.  Nothing here reads the game, the
installed kit or private art.
"""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from d5lib import colorvariants, drpg, drpgmap, modsys, newclasses, outfits, ownanim, script, scriptpatch


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


BODY_FIELDS = dict(size_radius=7, height=44, height2=60, magichange_type=0, magichange_weapon=0,
                   overload_id=0, unk_0CA=104, mastery_sword=9)


def row(cid, sprite=None, colour=None, body=0, **extra):
    r = {"id": cid, "sprite_id": sprite if sprite is not None else cid,
         "color_id": colour if colour is not None else cid, "body_type": body,
         "name_EN": f"row{cid}"}
    r.update(BODY_FIELDS)
    r.update(extra)
    return r


class TemporaryTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="drpgk4-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)


class BodyDeclarationTests(TemporaryTree):
    """outfits.json keeps the declared body; dropping the pair drops it."""

    def test_bodies_round_trip_and_follow_the_pairs(self):
        mod = modsys.Mod(str(self.root / "mod"))
        outfits.save(mod, [[11, 30000]], names={30000: "Beach"}, colours={30000: 14880},
                     bodies={30000: 2010})
        data = json.loads((self.root / "mod/patches/outfits/outfits.json").read_text())
        self.assertEqual(data["bodies"], {"30000": 2010})
        self.assertEqual(outfits.load_bodies(mod), {30000: 2010})
        outfits.save(mod, [], names={}, colours=None, bodies=None)
        self.assertEqual(outfits.load_bodies(mod), {})

    def test_existing_mod_without_bodies_is_untouched(self):
        mod = modsys.Mod(str(self.root / "plain"))
        outfits.save(mod, [[10, 473]], names={473: "Swimsuit"})
        data = json.loads((self.root / "plain/patches/outfits/outfits.json").read_text())
        self.assertEqual(set(data), {"pairs", "names"})


class CreateMixedOutfitTests(TemporaryTree):
    """create_drpg_outfit(body=...) through the real builder path (only file I/O is stubbed)."""

    def setUp(self):
        super().setUp()
        self.mod = modsys.Mod(str(self.root / "mod"))
        self.fs = Mock()
        self.written = {}
        self.clones = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        patcher = self.stack.enter_context
        self.ed = Table([row(11, sprite=11, colour=10)])
        self.vanilla = Table([row(11, sprite=11, colour=10),
                              row(40, sprite=40, colour=40, body=0, height=52, height2=70, unk_0CA=101),
                              row(2010, sprite=2010, colour=2010, body=1, height=31, height2=48, unk_0CA=201)])
        patcher(patch.object(outfits, "_char_tables", side_effect=lambda fs, mod: (self.vanilla, self.ed)))
        patcher(patch.object(outfits.dbpatch, "diff_table", return_value={}))
        patcher(patch.object(drpg, "unit_sheets", return_value=None))
        patcher(patch.object(drpgmap, "own_map_path", return_value=str(Path(__file__))))
        patcher(patch.object(drpgmap, "load_hands", return_value={}))
        patcher(patch.object(outfits.sprites, "motion_block", return_value=None))
        patcher(patch.object(outfits.sprites, "sprite_vpath", return_value="Anime/anm.vp"))
        patcher(patch.object(outfits.anm, "parse", return_value=Mock()))
        self.build = patcher(patch.object(drpgmap, "build",
                                          return_value=(Mock(to_bytes=lambda: b"body"), {"ok": True})))
        self.companion = patcher(patch.object(newclasses, "monster_companion",
                                              return_value=Mock(to_bytes=lambda: b"companion")))
        self.ownanim = patcher(patch.object(ownanim, "with_id", return_value=Mock(to_bytes=lambda: b"copy")))
        patcher(patch.object(outfits, "save_source", return_value=None))
        patcher(patch.object(outfits, "_save_parts", return_value=None))
        patcher(patch.object(colorvariants, "repartition", return_value={}))
        patcher(patch.object(outfits, "_resident_icon", return_value=None))
        patcher(patch.object(drpg, "unit_extras", return_value={}))
        patcher(patch.object(outfits, "_clone", side_effect=lambda fs, mod, s, d: self.clones.append((s, d)) or True))
        patcher(patch.object(self.mod, "write_file", side_effect=self.write))

    def write(self, vp, data):
        self.written[vp] = data

    def test_monster_costume_of_humanoid_gets_the_monster_body_set(self):
        r = outfits.create_drpg_outfit(self.fs, self.mod, 11, 20091, "Beach Raspberyl", log=lambda *_: None,
                                       slot=30160, colour=14880, body="monster", body_template=2010)
        self.assertEqual((r["slot"], r["sprite"]), (30160, 14880))
        twin = self.ed.find(30160)
        self.assertEqual(twin["body_type"], 1)                       # monster body, not the character's
        self.assertEqual((twin["height"], twin["height2"], twin["unk_0CA"]), (31, 48, 201))
        self.assertEqual(twin["mastery_sword"], 9)
        self.assertEqual(outfits.load_bodies(self.mod), {30160: 2010})
        # its own motion set: built on the monster donor, not on the humanoid template 40
        self.assertEqual(self.build.call_args[0][2], 2010)
        # companion file, not an own-animation copy; and no "own sprite" claim (a monster plays its sprite's own)
        self.assertEqual(self.written["Anime/ANM_HI_JP.dat/anm14881.lzs"], b"companion")
        self.assertEqual(self.companion.call_args[0][2:], (2010, 14880))
        self.assertFalse(self.ownanim.called)
        self.assertEqual(outfits.load_own(self.mod), [])
        # declared look: only its art group, no slot-keyed copies
        self.assertEqual(sorted(self.written), ["Anime/ANM_HI_JP.dat/anm14880.lzs",
                                                "Anime/ANM_HI_JP.dat/anm14881.lzs"])
        self.assertEqual(self.clones, [(10010, 24880)])

    def test_humanoid_costume_of_monster_gets_the_humanoid_body_set(self):
        self.ed = Table([row(11, sprite=11, colour=10, body=1, height=44, height2=60, unk_0CA=104)])
        self.stack.enter_context(patch.object(outfits, "_char_tables",
                                              side_effect=lambda fs, mod: (self.vanilla, self.ed)))
        # no hybrid=: the look's own kind decides, not the character's
        r = outfits.create_drpg_outfit(self.fs, self.mod, 11, 191, "Majin Hanako", log=lambda *_: None,
                                       slot=30750, colour=16550, body="humanoid", body_template=40)
        self.assertEqual((r["slot"], r["sprite"]), (30750, 16550))
        twin = self.ed.find(30750)
        self.assertEqual(twin["body_type"], 0)                       # humanoid body, not the monster's
        self.assertEqual((twin["height"], twin["height2"], twin["unk_0CA"]), (52, 70, 101))
        self.assertEqual(outfits.load_bodies(self.mod), {30750: 40})
        self.assertEqual(self.build.call_args[0][2], 40)
        self.assertFalse(self.companion.called)                      # no monster companion
        self.assertEqual(self.written["Anime/ANM_HI_JP.dat/anm16551.lzs"], b"copy")
        self.assertEqual(outfits.load_own(self.mod), [16550, 16551])  # an own sprite: counts as a humanoid

    def test_monster_character_without_hybrid_or_body_still_refuses(self):
        self.ed = Table([row(11, sprite=11, colour=10, body=1)])
        self.stack.enter_context(patch.object(outfits, "_char_tables",
                                              side_effect=lambda fs, mod: (self.vanilla, self.ed)))
        with self.assertRaisesRegex(ValueError, "monster-type unit"):
            outfits.create_drpg_outfit(self.fs, self.mod, 11, 191, "x", log=lambda *_: None,
                                       slot=30750, colour=16550)


class ScriptSpriteTests(unittest.TestCase):
    """_script_sprites: a look with its own body kind reports the body it was built on to the skill scripts."""

    def test_declared_body_look_maps_its_sprite_to_its_donor(self):
        rows = {11: row(11, sprite=14560), 30160: row(30160, sprite=14880, body=1),
                30750: row(30750, sprite=16550, body=0)}
        ctx = SimpleNamespace(_outfit_bodies={30160: 2010, 30750: 40}, fs=Mock())
        with patch.object(outfits.database, "load_table", return_value=Table([row(11, sprite=14560)])):
            got = outfits._script_sprites(ctx, [[11, 30160], [11, 30750]], rows, {11: {}}, {}, own={16550, 16551})
        self.assertEqual(got[14880], 2010)          # the monster body it was built on
        self.assertEqual(got[16550], 40)            # the humanoid template

    def test_an_undeclared_outfit_is_unchanged(self):
        rows = {11: row(11, sprite=14560), 473: row(473, sprite=9550)}
        ctx = SimpleNamespace(fs=Mock())
        with patch.object(outfits.database, "load_table", return_value=Table([row(11, sprite=14560)])):
            got = outfits._script_sprites(ctx, [[11, 473]], rows, {}, {}, own={9550, 9551})
        self.assertEqual(got, {9550: 14560})


class MonsterAttackPairTests(unittest.TestCase):
    """_monster_attack_pairs: keyed on the LOOK's body kind, with the look's own donor."""

    def test_monster_costume_of_a_humanoid_character_is_paired_with_its_donor(self):
        rows = {11: row(11, sprite=14560), 30160: row(30160, sprite=14880, body=1)}
        pairs = outfits._monster_attack_pairs(rows, [11], {11: [30160]}, {30160: 2010})
        self.assertEqual(pairs, [(2010, 14880)])           # donor: the monster body it was built on

    def test_monster_character_outfit_keeps_the_character_sprite_as_donor(self):
        rows = {21: row(21, sprite=16580, body=1), 30200: row(30200, sprite=16680, body=1)}
        self.assertEqual(outfits._monster_attack_pairs(rows, [21], {21: [30200]}),
                         [(16580, 16680)])                 # unchanged behaviour for a monster character

    def test_humanoid_costume_of_a_monster_character_is_not_a_monster_pair(self):
        rows = {21: row(21, sprite=16580, body=1), 30750: row(30750, sprite=16550, body=0)}
        self.assertEqual(outfits._monster_attack_pairs(rows, [21], {21: [30750]}, {30750: 40}), [])


class MonsterScriptTests(unittest.TestCase):
    """_monster_scripts copies the three normal-attack events of the DONOR sprite for the look's sprite."""

    def test_events_copied_from_the_declared_donor(self):
        donor_events = [SimpleNamespace(id=p + 2010, encode=lambda: b"x")
                        for p in newclasses.MONSTER_SCRIPTS]
        added = {}

        class SF:
            events = []

        ctx = SimpleNamespace(log=lambda *_: None, parsed=lambda vp, f: SF(), changed=lambda *a: None)
        with patch.object(newclasses, "vanilla_script", return_value=SimpleNamespace(events=donor_events)), \
             patch.object(scriptpatch, "event_text", return_value="event text"), \
             patch.object(scriptpatch, "apply", side_effect=lambda sf, d: added.update(d["events"])):
            outfits._monster_scripts(ctx, [(2010, 14880)])
        self.assertEqual(sorted(added), [str(p + 14880) for p in newclasses.MONSTER_SCRIPTS])

    def test_a_humanoid_donor_copies_nothing(self):
        ctx = SimpleNamespace(log=lambda *_: None, parsed=lambda vp, f: SimpleNamespace(events=[]),
                              changed=lambda *a: None)
        with patch.object(newclasses, "vanilla_script", return_value=SimpleNamespace(events=[])):
            outfits._monster_scripts(ctx, [(14560, 14880)])     # no vanilla monster events for a humanoid sprite


if __name__ == "__main__":
    unittest.main()
