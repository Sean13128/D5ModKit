"""SOURCEPREP4-D1C: the Disgaea 1 Complete importer reads only the prepared source folder plus kit data.

Offline and synthetic: no game bytes, no installed pack, no network.  The prepared folder is a tiny fixture with
a real ``manifest.json`` (``d5lib/sourcefolder`` schema), so the tests exercise the resolver the import uses.
"""
import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

from d5lib import importcore, sourcefolder
from d5lib.importers import _d1c_batch, _d1c_source as src, d1c

HERE = Path(__file__).resolve().parents[1]
REL = src.REL
FIXTURE_SHA = hashlib.sha256(b'fixture').hexdigest()


def prepared(tmp_path, *, state='yes', omit=False, size=7, write=True, extra=()):
    root = tmp_path / 'Source'
    folder = root / 'd1c' / 'data'
    folder.mkdir(parents=True)
    if write:
        (folder / 'SUBDATA.DAT').write_bytes(b'fixture')
    for name in extra:
        (folder / name).write_bytes(b'unlisted')
    rows = [] if omit else [dict(path=REL, size=size, sha256=FIXTURE_SHA, known_build='fixture', verified=state)]
    sourcefolder.write_manifest(root, {'d1c': dict(edition='fixture', origin='user-dump', supplied=True, files=rows)})
    return root


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv('D5_SOURCE_DIR', raising=False)
    monkeypatch.setattr('d5lib.paths.kit_setting', lambda *_a, **_k: None)
    return monkeypatch


def test_data_uses_the_prepared_folder(env, tmp_path):
    root = prepared(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    data = src.data()
    assert data.subdata == root / 'd1c' / REL and data.prepared and data.sha256 == FIXTURE_SHA


def test_missing_manifest_says_how_to_prepare(env, tmp_path):
    env.setenv('D5_SOURCE_DIR', str(tmp_path / 'nothing'))
    with pytest.raises(src.D1cSourceError, match=r'manifest\.json.*prep_source\.py --d1c'):
        src.data()


def test_missing_manifest_row_names_the_file(env, tmp_path):
    env.setenv('D5_SOURCE_DIR', str(prepared(tmp_path, omit=True)))
    with pytest.raises(src.D1cSourceError, match=r'no Disgaea 1 Complete files'):
        src.data()
    # a manifest that lists d1c but not SUBDATA.DAT
    root = prepared(tmp_path / 'b', omit=True)
    sourcefolder.write_manifest(root, {'d1c': dict(supplied=True, files=[dict(path='data/OTHER.DAT', verified='yes')])})
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.D1cSourceError, match=r'd1c/data/SUBDATA\.DAT: no manifest row'):
        src.data()


def test_an_unverified_row_is_refused_with_its_state(env, tmp_path):
    env.setenv('D5_SOURCE_DIR', str(prepared(tmp_path, state='no')))
    with pytest.raises(src.D1cSourceError, match=r"d1c/data/SUBDATA\.DAT: manifest says verified 'no'"):
        src.data()
    env.setenv('D5_SOURCE_DIR', str(prepared(tmp_path / 'u', state='unknown')))
    with pytest.raises(src.D1cSourceError, match=r"verified 'unknown'"):
        src.data()


def test_a_verified_row_with_no_file_is_refused(env, tmp_path):
    env.setenv('D5_SOURCE_DIR', str(prepared(tmp_path, write=False)))
    with pytest.raises(src.D1cSourceError, match=r'listed as verified but the file is missing'):
        src.data()


def test_a_size_mismatch_is_refused(env, tmp_path):
    env.setenv('D5_SOURCE_DIR', str(prepared(tmp_path, size=999)))
    with pytest.raises(src.D1cSourceError, match=r'size 7 differs from the manifest \(999\)'):
        src.data()


def test_an_unlisted_file_in_the_folder_is_never_the_input(env, tmp_path):
    """A file merely present beside the verified one (here two stray archives) cannot become the input."""
    root = prepared(tmp_path, extra=('SUBDATA.DAT.bak', 'zz_other.DAT'))
    env.setenv('D5_SOURCE_DIR', str(root))
    data = src.data()
    assert data.subdata.name == 'SUBDATA.DAT' and data.subdata.read_bytes() == b'fixture'
    for rel in ('data/SUBDATA.DAT.bak', 'data/zz_other.DAT', 'data/start.dat'):
        with pytest.raises(src.D1cSourceError, match='not in the verified set'):
            data.path(rel)
    # and with no verified row the folder's own SUBDATA.DAT is still refused
    env.setenv('D5_SOURCE_DIR', str(prepared(tmp_path / 'c', omit=True, extra=('x',))))
    with pytest.raises(src.D1cSourceError):
        src.data()


