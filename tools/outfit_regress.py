"""Regression probe for the outfit builder: one canonical projection of every existing outfit input.

Read-only.  Run it from a worktree root (or with PYTHONPATH set to one):

    python tools/outfit_regress.py > /tmp/before.json     # on the old tree
    python tools/outfit_regress.py > /tmp/after.json      # on the new tree

Nothing here touches the game, the installed kit or a mod folder: the inputs are the *existing* outfits.json
files (read-only), the char.dat rows are synthetic and identical in both runs, and the one file the builder
writes is written into a scratch module and hashed.  Equal output = the builder makes the same decisions for
every input that does not declare a colour (DRPG-K1 regression gate).
"""
import glob
import hashlib
import json
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from d5lib import modsys, outfits                                        # noqa: E402

INPUTS = "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods/*/patches/outfits/outfits.json"


def rows_for(pairs):
    """Synthetic char.dat rows: every referenced id and its whole rank family (so generic expansion is exercised)."""
    ids = set()
    for a, b in pairs:
        for c in (int(a), int(b)):
            ids |= set(range(c, c + 10))
    return {i: {"id": i, "sprite_id": i, "color_id": i, "body_type": 0,
                "name_EN": f"row{i}"} for i in sorted(ids)}


def projection(path):
    data = json.loads(Path(path).read_text())
    pairs = [[int(a), int(b)] for a, b in data.get("pairs") or []]
    names = {int(k): v for k, v in (data.get("names") or {}).items()}
    hidden = {int(x) for x in data.get("hide") or []}
    rows = rows_for(pairs)
    out = {"input": Path(path).parts[-4], "pairs": pairs}
    if not pairs:
        out["groups"] = None
        return out
    records, strings, bases, members, key_of = outfits._groups(pairs, names, rows, hidden)
    out["groups"] = {"records": [list(r) for r in records], "strings": strings,
                     "bases": bases, "members": {str(k): v for k, v in members.items()},
                     "key_of": {str(k): v for k, v in key_of.items()}}
    out["looks"] = {str(k): list(v) for k, v in outfits._looks(records, rows).items()}
    out["colours"] = {str(slot): (slot if outfits.own_colour(slot) else rows[base]["color_id"])
                      for base in bases for slot in members[base]}
    # list-icon owners, with the two image helpers replaced by markers (no textures read here)
    old_small, old_base = outfits._small_face_image, outfits.base_face_image
    outfits._small_face_image = lambda ctx, colour: ["cell", colour]
    outfits.base_face_image = lambda fs, colour: ["face", colour]

    class Ctx:
        fs = None
    try:
        owners = outfits._outfit_icon_owners(Ctx(), pairs, rows, {})
    finally:
        outfits._small_face_image, outfits.base_face_image = old_small, old_base
    out["icon_owners"] = [[k, list(cs), img] for k, cs, img in owners]
    # the one file the builder writes for these inputs
    with tempfile.TemporaryDirectory() as tmp:
        mod = modsys.Mod(tmp)
        outfits.save(mod, pairs, names=names)
        p = Path(tmp) / "patches/outfits/outfits.json"
        raw = p.read_bytes() if p.is_file() else b""
        out["saved_sha256"] = hashlib.sha256(raw).hexdigest()
    return out


def main():
    files = sorted(glob.glob(INPUTS))
    print(json.dumps([projection(f) for f in files], indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
