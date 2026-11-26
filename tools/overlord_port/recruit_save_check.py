"""OLWISH1 offline check: do passed recruit bills store anything by bill id in a save?

Reads a COPY of Save1 (Save_001.sav; refuses any other file name, in particular Save_002 = Save2, known bad).
The input is copied into --work-dir, the copy's sha256 must equal --sha256 (when given), and the original is only read.

What it establishes, and what it does not:
  * the converted rows (patches/db/WishDataBase.dat.json) have set_flag/clear_flag/block_flag all 0, so passing a
    recruit bill changes no story flag; the only effect is wishrecruit's roster_create_unit call (a roster unit,
    stored by its class and serial like any unit, not by bill id);
  * the kit's save parser knows no per-bill structure (savegame.py maps roster, squads, groups, quest slots, story
    flags, stages); the save is parsed and none of those is addressed by a wish id, so re-keying 1049..1057 ->
    2049..2057 cannot orphan a record;
  * Save1 holds none of the recruit classes yet (no bill has been passed in it);
  * which of his required flags (req_flag1) Save1 already has set -> which bills would be listed in it.
It does NOT prove the game writes nothing else on passing a bill (that needs the live game, RECRUIT1-LIVE).
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

FLAG_PREFIXES = ("set_flag", "clear_flag", "block_flag")
ALLOWED = "Save_001.sav"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(save, rows, recruits):
    """save: anything with .units() (each .cls) and .flag(n); rows: converted WishDataBase rows; recruits: the
    {"recruits": {...}} json.  -> report dict with a boolean 'pass' and per-check results"""
    out = {"checks": []}

    def ck(name, ok, detail=None):
        out["checks"].append({"check": name, "ok": bool(ok), "detail": detail})

    flagged = [(r["id"], k, r[k]) for r in rows for k in r
               if k.startswith(FLAG_PREFIXES) and r[k]]
    ck("passing a recruit bill sets, clears and blocks no flag (all set/clear/block_flag1..4 are 0)",
       not flagged, flagged)
    ids = sorted(int(b) for b in recruits["recruits"])
    ck("every recruit bill id is a converted row id", ids == sorted(r["id"] for r in rows), ids)
    held = {u.cls for u in save.units()}
    owned = sorted(int(e["character"]) for e in recruits["recruits"].values() if int(e["character"]) in held)
    ck("Save1 holds none of the recruit classes (nothing stored by passing a bill yet)", not owned, owned)
    gates = {}
    for r in rows:
        if r.get("req_flag1"):
            gates[str(r["id"])] = {"req_flag1": r["req_flag1"], "set_in_save": save.flag(r["req_flag1"])}
    out["req_flag_state"] = gates
    out["listed_bills_in_save"] = sorted(int(b) for b, g in gates.items() if g["set_in_save"])
    out["pass"] = all(c["ok"] for c in out["checks"])
    return out


def run(save_path, mod_dir, work_dir, sha=None):
    from d5lib import savegame
    name = os.path.basename(save_path)
    if name != ALLOWED:
        raise SystemExit(f"refusing {name}: only a copy of Save1 ({ALLOWED}) is read here (Save2 is known bad)")
    os.makedirs(work_dir, exist_ok=True)
    work = os.path.join(work_dir, name)
    shutil.copyfile(save_path, work)
    digest = sha256(work)
    if sha and digest != sha:
        raise SystemExit(f"sha256 of the copy is {digest}, expected {sha}")
    rows = json.load(open(os.path.join(mod_dir, "patches", "db", "WishDataBase.dat.json"),
                          encoding="utf-8"))["added"]
    recruits = json.load(open(os.path.join(mod_dir, "patches", "wishes", "recruit_wishes.json")))
    save = savegame.Save(work)
    rep = check(save, rows, recruits)
    rep.update({"save_copy": work, "sha256": digest, "army": save.army_count, "reserve": save.reserve_count})
    if sha256(save_path) != digest:
        raise SystemExit("the original changed while it was read")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", required=True, help="Save_001.sav (Save1); copied, never written")
    ap.add_argument("--mod", required=True, help="converted mod folder (recruit_wishes.py output)")
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--sha256")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = run(a.save, a.mod, a.work_dir, a.sha256)
    text = json.dumps(rep, indent=1)
    if a.out:
        open(a.out, "w").write(text)
    for c in rep["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"])
    print("bills whose gate flag Save1 has:", rep["listed_bills_in_save"])
    print("OVERALL", "PASS" if rep["pass"] else "FAIL")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
