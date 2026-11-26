"""Synthetic integration preflight; no game assets or gameplay claims."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from d5lib import d4expansion as exp, d4unique, database, modsys


def raw_table(name, fields=()):
    schema = database.get_schema(name)
    t = database.load_table(name, bytes(schema.header_size))
    for values in fields:
        r = t.new_row()
        for k, v in values.items():
            r.set(k, v)
        t.rows.append(r)
    return t.to_bytes()


class FS:
    def __init__(self):
        self.data = {exp.DB + name: raw_table(name, fields) for name, fields in (
            ('char.dat', [{'id': 10, 'name_EN': 'Original'}]),
            ('Quest.dat', [{'id': 1, 'sort_order': 0}]),
            ('charhelp.dat', [{'id': 10, 'char_id': 10}]),
            ('magic.dat', [{'id': 10571}]), ('Skill.dat', []), ('charPersonal.dat', [{'id': 131}]))}

    def read(self, name):
        return self.data[name]

    get = read


class ExpansionTests(unittest.TestCase):
    def test_unique_help_leases_preserve_class_and_disabled_claims(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);generic,disabled,a,b=[self.mod(root,n) for n in ('Generic','Disabled','A','B')]
            generic.save_patch('db','charhelp.dat.json',{'added':[{'id':14560,'char_id':14560}]})
            disabled.save_patch('db','charhelp.dat.json',{'added':[{'id':16000,'char_id':16000}]})
            before=exp.snapshot(generic)
            for mod,cid,sid in ((a,223,70),(b,226,170)):
                mod.meta['source_import']={'source_id':sid};mod.save_meta()
                mod.save_patch('db','charhelp.dat.json',{'added':[{'id':14560,'char_id':14560,'line1_EN':'Source'}]})
                mod.save_patch('db','char.dat.json',{'added':[{'id':cid,'help_id':14560}]})
            changes=exp.lease_unique_help_rows(FS(),[generic,a,b],[disabled])
            self.assertEqual([r['new'] for r in changes['changes']],[16001,16002])
            self.assertEqual(a.load_patch('db','char.dat.json')['added'][0]['help_id'],16001)
            self.assertEqual(b.load_patch('db','charhelp.dat.json')['added'][0]['char_id'],16002)
            self.assertEqual(exp.snapshot(generic),before)
            self.assertTrue(all(r['native_serialized_readback']for r in changes['changes']))

    def test_body_overlay_changes_only_owned_pair_in_staged_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);staged=self.mod(root,'Source');staged.meta['source_import']={'identity':{'character_id':1010}};staged.save_meta()
            staged.save_patch('classes','class_14010.json',dict(family=14010,template=1010,kind='humanoid',sprite_family=1270))
            overlay=root/'overlay';source=modsys.Mod(str(overlay/'native-mods'/'Source'));source.save_meta()
            for n in (1270,1271):
                vp=f'Anime/ANM_HI_JP.dat/anm{n:05d}.lzs';staged.write_file(vp,b'old');source.write_file(vp,b'new')
            source.save_patch('db','char.dat.json',{'added':[{'id':999}]})
            receipt=dict(source_ranks=[{'id':1010}],family=14010,sprite_family=1270,ownanim={'source_frame_fallbacks':[1]})
            (overlay/'pilot-receipt.json').write_text(json.dumps(receipt));before=exp.snapshot(source)
            changes=exp.stage_body_overlays([staged],{'1010':overlay})
            self.assertEqual(staged.read_file('Anime/ANM_HI_JP.dat/anm01270.lzs'),b'new')
            self.assertIsNone(staged.load_patch('db','char.dat.json'))
            self.assertEqual(exp.snapshot(source),before)
            self.assertEqual(len(changes[0]['body_changes']),2)
            with self.assertRaisesRegex(ValueError,'no selected'):
                exp.stage_body_overlays([staged],{'1020':overlay})

    def test_unique_contracts_keep_source_body_disable_zero_mc_and_only_own_attack_events(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mod=self.mod(root,'Unique');mod.meta['source_import']={'source_id':170};mod.save_meta()
            mod.save_patch('db','char.dat.json',{'added':[{'id':226,'body_type':1,'magichange_type':2,'magichange_weapon':1234}]})
            events={str(prefix+n):'event '+str(prefix+n) for prefix in (12010000,12110000,12210000)for n in (226,227)}
            mod.save_patch('script','script.json',{'events':events})
            ip=root/'overlay.json';ip.write_text(json.dumps({'items':[dict(source_id=170,uid='source',source_sha256='a'*64,
                stored_fields={'body_type':{'value':1},'magichange':{'value':0}})]}))
            changes=exp.stage_unique_contracts([mod],ip)
            row=mod.load_patch('db','char.dat.json')['added'][0]
            self.assertEqual((row['body_type'],row['magichange_type'],row['magichange_weapon']),(1,0,0))
            self.assertEqual(set(mod.load_patch('script','script.json')['events']),{'12010226','12110226','12210226'})
            self.assertEqual(len(changes[0]['attack_events_pruned']),3)

    def test_receipt_coverage_inherits_untouched_items_and_rejects_stale_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source';source.mkdir();out=root/'out';out.mkdir()
            def item(uid,kind,sid,**data):
                return dict(uid=uid,kind=kind,source_id=sid,data=data,source={'sha256':'a'*64},fidelity='partial',
                    status=dict(extraction='metadata-verified',conversion='not-started',implementation='not-started',gameplay='not-tested',presentation='not-tested'))
            inventory=dict(items=[item('char','character',1010,sprite=1010,body=1010,color_id=1010,help_id=1,kind_gender=11),
                item('skill','skill',1),item('untouched','source-file',99)],edges=[],unresolved=[],collisions=[])
            ip=root/'inventory.json';ip.write_text(json.dumps(inventory))
            receipt=dict(family=14010,source_ranks=[dict(id=1010,evidence={'row_sha256':'a'*64})],
                d4_plan={'report':[dict(kind='skill',d4_id=1,status='placeholder'),dict(kind='skill',d4_id=999,status='unmapped')]})
            rp=source/'pilot-receipt.json';rp.write_text(json.dumps(receipt))
            (source/'catalogue.json').write_text(json.dumps({'entries':[{'artifact':{'mod_id':'Source'}}]}))
            exp.coverage_imports(inventory_path=ip,builds={'source':source},output=out)
            coverage=json.loads((out/'coverage.json').read_text());ledger=json.loads((out/'progress-ledger.json').read_text())
            self.assertEqual((coverage['baseline_item_count'],coverage['overridden_item_count'],coverage['unchanged_item_count']),(3,2,1))
            self.assertNotIn('untouched',ledger)
            self.assertEqual(ledger['skill']['status']['implementation'],'blocked')
            self.assertEqual(ledger['char']['status']['gameplay'],'not-tested')
            self.assertEqual(len(json.loads((out/'unresolved-import-references.json').read_text())),1)
            receipt['source_ranks'][0]['evidence']['row_sha256']='b'*64;rp.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'source hash mismatch'):
                exp.coverage_imports(inventory_path=ip,builds={'source':source},output=out)

    def test_voice_bank_overlay_copies_native_payload_and_only_changes_staged_voice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged, bank = self.mod(root, 'Staged'), self.mod(root, 'Bank')
            staged.meta['source_import'] = {'identity': {'character_id': 1010}}
            staged.save_meta()
            staged.save_patch('db', 'char.dat.json', {'added': [{'id':14010, 'voice_id':1010, 'name_EN':'Source'}]})
            bank.save_patch('voices', 'voices.json', {'voices': {'9000': {'lines': [{'file':'clip.vag','kind':0,'cats':[1]}]}}})
            payload = Path(bank.patches_dir) / 'voices/clip.vag'
            payload.write_bytes(b'synthetic source voice')
            before = exp.snapshot(bank)
            changes = exp.stage_voice_banks([staged], {'1010':bank.folder})
            self.assertEqual((Path(staged.patches_dir)/'voices/clip.vag').read_bytes(), b'synthetic source voice')
            row = staged.load_patch('db','char.dat.json')['added'][0]
            self.assertEqual((row['voice_id'],row['name_EN']), (9000,'Source'))
            self.assertEqual(exp.snapshot(bank),before)
            self.assertEqual(changes[0]['source_id'],1010)
            with self.assertRaisesRegex(ValueError, 'do not match'):
                exp.stage_voice_banks([staged], {'999':bank.folder})

    def test_staged_personalities_lease_global_rows_and_preserve_installed_pilot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pilot, disabled, a, b = [self.mod(root, n) for n in ('Pilot', 'Disabled', 'A', 'B')]
            pilot.save_patch('db', 'charPersonal.dat.json', {'added': [{'id': 132, 'voice_group': 135, 'variant': 0}]})
            disabled.save_patch('db', 'charPersonal.dat.json', {'added': [{'id': 145, 'voice_group': 999, 'variant': 0}]})
            before = exp.snapshot(pilot)
            for mod, family, physical in ((a, 14010, 1270), (b, 14020, 1280)):
                mod.save_patch('classes', f'class_{family}.json', dict(family=family, template=1010,
                    kind='humanoid', sprite_family=physical))
                mod.save_patch('db', 'charPersonal.dat.json', {'added': [dict(id=132+k,
                    voice_group=family//10, variant=k, name_EN='Source '+str(k)) for k in range(3)]})
            receipt = exp.lease_personality_rows(FS(), [a, b], [pilot, disabled])
            self.assertEqual([[r['id'] for r in c['rows']] for c in receipt['changes']], [[146,147,148],[149,150,151]])
            self.assertEqual(exp.snapshot(pilot), before)
            self.assertEqual(exp.preflight(FS(), [a,b], [pilot,disabled])['conflicts'], [])
            self.assertEqual(a.load_patch('db', 'charPersonal.dat.json')['added'][2]['name_EN'], 'Source 2')
            collision = self.mod(root, 'DisabledCollision')
            collision.save_patch('db', 'charPersonal.dat.json', {'added': [dict(id=146)]})
            with self.assertRaisesRegex(ValueError, 'charPersonal.dat:146'):
                exp.preflight(FS(), [a,b], [pilot,disabled,collision])

    def test_n_imports_preserve_dependency_selection_and_reject_mod_overwrite(self):
        from d5lib import gamepacks
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifacts = {}
            for i in range(3):
                mod = self.mod(root, 'Import' + str(i))
                mod.save_patch('db', 'char.dat.json', {'added': [{'id': 216 + i}]})
                entry = dict(id='d4:test' + str(i), game='d4', name='Fixture' + str(i),
                    category='monsters' if i == 0 else 'humanoid_classes', status='build-ready',
                    source=dict(edition='synthetic', identity=str(i), provenance=[dict(kind='fixture', reference='test')]),
                    fidelity=dict(mode='hybrid', missing_mappings=['native acceptance'], adaptations=[]),
                    requires=['d4:test0'] if i == 2 else [],
                    artifact=dict(mod_id=mod.id, required_payload=['patches/db/char.dat.json']))
                artifacts[str(i)] = entry, mod
            with patch.object(exp, 'read_pilot', side_effect=lambda p: artifacts[p]):
                cat, mods, aliases = exp.accepted_imports({'a': '0', 'b': '1', 'c': '2'})
                selected = gamepacks.resolve_selection(cat, artifacts=mods, entries=[aliases['c']])
                self.assertEqual(selected.mod_ids, ('Import0', 'Import2'))
                self.assertEqual(cat['entries'][0]['category'], 'monsters')
                with self.assertRaisesRegex(ValueError, 'Duplicate accepted native mod'):
                    exp.accepted_imports({'a': '0', 'b': '0'})

    def test_custom_voice_collision_is_reserved(self):
        from d5lib import voices  # register the real handler used by this fixture
        with tempfile.TemporaryDirectory() as td:
            a, b = [self.mod(Path(td), n) for n in ('Selected', 'Other')]
            for m in (a, b):
                m.save_patch('voices', 'voices.json', {'voices': {'9000': {'lines': []}}})
            with self.assertRaisesRegex(ValueError, 'voice:9000'):
                exp.preflight(FS(), [a], [b])

    def test_cold_finalization_checks_and_records_execution_order(self):
        from d5lib import gamefs, runtime, sprites
        def early(ctx):
            pass
        def late(ctx):
            pass
        early.__module__ = 'd5lib.outfits'
        late.__module__ = 'd5lib.enemyitems'
        expected = [fn.__module__ + '.' + fn.__name__ for fn in (early, late)]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = dict(game_path=str(root / 'game'), original_state=str(root / 'state'),
                          mods=[], selected_mods=[], output=str(root / 'output'),
                          cache=str(root / 'cache'), expected_finalizer_order=expected)
            fs = Mock()
            originals = Mock(reads={})
            ctx = Mock(outputs={}, skipped_features=[])
            with patch.object(modsys, 'FINALIZERS', [late, early]), \
                    patch.object(modsys, 'build', return_value=ctx), \
                    patch.object(gamefs, 'GameFS', return_value=fs), \
                    patch.object(exp, 'Originals', return_value=originals), \
                    patch.object(exp, 'verify_selected', return_value=[]), \
                    patch.object(runtime, 'CACHE'), patch.object(sprites, 'CACHE_DIR'):
                receipt = exp.finalize(config)
            self.assertEqual(receipt['finalizer_order'], expected)
            self.assertEqual(json.loads((root / 'output/finalization.json').read_text())['finalizer_order'], expected)
            fs.reset.assert_called_once()

    def mod(self, root, name):
        m = modsys.Mod(str(root / name))
        m.save_meta()
        return m

    def test_same_id_replacement_is_explicit_and_other_collisions_reject(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            selected = self.mod(root / 'new', 'Pilot')
            old = self.mod(root / 'installed', 'Pilot')
            patch = {'added': [{'id': 216, 'name_EN': 'Pilot'}]}
            selected.save_patch('db', 'char.dat.json', patch)
            old.save_patch('db', 'char.dat.json', patch)
            self.assertEqual(exp.preflight(FS(), [selected], [old])['conflicts'], [])
            other = self.mod(root, 'Unrelated')
            other.save_patch('db', 'char.dat.json', patch)
            with self.assertRaises(ValueError):
                exp.preflight(FS(), [selected], [old, other])

    def test_quest_progress_collision_checks_actual_field(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a, b = self.mod(root, 'A'), self.mod(root, 'B')
            a.save_patch('db', 'Quest.dat.json', {'added': [{'id': 192, 'sort_order': 397}]})
            b.save_patch('db', 'Quest.dat.json', {'added': [{'id': 193, 'sort_order': 397}]})
            with self.assertRaises(ValueError):
                exp.preflight(FS(), [a], [b])

    def test_derived_portrait_and_unlock_flags_collide(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a, b = self.mod(root, 'A'), self.mod(root, 'B')
            a.save_patch('db', 'char.dat.json', {'added': [{'id': 216}]})
            b.write_file('Anime/ANM_HI_JP.dat/anm10216.lzs', b'synthetic')
            with self.assertRaises(ValueError):
                exp.preflight(FS(), [a], [b])
            a.save_patch('classes', 'class_1350.json', dict(family=1350, template=1150))
            b.save_patch('classes', 'class_1350.json', dict(family=1350, template=1150))
            claims_a, details = exp.reservations(FS(), a, {})
            self.assertEqual(details['1350']['unlock_flags'], list(range(17331, 17337)))
            self.assertIn('unlock-flag:17331', claims_a)

    def test_preexisting_baseline_overlap_does_not_expand_authorized_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            selected, a, b = [self.mod(root, x) for x in ('Pilot', 'A', 'B')]
            selected.save_patch('db', 'char.dat.json', {'added': [{'id': 216}]})
            for mod in (a, b):
                mod.write_file('Script/example.dat', b'baseline')
            result = exp.preflight(FS(), [selected], [a, b])
            self.assertEqual(len(result['baseline_overlaps']), 1)
            self.assertEqual(result['conflicts'], [])

    def test_explicit_duplicate_help_routes_fail_ambiguously(self):
        with tempfile.TemporaryDirectory() as td:
            mod = self.mod(Path(td), 'Pilot')
            mod.save_patch('db', 'charhelp.dat.json', {'rows': {'0': {'line1_EN': 'changed'}}})
            fs = FS()
            fs.data[exp.DB + 'charhelp.dat'] = raw_table('charhelp.dat', [{'id': 10}, {'id': 10}])
            with self.assertRaisesRegex(ValueError, 'Ambiguous explicitly patched duplicate'):
                exp.preflight(fs, [mod], [])

    def test_positional_member_may_append_a_repeated_id(self):
        """CORED4B: Overlord's converted charPersonal member is `3, 4, 5, 3, 4, 5`.

        charPersonal is read by position, so one pack appending an id twice (and appending an id
        the vanilla table already has) is information, not an ambiguity: the claims collapse to
        one key and the positional guard is `d5lib.ordercheck`.  A D4 unique could not be built
        at all while this raised.
        """
        with tempfile.TemporaryDirectory() as td:
            mod = self.mod(Path(td), 'Pilot')
            rows = [{'id': 3, 'voice_group': 2000, 'variant': 0},
                    {'id': 3, 'voice_group': 2001, 'variant': 0},
                    {'id': 5, 'voice_group': 2000, 'variant': 2}]
            mod.save_patch('db', 'charPersonal.dat.json', {'added': rows})
            fs = FS()
            fs.data[exp.DB + 'charPersonal.dat'] = raw_table('charPersonal.dat', [{'id': 3}])
            claims, details = exp.reservations(fs, mod, {})
            self.assertEqual(details, {})
            self.assertIn('db:charPersonal.dat:3', claims)
            self.assertIn('db:charPersonal.dat:5', claims)
            exp.preflight(fs, [mod], [])                    # no ambiguity, no conflict

    def test_appended_duplicate_id_outside_positional_members_still_fails(self):
        """The ambiguity check keeps its teeth where an id really is the key."""
        with tempfile.TemporaryDirectory() as td:
            mod = self.mod(Path(td), 'Pilot')
            mod.save_patch('db', 'char.dat.json', {'added': [{'id': 216, 'name_EN': 'A'},
                                                             {'id': 216, 'name_EN': 'B'}]})
            with self.assertRaisesRegex(ValueError, 'Ambiguous explicitly patched duplicate char.dat ID 216'):
                exp.reservations(FS(), mod, {})

    def test_two_packs_appending_the_same_positional_id_still_conflict(self):
        """One pack repeating an id is information; two packs claiming it is an allocation error."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a, b = self.mod(root, 'A'), self.mod(root, 'B')
            a.save_patch('db', 'charPersonal.dat.json', {'added': [{'id': 3, 'voice_group': 2000}]})
            b.save_patch('db', 'charPersonal.dat.json', {'added': [{'id': 3, 'voice_group': 2001}]})
            with self.assertRaisesRegex(ValueError, 'allocation conflicts'):
                exp.preflight(FS(), [a], [b])

    def test_the_same_folder_listed_twice_is_one_mod(self):
        """A reserved set built from symlinks can reach one folder through two paths."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'one').mkdir()
            mod = self.mod(root / 'one', 'Pilot')
            mod.save_patch('db', 'charPersonal.dat.json', {'added': [{'id': 3, 'voice_group': 2000}]})
            (root / 'two').symlink_to(root / 'one', target_is_directory=True)
            for name in ('one', 'two'):
                self.assertEqual([m.id for m in d4unique.scan_mods([root / name])], ['Pilot'])
            self.assertEqual(len(d4unique.scan_mods([root / 'one', root / 'two'])), 1)
            # preflight given the same folder twice is not a conflict with itself
            twin = modsys.Mod(str(root / 'two' / 'Pilot'))
            self.assertEqual(exp.preflight(FS(), [mod], [twin])['conflicts'], [])

    def test_pilot_source_hashes_bind_native_mod_not_only_finalized_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod = self.mod(root / 'native-mods', 'Pilot')
            mod.save_patch('db', 'char.dat.json', {'added': [{'id': 216}]})
            payload = 'patches/db/char.dat.json'
            cat = dict(schema=1, id='test', name='Test', games=[dict(id='d4', name='D4')], entries=[dict(
                id='d4:test', game='d4', name='Test', category='characters', status='build-ready',
                source=dict(edition='synthetic', identity='10', provenance=[dict(kind='synthetic', reference='test')]),
                fidelity=dict(mode='hybrid', missing_mappings=[], adaptations=[]),
                artifact=dict(mod_id='Pilot', required_payload=[payload]))])
            (root / 'catalogue.json').write_text(json.dumps(cat))
            (root / 'native-files.json').write_text(json.dumps(exp.snapshot(mod)))
            (root / 'finalized-logical').mkdir()
            (root / 'finalized-logical/fixture').write_bytes(b'finalized')
            (root / 'finalization.json').write_text(json.dumps(dict(status='built-offline', skipped_features=[], finalizer_order=['synthetic'],
                files=[dict(path='fixture', bytes=9, sha256=exp.sha(b'finalized'))])))
            self.assertEqual(exp.read_pilot(root)[1].id, 'Pilot')
            mod.meta['author'] = 'changed after finalization'
            mod.save_meta()
            with self.assertRaisesRegex(ValueError, 'native source differs'):
                exp.read_pilot(root)

    def test_generated_class_events_collide_with_direct_script_patch(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = [self.mod(Path(td), n) for n in ('Selected', 'Other')]
            a.save_patch('classes', 'class_1350.json', dict(family=1350, template=1150))
            b.save_patch('script', 'custom.json', {'events': {'3101350': 'event 3101350\n    wait_children\n'}})
            with self.assertRaisesRegex(ValueError, 'allocation conflicts'):
                exp.preflight(FS(), [a], [b])

    def test_raw_database_carrier_conflicts_with_structured_row_patch(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = [self.mod(Path(td), n) for n in ('Selected', 'Other')]
            a.save_patch('db', 'char.dat.json', {'added': [{'id': 216}]})
            b.write_file(exp.DB + 'char.dat', FS().read(exp.DB + 'char.dat'))
            with self.assertRaisesRegex(ValueError, 'raw-carrier'):
                exp.preflight(FS(), [a], [b])

    def test_duplicate_final_character_is_not_hidden_by_last_id_dictionary(self):
        with tempfile.TemporaryDirectory() as td:
            a = self.mod(Path(td), 'Selected')
            a.save_patch('db', 'char.dat.json', {'added': [{'id': 216, 'color_id': 570, 'name_EN': 'Pilot'}]})
            final = FS()
            final.data[exp.DB + 'char.dat'] = raw_table('char.dat', [dict(id=216, color_id=999, name_EN='wrong'),
                dict(id=216, color_id=216, name_EN='Pilot')])
            with self.assertRaisesRegex(ValueError, 'Ambiguous finalized'):
                exp.verify_selected(FS(), [a], final)

    def test_profile_read_is_exact_read_only_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.mod(root / 'mods', 'A')
            self.mod(root / 'mods', 'B')
            (root / 'profiles/Test').mkdir(parents=True)
            path = root / 'profiles/Test/load_order.json'
            path.write_text('["B", "A"]')
            settings = root / 'settings.json'
            settings.write_text('{"profile":"Test"}')
            before = settings.read_bytes(), path.read_bytes()
            mods, receipt = exp.read_current(root)
            self.assertEqual([m.id for m in mods], ['B', 'A'])
            self.assertEqual(receipt['order'], ['B', 'A'])
            self.assertEqual(before, (settings.read_bytes(), path.read_bytes()))
            settings.write_text('{"profile":"../Other"}')
            with self.assertRaises(ValueError):
                exp.read_current(root)

    def test_readback_checks_final_skill_dependencies_and_full_selected_fields(self):
        with tempfile.TemporaryDirectory() as td:
            mod = self.mod(Path(td), 'Pilot')
            mod.save_patch('db', 'char.dat.json', {'added': [dict(id=216, color_id=570,
                name_EN='Pilot', learn_count=1, learn1_skill=10571, learn1_level=1)]})
            fs = FS()
            final = FS()
            final.data[exp.DB + 'char.dat'] = raw_table('char.dat', [dict(id=216, color_id=216,
                name_EN='Pilot', learn_count=1, learn1_skill=10571, learn1_level=1)])
            self.assertEqual(len(exp.verify_selected(fs, [mod], final)), 1)
            final.data[exp.DB + 'magic.dat'] = raw_table('magic.dat')
            with self.assertRaises(ValueError):
                exp.verify_selected(fs, [mod], final)

    def test_failed_pilot_and_output_overlap_refuse(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'finalization.json').write_text('{"status":"built-with-skips"}')
            with self.assertRaises(ValueError):
                exp.read_pilot(root)
            with self.assertRaises(ValueError):
                exp.build(generic_build=root, unique_build=root, game_path=root,
                    original_state=root, current_kit=root, output_path=root / 'overlap')
            self.assertFalse((root / 'overlap').exists())


if __name__ == '__main__':
    unittest.main()


class UpdateStagingTests(unittest.TestCase):
    def fixture(self, root, *, unique=False):
        from d5lib.sourceimports import d4_lease_digest
        import shutil
        old=modsys.Mod(str(root/'old'/'Owner'));old.meta['source_import']=dict(source_game='d4',source_id=230)if unique else {'identity':{'source':'d4','character_id':1010}};old.save_meta()
        cid=273 if unique else 14010;helpid=14727 if unique else 14010
        char=dict(id=cid,sprite_id=cid if unique else 1270,color_id=cid if unique else 1270,voice_id=9000,help_id=helpid,
            learn_count=1,learn1_skill=13010,learn1_level=5,evility_count=1,evility1=7000)
        old.save_patch('db','char.dat.json',{'added':[char]});old.save_patch('db','magic.dat.json',{'added':[{'id':13010}]})
        old.save_patch('db','Skill.dat.json',{'added':[{'id':7000,'owner':cid,'source':4}]})
        old.save_patch('db','charhelp.dat.json',{'added':[{'id':helpid,'char_id':helpid,'line1_EN':'Source','line3_EN':'Pending'}]})
        if unique:old.save_patch('evilities','aliases.json',{'7000':12})
        else:
            old.save_patch('classes','class_14010.json',dict(family=cid,template=1010,kind='humanoid',sprite_family=1270,evility_alias={'7000':12}))
            old.save_patch('db','charPersonal.dat.json',{'added':[dict(id=146+k,voice_group=1401,variant=k,name_EN='Source'+str(k))for k in range(3)]})
        controls={str(p.relative_to(old.patches_dir)):d4_lease_digest(json.loads(p.read_text()))for folder in('db','classes','evilities','voices')for p in(Path(old.patches_dir)/folder).glob('*.json')}
        evidence=dict(uid='source-ability',sha256='a'*64);owner=dict(family=cid,source_identity=old.meta['source_import'].get('identity')or old.meta['source_import'],baseline_meta=__import__('copy').deepcopy(old.meta),baseline_meta_sha256=d4_lease_digest(old.meta),baseline_patches=controls,
            sources=dict(skills={'1':evidence},evilities={'2':evidence}),skills={'1':dict(evidence,id=13010,donor=10571)},evilities={'2':dict(evidence,id=7000,donor=12)},
            characters=[{k:char[k]for k in('id','sprite_id','color_id','voice_id','help_id')}],
            learning={str(cid):dict(skills=[[13010,5]],innate=[7000])},specs=[]if unique else[dict(family=cid,template=1010,kind='humanoid',sprite_family=1270)],
            personality=[]if unique else old.load_patch('db','charPersonal.dat.json')['added'],help=old.load_patch('db','charhelp.dat.json')['added'])
        owner['baseline_files']={str(p.relative_to(old.folder)):__import__('hashlib').sha256(p.read_bytes()).hexdigest()for p in Path(old.folder).rglob('*')if p.is_file()}
        claims={n:{str(i):['Owner']for i in ids}for n,ids in [('magic.dat',[13010]),('Skill.dat',[7000]),('char.dat',[cid]),('charPersonal.dat',[]if unique else[146,147,148]),('charhelp.dat',[helpid])]}
        bundle=dict(schema='d4-update-leases/1',owners={'Owner':owner},claims=claims)
        shutil.copytree(old.folder,root/'new'/'Owner');new=modsys.Mod(str(root/'new'/'Owner'))
        return old,new,bundle

    def stage(self, fs, new, old, bundle):
        from d5lib.sourceimports import d4_lease_digest
        options=dict(previous_leases=bundle,previous_leases_sha256=d4_lease_digest(bundle))
        exp.lease_personality_rows(fs,[new],[old],**options);return exp.lease_unique_help_rows(fs,[new],[old],**options)

    def test_repeated_staging_keeps_ids_metadata_and_accepts_new_skill_and_notice(self):
        for unique in(False,True):
            with tempfile.TemporaryDirectory()as td:
                old,new,b=self.fixture(Path(td),unique=unique);before=exp.snapshot(old)
                p=new.load_patch('db','char.dat.json');r=p['added'][0];r.update(learn_count=2,learn2_skill=13010,learn2_level=5,learn1_skill=13011,learn1_level=1);new.save_patch('db','char.dat.json',p)
                p=new.load_patch('db','magic.dat.json');p['added'].append({'id':13011});new.save_patch('db','magic.dat.json',p)
                p=new.load_patch('db','charhelp.dat.json');p['added'][0]['line3_EN']='Updated pending notice';new.save_patch('db','charhelp.dat.json',p)
                self.stage(FS(),new,old,b);once=exp.snapshot(new);self.stage(FS(),new,old,b)
                self.assertEqual(exp.snapshot(new),once);self.assertEqual(exp.snapshot(old),before)
                self.assertEqual(new.load_patch('db','charhelp.dat.json')['added'][0]['id'],b['owners']['Owner']['help'][0]['id'])

    def test_drift_foreign_claim_and_dropped_learning_refuse_before_writes(self):
        for scenario in('old-patch','old-meta','old-nonjson','new-meta','missing-old','voice','sprite','learning','foreign','variant','alias'):
            with tempfile.TemporaryDirectory()as td:
                root=Path(td);old,new,b=self.fixture(root);others=[old]
                if scenario=='old-meta':old.meta['description']='drift'
                elif scenario=='old-nonjson':old.write_file('fixture.bin',b'drift')
                elif scenario=='new-meta':new.meta['author']='drift'
                elif scenario=='missing-old':others=[]
                elif scenario=='foreign':
                    foreign=modsys.Mod(str(root/'Foreign'));foreign.save_patch('db','charPersonal.dat.json',{'added':[{'id':146}]});others.append(foreign)
                elif scenario=='variant':
                    p=new.load_patch('db','charPersonal.dat.json');p['added'][0]['variant']=9;new.save_patch('db','charPersonal.dat.json',p)
                elif scenario=='alias':
                    p=new.load_patch('classes','class_14010.json');p['evility_alias']['7000']=99;new.save_patch('classes','class_14010.json',p)
                else:
                    target=old if scenario=='old-patch'else new;p=target.load_patch('db','char.dat.json');key={'old-patch':'voice_id','voice':'voice_id','sprite':'sprite_id','learning':'learn1_skill'}[scenario];p['added'][0][key]=999;target.save_patch('db','char.dat.json',p)
                before=exp.snapshot(new)
                from d5lib.sourceimports import d4_lease_digest
                with self.subTest(scenario=scenario),self.assertRaises(ValueError):exp.lease_personality_rows(FS(),[new],others,previous_leases=b,previous_leases_sha256=d4_lease_digest(b))
                self.assertEqual(exp.snapshot(new),before)

    def test_public_combined_build_enters_pinned_staging_without_finishing_package(self):
        from d5lib import sourceimports,gamefs,gamepacks
        import shutil
        class Boundary(Exception):pass
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);old,new,b=self.fixture(root);kit=root/'kit';(kit/'mods').mkdir(parents=True);shutil.copytree(old.folder,kit/'mods/Owner')
            new._source_fingerprint=exp.snapshot(new)
            selection=Mock(mod_ids=('Owner',),entry_ids=('entry',))
            def materialize(cat,sel,artifacts,staging_path):shutil.copytree(new.folder,Path(staging_path)/'mods/Owner')
            with patch.object(exp,'accepted_imports',return_value=({'entries':[]},{'Owner':new},{'one':'entry'})),patch.object(gamepacks,'validate_catalogue',side_effect=lambda x,**k:x),patch.object(gamepacks,'resolve_selection',return_value=selection),patch.object(exp,'read_current',return_value=([old],{'files':{},'order':['Owner'],'profile':'test'})),patch.object(exp,'Originals'),patch.object(gamefs,'GameFS',return_value=FS()),patch.object(gamepacks,'materialize',side_effect=materialize),patch.object(exp,'stage_pending_notices',return_value=[]),patch.object(exp,'preflight',side_effect=Boundary),patch.object(exp,'lease_personality_rows',wraps=exp.lease_personality_rows)as personality,patch.object(exp,'lease_unique_help_rows',wraps=exp.lease_unique_help_rows)as help_rows:
                fs=FS();fs.reset=Mock()
                with patch.object(gamefs,'GameFS',return_value=fs),self.assertRaises(Boundary):
                    exp.build(game_path=root/'game',original_state=root/'state',current_kit=kit,output_path=root/'out',builds={'one':root/'accepted'},previous_leases=b,previous_leases_sha256=sourceimports.d4_lease_digest(b))
                self.assertEqual(personality.call_args.kwargs['previous_leases'],b);self.assertEqual(help_rows.call_args.kwargs['previous_leases'],b)

    def test_only_pinned_normal_ability_disclosures_may_change(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory()as td:
            old,new,b=self.fixture(Path(td));o=b['owners']['Owner']
            # This is the exact report formatter called by normal build_d4_pilot.
            from d5lib.sourceimports import d4_ability_adaptations,d4_lease_digest
            baseline=['Unrelated disclosure','skill Earlier (1): placeholder']
            old.meta['source_import']['adaptations']=baseline;old.save_meta()
            o['baseline_meta']=deepcopy(old.meta);o['baseline_meta_sha256']=d4_lease_digest(old.meta)
            o['baseline_files']={str(p.relative_to(old.folder)):__import__('hashlib').sha256(p.read_bytes()).hexdigest()for p in Path(old.folder).rglob('*')if p.is_file()}
            o['expected_ability_adaptations']=d4_ability_adaptations([dict(kind='skill',d4_name='Earlier',d4_id=1,status='adapted',d5_id=13011,copy_of=10571)])
            new.meta['source_import']['adaptations']=[baseline[0],*o['expected_ability_adaptations']];new.save_meta()
            self.stage(FS(),new,old,b)
            new.meta['source_import']['adaptations'][0]='Unrelated drift';new.save_meta()
            with self.assertRaisesRegex(ValueError,'metadata changed'):self.stage(FS(),new,old,b)


class PaletteDisclosureUpdateTests(unittest.TestCase):
    fixture = UpdateStagingTests.fixture
    stage = UpdateStagingTests.stage
    legacy = ('D4 body palettes per colour (30 colour entries mapped exactly); '
              'D4 face and cut-in per colour where extracted; D4 class description')
    current = ('D4 body palettes per colour (30 exact entries, 0 nearest-source palette approximations); '
               'D4 face and cut-in per colour where extracted; D4 class description')

    def palette_fixture(self, root, before, after):
        from copy import deepcopy
        from d5lib.sourceimports import d4_lease_digest
        old, new, bundle = self.fixture(root)
        old.meta['source_import']['adaptations'] = [before]
        old.save_meta()
        owner = bundle['owners']['Owner']
        owner['baseline_meta'] = deepcopy(old.meta)
        owner['baseline_meta_sha256'] = d4_lease_digest(old.meta)
        owner['baseline_files'] = {str(p.relative_to(old.folder)):
            __import__('hashlib').sha256(p.read_bytes()).hexdigest()
            for p in Path(old.folder).rglob('*') if p.is_file()}
        new.meta['source_import']['adaptations'] = [after]
        new.save_meta()
        return old, new, bundle

    def test_actual_legacy_30_to_current_30_zero_keeps_all_pinned_inputs(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as td:
            old, new, bundle = self.palette_fixture(Path(td), self.legacy, self.current)
            prior_bundle = deepcopy(bundle)
            prior_old, prior_new_meta = exp.snapshot(old), deepcopy(new.meta)
            self.stage(FS(), new, old, bundle)
            self.assertEqual(bundle, prior_bundle)
            self.assertEqual(exp.snapshot(old), prior_old)
            self.assertEqual(new.meta, prior_new_meta)

    def test_ordinary_identical_legacy_and_current_wording_remains_valid(self):
        for line in (self.legacy, self.current):
            with self.subTest(line=line), tempfile.TemporaryDirectory() as td:
                old, new, bundle = self.palette_fixture(Path(td), line, line)
                self.stage(FS(), new, old, bundle)

    def test_changed_count_approximation_or_any_unrelated_metadata_refuses_without_writes(self):
        cases = {
            'count': self.current.replace('30 exact', '31 exact'),
            'nonzero-approximation': self.current.replace('0 nearest', '1 nearest'),
            'prefix': self.current.replace('D4 body', 'Other body'),
            'suffix': self.current + ' changed',
            'unknown-line': 'Unrelated new disclosure',
            'source-identity': self.current,
            'other-field': self.current,
            'extra-line': self.current,
        }
        for scenario, after in cases.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as td:
                old, new, bundle = self.palette_fixture(Path(td), self.legacy, after)
                if scenario == 'source-identity':
                    new.meta['source_import']['identity']['character_id'] = 999
                elif scenario == 'other-field':
                    new.meta['author'] = 'Unrelated change'
                elif scenario == 'extra-line':
                    new.meta['source_import']['adaptations'].append('Extra disclosure')
                new.save_meta()
                before = exp.snapshot(new)
                with self.assertRaises(ValueError):
                    self.stage(FS(), new, old, bundle)
                self.assertEqual(exp.snapshot(new), before)

    def test_palette_compatibility_combines_only_with_existing_exact_ability_allowance(self):
        from copy import deepcopy
        from d5lib.sourceimports import d4_lease_digest
        with tempfile.TemporaryDirectory() as td:
            old, new, bundle = self.palette_fixture(Path(td), self.legacy, self.current)
            old.meta['source_import']['adaptations'].append('skill Earlier (1): placeholder')
            old.save_meta()
            owner = bundle['owners']['Owner']
            owner['baseline_meta'] = deepcopy(old.meta)
            owner['baseline_meta_sha256'] = d4_lease_digest(old.meta)
            owner['baseline_files'] = {str(p.relative_to(old.folder)):
                __import__('hashlib').sha256(p.read_bytes()).hexdigest()
                for p in Path(old.folder).rglob('*') if p.is_file()}
            owner['expected_ability_adaptations'] = ['skill Earlier (1): adapted -> D5 10571']
            new.meta['source_import']['adaptations'].append(owner['expected_ability_adaptations'][0])
            new.save_meta()
            self.stage(FS(), new, old, bundle)
            new.meta['source_import']['adaptations'][1] = 'skill Foreign (1): adapted -> D5 10571'
            new.save_meta()
            with self.assertRaises(ValueError):
                self.stage(FS(), new, old, bundle)
