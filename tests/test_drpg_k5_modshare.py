"""DRPG-K5: modshare typed remap for costume claims + the disable guard, through the real functions.

A DRPG costume is one char.dat row above 1000 (its class id C) whose art is a separate high number N
(sprite_id = color_id = N), plus face / portrait / name keys and an ASSIGNED small-list-icon row pair.  Two
packs built from the same vanilla tables claim the same ids, so all of those are typed claims: import moves
each exactly once, and a claim the pack does not carry fails before anything is written.

Prior art: `d5lib/modshare.py` (plan/apply/_spr/_rename, the K1-style pack fixtures in
tests/test_drpg_outfits_k1.py), `d5lib/outfits.py` load_colours/load_portraits, `d5lib/anm.py` (synthetic
single-block anm files), `d5lib/savegame.py` find (unit classes in saves).
"""
import contextlib
import json
import os
import tempfile
import unittest
from unittest import mock

from d5lib import anm, modshare, modsys, outfits

ICON_64 = 817


class Vanilla:
    """char.dat / texturedatabase stand-in: rows with ids, and the one member plan() reads"""

    def __init__(self, ids):
        self.rows = [{"id": int(i), "char_id": int(i), "sort_order": int(i)} for i in ids]

    def find(self, i):
        return next((r for r in self.rows if r["id"] == int(i)), None)


class FS:
    """only what plan()/disable_blockers() read; anm ids are stubbed by sprites.used_sprite_numbers"""

    def read(self, vpath):
        return b""


def make_pack(root, name, cls, art, icon, base=94, cutin=True):
    """One DRPG costume pack: a low base row + one declared costume class id, its art group and its keys."""
    mod = modsys.Mod(os.path.join(root, name))
    mod.meta.update({"name": name, "version": "1.0"})
    mod.save_meta()
    mod.save_patch("db", "char.dat.json", {"table": "char.dat", "added": [
        {"id": cls, "name_EN": "Zed", "sprite_id": art, "color_id": art},   # the base row is the game's own
    ]})
    mod.save_patch("outfits", "outfits.json", {
        "pairs": [[base, cls]],
        "colours": {str(cls): art},
        "names": {str(cls): "Halloween Zed"},
        "own_sprites": [art, art + 1],
        "icons": {str(cls): [icon, icon + ICON_64]},
        "portraits": {str(cls): "donor" if not cutin else "own"},
    })
    mod.save_patch("db", "texturedatabase.dat.json", {"table": "texturedatabase.dat", "added": [
        {"id": icon}, {"id": icon + ICON_64}]})
    for n in (art, art + 1, art + 2, art + 10000):
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs",
                       anm.AnmFile([anm.AnmBlock(n)], [], []).to_bytes())
    chars = os.path.join(mod.patches_dir, "characters")
    os.makedirs(chars, exist_ok=True)
    with open(os.path.join(chars, f"face_{cls}.png"), "wb") as f:
        f.write(b"\x89PNG face")
    with open(os.path.join(chars, f"portrait_{art + 10000}.json"), "wb") as f:
        f.write(b'{"source": "drpg"}')
    return mod


def data(mod):
    return json.loads(json.dumps(mod.load_patch("outfits", "outfits.json")))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="drpgk5-")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        # the game: three vanilla rows, no free sprite numbers, texturedatabase ids up to 12999
        self.van = Vanilla([1, 2, 3, 94])          # 94 is the base character, so it is never a claim

        def load_table(name, _bytes):
            return Vanilla(range(13000)) if name.startswith("texturedatabase") else self.van

        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch("d5lib.database.load_table", load_table))
        self.patches.enter_context(mock.patch("d5lib.sprites.used_sprite_numbers", lambda fs: set()))


