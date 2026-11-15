"""BANKPR1: failure injection on synthetic saves (no game data), the duplicate guards, Dismiss's guest flag, and the
export always unequips (to the bag on a move)."""
import glob
import hashlib
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
sys.path.insert(0, HERE)

from d5lib import savegame, unitbank  # noqa: E402
import unit_bank  # noqa: E402
from test_bankfeat1 import NEEDS_LEARNED, TABLE, learned  # noqa: E402
from test_unit_bank_cli import INSTALLED, VANILLA, run, write_save  # noqa: E402


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def disk_full(*a, **k):
    raise OSError(28, "No space left on device")


def give_items(path, slot, ids, bag=()):
    """equip items `ids` on a unit and put `bag` item ids in the save's bag"""
    s = savegame.Save(path)
    base = savegame.ROSTER + slot * savegame.UNIT
    for k, iid in enumerate(ids):
        o = base + unitbank.ITEMS + k * unitbank.ITEM
        s.state[o:o + unitbank.ITEM] = bytes(unitbank.ITEM)
        struct.pack_into("<I", s.state, o + unitbank.ITEM_ID, iid)
        struct.pack_into("<I", s.state, o + 4, 224)                     # an innocent entry: travels with the block
    for i, iid in enumerate(bag):
        struct.pack_into("<I", s.state, unitbank.BAG + i * unitbank.ITEM + unitbank.ITEM_ID, iid)
    struct.pack_into("<H", s.state, unitbank.BAG_COUNT, len(bag))
    s.write()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.d = self.tmp.name
        sd = os.path.join(d, "AppData", *unit_bank.GAME_SAVE_DIRS, "27885847", "SaveData")
        os.makedirs(sd)
        units = [(0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7)),
                 (2, dict(name="Valvatorez", cls=570, serial=6))]
        self.live = write_save(os.path.join(sd, "Save_001.sav"), army=3, uid=9, slots=units)
        if learned:
            learned.sidecar_write(self.live + learned.SIDECAR_SUFFIX, learned.sidecar_doc(self.live, TABLE, {5: [21000]}))
        self.copy = write_save(os.path.join(d, "copy.sav"), army=3, uid=9, slots=units)
        self.kit = os.path.join(d, "kit")
        self.bank = os.path.join(d, "bank")
        p = mock.patch.object(unit_bank, "game_running", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def files(self):
        return sorted(glob.glob(os.path.join(self.bank, "*" + unit_bank.EXT)))

    def hashes(self, p):
        return [sha(f) for f in (p, p + unit_bank.SIDECAR_SUFFIX) if os.path.exists(f)]


class FailureInjection(Base):
    def move(self, path, **kw):
        return unit_bank.export(path, "Keke", self.bank, VANILLA, move=True, live=True, kit_dir=self.kit, **kw)

    def test_disk_full_writing_the_save_puts_it_back_and_takes_the_bank_file_back(self):
        before = self.hashes(self.live)
        with mock.patch.object(savegame.Save, "write", disk_full), self.assertRaises(OSError):
            self.move(self.live)
        self.assertEqual(self.hashes(self.live), before)
        self.assertEqual(self.files(), [])                       # the unit is in the save only: no duplicate
        (b,) = glob.glob(os.path.join(self.kit, "state", "save_backups", "*", "*", "SaveData", "Save_001.sav"))
        self.assertEqual(sha(b), before[0])                      # the backup is byte-identical

    @NEEDS_LEARNED
    def test_companion_write_failure_after_the_save_was_written(self):
        before = self.hashes(self.live)
        with mock.patch.object(unit_bank, "write_companion", disk_full), self.assertRaises(OSError):
            self.move(self.live)
        self.assertEqual(self.hashes(self.live), before)         # save AND companion put back
        self.assertEqual(self.files(), [])

    def test_failed_write_on_a_plain_copy_keeps_save_and_drops_bank_file(self):
        before = sha(self.copy)
        with mock.patch.object(savegame.Save, "write", disk_full), self.assertRaises(OSError):
            unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)
        self.assertEqual(sha(self.copy), before)
        self.assertEqual(self.files(), [])

    def test_disk_full_writing_the_bank_file_leaves_nothing(self):
        before = sha(self.copy)
        real = open

        def opener(path, mode="r", *a, **k):
            f = real(path, mode, *a, **k)
            if "x" in mode:
                f.write = disk_full
            return f
        with mock.patch("builtins.open", opener), self.assertRaises(OSError):
            unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)
        self.assertEqual(sha(self.copy), before)
        self.assertEqual(os.listdir(self.bank), [])              # no partial, unreadable bank file

    @NEEDS_LEARNED
    def test_import_companion_failure_puts_the_save_back(self):
        out, _ = unit_bank.export(self.copy, "Keke", self.bank, VANILLA)
        tgt = write_save(os.path.join(os.path.dirname(self.live), "Save_003.sav"), army=1, uid=40,
                         slots=[(0, dict(name="Killia", cls=10, serial=1))])
        learned.sidecar_write(tgt + learned.SIDECAR_SUFFIX, learned.sidecar_doc(tgt, TABLE, {}))
        before = self.hashes(tgt)
        with mock.patch.object(unit_bank, "write_companion", disk_full), self.assertRaises(OSError):
            unit_bank.import_(out, tgt, INSTALLED, VANILLA, move=True, live=True, kit_dir=self.kit)
        self.assertEqual(self.hashes(tgt), before)
        self.assertTrue(os.path.exists(out))                    # the bank file stays: the unit is nowhere else

    def test_same_name_class_serial_from_another_save_never_overwrites(self):
        other = write_save(os.path.join(self.d, "other.sav"), army=1, uid=9,
                           slots=[(0, dict(name="Keke", cls=190, serial=5, level=99))])
        a, _ = unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)
        b, _ = unit_bank.export(other, "Keke", self.bank, VANILLA, move=True)
        self.assertNotEqual(a, b)
        self.assertEqual([unit_bank.read_entry(f)["level"] for f in (a, b)], [7, 99])

    def test_stale_card_is_refused(self):
        before = sha(self.copy)
        with self.assertRaises(unit_bank.Refused):
            unit_bank.export(self.copy, "1", self.bank, VANILLA, move=True, serial=6)   # slot 1 is serial 5 now
        self.assertEqual(sha(self.copy), before)
        self.assertFalse(os.path.exists(self.bank) and os.listdir(self.bank))


