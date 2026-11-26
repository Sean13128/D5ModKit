"""EDFBISECT2: part-only EDF variants on BS-E's layout.

Layout of every variant (identical to BS-E except for the EDF bank's content):

    Strider  D1C_Class_11390  anm01540/01541 = TEST28 (byte-identical)
    EDF      D1C_Class_11400  anm01530/01531 = TEST28 + exactly one category of BS-DARK's delta
    17 unique packs            = TEST28 (byte-identical)
    profile  LIVE5_EB_<NAME>   188-entry order identical to LIVE5_TEST28

21/27 keep TEST28's roots (74/92) in every variant -- the same "dead trees" state BS-DARK is in,
except that BS-DARK also appends the two preservation rows 64001/64011; here they are not needed
because the base is TEST28, whose 21/27 roots already point at TEST28's own records.

Categories (from tools/edfbisect2_regiondiff.py + _detail.py):
    pal  10 new palette images (10..19) + their 10 palette_infos rows
    pix  the atlas pixel delta of texture 0 (texture 1 is unchanged in both banks)
    tab  the appended node/key/cell/transform/pivot/colour/param records (dead: nothing in
         TEST28's animation table reaches them)
    tabpal  tab + pal  (the smallest *coherent* append group: the appended cells carry pal=10)

usage: python tools/edfbisect2_build.py [out dir]
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
DARK = ROOT / 'Builds/WHEELBISECT1-20261102/bs_dark/mods'
LIVE_PROFILE = ROOT / 'Local/Installed D5ModKit/profiles/LIVE5_TEST28'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Builds/EDFBISECT2-20261102'
REL = base.REL
EDF = 'D1C_Class_11400'
STRIDER = 'D1C_Class_11390'
CLASS_MODS = (STRIDER, EDF)
TAB = ('nodes', 'keys', 'cells', 'transforms', 'pivots', 'colors', 'params')

VARIANTS = {
    'eb_pal':    {'name': 'LIVE5_EB_PAL',    'cat': ('pal',)},
    'eb_pix':    {'name': 'LIVE5_EB_PIX',    'cat': ('pix',)},
    'eb_tab':    {'name': 'LIVE5_EB_TAB',    'cat': ('tab',)},
    'eb_tabpal': {'name': 'LIVE5_EB_TABPAL', 'cat': ('tab', 'pal')},
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(mods_root, mod, bank):
    return anm.load((mods_root / mod / REL / bank).read_bytes())


def clone(f: anm.AnmFile) -> anm.AnmFile:
    """An independent deep copy of a parsed member (parse the serialized bytes)."""
    return anm.load(f.to_bytes())


def applied(t28: anm.AnmFile, dark: anm.AnmFile, cats):
    """TEST28 with exactly the named categories of DARK's delta applied."""
    f = clone(t28)
    b, db = f.block, dark.block
    rows = {}
    if 'tab' in cats:
        for name in TAB:
            mine, theirs = getattr(b, name), getattr(db, name)
            assert len(theirs) > len(mine), (name, len(mine), len(theirs))
            assert mine == theirs[:len(mine)], (name, 'TEST28 prefix differs from DARK')
            tail = theirs[len(mine):]
            getattr(b, name).extend(clone_value(tail))
            rows[name] = {'test28': len(mine), 'dark': len(theirs), 'appended': len(tail)}
    if 'pal' in cats:
        n = len(f.palettes)
        assert n == 10 and len(dark.palettes) == 20
        assert [p.data for p in f.palettes] == [p.data for p in dark.palettes[:n]]
        f.palettes.extend(clone_images(dark.palettes[n:]))
        # descriptors 0..n-1 differ from DARK only in their derived virtual offset
        assert [(p.num_colors, p.unk) for p in b.palette_infos] == \
               [(p.num_colors, p.unk) for p in db.palette_infos[:n]]
        b.palette_infos.extend(clone_value(db.palette_infos[n:]))
        rows['palettes'] = {'test28': n, 'dark': 20, 'appended': 20 - n}
    if 'pix' in cats:
        assert len(f.textures) == len(dark.textures)
        px = []
        for i, (a, d) in enumerate(zip(f.textures, dark.textures)):
            assert (a.width, a.height) == (d.width, d.height), i
            n = sum(1 for x, y in zip(a.data, d.data) if x != y)
            a.data = d.data
            px.append({'texture': i, 'changed_pixels': n})
        rows['pixels'] = px
    # the animation table, texture_infos and everything else stay TEST28's
    assert b.animations == t28.block.animations, 'table 0 must stay TEST28'
    for name in TAB:
        if name not in TAB:
            continue
    return f, rows


def clone_value(rows):
    import copy
    return [copy.deepcopy(r) for r in rows]


def clone_images(imgs):
    import copy
    return [copy.deepcopy(i) for i in imgs]


def region_state(f: anm.AnmFile) -> dict:
    """Everything a region diff needs, in a comparable (hashable-ish) form."""
    b = f.block
    return {
        'animations': [tuple(sorted(vars(a).items())) for a in b.animations],
        'nodes': [tuple(sorted(vars(n).items())) for n in b.nodes],
        'keys': [tuple(sorted(vars(k).items())) for k in b.keys],
        'cells': [tuple(sorted(vars(c).items())) for c in b.cells],
        'transforms': [tuple(sorted(vars(t).items())) for t in b.transforms],
        'pivots': [tuple(sorted(vars(p).items())) for p in b.pivots],
        'colors': [tuple(c.rgba) for c in b.colors],
        'params': list(b.params),
        'palette_ncolors': [(p.num_colors, p.unk) for p in b.palette_infos],
        'texture_infos_dims': [(t.width, t.height, t.bpp) for t in b.texture_infos],
        'palette_images': [(bytes(i.fmt), i.width, i.height, hashlib.sha256(i.data).hexdigest())
                           for i in f.palettes],
        'texture_pixels': [hashlib.sha256(i.data).hexdigest() for i in f.textures],
        'texture_pads': [bytes(i.pad) for i in f.textures],
        'palette_pads': [bytes(i.pad) for i in f.palettes],
        'hdr_unk': bytes(f.hdr_unk), 'trailing': bytes(f.trailing),
        'block_pad': bytes(b.pad), 'count9': b.count9, 'block_id': b.id,
        'block_size': b.layout()[1],
    }


