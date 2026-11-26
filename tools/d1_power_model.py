#!/usr/bin/env python3
"""D1POWER1: can a Disgaea 1 special's raw power be converted to a D5 magic.dat power % from the two damage formulas?

Answer (2026-11-10): no.  On the 29 physical moves both games ship, the formula model misses D5's real value by
54-180 points on average (depending on the reference level); the stand-in rule misses by 24.  So the 90 D1C rows
keep the stand-in's power (SPECIALS2 behaviour, unchanged).  This tool reproduces that decision.

Disgaea 1 PC dis1_st.exe (decomp /Volumes/Data/Decomp/d1), mean rolls, no geo/combo/status bonus:
  normal attack  FUN_0046f670: atk = (90+rng21) * ATK / 30         def = (45+rng16) * DEF / 30
  special        FUN_0046fdc0: atk = (90+rng21) * (ATK + v) / 20   def = (45+rng16) * DEF / 20      (category 2)
                 v = power * L / 100, L = soft(level + 100) (FUN_0046f5e0: half above 500, a fifth above 1000, >= 25)
                 bow (weapon 4): ATK+HIT(+2v) over 40 / 60; gun (5): HIT(+v) over 27 / 40
                 then damage = (atk - def) / 10 * skill-level factor (0x532bf0: 90, 100, 103 ... ; level 1 = 100)
  => a D1 special is 1.5x a normal hit before its power counts.
Disgaea 5 (decomp /Volumes/Data/Decomp/d5; Sorrow battle__damage.md D.1/D.3/D.5):
  compute_target 0x1401BE860: plain attack value = ATK; effect_list 0x1401BFAE0 kind 1: ATK * (val + 100) / 100,
  effect_value 0x1401D7A20: val = effect1_value + power_lv[skill level] - 100; raw = value - DEF / 2
  => special / normal (attack value) = (power_lv1 + effect1_value) / 100, power_lv1 = 100.
Both games create stats as base * (47..53) * (level + 1) / 100 (statfidelity), so the attacker's ATK at a level is
0.5 * base * (level + 1) * aptitude.

    python tools/d1_power_model.py [--json OUT]     validation table (reads Disgaea Source + clean D5, read-only)
"""
import json
import statistics as st
import struct
import sys
from pathlib import Path

D1_SKILL_LEVEL = (90, 100, 103, 106, 109, 112, 115, 118, 121, 124)   # dis1_st.exe 0x532bf0 (first 10 of 40)


