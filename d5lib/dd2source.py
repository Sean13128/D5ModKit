"""Disgaea D2 (PS3, BLUS31313) source tables: bounded, read-only readers.

Everything here was read from the user's own install and cross-checked row by row; nothing copies game data into the
repository.  Evidence, native-code citations and open questions live in
Research/source-packs/dd2/slice/packet/tables-evidence.json.

Members (relative to ``.../PS3_GAME/USRDIR/Data``)::

  START_4.dat   NISPACK archive holding char.dat (558 x 676), magic.dat (386 x 296), mskill.dat (227 x 232) and
                charhelp.dat (256 x 278).  The same member names exist in the older START.dat / START_1 / START_2
                packs with *different* magic.dat, mskill.dat and charhelp.dat content, so a caller must read one
                patch level and never mix members from two of them.

Geometry is identical for all four tables: a big-endian 16-bit record count, two unused bytes, then rows.  Every
reader checks that the count and the byte length agree with the stride it was told; a mismatch raises instead of
guessing.  All text is NUL-terminated UTF-8 (verified over every row of every table) and is read with ``strict``
decoding, so a layout error surfaces as an error rather than as replacement characters.

Evilities are *not* stored per row.  mskill.dat holds exactly three ids per class family base (1010..1210 and
2010..2200, step 10) and one or two per unique character id (10, 30/31, 70/71, 80/81, ...); the id numbering is the
only mapping the files support.  :func:`evility_ids` implements it and is marked inferred, including its known
blind spot for alternate unique rows.

Voice is **unproven**: the SndPakVoice banks carry anonymous index tables with no names or group numbers, no native
reader in the local D2-RE port touches them, and no char.dat field we could isolate indexes them.  Nothing here
guesses a voice group.
"""
from __future__ import annotations

import struct

PACK_MAGIC = b"NISPACK\0"
PACK_HEADER = 16
PACK_ENTRY = 44
PACK_NAME = 32

CHAR_COUNT, CHAR_STRIDE = 558, 676          # 0x2A4
SKILL_COUNT, SKILL_STRIDE = 386, 296        # 0x128
EVILITY_COUNT, EVILITY_STRIDE = 227, 232    # 0xE8
HELP_COUNT, HELP_STRIDE = 256, 278

STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")

# char.dat row layout: field -> (offset, struct format, confidence).  "high" = the value is self-evident and holds
# for every row (ids, text, the learn tables); "medium" = consistent across all 558 rows but read from the shape of
# the data rather than from native code.  See tables-evidence.json for the per-field evidence.
CHAR_LAYOUT = {
    "base":           (0x004, "8H",  "medium"),  # level-1 stats (Warrior 29/6/16/16/6/8/12/8)
    "learn_skill":    (0x014, "16H", "high"),    # magic.dat ids (Shark Dragon 12181..12184, 32181)
    "learn_level":    (0x034, "16H", "high"),    # levels for the same slots (8, 28, 56, 112, 1)
    "weapon_skill":   (0x094, "16H", "medium"),  # magic.dat ids (Warrior 201,202,203 = sword 1..3)
    "id":             (0x194, "H",   "high"),    # native: vm_read16(row+0x194) is the class id
    "body":           (0x196, "H",   "high"),    # native: the row's renderer resource; equals +0x1BC on 434 rows
    "help_id":        (0x19C, "H",   "high"),    # charhelp.dat id: 539/558 rows resolve, remainder are dummies
    "body_variants":  (0x1BC, "3H",  "medium"),  # native reads +0x1BC/+0x1BE as primary/alternate resources
    "name":           (0x1FC, "52s", "high"),
    "title":          (0x230, "52s", "high"),
    "aptitudes":      (0x274, "8B",  "high"),
    "palette":        (0x28B, "B",   "medium"),  # 0..5 across the table
}

SKILL_DESCRIPTION = (0x0A, 0x9E)    # magic.dat: description text
SKILL_NAME = (0x9E, 0xCE)           # magic.dat: name text
SKILL_NAME_ALT = (0xCE, 0xFE)       # magic.dat: second name text (identical on all 386 rows today)
EVILITY_ID, EVILITY_VALUE, EVILITY_VALUE2 = 0x08, 0x0C, 0x0E   # VALUE2: u8, the description's second %d (maximum, e.g. 200)
EVILITY_NAME = (0x0F, 0x5F)         # mskill.dat: name text
EVILITY_DESCRIPTION = (0x5F, 0xE8)  # mskill.dat: description text; EVILITY_VALUE is the %d it quotes


