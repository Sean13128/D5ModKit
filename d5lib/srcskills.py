"""Source-game special attacks with their own numbers (SPECIALS2, 2026-11-10).

Readers for the skill tables of Disgaea 4 Complete+, Disgaea D2 and Disgaea 1 Complete, normalised to one
record, plus the mapping to a D5 magic.dat row:

    E  the same special exists in D5 (JP name, then EN name): the unit learns D5's own row.
    A  a new magic.dat row = a D5 stand-in (animation, engine flags) carrying the SOURCE's numbers:
       SP cost, element, range, area shape, heights, ailments, and power converted through the skills
       both games share (the series' own rebalance; labelled, never a guess).
    H  held: Magichange moves (DECISIONS 2026-10-29) and skills whose main effect has no D5 code.

Field meanings (D4, DD2) were established by concordance: every skill the source shares by name with D5
(D4 about 145 rows; DD2 spot-checked) carries the same range / AttackMap id / heights / element / formula bytes in both
tables, so the D4/DD2 byte and the D5 schema field are the same field.  The earlier lanes' statement that
"D4 stores no formula, element, power or target selector" was wrong: they read the 40-byte EXP block at
the head of the row.  D4 second-of-pair bytes (range, area, power table, SP table) are not carried: they
are larger variants (believed giant / fused state) with no D5 counterpart.

Prior art: d4source.D4Data, dd2source.Tables, d1skill (readers), skillmotions.Survey + choreo (caster
motions vs the unit's bank), newclasses/dbpatch row writers, UNIQUESKILLS1's mapping rules.
"""
from __future__ import annotations

import json
import statistics
import struct
import unicodedata
from pathlib import Path

BASE = Path("/Volumes/Data/Projects/D5")
D4_ROOT = BASE / "Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+"
D5_CLEAN = BASE / "Disgaea Source/Disgaea 5 Complete (Steam 803600)"
MAGICHANGE_GROUP = 10
ELEMENTS = {0: "none", 1: "fire", 2: "wind", 3: "ice", 4: "star"}


def norm(name):
    """Name key: case, spacing and punctuation variants of one name compare equal."""
    import unicodedata
    s = unicodedata.normalize("NFKC", name or "").lower()
    return "".join(c for c in s if c.isalnum())


# ------------------------------------------------------------------ D4
def _d4_sub(db, name):
    raw = db.read(name)
    n = struct.unpack_from("<I", raw)[0]
    return {r[0]: r[1:11] for r in (struct.unpack_from("<13I", raw, 4 + i * 52) for i in range(n))}


def attack_maps(raw, wide, big=False):
    """{shape id: frozenset((x, y, kind))}.  D5: 8-byte records (u32 id); D4 / DD2: 6-byte (u16 id; DD2 big-endian)."""
    e = ">" if big else "<"
    count, cells = struct.unpack_from(e + "HH", raw)
    size = 8 if wide else 6
    base = 4 + count * size
    out = {}
    for i in range(count):
        sid, first, num = struct.unpack_from(e + ("IHB" if wide else "HHB"), raw, 4 + i * size)
        if first + num > cells:
            continue
        out[sid] = frozenset(struct.unpack_from("<bbB", raw, base + (first + j) * 3) for j in range(num))
    return out


def d4_table(root=None):
    """{skill id: record} from D4's magic.dat + magicspendSP.dat (EN text, JP name for matching).

    SOURCEPREP4-D4: the tables come from the verified prepared source set (`_d4_source.data_dir()`); ``root`` is
    the explicit, unverified diagnostic route (a D4 install folder)."""
    from . import d4source
    from .importers import _d4_source
    files = _d4_source.data_dir(root)
    en = files.data("EN")
    jp_db = d4source.Nsac(files.path("Data/DATA/JP/DATABASE.dat"))
    sp = _d4_sub(en.db, "magicspendSP.dat")
    jp_names = {struct.unpack_from("<I", r, 40)[0]: r[184:248].split(b"\0", 1)[0]
                for r in d4source._rows(jp_db.read("magic.dat"), d4source.SKILL_STRIDE)}
    out = {}
    for r in d4source._rows(en.db.read("magic.dat"), d4source.SKILL_STRIDE):
        sid = struct.unpack_from("<I", r, 40)[0]
        h = struct.unpack_from("<6H", r, 44)
        t = r[312:]
        types = list(t[0:5])
        values = list(struct.unpack_from("<5b", t, 5))
        out[sid] = dict(
            game="d4", id=sid, name=r[184:248].split(b"\0", 1)[0].decode("utf-8", "replace").strip(),
            name_jp=jp_names.get(sid, b""), desc=r[56:184].split(b"\0", 1)[0].decode("utf-8", "replace"), sp=sp.get(h[2], (None,))[0], sp_table=h[2], power_table=h[0],
            mastery_level=h[4], effects=[(a, b) for a, b in zip(types, values) if a],
            power_raw=values[0] if types[0] == 1 else None, moves=t[11], weapon=t[13], element=t[14],
            formula=t[15], area_flag=t[17], range=t[19], range_flag=t[21],
            attack_map=struct.unpack_from("<H", t, 24)[0], up=t[28], down=t[29],
            group=struct.unpack_from("<H", t, 40)[0])
    return out, attack_maps(en.db.read("AttackMap.dat"), False), en


