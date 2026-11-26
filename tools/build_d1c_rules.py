#!/usr/bin/env python3
"""Export the D1C importer's ids/rules/counts as checked-in JSON (SOURCEPREP4-D1C; maintenance tool).

Writes ``d5lib/importers/d1c-roster.json`` (class and unique listings, leases, donors, skill ladders) and
``d5lib/importers/d1c-bank-shapes.json`` (per pack: texture/palette counts of the banks an installed pack
carries, and whether it carries the 21/27 hurt slot).  Both hold ids, counts and SHA-256 text references
only: names and titles are read from the user's own SUBDATA.DAT (or the D5 tables) at build time and
checked against the recorded hashes.

Inputs (read only, maintainer machine): the working copy of the D1C batch lists
(``Research/source-packs/d1c/batches``), the earlier ``d1c-extra-leases.json`` and, for the bank shapes, the
installed packs.  A user never runs this: the output is in the kit.

    python tools/build_d1c_rules.py --batches <Research/source-packs/d1c/batches> --installed <mods folder>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
IMPORTERS = KIT / 'd5lib/importers'
BANK_DIR = Path('files/Anime/ANM_HI_JP.dat')


def text_hash(text):
    return hashlib.sha256(unicodedata.normalize('NFKC', str(text)).strip().encode('utf-8')).hexdigest()


def j(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def roster(batches, extra):
    classes = j(batches / 'classes.json')['classes']
    plan = j(batches / 'skills-plan.json')['classes']
    rows = j(batches / 'uniques.json')['rows']
    over = {int(r['id']): r for r in extra['rows']}
    rows = [over.get(int(r['id']), r) for r in rows]
    leased = j(batches / 'unique-leases.json')['leased']
    leased.update(extra['leases'])
    donors = j(batches / 'unique-donors.json')
    out = dict(schema='d1c-roster/1',
               about='Ids, rules and counts for the D1C importer; names/titles are SHA-256 references resolved '
                     'at build time from the user\'s own game files (SOURCEPREP4-D1C).',
               census_rows=len(j(batches.parent / 'roster/census.json').get('rows', [])))
    out['classes'] = [dict(registry=c['registry'], character_id=c['character_id'], kind=c['kind'],
                           physical=c['physical'], template=c['template'],
                           name_sha256=text_hash(c['name']), template_name_sha256=text_hash(c['template_name']))
                      for c in classes]
    out['skills'] = {k: dict(kind=v['kind'], skills=v['skills']) for k, v in sorted(plan.items())}
    out['uniques'] = [dict(id=r['id'], body=r['body'], shape=r['shape'], disposition=r['disposition'],
                           feasibility=r['feasibility'], note=r['note'], anims=r['anims'], palettes=r['palettes'],
                           name_sha256=text_hash(r['name']), title_sha256=text_hash(r['title']))
                      for r in rows]
    out['leases'] = {k: {f: v[f] for f in ('identity', 'physical', 'shape', 'listing', 'donor', 'kind', 'skills',
                                           'help_id', 'quest_id', 'quest_slot') if f in v}
                     for k, v in sorted(leased.items(), key=lambda kv: int(kv[0]))}
    out['donor_heights'] = donors['donor_heights']
    out['donors'] = [dict(id=r['id'], body=r['body'], shape=r['shape'], kind=r['kind'], body_sha256=r['body_sha256'],
                          source_stand_height=r['source_stand_height'], donor=r['donor'],
                          donor_stand_height=r['donor_stand_height'], height_ratio=r['height_ratio'],
                          donor_name_sha256=text_hash(r['donor_name']))
                     for r in donors['rows']]
    return out


def bank_shapes(installed):
    from d5lib import anm
    doc = {}
    for pack in sorted(Path(installed).glob('D1C_*')):
        banks = {}
        hurt = None
        for bank in sorted((pack / BANK_DIR).glob('anm*.lzs')):
            try:
                a = anm.load(bank)
            except Exception:                                  # noqa: BLE001 - not a bank
                continue
            banks[bank.name] = [len(a.textures), len(a.palettes)]
            if hurt is None and bank.name[3:8].isdigit() and int(bank.name[3:8]) < 10000:
                ids = {x.id for x in a.blocks[0].animations}
                if {1001, 1007} <= ids:
                    hurt = {21, 27} <= ids
        doc[pack.name] = dict(hurt=hurt, banks=banks)
    return dict(schema='d1c-bank-shapes/1',
                about='Counts only (textures, palettes) of the banks an installed D1C pack carried when this table '
                      'was exported, and whether its sprite bank carried the 21/27 hurt slot: the wheel-freeze '
                      'reference and the receiver shape for a machine with no installed pack (SOURCEPREP4-D1C).',
                packs=doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batches', type=Path, required=True)
    ap.add_argument('--installed', type=Path)
    ap.add_argument('--extra', type=Path, default=IMPORTERS / 'd1c-extra-leases.json')
    ap.add_argument('--only', choices=('roster', 'shapes'))
    args = ap.parse_args()
    if args.only != 'shapes':
        doc = roster(args.batches, j(args.extra))
        (IMPORTERS / 'd1c-roster.json').write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        print('d1c-roster.json', len(doc['classes']), 'classes', len(doc['uniques']), 'uniques', len(doc['leases']), 'leases')
    if args.only != 'roster':
        if not args.installed:
            ap.error('--installed is needed for the bank shapes')
        doc = bank_shapes(args.installed)
        (IMPORTERS / 'd1c-bank-shapes.json').write_text(json.dumps(doc, indent=1) + '\n', encoding='utf-8')
        print('d1c-bank-shapes.json', len(doc['packs']), 'packs')


if __name__ == '__main__':
    main()
