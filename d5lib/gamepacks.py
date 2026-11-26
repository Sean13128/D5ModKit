"""Source-neutral catalogues selecting existing native mods; never an installer.

Catalogue schema 1 and the callable selection/staging contract are documented in
validate_catalogue, resolve_selection and materialize. No gameplay IDs are allocated.
"""
import copy
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import modsys

CATEGORIES = ("characters", "humanoid_classes", "monsters")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*\Z")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _token(value, label):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _strings(value, label, *, unique=True):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{label} must be a list of nonempty strings")
    if unique and len(set(value)) != len(value):
        raise ValueError(f"duplicate {label}")
    return value


def _payload_path(value):
    _text(value, "required payload")
    p = PurePosixPath(value)
    if ("\\" in value or ":" in value or p.is_absolute() or
            any(x in ("", ".", "..") for x in value.split("/")) or
            len(p.parts) < 2 or p.parts[0] not in ("files", "patches")):
        raise ValueError(f"unsafe required payload: {value!r}")
    return value


def validate_catalogue(catalogue, *, artifacts=None):
    """Return an independent JSON-compatible schema-1 dict or raise ValueError.

    Top-level: schema=1, id, name, games=[{id,name}], entries=[...]. Each
    entry: id (globally stable, edition/variant-specific), game, name, category
    (CATEGORIES), source={edition,identity,provenance:[{kind,reference,...}]},
    fidelity={mode: faithful|d5-tuned|hybrid|unknown,missing_mappings:[],adaptations:[]},
    status=catalogue|build-ready, requires/conflicts=[entry ids]. Build-ready
    entries require artifact={mod_id,required_payload:[files/...|patches/...]},
    with at least one required payload. Catalogue entries cannot claim an artifact.
    Without artifacts only declarations are validated (portable offline browsing).
    Supplying artifacts, including {}, verifies every claimed build-ready native
    child and each declared required payload. Unknown JSON fields are retained,
    including hashes and explicit adaptations. Neither mode certifies source truth
    or native gameplay acceptance.
    """
    import json
    try:
        doc = copy.deepcopy(catalogue)
        json.dumps(doc, allow_nan=False)
        if not isinstance(doc, dict) or type(doc.get("schema")) is not int or doc["schema"] != 1:
            raise ValueError("unsupported catalogue schema")
        _token(doc.get("id"), "catalogue id")
        _text(doc.get("name"), "catalogue name")
        games = {}
        if not isinstance(doc.get("games"), list) or not isinstance(doc.get("entries"), list):
            raise ValueError("games and entries must be lists")
        for game in doc["games"]:
            gid = _token(game["id"], "game id")
            _text(game["name"], "game name")
            if gid in games:
                raise ValueError(f"duplicate game id: {gid}")
            games[gid] = game
        entries = {}
        identities = set()
        for e in doc["entries"]:
            eid = _token(e["id"], "entry id")
            if eid in entries:
                raise ValueError(f"duplicate entry id: {eid}")
            entries[eid] = e
            _text(e["name"], "entry name")
            if e["game"] not in games or e["category"] not in CATEGORIES:
                raise ValueError(f"unknown game/category: {eid}")
            src = e["source"]
            _text(src["edition"], "source edition")
            _text(src["identity"], "source identity")
            identity = (e["game"], src["edition"], src["identity"])
            if identity in identities:
                raise ValueError(f"duplicate source identity: {identity}")
            identities.add(identity)
            if not isinstance(src["provenance"], list) or not src["provenance"]:
                raise ValueError(f"source provenance required: {eid}")
            for p in src["provenance"]:
                _text(p["kind"], "provenance kind")
                _text(p["reference"], "provenance reference")
            fidelity = e["fidelity"]
            if fidelity["mode"] not in ("faithful", "d5-tuned", "hybrid", "unknown"):
                raise ValueError(f"unknown fidelity mode: {eid}")
            _strings(fidelity["missing_mappings"], "missing mappings")
            _strings(fidelity["adaptations"], "adaptations")
            for relation in ("requires", "conflicts"):
                _strings(e.get(relation, []), relation)
            if e["status"] not in ("catalogue", "build-ready"):
                raise ValueError(f"invalid status: {eid}")
            if e["status"] == "build-ready":
                a = e.get("artifact")
                if not isinstance(a, dict):
                    raise ValueError(f"build-ready entry needs artifact: {eid}")
                _token(a.get("mod_id"), "artifact mod id")
                if ":" in a["mod_id"]:
                    raise ValueError("native mod id cannot contain colon")
                payload = _strings(a.get("required_payload"), "required payload")
                if not payload:
                    raise ValueError(f"artifact requires payload: {eid}")
                for path in payload:
                    _payload_path(path)
            elif "artifact" in e:
                raise ValueError(f"catalogue-only entry cannot claim artifact: {eid}")
        for eid, e in entries.items():
            for relation in ("requires", "conflicts"):
                for other in e.get(relation, []):
                    if other == eid or other not in entries:
                        raise ValueError(f"invalid {relation}: {eid} -> {other}")
        if artifacts is not None:
            for entry in entries.values():
                if entry["status"] == "build-ready":
                    artifact = entry["artifact"]
                    _artifact(artifact["mod_id"], artifacts, artifact["required_payload"])
        return doc
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed catalogue: {exc}") from exc


