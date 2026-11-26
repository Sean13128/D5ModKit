"""Offline DRPG importer boundaries; synthetic art bytes, never game data.

The local roster acceptance check skips when the private research inputs are
absent. Allocation and provenance checks use temporary trees and mocked readers.
"""
import copy
import hashlib
import json
import pickle
import tempfile
import unittest
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from d5lib.importcore import Entry
from d5lib.importers import drpg
from d5lib.importers import _drpg_build as worker
from d5lib.importers import _drpg_namespaces as namespaces
from d5lib.importers import _drpg_monsters as monsters
from d5lib.importers import _drpg_reference as reference


class TemporaryTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="corerpg1-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)


class RosterTests(unittest.TestCase):
    """The reviewed roster is the kit's ``drpg-roster-*.json`` (SOURCEPREP4-DRPG): ids and rules, text as references."""

    def groups(self):
        from d5lib.importers import _drpg_roster
        return [g['character'] for g in _drpg_roster.load()['groups']]

    def test_reviewed_roster_scope_and_zed(self):
        from d5lib.importers import _drpg_roster
        groups = self.groups()
        self.assertEqual(len(groups), 146)
        self.assertEqual(len({g['base_id'] for g in groups}), 146)
        zed = next(g for g in groups if g['base_id'] == 94)
        self.assertEqual({l['id'] for l in zed['looks']}, {94, 182})
        self.assertTrue(zed['commands'])
        self.assertTrue(zed['leader_skills'])
        self.assertTrue(zed['mapping_provenance']['pins'])
        look_ids = {f"drpg:{g['base_id']}": {l['id'] for l in g['looks']} for g in groups}
        self.assertNotIn(20098, look_ids['drpg:117'])
        self.assertIn(20098, look_ids['drpg:20072'])
        self.assertIn(317, look_ids['drpg:162'])
        self.assertIn(20103, look_ids['drpg:20103'])
        self.assertNotIn(20103, look_ids['drpg:347'])
        self.assertIn(314, look_ids['drpg:161'])
        for dropped in ('drpg:20051', 'drpg:335', 'drpg:357'):
            self.assertNotIn(dropped, look_ids)
        for bid, ids in look_ids.items():
            self.assertTrue(ids)
        pins = {p['file'] for g in groups for p in g['mapping_provenance']['pins']} if False else set()

    def test_entries_carry_the_roster_identity_and_no_machine_path(self):
        from d5lib.importers import _drpg_roster
        chars = [(dict(base_id=7, name='Test Person', looks=[dict(id=7, type='humanoid')]), 7)]
        (entry,) = drpg.entries(chars, _drpg_roster.file_sha256())
        self.assertEqual(entry.id, 'drpg:7')
        self.assertEqual(entry.mod_folder, 'DRPG_Core_TestPerson_7')
        ref = entry.source_ref
        self.assertEqual(ref['sha256'], _drpg_roster.file_sha256())
        self.assertEqual(ref['row'], {'base_id': 7})
        self.assertNotIn('/', ref['original_root'])
        self.assertEqual(ref['art_policy'], 'original-verified-prepared-only')

    def test_kind_classifies_the_whole_family(self):
        self.assertEqual(drpg.family_kind([{"type": "monster"}]), "monster")
        self.assertEqual(drpg.family_kind([{"type": "humanoid"}]), "humanoid")
        self.assertEqual(drpg.family_kind([
            {"type": "humanoid"}, {"type": "monster"}]),
            "humanoid-with-monster-variant")


