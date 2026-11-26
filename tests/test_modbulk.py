"""SHAREBULK1: bulk export / import of mods (d5lib/modbulk.py): game folders, source mods untouched, local_ids skipped,
round trip into an empty mods dir, and `requires` re-pointed when the required mod's folder name was taken.

Prior art: d5lib/modshare.py import_package; fixtures follow tests/test_drpg_k5_modshare.py (database / sprite tables
stubbed, no game files).
"""
import contextlib
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from d5lib import anm, modbulk, modshare, modsys


class Vanilla:
    def __init__(self, ids):
        self.rows = [{"id": int(i), "char_id": int(i), "sort_order": int(i)} for i in ids]

    def find(self, i):
        return next((r for r in self.rows if r["id"] == int(i)), None)


class FS:
    def read(self, vpath):
        return b""


def rb(path):
    with open(path, "rb") as f:
        return f.read()


def jl(path):
    return json.loads(rb(path))


def make_mod(root, mid, **meta):
    mod = modsys.Mod(os.path.join(root, mid))
    mod.meta.update({"name": mid, "version": "1.0"})
    mod.meta.update(meta)
    mod.save_meta()
    mod.write_file("Text/readme.txt", mid.encode())
    return mod


def md5_all(mods_dir):
    out = {}
    for d in sorted(os.listdir(mods_dir)):
        p = os.path.join(mods_dir, d, "mod.json")
        if os.path.isfile(p):
            out[d] = hashlib.md5(rb(p)).hexdigest()
    return out


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="modbulk-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.src = os.path.join(self.tmp, "src", "mods")
        os.makedirs(self.src)
        patches = contextlib.ExitStack()
        self.addCleanup(patches.close)
        van = Vanilla([1, 2, 3])
        patches.enter_context(mock.patch("d5lib.database.load_table", lambda n, b: van))
        patches.enter_context(mock.patch("d5lib.sprites.used_sprite_numbers", lambda fs: set()))

    def mods(self):
        return modsys.ModManager(os.path.dirname(self.src)).all_mods()

    def target(self, name="dst"):
        kit = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(kit, "mods"))
        return kit, os.path.join(kit, "mods")


class GameOfTests(Base):
    def test_file_names_use_mod_names(self):
        make_mod(self.src, "D1C_Unique_2200", name="Thursday (D1C)")
        make_mod(self.src, "D4_Class_1080", name="Armor Knight (D4) \u2014 adapted offline import")
        make_mod(self.src, "D1C_Unique_2611", name="Kurtis (D1C)")
        make_mod(self.src, "D1C_Unique_2612", name="Kurtis (D1C)")
        make_mod(self.src, "D4_Unique_9", name='Bad/Name: "x"?')
        out = os.path.join(self.tmp, "out")
        rep = modbulk.export_all(self.mods(), out, log=lambda s: None)
        files = {e["id"]: e["file"] for e in rep["exported"]}
        self.assertEqual(files["D1C_Unique_2200"], "Thursday (D1C).zip")
        self.assertEqual(files["D4_Class_1080"], "Armor Knight (D4).zip")
        self.assertEqual(sorted([files["D1C_Unique_2611"], files["D1C_Unique_2612"]]),
                         ["Kurtis (D1C) [D1C_Unique_2612].zip", "Kurtis (D1C).zip"])
        self.assertEqual(files["D4_Unique_9"], "Bad_Name_ _x__.zip")
        for e in rep["exported"]:
            self.assertTrue(os.path.isfile(os.path.join(out, e["game"], e["file"])))

    def test_prefix_pack_and_source_import(self):
        m = lambda i, **k: make_mod(self.src, i, **k)  # noqa: E731
        self.assertEqual(modbulk.game_of(m("D1C_Class_1")), "D1C")
        self.assertEqual(modbulk.game_of(m("D4_Unique_170")), "D4")
        self.assertEqual(modbulk.game_of(m("DD2_Class_5")), "DD2")
        self.assertEqual(modbulk.game_of(m("DRPG_Core_Etna")), "DRPG")
        self.assertEqual(modbulk.game_of(m("Overlord Items")), "Overlord")
        self.assertEqual(modbulk.game_of(m("Outfit_System")), "Other")
        self.assertEqual(modbulk.game_of(m("Zed")), "Other")
        self.assertEqual(modbulk.game_of(m("Mystery"), {"Mystery": "D4"}), "D4")
        self.assertEqual(modbulk.game_of(m("X1", source_import={"identity": {"source": "d1c"}})), "D1C")
        self.assertEqual(modbulk.game_of(m("X2", source_import={"source_game": "d4"})), "D4")

    def test_packs_json_games(self):
        with open(os.path.join(self.src, "packs.json"), "w") as f:
            json.dump({"packs": [{"id": "dd2-characters", "members": ["Odd"]}, {"id": "zzz", "members": ["Q"]}]}, f)
        self.assertEqual(modbulk.load_pack_games(self.src), {"Odd": "DD2"})


