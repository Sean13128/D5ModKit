#!/usr/bin/env python3
"""GAMETRUTH1 acceptance: the verifier against the defects found by live play on 2026-11-10 (labelled data).

Each case = (known state, pack, check, expected).  Known-bad states are rebuilt from what was kept:
  QBOARD1    Quest.dat as built at NIGHT1 (QBOARD1 scratch quest_night1.json, 700 rows) + the same Save_001
  NODRAW2    the installer before 53c3947 (KITCODE-NODRAW2EG backup newclasses.py) replayed on each pack, over
             the clean game's anm_resident
  BACKVIEW1  pack folders before BACKVIEW1/BACKVIEW1B (kit-backups 1610, 1645)
  SMALLFIX1  pack folders before INSTALL3B (kit-backups 1229)
  INSTALL4   the outfit install step before VOICE1b (tools/simulate_outfit_voices replay, own_voice ignored)
and the fixed state is what is installed now.  Known-good live sightings: REALSURVEY1-results.json and the
NODRAW2 humanoid recruits.  QBOARD2: REALSURVEY1's four "not offered" recruit quests (439/441/442/443) are on the
game's board, and a replay of the harness walk reproduces each lap row it reported.  Read-only; needs the local game, backups and scratch inputs (skips what is missing).
"""
import collections
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
P = Path("/Volumes/Data/Projects/D5")
BK = P / "Local/kit-backups"
SAVE = Path("/Volumes/Data/ai-tmp/claude/GAMETRUTH1B-20261110-1930/Save_001.sav")   # copy of Save_001, md5 02716899
NIGHT1 = Path("/Volumes/Data/ai-tmp/claude/QBOARD1-20261110-024908/quest_night1.json")
CLEAN = P / "Disgaea Source/Disgaea 5 Complete (Steam 803600)"
EE = P / "Subprojects/Engine-Extensions"


LIVE5_BEFORE = Path("/Volumes/Data/ai-tmp/claude/LIVE5-20261110-194600/gametruth-before.json")   # verifier run on the pre-EVILFX2 install
EVILFX2_FIXED = ("D4_Unique_350", "D4_Unique_4390")       # Kyoko, Kojiro: REALSURVEY1 saw page 3 blank; EVILFX2 fixed it


def pinned_status(path, pack, check):
    if not Path(path).is_file():
        return "absent"
    r = next((x for x in json.loads(Path(path).read_text()) if x["pack"] == pack), None)
    return next((c["status"] for c in (r or {}).get("checks", []) if c["name"] == check), "absent")


