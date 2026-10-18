"""What a mod is and what it holds, in words: its category, the group it belongs to (outfit mods: their character),
a readable summary of its contents, which mods need it -- for the Home page's mod list.  Also mod packs: several mods
shown and switched as one entry (mods/packs.json), without touching the mods themselves.

Nothing here changes a mod.  A mod can set its own category in mod.json ("category": one of CATEGORY_KEYS); else it is
guessed from what it holds:
    system      features other mods build on, or that change how the game works (Outfit System, colour slots)
    outfits     outfits for existing characters (patches/outfits/outfits.json, nothing else new)
    characters  new playable characters (patches/characters, or new unique char.dat rows + a recruit quest)
    classes     new generic classes and monsters (patches/classes)
    skills      skills and their animations (patches/skills)
    gameplay    gameplay features (patches/autobattle ...)
    story       dialogue, text, event scripts
    art         sprites, textures, music without other changes
    data        database edits only
    other       anything else (a new empty mod starts here)
"""
import json
import os
from collections import Counter

CATEGORIES = [
    ("system", "⚙  Systems"),
    ("outfits", "👗  Outfits"),
    ("characters", "🧙  New characters"),
    ("classes", "🛡  Classes & monsters"),
    ("skills", "✨  Skills & effects"),
    ("gameplay", "⚔  Gameplay"),
    ("story", "💬  Story & text"),
    ("art", "🎨  Art & sound"),
    ("data", "📊  Database"),
    ("other", "📦  Other"),
]
CATEGORY_KEYS = [k for k, _ in CATEGORIES]
CATEGORY_LABELS = dict(CATEGORIES)
SYSTEM_HANDLERS = {"customcolors"}
GAMEPLAY_HANDLERS = {"autobattle"}
STORY_HANDLERS = {"text", "talk", "scripts", "script", "dialogue"}
FILE_KINDS = [  # (extension / folder hint, words)
    ((".lzs", ".anm"), "sprite"),
    ((".txf", ".png", ".dds"), "texture"),
    ((".ogg", ".wav", ".vag", ".at9"), "sound"),
    ((".obf",), "3D model"),
    ((".dat",), "data file"),
]


# ------------------------------------------------------------------------------------------------ reading a mod
def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def handlers(mod):
    """the patch folders a mod has (one per patch handler)"""
    try:
        return sorted(d for d in os.listdir(mod.patches_dir) if os.path.isdir(os.path.join(mod.patches_dir, d)))
    except OSError:
        return []


def outfits_of(mod):
    """[(character class, outfit class, outfit name)] from patches/outfits/outfits.json -- without the ones the mod
    hides itself (kept only so saves using them still work, e.g. Girl Laharl's Thunderlady looks, which are the
    Thunderlady character's)"""
    d = _json(os.path.join(mod.patches_dir, "outfits", "outfits.json")) or {}
    names = d.get("names") or {}
    hidden = {int(x) for x in d.get("hide") or []}
    return [(int(c), int(o), names.get(str(o)) or f"outfit {o}") for c, o in d.get("pairs") or []
            if int(o) not in hidden]


def db_changes(mod):
    """{table: (rows added, rows edited, [added rows])} of the mod's database patches"""
    out = {}
    pdir = os.path.join(mod.patches_dir, "db")
    try:
        names = sorted(os.listdir(pdir))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        d = _json(os.path.join(pdir, n))
        if not isinstance(d, dict) or "table" not in d:
            continue
        added = d.get("added") or []
        out[d["table"]] = (len(added), len(d.get("rows") or {}), added)
    return out


def new_classes(mod):
    """[(family id, name, hire text)] from patches/classes/class_*.json"""
    out = []
    pdir = os.path.join(mod.patches_dir, "classes")
    try:
        names = sorted(os.listdir(pdir))
    except OSError:
        return out
    for n in names:
        if n.startswith("class_") and n.endswith(".json"):
            d = _json(os.path.join(pdir, n)) or {}
            out.append((d.get("family"), d.get("name") or n[6:-5], d.get("hire_desc") or ""))
    return out