class ExportTests(Base):
    def test_source_untouched_skip_local_ids_and_manifest(self):
        make_mod(self.src, "D4_Class_1")
        make_mod(self.src, "D1C_Class_9", uid="abc")
        make_mod(self.src, "D4_Unique_2", local_ids={"class": {"5": 6}})
        junk = make_mod(self.src, "Outfit_System")
        junk.write_file("Text/.DS_Store", b"junk")
        before = md5_all(self.src)
        out = os.path.join(self.tmp, "out")
        rep = modbulk.export_all(self.mods(), out, log=lambda s: None)
        self.assertEqual(md5_all(self.src), before)
        self.assertEqual(rep["games"], {"D4": 1, "D1C": 1, "Other": 1})
        with zipfile.ZipFile(os.path.join(out, "Other", "Outfit_System.zip")) as z:
            self.assertFalse([n for n in z.namelist() if ".DS_Store" in n])
        self.assertEqual([s["id"] for s in rep["skipped"]], ["D4_Unique_2"])
        self.assertTrue(os.path.isfile(os.path.join(out, "README.txt")))
        man = jl(os.path.join(out, "D4", "manifest.json"))
        self.assertEqual([e["id"] for e in man["mods"]], ["D4_Class_1"])
        self.assertEqual(man["skipped"][0]["id"], "D4_Unique_2")
        e = man["mods"][0]
        self.assertFalse(e["uid_stored"])
        self.assertEqual(e["uid"], modbulk.uid_of(modsys.Mod(os.path.join(self.src, "D4_Class_1")))[0])
        self.assertEqual(len(e["sha256"]), 64)
        z = os.path.join(out, "D4", e["file"])
        self.assertEqual(hashlib.sha256(rb(z)).hexdigest(), e["sha256"])
        top, meta = modshare.read_package(z)
        self.assertEqual(meta["uid"], e["uid"])
        keep = jl(os.path.join(out, "D1C", "manifest.json"))["mods"][0]
        self.assertTrue(keep["uid_stored"])
        self.assertEqual(keep["uid"], "abc")

    def test_filters_games_only_enabled_and_closure(self):
        make_mod(self.src, "D4_Class_1", requires=["Outfit_System"])
        make_mod(self.src, "D1C_Class_9")
        make_mod(self.src, "Outfit_System")
        out = os.path.join(self.tmp, "out")
        rep = modbulk.export_all(self.mods(), out, games=["D4"], log=lambda s: None)
        ids = {e["id"]: e for e in rep["exported"]}
        self.assertEqual(set(ids), {"D4_Class_1", "Outfit_System"})
        self.assertTrue(ids["Outfit_System"]["dependency"])
        self.assertEqual(ids["D4_Class_1"]["requires_other_game"], ["Outfit_System"])
        self.assertEqual(ids["D4_Class_1"]["requires_uid"], [ids["Outfit_System"]["uid"]])
        rep = modbulk.export_all(self.mods(), os.path.join(self.tmp, "o2"), games=["D4"], closure=False,
                                 log=lambda s: None)
        self.assertEqual([e["id"] for e in rep["exported"]], ["D4_Class_1"])
        self.assertEqual(rep["exported"][0]["requires_not_exported"], ["Outfit_System"])
        rep = modbulk.export_all(self.mods(), os.path.join(self.tmp, "o3"), only=["D1C_*"], log=lambda s: None)
        self.assertEqual([e["id"] for e in rep["exported"]], ["D1C_Class_9"])
        rep = modbulk.export_all(self.mods(), os.path.join(self.tmp, "o4"), only_enabled=True,
                                 enabled_ids={"D1C_Class_9"}, log=lambda s: None)
        self.assertEqual([e["id"] for e in rep["exported"]], ["D1C_Class_9"])

    def test_stamp_uids_is_opt_in(self):
        make_mod(self.src, "D4_Class_1")
        modbulk.export_all(self.mods(), os.path.join(self.tmp, "o"), stamp_uids=True, log=lambda s: None)
        self.assertEqual(jl(os.path.join(self.src, "D4_Class_1", "mod.json"))["uid"],
                         modbulk.uid_of(modsys.Mod(os.path.join(self.src, "D4_Class_1")))[0])

    def test_export_package_still_stamps_and_strips_local_ids(self):
        mod = make_mod(self.src, "D4_Class_1")
        z = modshare.export_package(mod, os.path.join(self.tmp, "one.zip"), version="2.0")
        self.assertEqual(modshare.read_package(z)[1]["version"], "2.0")
        self.assertTrue(jl(os.path.join(self.src, "D4_Class_1", "mod.json"))["uid"])


