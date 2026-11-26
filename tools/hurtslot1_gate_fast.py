"""Gate both variants together; reuse baseline poses for equal sample requests."""
import json,sys
from pathlib import Path
from collections import OrderedDict
import numpy as np
KIT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(KIT),str(KIT/'tools')]
from d5lib import anm
import d1cmotion2_base as base, striderlift_render_diff as g
from hurtslot1_build import BASE,OUT,SAMPLES

def signature(im,pos): return (pos,im.size,im.tobytes())
def check(a,bs):
    # Texture decoding is shared within each bank for the full duration of this phase.
    old=anm.texture_to_image; cache=OrderedDict()
    def texture(o,t,palette=0):
        k=(id(o),t,palette)
        if k not in cache:
            cache[k]=old(o,t,palette)
            if len(cache)>192: cache.popitem(last=False)
        else: cache.move_to_end(k)
        return cache[k]
    anm.texture_to_image=texture
    try:
        indexes=[{x['id']:x['index'] for x in anm.list_animations(o)} for o in (a,*bs)]
        assert indexes[0].keys()==indexes[2].keys()
        extra=set(indexes[1])-set(indexes[0]); assert extra in (set(),{64000,64001}),extra
        assert set(indexes[0]) <= set(indexes[1])
        for bank in (a,*bs):
            ids=[z.id for z in bank.block.animations]; assert ids==sorted(ids)
        if extra:
            aa={v.id:v for v in a.block.animations}; bb={v.id:v for v in bs[0].block.animations}
            assert bb[64000].root==aa[1061].root and bb[64001].root==aa[1067].root
        source_cache={}
        rows=[{'unchanged_samples':0,'unchanged_bad':0,'art_samples':0,'art_bad':0,'art_blank':0,'examples':[]} for _ in bs]
        for aid,idx in indexes[0].items():
            changed=aid//10 in SAMPLES and aid%10 in (1,7)
            for rank in range(len(a.palettes)):
                times=set(anm.frame_times(a,idx))
                for b,ix in zip(bs,indexes[1:]): times.update(anm.frame_times(b,ix[aid]))
                if changed: times.update((0,2,4))
                times=sorted(times)
                # For unchanged slots render baseline only once, even when both variants need it.
                for t in times:
                    baseline=signature(*g.pose(a,idx,t,rank)) if not changed or aid//10 in (106,114) else None
                    for j,(b,ix) in enumerate(zip(bs,indexes[1:])):
                        row=rows[j]; hit=changed and not (j==1 and aid//10 in (106,114))
                        candidate=signature(*g.pose(b,ix[aid],t,rank))
                        if hit:
                            key=(aid%10,SAMPLES[aid//10],rank)
                            if key not in source_cache: source_cache[key]=signature(*g.pose(a,indexes[0][20+aid%10],key[1],rank))
                            source=source_cache[key]
                            row['art_samples']+=1; row['art_blank']+=int(source[0] is None or candidate[0] is None)
                            if source!=candidate: row['art_bad']+=1
                        else:
                            row['unchanged_samples']+=1
                            if baseline!=candidate: row['unchanged_bad']+=1
                        if (source!=candidate if hit else baseline!=candidate) and len(row['examples'])<12:
                            row['examples'].append([aid,rank,t,'art' if hit else 'unchanged'])
        return rows
    finally: anm.texture_to_image=old

def main():
    out=OUT/'evidence';out.mkdir(exist_ok=True);rows=[];ok=True
    for mod,names in base.manifest()['banks'].items():
      for bank in names:
        rel=Path(mod)/base.REL/bank;raw=(BASE/rel).read_bytes();data=[(OUT/v/'mods'/rel).read_bytes() for v in ('hurtslot','hurtslot_keepcarry')]
        row={'bank':str(rel)}
        for post in (False,True):
          mode='banner,grips' if 'Unique' in mod else 'grips'
          objs=[anm.load(g.replay_member(x,mode) if post else x) for x in [raw,*data]]; a,*bs=objs
          checks=check(a,bs)
          for j,b in enumerate(bs):
            exempt={m*10+d for m in SAMPLES if not (j==1 and m in (106,114)) for d in (1,7)}
            controls=[]
            for aid in sorted(exempt):
              x=next(z for z in a.block.animations if z.id==aid);y=next(z for z in b.block.animations if z.id==aid)
              xn=a.block.nodes[x.root];yn=b.block.nodes[y.root]
              controls.append(a.block.node_keys(xn)==b.block.node_keys(yn) and (xn.id,xn.flags,xn.unk2,xn.unk3,xn.mesh,xn.unk5)==(yn.id,yn.flags,yn.unk2,yn.unk3,yn.mesh,yn.unk5))
            s=anm.compare_structure(a,b);c=checks[j]
            c.update(new_structural_findings=len(s['structural_problems']), controls_match=all(controls),counts_match=(len(a.textures),len(a.palettes))==(len(b.textures),len(b.palettes)))
            c['pass']=not(c['new_structural_findings'] or c['unchanged_bad'] or c['art_bad'] or c['art_blank']) and c['controls_match'] and c['counts_match'];ok &= c['pass']
          row['post' if post else 'staged']=checks
        rows.append(row);(out/'gate-partial.json').write_text(json.dumps({'pass_so_far':bool(ok),'rows':rows},indent=2)+'\n')
        print(rel,'PASS' if all(x['pass'] for k in ('staged','post') for x in row[k]) else 'FAIL',flush=True)
    (out/'gate.json').write_text(json.dumps({'pass':bool(ok),'rows':rows},indent=2)+'\n'); return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
