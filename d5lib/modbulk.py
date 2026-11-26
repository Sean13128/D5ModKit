"""Share many mods at once: every mod as its own package, in one folder per game, and the folder back in.

    export_all(mods, out_dir, ...)   -> out_dir/<Game>/<mod name>.zip + <Game>/manifest.json + README.txt
    import_folder(folder, mods_dir, fs, state_dir, ...)   every zip under the folder, dependencies first

Each zip is an ordinary modshare package (import it alone with Home > Import / update from .zip).  The bulk layer adds:

  * Source mods are never changed.  Most mods made by the kit's importers have no stored uid, and modshare.export_package
    would write one into mod.json.  Here a mod without a uid gets a DETERMINISTIC one (uuid5 of its folder id), used only
    in the package; the manifest says "uid_stored": false.  Two PCs that export the same-named generated mod (for
    example D4_Class_2120) therefore share an identity, and importing one over the other is an update (the old
    folder is kept as a zip in state/mod_backups).  `stamp_uids=True` (CLI --stamp-uids) writes the uid back to the
    source mod.json instead.
  * "requires" lists mod folder ids, which are only names on one PC.  Each package also carries "requires_uid" (the
    uid of each required mod, in the same order).  import_package gives a new mod a free folder name when its own is
    taken (X becomes X_2); import_folder then re-points the "requires" of every imported mod to the folder that holds
    the required uid.
  * A mod import_package would refuse (it came from someone else with moved ids: local_ids) is skipped and listed.
  * A mod outside the chosen games that a chosen mod requires is exported too (closure), flagged "dependency".
"""
import fnmatch
import hashlib
import json
import os
import re
import time
import uuid

from . import modshare

GAMES = ("D1C", "D4", "DD2", "DRPG", "Overlord", "Other")
PREFIXES = (("D1C_", "D1C"), ("D4_", "D4"), ("DD2_", "DD2"), ("DRPG_", "DRPG"), ("Overlord", "Overlord"))
UID_NS = uuid.UUID("5d5b0b0b-6d6f-4d6b-8d35-0d5b17c0de01")
PACK_GAME = {"d1c": "D1C", "d4": "D4", "dd2": "DD2", "drpg": "DRPG", "overlord": "Overlord"}


def load_pack_games(mods_dir):
    """{mod id: game} from mods/packs.json (pack id d4-classes -> D4 ...)"""
    out = {}
    try:
        with open(os.path.join(mods_dir, "packs.json"), encoding="utf-8") as f:
            packs = json.load(f).get("packs") or []
    except (OSError, ValueError):
        return out
    for p in packs:
        g = PACK_GAME.get(str(p.get("id", "")).split("-")[0].lower())
        for m in p.get("members") or []:
            if g:
                out.setdefault(m, g)
    return out


def game_of(mod, pack_games=None):
    """"D1C" | "D4" | "DD2" | "DRPG" | "Overlord" | "Other": folder prefix, else packs.json, else source_import"""
    for pre, g in PREFIXES:
        if mod.id.startswith(pre):
            return g
    g = (pack_games or {}).get(mod.id)
    if g:
        return g
    si = mod.meta.get("source_import")
    if isinstance(si, dict):
        ident = si.get("identity")
        tag = (ident.get("source") if isinstance(ident, dict) else None) or si.get("source_game")
        if isinstance(tag, str) and tag.lower() in PACK_GAME:
            return PACK_GAME[tag.lower()]
    return "Other"


def uid_of(mod):
    """(uid, stored): the mod's own uid, else the deterministic one for its folder id"""
    u = mod.meta.get("uid")
    return (u, True) if u else (uuid.uuid5(UID_NS, mod.id).hex, False)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _matches(mod_id, patterns):
    return not patterns or any(fnmatch.fnmatchcase(mod_id, p) for p in patterns)


_BAD_FN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def file_name(mod, taken):
    """zip file name from the mod's display name ("Thursday (D1C)"), not its folder id: the part before an " — "
    remark, characters Windows/macOS refuse replaced; the folder id is added when the name is empty or already used
    in this game folder.  `taken`: lower-case names used so far (updated)."""
    name = (mod.meta.get("name") or "").split(" \u2014 ")[0]
    name = re.sub(r"\s+", " ", _BAD_FN.sub("_", name)).strip(" .")[:100]
    fn = f"{name}.zip" if name else f"{mod.id}.zip"
    if fn.lower() in taken:
        fn = f"{name} [{mod.id}].zip"
    taken.add(fn.lower())
    return fn


