"""Sharing mods between players -- custom characters above all -- without breaking anyone's saves or work.

A shared mod is its folder in a zip (export_package): mod.json + files/ + patches/.  mod.json carries
    "uid"        the mod's identity on every PC (made the first time it is exported, kept from then on)
    "version"    the author's version
    "based_on"   [{"uid", "name", "version", "author"}]: the mods it was made from (someone's work, iterated on)
On the PC that imported it, mod.json also holds
    "local_ids"  {kind: {"package id": local id}}: ids the package uses that were moved here because another mod
                 already used them (see KINDS)

import_package():
  * a mod with the same uid is here -> an UPDATE: the old folder is kept as a zip in state/mod_backups/, the package
    replaces it, ids moved for the old version are moved the same way again (units in saves keep their class, their
    skills ...), new ids that clash are moved too.  The update keeps whether the mod is switched on.
  * else a NEW mod: its folder gets a free name; it is switched on.
  * other mods are never changed.

Kinds of ids (what can clash between two mods made on different PCs):
    class    unique class ids below 1000 (new characters, outfit slots): char.dat rows, outfit pairs, faces, quests'
             recruit rewards, skills' users
    sprite   new sprite numbers, in groups of ten (anm N .. N+9 and the portraits 10000 + N ...): anm files and the
             blocks inside, char.dat sprite_id, outfit own sprites / parts / sources / event sheets, weapon grips
    help     charhelp.dat ids (character descriptions)
    quest    Quest.dat ids, and the quest's progress slot (its sort_order)
    skill    magic.dat ids: learned skills, skill animations
    evility  Skill.dat ids (evilities): characters' evilities
    event    custom choreography blocks (15900000, 14000000, 5000000 + n x 1000) of skills.json
    effect   custom effect models (3000+) of skills.json
    overload new Overloads (300+): OverlordSkill.dat rows and their script ids, overloads.json, characters'
             overload_id, their animations (skills.json OVL_KEY + id) and banner pictures; an Overload's own skill
             row (magic 3048-3255) moves as a "skill" within that range
A mod that edits rows the game already has (by index) keeps them: they are the same on every PC.  New generic
classes (patches/classes) keep their family ids: when one clashes the import says so and stops.
"""
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile

from . import dbpatch, skills

DB = "Database/Database_0.dat/"
KINDS = ("class", "sprite", "help", "quest", "slot", "skill", "evility", "event", "effect", "overload")
ANM_RE = re.compile(r"^(.*/)?anm(\d{5})\.lzs$", re.I)
MOD_CHOREO_BASE, CHOREO_MAX = 15900000, 16000000


# ------------------------------------------------------------------------------------------------ identity
def ensure_uid(mod):
    """the mod's uid (made and saved on first use)"""
    if not mod.meta.get("uid"):
        mod.meta["uid"] = uuid.uuid4().hex
        mod.save_meta()
    return mod.meta["uid"]


def export_package(mod, path, version=None, author=None):
    """zip the mod for sharing (mod.json gets a uid; version / author if given).  -> path
    A mod imported here whose ids were moved (local_ids) is not shared again under its identity: its files carry this
    PC's ids, which would not match the original's on a third PC.  Share the original package, or make your own
    version (derive) and share that."""
    if mod.meta.get("local_ids"):
        raise ValueError(f"'{mod.name}' came from someone else and some of its ids were moved on this PC, so it can't "
                         "be shared again as the same mod. Share their original package instead, or right-click › "
                         "Make my own version and share that.")
    ensure_uid(mod)
    if version:
        mod.meta["version"] = version
    if author:
        mod.meta["author"] = author
    mod.save_meta()
    meta = {k: v for k, v in mod.meta.items() if k != "local_ids"}
    meta["exported"] = time.strftime("%Y-%m-%d %H:%M")
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{mod.id}/mod.json", json.dumps(meta, indent=2, ensure_ascii=False))
        for root, _, files in os.walk(mod.folder):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, mod.folder).replace(os.sep, "/")
                if rel == "mod.json":
                    continue
                z.write(full, f"{mod.id}/{rel}")
    os.replace(tmp, path)
    return path