def test_explicit_root_is_an_unverified_diagnostic(tmp_path):
    folder = tmp_path / 'romfs' / 'data'
    folder.mkdir(parents=True)
    (folder / 'SUBDATA.DAT').write_bytes(b'x')
    data = src.data(tmp_path / 'romfs')
    assert not data.prepared and data.sha256 is None
    with pytest.raises(src.D1cSourceError, match='No data/SUBDATA.DAT'):
        src.data(tmp_path / 'empty')


def test_the_reader_opens_only_the_verified_path(env, tmp_path):
    """archive_member reads from the active input: the stray file next to it is never opened."""
    root = prepared(tmp_path, extra=('SUBDATA.DAT.bak',))
    env.setenv('D5_SOURCE_DIR', str(root))
    src.use(src.data())
    try:
        with pytest.raises(ValueError, match='not a PS_FS_V1'):
            src.archive_member('start.dat')                 # the fixture bytes are not an archive; nothing else is tried
        assert src.subdata_path() == root / 'd1c' / REL
    finally:
        src.use(src.D1cData(root / 'd1c' / REL))


def _voice_tree(tmp_path, *, data=b'x', sub=b'y'):
    root = tmp_path / 'Source'
    (root / 'd1pc' / 'Disgaea PC').mkdir(parents=True)
    (root / 'd1pc' / 'Disgaea PC' / 'DATA.DAT').write_bytes(data)
    (root / 'd1pc' / 'Disgaea PC' / 'SUBDATA.DAT').write_bytes(sub)
    return root


def _voice_manifest(root, states, blobs=None):
    blobs = blobs or {'DATA.DAT': b'x', 'SUBDATA.DAT': b'y'}
    rows = [dict(path=f'Disgaea PC/{n}', size=len(blobs[n]), sha256=hashlib.sha256(blobs[n]).hexdigest(), verified=s)
            for n, s in states.items()]
    sourcefolder.write_manifest(root, {'d1pc': dict(supplied=True, files=rows)})


