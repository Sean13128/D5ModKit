"""Every input of the DD2 importer, and where it comes from (SOURCEPREP4-DD2).

Game bytes come from the user's prepared source folder only (``SOURCEPREP2``: ``d5lib/sourcefolder.py``),
``<Disgaea 5 Complete>/D5ModKit/Source/dd2/PS3_GAME/USRDIR/Data``, and only when the prep manifest lists
each required file as verified and the file is actually there.  ``data_dir`` returns a :class:`Dd2Data`
whose ``files`` mapping is the *only* archive set any reader may open, so an archive the manifest never
mentions cannot win the readers' priority scan.

Ids and rules that used to sit in the project tree or in the installed packs are checked-in data files
next to this module; no game text is in the kit.  The DD2 reader package (Character Forge's
``forge.d2art``/``forge.nisfiles``/``forge.backend.d2_character_export`` and the ``_dd2_prepare`` glue)
is code, not game data: it is resolved explicitly through ``D5_DD2_FORGE`` (or the kit setting
``dd2_forge``) and never through a path specific to one machine.  See
Subprojects/Engine-Extensions/SOURCEPREP4-DD2-REPORT.md.
"""
from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path
import re

from .. import paths, sourcefolder

DATA_REL = 'PS3_GAME/USRDIR/Data'
# Every DD2 archive the baseline build can read; prep copies and verifies all of them.
REQUIRED = (
    'START.dat', 'START_1.dat', 'START_2.dat', 'START_3.dat', 'START_4.dat', 'START_5.dat', 'START_6.dat',
    'ANM_HI.dat', 'ANM_HI_1.dat', 'ANM_HI_2.dat', 'ANM_HI_3.dat', 'ANM_HI_4.dat', 'ANM_HI_5.dat', 'ANM_HI_6.dat',
)
FORGE_ENV = 'D5_DD2_FORGE'
FORGE_SETTING = 'dd2_forge'
POSE_ENV = 'D5_DD2_POSE_TABLE'
HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
DATA = HERE.parent / 'data'

BASELINE_CONFIGS = HERE / 'dd2-baseline-configs.json'
ABILITY_REVIEW = HERE / 'dd2-ability-review.json'
ENGINE_EMISSION = HERE / 'dd2-engine-emission.json'
FROZEN_PATCHES = HERE / 'dd2-frozen-patches.json'
CLAIMED_IDS = HERE / 'dd2-claimed-ids.json'
WHEEL_REFERENCE = HERE / 'dd2-wheel-reference.json'
POSE_TABLE = DATA / 'dd2-common-poses.json'


class Dd2SourceError(RuntimeError):
    """A required DD2 input is missing, unverified or ambiguous; the message says which and how to supply it."""


class Dd2Data:
    """The verified DD2 source file set every DD2 reader must stay inside.

    ``files`` maps a bare file name (``START_4.dat``) to the one verified physical path.  ``archives``
    preserves the source priority (numbered add-on archives newest first, base archive last) and refuses
    a stem whose base archive is absent.  No reader may glob the folder: a file absent from ``files``
    does not exist for the importer even when it sits in the same directory.
    """

    def __init__(self, root, files, *, prepared=False):
        self.root = Path(root)
        self.files = {str(name): Path(path) for name, path in files.items()}
        self.prepared = bool(prepared)

    def path(self, name):
        path = self.files.get(name)
        if path is None:
            where = 'the verified prepared source set' if self.prepared else 'the explicit source folder'
            raise Dd2SourceError(f'DD2 source file {name} is not in {where} ({self.root}); '
                                 're-run tools/prep_source.py --dd2 ... or pass --source-root for a diagnostic run')
        return path

    def archives(self, stem):
        """Archive paths for ``stem`` in source priority: numbered add-ons newest first, base last."""
        names = sorted((n for n in self.files if n.startswith(stem) and n.endswith('.dat')),
                       key=lambda n: (len(n), n))
        if not names or names[0] != stem + '.dat':
            raise Dd2SourceError(f'DD2 source base archive {stem}.dat is missing from the source set '
                                 f'({self.root}); re-run tools/prep_source.py --dd2 ...')
        return [self.files[n] for n in names[1:][::-1]] + [self.files[stem + '.dat']]

    def to_config(self):
        return dict(root=str(self.root), prepared=self.prepared,
                    files={name: str(path) for name, path in self.files.items()})

    @classmethod
    def from_config(cls, doc):
        doc = doc or {}
        return cls(doc.get('root') or '.', doc.get('files') or {}, prepared=bool(doc.get('prepared')))


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def data_dir(explicit=None):
    """The verified DD2 source set: the prepared source folder, or an explicit root for a diagnostic run.

    Without ``explicit`` the SOURCEPREP2 folder is used and every required archive must have a
    ``verified: "yes"`` row in ``manifest.json`` *and* be present on disk; a missing or failed row is
    refused and names the file.  ``explicit`` keeps the old CLI/test behaviour (a dump root, its ``Data``
    folder or the ``disc/*/PS3_GAME/USRDIR/Data`` folder); it is unverified, so it is for comparison and
    diagnosis only and is never the default.
    """
    if explicit:
        root = _normalize(Path(explicit))
        files = {p.name: p for p in sorted(root.iterdir()) if p.is_file() and p.suffix == '.dat'} \
            if root.is_dir() else {}
        if not files:
            raise Dd2SourceError(f'No DD2 *.dat archives under the explicit source root {root}')
        return Dd2Data(root, files, prepared=False)
    return _prepared()


