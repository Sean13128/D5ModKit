"""Source-neutral rank evidence and native static-field integration controls."""
import copy
import unittest

from d5lib import database, nativeimports, sourcefidelity


def packet(count=6):
    ranks = [dict(id=2180+k, name='Shark Dragon', title='Source rank '+str(k),
                  base=[28+k]*8, aptitudes=[110+k]*8, growth=[28+k]*8,
                  evidence=dict(table_sha256='a'*64, row_sha256=str(k)*64)) for k in range(count)]
    bindings = [dict(id=r['id'], body=2180, palette=k, row_sha256=r['evidence']['row_sha256'])
                for k, r in enumerate(ranks)]
    source = dict(game='dd2', edition='Explicit source edition', name='Shark Dragon',
                  ranks=ranks, rank_palette_bindings=bindings, help_lines=['Source description.', '', 'Third source line.'])
    prepared = dict(identity=dict(source='dd2', edition=source['edition'], character_id=2180, body=2180),
                    evidence=dict(source_receipt=dict(source_rank_profiles=copy.deepcopy(ranks),
                                                     rank_palette_bindings=copy.deepcopy(bindings))))
    return source, prepared


class NativeImportTests(unittest.TestCase):
    def test_six_genuine_rank_profiles_and_authored_rank_five_palette(self):
        source, prepared = packet()
        self.assertIs(nativeimports.validate_source(source, prepared), source)
        self.assertEqual(source['rank_palette_bindings'][5]['palette'], 5)
        donor = database.Table('char.dat', database.get_schema('char.dat')).new_row()
        donor.set('learn_count', 1)
        donor.set('learn1_skill', 123)
        donor.set('evility_count', 1)
        donor.set('evility1', 124)
        donor.set('overload_id', 125)
        for k, rank in enumerate(source['ranks']):
            desc = sourcefidelity.from_profile(rank, game='dd2', edition=source['edition'], rank_count=6, rank_index=k)
            row, receipt = sourcefidelity.encode_gameplay(donor, desc)
            self.assertEqual([row['base_'+s] for s in sourcefidelity.STATS], rank['base'])
            self.assertEqual([row['apt_'+s] for s in sourcefidelity.STATS], rank['aptitudes'])
            self.assertEqual([row[x] for x in ('learn_count', 'learn1_skill', 'evility_count', 'evility1', 'overload_id')], [0]*5)
            self.assertEqual(receipt['source']['game'], 'dd2')
            self.assertEqual(receipt['rank_index'], k)
            self.assertFalse(receipt['native_tested'])
        self.assertEqual(donor['learn1_skill'], 123)

    def test_one_rank_is_not_padded_to_six(self):
        source, prepared = packet(1)
        nativeimports.validate_source(source, prepared)
        self.assertEqual(len(source['ranks']), 1)

    def test_wrong_namespace_and_edition_refused(self):
        for field, value in [('game', 'd4'), ('game', 'd2'), ('edition', 'Other edition')]:
            source, prepared = packet()
            source[field] = value
            with self.assertRaisesRegex(ValueError, 'game/edition'):
                nativeimports.validate_source(source, prepared)

    def test_binding_drift_and_donor_rank_padding_refused(self):
        mutations = [lambda s: s['rank_palette_bindings'][5].update(palette=10),
                     lambda s: s['rank_palette_bindings'][5].update(body=2010),
                     lambda s: s['rank_palette_bindings'][5].update(row_sha256='f'*64),
                     lambda s: s['rank_palette_bindings'][5].update(palette=0),
                     lambda s: s['ranks'].__setitem__(5, copy.deepcopy(s['ranks'][0]))]
        for mutate in mutations:
            source, prepared = packet()
            mutate(source)
            with self.assertRaises(ValueError):
                nativeimports.validate_source(source, prepared)

    def test_source_help_keeps_every_line_and_rejects_absence(self):
        source, prepared = packet()
        original = copy.deepcopy(source['help_lines'])
        nativeimports.validate_source(source, prepared)
        self.assertEqual(source['help_lines'], original)
        for lines in ([], ['', ''], ['a']*4, [None]):
            source['help_lines'] = lines
            with self.assertRaises(ValueError):
                nativeimports.validate_source(source, prepared)

    def test_target_rows_may_only_reuse_declared_dummy_rows(self):
        dummy_rows = (470, 480)
        byid = {470: dict(is_dummy_slot=0), 471: dict(is_dummy_slot=0),
                1000: dict(is_dummy_slot=0), 990: dict(is_dummy_slot=1)}
        # An absent row is free.
        nativeimports._check_targets(byid, 400, 1, dummy_rows)
        # A declared Kit dummy row is reusable even though the table flags it 0,
        # which is how char.dat stores 'Unique Dummy'.
        nativeimports._check_targets(byid, 470, 1, dummy_rows)
        # A flagged dummy row is reusable too.
        nativeimports._check_targets(byid, 990, 1, dummy_rows)
        # A real row is refused, including one immediately after a dummy row and
        # every rank of a family that would land on a real row.
        for target in (471, 1000):
            with self.assertRaisesRegex(ValueError, 'Existing non-dummy target row'):
                nativeimports._check_targets(byid, target, 1, dummy_rows)
        with self.assertRaisesRegex(ValueError, 'Existing non-dummy target row'):
            nativeimports._check_targets(byid, 470, 2, dummy_rows)


    def test_rank_rows_keep_donor_voice_and_magichange(self):
        source, prepared = packet()
        donor = database.Table('char.dat', database.get_schema('char.dat')).new_row()
        for key, value in dict(voice_id=9025, magichange_type=2, magichange_weapon=151).items():
            donor.set(key, value)
        desc = sourcefidelity.from_profile(source['ranks'][0], game='dd2', edition=source['edition'],
                                           rank_count=6, rank_index=0)
        row, _ = nativeimports._gameplay_row(donor, desc, 2640)
        self.assertEqual([row[k] for k in ('voice_id', 'magichange_type', 'magichange_weapon')],
                         [9025, 2, 151])
        self.assertEqual(row['color_id'], 2640)


if __name__ == '__main__':
    unittest.main()