class GroupingDecisionTests(unittest.TestCase):
    def group(self, bid, looks):
        return dict(base_id=bid, name=f'Person {bid}', best_base_look_id=looks[0],
                    looks=[dict(id=i, en=f'Look {i}', jp='name', type='humanoid', art={}) for i in looks])

    def doc(self, groups):
        return dict(schema='drpg-grouping-decisions/1', characters=groups)

    def test_unchanged_membership_keeps_reviewed_mapping_and_pins(self):
        old = dict(self.group(1, [1, 2]), commands=[{'rpg_id': 9}],
                   leader_skills=[{'rpg_id': 8}], mapping_provenance={'reviewed': True})
        with patch('d5lib.importers._drpg_zed.mapped_family') as mapper:
            result = drpg.reviewed_characters([old], self.doc([self.group(1, [2, 1])]))
        mapper.assert_not_called()
        self.assertEqual(result[0][0]['commands'], [{'rpg_id': 9}])
        self.assertEqual(result[0][0]['mapping_provenance'], {'reviewed': True})
        self.assertEqual(result[0][1], 2)
        self.assertEqual(old['looks'][0]['id'], 1)

    def test_split_and_merge_remap_only_assigned_looks_without_stale_abilities(self):
        old = dict(self.group(1, [1, 2]), commands=[{'rpg_id': 999}], leader_skills=[])
        groups = [self.group(1, [1, 3]), self.group(2, [2])]
        def mapped(family):
            ids = [v['id'] for v in family['variants']]
            return dict(commands=[{'rpg_id': i} for i in ids], leader_skills=[])
        with patch('d5lib.importers._drpg_zed.mapped_family', side_effect=mapped) as mapper:
            result = drpg.reviewed_characters([old], self.doc(groups))
        self.assertEqual(mapper.call_count, 2)
        self.assertEqual([r[0]['commands'] for r in result],
                         [[{'rpg_id': 1}, {'rpg_id': 3}], [{'rpg_id': 2}]])
        self.assertNotIn(999, [v['rpg_id'] for r, _ in result for v in r['commands']])

    def test_invalid_or_repeated_assignments_fail_before_mapping(self):
        duplicate = self.group(2, [1])
        missing_best = dict(self.group(2, [2]), best_base_look_id=99)
        for groups in ([self.group(1, [1]), duplicate], [missing_best],
                       [self.group(1, [1, 1])], [self.group(1, [1]), self.group(1, [2])]):
            with self.subTest(groups=groups), patch('d5lib.importers._drpg_zed.mapped_family', return_value={}), self.assertRaises(ValueError):
                drpg.reviewed_characters([], self.doc(groups))
        with self.assertRaisesRegex(ValueError, 'schema'):
            drpg.reviewed_characters([], {'schema': 'unknown', 'characters': []})


class RegroupedAbilityTests(unittest.TestCase):
    def test_master_links_are_filtered_to_exact_group_membership(self):
        from d5lib.importers import _drpg_zed as mapping
        inputs = {
            'character': [dict(id=1, best_weapon_type=7, m_leader_skill_id=11),
                          dict(id=2, best_weapon_type=8, m_leader_skill_id=22)],
            'charactercommand': [dict(m_character_id=1, m_command_id=101),
                                 dict(m_character_id=2, m_command_id=202)],
            'command': [dict(id=101), dict(id=202)],
            'leaderskill': [dict(id=11), dict(id=22)],
            'd5-catalogs': {'Skill.dat': [{'id': 1}]}}
        mapper = SimpleNamespace(D5=lambda cat: SimpleNamespace(magic=True),
            map_command=Mock(return_value={'verdict': 'adapted'}), ELEMENT={}, TARGET={})
        leader = SimpleNamespace(build_ev_index=lambda rows: [1],
            map_ls=Mock(side_effect=lambda row, index: {'rpg_id': row['id']}))
        def read(path, *args):
            return json.dumps(inputs[path.stem]).encode()
        family = dict(base_id=2, base_name='Separate person',
                      variants=[dict(id=2, type='monster')])
        env = dict(DRPG_DATA='/data', DRPG_D5_CATALOGS='/d5-catalogs.json', DRPG_MAPPING_TOOLS='/tools')
        with patch.dict('os.environ', env), patch.object(mapping, '_read', side_effect=read), patch.object(
                mapping, '_tool', side_effect=[mapper, leader]):
            result = mapping.mapped_family(family)
        self.assertEqual([c['rpg_id'] for c in result['commands']], [202])
        self.assertEqual([l['rpg_id'] for l in result['leader_skills']], [22])
        self.assertEqual(result['mapping_provenance']['character_ids'], [2])
        self.assertEqual(result['mapping_provenance']['command_source_characters'], {'202': 2})
        mapper.map_command.assert_called_once_with({'id': 202}, unittest.mock.ANY, 8)
        self.assertEqual(result['base_id'], 2)
        self.assertEqual(result['kind'], 'monster')

    def test_regrouping_needs_the_maintainer_locations_and_has_no_machine_default(self):
        from d5lib.importers import _drpg_zed as mapping
        with patch.dict('os.environ', {}, clear=True), self.assertRaisesRegex(FileNotFoundError, 'maintainer step'):
            mapping.mapped_family(dict(base_id=2, base_name='X', variants=[dict(id=2, type='humanoid')]))

    def test_legacy_zed_wrapper_still_rejects_unreviewed_membership(self):
        from d5lib.importers import _drpg_zed as mapping
        with self.assertRaisesRegex(ValueError, 'reviewed Zed'):
            mapping.mapped_zed(dict(base_id=94, variants=[{'id': 94}]))


