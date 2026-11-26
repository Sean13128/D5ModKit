"""Site ledger (d5lib.exemap): every exe patch range recorded with its owner, overlaps refused by name."""
import hashlib
import os
import unittest
from unittest import mock

STEAM = os.environ.get("D5_CLEAN_GAME", "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)")
EXE = os.path.join(STEAM, "disgaea5.exe")
# a DISPOSABLE copy of the MAIN profile and its mods (never the installed kit: the outfit finalizer writes metadata into
# mods).  Build it as in SITELEDGER3-REPORT.md; the approval store is seeded inside it by the test itself.
INSTALLED = os.environ.get("D5_MAIN_FIXTURE", "")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        from d5lib import exemap
        exemap.reset_ledger()
        self.exemap, self._active = exemap, exemap.ACTIVE
        self.addCleanup(exemap.use, self._active)

    def test_overlap_by_other_owner_raises(self):
        e = self.exemap
        with e.owner("a"):
            e.claim(0x1000, 6, "first")
        with e.owner("b"), self.assertRaises(e.SiteClash) as cm:
            e.claim(0x1004, 2, "second")
        m = str(cm.exception)
        self.assertTrue("a" in m and "b" in m and "0x1004" in m, m)
        self.assertIsInstance(cm.exception, ValueError)

    def test_same_owner_same_range_ok(self):
        e = self.exemap
        with e.owner("a"):
            e.claim(0x1000, 6, "x")
            e.claim(0x1000, 6, "x")
        self.assertEqual(len(e.LEDGER), 1)

    def test_adjacent_ranges_ok(self):
        e = self.exemap
        with e.owner("a"):
            e.claim(0x1000, 4, "x")
        with e.owner("b"):
            e.claim(0x1004, 4, "y")

    def test_reset_clears(self):
        e = self.exemap
        e.claim(0x1000, 6, "x")
        e.reset_ledger()
        self.assertEqual(e.LEDGER, [])

    def test_release_drops_owner(self):
        e = self.exemap
        with e.owner("a"):
            e.claim(0x1000, 6, "x")
        with e.owner("b"):
            e.claim(0x2000, 2, "y")
        e.release("a")
        self.assertEqual([x["owner"] for x in e.LEDGER], ["b"])
        with e.owner("c"):
            e.claim(0x1000, 6, "z")

    @unittest.skipUnless(os.path.exists(EXE), "needs the clean Disgaea 5 exe")
    def test_site_claims_written_range(self):
        from d5lib import exemap
        from d5lib.exepatch import pefile
        exemap.use(exemap.Translator(exemap.KNOWN_SHA1))
        pe = pefile.PE(data=open(EXE, "rb").read(), fast_load=True)
        with exemap.owner("x"):
            exemap.site(pe, exemap.Native(0x1401AF645), bytes.fromhex("0F84DE010000"), "ally steal site")
        self.assertEqual(exemap.LEDGER, [{"start": 0x1401AF645, "end": 0x1401AF64B, "owner": "x",
                                          "what": "ally steal site"}])

    @unittest.skipUnless(os.path.exists(EXE), "needs the clean Disgaea 5 exe")
    def test_outfit_build_claims_only_what_it_writes(self):
        """checking the face/layer/gfx sites must not claim them: an outfit build without those features writes (and
        so claims) only the dispatch, open and hub hooks"""
        from d5lib import exemap, exepatch
        exe = open(EXE, "rb").read()
        exemap.use(exemap.translator_for(exe))
        with exemap.owner("outfits"):
            out = exepatch.build_outfit_patch(exe, [(0, 470, 1001)], 40001, 40002)
        claimed = sorted((e["start"], e["end"]) for e in exemap.LEDGER)
        written = [i for i in range(len(exe)) if exe[i] != out[i] and i < len(exe)]
        pe = exepatch.pefile.PE(data=exe, fast_load=True)
        want = sorted((exemap.ACTIVE(va), exemap.ACTIVE(va) + len(orig)) for va, orig in ((exepatch.OPEN_VA, exepatch.OPEN_ORIG),
                                                            (exepatch.DISPATCH_VA, exepatch.DISPATCH_ORIG),
                                                            (exepatch.HUB_VA, exepatch.HUB_ORIG)))
        self.assertEqual(claimed, want)
        for va in (exepatch.LAYER_VA, exepatch.FACE_A_VA, exepatch.FACE_B_VA, exepatch.GFX_VA):
            self.assertFalse(any(s < exemap.ACTIVE(va) + 1 and exemap.ACTIVE(va) < e for s, e in claimed))
        # every changed byte of the original image lies inside a claimed range
        for i in written:
            rva = pe.get_rva_from_offset(i)
            if rva is not None and any(s.VirtualAddress <= rva < s.VirtualAddress + s.SizeOfRawData
                                       and not s.Name.startswith(b".d5") for s in pe.sections):
                self.assertTrue(any(s <= rva + exepatch.IMAGE_BASE < e for s, e in claimed), hex(rva))

    def test_site_without_claim_checks_only(self):
        from d5lib import exemap

        class PE:
            @staticmethod
            def get_data(rva, n):
                return b"\x90" * n
        exemap.use(exemap.Translator(exemap.KNOWN_SHA1))
        with exemap.owner("x"):
            exemap.site(PE, exemap.Native(0x140001000), b"\x90\x90", "check", claim=False)
            self.assertEqual(exemap.LEDGER, [])
            exemap.site(PE, exemap.Native(0x140001000), b"\x90\x90", "claimed")
        self.assertEqual(len(exemap.LEDGER), 1)


