"""EDFBISECT2: byte-level region proof for every variant.

For each variant EDF bank: decode TEST28, the variant and BS-DARK, compute each file's own region
spans, and compare bytes region by region:

  * vs TEST28  -> the differing regions must be exactly the variant's categories (+ the derived
                  layout regions: block header, palette/texture info offsets, image headers,
                  file header);
  * vs BS-DARK -> every category region the variant does NOT carry must differ (they are DARK's
                  delta), and the regions it DOES carry must be byte-identical.

Writes evidence/regionproof.json and prints a compact table.

usage: python tools/edfbisect2_proof.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
OUT = ROOT / 'Builds/EDFBISECT2-20261102'
DARK = ROOT / 'Builds/WHEELBISECT1-20261102/bs_dark/mods'
EDF = 'D1C_Class_11400'
TABLES = ['animations', 'nodes', 'keys', 'palette_infos', 'texture_infos', 'cells',
          'transforms', 'pivots', 'colors', 'params']
TABLE_SIZE = [4, 20, 12, 8, 12, 18, 16, 4, 20, 4]

VARIANTS = {
    'eb_pal': ('pal',),
    'eb_pix': ('pix',),
    'eb_tab': ('tab',),
    'eb_tabpal': ('tab', 'pal'),
}
OWNED = {'pal': {'palette_images_10', 'palette_images_11', 'palette_images_12',
                 'palette_images_13', 'palette_images_14', 'palette_images_15', 'palette_images_16',
                 'palette_images_17', 'palette_images_18', 'palette_images_19'},
         'pix': {'texture_0_data'},
         'tab': {'nodes', 'keys', 'cells', 'transforms', 'pivots', 'colors', 'params'}}


def spans(data: bytes) -> dict:
    """region -> (start, end) byte spans of one decoded member, from its own layout."""
    f = anm.load(data)
    b = f.block
    offs, size = b.layout()
    head_end = 0x20
    out = {'file_header': (0, head_end), 'block_header': (head_end, head_end + 0x44)}
    for i, name in enumerate(TABLES):
        start = head_end + offs[i]
        out[name] = (start, start + len(b.tables()[i]) * TABLE_SIZE[i])
    block_end = head_end + size
    nimg = len(f.textures) + len(f.palettes)
    out['image_headers'] = (block_end, block_end + nimg * 0x10)
    # image data, in header order, with each image's 128-byte alignment padding
    base_off = struct_unpack_dsize(data)
    imgs = f.textures + f.palettes
    o = 0
    for i, im in enumerate(imgs):
        pad = im.pad if i else b''
        # the padding BEFORE this image belongs to the previous image's pad
        start = base_off + o + len(pad)
        out[f'{"texture" if i < len(f.textures) else "palette"}_{i if i < len(f.textures) else i - len(f.textures)}_data'] = \
            (start, start + len(im.data))
        o += len(pad) + len(im.data)
        if pad:
            prev = i - 1
            key = f'{"texture" if prev < len(f.textures) else "palette"}_{prev if prev < len(f.textures) else prev - len(f.textures)}_pad'
            out[key] = (start - len(pad), start)
    out['trailing'] = (base_off + o, len(data))
    return out


def struct_unpack_dsize(data: bytes) -> int:
    """offset of the image data area: field 0 of the file header + 0x10 (d5lib: base = h0 + 0x10)."""
    import struct
    return struct.unpack_from('<I', data, 0)[0] + 0x10


def region_diff(a: bytes, b: bytes, sa=None, merged=('palette_images',)):
    """name -> differing byte count, using file A's spans extended to file B."""
    sa = sa or spans(a)
    sb = spans(b)
    out = {}
    for name in set(sa) | set(sb):
        if name not in sb or name not in sa:
            s0, e0 = sa.get(name) or sb.get(name)
            out[name] = e0 - s0                 # present in one file only: all bytes differ
            continue
        s, e = sa[name]
        t, u = sb[name]
        n = 0
        for i in range(min(e - s, u - t)):
            if s + i < len(a) and t + i < len(b) and a[s + i] != b[t + i]:
                n += 1
        out[name] = n + abs((e - s) - (u - t))     # a size difference is a difference
    return out


