"""The D1C pack builders (class batch, unique batch, donor probe) and the roster lists, inside the kit.

SOURCEPREP4-D1C: this is what ``Research/source-packs/d1c/batches/{build_batch,build_uniques_batch,
build_medium_batch,probe_donors}.py`` did for the importer, reduced to the functions the importer calls and
rewritten so that every input is explicit:

* game bytes come from :mod:`._d1c_source` (the verified prepared SUBDATA.DAT) and the Disgaea 5 install the
  caller names with :func:`configure` (``ctx['game_path']`` / ``ctx['state_root']``);
* the roster, leases, skill ladders and donor choices are ``d1c-roster.json`` (ids and counts); names and titles
  carry SHA-256 references and are read from the source (D1C names) or the D5 tables (D5 donor names) at build
  time, and a text that does not match its recorded hash is refused;
* nothing reads an installed pack, ``Builds/``, ``Research/`` or a machine path.

The classic stat table parser is the ``d1hd`` layout of the Character Forge's ``stats_classic.parse`` (code, no
game data); the table itself is start.dat member 43 of SUBDATA.DAT.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import unicodedata
from pathlib import Path

from . import _d1c_source as src

GAME: Path | None = None      # the Disgaea 5 install (configure)
STATE: Path | None = None     # the kit's state folder for it (configure)
EDITION = ('Disgaea 1 Complete HD art (Switch SUBDATA.DAT start.dat[98]) + classic HD char_e.dat '
           f'(sha256 {src.HD_TABLE_SHA256})')
TABLE_LAYOUT = dict(header=8, stride=224, identity=94, base=106, aptitudes=84)
ORDER = (0, 1, 2, 3, 4, 7, 6, 5)
MONSTER_DONORS = list(range(2010, 2300, 10))
HUMANOID_DONORS = list(range(1000, 1200, 10))

_state = {}


def configure(game_path, state_root):
    """Name the Disgaea 5 install and state folder the builders copy donor art from."""
    global GAME, STATE
    GAME, STATE = Path(game_path), Path(state_root)
    _state.pop('d5_names', None)
    _state.pop('text_pool', None)


def text_hash(text):
    return hashlib.sha256(unicodedata.normalize('NFKC', str(text)).strip().encode('utf-8')).hexdigest()


def _checked(value, expect, what):
    if expect is not None and text_hash(value) != expect:
        raise src.D1cSourceError(f'{what}: the text in the user\'s game files does not match the recorded '
                                 'SHA-256 (a different build of the game than the one the importer was checked on)')
    return value


def art():
    """The d1cart root built from the source (cached by the source module's view)."""
    return src.art_root()


def __getattr__(name):                      # ``bb.ART`` kept for the shared-motion adders in tools/
    if name == 'ART':
        return art()
    raise AttributeError(name)


# ------------------------------------------------------------------------------------------- roster lists
def roster_doc():
    return src.rules('roster')


def class_specs(donor_names=True):
    """The 13 class specs; ``name`` read from the character table, ``template_name`` from the D5 table
    (``donor_names=False`` skips the D5 table: the roster listing needs no donor name)."""
    out = []
    for c in roster_doc()['classes']:
        row = src.character(c['character_id'])
        if row is None:
            raise src.D1cSourceError(f"character {c['character_id']} is not in the source character table")
        out.append(dict(registry=c['registry'], kind=c['kind'], character_id=c['character_id'],
                        physical=c['physical'], template=c['template'],
                        name=_checked(row['name'], c['name_sha256'], f"class {c['registry']} name"),
                        template_name=(_checked(d5_name(c['template']), c['template_name_sha256'],
                                                f"class {c['registry']} donor name") if donor_names else None)))
    return out


def skills_plan():
    return {str(k): dict(v) for k, v in roster_doc()['skills'].items()}


def unique_rows(names=True):
    """The listing rows with the ROSTERGAP1 overrides applied; ``name``/``title`` from the character table
    (``names=False`` returns the ids and rules only, which needs no game file)."""
    out = []
    for r in roster_doc()['uniques']:
        d = {k: v for k, v in r.items() if not k.endswith('_sha256')}
        if not names:
            out.append(d)
            continue
        row = src.character(r['id'])
        if row is None:
            raise src.D1cSourceError(f"character {r['id']} is not in the source character table")
        d['name'] = _checked(row['name'], r['name_sha256'], f"listing {r['id']} name")
        d['title'] = _checked(row['title'], r['title_sha256'], f"listing {r['id']} title")
        out.append(d)
    return out


def unique_leases():
    """Recorded leases plus the ones measured for the roster gap (ids only, no text)."""
    return {k: dict(v) for k, v in roster_doc()['leases'].items()}


def donor_rows():
    """{listing id: donor row} for the uniques whose donor was measured and recorded."""
    out = {}
    for r in roster_doc()['donors']:
        d = {k: v for k, v in r.items() if not k.endswith('_sha256')}
        d['donor_name'] = _checked(d5_name(r['donor']), r['donor_name_sha256'], f"listing {r['id']} donor name")
        row = src.character(r['id'])
        d['name'], d['title'] = row['name'], row['title']
        out[int(r['id'])] = d
    return out


def donor_heights():
    return {int(k): v for k, v in roster_doc()['donor_heights'].items()}


# ------------------------------------------------------------------------------------------- D5 names
def text_pool():
    """D1C source strings plus the Disgaea 5 tables: the pool ``@text`` references resolve against.

    TEXTHASH-D1C-DD2: the D1C data files carry SHA-256 references; the build reads the strings here.
    Both halves are cached (the source in :mod:`._d1c_source`, D5 in :mod:`d5lib.textrefs`), so one
    process opens each game file once."""
    from ..textrefs import TextPool, d5_text_pool
    if GAME is None or STATE is None:
        raise src.D1cSourceError('the Disgaea 5 install is not configured for the D1C builders (configure())')
    if 'text_pool' not in _state:
        pool = TextPool(label='the D1C data files')
        pool.merge(src.text_pool())
        pool.merge(d5_text_pool(GAME, STATE))
        _state['text_pool'] = pool
    return _state['text_pool']


def d5_names():
    """{char id: name_EN} from the pristine D5 character table (the user's own game, through the kit's backups)."""
    if GAME is None or STATE is None:
        raise src.D1cSourceError('the Disgaea 5 install is not configured for the D1C builders (configure())')
    if 'd5_names' not in _state:
        from d5lib import database, gamefs
        from d5lib.d4unique import Originals
        fs = gamefs.GameFS(str(GAME), backup_resolver=Originals(STATE))
        try:
            chars = database.load_table('char.dat', fs.read('Database/Database_0.dat/char.dat'))
            _state['d5_names'] = {r['id']: (r.get('name_EN') or '').strip() for r in chars.rows}
        finally:
            fs.reset()
    return _state['d5_names']


def d5_name(char_id):
    return d5_names().get(int(char_id)) or str(char_id)


# ------------------------------------------------------------------------------------------- stat table
def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_table(raw, origin):
    """Numeric rows of the classic HD character table (header 8, stride 224); Character Forge layout ``d1hd``."""
    lay = TABLE_LAYOUT
    count = struct.unpack_from('<I', raw)[0]
    expected = lay['header'] + count * lay['stride']
    padding = (-expected) % 16
    if (not 0 < count <= 10000 or len(raw) not in (expected, expected + padding) or any(raw[expected:])
            or struct.unpack_from('<I', raw, 4)[0] != count):
        raise ValueError('Classic character table count/size mismatch')
    table_hash = sha(raw)
    out = []
    for i in range(count):
        offset = lay['header'] + i * lay['stride']
        row = raw[offset:offset + lay['stride']]
        native_base = struct.unpack_from('<8H', row, lay['base'])
        native_apt = row[lay['aptitudes']:lay['aptitudes'] + 8]
        name = row[:32].split(b'\0', 1)[0].decode('shift_jis', 'replace')
        out.append({
            'id': struct.unpack_from('<H', row, lay['identity'])[0],
            'name': unicodedata.normalize('NFKC', name).strip(),
            'base': [native_base[k] for k in ORDER],
            'growth': None,
            'aptitudes': [10 * native_apt[k] for k in ORDER],
            'evidence': {
                'source': 'd1hd', 'origin': str(origin), 'table_sha256': table_hash,
                'row_sha256': sha(row), 'row_index': i, 'row_offset': offset, 'row_stride': lay['stride'],
                'base_offset': lay['base'], 'aptitudes_offset': lay['aptitudes'], 'aptitude_scale': 10,
                'source_order': 'HP SP ATK DEF INT SPD HIT RES', 'confidence': 'static-correspondence'},
            'limitations': [
                'Independent per-stat growth fields and source level-up formula are not validated.',
                'Source values are static extraction evidence, not D5 native gameplay acceptance.']})
    return out


def table_rows():
    raw = src.hd_table()
    return parse_table(raw, src.LABEL + '::start.dat::43(char_e.dat)'), sha(raw)


TABLE_LABEL = src.LABEL + ' start.dat[43]'


# ------------------------------------------------------------------------------------------- class batch
def source_packet(spec, rows, table_sha, plan):
    first = spec['character_id']
    by_id = {r['id']: r for r in rows}
    from d5lib import d1cart
    manifest = {c['id']: c for c in d1cart.characters(art())}
    palettes = d1cart.body_info(art(), manifest[first]['body'])['palettes']
    ranks, bindings = [], []
    for k in range(6):
        row = by_id[first + k]
        # D1CRIG1: the rank title is the character table's TITLE column (1140-1145: Scout, Surveyor, Ranger,
        # Strider, Geo Master, Lord), not the name column ("Strider", "Strider 2" ...); a row with no title keeps
        # the name.
        source_row = src.character(row['id']) or {}
        ranks.append(dict(id=row['id'], name=spec['name'], title=(source_row.get('title') or row['name']),
                          base=row['base'], aptitudes=row['aptitudes'],
                          growth=None, evidence=row['evidence'], limitations=row['limitations']))
        palette = min(k, palettes - 1)
        bindings.append(dict(id=row['id'], body=manifest[first]['body'],
                             row_sha256=row['evidence']['row_sha256'], palette=palette))
    titles = [r['title'] for r in ranks]
    skills = plan['skills']
    if skills:
        third = ('Disgaea 1 Complete HD art; %d D1 abilities are mapped to D5 skills.' % len(skills))
    else:
        third = ('Disgaea 1 Complete HD art; none of this class\'s D1 abilities exists in D5 under '
                 'the same name, so they stay backlogged rather than being relabelled.')
    help_lines = [f"{spec['name']} (Disgaea 1 Complete) - {titles[0]} .. {titles[-1]}",
                  'Disgaea 1 has no Evilities; this class uses D5 Evilities and D5 skill mappings.',
                  third]
    return dict(game='d1c', edition=EDITION, name=spec['name'], ranks=ranks,
                rank_palette_bindings=bindings, help_lines=help_lines,
                source_table=dict(path=TABLE_LABEL, sha256=table_sha,
                                  layout='d1hd header 8, stride 224, base 106, aptitudes 84'))


def palette_banks(body):
    import numpy as np
    from d5lib import anm, d1cart
    data = anm.parse(d1cart.body_bytes(art(), body))
    banks = [anm.get_palette(data, i) for i in range(len(data.palettes))]
    while len(banks) < 10:
        banks.append(banks[0])
    return np.stack(banks[:10])


def prepare(spec, folder):
    from d5lib import d1cart
    ART = art()
    folder.mkdir(parents=True)
    library = folder / 'library'
    (library / 'bodies').mkdir(parents=True)
    entry = next(c for c in d1cart.characters(ART) if int(c['id']) == spec['character_id'])
    body = int(entry['body'])
    kind = spec['kind']
    # blank_frames='drop': Vampire's own table has one empty key (tag 1501 frame 5).
    sequences, receipt = d1cart.poses(ART, body, kind=kind, blank_frames='drop')
    bundles = {}
    origin = receipt['canvas']['distinct_origins'][0]
    for (row, view), images in sorted(sequences.items()):
        (folder / view).mkdir(exist_ok=True)
        for n, image in enumerate(images):
            name = f'{row}{n + 1:02d}'
            rel = f'{view}/{name}.png'
            image.save(folder / rel)
            bundles.setdefault(view, []).append(dict(name=name, png=rel, decoded_size=list(image.size),
                                                     pivot=dict(x=origin[0] / image.width,
                                                                y=1 - origin[1] / image.height)))
    manifest = dict(source='d1c', character_id=int(entry['id']), name=entry['name'],
                    title=entry.get('title', ''), palette=int(entry.get('palette', 0)),
                    body=body, kind=kind, body_sha256=receipt['body_sha256'],
                    bundles=[dict(label=k, sprites=v) for k, v in sorted(bundles.items())],
                    poses_missing={}, limitations=receipt['limitations'],
                    held_pose_rows=receipt['held_pose_rows'],
                    dropped_blank_frames=receipt.get('dropped_blank_frames', []),
                    source_read=receipt)
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    raw = d1cart.body_bytes(ART, body)
    digest = sha(raw)
    (library / 'bodies' / f'{digest}.bin').write_bytes(raw)
    info = d1cart.body_info(ART, body)
    (library / 'art-manifest.json').write_text(json.dumps(dict(
        format='character-forge-art/1', source='d1c',
        bodies={str(body): dict(sha256=digest, bytes=len(raw))},
        characters=[dict(id=int(entry['id']), name=entry['name'], body=body,
                         palette=int(entry.get('palette', 0)), palettes=info['palettes'],
                         body_kind=kind)],
        provenance=src.PROVENANCE), indent=2) + '\n')
    return manifest, receipt


def screen_art(folder, manifest):
    """Face and cut-in derived from the body's own standing drawing (no authored face exists)."""
    from PIL import Image
    stands = sorted((folder / 'front').glob('stand*.png')) or sorted((folder / 'front').glob('wait*.png'))
    with Image.open(stands[0]) as im:
        figure = im.convert('RGBA')
    bbox = figure.getchannel('A').getbbox()
    if bbox is None:
        raise ValueError('standing drawing is blank')
    left, top, right, bottom = bbox
    height = bottom - top
    face = figure.crop((left, top, right, top + max(1, int(height * 0.42))))
    face = face.crop(face.getchannel('A').getbbox())
    face_path = folder.parent / f"face_{manifest['character_id']}.png"
    face.save(face_path)
    cutin_path = folder.parent / f"cutin_{manifest['character_id']}.png"
    figure.save(cutin_path)
    return [str(face_path)], [str(cutin_path)]


def build_class(spec, rows, table_sha, plan, batch_dir):
    from d5lib import nativeimports, sprites
    work = batch_dir / 'build' / str(spec['registry'])
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    packet_dir = work / 'prepared'
    manifest, receipt = prepare(spec, packet_dir)
    source = source_packet(spec, rows, table_sha, plan)
    faces, cutins = screen_art(packet_dir, manifest)
    output = work / 'out'
    sprites.CACHE_DIR = str(output) + '.cache'
    result = nativeimports.build_entry(
        source=source, prepared_root=packet_dir, library_root=packet_dir / 'library',
        game_path=GAME, original_state=STATE, output_path=output,
        mod_id=f"D1C_Class_{spec['registry']}", target=spec['registry'],
        physical=spec['physical'], template=spec['template'], kind=spec['kind'],
        face_paths=faces, cutin_paths=cutins,
        source_palettes=palette_banks(manifest['body']),
        mods_roots=(), help_id=None, quest_id=None, quest_slot=None,
        # six source ranks are built, so all six are offered (a partial declaration leaves five
        # built rows unreachable and is refused by d5lib.classcheck R2)
        unlocked_ranks=len(source['ranks']),
        approximate_palettes=True, log=lambda *a: None,
        # The D4 one-donor-body-track rule also wins for D1 Complete monsters.
        whole_body=True,
        skills=plan['skills'])
    return dict(spec=spec, manifest=manifest, source=source,
                held=len(manifest['held_pose_rows']),
                dropped_blank_frames=manifest.get('dropped_blank_frames', []),
                result=result)


# ------------------------------------------------------------------------------------------- unique batch
def unique_source_packet(row, table_row, table_sha, skills):
    rank = dict(id=table_row['id'], name=row['name'], title=row['title'] or table_row['name'],
                base=table_row['base'], aptitudes=table_row['aptitudes'], growth=None,
                evidence=table_row['evidence'], limitations=table_row['limitations'])
    binding = dict(id=table_row['id'], body=int(row['body']),
                   row_sha256=table_row['evidence']['row_sha256'], palette=0)
    if skills:
        third = f"{len(skills)} D1 abilities use D5 same-effect skills."
    else:
        third = 'No D1 learn list; no D5 skills borrowed.'
    return dict(game='d1c', edition=EDITION, name=row['name'], ranks=[rank],
                rank_palette_bindings=[binding],
                help_lines=[f"{row['name']} - {row['title']} (Disgaea 1 Complete)",
                            'D1 has no Evilities: D5 ones are kept.', third],
                source_table=dict(path=TABLE_LABEL, sha256=table_sha,
                                  layout='d1hd header 8, stride 224, base 106, aptitudes 84'))


def needs_shared_actions(body):
    """True when the source body carries no animation for a receiver-required ordinary row (Carter, Fl:F.Angel)."""
    from d5lib import d1cart
    tags = set(d1cart.body_info(art(), int(body))['animation_ids'])
    have = {d1cart.MONSTER_ROWS.get(tag - 6 if tag % 10 == 7 else tag) for tag in tags}
    return not set(d1cart.REQUIRED_ROWS) <= have


def build_unique(row, identity, physical, table_row, table_sha, skill_doc, donor_doc, batch_dir, lease):
    import contextlib
    import os
    from d5lib import d1cart, nativeimports, sprites
    work = batch_dir / 'build' / str(row['id'])
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    packet_dir = work / 'prepared'
    spec = dict(character_id=int(row['id']), kind=donor_doc['kind'])
    body = int(row['body'])
    shared = donor_doc['kind'] == 'monster' and needs_shared_actions(body)
    with contextlib.ExitStack() as stack:
        if shared:
            stack.enter_context(d1cart.shared_fallback())
        manifest, receipt = prepare(spec, packet_dir)
    skills = [[int(s), int(l)] for s, l in skill_doc['skills']]
    source = unique_source_packet(row, table_row, table_sha, skills)
    faces, cutins = screen_art(packet_dir, manifest)
    output = work / 'out'
    sprites.CACHE_DIR = str(output) + '.cache'
    result = nativeimports.build_entry(
        source=source, prepared_root=packet_dir, library_root=packet_dir / 'library',
        game_path=GAME, original_state=STATE, output_path=output,
        mod_id=f"D1C_Unique_{row['id']}", target=identity,
        physical=physical, template=int(donor_doc['donor']), kind=donor_doc['kind'],
        face_paths=faces, cutin_paths=cutins,
        source_palettes=palette_banks(manifest['body']),
        mods_roots=(), help_id=lease[0], quest_id=lease[1], quest_slot=lease[2],
        unlocked_ranks=1, approximate_palettes=True, log=lambda *a: None,
        whole_body=True, skills=skills)
    return dict(spec=dict(identity=identity, registry=int(row['id']), character_id=int(row['id']),
                          physical=physical, shape=('low' if identity == physical else 'registry'),
                          template=int(donor_doc['donor']), template_name=donor_doc['donor_name'],
                          kind=donor_doc['kind'], name=row['name'], title=row['title'],
                          body=int(row['body']), shared_rows=receipt.get('shared_rows') or []),
                manifest=manifest, source=source, result=result)


# ------------------------------------------------------------------------------------------- donor probe
def source_stand_height(body, kind):
    from d5lib import d1cart
    sequences, receipt = d1cart.poses(art(), body, kind=kind, blank_frames='drop', shared_fallback=True)
    image = sequences[('stand', 'front')][0]
    box = image.getchannel('A').getbbox()
    return (box[3] - box[1]) if box else 0, receipt['body_sha256']


def donor_stand_height(fs, family):
    from d5lib import anm, sprites
    data = anm.parse(fs.read(sprites.sprite_vpath(fs, family, 'EN')))
    for bi, ai, anim in data.all_animations():
        if anim.id not in (1, 6001):
            continue
        times = anm.frame_times(data, (bi, ai))
        poses = [anm.evaluate(data, (bi, ai), t) for t in times]
        bounds = anm.item_bounds([item for pose in poses for item in pose])
        frames = [anm.render_items(data, pose, bounds=bounds, background=(0, 0, 0, 0))[0] for pose in poses]
        heights = sorted(b[3] - b[1] for f in frames if (b := f.getchannel('A').getbbox()))
        if heights:
            return heights[len(heights) // 2]
    return 0


def donor_for(row, heights, names, class_donor):
    """The measured donor decision for one listing (same rule probe_donors.main used)."""
    body = int(row['body'])
    kind = 'monster' if row['shape'] == 'monster' else 'humanoid'
    src_h, body_sha = source_stand_height(body, kind)
    if body in class_donor:
        donor, donor_name, from_class = class_donor[body]
        basis = 'class'
    else:
        pool = MONSTER_DONORS if kind == 'monster' else HUMANOID_DONORS
        scored = [(abs((src_h / heights[f]) - 1.0), f) for f in pool if heights.get(f)]
        scored.sort()
        _, donor = scored[0]
        donor_name = names.get(donor) or str(donor)
        basis = 'measured'
    d_h = heights.get(donor)
    return dict(id=int(row['id']), name=row['name'], title=row['title'], body=body,
                shape=row['shape'], kind=kind, body_sha256=body_sha,
                source_stand_height=src_h, donor=donor, donor_name=donor_name,
                donor_stand_height=d_h,
                height_ratio=round(src_h / d_h, 3) if d_h else None, donor_basis=basis)
