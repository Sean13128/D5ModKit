"""Every game input of the Disgaea 1 Complete importer, and where it comes from (SOURCEPREP4-D1C).

The importer reads one game file, ``data/SUBDATA.DAT`` (Switch romfs or PS4 unpack): the character table
(``start.dat`` member 43), the HD sprite/cut-in pack (member 98), the older face set (member 73), the
classic stat table (member 43 again) and the HD faces (``anmdat.fad``).  It comes from the user's prepared
source folder (SOURCEPREP2, ``d5lib/sourcefolder.py``) and only when the prep manifest lists it with
``verified: "yes"``, the file is on disk and its size equals the manifest's.  :class:`D1cData` is the only
way any D1C reader gets that path; nothing in this package opens a folder or a path of its own.

An explicit ``--source-root`` (a romfs folder holding ``data/SUBDATA.DAT``) stays as an unverified
diagnostic route and is never the default.

This module also carries what used to live in ``Research/source-packs/d1c/d1c_source.py`` (the reader of
that file; it contains no game data).  Ids, rules and counts that used to be read from the installed packs
are the checked-in ``d1c-*.json`` files next to this module (ids/counts and SHA-256 text references only).
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import struct
import tempfile
import unicodedata
from pathlib import Path

from .. import sourcefolder

GAME = 'd1c'
REL = 'data/SUBDATA.DAT'
PACK_MEMBER, TABLE_MEMBER, FACE_MEMBER = 98, 43, 73
FACE_SIZE = 256
FORMAT = 'character-forge-d1complete-local/1'
# A label for the provenance records the build writes; the file itself is the prepared one.
LABEL = 'd1c/data/SUBDATA.DAT'
PROVENANCE = dict(kind='original-game-data', source=LABEL,
                  member=f'start.dat[{PACK_MEMBER}] (ANM pack), start.dat[{TABLE_MEMBER}] (characters)')
# Classic HD stat table: start.dat member 43 is the 81,328-byte char_e.dat slice (statfidelity.D1C_SLICE).
HD_TABLE_SHA256 = '8c6a76467fc1c9edd9b231bf9a2ebc216dcfe197ecebf613cb673bef353d59a1'
HD_TABLE_SIZE = 81328
HERE = Path(__file__).resolve().parent


class D1cSourceError(RuntimeError):
    """The D1C input is missing, unverified or ambiguous; the message says which and how to supply it."""


_VERIFIED = {}      # (path, size, mtime_ns, inode) -> SHA-256 already proven equal to the manifest row


def verify_file(path, sha256, label):
    """Prove ``path`` still holds the bytes the verified manifest row attests (SHA-256), once per file state.

    The proof is keyed on the file's stat signature, so an unchanged file is hashed once per process and a
    replaced or edited file is hashed again and refused when it no longer matches the manifest."""
    if not sha256:
        raise D1cSourceError(f'{label}: the manifest row carries no SHA-256, so the file cannot be trusted '
                             '(re-run tools/prep_source.py)')
    st = os.stat(path)
    key = (str(path), st.st_size, st.st_mtime_ns, st.st_ino)
    if _VERIFIED.get(key) == sha256:
        return
    got = sourcefolder.sha256_file(path)
    if got != sha256:
        raise D1cSourceError(f'{label}: the bytes on disk (SHA-256 {got[:16]}...) no longer match the verified '
                             f'manifest row ({sha256[:16]}...); re-run tools/prep_source.py')
    _VERIFIED[key] = sha256


class D1cData:
    """The verified Disgaea 1 Complete input set: one SUBDATA.DAT path (and its recorded SHA-256 when prepared)."""

    def __init__(self, subdata, *, sha256=None, size=None, prepared=False):
        self.subdata = Path(subdata)
        self.sha256 = sha256
        self.size = size
        self.prepared = bool(prepared)

    def check(self):
        """Re-prove a prepared file against its manifest SHA-256 (no-op for an explicit diagnostic root)."""
        if self.prepared:
            verify_file(self.subdata, self.sha256, f'd1c/{REL}')

    def path(self, rel=REL):
        if rel != REL:
            raise D1cSourceError(f'D1C source file {rel} is not in the verified set (only {REL})')
        return self.subdata

    def to_config(self):
        return dict(subdata=str(self.subdata), sha256=self.sha256, size=self.size, prepared=self.prepared)

    @classmethod
    def from_config(cls, doc):
        return cls(doc['subdata'], sha256=doc.get('sha256'), size=doc.get('size'), prepared=bool(doc.get('prepared')))


def data(explicit=None):
    """The verified D1C input: the prepared source folder, or an explicit romfs root for a diagnostic run."""
    if explicit:
        root = Path(explicit)
        path = root if root.is_file() else root / REL
        if not path.is_file():
            raise D1cSourceError(f'No {REL} under the explicit D1C source root {root}')
        return D1cData(path, prepared=False)
    return _prepared()


def _prepared():
    folder = sourcefolder.source_dir()
    manifest = folder / 'manifest.json'
    hint = ('Run `python tools/prep_source.py --d1c <folder holding data/SUBDATA.DAT>` '
            '(or point D5_SOURCE_DIR at a prepared folder).')
    if not manifest.is_file():
        raise D1cSourceError(f'No prepared D1C source: {manifest} is missing. {hint}')
    try:
        doc = sourcefolder.read_manifest(folder)
    except (OSError, ValueError) as exc:
        raise D1cSourceError(f'Prepared source manifest {manifest} is unreadable: {exc}') from exc
    entry = (doc.get('games') or {}).get(GAME) or {}
    rows = {row.get('path'): row for row in entry.get('files', [])}
    if not rows or entry.get('supplied') is False:
        raise D1cSourceError(f'The prepared source folder {folder} has no Disgaea 1 Complete files. {hint}')
    row = rows.get(REL)
    if row is None:
        raise D1cSourceError(f'd1c/{REL}: no manifest row ({hint})')
    if row.get('verified') != 'yes':
        raise D1cSourceError(f"d1c/{REL}: manifest says verified {row.get('verified')!r} "
                             '(size/SHA-256 do not match a known Disgaea 1 Complete dump)')
    path = folder / GAME / REL
    if not path.is_file():
        raise D1cSourceError(f'd1c/{REL}: listed as verified but the file is missing from {folder / GAME}')
    if row.get('size') is not None and path.stat().st_size != int(row['size']):
        raise D1cSourceError(f'd1c/{REL}: size {path.stat().st_size} differs from the manifest ({row["size"]}); '
                             're-run tools/prep_source.py --d1c ...')
    found = D1cData(path, sha256=row.get('sha256'), size=row.get('size'), prepared=True)
    found.check()
    return found


# ------------------------------------------------------------------------------------------- active input
_ACTIVE: D1cData | None = None


def use(d1c):
    """Make ``d1c`` (a :class:`D1cData`) the input every reader below uses; clears the per-input caches."""
    global _ACTIVE
    if _ACTIVE is None or _ACTIVE.subdata != d1c.subdata:
        for fn in (start_dat, pack, characters, _face_spans, face_ids, fad_member, text_pool):
            fn.cache_clear()
        import sys
        for mod, name in (('d5lib.importers.d1c_hdfaces', 'index'), ('d5lib.importers.d1c_art', '_cutin_ids')):
            fn = getattr(sys.modules.get(mod), name, None)
            if fn is not None:
                fn.cache_clear()
    _ACTIVE = d1c


def active():
    return _ACTIVE if _ACTIVE is not None else _use_default()


def _use_default():
    use(data())
    return _ACTIVE


def subdata_path():
    return active().subdata


def sha256_of_source():
    """SHA-256 of SUBDATA.DAT: the verified manifest value (the file was hashed by prep), else computed once."""
    d = active()
    if d.sha256:
        return d.sha256
    if getattr(d, '_computed', None) is None:
        h = hashlib.sha256()
        with open(d.subdata, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        d._computed = h.hexdigest()
    return d._computed


# ------------------------------------------------------------------------------------------- the archive
def archive_member(name, limit=None):
    """One named file of the PS_FS_V1 archive SUBDATA.DAT (magic(8) count(u64), 64-byte entries)."""
    active().check()                      # changed bytes under a verified row are refused, not read
    with open(subdata_path(), 'rb') as f:
        head = f.read(16)
        magic, count = struct.unpack('<8sQ', head) if len(head) == 16 else (b'', 0)
        if magic != b'PS_FS_V1' or not 0 < count <= 100000:
            raise ValueError('SUBDATA.DAT is not a PS_FS_V1 archive')
        for _ in range(count):
            e = f.read(64)
            if e[:48].split(b'\0', 1)[0].decode('latin1') == name:
                size, off = struct.unpack('<QQ', e[48:])
                if limit and size > limit:
                    raise ValueError(f'{name} is larger than expected')
                f.seek(off)
                return f.read(size)
    raise FileNotFoundError(f'SUBDATA.DAT has no {name}')


@functools.lru_cache(maxsize=1)
def start_dat():
    return archive_member('start.dat')


@functools.lru_cache(maxsize=1)
def fad_member():
    return archive_member('anmdat.fad', limit=64 * 1024 * 1024)


def member(idx):
    s = start_dat()
    n = struct.unpack_from('<I', s)[0]
    offs = struct.unpack_from('<%dI' % (n + 1), s, 4)
    return s[offs[idx]:offs[idx + 1]]


@functools.lru_cache(maxsize=1)
def pack():
    from d5lib import anm
    return anm.parse(member(PACK_MEMBER))


def hd_body(sprite):
    # The five story leads' sprites 1..5 are drawn as HD blocks 10..50; blocks 3..5 do not exist.
    return sprite * 10 if sprite < 10 else sprite


def _text(raw):
    return unicodedata.normalize('NFKC', raw.split(b'\0', 1)[0].decode('shift_jis', 'replace')).strip()


@functools.lru_cache(maxsize=1)
def characters():
    """Every character-table row, in table order, in the d1cart manifest's row shape."""
    t = member(TABLE_MEMBER)
    count = struct.unpack_from('<I', t)[0]
    rows = []
    for i in range(count):
        r = t[8 + i * 224:8 + (i + 1) * 224]
        cid, sprite = struct.unpack_from('<HH', r, 0x5e)
        rows.append(dict(id=cid, body=hd_body(sprite), legacy_body=sprite, palette=r[0x49],
                         name=_text(r[:0x21]), title=_text(r[0x21:0x42])))
    return rows


