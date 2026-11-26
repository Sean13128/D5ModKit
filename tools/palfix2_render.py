"""Render every TEST28 animation, except changed 21/27, and new 21/27 vs SLIM29.
Repeat with the member-local grips installer replay. Samples all frame times and 20 ranks.
"""
import json, sys
from collections import OrderedDict
from pathlib import Path
import numpy as np
KIT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(KIT),str(KIT/'tools')]
import d1cmotion2_base as base
from d5lib import anm
import striderlift_render_diff as gate
ROOT=Path('/Volumes/Data/Projects/D5')
B=ROOT/'Builds/PALFIX2-20261102'
SLIM=ROOT/'Builds/WHEELMEM1-20261102/slim29/mods'
MODS=B/'palmerge2/mods'
EV=B/'evidence/render'
EV.mkdir(parents=True,exist_ok=True)

def compare(a,b,ids,ranks,permit_alpha):
    original_texture_to_image=anm.texture_to_image
    textures=OrderedDict()
    def cached_texture(obj, tex, palette=0):
        key=(id(obj),tex,palette)
        if key not in textures:
            textures[key]=original_texture_to_image(obj,tex,palette)
            if len(textures)>96: textures.popitem(last=False)
        else: textures.move_to_end(key)
        return textures[key]
    anm.texture_to_image=cached_texture
    ia={x['id']:x['index'] for x in anm.list_animations(a)}
    ib={x['id']:x['index'] for x in anm.list_animations(b)}
    missing=sorted(set(ids)-ia.keys() | (set(ids)-ib.keys()))
    r={'missing_ids':missing,'samples':0,'position_or_size_differences':0,'rgb_differing_pixels':0,'alpha_differing_pixels':0,'max_alpha_difference':0,'rgba_differing_samples':0,'ids':sorted(ids),'ranks':ranks}
    for aid in sorted(set(ids)&ia.keys()&ib.keys()):
        times=sorted(set(anm.frame_times(a,ia[aid]))|set(anm.frame_times(b,ib[aid])))
        for t in times:
            for rank in range(ranks):
                x,xp=gate.pose(a,ia[aid],t,rank); y,yp=gate.pose(b,ib[aid],t,rank);r['samples']+=1
                if xp!=yp or x.size!=y.size:
                    r['position_or_size_differences']+=1;continue
                p=np.asarray(x,dtype=np.int16);q=np.asarray(y,dtype=np.int16)
                d=np.abs(p-q);rgb=np.any(d[:,:,:3]!=0,axis=2);al=d[:,:,3]
                r['rgb_differing_pixels']+=int(rgb.sum());r['alpha_differing_pixels']+=int((al!=0).sum());r['max_alpha_difference']=max(r['max_alpha_difference'],int(al.max(initial=0)))
                r['rgba_differing_samples']+=int(bool(rgb.any() or (al!=0).any()))
    anm.texture_to_image=original_texture_to_image
    r['pass']=not (missing or r['position_or_size_differences'] or r['rgb_differing_pixels'] or (r['alpha_differing_pixels'] and (not permit_alpha or r['max_alpha_difference']>1)))
    return r

def main():
    rows={}; build=json.loads((B/'evidence/build.json').read_text()); ok=True
    for key in build['changed_banks']:
        mod,bank=key.split('/'); target=(MODS/mod/base.REL/bank).read_bytes(); old=base.bank_path(mod,bank).read_bytes(); slim=(SLIM/mod/base.REL/bank).read_bytes()
        row={}
        for post in (False,True):
            a,b,c=(anm.load(gate.replay_member(x,'banner,grips') if post else x) for x in (old,target,slim))
            ai={x['id'] for x in anm.list_animations(a)};bi={x['id'] for x in anm.list_animations(b)}
            ranks=len(a.palettes)
            existing=compare(a,b,ai-{21,27},ranks,False)
            existing['extra_ids']=sorted(bi-ai);existing['pass'] &= not existing['extra_ids']
            art=compare(c,b,{21,27},ranks,mod=='D1C_Unique_2909')
            row['postinstall' if post else 'staged']={'test28_existing':existing,'slim29_hurt':art}
            ok &= existing['pass'] and art['pass']
        rows[key]=row
        (EV/(mod+'-'+bank+'.json')).write_text(json.dumps(row,indent=1)+'\n')
        print(key,'PASS' if all(x['test28_existing']['pass'] and x['slim29_hurt']['pass'] for x in row.values()) else 'FAIL',flush=True)
    (EV/'summary.json').write_text(json.dumps({'pass':bool(ok),'banks':len(rows)},indent=1)+'\n')
    return 0 if ok else 1
if __name__=='__main__': raise SystemExit(main())
