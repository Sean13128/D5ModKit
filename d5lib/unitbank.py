"""The character bank: take one unit out of a save and put it into another, byte for byte.

A unit *is* its roster record.  The save keeps 128 records of 0x4750 bytes (`savegame.ROSTER`), and
everything a character carries is inside its own record:

    0x010 .. 0xBC8   its five equipped items, 0x258 bytes each (0x10 + 5 * 0x258 = 0xBC8 = the name,
                     the arithmetic matches `savegame.U_NAME`; the game's own record constructor
                     `data_unit_construct_empty` 0x140063d40 zeroes exactly these five blocks and writes
                     its "empty" marker into each one)
    0xBC8 ..         name, title, level, class (+0x2E04), char.dat row (+0x2E0A), roster index (+0x2E31)
    0x2DA8           the ten weapon-mastery counters (level + aptitude)
    0x2E70 ..+0x2EEC the 125-byte learned-evility bitmap (positions 0..999 of Skill.dat, `d5lib.learned`)
    0x2F30           the built active-evility list (rebuilt by the game, not stored state)
    0x3058 / 0x30A0  squad (-1 none) and group (0xFF none)
    0x3060           the u64 serial every table outside the record names the unit by
    0x30A4 + 47*24   the class-mastery counters

So a unit needs no assembly from parts: the export is the record, and the import is the record plus the
few ids that mean something *outside* it.  Nothing else in the save is duplicated into the bank, and
nothing about the source save is needed to read a unit back.

The ids that must be re-addressed on import (everything else is copied verbatim):

  serial (+0x3060)  the game's unit id.  A save's serials are 1.. (Save1's highest is 6607 with the next
                    id at 12033), so the *same* number names a different unit in every save.  The import
                    therefore takes a fresh one from the save's own counter at state+0x5A7F60 — the same
                    dword the game increments in `roster_create_unit` 0x1402ea3e0 (that global,
                    0x145574a60, is state+0x5A7F60) — and leaves the counter above it.  Keeping the old
                    serial would collide with an unrelated unit, and every squad, group, the base walker,
                    its followers and the three 128-entry serial lists are keyed by it.
  index (+0x2E31)   the record's own roster position.  The game writes it when it makes a unit and
                    renumbers every slot when it removes one; a save whose indices disagree with the
                    slot order is not a state the game ever writes.
  row (+0x2E0A)     the index of the unit's char.dat row.  Only wrong when the target save's char.dat
                    is a different table (`fix_rows` in savegame does the same computation).
  squad / group     cleared.  The membership lives outside the record (10 serials per squad, 20 per
                    group) and names the *old* serial, so a unit cannot bring its squad with it; the
                    game's own Dismiss takes a unit out of these the same way.

What is *not* handled here and must be handled by whoever calls it:

  * the learned-evility companion (`<save>.d5learn.json`, `d5lib.learned.sidecar_doc`) is bound to the
    save's sha256 and keyed by serial, so a bank import that changes a save invalidates it; the bank
    hands over the extra learning keyed by the *new* serial (`unit["learned_extra"]`) and the caller
    re-emits the companion after the write.
  * a character whose char.dat row the target save does not have.  The record is still importable (the
    row is a cache; `d5lib.native.d5rows.inc.c` re-points it at run time) but the class is only
    playable with its mod installed.
  * the game's own remaining references to the *source* save (nothing — the bank is one record).

Everything here is pure: it reads and writes `savegame.Save` state in memory.  No game, no install.
"""
import hashlib
import struct

from . import savegame

SCHEMA = 1
KIND = "d5modkit.unitbank"
RECORD = savegame.UNIT                     # 0x4750
UID_NEXT = 0x5A7F60                        # state+0x5A7F60 = the exe's serial dword (0x145574a60): the LAST serial
                                           # issued; roster_create_unit pre-increments it and gives the unit the new value
ITEMS = 0x10
ITEMS_END = 0xBC8                          # 0x10 + 5 * 0x258 = the name
NO_SQUAD = -1
NO_GROUP = 0xFF


def _u32(state, off):
    return struct.unpack_from("<I", state, off)[0]


def _record(save, slot):
    base = savegame.ROSTER + int(slot) * RECORD
    return base, bytes(save.state[base:base + RECORD])