def character(cid):
    return next((c for c in characters() if int(c['id']) == int(cid)), None)


@functools.lru_cache(maxsize=1)
def text_pool():
    """Every D1C character name/title and skill name/description, for ``@text`` references.

    TEXTHASH-D1C-DD2: the checked-in D1C data files store SHA-256 references, not the strings.  This
    pool is what the build resolves them against: the character table (start.dat[43]) and the d1hd
    skill table (start.dat[40]) of the verified prepared SUBDATA.DAT, each also in its product-text
    ASCII fold (Disgaea 1 writes U+2212 for "Astro-One").  Add the Disgaea 5 tables with
    ``textrefs.d5_text_pool`` where a file names D5 rows."""
    from .. import d1skill
    from ..nativeimports import ascii_latin
    from ..textrefs import TextPool

    pool = TextPool(label='the prepared Disgaea 1 Complete source', folds=(ascii_latin,))
    for row in characters():
        pool.add(row['name'])
        pool.add(row['title'])
    for row in d1skill.read_table(member(40), 'd1hd')['rows']:
        pool.add(row['name'])
        pool.add(row['description'])
    return pool


def body_bytes(body):
    """One pack block as a standalone one-block ANM (what d1cart reads as a body file)."""
    from d5lib import anm
    a = pack()
    b = next(x for x in a.blocks if x.id == int(body))
    tex = a.textures[b.tex_base:b.tex_base + len(b.texture_infos)]
    pal = a.palettes[b.pal_base:b.pal_base + len(b.palette_infos)]
    base = (b.tex_base, b.pal_base)
    b.tex_base = b.pal_base = 0
    try:
        return anm.AnmFile([b], tex, pal).to_bytes()
    finally:
        b.tex_base, b.pal_base = base


