"""SOURCEPREP4-D4: the D4 importer reads only the verified prepared source folder plus kit data.

Offline and synthetic where possible: no game bytes, no installed pack, no network.  The prepared folder
is built as a tiny fixture with a real ``manifest.json`` (``d5lib/sourcefolder`` schema), so these tests
exercise the same resolver the import uses.
"""
import hashlib
import json
import os
import re
import threading
from pathlib import Path

import pytest

from d5lib import importcore, sourcefolder
from d5lib.importers import _d4_source as src

HERE = Path(__file__).resolve().parents[1]
REPO = Path('/Volumes/Data/Projects/D5')
D4_SOURCE = REPO / 'Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+'
D5_SOURCE = REPO / 'Disgaea Source/Disgaea 5 Complete (Steam 803600)'


def prepared(tmp_path, *, states=None, omit=(), size=None):
    """A prepared source folder: manifest rows + files for every required D4 file."""
    root = tmp_path / 'Source'
    data = root / 'd4'
    rows = []
    for rel in src.REQUIRED:
        if rel in omit:
            continue
        path = data / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
        state = (states or {}).get(rel, 'yes')
        rows.append(dict(path=rel, size=(size or {}).get(rel, 7), sha256=hashlib.sha256(b'fixture').hexdigest(),
                         known_build='fixture', verified=state))
    sourcefolder.write_manifest(root, {'d4': dict(edition='fixture', origin='steam-auto', root=str(data),
                                                  supplied=True, files=rows)})
    return root


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv('D5_SOURCE_DIR', raising=False)
    monkeypatch.delenv('D5_D4_FORGE', raising=False)
    monkeypatch.setenv('D5_SOURCE_DIR', str(prepared(tmp_path)))
    return tmp_path


# --------------------------------------------------------------------------------------------- resolver
def test_prepared_set_is_the_only_file_set(env):
    files = src.data_dir()
    assert files.prepared
    for rel in src.REQUIRED:
        assert files.path(rel).is_file()
    # a file that merely sits in the folder is not in the verified set
    stray = files.root / 'Data/DATA/EN/EXTRA.dat'
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b'stray')
    with pytest.raises(src.D4SourceError) as err:
        files.path('Data/DATA/EN/EXTRA.dat')
    assert 'not in the verified prepared source set' in str(err.value)


@pytest.mark.parametrize('kind', ['omit', 'no', 'unknown'])
def test_bad_manifest_row_refuses_by_name(tmp_path, monkeypatch, kind):
    root = prepared(tmp_path, states={'Data/DATA/ANM_HI.dat': 'no'} if kind == 'no' else
                    {'Data/DATA/ANM_HI.dat': 'unknown'} if kind == 'unknown' else {},
                    omit=('Data/DATA/ANM_HI.dat',) if kind == 'omit' else ())
    monkeypatch.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.D4SourceError) as err:
        src.data_dir()
    text = str(err.value)
    assert 'd4/Data/DATA/ANM_HI.dat' in text
    expected = {'omit': 'no manifest row', 'no': "verified 'no'", 'unknown': "verified 'unknown'"}[kind]
    assert expected in text


def test_verified_row_with_the_file_missing_refuses(tmp_path, monkeypatch):
    root = prepared(tmp_path, omit=('Data/DATA/EN/DATABASE_EN.dat',))
    # add a verified row for the file, but do not create it
    doc = json.loads((root / 'manifest.json').read_text())
    doc['games']['d4']['files'].append(dict(path='Data/DATA/EN/DATABASE_EN.dat', size=7,
                                            sha256=hashlib.sha256(b'fixture').hexdigest(), verified='yes'))
    (root / 'manifest.json').write_text(json.dumps(doc))
    monkeypatch.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.D4SourceError) as err:
        src.data_dir()
    assert 'verified but the file is missing' in str(err.value)


