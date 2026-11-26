"""TEXTHASH-D4: Disgaea 4 game text in tracked kit data is a SHA-256 reference, never the literal string.

``Reports/GITTEXT1-AUDIT-20261120.md`` listed the D4 files that stored names and descriptions literally.  Every file
below now stores ``{"@text": sha}`` / ``{"@template": sha, ...}`` / ``{"@segments": [...]}`` for game text and
``{"@authored": text}`` for wording the kit's lanes wrote; the build resolves them from the user's prepared D4 folder and
the Disgaea 5 tables (``d5lib/importers/_d4_source.TextPool``, ``tools/hash_d4_text.py``, docs/TEXT_REFS.md).

This test fails when a name/description/title/text field in these files is a literal string again, when a Python
generator passes a literal name or description to ``row()``/``alias()``, and it proves the reference forms the lane
added (a template with an escaped percent, a quote that drops the final full stop, a prose note that quotes a
description) resolve back to the exact text.
"""
import ast
import json
import re
import sys
from pathlib import Path

import pytest

from d5lib.importers import _d4_source

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import hash_d4_text  # noqa: E402

# Every tracked D4 data file of Reports/GITTEXT1-AUDIT-20261120.md, plus the D4 files its scan method finds
# (carriers2-ranking, magichange).  d4-evility-overlay.json is in the audit table; the d4-* rule files were hashed by
# SOURCEPREP4-D4 and are kept here so a regeneration that writes a literal fails.
FILES = {
    'd5lib/importers/d4-evility-additions.json': set(),
    'd5lib/importers/d4-evility-overlay.json': set(),
    'd5lib/sourcemaps/d4.json': set(),
    'd5lib/importers/d4-leases.json': set(),
    'd5lib/importers/d4-scope.json': set(),
    'd5lib/importers/d4-mapping.json': set(),
    'd5lib/importers/d4-extension-rows.json': set(),
    'd5lib/importers/d4-extension-rows-cast.json': set(),
    'd5lib/importers/d4-specials.json': set(),
    'd5lib/importers/d4-allocation.json': set(),
    'evility/carriers-content.json': set(),
    'evility/carriers2-content.json': set(),
    'evility/carriers2-ranking.json': set(),
    'magichange/magichange-content.json': {'character', 'single', 'pair', 'dual'},
    'magichange/rows.json': {'character'},
}
GAME_TEXT_FIELD = re.compile(r'^(name|title|desc|text)$|^(name|desc)_[A-Z]+$|_(name|title|desc|text)$')
REF_FORMS = {'@text', '@template', '@segments', '@authored', '@skeleton'}
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def is_ref(value):
    return isinstance(value, dict) and bool(REF_FORMS & set(value))


def literal_text_fields(doc, extra=frozenset(), key='', path=''):
    """(path, value) of every game-text field (and every personality name) that is a bare string."""
    if is_ref(doc):
        return
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == 'personalities' and isinstance(v, dict):
                for sid, names in v.items():
                    for n, name in enumerate(names if isinstance(names, list) else []):
                        if isinstance(name, str) and name:
                            yield f'{path}/personalities/{sid}[{n}]', name
            else:
                yield from literal_text_fields(v, extra, k, f'{path}/{k}')
    elif isinstance(doc, list):
        for index, item in enumerate(doc):
            yield from literal_text_fields(item, extra, key, f'{path}[{index}]')
    elif isinstance(doc, str) and doc and (GAME_TEXT_FIELD.search(key) or key in extra):
        yield path, doc


@pytest.mark.parametrize('name', sorted(FILES))
def test_no_literal_game_text(name):
    doc = json.loads((ROOT / name).read_text(encoding='utf-8'))
    bad = list(literal_text_fields(doc, FILES[name]))
    assert not bad, (f'{name} stores game text literally; store {{"@text": sha256(text)}} (or @authored for our own '
                     'wording; tools/hash_d4_text.py does it) and resolve it at build time: '
                     + '; '.join(f'{p} = {v!r}' for p, v in bad[:6]))


@pytest.mark.parametrize('name', sorted(FILES))
def test_reference_shape(name):
    """A reference is a dict with one of the known forms and a well-formed digest (or authored text)."""
    def walk(value, path=''):
        if is_ref(value):
            yield path, value
        elif isinstance(value, dict):
            for k, v in value.items():
                yield from walk(v, f'{path}/{k}')
        elif isinstance(value, list):
            for i, v in enumerate(value):
                yield from walk(v, f'{path}[{i}]')
    doc = json.loads((ROOT / name).read_text(encoding='utf-8'))
    for path, ref in walk(doc):
        if '@text' in ref:
            assert HEX64.match(ref['@text']), f'{name}{path}: bad digest'
        if '@template' in ref:
            assert HEX64.match(ref['@template']) and isinstance(ref.get('args', []), list), f'{name}{path}'
        if '@authored' in ref:
            assert isinstance(ref['@authored'], str) and ref['@authored'], f'{name}{path}: empty @authored'
        if '@segments' in ref:
            assert isinstance(ref['@segments'], list) and ref['@segments'], f'{name}{path}'
        assert set(ref) <= _d4_source.TextPool.REF_KEYS, f'{name}{path}: unknown key in {sorted(ref)}'


