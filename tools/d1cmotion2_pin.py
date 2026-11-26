"""Regenerate tools/test28-base.json (the pinned TEST28 bank hashes).

Every bank listed is asserted, at generation time, to be byte-identical to the same path in
`Local/Installed D5ModKit/mods` (TEST28 as installed), and the four class banks and the unique
2300 anchor are asserted against the literal hashes in the D1CMOTION3 brief. Run from the
worktree with the kit venv python.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d1cmotion2_base as base  # noqa: E402

# The 38 banks D1CMOTION2 changes, and D1CMOTION3 re-splices on the TEST28 base.
ORDERED = """
D1C_Class_11390/anm01540.lzs D1C_Class_11390/anm01541.lzs
D1C_Class_11400/anm01530.lzs D1C_Class_11400/anm01531.lzs
D1C_Unique_2300/anm00533.lzs D1C_Unique_2300/anm00534.lzs
D1C_Unique_2301/anm00536.lzs D1C_Unique_2301/anm00537.lzs
D1C_Unique_2302/anm00543.lzs D1C_Unique_2302/anm00544.lzs
D1C_Unique_2410/anm00856.lzs D1C_Unique_2410/anm00857.lzs
D1C_Unique_2907/anm00880.lzs D1C_Unique_2907/anm00881.lzs
D1C_Unique_2909/anm00883.lzs D1C_Unique_2909/anm00884.lzs
D1C_Unique_2910/anm00886.lzs D1C_Unique_2910/anm00887.lzs
D1C_Unique_2911/anm00889.lzs D1C_Unique_2911/anm00890.lzs
D1C_Unique_2912/anm00892.lzs D1C_Unique_2912/anm00893.lzs
D1C_Unique_2914/anm00895.lzs D1C_Unique_2914/anm00896.lzs
D1C_Unique_2915/anm00898.lzs D1C_Unique_2915/anm00899.lzs
D1C_Unique_3060/anm00596.lzs D1C_Unique_3060/anm00597.lzs
D1C_Unique_3150/anm00910.lzs D1C_Unique_3150/anm00911.lzs
D1C_Unique_3160/anm00913.lzs D1C_Unique_3160/anm00914.lzs
D1C_Unique_4/anm00516.lzs D1C_Unique_4/anm00517.lzs
D1C_Unique_5/anm00523.lzs D1C_Unique_5/anm00524.lzs
D1C_Unique_5590/anm00603.lzs D1C_Unique_5590/anm00604.lzs
"""


def main():
    ordered = ORDERED.split()
    mods = {}
    for line in ordered:
        mod, bank = line.split('/')
        mods.setdefault(mod, []).append(bank)
    for mod, banks in mods.items():
        for bank in banks:
            path = base.base_dir(mod) / mod / base.REL / bank
            installed = base.INSTALLED / 'mods' / mod / base.REL / bank
            got = base.sha256_file(path)
            if not installed.is_file() or base.sha256_file(installed) != got:
                raise SystemExit(f'{mod}/{bank}: base does not equal the installed TEST28 kit')
            anchor = base.CLASS_ANCHORS.get((mod, bank)) or base.UNIQUE_ANCHORS.get((mod, bank))
            if anchor and anchor != got:
                raise SystemExit(f'{mod}/{bank}: does not match the brief hash {anchor}')
    for (mod, bank), anchor in {**base.CLASS_ANCHORS, **base.UNIQUE_ANCHORS}.items():
        if mods.get(mod, [None])[0] != bank and bank not in mods.get(mod, []):
            raise SystemExit(f'{mod}/{bank}: anchor bank not in the changed set')
    doc = dict(description='TEST28 pre-finalizer base banks for D1CMOTION3; each verified equal to '
                           'Local/Installed D5ModKit/mods at generation time',
               class_base='Builds/LIFTSLOT1-20261101/mods',
               unique_base='Builds/UNIQWALK1-20261101/mods',
               banks={mod: {b: base.sha256_file(base.base_dir(mod) / mod / base.REL / b)
                            for b in banks} for mod, banks in mods.items()})
    base.MANIFEST.write_text(json.dumps(doc, indent=2) + '\n')
    print(f'wrote {base.MANIFEST} with {sum(len(v) for v in mods.values())} banks '
          f'in {len(mods)} packs')


if __name__ == '__main__':
    main()
