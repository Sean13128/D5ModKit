"""Render PALFIX2B post-installer replay against TEST28 and SLIM29."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import anm
import d1cmotion2_base as base
import palfix2_render as render
import striderlift_render_diff as gate
B=Path('/Volumes/Data/Projects/D5/Builds/PALFIX2-20261102')
EV=B/'evidence/palfix2b-render';EV.mkdir(parents=True,exist_ok=True)
rows={}
for key in json.loads((B/'evidence/palfix2b-build.json').read_text())['changed_banks']:
 mod,bank=key.split('/')
 paths=[base.bank_path(mod,bank),B/'palmerge2b/mods'/mod/base.REL/bank,render.SLIM/mod/base.REL/bank]
 a,b,c=[anm.load(gate.replay_member(p.read_bytes(),'banner,grips')) for p in paths]
 ai={x['id'] for x in anm.list_animations(a)};bi={x['id'] for x in anm.list_animations(b)}
 existing=render.compare(a,b,ai-{21,27},len(a.palettes),False);existing['extra_ids']=sorted(bi-ai);existing['pass'] &= not existing['extra_ids']
 hurt=render.compare(c,b,{21,27},len(a.palettes),mod=='D1C_Unique_2909')
 row={'test28_existing':existing,'slim29_hurt':hurt};rows[key]=row
 (EV/(mod+'-'+bank+'.json')).write_text(json.dumps(row,indent=1)+'\n')
 print(key,'PASS' if existing['pass'] and hurt['pass'] else 'FAIL',flush=True)
summary={'pass':all(x['test28_existing']['pass'] and x['slim29_hurt']['pass'] for x in rows.values()),'banks':len(rows)}
(EV/'summary.json').write_text(json.dumps(summary,indent=1)+'\n')
if not summary['pass']:raise SystemExit(1)
