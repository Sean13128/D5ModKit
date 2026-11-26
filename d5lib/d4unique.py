"""Bounded, offline Valvatorez comparison pack; no installer or new native rules.

D4 data stays in the caller's local package. Existing D5 implementations are
explicit adaptations, never claims of D4 equivalence. Bloody Battle is blocked.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from . import database, dbpatch, d4source, modsys, offlinepaths
from .importcore import D4_YIELD_NOTE, donor_yield

CHAR = 'Database/Database_0.dat/char.dat'
TABLES = ('char.dat', 'magic.dat', 'Skill.dat', 'charhelp.dat', 'Quest.dat')
SKILLS = {10011: (10571, 'Impaler Prince'), 10012: (10572, 'Bloody Hole'),
          10013: (10573, 'Tyrant Flughude')}
EVILITIES = {8: (4053, 'Physical Boost'), 815: (6032, 'Absorption'),
             65: (1031, 'Casting Mastery'), 66: (1091, 'Dodge Mastery')}
MOD_ID = 'D4_Valvatorez_Comparison'


def d4_bank(source, source_id):
    """The D4 colour bank a named row wears: `color_id % 10` when its body has that bank, else 0.

    Same rule the prepared packets use (Research/source-packs/d4uniq2/prepare_cast_art.py): Des X 180
    = Desco body 50 colour 54 -> bank 4, Nemo 220 -> 4, God's Part 230 (2048 on the Shroom body) -> 8.
    430 (colour 54 on a 4-bank body) falls back to 0; D4's own rule for that case is not established."""
    row = source.chars[source_id]
    count = len(source.body_palettes(row['sprite']))
    return row['color_id'] % 10 if row['color_id'] % 10 < count else 0


def rotate_banks(banks, first):
    """D4-PAL1: bank `first` moves to slot 0, the others keep D4's order (the game shows slot 0)."""
    banks = list(banks)
    return [banks[first]] + banks[:first] + banks[first + 1:]


def palette_distance(pal, bank):
    """Mean nearest-colour RGB distance from `pal`'s used (alpha > 0) entries to `bank`'s visible
    ones; 0.0 = every colour the palette uses is a colour of that bank (D4TYPES-REVIEW F1)."""
    import numpy as np
    used = pal[pal[:, 3] > 0][:, :3].astype(np.int32)
    vis = bank[bank[:, 3] > 0][:, :3].astype(np.int32)
    if not len(used) or not len(vis):
        return 0.0 if not len(used) else float('inf')
    return float(np.sqrt(((used[:, None, :] - vis[None, :, :]) ** 2).sum(-1)).min(1).mean())


def slot0_gate(sprite, banks, wanted):
    """-> (ok, why): palette slot 0 of a built unique bank must be the D4 bank its packet names."""
    from . import anm
    if not sprite.palettes:
        return False, 'bank has no palette'
    pal = anm.get_palette(sprite, 0)
    dist = [round(palette_distance(pal, b), 1) for b in banks]
    if dist[wanted] == 0:
        return True, f'slot 0 = D4 bank {wanted}'
    return False, (f'slot 0 is not D4 bank {wanted} (distance {dist[wanted]}; nearest D4 bank '
                   f'{dist.index(min(dist))}, distances {dist})')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Originals:
    """Read existing canonical installer backups without constructing Installer."""
    def __init__(self, state):
        self.state = Path(state).resolve(strict=True)
        self.index = json.loads((self.state / 'backups.json').read_text())
        self.reads = {}

    def __call__(self, archive):
        p = Path(archive)
        if p.is_absolute() or '..' in p.parts:
            raise ValueError('Unsafe original archive name')
        item = self.index.get(archive)
        if item is None:
            return None, None  # no recorded modification; GameFS reads original
        mode = item['mode']
        if mode not in ('append', 'full', 'psfs', 'fafs'):
            raise ValueError('No preserved original for ' + archive)
        path = self.state / 'backups' / (archive.replace('/', '__') + ('.full' if mode == 'full' else '.hdr'))
        raw = path.read_bytes()
        self.reads[archive] = dict(path=str(path), bytes=len(raw), sha256=sha(raw), mode=mode)
        return (None, str(path)) if mode == 'full' else (raw, None)

    def verify(self):
        for item in self.reads.values():
            if sha(Path(item['path']).read_bytes()) != item['sha256']:
                raise ValueError('Original backup changed during offline build')


def _one(table, rid, name=None):
    rows = [r for r in table.rows if r['id'] == rid]
    if len(rows) != 1 or (name is not None and rows[0]['name_EN'] != name):
        raise ValueError(f'Missing/ambiguous dependency {rid} {name or ""}')
    return rows[0]


def plan(source, tables, *, target_id=470, supported_ids=None):
    """Pure plan: source integers + existing D5 same-name skills; explicit gaps."""
    from . import charstudio, slots
    supported_ids = slots.DUMMY_ROWS if supported_ids is None else supported_ids
    if type(target_id) is not int or not 10 <= target_id < 1000 or target_id not in supported_ids:
        raise ValueError('Select a caller-verified supported low unique ID')
    existing = [r for r in tables['char.dat'].rows if r['id'] == target_id]
    if len(existing) > 1 or (existing and target_id not in slots.DUMMY_ROWS):
        raise ValueError('Refusing to replace an existing non-dummy character')
    donor = _one(tables['char.dat'], 570, 'Valvatorez')
    if source['id'] != 10 or source['name'] != 'Valvatorez' or source['innate_evility'] != 347:
        raise ValueError('This pilot requires genuine D4 Valvatorez 10 / Bloody Battle 347')
    out = donor.copy()
    charstudio.start_fresh(out)
    for k, stat in enumerate(d4source.STATS):
        out.set('base_' + stat, source['base'][k])
        out.set('apt_' + stat, source['aptitudes'][k])
    for key, value in source['battle'].items():
        out.set(key, value)
    out.set('id', target_id)
    out.set('is_dummy_slot', 0)
    out.set('dlc_group', 0)
    charstudio.set_langs(out, 'name', 'Valvatorez (D4 pilot)')
    charstudio.set_langs(out, 'title', source['title'])
    mappings = []
    for sid, level in source['learnset']:
        if sid not in SKILLS:
            raise ValueError('Unaccounted source unique skill ' + str(sid))
        target, name = SKILLS[sid]
        _one(tables['magic.dat'], target, name)
        charstudio.give_skill(out, target, level)
        mappings.append(dict(kind='skill', source_id=sid, target_id=target,
                             name=name, level=level, status='adapted',
                             reason='Reuse existing D5 skill data, normal/short/skip scripts, effects and audio; D4 equivalence unproven'))
    mappings.append(dict(kind='evility', source_id=347, name='Bloody Battle', status='blocked',
                         reason='D4 native ATK per defeated enemy rule has no verified D5 equivalent; no replacement or alias installed'))
    for eid in source['evilities']:
        if eid not in EVILITIES:
            raise ValueError('Unaccounted source learnable Evility ' + str(eid))
        target, name = EVILITIES[eid]
        row = _one(tables['Skill.dat'], target, name)
        mappings.append(dict(kind='evility', source_id=eid, target_id=target, name=name,
                             status='partial', reason='D5 comparison reference only; no custom ownership, grant, or parameter alias',
                             d5_kind=row['kind'], d5_description=row['desc_EN']))
    return out, mappings