class MoveCompressedAnmTests(Base):
    def test_a_moved_sprite_keeps_its_lzs_compressed_anm_compressed(self):
        mod = make_mod(self.src, "DD2_Unique_1")
        data = anm.lzs_compress(anm.AnmFile([anm.AnmBlock(630)], [], []).to_bytes())
        mod.write_file("Anime/ANM_HI_JP.dat/anm00630.lzs", data)
        modshare.apply(mod, {"sprite": {630: 9070}}, log=lambda s: None, vanilla_char=Vanilla([1]))
        self.assertFalse(mod.has_file("Anime/ANM_HI_JP.dat/anm00630.lzs"))
        raw = mod.read_file("Anime/ANM_HI_JP.dat/anm09070.lzs")
        self.assertEqual(raw[:4], b"dat\0")
        self.assertEqual([b.id for b in anm.load(raw).blocks], [9070])


class ImportTests(Base):
    def run_import(self, folder, mods_dir, kit):
        return modbulk.import_folder(folder, mods_dir, FS(), os.path.join(kit, "state"), log=lambda s: None)

    def test_round_trip_into_empty_mods_dir_dependencies_first(self):
        make_mod(self.src, "D4_Class_1", requires=["Outfit_System"])
        make_mod(self.src, "D1C_Class_9")
        make_mod(self.src, "Outfit_System")
        out = os.path.join(self.tmp, "out")
        modbulk.export_all(self.mods(), out, log=lambda s: None)
        kit, mods_dir = self.target()
        s = self.run_import(out, mods_dir, kit)
        self.assertEqual(s["failed"], [])
        self.assertEqual(sorted(s["imported"]), ["D1C_Class_9", "D4_Class_1", "Outfit_System"])
        self.assertLess(s["imported"].index("Outfit_System"), s["imported"].index("D4_Class_1"))
        self.assertEqual(s["repointed"], {})
        self.assertTrue(os.path.isfile(os.path.join(mods_dir, "D4_Class_1", "files", "Text", "readme.txt")))
        # again: same uids -> updates, nothing new
        s = self.run_import(out, mods_dir, kit)
        self.assertEqual((s["imported"], len(s["updated"])), ([], 3))

    def test_requires_repointed_when_the_folder_name_was_taken(self):
        make_mod(self.src, "D4_Class_1", requires=["Outfit_System"])
        make_mod(self.src, "Outfit_System")
        out = os.path.join(self.tmp, "out")
        modbulk.export_all(self.mods(), out, log=lambda s: None)
        kit, mods_dir = self.target()
        make_mod(mods_dir, "Outfit_System", uid="someone-elses-uid")      # a different mod holds the name
        s = self.run_import(out, mods_dir, kit)
        self.assertEqual(s["renamed"], {"Outfit_System": "Outfit_System_2"})
        self.assertEqual(s["repointed"], {"D4_Class_1": {"Outfit_System": "Outfit_System_2"}})
        meta = jl(os.path.join(mods_dir, "D4_Class_1", "mod.json"))
        self.assertEqual(meta["requires"], ["Outfit_System_2"])
        self.assertEqual(jl(os.path.join(mods_dir, "Outfit_System", "mod.json"))["uid"],
                         "someone-elses-uid")

    def test_one_bad_zip_does_not_stop_the_rest_and_missing_requires_reported(self):
        make_mod(self.src, "D4_Class_1", requires=["Gone"])
        out = os.path.join(self.tmp, "out")
        modbulk.export_all(self.mods(), out, log=lambda s: None)
        with open(os.path.join(out, "D4", "broken.zip"), "wb") as f:
            f.write(b"not a zip")
        with zipfile.ZipFile(os.path.join(out, "D4", "evil.zip"), "w") as z:
            z.writestr("a/mod.json", "{}")
            z.writestr("b/../x.txt", "x")
        kit, mods_dir = self.target()
        s = self.run_import(out, mods_dir, kit)
        self.assertEqual(s["imported"], ["D4_Class_1"])
        self.assertEqual(len(s["failed"]), 2)
        self.assertEqual(s["missing_requires"], {"D4_Class_1": ["Gone"]})


if __name__ == "__main__":
    unittest.main()
