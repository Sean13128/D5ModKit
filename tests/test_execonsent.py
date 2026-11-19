"""SITELEDGER3: program-patch mods (patches/exe): consent gate (off by default, approval bound to content, confirm on
import, visible label), the whole mod skipped when a patch can't apply, and the size caps.  No game exe needed."""
import contextlib
import json
import os
import tempfile
import unittest
from unittest import mock

from d5lib import exebytes, modinfo, modsys, modshare

PATCH = {"va": "0x1401AF645", "orig": "0F84DE010000", "new": "660F1F440000", "what": "steal"}


class Vanilla:
    rows = []

    def find(self, i):
        return None


class FS:
    def read(self, vpath):
        return b""


def make(kit, mid, patches=None, files=True):
    d = os.path.join(kit, "mods", mid)
    os.makedirs(os.path.join(d, "patches", "exe"), exist_ok=True)
    with open(os.path.join(d, "mod.json"), "w") as f:
        json.dump({"name": mid.upper(), "version": "1.0"}, f)
    if files:
        os.makedirs(os.path.join(d, "files", "Text"), exist_ok=True)
        with open(os.path.join(d, "files", "Text", "x.txt"), "w") as f:
            f.write(mid)
    if patches is not None:
        with open(os.path.join(d, "patches", "exe", "p.json"), "w") as f:
            json.dump({"patches": patches}, f)
    return modsys.Mod(d)


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="execonsent-")
        self.addCleanup(t.cleanup)
        self.kit = t.name
        os.makedirs(os.path.join(self.kit, "mods"))


