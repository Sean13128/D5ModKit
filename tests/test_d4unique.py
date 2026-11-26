"""Synthetic table fixtures: no copyrighted game bytes or native acceptance claims."""
import json
from pathlib import Path
import tempfile
import unittest

from d5lib import d4unique, database, modsys


def table(name, rows):
    schema = database.get_schema(name)
    t = database.load_table(name, bytes(schema.header_size))
    for fields in rows:
        row = t.new_row()
        for key, value in fields.items():
            row.set(key, value)
        t.rows.append(row)
    return t


def fixture():
    source = dict(id=10, name='Valvatorez', title='Prinny Instructor', innate_evility=347,
        base=[26, 14, 20, 18, 16, 16, 18, 17], aptitudes=[110, 110, 130, 110, 100, 110, 120, 90],
        battle=dict(MOV=5, JMP=20, crit=13, kind_gender=1),
        learnset=[(10011, 1), (10012, 32), (10013, 80)], evilities=[8, 815, 65, 66])
    tables = {'char.dat': table('char.dat', [dict(id=470, name_EN='Unique Dummy'),
               dict(id=570, name_EN='Valvatorez', color_id=570, sprite_id=570,
                    voice_id=570, evility1=6032, evility_count=1, overload_id=203,
                    learn1_skill=30571, learn1_level=1, learn_count=1)]),
        'magic.dat': table('magic.dat', [dict(id=sid, name_EN=name) for sid, name in d4unique.SKILLS.values()]),
        'Skill.dat': table('Skill.dat', [dict(id=eid, name_EN=name) for eid, name in d4unique.EVILITIES.values()])}
    return source, tables