def controls():
    """FIXUP1: the three false-PASS controls of VERIFIER-AUDIT1 as labelled cases (synthetic folder, stubbed inputs):
    an unresolved prerequisite must be FAIL or NOT MODELLED, never PASS.  -> [(label, check, expect, got)]"""
    import tempfile
    from types import SimpleNamespace as NS
    from PIL import Image
    from d5lib import gametruth as gt
    folder = Path(tempfile.mkdtemp(prefix="gt-control-")) / "synthetic-pack"
    (folder / "patches/db").mkdir(parents=True)
    (folder / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 3000, "sprite_id": 3000, "body_type": 1}]}))
    out = []

    def get(r, name):
        return next(c.status for c in r.checks if c.name == name)
    r = gt.PackResult("synthetic", "other", True)
    gt._actions(folder, r, NS(check_mod=lambda _: [{"unit": 3000, "skill": 999999, "status": "unknown"}]))
    out.append(("unresolved skill analysis", "actions: skill caster motions", "NOT MODELLED", get(r, "actions: skill caster motions")))
    r = gt.PackResult("synthetic", "other", True)
    gt._actions(folder, r, NS(check_mod=lambda _: [{"unit": 3000, "skill": 5, "status": "fallback"}]))
    out.append(("fallback only (vanilla precedent)", "actions: skill caster motions", "PASS", get(r, "actions: skill caster motions")))
    r = gt.PackResult("synthetic", "other", True)
    gt._voice(NS(voice_sets={}), folder, {}, [{"id": 3000, "voice_id": 12345}], r, {})
    out.append(("donor voice id with no line", "voice", "FAIL", get(r, "voice")))
    r = gt.PackResult("synthetic", "other", True)
    gt._voice(NS(voice_sets={}, voice_loaded=False), folder, {}, [{"id": 3000, "voice_id": 12345}], r, {})
    out.append(("voice tables not loaded", "voice", "NOT MODELLED", get(r, "voice")))
    bank = NS(textures=[], palettes=[], blocks=[NS(animations=[NS(id=x) for x in gt.BODY_MOTIONS.values()])])
    a = NS(evaluate=lambda *x, **k: [1], render_items=lambda *x: (Image.new("RGBA", (1, 1), (1, 1, 1, 255)), None),
           render_root_mismatches=lambda *x: [])
    for label, have in (("battle bank N+1 missing", {3000}), ("battle bank pair N, N+1 present", {3000, 3001})):
        w = NS(anm=a, gfx_id=lambda cid, tier: 3000, bank=lambda _f, n, have=have: bank if n in have else None,
               resident={3002}, human=set(), folder_mode=False)
        r = gt.PackResult("synthetic", "other", True)
        gt._body(w, folder, [{"id": 3000, "sprite_id": 3000, "body_type": 1, "color_id": 3000, "tier": 0}], r)
        out.append((label, "body: any FAIL", "FAIL" if len(have) == 1 else "PASS", "FAIL" if r.worst() == "FAIL" else "PASS"))
    return out


def backup(prefix):
    return next(BK.glob(prefix + "*")) / "kit" / "mods"


def build_banks_packs(prefix):
    txt = (next(BK.glob(prefix + "*")) / "BUILD.txt").read_text()
    banks = json.loads(next(l for l in txt.splitlines() if l.startswith("banks:"))[6:])
    return sorted({k.split("/")[1] for k in banks})


def status(results, pack, check):
    r = next((x for x in results if x.pack == pack), None)
    if r is None:
        return "absent"
    s = [c.status for c in r.checks if c.name == check]
    return "FAIL" if "FAIL" in s else s[0] if s else "absent"


def quest_packs(mods):
    out = {}
    for f in sorted(Path(mods).iterdir()):
        p = f / "patches/db/Quest.dat.json"
        if p.is_file():
            for q in json.loads(p.read_text()).get("added") or []:
                out[int(q["id"])] = f.name
    return out


def old_resident(folder, clean_ids, old_newclasses):
    """anm_resident after the pre-NODRAW2 installer: clean blocks + what its monster_picture_blocks adds."""
    from d5lib import newclasses  # noqa: F401
    path = folder / "patches/characters/unique.json"
    declared = {}
    if path.is_file():
        d = json.loads(path.read_text())
        declared = {int(x["identity"]): x for x in (d.get("uniques") or [d]) if isinstance(x, dict) and x.get("identity") is not None}
    anime = folder / "files/Anime/ANM_HI_JP.dat"
    outputs = {f"anime/anm_hi_jp.dat/{p.name}".lower(): (None, p.read_bytes()) for p in anime.glob("*.lzs")} if anime.is_dir() else {}
    ctx = SimpleNamespace(outputs=outputs, fs=None, _char_uniques=declared, _monster_rows=[], log=lambda *a, **k: None)
    specs = {int(d["family"]): d for d in (json.loads(c.read_text()) for c in
                                            sorted((folder / "patches/classes").glob("class_*.json")))}
    return set(clean_ids) | set(old_newclasses.monster_picture_blocks(ctx, specs))


