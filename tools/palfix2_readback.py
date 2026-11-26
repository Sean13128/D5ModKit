"""PALFIX2 readback: decode all 38 banks out of the sandbox archive after the install and
check them against (a) the member-local `grips` replay the post-install gate uses and (b) the
palette/image counts this build promises: each bank's TEST28 palette and image-header counts.

usage: python tools/palfix2_readback.py [--data-dir D]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402
import striderlift_render_diff as gate  # noqa: E402

B = Path('/Volumes/Data/Projects/D5/Builds/PALFIX2-20261102')
EV = B / 'evidence'
ANIME = Path('/Volumes/Data/ai-tmp/codex/palfix2/sandbox/game/Data/Anime')
MODS = B / 'palmerge2/mods'


def main():
    data_dir = ANIME
    if '--data-dir' in sys.argv:
        data_dir = Path(sys.argv[sys.argv.index('--data-dir') + 1])
    rows, ok = [], True
    for mod in base.manifest()['banks']:
        for bank in base.manifest()['banks'][mod]:
            f = anm.load_from_archive(bank, lang='JP', data_dir=str(data_dir))
            installed = f.to_bytes()
            staged = (MODS / mod / base.REL / bank).read_bytes()
            replay = anm.load(gate.replay_member(staged, 'banner,grips' if 'Unique' in mod else 'grips')).to_bytes()
            t28 = anm.load(base.bank_path(mod, bank))
            row = {'mod': mod, 'bank': bank,
                   'installed_sha256': hashlib.sha256(installed).hexdigest(),
                   'replay_sha256': hashlib.sha256(replay).hexdigest(),
                   'staged_sha256': hashlib.sha256(staged).hexdigest(),
                   'installed_equals_replay': installed == replay,
                   'installed_palettes': len(f.palettes),
                   'installed_palette_infos': len(f.block.palette_infos),
                   'installed_image_headers': len(f.palettes) + len(f.textures),
                   'test28_palettes': len(t28.palettes),
                   'test28_image_headers': len(t28.palettes) + len(t28.textures),
                   'installed_bytes': len(installed), 'staged_stored_bytes': len(staged)}
            row['palettes_match_test28'] = row['installed_palettes'] == row['test28_palettes']
            row['headers_match_test28'] = row['installed_image_headers'] == row['test28_image_headers']
            ok &= row['installed_equals_replay'] and row['palettes_match_test28'] \
                and row['headers_match_test28']
            rows.append(row)
            print(f"{mod}/{bank}: installed==replay {row['installed_equals_replay']}, "
                  f"palettes {row['installed_palettes']} (TEST28 {row['test28_palettes']}), "
                  f"image headers {row['installed_image_headers']} "
                  f"(TEST28 {row['test28_image_headers']}), {row['installed_bytes']:,} B decoded, "
                  f"staged {row['staged_stored_bytes']:,} B stored", flush=True)
    EV.mkdir(parents=True, exist_ok=True)
    (EV / 'readback.json').write_text(json.dumps(rows, indent=1) + '\n')
    print('READBACK', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
