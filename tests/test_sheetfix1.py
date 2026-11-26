"""SHEETFIX1: a floating companion piece joins its frame; specks and big frames stay."""
import numpy as np

from d5lib import drpg


def piece(x, y, w, h):
    return dict(x=x, y=y, rgba=np.full((h, w, 4), 255, np.uint8))


def test_satellite_joins_nearest_frame_only():
    frame_a, frame_b = piece(100, 0, 200, 200), piece(500, 0, 200, 200)
    orb = piece(60, 160, 40, 40)            # 40 x 40 px, 20 px left of frame A
    speck = piece(320, 100, 10, 10)         # below min_box: left alone
    far = piece(900, 900, 40, 40)           # no frame near it
    out = drpg.merge_satellites([frame_a, frame_b, orb, speck, far])
    boxes = sorted((p["x"], p["y"], p["rgba"].shape[1], p["rgba"].shape[0]) for p in out)
    assert (60, 0, 240, 200) in boxes       # A grew to cover the orb
    assert (500, 0, 200, 200) in boxes and (320, 100, 10, 10) in boxes and (900, 900, 40, 40) in boxes
    assert len(out) == 4
