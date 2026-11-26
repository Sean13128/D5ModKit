"""WHEELMEM1: measure ANM bank size and image budget for the D1C wheel builds.

Read-only. Reports, per bank: stored (LZS) bytes, raw (decompressed) bytes, texture
count, total texel pixels/bytes, palette count, palette bytes, cell count, animation
count. Also builds the vanilla ANM_HI_JP.dat size distribution.

Usage:
  python tools/wheelmem1_measure.py banks   --out <json>
  python tools/wheelmem1_measure.py vanilla --out <json>
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path('/Volumes/Data/Projects/D5')
sys.path.insert(0, str(ROOT / 'Local/Worktrees/striderlift4'))

from d5lib import anm, lzs, nispack  # noqa: E402

GAME = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete')
REL = 'files/Anime/ANM_HI_JP.dat'

# The 19 folders / 38 changed banks (TEST28 base, then TEST29b, TEST29c).
BUILD_ROOTS = {
    'TEST28': [ROOT / 'Builds/LIFTSLOT1-20261101/mods', ROOT / 'Builds/UNIQWALK1-20261101/mods'],
    'TEST29b': [ROOT / 'Builds/TEST29FIX1-20261101/mods'],
    'TEST29c': [ROOT / 'Builds/TEST29FIX1-20261101/candidate-c/mods'],
}


def raw_of(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:4] in (b'dat\0', b'pac\0') and struct.unpack_from('<I', data, 4)[0] != len(data):
        return lzs.decompress(data)
    return data


def measure(raw: bytes) -> dict:
    a = anm.AnmFile.parse(raw)
    texel_px = sum(im.width * im.height for im in a.textures)
    texel_bytes = sum(len(im.data) for im in a.textures)
    pal_bytes = sum(len(im.data) for im in a.palettes)
    pal_entries = sum(im.width * im.height for im in a.palettes)
    cells = sum(len(b.cells) for b in a.blocks)
    anims = sum(len(b.animations) for b in a.blocks)
    keys = sum(len(b.keys) for b in a.blocks)
    fmt_mix = {}
    for im in a.textures:
        k = 'idx8' if im.indexed else 'argb32'
        fmt_mix[k] = fmt_mix.get(k, 0) + 1
    return {
        'raw_bytes': len(raw),
        'textures': len(a.textures),
        'texture_fmt': fmt_mix,
        'texel_px': texel_px,
        'texel_bytes': texel_bytes,
        'palettes': len(a.palettes),
        'palette_bytes': pal_bytes,
        'palette_entries': pal_entries,
        'cells': cells,
        'animations': anims,
        'keys': keys,
        'blocks': len(a.blocks),
    }


def bank_map(root_list):
    out = {}
    for root in root_list:
        for p in sorted(root.glob('D1C_*')):
            d = p / REL
            if not d.is_dir():
                continue
            for f in sorted(d.glob('*.lzs')):
                out.setdefault(p.name, {})[f.name] = f
    return out


def cmd_banks(args):
    builds = {}
    for build, roots in BUILD_ROOTS.items():
        m = bank_map(roots)
        builds[build] = {}
        for mod, banks in m.items():
            builds[build][mod] = {}
            for bank, path in banks.items():
                raw = raw_of(path)
                builds[build][mod][bank] = {
                    'stored_bytes': path.stat().st_size,
                    'sha256': __import__('hashlib').sha256(path.read_bytes()).hexdigest(),
                    **measure(raw),
                }
    # per-wheel-ring sum: a class = front+back pair
    doc = {'builds': builds}
    Path(args.out).write_text(json.dumps(doc, indent=1))
    print(f'wrote {args.out}')
    # console table
    mods = sorted(builds['TEST28'])
    print(f'{"mod":22s} {"bank":13s} {"stored28":>9s} {"raw28":>9s} {"raw29b":>9s} {"raw29c":>9s} '
          f'{"tx28":>4s} {"tx29b":>4s} {"tx29c":>4s} {"pal28":>5s} {"pal29b":>5s} {"pal29c":>5s}')
    for mod in mods:
        for bank in sorted(builds['TEST28'][mod]):
            row = [builds[b].get(mod, {}).get(bank, {}) for b in ('TEST28', 'TEST29b', 'TEST29c')]
            print(f'{mod:22s} {bank:13s} ' + ' '.join(f'{r.get("raw_bytes",0):9d}' for r in row) +
                  ' ' + ' '.join(f'{r.get("textures",0):4d}' for r in row) +
                  ' ' + ' '.join(f'{r.get("palettes",0):5d}' for r in row))


def cmd_vanilla(args):
    pack = GAME / 'Data/Anime/ANM_HI_JP.dat'
    rows = []
    with nispack.NisPack(pack) as pk:
        for name, entry in sorted(pk.by_name.items()):
            if not name.startswith('anm') or not name.endswith('.lzs'):
                continue
            try:
                raw = lzs.decompress(pk.read(entry))
                meas = measure(raw)
            except Exception as exc:  # noqa: BLE001
                rows.append({'member': name, 'error': str(exc)})
                continue
            rows.append({'member': name, **meas})
    ok = [r for r in rows if 'error' not in r]
    sizes = sorted(r['raw_bytes'] for r in ok)
    p99 = sizes[int(0.99 * (len(sizes) - 1))]
    doc = {
        'members': len(ok),
        'errors': len(rows) - len(ok),
        'max': max(sizes),
        'p99': p99,
        'median': sizes[len(sizes) // 2],
        'top': sorted(ok, key=lambda r: -r['raw_bytes'])[:30],
        'rows': ok,
    }
    Path(args.out).write_text(json.dumps(doc, indent=1))
    print(f'members {len(ok)} max {max(sizes):,} p99 {p99:,} median {sizes[len(sizes)//2]:,}')
    for r in doc['top'][:20]:
        print(f'{r["member"]:20s} raw {r["raw_bytes"]:9,d}  tex {r["textures"]:4d} '
              f'texelB {r["texel_bytes"]:9,d}  pal {r["palettes"]:4d}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['banks', 'vanilla'])
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    {'banks': cmd_banks, 'vanilla': cmd_vanilla}[args.mode](args)


if __name__ == '__main__':
    main()
