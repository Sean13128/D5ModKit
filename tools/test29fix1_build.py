"""TEST29FIX1 driver: build TEST29b (params repair) and TEST29c (hurt only) from the TEST28 base.

Both candidates start from the pinned TEST28 base folders (tools/test28-base.json), never a kit
backup, and the only files that may differ from TEST28 are the 38 pinned banks.

  TEST29b  = the installed TEST29 content with table 9 repaired: the 42 alias keys per class bank
             point at a real (65003|65004, 0, -1) aux record instead of a bare id, so the engine
             reads start tick 0 and duration -1 as it does for every TEST28 nested key.
  TEST29c  = 21/27 only: the D1C hurt art, no preserved ids, no alias re-point (the fallback for a
             live A/B; the four stub aliases then draw the hurt body instead of the held picture).

usage: test29fix1_build.py <out bundle dir>
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
TEST29 = ROOT / 'Builds/D1CMOTION2-20261101/mods'
HERE = KIT / 'tools'
PY = sys.executable


def build_b(out):
    for mod, banks in base.manifest()['banks'].items():
        dest = out / mod
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(base.base_dir(mod) / mod, dest)
        for bank in banks:
            src29 = TEST29 / mod / base.REL / bank
            dst = dest / base.REL / bank
            assert dst.read_bytes() == base.bank_path(mod, bank).read_bytes(), dst
            probe = subprocess.run([PY, str(HERE / 'test29fix1_params.py'), str(src29),
                                    str(dst) + '.new'], capture_output=True, text=True)
            if probe.returncode == 0:
                Path(str(dst) + '.new').replace(dst)
                print(f'  b {mod}/{bank}: {probe.stdout.strip().splitlines()[0]}', flush=True)
            elif 'no misaligned preserved-id triple' in (probe.stderr + probe.stdout):
                shutil.copy2(src29, dst)          # nothing to repair: TEST29 content as-is
                print(f'  b {mod}/{bank}: unchanged from TEST29 (no alias triples)', flush=True)
            else:
                raise SystemExit(probe.stdout + probe.stderr)


def build_c(out):
    for mod, banks in base.manifest()['banks'].items():
        dest = out / mod
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(base.base_dir(mod) / mod, dest)
        for bank in banks:
            want = base.expected(mod, bank)
            subprocess.run([PY, str(HERE / 'd1cmotion2fix_splice.py'),
                            str(base.bank_path(mod, bank)),
                            str(TEST29 / mod / base.REL / bank),
                            str(dest / base.REL / bank), '--base-sha256', want, '--hurt-only'],
                           check=True, capture_output=True, text=True)
        print(f'  c {mod}: spliced {sorted(banks)}', flush=True)


def profile(out, name, desc):
    src = ROOT / 'Builds/D1CMOTION2-20261101/profile/LIVE5_TEST29'
    dst = out / 'profile' / name
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    shutil.copy2(src / 'load_order.json', dst / 'load_order.json')
    (dst / 'profile.json').write_text(json.dumps(
        {'name': name, 'separate_saves': False, 'description': desc}, indent=1))


def main():
    out = Path(sys.argv[1])
    n = base.require_base_set()
    print(f'TEST28 base asserted: {n} pinned banks', flush=True)
    b_dir = out / 'mods'
    c_dir = out / 'candidate-c' / 'mods'
    build_b(b_dir)
    profile(out, 'LIVE5_TEST29B',
            'TEST29 with the D1C hurt aux records repaired (table 9 triples) - 21/27 + 65003/65004')
    build_c(c_dir)
    profile(out / 'candidate-c', 'LIVE5_TEST29C',
            'D1C hurt on 21/27 only, no preserved ids (control build for the wheel freeze)')
    print('done', out)


if __name__ == '__main__':
    main()