class UniqueTests(unittest.TestCase):
    def test_general_unique_plan_uses_explicit_identity_and_shared_mapping(self):
        src, tables = fixture()
        profile = dict(src, id=70, name='Fixture unique', innate_evility={'id': 999, 'name': 'Pending'},
                       evilities=[], skills=[dict(id=701, name='Fire', level=12)])
        mapping = dict(skills={'701': dict(d4_name='Fire', relation='adapted', copy_of=10571)},
                       evilities={'999': dict(relation='placeholder', reason='Unimplemented')})
        tables['char.dat'].rows[1].set('kind_gender', 11)
        row, mapped, audit = d4unique.plan_import(profile, tables, mapping, target_id=216,
            template_id=570, supported_ids=[216], excluded_source_ids=[10])
        self.assertEqual((row['id'], row['sprite_id'], row['name_EN']), (216, 216, 'Fixture unique'))
        self.assertEqual(row['kind_gender'], 1)
        self.assertEqual(row['body_type'], tables['char.dat'].rows[1]['body_type'])
        self.assertEqual(row['base_HP'], 26)
        self.assertEqual(row['learn1_level'], 12)
        self.assertEqual(row['evility_count'], 0)
        self.assertEqual(mapped['report'][0]['status'], 'placeholder')
        self.assertEqual(audit['fields']['apt_ATK'], 130)
        with self.assertRaisesRegex(ValueError, 'already present'):
            d4unique.plan_import(profile, tables, mapping, target_id=216, template_id=570,
                                 supported_ids=[216], excluded_source_ids=[70])

    def test_unique_body_type_requires_compatible_donor_independent_of_gender(self):
        src,tables=fixture()
        profile=dict(src,id=180,battle=dict(src['battle'],body_type=1,kind_gender=2),
            innate_evility={'id':999,'name':'Pending'},evilities=[],skills=[])
        mapping=dict(evilities={'999':dict(relation='placeholder')},skills={})
        with self.assertRaisesRegex(ValueError,'donor body type'):
            d4unique.plan_import(profile,tables,mapping,target_id=216,template_id=570,supported_ids=[216])
        tables['char.dat'].rows[1].set('body_type',1)
        row,_,_=d4unique.plan_import(profile,tables,mapping,target_id=216,template_id=570,supported_ids=[216])
        self.assertEqual((row['body_type'],row['kind_gender'],row['id']),(1,2,216))
        self.assertEqual((row['overload_id'],row['learn_count'],row['evility_count']),(0,0,0))

    def test_weapon_forte_reads_d4_weapon_skill_groups(self):
        # 1xx fist 2xx sword 3xx spear 4xx bow 5xx gun 6xx axe; 7xx attack magic and 8xx heal/support are staff
        self.assertEqual(d4unique.weapon_forte(dict(weapon_skills=[10201, 10202, 10301, 10302])),
                         ['sword', 'spear'])
        self.assertEqual(d4unique.weapon_forte(dict(weapon_skills=[10201, 10601, 10816])),
                         ['sword', 'axe', 'staff'])
        self.assertEqual(d4unique.weapon_forte(dict(weapon_skills=[10701, 10711, 10721, 10731, 801])),
                         ['staff'])
        self.assertEqual(d4unique.weapon_forte(dict(weapon_skills=[951, 952])), [])   # tower, no D5 weapon
        self.assertEqual(d4unique.weapon_forte(dict(weapon_skills=[])), [])
        self.assertEqual(d4unique.weapon_forte({}), [])

    def test_humanoid_unique_forte_raises_only_that_weapons_mastery(self):
        src, tables = fixture()
        donor = tables['char.dat'].rows[1]
        for weapon, value in (('fist', 5), ('sword', 15), ('spear', 10), ('bow', 5),
                              ('gun', 3), ('axe', 2), ('staff', 1)):
            donor.set('mastery_' + weapon, value)
        donor.set('wres_sword', 20)
        profile = dict(src, id=70, name='Fixture unique', weapon_skills=[10201, 10301],
            battle=dict(src['battle'], body_type=0, kind_gender=1),
            innate_evility={'id': 999, 'name': 'Pending'}, evilities=[], skills=[])
        mapping = dict(evilities={'999': dict(relation='placeholder')}, skills={})
        row, _, audit = d4unique.plan_import(profile, tables, mapping, target_id=216,
            template_id=570, supported_ids=[216], source_row=profile)
        self.assertEqual([row['mastery_' + weapon] for weapon in d4unique.HUMANOID_WEAPONS],
                         [5, 15, 15, 5, 3, 2, 1])
        self.assertEqual(row['wres_sword'], 20)      # weapon resistance stays the donor's
        forte = audit['weapon_forte']
        self.assertEqual(forte['forte'], ['sword', 'spear'])
        self.assertEqual(forte['raised'], {'spear': dict(donor=10, written=15)})
        self.assertEqual(forte['already_best'], ['sword'])

    def test_monster_unique_keeps_donor_mastery(self):
        src, tables = fixture()
        profile = dict(src, id=180, name='Fixture monster', weapon_skills=[10601],
            battle=dict(src['battle'], body_type=1, kind_gender=2),
            innate_evility={'id': 999, 'name': 'Pending'}, evilities=[], skills=[])
        mapping = dict(evilities={'999': dict(relation='placeholder')}, skills={})
        tables['char.dat'].rows[1].set('body_type', 1)
        _, _, audit = d4unique.plan_import(profile, tables, mapping, target_id=216,
            template_id=570, supported_ids=[216], source_row=profile)
        self.assertNotIn('weapon_forte', audit)

    def test_exact_static_fields_and_level_mapping_without_forged_innate(self):
        src, tables = fixture()
        row, mappings = d4unique.plan(src, tables)
        self.assertEqual(row['id'], 470)
        self.assertEqual(row['base_HP'], 26)
        self.assertEqual(row['apt_ATK'], 130)
        self.assertEqual(row['crit'], 13)
        self.assertEqual(row['learn2_skill'], 10572)
        self.assertEqual(row['learn2_level'], 32)
        self.assertEqual(row['learn_count'], 3)
        self.assertEqual(row['evility_count'], 0)
        self.assertEqual(row['overload_id'], 0)
        self.assertEqual(row['learn4_skill'], 0)
        self.assertEqual(row['sprite_id'], 570)
        self.assertEqual(row['voice_id'], 570)
        self.assertEqual(tables['char.dat'].rows[1]['evility1'], 6032)
        self.assertEqual(next(x for x in mappings if x['source_id'] == 347)['status'], 'blocked')
        self.assertEqual(len(mappings), 8)
        # Native serialization readback checks field representation and clearing.
        t = table('char.dat', [])
        t.rows.append(row)
        actual = database.load_table('char.dat', t.to_bytes()).rows[0]
        self.assertEqual(actual['base_HP'], 26)
        self.assertEqual(actual['learn3_level'], 80)
        self.assertEqual(actual['evility1'], 0)

    def test_missing_and_mismatched_dependencies_reject(self):
        for mutate in ('name', 'skill', 'unknown', 'innate'):
            src, tables = fixture()
            if mutate == 'name':
                tables['magic.dat'].rows[0].set('name_EN', 'Unrelated')
            elif mutate == 'skill':
                tables['magic.dat'].rows.pop()
            elif mutate == 'unknown':
                src['learnset'].append((999, 1))
            else:
                src['innate_evility'] = 815
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                d4unique.plan(src, tables)

    def test_high_ids_and_boolean_ids_reject(self):
        src, tables = fixture()
        for target in (1000, 5000, True, 471):
            with self.subTest(target=target), self.assertRaises(ValueError):
                d4unique.plan(src, tables, target_id=target)

    def test_inserted_low_unique_requires_verified_pool_and_preserves_donor(self):
        src, tables = fixture()
        row, _ = d4unique.plan(src, tables, target_id=216, supported_ids=[216])
        self.assertEqual(row['id'], 216)
        self.assertEqual(tables['char.dat'].rows[1]['id'], 570)
        with self.assertRaises(ValueError):
            d4unique.plan(src, tables, target_id=570, supported_ids=[570])

    def test_collision_scan_covers_disabled_rows_outfits_and_art(self):
        _, tables = fixture()
        with tempfile.TemporaryDirectory() as td:
            mod = modsys.Mod(str(Path(td) / 'Disabled_candidate'))
            mod.save_meta()
            good = d4unique.check_conflicts(tables, [mod], 470)
            self.assertEqual(good['conflicts'], [])
            for patch in ({'rows': {'0': {'name_EN': 'Taken'}}}, {'added': [{'id': 470}]}):
                mod.save_patch('db', 'char.dat.json', patch)
                with self.assertRaises(ValueError):
                    d4unique.check_conflicts(tables, [mod], 470)
            mod.save_patch('db', 'char.dat.json', {})
            mod.save_patch('outfits', 'outfits.json', {'pairs': [[10, 470]]})
            with self.assertRaises(ValueError):
                d4unique.check_conflicts(tables, [mod], 470)
            mod.save_patch('outfits', 'outfits.json', {})
            mod.write_file('Anime/ANM_HI_JP.dat/anm10470.lzs', b'fixture')
            with self.assertRaises(ValueError):
                d4unique.check_conflicts(tables, [mod], 470)
            with self.assertRaises(ValueError):
                d4unique.check_conflicts(tables, [], 470, graphics=[472])

    def test_original_resolver_rejects_unsupported_or_mutated_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'backups').mkdir()
            index = {'EXE/disgaea5.exe': {'mode': 'full'}, 'Bad.dat': {'mode': 'created'}}
            (root / 'backups.json').write_text(json.dumps(index))
            path = root / 'backups/EXE__disgaea5.exe.full'
            path.write_bytes(b'original')
            resolver = d4unique.Originals(root)
            self.assertEqual(resolver('EXE/disgaea5.exe'), (None, str(path)))
            self.assertEqual(resolver('Unmodified.dat'), (None, None))
            with self.assertRaises(ValueError):
                resolver('Bad.dat')
            with self.assertRaises(ValueError):
                resolver('../unsafe')
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                resolver.verify()

    def test_output_overlaps_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                d4unique.build(d4_root=root, game_path=root, original_state=root,
                               mods_roots=[root], output_path=root / 'output')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()

