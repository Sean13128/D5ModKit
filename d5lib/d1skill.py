"""Bounded, read-only Disgaea 1 skill-table reader (Disgaea PC + D1 Complete HD).

The skill/spell table is ``magic.dat``: 285 rows. Two owned editions are read here and they agree
row for row, which is what makes the field meanings below safe to state:

* Disgaea PC: ``SUBDATA.DAT`` -> ``START.DAT`` member 41 (PSPFS outer archive, IMY chunks),
  rows of 172 bytes.
* D1 Complete HD: the retained same-edition ``start-40.bin`` table, rows of 180 bytes.

Record layout (both editions, identical numeric block):

    +0   u16 id
    +2   u16 level        required weapon-mastery tier; 0 for spells and unique skills
    +4   u16 power        raw table units, not a percentage
    +6   u16 sp           SP cost
    name / description (Shift-JIS, NUL-terminated, fixed-size fields)
    then 18 numeric bytes, identical in both editions:
        5  effect parameters   (first byte steps by 2 per spell tier)
        1  weapon type         1 fist .. 6 axe, 0 for spells/unique
        1  element             0 none, 1 fire, 2 wind, 3 ice, 4 star
        1  category            2 physical, 3 attack magic, 4 heal, 5/6 support
        1  weapon type (alt)   equal to the weapon type in all 285 rows
        1  range               cursor reach of the 13 cursor-shape rows (2..7); 0 = shape placed from the caster
        1  pattern             area shape: the game uses entry pattern-1 of 82 cell lists its code builds at
                               start-up; 0 = spell (area from the spell level)
        1  up, 1 down          height limits, same units as D5's height_up / height_down
        5  effect codes

D1SCRIPT1 (2026-11-10) corrected the earlier reading that range/area are not stored: the pattern byte is
the area and the shapes are in ``importers/d1-attack-patterns.json`` (tools/d1_attack_patterns.py runs the
builder, PC FUN_004430d0 = D1C Switch FUN_7100012ea4).

The field names match the publicly documented Disgaea PC ``magic.dat`` structure
(ProgSys/pg_disatools, PG_DisaDataMagic: id, level, pow, sp, name[33], description[113],
effectPrams[5], wt, e, st, wt2, rg, pat, up, dn, effect[5]). That structure is for the 172-byte PC
row; the 180-byte HD row is the same record with wider text fields. The published *meanings* are
used as names only; every value below is read from the owned tables, and the two editions are
cross-checked against each other.

No game launch, installer, save or kit state is touched.
"""
from __future__ import annotations

import hashlib
import struct
import unicodedata
from pathlib import Path

FORMAT = 'disgaea1-skill-table/1'
MAX_TABLE = 8 * 1024 * 1024
MAX_MEMBER = 64 * 1024 * 1024
CHUNK = 131072

