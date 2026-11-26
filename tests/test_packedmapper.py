from d5lib import packedmapper as mapper, packedmastery as pool


def test_native_and_unconfigured_are_untouched():
    raw = b'\x91' * pool.SPARE_SIZE
    assert mapper.map_family(4, 1010, {1350}, raw, {}).area == raw
    assert mapper.map_family(4, 1010, {1350}, raw, {}).slot == 4
    assert mapper.map_family(-1, 1360, {1350}, raw, {}).slot == -1


def test_stage_switch_and_independent_records():
    thresholds = {1350: (10,) * 6, 1360: (10,) * 6}
    a = mapper.map_family(-1, 1352, thresholds, bytes(pool.SPARE_SIZE), thresholds)
    assert a.slot == 52
    a_progress = pool.encode_pool({}, thresholds, 1350, (3, 0, 0, 0, 0, 0))
    switched = mapper.map_family(-1, 1360, thresholds, a_progress, thresholds)
    progress, staged, values = pool.decode_pool(switched.area, thresholds)
    assert (progress, staged, values) == ({1350: (3, 0, 0, 0, 0, 0)}, 1360, (0,) * 6)
    assert pool.decode_pool(a.area, thresholds)[1:] == (1350, (0,) * 6)


def test_refusal_preserves_unknown_or_full_data():
    thresholds = {f: (10,) * 6 for f in range(1350, 1750, 10)}
    bad = b'\x01' + bytes(pool.SPARE_SIZE - 1)
    refused = mapper.map_family(-1, 1350, thresholds, bad, thresholds)
    assert refused.slot == -1 and refused.area == bad and refused.reason
    entries = {f: (10,) * 6 for f in list(thresholds)[:38]}
    area = pool.encode_pool(entries, thresholds, 1730, (1, 0, 0, 0, 0, 0))
    refused = mapper.map_family(-1, 1740, thresholds, area, thresholds)
    assert refused.slot == -1 and refused.area == area and 'full' in refused.reason


def test_missing_threshold_and_invalid_area_refuse():
    area = pool.encode_pool({}, {}, 1350, (1, 0, 0, 0, 0, 0))
    refused = mapper.map_family(-1, 1360, {1350, 1360}, area, {})
    assert refused.slot == -1 and refused.area == area and refused.reason
    assert mapper.map_family(-1, 1350, {1350}, b'', {}).reason
