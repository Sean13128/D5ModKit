"""D1C-FIX1.1: every importer resolves the installed-mods reference through D5_INSTALLED_MODS."""
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class InstalledModsRoot(unittest.TestCase):
    def test_d1c_modules_read_no_installed_root_of_their_own(self):
        """SOURCEPREP4-D1C: the D1C importer gets an installed pack only through the build context
        (``--installed-reference``); it no longer resolves D5_INSTALLED_MODS itself."""
        with mock.patch.dict(os.environ, {'D5_INSTALLED_MODS': '/tmp/held-mods'}):
            from d5lib.importers import d1c, d1c_art
            importlib.reload(d1c_art)
            importlib.reload(d1c)
            self.assertFalse(hasattr(d1c, 'INSTALLED_MODS'))
            self.assertFalse(hasattr(d1c_art, 'INSTALLED'))
        importlib.reload(d1c_art)
        importlib.reload(d1c)


if __name__ == '__main__':
    unittest.main()


class BuildsAreSerial(unittest.TestCase):
    """D1C-FIX1.2/1.3: the D1C builders share process globals, so --jobs 2 must not overlap builds."""

    def test_concurrent_builds_do_not_overlap(self):
        import threading
        import time
        from d5lib.importers import d1c
        imp = d1c.Importer.__new__(d1c.Importer)
        live, peak = [0], [0]

        def fake(entry, out_dir, ctx=None):
            live[0] += 1
            peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            live[0] -= 1
            return {}
        imp._build = fake
        threads = [threading.Thread(target=imp.build, args=(None, None)) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(peak[0], 1)