class UniqueUpdateTests(unittest.TestCase):
    def test_first_import_and_pinned_recruitment_storage(self):
        from copy import deepcopy
        layered={'Quest.dat':table('Quest.dat',[dict(id=1,sort_order=0)]),'charhelp.dat':table('charhelp.dat',[dict(id=2,char_id=2)])}
        self.assertEqual(d4unique._import_storage(layered),(4000,2,1))
        owner=dict(family=216,quests=[dict(id=223,sort_order=537,reward_type=5,reward_value=216)],help=[dict(id=14727,char_id=14727)],characters=[dict(help_id=14727)])
        bundle=dict(claims={'Quest.dat':{'223':['Owner']},'charhelp.dat':{'14727':['Owner']}},quest_slots={'537':['Owner']})
        self.assertEqual(d4unique._import_storage(layered,owner,bundle,'Owner'),(14727,223,537))
        for scenario in('missing','ambiguous','foreign','occupied-id','occupied-slot','occupied-help'):
            o,b=deepcopy(owner),deepcopy(bundle);t={k:database.load_table(k,v.to_bytes())for k,v in layered.items()}
            if scenario=='missing':o['quests']=[]
            elif scenario=='ambiguous':o['quests']*=2
            elif scenario=='foreign':b['quest_slots']['537']=['Foreign']
            elif scenario=='occupied-id':t['Quest.dat'].rows.append(table('Quest.dat',[dict(id=223,sort_order=1)]).rows[0])
            elif scenario=='occupied-slot':t['Quest.dat'].rows.append(table('Quest.dat',[dict(id=2,sort_order=537)]).rows[0])
            else:t['charhelp.dat'].rows.append(table('charhelp.dat',[dict(id=14727,char_id=14727)]).rows[0])
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):d4unique._import_storage(t,o,b,'Owner')

    def test_public_unique_build_verifies_old_tree_and_forwards_context(self):
        from unittest.mock import patch,Mock
        import hashlib
        from d5lib import sourceimports as si,gamefs,offlinepaths,sprites,slots
        class Boundary(Exception):pass
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);mods=root/'mods';old=modsys.Mod(str(mods/'D4_Unique_70'));old.meta['source_import']=dict(source_game='d4',source_id=70);old.save_meta();old.save_patch('db','char.dat.json',{'added':[{'id':216}]});old.save_patch('db','magic.dat.json',{'added':[{'id':13010}]})
            owner=dict(family=216,skills={},evilities={},source_identity=old.meta['source_import'],baseline_meta_sha256=si.d4_lease_digest(old.meta),baseline_files={str(p.relative_to(old.folder)):hashlib.sha256(p.read_bytes()).hexdigest()for p in Path(old.folder).rglob('*')if p.is_file()})
            b=dict(schema='d4-update-leases/1',owners={old.id:owner},claims={});pin=si.d4_lease_digest(b)
            _,tables=fixture();tables.update({'Quest.dat':table('Quest.dat',[]),'charhelp.dat':table('charhelp.dat',[])})
            from d5lib import script
            script_fixture=script.ScriptFile();script_fixture.events=[script.Event(100,[script.Ins(0x0108)])]
            fs=Mock();fs.read.side_effect=lambda path:script_fixture.to_bytes()if path=='Script/script.dat'else tables[path.rsplit('/',1)[-1]].to_bytes()
            with patch.object(offlinepaths,'require_output_cache'),patch.object(d4unique,'Originals'),patch.object(gamefs,'GameFS',return_value=fs),patch.object(sprites,'used_sprite_numbers',return_value=[]),patch.object(slots,'unique_pool',return_value=[216]),patch.object(d4unique.d4source,'D4Data',return_value=Mock(class_profile=Mock(return_value=[{'id':70}]))),patch.object(d4unique,'plan_import',side_effect=Boundary)as planner:
                args=dict(d4_root=root/'source',game_path=root/'game',original_state=root/'original',mods_roots=[mods],output_path=root/'out',source_id=70,target_id=216,template_id=570,prepared_root=root/'prepared',library_root=root/'library',face_path=root/'face',cutin_path=root/'cutin',mapping={},previous_leases=b,previous_leases_sha256=pin,owner_mod_id=old.id)
                with self.assertRaises(Boundary):d4unique.build_import(**args)
                self.assertIs(planner.call_args.kwargs['previous_leases'],b);self.assertIn(13010,planner.call_args.kwargs['reserved_skills'])
                old.save_patch('db','char.dat.json',{'added':[{'id':217}]})
                with self.assertRaisesRegex(ValueError,'payload/patch drift'):d4unique.build_import(**args)
