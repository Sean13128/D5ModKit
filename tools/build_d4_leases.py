#!/usr/bin/env python3
"""Write `d5lib/importers/d4-leases.json`: the D4 unique id allocation, recorded once.

The importer must never *recompute* a lease (a different order would move an installed
character's voice, art row or skill ids).  This tool reads the allocation back from the
installed packs (profile MAIN) and the lanes' own receipts, cross-checks the two, and writes
one table the importer reads:

  * `physical`  - the art row (sprite p, companion p+1, standing picture p+2, portraits 10000+p)
                  as the installed pack ships it, or the re-leased value listed in `released`
  * `voice_id`  - the voice set the installed pack's VAG files are named with
  * `specials`  - D4 skill id -> D5 skill row, donor and relation, from the specials lanes'
                  receipts, checked against the installed pack's magic.dat / skills.json
  * `magichange`- the D4 Magichange attacks (MAGICHANGE lane, `magichange/magichange-content.json`) as the
                  installed pack ships them: D5 row id, name, donor and learn level, cross-checked against
                  the pack's magic.dat and learn list (D4-FIX5)
  * `evilities` - the exact evility rows a lane added on top of the builder's emission
  * `notes`     - whether the pack ships D4UNIQ3-ABILITY-NOTES.txt

Run (offline, read-only):

  python tools/build_d4_leases.py            # writes the table
  python tools/build_d4_leases.py --check    # exits 1 if the file on disk is stale
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path("/Volumes/Data/Projects/D5")
INSTALLED = Path(os.environ.get("D5_INSTALLED_MODS")
                 or "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods")
OUT = ROOT / "d5lib/importers/d4-leases.json"
MAGICHANGE = ROOT / "magichange/magichange-content.json"
RECEIPTS = (BASE / "Research/source-packs/specials/patch-receipt.json",
            BASE / "Research/source-packs/d4uniq3/specials-receipt.json")

# Art rows re-leased away from an installed value.  u210's 934 was never named in the P1OWN
# manifest's 853..999 lease list (which names Shark King 931-933 and Xenolith 941-943), while its
# monster attack scripts 12x10934 collided with D1C_Unique_3130's skill-10934 wrappers; 643 is
# the first window `slots.unique_sprite_pool` measures free of every game file and installed mod.
RELEASED = {
    "D4_Unique_210": dict(
        physical=643,
        supersedes=934,
        why="monster attack scripts 12010934/12110934/12210934 collided with the recorded "
            "D1C_Unique_3130 lease (Shark King, identity/art 931, skills 10932-10935); 934 is not "
            "named in the P1OWN 853..999 lease list, 643 is a measured free window (art row only, "
            "character content unchanged)",
        evidence="P1OWN MANIFEST.md anm_id 853-999 ('Leased today: Shark King 931-933, Xenolith "
                 "941-943'); d5lib/slots.unique_sprite_pool; CORED4C report"),
}


def jload(path):
    return json.loads(Path(path).read_text())


def installed_packs():
    out = {}
    for p in sorted(INSTALLED.glob("D4_Unique_*")):
        m = re.fullmatch(r"D4_Unique_(\d+)", p.name)
        if m and (p / "mod.json").is_file():
            out[int(m.group(1))] = p
    return out


def pack_facts(p):
    facts = {}
    ch = jload(p / "patches/db/char.dat.json")
    facts["identity"] = int(ch["added"][0]["id"]) if ch.get("added") else None
    anm = p / "files/Anime/ANM_HI_JP.dat"
    ids = []
    if anm.is_dir():
        for f in anm.glob("anm*.lzs"):
            m = re.fullmatch(r"anm(\d+)\.lzs", f.name)
            if m:
                ids.append(int(m.group(1)))
    facts["anm_ids"] = sorted(ids)
    facts["physical"] = min([i for i in ids if i < 1000], default=None)
    voices = p / "patches/voices"
    vids = set()
    files = 0
    if voices.is_dir():
        for f in voices.glob("*.vag"):
            files += 1
            m = re.match(r"d4_(\d+)_", f.name)
            if m:
                vids.add(int(m.group(1)))
    facts["voice_id"] = sorted(vids)[0] if len(vids) == 1 else (sorted(vids) if vids else None)
    facts["voice_files"] = files
    magic = jload(p / "patches/db/magic.dat.json") if (p / "patches/db/magic.dat.json").is_file() else {}
    facts["magic"] = [(int(r["id"]), r.get("name_EN") or r.get("name")) for r in magic.get("added") or []]
    skills = jload(p / "patches/skills/skills.json") if (p / "patches/skills/skills.json").is_file() else {}
    facts["skills"] = sorted(int(k) for k in (skills.get("skills") or {}))
    facts["notes"] = [f.name for f in p.glob("*.txt")]
    # recruitment storage: Quest.dat row + its progress slot, and the charhelp row
    q = jload(p / "patches/db/Quest.dat.json").get("added") or []
    h = jload(p / "patches/db/charhelp.dat.json").get("added") or []
    facts["storage"] = ({"quest_id": int(q[0]["id"]), "quest_slot": int(q[0]["sort_order"]),
                         "help_id": int(h[0]["id"])} if len(q) == 1 and len(h) == 1 else None)
    return facts


def magichange_lease(mod, p):
    """The Magichange rows the installed pack ships, checked against the lane's content file."""
    sys.path.insert(0, str(ROOT / "tools"))
    import magichange_rows            # resolves the content file's game-text references
    content = {e["mod"]: e for e in magichange_rows.load_content(MAGICHANGE, {mod})["characters"]}.get(mod)
    if content is None:
        return None
    ch = jload(p / "patches/db/char.dat.json")["added"][0]
    learn = {int(ch[f"learn{k}_skill"]): int(ch[f"learn{k}_level"]) for k in range(1, 17) if ch[f"learn{k}_skill"]}
    magic = {int(r["id"]): r.get("name_EN") for r in
             (jload(p / "patches/db/magic.dat.json").get("added") or [])} \
        if (p / "patches/db/magic.dat.json").is_file() else {}
    rows = []
    if content["d5_rows"] == "new":
        for sid, role in zip(content["ids"], ("single", "pair", "dual")):
            if sid not in magic or magic[sid] != content["names"][role]:
                raise SystemExit(f"{mod}: installed pack lacks Magichange row {sid} {content['names'][role]!r}")
            rows.append({"d5_id": sid, "name": content["names"][role], "copy_of": content["donor_single"],
                         "level": learn[sid]})
    else:                                       # reuse: D5's own rows, no new magic.dat row
        for sid, _lvl in content["learn"]:
            rows.append({"d5_id": sid, "name": None, "copy_of": None, "level": learn[sid]})
    return rows


