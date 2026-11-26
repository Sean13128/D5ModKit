"""WHEELMEM1: PAD28 — TEST28 padded to TEST29c's raw size with unreachable images.

One variable: bank size.  Each of the 38 TEST28 banks gets extra indexed textures appended
(nothing references them: no cell, key or animation is added or changed) until the
decompressed file is exactly the same number of bytes as TEST29c's member.  Rendering must be
byte-identical to TEST28 at every id x key time x 6 palettes, and the structural gate must show
no new problem.

usage: python tools/wheelmem1_pad.py <out bundle dir>
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
CAND = ROOT / 'Builds/TEST29FIX1-20261101/candidate-c/mods'
EV = ROOT / 'Builds/WHEELMEM1-20261102/evidence'
PY = sys.executable


def image_data_len(a):
    """Bytes occupied by the image data region (offsets are relative to it)."""
    body = len(b''.join(b.to_bytes() for b in a.blocks))
    nim = len(a.textures) + len(a.palettes)
    return len(a.to_bytes()) - (0x20 + body + nim * 0x10)


def factor(n):
    """A (w, h) pair with w*h == n and both <= 0xffff, preferring wide textures."""
    if n <= 0:
        raise ValueError(n)
    d = max(1, -(-n // 0xffff))
    while d <= 0xffff:
        if n % d == 0 and n // d <= 0xffff:
            return (n // d, d)
        d += 1
    raise ValueError(f'no factor pair for {n}')


def _add(a, s):
    w, h = factor(s)
    anm.add_texture(a, w, h, indexed=True)
    a.textures[-1].data = bytes(w * h)
    return (w, h)


def _drop_last(a):
    a.textures.pop()
    a.block.texture_infos.pop()


def pad_to(a, target):
    """Append unreachable indexed textures until len(to_bytes()) == target exactly.

    Each added image costs a 16-byte header plus its data, and the layout pads every image
    offset to 128 bytes; adding one TextureInfo also grows the block in lumps of 16 as the
    12-byte table entry fills its padding.  The cost of the last image is linear in its
    pixel count at a fixed image count, so probe once and solve.
    """
    for n in range(1, 10):
        added = []
        for _ in range(n - 1):
            added.append(_add(a, 1))
        cur = len(a.to_bytes())
        if cur >= target:
            for _ in added:
                _drop_last(a)
            continue
        # cost of one more image of s pixels = 16 + 128*ceil(s/128) + block growth g,
        # so probe a 1-pixel image to learn g and then pick a factorable size.
        _add(a, 1)
        cost1 = len(a.to_bytes()) - cur
        _drop_last(a)
        g = cost1 - 145
        want = target - cur
        for attempt in range(4):
            aligned = want - 16 - g
            if aligned < 1:
                break
            aligned -= aligned % 128
            for k in range(128):
                s = aligned - k
                if s < 1:
                    continue
                try:
                    wh = factor(s)
                except ValueError:
                    continue
                _add(a, s)
                got = len(a.to_bytes())
                if got == target:
                    added.append(wh)
                    return added
                _drop_last(a)
                want -= got - target
                break
            else:
                break
        for _ in added:
            _drop_last(a)
    raise ValueError(f'padding did not converge ({len(a.to_bytes())} vs {target})')


def main():
    out = Path(sys.argv[1])
    n = base.require_base_set()
    print(f'TEST28 base asserted: {n} pinned banks', flush=True)
    rows = []
    for mod, banks in base.manifest()['banks'].items():
        dest = out / 'mods' / mod
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(base.base_dir(mod) / mod, dest)
        for bank in banks:
            src = base.bank_path(mod, bank)
            a = anm.load(src)
            c_raw = len((CAND / mod / base.REL / bank).read_bytes())
            c_size = len(anm.load(CAND / mod / base.REL / bank).to_bytes())
            added = pad_to(a, c_size)
            raw = a.to_bytes()
            dst = dest / base.REL / bank
            dst.write_bytes(anm.lzs_compress(raw))
            rows.append({'mod': mod, 'bank': bank, 'test28_raw': len(anm.load(src).to_bytes()),
                         'pad_raw': len(raw), 'test29c_raw': c_size,
                         'added_textures': added,
                         'added_texels': sum(w * h for w, h in added)})
            print(f'  {mod}/{bank}: {rows[-1]["test28_raw"]:,} -> {len(raw):,} '
                  f'(c {c_size:,}) +{len(added)} textures', flush=True)
    EV.mkdir(parents=True, exist_ok=True)
    (EV / 'pad-manifest.json').write_text(json.dumps(rows, indent=1))
    print('wrote', out)


if __name__ == '__main__':
    main()