def file_kinds(mod):
    """Counter of file kinds ('sprite', 'texture' ...) under files/"""
    c = Counter()
    for f in mod.list_files():
        ext = os.path.splitext(f)[1].lower()
        kind = next((w for exts, w in FILE_KINDS if ext in exts), "file")
        c[kind] += 1
    return c


def skills_of(mod):
    """(skills changed, events, effects) counts from patches/skills/skills.json"""
    d = _json(os.path.join(mod.patches_dir, "skills", "skills.json")) or {}
    return len(d.get("skills") or {}), len(d.get("events") or {}), len(d.get("effects") or {})


# ------------------------------------------------------------------------------------------------ category
def _new_unique_chars(db, mod=None):
    """added char.dat rows with a unique-character id (< 1000) that aren't one of the mod's outfits -- new
    characters, not classes or outfit looks"""
    rows = db.get("char.dat", (0, 0, []))[2]
    looks = {o for _, o, _ in outfits_of(mod)} if mod is not None else set()
    return [r for r in rows if isinstance(r, dict) and 0 < int(r.get("id", 0)) < 1000 and int(r["id"]) not in looks]


def _renamed_rows(mod, names):
    """[(class id, old name, new name)] of existing char.dat rows the mod renames (a new character made from a
    reserved 'DLC Dummy' row shows as one)"""
    d = _json(os.path.join(mod.patches_dir, "db", "char.dat.json")) or {}
    out = []
    by_index = getattr(names, "by_index", None) or []
    for idx, fields in (d.get("rows") or {}).items():
        if not isinstance(fields, dict) or "name_EN" not in fields:
            continue
        i = int(idx)
        vid, vname = by_index[i] if i < len(by_index) else (None, "")
        out.append((vid, vname, fields["name_EN"]))
    return out


def _is_dummy(name):
    return not name or "dummy" in name.lower()


def _new_char_rows(mod, names, looks):
    """renamed reserved rows that are new unique characters (class < 1000; generic class tiers belong to a class)"""
    return [(vid, new) for vid, old, new in _renamed_rows(mod, names)
            if _is_dummy(old) and vid not in looks and (vid is None or vid < 1000)]


def category(mod):
    cat = (mod.meta.get("category") or "").strip().lower()
    if cat in CATEGORY_KEYS:
        return cat
    hs = set(handlers(mod))
    if hs & GAMEPLAY_HANDLERS:
        return "gameplay"
    if hs & SYSTEM_HANDLERS:
        return "system"
    if mod.id == "Outfit_System" or (hs == {"outfits"} and not outfits_of(mod)):
        return "system"
    db = db_changes(mod)
    if "classes" in hs:
        return "classes"
    if "characters" in hs or ("Quest.dat" in db and db["Quest.dat"][0] and (_new_unique_chars(db, mod) or "char.dat" in db)):
        return "characters"
    if outfits_of(mod):
        return "outfits"
    if "skills" in hs:
        return "skills"
    if hs & STORY_HANDLERS:
        return "story"
    kinds = file_kinds(mod)
    if kinds and not hs:
        return "art"
    if db and hs <= {"db"} and not kinds:
        return "data"
    return "other"


def group_of(mod, class_names=None):
    """a sub-group inside the category: outfit mods -> their character's name, else None"""
    if category(mod) != "outfits":
        return None
    chars = sorted({c for c, _, _ in outfits_of(mod)})
    if not chars:
        return None
    names = [(class_names or {}).get(c) or f"class {c}" for c in chars]
    return names[0] if len(names) == 1 else ", ".join(names)


# ------------------------------------------------------------------------------------------------ summary
def skill_names(read):
    """{magic.dat row index: name} of the game's skills (for summary: which skills a mod changes)"""
    try:
        from . import database
        t = database.load_table("magic.dat", read())
        return {i: (r["name_EN"] or str(r["id"])) for i, r in enumerate(t.rows)}
    except Exception:
        return {}