def receipts():
    rows = []
    for path in RECEIPTS:
        if path.is_file():
            rows.extend(jload(path))
    return rows


def build():
    packs = installed_packs()
    receipt = receipts()
    by_mod = {}
    for r in receipt:
        if r.get("kind") == "skill" and r.get("d5_id"):
            by_mod.setdefault(r["mod"], {})[int(r["d4_id"])] = r
    evility = {}
    for r in receipt:
        if r.get("kind") == "evility":
            evility.setdefault(r["mod"], []).append(r)

    out = {"schema": "d4-import-leases/1",
           "generated": "2026-11-03",
           "source": "generated by tools/build_d4_leases.py from the installed D4_Unique_* packs "
                     "(profile MAIN) and Research/source-packs/{specials,d4uniq3} receipts; read by "
                     "d5lib/importers/d4.py - never recomputed at build time",
           "voice_note": "voice_id is the set the installed VAG files are named with; clips are "
                         "d4_{voice_id}_{clip}_{EN,JP}.vag from the D4 source groups",
           "parked": {"D4_Unique_510": "parked: Overlord's Rutile wins (MODORG1, DECISIONS 2026-11-03)",
                      "D4_Unique_520": "parked: Overlord's Stella wins (MODORG1, DECISIONS 2026-11-03)"},
           "released": RELEASED,
           "characters": {}}

    for sid, p in packs.items():
        mod = p.name
        if mod in out["parked"]:
            continue
        facts = pack_facts(p)
        phys = facts["physical"]
        released = RELEASED.get(mod)
        entry = {
            "mod": mod,
            "identity": facts["identity"],
            "physical": released["physical"] if released else phys,
            "voice_id": facts["voice_id"],
            "specials_source": ("d4uniq3" if mod in
                                ("D4_Unique_70", "D4_Unique_220", "D4_Unique_410", "D4_Unique_420",
                                 "D4_Unique_430", "D4_Unique_440", "D4_Unique_450", "D4_Unique_460",
                                 "D4_Unique_470", "D4_Unique_610") else "specials"),
            "specials": [],
            "evilities": [],
            "notes": "D4UNIQ3-ABILITY-NOTES.txt" in facts["notes"],
            # pinned: the held pack's ids, kept so a rebuild reproduces them (D4-FIX4 decision 1)
            "storage": facts["storage"],
        }
        if released:
            entry["physical_supersedes"] = released["supersedes"]
            entry["physical_why"] = released["why"]
        installed_magic = {i: n for i, n in facts["magic"]}
        for d4_id, r in sorted(by_mod.get(mod, {}).items()):
            d5_id = int(r["d5_id"])
            entry["specials"].append({
                "d4_id": d4_id, "d5_id": d5_id, "name": r.get("name"),
                "copy_of": r.get("copy_of"), "relation": r.get("relation"),
                "level": r.get("level"),
                # a lease is only trusted when the installed pack really ships that row
                "in_installed_magic": d5_id in installed_magic,
                "installed_name": installed_magic.get(d5_id),
                "has_choreo": d5_id in facts["skills"],
            })
        for r in evility.get(mod, []):
            entry["evilities"].append({"d4_id": r.get("d4_id"), "d5_id": int(r["d5_id"]),
                                       "name": r.get("name"), "relation": r.get("relation")})
        mc = magichange_lease(mod, p)
        if mc:
            entry["magichange"] = mc
        entry["installed"] = {"magic": sorted(installed_magic), "skills": facts["skills"],
                              "voice_files": facts["voice_files"]}
        out["characters"][str(sid)] = entry
    # D4GAP1: a lease no installed pack can regenerate is carried over from the file on disk, never dropped: the nine
    # `"npc": true` entries (built from source, never installed) and the 14 restored uniques (leased, not installed).
    # A tool that silently shrank this file let their ids be handed out twice.
    if OUT.is_file():
        for key, entry in jload(OUT)["characters"].items():
            if key not in out["characters"]:
                out["characters"][key] = entry
                continue
            # D4-NPC1: how a raw row is declared (an NPC, and whose art it shares) is a decision the pack
            # cannot regenerate from its files; keep it when the generated entry would drop it.
            for k in ("npc", "share_art_with", "share_sprite", "share_color", "share_source_row", "share_note"):
                if k in entry and k not in out["characters"][key]:
                    out["characters"][key][k] = entry[k]
        out["characters"] = dict(sorted(out["characters"].items(), key=lambda kv: kv[0]))   # the file's own (string) order
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare with the file on disk, write nothing")
    args = ap.parse_args(argv)
    doc = build()
    # TEXTHASH-D4: names are written as game-text references (docs/TEXT_REFS.md), never as text
    sys.path.insert(0, str(ROOT / "tools"))
    import hash_d4_text
    from d5lib.importers import _d4_source
    doc = hash_d4_text.hash_document(doc, _d4_source.text_pool_for_tools())
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.check:
        current = OUT.read_text() if OUT.is_file() else ""
        if current != text:
            print("d4-leases.json is stale; re-run without --check")
            return 1
        print("d4-leases.json is current")
        return 0
    OUT.write_text(text)
    bad = [f"{c['mod']}:{s['d5_id']}" for c in doc["characters"].values() for s in c["specials"]
           if not s["in_installed_magic"]]
    print(f"wrote {OUT} ({len(doc['characters'])} characters, "
          f"{sum(len(c['specials']) for c in doc['characters'].values())} special rows, "
          f"{len(bad)} lease row(s) not present in the installed pack)")
    if bad:
        print("not in installed magic.dat: " + ", ".join(bad))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
