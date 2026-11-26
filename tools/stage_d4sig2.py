#!/usr/bin/env python3
"""D4SIG2: stage the eight D4 packs whose signature-evility rows or labels D4SIG2 changes, table files only (offline).

    python tools/stage_d4sig2.py OUT_DIR BASE_MODS [BASE_MODS ...]

Same procedure and checks as tools/stage_d4sig1.py (clone from the first base that has the pack, run the importer's own
d4.Importer._reviewed_evilities on the clone, refuse any non-table difference, bases must not change).
New row: D4_Class_2090 Stone Statue 27807.  Label-only changes: Death, Hugo, Gig, Marona, Ash, Mystic Beast, Pringer X.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_d4sig1 as stage                      # noqa: E402

stage.D4 = ("D4_Class_2090", "D4_Class_2120", "D4_Class_2130", "D4_Unique_170", "D4_Unique_210", "D4_Unique_340",
            "D4_Unique_440", "D4_Unique_450")

if __name__ == "__main__":
    rc = stage.main(sys.argv[1:])
    receipt = Path(sys.argv[1]) / "STAGE-RECEIPT.json"
    doc = json.loads(receipt.read_text())
    doc["lane"] = "D4SIG2"
    receipt.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    sys.exit(rc)
