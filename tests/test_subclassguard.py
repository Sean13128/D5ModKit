"""SUBCLASS2 rework: the Assembly sub-class panel guard (d5lib/subclassguard.py, section .d5sv) -- every build,
the Unicorn proof (missing row: no fault, panel skipped; present row: unchanged) and its static check."""
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

from d5lib import exemap, modsys, subclassguard as G

KIT = Path(__file__).resolve().parent.parent


def _proof():
    spec = importlib.util.spec_from_file_location("proof_subclassguard", KIT / "tools" / "proof_subclassguard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pinned():
    from test_recruit_runtime import pinned_exe
    p = pinned_exe()
    return Path(p).read_bytes() if p else None


class OrderTests(unittest.TestCase):
    def test_registered_as_its_own_finalizer_before_mod_bytes(self):
        order = modsys.HANDLER_MODULES
        self.assertIn("d5lib.subclassguard", order)
        self.assertLess(order.index("d5lib.subclassguard"), order.index("d5lib.exebytes"))

    def test_section_name_is_its_own(self):
        hits = [f.name for f in (KIT / "d5lib").glob("*.py")
                if f.name != "subclassguard.py" and 'b".d5sv"' in f.read_text(errors="replace")]
        self.assertEqual(hits, [])


@unittest.skipUnless(_pinned(), "needs the pinned exe")
class BuildTests(unittest.TestCase):
    def setUp(self):
        exemap.reset_ledger()
        self.addCleanup(exemap.reset_ledger)

    def test_every_build_gets_it_even_without_class_mods(self):
        """the finalizer needs no mod data: a vanilla exe is patched, one site claimed"""
        raw = _pinned()
        puts = []
        with exemap.owner("subclassguard"):
            G._finalize(SimpleNamespace(get=lambda _p: raw, put=lambda *a: puts.append(a), log=lambda *_: None))
        self.assertEqual(len(puts), 1)
        self.assertEqual([(e["start"], e["end"], e["owner"]) for e in exemap.LEDGER],
                         [(G.SITE, G.SITE + 11, "subclassguard")])
        self.assertIsNotNone(G.counter_va(puts[0][1]))

    def test_other_bytes_are_left_alone(self):
        raw = bytearray(_pinned())
        import pefile
        off = pefile.PE(data=bytes(raw), fast_load=True).get_offset_from_rva(G.EPILOGUE - 0x140000000)
        raw[off] ^= 0xFF
        self.assertEqual(G.patch(bytes(raw), log=lambda *_: None), bytes(raw))


@unittest.skipUnless(_pinned(), "needs the pinned exe")
class ProofTests(unittest.TestCase):
    def test_unicorn_proof_with_abi(self):
        r = _proof().prove(_pinned(), abi=True)
        self.assertEqual([c["check"] for c in r["checks"] if not c["ok"]], [])

    def test_static(self):
        self.assertTrue(_proof().prove_static(_pinned())["pass"])


if __name__ == "__main__":
    unittest.main()
