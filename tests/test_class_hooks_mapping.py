"""Address-domain regression tests; synthetic PE only, no game files."""
import struct
import unittest
from unittest.mock import patch

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

from d5lib import exemap, exepatch, newclasses

BASE = exemap.IMAGE_BASE


def fixture():
    """Minimal PE32+ with genuine .text / .pdata and moved fixed hook sites."""
    data = bytearray(0x3600)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 2, 0, 0, 0, 0xf0, 0x22)
    oh = 0x98
    struct.pack_into('<H', data, oh, 0x20b)
    struct.pack_into('<Q', data, oh + 24, BASE)
    struct.pack_into('<II', data, oh + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, oh + 56, 0x5000, 0x400)
    struct.pack_into('<I', data, oh + 108, 16)
    sh = oh + 0xf0
    for k, (name, rva, size, raw, flags) in enumerate([
            (b'.text', 0x1000, 0x3000, 0x400, 0x60000020),
            (b'.pdata', 0x4000, 0x200, 0x3400, 0x40000040)]):
        struct.pack_into('<8sIIIIIIHHI', data, sh + k * 40, name, size, rva,
                         size, raw, 0, 0, 0, 0, flags)
    data[0x400:0x3400] = b'\xcc' * 0x3000
    mapping = {}
    for k, name in enumerate(('LOOKUP', 'SETTER', 'HIRE', 'CAROUSEL')):
        va = getattr(newclasses, name + '_VA')
        original = getattr(newclasses, name + '_ORIG')
        rva = 0x1000 + k * 0x40
        mapping[va] = BASE + rva
        data[0x400 + rva - 0x1000:0x400 + rva - 0x1000 + len(original)] = original
    # Exact generic-class instruction shape: monster and human comparisons.
    code = bytes.fromhex('8d8226f8ffff3d22010000760d8d8218fcffff3d360100007600c3')
    data[0x1400:0x1400 + len(code)] = code   # native RVA 0x2000
    struct.pack_into('<III', data, 0x3400, 0x2000, 0x2000 + len(code), 0)
    mapping[next(iter(newclasses.GEN_SKIP))] = BASE + 0x3000
    return bytes(data), mapping, code


class ClassHookMappingTests(unittest.TestCase):
    def setUp(self):
        self.previous = exemap.ACTIVE
        self.addCleanup(exemap.use, self.previous)

    def build(self, raw, mapping):
        exemap.use(exemap.Translator('synthetic-moved', mapping, image_end=BASE + 0x5000))
        # Only unrelated list relocation and fixed hook bodies are simplified;
        # real generic discovery, stub assembly, site guards and PE writes run.
        with patch.object(newclasses, '_reloc_hooks', return_value=[]), \
             patch.object(newclasses, '_lookup_src', return_value='ret'), \
             patch.object(newclasses, '_setter_src', return_value='ret'), \
             patch.object(newclasses, '_hire_src', return_value='ret'), \
             patch.object(newclasses, '_carousel_src', return_value='ret'):
            return newclasses.build_hooks(raw, [1350], [1350], {})

    def test_discovered_site_is_native_and_return_is_not_translated_twice(self):
        raw, mapping, code = fixture()
        # A dangerous collision: the native VA is ALSO a known-build key. It
        # must neither require that entry nor use its unrelated mapped target.
        for collision in (False, True):
            with self.subTest(collision=collision):
                m = dict(mapping)
                if collision:
                    m[BASE + 0x2000] = BASE + 0x2800
                    m[BASE + 0x200b] = BASE + 0x2810
                out = self.build(raw, m)
                pe = pefile.PE(data=out)
                section = next(s for s in pe.sections if s.Name.rstrip(b'\0') == b'.d5cl')
                self.assertEqual(out[0x1400], 0xe9)
                self.assertEqual(out[0x1405:0x140b], b'\x90' * 6)
                self.assertEqual(out[0x140b:0x140d], code[11:13])  # jbe untouched
                self.assertEqual(out[0x1c00:0x1c10], raw[0x1c00:0x1c10])  # collision trap
                target = BASE + 0x2005 + struct.unpack_from('<i', out, 0x1401)[0]
                self.assertTrue(BASE + section.VirtualAddress <= target < BASE + section.VirtualAddress + section.Misc_VirtualSize)
                ins = list(Cs(CS_ARCH_X86, CS_MODE_64).disasm(pe.get_data(target - BASE, 128), target))
                jumps = [int(i.op_str, 16) for i in ins if i.mnemonic == 'jmp']
                self.assertIn(BASE + 0x200b, jumps)
                self.assertNotIn(BASE + 0x2810, jumps)
                self.assertEqual(struct.unpack_from('<I', out, 0x1414)[0], newclasses.GEN_HUM_SPAN)
                for va, nva in mapping.items():
                    if va != next(iter(newclasses.GEN_SKIP)):
                        self.assertEqual(pe.get_data(nva - BASE, 1), b'\xe9')


    def test_native_bytes_guard_and_unmapped_fixed_site_remain_strict(self):
        raw, mapping, code = fixture()
        exemap.use(exemap.Translator('synthetic-moved', mapping, image_end=BASE + 0x5000))
        with self.assertRaisesRegex(ValueError, 'native hook site'):
            exepatch.add_hook_section(raw, b'.d5cl', [], native_hooks=[
                (BASE + 0x2000, b'\x90' * 11, 'ret', 0xe9)])
        with self.assertRaises(exemap.Unmapped):
            exepatch.add_hook_section(raw, b'.d5cl', [
                (BASE + 0x2000, code[:11], 'ret', 0xe9)])
        damaged = bytearray(raw)
        damaged[0x400] ^= 1
        with self.assertRaisesRegex(ValueError, "hook site.*doesn't match"):
            self.build(bytes(damaged), mapping)

    def test_translated_exclusion_and_busy_ranges_are_native(self):
        raw, mapping, _ = fixture()
        skip = next(iter(newclasses.GEN_SKIP))
        mapping[skip] = BASE + 0x2000
        exemap.use(exemap.Translator('synthetic-moved', mapping))
        self.assertEqual(newclasses._generic_sites(raw)[0], [])
        mapping[skip] = BASE + 0x3000
        _, hooks, _ = newclasses.generic_patch(raw, [(BASE + 0x2000, 11)])
        self.assertEqual(hooks, [])

    def test_register_bound_human_stub_preserves_native_return(self):
        raw, mapping, _ = fixture()
        exemap.use(exemap.Translator('synthetic-moved', mapping))
        # Deliberate return-key collision catches hex retranslation without a PE.
        native_return = BASE + 0x2100
        mapping[native_return] = BASE + 0x2800
        src = newclasses._hum_stub('eax', '[rdx - 0x3e8]', [], native_return)
        code = exepatch._asm(src, BASE + 0x5000)
        ins = list(Cs(CS_ARCH_X86, CS_MODE_64).disasm(code, BASE + 0x5000))
        self.assertEqual(ins[-1].mnemonic, 'jmp')
        self.assertEqual(int(ins[-1].op_str, 16), native_return)
        self.assertEqual(ins[1].op_str, 'eax, 0x3e7')


if __name__ == '__main__':
    unittest.main()
