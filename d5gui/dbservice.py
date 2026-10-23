"""Database access for editors: vanilla tables + the mods' row patches.

Saving puts each change where it belongs: a row a mod made or changes (a new character, its recruit quest, its
description, its skills ...) into that mod -- the last one in the load order when several change it -- and
everything else (the game's own rows no mod changes, new rows) into the active mod (bottom left, "New edits go to").
So editing a mod's character needs no switching of the active mod.

A row a mod adds stays that mod's: kit versions before 1.5 saved changes to it into the active mod as a change of row
number N, which hits another row when the load order changes (and travels with a shared mod).  adopt_strays() moves
such changes into the mod that adds the row (the game gets the same table)."""
import datetime
import json
import os
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
        self._owners = {}
        self._adopted = set()
        self.saved_into = []                  # names of the mods the last commits wrote (the pages say where)
        ws.active_mod_changed.connect(lambda _: self.reload())
        ws.mods_changed.connect(lambda: self.reload(keep_unsaved=True))

    def reload(self, keep_unsaved=False):
        """Forget the loaded tables (they are rebuilt from the mods on the next use) and tell the pages, whose row
        numbers no longer hold (a mod switched off takes its added rows along: every later row moves up).
        keep_unsaved: unsaved edits are carried over -- as the active mod's patch (what Save would write, made
        against the tables they were edited on) applied to the new tables -- never kept as stale tables."""
        pending = {}
        if keep_unsaved:
            for m in self._dirty:
                if m in self._work:
                    try:
                        pending[m] = dbpatch.diff_table(self.base(m), self._work[m])
                    except Exception:
                        pass
        loaded = set(self._work) | set(self._base)
        self._work, self._base, self._dirty = {}, {}, set()
        self._owners = {}
        self._tipcache = {}
        for m, patch in pending.items():
            t = self._layered(m, False)
            dbpatch.apply_patch(t, patch)
            self._work[m] = t
            self._dirty.add(m)
        for m in sorted(loaded):
            self.table_changed.emit(m)

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

    def _layered(self, member, with_active, owners=None):
        """the table as the game will get it: original (or a mod's full-file copy) + every enabled mod's row
        patch in load order, the active mod last.  owners: a dict that gets {row index: (mod id, 'rows' or 'added',
        index in the mod's added list)} of the last mod changing or adding each row."""
        if member not in self._adopted:
            try:
                self.adopt_strays(member)
            except Exception as e:
                self.ws.log(f"(row changes of {member} not checked: {e})")
        t = database.load_table(member, self.ws.read(f"{DB}/{member}"))
        active = self.ws.active_mod

        def put(mod, patch):
            placed = [] if owners is not None else None
            warn = dbpatch.apply_patch(t, patch, placed=placed)
            if owners is not None:
                for idx in patch.get("rows") or {}:
                    if owners.get(int(idx), (None, None))[1] != "added":     # (a row a mod adds stays its own)
                        owners[int(idx)] = (mod.id, "rows", None)
                for k, i in enumerate(placed):
                    owners[i] = (mod.id, "added", k)
            return warn

        for mod in self.ws.mods.enabled_mods():
            if active and mod.id == active.id:
                continue
            patch = mod.load_patch("db", member + ".json")
            if patch:
                put(mod, patch)
        if with_active and active:
            patch = active.load_patch("db", member + ".json")
            if patch:
                for w in put(active, patch):
                    self.ws.log("warning: " + w)
        return t

    def owner_map(self, member):
        """{row index: (mod id, kind, k)} (_layered)"""
        o = self._owners.get(member)
        if o is None:
            o = {}
            self._layered(member, True, o)
            self._owners[member] = o
        return o

    def row_owner(self, member, index):
        """the enabled mod that made or (last) changes row `index` -- where its changes are saved; None: the game's
        own row no mod changes (its changes go into the active mod)"""
        o = self.owner_map(member).get(int(index))
        return self.ws.mods.get(o[0]) if o else None

    def _route(self, member, with_active=False):
        """{mod id: [(row index, kind, k, {field: value})]}: rows changed since the last save that a mod other than
        the active one (with_active: any mod) made or changes"""
        work = self._work.get(member)
        if work is None:
            return {}
        act = self.ws.active_mod
        enabled = {m.id for m in self.ws.mods.enabled_mods()}
        mine = {i: o for i, o in self.owner_map(member).items()
                if o[0] in enabled and (with_active or not (act and o[0] == act.id))}
        if not mine:
            return {}
        saved = self._layered(member, True)
        if len(work.rows) < len(saved.rows):          # rows deleted: the numbers moved (all goes as before)
            return {}
        out = {}
        for i, (mid, kind, k) in sorted(mine.items()):
            if i >= len(saved.rows):
                continue
            a, b = saved.rows[i], work.rows[i]
            if bytes(a.raw) == bytes(b.raw) and a.strs == b.strs:
                continue
            ch = {f.name: dbpatch._jsonable(b._get(f)) for f in saved.schema.fields if a._get(f) != b._get(f)}
            if ch:
                out.setdefault(mid, []).append((i, kind, k, ch))
        return out

    def _save_routed(self, mod, member, items):
        p = mod.load_patch("db", member + ".json") or {"table": member}
        added = p.get("added") or []
        for i, kind, k, ch in items:
            if kind == "added" and k is not None and k < len(added) and isinstance(added[k], dict):
                added[k].update(ch)
            else:
                p.setdefault("rows", {}).setdefault(str(i), {}).update(ch)
        mod.save_patch("db", member + ".json", p)

    def base(self, member) -> database.Table:
        """What the active mod's patch is applied on (= saved as differences against)."""
        t = self._base.get(member)
        if t is None:
            t = self._base[member] = self._layered(member, False)
        return t

    def adopt_strays(self, member):
        """move changes a mod makes to a row another mod adds (by row number, see the module text) into the mod that
        adds it, in load order as the install has them -> number moved.  The patch files are copied to
        state/mod_backups first."""
        self._adopted.add(member)
        mods = self.ws.mods.enabled_mods()
        if not any(m.load_patch("db", member + ".json") for m in mods):
            return 0
        t = database.load_table(member, self.ws.read(f"{DB}/{member}"))
        added_by, moves = {}, []
        for m in mods:
            p = m.load_patch("db", member + ".json")
            if not p:
                continue
            for idx, fields in (p.get("rows") or {}).items():
                a = added_by.get(int(idx))
                if a is not None and a[0].id != m.id and fields:
                    r = t.rows[int(idx)]
                    moves.append((m, idx, a, dict(fields), r["name_EN"] if "name_EN" in r else f"row {idx}"))
            placed = []
            dbpatch.apply_patch(t, p, placed=placed)
            for k, i in enumerate(placed):
                added_by[i] = (m, k)
        if not moves:
            return 0
        from .workspace import KIT_DIR
        bdir = os.path.join(KIT_DIR, "state", "mod_backups",
                            "row_changes_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        for m, idx, (a, k), fields, name in moves:
            for mod in (m, a):
                src = mod.patch_path("db", member + ".json")
                dst = os.path.join(bdir, mod.id, member + ".json")
                if os.path.exists(src) and not os.path.exists(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(src, "rb") as f, open(dst, "wb") as g:
                        g.write(f.read())
            pa = a.load_patch("db", member + ".json")
            pa["added"][k].update(fields)
            a.save_patch("db", member + ".json", pa)
            pm = m.load_patch("db", member + ".json")
            pm["rows"].pop(idx, None)
            if not pm["rows"]:
                pm.pop("rows")
            m.save_patch("db", member + ".json", None if dbpatch.is_empty(pm) else pm)
            self.ws.log(f"{member.rsplit('.', 1)[0]}: the changes to {name} kept in the mod '{m.name}' moved into "
                        f"'{a.name}', which adds {name} (a copy of both files: "
                        f"{os.path.relpath(bdir, KIT_DIR)})")
        return len(moves)

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

    def _note(self, mod):
        for lst in (self.saved_into, self.last_saved):
            if mod.name not in lst:
                lst.append(mod.name)

    def saved_text(self):
        """where the last commit() saved: "'A'" / "'A', 'B'" (for log lines)"""
        names = getattr(self, "last_saved", None) or []
        return ", ".join(f"'{n}'" for n in names) if names else "no mod (nothing changed)"

    def _done(self, member):
        # the working table goes too: a mod made during the commit (require_mod) rebuilt it before the patch was
        # written, so it would be missing the rows just saved; the next table() layers everything afresh
        self._work.pop(member, None)
        self._base.pop(member, None)
        self._owners.pop(member, None)
        self._dirty.discard(member)
        self.ws.file_changed.emit(f"{DB}/{member}")
        self.table_changed.emit(member)

    def _commit_into(self, member, into):
        """commit() with `into` instead of the active mod: rows a mod made or changes go into that mod, new rows and
        changes to rows no mod changes into `into` -> False when it can't (rows were deleted)"""
        work = self._work.get(member)
        saved = self._layered(member, True)
        if work is None or len(work.rows) < len(saved.rows):
            return False
        routed = self._route(member, with_active=True)
        ch = dbpatch.diff_table(saved, work)
        for items in routed.values():
            for i, *_ in items:
                (ch.get("rows") or {}).pop(str(i), None)
        for mid, items in routed.items():
            m = self.ws.mods.get(mid)
            self._save_routed(m, member, items)
            self._note(m)
        if ch.get("rows") or ch.get("added"):
            p = into.load_patch("db", member + ".json") or {"table": member}
            for idx, fields in (ch.get("rows") or {}).items():
                p.setdefault("rows", {}).setdefault(idx, {}).update(fields)
            if ch.get("added"):
                p.setdefault("added", []).extend(ch["added"])
            into.save_patch("db", member + ".json", p)
            self._note(into)
        self._done(member)
        return True

    def commit(self, member, parent=None, into=None, suggest=None, category=None):
        """Save working-table differences: rows another mod made or changes into that mod (_route), the rest into
        the active mod as a patch (or into the mod `into`: a new skill of a mod's character goes into its mod).
        suggest / category: for the mod asked for when there is none (its name offered, its kind)."""
        self.last_saved = []
        act = self.ws.active_mod
        if into is not None and (act is None or into.id != act.id) and self._commit_into(member, into):
            return True
        routed = self._route(member)
        patch = dbpatch.diff_table(self.base(member), self.table(member))
        for items in routed.values():
            for i, *_ in items:
                (patch.get("rows") or {}).pop(str(i), None)
        if "rows" in patch and not patch["rows"]:
            patch.pop("rows")
        act = self.ws.active_mod
        mod = None
        if act is not None or not dbpatch.is_empty(patch):
            mod = self.ws.require_mod(parent, suggest=suggest, category=category)
            if not mod:
                return False
        for mid, items in routed.items():
            m = self.ws.mods.get(mid)
            self._save_routed(m, member, items)
            self._note(m)
            self.ws.log(f"{member.rsplit('.', 1)[0]}: changes to {len(items)} row(s) made by the mod '{m.name}' "
                        "saved in it")
        if mod is None:
            self._done(member)
            return True
        old = mod.load_patch("db", member + ".json") or {}
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
        new = None if dbpatch.is_empty(patch) else patch
        if json.dumps(new, sort_keys=True) != json.dumps(old or None, sort_keys=True):   # (unchanged: not rewritten)
            mod.save_patch("db", member + ".json", new)
            self._note(mod)
        self._done(member)
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
