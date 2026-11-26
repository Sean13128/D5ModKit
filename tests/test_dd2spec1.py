"""DD2SPEC1: Disgaea D2 scene scripts and effect models read for the D4 scene route (offline, real bytes).

Reads the user's prepared DD2 and D4 copies under `Disgaea Source/` at test time and skips when they are absent;
no game data is stored in the repository.
"""
import glob
import hashlib
import os
import struct
import unittest
from pathlib import Path

from d5lib import d4inventory, dd2effects, dd2scripts, lzs, obf, fxanim, script

PROJECT = Path(os.environ.get("D5_PROJECT", "/Volumes/Data/Projects/D5"))
DD2 = next(iter(glob.glob(str(PROJECT / "Disgaea Source/Disgaea D2 PS3 (BLUS31313)/disc/*/PS3_GAME/USRDIR/Data"))),
           None)
D4 = next(iter(glob.glob(str(PROJECT / "Disgaea Source/Disgaea 4 Complete+ (Steam *)/*/Data/DATA/EN"))), None)
SCRIPT_SHA = "4fa90337e0ac1e2c52d88b221082cada01a370e7491377a229a80e0e53999e7a"   # START_4.dat script.dat (BLUS31313)
# the adapted DD2 specials of the installed packs (specials2 label A), by source skill id
ADAPTED = [10013, 10061, 10081, 10082, 10101, 10102, 10141, 10213, 10291, 10292, 10293, 10321, 10402, 10421, 10422,
           10423, 10481, 10482, 10483, 10571, 10572, 10573, 12021, 12022, 12023, 12024, 12041, 12042, 12043, 12044,
           12051, 12052, 12053, 12054, 12091, 12092, 12093, 12094, 12121, 12122, 12123, 12124, 12131, 12132, 12133,
           12134, 12171, 12172, 12173, 12174, 12181, 12182, 12183, 12184, 12201, 12202, 12203, 12204]


def _source():
    return dd2scripts.Source(dd2scripts.open_pack(Path(DD2) / "START_4.dat").read("script.dat"))


@unittest.skipUnless(DD2, "Disgaea D2 source copy not present")
class Scripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _source()

    def test_identity_and_framing(self):
        self.assertEqual(self.source.sha256, SCRIPT_SHA)
        self.assertEqual(len(self.source.index), 12710)
        # every event but three frames with DD2's widths (DD2EVENT1's survey framed 12483); every framed one parses
        self.assertEqual(len(self.source.failed), 3)
        errors = [e for e in self.source.index if self.source.event(e).get("error")]
        self.assertEqual(sorted(errors), sorted(self.source.failed))

    def test_transcode_is_byte_exact_per_instruction(self):
        # transcoding back: re-encoding the parsed event in D5 layout equals the transcoded bytes, and its length
        # equals the DD2 event's (only byte order changed)
        raw = dd2scripts.open_pack(Path(DD2) / "START_4.dat").read("script.dat")
        n = struct.unpack_from(">I", raw)[0]
        offs = list(struct.unpack_from(f">{n}I", raw, 4)) + [len(raw) - 4 - 8 * n]
        ids = struct.unpack_from(f">{n}I", raw, 4 + 4 * n)
        for i in range(0, n, 97):
            if ids[i] in self.source.failed:
                continue
            record = self.source.event(ids[i])
            self.assertEqual(record["source_bytes"], offs[i + 1] - offs[i])

    def test_adapted_specials_resolve(self):
        complete = 0
        for sid in ADAPTED:
            closure = self.source.closure(12000000 + sid)
            bad = [e for e in closure["events"] if self.source.event(e).get("error")]
            self.assertFalse(closure["dynamic_calls"], sid)
            if not bad:
                complete += 1
            else:   # the two known DD2 calls to events DD2 does not ship
                self.assertIn((sid, bad), [(10321, [15045900]), (12203, [15112200])])
        self.assertEqual(complete, 56)

    def test_actor_and_target_operands_are_d4_s(self):
        # Flying Press: caster 1064, main target 151, damage 7220 and one finalizer 7228 on 151, as D4 scenes do
        ops = [ins for e in self.source.closure(12012091)["events"] for ins in self.source.event(e)["event"].code]
        hits = [i.args for i in ops if i.cid == 0x7220]
        self.assertTrue(hits and all(a[0] == 151 for a in hits))
        self.assertEqual([i.args for i in ops if i.cid == 0x7228 and i.args[0] == 151], [[151, 30]])   # one finalizer
        self.assertTrue(any(i.cid == 0x6510 and i.args[0] == 1064 for i in ops))

    def test_widths_differ_from_d4_only_for_sound(self):
        d4 = d4inventory.script_reader().SIGS
        for cid, widths in dd2scripts.DD2_WIDTHS.items():
            self.assertNotEqual(d4.get(cid), widths, hex(cid))
            self.assertTrue(cid >> 8 == 0x46 or cid == 0x78B7, hex(cid))


