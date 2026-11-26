"""Local selection/staging and strict offline integration of accepted D4 imports.

No extraction, installer, save operation, live settings mutation, or native rules.
Finalizations run in a fresh process through tools/build_d4_expansion.py.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import classcheck, database, dbpatch, gamepacks, modclaims, modsys, offlinepaths, slots
from .d4unique import Originals

POSITIONAL_MEMBERS = modclaims.POSITIONAL_MEMBERS

ENTRIES = {'armor-knight': 'd4:pc-en-armor-knight-1080-pilot', 'valvatorez': 'd4:pc-en-valvatorez-10'}
DB = 'Database/Database_0.dat/'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def required_kit_source():
    """Pin the source-backed Kit required before any future installation."""
    import inspect
    from . import newclasses
    required = ('validate_specs', 'sprite_family', 'class_kind', 'flag_of')
    if any(not callable(getattr(newclasses, key, None)) for key in required) or \
            'sprite_family' not in inspect.signature(newclasses.fill_class).parameters or \
            'specs' not in inspect.signature(newclasses.flag_of).parameters:
        raise ValueError('Registry package requires the updated Kit identity/physical-lease API; legacy installed code is unsupported')
    root = Path(__file__).resolve().parents[1]
    files = sorted(p for p in (root / 'd5lib').rglob('*') if p.is_file() and p.suffix in ('.py','.c','.h','.asm','.zig'))
    return dict(schema=1, files={str(p.relative_to(root)): sha(p.read_bytes()) for p in files},
        required_api=list(required) + ['fill_class(sprite_family=...)', 'flag_of(cls,specs=...)'],
        installation='Owner approval required. Verify these source fingerprints and registry API before the canonical Installer runs. Use the existing canonical mods/state/profiles; do not create a second installer owner or game clone.',
        deployment='Offline build only; an older installed release is not upgraded by this package')


def snapshot(mod):
    return {str(p.relative_to(mod.folder)): dict(bytes=p.stat().st_size, sha256=sha(p.read_bytes()))
            for p in gamepacks._native_tree(Path(mod.folder))}


def read_current(kit):
    """Read exact active profile without constructing a live ModManager/Profiles."""
    kit = Path(kit).resolve(strict=True)
    settings_path = kit / 'settings.json'
    raw = settings_path.read_bytes()
    settings = json.loads(raw)
    pid = settings.get('profile', 'Default')
    if not isinstance(pid, str) or Path(pid).name != pid:
        raise ValueError('Unsafe active profile identity')
    path = kit / 'profiles' / pid / 'load_order.json'
    order_raw = path.read_bytes()
    order = json.loads(order_raw)
    if not isinstance(order, list) or len(order) != len(set(order)) or any(not isinstance(v, str) or Path(v).name != v for v in order):
        raise ValueError('Invalid exact current load order')
    mods = [modsys.Mod(str(kit / 'mods' / mid)) for mid in order]
    if any(not (Path(m.folder) / 'mod.json').is_file() for m in mods):
        raise ValueError('Current profile refers to missing mod')
    return mods, dict(profile=pid, order=order,
        files={str(settings_path): sha(raw), str(path): sha(order_raw)})


def read_pilot(root):
    root = Path(root).resolve(strict=True)
    final = json.loads((root / 'finalization.json').read_text())
    if final.get('status') != 'built-offline' or final.get('skipped_features') or not final.get('files'):
        raise ValueError('Pilot lacks successful strict offline finalization: ' + str(root))
    for item in final['files']:
        path = root / 'finalized-logical' / item['path']
        if path.stat().st_size != item['bytes'] or sha(path.read_bytes()) != item['sha256']:
            raise ValueError('Pilot finalized output changed: ' + str(path))
    catalogue = json.loads((root / 'catalogue.json').read_text())
    if len(catalogue['entries']) != 1:
        raise ValueError('Expected one independently built pilot entry')
    entry = catalogue['entries'][0]
    mid = entry['artifact']['mod_id']
    mod = modsys.Mod(str(root / 'native-mods' / mid))
    gamepacks.validate_catalogue(catalogue, artifacts={mid: mod})
    if (root / 'native-files.json').is_file():
        expected = json.loads((root / 'native-files.json').read_text())
    elif (root / 'pilot-receipt.json').is_file():
        receipt = json.loads((root / 'pilot-receipt.json').read_text())
        expected = {x['path']: dict(bytes=x['bytes'], sha256=x['sha256']) for x in receipt['files']}
    else:
        raise ValueError('Pilot has no prior native source hash receipt')
    if snapshot(mod) != expected:
        raise ValueError('Pilot native source differs from its prior receipt: ' + str(root))
    mod._source_fingerprint = expected
    if not final.get('finalizer_order'):
        raise ValueError('Pilot has no accepted finalizer-order receipt')
    mod._finalizer_order = final['finalizer_order']
    return deepcopy(entry), mod


def _claim_rows(fs, mod, originals):
    claims = {}
    pdir = Path(mod.patches_dir) / 'db'
    for path in sorted(pdir.glob('*.json')):
        name = path.name[:-5]
        # Only schema DB patches are accepted by the native database handler.
        if name not in originals:
            originals[name] = fs.read(DB + name)
        original = database.load_table(name, originals[name])
        edited = database.load_table(name, originals[name])
        patch = json.loads(path.read_text())
        placed = []
        dbpatch.apply_patch(edited, patch, strict=True, placed=placed)
        # Source help tables contain repeated IDs with different flag routes.
        # Only explicitly edited/placed rows are claims; an ID->last-row diff
        # would spuriously claim untouched duplicate rows in every mod.
        indices = {int(i) for i in patch.get('rows', {})} | set(placed)
        edited_indices = {int(i) for i in patch.get('rows', {})}
        for index in sorted(indices):
            row = edited.rows[index]
            if 'id' in row:
                # An index-keyed edit of a row whose id repeats cannot be claimed by id at all:
                # it could name either row, so it stays an error for every member.
                #
                # A row the patch *appends* is different.  Members the game reads by position have
                # no id key -- the vanilla table repeats ids (charPersonal 129-131) and a pack may
                # append the same id on purpose (the Overlord charPersonal member converted by
                # OLCOMPAT2 is `3, 4, 5, 3, 4, 5`), so such an append is information: its claims
                # collapse to one key.  A second PACK claiming the same id is still an allocation
                # conflict in `preflight`, and positional drift is guarded by
                # `d5lib.ordercheck.positional_errors`.
                if sum(r['id'] == row['id'] for r in edited.rows) != 1:
                    positional_append = index not in edited_indices and name in POSITIONAL_MEMBERS
                    if not positional_append:
                        raise ValueError(f'Ambiguous explicitly patched duplicate {name} ID {row["id"]}; use a route-aware handler')
                claims[f'db:{name}:{row["id"]}'] = row
    return claims


def reservations(fs, mod, originals):
    """Actual patched IDs plus derived graphics, quest slots and kit unlock flags."""
    from . import newclasses
    rows = _claim_rows(fs, mod, originals)
    claims = set(rows)
    details = {}
    for key, row in rows.items():
        if key.startswith('db:Quest.dat:'):
            claims.add(f'quest-progress:{row["sort_order"]}')
        elif key.startswith('db:char.dat:'):
            cid = row['id']
            if cid < 1000:
                for n in (cid, cid + 1, cid + 2, cid + 10000, cid + 10001):
                    claims.add(f'anm:{n}')
                claims.add(f'color:{cid}')
    for vp in mod.list_files():
        claims.add('file:' + vp.lower())
        if vp.lower().startswith(DB.lower()):
            claims.add('raw-db:' + vp.rsplit('/', 1)[-1].lower())
        name = Path(vp).name.lower()
        if name.startswith('anm') and name[3:8].isdigit():
            claims.add('anm:' + str(int(name[3:8])))
    for spec in newclasses.load_specs(mod):
        family = int(spec['family'])
        physical = newclasses.sprite_family(family, spec)
        flags = [newclasses.flag_of(family + k, {family: spec}) for k in range(6)]
        for flag in flags:
            claims.add(f'unlock-flag:{flag}')
        claims.add(f'sprite-lease:{physical}')
        for n in (physical, physical + 1, physical + 2, *range(physical + 10000, physical + 10010)):
            claims.add(f'anm:{n}')
        for n in range(physical, physical + 10):
            claims.add(f'color:{n}')
        details[str(family)] = dict(unlock_flags=flags, unlocked_ranks=spec.get('unlocked_ranks', 1),
                                     aliases=spec.get('evility_alias', {}), template=spec['template'])
        for key in spec.get('evility_alias', {}):
            claims.add('evility-alias:' + str(int(key)))
    from . import skills
    claims.update('events:' + str(eid) for eid in skills.event_ids(mod))
    skill = mod.load_patch('skills', 'skills.json') or {}
    for key in skill.get('effects', {}):
        claims.add('effects:' + str(int(key)))
    for vid in (mod.load_patch('voices', 'voices.json') or {}).get('voices', {}):
        claims.add('voice:' + str(int(vid)))
    for eid in (mod.load_patch('evilities', 'aliases.json') or {}):
        claims.add('evility-alias:' + str(int(eid)))
    return claims, details


def preflight(fs, selected, others):
    """Reject new collisions; existing baseline overlaps are preserved separately."""
    originals, reserved, detail = {}, {}, {}
    selected_ids = {m.id for m in selected}
    if len(selected_ids) != len(selected):
        raise ValueError('Duplicate selected mod identity')
    # An installed pilot with the same mod ID is an explicit replacement candidate.
    others = [m for m in others if m.id not in selected_ids]
    seen = set()
    for mod in [*others, *selected]:
        resolved = str(Path(mod.folder).resolve())
        if resolved in seen:                 # one folder, one claim set: a duplicate path is the same mod
            continue
        seen.add(resolved)
        keys, specs = reservations(fs, mod, originals)
        detail[resolved] = dict(mod_id=mod.id, reservations=sorted(keys), classes=specs)
        for key in keys:
            reserved.setdefault(key, []).append(mod)
    conflicts = []
    for key, owners in reserved.items():
        if len(owners) > 1 and any(m.id in selected_ids for m in owners):
            conflicts.append(dict(resource=key, mods=[m.id for m in owners]))
    for key, raw_owners in reserved.items():
        if key.startswith('raw-db:'):
            name = key[len('raw-db:'):]
            structured = [m for k, owners in reserved.items() if k.lower().startswith('db:' + name + ':') for m in owners]
        elif key == 'file:script/script.dat':
            structured = [m for k, owners in reserved.items() if k.startswith('events:') for m in owners]
        else:
            continue
        pairs = {(a.id, b.id) for a in raw_owners for b in structured if a.id != b.id and
                 (a.id in selected_ids or b.id in selected_ids)}
        if pairs:
            conflicts.append(dict(resource=key, reason='raw-carrier-overlaps-structured-patches', mods=sorted({m for pair in pairs for m in pair})))
    for mod in selected:
        pdir = Path(mod.patches_dir)
        unknown = [p.name for p in pdir.iterdir() if p.is_dir() and any(p.iterdir()) and p.name not in modsys.PATCH_HANDLERS]
        if unknown:
            raise ValueError('Selected nonempty patch directories have no registered handler: ' + repr(unknown))
    if conflicts:
        raise ValueError('Expansion allocation conflicts: ' + json.dumps(conflicts, sort_keys=True))
    # Class/unique identity rules (d5lib.classcheck): the same gate for every importer, so a pack
    # cannot ship without the rows the Recruiter needs, with a quest reward pointing at another
    # character, or on a char.dat row another pack already owns.
    vanilla_ids, _personal = classcheck.vanilla_rows(fs)
    vanilla_help = classcheck.vanilla_help_ids(fs)
    foreign = classcheck.foreign_rows(others, vanilla_ids)
    identity = []
    for mod in selected:
        found = classcheck.errors(classcheck.check(mod.folder, vanilla_char_ids=vanilla_ids,
                                                   foreign=foreign, dummy_rows=slots.DUMMY_ROWS,
                                                   owner=mod.id, vanilla_help_ids=vanilla_help))
        if found:
            identity.append(dict(mod_id=mod.id, findings=found))
    if identity:
        raise ValueError('Class identity rules failed: ' + json.dumps(identity, sort_keys=True))
    return dict(status='passed', selected_mods=sorted(selected_ids), reservations=detail, conflicts=[],
                baseline_overlaps=[dict(resource=k, mods=[m.id for m in v]) for k, v in reserved.items() if len(v) > 1],
                scope='Fixed table IDs, resources, derived graphics, unlock flags, quest slots and literal custom event/effect IDs; no runtime capacity claim')


def verify_selected(fs, mods, ctx):
    """Check actual finalized table values and references, not row-count/ID width."""
    originals, checks = {}, []
    required = ('char.dat', 'magic.dat', 'Skill.dat', 'Quest.dat')
    tables = {name: database.load_table(name, ctx.get(DB + name)) for name in required}
    rows = {name: {r['id']: r for r in table.rows} for name, table in tables.items()}
    selected_char_ids = set()
    for mod in mods:
        changed = _claim_rows(fs, mod, originals)
        for key, expected in changed.items():
            _, name, sid = key.split(':', 2)
            if name == 'char.dat':
                selected_char_ids.add(int(sid))
            if name not in rows:
                table = database.load_table(name, ctx.get(DB + name))
                rows[name] = {r['id']: r for r in table.rows}
            actual_table = database.load_table(name, ctx.get(DB + name))
            if sum(r['id'] == int(sid) for r in actual_table.rows) != 1:
                raise ValueError('Ambiguous finalized selected row occurrences: ' + key)
            actual = rows[name].get(int(sid))
            if actual is None:
                raise ValueError('Finalized selected row absent: ' + key)
            for field in expected.keys():
                value = expected[field]
                if name == 'char.dat' and expected['id'] < 1000 and field == 'color_id':
                    value = expected['id']
                if actual[field] != value:
                    raise ValueError(f'Finalized selected mismatch {key}.{field}')
            checks.append(dict(mod=mod.id, table=name, id=int(sid), status='exact-patch-readback'))
    for row in tables['char.dat'].rows:
        if row['id'] not in selected_char_ids:
            continue
        for k in range(1, row['learn_count'] + 1):
            if row[f'learn{k}_skill'] not in rows['magic.dat']:
                raise ValueError('Finalized learned skill dependency missing')
        for k in range(1, row['evility_count'] + 1):
            if row[f'evility{k}'] not in rows['Skill.dat']:
                raise ValueError('Finalized innate Evility dependency missing')
    return checks


def finalize(config):
    """Fresh-process worker entry point; load canonical handlers before calling."""
    protected = (Path(__file__).parents[1], config['game_path'], config['original_state'], *config['mods'])
    offlinepaths.offline_output(config['output'], protected)
    offlinepaths.offline_output(config['cache'], protected)
    offlinepaths.separate_outputs(config['output'], config['cache'])
    from . import gamefs, runtime, sprites
    runtime.CACHE = str(Path(config['cache']).resolve())
    sprites.CACHE_DIR = runtime.CACHE
    originals = Originals(config['original_state'])
    fs = gamefs.GameFS(config['game_path'], backup_resolver=originals)
    mods = [modsys.Mod(p) for p in config['mods']]
    selected = [m for m in mods if m.id in config['selected_mods']]
    output = Path(config['output'])
    output.mkdir()
    logs = []
    try:
        observed_order = [fn.__module__ + '.' + fn.__name__ for fn in modsys.ordered_finalizers()]
        if observed_order != config['expected_finalizer_order']:
            raise ValueError('Cold finalizer order differs from accepted pilot order')
        missing = modsys.missing_requirements(mods)
        # D4-NPC1: a `requires` that only names the pack owning a character's shared art is a load-order
        # dependency, not data this build reads (the pack writes no art; unique.json says shares_art_with).
        # The installer still enforces it through mod.json; the offline finalizer would otherwise need the
        # owner's own patch set in this build's context.
        def _shared_only(mod_id, req):
            for p in config['mods']:
                if modsys.Mod(p).id != mod_id:
                    continue
                decl = Path(p) / 'patches' / 'characters' / 'unique.json'
                if not decl.is_file():
                    return False
                doc = json.loads(decl.read_text(encoding='utf-8-sig'))
                return any(d.get('shares_art_with') == req
                           for d in (doc.get('uniques') or [doc]) if isinstance(d, dict))
            return False
        missing = [(m, r) for m, r in missing if not _shared_only(m.id, r)]
        if missing:
            raise ValueError('Unresolved native dependencies: ' + repr([(m.id, r) for m, r in missing]))
        def log(message):
            logs.append(message)
            print(message, flush=True)
        ctx = modsys.build(fs, mods, log=log)
        if getattr(ctx, 'skipped_features', []):
            raise ValueError('Native finalization skipped required features: ' + repr(ctx.skipped_features))
        checks = verify_selected(fs, selected, ctx)
        inventory = []
        for _, (vp, content) in sorted(ctx.outputs.items()):
            rel = Path(vp)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('Unsafe output virtual path')
            path = output / 'logical' / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            digest = sha(path.read_bytes())
            if digest != sha(content):
                raise ValueError('Offline finalization disk readback failed')
            inventory.append(dict(path=vp, bytes=len(content), sha256=digest))
        originals.verify()
        receipt = dict(status='built-offline', native_tested=False, mod_ids=[m.id for m in mods],
            finalizer_order=[fn.__module__ + '.' + fn.__name__ for fn in modsys.ordered_finalizers()],
            skipped_features=[], files=inventory, selected_readback=checks,
            originals=originals.reads, logs=logs)
        write(output / 'finalization.json', receipt)
        return receipt
    finally:
        fs.reset()


def coverage(*, inventory_path, generic_build, unique_build, output, entries, effect_verification=None):
    """Sparse hash-bound ledger; immutable baseline supplies every unmodified item."""
    from . import d4inventory, d4source, lzs
    path = Path(inventory_path).resolve(strict=True)
    inventory_raw = path.read_bytes()
    data = json.loads(inventory_raw)
    source = d4source.D4Data(data['source_root'], data['language'])
    source_tables = {name: source.db.read(name) for name in ('char.dat', 'magic.dat', 'mskill.dat')}
    items = {(x['kind'], x.get('source_id')): x for x in data['items'] if x['kind'] in ('character', 'skill', 'evility')}
    ledger, bindings = {}, []

    def add(kind, source_id, fidelity, conversion, implementation, evidence, target=None):
        item = items[kind, source_id]
        src = item['source']
        observed = source_tables[src['member']][src['offset']:src['offset'] + src['bytes']]
        if sha(observed) != src['sha256']:
            raise ValueError('Stale inventory source row for coverage: ' + item['uid'])
        ledger[item['uid']] = dict(source_sha256=src['sha256'], fidelity=fidelity,
            status=dict(conversion=conversion, implementation=implementation, gameplay='not-tested', presentation='not-tested'),
            evidence=[str(Path(evidence).resolve())])
        bindings.append(dict(uid=item['uid'], source_sha256=src['sha256'], source_id=source_id,
                             namespace=kind, target=target, fidelity=fidelity))

    if 'armor-knight' in entries:
        receipt_path = Path(generic_build) / 'pilot-receipt.json'
        receipt = json.loads(receipt_path.read_text())
        for k, row in enumerate(receipt['source_ranks']):
            if row['evidence']['row_sha256'] != items['character', row['id']]['source']['sha256']:
                raise ValueError('Generic source receipt / inventory mismatch')
            add('character', row['id'], 'partial', 'partial', 'partial', receipt_path,
                dict(id=receipt['family'] + k, mod='D4_ArmorKnight_1080_PILOT', relation='adapted-static-and-art'))
        for mapping in receipt['d4_plan']['report']:
            blocked = mapping['status'] in ('omitted', 'unmapped')
            target = None if blocked else dict(id=mapping['d5_id'], donor=mapping.get('works_like', mapping.get('copy_of')),
                relation='D5-donor-adaptation', mod='D4_ArmorKnight_1080_PILOT')
            add(mapping['kind'], mapping['d4_id'], 'blocked' if blocked else 'adapted',
                'blocked' if blocked else 'metadata-derived', 'blocked' if blocked else 'adapted', receipt_path, target)
    if 'valvatorez' in entries:
        receipt_path = Path(unique_build) / 'unique-receipt.json'
        receipt = json.loads(receipt_path.read_text())
        if sha(source_tables['char.dat']) != receipt['provenance']['d4_char_sha256']:
            raise ValueError('Unique source table / inventory mismatch')
        add('character', 10, 'partial', 'partial', 'partial', receipt_path,
            dict(id=receipt['target_id'], mod='D4_Valvatorez_Comparison', relation='adapted-comparison'))
        for mapping in receipt['mappings']:
            status = mapping['status']
            target = None if 'target_id' not in mapping else dict(id=mapping['target_id'],
                relation='D5-reuse' if mapping['kind'] == 'skill' else 'comparison-reference-only',
                mod='D4_Valvatorez_Comparison')
            add(mapping['kind'], mapping['source_id'], status,
                'blocked' if status == 'blocked' else 'metadata-derived', status, receipt_path, target)
    if effect_verification:
        ep = Path(effect_verification).resolve(strict=True)
        effects = json.loads(ep.read_text())
        archive = d4source.Nsac(effects['source_archive'])
        archive_rel = str(Path(effects['source_archive']).relative_to(Path(data['source_root'])))
        resources = {(x['source'].get('path'), x['source'].get('member')): x
                     for x in data['items'] if x['kind'] == 'resource'}
        for model in effects['models']:
            item = resources[archive_rel, model['member']]
            stored = archive.read(model['member'])
            if sha(stored) != item['source']['sha256'] or sha(lzs.decompress(stored)) != model['source_sha256']:
                raise ValueError('Effect stored/decoded source hashes do not bind to inventory: ' + model['member'])
            passed = model['conversion'] == 'pixel-exact-offline'
            if passed and sha(Path(model['output']).read_bytes()) != model['output_sha256']:
                raise ValueError('Converted effect changed after verification')
            ledger[item['uid']] = dict(source_sha256=item['source']['sha256'], fidelity='partial' if passed else 'blocked',
                status=dict(conversion='passed' if passed else 'blocked', implementation='not-started',
                            gameplay='not-tested', presentation='not-tested'), evidence=[str(ep)])
            bindings.append(dict(uid=item['uid'], source_sha256=item['source']['sha256'], namespace='effect-conversion',
                target=dict(path=model['output'], sha256=model['output_sha256'], installed=False) if passed else None,
                fidelity='partial' if passed else 'blocked'))
    d4inventory.apply_progress(data, ledger)
    output = Path(output)
    write(output / 'progress-ledger.json', ledger)
    write(output / 'target-bindings.json', bindings)
    write(output / 'coverage.json', dict(schema=1, baseline_inventory=str(path), baseline_sha256=sha(inventory_raw),
        baseline_item_count=len(data['items']), overridden_item_count=len(ledger),
        unchanged_item_count=len(data['items']) - len(ledger), summary=data['summary'],
        inheritance='Every item not in progress-ledger.json retains the immutable baseline status; no native acceptance claimed'))


def coverage_imports(*, inventory_path, builds, output, voice_status_path=None, interpretation_path=None):
    """Merge actual import receipts into all immutable source-item occurrences.

    Unchanged items inherit baseline stages. Target arrays retain every reuse;
    an offline conversion never implies native gameplay or visual acceptance.
    """
    from . import d4inventory
    path = Path(inventory_path).resolve(strict=True)
    raw = path.read_bytes(); data = json.loads(raw)
    by_uid = {x['uid']:x for x in data['items']}
    by_key = {(x['kind'],x.get('source_id')):x for x in data['items'] if 'source_id' in x}
    resources = {(x['source'].get('path'),x['source'].get('member')):x for x in data['items'] if x['kind']=='resource'}
    ledger = {}; targets = []; unresolved = []

    def add(item, evidence, *, conversion='partial', implementation='adapted', target=None, digest=None, reason=None):
        if digest is not None and digest != item['source']['sha256']:
            raise ValueError('Receipt/inventory source hash mismatch: ' + item['uid'])
        record = ledger.setdefault(item['uid'],dict(source_sha256=item['source']['sha256'],fidelity='partial',
            status=dict(conversion=conversion,implementation=implementation,gameplay='not-tested',presentation='not-tested'),evidence=[],targets=[],reasons=[]))
        # A later omitted use must not downgrade another installed adaptation.
        if implementation == 'adapted':
            record['status'].update(conversion=conversion,implementation=implementation)
        ev = str(Path(evidence).resolve())
        if ev not in record['evidence']:record['evidence'].append(ev)
        if target is not None and target not in record['targets']:
            record['targets'].append(target)
            targets.append(dict(uid=item['uid'],source_sha256=item['source']['sha256'],target=target))
        if reason and reason not in record['reasons']:record['reasons'].append(reason)

    interpretation = {}
    if interpretation_path:
        ip = Path(interpretation_path).resolve(strict=True); overlay=json.loads(ip.read_text())
        if overlay['baseline_inventory_sha256'] != sha(raw):raise ValueError('Stale character interpretation baseline')
        for row in overlay['items']:
            if row['source_sha256'] != by_uid[row['uid']]['source']['sha256']:raise ValueError('Stale interpretation row')
            interpretation[row['source_id']] = row
    for alias, root in builds.items():
        root=Path(root); generic=(root/'pilot-receipt.json').is_file()
        rp=root/('pilot-receipt.json' if generic else 'unique-receipt.json'); receipt=json.loads(rp.read_text())
        catalogue=json.loads((root/'catalogue.json').read_text()); mid=catalogue['entries'][0]['artifact']['mod_id']
        rows=receipt['source_ranks'] if generic else [dict(id=receipt['source_id'])]
        for k,row in enumerate(rows):
            item=by_key['character',row['id']]
            digest=row.get('evidence',{}).get('row_sha256')
            add(item,rp,digest=digest,target=dict(mod=mid,id=receipt['family']+k if generic else receipt['target_id'],relation='source-static/art and D5 mechanics adaptation'))
            source_row=item['data']; corrected=interpretation.get(row['id'])
            sprite=corrected['interpretation']['art_sprite'] if corrected else source_row.get('sprite',source_row['body'])
            for member in (f'anm{sprite:05d}.lzs',f'anm{10000+source_row["color_id"]:05d}.lzs'):
                asset=resources.get(('Data/DATA/ANM_HI.dat',member))
                if asset:add(asset,rp,target=dict(mod=mid,source_member=member,relation='prepared source asset; donor motion/palette/portrait routing adaptations'),reason='Source member identity follows sprite(+196), not legacy voice-group body(+1BA); native presentation not tested')
            help_item=by_key.get(('character-help',source_row['help_id']))
            if help_item:add(help_item,rp,target=dict(mod=mid,relation='source text with visible pending-ability notice'))
        for m in receipt['d4_plan']['report'] if generic else receipt['mappings']:
            item=by_key.get((m['kind'],m['d4_id']))
            if item is None:
                unresolved.append(dict(import_alias=alias,source_character_ids=[r['id']for r in rows],reference=m,evidence=str(rp.resolve()),reason='Stored source reference has no matching source-table inventory row; no identity invented'))
                continue
            blocked=m['status'] in ('placeholder','unmapped','omitted','blocked')
            add(item,rp,conversion='metadata-derived' if blocked else 'partial',implementation='blocked' if blocked else 'adapted',
                target=None if blocked else dict(mod=mid,id=m['d5_id'],donor=m.get('works_like',m.get('copy_of')),relation=m['status']),
                reason=m.get('reason') or ('Unavailable learned/effect record omitted; visible help notice required' if blocked else 'D5 implementation/values retained'))
    if voice_status_path:
        vp=Path(voice_status_path).resolve(strict=True); statuses=json.loads(vp.read_text())
        for sid,bank in statuses.items():
            for clip in bank.get('clips',[]):
                uid=clip.get('source_uid')
                if uid is None:continue
                item=by_uid[uid];converted=clip.get('status')=='converted-adapted'
                add(item,vp,digest=clip['source_row_sha256'],conversion='passed' if converted else 'blocked',implementation='adapted' if converted else 'blocked',
                    target=dict(source_character=int(sid),bank=bank.get('bank_path'),output_sha256=clip.get('output_sha256'),destinations=clip.get('destinations'),relation=clip.get('status')),
                    reason='D5 triggers/randomizer and adapted semantic routes; missing/unrouted clips explicit')
    body_receipts=Path(output)/'staged-body-overlays.json'
    if body_receipts.is_file():
        for change in json.loads(body_receipts.read_text()):
            item=by_key['character',change['source_id']]
            sprite=item['data'].get('sprite',item['data']['body'])
            asset=resources.get(('Data/DATA/ANM_HI.dat',f'anm{sprite:05d}.lzs'))
            evidence=Path(change['overlay'])/'pilot-receipt.json'
            if asset:add(asset,evidence,target=dict(mod=change['mod'],relation='source-frame fallback body successor',files=change['body_changes']))
    if voice_status_path:
        for sid,bank in statuses.items():
            if not bank.get('clips') and ('character',int(sid)) in by_key:
                add(by_key['character',int(sid)],vp,target=dict(voice_id=bank['voice_id'],relation=bank['status']),reason=bank.get('reason'))
            for extra in bank.get('extra_personality_accounting',[]):
                for clip in extra.get('clips',[]):
                    add(by_uid[clip['uid']],vp,conversion='blocked',implementation='blocked',reason=extra['reason'],
                        target=dict(source_character=int(sid),excluded_variant=extra['variant'],relation='explicitly-excluded-personality'))
    d4inventory.apply_progress(data,ledger)
    output=Path(output)
    write(output/'progress-ledger.json',ledger);write(output/'target-bindings.json',targets)
    write(output/'unresolved-import-references.json',unresolved)
    write(output/'coverage.json',dict(schema=2,status='merged-offline-partial',baseline_inventory=str(path),baseline_sha256=sha(raw),
        baseline_item_count=len(data['items']),overridden_item_count=len(ledger),unchanged_item_count=len(data['items'])-len(ledger),summary=data['summary'],
        voice_status=str(voice_status_path) if voice_status_path else None,character_interpretation=str(interpretation_path) if interpretation_path else None,
        inheritance='Every unoverridden item retains its immutable baseline stages; gameplay and presentation remain not-tested'))


def accepted_imports(builds):
    """Combine any number of independently verified single-entry native imports.

    Keys are caller selection aliases; catalogue identities and dependencies stay
    authoritative. Reusing a native mod identity would silently overwrite an
    artifact, so reject it before selection, caches or staging can be written.
    """
    if not isinstance(builds, dict) or not builds or any(
            not isinstance(k, str) or not k.strip() for k in builds):
        raise ValueError('Supply a nonempty alias -> accepted build mapping')
    rows, artifacts, aliases = [], {}, {}
    for alias, root in builds.items():
        entry, mod = read_pilot(root)
        if mod.id in artifacts:
            raise ValueError('Duplicate accepted native mod identity: ' + mod.id)
        rows.append(entry)
        artifacts[mod.id] = mod
        aliases[alias] = entry['id']
    catalogue = dict(schema=1, id='d4-expansion-local', name='D4 content expansion — partial imports',
                     games=[dict(id='d4', name='Disgaea 4 Complete+')], entries=rows)
    return gamepacks.validate_catalogue(catalogue, artifacts=artifacts), artifacts, aliases


def _update_source_identity(mod):
    source = mod.meta.get('source_import', {})
    return source.get('identity') or {k: source.get(k) for k in ('source_game', 'source_id')}


def _legacy_exact_palette_disclosure(line):
    """The old exact-only report and its current zero-approximation spelling."""
    import re
    if not isinstance(line, str):
        return None
    match = re.fullmatch(
        r'D4 body palettes per colour \(([0-9]+) colour entries mapped exactly\); '
        r'D4 face and cut-in per colour where extracted; D4 class description', line)
    if match is None:
        return None
    return (f'D4 body palettes per colour ({match[1]} exact entries, '
            '0 nearest-source palette approximations); D4 face and cut-in per colour '
            'where extracted; D4 class description')


def _verify_update_identity(mod, owner, *, unique_help=False):
    from . import newclasses
    if _update_source_identity(mod) != owner['source_identity']:
        raise ValueError('D4 update source identity drift: ' + mod.id)
    meta = {k: v for k, v in mod.meta.items() if k != 'gamepack'}
    baseline = deepcopy({k: v for k, v in owner.get('baseline_meta', {}).items() if k != 'gamepack'})
    if 'expected_ability_adaptations' in owner:
        import re
        expected = iter(owner['expected_ability_adaptations'])
        source = baseline.get('source_import', {})
        lines = source.get('adaptations', [])
        # Only complete per-ability disclosure lines may change, in source order.
        def replace(line):
            if not re.match(r'^(skill|evility) .* \(\d+\): ', line):
                return line
            value = next(expected, None)
            if not isinstance(value, str) or line.split('): ', 1)[0] != value.split('): ', 1)[0]:
                raise ValueError('D4 update ability disclosure identity drift')
            return value
        source['adaptations'] = [replace(line) for line in lines]
        if next(expected, None) is not None:
            raise ValueError('Extra D4 update ability disclosure')
    # Compare only a local baseline copy. Old pinned metadata/files remain exact.
    source = baseline.get('source_import', {})
    old_lines = source.get('adaptations')
    new_lines = meta.get('source_import', {}).get('adaptations')
    if isinstance(old_lines, list) and isinstance(new_lines, list) and len(old_lines) == len(new_lines):
        for index, (before, after) in enumerate(zip(old_lines, new_lines)):
            current = _legacy_exact_palette_disclosure(before)
            if current is not None and after == current:
                old_lines[index] = current
    if not baseline or meta != baseline:
        raise ValueError('Unrelated D4 update metadata changed: ' + mod.id)
    quests = mod.load_patch('db', 'Quest.dat.json') or {}
    if quests.get('rows') or quests.get('added', []) != owner.get('quests', []):
        raise ValueError('D4 update recruitment quest identity/metadata drift')
    patch = mod.load_patch('db', 'char.dat.json') or {}
    rows = [*patch.get('added', []), *patch.get('rows', {}).values()]
    expected = {r['id']: r for r in owner['characters']}
    if len(rows) != len(expected) or {r.get('id') for r in rows} != set(expected):
        raise ValueError('D4 update character ownership changed: ' + mod.id)
    for row in rows:
        keys = ('id', 'sprite_id', 'color_id', 'voice_id') if unique_help else tuple(expected[row['id']])
        if any(row.get(k) != expected[row['id']][k] for k in keys):
            raise ValueError('D4 update fixed character/voice/sprite/help lease changed: ' + mod.id)
        binding = owner.get('learning', {}).get(str(row['id']))
        if binding is None:
            raise ValueError('D4 update prior learned ownership missing')
        learned = [(row.get(f'learn{n}_skill'), row.get(f'learn{n}_level'))
                   for n in range(1, row.get('learn_count', 0) + 1)]
        innate = [row.get(f'evility{n}', 0) for n in range(1, 5)]
        if any(tuple(pair) not in learned for pair in binding['skills']) or \
                any(e not in innate for e in binding['innate']):
            raise ValueError('Existing D4 learned/innate lease dropped or renumbered')
    specs = [{k: s.get(k) for k in ('family', 'template', 'kind', 'sprite_family')}
             for s in newclasses.load_specs(mod)]
    if sorted(specs, key=lambda s: s['family']) != sorted(owner['specs'], key=lambda s: s['family']):
        raise ValueError('D4 update physical/spec lease changed: ' + mod.id)


def _restage_update_rows(fs, selected, others, leases, expected_sha256, table_name):
    """Reuse verified ownership only; default first-import allocators stay separate."""
    from .sourceimports import validate_d4_update_leases, d4_lease_digest, verify_d4_previous_mod
    validate_d4_update_leases(leases, expected_sha256)
    selected_ids = {m.id for m in selected}
    if len(selected_ids) != len(selected) or not selected_ids <= leases['owners'].keys():
        raise ValueError('Missing/duplicate D4 update owner')
    seen = set()
    for mod in others:
        if mod.id in seen:
            raise ValueError('Duplicate prior mod identity')
        seen.add(mod.id)
        if mod.id in selected_ids:
            verify_d4_previous_mod(mod, leases, expected_sha256, mod.id)
        # Check actual supplied claims, not only a same-name replacement exemption.
        for name, claims in leases['claims'].items():
            patch = mod.load_patch('db', name + '.json') or {}
            original = None
            for index, row in [(None, r) for r in patch.get('added', [])] + list(patch.get('rows', {}).items()):
                rid = row.get('id')
                if rid is None:
                    if index is None:
                        raise ValueError('Unverifiable added update claim')
                    if original is None:
                        original = database.load_table(name, fs.read(DB + name))
                    rid = original.rows[int(index)]['id']
                if mod.id not in claims.get(str(rid), []):
                    raise ValueError('New/foreign D4 update claim requires fresh preflight')
    if not selected_ids <= seen:
        raise ValueError('Pinned prior replacement missing from supplied mods')
    original = database.load_table(table_name, fs.read(DB + table_name))
    pending, changes, placed_claims = [], [], set()
    for mod in selected:
        owner = leases['owners'][mod.id]
        unique = 'source_id' in mod.meta.get('source_import', {})
        _verify_update_identity(mod, owner, unique_help=unique)
        for kind, name in (('skills', 'magic.dat'), ('evilities', 'Skill.dat')):
            ability_patch = mod.load_patch('db', name + '.json') or {}
            added = ability_patch.get('added', [])
            if ability_patch.get('rows'):
                raise ValueError('D4 update abilities must remain owned added rows')
            ids = [r.get('id') for r in added]
            if len(ids) != len(set(ids)) or not {x['id'] for x in owner[kind].values()} <= set(ids):
                raise ValueError('D4 update duplicate or dropped ability rows')
            for rid in ids:
                claim = (name, rid)
                previous_owners = leases['claims'].get(name, {}).get(str(rid), [])
                if claim in placed_claims or (previous_owners and previous_owners != [mod.id]):
                    raise ValueError('D4 update ability ID collision')
                base = database.load_table(name, fs.read(DB + name))
                if any(r['id'] == rid for r in base.rows):
                    raise ValueError('D4 update ability overlaps original row')
                placed_claims.add(claim)
            if kind == 'evilities' and any(r.get('owner') != owner['family'] or r.get('source') != 4 for r in added):
                raise ValueError('D4 update Evility owner/source drift')
        aliases = dict(mod.load_patch('evilities', 'aliases.json') or {})
        from . import newclasses
        for spec in newclasses.load_specs(mod):
            aliases.update(spec.get('evility_alias', {}))
        if any(aliases.get(str(e['id'])) != e['donor'] for e in owner['evilities'].values()):
            raise ValueError('D4 update Evility alias drift')
        key = 'personality' if table_name == 'charPersonal.dat' else 'help'
        # Generic help is fixed by its character/spec identity and not re-leased.
        if key == 'help' and not unique:
            current = mod.load_patch('db', table_name + '.json') or {}
            actual = current.get('added', [])
            if current.get('rows') or len(actual) != len(owner[key]) or any(
                    set(a) != set(b) or any(a[k] != b[k] for k in a if not k.startswith('line'))
                    for a, b in zip(actual, owner[key])):
                raise ValueError('Generic help metadata/lease drift')
            continue
        patch = deepcopy(mod.load_patch('db', table_name + '.json') or {})
        rows = patch.get('added', [])
        if patch.get('rows') or len(rows) != len(owner[key]):
            raise ValueError('Existing D4 staged rows dropped/changed')
        if not rows:
            continue
        expected = {(r['voice_group'], r['variant']): r for r in owner[key]} if key == 'personality' else {0: owner[key][0]}
        if len(expected) != len(rows) or (key == 'help' and len(rows) != 1):
            raise ValueError('Ambiguous prior D4 row ownership')
        before = d4_lease_digest(patch)
        ids = []
        char_patch = deepcopy(mod.load_patch('db', 'char.dat.json'))
        chars = [*char_patch.get('added', []), *char_patch.get('rows', {}).values()]
        used_keys = set()
        for row in rows:
            identity = (row.get('voice_group'), row.get('variant')) if key == 'personality' else 0
            if identity not in expected or identity in used_keys:
                raise ValueError('D4 personality group/variant drift')
            used_keys.add(identity)
            old = expected[identity]
            if leases['claims'].get(table_name, {}).get(str(old['id'])) != [mod.id]:
                raise ValueError('Foreign prior D4 staged row lease')
            if any(r['id'] == old['id'] for r in original.rows):
                raise ValueError('D4 staged lease overlaps original row')
            allowed = {'id'} if key == 'personality' else {'id', 'char_id'} | {k for k in old if k.startswith('line')}
            if set(row) != set(old) or any(row[k] != old[k] for k in row if k not in allowed):
                raise ValueError('Unrelated D4 staged source metadata changed')
            previous_id = row['id']
            if key == 'help':
                if len(chars) != 1 or row['char_id'] != previous_id or chars[0]['help_id'] != previous_id or \
                        owner['characters'][0]['help_id'] != old['id'] or old['char_id'] != old['id']:
                    raise ValueError('D4 help linkage/ownership drift')
                row['char_id'] = old['id']
                chars[0]['help_id'] = old['id']
            row['id'] = old['id']
            probe = original.new_row()
            for field, value in row.items():
                probe.set(field, value)
            native = database.load_table(table_name, fs.read(DB + table_name))
            native.rows.append(probe)
            decoded = database.load_table(table_name, native.to_bytes()).rows[-1]
            if any(decoded[k] != v for k, v in row.items()):
                raise ValueError('D4 leased native row serialization drift')
            ids.append(dict(old_id=previous_id, id=old['id']))
        pending.append((mod, patch, char_patch if key == 'help' else None))
        changes.append(dict(mod_id=mod.id, rows=ids, input_patch_sha256=before,
                            output_patch_sha256=d4_lease_digest(patch), preserved=True))
    # Validate all owners/metadata before writing any disposable staged patch.
    for mod, patch, char_patch in pending:
        mod.save_patch('db', table_name + '.json', patch)
        if char_patch is not None:
            mod.save_patch('db', 'char.dat.json', char_patch)
    return dict(contract='Explicit pinned prior ownership; existing leases preserved', changes=changes)


def lease_personality_rows(fs, selected, others, *, previous_leases=None, previous_leases_sha256=None):
    """Lease copied registry-import rows with the Kit's max(id)+1 contract.

    `selected` must be disposable staged copies. Native personality selection
    keeps its existing voice_group/variant/name data; only added row identities
    are leased against the original table and every supplied native mod,
    including disabled ones. Original inputs are never mutated.
    """
    if previous_leases is not None or previous_leases_sha256 is not None:
        return _restage_update_rows(fs, selected, others, previous_leases,
                                    previous_leases_sha256, 'charPersonal.dat')
    from . import newclasses
    name = 'charPersonal.dat'
    original = database.load_table(name, fs.read(DB + name))
    used = {int(r['id']) for r in original.rows}
    for mod in others:
        edited = database.load_table(name, fs.read(DB + name))
        patch = mod.load_patch('db', name + '.json')
        if patch:
            dbpatch.apply_patch(edited, patch, strict=True)
            used.update(int(r['id']) for r in edited.rows)
    # Include any selected non-registry edits unchanged, rather than treating
    # their allocation as available merely because they are not enabled yet.
    registry = {}
    for mod in selected:
        families = {int(s['family']) for s in newclasses.load_specs(mod) if int(s['family']) >= 10000}
        patch = mod.load_patch('db', name + '.json')
        if families and patch:
            if patch.get('rows'):
                raise ValueError('Registry personality staging only supports added rows')
            registry[mod.id] = families, patch
        elif patch:
            edited = database.load_table(name, fs.read(DB + name))
            dbpatch.apply_patch(edited, patch, strict=True)
            used.update(int(r['id']) for r in edited.rows)
    next_id = max(used | {-1}) + 1
    changes = []
    for mod in selected:
        if mod.id not in registry:
            continue
        families, patch = registry[mod.id]
        before = sha(json.dumps(patch, sort_keys=True).encode())
        rows = patch.get('added', [])
        groups = {family // 10 for family in families}
        if len(rows) != 3 * len(families) or {r.get('voice_group') for r in rows} != groups:
            raise ValueError('Registry import personality rows do not match selected source families')
        leased = []
        for row in sorted(rows, key=lambda r: (r['voice_group'], r['variant'])):
            old = row['id']
            row['id'] = next_id
            # Use the actual native writer/readback, not integer-width inference.
            probe = original.new_row()
            for key, value in row.items():
                probe.set(key, value)
            native = database.load_table(name, fs.read(DB + name))
            native.rows.append(probe)
            actual = database.load_table(name, native.to_bytes()).rows[-1]
            if any(actual[k] != value for k, value in row.items()):
                raise ValueError('Native personality row serialization changed staged fields')
            leased.append(dict(old_id=old, id=next_id, voice_group=row['voice_group'], variant=row['variant']))
            used.add(next_id)
            next_id += 1
        mod.save_patch('db', name + '.json', patch)
        changes.append(dict(mod_id=mod.id, rows=leased, input_patch_sha256=before,
                            output_patch_sha256=sha(json.dumps(patch, sort_keys=True).encode())))
    return dict(contract='Kit max(original and all-mod row IDs)+1; groups/variants/names unchanged', changes=changes)


def lease_unique_help_rows(fs, selected, others, *, previous_leases=None, previous_leases_sha256=None):
    """Lease copied unique help IDs after every class/disabled-mod claim."""
    if previous_leases is not None or previous_leases_sha256 is not None:
        return _restage_update_rows(fs, selected, others, previous_leases,
                                    previous_leases_sha256, 'charhelp.dat')
    name='charhelp.dat';raw=fs.read(DB+name);used=set()
    for mod in [None,*others,*selected]:
        table=database.load_table(name,raw)
        patch=mod.load_patch('db',name+'.json') if mod else None
        if patch:dbpatch.apply_patch(table,patch,strict=True)
        used.update(int(r[key]) for r in table.rows for key in ('id','char_id'))
    next_id=max(used|{3999})+1;changes=[]
    for mod in selected:
        if 'source_id' not in mod.meta.get('source_import',{}):continue
        help_patch=mod.load_patch('db',name+'.json');char_patch=mod.load_patch('db','char.dat.json')
        hrows=help_patch.get('added',[]) if help_patch else []
        crows=[*char_patch.get('added',[]),*char_patch.get('rows',{}).values()] if char_patch else []
        if len(hrows)!=1 or help_patch.get('rows') or len(crows)!=1:
            raise ValueError('Unique help leasing expects one added help row and one owned character row')
        help_row,char_row=hrows[0],crows[0];old=help_row['id']
        if help_row['char_id']!=old or char_row['help_id']!=old:
            raise ValueError('Unique help linkage differs before staging')
        help_row['id']=next_id;help_row['char_id']=next_id;char_row['help_id']=next_id
        table=database.load_table(name,raw);dbpatch.apply_patch(table,help_patch,strict=True)
        decoded=database.load_table(name,table.to_bytes()).find(next_id)
        if decoded is None or decoded['char_id']!=next_id:raise ValueError('Native help serialization lost the unique linkage')
        mod.save_patch('db',name+'.json',help_patch);mod.save_patch('db','char.dat.json',char_patch)
        changes.append(dict(mod=mod.id,character_id=char_row['id'],old=old,new=next_id,native_serialized_readback=True))
        next_id+=1
    return dict(policy='Existing Kit max(original + all29mods + selected help id/char_id)+1; copied unique rows only',changes=changes)


def stage_unique_contracts(mods, interpretation_path):
    """Normalize copied unique metadata against pinned source body/MC fields."""
    if not interpretation_path:return []
    from . import newclasses
    rows={int(r['source_id']):r for r in json.loads(Path(interpretation_path).read_text())['items']}
    changes=[]
    for mod in mods:
        sid=mod.meta.get('source_import',{}).get('source_id')
        if sid is None:continue
        source=rows[int(sid)];body=source['stored_fields']['body_type']['value'];mc=source['stored_fields']['magichange']['value']
        patch=mod.load_patch('db','char.dat.json');placed=[*patch.get('added',[]),*patch.get('rows',{}).values()]
        if len(placed)!=1 or placed[0].get('body_type')!=body:
            raise ValueError('Unique source body contract mismatch before staging: '+mod.id)
        row=placed[0];target=row['id']
        if mc==0:
            row['magichange_type']=0;row['magichange_weapon']=0
            mod.save_patch('db','char.dat.json',patch)
        events=mod.load_patch('script','script.json');pruned=[]
        if body==1:
            if not events:raise ValueError('Monster unique lacks ordinary attack events: '+mod.id)
            allowed={str(p+target)for p in newclasses.MONSTER_SCRIPTS}
            if not allowed<=events.get('events',{}).keys():raise ValueError('Monster unique lacks all three attack modes')
            generated={str(p+target+k)for p in newclasses.MONSTER_SCRIPTS for k in range(10)}
            if set(events['events'])-generated:raise ValueError('Unexpected unique attack event namespace')
            # A unique has one row, unlike a ten-colour generic family. Old
            # materializations copied neighbour events that can collide with
            # the next low unique. Keep exactly this unit's three modes.
            pruned=sorted(set(events['events'])-allowed,key=int)
            events['events']={k:v for k,v in events['events'].items()if k in allowed}
            mod.save_patch('script','script.json',events)
        changes.append(dict(mod=mod.id,source_id=int(sid),source_uid=source['uid'],source_sha256=source['source_sha256'],
            body_type=body,source_magichange=mc,magichange='explicitly disabled; source zero' if mc==0 else 'D5 donor weapon/type adaptation',
            attack_events_pruned=pruned,native_gameplay='not-tested'))
    return changes


def stage_body_overlays(mods, overlays):
    """Copy bounded source-body successors into disposable accepted children.

    The original receipt remains frozen; the final combined cold build accepts
    these explicit materialized body changes. No database or arbitrary payload
    from an overlay is copied.
    """
    from . import newclasses
    changes=[];used=set()
    for mod in mods:
        specs=newclasses.load_specs(mod)
        if len(specs)!=1:continue
        identity=mod.meta.get('source_import',{}).get('identity',{})
        sid=str(identity.get('character_id'))
        if sid not in overlays:continue
        root=Path(overlays[sid]).resolve(strict=True)
        receipt=json.loads((root/'pilot-receipt.json').read_text())
        spec=specs[0];physical=int(spec.get('sprite_family',spec['family']))
        if receipt['source_ranks'][0]['id']!=int(sid) or receipt['family']!=spec['family'] or receipt['sprite_family']!=physical:
            raise ValueError('Body overlay source/registry/physical lease mismatch')
        source=modsys.Mod(str(root/'native-mods'/mod.id))
        changed=[]
        for number in (physical,physical+1):
            vp=f'Anime/ANM_HI_JP.dat/anm{number:05d}.lzs'
            if not mod.has_file(vp) or not source.has_file(vp):raise ValueError('Body overlay must replace existing owned sprite pair')
            before=mod.read_file(vp);data=source.read_file(vp)
            mod.write_file(vp,data)
            changed.append(dict(path=vp,before_sha256=sha(before),after_sha256=sha(data)))
        changes.append(dict(mod=mod.id,source_id=int(sid),overlay=str(root),receipt_sha256=sha((root/'pilot-receipt.json').read_bytes()),
            overlay_files=snapshot(source),body_changes=changed,animation=receipt['ownanim'],native_gameplay='not-tested'))
        used.add(sid)
    if set(overlays)-used:raise ValueError('Body overlay has no selected registry import: '+','.join(sorted(set(overlays)-used)))
    return changes


def stage_pending_notices(mods, builds):
    """Disclose omitted abilities in copied in-game help, preserving old inputs."""
    by_mid = {m.id:m for m in mods}
    changes = []
    for root in builds.values():
        root=Path(root)
        cat=json.loads((root/'catalogue.json').read_text())
        mid=cat['entries'][0]['artifact']['mod_id']
        if mid not in by_mid:continue
        rp=root/('pilot-receipt.json' if (root/'pilot-receipt.json').is_file() else 'unique-receipt.json')
        receipt=json.loads(rp.read_text())
        mappings=receipt.get('mappings') or receipt.get('d4_plan',{}).get('report',[])
        pending=[m for m in mappings if m['status'] in ('placeholder','unmapped','omitted','blocked')]
        if not pending:continue
        mod=by_mid[mid];patch=mod.load_patch('db','charhelp.dat.json')
        if not patch:raise ValueError('Pending import lacks in-game help: '+mid)
        rows=[*patch.get('added',[]),*patch.get('rows',{}).values()]
        for row in rows:
            for lang in ('JP','EN','FR','CHN','KOR'):
                row['line3_'+lang]='D4 skills/Evilities pending; see GAPS.'
        mod.save_patch('db','charhelp.dat.json',patch)
        changes.append(dict(mod=mid,pending=pending,help_rows=len(rows),notice='D4 skills/Evilities pending; see GAPS.'))
    return changes


def stage_voice_banks(selected, banks):
    """Overlay completed source voice banks into copied import children only."""
    from . import voices
    changes, consumed = [], set()
    for mod in selected:
        imported = mod.meta.get('source_import', {})
        sid = imported.get('source_id', imported.get('identity', {}).get('character_id'))
        if str(sid) not in banks:
            continue
        root = Path(banks[str(sid)]).resolve(strict=True)
        bank = modsys.Mod(str(root))
        if not (root / 'mod.json').is_file():
            raise ValueError('Voice bank must be a completed native Mod root')
        data = voices.load(bank)
        if len(data['voices']) != 1:
            raise ValueError('One explicit source voice lease per bank required')
        vid = int(next(iter(data['voices'])))
        if not voices.CUSTOM_FIRST <= vid <= voices.CUSTOM_LAST:
            raise ValueError('Source voice bank is outside the Kit custom voice range')
        files = list(gamepacks._native_tree(root))
        if any(p.relative_to(root).parts[:2] != ('patches','voices') for p in files if p.name != 'mod.json'):
            raise ValueError('Voice bank may contain only native voice patches and payloads')
        fingerprint = snapshot(bank)
        for source in files:
            if source.name == 'mod.json':
                continue
            dest = Path(mod.folder) / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        patch = mod.load_patch('db', 'char.dat.json')
        if not patch or not (patch.get('added') or patch.get('rows')):
            raise ValueError('Selected import has no character rows for its source voice')
        for row in [*patch.get('added', []), *patch.get('rows', {}).values()]:
            row['voice_id'] = vid
        mod.save_patch('db', 'char.dat.json', patch)
        changes.append(dict(source_id=sid, mod_id=mod.id, voice_id=vid, bank=str(root), bank_files=fingerprint))
        consumed.add(str(sid))
    if set(banks) != consumed:
        raise ValueError('Voice banks do not match selected source identities: ' + repr(sorted(set(banks)-consumed)))
    return changes


def build(*, game_path, original_state, current_kit, output_path,
          generic_build=None, unique_build=None, builds=None, entries=None, worker_script=None,
          inventory_path=None, effect_verification=None, voice_banks=None,
          voice_status_path=None, interpretation_path=None, body_overlays=None,
          previous_leases=None, previous_leases_sha256=None):
    """Reuse accepted artifacts; publish a new isolated grouped pack and evidence."""
    from . import gamefs
    if previous_leases is not None or previous_leases_sha256 is not None:
        from .sourceimports import validate_d4_update_leases
        validate_d4_update_leases(previous_leases, previous_leases_sha256)
    source_contract = required_kit_source()
    voice_banks = {str(k): v for k,v in (voice_banks or {}).items()}
    body_overlays = {str(k):v for k,v in (body_overlays or {}).items()}
    if builds is not None and (generic_build is not None or unique_build is not None):
        raise ValueError('Use either builds or the legacy generic/unique pair')
    legacy = builds is None
    if legacy and previous_leases is not None:
        raise ValueError('Pinned updates require explicit accepted builds')
    if legacy:
        if generic_build is None or unique_build is None:
            raise ValueError('Supply accepted builds or both legacy pilot paths')
        builds = dict(zip(ENTRIES, (generic_build, unique_build)))
    entries = tuple(builds if entries is None else entries)
    if not entries or len(entries) != len(set(entries)) or set(entries) - builds.keys():
        raise ValueError('Select distinct known import aliases')
    output = Path(os.path.abspath(output_path))
    protected = (*builds.values(), *(str(p) + '.cache' for p in builds.values()),
                 game_path, original_state, current_kit, Path(__file__).parents[1], inventory_path, effect_verification,
                 *voice_banks.values(), *body_overlays.values(), voice_status_path, interpretation_path)
    if output.exists() or not output.parent.is_dir() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('Output must be new under an existing canonical directory')
    offlinepaths.offline_output(output, protected)
    offlinepaths.offline_output(str(output) + '.cache', (*protected, output))
    offlinepaths.separate_outputs(output, str(output) + '.cache')
    catalogue, artifacts, aliases = accepted_imports(builds)
    # Only these historical artifacts inherit the two-pilot disclosure.
    for entry in catalogue['entries']:
        if legacy and entry['category'] == 'humanoid_classes':
            entry['fidelity']['label'] = 'partial'
            entry['fidelity']['missing_mappings'] = ['growth', 'weapon_preferences', 'D4 voice', 'Lift Catch',
                'Aegis native rule', 'class mastery', 'subclass integration', 'native acceptance']
    catalogue = gamepacks.validate_catalogue(catalogue, artifacts=artifacts)
    selection = gamepacks.resolve_selection(catalogue, artifacts=artifacts, entries=[aliases[x] for x in entries])
    selected = [artifacts[mid] for mid in selection.mod_ids]
    current, profile = read_current(current_kit)
    allmods = [modsys.Mod(str(p)) for p in sorted((Path(current_kit).resolve() / 'mods').iterdir())
               if p.is_dir() and (p / 'mod.json').is_file()]
    originals = Originals(original_state)
    before = {str(Path(m.folder).resolve()): snapshot(m) for m in [*allmods, *selected]}
    for mod in selected:
        if before[str(Path(mod.folder).resolve())] != mod._source_fingerprint:
            raise ValueError('Selected pilot changed after prior receipt verification')
    temp = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
    try:
        gamepacks.materialize(catalogue, selection, artifacts=artifacts, staging_path=temp / 'staged-kit')
        staged = {mid: modsys.Mod(str(temp / 'staged-kit/mods' / mid)) for mid in selection.mod_ids}
        unique_contracts = stage_unique_contracts(list(staged.values()), interpretation_path)
        body_changes = stage_body_overlays(list(staged.values()), body_overlays)
        help_notices = stage_pending_notices(list(staged.values()), builds)
        voice_changes = stage_voice_banks(list(staged.values()), voice_banks)
        fs = gamefs.GameFS(str(game_path), backup_resolver=originals)
        try:
            update = dict(previous_leases=previous_leases, previous_leases_sha256=previous_leases_sha256)
            allocation = lease_personality_rows(fs, list(staged.values()), allmods, **update) if not legacy else None
            help_allocation = lease_unique_help_rows(fs, list(staged.values()), allmods, **update) if not legacy else None
            pre = preflight(fs, list(staged.values()), allmods)
        finally:
            fs.reset()
        write(temp / 'staged-allocation.json', allocation)
        write(temp / 'staged-help-allocation.json', help_allocation)
        write(temp / 'required-kit-source.json', source_contract)
        write(temp / 'staged-voices.json', voice_changes)
        write(temp / 'staged-help-notices.json', help_notices)
        write(temp / 'staged-body-overlays.json', body_changes)
        write(temp / 'staged-unique-contracts.json', unique_contracts)
        write(temp / 'staged-input-hashes.json', {mid: snapshot(mod) for mid, mod in staged.items()})
        rollback = temp / 'rollback'
        rollback.mkdir()
        for livepath in profile['files']:
            src = Path(livepath)
            shutil.copyfile(src, rollback / src.name)
        for old in current:
            if old.id in staged:
                dest = rollback / 'mods' / old.id
                dest.mkdir(parents=True)
                for source_path in gamepacks._native_tree(Path(old.folder)):
                    target = dest / source_path.relative_to(old.folder)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_path, target)
        write(rollback / 'README.json', dict(profile=profile['profile'], exact_order=profile['order'],
            replacement_mod_copies=[m.id for m in current if m.id in staged], save_snapshot_included=False,
            requirement='Rollback needs these original mods/order AND a matching pre-transaction Save1 snapshot; vanilla restore alone is insufficient for custom units'))
        # Replace installed children in their exact existing positions; append new children.
        stack = [staged[m.id] if m.id in staged else m for m in current]
        stack += [staged[mid] for mid in selection.mod_ids if mid not in {m.id for m in current}]
        cache = output.parent / (output.name + '.cache')
        cache.mkdir(exist_ok=True)
        cache_sources = []
        selected_roots = [root for alias, root in builds.items() if aliases[alias] in selection.entry_ids]
        for root in selected_roots:
            source_cache = Path(str(root) + '.cache')
            for dll in source_cache.glob('*.dll'):
                dest = cache / dll.name
                if not dest.exists():
                    shutil.copyfile(dll, dest)
                cache_sources.append(dict(name=dll.name, source=str(dll), source_sha256=sha(dll.read_bytes()),
                    selected_sha256=sha(dest.read_bytes()),
                    note='First source/cache retained; independently compiled PE files may differ in linker timestamps'))
        write(temp / 'runtime-cache-sources.json', cache_sources)
        write(temp / 'catalogue.json', catalogue)
        write(temp / 'selection.json', dict(schema=1, entries=list(entries), entry_ids=selection.entry_ids,
            standalone_order=selection.mod_ids, original_profile=profile, combined_order=[m.id for m in stack],
            replacements=[m.id for m in current if m.id in staged], native_tested=False))
        write(temp / 'preflight.json', pre)
        write(temp / 'input-hashes.json', before)
        write(temp / 'transaction-plan.json', dict(schema=1, installed=False, native_tested=False,
            import_builds={alias: str(Path(root).resolve()) for alias, root in builds.items()
                           if aliases[alias] in selection.entry_ids},
            standalone_order=list(selection.mod_ids), proposed_order=[m.id for m in stack],
            restore_order=profile['order'], replacements=[m.id for m in current if m.id in staged],
            appended=[mid for mid in selection.mod_ids if mid not in profile['order']],
            dependency_edges={e['id']: e.get('requires', []) for e in catalogue['entries']
                              if e['id'] in selection.entry_ids},
            controls=profile['files'], rollback='rollback/', saves_included=False,
            approval_required=['canonical installation', 'save operations', 'publication']))
        script = Path(worker_script or Path(__file__).parents[1] / 'tools/build_d4_expansion.py').resolve()
        for mode, mods in (('standalone', list(staged.values())), ('with-current-stack', stack)):
            orders = [mod._finalizer_order for mod in selected]
            if any(order != orders[0] for order in orders):
                raise ValueError('Selected pilots were accepted with different handler orders')
            config = dict(game_path=str(Path(game_path).resolve()), original_state=str(Path(original_state).resolve()),
                          mods=[m.folder for m in mods], selected_mods=list(staged), cache=str(cache), output=str(temp / mode),
                          expected_finalizer_order=orders[0])
            configpath = temp / (mode + '-config.json')
            write(configpath, config)
            result = subprocess.run([sys.executable, str(script), '--finalize-config', str(configpath)],
                                    capture_output=True, text=True)
            (temp / (mode + '.log')).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f'Cold {mode} build failed: ' + (result.stdout + result.stderr)[-6000:])
            receipt = json.loads((temp / mode / 'finalization.json').read_text())
            if receipt['status'] != 'built-offline' or receipt['skipped_features']:
                raise ValueError('Cold finalization did not pass')
        for folder, expected in before.items():
            if snapshot(modsys.Mod(folder)) != expected:
                raise ValueError('Source mod changed during build: ' + folder)
        for change in voice_changes:
            if snapshot(modsys.Mod(change['bank'])) != change['bank_files']:
                raise ValueError('Source voice bank changed during combined build')
        for change in body_changes:
            overlay_mod=modsys.Mod(str(Path(change['overlay'])/'native-mods'/change['mod']))
            if snapshot(overlay_mod)!=change['overlay_files'] or sha((Path(change['overlay'])/'pilot-receipt.json').read_bytes())!=change['receipt_sha256']:
                raise ValueError('Source body overlay changed during combined build')
        for path, digest in profile['files'].items():
            if sha(Path(path).read_bytes()) != digest:
                raise ValueError('Live settings/profile changed during build')
        originals.verify()
        if required_kit_source()['files'] != source_contract['files']:
            raise ValueError('Kit source changed during the combined build; preserve this checkpoint and build a fresh candidate')
        if inventory_path and legacy:
            coverage(inventory_path=inventory_path, generic_build=generic_build, unique_build=unique_build,
                     output=temp, entries=entries, effect_verification=effect_verification)
        elif inventory_path:
            coverage_imports(inventory_path=inventory_path, builds={alias:root for alias,root in builds.items() if alias in entries},
                output=temp, voice_status_path=voice_status_path, interpretation_path=interpretation_path)
        write(temp / 'build-result.json', dict(status='built-offline-partial', native_tested=False,
            output=str(output), staging=str(output / 'staged-kit'),
            standalone_mods=list(selection.mod_ids), current_profile_mod_count=len(current),
            combined_mod_count=len(stack), installed=False))
        # Configs reference private construction paths; preserve runnable published paths.
        for path in temp.glob('*-config.json'):
            cfg = json.loads(path.read_text())
            cfg['mods'] = [p.replace(str(temp), str(output), 1) if p.startswith(str(temp)) else p for p in cfg['mods']]
            cfg['output'] = cfg['output'].replace(str(temp), str(output), 1)
            write(path, cfg)
        os.rename(temp, output)
        return json.loads((output / 'build-result.json').read_text())
    except BaseException:
        # Keep finite failure evidence for review; never publish success after failure.
        write(temp / 'FAILED.json', dict(status='failed', output=str(output), native_tested=False))
        raise