VIEW_MARKER = '.d5-d1c-source-view'
_BODY_NAME = re.compile(r'^bodies/anm\d{5}\.dat$')


def view_dir():
    return Path(os.environ.get('D5_D1C_SOURCE_VIEW') or (Path(tempfile.gettempdir()) / 'd5kit-d1c-source-view'))


def _claim_view(view):
    """Make ``view`` a cache directory this module owns, or refuse.  Only a missing or empty directory, or one
    carrying our marker, qualifies; anything else (a user's folder, a symlink) is never written into."""
    if view.is_symlink():
        raise D1cSourceError(f'D1C source view {view} is a symlink; refusing to use it as a cache '
                             '(set D5_D1C_SOURCE_VIEW to an empty folder)')
    if view.exists():
        if not view.is_dir():
            raise D1cSourceError(f'D1C source view {view} is not a folder (set D5_D1C_SOURCE_VIEW)')
        if not (view / VIEW_MARKER).is_file() and any(view.iterdir()):
            raise D1cSourceError(f'D1C source view {view} is not empty and is not a D1C cache folder; refusing to '
                                 'write into or delete from it (set D5_D1C_SOURCE_VIEW to an empty folder)')
    view.mkdir(parents=True, exist_ok=True)
    (view / VIEW_MARKER).write_text('d5 D1C source view cache; safe to delete\n')


