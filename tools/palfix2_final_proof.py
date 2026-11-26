"""Prove final banner-repacked output against banner-repacked TEST28 and the graft."""
import json,sys
from pathlib import Path
import numpy as np
KIT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(KIT),str(KIT/'tools')]
import d1cmotion2_base as base
from d5lib import anm, ownanim
from palfix1_build import pixels
ROOT=Path('/Volumes/Data/Projects/D5/Builds/PALFIX2-20261102')
OUT=ROOT/'palmerge2/mods'
PRE=Path('/Volumes/Data/ai-tmp/codex/palfix2/palmerge2-prebanner/mods')

def main():
 rows={}
 for mod,banks in base.manifest()['banks'].items():
  if not mod.startswith('D1C_Unique_'): continue
  for bank in banks:
   t=anm.load(base.bank_path(mod,bank)); before=anm.load(PRE/mod/base.REL/bank); a=anm.load(OUT/mod/base.REL/bank)
   baseline=anm.load(t.to_bytes()); ownanim.banner_layout(baseline)
   problems=anm.compare_structure(t,a)['structural_problems']; problems_banner=anm.compare_structure(baseline,a)['structural_problems']
   assert not problems and not problems_banner,(mod,bank,problems,problems_banner)
   assert len(a.palettes)==len(t.palettes) and len(a.textures)==len(t.textures)
   assert not ownanim.banner_layout(a)
   use=set()
   for c in t.block.cells:
    if c.w and c.h and c.tex<len(t.textures):use.update(int(i) for i in np.unique(pixels(t,c)))
   used=sorted(use)
   for p in range(len(t.palettes)):assert np.array_equal(anm.get_palette(t,p)[used],anm.get_palette(a,p)[used])
   assert all(np.array_equal(pixels(baseline,x),pixels(a,y)) for x,y in zip(baseline.block.cells,a.block.cells) if x.w and x.h and x.tex<len(baseline.textures))
   # The only changes between the graft and the pre-banner candidate are cells and texture tables/data.
   for name in ('animations','nodes','keys','pivots','transforms','colors','params'):
    assert getattr(before.block,name)==getattr(a.block,name),(mod,bank,name)
   assert all(np.array_equal(anm.get_palette(before,p),anm.get_palette(a,p)) for p in range(len(a.palettes)))
   rows[f'{mod}/{bank}']={'new_structural_findings_vs_test28':0,'new_structural_findings_vs_banner_test28':0,
       'test28_cell_pixels_match_banner_baseline':True,'used_palette_entries_unchanged':True,
       'noncell_tables_equal_prebanner_graft':True,'palettes_equal_prebanner_graft':True,
       'installed_layout_idempotent':True,'palette_count':len(a.palettes),'image_headers':len(a.palettes)+len(a.textures)}
   print(mod,bank,'PASS',flush=True)
 (ROOT/'evidence'/'final-proof.json').write_text(json.dumps(rows,indent=1)+'\n')
if __name__=='__main__':main()