def unique_shape(target_id, identity=None, physical=None, shared=None):
    """The two ids a D4 unique is built on: its char row and its art key.

    Legacy low shape (target_id): one low id is both the char row and the art key.
    Registry shape (DECISIONS 2026-10-27, the shape Overlord ships for Stella 20300): the char
    row id is a registry identity >= 10000 and the art is keyed to a leased low ``physical``
    row, exactly as ``d5lib.nativeimports.unique_identity`` defines it for the D1 Complete batch
    (identity must be a rank-0 multiple of ten outside Overlord's 20000-21999; physical is a low
    art key below 1000).  Nothing here allocates: the caller pins both numbers offline.
    """
    from . import nativeimports
    if shared:
        # D4-NPC1: an NPC whose D4 look is a body the Kit already carries (a built class, a D5 class,
        # a leased unique) is a character of its own -- name, title, stats, learn list -- on the
        # owner's art.  Nothing is written at a new art window: `sprite_id`/`color_id` point at the
        # owner's keys and installing the pack needs the owner (`shares_art_with`).
        identity = int(identity)
        if identity < 10000 or identity % 10 or 20000 <= identity < 22000:
            raise ValueError('a shared-art unique still takes a registry identity >= 10000, multiple of ten')
        return dict(identity=identity, physical=int(shared['color_id']), registry=True,
                    sprite_id=int(shared['sprite_id']), color_id=int(shared['color_id']),
                    shared=dict(shared), keyed=[])
    identity = int(target_id if identity is None else identity)
    physical = int(target_id if physical is None else physical)
    if identity == physical:
        if identity != int(target_id):
            # A caller that names two different low ids is asking for something the game cannot
            # represent: the identity is the char row and it may not also be its own art lease.
            raise ValueError('a unique identity cannot also be its own art lease')
        return dict(identity=identity, physical=physical, registry=False)
    lease = nativeimports.unique_identity(identity, physical)
    return dict(identity=identity, physical=physical, registry=True,
                keyed=lease['keyed'])


# D4 char.dat ``weapon_skills``: each code is 10000 + a magic.dat id (d4source.CHAR_LAYOUT), and the
# id's hundreds digit names the weapon family.  D4 stores no mastery or resistance letters; the set of
# families a row learns is its weapon forte (D4TYPES-REVIEW F5).  Both 7xx attack magic and 8xx
# heal/support are staff skills; 9xx tower skills are not a D5 humanoid weapon.
D4_FORTE_WEAPONS = {1: 'fist', 2: 'sword', 3: 'spear', 4: 'bow', 5: 'gun', 6: 'axe',
                    7: 'staff', 8: 'staff'}
HUMANOID_WEAPONS = ('fist', 'sword', 'spear', 'bow', 'gun', 'axe', 'staff')


