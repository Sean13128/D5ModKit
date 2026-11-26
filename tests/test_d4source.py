"""D4 source readers and the D4 profile planner on synthetic bytes (no game data)."""
import struct
import tempfile
import unittest
from pathlib import Path

from d5lib import d4source, newclasses, voices
from d5lib.importers._d4_source import TextPool
from d5lib.sourceimports import load_d4_mapping as _load_d4_mapping, plan_d4_profile

# The reviewed map stores game text as SHA-256 references.  These tests build their own synthetic D4 bytes, so they
# resolve only the few strings their data and assertions name; any other reference stays an unresolved marker.
SYNTHETIC_TEXT = TextPool(['Aegis', 'Last Fortress', 'Advance Guard', 'Spear Defense', 'Lift Catch', 'Lift'])


def load_d4_mapping():
    return _load_d4_mapping(pool=SYNTHETIC_TEXT, lenient=True)


def nsac(members):
    names = b"".join(struct.pack("<HII", len(n), 0, 0) + n.encode() + b"\0" for n in members)
    index_size, data_at = len(members) * 10, None
    data_at = 28 + index_size + len(names)
    offsets, pos = [], data_at
    for data in members.values():
        offsets.append(pos)
        pos += len(data)
    names = b"".join(struct.pack("<HII", len(n), o, len(d)) + n.encode() + b"\0"
                     for (n, d), o in zip(members.items(), offsets))
    index = b"".join(struct.pack("<HII", i, o, len(d)) for i, ((n, d), o) in enumerate(zip(members.items(), offsets)))
    head = struct.pack("<4sHH5I", b"NSAC", 2, len(members), pos, data_at, index_size, len(names), 0)
    return head + index + names + b"".join(members.values())


def char_row(cid, tier, evilities, skills=((13081, 10),), gender=11):
    r = bytearray(d4source.CHAR_STRIDE)
    struct.pack_into("<8H", r, 0x4, 32, 8, 14, 18, 6, 6, 12, 14)        # native order: SPD before RES
    for n, (s, l) in enumerate(skills):
        struct.pack_into("<H", r, 0x14 + 2 * n, s)
        struct.pack_into("<H", r, 0x34 + 2 * n, l)
    struct.pack_into("<H", r, 0x194, cid)
    struct.pack_into("<HHH", r, 0x1A4, 3, 0, 1)
    struct.pack_into("<H", r, 0x1B4, 392)
    for n, e in enumerate(evilities):
        struct.pack_into("<H", r, 0x1BE + 2 * n, e)
        struct.pack_into("<H", r, 0x1DE + 2 * n, 1)
    r[0x1FE:0x1FE + 12] = b"Armor Knight"
    r[0x23E:0x23E + 5] = b"Title"
    r[0x27E:0x286] = bytes([120, 80, 110, 130, 70, 70, 100, 110])
    struct.pack_into("<bbb", r, 0x28E, -25, 25, 25)
    r[0x292], r[0x294], r[0x296], r[0x299], r[0x29A], r[0x29D] = gender, tier, 15, 6, 2, 6 + tier
    return bytes(r)


def table(rows, stride):
    return struct.pack("<I", len(rows)) + b"".join(r.ljust(stride, b"\0") for r in rows)


def evility(eid, name, mana=100):
    r = bytearray(d4source.EVILITY_STRIDE)
    struct.pack_into("<IH", r, 0, mana, 0)
    struct.pack_into("<H", r, 8, eid)
    r[15:15 + len(name)] = name.encode()
    return bytes(r)


def skill(sid, name):
    r = bytearray(d4source.SKILL_STRIDE)
    struct.pack_into("<I", r, 40, sid)
    r[56:60] = b"desc"
    r[184:184 + len(name)] = name.encode()
    return bytes(r)


class Rows:
    def __init__(self, ids):
        self.rows = [{"id": i} for i in ids]


