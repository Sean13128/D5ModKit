"""Database access for editors: vanilla tables + the active mod's row patches."""
from PyQt6.QtCore import QObject, pyqtSignal

from d5lib import database, dbpatch

DB = dbpatch.DB_ARCHIVE


class DBService(QObject):
    table_changed = pyqtSignal(str)  # member name

    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        self._vanilla = {}
        self._base = {}
        self._work = {}
        self._dirty = set()
        ws.active_mod_changed.connect(lambda _: self.reload())
        ws.mods_changed.connect(lambda: self.reload(keep_unsaved=True))

    def reload(self, keep_unsaved=False):
        """Forget the loaded tables (they are rebuilt from the mods on the next use)."""
        keep = self._dirty if keep_unsaved else set()
        self._work = {m: t for m, t in self._work.items() if m in keep}
        self._base = {m: t for m, t in self._base.items() if m in keep}
        self._dirty = set(keep)

    # ------------------------------------------------------------------
    def members(self):
        return self.ws.fs.list_members(DB)

    def has_schema(self, member):
        try:
            database.get_schema(member)
            return True
        except Exception:
            return False

    def vanilla(self, member) -> database.Table:
        t = self._vanilla.get(member)
        if t is None:
            t = database.load_table(member, self.ws.fs.read(f"{DB}/{member}"))
            self._vanilla[member] = t
        return t

    def _layered(self, member, with_active):
        """the table as the game will get it: original (or a mod's full-file copy) + every enabled mod's row
        patch in load order, the active mod last"""
        t = database.load_table(member, self.ws.read(f"{DB}/{member}"))
        active = self.ws.active_mod
        for mod in self.ws.mods.enabled_mods():
            if active and mod.id == active.id:
                continue
            patch = mod.load_patch("db", member + ".json")
            if patch:
                dbpatch.apply_patch(t, patch)
        if with_active and active:
            patch = active.load_patch("db", member + ".json")
            if patch:
                for w in dbpatch.apply_patch(t, patch):
                    self.ws.log("warning: " + w)
        return t

    def base(self, member) -> database.Table:
        """What the active mod's patch is applied on (= saved as differences against)."""
        t = self._base.get(member)
        if t is None:
            t = self._base[member] = self._layered(member, False)
        return t

    def table(self, member) -> database.Table:
        """Working (editable) table: every enabled mod's changes, the active mod's on top."""
        t = self._work.get(member)
        if t is None:
            t = self._work[member] = self._layered(member, True)
        return t

    def find_table(self, name):
        """Case/extension-insensitive lookup of a member name (for field refs)."""
        n = name.lower().split(":")[0]
        for m in self.members():
            ml = m.lower()
            if ml == n or ml.split(".")[0] == n.split(".")[0] or (len(ml) == 32 and n.startswith(ml)):
                return m
        return None

    def mark_dirty(self, member):
        self._dirty.add(member)
        self._tipcache = {}

    def is_dirty(self, member):
        return member in self._dirty

    def dirty_members(self):
        return sorted(self._dirty)

    def commit_all(self, parent=None):
        return all(self.commit(m, parent) is not False for m in list(self._dirty))

    def commit(self, member, parent=None):
        """Save working-table differences into the active mod as a patch."""
        mod = self.ws.require_mod(parent)
        if not mod:
            return False
        old = mod.load_patch("db", member + ".json") or {}
        patch = dbpatch.diff_table(self.base(member), self.table(member))
        # rows only another mod changed are not repeated here; fields the active mod set before and that equal the
        # other mods' value now are kept (so the mod still works when the other mod is switched off)
        for idx, fields in (old.get("rows") or {}).items():
            row = patch.setdefault("rows", {}).setdefault(idx, {})
            t = self.table(member)
            if int(idx) < len(t.rows):
                for name in fields:
                    if name not in row and name in t.rows[int(idx)]:
                        v = t.rows[int(idx)][name]
                        row[name] = v.hex() if isinstance(v, (bytes, bytearray)) else v
            if not row:
                patch["rows"].pop(idx)
        if "rows" in patch and not patch["rows"]:
            patch.pop("rows")
        mod.save_patch("db", member + ".json", None if dbpatch.is_empty(patch) else patch)
        self._base.pop(member, None)
        self._dirty.discard(member)
        self.ws.file_changed.emit(f"{DB}/{member}")
        self.table_changed.emit(member)
        return True

    def discard(self, member):
        self._work.pop(member, None)
        self._dirty.discard(member)
        self.table_changed.emit(member)

    def revert_all(self, member):
        mod = self.ws.active_mod
        if mod:
            mod.save_patch("db", member + ".json", None)
        self.discard(member)
        self.ws.file_changed.emit(f"{DB}/{member}")

    # ------------------------------------------------------------------ refs
    def ref_choices(self, ref):
        m = self.find_table(ref)
        if not m or not self.has_schema(m):
            return []
        t = self.table(m)
        k, d = t.schema.key, t.schema.display
        out = []
        for i, r in enumerate(t.rows):
            kv = r.get(k) if k else i
            lab = r.get(d) if d else ""
            out.append((kv, lab))
        return out

    def ref_label(self, ref, value):
        m = self.find_table(ref)
        if not m or not self.has_schema(m):
            return None
        cache = getattr(self, "_labcache", {})
        self._labcache = cache
        key = (m, id(self.table(m)))
        lab = cache.get(key)
        if lab is None:
            lab = {kv: l for kv, l in self.ref_choices(ref)}
            cache[key] = lab
        return lab.get(value)

    # ------------------------------------------------------------------ hover descriptions
    def ref_tooltips(self, ref):
        """{key: rich-text tooltip} of a table (skills, evilities, items, characters ...): name, the
        game's own description and the most useful numbers. Follows the active mod's edits."""
        m = self.find_table(ref)
        if not m or not self.has_schema(m):
            return {}
        cache = getattr(self, "_tipcache", {})
        self._tipcache = cache
        t = self.table(m)
        key = (m, id(t))
        tips = cache.get(key)
        if tips is None:
            tips = {}
            extra = self._char_help() if m == "char.dat" else None
            k = t.schema.key
            for i, r in enumerate(t.rows):
                kv = r.get(k) if k else i
                if kv not in tips:
                    tip = describe_row(m, t.schema, r, extra)
                    if tip:
                        tips[kv] = tip
            cache[key] = tips
        return tips

    def ref_tooltip(self, ref, value):
        return self.ref_tooltips(ref).get(value)

    def _char_help(self):
        """{help id: description} from charhelp.dat."""
        try:
            t = self.table("charhelp.dat")
        except Exception:
            return {}
        out = {}
        for r in t.rows:
            lines = [r.get(f"line{n}_EN") or "" for n in (1, 2, 3)]
            text = " ".join(x.strip() for x in lines if x and x.strip())
            if text:
                out[r.get("id")] = text
        return out