class Gate(Base):
    def test_unapproved_is_refused_and_label_shown(self):
        m = make(self.kit, "a", [PATCH])
        self.assertTrue(exebytes.carries(m))
        self.assertFalse(exebytes.is_approved(m))
        self.assertIn("not approved", exebytes.consent_problem(m))
        self.assertTrue(modinfo.one_line(m).startswith("⚠ " + exebytes.LABEL))
        self.assertTrue(any("OFF until you approve" in l for l in modinfo.summary(m)))

    def test_mod_without_exe_has_no_gate_or_label(self):
        m = make(self.kit, "plain")
        self.assertEqual(exebytes.consent_problem(m), "")
        self.assertNotIn(exebytes.LABEL, modinfo.one_line(m))

    def test_approval_is_bound_to_content_and_settings(self):
        m = make(self.kit, "a", [PATCH])
        exebytes.approve(m)
        self.assertEqual(exebytes.consent_problem(m), "")
        self.assertTrue(any("approved by you" in l for l in modinfo.summary(m)))
        make(self.kit, "a", [dict(PATCH, new="660F1F440001")])           # content changed
        self.assertTrue(exebytes.consent_problem(modsys.Mod(m.folder)))
        exebytes.approve(modsys.Mod(m.folder))
        m2 = modsys.Mod(m.folder)
        m2.meta["settings"] = {"cost": 5}                                # settings changed
        self.assertTrue(exebytes.consent_problem(m2))

    def test_approval_is_not_taken_from_the_mod(self):
        m = make(self.kit, "a", [PATCH])
        m.meta["exe_approved"] = True
        m.meta["approved"] = exebytes.fingerprint(m)
        m.save_meta()
        self.assertTrue(exebytes.consent_problem(modsys.Mod(m.folder)))

    def test_revoke(self):
        m = make(self.kit, "a", [PATCH])
        exebytes.approve(m)
        exebytes.revoke(m)
        self.assertTrue(exebytes.consent_problem(m))

    def test_build_leaves_the_unapproved_mod_out_whole(self):
        a, b = make(self.kit, "a", [PATCH]), make(self.kit, "b")
        seen = []

        def fake(fs, mods, log, notes=(), exe_snapshots=None):
            seen.append([m.id for m in mods])
            return mock.Mock(drop_mods=None, notes=list(notes), exe_snapshots=exe_snapshots)
        logs = []
        with mock.patch.object(modsys, "_build", fake):
            ctx = modsys.build(FS(), [a, b], log=logs.append)
        self.assertEqual(seen, [["b"]])
        self.assertEqual(ctx.notes[0][0], "mod A (a)")
        self.assertTrue(any("left out whole" in l and "not approved" in l for l in logs))
        exebytes.approve(a)
        seen.clear()
        with mock.patch.object(modsys, "_build", fake):
            modsys.build(FS(), [a, b], log=logs.append)
        self.assertEqual(seen, [["a", "b"]])

    def test_failing_patch_skips_the_whole_mod_and_rebuilds_without_it(self):
        a, b = make(self.kit, "a", [PATCH]), make(self.kit, "b")
        exebytes.approve(a)
        calls = []

        def fake(fs, mods, log, notes=(), exe_snapshots=None):
            ids = [m.id for m in mods]
            calls.append((ids, list(notes)))
            return mock.Mock(drop_mods={"a": ("mod A (a)", "bytes differ")} if "a" in ids else None)
        logs = []
        with mock.patch.object(modsys, "_build", fake):
            modsys.build(FS(), [a, b], log=logs.append)
        self.assertEqual([c[0] for c in calls], [["a", "b"], ["b"]])
        self.assertEqual(calls[1][1], [("mod A (a)", "left out whole: bytes differ")])
        self.assertTrue(any("Building again without a" in l for l in logs))

    def test_build_passes_the_snapshot_it_checked_to_the_build(self):
        a = make(self.kit, "a", [PATCH])
        exebytes.approve(a)
        seen = []

        def fake(fs, mods, log, notes=(), exe_snapshots=None):
            seen.append(exe_snapshots)
            return mock.Mock(drop_mods=None)
        with mock.patch.object(modsys, "_build", fake):
            modsys.build(FS(), [a], log=lambda *_: None)
        snap = seen[0]["a"]
        self.assertEqual(snap["fingerprint"], exebytes.fingerprint(a))
        self.assertEqual(snap["files"]["p.json"], open(os.path.join(a.patches_dir, "exe", "p.json"), "rb").read())

    def test_bytes_changed_after_approval_are_refused(self):
        m = make(self.kit, "a", [PATCH])
        exebytes.approve(m)
        approved = exebytes.fingerprint(m)
        self.assertEqual(exebytes.assess(m)[1], "")
        make(self.kit, "a", [dict(PATCH, new="660F1F440001")])          # edited after the approval
        snap, why = exebytes.assess(m)
        self.assertTrue(why and "not approved" in why)
        self.assertNotEqual(snap["fingerprint"], approved)
        self.assertFalse(exebytes.is_approved(m, snap))

    def test_the_build_applies_the_approved_snapshot_not_a_later_edit(self):
        m = make(self.kit, "a", [PATCH])
        exebytes.approve(m)
        snap, why = exebytes.assess(m)
        self.assertEqual(why, "")
        make(self.kit, "a", [dict(PATCH, new="660F1F440001", orig="0F84DE010000")])
        entries = exebytes.load(m, snap)                     # what the finalizer applies
        self.assertEqual(entries[0]["new"], bytes.fromhex("660F1F440000"))
        self.assertNotEqual(exebytes.assess(m)[0], snap)     # and the next build sees the edit and refuses it

    def test_unreadable_patch_file_is_a_named_whole_mod_skip(self):
        a, b = make(self.kit, "a", [PATCH]), make(self.kit, "b")
        os.remove(os.path.join(a.patches_dir, "exe", "p.json"))
        os.makedirs(os.path.join(a.patches_dir, "exe", "p.json"))        # a file the kit can't read as JSON
        snap, why = exebytes.assess(a)
        self.assertIn("p.json", why)
        self.assertIn("can't be read", why)
        seen = []

        def fake(fs, mods, log, notes=(), exe_snapshots=None):
            seen.append([m.id for m in mods])
            return mock.Mock(drop_mods=None, notes=list(notes))
        logs = []
        with mock.patch.object(modsys, "_build", fake):
            ctx = modsys.build(FS(), [a, b], log=logs.append)       # no traceback: a skip with its reason
        self.assertEqual(seen, [["b"]])
        self.assertTrue(ctx.notes and "p.json" in ctx.notes[0][1])

    def test_a_patch_added_after_the_consent_check_is_not_applied(self):
        m = make(self.kit, "a")                                          # nothing to approve when the build checked
        ctx = mock.Mock(mod_folders=[m.folder], exe_snapshots={}, skipped_features=[], log=mock.Mock())
        ctx.drop_mods = None
        del ctx.drop_mods
        make(self.kit, "a", [PATCH])                                     # appears before the finalizer runs
        exebytes._finalize(ctx)
        self.assertIn("a", ctx.drop_mods)
        self.assertIn("not approved", ctx.drop_mods["a"][1])

    def test_a_patch_appearing_after_the_last_assessment_is_never_written(self):
        m = make(self.kit, "a")
        real = exebytes.assess

        def assess_then_add(mod):
            r = real(mod)                                                # sees no patch: (None, "")
            make(self.kit, "a", [PATCH])                                 # the file lands right after the check
            return r
        ctx = mock.Mock(mod_folders=[m.folder], exe_snapshots={}, exe_applied={}, skipped_features=[], log=mock.Mock())
        with mock.patch.object(exebytes, "assess", assess_then_add), \
                mock.patch.object(exebytes, "apply") as writer:
            exebytes._finalize(ctx)
        writer.assert_not_called()
        ctx.put.assert_not_called()
        self.assertNotIn("a", ctx.exe_applied)

    def test_success_log_comes_from_the_applied_snapshot_not_a_reread(self):
        m = make(self.kit, "a", [PATCH])
        exebytes.approve(m)
        snap, why = exebytes.assess(m)
        self.assertEqual(why, "")
        logs = []
        ctx = mock.Mock(mod_folders=[m.folder], exe_snapshots={"a": snap}, exe_applied={}, skipped_features=[], log=logs.append)
        boom = OSError("read failed after apply")
        with mock.patch.object(exebytes, "load", return_value=[{"va": 1, "orig": b"\x0f\x84", "new": b"\x90\x90", "what": "w"}]), \
                mock.patch.object(exebytes, "apply", return_value=b"patched") as writer, \
                mock.patch.object(exebytes, "describe", side_effect=boom), \
                mock.patch.object(modsys.Mod, "load_patch", side_effect=boom):
            exebytes._finalize(ctx)                                      # must not raise
        writer.assert_called_once()
        ctx.put.assert_called_once()
        self.assertTrue(any("1 sites (2 bytes)" in l for l in logs))


