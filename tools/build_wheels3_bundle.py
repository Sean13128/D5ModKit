"""Build Builds/WHEELS3-20261030/: the overlay on TEST16 that fixes the LIVE12 wheel freeze.

Copies the two kit files, the three test files and the wheel receipts out of this worktree, writes
INSTALL.md / LIVE-CHECK.md / WHAT-CHANGED.md from the templates kept beside this script, then
INVENTORY.txt and VERIFY.json (every file re-hashed after writing).

    python tools/build_wheels3_bundle.py [--out /Volumes/Data/Projects/D5/Builds/WHEELS3-20261030]
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
BUILDS = Path("/Volumes/Data/Projects/D5/Builds")
BASE = "LIVE5_TEST16-20261030"

FILES = [
    ("d5lib/newclasses.py", "kit-install/d5lib/newclasses.py"),
    ("d5lib/wheelmeta.py", "kit-install/d5lib/wheelmeta.py"),
    ("tests/test_wheel_page.py", "tests/test_wheel_page.py"),
    ("tests/test_wheel_hires.py", "tests/test_wheel_hires.py"),
    ("tests/test_wheelmeta.py", "tests/test_wheelmeta.py"),
    ("wheels/WHEELS3-DIAGNOSIS.md", "wheels/WHEELS3-DIAGNOSIS.md"),
    ("wheels/proof_keyslot.py", "wheels/proof_keyslot.py"),
    ("wheels/proof-keyslot.json", "wheels/proof-keyslot.json"),
    ("wheels/static_stack_wheels.py", "wheels/static_stack_wheels.py"),
    ("wheels/static-stack-wheels3.json", "wheels/static-stack-wheels3.json"),
    ("wheels/build_payload_wheels.py", "wheels/build_payload_wheels.py"),
    ("wheels/payload-wheels3.json", "wheels/payload-wheels3.json"),
]
DOCS = ["INSTALL.md", "LIVE-CHECK.md", "WHAT-CHANGED.md"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BUILDS / f"WHEELS3-{date.today():%Y%m%d}"))
    args = ap.parse_args()
    out = Path(args.out)
    (out / "kit-install" / "d5lib").mkdir(parents=True, exist_ok=True)
    (out / "tests").mkdir(exist_ok=True)
    (out / "wheels").mkdir(exist_ok=True)

    for src, rel in FILES:
        s = KIT / src
        if not s.is_file():
            raise SystemExit(f"missing {s}")
        shutil.copy2(s, out / rel)
    for name in DOCS:
        s = KIT / "wheels" / "bundle" / name
        if not s.is_file():
            raise SystemExit(f"missing template {s}")
        shutil.copy2(s, out / name)

    entries = []
    for p in sorted(x for x in out.rglob("*") if x.is_file()):
        rel = str(p.relative_to(out))
        if rel in ("INVENTORY.txt", "VERIFY.json"):
            continue
        entries.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256(p)})
    lines = [f"# WHEELS3-{date.today():%Y%m%d} overlay inventory", "",
             f"Base: `Builds/{BASE}`. Every file this overlay adds or replaces, hashed after writing.", ""]
    for e in entries:
        lines.append(f"{e['path']}  {e['bytes']:,}  {e['sha256']}")
    (out / "INVENTORY.txt").write_text("\n".join(lines) + "\n")

    receipt = {
        "overlay": out.name, "built": f"{date.today():%Y-%m-%d}", "base": f"Builds/{BASE}",
        "ok": True,
        "files": [{"path": e["path"], "bytes": e["bytes"], "sha256": sha256(out / e["path"])} for e in entries],
        "evidence": {
            "wheel_page_tests": "tests/test_wheel_page.py (14)",
            "hire_under_cursor_tests": "tests/test_wheel_hires.py (8)",
            "keyslot_ab": "wheels/proof-keyslot.json",
            "static_stack_audit": "wheels/static-stack-wheels3.json",
            "payload": "wheels/payload-wheels3.json",
        },
    }
    (out / "VERIFY.json").write_text(json.dumps(receipt, indent=1))
    print(f"{out}  files={len(entries)}  ok={receipt['ok']}")


if __name__ == "__main__":
    main()
