"""K0 gate per install batch: every built pack in a batch file carries exactly the ids the lease manifest gives it.

    python tools/drpg_batch_check.py BATCHFILE [--extra-mods DIR ...] [--leases-from FILE ...]

Exit 0 only if (1) each pack's receipt row/sprite/costume ids equal its lease, (2) no anm number >= 32768,
(3) no id is shared by two packs of the batch, (4) a pack with costumes requires Outfit_System, and (5) `drpg_leases check`
(with the same extra roots / lease files) is clean.  Reads only.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path("/Volumes/Data/Projects/D5")
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from d5lib.importers import drpg_leases as L  # noqa: E402


def check_batch(lines, manifest, root=ROOT):
    bases, costumes = L.index(manifest)
    problems, rows, arts = [], {}, {}
    for ln in lines:
        bid, rel = ln.split("\t")[:2]
        pack = root / rel
        lease = bases.get(f"drpg:{bid}")
        if lease is None:
            problems.append(f"drpg:{bid}: no lease")
            continue
        rec = json.loads((pack / "CORERPG1-receipt.json").read_text())["leased_ids"]
        if rec["row"] != lease["class_id"] or rec["sprite"] != lease["art"]:
            problems.append(f"drpg:{bid}: pack row/sprite {rec['row']}/{rec['sprite']} != lease "
                            f"{lease['class_id']}/{lease['art']}")
        rows.setdefault(rec["row"], []).append(bid)
        for c in costumes.values():
            if c["owner"] == lease["lease"]:
                arts.setdefault(c["art"], []).append(bid)
                if not (pack / f"files/Anime/ANM_HI_JP.dat/anm{c['art']}.lzs").is_file():
                    problems.append(f"drpg:{bid}: costume {c['lease']} art {c['art']} missing in the pack")
        arts.setdefault(lease["art"], []).append(bid)
        for f in (pack / "files/Anime/ANM_HI_JP.dat").glob("anm*.lzs"):
            m = re.match(r"anm(\d+)\.lzs", f.name)
            if m and int(m.group(1)) >= 32768:
                problems.append(f"drpg:{bid}: {f.name} >= 32768")
        has_costumes = any(c["owner"] == lease["lease"] for c in costumes.values())
        if has_costumes and "Outfit_System" not in (json.loads((pack / "mod.json").read_text()).get("requires") or []):
            problems.append(f"drpg:{bid}: pack does not require Outfit_System")
    problems += [f"row {k} used by {v}" for k, v in rows.items() if len(v) > 1]
    problems += [f"art {k} used by {v}" for k, v in arts.items() if len(v) > 1]
    return problems


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    lines = [x for x in Path(argv[0]).read_text().splitlines() if x.strip()]
    manifest = L.load()
    problems = check_batch(lines, manifest)
    rc = L.main(["check", *argv[1:]])
    for p in problems:
        print("PROBLEM", p)
    print(f"{len(lines)} packs, {len(problems)} pack problems, lease check exit {rc}")
    return 1 if (problems or rc) else 0


if __name__ == "__main__":
    raise SystemExit(main())