def summary(mod, class_names=None, all_mods=(), skill_names=None):
    """readable lines about what the mod holds (the Home page's 'What's inside')"""
    cn = class_names or {}
    lines = []
    outs = outfits_of(mod)
    if outs:
        by_char = {}
        for c, o, n in outs:
            by_char.setdefault(c, []).append(n)
        for c, names in by_char.items():
            who = cn.get(c) or f"class {c}"
            lines.append(f"👗 {len(names)} outfit{'s' if len(names) != 1 else ''} for {who}: " + ", ".join(names))
    elif mod.id == "Outfit_System" or (set(handlers(mod)) == {"outfits"}):
        lines.append("👗 The Outfit entry in the character menu (the system outfit mods build on)")
    db = db_changes(mod)
    looks = {o for _, o, _ in outs}
    for r in _new_unique_chars(db, mod):
        nm = r.get("name_EN") or r.get("name") or f"class {r.get('id')}"
        lines.append(f"🧙 New character: {nm} (class {r.get('id')})")
    for vid, new in _new_char_rows(mod, cn, looks):
        lines.append(f"🧙 New character: {new}" + (f" (class {vid})" if vid is not None else ""))
    for vid, old, new in _renamed_rows(mod, cn):
        if vid not in looks and not _is_dummy(old) and old != new:
            lines.append(f"✏ {old} renamed to {new}")
    for fam, nm, hire in new_classes(mod):
        lines.append(f"🛡 New class: {nm}" + (f" — {hire}" if hire else ""))
    q = db.get("Quest.dat")
    if q and q[0]:
        lines.append("📜 Quest" + ("s" if q[0] > 1 else "") + ": " + ", ".join(
            r.get("name_EN") or str(r.get("id")) for r in q[2] if isinstance(r, dict)))
    m = db.get("magic.dat")
    if m and m[0]:
        lines.append("✨ New skills: " + ", ".join(r.get("name_EN") or str(r.get("id")) for r in m[2]
                                                   if isinstance(r, dict)))
    if m and m[1]:
        d = _json(os.path.join(mod.patches_dir, "db", "magic.dat.json")) or {}
        idx = sorted(int(k) for k in (d.get("rows") or {}) if str(k).isdigit())
        names = [(skill_names or {}).get(i, f"row {i}") for i in idx]
        lines.append(f"✨ Skills changed ({len(idx)}): " + ", ".join(names[:8]) + (" …" if len(names) > 8 else ""))
    g = _json(os.path.join(mod.patches_dir, "spells", "growth.json")) or {}
    if g.get("levels"):
        lines.append("🔮 Spells' reach and area tiers end at levels " + ", ".join(str(v) for v in g["levels"]))
    sk, ev, fx = skills_of(mod)
    if sk or ev or fx:
        parts = [f"{sk} skill animation{'s' if sk != 1 else ''}" if sk else "",
                 f"{ev} script event{'s' if ev != 1 else ''}" if ev else "",
                 f"{fx} effect{'s' if fx != 1 else ''}" if fx else ""]
        lines.append("🎬 " + ", ".join(p for p in parts if p))
    hs = set(handlers(mod))
    if "autobattle" in hs:
        lines.append("⚔ Item World auto-battle settings and Demonic Intelligence programs")
    if "customcolors" in hs:
        lines.append("🎨 Custom Color slots in the colour screens")
    if "grips" in hs:
        n = len([f for f in os.listdir(os.path.join(mod.patches_dir, "grips")) if f.endswith(".json")])
        lines.append(f"🗡 Weapon grips for {n} sprite{'s' if n != 1 else ''}")
    tables = [(t, a, e) for t, (a, e, _) in db.items() if t not in ("Quest.dat", "magic.dat") or e]
    if tables:
        lines.append("📊 Database: " + "; ".join(
            f"{t} " + ", ".join(x for x in ((f"+{a} rows" if a else ""), (f"{e} edited" if e else "")) if x)
            for t, a, e in tables))
    kinds = file_kinds(mod)
    if kinds:
        lines.append("📁 Files: " + ", ".join(f"{n} {k}{'s' if n != 1 else ''}" for k, n in kinds.most_common()))
    other = sorted(hs - {"outfits", "db", "classes", "characters", "skills", "autobattle", "customcolors", "grips"})
    if other:
        lines.append("🧩 Also: " + ", ".join(other))
    needed_by = [x for x in all_mods if mod.id in (x.meta.get("requires") or [])]
    if needed_by:
        lines.append(f"🔗 Needed by {len(needed_by)} mod{'s' if len(needed_by) != 1 else ''}: "
                     + ", ".join(x.name for x in needed_by[:6]) + (" …" if len(needed_by) > 6 else ""))
    if not lines:
        lines.append("(no changes yet)")
    return lines