def _literal_args(path, funcs):
    """Line numbers of calls to ``funcs`` whose name (arg 1) or description (arg 2) is a bare string literal."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs:
            for arg in node.args[1:3]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and '\u27e6' not in arg.value:
                    bad.append(node.lineno)         # (a marked quote is turned into a reference by evilgap1_rows.refs)
    return sorted(set(bad))


def test_evilgap1_generator_has_no_literal_name_or_description():
    """tools/evilgap1_rows.py (D4 evility rows in code): row()/alias() take reference dicts, not text."""
    bad = _literal_args(ROOT / 'tools/evilgap1_rows.py', {'row', 'alias'})
    assert not bad, f'tools/evilgap1_rows.py passes a literal name/description at line(s) {bad}'


def test_the_checks_catch_a_literal(tmp_path):
    """Negative control: a literal put back is found by both checks."""
    assert list(literal_text_fields({'a': {'d4_name': 'Aegis'}}))
    assert list(literal_text_fields({'rows': [{'desc': 'Increase damage by 15%.'}]}))
    assert list(literal_text_fields({'personalities': {'1080': ['Honest']}}))
    assert list(literal_text_fields({'c': {'single': 'Attack'}}, {'single'}))
    assert not list(literal_text_fields({'d4_name': {'@text': 'a' * 64}, 'desc': {'@authored': 'ours'}}))
    sample = tmp_path / 'gen.py'
    sample.write_text('x = row(1, "Aegis", "Increase damage by 15%.", 2)\ny = alias(1, {"@text": "ab"}, {"@text": "cd"})\n')
    assert _literal_args(sample, {'row', 'alias'}) == [1]


def test_reference_forms_round_trip():
    """The forms this lane added resolve to the exact string: escaped-percent template, dropped full stop, prose."""
    pool = _d4_source.TextPool([
        'When HP is under 25%%, recovers fully at the end of turn.',
        'Increase SPD by %d%% x panels moved this turn.',
        'Increase ally stats by %d%%, and decrease enemy stats by %d%%.',
        'Stone Statue',
    ])
    cases = [
        'When HP is under 25％, recovers fully at the end of turn.',            # no %d: only the escape
        'Increase SPD by 5％ x panels moved this turn',                          # quote without the final stop
        'Increase ally stats by 10%, and decrease enemy stats by %d%.',            # half-rendered
        "evility Stone Statue (807): adapted - D4 'Increase SPD by 5% x panels moved this turn' is read as ...",
    ]
    for value in cases:
        ref = hash_d4_text.embedded(pool, value) or hash_d4_text.make_ref(pool, value)
        assert pool.resolve(ref) == value, value
        assert not (set(ref) == {'@authored'}), f'{value!r} stayed literal'
    prose = hash_d4_text.embedded(pool, cases[-1])
    assert '@segments' in prose and any(isinstance(p, str) and p.startswith('evility') for p in prose['@segments'])


def test_hash_document_is_idempotent_and_resolves_to_the_same_strings():
    pool = _d4_source.TextPool(['Aegis', 'Decrease damage taken by %d%% when attacked.', 'Lift'])
    doc = {'uniques': {'1': {'d4_name': 'Aegis', 'd4_desc': 'Decrease damage taken by 30% when attacked.',
                             'works_like_name': 'Lift', 'note': 'kit wording', 'name': 'Warrior line'}},
           'personalities': {'1080': ['Aegis']}}
    once = hash_d4_text.hash_document(doc, pool)
    assert list(literal_text_fields(once)) == []
    assert hash_d4_text.hash_document(once, pool) == once
    resolved = pool.resolve_doc(once)
    assert resolved == doc


def test_loader_refuses_unresolvable_text_and_names_what_to_supply(tmp_path, monkeypatch):
    """No pool, no prepared folder or D5 backups: the loader says what is missing instead of returning hashes."""
    from d5lib import sourceimports
    mapping = {'schema': 1, 'game': 'd4', 'evilities': {'1': {'d4_name': {'@text': 'f' * 64}}}}
    path = tmp_path / 'm.json'
    path.write_text(json.dumps(mapping))
    with pytest.raises(_d4_source.D4SourceError) as exc:
        sourceimports.load_d4_mapping(path, pool=_d4_source.TextPool())
    assert 'is not in the prepared D4 source' in str(exc.value)
    got = sourceimports.load_d4_mapping(path, pool=_d4_source.TextPool(), lenient=True)
    assert got['evilities']['1']['d4_name'].startswith('<unresolved d4 text ffffffffffff')
    plain = {'schema': 1, 'game': 'd4', 'evilities': {'1': {'d4_name': 'Aegis'}}}
    path.write_text(json.dumps(plain))
    assert sourceimports.load_d4_mapping(path)['evilities']['1']['d4_name'] == 'Aegis'   # nothing to resolve


def test_every_reference_resolves_from_the_prepared_source():
    """When the prepared D4 folder and the D5 tables are reachable, every file resolves completely."""
    try:
        pool = _d4_source.text_pool_for_tools()
    except Exception as exc:                                     # noqa: BLE001 - no prepared folder / no D5 backups
        pytest.skip(f'prepared D4 folder or D5 tables not reachable: {exc}')
    for name in FILES:
        doc = json.loads((ROOT / name).read_text(encoding='utf-8'))
        pool.resolve_doc(doc)                                    # raises naming the digest when one is missing
