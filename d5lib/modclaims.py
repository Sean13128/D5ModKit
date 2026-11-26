"""Claims from every installed mod folder, plus the vanilla table (offline, read-only).

The allocation manifest (`d5lib/ownership.py`) says which *band* may belong to whom; this module reads
what the mod folders on disk actually use, so a build can be checked against the whole installed set and
not only against its own pack.  The 491-495 collision (DRPG_Outfits_Majorita's outfit rows vs the two
DRPG samples' outfit rows) happened because a gate only ever looked at one pack at a time.

A mod claims a database id two ways, both in `patches/db/<member>.json`:

  "added": [{..., "id": 491}, ...]   a row appended with that id        -> claims the id
  "rows":  {"48": {...}}             an edit of row index 48 (0-based)  -> claims that row's id

`rows` is keyed by *index*, not id, so an edit is mapped through the vanilla table when one is supplied
(otherwise it is only reported as a patch conflict between two mods, which needs no id).

Nothing here launches the game or writes anywhere: `scan_mods` opens files for reading only.
"""
import json
import os

# Members a mod patches by row id, and the manifest namespace each one allocates from (see
# d5lib/ownership.py).  charPersonal/charhelp/JobRank/Quest have no manifest namespace, but two mods
# appending the same id there is still a real duplicate, so they are scanned for duplicates regardless.
NAMESPACES = {
    "char.dat": "char_dat_row",
    "Skill.dat": "evility_id",
    "magic.dat": "special_id",
    "charPersonal.dat": "personality_id",
}

# The game's own empty rows: an added row with a dummy row's id *fills* that row (dbpatch._reserved_row)
# instead of appending a second row with the same id, so it is not a collision.
DUMMY_NAMES = {"Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy"}

# Members whose rows the game reads by *position*, not by id: the identity column repeats in vanilla
# (charPersonal 129-131; the charhelp id is the row's own index) and a pack may append the same id more
# than once on purpose -- Overlord's charPersonal member, converted faithfully by OLCOMPAT2, is
# `3, 4, 5, 3, 4, 5`.  An id is not a key here, so an id the same pack repeats, or one the vanilla table
# also has, is reported as information; a *second pack* claiming the same id stays an error, because two
# packs extending the same positions cannot be reasoned about.  The real guard for these members is
# `d5lib.ordercheck.positional_errors` (a change that moves a saved position).
POSITIONAL_MEMBERS = {"charPersonal.dat", "charhelp.dat", "SugorokuMapSetting.dat"}

ERROR, WARNING, INFO = "error", "warning", "info"


class Scan:
    """What every mod folder under one directory claims."""

    def __init__(self):
        self.mods = []                                  # folder names, sorted
        self.added = {}                                 # member -> {id: [mod, ...]}
        self.patched = {}                               # member -> {row index: [mod, ...]}
        self.payloads = {}                              # (member, id) -> {mod: canonical row json}
        self.patch_payloads = {}                        # (member, index) -> {mod: canonical row json}
        self.empty_tables = []                          # members a mod patches but with no rows at all
        self.missing = []                               # names asked for in `only` with no folder on disk

    # ---- views -------------------------------------------------------------------------------------
    def tables(self):
        return sorted(set(self.added) | set(self.patched))

    def ids(self, member):
        return sorted(self.added.get(member, {}))

    def holders(self, member, rid):
        return list(self.added.get(member, {}).get(int(rid), ()))

    def as_dict(self):
        return {"mods": self.mods,
                "tables": {m: {"added": len(self.added.get(m, {})), "patched": len(self.patched.get(m, {}))}
                           for m in self.tables()}}


class Finding:
    __slots__ = ("severity", "kind", "table", "rid", "holders", "detail")

    def __init__(self, severity, kind, table, rid, holders, detail):
        self.severity, self.kind = severity, kind
        self.table, self.rid = table, rid
        self.holders, self.detail = list(holders), detail

    @property
    def span(self):
        return f"{self.table}[{self.rid}]" if self.rid is not None else self.table

    def as_dict(self):
        return dict(severity=self.severity, kind=self.kind, table=self.table, id=self.rid,
                    holders=self.holders, detail=self.detail)

    def __str__(self):
        return f"{self.severity.upper():7s} {self.kind:16s} {self.span}: {self.detail}"

    def __repr__(self):
        return f"Finding({self.as_dict()!r})"


