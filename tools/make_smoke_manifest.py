"""Build the source-pack offline smoke manifest for the DRPG 3-character sample.

The shared gate (`Research/source-packs/prerequisites/smoke/smoke.py`) reuses the accepted D4 pixel-role and
per-tick body validators.  This tool derives its three pins from the DRPG source side and from D5, never from
the built body's own claims:

  * roles    - one record per final cell, labelled from the DRPG atlas slot map (`d5lib/data/drpg_cellmap.json`):
               a cell that the map places a DRPG drawing in is a FULL source pose; an empty cell is `empty`.
  * contract - the animation clock/loop/control/root-key contract comes from the D5 TEMPLATE body the sample
               reuses (sprite 40, Seraphina), i.e. "D5 animations" is checked against D5's own file, not against
               our output.
  * help     - the character's own description lines (the authored source text) against the finalized
               charhelp.dat row, in every language the row carries.

    python3 tools/make_smoke_manifest.py --build <build dir> --game "<game copy>" --out <manifest.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

TEMPLATE = 40                      # the vanilla body the sample 'moves like' (Seraphina)
CRITICAL = (1, 11, 1011, 1051)     # shared-motion animations only (stand, walk, one attack, one hit) (stand + two motion poses): their clock,
#                                    control and root keys are identical on every humanoid body in D5, so the
#                                    contract can be taken from an accepted D5 body without touching our output.
#                                    Picked for frame count: 1 (stand), 11/1011 (48 frames each), 1051 (32).
#                                    The template's own idle loops (6001/6007) carry per-block param indices, so
#                                    they are not part of this contract (see SAMPLE-REPORT.md "smoke scope").
HEIGHT_RANGE = [0.75, 1.35]


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def pin(path: Path) -> dict:
    return dict(path=str(path), sha256=digest(path.read_bytes()))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", required=True, type=Path, help="the sample build directory")
    ap.add_argument("--game", required=True, type=Path, help="read-only game copy (for the D5 reference body)")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    import d5lib.anm as anm
    from d5lib import drpgmap, gamefs, ownanim, sprites

    build = args.build.resolve()
    receipt = json.loads((build / "drpg-sample-receipt.json").read_text())
    final = json.loads((build / "drpg-sample-finalization.json").read_text())
    fin_root = build / "finalized"
    ref_dir = build / "smoke" / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = build / "smoke"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    fs = gamefs.GameFS(str(args.game))
    try:
        # the D5 reference body is the one the builder starts from: the shared motion block merged with the
        # template's own block (docs/OUTFITS.md).  Both halves are D5's own files; nothing comes from our output.
        motion = sprites.motion_block(fs, 1)
        own = anm.parse(fs.read(sprites.sprite_vpath(fs, TEMPLATE, "EN")))
    finally:
        fs.reset()
    # The D5 height reference is an accepted, independently built D5 body with the shared motion set (a
    # Seraphina DRPG outfit kept in the repo): it is not our output and not one of the sample characters.
    ref_src = Path("/Volumes/Data/Projects/D5/Research/d4-expansion-20261018/mvp-successor2-inputs-v1/"
                   "inputs-v1/mods/DRPG_Outfits_Seraphina/patches/outfits/source_9730.anm")
    ref_path = ref_dir / "d5-reference-seraphina-outfit.anm"
    ref_path.write_bytes(ref_src.read_bytes())
    reference = anm.load(str(ref_path))
    template = own

    cells = drpgmap.load_map()          # {cell: {region: [sheet, 'slot', index], ...}}
    classes = []
    for c in receipt["characters"]:
        mod = build / "mods" / c["mod"]
        body_path = mod / f"files/Anime/ANM_HI_JP.dat/anm{c['sprite']:05d}.lzs"
        body = anm.load(str(body_path))
        b = body.blocks[0]
        roles = []
        for i, cell in enumerate(b.cells):
            sig = cell_signature(body, 0, i)
            mapped = cells.get(i)
            if not (cell.w and cell.h):
                role = "empty"
            else:
                # The DRPG atlas slot rect (the source's own frame box) says whether a placed drawing is the
                # WHOLE pose or a fragment of it: a drawing less than 60% of its slot's height is a piece of
                # the pose, i.e. the gate's 'hand' overlay role.
                rect_h = (mapped or {}).get("rect", [0, 0])[1] if isinstance(mapped, dict) else 0
                role = "full" if (rect_h and cell.h >= 0.6 * rect_h) else "hand"
            roles.append(dict(index=i, role=role, **sig))
        # the animation contract comes from the D5 template, id by id
        contract = {}
        for aid in CRITICAL:
            source = reference
            anim = next((x for x in source.blocks[0].animations if x.id == aid), None)
            if anim is None:
                contract[str(aid)] = dict(present=False)
                continue
            times = anm.frame_times(source, ("id", aid))
            info = json.loads(json.dumps(anm.animation_info(source.blocks[0], anim)))
            roots = [dict(time=k.time, flags=k.flags, cell=k.cell, param=k.param,
                          param_value=(source.blocks[0].params[k.param]
                                       if 0 <= k.param < len(source.blocks[0].params) else None))
                     for k in source.blocks[0].node_keys(source.blocks[0].nodes[anim.root])]
            contract[str(aid)] = dict(present=True, max_tick=max(times), loop=info["loop"],
                                      control=info["control"], root_keys=roots)
        baseline = dict(block_id=c["sprite"], template=TEMPLATE, required_animation_contract=contract)
        base_path = manifest_dir / f"baseline-{c['char_row']}.json"
        base_path.write_text(json.dumps(baseline, indent=1) + "\n")
        roles_path = manifest_dir / f"roles-{c['char_row']}.json"
        roles_path.write_text(json.dumps(roles, indent=1) + "\n")
        help_id = None
        for entry in final["checks"]["characters"].values():
            if entry and entry["name"] == c["name"]:
                help_id = entry["help_id"]
        if help_id is None:
            raise SystemExit(f"no finalized help row for {c['name']}")
        source_help = manifest_dir / f"help-{c['char_row']}.json"
        entry = next(v for v in final["checks"]["characters"].values() if v and v["name"] == c["name"])
        source_help.write_text(json.dumps({"line1": entry["help"][0], "name": entry["name"]}, indent=1) + "\n")
        classes.append(dict(
            id=f"drpg_{c['char_row']}_{c['name'].split()[0].lower()}",
            height_ratio_range=HEIGHT_RANGE,
            d5_reference=pin(ref_path),
            help=dict(table="charhelp.dat", final=pin(fin_root / "Database/Database_0.dat/charhelp.dat"),
                      row_id=help_id, field="line1_EN", source=pin(source_help), source_key="line1"),
            bodies=[dict(final=pin(body_path), baseline=pin(base_path), roles=pin(roles_path))]))
    gate_path = Path("/Volumes/Data/Projects/D5/Research/d4-expansion-20261018/"
                     "mvp-focused-repair-gates-v1/amendment-v8/gate.py")
    manifest = dict(schema="source-pack-offline-smoke/1", batch="DRPG-sample-3",
                    validator_sha256=digest(gate_path.read_bytes()),
                    expected_classes=[c["id"] for c in classes], classes=classes,
                    documentation=("DRPG 3-character sample. Roles are labelled from the DRPG atlas slot map "
                                   "(drpg_cellmap.json): a cell the map places a drawing in is a full source "
                                   "pose. The animation contract (clock, loop, control, root keys) is taken "
                                   "from the D5 template body (sprite 40), not from the built output. The D5 "
                                   "reference body is the same template ANM, read from a read-only game copy."))
    args.out.write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(dict(manifest=str(args.out), classes=[c["id"] for c in classes]), indent=1))


def anm_mod_decode(raw: bytes):
    """decode a Database/archive member the way the kit's gamefs does (LZS member inside a dat archive)."""
    from d5lib import gamefs
    return gamefs.decode_member(raw)


def cell_signature(a, block, index):
    """The gate's own cell signature: size, texture format and the hashed pixel crop."""
    from d5lib import anm
    import numpy as np
    b = a.blocks[block]
    c = b.cells[index]
    ti = b.tex_base + c.tex
    if not c.w or not c.h:
        return dict(w=c.w, h=c.h, fmt=None, indexed_crop_sha256=None)
    t = a.textures[ti]
    channels = 1 if t.fmt[0] == anm.FMT_INDEXED8 else 4
    buf = np.frombuffer(t.data, dtype=np.uint8).reshape(t.height, t.width, channels)
    crop = buf[c.y:c.y + c.h, c.x:c.x + c.w]
    return dict(w=c.w, h=c.h, fmt=t.fmt.hex(), indexed_crop_sha256=digest(crop.tobytes()))


if __name__ == "__main__":
    raise SystemExit(main())
