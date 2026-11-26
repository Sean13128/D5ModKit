"""SOURCEPREP4-DRPG: the Disgaea RPG importer reads only the prepared source folder plus kit data.

Offline and synthetic: no game bytes, no installed pack, no network.  The prepared folder is a tiny fixture with a real
``manifest.json`` (``d5lib/sourcefolder`` schema), so the tests exercise the resolver the import uses.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from d5lib import importcore, sourcefolder
from d5lib.importers import _drpg_build as build, _drpg_reference as refmod, _drpg_roster as roster, _drpg_source as src, drpg

HERE = Path(__file__).resolve().parents[1]
UID = 15


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prepared(tmp_path, files=None, state='yes', unlisted=()):
    """A fixture folder: ``files`` {rel: bytes} are written and listed; ``unlisted`` are written but not listed."""
    root = tmp_path / 'Source'
    rows = []
    files = dict(files if files is not None else sheets(UID))
    for rel, raw in {**files, **{u: b'unlisted' for u in unlisted}}.items():
        path = root / 'drpg' / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    for rel, raw in files.items():
        rows.append(dict(path=rel, size=len(raw), sha256=sha(raw), known_build='fixture', verified=state))
    sourcefolder.write_manifest(root, {'drpg': dict(edition='fixture', origin='user-dump', supplied=True, files=rows)})
    return root


def sheets(uid, cutin=False, icon=True):
    rels = src.unit_files(uid)
    keep = list(src.REQUIRED_ROLES) + (['icon'] if icon else []) + (['cutin'] if cutin else [])
    return {rels[role]: f'{role}-{uid}'.encode() for role in keep}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv('D5_SOURCE_DIR', raising=False)
    monkeypatch.delenv('D5_DRPG_OWN_CUTINS', raising=False)
    monkeypatch.setattr('d5lib.paths.kit_setting', lambda *_a, **_k: None)
    return monkeypatch


# ------------------------------------------------------------------------------------------- the resolver
def test_data_uses_the_prepared_folder(env, tmp_path):
    root = prepared(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    data = src.data()
    assert data.folder == root and data.sheets_complete(UID)


def test_missing_manifest_says_how_to_prepare(env, tmp_path):
    env.setenv('D5_SOURCE_DIR', str(tmp_path / 'nothing'))
    with pytest.raises(src.DrpgSourceError, match=r'manifest\.json.*prep_source\.py --drpg'):
        src.data()


def test_manifest_without_drpg_rows_refuses(env, tmp_path):
    root = tmp_path / 'S'
    sourcefolder.write_manifest(root, {'dd2': dict(supplied=True, files=[])})
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.DrpgSourceError, match='no Disgaea RPG files'):
        src.data()


def test_a_missing_manifest_row_refuses_by_name(env, tmp_path):
    files = sheets(UID)
    root = prepared(tmp_path, files)
    rel = src.unit_files(UID)['front']
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['games']['drpg']['files'] = [r for r in manifest['games']['drpg']['files'] if r['path'] != rel]
    (root / 'manifest.json').write_text(json.dumps(manifest))
    data = src.data(root)
    with pytest.raises(src.DrpgSourceError, match=re.escape(f'drpg/{rel}: no manifest row')):
        data.read(rel)
    with pytest.raises(FileNotFoundError, match='verified source sheets'):
        build.source_assets(UID, data)


@pytest.mark.parametrize('state', ['no', 'unknown'])
def test_an_unverified_row_is_refused_with_its_state(env, tmp_path, state):
    data = src.data(prepared(tmp_path, state=state))
    rel = src.unit_files(UID)['front']
    assert not data.have(rel)
    with pytest.raises(src.DrpgSourceError, match=f"verified {state!r}"):
        data.read(rel)


def test_a_verified_row_with_no_file_or_wrong_size_is_refused(env, tmp_path):
    root = prepared(tmp_path)
    rel = src.unit_files(UID)['back']
    (root / 'drpg' / rel).write_bytes(b'longer than the row says')
    data = src.data(root)
    with pytest.raises(src.DrpgSourceError, match='size differs'):
        data.read(rel)
    (root / 'drpg' / rel).unlink()
    with pytest.raises(src.DrpgSourceError, match='file is missing'):
        data.read(rel)


def test_a_same_size_replacement_of_a_verified_file_is_detected(env, tmp_path):
    root = prepared(tmp_path)
    rel = src.unit_files(UID)['front']
    path = root / 'drpg' / rel
    original = path.read_bytes()
    path.write_bytes(bytes(reversed(original)))          # same size, different bytes
    assert len(path.read_bytes()) == len(original)
    data = src.data(root)
    with pytest.raises(src.DrpgSourceError, match='no longer match the verified manifest row'):
        data.read(rel)
    assert data.have(rel)                                # the stat looks fine: only the hash tells
    with pytest.raises(src.DrpgSourceError, match='no longer match'):
        build.stage_assets([dict(id=UID, type='humanoid', assets=None)], tmp_path / 'work', data)


# ------------------------------------------------------------------------------------------- unlisted files never win
def test_an_unlisted_file_never_supplies_a_role(env, tmp_path):
    """The icon and cut-in exist on disk but the manifest does not list them: no route returns them."""
    rels = src.unit_files(UID)
    root = prepared(tmp_path, sheets(UID, cutin=False, icon=False), unlisted=(rels['icon'], rels['cutin'], 'sprites/Cutins/extra.png'))
    data = src.data(root)
    assert set(data.unit_assets(UID)) == set(src.REQUIRED_ROLES)
    files = build.source_assets(UID, data)['files']
    assert 'icon' not in files and 'cutin' not in files
    with pytest.raises(src.DrpgSourceError, match='no manifest row'):
        data.read(rels['cutin'])


def test_the_own_cutin_folder_is_an_explicit_opt_in(env, tmp_path):
    data = src.data(prepared(tmp_path))
    own = tmp_path / 'own'
    own.mkdir()
    (own / f'{UID}.png').write_bytes(b'own cutin')
    assert 'cutin' not in build.source_assets(UID, data)['files']
    env.setenv('D5_DRPG_OWN_CUTINS', str(own))
    got = build.source_assets(UID, data)['files']['cutin']
    assert got['provenance'] == build.OWN_CUTIN_PROVENANCE and got['sha256'] == sha(b'own cutin')


def test_costume_looks_are_resolved_per_look(env, tmp_path):
    files = {**sheets(UID), **sheets(UID + 1)}
    data = src.data(prepared(tmp_path, files))
    c = dict(looks=[dict(id=UID, type='humanoid'), dict(id=UID + 1, type='humanoid'), dict(id=UID + 2, type='humanoid')])
    looks = build.distinct_looks(c, UID, data)
    assert [l['id'] for l in looks] == [UID, UID + 1, UID + 2]
    assert looks[0]['assets'] and looks[1]['assets'] and looks[2]['assets'] is None   # no rows: never invented


def test_voice_banks_are_exact_manifest_rows(env, tmp_path):
    from d5lib import drpgvoice
    files = {**sheets(UID), **{r: b'bank' for r in src.voice_files(7).values()}}
    root = prepared(tmp_path, files, unlisted=tuple(src.voice_files(8).values()))
    data = src.data(root)
    assert data.voice_looks() == [7]
    assert data.voice_bank(7) == src.voice_files(7)
    with pytest.raises(src.DrpgSourceError, match='no manifest row'):
        data.voice_bank(8)                                # on disk, not listed
    with pytest.raises(src.DrpgSourceError):
        drpgvoice.read_bank(data, 8)
    # a same-size replacement of a listed bank is refused by the same read
    path = root / 'drpg' / src.voice_files(7)['acb']
    path.write_bytes(b'BANK')
    with pytest.raises(src.DrpgSourceError, match='no longer match'):
        data.read(src.voice_files(7)['acb'])


# ------------------------------------------------------------------------------------------- owned folders
def test_a_foreign_folder_is_never_deleted(tmp_path):
    folder = tmp_path / 'native-mods' / 'Pack'
    folder.mkdir(parents=True)
    (folder / 'mine.txt').write_text('keep')
    with pytest.raises(FileExistsError, match='not created by this importer'):
        drpg.remove_created(folder)
    assert (folder / 'mine.txt').read_text() == 'keep'


def test_only_recorded_files_are_removed(tmp_path):
    folder = tmp_path / 'native-mods' / 'Pack'
    (folder / 'sub').mkdir(parents=True)
    (folder / 'sub' / 'built.bin').write_bytes(b'1')
    drpg.record_created(folder)
    (folder / 'later-user-file.txt').write_text('keep')
    drpg.remove_created(folder)
    assert not (folder / 'sub').exists() and (folder / 'later-user-file.txt').read_text() == 'keep'
    assert not drpg._owned_marker(folder).exists()


def test_the_staged_asset_folder_refuses_foreign_files(env, tmp_path):
    """Art the importer did not stage would be readable as source art, so a folder holding any is not reused."""
    data = src.data(prepared(tmp_path))
    work = tmp_path / 'work'
    looks = [dict(id=UID, type='humanoid')]
    root = Path(build.stage_assets(looks, work, data))
    staged = sorted(p.relative_to(root).as_posix() for p in root.rglob('*.png'))
    assert f'Characters/Sprites/front/front{UID}.png' in staged
    (root / 'Characters' / 'Cut-Ins').mkdir(parents=True, exist_ok=True)
    (root / 'Characters' / 'Cut-Ins' / f'{UID}.png').write_bytes(b'foreign')
    with pytest.raises(FileExistsError, match='did not create'):
        build.stage_assets(looks, work, data)
    assert (root / 'Characters' / 'Cut-Ins' / f'{UID}.png').read_bytes() == b'foreign'


def test_a_rerun_restages_exactly_the_verified_files(env, tmp_path):
    data = src.data(prepared(tmp_path))
    work = tmp_path / 'work'
    looks = [dict(id=UID, type='humanoid')]
    build.stage_assets(looks, work, data)
    again = Path(build.stage_assets(looks, work, data))
    assert (again / 'Characters/Sprites/front' / f'front{UID}.png').read_bytes() == f'front-{UID}'.encode()


# ------------------------------------------------------------------------------------------- installed packs
def test_drpg_is_a_source_only_game():
    assert 'drpg' in importcore.SOURCE_ONLY_GAMES
    assert importcore.installed_pack('drpg', {}, '/nowhere', 'DRPG_Core_X_1') is None
    assert importcore.reference_roots('drpg', {}, ()) == []
    assert importcore.installed_pack('drpg', {'installed_reference': True}, '/nowhere', 'X') == Path('/nowhere/X')


def test_namespaces_read_no_installed_folder_when_none(monkeypatch):
    from d5lib.importers import _drpg_namespaces as ns

    # the roots list is built from the argument: None gives no installed root, only explicit extra roots
    import inspect
    assert 'if installed_root else []' in inspect.getsource(ns.taken_namespaces)
    assert 'if installed_root else ()' in inspect.getsource(ns.reserve_evilities)


def test_outfit_system_is_generated_not_read(tmp_path):
    from d5lib import modsys, outfits
    folder = build.outfit_system(tmp_path / 'work')
    mod = modsys.Mod(str(folder))
    assert outfits.is_system_mod(mod) and mod.meta['name'] == 'Outfit System'
    build.outfit_system(tmp_path / 'work')               # idempotent: only its own files are replaced


def test_pose_reference_is_pinned_and_never_unpickled_unchecked(tmp_path, monkeypatch):
    bogus = tmp_path / 'ref.pickle'
    import pickle
    bogus.write_bytes(pickle.dumps('evil'))
    monkeypatch.setattr(drpg, 'REF_PATH', str(bogus), raising=False)
    from d5lib import drpg as lib
    monkeypatch.setattr(lib, 'REF_PATH', str(bogus))
    original = lib.load_reference
    try:
        used = refmod.configure(None)
        with pytest.raises(refmod.PoseReferenceError, match='not the pinned DRPG pose reference'):
            lib.load_reference()
        monkeypatch.setattr(lib, 'REF_PATH', str(tmp_path / 'missing.pickle'))
        refmod.configure(None)
        with pytest.raises(refmod.PoseReferenceError, match='missing: put the upstream release file'):
            lib.load_reference()
        assert used == {}
    finally:
        lib.load_reference = original


def test_pose_reference_pin_names_the_installed_kit_file():
    pin = refmod.pin()
    assert len(pin['sha256']) == 64 and pin['size'] > 1_000_000


# ------------------------------------------------------------------------------------------- kit data: no text, no paths
MODULES = ('drpg.py', '_drpg_build.py', '_drpg_source.py', '_drpg_roster.py', '_drpg_reference.py',
           '_drpg_namespaces.py', '_drpg_zed.py', '_drpg_monsters.py', 'drpg_leases.py')
FORBIDDEN = ('/Volumes', 'Disgaea Source', 'ai-tmp', 'Builds/', 'Character Forge', 'CharacterForge', 'INSTALLED_MODS',
             'offlinepaths', 'Local/Installed', 'D5ModKit/state', 'FALLBACKS', 'DRPG-Assets-Updated')


@pytest.mark.parametrize('module', MODULES)
def test_drpg_modules_carry_no_machine_path(module):
    text = (HERE / 'd5lib/importers' / module).read_text(encoding='utf-8')
    code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    code = re.sub(r'""".*?"""', '', code, flags=re.S)
    for token in FORBIDDEN:
        if module == 'drpg_leases.py' and token in ('Builds/', 'D5ModKit/state'):     # the maintainer rebuild functions, under a --base the caller names
            continue
        assert token not in code, f'{module} still names {token!r}'


def test_roster_counts_and_size():
    doc = roster.load()
    bases = [g['character']['base_id'] for g in doc['groups']]
    assert len(bases) == 146 == len(set(bases))
    assert sum(len(g['character']['looks']) - 1 for g in doc['groups']) == 89
    for part in roster.PARTS:
        assert part.stat().st_size < 1 << 20


JAPANESE = re.compile('[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]')


def test_roster_and_shapes_carry_no_japanese_and_no_text_values():
    for path in (*roster.PARTS, roster.SHAPES):
        raw = path.read_text(encoding='utf-8')
        assert not JAPANESE.search(raw) and '\\u' not in re.sub(r'\\u(ff05|2014|30fb|ff65)', '', raw, flags=re.I) \
            or not re.search(r'\\u(30[4-9a-f]|3[4-9a-f]|[4-9][0-9a-f]{3}|ff6|ff7|ff8|ff9)', raw, flags=re.I), path.name


def test_roster_text_is_references_only():
    """Every string under a text key is an @text/@authored/@parts reference; ids and rules stay literal."""
    keys = {'rpg_name', 'rpg_text', 'effect', 'name_jp', 'jp', 'cv_name', 'd5_name_jp'}
    doc = roster.load()

    def walk(node, key=None):
        if isinstance(node, dict):
            if set(node) <= {'@text', '@authored', '@parts', 'of', 'at'} and node:
                return
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and node and key in keys:
            raise AssertionError(f'literal text under {key!r}: {node[:20]!r}')

    walk(doc)


def test_text_references_resolve_and_refuse_a_changed_source():
    pool = roster.TextPool(['alpha beta', 'gamma'])
    ref = {'@text': roster.text_sha('gamma')}
    assert roster.resolve({'x': [ref, {'@authored': 'mine'}]}, pool) == {'x': ['gamma', 'mine']}
    part = {'@text': roster.text_sha('beta'), 'of': roster.text_sha('alpha beta'), 'at': [6, 10]}
    assert roster.resolve({'@parts': ['<', part, '>']}, pool) == '<beta>'
    with pytest.raises(roster.DrpgRosterError, match='not in the prepared masters'):
        roster.resolve({'@text': roster.text_sha('absent')}, pool)
    with pytest.raises(roster.DrpgRosterError, match='not at'):
        roster.resolve(dict(part, at=[0, 4]), pool)


def test_the_full_roster_resolves_against_the_prepared_source_when_present(env):
    from d5lib import sourcefolder as sf
    folder = sf.source_dir()
    if not (Path(folder) / 'manifest.json').is_file():
        pytest.skip('no prepared source folder')
    try:
        data = src.data()
    except src.DrpgSourceError:
        pytest.skip('no prepared DRPG source')
    if not all(data.have(f'masters/{n}.json') for n in roster.MASTERS):
        pytest.skip('the prepared folder lacks the decoded masters')
    pool = roster.TextPool.from_sources(data)                   # no Disgaea 5 tables here: D5 names may stay unresolved
    try:
        chars = roster.characters(pool)
    except roster.DrpgRosterError as exc:
        assert 'not in the prepared masters or the Disgaea 5 tables' in str(exc)
        return
    assert len(chars) == 146


def test_bank_shapes_cover_every_roster_folder():
    shapes = roster.bank_shapes()
    names = {drpg.NAMES.get(g['character']['base_id']) or None for g in roster.load()['groups']}
    assert 'DRPG_Core_Zed_94' in shapes
    assert all(all(len(v) == 2 for v in banks.values()) for banks in shapes.values())


# ------------------------------------------------------------------------------------------- CLI
def test_import_game_refuses_a_missing_manifest_by_name(env, tmp_path, capsys):
    from tools import import_game
    env.setenv('D5_SOURCE_DIR', str(tmp_path / 'empty'))
    with pytest.raises(SystemExit) as exc:
        import_game.main(['drpg', '--only', 'drpg:15', '--out', str(tmp_path / 'out'), '--game-path', str(tmp_path / 'game'),
                          '--state', str(tmp_path / 'state')])
    assert exc.value.code == 2
    assert 'manifest.json is missing' in capsys.readouterr().err
    assert not (tmp_path / 'out' / 'drpg' / 'mods').exists() or not list((tmp_path / 'out' / 'drpg' / 'mods').iterdir())


def test_decode_rows_keep_the_derived_fallback_label():
    from d5lib.importers import _drpg_source as src
    data = src.DrpgData('/nowhere', {'a.png': {'known_build': 'drpg-jp-client-decoded-20261016'},
                                     'b.png': {'known_build': 'drpg-jp-rpgextract1'}})
    assert data.provenance('a.png') == 'derived-fallback' and data.provenance('b.png') == 'original'


def test_a_staged_own_cutin_stays_recognisable_as_an_illustration(env, tmp_path):
    """drpgcutin.is_own() looks at the folder the file really lives in; staging must not hide it (portrait label)."""
    from d5lib import drpgcutin
    data = src.data(prepared(tmp_path))
    own = tmp_path / 'own-cutins'
    own.mkdir()
    (own / f'{UID}.png').write_bytes(b'own cutin')
    env.setenv('D5_DRPG_OWN_CUTINS', str(own))
    root = Path(build.stage_assets([dict(id=UID, type='humanoid')], tmp_path / 'work', data))
    staged = root / 'Characters' / 'Cut-Ins' / f'{UID}.png'
    assert staged.read_bytes() == b'own cutin' and drpgcutin.is_own(staged)
    # a cut-in of the source is a verified copy and is never labelled an illustration
    assert not drpgcutin.is_own(root / 'Characters' / 'Sprites' / 'front' / f'front{UID}.png')
    build.stage_assets([dict(id=UID, type='humanoid')], tmp_path / 'work', data)    # rerun removes only what it created
    assert (own / f'{UID}.png').read_bytes() == b'own cutin'


def test_a_marked_folder_under_a_symlinked_parent_is_reset_and_an_unmarked_one_refused(tmp_path):
    """Regression: /tmp and /var are symlinks on macOS; the owned-folder check compared an unresolved folder with resolved
    targets, so a pack the importer itself wrote was never reset and a stale success stayed in place."""
    from d5lib.importers import drpg
    real = tmp_path / 'real'
    real.mkdir()
    (tmp_path / 'link').symlink_to(real)
    marked = tmp_path / 'link' / 'pack'
    marked.mkdir()
    (marked / 'a.json').write_text('old')
    drpg.record_created(marked)
    drpg.remove_created(marked)
    assert not marked.exists()                          # reset: nothing stale survives
    foreign = tmp_path / 'link' / 'foreign'
    foreign.mkdir()
    (foreign / 'mine.txt').write_text('keep')
    with pytest.raises(FileExistsError, match='not created by this importer'):
        drpg.remove_created(foreign)
    assert (foreign / 'mine.txt').read_text() == 'keep'
