"""tools/prep_source.py: copy, verify, link, refuse, preserve and explain (SOURCEPREP2, offline).

Every test runs sandboxed: Steam/game discovery is stubbed, so no test reads the host's Steam libraries or settings.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from d5lib import sourcefolder

TOOL = Path(__file__).resolve().parents[1] / "tools" / "prep_source.py"
_spec = importlib.util.spec_from_file_location("prep_source", TOOL)
prep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prep)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_d4(root):
    for index, rel in enumerate(prep.D4_FILES):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"d4 file {index} {rel}".encode())


def known_rows(rows):
    """rows: iterable of (game, rel, bytes, build) -> a synthetic known-good table."""
    games = {}
    for game, rel, data, build in rows:
        games.setdefault(game, {"edition": "synthetic", "files": {}})["files"].setdefault(rel, []).append(
            {"size": len(data), "sha256": sha(data), "build": build})
    return {"schema": "d5-source-known/1", "games": games}


def write_known(tmp, rows, name="known.json"):
    path = Path(tmp) / name
    path.write_text(json.dumps(known_rows(rows)))
    return path


def run(args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = prep.main(args)
    return code, out.getvalue()


class Sandboxed(unittest.TestCase):
    """No host discovery: Steam, the saved game dir and the kit settings all answer None."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        for target, kwargs in ((prep, {"name": "steam_app", "return_value": None}),
                               (prep.paths, {"name": "steam_libraries_all", "return_value": []}),
                               (prep.paths, {"name": "platform_steam_roots", "return_value": []}),
                               (prep.paths, {"name": "game_dir", "return_value": None}),
                               (prep.paths, {"name": "kit_setting", "return_value": None})):
            patcher = mock.patch.object(target, kwargs.pop("name"), **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)