def weapon_forte(source_row):
    """-> the D5 humanoid weapon fields a D4 ``weapon_skills`` list names, in first-seen order.

    A missing or empty list (most monster rows) is an empty forte, never an error.
    """
    out = []
    for code in (source_row or {}).get('weapon_skills') or ():
        try:
            skill = int(code) - 10000
        except (TypeError, ValueError):
            continue
        weapon = D4_FORTE_WEAPONS.get(skill // 100) if skill > 0 else None
        if weapon and weapon not in out:
            out.append(weapon)
    return out


def apply_weapon_forte(row, donor, forte):
    """D4TYPES-REVIEW F5 derived rule: each D4 forte weapon takes the donor's best stored weapon
    mastery; every other weapon keeps the donor's value.  Returns the receipt audit entry.

    D4 has no per-character mastery letters, so nothing here is a source value: the letters stay
    the D5 template's, with the template's own best rank standing in for each forte.  Weapon-type
    resistances stay the donor's: D4 char.dat stores only fire/wind/ice resistance.
    """
    donor_values = {weapon: int(donor['mastery_' + weapon]) for weapon in HUMANOID_WEAPONS}
    best = max(donor_values.values()) if donor_values else 0
    raised, already = {}, []
    for weapon in forte:
        if weapon not in HUMANOID_WEAPONS:
            continue
        if donor_values[weapon] < best:
            row.set('mastery_' + weapon, best)
            raised[weapon] = dict(donor=donor_values[weapon], written=best)
        else:
            already.append(weapon)
    return dict(rule="derived: each D4 forte weapon -> the D5 donor template's best stored weapon mastery",
                forte=list(forte), donor_template=int(donor['id']),
                donor_values=donor_values, donor_best=best, raised=raised, already_best=already,
                other_weapons='donor value unchanged',
                weapon_resistances='donor value; D4 stores no weapon-type resistance')


def plan_import(source, tables, mapping, *, target_id, template_id, supported_ids,
                excluded_source_ids=(), reserved_evilities=(), reserved_skills=(),
                previous_leases=None, previous_leases_sha256=None, owner_mod_id=None,
                identity=None, physical=None, share_art=None, source_row=None, ability_lease=None):
    """Plan one D4-only identity through the shared source-profile mapper.

    Identity exclusions are explicit caller-reviewed source IDs. A name match
    never chooses a template, excludes a source, or establishes equivalence.
    Unlike the legacy comparison plan, this accepts any genuine source profile.
    ``identity``/``physical`` switch the build to the registry shape (see unique_shape);
    ``share_art`` ({owner, sprite_id, color_id}) builds on an owner's art instead (D4-NPC1).
    ``source_row`` is the full D4 char.dat row; its ``weapon_skills`` forte raises a humanoid
    unique's matching weapon masteries to the donor's best (D4TYPES-REVIEW F5).
    """
    from . import charstudio, sourceimports, slots
    if source['id'] in excluded_source_ids:
        raise ValueError('Source identity is already present in D5')
    shape = unique_shape(target_id, identity, physical, shared=share_art)
    identity, physical = shape['identity'], shape['physical']
    if shape.get('shared'):
        # Only the identity row is new; the art keys belong to the owner and are already in use.
        if any(r['id'] == identity for r in tables['char.dat'].rows):
            raise ValueError(f'Unique {identity} would replace an existing character')
    elif shape['registry']:
        # The identity is the class id and the char row id; it must carry no row yet, and the
        # leased art key must be an unused low unique id, never a real character.
        for key in (identity, physical):
            if any(r['id'] == key for r in tables['char.dat'].rows):
                raise ValueError(f'Unique {key} would replace an existing character')
    else:
        if type(target_id) is not int or not 10 <= target_id < 1000 or target_id not in supported_ids:
            raise ValueError('Caller-verified low unique identity required')
        existing = [r for r in tables['char.dat'].rows if r['id'] == target_id]
        if len(existing) > 1 or (existing and target_id not in slots.DUMMY_ROWS):
            raise ValueError('Unique target would replace an existing character')
    donor = _one(tables['char.dat'], template_id)
    if 'body_type' in source['battle'] and donor['body_type'] != source['battle']['body_type']:
        raise ValueError('D5 donor body type differs from the source native body discriminator')
    row = donor.copy()
    charstudio.start_fresh(row)
    fields = {}
    for k, stat in enumerate(d4source.STATS):
        for prefix, vector in (('base_', 'base'), ('apt_', 'aptitudes')):
            fields[prefix + stat] = source[vector][k]
    for field, value in fields.items():
        row.set(field, value)
    audit = dict(fields=fields, relation='Exact stored source integers; D5 progression retained')
    # D4-FORTE1: humanoid uniques keep the D5 template's mastery *letters*, so a D4 forte weapon is
    # raised to the template's best stored rank and every other weapon/resistance stays the donor's.
    # The full char row carries weapon_skills; the rank profile above does not.
    body_type = (source_row or {}).get('battle', {}).get('body_type', source['battle'].get('body_type'))
    forte = weapon_forte(source_row if source_row is not None else source)
    if body_type != 1 and forte:
        audit['weapon_forte'] = apply_weapon_forte(row, donor, forte)
    mapped = sourceimports.plan_d4_profile([source], mapping, family=identity, template_rows=[donor],
        skill_table=tables['Skill.dat'], magic_table=tables['magic.dat'],
        reserved_evilities=reserved_evilities, reserved_skills=reserved_skills,
        previous_leases=previous_leases, previous_leases_sha256=previous_leases_sha256,
        owner_mod_id=owner_mod_id, pinned_evilities=(ability_lease or {}).get('evilities'),
        pinned_skills=(ability_lease or {}).get('skills'))
    for field, value in mapped['ranks'][0].items():
        row.set(field, value)
    kind_gender = source['battle']['kind_gender']
    if kind_gender >= 10:
        # D4-KG1: a story boss on a generic body keeps the generic code (God's Part 230: 21); no D5
        # unique row uses 21/22, so the unique keeps only the gender digit.
        audit['kind_gender'] = dict(source=kind_gender, written=kind_gender % 10,
                                    relation='generic class code reduced to the unique gender digit (value % 10)')
        kind_gender %= 10
    row.set('kind_gender', kind_gender)
    # The char row id is the identity; the art keys are the leased physical row (registry shape)
    # or the same low id (legacy shape).  The game keys faces and portraits by colour id, so a
    # registry unique carries its physical row there too (nativeimports.build_entry does the same).
    row.set('id', identity)
    row.set('sprite_id', shape.get('sprite_id', physical))
    row.set('color_id', shape.get('color_id', physical))
    row.set('is_dummy_slot', 0)
    row.set('dlc_group', 0)
    charstudio.set_langs(row, 'name', source['name'])
    charstudio.set_langs(row, 'title', source['title'])
    return row, mapped, audit



def load_storage_leases(path, owner_key):
    """(pinned, reserved) from `d5lib/importers/d4-leases.json`: this character's recorded
    quest/slot/help ids, and every other character's (a fresh allocation must avoid them)."""
    chars = json.loads(Path(path).read_text())['characters']
    mine = (chars.get(str(owner_key)) or {}).get('storage')
    return mine, [c['storage'] for k, c in chars.items() if k != str(owner_key) and c.get('storage')]


def load_ability_leases(path, owner_key):
    """Recorded ability rows from `d4-leases.json`: {"evilities": {d4 id: Skill.dat row}, "skills": {d4 id: magic.dat
    row}, "exact": [d4 evility ids that take a reviewed exact row] or None, "reserved_evilities": {rows},
    "reserved_skills": {rows}} -- this character's rows (reproduced exactly, never re-allocated) and every other
    character's (a fresh allocation avoids them).  Ids only; a character without the keys allocates first-free."""
    chars = json.loads(Path(path).read_text())['characters']
    me = chars.get(str(owner_key)) or {}
    def rows(key):
        return {int(k): int(v) for k, v in (me.get(key) or {}).items()}
    def others(key):
        return {int(v) for k, c in chars.items() if k != str(owner_key) for v in (c.get(key) or {}).values()}
    return dict(evilities=rows('evility_rows'), skills=rows('skill_rows'),
                exact=[int(i) for i in me['evility_exact']] if 'evility_exact' in me else None,
                reserved_evilities=others('evility_rows'), reserved_skills=others('skill_rows'))


def _import_storage(layered, owner=None, leases=None, owner_mod_id=None, pinned=None, reserved=()):
    """Existing unique recruitment/help allocation, or explicit prior leases.

    `pinned` ({quest_id, quest_slot, help_id}) is the recorded allocation of a character an earlier
    build installed: it is reproduced, and an occupied id is an error, never a silent move.
    Otherwise the next free ids are taken, skipping the `reserved` pinned ids of other characters."""
    from . import dbpatch
    if pinned:
        qid, qslot, helpid = pinned['quest_id'], pinned['quest_slot'], pinned['help_id']
        if any(r['id'] == qid or (not dbpatch.is_placeholder_quest(r) and r['sort_order'] == qslot)
               for r in layered['Quest.dat'].rows) or any(
                r['id'] == helpid or r['char_id'] == helpid for r in layered['charhelp.dat'].rows):
            raise ValueError(f'Pinned recruitment/help ids occupied: {pinned}')
    elif owner is None:
        rq = {r['quest_id'] for r in reserved}
        rs = {r['quest_slot'] for r in reserved}
        rh = {r['help_id'] for r in reserved}
        helpid = max({r['id'] for r in layered['charhelp.dat'].rows} |
                     {r['char_id'] for r in layered['charhelp.dat'].rows} | rh | {3999}) + 1
        qid = max(i for i in {r['id'] for r in layered['Quest.dat'].rows} | rq | {0}
                  if i < dbpatch.PLACEHOLDER_FIRST) + 1
        qslot = dbpatch.free_quest_slot(layered['Quest.dat'], reserved=rs)
    else:
        quests, helps = owner.get('quests', []), owner.get('help', [])
        if len(quests) != 1 or len(helps) != 1:
            raise ValueError('Missing/ambiguous prior unique recruitment/help lease')
        quest = quests[0]
        qid, qslot, helpid = quest['id'], quest['sort_order'], helps[0]['id']
        if quest.get('reward_type') != 5 or quest.get('reward_value') != owner['family'] or \
                helps[0].get('char_id') != helpid or owner['characters'][0]['help_id'] != helpid or \
                leases['claims'].get('Quest.dat', {}).get(str(qid)) != [owner_mod_id] or \
                leases.get('quest_slots', {}).get(str(qslot)) != [owner_mod_id] or \
                leases['claims'].get('charhelp.dat', {}).get(str(helpid)) != [owner_mod_id]:
            raise ValueError('Foreign/unverifiable prior unique storage')
        if any(r['id'] == qid or (not dbpatch.is_placeholder_quest(r) and r['sort_order'] == qslot)
               for r in layered['Quest.dat'].rows) or any(
                r['id'] == helpid or r['char_id'] == helpid for r in layered['charhelp.dat'].rows):
            raise ValueError('Prior unique recruitment/help lease occupied')
    if qid >= dbpatch.PLACEHOLDER_FIRST or not 0 <= qslot < dbpatch.QUEST_SLOTS:
        raise ValueError('No safe recruitment quest storage')
    return helpid, qid, qslot

def build_import(*, d4_root, game_path, original_state, mods_roots, output_path,
                 source_id, target_id, template_id, prepared_root, library_root,
                 face_path, cutin_path, mapping, excluded_source_ids=(), finalize=True, log=print,
                 source_voice=None, previous_leases=None, previous_leases_sha256=None, owner_mod_id=None,
                 exact_emission=None, supersede_prefixes=(), engine_exact=None,
                 identity=None, physical=None, storage_pin=None, storage_reserved=(), share_art=None,
                 ability_lease=None):
    """General source-art unique importer, independent of the Valvatorez comparison.

    Uses the Kit's normal own-animation, character-face, skill, Evility, quest and
    cold-finalization paths. All caller-selected mods, including disabled ones,
    participate in allocation, except mods whose id starts with one of
    ``supersede_prefixes`` (an earlier generation this import replaces; they are
    still read, never written, and are recorded in the receipt).
    ``engine_exact`` is a reviewed D4 extension emission; the owned exact rows are
    applied to the staged mod before the single canonical finalization.
    ``identity``/``physical`` (both or neither, see unique_shape) build the character on a
    registry identity keyed to a leased low art row instead of the legacy low row.
    """
    from . import anm, charstudio, d4expansion, gamefs, gamepacks, newchars, newclasses
    from . import modsys, outfits, ownanim, sourceimports, sprites, slots
    from PIL import Image
    shape = unique_shape(target_id, identity, physical, shared=share_art)
    from typing import cast
    identity = cast(int, shape['identity'])
    physical = cast(int, shape['physical'])
    registry = bool(shape['registry'])
    shared = shape.get('shared')
    if not registry and identity != target_id:
        raise ValueError('Legacy shape requires identity == physical == target_id')
    output = Path(os.path.abspath(output_path))
    protected = (d4_root, game_path, original_state, prepared_root, library_root,
                 face_path, cutin_path, Path(__file__).parents[1], *mods_roots)
    if output.exists() or not output.parent.is_dir() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('Unique output must be new under a canonical private parent')
    offlinepaths.offline_output(output, protected)
    offlinepaths.require_output_cache(sprites.CACHE_DIR, output, protected)
    originals, temp = Originals(original_state), None
    fs = gamefs.GameFS(str(game_path), backup_resolver=originals)
    try:
        tables = {n: database.load_table(n, fs.read('Database/Database_0.dat/' + n)) for n in TABLES}
        # One folder reached through two roots (a symlinked reserved set, the same kit named twice)
        # is one mod: scan it once, or every id it claims looks like a conflict with itself.
        all_mods = scan_mods(mods_roots)
        # An earlier generation this import replaces (e.g. D4_Unique_*) is read but
        # claims nothing: its character/art/Skill rows are superseded in place.
        superseded = superseded_mod_ids(all_mods, supersede_prefixes)
        mods = [m for m in all_mods if m.id not in set(superseded)]
        conflict_mods, owner = mods, None
        update = dict(previous_leases=previous_leases, previous_leases_sha256=previous_leases_sha256,
                      owner_mod_id=owner_mod_id)
        if any(v is not None for v in update.values()):
            owner = sourceimports._d4_update_owner(previous_leases, previous_leases_sha256, owner_mod_id)
            prior = [m for m in mods if m.id == owner_mod_id]
            if owner_mod_id != f'D4_Unique_{source_id}' or owner['family'] != identity or len(prior) != 1:
                raise ValueError('Explicit unambiguous prior unique owner required')
            sourceimports.verify_d4_previous_mod(prior[0], previous_leases, previous_leases_sha256, owner_mod_id)
            conflict_mods = [m for m in mods if m is not prior[0]]
        check_conflicts(tables, conflict_mods, identity, physical=physical if registry else None,
                        graphics=sprites.used_sprite_numbers(fs), shared=shared)
        source = d4source.D4Data(d4_root)
        ranks = source.class_profile(source_id, 1)
        profile = ranks[0]
        original_reserved = charstudio.all_mod_skill_ids((), fs=fs)
        if owner is not None and any(x['id'] in original_reserved for x in owner['skills'].values()):
            raise ValueError('Prior D4 skill wrapper collides with an original event')
        row, mapped, audit = plan_import(profile, tables, mapping, target_id=target_id,
            template_id=template_id, supported_ids=slots.unique_pool(fs, tables['char.dat']),
            excluded_source_ids=excluded_source_ids,
            reserved_evilities=charstudio.all_mod_evility_ids(mods) | set((ability_lease or {}).get('reserved_evilities', ())),
            reserved_skills=(charstudio.all_mod_skill_ids(mods) | original_reserved
                             | set((ability_lease or {}).get('reserved_skills', ()))),
            identity=identity, physical=physical, share_art=share_art,
            source_row=source.chars[source_id] if isinstance(getattr(source, 'chars', None), dict) else None,
            ability_lease=ability_lease, **update)
        prepared = None
        if not share_art:
            prepared = sourceimports.read_prepared(prepared_root, library_root, edition='Disgaea 4 Complete+ PC EN')
            if (prepared['identity']['character_id'] != source_id or
                    prepared['identity']['body'] != source.chars[source_id]['sprite']):
                raise ValueError('Prepared art/source unique identity mismatch')
        # Apply every supplied mod before choosing help and recruitment storage.
        layered = {n: database.load_table(n, fs.read('Database/Database_0.dat/' + n))
                   for n in ('Quest.dat', 'charhelp.dat')}
        for n, table in layered.items():
            for mod in conflict_mods:
                patch = mod.load_patch('db', n + '.json')
                if patch:
                    dbpatch.apply_patch(table, patch, strict=True)
        helpid, qid, qslot = _import_storage(layered, owner, previous_leases, owner_mod_id,
                                              pinned=storage_pin, reserved=storage_reserved)
        if source.chars[source_id]['magichange'] == 0:
            row.set('magichange_type', 0); row.set('magichange_weapon', 0)
        row.set('help_id', helpid)
        temp = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
        mid = f'D4_Unique_{source_id}'
        mod = modsys.Mod(str(temp / 'native-mods' / mid))
        mod.meta.update(name=profile['name'] + ' (D4)', author='Local source import', version='0.1.0',
            description='D4 source art/static stats; D5 mapped mechanics with explicit unavailable gaps.',
            source_import=dict(source_game='d4', source_id=source_id, native_tested=False,
                               yield_source=donor_yield(D4_YIELD_NOTE)))
        if share_art and share_art.get('owner') and share_art['owner'] != 'vanilla':
            # D4-NPC1: the art is the owner pack's; installing this character without it draws nothing.
            # "vanilla" means the art is the base game's own class rows and needs no pack.
            mod.meta['requires'] = [share_art['owner']]
        mod.save_meta()
        voice_receipt = sourceimports.import_d4_voice(mod, source, **source_voice) if source_voice else None
        if voice_receipt:
            row.set('voice_id', voice_receipt['voice_id'])
        ct = database.load_table('char.dat', fs.read(CHAR))
        if ct.index_of(identity) >= 0:
            ct.rows[ct.index_of(identity)] = row
        else:
            ct.rows.append(row)
        mod.save_patch('db', 'char.dat.json', dbpatch.diff_table(tables['char.dat'], ct))
        ht = database.load_table('charhelp.dat', fs.read('Database/Database_0.dat/charhelp.dat'))
        hr = ht.new_row()
        hr.set('id', helpid); hr.set('char_id', helpid)
        help_lines = dbpatch.help_lines(source.help_lines(source.chars[source_id]['help_id']))
        original_help_lines = list(help_lines)
        pending_abilities = [x for x in mapped['report'] if x['status'] in ('placeholder', 'unmapped', 'omitted')]
        if pending_abilities:
            help_lines[2] = 'D4 skills/Evilities pending; see GAPS.'
        for n, text in enumerate(help_lines, 1):
            charstudio.set_langs(hr, f'line{n}', text)
        ht.rows.append(hr)
        mod.save_patch('db', 'charhelp.dat.json', dbpatch.diff_table(tables['charhelp.dat'], ht))
        qt = database.load_table('Quest.dat', fs.read('Database/Database_0.dat/Quest.dat'))
        qr = _one(qt, 1).copy()
        qr.set('id', qid); qr.set('sort_order', qslot)
        charstudio.set_langs(qr, 'name', 'D4: ' + profile['name'])
        charstudio.set_langs(qr, 'client', profile['name'])
        for n, text in enumerate(dbpatch.quest_lines('Recruit this partial D4 source import after clearing Dried Up Wasteland.'), 1):
            charstudio.set_langs(qr, f'desc{n}', text)
        qr.set('reward_type', 5); qr.set('reward_value', identity); qr.set('reward_count', 1); qr.set('important', 1)
        from . import questcheck
        questcheck.set_objective(qr, dict(type=4, target=101, count=1))
        qt.rows.append(qr)
        mod.save_patch('db', 'Quest.dat.json', dbpatch.diff_table(tables['Quest.dat'], qt))
        aliases = {}
        for ev in mapped['evilities']:
            newclasses.add_evility(fs, mod, ev['id'], ev['works_like'], ev['name'], ev['desc'],
                owner=identity, order=0, kind=1 if ev['unique'] else 0, source=4, shop_rank=0,
                **({'slot_cost': 0} if ev['unique'] else {}),
                **({'mana_cost': ev['mana']} if ev['mana'] else {}))
            aliases[str(ev['id'])] = ev['works_like']
        if aliases:
            # Existing character-owned aliases do not add a class descriptor.
            mod.save_patch('evilities', 'aliases.json', aliases)
        for sk in mapped['skills']:
            newclasses.add_skill(fs, mod, sk['id'], sk['copy_of'], sk['name'], sk['desc'], **sk['fields'])
        engine: dict = dict(exact=[], adapted=[], missing=[], superseded=superseded)
        if engine_exact:
            # Reviewed exact D4 rows replace the leased donor alias for the evilities
            # this character owns and the extension vocabulary covers exactly.
            from . import d4exact
            occupied = set(charstudio.all_mod_evility_ids(mods)) | set(charstudio.all_mod_skill_ids(mods))
            exact_all = {int(x['d4_id']): int(x['d5_id']) for x in engine_exact['exact']}
            # A leased evility (d4-leases.json "evility_rows") stays the adapted row the lease records: whether an
            # exact row happens to be free depends on build order and on what else is installed, so it never decides.
            leased = (ability_lease or {}).get('exact')           # None: no lease, first-free as before
            keep_all = {sid: target for sid, target in exact_all.items()
                        if target not in occupied and sid not in ((ability_lease or {}).get('evilities') or {})}
            keep = {sid: target for sid, target in keep_all.items() if leased is None or sid in leased}
            if not keep_all:
                engine['note'] = 'no owned D4 evility is in the exact set'
            else:
                targets = set(keep.values())
                added = engine_exact['mod_files']['patches/db/Skill.dat.json']['added']
                behavior = engine_exact['mod_files']['patches/evilities/evilities.json']['evilities']
                filtered = dict(
                    exact=[dict(d4_id=sid, d5_id=target) for sid, target in sorted(keep.items())],
                    mod_files={'patches/db/Skill.dat.json': {'added': [r for r in added if int(r['id']) in targets]},
                               'patches/evilities/evilities.json': {
                                   'evilities': {k: v for k, v in behavior.items() if int(k) in targets}}})
                prior = {int(e['d4_id']): int(e['d5_id']) for e in mapped['report']
                         if e.get('kind') == 'evility' and e.get('d5_id') is not None}
                engine['exact'] = d4exact.apply_exact(mod.folder, filtered, ranks, identity, occupied, prior)
            for item in mapped['report']:
                match = next((r for r in engine['exact'] if r['d4_id'] == item.get('d4_id')), None)
                if item.get('kind') == 'evility' and match:
                    item.update(status='exact-extension', d5_id=match['target_id'])
                    item.pop('works_like', None)
                    item.pop('works_like_name', None)
            engine['adapted'] = [e['d4_id'] for e in mapped['report']
                                 if e.get('kind') == 'evility' and e.get('status') == 'adapted']
            engine['missing'] = [e['d4_id'] for e in mapped['report']
                                 if e.get('kind') == 'evility' and e.get('status') in ('omitted', 'placeholder', None)]
            # The help overlay is decided after exact rows, so it must not claim a
            # pending ability that this character now owns exactly.
            pending_abilities = [x for x in mapped['report'] if x['status'] in ('placeholder', 'unmapped', 'omitted')]
            help_lines = list(original_help_lines)
            if pending_abilities:
                help_lines[2] = 'D4 skills/Evilities pending; see GAPS.'
            for n, text in enumerate(help_lines, 1):
                charstudio.set_langs(hr, f'line{n}', text)
            mod.save_patch('db', 'charhelp.dat.json', dbpatch.diff_table(tables['charhelp.dat'], ht))
        # The donor row is read for both shapes (the receipt and unique.json name its body type and colour).
        donor_row = tables['char.dat'].find(template_id)
        donor_monster = int(donor_row['body_type']) == 1
        motion, rep, attack_events = None, {}, []
        if not shared:
            # D4-NPC1: a shared-art character ships no bank, face, icon, portrait or attack
            # scripts: every art key it draws with belongs to the owner pack it requires.
            base = anm.parse(fs.read(sprites.sprite_vpath(fs, template_id, 'EN')))
            # Unique monsters (e.g. Desco) use kind_gender=2 too; their
            # animation layout and body_type are independent receiver contracts.
            motion = sprites.motion_block(fs, 1, log) if sprites.needs_motion_set(base) else None
            from . import frameconvert
            rep = {}
            sprite = ownanim.build(prepared['sequences'], base, motion, physical,
                variants=[(0, 0, 0)], report=rep, log=log,
                prefer=frameconvert.MONSTER_ROWS if donor_monster else frameconvert.HUMAN_ROWS,
                source_fallbacks=True, whole_body=True)
            from . import standground
            standground.normalize_stand_ground(sprite, standground.bound_reference(base, motion),
                                               report=rep, log=log)
            # D4's own colour banks: the sprite is built from colour-0 art, so every palette slot holds
            # the same bank.  The class path (`sourceimports.map_source_palettes`) recolours each slot
            # from the source body's own palettes; without it a unique shipped 10 identical banks where
            # its sibling class packs ship the D4 colours (CORED4B, measured on the installed copies).
            if len({p.data for p in sprite.palettes}) == 1:
                # D4-PAL1: the packet's art is cut in its D4 bank (Des X: bank 4), so that bank is
                # source palette 0: the colour lookup is exact and slot 0 is the colour D4 shows.
                first = prepared['identity']['palette']
                banks = rotate_banks(source.body_palettes(source.chars[source_id]['sprite']), first)
                palette_report = {'slot0_d4_bank': first}
                sourceimports.map_source_palettes(sprite, banks, approximate=True, report=palette_report)
                rep['palettes'] = palette_report
            for number in (physical, physical + 1):
                mod.write_file(f'Anime/ANM_HI_JP.dat/anm{number:05d}.lzs', ownanim.with_id(sprite, number).to_bytes())
            outfits.save(mod, [], own_sprites=[physical, physical + 1])
            attack_events = []
            if donor_monster:
                from . import script, scriptpatch, skills
                vanilla = script.ScriptFile.from_bytes(fs.read(skills.SCRIPT))
                by_id = {}
                for event in vanilla.events:
                    by_id.setdefault(event.id, event)
                events = {}
                donor_sprite = int(donor_row['sprite_id'])
                for prefix in newclasses.MONSTER_SCRIPTS:
                    for variant in (0,):
                        old_id, new_id = prefix + donor_sprite + variant, prefix + physical + variant
                        if old_id not in by_id:
                            continue
                        events[str(new_id)] = scriptpatch.event_text(by_id[old_id], annotate=False).replace(
                            f'event {old_id}', f'event {new_id}', 1)
                        attack_events.append(dict(source=old_id, target=new_id))
                if not all(str(prefix + physical) in events for prefix in newclasses.MONSTER_SCRIPTS):
                    raise ValueError('Monster donor lacks normal/short/skipped attack scripts')
                mod.save_patch('script', 'script.json', dict(events=events))
                companion = newclasses.monster_companion(fs, sprite, donor_sprite, physical)
                mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical + 1:05d}.lzs', companion.to_bytes())
            with Image.open(face_path) as face:
                newchars.set_face(mod, physical, sourceimports.d4_screen_picture(face, sourceimports.FACE_MATTE))
            icon = outfits._resident_icon(fs, template_id + 2)
            if icon is not None:
                icon = outfits.repaint_stand_icon(icon, base, motion, sprite)
                icon.blocks[0].id = physical + 2
                mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical + 2:05d}.lzs', icon.to_bytes())
            portrait = anm.parse(fs.read(sprites.sprite_vpath(fs, template_id + 10000, 'EN')))
            for block in portrait.blocks:
                block.id = physical + 10000
            with Image.open(cutin_path) as cutin:
                image = sourceimports.d4_screen_picture(cutin, sourceimports.D4_MATTE)
                import numpy as np
                texture = portrait.textures[0]
                if texture.indexed:
                    raise ValueError('Unique portrait template must be RGBA')
                texture.data = anm._rgba_to_argb(np.asarray(image.resize((texture.width, texture.height), Image.Resampling.LANCZOS))).tobytes()
            for texture in portrait.textures[1:]:
                texture.data = bytes(len(texture.data))
            mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical + 10000:05d}.lzs', portrait.to_bytes())
        if registry:
            # The finalizer reads this to give the identity its own face / banner / list icon under
            # the leased physical colour id (d5lib/outfits.py _finalize_characters): a registry unique
            # is not a class family, so it has no class descriptor and no unlock flags.  Same
            # declaration the D1 Complete registry batch writes (d5lib/nativeimports.build_entry).
            declaration = dict(
                schema=1, identity=identity, physical=physical, template=template_id,
                template_colour=int(donor_row['color_id']), kind=('monster' if donor_monster else 'humanoid'),
                name=profile['name'],
                rule='one rank on a registry identity; sprite/portrait/face keys leased to physical')
            if shared:
                # The char row draws with the owner's keys; the installer clones no face/icon and the
                # ownership gate claims no art window for this pack (D4-NPC1).
                declaration.update(sprite_id=shared['sprite_id'], color_id=shared['color_id'],
                                   shares_art_with=shared['owner'],
                                   rule="one rank on a registry identity; all graphics are the "
                                        "'shares_art_with' pack's (no art window of its own)")
            mod.save_patch('characters', 'unique.json', declaration)
        exact_receipt = []
        if exact_emission is not None:
            if previous_leases is not None:
                raise ValueError('Exact import cannot update a prior lease')
            from . import d4exact
            exact_receipt = d4exact.apply_import(mod, exact_emission, [profile], identity,
                tables['Skill.dat'], d4exact.existing_mods(game_path, mods_roots), mapped['report'])
        # Reuse the full package preflight, including all disabled allocations.
        d4expansion.preflight(fs, [mod], mods)
        receipt = dict(schema=2, source_id=source_id, target_id=target_id, identity=identity,
            physical=physical, shape=('registry' if registry else 'low'), template_id=template_id,
            source=profile, mappings=mapped['report'], exact_evilities=exact_receipt, source_static=audit,
            source_art=prepared['evidence'] if prepared else None,
            shared_art=shared,
            screen_art={} if shared else {k:dict(path=str(Path(p).resolve()),sha256=sha(Path(p).read_bytes())) for k,p in [('face',face_path),('cutin',cutin_path)]},
            receiver=dict(template=template_id, body_type=donor_row['body_type'], shared_motion=motion is not None,
                attack_events=attack_events, source_body_type=profile['battle'].get('body_type'),
                source_magichange=source.chars[source_id]['magichange'], native_equipment_magichange='not-tested; donor body contract is an adaptation, source type requires independent predicate evidence'),
            animation={k:v for k,v in rep.items() if k not in ('matches','offsets')},
            recruitment=dict(id=qid, progress_slot=qslot), native_tested=False,
            source_help_lines=original_help_lines, displayed_help_lines=help_lines, pending_abilities=pending_abilities,
            source_voice=voice_receipt, engine=engine,
            gaps=['D5 animation timing/attachments and progression', 'Unmapped D4 mechanics unavailable',
                  'D5 template voice until source voice mapping is supplied',
                  "Weapon mastery: D4 forte weapons raised to the donor template's best rank; other weapons and "
                  'all weapon resistances are the donor value (D4 stores no mastery letters or weapon resistances)',
                  'Native gameplay acceptance'])
        d4expansion.write(temp / 'unique-receipt.json', receipt)
        d4expansion.write(temp / 'native-files.json', d4expansion.snapshot(mod))
        payload = [str(p.relative_to(mod.folder)) for p in gamepacks._native_tree(Path(mod.folder)) if p.name != 'mod.json']
        eid = f'd4:pc-en-unique-{source_id}'
        catalogue = dict(schema=1, id='d4-unique-import', name='D4 source unique import',
            games=[dict(id='d4', name='Disgaea 4 Complete+')], entries=[dict(id=eid, game='d4',
            name=profile['name'] + ' (D4)', category='characters', status='build-ready',
            source=dict(edition='Disgaea 4 Complete+ PC EN', identity=f'char.dat:{source_id}',
                provenance=[dict(kind='source-table', reference=sha(source.db.read('char.dat')))]),
            fidelity=dict(mode='hybrid', missing_mappings=receipt['gaps'], adaptations=['Source stored integers/art with D5 mapped mechanics']),
            artifact=dict(mod_id=mid, required_payload=payload))])
        gamepacks.validate_catalogue(catalogue, artifacts={mid:mod})
        d4expansion.write(temp / 'catalogue.json', catalogue)
        if finalize:
            from . import runtime
            offlinepaths.require_output_cache(runtime.CACHE, output, protected)
            final = d4expansion.finalize(dict(game_path=str(game_path), original_state=str(original_state),
                mods=[mod.folder], selected_mods=[mid], cache=str(runtime.CACHE), output=str(temp / 'final-pass'),
                expected_finalizer_order=[fn.__module__ + '.' + fn.__name__ for fn in modsys.ordered_finalizers()]))
            os.rename(temp / 'final-pass/logical', temp / 'finalized-logical')
            d4expansion.write(temp / 'finalization.json', final)
        originals.verify()
        d4expansion.write(temp / 'original-read-receipt.json', originals.reads)
        os.rename(temp, output)
        temp = None
        return dict(output=str(output), mod_id=mid, entry_id=eid, target_id=target_id,
                    identity=identity, physical=physical, shape=('registry' if registry else 'low'),
                    finalization='built-offline' if finalize else 'not-requested', installed=False, native_tested=False)
    finally:
        fs.reset()


