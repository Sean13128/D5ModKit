"""Group accepted local D4 imports and build them in fresh offline workers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def guard(allowed):
    def check(value):
        if not isinstance(value, int) and not Path(os.fsdecode(value)).resolve().is_relative_to(allowed):
            raise RuntimeError('Expansion build refused write outside output parent: ' + str(value))
    own_script = str(Path(__file__).resolve())
    def audit(event, values):
        if event == 'open':
            path, mode, flags = values
            if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                check(path)
        elif event == 'os.mkdir' and not isinstance(values[0], int) and os.path.isdir(os.fsdecode(values[0])):
            return
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime'):
            check(values[0])
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            check(values[0]); check(values[1])
        elif event == 'subprocess.Popen':
            cmd = values[1]
            if (len(cmd) == 4 and cmd[:3] == [sys.executable, own_script, '--finalize-config']
                    and Path(cmd[3]).resolve().is_relative_to(allowed)):
                return
            if (cmd[:3] == [sys.executable, '-m', 'ziglang'] and '-o' in cmd
                    and Path(cmd[cmd.index('-o') + 1]).resolve().is_relative_to(allowed)):
                return
            raise RuntimeError('Expansion build blocks unrelated subprocesses')
        elif event in ('os.system', 'socket.connect', 'socket.bind'):
            raise RuntimeError('Expansion build blocks shell/network operations')
    sys.addaudithook(audit)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--finalize-config':
        path = Path(sys.argv[2]).resolve(strict=True)
        config = json.loads(path.read_text())
        from d5lib import offlinepaths
        protected = (Path(__file__).resolve().parents[1], path, config['game_path'],
                     config['original_state'], *config['mods'])
        offlinepaths.offline_output(config['output'], protected)
        offlinepaths.offline_output(config['cache'], protected)
        offlinepaths.separate_outputs(config['output'], config['cache'])
        allowed = Path(config['cache']).parent.resolve(strict=True)
        tempfile.tempdir = str(allowed)
        guard(allowed)
        os.environ['ZIG_GLOBAL_CACHE_DIR'] = str(Path(config['cache']) / 'zig-global')
        os.environ['ZIG_LOCAL_CACHE_DIR'] = str(Path(config['cache']) / 'zig-local')
        from d5lib import modsys
        modsys.load_handlers()
        from d5lib import d4expansion
        d4expansion.finalize(config)
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ('game-path', 'original-state', 'current-kit', 'output-path'):
        ap.add_argument('--' + flag, required=True, type=Path)
    ap.add_argument('--generic-build', type=Path)
    ap.add_argument('--unique-build', type=Path)
    ap.add_argument('--build', nargs=2, metavar=('ALIAS', 'PATH'), action='append',
                    help='Repeat for N accepted single-entry builds; replaces legacy pilot pair')
    ap.add_argument('--entry', action='append', help='Repeat to select aliases; default all with dependencies')
    ap.add_argument('--voice-bank', nargs=2, metavar=('SOURCE_ID', 'NATIVE_MOD_PATH'), action='append',
                    help='Overlay a completed source voice bank into its copied import child; repeat')
    ap.add_argument('--inventory', type=Path, help='Immutable full D4 inventory; emit sparse coverage ledger')
    ap.add_argument('--body-overlay', nargs=2, action='append', metavar=('SOURCE_ID','MATERIALIZED_BUILD'), help='Source body successor copied only into staged owned sprite pair')
    ap.add_argument('--voice-status', type=Path, help='Hash-bound per-clip voice successor status ledger')
    ap.add_argument('--character-interpretation', type=Path, help='Hash-bound source sprite/voice interpretation overlay')
    ap.add_argument('--effect-verification', type=Path, help='Optional verified offline effect conversion corpus')
    ap.add_argument('--previous-leases', type=Path, help='Explicit pinned prior ownership JSON; enables update mode')
    ap.add_argument('--previous-leases-sha256', help='Expected canonical JSON digest (not raw file SHA256)')
    args = ap.parse_args()
    from d5lib.sourceimports import d4_update_options
    try:
        update = d4_update_options(args.previous_leases, args.previous_leases_sha256, owner_required=False)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    if update and not args.build:
        ap.error('Pinned updates require explicit --build entries')
    if args.voice_bank and len({x[0] for x in args.voice_bank}) != len(args.voice_bank):
        ap.error('Voice bank source identities must be distinct')
    voice_banks = dict(args.voice_bank or [])
    if args.body_overlay and len({x[0]for x in args.body_overlay})!=len(args.body_overlay):ap.error("Body overlay source identities must be distinct")
    body_overlays=dict(args.body_overlay or [])
    if args.build:
        if args.generic_build or args.unique_build or len({x[0] for x in args.build}) != len(args.build):
            ap.error('Use distinct --build aliases without the legacy generic/unique pair')
        builds = {alias: Path(path) for alias, path in args.build}
    else:
        if not args.generic_build or not args.unique_build:
            ap.error('Supply repeated --build ALIAS PATH, or both legacy pilot paths')
        builds = None
    args.output_path = Path(os.path.abspath(args.output_path))
    allowed = args.output_path.parent.resolve(strict=True)
    if allowed != args.output_path.parent or args.output_path.exists() or allowed == Path(allowed.anchor) or allowed == Path.home():
        ap.error('Choose a new output below an existing dedicated canonical directory')
    from d5lib import offlinepaths
    roots = list(builds.values()) if builds else [args.generic_build, args.unique_build]
    protected = (Path(__file__).resolve().parents[1], *roots, *(str(p) + '.cache' for p in roots),
                 args.game_path, args.original_state, args.current_kit, args.inventory, args.effect_verification,
                 *voice_banks.values(), *body_overlays.values(), args.voice_status, args.character_interpretation, args.previous_leases)
    try:
        offlinepaths.offline_output(args.output_path, protected)
        offlinepaths.offline_output(str(args.output_path) + '.cache', (*protected, args.output_path))
        offlinepaths.separate_outputs(args.output_path, str(args.output_path) + '.cache')
    except ValueError as exc:
        ap.error(str(exc))
    tempfile.tempdir = str(allowed)
    guard(allowed)
    from d5lib import modsys
    modsys.load_handlers()
    from d5lib import d4expansion
    print(json.dumps(d4expansion.build(generic_build=args.generic_build, unique_build=args.unique_build,
        game_path=args.game_path, original_state=args.original_state, current_kit=args.current_kit,
        output_path=args.output_path, builds=builds, entries=args.entry,
        worker_script=Path(__file__).resolve(), inventory_path=args.inventory,
        effect_verification=args.effect_verification, voice_banks=voice_banks,
        voice_status_path=args.voice_status, interpretation_path=args.character_interpretation, body_overlays=body_overlays, **update), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