def _prepared():
    folder = sourcefolder.source_dir()
    manifest = folder / 'manifest.json'
    if not manifest.is_file():
        raise Dd2SourceError(
            f'No prepared DD2 source: {manifest} is missing. Run `python tools/prep_source.py --dd2 '
            f'<decrypted PS3 dump holding PS3_GAME/USRDIR/Data>` (or point D5_SOURCE_DIR at a prepared folder).')
    try:
        doc = sourcefolder.read_manifest(folder)
    except (OSError, ValueError) as exc:
        raise Dd2SourceError(f'Prepared source manifest {manifest} is unreadable: {exc}') from exc
    games = doc.get('games') or {}
    entry = games.get('dd2') or {}
    rows = {row.get('path'): row for row in entry.get('files', [])}
    if 'dd2' not in games or entry.get('supplied') is False or not rows:
        raise Dd2SourceError(
            f'The prepared source folder {folder} has no Disgaea D2 files. Run `python tools/prep_source.py '
            f'--dd2 <decrypted PS3 dump holding PS3_GAME/USRDIR/Data>`.')
    problems = []
    files = {}
    for name in REQUIRED:
        rel = f'{DATA_REL}/{name}'
        row = rows.get(rel)
        if row is None:
            problems.append(f'dd2/{rel}: no manifest row (re-run tools/prep_source.py --dd2 ...)')
            continue
        state = row.get('verified')
        if state != 'yes':
            detail = row.get('note') or 'size/SHA-256 do not match the known Disgaea D2 dump'
            problems.append(f'dd2/{rel}: manifest says verified {state!r} ({detail})')
            continue
        path = folder / 'dd2' / rel
        if not path.is_file():
            problems.append(f'dd2/{rel}: manifest row is verified but the file is missing at {path} '
                            f'(re-run tools/prep_source.py --dd2 ...)')
            continue
        size = row.get('size')
        if isinstance(size, int) and path.stat().st_size != size:
            problems.append(f'dd2/{rel}: file size {path.stat().st_size} does not match the manifest '
                            f'{size} (re-run tools/prep_source.py --dd2 ...)')
            continue
        files[name] = path
    if problems:
        raise Dd2SourceError('The prepared DD2 source cannot be used:\n  ' + '\n  '.join(problems))
    root = folder / 'dd2' / DATA_REL
    return Dd2Data(root, files, prepared=True)


def _normalize(root):
    root = Path(root)
    if root.is_file():
        return root.parent if root.name.endswith('.dat') else root
    if (root / 'START_4.dat').is_file():
        return root
    for cand in (root / 'Data', root / DATA_REL):
        if (cand / 'START_4.dat').is_file():
            return cand
    matches = sorted(root.glob('disc/*/PS3_GAME/USRDIR/Data/START_4.dat'))
    if len(matches) == 1:
        return matches[0].parent
    raise Dd2SourceError(
        f'No Disgaea D2 Data folder with START_4.dat under {root}; pass the decrypted PS3 dump folder '
        f'(holding PS3_GAME/USRDIR/Data) or use the prepared source folder.')


