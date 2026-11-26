"""Plugin boundary tests: malformed banks must fail, offline reads never create state."""
import json
import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import anm, classcheck, modsys
from d5lib.importers import dd2


def _bank(tmp_path, marker=1):
    path = tmp_path / 'files/Anime/ANM_HI.dat/anm00001.lzs'
    path.parent.mkdir(parents=True)
    image = anm.Image8(bytes([9, 1, 1, 1]), 1, 1, marker, b'\x01')
    path.write_bytes(anm.AnmFile([], [image], []).to_bytes())
    return path


def test_bank_gate_rejects_wheel6_marker_defect(tmp_path, monkeypatch):
    monkeypatch.setattr(classcheck, 'check', lambda *a, **k: [])
    path = _bank(tmp_path, marker=0x10000)
    gates, notes = dd2.validate_pack(tmp_path)
    assert gates['identity']
    assert not gates['anm']
    assert 'byte-order marker' in '\n'.join(notes)
    path.write_bytes(anm.AnmFile([], [anm.Image8(bytes([9, 1, 1, 1]), 1, 1, 1, b'\x01')], []).to_bytes())
    assert dd2.validate_pack(tmp_path) == ({'identity': True, 'anm': True}, [])


def test_bank_gate_rejects_corruption_and_empty_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(classcheck, 'check', lambda *a, **k: [])
    assert not dd2.validate_pack(tmp_path)[0]['anm']
    path = _bank(tmp_path)
    path.write_bytes(path.read_bytes()[:-1])
    assert not dd2.validate_pack(tmp_path)[0]['anm']


def test_original_fs_does_not_construct_installer(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('offline read constructed Installer')
    monkeypatch.setattr(modsys.Installer, '__init__', forbidden)
    (tmp_path / 'backups.json').write_text(json.dumps({}))
    fs = dd2.original_fs({'state_root': tmp_path, 'game_path': tmp_path})
    assert fs._backup_resolver('Database/Database_0.dat') == (None, None)
    fs.reset()
    assert not (tmp_path / 'backups').exists()


def test_cli_reviewed_switch_is_explicit_and_restored(tmp_path, monkeypatch):
    from d5lib import importcore
    path = Path(__file__).resolve().parents[1] / 'tools/import_game.py'
    spec = importlib.util.spec_from_file_location('coredd2_cli', path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    seen = []
    def run(game, **ctx):
        seen.append((game, os.environ['D5_DD2_REVIEWED_ABILITIES'], ctx['source_root']))
        return dict(built=0, total=0, gates_passed=0, regressions=[], seconds=0, out=str(tmp_path), exit=0)
    monkeypatch.setattr(importcore, 'run', run)
    # SOURCEPREP4-DD2: without --source-root the importer itself resolves the prepared folder from its
    # verified manifest, so the CLI must not pass a path that would be treated as an explicit root.
    monkeypatch.setenv('D5_DD2_REVIEWED_ABILITIES', 'ambient-value')
    monkeypatch.setenv('D5_IMPORT_OUT', str(tmp_path))
    assert cli.main(['dd2', '--out', str(tmp_path)]) == 0
    assert cli.main(['dd2', '--out', str(tmp_path), '--with-reviewed-abilities']) == 0
    assert [item[1] for item in seen] == ['0', '1']
    assert all(item[2] is None for item in seen)
    assert os.environ['D5_DD2_REVIEWED_ABILITIES'] == 'ambient-value'
