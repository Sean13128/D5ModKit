"""Freeze existing 21/27 trees into hit slots, retaining each slot's control track.

Inputs are the local PALMERGE2B bundle; output is private build data, never Git.
"""
import copy, hashlib, json, sys
from pathlib import Path
KIT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(KIT))
from d5lib import anm
ROOT=Path('/Volumes/Data/Projects/D5/Builds')
BASE=ROOT/'PALFIX2-20261102/palmerge2b/mods'
OUT=ROOT/'HURTSLOT1-20261102'
# Each reaction page plays descending; five samples cover the seven source keys.
SAMPLES={117:0,116:12,115:24,114:30,121:0,120:12,119:24,118:30,125:0,124:12,123:24,122:30,106:36,126:36}

def freeze(b,root,tick):
    """Copy sibling/child tree, sampling each track at tick; preserve referenced art."""
    mapping={i:len(b.nodes)+j for j,(i,_,_) in enumerate(b.walk(root))}
    for old in mapping:
        n=copy.copy(b.nodes[old]); keys=b.node_keys(n)
        n.child=mapping[n.child] if n.child>=0 else -1
        n.next=mapping[n.next] if n.next>=0 else -1
        if keys:
            selected=max((k for k in keys if k.time<=tick),key=lambda k:k.time,default=keys[0])
            selected=copy.copy(selected); selected.time=0
            n.first_key=len(b.keys); n.num_keys=1; b.keys.append(selected)
        else: n.first_key=-1; n.num_keys=0
        b.nodes.append(n)
    return mapping[root]

def preserve_aliases(a, changed):
    b=a.block; anims={x.id:x for x in b.animations}; refs={}
    # Only stubs invoke nested animation IDs in the kit evaluator.
    for i,animation in enumerate(list(b.animations)):
        if animation.id in changed or not anm.is_stub(a,0,i): continue
        for ni,_,_ in b.walk(animation.root):
            for k in b.node_keys(b.nodes[ni]):
                if anm.is_nested(k) and 0<=k.param<len(b.params) and b.params[k.param] in changed:
                    refs.setdefault(animation.id,set()).add(b.params[k.param])
    targets=sorted(set().union(*refs.values())) if refs else []
    # Survey asserts the preserved trees are direct art, not further stubs.
    for aid in targets:
        idx=next(i for i,x in enumerate(b.animations) if x.id==aid)
        assert not anm.is_stub(a,0,idx), (aid,refs)
    free=(i for i in range(64000,65000) if i not in anims)
    redirects={aid:next(free) for aid in targets}
    for aid,newid in redirects.items(): b.animations.append(anm.Animation(newid,anims[aid].root))
    for aid in refs:
        animation=anims[aid]; originals=list(b.walk(animation.root))
        mapping={old:len(b.nodes)+j for j,(old,_,_) in enumerate(originals)}
        for old,_,_ in originals:
            n=copy.copy(b.nodes[old]); keys=b.node_keys(n)
            n.child=mapping[n.child] if n.child>=0 else -1
            n.next=mapping[n.next] if n.next>=0 else -1
            if keys:
                n.first_key=len(b.keys); n.num_keys=len(keys)
                for key in keys:
                    k=copy.copy(key)
                    if anm.is_nested(k) and 0<=k.param<len(b.params) and b.params[k.param] in redirects:
                        assert k.param+2<len(b.params)
                        record=b.params[k.param:k.param+3].copy(); record[0]=redirects[record[0]]
                        k.param=len(b.params); b.params.extend(record)
                    b.keys.append(k)
            else: n.first_key=-1; n.num_keys=0
            b.nodes.append(n)
        animation.root=mapping[animation.root]
    return redirects

def transform(path,keep):
    a=anm.load(path); assert len(a.blocks)==1
    b=a.block; ids=[x.id for x in b.animations]
    # CORED1CB: a fresh source build now carries its own 65003/65004 (the preserved held copy
    # ownanim writes), which are outside the 64000..64999 band this transform allocates from.
    # The reservation that matters is that band, not the highest id.
    assert ids==sorted(ids) and not any(64000<=i<65000 for i in ids), (path, ids[-3:])
    anims={x.id:x for x in b.animations}; original=(len(a.textures),len(a.palettes))
    changed={m*10+d for m in SAMPLES if not (keep and m in (106,114)) for d in (1,7)}
    preserve_aliases(a,changed)
    for motion,tick in SAMPLES.items():
        if keep and motion in (106,114): continue
        for direction in (1,7):
            aid=motion*10+direction; src=20+direction
            assert aid in anims and src in anims,(path,aid,src)
            dest=b.nodes[anims[aid].root]; source=b.nodes[anims[src].root]
            assert dest.child==-1 and dest.next>=0 and source.child==-1 and source.next>=0
            # BACKVIEW1: control first, frozen tree at root+1 -- the game draws node root+1, not root.next
            control=copy.copy(dest); anims[aid].root=len(b.nodes); b.nodes.append(control)
            control.next=freeze(b,source.next,tick)
            assert control.next==anims[aid].root+1
    assert original==(len(a.textures),len(a.palettes))
    # CORED1CB: a bank that already carries 65003/65004 gets its preserved aliases (64000+) appended
    # after them, so the id order is no longer ascending. Animation order is not semantic; the
    # reservation band is what the transform must not disturb, and it does not.
    b.animations.sort(key=lambda x: x.id)
    assert [x.id for x in b.animations]==sorted(x.id for x in b.animations)
    return anm.lzs_compress(a.to_bytes())

def main():
    sys.path.insert(0,str(KIT/"tools"))
    import d1cmotion2_base as base        # SOURCEPREP4-D1C: only the maintainer CLI needs the TEST28 base; transform() reads no path
    banks=sorted(BASE/mod/base.REL/bank for mod, names in base.manifest()['banks'].items() for bank in names); assert len(banks)==38,len(banks)
    receipt=json.loads((ROOT/'PALFIX2-20261102/evidence/readback-palfix2b.json').read_text())
    pins={(x['mod'],x['bank']):x for x in receipt}; assert len(pins)==38
    for bank in banks:
        mod=bank.relative_to(BASE).parts[0]; pin=pins[(mod,bank.name)]
        assert pin['installed_equals_replay'] and hashlib.sha256(bank.read_bytes()).hexdigest()==pin['staged_sha256'],bank
    rows=[]
    for bank in banks:
        rel=bank.relative_to(BASE); row={'bank':str(rel),'base_sha256':hashlib.sha256(bank.read_bytes()).hexdigest()}
        for name,keep in [('hurtslot',False),('hurtslot_keepcarry',True)]:
            out=OUT/name/'mods'/rel; out.write_bytes(transform(bank,keep))
            row[name]=hashlib.sha256(out.read_bytes()).hexdigest()
        rows.append(row); print(rel,flush=True)
    (OUT/'build-receipt.json').write_text(json.dumps({'sample_ticks':SAMPLES,'banks':rows},indent=2)+'\n')
if __name__=='__main__': main()