def voice_replay_rows(mods, order):
    """char rows after the pre-VOICE1b install (outfits._follow_base without own_voice declarations)."""
    from d5lib import database, dbpatch, gamefs, modsys, outfits
    table = database.load_table("char.dat", gamefs.GameFS(str(CLEAN)).read("Database/Database_0.dat/char.dat"))
    pairs = []
    for name in order:
        folder = Path(mods) / name
        if not (folder / "mod.json").is_file():
            continue
        f = folder / "patches/db/char.dat.json"
        if f.is_file():
            try:
                dbpatch.apply_patch(table, json.loads(f.read_text(encoding="utf-8-sig")))
            except Exception:                                    # noqa: BLE001
                pass
        pairs += [p for p in outfits.load(modsys.Mod(str(folder))) if p not in pairs]
    rows = {r["id"]: r for r in table.rows}
    outfits._follow_base(rows, pairs, set())
    return {int(k): int(r["voice_id"]) for k, r in rows.items()}


# REALSURVEY1 recruit order per session (scratch rec-s1.log, rec-s1b.log, group-s2.log, group-s3.log)
SURVEY_ORDER = {"s1": [440, 392, 322, 438, 439, 441, 394, 321, 318, 391],
                "s2": [309, 387, 393, 395, 304, 443, 442, 437], "s3": [435]}


def harness_walk(listed, sort, want, burst=5):
    """Replay of live-harness hub.quest_goto (QBOARD2) over the board list: cursor on row 1, bursts of `burst` rows,
    the lap check (sort_order drops) BEFORE the overshoot check.  None = reached; else the quest id the lap ended on.
    A target in the last burst-1 rows of the main list is jumped over onto the request rows (sort 501..) = a 'lap'."""
    target, p, last = sort[want], 0, -1
    while True:
        q = listed[p % len(listed)]
        if q == want:
            return None
        here = sort[q]
        if last >= 0 and here < last:
            return q
        last = here
        if here > target:                                    # overshoot: step back row by row
            for _ in range(burst + 2):
                p -= 1
                if listed[p] == want:
                    return None
                if sort[listed[p]] < target:
                    break
        p += burst