class Caps(Base):
    def test_patch_over_256_bytes_is_refused(self):
        n = exebytes.MAX_PATCH_BYTES + 1
        m = make(self.kit, "a", [dict(PATCH, orig="90" * n, new="CC" * n)])
        with self.assertRaisesRegex(ValueError, "256-byte limit"):
            exebytes.load(m)

    def test_256_bytes_is_allowed(self):
        n = exebytes.MAX_PATCH_BYTES
        with mock.patch.object(exebytes.exemap, "ACTIVE", mock.Mock(sha1="ab")):
            m = make(self.kit, "a", [dict(PATCH, orig="90" * n, new="CC" * n)])
            self.assertEqual(len(exebytes.load(m)), 1)

    def test_mod_over_4kb_is_refused(self):
        n = exebytes.MAX_PATCH_BYTES
        ps = [dict(PATCH, va=hex(0x140001000 + i * 512), orig="90" * n, new="CC" * n) for i in range(17)]   # 4352 B
        with self.assertRaisesRegex(ValueError, "4096-byte limit"):
            exebytes.load(make(self.kit, "a", ps))
        ok = ps[:16]                                                    # exactly 4096
        self.assertEqual(len(exebytes.load(make(self.kit, "b", ok))), 16)

    def test_oversize_mod_is_dropped_whole_by_finalize(self):
        n = exebytes.MAX_PATCH_BYTES
        ps = [dict(PATCH, va=hex(0x140001000 + i * 512), orig="90" * n, new="CC" * n) for i in range(17)]
        m = make(self.kit, "a", ps)
        ctx = mock.Mock(mod_folders=[m.folder], skipped_features=[], drop_mods=None)
        ctx.drop_mods = None
        del ctx.drop_mods
        exebytes._finalize(ctx)
        self.assertIn("a", ctx.drop_mods)
        self.assertIn("4096-byte", ctx.skipped_features[0][1])