# ---------------------------------------------------------------------- descriptions
_ITEM_STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD", "MOV", "JMP", "RNG", "CRT")


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fill_values(text, row):
    """Evility texts carry printf placeholders (%d) filled from value1, value2 ..."""
    text = text.replace("％", "%")
    vals = [row.get(f"value{n}") for n in range(1, 5)]
    vals = [v for v in vals if v is not None]
    out, k, i = [], 0, 0
    while i < len(text):
        if text[i] == "%" and i + 1 < len(text) and text[i + 1] in "du":
            out.append(str(vals[k]) if k < len(vals) else "?")
            k += 1
            i += 2
        elif text[i] == "%" and i + 1 < len(text) and text[i + 1] == "%":
            out.append("%")
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _enum(schema, name, v):
    for f in schema.fields:
        if f.name == name and f.enum:
            return f.enum.get(str(v), f.enum.get(v))
    return None


def describe_row(member, schema, row, char_help=None):
    """Rich-text hover description of one database row ('' when there is nothing to say)."""
    names = {f.name for f in schema.fields}
    title = row.get(schema.display) if schema.display else None
    if member == "char.dat":
        title = row.get("name_EN")
        sub = row.get("title_EN")
        if sub and sub != title:
            title = f"{title} — {sub}"
    desc = " ".join((row.get(n) or "").strip() for n in sorted(names)
                    if n.startswith("desc") and n.endswith("_EN") and row.get(n))
    if not desc and member == "char.dat" and char_help:
        desc = char_help.get(row.get("help_id"), "")
    if desc and "value1" in names:
        desc = _fill_values(desc, row)
    # %s marks a line break in skill texts ("Fist:%sHitting 3 times ...")
    desc = desc.replace("％", "%").replace("%s", " ").replace("  ", " ")
    facts = []
    if member == "magic.dat":
        if row.get("sp_cost"):
            facts.append(f"SP cost {row.get('sp_cost')}")
        for n in ("formula", "element", "weapon_type"):
            lab = _enum(schema, n, row.get(n))
            if lab and lab != "none":
                facts.append(lab)
        rng = row.get("range")
        if rng:
            facts.append("range: whole map" if rng == 99 else f"range {rng}")
    elif member == "Skill.dat":
        if row.get("slot_cost"):
            facts.append(f"evility slot cost {row.get('slot_cost')}")
        if row.get("mana_cost"):
            facts.append(f"{row.get('mana_cost')} mana")
    elif member == "item.dat":
        stats = [f"{s} {row.get(s):+d}" for s in _ITEM_STATS if s in names and isinstance(row.get(s), int) and row.get(s)]
        if stats:
            facts.append("  ".join(stats))
        if row.get("price"):
            facts.append(f"{row.get('price')} HL")
    elif member == "char.dat":
        facts.append("  ".join(f"{s} {row.get('base_' + s)}" for s in ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")
                               if f"base_{s}" in names))
    if not title and not desc and not facts:
        return ""
    parts = []
    if title:
        parts.append(f"<b>{_esc(title)}</b>")
    if desc:
        parts.append(_esc(desc))
    facts = [f for f in facts if f]
    if facts:
        parts.append(f"<span style='color:#9aa4b8'>{_esc(' · '.join(facts))}</span>")
    return "<qt>" + "<br>".join(parts) + "</qt>"


