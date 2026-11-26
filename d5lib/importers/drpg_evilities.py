"""DRPGEVIL1: a Disgaea RPG base character's own source evilities, from the reviewed overlay.

The overlay (drpg-evility-overlay.json, built by tools/build_drpg_evility_overlay.py from the census of the JP
client's `leaderskill` master) is read here and never recomputed.  `apply` edits a built pack folder's table
patches only: Skill.dat rows, the runtime rows (patches/evilities), and the evility links of every char row.

Link rule (labelled in mod.json `source_import.evilities`): the character's own built evilities first, in source
slot order (main, sub 1-3); the slots that are not built keep the donor D5 evility the importer already linked
for that slot (`source.character.leader_skills`), four links at most.  With nothing built the pack is unchanged.
An evility whose overlay `needs` names a decision (D1/D2/D3/D4) is applied only when that decision is switched on.
D4 (DRPGPARTY1) evilities read a unit's potential type / favourite weapon: `apply` then also writes the class
registry (`classes`) into patches/evilities/evilities.json, which the runtime builds into the .d5el section.
"""
import json
from pathlib import Path

from . import _drpg_text

OVERLAY = Path(__file__).with_name("drpg-evility-overlay.json")
REGISTRY = Path(__file__).with_name("drpg-class-registry.json")
_CACHE = {}


def overlay():
    """the overlay with its text references resolved (TEXTHASH-DRPG: JP names are hashes, resolved from the build's pool)"""
    return _drpg_text.load(OVERLAY)


def registry():
    """DRPGPARTY1: {class id: {weapon, potential}} for every Disgaea RPG class (drpg-class-registry.json, built by
    tools/build_drpg_class_registry.py from the JP `character` master; never recomputed at build time)"""
    if "reg" not in _CACHE:
        _CACHE["reg"] = json.loads(REGISTRY.read_text())["classes"]
    return _CACHE["reg"]


def needs_registry(own):
    """an evility that needs decision D4 reads potential type / favourite weapon through the registry"""
    return any("D4" in e["needs"] for e in own)


def enabled(base_id, decisions=None):
    """the overlay evilities of a base that the switched-on decisions allow, in slot order"""
    doc = overlay()
    if int(base_id) in doc["samples_untouched"]:
        return []
    on = {k for k, v in {**doc["decisions"], **(decisions or {})}.items() if v}
    return [e for e in (doc["bases"].get(str(base_id)) or {}).get("evilities", []) if set(e["needs"]) <= on]


def links(base_id, leader_skills, decisions=None):
    """(evility ids for evility1..4, label per id).  `leader_skills` is the pack's recorded donor mapping."""
    own = enabled(base_id, decisions)
    built = {i for e in own for i in e["rpg_ids"]}
    out = [e["id"] for e in own]
    label = {e["id"]: "source" for e in own}
    for ls in leader_skills or []:
        ev = ls.get("evility") or ls.get("fallback_evility")
        if ls["rpg_id"] in built or not (ev and ev.get("id")) or ev["id"] in out:
            continue
        out.append(ev["id"])
        label[ev["id"]] = "donor"
    out = out[:4]
    return out, {i: label[i] for i in out}


def _load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _dump(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def apply(mod_dir, base_id, decisions=None):
    """Write the base's own evilities into a pack folder.  Returns None when there is nothing to apply."""
    mod_dir = Path(mod_dir)
    own = enabled(base_id, decisions)
    if not own:
        return None
    meta = json.loads((mod_dir / "mod.json").read_text())
    char = meta["source_import"]["source"]["character"]
    ids, label = links(base_id, char.get("leader_skills"), decisions)
    p = mod_dir / "patches/db/Skill.dat.json"
    patch = _load(p, {"table": "Skill.dat", "added": []})
    mine = {e["id"]: e["skill_row"] for e in own}
    patch["added"] = sorted([r for r in patch.get("added") or [] if int(r["id"]) not in mine] + list(mine.values()),
                            key=lambda r: int(r["id"]))
    _dump(p, patch)
    rt = {str(e["id"]): e["rows"] for e in own if e.get("rows")}
    if rt:
        p = mod_dir / "patches/evilities/evilities.json"
        doc = _load(p, {"evilities": {}})
        doc.setdefault("evilities", {}).update(rt)
        if needs_registry(own):
            doc["classes"] = registry()          # DRPGPARTY1: the conditions' class -> weapon / potential table
        _dump(p, doc)
    al = {str(e["id"]): e["alias"] for e in own if e.get("alias")}
    if al:
        p = mod_dir / "patches/evilities/aliases.json"
        _dump(p, {**_load(p, {}), **al})
    p = mod_dir / "patches/db/char.dat.json"
    patch = json.loads(p.read_text())
    rows = patch.get("added") or []
    for r in rows:
        r.update({f"evility{i}": ids[i - 1] if i <= len(ids) else 0 for i in range(1, 5)}, evility_count=len(ids))
    _dump(p, patch)
    main = next((e for e in own if e["slot"] == "main"), None)
    si = meta["source_import"]
    si["signature_evility"] = "source" if main else "donor (main evility not built); own: " + ", ".join(e["slot"] for e in own)
    si["evilities"] = dict(
        own=[dict(id=e["id"], slot=e["slot"], rpg_ids=e["rpg_ids"], name_jp=e["name_jp"], name_en=e["name_en"],
                  name_label=e["name_label"], cls=e["cls"], needs=e["needs"], label=e["label"]) for e in own],
        links=[dict(id=i, kind=label[i]) for i in ids],
        decisions={k: bool(v) for k, v in {**overlay()["decisions"], **(decisions or {})}.items()})
    _dump(mod_dir / "mod.json", meta)
    return dict(own=[e["id"] for e in own], links=ids, char_rows=len(rows))


def gate(mod_dir, base_id, decisions=None):
    """(ok, why): the pack carries exactly the evilities the overlay allows for this base."""
    mod_dir = Path(mod_dir)
    own = enabled(base_id, decisions)
    if not own:
        return True, "no own evility for this base under the current decisions (donor links kept)"
    meta = json.loads((mod_dir / "mod.json").read_text())
    ids, _ = links(base_id, meta["source_import"]["source"]["character"].get("leader_skills"), decisions)
    have = {int(r["id"]): r for r in _load(mod_dir / "patches/db/Skill.dat.json", {}).get("added") or []}
    rt = _load(mod_dir / "patches/evilities/evilities.json", {}).get("evilities") or {}
    al = _load(mod_dir / "patches/evilities/aliases.json", {})
    for e in own:
        if have.get(e["id"]) != e["skill_row"]:
            return False, f"Skill.dat row {e['id']} missing or not the overlay's"
        if e.get("rows") and rt.get(str(e["id"])) != e["rows"]:
            return False, f"runtime rows of {e['id']} missing or not the overlay's"
    if needs_registry(own) and _load(mod_dir / "patches/evilities/evilities.json", {}).get("classes") != registry():
        return False, "class registry (potential type / favourite weapon) missing or not the importer's"
    for e in own:
        if e.get("alias") and al.get(str(e["id"])) != e["alias"]:
            return False, f"alias of {e['id']} missing"
    want = [ids[i] if i < len(ids) else 0 for i in range(4)]
    for r in _load(mod_dir / "patches/db/char.dat.json", {}).get("added") or []:
        if [r.get(f"evility{i}") for i in range(1, 5)] != want or r.get("evility_count") != len(ids):
            return False, f"char row {r.get('id')} links {[r.get(f'evility{i}') for i in range(1, 5)]}, expected {want}"
    return True, f"{len(own)} own evilities linked first, {len(ids) - len(own)} donor links kept"