def scan_mods(mods_roots):
    """Every mod folder under these roots, once, by resolved path.

    A reserved set is assembled from symlinks and a caller may name the same tree twice; the same
    folder then arrives as two `modsys.Mod` objects and every id it claims looks like a conflict
    with itself.  Reading it once is the fix; the claim rules are per folder.
    """
    mods, seen = [], set()
    for root in mods_roots:
        for p in sorted(Path(root).resolve(strict=True).iterdir()):
            if not (p.is_dir() and (p / 'mod.json').is_file()):
                continue
            real = Path(p).resolve()
            if real in seen:
                continue
            seen.add(real)
            mods.append(modsys.Mod(str(p)))
    return mods


def superseded_mod_ids(mods, prefixes):
    """Ids of an earlier generation this import replaces in place.

    They are still read (never written) but claim no character, art or Skill.dat
    row: the replacement mod supplies those rows itself.
    """
    prefixes = tuple(p for p in (prefixes or ()) if p)
    if not prefixes:
        return []
    return sorted({m.id for m in mods if m.id.startswith(prefixes)})


def check_conflicts(tables, mods, target_id, *, graphics=(), physical=None, shared=None):
    """Reject collisions with all supplied mods, including disabled allocations.

    ``target_id`` is the char row the build claims (a registry identity when ``physical`` is
    given) and ``physical`` is the low art key set it writes: ``p, p+1, p+2, 10000+p, 10001+p``.
    ``shared`` (D4-NPC1) means the build writes no art: only the identity row is checked, and
    the keys belong to the owner pack named in ``shared['owner']``.
    """
    from . import slots
    vanilla = tables['char.dat']
    row_id = target_id
    art = int(physical if physical is not None else target_id)
    target_index = vanilla.index_of(row_id)
    keyed = set() if shared else {art, art + 1, art + 2, 10000 + art, 10001 + art}
    conflicts, inventory = [], []
    if shared:
        if type(target_id) is not int or target_id < 10000 or target_id % 10 or target_index >= 0:
            raise ValueError('A shared-art unique needs an unused registry identity row')
    elif physical is not None:
        if type(target_id) is not int or target_id < 10000 or target_id % 10:
            raise ValueError('A registry unique identity must be a rank-0 multiple of ten at or above 10000')
        if not 10 <= art < 1000:
            raise ValueError('A registry unique leases a low physical art row below 1000')
        if target_index >= 0:
            raise ValueError('Registry identity already carries a character row')
        if any(r['id'] == art for r in vanilla.rows) and art not in slots.DUMMY_ROWS:
            raise ValueError('Physical art row would replace an existing character')
    elif type(target_id) is not int or not 10 <= target_id < 1000 or (target_index >= 0 and target_id not in slots.DUMMY_ROWS):
        raise ValueError('Target must be an unused low unique ID or supported dummy')
    if keyed & set(graphics):
        conflicts.append(dict(kind='vanilla-art', ids=sorted(keyed & set(graphics))))
    for mod in sorted(mods, key=lambda m: str(m.folder)):
        patch = mod.load_patch('db', 'char.dat.json') or {}
        if (target_index >= 0 and str(target_index) in patch.get('rows', {})) or any(r.get('id') == row_id for r in patch.get('added', [])):
            conflicts.append(dict(kind='character', mod=mod.id, id=row_id))
        if physical is not None and not shared and any(r.get('id') == art for r in patch.get('added', [])):
            conflicts.append(dict(kind='character-row', mod=mod.id, id=art))
        outfit = mod.load_patch('outfits', 'outfits.json') or {}
        if not shared and any(art in pair for pair in outfit.get('pairs', [])):
            conflicts.append(dict(kind='outfit', mod=mod.id, id=art))
        for vp in mod.list_files():
            name = Path(vp).name
            if name.startswith('anm') and name[3:8].isdigit() and int(name[3:8]) in keyed:
                conflicts.append(dict(kind='art', mod=mod.id, path=vp))
        hashes = {str(p.relative_to(mod.folder)): sha(p.read_bytes()) for p in sorted(Path(mod.patches_dir).rglob('*.json'))}
        inventory.append(dict(mod_id=mod.id, path=str(Path(mod.folder).resolve()), patch_hashes=hashes))
    result = dict(schema=1, target_id=target_id, physical=art, keyed_graphics=sorted(keyed), mods=inventory, conflicts=conflicts,
                  scope='All mods in explicitly supplied roots; provisional local reservation only')
    if conflicts:
        raise ValueError('Unique allocation collision: ' + json.dumps(conflicts, sort_keys=True))
    return result


