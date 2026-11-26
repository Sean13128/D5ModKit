"""Inactive, bytes-only prototype of versioned custom-class mastery storage.

This is not a save reader, writer, native hook or installer. Callers provide a
registry and the digest of an already obtained native snapshot. No filesystem
access or implicit migration is performed. Native mastery remains native.
"""
from dataclasses import dataclass
import hashlib
import struct


MAGIC = b"D5KCMST\0"
VERSION = 1
MAX_UNITS = 128
MAX_FAMILIES = 4096
RANKS = 6
NATIVE_FAMILIES = tuple(range(1010, 1270, 10)) + tuple(range(2010, 2220, 10))
_PREFIX = struct.Struct("<8sHHIQII32s32s")
_UNIT = struct.Struct("<QII8Q")
_ENTRY = struct.Struct("<I6IB3s")
HEADER_SIZE = _PREFIX.size + 32
MAX_BYTES = HEADER_SIZE + MAX_UNITS * (_UNIT.size + MAX_FAMILIES * _ENTRY.size)


def _uint(value, bits, name):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f"{name} must be an unsigned {bits}-bit integer")
    return value


def _digest(value, name):
    if type(value) is not bytes or len(value) != 32:
        raise ValueError(f"{name} must be 32 digest bytes")
    return value


def _family(value):
    _uint(value, 32, "family")
    if value % 10 or not 10000 <= value <= 32760 or 20000 <= value < 22000:
        raise ValueError("family must be an unreserved community family base")
    return value


@dataclass(frozen=True)
class Registry:
    """Explicit identities, including each game version independently.

    Sequence order and class names do not assign storage. The complete supplied
    family set is fingerprinted; adding/removing a family requires an explicit
    caller-controlled migration, even if that family has no progress yet.
    """
    families: tuple
    source_digest: bytes

    def __post_init__(self):
        _digest(self.source_digest, "registry source digest")
        values = tuple(self.families)
        if len(values) > MAX_FAMILIES:
            raise ValueError("registry capacity exceeded")
        for value in values:
            _family(value)
        if len(set(values)) != len(values):
            raise ValueError("duplicate registry family")
        object.__setattr__(self, "families", tuple(sorted(values)))

    @property
    def digest(self):
        payload = b"D5Kit class mastery registry v1\0" + self.source_digest
        payload += struct.pack("<I", len(self.families))
        payload += struct.pack(f"<{len(self.families)}I", *self.families)
        return hashlib.sha256(payload).digest()


@dataclass(frozen=True)
class Progress:
    family: int
    counters: tuple = (0,) * RANKS
    awarded_mask: int = 0


@dataclass(frozen=True)
class Unit:
    serial: int
    subclass: int = 0
    progress: tuple = ()
    # Wide bookkeeping only: applying these values to D5's narrow fields is
    # explicitly unimplemented. A runtime must define its cap policy first.
    completion_bonuses: tuple = (0,) * 8


@dataclass(frozen=True)
class Snapshot:
    generation: int
    native_digest: bytes
    units: tuple = ()


