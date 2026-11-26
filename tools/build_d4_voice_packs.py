"""Rebuild the D4 Armor Knight and Valvatorez pilot packs with their own D4 voices.

Offline only: reads the D4 install's sound archives read-only, writes new pack
copies under --output, never touches the installed kit, the D5 game or a save.

Voice routing (D4 situation -> D5 kind/situation) is evidence-bound; see
docs/D4_VOICES.md and Subprojects/Engine-Extensions/voices/REPORT.md. Every
source clip that has no reviewed destination is recorded as an explicit gap
instead of being guessed onto an unrelated D5 situation.

Usage (from the worktree root):
  python -B tools/build_d4_voice_packs.py --output /Volumes/Data/Projects/D5/Local/d4-voices-packs
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from d5lib import d4source, d4voices, modsys, voices  # noqa: E402

D4_ROOT = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+')
RESEARCH = Path('/Volumes/Data/Projects/D5/Research/d4-expansion-20261018')

# D4 has twelve voice situations; only the dispatcher wrapper differs between
# them (see docs/D4_VOICES.md). The routes come from the Kit helper so there is
# one source of truth; they are the situations with native caller evidence, not
# name or number similarity.
EVENT_MAP = d4voices.basic_event_map()

# No reviewed destination. Kept as explicit receipts so the gap is auditable.
UNROUTED = {
    '1': 'script-only wrapper (0x140252310 has no engine caller); role not established',
    '3': 'script-only wrapper (0x1402520e0); role not established',
    '8': 'script-only wrapper (0x1402522e0); only arm forwarding an explicit voice channel',
    '9': 'script-only wrapper (0x140251f60); role not established',
    '10': 'growth/level-up at one caller (0x140300bb0), generic filler at four others; weak',
    '11': 'whole-bank recruitment preview bucket; not a battle event',
}

PACKS = [
    dict(mod_id='D4_ArmorKnight_1350_VOICE', source_id=1080, groups=[1080, 1081, 1082],
         voice_id=9073, name='Male Armor Knight (D4)',
         origin=Path('/Volumes/Data/Projects/D5/Local/ex08-pilot-fixed/D4_ArmorKnight_1080_PILOT'),
         rows=[303, 304, 305, 306, 307, 308]),
    dict(mod_id='D4_ArmorKnight_1080_VOICE', source_id=1080, groups=[1080, 1081, 1082],
         voice_id=9071, name='Armor Knight (D4)',
         origin=RESEARCH / 'mvp-focused-repair-build-v1/run-2/combined/staged-kit/mods/D4_Class_1080',
         rows=[14080, 14081, 14082, 14083, 14084, 14085]),
    dict(mod_id='D4_Valvatorez_VOICE', source_id=300, groups=[10],
         voice_id=9072, name='Valvatorez (D4 pilot)',
         origin=RESEARCH / 'unique/comparison-v4/native-mods/D4_Valvatorez_Comparison',
         rows=[216]),
]


def occupied_ids(output: Path):
    """custom voice ids already used by mods next to the output (never the live kit)."""
    used = set()
    for p in output.parent.glob('*/patches/voices/voices.json'):
        try:
            used |= {int(k) for k in json.loads(p.read_text())['voices']}
        except (OSError, ValueError, KeyError):
            continue
    return used


def set_voice_id(mod: Path, rows, voice_id):
    """set voice_id on the given char rows; patches use either a `rows` map or an `added` list"""
    path = mod / 'patches/db/char.dat.json'
    data = json.loads(path.read_text())
    seen = set()
    for key in ('rows', 'added'):
        group = data.get(key)
        if isinstance(group, dict):
            for row_id, row in group.items():          # `rows` is keyed by id and has no id field
                if int(row_id) in rows:
                    row['voice_id'] = voice_id
                    seen.add(int(row_id))
            continue
        for row in group or []:
            if int(row['id']) in rows:
                row['voice_id'] = voice_id
                seen.add(int(row['id']))
    if seen != set(rows):
        raise SystemExit(f'{path}: expected char rows {sorted(rows)}, patched {sorted(seen)}')
    path.write_text(json.dumps(data, indent=1) + '\n')


def build_pack(pack, output: Path, occupied):
    dest = output / pack['mod_id']
    if dest.exists():
        raise SystemExit(f'{dest} already exists; refusing to overwrite')
    shutil.copytree(pack['origin'], dest)
    mod = modsys.Mod(str(dest))
    # The origin bank (if any) is replaced by the rebuilt EN+JP one.
    old = dest / 'patches/voices'
    if old.exists():
        shutil.rmtree(old)
    if pack['voice_id'] in occupied:
        raise SystemExit(f"voice id {pack['voice_id']} already used next to {output}")

    en = d4source.D4Data(D4_ROOT, lang='EN')          # JP shares the EN character DB
    receipts = {}
    for lang in ('EN', 'JP'):
        receipts[lang] = d4voices.import_d4_voice(
            mod, en, voice_id=pack['voice_id'], groups=pack['groups'], event_map=EVENT_MAP,
            source_language=lang, destination_language=lang)
    set_voice_id(dest, pack['rows'], pack['voice_id'])
    meta = json.loads((dest / 'mod.json').read_text())
    meta['version'] = '0.2.0-d4voice'
    meta['description'] = (meta.get('description', '').rstrip('. ') +
                           '. Own D4 voice: genuine D4 EN+JP recordings, six routed situations, '
                           'unrouted source clips listed in the build receipt.').lstrip('. ')
    (dest / 'mod.json').write_text(json.dumps(meta, indent=1) + '\n')
    return dict(mod_id=pack['mod_id'], voice_id=pack['voice_id'], groups=pack['groups'],
                rows=pack['rows'], locales={k: dict(v) for k, v in receipts.items()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    occupied = occupied_ids(output)
    result = dict(format='d4-voice-packs/1', event_map=EVENT_MAP, unrouted=UNROUTED,
                  packs=[build_pack(p, output, occupied) for p in PACKS],
                  installed=False, native_gameplay_tested=False, audio_played=False)
    (output / 'build-receipt.json').write_text(json.dumps(result, indent=1) + '\n')
    for p in result['packs']:
        for lang, r in p['locales'].items():
            routed = sum(1 for c in r['clips'] if c['status'] == 'converted-adapted')
            print(f"{p['mod_id']} {lang}: voice {p['voice_id']} groups {p['groups']} "
                  f"routed {routed}/{len(r['clips'])} clips")
    print(f'receipt: {output / "build-receipt.json"}')


if __name__ == '__main__':
    main()
