"""Reviewed DD2 ability mapping and product-text rules (offline, synthetic packets)."""
import unittest
from pathlib import Path

from d5lib import nativeimports

EDITION = 'Explicit source edition'


def sourcemap(**changes):
    data: dict = dict(schema=1, game='dd2', edition=EDITION,
                allocations=dict(skills={'12181': 39101, '32181': 39107},
                                 evilities={'2180': 9101, '2181': 9102}),
                skills={'12181': dict(copy_of=12131, copy_of_name='Bubble Cutter', relation='adapted'),
                        '32181': dict(relation='omit', reason='Mounted only')},
                evilities={'2180': dict(works_like=4016, works_like_name='Water Management', relation='exact'),
                           '2181': dict(works_like=10, works_like_name='War Demon', relation='lookalike')},
                voice=dict(status='unproven'))
    data.update(changes)
    return data


def packet():
    return dict(game='dd2', edition=EDITION, name='Shark Dragon',
                skills=[dict(id=12181, name='Shark Slider', description='Unique\uff1a%s A shark\uff0e'),
                        dict(id=32181, name='Jaws Wave Rider', description='Mounted\uff1a%s Surfs up\uff01')],
                evilities=[dict(id=2180, name='Water Dominance', description='Nullify water\uff0e'),
                           dict(id=2181, name='Cold Charge', description='Stats per water skill\uff0e')])


VANILLA = {'skills': {12131}, 'evilities': {4016, 10}}


class AbilityPlanTests(unittest.TestCase):
    def test_adapter_keeps_donor_text_and_exact_uses_source_text(self):
        plan = nativeimports.ability_plan(packet(), sourcemap(), VANILLA,
                                          {'skills': set(), 'evilities': set()})
        skills = {e['source_id']: e for e in plan['skills']}
        evilities = {e['source_id']: e for e in plan['evilities']}
        self.assertEqual(skills[12181]['id'], 39101)
        # a skill row carries the source name, so it carries the source text too (folded)
        self.assertEqual(skills[12181]['desc'], 'A shark.')
        self.assertEqual(evilities[2180]['desc'], 'Nullify water.')   # exact: source text, folded
        self.assertIsNone(evilities[2181]['desc'])        # lookalike: donor text
        self.assertEqual(plan['aliases'], {'9101': 4016, '9102': 10})

    def test_omitted_ids_are_recorded_with_a_reason(self):
        plan = nativeimports.ability_plan(packet(), sourcemap(), VANILLA,
                                          {'skills': set(), 'evilities': set()})
        self.assertEqual([(e['kind'], e['source_id'], e['reason']) for e in plan['omitted']],
                         [('skill', 32181, 'Mounted only')])
        self.assertNotIn(32181, [e['source_id'] for e in plan['skills']])

    def test_unmapped_source_id_refuses(self):
        data = sourcemap()
        del data['skills']['12181']
        with self.assertRaisesRegex(ValueError, 'Unmapped DD2 skill 12181'):
            nativeimports.ability_plan(packet(), data, VANILLA, {'skills': set(), 'evilities': set()})

    def test_allocated_or_claimed_product_id_refuses(self):
        with self.assertRaisesRegex(ValueError, 'already taken'):
            nativeimports.ability_plan(packet(), sourcemap(), {'skills': {39101}, 'evilities': set()},
                                       {'skills': set(), 'evilities': set()})
        with self.assertRaisesRegex(ValueError, 'already taken'):
            nativeimports.ability_plan(packet(), sourcemap(), {'skills': set(), 'evilities': set()},
                                       {'skills': {39101}, 'evilities': set()})

    def test_missing_product_allocation_refuses(self):
        data = sourcemap()
        data['allocations']['skills'] = {}
        with self.assertRaisesRegex(ValueError, 'No reviewed product id'):
            nativeimports.ability_plan(packet(), data, {'skills': set(), 'evilities': set()},
                                       {'skills': set(), 'evilities': set()})

    def test_edition_mismatch_refuses(self):
        data = sourcemap(edition='Other edition')
        with self.assertRaisesRegex(ValueError, 'edition'):
            nativeimports.ability_plan(packet(), data, VANILLA, {'skills': set(), 'evilities': set()})


class RankAbilityTests(unittest.TestCase):
    def plan(self):
        return nativeimports.ability_plan(packet(), sourcemap(), VANILLA,
                                          {'skills': set(), 'evilities': set()})

    def test_rank_learn_list_uses_product_ids_and_levels(self):
        ranks = [dict(id=2180, learn=[[12181, 8], [32181, 1]], evilities=[])]
        out = nativeimports.rank_abilities(self.plan(), ranks, generic=True)
        self.assertEqual(out[0]['learn'], [(39101, 8)])   # the omitted skill never reaches the row
        self.assertEqual(out[0]['innate'], [])            # class evilities are shop-learned

    def test_unique_keeps_innate_evilities(self):
        ranks = [dict(id=80, learn=[], evilities=[2180, 2181])]
        out = nativeimports.rank_abilities(self.plan(), ranks, generic=False)
        self.assertEqual(out[0]['innate'], [9101, 9102])

    def test_learn_slot_overflow_refuses(self):
        ranks = [dict(id=2180, learn=[[12181, 1]] * 17, evilities=[])]
        with self.assertRaisesRegex(ValueError, '16 learn slots'):
            nativeimports.rank_abilities(self.plan(), ranks, generic=True)