class D4PrepTests(Sandboxed):
    def setUp(self):
        super().setUp()
        self.src = self.tmp / "d4-game"
        make_d4(self.src)
        self.dest = self.tmp / "Source"
        self.known = write_known(self.tmp, [("d4", rel, (self.src / rel).read_bytes(), "synthetic")
                                            for rel in prep.D4_FILES])

    def args(self, *extra):
        return ["--only", "d4", "--d4", str(self.src), "--dest", str(self.dest),
                "--known", str(self.known), *extra]

    def test_verified_copy_and_manifest(self):
        code, out = run(self.args())
        self.assertEqual(code, 0, out)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        self.assertEqual(manifest["schema"], "d5-source-manifest/1")
        files = manifest["games"]["d4"]["files"]
        self.assertEqual(len(files), len(prep.D4_FILES))
        self.assertTrue(all(f["verified"] == "yes" for f in files))
        self.assertTrue(all(f["known_build"] == "synthetic" for f in files))
        for rel in prep.D4_FILES:
            self.assertEqual((self.dest / "d4" / rel).read_bytes(), (self.src / rel).read_bytes())
        self.assertIn("D5 base game is read in place", out)

    def test_second_run_keeps_existing_files(self):
        self.assertEqual(run(self.args())[0], 0)
        mtime = (self.dest / "d4" / prep.D4_FILES[0]).stat().st_mtime_ns
        self.assertEqual(run(self.args())[0], 0)
        self.assertEqual((self.dest / "d4" / prep.D4_FILES[0]).stat().st_mtime_ns, mtime)

    def test_corrupted_copy_reports_no(self):
        rel = "Data/DATA/ANM_HI.dat"
        (self.src / rel).write_bytes((self.src / rel).read_bytes() + b"!")
        code, out = run(self.args("--json"))
        self.assertEqual(code, 1, out)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        row = next(f for f in manifest["games"]["d4"]["files"] if f["path"] == rel)
        self.assertEqual(row["verified"], "no")
        self.assertEqual((self.dest / "d4" / rel).read_bytes(), (self.src / rel).read_bytes())

    def test_verified_output_survives_a_mismatched_retry(self):
        """Review finding 4: a bad input never replaces a verified file already in the folder."""
        self.assertEqual(run(self.args())[0], 0)
        rel = "Data/DATA/ANM_HI.dat"
        good = (self.dest / "d4" / rel).read_bytes()
        (self.src / rel).write_bytes(b"corrupted re-pull")
        code, out = run(self.args("--json"))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.dest / "d4" / rel).read_bytes(), good)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        row = next(f for f in manifest["games"]["d4"]["files"] if f["path"] == rel)
        self.assertEqual(row["verified"], "yes")
        self.assertIn("kept", row["note"])
        self.assertIn("kept the verified file", out)

    def test_failed_first_copy_describes_the_destination(self):
        """Review R2 finding 3: a failed first copy leaves no file, so the row must not carry the input's hash."""
        def broken_copy(src, dst, *a, **kw):
            raise OSError("disk full")

        with mock.patch.object(prep.shutil, "copy2", side_effect=broken_copy):
            code, out = run(self.args("--json"))
        self.assertEqual(code, 1, out)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        for row in manifest["games"]["d4"]["files"]:
            self.assertEqual(row["verified"], "missing")
            self.assertIsNone(row["sha256"])
        self.assertFalse((self.dest / "d4" / prep.D4_FILES[0]).exists())

    def test_unavailable_input_keeps_the_prepared_rows(self):
        """Review R2 finding 3: a selected retry with no input must not erase the rows of files still on disk."""
        self.assertEqual(run(self.args())[0], 0)
        code, out = run(["--only", "d4", "--dest", str(self.dest), "--known", str(self.known), "--json"])
        self.assertEqual(code, 1, out)  # the input failure is still reported
        manifest = json.loads((self.dest / "manifest.json").read_text())
        rows = manifest["games"]["d4"]["files"]
        self.assertEqual(len(rows), len(prep.D4_FILES))
        self.assertTrue(all(row["verified"] == "yes" for row in rows))
        self.assertTrue((self.dest / "d4" / prep.D4_FILES[0]).is_file())

    def test_failed_staged_replacement_keeps_previous_file(self):
        self.assertEqual(run(self.args())[0], 0)
        rel = "Data/DATA/ANM_HI.dat"
        good = (self.dest / "d4" / rel).read_bytes()
        new_data = b"new verified build"
        (self.src / rel).write_bytes(new_data)
        rows = [("d4", r, good if r == rel else (self.src / r).read_bytes(), "synthetic")
                for r in prep.D4_FILES]
        rows += [("d4", rel, new_data, "synthetic-new")]
        self.known = write_known(self.tmp, rows, name="known2.json")

        def broken_copy(src, dst, *a, **kw):
            Path(dst).write_bytes(b"partial")
            raise OSError("disk full")

        with mock.patch.object(prep.shutil, "copy2", side_effect=broken_copy):
            code, out = run(self.args("--json"))
        self.assertEqual(code, 1, out)
        self.assertEqual((self.dest / "d4" / rel).read_bytes(), good)
        leftovers = list((self.dest / "d4/Data/DATA").glob(".*.part"))
        self.assertEqual(leftovers, [])
        manifest = json.loads((self.dest / "manifest.json").read_text())
        row = next(f for f in manifest["games"]["d4"]["files"] if f["path"] == rel)
        self.assertEqual(row["verified"], "yes")
        self.assertIn("previous file was kept", row["note"])

    def test_nested_destination_symlink_is_refused(self):
        """Review finding 4: a symlinked destination ancestor may not redirect writes outside the folder."""
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        (self.dest / "d4").mkdir(parents=True)
        (self.dest / "d4/Data").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SystemExit) as ctx:
            run(self.args())
        self.assertIn("refusing", str(ctx.exception))
        self.assertFalse((outside / "DATA/ANM_HI.dat").exists())

    def test_link_mode(self):
        code, out = run(self.args("--link"))
        self.assertEqual(code, 0, out)
        target = self.dest / "d4" / prep.D4_FILES[0]
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.read_bytes(), (self.src / prep.D4_FILES[0]).read_bytes())

    def test_failed_link_replacement_keeps_the_previous_output(self):
        """Review R2 finding 1: a replacement link is staged and renamed, so a failed link keeps the output."""
        self.assertEqual(run(self.args("--link"))[0], 0)
        rel = "Data/DATA/ANM_HI.dat"
        target = self.dest / "d4" / rel
        original = os.readlink(target)
        src2 = self.tmp / "d4-game-2"
        make_d4(src2)
        (src2 / rel).write_bytes(b"a second accepted build")
        rows = [("d4", r, (self.src / r).read_bytes(), "synthetic-old") for r in prep.D4_FILES]
        rows.append(("d4", rel, (src2 / rel).read_bytes(), "synthetic-new"))
        known2 = write_known(self.tmp, rows, name="known2.json")
        with mock.patch.object(prep.os, "symlink", side_effect=OSError("link refused")):
            code, out = run(["--only", "d4", "--d4", str(src2), "--dest", str(self.dest),
                             "--known", str(known2), "--link", "--json"])
        self.assertEqual(code, 1, out)
        self.assertTrue(target.is_symlink())
        self.assertEqual(os.readlink(target), original)
        self.assertEqual(target.read_bytes(), (self.src / rel).read_bytes())
        leftovers = [p.name for p in target.parent.iterdir() if p.name.startswith("." + target.name)]
        self.assertEqual(leftovers, [])
        manifest = json.loads((self.dest / "manifest.json").read_text())
        row = next(f for f in manifest["games"]["d4"]["files"] if f["path"] == rel)
        self.assertEqual(row["verified"], "yes")
        self.assertIn("previous file was kept", row["note"])

    def test_dry_run_writes_nothing(self):
        code, out = run(self.args("--dry-run"))
        self.assertEqual(code, 0, out)
        self.assertFalse(self.dest.exists())

    def test_refuses_destination_inside_input(self):
        with self.assertRaises(SystemExit) as ctx:
            run(self.args("--dest", str(self.src / "out")))
        self.assertIn("refusing", str(ctx.exception))

    def test_refuses_disgaea_source_tree(self):
        with self.assertRaises(SystemExit) as ctx:
            run(self.args("--dest", str(self.tmp / "Disgaea Source" / "Source")))
        self.assertIn("Disgaea Source", str(ctx.exception))


