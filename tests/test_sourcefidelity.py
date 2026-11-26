"""Synthetic profiles only: no game assets or alleged source-equivalence fixtures."""
import unittest

from d5lib import database, dbpatch
from d5lib import sourcefidelity as sf


def profile():
    return sf.from_profile(
        {"id": 42, "name": "Synthetic unit", "base": list(range(10, 18)),
         "aptitudes": [100] * 8, "growth": None,
         "evidence": {"table_sha256": "a" * 64}, "limitations": ["Synthetic fixture"]},
        game="synthetic", edition="synthetic-test-v1", rank_count=3)


def unit_rule(src, kind, name, **kwargs) -> dict:
    from copy import deepcopy
    feature = (src[kind].get(name) if kind in ("stats", "aptitudes")
               else next(item for item in src[kind] if item["name"] == name))
    return dict(kind=kind, name=name, scope="unit",
                source_game=src["source"]["game"], source_id=src["source"]["id"],
                source_rank_index=src["rank_index"], source_feature=deepcopy(feature),
                source_sha256=src["source"]["sha256"], source_edition=src["source"]["edition"],
                **kwargs)


def donor():
    table = database.Table("char.dat", database.get_schema("char.dat"))
    row = table.add_row(id=970, base_HP=99, apt_HP=90, mastery_sword=16,
                        learn1_skill=123, learn1_level=1, learn_count=1,
                        evility1=123, evility_count=1, overload_id=123)
    return row