class TypedRemapTests(Base):
    def test_colliding_costume_pack_moves_every_claim_exactly_once(self):
        other = make_pack(self.root, "other", 30100, 14000, 13000)
        pkg = make_pack(self.root, "pkg", 30100, 14000, 13000, cutin=False)
        mapping = modshare.plan(pkg, [other], FS())
        self.assertEqual(mapping["class"], {30100: 30101})
        self.assertEqual(mapping["art"], {14000: 9000})
        # a list-icon pair moves together, 817 apart
        self.assertEqual(mapping["icon"], {13000: 13001, 13817: 13818})
        modshare.apply(pkg, mapping, vanilla_char=self.van)

        d = data(pkg)
        self.assertEqual(d["pairs"], [[94, 30101]])
        self.assertEqual(d["colours"], {"30101": 9000})
        self.assertEqual(d["portraits"], {"30101": "donor"})
        self.assertEqual(d["icons"], {"30101": [13001, 13818]})
        self.assertEqual(d["own_sprites"], [9000, 9001])

        row = next(r for r in pkg.load_patch("db", "char.dat.json")["added"] if r["id"] < 1000 or r["id"] == 30101)
        self.assertEqual((row["id"], row["sprite_id"], row["color_id"]), (30101, 9000, 9000),
                         "a declared costume's colour follows its ART, never its class id")

        files = set(pkg.list_files())
        for n in (9000, 9001, 9002, 19000):
            self.assertIn(f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs", " ".join(files))
        chars = sorted(os.listdir(os.path.join(pkg.patches_dir, "characters")))
        self.assertIn("face_30101.png", chars, "faces are class-keyed")
        self.assertIn("portrait_19000.json", chars, "portrait keys are art numbers (10000 + N)")
        self.assertNotIn("portrait_24000.json", chars)
        tex = pkg.load_patch("db", "texturedatabase.dat.json")
        self.assertEqual([r["id"] for r in tex["added"]], [13001, 13818])

        # one dependent reference, one move: nothing moved twice, nothing left on the old id
        self.assertEqual(pkg.load_patch("db", "char.dat.json")["added"][0]["id"], 30101)
        self.assertEqual([r["id"] for r in pkg.load_patch("db", "texturedatabase.dat.json")["added"]],
                         [13001, 13818])

    def test_art_moves_without_the_class_when_only_the_art_collides(self):
        other = make_pack(self.root, "other", 30200, 14000, 13000)
        pkg = make_pack(self.root, "pkg", 30100, 14000, 13000)
        mapping = modshare.plan(pkg, [other], FS())
        self.assertEqual(mapping["class"], {})
        self.assertEqual(mapping["art"], {14000: 9000})
        modshare.apply(pkg, mapping, vanilla_char=self.van)
        d = data(pkg)
        self.assertEqual(d["pairs"], [[94, 30100]], "the class id is untouched")
        self.assertEqual(d["colours"], {"30100": 9000}, "the declared colour follows the art")
        row = pkg.load_patch("db", "char.dat.json")["added"][0]
        self.assertEqual((row["id"], row["color_id"]), (30100, 9000))

    def test_a_missing_claim_fails_before_anything_is_written(self):
        pkg = make_pack(self.root, "pkg", 30100, 14000, 13000)
        pkg.remove_file("Anime/ANM_HI_JP.dat/anm14000.lzs")
        age = os.stat(pkg.folder).st_mtime_ns
        with self.assertRaises(modshare.ClaimError) as e:
            modshare.validate_claims(pkg)
        self.assertIn("anm 14000", str(e.exception))
        self.assertEqual(os.stat(pkg.folder).st_mtime_ns, age)
        self.assertNotIn("local_ids", pkg.meta)

    def test_a_failed_apply_is_rolled_back_file_for_file(self):
        pkg = make_pack(self.root, "pkg", 30100, 14000, 13000)
        before = {f: pkg.read_file(f) for f in pkg.list_files()}
        broken = dict(pkg.load_patch("db", "char.dat.json"))
        broken["added"] = [{"name_EN": "no id"}]          # apply() raises on the missing id
        pkg.save_patch("db", "char.dat.json", broken)
        before = {f: pkg.read_file(f) for f in pkg.list_files()}
        before = {f: pkg.read_file(f) for f in pkg.list_files()}
        with mock.patch("d5lib.anm.parse", side_effect=ValueError("broken anm")):
            with self.assertRaises(ValueError):
                modshare.apply(pkg, {"class": {30100: 30101}, "art": {14000: 9000}})
        after = {f: pkg.read_file(f) for f in pkg.list_files()}
        self.assertEqual(after, before, "a failed move leaves the pack exactly as it was")


class IconClaimTests(Base):
    def test_icon_pair_is_a_claim_and_a_broken_declaration_is_refused(self):
        pkg = make_pack(self.root, "pkg", 30100, 14000, 13000)
        self.assertEqual(modshare.icon_claims(pkg), {13000: 13817})
        d = data(pkg)
        d["icons"] = {"30100": [13000]}                   # one row is not a pair
        pkg.save_patch("outfits", "outfits.json", d)
        with self.assertRaisesRegex(ValueError, "not a \\[48 px row, 64 px row\\] pair"):
            modshare.icon_claims(pkg)


class DisableGuardTests(Base):
    def test_disable_refuses_when_a_save_wears_the_costume(self):
        mod = make_pack(self.root, "drpg", 30100, 14000, 13000)
        unit = type("U", (), {"name": "Zed", "cls": 30100})()
        mgr = Manager([mod])
        with mock.patch("d5lib.savegame.find", return_value=[(os.path.join(self.root, "SaveData1"), None,
                                                              [unit], [], {})]):
            blockers = modshare.disable_blockers(mod, [], FS(), saves_root=self.root)
            self.assertEqual(len(blockers), 1)
            self.assertIn("class 30100", blockers[0])
            with self.assertRaises(modshare.DisableBlocked):
                modshare.disable(mod, mgr, FS(), saves_root=self.root, log=lambda s: None)
        self.assertTrue(mgr.enabled, "a blocked disable writes nothing")

    def test_disable_refuses_when_another_mod_uses_its_costume(self):
        mod = make_pack(self.root, "drpg", 30100, 14000, 13000)
        child = modsys.Mod(os.path.join(self.root, "child"))
        child.meta.update({"name": "child"})
        child.save_meta()
        child.save_patch("outfits", "outfits.json", {"pairs": [[30100, 30101]]})
        blockers = modshare.disable_blockers(mod, [child], FS())
        self.assertTrue(any("outfit class 30100" in b for b in blockers), blockers)

    def test_disable_succeeds_when_nothing_depends_on_it(self):
        mod = make_pack(self.root, "drpg", 30100, 14000, 13000)
        mgr = Manager([mod])
        self.assertTrue(modshare.disable(mod, mgr, FS(), log=lambda s: None))
        self.assertFalse(mgr.enabled)


class Manager:
    """the two ModManager calls disable() makes"""

    def __init__(self, mods):
        self.mods = list(mods)
        self.enabled = True

    def enabled_mods(self):
        return list(self.mods) if self.enabled else []

    def set_enabled(self, mod_id, on):
        self.enabled = bool(on)


if __name__ == "__main__":
    unittest.main()