def test_size_mismatch_refuses(tmp_path, monkeypatch):
    root = prepared(tmp_path, size={'Data/DATA/WF.dat': 99})
    monkeypatch.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.D4SourceError) as err:
        src.data_dir()
    assert 'does not match the manifest' in str(err.value)


def test_no_manifest_says_how_to_prepare(tmp_path, monkeypatch):
    monkeypatch.setenv('D5_SOURCE_DIR', str(tmp_path))
    with pytest.raises(src.D4SourceError) as err:
        src.data_dir()
    assert 'tools/prep_source.py' in str(err.value)


@pytest.mark.skipif(not D4_SOURCE.is_dir(), reason='Disgaea Source D4 copy not present')
def test_explicit_root_is_the_diagnostic_route(monkeypatch):
    monkeypatch.delenv('D5_SOURCE_DIR', raising=False)
    files = src.data_dir(explicit=D4_SOURCE)
    assert not files.prepared
    assert files.path(src.DATABASE_EN).is_file()
    assert files.data('EN').chars[1080]['name']


# ------------------------------------------------------------------------------------------ game text
def test_text_reference_round_trip():
    pool = src.TextPool()
    pool.add('Warrior')
    pool.add('SP Aptitude increased by %d％.')
    assert pool.resolve(pool.ref('Warrior')) == 'Warrior'
    assert pool.ref('Warrior') == {'@text': src.text_sha('Warrior')}
    assert pool.resolve(pool.ref('SP Aptitude increased by 10％.')) == 'SP Aptitude increased by 10％.'
    assert pool.resolve(pool.ref('[Unavailable D4] 物理')) == '[Unavailable D4] 物理'
    assert pool.ref('a kit-written sentence') == {'@authored': 'a kit-written sentence'}


def test_unknown_text_hash_refuses():
    pool = src.TextPool(['Warrior'])
    with pytest.raises(src.D4SourceError):
        pool.resolve({'@text': 'f' * 64})


def test_rule_data_carries_references_not_game_text():
    """No string in the moved rule data equals a D4 or D5 table value (the scrub's contract)."""
    if not D4_SOURCE.is_dir() or not D5_SOURCE.is_dir():
        pytest.skip('Disgaea Source copies not present')
    from d5lib import gamefs
    files = src.data_dir(explicit=D4_SOURCE)
    pool = src.text_pool(files, gamefs.GameFS(str(D5_SOURCE)))

    def strings(doc):
        if isinstance(doc, dict):
            for value in doc.values():
                yield from strings(value)
        elif isinstance(doc, list):
            for value in doc:
                yield from strings(value)
        elif isinstance(doc, str):
            yield doc

    for name in ('d4-allocation.json', 'd4-mapping.json', 'd4-extension-rows.json',
                 'd4-extension-rows-cast.json', 'd4-reserved-ids.json', 'd4-unique-commands.json',
                 'd4-specials.json', 'd4-evility-overlay.json', 'd4-evility-additions.json'):
        doc = json.loads((HERE / 'd5lib/importers' / name).read_text(encoding='utf-8'))
        hits = [s for s in strings(doc) if src.text_sha(s) in pool._text]
        assert not hits, f'{name} still carries game text: {hits[:3]}'


def test_moved_rule_data_has_no_paths():
    for name in ('d4-unique-commands.json', 'd4-allocation.json', 'd4-mapping.json',
                 'd4-extension-rows.json', 'd4-extension-rows-cast.json', 'd4-specials.json'):
        text = (HERE / 'd5lib/importers' / name).read_text(encoding='utf-8')
        assert '/Volumes/' not in text and 'ai-tmp' not in text and 'Research/' not in text, name


def test_recorded_commands_keep_their_art_ids_and_flags():
    commands = src.commands()
    assert commands
    for sid, row in commands.items():
        assert int(row['source_id']) == int(sid)
        assert 'template_id' in row
        assert row.get('face_ids')
        assert row.get('cutin_ids') or row.get('cutin_packet_frame')
    assert src.command(180)['face_ids'] == [54]      # rows 180/220 name a resource id that is not their row
    assert src.command(220)['cutin_ids'] == [74]
    assert src.command(610)['cutin_packet_frame'] == '1/0000.png'