class D4SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        lists = [[228], [228], [228, 391], [228, 391], [228, 391, 85], [228, 391, 85, 62]]
        chars = table([char_row(1080 + k, k, lists[k]) for k in range(6)], d4source.CHAR_STRIDE)
        ev = table([evility(392, "Aegis", 0xFFFFFFFF), evility(228, "Last Fortress", 1000), evility(391, "Advance Guard"),
                    evility(85, "Spear Defense"), evility(62, "Mind Mastery")], d4source.EVILITY_STRIDE)
        mg = table([skill(13081, "Lift Catch")], d4source.SKILL_STRIDE)
        db = root / d4source.DATABASE.format(lang="EN")
        db.parent.mkdir(parents=True)
        db.write_bytes(nsac({"char.dat": chars, "mskill.dat": ev, "magic.dat": mg}))
        self.d4 = d4source.D4Data(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_body_type_is_independent_of_unique_gender_and_art(self):
        raw = bytearray(char_row(180, 0, [], gender=2))
        raw[0x298] = 1
        decoded = d4source.decode_char(bytes(raw))
        self.assertEqual((decoded['body_type'], decoded['kind_gender']), (1, 2))
        raw[0x298] = 0
        self.assertEqual(d4source.decode_char(bytes(raw))['body_type'], 0)

    def test_decodes_battle_profile_and_canonical_stats(self):
        prof = self.d4.class_profile(1080)
        self.assertEqual(prof[0]["base"], [32, 8, 14, 18, 6, 14, 12, 6])            # RES/SPD swapped back
        self.assertEqual(prof[0]["aptitudes"][5], 110)
        self.assertEqual(prof[0]["battle"], dict(MOV=3, move_type=0, attack_range=1, JMP=15, throw=6, counter=2,
                                                 crit=6, res_fire=-25, res_wind=25, res_ice=25, kind_gender=11, body_type=0))
        self.assertEqual(prof[5]["battle"]["crit"], 11)
        self.assertEqual(prof[0]["innate_evility"]["name"], "Aegis")
        self.assertEqual([e["name"] for e in prof[4]["evilities"]], ["Last Fortress", "Advance Guard", "Spear Defense"])
        self.assertEqual([(s["name"], s["level"]) for s in prof[0]["skills"]], [("Lift Catch", 10)])

    def test_plan_maps_innate_evilities_per_rank_and_omits_generic(self):
        prof = self.d4.class_profile(1080)
        plan = plan_d4_profile(prof, load_d4_mapping(), family=1350,
                               template_rows=[{"kind_gender": 12}] * 6,
                               skill_table=Rows([12, 6082, 1152, 53]), magic_table=Rows([915, 1502]))
        r1, r6 = plan["ranks"][0], plan["ranks"][5]
        self.assertEqual(r1["kind_gender"], 11)                                       # tens digit from D5, male from D4
        self.assertEqual(r1["evility_count"], 1)                                      # built in: Aegis only
        self.assertEqual(r6["evility_count"], 1)
        shop = {e["name"]: (e["mana"], e["first_rank"]) for e in plan["evilities"] if not e["unique"]}
        self.assertEqual(shop, {"Last Fortress": (1000, 1), "Advance Guard": (100, 3), "Spear Defense": (100, 5)})
        self.assertEqual(r1["learn_count"], 0)                                        # Lift Catch: omitted (tested)
        self.assertIn(("skill", "omitted"), {(x["kind"], x["status"]) for x in plan["report"]})
        self.assertEqual({e["name"]: e["unique"] for e in plan["evilities"]},
                         {"Aegis": True, "Last Fortress": False, "Advance Guard": False, "Spear Defense": False})
        aliases = {e["name"]: e["works_like"] for e in plan["evilities"]}
        self.assertEqual(aliases, {"Aegis": 12, "Last Fortress": 6082, "Advance Guard": 1152, "Spear Defense": 53})
        self.assertIn("omitted", {x["status"] for x in plan["report"]})

    def test_plan_refuses_missing_d5_target(self):
        with self.assertRaises(ValueError):
            plan_d4_profile(self.d4.class_profile(1080), load_d4_mapping(), family=1350,
                            template_rows=[{"kind_gender": 12}] * 6,
                            skill_table=Rows([12]), magic_table=Rows([915, 1502]))

    def test_batch_reserved_ids_and_placeholder_do_not_silently_alias(self):
        prof = self.d4.class_profile(1080)
        mapping = load_d4_mapping()
        mapping['evilities']['228'] = dict(relation='placeholder', display_name='[Unavailable D4] Last Fortress',
                                            reason='No reviewed equivalent')
        plan = plan_d4_profile(prof, mapping, family=14080,
                               template_rows=[{'kind_gender': 12}] * 6,
                               skill_table=Rows([12, 1152, 53]), magic_table=Rows([]),
                               reserved_evilities=(7000, 7001), reserved_skills=(13000,))
        self.assertEqual(plan['evilities'][0]['id'], 7002)
        self.assertNotIn('Last Fortress', [e['name'] for e in plan['evilities']])
        gap = next(r for r in plan['report'] if r['d4_id'] == 228)
        self.assertEqual(gap['status'], 'placeholder')
        self.assertEqual(gap['display_name'], '[Unavailable D4] Last Fortress')

    def test_unmapped_entries_are_reported_not_guessed(self):
        mapping = load_d4_mapping()
        mapping = dict(mapping, evilities={}, skills={})
        plan = plan_d4_profile(self.d4.class_profile(1080), mapping, family=1350,
                               template_rows=[{"kind_gender": 12}] * 6, skill_table=Rows([]), magic_table=Rows([]))
        self.assertEqual(plan["ranks"][0]["evility_count"], 0)
        self.assertTrue(all(x["status"] == "unmapped" for x in plan["report"]))


class KitOptionTests(unittest.TestCase):
    def test_unlocked_ranks(self):
        # the 1.5.8 port unlocks all six ranks by default (docs/CLASSES.md; tests/test_recruit_ranks.py)
        self.assertEqual(newclasses.auto_ranks(1350, {"unlocked": True}), list(range(1350, 1356)))
        self.assertEqual(newclasses.auto_ranks(1350, {"unlocked": True, "unlocked_ranks": 6}), list(range(1350, 1356)))
        self.assertEqual(newclasses.auto_ranks(1350, {"unlocked": False, "unlocked_ranks": 6}), [])

    def test_voice_lines_per_personality(self):
        voice = {"lines": [{"kind": 0, "cats": [0], "file": "a.vag", "personality": 1},
                           {"kind": 0, "cats": [1], "file": "b.vag"}]}
        by_p = {}
        for line, ref in voices.custom_lines(9000, voice):
            by_p.setdefault(voices.split_set(line.group)[2], []).append(ref[1])
        self.assertEqual(by_p, {0: ["b.vag"], 1: ["a.vag", "b.vag"], 2: ["b.vag"]})


if __name__ == "__main__":
    unittest.main()


class ColourTests(unittest.TestCase):
    def test_map_source_palettes_per_colour(self):
        import numpy as np
        from d5lib import anm
        from d5lib.sourceimports import map_source_palettes
        f = anm.AnmFile([], [], [])
        base = np.zeros((256, 4), np.uint8)
        base[1] = (10, 20, 30, 255)
        base[2] = (40, 50, 60, 255)
        base[3] = (1, 2, 3, 255)                          # not a source colour
        for _ in range(3):
            anm.set_palette(f, len(f.palettes), base)
        src = [np.zeros((256, 4), np.uint8) for _ in range(3)]
        for k in range(3):
            src[k][7] = (10 + k, 20, 30, 255) if k else (10, 20, 30, 255)
            src[k][9] = (40, 50 + k, 60, 255) if k else (40, 50, 60, 255)
        self.assertEqual(map_source_palettes(f, src), (2, 1))
        self.assertEqual(tuple(anm.get_palette(f, 2)[1][:3]), (12, 20, 30))
        self.assertEqual(tuple(anm.get_palette(f, 1)[2][:3]), (40, 51, 60))
        self.assertEqual(tuple(anm.get_palette(f, 2)[3][:3]), (1, 2, 3))

    def test_ambiguous_colour_the_sprite_does_not_use_is_not_an_error(self):
        """Two source entries may share one bank-0 RGB and diverge later; only a colour a pixel
        actually carries is ambiguous (DD2 Laharl/Flonne gate, 2026-10-30)."""
        import numpy as np
        from d5lib import anm
        from d5lib.sourceimports import map_source_palettes
        f = anm.AnmFile([], [], [])
        base = np.zeros((256, 4), np.uint8)
        base[1] = (10, 20, 30, 255)
        for _ in range(2):
            anm.set_palette(f, len(f.palettes), base)
        src = [np.zeros((256, 4), np.uint8) for _ in range(2)]
        src[0][7] = (10, 20, 30, 255)                     # the colour the sprite carries
        src[0][40] = (5, 6, 7, 255)
        src[0][41] = (5, 6, 7, 255)                       # same RGB, two indices, unused
        src[1][7] = (200, 0, 0, 255)
        src[1][40] = (90, 0, 0, 255)
        src[1][41] = (0, 0, 90, 255)                      # ... that diverge in bank 1
        report = {}
        self.assertEqual(map_source_palettes(f, src, report=report), (1, 0))
        self.assertEqual(report['ambiguous_used_colours'], 0)
        self.assertEqual(report['dropped_banks'], [])
        self.assertEqual(tuple(anm.get_palette(f, 1)[1][:3]), (200, 0, 0))

    def test_exact_banks_drop_a_conflicting_alternate_and_keep_bank_zero(self):
        import numpy as np
        from d5lib import anm
        from d5lib.sourceimports import map_source_palettes
        f = anm.AnmFile([], [], [])
        base = np.zeros((256, 4), np.uint8)
        base[1] = (10, 20, 30, 255)
        for _ in range(3):
            anm.set_palette(f, len(f.palettes), base)
        src = [np.zeros((256, 4), np.uint8) for _ in range(3)]
        for k in range(3):
            src[k][7] = (10, 20, 30, 255)
        src[0][9] = (10, 20, 30, 255)                     # index 9 also carries the colour
        src[1][7] = (90, 20, 30, 255)
        src[1][9] = (90, 20, 30, 255)                     # bank 1 agrees -> exact
        src[2][7] = (250, 0, 0, 255)
        src[2][9] = (0, 0, 250, 255)                      # bank 2 diverges -> no exact colour
        report = {}
        self.assertEqual(map_source_palettes(f, src, exact_banks=True, report=report), (1, 0))
        self.assertEqual(report['dropped_banks'], [2])
        self.assertEqual(tuple(anm.get_palette(f, 1)[1][:3]), (90, 20, 30))
        self.assertEqual(tuple(anm.get_palette(f, 2)[1][:3]), (10, 20, 30))

    def test_colour_variants(self):
        from d5lib.sourceimports import colour_variants
        with tempfile.TemporaryDirectory() as td:
            for k in range(10):
                d = Path(td) / f"ANM_HI__anm1108{k}"
                d.mkdir()
                (d / "p0.png").write_bytes(b"x")
            got = colour_variants(Path(td) / "ANM_HI__anm11080" / "p0.png", 11080)
            self.assertEqual([Path(p).parent.name for p in got], [f"ANM_HI__anm1108{k}" for k in range(10)])
            self.assertIsNone(colour_variants(Path(td) / "ANM_HI__anm11080" / "p0.png", 11080, colours=11))


class StableUpdateTests(unittest.TestCase):
    def fixture(self):
        from d5lib.sourceimports import d4_lease_digest
        profile = [dict(id=1080, battle={'kind_gender':11},
            innate_evility={'id':5,'name':'Old Evility'},evilities=[],
            skills=[dict(id=1,name='Earlier',level=2),dict(id=2,name='Existing',level=9)])]
        evidence = lambda n: dict(uid='fixture:'+str(n),sha256='a'*64)
        mapping = dict(skills={str(n):dict(relation='adapted',d4_name=str(n),copy_of=915,
                       source_evidence=evidence(n))for n in(1,2)},
                       evilities={'5':dict(relation='adapted',d4_name='Old Evility',works_like=12,
                       source_evidence=evidence(5))})
        owner=dict(family=14080,source_ids=[1080],profile_sha256=d4_lease_digest(profile),
            sources=dict(skills={str(n):evidence(n)for n in(1,2)},evilities={'5':evidence(5)}),
            skills={'2':dict(evidence(2),id=13055,donor=915,row_sha256='b'*64)},
            evilities={'5':dict(evidence(5),id=7005,donor=12,row_sha256='c'*64)})
        bundle=dict(schema='d4-update-leases/1',owners={'Owner':owner},claims={
            'magic.dat':{'13000':['Disabled'],'13001':['Other'],'13055':['Owner']},
            'Skill.dat':{'7005':['Owner']}})
        return profile,mapping,bundle

    def plan(self, profile, mapping, bundle, **options):
        from d5lib.sourceimports import d4_lease_digest
        return plan_d4_profile(profile,mapping,family=14080,template_rows=[{'kind_gender':12}],
            magic_table=Rows([915]),skill_table=Rows([12]),previous_leases=bundle,
            previous_leases_sha256=options.pop('pin',d4_lease_digest(bundle)),
            owner_mod_id=options.pop('owner','Owner'),**options)

    def test_earlier_mapping_preserves_old_ability_ids_and_reserves_foreign_ids(self):
        p,m,b=self.fixture();got=self.plan(p,m,b)
        self.assertEqual([x['id']for x in got['skills']],[13002,13055])
        self.assertEqual(got['evilities'][0]['id'],7005)
        self.assertEqual([(got['ranks'][0][f'learn{n}_skill'],got['ranks'][0][f'learn{n}_level'])for n in(1,2)],[(13002,2),(13055,9)])
        default=plan_d4_profile(p,m,family=14080,template_rows=[{'kind_gender':12}],magic_table=Rows([915]),skill_table=Rows([12]))
        self.assertEqual([x['id']for x in default['skills']],[13000,13001])

    def test_update_refuses_omitted_mismatched_foreign_and_duplicate_leases(self):
        from copy import deepcopy
        for scenario in ('pin','owner','profile','omit','uid','donor','foreign','duplicate','new-source'):
            p,m,b=self.fixture();options={}
            if scenario=='pin':options['pin']='0'*64
            elif scenario=='owner':options['owner']='Foreign'
            elif scenario=='profile':p[0]['skills'][1]['level']=10
            elif scenario=='omit':m['skills']['2']['relation']='omit'
            elif scenario=='uid':m['skills']['2']['source_evidence']['uid']='foreign'
            elif scenario=='donor':m['skills']['2']['copy_of']=1502
            elif scenario=='foreign':b['claims']['magic.dat']['13055']=['Other']
            elif scenario=='duplicate':b['owners']['Owner']['skills']['1']=deepcopy(b['owners']['Owner']['skills']['2'])
            elif scenario=='new-source':m['skills']['1']['source_evidence']['sha256']='f'*64
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):self.plan(p,m,b,**options)

    def test_existing_target_bytes_must_match_prior_row(self):
        from d5lib.sourceimports import d4_lease_digest
        p,m,b=self.fixture()
        with self.assertRaisesRegex(ValueError,'original table required'):
            plan_d4_profile(p,m,family=14080,template_rows=[{'kind_gender':12}],
                magic_table=Rows([915,13055]),skill_table=Rows([12]),previous_leases=b,
                previous_leases_sha256=d4_lease_digest(b),owner_mod_id='Owner')

    def test_public_generic_build_forwards_pinned_context_before_art_emission(self):
        from unittest.mock import patch,Mock
        from PIL import Image
        from d5lib import sourceimports as si,database,gamefs,offlinepaths
        class Boundary(Exception):pass
        p,m,b=self.fixture();p=[dict(p[0],id=1080+k,base=[1]*8,aptitudes=[100]*8)for k in range(6)]
        o=b['owners']['Owner'];o['source_ids']=[r['id']for r in p];o['profile_sha256']=si.d4_lease_digest(p)
        def raw(name,rows=()):
            t=database.load_table(name,bytes(database.get_schema(name).header_size))
            for fields in rows:
                row=t.new_row()
                for k,v in fields.items():row.set(k,v)
                t.rows.append(row)
            return t.to_bytes()
        chars=raw('char.dat',[dict(id=1010+k,kind_gender=11)for k in range(6)])
        from d5lib import script
        script_fixture=script.ScriptFile();script_fixture.events=[script.Event(100,[script.Ins(0x0108)])];empty_script=script_fixture.to_bytes()
        fs=Mock();fs.read.side_effect=lambda path:empty_script if path=='Script/script.dat'else chars if path==newclasses.CHAR else raw('Skill.dat'if path==newclasses.SKILL else'magic.dat')
        poses=('stand','wait','walk','damage','attack_fist','attack_sword','attack_lance','attack_arrow','attack_gun','attack_ax')
        prepared=dict(identity=dict(character_id=1080,body=1080),sequences={(x,y):[]for x in poses for y in('front','back')})
        ranks=[dict(r,body=1080,name='Fixture',title='Rank')for r in p]
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);image=root/'fixture.png';Image.new('RGBA',(1,1),(1,2,3,255)).save(image)
            with patch.object(si,'read_prepared',return_value=prepared),patch.object(si,'read_d4_ranks',return_value=ranks),patch.object(d4source,'D4Data',return_value=Mock(chars={1080:{'help_id':1}},class_profile=Mock(return_value=p))),patch.object(offlinepaths,'require_output_cache'),patch.object(gamefs,'GameFS',return_value=fs),patch.object(si,'plan_d4_profile',side_effect=Boundary)as planner:
                args=dict(prepared_root=root/'prepared',library_root=root/'library',source_archive=root/'archive',game_path=root/'game',face_path=image,cutin_path=image,output_path=root/'output',family=14080,template=1010,sprite_family=1270,supported_families=[14080],source_ids=o['source_ids'],edition='fixture',source_root=root/'source',mapping=m,mod_id='Owner',backup_resolver=lambda path:(None,None),previous_leases=b,previous_leases_sha256=si.d4_lease_digest(b),owner_mod_id='Owner')
                with self.assertRaises(Boundary):si.build_d4_pilot(**args)
                self.assertIs(planner.call_args.kwargs['previous_leases'],b);self.assertEqual(planner.call_args.kwargs['owner_mod_id'],'Owner')
                from d5lib import charstudio
                with patch.object(charstudio,'all_mod_skill_ids',return_value={13055}),self.assertRaisesRegex(ValueError,'original event'):si.build_d4_pilot(**args)
                self.assertEqual(planner.call_count,1)

    def test_update_cli_validation_and_existing_build_forwarding(self):
        import contextlib,io,json,importlib.util,os
        from unittest.mock import patch
        from d5lib import sourceimports as si,d4unique,d4expansion,modsys,sprites,runtime
        class Boundary(Exception):pass
        _,_,bundle=self.fixture()
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);lease=root/'leases.json';lease.write_text(json.dumps(bundle));pin=si.d4_lease_digest(bundle)
            self.assertEqual(si.d4_update_options(),{})
            for kwargs in(dict(path=lease),dict(expected_sha256=pin),dict(path=lease,expected_sha256='0'*64,owner_mod_id='Owner'),dict(path=lease,expected_sha256=pin)):
                with self.assertRaises(ValueError):si.d4_update_options(**kwargs)
            state=root/'original';state.mkdir();(state/'backups.json').write_text('{}')
            base=['--game-path',str(root/'game'),'--output-path',str(root/'out')]
            cases=[('build_source_pack',si,'build_d4_pilot',base+['--prepared-root',str(root/'prepared'),'--library-root',str(root/'library'),'--source-archive',str(root/'archive'),'--face-path',str(root/'face'),'--cutin-path',str(root/'cutin'),'--family','14080','--template','1010','--supported-families','14080','--source-ids',*map(str,range(1080,1086)),'--edition','fixture','--original-state',str(state)]),('build_d4_unique',d4unique,'build_import',base+['--d4-root',str(root/'source'),'--original-state',str(root/'original'),'--mods-root',str(root/'mods'),'--source-id','70','--template-id','570','--prepared-root',str(root/'prepared'),'--library-root',str(root/'library'),'--face-path',str(root/'face'),'--cutin-path',str(root/'cutin')]),('build_d4_expansion',d4expansion,'build',base+['--original-state',str(root/'original'),'--current-kit',str(root/'kit'),'--build','entry',str(root/'accepted')])]
            for name,module,method,args in cases:
                spec=importlib.util.spec_from_file_location(name,Path(__file__).parents[1]/'tools'/f'{name}.py');tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
                cli=args+['--previous-leases',str(lease),'--previous-leases-sha256',pin]+([]if name=='build_d4_expansion'else['--owner-mod-id','Owner'])
                with self.subTest(tool=name),patch('sys.argv',[name,*cli]),patch('sys.addaudithook'),patch.dict(os.environ,{}),patch.object(tempfile,'tempdir',str(root)),patch.object(modsys,'load_handlers'),patch.object(sprites,'CACHE_DIR',str(root/'absent-cache')),patch.object(runtime,'CACHE',str(root/'absent-cache')),patch.object(module,method,side_effect=Boundary)as build,contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(Boundary):tool.main()
                    self.assertEqual(build.call_args.kwargs['previous_leases'],bundle);self.assertEqual(build.call_args.kwargs['previous_leases_sha256'],pin)
                if name=='build_source_pack':
                    absent=list(cli);n=absent.index('--original-state');del absent[n:n+2]
                    with patch('sys.argv',[name,*absent]),patch.object(module,method)as build,contextlib.redirect_stderr(io.StringIO())as errors:
                        with self.assertRaises(SystemExit):tool.main()
                        self.assertIn('require --original-state',errors.getvalue());build.assert_not_called()
                with patch('sys.argv',[name,*args,'--previous-leases',str(lease),'--previous-leases-sha256','0'*64]),patch.object(module,method)as build,contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):tool.main()
                    build.assert_not_called()

    def test_matching_prior_native_row_hash_still_refuses_original_input(self):
        import hashlib
        from d5lib import database
        from d5lib.sourceimports import d4_lease_digest
        for kind,name,oldid,donor in [('skills','magic.dat',13055,915),('evilities','Skill.dat',7005,12)]:
            p,m,b=self.fixture();t=database.load_table(name,bytes(database.get_schema(name).header_size));row=t.new_row();row.set('id',oldid);t.rows.append(row)
            lease=next(iter(b['owners']['Owner'][kind].values()));lease['row_sha256']=hashlib.sha256(row.raw).hexdigest()
            with self.subTest(table=name),self.assertRaisesRegex(ValueError,'original table required'):
                plan_d4_profile(p,m,family=14080,template_rows=[{'kind_gender':12}],magic_table=t if kind=='skills'else Rows([915]),skill_table=t if kind=='evilities'else Rows([12]),previous_leases=b,previous_leases_sha256=d4_lease_digest(b),owner_mod_id='Owner')

    def test_generic_update_requires_original_resolver_before_any_build_work(self):
        from unittest.mock import patch
        from d5lib import sourceimports as si
        p,m,b=self.fixture()
        with patch.object(si,'read_prepared')as read:
            with self.assertRaisesRegex(ValueError,'original backup resolver'):
                si.build_d4_pilot(prepared_root='fixture',library_root='fixture',source_archive='fixture',game_path='fixture',face_path='fixture',cutin_path='fixture',output_path='fixture',family=14080,template=1010,supported_families=[14080],source_ids=[1080],edition='fixture',source_root='fixture',mod_id='Owner',previous_leases=b,previous_leases_sha256=si.d4_lease_digest(b),owner_mod_id='Owner')
            read.assert_not_called()

    def test_own_prior_wrappers_reserve_new_ids_without_renumbering_pinned_skill(self):
        from d5lib import charstudio,modsys,d4expansion
        p,m,b=self.fixture()
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);own=modsys.Mod(str(root/'Owner'));own.save_patch('skills','skills.json',{'skills':{'13055':{'choreography':15000001}}})
            blocked=charstudio.all_mod_skill_ids([own]);self.assertIn(13055,blocked)
            got=self.plan(p,m,b,reserved_skills=blocked);self.assertEqual([s['id']for s in got['skills']],[13002,13055])
            other=modsys.Mod(str(root/'Foreign'));eid=12113055;other.save_patch('script','script.json',{'events':{str(eid):f'event {eid}\n    wait_children\n'}})
            with self.assertRaisesRegex(ValueError,'allocation conflicts'):d4expansion.preflight(None,[own],[other])
