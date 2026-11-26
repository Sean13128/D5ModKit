import sys,copy
from pathlib import Path
root=Path('/Volumes/Data/Projects/D5');kit=root/'Local/Worktrees/striderlift4';sys.path.insert(0,str(kit))
from d5lib import anm,ownanim
old,new,out=map(Path,sys.argv[1:]);a=anm.load(old);b=anm.load(new)
assert len(a.blocks)==len(b.blocks)==1
x=a.block;y=b.block
print('old palette refs',sorted({c.pal for c in x.cells}),'palette count',len(x.palette_infos))
# All old six variant palette lookups must stay within old palette table.
assert all(c.pal+5<len(x.palette_infos) for c in x.cells if c.w and c.h)
nodebase=len(x.nodes);keybase=len(x.keys);cellbase=len(x.cells);xfbase=len(x.transforms);pivotbase=len(x.pivots);colorbase=len(x.colors);parambase=len(x.params);texbase=len(x.texture_infos);palbase=len(x.palette_infos)
for n in y.nodes:
 n=copy.copy(n); n.first_key=n.first_key+keybase if n.first_key>=0 else -1;n.child=n.child+nodebase if n.child>=0 else -1;n.next=n.next+nodebase if n.next>=0 else -1;x.nodes.append(n)
for k in y.keys:
 k=copy.copy(k);k.cell=k.cell+cellbase if k.cell else 0;k.xform+=xfbase;k.color+=colorbase;k.param+=parambase;x.keys.append(k)
for c in y.cells:
 c=copy.copy(c);c.tex+=texbase;c.pal+=palbase;x.cells.append(c)
for t in y.transforms:
 t=copy.copy(t);t.pivot+=pivotbase;x.transforms.append(t)
x.pivots.extend(copy.deepcopy(y.pivots));x.colors.extend(copy.deepcopy(y.colors));x.params.extend(y.params);x.texture_infos.extend(copy.deepcopy(y.texture_infos));x.palette_infos.extend(copy.deepcopy(y.palette_infos));a.textures.extend(copy.deepcopy(b.textures));a.palettes.extend(copy.deepcopy(b.palettes))
lookup={v.id:v for v in y.animations}
for anim in x.animations:
 if anim.id in (11,17,1101,1107,1131,1137):anim.root=lookup[anim.id].root+nodebase
# Retarget stubs to a held neighbour with the same first seven-tick drawing;
# adjust each key in its own transform space to preserve the old pivot placement.
import math
for ai,anim in enumerate(x.animations):
 if anim.id in (11,17) or not anm.is_stub(a,0,ai): continue
 for ni,_,_ in x.walk(anim.root):
  for k in x.node_keys(x.nodes[ni]):
   if not anm.is_nested(k) or not 0<=k.param<len(x.params): continue
   target=x.params[k.param]
   if target not in (11,17): continue
   alternate=(31 if target==11 else 37) if anim.id in (1011,1017) else (1011 if target==11 else 1017)
   # Compute old-vs-alternate position from the original animations at t=0.
   # All relevant originals were kept in the old block under their original roots.
   def corner(root_index):
    oldroot=anim.root; anim.root=root_index
    try:
     im,origin=anm.render_items(a,anm.evaluate(a,('id',anim.id),0,nested=True));box=im.getchannel('A').getbbox();return box[0]-origin[0],box[1]-origin[1]
    finally:anim.root=oldroot
   # Baseline root positions are measured from a separate baseline object, so 11 remains intact.
   if '_baseline' not in globals(): _baseline=anm.load(old)
   def pos(which):
    im,o=anm.render_items(_baseline,anm.evaluate(_baseline,('id',which),0,nested=True)); bb=im.getchannel('A').getbbox();return bb[0]-o[0],bb[1]-o[1]
   p0=pos(target);p1=pos(alternate);dx=p0[0]-p1[0];dy=p0[1]-p1[1]
   t=copy.copy(x.transforms[k.xform]);r=math.radians(t.rot); ox=math.cos(r)*t.sx/100*dx-math.sin(r)*t.sy/100*dy;oy=math.sin(r)*t.sx/100*dx+math.cos(r)*t.sy/100*dy
   assert abs(ox-round(ox))<1e-6 and abs(oy-round(oy))<1e-6
   t.x+=int(round(ox));t.y+=int(round(oy));k.xform=len(x.transforms);x.transforms.append(t)
   k.param=len(x.params);x.params.extend([alternate,0,-1])
# Align transplanted drawings with original stand. Shared transforms may be reused, so clone each affected transform.
def bottom(aid):
 times=anm.frame_times(a,('id',aid)) if aid in (11,17) else anm.frame_times(a,('id',aid))[:1]
 values=[]
 for t in times:
  im,origin=anm.render_items(a,anm.evaluate(a,('id',aid),t,nested=True));values.append(im.getchannel('A').getbbox()[3]-origin[1])
 return max(values)
for aid,stand in [(11,1001),(17,1007),(1101,1001),(1107,1007)]:
 dy=int(round(bottom(stand)-bottom(aid)));print(aid,'shift y',dy)
 if dy:
  animation=next(t for t in x.animations if t.id==aid)
  byold={}
  for ni,_,_ in x.walk(animation.root):
   for k in x.node_keys(x.nodes[ni]):
    if k.cell:
     if k.xform not in byold:
      t=copy.copy(x.transforms[k.xform]);t.y+=dy;byold[k.xform]=len(x.transforms);x.transforms.append(t)
     k.xform=byold[k.xform]
out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(anm.lzs_compress(a.to_bytes()));print('WROTE',out)
