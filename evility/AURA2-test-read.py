"""Offline-only guard tests. Imports the prepared script without opening a live pipe."""
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('aura2_read', Path(__file__).with_name('AURA2-scripts-read.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Memory:
    def __init__(self, data, *, drop=False):
        self.data = bytearray(data)
        self.drop = drop
        self.writes = []

    def cmd(self, command):
        op, address, value = command.split()
        addr = int(address, 0)
        if op == 'rd':
            return {'hex': self.data[addr:addr + int(value)].hex()}
        assert op == 'wr'
        payload = bytes.fromhex(value)
        self.writes.append((addr, payload))
        if not self.drop:
            self.data[addr:addr + len(payload)] = payload
        return {'ok': True}


def section():
    data = bytearray(16)
    for ev, shape in m.SHAPES.items():
        for mask, nc, nf in shape:
            data += struct.pack('<8I', ev, mask, 0, nc, 0, nf, 0, 0)
    return data


class Guards(unittest.TestCase):
    def test_locate_exact_runs(self):
        rows = m.locate_rows(section(), 0x1000)
        self.assertEqual([len(rows[i]) for i in m.SHAPES], [4, 2, 2, 2])

    def test_missing_run_fails(self):
        with self.assertRaises(AssertionError):
            m.locate_rows(bytes(64), 0)

    def test_ambiguous_runs_fail(self):
        with self.assertRaises(AssertionError):
            m.locate_rows(section() + section(), 0)

    def test_mask_toggle_preserves_id_and_restores_entire_row(self):
        original = struct.pack('<8I', 28304, 66, 32, 1, 16, 4, 0, 0)
        c = Memory(original)
        m.write_row_mask(c, 0, 28304, 66, False)
        self.assertEqual(struct.unpack_from('<II', c.data), (28304, 0))
        m.write_row_mask(c, 0, 28304, 66, True)
        self.assertEqual(c.data, original)
        self.assertEqual([addr for addr, _ in c.writes], [4, 4])

    def test_dropped_mask_write_fails(self):
        c = Memory(struct.pack('<8I', 28304, 66, 0, 1, 0, 4, 0, 0), drop=True)
        with self.assertRaisesRegex(AssertionError, 'write readback'):
            m.write_row_mask(c, 0, 28304, 66, False)

    def test_aura1_corrupted_id_refused_before_write(self):
        c = Memory(struct.pack('<8I', 66, 66, 0, 1, 0, 4, 0, 0))
        with self.assertRaisesRegex(AssertionError, 'row identity'):
            m.write_row_mask(c, 0, 28304, 66, True)
        self.assertEqual(c.writes, [])

    def test_snapshot_gate_passes_equal(self):
        m.assert_full({'Noel': {'atk': 18}}, {'Noel': {'atk': 18}})

    def test_snapshot_gate_fails_stuck_restore(self):
        with self.assertRaisesRegex(AssertionError, 'restore/recalc'):
            m.assert_full({'Citri': {'atk': 14}}, {'Citri': {'atk': 16}})


if __name__ == '__main__':
    unittest.main()
