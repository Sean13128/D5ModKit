"""Build and run the source-pack offline smoke for the converted character.

smoke.py (Research/source-packs/prerequisites/smoke) is the project's offline gate for an imported
character body: exact help text, cell-role correspondence, the animation clock contract, one full pose
per tick, and figure height against a D5 reference.  It wants a manifest whose entries point at
finalized artifacts, so this script

  1. finalizes the mod again (in memory) and writes the finalized charhelp.dat to a private folder,
  2. derives the body's role list and animation contract from the shipped member,
  3. writes the manifest, then runs smoke.py --out <dir>.

  PYTHONDONTWRITEBYTECODE=1 python3 tools/overlord_port/smoke_manifest.py <mod-dir> <work-dir>
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess

import numpy as np
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
PROJECT = Path("/Volumes/Data/Projects/D5")
sys.path.insert(0, str(KIT))

from d5lib import anm, database, gamefs, modsys  # noqa: E402
from d5lib.d4unique import Originals  # noqa: E402

GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = PROJECT / "D5Modkit/state/games/Disgaea_5_Complete-d8040a88"
SMOKE = PROJECT / "Research/source-packs/prerequisites/smoke/smoke.py"
D4_GATE = PROJECT / "Research/d4-expansion-20261018/mvp-focused-repair-gates-v1/amendment-v8/gate.py"
# the D5 humanoid clock the bodies are drawn on: the accepted D4_Class_1190 bank from the build tree (not the
# installed copy, which another lane may be rewriting)
CLOCK = (PROJECT / "Research/d4-expansion-20261018/mvp-focused-repair-build-v1/run-2/imports/D4_Class_1190/"
         "native-mods/D4_Class_1190/files/Anime/ANM_HI_JP.dat/anm01460.lzs")
# defaults are P4's Stella lease; OLCONV2 reads body / help id / source id from the mod itself (read_mod_facts)
BODY, CUTIN, HELP_ID, SOURCE_ID, LABEL = 224, 10224, 22682, None, "overlord_stella_224"
RELEASE_DB = Path("/Volumes/Data/ai-tmp/claude/overlord-v3/mods/Overlord/Database/Database_0")


def read_mod_facts(mod):
    """body bank, help id and the source's own help row, from the finished mod folder (unique.json + char/help patches)"""
    global BODY, CUTIN, HELP_ID, SOURCE_ID, LABEL
    u = json.loads((mod / "patches/characters/unique.json").read_text())
    meta = json.loads((mod / "mod.json").read_text())
    BODY, CUTIN = int(u["physical"]), 10000 + int(u["physical"])
    char = json.loads((mod / "patches/db/char.dat.json").read_text())["added"][0]
    HELP_ID = int(char["help_id"])
    SOURCE_ID = int(meta["source_import"]["source"]["character_id"])
    LABEL = f"overlord_{u['name'].lower()}_{BODY}"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def gate_sig(a, i):
    """the gate's own cell signature, so the role file cannot drift from its reader."""
    spec = importlib.util.spec_from_file_location("d4_gate", D4_GATE)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g.cell_signature(a, 0, i), g.signature_key


def _visible(a, aid, tick, cache):
    """the gate's own visibility rule, so a role cannot claim a pose the gate cannot see."""
    out = []
    for it in anm.evaluate(a, ("id", aid), tick, nested=True):
        c = it.cell
        if not c.w or not c.h or it.color[3] <= 0:
            continue
        q = np.asarray(it.quad)
        v, w = q[1] - q[0], q[3] - q[0]
        if abs(v[0] * w[1] - v[1] * w[0]) < 1e-6:
            continue
        im = anm._cell_image(a, it, 0, cache)
        if im is None or im.getchannel("A").getextrema()[1] <= 0:
            continue
        out.append(it.key.cell)
    return out


def roles_for(a, ids=(1, 7, 6001, 1001)):
    """one 'full' cell per rendered tick (the largest drawn cell), every other drawn cell 'hand'.

    The gate refuses two full poses at one tick, which is what a body-plus-prop frame looks like unless
    the extra cells are declared as parts.
    """
    b = a.blocks[0]
    cache = {}
    full = set()
    for aid in ids:
        for tick in range(max(anm.frame_times(a, ("id", aid))) + 1):
            shown = _visible(a, aid, tick, cache)
            if shown:
                full.add(max(shown, key=lambda c: b.cells[c].w * b.cells[c].h))
    cells = []
    for i, c in enumerate(b.cells):
        sig, key = gate_sig(a, i)
        rec = dict(index=i, w=sig["w"], h=sig["h"], fmt=sig["fmt"],
                   indexed_crop_sha256=sig["indexed_crop_sha256"], flags=c.flags, unk2=c.unk2,
                   unk8=c.unk8, pal=c.pal)
        rec["role"] = "empty" if not c.w or not c.h else ("full" if i in full else "hand")
        cells.append(rec)
    return cells


def contract_for(a, ids):
    out = {}
    b = a.blocks[0]
    for aid in ids:
        an = next(x for x in b.animations if x.id == aid)
        info = json.loads(json.dumps(anm.animation_info(b, an)))
        times = anm.frame_times(a, ("id", aid))
        roots = [dict(time=k.time, flags=k.flags, cell=k.cell, param=k.param,
                      param_value=b.params[k.param] if 0 <= k.param < len(b.params) else None)
                 for k in b.node_keys(b.nodes[an.root])]
        out[str(aid)] = dict(present=True, max_tick=max(times), loop=info["loop"], control=info["control"],
                             root_keys=roots)
    return out


