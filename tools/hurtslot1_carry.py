from pathlib import Path
import sys
sys.path.insert(0,'/Volumes/Data/Projects/D5/Local/Worktrees/hurtslot1')
from d5lib import anm,gamefs,d4unique,sprites
from PIL import Image,ImageDraw
R=Path('/Volumes/Data/Projects/D5');S=Path('/Volumes/Data/ai-tmp/dd2-snapshot-20261029-1335'); B=R/'Builds/HURTSLOT1-20261102'; OUT=B/'inventory'
fs=gamefs.GameFS(str(S/'game'),backup_resolver=d4unique.Originals(S/'kit/state/games/Disgaea_5_Complete-d8040a88'))
def load(v):return sprites.preview_file(fs,anm.load((B/v/'mods/D1C_Class_11390/files/Anime/ANM_HI_JP.dat/anm01540.lzs').read_bytes()))
def frame(a,id):
 im,origin=anm.render_items(a,anm.evaluate(a,anm._resolve_anim(a,('id',id)),0,nested=True),palette_index=0); bb=im.getchannel('A').getbbox();return im.crop(bb) if bb else None
def put(out,im,x,y):
 if im:out.paste(im,(x-im.width//2,y-im.height),im)
out=Image.new('RGB',(960,700),(35,36,42));d=ImageDraw.Draw(out)
for col,v in enumerate(('hurtslot','hurtslot_keepcarry')):
 a=load(v)
 for row,view in enumerate((1,7)):
  x=col*480+240;y=row*350+340
  put(out,frame(a,1130+view),x,y);put(out,frame(a,1060+view),x,y-130)
  d.text((col*480+4,row*350+4),f'{v}: {"front" if view==1 else "back"}',fill='white')
  d.text((col*480+4,row*350+20),'106 above 113, illustrative placement',fill='white')
out.save(OUT/'carried-illustrative.png');fs.reset()
