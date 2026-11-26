"""Single-cell resident icons must contain each entire source stand."""
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from d5lib import anm, outfits


def _fixture(monkeypatch, multipart=False):
    texture = SimpleNamespace(width=64, height=32, data=b'')
    icon = SimpleNamespace(textures=[texture], palettes=[object() for _ in range(10)])
    source = object()
    front = SimpleNamespace(x=0, y=0, w=20, h=30)
    back = SimpleNamespace(x=20, y=0, w=35, h=20)
    monkeypatch.setattr(anm, 'list_animations', lambda _: [{'id': 1, 'index': 1}, {'id': 7, 'index': 7}])
    def evaluate(_icon, index, _time):
        item = SimpleNamespace(tex_global=0, cell=front if index == 1 else back)
        return [item, item] if multipart else [item]
    monkeypatch.setattr(anm, 'evaluate', evaluate)
    def frame(_source, index, time, bounds):
        image = Image.new('RGBA', (640, 580))
        draw = ImageDraw.Draw(image)
        draw.rectangle((200, 100, 339, 279), fill=('red' if index == 1 else 'blue'))
        return image
    monkeypatch.setattr(anm, 'render_frame', frame)
    palettes = []
    monkeypatch.setattr(anm, 'set_palette', lambda _icon, i, pal: palettes.append((i, pal)))
    return icon, source, palettes


def test_complete_views_fit_actual_cells_and_keep_palette_count(monkeypatch):
    icon, source, palettes = _fixture(monkeypatch)
    assert outfits.repaint_single_cell_monster_icon(icon, source) is icon
    pixels = np.frombuffer(icon.textures[0].data, dtype=np.uint8).reshape(32, 64)
    assert np.count_nonzero(pixels[:, :20]) > 0
    assert np.count_nonzero(pixels[:, 20:55]) > 0
    assert not np.any(pixels[30:, :20])
    assert not np.any(pixels[20:, 20:55])
    assert not np.any(pixels[:, 55:])
    # Each palette has its own transparent index, and both source colours survive.
    assert len(palettes) == 10
    pal = palettes[0][1]
    assert pal[0, 3] == 0
    assert any(row[0] > 200 and row[2] < 20 for row in pal)
    assert any(row[2] > 200 and row[0] < 20 for row in pal)


def test_rejects_segmented_icon(monkeypatch):
    icon, source, _ = _fixture(monkeypatch, multipart=True)
    with pytest.raises(ValueError, match='not single-cell'):
        outfits.repaint_single_cell_monster_icon(icon, source)
