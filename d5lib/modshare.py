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
  * a package with game-program patches (patches/exe) is the exception: it comes in OFF unless the player approves it
    (exe_consent), and a decline switches an installed update off; the approval is bound to the patch bytes and
    settings and kept outside the mod (d5lib.exebytes).
  * other mods are never changed.

Kinds of ids (what can clash between two mods made on different PCs):
    class    unique class ids below 1000 (new characters, outfit slots): char.dat rows, outfit pairs, faces, quests'
             recruit rewards, skills' users.  A DRPG costume row is a class id ABOVE 1000 that is not a generic
             family: it is declared in outfits.json "colours" and moves like any other class claim.
    sprite   new sprite numbers, in groups of ten (anm N .. N+9 and the portraits 10000 + N ...): anm files and the
             blocks inside, char.dat sprite_id, the DECLARED COLOUR of a costume (its art number N, which is not
             its class id), outfit own sprites / parts / sources / event sheets, weapon grips
    icon     texturedatabase rows a pack brings for its assigned small list icons, as a 48/64 px pair (the 64 px
             row is the 48 px row + 817).  Two packages built from the same vanilla table claim the same rows, so
             a moved pack moves both rows of every pair by the same block.
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

from . import dbpatch, lzs, skills

DB = "Database/Database_0.dat/"
KINDS = ("class", "sprite", "art", "icon", "help", "quest", "slot", "skill", "evility", "event", "effect", "overload")
ANM_RE = re.compile(r"^(.*/)?anm(\d{5})\.lzs$", re.I)
ICON_64 = 817                    # the 64 px texturedatabase row = the 48 px row + 817 (d5lib/outfits.py)
ICON_BLOCK = 2 * ICON_64         # rows come in blocks of 817 48 px rows, then their 817 64 px rows
TEXPATCH = "texturedatabase.dat"
JUNK = (".DS_Store", "Thumbs.db", "desktop.ini")
MOD_CHOREO_BASE, CHOREO_MAX = 15900000, 16000000


# ------------------------------------------------------------------------------------------------ identity
def ensure_uid(mod):
    """the mod's uid (made and saved on first use)"""
    if not mod.meta.get("uid"):
        mod.meta["uid"] = uuid.uuid4().hex
        mod.save_meta()
    return mod.meta["uid"]


def export_package(mod, path, version=None, author=None, copy=False):
    """zip the mod for sharing (mod.json gets a uid; version / author if given).  -> path
    A mod imported here whose ids were moved (local_ids) is not shared again under its identity: its files carry this
    PC's ids, which would not match the original's on a third PC.  Share the original package, or make your own
    version (derive) and share that.  copy: for another profile of this PC (copy_to_profile), no such check."""
    if mod.meta.get("local_ids") and not copy:
        raise ValueError(f"'{mod.name}' came from someone else and some of its ids were moved on this PC, so it can't "
                         "be shared again as the same mod. Share their original package instead, or right-click › "
                         "Make my own version and share that.")
    ensure_uid(mod)
    if version:
        mod.meta["version"] = version
    if author:
        mod.meta["author"] = author
    mod.save_meta()
    return write_package(mod, package_meta(mod.meta), path)


def package_meta(meta):
    """the mod.json a package carries: this PC's local_ids / profile left out, the export time added"""
    meta = {k: v for k, v in meta.items() if k not in ("local_ids", "profile")}
    meta["exported"] = time.strftime("%Y-%m-%d %H:%M")
    return meta


def write_package(mod, meta, path):
    """zip mod's folder with `meta` as its mod.json (the mod itself is not changed) -> path"""
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{mod.id}/mod.json", json.dumps(meta, indent=2, ensure_ascii=False))
        for root, _, files in os.walk(mod.folder):
            for fn in files:
                if fn in JUNK or fn.startswith("._"):
                    continue                      # Finder / Explorer droppings: a package may not hold them
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


def icon_claims(mod):
    """{48 px texturedatabase row: 64 px row} this pack claims for its assigned list icons, from
    outfits.json "icons" ({class id: [48 px row, 64 px row]}, written by the costume builder) and from a
    texturedatabase patch the pack carries.  A DRPG costume's icon is ASSIGNED (its colour is above the game's
    derived range), so the pair is a typed claim like any other id and must move with the pack."""
    pair = {}
    icons = (mod.load_patch("outfits", "outfits.json") or {}).get("icons") or {}
    for v in icons.values():
        try:
            r48, r64 = [int(x) for x in (v or [])][:2]
        except (TypeError, ValueError):
            raise ValueError(f"'{mod.name}': list-icon declaration {v!r} is not a [48 px row, 64 px row] pair")
        pair[r48] = r64
    known64 = set(pair.values())
    for r in _added(mod, TEXPATCH):
        try:
            i = int(r.get("id", 0))
        except (TypeError, ValueError):
            continue
        if i > 0 and i not in known64:          # a declared 64 px row is the pair's second half, not another pair
            pair.setdefault(i, i + ICON_64)
    return pair


