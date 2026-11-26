"""EDFBISECT2 step 1b: what the EDF delta has that the Strider delta does not.

Compares, per region, the TEST28->BS-DARK delta of anm01530 (EDF) and anm01540 (Strider), and the
sizes/offsets/counts of both against every power of two they sit near, so any crossing that happens
in EDF and not in Strider (or the reverse) is visible.

usage: python tools/edfbisect2_edf_vs_strider.py
"""
from __future__ import annotations

import hashlib
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
BANKS = {'EDF': ('D1C_Class_11400', 'anm01530.lzs'),
         'Strider': ('D1C_Class_11390', 'anm01540.lzs')}
TABLES = ['animations', 'nodes', 'keys', 'palette_infos', 'texture_infos', 'cells',
          'transforms', 'pivots', 'colors', 'params']


def crossings(a: int, b: int):
    """powers of two strictly crossed by the interval [a, b]."""
    lo, hi = min(a, b), max(a, b)
    return [1 << k for k in range(0, 40) if lo < (1 << k) <= hi]


def main():
    out = {}
    for label, (mod, bank) in BANKS.items():
        t = anm.load((base.base_dir(mod) / mod / base.REL / bank).read_bytes())
        d = anm.load((DARK / mod / base.REL / bank).read_bytes())
        tb, db = t.block, d.block
        row = {'bank': bank, 'tables': {}, 'sizes': {}}
        for name, ta, td in zip(TABLES, tb.tables(), db.tables()):
            row['tables'][name] = {'test28': len(ta), 'dark': len(td),
                                   'delta': len(td) - len(ta),
                                   'crossings': crossings(len(ta), len(td))}
        row['tables']['palette_images'] = {'test28': len(t.palettes), 'dark': len(d.palettes),
                                           'delta': len(d.palettes) - len(t.palettes),
                                           'crossings': crossings(len(t.palettes), len(d.palettes))}
        row['sizes'] = {
            'raw': {'test28': len(t.to_bytes()), 'dark': len(d.to_bytes()),
                    'crossings': crossings(len(t.to_bytes()), len(d.to_bytes()))},
            'block': {'test28': tb.layout()[1], 'dark': db.layout()[1],
                      'crossings': crossings(tb.layout()[1], db.layout()[1])},
            'texture0': {'test28': t.textures[0].width * t.textures[0].height,
                         'dark': d.textures[0].width * d.textures[0].height, 'crossings': []},
            'texture1': {'test28': t.textures[1].width * t.textures[1].height,
                         'dark': d.textures[1].width * d.textures[1].height, 'crossings': []},
            'single_allocation': {'test28': (len(t.to_bytes()) + 0xFFFF) & ~0xFFFF,
                                  'dark': (len(d.to_bytes()) + 0xFFFF) & ~0xFFFF,
                                  'crossings': crossings((len(t.to_bytes()) + 0xFFFF) & ~0xFFFF,
                                                         (len(d.to_bytes()) + 0xFFFF) & ~0xFFFF)},
        }
        # palette content of the 10 new palettes: how much of each is distinct / unused
        pal = []
        for i, im in enumerate(d.palettes[len(t.palettes):], start=len(t.palettes)):
            colours = [bytes(im.data[j:j + 4]) for j in range(0, len(im.data), 4)]
            pal.append({'index': i, 'distinct': len(set(colours)),
                        'black': sum(1 for c in colours if c == b'\0\0\0\0'),
                        'sha256': hashlib.sha256(im.data).hexdigest()})
        row['new_palettes'] = pal
        out[label] = row
        print(f'== {label} ({bank})')
        for name in list(TABLES) + ['palette_images']:
            r = row['tables'][name]
            flag = f"  CROSSES {r['crossings']}" if r['crossings'] else ''
            print(f'  {name:14s} {r["test28"]:6d} -> {r["dark"]:6d} (+{r["delta"]}){flag}')
        for k, v in row['sizes'].items():
            flag = f"  CROSSES {v['crossings']}" if v['crossings'] else ''
            print(f'  {k:18s} {v["test28"]:>9} -> {v["dark"]:>9}{flag}')
        print('  new palettes distinct/black: ' +
              ', '.join(f"{p['index']}:{p['distinct']}/{p['black']}" for p in pal))

    e, s = out['EDF'], out['Strider']
    only_edf, only_str = [], []
    for name in set(e['tables']) | set(e['sizes']):
        ce = (e['tables'].get(name) or e['sizes'].get(name) or {}).get('crossings') or []
        cs = (s['tables'].get(name) or s['sizes'].get(name) or {}).get('crossings') or []
        if set(ce) - set(cs):
            only_edf.append({name: sorted(set(ce) - set(cs))})
        if set(cs) - set(ce):
            only_str.append({name: sorted(set(cs) - set(ce))})
    out['crossings_only_edf'] = only_edf
    out['crossings_only_strider'] = only_str
    out['new_palettes_identical_between_banks'] = [
        a['sha256'] == b['sha256'] for a, b in zip(e['new_palettes'], s['new_palettes'])]
    print('== crossings only in EDF:', only_edf)
    print('== crossings only in Strider:', only_str)
    print('== new palette images identical across the two banks:',
          out['new_palettes_identical_between_banks'])
    p = Path('/Volumes/Data/Projects/D5/Builds/EDFBISECT2-20261102/evidence/edf-vs-strider.json')
    p.write_text(json.dumps(out, indent=1) + '\n')
    print('wrote', p)


if __name__ == '__main__':
    main()