class Import(Base):
    def setUp(self):
        super().setUp()
        st = contextlib.ExitStack()
        self.addCleanup(st.close)
        st.enter_context(mock.patch("d5lib.database.load_table", lambda n, b: Vanilla()))
        st.enter_context(mock.patch("d5lib.sprites.used_sprite_numbers", lambda fs: set()))
        src = tempfile.TemporaryDirectory(prefix="execonsent-src-")
        self.addCleanup(src.cleanup)
        os.makedirs(os.path.join(src.name, "mods"))
        self.pkg = modshare.export_package(make(src.name, "pk", [PATCH]), os.path.join(src.name, "pk.zip"), copy=True) \
            if "copy" in modshare.export_package.__code__.co_varnames else \
            modshare.export_package(make(src.name, "pk", [PATCH]), os.path.join(src.name, "pk.zip"))
        self.state = os.path.join(self.kit, "state")

    def imp(self, consent=None):
        return modshare.import_package(self.pkg, os.path.join(self.kit, "mods"), FS(), self.state, log=lambda *_: None,
                                       exe_consent=consent)

    def mm(self):
        return modsys.ModManager(self.kit)

    def test_default_is_off_and_unapproved(self):
        r = self.imp()
        self.assertTrue(r["exe"] and not r["exe_approved"])
        self.assertNotIn(r["mod_id"], self.mm().load_order())
        self.assertTrue(exebytes.consent_problem(modsys.Mod(os.path.join(self.kit, "mods", r["mod_id"]))))

    def test_decline_is_off(self):
        asked = []
        r = self.imp(lambda line: asked.append(line) or False)
        self.assertEqual(len(asked), 1)
        self.assertIn("patches the game's code at 1 sites", asked[0])
        self.assertNotIn(r["mod_id"], self.mm().load_order())

    def test_confirm_enables_and_approves(self):
        r = self.imp(lambda line: True)
        self.assertTrue(r["exe_approved"])
        self.assertIn(r["mod_id"], self.mm().load_order())
        self.assertEqual(exebytes.consent_problem(modsys.Mod(os.path.join(self.kit, "mods", r["mod_id"]))), "")

    def test_declined_update_switches_the_mod_off_and_revokes(self):
        r = self.imp(lambda line: True)
        self.imp(lambda line: False)
        self.assertNotIn(r["mod_id"], self.mm().load_order())
        self.assertTrue(exebytes.consent_problem(modsys.Mod(os.path.join(self.kit, "mods", r["mod_id"]))))

    def test_yes_after_no_switches_the_mod_on(self):
        r = self.imp(lambda line: False)
        self.assertFalse(r["enabled"])
        r2 = self.imp(lambda line: True)                    # the same package again, now approved
        self.assertTrue(r2["enabled"])
        self.assertIn(r2["mod_id"], self.mm().load_order())
        self.assertEqual(exebytes.consent_problem(modsys.Mod(os.path.join(self.kit, "mods", r2["mod_id"]))), "")

    def test_result_reports_the_profile_state(self):
        self.assertFalse(self.imp(lambda line: False)["enabled"])
        self.assertTrue(self.imp(lambda line: True)["enabled"])


class HomeRow(Base):
    def test_program_label_survives_the_dependency_warning(self):
        from d5gui.pages import home
        m = make(self.kit, "a", [PATCH])
        line = modinfo.one_line(m)
        self.assertTrue(line.startswith("⚠ " + exebytes.LABEL))
        sub = home.mod_subtitle(line, ["Base Mod"])
        self.assertIn("⚠ " + exebytes.LABEL, sub)          # the program-change label is not replaced
        self.assertIn("⚠ needs Base Mod", sub)
        self.assertEqual(home.mod_subtitle("plain text"), "plain text")
        self.assertEqual(home.mod_subtitle("", ["Base Mod"]), "⚠ needs Base Mod")


if __name__ == "__main__":
    unittest.main()
