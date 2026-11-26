"""Two features may read data from the same patch folder, and the folders run in one order.

`d5lib.newclasses` owns `patches/classes/class_<family>.json` (the class registry: unlock flags, rank counts, the
Hire Character carousel) and `d5lib.masteryext` owns `patches/classes/mastery.json` (the mastery extension's
family list).  `register_patch_handler` used to overwrite the entry for a folder, so installing masteryext silently
dropped every class spec: the exe carried the mastery hooks but no hire/carousel/class-table hook, and the imported
class never appeared in the Recruiter (found live, EX-LIVE2).

The ordering tests cover the review's P1: the old loop sorted *folder names* and then the handlers inside a folder,
so `classes` (order 45) ran before `db` (order 10) because "classes" sorts first.  The build now flattens every
handler into one (order, registration number, folder) list.
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, KIT)

from d5lib import modsys  # noqa: E402


class HandlerRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(modsys.PATCH_HANDLERS)
        self.saved_seq = dict(modsys._PATCH_SEQ)
        modsys.PATCH_HANDLERS.clear()
        modsys._PATCH_SEQ.clear()

    def tearDown(self):
        modsys.PATCH_HANDLERS.clear()
        modsys.PATCH_HANDLERS.update(self.saved)
        modsys._PATCH_SEQ.clear()
        modsys._PATCH_SEQ.update(self.saved_seq)

    def test_two_handlers_one_folder(self):
        def first(ctx, mod, d):
            pass

        def second(ctx, mod, d):
            pass

        modsys.register_patch_handler("classes", first, order=45)
        modsys.register_patch_handler("classes", second, order=46)
        regs = modsys.PATCH_HANDLERS["classes"]
        self.assertEqual([fn for _o, _s, fn in regs], [first, second])
        self.assertEqual([o for o, _s, _fn in regs], [45, 46])

    def test_reregistering_the_same_handler_does_not_duplicate_it(self):
        def only(ctx, mod, d):
            pass

        modsys.register_patch_handler("classes", only, order=45)
        modsys.register_patch_handler("classes", only, order=45)
        self.assertEqual(len(modsys.PATCH_HANDLERS["classes"]), 1)

    def test_same_order_in_one_folder_is_stable_and_never_compares_functions(self):
        def first(ctx, mod, d):
            pass

        def second(ctx, mod, d):
            pass

        modsys.register_patch_handler("classes", first, order=45)
        modsys.register_patch_handler("classes", second, order=45)
        # a tuple of tuples of functions would raise TypeError on the second element; this is a plain sort
        self.assertEqual([fn for _o, _s, fn in modsys.PATCH_HANDLERS["classes"]], [first, second])

    def test_order_is_global_across_folders(self):
        def db_handler(ctx, mod, d):
            pass

        def classes_handler(ctx, mod, d):
            pass

        modsys.register_patch_handler("classes", classes_handler, order=45)
        modsys.register_patch_handler("db", db_handler, order=10)
        order = [(folder, fn) for _o, _s, folder, fn in modsys.ordered_patch_handlers()]
        # "classes" sorts first as a *name*; order 10 must still run before order 45
        self.assertEqual(order, [("db", db_handler), ("classes", classes_handler)])

    def test_a_dependent_folder_sees_the_other_folder_s_output(self):
        seen = []

        def db_handler(ctx, mod, d):
            seen.append(("db", list(ctx.state)))

        def classes_handler(ctx, mod, d):
            ctx.state.append("class-spec-1350")
            seen.append(("classes", list(ctx.state)))

        modsys.register_patch_handler("classes", classes_handler, order=45)
        modsys.register_patch_handler("db", db_handler, order=10)
        ctx = SimpleNamespace(state=[])
        with tempfile.TemporaryDirectory() as mod_dir:
            for folder in ("classes", "db"):
                os.makedirs(os.path.join(mod_dir, "patches", folder))
                open(os.path.join(mod_dir, "patches", folder, "x.json"), "w").write("{}")
            mod = SimpleNamespace(patches_dir=os.path.join(mod_dir, "patches"), list_files=lambda: [],
                                  read_file=lambda rel: b"")
            for _o, _s, folder, fn in modsys.ordered_patch_handlers():
                fn(ctx, mod, os.path.join(mod.patches_dir, folder))
        self.assertEqual(seen[0], ("db", []))
        self.assertEqual(seen[1], ("classes", ["class-spec-1350"]))


if __name__ == "__main__":
    unittest.main()