def test_voice_source_needs_both_verified_rows(env, tmp_path):
    root = _voice_tree(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    _voice_manifest(root, {'DATA.DAT': 'yes', 'SUBDATA.DAT': 'yes'})
    found = src.voice_source()
    assert found.files() == (root / 'd1pc' / 'Disgaea PC' / 'DATA.DAT', root / 'd1pc' / 'Disgaea PC' / 'SUBDATA.DAT')
    _voice_manifest(root, {'DATA.DAT': 'yes', 'SUBDATA.DAT': 'no'})
    assert src.voice_source() is None
    _voice_manifest(root, {'DATA.DAT': 'yes'})
    assert src.voice_source() is None


def _dsarc(clips):
    raw = b'DSARC FL' + struct.pack('<I', len(clips)) + b'\0' * 4
    body = b''
    base = 16 + 48 * len(clips)
    for name, data in clips.items():
        raw += name.encode().ljust(40, b'\0') + struct.pack('<II', len(data), base + len(body))
        body += data
    return raw + body


def _pspfs(members):
    table, body = b'', b''
    base = 16 + 52 * len(members)
    for name, data in members.items():
        table += name.encode().ljust(44, b'\0') + struct.pack('<II', len(data), base + len(body))
        body += data
    return b'PSPFS_V1' + struct.pack('<I', len(members)) + b'\0' * 4 + table + body


def test_voice_reader_opens_only_the_two_verified_archives(env, tmp_path, monkeypatch):
    """REVIEW item 1: an unlisted DATA.DAT in a sibling folder never wins over the manifest-owned one."""
    from d5lib import d1cvoice
    good = _pspfs({n: _dsarc({'good.ogg': b'GOOD'}) for n in d1cvoice.BANKS['EN']} |
                  {n: _dsarc({}) for n in d1cvoice.BANKS['JP']})
    rogue = _pspfs({n: _dsarc({'rogue.ogg': b'ROGUE'}) for n in d1cvoice.BANKS['EN']} |
                   {n: _dsarc({}) for n in d1cvoice.BANKS['JP']})
    root = _voice_tree(tmp_path, data=good)
    (root / 'd1pc' / '000-unlisted').mkdir()
    (root / 'd1pc' / '000-unlisted' / 'DATA.DAT').write_bytes(rogue)
    (root / 'd1pc' / '000-unlisted' / 'SUBDATA.DAT').write_bytes(b'rogue')
    env.setenv('D5_SOURCE_DIR', str(root))
    _voice_manifest(root, {'DATA.DAT': 'yes', 'SUBDATA.DAT': 'yes'}, {'DATA.DAT': good, 'SUBDATA.DAT': b'y'})
    source = src.voice_source()
    d1cvoice._cache.clear()
    opened = []
    from d5lib import d1skill
    monkeypatch.setattr(d1skill, 'disgaea_pc_magic', lambda path, member: opened.append(Path(path)) or (_dsarc({}), None))
    clips = d1cvoice.pc_clips(source)
    assert opened == [root / 'd1pc' / 'Disgaea PC' / 'SUBDATA.DAT']           # never the unlisted sibling
    assert clips[('EN', 'good')] == b'GOOD' and ('EN', 'rogue') not in clips
    assert not any(k[1] == 'rogue' for k in clips)


def test_voice_archive_changed_after_verification_is_refused(env, tmp_path):
    root = _voice_tree(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    _voice_manifest(root, {'DATA.DAT': 'yes', 'SUBDATA.DAT': 'yes'})
    source = src.voice_source()
    (root / 'd1pc' / 'Disgaea PC' / 'DATA.DAT').write_bytes(b'z')           # same size, other bytes
    with pytest.raises(src.D1cSourceError, match=r'd1pc/Disgaea PC/DATA\.DAT.*no longer match'):
        source.files()


def test_main_archive_changed_after_verification_is_refused(env, tmp_path):
    """REVIEW item 2: a same-size replacement under a verified row is refused, never read as the old digest."""
    root = prepared(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    data = src.data()
    src.use(data)
    try:
        with pytest.raises(ValueError, match='not a PS_FS_V1'):
            src.archive_member('start.dat')                 # unchanged file: allowed to be read
        (root / 'd1c' / REL).write_bytes(b'FIXTURE')        # same size, different bytes
        with pytest.raises(src.D1cSourceError, match=r'd1c/data/SUBDATA\.DAT.*no longer match'):
            src.archive_member('start.dat')
        with pytest.raises(src.D1cSourceError, match=r'no longer match'):
            src.data()                                       # and a fresh resolve refuses it too
    finally:
        src.use(src.D1cData(root / 'd1c' / REL))


def test_row_without_a_digest_is_not_trusted(env, tmp_path):
    root = prepared(tmp_path)
    sourcefolder.write_manifest(root, {'d1c': dict(supplied=True, files=[dict(path=REL, size=7, verified='yes')])})
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.D1cSourceError, match='no SHA-256'):
        src.data()


def test_source_specials_read_the_prepared_input_not_research(monkeypatch):
    """REVIEW item 2b: srcskills.d1c_table asks the resolver-backed reader for member 40; the Research loader is not used."""
    import sys
    from d5lib import d1skill, srcskills
    asked = []
    monkeypatch.setattr(src, 'member', lambda i: asked.append(i) or b'raw')

    class Stop(Exception):
        pass

    def read_table(raw, kind):
        assert raw == b'raw'
        raise Stop
    monkeypatch.setattr(d1skill, 'read_table', read_table)
    before = [p for p in sys.path if 'source-packs' in p]
    with pytest.raises(Stop):
        srcskills.d1c_table()
    assert asked == [40] and [p for p in sys.path if 'source-packs' in p] == before
    assert 'd1c_source' not in sys.modules


@pytest.fixture()
def empty_source(monkeypatch):
    class Pack:
        blocks = []
    monkeypatch.setattr(src, 'pack', lambda: Pack())
    monkeypatch.setattr(src, 'characters', lambda: [])


def test_source_view_never_writes_into_a_foreign_folder(env, tmp_path, empty_source):
    """REVIEW item 3: a configured folder that is not an empty or marked cache is refused and left alone."""
    foreign = tmp_path / 'mine'
    foreign.mkdir()
    (foreign / 'notes.txt').write_text('keep')
    (foreign / 'manifest.json').write_text('{"not": "ours"}')
    env.setenv('D5_D1C_SOURCE_VIEW', str(foreign))
    with pytest.raises(src.D1cSourceError, match='not a D1C cache folder'):
        src.art_root()
    assert (foreign / 'notes.txt').read_text() == 'keep' and (foreign / 'manifest.json').read_text() == '{"not": "ours"}'


def test_source_view_removes_only_files_it_listed(env, tmp_path, empty_source):
    view = tmp_path / 'view'
    env.setenv('D5_D1C_SOURCE_VIEW', str(view))
    assert src.art_root() == view and (view / src.VIEW_MARKER).is_file()      # an empty/missing folder is claimed
    (view / 'bodies' / 'anm00001.dat').write_bytes(b'old')
    (view / 'bodies' / 'user.txt').write_text('keep')
    (view / 'extra.txt').write_text('keep')
    old = json.loads((view / 'manifest.json').read_text())
    old['bodies'] = {'1': dict(file='bodies/anm00001.dat')}
    (view / 'manifest.json').write_text(json.dumps(old))                      # a previous build listed one body
    src.art_root()
    assert not (view / 'bodies' / 'anm00001.dat').exists()                     # its own stale file went
    assert (view / 'bodies' / 'user.txt').read_text() == 'keep' and (view / 'extra.txt').read_text() == 'keep'


def test_source_view_refuses_a_symlink(env, tmp_path, empty_source):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target)
    env.setenv('D5_D1C_SOURCE_VIEW', str(link))
    with pytest.raises(src.D1cSourceError, match='symlink'):
        src.art_root()


def test_import_game_refuses_a_bad_manifest_by_name(env, tmp_path, capsys):
    from tools import import_game
    env.setenv('D5_SOURCE_DIR', str(prepared(tmp_path, state='no')))
    for name in ('game', 'state'):
        (tmp_path / name).mkdir()
    with pytest.raises(SystemExit) as exc:
        import_game.main(['d1c', '--only', 'class:11400', '--out', str(tmp_path / 'out'),
                          '--game-path', str(tmp_path / 'game'), '--state', str(tmp_path / 'state')])
    assert exc.value.code == 2
    assert 'd1c/data/SUBDATA.DAT' in capsys.readouterr().err


# ------------------------------------------------------------------------------------------- no installed pack
def test_installed_packs_are_not_read_by_default():
    imp = d1c.Importer()
    imp._ctx = dict(installed_root=HERE, installed_reference=False)
    assert imp._reference_pack('D1C_Class_11400') is None
    imp._ctx = dict(installed_root=HERE, installed_reference=True)
    assert imp._reference_pack('D1C_Class_11400') is None          # the pack is not there: nothing to compare
    pack = HERE / 'tests'
    imp._ctx = dict(installed_root=pack.parent, installed_reference=True)
    assert imp._reference_pack('tests') == pack                   # the explicit opt-in finds an installed pack


def test_source_only_default_for_d1c():
    assert 'd1c' in importcore.SOURCE_ONLY_GAMES
    assert importcore.installed_pack('d1c', {}, '/x', 'D1C_Class_11400') is None
    assert importcore.installed_pack('d1c', {'installed_reference': True}, '/x', 'D1C_Class_11400') == Path('/x/D1C_Class_11400')
    assert importcore.reference_roots('d1c', {}, ('/only/this',)) == [Path('/only/this')]
    assert importcore.installed_pack('d3', {}, '/x', 'p') == Path('/x/p')     # other games keep theirs


def test_recorded_shapes_and_hurt_flags_answer_for_every_pack():
    doc = src.rules('bank-shapes')['packs']
    assert len(doc) == 59
    imp = d1c.Importer()
    imp._ctx = dict(installed_reference=False)
    for name, row in doc.items():
        assert imp._installed_has_hurt(name) == row['hurt']
        ref = imp.wheel_reference(name)
        assert ref and all(k.startswith('Anime/ANM_HI_JP.dat/anm') and len(v) == 2 for k, v in ref.items())
    # the receiver shape of a unique is its recorded sprite bank's (textures, palettes)
    lease = d1c.unique_leases()['4']
    name = f"anm{lease['physical']:05d}.lzs"
    assert imp._receiver_shape('D1C_Unique_4', lease['physical']) == tuple(doc['D1C_Unique_4']['banks'][name])
    assert imp._receiver_shape('D1C_Unique_not_recorded', 999) is None


def test_wheel_freeze_gate_uses_the_recorded_counts(tmp_path):
    from d5lib import anm
    imp = d1c.Importer()
    imp._ctx = dict(installed_reference=False)
    row = src.rules('bank-shapes')['packs']['D1C_Unique_4']
    name, (tex, pal) = next(iter(row['banks'].items()))
    # the recorded reference is compared by the shared wheel gate when no installed pack exists
    ref = imp.wheel_reference('D1C_Unique_4')
    assert ref[f'Anime/ANM_HI_JP.dat/{name}'] == (tex, pal)


# ------------------------------------------------------------------------------------------- kit data, no text, no paths
MODULES = ('d1c.py', 'd1c_art.py', 'd1c_hdfaces.py', '_d1c_source.py', '_d1c_batch.py')
FORBIDDEN = ('/Volumes', 'Research/', 'Research\'', 'Disgaea Source', 'ai-tmp', 'Migration', 'CharacterForge',
             'INSTALLED_MODS', 'offlinepaths', 'Local/Installed', 'D5ModKit/state')


@pytest.mark.parametrize('module', MODULES)
def test_d1c_modules_carry_no_machine_path(module):
    text = (HERE / 'd5lib/importers' / module).read_text(encoding='utf-8')
    code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    # drop docstrings so a description of the old layout does not count
    code = re.sub(r'""".*?"""', '', code, flags=re.S)
    for token in FORBIDDEN:
        assert token not in code, f'{module} still names {token!r}'


def test_roster_data_carries_references_not_text():
    doc = src.rules('roster')
    for row in doc['classes'] + doc['uniques'] + doc['donors']:
        assert not {'name', 'title', 'template_name', 'donor_name'} & set(row)
    for row in doc['classes']:
        assert re.fullmatch(r'[0-9a-f]{64}', row['name_sha256']) and re.fullmatch(r'[0-9a-f]{64}', row['template_name_sha256'])
    for row in doc['uniques']:
        assert re.fullmatch(r'[0-9a-f]{64}', row['name_sha256']) and re.fullmatch(r'[0-9a-f]{64}', row['title_sha256'])
    for row in doc['leases'].values():
        assert 'name' not in row
    for skills in doc['skills'].values():
        assert set(skills) == {'kind', 'skills'}
    assert doc['census_rows'] == 297 and len(doc['classes']) == 13


def test_a_text_that_does_not_match_its_hash_is_refused(monkeypatch):
    monkeypatch.setattr(src, 'character', lambda cid: dict(id=cid, name='Wrong', title='Wrong', body=10, palette=0,
                                                         legacy_body=1))
    with pytest.raises(src.D1cSourceError, match='does not match the recorded SHA-256'):
        _d1c_batch.unique_rows()
    with pytest.raises(src.D1cSourceError, match='does not match the recorded SHA-256'):
        _d1c_batch.class_specs(donor_names=False)


def test_names_resolve_from_the_source_when_the_hash_matches(monkeypatch):
    doc = dict(src.rules('roster'))
    stand_in = 'Stand-in'
    doc['classes'] = [dict(doc['classes'][0], name_sha256=_d1c_batch.text_hash(stand_in))]
    monkeypatch.setattr(_d1c_batch, 'roster_doc', lambda: doc)
    monkeypatch.setattr(src, 'character', lambda cid: dict(id=cid, name=' Stand-in ', title='', body=10, palette=0,
                                                         legacy_body=1))
    spec = _d1c_batch.class_specs(donor_names=False)[0]
    assert spec['name'] == ' Stand-in ' and spec['template_name'] is None


def test_leases_and_rows_keep_their_old_shape():
    leases = d1c.unique_leases()
    assert len(leases) == 46 and all(set(v) >= {'identity', 'physical', 'help_id', 'quest_id', 'quest_slot'} for v in leases.values())
    # ROSTERGAP1 re-leases win over the recorded ones (they were the d1c-extra-leases.json overrides)
    assert {'2400', '2500', '5390', '6601'} <= set(leases)
    assert [r['id'] for r in _d1c_batch.roster_doc()['uniques']][:3] == [1, 2, 3]


def test_the_reference_table_is_counts_only():
    doc = src.rules('bank-shapes')
    text = json.dumps(doc)
    assert not re.search(r'[A-Za-z]{4,}', re.sub(r'D1C_(Class|Unique)_\d+|anm\d+\.lzs|true|false|null|hurt|banks', '', json.dumps(
        doc['packs'])))
    assert 'Volumes' not in text
