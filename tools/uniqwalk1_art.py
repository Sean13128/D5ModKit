"""UNIQWALK1: rebuild unique art using recorded leases; never run lease allocation."""
import json, os, shutil, subprocess, sys
from pathlib import Path
ROOT=Path('/Volumes/Data/Projects/D5')
KIT=Path(__file__).resolve().parents[1]
os.environ['D5_KIT']=str(KIT)
sys.path.insert(0,str(KIT))
sys.path.insert(0,str(ROOT/'Research/source-packs/d1c/batches'))
import build_uniques_batch as ub
from tools.pt1030_rebuild_d1c import add_shared_lift, add_shared_walk, add_shared_damage
from d5lib import nativeimports
B=ub.BATCHES
SCRATCH=Path('/Volumes/Data/ai-tmp/codex/uniqwalk1/art')
OUT=ROOT/'Builds/UNIQWALK1-20261101/mods'
BASE=ROOT/'Local/kit-backups/20261101-live27/kit/mods'
IDS=[2300,2301,2302,2410,2907,2909,2910,2911,2912,2914,2915,3060,3150,3160,4,5,5590]
rows={int(r['id']):r for r in json.loads((B/'uniques.json').read_text())['rows']}
leases=json.loads((B/'unique-leases.json').read_text())['leased']
donors={int(r['id']):r for r in json.loads((B/'unique-donors.json').read_text())['rows']}
skills=json.loads((B/'unique-skills.json').read_text())['characters']
tables, table_sha=ub.bb.table_rows(); tables={r['id']:r for r in tables}
prepare=ub.bb.prepare; build=nativeimports.build_entry
receipt_current=None

def prepare_motion(spec, packet_dir):
 global receipt_current
 manifest, receipt=prepare(spec,packet_dir)
 if not os.environ.get('UNIQWALK_PLAIN'):
  add_shared_lift(spec,packet_dir,manifest,receipt)
  add_shared_walk(spec,packet_dir,manifest,receipt)
  if os.environ.get('UNIQWALK_DAMAGE'):
   add_shared_damage(spec,packet_dir,manifest,receipt)
 receipt_current=receipt
 return manifest,receipt

def build_motion(**kwargs):
 if not os.environ.get('UNIQWALK_PLAIN'):
  kwargs['source_times']=receipt_current.get('row_times')
 return build(**kwargs)

ub.bb.prepare=prepare_motion
nativeimports.build_entry=build_motion
SCRATCH.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
for id in (list(map(int,sys.argv[1:])) if len(sys.argv)>1 else IDS):
 lease=leases[str(id)]; row=rows[id]
 donor=donors.get(id) or dict(donor=lease['donor'],kind=lease['kind'],donor_name=str(lease['donor']))
 skill=skills.get(str(id),{'skills':[]}) if id in donors else {'skills':[]}
 result=ub.build_one(row,int(lease['identity']),int(lease['physical']),tables[id],table_sha,skill,donor,SCRATCH,(lease['help_id'],lease['quest_id'],lease['quest_slot']))
 mod=f'D1C_Unique_{id}'; source=SCRATCH/'build'/str(id)/'out'/'native-mods'/mod
 dest=(SCRATCH/'plain-mods' if os.environ.get('UNIQWALK_PLAIN') else OUT)/mod
 if dest.exists(): shutil.rmtree(dest)
 shutil.copytree(BASE/mod,dest)
 relative=Path('files/Anime/ANM_HI_JP.dat')
 for i in (int(lease['physical']),int(lease['physical'])+1):
  name=f'anm{i:05d}.lzs'
  if os.environ.get('UNIQWALK_PLAIN'):
   shutil.copy2(source/relative/name,dest/relative/name)
  else:
   subprocess.run([sys.executable, str(KIT/'tools/uniqwalk1_splice.py'), str(BASE/mod/relative/name), str(source/relative/name), str(dest/relative/name)], check=True)
 print(f'{id}: {source} -> {dest}',flush=True)
