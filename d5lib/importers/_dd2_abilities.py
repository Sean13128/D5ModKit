"""Apply the DD2 whole-table review to a staged pack, offline.

Native D5 skills are learned by reference. Owned Evility display rows use the
Kit's existing alias writer; the reviewed DD2 engine emission contains zero
extension rows, so this module never invents .d5el behavior. Cryswar's alias
and class-ownership design (The Unlicense) is reused through newclasses.

SOURCEPREP4-DD2: the source table comes from the prepared source folder, the
review and emission documents are checked-in kit data, and id collisions are
checked against the checked-in canonical claims (plus any installed root that
happens to be supplied) instead of requiring an installed mods folder.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import database, dd2source, modsys, nativeimports, newclasses
from . import _dd2_source as sources

LEASES = Path(__file__).with_name('dd2-ability-leases.json')
ALLOWED_SKILLS = frozenset(('exact', 'adapted', 'lookalike'))
ALLOWED_EVILITIES = frozenset(('exact', 'adapted'))


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_tables(source_root=None, *, review=None):
    """Read the verified DD2 START_4 table and check it against the reviewed snapshot hash.

    The file comes from the same verified set the rest of the import uses (``_dd2_source.data_dir``);
    no directory scan can pick another copy.
    """
    review = review or sources.ability_review()
    data = source_root if isinstance(source_root, sources.Dd2Data) else sources.data_dir(source_root)
    path = data.path('START_4.dat')
    digest = _hash(path)
    if digest != review['sources']['dd2']['sha256']:
        raise ValueError('DD2 START_4.dat differs from the reviewed coverage snapshot')
    return dd2source.Tables(dd2source.Nispack(path.read_bytes())), path, digest


def _reviewed_source(row, recipe, sid, label):
    """The source text, checked against the review's SHA-256 reference (no text in Git)."""
    name, desc = row['name'], row['description']
    if sources.text_sha(name) != recipe['dd2_name_sha256'] or sources.text_sha(desc) != recipe['dd2_desc_sha256']:
        raise ValueError(f'DD2 {label} {sid} differs from its reviewed source text')
    return name


def _donor_name(table, donor_id, expected_sha, label):
    """The donor's Disgaea 5 name, read from the user's own Skill.dat/magic.dat and hash-checked."""
    row = table.get(int(donor_id))
    if row is None:
        raise ValueError(f'Reviewed {label} donor {donor_id} is missing from the Disgaea 5 table')
    name = row['name_EN'].strip()
    if sources.text_sha(name) != expected_sha:
        raise ValueError(f'Reviewed {label} donor {donor_id} name changed or is not the reviewed one')
    return name