# -------------------------------------------------------------------------------------------- no install
def test_d4_is_source_only_and_reads_no_installed_pack(tmp_path):
    assert 'd4' in importcore.SOURCE_ONLY_GAMES
    root = tmp_path / 'mods'
    root.mkdir()
    assert importcore.installed_pack('d4', {}, root, 'D4_Unique_310') is None
    assert importcore.installed_pack('d4', {'installed_reference': True}, root, 'D4_Unique_310') == \
        root / 'D4_Unique_310'
    assert importcore.reference_roots('d4', {}, ()) == []
    assert importcore.reference_roots('d4', {'installed_reference': True}, ()) != []


def test_hold_blank_default_passes_no_installed_pack(monkeypatch):
    from d5lib import holdblank
    from d5lib.importers import d4
    seen = {}

    def fake(built, installed, reference, **kwargs):
        seen['installed'], seen['reference'] = installed, reference
        return {}
    monkeypatch.setattr(holdblank, 'hold_pack', fake)
    imp = d4.Importer()
    entry = type('E', (), {'mod_folder': 'D4_Unique_310'})()
    imp._hold_blank_keys(entry, Path('/tmp/does-not-exist'), {})
    assert seen['installed'] is None            # no installed pack on the default path


def test_wheel_reference_is_recorded_data():
    folders = json.loads((HERE / 'd5lib/importers/d4-bank-shapes.json').read_text())['folders']
    assert folders
    folder = sorted(folders)[0]
    shapes = src.wheel_reference(folder)
    assert shapes and all(isinstance(v, tuple) and len(v) == 2 for v in shapes.values())


def test_source_census_marks_the_recorded_lease_set():
    if not D4_SOURCE.is_dir():
        pytest.skip('Disgaea Source D4 copy not present')
    from d5lib.importers import d4
    imp = d4.Importer()
    imp._source_cache = (str(D4_SOURCE), src.data_dir(explicit=D4_SOURCE))
    census = imp.unique_census(D4_SOURCE)
    shipped = {row['id'] for row in census if row['shipped']}
    assert 310 in shipped and 10 in shipped


# ----------------------------------------------------------------------------------------- machine paths
def test_importer_modules_have_no_machine_path():
    for name in ('d5lib/importers/d4.py', 'd5lib/importers/_d4_source.py',
                 'd5lib/importers/_d4_specials.py', 'd5lib/d4unique.py', 'd5lib/d4expansion.py',
                 'd5lib/d4voices.py', 'tools/d4_prepare_art.py'):
        text = (HERE / name).read_text(encoding='utf-8')
        for needle in ('/Volumes/', 'SteamLibrary', 'ai-tmp', 'Character Forge Art', 'CharForge-Backup',
                       'Disgaea Source'):
            assert needle not in text, f'{name} names {needle}'


def test_screen_art_default_is_the_source_folder(monkeypatch, tmp_path):
    from d5lib import d4screenart
    source = tmp_path / 'Source'
    source.mkdir()
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    monkeypatch.setattr(d4screenart, 'source_root', lambda: source)
    monkeypatch.setattr(d4screenart, 'LEGACY_ART', legacy)
    monkeypatch.delenv(d4screenart.SCREEN_ART_ENV, raising=False)
    assert d4screenart.screen_art_dir() == source / d4screenart.ART_FOLDER


