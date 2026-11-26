#!/usr/bin/env python3
"""DD2VOICE5 offline checks on staged Disgaea D2 voice packs (reads only; extends check_dd2voice4.py).

    D5Modkit/.venv-macos/bin/python tools/check_dd2voice5.py --staged <bundle>/mods --installed <kit>/mods [--v4 <DD2VOICE4 mods>]

1. BANK CONTROL: every staged kind-0 line's situations equal exactly the union of its battle columns' routes
   (0 -> 0, 1 -> 2, 2 -> 3, 4, 4 -> 6, 5 -> 9, 6 -> 10, 7 -> 11, 9 -> 13), derived here from the selector map rows, not from
   dd2voice. Kind 1-3 lines are never new or larger than installed. Kept clips are byte-identical.
2. V4 CONTROL (--v4): everything the DD2VOICE4 staged build routed still routes the same: every v4 line is still there with
   a superset of its situations, and the only additions are the new columns' (2, 6, 13 on kind 0).
3. ASKED GATE (+ negative control): every kind-0 situation a staged pack serves is asked for by the game (vanilla script
   voice commands + the engine's kind-0 callers of sound_voice_play_random_for_set).
4. SPELL GATE (+ negative control): a skill-cue column (1, 4, 9) never lands on D5 situation 4 (the elemental spell
   cast shout), and no cue destination is asked for by any vanilla spell script (skill_type 2).
5. DUAL USE (+ negative control): a clip that two battle columns of different roles list plays in both destinations and
   the receipt's dual_use names it with a label; every dual-use clip in the selector rows is listed, none invented.
6. RECEIPT: every column the character's rows list is routed or held_back with a reason from the fixed vocabulary; the
   reasons are the routes file's; none unproven/unknown.
Exit 1 on any failure.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

ENGINE = {3: "deploy_select_s0_update 0x14054f830", 4: "turn_ctl_s3_update 0x1405f9fb0; FUN_1408286d0; FUN_140829390",
          0xb: "throw_ctl_s0_update 0x1406335c0", 0xd: "turn_unit_auto_walk_step 0x14052e920; FUN_140853720",
          0xf: "specials_fieldfx_tick 0x1404a7be0", 0x12: "forecast_steal_attempt 0x14062bdb0",
          0x14: "s37_dismiss_browser_update 0x140652580; FUN_140695870; FUN_14069a770"}
ROUTES0 = {0: [0], 1: [2], 2: [3, 4], 4: [6], 5: [9], 6: [10], 7: [11], 9: [13]}     # battle columns -> kind-0 situations
ROLE = {0: "attack", 1: "skill_cue", 2: "deploy_cast", 4: "skill_cue", 5: "heal_cast", 6: "lift", 7: "throw", 9: "move_dash"}
CUE_SLOTS = (1, 4, 9)
VOCAB = ("no_d5_situation", "not_called_in_source", "no_place_found", "unproven", "unknown")
GAME = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)")


def script_cats():
    """({category asked by any script}, {category asked by a spell script (skill_type 2)})"""
    from d5lib import database, skills
    from d5lib.gamefs import GameFS
    fs = GameFS(str(GAME))
    sc = skills.vanilla_scripts(fs)
    t = database.load_table("magic.dat", fs.read("Database/Database_0.dat/magic.dat"))
    allc, spell = set(), set()
    for eid in sc.ev:
        for line in (sc.text(eid) or "").splitlines():
            m = re.search(r"voice_play_actor (\d+)", line)
            if m:
                allc.add(int(m.group(1)) // 10000)
    for r in t.rows:
        root = sc.root_of(int(r["id"]))
        if root and int(r["skill_type"]) == 2:
            for e in sc.tree(root):
                for line in (sc.text(e) or "").splitlines():
                    m = re.search(r"voice_play_actor (\d+)", line)
                    if m and int(m.group(1)) % 10000 == 0:
                        spell.add(int(m.group(1)) // 10000)
    return allc, spell


def lines_of(pack):
    d = json.loads((pack / "patches/voices/voices.json").read_text())
    (vid, v), = d["voices"].items()
    return int(vid), v["lines"]


def key(ln):
    return ln.get("personality", -1), ln["source_voice_id"], ln["kind"]


def unasked(lines, asked):
    return sorted({c for ln in lines if ln["kind"] == 0 for c in ln["cats"] if c not in asked})


def expected0(var, vsrc, rows):
    """kind-0 situations the selector rows give a clip (variant -1 = every personality)"""
    want = set()
    for slot, cats in ROUTES0.items():
        for v in ([var] if var >= 0 else range(3)):
            if vsrc in rows.get((v, slot), ()):
                want |= set(cats)
    return want


def roles_of(var, vsrc, rows):
    return {ROLE[s] for s in ROUTES0 for v in ([var] if var >= 0 else range(3)) if vsrc in rows.get((v, s), ())}


def spell_problems(lines, rows, spell):
    """cue clips (slot 1/4/9 only) on situation 4, or a cue destination a spell script asks for"""
    bad = []
    for ln in lines:
        if ln["kind"] != 0:
            continue
        var, vsrc = ln.get("personality", -1), ln["source_voice_id"]
        in_cue = any(vsrc in rows.get((v, s), ()) for s in CUE_SLOTS for v in ([var] if var >= 0 else range(3)))
        in_cast = any(vsrc in rows.get((v, 2), ()) for v in ([var] if var >= 0 else range(3)))
        if 4 in ln["cats"] and not in_cast:
            bad.append(f"clip {vsrc} plays on situation 4 (spell cast) but is not in slot 2")
    for s in CUE_SLOTS:
        bad += [f"cue slot {s} -> {c} is asked for by a spell script" for c in ROUTES0[s] if c in spell]
    return bad


def dual_problems(lines, rows, receipt):
    """receipt dual_use must equal the selector rows' multi-role clips, each with a label, and the lines must play in each"""
    bad = []
    want = {}
    for ln in lines:
        if ln["kind"] != 0:
            continue
        var, vsrc = ln.get("personality", -1), ln["source_voice_id"]
        if len(roles_of(var, vsrc, rows)) > 1:
            want[(var, vsrc)] = set(ln["cats"])
    got = {(d["personality"], d["clip"]): d for d in receipt.get("dual_use", [])}
    for k in sorted(set(want) - set(got)):
        bad.append(f"dual-use clip {k} plays in {sorted(want[k])} but the receipt's dual_use does not name it")
    for k in sorted(set(got) - set(want)):
        bad.append(f"dual_use names {k} but its clip has one role in the selector rows")
    for k, d in got.items():
        if not d.get("label"):
            bad.append(f"dual_use {k} has no label")
    return bad