def pose_table():
    """The pinned shared-pose rules table: ``D5_DD2_POSE_TABLE``, the prepared folder, else the kit copy."""
    env = os.environ.get(POSE_ENV)
    if env and env.strip():
        path = Path(env.strip()).expanduser()
        if not path.is_file():
            raise Dd2SourceError(f'{POSE_ENV} points at {path}, which is not a file')
        return path
    prepared = sourcefolder.source_dir() / 'dd2' / 'd2-common-poses.json'
    if prepared.is_file():
        return prepared
    if POSE_TABLE.is_file():
        return POSE_TABLE
    raise Dd2SourceError(
        f'The DD2 shared-pose table is missing ({POSE_TABLE}); set {POSE_ENV} to a d2-common-poses.json.')


def forge_root():
    """The folder that holds the ``forge`` reader package (``forge/d2art.py``).

    Order: ``D5_DD2_FORGE``, the kit setting ``dd2_forge``, then a ``forge`` package beside the kit.
    The Character Forge reference tree is outside this repository on purpose (provenance review pending),
    so no project path is guessed.
    """
    candidates = []
    env = os.environ.get(FORGE_ENV)
    if env and env.strip():
        candidates.append(Path(env.strip()).expanduser())
    saved = paths.kit_setting(FORGE_SETTING)
    if saved and str(saved).strip():
        candidates.append(Path(str(saved).strip()).expanduser())
    candidates.append(KIT.parent / 'forge')
    for root in candidates:
        if (root / 'forge' / 'd2art.py').is_file() or (root / 'd2art.py').is_file():
            return root if (root / 'forge').is_dir() else root.parent
    raise Dd2SourceError(
        'The Disgaea D2 reader package (Character Forge `forge/d2art.py`) was not found. Set '
        f'{FORGE_ENV} to the folder holding `forge/` (for example '
        '`<project>/Migration/CharacterForge`) or save the same path as the kit setting `dd2_forge`. '
        'Those readers are outside-kit code today (SOURCEPREP1-REPORT.md section 1.5); vendoring them is a '
        'follow-up card, not something this importer may guess a path for.')


def baseline_config(source_id):
    """The frozen packet rows for the two DD2 continuation uniques (sources 30 and 100)."""
    doc = _json(BASELINE_CONFIGS)
    entry = doc['uniques'].get(str(source_id))
    if entry is None:
        return None
    return dict(entry['source'], _config_file=entry['config'])


def ability_review():
    return _json(ABILITY_REVIEW)


def engine_emission():
    return _json(ENGINE_EMISSION)


def frozen_patches(folder, text=None):
    """Frozen ability/alias rows the shipped pack carries; ``{}`` for a folder with none.

    ``text`` is a callable ``(sha256) -> str`` that returns the final game text for a text field.
    The checked-in recipe stores only that hash (or an authored literal), so no game text is in Git;
    the build reads it from the user's own prepared archives and Disgaea 5 tables.  Without ``text``
    the recipe's raw ``doc`` (placeholders included) is returned, which is useful only for inspection.
    """
    entry = _json(FROZEN_PATCHES)['folders'].get(folder)
    if not entry:
        return {}
    files = {}
    for rel, item in (entry.get('files') or {}).items():
        if text is None:
            files[rel] = item
            continue
        doc = _resolve_text(item['doc'], text)
        rendered = render_frozen(item, doc)
        expected = item.get('sha256')
        if expected:
            import hashlib
            got = hashlib.sha256(rendered.encode('utf-8')).hexdigest()
            if got != expected:
                raise Dd2SourceError(
                    f'Frozen DD2 patch {folder}/{rel} rebuilt to {got}, not the recorded {expected}; '
                    'the prepared source edition or the checked-in recipe changed.')
        files[rel] = rendered
    return dict(entry, files=files)


def render_frozen(item, doc):
    """The exact bytes a frozen patch file has in the installed pack (JSON, indent 1, no sort)."""
    text = json.dumps(doc, indent=1, ensure_ascii=False) + ('\n' if item.get('newline') else '')
    return text


