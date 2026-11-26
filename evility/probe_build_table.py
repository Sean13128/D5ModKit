#!/usr/bin/env python3
"""Rebuild the Skill.dat table TEST16 installs, offline, from the vanilla database.

The install applies every mod's `patches/db/Skill.dat.json` in the profile's load order.
This does exactly that to a copy of the pristine database and prints the finished table's
id list, so a replay can use the same 1,042 rows Sean's save was written against instead
of whatever the game folder happens to hold while another lane reinstalls.

Writes nothing outside /Volumes/Data/ai-tmp/evcap5/.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get('D5_KIT', os.path.dirname(HERE))
sys.path.insert(0, KIT)

from d5lib import database, dbpatch

VANILLA = os.environ.get('D5_VANILLA', '/Volumes/Data/ai-tmp/magichange/vanilla/Database_0.dat')
BUNDLE = os.environ.get('D5_BUNDLE', '/Volumes/Data/Projects/D5/Builds/LIVE5_TEST16-20261030')
WORK = os.environ.get('D5_WORK', '/Volumes/Data/ai-tmp/evcap5/build')


def main():
    os.makedirs(WORK, exist_ok=True)
    copy = os.path.join(WORK, 'Database_0.dat')
    shutil.copyfile(VANILLA, copy)
    db = database.load_database(copy)
    skill = db.table('Skill.dat')
    order = json.load(open(os.path.join(BUNDLE, 'profile', 'LIVE5_TEST16', 'load_order.json')))
    applied = []
    for name in order:
        folder = os.path.join(BUNDLE, 'mods', name)
        patch_dir = os.path.join(folder, 'patches', 'db')
        if not os.path.isdir(patch_dir):
            continue
        for fname in sorted(os.listdir(patch_dir)):
            if not fname.lower().endswith('.json'):
                continue
            patch = json.load(open(os.path.join(patch_dir, fname)))
            member = patch.get('table') or fname[:-5]
            if member.lower() != 'skill.dat':
                continue
            dbpatch.apply_patch(skill, patch)
            applied.append((name, len(patch.get('rows') or {}), len(patch.get('added') or [])))
    ids = sorted(int(r['id']) for r in skill.rows)
    out = {'rows': len(ids), 'ids': ids, 'patches': applied}
    open(os.path.join(WORK, 'Skill.dat'), 'wb').write(skill.to_bytes())
    path = os.path.join(WORK, 'skill-table.json')
    json.dump(out, open(path, 'w'))
    print(json.dumps({'rows': len(ids), 'patches': len(applied), 'min': ids[0], 'max': ids[-1],
                      'has_8228': 8228 in ids,
                      'position_8228': ids.index(8228) if 8228 in ids else None,
                      'ids_at_1000+': ids[1000:]}, indent=1))
    print('wrote', path)


if __name__ == '__main__':
    main()
