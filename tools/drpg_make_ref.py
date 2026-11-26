"""Rebuild d5lib/data/drpg_ref_humanoid.pickle (the DRPG learned pose reference) from Girl Laharl's labelled sheet.

The pickle is not in Git; the upstream release zip ships it and names its generator `_research/drpg_make_ref.py`
(unpublished).  POSEREF1 (2026-11-22) found the rule by reproducing every field of the shipped file from the labelled
frame dump the same release zip carries, `SpriteSheet/Girl_Laharl/Girl_Laharl_Swimsuit_SS.png`:

* rows and labels: `framesheet.parse_sheet` + `framesheet.guess_rows` (the kit's own sheet reader and its
  `sheet_labels.pickle`); 53 labelled rows, 110 cells;
* one entry per non-empty cell, in sheet reading order (9 hand-overlay cells are fully transparent and are skipped:
  110 - 9 = 101 entries);
* `canvas` = the cell size (h, w); `offset` = top-left of the cell's alpha > 0 pixels; `mask` = those pixels cropped;
  `feats` = `drpg.features` of the cropped RGBA; `pos` = index of the cell in its row;
* `sheet` = the DRPG atlas the pose lives in: 'wait_front' / 'wait_back' for the idle row, else the view;
* `found` = True except ('attack_arrow', 'front', 0).  That one value is copied from the shipped file: it cannot be
  derived from the sheet (it probably records a first-pass miss against the DRPG atlas of the outfit) and nothing in
  the kit reads `found` or `mask` (drpg.match_unit and drpg.py's slot code read name, view, sheet, canvas, offset, pos
  and feats).

    python tools/drpg_make_ref.py --release-zip <D5ModKit release zip> --out <file>   # sheet read from the zip
    python tools/drpg_make_ref.py --sheet <Girl_Laharl_Swimsuit_SS.png> --out <file>
    python tools/drpg_make_ref.py --sheet ... --out ... --check <existing pickle>      # field-by-field compare

The sheet is game-derived art: it stays out of Git, like the pickle.  The output is written only to --out (never over
an existing file unless --force); the importer still uses only a file whose SHA-256 equals
d5lib/importers/drpg-pose-reference.json, so a rebuilt file is accepted exactly when it is byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import pickle
import sys
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

import numpy as np  # noqa: E402

from d5lib import drpg, framesheet  # noqa: E402

SHEET_MEMBER = "SpriteSheet/Girl_Laharl/Girl_Laharl_Swimsuit_SS.png"
SHEET_SHA256 = "dcccf0685b96e1fd8f36b9657f2fa7c36cad3e87d6a23d0300c0afb4e165b546"   # the upstream 1.x release sheet
NOT_FOUND = {("attack_arrow", "front", 0)}   # copied from the shipped file (see above); no consumer reads `found`
PICKLE_PROTOCOL = 4                          # the shipped file's protocol


def sheet_bytes(sheet=None, release_zip=None):
    if sheet:
        return Path(sheet).read_bytes()
    with zipfile.ZipFile(release_zip) as z:
        names = [n for n in z.namelist() if n.endswith(SHEET_MEMBER)]
        if not names:
            raise SystemExit(f"{release_zip}: no {SHEET_MEMBER}")
        return z.read(names[0])


def build(raw):
    """-> list of reference entries (the shipped pickle's shape and order) from the labelled sheet's PNG bytes"""
    im, rows = framesheet.parse_sheet(io.BytesIO(raw))
    labels = framesheet.guess_rows(im, rows)
    out = []
    for row, (name, view, text) in zip(rows, labels):
        if not name or text is None:
            raise ValueError(f"unlabelled sheet row at y={row['cells'][0][1]}: not the expected labelled sheet")
        for pos, (x0, y0, x1, y1) in enumerate(row["cells"]):
            sheet = f"wait_{view}" if name == "wait" else view    # a new string per entry, as the shipped file has
            cell = im[y0:y1, x0:x1]
            ys, xs = np.nonzero(cell[..., 3] > 0)
            if not len(ys):
                continue                       # empty overlay cell on the sheet
            rgba = cell[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            out.append(dict(name=name, view=view, sheet=sheet, canvas=(int(y1 - y0), int(x1 - x0)),
                            offset=(int(ys.min()), int(xs.min())), pos=pos, mask=rgba[..., 3] > 0,
                            feats=drpg.features(rgba), found=(name, view, pos) not in NOT_FOUND))
    return out


def compare(new, old):
    """-> list of differences (empty when every field of every entry is equal)"""
    diffs = []
    if len(new) != len(old):
        diffs.append(f"entries: {len(new)} vs {len(old)}")
    for k, (a, b) in enumerate(zip(new, old)):
        if list(a) != list(b):
            diffs.append(f"{k}: keys {list(a)} vs {list(b)}")
            continue
        for f in a:
            x, y = a[f], b[f]
            if f == "feats":
                same = len(x) == len(y) and all(p.dtype == q.dtype and np.array_equal(p, q) for p, q in zip(x, y))
            elif isinstance(x, np.ndarray):
                same = x.dtype == y.dtype and np.array_equal(x, y)
            else:
                same = x == y and type(x) is type(y)
            if not same:
                diffs.append(f"{k} {a['name']}/{a['view']}/{a['pos']}: {f} differs")
    return diffs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--sheet", help="Girl_Laharl_Swimsuit_SS.png")
    src.add_argument("--release-zip", help="a D5ModKit release zip that holds " + SHEET_MEMBER)
    ap.add_argument("--out", required=True, help="pickle to write")
    ap.add_argument("--force", action="store_true", help="overwrite --out")
    ap.add_argument("--check", help="existing pickle to compare with (pinned file: hash check only, then compared)")
    ap.add_argument("--any-sheet", action="store_true", help="accept a sheet whose SHA-256 is not the release sheet's")
    a = ap.parse_args(argv)

    raw = sheet_bytes(a.sheet, a.release_zip)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SHEET_SHA256 and not a.any_sheet:
        raise SystemExit(f"sheet SHA-256 {digest} is not the release sheet {SHEET_SHA256} (use --any-sheet to build anyway)")
    out = Path(a.out)
    if out.exists() and not a.force:
        raise SystemExit(f"{out} exists (use --force)")
    ref = build(raw)
    data = pickle.dumps(ref, protocol=PICKLE_PROTOCOL)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    pin = __import__("json").loads((KIT / "d5lib/importers/drpg-pose-reference.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256(data).hexdigest()
    print(f"{out}: {len(ref)} entries, {len(data)} bytes, SHA-256 {sha}")
    print("matches the importer pin" if sha == pin["sha256"] and len(data) == pin["size"] else
          f"does NOT match the importer pin ({pin['sha256']}, {pin['size']} bytes)")
    if a.check:
        old_raw = Path(a.check).read_bytes()
        old_sha = hashlib.sha256(old_raw).hexdigest()
        if old_sha != pin["sha256"]:
            raise SystemExit(f"--check {a.check}: SHA-256 {old_sha} is not the pinned file; not unpickling it")
        diffs = compare(ref, pickle.loads(old_raw))
        print("field compare: identical" if not diffs else "field compare: %d differences\n  " % len(diffs)
              + "\n  ".join(diffs[:40]))
        return 1 if diffs else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