# edition -> fixed row layout. ``numbers`` is where the 18 identical numeric bytes start.
LAYOUTS = {
    'd1': dict(stride=172, name=(8, 41), description=(41, 154), numbers=154),
    'd1hd': dict(stride=180, name=(8, 42), description=(42, 162), numbers=162),
}
# Character table: learn slots live here, not in the skill table.
CHAR_LAYOUTS = {
    'd1': dict(header=8, stride=216, identity=86, skills=0x88, levels=0xB0, slots=20),
    'd1hd': dict(header=8, stride=224, identity=94, skills=0x90, levels=0xB8, slots=20),
}
WEAPON_TYPES = {0: 'none', 1: 'fist', 2: 'sword', 3: 'spear', 4: 'bow', 5: 'gun', 6: 'axe', 7: 'staff'}
ELEMENTS = {0: 'none', 1: 'fire', 2: 'wind', 3: 'ice', 4: 'star'}
CATEGORIES = {2: 'physical', 3: 'magic', 4: 'heal', 5: 'support', 6: 'support-other'}
NUMBER_FIELDS = (
    ('effect_params', 5), ('weapon_type', 1), ('element', 1), ('category', 1),
    ('weapon_type_alt', 1), ('range', 1), ('pattern', 1), ('up', 1), ('down', 1), ('effect', 5),
)
PINNED = {
    'd1hd': dict(bytes=51312,
                 sha256='4dfb1f6d91a86dcafada159d0795d04cb09f53eb3259c7da637d76581a479d5f',
                 origin='SUBDATA.DAT start.dat[40] of the owned Disgaea 1 Complete Switch image'),
    'd1': dict(bytes=49040,
               sha256='51655b5704f12010d4e2d7b49fee1bce62953654498cbbeeeeed1a68acb1bed5',
               origin='Disgaea PC SUBDATA.DAT -> START.DAT member 41'),
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _text(raw):
    return unicodedata.normalize('NFKC', raw.split(b'\0', 1)[0].decode('shift_jis', 'replace')).strip()


def _label(table, value, what):
    if value not in table:
        raise ValueError(f'unknown {what} value {value}')
    return table[value]


def shape(raw, edition):
    """Checked header/count/size for a skill table; returns (count, stride)."""
    if edition not in LAYOUTS:
        raise ValueError('No validated Disgaea 1 skill-table layout for ' + str(edition))
    layout = LAYOUTS[edition]
    if len(raw) < 8:
        raise ValueError('Truncated Disgaea 1 skill table')
    count = struct.unpack_from('<I', raw)[0]
    if struct.unpack_from('<I', raw, 4)[0] != count:
        raise ValueError('Duplicate row count mismatch in Disgaea 1 skill table')
    end = 8 + count * layout['stride']
    if not 0 < count <= 2000 or end > len(raw) or len(raw) - end > 15 or any(raw[end:]):
        raise ValueError('Disgaea 1 skill-table count/size mismatch')
    return count, layout['stride']


def read_table(raw, edition='d1hd', *, verify=True):
    """Parse a complete ``magic.dat``; every row carries its raw hex and hash.

    ``verify`` additionally checks the pinned size/SHA256 of the two owned editions. Pass
    ``verify=False`` only for synthetic fixtures in tests.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError('skill table must be bytes')
    raw = bytes(raw)
    count, stride = shape(raw, edition)
    if verify:
        pin = PINNED[edition]
        if len(raw) != pin['bytes'] or _sha(raw) != pin['sha256']:
            raise ValueError(f'Disgaea 1 skill table ({edition}) failed its pinned size/SHA256')
    layout = LAYOUTS[edition]
    rows = []
    for index in range(count):
        offset = 8 + index * stride
        row = raw[offset:offset + stride]
        ident, level, power, sp = struct.unpack_from('<4H', row)
        numbers = row[layout['numbers']:layout['numbers'] + 18]
        values, at = {}, 0
        for name, width in NUMBER_FIELDS:
            values[name] = list(numbers[at:at + width]) if width > 1 else numbers[at]
            at += width
        if at != 18:
            raise AssertionError('number field layout drifted')
        rows.append(dict(
            id=ident, level=level, power=power, sp=sp,
            name=_text(row[layout['name'][0]:layout['name'][1]]),
            description=_text(row[layout['description'][0]:layout['description'][1]]),
            element=_label(ELEMENTS, values['element'], 'element'),
            weapon=_label(WEAPON_TYPES, values['weapon_type'], 'weapon type'),
            category=_label(CATEGORIES, values['category'], 'skill category'),
            range=values['range'], pattern=values['pattern'],
            up=values['up'], down=values['down'],
            effect_params=values['effect_params'], effect=values['effect'],
            weapon_alt=values['weapon_type_alt'],
            row_index=index, row_offset=offset, row_sha256=_sha(row)))
    ids = [r['id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate skill id in Disgaea 1 skill table')
    return dict(format=FORMAT, edition=edition, bytes=len(raw), sha256=_sha(raw),
                count=count, stride=stride, numbers_offset=layout['numbers'],
                element_names=ELEMENTS, weapon_names=WEAPON_TYPES,
                category_names=CATEGORIES, rows=rows)


def table(path, edition='d1hd'):
    """Read a skill table file, bounded, and parse it."""
    path = Path(path)
    if path.stat().st_size > MAX_TABLE:
        raise ValueError('Disgaea 1 skill table larger than its bound')
    return read_table(path.read_bytes(), edition)


def by_id(doc):
    return {row['id']: row for row in doc['rows']}


def disgaea_pc_magic(subdata, index=41):
    """Extract ``START.DAT`` member 41 (the skill table; VOICE2: or another member, e.g. 66 = the sound-effect
    bank) from a Disgaea PC ``SUBDATA.DAT``, bounded and read-only.

    Returns ``(bytes, provenance)``. The outer archive is a PSPFS_V1 table; START.DAT is a chunked
    IMY package whose first chunk holds the member offset table.
    """
    path = Path(subdata)
    with path.open('rb') as stream:
        head = stream.read(16)
        if head[:8] != b'PSPFS_V1':
            raise ValueError('Not a Disgaea PC SUBDATA archive')
        count = struct.unpack_from('<I', head, 8)[0]
        if not 0 < count <= 100000:
            raise ValueError('Disgaea PC archive table is larger than expected')
        table_bytes = stream.read(count * 52)
    entry = None
    for i in range(count):
        row = table_bytes[i * 52:(i + 1) * 52]
        if row.split(b'\0', 1)[0] == b'START.DAT':
            size, offset = struct.unpack_from('<II', row, 44)
            entry = (offset, size)
            break
    if entry is None:
        raise ValueError('Disgaea PC SUBDATA carries no START.DAT')
    base, size = entry
    if not 0 < size <= MAX_MEMBER * 16:
        raise ValueError('Disgaea PC START.DAT is larger than expected')

    def read_at(offset, length):
        if length < 0 or length > MAX_MEMBER:
            raise ValueError('Disgaea PC member read outside its bound')
        with path.open('rb') as stream:
            stream.seek(offset)
            data = stream.read(length)
        if len(data) != length:
            raise ValueError('Disgaea PC member runs past the end of its archive')
        return data

    def imy(chunk):
        if len(chunk) < 34 or chunk[:4] != b'IMY\0' or chunk[10] >> 4 != 1:
            raise ValueError('Unsupported Disgaea PC IMY chunk')
        stride = struct.unpack_from('<H', chunk, 8)[0]
        expected = stride * struct.unpack_from('<H', chunk, 12)[0]
        flags = struct.unpack_from('<H', chunk, 32)[0]
        end = cursor = 34 + flags
        if not 0 < expected <= MAX_MEMBER or end > len(chunk):
            raise ValueError('Invalid Disgaea PC IMY size')
        out = bytearray()
        for flag in chunk[34:end]:
            if flag >= 0xC0:
                distance = (2, stride, stride + 2, stride - 2)[(flag >> 4) & 3]
                length = ((flag & 15) + 1) * 2
                if not 0 < distance <= len(out):
                    raise ValueError('IMY back reference runs outside its output')
                pattern = out[-distance:]
                out += (pattern * (length // distance + 1))[:length]
            elif flag >= 16:
                start = cursor - ((flag - 16) * 2 + 2)
                if start < end or start + 2 > len(chunk):
                    raise ValueError('IMY literal reference runs outside its data')
                out += chunk[start:start + 2]
            else:
                length = (flag + 1) * 2
                if cursor + length > len(chunk):
                    raise ValueError('Truncated IMY literal')
                out += chunk[cursor:cursor + length]
                cursor += length
            if len(out) > expected:
                raise ValueError('IMY output exceeds its declared size')
            if len(out) == expected:
                return bytes(out)
        raise ValueError('Truncated IMY output')

    chunks_head = read_at(base, 8)
    chunks, chunk_size = struct.unpack('<II', chunks_head)
    if not 0 < chunks <= 10000 or chunk_size != CHUNK:
        raise ValueError('Unsupported Disgaea PC START package')
    offsets_chunks = list(struct.unpack(f'<{chunks}I', read_at(base + 8, chunks * 4)))
    first = imy(read_at(base + offsets_chunks[0], offsets_chunks[1] - offsets_chunks[0]))
    members = struct.unpack_from('<I', first)[0]
    if not 72 <= members <= 10000:
        raise ValueError('Unexpected Disgaea PC START file table')
    offsets = list(struct.unpack_from(f'<{members}I', first, 4))
    if not 0 <= index < len(offsets) - 1:
        raise ValueError('Unsupported START member index')
    start, end = offsets[index:index + 2]
    if not 0 <= start <= end or end - start > MAX_MEMBER:
        raise ValueError('Invalid START member size')
    out = bytearray()
    for i in range(start // CHUNK, (end + CHUNK - 1) // CHUNK):
        if i >= len(offsets_chunks):
            raise ValueError('START member runs outside its package')
        stop = offsets_chunks[i + 1] if i + 1 < len(offsets_chunks) else size
        raw = imy(read_at(base + offsets_chunks[i], stop - offsets_chunks[i]))
        out += raw[max(0, start - i * CHUNK):min(len(raw), end - i * CHUNK)]
    if len(out) != end - start:
        raise ValueError('Truncated START member')
    data = bytes(out)
    return data, dict(archive=str(path), member=index, bytes=len(data), sha256=_sha(data),
                      origin=f'Disgaea PC SUBDATA.DAT -> START.DAT member {index}')


def character_shape(raw, edition):
    layout = CHAR_LAYOUTS[edition]
    if len(raw) < layout['header']:
        raise ValueError('Truncated Disgaea 1 character table')
    count = struct.unpack_from('<I', raw)[0]
    end = layout['header'] + count * layout['stride']
    if not 0 < count <= 20000 or end > len(raw) or len(raw) - end > 15 or any(raw[end:]):
        raise ValueError('Disgaea 1 character-table count/size mismatch')
    return count


def learnset(raw_char, character_id, edition='d1hd'):
    """The learned-skill list of one character row: ``[{skill, level, slot}]``.

    Learn slots live in ``char.dat``/``char_e.dat`` (20 id/level pairs per row), not in the skill
    table. A learned id absent from the skill table stays listed with ``name=None``.
    """
    count = character_shape(raw_char, edition)
    layout = CHAR_LAYOUTS[edition]
    found = []
    for index in range(count):
        offset = layout['header'] + index * layout['stride']
        row = raw_char[offset:offset + layout['stride']]
        if struct.unpack_from('<H', row, layout['identity'])[0] != character_id:
            continue
        ids = struct.unpack_from(f"<{layout['slots']}H", row, layout['skills'])
        levels = struct.unpack_from(f"<{layout['slots']}H", row, layout['levels'])
        found.append(dict(id=character_id, row_index=index, row_offset=offset,
                          row_sha256=_sha(row),
                          learn=[dict(skill=s, level=l, slot=i)
                                 for i, (s, l) in enumerate(zip(ids, levels)) if s]))
    if not found:
        raise ValueError(f'character {character_id} is absent from the Disgaea 1 character table')
    if len(found) > 1:
        raise ValueError(f'character {character_id} is ambiguous in the character table')
    return found[0]