def _text(raw, field, where):
    """A NUL-terminated UTF-8 region; anything else is a layout error, not a text to repair."""
    body, terminator, _ = bytes(raw).partition(b"\0")
    if not terminator:
        raise ValueError(f"{where}: {field} is not NUL terminated")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{where}: {field} is not UTF-8: {error}") from None


def _rows(data, where, stride, count):
    """Split a table into rows, refusing any count/stride/size disagreement."""
    data = bytes(data)
    if len(data) < 4:
        raise ValueError(f"{where}: truncated table header")
    found = struct.unpack_from(">H", data, 0)[0]
    if found != count or len(data) != 4 + found * stride:
        raise ValueError(f"{where}: expected a BE16 count of {count} and {4 + count * stride} bytes, "
                         f"found a count of {found} and {len(data)} bytes")
    return [data[4 + i * stride: 4 + (i + 1) * stride] for i in range(count)]


class Nispack:
    """NISPACK archive: {member name: (offset, size)} plus read(name) -> bytes.

    Verified header (all four START*.dat packs): 8-byte magic ``NISPACK\\0``, a constant word 0x01000000 at +8 and a
    big-endian member count at +12, then one 44-byte entry per member: a 32-byte NUL-padded ASCII name, big-endian
    offset, big-endian size and one more big-endian word that reads like a Unix timestamp (1123643874 = 2005-08-10).
    Members start at or after the end of the table; the first one starts at 2048 in the shipped packs.  The
    timestamp word is exposed but not interpreted; the 0x01000000 word is exposed unvalidated because one sample
    cannot prove it is a version.
    """

    def __init__(self, data):
        data = bytes(data)
        if len(data) < PACK_HEADER or data[:8] != PACK_MAGIC:
            raise ValueError("not a NISPACK archive")
        self.data = data
        self.marker = struct.unpack_from(">I", data, 8)[0]
        count = struct.unpack_from(">I", data, 12)[0]
        table_end = PACK_HEADER + count * PACK_ENTRY
        if not 0 < count <= 100000 or table_end > len(data):
            raise ValueError(f"NISPACK member table of {count} entries does not fit in {len(data)} bytes")
        self.members, self.stamps, self.order = {}, {}, []
        for index in range(count):
            entry = data[PACK_HEADER + index * PACK_ENTRY: PACK_HEADER + (index + 1) * PACK_ENTRY]
            name = entry[:PACK_NAME].partition(b"\0")[0].decode("ascii", "strict")
            offset, size, stamp = struct.unpack_from(">III", entry, PACK_NAME)
            if not name or name in self.members:
                raise ValueError(f"NISPACK member {index} is unnamed or duplicates {name!r}")
            if offset < table_end or offset + size > len(data):
                raise ValueError(f"NISPACK member {name} lies outside the archive")
            self.members[name] = (offset, size)
            self.stamps[name] = stamp
            self.order.append(name)

    def __contains__(self, name):
        return name in self.members

    def __len__(self):
        return len(self.members)

    def read(self, name):
        offset, size = self.members[name]
        return self.data[offset: offset + size]


def decode_skill(row, where="magic.dat"):
    """One magic.dat row -> dict(id, name, description, name_alt).

    The name lives in two 48-byte regions; they are identical on all 386 shipped rows, so the second is only
    appended (space separated) when it differs, as the D2 tables do for a few renamed skills in other packs.
    """
    if len(row) != SKILL_STRIDE:
        raise ValueError(f"{where}: skill row of {len(row)} bytes is not {SKILL_STRIDE}")
    name = _text(row[SKILL_NAME[0]:SKILL_NAME[1]], "name", where)
    alt = _text(row[SKILL_NAME_ALT[0]:SKILL_NAME_ALT[1]], "second name", where)
    return dict(id=struct.unpack_from(">H", row, 0)[0],
                name=name if not alt or alt == name else f"{name} {alt}",
                name_alt=alt,
                description=_text(row[SKILL_DESCRIPTION[0]:SKILL_DESCRIPTION[1]], "description", where))