# ------------------------------------------------------------------ DD2
def dd2_table():
    """{skill id: record} from DD2's magic.dat (big-endian; the row is D5's layout without the level tables)."""
    from . import dd2source
    from .importers import _dd2_abilities
    tables, _path, _digest = _dd2_abilities.source_tables()
    out = {}
    for row in tables._table("magic.dat", dd2source.SKILL_STRIDE, dd2source.SKILL_COUNT):
        d = dd2source.decode_skill(row)
        sp, mastery, rank = struct.unpack_from(">3H", row, 4)
        t = row[0xFE:]
        types = list(t[0:6])
        values = list(struct.unpack_from(">5h", t, 6))
        out[d["id"]] = dict(
            game="dd2", id=d["id"], name=unicodedata.normalize("NFKC", d["name"]).strip(), name_jp=b"", desc=d["description"],
            sp=sp, mastery_level=mastery, rank=rank, effects=[(a, b) for a, b in zip(types, values) if a],
            power_raw=values[0] if types[0] == 1 else None, moves=t[17], weapon=t[18], element=t[19],
            formula=t[20], area_flag=t[22], range=t[23], range_flag=t[24],
            attack_map=struct.unpack_from(">H", t, 26)[0], up=t[28], down=t[29], group=None, dd2_group=t[37])
    return out, attack_maps(tables.member("AttackMap.dat"), False, big=True), tables


# ------------------------------------------------------------------ D1C
D1_PATTERNS = Path(__file__).resolve().parent / "importers/d1-attack-patterns.json"


def d1c_table():
    """{skill id: record} from D1 Complete's magic.dat.  D1 keeps no AttackMap id: the row's pattern byte picks one
    of 82 shapes the executable builds in code (D1SCRIPT1, tools/d1_attack_patterns.py), and its range byte is the
    cursor reach of the centred shapes.  attack_map is the key "d1:<pattern>" into the returned shape map; the
    caster-landing cells (kind 2) are left out, as D5's own Blade Rush does, because a stand-in animation does
    not move the caster.  Pattern 0 = a spell (area from the spell level): no shape, the stand-in's."""
    from .importers import _d1c_source as d1c_source        # the verified prepared SUBDATA.DAT (SOURCEPREP4-D1C)
    from . import d1skill
    table = d1skill.read_table(d1c_source.member(40), "d1hd")
    pats = json.loads(D1_PATTERNS.read_text())["patterns"]
    maps = {f"d1:{p}": frozenset(tuple(c) for c in cells if c[2] != 2) for p, cells in pats.items()}
    codes = {v: k for k, v in d1skill.ELEMENTS.items()}
    formula = {"physical": 2, "magic": 3, "heal": 4, "support": 5, "support-other": 6}
    weapon = {v: k for k, v in d1skill.WEAPON_TYPES.items()}
    out = {}
    for r in table["rows"]:
        key = f"d1:{int(r['pattern'])}"
        hits = maps.get(key)
        out[int(r["id"])] = dict(
            game="d1c", id=int(r["id"]), name=r["name"], name_jp=b"", desc="", sp=int(r["sp"]),
            mastery_level=int(r["level"]), power_raw=int(r["power"]), effects=[], d1_effect=list(r["effect"]), moves=0, weapon=weapon[r["weapon"]],
            element=codes[r["element"]], formula=formula[r["category"]],
            area_flag=None if not hits else int(len(hits) > 1), range=int(r["range"]) if hits else None,
            range_flag=None, attack_map=key if hits else None, up=int(r["up"]), down=int(r["down"]), group=None,
            d1_range=int(r["range"]), d1_pattern=int(r["pattern"]), d1_cells=pats.get(str(int(r["pattern"]))))
    return out, maps, d1c_source


