"""SUBCLASS2: sub-class from the Status Class tab (d5lib/subclasstab.py, section .d5sb) -- install rules, Overlord
arbitration, and the Unicorn / static-stack proof on the pinned exe (tools/proof_subclasstab.py)."""
import importlib.util
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from d5lib import exemap, modsys, overlord_compat, subclasstab as S

KIT = Path(__file__).resolve().parent.parent


def _proof():
    spec = importlib.util.spec_from_file_location("proof_subclasstab", KIT / "tools" / "proof_subclasstab.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    import unicorn  # noqa: F401
    HAVE_UNICORN = True
except ImportError:                                     # pragma: no cover
    HAVE_UNICORN = False


def _pinned():
    from test_recruit_runtime import pinned_exe
    p = pinned_exe()
    return Path(p).read_bytes() if p else None


class SourceTests(unittest.TestCase):
    def test_no_absolute_address_is_loaded(self):
        """the game runs with ASLR: game and section addresses are rip-relative symbols or branch targets"""
        for src in (S._src(0x148090000, 512), S._src(None, S.NATIVE_CAP)):
            self.assertFalse(re.search(r"\bmovabs\b|mov r\w+, 0x14|mov r\w+, 5\d{9}", src), src)
            self.assertIn("[rip + SC_ROSTER]", src)
        self.assertIn("[rip + SC_LIST]", S._src(0x148090000, 512))
        self.assertIn(f"[rbx + rdi*4 + {S.NATIVE_LIST:#x}]", S._src(None, S.NATIVE_CAP))

    def test_section_name_is_not_another_features(self):
        """claims are found by name (state_address, has_feature): .d5sc is scalepatch's, so this one is .d5sb"""
        hits = [f.name for f in (KIT / "d5lib").glob("*.py")
                if f.name != "subclasstab.py" and re.search(r'b"\.d5sb"', f.read_text(errors="replace"))]
        self.assertEqual(hits, [])
        self.assertEqual(S.SECTION_NAME, b".d5sb")

    def test_finalizer_runs_after_the_class_hooks(self):
        order = modsys.HANDLER_MODULES
        self.assertLess(order.index("d5lib.newclasses"), order.index("d5lib.subclasstab"))
        self.assertLess(order.index("d5lib.subclasstab"), order.index("d5lib.exebytes"))

    def test_overlord_site_is_the_kits_when_both_are_present(self):
        site = overlord_compat.SITES[S.SITE]
        self.assertEqual((site["section"], site["his_len"], site["kit_len"]), (".d5sb", 12, len(S.SITE_ORIG)))
        self.assertEqual(overlord_compat.owner_of(S.SITE, {"runtime": True, "plugins": True}), "kit")
        self.assertEqual(overlord_compat.owner_of(S.SITE, {"runtime": False}), "kit")


@unittest.skipUnless(_pinned(), "needs the pinned exe")
class BuildTests(unittest.TestCase):
    def setUp(self):
        self.raw = _pinned()
        self.prev = exemap.ACTIVE
        exemap.use(exemap.translator_for(self.raw))
        exemap.reset_ledger()
        self.addCleanup(exemap.use, self.prev)
        self.addCleanup(exemap.reset_ledger)

    def test_vanilla_build_is_left_alone(self):
        """no class mods: the Class tab is not relocated and the finalizer writes nothing"""
        self.assertIsNone(S.classtab_buffer(self.raw))
        self.assertEqual(S.build_patch(self.raw), self.raw)
        puts = []
        S._finalize(SimpleNamespace(get=lambda _p: self.raw, put=lambda *a: puts.append(a), log=lambda *_: None))
        self.assertEqual(puts, [])

    def test_class_build_gets_one_hook_and_its_ledger_entry(self):
        from d5lib import newclasses
        spec = {1440: dict(family=1440, template=1150, name="probe", unlocked=True, unlocked_ranks=6,
                           evility_alias={})}
        cls = list(range(1440, 1446))
        classes = newclasses.build_hooks(self.raw, cls, cls, {}, (), specs=spec)
        exemap.reset_ledger()
        with exemap.owner("d5lib.subclasstab"):
            out = S.build_patch(classes)
        self.assertTrue(S.is_hooked(out))
        self.assertEqual([(e["start"], e["end"]) for e in exemap.LEDGER], [(S.SITE, S.SITE + 12)])
        import pefile
        pe = pefile.PE(data=out, fast_load=True)
        off = pe.get_offset_from_rva(S.SITE - 0x140000000)
        self.assertEqual(out[off], 0xE9)
        self.assertEqual(out[off + 5:off + 12], b"\x90" * 7)
        self.assertIsNotNone(S.state_address(out))

    def test_overlord_runtime_owning_the_site_means_no_hook(self):
        from d5lib import newclasses
        spec = {1440: dict(family=1440, template=1150, name="probe", unlocked=True, unlocked_ranks=6,
                           evility_alias={})}
        cls = list(range(1440, 1446))
        classes = newclasses.build_hooks(self.raw, cls, cls, {}, (), specs=spec)
        site = overlord_compat.SITES[S.SITE]
        old_w, old = site["winner"], dict(overlord_compat.ACTIVE)
        site["winner"] = "overlord"
        overlord_compat.ACTIVE.update(runtime=True, plugins=True)
        try:
            self.assertEqual(S.build_patch(classes), classes)
        finally:
            site["winner"] = old_w
            overlord_compat.ACTIVE.clear()
            overlord_compat.ACTIVE.update(old)

    def test_another_build_is_refused(self):
        bad = bytearray(self.raw)
        import pefile
        pe = pefile.PE(data=self.raw, fast_load=True)
        off = pe.get_offset_from_rva(S.ACTION - 0x140000000)
        bad[off + 20] ^= 0xFF
        with self.assertRaisesRegex(ValueError, "carry_common_action"):
            S.build_patch_native(bytes(bad))


@unittest.skipUnless(_pinned() and HAVE_UNICORN, "needs the pinned exe and unicorn")
class ProofTests(unittest.TestCase):
    def test_unicorn_proof(self):
        r = _proof().prove(_pinned(), abi=True)
        failed = [c["check"] for c in r["checks"] if not c["ok"]]
        self.assertEqual(failed, [])
        self.assertGreaterEqual(len(r["checks"]), 28)

    def _named(self, words):
        r = _proof().prove(_pinned())
        hit = [c for c in r["checks"] if words in c["check"]]
        self.assertTrue(hit, words)
        self.assertTrue(all(c["ok"] for c in hit), hit)

    def test_own_main_class_is_refused(self):
        """rework (Codex review): a unit's own class family is never written as its sub-class"""
        self._named("own class (main")

    def test_rank_gap_takes_the_highest_unlocked_rank(self):
        """rework (Codex review): base + rank 5 unlocked -> rank 5; base locked -> refused"""
        self._named("rank gap (base and rank 5")
        self._named("base rank locked")

    def test_keyboard_confirm_reaches_the_hook(self):
        """SUBCLASS3: Confirm is read with carry_common_action, so a keyboard key bound to it writes the sub-class"""
        self._named("keyboard Confirm (key bound to action 4")
        self._named("does not see that keyboard Confirm")

    def test_registry_family_is_accepted(self):
        """SUBCLASS3: D1C Golem 11770 is a generic family (the INSTALL1120A row)"""
        self._named("registry family 11770")

    def test_static_stack_audit(self):
        r = _proof().prove_static(_pinned())
        self.assertTrue(r["pass"], [c for c in r["checks"] if not c["ok"]])


if __name__ == "__main__":
    unittest.main()