def decode_evility(row, where="mskill.dat"):
    """One mskill.dat row -> dict(id, value, value2, name, description).

    value is the number the first %d shows; value2 (byte +0x0E, 0 when unused) the second, usually the stated maximum
    (Plume 10/200, Adell 5/100).  EVILNEW1 census: all 29 two-placeholder descriptions have a nonzero value2."""
    if len(row) != EVILITY_STRIDE:
        raise ValueError(f"{where}: evility row of {len(row)} bytes is not {EVILITY_STRIDE}")
    return dict(id=struct.unpack_from(">H", row, EVILITY_ID)[0],
                value=struct.unpack_from(">H", row, EVILITY_VALUE)[0],
                value2=row[EVILITY_VALUE2],
                name=_text(row[EVILITY_NAME[0]:EVILITY_NAME[1]], "name", where),
                description=_text(row[EVILITY_DESCRIPTION[0]:EVILITY_DESCRIPTION[1]], "description", where))


def decode_help(row, where="charhelp.dat"):
    """One charhelp.dat row -> dict(id, text); text is a single line (longest shipped line is 46 bytes)."""
    if len(row) != HELP_STRIDE:
        raise ValueError(f"{where}: help row of {len(row)} bytes is not {HELP_STRIDE}")
    return dict(id=struct.unpack_from(">H", row, 0)[0], text=_text(row[2:], "text", where))


def decode_char(row, where="char.dat"):
    """One char.dat row -> dict of CHAR_LAYOUT fields plus learnset [(skill id, level)]."""
    if len(row) != CHAR_STRIDE:
        raise ValueError(f"{where}: character row of {len(row)} bytes is not {CHAR_STRIDE}")
    out = {}
    for name, (offset, fmt, _) in CHAR_LAYOUT.items():
        value = struct.unpack_from(">" + fmt, row, offset)
        if fmt.endswith("s"):
            value = _text(value[0], name, where)
        elif len(value) == 1:
            value = value[0]
        out[name] = list(value) if isinstance(value, tuple) else value
    out["learnset"] = [(skill, level) for skill, level in zip(out.pop("learn_skill"), out.pop("learn_level")) if skill]
    out["weapon_skills"] = [skill for skill in out["weapon_skill"] if skill]
    return out


# ------------------------------------------------------------------ battle fields (DD2FIELDS1)
# The 676-byte row also holds the battle block the unit builder (EBOOT 1.40 function 0x10E77C) copies to the
# unit.  Evidence per field is in Research/import-checklist/source-values/dd2-FIELD-MAP.md (DD2FIELDS1 section):
# code = read from the PS3 ELF; community = GameFAQs "Disgaea D2 Character Guide" by Guilu (gamefaqs.gamespot.com/
# ps3/687861-disgaea-d2-a-brighter-darkness/faqs/68086), 67 characters compared; D5 = the same-named Disgaea 5 row.
# Value = D5 char.dat field -> (source offset, struct format, class, evidence).  class "source-exact" is the stored
# number written unchanged (same unit and scale in D5); "rule-converted" is a stated mapping.
BATTLE_LAYOUT = {
    "MOV":            (0x1A2, ">H", "source-exact", "code 0x10E77C/0x107874 + community 66/67 + D5 Laharl/Etna/Flonne equal"),
    "JMP":            (0x28D, ">B", "source-exact", "code 0x1078A4 + community 67/67 + D5 equal"),
    "throw":          (0x290, ">B", "source-exact", "code clamp 0x107814 + community 42/42 + D5 equal"),
    "counter":        (0x291, ">B", "source-exact", "code clamp 0x107844 + community 67/67 + D5 equal"),
    "crit":           (0x292, ">B", "source-exact", "code clamp 0x1077E4 + community 67/67 (byte = displayed percent) + D5 equal scale"),
    "attack_range":   (0x1A6, ">H", "source-exact", "code to unit+0x1180 + community 25/25 monsters + D5 equal"),
    "res_fire":       (0x285, ">b", "source-exact", "code: unit+0x1168 -> 0x116B read by element id 1 (Fire spell 1001) at 0xF5524 + community 65/66"),
    "res_wind":       (0x286, ">b", "source-exact", "code: unit+0x1169 -> 0x116C read by element id 2 (Wind spell 1101) + community 65/66"),
    "res_ice":        (0x287, ">b", "source-exact", "code: unit+0x116A -> 0x116D read by element id 3 (Ice spell 1201) + community 65/66"),
    "mastery_fist":   (0x27C, ">B", "source-exact", "code unit+0x1146.. + community letter bins + D5 Laharl/Etna equal"),
    "mastery_sword":  (0x27D, ">B", "source-exact", "as mastery_fist"),
    "mastery_spear":  (0x27E, ">B", "source-exact", "as mastery_fist"),
    "mastery_bow":    (0x27F, ">B", "source-exact", "as mastery_fist"),
    "mastery_gun":    (0x280, ">B", "source-exact", "as mastery_fist"),
    "mastery_axe":    (0x281, ">B", "source-exact", "as mastery_fist"),
    "mastery_staff":  (0x282, ">B", "source-exact", "as mastery_fist"),
    "kind_gender":    (0x289, ">B", "source-exact", "code switch 0x10E958 + D5 decomp: only reader is unit_class_name_bank (0..2 keep the row's own name) + D5 equal for 22/23 classes, 26/26 uniques"),
}
FLYING_OFFSET = 0x1A4            # u16 0/1 -> D5 move_type 0 (walking) / 1 (flying): rule-converted
IMMUNITY_OFFSET = 0x000          # i32 mask; bit order differs from D5's (D2 Xenolith 12 bits, D5 uses 7/14): only all-or-nothing carries
D2_IMMUNITY_ALL = 0x0FFFFFFF