class ProvenanceTests(TemporaryTree):
    """Art provenance now means: a verified row of the prepared manifest (``_drpg_source``), nothing else."""

    def setUp(self):
        super().setUp()
        self.files = {}

    def sheets(self, uid, label, portraits=True):
        from d5lib.importers import _drpg_source as src
        rels = src.unit_files(uid)
        roles = list(src.REQUIRED_ROLES) + (["icon", "cutin"] if portraits else [])
        for role in roles:
            self.files[rels[role]] = f"synthetic {label} {role}".encode()
        return {role: rels[role] for role in roles}

    def data(self):
        from d5lib import sourcefolder
        from d5lib.importers import _drpg_source as src
        root = self.root / "Source"
        rows = []
        for rel, raw in self.files.items():
            path = root / "drpg" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            rows.append(dict(path=rel, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), verified="yes"))
        sourcefolder.write_manifest(root, {"drpg": dict(supplied=True, files=rows)})
        return src.data(root)

    def test_complete_original_pins_every_consumed_file(self):
        paths = self.sheets(7, "original")
        assets = worker.source_assets(7, self.data())
        self.assertEqual(assets["provenance"], "original")
        self.assertEqual(set(assets["files"]), set(paths))
        for role, rel in paths.items():
            self.assertEqual(assets["files"][role], {
                "path": f"drpg/{rel}", "sha256": hashlib.sha256(self.files[rel]).hexdigest(),
                "provenance": "original", "rel": rel})

    def test_a_missing_sheet_role_fails_instead_of_filling_from_anywhere_else(self):
        paths = self.sheets(7, "original")
        del self.files[paths["wait_back"]]
        with self.assertRaisesRegex(FileNotFoundError, "verified source sheets for DRPG unit 7"):
            worker.source_assets(7, self.data())

    def test_missing_sheets_fail_instead_of_claiming_source_art(self):
        self.sheets(8, "other unit")
        with self.assertRaisesRegex(FileNotFoundError, "7"):
            worker.source_assets(7, self.data())

    def test_optional_portraits_are_not_falsely_claimed(self):
        self.sheets(7, "original", portraits=False)
        assets = worker.source_assets(7, self.data())
        self.assertNotIn("icon", assets["files"])
        self.assertNotIn("cutin", assets["files"])

    def test_best_look_is_first_and_exact_sheet_duplicates_keep_source_ids(self):
        self.sheets(7, "same")
        self.sheets(8, "same")
        self.sheets(9, "different")
        looks = [{"id": n, "type": "humanoid"} for n in (7, 8, 9)]
        result = worker.distinct_looks({"looks": looks}, 8, self.data())
        self.assertEqual([l["id"] for l in result], [8, 9])
        self.assertEqual(result[0]["equivalent_ids"], [7])
        self.assertEqual(looks, [{"id": n, "type": "humanoid"} for n in (7, 8, 9)])

    def test_look_with_different_portrait_is_retained_as_costume(self):
        self.sheets(7, "same")
        paths = self.sheets(8, "same")
        self.files[paths["cutin"]] = b"synthetic alternate cut-in"
        result = worker.distinct_looks({"looks": [
            {"id": 7, "type": "humanoid"}, {"id": 8, "type": "humanoid"}]}, 7, self.data())
        self.assertEqual([l["id"] for l in result], [7, 8])


def entry(uid, look_count=1, folder=None):
    return Entry(f"drpg:{uid}", "humanoid", f"Synthetic {uid}", folder or f"Mod_{uid}", {
        "best_base_look": uid,
        "character": {"base_id": uid, "looks": [
            {"id": uid + 1000 * n, "type": "humanoid"} for n in range(look_count)]}})


class Table:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def find(self, uid):
        return next((r for r in self.rows if r["id"] == uid), None)


