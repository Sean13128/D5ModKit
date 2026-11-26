#!/usr/bin/env python3
"""S2 table: the stand picture's ground line, shipped vs rebuilt, against each pack's own donor template.

    python tools/regen_stand_ground.py --before <mods> --after <mods> --out <playtest>/regen-renders

For every D4 class pack that ships a sprite it renders animation 1 (the picture the creation/class-change
wheel draws) and reports the silhouette's bottom y in sprite coordinates (0 = the tile the game stands the
unit on), compares it with the donor template's own stand picture, and states the delta.  PTSPRITE measured
28 of 45 packs off by more than 2 px before the fix.  Nothing is launched; the donor sprites are read out of
the game folder read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

KIT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, KIT)

from d5lib import anm, sprites       # noqa: E402
from d5lib.gamefs import GameFS      # noqa: E402

GAME = '/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete'
BOUNDS = (-320, -440, 320, 140)


def load(path):
    with open(path, 'rb') as fh:
        return anm.load(fh.read())


def view_of(fs, a):
    if sprites.needs_motion_set(a):
        a = anm.bind_motion_set(anm.AnmFile([sprites.motion_block(fs, 1)], [], []), 0, a)
    return a


def stand_bottom(a, aid=1):
    ids = [x['id'] for x in anm.list_animations(a)]
    if aid not in ids:
        return None
    items = anm.evaluate(a, ('id', aid), 0)
    img, _ = anm.render_items(a, items, 0, bounds=BOUNDS)
    m = np.asarray(img)[..., 3] >= 128
    if not m.any():
        return None
    return int(np.nonzero(m)[0].max()) + BOUNDS[1]


def meta(mod_dir):
    cdir = os.path.join(mod_dir, 'patches', 'classes')
    for name in sorted(os.listdir(cdir)):
        if name.startswith('class_') and name.endswith('.json'):
            data = json.loads(open(os.path.join(cdir, name)).read())
            return int(data['sprite_family']), int(data['template'])
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--before', required=True)
    ap.add_argument('--after', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    fs = GameFS(GAME)
    donor_cache = {}
    lines = ['# S2 ground line of the stand picture (animation 1), in sprite px, 0 = the tile',
             '# donor_stand = the donor animation 1 as the game draws it (shared motion set bound).',
             '# donor_idle  = the donor wheel idle 6001 (the animation the Recruiter/class wheel plays).',
             '# "d_stand"/"d_idle" = pack minus that donor value.  A fix moves the pack onto the reference',
             '# PTSPRITE chose: the donor stand picture when it has one, else its wheel idle.',
             f'{"mod":22} {"d_stand":>8} {"d_idle":>7} {"before":>7} {"after":>6} {"d_stand b→a":>13} {"d_idle a":>9}']
    rows, off_before, off_after = [], 0, 0
    for mod in sorted(p.name for p in Path(args.after).iterdir() if p.is_dir()):
        if not mod.startswith('D4_Class_'):
            continue
        fam, tpl = meta(str(Path(args.after) / mod))
        if fam is None:
            continue
        bank = f'anm{fam:05d}.lzs'
        pb = Path(args.before) / mod / 'files/Anime/ANM_HI_JP.dat' / bank
        pa = Path(args.after) / mod / 'files/Anime/ANM_HI_JP.dat' / bank
        if not pa.exists():
            continue
        if tpl not in donor_cache:
            raw = anm.parse(fs.read(sprites.sprite_vpath(fs, tpl, 'EN')))
            donor_cache[tpl] = (view_of(fs, raw), raw)
        bound, raw = donor_cache[tpl]
        d = stand_bottom(bound)
        di = stand_bottom(raw, 6001)
        b = stand_bottom(load(pb)) if pb.exists() else None
        a = stand_bottom(load(pa))
        db = None if (b is None or d is None) else b - d
        da = None if (a is None or d is None) else a - d
        if db is not None and abs(db) > 2:
            off_before += 1
        if da is not None and abs(da) > 2:
            off_after += 1
        fmt = lambda v: 'n/a' if v is None else str(v)
        da_idle = None if (a is None or di is None) else a - di
        lines.append(f'{mod:22} {fmt(d):>8} {fmt(di):>7} {fmt(b):>7} {fmt(a):>6} '
                     f'{fmt(db)}→{fmt(da)}'.rjust(14) + f' {fmt(da_idle):>9}')
        rows.append(dict(mod=mod, donor_stand=d, donor_idle=di, before=b, after=a,
                         delta_before=db, delta_after=da, delta_after_idle=da_idle))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'STAND-GROUND.txt').write_text('\n'.join(lines) + '\n')
    (out / 'stand-ground.json').write_text(json.dumps(rows, indent=1))
    print('\n'.join(lines))
    print(f'\npacks off by more than 2 px: before {off_before}, after {off_after} (of {len(rows)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
