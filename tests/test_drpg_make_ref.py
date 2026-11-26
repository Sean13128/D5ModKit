"""POSEREF1: tools/drpg_make_ref.py rebuilds the DRPG pose reference from the labelled sheet.

The rule is checked on a synthetic sheet (no game art in the repository).  The byte-for-byte check against the pin runs
only when D5_DRPG_REF_SHEET names the release sheet (Girl_Laharl_Swimsuit_SS.png) or a D5ModKit release zip."""
import hashlib
import importlib.util
import json
import os
import pickle
from pathlib import Path

import numpy as np
import pytest

KIT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('drpg_make_ref', KIT / 'tools' / 'drpg_make_ref.py')
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)


def _sheet(monkeypatch):
    """two labelled rows: stand (one drawn cell, one empty) and the idle row (one drawn cell)"""
    im = np.zeros((40, 60, 4), np.uint8)
    im[3:9, 4:7] = (200, 150, 120, 255)          # stand cell 0 (0..20 x 0..10): drawing at (3, 4)
    im[25:30, 2:9] = (90, 90, 230, 255)          # wait cell 0 (0..20 x 20..30)
    rows = [{'cells': [(0, 0, 10, 20), (10, 0, 20, 20)], 'label_box': (0, 0, 1, 1)},
            {'cells': [(0, 20, 12, 40)], 'label_box': (0, 0, 1, 1)}]
    monkeypatch.setattr(mk.framesheet, 'parse_sheet', lambda f: (im, rows))
    monkeypatch.setattr(mk.framesheet, 'guess_rows',
                        lambda im_, rows_: [('stand', 'front', 'x'), ('wait', 'back', 'y')])


def test_one_entry_per_drawn_cell_in_reading_order(monkeypatch):
    _sheet(monkeypatch)
    ref = mk.build(b'')
    assert [(e['name'], e['view'], e['sheet'], e['pos']) for e in ref] == [
        ('stand', 'front', 'front', 0), ('wait', 'back', 'wait_back', 0)]          # the empty cell is skipped
    stand, wait = ref
    assert list(stand) == ['name', 'view', 'sheet', 'canvas', 'offset', 'pos', 'mask', 'feats', 'found']
    assert stand['canvas'] == (20, 10) and stand['offset'] == (3, 4) and stand['mask'].shape == (6, 3)
    assert wait['canvas'] == (20, 12) and wait['offset'] == (5, 2) and wait['mask'].all()
    assert [f.shape for f in stand['feats']] == [(6, 3)] * 3 and stand['found'] is True
    assert mk.compare(ref, pickle.loads(pickle.dumps(ref))) == []


def test_unlabelled_row_is_refused(monkeypatch):
    _sheet(monkeypatch)
    monkeypatch.setattr(mk.framesheet, 'guess_rows', lambda im_, rows_: [('', 'front', None), ('wait', 'back', 'y')])
    with pytest.raises(ValueError, match='unlabelled sheet row'):
        mk.build(b'')


def test_other_sheet_is_refused_and_existing_output_kept(tmp_path):
    sheet = tmp_path / 'x.png'
    sheet.write_bytes(b'not the release sheet')
    with pytest.raises(SystemExit, match='is not the release sheet'):
        mk.main(['--sheet', str(sheet), '--out', str(tmp_path / 'o.pickle')])
    out = tmp_path / 'o.pickle'
    out.write_bytes(b'keep')
    with pytest.raises(SystemExit, match='exists'):
        mk.main(['--sheet', str(sheet), '--out', str(out), '--any-sheet'])
    assert out.read_bytes() == b'keep'


@pytest.mark.skipif(not os.environ.get('D5_DRPG_REF_SHEET'), reason='D5_DRPG_REF_SHEET (release sheet or zip) not set')
def test_release_sheet_rebuilds_the_pinned_file(tmp_path):
    src = os.environ['D5_DRPG_REF_SHEET']
    out = tmp_path / 'drpg_ref_humanoid.pickle'
    flag = '--release-zip' if src.lower().endswith('.zip') else '--sheet'
    assert mk.main([flag, src, '--out', str(out)]) == 0
    pin = json.loads((KIT / 'd5lib/importers/drpg-pose-reference.json').read_text(encoding='utf-8'))
    data = out.read_bytes()
    assert len(data) == pin['size'] and hashlib.sha256(data).hexdigest() == pin['sha256']
