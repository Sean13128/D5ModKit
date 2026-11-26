import json,sys
from pathlib import Path
from PIL import Image,ImageDraw
root=Path('/Volumes/Data/Projects/D5');kit=root/'Local/Worktrees/striderlift4';sys.path[:0]=[str(kit),str(kit/'tools')]
from striderlift_render_diff import read,pose
from d5lib import anm
candidate=Path(sys.argv[1]);info=json.loads((root/'Builds/D1CWALK1-20261101/install-proof/proofs/uniques-packcheck.json').read_text());w,h=126,190; left=150; top=36
out=Image.new('RGB',(left+6*w,top+len(info)*h),(40,40,44));d=ImageDraw.Draw(out)
for col,s in enumerate(['FRONT stand','FRONT walk t16','FRONT lift','BACK stand','BACK walk t16','BACK lift']):d.text((left+col*w+3,5),s,fill='white')
for row,(uid,rec) in enumerate(info.items()):
 d.text((4,top+row*h+10),uid+' '+rec['name'],fill='white');path=candidate/('D1C_Unique_'+uid)/'files/Anime/ANM_HI_JP.dat'/rec['banks'][0]
 if not path.exists():d.text((left,top+row*h+10),'MISSING',fill='red');continue
 a,_=read(path);ids={x['id']:x['index'] for x in anm.list_animations(a)}
 for col,(idx,t) in enumerate([(1001,0),(11,16),(1101,0),(1007,0),(17,16),(1107,0)]):
  im,_=pose(a,ids[idx],t,0);im.thumbnail((w-6,h-10));x=left+col*w+(w-im.width)//2;y=top+row*h+h-5-im.height;out.paste(im,(x,y),im)
 for x in range(7):d.line((left+x*w,top+row*h,left+x*w,top+(row+1)*h),fill=(65,65,70))
 d.line((0,top+(row+1)*h-1,out.width,top+(row+1)*h-1),fill=(70,70,75))
p=root/'Builds/UNIQWALK1-20261101/review/contact-all.png';p.parent.mkdir(parents=True,exist_ok=True);out.save(p);print(p)
