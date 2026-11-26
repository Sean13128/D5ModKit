#!/usr/bin/env python3
"""Source-versus-built face audit for Disgaea 4 packs (D4FACE1, 2026-11-25).  No game, read-only.

    python tools/d4_face_audit.py MODS_DIR [--only D4_Class_1240,...] [--gate] [--source-root GAME_DIR] [--out FILE]

For every D4 pack in MODS_DIR (``mod.json`` ``source_import``) and every character row it holds, compares the face
picture in the pack with the face the GAME draws for that row (rule D4-FACE-02, ``d4screenart.game_face_number``:
the char.dat colour id rounded down to tens for class, rank and NPC rows, the colour id itself for ids below 1000)
decoded from the original ``WF.dat`` (``swf<N>.nltx``).  The pack face is resized to the source face (the
importer resizes D4's 256x256 face to the D5 size and matte-flattens it), then compared as the mean absolute RGB
difference over the pixels either side draws, as the Goal 1 compare does:

  equal      mean difference < --tolerance (4.0): the same picture (a resize / matte / compression difference)
  fallback   (class packs) the rank slot has no file of its own and the kit gives the slot the colour-0 face
             (``outfits._finalize_classes``: ``own.get(j, img)``); judged on that face
  differs    the pack face looks like another source face (the nearest face is named) or like none
  missing    no face file for the row at all

A class pack has a file per colour slot ``patches/classes/face_<family>[_k].png`` (slot k = rank row k); a unique has
``patches/characters/face_<key>.png``.  ``--gate`` exits 1 when any row is ``differs`` or ``missing``; the rule is
enforced on EVERY D4 pack.  Limit: it judges the picture on disk, not how the game places or crops it, and it
cannot tell a face that is wrong but within the tolerance of the right one (swf1084 vs swf1080 differ by 3.7).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

from d5lib import d4screenart, d4source  # noqa: E402

SOURCE_ROOT = Path('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+')
TOLERANCE = 4.0


def mean_diff(a, b):
    """Mean absolute RGB difference over the pixels either image draws, `b` resized to `a`."""
    from PIL import Image
    a = a.convert('RGBA')
    b = b.convert('RGBA').resize(a.size, Image.BILINEAR)
    x, y = np.asarray(a).astype(float), np.asarray(b).astype(float)
    m = (x[..., 3] > 16) | (y[..., 3] > 16)
    if not m.any():
        return 0.0
    return float(np.abs(x[..., :3] - y[..., :3])[m].mean())


class Source:
    def __init__(self, root=SOURCE_ROOT):
        root = Path(root)
        self.data = d4source.D4Data(root, locate=lambda rel: root / rel)
        wf, _ = d4screenart.archive_paths(root)
        self.wf = d4source.Nsac(wf)
        self._faces = {}

    def face(self, n):
        if n not in self._faces:
            member = f'swf{int(n):04d}.nltx'
            try:
                self._faces[n] = d4screenart.decode_face(self.wf.read(member))
            except (KeyError, ValueError, OSError):
                self._faces[n] = None
        return self._faces[n]

    def row(self, sid):
        return self.data.chars[int(sid)]


def pack_rows(pack):
    """[(row id, [pack face file candidates in order])] for one pack folder, or None when it is not a D4 pack."""
    meta = json.loads((pack / 'mod.json').read_text(encoding='utf-8')).get('source_import') or {}
    classes = sorted((pack / 'patches' / 'classes').glob('class_*.json'))
    if classes and meta.get('source_ranks'):
        spec = json.loads(classes[0].read_text(encoding='utf-8'))
        fam = int(spec['family'])
        base = pack / 'patches' / 'classes'
        out = []
        for k, r in enumerate(meta['source_ranks']):
            own = base / (f'face_{fam}.png' if k == 0 else f'face_{fam}_{k}.png')
            out.append((int(r['id']), own, base / f'face_{fam}.png'))
        return out
    if meta.get('source_game') == 'd4' and meta.get('source_id') is not None:
        faces = sorted((pack / 'patches' / 'characters').glob('face_*.png'))
        return [(int(meta['source_id']), faces[0] if faces else None, None)]
    return None


def audit_pack(src, pack):
    from PIL import Image
    rows = []
    spec = pack_rows(pack)
    if spec is None:
        return None
    for sid, own, fallback in spec:
        ch = src.row(sid)
        number = d4screenart.game_face_number(sid, ch['color_id'])
        want = src.face(number)
        used, status = own, None
        if own is None or not own.is_file():
            if fallback is not None and fallback.is_file():
                used, status = fallback, 'fallback'
            else:
                rows.append(dict(row=sid, face_number=number, status='missing', detail='no face file for the row'))
                continue
        if want is None:
            rows.append(dict(row=sid, face_number=number, status='differs', detail=f'source has no swf{number:04d}'))
            continue
        with Image.open(used) as im:
            d = mean_diff(im, want)
            if d < TOLERANCE:
                rows.append(dict(row=sid, face_number=number, status=status or 'equal', diff=round(d, 2), file=used.name))
                continue
            best = None
            for n in sorted({int(src.row(r)['color_id']) for r, _, _ in spec} | {number}):
                other = src.face(n)
                if other is not None:
                    dd = mean_diff(im, other)
                    if best is None or dd < best[0]:
                        best = (dd, n)
        near = f'; nearest swf{best[1]:04d} ({best[0]:.2f})' if best and best[0] < TOLERANCE else ''
        rows.append(dict(row=sid, face_number=number, status='differs', diff=round(d, 2), file=used.name,
                         detail=f'mean difference {d:.2f} to the face the game draws, swf{number:04d}{near}'))
    return rows


def gate(rows):
    """[reasons] a pack fails the face gate (empty = pass)."""
    return [f"row {r['row']}: {r['status']} ({r['detail']})" for r in rows if r['status'] in ('differs', 'missing')]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('mods', type=Path)
    ap.add_argument('--only', help='comma list of pack folders')
    ap.add_argument('--gate', action='store_true')
    ap.add_argument('--source-root', type=Path, default=SOURCE_ROOT)
    ap.add_argument('--out', type=Path, help='write the rows as JSON')
    args = ap.parse_args(argv)
    src = Source(args.source_root)
    only = set(args.only.split(',')) if args.only else None
    result, failed = {}, []
    for pack in sorted(args.mods.glob('D4_*')):
        if only and pack.name not in only:
            continue
        try:
            rows = audit_pack(src, pack)
        except Exception as exc:                                    # noqa: BLE001  an unreadable pack fails, never skipped
            rows = [dict(row=None, face_number=None, status='missing', detail=f'{type(exc).__name__}: {exc}')]
        if rows is None:
            continue
        result[pack.name] = rows
        count = {}
        for r in rows:
            count[r['status']] = count.get(r['status'], 0) + 1
        bad = gate(rows)
        if bad:
            failed.append(pack.name)
        print(f"{pack.name}: {', '.join(f'{k} {v}' for k, v in sorted(count.items()))}{'  FAIL' if bad else ''}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1) + '\n')
    print(f"{len(result)} packs, {len(failed)} fail the face gate")
    return 1 if args.gate and failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
