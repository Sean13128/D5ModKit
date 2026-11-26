"""P3 re-classification: which real D4 and DD2 evilities the four new additive passes actually cover.

This is a review tool, not a coverage generator.  Every row below was read in `d4_evilities.json` (D4) or
`Research/source-packs/dd2/coverage.json` (DD2) and given an explicit decision: either the exact `.d5el` row
that expresses it, or the reason it is still unsupported.  The emitted rows are then pushed through the
runtime's own validator (`d5lib.evility.table`), so a "covered" verdict is a row the extension accepts, not a
claim in prose.

    <kit python> evility/p3_reclassify.py [--json out.json]

Evidence class: offline, text-level.  A covered row is expressible; it is not a gameplay proof, and D4's own
arithmetic/stacking still needs consumer validation.
"""
import argparse
import json
import os
from pathlib import Path
import sys

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
from d5lib import evility as ev

ROOT = Path('/Volumes/Data/Projects/D5')
D4 = ROOT / 'Subprojects/Engine-Extensions/d4-evility-map/d4_evilities.json'
DD2 = ROOT / 'Research/source-packs/dd2/coverage.json'

# --- D4 primary rows the new families cover, with the row that expresses each one ------------------------
# The comment for every entry says what was checked: the effect text, its magnitude, and that every
# condition the text states has a COND_KINDS kind that an additive row can evaluate (unit state only).
D4_COVERED = {
    229: ('move', [{'value': 3}], [{'kind': 'hp_below', 'id': 25}],
          'Evasive Maneuvers: "MV increased by 3 when HP is under 25%" -- one effect, hp_below'),
    842: ('move', [{'value': 1, 'per': 'adjacent_ally'}], [],
          'Adjacent Catapult: "Move range increased by 1 x # of adjacent ally units" -- per=adjacent_ally'),
    48: ('range', [{'value': 1}], [],
         'Enlarge: "Magic range increased by 1 panel" -- unconditional'),
    341: ('power', [{'value': 3, 'per': 'map_enemy'}], [],
          'Violent Courage: "Attack power increased by # of enemy units on map x 3%" -- per=map_enemy'),
}

# --- D4 rows in the same families that stay unsupported, and why -----------------------------------------
D4_REJECTED = {
    176: 'Chicken Heart: MV +3 *and* stats -30% in one evility -- one row per id cannot carry two passes',
    180: 'Rapid Move: needs "SP is at maximum", which is not a condition kind',
    809: 'Stone Wall: DEF/RES +30% *and* MV -2 in one evility -- two passes, one row',
    464: 'Sky High: changes movement type to flying, which is the existing `flight` predicate, not a range',
    867: 'Transportation: carry/transport rule, not a move-range amount',
    413: 'Law by Range: magic range +2 *and* 50% more SP -- two passes and an SP-cost family we lack',
    829: 'Flying Bullets: "limitless" range with a gun -- a sentinel, not an amount the game adds',
    862: 'All Range +: an aura that raises adjacent allies\' range -- additive passes take no aura',
    337: 'Accel Shot: power + distance(panels) x 5% -- no per=distance scale and no distance measure',
    344: 'Calm Waters: power +30% on a single target -- target_count needs an action context the pass lacks',
    407: 'Magic Bundle: skill power +30% *and* 50% more SP -- two passes and an SP-cost family we lack',
    692: 'Accel Element: elemental ATK +10% x panels moved -- needs a distance measure and an element context',
}
# Covered by the family, but the numeric weapon-category id the `weapon` condition needs is not verified:
# d5lib/weaponlevels.WEAPONS is the *mastery* order (fist, sword, spear, bow, ...) while the condition reads the
# equipped item's category byte.  Assuming they share a 1-based numbering would be an inference, so these two
# stay out of the count until the mapping is measured.
D4_BLOCKED_ON_EVIDENCE = {
    41: 'Fist Range UP: +1 panel with a fist -- needs a verified equipped-weapon category id',
    44: 'Bow Range UP: +1 panel with a bow -- needs a verified equipped-weapon category id',
}
D4_RESISTANCE = 'resistance and resistance-aura rows (5) need a resistance accumulator, which is not built'

