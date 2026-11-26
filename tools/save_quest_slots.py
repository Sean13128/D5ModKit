"""DRPG-SAVESLOT1: which quest progress slots are not 'never touched' in the saves of a SaveData folder.

    python tools/save_quest_slots.py SAVEDATA_DIR [--out dirty-slots.json]

Reads every *.sav (not SystemSave) with d5lib.savegame.  A slot is dirty when completed, accepted or seen is non-zero in
any save.  Output JSON: {"generated": date, "source": dir, "saves": [...], "slots": {"<slot>": {"<save>": [completed, accepted, seen]}}}.
The DRPG lease allocator reads this file (--dirty-slots); importers never open saves themselves.  Never point it at a live SaveData:
use the backup copy.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True


def survey(save_dir):
    from d5lib import savegame
    saves, slots = [], {}
    for f in sorted(Path(save_dir).glob("*.sav")):
        if f.name.startswith("SystemSave"):
            continue
        s = savegame.Save(str(f))
        saves.append(f.name)
        for q in range(savegame.QUEST_SLOTS):
            st = s.quest_state(q)
            if any(st):
                slots.setdefault(str(q), {})[f.stem] = list(st)
    return {"generated": time.strftime("%Y-%m-%d"), "source": str(save_dir), "saves": saves, "slots": slots}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("save_dir", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    doc = survey(a.save_dir)
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(text)
    print(f"{len(doc['saves'])} saves, {len(doc['slots'])} dirty slots" + (f" -> {a.out}" if a.out else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
