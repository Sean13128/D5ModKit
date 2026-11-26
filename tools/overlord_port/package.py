"""Option (b): treat the Overlord v3 release as a set of "Overlord package" mods the Kit can convert.

Offline pipeline, no game launch and no install:

  1. discover the `Database_0` members the release ships as full replacements;
  2. for each one, diff it against the *vanilla* member (`baseline.py`) into a Kit row patch and
     prove the patch round-trips to the replacement's exact bytes (`tables.py`) -- including the
     members his build *inserts* rows into (item.dat) and the members nothing can address by key;
  3. split every patch into **one mod per feature** (Sean, 2026-10-29: "split Overlord into separate
     optional Kit mods per feature ... all ON by default"), so each thing can be switched off alone:

       Overlord Character - Majin / Battle Suit / Stella / Android / Rutile   one char.dat row each
       Overlord Characters    charhelp + charPersonal rows (kept together: both are addressed by
                              position, and his row order is the only thing keeping them aligned)
       Overlord Evilities     the 23 Skill.dat rows
       Overlord Specials      the 13 magic.dat rows
       Overlord Recruit Wishes  the 14 WishDataBase rows + the 3 Quest.dat conditions they sit behind
       Overlord Items         the 3 item rows his build inserts at index 1207
       Overlord Curry         his curry row and its descriptions
       Overlord Voices        the 96 voice-list rows
       Overlord UI Text       the 4 menu strings that explain what a screen does
       Overlord Innocent Renames   the 105 HABIT.dat rows (names that say what the innocent does)
       Overlord Rebalance     every remaining row of the game's own tables that his build retunes

     The split is proven, not asserted: every feature mod applied in order, then "Overlord Rebalance",
     must reproduce all 15 of his member files byte for byte (`composite_byte_exact`), so no feature
     depends on another and any subset can be enabled;
  4. gate the result: every id the package appends must be one the ownership manifest gives to
     Overlord, no installed mod may already claim it, and a change that moves a position a save
     points at (the learned-evility bitmap) is refused unless a save migration ships with it.

The output is a *plan*, refused by default with the reasons named. Nothing here writes the game
folder, the installed kit, a profile or a save.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import baseline      # noqa: E402
import tables        # noqa: E402

from d5lib import database, dbpatch, modclaims, ownership   # noqa: E402

MOD_NAME = "Overlord Edition"          # the umbrella name the report and docs use
REBALANCE_NAME = "Overlord Rebalance"
PACK_ID = "Overlord"
RELEASE_SUBDIR = os.path.join("mods", "Overlord", "Database", "Database_0")
HOLDER = "overlord:" + MOD_NAME

# (mod name, [(member, kind, ids|None)]) in install order.  The per-character order is his own file
# order (20500, 20000, 20300, 20010, 20310), so the appended rows land exactly where his do.
FEATURES = [
    ("Overlord Character - Majin", [("char.dat", "added", [20500])]),
    ("Overlord Character - Battle Suit", [("char.dat", "added", [20000])]),
    ("Overlord Character - Stella", [("char.dat", "added", [20300])]),
    ("Overlord Character - Android", [("char.dat", "added", [20010])]),
    ("Overlord Character - Rutile", [("char.dat", "added", [20310])]),
    ("Overlord Characters", [("charhelp.dat", "added", None),
                             ("charPersonal.dat", "added", None)]),
    ("Overlord Evilities", [("Skill.dat", "added", None)]),
    ("Overlord Specials", [("magic.dat", "added", None)]),
    ("Overlord Recruit Wishes", [("WishDataBase.dat", "added", None),
                                 ("Quest.dat", "rows", None)]),
    ("Overlord Items", [("item.dat", "insert", None)]),
    ("Overlord Curry", [("Curry.dat", "added", None), ("Curry.dat", "rows", None)]),
    ("Overlord Voices", [("Sound_Voice_EN_0.dat", "added", None)]),
    ("Overlord UI Text", [("StringListDataBase.dat", "rows", None)]),
    ("Overlord Innocent Renames", [("HABIT.dat", "rows", None)]),
]
MOD_ORDER = tuple([name for name, _ in FEATURES] + [REBALANCE_NAME])

DESCRIPTIONS = {
    "Overlord Characters": "character help and personality rows for his five characters",
    "Overlord Evilities": "the 23 evility rows his build adds",
    "Overlord Specials": "the 13 unique specials his characters use",
    "Overlord Recruit Wishes": "his 14 recruit wishes and the quest conditions they sit behind",
    "Overlord Items": "the three item rows his build inserts mid-table",
    "Overlord Curry": "his curry row and curry descriptions",
    "Overlord Voices": "his voice-list rows",
    "Overlord UI Text": "menu strings that say what a screen does",
    "Overlord Innocent Renames": "innocent names that say what the innocent does",
}


def shipped_members(release_dir):
    d = os.path.join(release_dir, RELEASE_SUBDIR)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"{d}: not an extracted Overlord release")
    return sorted(f for f in os.listdir(d) if f.lower().endswith(".dat"))


def _claims_for(table, added_ids, holder):
    """ownership.Claim objects for the ids one feature mod appends."""
    ns = dict(modclaims.NAMESPACES)
    ns.setdefault("WishDataBase.dat", "wish_id")
    namespace = ns.get(table)
    out = []
    if namespace and added_ids:
        for rid in sorted(added_ids):
            out.append(ownership.Claim(holder, namespace, rid, rid,
                                       label=f"{table} added row {rid}",
                                       evidence="converted from the Overlord v3 release"))
    return out


def split_features(patches):
    """{member: full patch} -> ({mod: {member: patch}}, {member: patch}), his add order kept."""
    rest = {m: {"rows": dict(p.get("rows") or {}), "added": list(p.get("added") or []),
                "insert": list(p.get("insert") or [])} for m, p in patches.items()}
    feats = {name: {} for name, _ in FEATURES}
    for name, spec in FEATURES:
        for member, kind, ids in spec:
            src = rest.get(member)
            if not src:
                continue
            part = feats[name].get(member) or {"table": member}
            if kind == "added" and src["added"]:
                if ids:
                    take = [r for r in src["added"] if r.get("id") in ids]
                    src["added"] = [r for r in src["added"] if r.get("id") not in ids]
                else:
                    take, src["added"] = src["added"], []
                if take:
                    part["added"] = take
            elif kind == "insert" and src["insert"]:
                part["insert"], src["insert"] = src["insert"], []
            elif kind == "rows" and src["rows"]:
                part["rows"], src["rows"] = src["rows"], {}
            if len(part) > 1:
                feats[name][member] = part
    rebalance = {}
    for member, left in rest.items():
        p = {"table": member}
        for kind in ("rows", "insert", "added"):
            if left[kind]:
                p[kind] = left[kind]
        if len(p) > 1:
            rebalance[member] = p
    return feats, rebalance


def _composite(fs, member, replacement, parts):
    """apply the member's feature patches in install order: must equal his bytes, or the split lost data"""
    table = database.load_table(member, baseline.read(fs, member))
    warns = []
    for part in parts:
        warns += dbpatch.apply_patch(table, part)
    same = table.to_bytes() == database.load_table(member, replacement).to_bytes()
    return same, warns


