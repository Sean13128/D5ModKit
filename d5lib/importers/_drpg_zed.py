"""Run the existing research mapping rules for reviewed DRPG families.

Maintainer step only (SOURCEPREP4-DRPG): ``tools/build_drpg_rules.py roster`` uses it, with DRPG_DATA,
DRPG_D5_CATALOGS and DRPG_MAPPING_TOOLS naming the private research inputs, to produce ``drpg-roster.json``.
The importer never calls it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path


# Match drpg_map_roster.py's reviewed selection, including its limited coverage.
_LEADER_FIELDS = ('m_leader_skill_id', 'additional_m_leader_skill_id',
                  'm_leader_skill_id_sub_1', 'm_leader_skill_id_sub_2',
                  'm_leader_skill_id_sub_3')


def _read(path, pins, setting):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FileNotFoundError(
            f'DRPG family mapping requires readable input {path}; restore the private '
            f'research inputs or set {setting} to their location. '
            'Empty donor mappings are not substituted.'
        ) from exc
    pins.append({'file': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
    return raw


def _tool(path, pins):
    """Load definitions through importlib without writing adjacent .pyc files."""
    raw = _read(path, pins, 'DRPG_MAPPING_TOOLS')
    spec = importlib.util.spec_from_file_location('_corerpg1_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def mapped_zed(family):
    """Return a mapping.json-shaped character, with mapping_provenance pins.

    ``family`` is the Zed row from families.json. DRPG_DATA,
    DRPG_D5_CATALOGS and DRPG_MAPPING_TOOLS can relocate existing inputs.
    Missing masters, referenced abilities or catalogs fail explicitly.
    """
    if family['base_id'] != 94 or {v['id'] for v in family['variants']} != {94, 182}:
        raise ValueError('mapped_zed requires the reviewed Zed94 + look182 family')
    return mapped_family(family)


def mapped_family(family):
    """Map only the assigned looks using the existing reviewed research rules.

    Regrouping must recompute abilities: the snapshot stores family aggregates,
    so copying them after moving a look would retain another person's skills.
    """
    try:
        data = Path(os.environ['DRPG_DATA'])
        catalogs = Path(os.environ['DRPG_D5_CATALOGS'])
        tools = Path(os.environ['DRPG_MAPPING_TOOLS'])
    except KeyError as exc:
        raise FileNotFoundError(f'{exc.args[0]} is not set: regrouping DRPG families is a maintainer step '
                                '(tools/build_drpg_rules.py); the importer reads drpg-roster.json instead') from exc
    pins = []
    masters = {name: json.loads(_read(data / (name + '.json'), pins, 'DRPG_DATA'))
               for name in ('character', 'charactercommand', 'command', 'leaderskill')}
    cat = json.loads(_read(catalogs, pins, 'DRPG_D5_CATALOGS'))
    mapper = _tool(tools / 'drpg_map_d5.py', pins)
    leader_mapper = _tool(tools / 'drpg_map_leader.py', pins)
    chars = {r['id']: r for r in masters['character']}
    commands = {r['id']: r for r in masters['command']}
    leaders = {r['id']: r for r in masters['leaderskill']}
    ids = [v['id'] for v in family['variants']]
    absent = [i for i in ids if i not in chars]
    if absent:
        raise ValueError(f'DRPG character master rows missing: {absent}; restore DRPG_DATA')
    command_sources = {}
    leader_sources = {}
    # Same family-wide selection and base weapon rule as drpg_map_roster/apply.
    for cid in ids:
        for row in masters['charactercommand']:
            if row['m_character_id'] == cid:
                command_sources[row['m_command_id']] = cid
        for field in _LEADER_FIELDS:
            lid = chars[cid].get(field) or 0
            if lid:
                leader_sources[lid] = cid
    if not command_sources and not leader_sources:
        raise ValueError('DRPG group has no linked commands or leader skills; appearance-only groups are deferred')
    missing_commands = sorted(set(command_sources) - commands.keys())
    missing_leaders = sorted(set(leader_sources) - leaders.keys())
    if missing_commands or missing_leaders:
        raise ValueError(f'DRPG ability master rows missing: commands={missing_commands}, '
                         f'leaders={missing_leaders}; restore complete DRPG_DATA')
    d5 = mapper.D5(cat)
    index = leader_mapper.build_ev_index(cat['Skill.dat'])
    if not index or not d5.magic:
        raise ValueError('DRPG mapping requires populated Skill.dat and magic.dat D5 catalogs')
    cm = []
    for command_id in command_sources:
        row = commands[command_id]
        mapped = mapper.map_command(row, d5, chars[family['base_id']].get('best_weapon_type'))
        mapped.update(rpg_id=row['id'], rpg_name=row.get('name'), sp=row.get('sp_min'),
                      element=mapper.ELEMENT.get(row.get('attr')),
                      targets=sorted({mapper.TARGET.get(t, str(t))
                                      for t in row.get('effect_targets') or []}),
                      effect=row.get('description_effect'))
        cm.append(mapped)
    ls = [leader_mapper.map_ls(leaders[i], index) for i in sorted(leader_sources)]
    looks = [dict(id=v['id'], en=v.get('english_name'), jp=v.get('japanese_name'),
                  type=v.get('type'), outfits=v.get('catalog_outfits') or [],
                  art={k: bool(x) for k, x in (v.get('art') or {}).items()})
             for v in family['variants']]
    for look in looks:
        if family['base_id'] == 94 and look['id'] == 182:
            look['english_source_name'] = look['en']
            look['en'] = 'Infinite Super Reincarnation Zed'
    main = next((r['rpg_id'] for r in ls if r['rpg_id'] % 10 == 1), None)
    return dict(
        base_id=family['base_id'], name=family['base_name'], name_jp=chars[family['base_id']].get('name'),
        kind=('monster' if all(l['type'] == 'monster' for l in looks) else 'humanoid'), origin_game=family.get('source_game') or 'unknown',
        origin_confidence=family.get('source_game_confidence'),
        cv_name=chars[family['base_id']].get('cv_name'), distinct_looks=len(looks),
        looks=looks, outfits_plan=[dict(look_id=v['id'], name=v['en'] or v['jp'],
                                       type=v['type']) for v in looks if v['id'] != family['base_id']],
        already_installed_outfits=sum(bool(v['outfits']) for v in looks),
        commands=cm, leader_skills=ls, leader_skill_main=main,
        mapping_provenance=dict(
            status='newly run same-rule mappings for the exact reviewed look membership',
            command_rule='drpg_map_d5.map_command', leader_rule='drpg_map_leader.map_ls',
            selection_rule='drpg_map_roster family links; drpg_map_apply base weapon',
            leader_fields=list(_LEADER_FIELDS),
            excluded_additional_sub_fields='Same selection as existing roster tool; not a full ability census',
            pins=pins, character_ids=ids,
            command_source_characters={str(k): v for k, v in command_sources.items()},
            leader_source_characters={str(k): v for k, v in leader_sources.items()}))