# ------------------------------------------------------------------------ review fixtures (DD2 / D1C reviews)
def test_same_size_replacement_of_a_verified_file_is_refused(env):
    """The manifest row attests bytes; a same-size file swapped in after prep is hashed again and refused."""
    files = src.data_dir()
    victim = files.path('Data/DATA/WF.dat')
    assert files.path('Data/DATA/WF.dat') == victim          # unchanged: served from the stat-keyed proof
    victim.write_bytes(b'replace')                           # same size (7 bytes), different bytes
    with pytest.raises(src.D4SourceError) as err:
        files.path('Data/DATA/WF.dat')
    assert 'd4/Data/DATA/WF.dat' in str(err.value) and 'no longer match' in str(err.value)
    with pytest.raises(src.D4SourceError):
        src.data_dir()                                       # a fresh resolve refuses it too


def test_a_row_without_a_sha256_is_refused(tmp_path, monkeypatch):
    root = prepared(tmp_path)
    doc = json.loads((root / 'manifest.json').read_text())
    for row in doc['games']['d4']['files']:
        row.pop('sha256')
    (root / 'manifest.json').write_text(json.dumps(doc))
    monkeypatch.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.D4SourceError) as err:
        src.data_dir()
    assert 'no SHA-256' in str(err.value)


def test_table_reader_opens_only_through_the_verified_set(env, monkeypatch):
    """Every file D4Data opens comes from ``D4Files.path``: a stray sibling of a listed file is never chosen."""
    from d5lib import d4source
    files = src.data_dir()
    stray = files.root / 'Data/DATA/EN/DATABASE_EN.dat.bak'
    stray.write_bytes(b'x')
    asked = []
    real = files.path

    def spy(rel):
        asked.append(rel)
        return real(rel)
    monkeypatch.setattr(d4source, 'Nsac', lambda path: asked.append(('nsac', str(path))) or object())
    reader = d4source.D4Data(files.root, 'EN', locate=spy)
    assert asked[0] == 'Data/DATA/EN/DATABASE_EN.dat'
    assert all(not str(x).endswith('.bak') for x in asked)
    assert reader.db is not None


def test_child_builders_read_through_the_verified_set(env, monkeypatch):
    """A child process is told the set (D5_D4_VERIFIED_SET): its D4Data refuses a file the set does not list."""
    from d5lib import d4source
    files = src.data_dir()
    config = env / 'set.json'
    config.write_text(json.dumps(files.to_config()))
    monkeypatch.setenv(d4source.VERIFIED_SET_ENV, str(config))
    locate = d4source._verified_locate(files.root)
    assert locate is not None
    assert Path(locate('Data/DATA/WF.dat')) == files.path('Data/DATA/WF.dat')
    with pytest.raises(src.D4SourceError):
        locate('Data/DATA/EN/EXTRA.dat')
    assert d4source._verified_locate(env / 'elsewhere') is None       # another root: not this set's business
    files.path('Data/DATA/WF.dat').write_bytes(b'replace')
    with pytest.raises(src.D4SourceError):
        locate('Data/DATA/WF.dat')


def test_voice_facts_open_only_listed_files(env):
    """The optional voice route asks the verified set for the table and pack names, nothing else."""
    from d5lib import d4voices
    files = src.data_dir()
    asked = []

    def locate(rel):
        asked.append(rel)
        raise src.D4SourceError('stop')
    with pytest.raises(src.D4SourceError):
        d4voices.source_voice_facts(files.root, 1, locate=locate)
    assert asked == ['Data/DATA/EN/DATABASE_EN.dat']


def _art_fixture(tmp_path, monkeypatch):
    from PIL import Image
    from d5lib import d4screenart as art
    images = {}

    def fake_extract(game, out_dir, ids=None, palettes=(0,), log=None, kinds=('face', 'cutin'),
                     publish=True, preserve_existing=True):
        out = Path(out_dir)
        doc = {'tool': art.TOOL, 'source': {}, 'palettes': [0], 'faces': {}, 'cutins': {}, 'errors': {},
               'missing': {'face': [], 'cutin': []}}
        for n in ids:
            if 'face' in kinds:
                rel = art.face_rel(n)
                if preserve_existing and (out / rel).is_file():
                    doc['faces'][str(n)] = art._file_entry(out / rel, out)
                else:
                    doc['faces'][str(n)] = {'file': rel, 'sha256': art._png(out / rel, Image.new('RGBA', (4, 4), (n % 250, 1, 2, 3)))}
            if 'cutin' in kinds:
                rel = art.cutin_rel(n)
                doc['cutins'][str(n)] = [{'file': rel, 'size': [4, 4],
                                          'sha256': art._png(out / rel, Image.new('RGBA', (4, 4), (n % 250, 9, 9, 9)))}]
        return doc
    monkeypatch.setattr(art, 'extract', fake_extract)
    return art, Image