class ForeignManifestTests(Sandboxed):
    """Review R5: another tool's manifest.json in --dest is refused, never replaced, even when prep would exit 1."""

    def setUp(self):
        super().setUp()
        self.src = self.tmp / "d4-game"
        make_d4(self.src)
        self.dest = self.tmp / "Source"
        self.known = write_known(self.tmp, [("d4", rel, (self.src / rel).read_bytes(), "synthetic")
                                            for rel in prep.D4_FILES])

    def args(self, *extra):
        return ["--only", "d4", "--d4", str(self.src), "--dest", str(self.dest),
                "--known", str(self.known), *extra]

    def foreign(self, doc=None, raw=None):
        """Write a manifest.json another tool could have left; return its exact bytes."""
        path = self.dest / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = raw if raw is not None else json.dumps(
            doc if doc is not None else {"schema": "local-export/1", "files": ["keep me"]}).encode()
        path.write_bytes(data)
        return path, data

    def assert_refused(self, path, data, args=None):
        with self.assertRaises(SystemExit) as ctx:
            run(args or self.args())
        message = str(ctx.exception)
        self.assertIn("not a D5 source manifest", message)
        self.assertIn(str(path), message)
        self.assertIn("fresh destination", message)
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["manifest.json"])

    def test_another_tool_schema_is_refused_before_any_copy(self):
        path, data = self.foreign()
        self.assert_refused(path, data)
        self.assertFalse((self.dest / "d4").exists())

    def test_a_dry_run_refuses_a_foreign_manifest_too(self):
        path, data = self.foreign()
        self.assert_refused(path, data, self.args("--dry-run"))

    def test_invalid_json_is_refused(self):
        path, data = self.foreign(raw=b"{not json")
        self.assert_refused(path, data)

    def test_a_json_value_that_is_not_an_object_is_refused(self):
        path, data = self.foreign(raw=b'["a", "b"]')
        self.assert_refused(path, data)

    def test_the_review_reproduction_a_failing_run_keeps_the_foreign_file(self):
        """The R5 probe: --only drpg with a folder lacking looks.json exits 1; the foreign file must survive."""
        path, data = self.foreign({"schema": "local-export/1", "records": [{"user": "keep"}]})
        src = self.tmp / "drpg-no-index"
        src.mkdir()
        self.assert_refused(path, data, ["--only", "drpg", "--drpg", str(src), "--dest", str(self.dest)])

    def test_a_valid_d5_manifest_still_runs_and_is_rewritten(self):
        self.assertEqual(run(self.args())[0], 0)
        manifest = self.dest / "manifest.json"
        first = json.loads(manifest.read_text())
        self.assertEqual(first["schema"], "d5-source-manifest/1")
        code, out = run(self.args("--json"))
        self.assertEqual(code, 0, out)
        second = json.loads(manifest.read_text())
        self.assertEqual(second["schema"], "d5-source-manifest/1")
        self.assertEqual({f["path"]: f["verified"] for f in second["games"]["d4"]["files"]},
                         {rel: "yes" for rel in prep.D4_FILES})

    def test_a_valid_manifest_without_games_is_still_a_d5_manifest(self):
        self.foreign({"schema": "d5-source-manifest/1"})
        code, out = run(self.args())
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads((self.dest / "manifest.json").read_text())["schema"], "d5-source-manifest/1")