def main(out=None):
    from d5lib import gametruth as gt, anm, gamefs
    cases = []

    def add(src, label, state, pack, check, expect, got):
        cases.append(dict(source=src, label=label, state=state, pack=pack, check=check, expect=expect, got=got))

    inst = gt.World(save=SAVE)
    mods = inst.mods
    qp = quest_packs(mods)

    # ---- QBOARD1: the board (executed)
    if NIGHT1.is_file():
        night = json.loads(NIGHT1.read_text())
        wq = gt.World(save=SAVE, quest_rows=night)
        bad = (423, 424, 425)
        good = (396, 347, 422, 417, 305, 418, 419, 420, 421)
        packs = {qp[q] for q in bad + good if q in qp}
        rq = gt.run(wq, only=packs, survey=False, voices=False)
        ri = gt.run(inst, only=packs, survey=False, voices=False)
        for q in bad + good:
            if q not in qp:
                continue
            exp = "FAIL" if q in bad else "PASS"
            add("live (NIGHT1 board + QBOARD1)", f"quest {q}", "NIGHT1 Quest.dat", qp[q], "recruit: board", exp,
                status(rq, qp[q], "recruit: board"))
            add("live (QBOARD1 fix installed)", f"quest {q}", "installed", qp[q], "recruit: board", "PASS",
                status(ri, qp[q], "recruit: board"))
        # executed vs QBOARD1's re-implementation and the game's drawn list
        sim = Path("/Volumes/Data/ai-tmp/claude/QBOARD1-20261110-024908/offered_night1.json")
        if sim.is_file():
            want = [x[0] for x in json.loads(sim.read_text())]
            got = [i for i in wq.board()["listed"] if i < 2000]
            add("offline (QBOARD1 sim.py rule)", f"{len(want)} offered ids", "NIGHT1 Quest.dat", "-", "board list equal",
                "PASS", "PASS" if got == want else f"FAIL ({len(got)} vs {len(want)})")

    # ---- NODRAW2: monster placeholder (pre-fix installer replay)
    old = BK / "20261110-0930-KITCODE-NODRAW2EG/d5lib/newclasses.py"
    spec = importlib.util.spec_from_file_location("d5lib._old_newclasses", old)
    oldmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oldmod)
    clean = {b.id for b in anm.parse(gamefs.GameFS(str(CLEAN)).read("Anime/ANM_HI_JP.dat/anm_resident.lzs")).blocks}
    live_bad = {"Beatrice": 16730, "Hanako": 16540, "Suisen": 16820, "ColossalPrinny": 17050, "OverlordAsagi": 16600}
    live_good = ("Zed", "Barbara", "Merome", "Lanzarote", "Garbage")
    from d5lib import importcore
    nd_fail, nd_names = [], []
    for f in sorted(mods.iterdir()):
        if not (f / "mod.json").is_file() or (inst.enabled and f.name not in inst.enabled):
            continue
        ok_now, why_now = importcore.resident_placeholder_gate(f, resident_ids=inst.resident)
        if why_now.startswith("no monster"):
            continue
        then = f if f.name != "D1C_Unique_3130" else backup("20261110-1229-INSTALL3B") / f.name   # before SMALLFIX1
        r_old = old_resident(then, clean, oldmod)
        res_old = gt.check_pack(inst, f, None, {}, resident_override=r_old)
        st_old = status([res_old], f.name, "body: monster placeholder")
        label = next((k for k in live_bad if k.lower() in f.name.lower().replace("_", "")), None)
        src = "live (NODRAW2 recruits)" if label else "offline (NODRAW2 installed sweep, 42 packs)"
        exp_old = "FAIL" if f.name.startswith(("DRPG_Core", "D1C_Unique_3130")) else "PASS"
        add(src, label or f.name, "installer before 53c3947", f.name, "body: monster placeholder", exp_old, st_old)
        add(src, label or f.name, "installed", f.name, "body: monster placeholder", "PASS", "PASS" if ok_now else "FAIL")
    for g in live_good:
        f = next((x for x in mods.iterdir() if x.name.startswith("DRPG_Core_" + g)), None)
        if f:
            r = gt.check_pack(inst, f, None, {})
            for c in ("body: monster placeholder", "body: idle draws (front/back)", "body: render root"):
                add("live (NODRAW2: humanoid recruit drew)", g, "installed", f.name, c, "PASS", status([r], f.name, c))

    # ---- BACKVIEW1: render root (pre-fix folders)
    live_bv = {"D4_Unique_4390": "Kojiro", "D4_Unique_5301": "Chief", "D4_Unique_5307": "Garatea", "D4_Unique_5306": "Baltis"}
    for prefix in ("20261110-1610-BACKVIEW1", "20261110-1645-BACKVIEW1B"):
        bmods = backup(prefix)
        packs = set(build_banks_packs(prefix))
        wb = gt.World(mods=bmods, folder_mode=True)
        rb = gt.run(wb, only=packs, survey=False, voices=False)
        ri = gt.run(inst, only=packs, survey=False, voices=False)
        for p in sorted(packs):
            src = "live (BACKVIEW1: back view empty)" if p in live_bv else "offline (BACKVIEW1 gate sweep)"
            add(src, live_bv.get(p, p), "pre-BACKVIEW1 folder", p, "body: render root", "FAIL", status(rb, p, "body: render root"))
            add(src, live_bv.get(p, p), "installed", p, "body: render root", "PASS", status(ri, p, "body: render root"))
            if p in live_bv:
                add(src, live_bv[p], "pre-BACKVIEW1 folder", p, "body: idle draws (front/back)", "FAIL",
                    status(rb, p, "body: idle draws (front/back)"))
                add(src, live_bv[p], "installed", p, "body: idle draws (front/back)", "PASS",
                    status(ri, p, "body: idle draws (front/back)"))

    # ---- SMALLFIX1: portrait template + DRPG titles (pre-INSTALL3B folders)
    smods = backup("20261110-1229-INSTALL3B")
    ws = gt.World(mods=smods, folder_mode=True)
    sp = {"D1C_Unique_3130": ("live (Shark King blank portrait)", "status: portrait"),
          "DD2_Unique_941": ("offline (SMALLFIX1 sweep: Xenolith same defect)", "status: portrait"),
          "DRPG_Core_Beatrice_20033": ("live (Beatrice panel: 'Disgaea RPG' title)", "status: name/title")}
    drpg = sorted(x.name for x in smods.iterdir() if x.name.startswith("DRPG_Core_"))[:12]
    for p in drpg:
        sp.setdefault(p, ("offline (SMALLFIX1: 144 packs carried the label)", "status: name/title"))
    rs = gt.run(ws, only=set(sp), survey=False, voices=False)
    ri = gt.run(inst, only=set(sp), survey=False, voices=False)
    for p, (src, c) in sp.items():
        exp = "PASS" if any(p.endswith("_" + k) for k in ("60019", "60025")) else "FAIL"
        add(src, p, "pre-INSTALL3B folder", p, c, exp, status(rs, p, c))
        add(src, p, "installed", p, c, "PASS", status(ri, p, c))

    # ---- INSTALL4: costume voices overwritten (pre-VOICE1b outfit step)
    order = json.loads((mods.parent / "profiles/MAIN/load_order.json").read_text())
    pre = voice_replay_rows(mods, order)
    wv = gt.World(save=SAVE)
    for cid, r in wv.chars.items():
        if cid in pre and int(r["voice_id"]) != pre[cid]:
            r.set("voice_id", pre[cid])
    vpacks = sorted(x.name for x in mods.iterdir() if x.name.startswith("DRPG_Core_")
                    and (x / "patches/voices/voices.json").is_file() and (x / "patches/outfits/outfits.json").is_file())
    rv = gt.run(wv, only=set(vpacks), survey=False, voices=True)
    ri = gt.run(inst, only=set(vpacks), survey=False, voices=True)
    for p in vpacks:
        rr = next(x for x in rv if x.pack == p)
        costume = any(cid >= 30000 for cid in rr.rows)
        add("offline readback (INSTALL4: 89 costume rows after a real install)", p, "outfit step before VOICE1b", p,
            "voice", "FAIL" if costume else "PASS", status(rv, p, "voice"))
        add("offline readback (VOICE1b installed)", p, "installed", p, "voice", "PASS", status(ri, p, "voice"))

    # ---- REALSURVEY1 known-good / known-bad sightings
    rsv = json.loads((EE / "REALSURVEY1-results.json").read_text())["entries"]
    seen = {k: v for k, v in rsv.items() if v.get("result", "").startswith("proven")}
    rr = gt.run(inst, only=set(seen), survey=True, voices=True)
    defend_only = 0
    for p, v in seen.items():
        if p in EVILFX2_FIXED:
            # FIXUP1: the sighting (page 3 blank) was true before EVILFX2's install and is false after it; pin both
            before = pinned_status(LIVE5_BEFORE, p, "status: innate evility")
            add("live (REALSURVEY1 status page 3, before EVILFX2 install)", v["name"], "pre-EVILFX2 install", p,
                "status: innate evility", "FAIL" if not v["a_status"] else "PASS", before)
            add("offline (EVILFX2 install, same pack)", v["name"], "installed", p, "status: innate evility",
                "PASS", status(rr, p, "status: innate evility"))
        else:
            add("live (REALSURVEY1 status page 3)", v["name"], "installed", p, "status: innate evility",
                "PASS" if v["a_status"] else "FAIL", status(rr, p, "status: innate evility"))
        for c in ("body: idle draws (front/back)", "body: render root", "body: monster placeholder", "body: graphics id",
                  "status: portrait", "status: name/title"):
            add("live (REALSURVEY1 front/back + panel)", v["name"], "installed", p, c, "PASS", status(rr, p, c))
        rc = "recruit: class page" if "_Class_" in p else "recruit: board"     # classes come from the Recruiter
        add("live (REALSURVEY1 recruited)", v["name"], "installed", p, rc, "PASS", status(rr, p, rc))
        defend_only += 1      # FIXUP1: c_action was Defend + End Turn (REALSURVEY1-REPORT line 13), not a skill: no case

    # ---- QBOARD2: REALSURVEY1's four "not offered" quests are on the game's board; the harness walk missed them
    sort = {int(q["id"]): int(q["sort_order"]) for q in inst.quests}
    title = {int(q["id"]): q["name_EN"] for q in inst.quests}
    board = inst.board()["listed"]
    for sess, seq in SURVEY_ORDER.items():
        done = set()
        for qid in seq:
            listed = [i for i in board if i not in done]
            got = harness_walk(listed, sort, qid)
            live = next((v for v in rsv.values() if v.get("quest") == qid), {})
            if live.get("result") == "not recruited":
                p = qp[qid]
                add("live (REALSURVEY1 not offered, QBOARD2)", f"quest {qid}", "installed", p, "recruit: board", "PASS",
                    status(gt.run(inst, only={p}, survey=False, voices=False), p, "recruit: board"))
                exp = live["why"].split("lap ended at ")[1].split(")")[0]          # e.g. 'Great Deals'
                add("live (REALSURVEY1 not offered, QBOARD2)", f"quest {qid}", "installed", p, "harness walk replay",
                    "PASS", "PASS" if title.get(got) == exp.strip("'") else f"FAIL (replay: {title.get(got, got)})")
            else:
                add("live (REALSURVEY1 recruited, QBOARD2)", f"quest {qid}", "installed", qp.get(qid, "-"),
                    "harness walk replay", "PASS", "PASS" if got is None else f"FAIL (replay lap at {title[got]})")
                done.add(qid)

    # ---- stats: the two live LV1 readings lie inside the executed oracle's roll range
    sys.path.insert(0, str(KIT / "tools"))
    import stat_oracle as so
    for name, lr in so.LIVE_READINGS.items():
        rows = gt.added_rows(mods / lr["mod"], "char.dat")
        r0 = inst.chars[int(rows[0]["id"])]
        base = [int(r0["base_" + s]) for s in so.STATS]
        ok = all(so.rolls_consistent(base, lr["level"], lr["stats"]))
        add("live (STATORACLE1 LV1 reading)", name, "installed", lr["mod"], "stats: creation", "PASS", "PASS" if ok else "FAIL")

    # ---- FIXUP1 controls: unresolved prerequisites are never a PASS
    for label, check, expect, got in controls():
        add("synthetic control (VERIFIER-AUDIT1)", label, "stubbed", "synthetic-pack", check, expect, got)

    # ---- pending coverage: stays visible in every acceptance summary
    pending = collections.Counter()
    for r in rr:
        for c in r.checks:
            if c.status == "NOT MODELLED":
                pending[c.name] += 1
    pending_live = ["battle entry/bank bind of a deployed unit", "normal attacks (weapon -> script -> motion)",
                    "skill playback and evility effects in battle", "audible voice/sound output", "timing / freeze under load",
                    "REALSURVEY1 action = Defend/End Turn only (%d sightings): not skill evidence" % defend_only]
    print("PENDING COVERAGE (not accepted by this corpus):")
    for k, v in sorted(pending.items()):
        print(f"  NOT MODELLED  {k}: {v} pack(s) in the REALSURVEY1 set")
    for x in pending_live:
        print("  live only    ", x)

    # ---- table
    conf = collections.Counter((c["expect"], c["got"]) for c in cases)
    by = collections.defaultdict(collections.Counter)
    for c in cases:
        by[(c["source"].split(" (")[0], c["check"])][("ok" if c["expect"] == c["got"] else "wrong")] += 1
    print("expected -> got:", dict(conf))
    for k, v in sorted(by.items()):
        print(f"  {k[0]:22} {k[1]:32} right {v['ok']:4} wrong {v['wrong']:3}")
    wrong = [c for c in cases if c["expect"] != c["got"]]
    for c in wrong:
        print("WRONG", c)
    if out:
        Path(out).write_text(json.dumps(dict(confusion={f"{a}->{b}": n for (a, b), n in conf.items()}, cases=cases,
                                             pending_modelled=dict(pending), pending_live=pending_live), indent=1))
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