# --- DD2 needs-new-logic rows: the new passes change the vocabulary, not the verdict ---------------------
DD2_REVIEW = {
    100: 'Passiveness: power + defence power + unconditional counter in one evility -- three passes, one row',
    2090: 'Stone Statue: defence power +% "as long as the unit has not moved" -- no did-not-move condition',
    2111: 'Great Wall: defence power +% but all attacks hit -- no forced-hit rule',
    430: 'Demon Experiments: ally aura deals +% *and* enemies take +% -- two different magnitudes on one id',
    2012: 'Corrupting Body: damage taken -% *and* an ailment roll -- two magnitudes on one id',
}


def load():
    d4 = json.loads(D4.read_text())
    dd2 = json.loads(DD2.read_text())
    return {e['id']: e for e in d4['evilities'] if e['scope'] == 'primary'}, dd2['evilities']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    d4, dd2 = load()
    report = {'families': {}, 'd4': {}, 'dd2': {}}

    # --- the emitted rows, validated by the runtime itself
    rows = {}
    for eid, (family, effects, conditions, why) in sorted(D4_COVERED.items()):
        row = {'family': family, 'effects': effects}
        if conditions:
            row['conditions'] = conditions
        rows[eid] = row
    emitted = ev.table(rows)          # raises if the runtime rejects any of them
    report['emitted'] = {'rows': len(emitted[0]), 'conditions': len(emitted[1]),
                         'effects': len(emitted[2]),
                         'by_family': {f: sum(1 for e in rows.values() if e['family'] == f)
                                       for f in ('move', 'range', 'power')}}

    for eid, (family, effects, conditions, why) in sorted(D4_COVERED.items()):
        row = dict(rows[eid])
        report['d4'][str(eid)] = {'name': d4[eid]['name'], 'family': family, 'row': row,
                                  'source': d4[eid]['d4_effect_rendered'], 'why': why,
                                  'verdict': 'covered-by-extension'}
    by_family = {}
    for body in report['d4'].values():
        by_family.setdefault(body['family'], []).append(body['name'])
    report['families'] = by_family

    for eid, why in sorted(D4_REJECTED.items()):
        report['d4'][str(eid)] = {'name': d4[eid]['name'], 'source': d4[eid]['d4_effect_rendered'],
                                  'why': why, 'verdict': 'unsupported'}
    for eid, why in sorted(D4_BLOCKED_ON_EVIDENCE.items()):
        report['d4'][str(eid)] = {'name': d4[eid]['name'], 'source': d4[eid]['d4_effect_rendered'],
                                  'why': why, 'verdict': 'blocked-on-evidence'}
    report['d4_resistance'] = D4_RESISTANCE

    new_logic = {k: v for k, v in dd2.items() if v['relation'] == 'needs-new-logic'}
    still = [k for k in new_logic if k not in DD2_REVIEW]
    report['dd2'] = {'needs_new_logic': len(new_logic),
                     'covered_by_the_new_passes': 0,
                     'still_unsupported': len(new_logic),
                     'reviewed_against_the_new_vocabulary': {
                         k: {'name': new_logic[k]['dd2_name'],
                             'text': new_logic[k]['dd2_desc'], 'why': DD2_REVIEW[k]}
                         for k in DD2_REVIEW if k in new_logic},
                     'unreviewed_names': sorted(new_logic[k]['dd2_name'] for k in still
                                                if k not in DD2_REVIEW)}

    totals = {'d4_primary': len(d4),
              'd4_covered_by_extension': len(D4_COVERED),
              'd4_rejected_in_the_new_families': len(D4_REJECTED),
              'd4_blocked_on_evidence': len(D4_BLOCKED_ON_EVIDENCE),
              'dd2_needs_new_logic': len(new_logic),
              'dd2_moved': 0}
    report['totals'] = totals
    print(json.dumps(totals, indent=1))
    print('emitted rows:', report['emitted'])
    for family, names in sorted(by_family.items()):
        print(f'  {family}: {len(names)} -- {", ".join(names)}')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