class AllocationTests(TemporaryTree):
    def setUp(self):
        super().setUp()
        self.installed = self.root / "installed"
        self.installed.mkdir()
        self.ctx = {"installed_root": self.installed, "game_path": self.root / "game", "installed_reference": True,
                    "source_root": self.root / "source", "output_root": self.root / "out"}
        self.fs = Mock()
        self.mods = {}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(worker, "_PLAN", {}))
        self.stack.enter_context(patch.object(worker, "source_fs", return_value=self.fs))
        self.stack.enter_context(patch.object(worker, "source_data", return_value=Mock()))
        self.stack.enter_context(patch.object(worker.database, "load_table", return_value=Table()))
        self.stack.enter_context(patch.object(worker, "distinct_looks", side_effect=lambda c, best, source_root=None: copy.deepcopy(c["looks"])))
        self.used = self.stack.enter_context(patch.object(worker.sprites, "used_sprite_numbers", return_value=set()))
        self.pool = self.stack.enter_context(patch.object(worker.slots, "unique_pool", return_value=list(range(200, 231))))
        self.stack.enter_context(patch.object(worker.modsys, "Mod", side_effect=lambda p: self.mods[Path(p).name]))
        self.stack.enter_context(patch.object(worker.outfits, "_char_tables", side_effect=lambda fs, mod: (Table(), mod.table)))
        self.stack.enter_context(patch.object(worker.outfits, "load", side_effect=lambda mod: mod.pairs))
        self.stack.enter_context(patch.object(namespaces, "reserve", return_value={}))
        self.stack.enter_context(patch.object(namespaces, "reserve_evilities", return_value={}))

    def installed_mod(self, name, rows, pairs=(), files=()):
        folder = self.installed / name
        folder.mkdir()
        (folder / "mod.json").write_text("{}")
        for filename in files:
            (folder / filename).touch()
        mod = SimpleNamespace(table=Table(rows), pairs=list(pairs))
        mod.load_patch = lambda *args: {"added": rows}
        self.mods[name] = mod

    def test_complete_roster_uses_nonoverlapping_keyed_windows(self):
        roster = [entry(1, 2), entry(2, 3), entry(3)]
        leases = worker.plan(roster, self.ctx)
        self.assertEqual(set(leases), {e.id for e in roster})
        occupied = set()
        for lease in leases.values():
            for art in [lease] + lease["costumes"]:
                n = art["sprite"]
                window = {n, n + 1, n + 2, n + 10000, n + 10001}
                self.assertFalse(occupied & window)
                occupied |= window
        self.fs.reset.assert_called_once()

    def test_exhaustion_has_no_partial_allocation_and_smaller_entries_can_fit(self):
        self.pool.return_value = [200, 203]
        too_large, small = entry(1, 3), entry(2, 2)
        leases = worker.plan([too_large, small], self.ctx)
        self.assertNotIn(too_large.id, leases)
        self.assertEqual(leases[small.id]["row"], 200)
        self.assertEqual(leases[small.id]["costumes"], [{"row": 203, "sprite": 203}])

    def test_installed_disabled_rows_and_sprite_files_are_reserved(self):
        self.installed_mod("Unrelated_Disabled", [{"id": 200, "sprite_id": 800}],
                           files=["anm00204.lzs"])
        lease = worker.plan([entry(1)], self.ctx)["drpg:1"]
        self.assertNotIn(lease["row"], {200, 202, 203, 204})
        self.assertNotIn(204, {lease["sprite"], lease["sprite"] + 1,
                               lease["sprite"] + 2})

    def test_no_installed_pack_is_listed_unless_the_reference_is_explicit(self):
        class Boom:
            def iterdir(self):
                raise AssertionError('the installed mods folder was listed')
        self.ctx["installed_root"] = Boom()
        self.ctx["installed_reference"] = False
        leases = worker.plan([entry(1, 2), entry(2)], self.ctx)
        self.assertEqual(set(leases), {"drpg:1", "drpg:2"})

    def test_zed_reuses_retiring_mod_lease_and_adds_only_missing_costume(self):
        self.installed_mod("Zed", [{"id": 100, "sprite_id": 13000}])
        leases = worker.plan([entry(94, 2, "DRPG_Core_Zed_94"), entry(1)], self.ctx)
        zed = leases["drpg:94"]
        self.assertEqual((zed["row"], zed["sprite"]), (100, 13000))
        self.assertEqual(zed["costumes"], [{"row": 200, "sprite": 200}])
        self.assertNotEqual(leases["drpg:1"]["row"], 200)

    def test_replacement_keeps_existing_costume_rows_and_sprites(self):
        self.installed_mod("Mod_1", [{"id": 100, "sprite_id": 13000},
                                      {"id": 103, "sprite_id": 13003}], pairs=[(100, 103)])
        self.pool.return_value = []
        lease = worker.plan([entry(1, 2)], self.ctx)["drpg:1"]
        self.assertEqual(lease["costumes"], [{"row": 103, "sprite": 13003}])

    def test_reader_failure_releases_gamefs(self):
        self.pool.side_effect = ValueError("synthetic reader failure")
        with self.assertRaisesRegex(ValueError, "synthetic reader failure"):
            worker.plan([entry(1)], self.ctx)
        self.fs.reset.assert_called_once()


