"""WHEELFIX1 readback: decode the four class banks out of the sandbox archive after the install and
check them against the member-local replay the post-install gate uses (so "installed bytes" is a
measurement, not an inference).

usage: python tools/wheelfix1_readback.py
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

B = Path('/Volumes/Data/Projects/D5/Builds/WHEELFIX1-20261102')
EV = B / 'evidence'
ANIME = Path('/Volumes/Data/ai-tmp/hermes/wheelfix1/sandbox/game/Data/Anime')


def main():
    rows, ok = [], True
    for mod in ('D1C_Class_11390', 'D1C_Class_11400'):
        for bank in base.manifest()['banks'][mod]:
            installed = anm.load_from_archive(bank, data_dir=str(ANIME)).to_bytes()
            staged = (B / 'mods' / mod / base.REL / bank).read_bytes()
            replay = gate.replay_member(staged, 'grips')
            row = {'mod': mod, 'bank': bank,
                   'installed_sha256': hashlib.sha256(installed).hexdigest(),
                   'replay_sha256': hashlib.sha256(replay).hexdigest(),
                   'staged_sha256': hashlib.sha256(staged).hexdigest(),
                   'installed_equals_replay': installed == replay,
                   'installed_bytes': len(installed), 'staged_bytes': len(staged)}
            ok &= row['installed_equals_replay']
            rows.append(row)
            print(f"{mod}/{bank}: installed==replay {row['installed_equals_replay']} "
                  f"({row['installed_bytes']:,} B decoded)", flush=True)
    (EV / 'readback-wheelfix.json').write_text(json.dumps(rows, indent=1) + '\n')
    print('READBACK', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