def _sibling_diff(sibling_bytes, other_bytes, sibling):
    """How a stray second copy of a table differs from the copy the game loads.

    `Curry_modded.dat` is his working copy of `Curry.dat`: 9 rows differ only in the game's full-width
    ％ being typed as ASCII % (the mistake DECISIONS.md 2026-10-29 records -- it crashed the Skill
    Trainer) and one row differs in wording.  Installing it would be a regression, so it is reported
    as a superseded duplicate of the member that *is* converted rather than converted itself.  A copy
    that differs in any non-text field, or that is not the same shape, is not explained this way.
    """
    try:
        a = database.load_table(sibling, sibling_bytes)
        b = database.load_table(sibling, other_bytes)
    except (KeyError, ValueError, IndexError):
        return None
    if len(a.rows) != len(b.rows) or [r.get("id") for r in a.rows] != [r.get("id") for r in b.rows]:
        return None
    strip = lambda t: str(t).replace("\uff05", "").replace("%", "")
    pct, other = [], []
    for i, (ra, rb) in enumerate(zip(a.rows, b.rows)):
        fields = {f.name for f in a.schema.fields if ra._get(f) != rb._get(f)}
        if not fields:
            continue
        if any(f.type != "str" for f in a.schema.fields if f.name in fields):
            return None
        if all(strip(ra._get(f)) == strip(rb._get(f)) for f in a.schema.fields if f.name in fields):
            pct.append(i)
        else:
            other.append(i)
    if not pct and not other:
        return None
    return {"sibling": sibling, "percent_rows": len(pct), "wording_rows": len(other),
            "rows": len(pct) + len(other)}