# ------------------------------------------------------------------ D5 reference
class D5:
    def __init__(self, game=D5_CLEAN):
        from . import database, gamefs, skillmotions
        self.fs = gamefs.GameFS(str(game))
        self.table = database.load_table("magic.dat", self.fs.read("Database/Database_0.dat/magic.dat"))
        self.rows = {int(r["id"]): r for r in self.table.rows}
        self.maps = attack_maps(self.fs.read("Database/Database_0.dat/AttackMap.dat"), True)
        self.survey = skillmotions.Survey(game)
        self.by_en, self.by_jp = {}, {}
        for r in self.table.rows:                      # lowest id wins: the base row, not a DLC duplicate
            self.by_en.setdefault(norm(r["name_EN"]), int(r["id"]))
            self.by_jp.setdefault(norm(r["name_JP"]), int(r["id"]))

    def twin(self, src):
        """D5 id of the same special (JP name first, then EN), or None."""
        jp = src.get("name_jp") or b""
        for enc in ("utf-8", "shift_jis"):
            try:
                key = norm(jp.decode(enc))
            except UnicodeDecodeError:
                continue
            if key and key in self.by_jp:
                return self.by_jp[key], "JP name"
        key = norm(src["name"])
        if key and key in self.by_en:
            return self.by_en[key], "EN name"
        return None, None

    def has_root(self, sid):
        try:
            return self.survey.sc.root_of(sid) is not None
        except Exception:                               # noqa: BLE001
            return False

    def own_motions(self, sid):
        """Motions 400-409 a skill's script puts on any fixed actor (static scan of `cmd_6510 actor, motion, speed`
        over the wrapper and choreography events; the kit simulator's caster view misses actor 1000)."""
        cache = self.__dict__.setdefault("_own", {})
        if sid not in cache:
            from . import skills
            sc, out = self.survey.sc, set()
            root = sc.root_of(sid) if self.has_root(sid) else None
            for eid in ([skills.wrapper_id(sid)] + (sc.tree(root) if root else [])):
                if eid in sc.ev:
                    out |= _scan_6510(sc.ev[eid].code)
            cache[sid] = frozenset(out)
        return cache[sid]

    def pool(self):
        """Stand-in candidates: single-user attack rows with a choreography (no Magichange, combo, system)."""
        if not hasattr(self, "_pool"):
            self._pool = [r for r in self.table.rows
                          if int(r["skill_group"]) in (7, 8, 9) and not int(r["partner_count"])
                          and int(r["effect1_type"]) == 1 and int(r["formula"]) in (2, 3)
                          and int(r["power_lv10"]) > int(r["power_lv1"])      # a real attack (not Thief's Key)
                          and self.has_root(int(r["id"]))]
        return self._pool