class ReservationTests(unittest.TestCase):
    def setUp(self):
        from d5lib import exemap
        exemap.reset_ledger(reserved=True)
        self.exemap = exemap

    def tearDown(self):
        self.exemap.reset_ledger(reserved=True)

    def test_reservation_survives_outfit_reset(self):
        e = self.exemap
        e.reserve(0x1000, 8, "R")
        e.reset_ledger()
        self.assertEqual(len(e.RESERVED), 1)
        e.reset_ledger(reserved=True)
        self.assertEqual(e.RESERVED, [])

    def test_claim_on_reserved_site_clashes(self):
        e = self.exemap
        e.reserve(0x1000, 8, "R")
        with e.owner("k"), self.assertRaises(e.SiteClash) as cm:
            e.claim(0x1004, 2, "x")
        self.assertIn("R", str(cm.exception))
        with e.owner("R"):
            e.claim(0x1004, 2, "his own")


class SkipTests(unittest.TestCase):
    def test_clash_is_skipped_named_and_released(self):
        from d5lib import exemap, modsys

        class Ctx:
            log = staticmethod(lambda *_: None)
        ctx = Ctx()
        exemap.reset_ledger()
        with exemap.owner("first"):
            modsys._tolerant(ctx, "first", lambda: exemap.claim(0x1000, 6, "ok"))

        def second():
            exemap.claim(0x2000, 4, "own")                 # a partial claim ...
            exemap.claim(0x1002, 2, "clash")               # ... then the clash
        with exemap.owner("second"):
            modsys._tolerant(ctx, "second", second)
        self.assertEqual([e["owner"] for e in exemap.LEDGER], ["first"])
        (what, why), = ctx.skipped_features
        self.assertEqual(what, "second")
        self.assertIn("exe patch clash", why)
        self.assertIn("first", why)
        exemap.reset_ledger()

    def test_unexpected_exe_version_releases_partial_claims(self):
        from d5lib import exemap, modsys

        class Ctx:
            log = staticmethod(lambda *_: None)
        ctx = Ctx()
        exemap.reset_ledger()

        def f():
            exemap.claim(0x3000, 4, "a")
            raise ValueError("unexpected exe version: x")
        with exemap.owner("f"):
            modsys._tolerant(ctx, "f", f)
        self.assertEqual(exemap.LEDGER, [])
        self.assertEqual(len(ctx.skipped_features), 1)

    @unittest.skipUnless(os.path.exists(EXE), "needs the clean Disgaea 5 exe")
    def test_add_code_section_claims_its_patch_ranges(self):
        from d5lib import exemap, exepatch
        old = exemap.ACTIVE
        exemap.use(exemap.Translator(exemap.KNOWN_SHA1))
        try:
            exemap.reset_ledger()
            exe = open(EXE, "rb").read()
            va, orig = 0x1401AF645, bytes.fromhex("0F84DE010000")
            with exemap.owner("t"):
                exepatch.add_code_section(exe, b".d5tt", b"\xC3" * 4, [(va, orig, 0x140000000, 0xE9)])
            self.assertEqual([(e["start"], e["end"], e["owner"]) for e in exemap.LEDGER], [(va, va + 6, "t")])
            with exemap.owner("u"), self.assertRaises(exemap.SiteClash):
                exepatch.add_code_section(exe, b".d5tu", b"\xC3" * 4, [(va + 2, orig[2:], 0x140000000, 0xE9)])
        finally:
            exemap.reset_ledger()
            exemap.use(old)