class SourceFidelityTests(unittest.TestCase):
    def test_unit_rule_cannot_replay_across_source_context_or_feature(self):
        from copy import deepcopy
        from unittest.mock import patch
        src = profile()
        src["weapon_preferences"] = [{"name": "sword", "value": "S"}]
        rule = dict(kind="weapon_preferences", name="sword", scope="unit",
                    target_field="mastery_sword", value=20, relation="exact",
                    evidence="Synthetic row 42 rank 0 sword S ONLY",
                    source_sha256="a" * 64, source_edition="synthetic-test-v1",
                    source_game="synthetic", source_id=42, source_rank_index=0,
                    source_feature={"name": "sword", "value": "S"})
        encoded, report = sf.encode_gameplay(donor(), src, rules=[rule])
        self.assertEqual(encoded["mastery_sword"], 20)
        self.assertEqual(next(x["status"] for x in report["mappings"]
                              if x["path"] == "weapon_preferences.sword"),
                         "mapped-exact-reviewed")
        replay = deepcopy(src)
        replay["source"]["id"] = 43
        replay["weapon_preferences"][0]["value"] = "E"
        with patch.object(sf, "start_fresh") as writer:
            with self.assertRaisesRegex(ValueError, "rule source"):
                sf.encode_gameplay(donor(), replay, rules=[rule])
            writer.assert_not_called()
        for field, value in [("id", 43), ("game", "other-game"),
                             ("rank_index", 1), ("value", "E"),
                             ("edition", "other-edition"), ("sha256", "b" * 64)]:
            changed = deepcopy(src)
            if field == "rank_index":
                changed[field] = value
            elif field == "value":
                changed["weapon_preferences"][0][field] = value
            else:
                changed["source"][field] = value
            row = donor()
            original = bytes(row.raw)
            with self.subTest(field=field), patch.object(sf, "start_fresh") as writer:
                with self.assertRaisesRegex(ValueError, "rule source"):
                    sf.encode_gameplay(row, changed, rules=[rule])
                writer.assert_not_called()
                self.assertEqual(bytes(row.raw), original)

    def test_table_scope_deliberately_reuses_only_exact_skill_predicate(self):
        from copy import deepcopy
        src = profile()
        src["skills"] = [{"name": "Synthetic laser", "level": 5, "power": 10}]
        table = database.Table("magic.dat", database.get_schema("magic.dat"))
        table.add_row(id=9001, name_EN="Synthetic target")
        tables = {"magic.dat": table}
        rule = dict(scope="table", kind="skills", name="Synthetic laser",
                    source_game="synthetic", source_edition="synthetic-test-v1",
                    source_sha256="a" * 64, source_feature=deepcopy(src["skills"][0]),
                    target_id=9001, target_name="Synthetic target", animation_verified=True,
                    relation="exact", evidence="Synthetic deliberate table-wide equivalence")
        changed = deepcopy(src)
        changed["source"]["id"] = 43
        changed["rank_index"] = 1
        encoded, report = sf.encode_gameplay(donor(), changed, rules=[rule], tables=tables)
        self.assertEqual(encoded["learn1_skill"], 9001)
        self.assertEqual(encoded["learn1_level"], 5)
        self.assertIn(rule, [x.get("rule") for x in report["mappings"]])
        pinned = dict(rule, source_id=43, source_rank_index=1)
        self.assertEqual(sf.encode_gameplay(donor(), changed, rules=[pinned], tables=tables)[0]["learn1_skill"], 9001)
        for feature in [{"name": "Synthetic laser", "level": 5, "power": 11},
                        {"name": "Synthetic laser", "level": 6, "power": 10},
                        {"name": "Synthetic laser", "level": 5}]:
            altered = deepcopy(changed)
            altered["skills"] = [feature]
            with self.subTest(feature=feature), self.assertRaisesRegex(ValueError, "rule source feature"):
                sf.encode_gameplay(donor(), altered, rules=[rule], tables=tables)
        for constraint in [dict(source_id=42), dict(source_rank_index=0),
                           dict(source_game="other-game"), dict(source_edition="other"),
                           dict(source_sha256="b" * 64), dict(source_rank_index=True)]:
            with self.subTest(constraint=constraint), self.assertRaisesRegex(ValueError, "rule source"):
                sf.encode_gameplay(donor(), changed, rules=[dict(rule, **constraint)], tables=tables)
        # Even table scope cannot omit its exact source-feature predicate.
        del rule["source_feature"]
        with self.assertRaisesRegex(ValueError, "rule source feature"):
            sf.map_gameplay(changed, rules=[rule], tables=tables)
        rule["source_feature"] = deepcopy(src["skills"][0])
        del rule["source_game"]
        with self.assertRaisesRegex(ValueError, "rule source context"):
            sf.map_gameplay(changed, rules=[rule], tables=tables)

    def test_default_unit_scope_requires_all_pins_and_exact_feature_predicate(self):
        src = profile()
        for kind, name in [("stats", "HP"), ("aptitudes", "HP"),
                           ("weapon_preferences", "sword"), ("skills", "Laser"),
                           ("evilities", "Aura")]:
            if kind not in ("stats", "aptitudes"):
                src[kind] = [{"name": name, "value": "S", "unit": "synthetic"}]
            rule = unit_rule(src, kind, name, relation="adapted", evidence="Synthetic predicate",
                             value=20, target_field="mastery_sword")
            del rule["scope"]
            # Absence of scope means unit-specific, not a legacy table-wide wildcard.
            sf.map_gameplay(src, policy="adapted-d5", rules=[rule])
            for key in ("source_game", "source_id", "source_rank_index", "source_feature",
                        "source_edition", "source_sha256"):
                incomplete = dict(rule)
                del incomplete[key]
                with self.subTest(kind=kind, missing=key), self.assertRaisesRegex(ValueError, "rule source"):
                    sf.map_gameplay(src, policy="adapted-d5", rules=[incomplete])
            feature = rule["source_feature"]
            changed = dict(feature, value="E") if isinstance(feature, dict) else feature + 1
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "rule source feature"):
                sf.map_gameplay(src, policy="adapted-d5", rules=[dict(rule, source_feature=changed)])
            if isinstance(feature, dict):
                for predicate in [{"name": name}, dict(feature, unit="different")]:
                    with self.subTest(predicate=predicate), self.assertRaisesRegex(ValueError, "rule source feature"):
                        sf.map_gameplay(src, policy="adapted-d5", rules=[dict(rule, source_feature=predicate)])
            else:
                with self.assertRaisesRegex(ValueError, "rule source feature"):
                    sf.map_gameplay(src, policy="adapted-d5", rules=[dict(rule, source_feature=float(feature))])
            for constraint in [dict(source_id=42.0), dict(source_rank_index=False),
                               dict(scope="generic"), dict(scope=None)]:
                with self.subTest(constraint=constraint), self.assertRaisesRegex(ValueError, "rule source"):
                    sf.map_gameplay(src, policy="adapted-d5", rules=[dict(rule, **constraint)])

    def test_static_values_encode_with_real_row_without_mutating_donor(self):
        src = profile()
        row = donor()
        original = bytes(row.raw)
        encoded, report = sf.encode_gameplay(row, src)
        self.assertEqual(encoded["base_HP"], 10)
        self.assertEqual(encoded["apt_SPD"], 100)
        self.assertEqual(bytes(row.raw), original)
        self.assertEqual(encoded["learn_count"], 0)
        self.assertEqual(encoded["evility_count"], 0)
        self.assertEqual(encoded["overload_id"], 0)
        self.assertFalse(report["native_tested"])
        self.assertIn("growth", [x["path"] for x in report["unresolved"]])
        self.assertEqual(report["donor_retained"]["mastery_sword"], 16)
        self.assertEqual(report["source"]["edition"], "synthetic-test-v1")
        self.assertEqual(report["rank_count"], 3)
        self.assertEqual(dbpatch.apply_patch(
            database.Table("char.dat", database.get_schema("char.dat")),
            {"table": "char.dat", "added": [encoded.to_dict()]}, strict=True), [])

    def test_invalid_description_rejected_before_any_encoding(self):
        from copy import deepcopy
        cases = [("source", "sha256", "bad"), ("source", "edition", ""),
                 ("source", "id", True), ("stats", "HP", -1),
                 ("stats", "HP", True), ("stats", "unknown", 1),
                 ("aptitudes", "HP", 1.5)]
        for group, key, value in cases:
            src = deepcopy(profile())
            src[group][key] = value
            with self.subTest(group=group, key=key, value=value):
                with self.assertRaises(ValueError):
                    sf.map_gameplay(src)
        for key, value in [("rank_count", 0), ("rank_count", True),
                           ("rank_index", 3), ("skills", ["Fire"]),
                           ("version", 2)]:
            src = profile()
            src[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    sf.map_gameplay(src)

    def test_missing_and_oversized_static_values_never_silently_use_donor(self):
        for group, value in [("stats", None), ("stats", 100000), ("aptitudes", 300)]:
            src = profile()
            src[group]["HP"] = value
            report = sf.map_gameplay(src)
            self.assertIn(group + ".HP", [x["path"] for x in report["unresolved"]])
            original = bytes(donor().raw)
            with self.assertRaises(ValueError):
                sf.encode_gameplay(donor(), src)
            self.assertEqual(bytes(donor().raw), original)

    def test_adapted_policy_keeps_donor_budget_explicitly_and_pins_overrides(self):
        src = profile()
        src["stats"] = {"HP": 100000}
        encoded, report = sf.encode_gameplay(donor(), src, policy="adapted-d5")
        self.assertEqual(encoded["base_HP"], 99)
        self.assertEqual(report["donor_retained"]["base_HP"], 99)
        self.assertEqual(report["policy"], "adapted-d5")
        rule = unit_rule(src, "stats", "HP", value=50,
                         relation="adapted", evidence="Synthetic deliberate D5 budget")
        encoded, report = sf.encode_gameplay(donor(), src, policy="adapted-d5", rules=[rule])
        self.assertEqual(encoded["base_HP"], 50)
        self.assertIn(rule, [x.get("rule") for x in report["mappings"]])
        with self.assertRaises(ValueError):
            sf.map_gameplay(profile(), policy="d5-tuned")
        with self.assertRaises(ValueError):
            sf.map_gameplay(src, rules=[dict(rule, source_sha256="b" * 64)])

    def test_non_equivalent_named_features_remain_explicit_backlog(self):
        src = profile()
        src["skills"] = [{"name": "Synthetic laser", "level": 5}]
        src["evilities"] = [{"name": "Synthetic aura"}]
        src["weapon_preferences"] = [{"name": "sword", "value": "S", "unit": "letter-grade"}]
        src["rank_count"] = 10
        encoded, report = sf.encode_gameplay(donor(), src)
        paths = {x["path"] for x in report["unresolved"]}
        self.assertTrue({"skills.Synthetic laser", "evilities.Synthetic aura",
                         "weapon_preferences.sword", "rank_count"} <= paths)
        self.assertEqual(encoded["learn1_skill"], 0)
        self.assertEqual(report["rank_count"], 10)

    def test_reviewed_skill_evility_and_weapon_rules_encode_real_fields(self):
        src = profile()
        src["skills"] = [{"name": "Synthetic laser", "level": 5}]
        src["evilities"] = [{"name": "Synthetic aura"}]
        src["weapon_preferences"] = [{"name": "sword", "value": "S", "unit": "letter-grade"}]
        tables = {}
        for name, sid in [("magic.dat", 9001), ("Skill.dat", 1210)]:
            tables[name] = database.Table(name, database.get_schema(name))
            tables[name].add_row(id=sid, name_EN="Synthetic target")
        def rule(kind, name, **kwargs):
            return unit_rule(src, kind, name, relation="exact",
                             evidence="Synthetic equivalence assertion ONLY", **kwargs)
        rules = [rule("skills", "Synthetic laser", target_id=9001, target_name="Synthetic target", animation_verified=True),
                 rule("evilities", "Synthetic aura", target_id=1210, target_name="Synthetic target"),
                 rule("weapon_preferences", "sword", target_field="mastery_sword", value=20)]
        encoded, report = sf.encode_gameplay(donor(), src, tables=tables, rules=rules)
        self.assertEqual(encoded["learn1_skill"], 9001)
        self.assertEqual(encoded["learn1_level"], 5)
        self.assertEqual(encoded["learn_count"], 1)
        self.assertEqual(encoded["evility1"], 1210)
        self.assertEqual(encoded["evility_count"], 1)
        self.assertEqual(encoded["mastery_sword"], 20)
        self.assertTrue(all(x["status"] == "mapped-exact-reviewed" for x in report["mappings"] if x.get("rule")))
        for altered in [dict(rules[0], target_id=9002), dict(rules[0], animation_verified=False),
                        dict(rules[0], target_name="Wrong"), dict(rules[0], relation="adapted")]:
            result = sf.map_gameplay(src, tables=tables, rules=[altered])
            self.assertEqual(result["fields"].get("learn1_skill", 0), 0)
            self.assertIn("skills.Synthetic laser", [x["path"] for x in result["unresolved"]])

    def test_plan_fields_alone_clear_donor_abilities_via_native_patch(self):
        report = sf.map_gameplay(profile())
        table = database.Table("char.dat", database.get_schema("char.dat"))
        table.rows = [donor()]
        dbpatch.apply_patch(table, {"rows": {"0": report["fields"]}}, strict=True)
        for field in ("learn1_skill", "learn1_level", "learn_count", "evility1", "evility_count", "overload_id"):
            self.assertEqual(table.rows[0][field], 0, field)

    def test_unrepresentable_rank_cannot_be_encoded(self):
        src = profile()
        src["rank_count"], src["rank_index"] = 10, 6
        with self.assertRaises(ValueError):
            sf.encode_gameplay(donor(), src)

    def test_profile_wrapper_validates_and_preserves_rpg_unknowns(self):
        src = sf.from_profile({"id": 12, "base": None, "aptitudes": None,
                               "source_base": {"hp": 217, "spd": 51},
                               "source_growth": {"hp": 43},
                               "evidence": {"sha256": "b" * 64}},
                              game="rpg", edition="synthetic-jp", rank_count=1)
        self.assertEqual(src["stats"], {})
        self.assertEqual(src["source_profile"]["source_growth"], {"hp": 43})
        with self.assertRaises(ValueError):
            sf.encode_gameplay(donor(), src)
        with self.assertRaises(ValueError):
            sf.from_profile({"id": 1}, game="synthetic", edition="", rank_count=1)

    def test_real_fixed_table_roundtrip_preserves_unmapped_bytes(self):
        import struct
        schema = database.get_schema("char.dat")
        table = database.load_table("char.dat", struct.pack("<I", 1) + bytes([0x7A]) * schema.record_size)
        row = table.rows[0]
        encoded, report = sf.encode_gameplay(row, profile())
        table.rows = [encoded]
        decoded = database.load_table("char.dat", table.to_bytes()).rows[0]
        self.assertEqual(bytes(decoded.raw), bytes(encoded.raw))
        changed_offsets = set()
        for field in report["fields"]:
            f = row.field(field)
            changed_offsets.update(range(f.offset, f.end))
        self.assertTrue(all(a == b for i, (a, b) in enumerate(zip(row.raw, decoded.raw)) if i not in changed_offsets))

    def test_ability_caps_duplicate_targets_and_missing_catalogs_are_backlog(self):
        src = profile()
        src["skills"] = [{"name": f"Synthetic skill {i}"} for i in range(18)]
        src["evilities"] = [{"name": f"Synthetic evility {i}"} for i in range(6)]
        tables, rules = {}, []
        for kind, table_name in [("skills", "magic.dat"), ("evilities", "Skill.dat")]:
            table = database.Table(table_name, database.get_schema(table_name))
            tables[table_name] = table
            for i, entry in enumerate(src[kind]):
                # Last entry intentionally targets the first existing target again.
                sid = i + 1 if i < len(src[kind]) - 1 else 1
                if i < len(src[kind]) - 1:
                    table.add_row(id=sid, name_EN=f"Synthetic target {sid}")
                rules.append(unit_rule(src, kind, entry["name"], target_id=sid,
                                  target_name=f"Synthetic target {sid}", animation_verified=True,
                                  relation="exact", evidence="Synthetic rule"))
        encoded, report = sf.encode_gameplay(donor(), src, rules=rules, tables=tables)
        self.assertEqual(encoded["learn_count"], 16)
        self.assertEqual(encoded["evility_count"], 4)
        self.assertEqual(len([x for x in report["unresolved"] if x["path"].startswith(("skills.", "evilities."))]), 4)
        without = sf.map_gameplay(src, rules=rules)
        self.assertEqual(without["fields"].get("learn_count", 0), 0)
        with self.assertRaises(ValueError):
            sf.map_gameplay(src, rules=[rules[0], rules[0]])

    def test_report_is_json_serializable_and_identifies_actual_encoded_state(self):
        import json
        src = profile()
        self.assertFalse(sf.map_gameplay(src)["encoded"])
        encoded, report = sf.encode_gameplay(donor(), src)
        self.assertTrue(report["encoded"])
        self.assertEqual(report["donor"]["id"], 970)
        self.assertEqual(len(report["donor"]["row_sha256"]), 64)
        self.assertEqual(json.loads(json.dumps(report)), report)
        self.assertIn("name_EN", report["unchanged_fields"])
        src["growth"] = float("nan")
        with self.assertRaises(ValueError):
            sf.map_gameplay(src)

    def test_schema_limits_are_not_mistaken_for_old_signed_word_policy(self):
        src = profile()
        src["stats"]["HP"] = 65535
        encoded, _ = sf.encode_gameplay(donor(), src)
        self.assertEqual(encoded["base_HP"], 65535)  # u16 in kit schema, not native acceptance
        src["stats"]["HP"] = 65536
        with self.assertRaises(ValueError):
            sf.encode_gameplay(donor(), src)

    def test_rule_schema_rejects_nonfinite_metadata_and_invalid_mastery_target(self):
        src = profile()
        src["weapon_preferences"] = [{"name": "sword", "value": "A", "unit": "letter-grade"}]
        rule = unit_rule(src, "weapon_preferences", "sword", target_field=["mastery_sword"], value=20,
                         relation="exact", evidence="Synthetic rule")
        report = sf.map_gameplay(src, rules=[rule])
        self.assertIn("weapon_preferences.sword", [x["path"] for x in report["unresolved"]])
        rule["target_field"] = "mastery_sword"
        rule["extra"] = float("nan")
        with self.assertRaises(ValueError):
            sf.map_gameplay(src, rules=[rule])


if __name__ == "__main__":
    unittest.main()