class DefaultDestinationTests(Sandboxed):
    """Review finding 1: prep and the resolver share the one game-relative folder, even with the kit elsewhere."""

    def test_prep_and_resolver_agree_off_game(self):
        game = self.tmp / "game"
        (game / "Data").mkdir(parents=True)
        (game / "disgaea5.exe").write_bytes(b"exe")
        src = self.tmp / "d4-game"
        make_d4(src)
        known = write_known(self.tmp, [("d4", rel, (src / rel).read_bytes(), "synthetic")
                                       for rel in prep.D4_FILES])
        with mock.patch.object(prep.paths, "game_dir", return_value=str(game)):
            code, out = run(["--only", "d4", "--d4", str(src), "--known", str(known)])
            self.assertEqual(code, 0, out)
            env = {k: v for k, v in os.environ.items() if k != sourcefolder.ENV}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(sourcefolder.source_dir(), game / "D5ModKit" / "Source")
        self.assertTrue((game / "D5ModKit/Source/d4/Data/DATA/ANM_HI.dat").is_file())

    def test_kit_source_fallback_only_when_no_game(self):
        env = {k: v for k, v in os.environ.items() if k != sourcefolder.ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(sourcefolder.default_source_dir(), Path(sourcefolder.paths.KIT_DIR) / "Source")


class D1CTests(Sandboxed):
    SWITCH = b"switch romfs SUBDATA bytes"
    PS4 = b"ps4 unpack SUBDATA bytes, a different build"
    OTHER = b"an unrecognized SUBDATA of a third length entirely"

    def setUp(self):
        super().setUp()
        self.dest = self.tmp / "Source"
        self.rows = [("d1c", "data/SUBDATA.DAT", self.SWITCH, "d1c-switch-01004B100AF18000"),
                     ("d1c", "data/SUBDATA.DAT", self.PS4, "d1c-ps4-CUSA13171")]
        self.known = write_known(self.tmp, self.rows)

    def dump(self, name, data):
        folder = self.tmp / "dumps" / name / "data"
        folder.mkdir(parents=True)
        (folder / "SUBDATA.DAT").write_bytes(data)
        return folder.parent

    def args(self, root, *extra):
        return ["--only", "d1c", "--d1c", str(root), "--dest", str(self.dest),
                "--known", str(self.known), *extra]

    def test_mixed_parent_prefers_the_switch_hd_dump(self):
        dump = self.tmp / "dumps"
        self.dump("ps4", self.PS4)
        self.dump("switch", self.SWITCH)
        code, out = run(self.args(dump, "--json"))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.dest / "d1c/data/SUBDATA.DAT").read_bytes(), self.SWITCH)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        self.assertEqual(manifest["games"]["d1c"]["hd_faces"], "switch")
        self.assertIn("Switch SUBDATA.DAT chosen", out)

    def test_ps4_only_is_incomplete(self):
        dump = self.dump("ps4", self.PS4)
        code, out = run(self.args(dump, "--json"))
        self.assertEqual(code, 1, out)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        self.assertEqual(manifest["games"]["d1c"]["hd_faces"], "ps4-incomplete")
        self.assertTrue(all(f["verified"] == "yes" for f in manifest["games"]["d1c"]["files"]))
        self.assertIn("incomplete", out)
        self.assertIn("D1CHDFACE1", out)

    def test_ps4_retry_keeps_the_prepared_switch_dump(self):
        """Review R2 finding 2: an incomplete PS4 retry must not overwrite a prepared Switch dump."""
        switch_root = self.dump("switch", self.SWITCH)
        ps4_root = self.dump("ps4", self.PS4)
        self.assertEqual(run(self.args(switch_root))[0], 0)
        code, out = run(self.args(ps4_root, "--json"))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.dest / "d1c/data/SUBDATA.DAT").read_bytes(), self.SWITCH)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        self.assertEqual(manifest["games"]["d1c"]["hd_faces"], "switch")
        row = manifest["games"]["d1c"]["files"][0]
        self.assertEqual(row["verified"], "yes")
        self.assertIn("kept the prepared Switch SUBDATA.DAT", out)

    def test_failed_switch_copy_over_ps4_reports_the_retained_build(self):
        """Review R2 finding 2: hd_faces describes the retained PS4 file, not the Switch input that failed."""
        ps4_root = self.dump("ps4", self.PS4)
        self.assertEqual(run(self.args(ps4_root))[0], 1)
        switch_root = self.dump("switch", self.SWITCH)

        def broken_copy(src, dst, *a, **kw):
            raise OSError("disk full")

        with mock.patch.object(prep.shutil, "copy2", side_effect=broken_copy):
            code, out = run(self.args(switch_root, "--json"))
        self.assertEqual(code, 1, out)
        self.assertEqual((self.dest / "d1c/data/SUBDATA.DAT").read_bytes(), self.PS4)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        self.assertEqual(manifest["games"]["d1c"]["hd_faces"], "ps4-incomplete")
        row = manifest["games"]["d1c"]["files"][0]
        self.assertEqual(row["verified"], "yes")
        self.assertIn("previous file was kept", row["note"])

    def test_unrecognized_build_does_not_raise_a_ps4_warning(self):
        """Review finding 2: hash recognition is distinct from HD readiness."""
        dump = self.dump("some-romfs", self.OTHER)
        code, out = run(self.args(dump, "--json"))
        self.assertEqual(code, 1, out)
        self.assertNotIn("PS4 SUBDATA.DAT is incomplete", out)
        self.assertIn("not a recognized D1 Complete build", out)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        self.assertEqual(manifest["games"]["d1c"]["hd_faces"], "unrecognized")


