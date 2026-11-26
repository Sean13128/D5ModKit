# Custom mastery storage prototype

`d5lib.classmastery` is an **inactive bytes-only codec prototype**. Nothing calls
it from the installer, save tools, native code or game. It does not implement
custom class experience, mastery rewards, subclass selection or save support.
It has no file I/O. Tests use synthetic buffers only.

The proposed companion format keeps custom progress outside native unit records.
It assigns state by explicit family ID and stable unit serial, independent of
mod order, resource leases, display names and physical sprite slots. Every game
version retains its own registered ID. The caller supplies the complete registry
and a SHA-256 digest of its authoritative source, preserving variant/alias
provenance even where several source rows share one numeric family. Such rows do
not acquire separate counters automatically; their identity semantics must be
resolved before implementation.

## Prototype API

```python
from d5lib import classmastery as cm

registry = cm.Registry((14080, 14550), registry_source_sha256_bytes)
snapshot = cm.Snapshot(generation, native_snapshot_sha256_bytes, (
    cm.Unit(serial, subclass=14080, progress=(
        cm.Progress(14080, (12, 0, 0, 0, 0, 0), awarded_mask=0),
    )),
))
companion = cm.encode(snapshot, registry)
restored = cm.decode(companion, registry,
                     native_digest=native_snapshot_sha256_bytes,
                     generation=generation)
```

`decode` requires an expected generation supplied by a future transaction
controller. A digest of native bytes alone cannot distinguish two otherwise
identical native snapshots with different custom-only progress. Reading the
generation out of the companion and treating that as the expected generation
would defeat this check. This prototype supplies no such controller.

## Version 1 layout

All integers are little endian. The header is 128 bytes: magic `D5KCMST\0`,
version u16, zero flags u16, header length u32, generation u64, unit count u32,
payload length u32, native snapshot SHA-256, registry SHA-256 and SHA-256 of the
preceding header fields plus payload. The registry digest includes a domain
marker, the source digest and sorted explicit numeric family bases.

Each unit has an 80-byte header: nonzero serial u64, selected subclass u32,
family count u32 and eight u64 completion-bonus bookkeeping accumulators.
Each family entry is 32 bytes: family u32, six exact u32 counters, a six-bit
awarded-rank mask u8, and three reserved zero bytes. Unit serials and family
entries are strictly ascending on disk. No float, lossy packing, eviction or
donor-state aliasing is used. Zero counters and masks remain representable.

The accumulators and masks are storage fields, not implemented award semantics.
There is no claim that a stored counter equals displayed XP, that a threshold
was earned, or that applying a wide accumulator to a native narrow field is
valid. Thresholds, rounding, reward timing, stacking and cap policy need a
separate native implementation and tests.

The format allows 128 units and 4096 families. Dense size is
`128 + units * (80 + 32 * families)`. Current supported community bases must
be multiples of ten from 10000 through 32760, excluding 20000–21999; only rank
digits 0–5 are accepted. The format ceiling exceeds every base in that range.
This is a codec capacity, not a claim about native content or menu capacity.

Malformed versions, flags, sizes, reserved bytes, digest mismatches, duplicate
serials/families, unknown families, invalid subclasses, noncanonical order and
integer overflow raise an error before any snapshot is returned. Checksums
detect corruption and pairing mistakes; they are not authentication.

## Integration contract still required

Keep native families on their existing storage paths. Custom award/read/menu/
evility consumers need one consistent owner of this extended state. Stage a
single family only after proving every staging reader, writer, copy and
reincarnation boundary; global unlock flags and sprite leases are separate.

A future persistence controller must bind native bytes, companion bytes,
registry source and generation in a committed manifest. Preserve previous
complete generations. Write pending files and verify them before committing
the manifest; recover only complete matching generations after a crash. Two
independent file replacements are not a transaction. A missing or stale pair
must stop extended-state loading, never reset mastery to zero. No legacy pool
migration or physical-slot reassignment may happen implicitly.

Before enabling this: prove save/load writer ownership, autosave and manual save
transactions, crash points, copied/reordered/dismissed units, disabled mods,
registry changes, cross-generation rollback, UI enumeration and all native XP
and completion-bonus consumers. Rollback restores an entire previously accepted
native/companion/manifest set; removing the hook while silently retaining a
custom-dependent save is not a restoration procedure.

Run the bounded source checks with
`python -m unittest tests.test_classmastery`. Native and gameplay acceptance
remain separate and have not been supplied by this prototype.
