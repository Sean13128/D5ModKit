"""D1CMOTION3: rebuild the two D1C class packs' hurt slot onto the **TEST28** base.

D1CMOTION2 built these from `Local/kit-backups/20261101-live28/kit/mods`, a backup taken before
TEST27 was installed (TEST26), which silently dropped the TEST27 lifter fix and the TEST28 walk
from the shipped banks. This driver takes its base from `tools/d1cmotion2_base.py` only, and the
base banks are asserted against `tools/test28-base.json` (TEST28 as installed) before the splice
and again by the splice itself.

  1. rebuild both packs from source with the shared lift / walk / hurt row
     (`tools/pt1030_rebuild_d1c.py --shared-lift --shared-walk --shared-damage`);
  2. copy the TEST28 pack folder whole and graft only 21/27/65003/65004 into its four banks.

usage: d1cmotion2_classes.py [--work DIR] [--out DIR]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(HERE))
import d1cmotion2_base as base  # noqa: E402

OUT = base.ROOT / 'Builds/D1CMOTION2-20261101/mods'
WORK = Path('/Volumes/Data/ai-tmp/hermes/d1cmotion3/classes')
PACKS = (('D1C_Class_11390', 11390), ('D1C_Class_11400', 11400))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', default=str(WORK))
    ap.add_argument('--out', default=str(OUT))
    ap.add_argument('--skip-rebuild', action='store_true', help='reuse an existing rebuild in --work')
    args = ap.parse_args()
    work, out = Path(args.work), Path(args.out)
    n = base.require_base_set([m for m, _ in PACKS])
    print(f'base pins OK: {n} class banks at {base.class_base()}', flush=True)
    env = dict(os.environ, D5_KIT=str(KIT), PYTHONPATH=str(KIT))
    cmd = [sys.executable, str(HERE / 'pt1030_rebuild_d1c.py'), '--batch', 'humanoids',
           '--work', str(work), '--shared-lift', '--shared-walk', '--shared-damage']
    for _, registry in PACKS:
        cmd += ['--only', str(registry)]
    if args.skip_rebuild:
        print('reusing rebuild in', work, flush=True)
    else:
        subprocess.run(cmd, check=True, env=env, cwd=str(KIT))
    receipt = json.loads((work / str(PACKS[0][1]) / 'out' / 'source-import-receipt.json').read_text())
    print('rebuild receipt keys:', sorted(receipt)[:8], flush=True)
    for mod, registry in PACKS:
        source = work / str(registry) / 'out' / 'native-mods' / mod
        if not source.is_dir():
            raise SystemExit(f'{mod}: rebuilt pack missing at {source}')
        dest = out / mod
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(base.class_base() / mod, dest)
        for path in sorted((dest / base.REL).glob('anm*.lzs')):
            staged = source / base.REL / path.name
            if not staged.is_file():
                continue  # unaffected bank: stays byte-identical to TEST28
            if path.name not in base.manifest()['banks'].get(mod, {}):
                continue
            want = base.expected(mod, path.name)
            subprocess.run([sys.executable, str(HERE / 'd1cmotion2_splice.py'),
                            str(base.class_base() / mod / base.REL / path.name),
                            str(staged), str(path), '--base-sha256', want], check=True)
        print(f'{mod}: spliced {sorted(base.manifest()["banks"][mod])}', flush=True)


if __name__ == '__main__':
    main()
