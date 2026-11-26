"""Bounded local prepared-art bridge to native D5ModKit writers.

No Forge module, installer or settings writer is used here. Offline builders
require caller-configured private per-output caches; shared caches are refused.
The retained-art JSON contract was reviewed locally (spritepack.py/d2art.py);
this is a new implementation, not a port of the historical backend.
Game assets must remain outside the source repository.
"""
from __future__ import annotations

from .importcore import D4_YIELD_NOTE, donor_yield

import hashlib
import json
import os
from pathlib import Path
import re

MAX_JSON = 16 * 1024 * 1024
# D4 face and cut-in pictures are drawn on a plain white background.  Background removal is OFF by default
# (owner decision 2026-10-25): the automatic matte left outlines semi-transparent and corrupted the imported
# faces/cut-ins, so pictures keep their white background until a reviewed removal step exists.
# D4_MATTE_OPTIONS keeps the earlier settings (2026-10-18) for an explicit opt-in: environment D5MODKIT_D4_MATTE=1.
D4_MATTE_OPTIONS = dict(bottom=False, feather=4, soft_from=0.0, min_alpha=0.0)
D4_MATTE = dict(D4_MATTE_OPTIONS) if os.environ.get('D5MODKIT_D4_MATTE') == '1' else None
FACE_MATTE = D4_MATTE


def d4_screen_picture(image, matte=None):
    """A D4 face/cut-in picture as RGBA.  matte None (default): unchanged, white background kept;
    otherwise options for imgtools.remove_white_background, honoured only under the D5MODKIT_D4_MATTE=1
    opt-in (imgtools.screen_picture is the single switch every source importer goes through)."""
    from .imgtools import screen_picture
    return screen_picture(image, matte)
MAX_BODY = 128 * 1024 * 1024


def read_d4_ranks(archive, *, source_ids, edition):
    """Bounded independently written stdlib NSAC v2 / D4 PC EN row reader.

    Header/index/name-directory layout is cross-checked against both observed
    archive directories. Row evidence: j9-modern-evidence.md:11-26 and
    CLASS-DELTA.md:322. RES/SPD order is empirical, not runtime-consumer proof.
    No private reader import, extraction, source discovery or donor rank fill.
    """
    import struct
    if not isinstance(edition, str) or not edition.strip():
        raise ValueError('Explicit D4 source edition required')
    if not isinstance(source_ids, (list, tuple)) or len(source_ids) != 6 or any(
            type(i) is not int or i < 0 for i in source_ids) or len(set(source_ids)) != 6:
        raise ValueError('Exactly six distinct source rank IDs required; no donor padding')
    archive = Path(archive)
    length = archive.stat().st_size
    with archive.open('rb') as f:
        header = f.read(28)
        if len(header) != 28:
            raise ValueError('Truncated NSAC header')
        magic, version, count, declared, data_at, index_size, names_size, reserved = struct.unpack('<4sHH5I', header)
        if (magic != b'NSAC' or version != 2 or not 0 < count <= 4096 or
                declared != length or index_size != count * 10 or
                not 0 < names_size <= 1024 * 1024 or
                data_at != 28 + index_size + names_size or data_at > length):
            raise ValueError('Unsupported or malformed bounded NSAC v2 directory')
        index, names = f.read(index_size), f.read(names_size)
        if len(index) != index_size or len(names) != names_size:
            raise ValueError('Truncated NSAC directories')
        entries, pos = {}, 0
        for i in range(count):
            if pos + 10 > len(names):
                raise ValueError('Truncated NSAC named entry')
            name_size, offset, size = struct.unpack_from('<HII', names, pos)
            pos += 10
            if not 1 <= name_size <= 255 or pos + name_size + 1 > len(names):
                raise ValueError('NSAC name outside bounded directory')
            # Stored length excludes the trailing NUL (verified in both real
            # directories; e.g. AnimeInfo.dat length13, char.dat length8).
            encoded = names[pos:pos + name_size + 1]
            pos += name_size + 1
            if encoded[-1:] != b'\0' or b'\0' in encoded[:-1]:
                raise ValueError('Invalid NSAC name terminator')
            try:
                name = encoded[:-1].decode('ascii')
            except UnicodeDecodeError as exc:
                raise ValueError('Non-ASCII NSAC member') from exc
            if struct.unpack_from('<HII', index, i * 10) != (i, offset, size):
                raise ValueError('NSAC directory mirrors disagree')
            if name in entries or offset < data_at or offset + size > length:
                raise ValueError('Duplicate or out-of-bounds NSAC member')
            entries[name] = (offset, size)
        if pos != len(names) or 'char.dat' not in entries:
            raise ValueError('Incomplete NSAC names or missing char.dat')
        offset, size = entries['char.dat']
        if not 4 <= size <= 4 + 20000 * 684:
            raise ValueError('char.dat outside table size bound')
        f.seek(offset)
        raw = f.read(size)
    if len(raw) != size:
        raise ValueError('Truncated D4 char.dat')
    count_rows = struct.unpack_from('<I', raw)[0]
    if not 0 < count_rows <= 20000 or 4 + count_rows * 684 != len(raw):
        raise ValueError('D4 char.dat count/stride mismatch')
    selected, order = {}, (0, 1, 2, 3, 4, 7, 6, 5)
    for index_row in range(count_rows):
        row_offset = 4 + 684 * index_row
        row = raw[row_offset:row_offset + 684]
        cid = struct.unpack_from('<H', row, 0x194)[0]
        if cid not in source_ids:
            continue
        if cid in selected:
            raise ValueError('Ambiguous duplicate selected source rank')
        base = struct.unpack_from('<8H', row, 4)
        aptitude = row[0x27E:0x286]
        def text(at):
            return row[at:at + 64].split(b'\0', 1)[0].decode('utf-8', 'strict').strip()
        selected[cid] = dict(id=cid, name=text(0x1FE), title=text(0x23E),
                            body=struct.unpack_from('<H', row, 0x1BA)[0],
                            base=[base[k] for k in order], aptitudes=[aptitude[k] for k in order], growth=None,
                            evidence=dict(path=str(archive.resolve()), edition=edition, member='char.dat',
                                          archive_header_sha256=_hash(header + index + names),
                                          member_offset=offset, member_size=size, table_sha256=_hash(raw),
                                          row_sha256=_hash(row), row=index_row, row_offset=row_offset,
                                          row_stride=684, base_offset=4, aptitude_offset=0x27E,
                                          native_to_canonical=list(order),
                                          layout_evidence='j9-modern-evidence.md:11-26; CLASS-DELTA.md:322',
                                          certainty='source-table; order empirical, not consumer-proven'))
    if set(selected) != set(source_ids):
        raise ValueError('Missing genuine D4 source rank; no donor fill')
    return [selected[cid] for cid in source_ids]


