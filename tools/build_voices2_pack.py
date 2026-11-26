"""VOICES2 builder: rebuild a D4-imported pack's voice bank from the D4 install, all roles.

Offline. Reads the user's D4 install read-only; writes only inside the given output mod folder.

Role map (D4 source category -> D5 destination), evidence in docs/VOICES2.md:
  0  attack           -> kind 0, situations [0]
  2  cast             -> kind 0, situations [4]
  4  cast release     -> kind 0, situations [9]
  5  lift             -> kind 0, situations [10]
  6  throw            -> kind 0, situations [11]
  7  move / landing   -> kind 0, situations [13]
  1  skill shout A    -> kind 0, situations [1, 2]
  3  skill shout B    -> kind 0, situations [6]
  8, 9, 10, 11        -> unrouted (no established D5 destination; see the report)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import d4source, d4voices, modsys, voices  # noqa: E402

D4 = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+")

ROLE_MAP = {
    0: [dict(kind=0, cats=[0], role="attack")],
    2: [dict(kind=0, cats=[4], role="cast")],
    4: [dict(kind=0, cats=[9], role="cast release")],
    5: [dict(kind=0, cats=[10], role="lift")],
    6: [dict(kind=0, cats=[11], role="throw")],
    7: [dict(kind=0, cats=[13], role="move")],
    1: [dict(kind=0, cats=[1, 2], role="skill shout A")],
    3: [dict(kind=0, cats=[6], role="skill shout B")],
}


def event_map():
    return {str(k): v for k, v in ROLE_MAP.items()}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def char_rows(pack):
    data = json.loads((pack / "patches/db/char.dat.json").read_text())
    return data, data.get("added", [])


def source_ids(pack):
    name = pack.name
    m = re.fullmatch(r"D4_Class_(\d{4})", name)
    if m:
        return dict(kind="class", base=int(m.group(1)))
    if name == "D4_ArmorKnight_1080_PILOT":
        return dict(kind="class", base=1080)   # the deployable Armor Knight pack (D5 rows 303-308)
    m = re.fullmatch(r"D4_Unique_(\d+)", name)
    if m:
        return dict(kind="unique", row=int(m.group(1)))
    return None


def build(pack, out, voice_id, d4):
    info = source_ids(pack)
    if info is None:
        raise ValueError(f"not a D4 pack: {pack.name}")
    if info["kind"] == "class":
        row = d4.chars[info["base"]]
        base = row["voice_group_base"]
        groups = [base, base + 1, base + 2]
    else:
        row = d4.chars[info["row"]]
        base = row["voice_group_base"]
        groups = [base]          # a story character has one recorded set, one personality
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(pack, out)
    for f in (out / "patches/voices").glob("*") if (out / "patches/voices").exists() else []:
        f.unlink()
    src = d4
    receipts = []
    for lang in ("EN", "JP"):
        r = d4voices.import_d4_voice(modsys.Mod(str(out)), src, voice_id=voice_id, groups=groups, event_map=event_map(),
                                     source_language=lang, destination_language=lang)
        receipts.append(r)
    data, rows = char_rows(out)
    touched = 0
    for r in rows:
        r["voice_id"] = voice_id
        touched += 1
    for row_id, r in (data.get("rows") or {}).items():
        r["voice_id"] = voice_id
        touched += 1
    if not touched:
        raise ValueError(f"{out.name}: no char row to carry voice {voice_id}")
    (out / "patches/db/char.dat.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return dict(pack=pack.name, kind=info["kind"], source=info, groups=groups, voice_id=voice_id,
                receipts=receipts,
                files=sorted(p.name for p in (out / "patches/voices").iterdir()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--voice-id", type=int, required=True)
    ap.add_argument("--receipt", type=Path)
    a = ap.parse_args()
    d4 = d4source.D4Data(D4, "EN")
    receipt = build(a.pack, a.out, a.voice_id, d4)
    text = json.dumps(receipt, indent=1)
    if a.receipt:
        a.receipt.write_text(text)
    print(json.dumps({k: v for k, v in receipt.items() if k != "receipts"}, indent=1))
    total = sum(len(r["clips"]) for r in receipt["receipts"])
    unrouted = sum(1 for r in receipt["receipts"] for c in r["clips"] if c["status"] != "converted-adapted")
    print("clip records:", total, "routed:", total - unrouted, "unrouted:", unrouted)


if __name__ == "__main__":
    main()
