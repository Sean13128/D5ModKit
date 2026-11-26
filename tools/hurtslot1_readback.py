"""Compare sandbox members against member-local candidate and PALMERGE2B replays."""
import argparse,hashlib,json,sys
from pathlib import Path
KIT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(KIT),str(KIT/'tools')]
from d5lib import anm
import d1cmotion2_base as base, striderlift_render_diff as gate
from hurtslot1_build import BASE,OUT
p=argparse.ArgumentParser(); p.add_argument('variant',choices=['hurtslot','hurtslot_keepcarry']); args=p.parse_args()
data=Path('/Volumes/Data/ai-tmp/codex/hurtslot1/gates/sandbox/game/Data/Anime')
rows=[]
for mod,names in base.manifest()['banks'].items():
 for bank in names:
  rel=Path(mod)/base.REL/bank; mode='banner,grips' if 'Unique' in mod else 'grips'
  actual=anm.load_from_archive(bank,lang='JP',data_dir=str(data))
  candidate=anm.load(gate.replay_member((OUT/args.variant/'mods'/rel).read_bytes(),mode))
  baseline=anm.load(gate.replay_member((BASE/rel).read_bytes(),mode))
  row={'bank':str(rel),'matches_replay':actual.to_bytes()==candidate.to_bytes(),
       'installed_palettes':len(actual.palettes),'baseline_palettes':len(baseline.palettes),
       'installed_headers':len(actual.palettes)+len(actual.textures),'baseline_headers':len(baseline.palettes)+len(baseline.textures)}
  row['pass']=row['matches_replay'] and row['installed_palettes']==row['baseline_palettes'] and row['installed_headers']==row['baseline_headers']
  rows.append(row);print(rel,row['pass'],flush=True)
(OUT/'install-proof'/f'{args.variant}-readback.json').write_text(json.dumps({'pass':all(r['pass'] for r in rows),'rows':rows},indent=2)+'\n')
raise SystemExit(0 if all(r['pass'] for r in rows) else 1)