@dataclass(frozen=True)
class Selection:
    """Topological entry/mod order plus explicitly unbuilt catalogue selections."""
    entry_ids: tuple
    catalogue_only: tuple
    mod_ids: tuple


def _ordered(roots, dependencies, label):
    import heapq
    graph, pending = {}, list(roots)
    while pending:
        key = pending.pop()
        if key not in graph:
            graph[key] = set(dependencies(key))
            pending.extend(graph[key] - graph.keys())
    followers = {key: [] for key in graph}
    degree = {key: len(deps) for key, deps in graph.items()}
    for key, deps in graph.items():
        for dep in deps:
            followers[dep].append(key)
    ready = [key for key in graph if not degree[key]]
    heapq.heapify(ready)
    out = []
    while ready:
        key = heapq.heappop(ready)
        out.append(key)
        for user in followers[key]:
            degree[user] -= 1
            if not degree[user]:
                heapq.heappush(ready, user)
    if len(out) != len(graph):
        raise ValueError(f"{label} dependency cycle: {sorted(k for k in graph if degree[k])}")
    return tuple(out)


def _artifact(mod_id, artifacts, required=()):
    """Read a named native child only; never search a mod store or allocate IDs."""
    _token(mod_id, "native mod id")
    if ":" in mod_id:
        raise ValueError(f"invalid native mod id: {mod_id}")
    if mod_id not in artifacts:
        raise ValueError(f"missing artifact child: {mod_id}")
    value = artifacts[mod_id]
    folder = Path(value.folder if isinstance(value, modsys.Mod) else value).absolute()
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise ValueError(f"symlink in artifact source path: {mod_id}")
    if not folder.is_dir() or folder.name != mod_id:
        raise ValueError(f"artifact folder/id mismatch or symlink: {mod_id}")
    for native in (folder / "files", folder / "patches", folder / "patches" / "classes"):
        if native.is_symlink():
            raise ValueError(f"symlink in native artifact tree: {mod_id}")
    meta = folder / "mod.json"
    if meta.is_symlink() or not meta.is_file():
        raise ValueError(f"missing native mod.json: {mod_id}")
    try:
        mod = modsys.Mod(str(folder))  # fresh metadata, not a caller's stale object
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid native artifact metadata: {mod_id}") from exc
    for path in required:
        payload = folder / _payload_path(path)
        if any(p.is_symlink() for p in (payload, *payload.parents) if p != folder.parent):
            raise ValueError(f"symlink in artifact payload: {mod_id}/{path}")
        if not payload.is_file() or payload.stat().st_size == 0:
            raise ValueError(f"missing required payload: {mod_id}/{path}")
    return mod


