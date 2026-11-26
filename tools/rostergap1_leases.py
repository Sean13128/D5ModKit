#!/usr/bin/env python3
"""ROSTERGAP1: measure which ids are free for the DD2 rows that have no lease yet (offline, read-only).

    D5_INSTALLED_MODS=<holding>/mods python tools/rostergap1_leases.py [--json out.json]

Sources of claims (nothing is assumed free because a dry run said "not installed"):
  * vanilla char.dat / charhelp.dat / Quest.dat / charPersonal.dat / JobRank.dat and every anm number the
    game resolves (the original backup state, via d5lib.sprites.used_sprite_numbers)
  * every mod folder under the live installed-mods root, the holding folder and D5_INSTALLED_MODS (db rows added,
    row indexes patched, anm files shipped)
  * the recorded leases: dd2-leases.json, d4-leases.json, Research d1c unique-leases.json, unique_art_leases.json,
    Builds/*/LEASES.json
Allocation is "next free above every claim" for storage ids (the D1C batch's rule) and the first measured free
window for art (d5lib.slots.unique_sprite_pool, widened by the shipped-file check below).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
P = Path('/Volumes/Data/Projects/D5')
GAME = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete')
STATE = GAME / 'D5ModKit/state/games/Disgaea_5_Complete-d8040a88'
# folders being superseded by the rebuild (ROSTERGAP1_SKIP=a,b): their own claims are not competing claims
SKIP = set(filter(None, os.environ.get('ROSTERGAP1_SKIP', '').split(',')))
MOD_ROOTS = [P / 'Local/Installed D5ModKit/mods', P / 'Local/mods-holding/20261108-PLAYTEST-RESET/mods']


def vanilla():
    from d5lib import database, newclasses, slots, sprites
    from d5lib.importers.dd2 import original_fs
    import tempfile
    sprites.CACHE_DIR = tempfile.mkdtemp(prefix='rg1cache')
    fs = original_fs(dict(game_path=GAME, state_root=STATE))
    try:
        out = {}
        for name in ('char.dat', 'charhelp.dat', 'Quest.dat', 'charPersonal.dat', 'JobRank.dat'):
            t = database.load_table(name, fs.read('Database/Database_0.dat/' + name))
            out[name] = t
        used = set(sprites.used_sprite_numbers(fs))
    finally:
        fs.reset()
    return out, used


def table_claims(tables):
    c = {}
    c['char'] = {int(r['id']) for r in tables['char.dat'].rows}
    c['help'] = {int(r['id']) for r in tables['charhelp.dat'].rows} | {int(r['char_id']) for r in tables['charhelp.dat'].rows}
    c['quest'] = {int(r['id']) for r in tables['Quest.dat'].rows}
    c['slot'] = {int(r['sort_order']) for r in tables['Quest.dat'].rows}
    c['personality'] = {int(r['id']) for r in tables['charPersonal.dat'].rows}
    c['jobrank'] = {int(r['id']) for r in tables['JobRank.dat'].rows}
    return c


def mod_claims(roots, c):
    """Add what every mod folder adds (db rows, shipped anm numbers); return {anm number: folder}."""
    members = {'char.dat': 'char', 'charhelp.dat': 'help', 'Quest.dat': 'quest', 'charPersonal.dat': 'personality',
               'JobRank.dat': 'jobrank'}
    anm = {}
    for root in roots:
        if not Path(root).is_dir():
            continue
        for folder in sorted(Path(root).iterdir()):
            if not (folder / 'mod.json').is_file() or folder.name in SKIP:
                continue
            for member, key in members.items():
                f = folder / 'patches/db' / (member + '.json')
                if not f.is_file():
                    continue
                try:
                    doc = json.loads(f.read_text(encoding='utf-8-sig'))
                except ValueError:
                    continue
                for r in doc.get('added') or []:
                    if 'id' in r:
                        c[key].add(int(r['id']))
                    if key == 'help' and 'char_id' in r:
                        c[key].add(int(r['char_id']))
                    if key == 'quest' and 'sort_order' in r:
                        c['slot'].add(int(r['sort_order']))
            for f in (folder / 'files').rglob('anm*.lzs') if (folder / 'files').is_dir() else ():
                m = re.fullmatch(r'anm(\d+)\.lzs', f.name)
                if m:
                    anm.setdefault(int(m.group(1)), folder.name)
    return anm


def lease_claims(c, phys, ident):
    for f in (ROOT / 'd5lib/importers/dd2-leases.json', ):
        for lease in json.loads(f.read_text())['entries'].values():
            if lease.get('parked'):
                continue
            c['char'].update(lease['rank_ids']); c['char'].add(lease['target'])
            c['help'].add(lease['help']); c['jobrank'].update(lease['jobranks']); c['personality'].update(lease['personalities'])
            c['quest'].update(lease['quests'])
            if lease.get('quest_slot'):
                c['slot'].add(lease['quest_slot'])
            phys.add(lease['physical'])
            if lease['kind'] == 'unique':
                ident.add(lease['target'])
    d4 = json.loads((ROOT / 'd5lib/importers/d4-leases.json').read_text())
    for e in d4['characters'].values():
        ident.add(e['identity']); phys.add(e['physical']); c['char'].add(e['identity'])
        st = e.get('storage') or {}
        if st:
            c['help'].add(st['help_id']); c['quest'].add(st['quest_id']); c['slot'].add(st['quest_slot'])
    d1 = json.loads((P / 'Research/source-packs/d1c/batches/unique-leases.json').read_text())['leased']
    for e in d1.values():
        ident.add(int(e['identity'])); phys.add(int(e['physical'])); c['char'].add(int(e['identity']))
        for k, key in (('help_id', 'help'), ('quest_id', 'quest'), ('quest_slot', 'slot')):
            if e.get(k):
                c[key].add(int(e[k]))
    art = json.loads((ROOT / 'd5lib/data/unique_art_leases.json').read_text())['leases']
    for e in art.values():
        ident.add(int(e['identity'])); phys.add(int(e['physical']))
    for f in glob.glob(str(P / 'Builds/*/LEASES.json')):
        try:
            doc = json.loads(Path(f).read_text())
        except ValueError:
            continue
        mods = doc.get('mods') if isinstance(doc, dict) else None
        items = mods.values() if isinstance(mods, dict) else (mods or [])
        for e in items:
            if isinstance(e, dict) and e.get('identity'):
                ident.add(int(e['identity'])); c['char'].add(int(e['identity']))
                if e.get('physical'):
                    phys.add(int(e['physical']))
                for k, key in (('help_id', 'help'), ('quest_id', 'quest'), ('quest_slot', 'slot')):
                    if e.get(k):
                        c[key].add(int(e[k]))


def measure():
    tables, used_vanilla_anm = vanilla()
    c = table_claims(tables)
    roots = list(MOD_ROOTS)
    if os.environ.get('D5_INSTALLED_MODS'):
        roots.append(Path(os.environ['D5_INSTALLED_MODS']))
    anm = mod_claims(roots, c)
    phys, ident = set(), set()
    lease_claims(c, phys, ident)
    return c, anm, used_vanilla_anm, phys, ident


def free_window(n, anm, used, phys):
    keys = {n, n + 1, n + 2, 10000 + n, 10001 + n}
    return (not keys & used and not keys & set(anm) and not keys & set(c_char_global)
            and all(abs(n - t) >= 3 for t in phys))


c_char_global = set()


def propose(want):
    """want: {'uniques': n, 'class_monster_slots': n, 'personalities': n}"""
    global c_char_global
    c, anm, used, phys, ident = measure()
    c_char_global = c['char']
    out = {}
    free_ident = [i for i in range(10000, 10991, 10) if i not in ident and i not in c['char']]
    out['identity_free_first'] = free_ident[:12]
    from d5lib import slots
    pool = []
    taken = set(phys)
    for lo, hi in slots.SPRITE_LEASE_RUNS:
        for n in range(lo, hi + 1):
            if free_window(n, anm, used, taken | set(pool)):
                pool.append(n)
    out['art_windows_free_first'] = pool[:12]
    out['art_windows_free_total'] = len(pool)
    out['help_next'] = max(c['help'] | {22681}) + 1
    from d5lib import dbpatch
    out['quest_next'] = max(i for i in c['quest'] if i < dbpatch.PLACEHOLDER_FIRST) + 1   # dbpatch.new_quest_id's rule
    top = max(c['slot'])
    out['slots_free_below_top'] = [n for n in range(top) if n not in c['slot']][:12]       # dbpatch.free_quest_slot's rule
    out['slot_next'] = top + 1
    out['personality_next'] = max(c['personality']) + 1
    slots_m = [s for s in range(2620, 2891, 10)
               if not ({s, s + 1, s + 2, 10000 + s, 10001 + s} & (set(anm) | used)) and s not in phys
               and not any(s + k in c['char'] for k in range(6))]
    out['monster_slots_free'] = slots_m
    out['monster_slots_taken_by_leases'] = sorted(p for p in phys if 2620 <= p <= 2890)
    out['claims'] = {k: [min(v), max(v), len(v)] for k, v in c.items()}
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    a = ap.parse_args()
    res = propose({})
    print(json.dumps(res, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
