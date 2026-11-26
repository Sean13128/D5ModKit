"""Resolve the D4 importer's checked-in rule data for tests (SOURCEPREP4-D4).

The data files carry game text as SHA-256 references, so a test that asserts on a name or a
description needs the text pool the build uses: the prepared D4 source (``D5_SOURCE_DIR``) or the
project's own diagnostic copy, plus the Disgaea 5 tables (the clean depot copy when present, else the
kit's backup index).  A machine without them skips the module rather than failing.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from d5lib.importers import _d4_source

PROJECT = Path('/Volumes/Data/Projects/D5')
D4_DIAGNOSTIC = PROJECT / 'Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+'
D5_CLEAN = PROJECT / 'Disgaea Source/Disgaea 5 Complete (Steam 803600)'
GAME = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete')
STATE = GAME / 'D5ModKit/state/games/Disgaea_5_Complete-d8040a88'

_cache = {}


class Unavailable(Exception):
    pass


def _at_import(fn):
    """Call an import-time loader, turning an unavailable source into a module-level skip."""
    try:
        return fn()
    except Unavailable as exc:
        pytest.skip(str(exc), allow_module_level=True)


def files():
    if 'files' in _cache:
        return _cache['files']
    root = None if os.environ.get('D5_SOURCE_DIR') else (D4_DIAGNOSTIC if D4_DIAGNOSTIC.is_dir() else None)
    if root is None and not os.environ.get('D5_SOURCE_DIR'):
        raise Unavailable('no prepared D4 source (D5_SOURCE_DIR) and no Disgaea Source copy')
    try:
        _cache['files'] = _d4_source.data_dir(root)
    except _d4_source.D4SourceError as exc:
        raise Unavailable(f'D4 source not usable: {exc}') from exc
    return _cache['files']


def data_or_skip():
    try:
        return files().data('EN')
    except Unavailable as exc:
        pytest.skip(str(exc))


def d5_fs():
    if 'fs' in _cache:
        return _cache['fs']
    from d5lib import gamefs
    fs = None
    if D5_CLEAN.is_dir():
        fs = gamefs.GameFS(str(D5_CLEAN))
    else:
        try:
            from d5lib.importers.dd2 import original_fs
            fs = original_fs(dict(game_path=str(GAME), state_root=str(STATE)))
        except Exception:                                   # noqa: BLE001 - no game on this machine
            fs = None
    _cache['fs'] = fs
    return fs


def pool():
    if 'pool' not in _cache:
        _cache['pool'] = _at_import(lambda: _d4_source.text_pool(files(), d5_fs()))
    return _cache['pool']


def overlay():
    if 'overlay' not in _cache:
        _cache['overlay'] = _at_import(lambda: pool().resolve_doc(_d4_source.overlay()))
    return _cache['overlay']


def mods():
    return overlay()['mods']


def overlay_path():
    """A path to the resolved overlay (for tests that re-read it inside each test)."""
    if 'path' not in _cache:
        folder = Path(tempfile.mkdtemp(prefix='d4rules-'))
        path = folder / 'd4-evility-overlay.json'
        path.write_text(json.dumps(overlay(), indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        _cache['path'] = path
    return _cache['path']


def additions():
    if 'additions' not in _cache:
        doc = _at_import(lambda: pool().resolve_doc(json.loads((_d4_source.ADDITIONS).read_text(encoding='utf-8'))))
        _cache['additions'] = doc
    return _cache['additions']