def resolve_selection(catalogue, *, artifacts=None, games=(), categories=None,
                      entries=(), exclude_entries=()):
    """Resolve a selection without writing. All toggles are stable IDs, not labels.

    Bulk selection = games intersect categories (None means all three); explicit
    entries are unioned, then exclude_entries removed. Defaults select nothing.
    Entry dependencies and native mod.json.requires are transitively sorted before
    users, deduped, and cycles/missing dependencies/excluded dependencies rejected.
    Selected catalogue-only entries are reported, never materialized. A built
    entry cannot depend on a catalogue-only entry. artifacts maps native mod IDs
    to Mod objects or explicit folders; selected build-ready children must exist.
    """
    doc = validate_catalogue(catalogue)
    by_id = {e["id"]: e for e in doc["entries"]}
    game_ids = {g["id"] for g in doc["games"]}
    def choices(values, known, label):
        if isinstance(values, str):
            raise ValueError(f"{label} must be an iterable of IDs, not a string")
        chosen = set(values)
        if not chosen <= set(known):
            raise ValueError(f"unknown {label}: {sorted(chosen - set(known))}")
        return chosen
    gs = choices(games, game_ids, "games")
    cs = choices(CATEGORIES if categories is None else categories, CATEGORIES, "categories")
    explicit = choices(entries, by_id, "entries")
    excluded = choices(exclude_entries, by_id, "exclude_entries")
    wanted = (explicit | {e["id"] for e in by_id.values()
                          if e["game"] in gs and e["category"] in cs}) - excluded
    catalogue_only = tuple(sorted(eid for eid in wanted if by_id[eid]["status"] == "catalogue"))
    def entry_deps(eid):
        if eid in excluded:
            raise ValueError(f"required entry excluded: {eid}")
        e = by_id[eid]
        if e["status"] != "build-ready":
            raise ValueError(f"required entry is catalogue-only: {eid}")
        return e.get("requires", [])
    ordered = _ordered(wanted - set(catalogue_only), entry_deps, "entry")
    selected = set(ordered) | set(catalogue_only)
    for eid in selected:
        clash = selected & set(by_id[eid].get("conflicts", []))
        if clash:
            raise ValueError(f"entry conflict: {eid} with {sorted(clash)}")
    artifacts = artifacts or {}
    mods = {}
    for eid in ordered:
        a = by_id[eid]["artifact"]
        mods[a["mod_id"]] = _artifact(a["mod_id"], artifacts, a["required_payload"])
    def mod_deps(mid):
        if mid not in mods:
            mods[mid] = _artifact(mid, artifacts)
        return _strings(mods[mid].meta.get("requires", []), f"native requires for {mid}", unique=False)
    mod_ids = _ordered(mods, mod_deps, "native mod")
    if modsys.missing_requirements([mods[mid] for mid in mod_ids]):
        raise ValueError("native dependency ordering failed")
    for eid, entry in by_id.items():
        if entry["status"] == "build-ready" and entry["artifact"]["mod_id"] in mod_ids:
            if eid not in ordered:
                raise ValueError(f"atomic native child also contains unselected entry: {eid}; select it explicitly")
            expected = "characters" if entry["category"] == "characters" else "classes"
            category = mods[entry["artifact"]["mod_id"]].meta.get("category")
            if category and category != expected:
                raise ValueError(f"native category disagrees with catalogue: {eid}")
    from . import modshare
    uids, families = {}, {}
    for mid in mod_ids:
        mod = mods[mid]
        clash = set(mod_ids) & set(_strings(mod.meta.get("conflicts", []), f"native conflicts for {mid}"))
        if clash:
            raise ValueError(f"native mod conflict: {mid} with {sorted(clash)}")
        uid = mod.meta.get("uid")
        if uid:
            _text(uid, "native uid")
            if uid in uids:
                raise ValueError(f"duplicate native uid: {uids[uid]} and {mid}")
            uids[uid] = mid
        for family in modshare.class_families(mod):
            if family in families:
                raise ValueError(f"fixed class family conflict: {families[family]} and {mid}: {family}")
            families[family] = mid
    return Selection(ordered, catalogue_only, mod_ids)


def _native_tree(folder):
    """Enumerate only this explicitly selected artifact, refusing links/special files."""
    import os
    import stat
    def checked(path):
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"symlink/special file in artifact: {path}")
    for path in folder.iterdir():
        checked(path)  # reject top-level links without descending unrelated folders
    yield folder / "mod.json"
    for native in ("files", "patches"):
        subtree = folder / native
        if not subtree.exists():
            continue
        if not subtree.is_dir():
            raise ValueError(f"native payload folder is not a directory: {subtree}")
        for root, dirs, files in os.walk(subtree, followlinks=False):
            for name in dirs + files:
                checked(Path(root) / name)
            for name in sorted(files):
                yield Path(root) / name