class DrpgInventoryTests(Sandboxed):
    """Review finding 3: omissions against the known-good inventory are missing, not silently absent."""

    def setUp(self):
        super().setUp()
        self.src = self.tmp / "drpg"
        (self.src / "sprites/Sprites/Standard/BattleFront").mkdir(parents=True)
        (self.src / "sprites/Sprites/Standard/BattleFront/front15.png").write_bytes(b"png15")
        (self.src / "looks.json").write_bytes(b"{}")
        (self.src / "atlas-index.json").write_bytes(b"{}")
        voice = self.src / "assetbundle/sounds/voice/battle/15"
        voice.mkdir(parents=True)
        (voice / "15_acb").write_bytes(b"acb15")
        self.entries = {
            "looks.json": b"{}",
            "atlas-index.json": b"{}",
            "sprites/Sprites/Standard/BattleFront/front15.png": b"png15",
            "sprites/Sprites/Standard/BattleFront/front16.png": b"png16",
            "assetbundle/sounds/voice/battle/15/15_acb": b"acb15",
            "assetbundle/sounds/voice/battle/15/15_awb": b"awb15",
        }
        self.known = write_known(self.tmp, [("drpg", rel, data, "synthetic")
                                            for rel, data in self.entries.items()])
        self.dest = self.tmp / "Source"

    def args(self, *extra):
        return ["--only", "drpg", "--drpg", str(self.src), "--dest", str(self.dest),
                "--known", str(self.known), "--json", *extra]

    def rows(self):
        manifest = json.loads((self.dest / "manifest.json").read_text())
        return {f["path"]: f["verified"] for f in manifest["games"]["drpg"]["files"]}

    def test_inventory_omissions_are_missing(self):
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        rows = self.rows()
        self.assertEqual(rows["sprites/Sprites/Standard/BattleFront/front16.png"], "missing")
        self.assertEqual(rows["assetbundle/sounds/voice/battle/15/15_awb"], "missing")
        self.assertEqual(rows["sprites/Sprites/Standard/BattleFront/front15.png"], "yes")

    def test_empty_sprite_directory_does_not_pass(self):
        for png in self.src.rglob("*.png"):
            png.unlink()
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        rows = self.rows()
        self.assertEqual(rows["sprites/Sprites/Standard/BattleFront/front15.png"], "missing")
        self.assertEqual(rows["sprites/Sprites/Standard/BattleFront/front16.png"], "missing")

    def test_absent_battle_voice_directory_keeps_missing_rows(self):
        """Review R2 DRPG gap: an absent battle-voice directory must leave missing rows, not zero rows."""
        shutil.rmtree(self.src / "assetbundle")
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        self.assertIn("DRPG battle voices not found", out)
        rows = self.rows()
        self.assertEqual(rows["assetbundle/sounds/voice/battle/15/15_acb"], "missing")
        self.assertEqual(rows["assetbundle/sounds/voice/battle/15/15_awb"], "missing")

    def test_absent_sprite_directory_keeps_missing_rows(self):
        shutil.rmtree(self.src / "sprites")
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        self.assertIn("DRPG sprite PNGs not found", out)
        rows = self.rows()
        self.assertEqual(rows["sprites/Sprites/Standard/BattleFront/front15.png"], "missing")
        self.assertEqual(rows["sprites/Sprites/Standard/BattleFront/front16.png"], "missing")
        self.assertEqual(rows["looks.json"], "yes")

    def test_one_omitted_file_is_named(self):
        (self.src / "assetbundle/sounds/voice/battle/15/15_awb").write_bytes(b"awb15")
        (self.src / "sprites/Sprites/Standard/BattleFront/front16.png").write_bytes(b"png16")
        (self.src / "assetbundle/sounds/voice/battle/15/15_awb").unlink()
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        rows = self.rows()
        self.assertEqual(rows["assetbundle/sounds/voice/battle/15/15_awb"], "missing")
        self.assertEqual(rows["assetbundle/sounds/voice/battle/15/15_acb"], "yes")


