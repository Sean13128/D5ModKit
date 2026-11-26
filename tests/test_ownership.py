"""Allocation manifest + collision checker (offline; synthetic claims, no game or kit state).

The manifest is generated from the kit's own constants (d5lib/newclasses, masteryext, voices, skills),
so these tests are the drift gate: if an allocation constant moves, the manifest test fails until the
manifest, the ownership notes and the report are updated together.
"""
import json
import os
import subprocess
import sys
import unittest

from d5lib import masteryext, newclasses, ownership, skills, voices

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures", "ownership")
MANIFEST = os.path.join(ROOT, "d5lib", "data", "ownership_manifest.json")


def kit(*parts):
    return os.path.join(ROOT, "tools", *parts)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = ownership.load(MANIFEST)

    def test_self_check_is_clean(self):
        self.assertEqual([str(f) for f in ownership.errors(ownership.check_manifest(self.manifest))], [])

    def test_committed_manifest_matches_the_builder(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        try:
            import build_ownership_manifest as builder
        finally:
            sys.path.pop(0)
        with open(MANIFEST, "r", encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(builder.build(), committed,
                         "ownership_manifest.json is stale: run tools/build_ownership_manifest.py")

    def test_every_namespace_the_task_names_exists(self):
        for name in ("unlock_flag", "mastery_slot", "job_class_id", "char_dat_row", "special_id",
                     "evility_id", "wish_id", "database_member", "anm_id", "voice_id", "script_event_id"):
            self.assertIn(name, self.manifest.namespaces)

    def test_every_kit_family_row_and_flag_is_owned_by_the_kit(self):
        rows = self.manifest.namespaces["char_dat_row"]
        jobs = self.manifest.namespaces["job_class_id"]
        flags = self.manifest.namespaces["unlock_flag"]
        for family in newclasses.ALL_FAMILIES:
            for rank in range(6):
                cls = family + rank
                row = rows.band_at(cls)
                job = jobs.band_at(cls)
                self.assertIsNotNone(row, cls)
                self.assertIsNotNone(job, cls)
                if 1350 <= cls <= 1355:
                    self.assertEqual(row.owner, "contested", cls)
                    self.assertEqual(job.owner, "contested", cls)
                    continue
                self.assertEqual(row.owner, "kit", f"char row {cls}")
                self.assertEqual(job.owner, "kit", f"class id {cls}")

    def test_flag_block_matches_the_code(self):
        flags = self.manifest.namespaces["unlock_flag"]
        for index in (0, 1, 8, 20, len(newclasses.ALL_FAMILIES) - 1):
            for rank in range(6):
                flag = newclasses.FLAG_BASE + 6 * index + rank
                band = flags.band_at(flag)
                self.assertIsNotNone(band, flag)
                self.assertEqual(band.owner, "kit", flag)
        self.assertEqual(flags.band_at(newclasses.FLAG_LAST).owner, "kit")

    def test_mastery_slots_47_to_52_are_the_kit_band(self):
        slots = self.manifest.namespaces["mastery_slot"]
        self.assertEqual(slots.band_at(masteryext.SLOT_FIRST - 1).owner, "vanilla")
        for slot in range(masteryext.SLOT_FIRST, masteryext.SLOT_FIRST + masteryext.SLOT_COUNT):
            self.assertEqual(slots.band_at(slot).owner, "kit", slot)
        self.assertIsNone(slots.band_at(masteryext.RANK_SLOTS))

    def test_voice_band_matches_the_code(self):
        voices_ns = self.manifest.namespaces["voice_id"]
        self.assertEqual(voices_ns.band_at(voices.CUSTOM_FIRST).owner, "kit")
        self.assertEqual(voices_ns.band_at(voices.CUSTOM_LAST).owner, "kit")

    def test_armor_knight_rows_are_contested(self):
        band = self.manifest.namespaces["char_dat_row"].band_at(1353)
        self.assertEqual((band.start, band.end, band.owner, band.status), (1350, 1355, "contested", "contested"))
        self.assertEqual(set(band.claimants), {"kit", "overlord"})

    def test_overlord_class_band_is_reserved(self):
        for ns in ("job_class_id", "char_dat_row"):
            band = self.manifest.namespaces[ns].band_at(20000)
            self.assertEqual(band.owner, "overlord", ns)
        self.assertEqual(self.manifest.namespaces["job_class_id"].band_at(21999).owner, "overlord")


class ClaimTest(unittest.TestCase):
    def setUp(self):
        self.manifest = ownership.load(MANIFEST)

    def kinds(self, claims):
        return sorted(f.kind for f in ownership.check_claims(self.manifest, claims))

    def test_a_kit_class_lease_is_clean(self):
        claims = [ownership.Claim("kit:d4-class", "job_class_id", 14080, 14085)]
        self.assertEqual([str(f) for f in ownership.check_claims(self.manifest, claims)], [])

    def test_armor_knight_claim_is_refused_as_contested(self):
        claims = [ownership.Claim("kit:pilot", "char_dat_row", 1350, 1355),
                  ownership.Claim("kit:pilot", "job_class_id", 1350, 1355)]
        self.assertEqual(self.kinds(claims), ["contested", "contested"])

    def test_overlord_class_ids_are_refused(self):
        claims = [ownership.Claim("kit:import", "job_class_id", 20000, 20005)]
        self.assertIn("reserved_id", self.kinds(claims))

    def test_registry_identity_shape(self):
        # 6 ranks from a base that is a multiple of ten is the only shape a lease may have
        self.assertEqual(self.kinds([ownership.Claim("kit:x", "job_class_id", 14080, 14085)]), [])
        self.assertEqual(self.kinds([ownership.Claim("kit:x", "job_class_id", 22770, 22775)]), [])
        self.assertIn("registry_step", self.kinds([ownership.Claim("kit:x", "job_class_id", 14085, 14090)]))
        self.assertIn("registry_ranks", self.kinds([ownership.Claim("kit:x", "job_class_id", 14080, 14087)]))
        # 9995 is a vanilla row id, not a registry identity: it is refused, but as an owner mismatch
        self.assertEqual(self.kinds([ownership.Claim("kit:x", "job_class_id", 9995, 9995)]), ["not_owned"])

    def test_two_holders_may_not_claim_the_same_ids(self):
        claims = [ownership.Claim("kit:a", "evility_id", 7048, 7049),
                  ownership.Claim("kit:b", "evility_id", 7049, 7050)]
        self.assertIn("duplicate_claim", self.kinds(claims))

    def test_one_mod_claiming_twice_is_only_a_warning(self):
        claims = [ownership.Claim("kit:a", "evility_id", 7048, 7049),
                  ownership.Claim("kit:a", "evility_id", 7049, 7050)]
        findings = ownership.check_claims(self.manifest, claims)
        self.assertEqual([f.kind for f in ownership.errors(findings)], [])
        self.assertIn("self_overlap", [f.kind for f in findings])

    def test_unallocated_bands_are_not_free(self):
        claims = [ownership.Claim("kit:x", "char_dat_row", 3000, 3005)]
        self.assertEqual(self.kinds(claims), ["not_owned"])

    def test_a_claim_may_not_straddle_two_bands(self):
        claims = [ownership.Claim("kit:x", "char_dat_row", 1340, 1360)]
        self.assertIn("spans_bands", self.kinds(claims))

    def test_database_member_has_one_owner(self):
        ok = [ownership.Claim("kit:mod", "database_member", member="magic.dat")]
        self.assertEqual(self.kinds(ok), [])
        refused = [ownership.Claim("overlord:v3", "database_member", member="char.dat")]
        self.assertEqual(self.kinds(refused), ["not_owned"])
        unknown = [ownership.Claim("kit:mod", "database_member", member="not_a_member.dat")]
        self.assertEqual(self.kinds(unknown), ["unknown_member"])

    def test_unknown_namespace_is_refused(self):
        claims = [ownership.Claim("kit:x", "no_such_namespace", 1, 2)]
        self.assertEqual(self.kinds(claims), ["unknown_namespace"])


class UniqueGraphicsTest(unittest.TestCase):
    """A unique character owns its class id, its sprite set and its cut-in, all keyed to its char row.

    Found by the P4 Overlord-Stella conversion: three claims (anm 224-225, anm 10224, job_class_id 224)
    were refused because the manifest marked every id below 11270 vanilla, although a kit unique lives
    on a row id below 1000 and its graphics are numbered from that row (d5lib/d4unique.py:479).
    """

    def setUp(self):
        self.manifest = ownership.load(MANIFEST)
        self.rows = self.manifest.namespaces["char_dat_row"]
        self.jobs = self.manifest.namespaces["job_class_id"]
        self.anm = self.manifest.namespaces["anm_id"]
        self.rule = self.anm.rules["unique_keyed_graphics"]

    def findings(self, claims):
        return [str(f) for f in ownership.check_claims(self.manifest, claims)]

    def test_the_overlord_stella_claims_are_clean(self):
        claims = ownership.load_claims(os.path.join(FIXTURES, "overlord-stella-20300.json"))
        self.assertEqual(self.findings(claims), [])

    def test_a_unique_class_id_is_its_char_row(self):
        first, last = self.rule["rows"]
        self.assertEqual((first, last), (223, 403))
        # 931 (Shark King) and 941 (Xenolith) are the two re-leased single rows: a unique's class id
        # is its char row, so the class-id namespace follows the row.
        for row in (931, 941, first, 300, last):
            self.assertEqual(self.rows.band_at(row).owner, "kit", f"char row {row}")
            self.assertEqual(self.jobs.band_at(row).owner, "kit", f"class id {row}")

    def test_vanilla_unique_rows_and_their_graphics_stay_vanilla(self):
        # 80 is the vanilla 'Usalia (Awakening)' row: Xenolith no longer repurposes it.
        for value in (1, 79, 80, 81, 222, 404, 1009):
            self.assertEqual(self.jobs.band_at(value).owner, "vanilla", f"class id {value}")
        for value in (79, 81, 222, 404, 1007, 11269):
            self.assertEqual(self.anm.band_at(value).owner, "vanilla", f"anm {value}")

    def test_the_unique_bands_match_the_derivation_rule(self):
        first, last = self.rule["rows"]
        sprite = self.anm.band_at(first)
        portrait = self.anm.band_at(self.rule["portrait_offset"] + first)
        # the sprite band is the row band, the portrait band is the portrait window of every row in it
        self.assertEqual((sprite.start, sprite.end, sprite.owner), (first, last, "kit"))
        self.assertEqual((portrait.start, portrait.end, portrait.owner),
                         (self.rule["portrait_offset"] + first,
                          self.rule["portrait_offset"] + last + self.rule["portrait_span"] - 1, "kit"))

    def test_every_unique_row_that_fits_owns_its_sprite_set_and_cut_in(self):
        first, last = self.rule["rows"]
        span, offset = self.rule["sprite_span"], self.rule["portrait_offset"]
        for row in range(first, last + 1):
            claims = [ownership.Claim("kit:unique", "char_dat_row", row, row),
                      ownership.Claim("kit:unique", "job_class_id", row, row)]
            fits = row + span - 1 <= last
            if fits:
                claims.append(ownership.Claim("kit:unique", "anm_id", row, row + span - 1))
            claims.append(ownership.Claim("kit:unique", "anm_id", offset + row,
                                          offset + row + self.rule["portrait_span"] - 1))
            self.assertEqual(self.findings(claims), [], f"row {row} (sprite set fits: {fits})")

    def test_a_unique_whose_sprite_set_leaves_the_band_is_refused(self):
        first, last = self.rule["rows"]
        span = self.rule["sprite_span"]
        claims = [ownership.Claim("kit:unique", "anm_id", last, last + span - 1)]
        self.assertIn("spans_bands", [f.kind for f in ownership.check_claims(self.manifest, claims)])
        # one row lower the whole set still fits, so the refusal is about the row, not the width
        claims = [ownership.Claim("kit:unique", "anm_id", last - span + 1, last)]
        self.assertEqual(self.findings(claims), [])

    def test_the_re_leased_unique_rows_own_their_graphics_and_neighbours_do_not(self):
        # Shark King 931 (sprite 931-932, cut-in 10931-10932) and Xenolith 941 (941-942,
        # 10941-10942); the rows ten apart keep the two key sets disjoint.
        for value in (931, 932, 941, 942, 10931, 10932, 10941, 10942):
            self.assertEqual(self.anm.band_at(value).owner, "kit", f"anm {value}")
        # ... and 853-999 is the kit's unique sprite-lease pool (2026-10-27): no game file and no mod
        # file sits at n or 10000+n anywhere in it, so every number in the run is the kit's to lease.
        for value in (853, 930, 943, 999, 10853, 10930, 10943, 10999):
            self.assertEqual(self.anm.band_at(value).owner, "kit", f"anm {value}")
        # outside the pool everything stays vanilla
        for value in (80, 852, 1000, 10080, 10852, 11000):
            self.assertEqual(self.anm.band_at(value).owner, "vanilla", f"anm {value}")

    def test_a_unique_may_not_be_placed_on_a_vanilla_row(self):
        claims = [ownership.Claim("kit:unique", "char_dat_row", 430, 430),
                  ownership.Claim("kit:unique", "job_class_id", 430, 430)]
        self.assertEqual([f.kind for f in ownership.check_claims(self.manifest, claims)],
                         ["not_owned", "not_owned"])


class FixtureTest(unittest.TestCase):
    """The fixtures are the current installed set and Overlord v3, documented from reports (offline)."""

    def setUp(self):
        self.manifest = ownership.load(MANIFEST)
        self.kit_claims = ownership.load_claims(os.path.join(FIXTURES, "kit-installed-20261026.json"))
        self.overlord_claims = ownership.load_claims(os.path.join(FIXTURES, "overlord-v3.json"))

    def test_kit_fixture_has_the_armor_knight_collision_and_the_stale_xenolith_row(self):
        findings = ownership.check_claims(self.manifest, self.kit_claims)
        # 1350: the Armor Knight pilot vs Overlord's Human Dummy rewrite (contested, two namespaces).
        # 80: the installed DD2 pack still holds the vanilla Usalia row; the rebuilt mod uses 941, so
        # this finding is the record that the installed pack is out of date until it is replaced.
        self.assertEqual(sorted(f.kind for f in findings), ["contested", "contested", "not_owned"])
        self.assertEqual([f.start for f in findings if f.kind == "not_owned"], [80])

    def test_overlord_fixture_collides_only_where_ownership_is_shared(self):
        findings = ownership.check_claims(self.manifest, self.overlord_claims)
        kinds = sorted(f.kind for f in findings)
        self.assertEqual(kinds, ["not_owned", "not_owned", "not_owned"])
        namespaces = sorted(f.namespace for f in findings)
        self.assertEqual(namespaces, ["database_member", "mastery_slot", "unlock_flag"])

    def test_install_and_uninstall_round_trip_is_repeatable(self):
        baseline = ownership.Projection(self.manifest, self.kit_claims)
        before = baseline.snapshot()
        baseline.install(self.overlord_claims)
        installed = baseline.snapshot()
        self.assertNotEqual(before, installed)
        self.assertIn("overlord:v3", baseline.holders())
        baseline.uninstall("overlord:v3")
        self.assertEqual(baseline.snapshot(), before)
        # replaying the same plan gives the same projection, twice in a row
        twice = ownership.Projection(self.manifest, self.kit_claims)
        twice.install(self.overlord_claims).install(self.overlord_claims)
        self.assertEqual(twice.snapshot(), installed)
        twice.uninstall("overlord:v3")
        self.assertEqual(twice.snapshot(), before)

    def test_projection_names_the_owner_of_an_id(self):
        p = ownership.Projection(self.manifest, self.kit_claims + self.overlord_claims)
        self.assertEqual(p.owner_of("char_dat_row", 1350), "kit:d4-armor-knight-pilot")
        self.assertEqual(p.owner_of("char_dat_row", 20000), "overlord:v3")
        self.assertIsNone(p.owner_of("char_dat_row", 12000))

    def test_cli_exit_codes(self):
        python = sys.executable
        blank = subprocess.run([python, kit("check_ownership.py")], capture_output=True, text=True)
        self.assertEqual(blank.returncode, 0, blank.stdout + blank.stderr)
        dirty = subprocess.run([python, kit("check_ownership.py"), "--claims",
                                os.path.join(FIXTURES, "kit-installed-20261026.json")],
                               capture_output=True, text=True)
        self.assertEqual(dirty.returncode, 1, dirty.stdout + dirty.stderr)
        self.assertIn("contested", dirty.stdout)


if __name__ == "__main__":
    unittest.main()
