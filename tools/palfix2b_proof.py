"""Check structure and every graft cell and palette after PALFIX2B repacking."""
import sys,json
from pathlib import Path
import numpy as np
WT=Path('/Volumes/Data/Projects/D5/Local/Worktrees/palfix2b');sys.path[:0]=[str(WT),str(WT/'tools')]
import d1cmotion2_base as base
from d5lib import anm,ownanim
from palfix1_build import pixels
R=Path('/Volumes/Data/Projects/D5/Builds/PALFIX2-20261102');src=Path(sys.argv[1])/'mods' if len(sys.argv)>1 else Path('/Volumes/Data/ai-tmp/codex/palfix2b/prebanner/mods');dst=R/'palmerge2b/mods';targets=json.loads((R/'evidence/test28-installer-header-replay.json').read_text());rows={}
for mod,banks in base.manifest()['banks'].items():
 if not mod.startswith('D1C_Unique_'):continue
 for bank in banks:
  t=anm.load(base.bank_path(mod,bank)); before=anm.load(src/mod/base.REL/bank);a=anm.load(dst/mod/base.REL/bank);baseline=anm.load(t.to_bytes());ownanim.banner_layout(baseline)
  probs=anm.compare_structure(t,a)['structural_problems'];probs2=anm.compare_structure(baseline,a)['structural_problems'];assert not probs and not probs2,(mod,bank,probs,probs2)
  assert len(a.textures)+len(a.palettes)==targets[f'{mod}/{bank}']['replay_headers'] and len(a.palettes)==20
  assert not ownanim.banner_layout(a)
  for x,y in zip(before.block.cells,a.block.cells):
   assert (x.pal,x.unk2,x.flags,x.w,x.h,x.unk8)==(y.pal,y.unk2,y.flags,y.w,y.h,y.unk8)
   if x.w and x.h and x.tex<len(before.textures):assert np.array_equal(pixels(before,x),pixels(a,y)),(mod,bank,'pixel')
  assert len(before.block.cells)==len(a.block.cells)
  for name in ('animations','nodes','keys','pivots','transforms','colors','params'):assert getattr(before.block,name)==getattr(a.block,name),(mod,bank,name)
  for p in range(20):assert np.array_equal(anm.get_palette(before,p),anm.get_palette(a,p))
  rows[f'{mod}/{bank}']={'new_structural_findings_vs_test28':0,'new_structural_findings_vs_repacked_test28':0,'all_graft_cell_pixels_and_nonlocation_fields_equal':True,'noncell_tables_equal_graft':True,'palettes_equal_graft':True,'banner_idempotent':True,'installed_headers':len(a.textures)+len(a.palettes),'test28_replay_headers':targets[f'{mod}/{bank}']['replay_headers'],'palettes':20}
  print(mod,bank,'PASS',flush=True)
(R/'evidence/palfix2b-field-proof.json').write_text(json.dumps(rows,indent=1)+'\n')
