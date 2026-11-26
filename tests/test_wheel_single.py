"""Checks for the underlying unfiltered carousel and wheel metadata validation."""
import re

import pytest

from d5lib import newclasses as n


def test_one_list_carries_every_family():
    """47 vanilla families plus 67 mod families on the one list, nowhere near the 512-entry buffer."""
    families = [14010 + 10 * i for i in range(67)]
    src = n._carousel_src(families)
    table = src.split('new_fams:')[1]
    ids = [int(v) for v in re.findall(r'\.long ([\d, ]+)', table)[0].split(',')]
    assert ids == families + [0]                      # every family once, 0 ends the table
    assert len(n.HIRE_LIST) == 47
    assert len(n.HIRE_LIST) + len(families) == 114
    assert len(n.HIRE_LIST) + len(families) < n.CAROUSEL_CAP == 512
    assert f'cmp dword ptr [rdi + 0x208], {n.CAROUSEL_CAP}' in src    # the buffer bound is still checked


def test_the_carousel_keeps_the_vanilla_prefix_and_still_bounds_the_list():
    src = n._carousel_src([14010])
    assert 'cmp rbp, 0x2f' in src                     # the 47 vanilla entries come first
    assert 'cr_busy' in src                           # the one buffer is still guarded against re-entry
    assert 'jmp ' in src


def test_the_shared_buffer_is_plain_storage_again():
    """The legacy buffer offsets and guard stay unchanged with wheel metadata appended."""
    assert n.BUF_SIZE == n.BUF_GUARD + 16
    assert n.BUF_CLASSTAB == n.CAROUSEL_CAP * 8
    assert n.BUF_PROF == n.BUF_CLASSTAB + n.CLASSTAB_CAP * 4
    assert n.BUF_GUARD == n.BUF_PROF + n.CLASSTAB_CAP * 4


def test_wheel_metadata_is_still_validated_as_plain_metadata():
    from d5lib.wheelmeta import class_wheel, family_wheels
    assert class_wheel({'category': 'classes', 'wheel': 'dd2'}) == 'dd2'
    with pytest.raises(ValueError):
        class_wheel({'category': 'classes', 'wheel': 'DD2'})     # the token stays strict
    with pytest.raises(ValueError, match='assigned to both'):
        family_wheels([({'wheel': 'd4'}, [{'family': 14010}]),
                       ({'wheel': 'd1c'}, [{'family': 14010}])])
