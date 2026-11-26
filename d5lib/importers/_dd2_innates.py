"""EVILFX3: the innate evility of a DD2 pack whose char rows linked none (reviewed data: dd2-innate-evilities.json,
written by tools/build_dd2_innates.py).  `apply` edits a built pack's table patches only: one Skill.dat row (unless the
pack already ships it), its alias or runtime rows, and evility1 of every char row; existing links move down."""
import json
from pathlib import Path

DATA = Path(__file__).with_name("dd2-innate-evilities.json")


def _load(p, default):
    return json.loads(p.read_text()) if p.is_file() else default


def _dump(p, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")


def reviewed_pick(folder, data=None, text=None):
    """The reviewed row for ``folder`` with its ``@text`` references resolved.

    TEXTHASH-D1C-DD2: the checked-in data stores game names/rows as SHA-256 references and our own
    adaptation wording as ``@authored``; the names and any source-text row come from the prepared DD2
    source.  A caller may pass ``text`` (a ``(sha256) -> str`` resolver); a literal row needs none."""
    from .. import textrefs
    pick = (data or json.loads(DATA.read_text()))["packs"].get(folder)
    if not pick or not textrefs.has_refs(pick):
        return pick
    if text is None:
        from . import _dd2_source
        text = _dd2_source.text_pool().get
    return textrefs.resolve(pick, text, f'dd2-innate-evilities.packs.{folder}')


def apply(pack, folder, data=None, text=None):
    """-> a note, or None when the reviewed data has nothing for this folder"""
    pick = reviewed_pick(folder, data, text)
    if not pick:
        return None
    pack, rid = Path(pack), int(pick["id"])
    if "row" not in pick:                       # link only: the pack must already ship the row (reviewed-abilities layer or
        have = _load(pack / "patches/db/Skill.dat.json", {}).get("added") or []      # the installed copy), else no link
        if not any(int(r["id"]) == rid for r in have):
            return None
    if "row" in pick:
        p = pack / "patches/db/Skill.dat.json"
        doc = _load(p, {"table": "Skill.dat", "added": []})
        doc["added"] = sorted([r for r in doc.get("added") or [] if int(r["id"]) != rid] + [pick["row"]], key=lambda r: int(r["id"]))
        _dump(p, doc)
    if pick.get("alias"):
        p = pack / "patches/evilities/aliases.json"
        _dump(p, {**_load(p, {}), str(rid): pick["alias"]})
    if pick.get("drop_alias"):                  # DD2EVIL1: an own exact row replaces the earlier alias to a D5 evility
        p = pack / "patches/evilities/aliases.json"
        left = {k: v for k, v in _load(p, {}).items() if k != str(rid)}
        if left:
            _dump(p, left)
        elif p.exists():
            p.unlink()
    if pick.get("behavior"):
        p = pack / "patches/evilities/evilities.json"
        doc = _load(p, {"evilities": {}})
        doc.setdefault("evilities", {})[str(rid)] = pick["behavior"]
        _dump(p, doc)
    p = pack / "patches/db/char.dat.json"
    doc = json.loads(p.read_text())
    for r in doc["added"]:
        links = [rid] + [int(r[f"evility{i}"]) for i in range(1, 5) if r.get(f"evility{i}") and int(r[f"evility{i}"]) != rid]
        links = links[:4]
        r.update({f"evility{i + 1}": links[i] if i < len(links) else 0 for i in range(4)}, evility_count=len(links))
    _dump(p, doc)
    p = pack / "mod.json"
    meta = json.loads(p.read_text())
    si = meta.setdefault("source_import", {})
    si["innate_evility"] = dict(id=rid, dd2_id=pick["dd2_id"], name=pick["name"], relation=pick["relation"])
    lst = si.setdefault("adaptations", [])
    lst[:] = [a for a in lst if a == pick["label"] or not a.startswith(f"evility {pick['name']} ({pick['dd2_id']})")]  # DD2EVIL1: no stale line
    if pick["label"] not in lst:
        lst.append(pick["label"])
    _dump(p, meta)
    return f"innate evility {rid} {pick['name']} ({pick['relation']}) linked on {len(doc['added'])} char row(s)"


def gate(pack, folder, data=None):
    """(ok, why): every char row of a pack the data names links its innate first"""
    pick = (data or json.loads(DATA.read_text()))["packs"].get(folder)
    if not pick:
        return True, "no reviewed innate for this pack"
    rows = _load(Path(pack) / "patches/db/char.dat.json", {}).get("added") or []
    bad = [r.get("id") for r in rows if int(r.get("evility1") or 0) != int(pick["id"])]
    return (not bad, f"innate {pick['id']} linked on {len(rows)} row(s)" if not bad else f"char rows {bad} do not link {pick['id']}")
