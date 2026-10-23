"""Where a skill hits: magic.dat (range, attack_map, height reach) + AttackMap.dat (area shapes).

What the game does (disgaea5.exe, 2026-10-10):
  * AttackMap.dat stays in memory as loaded (0x1400c3aa0): u16 count, u16 cell count, 8-byte shape records
    (u32 id, u16 first cell, u8 cell count, u8 directional), 3-byte cells (i8 x, i8 y, u8 kind), then 3 junk bytes.
    A shape is found by a linear search for its id compared as a u16 (0x14008a6f0, 0x1401389e0): new shapes can go
    anywhere in the file, their ids must be below 65536.
  * a cell turns with the caster's facing like a script offset does (0x140138940): facing 0 as written, 1 (x, y) ->
    (y, -x), 2 -> (-x, -y), 3 -> (-y, x), then + the base panel.  So x = sideways and y = forward in the same frame as
    the scripts' offsets (stage.turn_offset), whatever the facing.
  * kinds: 1 a panel it hits, 3 the cursor's panel (hit too), 2 where the caster ends up (skills that move them).
  * range > 0: the player puts a cursor on a panel up to `range` panels away and the shape is centred on it;
    range 0: the shape is placed from the caster (Exploding Tiger: 3000 = the 3 panels in front).
  * the units on the hit panels are the area targets, in the shape's cell order: script actor 3000 + i, variable
    $60400 + i = 1 when target i exists; 3600 = the main target.  5000 + i is the place of area panel i.
"""
from dataclasses import dataclass, field

HIT, USER_TO, CURSOR = 1, 2, 3
KIND_NAMES = {HIT: "hit", USER_TO: "caster ends here", CURSOR: "cursor (hit)"}
NEW_SHAPE_BASE = 40000          # ids of shapes the kit makes (vanilla: 1 .. 33464; the game compares ids as u16)
MAX_SHAPE_ID = 65535
MAX_CELLS = 255                 # u8 cell count
MAP_WIDE = 99                   # range 99: anywhere on the map


@dataclass
class Shape:
    id: int
    cells: list                 # [(x, y, kind)]: x sideways, y forward (panels)
    directional: bool = True


@dataclass
class Area:
    """a skill's reach and area, as the battle uses them"""
    skill: int = None
    range: int = 0
    shape: int = 0
    cells: list = field(default_factory=list)
    height_up: int = 0
    height_down: int = 0
    known: bool = True          # False: magic.dat gives no shape (generic spells): one panel at the cursor

    @property
    def centred(self):
        """the shape is centred on a cursor the player places (else it is placed from the caster)"""
        return self.range > 0 or not self.known

    def hit_cells(self):
        return [(x, y) for x, y, k in self.cells if k in (HIT, CURSOR)]

    def panels(self, cursor=1):
        """[(x, y, kind)] relative to the caster's panel (x sideways, y forward); cursor = panels to the cursor"""
        dy = int(cursor) if self.centred else 0
        return [(x, y + dy, k) for x, y, k in self.cells]

    def target_panels(self, cursor=1, chosen=None):
        """panels of the area targets in the game's order (the shape's cell order), relative to the caster;
        chosen: the hit panels (relative to the caster) that hold an enemy (None: the first hit panel only)"""
        hits = [(x, y) for x, y, k in self.panels(cursor) if k in (HIT, CURSOR)]
        if chosen is None:
            return hits[:1] or [(0, int(cursor))]
        ch = {tuple(c) for c in chosen}
        return [p for p in hits if p in ch] or hits[:1] or [(0, int(cursor))]

    def reach(self):
        """panels the cursor may go to (range > 0): a diamond of `range` around the caster (not the caster's own)"""
        r = self.range
        if r <= 0 or r >= MAP_WIDE:
            return []
        return [(x, y) for x in range(-r, r + 1) for y in range(-r, r + 1) if 0 < abs(x) + abs(y) <= r]


def default_area(skill=None):
    return Area(skill=skill, range=0, shape=0, cells=[(0, 0, CURSOR)], known=False)


def is_directional(cells):
    """the game's flag: 0 for shapes that look the same turned by 90 degrees"""
    s = {(x, y, k) for x, y, k in cells}
    return s != {(-y, x, k) for x, y, k in cells}


def shapes(table):
    """AttackMap.dat table (d5lib.database) -> {id: Shape}"""
    cells = table.sections["cells"].rows
    out = {}
    for r in table.rows:
        f, n = int(r["first_cell"]), int(r["cell_num"])
        out[int(r["id"])] = Shape(int(r["id"]), [(int(c["x"]), int(c["y"]), int(c["kind"])) for c in cells[f:f + n]],
                                  bool(r["directional"]))
    return out


def area_of(row, shape_map):
    """a magic.dat row -> Area"""
    if row is None:
        return default_area()
    sid = int(row["attack_map"] or 0)
    sh = shape_map.get(sid) if sid else None
    a = Area(skill=int(row["id"]), range=int(row["range"] or 0), shape=sid,
             cells=list(sh.cells) if sh else [(0, 0, CURSOR)], height_up=int(row["height_up"] or 0),
             height_down=int(row["height_down"] or 0), known=sh is not None)
    return a


