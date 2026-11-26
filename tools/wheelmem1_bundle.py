"""WHEELMEM1 bundle finalizer: profiles + folder delta proof for PAD28 and SLIM29.

Both candidates ship the 19 TEST28 folders with only their 38 banks replaced.  This asserts
that (every other file byte-identical, only .lzs banks differ, and exactly the pinned 38), and
writes the LIVE5_PAD28 / LIVE5_SLIM29 profiles with TEST28's 188-entry order.

usage: python tools/wheelmem1_bundle.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
B = ROOT / 'Builds/WHEELMEM1-20261102'
LIVE_PROFILE = ROOT / 'Local/Installed D5ModKit/profiles/LIVE5_TEST28'
CANDIDATES = {'pad28': 'LIVE5_PAD28', 'slim29': 'LIVE5_SLIM29'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    order = json.loads((LIVE_PROFILE / 'load_order.json').read_text())
    assert len(order) == 188, len(order)
    ok = True
    report = {}
    for cand, prof in CANDIDATES.items():
        changed, identical, folders = [], 0, 0
        for mod, banks in base.manifest()['banks'].items():
            src = base.base_dir(mod) / mod
            dst = B / cand / 'mods' / mod
            folders += 1
            assert dst.is_dir(), dst
            rels = {p.relative_to(src) for p in src.rglob('*') if p.is_file()}
            assert rels == {p.relative_to(dst) for p in dst.rglob('*') if p.is_file()}, mod
            for rel in sorted(rels):
                a, b = src / rel, dst / rel
                if a.read_bytes() == b.read_bytes():
                    identical += 1
                else:
                    assert rel.suffix == '.lzs', (cand, mod, rel)
                    changed.append(f'{mod}/{rel.relative_to(base.REL)}')
        want = sorted(f'{m}/{b}' for m, banks in base.manifest()['banks'].items() for b in banks)
        good = sorted(changed) == want
        ok &= good
        report[cand] = {'folders': folders, 'files': identical + len(changed),
                        'identical': identical, 'changed': len(changed), 'match': good}
        print(f'{cand}: {folders} folders, {identical} files identical, {len(changed)} banks '
              f'changed, exact pinned set: {good}', flush=True)
        # profile
        pdir = B / cand / 'profile' / prof
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / 'load_order.json').write_text(json.dumps(order))
        (pdir / 'profile.json').write_text(json.dumps(
            {'name': prof, 'separate_saves': False,
             'description': 'WHEELMEM1: TEST28 content padded to TEST29c raw size (PAD28)' if cand == 'pad28'
             else 'WHEELMEM1: 21/27 hurt art packed inside TEST28 free atlas space (SLIM29)'}, indent=1))
        assert json.loads((pdir / 'load_order.json').read_text()) == order
    (B / 'evidence/bundle.json').write_text(json.dumps(report, indent=1))
    print('BUNDLE', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
