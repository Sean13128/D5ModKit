"""Disgaea 5 Complete saves: read and write them, list the army, and take characters out of a save the way the
game's own Dismiss does (for the characters of a mod that is deleted).

Files: %APPDATA%\\Nippon Ichi Software, Inc\\Disgaea 5 Complete\\<player>\\SaveData\\Save_NNN.sav, AutoSave.sav
(SystemSave.sav holds the options, no units).  The October 2018 build and today's Steam build read and write the same
format (loader 0x140748a60, writer 0x140749000 in the launch exe; every offset below is the same in both).

    0x000  0x1C0-byte header, obfuscated with the NISPACK nibble cipher (d5lib.crypt): magic
           'NIS_DISGAEA5_COMPLETE_SAVEDATA_', +0x38 u32 body size, +0x40 title, +0xC0 chapter, +0x140 play time
    0x1C0  u64 0xE5B2688ACB279CA6, then a YKCMP_V1 container with every whole u64 XOR 0xE76FCBE3F6D46A37.  It holds
           the game state, 0x89B8C8 bytes, which the game copies as it is to 0x144FFA9A0 (offsets below are into it).
           The game writes type 4 (Yukes LZ); it reads every YKCMP type, and the kit writes type 7 (zlib).

State
    0x23B2B8  roster: 128 units of 0x4750 bytes.  The army is units 0 .. army-1 (s16 at 0x5A7F9C); the reserve
              (overlords the story or a recruit quest hands over later) is the top `reserve` units (s16 at
              0x5A7F9E).  The slots between are blank records, or stale copies the game leaves when a unit moves.
    unit      +0x000 u32 in use, +0xBC8 name, +0xBFC title, +0x2DFC u16 level, +0x2E04 u32 class (char.dat id),
              +0x2E0A s16 char.dat row of the class (the kit's runtime re-points it when rows move,
              d5lib/native/d5rows.inc.c), +0x2E31 u8 roster index, +0x3058 s16 squad (-1 none), +0x3060 u64
              serial (the tables below name units by it), +0x30A0 u8 group (0xFF none)
              +0x2DA8 weapon mastery, 10 x 8 bytes (fist .. armor, d5lib.weaponlevels.WEAPONS): u32 experience,
              u8 level, u8 (level with bonuses), u8 aptitude = the rank (char.dat mastery_*, copied when the unit is
              made and never changed after), u8 bonus.  The game's 'set weapon level' (0x14015b980) writes the
              level and its experience, 300 x (L (L + 1) / 2 + 4 L), L at most 101.
    0x5A8058  squads: 0x2B0 each, 10 member serials, u32 member count at +0x50                   (0x1402bc3f0)
    0x87B7F0  25 groups: 0xB8 each, 20 member serials, u8 size at +0xA8, leader serial at +0xB0  (0x1401d27f0)
    0x878D48  serial of the unit walking the base; 0x879158 its 5 followers, u32 count at 0x879184 (0x1401c25a0)
    0x880498  3 lists of 128 serials                                                           (0x140654770)
    0x87CE22 / 0x87D222 / 0x87D622  quest progress, one byte per Quest.dat sort_order (0x400 each): completed /
              accepted / seen (0x1458777c2 .. in the launch exe; the Quest Shop's completed list matches them)

Dismiss (0x140654770, the menu's handler) takes a unit out like this, and remove_units() does the same: the base
walker and its followers, the three serial lists, the 'recruited' flag of a vanilla overlord (a static table in the
exe; no kit character is in it), its group (a new leader from the members), its squad, then it swaps the unit to the
end of the army (every slot's +0x2E31 renumbered) and lowers the army count.  remove_units() also blanks that slot
and any stale copy of the unit, so nothing of it is left in the save.
"""
import glob
import os
import shutil
import struct
import time

from . import crypt, ykcmp

HEADER = 0x1C0
MAGIC = b"NIS_DISGAEA5_COMPLETE_SAVEDATA_"
BODY_MAGIC = 0xE5B2688ACB279CA6
BODY_KEY = 0xE76FCBE3F6D46A37
STATE_SIZE = 0x89B8C8
H_BODY_SIZE, H_TITLE, H_CHAPTER = 0x38, 0x40, 0xC0

