"""Source text must reach D5's Latin slots as ASCII (INTEG15 finding 1, repaired by hand in 13 packs).

INTEG15's widened class gate (R7) found 13 packs carrying Unicode punctuation in the Latin slots of
char.dat / charhelp.dat:

  * D1 Complete uniques 2614/2615 ("Astro-One"), where the batch data spells the hyphen U+2212;
  * nine DD2 uniques, whose help lines come straight out of the DD2 release's charhelp table and end in
    CJK fullwidth stops ("Celestia's new Archangel．").

Both routes build through `d5lib.nativeimports.build_entry`, which folded the help lines *only when the
packet carried source abilities* and never folded the name.  `latin_slots()` is now the one place the
fold is decided, for name, titles and help lines alike, and the JP slot keeps the source's own spelling.

The repaired values in Builds/LIVE5_TEST15-20261029 are the target: the fold must reproduce that repair
exactly.  Those bundles are evidence outside the repo, so the cross-check skips when they are absent --
the literal-string tests below cover the same characters and never skip.
"""
import importlib
import inspect
import json
import os
import sys

import pytest

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

nativeimports = importlib.import_module('d5lib.nativeimports')
dbpatch = importlib.import_module('d5lib.dbpatch')

REPO = os.environ.get('D5_REPO') or '/Volumes/Data/Projects/D5'   # the project root (Builds/ lives there)
TEST14 = os.path.join(REPO, 'Builds', 'LIVE5_TEST14-20261029', 'mods')
TEST15 = os.path.join(REPO, 'Builds', 'LIVE5_TEST15-20261029', 'mods')

# The repair list of INTEG15 (stage-log.json doc.text_repairs): (pack, file, Latin fields).
REPAIRS = [
    ('D1C_Unique_2614', 'patches/db/char.dat.json', ['name_EN', 'name_FR']),
    ('D1C_Unique_2614', 'patches/db/charhelp.dat.json', ['line1_EN', 'line1_FR']),
    ('D1C_Unique_2615', 'patches/db/char.dat.json', ['name_EN', 'name_FR']),
    ('D1C_Unique_2615', 'patches/db/charhelp.dat.json', ['line1_EN', 'line1_FR']),
    ('DD2_Unique_140', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line2_EN', 'line2_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_210', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line2_EN', 'line2_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_270', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line2_EN', 'line2_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_320', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line2_EN', 'line2_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_400', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line2_EN', 'line2_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_420', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_430', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line2_EN', 'line2_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_550', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line2_EN', 'line2_FR', 'line3_EN', 'line3_FR']),
    ('DD2_Unique_570', 'patches/db/charhelp.dat.json',
     ['line1_EN', 'line1_FR', 'line3_EN', 'line3_FR']),
]

# INTEG15's ASCII_FIX mapping (build_stage15.py) -- the characters this fix must keep folding.
ASCII_FIX = {'\u2212': '-', '\uff0e': '.', '\uff01': '!', '\uff1f': '?', '\uff0c': ',',
             '\uff1a': ':', '\uff1b': ';', '\uff0d': '-', '\uff5e': '~'}

D1C_NAME = 'Astro\u2212One'
D1C_HELP = 'Astro\u2212One - Defender? (Disgaea 1 Complete)'
DD2_HELP = ["Celestia's new Archangel\uff0e", 'He loves angels and hates demons\uff0e',
            'Believes all his actions exude love\uff0e']


def _added(path):
    with open(path, encoding='utf-8') as fh:
        return (json.load(fh).get('added') or [{}])[0]


def _packet(name, title, help_lines):
    return dict(game='dd2', edition='test', name=name, ranks=[dict(id=1, title=title)],
                help_lines=list(help_lines))


# --------------------------------------------------------------------- the fold itself
def test_every_integ15_character_is_folded():
    for bad, good in ASCII_FIX.items():
        assert nativeimports.ascii_latin('x' + bad + 'y') == 'x' + good + 'y'
    # three in one string, the D1C and DD2 spellings together
    assert nativeimports.ascii_latin('Astro\u2212One\uff1aArchangel\uff0e') == 'Astro-One:Archangel.'


def test_fold_never_drops_or_transliterates_a_character():
    # a fold is a substitution: same length, and Japanese text comes through byte-identical
    for text in (D1C_NAME, D1C_HELP, *DD2_HELP, '\u30a2\u30b9\u30c8\u30ed\u30fc\u30ef\u30f3', '\u4e00\u4e8c\u4e09'):
        assert len(nativeimports.ascii_latin(text)) == len(text)
    assert nativeimports.ascii_latin('\u30a2\u30b9\u30c8\u30ed') == '\u30a2\u30b9\u30c8\u30ed'
    assert nativeimports.ascii_latin('\u4e00\u4e8c\u4e09') == '\u4e00\u4e8c\u4e09'


def test_d1c_unique_slots_are_ascii():
    name, titles, help_lines = nativeimports.latin_slots(_packet(D1C_NAME, 'Defender?', [D1C_HELP]))
    assert name == 'Astro-One'
    assert titles == ['Defender?']
    assert help_lines == ['Astro-One - Defender? (Disgaea 1 Complete)']
    assert all(line.isascii() for line in [name, *titles, *help_lines])


def test_dd2_help_slots_are_ascii_without_source_abilities():
    # the nine DD2 packs carry no skills/evilities in the packet: folding must not depend on that
    packet = _packet('Virunga', 'Archangel', DD2_HELP)
    assert not packet.get('skills') and not packet.get('evilities')
    name, _, help_lines = nativeimports.latin_slots(packet)
    assert name == 'Virunga'
    assert help_lines == ["Celestia's new Archangel.", 'He loves angels and hates demons.',
                          'Believes all his actions exude love.']
    assert all(line.isascii() for line in help_lines)


