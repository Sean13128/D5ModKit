"""DRPG-INSTALLPREP1: batch lists + one pipeline spec per DRPG install batch (offline, writes only the spec/list files).

    python tools/drpg_install_spec.py --lists OUTDIR            # batchN.txt, mechanical order
    python tools/drpg_install_spec.py --spec N SPECFILE         # spec for batch N from the built packs

Batch 1 is fixed (31 bases incl. Zed 94, Noel 55, Melodia 106); the rest: clean original-art packs first, derived-art last,
chunks of 29/29/29/28.  Packs come from Builds/DRPGBUILD2-20261109 (full run, leases + quest/help ids pinned by the manifest).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/Volumes/Data/Projects/D5")
A = "Builds/DRPGBUILD2-20261109/drpg"      # the full 146 run against the used-id gate union, quest/help ids pinned (DRPG-LEASE1)
BATCH1 = [94, 55, 106, 20009, 15, 23, 46, 47, 48, 59, 63, 64, 65, 66, 67, 72, 73, 74, 77, 88, 89, 95, 99, 100,
          107, 111, 116, 117, 118, 121, 122]
REBUILT = [225, 228, 239, 240, 246, 273, 275, 276, 279, 281, 290, 302, 305, 307, 308, 310, 311, 319, 334, 337, 338,
           340, 341, 343, 347]
D1C_PAGE = [11390, 11400, 11760, 11770, 11800, 11810, 11820, 11830, 11840, 11850, 11860, 11900, 11930]


def packs():
    """{base id: (build dir, folder, derived-art?)}; the 25 re-leased bases come from the B build."""
    out = {}
    for d in (A,):
        if not (ROOT / d / "results.json").is_file():
            continue                      # the B build is not finished: batches 2-5 then lack the 25 re-leased bases
        res = json.loads((ROOT / d / "results.json").read_text())["results"]
        for r in res:
            bid = int(r["id"].split(":")[1])
            rec = json.loads((ROOT / d / "mods" / r["mod_folder"] / "CORERPG1-receipt.json").read_text())
            derived = any(l["assets"]["provenance"] != "original" for l in rec["leased_ids"]["looks"])
            out[bid] = (d, r["mod_folder"], derived)
    return out


def batches():
    p = packs()
    rest = [b for b in sorted(p) if b not in BATCH1]
    rest.sort(key=lambda b: (p[b][2], b in REBUILT, b))      # original art, clean build first; derived last
    chunks = [rest[0:29], rest[29:58], rest[58:87], rest[87:]]
    return [BATCH1] + chunks, p


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bank_rows(build, folder, kit):
    sys.path.insert(0, str(kit))
    from d5lib import anm
    rows = []
    d = ROOT / build / "mods" / folder / "files/Anime/ANM_HI_JP.dat"
    for f in sorted(d.glob("anm*.lzs")):
        a = anm.load(str(f))
        rows.append({"bank": f"mods/{folder}/files/Anime/ANM_HI_JP.dat/{f.name}", "palettes": len(a.palettes),
                     "headers": len(a.palettes) + len(a.textures), "sha256": sha(f)})
    return rows


def spec(n, kit):
    bs, p = batches()
    ids = bs[n - 1]
    folders = [f"{p[b][0]}/mods/{p[b][1]}" for b in ids]
    banks = []
    for b in ids:
        banks += [dict(r, bank=r["bank"], _build=p[b][0]) for r in bank_rows(p[b][0], p[b][1], kit)]
    for r in banks:
        r["bank"] = r["bank"]            # kit-relative path inside the pack's own build (readback resolves <build>/<bank>)
        r.pop("_build")
    return {
        "lane": f"DRPGINSTALL1-B{n}",
        "min_disk_gb": 300,
        "build": A,
        "notes": (f"DRPG batch {n} of 5 ({len(ids)} bases: {', '.join(map(str, ids))}). Prepared offline, NOT run. "
                  "Coordinator before the real run: (1) re-pin base (mods/exe) from the live kit; (2) set `kitcode` "
                  "(none written: the installed kit already carries K1-K5 outfits since KITCODE1 and is at integ-2026-11); "
                  "(3) run `python tools/drpg_batch_check.py <batch file>` (K0 lease check per batch, exit 0); (4) dry-run, "
                  "then real run; (5) layer-2: `drpgk6_steps.py` (Zed 94: quest 192 -> row 102, costume 30170 / art 14940) "
                  "after batch 1. DRPG packs carry no wheel class, so the soak page gate is the D1C wheel (LSHIFT+3) "
                  "installed by D1CDD2INSTALL1A, unchanged by this batch: a regression gate, not a DRPG page."),
        "re_pin_at_launch": "RE-PIN: base.mods and base.exe_sha256 are placeholders (expected MAIN ~154 folders after D1C+DD2)",
        "profile": {"name": "MAIN", "enable_staged": True},
        "base": {"profile": "MAIN", "mods": 154, "exe_sha256": "RE-PIN-AT-LAUNCH", "banks": {}},
        "boot": {"timeout": 300, "silent_budget": 15},
        "load": {"slot": "(01)", "units_min": 58},
        "shortcuts": {"class_swap_by_memory": True, "hp_sp_by_memory": True, "restart": "kill"},
        "folders": folders,
        "expect": {"mods_after": 154 + len(ids), "banks": banks},
        "soak": {"boots": 1, "campaigns": 2, "presses": 40, "page_keys": ["LSHIFT", "3"], "freeze_silent_s": 20,
                 "page": {"wheel": "d1c", "page_key": ["LSHIFT", "3"], "ids": D1C_PAGE, "count": 13, "min_ids": 10,
                          "derived_from": "D1CDD2INSTALL1A soak.page (same 13 ids); DRPG packs add no class descriptor"}},
        "hits": [], "crops": [], "keep_if": "all_pass",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists")
    ap.add_argument("--spec", nargs=2, metavar=("N", "FILE"))
    ap.add_argument("--kit", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args()
    if a.lists:
        bs, p = batches()
        for i, ids in enumerate(bs, 1):
            lines = [f"{b}\t{p[b][0]}/mods/{p[b][1]}\t{'derived-art' if p[b][2] else 'original-art'}" for b in ids]
            (Path(a.lists) / f"batch{i}.txt").write_text("\n".join(lines) + "\n")
            print(f"batch{i}: {len(ids)}")
    if a.spec:
        s = spec(int(a.spec[0]), a.kit)
        Path(a.spec[1]).write_text(json.dumps(s, indent=1) + "\n")
        print(a.spec[1], len(s["folders"]), "folders", len(s["expect"]["banks"]), "banks")


if __name__ == "__main__":
    main()
