"""DD2 source preparation, inside the kit (SOURCEPREP4-DD2).

Moved from ``Research/source-packs/dd2/reader/v2/dd2_prepare.py`` so a kit checkout carries its own DD2
glue.  It still calls the retained Character Forge readers (``forge``) in place: those are outside-kit
code resolved by ``_dd2_source.forge_root()``, never vendored here.  ``d2_face_location`` and its tables
were lifted out of ``forge/illustrations.py`` because the importer needs only that pure selector; the
values are the same ones the face atlas has always used.  No installer, save, donor or registry access.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

EDITION = 'Disgaea D2: A Brighter Darkness PS3 BLUS31313, local 1.40/DLC archives'
MAX_MEMBER = 128 * 1024 * 1024
EXPECTED_TABLE_SHA256 = 'd9cac040dda3b3e9aa8b6dbb5fa8951dd68c5f688cea853afd440e2a37f641dd'

# Face atlas selector (verbatim from forge/illustrations.py: _D2_UNIQUE / _D2_BANKS / d2_face_location).
_D2_UNIQUE = tuple(range(10, 150, 10)) + (1115,) + tuple(range(200, 450, 10))
_D2_BANKS = ('wf_unique1.lzs', 'wf_unique2.lzs', 'wf_human.lzs', 'wf_monster.lzs', 'wf_other.lzs')


def d2_face_location(face):
    if face < 500:
        return (0, _D2_UNIQUE.index(face)) if face in _D2_UNIQUE else None
    if 500 <= face < 1000 and face in range(500, 810, 10):
        return 1, (face - 500) // 10
    if 1000 <= face < 2000 and face // 10 in range(101, 128):
        return 2, face // 10 - 101
    if 2000 <= face < 3000 and face // 10 in range(201, 226):
        return 3, face // 10 - 201
    if face // 10 in (481, 482):
        return 4, face // 10 - 481
    return None


def face_bank(location):
    return _D2_BANKS[location[0]]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive_member(data, stem, member):
    """Read ``member`` from the verified source set (never by globbing the folder).

    ``data`` is a ``_dd2_source.Dd2Data``; a plain path is accepted for tests and explicit diagnostic
    roots only, and is turned into an unverified set of the ``*.dat`` files in it.
    """
    from forge.backend.d2_character_export import nispack
    from . import _dd2_source
    if not isinstance(data, _dd2_source.Dd2Data):
        data = _dd2_source.data_dir(data)
    for archive in data.archives(stem):
        with archive.open('rb') as stream:
            directory = nispack(stream, archive.stat().st_size)
            matches = [r for r in directory if r['name'] == member]
            if len(matches) > 1:
                raise ValueError('Duplicate selected archive member')
            if not matches:
                continue
            row = matches[0]
            if not 0 < row['size'] <= MAX_MEMBER:
                raise ValueError('Selected member outside bound')
            stream.seek(row['offset'])
            raw = stream.read(row['size'])
        if len(raw) != row['size']:
            raise ValueError('Truncated selected member')
        return raw, dict(path=str(archive), bytes=archive.stat().st_size,
                         member=member, member_offset=row['offset'], member_size=row['size'],
                         member_sha256=sha(raw), directory_sha256=sha(json.dumps(directory, sort_keys=True).encode()))
    raise ValueError('Source member absent: ' + member)


def read_selected(data, source_ids):
    from forge import d2art, nisfiles, stats_modern
    from forge.backend.d2_character_export import characters, anm_pages
    if not 1 <= len(source_ids) <= 6 or len(set(source_ids)) != len(source_ids):
        raise ValueError('Select1–6 distinct DD2 identities; no generated ranks')
    table, provenance = archive_member(data, 'START', 'char.dat')
    if sha(table) != EXPECTED_TABLE_SHA256:
        raise ValueError('Unreviewed DD2 source table hash: revalidate edition before importing')
    identities = {r['id']: r for r in characters(table)}
    raw_rows = {cid: table[r['record_offset']:r['record_offset'] + 676] for cid,r in identities.items()}
    # The stat reader's own directory scan is bypassed: it parses the char.dat this verified set
    # already selected, so an archive the manifest never lists cannot change the chosen table.
    # Its evidence keeps the four fields ``extract`` recorded (provenance hashes stay on source_table).
    stat_evidence = {k: provenance[k] for k in ('path', 'member', 'member_offset', 'member_size')}
    profiles = {r['id']: r for r in stats_modern.rows('d2', table, stat_evidence)}
    if len(identities) != len(characters(table)) or len(profiles) != len(identities):
        raise ValueError('Duplicate/missing source IDs')
    selected = []
    for cid in source_ids:
        row, profile = identities[cid], profiles[cid]
        record = table[row['record_offset']:row['record_offset'] + 676]
        if sha(record) != profile['evidence']['row_sha256'] or profile['evidence']['path'] != provenance['path']:
            raise ValueError('Static readers disagree on source row or precedence')
        assert list(struct.unpack_from('>8H', record, 4)) == profile['base']
        assert list(record[0x274:0x27c]) == profile['aptitudes']
        if struct.unpack_from('>H',record,0x194)[0] != cid:
            raise ValueError('Raw selected source ID guard failed')
        body = struct.unpack_from('>h', record, 0x196)[0]
        if not 1 <= body <= 32767:
            raise ValueError('Ordinary positive source appearance key required; special route needs own evidence')
        profile['evidence']['retained_reader_source_key'] = profile['source']
        profile['source'] = 'dd2'
        stored, art_evidence = archive_member(data, 'ANM_HI', f'anm{body:05d}.lzs')
        raw = nisfiles.expand(stored)
        summary = d2art.layout_summary(stored, body)
        delta = cid - body
        palette = struct.unpack_from('>b',record,0x28B)[0]
        if not 0 <= palette < summary['palettes']:
            raise ValueError('Authored default palette outside selected body palette count')
        family = sorted(rid for rid,rr in raw_rows.items() if struct.unpack_from('>h',rr,0x196)[0] == body and 0 <= rid - body < 6)
        # Exact byte accounting of every source palette and indexed texture; no guessed colors.
        decoded = anm_pages(raw, include_rgba=False, palette_indices=[palette])
        pages = d2art.pages(raw, palette)
        pixel_checks = []
        for p in decoded:
            if 'indices' not in p:
                raise ValueError('Unsupported texture format in selected appearance')
            reference = b''.join(p['colors'][i] for i in p['indices'])
            actual = pages[p['texture']]
            if reference != actual.tobytes():
                raise ValueError('Decoded texture pixels differ from source index/palette bytes')
            pixel_checks.append(dict(texture=p['texture'], palette=p['palette'], size=list(actual.size), rgba_sha256=sha(reference)))
        facings = {}
        for name, tags in [('front', d2art.FRONT), ('back', d2art.BACK)]:
            frames, pivot = d2art.standing(raw, body, palette, tags)
            if any(im.getchannel('A').getextrema()[1] == 0 for im in frames):
                raise ValueError('Transparent standing frame')
            facings[name] = dict(frames=len(frames), pivot=list(pivot),
                                  sizes=[list(im.size) for im in frames], rgba_sha256=[sha(im.tobytes()) for im in frames])
        selected.append(dict(source='dd2', edition=EDITION, id=cid, name=row['name'], title=row['name_230'],
                             body=body, appearance_variant=0, body_source_field='char.dat signed BE16+0x196; ordinary visual variant0',
                             source_words_1bc_1be=list(struct.unpack_from('>2H',record,0x1BC)),
                             source_words_1bc_1be_role='innateEvility candidates; not used for art routing',
                             source_rank_profiles=[dict(profiles[rid],source='dd2') for rid in family],
                             rank_palette_bindings=[dict(id=rid,body=struct.unpack_from('>h',raw_rows[rid],0x196)[0],
                                 palette=struct.unpack_from('>b',raw_rows[rid],0x28B)[0],row_sha256=sha(raw_rows[rid])) for rid in family], rank_delta=delta,
                             observed_family_rank_ids=family, palette=palette, palettes=summary['palettes'],
                             palette_rule='authored signed byte+0x28B, native ordinary visual constructor00029804 colorarg=-1; explicit overrides separate',
                             palette_evidence=dict(record_offset=0x28B, value=palette, consumer='func00029804 default -1 -> descriptor21E -> func002E8DFC -> model14/activeanim26; native-visual-binding.json'),
                             body_kind='humanoid' if summary['humanoid'] else 'monster',
                             profile=profile, body_sha256=sha(raw), source_table=provenance,
                             source_art=art_evidence, pixel_checks=pixel_checks, facings=facings,
                             _body_raw=raw))
    return selected


def prepare(rows, root, output, pose_table):
    from forge import d2art, monsterclips
    out = Path(output)
    if out.exists():
        raise ValueError('Output already exists; preserve accepted outputs')
    out.mkdir(parents=True)
    library = dict(format='character-forge-art/1', source='dd2', bodies={}, characters=[])
    common = None
    if any(r['body_kind'] == 'humanoid' for r in rows):
        if pose_table is None:
            raise ValueError('Pinned DD2 shared pose table required; no donor pose guessing')
        table = json.loads(Path(pose_table).read_text())
        if table.get('format') != d2art.TABLE_FORMAT:
            raise ValueError('Wrong shared pose table format')
        from forge import nisfiles
        stored, common_evidence = archive_member(root, 'ANM_HI', 'anm00001.lzs')
        common = nisfiles.expand(stored)
        if sha(common) != table['common_sha256']:
            raise ValueError('Shared pose table belongs to different DD2 animation source')
        library['pose_table'] = dict(path=str(Path(pose_table).resolve()), sha256=sha(Path(pose_table).read_bytes()),
                                     common_source=common_evidence, teachers=table['teachers'])
        library['bodies']['1'] = dict(sha256=sha(common), bytes=len(common))
    (out / 'library' / 'bodies').mkdir(parents=True)
    for row in rows:
        raw, body, cid = row['_body_raw'], row['body'], row['id']
        library['bodies'][str(body)] = dict(sha256=sha(raw), bytes=len(raw))
        (out / 'library' / 'bodies' / (sha(raw) + '.bin')).write_bytes(raw)
        library['characters'].append({k: row[k] for k in ('id','name','body','palette','palettes','body_kind')})
        folder = out / str(cid)
        if row['body_kind'] == 'humanoid':
            manifest = d2art.extract(raw, common, body, row['palette'], table, folder, name=row['name'], source='dd2')
        else:
            manifest = monsterclips.extract(raw, body, row['palette'], folder, 'dd2', name=row['name'])
        manifest['character_id'] = cid  # rank identity differs from body identity
        manifest['source_receipt'] = {k:v for k,v in row.items() if k != '_body_raw'}
        manifest['limitations'] = manifest.get('limitations', []) + ['Source timings not transferred by prepared-art importer; D5 target timing remains an adaptation.']
        (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    if common is not None:
        (out / 'library' / 'bodies' / (sha(common) + '.bin')).write_bytes(common)
    (out / 'library' / 'art-manifest.json').write_text(json.dumps(library, indent=2))
