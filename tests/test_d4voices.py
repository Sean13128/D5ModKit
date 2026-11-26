"""D4 voice interpretation and malformed-source checks using synthetic bytes only."""
import contextlib
import io
import struct
import tempfile
import types
import unittest
import wave
from pathlib import Path

from d5lib import d4source, fafs, d4voices, modsys, voices
from tools import d4_inspect


def row(line=101, group=10, rate=30050, categories=(0, 11), gain=100.):
    flags = [2 if i in categories else 0 for i in range(12)]  # native tests nonzero, not ==1
    return struct.pack('<IIfi12I', line, group, gain, rate, *flags)


def table(*rows):
    return struct.pack('<III', 64, len(rows), 0) + b''.join(rows)


def wrapped(riff=None):
    if riff is None:
        b = io.BytesIO()
        with wave.open(b, 'wb') as w:
            w.setparams((1, 2, 22112, 0, 'NONE', 'not compressed'))
            w.writeframes(bytes(32))
        riff = b.getvalue()
    return struct.pack('<7I', 5, len(riff), 22050, 16, 0, len(riff), 0) + riff


def archive(entries):
    """Minimal real FAFS container; entries may deliberately repeat a name/line."""
    names, index, body = bytearray(), bytearray(), bytearray()
    payload_at = 0x200 + len(entries) * 48 + sum(len(name) + 1 for name, data in entries)
    for name, data in entries:
        index += struct.pack('<6Q', fafs.name_hash(name), len(names), 0, len(data), payload_at + len(body), 0)
        names += name.encode('ascii') + b'\0'
        body += data
    header = bytearray(0x200)
    header[:8] = fafs.MAGIC
    struct.pack_into('<I', header, 8, len(entries))
    struct.pack_into('<QQQ', header, 0x10, 0x200 + len(index), len(names), 0x200)
    return bytes(header + index + names + body)


class VoiceSchemaTests(unittest.TestCase):
    def test_rate_is_separate_from_native_category_zero_and_last(self):
        decoded = d4source.decode_voice_table(table(row()))[101]
        self.assertEqual(decoded['native_rate_input_signed'], 30050)
        self.assertEqual(decoded['native_active_categories'], [0, 11])
        self.assertEqual(decoded['native_category_flags'], [2] + [0] * 10 + [2])
        self.assertEqual(decoded['legacy_raw_dwords'], [30050, 2] + [0] * 10 + [2])
        self.assertEqual(decoded['flags'], [0, 1, 12])
        self.assertEqual(decoded['legacy_flags'], decoded['flags'])
        self.assertIn('not an event', decoded['flags_semantics'])

    def test_signed_rate_and_no_category_keeps_legacy_interface(self):
        decoded = d4source.decode_voice_table(table(row(rate=-123, categories=())))[101]
        self.assertEqual(decoded['native_rate_input_signed'], -123)
        self.assertEqual(decoded['legacy_raw_dwords'][0], 2**32 - 123)
        self.assertEqual(decoded['flags'], [0])
        self.assertEqual(decoded['native_active_categories'], [])

    def test_table_stride_count_extent_and_duplicate_ids(self):
        good = table(row())
        cases = [b'', good[:11], good[:-1], good + b'\0', table(row(), row())]
        for offset, value in ((0, 60), (4, 0), (4, 2)):
            bad = bytearray(good)
            struct.pack_into('<I', bad, offset, value)
            cases.append(bytes(bad))
        for bad in cases:
            with self.subTest(bytes=len(bad)), self.assertRaises(ValueError):
                d4source.decode_voice_table(bad)

    def test_nonfinite_gain_rejected_without_changing_raw_finite_gain(self):
        for gain in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                d4source.decode_voice_table(table(row(gain=gain)))
        self.assertAlmostEqual(d4source.decode_voice_table(table(row(gain=12.25)))[101]['volume_raw'], 12.25)

    def test_wrapper_and_riff_rates_remain_distinct(self):
        raw = wrapped()
        parsed = d4source.decode_voice_member(raw)
        self.assertEqual(parsed['riff'], raw[28:])
        self.assertEqual(parsed['wrapper_hex'], raw[:28].hex())
        self.assertEqual(parsed['wrapper_u32'][2], 22050)
        self.assertEqual(parsed['riff_sample_rate'], 22112)

    def test_bad_wrapper_and_riff_extents_rejected(self):
        good = wrapped()
        cases = [good[:39], good[:-1], good + b'\0', good[:28] + b'JUNK' + good[32:]]
        for offset, value in ((0, 4), (4, 0), (8, 0), (16, 1), (20, 0), (24, 1), (32, 0)):
            bad = bytearray(good)
            struct.pack_into('<I', bad, offset, value)
            cases.append(bytes(bad))
        for bad in cases:
            with self.subTest(bytes=len(bad)), self.assertRaises(ValueError):
                d4source.decode_voice_member(bad)

    def test_duplicate_missing_and_truncated_riff_chunks(self):
        riff = wrapped()[28:]
        for body in (riff[12:36] * 2 + riff[36:], riff[12:36], riff[12:] + b'X'):
            bad = b'RIFF' + struct.pack('<I', len(body) + 4) + b'WAVE' + body
            with self.assertRaises(ValueError):
                d4source.decode_voice_member(wrapped(bad))


class VoiceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'd4'
        self.reader = object.__new__(d4source.D4Data)
        self.reader.root, self.reader.lang = self.root, 'EN'

    def tearDown(self):
        self.tmp.cleanup()

    def sources(self, rows, entries):
        for rel, data in ((d4source.VOICE_TABLE, table(*rows)), (d4source.VOICE_PACK, archive(entries))):
            path = self.root / rel.format(lang='EN')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_real_archive_returns_exact_riff_and_sorted_identifiers(self):
        raw = wrapped()
        self.sources([row(102), row()], [('en/10/voice_102.nlsd', raw), ('en/10/voice_101.nlsd', raw)])
        lines = self.reader.voice_lines({10})
        self.assertEqual([x['line'] for x in lines], [101, 102])
        self.assertEqual([x['riff'] for x in lines], [raw[28:], raw[28:]])

    def test_archive_missing_table_line_and_group_mismatch_rejected(self):
        for rows, name in (([row()], 'en/10/voice_102.nlsd'), ([row(group=11), row(102)], 'en/10/voice_101.nlsd')):
            self.sources(rows, [(name, wrapped())])
            with self.assertRaises(ValueError):
                self.reader.voice_lines({10})

    def test_missing_audio_and_absent_requested_group_rejected(self):
        self.sources([row(), row(102)], [('en/10/voice_101.nlsd', wrapped())])
        with self.assertRaisesRegex(ValueError, 'missing audio'):
            self.reader.voice_lines({10})
        with self.assertRaisesRegex(ValueError, 'absent from table'):
            self.reader.voice_lines({11})

    def test_duplicate_archive_line_and_malformed_member_rejected(self):
        for names in (['en/10/voice_101.nlsd'] * 2, ['jp/10/voice_101.nlsd'], ['en/10/not-a-voice']):
            self.sources([row()], [(n, wrapped()) for n in names])
            with self.assertRaises(ValueError):
                self.reader.voice_lines({10})

    def test_truncated_archive_member_rejected(self):
        self.sources([row()], [('en/10/voice_101.nlsd', wrapped())])
        path = self.root / d4source.VOICE_PACK.format(lang='EN')
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'truncated.*member'):
            self.reader.voice_lines({10})

    def test_inspector_exports_and_displays_corrected_categories(self):
        self.sources([row()], [('en/10/voice_101.nlsd', wrapped())])
        dest = Path(self.tmp.name) / 'export'
        args = types.SimpleNamespace(groups=[10], export=dest, json=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            d4_inspect.cmd_voice(self.reader, {}, args)
        self.assertIn('native categories [0, 11] rate input 30050 legacy raw flags [0, 1, 12]', buf.getvalue())
        self.assertEqual([p.name for p in dest.iterdir()], ['101_p0_c0-11.wav'])
        with wave.open(str(next(dest.iterdir())), 'rb') as wav:
            self.assertEqual(wav.getframerate(), 22112)
        with self.assertRaisesRegex(ValueError, 'new directory'):
            d4_inspect.cmd_voice(self.reader, {}, args)

    def test_inspector_protected_exports_refused_before_source_read(self):
        args = types.SimpleNamespace(groups=[10], export=self.root / 'bad', json=False)
        with self.assertRaisesRegex(ValueError, 'protected input'):
            d4_inspect.cmd_voice(self.reader, {}, args)


class VoiceImportTests(unittest.TestCase):
    def clips(self):
        import numpy as np
        a=(np.sin(np.arange(1200)*0.17)*30000).astype('<i2')
        b=io.BytesIO()
        with wave.open(b,'wb') as w:
            w.setparams((1,2,22050,0,'NONE','not compressed'));w.writeframes(a.tobytes())
        return [dict(line=i+1,group=100+p,volume_raw=150.,native_active_categories=cats,
                     native_category_flags=[int(c in cats) for c in range(12)],
                     native_rate_input_signed=0,table_row_index=i,riff=b.getvalue())
                for i,(p,cats) in enumerate([(0,[0,11]),(1,[5]),(2,[]),(2,[3,11])])]

    def test_conversion_preserves_personality_and_accounts_every_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod=modsys.Mod(tmp);source=types.SimpleNamespace(lang='EN',voice_lines=lambda g:self.clips())
            r=d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map())
            self.assertEqual(len(r['clips']),4)
            good=[x for x in r['clips'] if x['status']=='converted-adapted']
            self.assertEqual([x['personality'] for x in good],[0,1])
            self.assertTrue(all(x['output_rate']==48000 and x['output_peak']<=0.85001 for x in good))
            self.assertTrue(all(x.get('reason') for x in r['clips'] if x['status']=='unrouted-placeholder'))
            self.assertTrue(all('source_row_sha256' in x and 'source_uid' in x for x in r['clips']))
            registered=voices.load(mod)['voices']['9000']['lines']
            self.assertEqual([x['personality'] for x in registered],[0,1])
            rows=voices.custom_lines(9000,voices.load(mod)['voices']['9000'])
            self.assertEqual([voices.split_set(x.group)[2] for x,_ in rows],[0,1])

    def test_bad_lease_groups_and_gain_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod=modsys.Mod(tmp);source=types.SimpleNamespace(voice_lines=lambda g:self.clips())
            for args in [dict(voice_id=9000,groups=[100,100]),dict(voice_id=9000,groups=[100,101,102,103]),
                         dict(voice_id=9000,groups=[100],occupied_ids=[9000])]:
                with self.assertRaises(ValueError):
                    d4voices.import_d4_voice(mod,source,event_map=d4voices.basic_event_map(),**args)
            bad=self.clips()[0];bad['volume_raw']=-1
            source.voice_lines=lambda g:[bad]
            with self.assertRaisesRegex(ValueError,'gain'):
                d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100],event_map=d4voices.basic_event_map())

    def test_explicit_dual_locale_files_handler_preview_and_export(self):
        import json
        import zipfile
        from d5lib import modshare
        with tempfile.TemporaryDirectory() as tmp:
            mod=modsys.Mod(str(Path(tmp)/'native'));mod.save_meta()
            clips=self.clips()
            for lang,scale in [('EN',1),('JP',-1)]:
                selected=[]
                for clip in clips:
                    clip=dict(clip)
                    if scale<0:
                        # Distinct genuine synthetic PCM, no language inference from content.
                        b=io.BytesIO()
                        with wave.open(b,'wb')as w:
                            w.setparams((1,2,22050,0,'NONE','not compressed'));w.writeframes(struct.pack('<1200h',*([-1000]*1200)))
                        clip['riff']=b.getvalue()
                    selected.append(clip)
                source=types.SimpleNamespace(lang=lang,voice_lines=lambda g,items=selected:items)
                receipt=d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map(),source_language=lang,destination_language=lang)
                self.assertEqual(receipt['source_language'],lang)
            data=voices.load(mod);voice=data['voices']['9000'];self.assertEqual(len(voice['lines']),4)
            self.assertTrue(all(Path(voices.folder(mod),name).is_file()for line in voice['lines']for name in line['files'].values()))
            class Context:
                def __init__(self):self.outputs={}
                def get(self,path):return voices.write_table([voices.Line(1,1,cats=[0])])
                def put(self,path,data):self.outputs[path]=data
                def log(self,text):pass
            ctx=Context();voices._handler(ctx,mod,voices.folder(mod))
            for lang in ('EN','JP'):
                rows=voices.custom_lines(9000,voice,lang=lang);self.assertEqual(len(rows),2)
                bank=voices.VoiceBank(None,[mod],lang=lang,get=lambda path:voices.write_table([]))
                self.assertEqual(bank._raw(rows[0][0].id),Path(voices.folder(mod),rows[0][1][1]).read_bytes())
                path=f'{voices.ARCHIVE}/{voices.PREFIX[lang]}/{rows[0][0].group:06d}.dat'
                packed=fafs.pack_members(ctx.outputs[path]);self.assertEqual(next(iter(packed.values())),bank._raw(rows[0][0].id))
            en=voices.custom_lines(9000,voice,lang='EN')[0][1][1];jp=voices.custom_lines(9000,voice,lang='JP')[0][1][1]
            self.assertNotEqual(Path(voices.folder(mod),en).read_bytes(),Path(voices.folder(mod),jp).read_bytes())
            archive=Path(tmp)/'synthetic.zip';modshare.export_package(mod,str(archive))
            with zipfile.ZipFile(archive)as z:
                member=next(n for n in z.namelist()if n.endswith('patches/voices/voices.json'))
                self.assertEqual(json.loads(z.read(member)),voices.load(mod))

    def test_locale_silence_fallback_and_legacy_defaults_are_explicit(self):
        legacy=dict(lines=[dict(file='one.vag',kind=0,cats=[0])])
        self.assertEqual([(row.pack(),ref)for row,ref in voices.custom_lines(9000,legacy,lang='EN')],
                         [(row.pack(),ref)for row,ref in voices.custom_lines(9000,legacy,lang='JP')])
        v=dict(lines=[dict(files={'EN':'en.vag'},kind=0,cats=[0],missing_locale='silence')])
        self.assertEqual(voices.custom_lines(9000,v,lang='JP'),[])
        v['lines'][0]['fallback_language']='EN'
        self.assertEqual(voices.custom_lines(9000,v,lang='JP')[0][1],('file','en.vag'))
        del v['lines'][0]['fallback_language'];del v['lines'][0]['missing_locale']
        with self.assertRaisesRegex(ValueError,'requires explicit'):voices.custom_lines(9000,v,lang='JP')
        v['lines'][0]['files']={'EN':'../escape.vag'}
        with self.assertRaisesRegex(ValueError,'Invalid explicit'):voices.custom_lines(9000,v,lang='EN')

    def test_jp_source_override_uses_sound_reader_without_jp_character_database(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory()as tmp:
            mod=modsys.Mod(tmp);source=types.SimpleNamespace(lang='EN',root=Path(tmp))
            with patch.object(d4source.D4Data,'voice_lines',autospec=True,return_value=self.clips())as read:
                r=d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map(),source_language='JP',destination_language='JP')
            self.assertEqual(read.call_args.args[0].lang,'JP')
            self.assertEqual(read.call_args.args[0].root,source.root)
            self.assertEqual(r['source_language'],'JP')

    def test_locale_reimport_preserves_other_half_of_combined_record(self):
        with tempfile.TemporaryDirectory()as tmp:
            mod=modsys.Mod(tmp);source=types.SimpleNamespace(lang='EN',voice_lines=lambda g:self.clips())
            args=dict(voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map())
            d4voices.import_d4_voice(mod,source,**args,destination_language='EN')
            data=voices.load(mod);original=data['voices']['9000']
            for line in original['lines']:
                en=line['files']['EN'];jp=en.replace('_EN.vag','_JP.vag')
                Path(voices.folder(mod),jp).write_bytes(Path(voices.folder(mod),en).read_bytes())
                line['files']['JP']=jp
            voices.save(mod,data)
            before=[(row.pack(),ref,Path(voices.folder(mod),ref[1]).read_bytes())for row,ref in voices.custom_lines(9000,original,lang='EN')]
            source.lang='JP'
            d4voices.import_d4_voice(mod,source,**args,destination_language='JP')
            after=voices.load(mod)['voices']['9000']
            self.assertEqual(before,[(row.pack(),ref,Path(voices.folder(mod),ref[1]).read_bytes())for row,ref in voices.custom_lines(9000,after,lang='EN')])
            self.assertEqual(len(voices.custom_lines(9000,after,lang='JP')),2)

    def test_invalid_locale_save_cannot_replace_config_or_delete_recordings(self):
        import copy
        with tempfile.TemporaryDirectory()as tmp:
            mod=modsys.Mod(tmp);source=types.SimpleNamespace(lang='EN',voice_lines=lambda g:self.clips())
            d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map(),destination_language='EN')
            data=voices.load(mod);directory=Path(voices.folder(mod));before={p.name:p.read_bytes()for p in directory.iterdir()}
            for mutation in [dict(file='other.vag'),dict(src=1),dict(fallback_language='JP'),dict(fallback_language=[]),dict(missing_locale='guess')]:
                bad=copy.deepcopy(data);bad['voices']['9000']['lines'][0].update(mutation)
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):voices.save(mod,bad)
                self.assertEqual(before,{p.name:p.read_bytes()for p in directory.iterdir()})
            bad=copy.deepcopy(data);bad['voices']['9000']['lines'][0].update(files={'EN':'one.vag','JP':'two.vag'},fallback_language='KR')
            for lang in ('EN','JP'):
                with self.assertRaisesRegex(ValueError,'fallback'):voices.custom_lines(9000,bad['voices']['9000'],lang=lang)
            with self.assertRaises(ValueError):voices.save(mod,bad)
            self.assertEqual(before,{p.name:p.read_bytes()for p in directory.iterdir()})

    def test_locale_mismatch_and_legacy_mix_refused(self):
        with tempfile.TemporaryDirectory()as tmp:
            mod=modsys.Mod(tmp);source=types.SimpleNamespace(lang='EN',voice_lines=lambda g:self.clips())
            with self.assertRaisesRegex(ValueError,'matching source'):
                d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map(),destination_language='JP')
            d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map())
            with self.assertRaisesRegex(ValueError,'mix legacy'):
                d4voices.import_d4_voice(mod,source,voice_id=9000,groups=[100,101,102],event_map=d4voices.basic_event_map(),destination_language='EN')

    def test_preview_bucket_is_not_silently_routed_as_battle(self):
        self.assertNotIn('11',d4voices.basic_event_map())
        self.assertEqual(d4voices.basic_event_map()['5'][0]['cats'],[10])


if __name__ == '__main__':
    unittest.main()