# Fields the source row has a candidate for but that stay on the donor, with the reason (written into mod.json).
BATTLE_DONOR = {
    "hl_value": "+0x1A8 located by pattern only; D5 class values differ by 0.4-0.7x from the D2 numbers (D5 rebalanced), no code reader",
    "exp_value": "+0x1AA located by pattern only; 10 on D2 DLC uniques where D5 has 40, no code reader",
    "mana_value": "+0x1B0 located by pattern only, no code reader",
    "is_unique": "+0x298 has no code reader; the D5 export shows no reader of char+0x384 either, risk unsettled",
    "res_star": "the D2 row has no Star resistance byte",
    "immunity_flags": "partial D2 masks use a different bit order from D5's; only none/all carries",
}


def battle_fields(row, where="char.dat"):
    """One 676-byte row -> (fields, provenance): D5 char.dat field -> value, and field -> dict(class, offset, evidence).

    Pure decode, no donor.  Fields not returned stay on the donor (see BATTLE_DONOR)."""
    if len(row) != CHAR_STRIDE:
        raise ValueError(f"{where}: character row of {len(row)} bytes is not {CHAR_STRIDE}")
    fields, prov = {}, {}
    for name, (offset, fmt, kind, evidence) in BATTLE_LAYOUT.items():
        fields[name] = struct.unpack_from(fmt, row, offset)[0]
        prov[name] = dict(kind=kind, offset=hex(offset), source_value=fields[name], evidence=evidence)
    flag = struct.unpack_from(">H", row, FLYING_OFFSET)[0]
    if flag not in (0, 1):
        raise ValueError(f"{where}: flying flag {flag} is not 0/1")
    fields["move_type"] = flag
    prov["move_type"] = dict(kind="rule-converted", offset=hex(FLYING_OFFSET), source_value=flag,
                             evidence="code to unit+0x117E + community fly flag 67/67; D5 move_type 1 = flying, 0 = walking")
    mask = struct.unpack_from(">i", row, IMMUNITY_OFFSET)[0]
    if mask == 0:
        fields["immunity_flags"] = 0
        prov["immunity_flags"] = dict(kind="source-exact", offset="0x0", source_value=0, evidence="no immunity")
    elif mask == D2_IMMUNITY_ALL:
        fields["immunity_flags"] = -1
        prov["immunity_flags"] = dict(kind="rule-converted", offset="0x0", source_value=mask,
                                      evidence="all 28 D2 bits set -> all D5 bits set (D5 Baal Slave is -1)")
    return fields, prov


def evility_ids(char_id):
    """mskill.dat ids a character row draws evilities from, by id numbering.

    Inferred from the table contents, not stored anywhere: char.dat contains no evility id list (a u16 sweep of the
    whole row is recorded in tables-evidence.json).  mskill.dat carries exactly three ids per class family base
    (1010..1210 and 2010..2200, step 10: 1010/1011/1012 are the Warrior's three) and one or two per unique
    character id (30/31 Etna, 80/81 Xenolith, 90 Artifact Gone Wild).

    Known blind spot, do not paper over it: alternate unique rows have no ids of their own - row 40 is Etna's second
    row and returns [] although the character has evilities.  An empty result therefore means "not found", never
    "has none".
    """
    base = char_id - char_id % 10 if char_id >= 1000 else char_id
    return [base + step for step in range(3)]


