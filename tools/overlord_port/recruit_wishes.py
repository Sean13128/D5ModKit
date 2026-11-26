"""OLWISH1: convert Overlord's Recruit Wishes to the kit's recruit-wish format (d5lib/wishrecruit.py).

Input
  * his WishDataBase rows for the 14 recruit bills (the "Overlord Recruit Wishes" mod's
    patches/db/WishDataBase.dat.json, {"table": "WishDataBase.dat", "added": [rows]}), and
  * his recruit table: mods/_loader/custom_wishes.txt, `wish=character,level,duplicates[,required_flag[,alias]]`
    (parse_custom_wishes), or the built-in copy of RELEASE.md section 8 (OVERLORD_TABLE) when the file is not at hand.

Output (a mod folder)
  patches/db/WishDataBase.dat.json     his rows, bills 1000..1999 re-keyed +1000 (1049..1057 -> 2049..2057), the
                                       row's own req_flag1 = his required flag
  patches/wishes/recruit_wishes.json   {"recruits": {bill: {character, level[, duplicates]}}}
  mod.json

Why re-key: the game's Item Assembly lists exactly the bill ids 1000..1999 and the Strategy Assembly hides them
(RECRUIT1-REPORT section 1), so wishrecruit refuses recruit bills below 2000.  His 20000/20010/20300/20310/20500
are already clear and keep their ids.  Why req_flag1: he keeps the unlock flag in custom_wishes.txt; the kit's row
carries it itself and the game's own predicate applies it.

Nothing here touches the game, an install, a profile or a save.  Credit: Cryswar (Disgaea 5 Overlord Edition,
The Unlicense).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from d5lib import wishrecruit   # noqa: E402

REKEY_FROM = range(1000, 2000)
REKEY_BY = 1000
KEEP_FLAG_FIELDS = ("req_flag1",)
CREDIT = "Cryswar (Disgaea 5 Overlord Edition v3, The Unlicense); converted by D5 Mod Kit, offline"

# RELEASE.md section 8: wish -> (character, level, duplicates, required flag, comment in his file)
OVERLORD_TABLE = {
    1049: (90, 60, False, 1199, "berserk usalia, beat Toto Bunny Castle"),
    1050: (170, 120, False, 1699, "liezerota, beat her in main story"),
    1051: (430, 2000, False, 19117, "prinny overlord, beat him in carnage storyline"),
    1052: (770, 9999, False, 13502, "baal"),
    1053: (820, 9999, False, 13502, "baal bit (fire)"),
    1054: (830, 9999, False, 13502, "baal bit (ice)"),
    1055: (840, 9999, False, 13502, "baal bit (wind)"),
    1056: (850, 9999, False, 13502, "baal bit (star)"),
    1057: (2615, 5000, False, 19146, "proto darkdeath, beat him in item world"),
    20000: (20000, 50, True, 17127, "battlesuit"),
    20010: (20010, 100, True, 1699, "android"),
    20300: (20300, 10, False, 399, "stella"),
    20310: (20310, 10, False, 399, "rutile"),
    20500: (20500, 100, True, 1699, "majin"),
}


def rekey(bill):
    """the kit bill id for one of his: 1000..1999 move up 1000, every other id stays"""
    return bill + REKEY_BY if bill in REKEY_FROM else bill


def parse_custom_wishes(text):
    """his custom_wishes.txt -> {wish: (character, level, duplicates, required flag, comment)}.
    Lines are `wish=character,level,allow_duplicates[,required_flag[,cleanup_alias]]`; `#` starts a comment.
    A line that does not parse raises ValueError (a converter must not skip a bill silently)."""
    out = {}
    for n, raw in enumerate(text.lstrip("﻿").splitlines(), 1):
        line, _, comment = raw.partition("#")
        line = line.strip()
        if not line:
            continue
        left, eq, right = line.partition("=")
        parts = [p.strip() for p in right.split(",")]
        try:
            if not eq or len(parts) < 3:
                raise ValueError
            wish = int(left.strip(), 10)
            dup = parts[2].lower() in ("1", "true", "yes", "on")
            if parts[2].lower() not in ("0", "1", "true", "false", "yes", "no", "on", "off"):
                raise ValueError
            flag = int(parts[3], 10) if len(parts) > 3 and parts[3] else 0
            entry = (int(parts[0], 10), int(parts[1], 10), dup, flag, comment.strip())
        except ValueError:
            raise ValueError(f"custom_wishes.txt line {n}: cannot read {raw.strip()!r}") from None
        if wish in out and out[wish][:4] != entry[:4]:
            raise ValueError(f"custom_wishes.txt line {n}: wish {wish} listed twice with different values")
        out[wish] = entry
    return out


def convert_rows(rows, table):
    """-> (kit rows, recruits json, report).  rows: his WishDataBase rows (dicts); table: wish -> entry.
    Every table entry needs its row and every row needs its entry; the re-keyed ids must not collide."""
    by_id = {}
    for r in rows:
        if r["id"] in by_id:
            raise ValueError(f"bill {r['id']}: two rows with that id")
        by_id[r["id"]] = r
    missing = sorted(set(table) - set(by_id))
    extra = sorted(set(by_id) - set(table))
    if missing:
        raise ValueError(f"recruit table lists bills with no WishDataBase row: {missing}")
    if extra:
        raise ValueError(f"WishDataBase rows with no recruit table entry: {extra}")
    new_ids = [rekey(b) for b in table]
    if len(set(new_ids)) != len(new_ids):
        raise ValueError("re-keying makes two bills share an id")
    out_rows, recruits, mapping = [], {}, []
    for bill in sorted(table):
        character, level, dup, flag, note = table[bill]
        kit = rekey(bill)
        row = dict(by_id[bill])
        row["id"] = kit
        for f in KEEP_FLAG_FIELDS:
            if row.get(f):
                raise ValueError(f"bill {bill}: row already has {f} = {row[f]}; refusing to overwrite it")
        row["req_flag1"] = flag
        out_rows.append(row)
        rec = {"character": character, "level": level}
        if dup:
            rec["duplicates"] = True
        if note:
            rec["note"] = note
        recruits[str(kit)] = rec
        mapping.append({"overlord_bill": bill, "kit_bill": kit, "character": character, "level": level,
                        "duplicates": dup, "req_flag1": flag})
    wishrecruit.normalise(recruits)          # the kit's own rules: raises on anything its hooks could not honour
    return out_rows, {"recruits": recruits}, {"bills": mapping}


def convert(rows_json, out_dir, table=None, custom_wishes=None):
    """read his WishDataBase patch, write the kit mod under out_dir -> report dict"""
    if table is None:
        table = parse_custom_wishes(open(custom_wishes, encoding="utf-8").read()) if custom_wishes \
            else OVERLORD_TABLE
    with open(rows_json, encoding="utf-8") as f:
        src = json.load(f)
    rows, recruits, report = convert_rows(src["added"], table)
    db = os.path.join(out_dir, "patches", "db")
    wd = os.path.join(out_dir, "patches", wishrecruit.FOLDER)
    os.makedirs(db, exist_ok=True)
    os.makedirs(wd, exist_ok=True)
    with open(os.path.join(db, "WishDataBase.dat.json"), "w", encoding="utf-8") as f:
        json.dump({"table": src.get("table", "WishDataBase.dat"), "added": rows}, f, ensure_ascii=False, indent=1,
                  sort_keys=True)
    with open(os.path.join(wd, wishrecruit.DATA_FILE), "w", encoding="utf-8") as f:
        json.dump(recruits, f, indent=1)
    with open(os.path.join(out_dir, "mod.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "Overlord Recruit Wishes", "author": CREDIT, "version": "0.0.2-converted",
                   "description": "his 14 recruit wishes as kit recruit wishes: bills 1049..1057 re-keyed to "
                                  "2049..2057, his required flag in the row's req_flag1. Needs the kit's "
                                  "wishrecruit hooks (RECRUIT1).",
                   "enabled_by_default": True}, f, indent=1)
    report["out"] = out_dir
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--wishes", required=True, help="his WishDataBase.dat.json patch (the 14 added rows)")
    ap.add_argument("--custom-wishes", help="his mods/_loader/custom_wishes.txt (default: the RELEASE.md §8 table)")
    ap.add_argument("--out", required=True, help="mod folder to write")
    a = ap.parse_args(argv)
    rep = convert(a.wishes, a.out, custom_wishes=a.custom_wishes)
    for b in rep["bills"]:
        print(f"{b['overlord_bill']:>6} -> {b['kit_bill']:>6}  char {b['character']:>5} lv {b['level']:>4} "
              f"{'dup ' if b['duplicates'] else '    '} req_flag1 {b['req_flag1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