def _owned_names(view):
    """File names the previous build recorded in this cache's manifest (nothing else in it is ours to remove)."""
    try:
        old = json.loads((view / 'manifest.json').read_text())
        return {v['file'] for v in old.get('bodies', {}).values() if _BODY_NAME.match(str(v.get('file')))}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return set()


def art_root():
    """A d1cart root (manifest.json + bodies/) built from the source into an owned cache folder; returns its path."""
    view = view_dir()
    blocks = {b.id: b for b in pack().blocks}
    rows = [c for c in characters() if c['body'] in blocks]
    bodies, files = {}, {}
    for body in sorted({b for c in rows for b in (c['body'], c['legacy_body']) if b in blocks}):
        raw = body_bytes(body)
        name = f'bodies/anm{body:05d}.dat'
        files[name] = raw
        bodies[str(body)] = dict(file=name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                                 palettes=len(blocks[body].palette_infos),
                                 tags=sorted({a.id for a in blocks[body].animations}))
    manifest = (json.dumps(dict(format=FORMAT, source=PROVENANCE, characters=rows, bodies=bodies),
                           indent=1) + '\n').encode()
    _claim_view(view)
    current = view / 'manifest.json'
    if current.is_file() and current.read_bytes() == manifest:
        return view                                # d1cart re-checks every body's SHA-256 on read
    stale = _owned_names(view) - set(files)
    (view / 'bodies').mkdir(exist_ok=True)
    for name, raw in files.items():                # each file replaced atomically; the manifest goes last
        tmp = view / (name + f'.tmp{os.getpid()}')
        tmp.write_bytes(raw)
        os.replace(tmp, view / name)
    tmp = view / f'manifest.json.tmp{os.getpid()}'
    tmp.write_bytes(manifest)
    os.replace(tmp, current)
    for name in stale:                             # only files the previous manifest of this cache listed
        (view / name).unlink(missing_ok=True)
    return view


# ------------------------------------------------------------------------------------------- member 73 faces
@functools.lru_cache(maxsize=1)
def _face_spans():
    m = member(FACE_MEMBER)
    n = struct.unpack_from('<I', m)[0]
    offs = list(struct.unpack_from('<%dI' % n, m, 4)) + [len(m)]
    return m, offs


@functools.lru_cache(maxsize=1)
def face_ids():
    """{sprite id: face index} from the identity table after the offsets (D1CFACE1)."""
    m, offs = _face_spans()
    n = len(offs) - 1
    ids = struct.unpack_from('<%dH' % n, m, 4 + n * 4)
    return {sid: i for i, sid in enumerate(ids) if sid and offs[i + 1] > offs[i]}