ROSTER, UNIT, SLOTS = 0x23B2B8, 0x4750, 128
ARMY_COUNT, RESERVE_COUNT = 0x5A7F9C, 0x5A7F9E
U_USED, U_NAME, U_TITLE, U_LEVEL, U_CLASS, U_ROW, U_INDEX = 0x0, 0xBC8, 0xBFC, 0x2DFC, 0x2E04, 0x2E0A, 0x2E31
U_SQUAD, U_SERIAL, U_GROUP = 0x3058, 0x3060, 0x30A0
U_WEAPONS, WEAPON_SIZE, WEAPON_COUNT = 0x2DA8, 8, 10
SQUADS, SQUAD_SIZE, SQUAD_MEMBERS, SQUAD_COUNT = 0x5A8058, 0x2B0, 10, 0x50
GROUPS, GROUP_SIZE, GROUP_COUNT, GROUP_MEMBERS, GROUP_SLOTS, GROUP_LEADER = 0x87B7F0, 0xB8, 25, 20, 0xA8, 0xB0
GROUP_FLAGS = 0x923                 # bit 1: group 24 is in use (0x1401d2829)
BASE_WALKER = 0x878D48
FOLLOWERS, FOLLOWER_SLOTS, FOLLOWER_COUNT = 0x879158, 5, 0x879184
SERIAL_LISTS, LIST_LEN, LIST_COUNT = 0x880498, 128, 3
QUEST_COMPLETED, QUEST_ACCEPTED, QUEST_SEEN, QUEST_SLOTS = 0x87CE22, 0x87D222, 0x87D622, 0x400
KILLIA = 10                         # the base walker when the one walking is dismissed (0x1401c2610)

SAVE_GLOB = ("Save_*.sav", "AutoSave.sav")


def save_root():
    """the game's save folder: one folder per player id, each with SaveData"""
    return os.path.join(os.environ.get("APPDATA", ""), "Nippon Ichi Software, Inc", "Disgaea 5 Complete")


