"""Apply PT1030ANIM's converter rules to sprite banks already on disk (art only).

  --wheel   restore motion 1001/1007 to the native zero-length attachment stub (d5lib.ownanim
            .wheel_stub_shape / normalize_wheel_motion), laid out the way the game reads it (control root,
            drawing at root+1: ownanim.fix_render_roots, BACKVIEW1)
  --order   paint a composed figure's biggest part first (d5lib.ownanim.order_part_layers)

Only files whose bytes change are written, so `diff -rq` against the base names the change.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5lib import anm, ownanim


def fix_bank(raw, wheel=True, order=True, pack_name='', order_prefix='D4_', min_items=3):
    a = anm.load(raw)
    log = []
    for block in a.blocks:
        if wheel:
            for aid, idle in ((1001, 6001), (1007, 6007)):
                hit = ownanim.normalize_wheel_motion(block, aid, idle)
                if hit:
                    log.append(dict(action='wheel-normalized', **hit))
            fixed = ownanim.fix_render_roots(block)       # BACKVIEW1: the game draws node root+1 only
            if fixed:
                log.append(dict(action='render-root', animations=fixed))
        if order and pack_name.startswith(order_prefix):
            groups = ownanim.order_part_layers(block, min_items=min_items)
            if groups:
                log.append(dict(action='part-order', groups=groups))
    return anm.parse(a.to_bytes()), log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--packs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--wheel', action='store_true')
    ap.add_argument('--order', action='store_true')
    ap.add_argument('--order-prefix', default='D4_')
    ap.add_argument('--min-items', type=int, default=3)
    ap.add_argument('--only', action='append', default=[])
    ap.add_argument('--report', default=None)
    args = ap.parse_args()
    if not (args.wheel or args.order):
        raise SystemExit('choose --wheel and/or --order')
    root, out = Path(args.packs), Path(args.out)
    report = {}
    for pack in sorted(p for p in root.iterdir() if p.is_dir()):
        if args.only and pack.name not in args.only:
            continue
        d = pack / 'files/Anime/ANM_HI_JP.dat'
        if not d.is_dir():
            continue
        for f in sorted(d.glob('anm0*.lzs')):
            raw = f.read_bytes()
            fixed, log = fix_bank(raw, args.wheel, args.order, pack.name,
                                  args.order_prefix, args.min_items)
            if not log:
                continue
            new = fixed.to_bytes()
            if new == raw:
                continue
            rel = f.relative_to(pack)
            dest = out / pack.name / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(new)
            report.setdefault(pack.name, []).append(dict(file=rel.as_posix(), log=log))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    print('packs changed:', len(report), 'files:', sum(len(v) for v in report.values()))


if __name__ == '__main__':
    main()
