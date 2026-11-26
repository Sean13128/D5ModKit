"""Offline specification for safe packed mastery awards; not runtime code.

The projection follows the STARS-FIX base-rank writer loop. It accepts the
already-normalized nonnegative native award amount; native clamping, callbacks,
reentrancy and actual side effects are outside this specification.
"""
from . import packedmastery as packed


def project(counters, thresholds, amount):
    """Return (counters, newly completed rank indices) for a base-rank award."""
    if len(counters) != 6 or len(thresholds) != 6:
        raise ValueError('six counters and thresholds required')
    if type(amount) is not int or not 0 <= amount <= 0x7fffffff:
        raise ValueError('expected a normalized nonnegative award')
    if any(type(t) is not int or not 0 < t <= 0xffffffff for t in thresholds):
        raise ValueError('invalid thresholds')
    if any(type(v) is not int or not 0 <= v <= t for v, t in zip(counters, thresholds)):
        raise ValueError('invalid counters')
    result = list(counters)
    completed = []
    for i, (old, threshold) in enumerate(zip(counters, thresholds)):
        new = min(threshold, old + amount)
        result[i] = new
        if new != threshold:
            break
        if old < threshold:
            completed.append(i)
        if i == 5:
            break
        amount = old + amount - threshold
    return tuple(result), tuple(completed)


def preflight(area, family, thresholds, amount):
    """Return a candidate staged area and completions, or raise without mutation.

    Verify that the projected stage can be packed after the award, not merely
    that the stage switch itself fits. The caller must not treat this as an
    atomic reservation across native callbacks or concurrent operations.
    """
    candidate = packed.switch_stage(area, family, thresholds)
    entries, staged, counters = packed.decode_pool(candidate, thresholds)
    updated, completed = project(counters, thresholds[family], amount)
    entries[staged] = updated
    # Encoding with no active stage validates both capacity and 24-bit partials.
    packed.encode_pool(entries, thresholds)
    return packed.encode_pool({k: v for k, v in entries.items() if k != staged},
                              thresholds, staged, updated), completed
