"""Overlord's `evilities.ini` -> Kit evility rows, now that five of his effects are native.

The Kit's `.d5el` format was built with Overlord's own model in mind: one evility id, a *list* of
effects, each with its own conditions, later rows adding rather than overwriting
(`d5lib/evility.py`). So an `evilities.ini` section maps almost one-to-one:

    [6314 Damage Dealt]                 ->  "6314": [{"family": "dealt",
    enabled=1                                                  "effects": [{"value": <Skill.dat value1>}]}]
    effect=damage_dealt_percent
    value=ValueA

`ValueA`/`ValueB` are not numbers in the ini: they name `Skill.dat` `value1`/`value2` of that same
row (the release's own `evility_editor.py` says so), so the converter resolves them from the
release's `Skill.dat`.

Verdicts, per section (never a silent drop):

  native      the family exists in the Kit runtime today (`FAMILIES` in d5lib/evility.py)
  new-lane    the family exists only in the OLEFFECTS lane (worktree `oleffects`, f9f747f):
              permanent_revenge, block_overload, steal_on_kill_percent, sp_drain_per_turn
  sign        converted with the value negated: Overlord's "reduction" is a positive number, our
              `taken` is negative for the same meaning (docs in d5lib/evility.py)
  refused     not expressible: no family, a dimension we do not have, or arithmetic that differs
              (ailment_infliction multiplies where we add points; auras are presence-only here)

Offline only: reads the release folder and a vanilla or release table; writes a JSON file.
"""
import configparser
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from d5lib import database   # noqa: E402

# Overlord effect -> (kit family, verdict, extra).  `extra` is the per-effect JSON skeleton that is
# merged with the resolved value; the comment cites where the equivalence (or its limits) is proven.
MAP = {
    # --- native today (P3 and earlier) ---------------------------------------------------------
    "power_percent": ("power", "native", {}),
    "defense_power_percent": ("defense_power", "native", {}),
    "magic_range": ("range", "native", {}),
    "damage_dealt_percent": ("dealt", "native", {}),
    "damage_taken_reduction": ("taken", "sign", {}),
    "hp_regen_percent": ("regen", "native", {}),
    "stat_percent": ("stats", "native", {}),
    "stat_per_unit_in_range": ("stats", "native", {}),
    "stat_conversion_flat": ("conversion", "native", {}),
    "damage_vs_ailment": ("dealt", "native", {}),
    # --- OLEFFECTS lane, 2026-10-29 (needs that lane merged) ------------------------------------
    "permanent_revenge": ("permanent_revenge", "new-lane", {}),
    "block_overload": ("block_overload", "new-lane", {}),
    "sp_drain_per_turn": ("sp_drain_per_turn", "new-lane", {}),
    "steal_on_kill_percent": ("steal_on_kill_percent", "new-lane", {}),
    "stat_per_squad_unit": ("stats", "new-lane", {"per": "squad"}),
    # --- refused: named with the reason, never dropped quietly --------------------------------
    "stat_aura_percent": ("aura", "refused",
                          "our aura tests the *presence* of a provider in range, not how many "
                          "holders; no per-holder stacking and no auto enemy negation"),
    "ailment_infliction": ("status_chance", "refused",
                           "Overlord multiplies the chance ((100+v)/100), ours adds points"),
    "element_resistance_percent": ("taken", "refused",
                                   "aura form: per-holder element resistance is presence-only "
                                   "here, and the holder-state conditions are disabled in "
                                   "Overlord's own editor too"),
    "prevent_ally_damage": (None, "refused", "no family in the Kit runtime"),
    "element_damage_dealt": ("dealt", "native", {}),
    "element_damage_taken_reduction": ("taken", "sign", {}),
    "critical_rate_percent": ("crit_rate", "native", {}),
    "max_hp_percent": ("stats", "unproven",
                       "both mean 'N % max HP' but write different arrays; not settled offline"),
}

