"""d5lib.sourcefolder: resolver order, SourceMissing, known-good table and manifest (SOURCEPREP2)."""
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from d5lib import sourcefolder


class ResolverTests(unittest.TestCase):
    def test_env_wins_over_settings_and_default(self):
        with mock.patch.object(sourcefolder.paths, "kit_setting", return_value="/from/settings"), \
                mock.patch.dict(os.environ, {sourcefolder.ENV: "/from/env"}):
            self.assertEqual(sourcefolder.source_dir(), Path("/from/env"))

    def test_settings_when_env_unset(self):
        env = {k: v for k, v in os.environ.items() if k != sourcefolder.ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sourcefolder.paths, "kit_setting", return_value="/from/settings"):
            self.assertEqual(sourcefolder.source_dir(), Path("/from/settings"))

    def test_default_is_game_relative_when_the_game_is_found(self):
        """One canonical folder (Sean 2026-11-18) shared by prep and the resolver, even off the game folder."""
        env = {k: v for k, v in os.environ.items() if k != sourcefolder.ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sourcefolder.paths, "kit_setting", return_value=None), \
                mock.patch.object(sourcefolder.paths, "game_dir", return_value="/games/Disgaea 5 Complete"):
            self.assertEqual(sourcefolder.source_dir(),
                             Path("/games/Disgaea 5 Complete") / "D5ModKit" / "Source")

    def test_kit_source_fallback_only_without_a_game(self):
        env = {k: v for k, v in os.environ.items() if k != sourcefolder.ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sourcefolder.paths, "kit_setting", return_value=None), \
                mock.patch.object(sourcefolder.paths, "game_dir", return_value=None):
            self.assertEqual(sourcefolder.source_dir(), Path(sourcefolder.paths.KIT_DIR) / "Source")

    def test_source_path_and_have(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            (folder / "d1c/data").mkdir(parents=True)
            (folder / "d1c/data/SUBDATA.DAT").write_bytes(b"x")
            with mock.patch.dict(os.environ, {sourcefolder.ENV: t}):
                self.assertTrue(sourcefolder.have("d1c", "data/SUBDATA.DAT"))
                self.assertFalse(sourcefolder.have("d1c", "data/DATA.DAT"))
                self.assertEqual(sourcefolder.source_path("d1c", "data/SUBDATA.DAT"),
                                 folder / "d1c/data/SUBDATA.DAT")

    def test_missing_names_the_prep_step(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {sourcefolder.ENV: t}):
            with self.assertRaises(sourcefolder.SourceMissing) as ctx:
                sourcefolder.source_path("dd2", "PS3_GAME/USRDIR/Data/START_4.dat")
            message = str(ctx.exception)
            self.assertIn("dd2/PS3_GAME/USRDIR/Data/START_4.dat", message)
            self.assertIn("prep_source.py", message)
            self.assertIn("--dd2", message)


class SteamDiscoveryTests(unittest.TestCase):
    """d5lib.paths finds apps on macOS/Linux roots and their libraryfolders.vdf (used by prep and the resolver)."""

    def test_platform_root_and_vdf_library(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "Steam"
            (root / "steamapps/common").mkdir(parents=True)
            library = Path(t) / "SteamLibrary"
            (library / "steamapps/common/Disgaea 4 Complete+").mkdir(parents=True)
            (root / "steamapps/libraryfolders.vdf").write_text(
                '"libraryfolders" { "0" { "path" "%s" } }' % library, encoding="utf-8")
            with mock.patch.object(sourcefolder.paths, "steam_libraries", return_value=[]), \
                    mock.patch.object(sourcefolder.paths, "platform_steam_roots", return_value=[str(root)]):
                found = sourcefolder.paths.steam_app(1233880, "Disgaea 4 Complete+")
            self.assertEqual(Path(found), library / "steamapps/common/Disgaea 4 Complete+")


class KnownTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.known = sourcefolder.load_known()

    def test_schema_and_games(self):
        self.assertEqual(self.known["schema"], sourcefolder.KNOWN_SCHEMA)
        self.assertEqual(set(self.known["games"]), set(sourcefolder.GAMES))

    def test_expected_file_counts(self):
        counts = {g: len(v["files"]) for g, v in self.known["games"].items()}
        self.assertEqual(counts["d4"], 8)
        self.assertEqual(counts["d1c"], 1)
        self.assertEqual(counts["d1pc"], 2)
        self.assertEqual(counts["dd2"], 16)
        self.assertEqual(counts["drpg"], 3820)       # +1: the optional masters/characterclassname.json (TEXTHASH-DRPG)

    def test_rows_are_well_formed(self):
        hex64 = re.compile(r"^[0-9a-f]{64}$")
        for game, entry in self.known["games"].items():
            for rel, rows in entry["files"].items():
                self.assertTrue(rows, f"{game}/{rel} has no accepted build")
                for row in rows:
                    self.assertGreaterEqual(int(row["size"]), 0, f"{game}/{rel}")
                    self.assertRegex(row["sha256"], hex64, f"{game}/{rel}")
                    self.assertTrue(row["build"], f"{game}/{rel}")

    def test_d1c_has_switch_and_ps4_builds(self):
        builds = {r["build"] for r in self.known["games"]["d1c"]["files"]["data/SUBDATA.DAT"]}
        self.assertEqual(builds, {"d1c-switch-01004B100AF18000", "d1c-ps4-CUSA13171"})

    def test_d4_wf_dat_is_listed_for_hd_faces(self):
        self.assertIn("Data/DATA/WF.dat", self.known["games"]["d4"]["files"])

    def test_matches_disgaea_source_sums_when_present(self):
        """Every original-game row equals the recorded Disgaea Source SHA-256 (skipped off Sean's machine)."""
        root = os.environ.get("D5_DISGAEA_SOURCE")
        if not root:
            self.skipTest("set D5_DISGAEA_SOURCE to the Disgaea Source folder")
        root = Path(root)
        prefixes = {
            "d4": "Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+/",
            "d1c": "Disgaea 1 Complete Switch (01004B100AF18000)/extracted/romfs/",
            "d1pc": "Disgaea 1 PC (Steam 405900)/",
            "dd2": "Disgaea D2 PS3 (BLUS31313)/disc/Disgaea D2 A Brighter Darkness - [BLUS31313]/",
        }
        sums = {}
        for line in (root / "SHA256SUMS-20261102.txt").read_text().splitlines():
            sha, rel = line.split(None, 1)
            sums[rel.strip().lstrip("./")] = sha
        checked = 0
        for game, prefix in prefixes.items():
            for rel, rows in self.known["games"][game]["files"].items():
                for row in rows:
                    if row["build"] not in ("d4-steam-1233880", "d1c-switch-01004B100AF18000",
                                            "d1pc-steam-405900", "dd2-ps3-BLUS31313"):
                        continue
                    key = prefix + rel
                    self.assertEqual(row["sha256"], sums[key], f"{game}/{rel}")
                    checked += 1
        self.assertEqual(checked, 8 + 1 + 2 + 16)


class VerifyAndManifestTests(unittest.TestCase):
    def known(self):
        return {"schema": sourcefolder.KNOWN_SCHEMA,
                "games": {"d4": {"files": {"Data/DATA/ANM_HI.dat": [
                    {"size": 3, "sha256": hashlib.sha256(b"abc").hexdigest(), "build": "test"}]}}}}

    def test_verify_file_yes_no_unknown(self):
        known = self.known()
        yes = sourcefolder.verify_file("d4", "Data/DATA/ANM_HI.dat", 3, hashlib.sha256(b"abc").hexdigest(), known)
        self.assertEqual(yes[0], "yes")
        self.assertEqual(yes[1], "test")
        no = sourcefolder.verify_file("d4", "Data/DATA/ANM_HI.dat", 3, hashlib.sha256(b"abd").hexdigest(), known)
        self.assertEqual(no[0], "no")
        unknown = sourcefolder.verify_file("d4", "Data/DATA/WF.dat", 3, hashlib.sha256(b"abc").hexdigest(), known)
        self.assertEqual(unknown[0], "unknown")

    def test_manifest_round_trip_and_drift(self):
        with tempfile.TemporaryDirectory() as t:
            dest = Path(t)
            (dest / "d4/Data/DATA").mkdir(parents=True)
            (dest / "d4/Data/DATA/ANM_HI.dat").write_bytes(b"abc")
            games = {"d4": {"edition": "test", "origin": "user-supplied", "root": "d4", "supplied": True,
                            "files": [{"path": "Data/DATA/ANM_HI.dat", "size": 3,
                                       "sha256": hashlib.sha256(b"abc").hexdigest(),
                                       "known_build": "test", "verified": "yes"}]}}
            path = sourcefolder.write_manifest(dest, games, tool="test")
            self.assertTrue(path.is_file())
            self.assertEqual(sourcefolder.read_manifest(dest)["games"], games)
            self.assertEqual([r["verified"] for r in sourcefolder.verify_manifest(dest, self.known())], ["yes"])
            (dest / "d4/Data/DATA/ANM_HI.dat").write_bytes(b"abd")
            self.assertEqual([r["verified"] for r in sourcefolder.verify_manifest(dest, self.known())], ["no"])
            (dest / "d4/Data/DATA/ANM_HI.dat").unlink()
            self.assertEqual([r["verified"] for r in sourcefolder.verify_manifest(dest, self.known())], ["missing"])

    def test_bad_manifest_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "manifest.json").write_text(json.dumps({"schema": "other"}))
            with self.assertRaises(ValueError):
                sourcefolder.read_manifest(t)

    def test_non_manifest_json_is_rejected(self):
        """Review R5: a list, a non-object games value and broken JSON are all "not a D5 source manifest"."""
        for text in ('["a"]', '{"schema": "d5-source-manifest/1", "games": ["a"]}', "{not json"):
            with tempfile.TemporaryDirectory() as t:
                (Path(t) / "manifest.json").write_text(text)
                with self.assertRaises(ValueError):
                    sourcefolder.read_manifest(t)

    def test_write_manifest_refuses_to_replace_a_foreign_file(self):
        """Review R5: the library guard keeps another tool's manifest.json byte-identical."""
        with tempfile.TemporaryDirectory() as t:
            dest = Path(t)
            path = dest / "manifest.json"
            data = b'{"schema": "local-export/1", "files": ["keep me"]}'
            path.write_bytes(data)
            with self.assertRaises(sourcefolder.ForeignManifest):
                sourcefolder.write_manifest(dest, {"d4": {}})
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual([p.name for p in dest.iterdir()], ["manifest.json"])

    def test_write_manifest_replaces_a_valid_d5_manifest(self):
        with tempfile.TemporaryDirectory() as t:
            dest = Path(t)
            sourcefolder.write_manifest(dest, {"d4": {"files": []}})
            sourcefolder.write_manifest(dest, {"drpg": {"files": []}})
            self.assertEqual(list(sourcefolder.read_manifest(dest)["games"]), ["drpg"])


if __name__ == "__main__":
    unittest.main()
