"""SOURCEPREP4-DD2: the DD2 importer reads only the prepared source folder plus kit data.

Offline and synthetic: no game bytes, no installed pack, no network.  The prepared folder is built as a
tiny fixture with a real ``manifest.json`` (``d5lib/sourcefolder`` schema), so these tests exercise the
same resolver the import uses.
"""
import json
from pathlib import Path

import pytest

from d5lib import sourcefolder
from d5lib.importers import _dd2_source as src

DATA_REL = 'PS3_GAME/USRDIR/Data'
HERE = Path(__file__).resolve().parents[1]


def prepared(tmp_path, *, states=None, omit=()):
    """A prepared source folder: manifest rows + files for every required DD2 archive."""
    root = tmp_path / 'Source'
    data = root / 'dd2' / DATA_REL
    data.mkdir(parents=True)
    rows = []
    for name in src.REQUIRED:
        rel = f'{DATA_REL}/{name}'
        if name in omit:
            continue
        (data / name).write_bytes(b'fixture')
        state = (states or {}).get(name, 'yes')
        rows.append(dict(path=rel, size=7, sha256='0' * 64, known_build='fixture', verified=state))
    sourcefolder.write_manifest(root, {'dd2': dict(edition='fixture', origin='user-dump', root=str(data),
                                                   supplied=True, files=rows)})
    return root


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv('D5_SOURCE_DIR', raising=False)
    monkeypatch.delenv('D5_DD2_FORGE', raising=False)
    monkeypatch.delenv('D5_DD2_POSE_TABLE', raising=False)
    # The host kit's settings.json must not decide a test: no saved source_dir / dd2_forge.
    monkeypatch.setattr('d5lib.paths.kit_setting', lambda *_a, **_k: None)
    return monkeypatch


def test_data_dir_uses_the_prepared_folder(env, tmp_path):
    root = prepared(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    data = src.data_dir()
    assert data.root == root / 'dd2' / DATA_REL
    assert data.prepared
    assert sorted(data.files) == sorted(src.REQUIRED)


def test_missing_manifest_says_how_to_prepare(env, tmp_path):
    env.setenv('D5_SOURCE_DIR', str(tmp_path / 'nothing'))
    with pytest.raises(src.Dd2SourceError, match=r'manifest\.json.*prep_source\.py --dd2'):
        src.data_dir()


def test_missing_manifest_row_names_the_file(env, tmp_path):
    root = prepared(tmp_path, omit=('ANM_HI_3.dat',))
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.Dd2SourceError) as exc:
        src.data_dir()
    message = str(exc.value)
    assert f'dd2/{DATA_REL}/ANM_HI_3.dat' in message and 'no manifest row' in message


def test_failed_manifest_row_names_the_file_and_state(env, tmp_path):
    root = prepared(tmp_path, states={'START_4.dat': 'no'})
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.Dd2SourceError) as exc:
        src.data_dir()
    message = str(exc.value)
    assert f'dd2/{DATA_REL}/START_4.dat' in message and "'no'" in message


def test_every_bad_row_is_listed(env, tmp_path):
    root = prepared(tmp_path, states={'START.dat': 'no'}, omit=('ANM_HI_6.dat',))
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.Dd2SourceError) as exc:
        src.data_dir()
    message = str(exc.value)
    assert 'START.dat' in message and 'ANM_HI_6.dat' in message


def test_a_dd2_less_manifest_says_prep_was_not_run(env, tmp_path):
    root = tmp_path / 'Source'
    root.mkdir()
    sourcefolder.write_manifest(root, {})
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.Dd2SourceError, match='no Disgaea D2 files'):
        src.data_dir()


def test_unreadable_manifest_is_refused(env, tmp_path):
    root = tmp_path / 'Source'
    root.mkdir()
    (root / 'manifest.json').write_text('{"schema": "not-ours"}')
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.Dd2SourceError, match='unreadable'):
        src.data_dir()


@pytest.mark.parametrize('shape', ['data', 'dump', 'disc'])
def test_explicit_root_keeps_the_old_shapes_without_a_manifest(tmp_path, shape):
    if shape == 'data':
        root = tmp_path / 'dump'
        (root / DATA_REL).mkdir(parents=True)
        (root / DATA_REL / 'START_4.dat').write_bytes(b'x')
        expected = root / DATA_REL
    elif shape == 'dump':
        root = tmp_path / 'dump'
        (root / 'Data').mkdir(parents=True)
        (root / 'Data' / 'START_4.dat').write_bytes(b'x')
        expected = root / 'Data'
    else:
        root = tmp_path / 'dump'
        (root / 'disc' / 'game' / DATA_REL).mkdir(parents=True)
        (root / 'disc' / 'game' / DATA_REL / 'START_4.dat').write_bytes(b'x')
        expected = root / 'disc' / 'game' / DATA_REL
    data = src.data_dir(root)
    assert data.root == expected
    assert not data.prepared


