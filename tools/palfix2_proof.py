"""PALFIX2 field, palette and baseline-relative structure proof."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
MODS = ROOT / 'Builds/PALFIX2-20261102/palmerge2/mods'
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
EV = ROOT / 'Builds/PALFIX2-20261102/evidence'
TAB = ('nodes', 'keys', 'cells', 'transforms', 'pivots', 'colors', 'params')


def px(a, c):
    t = a.textures[c.tex]
    m = np.frombuffer(t.data, np.uint8).reshape(t.height, t.width)
    return m[c.y:c.y + c.h, c.x:c.x + c.w]


def main():
    out = {}
    for mod in (m for m in base.manifest()['banks'] if m.startswith('D1C_Unique_')):
        for bank in base.manifest()['banks'][mod]:
            t28 = anm.load(base.bank_path(mod, bank))
            slim = anm.load(SLIM / mod / base.REL / bank)
            new = anm.load(MODS / mod / base.REL / bank)
            n0 = len(t28.block.cells)
            row = {'vs_test28': {}, 'vs_slim29': {}}
            for name in TAB:
                a = getattr(t28.block, name)
                b = getattr(new.block, name)
                s = getattr(slim.block, name)
                row['vs_test28'][name] = {'test28': len(a), 'built': len(b),
                                          'prefix_equal': b[:len(a)] == a,
                                          'appended': len(b) - len(a)}
                if name == 'cells':
                    same = [i for i, (x, y) in enumerate(zip(s[len(a):], b[len(a):]))
                            if x.__dict__ == y.__dict__]
                    pal_only = all(x.tex == y.tex and x.x == y.x and x.y == y.y and
                                   x.w == y.w and x.h == y.h and x.flags == y.flags and
                                   x.unk2 == y.unk2 and x.unk8 == y.unk8 and
                                   x.pal == 20 and y.pal == 10
                                   for x, y in zip(s[len(a):], b[len(a):]))
                    row['vs_slim29'][name] = {'slim29': len(s), 'built': len(b),
                                              'prefix_equal': b[:len(a)] == s[:len(a)],
                                              'appended_identical': len(same),
                                              'appended_differs_only_in_pal': pal_only}
                else:
                    k = len(a)
                    entry = {'slim29': len(s), 'built': len(b),
                             'prefix_equal': b[:k] == s[:k],
                             'tail_equal': b[k:] == s[k:]}
                    if name == 'keys' and not entry['tail_equal']:
                        tb, ts = b[k:], s[k:]
                        diff = [i for i, (x, y) in enumerate(zip(ts, tb)) if x != y]
                        entry['tail_differs'] = len(diff)
                        entry['tail_differs_only_in_param'] = all(
                            ts[i].time == tb[i].time and ts[i].flags == tb[i].flags and
                            ts[i].cell == tb[i].cell and ts[i].xform == tb[i].xform and
                            ts[i].color == tb[i].color and ts[i].param != tb[i].param for i in diff)
                    row['vs_slim29'][name] = entry
            # key params: exactly the 60 out-of-range ones differ from SLIM29
            bad = [i for i, k in enumerate(slim.block.keys) if k.param >= len(slim.block.params)]
            row['param_fix'] = {'count': len(bad),
                                'all_now_in_range': all(new.block.keys[i].param < len(new.block.params) for i in bad),
                                'changed_vs_slim29': sum(1 for i in bad
                                                         if new.block.keys[i].param != slim.block.keys[i].param),
                                'others_unchanged': all(new.block.keys[i] == slim.block.keys[i]
                                                        for i in range(len(new.block.keys))
                                                        if i not in set(bad))}
            # palettes and image headers
            row['counts'] = {'palettes_test28': len(t28.palettes), 'palettes_built': len(new.palettes),
                             'palette_infos_built': len(new.block.palette_infos),
                             'images_test28': len(t28.palettes) + len(t28.textures),
                             'images_built': len(new.palettes) + len(new.textures),
                             'textures_test28': len(t28.textures), 'textures_built': len(new.textures)}
            # base art untouched
            same_px = all((px(t28, c) == px(new, c)).all() for c in t28.block.cells
                          if 0 <= c.tex < len(t28.textures) and c.w and c.h)
            use = np.zeros(256, np.int64)
            for c in t28.block.cells:
                if c.w and c.h:
                    use += np.bincount(px(t28, c).ravel(), minlength=256)
            used = np.nonzero(use)[0].tolist()
            pal_ok = all((anm.get_palette(t28, p)[used] == anm.get_palette(new, p)[used]).all()
                         for p in range(len(t28.palettes)))
            changed = sum(len(set(np.nonzero((anm.get_palette(t28, p) != anm.get_palette(new, p)).any(1))[0])
                              ) for p in range(len(t28.palettes)))
            row['base_art'] = {'cells_pixel_identical': bool(same_px),
                               'used_palette_entries_identical': bool(pal_ok),
                               'entries_changed_total_across_10_palettes': changed,
                               'art_pixels_remapped': int(sum(c.w * c.h for c in new.block.cells[n0:]))}
            row['raw'] = {'test28': len(t28.to_bytes()), 'slim29': len(slim.to_bytes()),
                          'built': len(new.to_bytes())}
            row['structure'] = {tag: anm.compare_structure(origin, new)['structural_problems']
                                for tag, origin in [('test28', t28), ('slim29', slim)]}
            assert not any(row['structure'].values()), (mod, bank, row['structure'])
            assert all(v['prefix_equal'] for v in row['vs_test28'].values()), (mod, bank, 'prefix')
            assert all(v.get('tail_equal', v.get('appended_differs_only_in_pal')) or k == 'keys'
                       for k, v in row['vs_slim29'].items()), (mod, bank, 'tail')
            assert row['param_fix']['count'] == 60 and row['param_fix']['others_unchanged']
            assert same_px and pal_ok
            assert row['counts']['images_test28'] == row['counts']['images_built']
            assert row['counts']['palettes_test28'] == row['counts']['palettes_built']
            out[f'{mod}/{bank}'] = row
            print(f"{mod}/{bank}: vs TEST28 tables prefix-equal "
                  f"{all(v['prefix_equal'] for v in row['vs_test28'].values())}; "
                  f"vs SLIM29 tails equal {all(v.get('tail_equal', v.get('appended_differs_only_in_pal')) for v in row['vs_slim29'].values())}; "
                  f"params fixed {row['param_fix']['count']} (others unchanged "
                  f"{row['param_fix']['others_unchanged']}); base pixels identical {same_px}; "
                  f"{changed} palette entries changed, none used; raw {row['raw']['built']:,}", flush=True)
    EV.mkdir(parents=True, exist_ok=True)
    (EV / 'proof.json').write_text(json.dumps(out, indent=1) + '\n')
    print('wrote', EV / 'proof.json')


if __name__ == '__main__':
    main()
