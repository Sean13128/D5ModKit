#!/usr/bin/env python3
"""Resolve every ``@text`` reference in the D1C/DD2 kit data from the user's own prepared sources.

    python tools/verify_textrefs.py [--d4-prepared DIR]

TEXTHASH-D1C-DD2.  The audited files (Reports/GITTEXT1-AUDIT-20261120.md) store game names/titles/
descriptions as SHA-256 references; the build resolves them at run time.  This tool is the offline
check a maintainer runs against their prepared folder: every reference must resolve, and the resolved
document must equal the document the pack used to carry (the round-trip proof the lane report cites).

Inputs, each named by the normal source resolver:
  * D1C: the verified prepared folder (``D5_SOURCE_DIR`` / kit setting) through ``_d1c_source``
  * DD2: the same prepared folder through ``_dd2_source``
  * D5:  the install the kit resolves plus its backup state (or ``--game-path``/``--state``)
  * D4:  only ``unique_art_leases.json`` names D4 rows; optional, ``--d4-prepared``
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import textrefs  # noqa: E402

FILES = ('d5lib/sourcemaps/d1c.json', 'd5lib/importers/d1c-voice-map.json',
         'd5lib/importers/d1c-donor-evilities.json', 'd5lib/data/unique_art_leases.json',
         'd5lib/sourcemaps/dd2.json', 'd5lib/importers/dd2-innate-evilities.json',
         'd5lib/importers/dd2-leases.json', 'd5lib/importers/dd2-voice-map.json')


def counts(value, out):
    if isinstance(value, dict):
        if textrefs.is_ref(value):
            out['text' if textrefs.TEXT in value else 'authored'] += 1
            return
        for item in value.values():
            counts(item, out)
    elif isinstance(value, list):
        for item in value:
            counts(item, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game-path', help='Disgaea 5 install (default: the kit resolver)')
    ap.add_argument('--state', help='the kit game-state folder holding backups.json')
    ap.add_argument('--d4-prepared', type=Path,
                    help='prepared D4 folder (holds Data/DATA/EN/DATABASE_EN.dat); needed for unique_art_leases')
    ap.add_argument('--json', action='store_true', help='print one JSON object per file')
    args = ap.parse_args(argv)

    from d5lib import d1cvoice
    from d5lib import textrefs as tr
    from d5lib.importers import _d1c_source, _dd2_source

    d5 = tr.d5_text_pool_for_build(args.game_path, args.state)
    d1c_pool = tr.TextPool(label='d1c+d5').merge(_d1c_source.text_pool()).merge(d5)
    dd2_pool = tr.TextPool(label='dd2+d5').merge(_dd2_source.text_pool()).merge(d5)
    mixed = tr.TextPool(label='d1c+dd2+d5').merge(d1c_pool).merge(dd2_pool)
    if args.d4_prepared:
        from d5lib import d4source
        from d5lib.nativeimports import ascii_latin
        d4 = tr.TextPool(label='the prepared Disgaea 4 source', folds=(ascii_latin,))
        d4.update(c['name'] for c in d4source.D4Data(args.d4_prepared).chars.values())
        mixed.merge(d4)

    failures = []
    report = {}
    for name in FILES:
        doc = json.loads((ROOT / name).read_text(encoding='utf-8'))
        stats = {'text': 0, 'authored': 0}
        counts(doc, stats)
        try:
            if name.endswith('d1c-voice-map.json'):
                for section in ('mods', 'silent', 'unchanged'):
                    for folder, entry in (doc.get(section) or {}).items():
                        d1cvoice.voice_label(entry, f'd1c-voice-map {section}.{folder}')
            elif name.endswith('unique_art_leases.json'):
                tr.resolve(doc, mixed.get)
            elif name.startswith('d5lib/sourcemaps/dd2') or name.startswith('d5lib/importers/dd2'):
                tr.resolve(doc, dd2_pool.get)
            elif name.endswith('d1c-donor-evilities.json'):
                tr.resolve(doc, d5.get)
            else:
                tr.resolve(doc, d1c_pool.get)
        except textrefs.TextRefError as exc:
            failures.append(f'{name}: {exc}')
            continue
        report[name] = stats
        if not args.json:
            print(f'{name}: {stats["text"]} @text, {stats["authored"]} @authored references resolve')

    if args.json:
        print(json.dumps(report, indent=2))
    for failure in failures:
        print('FAIL', failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
