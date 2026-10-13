"""Disgaea 5 Complete (PC) database tables (members of Data/Database/Database_0.dat).

Every table is described by a JSON schema in ``d5lib/schemas/<table>.json`` (see
docs/DATABASE.md for the schema format).  Rows are backed by their raw record bytes,
so reading and writing an unmodified table is byte-identical, and fields that are
not (yet) understood are preserved untouched.

Quick use::

    from d5lib.database import load_database, load_table
    db = load_database(r"...\\Data\\Database\\Database_0.dat")
    char = db["char.dat"]
    row = char.rows[0]
    print(row["name_EN"], row["base_HP"])
    row["name_EN"] = "Killia2"
    char.add_row(copy_from=0)
    data = char.to_bytes()

Layouts
-------
* ``fixed``  : header (count + optional extra fields) followed by N fixed-size records.
* ``pool``   : fixed-size records whose ``strptr`` fields are u32 offsets (relative to
  ``pool.base``, normally 4 = start of records) into a string pool placed after the
  records.  Pool layout: for every string, in row order then field order:
  ``b"\\0" + utf8 + b"\\0"``; the pointer points at the first text byte.
  Fields with ``"role": "strlen"`` hold the *character* count of the string of the
  strptr field named in ``"of"`` and are recomputed on write.
* ``custom`` : ``name_lists`` (name.dat), ``attackmap`` (AttackMap.dat),
  ``matrix`` (comb.dat).  The custom reader converts the file into pseudo-records
  described by the schema, the writer converts back.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import struct
from typing import Dict, List, Optional

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")

_FMT = {
    "u8": "<B", "i8": "<b", "u16": "<H", "i16": "<h", "u32": "<I", "i32": "<i",
    "u64": "<Q", "i64": "<q", "f32": "<f", "f64": "<d", "strptr": "<I",
}
_SIZE = {k: struct.calcsize(v) for k, v in _FMT.items()}
LANGS = ("JP", "EN", "FR", "CHN", "KOR")


class StringTooLong(ValueError):
    pass


# --------------------------------------------------------------------------- schema
class Field:
    __slots__ = ("name", "offset", "type", "size", "lang", "ref", "desc", "confidence",
                 "role", "of", "enum", "extra")

    def __init__(self, d: dict):
        self.name = d["name"]
        self.offset = int(d["offset"])
        self.type = d["type"]
        if self.type in ("str", "bytes"):
            self.size = int(d["size"])
        else:
            self.size = _SIZE[self.type]
        self.lang = d.get("lang")
        self.ref = d.get("ref")
        self.desc = d.get("desc", "")
        self.confidence = d.get("confidence", "low")
        self.role = d.get("role")
        self.of = d.get("of")
        self.enum = d.get("enum")
        self.extra = {k: v for k, v in d.items() if k not in (
            "name", "offset", "type", "size", "lang", "ref", "desc", "confidence", "role", "of", "enum")}

    @property
    def end(self):
        return self.offset + self.size

    def to_dict(self):
        d = {"name": self.name, "offset": self.offset, "type": self.type}
        if self.type in ("str", "bytes"):
            d["size"] = self.size
        for k in ("lang", "ref", "role", "of", "enum"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.desc:
            d["desc"] = self.desc
        d["confidence"] = self.confidence
        d.update(self.extra)
        return d

    def __repr__(self):
        return f"<Field {self.name} @{self.offset:#x} {self.type}>"


class Schema:
    def __init__(self, d: dict, path: str = None):
        self.raw = d
        self.path = path
        self.file = d["file"]
        self.layout = d.get("layout", "fixed")
        self.custom = d.get("custom")
        h = d.get("header", {"size": 4, "fields": [{"name": "count", "offset": 0, "type": "u32", "role": "count"}]})
        self.header_size = int(h["size"])
        self.header_fields = [Field(_with_offsets(f)) for f in _auto_offsets(h.get("fields", []))]
        self.record_size = int(d["record_size"])
        self.fields = [Field(f) for f in _auto_offsets(d["fields"])]
        self.by_name = {f.name: f for f in self.fields}
        self.header_by_name = {f.name: f for f in self.header_fields}
        self.key = d.get("key")
        self.display = d.get("display")
        self.pool = d.get("pool", {"base": 4})
        self.sections = {k: Schema(dict(v, file=f"{self.file}#{k}"), None) for k, v in d.get("sections", {}).items()}
        self.desc = d.get("desc", "")
        self.title = d.get("title") or os.path.splitext(self.file.split("#")[0])[0]

    @property
    def strptr_fields(self):
        return [f for f in self.fields if f.type == "strptr"]

    def check_coverage(self) -> List[str]:
        """returns list of problems (gaps / overlaps / overflow)"""
        probs = []
        cov = [0] * self.record_size
        for f in self.fields:
            if f.end > self.record_size:
                probs.append(f"{f.name} overflows record")
                continue
            for i in range(f.offset, f.end):
                cov[i] += 1
        gaps = [i for i, v in enumerate(cov) if v == 0]
        over = [i for i, v in enumerate(cov) if v > 1]
        if gaps:
            probs.append(f"uncovered bytes: {_ranges(gaps)}")
        if over:
            probs.append(f"overlapping bytes: {_ranges(over)}")
        names = [f.name for f in self.fields]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            probs.append(f"duplicate names: {sorted(dup)}")
        return probs


def _ranges(idx):
    out = []
    s = p = idx[0]
    for i in idx[1:]:
        if i != p + 1:
            out.append(f"{s:#x}-{p:#x}")
            s = i
        p = i
    out.append(f"{s:#x}-{p:#x}")
    return ", ".join(out[:20]) + (" ..." if len(out) > 20 else "")


def _auto_offsets(fields):
    """allow schemas to omit offsets: consecutive packing"""
    out = []
    pos = 0
    for f in fields:
        f = dict(f)
        if "offset" not in f:
            f["offset"] = pos
        size = int(f["size"]) if f["type"] in ("str", "bytes") else _SIZE[f["type"]]
        pos = int(f["offset"]) + size
        out.append(f)
    return out


def _with_offsets(f):
    return f


_SCHEMAS: Optional[Dict[str, Schema]] = None


def _norm(name: str) -> str:
    return name.lower()


def schemas() -> Dict[str, Schema]:
    """all schemas keyed by lower-case archive member name"""
    global _SCHEMAS
    if _SCHEMAS is None:
        _SCHEMAS = {}
        for p in sorted(glob.glob(os.path.join(SCHEMA_DIR, "*.json"))):
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            s = Schema(d, p)
            _SCHEMAS[_norm(s.file)] = s
    return _SCHEMAS


def reload_schemas():
    global _SCHEMAS
    _SCHEMAS = None
    return schemas()


def get_schema(name: str) -> Schema:
    sc = schemas()
    n = _norm(name)
    if n in sc:
        return sc[n]
    # archive names are truncated to 31/32 chars; also accept full names / json stems
    for k, s in sc.items():
        if n.startswith(k) or k.startswith(n) or os.path.splitext(k)[0] == os.path.splitext(n)[0]:
            return s
    raise KeyError(f"no schema for table {name!r}")


def schema_filename(member_name: str) -> str:
    """json file stem for an archive member name (strips .dat or a truncated .d/.da)"""
    base = member_name
    for ext in (".dat", ".da", ".d", "."):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return base + ".json"


# --------------------------------------------------------------------------- rows
class Row:
    """A record. ``raw`` holds the fixed-size bytes; ``strs`` holds the text of
    ``strptr`` fields (pool tables)."""
    __slots__ = ("raw", "strs", "_schema", "_fields")

    def __init__(self, schema: Schema, raw: bytes, strs: Optional[dict] = None, fields=None):
        self._schema = schema
        self._fields = fields if fields is not None else schema.by_name
        self.raw = bytearray(raw)
        self.strs = strs if strs is not None else {}

    # --- access
    def field(self, name) -> Field:
        return self._fields[name]

    def get(self, name, default=None):
        f = self._fields.get(name)
        if f is None:
            return default
        return self._get(f)

    def __getitem__(self, name):
        return self._get(self._fields[name])

    def __setitem__(self, name, value):
        self.set(name, value)

    def __contains__(self, name):
        return name in self._fields

    def keys(self):
        return list(self._fields.keys())

    def _get(self, f: Field):
        t = f.type
        if t == "str":
            b = bytes(self.raw[f.offset:f.end])
            z = b.find(b"\0")
            if z >= 0:
                b = b[:z]
            return b.decode("utf-8", "replace")
        if t == "bytes":
            return bytes(self.raw[f.offset:f.end])
        if t == "strptr":
            return self.strs.get(f.name, "")
        return struct.unpack_from(_FMT[t], self.raw, f.offset)[0]

    def set(self, name, value, truncate=False):
        f = self._fields[name]
        t = f.type
        if t == "str":
            enc = encode_str(value, f.size, truncate=truncate, field=name)
            self.raw[f.offset:f.end] = enc
        elif t == "bytes":
            if isinstance(value, str):
                value = bytes.fromhex(value)
            value = bytes(value)
            if len(value) != f.size:
                raise ValueError(f"{name}: need {f.size} bytes, got {len(value)}")
            self.raw[f.offset:f.end] = value
        elif t == "strptr":
            self.strs[name] = str(value)
        else:
            if t == "f32" or t == "f64":
                value = float(value)
            else:
                value = int(value)
                lo, hi = _range(t)
                if not lo <= value <= hi:
                    raise ValueError(f"{name}: value {value} out of range for {t} [{lo},{hi}]")
            struct.pack_into(_FMT[t], self.raw, f.offset, value)

    def to_dict(self) -> dict:
        return {n: self._get(f) for n, f in self._fields.items()}

    def copy(self) -> "Row":
        return Row(self._schema, bytes(self.raw), dict(self.strs), self._fields)

    def __repr__(self):
        s = self._schema
        lab = None
        if s.display and s.display in self._fields:
            lab = self.get(s.display)
        return f"<Row {s.file} {lab!r}>"


def _range(t):
    bits = _SIZE[t] * 8
    if t.startswith("u") or t == "strptr":
        return 0, (1 << bits) - 1
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def encode_str(value: str, size: int, truncate=False, field="") -> bytes:
    """utf-8 encode into a fixed slot of ``size`` bytes (always NUL-terminated)."""
    b = (value or "").encode("utf-8")
    if len(b) > size - 1:
        if not truncate:
            raise StringTooLong(f"{field}: {len(b)} bytes > {size - 1} available")
        b = b[: size - 1]
        while b:
            try:
                b.decode("utf-8")
                break
            except UnicodeDecodeError:
                b = b[:-1]
    return b + b"\0" * (size - len(b))


# --------------------------------------------------------------------------- table
class Table:
    def __init__(self, name: str, schema: Schema):
        self.name = name
        self.schema = schema
        self.header: Optional[Row] = None
        self.rows: List[Row] = []
        self.sections: Dict[str, "Table"] = {}
        self.extra: dict = {}  # custom-layout leftovers (kept for round trip)

    # convenience
    @property
    def fields(self) -> List[Field]:
        return self.schema.fields

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, i) -> Row:
        return self.rows[i]

    def find(self, value, field: str = None) -> Optional[Row]:
        field = field or self.schema.key
        for r in self.rows:
            if r.get(field) == value:
                return r
        return None

    def index_of(self, value, field: str = None) -> int:
        field = field or self.schema.key
        for i, r in enumerate(self.rows):
            if r.get(field) == value:
                return i
        return -1

    def new_row(self) -> Row:
        return Row(self.schema, bytes(self.schema.record_size), {f.name: "" for f in self.schema.strptr_fields})

    def add_row(self, copy_from: Optional[int] = None, index: Optional[int] = None, **values) -> Row:
        """append (or insert at ``index``) a new row, optionally copied from row ``copy_from``;
        keyword args set fields."""
        row = self.rows[copy_from].copy() if copy_from is not None else self.new_row()
        for k, v in values.items():
            row[k] = v
        if index is None:
            self.rows.append(row)
        else:
            self.rows.insert(index, row)
        return row

    def delete_row(self, i: int) -> Row:
        return self.rows.pop(i)

    def to_bytes(self) -> bytes:
        return _WRITERS[self._layout_key()](self)

    def _layout_key(self):
        s = self.schema
        return s.custom if s.layout == "custom" else s.layout

    def to_records(self) -> List[dict]:
        return [r.to_dict() for r in self.rows]

    def __repr__(self):
        return f"<Table {self.name} rows={len(self.rows)}>"


def _read_header(schema: Schema, data: bytes) -> Row:
    return Row(schema, data[:schema.header_size], fields=schema.header_by_name)


def _update_count(table: Table, n: int):
    for f in table.schema.header_fields:
        if f.role == "count":
            table.header.set(f.name, n)


# ---- fixed
def _read_fixed(table: Table, data: bytes):
    s = table.schema
    table.header = _read_header(s, data)
    cnt = _count(table)
    rs = s.record_size
    exp = s.header_size + cnt * rs
    if len(data) < exp:
        raise ValueError(f"{table.name}: file too short ({len(data)} < {exp})")
    table.rows = [Row(s, data[s.header_size + i * rs: s.header_size + (i + 1) * rs]) for i in range(cnt)]
    table.extra["trailer"] = data[exp:]


def _count(table: Table) -> int:
    for f in table.schema.header_fields:
        if f.role == "count":
            return table.header.get(f.name)
    raise ValueError("schema has no count field")


def _write_fixed(table: Table) -> bytes:
    _update_count(table, len(table.rows))
    out = bytearray(table.header.raw)
    for r in table.rows:
        out += r.raw
    out += table.extra.get("trailer", b"")
    return bytes(out)


# ---- pool
def _read_pool(table: Table, data: bytes):
    s = table.schema
    table.header = _read_header(s, data)
    cnt = _count(table)
    rs = s.record_size
    base = s.pool.get("base", s.header_size)
    ptrs = s.strptr_fields
    rows = []
    for i in range(cnt):
        raw = data[s.header_size + i * rs: s.header_size + (i + 1) * rs]
        r = Row(s, raw)
        for f in ptrs:
            v = struct.unpack_from("<I", raw, f.offset)[0]
            if v == 0 and s.pool.get("zero_is_empty"):
                r.strs[f.name] = None
                continue
            p = base + v
            e = data.index(b"\0", p)
            r.strs[f.name] = data[p:e].decode("utf-8")
        rows.append(r)
    table.rows = rows


def _write_pool(table: Table) -> bytes:
    s = table.schema
    _update_count(table, len(table.rows))
    rs = s.record_size
    base = s.pool.get("base", s.header_size)
    ptrs = s.strptr_fields
    lens = [f for f in s.fields if f.role == "strlen"]
    pool_start = s.header_size + len(table.rows) * rs
    pool = bytearray()
    body = bytearray()
    for r in table.rows:
        raw = bytearray(r.raw)
        for f in ptrs:
            t = r.strs.get(f.name, "")
            if t is None:
                struct.pack_into("<I", raw, f.offset, 0)
                continue
            pos = pool_start + len(pool) + 1
            pool += b"\0" + t.encode("utf-8") + b"\0"
            struct.pack_into("<I", raw, f.offset, pos - base)
        for f in lens:
            t = r.strs.get(f.of, "") or ""
            struct.pack_into(_FMT[f.type], raw, f.offset, len(t))
        r.raw = raw
        body += raw
    return bytes(table.header.raw) + bytes(body) + bytes(pool)


# ---- custom: name.dat
def _read_name_lists(table: Table, data: bytes):
    """30 u32 list counts, then sum(counts) u32 offsets into a NUL-separated pool.
    Pseudo record: list u32, pool_order u32, text strptr."""
    s = table.schema
    nl = s.raw.get("lists", 30)
    counts = struct.unpack_from(f"<{nl}I", data, 0)
    total = sum(counts)
    offs = struct.unpack_from(f"<{total}I", data, nl * 4)
    P = nl * 4 + total * 4
    # pool order = rank of offset
    order = {o: k for k, o in enumerate(sorted(set(offs)))}
    table.header = Row(s, struct.pack("<I", total), fields=s.header_by_name)
    rows = []
    k = 0
    for li, c in enumerate(counts):
        for _ in range(c):
            o = offs[k]
            k += 1
            e = data.index(b"\0", P + o)
            r = Row(s, struct.pack("<III", li, order[o], 0))
            r.strs["text"] = data[P + o:e].decode("utf-8")
            rows.append(r)
    table.rows = rows
    table.extra["lists"] = nl
    table.extra["pool_tail"] = data[P + (max(offs) if offs else 0):]
    # sanity: pool is exactly strings in pool order separated by NUL
    table.extra["pool_len"] = len(data) - P


def _write_name_lists(table: Table) -> bytes:
    nl = table.extra.get("lists", 30)
    rows = sorted(enumerate(table.rows), key=lambda t: (t[1]["list"], t[0]))
    counts = [0] * nl
    for _, r in rows:
        counts[r["list"]] += 1
    # pool order
    porder = sorted(range(len(table.rows)), key=lambda i: (table.rows[i]["pool_order"], i))
    pool = bytearray()
    off = {}
    for i in porder:
        off[i] = len(pool)
        pool += table.rows[i].strs.get("text", "").encode("utf-8") + b"\0"
    out = bytearray(struct.pack(f"<{nl}I", *counts))
    for i, _ in rows:
        out += struct.pack("<I", off[i])
    table.header.set("count", len(table.rows))
    return bytes(out + pool)


# ---- custom: AttackMap.dat
def _read_attackmap(table: Table, data: bytes):
    s = table.schema
    table.header = _read_header(s, data)
    n = table.header["count"]
    m = table.header["cell_count"]
    rs = s.record_size
    table.rows = [Row(s, data[4 + i * rs: 4 + (i + 1) * rs]) for i in range(n)]
    cs = s.sections["cells"]
    cells = Table(table.name + "#cells", cs)
    cells.header = Row(cs, b"", fields={})
    p = 4 + n * rs
    cells.rows = [Row(cs, data[p + i * cs.record_size: p + (i + 1) * cs.record_size]) for i in range(m)]
    table.sections["cells"] = cells
    table.extra["trailer"] = data[p + m * cs.record_size:]


def _write_attackmap(table: Table) -> bytes:
    cells = table.sections["cells"]
    table.header.set("count", len(table.rows))
    table.header.set("cell_count", len(cells.rows))
    out = bytearray(table.header.raw)
    for r in table.rows:
        out += r.raw
    for r in cells.rows:
        out += r.raw
    out += table.extra.get("trailer", b"")
    return bytes(out)


# ---- custom: comb.dat (square matrix + id vector)
def _read_matrix(table: Table, data: bytes):
    s = table.schema
    dim = s.raw.get("dim", 256)
    table.header = _read_header(s, data)
    ids = struct.unpack_from(f"<{dim}H", data, 4)
    M = 4 + dim * 2
    rows = []
    for i in range(dim):
        rows.append(Row(s, struct.pack("<H", ids[i]) + data[M + i * dim: M + (i + 1) * dim]))
    table.rows = rows
    table.extra["dim"] = dim


def _write_matrix(table: Table) -> bytes:
    dim = table.extra.get("dim", 256)
    if len(table.rows) != dim:
        raise ValueError(f"comb.dat must keep exactly {dim} rows (fixed matrix)")
    out = bytearray(table.header.raw)
    for r in table.rows:
        out += r.raw[:2]
    for r in table.rows:
        out += r.raw[2:]
    return bytes(out)


_READERS = {"fixed": _read_fixed, "pool": _read_pool, "name_lists": _read_name_lists,
            "attackmap": _read_attackmap, "matrix": _read_matrix}
_WRITERS = {"fixed": _write_fixed, "pool": _write_pool, "name_lists": _write_name_lists,
            "attackmap": _write_attackmap, "matrix": _write_matrix}


def load_table(name: str, data: bytes, schema: Optional[Schema] = None) -> Table:
    """parse one database member file"""
    schema = schema or get_schema(name)
    t = Table(name, schema)
    key = schema.custom if schema.layout == "custom" else schema.layout
    _READERS[key](t, data)
    return t


# --------------------------------------------------------------------------- database
class Database(dict):
    """ordered mapping member name -> Table (plus ``stamps``/``order`` for repacking)"""

    def __init__(self):
        super().__init__()
        self.order: List[str] = []
        self.stamps: Dict[str, int] = {}
        self.unk = 0
        self.errors: Dict[str, str] = {}
        self.raw: Dict[str, bytes] = {}

    def table(self, name) -> Table:
        if name in self:
            return self[name]
        n = name.lower()
        for k in self:
            if k.lower() == n or k.lower().startswith(os.path.splitext(n)[0]) and n.startswith(os.path.splitext(k.lower())[0]):
                return self[k]
        raise KeyError(name)

    def member_bytes(self, name) -> bytes:
        return self[name].to_bytes() if name in self else self.raw[name]

    def save(self, path: str):
        """write a complete Database_0.dat (obfuscated NISPACK).  Never point this at the
        game's Data folder without a backup."""
        from .nispack import write_nispack
        files = [(n, self.member_bytes(n), self.stamps.get(n, 0)) for n in self.order]
        write_nispack(path, files, self.unk)


