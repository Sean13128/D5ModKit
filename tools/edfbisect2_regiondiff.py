"""EDFBISECT2 step 1: enumerate every byte difference between TEST28 and BS-DARK class banks,
grouped by region (file header, block header, tables 0-9, image headers, texture pixels, palettes,
padding).

Usage: python tools/edfbisect2_regiondiff.py [out.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
DARK = ROOT / 'Builds/WHEELBISECT1-20261102/bs_dark/mods'
TABLES = ['animations', 'nodes', 'keys', 'palette_infos', 'texture_infos', 'cells',
          'transforms', 'pivots', 'colors', 'params']
BLOCK_HEADER = 0x44


def rec(r):
    """JSON-able record."""
    if hasattr(r, 'rgba'):
        return {'rgba': list(r.rgba)}
    if hasattr(r, '__dataclass_fields__'):
        return {f: getattr(r, f) for f in r.__dataclass_fields__}
    return r


def diff_table(a, b, name):
    """index-wise comparison of one table between two blocks."""
    la, lb = a, b
    n = min(len(la), len(lb))
    changed = [i for i in range(n) if la[i] != lb[i]]
    out = {'count_test28': len(la), 'count_dark': len(lb),
           'appended': len(lb) - len(la) if len(lb) >= len(la) else 0,
           'removed': len(la) - len(lb) if len(la) > len(lb) else 0,
           'changed_in_common_prefix': len(changed),
           'changed_indices_head': changed[:12]}
    if changed:
        i = changed[0]
        out['first_change'] = {'index': i, 'test28': rec(la[i]), 'dark': rec(lb[i])}
        diffs = []
        for i in changed[:40]:
            x, y = rec(la[i]), rec(lb[i])
            fields = {k: [x[k], y[k]] for k in x if x[k] != y[k]} if isinstance(x, dict) else x
            diffs.append({'index': i, 'fields': fields})
        out['field_diffs'] = diffs
    return out


def bbox_of_diff(a: bytes, b: bytes, w: int, h: int):
    """count + bounding box of differing pixels of one 8-bit texture."""
    assert len(a) == len(b) == w * h
    n = 0
    x0, y0, x1, y1 = w, h, -1, -1
    for i in range(len(a)):
        if a[i] != b[i]:
            n += 1
            y, x = divmod(i, w)
            x0, x1 = min(x0, x), max(x1, x)
            y0, y1 = min(y0, y), max(y1, y)
    if not n:
        return {'changed_pixels': 0}
    return {'changed_pixels': n, 'bbox': [x0, y0, x1, y1]}


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/Volumes/Data/ai-tmp/codex/edfbisect2/regions.json')
    result = {}
    for mod, bank in (('D1C_Class_11400', 'anm01530.lzs'), ('D1C_Class_11390', 'anm01540.lzs')):
        t28_file = base.base_dir(mod) / mod / base.REL / bank
        dark_file = DARK / mod / base.REL / bank
        t28 = anm.load(t28_file.read_bytes())
        dk = anm.load(dark_file.read_bytes())
        tb, db = t28.block, dk.block
        row = {
            'bank': bank, 'mod': mod,
            'test28_sha': __import__('hashlib').sha256(t28_file.read_bytes()).hexdigest(),
            'raw_test28': len(t28.to_bytes()), 'raw_dark': len(dk.to_bytes()),
            'file_header': {'nblock': [len(t28.blocks), len(dk.blocks)],
                            'ntex': [len(t28.textures), len(dk.textures)],
                            'npal': [len(t28.palettes), len(dk.palettes)],
                            'hdr_unk_equal': t28.hdr_unk == dk.hdr_unk,
                            'trailing': [len(t28.trailing), len(dk.trailing)]},
            'block': {'id': [tb.id, db.id],
                      'layout_size': [tb.layout()[1], db.layout()[1]],
                      'pad_equal': tb.pad == db.pad,
                      'count9': [tb.count9, db.count9],
                      'offsets_test28': list(tb.layout()[0]),
                      'offsets_dark': list(db.layout()[0])},
            'tables': {}, 'textures': [], 'palettes': [],
        }
        for name, ta, td in zip(TABLES, tb.tables(), db.tables()):
            row['tables'][name] = diff_table(ta, td, name)
        for i, (im28, imdk) in enumerate(zip(t28.textures, dk.textures)):
            d = bbox_of_diff(im28.data, imdk.data, im28.width, im28.height) if im28.data != imdk.data else {'changed_pixels': 0}
            d.update({'index': i, 'w': im28.width, 'h': im28.height,
                      'fmt': [list(im28.fmt), list(imdk.fmt)],
                      'dims_equal': (im28.width, im28.height) == (imdk.width, imdk.height),
                      'data_len': [len(im28.data), len(imdk.data)],
                      'pad': [len(im28.pad), len(imdk.pad)], 'pad_equal': im28.pad == imdk.pad})
            row['textures'].append(d)
        for i in range(max(len(t28.palettes), len(dk.palettes))):
            a = t28.palettes[i] if i < len(t28.palettes) else None
            b = dk.palettes[i] if i < len(dk.palettes) else None
            row['palettes'].append({
                'index': i,
                'test28': None if a is None else [list(a.fmt), a.width, a.height, a.unk],
                'dark': None if b is None else [list(b.fmt), b.width, b.height, b.unk],
                'data_equal': (a is not None and b is not None and a.data == b.data),
                'data_len': [None if a is None else len(a.data), None if b is None else len(b.data)],
                'pad_equal': (a is not None and b is not None and a.pad == b.pad),
            })
        result[bank] = row
        print(f'{bank}: raw {row["raw_test28"]:,} -> {row["raw_dark"]:,}')
        for name in TABLES:
            t = row['tables'][name]
            print(f'  {name:14s} {t["count_test28"]:6d} -> {t["count_dark"]:6d} appended {t["appended"]:3d} '
                  f'changed {t["changed_in_common_prefix"]}')
        for t in row['textures']:
            print(f'  texture{t["index"]} {t["w"]}x{t["h"]} changed pixels {t["changed_pixels"]} {t.get("bbox")}')
        print('  palettes: ' + ', '.join(f'{p["index"]}:{"same" if p["data_equal"] else ("new" if p["test28"] is None else "DIFF")}'
                                          for p in row['palettes']))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1) + '\n')
    print('wrote', out_path)


if __name__ == '__main__':
    main()
