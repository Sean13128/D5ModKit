"""DRPGSKILL1: a Disgaea RPG base character's own source skills, from the reviewed overlay.

The overlay (drpg-skill-overlay.json, built by tools/build_drpg_skill_overlay.py from the census of the JP
client's `command` / `charactercommand` / `charactermagiccommand` masters) is read here and never recomputed.
`apply` edits a built pack folder's table patches only: magic.dat rows, their choreography links
(patches/skills/skills.json) and the learn list of every char row.

Classes: E = D5 has the skill under the same JP name, the D5 row itself is linked; A = an own magic.dat row
with the source's numbers, playing a labelled stand-in D5 animation; X = no D5 expression, the link the pack
already has (a D5 lookalike) is kept and labelled donor.

Learn-list rule (labelled in mod.json `source_import.skills`): the character's own skills first, in source
order at the source's unlock level; then, when decision M1 is on, the source's weapon-mastery spells that D5 has
under the same name; then every link the pack already carried that is not replaced by an own skill, unchanged.
Sixteen links at most.  Learned skills are stored in the unit record by id (unit +0xCC0, 16-byte entries,
`unit_stats_skills_grant` 0x140160B00) and found by a binary search of magic.dat by id, so row position is
free; removing a link never removes a skill a saved unit already has.
"""
import hashlib
import json
from pathlib import Path

from . import _drpg_text

OVERLAY = Path(__file__).with_name("drpg-skill-overlay.json")
TWINS = Path(__file__).with_name("drpg-skill-twins.json")
SLOTS = 16
_CACHE = {}
# magic.dat field widths the gate holds the own rows to (d5lib/schemas/magic.json)
U16 = ("sp_cost", "learn_level", "rank", "attack_map", "anim_id")
I16 = tuple(f"effect{i}_value" for i in range(1, 7)) + tuple(f"power_lv{i}" for i in range(1, 11))


LANGS = ("JP", "EN", "FR", "CHN", "KOR")


def overlay():
    """the overlay with its text references resolved (TEXTHASH-DRPG)"""
    return _drpg_text.load(OVERLAY)


