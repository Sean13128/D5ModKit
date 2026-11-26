"""A face above 32767 never draws (the game reads animation ids as a signed short): refuse to write it."""
import pytest

from d5lib import facepatch


def test_a_face_above_32767_is_refused_before_anything_is_parsed():
    with pytest.raises(ValueError) as exc:
        facepatch.add_faces(b"not even lzs", [(40170, 10040, None)])
    assert "40170" in str(exc.value) and "signed 16-bit" in str(exc.value)


def test_a_banner_above_32767_is_refused_too():
    with pytest.raises(ValueError):
        facepatch.add_faces(b"not even lzs", [], banners=[(40170, 40)])


def test_in_range_ids_get_past_the_guard():
    # 24940 (10000 + art number 14940) is fine; the garbage payload then fails later, which proves the guard let it through
    with pytest.raises(Exception) as exc:
        facepatch.add_faces(b"not even lzs", [(24940, 10040, None)])
    assert "signed 16-bit" not in str(exc.value)