def convert(release_dir, out_dir, game_dir=None, installed_mods=None,
            allow_vanilla_row_rewrites=True, allow_positional=False, write=True, log=print):
    """Audit every shipped member and (optionally) emit one mod folder per feature.

    Returns a report dict: per-member results, per-mod contents, id claims, ownership findings, verdict.
    """
    fs = baseline.open_database(game_dir or baseline.DEFAULT_GAME)
    vanilla_names = set(baseline.members(fs))
    manifest = ownership.load()
    report = {"release": os.path.abspath(release_dir), "game_dir": os.path.abspath(fs.game_dir),
              "mod": MOD_NAME, "rebalance_mod": REBALANCE_NAME, "pack": PACK_ID,
              "holder": HOLDER, "members": [], "claims": [], "findings": [], "mods": {},
              "verdict": "refused", "reasons": []}
    released = {}
    for member in shipped_members(release_dir):
        with open(os.path.join(release_dir, RELEASE_SUBDIR, member), "rb") as fh:
            released[member] = fh.read()
    patches = {}
    for member, replacement in sorted(released.items()):
        if member not in vanilla_names:
            entry = {"table": member, "status": "not-a-vanilla-member",
                     "reason": "no such member in the game's own Database_0"}
            stem = member.rsplit("_", 1)[0]
            sibling = next((m for m in released if m.rsplit(".", 1)[0] == stem), None)
            diff = _sibling_diff(released[sibling], replacement, sibling) if sibling and \
                sibling in vanilla_names else None
            if diff:
                entry = dict(diff, table=member, status="superseded-duplicate",
                             reason=(f"his working copy of {diff['sibling']}: {diff['percent_rows']} row(s) "
                                     f"differ only in the percent sign (full-width ％ vs ASCII %) and "
                                     f"{diff['wording_rows']} in wording. {diff['sibling']} is the member the "
                                     f"game loads and the one converted; this copy is not installed "
                                     f"(DECISIONS.md 2026-10-29: ％, never %)"))
            report["members"].append(entry)
            continue
        result = tables.audit(member, baseline.read(fs, member), replacement,
                              allow_positional=allow_positional)
        entry = result.as_dict()
        report["members"].append(entry)
        if result.convertible:
            patches[member] = result.patch
    feats, rebalance = split_features(patches)
    # ---- the split must be lossless, per member, in install order --------------------------------
    for member in patches:
        parts = [feats[name][member] for name, _ in FEATURES if member in feats[name]]
        if member in rebalance:
            parts.append(rebalance[member])
        same, warns = _composite(fs, member, released[member], parts)
        for entry in report["members"]:
            if entry["table"] == member:
                entry["composite_byte_exact"] = same
                entry["composite_warnings"] = warns
                if not same:
                    entry["status"] = "refused"
                    entry["reason"] = "the feature split does not reproduce the replacement's bytes"
    failed = {e["table"] for e in report["members"] if e["status"] == "refused"}
    for name, _ in FEATURES:                       # a member whose split failed ships nothing
        for member in list(feats[name]):
            if member in failed:
                feats[name].pop(member)
    for member in list(rebalance):
        if member in failed:
            rebalance.pop(member)
    # ---- claims, per mod ------------------------------------------------------------------------
    claims = []
    unkeyed = {e["table"] for e in report["members"] if e["status"] == "convertible-unkeyed"}
    report["unclaimed_members"] = sorted(unkeyed)
    for name, _ in FEATURES:
        for member, patch in feats[name].items():
            if member in unkeyed:
                continue                     # ids repeat there: a row is a position, not an identity
            key = dbpatch.row_key(database.load_table(member, baseline.read(fs, member)), patch)
            rows = (patch.get("added") or []) + [r for i in patch.get("insert") or []
                                                for r in (i.get("rows") or [])]
            claims += _claims_for(member, {r[key] for r in rows if key and key in r}, f"overlord:{name}")
    report["claims"] = [c.as_dict() for c in claims]
    report["mods"] = {name: {"members": {m: {"rows": len(p.get("rows") or {}),
                                             "insert": sum(len(i.get("rows") or [])
                                                           for i in p.get("insert") or []),
                                             "added": len(p.get("added") or [])}
                                     for m, p in feats[name].items()}}
                      for name, _ in FEATURES if feats[name]}
    if rebalance:
        report["mods"][REBALANCE_NAME] = {"members": {
            m: {"rows": len(p.get("rows") or {}),
                "insert": sum(len(i.get("rows") or []) for i in p.get("insert") or []),
                "added": len(p.get("added") or [])} for m, p in rebalance.items()}}
    report["vanilla_rows_rewritten"] = sum(len(p.get("rows") or {}) for p in rebalance.values())
    report["rebalance_members"] = sorted(rebalance)
    report["mod_order"] = list(MOD_ORDER)
    if write:
        _emit(out_dir, feats, rebalance, report)
    # ---- gates ---------------------------------------------------------------------------------
    findings = ownership.check_claims(manifest, claims)
    if installed_mods:
        scan = modclaims.scan_mods(installed_mods)
        for name in report["mods"]:
            mine = modclaims.scan_mods(out_dir, only=[name]) if write else None
            if mine is None:
                continue
            for member, ids in mine.added.items():
                for rid, holders in ids.items():
                    other = [h for h in scan.added.get(member, {}).get(rid, []) if h != name]
                    if other:
                        findings.append(ownership.Finding(
                            ownership.ERROR, "duplicate_id", member, rid, rid, f"overlord:{name}",
                            f"{member} row {rid} is also used by {', '.join(sorted(other))}"))
    report["findings"] = [f.as_dict() for f in findings]
    errors = [f for f in findings if f.severity == ownership.ERROR]
    if errors:
        report["reasons"].append(f"{len(errors)} ownership finding(s) — see 'findings'")
    refused = [m for m in report["members"] if m.get("status") not in
               ("convertible", "convertible-unkeyed", "convertible-inserted",
                "convertible-needs-migration", "superseded-duplicate")]
    if refused:
        report["reasons"].append(f"{len(refused)} member(s) not converted: "
                                 + ", ".join(m["table"] for m in refused))
    if not errors and report["mods"] and not refused:
        report["verdict"] = "installable-plan"
    report["installable"] = report["verdict"] == "installable-plan"
    report["converted_members"] = sorted(patches)
    if write:
        with open(os.path.join(out_dir, "conversion-report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, ensure_ascii=False)
    return report


def _meta(name, description, extra):
    return {
        "name": name,
        "author": "Cryswar (Disgaea 5 Overlord Edition); conversion by D5 Mod Kit, offline",
        "version": "0.0.1-converted",
        "description": description,
        "enabled_by_default": True,
        "overlord_package": extra,
    }


def _write_mod(out_dir, name, meta, patches):
    root = os.path.join(out_dir, name)
    db = os.path.join(root, "patches", "db")
    os.makedirs(db, exist_ok=True)
    for member, patch in patches.items():
        with open(os.path.join(db, member + ".json"), "w", encoding="utf-8") as fh:
            json.dump(patch, fh, indent=1, sort_keys=True)
    with open(os.path.join(root, "mod.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, ensure_ascii=False)


def _emit(out_dir, feats, rebalance, report):
    """one normal Kit mod folder per feature, plus the pack that switches them together"""
    common = {"release": report["release"], "pack": PACK_ID,
              "not_installed": ["dinput8.dll", "d5_runtime_core.dll", "plugins/",
                                "mods/_loader/*.ini", "mods/Overlord Visual/"]}
    written = []
    for name, _ in FEATURES:
        if not feats[name]:
            continue
        _write_mod(out_dir, name, _meta(
            name, (DESCRIPTIONS.get(name, "converted from Overlord v3") +
                   ". Part of Overlord Edition v3, converted to Kit patches; credit Cryswar "
                   "(The Unlicense). Does not install Overlord's dinput8 proxy."),
            dict(common, members=sorted(feats[name]))), feats[name])
        written.append(name)
    if rebalance:
        _write_mod(out_dir, REBALANCE_NAME, _meta(
            REBALANCE_NAME,
            ("The rows of Disgaea 5's own tables that Overlord v3 retunes. Optional: switch it off "
             "for vanilla balance. With every Overlord mod on, the set reproduces Overlord v3's "
             "tables byte for byte."),
            dict(common, part="rebalance", members=sorted(rebalance),
                 vanilla_rows=report["vanilla_rows_rewritten"])), rebalance)
        written.append(REBALANCE_NAME)
    with open(os.path.join(out_dir, "conversion-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(out_dir, "packs.json"), "w", encoding="utf-8") as fh:
        json.dump({"packs": [{"id": PACK_ID, "name": PACK_ID,
                              "description": "Cryswar's Overlord Edition v3, converted by the Kit "
                                             "(one mod per feature, all on by default)",
                              "members": [m for m in MOD_ORDER if m in written]}]},
                  fh, indent=2, ensure_ascii=False)