# ------------------------------------------------------------------ conversions
class Concordance:
    """Source value -> D5 value through the skills both games ship under one name."""

    def __init__(self, src, d5, formulas=(2, 3)):
        self.power, self.effect, self.pairs = {}, {}, 0
        votes = {}
        for s in src.values():
            if s.get("group") == MAGICHANGE_GROUP:
                continue
            tid, _ = d5.twin(s)
            if tid is None:
                continue
            q = d5.rows[tid]
            d5_eff = [(int(q[f"effect{i}_type"]), int(q[f"effect{i}_value"])) for i in range(1, 7)
                      if int(q[f"effect{i}_type"])]
            if s["power_raw"] is not None and d5_eff and d5_eff[0][0] == 1 and s["formula"] in formulas \
                    and int(q["formula"]) == s["formula"]:
                self.power.setdefault((s["formula"], s["power_raw"]), []).append(d5_eff[0][1])
                self.pairs += 1
            if len(d5_eff) == len(s["effects"]):
                for (a, _), (b, _) in zip(s["effects"], d5_eff):
                    votes.setdefault(a, []).append(b)
        for a, bs in votes.items():
            best = max(set(bs), key=bs.count)
            if len(set(bs)) == 1 or (bs.count(best) >= 3 and bs.count(best) * 4 >= len(bs) * 3):   # unanimous, or 3+ at 75%
                self.effect[a] = best

    def relation(self, formula):
        """Spearman rank correlation between source value and D5 value over the shared skills (None under 4 points)."""
        pts = sorted((v, statistics.median(xs)) for (f, v), xs in self.power.items() if f == formula)
        if len(pts) < 4 or len({y for _, y in pts}) < 2:
            return None
        return statistics.correlation([p[0] for p in pts], [p[1] for p in pts], method="ranked")

    def fit(self, formula):
        """How well the conversion reproduces the shared skills: pairs, values, rank correlation, residuals."""
        pairs = [(v, y) for (f, v), ys in self.power.items() if f == formula for y in ys]
        if not pairs:
            return dict(pairs=0)
        res = sorted(abs(y - (self.convert_power(formula, v)[0] if self.convert_power(formula, v)[0] is not None else v))
                     for v, y in pairs)
        rho = self.relation(formula)
        return dict(pairs=len(pairs), source_values=len({v for v, _ in pairs}), rank_correlation=rho and round(rho, 2),
                    mean_abs_residual=round(statistics.mean(res), 1), median_abs_residual=statistics.median(res),
                    max_abs_residual=res[-1],
                    mean_abs_residual_if_copied=round(statistics.mean(abs(y - v) for v, y in pairs), 1))

    def convert_power(self, formula, raw):
        """(D5 effect1_value, basis text).  Median of the shared skills at that source value; between two
        measured values, linear interpolation; outside them, the nearest measured value (clamped)."""
        pts = sorted((v, statistics.median(xs), len(xs)) for (f, v), xs in self.power.items() if f == formula)
        if not pts:
            return None, "no shared skill of this formula"
        rho = self.relation(formula)
        if rho is None or rho < 0.6:                    # the shared skills show no usable relation: do not fit noise
            return None, (f"the {len(pts)} shared source values show no usable relation to D5's scale "
                          f"(rank correlation {rho if rho is None else round(rho, 2)})")
        blocks = [[y, n, 1] for _, y, n in pts]          # pool adjacent violators: least-squares monotone fit
        i = 0
        while i < len(blocks) - 1:
            if blocks[i][0] > blocks[i + 1][0]:
                a, b = blocks[i], blocks.pop(i + 1)
                blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / (a[1] + b[1]), a[1] + b[1], a[2] + b[2]]
                i = max(i - 1, 0)
            else:
                i += 1
        ys = [y for y, _, k in blocks for _ in range(k)]
        xs = [p[0] for p in pts]
        if raw <= xs[0]:
            return int(round(ys[0])), f"source {raw} <= lowest shared value {xs[0]}"
        if raw >= xs[-1]:
            return int(round(ys[-1])), f"source {raw} >= highest shared value {xs[-1]}"
        for i in range(1, len(xs)):
            if raw == xs[i]:
                return int(round(ys[i])), f"median of {pts[i][2]} shared skill(s) with source value {raw}"
            if raw < xs[i]:
                y = ys[i - 1] + (ys[i] - ys[i - 1]) * (raw - xs[i - 1]) / (xs[i] - xs[i - 1])
                return int(round(y)), f"between shared values {xs[i - 1]} and {xs[i]}"
        return None, "unreachable"


def shape_for(src, src_maps, d5):
    """(D5 attack_map id, label).  Same id + same cells = exact; same cells under another id = exact shape;
    DD2 ids are D5's own (the table is D5's direct predecessor) and are checked to exist."""
    am = src["attack_map"]
    if am is None:
        return None, "source stores no area"
    if am == 0:
        return 0, "exact"
    if src_maps is None:
        return (am, "same id (source shape table not compared)") if am in d5.maps else (None, f"shape {am} not in D5")
    cells = _plain(src_maps.get(am))
    if cells and _plain(d5.maps.get(am)) == cells:
        return am, "exact"
    order = sorted(d5.maps.items())
    if src["game"] == "d1c":                             # D5 keeps twins (8 = 8001): take one D5 uses at this reach kind
        reach = {}
        for r in d5.table.rows:
            reach.setdefault(int(r["attack_map"]), set()).add(bool(int(r["range"])))
        order.sort(key=lambda kv: bool(src["range"]) not in reach.get(kv[0], ()))
    for did, dc in order:                                # D5 marks a cursor shape's origin cell as kind 3; D4 does not
        if cells and _plain(dc) == cells and any(k == 3 for _, _, k in dc) == bool(src["range"]):
            return did, f"exact cells (D5 id {did} for source id {am})"
    return None, f"source shape {am} has no identical D5 shape"


def _plain(cells):
    return frozenset((x, y, 1 if k == 3 else k) for x, y, k in cells or ())