def export_all(mods, out_dir, games=None, only_enabled=False, author=None, log=print, only=None, stamp_uids=False,
               enabled_ids=None, closure=True, pack_games=None):
    """Write every chosen mod as out_dir/<Game>/<mod name>.zip (file_name) with a manifest per game folder -> report dict
    {"exported": [entry], "skipped": [{"id", "game", "reason"}], "games": {game: count}, "uid_unstored": n}
    mods: Mod list.  games: only these games (None = all).  only: fnmatch patterns on mod ids.  only_enabled needs
    enabled_ids.  closure: also export mods a chosen mod requires that the filters left out."""
    by_id = {m.id: m for m in mods}
    pack_games = pack_games or {}
    games = [g for g in games] if games else None
    for g in games or ():
        if g not in GAMES:
            raise ValueError(f"unknown game '{g}' (one of {', '.join(GAMES)})")
    chosen = []
    for m in mods:
        if games and game_of(m, pack_games) not in games:
            continue
        if only_enabled and m.id not in (enabled_ids or ()):
            continue
        if not _matches(m.id, only):
            continue
        chosen.append(m)
    deps = set()
    if closure:
        todo = list(chosen)
        have = {m.id for m in chosen}
        while todo:
            item = todo.pop()
            for rid in (item.meta.get("requires") or []) + (item.meta.get("needs") or []):
                if rid in by_id and rid not in have:
                    have.add(rid)
                    deps.add(rid)
                    chosen.append(by_id[rid])
                    todo.append(by_id[rid])
    uids = {m.id: uid_of(m)[0] for m in mods}
    report = {"exported": [], "skipped": [], "games": {}, "uid_unstored": 0}
    skipped_ids = set()
    exported_ids = set()
    for m in chosen:
        if m.meta.get("local_ids"):
            skipped_ids.add(m.id)
    os.makedirs(out_dir, exist_ok=True)
    per_game = {}
    names = {}                                   # game -> zip names used
    for i, m in enumerate(chosen, 1):
        g = game_of(m, pack_games)
        if m.id in skipped_ids:
            report["skipped"].append({"id": m.id, "game": g, "reason":
                                      "came from someone else with ids moved on this PC (local_ids); share their original"})
            log(f"[{i}/{len(chosen)}] skip {m.id}: has local_ids")
            continue
        uid, stored = uid_of(m)
        if stamp_uids and not stored:
            m.meta["uid"] = uid
            m.save_meta()
            stored = True
        meta = modshare.package_meta(m.meta)
        meta["uid"] = uid
        if author:
            meta["author"] = author
        req = [r for r in (m.meta.get("requires") or []) if isinstance(r, str)]
        if req:
            meta["requires_uid"] = [uids.get(r) for r in req]
        gdir = os.path.join(out_dir, g)
        os.makedirs(gdir, exist_ok=True)
        fn = file_name(m, names.setdefault(g, set()))
        path = os.path.join(gdir, fn)
        try:
            modshare.write_package(m, meta, path)
        except Exception as e:                    # one mod must not stop the rest
            report["skipped"].append({"id": m.id, "game": g, "reason": f"export failed: {e}"})
            log(f"[{i}/{len(chosen)}] FAILED {m.id}: {e}")
            continue
        entry = {"id": m.id, "game": g, "name": m.name, "uid": uid, "uid_stored": stored,
                 "version": meta.get("version", ""), "author": meta.get("author", ""), "requires": req,
                 "requires_uid": meta.get("requires_uid", []), "file": fn,
                 "size": os.path.getsize(path), "sha256": _sha256(path)}
        if m.id in deps:
            entry["dependency"] = True
        if not stored:
            report["uid_unstored"] += 1
        per_game.setdefault(g, []).append(entry)
        report["exported"].append(entry)
        exported_ids.add(m.id)
        report["games"][g] = report["games"].get(g, 0) + 1
        log(f"[{i}/{len(chosen)}] {g}/{fn} ({entry['size'] >> 10} KB)")
    # notes about requirements that did not make it into the export
    for e in report["exported"]:
        miss = [r for r in e["requires"] if r not in exported_ids]
        other = [r for r in e["requires"] if r in exported_ids and next(
            x["game"] for x in report["exported"] if x["id"] == r) != e["game"]]
        if miss:
            e["requires_not_exported"] = miss
        if other:
            e["requires_other_game"] = other
    for g, entries in per_game.items():
        skipped = [s for s in report["skipped"] if s["game"] == g]
        with open(os.path.join(out_dir, g, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"game": g, "exported": time.strftime("%Y-%m-%d %H:%M"), "mods": entries, "skipped": skipped},
                      f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README)
    return report


README = """D5 Mod Kit mods, one zip per mod, one folder per game (D1C, D4, DD2, DRPG, Overlord, Other).

To install in your own D5 Mod Kit
  * Command line:   python tools/share_bulk.py import THIS_FOLDER
  * Or in the kit:  Home > More > Import folder...  and choose this folder.
  * One mod only:   Home > More > Import / update from .zip...  (any single zip here)
It imports every zip in every game subfolder, mods that others need first.  A mod that is already installed
(same uid) is updated and its old folder is kept as a zip in state/mod_backups.  Ids that clash with your own mods
(characters, sprites, skills ...) are moved, never your mods'.  Mods that require another mod are re-pointed if the
required mod had to get a different folder name.  Then Install to put the mods into the game.

Each game folder has manifest.json: id, name, uid, version, author, requires, size and sha256 of every zip, and the
mods that were skipped.  "uid_stored": false means the source mod had no uid yet; the uid is derived from its folder
name, so another PC exporting the same generated mod gets the same identity.
"""


