"""TEST28 base pin for D1CMOTION3.

D1CMOTION2 resolved its "installed TEST28 base" to
`Local/kit-backups/20261101-live28/kit/mods`, which was taken **before** TEST27 was installed and
is therefore TEST26. Every bank it grafted into was TEST26 (Strider anm01540 `8c07b693`, unique
2300 anm00533 `a1313ea4`), so the shipped TEST29 banks dropped the TEST27 lifter fix and the
TEST28 walk/lift.

This module is the only way the D1CMOTION tools may find their base. The base folders are the
pre-finalizer TEST28 bundle folders:

  * class:     Builds/LIFTSLOT1-20261101/mods/D1C_Class_{11390,11400}
  * uniques:   Builds/UNIQWALK1-20261101/mods/D1C_Unique_*

`tools/test28-base.json` pins the sha256 of all 38 banks that D1CMOTION3 splices into; it was
generated with `tools/d1cmotion2_pin.py`, which asserts every one of those files (and every file
of the 19 folders) is byte-identical to `Local/Installed D5ModKit/mods` (TEST28 as installed).
A base file whose sha256 is not in that set is refused.

`D1CMOTION_BASE` may override the folder root, but only with a root whose banks still hash to
the pinned TEST28 set — it cannot select a backup that fails the check.
"""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path('/Volumes/Data/Projects/D5')
REL = Path('files/Anime/ANM_HI_JP.dat')
DEFAULT_CLASS_BASE = ROOT / 'Builds/LIFTSLOT1-20261101/mods'
DEFAULT_UNIQUE_BASE = ROOT / 'Builds/UNIQWALK1-20261101/mods'
INSTALLED = (ROOT / 'Local/Installed D5ModKit').resolve()
MANIFEST = Path(__file__).resolve().parent / 'test28-base.json'

# The four class banks, exactly as named in the D1CMOTION3 brief (TEST28).
CLASS_ANCHORS = {
    ('D1C_Class_11390', 'anm01540.lzs'):
        '382327353a5a1f09ae879bb66eaf3e28ef4a2f1097aaae026641a9f6bc30058b',
    ('D1C_Class_11390', 'anm01541.lzs'):
        'ec14365d032fc7ce7600697c92876d5ea4d169bef8b9dba84d5cf18b1ab0e257',
    ('D1C_Class_11400', 'anm01530.lzs'):
        '699d3ce653b2ae7e9c09eeb66933af04b0bd02f15a283048def2357901c8b21b',
    ('D1C_Class_11400', 'anm01531.lzs'):
        'fca7ecc754f0738396bae15b2cd64d663aca25d28abe03d74bf8026ae66d6f63',
}
UNIQUE_ANCHORS = {
    ('D1C_Unique_2300', 'anm00533.lzs'):
        '052dc6c2bd08ea015f49a956061b6c4f7dedc8474cb18af457216e044539c4f5',
}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest():
    return json.loads(MANIFEST.read_text())


def pinned():
    """{('mod','bank.lzs'): sha256} for all 38 banks D1CMOTION3 touches."""
    doc = manifest()
    return {(m, b): h for m, banks in doc['banks'].items() for b, h in banks.items()}


def class_base():
    return Path(os.environ.get('D1CMOTION_CLASS_BASE', DEFAULT_CLASS_BASE))


def unique_base():
    return Path(os.environ.get('D1CMOTION_UNIQUE_BASE', DEFAULT_UNIQUE_BASE))


def base_dir(mod):
    if mod.startswith('D1C_Class_'):
        return class_base()
    if mod.startswith('D1C_Unique_'):
        return unique_base()
    raise SystemExit(f'{mod}: not a D1CMOTION3 target pack')


def bank_path(mod, bank):
    return base_dir(mod) / mod / REL / bank


def expected(mod, bank):
    try:
        return pinned()[(mod, bank)]
    except KeyError:
        raise SystemExit(f'{mod}/{bank}: not one of the pinned TEST28 banks') from None


def require_base(mod, bank, path=None):
    """Refuse a base bank whose sha256 is not the TEST28 one."""
    path = Path(path) if path is not None else bank_path(mod, bank)
    want = expected(mod, bank)
    if not path.is_file():
        raise SystemExit(f'{mod}/{bank}: base bank missing at {path}')
    got = sha256_file(path)
    if got != want:
        hint = ''
        if 'kit-backups' in str(path):
            hint = ' (that path is a kit backup; the 20261101-live28 backup is TEST26)'
        raise SystemExit(f'{mod}/{bank}: base is not TEST28{hint}: {path}\n'
                         f'  expected {want}\n  found    {got}')
    return path


def require_base_set(mods=None):
    """Check every pinned bank of the given mods (default: all 19). Returns count checked."""
    doc = manifest()
    selected = mods or list(doc['banks'])
    n = 0
    for mod in selected:
        for bank in doc['banks'][mod]:
            require_base(mod, bank)
            n += 1
    for (mod, bank), want in {**CLASS_ANCHORS, **UNIQUE_ANCHORS}.items():
        if mod in selected and doc['banks'][mod][bank] != want:
            raise SystemExit(f'manifest disagrees with the brief for {mod}/{bank}')
    return n


def require_installed_match(mods=None):
    """Read-only: every file of the base folders must equal the installed TEST28 kit."""
    doc = manifest()
    selected = mods or list(doc['banks'])
    n = 0
    for mod in selected:
        root = base_dir(mod) / mod
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            target = INSTALLED / 'mods' / path.relative_to(base_dir(mod))
            if not target.is_file():
                raise SystemExit(f'{path}: absent from the installed kit')
            if path.read_bytes() != target.read_bytes():
                raise SystemExit(f'{path}: differs from the installed kit')
            n += 1
    return n
