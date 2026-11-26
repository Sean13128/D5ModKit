"""Assemble Builds/ANIMALL2-<date>: only the folders that actually change, with a re-hashable inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

R = Path('/Volumes/Data/Projects/D5')


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', required=True)
    ap.add_argument('--gates', required=True)
    ap.add_argument('--base', default=str(R / 'Builds/PT1029-20261029/mods'))
    ap.add_argument('--fallback', default=str(R / 'Builds/LIVE5_TEST14-20261029/mods'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--receipts', default='')
    args = ap.parse_args()
    stage, out = Path(args.stage), Path(args.out)
    base, fallback = Path(args.base), Path(args.fallback)
    gates = json.loads((Path(args.gates) / 'gates.json').read_text())
    mods = out / 'mods'
    if out.exists():
        shutil.rmtree(out)
    mods.mkdir(parents=True)
    inv, shipped = {}, []
    for name, rec in sorted(gates.items()):
        if rec.get('unchanged') or not rec.get('changed'):
            continue
        src = stage / name
        dst = mods / name
        shutil.copytree(src, dst)
        b = base / name if (base / name).exists() else fallback / name
        which = 'PT1029-20261029' if (base / name).exists() else 'LIVE5_TEST14-20261029'
        files = []
        for rel in rec['changed']:
            f = dst / rel
            files.append(dict(path=rel, base=which, base_sha256=sha(b / rel), sha256=sha(f),
                              bytes=f.stat().st_size))
        inv[name] = dict(bank=rec.get('bank'), motions=rec.get('motions'), files=files,
                         wheel=rec.get('wheel'), attachments=rec.get('attachments', []))
        shipped.append(name)
    (out / 'INVENTORY.json').write_text(json.dumps(inv, indent=1))
    if args.receipts:
        rdir = out / 'receipts'
        rdir.mkdir()
        for f in Path(args.receipts).rglob('*'):
            if f.is_file():
                target = rdir / f.relative_to(Path(args.receipts))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
    print(f'{len(shipped)} folders, {sum(len(v["files"]) for v in inv.values())} files, '
          f'{sum(f["bytes"] for v in inv.values() for f in v["files"])} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
