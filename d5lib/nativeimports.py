"""Bounded prepared-source imports through native Kit writers.

Readers, source archives and empirical pose composition remain caller-owned.
This module never installs, allocates global IDs or implements source abilities.
The ordinary mod reservation/finalization utilities live in d4expansion; their
generic helpers are reused without invoking either D4 source builder/parser.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

from . import database, dbpatch, sourcefidelity, sourceimports
from .importcore import NO_YIELD_FIELD_NOTE, donor_yield

DB = 'Database/Database_0.dat/'

# Reviewed-ability machinery ported from the DD2 prepared-source lane
# (`work/dd2-source-pack-20261019`), Cryswar-lineage design, The Unlicense; the sourcemap is the
# reviewed map for each source game and the only place a product id comes from.
SOURCEMAPS = Path(__file__).with_name('sourcemaps')

# The source releases write Unicode punctuation in their Latin text: DD2's CJK fullwidth stops
# ("Archangel．") and D1 Complete's U+2212 minus sign where the word is "Astro-One".  D5's own text is
# ASCII, so every Latin slot this module writes is folded.  Folding is display-only: the raw source
# line stays in the receipt.  JP slots are never passed through here -- a source name that is
# genuinely Japanese stays Japanese.
PRODUCT_TEXT = {0xFF0E: '.', 0xFF0C: ',', 0xFF1F: '?', 0xFF01: '!',
                0xFF05: '%', 0xFF1A: ':', 0xFF08: '(', 0xFF09: ')',
                0xFF1B: ';', 0xFF0D: '-', 0xFF5E: '~', 0x2212: '-'}
SOURCE_TAGS = ('Unique', 'Mounted')
# classcheck R7: only `_EN`/`_FR` are the Latin slots; the JP/CHN/KOR slots are UTF-8 in the vanilla
# table, so a source spelling there is legitimate and is never folded.
CJK_SUFFIXES = ('_JP', '_CHN', '_KOR')


def ascii_latin(text):
    """One Latin-slot string (char.dat name/title, charhelp line) with source punctuation folded to ASCII.

    Nothing else changes: no transliteration, no case change.  Never call this on a *_JP field."""
    return str(text).translate(PRODUCT_TEXT)


def class_display_name(name, game):
    """A generic class's player-facing name, tagged with its source game: "Gargoyle (D1C)", "Masked Hero (DD2)".

    CLASSTAG1: two source games ship the same class (Masked Hero, Gargoyle, Golem ...), so an untagged name
    doubles in the recruit list.  D4 classes were always tagged " (D4)" (`importers/d4.py --class-name`); this
    gives the prepared-source classes the same tag, spelt like the mod title (`mod.json` name).  Longest result
    "Shark Dragon (DD2)" = 18 characters, the same as D4's "Dragon Zombie (D4)"; char.dat's name slots are 52 bytes."""
    return name + ' (' + str(game).upper() + ')'


def product_text(text):
    """One source string as product text: source tag and caster placeholder removed, punctuation folded."""
    value = str(text)
    for tag in SOURCE_TAGS:
        prefix = tag + '\uff1a'
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    value = value.replace('%s ', '').replace('%s', '').strip()
    return ascii_latin(value)


def latin_slots(source):
    """The ASCII Latin text a prepared source packet writes: char.dat name, per-rank titles, help lines.

    The only place the fold is decided, so a rebuild of any packet -- with or without source abilities
    -- cannot carry Unicode source punctuation into a Latin slot again."""
    name = ascii_latin(source['name'])
    titles = [ascii_latin(rank['title']) for rank in source['ranks']]
    help_lines = [product_text(line) for line in source['help_lines']]
    return name, titles, help_lines


def _set_latin(row, prefix, text, source=None):
    """Write one product string to a row's Latin slots (EN/FR), then put the source spelling back in JP/CHN/KOR.

    `text` is the ASCII product text; the other slots keep exactly what the source wrote, so nothing is
    transliterated into or out of Japanese and a Latin source name keeps the source's spelling there
    (classcheck R7 counts only EN/FR as Latin slots)."""
    from . import charstudio
    charstudio.set_langs(row, prefix, text)
    if source is not None:
        for suffix in CJK_SUFFIXES:
            key = prefix + suffix
            if key in row.keys():
                row.set(key, str(source), truncate=True)


def load_sourcemap(game):
    """The reviewed mapping for `game` (d5lib/sourcemaps/<game>.json), validated by identity."""
    path = SOURCEMAPS / (str(game) + '.json')
    if not path.is_file():
        raise ValueError('No reviewed source map for ' + str(game))
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or data.get('game') != game:
        raise ValueError('Source map identity mismatch for ' + str(game))
    return data


def ability_sourcemap(game):
    """The source map for the ability route (packets carrying source skills/evilities, the DD2 route): it must be
    an ability map.  d1c.json is a per-character learn-list map (UNIQUESKILLS1) and does not qualify."""
    data = load_sourcemap(game)
    if 'skills' not in data or 'evilities' not in data:
        raise ValueError('Source map for ' + str(game) + ' is not an ability map')
    return data


def _claimed_abilities(mods):
    """Every magic.dat / Skill.dat id an already-built mod adds or edits."""
    claims = {'skills': set(), 'evilities': set()}
    for mod in mods:
        for kind, table in (('skills', 'magic.dat'), ('evilities', 'Skill.dat')):
            patch = mod.load_patch('db', table + '.json') or {}
            for row in patch.get('added', []) or []:
                if isinstance(row, dict) and isinstance(row.get('id'), int):
                    claims[kind].add(row['id'])
            for row in (patch.get('rows') or {}).values():
                if isinstance(row, dict) and isinstance(row.get('id'), int):
                    claims[kind].add(row['id'])
    return claims


def ability_plan(source, sourcemap, vanilla, claimed):
    """Reviewed recipes -> concrete product rows; omits are recorded, never silently dropped.

    `vanilla` = {'skills': {ids}, 'evilities': {ids}} of the unmodified game,
    `claimed` = output of _claimed_abilities for every other supplied mod.
    """
    if sourcemap.get('edition') != source['edition']:
        raise ValueError('Source map edition differs from the packet edition')
    plan = {'skills': [], 'evilities': [], 'omitted': [], 'aliases': {}}
    for kind, key, name_key in (('skills', 'skills', 'name'), ('evilities', 'evilities', 'name')):
        recipes = sourcemap.get(kind, {})
        for item in source.get(key) or []:
            sid = int(item['id'])
            recipe = recipes.get(str(sid))
            singular = 'skill' if kind == 'skills' else 'Evility'
            label = 'skill' if kind == 'skills' else 'evility'
            if recipe is None:
                raise ValueError('Unmapped DD2 %s %d' % (singular, sid))
            if recipe.get('relation') == 'omit':
                plan['omitted'].append(dict(kind=label, source_id=sid,
                                            name=item.get(name_key), reason=recipe.get('reason', '')))
                continue
            product = sourcemap.get('allocations', {}).get(kind, {}).get(str(sid))
            if type(product) is not int:
                raise ValueError('No reviewed product id for DD2 %s %d' % (singular, sid))
            if product in vanilla[kind] or product in claimed[kind]:
                raise ValueError('Product %s id %d is already taken' % (singular, product))
            claimed[kind].add(product)
            entry: dict[str, object] = dict(kind=label, source_id=sid, id=product,
                         relation=recipe['relation'], source_name=item.get(name_key),
                         source_description=item.get('description'), note=recipe.get('note', ''))
            exact = recipe['relation'] == 'exact'
            if kind == 'skills':
                entry['copy_of'] = int(recipe['copy_of'])
                entry['copy_of_name'] = recipe.get('copy_of_name')
                # A skill row carries the source name, so it carries the source flavour text too; the
                # relation note states that the numbers are the donor's. An absent text keeps the donor's.
                entry['desc'] = product_text(item.get('description') or '') or None
            else:
                entry['copy_of'] = int(recipe['works_like'])
                entry['copy_of_name'] = recipe.get('works_like_name')
                entry['desc'] = product_text(item.get('description') or '') if exact else None
                plan['aliases'][str(product)] = entry['copy_of']
            plan[kind].append(entry)
    return plan


def rank_abilities(plan, ranks, generic):
    """Per source rank: the product learn list and (uniques only) innate evility ids.

    Source ranks carry their own decoded learn/evility ids; an id with no reviewed
    recipe never reaches this function because ability_plan refuses it.
    """
    by_skill = {e['source_id']: e['id'] for e in plan['skills']}
    by_evility = {e['source_id']: e['id'] for e in plan['evilities']}
    out = []
    for k, rank in enumerate(ranks):
        learn = [(by_skill[int(sid)], int(level)) for sid, level in (rank.get('learn') or [])
                 if int(sid) in by_skill]
        if len(learn) > 16:
            raise ValueError('Rank %d learns %d skills; the game has 16 learn slots' % (k + 1, len(learn)))
        innate = [by_evility[int(sid)] for sid in (rank.get('evilities') or []) if int(sid) in by_evility]
        if generic:
            innate = []                      # class evilities are shop-learned, not innate
        if len(innate) > len(dbpatch.EVILITIES):
            raise ValueError('Rank %d has %d innate evilities; the game has %d slots'
                             % (k + 1, len(innate), len(dbpatch.EVILITIES)))
        out.append(dict(learn=learn, innate=innate))
    return out


def _write_abilities(fs, mod, plan, generic, target):
    """Create the reviewed magic.dat / Skill.dat rows and the Evility alias table."""
    from . import newclasses
    for sk in plan['skills']:
        newclasses.add_skill(fs, mod, sk['id'], sk['copy_of'], sk['source_name'], sk['desc'])
    for order, ev in enumerate(plan['evilities'], 1):
        if generic:
            newclasses.add_evility(fs, mod, ev['id'], ev['copy_of'], ev['source_name'], ev['desc'],
                                   owner=target, order=order, kind=0, source=3)
        else:
            newclasses.add_evility(fs, mod, ev['id'], ev['copy_of'], ev['source_name'], ev['desc'],
                                   owner=target, order=0, kind=1, source=4, slot_cost=0, shop_rank=0)
    if plan['aliases']:
        mod.save_patch('evilities', 'aliases.json', plan['aliases'])


def validate_source(source, prepared):
    """Bind explicit exact source ranks, authored palettes and product prose."""
    identity = prepared['identity']
    ranks = source['ranks']
    count = len(ranks)
    if count not in (1, 6) or source['game'] != identity['source'] or source['edition'] != identity['edition']:
        raise ValueError('Source game/edition or genuine rank count mismatch')
    if ranks[0]['id'] != identity['character_id'] or len({r['id'] for r in ranks}) != count:
        raise ValueError('Prepared identity must match distinct genuine source ranks')
    bindings = source['rank_palette_bindings']
    if len(bindings) != count:
        raise ValueError('One authored palette binding per genuine source rank required')
    for k, (rank, binding) in enumerate(zip(ranks, bindings, strict=True)):
        sourcefidelity.from_profile(rank, game=source['game'], edition=source['edition'],
                                   rank_count=count, rank_index=k)
        if (binding['id'] != rank['id'] or binding['body'] != identity['body'] or
                binding['row_sha256'] != rank['evidence']['row_sha256'] or
                type(binding['palette']) is not int or not 0 <= binding['palette'] < 10):
            raise ValueError('Source rank/palette/body evidence mismatch')
        if not isinstance(rank.get('title'), str) or not rank['title'].strip():
            raise ValueError('Every genuine source rank requires a source title')
    help_lines = source['help_lines']
    if (not isinstance(help_lines, list) or not 1 <= len(help_lines) <= 3 or
            any(not isinstance(v, str) for v in help_lines) or not any(v.strip() for v in help_lines)):
        raise ValueError('Source product help needs one to three source text lines')
    receipt = prepared['evidence'].get('source_receipt', {})
    if receipt:
        if (receipt.get('rank_palette_bindings') != bindings or
                [r['evidence']['row_sha256'] for r in receipt['source_rank_profiles']] !=
                [r['evidence']['row_sha256'] for r in ranks]):
            raise ValueError('Prepared source receipt differs from supplied ranks/bindings')
    return source


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def _portrait(fs, mod, physical, template, paths, matte, *, generic, fit='stretch'):
    """Replace the main illustration; clear donor auxiliary picture layers.  `fit` is imgtools.cutin_placement's mode;
    returns one placement record per picture written (DD2CUTIN1: the receipt carries them)."""
    from . import anm, newclasses, sprites
    if generic:
        placements = newclasses.set_portraits(fs, mod, physical, template, paths, matte=matte, fit=fit)
    else:
        from PIL import Image
        from .imgtools import fit_cutin, screen_picture
        import numpy as np
        portrait = anm.parse(fs.read(sprites.sprite_vpath(fs, template + 10000, 'EN')))
        for block in portrait.blocks:
            block.id = physical + 10000
        with Image.open(paths[0]) as image:
            # no automatic transparency (PT1027 S3): the cut-in keeps its own background unless the
            # caller asks for a matte AND the opt-in is set -- imgtools.screen_picture decides
            image = screen_picture(image, matte)
            texture = portrait.textures[0]
            if texture.indexed:
                raise ValueError('Prepared-source cut-in requires an RGBA receiver')
            fitted, place = fit_cutin(image, (texture.width, texture.height), fit)
            texture.data = anm._rgba_to_argb(np.asarray(fitted)).tobytes()
            placements = [dict(place, source_size=list(image.size), texture=[texture.width, texture.height],
                               bank=physical + 10000)]
        mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical + 10000:05d}.lzs', portrait.to_bytes())
    for number in range(physical + 10000, physical + 10000 + (10 if generic else 1)):
        vp = f'Anime/ANM_HI_JP.dat/anm{number:05d}.lzs'
        raw = mod.read_file(vp)
        if raw is None:
            continue
        portrait = anm.parse(raw)
        if portrait.textures[0].indexed:
            raise ValueError('Prepared-source cut-in requires an RGBA receiver')
        for texture in portrait.textures[1:]:
            texture.data = bytes(len(texture.data))
        mod.write_file(vp, portrait.to_bytes())
    return placements


def _check_targets(byid, target, count, dummy_rows):
    """Every target row must be absent, a declared Kit dummy row, or flagged dummy.

    A real row belongs to the game or another mod: reusing it would overwrite an
    installed identity, so this refuses instead of editing in place.
    """
    for k in range(count):
        cid = target + k
        row = byid.get(cid)
        if row is not None and not (cid in dummy_rows or row['is_dummy_slot']):
            raise ValueError('Existing non-dummy target row')


def unique_identity(identity, physical):
    """Check a unique's registry identity and the low "physical" row its art is keyed to.

    The identity is one rank of a registry class family: a multiple of ten (rank 0; digits 6-9 are
    reserved), at or above 10000, below the range's end, and outside Overlord's reserved band.  The
    physical row is the id the sprites, portraits and faces are keyed to: the sprite set `row .. row+2`
    and the cut-in / status portraits `10000 + row .. +1` (d5lib/d4unique.py:479), so it must be a low
    id (a unique's graphics namespace) and it may never be the identity itself.
    """
    identity, physical = int(identity), int(physical)
    if not 10000 <= identity <= 32760 or identity % 10 or 20000 <= identity < 22000:
        raise ValueError('unique registry identity must be a multiple of 10 in 10000..32760, outside 20000..21999')
    if not 10 <= physical < 1000:
        raise ValueError('a unique leases a low physical row below 1000 for its art')
    if identity == physical:
        raise ValueError('unique identity and physical row must differ')
    return dict(identity=identity, physical=physical,
                keyed=[physical, physical + 1, physical + 2, 10000 + physical, 10001 + physical])


def _check_physical_key(fs, physical, kind):
    """Refuse a physical row whose keyed art numbers the game or another mod already uses.

    `sprites.used_sprite_numbers` is the receiver's own inventory of anm numbers (the game's files and
    every installed mod's), so a free lease cannot overwrite a real character's art or portrait.
    """
    from . import sprites
    used = sprites.used_sprite_numbers(fs)
    keyed = {physical, physical + 1, physical + 2, 10000 + physical, 10001 + physical}
    taken = sorted(keyed & used)
    if taken:
        raise ValueError('physical art keys %s are already used by %s' % (taken, kind))
    return sorted(keyed)


def _gameplay_row(donor, desc, color_id, battle=None):
    """A rank row from the donor with source stats, keeping donor voice/magichange.

    Voice and magichange are deliberately inherited: every vanilla class row has a
    voice id, and zeroing it produced a class row the recruit screen crashed on.
    """
    row, report = sourcefidelity.encode_gameplay(donor, desc)
    row.set('color_id', color_id)
    if battle:
        # DD2FIELDS1: source battle fields written over the donor's; recorded so the generic path copies them
        for key, value in battle.items():
            row.set(key, value)
        report['fields'] = dict(report['fields'], **{k: row[k] for k in battle})
        report['battle_source_fields'] = sorted(battle)
    return row, report


def _skill_plan(skills, rank_count):
    """Normalise a caller's mapped-skill plan to one list per rank.

    ``skills`` is ``None`` (nothing mapped), a flat ``[(id, level), ...]`` applied to
    every rank, or a per-rank list of such lists. Ids and levels are validated by the
    caller against the receiver's own magic.dat; this only fixes the shape.
    """
    if skills is None:
        return [[] for _ in range(rank_count)]
    if not isinstance(skills, (list, tuple)):
        raise ValueError('skills must be a list of (skill id, learn level) pairs')
    if skills and isinstance(skills[0], (list, tuple)) and skills[0] and isinstance(skills[0][0], (list, tuple)):
        plan = [[tuple(p) for p in rank] for rank in skills]
        if len(plan) != rank_count:
            raise ValueError('skills plan must carry one list per rank')
        return plan
    flat = [tuple(pair) for pair in skills]
    return [list(flat) for _ in range(rank_count)]


def _apply_learn(row, pairs):
    """Write a rank row's learned-skill slots: 16 slots, then the count field."""
    if len(pairs) > 16:
        raise ValueError('more learned skills than the 16 receiver slots')
    if len({int(s) for s, _ in pairs}) != len(pairs):
        raise ValueError('duplicate skill id in the mapped learn list')
    for i in range(16):
        skill, level = pairs[i] if i < len(pairs) else (0, 0)
        row.set(f'learn{i + 1}_skill', int(skill))
        row.set(f'learn{i + 1}_level', int(level))
    if 'learn_count' in row:
        row.set('learn_count', len(pairs))


def _apply_innate(row, innate, report=None):
    """Write a rank row's innate evility slots (dbpatch.EVILITIES) and their count.

    `report` is the gameplay report of the same rank: the fields written here are recorded in it, so
    the readback check compares the row against what this call did rather than against the source
    profile (which carries no receiver evility ids).
    """
    if len(innate) > len(dbpatch.EVILITIES):
        raise ValueError('more innate evilities than the receiver slots')
    written = {fname: int(innate[n]) if n < len(innate) else 0
               for n, fname in enumerate(dbpatch.EVILITIES)}
    for fname, value in written.items():
        row.set(fname, value)
    if 'evility_count' in row:
        row.set('evility_count', len(innate))
        written['evility_count'] = len(innate)
    if report is not None:
        report['fields'].update(written)


def build_entry(*, source, prepared_root, library_root, game_path, original_state,
                output_path, mod_id, target, physical, template, kind,
                face_paths, cutin_paths, source_palettes, mods_roots=(),
                help_id=None, quest_id=None, quest_slot=None, unlocked_ranks=None,
                approximate_palettes=False, exact_palette_banks=False, matte=None, log=print, whole_body=True,
                skills=None, source_times=None, source_tracks=None, sprite_shape=None, default_palette=0, attack_track=False, attack_max_frames=None,
                source_base_bank=0, cutin_fit='stretch'):
    """Emit one isolated native source mod; caller supplies pinned offline leases.

    `source` is an extracted source-neutral packet, not a game-table parser.
    One rank creates a low unique, six create a registered generic family.
    Donor skills are always cleared; `skills` supplies the mapped receiver skill ids and
    learn levels (flat for every rank, or one list per rank) and is validated against the
    receiver's own magic.dat. No Evilities/Overload are inherited; voice is explicitly
    muted until the later source voice phase. Other receiver mechanics stay disclosed.

    whole_body=True keeps one donor body track per animation (the D4 rule: the
    donor's extra arm/hair/shield layers must not show through a complete source
    pose). It is off for the D1 Complete monster slice, where the receiver's skill
    animations draw their own body layer on a second track; suppressing that track
    left 9 of 10 attack frames empty.

    sprite_shape=(pages, palettes): the receiver bank this rebuild replaces. The built
    bank is given exactly that many atlas pages (the frames are spread over them) and
    palette entries, so a rebuild never changes the image-header count of a bank the
    game already loads. None: the natural count of the composed atlas.
    """
    from PIL import Image
    import numpy as np
    from . import (anm, charstudio, d4expansion, gamefs, gamepacks, modsys,
                   newchars, newclasses, offlinepaths, outfits, ownanim, slots, sprites)
    from .d4unique import Originals
    from . import frameconvert

    output = Path(os.path.abspath(output_path))
    protected = (prepared_root, library_root, game_path, original_state,
                 Path(__file__).resolve().parents[1], *mods_roots, *face_paths, *cutin_paths)
    offlinepaths.offline_output(output, protected)
    offlinepaths.offline_output(str(output) + '.cache', (*protected, output))
    offlinepaths.require_output_cache(sprites.CACHE_DIR, output, protected)
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('New canonical offline output required')
    prepared = sourceimports.read_prepared(prepared_root, library_root,
                                          edition=source['edition'], source_game=source['game'])
    validate_source(source, prepared)
    ranks = source['ranks']
    generic = len(ranks) == 6
    # A one-rank unique either keeps the legacy shape (class id = its own char row, below 1000) or leases a
    # registry identity with a separate low row for its art (see unique_identity()).
    registry_unique = (not generic) and int(target) != int(physical)
    if kind not in ('humanoid', 'monster'):
        raise ValueError('Explicit receiver kind required')
    if generic:
        newclasses.validate_specs([dict(family=target, template=template,
                                       sprite_family=physical, kind=kind)])
    elif target == physical:
        if not 10 <= target < 1000:
            raise ValueError('Low unique requires its own physical identity')
    else:
        # A unique on a registry identity: one rank whose class id is >= 10000 (the shape Overlord ships
        # for Stella 20300; d5_custom_classes.c, The Unlicense, credit Cryswar) and whose art is keyed to a
        # separate low "physical" row leased for it.  The class id is also its char.dat row id because the
        # game's own char_find_by_id (0x140061f80) binary-searches the table by id.
        unique_identity(target, physical)
    if not face_paths or not cutin_paths:
        raise ValueError('Source-backed face and illustration required')
    palettes = np.asarray(source_palettes, dtype=np.uint8)
    if palettes.shape != (10, 256, 4):
        raise ValueError('Ten complete authored source RGBA banks required')
    if unlocked_ranks is None:                  # default: every rank the pack builds
        unlocked_ranks = len(ranks)
    if type(unlocked_ranks) is not int or not 1 <= unlocked_ranks <= max(len(ranks), 1):
        raise ValueError('unlocked_ranks must be 1..the ranks the pack builds')
    if generic and int(target) >= 10000 and unlocked_ranks != len(ranks):
        # a registry family has no mastery chain in the receiver, so a partial declaration leaves
        # built rows unreachable in the Recruiter and the rank switch (classcheck R2)
        raise ValueError('a registry class declares every rank it builds')
    originals = Originals(original_state)
    fs = gamefs.GameFS(str(game_path), backup_resolver=originals)
    output.mkdir(parents=True)
    try:
        ct = database.load_table('char.dat', fs.read(DB + 'char.dat'))
        byid = {r['id']: r for r in ct.rows}
        _check_targets(byid, target, len(ranks), slots.DUMMY_ROWS)
        if registry_unique:
            _check_physical_key(fs, physical, 'the game or an installed mod')
        plan = _skill_plan(skills, len(ranks))
        magic_raw = None
        if any(plan):
            magic_raw = fs.read(DB + 'magic.dat')
            mt = database.load_table('magic.dat', magic_raw)
            known = {r['id'] for r in mt.rows}
            for k, pairs in enumerate(plan):
                for skill_id, level in pairs:
                    if skill_id not in known:
                        raise ValueError(f'mapped skill {skill_id} is absent from the receiver magic.dat')
                    if not 1 <= int(level) <= 9999:
                        raise ValueError(f'mapped skill {skill_id} has an out-of-range learn level')
        else:
            mt = None
        # Source abilities: a packet that carries them is applied from the reviewed source map (the DD2
        # route). Sources that map onto existing receiver rows pass `skills` instead; both may not mix.
        abilities = per_rank = sourcemap = None
        personalities = None
        if source.get('skills') or source.get('evilities'):
            if any(plan):
                raise ValueError('A packet with source abilities cannot also pass a mapped skills plan')
            sourcemap = ability_sourcemap(source['game'])
            magic_raw = fs.read(DB + 'magic.dat')
            vanilla = {
                'skills': {r['id'] for r in database.load_table('magic.dat', magic_raw).rows},
                'evilities': {r['id'] for r in database.load_table('Skill.dat', fs.read(DB + 'Skill.dat')).rows},
            }
            abilities = ability_plan(source, sourcemap, vanilla,
                                    _claimed_abilities([modsys.Mod(str(p)) for p in mods_roots]))
            per_rank = rank_abilities(abilities, ranks, generic)
            plan = [[tuple(pair) for pair in rank['learn']] for rank in per_rank]
        # Both source games write Unicode punctuation in their Latin text (DD2 fullwidth stops, D1
        # Complete's U+2212); D5's own text is ASCII, so every packet's name, titles and help lines are
        # folded here -- whether or not it carries source abilities.  The raw lines stay in the receipt
        # (`source_help_lines`); nothing is transliterated and no *_JP slot is touched.
        text = latin_slots(source)
        product_name, product_titles, display_help = text
        if generic:
            product_name = class_display_name(product_name, source['game'])
        donor = byid[template]
        if (donor['body_type'] == 1) != (kind == 'monster'):
            raise ValueError('Receiver body_type disagrees with explicit kind')
        required = ('stand', 'wait', 'walk', 'damage', 'attack_fist')
        if any((pose, view) not in prepared['sequences'] for pose in required for view in ('front', 'back')):
            raise ValueError('Prepared source lacks required ordinary actions')
        base = anm.parse(fs.read(sprites.sprite_vpath(fs, template, 'EN')))
        while len(base.palettes) < 10:
            anm.set_palette(base, len(base.palettes), anm.get_palette(base, 0))
        motion = sprites.motion_block(fs, 1, log) if sprites.needs_motion_set(base) else None
        animation = {}
        timing = None
        if source_times:
            timing = {(str(k).split('_')[0], str(k).split('_')[-1]): v for k, v in source_times.items()}
        if attack_track and kind == 'monster':      # MONATK1: the source's own attack frames on the donor's attack clock
            source_tracks = {**(source_tracks or {}),
                             **ownanim.attack_tracks(base.blocks[0], source_times,
                                                     *(() if attack_track is True else (attack_track,)),
                                                     max_frames=attack_max_frames)}
        sprite = ownanim.build(prepared['sequences'], base, motion, physical,
            variants=[(0, 0, 0)], report=animation, log=log,
            prefer=frameconvert.MONSTER_ROWS if kind == 'monster' else frameconvert.HUMAN_ROWS,
            source_fallbacks=True, whole_body=whole_body, source_times=timing, source_tracks=source_tracks,
            anchor_feet=False, uniform_offset=True, shape=sprite_shape)
        from . import standground
        standground.normalize_stand_ground(sprite, standground.bound_reference(base, motion),
                                           report=animation, log=log)
        if sprite_shape:
            # The receiver bank's image-header count, applied after every step that moves a drawing (the
            # stand-ground shift above changes where the Quest Shop banner wants the stand picture): the
            # atlas is packed in the installer's own banner layout over exactly the receiver's page count,
            # so the installer's banner_layout call is a no-op and cannot compact the pages away
            # (PALFIX2B measured that compaction on the D1C uniques).
            laid = ownanim.banner_layout(sprite, pages=sprite_shape[0])
            if isinstance(animation, dict) and 'receiver_shape' in animation:
                animation['receiver_shape'].update(banner_relaid=laid, pages_final=len(sprite.textures))
        palette_report = {}
        palette_mapping = sourceimports.map_source_palettes(
            sprite, palettes, approximate=approximate_palettes,
            exact_banks=exact_palette_banks, report=palette_report, base_bank=source_base_bank)
        if palette_mapping[1] and not approximate_palettes:
            raise ValueError('Composited/quantized palette needs explicit approximation policy: %r'
                             % (palette_report,))
        if sprite_shape and len(sprite.palettes) > len(palettes):
            # The receiver bank's extra palette group (the graft lineage's offset-10 group): give it the
            # character's own mapped colours as well.  No cell of this build indexes it, but a key the game
            # resolves with a palette offset past the source's banks would otherwise draw the fitted atlas
            # palette instead of the character (the installed banks map offset 10 to the source colours too).
            for k in range(len(palettes), len(sprite.palettes)):
                anm.set_palette(sprite, k, anm.get_palette(sprite, k % len(palettes)))
        if not generic:     # D1CCOLOR1: a unique's source-selected palette is its default slot
            sourceimports.select_default_palette(sprite, default_palette)
        mod = modsys.Mod(str(output / 'native-mods' / mod_id))
        if abilities is not None:
            _write_abilities(fs, mod, abilities, generic, target)
        gaps = ['D5 receiver timing, attachments, movement, resistances, mastery and progression are adaptations',
                'Empirical source pose composition is not native-equivalent animation playback',
                ('Source voice and Evilities omitted/backlogged for the later fidelity phase; the donor '
                 'template voice and magichange fields are inherited so the class row stays vanilla-shaped'
                 if any(plan) else
                 'Source voice, skills and Evilities omitted/backlogged for the later fidelity phase; the donor '
                 'template voice and magichange fields are inherited so the class row stays vanilla-shaped'),
                'Native recruitment, battle and save/reload acceptance pending']
        if abilities is not None:
            gaps.append('Source skills and Evilities are reviewed adaptations, not native-equivalent rules; every '
                        'omitted or lookalike source id is listed in this receipt with its reason')
        elif any(plan):
            gaps.append('Mapped skills are existing D5 rows of the same ability name (no skill copies); learn '
                        'levels reuse the source table number, which is a source mastery tier rather than a '
                        'receiver character level. Every unmapped source ability stays backlogged.')
        if palette_mapping[1]:
            gaps.append('Composited/quantized colours mapped to nearest authored source RGB; source bank/index choices disclosed')
        if exact_palette_banks and palette_report.get('dropped_banks') == [] and source_base_bank:
            gaps.append('Source palette bank %d is the default slot and every source bank ships exactly (%d exact entries, '
                        'no ambiguous colour)' % (source_base_bank, palette_report.get('exact_entries')))
        if palette_report.get('dropped_banks') and exact_palette_banks:
            gaps.append('Source palette banks %s are not shipped: %d used colour(s) have two source indices that '
                        'diverge in those banks, so no exact colour exists there; every receiver palette uses the '
                        'exact bank-0 colours instead (%d exact entries)'
                        % (palette_report.get('dropped_banks'), palette_report.get('ambiguous_used_colours'),
                           palette_report.get('exact_entries')))
        battle_record = None
        if any(rank.get('battle_fields') for rank in ranks):
            from .dd2source import BATTLE_DONOR as donor_fields
            battle_record = dict(
                rule='DD2FIELDS1: battle block read from the source char.dat row; every field below is source-exact '
                     'or rule-converted, the donor fields are listed with their reason',
                ranks=[dict(source_id=rank['id'], fields={k: dict(value=rank['battle_fields'][k], **rank['battle_provenance'][k])
                                                          for k in rank['battle_fields']},
                            donor=sorted(k for k in donor_fields if k not in rank['battle_fields']))
                       for rank in ranks if rank.get('battle_fields')],
                donor_reasons=dict(donor_fields))
            gaps[0] = ('D5 receiver timing, attachments and progression are adaptations; movement, jump, throw, counter, '
                       'critical, range, flying, resistances (fire/wind/ice), weapon aptitudes and kind/gender are source '
                       'values (mod.json battle_fields); HL/EXP/Mana, is_unique, star and weapon resistances stay donor')
        mod.meta.update(name=(product_name if generic else class_display_name(product_name, source['game'])),
            author='Local source import', version='0.1.0', category='classes' if generic else 'characters',
            description='Source art and exact stored source bases/aptitudes; receiver mechanics adapted.',
            source_import=dict(identity=prepared['identity'], source_ranks=ranks,
                rank_palette_bindings=source['rank_palette_bindings'], native_tested=False, adaptations=gaps,
                **({'battle_fields': battle_record} if battle_record else {}),
                yield_source=donor_yield(NO_YIELD_FIELD_NOTE.format(source['game'].upper()))))
        mod.save_meta()
        mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical:05d}.lzs', sprite.to_bytes())
        companion = (newclasses.monster_companion(fs, sprite, template, physical)
                     if kind == 'monster' else ownanim.with_id(sprite, physical + 1))
        mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical + 1:05d}.lzs', companion.to_bytes())
        icon = outfits._resident_icon(fs, template + 2)
        if icon is None:
            raise ValueError('Missing receiver icon')
        icon = outfits.repaint_stand_icon(icon, base, motion, sprite)
        for palette in icon.palettes[1:]:
            palette.data = icon.palettes[0].data
        icon_mapping = sourceimports.map_source_palettes(
            icon, palettes, approximate=approximate_palettes, exact_banks=exact_palette_banks,
            base_bank=source_base_bank)
        if not generic:
            sourceimports.select_default_palette(icon, default_palette)
        icon.blocks[0].id = physical + 2
        mod.write_file(f'Anime/ANM_HI_JP.dat/anm{physical + 2:05d}.lzs', icon.to_bytes())
        gameplay = []
        encoded = []
        for k, rank in enumerate(ranks):
            desc = sourcefidelity.from_profile(rank, game=source['game'], edition=source['edition'],
                                              rank_count=len(ranks), rank_index=k)
            row, report = _gameplay_row(byid[template + k] if generic else donor, desc,
                                        physical + source['rank_palette_bindings'][k]['palette'],
                                        battle=rank.get('battle_fields'))
            gameplay.append(report)
            encoded.append(row)
            _apply_learn(row, plan[k])
            if per_rank is not None:
                _apply_innate(row, per_rank[k]['innate'], report=report)
        if generic:
            def edit(row, k):
                for key in gameplay[k]['fields']:
                    row.set(key, encoded[k][key])
                for key in ('voice_id', 'magichange_type', 'magichange_weapon', 'color_id'):
                    row.set(key, encoded[k][key])
                _apply_learn(row, plan[k])
            newclasses.fill_class(fs, mod, target, template, product_name, product_titles,
                help_lines=display_help, edit=edit, log=log, sprite_family=physical)
            # The Recruiter's personality page lists charPersonal.dat rows whose voice_group is the
            # class id / 10 and dereferences all three choices without a bounds check (Overlord
            # patches that page for the same reason: d5_custom_classes.c "the page needs 3").  A
            # family with no rows of its own wedges the create flow, so every generic family gets
            # the donor class's three rows under its own group.  Live evidence: the 13 D1C families
            # and DD2 22680 (this importer) wedged; every D4 family (sourceimports, which writes
            # these rows) created.
            personalities = newclasses.personality_names(fs, template)
            newclasses.add_personalities(fs, mod, target, template, personalities)
            newclasses.save_spec(mod, dict(family=target, template=template, kind=kind, sprite_family=physical,
                name=product_name, unlocked=True, unlocked_ranks=unlocked_ranks,
                hire_desc=' '.join(v.strip() for v in display_help if v.strip()),
                evility_alias=(abilities['aliases'] if abilities is not None else {})))
        else:
            if any(type(v) is not int for v in (help_id, quest_id, quest_slot)):
                raise ValueError('Explicit unique help/quest/progress leases required')
            row = encoded[0]
            # A registry unique keys its graphics to the leased physical row (sprite, companion, standing
            # picture, portraits 10000 + physical); a legacy low unique is its own art key.
            colour = physical if registry_unique else target
            for key, value in dict(id=target, sprite_id=physical, color_id=colour,
                                   help_id=help_id, is_dummy_slot=0, dlc_group=0).items():
                row.set(key, value)
            _set_latin(row, 'name', product_name, source['name'])
            _set_latin(row, 'title', product_titles[0], ranks[0]['title'])
            edited = database.load_table('char.dat', fs.read(DB + 'char.dat'))
            index = edited.index_of(target)
            if index >= 0:
                edited.rows[index] = row
            else:
                edited.rows.append(row)
            mod.save_patch('db', 'char.dat.json', dbpatch.diff_table(ct, edited))
            ht = database.load_table('charhelp.dat', fs.read(DB + 'charhelp.dat'))
            original_help = database.load_table('charhelp.dat', ht.to_bytes())
            if any(r['id'] == help_id or r['char_id'] == help_id for r in ht.rows):
                raise ValueError('Unique help lease already present')
            hr = ht.new_row()
            hr.set('id', help_id); hr.set('char_id', help_id)
            raw_help = dbpatch.help_lines(source['help_lines'])
            for k, text in enumerate(dbpatch.help_lines(display_help), 1):
                _set_latin(hr, f'line{k}', text, raw_help[k - 1])
            ht.rows.append(hr)
            mod.save_patch('db', 'charhelp.dat.json', dbpatch.diff_table(original_help, ht))
            qt = database.load_table('Quest.dat', fs.read(DB + 'Quest.dat'))
            original_quest = database.load_table('Quest.dat', qt.to_bytes())
            if any(r['id'] == quest_id or r['sort_order'] == quest_slot for r in qt.rows):
                raise ValueError('Unique recruitment lease already present')
            qr = next(r for r in qt.rows if r['id'] == 1).copy()
            for key, value in dict(id=quest_id, sort_order=quest_slot, reward_type=5,
                                   reward_value=target, reward_count=1, important=1).items():
                qr.set(key, value)
            charstudio.set_langs(qr, 'name', 'Recruit ' + product_name)
            charstudio.set_langs(qr, 'client', product_name)
            for k, text in enumerate(dbpatch.quest_lines('Welcome ' + product_name + ' after clearing Dried Up Wasteland.'), 1):
                charstudio.set_langs(qr, f'desc{k}', text)
            from . import questcheck
            questcheck.set_objective(qr, dict(type=4, target=101, count=1))
            qt.rows.append(qr)
            mod.save_patch('db', 'Quest.dat.json', dbpatch.diff_table(original_quest, qt))
            outfits.save(mod, [], own_sprites=[physical, physical + 1])
            # The finalizer reads this to give the identity its own face / banner / list icon under the
            # leased physical colour id (d5lib/outfits.py _finalize_characters): a registry unique is not
            # a class family, so it has no class descriptor and no unlock flags.
            # SMALLFIX1: a legacy low unique (identity == physical, e.g. Shark King 931, Xenolith 941) needs the
            # same declaration.  Its row's colour id is its own id, so newchars.find() saw "already has its own
            # colour id" (template None), cloned no face animation and the status-panel portrait stayed blank.
            mod.save_patch('characters', 'unique.json', dict(
                schema=1, identity=target, physical=physical, template=template,
                template_colour=int(donor['color_id']), kind=kind, name=product_name,
                rule=('one rank on a registry identity; sprite/portrait/face keys leased to physical'
                      if registry_unique else
                      'one rank on a low row that is its own art key (identity == physical)')))
        screen_art = []
        for k, path in enumerate(face_paths):
            from .imgtools import screen_picture
            with Image.open(path) as image:
                image = screen_picture(image, matte)
                (newclasses.set_face(mod, target, image, colour=k) if generic
                 else newchars.set_face(mod, physical if registry_unique else target, image))
            screen_art.append(dict(kind='face', path=str(path), sha256=sourceimports._hash(Path(path).read_bytes())))
        placements = _portrait(fs, mod, physical, template, [str(p) for p in cutin_paths], matte, generic=generic, fit=cutin_fit)
        screen_art += [dict(kind='cutin', path=str(p), sha256=sourceimports._hash(Path(p).read_bytes()),
                            fit=dict(placements[min(k, len(placements) - 1)], requested=cutin_fit))
                       for k, p in enumerate(cutin_paths)]
        others = [modsys.Mod(str(p)) for p in mods_roots]
        preflight = d4expansion.preflight(fs, [mod], others)
        readback, inventory = [], []
        for path in gamepacks._native_tree(Path(mod.folder)):
            raw = path.read_bytes()
            item = dict(path=str(path.relative_to(mod.folder)), bytes=len(raw), sha256=sourceimports._hash(raw))
            if path.suffix == '.lzs':
                parsed = anm.parse(raw)
                if gamefs.decode_member(gamefs.encode_like(raw, None, path.name)) != raw:
                    raise ValueError('ANM archive codec readback failed')
                item['anm_blocks'] = [b.id for b in parsed.blocks]
            if path.parent.name == 'db':
                name = path.name[:-5]
                table = database.load_table(name, fs.read(DB + name))
                dbpatch.apply_patch(table, json.loads(raw), strict=True)
                table = database.load_table(name, table.to_bytes())
                if name == 'char.dat':
                    for k, rank in enumerate(ranks):
                        row = table.find(target + k)
                        expected = dict({k: v for k, v in gameplay[k]['fields'].items()
                                         if not k.startswith('learn')},
                                        color_id=encoded[k]['color_id'],
                                        voice_id=encoded[k]['voice_id'],
                                        magichange_type=encoded[k]['magichange_type'],
                                        magichange_weapon=encoded[k]['magichange_weapon'])
                        wrong = {f: (row[f], v) for f, v in expected.items() if row[f] != v}
                        if wrong:
                            raise ValueError('Source static/rank-palette readback failed: %r' % wrong)
                        learned = [[row[f'learn{i}_skill'], row[f'learn{i}_level']]
                                   for i in range(1, 17) if row[f'learn{i}_skill']]
                        if learned != [[int(s), int(l)] for s, l in plan[k]]:
                            raise ValueError('Mapped learn-list readback failed')
                        readback.append(dict(id=row['id'], source_id=rank['id'], color_id=row['color_id'],
                            voice_id=row['voice_id'], magichange=[row['magichange_type'], row['magichange_weapon']],
                            base=[row['base_' + s] for s in sourcefidelity.STATS],
                            aptitudes=[row['apt_' + s] for s in sourcefidelity.STATS],
                            learned_skills=[dict(skill=s, level=l) for s, l in learned],
                            learn=learned,
                            innate=[row[f] for f in dbpatch.EVILITIES]))
                elif abilities is not None and name in ('magic.dat', 'Skill.dat'):
                    kind_of = 'skills' if name == 'magic.dat' else 'evilities'
                    for entry in abilities[kind_of]:
                        row = table.find(entry['id'])
                        if row is None or row['name_EN'] != entry['source_name']:
                            raise ValueError('Source %s row readback failed' % kind_of[:-1])
                        entry['readback'] = dict(id=row['id'], name=row['name_EN'],
                                                 description=row['desc_EN'], donor=entry['copy_of'])
            inventory.append(item)
        receipt = dict(schema=1, status='built-offline-not-installed', source=source,
            prepared_identity=prepared['identity'], source_art=prepared['evidence'],
            target=target, physical=physical, template=template, kind=kind,
            **({'unique_registry': dict(identity=target, physical=physical,
                                        colour_id=physical,
                                        keyed=[physical, physical + 1, physical + 2,
                                               10000 + physical, 10001 + physical],
                                        class_row_rule='char.dat row id == class id, found by the game\'s '
                                                       'char_find_by_id (0x140061f80) binary search',
                                        ranks=1,
                                        note='identity is a one-rank registry class; art is keyed to the leased '
                                             'physical row so no low char row is consumed')}
               if registry_unique else {}),
            source_help_lines=source['help_lines'], display_help_lines=display_help,
            displayed_help_lines=dbpatch.help_lines(display_help),
            text_folding=dict(rule='Unicode source punctuation folded to ASCII in the Latin slots; raw source lines kept above',
                              table={hex(k2): v2 for k2, v2 in PRODUCT_TEXT.items()},
                              tags_removed=list(SOURCE_TAGS), caster_placeholder_removed='%s'),
            gameplay=gameplay, readback=readback, screen_art=screen_art,
            palette_mapping=dict(exact=palette_mapping[0], approximated=palette_mapping[1], icon=list(icon_mapping),
                source_banks_sha256=sourceimports._hash(palettes.tobytes()), rank_bindings=source['rank_palette_bindings']),
            animation={k:v for k,v in animation.items() if k not in ('matches', 'offsets')},
            **({'abilities': dict(plan_source=str(SOURCEMAPS / (source['game'] + '.json')),
                                 map_edition=sourcemap.get('edition'),
                                 skills=[{k2: v2 for k2, v2 in e.items() if k2 != 'source_description'}
                                         for e in abilities['skills']],
                                 evilities=[{k2: v2 for k2, v2 in e.items() if k2 != 'source_description'}
                                            for e in abilities['evilities']],
                                 omitted=abilities['omitted'], aliases=abilities['aliases'],
                                 per_rank=per_rank),
                'voice': dict(sourcemap.get('voice') or {},
                              inherited_donor_voice=[r['voice_id'] for r in readback])}
               if abilities is not None else {}),
            skills=dict(mapped=[dict(rank=k, learned=[dict(skill=int(s), level=int(l)) for s, l in pairs])
                                for k, pairs in enumerate(plan)],
                        table='magic.dat', table_sha256=(hashlib.sha256(magic_raw).hexdigest()
                                                         if magic_raw is not None else None),
                        rule='existing D5 skill rows of the same ability name; no skill copies'),
            **({'personalities': dict(voice_group=target // 10, source='donor template %d' % template,
                                     names=personalities,
                                     inherited_from_donor=True,
                                     reason='the Recruiter personality page dereferences three '
                                            'charPersonal rows for the class family (classcheck R1)')}
               if generic else {}),
            adaptations=gaps, preflight=preflight, files=inventory, native_tested=False)
        _write_json(output / 'source-import-receipt.json', receipt)
        eid = f'{source["game"]}:source-{ranks[0]["id"]}'
        catalogue = dict(schema=1, id=source['game'] + '-prepared-import', name='Local prepared-source import',
            games=[dict(id=source['game'], name=source['edition'])], entries=[dict(id=eid, game=source['game'],
                name=product_name, category=('monsters' if kind == 'monster' else 'humanoid_classes') if generic else 'characters',
                status='build-ready', source=dict(edition=source['edition'], identity=f'char.dat:{ranks[0]["id"]}',
                    rank_count=len(ranks), source_ids=[r['id'] for r in ranks],
                    provenance=[dict(kind='source-table', reference=ranks[0]['evidence']['table_sha256'])]),
                fidelity=dict(mode='hybrid', missing_mappings=(['growth', 'evilities', 'voice', 'native acceptance']
                                    if any(plan) else ['growth', 'skills', 'evilities', 'voice', 'native acceptance']), adaptations=gaps),
                artifact=dict(mod_id=mod_id, required_payload=[i['path'] for i in inventory if i['path'] != 'mod.json']))])
        registry = {mod_id: mod}
        gamepacks.validate_catalogue(catalogue, artifacts=registry)
        selection = gamepacks.resolve_selection(catalogue, artifacts=registry, entries=[eid])
        gamepacks.materialize(catalogue, selection, artifacts=registry, staging_path=output / 'staged-kit')
        _write_json(output / 'catalogue.json', catalogue)
        originals.verify()
        _write_json(output / 'original-read-receipt.json', originals.reads)
        return dict(output=str(output), mod=str(Path(mod.folder)), mod_id=mod_id, entry_id=eid,
                    installed=False, native_tested=False)
    finally:
        fs.reset()
