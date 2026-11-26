#!/usr/bin/env python3
"""D1CLIST3: who calls Disgaea 1 voice list 3 (opcode 0x87, slot 3), offline, read-only.

Control: the VOICEMAP1 joiner must give slots 0/1/2 = 509/75/46 of 632 calls, else exit 1.
Then: the slot-3 call sites, the events that call those events (opcode 0x12 = call event, 3-byte LE id),
which skills those are, and which voiced D1C characters learn them.
Run: D5Modkit/.venv-macos/bin/python -I tools/d1c_list3_callers.py OUT.json
"""
import bisect, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path('/Volumes/Data/Projects/D5')
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import d1cvoice, d1skill

spec = importlib.util.spec_from_file_location('ctx', ROOT / 'Subprojects/Engine-Extensions/voices/voicemap1/d1_script_context.py')
ctx = importlib.util.module_from_spec(spec); spec.loader.exec_module(ctx)
ctx.ROOT = ROOT
ctx.SOURCE = ROOT / 'Disgaea Source/Disgaea 1 Complete Switch (01004B100AF18000)/extracted/romfs/data/script.dat'
r = ctx.survey()
counts = {int(k): v for k, v in r['slot_counts'].items()}
control = counts.get(0) == 509 and counts.get(1) == 75 and counts.get(2) == 46 and len(r['calls']) == 632
print('control (509/75/46 of 632):', 'PASS' if control else 'FAIL', counts, len(r['calls']))
if not control:
    sys.exit(1)

d = ctx.SOURCE.read_bytes()
n = struct.unpack_from('<I', d)[0]
offs = list(struct.unpack_from(f'<{n}I', d, 4)); ids = struct.unpack_from(f'<{n}I', d, 4 + 4 * n)
base = 4 + 8 * n; offs.append(len(d) - base); starts = [base + o for o in offs]
failed = {f['event'] for f in r['framing_failures']}
callers = {}                       # event id -> events that call it with opcode 0x12
for i, eid in enumerate(ids):
    if eid in failed:
        continue
    q, e = starts[i], starts[i + 1]
    while q < e:
        op, ln = d[q:q + 2]
        if op == 0x12 and ln == 3:
            callers.setdefault(int.from_bytes(d[q + 2:q + 5], 'little'), []).append(eid)
        q += 3 + struct.unpack_from('<H', d, q + 1)[0] if op == 7 else 2 + ln
slot3 = [c for c in r['calls'] if c['slot'] == 3]
sites = [dict(c, called_by=sorted(callers.get(c['event'], []))) for c in slot3]

sys.path.insert(0, str(ROOT / 'Research/source-packs/d1c'))
spec = importlib.util.spec_from_file_location('src', ROOT / 'Research/source-packs/d1c/d1c_source.py')
src = importlib.util.module_from_spec(spec); spec.loader.exec_module(src)
names = {s['id']: s['name'] for s in d1skill.read_table(src.member(40), 'd1hd')['rows']}
skills = sorted({e - 2000000 for s in sites for e in s['called_by'] if 2000000 < e < 2050000} |
                {e - 2050000 for s in sites for e in s['called_by'] if 2050000 <= e < 2100000})
raw = src.member(43)
vmap = json.loads((Path(__file__).resolve().parents[1] / 'd5lib/importers/d1c-voice-map.json').read_text())
chars = []
for folder, m in vmap['mods'].items():
    if m.get('sound_effect'):
        continue
    learn = [x['skill'] for x in d1skill.learnset(raw, m['source_id'])['learn']]
    only3 = [k for k, c in m['clips'].items() if c['slots'] == [3]]
    chars.append(dict(mod=folder, name=d1cvoice.voice_label(m, f'd1c-voice-map.mods.{folder}'), source_id=m['source_id'], learns_list3_skill=sorted(set(skills) & set(learn)),
                      list3_only_clips=only3))
out = dict(control=dict(slot_counts=counts, calls=len(r['calls']), passed=control), slot3_call_sites=sites,
           skills_reaching_list3=[dict(id=s, name=names.get(s)) for s in skills], characters=chars,
           framing_failures_excluded=sorted(failed))
Path(sys.argv[1]).write_text(json.dumps(out, indent=1) + '\n')
print(json.dumps(sites)); print([(s, names.get(s)) for s in skills])
for c in chars:
    if c['list3_only_clips'] or c['learns_list3_skill']:
        print(c['name'], c['learns_list3_skill'], c['list3_only_clips'])