CATEGORY_REGIONS = {'pal': ('palette_ncolors', 'palette_images', 'palette_pads'),
                    'pix': ('texture_pixels',),
                    'tab': ('nodes', 'keys', 'cells', 'transforms', 'pivots', 'colors', 'params')}


def verify(variant: anm.AnmFile, t28: anm.AnmFile, dark: anm.AnmFile, cats):
    """Every category region must equal DARK's; every other region must equal TEST28's."""
    v, t, d = region_state(variant), region_state(t28), region_state(dark)
    owned = set()
    for c in cats:
        owned |= set(CATEGORY_REGIONS[c])
    # block size / block alignment padding are layout consequences of any table growth, not
    # categories: they are recorded, never asserted against either side.
    DERIVED = ('block_size', 'block_pad')
    report = {}
    for name in v:
        if name in DERIVED:
            continue
        if name in owned:
            if name == 'palette_images':      # DARK has 20 images, the variant only its own subset
                n = len(v[name]) if 'pal' not in cats else len(d[name])
                ok = v[name][:n] == d[name][:n]
                if 'pal' not in cats:
                    ok = ok and len(v[name]) == len(t[name])
            elif name in ('nodes', 'keys', 'cells', 'transforms', 'pivots', 'colors', 'params'):
                ok = v[name] == d[name][:len(v[name])] if 'tab' in cats else v[name] == t[name]
                if 'tab' in cats:
                    ok = ok and len(v[name]) == len(d[name])
            else:
                ok = v[name] == d[name]
        else:
            ok = v[name] == t[name]
        report[name] = ok
    assert all(report.values()), {k: x for k, x in report.items() if not x}
    return report


def main():
    n = base.require_base_set()
    print(f'TEST28 base asserted: {n} pinned banks', flush=True)
    order = json.loads((LIVE_PROFILE / 'load_order.json').read_text())
    assert len(order) == 188, len(order)
    profile_doc = json.loads((LIVE_PROFILE / 'profile.json').read_text())

    t28_root = {m: base.base_dir(m) for m in base.manifest()['banks']}
    report = {}
    for key, spec in VARIANTS.items():
        dest = OUT / key
        if dest.exists():
            shutil.rmtree(dest)
        (dest / 'mods').mkdir(parents=True)
        for mod in base.manifest()['banks']:
            # Strider and the 17 unique packs are TEST28; only the EDF class pack changes
            src = t28_root[mod] / mod
            shutil.copytree(src, dest / 'mods' / mod)
        row = {'profile': spec['name'], 'categories': list(spec['cat']), 'banks': {}}
        for bank in base.manifest()['banks'][EDF]:
            t28 = load(t28_root[EDF], EDF, bank)
            dark = anm.load((DARK / EDF / REL / bank).read_bytes())
            built, rows = applied(t28, dark, spec['cat'])
            vr = verify(built, t28, dark, spec['cat'])
            raw = built.to_bytes()
            dst = dest / 'mods' / EDF / REL / bank
            dst.write_bytes(anm.lzs_compress(raw))
            back = anm.load(dst.read_bytes()).to_bytes()
            assert back == raw, (bank, 'lzs roundtrip')
            row['banks'][bank] = {'test28_raw': len(t28.to_bytes()), 'raw': len(raw),
                                  'dark_raw': len(dark.to_bytes()),
                                  'delta_vs_test28': len(raw) - len(t28.to_bytes()),
                                  'regions': rows, 'verify': vr,
                                  'sha256': hashlib.sha256(dst.read_bytes()).hexdigest()}
            print(f"  {key} {EDF}/{bank}: raw {len(raw):,} "
                  f"(TEST28 {len(t28.to_bytes()):,}, DARK {len(dark.to_bytes()):,})", flush=True)
        pdir = dest / 'profile' / spec['name']
        pdir.mkdir(parents=True)
        (pdir / 'load_order.json').write_text(json.dumps(order, indent=1) + '\n')
        doc = dict(profile_doc)
        doc['name'] = spec['name']
        (pdir / 'profile.json').write_text(json.dumps(doc, indent=1) + '\n')
        # file delta vs TEST28
        changed, identical = [], 0
        for mod in base.manifest()['banks']:
            src, dst = t28_root[mod] / mod, dest / 'mods' / mod
            rels = {p.relative_to(src) for p in src.rglob('*') if p.is_file()}
            assert rels == {p.relative_to(dst) for p in dst.rglob('*') if p.is_file()}, mod
            for rel in sorted(rels):
                if (src / rel).read_bytes() == (dst / rel).read_bytes():
                    identical += 1
                else:
                    changed.append(f'{mod}/{rel.relative_to(REL)}')
        assert len(changed) <= 2, changed
        row.update({'files': identical + len(changed), 'identical': identical,
                    'changed_banks': changed, 'load_order_len': len(order)})
        report[key] = row
        print(f'{key}: {len(changed)} banks changed {changed}, {identical} files identical', flush=True)

    (OUT / 'evidence').mkdir(parents=True, exist_ok=True)
    (OUT / 'evidence' / 'build.json').write_text(json.dumps(report, indent=1) + '\n')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