class ManifestScopeTests(Sandboxed):
    """Review finding 5: scoped runs keep the entries of games they did not touch."""

    def setUp(self):
        super().setUp()
        self.d4 = self.tmp / "d4-game"
        make_d4(self.d4)
        switch = b"switch romfs SUBDATA bytes"
        self.rows = [("d4", rel, (self.d4 / rel).read_bytes(), "synthetic") for rel in prep.D4_FILES]
        self.rows.append(("d1c", "data/SUBDATA.DAT", switch, "d1c-switch-01004B100AF18000"))
        self.known = write_known(self.tmp, self.rows)
        self.dest = self.tmp / "Source"
        self.d1c = self.tmp / "romfs/data"
        self.d1c.mkdir(parents=True)
        (self.d1c / "SUBDATA.DAT").write_bytes(switch)

    def test_two_scoped_runs_keep_both_entries(self):
        code, out = run(["--only", "d4", "--d4", str(self.d4), "--dest", str(self.dest),
                         "--known", str(self.known)])
        self.assertEqual(code, 0, out)
        code, out = run(["--only", "d1c", "--d1c", str(self.tmp / "romfs"), "--dest", str(self.dest),
                         "--known", str(self.known)])
        self.assertEqual(code, 0, out)
        manifest = json.loads((self.dest / "manifest.json").read_text())
        self.assertEqual(set(manifest["games"]), {"d4", "d1c"})
        self.assertEqual(len(manifest["games"]["d4"]["files"]), len(prep.D4_FILES))
        self.assertTrue((self.dest / "d4/Data/DATA/ANM_HI.dat").is_file())


class MissingInputTests(Sandboxed):
    def test_missing_game_explains_how_to_get_it(self):
        code, out = run(["--only", "d1c", "--dest", str(self.tmp / "Source")])
        self.assertEqual(code, 1)
        self.assertIn("D1 Complete dump not supplied", out)
        self.assertIn("prep_source.py --d1c", out)

    def test_drpg_without_masters_is_a_problem(self):
        src = self.tmp / "drpg"
        (src / "sprites/Sprites/Standard/BattleFront").mkdir(parents=True)
        (src / "sprites/Sprites/Standard/BattleFront/front15.png").write_bytes(b"png")
        (src / "looks.json").write_bytes(b"{}")
        (src / "atlas-index.json").write_bytes(b"{}")
        voice = src / "assetbundle/sounds/voice/battle/15"
        voice.mkdir(parents=True)
        (voice / "15_acb").write_bytes(b"acb")
        known = write_known(self.tmp, [
            ("drpg", "looks.json", b"{}", "synthetic"),
            ("drpg", "atlas-index.json", b"{}", "synthetic"),
            ("drpg", "sprites/Sprites/Standard/BattleFront/front15.png", b"png", "synthetic"),
            ("drpg", "assetbundle/sounds/voice/battle/15/15_acb", b"acb", "synthetic"),
        ])
        code, out = run(["--only", "drpg", "--drpg", str(src), "--dest", str(self.tmp / "Source"),
                         "--known", str(known), "--json"])
        self.assertEqual(code, 1)
        self.assertIn("--drpg-masters", out)
        manifest = json.loads((self.tmp / "Source/manifest.json").read_text())
        rows = {f["path"]: f["verified"] for f in manifest["games"]["drpg"]["files"]}
        # Review R3: the four required master rows are planned even when the flag is omitted.
        for name in prep.DRPG_MASTERS:
            self.assertEqual(rows[f"masters/{name}.json"], "missing")
        self.assertEqual(rows["looks.json"], "yes")


