"""POOLLEAK1: on-demand effect loads must not leak vertex-arena records (d5lib.fxarena, d5fx.inc.c).

The exe tests read the clean D5 exe from Disgaea Source/ at test time and skip when it is absent (nothing of the game
is stored here); they run the game's own build step and release in Unicorn.
"""
import os
import unittest
from pathlib import Path

from d5lib import fxarena

SOURCE = Path(os.environ.get("D5_SOURCE_DIR", "/Volumes/Data/Projects/D5/Disgaea Source"))
D5_EXE = SOURCE / "Disgaea 5 Complete (Steam 803600)/disgaea5.exe"
NATIVE = Path(__file__).resolve().parents[1] / "d5lib/native/d5fx.inc.c"

OLD_FX_LOAD = """
static int fx_load(fx_entry *c, fx_model *m) {
    e->data = ((void *(*)(void *, int))G(FX_LOAD_VA))(buf, slot);
    free(buf);
    ((void (*)(void *, int))G(FX_FINISH_VA))(*(void **)G(FX_MGR_VA), slot);
    e->ref = 1;
    return 1;
}
"""


class RuntimePolicy(unittest.TestCase):
    def test_runtime_builds_once(self):
        self.assertEqual(fxarena.runtime_policy(NATIVE.read_text(encoding="utf-8")), "once")

    def test_old_sequence_is_twice(self):
        self.assertEqual(fxarena.runtime_policy(OLD_FX_LOAD), "twice")


class Session(unittest.TestCase):
    LISTS = {e: [(e, i) for i in range(30)] for e in range(80)}
    CASTS = [e % 80 for e in range(400)]

    def test_twice_orphans_one_record_per_load(self):
        r = fxarena.simulate(self.CASTS, self.LISTS, "twice", baseline=50)
        self.assertEqual(r["orphans"], r["loads"])
        self.assertIsNotNone(r["exhausted_at"])

    def test_once_is_flat(self):
        r = fxarena.simulate(self.CASTS, self.LISTS, "once", baseline=50)
        self.assertEqual(r["orphans"], 0)
        self.assertIsNone(r["exhausted_at"])
        self.assertEqual(max(r["used"]), 50 + fxarena.CACHE_ROOM)


@unittest.skipUnless(D5_EXE.is_file(), "clean D5 exe not present")
class GameCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = D5_EXE.read_bytes()
        cls.facts = fxarena.exe_facts(cls.exe)

    def test_loader_builds_and_release_frees(self):
        f = self.facts
        self.assertEqual(f["loader_builds"], 1)
        self.assertTrue(f["loader_build_unconditional"])
        self.assertEqual(f["release_frees"], 1)
        self.assertTrue(f["release_reads_slot_block"])

    def test_two_builds_exhaust_the_arena(self):
        r = fxarena.emulate(self.exe, 1100, extra=True, facts=self.facts)
        self.assertEqual(r["used"][:3], [1, 2, 3])
        self.assertIsNotNone(r["fault"])
        rip, addr, _ = r["fault"]
        self.assertEqual(addr, 0)                                   # the write through NULL
        self.assertTrue(self.facts["record_take"] <= rip < self.facts["record_take"] + 0x70)
        self.assertEqual(r["cycles"], fxarena.ARENA_RECORDS - 1)

    def test_one_build_is_flat(self):
        r = fxarena.emulate(self.exe, 1100, extra=False, facts=self.facts)
        self.assertIsNone(r["fault"])
        self.assertEqual(set(r["used"]), {0})


if __name__ == "__main__":
    unittest.main()