def plan_rank(tables, source_id, review, magic, skill):
    """Resolve exactly the stored learn list; retain every rejected source ID.

    Multiple source skills may map to one D5 ultimate. Learn it once at the
    earliest source level and keep both source mappings in the receipt.
    Weapon mastery entries have no character learn levels and stay mastery.
    ``magic``/``skill`` are the user's own Disgaea 5 rows keyed by id, so donor
    names come from the game rather than from reviewed text in Git.
    """
    skills, evilities, omitted = [], [], []
    learn = {}
    for sid, level in tables.learn_list(source_id):
        recipe = review['skills'].get(str(sid))
        item = dict(source_id=sid, level=level, kind='skill')
        if recipe is None:
            omitted.append(dict(item, relation='unresolved', reason='Source learn ID has no reviewed magic.dat row'))
            continue
        name = _reviewed_source(tables.skills[sid], recipe, sid, 'skill')
        item.update(relation=recipe['relation'], source_name=name, note=recipe.get('note', ''))
        if recipe['relation'] not in ALLOWED_SKILLS:
            omitted.append(dict(item, reason=recipe.get('note', 'Not eligible for emission')))
            continue
        target = recipe.get('copy_of')
        if type(target) is not int or target <= 0:
            raise ValueError(f'Eligible DD2 skill {sid} has no D5 target')
        item.update(target_id=target,
                    target_name=_donor_name(magic, target, recipe.get('copy_of_name_sha256'), 'skill'))
        if not 1 <= level <= 9999:
            raise ValueError(f'DD2 skill {sid} has invalid source learn level {level}')
        learn[target] = min(level, learn.get(target, level))
        skills.append(item)
    if len(learn) > 16:
        raise ValueError(f'DD2 row {source_id} exceeds the 16 native learn slots')
    source_evilities = tables.evilities_for(source_id)
    for index, (sid, source) in enumerate(source_evilities):
        recipe = review['evilities'].get(str(sid))
        item = dict(source_id=sid, kind='evility', signature=index == 0)
        if recipe is None:
            raise ValueError(f'DD2 evility {sid} has no review')
        name = _reviewed_source(source, recipe, sid, 'evility')
        item.update(relation=recipe['relation'], source_name=name, note=recipe.get('note', ''))
        if recipe['relation'] not in ALLOWED_EVILITIES:
            omitted.append(dict(item, reason=recipe.get('note', 'Not eligible for emission')))
            continue
        if type(recipe.get('copy_of')) is not int or recipe['copy_of'] <= 0:
            raise ValueError(f'Eligible DD2 evility {sid} has no native donor')
        item.update(donor_id=recipe['copy_of'],
                    donor_name=_donor_name(skill, recipe['copy_of'], recipe.get('copy_of_name_sha256'), 'evility'))
        evilities.append(item)
    return dict(source_id=source_id, skills=skills, evilities=evilities,
                learn=list(learn.items()), omitted=omitted,
                source_learn_count=len(tables.learn_list(source_id)),
                source_signature_id=source_evilities[0][0] if source_evilities else None,
                signature_supported=bool(evilities and evilities[0]['signature']),
                weapon_mastery_source_ids=list(tables.chars[source_id]['weapon_skills']),
                evility_assignment='inferred source numbering; alternate rows may be unresolved',
                evility_assignment_resolved=bool(source_evilities))


def _claims(root, skip=None):
    """All installed claims, including disabled packs and alias-only claims.

    ``skip`` is the pack being rebuilt: its own installed copy is not a competing claim."""
    claims = {}
    for folder in sorted(Path(root).iterdir()):
        if folder.name == skip or not folder.is_dir() or not (folder / 'mod.json').is_file():
            continue
        ids = set()
        path = folder / 'patches/db/Skill.dat.json'
        if path.is_file():
            patch = _load(path)
            ids.update(int(r['id']) for r in patch.get('added', []))
            ids.update(map(int, patch.get('rows', {})))
        for name, key in [('aliases.json', None), ('evilities.json', 'evilities')]:
            path = folder / 'patches/evilities' / name
            if path.is_file():
                value = _load(path)
                ids.update(map(int, value.get(key, {}) if key else value))
        for path in (folder / 'patches/classes').glob('class_*.json'):
            ids.update(map(int, _load(path).get('evility_alias', {})))
        for sid in ids:
            claims.setdefault(sid, []).append(folder.name)
    return claims


def _check_donor(table, sid, expected, label):
    rows = [row for row in table.rows if int(row['id']) == sid]
    if len(rows) != 1 or not expected or rows[0]['name_EN'].strip() != expected.strip():
        raise ValueError(f'Reviewed {label} donor {sid} name missing or changed (expected {expected!r})')