def face_by_sprite(sprite_id):
    i = face_ids().get(int(sprite_id))
    return (i, face(i)) if i is not None else (None, None)


def face_count():
    return len(_face_spans()[1]) - 1


def face(index):
    """Source face ``index`` of member 73 as a 256x256 RGBA PIL image, or None (empty span / 64x64 icon entry)."""
    from PIL import Image
    m, offs = _face_spans()
    e = m[offs[index]:offs[index + 1]]
    if not e:
        return None
    w, h, kind = struct.unpack_from('<3H', e)
    if (w, h, kind) == (64, 64, 16):
        return None
    if (w, h, kind) != (FACE_SIZE, FACE_SIZE, 3) or len(e) < 16 + w * h * 4:
        raise ValueError(f'face {index}: unexpected header {(w, h, kind)} / length {len(e)}')
    return Image.frombytes('RGBA', (w, h), e[16:16 + w * h * 4], 'raw', 'RGBA')


# ------------------------------------------------------------------------------------------- stat table
def hd_table():
    """The classic HD character table (the 81,328-byte char_e.dat slice, start.dat member 43), checked against its pin."""
    raw = member(TABLE_MEMBER)
    if len(raw) != HD_TABLE_SIZE or hashlib.sha256(raw).hexdigest() != HD_TABLE_SHA256:
        raise D1cSourceError('D1C character table (start.dat member 43) failed its pinned SHA-256; the source is '
                             'not the Disgaea 1 Complete build the stats were checked against')
    return raw


# ------------------------------------------------------------------------------------------- recorded rules
@functools.lru_cache(maxsize=None)
def rules(name):
    """A checked-in ids/counts file beside this module (``d1c-<name>.json``)."""
    return json.loads((HERE / f'd1c-{name}.json').read_text(encoding='utf-8'))


# ------------------------------------------------------------------------------------------- optional D1 PC voices
VOICE_FILES = ('Disgaea PC/DATA.DAT', 'Disgaea PC/SUBDATA.DAT')


class D1cVoiceSource:
    """The two verified Disgaea 1 PC archives (voice banks and the sound-effect bank), by exact path + SHA-256.

    ``files()`` re-proves both against their manifest rows and returns ``(DATA.DAT, SUBDATA.DAT)``; the voice
    reader opens exactly those paths and never searches a folder."""

    def __init__(self, data, subdata, data_sha256, subdata_sha256):
        self.data, self.subdata = Path(data), Path(subdata)
        self.data_sha256, self.subdata_sha256 = data_sha256, subdata_sha256

    def files(self):
        verify_file(self.data, self.data_sha256, 'd1pc/' + VOICE_FILES[0])
        verify_file(self.subdata, self.subdata_sha256, 'd1pc/' + VOICE_FILES[1])
        return self.data, self.subdata

    def __str__(self):
        return str(self.data.parent)


def voice_source():
    """The verified Disgaea 1 PC voice archives (optional) when the manifest lists both as verified, else None.

    Only the opt-in ``--source-voices`` pass reads them; an unverified, missing or changed file is not offered."""
    folder = sourcefolder.source_dir()
    try:
        doc = sourcefolder.read_manifest(folder)
    except (OSError, ValueError):
        return None
    entry = (doc.get('games') or {}).get('d1pc') or {}
    rows = {row.get('path'): row for row in entry.get('files', [])}
    found = []
    for rel in VOICE_FILES:
        row = rows.get(rel)
        path = folder / 'd1pc' / rel
        if row is None or row.get('verified') != 'yes' or not row.get('sha256') or not path.is_file():
            return None
        if row.get('size') is not None and path.stat().st_size != int(row['size']):
            return None
        found.append((path, row['sha256']))
    src = D1cVoiceSource(found[0][0], found[1][0], found[0][1], found[1][1])
    try:
        src.files()
    except D1cSourceError:
        return None
    return src
