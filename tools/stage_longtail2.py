#!/usr/bin/env python3
"""LONGTAIL2: stage the DD2 packs whose innate evility row LONGTAIL2 adds (Xenolith 941, Baal Slave 640), table files only (offline).

    python tools/stage_longtail2.py OUT_DIR PACK[,PACK] BASE_MODS [BASE_MODS ...]

Same procedure and checks as tools/stage_d4sig1.py (clone from the FIRST base that has the pack, run _dd2_innates.apply on the clone,
refuse any non-table difference, bases must not change).  Put the staged voice build first for Xenolith.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_d4sig1 as stage                      # noqa: E402

if __name__ == "__main__":
    out, packs, bases = sys.argv[1], sys.argv[2].split(","), sys.argv[3:]
    stage.D4, stage.DD2 = (), tuple(packs)
    rc = stage.main([out, *bases])
    receipt = Path(out) / "STAGE-RECEIPT.json"
    doc = json.loads(receipt.read_text())
    doc["lane"] = "LONGTAIL2"
    receipt.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    sys.exit(rc)
