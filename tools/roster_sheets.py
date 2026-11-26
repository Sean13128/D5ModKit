#!/usr/bin/env python3
"""SHEET1: offline contact sheets of every installed imported unit (no game, no live screenshots).

    D5Modkit/.venv-macos/bin/python tools/roster_sheets.py [--only A,B] [--out DIR] [--json FILE]
        [--mods DIR] [--game DIR] [--bank-source archive|pack] [--limit N]

Roster: Reports/tracker/items_compact.csv rows with in_installed_build == done (the playable entries); the pack of
each row is the `installed kit mods/<pack>` named in its source column.  Per unit: stand (1001 front / 1007 back),
walk (11/17), one attack (first of 2001, 3001, 4001), hurt (1061/1067) and every distinct caster motion (m -> m*10+1 /
m*10+7) that its own learn lists put on the caster per d5lib/choreo.py, at the palette the game picks for the row
(colour id % 10, docs/ANM.md sec. 3; D1C uniques: slot 0 already holds the source-selected palette, IMPORT_GATES.md
"Unique default palette").  One PNG per unit + one index sheet per game + a JSON summary of machine checks, each
PASS / FAIL / NOT CHECKED (unknown is never PASS).  Rendering is d5lib.anm only.

It shows what the files say (installed archive banks, the clean game's skill scripts), not what the game loads.
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True

import numpy as np  # noqa: E402

PROJECT = Path("/Volumes/Data/Projects/D5")
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
OUT = PROJECT / "Reports/sheets-20261111"
ROSTER = PROJECT / "Reports/tracker/items_compact.csv"
ANIME = "Anime/ANM_HI_JP.dat"
ALPHA = 16
ATTACK_IDS = (2001, 3001, 4001)
FIXED = [("stand", 1001, 1007), ("walk", 11, 17), ("hurt", 1061, 1067)]   # + attack, + skill motions
BBOX_RATIO = (0.25, 4.0)                  # pose size vs the stand pose (each side)
PASS, FAIL, NC = "PASS", "FAIL", "NOT CHECKED"


def skillmotions_anims(m):
    from d5lib import skillmotions
    return skillmotions.anims_of(m)


def motion_ids(m, kind):
    """animation ids of caster motion m: the humanoid special cases (109 -> 1051, 151 -> 7011: seen in game on humanoid
    classes) do not hold for a monster body, whose motion 151 is its own 1511/1517 (MONATK1: Death's normal attack)"""
    if kind == 1 and m == 151:
        return 1511, 1517
    return (m * 10 + 1, m * 10 + 7) if m not in (109, 151) else ((1051, 1057) if m == 109 else (7011, 7017))


def worst(statuses):
    s = set(statuses)
    return FAIL if FAIL in s else NC if NC in s else PASS if s else NC


# ------------------------------------------------------------------------------------------ data
def roster(path=ROSTER):
    out = []
    for r in csv.DictReader(open(path, newline="", encoding="utf-8")):
        if r["in_installed_build"] != "done" or r["game"] not in ("D1C", "D4", "DD2", "DRPG"):
            continue
        m = re.search(r"installed kit mods/([^ ;:,)/]+)", r["source"])
        out.append(dict(game=r["game"], kind=r["kind"], name=r["name"], pack=m.group(1) if m else None))
    return out


class Ctx:
    """the files read: installed archive banks (or a pack's own bank first), resident humanoid block, skill survey"""

    def __init__(self, game=GAME, mods=None, bank_source="archive"):
        from d5lib import anm, gamefs
        self.anm, self.gamefs = anm, gamefs
        self.game = Path(game)
        self.mods = Path(mods) if mods else self.game / "D5ModKit" / "mods"
        self.bank_source = bank_source
        self.fs = gamefs.GameFS(str(self.game))
        res = anm.parse(self.fs.read(f"{ANIME}/anm_resident.lzs"))
        self.block1 = next(b for b in res.blocks if b.id == 1)          # shared humanoid motions
        self.resident_ids = {a.id for a in self.block1.animations}
        self._banks, self._survey = {}, None

    def pack_bank_path(self, pack, n):
        return self.mods / pack / "files" / ANIME / f"anm{n:05d}.lzs"

    def bank(self, pack, n):
        """(AnmFile or None, source label)"""
        key = (pack if self.bank_source == "pack" else "", n)
        if key not in self._banks:
            p = self.pack_bank_path(pack, n)
            try:
                if self.bank_source == "pack" and p.is_file():
                    self._banks[key] = (self.anm.parse(self.gamefs.decode_member(p.read_bytes())), "pack folder")
                else:
                    self._banks[key] = (self.anm.parse(self.fs.read(f"{ANIME}/anm{n:05d}.lzs")), "installed archive")
            except Exception:                                           # noqa: BLE001  no such member
                self._banks[key] = (None, "absent")
        return self._banks[key]

    def vanilla_pose(self, f, b):
        """how the clean game's own banks draw motion pair f/b: {n, blank, same} over a fixed sample of banks that hold it
        (6 humanoid + 6 monster rows of the clean char.dat, first by id)"""
        if not hasattr(self, "_vs"):
            from d5lib import database
            sv = self.survey()
            rows = database.load_table("char.dat", sv.fs.read("Database/Database_0.dat/char.dat")).rows
            pick = {0: [], 1: []}
            for r in rows:
                sp, k = int(r["sprite_id"] or 0), int(r["body_type"] or 0)
                if sp and k in pick and len(pick[k]) < 6 and sp not in pick[k] and sp < 3000:
                    pick[k].append(sp)
            self._vs, self._vcache = [], {}
            for k, lst in pick.items():
                for sp in lst:
                    try:
                        bk = self.anm.parse(sv.fs.read(f"{ANIME}/anm{sp + (1 if sp > 2000 else 0):05d}.lzs"))
                    except Exception:                                    # noqa: BLE001
                        continue
                    self._vs.append(([bk] + ([self.anm.bind_motion_set(self.anm.AnmFile([self.block1], [], []), 0, bk)] if k == 0 else [])))
        key = (f, b)
        if key not in self._vcache:
            n = blank = same = 0
            for cands in self._vs:
                got = []
                for aid in (f, b):
                    fl = next((c for c in cands if self.anm.has_animation(c, aid)), None)
                    got.append(None if fl is None else (fl, self.anm.evaluate(fl, ("id", aid), 0, nested=True)))
                if None in got:
                    continue
                bd = self.anm.item_bounds(got[0][1] + got[1][1])
                arr = [np.asarray(self.anm.render_items(g[0], g[1], 0, bounds=bd)[0]) for g in got]
                n += 1
                blank += int(not (arr[0][..., 3] > ALPHA).any() and not (arr[1][..., 3] > ALPHA).any())
                same += int(arr[0].tobytes() == arr[1].tobytes())
            self._vcache[key] = dict(n=n, blank=blank, same=same)
        return self._vcache[key]

    def normal_attack(self, pack, kind):
        """monster body only: the caster motions of the normal-attack event the game starts for it (script event
        12010000 + sprite, a copy of its template's: docs/MONSTERS.md), simulated by choreo on the clean script.
        -> (template, [motion ids without the stand 100]) or None when the template is not recorded in the pack"""
        if kind != 1:
            return None
        tmpl = None
        try:
            for f in sorted((self.mods / pack / "patches" / "classes").glob("*.json")):
                tmpl = json.loads(f.read_text()).get("template")
            rc = self.mods / pack / "CORERPG1-receipt.json"
            if tmpl is None and rc.is_file():
                mr = json.loads(rc.read_text()).get("monster_reports") or {}
                tmpl = next(iter(mr.values()))["template"] if mr else None
        except Exception:                                                # noqa: BLE001
            tmpl = None
        if not tmpl:
            return None
        from d5lib import choreo
        sv = self.survey()
        if 12010000 + int(tmpl) not in sv.vanilla:
            return None
        c = choreo.Context(loading=True, in_battle=(1, 2010))
        c.vars[60201], c.vars[64000] = 0, 1
        tl = choreo.simulate(sv.vanilla, 12010000 + int(tmpl), c)
        ms = sorted({m for _, _, m, _ in tl.motions(choreo.CASTER) if isinstance(m, int)} - {100})
        return int(tmpl), ms

    def survey(self):
        if self._survey is None:
            from d5lib import skillmotions
            folders = sorted(p for p in self.mods.iterdir() if p.is_dir() and (p / "mod.json").is_file())
            self._survey = skillmotions.Survey(skill_roots=folders)
        return self._survey


def pack_rows(ctx, pack):
    d = json.loads((ctx.mods / pack / "patches/db/char.dat.json").read_text())
    return d.get("added") or []


# ------------------------------------------------------------------------------------------ one unit
def palette_rule(entry, pack_meta, row):
    p = ((pack_meta.get("source_import") or {}).get("identity") or {}).get("palette")
    if entry["kind"] == "generic class":
        return "class: per-rank colour row, palette = tier = colour id - sprite id (= id % 10, ANM.md sec. 3)"
    base = "unique: default palette slot = colour id - sprite id = 0"
    if entry["game"] == "D1C" and p:
        return base + f"; D1CCOLOR1: source palette {p} was swapped into slot 0 at import (installed bank read as is)"
    return base


def bank_diff(a, b):
    """'' when two parsed banks hold the same textures, palettes and tables, else what differs"""
    out = []
    for name in ("textures", "palettes"):
        x, y = getattr(a, name), getattr(b, name)
        if len(x) != len(y) or any(i.data != j.data for i, j in zip(x, y)):
            out.append(name)
    if len(a.blocks) != len(b.blocks):
        out.append("block count")
    else:
        names = ("animations", "nodes", "keys", "palette_infos", "texture_infos", "cells", "transforms", "pivots", "colors", "params")
        for bi, (p, q) in enumerate(zip(a.blocks, b.blocks)):
            for nm, t1, t2 in zip(names, p.tables(), q.tables()):
                if t1 != t2:
                    n = sum(1 for i, j in zip(t1, t2) if i != j) + abs(len(t1) - len(t2))
                    out.append(f"block {bi} {nm}: {n} row(s)")
    return "; ".join(out)


def unit_frames(ctx, entry):
    """render every pose of one unit -> dict(rows, poses, checks, frames[], palettes[])"""
    anm = ctx.anm
    pack = entry["pack"]
    meta = json.loads((ctx.mods / pack / "mod.json").read_text())
    rows = pack_rows(ctx, pack)
    res = dict(name=entry["name"], game=entry["game"], kind=entry["kind"], pack=pack, rows=[], poses=[], checks={})
    if not rows:
        res["checks"]["char rows"] = dict(status=FAIL, why="pack has no char rows")
        return res, [], []
    r0 = rows[0]
    sprite, kind = int(r0.get("sprite_id") or 0), int(r0.get("body_type") or 0)
    body = sprite + (1 if sprite > 2000 else 0)             # battle bank (skillmotions.Survey convention)
    bank, src = ctx.bank(pack, body)
    res["bank"] = dict(number=body, source=src, humanoid=kind == 0)
    res["palette_rule"] = palette_rule(entry, meta, r0)
    res["info"] = {}
    for r in rows:
        off = int(r["color_id"]) - int(r["sprite_id"])          # colour row offset from the sprite id = tier for classes
        res["rows"].append(dict(id=int(r["id"]), tier=int(r.get("tier") or 0), sprite_id=int(r["sprite_id"]),
                                color_id=int(r["color_id"]), palette=off if 0 <= off < 10 else int(r["color_id"]) % 10,
                                mod10=int(r["color_id"]) % 10, body_type=int(r.get("body_type") or 0)))
    pal0 = res["rows"][0]["palette"]
    # bank exists / installed archive equals the pack folder's bank
    res["checks"]["bank exists"] = dict(status=PASS if bank else FAIL, why=f"anm{body:05d} {src}")
    pp = ctx.pack_bank_path(pack, body)
    if bank and pp.is_file() and ctx.bank_source == "archive":
        diff = bank_diff(anm.parse(ctx.gamefs.decode_member(pp.read_bytes())), bank)
        res["info"]["installed vs pack bank"] = diff or "equal (textures, palettes, tables)"   # the installer rewrites banks: info only
    if not bank:
        return res, [], []
    nv = len(bank.palettes)
    bad = [r for r in res["rows"] if r["palette"] >= nv]
    res["checks"]["palette in range"] = dict(status=FAIL if bad else PASS,
                                             why=f"{nv} palettes; row palettes {[r['palette'] for r in res['rows']]}")
    # the kit's graphics-id rule (palette = id % 10) and the colour-row offset agree for every vanilla row; an imported
    # unique with a sprite id that is no multiple of 10 splits them, and the engine's split was not traced
    split = [r for r in res["rows"] if r["mod10"] != r["palette"]]
    res["checks"]["palette rule agrees"] = dict(
        status=NC if split else PASS,
        why=(f"rows {[r['id'] for r in split][:4]}: colour-row offset gives palette {split[0]['palette']}, kit id%10 rule gives "
             f"{split[0]['mod10']}; sheet shows the offset (slot 0 for a unique); the engine's split was not traced") if split
        else "colour-row offset = id % 10 on every row")
    cands = [bank] + ([anm.bind_motion_set(anm.AnmFile([ctx.block1], [], []), 0, bank)] if kind == 0 else [])
    if kind == 1 and sprite > 2000:         # MONATK1: a monster's attacks live in its MAIN bank anm<sprite>; anm<sprite+1> is
        main, _ = ctx.bank(pack, sprite)    # the companion (vanilla 2010: 54 ids, no 2071; main: 78 ids incl. 2071/2077)
        if main is not None:
            cands.append(main)

    def find(aid):
        for k, f in enumerate(cands):
            if anm.has_animation(f, aid):
                return f, ("bank" if k == 0 else "main bank" if kind == 1 else "resident")
        return None, None

    # pose list: (label, front id, back id)
    poses = [(a, f, b) for a, f, b in FIXED[:2]]
    na = ctx.normal_attack(pack, kind)
    res["info"]["normal attack"] = (f"monster template {na[0]}: event 12010000+sprite plays caster motions {na[1]}" if na else
                                    "stand-in 2001/3001/4001 (humanoid: weapon -> motion not traced; monster: template not recorded)")
    if na and na[1]:                       # the motion the game really plays for a monster's normal attack
        atk = motion_ids(na[1][0], kind)[0]
        poses.append(("attack", atk, atk + 6))
    else:
        atk = next((i for i in ATTACK_IDS if find(i)[0] or find(i + 6)[0]), None)
        poses.append(("attack", atk if atk else ATTACK_IDS[0], (atk if atk else ATTACK_IDS[0]) + 6))
    poses.append(FIXED[2])
    sv = ctx.survey()
    by_motion = {}
    for r in rows:
        for i in range(1, min(int(r.get("learn_count") or 0), 16) + 1):
            sid = int(r.get(f"learn{i}_skill") or 0)
            for m in (sv.caster(sid) or []) if sid else []:
                if m:
                    by_motion.setdefault(m, set()).add(sid)
    std = {x for _, f, b in poses for x in (f, b)}
    skill_unknown = sorted({int(r.get(f"learn{i}_skill") or 0) for r in rows
                            for i in range(1, min(int(r.get("learn_count") or 0), 16) + 1)
                            if int(r.get(f"learn{i}_skill") or 0) and sv.caster(int(r.get(f"learn{i}_skill"))) is None})
    for m in sorted(by_motion):
        f, b = motion_ids(m, kind)
        if f not in std:
            poses.append((f"skill m{m}", f, b))
    res["skills_unresolved"] = skill_unknown
    # evaluate every pose once
    shots = {}                                              # aid -> (file, items, source) or None
    frames_drawn = {}                                       # aid -> (key times that hold any item, key times)
    for _, f, b in poses:
        for aid in (f, b):
            if aid in shots:
                continue
            fl, how = find(aid)
            if fl is None:
                shots[aid] = None
                continue
            ts = anm.frame_times(fl, ("id", aid))
            t = ts[len(ts) // 2] if aid in (atk, atk and atk + 6) and len(ts) > 2 else ts[0]
            its = anm.evaluate(fl, ("id", aid), t, nested=True)
            allits = [anm.evaluate(fl, ("id", aid), x, nested=True) for x in ts]
            drawn = [i for i, x in enumerate(allits) if any(it.cell.w > 0 and it.cell.h > 0 for it in x)]   # a 0x0 cell draws nothing (vanilla's own last key)
            if not its and drawn:        # the chosen frame draws nothing but another does: show that one (SHEETFIX1)
                its = allits[drawn[len(drawn) // 2]]
            shots[aid] = (fl, its, how)
            frames_drawn[aid] = (len(drawn), len(ts))
    allitems = [it for s in shots.values() if s for it in s[1]]
    bounds = anm.item_bounds(allitems) if allitems else (-8, -8, 8, 8)

    def render(aid, pal):
        s = shots[aid]
        img, _ = anm.render_items(s[0], s[1], pal, bounds=bounds)
        return img

    frames, arrays = [], {}
    for label, f, b in poses:
        for view, aid in (("front", f), ("back", b)):
            p = dict(label=label, view=view, id=aid, palette=pal0)
            s = shots.get(aid)
            if s is None:
                p.update(source=None, checks=dict(exists=FAIL, nonempty=NC, bbox=NC))
                if label in ("attack",) and atk is None and not na:
                    have = sorted(i for i in {x.id for bl in bank.blocks for x in bl.animations} if 2000 <= i < 5000 and i % 10 == 1)
                    p["note"] = f"no attack id of 2001/3001/4001 in the bank or resident set; bank has family ids {have[:6]}"
                if label.startswith("skill") or label == "attack":   # absent, but does vanilla run this pair without it too?
                    p["vanilla_fallback"] = (kind, aid) in sv.precedent()
                frames.append((label, view, aid, None))
            else:
                img = render(aid, pal0)
                a = np.asarray(img)
                arrays[aid] = a
                mask = a[..., 3] > ALPHA
                n = int(mask.sum())
                if n:
                    ys, xs = np.where(mask)
                    p["bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                p.update(source=s[2], pixels=n, frames_drawn=list(frames_drawn[aid]),
                         checks=dict(exists=PASS, nonempty=PASS if n else FAIL, bbox=NC))
                frames.append((label, view, aid, img))
            res["poses"].append(p)
    # an empty frame or identical front/back that the clean game's own banks draw the same way is not a fault of the import
    pair = {}
    for label, f, b in poses:
        pair[f] = pair[b] = (f, b)
    for p in res["poses"]:
        if p["checks"]["nonempty"] == FAIL and p["label"] not in ("stand", "walk", "hurt"):
            v = ctx.vanilla_pose(*pair[p["id"]])
            p["vanilla_sample"] = v
            if v["n"] and v["blank"] * 2 >= v["n"]:
                p["checks"]["nonempty"] = NC
                p["note"] = f"empty here and in the clean game's banks ({v['blank']}/{v['n']} sampled): intentional blank motion, not judged"
    # bbox vs the stand frame of the same view
    ref = {}
    for p in res["poses"]:
        if p["label"] == "stand" and p.get("bbox"):
            ref[p["view"]] = p["bbox"]
    for p in res["poses"]:
        if p["label"] == "stand" and p["view"] == "front":
            p["checks"]["bbox"] = "REF"                     # the reference itself: left out of every count
            p["bbox_note"] = "reference frame"
        elif p.get("bbox") and (p["view"] in ref or p["label"] == "stand" and "front" in ref):
            r_ = ref["front"] if p["label"] == "stand" else ref[p["view"]]   # stand back is judged against stand front
            rw, rh = r_[2] - r_[0], r_[3] - r_[1]
            w, h = p["bbox"][2] - p["bbox"][0], p["bbox"][3] - p["bbox"][1]
            ok = all(BBOX_RATIO[0] <= x / y <= BBOX_RATIO[1] for x, y in ((w, rw), (h, rh)))
            p["checks"]["bbox"] = PASS if ok else FAIL
            p["bbox_note"] = f"{w}x{h} vs stand front {rw}x{rh}" if p["label"] == "stand" else f"{w}x{h} vs stand {rw}x{rh}"
    # front vs back not byte-identical (both ids resolve)
    res["front_back"] = []
    for label, f, b in poses:
        if f in arrays and b in arrays:
            same = arrays[f].tobytes() == arrays[b].tobytes()
            st, why = (FAIL, "front and back render byte-identical") if same else (PASS, "differ")
            if same and label not in ("stand", "walk", "hurt"):
                v = ctx.vanilla_pose(f, b)
                if not (arrays[f][..., 3] > ALPHA).any():
                    st, why = NC, "both frames empty"
                elif v["n"] and v["same"] * 2 >= v["n"]:
                    st, why = NC, f"identical here and in the clean game's banks ({v['same']}/{v['n']} sampled)"
            res["front_back"].append(dict(label=label, front=f, back=b, status=st, why=why))
        else:
            res["front_back"].append(dict(label=label, front=f, back=b, status=NC, why="an id is missing"))
    # roll up
    for name in ("exists", "nonempty", "bbox"):
        res["checks"][f"pose {name}"] = dict(
            status=worst(p["checks"][name] for p in res["poses"] if p["checks"][name] != "REF"),
            why="; ".join(f"{p['label']} {p['view']} {p['id']}" for p in res["poses"] if p["checks"][name] == FAIL)[:300])
    res["checks"]["front/back differ"] = dict(
        status=worst(x["status"] for x in res["front_back"]),
        why="; ".join(f"{x['label']} {x['front']}/{x['back']}" for x in res["front_back"] if x["status"] == FAIL)[:300])
    # palette strip: stand front under each distinct row palette
    strip = []
    if 1001 in shots and shots[1001]:
        seen = set()
        for r in res["rows"]:
            if r["palette"] in seen or r["palette"] >= nv:
                continue
            seen.add(r["palette"])
            strip.append((f"row {r['id']} tier {r['tier']} pal {r['palette']}", render(1001, r["palette"])))
    return res, frames, strip


# ------------------------------------------------------------------------------------------ drawing
def _font(size=11):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def sheet(res, frames, strip, path, cw=150, ch=190, cols=6):
    from PIL import Image, ImageDraw
    BG, TXT = (58, 60, 70, 255), (235, 235, 235, 255)
    items = [(f"{lab} {view} {aid}", img) for lab, view, aid, img in frames] + [(t, im) for t, im in strip]
    rows = (len(items) + cols - 1) // cols
    head = 44
    S = Image.new("RGBA", (cols * cw, head + rows * (ch + 16)), BG)
    d = ImageDraw.Draw(S)
    f, fs = _font(13), _font(10)
    bad = [k for k, v in res["checks"].items() if v["status"] == FAIL] + \
          [f"front/back {x['label']}" for x in res.get("front_back", []) if x["status"] == FAIL]
    d.text((6, 4), f"{res['name']}  [{res['game']} {res['kind']}]  pack {res['pack']}", fill=TXT, font=f)
    d.text((6, 22), (res.get("palette_rule") or "")[:150], fill=(180, 200, 255, 255), font=fs)
    if bad:
        d.text((6, 33), "FAIL: " + ", ".join(bad)[:150], fill=(255, 110, 110, 255), font=fs)
    for k, (label, img) in enumerate(items):
        x, y = (k % cols) * cw, head + (k // cols) * (ch + 16)
        if img is None:
            d.rectangle((x + 4, y + 4, x + cw - 4, y + ch - 4), outline=(255, 90, 90, 255))
            d.text((x + 12, y + ch // 2 - 6), "MISSING", fill=(255, 90, 90, 255), font=f)
        else:
            s = min((cw - 8) / img.width, ch / img.height, 1.0)
            im = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
            S.alpha_composite(im, (x + (cw - im.width) // 2, y + ch - im.height))
        d.text((x + 3, y + ch + 2), label[:26], fill=TXT, font=fs)
    S.convert("RGB").save(path)


def index_sheet(game, results, thumbs, path, cols=8, cw=130, ch=160):
    from PIL import Image, ImageDraw
    n = len(results)
    rows = (n + cols - 1) // cols
    S = Image.new("RGB", (cols * cw, 24 + max(1, rows) * ch), (40, 42, 50))
    d = ImageDraw.Draw(S)
    d.text((6, 4), f"{game}: {n} units (red frame = a FAIL check, grey = no frames)", fill=(235, 235, 235), font=_font(13))
    fs = _font(10)
    for k, r in enumerate(results):
        x, y = (k % cols) * cw, 24 + (k // cols) * ch
        fail = any(v["status"] == FAIL for v in r["checks"].values()) or \
            any(x_["status"] == FAIL for x_ in r.get("front_back", []))
        d.rectangle((x + 2, y + 2, x + cw - 3, y + ch - 3), outline=(220, 70, 70) if fail else (80, 85, 100), width=2)
        t = thumbs.get(r["name"] + r["pack"])
        if t is not None:
            S.paste(t, (x + (cw - t.width) // 2, y + 4))
        d.text((x + 5, y + ch - 30), r["name"][:20], fill=(235, 235, 235), font=fs)
        d.text((x + 5, y + ch - 18), r["pack"][-20:], fill=(150, 160, 180), font=fs)
    S.save(path)


def thumb(frames, w=60, h=104):
    """stand front + back side by side"""
    from PIL import Image
    ims = [img for lab, view, aid, img in frames if lab == "stand" and img is not None]
    if not ims:
        return None
    T = Image.new("RGB", (w * len(ims), h), (58, 60, 70))
    for k, im in enumerate(ims):
        s = min(w / im.width, h / im.height)
        r = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        T.paste(r, (k * w + (w - r.width) // 2, h - r.height), r)
    return T


# ------------------------------------------------------------------------------------------ main
def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma list: unit names or pack names (substring match)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--game", type=Path, default=GAME)
    ap.add_argument("--mods", type=Path)
    ap.add_argument("--roster", type=Path, default=ROSTER)
    ap.add_argument("--bank-source", choices=("archive", "pack"), default="archive")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-png", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    ctx = Ctx(a.game, a.mods, a.bank_source)
    ents = roster(a.roster)
    if a.only:
        keys = [k.strip().lower() for k in a.only.split(",")]
        ents = [e for e in ents if any(k in e["name"].lower() or k in (e["pack"] or "").lower() for k in keys)]
    if a.limit:
        ents = ents[:a.limit]
    if not a.no_png:
        a.out.mkdir(parents=True, exist_ok=True)
    results, by_game, thumbs = [], {}, {}
    for e in ents:
        if not e["pack"] or not (ctx.mods / e["pack"] / "mod.json").is_file():
            r = dict(name=e["name"], game=e["game"], kind=e["kind"], pack=e["pack"] or "?", rows=[], poses=[],
                     checks={"pack present": dict(status=FAIL, why="pack folder not found")})
            frames = strip = []
        else:
            try:
                r, frames, strip = unit_frames(ctx, e)
            except Exception as ex:                                      # noqa: BLE001  one unit never stops the run
                r = dict(name=e["name"], game=e["game"], kind=e["kind"], pack=e["pack"], rows=[], poses=[],
                         checks={"render": dict(status=FAIL, why=f"{type(ex).__name__}: {ex}"[:200])})
                frames = strip = []
        r["png"] = None
        if frames and not a.no_png:
            p = a.out / f"{e['game']}_{safe(e['name'])}_{e['pack']}.png"
            sheet(r, frames, strip, p)
            r["png"] = str(p)
            thumbs[r["name"] + r["pack"]] = thumb(frames)
        results.append(r)
        by_game.setdefault(e["game"], []).append(r)
    if not a.no_png:
        for g, rs in by_game.items():
            index_sheet(g, rs, thumbs, a.out / f"index-{g}.png")
    counts = {}
    for r in results:
        for k, v in r["checks"].items():
            counts.setdefault(k, {PASS: 0, FAIL: 0, NC: 0})[v["status"]] += 1
        for x in r.get("front_back", []):
            counts.setdefault("front/back pair", {PASS: 0, FAIL: 0, NC: 0})[x["status"]] += 1
        for p in r["poses"]:
            for k, v in p["checks"].items():
                if v != "REF":
                    counts.setdefault(f"pose {k} (each frame)", {PASS: 0, FAIL: 0, NC: 0})[v] += 1
    fails = []
    for r in results:
        for k, v in r["checks"].items():
            if v["status"] == FAIL and not k.startswith("pose "):
                fails.append(dict(unit=r["name"], pack=r["pack"], check=k, why=v["why"]))
        for p in r["poses"]:
            for k, v in p["checks"].items():
                if v == FAIL:
                    fails.append(dict(unit=r["name"], pack=r["pack"], check=f"pose {k}", motion=p["id"],
                                      label=p["label"], view=p["view"]))
        for x in r.get("front_back", []):
            if x["status"] == FAIL:
                fails.append(dict(unit=r["name"], pack=r["pack"], check="front/back differ", motion=f"{x['front']}/{x['back']}",
                                  label=x["label"]))
    summary = dict(units=len(results), seconds=round(time.time() - t0, 1), bank_source=a.bank_source,
                   counts=counts, fails=fails, results=results)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"{len(results)} units in {summary['seconds']} s; {len(fails)} FAIL entries")
    for k, v in counts.items():
        print(f"  {k:34} PASS {v[PASS]:5} FAIL {v[FAIL]:5} NOT CHECKED {v[NC]:5}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