def describe(area):
    """a short line for people: reach, panels, height"""
    n = len(area.hit_cells())
    if not area.known:
        return "One panel at the cursor (this skill's area is not in magic.dat)"
    where = (f"up to {area.range} panels away" if 0 < area.range < MAP_WIDE else
             "anywhere on the map" if area.range >= MAP_WIDE else "from the caster")
    moves = any(k == USER_TO for _, _, k in area.cells)
    return (f"Hits {n} panel{'s' if n != 1 else ''} · {where} · reach up {area.height_up} / down "
            f"{area.height_down}" + (" · moves the caster" if moves else ""))


def users(magic_table, shape_id):
    """skill ids whose attack_map is shape_id"""
    return [int(r["id"]) for r in magic_table.rows if int(r["attack_map"] or 0) == int(shape_id)]


def find_shape(shape_map, cells):
    """an existing shape with exactly these cells (same order: it decides the target order) or None"""
    want = [tuple(c) for c in cells]
    for sid, sh in sorted(shape_map.items()):
        if [tuple(c) for c in sh.cells] == want:
            return sid
    return None


def store(magic_table, attack_table, skill, area, base_rows=None, base_cells=None):
    """write a skill's area into the tables (the caller saves them): range / height into magic.dat; the shape is an
    existing one with the same cells, the skill's own kit-made shape (rewritten when no other skill uses it) or a
    new one (id NEW_SHAPE_BASE + ..., its cells appended).  base_rows / base_cells: AttackMap.dat's sizes without
    this mod (shapes and cells past them are this mod's own; unused ones are dropped).  -> the shape id used"""
    from .database import Row
    if not area.cells:
        raise ValueError("the area needs at least one panel")
    if len(area.cells) > MAX_CELLS:
        raise ValueError(f"an area has at most {MAX_CELLS} panels")
    for x, y, k in area.cells:
        if not (-128 <= x <= 127 and -128 <= y <= 127) or k not in KIND_NAMES:
            raise ValueError(f"bad panel {(x, y, k)}")
    row = next((r for r in magic_table.rows if int(r["id"]) == int(skill)), None)
    if row is None:
        raise KeyError(f"no skill {skill} in magic.dat")
    shape_map = shapes(attack_table)
    sid = find_shape(shape_map, area.cells)
    if sid is None:
        cur = int(row["attack_map"] or 0)
        cells_t = attack_table.sections["cells"]
        own = (cur >= NEW_SHAPE_BASE and cur in shape_map and users(magic_table, cur) == [int(skill)])
        rec = next((r for r in attack_table.rows if int(r["id"]) == cur), None) if own else None
        if rec is None:
            sid = max([NEW_SHAPE_BASE - 1] + [i for i in shape_map if i < MAX_SHAPE_ID]) + 1
            if sid > MAX_SHAPE_ID:
                raise ValueError("no free shape id left")
            rec = Row(attack_table.schema, bytes(attack_table.schema.record_size))
            rec.set("id", sid)
            attack_table.rows.append(rec)
        else:
            sid = cur
        if rec is not None and own and len(area.cells) <= int(rec["cell_num"]):
            first = int(rec["first_cell"])                   # the skill's own shape: rewritten in place
        else:
            first = len(cells_t.rows)                        # new cells at the end (old ones stay, unused)
            for _ in area.cells:
                cells_t.rows.append(Row(cells_t.schema, bytes(cells_t.schema.record_size)))
        for i, (x, y, k) in enumerate(area.cells):
            c = cells_t.rows[first + i]
            c.set("x", int(x))
            c.set("y", int(y))
            c.set("kind", int(k))
        rec.set("first_cell", first)
        rec.set("cell_num", len(area.cells))
        rec.set("directional", 1 if is_directional(area.cells) else 0)
    row.set("attack_map", int(sid))
    row.set("range", max(0, min(MAP_WIDE, int(area.range))))
    row.set("height_up", max(0, min(255, int(area.height_up))))
    row.set("height_down", max(0, min(255, int(area.height_down))))
    if "area_flag" in row:
        row.set("area_flag", 1 if len(area.hit_cells()) > 1 else int(row["area_flag"] or 0))
    _drop_unused(magic_table, attack_table, base_rows, base_cells)
    return int(sid)


def clear_area(magic_table, skill):
    """a spell back to the game's rule: no shape, no reach of its own (they come from its level again)"""
    row = next((r for r in magic_table.rows if int(r["id"]) == int(skill)), None)
    if row is None:
        raise KeyError(f"no skill {skill} in magic.dat")
    row.set("attack_map", 0)
    row.set("range", 0)
    if "area_flag" in row:
        row.set("area_flag", 0)