# ------------------------------------------------------------------------------------------------ import
def _scan_zips(folder):
    out = []
    for root, _, files in os.walk(folder):
        out += [os.path.join(root, f) for f in files if f.lower().endswith(".zip")]
    return sorted(out)


def _order(items):
    """items: [(path, top, meta)] -> the same, mods that others require first (a cycle keeps its file order)"""
    by_top = {t: i for i, (_, t, _) in enumerate(items)}
    by_uid = {m.get("uid"): i for i, (_, _, m) in enumerate(items) if m.get("uid")}

    def deps(i):
        m = items[i][2]
        ru = m.get("requires_uid") or []
        out = []
        for k, rid in enumerate(m.get("requires") or []):
            j = by_uid.get(ru[k]) if k < len(ru) and ru[k] else None
            if j is None:
                j = by_top.get(rid)
            if j is not None and j != i:
                out.append(j)
        return out

    done, seq, state = set(), [], {}

    def visit(i):
        if state.get(i):
            return
        state[i] = 1
        for j in deps(i):
            visit(j)
        if i not in done:
            done.add(i)
            seq.append(items[i])

    for i in range(len(items)):
        visit(i)
    return seq


def _uids_in(mods_dir):
    """{uid: folder id} of the mods in mods_dir (stored uids)"""
    out = {}
    for d in sorted(os.listdir(mods_dir)):
        mj = os.path.join(mods_dir, d, "mod.json")
        try:
            with open(mj, encoding="utf-8") as f:
                u = json.load(f).get("uid")
        except (OSError, ValueError):
            continue
        if u:
            out[u] = d
    return out


def import_folder(folder, mods_dir, fs, state_dir, log=print, games=None):
    """Import every package zip under `folder` (all game subfolders), dependencies first, then re-point "requires".
    One bad package does not stop the rest.  -> {"imported": [id], "updated": [id], "moved": {id: moved ids},
    "renamed": {package id: folder id}, "repointed": {id: {old: new}}, "missing_requires": {id: [required id]},
    "failed": [{"file", "reason"}]}"""
    summary = {"imported": [], "updated": [], "moved": {}, "renamed": {}, "repointed": {}, "missing_requires": {},
               "failed": []}
    items = []
    for path in _scan_zips(folder):
        try:
            top, meta = modshare.read_package(path)
        except Exception as e:
            summary["failed"].append({"file": path, "reason": f"not a mod package: {e}"})
            log(f"skip {path}: {e}")
            continue
        if games and os.path.basename(os.path.dirname(path)) not in games:
            continue
        items.append((path, top, meta))
    results = {}                                    # package uid or top -> final folder id
    for n, (path, top, meta) in enumerate(_order(items), 1):
        log(f"[{n}/{len(items)}] {top}")
        try:
            res = modshare.import_package(path, mods_dir, fs, state_dir, log=log)
        except Exception as e:
            summary["failed"].append({"file": path, "reason": str(e)})
            log(f"  FAILED {top}: {e}")
            continue
        mid = res["mod_id"]
        (summary["updated"] if res["update"] else summary["imported"]).append(mid)
        if res.get("exe") and not res.get("exe_approved"):
            summary.setdefault("exe_unapproved", []).append(mid)
            log(f"  {mid} changes the game's program: imported OFF (approve it by importing it by itself)")
        if mid != top:
            summary["renamed"][top] = mid
        if res.get("moved"):
            summary["moved"][mid] = res["moved"]
        results[mid] = (top, meta)
    _repoint(mods_dir, results, summary, log)
    return summary


def _repoint(mods_dir, results, summary, log):
    """set each imported mod's "requires" to the folder that now holds the required uid"""
    where = _uids_in(mods_dir)
    for mid, (top, meta) in results.items():
        req = meta.get("requires") or []
        ru = meta.get("requires_uid") or []
        if not req:
            continue
        mj = os.path.join(mods_dir, mid, "mod.json")
        with open(mj, encoding="utf-8") as f:
            cur = json.load(f)
        new, changed, missing = [], {}, []
        for k, rid in enumerate(req):
            u = ru[k] if k < len(ru) else None
            target = where.get(u) if u else None
            if target is None:
                target = rid if os.path.isdir(os.path.join(mods_dir, rid)) else None
            if target is None:
                missing.append(rid)
                target = rid
            if target != rid:
                changed[rid] = target
            new.append(target)
        if missing:
            summary["missing_requires"][mid] = missing
            log(f"  warning: {mid} requires {', '.join(missing)}, which is not installed")
        if changed:
            cur["requires"] = new
            with open(mj, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=2, ensure_ascii=False)
            summary["repointed"][mid] = changed
            log(f"  {mid}: requires re-pointed " + ", ".join(f"{a} -> {b}" for a, b in changed.items()))
