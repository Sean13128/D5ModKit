"""Compile every evility row the bundle would install, the way the finalizer does (offline).

    python tools/carriers2_tablecheck.py /Volumes/Data/Projects/D5/Builds/CARRIERS2-20261030

Reads the profile's enabled folders only (the installer's own set), merges each mod's evilities.json with
d5lib.evility._merge, compiles one table and reports the row/condition/effect census against the budgets.
Exit status 1 when the table does not compile or overflows.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from d5lib import evility as ev      # noqa: E402


def main():
    bundle = Path(sys.argv[1])
    profile = json.loads((bundle / 'profile/LIVE5_TEST16/load_order.json').read_text())
    mods = [m for m in profile if (bundle / 'mods' / m).is_dir()]
    acc = {}
    owned = {}
    for name in mods:
        p = bundle / 'mods' / name / 'patches/evilities/evilities.json'
        if not p.is_file():
            continue
        for k, e in (json.loads(p.read_text()).get('evilities') or {}).items():
            ev._merge(acc, k, e)
            owned.setdefault(int(k), name)
    rows, conds, fx = ev.table(acc)
    print(f'{len(mods)} enabled folders, {len(acc)} evility ids, {len(rows)} table rows '
          f'(budget {ev.MAX_ROWS}), {len(conds)} conditions (budget {ev.MAX_COND}), '
          f'{len(fx)} effects (budget {ev.MAX_FX})')
    for rid in (8187, 8837, 8841):
        n = sum(1 for r in rows if r[0] == rid)
        print(f'  row {rid}: {n} table row(s), owner {owned.get(rid)}')
    bad = []
    if len(rows) > ev.MAX_ROWS:
        bad.append('rows over budget')
    if not all(0 <= r[7] <= 0xFFFFFFFF for r in rows):
        bad.append('filter out of range')
    print('problems:', bad or 'none')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