def receipt_problems(receipt, char, cls, routed_cols, doc):
    bad = []
    hb = receipt["held_back"]
    for r in char["rows"]:
        cat, var, col = r.split(":")
        if int(var) > (2 if cls else 0):
            continue
        c = f"{cat}:{col}"
        if c not in routed_cols and c not in hb:
            bad.append(f"column {c} neither routed nor held_back")
    for c, h in hb.items():
        if h["reason"] not in VOCAB:
            bad.append(f"{c}: reason {h['reason']!r} not in the vocabulary")
        if h["reason"] != doc.get(c, {}).get("hold_reason", "unknown"):
            bad.append(f"{c}: reason differs from the routes file")
        if h["reason"] in ("unproven", "unknown"):
            bad.append(f"{c}: held for reason {h['reason']} (holds the row at partial)")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", type=Path, required=True)
    ap.add_argument("--installed", type=Path, required=True)
    ap.add_argument("--v4", type=Path, help="the DD2VOICE4 staged mods: its routes must all be kept")
    a = ap.parse_args()
    from d5lib import dd2voice
    m = dd2voice.voice_map()
    doc = dd2voice.route_doc()
    routes_file = dd2voice.routes()
    allc, spell = script_cats()
    asked = allc | set(ENGINE)
    bad = []
    packs = sorted(p for p in a.staged.iterdir() if (p / "mod.json").is_file())
    last = None
    for p in packs:
        old, new = a.installed / p.name, p
        vid, nl = lines_of(new)
        _o, ol = lines_of(old)
        key_new, key_old = {key(x): x for x in nl}, {key(x): x for x in ol}
        rec = json.loads((new / "patches/voices/dd2-voice-receipt.json").read_text())["voices"][0]
        char = m["characters"][str(rec["voice_key"])]
        cls = p.name.startswith("DD2_Class_")
        rows = {}
        for r, ids in char["rows"].items():
            cat, var, col = map(int, r.split(":"))
            if cat == 0 and var <= (2 if cls else 0):
                rows[(var, col)] = set(ids)
        n_same = n_new = 0
        for k, ln in key_new.items():
            var, vsrc, kind = k
            if kind == 0:
                want = expected0(var, vsrc, rows)
                if set(ln["cats"]) != want:
                    bad.append(f"{p.name}: line {k} cats {sorted(ln['cats'])} != expected {sorted(want)}")
            elif k not in key_old or not set(ln["cats"]) <= set(key_old[k]["cats"]):
                bad.append(f"{p.name}: non-battle line {k} is new or grew")
            if k in key_old:
                for dub, fn in ln["files"].items():
                    f0, f1 = old / "patches/voices" / key_old[k]["files"][dub], new / "patches/voices" / fn
                    if f0.name != f1.name or hashlib.sha256(f0.read_bytes()).digest() != hashlib.sha256(f1.read_bytes()).digest():
                        bad.append(f"{p.name}: clip {fn} changed")
            n_same += k in key_old and set(ln["cats"]) == set(key_old[k]["cats"])
            n_new += k not in key_old
        # v4 control
        v4txt = ""
        if a.v4:
            _v, vl = lines_of(a.v4 / p.name)
            kv = {key(x): x for x in vl}
            lost = [k for k, x in kv.items() if k not in key_new or not set(x["cats"]) <= set(key_new[k]["cats"])]
            extra = {c for k, x in key_new.items() if k[2] == 0 for c in x["cats"]} - {c for x in vl if x["kind"] == 0 for c in x["cats"]}
            added = sum(1 for k, x in key_new.items() if k in kv and set(x["cats"]) != set(kv[k]["cats"]))
            v4txt = f"; v4 lines kept {len(kv) - len(lost)}/{len(kv)}, grew {added}, new situations {sorted(extra)}"
            bad += [f"{p.name}: DD2VOICE4 line {k} no longer routes the same" for k in lost]
            for k, x in key_new.items():
                if k in kv and k[2] == 0:
                    grown = set(x["cats"]) - set(kv[k]["cats"])
                    if not grown <= {2, 6, 13}:
                        bad.append(f"{p.name}: line {k} gained {sorted(grown)} beyond the new cue columns")
            if not extra <= {2, 6, 13}:
                bad.append(f"{p.name}: new kind-0 situations {sorted(extra)} beyond 2, 6, 13")
        # spell gate, dual use, receipt
        bad += [f"{p.name}: {x}" for x in spell_problems(nl, rows, spell)]
        bad += [f"{p.name}: {x}" for x in dual_problems(nl, rows, rec)]
        routed_cols = set(routes_file)
        bad += [f"{p.name}: {x}" for x in receipt_problems(rec, char, cls, routed_cols, doc)]
        if unasked(nl, asked):
            bad.append(f"{p.name}: kind-0 situation(s) {unasked(nl, asked)} are never asked for by the game")
        print(f"{p.name}: lines {len(nl)} (installed {len(ol)}), same {n_same}, new {n_new}, dual-use clips {len(rec['dual_use'])}, "
              f"held by reason {rec['held_by_reason']}{v4txt}")
        last = (nl, rows, rec, cls)
    nl, rows, rec, cls = last
    # negative controls
    never = next(c for c in range(22) if c not in asked)
    ok1 = unasked(nl + [dict(kind=0, cats=[never])], asked) == [never]
    # a cue clip (slot 1/4/9 only) given situation 4
    cue = next((ln for ln in nl if ln["kind"] == 0 and not any(ln["source_voice_id"] in rows.get((v, 2), ()) for v in range(3))
                and any(ln["source_voice_id"] in rows.get((v, s), ()) for s in CUE_SLOTS for v in range(3))), None)
    ok2 = cue is not None and bool(spell_problems([dict(cue, cats=sorted(set(cue["cats"]) | {4}))], rows, spell))
    # an attack clip also given the move destination 13; and a dual-use list with its label removed
    att = next((ln for ln in nl if ln["kind"] == 0 and roles_of(ln.get("personality", -1), ln["source_voice_id"], rows) == {"attack"}), None)
    ok3 = att is not None and expected0(att.get("personality", -1), att["source_voice_id"], rows) != set(att["cats"]) | {13}
    dual = next((d for p in packs for d in json.loads((p / "patches/voices/dd2-voice-receipt.json").read_text())["voices"][0]["dual_use"]), None)
    strip = dict(rec, dual_use=[dict(dual, label="")] if dual else [])
    ok4 = bool(dual) and any("no label" in x for x in dual_problems(nl, rows, strip))
    ok5 = bool(receipt_problems(dict(rec, held_back=dict(rec["held_back"], **{"0:3": dict(reason="unproven", clips=[], also_routed=[])})),
                                {"rows": {"0:0:3": []}}, False, set(), doc))
    print(f"asked kind-0 situations: {sorted(asked)}; spell-script categories {sorted(spell)}; cue destinations 2, 6, 13 "
          f"{'not asked by a spell script' if not ({2, 6, 13} & spell) else 'ASKED BY A SPELL SCRIPT'}")
    for name, ok in (("unasked situation", ok1), ("cue clip on 4", ok2), ("attack clip on 13", ok3), ("dual-use label removed", ok4),
                     ("held as unproven", ok5)):
        print(f"negative control {name}: {'flagged' if ok else 'NOT flagged'}")
        if not ok:
            bad.append(f"negative control {name} did not fire")
    for b in bad:
        print("FAIL", b)
    print("PASS" if not bad else f"FAIL ({len(bad)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
