"""Game text in checked-in kit data: a SHA-256 reference (``@text``), never the literal string.

The importer data files (sourcemaps, leases, voice maps, reviewed rows) describe the user's own game
files.  A field that holds game text stores ``{"@text": "<sha256>"}`` instead of the text itself; the
build reads the text from the user's prepared source folder and the Disgaea 5 tables, looks the hash up
in a :class:`TextPool` and refuses, naming the field, when the string is not there (a different game
edition or a stale recipe).  Wording our own lanes wrote stores ``{"@authored": "<text>"}``.

This is the DD2 frozen-patch rule (``d5lib/importers/_dd2_source.py``, SOURCEPREP4-DD2) made shared.
The hash is of the exact text the pack receives, so a resolved document is byte-for-byte what the
literal document was.
"""
from __future__ import annotations

import hashlib
import os

TEXT = '@text'
AUTHORED = '@authored'
PARTS = '@parts'            # a sentence of our own wording with game text inside (TEXTHASH-DRPG, additive)


class TextRefError(RuntimeError):
    """A ``@text`` hash is not in the pool; the message says which field and how to fix it."""


def sha(value: str) -> str:
    """The reference digest of one exact text value."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def ref(value: str) -> dict:
    """A ``@text`` reference to ``value`` (the value is not written to disk)."""
    return {TEXT: sha(value)}


def authored(value: str) -> dict:
    """Wording our lanes wrote (a label, a note, an adaptation line): kept as text, marked as ours."""
    return {AUTHORED: value}


def is_ref(value) -> bool:
    """True for a reference shape (a dict whose only key is ``@text``, ``@authored`` or ``@parts``)."""
    return isinstance(value, dict) and len(value) == 1 and (TEXT in value or AUTHORED in value or PARTS in value)


def has_refs(value) -> bool:
    """True when ``value`` holds at least one ``@text``/``@authored`` reference (anywhere below it)."""
    if is_ref(value):
        return True
    if isinstance(value, dict):
        return any(has_refs(item) for item in value.values())
    if isinstance(value, list):
        return any(has_refs(item) for item in value)
    return False


def variants(value: str, folds=()):
    """Every spelling a source string may be stored under.

    The exact text comes first.  Each fold (for example the product-text ASCII fold, or NFKC) is
    applied to the exact value and to its NFKC spelling, so a reference to the spelling a pack writes
    resolves even when the source file stores a Unicode punctuation variant of it."""
    out = [value]
    seeds = [value]
    try:
        import unicodedata
        nfkc = unicodedata.normalize('NFKC', value)
    except (TypeError, ValueError):                       # pragma: no cover - a str always normalizes
        nfkc = value
    if nfkc != value:
        out.append(nfkc)
        seeds.append(nfkc)
    for fold in folds:
        for seed in seeds:
            try:
                folded = fold(seed)
            except Exception:                             # noqa: BLE001 - a fold never decides a build
                continue
            if isinstance(folded, str) and folded and folded not in out:
                out.append(folded)
    return out


class TextPool:
    """SHA-256 -> text of every string a build may read from the user's own game files.

    ``label`` names the source in a refusal ("the prepared Disgaea D2 source", "the Disgaea 5
    tables"); ``folds`` are spelling transforms (see :func:`variants`)."""

    def __init__(self, strings=(), *, label='text pool', folds=()):
        self.label = label
        self.folds = tuple(folds)
        self._by_sha = {}
        for value in strings:
            self.add(value)

    def add(self, value):
        if not isinstance(value, str) or not value:
            return
        for candidate in variants(value, self.folds):
            self._by_sha.setdefault(sha(candidate), candidate)

    def update(self, values):
        for value in values:
            self.add(value)

    def merge(self, other):
        """Fold another pool's strings in (both pools stay usable)."""
        self._by_sha.update(other._by_sha)
        if other.label and other.label not in self.label:
            self.label = f'{self.label} and {other.label}'
        return self

    def get(self, digest: str) -> str:
        value = self._by_sha.get(digest)
        if value is None:
            raise TextRefError(
                f'text {digest} is not in {self.label}; the game edition or the checked-in recipe '
                'changed. Re-run tools/prep_source.py with the reviewed dump (or point D5_SOURCE_DIR '
                'at the prepared folder) and check the file that names this hash.')
        return value

    def __contains__(self, digest) -> bool:
        return digest in self._by_sha

    def has_text(self, value) -> bool:
        """True when ``value`` (or one of its fold spellings) is a string this pool holds."""
        return any(sha(candidate) in self._by_sha for candidate in variants(value, self.folds))

    def __len__(self) -> int:
        return len(self._by_sha)


def resolve(value, text, where: str = '<root>'):
    """Replace every ``@text``/``@authored`` reference under ``value`` (dict/list) with its text.

    ``text`` is a callable ``(sha256) -> str`` (normally :meth:`TextPool.get`).  An unknown hash
    raises :class:`TextRefError` with ``where`` (the JSON path, which names the pack/skill id) in
    front, so the refusal says exactly which field failed."""
    if isinstance(value, dict):
        if set(value) == {TEXT}:
            try:
                return text(value[TEXT])
            except TextRefError as exc:
                raise TextRefError(f'{where}: {exc}') from None
        if set(value) == {AUTHORED}:
            return value[AUTHORED]
        if set(value) == {PARTS}:
            return ''.join(part if isinstance(part, str) else resolve(part, text, f'{where}.{PARTS}')
                           for part in value[PARTS])
        return {key: resolve(item, text, f'{where}.{key}') for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, text, f'{where}[{index}]') for index, item in enumerate(value)]
    return value


