"""EDFBISECT2: detail checks behind the region diff.

  * palette_infos / texture_infos: which FIELDS change (expect only the derived virtual offset)
  * the 14 appended cells: tex/pal/rect
  * do the changed atlas pixels fall inside any TEST28 cell rectangle? (i.e. is the art in holes?)
  * does the appended 21/27 tree reference the appended cells / palettes / colours?
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


def changed_mask(a: bytes, b: bytes):
    return [i for i in range(len(a)) if a[i] != b[i]]


def main():
    out = {}
    for mod, bank in (('D1C_Class_11400', 'anm01530.lzs'), ('D1C_Class_11390', 'anm01540.lzs')):
        t28 = anm.load((base.base_dir(mod) / mod / base.REL / bank).read_bytes())
        dk = anm.load((DARK / mod / base.REL / bank).read_bytes())
        tb, db = t28.block, dk.block
        row = {}
        # 1. palette_infos field-level
        fields = [f for f in tb.palette_infos[0].__dataclass_fields__]
        row['palette_infos_fields_changed'] = sorted({
            f for i in range(10) for f in fields
            if getattr(tb.palette_infos[i], f) != getattr(db.palette_infos[i], f)})
        row['palette_infos_old'] = [{f: getattr(tb.palette_infos[i], f) for f in fields} for i in (0, 9)]
        row['palette_infos_new_head'] = [{f: getattr(db.palette_infos[i], f) for f in fields} for i in (0, 9)]
        row['palette_infos_appended'] = [{f: getattr(db.palette_infos[i], f) for f in fields} for i in range(10, 20)]
        tf = [f for f in tb.texture_infos[0].__dataclass_fields__]
        row['texture_infos_fields_changed'] = sorted({
            f for i in range(2) for f in tf
            if getattr(tb.texture_infos[i], f) != getattr(db.texture_infos[i], f)})
        row['texture_infos_old'] = [{f: getattr(tb.texture_infos[i], f) for f in tf} for i in range(2)]
        row['texture_infos_new'] = [{f: getattr(db.texture_infos[i], f) for f in tf} for i in range(2)]
        # 2. appended cells
        row['cells_appended'] = [{'tex': c.tex, 'pal': c.pal, 'unk2': c.unk2, 'flags': c.flags,
                                  'x': c.x, 'y': c.y, 'w': c.w, 'h': c.h, 'unk8': c.unk8}
                                 for c in db.cells[len(tb.cells):]]
        # 3. changed pixels vs TEST28 cell rects
        tex = 0
        a, b = t28.textures[tex].data, dk.textures[tex].data
        w, h = t28.textures[tex].width, t28.textures[tex].height
        idx = changed_mask(a, b)
        cells = [(c.x, c.y, c.x + c.w, c.y + c.h) for c in tb.cells if c.tex == tex and c.w and c.h]
        inside = 0
        outside_bbox = None
        ox0 = oy0 = 10 ** 9
        ox1 = oy1 = -1
        for i in idx:
            y, x = divmod(i, w)
            hit = any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in cells)
            if hit:
                inside += 1
            else:
                ox0, oy0 = min(ox0, x), min(oy0, y)
                ox1, oy1 = max(ox1, x), max(oy1, y)
        row['pixels'] = {'texture': tex, 'changed': len(idx),
                         'inside_test28_cell_rects': inside,
                         'outside_bbox': [ox0, oy0, ox1, oy1] if ox1 >= 0 else None,
                         'test28_cell_count': len(cells)}
        # also: appended cells' rects vs changed pixels
        new_cells = [(c.x, c.y, c.x + c.w, c.y + c.h) for c in db.cells[len(tb.cells):] if c.tex == tex]
        covered = sum(1 for i in idx for y, x in [divmod(i, w)]
                      if any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in new_cells))
        row['pixels']['inside_appended_cell_rects'] = covered
        # 4. appended tree references
        appended_keys = db.keys[len(tb.keys):]
        row['appended_keys'] = {
            'count': len(appended_keys),
            'cell_refs': sorted({k.cell for k in appended_keys}),
            'pal_refs_via_cells': sorted({db.cells[k.cell].pal for k in appended_keys if k.cell < len(db.cells)}),
            'color_refs': sorted({k.color for k in appended_keys}),
            'param_refs_min': min(k.param for k in appended_keys),
            'flags': sorted({k.flags for k in appended_keys}),
        }
        row['appended_nodes'] = {'count': len(db.nodes) - len(tb.nodes),
                                 'ids': sorted({n.id for n in db.nodes[len(tb.nodes):]})}
        out[bank] = row
        print(bank, json.dumps(row, indent=1)[:2600])
    Path('/Volumes/Data/ai-tmp/codex/edfbisect2/detail.json').write_text(json.dumps(out, indent=1) + '\n')


if __name__ == '__main__':
    main()
