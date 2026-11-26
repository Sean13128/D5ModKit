"""Hook arbitration: one owner per contested site, decided by capability (Sean, 2026-10-30 08:15).

Synthetic: no executable is read here.  `arbitrate.compare` works on plain dicts, and the policy module
(`d5lib.overlord_compat`) is pure, so the *decision* can be tested without the game.  The build-time
proof that the decision reached the bytes is `verify_yield`, exercised against the pinned exe and a
built payload by `tools/overlord_port/yield_check.py`.
"""
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "overlord_port"))
sys.path.insert(0, ROOT)

import arbitrate                      # noqa: E402
from d5lib import overlord_compat     # noqa: E402

CONTENT = {"runtime": False, "plugins": False, "mods": []}
RUNTIME = {"runtime": True, "plugins": False, "mods": [], "families": None}
RUNTIME_PLUGINS = {"runtime": True, "plugins": True, "mods": []}
# his runtime without any Kit steal/sp_drain row: the Kit is not a competitor for those effect sites
RUNTIME_NO_ROWS = {"runtime": True, "plugins": False, "mods": [], "families": ["power"]}


def site(owner, name, va, length):
    return {"owner": owner, "name": name, "va": va, "len": length}


class OwnershipTest(unittest.TestCase):
    def test_every_contested_site_has_exactly_one_owner_in_every_configuration(self):
        for cfg in (CONTENT, RUNTIME, RUNTIME_PLUGINS):
            owners = overlord_compat.resolve(cfg)
            self.assertEqual(len(owners), 11)          # + SUBCLASS_CLASS_TAB (SUBCLASS2)
            self.assertTrue(all(v["owner"] in ("kit", "overlord", "both") for v in owners.values()))

    def test_content_only_install_keeps_every_site(self):
        self.assertEqual(overlord_compat.yielded_sites(CONTENT), set())
        self.assertEqual(overlord_compat.double_apply(CONTENT), [])

    def test_capability_rule_gives_the_wider_side_the_site(self):
        yielded = overlord_compat.yielded_sites(RUNTIME)
        # his charhelp rule covers every custom class id; ours is 1 of 95 identity checks
        self.assertIn(0x14029F753, yielded)
        # the two effect sites moved to the Kit: identical arithmetic, more authorable rows
        self.assertNotIn(0x1401AF6A2, yielded)
        self.assertNotIn(0x140552080, yielded)
        self.assertEqual(overlord_compat.owner_of(0x1401AF6A2, RUNTIME), "kit")
        self.assertEqual(overlord_compat.owner_of(0x140552080, RUNTIME), "kit")
        # the class-unlock site is his WIP only: the Kit keeps it
        self.assertNotIn(0x1401C62A0, yielded)
        # his ten palettes beat our five; the colour site is in the optional plugin
        self.assertNotIn(0x1404552F1, yielded)

    def test_the_visual_sites_follow_his_optional_plugin(self):
        yielded = overlord_compat.yielded_sites(RUNTIME_PLUGINS)
        for va in (0x1401A0880, 0x1401A3010, 0x1404552F1):
            self.assertIn(va, yielded)
        self.assertNotIn(0x1401C62A0, yielded)

    def test_the_overload_resolver_is_shared_because_the_bytes_are_disjoint(self):
        self.assertEqual(overlord_compat.owner_of(0x14015DBF0, RUNTIME_PLUGINS), "both")
        self.assertNotIn(0x14015DBF0, overlord_compat.yielded_sites(RUNTIME_PLUGINS))

    def test_a_kit_without_the_family_does_not_take_his_effect_site(self):
        self.assertEqual(overlord_compat.owner_of(0x1401AF6A2, RUNTIME_NO_ROWS), "overlord")
        self.assertIn(0x1401AF6A2, overlord_compat.yielded_sites(RUNTIME_NO_ROWS))
        # and with the family present it is the Kit's, in the same configuration
        self.assertEqual(overlord_compat.owner_of(0x1401AF6A2, RUNTIME), "kit")

    def test_the_sites_this_rule_moved(self):
        # two real moves (his hook now yields), plus the overload entry, which OLCOMPAT2 called his and
        # this rule calls shared: the Kit only ever patched the 11 callers, so no byte moves there.
        # SUBCLASS2: the Class tab sub-class switch (his core runtime, OLCOMPAT2 would have kept it his) is the Kit's.
        self.assertEqual(overlord_compat.changed_sites(RUNTIME),
                         {0x1401AF6A2: ("overlord", "kit"), 0x140552080: ("overlord", "kit"),
                          0x14015DBF0: ("overlord", "both"), 0x14029CA50: ("overlord", "kit")})
        self.assertEqual(overlord_compat.changed_sites(CONTENT), {})

    def test_every_site_carries_its_capability_evidence(self):
        for va, s in overlord_compat.SITES.items():
            for key in ("his_allows", "kit_allows", "winner", "why", "loser", "his_len", "kit_len"):
                self.assertTrue(s.get(key), f"{va:#x} has no {key}")
            self.assertIn(s["winner"], ("kit", "overlord", "both"))

    def test_the_effects_that_would_apply_twice_are_named(self):
        self.assertEqual(overlord_compat.double_apply(RUNTIME),
                         ["defense_power", "power", "range", "sp_drain_per_turn",
                          "steal_on_kill_percent"])
        # power / defense / range are the Kit's: his copy of those rows is the one that goes off
        self.assertTrue({"power", "defense_power", "range"} <= set(overlord_compat.double_apply(RUNTIME)))

    def test_the_gate_drops_exactly_the_yielded_hooks(self):
        hooks = [(0x14029F753, b"123456", "nop", 0xE9), (0x1404552F1, b"x" * 13, "nop", 0xE9)]
        overlord_compat.ACTIVE.update(RUNTIME)
        try:
            kept, dropped = overlord_compat.filter_hooks(b".d5id", hooks)
        finally:
            overlord_compat.ACTIVE.update(CONTENT)
        self.assertEqual([h[0] for h in kept], [0x1404552F1])
        self.assertEqual([h[0] for h in dropped], [0x14029F753])

    def test_the_gate_keeps_the_effect_sites_the_kit_now_owns(self):
        hooks = [(0x1401AF6A2, b"12345", "nop", 0xE9), (0x140552080, b"12345", "nop", 0xE9)]
        overlord_compat.ACTIVE.update(RUNTIME)
        try:
            kept, dropped = overlord_compat.filter_hooks(b".d5el", hooks)
        finally:
            overlord_compat.ACTIVE.update(CONTENT)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])

    def test_the_gate_is_inert_without_his_runtime(self):
        hooks = [(0x14029F753, b"123456", "nop", 0xE9)]
        kept, dropped = overlord_compat.filter_hooks(b".d5id", hooks)
        self.assertEqual((len(kept), dropped), (1, []))

    def test_configure_reads_a_runtime_package_and_ignores_a_content_one(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            content = os.path.join(d, "Overlord Edition")
            os.makedirs(os.path.join(content, "patches", "evilities"))
            with open(os.path.join(content, "mod.json"), "w") as f:
                json.dump({"overlord_package": {"converted_members": ["Skill.dat"]}}, f)
            with open(os.path.join(content, "patches", "evilities", "evilities.json"), "w") as f:
                json.dump({"evilities": {"20001": {"family": "steal_on_kill_percent",
                                                   "effects": [{"value": 15}]}}}, f)
            runtime = os.path.join(d, "Overlord Runtime")
            os.makedirs(runtime)
            with open(os.path.join(runtime, "mod.json"), "w") as f:
                json.dump({"overlord_package": {"runtime": True, "plugins": True}}, f)

            class Ctx:
                mod_folders = [content]
            self.assertFalse(overlord_compat.configure(Ctx())["runtime"])
            self.assertIn("steal_on_kill_percent", overlord_compat.ACTIVE["families"])
            Ctx.mod_folders = [content, runtime]
            state = overlord_compat.configure(Ctx())
            self.assertTrue(state["runtime"] and state["plugins"])
            self.assertIn("steal_on_kill_percent", state["families"])
            overlord_compat.ACTIVE.update(CONTENT)      # leave the module as found
            overlord_compat.ACTIVE["families"] = set()

    def test_a_row_that_declares_several_families_is_read_not_crashed(self):
        """LIVE12's third install blocker: `"family": ["stats","aura"]` raised TypeError (unhashable list) and
        aborted the whole install.  A row may declare several families; each one counts as shipped."""
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "D4_Class_1220")
            os.makedirs(os.path.join(folder, "patches", "evilities"))
            with open(os.path.join(folder, "patches", "evilities", "evilities.json"), "w") as f:
                json.dump({"evilities": {
                    "8181": {"family": ["stats", "aura"], "effects": [{"value": 5}]},
                    "8182": {"family": "steal_on_kill_percent", "effects": [{"value": 15}]},
                    "8183": [{"family": ["stats", 7, None]}, {"family": ""}],
                }}, f)
            self.assertEqual(overlord_compat.families_in(folder),
                             {"stats", "aura", "steal_on_kill_percent"})
            class Ctx:
                mod_folders = [folder]
            state = overlord_compat.configure(Ctx())
            self.assertEqual(set(state["families"]), {"stats", "aura", "steal_on_kill_percent"})
            # a list row can now take the effect site the old code would have died on
            self.assertEqual(overlord_compat.owner_of(0x1401AF6A2, dict(CONTENT, families=set(state["families"]))),
                             "kit")
            overlord_compat.ACTIVE.update(CONTENT)
            overlord_compat.ACTIVE["families"] = set()


