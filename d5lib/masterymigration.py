"""Explicit copied-save conversions between the six legacy mastery slots and the packed pool.

Two operations, both on copies and both refusing anything they cannot prove:

* ``migrate_copy``  legacy slot counters -> a packed pool entry.  Which family the counters
  are written as is decided by ``packed`` (the family bases the build declares packed) via
  ``plan()``: a six-slot family that the build itself packs is written as *itself*
  (1350 -> 1350, no class, row, sub-class or flag edit at all).  Only a family the build
  does not pack may be re-homed to another family, which does rewrite identity fields.
* ``clear_legacy``  zero the legacy area of the units the packed hook would otherwise fail
  closed on, so the hook's own all-zero initialisation can own them.  Nothing else changes.

This is an offline conversion; native loading and gameplay remain unverified.
"""
import os
import struct
import tempfile
from pathlib import Path

from . import newclasses, ownership, packedmastery, savegame

OLD = 1350
MASTERY = 0x30A4 + 47 * 24
SUBCLASS = 0x35AC
IDENTITY = 'identity'
REHOME = 'rehome'


def plan(*, leases, packed=(), target=None):
    """Decide where OLD's counters land, before a save is touched.

    Returns ``{'mode': 'identity'|'rehome', 'family': int}``.

    The pool entry carries its own family id, so a build that declares OLD packed
    (INTEG7 does: the Armor Knight pilot's ``patches/classes/mastery.json`` declares
    1350, and the LIVE5 set is packed because it holds 29 families) needs **no**
    re-homing: the legacy slot-47 counters are simply re-encoded as the 1350 entry.
    Re-homing is only for a build that packs some other family and not 1350, and it is
    then an explicit, separate decision -- never the default.
    """
    if OLD not in leases:
        raise ValueError('ambiguous old or target lease')
    declared = {int(f) for f in (packed or ())}
    family = None if target is None else target.get('family')
    if OLD in declared:
        if family not in (None, OLD):
            raise ValueError('packed declaration makes 1350 its own target; refusing a different family')
        return {'mode': IDENTITY, 'family': OLD}
    if family is None or family == OLD:
        raise ValueError('explicit different target family required')
    return {'mode': REHOME, 'family': family}


def _paths(source, output):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('source and output must be different copies')
    backup = Path(str(output) + '.bak')
    if output.exists() or backup.exists():
        raise FileExistsError('output or backup already exists')
    return source, output, backup


def _publish(original, data, output, backup):
    """Exclusive hard-link publication; a failed publish removes our own output only."""
    with open(backup, 'xb') as f:
        f.write(original)
        f.flush()
        os.fsync(f.fileno())
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.d5-migrate-', delete=False) as f:
            tmp = f.name
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, output)
    finally:
        if tmp is not None:
            os.unlink(tmp)


def _roundtrip(save, data):
    check = savegame.Save.__new__(savegame.Save)
    savegame._parse_into(check, data)
    if check.state != save.state:
        raise ValueError('save serialization did not round-trip')


def _spare(save, unit):
    off = unit.base + MASTERY
    return off, bytes(save.state[off:off + packedmastery.SPARE_SIZE])