def merge_palettes(d):
    """collapse palette_N_data / palette_N_pad into one key per palette (palette_images_N)."""
    out = {}
    for k, v in d.items():
        if k.startswith('palette_') and k.split('_')[1].isdigit():
            out['palette_images_' + k.split('_')[1]] = out.get('palette_images_' + k.split('_')[1], 0) + v
        else:
            out[k] = v
    return out


def main():
    result = {}
    ok_all = True
    derived = {'file_header', 'block_header', 'palette_infos', 'texture_infos', 'image_headers',
               'texture_0_pad', 'texture_1_pad', 'trailing'}
    for key, cats in VARIANTS.items():
        owned = set().union(*[OWNED[c] for c in cats])
        rows = {}
        for bank in base.manifest()['banks'][EDF]:
            # decoded members: a byte region diff must not be taken over LZS streams
            t28 = anm.load((base.base_dir(EDF) / EDF / base.REL / bank).read_bytes()).to_bytes()
            var = anm.load((OUT / key / 'mods' / EDF / base.REL / bank).read_bytes()).to_bytes()
            dk = anm.load((DARK / EDF / base.REL / bank).read_bytes()).to_bytes()
            d28 = merge_palettes(region_diff(t28, var))
            ddelta = merge_palettes(region_diff(t28, dk))
            dd = merge_palettes(region_diff(dk, var))
            delta_regions = {k for k, v in ddelta.items() if v}
            # A. a region with no delta in DARK may not change in the variant
            changed_without_delta = {k: v for k, v in d28.items() if v and k not in delta_regions}
            # B. delta regions the variant does not own must stay TEST28's
            kept_but_moved = {k: v for k, v in d28.items()
                              if v and k in delta_regions and k not in owned and k not in derived}
            # C. owned delta regions must reproduce DARK byte-for-byte
            owned_differ = {k: v for k, v in dd.items() if k in owned and v}
            # D. palette descriptors (semantic: rows past 10 exist with DARK's num_colors/unk)
            def descs(path):
                b = anm.load(path).block
                return [(p.num_colors, p.unk) for p in b.palette_infos]
            vt, vd = descs(OUT / key / 'mods' / EDF / base.REL / bank), descs(DARK / EDF / base.REL / bank)
            tt = descs(base.base_dir(EDF) / EDF / base.REL / bank)
            if 'pal' in cats:
                desc_ok = len(vt) == len(vd) and vt == vd
            else:
                desc_ok = vt == tt
            ok = not changed_without_delta and not kept_but_moved and not owned_differ and desc_ok
            ok_all &= ok
            rows[bank] = {'vs_test28': d28, 'vs_dark': dd, 'dark_delta': ddelta,
                          'changed_region_without_a_dark_delta': changed_without_delta,
                          'delta_region_kept_as_test28': kept_but_moved,
                          'owned_region_differing_from_dark': owned_differ,
                          'palette_descriptors_match': desc_ok, 'pass': ok}
            print(f'{key} {bank}: vs TEST28 {sorted((k, v) for k, v in d28.items() if v)}', flush=True)
            print(f'   DARK delta regions: {sorted(delta_regions)}', flush=True)
            print(f'   owned-from-DARK identical: {sorted(k for k in owned if not dd.get(k))}', flush=True)
            print(f'   palette descriptors match: {desc_ok}   {"PASS" if ok else "FAIL"}', flush=True)
            if changed_without_delta:
                print('   ! changed without a DARK delta:', changed_without_delta, flush=True)
            if kept_but_moved:
                print('   ! delta region not kept as TEST28:', kept_but_moved, flush=True)
            if owned_differ:
                print('   ! owned but differing from DARK:', owned_differ, flush=True)
        result[key] = rows
    (OUT / 'evidence').mkdir(parents=True, exist_ok=True)
    (OUT / 'evidence' / 'regionproof.json').write_text(json.dumps(result, indent=1) + '\n')
    print('REGION PROOF', 'PASS' if ok_all else 'FAIL')
    return 0 if ok_all else 1


if __name__ == '__main__':
    raise SystemExit(main())