def load_database(path: str, strict: bool = False) -> Database:
    """load every member of Database_0.dat that has a schema"""
    from .nispack import NisPack
    db = Database()
    with NisPack(path) as pk:
        db.unk = pk.unk
        for e in pk.entries:
            data = pk.read(e)
            db.order.append(e.name)
            db.stamps[e.name] = e.stamp
            db.raw[e.name] = data
            try:
                db[e.name] = load_table(e.name, data)
            except Exception as ex:  # keep raw bytes, report
                if strict:
                    raise
                db.errors[e.name] = f"{type(ex).__name__}: {ex}"
    return db


def load_database_dir(path: str) -> Database:
    """load tables from a directory of extracted member files"""
    db = Database()
    for p in sorted(os.listdir(path)):
        fp = os.path.join(path, p)
        with open(fp, "rb") as fh:
            data = fh.read()
        db.order.append(p)
        db.raw[p] = data
        try:
            db[p] = load_table(p, data)
        except Exception as ex:
            db.errors[p] = f"{type(ex).__name__}: {ex}"
    return db


# --------------------------------------------------------------------------- csv
def _csv_value(f: Field, v):
    if f.type == "bytes":
        return v.hex(" ")
    return v


def table_to_csv(table: Table, path: str, include_index=True):
    fields = table.schema.fields
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow((["#"] if include_index else []) + [f.name for f in fields])
        for i, r in enumerate(table.rows):
            w.writerow(([i] if include_index else []) + [_csv_value(f, r._get(f)) for f in fields])
    for k, sub in table.sections.items():
        root, ext = os.path.splitext(path)
        table_to_csv(sub, f"{root}__{k}{ext}", include_index)


