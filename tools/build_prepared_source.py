"""Build one caller-pinned prepared-source entry or cold-finalize normal mods.

All assets and allocations arrive in an explicit private JSON configuration.
The process write guard restricts writes to the dedicated offline output parent.

Ported into the Kit from the DD2 source-pack worktree (2026-10-27) so a DD2 rebuild runs the
importer of the branch that owns it.  Only the sys.path root moved (this file's own checkout).
"""
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
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--config', type=Path)
    group.add_argument('--finalize-config', type=Path)
    args = parser.parse_args()
    config = json.loads((args.config or args.finalize_config).read_text())
    output = Path(config.get('output_path', config.get('output'))).absolute()
    allowed = output.parent.resolve(strict=True)
    if output.exists() or output.parent != allowed or any(p.is_symlink() for p in output.parents):
        parser.error('Choose a new output beneath a canonical private parent')
    # Existing shared guard accepts only the Kit Zig compiler and its bounded
    # cold worker. This entry does not spawn the old D4 worker.
    from tools.build_d4_expansion import guard
    tempfile.tempdir = str(allowed)
    guard(allowed)
    cache = str(output) + '.cache'
    os.environ['ZIG_GLOBAL_CACHE_DIR'] = str(Path(cache) / 'zig-global')
    os.environ['ZIG_LOCAL_CACHE_DIR'] = str(Path(cache) / 'zig-local')
    from d5lib import modsys
    modsys.load_handlers()
    from d5lib import sprites, runtime
    sprites.CACHE_DIR = runtime.CACHE = config.get('cache', cache)
    if args.finalize_config:
        from d5lib import d4expansion
        result = d4expansion.finalize(config)
    else:
        from d5lib import nativeimports
        result = nativeimports.build_entry(**config)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()