def uid_next(save):
    """the save's serial counter: the last serial the game issued (its next unit gets this + 1, 0x1402ea3e0)"""
    return _u32(save.state, UID_NEXT)


def set_uid_next(save, value):
    struct.pack_into("<I", save.state, UID_NEXT, int(value))


def _blank(state, base):
    """a never-used record: not in use, no serial, no class (what `savegame.Save._blank` looks for)"""
    return (_u32(state, base + savegame.U_USED) == 0
            and struct.unpack_from("<Q", state, base + savegame.U_SERIAL)[0] == 0
            and _u32(state, base + savegame.U_CLASS) == 0)


def export_unit(save, slot, *, extra_learned=None, sha=None):
    """one army/reserve unit as a bank entry -> dict (JSON-safe).

    extra_learned: {serial: [evility ids]} from the save's companion (the ids past the native bitmap);
    sha: the save file's sha256, recorded as provenance only (nothing is verified against it later).
    """
    slot = int(slot)
    if not 0 <= slot < savegame.SLOTS:
        raise ValueError(f"roster slot {slot} is outside 0..{savegame.SLOTS - 1}")
    base, record = _record(save, slot)
    if _u32(save.state, base + savegame.U_USED) == 0:
        raise ValueError(f"roster slot {slot} holds no unit")
    unit = savegame.Unit(save, slot)
    serial = unit.serial
    return {
        "name": unit.name,
        "title": unit.title,
        "class": unit.cls,
        "level": unit.level,
        "serial": serial,
        "record": record.hex(),
        "learned_extra": sorted({int(i) for i in (extra_learned or {}).get(serial, [])}),
        "from_save": sha,
    }


def entry_record(entry):
    """the 0x4750 bytes of a bank entry (and its length checked)"""
    raw = bytes.fromhex(entry["record"])
    if len(raw) != RECORD:
        raise ValueError(f"unit record is {len(raw)} bytes, not {RECORD}")
    return raw


def bank_doc(entries, note=""):
    """what a bank file holds"""
    return {"kind": KIND, "schema": SCHEMA, "note": note, "units": list(entries)}


def bank_add(doc, save, slot, **kw):
    """append one unit of a save to a bank document -> the entry"""
    entry = export_unit(save, slot, **kw)
    doc.setdefault("units", []).append(entry)
    return entry


def _row_of(class_id, rows):
    """the char.dat row of a class id (the table is sorted by id, so the row is its sorted position)"""
    if rows is None:
        return None
    try:
        return sorted(int(r) for r in rows).index(int(class_id))
    except ValueError:
        return None


