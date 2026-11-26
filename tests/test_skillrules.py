"""Skill rules (EX-06): the skill-scope half of the evility table.

Adversarial checks first: a skill row must be a *separate namespace* keyed by the action's skill id, so
the things that can go wrong are a row that shadows an evility row of the same id, a row that lands in
the evility half of the table (where evil_find's binary search lives), a family the action context never
reaches, and a mod that puts skill rules in the evility file or the other way round.
"""
import json
import struct
import unittest
from unittest.mock import patch

from d5lib import evility as ev


class FakeMod:
    """the Mod API evility uses (load_patch / save_patch), backed by a file dict"""

    def __init__(self, files=None):
        self.files = dict(files or {})

    def load_patch(self, handler, name, default=None):
        key = f"patches/{handler}/{name}"
        return json.loads(self.files[key].decode("utf-8")) if key in self.files else default

    def save_patch(self, handler, name, obj):
        key = f"patches/{handler}/{name}"
        if obj in (None, {}, []):
            self.files.pop(key, None)
            return
        self.files[key] = json.dumps(obj, indent=1).encode("utf-8")


def rows_of(src):
    """the .long rows of the emitted table, as word lists"""
    out = []
    for line in src.splitlines():
        if line.strip().startswith(".long") and line.count(",") == 7:
            out.append([int(w) for w in line.split(None, 1)[1].split(",")])
    return out


