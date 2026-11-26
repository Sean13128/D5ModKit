"""Repack an existing PALFIX2 pre-banner graft into a prepared PALMERGE2B bundle.

The graft is reproducible with palfix2_build.py (set OUT to a disposable path
and NAME to LIVE5_PALMERGE2B). This script modifies the candidate bundle only;
it reuses the kit banner finalizer and preserves every indexed cell image.
"""
import sys,json
from pathlib import Path
WT=Path('/Volumes/Data/Projects/D5/Local/Worktrees/palfix2b');sys.path[:0]=[str(WT),str(WT/'tools')]
import d1cmotion2_base as base
from d5lib import anm,ownanim
from palfix1_build import pixels
R=Path('/Volumes/Data/Projects/D5/Builds/PALFIX2-20261102');out=R/'palmerge2b/mods';src=Path(sys.argv[1])/'mods' if len(sys.argv)>1 else Path('/Volumes/Data/ai-tmp/codex/palfix2b/prebanner/mods');targets=json.loads((R/'evidence/test28-installer-header-replay.json').read_text());result={}
for mod,banks in base.manifest()['banks'].items():
 if not mod.startswith('D1C_Unique_'):continue
 for bank in banks:
  orig=anm.load(src/mod/base.REL/bank);seen={};duplicates=[]
  for i,c in enumerate(orig.block.cells):
   if not i or not c.w or not c.h or c.tex>=len(orig.textures):continue
   key=(c.w,c.h,pixels(orig,c).tobytes())
   if key in seen:
    t,x,y=seen[key]
    if (c.tex,c.x,c.y)!=(t,x,y):duplicates.append((i,t,x,y))
   else:seen[key]=(c.tex,c.x,c.y)
  target=targets[f'{mod}/{bank}']['replay_headers'];lo=0;hi=len(duplicates); chosen=None
  while lo<=hi:
   k=0 if chosen is None and lo==0 and hi==len(duplicates) else (lo+hi)//2
   a=anm.load(orig.to_bytes())
   for i,t,x,y in duplicates[:k]:
    c=a.block.cells[i];a.block.cells[i]=anm.Cell(t,c.pal,c.unk2,c.flags,x,y,c.w,c.h,c.unk8)
   ownanim.banner_layout(a);n=len(a.textures)+len(a.palettes)
   if n==target:chosen=(k,a);break
   if n>target:lo=k+1
   else:hi=k-1
  assert chosen,(mod,bank,target,lo,hi)
  k,a=chosen;assert not ownanim.banner_layout(a);assert len(a.palettes)==20
  p=out/mod/base.REL/bank;p.write_bytes(anm.lzs_compress(a.to_bytes()))
  result[f'{mod}/{bank}']={'duplicate_cells_repointed':k,'installed_headers':n,'test28_replay_headers':target,'palettes':20,'banner_idempotent':True}
  print(mod,bank,k,n,target,flush=True)
(R/'evidence/palfix2b-layout.json').write_text(json.dumps(result,indent=1)+'\n')