def row_sha(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def vanilla_rows(fs):
    """{skill id: row values} of the game's own magic.dat, for `apply` / `gate` (the overlay holds no game rows)"""
    from .. import database, dbpatch
    return {int(r["id"]): dbpatch._row_values(r) for r in
            database.load_table("magic.dat", fs.read("Database/Database_0.dat/magic.dat")).rows}


def row_of(s, vanilla):
    """the magic.dat row of own skill `s`: the stand-in's row (checked against the sha the overlay was built with)
    with the overlay's fields set; name and description are written in every language, as the kit does."""
    sid = s["stand_in"]["id"]
    donor = (vanilla or {}).get(sid)
    if donor is None:
        raise ValueError(f"stand-in {sid} is not in the magic.dat rows given to drpg_skills")
    if row_sha(donor) != overlay()["stand_in_sha256"][str(sid)]:
        raise ValueError(f"magic.dat row {sid} is not the vanilla row the overlay was built from (a mod edits it?)")
    row = dict(donor, **s["set"])
    for f in ("name", "desc"):
        row.update({f"{f}_{L}": s["set"][f"{f}_EN"] for L in LANGS if f"{f}_{L}" in donor})
    return row


def _on(decisions=None):
    return {k for k, v in {**overlay()["decisions"], **(decisions or {})}.items() if v}


def base(base_id):
    return overlay()["bases"].get(str(base_id))


def own(base_id, decisions=None):
    """the base's built skills (class E and A) in source order"""
    b = base(base_id) or {}
    return [s for s in b.get("skills", []) if s["cls"] in ("E", "A")]


def spells(base_id, decisions=None):
    b = base(base_id) or {}
    return [m for m in b.get("magic", []) if m.get("d5_id") and set(m["needs"]) <= _on(decisions)]


def enabled(base_id, decisions=None):
    return bool(own(base_id, decisions) or spells(base_id, decisions))


def _load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _dump(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def _kept(meta, folder, existing, built_rpg, decisions=None):
    """existing learn links (id, level) that no own skill replaces.  A link goes only when every source command
    the pack mapped to it (after the recorded motion twin swap) is one of the base's own built skills."""
    twins = (_drpg_text.load(TWINS)["packs"].get(folder) or {})
    by_d5 = {}
    for c in meta["source_import"]["source"]["character"].get("commands") or []:
        d5 = c.get("d5_id")
        if not d5 or c.get("verdict") == "omit":
            continue
        d5 = (twins.get(str(d5)) or {}).get("twin", d5)
        by_d5.setdefault(int(d5), []).append(int(c["rpg_id"]))
    out = []
    for sid, lv in existing:
        src = by_d5.get(sid)
        if src and all(r in built_rpg for r in src):
            continue
        if "C1" in _on(decisions) and src:       # C1: drop the costume looks' D5 lookalikes too
            continue
        out.append((sid, lv))
    return out


def learn_list(meta, folder, existing, base_id, decisions=None):
    """([(skill id, level)], {skill id: label}) for the pack; `existing` is the learn list it carries now."""
    mine = own(base_id, decisions)
    out, label = [], {}
    for s in mine:
        if s["d5_id"] not in label:
            out.append((s["d5_id"], s["unlock_level"]))
            label[s["d5_id"]] = "source (same D5 skill)" if s["cls"] == "E" else "source numbers, stand-in animation"
    for m in spells(base_id, decisions):
        if m["d5_id"] not in label:
            out.append((m["d5_id"], m["level"]))
            label[m["d5_id"]] = "source spell (same D5 spell)"
    # existing links that were themselves written by an earlier apply are not donors
    prev = {int(x["id"]) for x in (meta["source_import"].get("skills") or {}).get("links", []) if x["kind"] != "donor"}
    for sid, lv in _kept(meta, folder, [e for e in existing if e[0] not in prev], {s["rpg_id"] for s in mine}, decisions):
        if sid not in label:
            out.append((sid, lv))
            label[sid] = "donor"
    return out[:SLOTS], {i: label[i] for i, _ in out[:SLOTS]}


def _existing(row):
    n = min(int(row.get("learn_count") or 0), SLOTS)
    return [(int(row[f"learn{i}_skill"]), int(row.get(f"learn{i}_level") or 0)) for i in range(1, n + 1)
            if int(row.get(f"learn{i}_skill") or 0)]


def apply(mod_dir, base_id, decisions=None, vanilla=None):
    """Write the base's own skills into a pack folder.  Returns None when there is nothing to apply.
    `vanilla`: vanilla_rows(fs) of the unmodded game (needed when the base has an own row)."""
    mod_dir = Path(mod_dir)
    if not enabled(base_id, decisions):
        return None
    meta = json.loads((mod_dir / "mod.json").read_text())
    p = mod_dir / "patches/db/char.dat.json"
    patch = json.loads(p.read_text())
    rows = patch.get("added") or []
    learn, label = learn_list(meta, mod_dir.name, _existing(rows[0]), base_id, decisions)
    built = [s for s in own(base_id, decisions) if s["cls"] == "A"]
    band = overlay()["band"]
    if built:
        mp = mod_dir / "patches/db/magic.dat.json"
        doc = _load(mp, {"table": "magic.dat", "added": []})
        mine = {s["d5_id"]: row_of(s, vanilla) for s in built}
        doc["added"] = sorted([r for r in doc.get("added") or [] if not band[0] <= int(r["id"]) <= band[1]] + list(mine.values()),
                              key=lambda r: int(r["id"]))
        _dump(mp, doc)
        sp = mod_dir / "patches/skills/skills.json"
        doc = _load(sp, {"skills": {}, "events": {}, "effects": {}})
        doc["skills"] = {k: v for k, v in (doc.get("skills") or {}).items() if not band[0] <= int(k) <= band[1]}
        doc["skills"].update({str(s["d5_id"]): {"choreography": s["choreography"]} for s in built})
        _dump(sp, doc)
    for r in rows:
        for i in range(1, SLOTS + 1):
            r[f"learn{i}_skill"] = learn[i - 1][0] if i <= len(learn) else 0
            r[f"learn{i}_level"] = learn[i - 1][1] if i <= len(learn) else 0
        r["learn_count"] = len(learn)
    _dump(p, patch)
    si = meta["source_import"]
    b = base(base_id)
    si["skills"] = dict(
        own=[{k: s.get(k) for k in ("d5_id", "cls", "rpg_id", "name_jp", "name_en", "name_label", "unlock_level", "label",
                                    "stand_in", "dropped", "adaptations")} for s in b["skills"]],
        spells=[{k: m.get(k) for k in ("d5_id", "d5_name", "rpg_id", "name_jp", "level", "needs", "label")} for m in b.get("magic", [])],
        links=[dict(id=i, level=lv, kind=label[i]) for i, lv in learn],
        decisions={k: k in _on(decisions) for k in overlay()["decisions"]})
    si["skills"]["counts"] = _count(b)      # `specials` stays as it was: every animation is still a D5 stand-in
    _dump(mod_dir / "mod.json", meta)
    return dict(own=[s["d5_id"] for s in own(base_id, decisions)], rows=[s["d5_id"] for s in built],
                learn=[list(x) for x in learn], char_rows=len(rows))


def _count(b):
    out = {}
    for s in b["skills"]:
        out[s["cls"]] = out.get(s["cls"], 0) + 1
    return out


def gate(mod_dir, base_id, decisions=None, survey=None, vanilla=None):
    """(ok, why): the pack carries exactly the overlay's skills for this base, own rows stay inside magic.dat's
    field widths, and - with `vanilla` (vanilla_rows) - every row is the stand-in's row with the overlay's fields
    and every learn link resolves; with `survey` (a skillmotions.Survey) no caster motion is missing from any
    body of the pack."""
    mod_dir = Path(mod_dir)
    if not enabled(base_id, decisions):
        return True, "no own skill for this base under the current decisions (links kept)"
    meta = json.loads((mod_dir / "mod.json").read_text())
    rows = _load(mod_dir / "patches/db/char.dat.json", {}).get("added") or []
    have = {int(r["id"]): r for r in _load(mod_dir / "patches/db/magic.dat.json", {}).get("added") or []}
    chor = _load(mod_dir / "patches/skills/skills.json", {}).get("skills") or {}
    band = overlay()["band"]
    for s in own(base_id, decisions):
        if s["cls"] != "A":
            continue
        row = have.get(s["d5_id"])
        if not band[0] <= s["d5_id"] <= band[1] or s["d5_id"] >= 32768:
            return False, f"own skill id {s['d5_id']} outside the leased band {band}"
        if row is None or any(row.get(k) != v for k, v in s["set"].items()) or (vanilla is not None and row != row_of(s, vanilla)):
            return False, f"magic.dat row {s['d5_id']} missing or not the overlay's"
        if (chor.get(str(s["d5_id"])) or {}).get("choreography") != s["choreography"]:
            return False, f"choreography of {s['d5_id']} missing or not the stand-in's"
        for k in U16:
            if not 0 <= int(row[k]) <= 0xFFFF:
                return False, f"row {s['d5_id']} {k}={row[k]} outside u16"
        for k in I16:
            if not -32768 <= int(row[k]) <= 32767:
                return False, f"row {s['d5_id']} {k}={row[k]} outside i16"
        if not 0 <= int(row["sp_cost"]) <= 999 or not int(row["name_EN"] != ""):
            return False, f"row {s['d5_id']} SP {row['sp_cost']} or empty name"
    first = rows[0] if rows else {}
    cur = _existing(first)
    want, _ = learn_list(meta, mod_dir.name, cur, base_id, decisions)
    for r in rows:
        if _existing(r) != want or int(r.get("learn_count") or 0) != len(want):
            return False, f"char row {r.get('id')} learn list {_existing(r)}, expected {want}"
    if vanilla is not None:
        for sid, _ in want:
            if sid not in vanilla and sid not in have:
                return False, f"learn link {sid} resolves to no magic.dat row (vanilla or this pack)"
    if survey is not None:
        bad = [(r["unit"], r["skill"], r.get("missing")) for r in survey.check_mod(mod_dir) if r["status"] in ("missing", "unknown")]
        if bad:
            return False, f"caster motion missing/unknown: {bad[:4]}"
    n = len(own(base_id, decisions))
    return True, f"{n} own skills first ({sum(s['cls'] == 'E' for s in own(base_id, decisions))} same D5 skill), {len(spells(base_id, decisions))} spells, {len(want) - n - len(spells(base_id, decisions))} donor links kept"