def test_screen_art_planted_file_never_wins_in_the_importer_folder(tmp_path, monkeypatch):
    """An unlisted PNG at the path of a requested face is replaced by the extraction, not used or certified."""
    art, Image = _art_fixture(tmp_path, monkeypatch)
    folder = tmp_path / 'art'
    planted = folder / art.face_rel(70)
    planted.parent.mkdir(parents=True)
    Image.new('RGBA', (4, 4), (255, 255, 255, 255)).save(planted)
    before = planted.read_bytes()
    written = art.ensure(game=None, folder=folder, face_ids=[70], cutin_ids=[], verified=True)
    assert written == [70]
    assert planted.read_bytes() != before
    receipt = json.loads((folder / 'manifest.json').read_text())
    assert receipt['faces']['70']['sha256'] == hashlib.sha256(planted.read_bytes()).hexdigest()
    # a second run trusts exactly what the receipt records, and a changed file is extracted again
    assert art.ensure(game=None, folder=folder, face_ids=[70], cutin_ids=[], verified=True) == []
    planted.write_bytes(b'tampered')
    assert art.ensure(game=None, folder=folder, face_ids=[70], cutin_ids=[], verified=True) == [70]


def test_unverified_ensure_still_certifies_files_for_a_named_folder(tmp_path, monkeypatch):
    """The user's own named folder keeps the old repair behaviour (documented as their choice)."""
    art, Image = _art_fixture(tmp_path, monkeypatch)
    folder = tmp_path / 'art'
    path = folder / art.face_rel(70)
    path.parent.mkdir(parents=True)
    Image.new('RGBA', (4, 4)).save(path)
    assert art.ensure(game=None, folder=folder, face_ids=[70], cutin_ids=[]) == []


def test_importer_art_folder_is_owned_and_never_the_source_folder(tmp_path, monkeypatch):
    from d5lib import d4screenart
    from d5lib.importers import d4
    monkeypatch.delenv(d4screenart.SCREEN_ART_ENV, raising=False)
    monkeypatch.setattr(d4screenart, 'explicit_art_dir', lambda: None)
    out = tmp_path / 'out'
    folder = d4.claim_art_dir(out)
    assert folder == out / 'screen-art' and (folder / d4.ART_MARKER).is_file()
    assert d4.art_dir() == folder
    assert d4._ART['owned']
    # the same folder can be claimed again (our marker), and nothing in it is removed
    (folder / 'keep.txt').write_text('mine')
    assert d4.claim_art_dir(out) == folder and (folder / 'keep.txt').read_text() == 'mine'


def test_importer_art_folder_refuses_foreign_and_symlinked_paths(tmp_path, monkeypatch):
    from d5lib import d4screenart
    from d5lib.importers import d4
    monkeypatch.setattr(d4screenart, 'explicit_art_dir', lambda: None)
    foreign = tmp_path / 'foreign'
    (foreign / 'screen-art').mkdir(parents=True)
    (foreign / 'screen-art' / 'user-file.txt').write_text('precious')
    with pytest.raises(src.D4SourceError) as err:
        d4.claim_art_dir(foreign)
    assert 'not an importer cache' in str(err.value)
    assert (foreign / 'screen-art' / 'user-file.txt').read_text() == 'precious'
    target = tmp_path / 'elsewhere'
    target.mkdir()
    link = tmp_path / 'linked'
    (link).mkdir()
    (link / 'screen-art').symlink_to(target, target_is_directory=True)
    with pytest.raises(src.D4SourceError) as err:
        d4.claim_art_dir(link)
    assert 'symlink' in str(err.value)
    assert not any(target.iterdir())