def store_shape(attack_table, sid, cells):
    """rewrite one shape of AttackMap.dat (the spell shapes 1-9, shared by every spell): in place when the new cells
    fit the old count, else as new cells at the end (the old ones stay, unused)"""
    if not cells:
        raise ValueError("the area needs at least one panel")
    if len(cells) > MAX_CELLS:
        raise ValueError(f"an area has at most {MAX_CELLS} panels")
    rec = next((r for r in attack_table.rows if int(r["id"]) == int(sid)), None)
    if rec is None:
        raise KeyError(f"no shape {sid}")
    cells_t = attack_table.sections["cells"]
    from .database import Row
    if len(cells) <= int(rec["cell_num"]):
        first = int(rec["first_cell"])
    else:
        first = len(cells_t.rows)
        for _ in cells:
            cells_t.rows.append(Row(cells_t.schema, bytes(cells_t.schema.record_size)))
    for i, (x, y, k) in enumerate(cells):
        c = cells_t.rows[first + i]
        c.set("x", int(x))
        c.set("y", int(y))
        c.set("kind", int(k))
    rec.set("first_cell", first)
    rec.set("cell_num", len(cells))
    rec.set("directional", 1 if is_directional(cells) else 0)
    return int(sid)


def _check_cells(cells):
    if not cells:
        raise ValueError("a shape needs at least one panel")
    if len(cells) > MAX_CELLS:
        raise ValueError(f"a shape has at most {MAX_CELLS} panels")
    for x, y, k in cells:
        if not (-128 <= x <= 127 and -128 <= y <= 127) or k not in KIND_NAMES:
            raise ValueError(f"bad panel {(x, y, k)}")


def free_shape_id(attack_table, start=NEW_SHAPE_BASE):
    have = {int(r["id"]) for r in attack_table.rows}
    sid = max(int(start), NEW_SHAPE_BASE)
    while sid in have:
        sid += 1
    if sid > MAX_SHAPE_ID:
        raise ValueError("no free shape id left")
    return sid


def new_shape(attack_table, cells, sid=None):
    """a new shape (its cells appended) -> its id (NEW_SHAPE_BASE + ... unless given)"""
    from .database import Row
    _check_cells(cells)
    sid = free_shape_id(attack_table) if sid is None else int(sid)
    if any(int(r["id"]) == sid for r in attack_table.rows):
        raise ValueError(f"shape {sid} exists already")
    if not 0 < sid <= MAX_SHAPE_ID:
        raise ValueError(f"a shape id is 1..{MAX_SHAPE_ID}")
    rec = Row(attack_table.schema, bytes(attack_table.schema.record_size))
    rec.set("id", sid)
    rec.set("first_cell", 0)
    rec.set("cell_num", 0)
    attack_table.rows.append(rec)
    store_shape(attack_table, sid, cells)
    return sid


def delete_shape(attack_table, sid):
    """take a shape out (its cells stay unless they are the last ones of the file)"""
    rec = next((r for r in attack_table.rows if int(r["id"]) == int(sid)), None)
    if rec is None:
        raise KeyError(f"no shape {sid}")
    attack_table.rows.remove(rec)
    cells_t = attack_table.sections["cells"]
    keep = max([0] + [int(r["first_cell"]) + int(r["cell_num"]) for r in attack_table.rows])
    if keep < len(cells_t.rows):
        del cells_t.rows[keep:]


def _drop_unused(magic_table, attack_table, base_rows, base_cells):
    """kit-made shapes no skill uses any more, at the end of the file (only ones this mod added: past base_rows),
    and their cells at the end of the cells"""
    cells_t = attack_table.sections["cells"]
    used = {int(r["attack_map"] or 0) for r in magic_table.rows}
    while len(attack_table.rows) > max(int(base_rows or 0), 1):
        rec = attack_table.rows[-1]
        if int(rec["id"]) < NEW_SHAPE_BASE or int(rec["id"]) in used:
            break
        attack_table.rows.pop()
    keep = max([int(base_cells or 0)] + [int(r["first_cell"]) + int(r["cell_num"]) for r in attack_table.rows])
    del cells_t.rows[keep:]


def load_tables(read, mods=()):
    """(magic.dat, AttackMap.dat) as the game gets them with these mods' row patches (tools; the GUI uses its
    database service)"""
    from . import database, dbpatch
    out = []
    for name in ("magic.dat", "AttackMap.dat"):
        t = database.load_table(name, read(f"{dbpatch.DB_ARCHIVE}/{name}"))
        for m in mods:
            p = m.load_patch("db", name + ".json")
            if p:
                dbpatch.apply_patch(t, p)
        out.append(t)
    return out


def area_for(magic_table, attack_table, skill):
    row = next((r for r in magic_table.rows if int(r["id"]) == int(skill)), None)
    return area_of(row, shapes(attack_table)) if row is not None else default_area(skill)


def target_vars(n):
    """script variables of n area targets: $60400 + i = 1 for the ones that exist"""
    from .choreo import MAX_TARGETS
    return {60400 + i: 1 if i < n else 0 for i in range(MAX_TARGETS)}
