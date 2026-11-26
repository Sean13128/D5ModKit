#!/usr/bin/env python3
"""Render a metadata-only wheel inventory for an offline profile.

Usage: PYTHONPATH=. python tools/wheel_contents.py MODS_DIR LOAD_ORDER_JSON
Only enabled class descriptors are inventoried; this does not model native
unlock flags, visibility, cursor order, animation, or actual rendered menus.
"""
import json
import sys
from pathlib import Path

from d5lib import modsys, newclasses, wheelmeta


def inventory(mods_dir, order):
    pairs, names, missing = [], {}, []
    for mod_id in order:
        folder = Path(mods_dir) / mod_id
        if not folder.is_dir():
            missing.append(mod_id)
            continue
        mod = modsys.Mod(str(folder))
        specs = newclasses.load_specs(mod)
        pairs.append((mod.meta, specs))
        for spec in specs:
            names[int(spec['family'])] = spec.get('name', mod.name)
    groups = wheelmeta.family_wheels(pairs)
    return groups, names, missing


def render(groups, names, missing):
    lines = ['# Offline wheel contents', '',
             'Metadata inventory only: not a game render or a visibility/unlock proof.',
             'D5 native candidates are implicit and are not listed.', '']
    for wheel, families in groups.items():
        lines.extend([f'## {wheel.upper()} — {len(families)} custom families', ''])
        lines.extend(f'- {family}: {names[family]}' for family in families)
        if not families:
            lines.append('- No custom families in the inspected mods.')
        lines.append('')
    if missing:
        lines.extend([f'Profile entries unavailable for inspection ({len(missing)}):', ''])
        lines.extend(f'- {name}' for name in missing)
    return '\n'.join(lines) + '\n'


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    order = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    print(render(*inventory(sys.argv[1], order)), end='')


if __name__ == '__main__':
    main()
