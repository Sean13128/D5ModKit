"""Preapply the installer's Quest Shop banner repack and preserve TEST28 image counts.

Blank unused texture pages are appended where banner_layout compacted the atlas.
Run on a fresh output directory; source bundle is never modified.
"""
from __future__ import annotations
import copy, hashlib, json, shutil, sys
from pathlib import Path
import numpy as np
KIT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(KIT),str(KIT/'tools')]
import d1cmotion2_base as base
from d5lib import anm, ownanim
from palfix1_build import pixels
ROOT=Path('/Volumes/Data/Projects/D5/Builds/PALFIX2-20261102')
SRC=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'palmerge2'
DST=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/'palmerge2-banner'

def main():
    if DST.exists(): raise SystemExit('refusing to overwrite existing output')
    shutil.copytree(SRC,DST)
    receipt={}
    for mod,banks in base.manifest()['banks'].items():
        if not mod.startswith('D1C_Unique_'): continue
        for bank in banks:
            path=DST/'mods'/mod/base.REL/bank
            a=anm.load(path); old=anm.load(path); t28=anm.load(base.bank_path(mod,bank))
            orig=len(t28.textures)
            changed=ownanim.banner_layout(a)
            packed=len(a.textures)
            assert changed and packed<=orig,(mod,bank,packed,orig)
            assert len(a.block.cells)==len(old.block.cells)
            assert all(np.array_equal(pixels(old,x),pixels(a,y)) for x,y in zip(old.block.cells,a.block.cells)
                       if x.w and x.h and x.tex<len(old.textures)),(mod,bank,'cell pixels')
            assert all(np.array_equal(anm.get_palette(a,p),anm.get_palette(old,p)) for p in range(len(a.palettes)))
            moved=sum(vars(x)!=vars(y) for x,y in zip(old.block.cells,a.block.cells))
            while len(a.textures)<orig:
                i=len(a.textures); tex=copy.deepcopy(t28.textures[i]); tex.data=bytes(len(tex.data))
                a.textures.append(tex); a.block.texture_infos.append(copy.deepcopy(t28.block.texture_infos[i]))
            assert not ownanim.banner_layout(a),(mod,bank,'not idempotent')
            assert len(a.textures)==orig and len(a.palettes)==len(t28.palettes)
            raw=a.to_bytes(); path.write_bytes(anm.lzs_compress(raw))
            assert anm.load(path).to_bytes()==raw
            receipt[f'{mod}/{bank}']={'textures_before':orig,'textures_packed':packed,'textures_padded':orig-packed,
                 'final_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'moved_cells':moved,'cells':len(old.block.cells),'cell_pixels_identical':True,
                 'palette_images_identical':True,'banner_idempotent':True}
            print(mod,bank,receipt[f'{mod}/{bank}'],flush=True)
    (ROOT/'evidence'/'banner-proof.json').write_text(json.dumps(receipt,indent=1)+'\n')
if __name__=='__main__':main()
