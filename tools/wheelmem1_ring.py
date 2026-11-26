"""WHEELMEM1: per-D1C-wheel-ring (13 entries) resident-bank totals for each build.

The D1C Hire page holds 13 entries (live33/wheel33.json path):
  11390 11400 11760 11770 11800 11810 11820 11830 11840 11850 11860 11900 11930
FUN_140666920 draws 12 slots per pass through unit_set_appearance(slot, class, ...), and
ui_sprite_set_anm loads `sprite_family` plus `sprite_family + 2` for each slot
(`ui_sprite_set_anm(..., iVar3 + param_5, ..., iVar3 + 2, ...)`), so the wheel keeps two
banks per visible entry resident and releases the previous one on each cursor move.

usage: wheelmem1_ring.py <banks.json> <out.json>
"""
import json
import sys
from pathlib import Path

ROOT = Path('/Volumes/Data/Projects/D5')
sys.path.insert(0, str(ROOT / 'Local/Worktrees/striderlift4'))
from d5lib import anm  # noqa: E402

INSTALLED = ROOT / 'Local/Installed D5ModKit/mods'
REL = Path('files/Anime/ANM_HI_JP.dat')
RING = [11390, 11400, 11760, 11770, 11800, 11810, 11820, 11830, 11840, 11850, 11860, 11900, 11930]
# banks the TEST29 builds rewrite (mod folder + changed members), for substitution
BUILD_BANKS = {
    'TEST29b': ROOT / 'Builds/TEST29FIX1-20261101/mods',
    'TEST29c': ROOT / 'Builds/TEST29FIX1-20261101/candidate-c/mods',
}


def family_of(cid):
    p = INSTALLED / f'D1C_Class_{cid}' / 'patches/classes' / f'class_{cid}.json'
    return json.loads(p.read_text())['sprite_family']


def bank_path(mod, fam):
    return INSTALLED / mod / REL / f'anm{fam:05d}.lzs'


def main():
    banks = json.loads(Path(sys.argv[1]).read_text())
    mapping = {}
    for cid in RING:
        fam = family_of(cid)
        mapping[cid] = fam
    out = {'ring': RING, 'sprite_family': mapping, 'builds': {}}
    for build in ('TEST28', 'TEST29b', 'TEST29c'):
        rows, total = [], 0
        for cid in RING:
            fam = mapping[cid]
            mod = f'D1C_Class_{cid}'
            for off in (0, 1, 2):
                name = f'anm{fam + off:05d}.lzs'
                # changed banks: take the build's own copy; otherwise the installed (TEST28) member
                rec = None
                if build != 'TEST28' and mod in banks['builds'][build] and name in banks['builds'][build][mod]:
                    rec = banks['builds'][build][mod][name]
                elif mod in banks['builds']['TEST28'] and name in banks['builds']['TEST28'][mod]:
                    rec = banks['builds']['TEST28'][mod][name]
                else:
                    p = bank_path(mod, fam + off)
                    if p.exists():
                        a = anm.load(p)
                        rec = {'raw_bytes': len(a.to_bytes()), 'textures': len(a.textures),
                               'palettes': len(a.palettes),
                               'texel_bytes': sum(len(i.data) for i in a.textures)}
                if rec is None:
                    continue
                total += rec['raw_bytes']
                rows.append({'class': cid, 'bank': name, 'raw_bytes': rec['raw_bytes'],
                             'textures': rec['textures'], 'texel_bytes': rec.get('texel_bytes', 0),
                             'palettes': rec['palettes'],
                             'replaced': bool(build != 'TEST28' and rec is not None
                                              and mod in banks['builds'][build]
                                              and name in banks['builds'][build][mod])})
        out['builds'][build] = {'rows': rows, 'resident_raw_bytes': total}
        print(f'{build}: ring resident raw {total:,} B over {len(rows)} banks '
              f'({total/1048576:.1f} MiB)')
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
    print('wrote', sys.argv[2])


if __name__ == '__main__':
    main()