def import_unit(save, entry, *, rows=None, slot=None, keep_ids=False):
    """put a bank entry into a save -> {"slot", "serial", "row", "warnings": [...]}.

    slot: the roster slot to use (default: the end of the army, where the game's own
    `roster_create_unit` appends).  rows: the target's char.dat class ids, to re-address +0x2E0A.
    keep_ids: keep the entry's serial and index (only for a save the unit came out of — a re-insert).
    """
    raw = bytearray(entry_record(entry))
    warnings = []
    army, reserve = save.army_count, save.reserve_count
    if army < 0 or reserve < 0:
        raise ValueError("save holds an impossible army/reserve count")
    if slot is None:
        slot = army
    slot = int(slot)
    if not 0 <= slot < savegame.SLOTS - max(0, reserve):
        raise ValueError(f"slot {slot} is not a free army slot (army {army}, reserve {reserve})")
    if army + reserve >= savegame.SLOTS:
        raise ValueError(f"the roster is full: {army} army + {reserve} reserve = {savegame.SLOTS} slots")
    base = savegame.ROSTER + slot * RECORD
    if not _blank(save.state, base) and slot != army:
        raise ValueError(f"slot {slot} holds a unit or a stale copy; only the end of the army "
                         f"({army}) is overwritten the way the game does it")

    old_serial = struct.unpack_from("<Q", raw, savegame.U_SERIAL)[0]
    if keep_ids:
        serial = old_serial
        if any(u.serial == serial for u in save.units() if u.slot != slot):
            raise ValueError(f"serial {serial} already names another unit in this save")
    else:
        serial = uid_next(save) + 1                  # as roster_create_unit: ++counter, the unit gets it
        while serial in {u.serial for u in save.units()}:
            serial += 1
        set_uid_next(save, serial)
    struct.pack_into("<Q", raw, savegame.U_SERIAL, serial)

    cls = struct.unpack_from("<I", raw, savegame.U_CLASS)[0]
    row = _row_of(cls, rows)
    if row is not None:
        if struct.unpack_from("<h", raw, savegame.U_ROW)[0] != row:
            warnings.append(f"class row {struct.unpack_from('<h', raw, savegame.U_ROW)[0]} -> {row} "
                            f"for this save's char.dat")
        struct.pack_into("<h", raw, savegame.U_ROW, row)
    elif rows is not None:
        warnings.append(f"class {cls} is not in this save's char.dat (the unit needs its mod installed)")

    squad = struct.unpack_from("<h", raw, savegame.U_SQUAD)[0]
    group = raw[savegame.U_GROUP]
    if squad != NO_SQUAD or group != NO_GROUP:
        warnings.append("squad / group membership is dropped: it names the unit by its old serial")
    struct.pack_into("<h", raw, savegame.U_SQUAD, NO_SQUAD)
    raw[savegame.U_GROUP] = NO_GROUP
    raw[savegame.U_INDEX] = slot

    if not _blank(save.state, base):
        warnings.append(f"slot {slot} held a stale copy, overwritten (the game's create does the same)")
    save.state[base:base + RECORD] = raw

    if slot >= army:
        struct.pack_into("<h", save.state, savegame.ARMY_COUNT, army + 1)
    for i in range(savegame.SLOTS):
        save.state[savegame.ROSTER + i * RECORD + savegame.U_INDEX] = i
    return {"slot": slot, "serial": serial, "row": row, "warnings": warnings,
            "learned_extra": {serial: list(entry.get("learned_extra") or [])} if entry.get("learned_extra")
            else {}}


def verify(save):
    """the invariants an imported unit must not break -> list of problems (empty is the pass)"""
    bad = []
    army, reserve = save.army_count, save.reserve_count
    if army < 0 or reserve < 0:
        bad.append(f"army {army} / reserve {reserve}")
    if army + reserve > savegame.SLOTS:
        bad.append(f"army {army} + reserve {reserve} exceeds {savegame.SLOTS} slots")
    serials = {}
    for u in save.units():
        base = u.base
        if _u32(save.state, base + savegame.U_USED) == 0:
            bad.append(f"slot {u.slot} is in the army/reserve but not in use")
        got = save.state[base + savegame.U_INDEX]
        if got != u.slot:
            bad.append(f"slot {u.slot} says its index is {got}")
        if u.serial in serials:
            bad.append(f"serial {u.serial} names slots {serials[u.serial]} and {u.slot}")
        serials[u.serial] = u.slot
    top = max(serials) if serials else 0
    if uid_next(save) < top:
        bad.append(f"the serial counter ({uid_next(save)}) is below the highest serial in use ({top})")
    return bad


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# --- what Dismiss does outside the roster that remove_units() leaves out (BANKPR1, decomp of the Steam exe)
GAME_FLAGS = 0xE                           # game_flags: bit n at state[0xE + n // 8]
# The exe table 0x140A0D960 (39 rows of 20 bytes: u32 flag at +4, s16 class id at +8), looked up by 0x140142250.
# Dismiss (0x140652580, the clear after the three serial lists) clears the class's flag when the id is below 1000
# (or 2460): the DLC guests' "recruited" flag, read by the guest room (0x140142580) before it offers the character
# again.  Ids >= 1000 in the table (1240/1250/1260) are never cleared.  590 and 800 share flag 18312 (as in the game).
GUEST_FLAGS = {510: 18300, 520: 18301, 530: 18302, 540: 18303, 550: 18304, 560: 18305, 570: 18310, 580: 18311,
               590: 18312, 600: 18313, 610: 18314, 620: 18315, 630: 18316, 640: 18320, 650: 18321, 660: 18322,
               670: 18323, 680: 18324, 690: 18325, 700: 18330, 710: 18331, 720: 18332, 730: 18340, 740: 18341,
               750: 18342, 760: 18343, 800: 18312, 860: 18345, 870: 18346, 880: 18347, 890: 18348, 900: 18349,
               910: 18350, 920: 18351, 930: 18352, 940: 18353}


