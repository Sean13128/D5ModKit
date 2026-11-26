"""SMALLFIX1: the class title a Disgaea RPG character shows under its name on the status panel.

Every DRPG pack used to write the group label "Disgaea RPG" there (a literal in _drpg_build).  The panel reads the
char row's own title field, so each character now gets the title its own source row carries
(`drpg-titles.json`: JP characterclassname at the character's base rarity; English from the Disgaea RPG Wiki
where it documents one, else a labelled provisional translation).  Two characters have no title in the source
(monster / collab id block); they keep the group label and are named in the table's `no_source_title`.

DRPGTITLE2 (rework 2026-11-19): 9 titles carry a documented English (`en_kind` "community", cited in `en_source`
by wiki page, revision, author and quoted name, with the archived Global master as corroboration where it agrees);
the other 135 stay provisional and say why.  The two titles whose wiki and Global names disagree (55, 20011) stay
provisional.  `apply` rewrites every row, so a staged pack can be re-titled in place.
"""
import json
from pathlib import Path

from . import _drpg_text

TABLE = Path(__file__).with_name('drpg-titles.json')
PLACEHOLDER = 'Disgaea RPG'
LATIN = ('EN', 'FR')
CJK = ('JP', 'CHN', 'KOR')


def load():
    """the title table with its text references resolved (TEXTHASH-DRPG: JP titles are hashes of the prepared source)"""
    return _drpg_text.load(TABLE)


def title_of(base_id, doc=None):
    """{'jp', 'en', ...} for a base character, or None when the source has no title."""
    return (doc or load())['titles'].get(str(int(base_id)))


def apply(mod_dir, base_id, doc=None):
    """Write the table's title into the title fields of every char row of the pack.  Returns the number of rows
    changed (0 for a character without a source title).  Idempotent: a row that already carries another title (an
    installed pack whose wording predates a table edit) is rewritten, so a stage step can re-title an existing pack
    without a full rebuild (DRPGTITLE2)."""
    rec = title_of(base_id, doc)
    path = Path(mod_dir) / 'patches/db/char.dat.json'
    if rec is None or not path.is_file():
        return 0
    patch = json.loads(path.read_text(encoding='utf-8'))
    n = 0
    for row in patch.get('added') or []:
        for lang in LATIN:
            row[f'title_{lang}'] = rec['en']
        for lang in CJK:
            row[f'title_{lang}'] = rec['jp']
        n += 1
    if n:
        path.write_text(json.dumps(patch, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    return n


def gate(mod_dir, base_id, doc=None):
    """(ok, why): no row of the pack shows the group label unless the source has no title for the character, and
    every row of a titled character shows exactly its table title."""
    doc = doc or load()
    rec = title_of(base_id, doc)
    path = Path(mod_dir) / 'patches/db/char.dat.json'
    rows = (json.loads(path.read_text(encoding='utf-8')).get('added') or []) if path.is_file() else []
    if rec is None:
        if str(int(base_id)) in doc['no_source_title']:
            return True, 'no source title; group label kept'
        return False, f'base id {base_id} has no entry in drpg-titles.json'
    bad = [r['id'] for r in rows if r.get('title_EN') != rec['en'] or r.get('title_JP') != rec['jp']]
    return (not bad), (f'rows {bad[:4]} do not carry the title {rec["en"]!r}' if bad else '')