def get_service(ws):
    if not hasattr(ws, "_dbservice"):
        ws._dbservice = DBService(ws)
    return ws._dbservice


# ---------------------------------------------------------------------- name lookups
CHAR_ID_OFFSET = 0xD0      # u16 unit/class id used by maps, quests, etc.
CHAR_NAME_EN = 0x12C       # 52 bytes
CHAR_TITLE_EN = 0x240      # 68 bytes


def char_names(svc):
    """{char id: 'Name (Title)'} from char.dat (first occurrence wins)."""
    import struct
    out = {}
    try:
        t = svc.table("char.dat")
        rows = [bytes(r.raw) for r in t.rows]
    except Exception:
        d = svc.ws.read(f"{DB}/char.dat")
        n = struct.unpack_from("<I", d)[0]
        rows = [d[4 + i * 908:4 + (i + 1) * 908] for i in range(n)]
    for raw in rows:
        cid = struct.unpack_from("<H", raw, CHAR_ID_OFFSET)[0]
        name = raw[CHAR_NAME_EN:CHAR_NAME_EN + 52].split(b"\0")[0].decode("utf-8", "replace")
        title = raw[CHAR_TITLE_EN:CHAR_TITLE_EN + 68].split(b"\0")[0].decode("utf-8", "replace")
        if cid and cid not in out:
            out[cid] = f"{name} ({title})" if title and title != name else name
    return out


def table_names(svc, member):
    """{key: EN display name} for tables with key/display in their schema (item, magic, Skill, GE...)."""
    try:
        return {k: v for k, v in svc.ref_choices(member)}
    except Exception:
        return {}