def errors(findings):
    return [f for f in findings if f.severity == ERROR]


# ------------------------------------------------------------------------------------------------ scan
def _mod_folders(root, only=None):
    """Every mod folder under `root` (optionally only the names in `only`, e.g. an enabled profile)."""
    keep = None if only is None else {str(n) for n in only}
    return sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
                  and (keep is None or d in keep))


def _rows(patch):
    """('added', [(id, row)]) + ('rows', [(index, row)]) from one patches/db file, or ([], [])."""
    added, rows = [], []
    table = patch.get("table") or ""
    for row in patch.get("added") or ():
        if "id" not in row:
            continue                                  # a member with no id field claims nothing by id
        added.append((int(row["id"]), row))
    for index, row in (patch.get("rows") or {}).items():
        try:
            rows.append((int(index), row))
        except (TypeError, ValueError):
            continue
    for _section, sub in (patch.get("sections") or {}).items():
        a, r = _rows(sub or {})
        added += a
        rows += r
    return added, rows


def scan_mods(root, only=None):
    """Every `*/patches/db/<member>.json` under `root`, read-only.  Raises OSError if root is absent.

    `only` restricts the scan to those mod folder names (a profile's enabled set); a name that is not
    present under `root` is reported by `missing` rather than silently ignored.
    """
    scan = Scan()
    scan.mods = _mod_folders(root, only)
    if only is not None:
        present = set(_mod_folders(root))
        scan.missing = sorted(str(n) for n in only if str(n) not in present)
    for mod in scan.mods:
        dbdir = os.path.join(root, mod, "patches", "db")
        if not os.path.isdir(dbdir):
            continue
        for name in sorted(os.listdir(dbdir)):
            if not name.lower().endswith(".json"):
                continue
            member = name[:-5]
            try:
                with open(os.path.join(dbdir, name), "r", encoding="utf-8-sig") as fh:
                    patch = json.load(fh)
            except (OSError, ValueError) as exc:
                raise ValueError(f"{mod}/patches/db/{name}: {exc}") from exc
            if not isinstance(patch, dict):
                raise ValueError(f"{mod}/patches/db/{name}: not an object")
            added, rows = _rows(patch)
            for rid, row in added:
                scan.added.setdefault(member, {}).setdefault(rid, []).append(mod)
                scan.payloads.setdefault((member, rid), {})[mod] = _canonical(row)
            for index, row in rows:
                scan.patched.setdefault(member, {}).setdefault(index, []).append(mod)
                scan.patch_payloads.setdefault((member, index), {})[mod] = _canonical(row)
            if not added and not rows:
                scan.empty_tables.append((mod, member))
    return scan


