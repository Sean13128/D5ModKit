"""Assemble the OLCOMPAT evidence bundle without shipping game data or mod content.

The working outputs under /Volumes/Data/ai-tmp hold vanilla bytes, converted patches (full table
rows) and Overlord's authored numbers. None of that belongs in the repository or in a bundle that
might travel: AGENTS.md forbids publishing game data, and Overlord's row values are Cryswar's
content. So the bundle keeps *decisions and counts*:

  conversion-report.json  per-member status, row counts, hashes, ownership findings
  arbitration.json        sites, RVAs, verdicts (no executable bytes)
  effects-verdicts.json   per-section id/label/verdict/family/reason (no values)
  receipts.json           the numbers quoted in the report

Usage:  python tools/overlord_port/bundle.py <work-dir> <bundle-dir>
"""
import json
import os
import shutil
import sys

STRIP_ARBITRATION = ("bytes",)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sanitize_conversion(report):
    out = dict(report)
    out["members"] = [{k: v for k, v in m.items()} for m in report["members"]]
    return out


def sanitize_arbitration(report):
    out = dict(report)
    out["overlap_sites"] = [{k: v for k, v in s.items() if k not in STRIP_ARBITRATION}
                            for s in report.get("overlap_sites", [])]
    return out


def sanitize_verdicts(verdicts):
    keep = ("id", "label", "verdict", "effect", "family", "reason")
    return [{k: v[k] for k in keep if k in v} for v in verdicts]


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    work, bundle = argv
    os.makedirs(bundle, exist_ok=True)
    receipts = {}
    conv = os.path.join(work, "tables-allow", "conversion-report.json")
    if os.path.exists(conv):
        report = sanitize_conversion(_load(conv))
        with open(os.path.join(bundle, "conversion-report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, ensure_ascii=False)
        receipts["tables"] = {
            "members_audited": len(report["members"]),
            "accepted": len(report["converted_members"]) + sum(
                1 for m in report["members"] if m["status"] == "convertible-unkeyed"),
            "composable": len(report["converted_members"]),
            "refused": sorted(m["table"] for m in report["members"] if m["status"] == "refused"),
            "unkeyed": sorted(m["table"] for m in report["members"]
                              if m["status"] == "convertible-unkeyed"),
            "vanilla_rows_rewritten": report["vanilla_rows_rewritten"],
            "claims": len(report["claims"]),
            "ownership_findings": len(report["findings"]),
        }
    arb = os.path.join(work, "arbitration.json")
    if os.path.exists(arb):
        report = sanitize_arbitration(_load(arb))
        with open(os.path.join(bundle, "arbitration.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        scan = report.get("release_scan") or {}
        needles = scan.get("sites") or {}
        receipts["arbitration"] = {
            "exe_sha256": report["exe_sha256"],
            "sites": report["sites"],
            "verdicts": report["verdict_counts"],
            "release_needles": len(needles),
            "release_needles_referenced": sum(1 for v in needles.values() if v["candidates"]),
            "release_needles_absent": sorted(n for n, v in needles.items() if not v["candidates"]),
        }
    ver = os.path.join(work, "effects", "evilities-verdicts.json")
    if os.path.exists(ver):
        verdicts = sanitize_verdicts(_load(ver))
        with open(os.path.join(bundle, "effects-verdicts.json"), "w", encoding="utf-8") as fh:
            json.dump(verdicts, fh, indent=1)
        summary = {}
        for v in verdicts:
            summary[v["verdict"]] = summary.get(v["verdict"], 0) + 1
        receipts["effects"] = {"sections": len(verdicts), "verdicts": summary,
                               "refused": sorted(v["label"] for v in verdicts
                                                 if v["verdict"] in ("refused", "unproven"))}
    with open(os.path.join(bundle, "receipts.json"), "w", encoding="utf-8") as fh:
        json.dump(receipts, fh, indent=1, ensure_ascii=False)
    print(json.dumps(receipts, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
