"""Offline source-neutral gameplay mapping to existing D5ModKit char.dat fields.

Faithful means exact *stored static values*, never equivalent engine growth.
No archive reader, installer, new IDs, effect implementation, or global paths.
This is original integration glue; reference Forge readers are not vendored.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import database
from .charstudio import GROUPS, start_fresh

STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")
POLICIES = ("faithful", "adapted-d5")


def from_profile(profile, *, game, edition, rank_count, rank_index=0):
    """Wrap an already extracted classic/modern/RPG profile without donor fill.

    Edition is mandatory: a game key or row ID alone cannot establish provenance.
    Existing source evidence, raw coefficients, limitations and extra fields survive.
    """
    evidence = deepcopy(profile.get("evidence", {}))
    digest = evidence.get("table_sha256", evidence.get("sha256"))
    def vector(name):
        values = profile.get(name)
        return dict(zip(STATS, values, strict=True)) if values is not None else {}
    return validate_description({
        "version": 1,
        "source": {"game": game, "edition": edition, "id": profile["id"],
                   "sha256": digest, "evidence": evidence},
        "name": profile.get("name", ""),
        "rank_count": rank_count, "rank_index": rank_index,
        "stats": vector("base"), "aptitudes": vector("aptitudes"),
        "growth": deepcopy(profile.get("growth")),
        "weapon_preferences": [], "skills": [], "evilities": [],
        "source_profile": deepcopy(profile),
    })


def validate_description(description):
    """Validate source-neutral shape, preserving unknown data rather than coercing it."""
    import re
    def text(v):
        return isinstance(v, str) and bool(v.strip())
    def integer(v, minimum=0):
        return type(v) is int and v >= minimum
    if not isinstance(description, dict) or type(description.get("version")) is not int or description["version"] != 1:
        raise ValueError("description.version must be 1")
    source = description.get("source")
    if not isinstance(source, dict) or not all(text(source.get(k)) for k in ("game", "edition")):
        raise ValueError("source requires game and explicit edition")
    if not integer(source.get("id")) or not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source["sha256"]):
        raise ValueError("source requires integer id and SHA256 (no normalization)")
    count, index = description.get("rank_count"), description.get("rank_index")
    if type(count) is not int or count < 1 or type(index) is not int or not 0 <= index < count:
        raise ValueError("rank_count must be positive; rank_index must be within source ranks")
    for group in ("stats", "aptitudes"):
        values = description.get(group)
        if not isinstance(values, dict) or set(values) - set(STATS):
            raise ValueError(group + " must use canonical stat names")
        if any(v is not None and not integer(v) for v in values.values()):
            raise ValueError(group + " values must be nonnegative integers or null")
    for group in ("skills", "evilities", "weapon_preferences"):
        items = description.get(group)
        if not isinstance(items, list) or any(not isinstance(v, dict) or not text(v.get("name")) for v in items):
            raise ValueError(group + " must be a list of named objects")
        if len({v["name"] for v in items}) != len(items):
            raise ValueError(group + " names must be unique (use source-qualified names)")
        if group == "skills" and any(not integer(v.get("level", 1), 1) or v.get("level", 1) > 9999 for v in items):
            raise ValueError("skill levels must be 1..9999")
    try:
        json.dumps(description, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("description must be finite JSON-compatible data") from exc
    return deepcopy(description)


def map_gameplay(description, *, policy="faithful", rules=(), tables=None):
    """Return a plan/audit, not an install or a claim of gameplay equivalence.

    Rules are caller-reviewed, source-pinned assertions, NOT inferred matches.
    `scope` defaults to "unit": source_game/edition/sha256, source_id and
    source_rank_index must match exactly. Explicit "table" scope permits reuse
    across units/ranks within that game/edition/hash, but still checks any supplied
    source_id/source_rank_index constraints. Both scopes require source_feature:
    the exact source scalar for stats/aptitudes (including explicit null), or the
    complete named object for skills/evilities/weapon_preferences. This is an
    exact JSON predicate, not a subset, coercion, or inferred grade equivalence.
    Missing/mismatched context or predicates raise before any row is encoded.
    Legacy edition/hash-only rules must be deliberately migrated to either scope.
    `tables` supplies actual kit Tables for magic.dat / Skill.dat references.
    Adapted-D5 defaults to a native donor budget; only explicit rules override it.
    Missing ability animations/effects are omitted, not donor-filled or renamed.
    """
    description = validate_description(description)
    if policy not in POLICIES:
        raise ValueError("policy must be faithful or adapted-d5")
    if not isinstance(rules, (list, tuple)):
        raise ValueError("rules must be a list/tuple")
    source = description["source"]
    indexed = {}
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("rules must contain objects")
        kind, name = rule.get("kind"), rule.get("name")
        if kind not in ("stats", "aptitudes", "skills", "evilities", "weapon_preferences") or not isinstance(name, str):
            raise ValueError("rule needs a supported kind and source name")
        available = STATS if kind in ("stats", "aptitudes") else [x["name"] for x in description[kind]]
        if name not in available or (kind, name) in indexed:
            raise ValueError("unknown or duplicate rule source: " + str((kind, name)))
        if rule.get("source_sha256") != source["sha256"] or rule.get("source_edition") != source["edition"]:
            raise ValueError("rule source edition/hash mismatch")
        if rule.get("relation") not in ("exact", "adapted") or not isinstance(rule.get("evidence"), str) or not rule["evidence"].strip():
            raise ValueError("rule needs exact/adapted relation and review evidence")
        try:
            json.dumps(rule, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("rules must be finite JSON-compatible data") from exc
        scope = rule.get("scope", "unit")
        if scope not in ("unit", "table"):
            raise ValueError("rule source scope must be unit or table")
        context = {"source_game": source["game"], "source_id": source["id"],
                   "source_rank_index": description["rank_index"]}
        for key, expected in context.items():
            # Table reuse is deliberate, never permission to ignore supplied pins.
            required = scope == "unit" or key == "source_game" or key in rule
            if required and (type(rule.get(key)) is not type(expected) or rule[key] != expected):
                raise ValueError("rule source context missing or mismatched: " + key)
        feature = (description[kind].get(name) if kind in ("stats", "aptitudes")
                   else next(item for item in description[kind] if item["name"] == name))
        # Full exact JSON predicate binds grades, units and ability metadata too.
        # JSON comparison distinguishes bool/int/float, unlike Python equality.
        if "source_feature" not in rule or json.dumps(rule["source_feature"], sort_keys=True) != json.dumps(feature, sort_keys=True):
            raise ValueError("rule source feature missing or mismatched")
        indexed[kind, name] = deepcopy(rule)
    fields = {f: 0 for group in ("skills", "evilities", "overload") for f in GROUPS[group]}
    mappings, unresolved = [], []
    probe = database.Table("char.dat", database.get_schema("char.dat")).new_row()

    def record(path, status, reason, target=None, rule=None):
        item = {"path": path, "status": status, "reason": reason}
        if target:
            item["target"] = target
        if rule:
            item["rule"] = deepcopy(rule)
        mappings.append(item)
        if status == "unresolved":
            unresolved.append(item)

    def representable(target, value):
        if type(value) is not int or value < 0:
            return False
        try:
            probe.set(target, value)
        except (ValueError, KeyError):
            return False
        return True

    for group, prefix in (("stats", "base_"), ("aptitudes", "apt_")):
        for stat in STATS:
            path, target = f"{group}.{stat}", prefix + stat
            rule = indexed.get((group, stat))
            value = description[group].get(stat)
            if policy == "adapted-d5":
                if rule is None:
                    record(path, "donor-budget", "Explicit adapted-D5 policy retains native donor field", target)
                    continue
                value = rule.get("value")
            elif rule is not None:
                raise ValueError("faithful static fields cannot be overridden; choose adapted-d5")
            if value is None or not representable(target, value):
                record(path, "unresolved", "Source value absent or outside kit field representation; no clipping", rule=rule)
                continue
            fields[target] = value
            record(path, "adapted" if rule else "exact-static",
                   "Explicit D5 budget override" if rule else "Exact stored source integer only; not equal engine progression",
                   target, rule)
    record("growth", "unresolved", "Source/D5 progression equivalence unestablished; no universal conversion")
    if description["rank_count"] > 6:
        record("rank_count", "unresolved", "Source ranks preserved; >6 requires separate native capacity work")
    else:
        record("rank_count", "metadata-only", "Rank count preserved; this API encodes one selected row, not a rank chain")
    slots = {"skills": 0, "evilities": 0}
    used_targets = set()
    weapon_fields = set(GROUPS["mastery"]) - {"mastery_armor"}
    for group in ("weapon_preferences", "skills", "evilities"):
        if not description[group]:
            record(group, "unresolved", "No named source entries supplied; empty is not proof of no source abilities/preferences")
        for item in description[group]:
            path = group + "." + item["name"]
            rule = indexed.get((group, item["name"]))
            if rule is None or (policy == "faithful" and rule["relation"] != "exact"):
                record(path, "unresolved", "No reviewed equivalent rule for selected policy; omitted/backlog", rule=rule)
                continue
            if group == "weapon_preferences":
                target, value = rule.get("target_field"), rule.get("value")
                if not isinstance(target, str) or target not in weapon_fields or not representable(target, value) or target in used_targets:
                    record(path, "unresolved", "Unsupported/duplicate mastery target or unrepresentable reviewed value", rule=rule)
                    continue
                fields[target] = value
            else:
                table_name = "magic.dat" if group == "skills" else "Skill.dat"
                table = (tables or {}).get(table_name)
                sid, target_name = rule.get("target_id"), rule.get("target_name")
                matches = [] if table is None else [r for r in table.rows if r.get("id") == sid]
                if type(sid) is not int or sid <= 0 or len(matches) != 1 or not isinstance(target_name, str) or not target_name or matches[0].get("name_EN") != target_name:
                    record(path, "unresolved", "Target table/id/name missing or ambiguous; IDs alone are not equivalence", rule=rule)
                    continue
                if group == "skills" and rule.get("animation_verified") is not True:
                    record(path, "unresolved", "No reviewed usable D5 animation; omit/backlog", rule=rule)
                    continue
                capacity = 16 if group == "skills" else 4
                next_slot = slots[group] + 1
                target = f"learn{next_slot}_skill" if group == "skills" else f"evility{next_slot}"
                if next_slot > capacity or (group, sid) in used_targets or not representable(target, sid):
                    record(path, "unresolved", "Target duplicated or native character slots/field capacity exceeded", rule=rule)
                    continue
                slots[group] = next_slot
                used_targets.add((group, sid))
                fields[target] = sid
                if group == "skills":
                    fields[f"learn{next_slot}_level"] = item.get("level", 1)
            used_targets.add(target)
            record(path, "mapped-exact-reviewed" if rule["relation"] == "exact" else "adapted",
                   "Caller-reviewed mapping to existing D5 data, not an implementation of source effects", target, rule)
    if slots["skills"]:
        fields["learn_count"] = slots["skills"]
    if slots["evilities"]:
        fields["evility_count"] = slots["evilities"]
    return {"version": 1, "policy": policy, "source": deepcopy(source),
            "rank_count": description["rank_count"], "rank_index": description["rank_index"],
            "description": description, "fields": fields, "mappings": mappings,
            "unresolved": unresolved, "native_tested": False, "encoded": False,
            "fidelity_scope": "stored-static-fields-only; not complete source gameplay"}


def encode_gameplay(row, description, *, policy="faithful", rules=(), tables=None):
    """Return (independent Row copy, report), using real kit field writers.

    Not an install. The caller must persist this row through native pack writers.
    Donor learned skills, innate evilities and Overload are always cleared first.
    """
    report = map_gameplay(description, policy=policy, rules=rules, tables=tables)
    if policy == "faithful" and any(x["path"].startswith(("stats.", "aptitudes.")) for x in report["unresolved"]):
        raise ValueError("Faithful static stats/aptitudes incomplete or unrepresentable; inspect map_gameplay report")
    if report["rank_index"] >= 6:
        raise ValueError("Rank index beyond current six-rank native path; separate capacity work required")
    out = row.copy()
    start_fresh(out)
    for name, value in report["fields"].items():
        out.set(name, value)
    report["fields"] = {k: out[k] for k in out.keys() if out[k] != row[k] or k in report["fields"]}
    managed = set(sum((GROUPS[k] for k in ("base", "apt", "mastery", "move", "res")), []))
    report["donor_retained"] = {k: out[k] for k in sorted(managed - set(report["fields"])) if k in out}
    report["encoded"] = True
    report["donor"] = {"id": row.get("id"), "row_sha256": hashlib.sha256(bytes(row.raw)).hexdigest()}
    report["unchanged_fields"] = sorted(set(row.keys()) - set(report["fields"]))
    return out, report
