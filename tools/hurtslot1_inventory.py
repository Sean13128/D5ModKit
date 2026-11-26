from pathlib import Path
import sys,hashlib,json
sys.path.insert(0,'/Volumes/Data/Projects/D5/Local/Worktrees/hurtslot1')
from d5lib import anm,gamefs,d4unique,sprites
from PIL import Image,ImageDraw
R=Path('/Volumes/Data/Projects/D5'); S=Path('/Volumes/Data/ai-tmp/dd2-snapshot-20261029-1335'); O=R/'Builds/HURTSLOT1-20261102/inventory'; P=R/'Builds/PALFIX2-20261102/palmerge2b/mods'
fs=gamefs.GameFS(str(S/'game'),backup_resolver=d4unique.Originals(S/'kit/state/games/Disgaea_5_Complete-d8040a88'))
def read(rel): return anm.load((P/rel).read_bytes())
def bank(folder,n): return sprites.preview_file(fs,read(f'{folder}/files/Anime/ANM_HI_JP.dat/anm{n:05}.lzs'))
items=[('Warrior1010',sprites.preview_file(fs,anm.load(fs.read(sprites.sprite_vpath(fs,1010,'EN')))))]
for name,f,n in [('Strider1540','D1C_Class_11390',1540),('Strider1541','D1C_Class_11390',1541),('EDF1530','D1C_Class_11400',1530),('EDF1531','D1C_Class_11400',1531),('Gordon516','D1C_Unique_4',516),('Gordon517','D1C_Unique_4',517)]: items.append((name,bank(f,n)))
ids=[106]+list(range(114,127)); rec={}
for name,a in items:
 index={x['id']:x['index'] for x in anm.list_animations(a)}; out=Image.new('RGB',(len(ids)*130,2*180),(35,36,42));d=ImageDraw.Draw(out); rec[name]={}
 for row,view in enumerate([1,7]):
  for col,m in enumerate(ids):
   aid=m*10+view
   if aid not in index: rec[name][str(aid)]={'missing':True};continue
   ix=index[aid]; ts=anm.frame_times(a,ix); t=ts[0]; im,origin=anm.render_items(a,anm.evaluate(a,ix,t,nested=True),palette_index=0);bbox=im.getchannel('A').getbbox()
   if bbox:
    crop=im.crop(bbox); crop.thumbnail((120,145),Image.Resampling.NEAREST);out.paste(crop,(col*130+(130-crop.width)//2,row*180+170-crop.height),crop)
    h=hashlib.sha256(crop.tobytes()).hexdigest()[:12]
   else:h='blank'
   d.text((col*130+3,row*180+3),str(aid),fill='white');rec[name][str(aid)]={'times':ts,'origin':origin,'bbox':bbox,'hash':h}
 out.save(O/(name+'.png')); print(name,flush=True)
(O/'inventory.json').write_text(json.dumps(rec,indent=2))
fs.reset()
