"""The recorded specials / voice / notes post-pass for the D4 unique packs.

The installed D4 uniques carry content that no builder produces on its own:

* the reviewed donor specials (`Research/source-packs/specials/patch_specials.py` for 22 packs,
  `Research/source-packs/d4uniq3/specials.py` for ten), with their magic.dat rows, choreography
  rules, learn lists and the three exact evility rows (8861, 8874, 8884);
* the D4UNIQ3 ability notes the ten packs ship.

Recomputing those ids (`10000 + identity + order`) is how a rebuild drifts, so both scripts are
called with the id allocation read from `d5lib/importers/d4-leases.json` (generated once by
`tools/build_d4_leases.py` from the installed packs and the lanes' receipts).  Nothing here
invents content: the scripts own it, this module only decides which pack gets which row.

Prior art: the two lane scripts themselves (refactored to take a lease + a target map, with their
original CLI behaviour kept), `d5lib/newclasses.add_skill` (the row/choreography writer they call),
`d5lib/sourceimports`/`d4unique` for the build side, `Tools/build_tracker.py` vocabulary.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path

BASE = Path("/Volumes/Data/Projects/D5")
SPECIALS = BASE / "Research/source-packs/specials/patch_specials.py"
D4UNIQ3 = BASE / "Research/source-packs/d4uniq3/specials.py"


_LOAD_LOCK = threading.Lock()


def _load(name, path):
    """Import a lane script by path, without leaving its directory on sys.path.

    Locked: under `--jobs 2` a second build thread found the half-executed module in sys.modules
    ("module 'd4_specials_pass' has no attribute 'apply'", D4FIX)."""
    with _LOAD_LOCK:
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module


def lease_by_mod(lease_doc):
    return {c["mod"]: c for c in lease_doc["characters"].values()}


def builder_mappings(receipts):
    """{mod_id: {d4_id: d5_id}} - the skills a build emitted from the reviewed completed mapping."""
    out = {}
    for sid, doc in receipts.items():
        mod = f"D4_Unique_{sid}"
        out[mod] = {int(m["d4_id"]): int(m["d5_id"]) for m in doc.get("mappings", [])
                    if m.get("kind") == "skill" and m.get("d5_id")}
    return out


def _has_learn_row(mod, skill_id):
    path = Path(mod) / "patches/db/char.dat.json"
    if not path.is_file():
        return False
    return any(int(r.get(f"learn{i}_skill") or 0) == int(skill_id)
               for r in json.loads(path.read_text()).get("added") or [] for i in range(1, 17))


def _donor_learn(sid):
    """Reviewed fallback rows for a D4 unique whose source learnset is empty (sourcemaps/d4.json "uniques")."""
    doc = json.loads((Path(__file__).resolve().parents[1] / "sourcemaps/d4.json").read_text())
    return (doc.get("uniques") or {}).get(str(sid), {}).get("skills", [])


def write_learn_lists(catalog, lease, emitted, source):
    """D4's learn order, level for level, with the leased (or builder's) D5 id for each row.

    The installed packs' learn lists are exactly this: the D4 learnset in order, each row keyed to
    the id the specials pass leased or the builder's own completed-mapping row, Magichange rows
    dropped (`SKILLS[...] == 'omit'`).  Writing it here (instead of in either pass) keeps one rule
    for both groups and cannot disagree with the ids the passes just wrote.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from d5lib import d4source
    data = d4source.D4Data(source, "EN")
    report = {}
    for mod_id, folder in catalog.items():
        entry = lease.get(mod_id)
        if not entry or entry.get("parked"):
            continue
        sid = int(entry["mod"].rsplit("_", 1)[-1])
        char = data.chars.get(sid)
        if not char:
            report[mod_id] = "no D4 char row"
            continue
        leased = {int(s["d4_id"]): int(s["d5_id"]) for s in entry.get("specials", [])}
        builder = emitted.get(mod_id, {})
        learn = []
        for d4_id, level in char["learnset"]:
            d5_id = leased.get(d4_id) or builder.get(d4_id)
            if d5_id:
                learn.append((d5_id, level))
        if not learn:   # UNIQUESKILLS1: no source skills; the reviewed map's labelled donor-class line (d4.json "uniques")
            learn = [(int(r["d5_id"]), int(r["level"])) for r in _donor_learn(sid)]
        path = Path(folder) / "patches/db/char.dat.json"
        if not path.is_file():
            report[mod_id] = "no char.dat patch"
            continue
        doc = json.loads(path.read_text())
        if len(doc.get("added") or []) != 1:
            report[mod_id] = "char.dat patch is not a single row"
            continue
        row = doc["added"][0]
        changed = 0
        for n in range(16):
            sid_value = learn[n][0] if n < len(learn) else 0
            level = learn[n][1] if n < len(learn) else 0
            if int(row.get(f"learn{n + 1}_skill") or 0) != sid_value:
                changed += 1
            row[f"learn{n + 1}_skill"] = sid_value
            row[f"learn{n + 1}_level"] = level
        row["learn_count"] = len(learn)
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        report[mod_id] = dict(rows=len(learn), changed=changed)
    return report


