#!/usr/bin/env python3
"""DD2VOICE4 offline checks on staged Disgaea D2 voice packs (reads only).

    D5Modkit/.venv-macos/bin/python tools/check_dd2voice4.py --staged <bundle>/mods --installed <kit>/mods

1. CONTROL (bank level): every staged kind-0 line's situations equal exactly the union of its battle columns' routes
   (0 -> 0, 2 -> 3, 4, 5 -> 9, 6 -> 10, 7 -> 11), derived here from the selector map rows, not from dd2voice; kind 1-3 lines
   are never new or larger than installed; kept clips are byte-identical; prints per (kind, situation) line counts
   installed -> staged and every destination that went silent.
2. ASKED GATE: every kind-0 situation a staged pack serves is one the game asks for: script voice commands in the vanilla
   Disgaea 5 script.dat (voice_play_actor, operand / 10000, kind 0 by decomp 0x14018c650) plus the engine's own
   kind-0 callers of sound_voice_play_random_for_set 0x1402277b0 (ENGINE below, read from the decomp).
   NEGATIVE CONTROL: a copy of a pack with a line to a kind-0 situation the game never asks for must be flagged.
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

# kind-0 engine callers (decomp /Volumes/Data/Decomp/d5/functions, cmdmenu_util_voice_key(unit, 0) then the call)
ENGINE = {3: "deploy_select_s0_update 0x14054f830 (after deploy_env_unit_img_after_dispatch)",
          4: "turn_ctl_s3_update 0x1405f9fb0; FUN_1408286d0; FUN_140829390",
          0xb: "throw_ctl_s0_update 0x1406335c0", 0xd: "turn_unit_auto_walk_step 0x14052e920; FUN_140853720",
          0xf: "specials_fieldfx_tick 0x1404a7be0", 0x12: "forecast_steal_attempt 0x14062bdb0",
          0x14: "s37_dismiss_browser_update 0x140652580; FUN_140695870; FUN_14069a770"}
ROUTES0 = {0: [0], 2: [3, 4], 5: [9], 6: [10], 7: [11]}     # battle columns shipped -> kind-0 situations (slot 9 held)
GAME = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)")


def script_asked():
    from d5lib import skills
    from d5lib.gamefs import GameFS
    sc = skills.vanilla_scripts(GameFS(str(GAME)))
    cats = set()
    for eid in sc.ev:
        for line in (sc.text(eid) or "").splitlines():
            m = re.search(r"voice_play_actor (\d+)", line)
            if m:
                cats.add(int(m.group(1)) // 10000)
    return cats


def lines_of(pack):
    d = json.loads((pack / "patches/voices/voices.json").read_text())
    (vid, v), = d["voices"].items()
    return int(vid), v["lines"]


def key(ln):
    return ln.get("personality", -1), ln["source_voice_id"], ln["kind"]


def unasked(lines, asked):
    """kind-0 situations a pack's lines serve that the game never asks for"""
    return sorted({c for ln in lines if ln["kind"] == 0 for c in ln["cats"] if c not in asked})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", type=Path, required=True)
    ap.add_argument("--installed", type=Path, required=True)
    a = ap.parse_args()
    from d5lib import dd2voice
    m = dd2voice.voice_map()
    asked = script_asked() | set(ENGINE)
    bad = []
    packs = sorted(p for p in a.staged.iterdir() if (p / "mod.json").is_file())
    for p in packs:
        old, new = a.installed / p.name, p
        vid, nl = lines_of(new)
        _o, ol = lines_of(old)
        key_new, key_old = {key(x): x for x in nl}, {key(x): x for x in ol}
        meta = json.loads((new / "patches/voices/dd2-voice-receipt.json").read_text())["voices"][0]
        char = m["characters"][str(meta["voice_key"])]
        cls = p.name.startswith("DD2_Class_")
        rows = {}                                              # (variant, slot) -> clip ids, battle category only
        for r, ids in char["rows"].items():
            cat, var, col = map(int, r.split(":"))
            if cat == 0 and var <= (2 if cls else 0):
                rows[(var, col)] = set(ids)
        n_same = n_new = n_cut = 0
        for k, ln in key_new.items():
            var, vsrc, kind = k
            if kind == 0:                                      # exact: union of the battle columns this clip is in
                want = set()
                for slot, cats in ROUTES0.items():
                    for v in ([var] if var >= 0 else range(3)):
                        if vsrc in rows.get((v, slot), ()):
                            want |= set(cats)
                if set(ln["cats"]) != want:
                    bad.append(f"{p.name}: line {k} cats {sorted(ln['cats'])} != expected {sorted(want)}")
            elif k not in key_old or not set(ln["cats"]) <= set(key_old[k]["cats"]):
                bad.append(f"{p.name}: non-battle line {k} is new or grew")
            if k in key_old:
                for dub, fn in ln["files"].items():            # a kept clip is byte-identical to the installed one
                    f0, f1 = old / "patches/voices" / key_old[k]["files"][dub], new / "patches/voices" / fn
                    if f0.name != f1.name or hashlib.sha256(f0.read_bytes()).digest() != hashlib.sha256(f1.read_bytes()).digest():
                        bad.append(f"{p.name}: clip {fn} changed")
            n_same += k in key_old and set(ln["cats"]) == set(key_old[k]["cats"])
            n_new += k not in key_old
        n_cut = sum(1 for k, ln in key_old.items() if k not in key_new or set(key_new[k]["cats"]) != set(ln["cats"]))

        def pairs(lines):                                      # (kind, situation) -> line count
            out = {}
            for x in lines:
                for c in x["cats"]:
                    out[(x["kind"], c)] = out.get((x["kind"], c), 0) + 1
            return out
        po, pn = pairs(ol), pairs(nl)
        silent = sorted(k for k in po if k not in pn)
        fell = {k: (po[k], pn.get(k, 0)) for k in sorted(po) if pn.get(k, 0) < po[k] and k[0] == 0}
        print(f"{p.name}: lines same {n_same}, changed/removed {n_cut}, new {n_new}; (kind,situation) lines installed -> staged "
              + ", ".join(f"{k[0]}:{k[1]} {a}->{b}" for k, (a, b) in fell.items()) + f"; destinations now silent: {silent or 'none'}")
        if unasked(nl, asked):
            bad.append(f"{p.name}: kind-0 situation(s) {unasked(nl, asked)} are never asked for by the game")
    # negative control: the same gate on a copy of the last pack with one extra line to an unasked kind-0 situation
    never = next(c for c in range(22) if c not in asked)
    flagged = unasked(nl + [dict(kind=0, cats=[never])], asked)
    print(f"asked kind-0 situations: {sorted(asked)}; negative control situation {never}: "
          f"{'flagged ' + str(flagged) if flagged == [never] else 'NOT flagged'}")
    if flagged != [never]:
        bad.append("negative control did not fire")
    for b in bad:
        print("FAIL", b)
    print("PASS" if not bad else f"FAIL ({len(bad)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