@NEEDS_LEARNED
class Companion(Base):
    def test_move_keeps_the_next_units_quarantine(self):
        doc = learned.sidecar_doc(self.copy, TABLE, {}, quarantine=[dict(serial=5, id=90001), dict(serial=6, id=90002)])
        learned.sidecar_write(self.copy + learned.SIDECAR_SUFFIX, doc)
        unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)       # Valvatorez (6) shifts into slot 1
        comp, why = unit_bank.companion(self.copy)
        self.assertIsNone(why)
        self.assertEqual(comp["quarantine"], [dict(serial=6, id=90002)])


class Duplicates(Base):
    def test_importing_the_same_bank_file_twice_is_refused(self):
        out, _ = unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)
        tgt = write_save(os.path.join(self.d, "t.sav"), army=1, uid=40, slots=[(0, dict(name="Killia", cls=10, serial=1))])
        self.assertEqual(run("import", str(out), tgt)[0], 0)
        before = sha(tgt)
        code, text = run("import", str(out), tgt)
        self.assertEqual(code, 2, text)
        self.assertIn("already holds this unit", text)
        self.assertEqual(sha(tgt), before)
        self.assertEqual(run("import", str(out), tgt, "--allow-duplicate")[0], 0)

    def test_putting_it_back_into_its_own_save_is_allowed(self):
        out, _ = unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)
        self.assertEqual(run("import", str(out), self.copy)[0], 0)


class GuestFlag(Base):
    def test_move_clears_the_dlc_recruited_flag_like_dismiss(self):
        s = savegame.Save(self.copy)
        for f in (18310, 18300):                                  # Valvatorez's flag and Laharl's
            s.state[unitbank.GAME_FLAGS + f // 8] |= 1 << (f & 7)
        s.write()
        unit_bank.export(self.copy, "Valvatorez", self.bank, VANILLA, move=True)
        st = savegame.Save(self.copy).state
        bit = lambda f: st[unitbank.GAME_FLAGS + f // 8] >> (f & 7) & 1   # noqa: E731
        self.assertEqual((bit(18310), bit(18300)), (0, 1))

    def test_import_sets_it_again(self):
        out, _ = unit_bank.export(self.copy, "Valvatorez", self.bank, VANILLA, move=True)
        tgt = write_save(os.path.join(self.d, "t.sav"), army=1, uid=40, slots=[(0, dict(name="Killia", cls=10, serial=1))])
        self.assertEqual(run("import", str(out), tgt)[0], 0)
        st = savegame.Save(tgt).state
        self.assertEqual(st[unitbank.GAME_FLAGS + 18310 // 8] >> (18310 & 7) & 1, 1)

    def test_copy_export_leaves_flags(self):
        before = sha(self.copy)
        unit_bank.export(self.copy, "Valvatorez", self.bank, VANILLA)
        self.assertEqual(sha(self.copy), before)


class Unequip(Base):
    def test_export_never_carries_items(self):
        give_items(self.copy, 1, [101, 102])
        out, e = unit_bank.export(self.copy, "Keke", self.bank, VANILLA)
        self.assertEqual(unitbank.equipped(unitbank.entry_record(unit_bank.read_entry(out))), [])

    def test_move_puts_items_in_the_bag(self):
        give_items(self.copy, 1, [101, 102], bag=[7, 8, 9])
        out, e = unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)
        self.assertEqual(e["unequipped"], 2)
        self.assertEqual(unitbank.equipped(unitbank.entry_record(unit_bank.read_entry(out))), [])
        s = savegame.Save(self.copy)
        ids = [unitbank._u32(s.state, unitbank.BAG + i * unitbank.ITEM + unitbank.ITEM_ID) for i in range(6)]
        self.assertEqual(ids, [7, 8, 9, 101, 102, 0])
        self.assertEqual(struct.unpack_from("<H", s.state, unitbank.BAG_COUNT)[0], 5)
        self.assertEqual(unitbank._u32(s.state, unitbank.BAG + 3 * unitbank.ITEM + 4), 224)   # innocent came along

    def test_copy_strips_the_bank_copy_and_keeps_the_save(self):
        give_items(self.copy, 1, [101])
        before = sha(self.copy)
        out, e = unit_bank.export(self.copy, "Keke", self.bank, VANILLA)
        self.assertEqual(sha(self.copy), before)
        rec = unitbank.entry_record(unit_bank.read_entry(out))
        self.assertEqual(rec[unitbank.ITEMS:unitbank.ITEMS + unitbank.ITEM], unitbank.EMPTY_ITEM)

    def test_full_bag_refuses_and_changes_nothing(self):
        give_items(self.copy, 1, [101, 102], bag=[5] * (unitbank.BAG_SLOTS - 1))
        before = sha(self.copy)
        with self.assertRaises(unit_bank.Refused) as cm:
            unit_bank.export(self.copy, "Keke", self.bank, VANILLA, move=True)
        self.assertIn("room for 1", str(cm.exception))
        self.assertEqual(sha(self.copy), before)
        self.assertFalse(os.path.exists(self.bank) and os.listdir(self.bank))


if __name__ == "__main__":
    unittest.main()