def test_latin_slots_does_not_rewrite_its_input():
    packet = _packet(D1C_NAME, 'Archangel', DD2_HELP)
    before = json.dumps(packet, sort_keys=True)
    nativeimports.latin_slots(packet)
    assert json.dumps(packet, sort_keys=True) == before


def test_build_entry_writes_through_latin_slots_and_keeps_cjk_slots_raw():
    src = inspect.getsource(nativeimports.build_entry)
    assert 'latin_slots(source)' in src, 'build_entry must fold through latin_slots'
    assert "if abilities is not None else source['help_lines']" not in src, \
        'the abilities-only fold is the defect INTEG15 repaired: help lines are folded for every packet'
    assert '_set_latin(hr,' in src, 'help lines go through the EN/FR-only writer'
    assert '_set_latin(row, \'name\'' in src, 'the char.dat name goes through the EN/FR-only writer'


def test_set_latin_folds_en_fr_and_leaves_the_cjk_slots_alone():
    """classcheck R7 counts only _EN/_FR as Latin slots; JP/CHN/KOR keep the source spelling."""

    class Row:
        def __init__(self):
            self.f = {f'{p}_{L}': '' for p in ('name', 'title', 'line1')
                      for L in ('JP', 'EN', 'FR', 'CHN', 'KOR')}

        def keys(self):
            return list(self.f)

        def set(self, key, value, truncate=False):
            self.f[key] = value

        def __getitem__(self, key):
            return self.f[key]

    row = Row()
    nativeimports._set_latin(row, 'line1', "Celestia's new Archangel.", DD2_HELP[0])
    assert row['line1_EN'] == row['line1_FR'] == "Celestia's new Archangel."
    assert row['line1_JP'] == row['line1_CHN'] == row['line1_KOR'] == DD2_HELP[0]


# --------------------------------------------------------------------- against the INTEG15 repair
@pytest.mark.skipif(not (os.path.isdir(TEST14) and os.path.isdir(TEST15)),
                    reason='INTEG15 TEST14/TEST15 bundles are evidence outside the repo')
def test_fold_reproduces_the_integ15_repair():
    """Folding a TEST14 (un-repaired) value gives exactly TEST15's repaired value, for all 13 packs."""
    seen = 0
    for pack, rel, fields in REPAIRS:
        bad = _added(os.path.join(TEST14, pack, rel))
        good = _added(os.path.join(TEST15, pack, rel))
        for field in fields:
            assert nativeimports.ascii_latin(bad[field]) == good[field], '%s %s %s' % (pack, rel, field)
            assert good[field].isascii(), '%s %s %s is still not ASCII' % (pack, rel, field)
            seen += 1
    assert seen == 58, seen    # 8 D1C fields (name + help, EN/FR on 2 packs) + 50 DD2 help fields


@pytest.mark.skipif(not (os.path.isdir(TEST14) and os.path.isdir(TEST15)),
                    reason='INTEG15 TEST14/TEST15 bundles are evidence outside the repo')
def test_regenerated_d1c_and_dd2_packets_match_test15():
    """The packet Latin slots a rebuild would write equal the repaired TEST15 tables."""
    for pack in ('D1C_Unique_2614', 'D1C_Unique_2615'):
        char = _added(os.path.join(TEST14, pack, 'patches/db/char.dat.json'))
        help14 = _added(os.path.join(TEST14, pack, 'patches/db/charhelp.dat.json'))
        char15 = _added(os.path.join(TEST15, pack, 'patches/db/char.dat.json'))
        help15 = _added(os.path.join(TEST15, pack, 'patches/db/charhelp.dat.json'))
        name, titles, help_lines = nativeimports.latin_slots(
            _packet(char['name_EN'], char['title_EN'], [help14['line1_EN']]))
        assert name == char15['name_EN']
        assert f'{name} - {titles[0]} (Disgaea 1 Complete)' == help15['line1_EN']
        assert help_lines == [help15['line1_EN']]
    for pack, rel, fields in REPAIRS:
        if not pack.startswith('DD2_'):
            continue
        bad = _added(os.path.join(TEST14, pack, rel))
        good = _added(os.path.join(TEST15, pack, rel))
        lines = [bad[f'line{k}_EN'] for k in (1, 2, 3) if f'line{k}_EN' in bad]
        name, _, help_lines = nativeimports.latin_slots(_packet('source', 'title', lines))
        assert help_lines == [good[f'line{k}_EN'] for k in range(1, len(lines) + 1)]
        # and the wrapped lines the importer writes are the repaired ones too
        assert dbpatch.help_lines(help_lines) == [good[f'line{k}_EN'] for k in range(1, len(lines) + 1)]


def test_d1c_batch_data_no_longer_spells_the_hyphen_as_a_minus():
    path = os.path.join(REPO, 'Research', 'source-packs', 'd1c', 'batches', 'uniques.json')
    if not os.path.isfile(path):
        pytest.skip('D1C batch spec not present')
    with open(path, encoding='utf-8') as fh:
        rows = {row['id']: row for row in json.load(fh)['rows']}
    assert rows[2614]['name'] == 'Astro-One'
    assert rows[2615]['name'] == 'Astro-Two'
    assert rows[2614]['name'].isascii() and rows[2615]['name'].isascii()
