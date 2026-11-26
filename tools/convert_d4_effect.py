#!/usr/bin/env python3
"""Convert an explicit extracted D4 effect to an offline D5 OBF. Never install."""
import argparse
import json
import hashlib
from pathlib import Path
import sys
import struct

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import d4effects, lzs, offlinepaths, ykcmp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path, help='extracted D4 OBF or LZS member')
    ap.add_argument('output', type=Path, help='new output file outside the source checkout')
    ap.add_argument('--ykcmp', action='store_true', help='wrap output as D5 YKCMP')
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument('--effect71-two-frames', action='store_true',
                    help='opt in to the exact reviewed EN effect71 two-palette offline case; not resource readiness')
    modes.add_argument('--palette-frames', action='store_true',
                       help='opt in to bounded static-material multi-palette color frames; not resource readiness')
    args = ap.parse_args()
    checkout = Path(__file__).resolve().parents[1]
    try:
        output = offlinepaths.offline_output(args.output, (checkout, args.source))
        offlinepaths.offline_output(output.with_suffix(output.suffix + '.json'), (checkout, args.source))
    except ValueError as exc:
        ap.error(str(exc))
    if output.exists() or output.with_suffix(output.suffix + '.json').exists():
        ap.error('output or report already exists; choose a new path')
    if args.source.stat().st_size > d4effects.LIMIT:
        ap.error('source exceeds bounded input limit')
    raw = args.source.read_bytes()
    if raw[:4] in (b'dat\0', b'obf\0'):
        if len(raw) < 16:
            ap.error('truncated LZS header')
        usize, csize, marker = struct.unpack_from('<III', raw, 4)
        if usize > d4effects.LIMIT or csize not in (len(raw), len(raw)-4) or marker > 255:
            ap.error('unverified or oversized LZS header')
        raw = lzs.decompress(raw)
    try:
        converted, report = d4effects.convert_obf(raw, effect71_two_frames=args.effect71_two_frames,
                                                palette_frames=args.palette_frames)
    except ValueError as exc:
        ap.exit(2, f'Conversion blocked: {exc}\n')
    if args.ykcmp:
        converted = ykcmp.compress(converted)
    report.update(source=str(args.source.resolve()), output=str(output), compressed=args.ykcmp,
                  output_sha256=hashlib.sha256(converted).hexdigest())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(converted)
    with output.with_suffix(output.suffix + '.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
