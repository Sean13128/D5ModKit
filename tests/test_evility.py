"""Evility extension: mod data validation, the table layout and the assembled code (no game files)."""
import json
import struct
import unittest
from unittest.mock import patch

from d5lib import evility as ev


class FakeMod:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def read(self, name):
        if name not in self.files:
            raise FileNotFoundError(name)
        return self.files[name]

    def write(self, name, data):
        self.files[name] = bytes(data)

    # the Mod API evility uses (modsys.Mod.load_patch / save_patch), backed by the same file dict
    def load_patch(self, handler, name, default=None):
        import json
        key = f"patches/{handler}/{name}"
        return json.loads(self.files[key].decode("utf-8")) if key in self.files else default

    def save_patch(self, handler, name, obj):
        import json
        key = f"patches/{handler}/{name}"
        if obj in (None, {}, []):
            self.files.pop(key, None)
            return
        self.files[key] = (json.dumps(obj, indent=1, ensure_ascii=False)).encode("utf-8")


class TableTests(unittest.TestCase):
    def test_power_aura_with_bounded_defeat_scale(self):
        row = {"family": ["power", "aura"],
               "effects": [{"value": 10, "per": "defeated_any", "max": 200}],
               "condition": {"kind": "near_has", "of": 1, "radius": 65535, "id": 26304}}
        rows, conds, fx = ev.table({26304: row})
        self.assertEqual(rows[0][1], ev.F_POWER | ev.F_AURA)
        self.assertEqual(conds, [(ev.COND_KINDS["near_has"], 1, 65535, 26304)])
        self.assertEqual(fx, [(0x1000000 | ev.SCALES["defeated_any"] << 16, 200 << 16 | 10)])
        # The original family exclusivity still holds for other additive combinations.
        for fams in (["power", "stats"], ["defense_power", "aura"], ["power", "move", "aura"]):
            with self.subTest(families=fams), self.assertRaises(ValueError):
                ev.table({26304: dict(row, family=fams)})
        with self.assertRaisesRegex(ValueError, "provider"):
            ev.table({26304: {"family": ["power", "aura"], "effects": [{"value": 10}]}})

    def test_effect_max_encoding_and_validation(self):
        for base in (-32768, -10, 0, 10, 32767):
            for cap in (0, 200, 32767):
                for family in ("power", "dealt", "hit", "steal_on_kill_percent"):
                    with self.subTest(base=base, cap=cap, family=family):
                        _, _, fx = ev.table({26304: {"family": family,
                                                   "effects": [{"value": base, "max": cap}]}})
                        self.assertEqual(fx, [(0x1000000, (cap << 16) | (base & 0xFFFF))])
        for cap in (-1, 32768, True, False, None, "200", 200.0):
            with self.subTest(cap=cap), self.assertRaisesRegex(ValueError, "max"):
                ev.table({26304: {"family": "power", "effects": [{"value": 10, "max": cap}]}})
        for family in ("stats", "potency", "growth", "regen", "conversion", "absorb"):
            with self.subTest(family=family), self.assertRaisesRegex(ValueError, "max"):
                ev.table({26304: {"family": family, "effects": [{"value": 10, "max": 200}]}})
        with self.assertRaises(ValueError):
            ev.table({26304: {"family": "dealt", "effects": [{"stat": "atk", "value": 10, "max": 200}]}})
        # Uncapped encoding is unchanged, including signed negative values and scale byte.
        for value in (-32768, -10, 0, 10, 32767):
            _, _, fx = ev.table({26304: {"family": "power", "effects": [{"value": value}]}})
            self.assertEqual(struct.pack("<Ii", *fx[0]), struct.pack("<Ii", 0, value))
        _, _, fx = ev.table({26304: {"family": "power",
                                   "effects": [{"value": 10, "per": "defeated_any"}]}})
        self.assertEqual(fx, [(ev.SCALES["defeated_any"] << 16, 10)])

    def test_row_layout_and_effect_offsets(self):
        rows, conds, fx = ev.table({
            7002: {"family": "potency", "effects": [{"stat": "atk", "value": 30}]},
            7001: {"family": "growth", "effects": [{"stat": 5, "value": 7}, {"stat": 0, "value": -1}]},
        })
        self.assertEqual([r[0] for r in rows], [7001, 7002], "rows are sorted by id")
        self.assertEqual(rows[0][1], ev.F_GROWTH)
        self.assertEqual(rows[1][1], ev.F_POTENCY)
        self.assertEqual(rows[0][4], 0, "the first row's effects start at 0")
        self.assertEqual(rows[1][4], 16, "the second row's effects follow the first two")
        self.assertEqual(rows[1][5], 1)
        self.assertEqual(conds, [])
        self.assertEqual(fx, [(5, 7), (0, -1), (2, 30)])

    def test_stat_names_and_all(self):
        _rows, _conds, fx = ev.table({7100: {"family": "potency", "effects": [{"stat": "all", "value": 3}]}})
        self.assertEqual([s for s, _ in fx], [0, 1, 2, 3, 4, 5, 6, 7])
        _rows, _conds, fx = ev.table({7101: {"family": "potency", "effects": [{"stat": "spd", "value": 3}]}})
        self.assertEqual(fx, [(7, 3)])

    def test_several_families_multiply_the_effect(self):
        _rows, _conds, fx = ev.table({7102: {"family": ["potency", "growth"],
                                            "effects": [{"stat": 4, "value": 9}]}})
        self.assertEqual(fx, [(4, 9), (4, 9)], "one effect per family, so both passes see it")

    def test_condition_defaults_and_kinds(self):
        rows, conds, _fx = ev.table({7103: {"family": "stats", "effects": [{"stat": 2, "value": 1}]}})
        self.assertEqual(rows[0][2:4], (0, 0), "no condition")
        self.assertEqual(conds, [])
        for kind, arg in (("has", 121), ("char", 10), ("count", 3), ("ally_adj", 1),
                          ("enemy_adj", 2), ("turn_min", 3), ("weapon", 2), ("element", 1)):
            rows, conds, _fx = ev.table({7104: {"family": "stats", "effects": [{"stat": 2, "value": 1}],
                                                "condition": {"kind": kind, "id": arg}}})
            self.assertEqual(rows[0][3], 1, "one condition")
            self.assertEqual(conds, [(ev.COND_KINDS[kind], arg, 0, 0)])

    def test_conditions_are_a_list_and_all_must_hold(self):
        rows, conds, _fx = ev.table({7105: {
            "family": "dealt", "effects": [{"value": 10}],
            "conditions": [{"kind": "attack_skill"}, {"kind": "element", "id": 1},
                           {"kind": "near_has", "of": 1, "radius": 1, "id": 7000}]}})
        self.assertEqual(rows[0][2], 0, "the condition block starts at 0")
        self.assertEqual(rows[0][3], 3)
        self.assertEqual(conds, [(ev.COND_KINDS["attack_skill"], 0, 0, 0),
                                 (ev.COND_KINDS["element"], 1, 0, 0),
                                 (ev.COND_KINDS["near_has"], 1, 1, 7000)])

    def test_aura_rows_need_a_provider_condition(self):
        # an aura acts on the recipient, so it must name the provider and cannot carry a family it
        # has no pass for
        with self.assertRaises(ValueError):
            ev.table({7106: {"family": ["potency", "aura"], "effects": [{"stat": 2, "value": 5}]}})
        with self.assertRaises(ValueError):
            # EVILFX2: regen may be an aura now; flight still has no recipient pass
            ev.table({7106: {"family": ["flight", "aura"],
                             "condition": {"kind": "near_has", "of": 1, "radius": 1, "id": 7000}}})
        # EX-05e: the damage-time passes are handed the recipient too, so they can carry an aura
        rows, conds, fx = ev.table({7106: {"family": ["taken", "aura"], "effects": [{"value": -50}],
                                           "condition": {"kind": "near_has", "of": 1, "radius": 1,
                                                         "id": 7106}}})
        self.assertEqual(rows[0][1], ev.F_TAKEN | ev.F_AURA)
        self.assertEqual(fx, [(0, -50)])
        _rows, conds, fx = ev.table({7106: {
            "family": ["potency", "aura"], "effects": [{"stat": "atk", "value": 20}],
            "condition": {"kind": "near_has", "of": 1, "radius": 1, "id": 7000}}})
        self.assertEqual(fx, [(2, 20)])
        self.assertEqual(conds, [(ev.COND_KINDS["near_has"], 1, 1, 7000)])

    def test_damage_families_take_one_percentage(self):
        rows, _conds, fx = ev.table({7105: {"family": "dealt", "effects": [{"value": 30}, {"value": -10}]},
                                     7106: {"family": "taken", "effects": [{"value": 50}]}})
        self.assertEqual(rows[0][1], ev.F_DEALT)
        self.assertEqual(rows[1][1], ev.F_TAKEN)
        self.assertEqual(fx, [(0, 30), (0, -10), (0, 50)],
                         "one effect per percentage, never one per stat")
        # a stat is meaningless for a damage row and is refused instead of silently ignored
        with self.assertRaises(ValueError):
            ev.table({7107: {"family": "dealt", "effects": [{"stat": "atk", "value": 10}]}})
        # a row can mix a damage family with a stat family; the stat family keeps its stat effect
        _rows, _conds, fx = ev.table({7108: {"family": ["dealt", "potency"],
                                     "effects": [{"value": 10}, {"stat": 2, "value": 5}]}})
        self.assertEqual(fx, [(0, 10), (2, 5)], "the damage percentage is not multiplied by eight")

    def test_extended_conditions(self):
        for kind, arg in (("hp_below", 50), ("hp_above", 50), ("level", 200), ("target_class", 5),
                          ("target_status", 5), ("self_status", 5), ("status_class", 3),
                          ("attack_dir", 2), ("rng", 30)):
            rows, conds, _fx = ev.table({7109: {"family": "dealt", "effects": [{"value": 1}],
                                                "condition": {"kind": kind, "id": arg}}})
            self.assertEqual(rows[0][3], 1)
            self.assertEqual(conds[0][:2], (ev.COND_KINDS[kind], arg))
        # target_class 0 is a legitimate class kind, and so are attack_dir 0 (front) and element 0 (none)
        for kind in ("target_class", "attack_dir", "element"):
            rows, conds, _fx = ev.table({7110: {"family": "dealt", "effects": [{"value": 1}],
                                                "condition": {"kind": kind, "id": 0}}})
            self.assertEqual(conds[0][1], 0)
        with self.assertRaises(ValueError):
            ev.table({7111: {"family": "dealt", "effects": [{"value": 1}],
                             "condition": {"kind": "hp_below", "id": 0}}})

    def test_chance_families_take_one_percentage_and_carry_no_stat(self):
        rows, _conds, fx = ev.table({7112: {"family": "hit", "effects": [{"value": 15}]},
                                     7113: {"family": "status_chance", "effects": [{"value": 10}]}})
        self.assertEqual([r[1] for r in rows], [ev.F_HIT, ev.F_STATUS])
        self.assertEqual(fx, [(0, 15), (0, 10)])

    def test_additive_families_take_one_number_and_carry_no_stat(self):
        """P3: power / defense_power / move / range add to a number the enclosing game function returns."""
        rows, _conds, fx = ev.table({
            7300: {"family": "power", "effects": [{"value": 30}]},
            7301: {"family": "defense_power", "effects": [{"value": 20}]},
            7302: {"family": "move", "effects": [{"value": 1}]},
            7303: {"family": "range", "effects": [{"value": 2}]}})
        self.assertEqual([r[1] for r in rows], [ev.F_POWER, ev.F_DPOWER, ev.F_MOVE, ev.F_RANGE])
        self.assertEqual(fx, [(0, 30), (0, 20), (0, 1), (0, 2)])
        self.assertEqual(sum(ev.ADD_FAMILIES), ev.F_POWER | ev.F_DPOWER | ev.F_MOVE | ev.F_RANGE | ev.F_WEAPON)

    def test_additive_families_reject_what_they_cannot_mean(self):
        bad = [
            # a stat means nothing to a pass that returns one number
            {"family": "power", "effects": [{"stat": "atk", "value": 10}]},
            {"family": "range", "effects": [{"stat": "all", "value": 10}]},
            # two additive passes in one row would be applied by neither wrapper
            {"family": ["power", "defense_power"], "effects": [{"value": 10}]},
            # an additive row is not a damage-time pass, so it cannot be an aura or a skill rule
            {"family": ["move", "aura"], "effects": [{"value": 1}]},
            {"family": "power", "effects": [{"value": 10}], "condition": {"kind": "attack_dir", "id": 2},
             "scope": "skill"},
            # and it still needs an effect
            {"family": "move"},
        ]
        for row in bad:
            with self.assertRaises(ValueError):
                ev.table({7300: row})
        # `per` is allowed: the additive value can scale with a runtime count
        _rows, _conds, fx = ev.table({7304: {"family": "power",
                                             "effects": [{"value": 3, "per": "adjacent_ally"}]}})
        self.assertEqual(fx, [(1 << 16, 3)])

    def test_additive_family_tags_and_sites_are_wired(self):
        for name, family in (("power", ev.F_POWER), ("defense_power", ev.F_DPOWER),
                             ("move", ev.F_MOVE), ("range", ev.F_RANGE)):
            tag, target, sites = ev.wrapper(name)
            self.assertTrue(tag and target and sites)
            self.assertEqual(ev.WRAPPER_NAMES[tag], name)
            self.assertTrue(family & (1 << 31) == 0, "the mask word stays a positive u32")

    def test_oleffects_predicates_are_presence_only(self):
        """OLEFFECTS: permanent_revenge and block_overload are predicates -- presence plus conditions."""
        rows, conds, fx = ev.table({
            7660: {"family": "permanent_revenge"},
            7661: {"family": "block_overload", "condition": {"kind": "level", "id": 100}}})
        self.assertEqual([r[1] for r in rows], [ev.F_REVENGE, ev.F_OVERLOAD])
        self.assertEqual(fx, [], "a predicate row carries no numbers")
        self.assertEqual(conds, [(ev.COND_KINDS["level"], 100, 0, 0)])
        for row in ({"family": "permanent_revenge", "effects": [{"value": 1}]},
                    {"family": "block_overload", "effects": [{"value": 1}]},
                    {"family": ["permanent_revenge", "dealt"], "effects": [{"value": 1}]}):
            with self.assertRaises(ValueError):
                ev.table({7662: row})

    def test_evilfx1_rearm_first_damage_is_a_lone_predicate(self):
        """EVILFX1: rearm_first_damage (bit 1<<26) is presence plus conditions and combines with nothing."""
        self.assertEqual(ev.F_REARM, 1 << 26)
        self.assertEqual(ev.FAMILIES["rearm_first_damage"], ev.F_REARM)
        rows, _conds, fx = ev.table({8667: {"family": "rearm_first_damage"}})
        self.assertEqual([r[1] for r in rows], [ev.F_REARM])
        self.assertEqual(fx, [])
        for row in ({"family": "rearm_first_damage", "effects": [{"value": 1}]},
                    {"family": ["rearm_first_damage", "permanent_revenge"]}):
            with self.assertRaises(ValueError):
                ev.table({8667: row})

    def test_oleffects_stack_families_take_one_number(self):
        """OLEFFECTS: steal_on_kill_percent and sp_drain_per_turn add one number to the game's own value."""
        rows, _conds, fx = ev.table({
            7670: {"family": "steal_on_kill_percent", "effects": [{"value": 30}]},
            7671: {"family": "sp_drain_per_turn", "effects": [{"value": -5}]}})
        self.assertEqual([r[1] for r in rows], [ev.F_STEAL, ev.F_SPDRAIN])
        self.assertEqual(fx, [(0, 30), (0, -5)])
        self.assertEqual(ev.STACK_FAMILIES, (ev.F_STEAL, ev.F_SPDRAIN, ev.F_SPDMG, ev.F_SUPPORT, ev.F_EVASION))   # EVILCAP1, D4SIG3, D4SIG5 appended
        # `per` is allowed, exactly like the additive passes
        _rows, _conds, fx = ev.table({7672: {"family": "sp_drain_per_turn",
                                            "effects": [{"value": 2, "per": "squad"}]}})
        self.assertEqual(fx, [(ev.SCALES["squad"] << 16, 2)])
        for row in ({"family": "steal_on_kill_percent", "effects": [{"stat": "atk", "value": 10}]},
                    {"family": ["steal_on_kill_percent", "sp_drain_per_turn"],
                     "effects": [{"value": 10}]},
                    {"family": ["steal_on_kill_percent", "dealt"], "effects": [{"value": 10}]},
                    {"family": "steal_on_kill_percent"}):
            with self.assertRaises(ValueError):
                ev.table({7673: row})

    def test_oleffects_names_and_sites_are_wired(self):
        """OLEFFECTS: Overlord's own effect names map to the four wrappers, at the sites this build has."""
        for name, family in (("permanent_revenge", ev.F_REVENGE), ("block_overload", ev.F_OVERLOAD),
                             ("steal_on_kill_percent", ev.F_STEAL),
                             ("sp_drain_per_turn", ev.F_SPDRAIN)):
            self.assertEqual(ev.FAMILIES[name], family)
            self.assertEqual(ev.FAMILY_NAME[family], name)
            self.assertTrue(family & (1 << 31) == 0, "the mask word stays a positive u32")
        for wrapper_name, family, site_count in (("revenge", ev.F_REVENGE, 1),
                                                 ("overload", ev.F_OVERLOAD, 11),
                                                 ("steal", ev.F_STEAL, 1),
                                                 ("sp_drain", ev.F_SPDRAIN, 1)):
            tag, target, sites = ev.wrapper(wrapper_name)
            self.assertEqual(ev.WRAPPER_NAMES[tag], wrapper_name)
            self.assertEqual(len(sites), site_count)
            self.assertEqual(len(set(sites)), site_count)
        self.assertEqual(ev.wrapper("revenge")[1], ev.END_ROUND)
        self.assertEqual(ev.wrapper("overload")[1], ev.OVERLOAD)
        self.assertEqual(ev.wrapper("steal")[1], ev.STEAL_ELIG)
        self.assertEqual(ev.wrapper("sp_drain")[1], ev.SP_REGEN)
        # the four masks continue where the D4REV2 absorb bit stopped, and never collide with it
        self.assertEqual(ev.F_REVENGE, 1 << 21)
        self.assertEqual(ev.F_OVERLOAD, 1 << 22)
        self.assertEqual(ev.F_STEAL, 1 << 23)
        self.assertEqual(ev.F_SPDRAIN, 1 << 24)

    def test_squad_scale_rides_the_stats_family(self):
        """stat_per_squad_unit is not a family: it is stats with per=squad, counted by evil_scale kind 9."""
        rows, _conds, fx = ev.table({7680: {"family": "stats",
                                           "effects": [{"stat": "all", "value": 2, "per": "squad"}]}})
        self.assertEqual([r[1] for r in rows], [ev.F_STATS])
        self.assertEqual(fx, [(n | (9 << 16), 2) for n in range(8)])

    def test_every_wrapper_has_a_site_and_a_tag(self):
        self.assertEqual(len(ev.TAGS), len(ev.WRAPPERS))
        self.assertEqual(len(set(ev.TAGS)), len(ev.TAGS), "build tags are unique")
        covered = set()
        for tag, target, sites in ev.WRAPPERS:
            self.assertTrue(sites, f"wrapper {tag:#x} has no call site")
            self.assertGreater(target, 0)
            for va in sites:
                self.assertGreater(va, 0)
        # the predicate families need no effect list; the others do
        for name, family in ev.FAMILIES.items():
            if family in ev.PREDICATE_FAMILIES:
                ev.table({7100: {"family": name}})
            else:
                with self.assertRaises(ValueError):
                    ev.table({7100: {"family": name}})

    def test_rejects_bad_rows(self):
        bad = [
            {7100: {"family": "potency"}},                                        # no effects
            {7100: {"family": "magic", "effects": [{"stat": 1, "value": 1}]}},    # unknown family
            {7100: {"family": "potency", "effects": [{"stat": 1, "value": 40000}]}},   # value out of range
            {7100: {"family": "potency", "effects": [{"stat": 9, "value": 1}]}},  # stat out of range
            {7100: {"family": "potency", "effects": [{"stat": "luck", "value": 1}]}},
            {7100: {"family": "potency", "effects": [{"stat": 1, "value": 1}],
                    "condition": {"kind": "whenever", "id": 1}}},
            {7100: {"family": "potency", "effects": [{"stat": 1, "value": 1}],
                    "condition": {"kind": "has"}}},                               # condition without id
            {0: {"family": "potency", "effects": [{"stat": 1, "value": 1}]}},     # id 0 terminates the table
        ]
        for d in bad:
            with self.assertRaises(ValueError):
                ev.table(d)

    def test_capacity(self):
        many = {7000 + i: {"family": "potency", "effects": [{"stat": 1, "value": i + 1}]}
                for i in range(ev.MAX_ROWS + 1)}
        with self.assertRaises(ValueError):
            ev.table(many)
        ok = {7000 + i: {"family": "potency", "effects": [{"stat": 1, "value": 1}]} for i in range(ev.MAX_ROWS)}
        self.assertEqual(len(ev.table(ok)[0]), ev.MAX_ROWS)

    def test_conversion_packs_base_source_without_changing_format(self):
        rows, _conditions, effects = ev.table({7200: {
            "family": "conversion", "effects": [{"stat": "hit", "from": "spd", "value": 30}]}})
        self.assertEqual(rows[0][1], ev.F_CONVERSION)
        self.assertEqual(effects, [(6 | (7 << 8), 30)])
        self.assertEqual(ev.HEADER, b"D5EV\x02")
        for row in (
                {"family": "conversion", "effects": [{"stat": "atk", "value": 1}]},
                {"family": "conversion", "effects": [{"from": "atk", "value": 1}]},
                {"family": "conversion", "effects": [{"stat": "all", "from": "atk", "value": 1}]},
                {"family": "conversion", "effects": [{"stat": "atk", "from": 9, "value": 1}]},
                {"family": "conversion", "effects": [{"stat": "atk", "from": "spd", "value": 1,
                                                      "per": "map_ally"}]},
                {"family": ["conversion", "stats"], "effects": [{"stat": "atk", "from": "spd", "value": 1}]},
                {"family": "stats", "effects": [{"stat": "atk", "from": "spd", "value": 1}]}):
            with self.assertRaises(ValueError):
                ev.table({7200: row})

    def test_runtime_magnitudes_pack_a_scale_byte(self):
        # EX-05d: `per` selects a count in byte 2 of the effect's stat word; a fixed effect stays 0
        _rows, _conds, fx = ev.table({7500: {
            "family": "stats", "effects": [{"stat": "atk", "value": 20, "per": "adjacent_ally"},
                                            {"stat": "def", "value": 5}]}})
        self.assertEqual(fx, [(2 | (ev.SCALES["adjacent_ally"] << 16), 20), (3, 5)])
        self.assertEqual(ev.SCALES["adjacent_ally"], 1, "kind 1 is what evil_scale_tbl expects")
        self.assertEqual(sorted(ev.SCALES), ["adjacent_ally", "adjacent_any", "adjacent_enemy", "defeated_any", "defeated_enemy", "geo_colours", "holder_kills", "hp_lost_pct", "hp_pct", "idle_turns", "map_ally", "map_any", "map_class", "map_class_ally", "map_class_enemy", "map_enemy", "map_has", "map_human", "map_monster", "map_squad", "movement_cost", "party_capped", "party_female", "party_human", "party_male", "party_monster", "party_weapon", "squad"])
        # EVILFX1: the squad-mates-on-the-map count is kind 15, after CARRIERS2's four
        self.assertEqual(ev.SCALES["map_squad"], 15)
        _rows, _conds, fx = ev.table({8840: {
            "family": "stats", "effects": [{"stat": "atk", "value": 5, "per": "map_squad"}]}})
        self.assertEqual(fx, [(2 | (15 << 16), 5)])
        with self.assertRaises(ValueError):    # map_squad reads no filter argument
            ev.table({8840: {"family": "stats", "filter": 3,
                             "effects": [{"stat": "atk", "value": 5, "per": "map_squad"}]}})
        # CARRIERS2: the four filtered map counts continue at 11, after movement_cost
        self.assertEqual((ev.SCALES["map_monster"], ev.SCALES["map_human"],
                          ev.SCALES["map_class"], ev.SCALES["map_has"]), (11, 12, 13, 14))
        # D4REV2: the battle's own defeated-unit counters are kinds 7 and 8, after the six map kinds
        self.assertEqual((ev.SCALES["defeated_enemy"], ev.SCALES["defeated_any"]), (7, 8))
        # OLEFFECTS: the squad count is kind 9, the next free kind (evil_scale dispatches it before 7/8)
        self.assertEqual(ev.SCALES["squad"], 9)
        self.assertEqual(ev.SCALES["movement_cost"], 10)
        # a percentage family carries only the scale byte
        _rows, _conds, fx = ev.table({7501: {"family": "dealt",
                                             "effects": [{"value": 3, "per": "map_enemy"}]}})
        self.assertEqual(fx, [(ev.SCALES["map_enemy"] << 16, 3)])
        # `all` repeats the scale for every stat
        _rows, _conds, fx = ev.table({7502: {"family": "stats", "effects": [
            {"stat": "all", "value": 1, "per": "map_any"}]}})
        self.assertEqual(fx, [(n | (ev.SCALES["map_any"] << 16), 1) for n in range(8)])
        with self.assertRaises(ValueError):
            ev.table({7503: {"family": "stats", "effects": [{"stat": "atk", "value": 1, "per": "nearby"}]}})
        with self.assertRaises(ValueError):
            ev.table({7504: {"family": "flight", "effects": [{"value": 1, "per": "map_ally"}]}})

    def test_current_sp_is_a_conversion_source(self):
        _rows, _conds, fx = ev.table({7510: {
            "family": "conversion", "effects": [{"stat": "atk", "from": "sp_current", "value": 10}]}})
        self.assertEqual(fx, [(2 | (8 << 8), 10)], "source 8 is the unit's current SP")
        self.assertEqual(ev.CONVERSION_SOURCES["sp_current"], 8)
        # a destination index is still one of the eight stats
        with self.assertRaises(ValueError):
            ev.table({7511: {"family": "conversion",
                             "effects": [{"stat": "sp_current", "from": "atk", "value": 1}]}})

    def test_ex_d5_conditions(self):
        # other-side HP thresholds, any-element, and the action's target count
        for kind, arg in (("other_hp_below", 50), ("other_hp_above", 100),
                          ("target_count", 1), ("target_count_min", 2)):
            _rows, conds, _fx = ev.table({7520: {"family": "dealt", "effects": [{"value": 1}],
                                                 "condition": {"kind": kind, "id": arg}}})
            self.assertEqual(conds, [(ev.COND_KINDS[kind], arg, 0, 0)])
        _rows, conds, _fx = ev.table({7521: {"family": "dealt", "effects": [{"value": 1}],
                                             "condition": {"kind": "element_any"}}})
        self.assertEqual(conds, [(ev.COND_KINDS["element_any"], 0, 0, 0)])
        with self.assertRaises(ValueError):
            ev.table({7522: {"family": "dealt", "effects": [{"value": 1}],
                             "condition": {"kind": "other_hp_below", "id": 0}}})

    def test_type_predicates_are_argument_free_and_poison_zero_is_explicit(self):
        for side in ("self", "other"):
            for type_name in ("human", "monster", "male", "female"):
                kind = side + "_" + type_name
                _rows, conditions, _effects = ev.table({7300: {
                    "family": "dealt", "effects": [{"value": 1}], "condition": {"kind": kind}}})
                self.assertEqual(conditions, [(ev.COND_KINDS[kind], 0, 0, 0)])
        for kind in ("target_status", "self_status", "status_class"):
            _rows, conditions, _effects = ev.table({7400: {
                "family": "dealt", "effects": [{"value": 1}], "condition": {"kind": kind, "id": 0}}})
            self.assertEqual(conditions, [(ev.COND_KINDS[kind], 0, 0, 0)])
        with self.assertRaises(ValueError):
            ev.table({7400: {"family": "dealt", "effects": [{"value": 1}],
                             "condition": {"kind": "has", "id": 0}}})

    def test_ex_e_vocabulary(self):
        # critical rate and regen are their own families; a nullification row is a predicate with no
        # effects, and a regen or crit row may not combine with another pass
        rows, _conds, fx = ev.table({7700: {"family": "crit_rate", "effects": [{"value": 20}]},
                                     7701: {"family": "regen",
                                            "effects": [{"stat": "hp", "value": 10},
                                                        {"stat": "sp", "value": -5}]},
                                     7702: {"family": "damage_null"},
                                     7703: {"family": "ailment_null"}})
        self.assertEqual([r[1] for r in rows],
                         [ev.F_CRIT, ev.F_REGEN, ev.F_DAMAGE_NULL, ev.F_ASTAT_NULL])
        self.assertEqual(fx, [(0, 20), (0, 10), (1, -5)])
        for bad in ({"family": "regen", "effects": [{"stat": "atk", "value": 1}]},      # not a pool
                    {"family": "regen", "effects": [{"value": 1}]},                     # no stat
                    {"family": "regen", "effects": [{"stat": "hp", "value": 1, "per": "map_any"}]},
                    {"family": ["regen", "stats"], "effects": [{"stat": "hp", "value": 1}]},
                    {"family": ["damage_null", "taken"]},
                    {"family": "damage_null", "effects": [{"value": 1}]},
                    {"family": "crit_rate"}):                                          # no effects
            with self.assertRaises(ValueError):
                ev.table({7704: bad})
        # near_char takes (of, radius, id) like near_has but names a character; other_adj takes nothing
        _rows, conds, _fx = ev.table({7705: {"family": "stats", "effects": [{"stat": "atk", "value": 1}],
                                            "condition": {"kind": "near_char", "of": 1, "radius": 1,
                                                          "id": 650}}})
        self.assertEqual(conds, [(ev.COND_KINDS["near_char"], 1, 1, 650)])
        _rows, conds, _fx = ev.table({7706: {"family": "dealt", "effects": [{"value": 1}],
                                            "condition": {"kind": "other_adj"}}})
        self.assertEqual(conds, [(ev.COND_KINDS["other_adj"], 0, 0, 0)])
        for bad in ({"kind": "near_char", "of": 3, "radius": 1, "id": 650},
                    {"kind": "near_char", "of": 1, "radius": 1},
                    {"kind": "near_char", "of": 1, "radius": 1, "id": 0}):
            with self.assertRaises(ValueError):
                ev.table({7707: {"family": "dealt", "effects": [{"value": 1}], "condition": bad}})

    def test_full_import_capacity_and_last_array_offsets(self):
        self.assertGreaterEqual(ev.MAX_ROWS, 512)
        rows = {8000 + i: {"family": "stats", "effects": [{"stat": "all", "value": 1}],
                           "conditions": [{"kind": "has", "id": j + 1} for j in range(4)]}
                for i in range(512)}
        table, conditions, effects = ev.table(rows)
        self.assertEqual((len(table), len(conditions), len(effects)), (512, 2048, 4096))
        self.assertEqual(table[-1][2:6], (2044 * 8, 4, 4088 * 8, 8))

    def test_several_rows_may_share_one_evility_id(self):
        table, conditions, effects = ev.table({
            7300: [{"family": "move", "effects": [{"value": 3}]},
                   {"family": "potency", "effects": [{"stat": "atk", "value": -30}]}],
            7301: {"family": "dealt", "effects": [{"value": 10}]}})
        self.assertEqual([r[0] for r in table], [7300, 7300, 7301], "a shared id stays adjacent")
        self.assertEqual([r[1] for r in table][:2], [ev.F_MOVE, ev.F_POTENCY])
        self.assertEqual([r[4:6] for r in table][:2], [(0, 1), (8, 1)], "each row has its own effects")
        self.assertEqual(effects, [(0, 3), (2, -30), (0, 10)])

    def test_two_rows_of_one_family_under_two_conditions(self):
        table, conditions, effects = ev.table({7302: [
            {"family": "move", "effects": [{"value": 3}], "condition": {"kind": "hp_below", "id": 25}},
            {"family": "move", "effects": [{"value": 1}]}]})
        self.assertEqual([c[0] for c in conditions], [ev.COND_KINDS["hp_below"]])
        self.assertEqual([(r[3], r[5]) for r in table], [(1, 1), (0, 1)], "conditions are per row")
        self.assertEqual(effects, [(0, 3), (0, 1)])

    def test_d4_batch1_rows_compile(self):
        """The rows the D4 review actually emits (d4-review/verdicts.json) validate as written.

        D4 176 Chicken Heart is the multi-effect case: MV +3 and all stats -30 % on one id, which is a
        `move` row and a `stats` row (all eight aggregate stats), not one row with two families.
        D4 228 Last Fortress and D4 697 Official Protection exercise the two remaining shapes this batch
        uses -- a gated aggregate row and a provider aura on the aggregate pass.
        """
        table, conditions, effects = ev.table({
            8176: [{"family": "move", "effects": [{"value": 3}]},
                   {"family": "stats", "effects": [{"stat": "all", "value": -30}]}],
            8228: {"family": "stats", "condition": {"kind": "hp_below", "id": 25},
                   "effects": [{"stat": "def", "value": 50}, {"stat": "res", "value": 50}]},
            8697: {"family": ["stats", "aura"],
                   "effects": [{"stat": "def", "value": 20}, {"stat": "res", "value": 20}],
                   "condition": {"kind": "near_has", "of": 1, "radius": 1, "id": 8697}}})
        self.assertEqual([r[0] for r in table], [8176, 8176, 8228, 8697])
        self.assertEqual([r[1] for r in table][:2], [ev.F_MOVE, ev.F_STATS])
        # move carries one number, stats-all carries the eight aggregate words
        self.assertEqual(len(effects), 1 + 8 + 2 + 2)
        self.assertEqual([c[0] for c in conditions], [ev.COND_KINDS["hp_below"], ev.COND_KINDS["near_has"]])
        self.assertEqual(table[1][2:6], (0, 0, 8, 8), "the stat row starts after the move row's one effect")

    def test_d4rev2_rows_compile(self):
        """The four D4 evilities the D4REV2 vocabulary makes exact, each carrying D4's own number."""
        table, conditions, effects = ev.table({
            8391: {"family": "taken", "effects": [{"value": -80}],
                   "condition": {"kind": "defending"}},
            8392: {"family": "taken", "effects": [{"value": -30}],
                   "conditions": [{"kind": "attack_dir", "id": 0}]},
            # D4 347 is "ATK +5% per defeated enemy"; D5's own carrier for its identical evility (140) is
            # the attack-power pass, so this is family power, not a stat aggregate.
            8347: {"family": "power", "effects": [{"value": 5, "per": "defeated_enemy"}]},
            8815: {"family": "absorb", "effects": [{"value": 10}]}})
        self.assertEqual([r[0] for r in table], [8347, 8391, 8392, 8815])
        self.assertEqual([r[1] for r in table],
                         [ev.F_POWER, ev.F_TAKEN, ev.F_TAKEN, ev.F_ABSORB])
        # the defending condition takes no argument and is kind 47, after other_slot (46)
        self.assertEqual(conditions[0], (47, 0, 0, 0))
        self.assertEqual(ev.COND_KINDS["defending"], 47)
        # attack_dir keeps its id and 0 (front) stays a legitimate argument on a `taken` row
        self.assertEqual(conditions[1], (ev.COND_KINDS["attack_dir"], 0, 0, 0))
        # the scale rides in byte 2 of the effect word; the value is D4's 5, not D5's 10
        self.assertEqual(effects[0], (7 << 16, 5))
        # absorb is one percentage (D4's 10, not D5's 20) with no stat and no scale
        self.assertEqual(effects[-1], (0, 10))
        self.assertEqual(ev.F_ABSORB, 1048576)
        self.assertEqual(ev.FAMILIES["absorb"], ev.F_ABSORB)
        self.assertTrue(ev.F_ABSORB & (1 << 31) == 0, "the mask word stays a positive u32")
        # and it is wired to its own wrapper at a real call site
        tag, target, sites = ev.wrapper("absorb")
        self.assertEqual((tag, target), (0xE70014, ev.ABSORB_PASS))
        self.assertEqual(sites, [0x1401AEE62])
        for bad in ({"family": "absorb", "effects": [{"stat": "atk", "value": 10}]},
                    {"family": "absorb", "effects": [{"value": 10, "per": "map_enemy"}]},
                    {"family": ["absorb", "stats"], "effects": [{"value": 10}]},
                    {"family": "absorb"}):
            with self.assertRaises(ValueError):
                ev.table({8815: bad})
        # `per` needs a stat or percentage family: absorb reads a live unit already
        with self.assertRaises(ValueError):
            ev.table({8347: {"family": "absorb", "effects": [{"value": 1, "per": "defeated_enemy"}]}})

    def test_d4rev2_batch2_rows_compile(self):
        """Shapes pack B's ten monster classes emit (D4 review batch 2), each with D4's own number."""
        table, conditions, effects = ev.table({
            # element blessings: one dealt row gated on the action's own element
            8013: {"family": "dealt", "effects": [{"value": 30}],
                   "condition": {"kind": "element", "id": 1}},
            # a debuff aura on enemies: the recipient's aggregate pass, provider = an adjacent enemy
            8118: {"family": ["stats", "aura"], "effects": [{"stat": "spd", "value": -50}],
                   "condition": {"kind": "near_has", "of": 2, "radius": 1, "id": 8118}},
            # one id, two families (D4 809 Stone Wall: DEF/RES +30, MV -2)
            8809: [{"family": "stats", "effects": [{"stat": "def", "value": 30},
                                                   {"stat": "res", "value": 30}]},
                   {"family": "move", "effects": [{"value": -2}]}],
            # a monster-weapon stat conversion (D4 94 Mach Strike)
            8094: {"family": "conversion", "effects": [{"stat": "atk", "from": "spd", "value": 30}]},
            # round-edge HP regeneration (D4 421 Photosynthesis)
            8421: {"family": "regen", "effects": [{"stat": "hp", "value": 10}]},
            # damage against a statused target (D4 274 Spiritual Wave: Forget/Amnesia is index 3)
            8274: {"family": "dealt", "effects": [{"value": 100}],
                   "condition": {"kind": "target_status", "id": 3}},
        })
        self.assertEqual([r[0] for r in table], [8013, 8094, 8118, 8274, 8421, 8809, 8809])
        self.assertEqual(table[1][1], ev.F_CONVERSION)   # 8094
        self.assertEqual(table[4][1], ev.F_REGEN)         # 8421
        self.assertEqual([t[0] for t in conditions],
                         [ev.COND_KINDS["element"], ev.COND_KINDS["near_has"],
                          ev.COND_KINDS["target_status"]])
        # the aura row's provider test keeps its relation (2 = enemy) and radius (1)
        self.assertEqual(conditions[1], (ev.COND_KINDS["near_has"], 2, 1, 8118))
        # the aura row keeps the aura bit beside the family it rides
        self.assertEqual(table[2][1], ev.F_STATS | ev.F_AURA)
        # conversion packs destination in byte 0 and the base source in byte 1 of the effect word
        self.assertEqual(effects[1], ((ev.STATS["atk"] | (ev.STATS["spd"] << 8)), 30))
        # the same id carries two rows of different families, and the move row is second
        self.assertEqual([r[1] for r in table[-2:]], [ev.F_STATS, ev.F_MOVE])
        # a conversion needs both a destination and a base source, and moves are not conversions
        with self.assertRaises(ValueError):
            ev.table({8094: {"family": "conversion", "effects": [{"value": 30}]}})

    def test_d4rev2_batch3_rows_compile(self):
        """Shapes the twelve earliest D4 generic classes emit (D4 review batch 3), each with D4's number."""
        table, conditions, effects = ev.table({
            # D4 71 Armor Mastery: one potency row with two equipment-aptitude words (HP and DEF at 30)
            8071: {"family": "potency", "effects": [{"stat": "hp", "value": 30},
                                                   {"stat": "def", "value": 30}]},
            # D4 84 Energy Slash: a conversion gated on the equipped weapon category (2 = sword)
            8084: {"family": "conversion", "condition": {"kind": "weapon", "id": 2},
                   "effects": [{"stat": "atk", "from": "sp_current", "value": 10}]},
            # D4 38 Shield Mastery: a reduction that only applies to a normal attack
            8038: {"family": "taken", "effects": [{"value": -50}],
                   "conditions": [{"kind": "attack_normal"}]},
            # D4 40 Max. HP DEF Boost: gated on the *attacker* being at full HP (taken's other side)
            8040: {"family": "taken", "effects": [{"value": -20}],
                   "condition": {"kind": "other_hp_above", "id": 100}},
            # D4 48 Enlarge: one panel from the range getter
            8048: {"family": "range", "effects": [{"value": 1}]},
            # D4 229 Evasive Maneuvers: move range while the unit is under 25 % HP
            8229: {"family": "move", "effects": [{"value": 3}],
                   "condition": {"kind": "hp_below", "id": 25}},
            # D4 108 Wild Cry: 20 % per adjacent enemy (a runtime magnitude, not a fixed value)
            8108: {"family": "stats", "effects": [{"stat": "all", "value": 20,
                                                   "per": "adjacent_enemy"}]},
            # D4 335 Assault Attack: 10 % per defeated enemy on the damage multiplier
            8335: {"family": "dealt", "effects": [{"value": 10, "per": "defeated_enemy"}]},
            # D4 352 Flicker Wing: a predicate row - no effects, a neighbour and a half-chance
            8352: {"family": "nullify", "conditions": [{"kind": "other_adj"},
                                                       {"kind": "rng", "id": 50}]},
            # D4 262 Hypnosis Wave: ailment chance for sleep (index 1) on a normal attack
            8262: {"family": "status_chance", "effects": [{"value": 50}],
                   "conditions": [{"kind": "attack_normal"}, {"kind": "status_class", "id": 1}]},
            # D4 266 Star Crossed Fate: one row per reviewed ailment, four rows of one id
            8266: [{"family": "status_chance", "effects": [{"value": 30}],
                    "conditions": [{"kind": "status_class", "id": k}]} for k in range(4)],
        })
        self.assertEqual([r[0] for r in table],
                         [8038, 8040, 8048, 8071, 8084, 8108, 8229, 8262, 8266, 8266, 8266, 8266, 8335,
                          8352])
        self.assertEqual([r[1] for r in table],
                         [ev.F_TAKEN, ev.F_TAKEN, ev.F_RANGE, ev.F_POTENCY, ev.F_CONVERSION, ev.F_STATS,
                          ev.F_MOVE, ev.F_STATUS, ev.F_STATUS, ev.F_STATUS, ev.F_STATUS, ev.F_STATUS,
                          ev.F_DEALT, ev.F_NULLIFY])
        # a weapon-gated conversion keeps the category id in its condition and the base source in byte 1
        self.assertIn((ev.COND_KINDS["weapon"], 2, 0, 0), conditions)
        self.assertIn(((ev.STATS["atk"] | (ev.CONVERSION_SOURCES["sp_current"] << 8)), 10), effects)
        # "all" expands to the eight stat words and the scale rides in byte 2 of each effect word
        for n in range(8):
            self.assertIn((n | (ev.SCALES["adjacent_enemy"] << 16), 20), effects)
        # ... and the multi-word potency row carries both of its words at D4's number
        self.assertIn((ev.STATS["hp"], 30), effects)
        self.assertIn((ev.STATS["def"], 30), effects)
        # a predicate row carries no effects at all, and its two conditions are both recorded
        self.assertEqual([r[1] for r in table if r[0] == 8352], [ev.F_NULLIFY])
        self.assertEqual(sorted(c[0] for c in conditions
                                if c[0] in (ev.COND_KINDS["other_adj"], ev.COND_KINDS["rng"])),
                         [ev.COND_KINDS["rng"], ev.COND_KINDS["other_adj"]])
        # four rows of one id are four table rows, each with its own status-class condition
        self.assertEqual([r[0] for r in table].count(8266), 4)
        self.assertEqual([c for c in conditions if c[0] == ev.COND_KINDS["status_class"]],
                         [(ev.COND_KINDS["status_class"], 1, 0, 0)]          # 8262: sleep
                         + [(ev.COND_KINDS["status_class"], k, 0, 0) for k in range(4)])
        # a predicate row may not carry effects, and a scale needs a stat/percentage family
        with self.assertRaisesRegex(ValueError, "no effects"):
            ev.table({8352: {"family": "nullify", "effects": [{"value": 50}]}})

    def test_d4rev4_batch4_rows_compile(self):
        """Shapes the seventeen remaining D4 generic classes emit (D4 review batch 4), at D4's numbers."""
        table, conditions, effects = ev.table({
            # D4 4 Cleanse Evil / 24 Calming Aura: the other side's unit type, on a dealt and a taken row
            8004: {"family": "dealt", "effects": [{"value": 25}], "condition": {"kind": "other_monster"}},
            8024: {"family": "taken", "effects": [{"value": -50}], "condition": {"kind": "other_monster"}},
            # D4 11 Spirit Benediction: only an attack that carries an element
            8011: {"family": "dealt", "effects": [{"value": 20}], "condition": {"kind": "element_any"}},
            # D4 75 Gimmick Body: two rows on one id (aptitude +100, every stat -50)
            8075: [{"family": "potency", "effects": [{"stat": "all", "value": 100}]},
                   {"family": "stats", "effects": [{"stat": "all", "value": -50}]}],
            # D4 103 Dark Tamer: an aura on an adjacent ally monster (provider named by near_has)
            8103: {"family": ["aura", "stats"], "effects": [{"stat": "all", "value": 20}],
                   "conditions": [{"kind": "near_has", "of": 1, "radius": 1, "id": 8103},
                                  {"kind": "self_monster"}]},
            # D4 211 Cursed Dance: the same aura, map-wide (radius 0xFFFF is 'no distance limit')
            8211: {"family": ["aura", "stats"], "effects": [{"stat": "all", "value": -5}],
                   "conditions": [{"kind": "near_has", "of": 2, "radius": 65535, "id": 8211}]},
            # D4 625 Angel Protection: an ally takes less from non-elemental attacks only
            8625: {"family": ["aura", "taken"], "effects": [{"value": -50}],
                   "conditions": [{"kind": "near_has", "of": 1, "radius": 1, "id": 8625},
                                  {"kind": "element", "id": 0}]},
            # D4 429 Revival: a full recovery at the round edge under 25 % HP
            8429: {"family": "regen", "effects": [{"stat": "hp", "value": 100}],
                   "condition": {"kind": "hp_below", "id": 25}},
            # D4 350 Sharp Eye: critical-rate points, no stat
            8350: {"family": "crit_rate", "effects": [{"value": 20}]},
            # D4 272 Dream Hunt / 291 Poison Mutilation: the other side's, then this unit's, status
            8272: {"family": "dealt", "effects": [{"value": 100}],
                   "condition": {"kind": "target_status", "id": 1}},
            8291: {"family": "stats", "effects": [{"stat": "atk", "value": 50}],
                   "condition": {"kind": "self_status", "id": 0}},
            # D4 344 Calm Waters / 354 Flame Haze: how many targets the action resolved to
            8344: {"family": "dealt", "effects": [{"value": 30}], "condition": {"kind": "target_count", "id": 1}},
            8354: {"family": "nullify", "conditions": [{"kind": "attack_skill"},
                                                       {"kind": "target_count_min", "id": 2},
                                                       {"kind": "rng", "id": 50}]},
        })
        self.assertEqual([r[0] for r in table],
                         [8004, 8011, 8024, 8075, 8075, 8103, 8211, 8272, 8291, 8344, 8350, 8354, 8429,
                          8625])
        self.assertEqual([r[1] for r in table],
                         [ev.F_DEALT, ev.F_DEALT, ev.F_TAKEN, ev.F_POTENCY, ev.F_STATS,
                          ev.F_AURA | ev.F_STATS, ev.F_AURA | ev.F_STATS, ev.F_DEALT, ev.F_STATS,
                          ev.F_DEALT, ev.F_CRIT, ev.F_NULLIFY, ev.F_REGEN, ev.F_AURA | ev.F_TAKEN])
        # the provider condition keeps both the radius and the id it names
        self.assertIn((ev.COND_KINDS["near_has"], 1, 1, 8103), conditions)
        self.assertIn((ev.COND_KINDS["near_has"], 2, 65535, 8211), conditions)
        # "all" on the potency half of 8075 is eight words at +100; the aggregate half is eight at -50
        for n in range(8):
            self.assertIn((n, 100), effects)
            self.assertIn((n, -50), effects)
        # a taken aura can narrow itself to non-elemental attacks (element 0), and the status fixes stay
        self.assertIn((ev.COND_KINDS["element"], 0, 0, 0), conditions)
        self.assertIn((ev.COND_KINDS["target_status"], 1, 0, 0), conditions)
        self.assertIn((ev.COND_KINDS["self_status"], 0, 0, 0), conditions)
        self.assertIn((ev.COND_KINDS["target_count"], 1, 0, 0), conditions)
        self.assertIn((ev.COND_KINDS["target_count_min"], 2, 0, 0), conditions)
        self.assertEqual([r[1] for r in table if r[0] == 8354], [ev.F_NULLIFY])
        # regen is hp or sp only, and cannot ride another family (it is a round-edge pass)
        with self.assertRaisesRegex(ValueError, "regen applies to hp or sp"):
            ev.table({8429: {"family": "regen", "effects": [{"stat": "atk", "value": 10}]}})
        with self.assertRaisesRegex(ValueError, "regen cannot combine"):
            ev.table({8429: {"family": ["regen", "stats"], "effects": [{"stat": "hp", "value": 10}]}})
        # an aura row without a provider condition is refused, and so is a radius that does not fit u16
        with self.assertRaisesRegex(ValueError, "aura row needs a condition naming the provider"):
            ev.table({8103: {"family": ["aura", "stats"], "effects": [{"stat": "all", "value": 20}]}})
        with self.assertRaisesRegex(ValueError, "out of range"):
            ev.table({8211: {"family": ["aura", "stats"], "effects": [{"stat": "all", "value": -5}],
                             "conditions": [{"kind": "near_has", "of": 2, "radius": 65536, "id": 8211}]}})

    def test_every_row_of_a_shared_id_is_validated_on_its_own(self):
        # the pre-P3b rule stays: one row may not mix an additive family with another family, so a
        # mixed evility is several rows, not one row with a tag
        with self.assertRaisesRegex(ValueError, "additive pass of its own"):
            ev.table({7303: {"family": ["move", "potency"],
                             "effects": [{"value": 1}, {"stat": "atk", "value": 2}]}})
        with self.assertRaisesRegex(ValueError, "empty row list"):
            ev.table({7303: []})
        with self.assertRaisesRegex(ValueError, "not an object"):
            ev.table({7303: [1]})
        with self.assertRaisesRegex(ValueError, "expected an object or a list of objects"):
            ev.table({7303: "move"})

    def test_shared_ids_are_counted_in_the_row_and_effect_budgets(self):
        rows = {8000 + i: [{"family": "dealt", "effects": [{"value": 1}]}] * 2 for i in range(ev.MAX_ROWS // 2)}
        table, _conditions, effects = ev.table(rows)
        self.assertEqual(len(table), ev.MAX_ROWS)
        self.assertEqual(len(effects), ev.MAX_ROWS)
        with self.assertRaisesRegex(ValueError, "too many new rows"):
            ev.table({9000: [{"family": "dealt", "effects": [{"value": 1}]}] * (ev.MAX_ROWS + 1)})

    def test_filtered_map_counts_need_a_filter_and_expand_class_lists(self):
        # CARRIERS2: map_class / map_has read the row's own filter argument (row dword 7)
        rows, _conditions, fx = ev.table({8100: {
            "family": "stats", "effects": [{"stat": "atk", "value": 5, "per": "map_class"}],
            "filter": 2120}})
        self.assertEqual(rows[0][7], 2120)
        self.assertEqual(fx, [(2 | (ev.SCALES["map_class"] << 16), 5)])
        # a species written as a class list becomes one row per class id, all of them adding up
        rows, _conditions, fx = ev.table({8101: {
            "family": "stats", "effects": [{"stat": "all", "value": 10, "per": "map_class"}],
            "classes": [2070, 2120]}})
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[7] for r in rows], [2070, 2120])
        self.assertEqual(len(fx), 16)
        # map_has filters on an evility id instead
        rows, _conditions, _fx = ev.table({8102: {
            "family": "stats", "effects": [{"stat": "atk", "value": 7, "per": "map_has"}],
            "filter": 8888}})
        self.assertEqual(rows[0][7], 8888)
        # the filters that do not read a value are the type ones, and they take none
        rows, _conditions, _fx = ev.table({8103: {
            "family": "stats", "effects": [{"stat": "all", "value": 5, "per": "map_monster"}]}})
        self.assertEqual(rows[0][7], 0)
        with self.assertRaisesRegex(ValueError, "needs filter"):
            ev.table({8104: {"family": "stats", "effects": [{"stat": "atk", "value": 5, "per": "map_class"}]}})
        with self.assertRaisesRegex(ValueError, "only read by the filtered map counts"):
            ev.table({8105: {"family": "stats", "effects": [{"stat": "atk", "value": 5}], "filter": 7}})
        with self.assertRaisesRegex(ValueError, "not both"):
            ev.table({8106: {"family": "stats", "effects": [{"stat": "atk", "value": 5, "per": "map_class"}],
                             "filter": 1, "classes": [2]}})
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            ev.table({8107: {"family": "stats", "effects": [{"stat": "atk", "value": 5, "per": "map_class"}],
                             "classes": []}})

    def test_map_has_min_is_a_counted_predicate(self):
        # CARRIERS2: condition 49 -- "at least a units of relation b have learned evility c"
        rows, conditions, _fx = ev.table({8108: {
            "family": "stats", "effects": [{"stat": "all", "value": 50}],
            "condition": {"kind": "map_has_min", "count": 7, "of": 1, "id": 8108}}})
        self.assertEqual(conditions, [(ev.COND_KINDS["map_has_min"], 7, 1, 8108)])
        self.assertEqual(ev.COND_KINDS["map_has_min"], 49, "after CARRIERS' hp_at_or_below (48)")
        with self.assertRaisesRegex(ValueError, "count of at least 1"):
            ev.table({8109: {"family": "stats", "effects": [{"stat": "atk", "value": 1}],
                             "condition": {"kind": "map_has_min", "count": 0, "of": 1, "id": 1}}})
        with self.assertRaisesRegex(ValueError, "map_has_min of 3"):
            ev.table({8110: {"family": "stats", "effects": [{"stat": "atk", "value": 1}],
                             "condition": {"kind": "map_has_min", "count": 2, "of": 3, "id": 1}}})
        with self.assertRaisesRegex(ValueError, "needs 'id'"):
            ev.table({8111: {"family": "stats", "effects": [{"stat": "atk", "value": 1}],
                             "condition": {"kind": "map_has_min", "count": 2, "of": 1}}})
        with self.assertRaisesRegex(ValueError, "map_has_min needs"):
            ev.table({8112: {"family": "stats", "effects": [{"stat": "atk", "value": 1}],
                             "condition": {"kind": "map_has_min", "of": 1, "id": 9}}})

    def test_effect_and_condition_budget_boundaries(self):
        effect = {"stat": "atk", "value": 1}
        condition = {"kind": "has", "id": 1}
        for name, limit in (("effects", ev.MAX_FX), ("conditions", ev.MAX_COND)):
            row = {"family": "stats", "effects": [effect]}
            row[name] = [effect if name == "effects" else condition] * limit
            table, conditions, effects = ev.table({8001: row})
            self.assertEqual(len(effects if name == "effects" else conditions), limit)
            row[name] = row[name] + [effect if name == "effects" else condition]
            with self.assertRaisesRegex(ValueError, "too many " + name):
                ev.table({8001: row})