class DrpgOmittedInputRowTests(Sandboxed):
    """Review R3: master and catalog rows survive an omitted flag, and recheck what is prepared on disk."""

    def setUp(self):
        super().setUp()
        self.src = self.tmp / "drpg"
        (self.src / "sprites/Sprites/Standard/BattleFront").mkdir(parents=True)
        (self.src / "sprites/Sprites/Standard/BattleFront/front15.png").write_bytes(b"png15")
        (self.src / "looks.json").write_bytes(b"{}")
        (self.src / "atlas-index.json").write_bytes(b"{}")
        voice = self.src / "assetbundle/sounds/voice/battle/15"
        voice.mkdir(parents=True)
        (voice / "15_acb").write_bytes(b"acb15")
        self.masters = self.tmp / "masters-input"
        self.masters.mkdir()
        self.master_bytes = {}
        for name in prep.DRPG_MASTERS:
            data = f"decoded master {name}".encode()
            (self.masters / f"{name}.json").write_bytes(data)
            self.master_bytes[f"masters/{name}.json"] = data
        self.catalog_bytes = b'{"catalogs": true}'
        self.catalogs = self.tmp / "d5-catalogs.json"
        self.catalogs.write_bytes(self.catalog_bytes)
        self.known = write_known(self.tmp, [
            ("drpg", "looks.json", b"{}", "synthetic"),
            ("drpg", "atlas-index.json", b"{}", "synthetic"),
            ("drpg", "sprites/Sprites/Standard/BattleFront/front15.png", b"png15", "synthetic"),
            ("drpg", "assetbundle/sounds/voice/battle/15/15_acb", b"acb15", "synthetic"),
            ("drpg", "d5-catalogs.json", self.catalog_bytes, "synthetic"),
            *[("drpg", rel, data, "synthetic") for rel, data in self.master_bytes.items()],
        ])
        self.known_doc = json.loads(self.known.read_text())
        self.dest = self.tmp / "Source"

    def args(self, *extra):
        return ["--only", "drpg", "--drpg", str(self.src), "--dest", str(self.dest),
                "--known", str(self.known), "--json", *extra]

    def rows(self):
        manifest = json.loads((self.dest / "manifest.json").read_text())
        return {f["path"]: f for f in manifest["games"]["drpg"]["files"]}

    def test_first_run_without_the_masters_flag_lists_the_required_rows(self):
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        rows = self.rows()
        for name in prep.DRPG_MASTERS:
            row = rows[f"masters/{name}.json"]
            self.assertEqual(row["verified"], "missing")
            self.assertIsNone(row["sha256"])  # nothing in the destination; never an input hash
            self.assertIn("--drpg-masters", row["note"])
        self.assertEqual(rows["d5-catalogs.json"]["verified"], "missing")
        self.assertEqual(rows["looks.json"]["verified"], "yes")
        # A consumer that only rechecks the manifest sees the omission instead of a complete source.
        states = {r["path"]: r["verified"] for r in sourcefolder.verify_manifest(self.dest, known=self.known_doc)}
        for name in prep.DRPG_MASTERS:
            self.assertEqual(states[f"masters/{name}.json"], "missing")

    def test_retry_without_the_masters_flag_keeps_the_prepared_rows(self):
        code, out = run(self.args("--drpg-masters", str(self.masters)))
        self.assertEqual(code, 0, out)
        code, out = run(self.args())  # same DRPG root, flag omitted
        self.assertEqual(code, 1, out)  # the unsupplied input is still a problem
        self.assertIn("--drpg-masters", out)
        rows = self.rows()
        for name in prep.DRPG_MASTERS:
            rel = f"masters/{name}.json"
            self.assertEqual(rows[rel]["verified"], "yes")
            self.assertEqual(rows[rel]["sha256"], sha(self.master_bytes[rel]))
            self.assertIn("kept the prepared copy", rows[rel]["note"])
            self.assertEqual((self.dest / "drpg" / rel).read_bytes(), self.master_bytes[rel])
        states = {r["path"]: r["verified"] for r in sourcefolder.verify_manifest(self.dest, known=self.known_doc)}
        for name in prep.DRPG_MASTERS:
            self.assertEqual(states[f"masters/{name}.json"], "yes")

    def test_retry_without_the_catalogs_flag_keeps_the_prepared_row(self):
        code, out = run(self.args("--drpg-masters", str(self.masters), "--drpg-catalogs", str(self.catalogs)))
        self.assertEqual(code, 0, out)
        code, out = run(self.args("--drpg-masters", str(self.masters)))  # catalog flag omitted
        self.assertEqual(code, 0, out)
        row = self.rows()["d5-catalogs.json"]
        self.assertEqual(row["verified"], "yes")
        self.assertEqual(row["sha256"], sha(self.catalog_bytes))
        self.assertIn("kept the prepared copy", row["note"])


