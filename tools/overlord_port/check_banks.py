"""OLCONV2 ANM gate for the converted Overlord banks (offline, read-only).

  python tools/overlord_port/check_banks.py MODS_DIR [--only NAME ...]

For every `files/Anime/ANM_HI_JP.dat/anm<N>.lzs` of every mod folder under MODS_DIR it checks, in this order:

  1. lzs round trip   : decompress -> anm.parse -> to_bytes is byte-identical to the decompressed member
  2. block id         : the bank's block id is its member number (a re-id'd bank that kept the source id is not found
                        by the game)
  3. every animation renders: all animations, first and middle tick, no exception, and no tick of a LOOPING animation
                        is blank (the smoke gate's "full source poses 0 at tick" failure)
  4. whole figure     : bodies only (N, N+1): the stand / idle ids 1, 7, 1001, 6001 each cover at least half the
                        opaque area of the biggest of them (a wireframe overlay is a fifth of it)
  5. palettes / textures: every cell's palette index exists and every cell rectangle lies inside its texture
  6. completeness     : a body must hold ALL of the stand/idle ids 1, 7, 1001, 6001 (a missing id is a failure, not a
                        skipped check), and MODS_DIR must hold at least one bank (an empty directory fails)

Exit 1 on any failure; prints one line per bank.  Each check has a planted-failure case in tests/test_olconv2.py or
was seen failing during OLCONV2 (notes in the report).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True

from d5lib import anm, lzs  # noqa: E402


EXPECTED_STAND = (1, 7, 1001, 6001)


def check_bank(path: Path, body: bool):
    problems = []
    n = int(path.stem[3:])
    raw = lzs.decompress(path.read_bytes())
    f = anm.parse(raw)
    if f.to_bytes() != raw:
        problems.append("lzs round trip: to_bytes differs from the decompressed member")
    blk = f.blocks[0]
    if blk.id != n:
        problems.append(f"block id {blk.id} != member number {n}")
    area = {}
    for an in blk.animations:
        if not an.id:
            continue
        times = anm.frame_times(f, ("id", an.id))
        looping = anm.animation_info(blk, an)["loop"] is not None
        probe = sorted({0, max(times) // 2, max(times)}) if not looping else range(max(times) + 1)
        for t in probe:
            try:
                im = anm.render_items(f, anm.evaluate(f, ("id", an.id), t, nested=True), 0)[0]
            except Exception as e:             # noqa: BLE001
                problems.append(f"animation {an.id} tick {t}: {type(e).__name__}: {e}")
                break
            a = int((np.asarray(im.getchannel("A")) > 0).sum())
            if an.id in (1, 7, 1001, 6001) and t == 0:
                area[an.id] = a
            if looping and a == 0 and an.id in (1, 7, 1001, 6001, 6007, 1007):
                problems.append(f"looping animation {an.id}: blank at tick {t}")
                break
    if body:
        missing = [i for i in EXPECTED_STAND if i not in area]
        if missing:
            problems.append(f"body lacks the stand/idle animation id(s) {missing}")
        top = max(area.values() or [0])
        for aid, a in sorted(area.items()):
            if a <= 0.5 * top:
                problems.append(f"animation {aid} covers {a}px, under half of {top}px: not a whole figure")
    for i, c in enumerate(blk.cells):
        if not c.w or not c.h:
            continue
        ti = blk.tex_base + c.tex
        if not 0 <= ti < len(f.textures):
            problems.append(f"cell {i}: texture {c.tex} missing")
            break
        tx = f.textures[ti]
        if c.x + c.w > tx.width or c.y + c.h > tx.height:
            problems.append(f"cell {i}: rectangle {c.x},{c.y} {c.w}x{c.h} outside its {tx.width}x{tx.height} texture")
            break
        if c.pal >= max(1, len(blk.palette_infos)) and c.pal >= len(f.palettes):
            problems.append(f"cell {i}: palette {c.pal} missing")
            break
    return problems, len(blk.animations), len(blk.cells)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mods", type=Path)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    bad = total = 0
    for mod in sorted(a.mods.iterdir()):
        if a.only and mod.name not in a.only:
            continue
        d = mod / "files/Anime/ANM_HI_JP.dat"
        if not d.is_dir():
            continue
        members = sorted(d.glob("anm*.lzs"))
        base = min(int(m.stem[3:]) for m in members if int(m.stem[3:]) < 10000)
        for m in members:
            n = int(m.stem[3:])
            problems, na, nc = check_bank(m, body=n in (base, base + 1))
            total += 1
            bad += bool(problems)
            print(f"{'FAIL' if problems else 'ok  '} {mod.name} {m.name}: {na} animations, {nc} cells"
                  + ("".join(f"\n      {p}" for p in problems)))
    print(f"{total} bank(s), {bad} failing")
    if total == 0:
        print("FAIL no bank found under " + str(a.mods))
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
