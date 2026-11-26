"""Rank the missing D4 signature evilities by how many imported characters each engine addition unlocks.

Input is the project's own reviewed data, not recollection:
  * Subprojects/Engine-Extensions/d4-evility-map/d4_evilities.json  -- every D4 evility with its owners
    (character id, title, kind) and its extension "needs" family
  * Subprojects/Engine-Extensions/d4-review/LEDGER*.json           -- the per-class verdict and the `needs`
    reason for the 45 imported D4 generic classes
  * Builds/LIVE5_TEST16-20261030/mods                              -- which folders exist (what is imported)
  * D4UNIQ2/D4UNIQ3-REPORT.md tables                               -- the named characters' missing lists

Every missing evility is assigned one engine-addition bucket by hand, with the D4 text next to it, and the
count is of *distinct imported characters* (a named unique mod, or a generic class mod) that would gain at
least one evility from that one addition.  A character with two evilities in the same bucket counts once.

    python tools/carriers2_ranking.py [--json out.json]
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path('/Volumes/Data/Projects/D5')
MODS = ROOT / 'Builds/LIVE5_TEST16-20261030/mods'
# the ten characters of the later D4UNIQ3 bundle are imported too (a separate bundle, same roster)
MODS_2 = ROOT / 'Builds/D4UNIQ3-20261030/mods'
MAP = ROOT / 'Subprojects/Engine-Extensions/d4-evility-map/d4_evilities.json'

# ---- the buckets ---------------------------------------------------------------------------------------
# bucket -> (one-line description, [(evility id, the pack that owns the character)])
BUCKETS = {
    'filtered-counts': (
        'count deployed units of a kind (species / class / type / carried evility) as a magnitude, and count '
        'them for a threshold',
        [(837, 'D4_Unique_300'), (837, 'D4_Class_2200'), (841, 'D4_Unique_320'), (841, 'D4_Class_1220'),
         (127, 'D4_Class_2020'), (131, 'D4_Class_1120'), (816, 'D4_Unique_40'), (875, 'D4_Unique_440'),
         (658, 'D4_Unique_340')]),
    'evil-area': (
        'Evil Area membership (dispatched Evil Area allies, Evil Area leader)',
        [(840, 'D4_Unique_320'), (840, 'D4_Class_1220'), (658, 'D4_Unique_340')]),
    'magichange-summon': (
        'a Magichange / Confine / summoning mode (the mode itself, not a modifier)',
        [(820, 'D4_Unique_70'), (820, 'D4_Unique_220'), (820, 'D4_Unique_410'), (876, 'D4_Unique_440'),
         (878, 'D4_Unique_450'), (879, 'D4_Unique_450'), (851, 'D4_Unique_340'), (682, 'D4_Unique_410')]),
    'damage-redirect': (
        'damage redirection / reflection / inversion (who the damage lands on)',
        [(813, 'D4_Unique_20'), (891, 'D4_Unique_500'), (872, 'D4_Unique_410')]),
    'healing-pass': (
        'the healing pass (heal amount, heal auras, cure-on-heal)',
        [(626, 'D4_Unique_310'), (627, 'D4_Unique_310'), (628, 'D4_Unique_310'), (889, 'D4_Unique_500'),
         (215, 'D4_Unique_420')]),
    'named-unit-scale': (
        'a magnitude scaled from a named other unit (its missing HP, its stats)',
        [(812, 'D4_Unique_20'), (852, 'D4_Unique_340')]),
    'weapon-category': (
        'a measured D5 weapon-category test for bows and monster weapons',
        [(44, 'D4_Unique_610'), (97, 'D4_Unique_420')]),
    'movement-state': (
        'panels moved / has not moved (the movement counter proof)',
        [(628, 'D4_Unique_310'), (610, 'D4_Unique_420')]),
    'instant-death': (
        'a deathblow roll on an attack or a spell',
        [(873, 'D4_Unique_420'), (891, 'D4_Unique_500')]),
    'evasion-aura': (
        'evasion granted to / taken from other units',
        [(844, 'D4_Unique_350'), (847, 'D4_Unique_360'), (886, 'D4_Unique_470')]),
    'facing-write': ('a facing write on the target', [(836, 'D4_Unique_300')]),
    'survival-latch': ('a lethal-hit survival latch with a per-turn limit', [(838, 'D4_Unique_300')]),
    'status-and-height': ('a status-intensity / height condition', [(839, 'D4_Unique_300')]),
    'sp-cost-aura': ('an SP-cost modifier applied to other units', [(216, 'D4_Unique_420')]),
    'resource-reward': ('an EXP/mana reward multiplier', [(814, 'D4_Unique_50'), (814, 'D4_Unique_430')]),
}


def imported():
    names = {p.name for p in MODS.iterdir() if p.is_dir()}
    if MODS_2.is_dir():
        names |= {p.name for p in MODS_2.iterdir() if p.is_dir()}
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    args = ap.parse_args()
    have = imported()
    d4 = {e['id']: e for e in json.loads(MAP.read_text())['evilities']}

    out, rows = [], []
    for bucket, (desc, items) in BUCKETS.items():
        packs = sorted({p for _i, p in items if p in have})
        held = sorted({p for _i, p in items if p not in have})
        ids = sorted({i for i, _p in items})
        row = {'bucket': bucket, 'description': desc, 'evility_ids': ids,
               'imported_characters': len(packs), 'packs': packs,
               'not_imported': held,
               'evilities': [{'id': i, 'name': d4[i]['name'], 'text': d4[i]['d4_effect_rendered'],
                              'packs': sorted({p for j, p in items if j == i and p in have})}
                             for i in ids]}
        rows.append(row)
    rows.sort(key=lambda r: (-r['imported_characters'], r['bucket']))

    print(f"{'characters':>10}  bucket")
    for r in rows:
        print(f"{r['imported_characters']:>10}  {r['bucket']:20s} {', '.join(r['packs'])}")
    print()
    for r in rows:
        print(f"== {r['bucket']} ({r['imported_characters']} imported characters)")
        print(f"   {r['description']}")
        for e in r['evilities']:
            print(f"   {e['id']:4d} {e['name']:22s} {e['text'][:80]}")
            print(f"        on {', '.join(e['packs']) or '(no imported pack)'}")
    # the class-level view the ledgers give, for the generic classes
    ledger = {}
    for p in sorted((ROOT / 'Subprojects/Engine-Extensions/d4-review').glob('LEDGER*.json')):
        for c in json.loads(p.read_text())['classes']:
            for e in c['evilities']:
                if e['verdict'] == 'omit' and e.get('needs'):
                    ledger.setdefault(e['needs'][:90], set()).add(c['mod_id'])
    print(f"\ngeneric classes: {len({m for s in ledger.values() for m in s})} distinct classes; "
          f"{len([n for n, s in ledger.items() if len(s) > 1])} `needs` shared by more than one class")
    if args.json:
        Path(args.json).write_text(json.dumps({'ranking': rows}, indent=1, ensure_ascii=False) + '\n')
        print('wrote', args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
