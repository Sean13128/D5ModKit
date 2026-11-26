"""DRPGOWN1: tools/drpg_outfit_own.py fills DRPG outfits' own values from their DRPG unit (offline, synthetic data)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from d5lib import modsys, outfits

KIT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("drpg_outfit_own", KIT / "tools/drpg_outfit_own.py")
own = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(own)


class Row(dict):
    def set(self, key, value):
        self[key] = value


def char_row(cid, **kw):
    r = {f: 0 for g in outfits.OWN_GROUPS.values() for f in g[1]}
    r.update(id=cid, sprite_id=cid, color_id=cid, body_type=0, voice_id=0, evility_count=0, name_EN=f"row{cid}")
    r.update(kw)
    return r


def rpg(uid, hp, atk, df, inte, res, spd, fire=0, water=0, wind=0, star=0):
    return dict(id=uid, name=f"u{uid}", hp_min=hp, atk_min=atk, def_min=df, inte_min=inte, res_min=res, spd_min=spd,
                attr_fire=fire, attr_water=water, attr_wind=wind, attr_star=star)


CHAR = dict(base_HP=30, base_SP=12, base_ATK=20, base_DEF=16, base_INT=10, base_RES=14, base_HIT=15, base_SPD=18,
            evility1=10, evility2=11, evility_count=2, res_fire=-25, res_ice=50)


def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


def make_installed(root):
    pack = root / "DRPG_Outfits_Test"
    write(pack / "mod.json", {"name": "t"})
    write(pack / "patches/outfits/outfits.json",
          {"pairs": [[10, 473], [10, 474], [10, 475]], "names": {"473": "A", "474": "B", "475": "C"},
           "own_fields": {"473": {"movement": {"MOV": 8}}}})                          # a leftover test value
    write(pack / "patches/outfits/drpg_units.json", {"39": 473, "40": 474, "96": 475})
    write(pack / "patches/db/char.dat.json", {"table": "char.dat",
                                               "added": [char_row(s, **CHAR) for s in (473, 474, 475)]})
    prov = root / "DRPG_Core_X_40"
    write(prov / "patches/db/Skill.dat.json", {"added": [{"id": 28100, "name_EN": "Built"},
                                                         {"id": 28101, "name_EN": "No rows"}]})
    write(prov / "patches/evilities/evilities.json", {"evilities": {"28100": [{"family": "stats"}]}})
    entry = dict(name="Test", mod="DRPG_Outfits_Test", twin=2, outfits=[[39, "A"], [40, "B"], [96, "C"]])
    master = {2: rpg(2, 100, 40, 30, 20, 25, 50, -25, 50),          # the twin
              39: rpg(39, 100, 40, 30, 20, 25, 50, -25, 50),        # same as the twin: nothing to own
              40: rpg(40, 120, 60, 30, 20, 25, 50, 0, 50),          # stronger ATK, other fire resistance
              96: rpg(96, 100, 40, 30, 20, 25, 50, -25, 50)}
    overlay = {"40": {"evilities": [
        dict(slot="main", id=28100, name_en="Built", cls="A", label="source: exact"),
        dict(slot="sub1", id=28101, name_en="No rows", cls="B", label="x"),
        dict(slot="sub2", id=28102, name_en="Not provided", cls="A", label="x")]}}
    return pack, entry, master, overlay


class PureTests(unittest.TestCase):
    def test_evility_set_order_dedup_cap(self):
        self.assertEqual(own.evility_set([28100, 28101], [10, 11]), [28100, 28101, 10, 11])
        self.assertEqual(own.evility_set([1, 2, 3], [10, 2, 11]), [1, 2, 3, 10])
        self.assertEqual(own.evility_set([1, 2, 3, 4, 5], [10]), [1, 2, 3, 4])

    def test_stats_equal_to_twin_keep_the_character(self):
        base = [30, 12, 20, 16, 10, 14, 15, 18]
        twin = [100, None, 40, 30, 20, 25, None, 50]
        self.assertEqual(own.map_stats(base, twin, twin), base)

    def test_stats_keep_the_five_stat_tier_and_sp_hit(self):
        base = [30, 12, 20, 16, 10, 14, 15, 18]
        new = own.map_stats(base, [100, None, 60, 30, 20, 25, None, 50], [100, None, 40, 30, 20, 25, None, 50])
        self.assertGreater(new[2], 20)
        self.assertLessEqual(abs(sum(new[k] for k in (0, 2, 3, 4, 5)) - sum(base[k] for k in (0, 2, 3, 4, 5))), 2)
        self.assertEqual((new[1], new[6], new[7]), (12, 15, 18))

    def test_resistances_copied_and_clamped(self):
        self.assertEqual(own.map_res(rpg(1, 1, 1, 1, 1, 1, 1, 200, -25, 0, 50)),
                         {"res_fire": 127, "res_ice": -25, "res_wind": 0, "res_star": 50})


class StageTests(unittest.TestCase):
    def test_plan_and_stage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "installed"
            pack, entry, master, overlay = make_installed(root)
            provided = own.provided_evilities(root)
            self.assertEqual(set(provided), {28100})                     # a Skill row without runtime rows is not
            recs = own.plan_pack(pack, entry, master, overlay, provided, {10: "E10", 11: "E11"})
            by = {r["slot"]: r for r in recs}
            self.assertEqual(by[473]["groups"], {})                       # same as the twin: follows the character
            self.assertEqual(set(by[474]["groups"]), {"evilities", "base_stats", "resistances"})
            self.assertEqual(by[474]["groups"]["evilities"],
                             {"evility1": 28100, "evility2": 10, "evility3": 11, "evility4": 0})
            self.assertEqual(by[474]["groups"]["resistances"]["res_fire"], 0)
            self.assertIn("not decoded", by[475]["skipped_evilities"])
            out = Path(td) / "out"
            own.stage(root, out, {pack.name: recs})
            mod = modsys.Mod(str(out / pack.name))
            got = outfits.load_own_fields(mod)
            self.assertNotIn(473, {int(k) for k in got})                  # the leftover test value is cleared
            self.assertEqual(got[474]["evilities"]["evility1"], 28100)
            # the outfit row the kit builds from it
            rows = {10: Row(char_row(10, **CHAR)), 474: Row(char_row(474, **CHAR))}
            outfits._follow_base(rows, [[10, 474]], (), {474: got[474]})
            self.assertEqual([rows[474][f"evility{i}"] for i in range(1, 5)] + [rows[474]["evility_count"]],
                             [28100, 10, 11, 0, 3])
            # nothing but outfits.json differs from the installed pack
            for f in pack.rglob("*"):
                if f.is_file() and f.name != "outfits.json":
                    self.assertEqual(f.read_bytes(), (out / pack.name / f.relative_to(pack)).read_bytes())


if __name__ == "__main__":
    unittest.main()
