#!/usr/bin/env python3
"""BLANKKEYS1: build the fixed packs.  Start from the INSTALLED pack folder (its bank equals the installed archive
bank; checked), change only the motions in the scope list and keep texture and palette counts.

    D5Modkit/.venv-macos/bin/python tools/blankkeys_apply.py --scope SCOPE.json --out DIR/mods
        [--fresh PACK=BANKNO=FRESH.lzs ...] [--skip-packs P1,P2]

* --fresh: a rebuild with the source attack frames (pt1030_rebuild_d1c.py --attack-track): its clock is replaced by the
  installed bank's for every animation it did not change on purpose (ownanim.restore_timing), then it stands in for the bank.
* every other flagged animation: ownanim.hold_blank_keys on the installed bank (pose held on blank key times).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
sys.dont_write_bytecode = True

import bank_compare as bc  # noqa: E402
import roster_sheets as rs  # noqa: E402
from d5lib import anm, ownanim  # noqa: E402

ANIME = rs.ANIME


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fresh", action="append", default=[])
    ap.add_argument("--attack-ids", default="2071,2077", help="ids the fresh rebuild changed on purpose (PACK=ids overrides)")
    ap.add_argument("--skip-packs", default="")
    ap.add_argument("--mods", type=Path, default=rs.GAME / "D5ModKit" / "mods")
    a = ap.parse_args(argv)
    ctx = rs.Ctx(mods=a.mods)
    scope = json.loads(a.scope.read_text())
    skip = set(filter(None, a.skip_packs.split(",")))
    fresh = {}
    for spec in a.fresh:
        pack, no, path, *ids = spec.split("=")
        fresh.setdefault(pack, {})[int(no)] = (path, tuple(int(i) for i in (ids[0] if ids else a.attack_ids).split(",")))
    by_pack = {}
    for game, name, pack, kind, bank, aid, d, t, v in scope:
        if pack not in skip:
            by_pack.setdefault(pack, dict(name=name, game=game, anims={}))["anims"].setdefault(bank, []).append(aid)
    report = {}
    for pack, info in sorted(by_pack.items()):
        src = a.mods / pack
        dst = a.out / pack
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        rep = report[pack] = dict(name=info["name"], game=info["game"], banks={})
        for bank, aids in sorted(info["anims"].items()):
            path = dst / "files" / ANIME / f"anm{bank:05d}.lzs"
            cur = bc.load(path)
            arch, _ = ctx.bank(pack, bank)
            same = set(bc.compare(cur, arch).values()) == {"same"} if arch is not None else None
            r = rep["banks"][bank] = dict(pack_equals_installed_archive=same, rebuilt=None, held={}, untouched=[])
            counts = (len(cur.textures), len(cur.palettes))
            if pack in fresh and bank in fresh[pack]:
                fpath, ids = fresh[pack][bank]
                new = bc.load(fpath)
                done, left = ownanim.restore_timing(new, cur, skip=ids)
                r["rebuilt"] = dict(ids_from_source_rebuild=list(ids), timing_restored=done, left_on_fresh_clock=left)
                if (len(new.textures), len(new.palettes)) != counts:
                    raise SystemExit(f"{pack} anm{bank}: texture/palette count {counts} -> {(len(new.textures), len(new.palettes))}")
                cur = new
            for aid in aids:
                before = _drawn(cur, aid)
                n = ownanim.hold_blank_keys(cur, aid)
                after = _drawn(cur, aid)
                if n:
                    r["held"][aid] = dict(before=before, after=after, keys_filled=n)
                else:
                    r["untouched"].append(dict(id=aid, drawn=before, why="not changed: nothing drawn on any key (an attachment layer the import hides on purpose), or every drawing layer is shared with another animation"))
            assert (len(cur.textures), len(cur.palettes)) == counts
            path.write_bytes(anm.lzs_compress(cur.to_bytes()))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out.parent / "blankkeys1-apply.json").write_text(json.dumps(report, indent=1))
    print(f"{len(report)} packs written under {a.out}")


def _drawn(fl, aid):
    ts = anm.frame_times(fl, ("id", aid))
    return [sum(1 for t in ts if any(i.cell.w > 0 and i.cell.h > 0 for i in anm.evaluate(fl, ("id", aid), t, nested=True))), len(ts)]


if __name__ == "__main__":
    main()
