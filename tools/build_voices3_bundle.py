"""VOICES3 staging: give the ten D4UNIQ3 characters (and Pringer X) their own D4 voice bank.

Reads Builds/LIVE5_TEST18B-20261030/mods (read only) and writes only the rebuilt packs into
``--out``. The D4 source row is the D4 char row in the mod name (D4_Unique_<row>); the source
voice group is that row's ``voice_group_base`` in D4's own char.dat, exactly as VOICES2 did.

Voice ids: 9130-9138, measured free against every Builds/*/mods voices.json, the installed kit's
mods and the D5 custom range (9000-9999, 9000-9044/9100-9122 already allocated).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import build_voices2_pack as B  # noqa: E402  (the VOICES2 per-pack builder, unchanged)
from d5lib import d4source  # noqa: E402

# D4UNIQ3's ten characters, in tracker order, plus the two that have no D4 bank.
PLAN = [
    ("D4_Unique_70", 70, 9130),
    ("D4_Unique_220", 220, 9131),
    ("D4_Unique_410", 410, 9132),
    ("D4_Unique_420", 420, 9133),
    ("D4_Unique_430", 430, 9134),
    ("D4_Unique_440", 440, 9135),
    ("D4_Unique_450", 450, 9136),
    ("D4_Unique_460", 460, 9137),
    ("D4_Unique_470", 470, 9138),
]
# No D4 recording exists for these two (evidence: VOICES3-REPORT.md §2).  VOICES3 left them on their D5 donor voice;
# Sean (2026-11-12 15:29) ruled they are silent like the source: tools/stage_d4_silent.py (VOICESILENT1) links them to
# the voice without lines and labels them "silent, as in the source game".
NO_BANK = [("D4_Unique_610", 610), ("D4_Unique_210", 210)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", type=Path, required=True, help="TEST18B mods folder (read only)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    d4 = d4source.D4Data(B.D4, "EN")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    inventory = []
    for name, row_id, vid in PLAN:
        pack = args.mods / name
        if not pack.is_dir():
            raise SystemExit(f"missing pack {pack}")
        row = d4.chars[row_id]
        expected_group = row["voice_group_base"]
        rec = B.build(pack, out / name, vid, d4)
        clips = sum(len(r["clips"]) for r in rec["receipts"])
        routed = sum(1 for r in rec["receipts"] for c in r["clips"] if c["status"] != "unrouted-placeholder")
        print(f"{name:16s} D4 row {row_id:3d} group {expected_group:4d} -> voice {vid}  "
              f"clips {clips} routed {routed}")
        inventory.append(rec)
    for name, row_id in NO_BANK:
        row = d4.chars[row_id]
        inventory.append(dict(pack=name, source=dict(kind="unique", row=row_id),
                              voice_group_base=row["voice_group_base"],
                              status="no-d4-bank", character=row["name"]))
        print(f"{name:16s} D4 row {row_id:3d} group {row['voice_group_base']:4d} -> NO D4 BANK (unchanged)")
    (out.parent / "VOICES3-INVENTORY.json").write_text(json.dumps(inventory, indent=1))
    print("packs built:", sum(1 for r in inventory if "receipts" in r))


if __name__ == "__main__":
    main()
