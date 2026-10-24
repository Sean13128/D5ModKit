import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from d5lib import modsys
from d5gui import workspace


class GameStampTests(unittest.TestCase):
    def test_stamp_changes_when_game_files_change(self):
        with tempfile.TemporaryDirectory() as game, tempfile.TemporaryDirectory() as kit:
            os.makedirs(os.path.join(game, "Data", "Anime"))
            for p in ("disgaea5.exe", os.path.join("Data", "Anime", "ANM_HI_EN.dat")):
                with open(os.path.join(game, p), "wb") as f:
                    f.write(b"x")
            inst = modsys.Installer(game, kit, log=lambda *_: None)
            before = inst.game_stamp()
            with open(os.path.join(game, "Data", ".DS_Store"), "wb") as f:     # Finder's files don't count
                f.write(b"y")
            self.assertEqual(inst.game_stamp(), before)
            with open(os.path.join(game, "Data", "Anime", "ANM_HI_EN.dat"), "wb") as f:
                f.write(b"xy")
            self.assertNotEqual(inst.game_stamp(), before)


class InstallSkipTests(unittest.TestCase):
    def _ws(self, info, stamp="s1"):
        installer = SimpleNamespace(modified_archives=lambda: ["EXE/disgaea5.exe"], installed_info=lambda: info,
                                    game_stamp=lambda: stamp, install=Mock(), set_installed=Mock())
        return SimpleNamespace(is_game_running=lambda: False, profile=SimpleNamespace(separate_saves=False),
                               installer=installer, mods_signature=lambda fresh=False: "sig",
                               mods=SimpleNamespace(profile=SimpleNamespace(id="p", name="P"),
                                                    enabled_mods=lambda: []),
                               log=Mock(), sync_saves=Mock(), fs=None)

    def _install(self, ws):
        with patch("d5lib.gamecheck.errors", return_value=[]), patch.object(modsys, "build") as build:
            n = workspace.Workspace.build_and_install(ws)
        return n, build

    def test_nothing_changed_skips_the_build(self):
        ws = self._ws({"signature": "sig", "profile": "p", "game": "s1"})
        n, build = self._install(ws)
        self.assertEqual(n, 0)
        build.assert_not_called()
        ws.sync_saves.assert_called_once()

    def test_any_difference_builds(self):
        for info, stamp in [({"signature": "old", "profile": "p", "game": "s1"}, "s1"),
                            ({"signature": "sig", "profile": "q", "game": "s1"}, "s1"),
                            ({"signature": "sig", "profile": "p", "game": "s1"}, "s2"),
                            ({"signature": "sig", "profile": "p"}, "s1")]:          # installed before the stamp
            with self.subTest(info=info, stamp=stamp):
                n, build = self._install(self._ws(info, stamp))
                build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
