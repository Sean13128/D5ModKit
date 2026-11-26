"""P3b re-classification: what several rows per evility id changes for real D4 and DD2 content.

Same method as `p3_reclassify.py` (a review tool, not a coverage generator): every row below was read in
`d4_evilities.json` (D4, 306 primary rows) or `Research/source-packs/dd2/coverage.json` (DD2, the 27
`needs-new-logic` rows) and given an explicit decision -- either the exact `.d5el` entry that expresses it
(a single row, or a *list* of rows for one id) or the reason it is still unsupported.  Every emitted entry is
pushed through the runtime's own validator (`d5lib.evility.table`), so a "covered" verdict is an entry the
extension accepts, not a claim in prose.

    <kit python> evility/p3b_reclassify.py [--json out.json]

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

# --- D4 primary rows the extension now covers, with the entry that expresses each one --------------------
# A single row where one family is enough; a list where one id has to carry two passes.
D4_COVERED = {
    229: ([{'family': 'move', 'effects': [{'value': 3}],
            'condition': {'kind': 'hp_below', 'id': 25}}],
          'Evasive Maneuvers: "MV increased by 3 when HP is under 25%" -- one effect, hp_below'),
    842: ([{'family': 'move', 'effects': [{'value': 1, 'per': 'adjacent_ally'}]}],
          'Adjacent Catapult: "Move range increased by 1 x # of adjacent ally units" -- per=adjacent_ally'),
    48: ([{'family': 'range', 'effects': [{'value': 1}]}],
         'Enlarge: "Magic range increased by 1 panel" -- unconditional'),
    341: ([{'family': 'power', 'effects': [{'value': 3, 'per': 'map_enemy'}]}],
          'Violent Courage: "Attack power increased by # of enemy units on map x 3%" -- per=map_enemy'),
    # P3b: two passes on one id, which one row could not carry
    176: ([{'family': 'move', 'effects': [{'value': 3}]},
           {'family': 'potency', 'effects': [{'stat': 'all', 'value': -30}]}],
          'Chicken Heart: "MV increased by 3, stats decreased by 30%" -- a move row and a potency row. '
          'The text says "stats", so the potency row names all eight; if D4 means the six combat stats '
          'the row is edited, the runtime is not the limit'),
    809: ([{'family': 'potency', 'effects': [{'stat': 'def', 'value': 30}, {'stat': 'res', 'value': 30}]},
           {'family': 'move', 'effects': [{'value': -2}]}],
          'Stone Wall: "Increase DEF/RES by 30%, MV -2" -- a potency row (two stats) and a move row'),
}

# --- D4 rows that stay unsupported, and why ---------------------------------------------------------------
D4_REJECTED = {
    180: 'Rapid Move: needs "SP is at maximum", which is not a condition kind',
    464: 'Sky High: changes movement type to flying, which is the existing `flight` predicate, not a range',
    867: 'Transportation: carry/transport rule, not a move-range amount',
    413: 'Law by Range: magic range +2 *and* 50% more SP -- the SP-cost family still does not exist',
    829: 'Flying Bullets: "limitless" range with a gun -- a sentinel, not an amount the game adds',
    862: 'All Range +: an aura that raises allies\' range -- the aura rows act on dealt/taken/hit/crit only',
    337: 'Accel Shot: power + distance(panels) x 5% -- no per=distance scale and no distance measure',
    344: 'Calm Waters: power +30% on a single target -- target_count needs an action context the pass lacks',
    407: 'Magic Bundle: skill power +30% *and* 50% more SP -- the SP-cost family still does not exist',
    692: 'Accel Element: elemental ATK +10% x panels moved -- needs a distance measure and an element context',
}
# Covered by the family, but the numeric weapon-category id the `weapon` condition needs is not verified:
# d5lib/weaponlevels.WEAPONS is the *mastery* order while the condition reads the equipped item's category
# byte, so assuming they share a 1-based numbering would be an inference.
D4_BLOCKED_ON_EVIDENCE = {
    41: 'Fist Range UP: +1 panel with a fist -- needs a verified equipped-weapon category id',
    44: 'Bow Range UP: +1 panel with a bow -- needs a verified equipped-weapon category id',
}
D4_RESISTANCE = 'resistance and resistance-aura rows (5) need a resistance accumulator, which is not built'

# --- DD2 needs-new-logic rows ----------------------------------------------------------------------------
DD2_COVERED = {
    100: ([{'family': 'power', 'effects': [{'value': 50}]},
           {'family': 'defense_power', 'effects': [{'value': 50}]},
           {'family': 'counter', 'effects': []}],
          'Passiveness: "Increase Attack and Defense Power by 50% and always counter when defending" -- a '
          'power row, a defense_power row and the counter predicate, three rows for one id'),
    430: ([{'family': ['aura', 'dealt'], 'effects': [{'value': 10}],
            'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 3, 'id': 430}]},
           {'family': ['aura', 'taken'], 'effects': [{'value': 10}],
            'conditions': [{'kind': 'near_has', 'of': 2, 'radius': 3, 'id': 430}]}],
          'Demon Experiments: "within 3 panels allies deal 10% more damage and enemies take 10% more" -- a '
          'dealt aura row and a taken aura row, each naming its own relation'),
}
DD2_REVIEW = {
    2012: 'Corrupting Body: "Decrease non-elemental damage taken by 30%. Inflict deprave." -- the taken half '
          'is a row (taken -30, element 0), but "inflict deprave" is not a chance percentage: the game rolls '
          'a status it already has, and no family *adds* a status to an attack. Not counted',
    2090: 'Stone Statue: defence power +% "as long as the unit has not moved" -- no did-not-move condition',
    2111: 'Great Wall: defence power +% but all attacks hit -- no forced-hit rule',
    630: 'T.O. Despair: regen for the heal half, but destroying the Base Panel is a battle-setup action',
}


def load():
    d4 = json.loads(D4.read_text())
    dd2 = json.loads(DD2.read_text())
    return {e['id']: e for e in d4['evilities'] if e['scope'] == 'primary'}, dd2['evilities']


def emitted(entries):
    """the runtime's own verdict: every entry must survive table()"""
    return ev.table({1: entries})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    d4, dd2 = load()
    report = {'d4': {}, 'dd2': {}, 'families': {}}

    rows = {eid: entry for eid, (entry, _why) in D4_COVERED.items()}
    table = ev.table(rows)             # raises if the runtime rejects any entry
    emitted_rows, _conds, _fx = table
    counts = {}
    for row in emitted_rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    report['emitted'] = {'ids': len(rows), 'rows': len(emitted_rows),
                         'shared_ids': sorted(eid for eid, n in counts.items() if n > 1)}

    by_family = {}
    for eid, (entry, why) in sorted(D4_COVERED.items()):
        fams = sorted({f for row in (entry if isinstance(entry, list) else [entry])
                       for f in ([row['family']] if isinstance(row['family'], str) else row['family'])})
        report['d4'][str(eid)] = {'name': d4[eid]['name'], 'families': fams,
                                  'rows': entry if isinstance(entry, list) else [entry],
                                  'source': d4[eid]['d4_effect_rendered'], 'why': why,
                                  'verdict': 'covered-by-extension'}
        for f in fams:
            by_family.setdefault(f, []).append(d4[eid]['name'])
    report['families'] = by_family

    for eid, why in sorted(D4_REJECTED.items()):
        report['d4'][str(eid)] = {'name': d4[eid]['name'], 'source': d4[eid]['d4_effect_rendered'],
                                  'why': why, 'verdict': 'unsupported'}
    for eid, why in sorted(D4_BLOCKED_ON_EVIDENCE.items()):
        report['d4'][str(eid)] = {'name': d4[eid]['name'], 'source': d4[eid]['d4_effect_rendered'],
                                  'why': why, 'verdict': 'blocked-on-evidence'}
    report['d4_resistance'] = D4_RESISTANCE

    new_logic = {k: v for k, v in dd2.items() if v['relation'] == 'needs-new-logic'}
    ev.table({k: entry for k, (entry, _why) in DD2_COVERED.items()})   # the runtime checks every DD2 entry
    report['dd2'] = {
        'needs_new_logic': len(new_logic),
        'covered_by_the_new_passes': len(DD2_COVERED),
        'covered': {k: {'name': new_logic[str(k)]['dd2_name'], 'text': new_logic[str(k)]['dd2_desc'],
                        'value': new_logic[str(k)].get('value'),
                        'rows': entry if isinstance(entry, list) else [entry], 'why': why}
                    for k, (entry, why) in sorted(DD2_COVERED.items()) if str(k) in new_logic},
        'still_unsupported': len(new_logic) - len(DD2_COVERED),
        'reviewed_against_the_new_vocabulary': {
            k: {'name': new_logic[str(k)]['dd2_name'], 'text': new_logic[str(k)]['dd2_desc'],
                'why': why}
            for k, why in DD2_REVIEW.items() if str(k) in new_logic},
        'unreviewed_names': sorted(new_logic[k]['dd2_name'] for k in new_logic
                                   if k not in DD2_REVIEW and k not in DD2_COVERED),
    }

    totals = {'d4_primary': len(d4),
              'd4_covered_by_extension': len(D4_COVERED),
              'd4_moved_by_p3b': 2,
              'd4_rejected_in_the_new_families': len(D4_REJECTED),
              'd4_blocked_on_evidence': len(D4_BLOCKED_ON_EVIDENCE),
              'dd2_needs_new_logic': len(new_logic),
              'dd2_covered_by_extension': len(DD2_COVERED),
              'dd2_moved_by_p3b': len(DD2_COVERED)}
    report['totals'] = totals
    print(json.dumps(totals, indent=1))
    print('emitted:', report['emitted'])
    for family, names in sorted(by_family.items()):
        print(f'  {family}: {len(names)} -- {", ".join(names)}')
    for k, body in report['dd2']['covered'].items():
        print(f"  DD2 {k} {body['name']}: {len(body['rows'])} rows")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
