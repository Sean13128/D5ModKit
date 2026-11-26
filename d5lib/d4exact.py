"""Apply reviewed D4 extension rows to a staged import; never installs.

A Skill.dat ID has one source-4 owner. If two imports need the same D4 ID,
callers must reject that collision rather than silently changing ownership.
"""
import copy
import json
from pathlib import Path

from . import d4pilotfix, textfmt


def apply_exact(mod_root, emission, profile, owner, occupied, prior_map=None, unique_ids=None):
    """Add exact owned rows and replace explicitly identified older aliases.

    occupied includes original Skill.dat IDs and every other mod's Skill.dat,
    behavior and alias claims, including disabled mods. prior_map maps source
    D4 IDs to alias IDs in this mod, not donor IDs. Returns a per-ID receipt.
    unique_ids (when given) is the set of evility ids that may fill an innate slot;
    the mod's char rows are then rewritten to keep only those (see d4pilotfix).
    """
    root = Path(mod_root)
    prior_map = {int(k): int(v) for k, v in (prior_map or {}).items()}
    owned = {}
    for rank_index, rank in enumerate(profile):
        for item in [rank['innate_evility']] + rank['evilities']:
            sid = int(item['id'])
            if sid:
                owned.setdefault(sid, []).append((rank_index, item,
                    sid == int(rank['innate_evility']['id'])))
    exact = {int(x['d4_id']): int(x['d5_id']) for x in emission['exact']}
    chosen = {sid: exact[sid] for sid in owned if sid in exact}
    if len(set(chosen.values())) != len(chosen):
        raise ValueError('Duplicate exact target IDs')
    if any(target != 8000 + sid for sid, target in chosen.items()):
        raise ValueError('Unexpected exact ID scheme')
    collisions = set(chosen.values()) & set(map(int, occupied))
    if collisions:
        raise ValueError('Exact IDs already occupied: ' + ', '.join(map(str, sorted(collisions))))
    skill_path = root / 'patches/db/Skill.dat.json'
    patch = json.loads(skill_path.read_text()) if skill_path.exists() else {'table': 'Skill.dat', 'added': []}
    if patch.get('table') != 'Skill.dat' or 'rows' in patch:
        raise ValueError('Unsupported Skill.dat patch layout')
    additions = patch.setdefault('added', [])
    old_ids = {prior_map[s] for s in chosen if s in prior_map}
    existing = {int(row['id']) for row in additions}
    if set(chosen.values()) & existing:
        raise ValueError('Exact ID already present in staged mod')
    if not old_ids <= existing:
        raise ValueError('Prior alias is absent from staged Skill.dat')
    skill_source = {int(row['id']): row for row in emission['mod_files']['patches/db/Skill.dat.json']['added']}
    behavior_source = emission['mod_files']['patches/evilities/evilities.json']['evilities']
    behavior_path = root / 'patches/evilities/evilities.json'
    behavior = json.loads(behavior_path.read_text()) if behavior_path.exists() else {'evilities': {}}
    if set(map(int, behavior['evilities'])) & set(chosen.values()):
        raise ValueError('Behavior ID already present in staged mod')
    additions[:] = [row for row in additions if int(row['id']) not in old_ids]
    receipt = []
    for sid, target in sorted(chosen.items()):
        if target not in skill_source or str(target) not in behavior_source:
            raise ValueError(f'Incomplete emission for D4 ID {sid}')
        instances = owned[sid]
        innate = any(x[2] for x in instances)
        row = copy.deepcopy(skill_source[target])
        textfmt.fix_row(row)
        mana = next((x[1].get('mana') for x in instances if x[1].get('mana')), 0)
        row.update(source=4, owner=int(owner), class_order=0, kind=int(innate),
                   mana_cost=mana if isinstance(mana, int) and 0 < mana < 0xffffffff else 0)
        if innate:
            row['slot_cost'] = 0
        else:
            # A D5 common evility carries a slot cost; 0 made these free to equip and
            # is what a unique row has (owner playtest 2, class evilities shown as UNIQUE).
            row['slot_cost'] = d4pilotfix.slot_cost_for_mana(row['mana_cost'])
        additions.append(row)
        behavior['evilities'][str(target)] = copy.deepcopy(behavior_source[str(target)])
        receipt.append(dict(d4_id=sid, target_id=target, first_rank=min(x[0] for x in instances)+1,
                            innate=innate, replaced=prior_map.get(sid)))
    replacements = {prior_map[sid]: target for sid, target in chosen.items() if sid in prior_map}
    char_path = root / 'patches/db/char.dat.json'
    char = json.loads(char_path.read_text()) if char_path.exists() else None
    if char:
        for row in list(char.get('rows', {}).values()) + char.get('added', []):
            for n in range(1, 5):
                key = f'evility{n}'
                if row.get(key) in replacements:
                    row[key] = replacements[row[key]]
        # An innate exact row must be equipped, not merely emitted: the donor path
        # leaves the slot empty when the D4 innate had no reviewed mapping.
        innate_targets = [r['target_id'] for r in receipt if r['innate']]
        if innate_targets:
            from .dbpatch import EVILITIES
            for row in list(char.get('rows', {}).values()) + char.get('added', []):
                if int(row.get('id', -1)) != int(owner):
                    continue
                present = {row.get(key) for key in EVILITIES}
                for target in innate_targets:
                    if target in present:
                        continue
                    free = next((key for key in EVILITIES if not row.get(key)), None)
                    if free is None:
                        raise ValueError('No free innate evility slot for exact row ' + str(target))
                    row[free] = target
                    present.add(target)
                row['evility_count'] = sum(1 for key in EVILITIES if row.get(key))
    # The alias handler has two formats, class descriptor and character aliases.
    alias_path = root / 'patches/evilities/aliases.json'
    aliases = json.loads(alias_path.read_text()) if alias_path.exists() else None
    if aliases is not None:
        for old in old_ids:
            aliases.pop(str(old), None)
    descriptors = []
    for path in (root / 'patches/classes').glob('class_*.json'):
        descriptor = json.loads(path.read_text())
        for old in old_ids:
            descriptor.get('evility_alias', {}).pop(str(old), None)
        descriptors.append((path, descriptor))
    def save(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + '\n')
    additions.sort(key=lambda row: int(row['id']))
    save(skill_path, patch)
    save(behavior_path, behavior)
    if char is not None: save(char_path, char)
    if aliases is not None: save(alias_path, aliases)
    for path, descriptor in descriptors: save(path, descriptor)
    if unique_ids is not None:
        d4pilotfix.enforce_innates(root, unique_ids)
        d4pilotfix.set_common_slot_costs(root)
    return receipt