class CodeTests(unittest.TestCase):
    def source(self):
        rows, conds, fx = ev.table({7001: {"family": "potency", "effects": [{"stat": "atk", "value": 30}]},
                                    7002: {"family": "growth", "effects": [{"stat": 5, "value": 7}],
                                           "condition": {"kind": "level", "id": 20}}})
        return ev._asm_source(rows, conds, fx)

    def test_source_starts_with_the_claim_so_the_table_can_be_found_again(self):
        src = self.source()
        first = src.splitlines()[0]
        want = "    .byte " + ", ".join(str(b) for b in ev.HEADER + bytes(16 - len(ev.HEADER)))
        self.assertEqual(first, want)
        self.assertEqual(ev.HEADER[:4], b"D5EV")

    def test_table_is_written_into_the_source(self):
        src = self.source()
        self.assertIn("evil_tbl:", src)
        self.assertIn("    .long 7001, 1, 0, 0, 0, 1, 0, 0", src)
        self.assertIn("    .long 7002, 4, 0, 1, 8, 1, 0, 0", src)
        self.assertIn("    .long 0, 0, 0, 0, 0, 0, 0, 0", src, "the terminator row")
        self.assertIn("evil_cond:", src)
        self.assertIn(f"    .word {ev.COND_KINDS['level']}, 20, 0, 0", src)
        self.assertIn("    .long 2, 30", src)
        self.assertIn("    .long 5, 7", src)

    def test_assembles_and_exposes_every_wrapper(self):
        base = 0x148000000
        code, labels = ev._assemble(self.source(), base)
        self.assertEqual(sorted(labels), sorted(ev.TAGS))
        for tag in ev.TAGS:
            at = labels[tag] - base
            self.assertEqual(code[at:at + 6], b"\x41\xbb" + struct.pack("<I", tag))

    def test_no_table_data_means_no_effects(self):
        src = ev._asm_source([], [], [])
        self.assertIn("evil_tbl:", src)
        self.assertIn("    .long 0, 0, 0, 0, 0, 0, 0, 0", src)

    def test_two_rows_for_one_id_are_both_written(self):
        rows, conds, fx = ev.table({7300: [{"family": "move", "effects": [{"value": 3}]},
                                           {"family": "potency", "effects": [{"stat": "atk", "value": -30}]}]})
        src = ev._asm_source(rows, conds, fx)
        self.assertIn(f"    .long 7300, {ev.F_MOVE}, 0, 0, 0, 1, 0, 0", src)
        self.assertIn(f"    .long 7300, {ev.F_POTENCY}, 0, 0, 8, 1, 0, 0", src)
        self.assertIn("evil_row_count:\n    .long 2", src, "two rows, one evility id")

    def test_build_redirects_every_original_call_with_call(self):
        # A JMP here would bypass the wrapper return address despite valid displacement.
        labels = {tag: 0x148000100 + tag * 0x10 for tag, _, _ in ev.WRAPPERS}
        with patch.object(ev, "code_base", return_value=0x148000000), \
             patch.object(ev, "_assemble", return_value=(b"code", labels)), \
             patch.object(ev, "_offset", return_value=0), \
             patch.object(ev, "_check_site"), \
             patch.object(ev, "add_code_section", return_value=b"patched") as add:
            self.assertEqual(ev.build_patch(b"original", {}), b"patched")
        patches = add.call_args.args[3]
        self.assertEqual(len(patches), sum(len(sites) for _, _, sites in ev.WRAPPERS))
        self.assertTrue(all(opcode == 0xE8 for _, _, _, opcode in patches))

    def test_site_check(self):
        va, target = 0x14021CD02, 0x1401E1B30
        good = b"\xe8" + struct.pack("<i", target - (va + 5))
        self.assertEqual(ev._check_site(va, good, target), target)
        with self.assertRaises(ValueError):
            ev._check_site(va, b"\x90" * 5, target)
        with self.assertRaises(ValueError):
            ev._check_site(va, b"\xe8" + struct.pack("<i", 0x1401E9B50 - (va + 5)), target)


