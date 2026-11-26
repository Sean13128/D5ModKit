"""D4-FIX5: the importer's Magichange pass emits the leased ids for u190 and refuses a drift."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from d5lib.importers import d4
from d5lib.importers._d4_source import TextPool
from tools import magichange_rows

HELD = Path("/Volumes/Data/Projects/D5/Local/mods-holding/20261108-PLAYTEST-RESET/mods/D4_Unique_190")
MOD = "D4_Unique_190"

# the lease names its pinned rows as game-text references; this test resolves the three it pins
NAMES = TextPool(["Twin Rocket Punch", "Sonic Fire", "Twin Twin Rocket Punch"])


@unittest.skipUnless(HELD.is_dir() and Path(magichange_rows.DEFAULT_DB).is_file(), "held pack / vanilla table absent")
class MagichangePass(unittest.TestCase):
    def built(self):
        """the held u190 with the Magichange rows and learn slots taken out = what the builder leaves"""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        built = tmp / MOD
        (built / "patches/db").mkdir(parents=True)
        mg = json.loads((HELD / "patches/db/magic.dat.json").read_text())
        mg["added"] = [r for r in mg["added"] if int(r["id"]) not in (20234, 20235, 20236)]
        (built / "patches/db/magic.dat.json").write_text(json.dumps(mg))
        ch = json.loads((HELD / "patches/db/char.dat.json").read_text())
        row = ch["added"][0]
        for k in (4, 5, 6):
            row[f"learn{k}_skill"], row[f"learn{k}_level"] = 0, 0
        row["learn_count"] = 3
        (built / "patches/db/char.dat.json").write_text(json.dumps(ch))
        (built / "mod.json").write_text("{}")
        return built

    def lease(self, **change):
        _doc, leases = d4.load_leases()
        want = [dict(r) for r in leases[MOD]["magichange"]]
        want[0].update(change)
        return {"magichange": want}

    def test_pinned_ids(self):
        built = self.built()
        d4.Importer._magichange_pass(SimpleNamespace(mod_folder=MOD), built, pool=NAMES)
        mg = {int(r["id"]): r["name_EN"] for r in json.loads((built / "patches/db/magic.dat.json").read_text())["added"]}
        self.assertEqual([mg[i] for i in (20234, 20235, 20236)],
                         ["Twin Rocket Punch", "Sonic Fire", "Twin Twin Rocket Punch"])
        row = json.loads((built / "patches/db/char.dat.json").read_text())["added"][0]
        self.assertEqual([(row[f"learn{k}_skill"], row[f"learn{k}_level"]) for k in (4, 5, 6)],
                         [(20234, 30), (20235, 70), (20236, 1)])

    def test_drift_refused(self):
        for change in (dict(name="Other Name"), dict(level=31), dict(d5_id=20299)):
            with self.assertRaises(Exception, msg=str(change)):
                d4.Importer._magichange_pass(SimpleNamespace(mod_folder=MOD), self.built(), lease=self.lease(**change), pool=NAMES)

    def test_missing_row_is_regression(self):
        from d5lib import importcore
        built = self.built()                       # the builder's output without the pass: rows absent
        imp = d4.Importer()
        entry = SimpleNamespace(mod_folder=MOD, kind="unique", source_ref={"row": 190})
        verdict, why = importcore.classify(([], [], ["patches/db/magic.dat.json"]), entry,
                                           imp.compare_reason, None, dirs=(built, HELD))
        self.assertEqual(verdict, "regression")
        self.assertIn("20234", why)
        d4.Importer._magichange_pass(entry, built, pool=NAMES)
        self.assertEqual(imp._magichange_lost(entry, (built, HELD)), "")


if __name__ == "__main__":
    unittest.main()