@unittest.skipUnless(DD2 and D4, "Disgaea D2 and Disgaea 4 source copies not present")
class Effects(unittest.TestCase):
    """Effects used by the adapted specials whose section layout equals the same-numbered D4 PC effect: the D4 PC
    bytes are the D5-order reference (the SPECBULK route converts them for D5)."""

    USED = (1, 2, 7, 9, 15, 37, 44, 46, 47, 50, 52, 100, 200, 201)

    @classmethod
    def setUpClass(cls):
        from d5lib.d4source import Nsac
        cls.dd2 = dd2scripts.open_pack(Path(DD2) / "START.dat")
        cls.d4 = Nsac(Path(D4) / "EFFECT.dat")

    def pairs(self):
        for eid in self.USED:
            raw = lzs.decompress(self.dd2.read(f"effect{eid:03d}.lzs"))
            ref = obf.ObfFile(lzs.decompress(self.d4.read(f"effect{eid:03d}.lzs")))
            yield eid, raw, ref

    def test_converted_sections_equal_d4(self):
        compared = 0
        for eid, raw, ref in self.pairs():
            model = obf.ObfFile(dd2effects.convert(raw))
            if [len(s) for s in model.sections[:9]] != [len(s) for s in ref.sections[:9]]:
                continue
            compared += 1
            for s in (0, 1, 6):
                self.assertEqual(model.sections[s], ref.sections[s], (eid, s))
            a, b = fxanim.read(model), fxanim.read(ref)
            self.assertEqual((a.length, len(a.nodes), len(a.keys), len(a.points)),
                             (b.length, len(b.nodes), len(b.keys), len(b.points)), eid)
            self.assertEqual([p.type for p in a.points], [p.type for p in b.points], eid)
            for t in model.textures:
                self.assertTrue(t.decodable, eid)
                t.to_image()
        self.assertGreaterEqual(compared, 8)

    def test_negative_control_plain_word_swap_fails(self):
        # the curve-point bit field is the one non-word field that matters: a plain 32-bit swap of section 5
        # gives other point types than D4 (so the comparison above can fail)
        eid, raw, ref = next((e, r, f) for e, r, f in self.pairs() if e == 50)
        total = struct.unpack_from(">I", raw)[0]
        offs = list(struct.unpack_from(">10I", raw, 8)) + [total]
        sec5 = raw[offs[5]:offs[6]]
        wrong = struct.pack(f"<{len(sec5) // 4}I", *struct.unpack(f">{len(sec5) // 4}I", sec5))
        good = obf.ObfFile(dd2effects.convert(raw))
        model = obf.ObfFile(good.to_bytes())
        model.sections[5] = wrong
        self.assertNotEqual([p.type for p in fxanim.read(model).points], [p.type for p in fxanim.read(ref).points])

    def test_la88_headers_turn_and_short_size_fields_are_fixed(self):
        raw = lzs.decompress(self.dd2.read("effect201.lzs"))
        model = obf.ObfFile(dd2effects.convert(raw))
        tex = model.textures[0]
        self.assertEqual((tex.format_name, tex.width, tex.height, tex.layers), ("LA88", 64, 64, 2))
        self.assertTrue(tex.decodable)


ELF = Path("/Volumes/Data/Applications/QuiverLauncher/Apps/Disgaea D2-RE/work/EBOOT.elf")
ELF_SHA = "0ba5683248b00a5cdb75d52a640f8b8bc30fd16a16181549cd605f7b09645447"


@unittest.skipUnless(ELF.is_file(), "DD2 1.00 EBOOT.elf not present")
class Native(unittest.TestCase):
    """DD2's own actor numbering (PPC64 BE, 1.00 EBOOT): the same ids as D4's actor lookup."""

    def words(self, start, count):
        data = ELF.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), ELF_SHA)
        ph = struct.unpack_from(">Q", data, 32)[0]
        size, n = struct.unpack_from(">HH", data, 54)
        for i in range(n):
            kind, _, off, va, _, filesz, _, _ = struct.unpack_from(">IIQQQQQQ", data, ph + i * size)
            if kind == 1 and va <= start < va + filesz:
                return struct.unpack_from(f">{count}I", data, off + start - va)
        raise AssertionError("address not mapped")

    def test_battle_unit_predicate(self):
        # 0x369ef8..0x369f24: addi r0,r3,-0x65; cmplwi 0x27 (101..140); cmpwi 0x97 (151); addi r0,r3,-0xa0;
        # cmplwi 0x1f (160..191 = area targets); cmpwi 0x8e; cmpwi 0x91
        w = self.words(0x369ef8, 12)
        self.assertEqual(w[0] & 0xFFFF, 0xFF9B)       # -0x65
        self.assertEqual(w[1] & 0xFFFF, 0x27)
        self.assertEqual(w[3] & 0xFFFF, 0x97)
        self.assertEqual(w[5] & 0xFFFF, 0xFF60)       # -0xa0
        self.assertEqual(w[6] & 0xFFFF, 0x1F)

    def test_group_anchors(self):
        # 0x369ca4..0x369cf0: 215, 10000, 30000 and 202 take the group path (D4 0x1401276d0: 202 = every target)
        self.assertEqual(self.words(0x369ca4, 1)[0] & 0xFFFF, 0xD7)
        self.assertEqual(self.words(0x369cb0, 1)[0] & 0xFFFF, 0x2710)
        self.assertEqual(self.words(0x369cb8, 1)[0] & 0xFFFF, 0x7530)
        self.assertEqual(self.words(0x369cf0, 1)[0] & 0xFFFF, 0xCA)


