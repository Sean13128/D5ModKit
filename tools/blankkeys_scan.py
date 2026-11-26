#!/usr/bin/env python3
"""BLANKKEYS1: per unit, per animation, how many key times draw any item ("drawn keys / key times"), for every
installed unit's own banks, plus the same measure on the clean game's banks ("vanilla also blanks here").

    D5Modkit/.venv-macos/bin/python tools/blankkeys_scan.py [--out FILE.json] [--bank-source archive|pack] [--only A,B]

Scope list = animations where ours draws fewer key times than the clean game's best bank for the same id (donor =
the pack's template bank for a monster; any clean bank holding the id otherwise).  Offline, reads only.
"""
import argparse
import json
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
sys.path.insert(0, str(KIT / "tools"))
import roster_sheets as rs  # noqa: E402


def drawn_keys(anm, fl, aid):
    """(key times that draw any item, key times) for animation id aid of file fl (stubs follow their nested pose)"""
    ts = anm.frame_times(fl, ("id", aid))
    return sum(1 for t in ts if any(i.cell.w > 0 and i.cell.h > 0 for i in anm.evaluate(fl, ("id", aid), t, nested=True))), len(ts)


def with_resident(ctx, fl):
    """a humanoid bank as the game sees it: its own animations first, the shared resident humanoid block behind them
    (own stubs name resident poses, so measuring the bank alone under-counts)"""
    import copy
    b = copy.copy(ctx.block1)
    b.tex_base = b.pal_base = 0
    b.palette_infos = list(fl.blocks[0].palette_infos)
    return ctx.anm.AnmFile(list(fl.blocks) + [b], fl.textures, fl.palettes)


def bank_table(anm, fl, only=None):
    out = {}
    own = {a.id for b in (fl.blocks if only is None else fl.blocks[:only]) for a in b.animations}
    for bi, ai, a in fl.all_animations():
        if a.id not in own:
            continue
        if a.id in out:
            continue
        try:
            out[a.id] = drawn_keys(anm, fl, a.id)
        except Exception as ex:                      # noqa: BLE001
            out[a.id] = (-1, -1)
    return out


def vanilla_tables(ctx):
    """sprite -> {id: (drawn,total)} for every clean-game char.dat sprite bank (main and +1 companion)"""
    from d5lib import database
    sv = ctx.survey()
    rows = database.load_table("char.dat", sv.fs.read("Database/Database_0.dat/char.dat")).rows
    kinds = {int(r["sprite_id"] or 0): int(r["body_type"] or 0) for r in rows if int(r["sprite_id"] or 0)}
    sprites = sorted(kinds)
    out = {}
    for sp in sprites:
        for n in {sp, sp + 1 if sp > 2000 else sp}:
            if n in out:
                continue
            try:
                fl = ctx.anm.parse(sv.fs.read(f"{rs.ANIME}/anm{n:05d}.lzs"))
            except Exception:                        # noqa: BLE001
                continue
            nb = len(fl.blocks)
            out[n] = bank_table(ctx.anm, with_resident(ctx, fl) if kinds[sp] == 0 else fl, nb)
    return out


def scope(units):
    """the real scope: [(game, name, pack, kind, bank, aid, drawn, total, best clean count)] where ours draws fewer key times
    than the clean game's banks of the same key-time count (the pack's template bank first) and no clean bank draws as few"""
    rows = []
    for u in units:
        for n, b in u["banks"].items():
            for aid, e in b.items():
                if e["t"] <= 1 or e["d"] >= e["t"]:
                    continue
                vs = set(e["vsame_set"])
                if e["donor"] and e["donor"][1] == e["t"]:
                    vs.add(e["donor"][0])
                if vs and e["d"] not in vs and e["d"] < max(vs):
                    rows.append((u["game"], u["name"], u["pack"], u["kind"], int(n), int(aid), e["d"], e["t"], max(vs)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=rs.PROJECT / "Reports/blankkeys1-20261111/scan.json")
    ap.add_argument("--bank-source", choices=("archive", "pack"), default="archive")
    ap.add_argument("--only")
    ap.add_argument("--mods", type=Path, help="mods folder to measure (default: the installed kit's)")
    a = ap.parse_args(argv)
    t0 = time.time()
    ctx = rs.Ctx(mods=a.mods, bank_source=a.bank_source)
    van = vanilla_tables(ctx)
    print(f"vanilla banks {len(van)} in {time.time()-t0:.0f}s", flush=True)
    ents = rs.roster()
    if a.only:
        ks = [k.lower() for k in a.only.split(",")]
        ents = [e for e in ents if any(k in e["name"].lower() or k in (e["pack"] or "").lower() for k in ks)]
    units = []
    for e in ents:
        if not e["pack"] or not (ctx.mods / e["pack"] / "mod.json").is_file():
            continue
        rows = rs.pack_rows(ctx, e["pack"])
        if not rows:
            continue
        sprite, kind = int(rows[0]["sprite_id"] or 0), int(rows[0]["body_type"] or 0)
        tmpl = None
        try:
            for f in sorted((ctx.mods / e["pack"] / "patches" / "classes").glob("*.json")):
                tmpl = json.loads(f.read_text()).get("template")
        except Exception:                            # noqa: BLE001
            pass
        banks = sorted({sprite, sprite + 1} if sprite > 2000 else {sprite})
        u = dict(game=e["game"], name=e["name"], pack=e["pack"], sprite=sprite, kind=kind, template=tmpl, banks={})
        for n in banks:
            fl, src = ctx.bank(e["pack"], n)
            if fl is None:
                continue
            tab = bank_table(ctx.anm, with_resident(ctx, fl) if kind == 0 else fl, len(fl.blocks))
            ent = {}
            for aid, (d, t) in tab.items():
                vs = [v[aid] for v in van.values() if aid in v and v[aid][1] > 0]
            
                donor = van.get(int(tmpl) + (1 if n != sprite else 0) if tmpl else -1, {}).get(aid) if tmpl else None
                if kind == 1 and tmpl and donor is None:
                    donor = van.get(int(tmpl), {}).get(aid)
                same = [x[0] for x in vs if x[1] == t]          # clean banks with the same number of key times
                ent[aid] = dict(d=d, t=t, donor=donor, vsame=max(same) if same else None, vsame_set=sorted(set(same)), vsame_n=len(same),
                                vmax=max((x[0] / x[1] for x in vs), default=None), vn=len(vs),
                                vfull=sum(1 for x in vs if x[0] == x[1]))
            u["banks"][n] = ent
        units.append(u)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(dict(units=units), indent=0))
    print(f"{len(units)} units in {time.time()-t0:.0f}s; scope {len(scope(units))} animations in {len({r[2] for r in scope(units)})} packs")


if __name__ == "__main__":
    main()
