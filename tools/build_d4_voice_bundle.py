"""Assemble class voice replacements from the verified private dual-language checkpoint.

Offline. Inputs and outputs must be distinct; never point output at an installation.
The checkpoint remains private game-derived data and must not be committed.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(base, overrides, checkpoint, output):
    if output.exists():
        raise ValueError('Output already exists')
    manifest = json.loads((checkpoint / 'manifest.json').read_text())
    hashes = manifest['files'] if 'files' in manifest else None
    if not isinstance(hashes, dict):
        raise ValueError('Unrecognized checkpoint manifest')
    packs = sorted(base.glob('D4_Class_*'))
    if len(packs) != 45:
        raise ValueError(f'Expected 45 class packs, got {len(packs)}')
    output.mkdir(parents=True)
    inventory = []
    for original in packs:
        sid = original.name.removeprefix('D4_Class_')
        source = overrides / original.name if (overrides / original.name).is_dir() else original
        bank = checkpoint / 'components-v1' / 'banks' / f'D4_DualVoice_{sid}' / 'patches' / 'voices'
        files = list(bank.iterdir())
        if not files:
            raise ValueError(f'Missing source bank {sid}')
        for f in files:
            rel = f.relative_to(checkpoint).as_posix()
            if hashes.get(rel) != digest(f):
                raise ValueError(f'Checkpoint hash mismatch: {rel}')
        voice = json.loads((bank / 'voices.json').read_text())['voices']
        if len(voice) != 1:
            raise ValueError(f'Expected one voice in {bank}')
        vid = int(next(iter(voice)))
        if not 6000 <= vid <= 9999:
            raise ValueError(f'Invalid custom voice ID {vid}')
        dest = output / original.name
        shutil.copytree(source, dest)
        target = dest / 'patches' / 'voices'
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(bank, target)
        char = dest / 'patches' / 'db' / 'char.dat.json'
        data = json.loads(char.read_text())
        rows = data.get('added', [])
        if len(rows) != 6:
            raise ValueError(f'Expected six ranks in {char}')
        before = sorted({r['voice_id'] for r in rows})
        for row in rows:
            row['voice_id'] = vid
        char.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')
        inventory.append(dict(pack=original.name, source_groups=[int(sid)+i for i in range(3)], before=before, after=vid, baseline=str(source)))
    if len({x['after'] for x in inventory}) != len(inventory):
        raise ValueError('Duplicate voice IDs')
    return inventory


def main():
    ap = argparse.ArgumentParser()
    for name in ('base', 'overrides', 'checkpoint', 'output'):
        ap.add_argument('--'+name, type=Path, required=True)
    a = ap.parse_args()
    result = build(a.base, a.overrides, a.checkpoint, a.output)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
