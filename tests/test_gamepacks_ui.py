"""Hidden Qt tests: actual catalogue/resolver/materializer, isolated authored mods."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication


class GamePacksUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gamepacks-ui-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        from d5gui.pages.gamepacks import GamePacksPage
        self.page = GamePacksPage(SimpleNamespace(game_dir=str(self.root / "fake-game")), None)
        self.addCleanup(self.page.close)

    def test_empty_no_workspace_reads_or_seed(self):
        self.assertIsNone(self.page.catalogue)
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertIn("Open", self.page.summary.text())
        self.assertFalse(self.page.build_button.isEnabled())
        from d5gui.app import PAGES
        self.assertIn(("CONTENT", "gamepacks", "📦  Game Content Packs", "gamepacks", "GamePacksPage"), PAGES)

    def fixture(self):
        from test_gamepacks import catalogue
        from d5lib import modsys
        import copy
        doc = catalogue()
        base = doc["entries"][0]
        doc["entries"] = []
        for key, category in (("hero", "characters"), ("human", "humanoid_classes"), ("monster", "monsters")):
            entry = copy.deepcopy(base)
            entry.update(id=f"fixture-a:{key}", name=key, category=category, status="build-ready",
                         artifact={"mod_id": key, "required_payload": [f"files/fixture/{key}.txt"]})
            entry["source"]["identity"] = key
            doc["entries"].append(entry)
            mod = modsys.Mod(str(self.root / "artifacts" / key))
            mod.meta.update(uid=f"test-{key}", requires=["shared"])
            mod.save_meta()
            mod.write_file(f"fixture/{key}.txt", b"authored synthetic fixture")
        doc["entries"].append(dict(copy.deepcopy(base), id="fixture-b:unbuilt", game="fixture-b"))
        shared = modsys.Mod(str(self.root / "artifacts" / "shared"))
        shared.meta.update(uid="test-shared")
        shared.save_meta()
        shared.write_file("fixture/shared.txt", b"authored dependency")
        path = self.root / "catalogue.json"
        path.write_text(json.dumps(doc))
        return path

    def open_fixture(self):
        path = self.fixture()
        with patch("d5gui.pages.gamepacks.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            self.page.open_button.click()
        for key in ("hero", "human", "monster", "shared"):
            with patch("d5gui.pages.gamepacks.QFileDialog.getExistingDirectory", return_value=str(self.root / "artifacts" / key)):
                self.page.artifact_button.click()
        return path

    def test_real_open_filters_overrides_dependencies_and_build_button(self):
        self.open_fixture()
        self.page.game_checks["fixture-a"].click()
        self.assertEqual(self.page.plan.mod_ids, ("shared", "hero", "human", "monster"))
        self.assertTrue(self.page.build_button.isEnabled())
        self.page.category_checks["monsters"].click()
        self.assertNotIn("monster", self.page.plan.mod_ids)
        self.page.overrides["fixture-a:hero"].setCurrentIndex(2)  # exclude
        self.assertEqual(self.page.plan.mod_ids, ("shared", "human"))
        self.page.overrides["fixture-a:hero"].setCurrentIndex(1)  # include
        self.assertIn("hero", self.page.plan.mod_ids)
        self.page.table.selectRow(0)
        self.assertIn("missing_mappings", self.page.details.toPlainText())
        target = self.root / "new-staging"
        with patch("d5gui.pages.gamepacks.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            self.page.build_button.click()
        receipt = json.loads((target / "gamepacks.json").read_text())
        self.assertEqual(receipt["mod_ids"], ["shared", "hero", "human"])
        from d5lib import modsys, modinfo
        staged = modsys.ModManager(str(target))
        self.assertEqual(staged.load_order(), receipt["mod_ids"])
        self.assertEqual(modinfo.Packs(str(target / "mods")).packs[0]["members"], ["hero", "human"])
        self.assertIn("Staged", self.page.result.text())
        self.assertFalse((self.root / "fake-game").exists())
        self.page.clear_button.click()
        self.assertEqual(self.page.plan.entry_ids, ())
        self.assertFalse(self.page.build_button.isEnabled())

    def test_catalogue_only_is_not_buildable_and_missing_artifact_errors(self):
        path = self.fixture()
        self.page.open_catalogue(path)
        self.page.game_checks["fixture-a"].click()
        self.assertIsNone(self.page.plan)
        self.assertIn("artifact", self.page.summary.text())
        self.assertFalse(self.page.build_button.isEnabled())
        self.page.clear_button.click()
        self.page.game_checks["fixture-b"].click()
        self.assertEqual(self.page.plan.catalogue_only, ("fixture-b:unbuilt",))
        self.assertFalse(self.page.build_button.isEnabled())
        self.assertIn("Catalogue-only", self.page.summary.text())

    def test_build_refuses_existing_folder_and_revalidates_changed_payload(self):
        self.open_fixture()
        self.page.game_checks["fixture-a"].click()
        existing = self.root / "existing"
        existing.mkdir()
        (existing / "sentinel").write_text("preserve")
        self.assertFalse(self.page.build_to(existing))
        self.assertEqual((existing / "sentinel").read_text(), "preserve")
        (self.root / "artifacts/hero/files/fixture/hero.txt").unlink()
        target = self.root / "must-not-exist"
        self.assertFalse(self.page.build_to(target))
        self.assertFalse(target.exists())
        self.assertIn("payload", self.page.result.text())

    def test_catalogue_intent_display_and_entry_dependency_exclusion(self):
        self.open_fixture()
        self.page.game_checks["fixture-b"].click()
        self.assertEqual(self.page.table.item(3, 6).text(), "Catalogue-only intent")
        self.assertIn("1 selected", self.page.summary.text())
        self.page.clear_button.click()
        self.page.catalogue["entries"][0]["requires"] = ["fixture-a:human"]
        self.page.overrides["fixture-a:hero"].setCurrentIndex(1)
        self.assertEqual(self.page.plan.mod_ids, ("shared", "hero", "human"))
        self.page.overrides["fixture-a:human"].setCurrentIndex(2)
        self.assertIsNone(self.page.plan)
        self.assertIn("excluded", self.page.summary.text())
        self.assertFalse(self.page.build_button.isEnabled())

    def test_bad_metadata_cancel_and_explicit_artifact_registry_only(self):
        self.open_fixture()
        original = self.page.catalogue
        bad = self.root / "bad.json"
        bad.write_text("not JSON")
        self.assertFalse(self.page.open_catalogue(bad))
        self.assertIs(self.page.catalogue, original)
        alias = self.root / "alias.json"
        alias.symlink_to(self.root / "catalogue.json")
        self.assertFalse(self.page.open_catalogue(alias))
        self.assertIn("Symlink", self.page.result.text())
        with patch("d5gui.pages.gamepacks.QFileDialog.getOpenFileName", return_value=("", "")):
            self.page.open_button.click()
        self.assertIs(self.page.catalogue, original)
        self.page.forget_button.click()
        self.assertEqual(self.page.artifacts, {})
        self.assertFalse(self.page.add_artifact(self.root / "artifacts"))
        self.assertEqual(self.page.artifacts, {})  # must not scan child folders


if __name__ == "__main__":
    unittest.main()