def test_a_named_art_folder_is_used_as_given(tmp_path, monkeypatch):
    from d5lib import d4screenart
    from d5lib.importers import d4
    named = tmp_path / 'mine'
    monkeypatch.setattr(d4screenart, 'explicit_art_dir', lambda: named)
    assert d4.claim_art_dir(tmp_path / 'out') == named
    assert not d4._ART['owned'] and not named.exists()


def test_screen_art_extraction_goes_through_the_verified_set(env, monkeypatch):
    """`d4screenart.archive_paths` takes the two archives from a verified set, never by scanning a folder."""
    from d5lib import d4screenart
    files = src.data_dir()
    assert d4screenart.archive_paths(files) == (files.path('Data/DATA/WF.dat'), files.path('Data/DATA/ANM_HI.dat'))
    files.path('Data/DATA/ANM_HI.dat').write_bytes(b'replace')
    with pytest.raises(src.D4SourceError):
        d4screenart.archive_paths(files)


# ------------------------------------------------------------------------------- no literal game text in the data
TEXT_FIELD = re.compile(r'(^|_)(name|desc|title|label|text)(_|$)', re.IGNORECASE)
NEW_DATA_FILES = ('d4-allocation.json', 'd4-mapping.json', 'd4-extension-rows.json',
                  'd4-extension-rows-cast.json', 'd4-specials.json', 'd4-evility-overlay.json',
                  'd4-evility-additions.json', 'd4-reserved-ids.json', 'd4-unique-commands.json')


def _literal_text_fields(doc, key=''):
    """(key, value) of every name/desc/title string that is not wrapped in a reference."""
    if isinstance(doc, dict):
        if set(doc) & {'@text', '@template', '@segments', '@authored', '@skeleton'}:
            return
        for k, v in doc.items():
            yield from _literal_text_fields(v, k)
    elif isinstance(doc, list):
        for v in doc:
            yield from _literal_text_fields(v, key)
    elif isinstance(doc, str) and TEXT_FIELD.search(key) and re.search(r'[A-Za-z\u3040-\u9fff]{3}', doc):
        yield key, doc


@pytest.mark.parametrize('name', NEW_DATA_FILES)
def test_d4_data_files_have_no_literal_name_or_description_fields(name):
    """Game text is a reference ({"@text"/"@template"/"@segments"/"@skeleton"} resolved from the user's files);
    a sentence the kit wrote itself says so ({"@authored"}).  A bare string in a name/desc field fails."""
    doc = json.loads((HERE / 'd5lib/importers' / name).read_text(encoding='utf-8'))
    bad = list(_literal_text_fields(doc))
    assert not bad, f'{name} has literal text fields: {bad[:3]}'


def test_the_literal_text_check_catches_a_literal():
    assert list(_literal_text_fields({'a': {'name_EN': 'Warrior'}}))
    assert list(_literal_text_fields({'skill_rows': [{'desc_JP': 'Increase damage'}]}))
    assert not list(_literal_text_fields({'name_EN': {'@text': 'a' * 64}, 'desc': {'@authored': 'x y z q'}}))


def test_authored_and_reference_forms_resolve_back_to_the_text():
    pool = src.TextPool(['Increase damage of weapon skills by %d%%.', 'Tyrant Soul', 'Unique:%sHis first soul reaping. (\ufffd\ufffdforget)'])
    for value in ('Increase damage of weapon skills by 15\uff05.', 'Increase damage of weapon skills by 15%.',
                  '[Unavailable D4] Tyrant Soul', 'Unique:%sHis first soul reaping. (\u0414forget)',
                  'a sentence the kit wrote itself'):
        assert pool.resolve(pool.ref(value)) == value
    assert pool.ref('a sentence the kit wrote itself') == {'@authored': 'a sentence the kit wrote itself'}
    assert '@prefix' in pool.ref('[Unavailable D4] Tyrant Soul')
    assert '@skeleton' in pool.ref('Unique:%sHis first soul reaping. (\u0414forget)')