def soft(x):
    """FUN_0046f5e0 on level + 100 (the caller floors it at 25)."""
    x = max(25, x)
    return x if x <= 500 else (500 + (x - 500) // 2 if x <= 1000 else 750 + (x - 1000) // 5)


def d1_ratio(power, level, atk, dfn=0.0, hit=0.0, weapon=0):
    """D1 damage of a level-1 special over a normal hit by the same unit (mean rolls; dfn = target DEF)."""
    v = power * soft(level + 100) / 100
    if weapon == 4:
        s, n, ds, dn = 2.5 * (atk + hit + 2 * v), (100 / 60) * (atk + hit), 52.5 / 20, 52.5 / 30
    elif weapon == 5:
        s, n, ds, dn = (100 / 27) * (hit + v), 2.5 * hit, 52.5 / 27, 52.5 / 40
    else:
        s, n, ds, dn = 5 * (atk + v), (100 / 30) * atk, 52.5 / 20, 52.5 / 30
    return (s - ds * dfn) / (n - dn * dfn) * D1_SKILL_LEVEL[1] / 100


def d5_percent(ratio, atk=1.0, dfn=0.0, power_lv1=100):
    """effect1_value giving D5 the same special / normal damage ratio (raw = ATK * m - DEF / 2)."""
    m = (ratio * (atk - dfn / 2) + dfn / 2) / atk
    return 100 * m - power_lv1


def predict(power, base, apt, level, weapon=0, defence=False):
    """D5 % for a D1 special of `power` used at `level` by a unit with D1 native base/aptitude (HP SP ATK DEF INT SPD HIT RES)."""
    k = [0.5 * base[i] * (level + 1) * apt[i] / 10 for i in range(8)]
    dfn = k[3] if defence else 0.0
    return d5_percent(d1_ratio(power, level, k[2], dfn, k[6], weapon), k[2], dfn)


def _standin_power(d5, s, twin):
    """effect1_value of the D5 skill srcskills.pick_standin would choose for this move if D5 lacked it (bank check
    left out: no pack).  Same scoring terms; the twin and same-named rows are excluded."""
    from d5lib import srcskills
    q0 = d5.rows[twin]
    am, rg, body = int(q0["attack_map"]), int(q0["range"]), 1 if int(q0["skill_group"]) == 9 else 0
    tier, best = min(int(q0["rank"]), 3), None
    for q in d5.pool():
        qid, same = int(q["id"]), int(q["attack_map"]) == am
        if qid == twin or srcskills.norm(q["name_EN"]) == srcskills.norm(q0["name_EN"]) or (int(q["moves_units"]) and not same):
            continue
        geom = 0 if same and int(q["range"]) == rg else 1 if same or (
            bool(int(q["range"])) == bool(rg) and len(d5.maps.get(int(q["attack_map"]), ())) == len(d5.maps.get(am, ()))) \
            else 2 if bool(int(q["range"])) == bool(rg) else 3
        sc = (4 * geom + 2 * (int(q["element"]) != s["element"]) + 2 * abs(min(int(q["rank"]), 3) - tier)
              + 5 * ((int(q["skill_group"]) == 9) != (body == 1)) + (int(q["formula"]) != s["formula"]),
              abs(int(q["sp_cost"]) - (s["sp"] or 0)), qid)
        if best is None or sc < best[0]:
            best = (sc, qid)
    return int(d5.rows[best[1]]["effect1_value"]), best[1]


def validate():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from d5lib import d1skill, srcskills
    table, _, handle = srcskills.d1c_table()
    d5 = srcskills.D5()
    raw = handle.member(43)
    chars, learners = {}, {}
    for i in range(struct.unpack_from("<I", raw)[0]):
        r = raw[8 + 224 * i:8 + 224 * (i + 1)]
        cid = struct.unpack_from("<H", r, 94)[0]
        chars.setdefault(cid, (struct.unpack_from("<8H", r, 106), r[84:92]))
        for sid, lv in zip(struct.unpack_from("<20H", r, 0x90), struct.unpack_from("<20H", r, 0xB8)):
            if sid:
                learners.setdefault(sid, []).append((cid, lv))
    pool = {c for v in learners.values() for c, _ in v}
    ref = (tuple(int(st.median(chars[c][0][i] for c in pool)) for i in range(8)), bytes([10] * 8))
    wcode = {v: k for k, v in d1skill.WEAPON_TYPES.items()}
    rows = []
    for s in sorted(table.values(), key=lambda s: s["id"]):
        twin = d5.twin(s)[0] if s["formula"] == 2 else None
        if twin is None or int(d5.rows[twin]["formula"]) != 2 or int(d5.rows[twin]["effect1_type"]) != 1:
            continue
        users = [(chars[c], lv) for c, lv in learners.get(s["id"], []) if c in chars]
        w = wcode.get(s["weapon"], 0)
        row = dict(id=s["id"], name=s["name"], d1_power=s["power_raw"], d5_real=int(d5.rows[twin]["effect1_value"]))
        row["model_learn_level"] = round(st.median(predict(s["power_raw"], *c, max(lv, 1), w) for c, lv in users)) if users else None
        for lv in (10, 100):
            row[f"model_level_{lv}"] = round(st.median(predict(s["power_raw"], *c, lv, w) for c, _ in users or [(ref, 0)]))
        row["standin"], row["standin_id"] = _standin_power(d5, s, twin)
        rows.append(row)
    scores = {}
    for key in ("model_learn_level", "model_level_10", "model_level_100", "standin"):
        xs = [(r[key], r["d5_real"]) for r in rows if r[key] is not None]
        err = [abs(a - b) for a, b in xs]
        scores[key] = dict(n=len(xs), mean_abs_error=round(st.mean(err), 1), median=st.median(err), worst=max(err))
    scores["copy_raw"] = dict(n=len(rows), mean_abs_error=round(st.mean(abs(r["d1_power"] - r["d5_real"]) for r in rows), 1),
                              worst=max(abs(r["d1_power"] - r["d5_real"]) for r in rows))
    best_model = min(v["mean_abs_error"] for k, v in scores.items() if k.startswith("model"))
    return dict(rows=rows, scores=scores, adopt=best_model < scores["standin"]["mean_abs_error"])


if __name__ == "__main__":
    res = validate()
    for k, v in res["scores"].items():
        print(f"{k:18} {v}")
    print("adopt formula model:", res["adopt"])
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(res, indent=1, ensure_ascii=False))
