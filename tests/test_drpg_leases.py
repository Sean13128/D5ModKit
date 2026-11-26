"""DRPG v2 lease/pin manifest: counts, ownership, collisions and pin invalidation.

Every test runs on a synthetic inventory; no game, kit install or private art is
read.  The negative control mutates one claim at a time and requires the checker
to name it.
"""
import copy
import unittest

from d5lib.importers import drpg_leases as leases


def synthetic_grouping(bases=146, costumes=89):
    characters = []
    look = 10
    for b in range(1, bases + 1):
        group = {"base_id": b, "name": f"Base {b}", "kind": "humanoid",
                 "best_base_look_id": look, "look_ids": [look], "costume_ids": [],
                 "eligible": True, "looks": [{"id": look, "en": f"Base {b}",
                                              "type": "humanoid"}]}
        if b <= costumes:
            look += 1
            group["look_ids"].append(look)
            group["costume_ids"].append(look)
            group["looks"].append({"id": look, "en": f"Look {b}", "type": "humanoid"})
        characters.append(group)
        look += 1
    return {"schema": "drpg-grouping-decisions/1", "characters": characters}


def synthetic_inventory(**over):
    base = dict(vanilla_ids=set(), installed_char_ids=set(), used_art=set(),
                face_anims=set(), banner_anims=set(), lease_identities=set(),
                helper_ids=set(),
                pins={"inventory_sha256": "a" * 64, "grouping_sha256": "b" * 64,
                      "allocation_sha256": "c" * 64, "audit_sha256": "d" * 64,
                      "ownership_manifest_sha256": "e" * 64})
    base.update(over)
    return leases.Inventory(**base)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.grouping = synthetic_grouping()
        self.inv = synthetic_inventory()

    def build(self):
        return leases.build(self.grouping, self.inv, generated="2026-11-06")

    def test_build_is_clean_and_complete(self):
        m = self.build()
        self.assertEqual(leases.check(m, self.inv), [])
        self.assertEqual(len(m["bases"]), 146)
        self.assertEqual(len(m["costumes"]), 89)
        self.assertEqual(m["counts"]["looks"], 235)
        self.assertEqual(len({b["class_id"] for b in m["bases"]}), 146)
        self.assertEqual(len({c["class_id"] for c in m["costumes"]}), 89)
        self.assertEqual(len({b["art"] for b in m["bases"]}
                             | {c["art"] for c in m["costumes"]}), 235)

    def test_every_look_has_one_owner_and_bands_hold(self):
        m = self.build()
        owners = {b["lease"] for b in m["bases"]}
        for c in m["costumes"]:
            self.assertIn(c["owner"], owners)
            self.assertEqual(c["sprite_id"], c["color_id"])
            self.assertEqual(c["sprite_id"], c["art"])
            self.assertGreaterEqual(c["class_id"], leases.COSTUME_CLASS_BAND[0])
            self.assertLessEqual(c["class_id"], leases.COSTUME_CLASS_BAND[1])
            self.assertEqual(c["class_id"] % 10, 0)
            self.assertFalse(leases.OVERLORD_BAND[0] <= c["class_id"] <= leases.OVERLORD_BAND[1])
        for b in m["bases"]:
            self.assertEqual((b["class_id"], b["sprite_id"], b["color_id"]),
                             (b["class_id"], b["art"], b["art"]))
            self.assertLess(b["class_id"], 1000)

    def test_spare_low_rows_are_recorded_unspent(self):
        m = self.build()
        leased = {b["class_id"] for b in m["bases"]}
        spare = set(m["reserved"]["spare_low_rows"])
        self.assertFalse(leased & spare)
        self.assertEqual(len(leased) + len(spare), len(self.inv.free_low_rows()))
        self.assertLessEqual(len(m["reserved"]["sample_zed_rows"]), 10)
        self.assertFalse(set(m["reserved"]["sample_zed_rows"]) & leased)

    def test_moved_kit_invalidates_manifest(self):
        m = self.build()
        moved = synthetic_inventory(pins=dict(self.inv.pins, inventory_sha256="f" * 64))
        problems = leases.check(m, moved)
        self.assertTrue(any("pin inventory_sha256" in p for p in problems), problems)

    def test_negative_control_art_collision_fails(self):
        m = self.build()
        colliding = synthetic_inventory(used_art={m["costumes"][0]["art"] + 2})
        problems = leases.check(m, colliding)
        self.assertTrue(any("already used" in p for p in problems), problems)

    def test_negative_control_vanilla_row_fails(self):
        m = self.build()
        row = next(b["class_id"] for b in m["bases"]
                   if b["class_id"] not in self.inv.dummy_rows)
        colliding = synthetic_inventory(vanilla_ids={row})
        problems = leases.check(m, colliding)
        self.assertTrue(any("is not free" in p for p in problems), problems)

    def test_negative_control_duplicate_claim_fails(self):
        m = self.build()
        m["costumes"][1]["art"] = m["costumes"][0]["art"]
        m["costumes"][1]["class_id"] = m["costumes"][0]["class_id"]
        problems = leases.check(m, self.inv)
        self.assertTrue(any("claimed by both" in p for p in problems), problems)

    def test_negative_control_colliding_copy_of_the_whole_manifest_fails(self):
        """The card's required control: a deliberately colliding copy must fail."""
        m = self.build()
        copy_m = copy.deepcopy(m)
        copy_m["costumes"][0]["claims"]["resident_face"] = [10 ** 6]
        copy_m["costumes"][0]["art"] = copy_m["bases"][0]["art"]
        copy_m["costumes"][0]["sprite_id"] = copy_m["costumes"][0]["art"]
        copy_m["costumes"][0]["color_id"] = copy_m["costumes"][0]["art"]
        self.assertTrue(leases.check(copy_m, self.inv))

    def test_missing_low_rows_refuse_a_lease(self):
        rows = self.inv.free_low_rows()
        inv = self.inv
        for n in rows:
            inv.vanilla_ids.add(n)
            inv.dummy_rows.discard(n)
        with self.assertRaises(ValueError):
            leases.build(self.grouping, inv, generated="2026-11-06")

    def test_planted_extra_root_collision_fails_check(self):
        """A candidate pack (not installed yet) that claims a leased row's slot file must fail the check:
        the union of installed + candidate roots is what the inventory is free against."""
        import json
        import tempfile
        from pathlib import Path
        m = self.build()
        row = m["bases"][5]["class_id"]
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "D4_Planted"
            (pack / "files/Anime/ANM_HI_JP.dat").mkdir(parents=True)
            (pack / "mod.json").write_text("{}")
            (pack / "files/Anime/ANM_HI_JP.dat" / ("anm%05d.lzs" % (row + 2))).write_bytes(b"x")
            claims = leases._Claims()
            leases.scan_mod_root(Path(tmp), None, claims, "extra:cand", None)
            inv = synthetic_inventory(used_art=claims.used)
            self.assertIn("extra:cand:D4_Planted", claims.who["art"][row + 2])
            problems = leases.check(m, inv)
            self.assertTrue(any("already used" in p for p in problems), problems)
            self.assertTrue(any(m["bases"][5]["lease"] in p for p in problems), problems)

    def test_rebase_moves_only_colliding_bases_and_stays_clean(self):
        m = self.build()
        victim = m["bases"][7]
        colliding = synthetic_inventory(used_art={victim["class_id"] + 2})
        self.assertTrue(leases.check(m, colliding))
        new, moved = leases.rebase(m, colliding, generated="2026-11-09")
        self.assertEqual(list(moved), [victim["lease"]])
        self.assertEqual(leases.check(new, colliding, pins_expected={}), [])
        for old_b, new_b in zip(m["bases"], new["bases"]):
            if old_b["lease"] != victim["lease"]:
                self.assertEqual(old_b, new_b)
            else:
                self.assertNotEqual(old_b["class_id"], new_b["class_id"])
                self.assertEqual(old_b["art"], new_b["art"])
        strip = lambda cs: [{k: v for k, v in c.items() if k != "owner_class_id"} for c in cs]
        self.assertEqual(strip(m["costumes"]), strip(new["costumes"]))
        for c in new["costumes"]:
            owner = next(b for b in new["bases"] if b["lease"] == c["owner"])
            self.assertEqual(c["owner_class_id"], owner["class_id"])
        self.assertFalse(set(new["reserved"]["sample_zed_rows"]) & {b["class_id"] for b in new["bases"]})
        self.assertNotIn(moved[victim["lease"]][1], leases.SAMPLE_ZED_ROWS)

    def test_pin_namespaces_keeps_free_values_and_moves_taken_ones(self):
        m = self.build()
        leases_ = [b["lease"] for b in m["bases"]][:3]
        current = {l: {"help_id": 4000 + i, "quest_id": 100 + i, "quest_slot": 500 + i}
                   for i, l in enumerate(leases_)}
        # a candidate pack already holds slot 501 and quest id 102
        new, moved = leases.pin_namespaces(m, current, help_ids=set(), quest_ids={102}, slots={501}, first=())
        pins = {b["lease"]: b["namespaces"] for b in new["bases"]}
        self.assertEqual(pins[leases_[0]], {"help_id": 4000, "quest_id": 100, "quest_slot": 500})
        self.assertNotEqual(pins[leases_[1]]["quest_slot"], 501)
        self.assertNotEqual(pins[leases_[2]]["quest_id"], 102)
        self.assertTrue({leases_[1], leases_[2]} <= set(moved))
        self.assertNotIn(leases_[0], moved)
        for field in ("help_id", "quest_id", "quest_slot"):      # no two bases share a value, ever
            vals = [b["namespaces"][field] for b in new["bases"]]
            self.assertEqual(len(vals), len(set(vals)))
        self.assertNotIn("namespaces", m["bases"][0])             # the input manifest is not mutated

    def test_reserve_honours_pins_and_avoids_them_for_the_rest(self):
        from d5lib.importers import _drpg_namespaces as ns
        calls = {}
        orig = ns.taken_namespaces
        ns.taken_namespaces = lambda fs, root, extra=(): (set(), set(), {0, 1})
        try:
            pin = {"help_id": 4000, "quest_id": 1, "quest_slot": 2}
            out = ns.reserve(["drpg:a", "drpg:b"], None, ".", pinned={"drpg:a": pin})
        finally:
            ns.taken_namespaces = orig
        self.assertEqual(out["drpg:a"], pin)
        self.assertNotEqual(out["drpg:b"]["quest_slot"], 2)       # taken by the pin
        self.assertNotEqual(out["drpg:b"]["quest_id"], 1)
        self.assertNotEqual(out["drpg:b"]["help_id"], 4000)

    def test_release_moves_only_what_the_union_claims_and_never_zed(self):
        m = self.build()
        victim = m["bases"][9]
        zed = m["bases"][0]["lease"]
        r, a = victim["class_id"], victim["art"]
        # another importer's pack ships anm 10000+r (the gate counts it) and a char.dat row at the costume's class id
        costume = next(c for c in m["costumes"] if c["owner"] == victim["lease"])
        claimed = {"anm": {r + 10000}, "char.dat": {costume["class_id"]}}
        new, moved = leases.release(m, self.inv, claimed, keep=(zed,))
        self.assertEqual(set(moved), {victim["lease"], costume["lease"]})
        self.assertNotEqual(new["bases"][9]["class_id"], r)
        self.assertEqual(new["bases"][9]["art"], a)                      # art untouched
        for i, (old_b, new_b) in enumerate(zip(m["bases"], new["bases"])):
            if i != 9:
                self.assertEqual(old_b, new_b)
        nc = next(c for c in new["costumes"] if c["lease"] == costume["lease"])
        self.assertNotEqual(nc["class_id"], costume["class_id"])
        self.assertEqual(nc["owner_class_id"], new["bases"][9]["class_id"])
        # the moved lease clears every claimed number, and the manifest is still internally clean
        mine = leases.base_gate_anm(new["bases"][9]["class_id"], new["bases"][9]["art"])
        self.assertFalse(mine & claimed["anm"])
        self.assertEqual(leases.check(new, self.inv, pins_expected={}), [])
        # a pinned lease that collides raises instead of moving
        with self.assertRaises(ValueError):
            leases.release(m, self.inv, {"anm": {m["bases"][0]["class_id"] + 2}}, keep=(zed,))


if __name__ == "__main__":
    unittest.main()