def derive(mod, new_name, author=""):
    """start iterating on someone's mod: a copy with its own uid that remembers where it came from (based_on)"""
    from .modsys import Mod
    root = os.path.dirname(mod.folder)
    fid = _free_folder(root, "".join(c if c.isalnum() else "_" for c in new_name).strip("_") or "Mod")
    shutil.copytree(mod.folder, os.path.join(root, fid))
    new = Mod(os.path.join(root, fid))
    base = {"uid": ensure_uid(mod), "name": mod.name, "version": mod.meta.get("version", ""),
            "author": mod.meta.get("author", "")}
    new.meta.update({"name": new_name, "uid": uuid.uuid4().hex, "version": "1.0",
                     "based_on": list(mod.meta.get("based_on") or []) + [base]})
    if author:
        new.meta["author"] = author
    new.meta.pop("local_ids", None)
    new.save_meta()
    return new


def _free_folder(root, base):
    fid, k = base, 2
    while os.path.exists(os.path.join(root, fid)):
        fid, k = f"{base}_{k}", k + 1
    return fid


# ------------------------------------------------------------------------------------------------ ids of a mod
def _patch(mod, name):
    return mod.load_patch("db", f"{name}.json") or {}


def _added(mod, name):
    return [r for r in _patch(mod, name).get("added") or [] if isinstance(r, dict)]


DUMMY_ROWS = (470, 480, 490, 950, 960, 970, 980, 990)     # the game's unused unique rows (d5lib.slots)


