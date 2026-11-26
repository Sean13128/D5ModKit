"""Every input of the D4 importer, and where it comes from (SOURCEPREP4-D4).

Game bytes come from the user's prepared source folder only (``SOURCEPREP2``: ``d5lib/sourcefolder.py``),
``<Disgaea 5 Complete>/D5ModKit/Source/d4``, and only when the prep manifest lists each required file as
verified and the file is actually there.  ``data_dir`` returns a :class:`D4Files` whose ``files`` mapping is
the *only* file set any D4 reader may open, so a file the manifest never mentions cannot be read even when it
sits in the same folder.

Ids and rules that used to sit in the project tree or in the installed packs are checked-in data files next
to this module (``d4-allocation.json``, ``d4-mapping.json``, ``d4-extension-rows*.json``, ``d4-reserved-ids.json``,
``d4-unique-commands.json``, ``d4-specials.json``, ``d4-bank-shapes.json`` and the existing ``d4-leases.json`` /
``d4-scope.json`` / ``d4-evility-overlay.json`` / ``d4-evility-additions.json``).  **No game text is in the kit**:
players' names, descriptions and titles are stored as SHA-256 references (or a template hash plus the numbers
rendered into it) and resolved at build time from the user's own D4 and Disgaea 5 tables by :class:`TextPool`.

Prepared art (the packets ``tools/build_source_pack.py`` / ``tools/build_d4_unique.py`` read) is regenerated
from the verified ``ANM_HI.dat`` on every build, in the build scratch, using the Character Forge art code.  That
code is outside the kit on purpose (provenance review pending, as for DD2): it is resolved explicitly through
``D5_D4_FORGE`` or the kit setting ``d4_forge``, never through a path specific to one machine.  The pose table
the packets were learned from is checked-in rule data (``d5lib/data/d4-common-poses.json``).

See Subprojects/Engine-Extensions/SOURCEPREP4-D4-REPORT.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from .. import d4source, paths, sourcefolder

# Every D4 file the importer can read; tools/prep_source.py copies and verifies all of them.
REQUIRED = (
    'Data/DATA/ANM_HI.dat',
    'Data/DATA/WF.dat',
    'Data/DATA/EN/DATABASE_EN.dat',
    'Data/DATA/JP/DATABASE.dat',
    'Data/SOUND/EN/voice.dat',
    'Data/SOUND/JP/voice.dat',
    'Data/SOUND/SoundData_Voice_EN.dat',
    'Data/SOUND/SoundData_Voice_JP.dat',
)
DATABASE_EN = 'Data/DATA/EN/DATABASE_EN.dat'
FORGE_ENV = 'D5_D4_FORGE'
FORGE_SETTING = 'd4_forge'
HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'
POSE_TABLE = DATA / 'd4-common-poses.json'

ALLOCATION = HERE / 'd4-allocation.json'
MAPPING = HERE / 'd4-mapping.json'
EMISSION = HERE / 'd4-extension-rows.json'
CAST_EMISSION = HERE / 'd4-extension-rows-cast.json'
RESERVED = HERE / 'd4-reserved-ids.json'
COMMANDS = HERE / 'd4-unique-commands.json'
SPECIALS = HERE / 'd4-specials.json'
BANK_SHAPES = HERE / 'd4-bank-shapes.json'
LEASES = HERE / 'd4-leases.json'
SCOPE = HERE / 'd4-scope.json'
OVERLAY = HERE / 'd4-evility-overlay.json'
ADDITIONS = HERE / 'd4-evility-additions.json'


class D4SourceError(RuntimeError):
    """A required D4 input is missing, unverified or ambiguous; the message says which and how to supply it."""


_VERIFIED = {}      # (path, size, mtime_ns, inode) -> SHA-256 already proven equal to the manifest row


def verify_file(path, sha256, label):
    """Prove ``path`` still holds the bytes the verified manifest row attests (SHA-256), once per file state.

    The proof is keyed on the file's stat signature: an unchanged file is hashed once per process, while a
    replaced or edited file (even one of the same size) is hashed again and refused when it no longer matches."""
    if not sha256:
        raise D4SourceError(f'{label}: the manifest row carries no SHA-256, so the file cannot be trusted '
                            '(re-run tools/prep_source.py)')
    st = os.stat(path)
    key = (str(path), st.st_size, st.st_mtime_ns, st.st_ino)
    if _VERIFIED.get(key) == sha256:
        return
    got = sourcefolder.sha256_file(path)
    if got != sha256:
        raise D4SourceError(f'{label}: the bytes on disk (SHA-256 {got[:16]}...) no longer match the verified '
                            f'manifest row ({sha256[:16]}...); re-run tools/prep_source.py')
    _VERIFIED[key] = sha256


class D4Files:
    """The verified D4 source file set every D4 reader must stay inside.

    ``files`` maps the relative path (``Data/DATA/EN/DATABASE_EN.dat``) to the one verified physical path.
    ``path`` refuses any other name and, on the prepared route, re-proves the file's SHA-256 against its
    manifest row (stat-keyed, so a same-size replacement is caught), so no reader can open a file that merely
    sits in the folder or that changed after prep.  ``data`` builds the D4 table reader on the same set, and
    every open it makes goes through ``path``.
    """

    def __init__(self, root, files, *, prepared=False, hashes=None):
        self.root = Path(root)
        self.files = {str(rel): Path(path) for rel, path in files.items()}
        self.prepared = bool(prepared)
        self.hashes = {str(rel): str(sha) for rel, sha in (hashes or {}).items()}
        self._data = {}

    def path(self, rel):
        path = self.files.get(rel)
        if path is None:
            where = 'the verified prepared source set' if self.prepared else 'the explicit source folder'
            raise D4SourceError(
                f'D4 source file {rel} is not in {where} ({self.root}); re-run tools/prep_source.py '
                f'(Disgaea 4 Complete+, Steam app 1233880) or pass --source-root for a diagnostic run')
        if self.prepared:
            verify_file(path, self.hashes.get(rel), f'd4/{rel}')
        return path

    def verify(self):
        """Re-prove every file of the set (cheap after the first call per file state); returns self."""
        for rel in self.files:
            self.path(rel)
        return self

    def data(self, lang='EN'):
        """`d4source.D4Data` over the verified set (only the tables naming required files exist)."""
        if lang not in self._data:
            self._data[lang] = d4source.D4Data(self.root, lang, locate=self.path)
        return self._data[lang]

    def anm_pack(self):
        return d4source.Nsac(self.path('Data/DATA/ANM_HI.dat'))

    def to_config(self):
        return dict(root=str(self.root), prepared=self.prepared, hashes=dict(self.hashes),
                    files={rel: str(path) for rel, path in self.files.items()})

    @classmethod
    def from_config(cls, doc):
        doc = doc or {}
        return cls(doc.get('root') or '.', doc.get('files') or {}, prepared=bool(doc.get('prepared')),
                   hashes=doc.get('hashes'))


def data_dir(explicit=None):
    """The verified D4 source set: the prepared source folder, or an explicit root for a diagnostic run.

    Without ``explicit`` the SOURCEPREP2 folder is used and every required file must have a
    ``verified: "yes"`` row in ``manifest.json`` *and* be present on disk; a missing or failed row is
    refused and names the file.  ``explicit`` keeps the old CLI/test behaviour (the D4 install folder,
    its ``Data`` or ``Data/DATA`` folder); it is unverified, so it is for comparison and diagnosis only
    and is never the default.
    """
    if explicit:
        return _explicit(Path(explicit))
    return _prepared()


def _explicit(given):
    root = _normalize(given)
    files = {}
    for rel in REQUIRED:
        path = root / rel
        if path.is_file():
            files[rel] = path
    if DATABASE_EN not in files:
        raise D4SourceError(
            f'No Disgaea 4 Data folder with {DATABASE_EN} under {given}; pass the D4 Complete+ install '
            f'folder or a prepared source folder')
    return D4Files(root, files, prepared=False)


def _normalize(root):
    root = Path(root)
    if (root / DATABASE_EN).is_file():
        return root
    for cand in (root / 'Disgaea 4 Complete+', root / 'Data', root / 'Data/DATA'):
        if (cand / DATABASE_EN).is_file() or (cand / 'DATABASE_EN.dat').is_file():
            if (cand / DATABASE_EN).is_file():
                return cand
            return cand.parent.parent
    matches = sorted(root.glob('*/Data/DATA/EN/DATABASE_EN.dat')) + sorted(root.glob('Data/DATA/EN/DATABASE_EN.dat'))
    if len(matches) == 1:
        return matches[0].parents[3]
    raise D4SourceError(
        f'No Disgaea 4 Data/DATA/EN/DATABASE_EN.dat under {root}; pass the Disgaea 4 Complete+ folder '
        f'(the one holding Data/DATA) or use the prepared source folder')


def _prepared():
    folder = sourcefolder.source_dir()
    manifest = folder / 'manifest.json'
    if not manifest.is_file():
        raise D4SourceError(
            f'No prepared D4 source: {manifest} is missing. Run `python tools/prep_source.py` with '
            f'Disgaea 4 Complete+ installed (Steam app 1233880), or pass --source-root for a diagnostic run '
            f'(or point D5_SOURCE_DIR at a prepared folder).')
    try:
        doc = sourcefolder.read_manifest(folder)
    except (OSError, ValueError) as exc:
        raise D4SourceError(f'Prepared source manifest {manifest} is unreadable: {exc}') from exc
    games = doc.get('games') or {}
    entry = games.get('d4') or {}
    rows = {row.get('path'): row for row in entry.get('files', [])}
    if 'd4' not in games or entry.get('supplied') is False or not rows:
        raise D4SourceError(
            f'The prepared source folder {folder} has no Disgaea 4 files. Run `python tools/prep_source.py` '
            f'with Disgaea 4 Complete+ installed (Steam app 1233880).')
    problems = []
    files, hashes = {}, {}
    for rel in REQUIRED:
        row = rows.get(rel)
        if row is None:
            problems.append(f'd4/{rel}: no manifest row (re-run tools/prep_source.py)')
            continue
        state = row.get('verified')
        if state != 'yes':
            detail = row.get('note') or 'size/SHA-256 do not match a known Disgaea 4 Complete+ build'
            problems.append(f'd4/{rel}: manifest says verified {state!r} ({detail})')
            continue
        path = folder / 'd4' / rel
        if not path.is_file():
            problems.append(f'd4/{rel}: manifest row is verified but the file is missing at {path} '
                            f'(re-run tools/prep_source.py)')
            continue
        size = row.get('size')
        if isinstance(size, int) and path.stat().st_size != size:
            problems.append(f'd4/{rel}: file size {path.stat().st_size} does not match the manifest {size} '
                            f'(re-run tools/prep_source.py)')
            continue
        if not row.get('sha256'):
            problems.append(f'd4/{rel}: the manifest row carries no SHA-256 (re-run tools/prep_source.py)')
            continue
        files[rel] = path
        hashes[rel] = row['sha256']
    if problems:
        raise D4SourceError('The prepared D4 source cannot be used:\n  ' + '\n  '.join(problems))
    return D4Files(folder / 'd4', files, prepared=True, hashes=hashes).verify()


# ------------------------------------------------------------------------------------- kit rule data
def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def allocation():
    return _json(ALLOCATION)


def mapping():
    return _json(MAPPING)


def emission(cast=False):
    return _json(CAST_EMISSION if cast else EMISSION)


def reserved(family):
    rows = _json(RESERVED).get('families') or {}
    row = rows.get(str(int(family)))
    if row is None:
        raise D4SourceError(f'no reserved-id row for D4 family {family} in {RESERVED.name}')
    return row


def commands():
    return _json(COMMANDS).get('uniques') or {}


def command(source_id):
    row = commands().get(str(int(source_id)))
    if row is None:
        raise D4SourceError(f'no recorded build command for D4 unique {source_id} in {COMMANDS.name}')
    return row


def specials():
    return _json(SPECIALS)


def overlay():
    return _json(OVERLAY)


def wheel_reference(folder):
    """Recorded ANM header shapes of the shipped D4 pack ({member: (textures, palettes)}), or ``{}``."""
    files = _json(BANK_SHAPES).get('folders', {}).get(folder) or {}
    return {rel: tuple(shape) for rel, shape in files.items()}


def pose_table():
    if not POSE_TABLE.is_file():
        raise D4SourceError(f'the D4 shared-pose table is missing ({POSE_TABLE})')
    return _json(POSE_TABLE)


# --------------------------------------------------------------------------- outside reader code
def forge_root():
    """The folder that holds the ``forge`` reader package (``forge/d2art.py``).

    Order: ``D5_D4_FORGE``, the kit setting ``d4_forge``, then a ``forge`` package beside the kit.
    The Character Forge reference tree is outside this repository on purpose (provenance review
    pending), so no project path is guessed.
    """
    candidates = []
    env = os.environ.get(FORGE_ENV)
    if env and env.strip():
        candidates.append(Path(env.strip()).expanduser())
    saved = paths.kit_setting(FORGE_SETTING)
    if saved and str(saved).strip():
        candidates.append(Path(str(saved).strip()).expanduser())
    candidates.append(Path(paths.KIT_DIR).parent / 'forge')
    for root in candidates:
        if (root / 'forge' / 'd2art.py').is_file() or (root / 'd2art.py').is_file():
            return root if (root / 'forge').is_dir() else root.parent
    raise D4SourceError(
        'The Disgaea 4 art reader package (Character Forge `forge/d2art.py`) was not found. Set '
        f'{FORGE_ENV} to the folder holding `forge/` (for example `<project>/Migration/CharacterForge`) or '
        'save the same path as the kit setting `d4_forge`. Those readers are outside-kit code today '
        '(SOURCEPREP1-REPORT.md section 1.5); vendoring them is a follow-up card, not something this '
        'importer may guess a path for.')


def _forge():
    root = forge_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from forge import d2art, d4art, monsterclips   # noqa: E402
    return d2art, d4art, monsterclips


# --------------------------------------------------------------------------- prepared art
def _body(files, number, d4art=None):
    from .. import gamefs
    if d4art is None:
        _d2art, d4art, _m = _forge()
    pack = files.anm_pack()
    return d4art.to_d2_layout(gamefs.decode_member(pack.read('anm%05d.lzs' % int(number))))


def packet_library(files, character_id, body_number, out, name=''):
    """A minimal Character Forge art library a prepared packet's ``read_prepared`` accepts.

    It holds exactly the two bodies the packet pins (the character body and, for a humanoid, the
    shared body 1), read from the verified source.  ``art-manifest.json`` is the same shape the
    retained library has; nothing else is copied.
    """
    out = Path(out)
    (out / 'bodies').mkdir(parents=True, exist_ok=True)
    bodies = {}
    for number in sorted({int(body_number), 1}):
        raw = _body(files, number)
        digest = hashlib.sha256(raw).hexdigest()
        (out / 'bodies' / (digest + '.bin')).write_bytes(raw)
        bodies[str(number)] = dict(bytes=len(raw), sha256=digest)
    doc = {'format': 'character-forge-art/1', 'source': 'd4',
           'characters': [dict(id=int(character_id), body=int(body_number), name=name,
                               source_sprite=int(body_number))],
           'bodies': bodies}
    (out / 'art-manifest.json').write_text(json.dumps(doc, indent=2) + '\n')
    return out


def class_art(files, family, name, root):
    """(prepared packet, library) of one class, rebuilt from the verified source bodies."""
    root = Path(root)
    prepared = class_packet(files, family, name, root / f'prepared-{int(family)}')
    library = packet_library(files, family, family, root / f'library-{int(family)}', name)
    return prepared, library


def unique_art(files, source_id, root, *, v3=False):
    """(prepared packet, library) of one unique, rebuilt from the verified source bodies."""
    root = Path(root)
    sid = int(source_id)
    row = files.data('EN').chars.get(sid) or {}
    sprite = int(row.get('sprite') or sid)
    prepared = unique_packet(files, sid, root / f'prepared-{sid}', v3=v3)
    library = packet_library(files, sid, sprite, root / f'library-{sid}', row.get('name') or '')
    return prepared, library


PACKET_MARKER = '.d5-d4-packet.json'


def _clear_packet(out):
    """Make ``out`` free for a fresh packet.  A folder of ours (it carries the marker listing the files this
    importer wrote) is emptied by removing exactly those files; any other existing path is refused, never
    reused (a stale or planted packet must not stand in for the verified source) and never deleted."""
    out = Path(out)
    if out.is_symlink():
        raise D4SourceError(f'D4 packet folder {out} is a symlink; refusing to use it')
    if not out.exists():
        return
    marker = out / PACKET_MARKER
    if not out.is_dir() or not marker.is_file():
        raise D4SourceError(f'D4 packet folder {out} exists and was not written by this importer; refusing to '
                            'reuse or delete it (move it aside)')
    try:
        listed = json.loads(marker.read_text())['files']
    except (OSError, ValueError, KeyError, TypeError):
        raise D4SourceError(f'D4 packet marker {marker} is unreadable; refusing to delete anything in {out}')
    for rel in listed:
        target = (out / rel)
        if target.is_symlink() or not target.resolve().is_relative_to(out.resolve()):
            continue
        target.unlink(missing_ok=True)
    marker.unlink()
    for folder in sorted((p for p in out.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            folder.rmdir()                       # only folders that are now empty
        except OSError:
            pass
    try:
        out.rmdir()
    except OSError:
        raise D4SourceError(f'D4 packet folder {out} holds files this importer did not write; move them aside')


def _seal_packet(out):
    out = Path(out)
    listed = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file())
    (out / PACKET_MARKER).write_text(json.dumps({'files': listed}, indent=1) + '\n')
    return out


def class_packet(files, family, name, out):
    """The prepared-art packet of one D4 class family, rebuilt from the verified source body."""
    d2art, _d4art, monsterclips = _forge()
    out = Path(out)
    _clear_packet(out)
    data = files.data('EN')
    if int(family) not in data.chars:
        raise D4SourceError(f'D4 source has no character row {family} for the class packet')
    kind = 'monster' if data.chars[int(family)]['body_type'] == 1 else 'humanoid'
    raw = _body(files, int(family))
    if kind == 'monster':
        if not monsterclips.supported(raw, int(family)):
            raise D4SourceError(f'D4 body {family} has no supported monster layout')
        monsterclips.extract(raw, int(family), 0, out, 'd4', name)
    else:
        common = _body(files, 1)
        table = pose_table()
        if hashlib.sha256(common).hexdigest() != table['common_sha256']:
            raise D4SourceError('the D4 shared body does not match the checked-in pose table')
        d2art.extract(raw, common, int(family), 0, table, out, name, 'd4')
    return _seal_packet(out)


def unique_packet(files, source_id, out, *, v3=False):
    """The prepared-art packet of one D4 unique, rebuilt from the verified source body.

    ``v3`` reproduces the October ``prepared-unique-v3`` packets: the manifest names the *source row*
    (not only its body), and a monster's transparent action frames point at the character's real
    front/back standing art.  The cast/Vulcanus/NPC packets were made without that pass.
    """
    d2art, _d4art, monsterclips = _forge()
    out = Path(out)
    _clear_packet(out)
    data = files.data('EN')
    sid = int(source_id)
    row = data.chars.get(sid)
    if row is None:
        raise D4SourceError(f'D4 source has no character row {sid} for the unique packet')
    sprite = int(row['sprite'])
    raw = _body(files, sprite)
    count = d2art.palette_count(raw)
    bank = int(row['color_id']) % 10
    palette = bank if bank < count else 0
    if d2art.has_humanoid_layout(raw, sprite):
        common = _body(files, 1)
        table = pose_table()
        if hashlib.sha256(common).hexdigest() != table['common_sha256']:
            raise D4SourceError('the D4 shared body does not match the checked-in pose table')
        d2art.extract(raw, common, sprite, palette, table, out, row.get('name') or '', 'd4')
    elif monsterclips.supported(raw, sprite):
        monsterclips.extract(raw, sprite, palette, out, 'd4', row.get('name') or '')
    else:
        # The October v2 rule: a sparse monster body keeps the actions it really has and uses its own
        # front/back standing art for the rest (recorded explicitly in the packet manifest).
        decoded, missing, fallback = {}, {}, {}
        tags = {r[0] for r in d2art.tables(raw, sprite)['tags']}
        for tag in monsterclips.ACTIONS:
            if tag in tags:
                try:
                    decoded[tag] = d2art.standing(raw, sprite, palette, (tag,))
                except (ValueError, KeyError, IndexError):
                    pass
        if not {1, 7} <= set(decoded):
            raise D4SourceError(f'D4 body {sprite} (unique {sid}) has no source front/back standing art')
        for tag in monsterclips.ACTIONS:
            if tag in decoded:
                continue
            base = 7 if tag % 10 == 7 else 1
            decoded[tag] = decoded[base]
            fallback[str(tag)] = base
            missing[str(tag)] = (f'Source action unavailable; source standing{base} is an explicit MVP pose '
                                 'placeholder')
        monsterclips.extract(raw, sprite, palette, out, 'd4', row.get('name') or '',
                             decoded_actions=(decoded, missing, fallback))
    manifest = out / 'manifest.json'
    doc = json.loads(manifest.read_text())
    if v3:
        doc.update(character_id=sid, source_sprite=sprite, source_voice_group_base=int(row['body']))
        fallback = []
        if 'actions' in doc:
            from PIL import Image
            actions = {a['tag']: a for a in doc['actions']}
            for action in doc['actions']:
                refs = []
                for frame in action['frames']:
                    with Image.open(out / frame) as image:
                        empty = image.convert('RGBA').getchannel('A').getextrema()[1] == 0
                    if empty:
                        base = 7 if action['tag'] % 10 == 7 else 1
                        replacement = actions[base]['frames'][0]
                        fallback.append(dict(tag=action['tag'], source_empty_frame=frame,
                                             replacement_source_stand=base, replacement_frame=replacement))
                        refs.append(replacement)
                    else:
                        refs.append(frame)
                action['frames'] = refs
            doc['transparent_action_frame_fallbacks'] = fallback
            if fallback:
                doc.setdefault('limitations', []).append(
                    'Transparent source action frames explicitly use actual source front/back standing art; '
                    'motion/pose fidelity remains pending')
    elif int(doc.get('character_id') or 0) != sid:
        doc['character_id'] = sid             # the cast wrapper's one patch
    manifest.write_text(json.dumps(doc, indent=2) + '\n')
    return _seal_packet(out)


# ------------------------------------------------------------------ game text as references
def normalize_source_text(value):
    """The spelling the reviewed rows sometimes use: NFKC, then one space between words."""
    return re.sub(r'  +', ' ', unicodedata.normalize('NFKC', value))


def text_sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class TextPool:
    """Hashes of every game text a build may read from the user's own files.

    The checked-in data carries only a SHA-256 per text field (``{"@text": sha}``), or a template hash
    plus the numbers rendered into it (``{"@template": sha, "args": [..]}``), or a kit-written prefix
    followed by a source string (``{"@prefix": text, "@text": sha}``).  This pool collects the D4 source
    strings and the Disgaea 5 skill/character tables, so a field resolves to exactly the text the
    installed pack carried, read from game files the user supplied -- never from Git.
    """

    def __init__(self, strings=()):
        self._text = {}
        self._templates = {}
        for value in strings:
            self.add(value)

    def add(self, value):
        if not isinstance(value, str) or not value:
            return
        for candidate in (value, normalize_source_text(value)):
            if candidate:
                self._text.setdefault(text_sha(candidate), candidate)
                if '%d' in candidate or '%%' in candidate:      # '%%' alone: TEXTHASH-D4 (a sentence whose percent sign is escaped)
                    self._templates.setdefault(text_sha(candidate), candidate)

    def __len__(self):
        return len(self._text)

    def get(self, digest):
        value = self._text.get(digest)
        if value is None:
            raise D4SourceError(
                f'D4 game text {digest} is not in the prepared D4 source or the Disgaea 5 tables; the '
                'source edition or the checked-in rule data changed. Re-run tools/build_d4_rules.py with '
                'the reviewed dump and check the d4-*.json rule files.')
        return value

    def template(self, digest):
        value = self._templates.get(digest)
        if value is None:
            raise D4SourceError(
                f'D4 game text template {digest} is not in the prepared D4 source or the Disgaea 5 tables; '
                'the source edition or the checked-in rule data changed.')
        return value

    # ---- building references (maintainer tool) -------------------------------------------------
    PERCENTS = ('%', '\uff05')            # D4 renders a template's ``%%`` as either spelling
    MIN_SEGMENT = 10                      # a pool string must be this long to be quoted as a piece

    def _regexes(self):
        """(sha, compiled pattern) of every pool string with a ``%d``: how a rendered sentence finds its template."""
        cached = getattr(self, '_template_regexes', None)
        if cached is None:
            cached = []
            for digest, text in self._templates.items():
                pieces = re.split(r'(%d|%%)', text)
                pattern = ''.join('(-?\\d+)' if p == '%d' else '[%\uff05]' if p == '%%' else re.escape(p)
                                  for p in pieces)
                cached.append((digest, re.compile('^' + pattern + '$')))
            self._template_regexes = cached
        return cached

    def ref(self, value):
        """The reference form of ``value``: exact text, a template plus its numbers, text quoted from pieces
        of the pool, or ``{"@authored": value}`` for a kit-written sentence no game table holds.

        Every form is checked to resolve back to exactly ``value``; the build never has to trust the guess."""
        if not isinstance(value, str) or not value:
            return value
        for guess in (self._exact, self._templated, self._prefixed, self._marked, self._segmented):
            found = guess(value)
            if found is not None and self.resolve(found) == value:
                return found
        return {'@authored': value}

    def _exact(self, value):
        digest = text_sha(value)
        return {'@text': digest} if digest in self._text else None

    def _templated(self, value):
        for digest, pattern in self._regexes():
            match = pattern.match(value)
            if match:
                doc = {'@template': digest, 'args': [int(n) for n in match.groups()]}
                if '%%' in self._templates[digest]:
                    doc['percent'] = next((c for c in self.PERCENTS if c in value), '%')
                return doc
        return None

    @staticmethod
    def _skeleton(text):
        return ''.join(c for c in text if c.isascii())

    def _marked(self, value):
        """A game string whose non-ASCII flag characters (the special-attack converter's markers) differ from the
        source bytes: the ASCII skeleton picks the string, ``marks`` are the flag characters and where they sit."""
        if len(value) < 6 or value.isascii():
            return None
        skeleton = self._skeleton(value)
        index = getattr(self, '_skeletons', None)
        if index is None:
            index = self._skeletons = {}
            for digest, text in self._text.items():
                if not text.isascii():
                    index.setdefault(self._skeleton(text), []).append(digest)
        hits = index.get(skeleton) or []
        if len(hits) != 1:
            return None
        marks = []
        for position, char in enumerate(value):
            if char.isascii():
                continue
            marks.append([len(self._skeleton(value[:position])), char])
        return {'@skeleton': hits[0], 'marks': marks}

    def _prefixed(self, value):
        """A kit-written label followed by exactly one game string (``[Unavailable D4] <name>``)."""
        for cut in range(1, min(len(value), 48)):
            if text_sha(value[cut:]) in self._text and len(value) - cut >= 3:
                return {'@prefix': value[:cut], '@text': text_sha(value[cut:])}
        return None

    @staticmethod
    def _boundary(value, start, end):
        """True when the piece is not cut out of the middle of a word."""
        before = value[start - 1] if start else ' '
        after = value[end] if end < len(value) else ' '
        if value[max(0, start - 2):start] == '%s':
            before = ' '                        # a printf marker in front is not part of the word
        return not (before.isascii() and before.isalnum()) and not (after.isascii() and after.isalnum())

    def _segmented(self, value):
        """``value`` as consecutive pool strings and kit-written pieces; None when no long piece is quoted."""
        if len(value) < self.MIN_SEGMENT:
            return None
        known = getattr(self, '_long', None)
        if known is None:
            known = self._long = {t for t in self._text.values() if len(t) >= self.MIN_SEGMENT}
            self._long_lengths = sorted({len(t) for t in known}, reverse=True)
        pieces, i, hits = [], 0, 0
        while i < len(value):
            for length in self._long_lengths:
                if (length <= len(value) - i and value[i:i + length] in known
                        and self._boundary(value, i, i + length)):
                    pieces.append({'@text': text_sha(value[i:i + length])})
                    hits += 1
                    i += length
                    break
            else:
                if pieces and isinstance(pieces[-1], str):
                    pieces[-1] += value[i]
                else:
                    pieces.append(value[i])
                i += 1
        return {'@segments': pieces} if hits else None

    # ---- resolving references (every build) ----------------------------------------------------
    def resolve(self, value):
        if not isinstance(value, dict):
            return value
        if '@authored' in value:
            return value['@authored']
        if '@skeleton' in value:
            out = self._skeleton(self.get(value['@skeleton']))
            for position, char in sorted(value.get('marks') or [], reverse=True):
                out = out[:position] + char + out[position:]
            return out
        if '@segments' in value:
            return ''.join(self.resolve(piece) if isinstance(piece, dict) else piece
                           for piece in value['@segments'])
        if '@template' in value:
            out = self.template(value['@template'])
            for arg in value.get('args') or []:
                if '%d' not in out:
                    break
                out = out.replace('%d', str(arg), 1)
            out = out.replace('%%', value.get('percent', '%'))
            return out[:-int(value['trim'])] if value.get('trim') else out      # trim: a quote without the final '.'
        if '@text' in value:
            return value.get('@prefix', '') + self.get(value['@text'])
        raise D4SourceError(f'unknown game-text reference {value!r}')

    REF_KEYS = {'@text', '@template', '@args', '@prefix', 'args', 'percent', 'trim', '@segments', '@authored', '@skeleton', 'marks'}
    FORMS = {'@text', '@template', '@segments', '@authored', '@skeleton'}

    def resolve_doc(self, doc, lenient=False):
        """Every reference under ``doc`` resolved.  ``lenient`` (tests that carry a few strings, never a build)
        keeps an unresolved reference as the marker ``<unresolved d4 text 0123456789ab>`` instead of refusing."""
        if isinstance(doc, dict):
            if set(doc) <= self.REF_KEYS and (self.FORMS & set(doc)):
                try:
                    return self.resolve(doc)
                except D4SourceError:
                    if not lenient:
                        raise
                    digest = doc.get('@text') or doc.get('@template') or doc.get('@skeleton') or '?'
                    return f'<unresolved d4 text {str(digest)[:12]}>'
            return {key: self.resolve_doc(value, lenient) for key, value in doc.items()}
        if isinstance(doc, list):
            return [self.resolve_doc(value, lenient) for value in doc]
        return doc


def has_refs(doc):
    """True when ``doc`` holds at least one game-text reference (a resolved document holds none)."""
    if isinstance(doc, dict):
        if set(doc) <= TextPool.REF_KEYS and (TextPool.FORMS & set(doc)):
            return True
        return any(has_refs(v) for v in doc.values())
    if isinstance(doc, list):
        return any(has_refs(v) for v in doc)
    return False


def text_pool_for_tools(game_path=None, state_root=None):
    """The pool for a maintainer tool, a test or a loader called without a build context: the prepared D4 folder plus
    the Disgaea 5 tables.  The D5 tables come from the installed kit's backups of the user's game (or from
    ``game_path``/``state_root`` when given); with no backups it falls back to a clean Disgaea 5 copy
    (``D5_CLEAN_GAME``, the one the skill-motion gate already reads).  Refuses, naming what to supply, when none of
    them is reachable."""
    from .. import gamefs, modsys, skillmotions
    from .dd2 import original_fs
    files = data_dir()
    problems = []
    try:
        game = str(game_path or paths.require_game_dir())
        state = Path(state_root or modsys.game_state_dir(game, modsys.KIT_DIR))
        if (state / 'backups.json').is_file():
            return text_pool(files, original_fs({'game_path': game, 'state_root': state}))
        problems.append(f'no backups.json in {state}')
    except Exception as exc:                                      # noqa: BLE001 - say what is missing
        problems.append(f'the Disgaea 5 install is not reachable ({exc})')
    clean = Path(skillmotions.CLEAN_GAME)
    if clean.is_dir():
        return text_pool(files, gamefs.GameFS(str(clean)))
    raise D4SourceError('; '.join(problems) + f'; no clean Disgaea 5 copy at {clean} either.  D4 game-text '
                        'references need the prepared D4 folder and the Disgaea 5 tables: pass --game-path/--state, '
                        'run from the installed kit, or set D5_CLEAN_GAME')


def text_pool(files, fs=None):
    """The pool of game text this build may resolve: D4 source tables and, when given, D5 tables."""
    data = files.data('EN')
    strings = set()
    for row in data.chars.values():
        strings.update(v for k in ('name', 'title') for v in (row.get(k),) if isinstance(v, str))
        for line in data.help_lines(row.get('help_id') or 0):
            strings.add(line)
    for row in data.evilities.values():
        strings.update(v for v in (row.get('name'), row.get('desc')) if isinstance(v, str))
    for row in data.skills.values():
        strings.update(v for v in (row.get('name'), row.get('desc')) if isinstance(v, str))
    for first_id in range(1010, 2300, 10):       # every class family's personality names (additive, TEXTHASH-D4)
        try:
            for row in data.personality_rows(first_id):
                strings.add(row['name'])
        except (ValueError, KeyError, OSError):
            continue
    if fs is not None:
        from .. import database, newclasses
        for name, path in (('Skill.dat', newclasses.SKILL), ('magic.dat', newclasses.MAGIC),
                           ('char.dat', newclasses.CHAR), ('charhelp.dat', 'Database/Database_0.dat/charhelp.dat')):
            try:
                table = database.load_table(name, fs.read(path))
            except (KeyError, OSError, ValueError):
                continue
            for row in table.rows:
                for key in row.keys():
                    value = row.get(key)
                    if isinstance(value, str):
                        strings.add(value)
    return TextPool(strings)
