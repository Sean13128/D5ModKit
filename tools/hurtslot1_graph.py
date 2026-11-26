"""Prove unchanged animation dependency closures retain identical ANM data."""
import json,sys
from pathlib import Path
KIT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(KIT),str(KIT/'tools')]
from d5lib import anm
import d1cmotion2_base as base, striderlift_render_diff as gate
from hurtslot1_build import BASE,OUT,SAMPLES

def graph(a,b,changed):
 x,y=a.block,b.block
 # Existing indexed tables and image data must be identical. New node/key suffixes are allowed.
 tables=[]
 for i,(u,v) in enumerate(zip(x.tables(),y.tables())):
  if i==0: continue
  if i==3: tables.append([(z.num_colors,z.unk) for z in v[:len(u)]]==[(z.num_colors,z.unk) for z in u]); continue
  if i==4: tables.append([(z.width,z.height,z.bpp,z.unk1,z.unk2,z.unk3) for z in v[:len(u)]]==[(z.width,z.height,z.bpp,z.unk1,z.unk2,z.unk3) for z in u]); continue
  tables.append(v[:len(u)]==u)
 def imsig(xs): return [(z.fmt,z.width,z.height,z.unk,z.data) for z in xs]
 images=(imsig(a.textures)==imsig(b.textures) and imsig(a.palettes)==imsig(b.palettes))
 xa={v.id:(i,v) for i,v in enumerate(x.animations)};ya={v.id:(i,v) for i,v in enumerate(y.animations)}
 extra=set(ya)-set(xa); alias={64000:1061,64001:1067} if extra else {}
 assert extra in (set(),set(alias)),extra
 def same_tree(xn,yn,seen):
  if (xn,yn) in seen:return True
  seen.add((xn,yn))
  if xn<0 or yn<0:return xn==yn
  n,m=x.nodes[xn],y.nodes[yn]
  if (n.id,n.flags,n.unk2,n.unk3,n.mesh,n.unk5,n.num_keys)!=(m.id,m.flags,m.unk2,m.unk3,m.mesh,m.unk5,m.num_keys):return False
  for k,l in zip(x.node_keys(n),y.node_keys(m)):
   if (k.time,k.flags,k.cell,k.xform,k.color)!=(l.time,l.flags,l.cell,l.xform,l.color):return False
   if anm.is_nested(k):
    u=x.params[k.param:k.param+3];v=y.params[l.param:l.param+3]
    if len(v)==3:v=[alias.get(v[0],v[0]),*v[1:]]
    if u!=v:return False
   elif k.param!=l.param:return False
  return same_tree(n.child,m.child,seen) and same_tree(n.next,m.next,seen)
 def closure(aid,seen):
  if aid in seen or aid not in ya:return set()
  seen.add(aid); i,anim=ya[aid]; hits={aid} if aid in changed else set()
  if anm.is_stub(b,0,i):
   for ni,_,_ in y.walk(anim.root):
    for k in y.node_keys(y.nodes[ni]):
     if anm.is_nested(k) and 0<=k.param<len(y.params):hits |= closure(y.params[k.param],seen)
  return hits
 indirect={}; trees=[]
 for aid,(i,anim) in xa.items():
  if aid in changed:continue
  trees.append(aid in ya and same_tree(anim.root,ya[aid][1].root,set()))
  hits=closure(aid,set())
  unpreserved=sorted(hits)
  if unpreserved:indirect[aid]=unpreserved
 for newid,original in alias.items(): trees.append(same_tree(xa[original][1].root,ya[newid][1].root,set()))
 return {'tables_prefix_equal':all(tables),'images_equal':images,'semantic_trees_equal':all(trees),'unpreserved_dependencies':indirect,'added_ids':sorted(extra),'pass':all(tables) and images and all(trees) and not indirect}


def main():
 rows=[];ok=True
 for mod,names in base.manifest()['banks'].items():
  for bank in names:
   rel=Path(mod)/base.REL/bank;raw=(BASE/rel).read_bytes()
   for v,keep in [('hurtslot',False),('hurtslot_keepcarry',True)]:
    data=(OUT/v/'mods'/rel).read_bytes();changed={m*10+d for m in SAMPLES if not(keep and m in (106,114)) for d in (1,7)}
    for post in (False,True):
     mode='banner,grips' if 'Unique' in mod else 'grips'
     a,b=(anm.load(gate.replay_member(t,mode) if post else t) for t in (raw,data))
     z=graph(a,b,changed);z.update(bank=str(rel),variant=v,post=post);rows.append(z);ok &= z['pass']
   print(rel,'PASS' if all(z['pass'] for z in rows[-4:]) else 'FAIL',flush=True)
 (OUT/'evidence/graph.json').write_text(json.dumps({'pass':bool(ok),'rows':rows},indent=2)+'\n')
 return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
