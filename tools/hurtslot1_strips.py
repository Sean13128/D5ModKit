from pathlib import Path
import sys,json
sys.path.insert(0,'/Volumes/Data/Projects/D5/Local/Worktrees/hurtslot1')
from d5lib import anm,gamefs,d4unique,sprites,choreo,skills
from PIL import Image,ImageDraw
R=Path('/Volumes/Data/Projects/D5'); S=Path('/Volumes/Data/ai-tmp/dd2-snapshot-20261029-1335'); OUT=R/'Builds/HURTSLOT1-20261102/inventory'; B=R/'Builds/HURTSLOT1-20261102'; BASE=R/'Builds/PALFIX2-20261102/palmerge2b/mods'
fs=gamefs.GameFS(str(S/'game'),backup_resolver=d4unique.Originals(S/'kit/state/games/Disgaea_5_Complete-d8040a88')); sc=skills.vanilla_scripts(fs)
def pack(base,folder,num):return sprites.preview_file(fs,anm.load((base/f'{folder}/files/Anime/ANM_HI_JP.dat/anm{num:05}.lzs').read_bytes()))
def draw(a,aid,t):
 idx=anm._resolve_anim(a,('id',aid)); items=anm.evaluate(a,idx,t,nested=True); img,origin=anm.render_items(a,items,palette_index=0); bb=img.getchannel('A').getbbox();return (img.crop(bb) if bb else None)
def paste(out,im,x,y,w,h):
 if im:
  im.thumbnail((w,h),Image.Resampling.NEAREST);out.paste(im,(x+(w-im.width)//2,y+h-im.height),im)
tls={n:choreo.simulate(sc.ev,sc.root_of(n),choreo.Context()) for n in (100,200,502)};meta={}
for variant in ('hurtslot','hurtslot_keepcarry'):
 for name,folder,num in [('strider','D1C_Class_11390',1540),('gordon','D1C_Unique_4',516)]:
  a=pack(B/variant/'mods',folder,num); source=pack(BASE,folder,num)
  for view in (1,7):
   for sid,tl in tls.items():
    spans=tl.motions(choreo.TARGET); samples=[]
    for start,end,m,_ in spans:
     for t in sorted(set([start, (start+end-1)//2, end-1])):
      st=tl.scene(t)['actors'][choreo.TARGET];samples.append((t,st['motion'],st['motion_time']))
    width=max(len(samples),7)*106;out=Image.new('RGB',(width,410),(35,36,42));d=ImageDraw.Draw(out)
    d.text((4,2),f'{variant} {name} skill {sid} view {view} | Timeline.scene(t): t / motion / local time',fill='white')
    for j,(t,m,mt) in enumerate(samples):
     d.text((j*106+3,23),f'{t} / {m} / {mt}',fill='white');paste(out,draw(a,m*10+view,mt),j*106,43,104,150)
    d.text((4,205),'PALMERGE2B D1C 21/27 source keys (0, 6, 12, 18, 24, 30, 35)',fill='white')
    for j,t in enumerate((0,6,12,18,24,30,35)):
     d.text((j*106+3,224),f'{t}',fill='white');paste(out,draw(source,20+view,t),j*106,244,104,150)
    filename=f'{variant}-{name}-{sid}-{view}.png';out.save(OUT/filename);meta[filename]=samples;print(filename,flush=True)
(OUT/'strip-samples.json').write_text(json.dumps(meta,indent=2)+'\n');fs.reset()