def apply_reviewed(pack_path, entry, ctx):
    """Add reviewed abilities to one output pack; never installs or edits sources.

    ctx['fs'] must be a read-only original GameFS. source_root optionally points
    to the canonical DD2 snapshot; id collisions are checked against the kit's
    recorded canonical claims and, when a root is supplied, any installed packs.
    Returns and stores a per-rank receipt, including rejected needs-new-logic.
    """
    root = Path(pack_path)
    fs = ctx['fs']
    review_path = Path(ctx.get('dd2_review') or sources.ABILITY_REVIEW)
    emission_path = Path(ctx.get('dd2_emission') or sources.ENGINE_EMISSION)
    review = _load(review_path)
    tables, source_path, digest = source_tables(ctx.get('source_root'), review=review)
    emission = _load(emission_path)
    if emission.get('extension_rows'):
        raise ValueError('DD2 extension review changed: explicit engine-row integration is required')
    mod = modsys.Mod(str(root))
    identity = mod.meta['source_import']['identity']
    source_id = int(identity['character_id'])
    generic = entry.kind == 'class'
    source_ids = [source_id + n for n in range(6)] if generic else [source_id]
    # The user's own Disgaea 5 rows: donor names are read from here, never from reviewed text in Git.
    mt = database.load_table('magic.dat', fs.read(newclasses.MAGIC))
    st = database.load_table('Skill.dat', fs.read(newclasses.SKILL))
    magic = {int(row['id']): row for row in mt.rows}
    skill = {int(row['id']): row for row in st.rows}
    plans = [plan_rank(tables, sid, review, magic, skill) for sid in source_ids]
    specs = newclasses.load_specs(mod)
    char_patch = mod.load_patch('db', 'char.dat.json') or {}
    patched = list(char_patch.get('added', [])) + list(char_patch.get('rows', {}).values())
    targets = sorted({int(row['id']) for row in patched if 'id' in row})
    if generic:
        if len(specs) != 1:
            raise ValueError('DD2 family requires one class descriptor')
        owner = int(specs[0]['family'])
        target_ids = list(range(owner, owner + 6))
    else:
        if len(targets) != 1:
            raise ValueError('DD2 unique requires exactly one patched character row')
        owner = targets[0]
        target_ids = [owner]
    lease = _load(LEASES)['evilities']
    selected = {}
    for plan in plans:
        for item in plan['evilities']:
            sid = item['source_id']
            if str(sid) not in lease:
                raise ValueError(f'No recorded reviewed-ability lease for DD2 evility {sid}')
            item['target_id'] = int(lease[str(sid)])
            selected.setdefault(sid, item)
    occupied = {int(row['id']): ['vanilla'] for row in st.rows}
    # SOURCEPREP4-DD2: the canonical claims are a checked-in data file, so a machine with no installed
    # packs (INSTALLED_MODS empty) still refuses a lease another pack already owns.  A supplied
    # installed root is an extra scan when one exists; it is no longer required.
    # DD2FIELDS1: a claim this very pack owns is not a collision (a rebuild of an installed pack re-requests its own lease)
    occupied.update({k: v for k, v in sources.claimed_ids().items() if v != [root.name]})
    installed = ctx.get('installed_root') if ctx.get('installed_reference', True) else None
    if installed is not None and Path(installed).is_dir():
        occupied.update(_claims(installed, skip=root.name))
    existing = mod.load_patch('db', 'Skill.dat.json') or {}
    own_ids = {int(row['id']) for row in existing.get('added', [])}
    # The selected IDs must be new, also relative to the baseline pack itself.
    for item in selected.values():
        tid = item['target_id']
        if tid in occupied or tid in own_ids:
            raise ValueError(f'Reviewed DD2 evility lease {tid} is occupied: {occupied.get(tid, [root.name])}')
        _check_donor(st, item['donor_id'], item['donor_name'], 'evility')
    for plan in plans:
        for item in plan['skills']:
            _check_donor(mt, item['target_id'], item['target_name'], 'skill')
    aliases = mod.load_patch('evilities', 'aliases.json') or {}
    common_order = 0
    for item in selected.values():
        signature = bool(item['signature'])
        if generic and not signature:
            common_order += 1
        order = 6 if generic and signature else common_order if generic else 0
        # Keep the donor text/magnitude for both exact and adapted review rows.
        # The receipt carries the source spelling and the relationship label.
        newclasses.add_evility(fs, mod, item['target_id'], item['donor_id'],
            item['donor_name'], None, owner=owner, order=order,
            kind=1 if signature or not generic else 0,
            source=4 if signature or not generic else 3,
            **({'slot_cost': 0, 'shop_rank': 0} if signature or not generic else {}))
        aliases[str(item['target_id'])] = item['donor_id']
    if selected:
        mod.save_patch('evilities', 'aliases.json', aliases)
    vanilla, edited = newclasses._tables(fs, mod, newclasses.CHAR)
    byid = {int(row['id']): row for row in edited.rows}
    for target, plan in zip(target_ids, plans, strict=True):
        if target not in byid:
            raise ValueError(f'DD2 target character {target} missing')
        row = byid[target]
        before_skills = {int(row[f'learn{n}_skill']) for n in range(1, 17)} - {0}
        before_evilities = {int(row[f'evility{n}']) for n in range(1, 5)} - {0}
        # Preserve baseline learned skills while adding the review's accepted rows.
        learn = dict(plan['learn'])
        for n in range(1, 17):
            sid, level = int(row[f'learn{n}_skill']), int(row[f'learn{n}_level'])
            if sid:
                learn[sid] = min(learn.get(sid, level), level)
        nativeimports._apply_learn(row, list(learn.items()))
        innate = [item['target_id'] for item in plan['evilities']
                  if not generic or item['signature']]
        # New reviewed signatures go first; baseline unrelated innates survive.
        innate += [int(row[f'evility{n}']) for n in range(1, 5)
                   if row[f'evility{n}'] and int(row[f'evility{n}']) not in innate]
        nativeimports._apply_innate(row, innate)
        plan.update(target_id=target, learned_target_ids=list(learn),
                    added_skill_target_ids=sorted(set(learn) - before_skills),
                    retained_baseline_skill_target_ids=sorted(before_skills),
                    source_skill_target_ids=list(dict.fromkeys(item['target_id'] for item in plan['skills'])),
                    innate_target_ids=innate,
                    added_innate_target_ids=[sid for sid in innate if sid not in before_evilities])
    newclasses._save(mod, newclasses.CHAR, vanilla, edited)
    receipt = dict(schema='coredd2-reviewed-abilities/1', source_path=str(source_path),
                   source_sha256=digest, review_path=str(review_path), review_sha256=_hash(review_path),
                   engine_emission_path=str(emission_path), engine_emission_sha256=_hash(emission_path),
                   engine_extension_rows=0, engine='native D5 aliases; reviewed extension_rows is empty',
                   owner=owner, ranks=plans, native_tested=False,
                   added_evility_ids=[item['target_id'] for item in selected.values()])
    unresolved = [item for plan in plans for item in plan['omitted']
                  if item['kind'] == 'skill' and item['relation'] == 'unresolved']
    # This is a content check only. Parent combines it with art/face/text/gates;
    # it must never be counted as installed or native acceptance.
    receipt.update(source_skills_added=len({item['source_id'] for plan in plans for item in plan['skills']}),
                   native_skill_targets_added=len({sid for plan in plans for sid in plan['added_skill_target_ids']}),
                   source_evilities_added=len(selected),
                   signatures_supported=all(plan['signature_supported'] for plan in plans),
                   offline_skills_ready=not unresolved and all(
                       bool(plan['skills'] or plan['weapon_mastery_source_ids']) for plan in plans),
                   unresolved_skill_ids=sorted({item['source_id'] for item in unresolved}),
                   actual_installed_usable_count_changed=False,
                   features={'skills': 'adapted' if any(p['skills'] for p in plans) else
                             'donor' if any(p['weapon_mastery_source_ids'] for p in plans) else 'missing',
                             'evilities': 'adapted' if selected else 'missing'})
    mod.meta['coredd2_reviewed_abilities'] = receipt
    mod.save_meta()
    (root / 'COREDD2-ABILITIES.json').write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + '\n')
    return receipt
