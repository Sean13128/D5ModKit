"""Disgaea RPG game text in checked-in data is a reference, never the text (TEXTHASH-DRPG).

The reviewed DRPG data files (evility and skill overlays, name tables, class titles, twin swaps, leases) used to carry
the JP client's strings and the Disgaea 5 names they were paired with.  A text field now stores one of

* ``{"@text": "<sha256>"}``: a string of the user's own files, looked up at build time in the pool of the prepared
  source folder (the verified ``masters/*.json``, ``characterclassname`` included) and the Disgaea 5 tables;
* ``{"@authored": "<text>"}``: wording this project wrote (a provisional English translation, a generated description,
  a character label) and keeps as text;
* ``{"@parts": [...]}``: a project sentence with a game name inside (literal ASCII pieces and ``@text`` references).

Loaders resolve a document with :func:`load`.  Which pool answers is decided by :func:`use` (the build sets the pool it
already has: the same masters and Disgaea 5 tables the roster resolves against) or, when nothing was set, by the
default pool of the prepared folder (``D5_SOURCE_DIR``) and the Disgaea 5 install.  A hash no source holds is refused
with the file and the JSON path of the field.  Tests install :class:`StubPool`, which answers every hash with a stable
placeholder so structure and ``@authored`` wording stay testable without game files.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import _drpg_roster

TEXT, AUTHORED, PARTS = '@text', '@authored', '@parts'
_STATE = {'pool': None}
_CACHE = {}


class StubPool:
    """A pool for tests: every digest resolves to ``<text 16-hex-digits>`` (equal digests give equal strings)."""

    def get(self, digest):
        return f'<text {digest[:16]}>'

    def sub(self, digest, of, at):
        return f'<text {digest[:16]}>'


class KeepRefs:
    """A pool that leaves every ``@text`` as it is: ``@authored``/``@parts`` literals resolve, game text stays a hash.
    For a reader that needs ids, counts and our own wording but no game text (and so no source folder)."""

    def get(self, digest):
        return {TEXT: digest}

    def sub(self, digest, of, at):
        return {TEXT: digest, 'of': of, 'at': list(at)}


KEEP = KeepRefs()


class _LazyDefault:
    """Builds the default pool the first time a ``@text`` is resolved (a file with none never needs sources)."""

    def get(self, digest):
        return default_pool().get(digest)

    def sub(self, digest, of, at):
        return default_pool().sub(digest, of, at)


def use(pool):
    """Resolve against ``pool`` from now on (``None`` returns to the default pool). Returns the previous pool."""
    previous = _STATE['pool']
    _STATE['pool'] = pool
    return previous


_LAZY = _LazyDefault()


def current():
    return _STATE['pool'] if _STATE['pool'] is not None else _LAZY


def build_pool(ctx, fs=None):
    """The pool of a build: verified masters of ``ctx['source_root']`` plus the Disgaea 5 tables read through ``fs``."""
    from . import _drpg_source
    return _drpg_roster.TextPool.from_sources(_drpg_source.data(ctx.get('source_root')), fs)


def _game_and_state():
    """(game folder, state folder) of the install the maintainer tools read: ``D5_DRPG_STATE`` names the state folder when
    the kit runs from a checkout that has none of its own (a scratch worktree)."""
    import os
    from .. import modsys, paths
    game = str(paths.require_game_dir())
    return game, os.environ.get('D5_DRPG_STATE') or str(modsys.game_state_dir(game, modsys.KIT_DIR))


def default_pool():
    """The prepared folder (``D5_SOURCE_DIR``) and the Disgaea 5 install the kit finds; refuses naming what is missing."""
    if 'default' not in _STATE:
        from . import _drpg_build, _drpg_source
        game, state = _game_and_state()
        fs = _drpg_build.source_fs(dict(game_path=game, state_root=state))
        try:
            _STATE['default'] = _drpg_roster.TextPool.from_sources(_drpg_source.data(), fs)
        finally:
            fs.reset()
    return _STATE['default']


def resolve(doc, where, pool=None):
    pool = pool or current()
    try:
        return _drpg_roster.resolve(doc, pool)
    except _drpg_roster.DrpgRosterError as exc:
        raise _drpg_roster.DrpgRosterError(f'{where}: {exc}') from None


def load(path, pool=None):
    """The resolved document of one data file (cached per pool)."""
    path = Path(path)
    pool = pool or current()
    key = (str(path), id(pool))
    hit = _CACHE.get(key)
    if hit is None or hit[0] is not pool:
        doc = json.loads(path.read_text(encoding='utf-8'))
        hit = _CACHE[key] = (pool, _resolve_tracked(doc, path.name, pool))
    return hit[1]


def load_authored(path):
    """The document with our own wording resolved and every game-text hash left in place (needs no sources)."""
    return load(path, KEEP)


def _resolve_tracked(doc, where, pool):
    """``resolve`` that names the JSON path of a failing hash (the roster resolver alone does not)."""
    if isinstance(doc, dict):
        if set(doc) == {TEXT}:
            try:
                return pool.get(doc[TEXT])
            except _drpg_roster.DrpgRosterError as exc:
                raise _drpg_roster.DrpgRosterError(f'{where}: {exc}') from None
        if set(doc) == {AUTHORED}:
            return doc[AUTHORED]
        if set(doc) == {PARTS}:
            pieces = [p if isinstance(p, str) else _resolve_tracked(p, where, pool) for p in doc[PARTS]]
            return ''.join(pieces) if all(isinstance(p, str) for p in pieces) else doc      # KEEP leaves it whole
        return {k: _resolve_tracked(v, f'{where}.{k}', pool) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_resolve_tracked(v, f'{where}[{i}]', pool) for i, v in enumerate(doc)]
    return doc


# ----------------------------------------------------------------------------------------------- writing references
def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def text_ref(value):
    return {TEXT: sha(value)} if isinstance(value, str) and value else value


def authored(value):
    return {AUTHORED: value} if isinstance(value, str) and value else value


def parts(sentence, names):
    """``sentence`` as ``@parts`` when it quotes one of ``names`` (game names, longest first), else unchanged."""
    names = sorted({n for n in names if isinstance(n, str) and len(n) >= 3}, key=lambda n: (-len(n), n))
    if not isinstance(sentence, str) or not names:
        return sentence
    pattern = re.compile('(?<![A-Za-z0-9])(' + '|'.join(re.escape(n) for n in names) + ')(?![A-Za-z0-9])')
    out, pos = [], 0
    for m in pattern.finditer(sentence):
        if m.start() > pos:
            out.append(sentence[pos:m.start()])
        out.append(text_ref(m.group(1)))
        pos = m.end()
    if not out:
        return sentence
    if pos < len(sentence):
        out.append(sentence[pos:])
    return {PARTS: out}


def prose_names(fs=None):
    """Disgaea 5 names (``name_EN`` of char/Skill/magic, ASCII, 6+ characters, with a capital) a review sentence may quote.

    Read through ``fs`` (the kit's pristine-table reader) or, without one, the default Disgaea 5 install of the kit.
    Only a maintainer tool needs it: the converter and the generators wrap such a name as an ``@text`` part."""
    if fs is None and 'names' in _STATE:
        return _STATE['names']
    own = fs is None
    if own:
        from . import _drpg_build
        game, state = _game_and_state()
        fs = _drpg_build.source_fs(dict(game_path=game, state_root=state))
    try:
        from .. import database
        out = set()
        for table in ('char.dat', 'Skill.dat', 'magic.dat'):
            for row in database.load_table(table, fs.read('Database/Database_0.dat/' + table)).rows:
                value = row.get('name_EN')
                if isinstance(value, str) and len(value) >= 6 and value.isascii() and any(c.isupper() for c in value):
                    out.add(value)
    finally:
        if own:
            fs.reset()
    if own:
        _STATE['names'] = out
    return out


def wrap_prose(doc, names):
    """Every plain sentence (12+ characters) under ``doc`` that quotes one of ``names`` becomes ``@parts`` (in place)."""
    if not names:
        return doc
    if isinstance(doc, dict):
        for k, v in list(doc.items()):
            if isinstance(v, str):
                if len(v) >= 12:
                    doc[k] = parts(v, names)
            elif not _is_ref(v):
                wrap_prose(v, names)
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            if isinstance(v, str):
                if len(v) >= 12:
                    doc[i] = parts(v, names)
            elif not _is_ref(v):
                wrap_prose(v, names)
    return doc


def _set(obj, keys, fn):
    for key in keys:
        if isinstance(obj, dict) and key in obj and obj[key] is not None and not _is_ref(obj[key]):
            obj[key] = fn(obj[key])


def _is_ref(value):
    return isinstance(value, dict) and len(value) == 1 and next(iter(value)) in (TEXT, AUTHORED, PARTS)


def refify_evility_overlay(doc, names=()):
    """Literal -> references for ``drpg-evility-overlay.json`` (in place; idempotent). JP names are source text; the
    English names, the five description columns and the character label are this project's wording."""
    for base in doc['bases'].values():
        _set(base, ('name',), authored)
        for e in base['evilities']:
            _set(e, ('name_jp',), text_ref)
            _set(e, ('name_en',), authored)
            row = e['skill_row']
            _set(row, ('name_JP', 'name_CHN', 'name_KOR'), text_ref)
            _set(row, ('name_EN', 'name_FR') + tuple(f'desc_{L}' for L in ('JP', 'EN', 'FR', 'CHN', 'KOR')), authored)
    return wrap_prose(doc, names)


def refify_skill_overlay(doc, names=()):
    """Literal -> references for ``drpg-skill-overlay.json``. JP names and the Disgaea 5 names (stand-ins, same-name
    spells) are source text; English names, generated descriptions and effect labels are this project's wording; a
    sentence that quotes a Disgaea 5 name becomes ``@parts``."""
    for base in doc['bases'].values():
        _set(base, ('name',), authored)
        for m in base.get('magic', []):
            _set(m, ('name_jp', 'd5_name'), text_ref)
        for s in base.get('skills', []):
            names = [(s.get('stand_in') or {}).get('name')]
            _set(s, ('name_jp',), text_ref)
            _set(s, ('name_en',), authored)
            for key in ('adaptations',):
                s[key] = [parts(a, names) for a in s.get(key, [])]
            if 'label' in s:
                s['label'] = parts(s['label'], names)
            for x in s.get('kept', []):
                _set(x, ('name',), authored)
            for x in s.get('dropped', []):
                _set(x, ('name',), authored)
                if 'why' in x:
                    x['why'] = parts(x['why'], names)
            if s.get('stand_in'):
                _set(s['stand_in'], ('name',), text_ref)
            _set(s.get('set') or {}, ('name_EN', 'desc_EN'), authored)
    return wrap_prose(doc, names)


def refify_evility_names(doc):
    """``names`` {JP name: English} -> a list of {jp: @text, en: @authored} (a JP name may not be a key)."""
    names = doc['names']
    if isinstance(names, dict):
        doc['names'] = [{'jp': text_ref(jp), 'en': authored(en)} for jp, en in names.items()]
    return doc


def evility_names(doc):
    """{JP name: provisional English} of a resolved ``drpg-evility-names.json``."""
    return {row['jp']: row['en'] for row in doc['names']}


def refify_skill_names(doc):
    _set(doc['names'], tuple(doc['names']), authored)
    return doc


def refify_titles(doc):
    for rec in doc['titles'].values():
        _set(rec, ('jp',), text_ref)
        _set(rec, ('en',), authored)
    return doc


def refify_twins(doc):
    for pack in doc['packs'].values():
        for row in pack.values():
            _set(row, ('name', 'replaces'), text_ref)
    return doc


def refify_leases(doc):
    for key in ('bases', 'costumes'):
        rows = doc.get(key)
        for row in (rows.values() if isinstance(rows, dict) else rows or []):
            _set(row, ('name',), authored)
    return doc


REFIFY = {
    'drpg-evility-overlay.json': refify_evility_overlay,
    'drpg-skill-overlay.json': refify_skill_overlay,
    'drpg-evility-names.json': refify_evility_names,
    'drpg-skill-names.json': refify_skill_names,
    'drpg-titles.json': refify_titles,
    'drpg-skill-twins.json': refify_twins,
    'drpg-leases.json': refify_leases,
}


def refify(file_name, doc, names=None):
    """The reference form of ``doc`` as the file ``file_name`` stores it (in place; a converted field stays)."""
    fn = REFIFY.get(file_name)
    if fn is None:
        return doc
    if fn in (refify_evility_overlay, refify_skill_overlay):
        return fn(doc, prose_names() if names is None else names)
    return fn(doc)


def format_doc(doc):
    """Compact JSON, one line per entry of the top level and of ``bases``/``titles``/``packs``/``names`` (the kit's commit
    guard allows no file over 1 MB, and a hash is longer than the text it replaces)."""
    def line(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    out = []
    for key, value in doc.items():
        if isinstance(value, dict) and key in ('bases', 'costumes', 'titles', 'packs', 'names') and value:
            inner = ',\n'.join(f'  {json.dumps(k)}:{line(v)}' for k, v in value.items())
            out.append(f' {json.dumps(key)}:{{\n{inner}\n }}')
        elif isinstance(value, list) and key in ('bases', 'costumes', 'names') and value:
            inner = ',\n'.join(f'  {line(v)}' for v in value)
            out.append(f' {json.dumps(key)}:[\n{inner}\n ]')
        else:
            out.append(f' {json.dumps(key)}:{line(value)}')
    return '{\n' + ',\n'.join(out) + '\n}\n'


def dump(path, doc):
    """Write ``doc`` as its file's reference form (a plain name or title is wrapped; a reference stays)."""
    path = Path(path)
    doc = refify(path.name, json.loads(json.dumps(doc)))
    path.write_text(format_doc(doc), encoding='utf-8')
