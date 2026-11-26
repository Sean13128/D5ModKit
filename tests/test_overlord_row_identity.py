"""The gate that would have caught LIVE12: every Overlord row edit lands on the row the pack names.

LIVE12 found the Rebalance reading vanilla at three named spots and concluded the packs were keyed by
`id` while the Kit applied them by index. They are not: they are diffs of whole tables, so their keys are
row indices, and re-diffing vanilla against his release reproduces every one of them (705 edits over 11
patch files in 5 of the 15 packs; the other 10 packs only append rows). The fix that followed -- treating
those index keys as ids -- moved the same 705 edits onto different rows.

So the check is not "does the key look like an id" but "is the row I just changed the row the pack meant".
This test proves it three ways:

  1. `tests/fixtures/overlord_row_identity.json` -- an independent witness, produced from his release file
     by `tools/overlord_port/audit_pack_keys.py`, naming the identity of every row each patch edits. The
     fixture is checked against the schemas here; no game data is stored in the repo.
  2. every patch in a built bundle, applied to its own vanilla table, must agree with that witness on
     every row it edits, and must carry the same `expect` map (0 misses over all 15 packs).
  3. the whole profile applied in load order -- Overlord packs last, after the 137 packs that also touch
     these tables -- must still be 0 misses, which is the case LIVE12's reading could not see.

Run against a built bundle:  OLFIX_BUNDLE=/Volumes/Data/Projects/D5/Builds/LIVE5_TEST16OL-20261030b
Without a bundle / vanilla copy / his release the bundle-dependent tests skip and name what is missing.
"""
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "overlord_port"))

from d5lib import database, dbpatch   # noqa: E402
import audit_pack_keys                 # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "overlord_row_identity.json")


def project_root(start=ROOT):
    """the D5 project root above this checkout (a checkout can be a worktree under Local/Worktrees)."""
    env = os.environ.get("D5_PROJECT_ROOT")
    if env:
        return env
    p = os.path.abspath(start)
    while p != os.path.dirname(p):
        if os.path.isdir(os.path.join(p, "Builds")):
            return p
        p = os.path.dirname(p)
    return os.path.dirname(os.path.dirname(os.path.abspath(start)))


PROJECTS = project_root()


def newest_bundle():
    env = os.environ.get("OLFIX_BUNDLE")
    if env:
        return env
    hits = sorted(glob.glob(os.path.join(PROJECTS, "Builds", "LIVE5_TEST16OL-*")))
    return hits[-1] if hits else None


BUNDLE = newest_bundle()
VANILLA = os.environ.get("OLFIX_VANILLA", audit_pack_keys.DEFAULT_VANILLA)
RELEASE = os.environ.get("OLFIX_RELEASE", audit_pack_keys.DEFAULT_RELEASE)
HAVE_BUNDLE = bool(BUNDLE and os.path.isdir(os.path.join(BUNDLE, "mods")))
HAVE_VANILLA = bool(VANILLA and os.path.exists(VANILLA))
HAVE_RELEASE = bool(RELEASE and os.path.isdir(os.path.join(RELEASE, audit_pack_keys.RELEASE_SUBDIR)))
WHY_SKIP = ("needs a built Overlord bundle and the vanilla member copy: "
            f"bundle={BUNDLE} mods={HAVE_BUNDLE} vanilla={VANILLA} present={HAVE_VANILLA}")


def fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class WitnessTest(unittest.TestCase):
    """The committed witness is well-formed and usable as a checker on its own."""

    def test_every_named_row_is_a_column_of_its_table_and_the_name_is_unique(self):
        doc = fixture()
        self.assertEqual(len(doc), 5, "5 of the 15 packs edit rows; the rest append")
        total = 0
        for mod, tables in doc.items():
            for member, spec in tables.items():
                schema = database.get_schema(member)
                fields = {f.name for f in schema.fields}
                by = spec["by"].split("#")[0]
                self.assertIn(by, fields, f"{member}: {by!r} is not a column")
                self.assertTrue(spec["rows"], f"{mod}/{member}: empty expect map")
                total += len(spec["rows"])
                if "#ord" not in spec["by"]:
                    names = list(spec["rows"].values())
                    self.assertEqual(len(names), len(set(map(str, names))),
                                     f"{member}: an identity is named twice")
        self.assertEqual(total, 705, "the witness covers every row edit in the 15 packs")

    def test_the_rebalance_covers_the_11_patch_files_that_edit_rows(self):
        doc = fixture()
        rebalance = doc["Overlord Rebalance"]
        self.assertEqual(sorted(rebalance), ["GroupHelp.dat", "Skill.dat", "SugorokuMapSetting.dat",
                                            "WishDataBase.dat", "char.dat", "item.dat", "magic.dat"])
        self.assertEqual(len(rebalance["Skill.dat"]["rows"]), 323)
        self.assertEqual(len(rebalance["item.dat"]["rows"]), 124)