def test_explicit_root_without_a_table_is_refused(tmp_path):
    with pytest.raises(src.Dd2SourceError, match='START_4.dat'):
        src.data_dir(tmp_path / 'empty')
    (tmp_path / 'empty').mkdir()
    with pytest.raises(src.Dd2SourceError, match='START_4.dat'):
        src.data_dir(tmp_path / 'empty')


def test_pose_table_order(env, tmp_path):
    root = prepared(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    assert src.pose_table() == src.POSE_TABLE       # prepared folder has none: kit copy
    prepared_copy = root / 'dd2' / 'd2-common-poses.json'
    prepared_copy.write_text('{}')
    assert src.pose_table() == prepared_copy
    override = tmp_path / 'mine.json'
    override.write_text('{}')
    env.setenv('D5_DD2_POSE_TABLE', str(override))
    assert src.pose_table() == override


def test_pose_table_missing_override_is_an_error(env, tmp_path):
    env.setenv('D5_DD2_POSE_TABLE', str(tmp_path / 'absent.json'))
    with pytest.raises(src.Dd2SourceError, match='D5_DD2_POSE_TABLE'):
        src.pose_table()


def test_forge_root_comes_from_the_explicit_override(env, tmp_path):
    (tmp_path / 'forge').mkdir()
    (tmp_path / 'forge' / 'd2art.py').write_text('')
    env.setenv('D5_DD2_FORGE', str(tmp_path))
    assert src.forge_root() == tmp_path
    env.setenv('D5_DD2_FORGE', str(tmp_path / 'forge'))
    assert src.forge_root() == tmp_path


def test_missing_forge_root_is_named(env, tmp_path):
    env.setenv('D5_DD2_FORGE', str(tmp_path / 'absent'))
    with pytest.raises(src.Dd2SourceError, match='D5_DD2_FORGE'):
        src.forge_root()


def test_baseline_configs_are_kit_data():
    for sid in (30, 100):
        cfg = src.baseline_config(sid)
        assert cfg and 'ranks' in cfg and len(cfg['ranks']) >= 1
    assert src.baseline_config(1210) is None


def test_frozen_patches_and_claims_are_kit_data():
    frozen = src.frozen_patches('DD2_Class_22210')
    assert 'patches/db/Skill.dat.json' in frozen['files']
    assert isinstance(frozen['reviewed_evility_ids'], list)
    assert src.frozen_patches('DD2_Class_does_not_exist') == {}
    claims = src.claimed_ids()
    assert claims and all(isinstance(k, int) for k in list(claims)[:5])


def test_wheel_reference_is_kit_data():
    shapes = src.wheel_reference('DD2_Unique_570')
    assert shapes['Anime/ANM_HI_JP.dat/anm00456.lzs'] == (2, 10)
    assert src.wheel_reference('DD2_Class_does_not_exist') == {}


def test_wheel_gate_falls_back_to_the_recorded_shape(tmp_path):
    """Without an installed pack the recorded header shape still freezes the wheel (DD2LEN1 parity)."""
    from d5lib import anm, importcore
    mod = tmp_path / 'DD2_Unique_570'
    bank = mod / 'files/Anime/ANM_HI_JP.dat/anm00456.lzs'
    bank.parent.mkdir(parents=True)
    images = [anm.Image8(bytes([9, 1, 1, 1]), 1, 1, 1, b'\x01') for _ in range(2)]
    palettes = [anm.Image8(bytes([9, 1, 1, 1]), 1, 1, 1, b'\x01') for _ in range(10)]
    bank.write_bytes(anm.AnmFile([], images, palettes).to_bytes())
    rel = 'Anime/ANM_HI_JP.dat/anm00456.lzs'
    ok, why = importcore.wheel_gate(mod, tmp_path / 'no-installed', reference={rel: (2, 10)})
    assert ok, why
    ok, why = importcore.wheel_gate(mod, tmp_path / 'no-installed', reference={rel: (3, 10)})
    assert not ok and 'recorded 10/3' in why
    # a two-argument call (D4/D1C) keeps the old "no reference" pass
    assert importcore.wheel_gate(mod, tmp_path / 'no-installed')[0] is True


def test_ability_review_and_emission_documents():
    review = src.ability_review()
    assert review['sources']['dd2']['sha256'] == '3e84005958fe5c63351118f1f02d4ef1c481a92c2be4c23a76e571a57daa5416'
    assert review['skills'] and review['evilities']
    assert src.engine_emission()['extension_rows'] in ({}, [])


def test_source_tables_refuses_a_table_that_differs_from_the_review(env, tmp_path):
    """The reviewed hash is checked before any decode, so a wrong prepared table is refused by name."""
    root = prepared(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    from d5lib.importers import _dd2_abilities
    with pytest.raises(ValueError, match='differs from the reviewed coverage snapshot'):
        _dd2_abilities.source_tables()


def test_statfidelity_dd2_rows_uses_the_prepared_folder(env, tmp_path, monkeypatch):
    root = prepared(tmp_path)
    env.setenv('D5_SOURCE_DIR', str(root))
    from d5lib import statfidelity, dd2source
    seen = {}

    class FakeTables:
        chars = {}

        def __init__(self, pack):
            pass

    monkeypatch.setattr(dd2source, 'Tables', FakeTables)
    monkeypatch.setattr(dd2source, 'Nispack', lambda raw: seen.setdefault('raw', raw))
    assert statfidelity.dd2_rows() == {}
    assert seen['raw'] == b'fixture'          # the prepared folder's START_4.dat was the table read


@pytest.mark.parametrize('module', ['d5lib/importers/dd2.py', 'd5lib/importers/_dd2_baseline.py',
                                    'd5lib/importers/_dd2_abilities.py', 'd5lib/importers/_dd2_source.py',
                                    'd5lib/importers/_dd2_prepare.py'])
def test_dd2_modules_carry_no_machine_path(module):
    text = (HERE / module).read_text(encoding='utf-8')
    assert '/Volumes/' not in text
    assert 'ai-tmp' not in text


def test_kit_owned_reader_modules_carry_no_machine_path():
    """The DD2 glue moved into the kit must not reach back to Research/ or the Forge tree by string path."""
    for module in ('d5lib/importers/_dd2_prepare.py', 'd5lib/importers/_dd2_source.py'):
        text = (HERE / module).read_text(encoding='utf-8')
        for literal in ("'Research", '"Research', "'Migration", '"Migration', "'/Volumes", '"/Volumes'):
            assert literal not in text, (module, literal)


def test_an_unlisted_archive_cannot_win_the_selection(env, tmp_path):
    """Review reproduction: START_999.dat in the folder was read even though the manifest never listed it."""
    root = prepared(tmp_path)
    data_dir = root / 'dd2' / DATA_REL
    (data_dir / 'START_999.dat').write_bytes(b'bogus table that must never be read')
    env.setenv('D5_SOURCE_DIR', str(root))
    data = src.data_dir()
    assert 'START_999.dat' not in data.files
    assert 'START_999.dat' not in [p.name for p in data.archives('START')]
    assert data.archives('START')[-1].name == 'START.dat'      # base archive stays last (lowest priority)
    with pytest.raises(src.Dd2SourceError, match='START_999.dat'):
        data.path('START_999.dat')


def test_a_verified_row_with_no_file_is_refused(env, tmp_path):
    """Review reproduction: stale 'verified' metadata for a physically missing ANM_HI_3.dat."""
    root = prepared(tmp_path)
    row = next(r for r in sourcefolder.read_manifest(root)['games']['dd2']['files']
               if r['path'].endswith('ANM_HI_3.dat'))
    row['verified'] = 'yes'
    (root / 'dd2' / DATA_REL / 'ANM_HI_3.dat').unlink()
    sourcefolder.write_manifest(root, sourcefolder.read_manifest(root)['games'])
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.Dd2SourceError) as exc:
        src.data_dir()
    message = str(exc.value)
    assert 'ANM_HI_3.dat' in message and 'missing' in message


def test_a_size_mismatch_is_refused(env, tmp_path):
    root = prepared(tmp_path)
    (root / 'dd2' / DATA_REL / 'START_2.dat').write_bytes(b'longer than the manifest says')
    env.setenv('D5_SOURCE_DIR', str(root))
    with pytest.raises(src.Dd2SourceError, match='START_2.dat.*size'):
        src.data_dir()


def test_installed_icons_are_not_pinned_by_default(tmp_path):
    """Review reproduction: the default stage copied installed icon row ids ([1,2] -> [3,4]) into output."""
    import json as _json
    from d5lib import importcore
    mod = tmp_path / 'built' / 'DD2_Unique_10'
    installed = tmp_path / 'installed'
    (mod / 'patches/outfits').mkdir(parents=True)
    (installed / 'DD2_Unique_10' / 'patches/outfits').mkdir(parents=True)
    (mod / 'patches/outfits/outfits.json').write_text(_json.dumps({'icons': {'10': [1, 2]}}))
    (installed / 'DD2_Unique_10' / 'patches/outfits/outfits.json').write_text(
        _json.dumps({'icons': {'10': [3, 4]}}))
    assert importcore.installed_pack('dd2', dict(installed_reference=False), installed, 'DD2_Unique_10') is None
    assert importcore.installed_pack('dd2', dict(installed_reference=True), installed, 'DD2_Unique_10') == \
        installed / 'DD2_Unique_10'
    assert importcore.pin_installed_icons(mod, None) == {}
    assert _json.loads((mod / 'patches/outfits/outfits.json').read_text())['icons'] == {'10': [1, 2]}
    # the explicit reference path still pins (unchanged behaviour for a comparison build)
    moved = importcore.pin_installed_icons(mod, installed / 'DD2_Unique_10')
    assert moved == {'10': [3, 4]}


def test_default_dd2_id_roots_do_not_reach_the_install(monkeypatch):
    """Review reproduction: the used-id gate added the live kit even with INSTALLED_MODS empty."""
    from d5lib import importcore
    monkeypatch.setattr(importcore, 'default_extra_roots', lambda extra=(): [Path('/installed-reference')])
    assert importcore.reference_roots('dd2', dict(installed_reference=False)) == []
    assert importcore.reference_roots('dd2', dict(installed_reference=False), ['/tmp/explicit']) == \
        [Path('/tmp/explicit')]
    # D4 is source-only too (SOURCEPREP4-D4); games not migrated yet keep their old installed reference
    assert importcore.reference_roots('d4', {}) == []
    assert importcore.reference_roots('d3', {}) == [Path('/installed-reference')]


def test_an_installed_bank_is_not_read_without_the_opt_in(tmp_path):
    """Review reproduction: installed shape differences must not reach the default gate."""
    from d5lib import anm, importcore
    mod = tmp_path / 'DD2_Unique_570'
    bank = mod / 'files/Anime/ANM_HI_JP.dat/anm00456.lzs'
    bank.parent.mkdir(parents=True)
    images = [anm.Image8(bytes([9, 1, 1, 1]), 1, 1, 1, b'\x01') for _ in range(2)]
    palettes = [anm.Image8(bytes([9, 1, 1, 1]), 1, 1, 1, b'\x01') for _ in range(10)]
    bank.write_bytes(anm.AnmFile([], images, palettes).to_bytes())
    installed = tmp_path / 'installed' / 'DD2_Unique_570'
    (installed / 'files/Anime/ANM_HI_JP.dat').mkdir(parents=True)
    (installed / 'files/Anime/ANM_HI_JP.dat/anm00456.lzs').write_bytes(b'not a bank')
    rel = 'Anime/ANM_HI_JP.dat/anm00456.lzs'
    ok, why = importcore.wheel_gate(mod, None, reference={rel: (2, 10)})
    assert ok, why


def test_frozen_recipes_store_no_game_text_and_round_trip(tmp_path):
    """The frozen patch recipe keeps ids/rules and sha256 text references, never the text."""
    raw = json.loads((HERE / 'd5lib/importers/dd2-frozen-patches.json').read_text())

    def check(doc):
        if isinstance(doc, dict):
            for key, value in doc.items():
                if key.startswith(('name_', 'desc_')):
                    assert isinstance(value, dict) and set(value) <= {'@text', '@authored'}, (key, value)
                else:
                    check(value)
        elif isinstance(doc, list):
            for value in doc:
                check(value)

    for entry in raw['folders'].values():
        for item in entry['files'].values():
            check(item['doc'])
    # a synthetic pool proves the resolver: source text and a normalized spelling resolve; an unknown
    # hash is refused by name rather than silently written.
    payload = {'patches/db/Skill.dat.json': dict(
        newline=False, sha256=None,
        doc={'table': 'Skill.dat', 'added': [{'id': 1, 'name_EN': {'@text': src.text_sha('Source name')},
                                              'desc_EN': {'@authored': 'kit wording'}}]})}
    pool = {src.text_sha('Source name'): 'Source name'}
    rendered = src._resolve_text(payload['patches/db/Skill.dat.json']['doc'], pool.get)
    assert rendered['added'][0]['name_EN'] == 'Source name'
    assert rendered['added'][0]['desc_EN'] == 'kit wording'
    with pytest.raises(src.Dd2SourceError, match='not in the prepared source'):
        src._resolve_text({'@text': '0' * 64}, src.TextPool().get)


def test_ability_review_carries_references_not_text():
    review = src.ability_review()
    for section in ('skills', 'evilities'):
        for row in review[section].values():
            assert 'dd2_name' not in row and 'dd2_desc' not in row and 'copy_of_name' not in row
            assert len(row['dd2_name_sha256']) == 64 and len(row['dd2_desc_sha256']) == 64
            if row.get('copy_of') is not None:
                assert len(row['copy_of_name_sha256']) == 64
    assert 'path' not in review['sources']['dd2'] and 'path' not in review['sources']['d5']['Skill.dat']
    emission = src.engine_emission()
    assert emission['extension_rows'] in ({}, [])
    assert 'source_text' not in json.dumps(emission) and 'inputs' not in emission
