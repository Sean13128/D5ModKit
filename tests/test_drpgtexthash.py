"""TEXTHASH-DRPG: the Disgaea RPG data files hold no literal game text.

``Reports/GITTEXT1-AUDIT-20261120.md`` listed the DRPG files that carried the JP client's strings (evility and skill
names, class titles) and the Disgaea 5 names they were paired with.  Those fields are now ``{"@text": sha256}`` (source
text, resolved at build time from the prepared masters and the Disgaea 5 tables) or ``{"@authored": text}`` (our own
wording).  This test fails when a literal name/title/description field, or any Japanese character, comes back.
"""
import json
import re
from pathlib import Path

import pytest

from d5lib import textrefs
from d5lib.importers import _drpg_roster, _drpg_text

ROOT = Path(__file__).resolve().parents[1]
IMP = ROOT / 'd5lib' / 'importers'
FILES = tuple(f'd5lib/importers/{name}' for name in _drpg_text.REFIFY)

# A key that names a thing the game (or we) call something: its string value must be a reference.  ``name_label`` and
# ``en_kind`` are provenance labels, not names.
TEXT_KEY = re.compile(r'^(name|title|desc|text|jp|en)$|^(name|desc|title)_[A-Za-z]+$|^(d5_name|replaces)$')
NOT_TEXT = {'name_label'}
# Citations of where a text came from (a page name and URL), not game text.
PROVENANCE = {'official_source', 'community_source'}
# Japanese kana, CJK ideographs (and extension A), half-width katakana, hangul.  Written as escapes: no game text here.
JAPANESE = re.compile('[぀-ヿ㐀-鿿ｦ-ﾟ가-힯]')
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def literal_fields(value, path='', key=''):
    """(path, string) of every literal string under a game-text key (a reference dict is never a literal)."""
    if textrefs.is_ref(value):
        return []
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if k not in PROVENANCE:
                out += literal_fields(v, f'{path}/{k}', k)
        return out
    if isinstance(value, list):
        out = []
        for i, v in enumerate(value):
            out += literal_fields(v, f'{path}[{i}]', key)
        return out
    if isinstance(value, str) and value and key not in NOT_TEXT and TEXT_KEY.search(key):
        return [(path, value)]
    return []


def docs():
    for name in FILES:
        yield name, json.loads((ROOT / name).read_text(encoding='utf-8'))


@pytest.mark.parametrize('name,doc', list(docs()))
def test_no_literal_game_text_field(name, doc):
    """Every name/title/description field is a reference."""
    bad = literal_fields(doc)
    if name.endswith('drpg-skill-names.json'):                     # {skill id: name}: the keys are ids, the values names
        bad += [(f'/names/{k}', v) for k, v in doc['names'].items() if not textrefs.is_ref(v)]
    assert not bad, f'{name} holds literal game text; store @text (source text) or @authored (ours): {bad[:5]}'


@pytest.mark.parametrize('name', FILES)
def test_no_japanese_character_in_the_file(name):
    found = sorted(set(JAPANESE.findall((ROOT / name).read_text(encoding='utf-8'))))
    assert not found, f'{name} holds {len(found)} distinct Japanese/Korean characters; hash them (@text)'


@pytest.mark.parametrize('name,doc', list(docs()))
def test_every_reference_is_well_formed(name, doc):
    """``@text`` = 64 hex digits, ``@authored`` = non-empty text, ``@parts`` = literal ASCII pieces and ``@text`` refs."""
    def walk(v, path=''):
        if textrefs.is_ref(v):
            (kind, body), = v.items()
            if kind == textrefs.TEXT:
                assert isinstance(body, str) and HEX64.match(body), f'{name}{path}: bad digest {body!r}'
            elif kind == textrefs.AUTHORED:
                assert isinstance(body, str) and body, f'{name}{path}: empty @authored'
            else:
                assert isinstance(body, list) and body, f'{name}{path}: empty @parts'
                for piece in body:
                    if isinstance(piece, str):
                        assert piece.isascii(), f'{name}{path}: non-ASCII literal piece {piece!r}'
                    else:
                        assert textrefs.is_ref(piece) and textrefs.TEXT in piece, f'{name}{path}: bad @parts piece'
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f'{path}/{k}')
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f'{path}[{i}]')
    walk(doc)


def test_the_scanner_finds_a_literal_put_back():
    """Negative control of the two checks above, on a copy of a real file with one literal returned."""
    doc = json.loads((IMP / 'drpg-evility-overlay.json').read_text(encoding='utf-8'))
    base = next(iter(doc['bases'].values()))
    assert literal_fields(doc) == []
    base['evilities'][0]['name_jp'] = 'テスト'                     # a katakana literal
    base['evilities'][0]['skill_row']['desc_EN'] = 'a literal description'
    found = dict(literal_fields(doc))
    assert any(p.endswith('/name_jp') for p in found) and any(p.endswith('/desc_EN') for p in found)
    assert JAPANESE.search(json.dumps(doc, ensure_ascii=False))


def test_resolving_with_the_stub_leaves_no_reference_and_ours_is_text():
    for name in FILES:
        doc = _drpg_text.load(ROOT / name)
        assert not textrefs.has_refs(doc), name


