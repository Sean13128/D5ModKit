"""Build a D4 source unique or legacy comparison. Never installs or opens saves."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ('d4-root', 'game-path', 'original-state', 'output-path'):
        ap.add_argument('--' + flag, type=Path, required=True)
    ap.add_argument('--mods-root', type=Path, action='append', required=True,
                    help='Check every native mod in this directory, including disabled mods; repeat for candidate kits')
    ap.add_argument('--target-id', type=int, default=470)
    ap.add_argument('--identity', type=int,
                    help='Registry identity for a general import (>= 10000, rank-0 multiple of ten); '
                         'the char row id. Requires --physical; ignored by the legacy comparison')
    ap.add_argument('--physical', type=int,
                    help='Leased low art row (10..999) a registry identity keys its sprite, companion, '
                         'standing picture, face and cut-in to')
    ap.add_argument('--source-id', type=int, help='General D4-only unique import instead of the legacy comparison')
    ap.add_argument('--template-id', type=int)
    ap.add_argument('--share-art-owner', help='D4-NPC1: build on another pack\'s art (its mod id); writes no art files')
    ap.add_argument('--share-sprite', type=int, help='With --share-art-owner: the owner char row\'s sprite_id')
    ap.add_argument('--share-color', type=int, help='With --share-art-owner: the colour id the row draws with')
    for flag in ('prepared-root', 'library-root', 'face-path', 'cutin-path', 'mapping', 'source-voice'):
        ap.add_argument('--' + flag, type=Path)
    ap.add_argument('--exact-emission', type=Path, help='Reviewed D4 exact extension emission JSON (general import only)')
    ap.add_argument('--exclude-source-id', action='append', type=int, default=[],
                    help='Explicit source identities already present in D5; repeat')
    ap.add_argument('--portrait-policy', choices=('d5-comparison', 'd4-converted'), default='d5-comparison')
    ap.add_argument('--no-finalize', action='store_true')
    ap.add_argument('--previous-leases', type=Path, help='Explicit pinned prior ownership JSON; enables update mode')
    ap.add_argument('--previous-leases-sha256', help='Expected canonical JSON digest (not raw file SHA256)')
    ap.add_argument('--owner-mod-id', help='Explicit canonical lease owner in the pinned bundle')
    ap.add_argument('--supersede-prefix', action='append', default=[],
                    help='Read but ignore mod ids with this prefix (an earlier generation this import replaces); repeat')
    ap.add_argument('--storage-lease', type=Path,
                    help='d4-leases.json: pin this --source-id character\'s recorded quest/slot/help ids and avoid every other one')
    ap.add_argument('--engine-exact', type=Path,
                    help='Reviewed D4 extension emission JSON; exact owned evilities are applied to this import')
    args = ap.parse_args()
    from d5lib.sourceimports import d4_update_options
    try:
        update = d4_update_options(args.previous_leases, args.previous_leases_sha256, args.owner_mod_id)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    if update and args.source_id is None:
        ap.error('Pinned updates require a general source unique import')
    share = None
    if args.share_art_owner is not None:
        if None in (args.share_sprite, args.share_color):
            ap.error('--share-art-owner needs --share-sprite and --share-color')
        if args.physical is not None:
            ap.error('A shared-art import has no physical art row of its own')
        share = dict(owner=args.share_art_owner, sprite_id=args.share_sprite, color_id=args.share_color)
    if args.source_id is not None and args.template_id is None:
        ap.error('General source imports require --template-id')
    if args.source_id is not None and share is None and any(v is None for v in (
            args.prepared_root, args.library_root, args.face_path, args.cutin_path)):
        ap.error('General source imports require prepared/library roots, face and cut-in')
    args.output_path = Path(os.path.abspath(args.output_path))
    allowed = args.output_path.parent.resolve(strict=True)
    if allowed != args.output_path.parent or args.output_path.exists() or allowed == Path(allowed.anchor) or allowed == Path.home():
        ap.error('Output must be new under an existing dedicated canonical parent')
    from d5lib import offlinepaths
    protected = (Path(__file__).resolve().parents[1], args.d4_root, args.game_path,
                 args.original_state, args.prepared_root, args.library_root, args.face_path, args.cutin_path,
                 args.mapping, args.source_voice, args.previous_leases, args.exact_emission, *args.mods_root)
    try:
        offlinepaths.offline_output(args.output_path, protected)
        offlinepaths.offline_output(str(args.output_path) + '.cache', (*protected, args.output_path))
        offlinepaths.separate_outputs(args.output_path, str(args.output_path) + '.cache')
    except ValueError as exc:
        ap.error(str(exc))
    tempfile.tempdir = str(allowed)

    def check_write(value):
        if not isinstance(value, int) and not Path(os.fsdecode(value)).resolve().is_relative_to(allowed):
            raise RuntimeError('Offline unique build refused write outside output parent: ' + str(value))

    def audit(event, values):
        if event == 'open':
            path, mode, flags = values
            if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                check_write(path)
        elif event == 'os.mkdir' and not isinstance(values[0], int) and os.path.isdir(os.fsdecode(values[0])):
            return
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime'):
            check_write(values[0])
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            check_write(values[0]); check_write(values[1])
        elif (event == 'subprocess.Popen' and list(values[1][:3]) == [sys.executable, '-m', 'ziglang']
              and '-o' in values[1] and Path(values[1][values[1].index('-o') + 1]).resolve().is_relative_to(allowed)):
            return
        elif event in ('subprocess.Popen', 'os.system', 'socket.connect', 'socket.bind'):
            raise RuntimeError('Offline unique build blocks unrelated subprocesses and network')
    sys.addaudithook(audit)
    from d5lib import modsys
    modsys.load_handlers()
    from d5lib import d4unique, runtime, sprites
    # Existing kit caches are never mutated; all cache writes stay with this output.
    sprites.CACHE_DIR = str(allowed / (args.output_path.name + '.cache'))
    runtime.CACHE = sprites.CACHE_DIR
    from d5lib import lzs_splice
    lzs_splice.CACHE_DIR = os.path.join(sprites.CACHE_DIR, 'lzs_splice')   # splice plans are a cache: keep them inside the allowed scratch
    os.environ['ZIG_GLOBAL_CACHE_DIR'] = str(Path(sprites.CACHE_DIR) / 'zig-global')
    os.environ['ZIG_LOCAL_CACHE_DIR'] = str(Path(sprites.CACHE_DIR) / 'zig-local')
    common = dict(d4_root=args.d4_root, game_path=args.game_path, original_state=args.original_state,
        mods_roots=args.mods_root, output_path=args.output_path, target_id=args.target_id,
        finalize=not args.no_finalize)
    if (args.identity is None) != (args.physical is None) and share is None:
        ap.error('--identity and --physical go together')
    if share is not None and (args.identity is None or args.source_id is None):
        ap.error('A shared-art import needs --identity and --source-id')
    if args.identity is not None and args.source_id is None:
        ap.error('A registry identity requires the general source unique import (--source-id)')
    if args.source_id is None and args.exact_emission is not None:
        ap.error('Exact extension requires the general unique import')
    if args.source_id is None:
        result = d4unique.build(**common, portrait_policy=args.portrait_policy)
    else:
        from d5lib import sourceimports
        storage = {}
        if args.storage_lease:
            pin, res = d4unique.load_storage_leases(args.storage_lease, args.source_id)
            storage = dict(storage_pin=pin, storage_reserved=res)
            storage.update(ability_lease=d4unique.load_ability_leases(args.storage_lease, args.source_id))
        result = d4unique.build_import(**common, source_id=args.source_id, template_id=args.template_id,
            prepared_root=args.prepared_root, library_root=args.library_root, face_path=args.face_path,
            cutin_path=args.cutin_path, mapping=sourceimports.load_d4_mapping(args.mapping),
            excluded_source_ids=args.exclude_source_id,
            source_voice=json.loads(args.source_voice.read_text()) if args.source_voice else None,
            exact_emission=json.loads(args.exact_emission.read_text()) if args.exact_emission else None,
            supersede_prefixes=tuple(args.supersede_prefix),
            identity=args.identity, physical=args.physical, share_art=share, **storage,
            engine_exact=json.loads(args.engine_exact.read_text()) if args.engine_exact else None, **update)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
