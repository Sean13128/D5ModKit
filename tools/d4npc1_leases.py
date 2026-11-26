"""D4-NPC1: write the shared-art leases and donor learn rows for the unsupported D4 roster rows.

The 25 rows D4FIX/D4-ROSTER1 listed as "not in the importer" were split by D4GAP1:
9 built on their own art window (leases already in `d4-leases.json`), 16 closed with a reason.
This tool re-opens the shareable ones as characters of their own on an *owner's* art
(`share_art_with`): same D4 body the row wears, own identity, name, title, stats, learn list,
voice set and recruitment quest.  Nothing is written at a new art window and nothing is drawn
from a copy of a bank: the char row points at the owner's sprite/colour keys.

Owner choices (one table, data-driven where the source decides):
  * a D4 class the Kit already builds  -> that class pack (`D4_Class_<sid>`), its bank 0
  * a D5 / Kit vanilla class           -> that class's rank-0 row
  * a leased D4 unique                 -> that unique's physical art row
  * no art anywhere (Beast Master, Onmyo Monk are D4 bodies no pack carries) -> left closed

Run:  .venv-macos/bin/python tools/d4npc1_leases.py [--check]
It only rewrites `d5lib/importers/d4-leases.json` and `d5lib/sourcemaps/d4.json`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEASES = ROOT / "d5lib/importers/d4-leases.json"
SOURCEMAP = ROOT / "d5lib/sourcemaps/d4.json"

# source row -> how it is built.  template: the vanilla D5 row whose gameplay fields fill in
# (body type and motion set); owner: mod / vanilla class whose art the row wears.
ROWS = {
    # Senator row:  D4 body (sprite)  owner kind               template (vanilla D5 row)
    4300: dict(owner="D4_Class_1080", sprite=1340, colour=1340, template=1150),   # Armor Knight
    4310: dict(owner=None, d5_class=1110, template=1110),                          # Archer
    4320: dict(owner=None, d5_class=1130, template=1130),                          # Ninja
    4330: dict(owner=None, d5_class=1040, template=1040),                          # Witch
    4340: dict(owner=None, d5_class=1010, template=1010),                          # Warrior
    4350: dict(owner=None, d5_class=1120, template=1120),                          # Gunner
    4400: dict(owner="D4_Class_2160", sprite=2370, colour=2370, template=2170),    # Wood Golem
    5300: dict(owner="D4_Class_1140", sprite=1410, colour=1410, template=1190),    # Bouncer
    5302: dict(owner=None, d5_class=1130, template=1130),                          # Ninja
    5303: dict(owner="D4_Class_1200", sprite=1470, colour=1470, template=1250),    # Android
    3307: dict(owner=None, d5_class=2090, template=2090),                          # Undead
    5403: dict(owner="D4_Unique_180", unique_row=180, template=610),               # Des X (monster)
    5414: dict(owner="D4_Unique_40", unique_row=40, template=1020),               # Fuka
    990: dict(owner="D4_Unique_10", unique_row=10, template=1010),                # Valvatorez body
}

# Rows that stay closed: their D4 body has no art in D5, in the Kit or in a built D4 pack.
CLOSED = {
    4370: "D4 body 1180 Onmyo Monk has no D5 or Kit art pack to share (D4-NPC1 owner table); "
          "building it needs its own art window",
    4380: "D4 body 1120 Beast Master has no D5 or Kit art pack to share (D4-NPC1 owner table); "
          "building it needs its own art window",
}

# D5 vanilla class rows: the D4 body name -> the D5 class id and its rank-0 sprite/colour key.
D5_CLASSES = {1010: (1010, 1010), 1040: (1040, 1040), 1110: (1110, 1110),
              1120: (1120, 1120), 1130: (1130, 1130), 2090: (2090, 2090)}

# The template class's own first two skills become labelled donor lines for a row whose D4
# learn list is empty (the D4GAP1 rule the nine built NPCs already use).
TEMPLATE_SKILLS = {
    1010: [(10, 11011, "Bulk Up"), (30, 11012, "Muscle Charge")],
    1020: [(10, 11021, "Valkyrie line"), (30, 11022, "Valkyrie line")],
    1040: [(10, 11041, "Witch line"), (30, 11042, "Witch line")],
    1110: [(10, 11111, "Archer line"), (30, 11112, "Archer line")],
    1120: [(10, 11121, "Gunner line"), (30, 11122, "Gunner line")],
    1130: [(10, 11131, "Ninja line"), (30, 11132, "Ninja line")],
    1150: [(10, 11011, "Warrior line"), (30, 11012, "Warrior line")],
    1190: [(10, 11141, "Lady Samurai line"), (30, 11142, "Lady Samurai line")],
    1250: [(10, 11201, "Pirate line"), (80, 11202, "Pirate line")],
    2090: [(8, 12091, "Undead line"), (24, 12092, "Undead line")],
    2170: [(8, 12161, "Nether Noble line"), (24, 12162, "Nether Noble line")],
}


def next_free(start, step, taken):
    value = start
    while value in taken:
        value += step
    return value


def build(source_chars, leases_doc, previous=None):
    previous = previous or {}
    chars = leases_doc["characters"]
    lease_chars = {v["mod"]: v for v in chars.values()}
    taken_identity = {int(v["identity"]) for v in chars.values()}
    art = json.loads((ROOT / "d5lib/data/unique_art_leases.json").read_text())["leases"]
    taken_identity |= {int(v["identity"]) for v in art.values()}
    taken_voice = {int(v["voice_id"]) for v in chars.values() if v.get("voice_id")}
    out = {}
    identity = next_free(18300, 10, taken_identity)
    voice = next_free(9149, 1, taken_voice)
    for sid in sorted(ROWS, key=lambda r: list(ROWS).index(r)):
        row = dict(ROWS[sid])
        src = source_chars[sid]
        entry = dict(mod=f"D4_Unique_{sid}", npc=True, identity=identity,
                     template=row["template"], voice_id=voice,
                     specials_source="specials", specials=[], evilities=[], notes=False)
        if "unique_row" in row:
            owner = lease_chars[f"D4_Unique_{row['unique_row']}"]
            entry.update(physical=int(owner["physical"]), share_art_with=row["owner"],
                         share_sprite=int(owner["physical"]), share_color=int(owner["physical"]))
        elif row.get("owner"):
            entry.update(physical=int(row["colour"]), share_art_with=row["owner"],
                         share_sprite=int(row["sprite"]), share_color=int(row["colour"]))
        else:
            sprite, colour = D5_CLASSES[row["d5_class"]]
            entry.update(physical=int(colour), share_art_with=None,
                         share_sprite=int(sprite), share_color=int(colour))
        # A D5 vanilla class needs no pack installed; record it as an owner of "vanilla".
        if entry["share_art_with"] is None:
            entry["share_art_with"] = "vanilla"
        entry["share_source_row"] = sid
        entry["share_note"] = ("D4-NPC1: own identity/name/title/stats/learn list; graphics are the owner's "
                               f"keys (sprite {entry['share_sprite']}, colour {entry['share_color']}). "
                               "The D4 body is " + str(src["sprite"]) + " at colour bank "
                               + str(src["color_id"] % 10) + ".")
        if (previous.get(str(sid)) or {}).get("storage"):
            # Keep a previously recorded storage block (a rebuild reproduces the ids a save knows).
            entry["storage"] = previous[str(sid)]["storage"]
        if not src["learnset"]:
            entry["no_source_skills"] = True
        out[sid] = entry
        identity = next_free(identity + 10, 10, taken_identity)
        voice += 1
    # Recruitment storage: one distinct quest / progress slot / help row per character, above the base
    # game's own highest real row (Quest.dat 444, sort_order 790, charhelp 22907) and clear of every recorded
    # lease.  Without a pin every build allocated the same "next free" ids and the used-id gate refused
    # the second pack.
    taken_q = {int(s["quest_id"]) for s in (v.get("storage") or {} for v in chars.values()) if s.get("quest_id")}
    taken_s = {int(s["quest_slot"]) for s in (v.get("storage") or {} for v in chars.values()) if s.get("quest_slot")}
    taken_h = {int(s["help_id"]) for s in (v.get("storage") or {} for v in chars.values()) if s.get("help_id")}
    quest, slot, helpid = 445, 791, 22908
    for sid in sorted(out):
        if out[sid].get("storage"):
            continue
        quest, slot, helpid = next_free(quest, 1, taken_q), next_free(slot, 1, taken_s), next_free(helpid, 1, taken_h)
        out[sid]["storage"] = dict(quest_id=quest, quest_slot=slot, help_id=helpid)
        taken_q.add(quest); taken_s.add(slot); taken_h.add(helpid)
    return out


# Source rows that DO learn skills, none of which has a D5 twin (D4GAP1's `donor_only` rule):
# the D4 ids and why.  The donor lines are the template class's own.
DONOR_ONLY = {
    4400: "D4 learnset 12161-12164, 22161-22162 (Wood Golem's own monster skills): no D5 twin in the "
          "reviewed mapping (D4-NPC1 build report)",
    5414: "D4 learnset 10041-10043 (Justice Fuka's own skills): no D5 twin in the reviewed mapping "
          "(D4-NPC1 build report)",
}


def sourcemap_entries(source_chars):
    """Donor learn rows for source rows that learn nothing (the D4GAP1 rule, labelled)."""
    out = {}
    for sid, row in ROWS.items():
        src = source_chars[sid]
        if src["learnset"] and sid not in DONOR_ONLY:
            continue
        template = row["template"]
        lines = TEMPLATE_SKILLS[template]
        donor_only = sid in DONOR_ONLY
        out[str(sid)] = dict(
            name=src["name"], **({"donor_only": True, "source": DONOR_ONLY[sid]} if donor_only else
                                 {"no_source_skills": True}),
            skills=[dict(d4_id=None, d4_name=None, level=lvl, d5_id=sid5, d5_name=name, label="donor",
                         reason=("D4 gives this character no D5-mappable learned skills; "
                                 f"template class {template} own skill, learn level {lvl}"))
                    for lvl, sid5, name in lines])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report drift instead of rewriting")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    from d5lib import d4source
    source = d4source.D4Data("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ "
                             "(Steam 1233880)/Disgaea 4 Complete+", "EN")
    chars = {sid: source.chars[sid] for sid in ROWS}
    doc = json.loads(LEASES.read_text())
    for key in [k for k in doc["characters"] if k.startswith("D4_Unique_")]:
        doc["characters"].pop(key)          # an earlier run keyed by mod id; entries are keyed by source row
    previous = {str(sid): doc["characters"].pop(str(sid)) for sid in ROWS if str(sid) in doc["characters"]}
    entries = build(chars, doc, previous)
    mapdoc = json.loads(SOURCEMAP.read_text())
    donors = sourcemap_entries(chars)
    # TEXTHASH-D4: names and descriptions are written as game-text references (docs/TEXT_REFS.md), never as text
    sys.path.insert(0, str(ROOT / "tools"))
    import hash_d4_text
    from d5lib.importers import _d4_source
    pool = _d4_source.text_pool_for_tools()
    entries = hash_d4_text.hash_document(entries, pool)
    donors = hash_d4_text.hash_document(donors, pool)
    if args.check:
        bad = [sid for sid, e in entries.items()
               if json.dumps({k: v for k, v in (doc["characters"].get(str(sid), {})).items()
                              if k != "storage"}, sort_keys=True, ensure_ascii=False)
               != json.dumps({k: v for k, v in e.items() if k != "storage"}, sort_keys=True, ensure_ascii=False)]
        bad += [sid for sid in donors if json.dumps(mapdoc["uniques"].get(str(sid)), sort_keys=True) != json.dumps(donors[sid], sort_keys=True)]
        print("drift:" if bad else "current", bad)
        return 1 if bad else 0
    for sid, e in entries.items():
        previous = doc["characters"].get(str(sid)) or {}
        if not e["storage"]:
            e.pop("storage", None)
        elif previous.get("storage") and previous["storage"] != e["storage"]:
            e["storage"] = previous["storage"]
        doc["characters"][str(sid)] = e
    LEASES.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    mapdoc["uniques"].update(donors)
    SOURCEMAP.write_text(json.dumps(mapdoc, indent=1, ensure_ascii=False) + "\n")
    for sid, e in entries.items():
        print(sid, chars[sid]["name"], "identity", e["identity"], "voice", e["voice_id"],
              "art", e["share_art_with"], e["share_sprite"], e["share_color"],
              "template", e["template"], "skills", "source" if chars[sid]["learnset"] else "donor")
    print("closed:", ", ".join(f"{sid} {why}" for sid, why in CLOSED.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
