"""The DRPG roster (reviewed groups and their mapped abilities) without game text in Git (SOURCEPREP4-DRPG).

``drpg-roster.json`` carries, for every reviewed base character, the same record the importer used to read from
``Research/source-packs/drpg/mapping.json`` + ``grouping-decisions.json`` + ``drpg-family/families.json``: ids,
rules, verdicts, counts and the mapped abilities.  Every game text in it is a reference, never the text:

* ``{"@text": "<sha256>"}``: a string of the user's own files, resolved at build time from the prepared masters
  (``masters/*.json``, verified) and the Disgaea 5 tables of the user's own install; a text that no source holds is
  refused, so the roster cannot silently become a different one;
* ``{"@authored": "<text>"}``: wording written by this project (English names, mapping reasons);
* ``{"@parts": [...]}``: a sentence of this project's wording with game text inside it: literal pieces (ASCII or
  punctuation only) and ``@text`` references to the non-ASCII runs the user's own files hold.

``tools/build_drpg_rules.py roster`` regenerates the file from the old research inputs (maintainer tool).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The roster is split in parts (the kit's commit guard allows no file over 1 MB); the parts are read in this order.
PARTS = tuple(HERE / f'drpg-roster-{i}.json' for i in range(4))
ROSTER = PARTS[0]            # the name the provenance records (the whole set is hashed together)
SCHEMA = 'drpg-roster/1'
MASTERS = ('character', 'charactercommand', 'command', 'leaderskill')
# Optional text masters: read into the text pool when the prepared folder lists them (TEXTHASH-DRPG: the class titles
# of drpg-titles.json are rows of ``characterclassname``); a hash that needs one and finds it absent is refused by name.
TEXT_MASTERS = ('characterclassname',)


class DrpgRosterError(ValueError):
    pass


RUN = re.compile(r'[^\x00-\x7f]+')


def is_punctuation(run):
    """True for a run of punctuation, symbols and spaces only (a full-width percent sign, a dash): not game text."""
    return all(unicodedata.category(ch)[0] in 'PSZ' for ch in run)


def runs(value):
    return [m.group(0) for m in RUN.finditer(value)]


def text_sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class TextPool:
    """Hashes of every game text the build may read from the user's own files."""

    def __init__(self, strings=()):
        self._by_sha = {}
        for value in strings:
            if isinstance(value, str) and value:
                for candidate in (value, unicodedata.normalize('NFKC', value), *runs(value)):
                    self._by_sha.setdefault(text_sha(candidate), candidate)

    def sub(self, digest, of, at):
        """The fragment ``at`` = [start, end) of the pool text ``of`` (a longer source string), checked against its hash."""
        text = self.get(of)[int(at[0]):int(at[1])]
        if text_sha(text) != digest:
            raise DrpgRosterError(f'DRPG roster fragment {digest} is not at {list(at)} of source text {of}; '
                                  'the source edition or the checked-in roster changed.')
        return text

    def find_parent(self, fragment):
        """(sha of a pool text holding ``fragment``, [start, end)) or None; the shortest holder wins."""
        best = None
        for text in self._by_sha.values():
            i = text.find(fragment)
            if i >= 0 and (best is None or len(text) < len(best[0])):
                best = (text, i)
        if best is None:
            return None
        return text_sha(best[0]), [best[1], best[1] + len(fragment)]

    def get(self, digest):
        value = self._by_sha.get(digest)
        if value is None:
            raise DrpgRosterError(
                f'DRPG text {digest} is not in the prepared masters (character, charactercommand, command, leaderskill, '
                'characterclassname) or the Disgaea 5 tables; the source edition or the checked-in recipe changed, or the '
                'prepared folder predates masters/characterclassname.json. Re-run tools/prep_source.py --drpg ... '
                '--drpg-masters ... and check the file that holds this hash.')
        return value

    def __contains__(self, value):
        return text_sha(value) in self._by_sha

    @classmethod
    def from_sources(cls, data, fs=None):
        """Strings of the verified masters (``drpg/masters/<name>.json``) and, with ``fs``, the D5 text columns."""
        strings = set()

        def walk(node):
            if isinstance(node, str):
                strings.add(node)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, dict):
                for item in node.values():
                    walk(item)

        for name in MASTERS + TEXT_MASTERS:
            rel = f'masters/{name}.json'
            if data.have(rel):
                walk(json.loads(data.read(rel)))
        if fs is not None:
            from .. import database
            for table in ('Skill.dat', 'magic.dat', 'char.dat', 'charhelp.dat'):
                try:
                    rows = database.load_table(table, fs.read('Database/Database_0.dat/' + table)).rows
                except (KeyError, OSError):
                    continue
                for row in rows:
                    for key in row.keys():
                        if key.startswith(('name_', 'desc_', 'title_', 'text_')):
                            value = row.get(key)
                            if isinstance(value, str):
                                strings.add(value)
        return cls(strings)


def resolve(value, pool):
    """Replace every ``@text`` / ``@authored`` reference of a roster record by its text."""
    if isinstance(value, dict):
        if set(value) == {'@text'}:
            return pool.get(value['@text'])
        if set(value) == {'@text', 'of', 'at'}:
            return pool.sub(value['@text'], value['of'], value['at'])
        if set(value) == {'@authored'}:
            return value['@authored']
        if set(value) == {'@parts'}:
            return ''.join(part if isinstance(part, str) else resolve(part, pool) for part in value['@parts'])
        return {key: resolve(item, pool) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, pool) for item in value]
    return value


def load(parts=None):
    """The roster document: the ``groups`` of every part, in order."""
    groups = []
    for part in parts or PARTS:
        doc = json.loads(Path(part).read_text(encoding='utf-8'))
        if doc.get('schema') != SCHEMA:
            raise DrpgRosterError(f'unsupported DRPG roster schema {doc.get("schema")!r}')
        groups.extend(doc['groups'])
    return dict(schema=SCHEMA, groups=groups)


def file_sha256(parts=None):
    """SHA-256 over the part files' bytes in order (the roster identity recorded in every pack)."""
    h = hashlib.sha256()
    for part in parts or PARTS:
        h.update(Path(part).read_bytes())
    return h.hexdigest()


def characters(pool, parts=None):
    """[(character record, best base look id)] with every text resolved, in roster order."""
    doc = load(parts)
    out = []
    for item in doc['groups']:
        out.append((resolve(item['character'], pool), item['best']))
    return out


SHAPES = HERE / 'drpg-bank-shapes.json'


def bank_shapes(path=None):
    """{pack folder: {bank member: [textures, palettes]}} recorded from the shipped packs (counts only)."""
    doc = json.loads(Path(path or SHAPES).read_text(encoding='utf-8'))
    if doc.get('schema') != 'drpg-bank-shapes/1':
        raise DrpgRosterError(f'unsupported DRPG bank shape schema {doc.get("schema")!r}')
    return doc['packs']


def icon_pins(folder, path=None):
    """{class id: [48 px row, 64 px row]} the shipped pack's list-icon pairs (``icons`` of ``drpg-bank-shapes.json``)."""
    doc = json.loads(Path(path or SHAPES).read_text(encoding='utf-8'))
    return {str(k): list(v) for k, v in (doc.get('icons', {}).get(folder) or {}).items()}