def _canonical(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------------------------- vanilla
def vanilla_ids(table):
    """{id: name_EN} of a d5lib.database.Table (the vanilla member), for fillable-id checks."""
    out = {}
    for row in table.rows:
        try:
            out[int(row["id"])] = row.get("name_EN") or ""
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fillable_ids(names):
    """Ids whose vanilla row is one of the game's empty dummy rows (an added row fills it, not duplicates)."""
    return {rid for rid, name in names.items() if name in DUMMY_NAMES}


# --------------------------------------------------------------------------------------------- checks
def duplicate_findings(scan):
    """Two mod folders appending the same id in one member, or patching one row differently."""
    out = []
    for member in sorted(scan.added):
        for rid in sorted(scan.added[member]):
            holders = scan.added[member][rid]
            if len(holders) < 2:
                continue
            variants = len(set(scan.payloads.get((member, rid), {}).values()))
            same = "identical rows" if variants == 1 else f"{variants} different rows"
            if member in POSITIONAL_MEMBERS and len(set(holders)) == 1:
                out.append(Finding(INFO, "positional_repeat", member, rid, holders,
                                   f"{holders[0]} appends id {rid} {len(holders)} times; {member} "
                                   f"rows are read by position, so this is not a duplicate"))
                continue
            out.append(Finding(ERROR, "duplicate_id", member, rid, holders,
                               f"{len(holders)} mods append id {rid} ({same}): {', '.join(holders)}"))
    for member in sorted(scan.patched):
        for index in sorted(scan.patched[member]):
            holders = scan.patched[member][index]
            if len(holders) < 2:
                continue
            fields = _field_clashes(scan.patch_payloads.get((member, index), {}), member)
            if fields:
                out.append(Finding(ERROR, "patch_conflict", member, index, holders,
                                   f"{len(holders)} mods patch row index {index} and disagree on "
                                   f"{', '.join(fields[:6])}{' …' if len(fields) > 6 else ''}: "
                                   f"{', '.join(holders)}"))
            else:
                out.append(Finding(INFO, "patch_merge", member, index, holders,
                                   f"{len(holders)} mods patch row index {index} with different fields "
                                   f"(they compose): {', '.join(holders)}"))
    return out


def _field_clashes(payloads, member=None):
    """Fields that two mods set to different values (a patch that only touches other fields composes).

    Legacy field names (schema "aliases", e.g. `unk_0E0` for `exp_yield_weight`) count as their canonical name, so
    a pack built before a rename and one built after still clash on the same field.
    """
    alias = {}
    if member:
        from . import database
        try:
            alias = database.get_schema(member).alias
        except KeyError:
            pass
    values = {}
    for mod, blob in payloads.items():
        try:
            row = json.loads(blob)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        for field, value in row.items():
            values.setdefault(alias.get(field, field), {})[mod] = json.dumps(value, sort_keys=True)
    return sorted(f for f, per_mod in values.items() if len(set(per_mod.values())) > 1)



def vanilla_findings(scan, names, fillable=None):
    """A mod appending an id the vanilla table already has (unless it is one of the empty dummy rows).

    names    = {member: {id: name_EN}} of the vanilla tables
    fillable = {member: {ids}} of the game's empty rows (modclaims.fillable_ids per member)
    """
    fillable = fillable or {}
    out = []
    for member in sorted(scan.added):
        table_names = names.get(member)
        if not table_names:
            continue
        can_fill = set(fillable.get(member, ()))
        for rid in sorted(scan.added[member]):
            if rid not in table_names:
                continue
            holders = scan.added[member][rid]
            what = table_names[rid] or "a row"
            if rid in can_fill:
                out.append(Finding(INFO, "fills_vanilla_dummy", member, rid, holders,
                                   f"id {rid} is the game's empty '{what}' row and is filled, not duplicated"))
            elif member in POSITIONAL_MEMBERS:
                out.append(Finding(INFO, "positional_vanilla_id", member, rid, holders,
                                   f"id {rid} also exists in vanilla {member} as '{what}'; {member} rows "
                                   f"are read by position, so the ids do not collide: "
                                   f"{', '.join(sorted(set(holders)))}"))
            else:
                out.append(Finding(ERROR, "vanilla_collision", member, rid, holders,
                                   f"id {rid} already exists in vanilla {member} as '{what}': "
                                   f"{', '.join(holders)}"))
    return out


def findings(scan, names=None, fillable=None):
    """All duplicate/collision findings for a scan.

    names    = {member: {id: name_EN}} of the vanilla tables (optional; without it only duplicates
               between mod folders are reported)
    fillable = {member: {ids}} for the game's empty dummy rows (modclaims.fillable_ids)
    """
    out = list(duplicate_findings(scan))
    if names:
        out += vanilla_findings(scan, names, fillable)
    return out


def vanilla_names(database_path):
    """{member: {id: name}} for every table in a Database_0.dat, read-only (for vanilla_findings)."""
    from . import database
    db = database.load_database(database_path)
    out = {}
    for name in db.order:
        table = db.get(name)
        if table is None or not any(f.name == "id" for f in table.schema.fields):
            continue
        out[name] = vanilla_ids(table)
    return out


def vanilla_fillable(names):
    """{member: ids} of the game's empty dummy rows, from `vanilla_names`."""
    return {member: fillable_ids(rows) for member, rows in names.items()}


def claims(scan, holder_prefix="mod", namespaces=None):
    """The scan as ownership.Claim objects, one per (mod, member, id) -- for ownership.check_usage."""
    from . import ownership
    namespaces = NAMESPACES if namespaces is None else namespaces
    out = []
    for member in sorted(scan.added):
        namespace = namespaces.get(member)
        if namespace is None:
            continue
        for rid in sorted(scan.added[member]):
            for mod in scan.added[member][rid]:
                out.append(ownership.Claim(f"{holder_prefix}:{mod}", namespace, rid, rid,
                                           label=f"{member} row {rid}"))
    return out