def test_authored_only_reader_needs_no_sources():
    doc = _drpg_text.load_authored(IMP / 'drpg-evility-overlay.json')
    ev = next(iter(doc['bases'].values()))['evilities'][0]
    assert isinstance(ev['name_en'], str) and ev['name_jp'] == {'@text': ev['name_jp']['@text']}


def test_unknown_hash_refuses_and_names_the_file_and_field(tmp_path):
    path = tmp_path / 'drpg-titles.json'
    path.write_text(json.dumps({'titles': {'15': {'jp': {'@text': '0' * 64}, 'en': {'@authored': 'ours'}}}}))
    with pytest.raises(_drpg_roster.DrpgRosterError) as exc:
        _drpg_text.load(path, _drpg_roster.TextPool())
    message = str(exc.value)
    assert 'drpg-titles.json.titles.15.jp' in message and '0' * 64 in message and 'characterclassname' in message


def test_resolution_returns_the_exact_text_and_parts_join():
    pool = _drpg_roster.TextPool(['Source Name', 'Other'])
    doc = {'a': {'@text': _drpg_text.sha('Source Name')}, 'b': {'@authored': 'ours'},
           'c': {'@parts': ['cast like D5 1502 ', {'@text': _drpg_text.sha('Other')}, " (stand-in)"]}}
    assert _drpg_text.resolve(doc, 'x', pool) == {'a': 'Source Name', 'b': 'ours', 'c': 'cast like D5 1502 Other (stand-in)'}
    assert textrefs.resolve(doc, pool.get) == {'a': 'Source Name', 'b': 'ours', 'c': 'cast like D5 1502 Other (stand-in)'}


def test_refify_is_idempotent_and_round_trips():
    """The generators' conversion keeps already converted fields and turns literals into references that resolve back."""
    pool = _drpg_roster.TextPool(['SRC-JP', 'D5 Skill'])
    doc = {'schema': 'drpg-skill-overlay/1', 'bases': {'15': {
        'name': 'Barbara', 'magic': [{'name_jp': 'SRC-JP', 'd5_name': 'D5 Skill'}],
        'skills': [{'name_jp': 'SRC-JP', 'name_en': 'Provisional', 'adaptations': ['cast like D5 1502 D5 Skill (stand-in)'],
                    'label': 'plain label', 'stand_in': {'id': 1502, 'name': 'D5 Skill'},
                    'kept': [{'name': 'DEF up'}], 'dropped': [{'name': 'ATK up', 'why': 'no D5 Skill here'}],
                    'set': {'name_EN': 'Provisional', 'desc_EN': 'Support: raises DEF.'}}]}}}
    once = _drpg_text.refify_skill_overlay(json.loads(json.dumps(doc)))
    assert once == _drpg_text.refify_skill_overlay(json.loads(json.dumps(once)))
    assert not literal_fields(once)
    assert once['bases']['15']['skills'][0]['adaptations'][0] == {'@parts': [
        'cast like D5 1502 ', {'@text': _drpg_text.sha('D5 Skill')}, ' (stand-in)']}
    assert _drpg_text.resolve(once, 'x', pool) == doc


def test_leases_load_gives_plain_names_and_dump_wraps_them(tmp_path):
    from d5lib.importers import drpg_leases
    manifest = drpg_leases.load()
    assert all(isinstance(b['name'], str) for b in manifest['bases'])
    assert all(isinstance(c['name'], str) for c in manifest['costumes'])
    out = tmp_path / 'drpg-leases.json'
    _drpg_text.dump(out, manifest)
    raw = json.loads(out.read_text(encoding='utf-8'))
    assert all(textrefs.is_ref(b['name']) for b in raw['bases'])
    assert drpg_leases.load(out) == manifest


def test_the_build_resolves_titles_evilities_and_skills_through_the_pool():
    """``_drpg_text.use`` is how the build hands its pool to the reviewed overlays (the stub stands in here)."""
    from d5lib.importers import drpg_evilities, drpg_skills, drpg_titles
    seen = _drpg_text.use(_drpg_roster.TextPool(['x']))
    try:
        with pytest.raises(_drpg_roster.DrpgRosterError):
            drpg_titles.load()
        with pytest.raises(_drpg_roster.DrpgRosterError):
            drpg_evilities.overlay()
        with pytest.raises(_drpg_roster.DrpgRosterError):
            drpg_skills.overlay()
    finally:
        _drpg_text.use(seen)
    assert drpg_titles.load()['titles']['15']['jp'].startswith('<text ')


def test_no_japanese_in_drpg_code_tests_and_docs():
    """The DRPG tools, tests and importer modules spell no game name in Japanese (the data is hashed)."""
    paths = [p for pattern in ('tools/*drpg*.py', 'tests/*drpg*.py', 'tests/test_smallfix1.py', 'd5lib/importers/*drpg*.py',
                               'evility/*drpg*.py', 'docs/EVILITIES.md')
             for p in ROOT.glob(pattern) if p.name != Path(__file__).name]
    hits = {str(p.relative_to(ROOT)): len(JAPANESE.findall(p.read_text(encoding='utf-8'))) for p in paths}
    assert not {k: v for k, v in hits.items() if v}, hits
