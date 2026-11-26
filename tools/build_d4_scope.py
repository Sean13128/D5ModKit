#!/usr/bin/env python3
"""Build d5lib/importers/d4-scope.json (D4-ROSTER1) from the class registry workbook, once.

Reads sheet 'Disgaea 4' of Research/class-registry/D5-Classes-by-Game.xlsx (stdlib only, no
openpyxl) and joins it to the allocation checkpoint by registry family.  A family is in scope when
the workbook says Buildable, or when it is an Overlord-convert target (1190/1200, D4-ROSTER1 brief:
ported to Kit mods, credit Cryswar) -- so the installed 11 stay in scope.  Everything else records
what D5 already has.  Run from anywhere; rewrites the json beside d4.py.
"""
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path("/Volumes/Data/Projects/D5")
XLSX = BASE / "Research/class-registry/D5-Classes-by-Game.xlsx"
CHECKPOINT = BASE / "Research/d4-expansion-20261018/mvp-breadth/allocation-checkpoint.json"
OUT = Path(__file__).resolve().parents[1] / "d5lib/importers/d4-scope.json"
TARGET = BASE / "Research/class-registry/TARGET-ROSTER.json"
LEASES = OUT.with_name("d4-leases.json")
OVERLORD_CONVERT = {1190, 1200}
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def sheet_rows(path, sheet):
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = ["".join(t.text or "" for t in si.iter(M + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    rid = next(s.get(R) for s in ET.fromstring(z.read("xl/workbook.xml")).iter(M + "sheet") if s.get("name") == sheet)
    target = next(r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")) if r.get("Id") == rid)
    for row in ET.fromstring(z.read("xl/" + target.replace("/xl/", "").lstrip("/"))).iter(M + "row"):
        out = []
        for c in row:
            v = c.find(M + "v")
            if v is None:
                i = c.find(M + "is")
                out.append("".join(x.text or "" for x in i.iter(M + "t")) if i is not None else "")
            else:
                out.append(ss[int(v.text)] if c.get("t") == "s" else v.text)
        yield out


def why_not(row):
    status, equiv = row[2], row[3]
    if status == "In D5":
        return f"D5 already has {row[0]} (same name; registry id {row[4]} reserved)"
    if status.startswith("In D5 ("):
        return f"D5 already has it as {equiv} (registry id {row[4]} reserved)"
    if status == "In D5ModKit":
        return f"D5ModKit already ships {equiv} (registry id {row[4]} reserved)"
    if status == "Overlord unique":
        return f"Overlord already ships {equiv} (registry id {row[4]} reserved)"
    return f"workbook ID status {row[12]!r} / {status!r}"


def build():
    rows = {int(r[4]): r for r in sheet_rows(XLSX, "Disgaea 4") if len(r) >= 13 and r[4].isdigit()}
    fams = [f for f in json.loads(CHECKPOINT.read_text())["families"] if f.get("registry_family")]
    out = {}
    for f in fams:
        sid, row = int(f["source_family"]), rows[int(f["registry_family"])]
        buildable = row[12] == "Buildable"
        keep = buildable or sid in OVERLORD_CONVERT
        out[str(sid)] = dict(
            name=f["name"], registry_family=f["registry_family"], status_vs_d5=row[2],
            id_status=row[12], in_scope=keep,
            why_not="" if keep else why_not(row),
            note=("Overlord-convert target: Overlord ships it, ported to a Kit mod (credit Cryswar)"
                  if not buildable and keep else ""))
    # D4-NPC1: TARGET-ROSTER D4 character rows with no lease are NPCs / alternates the importer
    # lists as out of scope until that card builds them (so they resolve to roster entries).
    doc = json.loads(LEASES.read_text())
    leased = {c["mod"] for c in doc["characters"].values()} | set(doc["parked"])
    # D4-NPC1 closure: the two rows whose D4 body (Onmyo Monk 1180, Beast Master 1120) has no
    # D5, Kit or built D4 art pack to share stay out of scope for that reason, not for want of a card.
    closed = {
        4370: "D4-NPC1 owner table: D4 body 1180 (Onmyo Monk) has no D5/Kit art pack to share",
        4380: "D4-NPC1 owner table: D4 body 1120 (Beast Master) has no D5/Kit art pack to share",
    }
    npcs = {r["mod_folder"]: dict(name=r["name"], row=r["source_row_id"],
                                  why_not=closed.get(int(r["source_row_id"]), "D4-NPC1"))
            for r in json.loads(TARGET.read_text())["rows"]
            if r.get("importer") == "d4" and r["kind"] == "character" and r["mod_folder"] not in leased}
    # The two closed rows are not in TARGET-ROSTER (it lists playable targets); keep them listed so the
    # D4 census still resolves every named non-shipped row (D4-ROSTER1's "0 unlisted" property).
    for row_id, name in ((4370, {"@text": "076958b3b9e4cfc0916bb7a4aa306b249a910765e291059808b4c55b8e37effc"}),
                         (4380, {"@text": "55a2b482ac57ab5460a81584b5586c3d4364191fe49d18d229258e80f966ba5f"})):
        npcs[f"D4_Unique_{row_id}"] = dict(name=name, row=row_id, why_not=closed[row_id])
    out["_npcs"] = npcs
    return out


if __name__ == "__main__":
    scope = build()
    # TEXTHASH-D4: names are written as game-text references (docs/TEXT_REFS.md), never as text
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hash_d4_text
    from d5lib.importers import _d4_source
    scope = hash_d4_text.hash_document(scope, _d4_source.text_pool_for_tools())
    OUT.write_text(json.dumps(scope, indent=1, ensure_ascii=False) + "\n")
    fam = [v for k, v in scope.items() if k != "_npcs"]
    n = sum(v["in_scope"] for v in fam)
    print(f"{len(fam)} families, {n} in scope, {len(fam) - n} out, {len(scope['_npcs'])} npc rows -> {OUT}",
          file=sys.stderr)