def table_from_csv(table: Table, path: str, truncate=False):
    """replace the rows of ``table`` with the rows of a CSV written by table_to_csv.
    Rows are rebuilt from the existing row with the same index (or a zero row), so
    columns missing from the CSV keep their old values."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rd = csv.reader(fh)
        head = next(rd)
        data = list(rd)
    has_idx = head and head[0] == "#"
    cols = head[1:] if has_idx else head
    new_rows = []
    for k, line in enumerate(data):
        vals = line[1:] if has_idx else line
        src = None
        if has_idx and line[0] != "":
            try:
                j = int(line[0])
                if 0 <= j < len(table.rows):
                    src = table.rows[j]
            except ValueError:
                pass
        row = src.copy() if src is not None else table.new_row()
        for name, v in zip(cols, vals):
            f = table.schema.by_name.get(name)
            if f is None:
                continue
            if f.type == "bytes":
                v = bytes.fromhex(v)
            elif f.type in ("str", "strptr"):
                pass
            elif f.type in ("f32", "f64"):
                v = float(v)
            else:
                v = int(v, 0) if isinstance(v, str) and v.strip().lower().startswith(("0x", "-0x")) else int(v)
            if f.type == "str":
                row.set(name, v, truncate=truncate)
            else:
                row.set(name, v)
        new_rows.append(row)
    table.rows = new_rows


def database_to_csv(db: Database, outdir: str):
    os.makedirs(outdir, exist_ok=True)
    for name, t in db.items():
        table_to_csv(t, os.path.join(outdir, os.path.splitext(schema_filename(name))[0] + ".csv"))


# --------------------------------------------------------------------------- refs
def parse_ref(ref: str):
    """'magic.dat' -> ('magic.dat', None, False); 'x.dat#index' -> ('x.dat', None, True);
    'x.dat:field' -> ('x.dat', 'field', False).  External refs ('anm', 'map', ...) -> (ref, None, False)."""
    if not ref:
        return None, None, False
    if ref.endswith("#index"):
        return ref[:-6], None, True
    if ":" in ref:
        t, f = ref.split(":", 1)
        return t, f, False
    return ref, None, False


def resolve_ref(db: Database, field: Field, value):
    """row referenced by a field value (target key / field / index), or None"""
    target, tfield, by_index = parse_ref(field.ref)
    if not target:
        return None
    try:
        t = db.table(target)
    except KeyError:
        return None
    if by_index or (tfield is None and not t.schema.key):
        return t.rows[value] if isinstance(value, int) and 0 <= value < len(t.rows) else None
    return t.find(value, tfield)


def ref_choices(db: Database, target: str):
    """[(value, label)] for dropdowns.  ``target`` may be a plain member name or a full ref string."""
    name, tfield, by_index = parse_ref(target)
    t = db.table(name)
    k = None if by_index else (tfield or t.schema.key)
    d = t.schema.display
    out = []
    for i, r in enumerate(t.rows):
        kv = r.get(k) if k else i
        out.append((kv, r.get(d) if d else str(kv)))
    return out
