#!/usr/bin/env python3
"""REGEN: rebuild the 45 installed D4 class packs' ART with the fixed converter, keep their tables.

Why art only: the reviewed tables of a D4 pack are the product of a chained history (batch build,
four review batches, DEDUP2 re-leases, PTFIX format/voice fixes, PTFIX2 innate links).  That history is
not reproducible from a single converter commit -- the installed packs' ANM files are a per-file mix of
two build states (see playtest/REGEN-REPORT.md, "byte identity proof").  So the pipeline takes the
authoritative folder (Builds/LIVE5_TEST3-20261028/mods/<mod>, the end state) and replaces ONLY

    files/Anime/**/*.lzs            the built sprite/animation banks
    patches/classes/*.png           faces and cut-ins

with what today's fixed converter (PTSPRITE S1 single body per stand pose, S2 stand ground line,
S3 no automatic matte) emits from the same prepared art, using each pack's own recorded build command.

Every other file is copied from the base folder and then re-hashed and compared: a non-art difference
is a hard failure (stop and explain), never a silent change.

    python tools/regen_d4_packs.py --out <dir> [--jobs 3] [--only D4_Class_1010 ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BASE = Path('/Volumes/Data/Projects/D5')
EVIDENCE = BASE / 'Research/d4-expansion-20261018/mvp-breadth'
BASE_MODS = BASE / 'Builds/LIVE5_TEST3-20261028/mods'
PY = BASE / 'Local/python-macos/bin/python'
CONVERTER = HERE / 'tools/build_source_pack.py'
ART_SUFFIXES = ('.lzs', '.png')


def command_for(mod_id: str) -> list[str]:
    """The pack's own recorded build command, converter swapped, output redirected."""
    sid = mod_id.rsplit('_', 1)[-1]
    cand = EVIDENCE / f'build-command-{sid}.json'
    if sid == '1220':                       # six personality variants: the installed pack is this one
        cand = EVIDENCE / 'build-command-1220-explicit-personalities.json'
    cmd = json.loads(cand.read_text())
    cmd[1] = str(CONVERTER)
    cmd[cmd.index('--output-path') + 1] = '__OUT__'   # filled per build
    return cmd


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def tree(root: Path, skip_art: bool = False):
    rows = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if skip_art and (rel.startswith('files/Anime/') or path.suffix in ART_SUFFIXES):
            continue
        rows[rel] = sha(path)
    return rows


def build_one(mod_id: str, scratch: Path) -> Path:
    out = scratch / 'builds' / mod_id
    if (out / 'staged-kit' / 'mods' / mod_id).is_dir():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = list(command_for(mod_id))          # command[0] is the kit python, command[1] the converter
    cmd[cmd.index('__OUT__')] = str(out)
    log = scratch / 'logs' / f'{mod_id}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with log.open('w') as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = '\n'.join(log.read_text(errors='replace').splitlines()[-15:])
        raise RuntimeError(f'{mod_id}: converter exited {proc.returncode}\n{tail}')
    return out


def regen_pack(mod_id: str, scratch: Path, out_mods: Path, base_mods: Path) -> dict:
    built = build_one(mod_id, scratch) / 'staged-kit' / 'mods' / mod_id
    if not built.is_dir():
        raise RuntimeError(f'{mod_id}: no staged mod in the build output')
    base = base_mods / mod_id
    dst = out_mods / mod_id
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base, dst)

    base_art = {rel for rel in tree(base) if rel.startswith('files/Anime/')
                or Path(rel).suffix in ART_SUFFIXES and not rel.startswith('patches/voices/')}
    new_art = {rel for rel in tree(built) if rel.startswith('files/Anime/')
               or Path(rel).suffix in ART_SUFFIXES and not rel.startswith('patches/voices/')}
    if base_art != new_art:
        raise RuntimeError(f'{mod_id}: art file set differs\n  only base: {sorted(base_art - new_art)}\n'
                           f'  only new: {sorted(new_art - base_art)}')

    changed, same = [], []
    for rel in sorted(new_art):
        src, dstf = built / rel, dst / rel
        dstf.parent.mkdir(parents=True, exist_ok=True)
        if dstf.exists() and sha(dstf) == sha(src):
            same.append(rel)
            continue
        shutil.copy2(src, dstf)
        changed.append(rel)

    after = tree(dst, skip_art=True)
    before = tree(base, skip_art=True)
    if after != before:
        diff = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        raise RuntimeError(f'{mod_id}: NON-ART DIFFERENCE (stop): {diff}')

    return dict(mod=mod_id, art_files=len(new_art), changed=changed, unchanged=same,
                table_files=len(before), non_art_identical=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True, help='output bundle dir (mods/<id> written under it)')
    ap.add_argument('--scratch', default='/Volumes/Data/ai-tmp/hermes/regen/work')
    ap.add_argument('--jobs', type=int, default=3)
    ap.add_argument('--only', nargs='+')
    ap.add_argument('--base-mods', type=Path, default=BASE_MODS,
                    help='authoritative baseline mod folders (default: TEST3)')
    args = ap.parse_args()

    out = Path(args.out)
    out_mods = out / 'mods'
    out_mods.mkdir(parents=True, exist_ok=True)
    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)

    mods = sorted(p.name for p in args.base_mods.iterdir() if p.is_dir() and p.name.startswith('D4_Class_'))
    if args.only:
        mods = [m for m in mods if m in args.only]
    print(f'{len(mods)} pack(s)', flush=True)

    results, failures = [], []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(regen_pack, m, scratch, out_mods, args.base_mods): m for m in mods}
        for fut in futures:
            m = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
                print(f'FAIL {m}: {exc}', flush=True)
                failures.append(dict(mod=m, error=str(exc)))
                continue
            results.append(r)
            print(f'ok {m}: {len(r["changed"])} art file(s) changed, {len(r["unchanged"])} same, '
                  f'{r["table_files"]} table files identical', flush=True)

    summary = dict(packs=len(results), failures=failures, results=results)
    (out / 'REGEN-SUMMARY.json').write_text(json.dumps(summary, indent=1))
    print(f'\n{len(results)} rebuilt, {len(failures)} failed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