class NamespaceTests(unittest.TestCase):
    def test_skill_rows_follow_the_evility_rows(self):
        rows, _conds, _fx = ev.table({"7000": {"family": "dealt", "effects": [{"value": 1}]}},
                                     {"392": {"family": "taken", "effects": [{"value": -30}]}})
        self.assertEqual([r[0] for r in rows], [7000, 392], "evility rows first, skill rows after")
        self.assertEqual([r[6] for r in rows], [0, ev.ROW_SKILL])

    def test_same_id_in_both_namespaces_stays_two_rows(self):
        rows, _conds, _fx = ev.table({"7000": {"family": "dealt", "effects": [{"value": 1}]}},
                                     {"7000": {"family": "dealt", "effects": [{"value": 2}]}})
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[6] for r in rows], [0, ev.ROW_SKILL])

    def test_skill_rows_are_sorted_among_themselves(self):
        rows, _conds, _fx = ev.table({}, {"900": {"family": "dealt", "effects": [{"value": 1}]},
                                          "100": {"family": "dealt", "effects": [{"value": 2}]}})
        self.assertEqual([r[0] for r in rows], [100, 900])

    def test_the_evility_count_is_what_evil_find_searches(self):
        src = ev._asm_source(*ev.table({"5": {"family": "dealt", "effects": [{"value": 1}]}},
                                       {"100": {"family": "dealt", "effects": [{"value": 2}]}}))
        at = src.splitlines().index("evil_row_count:")
        self.assertEqual(int(src.splitlines()[at + 1].split()[-1]), 2)
        at = src.splitlines().index("evil_evility_count:")
        self.assertEqual(int(src.splitlines()[at + 1].split()[-1]), 1)
        # the binary search must stop before the skill rows (they are a second, unsorted-together run)
        find = src[src.index("evil_find:"):src.index("evil_next:")]
        self.assertIn("evil_evility_count", find)
        self.assertNotIn("evil_row_count", find)

    def test_skill_index_points_at_the_skill_rows(self):
        src = ev._asm_source(*ev.table({"5": {"family": "dealt", "effects": [{"value": 1}]},
                                        "6": {"family": "dealt", "effects": [{"value": 1}]}},
                                       {"100": {"family": "dealt", "effects": [{"value": 2}]},
                                        "900": {"family": "dealt", "effects": [{"value": 2}]}}))
        lines = src.splitlines()
        at = lines.index("evil_skill_count:")
        self.assertEqual(int(lines[at + 1].split()[-1]), 2)
        at = lines.index("evil_skill_index:")
        self.assertEqual([int(lines[at + 1 + i].split()[-1]) for i in range(2)], [64, 96])
        words = rows_of(src)
        for off in (64, 96):
            self.assertEqual(words[off // 32][6] & ev.ROW_SKILL, ev.ROW_SKILL)

    def test_no_skill_rows_still_emits_the_index(self):
        src = ev._asm_source(*ev.table({"7000": {"family": "dealt", "effects": [{"value": 1}]}}))
        self.assertIn("evil_skill_count:\n    .long 0", src)
        self.assertIn("evil_skill_index:\n    .long 0", src)


class ValidationTests(unittest.TestCase):
    def test_only_the_families_that_get_the_action_context(self):
        # EX-06b: the ailment pass now gets the action context through wrap_achance/evil_ctx, so
        # status_chance is a skill family too; potency/stats/growth/conversion/flight/aura are not
        # damage-time at all and stay evility-only.
        for family in ("potency", "stats", "growth", "conversion", "flight"):
            with self.assertRaises(ValueError, msg=family) as ctx:
                ev.table({}, {"100": {"family": family,
                                      "effects": [] if family == "flight" else [{"value": 1,
                                                                                "stat": "atk"}]}})
            self.assertIn("damage-time", str(ctx.exception))
        for family in ("dealt", "taken", "hit", "status_chance"):
            rows, _c, _f = ev.table({}, {"100": {"family": family, "effects": [{"value": 1}]}})
            self.assertEqual(rows[0][1], ev.FAMILIES[family])

    def test_a_status_chance_skill_row_is_a_percentage_row(self):
        rows, conds, fx = ev.table({}, {"392": {"family": "status_chance",
                                                "effects": [{"value": -15}],
                                                "conditions": [{"kind": "status_class", "id": 2}]}})
        self.assertEqual(rows[0][1], ev.F_STATUS)
        self.assertEqual(fx, [(0, -15)])
        self.assertEqual(conds, [(ev.COND_KINDS["status_class"], 2, 0, 0)])

    def test_other_slot_is_a_condition_kind(self):
        # EX-06b split the old target_class behaviour (battle record +0x2F4, the unit's slot) out of
        # target_class, which now reads the other unit's class id.  EX-05e already holds 44 (near_char) and
        # 45 (other_adj) on the branch this was ported onto, so other_slot is 46 here.
        self.assertEqual(ev.COND_KINDS["other_slot"], 46)
        self.assertIn("other_slot", ev.COND_ZERO_OK)
        rows, conds, _fx = ev.table({}, {"392": {"family": "dealt", "effects": [{"value": 1}],
                                                "conditions": [{"kind": "other_slot", "id": 0}]}})
        self.assertEqual(conds, [(46, 0, 0, 0)])

    def test_the_predicate_families_take_no_effects(self):
        # EX-06b: nullify / counter are predicates -- the row's presence with its conditions is the
        # whole effect, like flight.  A counter row can never be a skill row (the function is given no
        # action context); a nullify row can (it is handed the context at the sites we redirect).
        for family in ("nullify", "counter"):
            rows, _c, fx = ev.table({"7001": {"family": family}}, {})
            self.assertEqual(rows[0][1], ev.FAMILIES[family])
            self.assertEqual(fx, [])
        self.assertIn(ev.F_NULLIFY, ev.SKILL_FAMILIES)
        self.assertNotIn(ev.F_COUNTER, ev.SKILL_FAMILIES)
        with self.assertRaises(ValueError) as ctx:
            ev.table({}, {"7001": {"family": "counter"}})
        self.assertIn("damage-time", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            ev.table({"100": {"family": "nullify", "effects": [{"value": 5}]}}, {})
        self.assertIn("no effects", str(ctx.exception))

    def test_mixed_families_are_refused_when_one_is_not_damage_time(self):
        with self.assertRaises(ValueError):
            ev.table({}, {"100": {"family": ["dealt", "potency"],
                                  "effects": [{"value": 1}]}})
        rows, _c, _f = ev.table({}, {"100": {"family": ["dealt", "taken", "hit"],
                                            "effects": [{"value": 1}]}})
        self.assertEqual(rows[0][1], ev.F_DEALT | ev.F_TAKEN | ev.F_HIT)

    def test_the_condition_vocabulary_is_the_evility_one(self):
        rows, conds, _fx = ev.table({}, {"392": {
            "family": "taken", "effects": [{"value": -30}],
            "conditions": [{"kind": "attack_dir", "id": 0}, {"kind": "element", "id": 1},
                           {"kind": "near_has", "of": 1, "radius": 1, "id": 7000}]}})
        self.assertEqual(conds, [(ev.COND_KINDS["attack_dir"], 0, 0, 0),
                                 (ev.COND_KINDS["element"], 1, 0, 0),
                                 (ev.COND_KINDS["near_has"], 1, 1, 7000)])
        self.assertEqual(rows[0][3], 3)

    def test_counted_magnitudes_work_on_a_skill_row(self):
        _rows, _conds, fx = ev.table({}, {"100": {"family": "dealt",
                                                 "effects": [{"value": -10,
                                                              "per": "adjacent_ally"}]}})
        self.assertEqual(fx[0][0] >> 16, ev.SCALES["adjacent_ally"])

    def test_an_unknown_condition_still_fails(self):
        with self.assertRaises(ValueError):
            ev.table({}, {"100": {"family": "dealt", "effects": [{"value": 1}],
                                  "condition": {"kind": "not_a_condition", "id": 1}}})

    def test_a_skill_row_needs_effects(self):
        with self.assertRaises(ValueError):
            ev.table({}, {"100": {"family": "dealt"}})

    def test_the_scope_key_cannot_cross_the_files(self):
        with self.assertRaises(ValueError) as ctx:
            ev.table({"7000": {"family": "dealt", "effects": [{"value": 1}], "scope": "skill"}})
        self.assertIn("skillrules.json", str(ctx.exception))
        with self.assertRaises(ValueError):
            ev.table({}, {"100": {"family": "dealt", "effects": [{"value": 1}], "scope": "evility"}})
        # spelling the folder's own scope is allowed
        rows, _c, _f = ev.table({}, {"100": {"family": "dealt", "effects": [{"value": 1}],
                                            "scope": "skill"}})
        self.assertEqual(rows[0][6], ev.ROW_SKILL)

    def test_skill_ids_are_range_checked(self):
        for bad in (0, -1, 0x80000000):
            with self.assertRaises(ValueError):
                ev.table({}, {str(bad): {"family": "dealt", "effects": [{"value": 1}]}})

    def test_the_row_budget_is_shared(self):
        with patch.object(ev, "MAX_ROWS", 2):
            with self.assertRaises(ValueError):
                ev.table({"1": {"family": "dealt", "effects": [{"value": 1}]}},
                         {"2": {"family": "dealt", "effects": [{"value": 1}]},
                          "3": {"family": "dealt", "effects": [{"value": 1}]}})


class DataFileTests(unittest.TestCase):
    def test_roundtrip(self):
        mod = FakeMod()
        data = {"rules": {"392": {"family": "taken", "effects": [{"value": -30}],
                                  "conditions": [{"kind": "attack_dir", "id": 0}]}}}
        ev.save_skills(mod, data)
        self.assertEqual(ev.load_skills(mod), data)
        self.assertIn("patches/skillrules/skillrules.json", mod.files)
        self.assertEqual(ev.load_skills(FakeMod()), {"rules": {}})

    def test_the_two_files_do_not_collide(self):
        mod = FakeMod()
        ev.save(mod, {"evilities": {"7000": {"family": "dealt", "effects": [{"value": 1}]}}})
        ev.save_skills(mod, {"rules": {"392": {"family": "taken", "effects": [{"value": -1}]}}})
        self.assertEqual(sorted(mod.files), ["patches/evilities/evilities.json",
                                             "patches/skillrules/skillrules.json"])


class FinalizerTests(unittest.TestCase):
    """the handlers collect into one table; a mod with only skill rules must still build the section"""

    class Ctx:
        def __init__(self):
            self.out = {}

        def get(self, name):
            return b"original exe"

        def put(self, name, data):
            self.out[name] = data

        def log(self, *_a):
            pass

    def _run(self, ev_files, skill_files):
        ctx = self.Ctx()
        mod = FakeMod()
        if ev_files:
            ev.save(mod, ev_files)
        if skill_files:
            ev.save_skills(mod, skill_files)
        with patch.object(ev, "EXE_FILE", "GAME/disgaea5.exe"), \
             patch.object(ev, "build_patch", return_value=b"patched") as build:
            if ev_files:
                ev._handler(ctx, mod, "patches/evilities")
            if skill_files:
                ev._skill_handler(ctx, mod, "patches/skillrules")
            ev._finalize(ctx)
        return ctx, build

    def test_skill_rules_alone_build_the_section(self):
        ctx, build = self._run(None, {"rules": {"392": {"family": "taken",
                                                        "effects": [{"value": -30}]}}})
        self.assertEqual(ctx.out["GAME/disgaea5.exe"], b"patched")
        self.assertEqual(build.call_args.args[1], {})
        self.assertEqual(sorted(build.call_args.args[2]), [392])

    def test_both_files_reach_one_table(self):
        _ctx, build = self._run({"evilities": {"7000": {"family": "dealt",
                                                        "effects": [{"value": 1}]}}},
                                {"rules": {"392": {"family": "taken",
                                                   "effects": [{"value": -1}]}}})
        self.assertEqual(sorted(build.call_args.args[1]), [7000])
        self.assertEqual(sorted(build.call_args.args[2]), [392])

    def test_nothing_configured_touches_nothing(self):
        ctx, build = self._run(None, None)
        self.assertEqual(ctx.out, {})
        build.assert_not_called()

    def test_a_skill_rule_with_the_evility_scope_is_refused(self):
        ctx = self.Ctx()
        mod = FakeMod()
        ev.save_skills(mod, {"rules": {"392": {"family": "taken", "effects": [{"value": -1}],
                                              "scope": "evility"}}})
        with self.assertRaises(ValueError) as e:
            ev._skill_handler(ctx, mod, "patches/skillrules")
        self.assertIn("scope", str(e.exception))


class AsmTests(unittest.TestCase):
    def test_the_skill_match_reads_the_action_context(self):
        src = ev._asm_source(*ev.table({}, {"392": {"family": "taken",
                                                   "effects": [{"value": -30}]}}))
        self.assertIn("test dword ptr [r12 + 24], 1", src)
        self.assertIn("mov eax, dword ptr [rbp + 0x27670]", src)

    def test_the_skill_pass_is_after_the_ordinary_rows(self):
        src = ev._asm_source(*ev.table({}, {"392": {"family": "taken",
                                                   "effects": [{"value": -30}]}}))
        self.assertIn("jz .d_skill", src)
        self.assertIn("cmp ecx, dword ptr [rip + evil_skill_count]", src)
        self.assertLess(src.index(".d_loop:"), src.index(".d_skill:"))

    def test_the_section_still_assembles_with_skill_rows(self):
        base = 0x148000000
        rows, conds, fx = ev.table({"7000": {"family": "dealt", "effects": [{"value": 1}]}},
                                   {"392": {"family": "taken", "effects": [{"value": -30}]}})
        code, labels = ev._assemble(ev._asm_source(rows, conds, fx), base)
        self.assertEqual(sorted(labels), sorted(ev.TAGS))
        self.assertGreater(len(code), 1000)

    def test_the_action_context_slot_is_in_the_data_area(self):
        # wrap_achance stores into evil_ctx and the proofs locate it by its magic word
        base = 0x148000000
        rows, conds, fx = ev.table({}, {"392": {"family": "status_chance", "effects": [{"value": 5}]}})
        src = ev._asm_source(rows, conds, fx)
        self.assertIn("evil_ctx:", src)
        code, labels = ev._assemble(src, base)
        slot = ev.SECTION_SYMBOLS["evil_ctx"]
        self.assertEqual(code[slot - base - 8:slot - base],
                         struct.pack("<Q", ev.EVIL_CTX_MAGIC))
        self.assertEqual(code[slot - base:slot - base + 8], bytes(8))
        self.assertIn("mov r8, qword ptr [rip + evil_ctx]", src)
        self.assertIn("mov qword ptr [rip + evil_ctx], rax", src)

    def test_build_patch_passes_the_skill_rows_through(self):
        labels = {tag: 0x148000100 + tag * 0x10 for tag, _, _ in ev.WRAPPERS}
        with patch.object(ev, "code_base", return_value=0x148000000), \
             patch.object(ev, "_assemble", return_value=(b"code", labels)), \
             patch.object(ev, "_offset", return_value=0), \
             patch.object(ev, "_check_site"), \
             patch.object(ev, "add_code_section", return_value=b"patched"):
            self.assertEqual(ev.build_patch(b"original", {"7000": {"family": "dealt",
                                                                   "effects": [{"value": 1}]}},
                                            {"392": {"family": "taken",
                                                     "effects": [{"value": -30}]}}), b"patched")
        with self.assertRaises(ValueError):
            ev.build_patch(b"original", {}, {"392": {"family": "potency",
                                                     "effects": [{"value": 1}]}})


if __name__ == "__main__":
    unittest.main()