class RuntimeSitesTest(unittest.TestCase):
    """configure() reserves his runtime's sites (data/overlord_sites.json) in the exe-site ledger"""

    def setUp(self):
        import json
        import tempfile
        from d5lib import exemap
        self.exemap, self.old = exemap, exemap.ACTIVE
        exemap.reset_ledger(reserved=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = os.path.join(self.tmp.name, "rt")
        os.makedirs(self.runtime)
        with open(os.path.join(self.runtime, "mod.json"), "w") as f:
            json.dump({"overlord_package": {"runtime": True, "plugins": True}}, f)

    def tearDown(self):
        self.exemap.use(self.old)
        self.exemap.reset_ledger(reserved=True)
        overlord_compat.ACTIVE.update(CONTENT)
        overlord_compat.ACTIVE["families"] = set()
        self.tmp.cleanup()

    def _configure(self, folders, steam=True):
        e = self.exemap
        e.use(e.Translator("9460a6411699a256faaf0daed6b90d903a7d6491" if steam else e.KNOWN_SHA1))

        class Ctx:
            mod_folders = folders
            log = lambda *a: None       # noqa: E731
        overlord_compat.configure(Ctx())

    def test_his_site_count(self):
        import json
        rows = json.load(open(os.path.join(os.path.dirname(overlord_compat.__file__), "data", "overlord_sites.json")))
        self.assertEqual(len(rows), 126)

    def test_runtime_preclaims_his_sites(self):
        e = self.exemap
        self._configure([self.runtime])
        va = 0x1401A0880
        held = [x for x in e.RESERVED if x["start"] == va]
        self.assertEqual(bool(held), overlord_compat.owner_of(va, overlord_compat.ACTIVE) == "overlord")
        # a site he owns outright clashes; the arbitrated ones the Kit holds are not reserved
        mine = [x for x in e.RESERVED if x["owner"] == "Overlord runtime"]
        self.assertTrue(mine)
        with e.owner("kit"), self.assertRaises(e.SiteClash):
            e.claim(mine[0]["start"], 2, "kit patch")
        yielded = overlord_compat.yielded_sites(overlord_compat.ACTIVE)
        self.assertIn(va, yielded)
        for v in set(overlord_compat.SITES) - yielded:
            self.assertFalse([x for x in mine if x["start"] == v], hex(v))

    def test_effect_sites_given_to_the_kit_are_not_reserved(self):
        self._configure([self.runtime])
        held = {x["start"] for x in self.exemap.RESERVED}
        self.assertFalse(held & set(overlord_compat.DOUBLE_APPLY))
        self.assertTrue({0x1401AF6A2, 0x140552080} <= set(overlord_compat.DOUBLE_APPLY))

    def test_content_config_claims_nothing(self):
        self._configure([])
        self.assertEqual(self.exemap.RESERVED, [])

    def test_other_build_reserves_nothing(self):
        self._configure([self.runtime], steam=False)
        self.assertEqual(self.exemap.RESERVED, [])


class ArbitrationTableTest(unittest.TestCase):
    """The table must reproduce the five byte overlaps and the two duplicate effects on its own."""

    def sites(self):
        return [
            site("kit", ".d5fi", 0x1401A0880, 5),
            site("overlord", "PORTRAIT_RESOLVER", 0x1401A0880, 14),
            site("kit", ".d5cl", 0x1401C62A0, 10),
            site("overlord", "hook_install@0x1c62a0", 0x1401C62A0, 13),
            site("kit-oleffects", "steal_on_kill_percent", 0x1401AF6A2, 5),
            site("overlord", "STEAL_ON_KILL_HOOK", 0x1401AF6A2, 5),
            site("kit-oleffects", "sp_drain_per_turn", 0x140552083, 5),
            site("overlord", "SP_DRAIN_HOOK", 0x140552080, 11),
            site("kit", ".d5el", 0x1401BF0F0, 5),
        ]

    def test_overlaps_are_fail_closed(self):
        overlaps = arbitrate.compare(self.sites())
        kinds = {(o["a"]["name"], o["b"]["name"]): o["verdict"] for o in overlaps}
        self.assertEqual(kinds[(".d5fi", "PORTRAIT_RESOLVER")], "needs-arbitration")
        self.assertEqual(kinds[(".d5cl", "hook_install@0x1c62a0")], "needs-arbitration")
        self.assertEqual(kinds[("steal_on_kill_percent", "STEAL_ON_KILL_HOOK")], "duplicate-effect")
        self.assertEqual(kinds[("sp_drain_per_turn", "SP_DRAIN_HOOK")], "duplicate-effect")

    def test_the_report_carries_the_ownership_table(self):
        report = arbitrate.ownership(CONTENT)
        self.assertEqual(len(report["sites"]), 11)
        self.assertEqual(report["kit_yields"], [])
        self.assertEqual(report["double_apply_rows_off"], [])
        runtime = arbitrate.ownership(RUNTIME)
        self.assertIn("0x14029f753", runtime["kit_yields"])
        self.assertIn("sp_drain_per_turn", runtime["double_apply_rows_off"])
        self.assertEqual(len(runtime["capability"]), 11)
        self.assertEqual(runtime["rule"], "more capability wins (Sean, 2026-10-30 08:15)")
        self.assertEqual(runtime["changed_by_this_rule"],
                         {"0x1401af6a2": ["overlord", "kit"], "0x140552080": ["overlord", "kit"],
                          "0x14015dbf0": ["overlord", "both"], "0x14029ca50": ["overlord", "kit"]})

    def test_every_documented_overlap_address_appears_in_the_policy(self):
        """The five byte overlaps of the earlier study are the five byte-range entries here."""
        byte_ranges = {va for va, s in overlord_compat.SITES.items() if s["kind"] == "byte-range"}
        self.assertEqual(byte_ranges, {0x1401A0880, 0x1401A3010, 0x1401C62A0,
                                       0x14029F753, 0x1404552F1})
        effects = {va for va, s in overlord_compat.SITES.items() if s["kind"] == "effect-site"}
        self.assertEqual(effects, {0x1401AF6A2, 0x140552080, 0x14015DBF0})
        natives = {va for va, s in overlord_compat.SITES.items() if s["kind"] == "native-hook"}
        self.assertEqual(natives, {0x14044A730, 0x140221793, 0x14029CA50})


class RecruitWishSitesTest(unittest.TestCase):
    """RECRUITCOMPAT1: the .d5wr native hooks are contested sites"""
    VIS, POST = 0x14044A730, 0x140221793

    def hooks(self):
        return [(self.VIS, b"", "", 0xE9), (self.POST, b"", "", 0xE9), (0x140000010, b"", "", 0xE9)]

    def test_owner_by_configuration(self):
        self.assertEqual(overlord_compat.owner_of(self.VIS, CONTENT), "kit")
        self.assertEqual(overlord_compat.owner_of(self.POST, CONTENT), "kit")
        for cfg in (RUNTIME, RUNTIME_PLUGINS):
            self.assertEqual(overlord_compat.owner_of(self.VIS, cfg), "overlord")
            self.assertEqual(overlord_compat.owner_of(self.POST, cfg), "overlord")
        self.assertEqual(overlord_compat.owner_of(self.VIS, dict(RUNTIME, wishes=False)), "kit")

    def test_other_sites_are_unchanged(self):
        before = {0x1401AF6A2: "kit", 0x140552080: "kit", 0x14015DBF0: "both", 0x14029F753: "overlord",
                  0x1401A0880: "overlord", 0x1401C62A0: "kit"}
        for va, want in before.items():
            self.assertEqual(overlord_compat.owner_of(va, RUNTIME_PLUGINS), want, hex(va))

    def test_native_filter_drops_only_the_wish_sites_under_runtime(self):
        saved = dict(overlord_compat.ACTIVE)
        try:
            overlord_compat.ACTIVE.update(runtime=True, plugins=False, wishes=True)
            kept, dropped = overlord_compat.filter_hooks(b".d5wr", self.hooks(), native=True)
            self.assertEqual([h[0] for h in dropped], [self.VIS, self.POST])
            self.assertEqual([h[0] for h in kept], [0x140000010])
            overlord_compat.ACTIVE.update(runtime=False)
            kept, dropped = overlord_compat.filter_hooks(b".d5wr", self.hooks(), native=True)
            self.assertEqual((len(kept), dropped), (3, []))
        finally:
            overlord_compat.ACTIVE.clear()
            overlord_compat.ACTIVE.update(saved)

    def test_configure_reads_wishes_flag(self):
        import json, tempfile
        saved = dict(overlord_compat.ACTIVE)
        try:
            with tempfile.TemporaryDirectory() as d:
                with open(os.path.join(d, "mod.json"), "w") as f:
                    json.dump({"overlord_package": {"runtime": True, "wishes": False}}, f)
                overlord_compat.configure(types.SimpleNamespace(mod_folders=[d], log=lambda *a: None))
                self.assertTrue(overlord_compat.ACTIVE["runtime"])
                self.assertFalse(overlord_compat.ACTIVE["wishes"])
                self.assertEqual(overlord_compat.owner_of(self.VIS, overlord_compat.ACTIVE), "kit")
        finally:
            overlord_compat.ACTIVE.clear()
            overlord_compat.ACTIVE.update(saved)


if __name__ == "__main__":
    unittest.main()