class DrpgIndexMissingTests(Sandboxed):
    """Review R4: a supplied DRPG folder whose index is missing still plans the required master and catalog rows.

    The fallback that keeps prepared rows of an unavailable input, and a first run with an unrecognized folder, both
    used to write no DRPG file rows at all, so ``verify_manifest()`` could call the source complete while a required
    master was missing.
    """

    def setUp(self):
        super().setUp()
        self.src = self.tmp / "drpg"  # sprites and voices present, looks.json absent
        (self.src / "sprites/Sprites/Standard/BattleFront").mkdir(parents=True)
        (self.src / "sprites/Sprites/Standard/BattleFront/front15.png").write_bytes(b"png15")
        voice = self.src / "assetbundle/sounds/voice/battle/15"
        voice.mkdir(parents=True)
        (voice / "15_acb").write_bytes(b"acb15")
        self.masters = self.tmp / "masters-input"
        self.masters.mkdir()
        self.master_bytes = {}
        for name in prep.DRPG_MASTERS:
            data = f"decoded master {name}".encode()
            (self.masters / f"{name}.json").write_bytes(data)
            self.master_bytes[f"masters/{name}.json"] = data
        self.catalog = self.tmp / "d5-catalogs.json"
        self.catalog.write_bytes(b'{"catalogs": true}')
        self.prepared = {
            "looks.json": b"{}",
            "atlas-index.json": b"{}",
            "sprites/Sprites/Standard/BattleFront/front15.png": b"png15",
            "assetbundle/sounds/voice/battle/15/15_acb": b"acb15",
        }
        self.known = write_known(self.tmp, [
            *[("drpg", rel, data, "synthetic") for rel, data in self.prepared.items()],
            *[("drpg", rel, data, "synthetic") for rel, data in self.master_bytes.items()],
            ("drpg", "d5-catalogs.json", self.catalog.read_bytes(), "synthetic"),
        ])
        self.known_doc = json.loads(self.known.read_text())
        self.dest = self.tmp / "Source"
        # A prior manifest that lists the prepared index/sprite/voice rows but no master or catalog rows.
        prior_files = []
        for rel, data in self.prepared.items():
            path = self.dest / "drpg" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            prior_files.append({"path": rel, "size": len(data), "sha256": sha(data),
                                "known_build": "synthetic", "verified": "yes"})
        sourcefolder.write_manifest(self.dest, {"drpg": {
            "edition": "synthetic", "origin": "user-supplied", "root": "drpg", "supplied": True,
            "files": prior_files}})

    def args(self, *extra):
        return ["--only", "drpg", "--drpg", str(self.src), "--dest", str(self.dest),
                "--known", str(self.known), "--json", *extra]

    def rows(self):
        manifest = json.loads((self.dest / "manifest.json").read_text())
        return {f["path"]: f for f in manifest["games"]["drpg"]["files"]}

    def test_first_run_with_a_missing_index_still_lists_the_required_masters(self):
        shutil.rmtree(self.dest / "drpg")
        (self.dest / "manifest.json").unlink()
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        self.assertIn("looks.json", out)  # the input diagnostic is kept
        rows = self.rows()
        for name in prep.DRPG_MASTERS:
            row = rows[f"masters/{name}.json"]
            self.assertEqual(row["verified"], "missing")
            self.assertIsNone(row["sha256"])  # never the input's hash
        self.assertEqual(rows["d5-catalogs.json"]["verified"], "missing")
        states = {r["path"]: r["verified"] for r in sourcefolder.verify_manifest(self.dest, known=self.known_doc)}
        for name in prep.DRPG_MASTERS:
            self.assertEqual(states[f"masters/{name}.json"], "missing")

    def test_prior_manifest_without_master_rows_is_completed_with_missing_rows(self):
        code, out = run(self.args())
        self.assertEqual(code, 1, out)
        self.assertIn("looks.json", out)
        rows = self.rows()
        for rel, data in self.prepared.items():  # prepared rows kept and rechecked
            self.assertEqual(rows[rel]["verified"], "yes")
            self.assertEqual(rows[rel]["sha256"], sha(data))
        for name in prep.DRPG_MASTERS:  # required rows now present, exactly once
            rel = f"masters/{name}.json"
            self.assertEqual(rows[rel]["verified"], "missing")
            self.assertEqual([r["path"] for r in rows.values()].count(rel), 1)
        self.assertEqual(rows["d5-catalogs.json"]["verified"], "missing")
        states = {r["path"]: r["verified"] for r in sourcefolder.verify_manifest(self.dest, known=self.known_doc)}
        for name in prep.DRPG_MASTERS:
            self.assertEqual(states[f"masters/{name}.json"], "missing")
        self.assertFalse(all(state == "yes" for state in states.values()))

    def test_supplied_masters_and_catalog_are_placed_without_the_index(self):
        code, out = run(self.args("--drpg-masters", str(self.masters), "--drpg-catalogs", str(self.catalog)))
        self.assertEqual(code, 1, out)  # the missing index still keeps the run incomplete
        rows = self.rows()
        for rel, data in self.master_bytes.items():
            self.assertEqual(rows[rel]["verified"], "yes")
            self.assertEqual((self.dest / "drpg" / rel).read_bytes(), data)
        self.assertEqual(rows["d5-catalogs.json"]["verified"], "yes")

    def test_retry_keeps_prepared_masters_and_catalog_without_the_flags(self):
        self.assertEqual(run(self.args("--drpg-masters", str(self.masters),
                                       "--drpg-catalogs", str(self.catalog)))[0], 1)
        code, out = run(self.args())  # index still missing, both flags omitted
        self.assertEqual(code, 1, out)
        self.assertIn("--drpg-masters", out)  # still a problem, not silently accepted
        rows = self.rows()
        for rel, data in self.master_bytes.items():
            self.assertEqual(rows[rel]["verified"], "yes")
            self.assertEqual(rows[rel]["sha256"], sha(data))
            self.assertIn("kept the prepared copy", rows[rel]["note"])
        self.assertEqual(rows["d5-catalogs.json"]["verified"], "yes")


if __name__ == "__main__":
    unittest.main()