STATS = ["ATK", "DEF", "INT", "RES", "HIT", "SPD"]
STAT_NAMES = {k.upper(): k.lower() for k in
              ("ATK", "DEF", "INT", "RES", "HIT", "SPD", "HP", "SP")}
ELEMENTS = {"fire": 1, "wind": 2, "ice": 3, "star": 4}
# Overlord `condition=` values -> our condition kinds.  Revenge mode is status 0x1A in the game's
# status table (the pair OLEFFECTS issues for permanent_revenge), so a "revenge" condition is a
# self_status test on that index; that mapping is an inference from the same status id, not a
# black-box equivalence.
CONDITIONS = {
    "revenge": {"kind": "self_status", "id": 0x1A},
    "attack_element:any": {"kind": "element_any"},
}


class Section:
    def __init__(self, evid, label, values):
        self.evid = evid
        self.label = label
        self.values = values

    def get(self, key, default=None):
        return (self.values.get(key) or default)


def parse(path):
    """`[<id> <label>]` sections, in file order (configparser would merge duplicate ids)."""
    out, cur = [], None
    with open(path, encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                head = line[1:-1].strip().split(None, 1)
                try:
                    evid = int(head[0])
                except (ValueError, IndexError):
                    cur = None
                    continue
                cur = Section(evid, head[1] if len(head) > 1 else "", {})
                out.append(cur)
                continue
            if cur is not None and "=" in line:
                k, v = line.split("=", 1)
                cur.values[k.strip().lower()] = v.strip()
    return out


def resolve_value(section, skill_row):
    """The authored number: ValueA/ValueB from the table row, or Fixed:<n> in the ini."""
    spec = section.get("value", "ValueA")
    low = spec.lower()
    if low in ("valuea", "a"):
        return int(skill_row["value1"]) if skill_row is not None else None
    if low in ("valueb", "b"):
        return int(skill_row["value2"]) if skill_row is not None else None
    if low.startswith("fixed:"):
        return int(spec.split(":", 1)[1])
    try:
        return int(spec)
    except ValueError:
        return None


def _per_scale(section):
    """`target=` + `range=` for stat_per_unit_in_range -> one of our `per` scales."""
    target = (section.get("target") or "allies").strip().lower()
    rng = (section.get("range") or "map").strip().lower()
    rel = {"allies": "ally", "enemies": "enemy", "everyone": "any"}.get(target)
    if rel is None:
        return None
    if rng in ("1", "adjacent"):
        return f"adjacent_{rel}"
    return f"map_{rel}"


def _effect(section, family, value, extra, effect_name=""):
    fx = {"value": value}
    if family == "regen":
        # our regen takes a stat (hp or sp): Overlord's hp_regen_percent is the hp form
        return [{"stat": "hp", "value": value}], None
    if family == "stats":
        stats = section.get("stats")
        if effect_name == "stat_per_unit_in_range":
            per = _per_scale(section)
            if per is None:
                return None, f"target={section.get('target')!r} has no Kit scale"
            return [{"stat": "all", "value": value, "per": per}], None
        if stats:
            names = [s.strip().lower() for s in stats.split(",") if s.strip()]
            if names == ["all"]:
                return [{"stat": "all", "value": value}], None
            entries = []
            for name in names:
                key = STAT_NAMES.get(name.upper(), name.lower())
                entries.append({"stat": key, "value": value})
            return entries, None
        return [{"stat": "all", "value": value}], None
    if family == "conversion":
        src = (section.get("source") or "").lower()
        dst = (section.get("destination") or "").lower()
        if not src or not dst:
            return None, "conversion needs source and destination"
        fx["stat"] = STAT_NAMES.get(dst.upper(), dst)      # destination
        fx["from"] = STAT_NAMES.get(src.upper(), src)      # base source
        return [fx], None
    if family in ("range",) and section.get("magic"):
        kind = section.get("magic").strip().lower()
        if kind not in ("all", "any", ""):
            return None, f"the magic-kind filter (magic={kind}) does not exist in the Kit family"
    if family in ("permanent_revenge", "block_overload"):
        return [], None            # predicates: the row is the effect, no number allowed
    return [fx], None


def convert(ini_path, skill_table, log=None):
    """Return (evilities dict, per-section verdicts). `skill_table` is a d5lib Table of Skill.dat."""
    rows = {}
    verdicts = []
    have = {}
    if skill_table is not None:
        have = {int(r["id"]): r for r in skill_table.rows}
    for sec in parse(ini_path):
        if (sec.get("enabled") or "1") != "1":
            verdicts.append({"id": sec.evid, "label": sec.label, "verdict": "disabled"})
            continue
        name = (sec.get("effect") or "").strip()
        if name not in MAP:
            verdicts.append({"id": sec.evid, "label": sec.label, "verdict": "refused",
                             "reason": f"effect {name!r} is not in the mapping table"})
            continue
        family, verdict, extra = MAP[name]
        if verdict in ("refused", "unproven"):
            reason = extra if isinstance(extra, str) else ""
            verdicts.append({"id": sec.evid, "label": sec.label, "verdict": verdict,
                             "effect": name, "reason": reason})
            continue
        skill_row = have.get(sec.evid)
        value = resolve_value(sec, skill_row)
        if family not in ("permanent_revenge", "block_overload") and value is None:
            verdicts.append({"id": sec.evid, "label": sec.label, "verdict": "refused",
                             "effect": name,
                             "reason": f"value {sec.get('value')!r} cannot be resolved "
                                       f"(no Skill.dat row {sec.evid} in the supplied table)"})
            continue
        effects, why = _effect(sec, family, value, extra, name)
        if effects is None:
            verdicts.append({"id": sec.evid, "label": sec.label, "verdict": "refused",
                             "effect": name, "reason": why})
            continue
        entry = {"family": family, "effects": effects} if effects else {"family": family}
        if verdict == "sign":
            for fx in entry["effects"]:
                fx["value"] = -fx["value"] if fx["value"] is not None else None
        if extra.get("per"):
            for fx in entry["effects"]:
                fx["per"] = extra["per"]
        cond = sec.get("condition")
        if cond:
            key = cond.strip()
            if key in CONDITIONS:
                entry["condition"] = dict(CONDITIONS[key])
            elif key.startswith("attack_element:"):
                el = key.split(":", 1)[1].strip().lower()
                if el == "any":
                    entry["condition"] = {"kind": "element_any"}
                elif el in ELEMENTS:
                    entry["condition"] = {"kind": "element", "id": ELEMENTS[el]}
                else:
                    verdicts.append({"id": sec.evid, "label": sec.label, "verdict": "refused",
                                     "effect": name, "reason": f"unknown element {el!r}"})
                    continue
            else:
                verdicts.append({"id": sec.evid, "label": sec.label, "verdict": "refused",
                                 "effect": name,
                                 "reason": f"condition {key!r} has no Kit equivalent"})
                continue
        el = sec.get("element")
        if el and "condition" not in entry:
            entry["condition"] = {"kind": "element", "id": ELEMENTS.get(el.lower(), 0)}
        rows.setdefault(str(sec.evid), []).append(entry)
        verdicts.append({"id": sec.evid, "label": sec.label, "verdict": verdict,
                         "effect": name, "family": family, "value": value,
                         "converted": entry})
    return {"evilities": rows}, verdicts


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ini")
    ap.add_argument("--skill-table", required=True,
                    help="Skill.dat bytes: the Overlord release's copy (his values) or vanilla")
    ap.add_argument("--out", help="write {'evilities': {...}} here")
    a = ap.parse_args(argv)
    with open(a.skill_table, "rb") as fh:
        table = database.load_table("Skill.dat", fh.read())
    data, verdicts = convert(a.ini, table)
    summary = {}
    for v in verdicts:
        summary[v["verdict"]] = summary.get(v["verdict"], 0) + 1
    print(json.dumps({"sections": len(verdicts), "summary": summary,
                      "evilities": len(data["evilities"])}, indent=1))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"evilities": data["evilities"], "verdicts": verdicts}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