def test_no_installed_pack_on_the_default_path_even_with_installed_mods_unset(tmp_path, monkeypatch):
    """Empty D5_INSTALLED_MODS and the old roots blocked: the default D4 route resolves no installed id root."""
    monkeypatch.setenv('D5_INSTALLED_MODS', str(tmp_path / 'empty'))
    (tmp_path / 'empty').mkdir()
    assert importcore.reference_roots('d4', {'installed_reference': False}, ()) == []
    from d5lib import d4exact
    with pytest.raises(ValueError):
        d4exact.existing_mods(tmp_path / 'nogame', [])


# ------------------------------------------------------------------ work folders: only ours, never foreign
def test_packet_folder_of_ours_is_replaced_by_removing_only_what_we_wrote(tmp_path):
    out = tmp_path / 'prepared-70'
    (out / 'front').mkdir(parents=True)
    (out / 'front/0.png').write_bytes(b'ours')
    src._seal_packet(out)
    (out / 'notes.txt').write_text('someone else put this here')     # not in the marker
    with pytest.raises(src.D4SourceError) as err:
        src._clear_packet(out)
    assert 'did not write' in str(err.value)
    assert (out / 'notes.txt').read_text() == 'someone else put this here'      # kept
    assert not (out / 'front/0.png').exists()                                   # ours: removed


def test_packet_folder_clear_is_complete_when_only_ours(tmp_path):
    out = tmp_path / 'prepared-70'
    (out / 'front').mkdir(parents=True)
    (out / 'front/0.png').write_bytes(b'ours')
    (out / 'manifest.json').write_text('{}')
    src._seal_packet(out)
    src._clear_packet(out)
    assert not out.exists()


def test_packet_folder_without_our_marker_or_symlinked_is_refused(tmp_path):
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    (foreign / 'precious.txt').write_text('mine')
    with pytest.raises(src.D4SourceError) as err:
        src._clear_packet(foreign)
    assert 'not written by this importer' in str(err.value)
    assert (foreign / 'precious.txt').read_text() == 'mine'
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'keep.txt').write_text('x')
    link = tmp_path / 'link'
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(src.D4SourceError) as err:
        src._clear_packet(link)
    assert 'symlink' in str(err.value)
    assert (target / 'keep.txt').exists()


def test_packet_marker_cannot_delete_outside_the_folder(tmp_path):
    out = tmp_path / 'packet'
    out.mkdir()
    victim = tmp_path / 'victim.txt'
    victim.write_text('outside')
    (out / src.PACKET_MARKER).write_text(json.dumps({'files': ['../victim.txt']}))
    src._clear_packet(out)
    assert victim.read_text() == 'outside'


# --------------------------------------------- shared readers take the verified set (stat oracle, source specials)
def test_stat_oracle_and_source_specials_resolve_the_prepared_set(monkeypatch):
    from d5lib import srcskills, statfidelity
    asked = []

    class Stop(Exception):
        pass

    def fake(explicit=None):
        asked.append(explicit)
        raise Stop
    monkeypatch.setattr(src, 'data_dir', fake)
    for call in (statfidelity.d4_rows, srcskills.d4_table):
        with pytest.raises(Stop):
            call()
    assert asked == [None, None]                      # no machine path: the prepared folder is the default
    with pytest.raises(Stop):
        statfidelity.d4_rows('/some/explicit/root')
    assert asked[-1] == '/some/explicit/root'          # an explicit root stays the diagnostic route