def main():
    mod = Path(sys.argv[1]).resolve()
    work = Path(sys.argv[2]).resolve()
    read_mod_facts(mod)
    work.mkdir(parents=True, exist_ok=True)
    fin = (work / "final")
    fin.mkdir(exist_ok=True)

    fs = gamefs.GameFS(str(GAME), backup_resolver=Originals(STATE))
    try:
        ctx = modsys.build(fs, [modsys.Mod(str(mod))], log=lambda s: None)
        (fin / "charhelp.dat").write_bytes(ctx.get("Database/Database_0.dat/charhelp.dat"))
        help_t = database.load_table("charhelp.dat", (fin / "charhelp.dat").read_bytes())
        hrow = help_t.find(HELP_ID)
    finally:
        fs.reset()

    bodies = []                                          # both body banks (N and N+1) go through the gate
    for off in (0, 1):
        bid = BODY + off
        body_path = mod / f"files/Anime/ANM_HI_JP.dat/anm{bid:05d}.lzs"
        body = anm.load(str(body_path))
        roles = roles_for(body)
        contract = contract_for(body, (1, 7, 6001, 1001))
        (work / f"roles-{bid}.json").write_text(json.dumps(roles, indent=1) + "\n")
        (work / f"baseline-{bid}.json").write_text(json.dumps(dict(block_id=bid, required_animation_contract=contract),
                                                           indent=1) + "\n")
        bodies.append(dict(final=dict(path=str(body_path), sha256=sha(body_path.read_bytes())),
                           baseline=dict(path=str(work / f"baseline-{bid}.json"),
                                         sha256=sha((work / f"baseline-{bid}.json").read_bytes())),
                           roles=dict(path=str(work / f"roles-{bid}.json"),
                                      sha256=sha((work / f"roles-{bid}.json").read_bytes()))))
        if off == 0:
            first_body = body

    ref_path = work / "d5-reference-anm01460.lzs"      # a copy: the smoke refuses symlinked paths
    ref_path.write_bytes(CLOCK.read_bytes())
    ref = anm.load(str(ref_path))
    h_ref = anm.render_frame(ref, ("id", 1), 0, 0).getchannel("A").getbbox()
    h_our = anm.render_frame(first_body, ("id", 1), 0, 0).getchannel("A").getbbox()
    ratio = (h_our[3] - h_our[1]) / (h_ref[3] - h_ref[1])
    # the gate compares ONE source string with one row field; line 1 goes through the gate, the second
    # line is checked here with the gate's own text rules, and the source's third line is empty
    # the SOURCE text, read from Overlord's own charhelp.dat: a final row that drifts from it fails the gate
    # (P4 compared the final row with a copy of itself, which cannot fail)
    shelp = database.load_table("charhelp.dat", (RELEASE_DB / "charhelp.dat").read_bytes()).find(SOURCE_ID)
    src_help = {"line1_EN": shelp["line1_EN"], "line2_EN": shelp["line2_EN"], "line3_EN": shelp["line3_EN"]}
    for k in ("line2_EN", "line3_EN"):
        if hrow[k] != shelp[k]:
            raise SystemExit(f"final help {k} differs from the source: {hrow[k]!r} vs {shelp[k]!r}")
    (fin / "source-help.json").write_text(json.dumps(src_help, indent=1) + "\n")
    spec = importlib.util.spec_from_file_location("d4_smoke", SMOKE)
    smoke_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke_mod)
    smoke_mod.text_gate(shelp["line2_EN"], hrow["line2_EN"])
    help_check = dict(line1="gate", line2="gate text rules (no developer markers)", line3="empty in source")

    manifest = {
        "schema": "source-pack-offline-smoke/1",
        "batch": f"OLCONV2 {mod.name}",
        "validator_sha256": sha(D4_GATE.read_bytes()),
        "expected_classes": [LABEL],
        "classes": [{
            "id": LABEL,
            "height_ratio_range": [0.75, 1.35],
            "d5_reference": {"path": str(ref_path), "sha256": sha(ref_path.read_bytes())},
            "help": {"table": "charhelp.dat",
                     "final": {"path": str(fin / "charhelp.dat"), "sha256": sha((fin / "charhelp.dat").read_bytes())},
                     "row_id": HELP_ID, "field": "line1_EN",
                     "source": {"path": str(fin / "source-help.json"),
                                "sha256": sha((fin / "source-help.json").read_bytes())},
                     "source_key": "line1_EN"},
            "bodies": bodies,
        }],
        "help_check": help_check,
        "documentation": ("OLCONV2: Overlord v3 character converted into a Kit mod.  Height range "
                          f"0.75-1.35 against the D5 humanoid clock; measured ratio {ratio:.3f}.  The body "
                          "is the source art on the D5 animation clock (138 ids), so the contract names the "
                          "stand/idle ids the gate requires."),
    }
    man = work / "smoke-manifest.json"
    man.write_text(json.dumps(manifest, indent=1) + "\n")
    out = work / "smoke-out"
    if out.exists():
        import shutil
        shutil.rmtree(out)
    r = subprocess.run([sys.executable, str(SMOKE), str(man), "--out", str(out)], capture_output=True, text=True)
    print(json.dumps(dict(exit=r.returncode, stdout=r.stdout.strip()[-2000:], stderr=r.stderr.strip()[-2000:],
                          measured_ratio=round(ratio, 3), manifest=str(man)), indent=1))


if __name__ == "__main__":
    main()
