"""Disgaea RPG outfits for the game's unique characters (catalog: d5lib/data/drpg_outfit_catalog.json).

    python tools/drpg_outfits.py list                     the catalog and what is built
    python tools/drpg_outfits.py check                    every catalog unit has sprites in a known atlas layout
    python tools/drpg_outfits.py learn [CLASS ...]        own-pose maps from the twins (d5lib/data/drpg_ownmap_<cls>.json)
    python tools/drpg_outfits.py build [CLASS ...] [--only UNIT,UNIT] [--rebuild]
                                                          make the outfits (one mod per character, Outfit_System needed)
    python tools/drpg_outfits.py events [CLASS ...]       the skills' event poses in each outfit's look (Killia,
                                                          Seraphina: d5lib.eventpose)

An outfit is a copy of the character (same stats, skills, name) with its own sprite: the character's complete
animation set (shared motions + its own idle and skill poses) drawn with the DRPG unit's drawings (d5lib.drpgmap,
specials=True), colour presets per part derived from the character's own presets, face (mirrored DRPG icon), list
icon, cut-in portrait and the small standing picture.  See docs/OUTFITS.md "DRPG outfits for every character".
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import drpg, drpgmap, modsys, outfits      # noqa: E402
from d5lib.gamefs import GameFS                       # noqa: E402

CATALOG = os.path.join(KIT, "d5lib", "data", "drpg_outfit_catalog.json")
LEARN_REPORT = os.path.join(KIT, "d5lib", "data", "drpg_outfit_twins.json")   # learned characters
GOOD_TWIN = 0.6          # share of the shared motion cells the twin must have exactly


def catalog():
    with open(CATALOG, encoding="utf-8") as f:
        return json.load(f)["characters"]


def game_fs():
    g = paths.require_game_dir()
    return GameFS(g, backup_resolver=modsys.Installer(g, KIT, log=lambda *a: None).backup_resolver)


def _learn(args):
    cls, twin = args
    t = time.time()
    lines = []
    _, rep = drpgmap.learn_unique(game_fs(), cls, twin, log=lines.append)
    rep["seconds"] = round(time.time() - t)
    rep["lines"] = lines
    return cls, twin, rep


def cmd_learn(chars, workers):
    todo = [(c["class"], c["twin"]) for c in chars if "twin" in c and c.get("kind") not in ("monster", "new_character")]
    reps = json.load(open(LEARN_REPORT)) if os.path.exists(LEARN_REPORT) else {}
    with ProcessPoolExecutor(workers) as ex:
        for cls, twin, rep in ex.map(_learn, todo):
            ok = rep["shared_exact"] >= GOOD_TWIN * rep["shared"]
            rep["twin_ok"] = ok
            reps[str(cls)] = dict(rep, twin=twin)
            print(f"{cls} <- DRPG {twin}: shared {rep['shared_exact']}/{rep['shared']} exact, agreement "
                  f"{rep['agreement']}, own {rep['own_exact']}/{rep['own']} exact + {rep['poses']} whole poses, "
                  f"{rep.get('effects', 0)} effect drawings kept "
                  f"({rep['seconds']}s){'' if ok else '  <-- NOT A TWIN'}", flush=True)
            with open(LEARN_REPORT, "w") as f:
                json.dump(reps, f, indent=1)


def cmd_check(chars):
    bad = 0
    for c in chars:
        for uid in [c["twin"]] + [u for u, n in c["outfits"]]:
            try:
                sheets = drpg.unit_sheets(uid)
            except FileNotFoundError:
                print(f"{c['name']}: DRPG {uid} has no sprites")
                bad += 1
                continue
            lay = []
            for key in ("front", "back", "wait_front", "wait_back"):
                name, _, own = drpg.fit_layout(drpg.atlas_pieces(sheets[key]), key)
                lay.append(name or "?")
            ex = drpg.unit_extras(uid)
            miss = [k for k in ("icon", "cutin") if k not in ex]
            if "?" in lay[:2] or miss:
                bad += 1
            print(f"{c['name']:12s} {uid:5d} layouts {'/'.join(lay)}" + (f"  missing {miss}" if miss else ""))
    print(f"{bad} problem(s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "check", "learn", "build", "events"])
    ap.add_argument("classes", nargs="*", type=int)
    ap.add_argument("--only")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    chars = [c for c in catalog() if not a.classes or c["class"] in a.classes]
    if a.cmd == "check":
        cmd_check(chars)
    elif a.cmd == "learn":
        cmd_learn(chars, a.workers)
    elif a.cmd == "list":
        for c in chars:
            print(f"{c['class']:4d} {c['name']:12s} twin {c['twin']:4d}  {len(c['outfits'])} outfits -> {c['mod']}")
        print(sum(len(c["outfits"]) for c in chars), "outfits")
    elif a.cmd == "build":
        cmd_build(chars, {int(x) for x in a.only.split(",")} if a.only else None, a.rebuild)
    elif a.cmd == "events":
        cmd_events(chars)


def cmd_events(chars):
    """every built outfit of a character whose skills spawn an event pose gets that sheet in its look"""
    from d5lib import eventpose
    fs = game_fs()
    mm = modsys.ModManager(KIT)
    for c in chars:
        if c["class"] not in eventpose.EVENT_SHEETS or c.get("kind") == "new_character":
            continue
        mod = mm.get(c["mod"])
        if mod is None:
            continue
        for uid, slot in sorted(built_units(mod).items()):
            t = time.time()
            n = eventpose.create_for_outfit(fs, mod, slot, uid, c["class"], c["twin"], log=print)
            print(f"{c['name']} DRPG {uid} (slot {slot}) -> anm {n} in {time.time() - t:.0f}s", flush=True)


def built_units(mod):
    """{DRPG unit: outfit slot} recorded in the mod (patches/outfits/drpg_units.json)"""
    d = mod.load_patch("outfits", "drpg_units.json") or {}
    return {int(u): int(s) for u, s in d.items()}


def _record(mod, units):
    mod.save_patch("outfits", "drpg_units.json", {str(u): s for u, s in sorted(units.items())} or None)


def description(c):
    looks = ", ".join(n for u, n in c["outfits"])
    if c.get("kind") == "new_character":
        q = (c.get("quest") or {}).get("title")
        return (f"Adds {c['name']} as a new playable character drawn from Disgaea RPG"
                + (f" (recruit quest '{q}')" if q else "") + f", with the outfits {looks}.")
    return f"{c['name']} gets outfits from Disgaea RPG: {looks}."


def get_mod(mm, c):
    mod = mm.get(c["mod"])
    if mod is None:
        mod = mm.create(c["mod"].replace("_", " "), "D5 Mod Kit", description(c))
        mod.meta["requires"] = [outfits.SYSTEM_MOD_ID]
        mod.meta["version"] = "1.0"
        mod.save_meta()
        if mod.id != c["mod"]:
            raise RuntimeError(f"mod folder came out as {mod.id}, expected {c['mod']}")
    return mod


def cmd_build(chars, only, rebuild):
    fs = game_fs()
    mm = modsys.ModManager(KIT)
    learned = json.load(open(LEARN_REPORT)) if os.path.exists(LEARN_REPORT) else {}
    done = []
    for c in chars:
        lr = learned.get(str(c["class"]))
        hybrid = None
        base_id, template = c["class"], None
        if c.get("kind") == "new_character":   # a new humanoid character: created once, outfits attach to it
            mod = get_mod(mm, c)
            rec = mod.load_patch("outfits", "drpg_character.json")
            if not rec:
                r = outfits.create_drpg_character(fs, mod, c["class"], c["template"], c["unit"], c["name"],
                                                  c.get("title"), c.get("skills"), c.get("desc", ()), c.get("quest"),
                                                  log=lambda *a: None, stats_from=c.get("stats_from"))
                rec = {"id": r["id"], "unit": c["unit"], "sprite": r["sprite"], "quest": r["quest"]}
                mod.save_patch("outfits", "drpg_character.json", rec)
                print(f"{c['name']}: new character {r['id']} (DRPG {c['unit']}, anm{r['sprite']:05d}), "
                      f"recruit quest {r['quest']}", flush=True)
            base_id, template = rec["id"], c["template"]
        elif c.get("kind") == "monster":          # drawn through a humanoid template (d5lib.hybridanim)
            from d5lib import hybridanim
            hybrid = dict(template=c["human_template"], sources=getattr(hybridanim, c["sources"]),
                          keep=getattr(hybridanim, c["keep"]))
        elif not lr or not os.path.exists(drpgmap.own_map_path(c["class"])):
            print(f"{c['name']}: own poses not learned yet (learn {c['class']}) - skipped")
            continue
        elif not lr.get("twin_ok"):
            print(f"{c['name']}: DRPG {c['twin']} is not an exact twin ({lr['shared_exact']}/{lr['shared']}) - skipped")
            continue
        todo = [(u, n, hybrid) for u, n in c["outfits"] if only is None or u in only]
        for u, n, pf in ([] if c.get("kind") == "new_character" else c.get("monster_outfits", [])):           # monster-type variants: the monster pipeline
            if only is None or u in only:
                from d5lib import monstermap
                todo.append((u, n, dict(pairs=monstermap.load_pairs(
                    os.path.join(KIT, "d5lib", "data", "monster_pairs", pf)))))
        if not todo:
            continue
        mod = get_mod(mm, c)
        units = built_units(mod)
        for uid, name, hybrid in todo:
            if uid in units:
                if not rebuild:
                    print(f"{c['name']} / {name}: already built (slot {units[uid]})")
                    continue
                outfits.remove_outfit(fs, mod, units.pop(uid))
                _record(mod, units)
            t = time.time()
            try:
                r = outfits.create_drpg_outfit(fs, mod, base_id, uid, name, log=lambda *a: None, hybrid=hybrid,
                                               template=template)
            except Exception as e:
                print(f"{c['name']} / {name} (DRPG {uid}): FAILED {type(e).__name__}: {e}", flush=True)
                continue
            units[uid] = r["slot"]
            _record(mod, units)
            rep = r["report"]
            print(f"{c['name']} / {name} (DRPG {uid}): slot {r['slot']}, anm{r['sprite']:05d}, "
                  f"{rep.get('cells', '?')} cells, {len(rep.get('missing', ()))} without a drawing ({time.time() - t:.0f}s)"
                  + (" [monster-type: hybrid]" if hybrid else ""), flush=True)
            done.append((c["mod"], r["slot"], r["sprite"]))
    print(f"{len(done)} outfit(s) built")
    return done


if __name__ == "__main__":
    main()