def ids_of(mod, vanilla_char_ids=(), vanilla_sprites=(), vanilla_by_index=()):
    """{kind: set of ids} a mod brings (new ones only: rows it adds, the reserved dummy rows it fills in, new sprite
    numbers, its custom events ...)"""
    from . import outfits
    out = {k: set() for k in KINDS}
    fams = class_families(mod)                 # a generic class's own rows keep their family (see the docstring)
    for r in _added(mod, "char.dat"):
        if int(r.get("id", 0)) > 0 and int(r["id"]) // 10 * 10 not in fams:
            out["class"].add(int(r["id"]))
    for idx in (_patch(mod, "char.dat").get("rows") or {}):
        i = int(idx)
        if i < len(vanilla_by_index) and vanilla_by_index[i] in DUMMY_ROWS:
            out["class"].add(vanilla_by_index[i])
    o = outfits._data(mod)
    for a, b in o.get("pairs", []):
        if int(b) < 1000 and int(b) not in vanilla_char_ids:
            out["class"].add(int(b))
    for f in mod.list_files():
        m = ANM_RE.match(f)
        if m:
            n = int(m.group(2))
            n = n - 10000 if n >= 10000 else n
            if n not in vanilla_sprites and n + 10000 not in vanilla_sprites:
                out["sprite"].add(n // 10 * 10)
    for r in _added(mod, "charhelp.dat"):
        out["help"].add(int(r["id"]))
    for r in _added(mod, "Quest.dat"):
        out["quest"].add(int(r["id"]))
        if "sort_order" in r:
            out["slot"].add(int(r["sort_order"]))
    for r in _added(mod, "magic.dat"):
        out["skill"].add(int(r["id"]))
    for r in _added(mod, "Skill.dat"):
        out["evility"].add(int(r["id"]))
    for r in _added(mod, "OverlordSkill.dat"):
        out["overload"].add(int(r["id"]))
    sk = mod.load_patch("skills", "skills.json") or {}
    for k in sk.get("events") or {}:
        if skills.is_custom_choreo(k):
            out["event"].add(int(k) // 1000 * 1000)
    out["effect"] |= {int(k) for k in sk.get("effects") or {}}
    return out


def class_families(mod):
    return {int(n[6:-5]) for n in (os.listdir(os.path.join(mod.patches_dir, "classes"))
                                   if os.path.isdir(os.path.join(mod.patches_dir, "classes")) else [])
            if n.startswith("class_") and n.endswith(".json")}


# ------------------------------------------------------------------------------------------------ planning
def plan(pkg_mod, others, fs, keep=None):
    """{kind: {package id: new id}} moving every id of pkg_mod that one of `others` (or the game) uses; `keep`: the
    mapping an earlier version got on this PC (reused for ids still in the package)"""
    from . import database, slots, sprites
    van = database.load_table("char.dat", fs.read(DB + "char.dat"))
    by_index = [int(r["id"]) for r in van.rows]
    vchar = set(by_index)
    vspr = sprites.used_sprite_numbers(fs)
    mine = ids_of(pkg_mod, vchar, vspr, by_index)
    used = {k: set() for k in KINDS}
    for m in others:
        for k, v in ids_of(m, vchar, vspr, by_index).items():
            used[k] |= v
    # the game's own ids
    used["sprite"] |= {n // 10 * 10 for n in vspr if n < 10000} | {(n - 10000) // 10 * 10 for n in vspr if n >= 10000}
    for name, kind in (("charhelp.dat", "help"), ("Quest.dat", "quest"), ("magic.dat", "skill"),
                       ("Skill.dat", "evility"), ("OverlordSkill.dat", "overload")):
        try:
            t = database.load_table(name, fs.read(DB + name))
        except Exception:
            continue
        used[kind] |= {int(r["id"]) for r in t.rows}
        if name == "charhelp.dat":
            used["help"] |= {int(r["char_id"]) for r in t.rows}
        if name == "Quest.dat":
            used["slot"] |= {int(r["sort_order"]) for r in t.rows}
            slot_limit = len(t.rows) + sum(len(_added(m, "Quest.dat")) for m in others) + len(_added(pkg_mod, "Quest.dat"))
    used["class"] |= vchar - set(DUMMY_ROWS)          # a dummy row clashes only when another mod fills it in
    keep = keep or {}
    limits = {"slot": locals().get("slot_limit")}
    mapping = {k: {} for k in KINDS}
    taken = {k: set(used[k]) | {v for v in (keep.get(k) or {}).values()} for k in KINDS}
    for kind in KINDS:
        old = {int(a): int(b) for a, b in (keep.get(kind) or {}).items()}
        for i in sorted(mine[kind]):
            if i in old:
                mapping[kind][i] = old[i]
                continue
            if i not in used[kind]:
                continue
            new = _free(kind, i, taken[kind], fs, van, limits.get(kind))
            mapping[kind][i] = new
            taken[kind].add(new)
        mapping[kind] = {a: b for a, b in mapping[kind].items() if a != b}
    clash = class_families(pkg_mod) & set().union(*(class_families(m) for m in others)) if others else set()
    if clash:
        raise ValueError(f"the package's new classes use the families {sorted(clash)}, which another mod here uses "
                         "too: switch one of them off (moving class families is not supported)")
    return mapping


def _free(kind, i, taken, fs, van, limit=None):
    if kind == "class" and i >= 1000:                     # a row of its own above the unique range
        j = i + 1
        while j in taken:
            j += 1
        return j
    if kind == "class":
        from . import slots
        for c in slots.unique_pool(fs, van):
            if c not in taken:
                return c
        raise RuntimeError("no free character id below 1000")
    if kind == "sprite":
        n = 9000
        while n in taken or n + 10000 > 32767:
            n += 10
        return n
    if kind == "event":
        b = MOD_CHOREO_BASE
        while b in taken:
            b = skills.next_block(b)
        return b
    if kind == "effect":
        e = 3000
        while e in taken:
            e += 1
        return e
    if kind == "overload":
        from . import overloads
        for j in range(max(i, overloads.NEW_FIRST), overloads.NEW_LAST + 1):
            if j not in taken:
                return j
        raise RuntimeError("no free Overload id")
    if kind == "skill" and 3000 <= i <= 3255:            # an Overload's own skill row stays in the Overload range
        from . import overloads
        for j in range(overloads.SKILL_FIRST, overloads.SKILL_LAST + 1):
            if j not in taken:
                return j
        raise RuntimeError("no free Overload skill id (3048-3255)")
    if kind == "slot":                                   # the quest board lists slots below the quest count
        for s in range(0, limit or 10 ** 6):
            if s not in taken:
                return s
        s = 0
        while s in taken:
            s += 1
        return s
    j = i + 1
    while j in taken:
        j += 1
    return j


# ------------------------------------------------------------------------------------------------ applying
def _spr(m, n):
    """sprite number n moved by the group map m (offset kept; portraits 10000 + n too)"""
    hi = n >= 10000
    b = n - 10000 if hi else n
    g = b // 10 * 10
    if g not in m:
        return n
    return m[g] + (b - g) + (10000 if hi else 0)


def apply(mod, mapping, log=print, vanilla_char=None):
    """rewrite the mod's files and patches with the moved ids (mapping from plan()).  vanilla_char: the game's
    char.dat (needed when a filled-in dummy row moves: its edit becomes a new row)"""
    from . import anm
    C, S, H = mapping.get("class", {}), mapping.get("sprite", {}), mapping.get("help", {})
    Q, QS, K = mapping.get("quest", {}), mapping.get("slot", {}), mapping.get("skill", {})
    EV, E, FX = mapping.get("evility", {}), mapping.get("event", {}), mapping.get("effect", {})
    O = mapping.get("overload", {})
    from .skills import OVL_WRAPPER
    if not any(mapping.values()):
        return
    c = lambda v: C.get(int(v), int(v))                               # noqa: E731
    # ---- a filled-in dummy row that moves: the edit becomes a whole new row with the new id
    cp = _patch(mod, "char.dat")
    if C and cp.get("rows") and vanilla_char is not None:
        for idx in list(cp["rows"]):
            i = int(idx)
            vid = int(vanilla_char.rows[i]["id"]) if i < len(vanilla_char.rows) else None
            if vid in DUMMY_ROWS and vid in C:
                full = {k: dbpatch._jsonable(v) for k, v in vanilla_char.rows[i].to_dict().items()}
                full.update(cp["rows"].pop(idx))
                full["id"] = vid                            # moved with the rest below
                cp.setdefault("added", []).append(full)
        mod.save_patch("db", "char.dat.json", cp)
    # ---- database
    for name in ("char.dat", "charhelp.dat", "Quest.dat", "magic.dat", "Skill.dat", "OverlordSkill.dat"):
        p = _patch(mod, name)
        if not p:
            continue
        rows = list(p.get("added") or []) + list((p.get("rows") or {}).values())
        for r in rows:
            if not isinstance(r, dict):
                continue
            if name == "char.dat":
                if "id" in r:
                    r["id"] = c(r["id"])
                if "sprite_id" in r:
                    r["sprite_id"] = _spr(S, int(r["sprite_id"]))
                if "help_id" in r:
                    r["help_id"] = H.get(int(r["help_id"]), r["help_id"])
                if "color_id" in r:
                    r["color_id"] = c(r["color_id"])
                for k in range(1, 17):
                    f = f"learn{k}_skill"
                    if f in r:
                        r[f] = K.get(int(r[f]), r[f])
                for f in dbpatch.EVILITIES:
                    if f in r:
                        r[f] = EV.get(int(r[f]), r[f])
                if "overload_id" in r:
                    r["overload_id"] = O.get(int(r["overload_id"]), r["overload_id"])
            elif name == "charhelp.dat":
                for f in ("id", "char_id"):
                    if f in r:
                        r[f] = H.get(int(r[f]), r[f])
            elif name == "Quest.dat":
                if "id" in r:
                    r["id"] = Q.get(int(r["id"]), r["id"])
                if "sort_order" in r:
                    r["sort_order"] = QS.get(int(r["sort_order"]), r["sort_order"])
                if int(r.get("reward_type", 0)) in (5, 6) and "reward_value" in r:
                    r["reward_value"] = c(r["reward_value"])
            elif name == "magic.dat":
                if "id" in r:
                    r["id"] = K.get(int(r["id"]), r["id"])
                for k in range(1, 5):
                    if f"user{k}" in r and r[f"user{k}"]:
                        r[f"user{k}"] = c(r[f"user{k}"])
            elif name == "Skill.dat":
                if "id" in r:
                    r["id"] = EV.get(int(r["id"]), r["id"])
                if "owner" in r and r["owner"]:
                    r["owner"] = c(r["owner"])
            elif name == "OverlordSkill.dat":
                old = int(r.get("id", 0))
                if old in O:
                    r["id"] = O[old]
                    if int(r.get("script_id", 0)) == OVL_WRAPPER + old:
                        r["script_id"] = OVL_WRAPPER + O[old]
        mod.save_patch("db", f"{name}.json", p)
    # ---- sprite files (renamed; block ids inside follow)
    if S:
        moves = []
        for f in mod.list_files():
            m = ANM_RE.match(f)
            if not m:
                continue
            n = int(m.group(2))
            new = _spr(S, n)
            if new != n:
                moves.append((f, n, new, (m.group(1) or "")))
        tmp = []
        for f, n, new, folder in moves:
            a = anm.parse(mod.read_file(f))
            for blk in a.blocks:
                if blk.id == n or _spr(S, blk.id) != blk.id:
                    blk.id = _spr(S, blk.id)
            tmp.append((f"{folder}anm{new:05d}.lzs", a.to_bytes()))
            mod.remove_file(f)
        for vp, data in tmp:
            mod.write_file(vp, data)
    # ---- outfits / characters / grips
    from . import outfits
    od = outfits._data(mod)
    if od:
        if "pairs" in od:
            od["pairs"] = [[c(a), c(b)] for a, b in od["pairs"]]
        if "names" in od:
            od["names"] = {str(c(k)): v for k, v in od["names"].items()}
        if "own_sprites" in od:
            od["own_sprites"] = sorted({_spr(S, int(x)) for x in od["own_sprites"]})
        mod.save_patch("outfits", "outfits.json", od)
    es = mod.load_patch("outfits", "event_sheets.json")
    if es:
        mod.save_patch("outfits", "event_sheets.json",
                       {str(c(k)): {e: _spr(S, int(n)) for e, n in v.items()} for k, v in es.items()})
    du = mod.load_patch("outfits", "drpg_units.json")
    if du:
        mod.save_patch("outfits", "drpg_units.json", {k: c(v) for k, v in du.items()})
    _rename(mod, "outfits", r"^(parts_|source_)(\d+)(\.json|\.anm)$", lambda n: _spr(S, n), group=2)
    _rename(mod, "outfits", r"^(face_)(\d+)(\.png)$", c, group=2)
    _rename(mod, "characters", r"^(face_)(\d+)(\.png)$", c, group=2)
    _rename(mod, "grips", r"^()(\d+)(\.json)$", lambda n: _spr(S, n), group=2)
    # ---- skills.json: skills, custom events, effects
    from . import skills
    sk = mod.load_patch("skills", "skills.json")
    if sk:
        ev_map = {}
        for k in list((sk.get("events") or {}).keys()):
            k = int(k)
            if k // 1000 * 1000 in E:
                ev_map[k] = E[k // 1000 * 1000] + k % 1000
        new_events = {}
        for k, text in (sk.get("events") or {}).items():
            t = skills.remap(text, ev_map) if ev_map else text
            for old, new in FX.items():
                t = skills.replace_effect(t, old, new)
            new_events[str(ev_map.get(int(k), int(k)))] = t
        sk["events"] = new_events
        new_sk = {}
        for k, v in (sk.get("skills") or {}).items():
            v = dict(v)
            if "choreography" in v and int(v["choreography"]) in ev_map:
                v["choreography"] = ev_map[int(v["choreography"])]
            k = int(k)
            if skills.is_ovl_key(k):
                new_sk[str(skills.OVL_KEY + O.get(k - skills.OVL_KEY, k - skills.OVL_KEY))] = v
            else:
                new_sk[str(K.get(k, k))] = v
        sk["skills"] = new_sk
        new_fx = {}
        for k, v in (sk.get("effects") or {}).items():
            nk = FX.get(int(k), int(k))
            v = dict(v)
            if nk != int(k) and "textures" in v:
                tex = {}
                for i, fn in v["textures"].items():
                    nfn = fn.replace(f"fx{int(k)}_", f"fx{nk}_")
                    src = os.path.join(mod.patches_dir, "skills", fn)
                    if os.path.exists(src):
                        os.replace(src, os.path.join(mod.patches_dir, "skills", nfn))
                    tex[i] = nfn
                v["textures"] = tex
            new_fx[str(nk)] = v
        sk["effects"] = new_fx
        mod.save_patch("skills", "skills.json", sk)
    # ---- overloads.json (ids, own skill rows) and banner pictures
    od = mod.load_patch("overloads", "overloads.json")
    if od and (O or K):
        new = {}
        for k, e in (od.get("overloads") or {}).items():
            e = dict(e)
            if e.get("skill"):
                e["skill"] = K.get(int(e["skill"]), int(e["skill"]))
            new[str(O.get(int(k), int(k)))] = e
        od["overloads"] = new
        mod.save_patch("overloads", "overloads.json", od)
    if O:
        _rename(mod, "overloads", r"^(banner_)(\d+)(\.png)$", lambda n: O.get(n, n), group=2)
    n = sum(len(v) for v in mapping.values())
    log(f"  {n} id(s) moved: " + "; ".join(f"{k} " + ", ".join(f"{a}->{b}" for a, b in sorted(v.items())[:8])
                                             + (" …" if len(v) > 8 else "") for k, v in mapping.items() if v))


def _rename(mod, handler, pattern, fn, group=2):
    d = os.path.join(mod.patches_dir, handler)
    if not os.path.isdir(d):
        return
    rx = re.compile(pattern)
    moves = []
    for name in os.listdir(d):
        m = rx.match(name)
        if m:
            n = int(m.group(group))
            new = fn(n)
            if new != n:
                moves.append((name, f"{m.group(1)}{new}{m.group(3)}"))
    tmp = []
    for a, b in moves:                      # two steps: a chain of renames never overwrites
        t = a + ".moving"
        os.replace(os.path.join(d, a), os.path.join(d, t))
        tmp.append((t, b))
    for t, b in tmp:
        os.replace(os.path.join(d, t), os.path.join(d, b))


# ------------------------------------------------------------------------------------------------ import
def read_package(path):
    """(top folder name, mod.json dict) of a package zip, checking its layout"""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n and not n.endswith("/")]
        top = {n.split("/")[0] for n in names}
        if len(top) != 1:
            raise ValueError("the zip must hold exactly one mod folder")
        t = top.pop()
        for n in names:
            if n.startswith("/") or ".." in n.split("/") or ":" in n:
                raise ValueError(f"unsafe path in the zip: {n}")
        try:
            meta = json.loads(z.read(f"{t}/mod.json").decode("utf-8"))
        except KeyError:
            meta = {}
    return t, meta


def import_package(path, mods_dir, fs, state_dir, log=print):
    """install a shared mod (see the module doc) -> dict(mod_id, update, moved, backup)"""
    from .modsys import Mod, ModManager
    top, meta = read_package(path)
    mm = ModManager(os.path.dirname(mods_dir.rstrip("/\\")))
    allmods = [m for m in mm.all_mods()]
    uid = meta.get("uid")
    old = next((m for m in allmods if uid and m.meta.get("uid") == uid), None)
    others = [m for m in allmods if old is None or m.id != old.id]
    work = tempfile.mkdtemp(prefix="d5import_")
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(work)
        pkg = Mod(os.path.join(work, top))
        keep = (old.meta.get("local_ids") if old else None) or {}
        mapping = plan(pkg, others, fs, keep)
        from . import database
        apply(pkg, mapping, log, vanilla_char=database.load_table("char.dat", fs.read(DB + "char.dat")))
        local = {k: {str(a): b for a, b in v.items()} for k, v in mapping.items() if v}
        pkg.meta.pop("local_ids", None)
        if local:
            pkg.meta["local_ids"] = local
        pkg.save_meta()
        backup = None
        enabled = mm.load_order()
        if old is not None:
            os.makedirs(os.path.join(state_dir, "mod_backups"), exist_ok=True)
            backup = os.path.join(state_dir, "mod_backups",
                                  f"{old.id}_v{old.meta.get('version', '')}_{time.strftime('%Y%m%d_%H%M%S')}.zip")
            with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _, files in os.walk(old.folder):
                    for fn in files:
                        full = os.path.join(root, fn)
                        z.write(full, os.path.join(old.id, os.path.relpath(full, old.folder)))
            target = old.folder
            shutil.rmtree(target)
            shutil.copytree(pkg.folder, target)
            mod_id = old.id
        else:
            mod_id = _free_folder(mods_dir, top)
            shutil.copytree(pkg.folder, os.path.join(mods_dir, mod_id))
            if mod_id not in enabled:
                mm.set_enabled(mod_id, True)
        log(f"{'updated' if old else 'imported'} {meta.get('name', mod_id)} v{meta.get('version', '?')}"
            + (f" (the old version is kept in {backup})" if backup else ""))
        return {"mod_id": mod_id, "update": old is not None, "moved": local, "backup": backup}
    finally:
        shutil.rmtree(work, ignore_errors=True)
