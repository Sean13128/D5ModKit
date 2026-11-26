"""tools/accept_packed_mastery.py: the acknowledgement a packed install requires, and nothing else."""
import importlib.util
import json
import os
import tempfile
import unittest

from d5lib import masteryext

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "accept_packed_mastery.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("accept_packed_mastery", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AcceptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, masteryext.LEASE_FILE)
        self.tool = load_tool()

    def lease(self, mapping):
        leases = masteryext.SlotLeases.load(self.path, log=lambda *_: None)
        leases.assign(mapping)
        leases.save()
        return leases

    def test_acknowledges_every_lease_and_verifies_the_write(self):
        self.lease([1350, 1360])
        self.assertEqual(self.tool.main(["--state-dir", self.tmp.name, "--json"]), 0)
        again = masteryext.SlotLeases.load(self.path, log=lambda *_: None)
        self.assertEqual(again.packed_ack["families"], [1350, 1360])
        self.assertEqual(again.slots, {1350: 47, 1360: 48})          # the mapping itself is unchanged
        record = json.load(open(self.path))
        self.assertEqual(record["slots"], {"1350": 47, "1360": 48})   # still a version-1 lease file
        self.assertEqual(record["version"], masteryext.LEASE_VERSION)

    def test_records_a_retired_family_too(self):
        leases = self.lease([1350, 1360])
        leases.assign([1360])                                          # 1350 retires, keeps slot 47
        leases.save()
        self.assertEqual(self.tool.main(["--state-dir", self.tmp.name]), 0)
        again = masteryext.SlotLeases.load(self.path, log=lambda *_: None)
        self.assertEqual(again.packed_ack["families"], [1350, 1360])

    def test_dry_run_writes_nothing(self):
        self.lease([1350])
        before = open(self.path, "rb").read()
        self.assertEqual(self.tool.main(["--state-dir", self.tmp.name, "--dry-run"]), 0)
        self.assertEqual(open(self.path, "rb").read(), before)

    def test_an_unknown_family_is_refused(self):
        self.lease([1350])
        with self.assertRaises(SystemExit):
            self.tool.main(["--state-dir", self.tmp.name, "--families", "9999"])

    def test_no_lease_file_is_not_created(self):
        with self.assertRaises(SystemExit) as caught:
            self.tool.main(["--state-dir", self.tmp.name])
        self.assertIn("nothing to acknowledge", str(caught.exception))
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