def pick_standin(src, body, mod, d5, d5_map, used, prefer=None, tier=0, own=None):
    """The D5 skill whose animation stands in: same targeting geometry first, then element, weight, body.
    Only skills whose caster motions the unit's bank can play (skillmotions 'ok'; 'fallback' if none)."""
    row = _first_row(mod)
    best, cands = None, []
    for q in d5.pool():
        qid = int(q["id"])
        if qid in used:
            continue
        status = d5.survey._status(Path(mod), row, qid)["status"]
        if status in ("missing", "unknown"):
            continue
        same_map = d5_map is not None and int(q["attack_map"]) == d5_map
        if int(q["moves_units"]) and not (same_map and src.get("moves")):
            continue
        if src["range"] is None:                       # D1: only the 13 ranged uniques store a range
            geom = 0 if not src.get("d1_range") else (0 if int(q["range"]) == src["d1_range"] else
                                                      1 if int(q["range"]) else 3)
        elif same_map and int(q["range"]) == src["range"]:
            geom = 0
        elif same_map or (bool(q["range"]) == bool(src["range"]) and d5_map is not None
                          and len(d5.maps.get(int(q["attack_map"]), ())) == len(d5.maps.get(d5_map, ()))):
            geom = 1
        elif bool(int(q["range"])) == bool(src["range"]):
            geom = 2
        else:
            geom = 3
        score = (0 if status == "ok" else 1,
                 4 * geom + 2 * (int(q["element"]) != src["element"]) + 2 * abs(min(int(q["rank"]), 3) - tier)
                 + 5 * ((int(q["skill_group"]) == 9) != (body == 1)) + (int(q["formula"]) != src["formula"])
                 - (3 if qid == prefer else 0),          # an earlier reviewed twin wins unless clearly worse
                 0 if qid == prefer else 1, abs(int(q["sp_cost"]) - (src["sp"] or 0)), qid)
        if best is None or score < best[0]:
            best = (score, qid, status, geom)
        if own is not None:
            cands.append((score, qid, status, geom, int(q["element"]) != src["element"],
                          abs(min(int(q["rank"]), 3) - tier), (int(q["skill_group"]) == 9) != (body == 1)))
    if best is None or own is None or not own["bank"]:
        return best
    # SPECIALS2c: the body's own attack tracks (motions 400-409 its bank holds) beat a generic animation,
    # when a D5 skill of matching reach / element / weight calls them; the D4 script's own motion numbers first.
    mine = next(c for c in cands if c[1] == best[1])
    pick = None
    for c in cands:
        calls = d5.own_motions(c[1])
        if not calls or not calls <= own["bank"] or c[3] > mine[3] or c[4] > mine[4] or c[5] > max(mine[5], 1) \
                or c[6] != mine[6] or c[2] != mine[2]:
            continue
        match = 0 if own["want"] and calls == own["want"] else 1 if calls & own["want"] else 2 if not own["want"] else 3
        if match == 3:
            continue
        if pick is None or (match, c[0]) < pick[0]:
            pick = ((match, c[0]), c)
    if pick is None:
        return best
    c = pick[1]
    return (c[0], c[1], c[2], c[3], dict(calls=sorted(d5.own_motions(c[1])), match=pick[0][0]))


def _first_row(mod):
    return (json.loads((Path(mod) / "patches/db/char.dat.json").read_text()).get("added") or [{}])[0]


def _scan_6510(code):
    return {int(i.args[1]) for i in code if i.cid == 0x6510 and len(i.args) >= 2
            and isinstance(i.args[0], int) and isinstance(i.args[1], int) and 400 <= i.args[1] <= 409}


def d4_script_motions(handle):
    """{D4 skill id: motions 400-409 its attack script names} from D4's script.dat (same format, same opcode
    0x6510 and the same 12000000 + id wrapper as D5; d4scripts.Source)."""
    from . import d4scripts, skills
    source = d4scripts.Source(handle.db.read("script.dat"))

    def of(sid):
        out, w = set(), skills.wrapper_id(sid)
        if w not in source.index:
            return None
        for eid in source.closure(w)["events"]:
            rec = source.event(eid)
            if not rec.get("error"):
                out |= _scan_6510(rec["event"].code)
        return frozenset(out)
    return of


def d4_script_ops(handle):
    """{D4 skill id: total opcodes in its attack-script closure} (None when the skill has no script wrapper).
    A closure of two opcodes is the empty wrapper: no animation, no damage step."""
    from . import d4scripts, skills
    source = d4scripts.Source(handle.db.read("script.dat"))

    def of(sid):
        w = skills.wrapper_id(sid)
        if w not in source.index:
            return None
        n = 0
        for eid in source.closure(w)["events"]:
            rec = source.event(eid)
            if not rec.get("error"):
                n += len(rec["event"].code)
        return n
    return of