class Tables:
    """The D2 tables this pack needs, read once from a member source.

    ``source`` is a :class:`Nispack`, a ``{member name: bytes}`` mapping or a callable ``name -> bytes``, so tests
    and tools never depend on a hard-coded game path.
    """

    def __init__(self, source):
        self.source = source
        self._cache = {}

    # ---------------------------------------------------------------- members and tables
    def member(self, name) -> bytes:
        """Raw member bytes (one read, cached)."""
        if name not in self._cache:
            reader = self.source
            if hasattr(reader, "read"):
                data = reader.read(name)
            elif callable(reader):
                data = reader(name)
            else:
                data = reader[name]
            self._cache[name] = bytes(data)
        return self._cache[name]

    def _table(self, name, stride, count):
        return _rows(self.member(name), name, stride, count)

    @property
    def chars(self):
        """{char id: decoded row}; duplicate ids raise instead of silently winning."""
        if "chars" not in self._cache:
            out = {}
            for index, row in enumerate(self._table("char.dat", CHAR_STRIDE, CHAR_COUNT)):
                decoded = decode_char(row, f"char.dat row {index}")
                if decoded["id"] in out:
                    raise ValueError(f"char.dat: duplicate character id {decoded['id']}")
                out[decoded["id"]] = decoded
            self._cache["chars"] = out
        return self._cache["chars"]

    def battle(self, char_id):
        """(fields, provenance) of :func:`battle_fields` for one char.dat row, found by its id."""
        for index, row in enumerate(self._table("char.dat", CHAR_STRIDE, CHAR_COUNT)):
            if struct.unpack_from(">H", row, 0x194)[0] == char_id:
                return battle_fields(row, f"char.dat row {index}")
        raise KeyError(char_id)

    @property
    def skills(self):
        """{skill id: dict(name, description)} from magic.dat."""
        if "skills" not in self._cache:
            out = {}
            for index, row in enumerate(self._table("magic.dat", SKILL_STRIDE, SKILL_COUNT)):
                decoded = decode_skill(row, f"magic.dat row {index}")
                if decoded["id"] in out:
                    raise ValueError(f"magic.dat: duplicate skill id {decoded['id']}")
                out[decoded["id"]] = decoded
            self._cache["skills"] = out
        return self._cache["skills"]

    @property
    def evilities(self):
        """{evility id: dict(name, value, value2, description)} from mskill.dat."""
        if "evilities" not in self._cache:
            out = {}
            for index, row in enumerate(self._table("mskill.dat", EVILITY_STRIDE, EVILITY_COUNT)):
                decoded = decode_evility(row, f"mskill.dat row {index}")
                if decoded["id"] in out:
                    raise ValueError(f"mskill.dat: duplicate evility id {decoded['id']}")
                out[decoded["id"]] = decoded
            self._cache["evilities"] = out
        return self._cache["evilities"]

    @property
    def helps(self):
        """{help id: text} from charhelp.dat (one id is duplicated in the shipped table: 5112)."""
        if "helps" not in self._cache:
            out = {}
            for index, row in enumerate(self._table("charhelp.dat", HELP_STRIDE, HELP_COUNT)):
                decoded = decode_help(row, f"charhelp.dat row {index}")
                out.setdefault(decoded["id"], decoded["text"])
            self._cache["helps"] = out
        return self._cache["helps"]

    # ---------------------------------------------------------------- derived views
    def learn_list(self, char_id):
        """[(skill id, level)] as stored, including ids magic.dat does not contain."""
        return list(self.chars[char_id]["learnset"])

    def evilities_for(self, char_id):
        """[(evility id, decoded dict)] for the ids this row's numbering reaches; see :func:`evility_ids`.

        Ids the candidate numbering produces but mskill.dat does not contain are omitted, so a short or empty result
        means "not found" - see the blind spot in :func:`evility_ids`.
        """
        table = self.evilities
        return [(evility, table[evility]) for evility in evility_ids(char_id) if evility in table]

    def help_text(self, char_id):
        """charhelp.dat text for a character row, or None when the table has no row for its help id."""
        return self.helps.get(self.chars[char_id]["help_id"])

    def unresolved_learn_ids(self):
        """{skill id: [char ids]}: learn-list entries with no magic.dat row (14 ids, 83 references, in START_4)."""
        missing = {}
        for char_id, row in self.chars.items():
            for skill, _ in row["learnset"]:
                if skill not in self.skills:
                    missing.setdefault(skill, []).append(char_id)
        return missing

    def character(self, char_id):
        """One character row resolved against the other tables.

        A learn entry whose skill is absent from magic.dat is kept with ``name=None`` and ``resolved=False``: the
        shipped table really is missing those ids (10083 is Xenolith's third unique skill, referenced by rows 80 and
        3532), so dropping them would hide a data gap.
        """
        row = self.chars[char_id]
        skills, evilities = self.skills, self.evilities
        learn = []
        for skill, level in row["learnset"]:
            known = skills.get(skill)
            learn.append(dict(id=skill, level=level, resolved=known is not None,
                              name=known["name"] if known else None,
                              description=known["description"] if known else None))
        return dict(row, learn=learn, evilities=self.evilities_for(char_id), help=self.help_text(char_id))


