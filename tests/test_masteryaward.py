import pytest

from d5lib import masteryaward, packedmastery


def test_projection_matches_star_fix_examples():
    ts = (64, 256, 1024, 4096, 16384, 262144)
    assert masteryaward.project((0,) * 6, ts, 7) == ((7, 0, 0, 0, 0, 0), ())
    assert masteryaward.project((0,) * 6, ts, 400) == ((64, 256, 80, 0, 0, 0), (0, 1))
    assert masteryaward.project((64, 250, 0, 0, 0, 0), ts, 8) == ((64, 256, 2, 0, 0, 0), (1,))
    assert masteryaward.project((60, 10, 5, 0, 0, 0), ts, 8) == ((64, 14, 5, 0, 0, 0), (0,))


def test_preflight_refuses_when_post_award_stage_will_not_fit():
    ts = {14000 + i * 10: (10,) * 6 for i in range(39)}
    entries = {f: (10,) * 6 for f in list(ts)[:38]}
    area = packedmastery.encode_pool(entries, ts, 14380, (0,) * 6)
    with pytest.raises(ValueError, match='pool full'):
        masteryaward.preflight(area, 14380, ts, 1)
    assert packedmastery.decode_pool(area, ts)[2] == (0,) * 6


def test_completed_entry_can_fit_where_partial_cannot():
    ts = {14000 + i * 10: (1,) * 6 for i in range(39)}
    entries = {f: (1,) * 6 for f in list(ts)[:37]}
    area = packedmastery.encode_pool(entries, ts, 14370, (0,) * 6)
    candidate, completed = masteryaward.preflight(area, 14370, ts, 6)
    assert completed == tuple(range(6))
    assert packedmastery.decode_pool(candidate, ts)[2] == (1,) * 6


def test_preflight_refuses_unrepresentable_partial():
    thresholds = {14000: (0x1000001,) * 6}
    area = packedmastery.encode_pool({}, thresholds, 14000)
    with pytest.raises(ValueError, match='24 bits'):
        masteryaward.preflight(area, 14000, thresholds, 0x1000000)