def clear_guest_flag(save, cls, on=False):
    """the guest-room flag Dismiss clears for a DLC character leaving the army (on=True sets it for one arriving: in the
    four test saves every DLC character in the army has it set, 46 of 46) -> the flag, or None"""
    flag = GUEST_FLAGS.get(int(cls))
    if flag is None:
        return None
    if on:
        save.state[GAME_FLAGS + flag // 8] |= 1 << (flag & 7)
    else:
        save.state[GAME_FLAGS + flag // 8] &= ~(1 << (flag & 7)) & 0xFF
    return flag


# --- equipment.  D5 has one item store (bag = warehouse): 2000 blocks of 0x258 at state+0x482FD8 (global 0x14544FAD8),
# u16 count at state+0x5A7F58; a block is used when its u32 item id at +0x128 is non-zero.  The Equip menu's remove
# (0x14027bc80) calls data_inventory_add_item 0x1401c9ba0 (compact, then a verbatim 0x258 copy into the first free slot,
# count + 1; -1 and nothing changed when all 2000 are used), then clears the equipment slot with 0x1401c9b70 (zeros,
# s32 -1 at +0x1CC).  The block holds its innocents and Item World index itself, and names no owner.
BAG, BAG_SLOTS, BAG_COUNT = 0x482FD8, 2000, 0x5A7F58
ITEM, ITEM_ID, ITEM_MARK, EQUIP_SLOTS = 0x258, 0x128, 0x1CC, 5
EMPTY_ITEM = bytes(ITEM_MARK) + b"\xff\xff\xff\xff" + bytes(ITEM - ITEM_MARK - 4)


def equipped(record):
    """[(equipment slot, 0x258-byte block)] of the items a record carries"""
    out = []
    for k in range(EQUIP_SLOTS):
        o = ITEMS + k * ITEM
        if _u32(record, o + ITEM_ID):
            out.append((k, bytes(record[o:o + ITEM])))
    return out


def strip_items(record):
    """the record with every equipment slot emptied the way the game empties one"""
    raw = bytearray(record)
    for k, _ in equipped(record):
        raw[ITEMS + k * ITEM:ITEMS + (k + 1) * ITEM] = EMPTY_ITEM
    return bytes(raw)


def bag_free(save):
    return [i for i in range(BAG_SLOTS) if not _u32(save.state, BAG + i * ITEM + ITEM_ID)]


def unequip_to_bag(save, slot):
    """move a unit's equipped items into the save's bag, as the Equip menu's remove does -> number moved.
    Raises ValueError, changing nothing, when the bag has no room for all of them (the game refuses item by item;
    a half-unequipped unit is not offered)."""
    base = savegame.ROSTER + int(slot) * RECORD
    items = equipped(save.state[base:base + RECORD])
    free = bag_free(save)
    if len(free) < len(items):
        raise ValueError(f"the item bag has room for {len(free)} of the unit's {len(items)} items "
                         f"({BAG_SLOTS} is the game's limit); empty the bag or keep the gear on")
    count = struct.unpack_from("<H", save.state, BAG_COUNT)[0]
    for (k, block), i in zip(items, free):
        save.state[BAG + i * ITEM:BAG + (i + 1) * ITEM] = block
        o = base + ITEMS + k * ITEM
        save.state[o:o + ITEM] = EMPTY_ITEM
    struct.pack_into("<H", save.state, BAG_COUNT, count + len(items))
    return len(items)


_SAME_MASK = ((savegame.U_SERIAL, 8), (savegame.U_INDEX, 1), (savegame.U_ROW, 2), (savegame.U_SQUAD, 2),
              (savegame.U_GROUP, 1))


def _masked(record):
    raw = bytearray(record)
    for off, n in _SAME_MASK:
        raw[off:off + n] = bytes(n)
    return bytes(raw)


def same_unit_in(save, entry):
    """the roster slot of a unit that is this bank entry already (equal outside the ids an import re-addresses), or None"""
    want = _masked(entry_record(entry))
    for u in save.units():
        if _masked(_record(save, u.slot)[1]) == want:
            return u.slot
    return None