def materialize(catalogue, selection, *, artifacts, staging_path):
    """Copy selected native children and native Packs into a NEW isolated kit path.

    Rechecks the selection/artifacts, then writes mods/<original-id>/mod.json,
    files/, patches/, mods/packs.json, a native Default profile load order, a
    catalogue snapshot and gamepacks.json receipt. Each game owns one native pack;
    dependency-only mods remain ungrouped because native packs are not nested and
    each mod can belong to at most one. Sources/UIDs/local_ids/requires are retained;
    gamepack entries are annotations on copies only. Returns the staging Path.

    Existing targets, symlink ancestors, source overlap, known kit/game ancestors
    are refused. No installation, export/remapping, settings or save operations.
    Failure before publication removes the private temporary sibling directory.
    The caller must keep artifacts stable for the duration (no concurrent writer).
    """
    import json
    import os
    import shutil
    import tempfile
    from . import modinfo
    doc = validate_catalogue(catalogue)
    if not isinstance(selection, Selection):
        raise ValueError("expected a resolved Selection")
    checked = resolve_selection(doc, entries=selection.entry_ids + selection.catalogue_only,
                                artifacts=artifacts)
    if checked != selection:
        raise ValueError("stale or altered selection; resolve again")
    target = Path(os.path.abspath(staging_path))
    if target.exists() or target.is_symlink():
        raise ValueError("staging target must not exist")
    for parent in target.parents:
        if parent.is_symlink():
            raise ValueError("symlink ancestor of staging path")
        if (parent == Path(modsys.KIT_DIR).resolve() or (parent / "disgaea5.exe").exists()
                or (parent / "settings.json").exists()):
            raise ValueError("staging cannot be inside a live kit/game")
    mods = {mid: _artifact(mid, artifacts) for mid in selection.mod_ids}
    for mod in mods.values():
        source = Path(mod.folder).resolve()
        if target.is_relative_to(source) or source.is_relative_to(target):
            raise ValueError("staging overlaps source artifact")
        # Preflight the complete copied native tree before any destination writes.
        paths = list(_native_tree(Path(mod.folder)))
        if not any(p.relative_to(mod.folder).parts[0] in ("files", "patches")
                   and p.stat().st_size for p in paths):
            raise ValueError(f"artifact child has no payload: {mod.id}")
    by_mod = {}
    for eid in selection.entry_ids:
        entry = next(e for e in doc["entries"] if e["id"] == eid)
        by_mod.setdefault(entry["artifact"]["mod_id"], []).append(entry)
    for mid, es in by_mod.items():
        if len({e["game"] for e in es}) > 1:
            raise ValueError(f"native child belongs to multiple game packs: {mid}")
        if len({"characters" if e["category"] == "characters" else "classes" for e in es}) > 1:
            raise ValueError(f"native child spans incompatible categories: {mid}")
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    def write(path, value):
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    try:
        (work / "mods").mkdir()
        for mid, mod in mods.items():
            destination = work / "mods" / mid
            destination.mkdir()
            shutil.copy2(Path(mod.folder) / "mod.json", destination / "mod.json")
            for folder in ("files", "patches"):
                src = Path(mod.folder) / folder
                if src.is_dir():
                    shutil.copytree(src, destination / folder)
            if mid in by_mod:
                child = modsys.Mod(str(destination))
                child.meta["gamepack"] = {"catalogue_id": doc["id"], "entries": by_mod[mid]}
                if not child.meta.get("category"):
                    child.meta["category"] = "characters" if by_mod[mid][0]["category"] == "characters" else "classes"
                child.save_meta()
        packs = modinfo.Packs(str(work / "mods"))
        for game in sorted(doc["games"], key=lambda g: g["id"]):
            members = [mid for mid in selection.mod_ids if mid in by_mod and by_mod[mid][0]["game"] == game["id"]]
            if members:
                pack = packs.create(game["name"], members, f"Selected native children from {doc['name']}")
                pack.update(id=f"gamepack/{doc['id']}/{game['id']}", game=game["id"], catalogue_id=doc["id"])
        packs.save()
        # Explicit staging root: never instantiate ModManager with its live default.
        manager = modsys.ModManager(str(work))
        manager.save_load_order(selection.mod_ids)
        write(work / "catalogue.json", doc)
        write(work / "gamepacks.json", {"schema": 1, "catalogue_id": doc["id"],
              "built_entries": selection.entry_ids, "catalogue_only": selection.catalogue_only,
              "mod_ids": selection.mod_ids})
        # Read through the actual native consumers before publishing the staging tree.
        if tuple(m.id for m in manager.enabled_mods()) != selection.mod_ids:
            raise ValueError("native staged load-order read-back failed")
        if modsys.missing_requirements(manager.enabled_mods()):
            raise ValueError("native staged dependencies failed")
        if target.exists():
            raise ValueError("staging target appeared during build")
        work.rename(target)
    finally:
        if work.exists():
            shutil.rmtree(work)
    return target
