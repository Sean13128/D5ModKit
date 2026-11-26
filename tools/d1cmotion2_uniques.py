"""D1CMOTION3: build the 17 unique packs with the source hurt reaction onto the **TEST28** base.

Same method as UNIQWALK1 (art only, recorded leases, never run lease allocation). TEST28's unique
banks already carry UNIQWALK1's walk 11/17 and lift 1101/1107/1131/1137, so only the hurt slot
(21/27 plus the preserved held copy 65003/65004) is grafted here, on top of the unmodified TEST28
bank.

D1CMOTION2 took its base from `Local/kit-backups/20261101-live28/kit/mods` — a backup taken before
TEST27 was installed (TEST26) — so its banks lost the TEST28 walk and lift. This driver's base is
`tools/d1cmotion2_base.py` (`Builds/UNIQWALK1-20261101/mods`), pinned by `tools/test28-base.json`
and re-checked here and inside the splice; `Local/kit-backups/**` is never a base.

  python tools/d1cmotion2_uniques.py [ids...]
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path('/Volumes/Data/Projects/D5')
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(KIT))
import d1cmotion2_base as base  # noqa: E402
os.environ['D5_KIT'] = str(KIT)
sys.path.insert(0, str(ROOT / 'Research/source-packs/d1c/batches'))
import build_uniques_batch as ub          # noqa: E402
from tools.pt1030_rebuild_d1c import add_shared_lift, add_shared_walk, add_shared_damage  # noqa: E402
from d5lib import nativeimports            # noqa: E402

B = ub.BATCHES
SCRATCH = Path('/Volumes/Data/ai-tmp/hermes/d1cmotion3/uniq')
OUT = ROOT / 'Builds/D1CMOTION2-20261101/mods'
IDS = [2300, 2301, 2302, 2410, 2907, 2909, 2910, 2911, 2912, 2914, 2915, 3060, 3150, 3160, 4, 5, 5590]
rows = {int(r['id']): r for r in json.loads((B / 'uniques.json').read_text())['rows']}
leases = json.loads((B / 'unique-leases.json').read_text())['leased']
donors = {int(r['id']): r for r in json.loads((B / 'unique-donors.json').read_text())['rows']}
skills = json.loads((B / 'unique-skills.json').read_text())['characters']
tables, table_sha = ub.bb.table_rows()
tables = {r['id']: r for r in tables}
prepare = ub.bb.prepare
build = nativeimports.build_entry
receipt_current = None


def prepare_motion(spec, packet_dir):
    global receipt_current
    manifest, receipt = prepare(spec, packet_dir)
    add_shared_lift(spec, packet_dir, manifest, receipt)
    add_shared_walk(spec, packet_dir, manifest, receipt)
    add_shared_damage(spec, packet_dir, manifest, receipt)
    receipt_current = receipt
    return manifest, receipt


def build_motion(**kwargs):
    kwargs['source_times'] = receipt_current.get('row_times')
    return build(**kwargs)


ub.bb.prepare = prepare_motion
nativeimports.build_entry = build_motion
SCRATCH.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
REL = base.REL
selected = [int(x) for x in sys.argv[1:]] or IDS
n = base.require_base_set([f'D1C_Unique_{u}' for u in selected])
print(f'base pins OK: {n} unique banks at {base.unique_base()}', flush=True)
for uid in selected:
    lease = leases[str(uid)]
    row = rows[uid]
    donor = donors.get(uid) or dict(donor=lease['donor'], kind=lease['kind'], donor_name=str(lease['donor']))
    skill = skills.get(str(uid), {'skills': []}) if uid in donors else {'skills': []}
    ub.build_one(row, int(lease['identity']), int(lease['physical']), tables[uid], table_sha, skill, donor,
                 SCRATCH, (lease['help_id'], lease['quest_id'], lease['quest_slot']))
    mod = f'D1C_Unique_{uid}'
    source = SCRATCH / 'build' / str(uid) / 'out' / 'native-mods' / mod
    dest = OUT / mod
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(base.unique_base() / mod, dest)
    changed = []
    for i in (int(lease['physical']), int(lease['physical']) + 1):
        name = f'anm{i:05d}.lzs'
        staged = source / REL / name
        if not staged.exists():
            print(f'{uid}: missing rebuilt {name}, skipped', flush=True)
            continue
        target = dest / REL / name
        want = base.expected(mod, name)
        subprocess.run([sys.executable, str(KIT / 'tools/d1cmotion2_splice.py'),
                        str(base.unique_base() / mod / REL / name), str(staged), str(target),
                        '--base-sha256', want], check=True)
        changed.append(name)
    print(f'{uid}: changed {changed}', flush=True)