def save_files(root=None):
    """every Save_NNN.sav / AutoSave.sav of every player folder, sorted"""
    root = root or save_root()
    out = []
    for pat in SAVE_GLOB:
        out += glob.glob(os.path.join(root, "*", "SaveData", pat))
    return sorted(out)


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _s16(b, o):
    return struct.unpack_from("<h", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def _text(b, o, n=0x30):
    return bytes(b[o:o + n]).split(b"\0")[0].decode("utf-8", "replace")


def _mask(body: bytes) -> bytes:
    n = len(body) // 8
    words = struct.unpack_from(f"<{n}Q", body)
    return struct.pack(f"<{n}Q", *(w ^ BODY_KEY for w in words)) + body[n * 8:]


class Unit:
    def __init__(self, save, slot):
        self.save, self.slot = save, slot
        self.base = ROSTER + slot * UNIT

    def _get(self, fn, off):
        return fn(self.save.state, self.base + off)

    name = property(lambda self: _text(self.save.state, self.base + U_NAME))
    title = property(lambda self: _text(self.save.state, self.base + U_TITLE, 0x44))
    level = property(lambda self: self._get(_u16, U_LEVEL))
    cls = property(lambda self: self._get(_u32, U_CLASS))
    serial = property(lambda self: self._get(_u64, U_SERIAL))
    squad = property(lambda self: self._get(_s16, U_SQUAD))
    group = property(lambda self: self.save.state[self.base + U_GROUP])
    reserve = property(lambda self: self.slot >= SLOTS - self.save.reserve_count)

    def set_class(self, cls):
        struct.pack_into("<I", self.save.state, self.base + U_CLASS, int(cls))

    def _weapon(self, w):
        return self.base + U_WEAPONS + int(w) * WEAPON_SIZE

    def weapons(self):
        """[(level, aptitude)] of the 10 weapons, fist .. armor"""
        b = self.save.state
        return [(b[self._weapon(w) + 4], b[self._weapon(w) + 6]) for w in range(WEAPON_COUNT)]

    def set_weapon_level(self, w, level):
        """as the game's 'set weapon level' (0x14015b980): the level and its experience"""
        level = max(0, min(255, int(level)))
        self.save.state[self._weapon(w) + 4] = level
        struct.pack_into("<I", self.save.state, self._weapon(w), weapon_exp(level))

    def set_aptitude(self, w, v):
        self.save.state[self._weapon(w) + 6] = max(0, min(255, int(v)))

    def __repr__(self):
        return f"<unit {self.slot}: {self.name!r} class {self.cls} Lv{self.level}>"


class Save:
    """one save file: its header and the game state (a bytearray you can change, then write())"""

    def __init__(self, path):
        self.path = path
        data = open(path, "rb").read()
        if len(data) < HEADER + 8:
            raise ValueError(f"{os.path.basename(path)}: too short for a save")
        self.header = bytearray(crypt.decode(data[:HEADER]))
        if not self.header.startswith(MAGIC):
            raise ValueError(f"{os.path.basename(path)}: not a Disgaea 5 Complete save")
        body = data[HEADER:]
        if _u64(body, 0) != BODY_MAGIC:
            raise ValueError(f"{os.path.basename(path)}: unknown save body")
        self.state = bytearray(ykcmp.decompress(_mask(body[8:])))
        if len(self.state) != STATE_SIZE:
            raise ValueError(f"{os.path.basename(path)}: game state of {len(self.state)} bytes, not {STATE_SIZE}")

    # --- header
    title = property(lambda self: _text(self.header, H_TITLE, 0x80))
    chapter = property(lambda self: _text(self.header, H_CHAPTER, 0x80))
    player = property(lambda self: os.path.basename(os.path.dirname(os.path.dirname(self.path))))
    label = property(lambda self: os.path.splitext(os.path.basename(self.path))[0].replace("_", " "))

    # --- roster
    army_count = property(lambda self: _s16(self.state, ARMY_COUNT))
    reserve_count = property(lambda self: _s16(self.state, RESERVE_COUNT))

    def army(self):
        return [Unit(self, i) for i in range(max(0, self.army_count))]

    def reserve(self):
        return [Unit(self, i) for i in range(SLOTS - max(0, self.reserve_count), SLOTS)]

    def units(self):
        """army + reserve"""
        return self.army() + self.reserve()

    # --- quests
    def quest_state(self, slot):
        """(completed, accepted, seen) of a Quest.dat sort_order"""
        return tuple(self.state[a + slot] for a in (QUEST_COMPLETED, QUEST_ACCEPTED, QUEST_SEEN))

    def finish_quest(self, slot):
        """the quest on that progress slot as done (seen, accepted, completed); -> True when anything changed"""
        if not 0 <= slot < QUEST_SLOTS:
            return False
        was = self.quest_state(slot)
        for a in (QUEST_COMPLETED, QUEST_ACCEPTED, QUEST_SEEN):
            self.state[a + slot] = 1
        return was != (1, 1, 1)

    def reset_quest(self, slot):
        """the quest on that progress slot as never seen; -> True when anything was set"""
        if not 0 <= slot < QUEST_SLOTS:
            return False
        was = any(self.quest_state(slot))
        for a in (QUEST_COMPLETED, QUEST_ACCEPTED, QUEST_SEEN):
            self.state[a + slot] = 0
        return was

    # --- taking units out (0x140654770)
    def _q(self, off):
        return _u64(self.state, off)

    def _setq(self, off, v):
        struct.pack_into("<Q", self.state, off, v)

    def _serials_in_army(self):
        return {u.serial: u for u in self.army()}

    def _drop_walker(self, unit):
        """0x1401c25a0: the unit walking the base and its followers"""
        st, serial = self.state, unit.serial
        if self._q(BASE_WALKER) == serial:
            rest = [u for u in self.army() if u.slot != unit.slot]
            new = next((u for u in rest if u.cls == KILLIA), None) or next((u for u in rest if u.serial == 1), None) \
                or (rest[0] if rest else None)
            self._setq(BASE_WALKER, new.serial if new else 0)
            if new:
                self._drop_follower(new.serial)
        self._drop_follower(serial)

    def _drop_follower(self, serial):
        slots = [self._q(FOLLOWERS + 8 * k) for k in range(FOLLOWER_SLOTS)]
        if serial not in slots:
            return
        k = slots.index(serial)
        slots = slots[:k] + slots[k + 1:] + [0]
        for j, v in enumerate(slots):
            self._setq(FOLLOWERS + 8 * j, v)
        struct.pack_into("<I", self.state, FOLLOWER_COUNT, max(0, _u32(self.state, FOLLOWER_COUNT) - 1))

    def _drop_from_lists(self, serial):
        for n in range(LIST_COUNT):
            base = SERIAL_LISTS + n * LIST_LEN * 8
            vals = [self._q(base + 8 * k) for k in range(LIST_LEN)]
            if serial in vals:
                k = vals.index(serial)
                vals = vals[:k] + vals[k + 1:] + [0]
                for j, v in enumerate(vals):
                    self._setq(base + 8 * j, v)

    def _drop_group(self, unit):
        """0x1401d27f0 / 0x1401d2640"""
        g = unit.group
        if g > GROUP_COUNT - 1:
            return
        if g == GROUP_COUNT - 1:
            self.state[GROUP_FLAGS] &= 0xFD
        self.state[unit.base + U_GROUP] = 0xFF
        base = GROUPS + g * GROUP_SIZE
        serial = unit.serial
        for k in range(GROUP_MEMBERS):
            if self._q(base + 8 * k) == serial:
                self._setq(base + 8 * k, 0)
        if self._q(base + GROUP_LEADER) == serial:
            army = self._serials_in_army()
            size = min(self.state[base + GROUP_SLOTS], GROUP_MEMBERS)
            new = 0
            for k in range(size):
                s = _u32(self.state, base + 8 * k)
                if s and s != serial and s in army and _u32(self.state, army[s].base + U_USED):
                    new = s
                    break
            self._setq(base + GROUP_LEADER, new)

    def _drop_squad(self, unit):
        """0x1402bc3f0"""
        sq = unit.squad
        if sq < 0:
            return
        base = SQUADS + sq * SQUAD_SIZE
        vals = [self._q(base + 8 * k) for k in range(SQUAD_MEMBERS)]
        if unit.serial in vals:
            k = vals.index(unit.serial)
            struct.pack_into("<I", self.state, base + SQUAD_COUNT, max(0, _u32(self.state, base + SQUAD_COUNT) - 1))
            vals = vals[:k] + vals[k + 1:] + [0]
            for j, v in enumerate(vals):
                self._setq(base + 8 * j, v)
        struct.pack_into("<h", self.state, unit.base + U_SQUAD, -1)

    def _blank(self):
        """a never-used roster record (the first blank slot between army and reserve), or None"""
        lo, hi = max(0, self.army_count), SLOTS - max(0, self.reserve_count)
        for i in range(lo, hi):
            b = ROSTER + i * UNIT
            if not _u32(self.state, b + U_USED) and not _u64(self.state, b + U_SERIAL) \
                    and not _u32(self.state, b + U_CLASS):
                return bytes(self.state[b:b + UNIT])
        return None

    def remove_units(self, slots):
        """take these army units out, as Dismiss does -> [(name, class, level)] removed"""
        blank = self._blank()
        out = []
        for slot in sorted({int(s) for s in slots}, reverse=True):
            if not 0 <= slot < self.army_count:
                continue
            u = Unit(self, slot)
            out.append((u.name, u.cls, u.level))
            serial = u.serial
            self._drop_walker(u)
            self._drop_from_lists(serial)
            self._drop_group(u)
            self._drop_squad(u)
            n = self.army_count
            for j in range(slot, n - 1):                    # 0x1402e8260 (j, j + 1), repeated
                a, b = ROSTER + j * UNIT, ROSTER + (j + 1) * UNIT
                self.state[a:a + UNIT], self.state[b:b + UNIT] = self.state[b:b + UNIT], self.state[a:a + UNIT]
            struct.pack_into("<h", self.state, ARMY_COUNT, n - 1)
            if blank is not None:
                last = ROSTER + (n - 1) * UNIT
                self.state[last:last + UNIT] = blank
            self._blank_copies(serial, blank)
        for i in range(SLOTS):
            self.state[ROSTER + i * UNIT + U_INDEX] = i
        return out

    def _blank_copies(self, serial, blank):
        """stale copies of a removed unit between army and reserve"""
        if blank is None or not serial:
            return
        for i in range(max(0, self.army_count), SLOTS - max(0, self.reserve_count)):
            b = ROSTER + i * UNIT
            if _u64(self.state, b + U_SERIAL) == serial:
                self.state[b:b + UNIT] = blank

    def fix_rows(self, class_ids):
        """+0x2E0A of every army / reserve unit -> the row of its class in a char.dat with these ids (the game sorts
        the table by id); a unit whose class isn't there keeps its row.  -> number changed"""
        rows = {c: i for i, c in enumerate(sorted(class_ids))}
        n = 0
        for u in self.units():
            r = rows.get(u.cls)
            if r is not None and _s16(self.state, u.base + U_ROW) != r:
                struct.pack_into("<h", self.state, u.base + U_ROW, r)
                n += 1
        return n

    # --- writing
    def to_bytes(self) -> bytes:
        body = struct.pack("<Q", BODY_MAGIC) + _mask(ykcmp.compress(bytes(self.state)))
        hdr = bytearray(self.header)
        struct.pack_into("<I", hdr, H_BODY_SIZE, len(body))
        return crypt.encode(bytes(hdr)) + body

    def write(self, path=None):
        path = path or self.path
        data = self.to_bytes()
        check = Save.__new__(Save)
        check.path = path
        _parse_into(check, data)
        if check.state != self.state:
            raise ValueError("the save did not read back the same; nothing written")
        tmp = path + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)


