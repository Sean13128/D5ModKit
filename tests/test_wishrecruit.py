"""RECRUIT1: recruit wishes (d5lib/wishrecruit.py, section .d5wr) -- the table rules, the install step, and the
Unicorn proof on the pinned exe (tools/proof_wishrecruit.py), including two mutations the proof must catch."""
import importlib.util
import os
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace

from d5lib import exemap, overlord_compat, wishrecruit as W

KIT = Path(__file__).resolve().parent.parent


def _proof():
    spec = importlib.util.spec_from_file_location("proof_wishrecruit", KIT / "tools" / "proof_wishrecruit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    import unicorn  # noqa: F401
    HAVE_UNICORN = True
except ImportError:                                     # pragma: no cover
    HAVE_UNICORN = False


class TableTests(unittest.TestCase):
    def test_normalise_sorts_and_packs(self):
        e = W.normalise({"20300": {"character": 20300, "level": 10},
                         "20000": {"character": 20000, "level": 50, "duplicates": True}})
        self.assertEqual(e, [(20000, 20000, 50, 1), (20300, 20300, 10, 0)])
        self.assertEqual(W.table_bytes(e), struct.pack("<8I", 20000, 20000, 50, 1, 20300, 20300, 10, 0))

    def test_item_assembly_range_and_vanilla_ids_are_refused(self):
        for bill in (1049, 1000, 1999, 5, 411):
            with self.assertRaisesRegex(ValueError, "2000 or more"):
                W.normalise({str(bill): {"character": 90, "level": 60}})

    def test_bad_values_are_refused(self):
        with self.assertRaisesRegex(ValueError, "level"):
            W.normalise({"2000": {"character": 90, "level": 10000}})
        with self.assertRaisesRegex(ValueError, "class id"):
            W.normalise({"2000": {"character": 0}})
        with self.assertRaisesRegex(ValueError, "unknown field"):
            W.normalise({"2000": {"character": 90, "flag": 1199}})   # the unlock flag is the row's req_flag1

    def test_two_mods_must_agree(self):
        acc = W.merge({}, {"2000": {"character": 90, "level": 60}})
        W.merge(acc, {"2000": {"character": 90, "level": 60}})
        with self.assertRaisesRegex(ValueError, "another character"):
            W.merge(acc, {"2000": {"character": 170, "level": 60}})

    def test_pack_format_lists_members_in_order(self):
        e = W.normalise({"2700": [{"character": 3002, "level": 30}, {"character": 3001, "level": 20}],
                         "2600": {"character": 90}})
        self.assertEqual(e, [(2600, 90, 1, 0), (2700, 3002, 30, 0), (2700, 3001, 20, 0)])
        self.assertEqual(W.packs(e)[2700], [(2700, 3002, 30, 0), (2700, 3001, 20, 0)])
        self.assertEqual(W.normalise({"2700": [{"character": 90}]}), W.normalise({"2700": {"character": 90}}))

    def test_malformed_packs_are_refused(self):
        with self.assertRaisesRegex(ValueError, "empty pack"):
            W.normalise({"2700": []})
        with self.assertRaisesRegex(ValueError, "listed twice"):
            W.normalise({"2700": [{"character": 90}, {"character": 90, "level": 5}]})
        with self.assertRaisesRegex(ValueError, "listed twice"):       # both must allow copies
            W.normalise({"2700": [{"character": 90, "duplicates": True}, {"character": 90}]})
        W.normalise({"2700": [{"character": 90, "duplicates": True}, {"character": 90, "duplicates": True}]})
        with self.assertRaisesRegex(ValueError, "exceeds the roster"):
            W.normalise({"2700": [{"character": 100 + i} for i in range(129)]})
        with self.assertRaisesRegex(ValueError, "level"):              # one bad member sinks the pack
            W.normalise({"2700": [{"character": 90}, {"character": 91, "level": 0}]})
        with self.assertRaisesRegex(ValueError, "expected an object"):
            W.normalise({"2700": [{"character": 90}, 5]})
        with self.assertRaisesRegex(ValueError, "2000 or more"):
            W.normalise({"1500": [{"character": 90}]})

    def test_pack_merge_and_check_rows(self):
        pack = {"2700": [{"character": 90}, {"character": 91}]}
        acc = W.merge({}, pack)
        W.merge(acc, pack)
        with self.assertRaisesRegex(ValueError, "another character"):
            W.merge(acc, {"2700": [{"character": 90}]})
        self.assertEqual(len(W.flatten(acc)), 2)
        wish = SimpleNamespace(rows=[])
        char = SimpleNamespace(rows=[{"id": 90}])
        self.assertEqual(W.check_rows(W.flatten(acc), wish, char),
                         ["recruit wish 2700: no WishDataBase.dat row 2700",
                          "recruit wish 2700: no char.dat row for class 91"])

    def test_check_rows_names_missing_rows(self):
        e = W.normalise({"20300": {"character": 20300}})
        wish = SimpleNamespace(rows=[{"id": 1}])
        char = SimpleNamespace(rows=[{"id": 10}])
        self.assertEqual(W.check_rows(e, wish, char), ["recruit wish 20300: no WishDataBase.dat row 20300",
                                                        "recruit wish 20300: no char.dat row for class 20300"])
        self.assertEqual(W.check_rows(e, SimpleNamespace(rows=[{"id": 20300}]),
                                      SimpleNamespace(rows=[{"id": 20300}])), [])


class FinalizeTests(unittest.TestCase):
    def test_overlord_runtime_owns_the_sites(self):
        logs = []
        ctx = SimpleNamespace(_recruit_wishes={20300: (20300, 20300, 10, 0)}, log=logs.append,
                              get=lambda *_: self.fail("the exe must not be read"),
                              put=lambda *_: self.fail("the exe must not be written"))
        saved = dict(overlord_compat.ACTIVE)
        overlord_compat.ACTIVE["runtime"] = True
        try:
            W._finalize(ctx)
        finally:
            overlord_compat.ACTIVE.clear()
            overlord_compat.ACTIVE.update(saved)
        self.assertIn("Overlord's runtime owns the wish hook site", logs[0])
        self.assertIn("0x14044a730", logs[0])

    def test_nothing_listed_writes_nothing(self):
        ctx = SimpleNamespace(log=print, get=lambda *_: self.fail("read"), put=lambda *_: self.fail("write"))
        W._finalize(ctx)


@unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the real-code proof")
class ProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.P = _proof()
        path = cls.P.find_pinned()
        if not path:
            raise unittest.SkipTest("the pinned game exe is not in the kit's game state")
        cls.pinned = path.read_bytes()

    def failed(self, receipt):
        return [c["check"] for c in receipt["checks"] if not c["ok"]]

    def test_proof_normal_and_abi(self):
        self.assertEqual(self.failed(self.P.prove(self.pinned)), [])
        self.assertEqual(self.failed(self.P.prove(self.pinned, abi=True)), [])

    def test_runtime_present_build_patch_is_a_no_op_but_absent_applies(self):
        saved = dict(overlord_compat.ACTIVE)
        entries = W.normalise({"20300": {"character": 20300}})
        prev = exemap.ACTIVE
        exemap.use(exemap.translator_for(self.pinned))
        try:
            overlord_compat.ACTIVE.update(runtime=True, wishes=True)
            self.assertEqual(W.build_patch(self.pinned, entries), self.pinned)
            overlord_compat.ACTIVE.update(runtime=False)
            self.assertTrue(W.is_hooked(W.build_patch(self.pinned, entries)))
        finally:
            exemap.use(prev)
            overlord_compat.ACTIVE.clear()
            overlord_compat.ACTIVE.update(saved)

    def test_the_hooks_land_and_claim_the_section(self):
        prev = exemap.ACTIVE
        exemap.use(exemap.translator_for(self.pinned))
        try:
            out = W.build_patch(self.pinned, W.normalise({"20300": {"character": 20300}}))
        finally:
            exemap.use(prev)
        self.assertTrue(W.is_hooked(out))
        self.assertFalse(W.is_hooked(self.pinned))

    def test_finalize_builds_the_exe_and_refuses_missing_rows(self):
        """the install step end to end on fakes: the tables it reads, the exe it writes"""
        from d5lib import database
        tables = {"WishDataBase.dat": [{"id": 20300}], "char.dat": [{"id": 20300}]}
        written, logs = {}, []
        from d5lib.gamefs import EXE_FILE
        ctx = SimpleNamespace(_recruit_wishes={20300: (20300, 20300, 10, 0)}, log=logs.append,
                              get=lambda path: self.pinned if path == EXE_FILE else path.rsplit("/", 1)[1].encode(),
                              put=lambda path, data: written.update({path: data}))
        real = database.load_table
        database.load_table = lambda name, data: SimpleNamespace(rows=tables[data.decode()])
        prev = exemap.ACTIVE
        exemap.use(exemap.translator_for(self.pinned))
        try:
            W._finalize(ctx)
            self.assertEqual(len(written), 1)
            self.assertTrue(W.is_hooked(next(iter(written.values()))))
            self.assertIn("bill 20300 -> class 20300 Lv10", logs[-1])
            tables["char.dat"] = [{"id": 10}]
            with self.assertRaisesRegex(ValueError, "no char.dat row for class 20300"):
                W._finalize(ctx)
        finally:
            database.load_table = real
            exemap.use(prev)

    def test_mutation_scan_stops_after_first_match_is_caught(self):
        old = W._post_src
        W._post_src = lambda n: old(n).replace("wr_p_next:", "jmp wr_p_done\nwr_p_next:").replace(
            "mov rsp, rbp\npop", "wr_p_done:\nmov rsp, rbp\npop")
        try:
            bad = self.failed(self.P.prove(self.pinned))
        finally:
            W._post_src = old
        self.assertTrue(any(c.startswith("pack bill 2700") for c in bad), bad)

    def test_mutation_pack_size_ignored_is_caught(self):
        old = W._vis_src
        W._vis_src = lambda n: old(n).replace("inc r9d", "nop")
        try:
            bad = self.failed(self.P.prove(self.pinned))
        finally:
            W._vis_src = old
        self.assertIn("pack of 3: army 100 + reserve 26 + 3 = 129 -> hidden", bad)

    def test_mutation_roster_guard_off_by_one_is_caught(self):
        old = W.ROSTER_MAX
        W.ROSTER_MAX = 0x7F
        try:
            bad = self.failed(self.P.prove(self.pinned))
        finally:
            W.ROSTER_MAX = old
        self.assertIn("army 100 + reserve 27 (one slot) -> visible", bad)

    def test_mutation_unaligned_call_is_caught(self):
        old = W._post_src
        W._post_src = lambda n: old(n).replace("and rsp, -16\n", "")
        try:
            bad = self.failed(self.P.prove(self.pinned, abi=True))
        finally:
            W._post_src = old
        self.assertIn("--abi effect: roster_create_unit entered at RSP 8 mod 16 (both alignments)", bad)

    def test_mutation_xmm_read_after_the_site_is_caught(self):
        """RECRUITCHK1 (3): the static xmm check must notice an xmm register read after the post hook's site"""
        self.assertTrue(self.P.xmm_liveness(self.pinned, W.POST_SITE)["ok"])
        base, _, secs = self.P.sections(self.pinned)
        va = 0x1402217A6                                   # dec byte ptr [rbx + 0x134] (6 bytes), after the site
        off = next(ro + va - base - sva for vs, sva, rs, ro in secs if sva <= va - base < sva + rs)
        self.assertEqual(self.pinned[off:off + 6], bytes.fromhex("fe8b34010000"))
        bad = bytearray(self.pinned)
        bad[off:off + 6] = bytes.fromhex("660f7ec09090")    # movd eax, xmm0 / nop / nop
        x = self.P.xmm_liveness(bytes(bad), W.POST_SITE)
        self.assertFalse(x["ok"])
        self.assertTrue(any("0x1402217a6" in p for p in x["problems"]), x)


STEAM = os.environ.get("D5_CLEAN_GAME", "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)")


@unittest.skipUnless(os.path.isfile(os.path.join(STEAM, "disgaea5.exe")), "needs the clean Steam copy (Disgaea Source)")
class SameInstallTests(unittest.TestCase):
    """RECRUITCHK1 (2): a recruit wish for a character that a new-character mod adds in the SAME install.  The whole
    install build (modsys.build) on the clean game files: dbpatch's handler adds the char.dat and WishDataBase rows,
    newchars' handler records the character's face, outfits' finalizer gives it its own colour id, and the
    wishrecruit finalizer must then see the added rows and write .d5wr.  Nothing is written to disk."""
    NEW_ID, BILL = 901, 2600                       # 901: a unique id the vanilla char.dat lacks

    @classmethod
    def setUpClass(cls):
        from d5lib import database
        from d5lib.dbpatch import DB_ARCHIVE
        from d5lib.gamefs import GameFS
        cls.fs = GameFS(STEAM)
        chars = database.load_table("char.dat", cls.fs.read(f"{DB_ARCHIVE}/char.dat"))
        wishes = database.load_table("WishDataBase.dat", cls.fs.read(f"{DB_ARCHIVE}/WishDataBase.dat"))
        assert cls.NEW_ID not in {r["id"] for r in chars.rows} and cls.BILL not in {r["id"] for r in wishes.rows}
        killia = next(r for r in chars.rows if r["id"] == 10)
        def fields(row):                           # the JSON a mod's db patch holds (padding bytes left at zero)
            return {k: v for k, v in row.to_dict().items() if not isinstance(v, bytes)}
        cls.char_row = dict(fields(killia), id=cls.NEW_ID, name_EN="Recruit Check")
        cls.wish_row = dict(fields(wishes.rows[-1]), id=cls.BILL)

    def _mod(self, root, with_char=True):
        import json
        import tempfile
        from PIL import Image
        from d5lib.modsys import Mod
        d = Path(tempfile.mkdtemp(dir=root))
        (d / "mod.json").write_text(json.dumps({"name": "Recruit check"}))
        for sub in ("db", "wishes", "characters"):
            (d / "patches" / sub).mkdir(parents=True)
        if with_char:
            (d / "patches" / "db" / "char.dat.json").write_text(json.dumps({"table": "char.dat",
                                                                           "added": [self.char_row]}))
            Image.new("RGBA", (64, 64), (200, 40, 40, 255)).save(d / "patches" / "characters" / f"face_{self.NEW_ID}.png")
        (d / "patches" / "db" / "WishDataBase.dat.json").write_text(json.dumps({"table": "WishDataBase.dat",
                                                                                "added": [self.wish_row]}))
        (d / "patches" / "wishes" / "recruit_wishes.json").write_text(json.dumps(
            {"recruits": {str(self.BILL): {"character": self.NEW_ID, "level": 10}}}))
        return Mod(str(d))

    def test_finalizer_runs_after_the_steps_that_add_rows(self):
        from d5lib import modsys
        modsys.load_handlers(lambda *_: None)
        mods = [fn.__module__ for fn in modsys.ordered_finalizers()]
        at = mods.index("d5lib.wishrecruit")
        for m in ("d5lib.dbpatch", "d5lib.outfits", "d5lib.newclasses"):
            self.assertLess(max(i for i, x in enumerate(mods) if x == m), at, m)
        handlers = {fn.__module__: order for order, _, _, fn in modsys.ordered_patch_handlers()}
        self.assertLess(handlers["d5lib.dbpatch"], handlers["d5lib.wishrecruit"])
        self.assertLess(handlers["d5lib.newchars"], handlers["d5lib.wishrecruit"])

    def test_new_character_from_the_same_install_is_accepted(self):
        import tempfile
        from d5lib import modsys, overlord_compat
        from d5lib.gamefs import EXE_FILE
        saved = dict(overlord_compat.ACTIVE)
        with tempfile.TemporaryDirectory() as root:
            logs = []
            try:
                ctx = modsys.build(self.fs, [self._mod(root)], log=logs.append)
            finally:
                overlord_compat.ACTIVE.clear()
                overlord_compat.ACTIVE.update(saved)
            self.assertTrue(W.is_hooked(ctx.outputs[EXE_FILE.lower()][1]), "\n".join(logs[-30:]))
            self.assertIn(f"  recruit wishes: bill {self.BILL} -> class {self.NEW_ID} Lv10", logs)
            self.assertFalse(getattr(ctx, "skipped_features", []))

    def test_without_the_character_row_the_install_is_refused(self):
        import tempfile
        from d5lib import modsys, overlord_compat
        saved = dict(overlord_compat.ACTIVE)
        with tempfile.TemporaryDirectory() as root:
            try:
                with self.assertRaisesRegex(ValueError, f"no char.dat row for class {self.NEW_ID}"):
                    modsys.build(self.fs, [self._mod(root, with_char=False)], log=lambda *_: None)
            finally:
                overlord_compat.ACTIVE.clear()
                overlord_compat.ACTIVE.update(saved)


if __name__ == "__main__":
    unittest.main()
