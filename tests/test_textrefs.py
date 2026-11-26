"""TEXTHASH-D1C-DD2: D1C and DD2 kit data carry game text as ``@text`` SHA-256 references.

The audit ``Reports/GITTEXT1-AUDIT-20261120.md`` lists the files that still held literal game text.
This test fails when a name/title/description/text field in any of them is a literal string again
(a regenerated file that ignored the reference rule), and it proves the refusal rule: an unresolved
hash names the field (and so the pack/skill id) it came from.
"""
import json
import re
from pathlib import Path

import pytest

from d5lib import textrefs

ROOT = Path(__file__).resolve().parents[1]

# The D1C rows and the remaining DD2 rows of Reports/GITTEXT1-AUDIT-20261120.md.  ``d1c-extra-leases``
# is gone (its leases are ``d1c-roster.json``, already hashed by SOURCEPREP4-D1C).
FILES = {
    'd5lib/sourcemaps/d1c.json': ('d1c', 'D5'),
    'd5lib/importers/d1c-voice-map.json': ('d1c',),
    'd5lib/importers/d1c-donor-evilities.json': ('D5',),
    'd5lib/data/unique_art_leases.json': ('d1c', 'd4', 'dd2', 'D5'),
    'd5lib/sourcemaps/dd2.json': ('dd2', 'D5'),
    'd5lib/importers/dd2-innate-evilities.json': ('dd2',),
    'd5lib/importers/dd2-leases.json': ('dd2',),
    'd5lib/importers/dd2-voice-map.json': ('dd2',),
    # SOURCEPREP4-DRPG: the files that branch added (the existing drpg overlay/names files are TEXTHASH-DRPG's).
    'd5lib/importers/drpg-roster-0.json': ('drpg', 'D5'),
    'd5lib/importers/drpg-roster-1.json': ('drpg', 'D5'),
    'd5lib/importers/drpg-roster-2.json': ('drpg', 'D5'),
    'd5lib/importers/drpg-roster-3.json': ('drpg', 'D5'),
    'd5lib/importers/drpg-bank-shapes.json': ('drpg',),
    'd5lib/importers/drpg-pose-reference.json': ('drpg',),
}

GAME_TEXT_FIELD = re.compile(r'^(name|title|desc|text)$|^(name|desc)_[A-Z]+$|_(name|title|desc|text)$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def walk(value, path=''):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f'{path}/{key}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f'{path}[{index}]')
    else:
        yield path, value


def documents():
    for name in FILES:
        yield name, json.loads((ROOT / name).read_text(encoding='utf-8'))


@pytest.mark.parametrize('name,doc', list(documents()))
def test_no_literal_game_text(name, doc):
    """Every name/title/desc/text field is a reference, never a literal string."""
    literals = [f'{path} = {value!r}' for path, value in walk(doc)
                if GAME_TEXT_FIELD.search(path.rsplit('/', 1)[-1].split('[')[0])
                and isinstance(value, str) and value and not textrefs.is_ref(value)]
    assert not literals, (
        f'{name} still stores game text literally; store {{"@text": sha256(text)}} (or @authored for '
        'our own wording) and resolve it at build time: ' + '; '.join(literals[:8]))


@pytest.mark.parametrize('name,doc', list(documents()))
def test_reference_shape(name, doc):
    """A reference is either ``{"@text": <64 hex>}`` or ``{"@authored": <text>}``, nothing else."""
    for path, value in walk(doc):
        if not textrefs.is_ref(value):
            continue
        if textrefs.TEXT in value:
            assert HEX64.match(value[textrefs.TEXT]), f'{name}{path}: bad digest {value[textrefs.TEXT]!r}'
        else:
            assert isinstance(value[textrefs.AUTHORED], str) and value[textrefs.AUTHORED], \
                f'{name}{path}: empty @authored text'


def test_unknown_hash_refuses_and_names_the_id():
    """An unresolved @text says which field (and therefore which pack id) failed."""
    doc = {'packs': {'DD2_Unique_999': {'name': {'@text': '0' * 64}, 'row': {'desc_EN': 'x'}}}}
    pool = textrefs.TextPool(label='an empty pool')
    with pytest.raises(textrefs.TextRefError) as exc:
        textrefs.resolve(doc, pool.get, 'dd2-innate-evilities')
    message = str(exc.value)
    assert 'dd2-innate-evilities.packs.DD2_Unique_999.name' in message
    assert '0' * 64 in message and 'an empty pool' in message


