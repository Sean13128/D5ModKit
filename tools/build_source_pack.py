"""Build one scratch-only D4 prepared-art/static-stat pilot and grouped staging kit.

All asset/game/backup paths and permitted IDs must be supplied explicitly.
No Installer, GUI, native game launch, ID leasing or package publication.
--finalize exercises modsys.build into logical outputs only; never writes game data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared-root', 'library-root', 'source-archive', 'game-path', 'face-path', 'cutin-path', 'output-path'):
        ap.add_argument('--' + name, required=True, type=Path)
    ap.add_argument('--original-state', type=Path, help='Read-only existing backup index/root; not an Installer')
    ap.add_argument('--family', required=True, type=int)
    ap.add_argument('--template', required=True, type=int)
    ap.add_argument('--sprite-family', type=int, help='Separate physical resource/unlock lease for registry class IDs')
    ap.add_argument('--kind', choices=('humanoid', 'monster'))
    ap.add_argument('--approximate-palettes', action='store_true',
                    help='MVP: map composited/quantized colours to nearest source palette entry; receipt discloses count')
    ap.add_argument('--source-frame-fallbacks', action=argparse.BooleanOptionalAction, default=True,
                    help='MVP: unmatched donor body keys use source role/standing frames; preserve attachment/blank keys')
    ap.add_argument('--reserved-ids', type=Path, help='Private cross-import allocation JSON: evilities/skills integer lists')
    ap.add_argument('--source-voice', type=Path, help='Explicit custom voice lease, source groups and adapted event map JSON')
    ap.add_argument('--personality-variants', nargs=3, type=int,
                    help='Explicit D4 variants for the three D5 choices; required when source has extra variants')
    ap.add_argument('--supported-families', required=True, nargs='+', type=int, help='Caller scratch allowlist, NOT global leases')
    ap.add_argument('--source-ids', required=True, nargs=6, type=int)
    ap.add_argument('--edition', required=True)
    ap.add_argument('--finalize', action='store_true')
    ap.add_argument('--d4-root', type=Path, help='D4 install folder: apply the D4 battle profile (d5lib.d4source)')
    ap.add_argument('--exact-emission', type=Path, help='Reviewed D4 exact extension emission JSON')
    ap.add_argument('--exact-mods-root', type=Path, action='append', default=[], help='All current mod roots, including disabled mods; repeat')
    ap.add_argument('--mapping', type=Path, help='Reviewed D4 -> D5 mapping JSON (default d5lib/sourcemaps/d4.json)')
    ap.add_argument('--class-name', default='Male Armor Knight (D4 pilot)')
    ap.add_argument('--mod-id', help='Mod folder id (default D4_ArmorKnight_<id>_PILOT)')
    ap.add_argument('--unlocked-ranks', type=int, default=1, choices=range(1, 7),
                    help='Ranks recruitable / rebirth choices from the start (1-6)')
    ap.add_argument('--engine-exact', type=Path,
                    help='Reviewed D4 evility extension emission (d4_evility extension rows); converts '
                         'whose D4 ID is in the exact set to their own extension row instead of an alias')
    ap.add_argument('--mastery', action='store_true',
                    help='Declare this class family for the class-mastery extension (six families per build with '
                         '.d5cm, unlimited with .d5pm)')
    ap.add_argument('--mastery-mode', choices=('six', 'packed'), default=None,
                    help='Which mastery mapping source this mod asks for (default: by family count at install '
                         'time).  "packed" is the right choice for a pack that is installed next to more than six '
                         'families; it also keeps the build from taking a six-slot lease.')
    ap.add_argument('--face-per-colour', dest='d4_face_rule', action='store_false',
                    help='D4 classes (D4FACE1): old path = a face per colour swf<body+k> (one face when a sibling is missing); '
                         'default puts the class face on all ten colour slots, as the game draws it (D4-FACE-02)')
    ap.add_argument('--d4-idle', action='store_true', help="Idle (6001/6007) with D4's own timing and weapon positions")
    ap.add_argument('--voice-id', type=int, help='D5 voice every rank speaks with (default: the template\'s)')
    ap.add_argument('--previous-leases', type=Path, help='Explicit pinned prior ownership JSON; enables update mode')
    ap.add_argument('--previous-leases-sha256', help='Expected canonical JSON digest (not raw file SHA256)')
    ap.add_argument('--owner-mod-id', help='Explicit canonical lease owner in the pinned bundle')
    args = ap.parse_args()
    from d5lib.sourceimports import d4_update_options
    try:
        update = d4_update_options(args.previous_leases, args.previous_leases_sha256, args.owner_mod_id)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    if update and args.original_state is None:
        ap.error('Pinned updates require --original-state for original backup reads')
    args.output_path = Path(os.path.abspath(args.output_path))
    # The write guard covers temporary sibling publication as well as final output.
    # Existing parents only: never silently create a broad unexpected output root.
    allowed = args.output_path.parent.resolve(strict=True)
    if allowed != args.output_path.parent or args.output_path.exists():
        ap.error('output must be new, with an existing canonical non-symlink parent')
    if allowed == Path(allowed.anchor) or allowed == Path.home():
        ap.error('choose a dedicated scratch parent, not a volume/home root')
    from d5lib import offlinepaths
    protected = (Path(__file__).resolve().parents[1], args.prepared_root, args.library_root,
                 args.source_archive, args.game_path, args.face_path, args.cutin_path,
                 args.original_state, args.d4_root, args.mapping, args.reserved_ids, args.source_voice, args.previous_leases, args.exact_emission, *args.exact_mods_root)
    try:
        offlinepaths.offline_output(args.output_path, protected)
        offlinepaths.offline_output(str(args.output_path) + '.cache', (*protected, args.output_path))
        offlinepaths.separate_outputs(args.output_path, str(args.output_path) + '.cache')
    except ValueError as exc:
        ap.error(str(exc))
    tempfile.tempdir = str(allowed)

    def check_write(path):
        if isinstance(path, int):
            return
        p = Path(os.fsdecode(path)).resolve()
        if not p.is_relative_to(allowed):
            raise RuntimeError('Offline pilot refused write outside scratch parent: ' + str(p))

    def audit(event, values):
        if event == 'open':
            path, mode, flags = values
            if (mode and any(c in mode for c in 'wax+')) or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                check_write(path)
        elif event == 'os.mkdir' and not isinstance(values[0], int) and os.path.isdir(os.fsdecode(values[0])):
            return                                   # makedirs(exist_ok=True) on an existing folder changes nothing
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime'):
            check_write(values[0])
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            check_write(values[0])
            check_write(values[1])
        elif (event == 'subprocess.Popen' and list(values[1][:3]) == [sys.executable, '-m', 'ziglang']
              and '-o' in values[1] and Path(values[1][values[1].index('-o') + 1]).resolve().is_relative_to(allowed)):
            return                                   # the kit's own runtime compile (Zig), output inside scratch
        elif event in ('subprocess.Popen', 'os.system', 'socket.connect', 'socket.bind'):
            raise RuntimeError('Offline pilot blocks subprocess/network; toolchain installation is not authorized')
    sys.addaudithook(audit)

    # Import handlers in the same order as the canonical installer before any
    # feature module can register a finalizer through an incidental import.
    from d5lib import modsys
    modsys.load_handlers()
    from d5lib import sourceimports, sprites
    # Kit caches (motion / icon / face blocks) normally live in the kit folder, which in a development checkout
    # links to the installed kit: an offline build keeps its own next to the output instead.
    import shutil
    scratch_cache = str(args.output_path) + '.cache'
    if os.path.isdir(sprites.CACHE_DIR) and not os.path.exists(scratch_cache):
        shutil.copytree(sprites.CACHE_DIR, scratch_cache)          # read the kit's cache, write only the copy
    sprites.CACHE_DIR = scratch_cache
    from d5lib import lzs_splice
    lzs_splice.CACHE_DIR = os.path.join(scratch_cache, 'lzs_splice')   # splice plans are a cache: keep them in scratch too
    from d5lib import runtime
    runtime.CACHE = scratch_cache                                 # the runtime DLL, if it must be compiled
    os.environ['ZIG_GLOBAL_CACHE_DIR'] = str(Path(scratch_cache) / 'zig-global')
    os.environ['ZIG_LOCAL_CACHE_DIR'] = str(Path(scratch_cache) / 'zig-local')
    state = args.original_state.resolve() if args.original_state else None
    index = json.loads((state / 'backups.json').read_text()) if state else {}
    backup_reads = {}

    def resolver(archive):
        info = index.get(archive)
        if info is None:
            return None, None
        if '..' in Path(archive).parts or Path(archive).is_absolute():
            raise ValueError('Unsafe original archive identity')
        base = state / 'backups' / archive.replace('/', '__')
        mode = info['mode']
        if mode not in ('append', 'full'):
            raise ValueError('Requested resource has no vanilla original: ' + archive)
        path = base.with_name(base.name + ('.hdr' if mode == 'append' else '.full'))
        data = path.read_bytes()
        backup_reads[archive] = dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        return (data, None) if mode == 'append' else (None, str(path))

    reserved = json.loads(args.reserved_ids.read_text()) if args.reserved_ids else {}
    result = sourceimports.build_d4_pilot(
        prepared_root=args.prepared_root, library_root=args.library_root,
        source_archive=args.source_archive, game_path=args.game_path,
        face_path=args.face_path, cutin_path=args.cutin_path, output_path=args.output_path,
        family=args.family, template=args.template, supported_families=args.supported_families,
        source_ids=args.source_ids, edition=args.edition,
        backup_resolver=resolver if state else None, log=lambda s: print(s, flush=True),
        source_root=args.d4_root, mapping=sourceimports.load_d4_mapping(args.mapping) if args.mapping else None,
        class_name=args.class_name, unlocked_ranks=args.unlocked_ranks, voice_id=args.voice_id, mod_id=args.mod_id,
        d4_idle=args.d4_idle, d4_face_rule=args.d4_face_rule, sprite_family=args.sprite_family, kind=args.kind,
        reserved_evilities=reserved.get('evilities', []), reserved_skills=reserved.get('skills', []),
        approximate_palettes=args.approximate_palettes, source_frame_fallbacks=args.source_frame_fallbacks,
        source_voice=json.loads(args.source_voice.read_text()) if args.source_voice else None,
        personality_variants=args.personality_variants, exact_emission=json.loads(args.exact_emission.read_text()) if args.exact_emission else None,
        exact_mods_roots=args.exact_mods_root, **update)
    if args.engine_exact and args.exact_emission:
        ap.error('--engine-exact and --exact-emission both apply exact rows; use one')
    if args.mastery_mode and not args.mastery:
        ap.error('--mastery-mode needs --mastery')
    if args.engine_exact or args.mastery:
        # New engine path: reviewed exact D4 evility rows (extension table) and the
        # class-mastery extension's own family declaration, applied to the built mod
        # before the one canonical finalization. No alias is left claiming an exact row.
        from d5lib import d4exact
        emission = json.loads(args.engine_exact.read_text()) if args.engine_exact else None
        stored = json.loads((args.output_path / 'pilot-receipt.json').read_text())
        plan, profile = stored['d4_plan'], stored['d4_profile']
        report = plan['report']
        prior = {int(e['d4_id']): int(e['d5_id']) for e in report
                 if e.get('kind') == 'evility' and e.get('d5_id') is not None}
        # Cross-import claims: the caller's reserved list already holds every other mod's IDs.
        occupied = set(reserved.get('evilities', ())) | set(reserved.get('skills', ()))
        engine = dict(exact=[], adapted=[], missing=[])
        targets = set()
        if emission is not None:
            exact_all = {int(x['d4_id']): int(x['d5_id']) for x in emission['exact']}
            keep = {sid: target for sid, target in exact_all.items() if target not in occupied}
            skill_added = emission['mod_files']['patches/db/Skill.dat.json']['added']
            behavior = emission['mod_files']['patches/evilities/evilities.json']['evilities']
            filtered = {
                'exact': [{'d4_id': sid, 'd5_id': target} for sid, target in sorted(keep.items())],
                'mod_files': {
                    'patches/db/Skill.dat.json': {'added': [r for r in skill_added if int(r['id']) in set(keep.values())]},
                    'patches/evilities/evilities.json': {
                        'evilities': {k: v for k, v in behavior.items() if int(k) in set(keep.values())}},
                },
            }
            for folder in (result['mod'],):
                root = Path(folder)
                if root.is_dir():
                    engine['exact'] = d4exact.apply_exact(root, filtered, profile,
                                                          args.family, occupied, prior)
                    targets = {row['target_id'] for row in engine['exact']}
            if not targets:
                staged = Path(result['staging']) / 'mods' / result['mod_id']
                if (staged / 'patches/db/Skill.dat.json').is_file():
                    engine['exact'] = d4exact.apply_exact(staged, filtered, profile,
                                                          args.family, occupied, prior)
                    targets = {row['target_id'] for row in engine['exact']}
            for item in report:
                match = next((r for r in engine['exact'] if r['d4_id'] == item.get('d4_id')), None)
                if item.get('kind') == 'evility' and match:
                    item.update(status='exact-extension', d5_id=match['target_id'])
                    item.pop('works_like', None)
                    item.pop('works_like_name', None)
            engine['adapted'] = [e['d4_id'] for e in report
                                 if e.get('kind') == 'evility' and e.get('status') == 'adapted']
            engine['missing'] = [e['d4_id'] for e in report
                                 if e.get('kind') == 'evility' and e.get('status') in ('omitted', 'placeholder', None)]
            if not targets:
                # Legitimate: this class owns no D4 evility the reviewed exact
                # vocabulary covers, so every evility stays an alias adaptation.
                engine['note'] = 'no owned D4 evility is in the exact set'
                print('engine path: no exact row applies; evilities stay adapted', flush=True)
        if args.mastery:
            payload = {'mastery': {'families': [args.family]}}
            if args.mastery_mode:
                payload['mastery']['mode'] = args.mastery_mode
            for folder in (result['mod'], str(Path(result['staging']) / 'mods' / result['mod_id'])):
                root = Path(folder)
                if root.is_dir():
                    path = root / 'patches/classes/mastery.json'
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(payload, indent=1) + '\n')
        # The finalized build reads the staged copy: mirror the small JSON patches
        # the engine path changed into it so exactly one set of rows is built.
        source_mod = Path(result['mod'])
        staged_mod = Path(result['staging']) / 'mods' / result['mod_id']
        if source_mod.is_dir() and staged_mod.is_dir():
            import shutil
            for relative in ('patches/db/Skill.dat.json', 'patches/db/char.dat.json',
                             'patches/evilities/evilities.json', 'patches/evilities/aliases.json',
                             'patches/classes/mastery.json'):
                src = source_mod / relative
                if src.is_file():
                    (staged_mod / relative).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, staged_mod / relative)
            for src in sorted((source_mod / 'patches/classes').glob('class_*.json')):
                shutil.copyfile(src, staged_mod / 'patches/classes' / src.name)
        result['engine'] = engine
        stored['d4_plan']['report'] = report
        stored['engine'] = engine
        (args.output_path / 'pilot-receipt.json').write_text(json.dumps(stored, indent=2))
        print('engine path: ' + json.dumps({k: (v if not isinstance(v, list) else len(v))
                                            for k, v in engine.items()}, default=str), flush=True)
    if args.finalize:
        from d5lib import database, gamefs, modsys, sourcefidelity
        stage = Path(result['staging'])
        order = json.loads((stage / 'profiles/Default/load_order.json').read_text())
        # Native profile file format is read by the native manager, not inferred.
        manager = modsys.ModManager(str(stage))
        mods = manager.enabled_mods()
        final = dict(status='failed', native_gameplay_tested=False)
        fs = gamefs.GameFS(str(args.game_path), backup_resolver=resolver if state else None)
        try:
            logs = []
            def log(message):
                logs.append(message)
                print(message, flush=True)
            ctx = modsys.build(fs, mods, log=log)
            out = args.output_path / 'finalized-logical'
            inventory = []
            for _, (vpath, raw) in sorted(ctx.outputs.items()):
                relative = Path(vpath)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Unsafe finalized virtual path')
                path = out / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                reread = path.read_bytes()
                if reread != raw:
                    raise ValueError('Finalized output readback mismatch')
                inventory.append(dict(path=vpath, bytes=len(raw), sha256=hashlib.sha256(reread).hexdigest()))
            char = database.load_table('char.dat', (out / 'Database/Database_0.dat/char.dat').read_bytes())
            rows = {r['id']: r for r in char.rows}
            for expected in result['source_stats_readback']:
                row = rows[expected['id']]
                if ([row['base_' + s] for s in sourcefidelity.STATS] != expected['base'] or
                        [row['apt_' + s] for s in sourcefidelity.STATS] != expected['aptitudes']):
                    raise ValueError('Finalizer changed source static rank fields')
            final.update(status='built-offline' if not getattr(ctx, 'skipped_features', []) else 'built-with-skips',
                         files=inventory, skipped_features=getattr(ctx, 'skipped_features', []), logs=logs,
                         load_order=order, mod_ids=[m.id for m in mods], source_rank_readback=True,
                         finalizer_order=[fn.__module__ + '.' + fn.__name__ for fn in modsys.ordered_finalizers()])
        except Exception as exc:
            final.update(error=f'{type(exc).__name__}: {exc}')
            print('OFFLINE FINALIZER BLOCKED:', final['error'], flush=True)
        finally:
            fs.reset()
        (args.output_path / 'finalization.json').write_text(json.dumps(final, indent=2))
        result['finalization'] = final['status']
    # Exact originals used by the resolver must remain unchanged.
    for item in backup_reads.values():
        if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Original backup changed during build')
    (args.output_path / 'original-read-receipt.json').write_text(json.dumps(backup_reads, indent=2))
    (args.output_path / 'build-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    # A materialized mod is not a successful finalized build. Callers must be
    # able to gate packaging/install preparation on the process exit status.
    return 1 if args.finalize and result.get('finalization') != 'built-offline' else 0


if __name__ == '__main__':
    raise SystemExit(main())
