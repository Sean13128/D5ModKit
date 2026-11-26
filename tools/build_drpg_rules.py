#!/usr/bin/env python3
"""Export the DRPG importer's ids/rules/counts as checked-in JSON (SOURCEPREP4-DRPG; maintenance tool).

Writes ``d5lib/importers/drpg-roster-0..3.json`` (the 146 reviewed groups with their mapped abilities; every game text
is an ``@text`` SHA-256 reference or ``@authored`` wording) and ``d5lib/importers/drpg-bank-shapes.json`` (per pack:
texture/palette counts of the banks an installed pack carries: the wheel-freeze reference for a machine with no
installed pack).  A user never runs this: the output is in the kit.

Inputs (read only, maintainer machine): the research mapping, grouping decisions, the mapping tools, the decoded
masters and D5 catalogs (``DRPG_DATA``, ``DRPG_D5_CATALOGS``, ``DRPG_MAPPING_TOOLS`` are set from the arguments for
the families that were regrouped), a prepared source folder and the Disgaea 5 install (the text pool), and for the
shapes the installed packs.

    python tools/build_drpg_rules.py roster --mapping M --grouping G --masters DIR --catalogs FILE --tools DIR \
        --source <prepared folder> --game-path <Disgaea 5> --state <state folder>
    python tools/build_drpg_rules.py shapes --installed <mods folder>
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
IMPORTERS = KIT / 'd5lib/importers'
# Keys whose string values are game text (JP names, effect text, D5 names) or this project's wording about it.
TEXT_KEYS = {'rpg_name', 'rpg_text', 'effect', 'name', 'name_jp', 'en', 'jp', 'cv_name', 'd5_name', 'd5_name_jp',
             'desc', 'english_source_name', 'reason', 'condition'}
# Provenance pins name machine files; the roster records the logical names instead (hashes are kept).
PIN_NAMES = {'character.json': 'masters/character.json', 'charactercommand.json': 'masters/charactercommand.json',
             'command.json': 'masters/command.json', 'leaderskill.json': 'masters/leaderskill.json',
             'd5-catalogs.json': 'd5-catalogs.json'}


def has_non_ascii(value):
    return any(ord(ch) > 127 for ch in value)


def refer(node, pool, key=None, stats=None):
    from d5lib.importers import _drpg_roster as r
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == 'file' and isinstance(v, str) and '/' in v:        # a provenance pin: logical name, hash kept
                v = PIN_NAMES.get(Path(v).name, Path(v).name)
            out[k] = refer(v, pool, k, stats)
        return out
    if isinstance(node, list):
        return [refer(v, pool, key, stats) for v in node]
    if isinstance(node, str) and node:
        if key in TEXT_KEYS:
            if node in pool:
                stats['text'] += 1
                return {'@text': r.text_sha(node)}
            if not has_non_ascii(node):
                stats['authored'] += 1
                return {'@authored': node}
            parts, last = [], 0
            for m in r.RUN.finditer(node):
                if node[last:m.start()]:
                    parts.append(node[last:m.start()])
                run = m.group(0)
                if r.is_punctuation(run):
                    parts.append(run)
                elif run in pool:
                    parts.append({'@text': r.text_sha(run)})
                elif pool.find_parent(run):
                    of, at = pool.find_parent(run)
                    parts.append({'@text': r.text_sha(run), 'of': of, 'at': at})
                else:
                    raise SystemExit(f'non-ASCII run under {key!r} is in no source: {run!r} in {node[:40]!r}')
                last = m.end()
            if node[last:]:
                parts.append(node[last:])
            stats['parts'] += 1
            return {'@parts': parts}
        if has_non_ascii(node):
            raise SystemExit(f'non-ASCII value under non-text key {key!r}: {node[:30]!r}')
    return node


def roster(args):
    from d5lib.importers import _drpg_roster as r, _drpg_source, drpg
    os.environ['DRPG_DATA'] = str(args.masters)
    os.environ['DRPG_D5_CATALOGS'] = str(args.catalogs)
    os.environ['DRPG_MAPPING_TOOLS'] = str(args.tools)
    mapping = json.loads(Path(args.mapping).read_text())
    decisions = json.loads(Path(args.grouping).read_text())
    chars = drpg.reviewed_characters(mapping['characters'], decisions)
    drpg_data = _drpg_source.data(args.source)
    from d5lib.importers._drpg_build import source_fs
    fs = source_fs(dict(game_path=args.game_path, state_root=args.state))
    try:
        pool = r.TextPool.from_sources(drpg_data, fs)
    finally:
        fs.reset()
    stats = dict(text=0, authored=0, parts=0)
    groups = []
    for character, best in chars:
        groups.append(dict(character=refer(copy.deepcopy(character), pool, None, stats), best=best))
    doc = dict(schema=r.SCHEMA,
               about='Reviewed Disgaea RPG groups (ids, rules, verdicts, mapped abilities). Text is an @text SHA-256 '
                     'reference resolved at build time from the prepared masters and the Disgaea 5 tables, or @authored '
                     'project wording. No game text (SOURCEPREP4-DRPG).',
               groups=groups)
    # round trip: the references resolve to exactly the old records
    back = [(r.resolve(g['character'], pool), g['best']) for g in groups]
    for (old, _b), (new, _b2) in zip(chars, back):
        a, b = json.loads(json.dumps(old)), json.loads(json.dumps(new))
        for pins in (a.get('mapping_provenance') or {}, b.get('mapping_provenance') or {}):
            for pin in pins.get('pins', []):
                pin['file'] = PIN_NAMES.get(Path(pin['file']).name, Path(pin['file']).name)
        assert a == b, old['base_id']
    per = -(-len(groups) // len(r.PARTS))
    for i, part in enumerate(r.PARTS):
        sub = dict(doc, groups=groups[i * per:(i + 1) * per], part=i)
        part.write_text(json.dumps(sub, separators=(',', ':'), sort_keys=True) + '\n', encoding='utf-8')
        assert part.stat().st_size < 1 << 20, part
    print('drpg-roster-*.json', len(groups), 'groups', stats)


def shapes(args):
    from d5lib import anm, gamefs
    doc, icons = {}, {}
    for pack in sorted(Path(args.installed).iterdir()):
        files = pack / 'files'
        if not (pack.name.startswith('DRPG_') or pack.name == 'Zed') or not files.is_dir():
            continue
        banks = {}
        for bank in sorted(files.rglob('*.lzs')):
            try:
                a = anm.parse(gamefs.decode_member(bank.read_bytes()))
            except Exception:                                  # noqa: BLE001 - not a bank
                continue
            banks[bank.relative_to(files).as_posix()] = [len(a.textures), len(a.palettes)]
        key = 'DRPG_Core_Zed_94' if pack.name == 'Zed' else pack.name
        doc[key] = banks
        listing = pack / 'patches/outfits/outfits.json'
        if listing.is_file() and (json.loads(listing.read_text()).get('icons')):
            icons[key] = json.loads(listing.read_text())['icons']
    out = dict(schema='drpg-bank-shapes/1',
               about='Counts only (textures, palettes) of the banks an installed DRPG pack carried when this table was '
                     'exported: the wheel-freeze reference for a machine with no installed pack (SOURCEPREP4-DRPG). '
                     'The installed Zed pack is recorded under the importer folder of base 94.',
               icons=icons, packs=doc)
    (IMPORTERS / 'drpg-bank-shapes.json').write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print('drpg-bank-shapes.json', len(doc), 'packs')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('roster')
    for name in ('mapping', 'grouping', 'masters', 'catalogs', 'tools', 'source', 'game-path', 'state'):
        a.add_argument('--' + name, type=Path, required=True)
    b = sub.add_parser('shapes')
    b.add_argument('--installed', type=Path, required=True)
    args = ap.parse_args()
    {'roster': roster, 'shapes': shapes}[args.cmd](args)


if __name__ == '__main__':
    main()
