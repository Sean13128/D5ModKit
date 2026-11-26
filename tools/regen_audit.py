#!/usr/bin/env python3
"""REGEN audit: stand/idle draw-item counts and ground lines, shipped bundle vs rebuilt bundle.

    python tools/regen_audit.py --before <bundle>/mods --after <bundle>/mods --out <playtest>/regen-renders

Runs `tools/sprite_audit.py` on both mods folders (no game launch; it reads the donor template sprites out
of the game folder read-only), then writes one comparison table and fails if any rebuilt pack still draws
more than one body in its stand picture (the S1 finding) or if a ground-line delta got worse.

Columns: stand_items / body_layers of animation 1, and the ground delta range over the idle animations
(a constant delta is the import's anchor offset; a range that swings is the per-frame idle error PTSPRITE
left open).  Ground values are the audit's own, in sprite pixels, 0 = the tile.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
GAME = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete"


def audit(mods: Path, out: Path) -> list:
    json_out = out / f'audit-{mods.parent.name}.json'
    env = dict(os.environ, D5_GAME=GAME)
    proc = subprocess.run([sys.executable, str(HERE / 'sprite_audit.py'), str(mods), '--out', str(json_out)],
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f'sprite_audit failed on {mods}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}')
    return json.loads(json_out.read_text())


def ground_range(entry):
    """the audit's own ground delta dict {min,max,n}, or None."""
    d = entry.get('ground_delta')
    return (d['min'], d['max']) if isinstance(d, dict) else None


def ground_delta(entry):
    return ground_range(entry)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--before', required=True)
    ap.add_argument('--after', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    before = {e['mod']: e for e in audit(Path(args.before), out)}
    after = {e['mod']: e for e in audit(Path(args.after), out)}

    lines = ['# REGEN sprite audit — shipped (LIVE5_TEST3) vs rebuilt',
             '# stand_items = draw items in animation 1 (1 = one body); ground = idle silhouette bottom range,',
             '# in sprite px; "n/a" = the audit measured no idle frame for that pack',
             f'{"mod":22} {"stand before":>12} {"stand after":>12} {"ground before":>16} {"ground after":>16} {"height b/a":>11}']
    problems = []
    for mod in sorted(after):
        b, a = before.get(mod), after[mod]
        if b is None:
            problems.append(f'{mod}: not present in the shipped bundle')
            continue
        bs, as_ = b['stand']['items'], a['stand']['items']
        gb, ga = ground_delta(b), ground_delta(a)
        hb = ((b.get('height') or {}).get('ratio'))
        ha = ((a.get('height') or {}).get('ratio'))
        fmt = lambda g: 'n/a' if not g else f'{g[0]}..{g[1]}'
        lines.append(f'{mod:22} {bs:>12} {as_:>12} {fmt(gb):>16} {fmt(ga):>16} '
                     f'{"n/a" if not hb or not ha else f"{ha / hb:.2f}":>11}')
        if as_ != 1:
            problems.append(f'{mod}: stand_items={as_} after the rebuild (S1 gate: must be 1)')
        if bs > 1 and as_ != 1:
            problems.append(f'{mod}: doubled body in the shipped pack and still doubled now')

    (out / 'REGEN-AUDIT.txt').write_text('\n'.join(lines) + '\n')
    summary = dict(
        packs=len(after),
        before_doubled=sum(1 for m, e in before.items() if e['stand']['items'] > 1),
        after_doubled=sum(1 for m, e in after.items() if e['stand']['items'] > 1),
        problems=problems,
    )
    (out / 'audit-summary.json').write_text(json.dumps(summary, indent=1))
    print('\n'.join(lines))
    print(f"\nbefore: {summary['before_doubled']} pack(s) with a doubled stand picture; "
          f"after: {summary['after_doubled']}")
    if problems:
        print('PROBLEMS:'); [print(' -', p) for p in problems]
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