@unittest.skipUnless(HAVE_BUNDLE and HAVE_VANILLA and HAVE_RELEASE, WHY_SKIP)
class BundleGateTest(unittest.TestCase):
    """0 misses over all 15 packs, against the bundle that will be installed."""

    @classmethod
    def setUpClass(cls):
        cls.mods = os.path.join(BUNDLE, "mods")
        cls.vanilla = database.load_database(VANILLA)
        cls.witness = fixture()
        cls.report = [audit_pack_keys.audit_one(cls.mods, RELEASE, cls.vanilla, *spec)
                      for spec in audit_pack_keys.patch_files(cls.mods)]

    def test_all_fifteen_packs_are_present_and_accounted_for(self):
        self.assertEqual(len(audit_pack_keys.overlord_mods(self.mods)), 15)
        self.assertEqual(len(self.report), 23, "23 patch files across the 15 packs")
        self.assertEqual(len({r["mod"] for r in self.report}), 15)

    def test_every_patch_is_positional_not_id_keyed(self):
        for r in self.report:
            self.assertIsNone(r["key"], f"{r['patch']}: declares a key column")
            if r["changed_rows"]:
                self.assertEqual(r["space"], "index", f"{r['patch']}: {r['verdict']}")

    def test_zero_misses_over_all_fifteen_packs(self):
        misses = []
        for r in self.report:
            if not r["changed_rows"]:
                continue
            again = dbpatch.apply_patch(database.load_table(r["member"], self.vanilla[r["member"]].to_bytes()),
                                        {k: v for k, v in self._patch(r["patch"]).items() if k != "expect"})
            row = dict(r, warnings=len(again))
            if row["content_ok"] != row["content_total"]:
                misses.append(f"{r['patch']}: {row['content_ok']}/{row['content_total']} rows carry his values")
            if row["aligned"] is not True:
                misses.append(f"{r['patch']}: his row identity differs at {row.get('aligned_mismatches')}")
            if row["fresh_diff_same_keys"] is not True:
                misses.append(f"{r['patch']}: re-diffing his file does not reproduce these keys")
        self.assertEqual(misses, [], "every edit must land on the row the pack names")

    def test_each_patch_carries_the_identity_of_the_rows_it_edits(self):
        missing = []
        for r in self.report:
            if not r["changed_rows"]:
                continue
            want = self.witness[r["mod"]][r["member"]]
            patch = self._patch(r["patch"])
            if patch.get("expect") != want:
                missing.append(r["patch"])
        self.assertEqual(missing, [], "a patch must carry the `expect` map the guard reads")

    def test_the_expected_guard_refuses_a_shifted_table_and_keeps_the_rest(self):
        """The same patches, onto a table with one extra row in front: nothing may be written to a stranger."""
        member = "Skill.dat"
        spec = next(r for r in self.report if r["member"] == member and r["changed_rows"])
        patch = self._patch(spec["patch"])
        t = database.load_table(member, self.vanilla[member].to_bytes())
        blank = t.new_row()
        blank["id"] = 999999
        t.rows.insert(0, blank)
        before = [r.to_dict() for r in t.rows]
        warns = dbpatch.apply_patch(t, patch)
        after = [r.to_dict() for r in t.rows]
        self.assertEqual(after[0], before[0], "the inserted row must not be edited")
        self.assertTrue(any("edit refused" in w for w in warns))
        # every row that did change is still the row this patch names
        named = {int(k): str(v) for k, v in patch["expect"]["rows"].items()}
        for i, (a, b) in enumerate(zip(before, after)):
            if a != b:
                self.assertIn(i, {k + 1 for k in named}, f"row {i} changed but is not in the patch")
                self.assertEqual(str(t.rows[i]["id"]), named[i - 1])

    def _patch(self, rel):
        with open(os.path.join(self.mods, rel), encoding="utf-8") as f:
            return json.load(f)


@unittest.skipUnless(HAVE_BUNDLE and HAVE_VANILLA, WHY_SKIP)
class ProfileOrderTest(unittest.TestCase):
    """The real composition: every pack in the profile's load order, then the Overlord packs last."""

    def test_the_whole_profile_still_lands_every_overlord_edit_on_its_own_row(self):
        mods = os.path.join(BUNDLE, "mods")
        profile = os.path.join(BUNDLE, "profile",
                               os.environ.get("OLFIX_PROFILE", "LIVE5_TEST16OL"), "load_order.json")
        with open(profile, encoding="utf-8") as f:
            order = json.load(f)
        vanilla = database.load_database(VANILLA)
        members = {}
        refused, applied = [], 0
        for folder in order:
            d = os.path.join(mods, folder, "patches", "db")
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    patch = json.load(f)
                member = patch.get("table") or name[:-5]
                if name[:-5] in ("charhelp.dat", "charPersonal.dat", "SugorokuMapSetting.dat") and \
                        folder.startswith("Overlord") and patch.get("rows"):
                    # a member with no unique id may still be edited, but only behind an identity guard
                    self.assertTrue(patch.get("expect"), f"{folder}/{name}: positional-only member needs `expect`")
                    self.assertIn(patch["expect"]["by"], ("id", "id#ord", "name_EN"),
                                  f"{folder}/{name}: {patch['expect']['by']!r} is not an identity")
                table = database.load_table(member, members.get(member) or vanilla[member].to_bytes())
                warns = dbpatch.apply_patch(table, patch)
                applied += 1
                refused += [w for w in warns if "edit refused" in w]
                members[member] = table.to_bytes()
        self.assertEqual(refused, [], "no Overlord (or other) edit may be refused at install time")
        self.assertGreater(applied, 200, "the profile really was applied")

        witness = fixture()
        misses = []
        for mod, tables in witness.items():
            for member, spec in tables.items():
                if member not in members:
                    misses.append(f"{member}: never applied")
                    continue
                table = database.load_table(member, members[member])
                for idx, want in spec["rows"].items():
                    i = int(idx)
                    col = spec["by"].split("#")[0]
                    got = table.rows[i][col] if i < len(table.rows) else None
                    if str(got) != str(want):
                        misses.append(f"{mod}/{member} row {i}: {col} {got!r}, pack names {want!r}")
        self.assertEqual(misses[:10], [], f"{len(misses)} misses in the built profile")


if __name__ == "__main__":
    unittest.main()
