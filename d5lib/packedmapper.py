"""Offline specification for site-aware packed mastery mapping.

This is not a machine-code hook.  It specifies the transaction and refusal
contract that a future runtime must implement, using the codec's exact format.
Cryswar's Overlord mapper supplies the site/record design (Unlicense); unlike
that implementation this contract never evicts or truncates progress.
"""
from dataclasses import dataclass

from . import packedmastery

STAGE_SLOT = 52
NO_SLOT = -1


@dataclass(frozen=True)
class Mapping:
    slot: int
    area: bytes
    reason: str | None = None


def map_family(native_slot, target, configured, area, thresholds):
    """Model a read-side mapper call with an already authenticated unit.

    Native answers pass through unchanged. Unknown/legacy bytes, malformed
    pools, missing thresholds, and an unrepresentable stage refuse without
    changing the record. ``reason`` makes refusals visible to tooling. A
    successful stage switch does *not* reserve space for a subsequent award;
    a real writer must separately preflight its actual result before effects.
    """
    original = bytes(area)
    if native_slot != NO_SLOT:
        return Mapping(native_slot, original)
    family = target - target % 10
    if family not in configured:
        return Mapping(NO_SLOT, original)
    if len(original) != packedmastery.SPARE_SIZE:
        return Mapping(NO_SLOT, original, 'invalid mastery area size')
    if not any(original):
        candidate = packedmastery.encode_pool({}, thresholds)
    elif original[:2] == packedmastery.MAGIC:
        candidate = original
    else:
        return Mapping(NO_SLOT, original, 'unknown or legacy mastery data')
    try:
        candidate = packedmastery.switch_stage(candidate, family, thresholds)
    except (ValueError, KeyError) as exc:
        return Mapping(NO_SLOT, original, str(exc))
    return Mapping(STAGE_SLOT, candidate)