def _resolve_text(value, text):
    if isinstance(value, dict):
        if set(value) == {'@text'}:
            return text(value['@text'])
        if set(value) == {'@authored'}:
            return value['@authored']
        return {key: _resolve_text(item, text) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_text(item, text) for item in value]
    return value


def claimed_ids():
    return {int(k): list(v) for k, v in _json(CLAIMED_IDS)['claims'].items()}


def wheel_reference(folder):
    """Recorded ANM header shapes of the shipped pack ({member: (textures, palettes)}), or ``{}``.

    Used by ``importcore.wheel_gate`` when no installed copy exists, so a machine without installed packs
    freezes the wheel against the same shapes (the DD2LEN1 source-clock fallback then matches)."""
    files = _json(WHEEL_REFERENCE)['folders'].get(folder) or {}
    return {rel: tuple(shape) for rel, shape in files.items()}


# --------------------------------------------------------------------------- text pools (no game text in Git)
def normalize_source_text(value):
    """The spelling the reviewed rows use for source text: NFKC, then one space between words."""
    return re.sub(r'  +', ' ', unicodedata.normalize('NFKC', value))


def text_sha(value):
    import hashlib
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class TextPool:
    """Hashes of every game text the build may read from the user's own files.

    The frozen-patch recipe carries only a SHA-256 per text field.  This pool collects the DD2 source
    strings (as stored and in the reviewed NFKC spelling) and the Disgaea 5 Skill.dat/magic.dat strings,
    so a field resolves to exactly the text the installed pack carried, read from game files the user
    supplied -- never from Git.
    """

    def __init__(self, strings=()):
        self._by_sha = {}
        for value in strings:
            for candidate in (value, normalize_source_text(value)):
                if candidate:
                    self._by_sha.setdefault(text_sha(candidate), candidate)

    def get(self, digest):
        value = self._by_sha.get(digest)
        if value is None:
            raise Dd2SourceError(
                f'Frozen DD2 patch text {digest} is not in the prepared source or the Disgaea 5 tables; '
                'the source edition or the checked-in recipe changed. Re-run tools/prep_source.py with the '
                'reviewed dump and check dd2-frozen-patches.json.')
        return value

    @classmethod
    def from_game(cls, data, fs=None):
        """Collect DD2 source strings and, when ``fs`` is given, the Disgaea 5 skill tables."""
        strings = set(source_strings(data))
        if fs is not None:
            from .. import database, newclasses
            for path in (newclasses.SKILL, newclasses.MAGIC):
                table = database.load_table('Skill.dat' if path is newclasses.SKILL else 'magic.dat', fs.read(path))
                for row in table.rows:
                    strings.update(v for k in row.keys() if k.startswith(('name_', 'desc_'))
                                   for v in (row.get(k),) if isinstance(v, str) and v)
        return cls(strings)


def source_strings(data):
    """Every string the DD2 source tables carry (skills, evilities, characters, help lines)."""
    from .. import dd2source
    tables = dd2source.Tables(dd2source.Nispack(data.path('START_4.dat').read_bytes()))
    strings = set()
    for row in tables.skills.values():
        strings.update(v for v in row.values() if isinstance(v, str))
    for row in tables.evilities.values():
        strings.update(v for v in row.values() if isinstance(v, str))
    for row in tables.chars.values():
        strings.update(v for v in row.values() if isinstance(v, str))
    strings.update(tables.helps.values())
    return strings


def text_pool(data=None, d5=None):
    """The pool the DD2 ``@text`` references in sourcemaps/leases/voice/innate data resolve against.

    TEXTHASH-D1C-DD2: same DD2 source strings and product-text fold as the frozen-patch rule, in the
    shared :mod:`d5lib.textrefs` shape.  ``d5`` (from :func:`d5lib.textrefs.d5_text_pool`) adds the
    Disgaea 5 rows a reviewed file names."""
    from ..nativeimports import ascii_latin
    from ..textrefs import TextPool

    data = data or data_dir()
    pool = TextPool(label='the prepared Disgaea D2 source', folds=(ascii_latin,))
    pool.update(source_strings(data))
    if d5 is not None:
        pool.merge(d5)
    return pool
