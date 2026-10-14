import os
import random
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from d5lib import lzs, lzs_compress, lzs_native
from d5gui import workspace


class NativeCodecTests(unittest.TestCase):
    def test_cross_decode_edge_cases(self):
        self.assertTrue(lzs_native.available(), 'native codec must build/load on this test host')
        rng = random.Random(803600)
        samples = [b'', b'x', b'\0' * 8192, bytes(range(256)) * 32,
                   bytes(rng.randrange(256) for _ in range(8192))]
        samples += [bytes(rng.randrange(8) for _ in range(n))
                    for n in [2, 3, 4, 16, 253, 254, 255, 256, 4096]]
        for sample in samples:
            with self.subTest(size=len(sample)):
                native = lzs_native.compress(sample)
                self.assertEqual(lzs.decompress(native, native=False), sample)
                self.assertEqual(lzs_native.decompress(native), sample)
                python = lzs_compress.compress(sample, native=False)
                self.assertEqual(lzs_native.decompress(python), sample)


@unittest.skipUnless(sys.platform == 'darwin', 'Mac routing')
class MacRoutingTests(unittest.TestCase):
    def test_wine_executable_with_spaces(self):
        output = 'S:\\steamapps\\common\\Disgaea 5 Complete\\disgaea5.exe\n/bin/sh\n'
        with patch.object(workspace.subprocess, 'run', return_value=Mock(stdout=output)):
            self.assertTrue(workspace.game_running())
        with patch.object(workspace.subprocess, 'run', return_value=Mock(stdout='C:\\Steam\\steam.exe\n/bin/sh\n')):
            self.assertFalse(workspace.game_running())

    def test_unknown_process_state_fails(self):
        with patch.object(workspace.subprocess, 'run', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(RuntimeError, 'Could not check'):
                workspace.game_running()

    def test_play_uses_steam(self):
        ws = SimpleNamespace(sync_saves=Mock(), installed_profile=lambda: None)
        with patch.object(workspace.subprocess, 'run') as launch:
            workspace.Workspace.launch_game(ws)
            launch.assert_called_once_with(['/usr/bin/open', 'steam://run/803600'], check=True)

    def test_shared_saves_are_not_guessed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(workspace.Workspace.sync_saves(SimpleNamespace(), None))
            with self.assertRaisesRegex(RuntimeError, 'APPDATA'):
                workspace.Workspace.sync_saves(SimpleNamespace(), SimpleNamespace(separate_saves=True))

    def test_separate_save_preflight_precedes_install(self):
        ws = SimpleNamespace(is_game_running=lambda: False, profile=SimpleNamespace(separate_saves=True))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'APPDATA'):
                workspace.Workspace.build_and_install(ws)

    def test_running_game_precedes_install(self):
        ws = SimpleNamespace(is_game_running=lambda: True)
        with self.assertRaisesRegex(RuntimeError, 'Close Disgaea'):
            workspace.Workspace.build_and_install(ws)


if __name__ == '__main__':
    unittest.main()