class NamespaceTests(TemporaryTree):
    def setUp(self):
        super().setUp()
        self.help = Table([{"id": 4000, "char_id": 4002}])
        self.quests = Table([{"id": 1, "sort_order": 0},
                             {"id": 1490, "sort_order": 1}])
        self.fs = Mock()
        self.reader = patch.object(namespaces.database, "load_table", side_effect=
            lambda name, raw: self.help if name == "charhelp.dat" else self.quests)
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def mod_patch(self, name, table, doc):
        folder = self.root / name
        folder.mkdir(exist_ok=True)
        (folder / "mod.json").write_text("{}")
        path = folder / "patches/db" / (table + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def test_leases_are_unique_against_vanilla_and_disabled_mod_claims(self):
        self.mod_patch("Disabled", "charhelp.dat", {"added": [{"id": 4001, "char_id": 4003}]})
        self.mod_patch("Disabled", "Quest.dat", {"added": [{"id": 2, "sort_order": 1}]})
        result = namespaces.reserve({"a": {}, "b": {}}, self.fs, self.root)
        self.assertEqual(result["a"], {"help_id": 4004, "quest_id": 3, "quest_slot": 2})
        self.assertEqual(result["b"], {"help_id": 4005, "quest_id": 4, "quest_slot": 3})

    def test_placeholder_vanilla_rows_do_not_claim_progress_slots(self):
        result = namespaces.reserve({"a": {}}, self.fs, self.root)
        self.assertEqual(result["a"]["quest_slot"], 1)

    def test_partial_index_and_key_edits_and_insertions_reserve_claims(self):
        self.mod_patch("Indexed", "Quest.dat", {"rows": {"0": {"sort_order": 1}},
            "insert": [{"before": 1, "rows": [{"id": 2, "sort_order": 2}]}]})
        self.mod_patch("Keyed", "charhelp.dat", {"key": "id", "rows": {"4000": {"char_id": 4001}}})
        result = namespaces.reserve({"a": {}}, self.fs, self.root)["a"]
        self.assertEqual(result, {"help_id": 4003, "quest_id": 3, "quest_slot": 3})

    def test_progress_exhaustion_is_actionable_and_does_not_mutate_tables(self):
        self.quests.rows = [{"id": 9501, "sort_order": n} for n in range(1024)]
        before = copy.deepcopy(self.quests.rows)
        with self.assertRaisesRegex(ValueError, "quest progress slots below 1024 exhausted"):
            namespaces.reserve({"a": {}}, self.fs, self.root)
        self.assertEqual(self.quests.rows, before)

    def test_shop_id_exhaustion_does_not_emit_non_shop_quest_id(self):
        self.quests.rows = [{"id": n, "sort_order": 0} for n in range(1, 1490)]
        with self.assertRaisesRegex(ValueError, "recruitment quest ids below 1490 exhausted"):
            namespaces.reserve({"a": {}}, self.fs, self.root)


class SyntheticBank:
    def __init__(self, uid, animations):
        self.blocks = [SimpleNamespace(id=uid, animations=[SimpleNamespace(id=n) for n in animations])]

    def to_bytes(self):
        return json.dumps({"id": self.blocks[0].id,
                           "animations": [a.id for a in self.blocks[0].animations]}).encode()


class EvilityNamespaceTests(TemporaryTree):
    def setUp(self):
        super().setUp()
        self.table = Table([{"id": 7000}, {"id": 42}])
        self.fs = Mock()
        self.reader = patch.object(namespaces.database, "load_table", return_value=self.table)
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def mod_patch(self, category, filename, doc):
        folder = self.root / "Disabled"
        folder.mkdir(exist_ok=True)
        (folder / "mod.json").write_text("{}")
        path = folder / "patches" / category / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def test_sample_leases_avoid_vanilla_database_runtime_and_alias_claims(self):
        self.mod_patch("db", "Skill.dat.json", {"added": [{"id": 7001}],
            "rows": {"1": {"id": 7002}},
            "insert": [{"before": 42, "rows": [{"id": 7003}]}]})
        self.mod_patch("evilities", "evilities.json", {"evilities": {"7004": {}}})
        self.mod_patch("evilities", "aliases.json", {"7005": 42})
        result = namespaces.reserve_evilities({"drpg:55": {}, "drpg:106": {},
                                               "drpg:311": {}, "drpg:94": {}}, self.fs, self.root)
        self.assertEqual(result, {"drpg:55": {7120: 7006, 7121: 7007},
                                  "drpg:106": {7100: 7008}, "drpg:311": {7110: 7009}})

    def test_only_allocated_sample_bases_receive_evility_leases(self):
        result = namespaces.reserve_evilities({"drpg:106": {}, "drpg:94": {}}, self.fs, self.root)
        self.assertEqual(result, {"drpg:106": {7100: 7001}})

    def test_no_samples_does_not_read_tables(self):
        self.assertEqual(namespaces.reserve_evilities({"drpg:94": {}}, self.fs, self.root), {})
        self.fs.read.assert_not_called()

    def test_band_exhaustion_fails_without_mutating_tables(self):
        self.table.rows = [{"id": n} for n in range(7000, 8000)]
        before = copy.deepcopy(self.table.rows)
        with self.assertRaisesRegex(ValueError, "own evility ids 7000..7999 exhausted"):
            namespaces.reserve_evilities({"drpg:55": {}}, self.fs, self.root)
        self.assertEqual(self.table.rows, before)

    def test_actual_installed_claims_are_avoided_without_loading_game_archives(self):
        installed = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/D5ModKit/mods")
        if not installed.is_dir():
            self.skipTest("private installed mod definitions are not present")
        # Independently collect explicit claims from actual installed definitions;
        # synthetic vanilla Skill rows keep this check archive-free and read-only.
        occupied = {7000}
        for path in installed.glob("*/patches/db/Skill.dat.json"):
            doc = json.loads(path.read_text())
            for row in list(doc.get("added") or []) + list((doc.get("rows") or {}).values()):
                if "id" in row:
                    occupied.add(int(row["id"]))
        for path in installed.glob("*/patches/evilities/evilities.json"):
            occupied.update(int(k) for k in json.loads(path.read_text()).get("evilities", {}))
        for path in installed.glob("*/patches/evilities/aliases.json"):
            occupied.update(int(k) for k in json.loads(path.read_text()))
        leases = namespaces.reserve_evilities({"drpg:55": {}, "drpg:106": {}, "drpg:311": {}}, self.fs, installed)
        new_ids = [n for remap in leases.values() for n in remap.values()]
        self.assertEqual(len(set(new_ids)), 4)
        self.assertFalse(set(new_ids) & occupied)
        self.assertTrue(all(7000 <= n < 8000 for n in new_ids))


class WorkerLifecycleTests(TemporaryTree):
    def setUp(self):
        super().setUp()
        self.output = self.root / "output"
        self.job = self.output / "jobs/one"
        self.subject = entry(1)
        self.ctx = {"output_root": self.output, "source_root": self.root / "source",
                    "game_path": self.root / "game", "installed_root": self.root / "installed"}
        self.importer = drpg.Importer()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.roster = self.stack.enter_context(patch.object(self.importer, "roster", return_value=[self.subject]))
        self.plan = self.stack.enter_context(patch.object(worker, "plan", return_value={self.subject.id: {"row": 231}}))
        self.process = self.stack.enter_context(patch.object(drpg.subprocess, "run"))

    def stale_job(self):
        previous = self.job / "native-mods" / self.subject.mod_folder
        previous.mkdir(parents=True)
        (previous / "obsolete-costume.json").write_text("stale")
        drpg.record_created(previous)          # what the earlier run of this importer recorded
        (self.job / "receipt.json").write_text(json.dumps({
            "ok": True, "gates": {"old": True}, "features": {}, "notes": []}))
        sibling = self.job / "native-mods/OtherMod/keep.txt"
        sibling.parent.mkdir()
        sibling.write_text("keep")
        return previous, sibling

    def test_repeat_build_resets_only_its_pack_and_reads_new_worker_receipt(self):
        previous, sibling = self.stale_job()
        def worker_run(*args, **kwargs):
            self.assertFalse(previous.exists())
            self.assertFalse((self.job / "receipt.json").exists())
            self.assertEqual(sibling.read_text(), "keep")
            previous.mkdir()
            (previous / "fresh.txt").write_text("fresh")
            (self.job / "receipt.json").write_text(json.dumps({
                "ok": True, "gates": {"new": True}, "features": {}, "notes": []}))
            return SimpleNamespace(returncode=0)
        self.process.side_effect = worker_run
        result = self.importer.build(self.subject, self.job, self.ctx)
        self.assertTrue(result.built)
        self.assertEqual(result.gates, {"new": True})
        self.assertFalse((previous / "obsolete-costume.json").exists())
        self.assertEqual(sibling.read_text(), "keep")

    def test_a_pack_folder_this_importer_did_not_create_is_refused_untouched(self):
        foreign = self.job / "native-mods" / self.subject.mod_folder
        foreign.mkdir(parents=True)
        (foreign / "mine.txt").write_text("keep")
        result = self.importer.build(self.subject, self.job, self.ctx)
        self.assertFalse(result.built)
        self.assertIn("not created by this importer", result.error)
        self.assertEqual((foreign / "mine.txt").read_text(), "keep")
        self.process.assert_not_called()

    def test_failing_worker_cannot_reuse_previous_success_receipt(self):
        previous, sibling = self.stale_job()
        self.process.return_value = SimpleNamespace(returncode=7)
        result = self.importer.build(self.subject, self.job, self.ctx)
        self.assertFalse(result.built)
        self.assertIn("worker rc=7", result.error)
        self.assertFalse((self.job / "receipt.json").exists())
        self.assertFalse(previous.exists())
        self.assertEqual(sibling.read_text(), "keep")

    def test_unallocated_group_fails_before_worker_with_design_reference(self):
        self.plan.return_value = {}
        result = self.importer.build(self.subject, self.job, self.ctx)
        self.assertFalse(result.built)
        self.assertIn('CORERPG2-REPORT.md', result.error)
        self.process.assert_not_called()

    def test_protected_outputs_and_job_outside_output_are_rejected_before_mutation(self):
        for key in ("source_root", "game_path", "installed_root"):
            for relationship in ("equal", "inside", "ancestor"):
                with self.subTest(key=key, relationship=relationship):
                    protected = self.ctx[key]
                    candidate = protected if relationship == "equal" else (
                        protected / "nested" if relationship == "inside" else self.root)
                    job = candidate / "job"
                    job.mkdir(parents=True, exist_ok=True)
                    marker = job / "receipt.json"
                    marker.write_text("do not mutate")
                    ctx = dict(self.ctx, output_root=candidate)
                    result = self.importer.build(self.subject, job, ctx)
                    self.assertFalse(result.built)
                    self.assertIn("Unsafe output", result.error)
                    self.assertEqual(marker.read_text(), "do not mutate")
        outside_job = self.root / "outside-job"
        result = self.importer.build(self.subject, outside_job, self.ctx)
        self.assertIn("Unsafe output", result.error)
        self.assertFalse(outside_job.exists())
        self.plan.assert_not_called()
        self.roster.assert_not_called()
        self.process.assert_not_called()


class PoseReferenceTests(TemporaryTree):
    """The pose reference is a kit file pinned by SHA-256 (the real pin is replaced by the synthetic file's here)."""

    def setUp(self):
        super().setUp()
        self.primary = self.root / "checkout/d5lib/data/drpg_ref_humanoid.pickle"
        self.installed_mods = self.root / "installed-kit/mods"
        self.installed_mods.mkdir(parents=True)
        self.fallback = self.installed_mods.parent / "d5lib/data/drpg_ref_humanoid.pickle"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(reference.drpg, "REF_PATH", str(self.primary)))
        self.stack.enter_context(patch.object(reference.drpg, "load_reference", reference.drpg.load_reference))

    def cache(self, path, label, pin=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"synthetic-reference": label}
        path.write_bytes(pickle.dumps(payload))
        if pin:
            self.stack.enter_context(patch.object(reference, "pin", return_value=dict(
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size)))
        return payload

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def test_the_kit_file_is_used_and_pinned_by_a_label_not_a_machine_path(self):
        payload = self.cache(self.primary, "checkout")
        before = self.snapshot()
        pins = reference.configure(None)
        self.assertEqual(pins, {})
        self.assertEqual(reference.drpg.load_reference(), payload)
        self.assertEqual(pins, {reference.LABEL: {
            "path": reference.LABEL, "sha256": hashlib.sha256(self.primary.read_bytes()).hexdigest(),
            "provenance": "Kit learned pose-reference cache"}})
        self.assertEqual(self.snapshot(), before)

    def test_the_installed_kit_copy_is_never_read_by_default(self):
        self.cache(self.fallback, "installed")
        pins = reference.configure(None)
        with self.assertRaisesRegex(FileNotFoundError, "put the upstream release file"):
            reference.drpg.load_reference()
        self.assertEqual(pins, {})

    def test_the_installed_kit_copy_is_an_explicit_opt_in_fallback(self):
        payload = self.cache(self.fallback, "installed")
        pins = reference.configure(self.installed_mods)
        self.assertEqual(reference.drpg.load_reference(), payload)
        self.assertEqual(set(pins), {reference.LABEL})
        self.assertFalse(self.primary.exists(), "fallback must never be copied into the checkout")

    def test_checkout_reference_takes_priority_over_the_explicit_fallback(self):
        payload = self.cache(self.primary, "checkout")
        pickle_path = self.fallback
        pickle_path.parent.mkdir(parents=True)
        pickle_path.write_bytes(pickle.dumps({"synthetic-reference": "installed"}))
        reference.configure(self.installed_mods)
        self.assertEqual(reference.drpg.load_reference(), payload)

    def test_a_file_that_is_not_the_pinned_one_is_never_unpickled(self):
        self.cache(self.primary, "checkout")
        self.primary.write_bytes(pickle.dumps({"synthetic-reference": "swapped"}))
        reference.configure(None)
        with self.assertRaisesRegex(FileNotFoundError, "not the pinned DRPG pose reference"):
            reference.drpg.load_reference()

    def test_missing_reference_gives_actionable_error_without_writes(self):
        before = self.snapshot()
        pins = reference.configure(self.installed_mods)
        with self.assertRaisesRegex(FileNotFoundError, "put the upstream release file"):
            reference.drpg.load_reference()
        self.assertEqual(pins, {})
        self.assertEqual(self.snapshot(), before)

    def test_missing_explicit_path_does_not_silently_use_installed_cache(self):
        self.cache(self.fallback, "installed")
        pins = reference.configure(self.installed_mods)
        with self.assertRaises(FileNotFoundError):
            reference.drpg.load_reference(self.root / "missing.pickle")
        self.assertEqual(pins, {})


