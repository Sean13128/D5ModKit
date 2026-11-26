"""Offline packed mastery codec; not an installed runtime or a save migrator.

Encoding follows Cryswar's Overlord d5_custom_classes.c (Unlicense): five
24-byte native slots store a versioned compact pool and a sixth is the active
stage. Unlike the reference implementation, this codec rejects overflow and
lossy values rather than evicting progress. Callers must supply the old lease
map and thresholds explicitly. No filesystem or save is modified here.
"""
import struct

POOL_SIZE = 120
STAGE_SIZE = 24
SPARE_SIZE = POOL_SIZE + STAGE_SIZE
MAGIC = b'\xc5\x01'
RANKS = 6


def _u24(b):
    return int.from_bytes(b, 'little')


def _put24(v):
    if not 0 <= v <= 0xffffff:
        raise ValueError('partial mastery cannot be represented in 24 bits')
    return v.to_bytes(3, 'little')


def _family(family):
    if type(family) is not int or family % 10 or not 0 < family // 10 < 8192:
        raise ValueError('family must be a nonzero base representable in 13 bits')
    return family // 10


def _entry(family, values, thresholds):
    fid = _family(family)
    if len(values) != RANKS or len(thresholds) != RANKS:
        raise ValueError('six counters and thresholds required')
    if any(type(v) is not int or not 0 <= v <= 0xffffffff for v in values):
        raise ValueError('invalid counter')
    if any(type(t) is not int or not 0 < t <= 0xffffffff for t in thresholds):
        raise ValueError('invalid threshold')
    if any(v > t for v, t in zip(values, thresholds)):
        raise ValueError('counter exceeds threshold; refusing lossy migration')
    k = 0
    while k < RANKS and values[k] == thresholds[k]:
        k += 1
    n = max((i - k + 1 for i in range(k, RANKS) if values[i]), default=0)
    if not k and not n:
        return b''
    return _put24(fid | (k << 13) | (n << 16)) + b''.join(_put24(v) for v in values[k:k+n])


def encode_pool(progress, thresholds, staged_family=0, stage=(0,)*RANKS):
    """Encode {family: six counters}; never discard or silently truncate.

    staged_family identifies the full-width counters stored in slot 52, and
    must not also be present in progress. Thresholds maps family to six values.
    """
    if staged_family:
        stage_id = _family(staged_family)
        if staged_family in progress:
            raise ValueError('staged family also exists in pool')
    else:
        stage_id = 0
        if any(stage):
            raise ValueError('unowned staging counters')
    if len(stage) != RANKS or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in stage):
        raise ValueError('invalid staging counters')
    entries = b''.join(_entry(f, progress[f], thresholds[f]) for f in sorted(progress))
    if len(entries) > POOL_SIZE - 4:
        raise ValueError('packed mastery pool full; no progress was discarded')
    pool = MAGIC + struct.pack('<H', stage_id) + entries
    return pool.ljust(POOL_SIZE, b'\0') + struct.pack('<6I', *stage)


def decode_pool(data, thresholds):
    """Return (pool entries, staged family, stage counters); validate structure."""
    if len(data) != SPARE_SIZE or data[:2] != MAGIC:
        raise ValueError('not a recognized packed mastery area')
    staged = struct.unpack_from('<H', data, 2)[0] * 10
    if staged:
        _family(staged)
    stage = struct.unpack_from('<6I', data, POOL_SIZE)
    if not staged and any(stage):
        raise ValueError('unowned staging counters')
    out = {}
    pos = 4
    while pos + 3 <= POOL_SIZE:
        h = _u24(data[pos:pos+3])
        if not h:
            break
        fid, k, n = h & 0x1fff, (h >> 13) & 7, (h >> 16) & 7
        family = fid * 10
        if h >> 19 or not fid or k > RANKS or n > RANKS - k or family in out or family == staged:
            raise ValueError('invalid packed entry')
        end = pos + 3 + 3*n
        if end > POOL_SIZE:
            raise ValueError('truncated packed entry')
        ts = thresholds[family]
        if len(ts) != RANKS or any(type(t) is not int or not 0 < t <= 0xffffffff for t in ts):
            raise ValueError('invalid thresholds')
        values = list(ts[:k]) + [_u24(data[i:i+3]) for i in range(pos+3, end, 3)]
        values += [0] * (RANKS - len(values))
        if any(v > t for v, t in zip(values, ts)):
            raise ValueError('counter exceeds threshold')
        out[family] = tuple(values)
        pos = end
    if any(data[pos:POOL_SIZE]):
        raise ValueError('garbage after packed entries')
    return out, staged, stage


def switch_stage(data, family, thresholds):
    """Return a new area with ``family`` staged, or raise without changing it.

    This is an offline specification of the required atomic switch, not the
    executable hook. In particular a full pool must retain the old stage.
    """
    _family(family)
    progress, staged, counters = decode_pool(data, thresholds)
    if staged == family:
        return bytes(data)
    if staged:
        # Validate before altering the candidate: the full-width stage must be
        # exactly representable when it returns to the packed pool.
        _entry(staged, counters, thresholds[staged])
        progress[staged] = counters
    next_counters = progress.pop(family, (0,) * RANKS)
    return encode_pool(progress, thresholds, family, next_counters)


def migrate_legacy(spare, leases, thresholds):
    """Convert 144 legacy bytes using an explicit complete {family: slot} map.

    Fail on unowned nonzero slots or overflow. Input bytes remain unchanged.
    Identity/class/flag migration and writing a save are separate operations.
    """
    if len(spare) != SPARE_SIZE:
        raise ValueError('expected exactly six native slots')
    if len(set(leases.values())) != len(leases) or any(type(s) is not int or s not in range(47, 53) for s in leases.values()):
        raise ValueError('invalid or conflicting legacy leases')
    progress = {}
    for family, slot in leases.items():
        _family(family)
        values = struct.unpack_from('<6I', spare, (slot - 47)*24)
        if any(values):
            progress[family] = values
    occupied = set(leases.values())
    for slot in range(47, 53):
        if slot not in occupied and any(spare[(slot-47)*24:(slot-46)*24]):
            raise ValueError('unowned legacy mastery data')
    return encode_pool(progress, thresholds)