def migrate_copy(source, output, *, leases, thresholds, packed=(), target=None,
                 claims=(), rows=None, old_rows=None, holder=None):
    """Write a converted copy and an exclusive byte-for-byte .bak of source.

    ``packed`` is the set of family bases the build declares packed; it decides the
    mapping (``plan``).  In identity mode nothing but the spare area of the units that
    actually hold legacy counters is written.  The re-home mode keeps its older,
    explicit contract: target class descriptor, six target and six source char.dat row
    indices, and the complete projected ownership set.  Source is untouched; all
    validation and serialization precede output.
    """
    source, output, backup = _paths(source, output)
    mapping = plan(leases=leases, packed=packed, target=target)
    mode, family = mapping['mode'], mapping['family']
    old_flags, new_flags = (), ()

    if mode == REHOME:
        if family not in thresholds or OLD not in thresholds or \
                tuple(thresholds[family]) != tuple(thresholds[OLD]):
            raise ValueError('source and target thresholds must match')
        newclasses.validate_specs([target])
        physical = newclasses.sprite_family(family, target)
        if physical == OLD or family in leases:
            raise ValueError('ambiguous old or target lease')
        if not rows or len(rows) != 6 or any(type(r) is not int or not 0 <= r <= 32767 for r in rows) or len(set(rows)) != 6:
            raise ValueError('six distinct target char.dat row indices required')
        if not old_rows or len(old_rows) != 6 or \
                any(type(r) is not int or not 0 <= r <= 32767 for r in old_rows) or len(set(old_rows)) != 6:
            raise ValueError('six distinct source char.dat row indices required')
        cs = [ownership.Claim.from_dict(c) if isinstance(c, dict) else c for c in claims]
        if ownership.errors(ownership.check_claims(ownership.load(), cs)):
            raise ValueError('ownership claims conflict')
        target_flag = newclasses.flag_of(family, [target])
        for namespace, start in (('job_class_id', family), ('char_dat_row', physical),
                                 ('unlock_flag', target_flag)):
            if not any(c.holder == holder and c.namespace == namespace and c.start == start
                       and c.end == start + 5 for c in cs):
                raise ValueError('target job, physical row and unlock flag leases required')
        if not holder or not holder.startswith('kit:'):
            raise ValueError('target holder must be a Kit lease')
    else:
        # Identity introduces no new id, so there is nothing to claim and no identity
        # field to rewrite: 1350's classes, rows and unlock bits already belong to it.
        if OLD not in thresholds:
            raise ValueError('thresholds for the packed family required')
        missing = sorted({int(f) for f in leases} - {int(f) for f in thresholds})
        if missing:
            raise ValueError(f'thresholds for every leased family required (missing {missing})')
        if target is not None and target.get('family') not in (None, OLD):
            raise ValueError('packed declaration makes 1350 its own target; refusing a different family')

    original = source.read_bytes()
    save = savegame.Save(str(source))
    if source.read_bytes() != original:
        raise ValueError('source changed while reading')
    if not (0 <= save.army_count <= savegame.SLOTS and
            0 <= save.reserve_count <= savegame.SLOTS - save.army_count):
        raise ValueError('ambiguous roster counts')

    if mode == REHOME:
        old_flags = [newclasses.flag_of(OLD + i) for i in range(6)]
        new_flags = [newclasses.flag_of(family + i, [target]) for i in range(6)]
        if any(save.flag(i) for i in new_flags):
            raise ValueError('target flags already set; ownership ambiguous')

    converted = []
    # Include stale records: nonzero spare data outside the roster cannot be safely
    # assigned, and silently leaving it would reinterpret legacy bytes.
    active = {u.slot for u in save.units()}
    for slot in range(savegame.SLOTS):
        u = savegame.Unit(save, slot)
        off, raw = _spare(save, u)
        if slot not in active:
            if any(raw) or (mode == REHOME and (
                    OLD <= u.cls <= OLD + 5 or
                    OLD <= savegame._u16(save.state, u.base + SUBCLASS) <= OLD + 5)):
                raise ValueError('stale unit data is ambiguous')
            continue
        subclass = savegame._u16(save.state, u.base + SUBCLASS)
        if mode == REHOME:
            if OLD + 6 <= u.cls <= OLD + 9 or OLD + 6 <= subclass <= OLD + 9:
                raise ValueError('invalid source rank is ambiguous')
            if family <= u.cls <= family + 9 or family <= subclass <= family + 9:
                raise ValueError('target already present in roster')
        if raw.startswith(packedmastery.MAGIC):
            raise ValueError('data resembles packed format; legacy ownership ambiguous')
        if not any(raw):
            if mode == IDENTITY:
                continue          # the hook's own pm_blank initialises an all-zero area
            area = packedmastery.encode_pool({}, thresholds)
        else:
            area = packedmastery.migrate_legacy(raw, leases, thresholds)
            progress, staged, stage = packedmastery.decode_pool(area, thresholds)
            if mode == REHOME and OLD in progress:
                progress[family] = progress.pop(OLD)
                area = packedmastery.encode_pool(progress, thresholds, staged, stage)
        save.state[off:off + packedmastery.SPARE_SIZE] = area
        if area != raw:
            converted.append(dict(slot=slot, name=u.name, cls=u.cls,
                                  legacy_counters=_legacy_counters(raw)))
        if mode == REHOME:
            if OLD <= u.cls <= OLD + 5:
                rank = u.cls - OLD
                if savegame._s16(save.state, u.base + savegame.U_ROW) != old_rows[rank]:
                    raise ValueError('source class and char.dat row disagree')
                u.set_class(family + rank)
                struct.pack_into('<h', save.state, u.base + savegame.U_ROW, rows[rank])
            subclass = savegame._u16(save.state, u.base + SUBCLASS)
            if OLD <= subclass <= OLD + 5:
                struct.pack_into('<H', save.state, u.base + SUBCLASS, family + subclass - OLD)

    if mode == REHOME:
        for old, new in zip(old_flags, new_flags):
            if save.flag(old):
                save.state[savegame.STORY_FLAGS + (new >> 3)] |= 1 << (new & 7)

    data = save.to_bytes()
    _roundtrip(save, data)
    _publish(original, data, output, backup)
    return {'output': str(output), 'backup': str(backup), 'mode': mode, 'family': family,
            'units_converted': converted}