class MonsterSupportTests(unittest.TestCase):
    def setUp(self):
        from d5lib import script
        self.sprite = 231
        self.donor = 2010
        # Include adjacent donor ranks so a generic ten-rank helper could leak
        # neighbor roots; the importer must select exactly the unique's 3 roots.
        self.event_ids = [base + self.donor + rank
                          for base in monsters.newclasses.MONSTER_SCRIPTS for rank in (0, 1)]
        self.raw = script.ScriptFile.assemble("".join(
            f"event {eid}\n    wait_children\n" for eid in self.event_ids)).to_bytes()
        self.bank = SyntheticBank(self.sprite, [1, 7, 11, 17, 31, 37])
        self.donor_companion = SyntheticBank(self.donor + 1, [1, 7, 11, 17])
        self.mod = Mock()
        self.mod.read_file.return_value = b"synthetic bank"
        self.mod.load_patch.return_value = {"events": {"777": "event 777\n    wait_children\n"}}
        self.fs = Mock()
        self.fs.read.side_effect = lambda path: self.raw if path == monsters.scriptpatch.SCRIPT else b"donor companion"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(monsters.anm, "load", return_value=self.bank))
        self.stack.enter_context(patch.object(monsters.anm, "parse", return_value=self.donor_companion))
        self.stack.enter_context(patch.object(worker.sprites, "sprite_vpath", return_value="donor companion path"))

    def test_unique_has_exactly_three_normal_skip_roots_without_rank_neighbors(self):
        roots = monsters.support(self.fs, self.mod, self.sprite, self.donor)
        expected = {base + self.sprite for base in monsters.newclasses.MONSTER_SCRIPTS}
        self.assertEqual(set(roots), expected)
        kind, filename, patch_doc = self.mod.save_patch.call_args.args
        self.assertEqual((kind, filename), ("script", "script.json"))
        self.assertEqual(set(patch_doc["events"]), {str(n) for n in expected} | {"777"})
        for event_id in expected:
            event = monsters.scriptpatch.parse_event_text(patch_doc["events"][str(event_id)])
            self.assertEqual(event.id, event_id)
        self.assertEqual([e.id for e in monsters.script.ScriptFile.from_bytes(self.raw).events], self.event_ids)

    def test_companion_uses_only_donor_companion_animations_and_keeps_base_full(self):
        monsters.support(self.fs, self.mod, self.sprite, self.donor)
        path, payload = self.mod.write_file.call_args.args
        self.assertEqual(path, "Anime/ANM_HI_JP.dat/anm00232.lzs")
        companion = json.loads(payload)
        self.assertEqual(companion, {"id": 232, "animations": [1, 7, 11, 17]})
        self.assertEqual([a.id for a in self.bank.blocks[0].animations], [1, 7, 11, 17, 31, 37])
        self.assertEqual(self.bank.blocks[0].id, 231)

    def test_missing_one_attack_root_fails_instead_of_claiming_support(self):
        self.raw = monsters.script.ScriptFile.assemble(
            f"event {self.event_ids[0]}\n    wait_children\n").to_bytes()
        with self.assertRaisesRegex(ValueError, "lacks normal/skip attack scripts"):
            monsters.support(self.fs, self.mod, self.sprite, self.donor)
        self.mod.save_patch.assert_not_called()

    def test_missing_donor_companion_fails_instead_of_emitting_full_copy(self):
        self.fs.read.side_effect = KeyError("missing donor companion")
        with self.assertRaises(KeyError):
            monsters.support(self.fs, self.mod, self.sprite, self.donor)
        self.mod.write_file.assert_not_called()
        self.mod.save_patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