def one_line(mod, class_names=None):
    """a short subtitle for the list"""
    outs = outfits_of(mod)
    n_out = f"{len(outs)} outfit{'s' if len(outs) != 1 else ''}" if outs else ""
    db = db_changes(mod)
    chars = [r.get("name_EN") or str(r.get("id")) for r in _new_unique_chars(db, mod)]
    looks = {o for _, o, _ in outs}
    chars += [new for _, new in _new_char_rows(mod, class_names or {}, looks)]
    if chars:
        return "new character: " + ", ".join(dict.fromkeys(chars)) + (f" · {n_out}" if n_out else "")
    if n_out:
        return n_out
    cls = new_classes(mod)
    if cls:
        return "new class: " + ", ".join(n for _, n, _ in cls)
    d = (mod.meta.get("description") or "").strip()
    return (d[:60] + "…") if len(d) > 61 else d


# ------------------------------------------------------------------------------------------------ class names
class Names(dict):
    """{class id: English name}; .by_index: [(id, name)] of the game's own char.dat rows (database patches edit
    rows by index)"""
    by_index = ()


def class_names(read_char_dat, mods=()):
    """Names from char.dat (read_char_dat() -> bytes) plus the mods' added rows"""
    from . import database
    out = Names()
    try:
        t = database.load_table("char.dat", read_char_dat())
        out.by_index = [(int(r["id"]), r.get("name_EN") or "") for r in t.rows]
        for i, n in out.by_index:
            out[i] = n
    except Exception:                   # no game: names fall back to 'class N'
        pass
    for m in mods:
        for r in db_changes(m).get("char.dat", (0, 0, []))[2]:
            if isinstance(r, dict) and r.get("id") is not None:
                out.setdefault(int(r["id"]), r.get("name_EN") or "")
    return out


# ------------------------------------------------------------------------------------------------ packs
class Packs:
    """mods/packs.json: {"packs": [{"id", "name", "description", "members": [mod ids]}]}.  A pack is only a way of
    showing and switching several mods as one; the mods stay as they are (ungrouping changes nothing else)."""

    def __init__(self, mods_dir):
        self.path = os.path.join(mods_dir, "packs.json")
        self.packs = (_json(self.path) or {}).get("packs") or []

    def save(self):
        if not self.packs:
            if os.path.exists(self.path):
                os.remove(self.path)
            return
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"packs": self.packs}, f, indent=2, ensure_ascii=False)

    def pack_of(self, mod_id):
        return next((p for p in self.packs if mod_id in p.get("members", [])), None)

    def create(self, name, members, description=""):
        members = list(dict.fromkeys(members))
        for p in self.packs:                       # a mod is in one pack at most
            p["members"] = [m for m in p.get("members", []) if m not in members]
        base = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_") or "Pack"
        pid, k = base, 2
        while any(p["id"] == pid for p in self.packs):
            pid, k = f"{base}_{k}", k + 1
        pack = {"id": pid, "name": name, "description": description, "members": members}
        self.packs.append(pack)
        self.packs = [p for p in self.packs if p.get("members")]
        self.save()
        return pack

    def remove(self, pack_id):
        self.packs = [p for p in self.packs if p["id"] != pack_id]
        self.save()

    def remove_member(self, mod_id):
        for p in self.packs:
            if mod_id in p.get("members", []):
                p["members"].remove(mod_id)
        self.packs = [p for p in self.packs if p.get("members")]
        self.save()
