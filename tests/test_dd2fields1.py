"""DD2FIELDS1: source battle fields reach the built row, and the audit gate catches it when they do not.

Synthetic bytes only (no game data).  The negative controls are the point: the importer used to leave these fields on
the D5 donor row and nothing noticed.
"""
import json
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from d5lib import anm, database, dd2source, nativeimports, sourcefidelity
from d5lib.sourceimports import map_source_palettes

ROOT = Path(__file__).resolve().parents[1]
from d5lib import dd2fieldaudit as audit


def source_row(cid=1180, **over):
    row = bytearray(dd2source.CHAR_STRIDE)
    struct.pack_into(">H", row, 0x194, cid)
    struct.pack_into(">H", row, 0x196, cid)
    values = dict(mov=5, flag=1, rng=3, jmp=30, thr=4, cnt=1, crit=10, res=(50, -75, 25), mast=(5, 6, 7, 8, 9, 10, 11),
                  kg=12, mask=0)
    values.update(over)
    struct.pack_into(">H", row, 0x1A2, values["mov"])
    struct.pack_into(">H", row, 0x1A4, values["flag"])
    struct.pack_into(">H", row, 0x1A6, values["rng"])
    row[0x28D], row[0x290], row[0x291], row[0x292] = values["jmp"], values["thr"], values["cnt"], values["crit"]
    struct.pack_into(">bbb", row, 0x285, *values["res"])
    row[0x27C:0x283] = bytes(values["mast"])
    row[0x289] = values["kg"]
    struct.pack_into(">i", row, 0, values["mask"])
    return bytes(row)


def char_dat(rows):
    rows = list(rows)
    filler = [source_row(cid=60000 + i) for i in range(dd2source.CHAR_COUNT - len(rows))]
    return struct.pack(">Hxx", dd2source.CHAR_COUNT) + b"".join(rows + filler)


class DecodeTests(unittest.TestCase):
    def test_battle_fields_read_the_documented_offsets(self):
        fields, prov = dd2source.battle_fields(source_row())
        self.assertEqual(fields, dict(MOV=5, JMP=30, throw=4, counter=1, crit=10, attack_range=3,
                                      res_fire=50, res_wind=-75, res_ice=25,
                                      mastery_fist=5, mastery_sword=6, mastery_spear=7, mastery_bow=8,
                                      mastery_gun=9, mastery_axe=10, mastery_staff=11,
                                      kind_gender=12, move_type=1, immunity_flags=0))
        self.assertEqual({v["kind"] for v in prov.values()} - {"source-exact"}, {"rule-converted"})
        self.assertEqual(prov["move_type"]["kind"], "rule-converted")
        self.assertTrue(all(v["evidence"] for v in prov.values()))

    def test_immunity_carries_only_none_or_all(self):
        self.assertEqual(dd2source.battle_fields(source_row(mask=dd2source.D2_IMMUNITY_ALL))[0]["immunity_flags"], -1)
        partial, _ = dd2source.battle_fields(source_row(mask=0x0FFF))
        self.assertNotIn("immunity_flags", partial)          # bit order differs from D5's: stays donor
        self.assertIn("immunity_flags", dd2source.BATTLE_DONOR)

    def test_donor_fields_are_never_carried(self):
        fields, _ = dd2source.battle_fields(source_row())
        for name in ("hl_value", "exp_value", "mana_value", "is_unique", "res_star"):
            self.assertNotIn(name, fields)

    def test_flying_flag_must_be_zero_or_one(self):
        with self.assertRaises(ValueError):
            dd2source.battle_fields(source_row(flag=2))

    def test_tables_battle_finds_a_row_by_id(self):
        tables = dd2source.Tables({"char.dat": char_dat([source_row(cid=2150, mov=3)])})
        self.assertEqual(tables.battle(2150)[0]["MOV"], 3)
        with self.assertRaises(KeyError):
            tables.battle(1)


class RowTests(unittest.TestCase):
    def donor(self):
        row = database.Table("char.dat", database.get_schema("char.dat")).new_row()
        row.set("MOV", 9); row.set("kind_gender", 2); row.set("is_unique", 2); row.set("hl_value", 77)
        return row

    def description(self):
        profile = dict(id=1180, name="Female Angel", base=[10] * 8, aptitudes=[100] * 8,
                       evidence=dict(sha256="a" * 64, row_sha256="b" * 64))
        return sourcefidelity.from_profile(profile, game="dd2", edition="test", rank_count=1)

    def test_old_path_keeps_the_donor(self):
        row, report = nativeimports._gameplay_row(self.donor(), self.description(), 5)
        self.assertEqual((row["MOV"], row["kind_gender"]), (9, 2))
        self.assertNotIn("battle_source_fields", report)

    def test_new_path_writes_source_fields_and_reports_them(self):
        battle, _ = dd2source.battle_fields(source_row())
        row, report = nativeimports._gameplay_row(self.donor(), self.description(), 5, battle=battle)
        self.assertEqual((row["MOV"], row["kind_gender"], row["move_type"], row["res_wind"]), (5, 12, 1, -75))
        for key in battle:                      # the generic path copies exactly these keys onto every rank row
            self.assertEqual(report["fields"][key], battle[key])
        self.assertEqual((row["is_unique"], row["hl_value"]), (2, 77))      # donor fields untouched