def test_resolve_reproduces_the_text_and_folds_source_spelling():
    """A reference resolves to the exact text the pack gets, through a source-spelling fold."""
    pool = textrefs.TextPool(['Astro−One (D1C)'], label='the prepared source',
                             folds=(lambda s: s.replace('−', '-'),))
    doc = {'name': {'@text': textrefs.sha('Astro-One (D1C)')},
           'note': {'@authored': 'our wording'},
           'ids': [1, 2]}
    assert textrefs.resolve(doc, pool.get, 'd1c-voice-map') == {
        'name': 'Astro-One (D1C)', 'note': 'our wording', 'ids': [1, 2]}


def test_has_refs_sees_nested_references():
    assert textrefs.has_refs({'a': [{'b': {'@text': 'f' * 64}}]})
    assert textrefs.has_refs({'a': {'@authored': 'ours'}})
    assert not textrefs.has_refs({'a': 'literal', 'b': [1, 2]})


def test_build_path_refuses_an_unresolved_donor_hash_naming_the_pack():
    """The real D1C build reader (``d1c.donor_evilities``) refuses with the pack folder and digest."""
    from d5lib.importers import d1c
    empty = textrefs.TextPool(label='an empty pool')
    with pytest.raises(textrefs.TextRefError) as exc:
        d1c.donor_evilities('D1C_Class_11400', text=empty.get)
    message = str(exc.value)
    assert 'd1c-donor-evilities.mods.D1C_Class_11400.' in message
    assert re.search(r'text [0-9a-f]{64} is not in an empty pool', message)


def test_voice_label_refuses_an_unresolved_hash_naming_the_pack(monkeypatch):
    from d5lib import d1cvoice
    from d5lib.importers import _d1c_source
    monkeypatch.setattr(_d1c_source, 'text_pool', lambda: textrefs.TextPool(label='the prepared D1C source'))
    with pytest.raises(textrefs.TextRefError) as exc:
        d1cvoice.voice_label({'name': {'@text': 'a' * 64}}, 'd1c-voice-map.mods.D1C_Class_99999')
    assert 'D1C_Class_99999' in str(exc.value) and 'a' * 64 in str(exc.value)


# --- SOURCEPREP4-DRPG: the roster files carry rules, ids and vocabulary as literals and nothing else ---------------
ROSTER_FILES = [f'd5lib/importers/drpg-roster-{i}.json' for i in range(4)]
ROSTER_LITERAL_KEYS = {
    'about', 'borrowed', 'channel', 'command_rule', 'cv_name', 'direction', 'donor_kind', 'element', 'family', 'file',
    'keys', 'kind', 'leader_fields', 'leader_rule', 'note', 'origin_confidence', 'origin_game', 'route', 'schema',
    'scope', 'selection_rule', 'excluded_additional_sub_fields', 'sha256', 'stats', 'status', 'targets', 'type',
    'verdict', 'what', 'part', 'groups',
}
JAPANESE = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]')


def roster_literals(doc):
    """(path, value) of every literal string under a key the roster does not own as a rule/vocabulary key."""
    out = []
    ref_keys = {'@text', '@authored', '@parts', 'of', 'at'}

    def visit(node, path, key):
        if isinstance(node, dict):
            if node and set(node) <= ref_keys:          # a reference (resolved at build time), not a literal
                return
            for k, v in node.items():
                visit(v, f'{path}/{k}', k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, f'{path}[{i}]', key)
        elif isinstance(node, str) and (key not in ROSTER_LITERAL_KEYS or JAPANESE.search(node)):
            out.append((path, node))
    visit(doc, '', None)
    return out


@pytest.mark.parametrize('name', ROSTER_FILES)
def test_roster_literals_are_rules_only(name):
    doc = json.loads((ROOT / name).read_text(encoding='utf-8'))
    assert not roster_literals(doc), roster_literals(doc)[:5]


def test_roster_literal_check_has_a_negative_control():
    """The check fails on a regenerated file that put a name, a translation or Japanese back as a literal."""
    base = json.loads((ROOT / ROSTER_FILES[0]).read_text(encoding='utf-8'))
    assert not roster_literals(base)
    first = base['groups'][0]['character']
    for key, text in (('en', 'a literal name'), ('name', 'a literal name'), ('name_jp', chr(0x30a2)), ('cv_name', chr(0x30a2))):
        probe = json.loads(json.dumps(base))
        probe['groups'][0]['character'][key] = text
        assert roster_literals(probe), key
    assert first   # the control used a real group
