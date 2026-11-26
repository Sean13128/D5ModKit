#!/usr/bin/env python3
"""C4 innate (unique) evility rows for the D4 class packs that have none: worksheet + gate arithmetic.

Twenty installed D4 class packs set `char.dat evility1 = 0` and ship no `kind 1` Skill row of their own,
so the class shows no UNIQUE evility (playtest C4, Cu Sith).  PTFIX2 built the 20 packs that *already
had* such a row and left these 20 open.  This tool answers, with the project's own files, whether a row
can be shipped today:

1. Which D4 evility is each class's unique one (the d4-review ledgers, `roles: ["innate"]`).
2. What D4 says it does (name, text, value -- `mvp-evility-sweep/catalogs.json`, the reviewed extraction).
3. What the review already decided about carrying it (verdict / path / `needs`).
4. Whether the Skill table has room for the row at all: the game's per-unit known-evility bitset is
   indexed by ROW POSITION and refuses >= 1000 (`0x14015e630`, `0x1407c0a0`, transcribed by PTFIX2), the
   installed table is 998 rows, so the headroom is 2 rows -- fewer than the 20 rows this needs.

It writes the worksheet and the per-class proposed row (all 24 fields, the same shape as the packs'
existing kind-1 rows) so the rows can be emitted unchanged once there is headroom and a carrier.  It
writes nothing else: `--apply` is deliberately not implemented, because shipping a row today would break
the 1000-row gate and, for every one of the 20, a row with no carrier would display an effect the game
does not apply (NORTH-STAR: approximations are labelled, never silent).

    python tools/innate_rows_worksheet.py --out <playtest>/regen-innate-rows.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path('/Volumes/Data/Projects/D5')
REVIEW = BASE / 'Subprojects/Engine-Extensions/d4-review'
CATALOGS = BASE / 'Research/d4-expansion-20261018/mvp-evility-sweep/catalogs.json'
BUNDLE = BASE / 'Builds/LIVE5_TEST3-20261028/mods'
CAP = 1000          # d5lib/ordercheck.py: the known-evility bitset refuses an index >= 1000
KIT_BAND = (7000, 7999)

# PTFIX2 §3: the 20 packs with neither evility1 nor a kind-1 row of their own.
PENDING = ['1050', '1060', '1070', '1170', '1190', '1200', '1220', '1240', '1250', '2020',
           '2070', '2080', '2090', '2110', '2120', '2130', '2170', '2180', '2190', '2200']


def ledgers():
    """Every reviewed class record, batch 1 ledger first, then batches 2-4 verdicts."""
    out = {}
    files = [('LEDGER.json', 'classes'), ('verdicts-batch2.json', 'classes'),
             ('verdicts-batch3.json', 'classes'), ('verdicts-batch4.json', 'classes')]
    for name, key in files:
        path = REVIEW / name
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        rows = data[key]
        rows = rows if isinstance(rows, list) else list(rows.values())
        for row in rows:
            if row.get('mod_id'):
                out.setdefault(row['mod_id'], row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--database', help='the installed Database_0.dat, read only, for the real row count')
    args = ap.parse_args()

    catalogs = json.loads(CATALOGS.read_text())['d4']
    reviews = ledgers()

    # how many rows the enabled set already has: the merged Skill.dat the game would see
    total_rows = 0
    for mod in sorted(BUNDLE.iterdir()):
        p = mod / 'patches' / 'db' / 'Skill.dat.json'
        if p.is_file():
            total_rows += len(json.loads(p.read_text())['added'])
    vanilla_rows = 796                      # PTFIX2 §1: the vanilla table

    rows, blocked = [], []
    for sid in PENDING:
        mod = f'D4_Class_{sid}'
        cls = reviews.get(mod)
        if not cls:
            blocked.append(dict(mod=mod, reason='no reviewed class record'))
            continue
        fam = cls.get('target_family') or cls.get('family')
        innate = [e for e in cls['evilities'] if 'innate' in (e.get('roles') or [])]
        if not innate:
            blocked.append(dict(mod=mod, reason='no innate evility in the review record'))
            continue
        e = innate[0]
        d4 = catalogs.get(str(e['d4_id']), {})
        desc = (d4.get('desc') or e.get('d4_text') or '').rstrip()
        row = {
            'id': None,                     # a lease from the kit band, once there is room
            'name_JP': d4.get('name') or e.get('name'), 'name_EN': d4.get('name') or e.get('name'),
            'name_FR': d4.get('name') or e.get('name'), 'name_CHN': d4.get('name') or e.get('name'),
            'name_KOR': d4.get('name') or e.get('name'),
            'slot_cost': 0,
            'desc_JP': desc, 'desc_EN': desc, 'desc_FR': desc, 'desc_CHN': desc, 'desc_KOR': desc,
            'kind': 1, 'effect_group': 0,
            'value1': d4.get('value', 0) if d4.get('value') not in (None, 0xFFFFFFFF) else 0,
            'value2': 0,
            'source': 4, 'category': 0, 'subcategory': 0, 'mana_cost': 0, 'shop_rank': 0,
            'owner': fam, 'class_order': 0, 'version_group': 100,
        }
        rows.append(dict(mod=mod, family=fam, d4_id=e['d4_id'], d4_name=row['name_EN'],
                         d4_text=desc, d4_value=row['value1'], d4_mana=d4.get('mana'),
                         verdict=e.get('verdict'), path=e.get('path'),
                         needs=e.get('needs'), why=e.get('why'), proposed_row=row))

    headroom = CAP - total_rows
    merged = None
    if args.database:
        import re
        import subprocess
        out = subprocess.run([sys.executable, str(Path(__file__).parent / 'check_table_order.py'),
                              '--database', args.database], capture_output=True, text=True)
        hit = re.search(r'Skill\.dat: (\d+) rows', out.stdout + out.stderr)
        if hit:
            merged = int(hit.group(1))
            headroom = CAP - merged
    report = dict(
        schema='d4-innate-rows/1',
        question='build the unique (kind 1) row for the 20 packs that have none',
        answer='not shippable today: 0 of 20 have a carrier the review accepts, and the table is 2 rows '
               'short of the space 20 rows need',
        table=dict(vanilla_rows=vanilla_rows, bundle_added_rows=total_rows,
                   installed_merged_rows=merged,
                   estimated_merged=vanilla_rows + total_rows, bitset_cap=CAP,
                   headroom_rows=headroom, rows_needed=len(rows),
                   source='PTFIX2-REPORT §1 (0x14015e630 / 0x1407c0a0 u32 < 1000); '
                          'tools/check_table_order.py on the installed Database_0.dat'),
        verdicts={v: sum(1 for r in rows if r['verdict'] == v) for v in {r['verdict'] for r in rows}},
        needs_breakdown=sorted({r['needs'] for r in rows}),
        classes=rows, blocked=blocked,
    )
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(f'{len(rows)} class(es) analysed, {len(blocked)} with no record')
    print(f'table: {total_rows} added rows + {vanilla_rows} vanilla = {vanilla_rows + total_rows}, '
          f'cap {CAP}, headroom {headroom}, rows needed {len(rows)}')
    print('verdicts:', report['verdicts'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