class ProductTextTests(unittest.TestCase):
    def test_fullwidth_punctuation_and_source_tags_fold(self):
        self.assertEqual(nativeimports.product_text('Unique\uff1a%s A shark\uff0e'), 'A shark.')
        self.assertEqual(nativeimports.product_text('A mysterious\uff0c young demon\uff0e'),
                         'A mysterious, young demon.')
        self.assertEqual(nativeimports.product_text('Increase by %d\uff05\uff1a done\uff01'),
                         'Increase by %d%: done!')

    def test_folding_is_display_only_for_source_lines(self):
        source = ['A ferocious shark dragon\uff0e', '', '']
        lines = nativeimports.dbpatch.help_lines([nativeimports.product_text(x) for x in source])
        self.assertEqual(lines[0], 'A ferocious shark dragon.')
        self.assertEqual(source[0], 'A ferocious shark dragon\uff0e')   # the raw line is untouched

    def test_d4_text_is_unchanged(self):
        self.assertEqual(nativeimports.product_text('A plain ASCII line.'), 'A plain ASCII line.')


class SourceMapOnThisBranchTest(unittest.TestCase):
    """The DD2 route exists on the integration branch: map in place, and no map = no ability route.

    Found by rebuilding the DD2 slice pack against `integration/next`: the merged `nativeimports` came
    from the D1 Complete lane and silently dropped the packet's skills (``learned_skills: []``, no
    ``learn``/``innate`` in the receipt), so the pack's own validator refused it. The ability machinery
    and the reviewed map are now on the same branch; D1 Complete keeps its caller-supplied `skills`
    plan because there is no reviewed map for it.
    """

    def setUp(self):
        self.root = Path(nativeimports.__file__).resolve().parents[1]

    def test_the_reviewed_dd2_map_is_on_this_branch(self):
        data = nativeimports.load_sourcemap('dd2')
        self.assertEqual((data['schema'], data['game']), (1, 'dd2'))
        self.assertTrue(data.get('edition'))
        self.assertTrue(data.get('allocations', {}).get('skills'))

    def test_the_map_file_is_shipped_next_to_the_module(self):
        self.assertTrue((self.root / 'd5lib' / 'sourcemaps' / 'dd2.json').is_file())

    def test_a_source_without_a_reviewed_map_cannot_take_the_ability_route(self):
        with self.assertRaises(ValueError):
            nativeimports.load_sourcemap('nope')
        # d1c has a learn-list map since UNIQUESKILLS1, but it is not an ability map
        for game in ('d1c', 'nope'):
            with self.assertRaises(ValueError):
                nativeimports.ability_sourcemap(game)
        self.assertIn('skills', nativeimports.ability_sourcemap('dd2'))


if __name__ == '__main__':
    unittest.main()


def test_claims_skip_the_pack_being_rebuilt(tmp_path):
    """DD2-FIX1.5: the installed/held copy of the pack itself is not a competing lease claim."""
    import json
    from d5lib.importers import _dd2_abilities as ab
    for name in ('DD2_Class_22520', 'DD2_Class_22540'):
        folder = tmp_path / name
        (folder / 'patches/db').mkdir(parents=True)
        (folder / 'mod.json').write_text('{}')
        (folder / 'patches/db/Skill.dat.json').write_text(json.dumps({'added': [{'id': 26020}]}))
    assert ab._claims(tmp_path)[26020] == ['DD2_Class_22520', 'DD2_Class_22540']
    assert ab._claims(tmp_path, skip='DD2_Class_22520')[26020] == ['DD2_Class_22540']


def test_baseline_copy_drops_the_references_reviewed_evility_rows(tmp_path):
    """DD2-FIX1.5b: a reference carrying the reviewed layer must not seed the rebuild with its leases."""
    import json
    from d5lib.importers._dd2_baseline import drop_reviewed_evilities
    ref = tmp_path / 'held'
    ref.mkdir()
    (ref / 'COREDD2-ABILITIES.json').write_text(json.dumps({'added_evility_ids': [26020]}))
    skill = tmp_path / 'Skill.dat.json'
    skill.write_text(json.dumps({'added': [{'id': 26020}, {'id': 9999}]}))
    assert drop_reviewed_evilities(ref, skill, 'patches/db/Skill.dat.json') == 1
    assert json.loads(skill.read_text())['added'] == [{'id': 9999}]
    alias = tmp_path / 'aliases.json'
    alias.write_text(json.dumps({'26020': 5, '7': 1}))
    assert drop_reviewed_evilities(ref, alias, 'patches/evilities/aliases.json') == 1
    assert json.loads(alias.read_text()) == {'7': 1}