# ---------------------------------------------------------------------------------------------
# built-bank normalisation: the control code lives in the LOW byte of a key's flags
# ---------------------------------------------------------------------------------------------
# D5's actor advance decodes a control node's code from the low byte of the key's flags u16 -
# measured on the TEST18B image (payload sha a06e79bd...): `0x1402f5002 movsx ecx, byte ptr
# [rdx+2]` then `sub ecx,2` (loop back), `sub ecx,1` (conditional), `sub ecx,1` (wait),
# `cmp ecx,1` (hold), and the back-scan `0x1402f5150 cmp byte ptr [rdx+2], 1` for the loop
# marker.  A key with code 0 takes no control action at all (0x1402f501c jne 0x1402f5074).
# (decomp functions/1402f4f70_anm_actor_advance.c, Sorrow's annotation "Controls 1 loop marker,
# 2 loop, 3 conditional loop, 4 wait, 5 hold".)
#
# A DD2 source bank carries that code in the HIGH byte of the same u16.  A converter that reads
# the source record straight through therefore writes a control root whose low byte is 0, and the
# engine never sees a marker: the preview never holds, restarts at frame 0 and re-selects its
# events every step.  All nine DD2 class packs built on 2026-10-30 shipped like that - they are
# the only packs of the 174 in TEST18B that fail classcheck R10 - and the Recruiter wheel lays
# the last five families out on its first frame, i.e. exactly those nine.

def normalize_control_flags(anmf) -> int:
    """Move a DD2 control code from the high byte to the low byte of an animation root's keys.

    Call on a built `d5lib.anm.AnmFile` before `to_bytes()`.  Only root-node keys whose low byte
    is 0 are touched, so the importer's own `Key(0, 5, ...)` placeholders (already correct) and
    every drawing-node key (where a 0x100/0x200 high byte is legitimate) are left alone.  The
    transform is idempotent; returns the number of keys changed.
    """
    changed = 0
    for block in anmf.blocks:
        roots = {a.root for a in block.animations if 0 <= a.root < len(block.nodes)}
        for index in roots:
            for key in block.node_keys(block.nodes[index]):
                low, high = key.flags & 0xFF, key.flags >> 8
                if low == 0 and high:
                    key.flags = high
                    changed += 1
    return changed


def drop_unresolved_attachments(anmf) -> int:
    """Clear attach flags whose target animation is not in the bank.

    DD2 monsters attach 6001/6007 on node id 99, which their banks do not hold.  These keys have
    never fired in the installed packs, so clearing them keeps that behaviour: D5 spawning an
    actor for a missing motion falls back to the bank's first motion, and spawn edges have
    frozen the Recruiter wheel before.  Returns the number of keys changed.
    """
    changed = 0
    for block in anmf.blocks:
        held = {a.id for a in block.animations}
        for key in block.keys:
            if key.flags >> 8 == 1 and not key.cell and (key.param >= len(block.params) or block.params[key.param] not in held):
                key.flags &= 0xFF
                changed += 1
    return changed


def normalize_image_byte_order(anmf) -> int:
    """Normalize DD2-converted ANM image markers to the D5 little-endian marker.

    The converted image dimensions and pixels are already in D5 order; preserving
    the console marker makes D5 swap dimensions and the reconstructed byte size.
    Reject other markers rather than silently changing unfamiliar input.
    """
    images = anmf.textures + anmf.palettes
    if any(image.unk not in (1, 0x10000) for image in images):
        raise ValueError('Unexpected DD2 ANM image byte-order marker')
    changed = 0
    for image in images:
        if image.unk == 0x10000:
            image.unk = 1
            changed += 1
    return changed