def comparison_dependencies(fs):
    """Resolve literal D5 event/effect closure; dynamic engine choices stay explicit."""
    from . import skills, sprites
    raw = fs.read(skills.SCRIPT)
    sc = skills.Scripts(raw)
    roots = [base + sid for sid, _ in SKILLS.values() for base in (12000000, 12100000, 12200000)]
    pending, seen = list(roots), set()
    while pending:
        eid = pending.pop()
        if eid in seen:
            continue
        if eid not in sc.ev:
            raise ValueError('Missing D5 comparison event ' + str(eid))
        seen.add(eid)
        pending.extend(sc.refs(eid))
    effects = sorted({i.args[1] for eid in seen for i in sc.ev[eid].code
                      if i.cid == 0x3c00 and isinstance(i.args[1], int)})
    members = skills.effect_members(fs.read)
    effect_rows = []
    for effect in effects:
        name = skills.effect_name(effect)
        if name not in members:
            raise ValueError('Missing D5 comparison effect ' + name)
        effect_rows.append(dict(id=effect, member=name, sha256=sha(members[name]), bytes=len(members[name])))
    art = {}
    for n in (570, 571, 10570):
        vp = sprites.sprite_vpath(fs, n, 'EN')
        data = fs.read(vp)
        art[vp] = dict(sha256=sha(data), bytes=len(data))
    return dict(script_sha256=sha(raw), wrappers=roots, literal_events=sorted(seen),
                literal_effects=effect_rows, donor_art=art,
                scope='Literal D5 event/effect closure only; dynamic sound/voice/resource selectors, timing and native gameplay remain unaccepted')