def _declared(mod):
    """{costume class id: its declared colour (art number N)} -- the DRPG costume declaration."""
    from . import outfits
    return outfits.load_colours(mod)


DUMMY_ROWS = (470, 480, 490, 950, 960, 970, 980, 990)     # the game's unused unique rows (d5lib.slots)


def ids_of(mod, vanilla_char_ids=(), vanilla_sprites=(), vanilla_by_index=()):
    """{kind: set of ids} a mod brings (new ones only: rows it adds, the reserved dummy rows it fills in, new sprite
    numbers, its custom events ...)"""
    from . import outfits
    out = {k: set() for k in KINDS}
    fams = class_families(mod)                 # a generic class's own rows keep their family (see the docstring)
    declared = _declared(mod)                  # {costume class id: its own art number N}
    for r in _added(mod, "char.dat"):
        if int(r.get("id", 0)) > 0 and int(r["id"]) // 10 * 10 not in fams:
            out["class"].add(int(r["id"]))
    for idx in (_patch(mod, "char.dat").get("rows") or {}):
        i = int(idx)
        if i < len(vanilla_by_index) and vanilla_by_index[i] in DUMMY_ROWS:
            out["class"].add(vanilla_by_index[i])
    o = outfits._data(mod)
    for a, b in o.get("pairs", []):
        # a declared costume row is a class claim whatever its id: it is one look, not a generic family
        if (int(b) < 1000 or int(b) in declared) and int(b) not in vanilla_char_ids:
            out["class"].add(int(b))
    for c, n in declared.items():
        # a costume's declared colour IS its art number: it is an ART claim (group of ten), not a class and not a
        # sprite number -- _spr reads everything from 10000 up as a portrait, which art N >= 10000 is not
        if int(n) not in vanilla_sprites:
            out["art"].add(int(n) // 10 * 10)
    for r48 in icon_claims(mod):
        out["icon"].add(int(r48))
    declared_art = set(declared.values())
    for f in mod.list_files():
        m = ANM_RE.match(f)
        if m:
            n = int(m.group(2))
            if n // 10 * 10 in declared_art or (n - 10000) // 10 * 10 in declared_art:
                # a declared look's own art group (anm N .. N+9) or its portraits (anm 10000 + N ..): both follow the
                # declaration.  The old n >= 10000 -> portrait rule would read art 14000 as "portrait of 4000".
                continue
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


def _vanilla_icons(fs):
    """every texturedatabase row id the game itself has: a new list icon goes after the last one"""
    from . import database
    try:
        t = database.load_table(TEXPATCH, fs.read(DB + TEXPATCH))
    except Exception:
        return set()
    ids = [int(r["id"]) for r in t.rows]
    return set(range(0, (max(ids) if ids else 0) + 1))


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
    _icon_pairs = icon_claims(pkg_mod)
    used = {k: set() for k in KINDS}
    for m in others:
        for k, v in ids_of(m, vchar, vspr, by_index).items():
            used[k] |= v
    used["icon"] |= _vanilla_icons(fs)
    # the game's own ids
    used["sprite"] |= {n // 10 * 10 for n in vspr if n < 10000} | {(n - 10000) // 10 * 10 for n in vspr if n >= 10000}
    used["art"] |= used["sprite"]
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
            if kind == "icon":
                # the pair moves as one: the 64 px row keeps the 817 offset of the 48 px row
                r64 = _icon_pairs.get(i, i + ICON_64)
                mapping[kind][r64] = new + (r64 - i)
                taken[kind].add(new + (r64 - i))
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
    if kind == "art":                                    # a declared costume's art group (N .. N+9, portraits 10000 + N)
        n = 9000
        while n in taken or n + 10000 > 32767:
            n += 10
        return n
    if kind == "icon":                                   # a list-icon pair: the 48 px row and its +817 row
        b = i
        while b in taken or b + ICON_64 in taken:
            b += 1
        return b
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


def _art(m, n):
    """declared art number n moved by the declared-art map `m` ({art group: new group}), exact or by its group;
    portraits (10000 + n) follow the same move.  Unlike _spr this never mistakes a high art number for a portrait."""
    if not m:
        return n
    for cand in (n, n // 10 * 10):
        if cand in m:
            return m[cand] + (n - cand)
    if n >= 10000:
        b = n - 10000
        for cand in (b, b // 10 * 10):
            if cand in m:
                return m[cand] + (b - cand) + 10000
    return n


def apply(mod, mapping, log=print, vanilla_char=None):
    """apply() as a transaction: either every dependent reference moves, or the folder is left exactly as it was"""
    snap = _snapshot(mod)
    try:
        _apply(mod, mapping, log=log, vanilla_char=vanilla_char)
    except BaseException:
        _restore(mod, snap)
        raise


def _apply(mod, mapping, log=print, vanilla_char=None):
    """rewrite the mod's files and patches with the moved ids (mapping from plan()).  vanilla_char: the game's
    char.dat (needed when a filled-in dummy row moves: its edit becomes a new row)"""
    from . import anm
    C, S, H = mapping.get("class", {}), mapping.get("sprite", {}), mapping.get("help", {})
    Q, QS, K = mapping.get("quest", {}), mapping.get("slot", {}), mapping.get("skill", {})
    EV, E, FX = mapping.get("evility", {}), mapping.get("event", {}), mapping.get("effect", {})
    A = mapping.get("art", {})
    I = mapping.get("icon", {})
    O = mapping.get("overload", {})
    declared = _declared(mod)
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
                old_id = int(r["id"]) if "id" in r else None
                if "id" in r:
                    r["id"] = c(r["id"])
                if "sprite_id" in r:
                    r["sprite_id"] = _art(A, int(r["sprite_id"])) if old_id in declared else _spr(S, int(r["sprite_id"]))
                if "help_id" in r:
                    r["help_id"] = H.get(int(r["help_id"]), r["help_id"])
                if "color_id" in r:
                    # a declared costume's colour is its ART number: it moves with the art, never with its class id
                    r["color_id"] = _art(A, int(r["color_id"])) if old_id in declared else c(r["color_id"])
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
    # ---- sprite / declared art files (renamed; block ids inside follow)
    if S or A:
        moves = []
        for f in mod.list_files():
            m = ANM_RE.match(f)
            if not m:
                continue
            n = int(m.group(2))
            new = _art(A, n) if (n // 10 * 10 in A or (n - 10000) // 10 * 10 in A) else _spr(S, n)
            if new != n:
                moves.append((f, n, new, (m.group(1) or "")))
        tmp = []
        for f, n, new, folder in moves:
            raw = mod.read_file(f)
            packed = raw[:4] in (b"dat\0", b"pac\0") and int.from_bytes(raw[4:8], "little") != len(raw)
            a = anm.parse(lzs.decompress(raw) if packed else raw)
            for blk in a.blocks:
                if blk.id == n or _spr(S, blk.id) != blk.id:
                    blk.id = _spr(S, blk.id)
            out = a.to_bytes()
            if packed:
                out = anm.lzs_compress(out, raw[:4])          # the importers store anm files LZS-compressed: keep it so
            tmp.append((f"{folder}anm{new:05d}.lzs", out))
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
            od["own_sprites"] = sorted({_art(A, int(x)) for x in od["own_sprites"]})
        if "colours" in od:
            # declared costume colours are art numbers: the key is the class id, the value the art group
            od["colours"] = {str(c(k)): _art(A, int(v)) for k, v in od["colours"].items()}
        if "bodies" in od:
            od["bodies"] = {str(c(k)): _art(A, int(v)) if int(k) in declared else _spr(S, int(v))
                            for k, v in od["bodies"].items()}
        if "icons" in od:            # a list-icon pair moves as a pair: [48 px row, 64 px row] both rewritten, never one of them
            od["icons"] = {str(c(k)): [I.get(int(a), int(a)), I.get(int(b), int(b))] for k, (a, b) in od["icons"].items()}
        if "portraits" in od:
            od["portraits"] = {str(c(k)): v for k, v in od["portraits"].items()}
        mod.save_patch("outfits", "outfits.json", od)
    if I:
        tp = _patch(mod, TEXPATCH)
        if tp.get("added"):
            for r in tp["added"]:
                if isinstance(r, dict) and "id" in r:
                    r["id"] = I.get(int(r["id"]), int(r["id"]))
            mod.save_patch("db", f"{TEXPATCH}.json", tp)
    es = mod.load_patch("outfits", "event_sheets.json")
    if es:
        mod.save_patch("outfits", "event_sheets.json",
                       {str(c(k)): {e: _spr(S, int(n)) for e, n in v.items()} for k, v in es.items()})
    du = mod.load_patch("outfits", "drpg_units.json")
    if du:
        mod.save_patch("outfits", "drpg_units.json", {k: c(v) for k, v in du.items()})
    _rename(mod, "outfits", r"^(parts_|source_)(\d+)(\.json|\.anm)$", lambda n: _art(A, n), group=2)
    _rename(mod, "outfits", r"^(face_)(\d+)(\.png)$", c, group=2)
    _rename(mod, "characters", r"^(face_)(\d+)(\.png)$", c, group=2)
    # portrait / cut-in keys are art numbers (portrait_<10000 + N>), not class ids
    _rename(mod, "characters", r"^(portrait_)(\d+)(\.json)$", lambda n: _art(A, n), group=2)
    _rename(mod, "outfits", r"^(portrait_)(\d+)(\.json)$", lambda n: _art(A, n), group=2)
    _rename(mod, "grips", r"^()(\d+)(\.json)$", lambda n: _art(A, n), group=2)
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


def _snapshot(mod):
    """every file in the mod folder, so a failed apply can put it back exactly"""
    snap = {}
    for root, _, files in os.walk(mod.folder):
        for fn in files:
            p = os.path.join(root, fn)
            with open(p, "rb") as f:
                snap[os.path.relpath(p, mod.folder)] = f.read()
    return snap


def _restore(mod, snap):
    for root, _, files in os.walk(mod.folder, topdown=False):
        for fn in files:
            p = os.path.join(root, fn)
            if os.path.relpath(p, mod.folder) not in snap:
                os.remove(p)
    for rel, data in snap.items():
        p = os.path.join(mod.folder, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)


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


# ------------------------------------------------------------------------------------------------ claims / guard
class ClaimError(ValueError):
    """a pack's own declaration points at art or an id the pack does not carry"""


class DisableBlocked(ValueError):
    """switching this mod off would leave a save or another mod pointing at ids only this mod defines"""


def validate_claims(mod):
    """Every claim a declared costume makes must resolve INSIDE the pack before anything is rewritten: the pair, the
    art at its declared colour N, and (when declared) the list-icon pair.  Raises ClaimError naming the first gap, so
    a share/import fails with nothing moved rather than half a costume."""
    from . import outfits
    data = outfits._data(mod)
    declared = _declared(mod)
    if not declared:
        return []
    pairs = {int(b) for _, b in data.get("pairs") or []}
    anms = set()
    for f in mod.list_files():
        m = ANM_RE.match(f)
        if m:
            anms.add(int(m.group(2)))          # raw numbers: anm N is the look's art, anm N+10000 its portrait
    icons = icon_claims(mod)
    problems = []
    for cid, n in sorted(declared.items()):
        if int(cid) not in pairs:
            problems.append(f"look {cid} declares colour {n} but has no outfit pair")
        if int(n) not in anms:
            problems.append(f"look {cid} declares colour {n} but the pack carries no anm {n}")
        cell = (data.get("icons") or {}).get(str(cid))
        if cell:
            r48 = int(cell[0])
            if r48 not in icons or icons[r48] != int(cell[1]):
                problems.append(f"look {cid} declares list icon {cell} but the pack carries no such icon rows")
    if problems:
        raise ClaimError(f"'{mod.name}': " + "; ".join(problems))
    return []


def disable_blockers(mod, others, fs, saves_root=None, log=None):
    """Why switching `mod` off would leave dangling rows or claims:
    [text] -- a unit in a save wears one of its classes, or an enabled mod references one of its ids.
    Empty list = safe to disable."""
    from . import database
    van = database.load_table("char.dat", fs.read(DB + "char.dat"))
    vchar = set(int(r["id"]) for r in van.rows)
    from . import sprites
    mine = ids_of(mod, vchar, sprites.used_sprite_numbers(fs), [int(r["id"]) for r in van.rows])
    out = []
    if saves_root:
        from . import savegame
        for path, save, army, reserve, _quests in savegame.find(mine["class"], root=saves_root):
            for u in list(army) + list(reserve):
                out.append(f"{os.path.basename(path)}: {u.name} is class {u.cls} from '{mod.name}'")
    for m in others:
        refs = _references(m, mine)
        if refs:
            out.append(f"'{m.name}' uses {', '.join(sorted(refs))} from '{mod.name}'")
    if log and out:
        for line in out:
            log(f"  {line}")
    return out


def _references(mod, mine):
    """the ids of `mine` another mod's patches point at (outfit pairs, team rewards, skills' users, drpg units)"""
    from . import outfits
    hit = set()
    for a, b in outfits._data(mod).get("pairs") or []:
        for v in (int(a), int(b)):
            if v in mine["class"]:
                hit.add(f"outfit class {v}")
    for r in _added(mod, "Quest.dat"):
        if int(r.get("reward_type", 0)) in (5, 6) and int(r.get("reward_value", 0)) in mine["class"]:
            hit.add(f"team reward {r['reward_value']}")
    for r in _added(mod, "magic.dat"):
        for k in range(1, 5):
            if r.get(f"user{k}") and int(r[f"user{k}"]) in mine["class"]:
                hit.add(f"skill {r.get('id')} user {r[f'user{k}']}")
    du = mod.load_patch("outfits", "drpg_units.json") or {}
    if any(int(v) in mine["class"] for v in du.values()):
        hit.add("drpg unit map")
    return hit


def disable(mod, manager, fs, saves_root=None, log=print):
    """Switch `mod` off, or refuse (DisableBlocked) when a save wears its classes or another enabled mod uses its ids.
    Never writes a half state: the blocker list is computed before load_order changes."""
    others = [m for m in manager.enabled_mods() if m.id != mod.id]
    blockers = disable_blockers(mod, others, fs, saves_root=saves_root)
    if blockers:
        raise DisableBlocked(f"'{mod.name}' can't be switched off: " + "; ".join(blockers)
                             + " -- switch those outfits back in game or remove them from the save first")
    manager.set_enabled(mod.id, False)
    log(f"switched off {mod.name}")
    return True


def copy_to_profile(mod, mods_dir, fs, state_dir, log=print):
    """Import from another profile: a copy of `mod` (a mod the active profile doesn't see) in the active profile, as a
    shared package comes in: ids that clash with this profile's mods are moved.  -> import_package's dict"""
    work = tempfile.mkdtemp(prefix="d5copy_")
    try:
        pkg = export_package(mod, os.path.join(work, f"{mod.id}.zip"), copy=True)
        return import_package(pkg, mods_dir, fs, state_dir, log=log)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ import
def read_package(path):
    """(top folder name, mod.json dict) of a package zip, after every safety check (modindex.check_zip: one mod
    folder, plain paths, only the file types mods use, no program files for the game folder, size limits)"""
    from .modindex import check_zip
    return check_zip(path)


def import_package(path, mods_dir, fs, state_dir, log=print, exe_consent=None):
    """install a shared mod (see the module doc) -> dict(mod_id, update, moved, backup, exe, exe_approved).
    A package with game-program patches (patches/exe) comes in OFF and unapproved unless exe_consent(summary line)
    returns True (asked after the package passed its checks, before anything is copied); a declined update of an
    installed mod is switched off too."""
    from .modsys import Mod, ModManager
    from . import exebytes
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
        validate_claims(pkg)                 # a claim the pack doesn't carry fails before anything moves
        keep = (old.meta.get("local_ids") if old else None) or {}
        mapping = plan(pkg, others, fs, keep)
        exe_line = exebytes.describe(pkg) or (f"{pkg.name}: {exebytes.LABEL}" if exebytes.carries(pkg) else "")
        approved = False
        if exebytes.carries(pkg):
            approved = bool(exe_consent and exe_consent(exe_line))
        from . import database
        apply(pkg, mapping, log, vanilla_char=database.load_table("char.dat", fs.read(DB + "char.dat")))
        local = {k: {str(a): b for a, b in v.items()} for k, v in mapping.items() if v}
        pkg.meta.pop("local_ids", None)
        if local:
            pkg.meta["local_ids"] = local
        mm.adopt(pkg)                       # the profile the kit works on owns it (a separate one), or it is shared
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
        if exe_line:                            # the approval is on file before the mod can be switched on
            final = Mod(os.path.join(mods_dir, mod_id))
            if approved:
                exebytes.approve(final)
            else:
                exebytes.revoke(final)
            log(f"  {exe_line} ({'approved' if approved else 'NOT approved: the mod stays off until you approve it'})")
            mm.set_enabled(mod_id, approved)    # Yes turns it on (also after an earlier No), No turns it off
        elif old is None and mod_id not in enabled:
            mm.set_enabled(mod_id, True)
        is_on = mod_id in mm.load_order()
        log(f"{'updated' if old else 'imported'} {meta.get('name', mod_id)} v{meta.get('version', '?')}"
            + (f" (the old version is kept in {backup})" if backup else "")
            + ("" if is_on or not exe_line else " (switched off: its game-program patches are not approved)"))
        return {"mod_id": mod_id, "update": old is not None, "moved": local, "backup": backup,
                "exe": exe_line, "exe_approved": approved, "enabled": is_on}
    finally:
        shutil.rmtree(work, ignore_errors=True)
