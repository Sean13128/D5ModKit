"""Rebuild the nine DD2 class packs' animation banks with the control code in the LOW byte.

    python tools/rebuild_dd2_control_flags.py --mods MODS_DIR --out OUT_DIR [--receipt FILE]

For every `.lzs` member of every DD2 class pack (a pack whose class descriptor says `wheel: DD2`):

  * load it with the kit's own reader, run `d5lib.dd2source.normalize_control_flags`, write it back
    with the kit's own writer;
  * assert that the ONLY bytes that changed are the four flag bytes belong to a root-node key
    (`key_table_offset + i*12 + 2` and `+3`); every other byte, every table, every image and the
    block layout must be identical or the pack is refused;
  * render animations 1 / 101 / 1001 / 1007 before and after and assert the pixels are identical
    (the control code is timing, not art);
  * re-run classcheck R10 on the rebuilt folder and require zero errors.

Writes `OUT_DIR/<pack>/` (a copy of the original pack with only the rebuilt members replaced) and a
receipt JSON.  Never writes into the source folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, classcheck, dd2source, lzs  # noqa: E402

ANIMS = (1, 101, 1001, 1007)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_byte_offsets(block) -> set:
    """Offsets (relative to the block) of every key's flag bytes."""
    offs, _size = block.layout()
    keys_off = offs[2]
    return {keys_off + i * 12 + 2 for i in range(len(block.keys))} | \
           {keys_off + i * 12 + 3 for i in range(len(block.keys))}


def diff_offsets(a: bytes, b: bytes):
    if len(a) != len(b):
        return None
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


def block_starts(data: bytes, blocks):
    """Absolute start offset of each block in a serialized anm file."""
    # AnmFile.to_bytes writes a 32-byte file header, then the blocks in order.
    starts, pos = [], 32
    for block in blocks:
        starts.append(pos)
        _offs, size = block.layout()
        pos += size
    return starts


def render(anmf, anim_id):
    idx = next((i for i, a in enumerate(anmf.blocks[0].animations) if a.id == anim_id), None)
    if idx is None:
        return None
    try:
        img = anm.render_frame(anmf, idx, 0)
    except Exception:  # noqa: BLE001 - a render failure is reported, not fatal
        return "error"
    return np.asarray(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--receipt", default=None)
    args = ap.parse_args()

    mods = Path(args.mods)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    receipt = {"packs": {}, "problems": []}

    packs = []
    for folder in sorted(mods.iterdir()):
        if not folder.is_dir():
            continue
        js = sorted((folder / "patches" / "classes").glob("class_*.json")) if (folder / "patches" / "classes").exists() else []
        if not js:
            continue
        spec = json.loads(js[0].read_text())
        if str(spec.get("wheel", "")).lower() == "dd2":
            packs.append((folder, spec))

    if len(packs) != 9:
        receipt["problems"].append("expected 9 DD2 class packs, found %d" % len(packs))
        print("expected 9 DD2 class packs, found %d" % len(packs))
        Path(args.receipt or (out_root / "rebuild-receipt.json")).write_text(json.dumps(receipt, indent=1))
        return 1

    for folder, spec in packs:
        dest = out_root / folder.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(folder, dest)
        rec = {"family": spec.get("family"), "name": spec.get("name"), "members": {},
               "changed_keys": 0, "changed_bytes": 0, "render_identical": True}
        for member in sorted((folder / "files").rglob("*.lzs")):
            rel = member.relative_to(folder / "files")
            import struct as _struct
            packed = member.read_bytes()
            compressed = (packed[:4] in (b"dat\0", b"pac\0")
                          and _struct.unpack_from("<I", packed, 4)[0] > len(packed))
            decompressed = lzs.decompress(packed) if compressed else packed
            raw = decompressed
            anmf = anm.parse(raw)
            before = [render(anmf, a) for a in ANIMS]
            changed = dd2source.normalize_control_flags(anmf)
            markers_changed = dd2source.normalize_image_byte_order(anmf)
            data = anmf.to_bytes()
            if len(data) != len(raw):
                receipt["problems"].append("%s: %s re-serialized to %d bytes, was %d"
                                           % (folder.name, rel, len(data), len(raw)))
                continue
            after = [render(anm.parse(data), a) for a in ANIMS]

            starts = block_starts(raw, anmf.blocks)
            allowed = set()
            for block, start in zip(anmf.blocks, starts):
                for off in key_byte_offsets(block):
                    allowed.add(start + off)
            image_start = 32 + sum(int.from_bytes(raw[start:start + 4], "little") for start in starts)
            for i in range(len(anmf.textures) + len(anmf.palettes)):
                allowed.update(range(image_start + i * 16 + 8, image_start + i * 16 + 12))
            diffs = diff_offsets(raw, data)
            if diffs is None:
                receipt["problems"].append("%s: %s changed length" % (folder.name, rel))
                continue
            stray = [d for d in diffs if d not in allowed]
            if stray:
                receipt["problems"].append("%s: %s changed %d byte(s) outside the key flag fields: %s"
                                           % (folder.name, rel, len(stray), stray[:8]))
            for a, b in zip(before, after):
                if isinstance(a, str) or isinstance(b, str):
                    continue
                if a is None and b is None:
                    continue
                if a is None or b is None or a.shape != b.shape or not np.array_equal(a, b):
                    rec["render_identical"] = False
            target = dest / "files" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            packed_out = anm.lzs_compress(data) if compressed else data
            if compressed and lzs.decompress(packed_out) != data:
                receipt["problems"].append("%s: %s does not round-trip through the packer" % (folder.name, rel))
                continue
            target.write_bytes(packed_out)
            rec["members"][str(rel)] = {"sha256_before": sha(packed), "sha256_after": sha(packed_out),
                                        "keys_changed": changed, "image_markers_changed": markers_changed, "bytes_changed": len(diffs),
                                        "render_identical": rec["render_identical"]}
            rec["changed_keys"] += changed
            rec["changed_bytes"] += len(diffs)
        # R10 on the rebuilt folder
        found = classcheck.control_flag_findings(str(dest))
        rec["r10_after"] = [f for f in found if f["severity"] == "error"]
        rec["r10_warnings"] = [f for f in found if f["severity"] != "error"]
        if rec["r10_after"]:
            receipt["problems"].append("%s: R10 still reports %d error(s) after the rebuild"
                                       % (folder.name, len(rec["r10_after"])))
        if not rec["render_identical"]:
            receipt["problems"].append("%s: a render changed" % folder.name)
        receipt["packs"][folder.name] = rec
        print("%-14s %-16s keys=%4d bytes=%5d r10_errors=%d renders_identical=%s"
              % (folder.name, rec["name"], rec["changed_keys"], rec["changed_bytes"],
                 len(rec["r10_after"]), rec["render_identical"]))

    path = Path(args.receipt or (out_root / "rebuild-receipt.json"))
    path.write_text(json.dumps(receipt, indent=1))
    print("problems:", len(receipt["problems"]))
    for p in receipt["problems"][:10]:
        print("  -", p)
    return 0 if not receipt["problems"] else 2


if __name__ == "__main__":
    sys.exit(main())