def _subclass(value, families):
    _uint(value, 32, "subclass")
    if value and (value % 10 >= RANKS or value // 10 * 10 not in families):
        raise ValueError("subclass must name a declared family and supported rank")


def encode(snapshot, registry):
    """Return canonical companion bytes, without reading or changing a save.

    All partial counters are retained; there is no eviction, donor alias or
    physical-slot reference. Zero entries may be retained. Input order is not
    significant. An unknown identity or unrepresentable value is an error.
    """
    _uint(snapshot.generation, 64, "generation")
    native_digest = _digest(snapshot.native_digest, "native digest")
    units = tuple(snapshot.units)
    if len(units) > MAX_UNITS:
        raise ValueError("unit capacity exceeded")
    families = set(registry.families)
    subclass_families = families | set(NATIVE_FAMILIES)
    seen_units = set()
    encoded_units = []
    for unit in units:
        _uint(unit.serial, 64, "unit serial")
        if unit.serial == 0 or unit.serial in seen_units:
            raise ValueError("zero or duplicate unit serial")
        seen_units.add(unit.serial)
        _subclass(unit.subclass, subclass_families)
        bonuses = tuple(unit.completion_bonuses)
        if len(bonuses) != 8:
            raise ValueError("eight completion bonus accumulators required")
        for value in bonuses:
            _uint(value, 64, "completion bonus")
        entries = tuple(unit.progress)
        if len(entries) > len(families):
            raise ValueError("family capacity exceeded")
        seen = set()
        encoded_entries = []
        for entry in entries:
            _family(entry.family)
            if entry.family not in families or entry.family in seen:
                raise ValueError("unknown or duplicate progress family")
            seen.add(entry.family)
            counters = tuple(entry.counters)
            if len(counters) != RANKS:
                raise ValueError("six rank counters required")
            for value in counters:
                _uint(value, 32, "rank counter")
            _uint(entry.awarded_mask, RANKS, "awarded rank mask")
            encoded_entries.append((entry.family, _ENTRY.pack(
                entry.family, *counters, entry.awarded_mask, bytes(3))))
        body = _UNIT.pack(unit.serial, unit.subclass, len(entries), *bonuses)
        body += b"".join(data for _, data in sorted(encoded_entries))
        encoded_units.append((unit.serial, body))
    payload = b"".join(data for _, data in sorted(encoded_units))
    prefix = _PREFIX.pack(MAGIC, VERSION, 0, HEADER_SIZE, snapshot.generation,
                          len(units), len(payload), native_digest, registry.digest)
    return prefix + hashlib.sha256(prefix + payload).digest() + payload


def decode(data, registry, *, native_digest, generation):
    """Verify a companion against an exact native snapshot and registry.

    A missing/mismatched companion must never be interpreted as zero mastery by
    the eventual runtime. This function raises instead of guessing or rebinding.
    The digest detects corruption/pair mismatch; it is not authentication.
    """
    _digest(native_digest, "native digest")
    _uint(generation, 64, "expected generation")
    if type(data) is not bytes or not HEADER_SIZE <= len(data) <= MAX_BYTES:
        raise ValueError("invalid companion length/type")
    magic, version, flags, header_size, saved_generation, count, size, saved_native, saved_registry = _PREFIX.unpack_from(data)
    if (magic, version, flags, header_size) != (MAGIC, VERSION, 0, HEADER_SIZE):
        raise ValueError("unsupported companion format/version/flags")
    if count > MAX_UNITS or size != len(data) - HEADER_SIZE:
        raise ValueError("invalid companion count/size")
    if saved_native != native_digest or saved_registry != registry.digest or saved_generation != generation:
        raise ValueError("native snapshot, generation or registry mismatch")
    payload = data[HEADER_SIZE:]
    if data[_PREFIX.size:HEADER_SIZE] != hashlib.sha256(data[:_PREFIX.size] + payload).digest():
        raise ValueError("companion digest mismatch")
    offset = 0
    units = []
    for _ in range(count):
        if offset + _UNIT.size > len(payload):
            raise ValueError("truncated unit")
        serial, subclass, entries, *bonuses = _UNIT.unpack_from(payload, offset)
        offset += _UNIT.size
        if entries > len(registry.families) or offset + entries * _ENTRY.size > len(payload):
            raise ValueError("invalid or truncated progress entries")
        progress = []
        for _ in range(entries):
            family, *values = _ENTRY.unpack_from(payload, offset)
            offset += _ENTRY.size
            if values[-1] != bytes(3):
                raise ValueError("nonzero reserved progress bytes")
            progress.append(Progress(family, tuple(values[:RANKS]), values[RANKS]))
        units.append(Unit(serial, subclass, tuple(progress), tuple(bonuses)))
    if offset != len(payload):
        raise ValueError("trailing companion bytes")
    result = Snapshot(generation, saved_native, tuple(units))
    # Revalidation also refuses duplicate/unknown identities and noncanonical
    # ordering, without ever exposing a partially validated snapshot.
    if encode(result, registry) != data:
        raise ValueError("noncanonical companion")
    return result


def dense_size(family_count, unit_count=MAX_UNITS):
    """Worst-case format size when every unit has all supplied families."""
    _uint(family_count, 32, "family count")
    _uint(unit_count, 32, "unit count")
    if family_count > MAX_FAMILIES or unit_count > MAX_UNITS:
        raise ValueError("format capacity exceeded")
    return HEADER_SIZE + unit_count * (_UNIT.size + family_count * _ENTRY.size)