def _parse_into(save, data):
    save.header = bytearray(crypt.decode(data[:HEADER]))
    save.state = bytearray(ykcmp.decompress(_mask(data[HEADER + 8:])))


def backup(paths, kit_dir, why="saves"):
    """copies of these save files in state/save_backups/<time>_<why>/<player>/SaveData -> that folder"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(kit_dir, "state", "save_backups", f"{stamp}_{why}")
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(kit_dir, "state", "save_backups", f"{stamp}_{why}_{n}")
        n += 1
    for p in paths:
        player = os.path.basename(os.path.dirname(os.path.dirname(p)))
        d = os.path.join(dst, player, "SaveData")
        os.makedirs(d, exist_ok=True)
        shutil.copy2(p, os.path.join(d, os.path.basename(p)))
    return dst


def find(class_ids, quest_slots=(), root=None, log=None):
    """saves holding units of these classes or progress on these quest slots ->
    [(path, Save, [Unit in the army], [Unit in the reserve], {slot: (completed, accepted, seen)})]"""
    class_ids = {int(c) for c in class_ids}
    out = []
    for p in save_files(root):
        try:
            s = Save(p)
        except (OSError, ValueError) as e:
            if log:
                log(f"  {p}: {e}")
            continue
        army = [u for u in s.army() if u.cls in class_ids]
        res = [u for u in s.reserve() if u.cls in class_ids]
        quests = {q: s.quest_state(q) for q in quest_slots if 0 <= q < QUEST_SLOTS and any(s.quest_state(q))}
        if army or res or quests:
            out.append((p, s, army, res, quests))
    return out


def recruit_mismatches(save, recruits):
    """recruit quests whose progress doesn't match the army.  recruits: [(slot, title, character name, {class ids:
    the character and its outfits})] -> [(slot, title, name, "missing" | "not_done")]: "missing" = shown done but no
    unit of the character in the save (progress another quest left on the slot: it can be done again), "not_done" =
    the character is there but its quest isn't done (the Quest Shop would recruit a second one)"""
    have = {u.cls for u in save.units()}
    out = []
    for slot, title, name, classes in recruits:
        done = save.quest_state(slot)[0]
        present = bool(have & set(classes))
        if done and not present:
            out.append((slot, title, name, "missing"))
        elif present and not done:
            out.append((slot, title, name, "not_done"))
    return out


