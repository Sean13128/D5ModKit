"""Asset-free per-game catalogue and native pack integration tests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from d5lib import modinfo, modsys


def catalogue():
    return {
        "schema": 1, "id": "fixture-catalogue", "name": "Fixture catalogue",
        "games": [{"id": "fixture-a", "name": "Fixture game A"},
                  {"id": "fixture-b", "name": "Fixture game B"}],
        "entries": [{
            "id": "fixture-a:hero", "game": "fixture-a", "name": "Fixture hero",
            "category": "characters", "status": "catalogue",
            "source": {"edition": "asset-free-fixture", "identity": "hero-variant-a",
                       "provenance": [{"kind": "test", "reference": "authored fixture, not game data"}]},
            "fidelity": {"mode": "unknown", "missing_mappings": ["all source data"], "adaptations": []},
            "requires": [], "conflicts": [],
        }],
    }


class CatalogueTests(unittest.TestCase):
    def test_validates_source_neutral_catalogue_without_mutation(self):
        from d5lib import gamepacks
        doc = catalogue()
        original = copy.deepcopy(doc)
        self.assertEqual(gamepacks.CATEGORIES, ("characters", "humanoid_classes", "monsters"))
        validated = gamepacks.validate_catalogue(doc)
        self.assertEqual(validated, original)
        validated["entries"][0]["source"]["edition"] = "changed"
        self.assertEqual(doc, original)
        for key, value in (("category", "classes"), ("status", "built"), ("game", "absent")):
            bad = copy.deepcopy(doc)
            bad["entries"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                gamepacks.validate_catalogue(bad)
        bad = copy.deepcopy(doc)
        bad["entries"][0]["status"] = "build-ready"
        with self.assertRaisesRegex(ValueError, "artifact"):
            gamepacks.validate_catalogue(bad)


    def test_catalogue_can_verify_all_claimed_ready_children_explicitly(self):
        from d5lib import gamepacks
        doc = catalogue()
        ready = doc["entries"][0]
        ready.update(status="build-ready", artifact={"mod_id": "hero", "required_payload": ["files/fixture/hero.txt"]})
        with self.assertRaisesRegex(ValueError, "artifact child"):
            gamepacks.validate_catalogue(doc, artifacts={})

    def test_rejects_duplicate_ids_source_identity_and_missing_provenance(self):
        from d5lib import gamepacks
        doc = catalogue()
        for mutation in ("id", "identity", "provenance", "dependency", "category", "unsafe-payload"):
            bad = copy.deepcopy(doc)
            e = bad["entries"][0]
            if mutation in ("id", "identity"):
                duplicate = copy.deepcopy(e)
                if mutation == "identity":
                    duplicate["id"] = "another-entry"
                bad["entries"].append(duplicate)
            elif mutation == "provenance":
                e["source"]["provenance"] = []
            elif mutation == "dependency":
                e["requires"] = ["not-a-real-entry"]
            elif mutation == "category":
                e["category"] = "imagined"
            else:
                e.update(status="build-ready", artifact={"mod_id": "hero", "required_payload": ["files/../outside"]})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                gamepacks.validate_catalogue(bad)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gamepacks-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.doc = catalogue()
        self.artifacts = {}
        base = copy.deepcopy(self.doc["entries"][0])
        self.doc["entries"] = []
        for key, category in (("hero", "characters"), ("human", "humanoid_classes"), ("monster", "monsters")):
            e = copy.deepcopy(base)
            e.update(id=f"fixture-a:{key}", category=category, status="build-ready")
            e["source"]["identity"] = key
            e["artifact"] = {"mod_id": key, "required_payload": [f"files/fixture/{key}.txt"]}
            self.doc["entries"].append(e)
            self.native_mod(key, requires=["shared"])
        self.native_mod("shared")
        self.doc["entries"].append(dict(copy.deepcopy(base), id="fixture-b:unbuilt", game="fixture-b"))

    def native_mod(self, key, requires=()):
        m = modsys.Mod(str(self.root / "source" / key))
        m.meta.update(name=f"Fixture {key}", uid=f"fixture-uid-{key}", requires=list(requires))
        m.save_meta()
        m.write_file(f"fixture/{key}.txt", f"authored fixture {key}".encode())
        self.artifacts[key] = m
        return m

    def resolve(self, **kwargs):
        from d5lib import gamepacks
        return gamepacks.resolve_selection(self.doc, artifacts=self.artifacts, **kwargs)

    def test_game_category_entry_toggles_and_native_dependency_dedupe(self):
        from d5lib import gamepacks
        plan = self.resolve(games=["fixture-a"], categories=["monsters", "characters"])
        self.assertEqual(plan.entry_ids, ("fixture-a:hero", "fixture-a:monster"))
        self.assertEqual(plan.mod_ids, ("shared", "hero", "monster"))
        self.assertEqual(plan.catalogue_only, ())
        self.assertEqual(modsys.missing_requirements([self.artifacts[x] for x in plan.mod_ids]), [])
        self.assertEqual(plan, self.resolve(entries=["fixture-a:monster", "fixture-a:hero", "fixture-a:hero"]))
        self.assertEqual(self.resolve(games=["fixture-a"], categories=[]).entry_ids, ())
        self.assertEqual(self.resolve(games=["fixture-a"], exclude_entries=["fixture-a:human"]).entry_ids,
                         ("fixture-a:hero", "fixture-a:monster"))
        unbuilt = self.resolve(games=["fixture-b"])
        self.assertEqual(unbuilt.entry_ids, ())
        self.assertEqual(unbuilt.catalogue_only, ("fixture-b:unbuilt",))
        self.assertEqual(self.resolve().mod_ids, ())
        for kwargs in ({"games": ["typo"]}, {"categories": ["classes"]}, {"entries": ["absent"]},
                       {"exclude_entries": ["absent"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.resolve(**kwargs)
        # An entry-level dependency is included even when the bulk category is filtered out.
        self.doc["entries"][0]["requires"] = ["fixture-a:human"]
        self.assertEqual(self.resolve(entries=["fixture-a:hero"]).entry_ids,
                         ("fixture-a:human", "fixture-a:hero"))
        with self.assertRaisesRegex(ValueError, "excluded"):
            self.resolve(entries=["fixture-a:hero"], exclude_entries=["fixture-a:human"])


    def test_materializes_native_groups_metadata_and_profile_readback(self):
        from d5lib import gamepacks, savegame
        self.artifacts["hero"].meta["category"] = ""
        self.artifacts["hero"].save_meta()
        plan = self.resolve(games=["fixture-a", "fixture-b"])
        destination = self.root / "staged-kit"
        result = gamepacks.materialize(self.doc, plan, artifacts=self.artifacts, staging_path=destination)
        self.assertEqual(result, destination)
        mm = modsys.ModManager(str(destination))
        self.assertEqual(tuple(m.id for m in mm.enabled_mods()), plan.mod_ids)
        self.assertEqual(modsys.missing_requirements(mm.enabled_mods()), [])
        packs = modinfo.Packs(str(destination / "mods"))
        self.assertEqual(len(packs.packs), 1)
        self.assertEqual(set(packs.packs[0]["members"]), {"hero", "human", "monster"})
        self.assertIsNone(packs.pack_of("shared"))
        self.assertEqual(packs.pack_of("hero")["game"], "fixture-a")
        for key, category in (("hero", "characters"), ("human", "classes"), ("monster", "classes")):
            mod = mm.get(key)
            self.assertEqual(modinfo.category(mod), category)
            self.assertEqual(mod.meta["uid"], f"fixture-uid-{key}")
            self.assertEqual(mod.meta["requires"], ["shared"])
            recorded = mod.meta["gamepack"]["entries"][0]
            self.assertEqual(recorded["source"]["edition"], "asset-free-fixture")
            self.assertEqual(recorded["fidelity"]["missing_mappings"], ["all source data"])
            self.assertNotIn("gamepack", self.artifacts[key].meta)
            self.assertEqual(mod.read_file(f"fixture/{key}.txt"), self.artifacts[key].read_file(f"fixture/{key}.txt"))
            self.assertEqual(savegame.mod_characters(mod), {"classes": {}, "outfits": {}, "quests": {}})
        receipt = json.loads((destination / "gamepacks.json").read_text())
        self.assertEqual(receipt["built_entries"], list(plan.entry_ids))
        self.assertEqual(receipt["catalogue_only"], ["fixture-b:unbuilt"])
        self.assertEqual(json.loads((destination / "catalogue.json").read_text()), self.doc)
        with self.assertRaises(ValueError):
            gamepacks.materialize(self.doc, plan, artifacts=self.artifacts, staging_path=destination)

    def test_native_conflicts_duplicate_uids_and_fixed_family_collisions_fail(self):
        hero, human = self.artifacts["hero"], self.artifacts["human"]
        hero.meta["conflicts"] = ["human"]
        hero.save_meta()
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.resolve(games=["fixture-a"])
        hero.meta.pop("conflicts")
        hero.meta["uid"] = human.meta["uid"]
        hero.save_meta()
        with self.assertRaisesRegex(ValueError, "uid"):
            self.resolve(games=["fixture-a"])
        hero.meta["uid"] = "fixture-uid-hero"
        hero.save_meta()
        # This is a filename-only collision fixture; no actual family is built/allocated.
        hero.save_patch("classes", "class_1010.json", {"fixture": True})
        human.save_patch("classes", "class_1010.json", {"fixture": True})
        with self.assertRaisesRegex(ValueError, "famil"):
            self.resolve(games=["fixture-a"])


    def test_missing_and_empty_required_payload_and_artifact_child_fail(self):
        from d5lib import gamepacks
        del self.artifacts["hero"]
        with self.assertRaisesRegex(ValueError, "artifact child"):
            self.resolve(entries=["fixture-a:hero"])
        hero = self.native_mod("hero")
        path = Path(hero.file_path("fixture/hero.txt"))
        path.unlink()
        with self.assertRaisesRegex(ValueError, "required payload"):
            self.resolve(entries=["fixture-a:hero"])
        path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "required payload"):
            self.resolve(entries=["fixture-a:hero"])
        path.write_text("fixture")
        self.doc["entries"][0]["artifact"]["required_payload"] = ["mod.json"]
        with self.assertRaisesRegex(ValueError, "payload"):
            gamepacks.validate_catalogue(self.doc)

    def test_entry_and_native_dependency_cycles_missing_and_unbuilt_fail(self):
        hero, human = self.doc["entries"][:2]
        hero["requires"] = [human["id"]]
        human["requires"] = [hero["id"]]
        with self.assertRaisesRegex(ValueError, "entry dependency cycle"):
            self.resolve(entries=[hero["id"]])
        human["requires"] = []
        hero["requires"] = ["fixture-b:unbuilt"]
        with self.assertRaisesRegex(ValueError, "catalogue-only"):
            self.resolve(entries=[hero["id"]])
        hero["requires"] = []
        self.artifacts["shared"].meta["requires"] = ["hero"]
        self.artifacts["shared"].save_meta()
        with self.assertRaisesRegex(ValueError, "native mod dependency cycle"):
            self.resolve(entries=[hero["id"]])
        self.artifacts["shared"].meta["requires"] = ["missing"]
        self.artifacts["shared"].save_meta()
        with self.assertRaisesRegex(ValueError, "artifact child"):
            self.resolve(entries=[hero["id"]])
        self.artifacts["shared"].meta["requires"] = []
        self.artifacts["shared"].save_meta()
        human["conflicts"] = [hero["id"]]  # asymmetric declaration still blocks the pair
        with self.assertRaisesRegex(ValueError, "entry conflict"):
            self.resolve(games=["fixture-a"])

    def test_two_native_game_groups_have_stable_ids_not_names(self):
        from d5lib import gamepacks
        e = copy.deepcopy(self.doc["entries"][0])
        e.update(id="fixture-b:other", game="fixture-b")
        e["artifact"] = {"mod_id": "other", "required_payload": ["files/fixture/other.txt"]}
        self.doc["entries"].append(e)
        self.native_mod("other", requires=["shared"])
        first = self.root / "first"
        gamepacks.materialize(self.doc, self.resolve(games=["fixture-a", "fixture-b"]),
                              artifacts=self.artifacts, staging_path=first)
        before = {p["game"]: p["id"] for p in modinfo.Packs(str(first / "mods")).packs}
        self.assertEqual(len(before), 2)
        self.doc["games"][0]["name"] = "Localized game name"
        second = self.root / "second"
        gamepacks.materialize(self.doc, self.resolve(games=["fixture-b", "fixture-a"]),
                              artifacts=self.artifacts, staging_path=second)
        after = {p["game"]: p["id"] for p in modinfo.Packs(str(second / "mods")).packs}
        self.assertEqual(before, after)
        self.assertIsNone(modinfo.Packs(str(second / "mods")).pack_of("shared"))

    def test_symlink_missing_dependency_payload_and_unsafe_targets_fail_without_writes(self):
        from d5lib import gamepacks
        plan = self.resolve(entries=["fixture-a:hero"])
        shared = self.artifacts["shared"]
        Path(shared.file_path("fixture/shared.txt")).unlink()
        with self.assertRaisesRegex(ValueError, "payload"):
            gamepacks.materialize(self.doc, plan, artifacts=self.artifacts, staging_path=self.root / "empty-dep")
        self.assertFalse((self.root / "empty-dep").exists())
        shared.write_file("fixture/shared.txt", b"fixture")
        (Path(shared.folder) / "leak").symlink_to(self.root / "not-read")
        with self.assertRaisesRegex(ValueError, "symlink"):
            gamepacks.materialize(self.doc, plan, artifacts=self.artifacts, staging_path=self.root / "linked-child")
        self.assertFalse((self.root / "linked-child").exists())
        (Path(shared.folder) / "leak").unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            gamepacks.materialize(self.doc, plan, artifacts=self.artifacts, staging_path=alias / "linked-target")
        with self.assertRaisesRegex(ValueError, "overlap"):
            gamepacks.materialize(self.doc, plan, artifacts=self.artifacts,
                                  staging_path=Path(shared.folder) / "nested")
        live = self.root / "fake-live-game"
        live.mkdir()
        (live / "disgaea5.exe").write_bytes(b"authored fixture marker only")
        with self.assertRaisesRegex(ValueError, "live"):
            gamepacks.materialize(self.doc, plan, artifacts=self.artifacts, staging_path=live / "no")
        self.assertFalse((live / "no").exists())

    def test_rejects_partial_native_child_and_misleading_category(self):
        from d5lib import gamepacks
        self.doc["entries"][1]["artifact"] = copy.deepcopy(self.doc["entries"][0]["artifact"])
        with self.assertRaisesRegex(ValueError, "unselected|atomic"):
            self.resolve(entries=["fixture-a:hero"])
        self.doc["entries"][1]["artifact"]["mod_id"] = "human"
        self.doc["entries"][1]["artifact"]["required_payload"] = ["files/fixture/human.txt"]
        self.artifacts["hero"].meta["category"] = "classes"
        self.artifacts["hero"].save_meta()
        with self.assertRaisesRegex(ValueError, "category"):
            self.resolve(entries=["fixture-a:hero"])

    def test_native_save_metadata_and_share_identity_remain_consumable(self):
        from d5lib import gamepacks, modshare, savegame
        hero = self.artifacts["hero"]
        # Existing reserved unique ID, authored rows only; not a playable character claim.
        hero.save_patch("db", "char.dat.json", {"table": "char.dat", "added": [{"id": 470, "name_EN": "Fixture hero"}]})
        hero.save_patch("db", "Quest.dat.json", {"table": "Quest.dat", "added": [
            {"id": 0, "name_EN": "Fixture recruit", "reward_type": 5, "reward_value": 470, "sort_order": 0}]})
        hero.meta["based_on"] = [{"uid": "fixture-original", "name": "Fixture", "version": "1", "author": "Test"}]
        hero.save_meta()
        staged = self.root / "share-and-save"
        gamepacks.materialize(self.doc, self.resolve(entries=["fixture-a:hero"]),
                              artifacts=self.artifacts, staging_path=staged)
        child = modsys.Mod(str(staged / "mods" / "hero"))
        self.assertEqual(savegame.mod_characters(child), {
            "classes": {470: "Fixture hero"}, "outfits": {}, "quests": {0: "Fixture recruit"}})
        exported = str(self.root / "fixture.zip")
        modshare.export_package(child, exported)
        top, meta = modshare.read_package(exported)
        self.assertEqual(top, "hero")
        self.assertEqual(meta["uid"], hero.meta["uid"])
        self.assertEqual(meta["based_on"], hero.meta["based_on"])
        self.assertEqual(meta["gamepack"]["entries"][0]["id"], "fixture-a:hero")
        # Remapped metadata must survive staging; existing native share guard still refuses re-export.
        hero.meta["local_ids"] = {"class": {"470": 480}}
        hero.save_meta()
        second = self.root / "remapped"
        gamepacks.materialize(self.doc, self.resolve(entries=["fixture-a:hero"]),
                              artifacts=self.artifacts, staging_path=second)
        remapped = modsys.Mod(str(second / "mods" / "hero"))
        self.assertEqual(remapped.meta["local_ids"], hero.meta["local_ids"])
        with self.assertRaisesRegex(ValueError, "moved"):
            modshare.export_package(remapped, str(self.root / "must-not-export.zip"))


    def test_duplicate_native_requires_are_deduplicated_in_load_order(self):
        hero = self.artifacts["hero"]
        hero.meta["requires"] = ["shared", "shared"]
        hero.save_meta()
        plan = self.resolve(entries=["fixture-a:hero"])
        self.assertEqual(plan.mod_ids, ("shared", "hero"))

    def test_rejects_unsafe_native_dependency_ids_and_source_aliases(self):
        shared = self.artifacts["shared"]
        hero = self.artifacts["hero"]
        hero.meta["requires"] = [".."]
        hero.save_meta()
        # Point directly at an explicit parent folder; no traversal should be accepted.
        parent = self.root / "source" / ".."
        (self.root / "mod.json").write_text('{"name":"parent fixture"}')
        self.artifacts[".."] = parent
        with self.assertRaisesRegex(ValueError, "native mod id"):
            self.resolve(entries=["fixture-a:hero"])
        hero.meta["requires"] = ["shared"]
        hero.save_meta()
        alias = self.root / "alias-source"
        alias.symlink_to(Path(shared.folder).parent, target_is_directory=True)
        self.artifacts["shared"] = alias / "shared"
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.resolve(entries=["fixture-a:hero"])

    def test_selection_canonicalizes_dependency_closure_for_revalidation(self):
        from d5lib import gamepacks
        hero, human, monster = self.doc["entries"][:3]
        monster["requires"] = [human["id"]]
        selected = self.resolve(entries=[hero["id"], monster["id"]])
        closure = self.resolve(entries=list(selected.entry_ids))
        self.assertEqual(selected, closure)
        gamepacks.materialize(self.doc, selected, artifacts=self.artifacts, staging_path=self.root / "canonical")
        altered = gamepacks.Selection(selected.entry_ids, selected.catalogue_only, tuple(reversed(selected.mod_ids)))
        with self.assertRaisesRegex(ValueError, "stale|altered"):
            gamepacks.materialize(self.doc, altered, artifacts=self.artifacts, staging_path=self.root / "altered")
        self.assertFalse((self.root / "altered").exists())


if __name__ == "__main__":
    unittest.main()
