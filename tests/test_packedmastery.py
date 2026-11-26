import struct
import pytest
from d5lib import packedmastery as p

T = (64, 256, 1024, 4096, 16384, 262144)


def test_roundtrip_and_staging():
    progress = {1350: (64, 12, 0, 0, 0, 0), 14080: T}
    data = p.encode_pool(progress, {1350: T, 14080: T}, 15000, (2, 0, 0, 0, 0, 0))
    assert p.decode_pool(data, {1350: T, 14080: T}) == (progress, 15000, (2, 0, 0, 0, 0, 0))


def test_legacy_requires_explicit_ownership_and_roundtrips():
    original = struct.pack('<6I', 64, 5, 2, 0, 0, 0) + bytes(120)
    with pytest.raises(ValueError, match='unowned'):
        p.migrate_legacy(original, {}, {})
    packed = p.migrate_legacy(original, {1350: 47}, {1350: T})
    assert p.decode_pool(packed, {1350: T})[0][1350] == (64, 5, 2, 0, 0, 0)
    assert original[:4] == b'\x40\0\0\0'


def test_full_pool_refuses_loss():
    progress = {10000 + i*10: T for i in range(39)}
    with pytest.raises(ValueError, match='pool full'):
        p.encode_pool(progress, {f: T for f in progress})
    progress.pop(10380)
    data = p.encode_pool(progress, {f: T for f in progress})
    assert len(p.decode_pool(data, {f: T for f in progress})[0]) == 38


def test_stage_switch_is_atomic_on_overflow_and_restores_progress():
    families = [10000 + i * 10 for i in range(40)]
    thresholds = {f: T for f in families}
    data = p.encode_pool({f: T for f in families[:38]}, thresholds, families[38], T)
    with pytest.raises(ValueError, match='pool full'):
        p.switch_stage(data, families[39], thresholds)
    assert p.decode_pool(data, thresholds)[1:] == (families[38], T)
    swapped = p.switch_stage(data, families[0], thresholds)
    entries, active, counters = p.decode_pool(swapped, thresholds)
    assert active == families[0] and counters == T
    assert entries[families[38]] == T and len(entries) == 38


def test_rejects_malformed_and_lossy_input():
    with pytest.raises(ValueError, match='24 bits'):
        p.encode_pool({1350: (0x1000000, 0, 0, 0, 0, 0)}, {1350: (0x1000001,)*6})
    with pytest.raises(ValueError, match='conflicting'):
        p.migrate_legacy(bytes(144), {1350: 47, 1360: 47}, {})
    with pytest.raises(ValueError, match='garbage'):
        p.decode_pool(p.MAGIC + bytes(2) + bytes(3) + b'X' + bytes(112) + bytes(24), {})
