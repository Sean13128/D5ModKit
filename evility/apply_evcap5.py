#!/usr/bin/env python3
"""Apply the EVCAP5 fix to whatever d5lib/dbpatch.py a kit has (idempotent, refuses to guess).

Why a patcher and not a file: the Kit's `dbpatch.py` moves between lines (TEST16 ships 5c931430,
25,353 B; TEST18B ships 819818b5, 31,408 B; the installed kit was on a third, 1dde5c0c, 26,238 B
while this ran), so copying one line's file over another would drag unrelated changes along.  This
inserts exactly the fix — one function and the two places that call it — and refuses if the anchors
it needs are not there.

    python apply_evcap5.py <path to kit>/d5lib/dbpatch.py            # dry run, prints the change
    python apply_evcap5.py <path to kit>/d5lib/dbpatch.py --write    # applies in place

Refuses: an already-patched file (does nothing, says so), a file without the two `_set(row, name, v,
warn, table.name)` call sites inside `apply_patch`, or a file where a marker is half present.
"""
import argparse
import hashlib
import sys

ANCHOR_DEF = 'RESERVED_NAMES = {"Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy"}'
ANCHOR_TAIL = '    if strict and warn:\n        raise ValueError("\\n".join(warn))\n    return warn'
LOOP = ('    for _row in table.rows:            # EVCAP5: every row this patch touched, added or inserted\n'
        '        fix_evility_category(_row, table.name)\n')

BLOCK = '''
# A learnable evility's `category` is which tab of the evility list it appears under (the screen filters with
# `category == tab || subcategory == tab`, tab 0 = no filter).  Not one of the game's own 587 learnable rows has
# category 0; a row with 0 is only reachable on the unfiltered tab, so an imported evility would vanish from the
# list as soon as a player picks any category tab (and would never appear in a category-tabbed pick list).
# These are the categories the game's own learnable rows of each effect group use most often (measured on the
# vanilla table); 1 is the fallback for a group the game does not use.
EVILITY_CATEGORY = {0: 9, 1: 9, 2: 1, 3: 2, 4: 1, 5: 1, 6: 1, 7: 4, 8: 11, 9: 5, 10: 1, 11: 5, 12: 12,
                    13: 12, 14: 2, 15: 5, 16: 12, 17: 1, 18: 1, 19: 1, 20: 1, 21: 2, 22: 1, 24: 18,
                    25: 1, 26: 1, 27: 18, 28: 14, 29: 2, 30: 1}


def fix_evility_category(row, tname):
    """Give a learnable evility row a display category if it has none.  -> True if the row changed.

    Only rows the game would offer to equip are touched (kind 0 = normal, and a Mana cost to learn); an
    innate/unique/rank row and a system row keep whatever they have.  A patch that names a category is never
    overridden: this only fills a 0 that no learnable row of the game's own table has.
    """
    if str(tname).lower() != "skill.dat":
        return False
    if "category" not in row or row["category"]:
        return False
    if row.get("kind") != 0 or not row.get("mana_cost"):
        return False
    row.set("category", EVILITY_CATEGORY.get(row.get("effect_group"), 1))
    return True
'''


def patch_text(text):
    if "fix_evility_category" in text:
        return text, 'already patched'
    if ANCHOR_DEF not in text:
        raise SystemExit('refused: the RESERVED_NAMES anchor is not in this file')
    if text.count(ANCHOR_TAIL) != 1:
        raise SystemExit(f'refused: expected 1 `if strict and warn` tail of apply_patch, '
                         f'found {text.count(ANCHOR_TAIL)}')
    text = text.replace(ANCHOR_DEF, ANCHOR_DEF + '\n' + BLOCK.rstrip('\n'), 1)
    text = text.replace(ANCHOR_TAIL, LOOP + ANCHOR_TAIL, 1)
    if text.count('fix_evility_category(_row, table.name)') != 1:
        raise SystemExit('refused: the call did not land')
    return text, 'patched'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()
    raw = open(args.path, 'rb').read()
    before = hashlib.sha256(raw).hexdigest()
    text, what = patch_text(raw.decode('utf-8'))
    print(f'{args.path}\n  before {before} ({len(raw)} B)\n  {what}')
    if what == 'already patched' or not args.write:
        if args.write and what == 'already patched':
            print('  nothing written')
        return
    open(args.path, 'wb').write(text.encode('utf-8'))
    after = hashlib.sha256(open(args.path, 'rb').read()).hexdigest()
    print(f'  after  {after} ({len(text)} B)')


if __name__ == '__main__':
    main()
