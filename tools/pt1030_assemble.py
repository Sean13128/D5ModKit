"""Assemble Builds/PT1030ANIM-<date>: changed sprite banks + the kit files that produce them.

Overlay on TEST18B: only files that differ from Builds/LIVE5_TEST18B-20261030 are shipped, so
`diff -rq` against the base lists exactly the bundle's contents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

BASE = Path('/Volumes/Data/Projects/D5/Builds/LIVE5_TEST18B-20261030/mods')
FIX = Path('/Volumes/Data/ai-tmp/codex/pt1030anim')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def add_file(bundle: Path, pack: str, rel: str, data: bytes, why: str, inv: dict):
    dest = bundle / 'mods' / pack / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    base_path = BASE / pack / rel
    entry = dict(pack=pack, path=rel, sha256=sha(data), bytes=len(data), reason=why,
                 base_sha256=sha(base_path.read_bytes()) if base_path.is_file() else None,
                 base_bytes=base_path.stat().st_size if base_path.is_file() else None)
    inv.setdefault(pack, []).append(entry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--d1c', required=True, help='folder of rebuilt D1C class outputs')
    ap.add_argument('--wheel', required=True, help='bankfix --wheel output folder')
    ap.add_argument('--order', required=True, help='bankfix --order output folder')
    ap.add_argument('--kit', required=True, help='worktree whose d5lib files ship')
    ap.add_argument('--date', default='20261030')
    args = ap.parse_args()
    bundle = Path(args.out)
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    inv, reasons = {}, {}

    # 1. D1C class banks rebuilt with the converted rules
    root = Path(args.d1c)
    for cls in sorted(p for p in root.iterdir() if p.is_dir()):
        pack = 'D1C_Class_%s' % cls.name
        mod = cls / 'out/native-mods' / pack
        d = mod / 'files/Anime/ANM_HI_JP.dat'
        if not d.is_dir():
            continue
        for f in sorted(d.glob('*.lzs')):
            rel = 'files/Anime/ANM_HI_JP.dat/' + f.name
            new = f.read_bytes()
            old = (BASE / pack / rel)
            if old.is_file() and old.read_bytes() == new:
                continue
            add_file(bundle, pack, rel, new, 'D1C: source-canvas placement, upright whole poses, '
                     'source-paced timing', inv)

    # 2. D4 wheel motion restored to the native stub shape
    for src in (Path(args.wheel), Path(args.order)):
        for pack_dir in sorted(p for p in src.iterdir() if p.is_dir()):
            for f in sorted((pack_dir / 'files/Anime/ANM_HI_JP.dat').glob('*.lzs')):
                rel = 'files/Anime/ANM_HI_JP.dat/' + f.name
                new = f.read_bytes()
                old = BASE / pack_dir.name / rel
                if old.is_file() and old.read_bytes() == new:
                    continue
                why = ('D4 wheel motion 1001/1007 restored to the native zero-length attachment stub'
                       if src == Path(args.wheel) else
                       'D4 composed figure: body paints first, weapon, then hands')
                add_file(bundle, pack_dir.name, rel, new, why, inv)

    # 3. kit files
    kit = bundle / 'kit-install' / 'd5lib'
    kit.mkdir(parents=True)
    kit_files = ['ownanim.py', 'cellmatch.py', 'd1cart.py', 'nativeimports.py']
    for name in kit_files:
        shutil.copy2(Path(args.kit) / 'd5lib' / name, kit / name)
    tests = bundle / 'tests'
    tests.mkdir()
    for name in ('test_ownanim_duplicate_parts.py',):
        p = Path(args.kit) / 'tests' / name
        if p.is_file():
            shutil.copy2(p, tests / name)

    files = [(p, sha(p.read_bytes()), p.stat().st_size)
             for p in sorted(bundle.rglob('*')) if p.is_file()]
    inventory = dict(schema='pt1030anim-inventory/1', date=args.date,
                     base='Builds/LIVE5_TEST18B-20261030',
                     mods={k: v for k, v in sorted(inv.items())},
                     kit=[dict(path=str(p.relative_to(bundle)), sha256=s, bytes=n)
                          for p, s, n in files if 'kit-install' in str(p) or '/tests/' in str(p)],
                     totals=dict(packs=len(inv),
                                 files=sum(len(v) for v in inv.values()),
                                 bytes=sum(e['bytes'] for v in inv.values() for e in v),
                                 bundle_files=len(files)))
    (bundle / 'INVENTORY.json').write_text(json.dumps(inventory, indent=2) + '\n')
    lines = ['# PT1030ANIM inventory (%s)' % args.date,
             'base: Builds/LIVE5_TEST18B-20261030', '']
    for pack, entries in sorted(inv.items()):
        lines.append('%s (%d file%s)' % (pack, len(entries), '' if len(entries) == 1 else 's'))
        for e in entries:
            lines.append('  %s  %d B  %s' % (e['path'].split('/')[-1], e['bytes'], e['reason']))
    lines += ['', 'kit-install/d5lib: ' + ', '.join(kit_files)]
    (bundle / 'INVENTORY.txt').write_text('\n'.join(lines) + '\n')
    print(json.dumps(inventory['totals'], indent=2))


if __name__ == '__main__':
    main()