class ModDataTests(unittest.TestCase):
    def test_roundtrip(self):
        mod = FakeMod()
        data = {"evilities": {"7001": {"family": "potency", "effects": [{"stat": "atk", "value": 30}]}}}
        ev.save(mod, data)
        self.assertEqual(ev.load(mod), data)
        self.assertEqual(ev.load(FakeMod()), {"evilities": {}})

    def test_a_later_mod_appends_rows_to_a_shared_id(self):
        acc = {}
        ev._merge(acc, "7001", {"family": "potency", "effects": [{"stat": "atk", "value": 30}]})
        ev._merge(acc, 7001, [{"family": "move", "effects": [{"value": 1}]}])
        self.assertEqual([r["family"] for r in acc[7001]], ["potency", "move"],
                         "a list entry adds to whatever the earlier mod had")
        ev._merge(acc, 7001, [{"family": "range", "effects": [{"value": 2}]}])
        self.assertEqual([r["family"] for r in acc[7001]], ["potency", "move", "range"])

    def test_two_single_rows_still_merge_key_by_key(self):
        acc = {}
        ev._merge(acc, "7002", {"family": "potency", "effects": [{"stat": "atk", "value": 1}],
                                "condition": {"kind": "level", "id": 2}})
        ev._merge(acc, "7002", {"family": "potency", "effects": [{"stat": "def", "value": 3}]})
        self.assertEqual(acc[7002]["effects"], [{"stat": "def", "value": 3}], "a later mod still overrides")
        self.assertIn("condition", acc[7002])

    def test_saved_file_is_json_in_the_mod(self):
        mod = FakeMod()
        ev.save(mod, {"evilities": {}})
        self.assertEqual(json.loads(mod.files["patches/evilities/evilities.json"]), {"evilities": {}})


if __name__ == "__main__":
    unittest.main()