def _read(path, limit):
    path = Path(path)
    if not 0 < path.stat().st_size <= limit:
        raise ValueError(f"Input outside size bound: {path}")
    with path.open('rb') as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Input exceeds size bound: {path}")
    return data


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _member(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Source path escapes selected art directory')
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Source symlink escapes selected art directory')
    return path


def read_prepared(art_root, library_root, *, edition, source_game='d4'):
    """Read ONLY the selected manifest, two pinned bodies and listed PNGs.

    Returns PIL sequences for ownanim.build and a serializable read receipt.
    Edition is supplied explicitly: a folder label is not source authentication.
    Original game archives are not required by this prepared-art adapter.
    """
    from PIL import Image
    from .frameconvert import ANIM_NAMES, HAND_NAMES
    import io

    if not isinstance(edition, str) or not edition.strip():
        raise ValueError('An explicit source edition is required')
    art_root, library_root = Path(art_root), Path(library_root)
    raw = _read(art_root / 'manifest.json', MAX_JSON)
    lib_raw = _read(library_root / 'art-manifest.json', MAX_JSON)
    prepared, library = json.loads(raw), json.loads(lib_raw)
    if library.get('format') != 'character-forge-art/1':
        raise ValueError('Unsupported retained-art format')
    if source_game not in ('d4', 'dd2', 'd1c'):
        raise ValueError('Unsupported prepared-art source: d4, dd2 and d1c only')
    if prepared.get('source') != source_game or library.get('source') != source_game:
        raise ValueError('Prepared-art and retained library source mismatch')
    cid = prepared['character_id']
    row = next((r for r in library['characters'] if r['id'] == cid), None)
    if row is None:
        raise ValueError('Source identity absent from retained library')
    bodies = []
    # D1 Complete HD bodies carry their own complete animation set and have no shared "common"
    # body, so only the character body is pinned and checked.
    monster = prepared.get('format') == 'character-forge-monster-clips/2'
    single = monster or source_game == 'd1c'
    for number, field in ([(row['body'], 'body_sha256')] if single else
                          [(row['body'], 'body_sha256'), (1, 'common_sha256')]):
        info = library['bodies'][str(number)]
        digest = info['sha256']
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid retained-body digest')
        if prepared.get(field) != digest:
            raise ValueError('Prepared art belongs to a different source body/common set')
        path = _member(library_root, 'bodies/' + digest + '.bin')
        body = _read(path, MAX_BODY)
        if len(body) != info['bytes'] or _hash(body) != digest:
            raise ValueError('Retained source body failed integrity check')
        bodies.append(dict(number=number, path=str(path), bytes=len(body), sha256=digest))
    sequences, images = {}, []
    bundles = prepared['bundles']
    if monster:
        # Existing monster preparation retains complete authored actions. The
        # Kit's standard roles choose a bounded subset for donor timing; every
        # unselected action and source fallback stays in the read receipt.
        roles = {1: 'stand', 1001: 'wait', 11: 'walk', 1061: 'damage',
                 2071: 'attack_fist', 1121: 'squat', 1091: 'two_arm_up_jump', 4001: 'one_arm_up'}
        actions = {a['tag']: a for a in prepared['actions']}
        bundles = []
        for tag, pose in roles.items():
            for delta, view in ((0, 'front'), (6, 'back')):
                action = actions.get(tag + delta)
                if action is None:
                    continue
                sprites = []
                for n, relative in enumerate(action['frames']):
                    with Image.open(_member(art_root, relative)) as im:
                        size = list(im.size)
                    sprites.append(dict(name=pose + f'{n:04d}', png=relative, decoded_size=size))
                bundles.append(dict(label=view, sprites=sprites))
    for bundle in bundles:
        label = bundle['label']
        view = label.removeprefix('wait_')
        if view not in ('front', 'back'):
            raise ValueError('Unsupported source view: ' + label)
        for sprite in sorted(bundle['sprites'], key=lambda s: s['name']):
            name = re.sub(r'\d+$', '', sprite['name'])
            if name not in ANIM_NAMES + HAND_NAMES:
                raise ValueError('Unsupported source pose: ' + name)
            path = _member(art_root, sprite['png'])
            data = _read(path, MAX_JSON)
            with Image.open(io.BytesIO(data)) as image:
                if list(image.size) != sprite['decoded_size'] or max(image.size) > 4096:
                    raise ValueError('Source PNG dimensions do not match manifest')
                rgba = image.convert('RGBA')
            if rgba.getchannel('A').getextrema()[1] == 0:
                raise ValueError('Empty source pose')
            canvas = sprite.get('canvas')
            if canvas is not None:
                if (not isinstance(canvas, list) or len(canvas) != 4 or
                        any(type(v) is not int or v < 0 for v in canvas) or
                        canvas[0] == 0 or canvas[1] == 0 or
                        canvas[0] + canvas[2] > rgba.height or canvas[1] + canvas[3] > rgba.width):
                    raise ValueError('Invalid source canvas')
                rgba = (rgba, tuple(canvas))
            sequences.setdefault((name, view), []).append(rgba)
            images.append(dict(path=str(path), bytes=len(data), sha256=_hash(data),
                               pose=name, view=view, size=list(image.size)))
            if len(images) > 1024:
                raise ValueError('Selected appearance exceeds bounded image count')
    if not images:
        raise ValueError('No source poses')
    return dict(identity=dict(source=source_game, edition=edition, character_id=cid,
                              body=row['body'], name=row['name'], palette=prepared['palette'],
                              body_sha256=prepared['body_sha256']),
                sequences=sequences,
                evidence=dict(prepared_manifest_sha256=_hash(raw), library_manifest_sha256=_hash(lib_raw),
                              bodies=bodies, images=images,
                              limitations=prepared.get('limitations', []),
                              poses_missing=prepared.get('poses_missing', {}),
                              source_action_fallbacks=(prepared.get('fallback_source_actions', {}) if source_game == 'dd2'
                                                       else prepared.get('fallbacks', {})),
                              source_missing_actions=(prepared.get('missing', prepared.get('poses_missing', {}))
                                                      if source_game == 'dd2' else prepared.get('missing', {})),
                              **({'source_receipt': prepared.get('source_receipt', {})} if source_game == 'dd2' else {}),
                              **({'source_read': prepared.get('source_read', {})} if source_game == 'd1c' else {})))


def _same_padding(value, match):
    """`value` written at the same width as `match` (`swf0070` stays four digits: id 71 -> `0071`, not `71`)."""
    return f"{int(value):0{len(match.group(0))}d}"


def _own_folder_variant(parts, family, pid, pat):
    """The same picture of id `pid` under that id's own `character_id_<id>` folder (D4FACETOOL1 extractor layout).

    `(…)/character_id_00070/face/swf0070.png` with pid 71 -> `(…)/character_id_00071/face/swf0071.png`;
    a cut-in (`…/character_id_00070/cutin/ANM_HI__anm10070/native_frames/p000….png`, first id 10070) keeps the
    folder id 70 and moves the `anm10070` part.  None when the path carries no such id below `character_id_*`."""
    parts = list(parts)
    parts[family] = "character_id_%05d" % (pid - 10000 if pid >= 10000 else pid)
    for i in range(family, len(parts)):
        if pat.search(parts[i]):
            parts[i] = pat.sub(lambda m: _same_padding(pid, m), parts[i])
            return Path(*parts)
    return None


def colour_variants(path, first_id, colours=10):
    """the per-colour siblings of an extracted D4 picture: the path with `first_id` (as a whole number, e.g. swf1080,
    anm11080) replaced by first_id + k, k = 0 .. colours - 1 -> list of paths, or None if any is missing.

    Two layouts are read (D4FACEWIRE1): all variants in one `character_id_<first_id>` folder (the October Forge
    extraction), or each id under its own folder (the D4FACETOOL1 extractor's output).  The same-folder path wins
    when both exist.  Zero padding is part of the name (`swf0070.png`), so the pattern accepts a padded id and the
    replacement keeps the width (R4: `swf0070.png` did not resolve before)."""
    path = Path(path)
    text = str(path)
    pat = re.compile(rf"(?<!\d)0*{int(first_id)}(?!\d)")
    matches = list(pat.finditer(text))
    if not matches:
        return None
    family = next((i for i, p in enumerate(path.parts) if re.fullmatch(r"character_id_\d+", p)), None)
    last = matches[-1]                         # the file/member name, not the character folder
    out = []
    for k in range(int(colours)):
        pid = int(first_id) + k
        same = text[:last.start()] + _same_padding(pid, last) + text[last.end():]
        cand = Path(same)
        if not cand.is_file() and family is not None:
            cand = _own_folder_variant(path.parts, family, pid, pat)
        if cand is None or not cand.is_file():
            return None
        out.append(str(cand))                  # callers pass these straight to open(); keep the old string shape
    return out


def class_face_files(face_path, body, from_source, rule=True, colours=10):
    """The face picture of each colour slot of a D4 class (slot k = rank row k): D4FACE1 / D4-FACE-02.

    The game draws the class face (swf<body>) for every rank row of a class (the colour id rounded down to tens), so
    with `rule` (default) all `colours` slots get the one class face.  Old path (`rule` False): a face per colour
    swf<body + k> when all of them exist (ranks 1..5 then show the rank colour's face the game never draws), else the
    one face for slot 0 only (the slots without a file then fall back to it inside the kit, but a compare that reads
    the files sees no rank face).  Without a D4 source (`from_source` False) there is only the one face."""
    if not from_source:
        return [face_path]
    if rule:
        return [face_path] * int(colours)
    return colour_variants(face_path, body, colours) or [face_path]


def map_source_palettes(anmfile, source_palettes, *, approximate=False, exact_banks=False, report=None, base_bank=0):
    """Recolour an indexed sprite built from colour-0 source art with the source's own palettes: every palette entry
    whose colour is source palette 0 entry j becomes source palette k entry j in palette k (alpha kept).
    -> (exact entries, non-exact entries). By default non-source colours are
    unchanged and ambiguous source colours raise. Explicit approximate=True
    chooses the nearest source RGB / first ambiguous source index; the second
    count discloses both approximations for the caller's gaps receipt.

    Ambiguity is only a problem for a colour the sprite actually uses: two source palette-0 entries
    can share one RGB and diverge in a later bank, but if no pixel carries that colour the mapping is
    still exact (2026-10-30 DD2NAMED — the old check raised from the palettes alone).

    exact_banks=True keeps the result exact without approximations by shipping only the source banks
    where every used colour still has exactly one index; a bank whose duplicates diverge is dropped
    and its receiver palette is filled from bank 0, so the class shows its true default colours in
    every slot instead of a guessed alternate. `report` (a dict) receives the measurement.

    base_bank names the source bank the art's own colours come from (default 0).  A DD2 unique whose row selects
    palette 5 is extracted in bank-5 colours; looking those colours up in bank 0 left them unmatched and every
    receiver slot became bank 0 (DD2FIELDS1).  Entry indices are shared by all banks, so the lookup bank only
    decides which colour is found, not where it lands.
    """
    import numpy as np
    from . import anm
    src0 = source_palettes[base_bank]
    where, duplicates = {}, {}
    for j, c in enumerate(src0):
        if c[3]:
            key = tuple(int(x) for x in c[:3])
            if key in where:
                duplicates.setdefault(key, [where[key]]).append(j)
            where.setdefault(key, j)
    base = anm.get_palette(anmfile, 0)
    used = {tuple(int(x) for x in base[i, :3]) for i in range(len(base)) if base[i, 3]}
    hits = [(i, where[tuple(int(x) for x in base[i, :3])]) for i in range(len(base))
            if base[i, 3] and tuple(int(x) for x in base[i, :3]) in where]
    missing = [i for i in range(len(base)) if base[i, 3] and tuple(int(x) for x in base[i, :3]) not in where]
    used_duplicates = {k: v for k, v in duplicates.items() if k in used}
    conflict_banks = []
    for k, pal in enumerate(source_palettes):
        if any(not np.array_equal(pal[idxs[0]][:3], pal[j][:3]) for idxs in used_duplicates.values()
               for j in idxs[1:]):
            conflict_banks.append(k)
    dropped = []
    if conflict_banks:
        if exact_banks:
            dropped = conflict_banks
        elif not approximate:
            first = next(iter(used_duplicates))
            raise ValueError(f"source colour {first} is two palette entries that differ in another palette")
    kept = [k for k in range(len(source_palettes)) if k not in dropped]
    still_ambiguous = {key for key, idxs in used_duplicates.items()
                       if any(not np.array_equal(source_palettes[k][idxs[0]][:3], source_palettes[k][j][:3])
                              for k in kept for j in idxs[1:])}
    ambiguous_count = sum(1 for i, _ in hits if tuple(int(x) for x in base[i, :3]) in still_ambiguous)
    exact_count = len(hits) - ambiguous_count
    if approximate:
        choices = np.array(list(where), dtype=np.int32)
        if not len(choices):
            raise ValueError('No visible source palette colours')
        for i in missing:
            colour = choices[((choices - base[i, :3].astype(np.int32)) ** 2).sum(axis=1).argmin()]
            hits.append((i, where[tuple(int(x) for x in colour)]))
    for k in range(min(len(anmfile.palettes), len(source_palettes))):
        pal = base.copy()
        source = 0 if k in dropped else k
        for i, j in hits:
            pal[i, :3] = source_palettes[source][j][:3]
        anm.set_palette(anmfile, k, pal)
    if report is not None:
        report.update(dict(exact_entries=exact_count, ambiguous_entries=ambiguous_count,
                           missing_entries=len(missing), dropped_banks=dropped,
                           ambiguous_used_colours=len(used_duplicates), banks=len(source_palettes),
                           shipped_banks=kept))
    return exact_count, len(missing) + ambiguous_count


def select_default_palette(anmfile, selected, offsets=(0, 10)):
    """Make the source character's selected palette the bank's default slot 0 (D1CCOLOR1).

    A unique's art is built from colour-0 source art, so `map_source_palettes` leaves source palette 0 in
    slot 0 and the character-table selection `selected` only in slot `selected`.  The game draws slot 0 by
    default, so swap the two, in every palette group the bank has (the offset-10 graft group too).  Bank
    size, slot count and every image are unchanged; the old default moves to slot `selected`.
    Returns the swapped slot pairs."""
    from . import anm
    selected = int(selected)
    done = []
    if selected <= 0:
        return done
    for base in offsets:
        if base + selected < len(anmfile.palettes):
            a, b = anm.get_palette(anmfile, base), anm.get_palette(anmfile, base + selected)
            anm.set_palette(anmfile, base, b)
            anm.set_palette(anmfile, base + selected, a)
            done.append((base, base + selected))
    return done


def load_d4_mapping(path=None, pool=None, lenient=False):
    """the reviewed D4 -> D5 mapping data (d5lib/sourcemaps/d4.json unless another file is given)

    The checked-in map stores game text as SHA-256 references (docs/TEXT_REFS.md).  They are resolved here, so the
    caller always gets plain names and descriptions: from ``pool`` when given, otherwise from the prepared D4 folder
    and the Disgaea 5 tables (``_d4_source.text_pool_for_tools``).  A file that holds no references (a mapping a build
    already resolved) is returned as it is.  ``lenient`` keeps an unresolved reference as a marker (tests)."""
    path = Path(path) if path else Path(__file__).with_name('sourcemaps') / 'd4.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or data.get('game') != 'd4':
        raise ValueError('Not a D4 mapping file (schema 1)')
    from .importers import _d4_source
    if _d4_source.has_refs(data):
        data = (pool if pool is not None else _d4_source.text_pool_for_tools()).resolve_doc(data, lenient=lenient)
    return data


def complete_d4_mapping(inventory, mapping):
    """Expand reviewed choices with explicit unavailable placeholders, never name matching.

    The result contains source-derived metadata and belongs in the caller's
    private build directory. A placeholder has no donor and creates no native
    effect or learned skill. Its marked name and reason feed the gaps ledger.
    """
    from copy import deepcopy
    if inventory.get('schema') != 'd4-content-inventory/1':
        raise ValueError('Expected immutable D4 inventory schema 1')
    result = deepcopy(mapping)
    if result.get('schema') != 1 or result.get('game') != 'd4':
        raise ValueError('Expected reviewed D4 mapping schema 1')
    seen = set()
    for item in inventory['items']:
        kind = item['kind']
        if kind not in ('evility', 'skill'):
            continue
        sid = str(item['source_id'])
        key = kind, sid
        if key in seen:
            raise ValueError('Ambiguous source mapping identity: ' + str(key))
        seen.add(key)
        name = item['data']['name']
        choices = result.setdefault('evilities' if kind == 'evility' else 'skills', {})
        if sid not in choices:
            choices[sid] = dict(d4_name=name, relation='placeholder',
                display_name='[Unavailable D4] ' + (name or f'{kind} {sid}'),
                reason='No reviewed D5 equivalent; no native effect or learned skill emitted. Tier 2 port remains open.')
        choices[sid]['source_evidence'] = dict(uid=item['uid'], **item['source'])
    return result


from .d4voices import import_d4_voice  # public importer compatibility alias



def d4_ability_adaptations(report):
    """The existing import disclosure lines, also usable in a pinned update contract."""
    return [f"{x['kind']} {x['d4_name']} ({x['d4_id']}): {x['status']}"
            + (f" -> D5 {x.get('works_like_name') or x.get('copy_of')}" if x.get('d5_id') else '')
            for x in report]

def d4_lease_digest(value):
    """Canonical JSON fingerprint; callers must supply an independently pinned value."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_d4_update_leases(leases, expected_sha256):
    """Validate an explicit prior ownership snapshot, never discover live state."""
    if not isinstance(leases, dict) or leases.get('schema') != 'd4-update-leases/1' or \
            not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or \
            d4_lease_digest(leases) != expected_sha256:
        raise ValueError('Missing or changed pinned D4 update leases')
    if not isinstance(leases.get('owners'), dict) or not isinstance(leases.get('claims'), dict):
        raise ValueError('D4 update ownership/claims missing')
    for mid, owner in leases['owners'].items():
        for kind, table in (('skills', 'magic.dat'), ('evilities', 'Skill.dat')):
            entries = owner.get(kind, {})
            ids = [x.get('id') for x in entries.values()]
            if len(ids) != len(set(ids)):
                raise ValueError('Duplicate prior ability lease')
            for sid, entry in entries.items():
                if type(entry.get('id')) is not int or entry['id'] <= 0 or \
                        leases['claims'].get(table, {}).get(str(entry['id'])) != [mid] or \
                        owner.get('sources', {}).get(kind, {}).get(sid) != \
                        {k: entry.get(k) for k in ('uid', 'sha256')}:
                    raise ValueError('Foreign or unverifiable prior ability lease')
                if not entry.get('uid') or not re.fullmatch('[0-9a-f]{64}', entry.get('sha256', '')):
                    raise ValueError('Prior ability source evidence missing')
    return leases



def d4_update_options(path=None, expected_sha256=None, owner_mod_id=None, *, owner_required=True):
    """Read explicit CLI input before any build/cache work; no default discovery."""
    if path is None and expected_sha256 is None and owner_mod_id is None:
        return {}
    if path is None:
        raise ValueError('D4 updates require a previous-leases JSON file')
    leases = json.loads(Path(path).read_text())
    validate_d4_update_leases(leases, expected_sha256)
    result = dict(previous_leases=leases, previous_leases_sha256=expected_sha256)
    if owner_required:
        _d4_update_owner(leases, expected_sha256, owner_mod_id)
        result['owner_mod_id'] = owner_mod_id
    return result

def _d4_update_owner(leases, expected_sha256, owner_mod_id):
    validate_d4_update_leases(leases, expected_sha256)
    if not isinstance(owner_mod_id, str) or owner_mod_id not in leases['owners']:
        raise ValueError('Explicit prior D4 owner required')
    return leases['owners'][owner_mod_id]



def verify_d4_previous_mod(mod, leases, expected_sha256, owner_mod_id):
    """Verify the complete pinned prior tree before exempting its own claims."""
    owner = _d4_update_owner(leases, expected_sha256, owner_mod_id)
    source = mod.meta.get('source_import', {})
    identity = source.get('identity') or {k: source.get(k) for k in ('source_game', 'source_id')}
    if mod.id != owner_mod_id or identity != owner.get('source_identity') or \
            d4_lease_digest(mod.meta) != owner.get('baseline_meta_sha256'):
        raise ValueError('Prior D4 owner/source/metadata drift')
    root = Path(mod.folder)
    if root.is_symlink():
        raise ValueError('Prior D4 owner root is a symlink')
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Prior D4 owner tree contains symlink')
        if path.is_file():
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not owner.get('baseline_files') or files != owner['baseline_files']:
        raise ValueError('Prior D4 owner payload/patch drift')
    return owner

def plan_d4_profile(profile, mapping, *, family, template_rows, skill_table, magic_table,
                    reserved_evilities=(), reserved_skills=(), previous_leases=None,
                    previous_leases_sha256=None, owner_mod_id=None, pinned_evilities=None, pinned_skills=None):
    """Source battle profile -> per-rank D5 char.dat fields plus the new evility / skill rows to create.

    Pure planning (no writes): returns dict(ranks=[{field: value}] x6, evilities=[...], skills=[...],
    report=[...]).  Values come from d5lib.d4source (actual D4 rows); evility / skill choices from the reviewed
    mapping only -- an entry missing from the mapping is reported and left out, never guessed.
    """
    from . import charstudio, dbpatch
    report, evilities, skills = [], {}, {}
    taken_e, taken_s = set(reserved_evilities), set(reserved_skills)
    previous = None
    if previous_leases is not None or previous_leases_sha256 is not None or owner_mod_id is not None:
        previous = _d4_update_owner(previous_leases, previous_leases_sha256, owner_mod_id)
        if previous.get('family') != family or previous.get('source_ids') != [r['id'] for r in profile] or \
                previous.get('profile_sha256') != d4_lease_digest(profile):
            raise ValueError('D4 update owner/source profile drift')
        taken_s.update(int(i) for i in previous_leases['claims'].get('magic.dat', {}))
        taken_e.update(int(i) for i in previous_leases['claims'].get('Skill.dat', {}))
        for kind, table in (('skills', magic_table), ('evilities', skill_table)):
            for sid, lease in previous[kind].items():
                choice = mapping.get(kind, {}).get(sid, {})
                donor = choice.get('copy_of' if kind == 'skills' else 'works_like')
                evidence = choice.get('source_evidence', {})
                if choice.get('relation') in (None, 'omit', 'placeholder') or donor != lease['donor'] or \
                        {k: evidence.get(k) for k in ('uid', 'sha256')} != previous['sources'][kind][sid]:
                    raise ValueError('Existing D4 ability omitted or source/donor drifted')
                placed = [r for r in table.rows if r['id'] == lease['id']]
                if placed:
                    raise ValueError('Prior D4 leased target row is present; original table required')

    def ability_id(kind, source_id, choice, table, taken):
        if previous is not None:
            evidence = choice.get('source_evidence', {})
            if previous['sources'].get(kind, {}).get(str(source_id)) != \
                    {k: evidence.get(k) for k in ('uid', 'sha256')}:
                raise ValueError('Unverifiable D4 update source ability')
            lease = previous[kind].get(str(source_id))
            if lease is not None:
                return lease['id']
        pins = pinned_evilities if kind == 'evilities' else pinned_skills
        if pins and int(source_id) in pins:
            row = int(pins[int(source_id)])                  # recorded lease: reproduced, never re-allocated
            if any(r['id'] == row for r in table.rows) or row in taken:
                raise ValueError(f'Leased {kind[:-1]} row {row} (D4 id {source_id}) is occupied')
            return row
        allocate = charstudio.free_skill_id if kind == 'skills' else charstudio.free_evility_id
        return allocate(table, family, taken)
    order = []
    for rank in profile:
        for ev in [rank['innate_evility']] + rank['evilities']:
            if ev['id'] and ev['id'] not in order:
                order.append(ev['id'])
    for d4id in order:
        m = mapping.get('evilities', {}).get(str(d4id))
        name = next((e.get('name') for r in profile for e in [r['innate_evility']] + r['evilities'] if e['id'] == d4id), '')
        if not m:
            report.append(dict(kind='evility', d4_id=d4id, d4_name=name, status='unmapped'))
            continue
        if m['relation'] in ('omit', 'placeholder'):
            report.append(dict(kind='evility', d4_id=d4id, d4_name=name,
                               status='placeholder' if m['relation'] == 'placeholder' else 'omitted',
                               reason=m.get('reason', ''), display_name=m.get('display_name')))
            continue
        if not any(r['id'] == m['works_like'] for r in skill_table.rows):
            raise ValueError(f"mapping: evility {m['works_like']} does not exist in D5")
        eid = ability_id('evilities', d4id, m, skill_table, taken_e)
        taken_e.add(eid)
        innate = any(r['innate_evility']['id'] == d4id for r in profile)
        mana = next((e.get('mana') for r in profile for e in r['evilities'] if e['id'] == d4id), None)
        evilities[d4id] = dict(id=eid, works_like=m['works_like'], name=m['d4_name'], desc=m.get('desc'),
                               relation=m['relation'], unique=innate,
                               mana=mana if isinstance(mana, int) and 0 < mana < 0xFFFFFFFF else None,
                               first_rank=next((k + 1 for k, r in enumerate(profile)
                                                if any(e['id'] == d4id for e in [r['innate_evility']] + r['evilities'])), 1))
        report.append(dict(kind='evility', d4_id=d4id, d4_name=name, status=m['relation'], d5_id=eid,
                           works_like=m['works_like'], works_like_name=m.get('works_like_name')))
    for rank in profile:
        for sk in rank['skills']:
            if sk['id'] in skills or any(x.get('d4_id') == sk['id'] and x['kind'] == 'skill' for x in report):
                continue
            m = mapping.get('skills', {}).get(str(sk['id']))
            if not m or m['relation'] in ('omit', 'placeholder'):
                report.append(dict(kind='skill', d4_id=sk['id'], d4_name=sk.get('name'),
                                   status='unmapped' if not m else ('placeholder' if m['relation'] == 'placeholder' else 'omitted'),
                                   reason=m.get('reason', '') if m else '',
                                   display_name=m.get('display_name') if m else None))
                continue
            if not any(r['id'] == m['copy_of'] for r in magic_table.rows):
                raise ValueError(f"mapping: skill {m['copy_of']} does not exist in D5")
            sid = ability_id('skills', sk['id'], m, magic_table, taken_s)
            taken_s.add(sid)
            skills[sk['id']] = dict(id=sid, copy_of=m['copy_of'], name=m['d4_name'], desc=m.get('desc'),
                                    fields=m.get('fields', {}), relation=m['relation'],
                                    experimental=bool(m.get('experimental')))
            report.append(dict(kind='skill', d4_id=sk['id'], d4_name=sk.get('name'), status=m['relation'],
                               d5_id=sid, copy_of=m['copy_of'], experimental=bool(m.get('experimental'))))
    ranks = []
    if previous is not None and (set(previous['skills']) - {str(i) for i in skills} or
                                 set(previous['evilities']) - {str(i) for i in evilities}):
        raise ValueError('Existing D4 ability lease dropped from update')
    for k, rank in enumerate(profile):
        f = dict(rank['battle'])
        donor = template_rows[k]
        f['kind_gender'] = donor['kind_gender'] // 10 * 10 + rank['battle']['kind_gender'] % 10
        f['res_star'] = 0                                   # D4 has no Star element
        # built in: D4's innate (Unique) evility only -- the game shows every built-in evility as Unique; D4's rank
        # evilities are Common ones the class learns in the Skill Shop (see build_d4_pilot / docs/D4_IMPORT.md)
        evs = [evilities[e['id']]['id'] for e in [rank['innate_evility']] + rank['evilities']
               if e['id'] in evilities and evilities[e['id']]['unique']]
        if len(evs) > len(dbpatch.EVILITIES):
            raise ValueError(f"rank {k + 1}: {len(evs)} evilities, the game has {len(dbpatch.EVILITIES)} slots")
        for n, fname in enumerate(dbpatch.EVILITIES):
            f[fname] = evs[n] if n < len(evs) else 0
        f['evility_count'] = len(evs)
        learn = [(skills[s['id']]['id'], s['level']) for s in rank['skills'] if s['id'] in skills]
        for n in range(16):
            f[f'learn{n + 1}_skill'], f[f'learn{n + 1}_level'] = learn[n] if n < len(learn) else (0, 0)
        f['learn_count'] = len(learn)
        ranks.append(f)
    return dict(ranks=ranks, evilities=list(evilities.values()), skills=list(skills.values()), report=report)


def _d4_class_help(source_lines, pending_abilities=()):
    """Keep source lines intact; creation help never includes the pending overlay.

    D4's third line is player text (Weapon Forte / Magichange Type).  A list of abilities the port could
    not map belongs in the mod's adaptations/receipt, not on the class's help screen: the literal
    "D4 skills/Evilities pending; see GAPS." shipped in 45 class packs and Sean read it as leftover
    pilot text on the recruiter wheel (playtest PT1029 W3).
    """
    original = list(source_lines)
    if len(original) > 3 or any(not isinstance(line, str) for line in original):
        raise ValueError('D4 class help needs at most three text lines')
    original += [''] * (3 - len(original))
    description = ' '.join(line.strip() for line in original if line.strip())
    if not description:
        description = 'Class description unavailable.'
    displayed = list(original)
    return original, displayed, description


def build_d4_pilot(*, prepared_root, library_root, source_archive, game_path,
                   face_path, cutin_path, output_path, family, template,
                   supported_families, source_ids, edition, backup_resolver=None, log=print,
                   source_root=None, mapping=None, class_name='Male Armor Knight (D4 pilot)',
                   unlocked_ranks=1, voice_id=None, mod_id=None, d4_idle=False, d4_face_rule=True,
                   sprite_family=None, kind=None, reserved_evilities=(), reserved_skills=(),
                   approximate_palettes=False, source_frame_fallbacks=False, source_voice=None,
                   personality_variants=None, previous_leases=None,
                   previous_leases_sha256=None, owner_mod_id=None, exact_emission=None, exact_mods_roots=()):
    """Emit one adapted six-rank D4 humanoid or monster and native staging kit.

    All roots/IDs are explicit. `supported_families` is a caller-owned scratch
    allowlist, NOT an allocator/global lease or permission to install. Restricted
    to explicit Kit leases or registry identities with physical leases; refuses
    existing non-dummy character overwrites. Native
    original-data resolver is optional and read-only, never an Installer object.
    Sprite/motion caches must be caller-configured per-output siblings; shared
    caches are refused. No installed mod manager, settings or saves are used.

    With `source_root` (the D4 install folder) the D4 battle profile is applied as well (d5lib.d4source +
    the reviewed `mapping`, default d5lib/sourcemaps/d4.json): gender, movement, jump, throw, counter, crit,
    elemental resistances, per-rank innate evilities (new Skill.dat rows aliased to the mapped D5 evility) and
    learned skills (new magic.dat rows copied from the mapped D5 skill).  `unlocked_ranks` (1-6) ranks are
    recruitable / rebirth choices from the start; `voice_id` gives every rank that D5 voice.
    """
    import copy
    import os
    import shutil
    import tempfile
    from PIL import Image
    from . import anm, database, dbpatch, gamefs, gamepacks, modsys, newclasses, offlinepaths, ownanim, outfits, sourcefidelity, sprites

    if previous_leases is not None or previous_leases_sha256 is not None or owner_mod_id is not None:
        owner = _d4_update_owner(previous_leases, previous_leases_sha256, owner_mod_id)
        if source_root is None or mod_id != owner_mod_id or family != owner['family']:
            raise ValueError('Update build requires explicit canonical owner and source profile')
        if not callable(backup_resolver):
            raise ValueError('Update build requires an explicit original backup resolver')
    physical = family if sprite_family is None else sprite_family
    kind = kind or ('monster' if type(template) is int and template >= 2000 else 'humanoid')
    monster = kind == 'monster'
    donor_ok = (2010 <= template <= 2210 if monster else 1010 <= template <= 1260) if type(template) is int else False
    if (type(family) is not int or family % 10 or family not in supported_families or
            type(physical) is not int or physical % 10 or kind not in ('humanoid', 'monster') or
            physical not in (newclasses.MONSTER_FAMILIES if monster else newclasses.HUMAN_FAMILIES) or
            not donor_ok or template % 10):
        raise ValueError('Explicit supported family, matching physical sprite lease and vanilla template required')
    spec = dict(family=family, template=template, kind=kind, sprite_family=physical)
    if family != physical:
        newclasses.validate_specs({family: spec})
    output_path = Path(os.path.abspath(output_path))
    if output_path.exists() or any(p.is_symlink() for p in (output_path, *output_path.parents)):
        raise ValueError('Output must be new and have no symlink ancestors')
    protected = (prepared_root, library_root, source_archive, source_root, game_path,
                 face_path, cutin_path, Path(__file__).resolve().parents[1])
    offlinepaths.offline_output(output_path, protected)
    offlinepaths.offline_output(str(output_path) + '.cache', (*protected, output_path))
    offlinepaths.separate_outputs(output_path, str(output_path) + '.cache')
    offlinepaths.require_output_cache(sprites.CACHE_DIR, output_path, protected)
    source = read_prepared(prepared_root, library_root, edition=edition)
    ranks = read_d4_ranks(source_archive, source_ids=source_ids, edition=edition)
    if (source['identity']['character_id'] != source_ids[0] or
            any(r['body'] != source['identity']['body'] or r['name'] != ranks[0]['name'] or
                not r['title'] for r in ranks)):
        raise ValueError('Source rank identity/body does not match selected prepared art')
    poses = ('stand', 'wait', 'walk', 'damage', 'attack_fist') if monster else (
        'stand', 'wait', 'walk', 'damage', 'attack_fist', 'attack_sword', 'attack_lance', 'attack_arrow', 'attack_gun', 'attack_ax')
    required = [(a, v) for a in poses for v in ('front', 'back')]
    if any(k not in source['sequences'] for k in required):
        raise ValueError('Selected D4 humanoid art lacks required native pose sequences')
    screen_art = []
    for p in (face_path, cutin_path):
        raw = _read(p, MAX_BODY)
        with Image.open(p) as image:
            if image.width > 4096 or image.height > 4096 or image.convert('RGBA').getchannel('A').getextrema()[1] == 0:
                raise ValueError('Invalid source face/cut-in dimensions or alpha')
            screen_art.append(dict(path=str(Path(p).resolve()), sha256=_hash(raw), bytes=len(raw), size=list(image.size)))
    fs = gamefs.GameFS(str(game_path), backup_resolver=backup_resolver)
    try:
        vanilla = database.load_table('char.dat', fs.read(newclasses.CHAR))
        rows = {r['id']: r for r in vanilla.rows}
        if any(family + k in rows and not rows[family + k]['is_dummy_slot'] for k in range(6)):
            raise ValueError('Target would overwrite an existing non-dummy character')
        if any(template + k not in rows for k in range(6)):
            raise ValueError('Missing native donor rank')
        source_profile = plan = source_profile_help = None
        if source_root is not None:
            from . import d4source
            source_profile_help = d4source.D4Data(source_root).chars[source_ids[0]]['help_id']
            source_profile = d4source.D4Data(source_root).class_profile(source_ids[0], 6)
            if [r['id'] for r in source_profile] != list(source_ids):
                raise ValueError('D4 profile ranks do not match the selected source ids')
            if any(p['base'] != r['base'] or p['aptitudes'] != r['aptitudes'] for p, r in zip(source_profile, ranks)):
                raise ValueError('D4 profile reader disagrees with the validated rank reader')
            from . import charstudio
            original_reserved = charstudio.all_mod_skill_ids((), fs=fs)
            if previous_leases is not None and any(x['id'] in original_reserved for x in owner['skills'].values()):
                raise ValueError('Prior D4 skill wrapper collides with an original event')
            plan = plan_d4_profile(source_profile, mapping or load_d4_mapping(), family=family,
                                   template_rows=[rows[template + k] for k in range(6)],
                                   skill_table=database.load_table('Skill.dat', fs.read(newclasses.SKILL)),
                                   magic_table=database.load_table('magic.dat', fs.read(newclasses.MAGIC)),
                                   reserved_evilities=reserved_evilities, reserved_skills=set(reserved_skills) | original_reserved,
                                   previous_leases=previous_leases, previous_leases_sha256=previous_leases_sha256,
                                   owner_mod_id=owner_mod_id)
        if source_voice is not None:
            if source_root is None:
                raise ValueError('Source voice requires an explicit D4 root')
            voice_id = source_voice['voice_id']
        if source_voice is None and voice_id is not None and not any(r['voice_id'] == voice_id for r in vanilla.rows):
            raise ValueError(f'voice {voice_id} is not a voice of the game')
        gameplay = []
        for k, rank in enumerate(ranks):
            description = sourcefidelity.from_profile(rank, game='d4', edition=edition, rank_count=6, rank_index=k)
            _, audit = sourcefidelity.encode_gameplay(rows[template + k], description, policy='faithful')
            gameplay.append(audit)
        resident = anm.parse(fs.read('Anime/ANM_HI_JP.dat/anm_resident.lzs'))
        motion = None if monster else next(b for b in resident.blocks if b.id == 1)
        base = anm.parse(fs.read(sprites.sprite_vpath(fs, template, 'EN')))
        while len(base.palettes) < 10:
            anm.set_palette(base, len(base.palettes), anm.get_palette(base, 0))
        animation_report = {}
        from . import frameconvert
        sprite = ownanim.build(source['sequences'], base, motion, physical,
                               variants=[(0, 0, 0)], report=animation_report, log=log,
                               prefer=frameconvert.MONSTER_ROWS if monster else None,
                               source_fallbacks=source_frame_fallbacks, whole_body=True)
        # the stand picture must stand on the donor's ground line (playtest PT1027 S2)
        from . import standground
        standground.normalize_stand_ground(sprite, standground.bound_reference(base, motion),
                                           report=animation_report, log=log)
        if len(sprite.palettes) < 10 or len({p.data for p in sprite.palettes}) != 1:
            raise ValueError('Expected explicitly duplicated source palette-0 banks')
        source_palettes = palette_report = None
        if source_root is not None:                         # D4's own colour per rank (and the extra colours)
            source_palettes = d4source.D4Data(source_root).body_palettes(ranks[0]['body'])
            palette_report = map_source_palettes(sprite, source_palettes, approximate=approximate_palettes)
            if palette_report[1] and not approximate_palettes:
                raise ValueError(f'{palette_report[1]} sprite colours are not D4 palette-0 colours')
        idle_audit = None
        if source_root is not None and d4_idle and not monster:
            from . import d4idle
            sprite, idle_audit = d4idle.apply(sprite, d4source.D4Data(source_root).anm(ranks[0]['body']), log=log)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix='.' + output_path.name + '-', dir=output_path.parent))
        try:
            mod_id = mod_id or f'D4_Class_{source_ids[0]}'
            mod_root = temp / 'native-mods' / mod_id
            mod = modsys.Mod(str(mod_root))
            adaptations = [
                'Adapted overall; exact source stored bases/aptitudes only, NOT equivalent growth/mechanics',
                'Unmatched donor drawing keys hidden; no donor battle texture fill',
                'Scratch caller-approved dummy family; no installed/global reservation',
                'Real source cut-in main layer; auxiliary donor textures cleared',
            ]
            adaptations.append('Ten identical source palette-0 banks; authentic rank colours unimplemented'
                               if palette_report is None else
                               f'D4 body palettes per colour ({palette_report[0]} exact entries, '
                               f'{palette_report[1]} nearest-source palette approximations); '
                               + ('D4 class face on every colour slot (the game draws it for every rank row) and cut-in per colour where extracted; D4 class description'
                                if d4_face_rule and source_root is not None else
                                'D4 face and cut-in per colour where extracted; D4 class description'))
            if plan is None:
                adaptations += ['D5 donor timing, attachments, mastery, movement, resistances, voices and personality retained',
                                'Source weapon/skills/evilities unmapped; donor learned skills/evilities/Overload cleared']
            else:
                adaptations += ['D4 gender, MOV/move type/attack range, JMP, throw, counter, crit and Fire/Wind/Ice '
                                'resistances per rank from D4 char.dat (Star 0: D4 has no Star element)',
                                'D5 donor timing, attachments, weapon mastery and weapon resistances retained (D4 has neither per class)',
                                'D4 evilities as innate per rank: own names/descriptions, D5 effects and D5 numbers (alias)',
                                'D4 skills as copies of mapped D5 skills (lookalikes; see mapping report)']
                adaptations += d4_ability_adaptations(plan['report'])
            adaptations.append(f'Ranks unlocked from the start: {unlocked_ranks} of 6'
                               + ('' if unlocked_ranks > 1 else '; rank chain/native recruitment acceptance unverified'))
            if voice_id is not None:
                adaptations.append(f'Voice: custom D4 source voice {voice_id}, explicit adapted event choices; D5 timing/randomizer'
                                   if source_voice is not None else
                                   f'Voice: D5 voice {voice_id} (interim until the D4 voice situations are mapped)')
            adaptations.append('Idle (6001/6007): D4 timing and D4 weapon positions (d5lib.d4idle); other animations D5 timing'
                               if idle_audit else 'All animations: D5 template timing and weapon positions')
            mod.meta.update(name=class_name + ' — adapted offline import', author='Local source import',
                            category='classes', version='0.0.2-pilot',
                            description='Genuine six D4 static rank rows and prepared art; mechanics/native acceptance incomplete.',
                            source_import=dict(identity=source['identity'], fidelity='adapted', adaptations=adaptations,
                                               source_ranks=ranks, gameplay=gameplay, screen_art=screen_art,
                                               yield_source=donor_yield(D4_YIELD_NOTE)))
            mod.save_meta()
            voice_receipt = (import_d4_voice(mod, d4source.D4Data(source_root), **source_voice)
                             if source_voice is not None else None)
            for number, body in [(physical, sprite), (physical + 1, ownanim.with_id(sprite, physical + 1))]:
                mod.write_file(f'Anime/ANM_HI_JP.dat/anm{number:05d}.lzs', body.to_bytes())
            # These two donor icons are assembled from several independent
            # cells. A full-pose repaint of that atlas produces fragments.
            # Use the vanilla 2082 single-cell-per-view layout for their D4 art.
            single_cell_icon = monster and int(source_ids[0]) in (2120, 2190)
            icon_template = 2082 if single_cell_icon else template + 2
            rb = next(b for b in resident.blocks if b.id == icon_template)
            icon = anm.AnmFile([copy.deepcopy(rb)], copy.deepcopy(resident.textures[rb.tex_base:rb.tex_base + len(rb.texture_infos)]),
                               copy.deepcopy(resident.palettes[rb.pal_base:rb.pal_base + len(rb.palette_infos)]))
            icon.blocks[0].tex_base = icon.blocks[0].pal_base = 0
            icon = (outfits.repaint_single_cell_monster_icon(icon, sprite) if single_cell_icon else
                    outfits.repaint_stand_icon(icon, base, motion, sprite))
            for palette in icon.palettes[1:]:
                palette.data = icon.palettes[0].data
            if source_palettes is not None:
                map_source_palettes(icon, source_palettes, approximate=approximate_palettes)
            icon.blocks[0].id = physical + 2
            mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical + 2:05d}.lzs', icon.to_bytes())
            def edit(row, k):
                for field, value in gameplay[k]['fields'].items():
                    row.set(field, value)
                for field, value in (plan['ranks'][k] if plan else {}).items():
                    row.set(field, value)
                if voice_id is not None:
                    row.set('voice_id', voice_id)
            d4help = (d4source.D4Data(source_root).help_lines(source_profile_help)
                      if source_root is not None else [])
            pending_abilities = [x for x in (plan['report'] if plan else [])
                                 if x['status'] in ('placeholder', 'unmapped', 'omitted')]
            original_help_lines, help_lines, hire_desc = _d4_class_help(d4help, pending_abilities)
            newclasses.fill_class(fs, mod, family, template, class_name,
                                  [r['title'] for r in ranks],
                                  help_lines=help_lines, edit=edit, log=log, sprite_family=physical)
            source_personalities = (d4source.D4Data(source_root).personality_rows(source_ids[0]) if source_root is not None else [])
            names = (d4source.D4Data(source_root).personality_names(source_ids[0], variants=personality_variants) if source_root is not None else
                     ((mapping or load_d4_mapping()).get('personalities', {}).get(str(source_ids[0]))
                      if plan else None) or ['Diligent', 'Proud', 'Newbie'])
            newclasses.add_personalities(fs, mod, family, template, names)
            aliases = {}
            for ev in (plan['evilities'] if plan else []):
                # D4's innate evility: built in, Unique.  D4's rank evilities: Common evilities only this class can
                # learn in the Skill Shop -- a character-owned evility (source 4, owner = the class: the shop checks
                # unit id / 10 == owner / 10), never a class evility (source 3: the shop reads the owner class's
                # mastery, which an imported class has not -> crash at 0x1407CDAE1).  D4 mana price, no shop rank.
                extra = (dict(kind=1, slot_cost=0, source=4) if ev['unique'] else
                         dict(kind=0, source=4, shop_rank=0, **({'mana_cost': ev['mana']} if ev['mana'] else {})))
                newclasses.add_evility(fs, mod, ev['id'], ev['works_like'], ev['name'], ev['desc'],
                                       owner=family, order=0, **extra)
                aliases[str(ev['id'])] = ev['works_like']
            for sk in (plan['skills'] if plan else []):
                newclasses.add_skill(fs, mod, sk['id'], sk['copy_of'], sk['name'], sk['desc'], **sk['fields'])
            from PIL import Image as _Image
            # D4FACE1 (D4-FACE-02, rule proven under Unicorn): the game draws the class face for every rank row of a
            # class, so each of the ten colour slots gets the class face.  `d4_face_rule=False` is the old path: a face
            # per colour (swf<body + k)  when all ten exist, else the one face for colour 0 only.
            faces = class_face_files(face_path, ranks[0]['body'], source_root is not None, d4_face_rule)
            for k, fp in enumerate(faces):                     # D4 faces are drawn on plain white; one per colour
                with _Image.open(fp) as face_image:
                    newclasses.set_face(mod, family, d4_screen_picture(face_image, FACE_MATTE),
                                        colour=k)
            cutins = (colour_variants(cutin_path, 10000 + ranks[0]['body']) if source_root is not None else None)
            newclasses.set_portraits(fs, mod, physical, template, cutins or str(cutin_path), matte=D4_MATTE if D4_MATTE is not None else False)
            for number in range(10000 + physical, 10000 + physical + 10):
                vp = f'Anime/ANM_HI_JP.dat/anm{number:05d}.lzs'
                portrait = anm.parse(mod.read_file(vp))
                if portrait.textures[0].indexed:
                    raise ValueError('Unsupported indexed cut-in template')
                for texture in portrait.textures[1:]:
                    texture.data = bytes(len(texture.data))
                mod.write_file(vp, portrait.to_bytes())
            newclasses.save_spec(mod, dict(**spec, name=class_name,
                                          unlocked=True, unlocked_ranks=int(unlocked_ranks),
                                          hire_desc=hire_desc, evility_alias=aliases))
            exact_receipt = []
            if exact_emission is not None:
                if not source_profile or previous_leases is not None:
                    raise ValueError('Exact import requires source profile and no prior lease update')
                from . import d4exact
                existing_mods = d4exact.existing_mods(game_path, exact_mods_roots)
                exact_receipt = d4exact.apply_import(mod, exact_emission, source_profile, family,
                    database.load_table('Skill.dat', fs.read(newclasses.SKILL)), existing_mods, plan['report'])
                replacements = {r['replaced']: r['target_id'] for r in exact_receipt if r['replaced'] is not None}
                for rank in plan['ranks']:
                    for n in range(1, 5):
                        key = f'evility{n}'
                        if rank.get(key) in replacements:
                            rank[key] = replacements[rank[key]]
            inventory, readback = [], []
            for path in sorted(mod_root.rglob('*')):
                if not path.is_file():
                    continue
                raw = path.read_bytes()
                item = dict(path=path.relative_to(mod_root).as_posix(), bytes=len(raw), sha256=_hash(raw))
                if path.suffix == '.lzs':
                    parsed = anm.parse(raw)
                    if gamefs.decode_member(gamefs.encode_like(raw, None, path.name)) != raw:
                        raise ValueError('Native ANM archive codec roundtrip failed')
                    item['native_anm'] = dict(blocks=[b.id for b in parsed.blocks], palettes=len(parsed.palettes),
                                              textures=len(parsed.textures), archive_roundtrip=True)
                if path.parent.name == 'db' and path.suffix == '.json':
                    name = path.name[:-5]
                    table = database.load_table(name, fs.read('Database/Database_0.dat/' + name))
                    dbpatch.apply_patch(table, json.loads(raw), strict=True)
                    table = database.load_table(name, table.to_bytes())
                    item['db_rows'] = len(table.rows)
                    if name == 'char.dat':
                        by_id = {r['id']: r for r in table.rows}
                        for k, rank in enumerate(ranks):
                            row = by_id[family + k]
                            actual_base = [row['base_' + s] for s in sourcefidelity.STATS]
                            actual_apt = [row['apt_' + s] for s in sourcefidelity.STATS]
                            if actual_base != rank['base'] or actual_apt != rank['aptitudes']:
                                raise ValueError('Six-rank source static readback mismatch')
                            if any(row[f] != v for f, v in gameplay[k]['fields'].items()
                                   if not plan or f not in plan['ranks'][k]):
                                raise ValueError('Encoded gameplay field readback mismatch')
                            if plan and any(row[f] != v for f, v in plan['ranks'][k].items()):
                                raise ValueError('D4 battle profile readback mismatch')
                            readback.append(dict(id=family + k, source_id=rank['id'], base=actual_base,
                                                 aptitudes=actual_apt, title=row['title_EN']))
                inventory.append(item)
            if len(readback) != 6:
                raise ValueError('Missing six-rank DB readback')
            receipt = dict(schema=1, status='adapted-offline-not-installed', family=family, sprite_family=physical,
                           kind=kind, template=template,
                           source_help_lines=original_help_lines, displayed_help_lines=help_lines,
                           source_help_available=any(line.strip() for line in original_help_lines),
                           source_personalities=source_personalities, represented_personality_variants=personality_variants or [0,1,2],
                           pending_abilities=pending_abilities,
                           source_voice=voice_receipt,
                           palette_mapping=(dict(exact_entries=palette_report[0], approximated_entries=palette_report[1],
                               mode='nearest-source-RGB/first-ambiguous-index' if approximate_palettes else 'strict-exact')
                               if palette_report is not None else None),
                           d4_profile=source_profile, d4_plan=plan, d4_idle=idle_audit, exact_evilities=exact_receipt,
                           source=source['identity'], source_art=source['evidence'], screen_art=screen_art,
                           source_ranks=ranks, gameplay=gameplay, readback=readback, adaptations=adaptations,
                           ownanim={k: v for k, v in animation_report.items() if k not in ('matches', 'offsets')},
                           files=inventory, native_tested=False)
            (temp / 'pilot-receipt.json').write_text(json.dumps(receipt, indent=2))
            entry_id = (f'd4:pc-en-armor-knight-{source_ids[0]}-pilot' if source_ids[0] == 1080 and family == 1350 else
                        f'd4:pc-en-class-{source_ids[0]}')
            catalogue = dict(schema=1, id='source-pilot', name='Local source import pilots',
                games=[dict(id=i, name=n) for i, n in [('d1', 'Disgaea 1'), ('d2', 'Disgaea 2'),
                    ('d3', 'Disgaea 3'), ('d4', 'Disgaea 4 Complete+'), ('dd2', 'Disgaea D2'), ('rpg', 'Disgaea RPG')]],
                entries=[dict(id=entry_id, game='d4', name=class_name + ' — adapted offline import',
                    category='monsters' if monster else 'humanoid_classes', status='build-ready',
                    source=dict(edition=edition, identity=f'char.dat:{source_ids[0]}:body:{ranks[0]["body"]}',
                                provenance=[dict(kind='source-table', reference=ranks[0]['evidence']['table_sha256'])],
                                source_ids=source_ids, rank_count=6),
                    fidelity=dict(mode='hybrid', label='adapted',
                                  missing_mappings=['growth', 'weapon_preferences', 'rank_colours']
                                  + ([] if plan else ['skills', 'evilities']) + ['voice'],
                                  adaptations=adaptations),
                    artifact=dict(mod_id=mod_id, required_payload=[i['path'] for i in inventory if i['path'] != 'mod.json']))])
            registry = {mod_id: mod_root}
            catalogue = gamepacks.validate_catalogue(catalogue, artifacts=registry)
            plan = gamepacks.resolve_selection(catalogue, artifacts=registry, entries=[entry_id])
            gamepacks.materialize(catalogue, plan, artifacts=registry, staging_path=temp / 'staged-kit')
            (temp / 'catalogue.json').write_text(json.dumps(catalogue, indent=2))
            os.rename(temp, output_path)
        except BaseException:
            # Absolute paths keep the write audit meaningful; shutil.rmtree's
            # dir_fd-relative unlink events otherwise resolve against cwd and
            # can mask the original source validation error.
            def remove_staged(path):
                for child in path.iterdir():
                    if child.is_dir() and not child.is_symlink():
                        remove_staged(child)
                    else:
                        child.unlink()
                path.rmdir()
            try:
                remove_staged(temp)
            except (OSError, RuntimeError) as cleanup_error:
                log(f'Failed staging retained at {temp}: {cleanup_error}')
            raise
    finally:
        fs.reset()
    return dict(output=str(output_path), mod_id=mod_id, entry_id=entry_id,
                mod=str(output_path / 'native-mods' / mod_id), staging=str(output_path / 'staged-kit'),
                source_stats_readback=readback)

