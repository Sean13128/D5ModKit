"""Flag patch strings above a conservative reference-corpus character count.

The default Quest.dat name threshold is the maximum English vanilla name length
(19 characters) in the preserved comparison-v4 Quest.dat, excluding its added
comparison quest. It is NOT a pixel measurement or proof that every shorter
string fits; proportional fonts and non-Latin glyphs need a native UI check.
Additional fields can be supplied with --field TABLE.FIELD=COUNT.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.check_pack_tables import iter_patch_rows, patch_files, walk_mods
import json


def check(table, fields, limits):
    """Return display warnings; non-ASCII widths have not been calibrated."""
    out = []
    for field, value in fields.items():
        key = (table.lower(), field.lower())
        if key not in limits or not isinstance(value, str):
            continue
        if len(value) > limits[key]:
            out.append(f'{field}: {len(value)} characters > {limits[key]} reference threshold: {value!r}')
        if not value.isascii():
            out.append(f'{field}: non-ASCII display width unmeasured: {value!r}')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mods', action='append', required=True, help='mod folder or folder containing mods')
    parser.add_argument('--field', action='append', default=[], metavar='TABLE.FIELD=COUNT',
                        help='additional or overriding character-count threshold')
    args = parser.parse_args(argv)
    limits = {('quest.dat', f'name_{lang}'): 19 for lang in ('en', 'fr', 'jp', 'chn', 'kor')}
    for spec in args.field:
        try:
            field, number = spec.rsplit('=', 1)
            table, name = field.rsplit('.', 1)
            number = int(number)
            if number < 0:
                raise ValueError
        except ValueError:
            parser.error(f'invalid --field {spec!r}; expected TABLE.FIELD=nonnegative count')
        limits[table.lower(), name.lower()] = number
    findings = 0
    mods = walk_mods(args.mods)
    if not mods:
        print('No mod folders found', file=sys.stderr)
        return 2
    for name, directory in mods:
        for path in patch_files(directory):
            try:
                patch = json.loads(path.read_text(encoding='utf-8'))
                for table, rid, fields, where in iter_patch_rows(patch, path.stem):
                    for warning in check(table, fields, limits):
                        print(f'{name}: {path.name}: {where} id={rid}: {warning}')
                        findings += 1
            except (OSError, ValueError) as exc:
                print(f'{path}: {exc}', file=sys.stderr)
                return 2
    print(f'{findings} warning(s); character counts are not rendered pixel widths')
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
