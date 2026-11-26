import hashlib,json,subprocess,sys,shutil
from pathlib import Path
root=Path('/Volumes/Data/Projects/D5');kit=root/'Local/Worktrees/striderlift4';sys.path.insert(0,str(kit));from d5lib import anm
mods=root/'Builds/UNIQWALK1-20261101/mods';old=root/'Local/kit-backups/20261101-live27/kit/mods';out=root/'Builds/UNIQWALK1-20261101';proof=out/'install-proof/proofs';proof.mkdir(parents=True,exist_ok=True);work=Path('/Volumes/Data/ai-tmp/codex/uniqwalk1/gate');art=root/'Assets/Forge art library/Disgaea 1 Complete HD';info=json.loads((root/'Builds/D1CWALK1-20261101/install-proof/proofs/uniques-packcheck.json').read_text())
def normalized(path):
 a=anm.load(path)
 assert len(a.blocks)==1
 a.block.id=0
 return hashlib.sha256(a.to_bytes()).hexdigest()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(script,args,log):
 with log.open('w') as f:return subprocess.run([sys.executable,str(script),*map(str,args)],stdout=f,stderr=subprocess.STDOUT).returncode
cache={};report={}
for uid,rec in info.items():
 print('BEGIN',uid,rec['name'],flush=True);folder='D1C_Unique_'+uid+'/files/Anime/ANM_HI_JP.dat';s={'name':rec['name'],'body':rec['body'],'banks':{},'source':{}};report[uid]=s
 for bank in rec['banks']:
  o=old/folder/bank;n=mods/folder/bank
  if not o.exists() or not n.exists():s['banks'][bank]={'error':'missing bank'};continue
  oldsha=sha(o);newsha=sha(n)
  if oldsha==newsha:s['banks'][bank]={'baseline_sha256':oldsha,'candidate_sha256':newsha,'method':'byte-identical'};continue
  key=(normalized(o),normalized(n));entry={'baseline_sha256':oldsha,'candidate_sha256':newsha,'baseline_normalized_sha256':key[0],'candidate_normalized_sha256':key[1]}
  if key not in cache:
   result=proof/('render-'+uid+'-'+bank+'.json'); previous=json.loads(result.read_text()) if result.exists() else {}; rc=0 if previous.get('baseline_sha256')==oldsha and previous.get('rebuilt_sha256')==newsha else run(kit/'tools/uniqwalk1_render_diff.py',[o,n,result,'--exempt',11,17,1101,1107,1131,1137,'--baseline-label','TEST27'],proof/('render-'+uid+'-'+bank+'.log'))
   if not result.exists():entry['error']='render tool exit '+str(rc);s['banks'][bank]=entry;continue
   d=json.loads(result.read_text());allowed={(1011,47),(1017,47),(5001,6),(5001,7)};bad=[x for x in d['differences'] if (x['id'],x['time']) not in allowed];ok=not(d['missing_ids'] or d['extra_ids'] or bad);cache[key]={'receipt':str(result.relative_to(out)),'samples':d['samples_compared'],'rank_equivalence':d['rank_equivalence'],'allowed_differences':len(d['differences'])-len(bad),'unexpected_differences':len(bad),'pass':ok}
  entry.update(cache[key]);entry['method']='rendered or equivalent after normalizing ANM block id';s['banks'][bank]=entry
 # Explicit source receipts per unique; second bank is covered by equal normalized hashes only.
 b=mods/folder/rec['banks'][0]
 for typ in ('walk','lift'):
  target=proof/(typ+'-'+uid+'.json');rc=run(kit/'tools'/('striderlift_'+typ+'_check.py'),['--art',art,'--pack',b,'--body',rec['body'],'--label',rec['name'],'--out',target],proof/(typ+'-'+uid+'.log'))
  if not target.exists():s['source'][typ]={'pass':False,'error':'check exit '+str(rc)};continue
  d=json.loads(target.read_text());valid=d['pass'] and all((abs(x['foot_line_delta'])<=1 if typ=='lift' else x['key_times']==x['source_times']) for x in d['views'].values());s['source'][typ]={'pass':valid,'receipt':str(target.relative_to(out))}
 s['pass']=all((v.get('method')=='byte-identical' or v.get('pass') is True) for v in s['banks'].values()) and all(v.get('pass') is True for v in s['source'].values());(proof/'gate-summary.json').write_text(json.dumps(report,indent=2)+'\n');print('DONE',uid,s['pass'],flush=True)
print('ALL DONE',len(report),'pass',sum(v['pass'] for v in report.values()),flush=True)
