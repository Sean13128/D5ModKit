"""Synthetic fixtures only; no game files required."""
import struct
import unittest
import hashlib
from unittest.mock import patch

from d5lib import d4effects as fx, obf


def texture(fmt=14, palettes=None, pixels=b'\0\1', width=2, height=1, attr=b'\x6c\0\x0a\x02'):
    colors = {14: 256, 10: 16, 2: 0}[fmt]
    if palettes is None:
        palettes = [bytes((i, 255-i, i // 2, i)) for i in range(colors)]
        palettes = [b''.join(palettes)] if colors else []
    pitch = width * 4 if fmt == 2 else width if fmt == 14 else width // 2
    header = bytes((fmt, 2, 0, 255, 0, len(palettes))) + struct.pack('<3HI', width, height, 1, pitch)
    payload = b''.join(palettes) + pixels
    # Stored extent is 16 larger than palettes+pixel data in intact resources.
    size = len(payload) + 16
    return attr + fx.MAGIC * 2 + struct.pack('<4I', 0, size, size, 0) + header + payload + fx.FOOTER + bytes(16)


def model(entries):
    sections = [struct.pack('<I', 0)] * 10
    sections[9] = obf.build_table(entries)
    offsets, cur = [], 48
    for section in sections:
        offsets.append(cur)
        cur += len(section)
    return struct.pack('<12I', cur, 2, *offsets) + b''.join(sections)


class LegacyEffectsTests(unittest.TestCase):
    def test_index8_bgra_and_alpha(self):
        t = fx.decode_texture(texture())
        self.assertEqual(t.rgba_layers[0], bytes((0, 255, 0, 0, 0, 254, 1, 1)))
        self.assertEqual(t.indices, b'\0\1')

    def test_index4_low_nibble_first(self):
        t = fx.decode_texture(texture(10, pixels=b'\x21'))
        self.assertEqual(t.indices, b'\1\2')
        self.assertEqual(t.image().getpixel((0, 0)), (0, 254, 1, 1))
        self.assertEqual(t.image().getpixel((1, 0)), (1, 253, 2, 2))

    def test_color32_bgra_alpha(self):
        t = fx.decode_texture(texture(2, pixels=bytes((1, 2, 3, 4, 5, 6, 7, 8))))
        self.assertEqual(t.rgba_layers[0], bytes((3, 2, 1, 4, 7, 6, 5, 8)))

    def test_every_palette_is_preserved_and_conversion_refuses_flattening(self):
        palettes = [bytes((1, 2, 3, 4)) * 16, bytes((5, 6, 7, 8)) * 16]
        entry = texture(10, palettes, pixels=b'\0')
        t = fx.decode_texture(entry)
        self.assertEqual(len(t.rgba_layers), 2)
        self.assertEqual(t.rgba_layers[1], bytes((7, 6, 5, 8)) * 2)
        with self.assertRaisesRegex(fx.UnsupportedEffect, '2 palette variants'):
            fx.convert_texture(entry)

    def test_conversion_matches_pixels_and_sampler_bytes(self):
        entry = texture()
        target, report = fx.convert_texture(entry)
        self.assertEqual(target[:4], entry[:3] + b'\0')
        self.assertEqual(obf.Texture(target).to_image().tobytes(), fx.decode_texture(entry).rgba_layers[0])
        self.assertTrue(report['pixel_exact'])

    def test_obf_only_section9_changes(self):
        source = model([texture()])
        output, report = fx.convert_obf(source)
        self.assertEqual(obf.ObfFile(source).sections[:9], obf.ObfFile(output).sections[:9])
        self.assertTrue(report['non_texture_sections_exact'])

    def test_malformed_sources_rejected(self):
        valid = texture()
        for offset, value in [(3, 0), (4, 0), (40, 0), (52, 9), (53, 3), (57, 0), (58, 0), (64, 0)]:
            b = bytearray(valid)
            b[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                fx.decode_texture(bytes(b))
        with self.assertRaises(ValueError):
            fx.decode_texture(valid[:-1])
        with self.assertRaises(ValueError):
            fx.decode_texture(valid + b'\0')

    def test_bad_footer_and_row_pitch_rejected(self):
        b = bytearray(texture())
        b[-32] = 0
        with self.assertRaisesRegex(ValueError, 'end marker'):
            fx.decode_texture(bytes(b))
        b = bytearray(texture())
        struct.pack_into('<I', b, 64, 10)
        with self.assertRaisesRegex(ValueError, 'row pitch'):
            fx.decode_texture(bytes(b))

    def test_bad_obf_header_rejected(self):
        for b in [b'', bytes(48), struct.pack('<II', 9999, 2) + bytes(40)]:
            with self.assertRaises(ValueError):
                fx.convert_obf(b)


class Effect71OptInTests(unittest.TestCase):
    """Generated pixels only. Reseal test fixtures, never weaken the API seal."""

    def setUp(self):
        self.palettes = [b''.join(bytes((i, i * 3 % 256, 255 - i, i * 7 % 256)) for i in range(256)),
                         b''.join(bytes((255 - i, i * 5 % 256, i * 11 % 256, (255 - i * 13) % 256)) for i in range(256))]
        self.indices = bytes((x * 5 + y * 3) % 256 for y in range(128) for x in range(128))
        self.entry = texture(14, self.palettes, self.indices, 128, 128, b'\x6c\0\0\x02')
        mesh0, mesh1 = bytearray(60), bytearray(60)
        struct.pack_into('<I', mesh0, 0, 3)
        struct.pack_into('<I', mesh1, 0, 6)
        mesh0[11], mesh1[11] = 255, 127
        self.sections = [bytes((index,)) * (4 + index) for index in range(9)]
        self.sections[7] = struct.pack('<III', 2, 12, 72) + mesh0 + mesh1
        self.source = self.container(self.sections + [struct.pack('<II', 1, 8) + self.entry])
        # Independent scalar palette/channel/header/container oracle, without
        # the production decoder, OBF writer or TXF encoder.
        self.rgba, payload = [], bytearray()
        for palette in self.palettes:
            rgba = bytearray()
            for index in self.indices:
                b, g, r, a = palette[index * 4:index * 4 + 4]
                rgba.extend((r, g, b, a));payload.extend((a, r, g, b))
            self.rgba.append(bytes(rgba))
        header = b'\0\1\1\1' + struct.pack('>HHII', 128, 128, 0x10000, 131072)
        self.expected = self.container(self.sections + [struct.pack('<II', 1, 8) + b'\x6c\0\0\0' + header + payload])

    @staticmethod
    def container(sections, trailer=b''):
        offsets, total = [], 48
        for section in sections:offsets.append(total);total += len(section)
        return struct.pack('<12I', total, 2, *offsets) + b''.join(sections) + trailer

    def sealed(self, source=None, expected=None):
        # Synthetic success tests substitute only identity seals; malformed
        # structural cases are resealed deliberately to exercise deeper guards.
        source = self.source if source is None else source
        expected = self.expected if expected is None else expected
        return patch.multiple(fx, EFFECT71_SOURCE_SHA256=hashlib.sha256(source).hexdigest(),
                              EFFECT71_TARGET_SHA256=hashlib.sha256(expected).hexdigest(),
                              EFFECT71_TARGET_BYTES=len(expected))

    def test_optin_requires_exact_complete_source_and_explicit_bool(self):
        with self.assertRaisesRegex(fx.UnsupportedEffect, 'exact reviewed expanded EN source fingerprint'):
            fx.convert_obf(self.source, effect71_two_frames=True)
        for value in (1, 'yes', None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'explicit bool'):
                fx.convert_obf(self.source, effect71_two_frames=value)
        with self.sealed():
            changed = bytearray(self.source);changed[48] ^= 1
            with self.assertRaisesRegex(fx.UnsupportedEffect, 'fingerprint'):
                fx.convert_obf(bytes(changed), effect71_two_frames=True)

    def test_default_refusal_and_single_palette_behavior_stay_unchanged(self):
        with self.sealed(), self.assertRaisesRegex(fx.UnsupportedEffect, '2 palette variants'):
            fx.convert_obf(self.source)
        source = model([texture()])
        default, report = fx.convert_obf(source)
        explicit, explicit_report = fx.convert_obf(source, effect71_two_frames=False)
        self.assertEqual((default, report), (explicit, explicit_report))
        self.assertEqual(report['status'], 'converted-offline')
        self.assertNotIn('resource_ready', report)

    def test_two_frames_match_independent_pixels_header_order_and_container(self):
        with self.sealed():output, report = fx.convert_obf(self.source, effect71_two_frames=True)
        self.assertEqual(output, self.expected)
        total, version, *offsets = struct.unpack_from('<12I', output)
        self.assertEqual((total, version), (len(output), 2))
        entry = output[offsets[9] + 8:total]
        self.assertEqual(entry[:20], b'\x6c\0\0\0\0\1\1\1' + struct.pack('>HHII', 128, 128, 0x10000, 131072))
        for index in range(2):
            encoded = entry[20 + index * 65536:20 + (index + 1) * 65536]
            rgba = b''.join(bytes((encoded[i+1], encoded[i+2], encoded[i+3], encoded[i])) for i in range(0, 65536, 4))
            self.assertEqual(rgba, self.rgba[index])
            frame = report['textures'][0]['frames'][index]
            self.assertEqual((frame['texture_entry_offset'], frame['length']), (20 + index * 65536, 65536))
            self.assertEqual(frame['rgba_sha256'], hashlib.sha256(rgba).hexdigest())
        self.assertEqual(report['fidelity'], 'adapted');self.assertEqual(report['status'], 'partial-offline')
        self.assertIs(report['resource_ready'], False)
        self.assertEqual(report['presentation'], 'not-tested')
        self.assertTrue(report['trailer_exact']);self.assertGreater(len(report['remaining_gates']), 3)

    def test_padding_and_opaque_trailer_bytes_are_preserved_exactly(self):
        for trailer in (bytes(7), b'opaque\0\xff'):
            source, expected = self.source + trailer, self.expected + trailer
            with self.subTest(trailer=trailer), self.sealed(source, expected):
                output, report = fx.convert_obf(source, effect71_two_frames=True)
                self.assertEqual(output, expected);self.assertTrue(report['trailer_exact'])

    def test_resealed_unsupported_texture_and_material_contracts_refuse(self):
        variants = []
        for offset, value in ((0, 2), (1, 1), (2, 1), (3, 0), (52, 10)):
            entry = bytearray(self.entry);entry[offset] = value
            variants.append(('texture-' + str(offset), self.sections + [struct.pack('<II', 1, 8) + entry]))
        for count in (1, 3):
            entry = texture(14, self.palettes[:1] if count == 1 else self.palettes + [self.palettes[0]], self.indices, 128, 128, b'\x6c\0\0\x02')
            variants.append(('palette-count-' + str(count), self.sections + [struct.pack('<II', 1, 8) + entry]))
        entry = texture(14, self.palettes, self.indices[:8192], 64, 128, b'\x6c\0\0\x02')
        variants.append(('dimensions', self.sections + [struct.pack('<II', 1, 8) + entry]))
        variants.append(('texture-count', self.sections + [obf.build_table([self.entry, self.entry])]))
        for offset, value in ((0, 1), (4, 13), (12 + 4, 1), (12 + 0x23, 1), (72 + 0x23, 1)):
            sections = list(self.sections);mesh = bytearray(sections[7]);mesh[offset] = value;sections[7] = bytes(mesh)
            variants.append(('material-' + str(offset), sections + [struct.pack('<II', 1, 8) + self.entry]))
        for name, sections in variants:
            source = self.container(sections)
            with self.subTest(name=name), self.sealed(source), self.assertRaises(ValueError):
                fx.convert_obf(source, effect71_two_frames=True)

    def test_receiver_mismatch_never_returns_a_candidate(self):
        with self.sealed(), patch.object(fx, 'EFFECT71_TARGET_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'reviewed offline carrier fingerprint'):
                fx.convert_obf(self.source, effect71_two_frames=True)


class PaletteFrameTests(unittest.TestCase):
    """Independent scalar pixels for synthetic indexed4/8 multi-frame cases."""

    def entry(self, fmt=10, width=32, height=32, count=2, attr=b'\x6c\0\0\x02'):
        colors = 16 if fmt == 10 else 256
        palettes = [b''.join(bytes(((i+p*11)%256, (255-i+p)%256,
                                    (i*3+p*17)%256, (i*7+p*23)%256))
                             for i in range(colors)) for p in range(count)]
        indices = bytes((x*3+y*5)%colors for y in range(height) for x in range(width))
        pixels = bytes(indices[i] | indices[i+1]<<4 for i in range(0,len(indices),2)) if fmt==10 else indices
        expected = tuple(b''.join(bytes((palette[i*4+2],palette[i*4+1],palette[i*4],palette[i*4+3]))
                                  for i in indices) for palette in palettes)
        return texture(fmt,palettes,pixels,width,height,attr), expected

    def container(self, entries, trailer=b'', meshes=None):
        if meshes is None:
            meshes = []
            for index in range(len(entries)):
                mesh = bytearray(60);struct.pack_into('<II',mesh,0,index*3+3,index)
                mesh[11],mesh[0x22] = 255,2
                meshes.append(bytes(mesh))
        sections = [bytes((i,))*4 for i in range(9)]
        sections[7] = obf.build_table(meshes)
        sections.append(obf.build_table(entries))
        return Effect71OptInTests.container(sections,trailer)

    def assert_pixels(self, target, expected, report):
        w,h = report['width'],report['height']
        self.assertEqual(target[:4],b'\x6c\0\0\0')
        self.assertEqual(target[4:8],b'\0\1\1\1')
        self.assertEqual(struct.unpack_from('>HHII',target,8),(w,h,0x10000,w*h*4*len(expected)))
        self.assertEqual(len(target),20+w*h*4*len(expected))
        for i,pixels in enumerate(expected):
            frame = target[20+i*w*h*4:20+(i+1)*w*h*4]
            rgba = b''.join(bytes((frame[p+1],frame[p+2],frame[p+3],frame[p])) for p in range(0,len(frame),4))
            self.assertEqual(rgba,pixels)
            self.assertEqual(report['frames'][i]['rgba_sha256'],hashlib.sha256(pixels).hexdigest())
            self.assertEqual(report['frames'][i]['source_palette_index'],i)

    def test_all_bounded_layouts_match_scalar_pixels_and_frame_order(self):
        layouts = ((14,64,64,2),(14,128,128,2),(10,32,32,2),(10,16,16,2),
                   (14,64,64,3),(10,32,32,3),(10,32,64,3),(10,64,64,3),
                   (14,32,32,2),(10,64,64,2),(10,32,32,16),(14,16,16,2))
        for fmt,w,h,n in layouts:
            with self.subTest(layout=(fmt,w,h,n)):
                entry,expected=self.entry(fmt,w,h,n)
                target,report=fx.convert_texture(entry,palette_frames=True)
                self.assert_pixels(target,expected,report)
                self.assertEqual(len(report['source_palette_sha256']),n)
                self.assertIs(report['resource_ready'],False)

    def test_multiple_entries_preserve_materials_sections_attributes_and_trailer(self):
        first,e0=self.entry();second,e1=self.entry(14,64,64,3)
        for trailer in (b'',bytes(13),b'opaque\0\xff'):
            source=self.container([first,second],trailer)
            target,report=fx.convert_obf(source,palette_frames=True)
            a,b=obf.ObfFile(source),obf.ObfFile(target)
            self.assertEqual(a.sections[:9],b.sections[:9]);self.assertEqual(a.trailer,b.trailer)
            entries=obf.read_table(b.sections[9])
            self.assert_pixels(entries[0],e0,report['textures'][0])
            self.assert_pixels(entries[1],e1,report['textures'][1])
            self.assertTrue(report['trailer_exact']);self.assertFalse(report['resource_ready'])
            self.assertEqual(report['status'],'partial-offline')

    def test_default_refusal_and_sealed_case_are_separate(self):
        entry,_=self.entry();source=self.container([entry])
        with self.assertRaisesRegex(fx.UnsupportedEffect,'palette variants'):fx.convert_obf(source)
        with self.assertRaisesRegex(fx.UnsupportedEffect,'fingerprint'):fx.convert_obf(source,effect71_two_frames=True)
        with self.assertRaisesRegex(ValueError,'choose'):fx.convert_obf(source,effect71_two_frames=True,palette_frames=True)
        for value in (None,1,'yes'):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'explicit bool'):
                fx.convert_obf(source,palette_frames=value)

    def test_unreviewed_layouts_and_attributes_are_refused(self):
        for fmt,w,h,count,attrs in ((14,128,64,2,b'\x6c\0\0\x02'),
                                   (10,32,32,4,b'\x6c\0\0\x02'),
                                   (10,32,32,2,b'\x6b\0\0\x02'),
                                   (10,32,32,2,b'\x6c\1\0\x02'),
                                   (10,32,32,2,b'\x6c\0\2\x02')):
            entry,_=self.entry(fmt,w,h,count,attrs)
            with self.subTest(case=(fmt,w,h,count,attrs)),self.assertRaises(fx.UnsupportedEffect):
                fx.convert_obf(self.container([entry]),palette_frames=True)

    def test_animated_foreign_and_unproved_materials_are_refused(self):
        entry,_=self.entry();mesh=bytearray(60);mesh[0x22]=2
        for offset,value in ((4,1),(0x22,1),(0x23,1)):
            changed=bytearray(mesh);changed[offset]=value
            with self.subTest(offset=offset),self.assertRaises(fx.UnsupportedEffect):
                fx.convert_obf(self.container([entry],meshes=[bytes(changed)]),palette_frames=True)
        for record in (bytes(mesh[:59]),bytes(mesh)+b'\0'):
            with self.assertRaises(fx.UnsupportedEffect):
                fx.convert_obf(self.container([entry],meshes=[record]),palette_frames=True)

    def test_noncanonical_texture_and_material_tables_are_refused(self):
        entry,_=self.entry();source=self.container([entry])
        for section in (7,9):
            parts=list(obf.ObfFile(source).sections)
            for field,value in ((0,0),(4,0),(4,99999999)):
                bad=bytearray(parts[section]);struct.pack_into('<I',bad,field,value)
                changed=list(parts);changed[section]=bytes(bad)
                malformed=Effect71OptInTests.container(changed)
                with self.subTest(section=section,field=field,value=value),self.assertRaises(fx.UnsupportedEffect):
                    fx.convert_obf(malformed,palette_frames=True)


if __name__ == '__main__':
    unittest.main()
