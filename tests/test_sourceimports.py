"""No game data: bounded prepared-art input contract."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest


class SourceImportTests(unittest.TestCase):
    def test_simple_voice_conversion_bakes_gain_preserves_personality_and_records_unrouted(self):
        import io
        import wave
        import numpy as np
        from unittest.mock import Mock, patch
        from d5lib import modsys, sfx, sourceimports, voices
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as stream:
            stream.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            stream.writeframes(np.full(1024, 16384, dtype='<i2').tobytes())
        source = Mock()
        source.voice_lines.return_value = [dict(line=1, group=1081, native_active_categories=[5],
            volume_raw=200, riff=wav.getvalue()), dict(line=2, group=1080, native_active_categories=[11],
            volume_raw=100, riff=wav.getvalue())]
        encoded_inputs = []
        real_encode = sfx.make_vag
        def encode_fixture(pcm, rate, **options):
            encoded_inputs.append(pcm.copy())
            return real_encode(pcm, rate, **options)
        with tempfile.TemporaryDirectory() as td:
            mod = modsys.Mod(str(Path(td) / 'Voice'))
            with patch.object(sfx, 'make_vag', side_effect=encode_fixture) as encode:
                result = sourceimports.import_d4_voice(mod, source, voice_id=9000, groups=[1080,1081,1082],
                    event_map={'5': [dict(kind=0, cats=[10])]})
                self.assertAlmostEqual(float(encoded_inputs[0].max()), 0.85, places=6)
                self.assertEqual(encode.call_args.kwargs, dict(normalize=False, trim=False))
                self.assertEqual(result['clips'][0]['output_rate'], 48000)
                self.assertLessEqual(result['clips'][0]['output_peak'], 0.85001)
            voice = voices.load(mod)['voices']['9000']
            self.assertEqual(voice['lines'][0]['personality'], 1)
            self.assertEqual(voice['lines'][0]['cats'], [10])
            self.assertEqual(result['clips'][1]['status'], 'unrouted-placeholder')
            self.assertFalse(result['native_tested'])
            with self.assertRaisesRegex(ValueError, 'free custom voice'):
                sourceimports.import_d4_voice(mod, source, voice_id=9000, groups=[1080], event_map={}, occupied_ids=[9000])

    def test_mapping_completion_preserves_reviewed_choices_and_marks_every_gap(self):
        from d5lib import sourceimports
        mapping = dict(schema=1, game='d4', evilities={'42': dict(d4_name='Fixture', relation='adapted', works_like=12)})
        items = [dict(kind=kind, source_id=sid, uid=f'{kind}:{sid}', data=dict(name='Fixture'),
                      source=dict(sha256='a' * 64)) for kind, sid in [('evility', 42), ('skill', 99)]]
        inventory = dict(schema='d4-content-inventory/1', items=items)
        result = sourceimports.complete_d4_mapping(inventory, mapping)
        self.assertEqual(result['evilities']['42']['works_like'], 12)
        self.assertEqual(result['skills']['99']['relation'], 'placeholder')
        self.assertIn('[Unavailable D4]', result['skills']['99']['display_name'])
        self.assertNotIn('copy_of', result['skills']['99'])
        self.assertNotIn('skills', mapping)
        inventory['items'].append(items[0])
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            sourceimports.complete_d4_mapping(inventory, mapping)

    def test_read_prepared_preserves_source_identity_and_hashes(self):
        from d5lib import sourceimports
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            art = root / 'art'
            art.mkdir()
            library = root / 'library'
            (library / 'bodies').mkdir(parents=True)
            body = b'fixture-source-body-not-game-data'
            sha = hashlib.sha256(body).hexdigest()
            (library / 'bodies' / (sha + '.bin')).write_bytes(body)
            (library / 'art-manifest.json').write_text(json.dumps({
                'format': 'character-forge-art/1', 'source': 'd4',
                'characters': [{'id': 1080, 'body': 1080, 'name': 'Armor Knight'}],
                'bodies': {'1080': {'sha256': sha, 'bytes': len(body)},
                           '1': {'sha256': sha, 'bytes': len(body)}}}))
            Image.new('RGBA', (4, 5), (10, 20, 30, 255)).save(art / 'stand.png')
            (art / 'manifest.json').write_text(json.dumps({
                'source': 'd4', 'character_id': 1080, 'palette': 0,
                'body_sha256': sha, 'common_sha256': sha,
                'bundles': [{'label': 'front', 'sprites': [
                    {'name': 'stand', 'png': 'stand.png', 'decoded_size': [4, 5]}]}]}))
            result = sourceimports.read_prepared(art, library, edition='Disgaea 4 Complete+')
            self.assertEqual(result['identity']['name'], 'Armor Knight')
            self.assertEqual(result['identity']['body_sha256'], sha)
            self.assertEqual(result['sequences'][('stand', 'front')][0].size, (4, 5))
            self.assertEqual(len(result['evidence']['images']), 1)
            # A larger drawing retains the smaller original source canvas and its pivot.
            manifest_path = art / 'manifest.json'
            canvas_manifest = json.loads(manifest_path.read_text())
            canvas_manifest['bundles'][0]['sprites'][0]['canvas'] = [3, 2, 1, 1]
            manifest_path.write_text(json.dumps(canvas_manifest))
            framed = sourceimports.read_prepared(art, library, edition='D4 Complete+')
            image, canvas = framed['sequences'][('stand', 'front')][0]
            self.assertEqual((image.size, canvas), ((4, 5), (3, 2, 1, 1)))
            canvas_manifest['bundles'][0]['sprites'][0]['canvas'] = [5, 4, 1, 0]
            manifest_path.write_text(json.dumps(canvas_manifest))
            with self.assertRaisesRegex(ValueError, 'Invalid source canvas'):
                sourceimports.read_prepared(art, library, edition='D4 Complete+')
            canvas_manifest['bundles'][0]['sprites'][0].pop('canvas')
            manifest_path.write_text(json.dumps(canvas_manifest))
            # Negative controls: identity is from the library, never the prepared display name.
            manifest_path = art / 'manifest.json'
            original = json.loads(manifest_path.read_text())
            for field, value in [('source', 'd2'), ('body_sha256', '0' * 64),
                                 ('character_id', 9999)]:
                changed = dict(original, **{field: value})
                manifest_path.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    sourceimports.read_prepared(art, library, edition='D4 Complete+')
            manifest_path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                sourceimports.read_prepared(art, library, edition='')
            (library / 'bodies' / (sha + '.bin')).write_bytes(b'corrupted')
            with self.assertRaises(ValueError):
                sourceimports.read_prepared(art, library, edition='D4 Complete+')
            (library / 'bodies' / (sha + '.bin')).write_bytes(body)
            for relative in ['../stand.png', '/stand.png']:
                changed = json.loads(json.dumps(original))
                changed['bundles'][0]['sprites'][0]['png'] = relative
                manifest_path.write_text(json.dumps(changed))
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    sourceimports.read_prepared(art, library, edition='D4 Complete+')
            outside = root / 'outside.png'
            Image.new('RGBA', (4, 5), (1, 2, 3, 255)).save(outside)
            (art / 'linked.png').symlink_to(outside)
            changed = json.loads(json.dumps(original))
            changed['bundles'][0]['sprites'][0]['png'] = 'linked.png'
            manifest_path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                sourceimports.read_prepared(art, library, edition='D4 Complete+')


class SourceStatsTests(unittest.TestCase):
    def archive(self, path, ids):
        import struct
        table = bytearray(struct.pack('<I', len(ids)))
        for k, cid in enumerate(ids):
            row = bytearray(684)
            struct.pack_into('<8H', row, 4, *range(10 + k, 18 + k))
            struct.pack_into('<H', row, 0x194, cid)
            struct.pack_into('<H', row, 0x1BA, 1080)
            row[0x1FE:0x1FE + 7] = b'Fixture'
            row[0x23E:0x23E + 6] = b'Rank ' + str(k).encode()
            row[0x27E:0x286] = bytes(range(100 + k, 108 + k))
            table.extend(row)
        name = b'char.dat\0'
        start = 28 + 10 + 10 + len(name)
        header = struct.pack('<4sHH5I', b'NSAC', 2, 1, start + len(table), start, 10, 10 + len(name), 0)
        path.write_bytes(header + struct.pack('<HII', 0, start, len(table)) +
                         struct.pack('<HII', len(name) - 1, start, len(table)) + name + table)

    def test_orchestration_rejects_unapproved_ids_before_any_output(self):
        from d5lib import sourceimports
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for family, allowed in [(1350, []), (99999, [99999]), (True, [True])]:
                with self.subTest(family=family), self.assertRaises(ValueError):
                    sourceimports.build_d4_pilot(
                        prepared_root=root / 'prepared', library_root=root / 'library',
                        source_archive=root / 'DATABASE_EN.dat', game_path=root / 'game',
                        face_path=root / 'face.png', cutin_path=root / 'cutin.png',
                        output_path=root / 'out', family=family, template=1150,
                        supported_families=allowed, source_ids=list(range(1080, 1086)),
                        edition='D4 fixture EN')
                self.assertFalse((root / 'out').exists())

    def test_bounded_d4_archive_ranks_and_missing_fail_closed(self):
        from d5lib import sourceimports
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'DATABASE_EN.dat'
            ids = list(range(1080, 1086))
            self.archive(p, ids)
            ranks = sourceimports.read_d4_ranks(p, source_ids=ids, edition='D4 fixture EN')
            self.assertEqual(len(ranks), 6)
            self.assertEqual(ranks[0]['base'], [10, 11, 12, 13, 14, 17, 16, 15])
            self.assertEqual(ranks[5]['aptitudes'], [105, 106, 107, 108, 109, 112, 111, 110])
            self.assertEqual(ranks[0]['evidence']['member_offset'], 57)
            self.assertEqual(ranks[5]['body'], 1080)
            for bad in [ids[:-1], ids[:-1] + [999], ids[:-1] + [1080]]:
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    sourceimports.read_d4_ranks(p, source_ids=bad, edition='D4 fixture EN')
            self.archive(p, ids[:-1])
            with self.assertRaises(ValueError):
                sourceimports.read_d4_ranks(p, source_ids=ids, edition='D4 fixture EN')
            self.archive(p, ids)
            p.write_bytes(p.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                sourceimports.read_d4_ranks(p, source_ids=ids, edition='D4 fixture EN')


if __name__ == '__main__':
    unittest.main()
