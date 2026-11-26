"""DD2 source-versus-built cut-in audit (DD2CUTIN1): report and gate.

The DD2 importer used to resize the source cut-in page (128x544, the drawn cell is 125x544) over the whole D5 cut-in
texture (336x1080), a non-uniform scale of x 2.62-2.69, y 1.99 (the strip's aspect 0.230 became 0.311), and gave every
class rank rank 0's strip.  For every cut-in bank of a built pack this audit measures, from the pack's own file:

  * the texture is the D5 cut-in texture and the picture drawn in it has ONE scale on both axes (within 1%),
  * no source pixel is lost: the scaled picture lies wholly inside the texture,
  * the picture equals the source cut-in resized by that scale (mean absolute difference over the four channels),
  * every texture pixel outside the picture is fully transparent,
  * for a class, rank k's bank holds rank k's strip, not another rank's.

The position is searched, not assumed (any horizontal/vertical offset passes), so a different anchoring choice later
does not need this audit changed.  A picture whose aspect is within 2% of the texture's fills it (D4's 390x1248 cell).

    python tools/dd2_cutin_audit.py --mods DIR [--source-root DIR] [--packs A,B] [--json OUT] [--gate]

The importer runs `audit_pack` as the gate `cutin_fit` on every DD2 pack built with `dd2_cutin_fit` on.  Limits: the
source images come from the same cell reader the importer uses (the independent check against the Goal 1 reader is
Tools/source_readers/dd2/compare.py); nothing shows how the game draws a strip narrower than its texture.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

TEXTURE = (336, 1080)
SCALE_TOLERANCE = 0.01
ASPECT_FILL = 0.02
MAX_MEAN_DIFF = 2.0         # of 255, over RGBA (same resampler on both sides measures 0.0; a stretch measures > 20)
MAX_BAD_SHARE = 0.01        # share of pixels more than 16 away


def pack_banks(pack):
    """[(bank number, RGBA texture image)] of the cut-in banks (anm1xxxx, 336x1080 first texture), by bank number."""
    from d5lib import anm, gamefs
    out = []
    folder = Path(pack) / "files/Anime/ANM_HI_JP.dat"
    for path in sorted(folder.glob("anm1????.lzs")):
        if not re.fullmatch(r"anm1\d{4}\.lzs", path.name):
            continue
        bank = anm.parse(gamefs.decode_member(path.read_bytes()))
        if not bank.textures or (bank.textures[0].width, bank.textures[0].height) != TEXTURE:
            continue
        out.append((int(path.name[3:8]), anm.texture_to_image(bank, 0, 0).convert("RGBA")))
    return out


def place_of(texture, src_size):
    """Locate the source picture in a cut-in texture from the texture alone -> (x, y, w, h) of the picture's box.
    Scale = the largest one-scale fit (min over axes) unless the aspects match (fill)."""
    tw, th = texture.size
    sw, sh = src_size
    if abs((sw / sh) / (tw / th) - 1.0) <= ASPECT_FILL:
        return (0, 0, tw, th)
    s = min(tw / sw, th / sh)
    return (None, None, min(tw, round(sw * s)), min(th, round(sh * s)))


def measure(texture, src):
    """One cut-in -> dict(scale_x, scale_y, box, mean_diff, bad_share, outside_opaque, uniform, lossless, ok).
    The texture is an RGBA image, src the source cut-in (RGBA)."""
    tex = np.asarray(texture.convert("RGBA")).astype(np.int16)
    tw, th = texture.size
    sw, sh = src.size
    x0, y0, w, h = place_of(texture, src.size)
    resized = np.asarray(src.convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)).astype(np.int16)
    best = None
    xs = [x0] if x0 is not None else range(tw - w + 1)
    ys = [y0] if y0 is not None else range(th - h + 1)
    for y in ys:
        for x in xs:
            d = np.abs(tex[y:y + h, x:x + w] - resized)
            score = float(d.mean())
            if best is None or score < best[0]:
                best = (score, x, y, d)
    mean, x, y, d = best
    outside = np.ones(tex.shape[:2], bool)
    outside[y:y + h, x:x + w] = False
    outside_opaque = int((tex[..., 3][outside] != 0).sum())
    sx, sy = w / sw, h / sh
    res = dict(scale_x=round(sx, 4), scale_y=round(sy, 4), box=[x, y, w, h], mean_diff=round(mean, 3),
               bad_share=round(float((d.max(axis=2) > 16).mean()), 4), outside_opaque=outside_opaque,
               uniform=abs(sx - sy) / max(sx, sy) <= SCALE_TOLERANCE, lossless=(w <= tw and h <= th))
    res["ok"] = bool(res["uniform"] and res["lossless"] and mean <= MAX_MEAN_DIFF
                     and res["bad_share"] <= MAX_BAD_SHARE and outside_opaque == 0)
    return res


def audit_pack(pack, sources):
    """One built pack and its source cut-ins (ordered like the importer's: one for a unique, six rank strips for a class)
    -> dict(pack, banks=[...], failed=[...]).  A class's banks beyond the sixth repeat rank 0's strip (the importer fills
    the family's ten colour slots that way)."""
    pack = Path(pack)
    banks = pack_banks(pack)
    out = dict(pack=pack.name, banks=[], failed=[])
    if not banks:
        out["failed"].append("no cut-in bank in the pack")
        return out
    for index, (number, texture) in enumerate(banks):
        src = sources[index] if index < len(sources) else sources[0]
        m = measure(texture, src)
        m.update(bank=number, source_index=index if index < len(sources) else 0, source_size=list(src.size))
        out["banks"].append(m)
        if not m["ok"]:
            out["failed"].append(f"anm{number}: " + ", ".join(
                k for k, ok in (("non-uniform scale", m["uniform"]), ("source pixels lost", m["lossless"]),
                                (f"differs from the resized source (mean {m['mean_diff']})", m["mean_diff"] <= MAX_MEAN_DIFF and m["bad_share"] <= MAX_BAD_SHARE),
                                (f"{m['outside_opaque']} opaque px outside the best one-scale placement (stretched, cropped, or another picture)", m["outside_opaque"] == 0)) if not ok))
    return out


def source_images(meta, data=None):
    """The source cut-ins of a built pack, read from the Disgaea D2 archives (ANM_HI anm10000+id+rank, drawn cell)."""
    sys.path.insert(0, str(_forge_root()))
    import numpy.testing  # noqa: F401
    from d5lib.importers import _dd2_baseline as base, _dd2_prepare as prep
    import tempfile
    data = data or base.source_data(None)
    ranks = meta["source_import"]["source_ranks"]
    sid = int(ranks[0]["id"])
    images = []
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(6 if len(ranks) == 6 else 1):
            try:
                path = base._cutin(data, prep, 10000 + sid + k, Path(tmp) / f"c{k}.png", cell=True)
            except ValueError:
                if k == 0:
                    raise
                images.append(images[0])
                continue
            with Image.open(path) as im:
                images.append(im.convert("RGBA").copy())
    return images


def _forge_root():
    from d5lib.importers import _dd2_source as src
    return src.forge_root()


def run(mods, packs=None):
    mods = Path(mods)
    names = packs or sorted(p.name for p in mods.iterdir() if p.name.startswith("DD2_") and (p / "mod.json").is_file())
    results = []
    for name in names:
        meta = json.loads((mods / name / "mod.json").read_text())
        results.append(audit_pack(mods / name, source_images(meta)))
    return dict(schema="dd2-cutin-audit/1", mods=str(mods), banks=sum(len(r["banks"]) for r in results),
                failed_packs=[r["pack"] for r in results if r["failed"]], packs=results)


def render(report):
    lines = [f"DD2 cut-in audit: {len(report['packs'])} packs, {report['banks']} banks, {len(report['failed_packs'])} packs failing"]
    for r in report["packs"]:
        worst = max((b["mean_diff"] for b in r["banks"]), default=0)
        scale = sorted({(b["scale_x"], b["scale_y"]) for b in r["banks"]})
        lines.append(f"  {'FAIL' if r['failed'] else 'PASS'} {r['pack']:<18} banks {len(r['banks']):>2}  scale {scale[0] if scale else '-'}  "
                     f"worst mean diff {worst:.2f}" + ("  " + "; ".join(r["failed"][:3]) if r["failed"] else ""))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mods", type=Path, required=True)
    ap.add_argument("--packs", help="comma-separated pack folders (default: every DD2_* pack in --mods)")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--gate", action="store_true", help="exit 1 when a cut-in is stretched, loses pixels or differs")
    args = ap.parse_args(argv)
    report = run(args.mods, [p for p in (args.packs or "").split(",") if p] or None)
    print(render(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    return 1 if args.gate and report["failed_packs"] else 0
