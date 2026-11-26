#!/usr/bin/env python3
"""Build the D4 importer's checked-in rule data (SOURCEPREP4-D4).  Maintainer tool, not used at build time.

Reads the reviewed tables the D4 lanes kept under ``Research/`` (the October breadth checkpoint, the
reviewed completed mapping, the two exact-emission tables, the per-class reserved-id lists, the recorded
unique build commands, the specials tables) and the installed D4 packs (bank header shapes only), and
writes the kit's ``d5lib/importers/d4-*.json`` files plus ``d5lib/data/d4-common-poses.json``.

No game text is written: every string that equals a user table value (D4 char/evility/skill/help text or
D5 skill/character text), a number-rendered D5 template, or contains one as a piece is stored as a
SHA-256 reference (``{"@text": sha}`` / ``{"@template": sha, "args": [..]}`` / ``{"@segments": [..]}``) and
resolved at build time by ``_d4_source.TextPool``.  Kit-written review sentences stay literal.

    /Volumes/Data/Projects/D5/D5Modkit/.venv-macos/bin/python tools/build_d4_rules.py [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

BASE = Path('/Volumes/Data/Projects/D5')
BREADTH = BASE / 'Research/d4-expansion-20261018/mvp-breadth'
MAPPING_SRC = BASE / 'Research/d4-expansion-20261018/mvp-successor3-inputs-v1/prep-v1/prepared-v2/completed-mapping.json'
EMIT_SRC = BASE / 'Subprojects/Engine-Extensions/d4-evility-map/emit/d4_extension_rows.json'
CAST_EMIT_SRC = BASE / 'Research/source-packs/d4uniq2/emit/d4_extension_rows-cast.json'
SPECIALS_SRC = BASE / 'Research/source-packs/specials'
POSE_SRC = Path('/Volumes/Data/CharForge-Backup/2026-10-16-211736/Build data/character-forge/work/templates/d4-common-poses.json')
D4_ROOT = BASE / 'Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+'
D5_ROOT = BASE / 'Disgaea Source/Disgaea 5 Complete (Steam 803600)'
IMPORTERS = ROOT / 'd5lib/importers'


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def dump(path, doc):
    Path(path).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


# ------------------------------------------------------------------------------------- text references
TEXT_KEY = re.compile(r'(^|_)(name|desc|title|label|text)(_|$)', re.IGNORECASE)


class Scrubber:
    """Turns every text-valued field into a reference (``TextPool.ref``); other strings are left alone."""

    def __init__(self, pool):
        self.pool = pool

    def ref(self, value):
        return self.pool.ref(value) if isinstance(value, str) else value

    def scrub(self, doc, key=''):
        if isinstance(doc, dict):
            if set(doc) & {'@text', '@template', '@segments', '@authored', '@skeleton'}:
                return doc                                    # already a reference
            return {k: self.scrub(v, k) for k, v in doc.items()}
        if isinstance(doc, list):
            return [self.scrub(v, key) for v in doc]
        if isinstance(doc, str) and TEXT_KEY.search(key):
            return self.pool.ref(doc)
        return doc


def build_pool():
    from d5lib.importers import _d4_source
    files = _d4_source.data_dir(explicit=D4_ROOT)
    from d5lib import gamefs
    fs = gamefs.GameFS(str(D5_ROOT))          # the clean depot copy: no installed pack rows
    return files, _d4_source.text_pool(files, fs)


# ------------------------------------------------------------------------------------- data builders
def allocation(scrub):
    plan = read(BREADTH / 'allocation-checkpoint.json')
    families = []
    for row in plan['families']:
        if not row.get('registry_family'):
            continue
        families.append({
            'source_family': int(row['source_family']),
            'registry_family': int(row['registry_family']),
            'name': scrub.ref(row['name']),
            'sprite_family': int(row['sprite_family']),
            'template': int(row['template']) if isinstance(row['template'], int) else row['template'],
            'kind': row['kind'],
        })
    return {'schema': 'd4-allocation/1', 'families': families}


MAPPING_EVILITY_FIELDS = ('relation', 'd4_name', 'desc', 'works_like', 'works_like_name',
                          'reason', 'display_name')
MAPPING_SKILL_FIELDS = ('relation', 'd4_name', 'desc', 'copy_of', 'copy_of_name', 'fields',
                        'experimental', 'reason', 'display_name')


def mapping(scrub):
    src = read(MAPPING_SRC)
    out = {'schema': 1, 'game': 'd4', 'edition': src.get('edition'), 'about': src.get('about'),
           'evilities': {}, 'skills': {}, 'voice': src.get('voice') or {},
           'personalities': src.get('personalities') or {}}
    for sid, row in (src.get('evilities') or {}).items():
        out['evilities'][sid] = scrub.scrub({k: row[k] for k in MAPPING_EVILITY_FIELDS if k in row})
    for sid, row in (src.get('skills') or {}).items():
        entry = scrub.scrub({k: row[k] for k in MAPPING_SKILL_FIELDS if k in row})
        out['skills'][sid] = entry
    out['personalities'] = scrub.scrub(out['personalities'])
    out['voice'] = scrub.scrub(out['voice'])
    return out


def emission(path, scrub):
    src = read(path)
    out = {'schema': src.get('schema') or 'd4-extension-emission/2',
           'exact': [{'d4_id': int(x['d4_id']), 'd5_id': int(x['d5_id'])} for x in src.get('exact') or []],
           'mod_files': {}}
    for rel, doc in (src.get('mod_files') or {}).items():
        out['mod_files'][rel] = scrub.scrub(doc)
    return out


def reserved():
    rows = {}
    for path in sorted(BREADTH.glob('reserved-*.json')):
        rows[path.stem.rsplit('-', 1)[1]] = read(path)
    return {'schema': 'd4-reserved-ids/1', 'families': rows}


def _flag(cmd, name, default=None):
    return cmd[cmd.index(name) + 1] if name in cmd else default


def _flag_all(cmd, name):
    out, i = [], 0
    while i < len(cmd):
        if cmd[i] == name and i + 1 < len(cmd):
            out.append(cmd[i + 1])
            i += 2
        else:
            i += 1
    return out


def _selected_command(sid):
    for directory in ('Research/source-packs/d4uniq3', 'Research/source-packs/d4uniq2',
                      'Research/source-packs/d4uniq'):
        path = BASE / directory / f'build-command-{sid}.json'
        if path.is_file():
            return path
    for name in (f'unique-v4-command-{sid}.json', f'unique-command-{sid}.json'):
        path = BREADTH / name
        if path.is_file():
            return path
    return None


def commands():
    out = {}
    paths = sorted({int(p.stem.rsplit('-', 1)[1]) for p in
                    list(BASE.glob('Research/source-packs/d4uniq*/build-command-*.json')) +
                    list(BREADTH.glob('unique*command-*.json'))})
    for sid in paths:
        path = _selected_command(sid)
        if path is None:
            continue
        cmd = read(path)
        prepared = _flag(cmd, '--prepared-root') or ''
        row = {
            'source_id': int(_flag(cmd, '--source-id', sid)),
            'template_id': int(_flag(cmd, '--template-id', 0)) or None,
            'exclude_source_ids': [int(x) for x in _flag_all(cmd, '--exclude-source-id')],
            'supersede_prefix': list(_flag_all(cmd, '--supersede-prefix')),
            'style': 'v3' if 'prepared-unique-v3' in Path(prepared).parent.name or \
                     'prepared-unique-v3' in str(prepared) else 'cast',
            'recorded_by': path.parent.name,
        }
        for flag, key in (('--identity', 'identity'), ('--physical', 'physical'), ('--target-id', 'target_id')):
            value = _flag(cmd, flag)
            if value is not None:
                row[key] = int(value)
        from d5lib import d4screenart
        for flag, key in (('--face-path', 'face_ids'), ('--cutin-path', 'cutin_ids')):
            ids = []
            for recorded in _flag_all(cmd, flag):
                rid = d4screenart.resource_id(flag, recorded)
                if rid is not None and rid not in ids:
                    ids.append(rid)
                elif rid is None and flag == '--cutin-path' and prepared:
                    # A prepared-image fallback (610's cut-in is its own stand frame): keep the packet frame.
                    try:
                        from pathlib import Path as _P
                        row['cutin_packet_frame'] = _P(recorded).relative_to(_P(prepared)).as_posix()
                    except ValueError:
                        pass
            if ids:
                row[key] = ids
        out[str(sid)] = {k: v for k, v in row.items() if v not in (None, [], '') or k in
                         ('source_id', 'exclude_source_ids', 'supersede_prefix')}
    return {'schema': 'd4-unique-commands/1', 'uniques': out}


def specials(scrub):
    mapping_src = read(SPECIALS_SRC / 'mapping-specials.json')
    uniques = read(SPECIALS_SRC / 'source/d4-uniques.json')
    skills = {}
    for sid, row in (mapping_src.get('skills') or {}).items():
        if row.get('copy_of') is not None:
            skills[sid] = {'copy_of': int(row['copy_of']), 'relation': row.get('relation')}
    chars = {}
    for sid, row in uniques.items():
        chars[sid] = {
            'mod': row['mod'],
            'identity': int(row['identity']),
            'skills': [{'id': int(s['id']), 'level': int(s['level']),
                        'name': scrub.ref(s.get('name') or ''),
                        'desc': scrub.ref(s.get('desc') or '')} for s in row.get('skills') or []],
        }
    return {'schema': 'd4-specials/1', 'mapping': skills, 'characters': chars}


def bank_shapes():
    """Recorded (textures, palettes) of every ANM member of every installed D4 pack."""
    from d5lib import anm, gamefs, offlinepaths
    root = Path(offlinepaths.installed_mods_root())
    folders = {}
    for folder in sorted(root.glob('D4_*')):
        if not folder.is_dir():
            continue
        members = {}
        for path in sorted((folder / 'files').rglob('anm*.lzs')):
            try:
                doc = anm.parse(gamefs.decode_member(path.read_bytes()))
            except Exception:                                   # noqa: BLE001  (unreadable member is not a shape)
                continue
            members[path.relative_to(folder / 'files').as_posix()] = [len(doc.textures), len(doc.palettes)]
        if members:
            folders[folder.name] = members
    return {'schema': 'd4-bank-shapes/1', 'source': 'installed D4 packs, 2026-11-20', 'folders': folders}


def overlay(scrub, additions=False):
    path = IMPORTERS / ('d4-evility-additions.json' if additions else 'd4-evility-overlay.json')
    src = read(path)
    out = {k: v for k, v in src.items() if k != 'source'}
    if 'source' in src:
        out['source'] = src['source']
    out['mods'] = {mod: scrub.scrub(state) for mod, state in (src.get('mods') or {}).items()}
    return out


# ------------------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true',
                    help='write nothing; report whether the kit data equals what this tool would write')
    args = ap.parse_args(argv)

    files, pool = build_pool()
    scrub = Scrubber(pool)
    outputs = {
        IMPORTERS / 'd4-allocation.json': allocation(scrub),
        IMPORTERS / 'd4-mapping.json': mapping(scrub),
        IMPORTERS / 'd4-extension-rows.json': emission(EMIT_SRC, scrub),
        IMPORTERS / 'd4-extension-rows-cast.json': emission(CAST_EMIT_SRC, scrub),
        IMPORTERS / 'd4-reserved-ids.json': reserved(),
        IMPORTERS / 'd4-unique-commands.json': commands(),
        IMPORTERS / 'd4-specials.json': specials(scrub),
        IMPORTERS / 'd4-evility-overlay.json': overlay(scrub, additions=False),
        IMPORTERS / 'd4-evility-additions.json': overlay(scrub, additions=True),
    }
    # TEXTHASH-D4: kit wording that quotes a description (a number-rendered template, a long game string) becomes a
    # reference too (tools/hash_d4_text.py), so a regeneration writes exactly what the checked-in files hold.
    sys.path.insert(0, str(ROOT / 'tools'))
    import hash_d4_text
    for key in ('d4-allocation.json', 'd4-mapping.json', 'd4-extension-rows.json', 'd4-extension-rows-cast.json',
                'd4-specials.json', 'd4-evility-overlay.json', 'd4-evility-additions.json'):
        path = IMPORTERS / key
        outputs[path] = hash_d4_text.hash_document(outputs[path], pool)
    if POSE_SRC.is_file():
        outputs[ROOT / 'd5lib/data/d4-common-poses.json'] = read(POSE_SRC)
    else:
        print(f'warning: pose table source missing ({POSE_SRC}); d5lib/data/d4-common-poses.json not written')
    shapes = bank_shapes()
    if shapes['folders']:
        outputs[IMPORTERS / 'd4-bank-shapes.json'] = shapes
    else:
        print('warning: no installed D4 packs found; d4-bank-shapes.json not written')

    changed = []
    for path, doc in outputs.items():
        rendered = json.dumps(doc, indent=1, ensure_ascii=False) + '\n'
        old = path.read_text(encoding='utf-8') if path.is_file() else None
        if old != rendered:
            changed.append(str(path.relative_to(ROOT)))
            if not args.check:
                dump(path, doc)
        print(f'{"would write" if args.check else "wrote" if old != rendered else "unchanged"} '
              f'{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}')
    print(f'\n{len(outputs)} data files, {len(changed)} changed; pool {len(pool)} strings')
    if args.check and changed:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