if __name__ == "__main__":
    unittest.main()


class LoopCounterConditions(unittest.TestCase):
    """DD2SPEC2: a condition on the loop counter ($10100 -> preview $20100) reads the counter, as operands do."""

    def test_condition_sees_the_counter(self):
        from d5lib import choreo
        end1, end2 = script.Ins(0x0148), script.Ins(0x0148)
        code = [script.Ins(0x0150, [1, 3]),
                script.Ins(0x0140, conds=[script.Cond(script.Var(choreo.LOOP_VAR), 0x0A, 2)], target=end1),
                script.Ins(0x7220, [151, 151, 10]), end1,
                script.Ins(0x0158), script.Ins(0x0108)]
        tl = choreo.simulate({1: script.Event(1, code)}, 1)
        self.assertEqual([op.args for op in tl.ops if op.cid == 0x7220], [[151, 151, 10]])


@unittest.skipUnless(DD2, "Disgaea D2 source copy not present")
class NativeTextureBounds(unittest.TestCase):
    """DD2SPEC3 (Codex REVIEW-DD2SPEC2): every converted DD2 effect passes D5's texture-header arithmetic
    (d5lib.obfbounds, after 0x14030FFF0); the DD2SPEC2 header (marker written as part of a u32) fails it."""

    @classmethod
    def setUpClass(cls):
        cls.pack = dd2scripts.open_pack(Path(DD2) / "START.dat")

    def model(self, eid):
        return dd2effects.convert(lzs.decompress(self.pack.read(f"effect{eid:03d}.lzs")))

    def test_every_dd2_effect_is_inside_its_bytes(self):
        from d5lib import obfbounds
        for eid in range(256):
            data = self.model(eid)
            self.assertEqual(obfbounds.check(data), [], eid)
            for (i, t), kit in zip(obfbounds.textures(data), obf.ObfFile(data).textures):
                self.assertEqual((t["width"], t["height"]), (kit.width, kit.height), (eid, i))

    def test_effect73_witness(self):
        from d5lib import obfbounds
        data = self.model(73)                      # staged as effect9268.obf for skill 29164 in DD2SPEC2
        tex = obfbounds.textures(data)[0][1]
        self.assertEqual((tex["fmt"], tex["width"], tex["height"], tex["size"], tex["swapped"]), (12, 256, 32, 16384, False))
        # negative control: the DD2SPEC2 header (bytes 8..11 written as u32 0x00010000 little-endian)
        total = struct.unpack_from("<I", data)[0]
        offs = list(struct.unpack_from("<10I", data, 8)) + [total]
        bank = offs[9]
        first = bank + struct.unpack_from("<I", data, bank + 4)[0] + 4
        broken = bytearray(data)
        broken[first + 8:first + 12] = struct.pack("<I", 0x00010000)
        problems = obfbounds.check(bytes(broken))
        self.assertTrue(problems and "4194304" in problems[0], problems)

    def test_staged_dd2spec2_model_fails(self):
        from d5lib import obfbounds
        staged = PROJECT / "Builds/DD2SPEC2-20261120/stage/mods/DD2_Class_22520/patches/skills/effect9268.obf"
        if not staged.is_file():
            self.skipTest("DD2SPEC2 stage not present")
        self.assertTrue(any("4194304" in p for p in obfbounds.check(staged.read_bytes())))

    def test_size_field_twice_the_pixels_is_cut_to_the_stored_layers(self):
        from d5lib import obfbounds
        for eid in (200, 201):
            for _, t in obfbounds.textures(self.model(eid)):
                self.assertLessEqual(t["copy"], t["available"])


D5SRC = next(iter(glob.glob(str(PROJECT / "Disgaea Source/Disgaea 5 Complete (Steam *)"))), None)


@unittest.skipUnless(D5SRC, "Disgaea 5 source copy not present")
class VanillaBaseline(unittest.TestCase):
    def test_vanilla_effects(self):
        """every vanilla D5 effect stays inside its bytes except effect1705, whose LA88 size fields are twice the
        stored pixels (the same layout as DD2 200/201): D5 itself reads past that model, the converter does not"""
        from d5lib import gamefs, obfbounds, skills, ykcmp
        fs = gamefs.GameFS(D5SRC)
        failing = []
        for name in sorted(skills.effect_members(fs.read)):
            data = fs.read(f"{skills.EFFECT_DAT}/{name}")
            data = ykcmp.decompress(data) if ykcmp.is_ykcmp(data) else data
            if obfbounds.check(data):
                failing.append(name)
        self.assertEqual(failing, ["effect1705.obf"])