class PaletteTests(unittest.TestCase):
    def test_base_bank_looks_colours_up_in_the_bank_the_art_uses(self):
        """Art extracted in bank 1 colours: with the old bank-0 lookup the colour is unmatched and bank 0 wins."""
        f = anm.AnmFile([], [], [])
        base = np.zeros((256, 4), np.uint8)
        base[1] = (200, 0, 0, 255)                      # the art carries source bank 1's entry 7
        for _ in range(2):
            anm.set_palette(f, len(f.palettes), base)
        src = [np.zeros((256, 4), np.uint8) for _ in range(2)]
        src[0][7] = (10, 20, 30, 255)
        src[1][7] = (200, 0, 0, 255)
        report = {}
        map_source_palettes(f, src, approximate=True, report=report)       # old behaviour
        self.assertEqual(tuple(anm.get_palette(f, 1)[1][:3]), (200, 0, 0))   # nearest-colour guess, only by luck
        self.assertEqual(tuple(anm.get_palette(f, 0)[1][:3]), (10, 20, 30))
        f2 = anm.AnmFile([], [], [])
        for _ in range(2):
            anm.set_palette(f2, len(f2.palettes), base)
        report = {}
        self.assertEqual(map_source_palettes(f2, src, report=report, base_bank=1), (1, 0))   # exact, no approximation
        self.assertEqual(tuple(anm.get_palette(f2, 0)[1][:3]), (10, 20, 30))
        self.assertEqual(tuple(anm.get_palette(f2, 1)[1][:3]), (200, 0, 0))


class AuditTests(unittest.TestCase):
    def pack(self, root, built_row, source_id=1180):
        pack = Path(root) / "DD2_Class_X"
        (pack / "patches/db").mkdir(parents=True)
        (pack / "mod.json").write_text(json.dumps(dict(category="classes", source_import=dict(source_ranks=[dict(id=source_id)]))))
        (pack / "patches/db/char.dat.json").write_text(json.dumps(dict(added=[built_row])))
        return pack

    def built(self):
        fields, _ = dd2source.battle_fields(source_row())
        return dict(fields, hl_value=1, exp_value=2, mana_value=3, is_unique=2)

    def rows(self):
        return audit.load_rows({"char.dat": char_dat([source_row()])})

    def test_a_carried_pack_passes_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.pack(tmp, self.built())
            report = audit.run(tmp, {"char.dat": char_dat([source_row()])}, palettes=False)
            self.assertEqual((report["mismatches"], report["failed_packs"]), (0, []))
            self.assertEqual(report["compared"], 19)

    def test_negative_control_donor_values_fail_the_gate(self):
        """The shape the old importer produced: donor MOV/throw/resistance/kind, nothing from the source row."""
        built = dict(self.built(), MOV=4, throw=5, res_wind=0, kind_gender=2, move_type=0)
        with tempfile.TemporaryDirectory() as tmp:
            self.pack(tmp, built)
            report = audit.run(tmp, {"char.dat": char_dat([source_row()])}, palettes=False)
            self.assertEqual(report["failed_packs"], ["DD2_Class_X"])
            self.assertEqual({m["field"] for m in report["packs"][0]["mismatches"]},
                             {"MOV", "throw", "res_wind", "kind_gender", "move_type"})
            self.assertIn("FAIL", audit.render(report))

    def test_a_single_off_by_one_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.pack(tmp, dict(self.built(), crit=11))
            report = audit.run(tmp, {"char.dat": char_dat([source_row()])}, palettes=False)
            self.assertEqual([(m["field"], m["source"], m["built"]) for m in report["packs"][0]["mismatches"]], [("crit", 10, 11)])

    def test_donor_fields_are_listed_but_do_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.pack(tmp, self.built())
            report = audit.run(tmp, {"char.dat": char_dat([source_row(mask=0x0FFF)])}, palettes=False)
            names = {d["field"] for d in report["packs"][0]["donor"]}
            self.assertTrue({"hl_value", "exp_value", "mana_value", "is_unique", "immunity_flags"} <= names)
            self.assertEqual(report["failed_packs"], [])

    def test_main_gate_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.pack(tmp, dict(self.built(), JMP=1))
            start = Path(tmp) / "START_4.dat"
            start.write_bytes(_nispack({"char.dat": char_dat([source_row()])}))
            self.assertEqual(audit.main(["--mods", tmp, "--source-root", str(start), "--no-palette", "--gate"]), 1)
            self.assertEqual(audit.main(["--mods", tmp, "--source-root", str(start), "--no-palette"]), 0)

    def test_independent_offsets_agree_with_the_importer_table(self):
        """The audit keeps its own offset table; a drift between the two must be a deliberate change."""
        for name, (offset, fmt, *_rest) in dd2source.BATTLE_LAYOUT.items():
            self.assertEqual(audit.CARRIED[name], (offset, fmt), name)
        self.assertEqual(audit.FLAG, (dd2source.FLYING_OFFSET, ">H"))


def _nispack(members):
    names = list(members)
    table = dd2source.PACK_HEADER + len(names) * dd2source.PACK_ENTRY
    offset, entries, body = table, b"", b""
    for name in names:
        data = members[name]
        entries += name.encode("ascii").ljust(dd2source.PACK_NAME, b"\0") + struct.pack(">III", offset, len(data), 0)
        body += data
        offset += len(data)
    return b"NISPACK\0" + struct.pack(">II", 0x01000000, len(names)) + entries + body


if __name__ == "__main__":
    unittest.main()
