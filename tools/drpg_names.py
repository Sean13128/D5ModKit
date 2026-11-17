"""Disgaea RPG unit names from the game's own masters/charactername, added to a "Units IDs.txt".

    python tools/drpg_names.py MASTERS --dump                     what the table holds (its fields, a few rows)
    python tools/drpg_names.py MASTERS --names "Units IDs.txt"    add the units the file doesn't name yet

MASTERS: the install's masters folder (or the file masters/charactername itself).  The names are the game's, so
Japanese for the JP edition: each added line ends in "[JP]".  Names the file already has are kept.  The old file is
kept as "Units IDs.txt.bak".  Needs UnityPy (pip install UnityPy).
"""
import argparse
import os
import re
import shutil
import sys


def rows(path):
    """the table's rows: the first list of records in the bundle's MonoBehaviour"""
    import UnityPy
    env = UnityPy.load(path)
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        for v in tree.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    raise SystemExit(f"{path}: no table found (no MonoBehaviour with a list of records)")


def pick_keys(sample, id_key=None, name_key=None):
    keys = list(sample)
    if not id_key:
        id_key = next((k for k in ("character_id", "chara_id", "id") if k in sample), None)
    if not name_key:
        named = [k for k in keys if "name" in k.lower() and isinstance(sample[k], str)]
        name_key = "name" if "name" in named else (named[0] if named else None)
    if not id_key or not name_key:
        raise SystemExit(f"can't tell the id / name fields among {keys}: give --id-key and --name-key")
    return id_key, name_key


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("masters")
    ap.add_argument("--names", help='the "Units IDs.txt" to add to')
    ap.add_argument("--dump", action="store_true", help="show the table's fields and first rows, change nothing")
    ap.add_argument("--id-key")
    ap.add_argument("--name-key")
    a = ap.parse_args()
    path = a.masters
    if os.path.isdir(path):
        path = os.path.join(path, "charactername")
    table = rows(path)
    if a.dump or not a.names:
        print(f"{len(table)} rows; fields: {list(table[0])}")
        for r in table[:8]:
            print(r)
        return
    id_key, name_key = pick_keys(table[0], a.id_key, a.name_key)
    game = {}
    for r in table:
        try:
            uid = int(r[id_key])
        except (KeyError, TypeError, ValueError):
            continue
        name = " ".join(str(r.get(name_key) or "").split())
        if name:
            game.setdefault(uid, name)
    have = set()
    text = ""
    if os.path.exists(a.names):
        with open(a.names, encoding="utf-8") as f:
            text = f.read()
        have = {int(m) for m in re.findall(r"^(\d+)\s+\S", text, re.M)}
    new = {u: n for u, n in sorted(game.items()) if u not in have}
    if not new:
        print(f"nothing to add: the file names every one of the {len(game)} units in {path}")
        return
    if text:
        shutil.copyfile(a.names, a.names + ".bak")
    # added lines go before the first group header: they get no group (the kit tells monsters by itself)
    block = "".join(f"{u} {n} [JP]\n" for u, n in new.items())
    m = re.search(r"^-+\s*.+?\s*-+$", text, re.M)
    text = text[:m.start()] + block + "\n" + text[m.start():] if m else text + block
    with open(a.names, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"added {len(new)} names ({id_key} / {name_key}) to {a.names}; {len(game) - len(new)} were there already")


if __name__ == "__main__":
    sys.exit(main())