def make_fs(game_path):
    """A GameFS whose tables are the ORIGINAL ones (the kit's own backups), not the live modded DB.

    The installed game's Database_0.dat already carries every installed mod's rows, so a patch
    diffed against it re-ships other packs' rows (measured: 137 rows for one u10 skill).  The
    builder is given `--original-state` for the same reason; the post-pass uses the same resolver.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from d5lib import gamefs, modsys
    installer = modsys.Installer(str(game_path), str(Path(__file__).resolve().parents[2]),
                                 log=lambda *a: None)
    return gamefs.GameFS(str(game_path), backup_resolver=installer.backup_resolver)


def add_skill_row(fs, mod, new_id, copy_of, name, desc):
    """`newclasses.add_skill`, but the magic.dat patch is written explicitly.

    The kit's add_skill diffs its edited table against whatever `fs.read` returned on the first
    call; in this checkout that is the LIVE (modded) Database_0.dat while a later call sees the
    same table, so the diff re-shipped every installed pack's skill rows (measured: 137 rows in
    D4_Unique_10's patch for one leased skill).  Copying the donor row and appending it under
    `added` is the shape the installed packs carry and cannot pick up another pack's rows.
    """
    from d5lib import dbpatch, database, modsys
    import d5lib.newclasses as newclasses
    table = database.load_table("magic.dat", fs.read("Database/Database_0.dat/magic.dat"))
    donor = table.find(int(copy_of))
    if donor is None:
        raise ValueError(f"magic.dat donor {copy_of} is not in the table")
    row = donor.copy()
    row.set("id", int(new_id))
    newclasses.set_langs(row, "name", name)
    if desc is not None:
        newclasses.set_langs(row, "desc", desc)
    doc = mod.load_patch("db", "magic.dat.json") or {"table": "magic.dat"}
    doc.setdefault("added", [])
    doc["added"] = [r for r in doc["added"] if int(r.get("id") or 0) != int(new_id)]
    doc["added"].append(dbpatch._row_values(row))
    mod.save_patch("db", "magic.dat.json", doc)
    from d5lib import skills
    skills.inherit(fs, mod, new_id, copy_of)


def apply(catalog, lease_doc, receipts, source, game_path=None):
    """Run both recorded passes over the rebuilt unique folders; returns a per-mod note dict."""
    lease = lease_by_mod(lease_doc)
    targets = {mod: Path(folder) for mod, folder in catalog.items() if not lease.get(mod, {}).get("parked")}
    if not targets:
        return {}
    emitted = builder_mappings(receipts)
    notes = {}
    fs = make_fs(game_path) if game_path else None
    if fs is None:
        from d5lib import gamefs
        fs = gamefs.GameFS(str(game_path))
    specials = _load("d4_specials_pass", SPECIALS)
    # both scripts call newclasses.add_skill; use the explicit writer below instead of its diff
    import d5lib.newclasses as _newclasses
    _newclasses.add_skill = add_skill_row
    specials.apply(lease, targets, fs=fs)
    notes["specials"] = "wrapped Research/source-packs/specials/patch_specials.py"
    uniq3 = _load("d4uniq3_specials", D4UNIQ3)
    three = uniq3.apply(lease, targets, receipts, fs=fs)
    if fs is not None:
        fs.reset()
    notes["d4uniq3"] = "wrapped Research/source-packs/d4uniq3/specials.py (specials, evilities, notes)"
    notes["learn"] = write_learn_lists(targets, lease, emitted, source)
    del three
    return notes