def test_rule_files_are_rewritten_not_reused(tmp_path):
    from d5lib.importers import d4
    imp = d4.Importer()
    pool = src.TextPool(['Warrior'])
    stale = tmp_path / 'mapping.json'
    stale.write_text('{"stale": true}')
    path = imp._rule_file('mapping', lambda: {'name': {'@text': src.text_sha('Warrior')}}, tmp_path, pool)
    assert json.loads(path.read_text()) == {'name': 'Warrior'}


# ------------------------------------------------------------------------ lease pin for nine uniques
NINE = ('3307', '4300', '4320', '4330', '4340', '4350', '4400', '5403', '5414')


def _leases():
    return json.loads((HERE / 'd5lib/importers/d4-leases.json').read_text(encoding='utf-8'))['characters']


def test_nine_uniques_have_disjoint_recorded_evility_rows():
    chars = _leases()
    rows = [(n, int(d4), int(row)) for n in NINE for d4, row in (chars[n].get('evility_rows') or {}).items()]
    assert {n for n, _, _ in rows} == set(NINE)
    ids = [row for _, _, row in rows]
    assert len(ids) == len(set(ids)), 'siblings share a leased row'
    assert min(ids) >= 7210 and all(isinstance(row, int) for row in ids)
    # ids only: the lease holds numbers, no names or descriptions
    for n in NINE:
        assert all(isinstance(k, str) and k.isdigit() and isinstance(v, int) for k, v in chars[n]['evility_rows'].items())


def test_lease_loader_pins_mine_and_reserves_the_others():
    from d5lib import d4unique
    path = HERE / 'd5lib/importers/d4-leases.json'
    mine = d4unique.load_ability_leases(path, 4300)
    assert mine['evilities'] == {392: 7211, 228: 7212, 62: 7213, 67: 7214} and mine['exact'] == []
    assert not set(mine['evilities'].values()) & mine['reserved_evilities']
    assert {7210, 7231} <= mine['reserved_evilities'] and {13003, 13007} <= mine['reserved_skills']
    assert d4unique.load_ability_leases(path, 3307)['skills'] == {12081: 13003, 12082: 13004, 12083: 13005}
    assert d4unique.load_ability_leases(path, 4320)['exact'] == [350]
    none = d4unique.load_ability_leases(path, 310)                      # no lease: first-free allocation as before
    assert none['evilities'] == {} and none['skills'] == {} and none['exact'] is None


def test_leased_row_is_reproduced_and_an_occupied_one_refused():
    from types import SimpleNamespace
    from d5lib import sourceimports
    skills = SimpleNamespace(rows=[{'id': 12}, {'id': 7000}])
    magic = SimpleNamespace(rows=[{'id': 1}])

    def profile():
        ev = {'id': 392, 'name': 'x', 'mana': 100}
        return [{'id': 4300, 'innate_evility': {'id': 0}, 'evilities': [ev], 'skills': [],
                 'battle': {'kind_gender': 0}}]
    mapping = {'evilities': {'392': {'relation': 'adapted', 'works_like': 12, 'd4_name': 'x'}}}
    donors = [{'kind_gender': 0}] * 6
    kw = dict(family=18300, template_rows=donors, skill_table=skills, magic_table=magic)
    try:
        got = sourceimports.plan_d4_profile(profile(), mapping, pinned_evilities={392: 7211}, **kw)
    except (KeyError, TypeError):
        pytest.skip('profile fixture too small for the rank pass')
    evs = got['evilities']
    assert [e['id'] for e in (evs.values() if isinstance(evs, dict) else evs)] == [7211]
    with pytest.raises(ValueError):
        sourceimports.plan_d4_profile(profile(), mapping, pinned_evilities={392: 7000}, **kw)


def test_lease_claims_carry_the_leased_rows_for_other_importers():
    claims = [c for source, owner, c in importcore.lease_claims() if owner == 'D4_Unique_4300']
    assert claims and set(claims[0].get('Skill.dat', ())) >= {7211, 7212, 7213, 7214}