def occupied_ids(skill_table, mods):
    """Read all Skill/behavior/alias claims from the original table and mods."""
    result = {int(row['id']) for row in skill_table.rows}
    for mod in mods:
        patch = mod.load_patch('db', 'Skill.dat.json') or {}
        result.update(int(row['id']) for row in patch.get('added', []))
        result.update(map(int, patch.get('rows', {})))
        result.update(map(int, (mod.load_patch('evilities', 'aliases.json') or {})))
        result.update(map(int, (mod.load_patch('evilities', 'evilities.json') or {}).get('evilities', {})))
        for path in (Path(mod.folder) / 'patches/classes').glob('class_*.json'):
            spec = json.loads(path.read_text())
            result.update(map(int, spec.get('evility_alias', {})))
    return result


def apply_import(mod, emission, profile, owner, skill_table, mods, report):
    """Apply to an import with claims gathered directly from source data."""
    prior = {int(item['d4_id']): int(item['d5_id']) for item in report
             if item.get('kind') == 'evility' and item.get('d5_id') is not None}
    # D5 shows every innate evility of a modded character as a UNIQUE evility, so a class
    # row may carry only its own class evility; commons belong to the shop list.
    unique = {int(r['id']) for r in skill_table.rows if int(r['kind']) == 1}
    skill_path = Path(mod.folder) / 'patches/db/Skill.dat.json'
    if skill_path.exists():
        unique |= {int(r['id']) for r in json.loads(skill_path.read_text()).get('added', [])
                   if int(r.get('kind', 0)) == 1}
    receipt = apply_exact(mod.folder, emission, profile, owner, occupied_ids(skill_table, mods),
                          prior, unique_ids=unique)
    by_source = {row['d4_id']: row for row in receipt}
    for item in report:
        match = by_source.get(item.get('d4_id')) if item.get('kind') == 'evility' else None
        if match:
            item.update(status='exact-extension', d5_id=match['target_id'])
            item.pop('works_like', None)
            item.pop('works_like_name', None)
    return receipt


def existing_mods(game_path, roots):
    """The declared mod roots; the canonical installed directory only when none is declared.

    SOURCEPREP4-D4: the importer always declares its own root (an empty folder on the default path),
    so a machine with no installed packs reads none.  The historical CLI convenience (no roots at
    all) still looks in the game folder.
    """
    from . import modsys
    canonical = Path(game_path) / 'D5ModKit' / 'mods'
    candidates = list(roots)
    if not candidates and canonical.is_dir():
        candidates.append(canonical)
    if not candidates:
        raise ValueError('Exact import needs a canonical or explicit mods root')
    seen, result = set(), []
    for root in candidates:
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Mods root is not a directory')
        for path in sorted(root.iterdir()):
            if path.is_dir() and (path / 'mod.json').is_file():
                path = path.resolve(strict=True)
                if path not in seen:
                    seen.add(path)
                    result.append(modsys.Mod(str(path)))
    return result