def _main_mods():
    """MAIN's enabled mods, read from the disposable fixture (its Ally_Steal is the converted Builds copy: the installed
    copy is only converted at the live install step)"""
    from d5lib.modsys import ModManager
    mods = ModManager(INSTALLED, profile="MAIN").enabled_mods()
    assert all(os.path.abspath(m.folder).startswith(INSTALLED) for m in mods), "fixture only: never the installed mods"
    return mods


@unittest.skipUnless(os.path.exists(EXE) and INSTALLED and os.path.isdir(os.path.join(INSTALLED, "profiles", "MAIN")),
                     "needs the clean Steam copy and D5_MAIN_FIXTURE (a disposable copy of the MAIN profile and mods)")
class MainProfileTests(unittest.TestCase):
    def test_main_profile_build_unchanged(self):
        """the MAIN profile builds with no site clash; D5_MAIN_EXE_SHA (the pre-ledger build's exe hash) must match"""
        from d5lib import modsys
        from d5lib.gamefs import GameFS, EXE_FILE
        from d5lib import exebytes
        mods = _main_mods()
        ally = [m for m in mods if m.id == "Ally_Steal"][0]
        exebytes.approve(ally)            # the fixture's own exe_approvals.json; real snapshot reads, no assess stub
        ctx = modsys.build(GameFS(STEAM), mods, log=lambda *_: None)
        self.assertFalse([s for s in getattr(ctx, "skipped_features", []) if "exe patch clash" in s[1]])
        self.assertFalse(getattr(ctx, "drop_mods", None))
        self.assertEqual(ctx.exe_applied.get("Ally_Steal"), exebytes.snapshot(ally)["fingerprint"])   # the approved snapshot was applied
        sha = hashlib.sha256(ctx.outputs[EXE_FILE.lower()][1]).hexdigest()
        if os.environ.get("D5_MAIN_EXE_SHA"):
            self.assertEqual(sha, os.environ["D5_MAIN_EXE_SHA"])

    def test_main_profile_builds_with_overlord_runtime_without_clash(self):
        from d5lib import modsys, overlord_compat as oc
        from d5lib.gamefs import GameFS
        orig = oc.configure

        def forced(ctx):
            r = orig(ctx)
            oc.ACTIVE.update(runtime=True, plugins=True)
            oc._reserve_sites(ctx)
            return r
        oc.configure = forced
        try:
            from d5lib import exebytes
            mods = _main_mods()
            exebytes.approve([m for m in mods if m.id == "Ally_Steal"][0])
            ctx = modsys.build(GameFS(STEAM), mods, log=lambda *_: None)
        finally:
            oc.configure = orig
            oc.ACTIVE.update(runtime=False, plugins=False, mods=[], families=set())
        self.assertTrue([e for e in ctx.exe_sites if e.get("reserved")])
        self.assertEqual([s for s in getattr(ctx, "skipped_features", []) if "exe patch clash" in s[1]], [])


if __name__ == "__main__":
    unittest.main()
