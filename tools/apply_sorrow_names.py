"""SCHEMA1: apply Sorrow's VERIFIED field names to d5lib/schemas/{char,Quest,item,JobRank}.json.

Offline, idempotent.  A rename keeps offset/type/width; the old name stays loadable through "aliases" (database.Schema.alias),
so mod packs built before the rename still apply.  Every other field whose Sorrow entry disagrees gets a "candidate" note
(Sorrow name + confidence) when Sorrow is PROBABLE, or VERIFIED against a kit field the kit itself rated low/medium;
Sorrow VERIFIED vs a kit 'high' field of the same notion, and UNKNOWN entries, add nothing.  Source: community/sorrow/research-20261014/database_fields.json.
"""
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SORROW = Path("/Volumes/Data/Projects/D5/Private/Overlord and Sorrow research/community/sorrow/research-20261014/database_fields.json")
TABLES = {"char": "char.dat", "Quest": "Quest.dat", "item": "item.dat", "JobRank": "JobRank.dat"}

# kit offset -> new name: only fields the kit left unnamed (unk_*) or guessed (req_extra, low) where Sorrow is VERIFIED
# at the same offset and the same notion; kit type and width stay.
RENAMES = {
    "char": {202: "torture_id", 224: "exp_yield_weight", 900: "is_unique"},
    "Quest": {308: "exclude_flag_id", 312: "min_level", 4792: "objective_param_2", 4796: "objective_param_3",
              5604: "bounty_target_mode", 5608: "bounty_target_char_id", 5612: "bounty_drop_item_id",
              5616: "bounty_drop_permille", 5620: "bounty_stage_id", 5624: "mode_restriction"},
    "item": {}, "JobRank": {},
}


def sorrow_at(fields):
    out = {}
    for x in fields:
        w = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4, "u64": 8, "i64": 8}.get(x["type"])
        n = x.get("count") or 1
        if w is None:                                  # char[N] strings: whole block only
            continue
        for i in range(n):
            out[x["offset"] + i * w] = (x["name"], i if n > 1 else None, x["confidence"], x["type"])
    return out


def main():
    sor = {t["table"]: t.get("fields", []) for t in json.load(open(SORROW))}
    summary = {}
    for stem, tn in TABLES.items():
        p = KIT / "d5lib" / "schemas" / f"{stem}.json"
        raw = p.read_text(encoding="utf-8")
        d = json.loads(raw)
        so = sorrow_at(sor[tn])
        ren = cand = 0
        for f in d["fields"]:
            s = so.get(f["offset"])
            new = RENAMES[stem].get(f["offset"])
            if new:
                assert s and s[2] == "VERIFIED" and new.startswith(s[0]), (stem, f, s)
                if f["name"] != new:
                    f.setdefault("aliases", []).append(f["name"])
                    f["name"] = new
                    ren += 1
                f["confidence"] = "high"
                f["candidate"] = f"Sorrow {s[0]}{'' if s[1] is None else '[%d]' % s[1]} {s[2]}; kit type {f['type']} kept (Sorrow {s[3]})"
                continue
            if (s and not s[0].startswith(("unk_", "pad")) and f["name"] != s[0]
                    and (s[2] == "PROBABLE" or (s[2] == "VERIFIED" and f.get("confidence") in ("low", "medium")))):
                f["candidate"] = f"Sorrow {s[0]}{'' if s[1] is None else '[%d]' % s[1]} {s[2]}"
                cand += 1
        p.write_text(json.dumps(d, indent=1, ensure_ascii=False) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
        summary[stem] = (ren, cand)
    print(summary)


if __name__ == "__main__":
    sys.exit(main())