def _legacy_counters(raw):
    return {str(47 + i): list(struct.unpack_from('<6I', raw, i * 24)) for i in range(6)}


def clear_legacy(source, output, *, slots=None):
    """Zero legacy mastery bytes so the packed hook can initialise the area itself.

    The packed hook takes over only an **all-zero** spare area (``pm_blank``) and fails
    closed on anything else, so a unit still carrying six-slot counters can never earn
    class mastery again until its 144 bytes are zero.  This operation does exactly that
    and nothing else: no class, row, sub-class, level, flag or inventory byte changes, and
    already-packed areas are left alone.  ``slots`` limits the work to named unit slots
    (default: every active unit that holds legacy data).
    """
    source, output, backup = _paths(source, output)
    save = savegame.Save(str(source))
    original = source.read_bytes()
    if source.read_bytes() != original:
        raise ValueError('source changed while reading')
    if not (0 <= save.army_count <= savegame.SLOTS and
            0 <= save.reserve_count <= savegame.SLOTS - save.army_count):
        raise ValueError('ambiguous roster counts')
    active = {u.slot for u in save.units()}
    wanted = None if slots is None else {int(s) for s in slots}
    cleared = []
    for slot in range(savegame.SLOTS):
        u = savegame.Unit(save, slot)
        off, raw = _spare(save, u)
        if slot not in active:
            if any(raw):
                raise ValueError('stale unit data is ambiguous')
            continue
        if wanted is not None and slot not in wanted:
            continue
        if not any(raw) or raw.startswith(packedmastery.MAGIC):
            continue
        save.state[off:off + packedmastery.SPARE_SIZE] = b'\0' * packedmastery.SPARE_SIZE
        cleared.append(dict(slot=slot, name=u.name, cls=u.cls, level=u.level,
                            nonzero_bytes=sum(1 for b in raw if b),
                            counters=_legacy_counters(raw)))
    data = save.to_bytes()
    _roundtrip(save, data)
    _publish(original, data, output, backup)
    return {'output': str(output), 'backup': str(backup), 'mode': 'clear',
            'units_cleared': cleared}