def build(*, d4_root, game_path, original_state, mods_roots, output_path, target_id=470,
          portrait_policy='d5-comparison', finalize=True, log=print):
    """Emit native Mod + grouped staging + strict offline readback, never install."""
    from . import anm, charstudio, gamefs, gamepacks, modsys, slots, sprites
    output = Path(os.path.abspath(output_path))
    protected = (d4_root, game_path, original_state, Path(__file__).parents[1], *mods_roots)
    if output.exists() or not output.parent.is_dir() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('Output must be new under an existing canonical directory')
    offlinepaths.offline_output(output, protected)
    offlinepaths.offline_output(str(output) + '.cache', (*protected, output))
    offlinepaths.separate_outputs(output, str(output) + '.cache')
    offlinepaths.require_output_cache(sprites.CACHE_DIR, output, protected)
    if finalize:
        from . import runtime
        offlinepaths.require_output_cache(runtime.CACHE, output, protected)
    if portrait_policy not in ('d5-comparison', 'd4-converted'):
        raise ValueError('Unknown portrait policy')
    originals = Originals(original_state)
    fs = gamefs.GameFS(str(game_path), backup_resolver=originals)
    temp = None
    try:
        raw = {n: fs.read('Database/Database_0.dat/' + n) for n in TABLES}
        tables = {n: database.load_table(n, b) for n, b in raw.items()}
        mods = []
        for root in mods_roots:
            root = Path(root).resolve(strict=True)
            mods += [modsys.Mod(str(p)) for p in sorted(root.iterdir()) if p.is_dir() and (p / 'mod.json').is_file()]
        conflicts = check_conflicts(tables, mods, target_id, graphics=sprites.used_sprite_numbers(fs))
        supported_ids = slots.unique_pool(fs, tables['char.dat'])
        source = d4source.D4Data(d4_root)
        profile = source.chars[10]
        row, mappings = plan(profile, tables, target_id=target_id, supported_ids=supported_ids)
        dependencies = comparison_dependencies(fs)
        # Reserve quest/help identities against every supplied installed/candidate mod.
        layered = {}
        for name in ('Quest.dat', 'charhelp.dat'):
            table = database.load_table(name, raw[name])
            for mod in mods:
                patch = mod.load_patch('db', name + '.json')
                if patch:
                    dbpatch.apply_patch(table, patch)
            layered[name] = table
        qid = dbpatch.new_quest_id(layered['Quest.dat'])
        qslot = dbpatch.free_quest_slot(layered['Quest.dat'])
        if qid >= dbpatch.PLACEHOLDER_FIRST or qslot >= dbpatch.QUEST_SLOTS:
            raise ValueError('No safe native recruitment quest slot')
        helpid = max({r['id'] for r in layered['charhelp.dat'].rows} | {r['char_id'] for r in layered['charhelp.dat'].rows} | {3999}) + 1
        row.set('help_id', helpid)
        expected = {k: row[k] for k in row.keys() if not isinstance(row[k], bytes)}
        ct = database.load_table('char.dat', raw['char.dat'])
        if ct.index_of(target_id) >= 0:
            ct.rows[ct.index_of(target_id)] = row
        else:
            ct.rows.append(row)
        ht = database.load_table('charhelp.dat', raw['charhelp.dat'])
        hr = ht.add_row(copy_from=next(i for i, r in enumerate(ht.rows) if r['char_id'] == 570))
        hr.set('id', helpid); hr.set('char_id', helpid)
        lines = dbpatch.help_lines(['D4 static values; D5 combat scenes.', 'Bloody Battle is not implemented.', 'Partial comparison pilot.'])
        for k, text in enumerate(lines, 1):
            charstudio.set_langs(hr, f'line{k}', text)
        for field in ('flag_off1', 'flag_off2', 'flag_off3'):
            hr.set(field, 0)
        qt = database.load_table('Quest.dat', raw['Quest.dat'])
        qr = qt.add_row(copy_from=next(i for i, r in enumerate(qt.rows) if r['id'] == 1))
        qr.set('id', qid); qr.set('sort_order', qslot)
        charstudio.set_langs(qr, 'name', 'D4 Valvatorez comparison')
        charstudio.set_langs(qr, 'client', 'Valvatorez')
        for k, text in enumerate(dbpatch.quest_lines('Clear Dried Up Wasteland to recruit the partial D4 comparison pilot.'), 1):
            charstudio.set_langs(qr, f'desc{k}', text)
        qr.set('reward_type', 5); qr.set('reward_value', target_id); qr.set('reward_count', 1); qr.set('important', 1)
        from . import questcheck
        questcheck.set_objective(qr, dict(type=4, target=101, count=1))
        temp = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
        modroot = temp / 'native-mods' / MOD_ID
        mod = modsys.Mod(str(modroot))
        mod.meta.update(name='D4 Valvatorez — partial comparison pilot', author='Local source import', version='0.1.0',
                        description='D4 stored stats/levels with D5 Valvatorez presentation and skills. Bloody Battle blocked.',
                        source_import=dict(source_game='d4', source_id=10, status='partial', native_tested=False,
                                                           yield_source=donor_yield(D4_YIELD_NOTE)))
        mod.save_meta()
        for name, edited in (('char.dat', ct), ('charhelp.dat', ht), ('Quest.dat', qt)):
            mod.save_patch('db', name + '.json', dbpatch.diff_table(tables[name], edited))
        art = dict(status='adapted', policy=portrait_policy, body='D5 Valvatorez570', face='D5 Valvatorez570',
                   voice='D5 voice570; language selected by game', timing='All D5 animation and weapon attachment tracks')
        # Optional finite D4 ANM conversion. Keeps pixels/transforms but has no render acceptance.
        if portrait_policy == 'd4-converted':
            portrait = source.anm(10010)
            for block in portrait.blocks:
                if block.id != 10010:
                    raise ValueError('Unexpected source portrait block identity')
                block.id = 10000 + target_id
            converted = portrait.to_bytes()
            reread = anm.parse(converted)
            if [x.data for x in reread.textures + reread.palettes] != [x.data for x in portrait.textures + portrait.palettes]:
                raise ValueError('Converted source portrait pixel readback mismatch')
            mod.write_file(f'Anime/ANM_HI_JP.dat/anm{10000 + target_id:05d}.lzs', converted)
            art['portrait'] = dict(status='partial', source_id=10010, sha256=sha(converted),
                                   source_member_sha256=sha(source._anm_pack.read('anm10010.lzs')),
                                   reason='D4 ANM structural conversion; pixels preserved; D5 layout/cut-in rendering unaccepted')
        else:
            art['portrait'] = dict(status='adapted', source='D5 Valvatorez570')
        source_raw = source.db.read('char.dat')
        receipt = dict(schema=1, status='partial-offline-not-installed', target_id=target_id, donor_id=570,
                       source=profile, source_edition='Disgaea 4 Complete+ PC EN installed files',
                       provenance=dict(d4_char_sha256=sha(source_raw), d4_magic_sha256=sha(source.db.read('magic.dat')),
                                       d4_evility_sha256=sha(source.db.read('mskill.dat')),
                                       d5_tables={k: sha(v) for k, v in raw.items()}),
                       mappings=mappings, art=art, dependencies=dependencies,
                       recruitment=dict(id=qid, progress_slot=qslot, map=101),
                       limitations=['D4 Bloody Battle absent: no innate Evility installed',
                                    'D4 learnable Evilities are comparison references, not granted or newly owned',
                                    'D5 growth, mastery, weapon resistances and native damage/targeting mechanics',
                                    'D4 weapon learning codes retained as evidence only; threshold semantics unproven',
                                    'D5 skills reuse every D5 normal/short/skip/event/effect/sound route; no D4 equivalence claim',
                                    'Recruitment, combat, appearance and persistence require gameplay acceptance'],
                       native_tested=False, expected_row=expected)
        (temp / 'unique-receipt.json').write_text(json.dumps(receipt, indent=2))
        (temp / 'conflicts.json').write_text(json.dumps(conflicts, indent=2))
        files = [str(p.relative_to(modroot)) for p in sorted(modroot.rglob('*')) if p.is_file() and p.name != 'mod.json']
        (temp / 'native-files.json').write_text(json.dumps({
            str(p.relative_to(modroot)): dict(bytes=p.stat().st_size, sha256=sha(p.read_bytes()))
            for p in sorted(modroot.rglob('*')) if p.is_file()}, indent=2))
        catalogue = dict(schema=1, id='d4-unique-pilot', name='Local D4 unique comparison',
            games=[dict(id='d4', name='Disgaea 4 Complete+')], entries=[dict(id='d4:pc-en-valvatorez-10', game='d4',
            name='Valvatorez — partial comparison pilot', category='characters', status='build-ready',
            source=dict(edition=receipt['source_edition'], identity='char.dat:10', provenance=[dict(kind='source-table', reference=sha(source_raw))]),
            fidelity=dict(mode='hybrid', label='partial', missing_mappings=['Bloody Battle', 'D4 scenes', 'D4 Evility ownership', 'native acceptance'],
                          adaptations=receipt['limitations']), artifact=dict(mod_id=MOD_ID, required_payload=files))])
        registry = {MOD_ID: modroot}
        catalogue = gamepacks.validate_catalogue(catalogue, artifacts=registry)
        selection = gamepacks.resolve_selection(catalogue, artifacts=registry, entries=['d4:pc-en-valvatorez-10'])
        gamepacks.materialize(catalogue, selection, artifacts=registry, staging_path=temp / 'staged-kit')
        (temp / 'catalogue.json').write_text(json.dumps(catalogue, indent=2))
        final = dict(status='not-requested', native_gameplay_tested=False)
        if finalize:
            ctx = modsys.build(fs, [mod], log=log)
            if getattr(ctx, 'skipped_features', []):
                raise ValueError('Offline finalizer skipped features: ' + repr(ctx.skipped_features))
            inventory = []
            for _, (vp, content) in sorted(ctx.outputs.items()):
                rel = Path(vp)
                if rel.is_absolute() or '..' in rel.parts:
                    raise ValueError('Unsafe finalized virtual path')
                path = temp / 'finalized-logical' / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                if path.read_bytes() != content:
                    raise ValueError('Finalized output readback failed')
                inventory.append(dict(path=vp, bytes=len(content), sha256=sha(content)))
            actual = database.load_table('char.dat', (temp / 'finalized-logical' / CHAR).read_bytes())
            result = _one(actual, target_id)
            for field, value in expected.items():
                if field != 'color_id' and result[field] != value:
                    raise ValueError('Finalized character field mismatch: ' + field)
            if result['color_id'] != target_id:
                raise ValueError('New unique color identity was not finalized')
            for vanilla in tables['char.dat'].rows:
                if vanilla['id'] != target_id and bytes(_one(actual, vanilla['id']).raw) != bytes(vanilla.raw):
                    raise ValueError('Finalizer changed unrelated original character ' + str(vanilla['id']))
            qr2 = _one(database.load_table('Quest.dat', (temp / 'finalized-logical/Database/Database_0.dat/Quest.dat').read_bytes()), qid)
            if qr2['reward_value'] != target_id or qr2['sort_order'] != qslot:
                raise ValueError('Recruitment finalization mismatch')
            final.update(status='built-offline', files=inventory, character_readback=True, recruitment_readback=True,
                         unrelated_characters_unchanged=True, skipped_features=[],
                         finalizer_order=[fn.__module__ + '.' + fn.__name__ for fn in modsys.ordered_finalizers()])
        (temp / 'finalization.json').write_text(json.dumps(final, indent=2))
        originals.verify()
        (temp / 'original-read-receipt.json').write_text(json.dumps(originals.reads, indent=2))
        result = dict(output=str(output), mod=str(output / 'native-mods' / MOD_ID),
                      staging=str(output / 'staged-kit'), target_id=target_id, finalization=final['status'],
                      status='partial', native_tested=False)
        (temp / 'build-result.json').write_text(json.dumps(result, indent=2))
        os.rename(temp, output)
        temp = None
        return result
    finally:
        fs.reset()
        if temp is not None:
            # Absolute paths keep CLI audit checks meaningful during failure cleanup.
            def remove_owned(path):
                for child in path.iterdir():
                    if child.is_dir() and not child.is_symlink():
                        remove_owned(child)
                    else:
                        child.unlink()
                path.rmdir()
            remove_owned(temp)