def resolve_doc(doc, text, where: str = '<root>'):
    """Field-level resolution that keeps the document's order and every non-reference value."""
    return resolve(doc, text, where)


# --------------------------------------------------------------------------- Disgaea 5 tables (cached)
_D5_POOLS = {}


def d5_text_pool(game_path, state_root) -> TextPool:
    """Every char/Skill/magic name and description of the user's own Disgaea 5 install.

    Read through the kit's read-only backup resolver, so a modded live install still yields the
    pristine rows the importer was reviewed against.  Cached per (game, state) pair: the build reads
    it once and every reviewed row resolves against the same strings."""
    key = (str(game_path), str(state_root))
    if key not in _D5_POOLS:
        from . import database, gamefs, newclasses
        from .d4unique import Originals

        fs = gamefs.GameFS(str(game_path), backup_resolver=Originals(state_root))
        pool = TextPool(label='the Disgaea 5 tables', folds=(_ascii_latin,))
        try:
            chars = database.load_table('char.dat', fs.read(newclasses.CHAR))
            for row in chars.rows:
                pool.update(v for k in row.keys() if k.startswith('name_')
                            for v in (row.get(k),) if isinstance(v, str) and v)
            for name, path in (('Skill.dat', newclasses.SKILL), ('magic.dat', newclasses.MAGIC)):
                table = database.load_table(name, fs.read(path))
                for row in table.rows:
                    pool.update(v for k in row.keys() if k.startswith(('name_', 'desc_'))
                                for v in (row.get(k),) if isinstance(v, str) and v)
        finally:
            fs.reset()
        _D5_POOLS[key] = pool
    return _D5_POOLS[key]


def _ascii_latin(text):
    """The product-text ASCII fold (d5lib.nativeimports.ascii_latin), imported lazily."""
    from .nativeimports import ascii_latin
    return ascii_latin(text)


def d5_text_pool_for_build(game_path=None, state_root=None) -> TextPool:
    """The D5 pool for a caller that has no build context (a maintainer tool or a test).

    The importer always passes its own ``game_path``/``state_root``; this resolver is the documented
    fallback and refuses, naming what to supply, when the kit cannot find the game or its backups."""
    from . import modsys, paths

    game = str(game_path or paths.require_game_dir())
    state = str(state_root or modsys.game_state_dir(game, modsys.KIT_DIR))
    if not (game_path and state_root) and not os.path.isfile(os.path.join(state, 'backups.json')):
        raise TextRefError(
            f'the Disgaea 5 backups are not in {state} (no backups.json): pass the game and its state '
            'folder to the build, or run from the installed kit. The @text references in this file '
            'are resolved from the pristine tables those backups hold.')
    return d5_text_pool(game, state)