def weapon_exp(level):
    """the weapon experience of a level (0x14015b980)"""
    lv = min(int(level), 101)
    return 300 * (lv * (lv + 1) // 2 + 4 * lv)


def weapon_mismatches(save, classes):
    """classes {class id: (aptitudes [10], starting levels [10] or None)} -> [(unit, [(weapon, aptitude, level)])]:
    units whose weapon ranks are not their class's (made before the class's ranks changed: a unit keeps the ranks it
    was made with) or whose weapon level is below the class's starting level.  aptitude / level None: unchanged."""
    out = []
    for u in save.units():
        want = classes.get(u.cls)
        if want is None:
            continue
        apts, levels = want
        ch = []
        for w, (lv, apt) in enumerate(u.weapons()):
            a = int(apts[w]) if apts is not None and int(apts[w]) != apt else None
            to = int(levels[w]) if levels is not None and lv < int(levels[w]) else None
            if a is not None or to is not None:
                ch.append((w, a, to))
        if ch:
            out.append((u, ch))
    return out


def fix_weapons(save, plan):
    """plan {slot: (class, [(weapon, aptitude or None, level or None)])} (weapon_mismatches) -> lines: the ranks set,
    weapon levels raised (never lowered: what a unit earned in game stays)"""
    lines = []
    for slot, (cls, changes) in (plan or {}).items():
        u = Unit(save, int(slot))
        if u.cls != int(cls):
            continue
        did = 0
        for w, apt, lv in changes:
            if apt is not None and u.weapons()[w][1] != apt:
                u.set_aptitude(w, apt)
                did += 1
            if lv is not None and u.weapons()[w][0] < lv:
                u.set_weapon_level(w, lv)
                did += 1
        if did:
            lines.append(f"{u.name} (Lv{u.level}): weapon mastery updated")
    return lines


def clean(save, class_ids, quest_slots=(), outfits=None, finish=(), guard=None):
    """take the units of class_ids out of the army, units wearing one of `outfits` ({outfit class: base class})
    back into their own look, reset the quests on quest_slots and mark the ones on `finish` done -> list of what
    changed (text lines).  guard {slot: class ids}: a slot is not reset when the save has a unit of those classes
    (another character's quest uses it, and the progress is that character's)"""
    class_ids = {int(c) for c in class_ids}
    outfits = {int(k): int(v) for k, v in (outfits or {}).items()}
    lines = []
    for u in save.units():
        if u.cls in outfits and outfits[u.cls] not in class_ids:
            lines.append(f"{u.name} (Lv{u.level}) back to the default outfit")
            u.set_class(outfits[u.cls])
    gone = [u.slot for u in save.army() if u.cls in class_ids or outfits.get(u.cls) in class_ids]
    for name, cls, lv in save.remove_units(gone):
        lines.append(f"{name} (Lv{lv}, class {cls}) taken out")
    have = {u.cls for u in save.units()}
    for q in quest_slots:
        if guard and have & set(guard.get(q, ())):
            continue
        if save.reset_quest(q):
            lines.append(f"recruit quest progress (slot {q}) cleared")
    for q in finish:
        if save.finish_quest(q):
            lines.append(f"recruit quest (slot {q}) marked done")
    return lines


RESERVED_NAMES = {"Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy"}   # = dbpatch.RESERVED_NAMES


def mod_characters(mod, vanilla_char=None):
    """what a mod adds that a save can hold -> dict(classes={id: name}, outfits={outfit class: base class},
    quests={progress slot: title})
      classes  its new characters and classes: a char.dat row it adds, or a reserved dummy row it fills; never a
               character or class of the game (vanilla_char: the game's char.dat table, to tell them apart)
      outfits  its outfit slots and the character each belongs to (units wearing one go back to that character)
      quests   the progress slots of the quests that recruit its characters (reward 5 / class unlock 6)"""
    van = list(vanilla_char.rows) if vanilla_char is not None else []
    vname = {r["id"]: r["name_EN"] for r in van}
    pairs = (mod.load_patch("outfits", "outfits.json") or {}).get("pairs") or []
    outfits = {int(b): int(a) for a, b in pairs}
    patch = mod.load_patch("db", "char.dat.json") or {}
    classes = {}
    for r in patch.get("added") or []:
        cid = int(r.get("id", -1))
        if cid < 0 or cid in outfits or (cid in vname and vname[cid] not in RESERVED_NAMES):
            continue
        classes[cid] = r.get("name_EN") or f"class {cid}"
    for idx, fields in (patch.get("rows") or {}).items():
        i = int(idx)
        if i < len(van) and van[i]["name_EN"] in RESERVED_NAMES and van[i]["id"] not in outfits                 and fields.get("name_EN") not in (None, "", van[i]["name_EN"]):
            classes[van[i]["id"]] = fields["name_EN"]
    quests = {}
    for r in (mod.load_patch("db", "Quest.dat.json") or {}).get("added") or []:
        if int(r.get("reward_type", 0)) in (5, 6) and int(r.get("reward_value", -1)) in classes and "sort_order" in r:
            quests[int(r["sort_order"])] = r.get("name_EN") or f"quest {r.get('id')}"
    return {"classes": classes, "outfits": outfits, "quests": quests}


def save_roots(kit_dir=None):
    """[(label, folder)]: the game's save folder, then the saves the kit keeps for profiles (they go back into the
    game when their profile is installed, d5lib.profiles)"""
    out = [("", save_root())]
    if kit_dir:
        prof = os.path.join(kit_dir, "profiles")
        if os.path.isdir(prof):
            for d in sorted(os.listdir(prof)):
                store = os.path.join(prof, d) if d == ".shared_saves" else os.path.join(prof, d, "saves")
                if os.path.isdir(store):
                    out.append(("shared saves" if d == ".shared_saves" else f"profile {d}", store))
    return out
