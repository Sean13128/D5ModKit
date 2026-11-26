"""ANIMALL2 gates: art-only diff, donor-id coverage, no wheel stub, blank attachments, tick-0 sheets.

Every check is offline and reads only --base / --stage / --out.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from d5lib import anm, ownanim

BOUNDS = (-240, -360, 240, 120)
PATH = Path('files/Anime/ANM_HI_JP.dat')


def shapes(block, aid):
    a = next((x for x in block.animations if x.id == aid), None)
    if a is None:
        return None
    info = anm.animation_info(block, a)
    nested, drawings, nkeys = [], 0, 0
    for ni, _, _ in block.walk(a.root):
        for k in block.node_keys(block.nodes[ni]):
            nkeys += 1
            if k.flags & 0xFF00 == anm.NESTED and 0 <= k.param < len(block.params):
                nested.append((k.time, block.params[k.param]))
            elif k.cell and 0 < k.cell < len(block.cells):
                c = block.cells[k.cell]
                if c.w or c.h:
                    drawings += 1
    return dict(length=info.get('length'), nkeys=nkeys, drawings=drawings, nested=nested)


def bank_of(folder, n):
    p = folder / PATH / f'anm{n:05d}.lzs'
    return anm.load(p).blocks[0] if p.exists() else None


def sheet(anim_file, out_png, cols=12, cell=64):
    """Every animation of one bank at tick 0, one cell each, id printed above the cell."""
    block = anim_file.blocks[0]
    ids = [a.id for a in block.animations]
    rows = (len(ids) + cols - 1) // cols
    img = Image.new('RGBA', (cols * cell, rows * (cell + 10)), (22, 22, 28, 255))
    d = ImageDraw.Draw(img)
    errors = []
    for i, aid in enumerate(ids):
        x, y = (i % cols) * cell, (i // cols) * (cell + 10)
        d.text((x + 1, y), str(aid), fill=(255, 240, 170, 255))
        try:
            frame = np.asarray(anm.render_items(
                anim_file, anm.evaluate(anim_file, ('id', aid), 0, nested=True), 0, bounds=BOUNDS)[0])
            im = Image.fromarray(frame).convert('RGBA')
            scale = min(cell / im.width, cell / im.height)
            if 0 < scale < 1:
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
            img.alpha_composite(im, (x, y + 10))
        except Exception as exc:  # noqa: BLE001 - a renderer error is a receipt, not a crash
            errors.append(dict(animation=aid, error=f'{type(exc).__name__}: {exc}'))
    img.save(out_png)
    return dict(motions=len(ids), errors=errors, sheet=str(out_png))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--fallback', default='')
    ap.add_argument('--stage', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sheets', default='')
    args = ap.parse_args()
    base, stage, out = Path(args.base), Path(args.stage), Path(args.out)
    fallback = Path(args.fallback) if args.fallback else None
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    fails = 0
    for folder in sorted(stage.iterdir()):
        if not folder.is_dir():
            continue
        name = folder.name
        rec = dict()
        b = base / name
        if not b.exists() and fallback is not None:
            b = fallback / name
        # art-only diff
        changed = sorted(str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()
                         and (not (b / p.relative_to(folder)).exists()
                              or p.read_bytes() != (b / p.relative_to(folder)).read_bytes()))
        removed = sorted(str(p.relative_to(b)) for p in b.rglob('*') if p.is_file()
                         and not (folder / p.relative_to(b)).exists()) if b.exists() else []
        rec['changed'] = changed
        rec['removed'] = removed
        if not changed and not removed:
            rec['unchanged'] = True
            rec['ok'] = True
            report[name] = rec
            continue
        ok = len(changed) == 2 and not removed and all(c.startswith(str(PATH)) for c in changed)
        n = int(Path(changed[0]).stem[3:]) if ok else None
        rec['bank'] = n
        if not ok:
            rec['fail'] = 'diff'
            fails += 1
            report[name] = rec
            continue
        old0, new0 = bank_of(b, n), bank_of(folder, n)
        old1, new1 = bank_of(b, n + 1), bank_of(folder, n + 1)
        rec['id_ok'] = bool(new0 and new1 and new0.id == n and new1.id == n + 1)
        have = {a.id for a in new0.animations}
        rec['missing_ids'] = sorted({a.id for a in old0.animations} - have)
        # wheel stub
        rec['wheel'] = {str(a): shapes(new0, a) for a in (1001, 1007) if shapes(new0, a)}
        rec['wheel_stub'] = [a for a in (1001, 1007)
                             if shapes(new0, a) and shapes(new0, a)['nkeys'] <= 2
                             and not shapes(new0, a)['drawings']
                             and any(t in (6001, 6007) for _, t in shapes(new0, a)['nested'])]
        # attachments: a donor attachment may keep D4's own part art, but a PICTURED motion that pulls
        # one in must not draw the whole figure twice -- i.e. the attachment must not draw a cell the
        # stand/idle motion already draws (SPRITE3).  A stub (a 0x100-only pose) is exempt: it exists to
        # show the attached animation instead of itself.
        stand_cells = set()
        stand_area = 0
        for sid in (1, 7, 6001, 6007, 1001, 1007):
            a = next((x for x in new0.animations if x.id == sid), None)
            if a is None:
                continue
            for ni, _, _ in new0.walk(a.root):
                for k in new0.node_keys(new0.nodes[ni]):
                    if k.cell and 0 < k.cell < len(new0.cells):
                        c = new0.cells[k.cell]
                        stand_cells.add((c.tex, c.x, c.y, c.w, c.h))
                        stand_area = max(stand_area, c.w * c.h)
        att, painted = set(), []
        for a in new0.animations:
            sh = shapes(new0, a.id)
            targets = [t for _, t in sh['nested'] if 1500 <= t < 2000] if sh else []
            if not targets or not sh['drawings']:
                continue                       # not an attachment, or a stub that only shows it
            for t in targets:
                att.add(t)
                ta = next((x for x in new0.animations if x.id == t), None)
                if ta is None:
                    continue
                dup = []
                for ni, _, _ in new0.walk(ta.root):
                    for k in new0.node_keys(new0.nodes[ni]):
                        if k.cell and 0 < k.cell < len(new0.cells):
                            c = new0.cells[k.cell]
                            if ((c.tex, c.x, c.y, c.w, c.h) in stand_cells
                                    and c.w * c.h >= 0.5 * stand_area):
                                dup.append(k.cell)
                if dup:
                    painted.append(dict(animation=a.id, attaches=t, whole_pose_cells=sorted(set(dup))))
        rec['attachments'] = sorted(att)
        rec['painted_attachments'] = painted
        rec['motions'] = len(have)
        rec['ok'] = (rec['id_ok'] and not rec['missing_ids'] and not rec['wheel_stub']
                     and not painted)
        if not rec['ok']:
            fails += 1
        report[name] = rec
    if args.sheets:
        sdir = out / 'sheets'
        sdir.mkdir(exist_ok=True)
        sheets = {}
        for name, rec in report.items():
            n = rec.get('bank')
            if not n:
                continue
            for off in (0, 1):
                f = folder = stage / name / PATH / f'anm{n + off:05d}.lzs'
                if not f.exists():
                    continue
                sheets[f'{name}:{n + off}'] = sheet(anm.load(f), sdir / f'{name}-{n + off}.png')
        (out / 'sheets.json').write_text(json.dumps(sheets, indent=1))
        print(f'{len(sheets)} tick-0 sheets, '
              f'{sum(len(s["errors"]) for s in sheets.values())} renderer errors')
    (out / 'gates.json').write_text(json.dumps(report, indent=1))
    bad = {k: v for k, v in report.items() if not v.get('ok')}
    print(f'{len(report)} folders, {fails} failing')
    for k, v in bad.items():
        print('FAIL', k, {x: v.get(x) for x in ('fail', 'id_ok', 'missing_ids', 'wheel_stub',
                                                'painted_attachments')})
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
