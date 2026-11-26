import pytest
from d5lib import anm, dd2source


def test_converted_image_markers_normalized_without_changing_pixels():
    texture = anm.Image8(bytes.fromhex('09010101'), 4, 4, 0x10000, bytes(range(16)))
    palette = anm.Image8(bytes.fromhex('00010101'), 1, 1, 1, b'\x01\x02\x03\x04')
    bank = anm.AnmFile([], [texture], [palette])
    assert dd2source.normalize_image_byte_order(bank) == 1
    assert texture.unk == 1 and palette.unk == 1
    assert texture.data == bytes(range(16)) and palette.data == b'\x01\x02\x03\x04'
    assert dd2source.normalize_image_byte_order(bank) == 0
    palette.unk = 2
    with pytest.raises(ValueError):
        dd2source.normalize_image_byte_order(bank)
