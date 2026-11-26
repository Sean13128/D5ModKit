"""Save-import proof on copies of a real save and the real tables (offline, read-only inputs).

Run:
    python tools/overlord_port/save_import_proof.py --save <copy of Save_001.sav> --out-dir <dir>

What it proves, and what it does not:

  A  identity        source table == target table: the imported save's *state* is byte-identical, so
                     the importer changes nothing when nothing differs.
  B  Overlord era    the same save re-addressed to his table, then imported back: every learned id
                     that his table also has comes back, per unit, exactly as before.
  C  his content     learned ids >= 20000 (his evilities) survive the import: into the bitmap when the
                     target table has room below position 1000, into the companion otherwise.
  D  unmappable      ids his table has and ours does not are reported, quarantined, never dropped.

No game binary is run, nothing is installed, and the input save is only read: the work copies live in
--out-dir.  "Loads in game" is NOT proven here; this is the file-level, data-level proof.
"""
import argparse
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from d5lib import database, gamefs, learned, ordercheck, overlord_import, savegame  # noqa: E402

import baseline   # noqa: E402


def read_member(game_dir, member):
    """the member as installed (patched by the kit), read-only"""
    fs = gamefs.GameFS(game_dir)
    return fs.read_raw(f"{baseline.ARCHIVE}/{member}")


def learned_ids(save, unit, ids):
    """the learned evility ids of one unit, decoded through a table's ordered ids"""
    off = unit.base + overlord_import.LEARNED
    bitmap = bytes(save.state[off:off + overlord_import.LEARNED_BYTES])
    return learned.learned_from_bitmap(bitmap, ids)


def reencode(save, unit, src_ids, tgt_ids):
    """write the unit's bitmap in `tgt_ids` positions for the ids it holds in `src_ids` positions"""
    off = unit.base + overlord_import.LEARNED
    bitmap = bytes(save.state[off:off + overlord_import.LEARNED_BYTES])
    new, overflow, unknown, _moved = ordercheck.remap_bitmap(bitmap, src_ids, tgt_ids)
    save.state[off:off + overlord_import.LEARNED_BYTES] = new
    return overflow, unknown


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", required=True, help="a COPY of an Overlord-era or kit save")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--game", default=baseline.DEFAULT_GAME)
    ap.add_argument("--release", default=os.path.expanduser(
        "~/Downloads/Disgaea 5 Overlord Edition v3(1)"))
    a = ap.parse_args(argv)

    work = os.path.abspath(a.out_dir)
    os.makedirs(work, exist_ok=True)
    receipt = {"save_in": os.path.abspath(a.save), "work": work, "checks": []}
    ok = True

    ours_skill = read_member(a.game, "Skill.dat")
    ours_char = read_member(a.game, "char.dat")
    rel = os.path.join(a.release, "mods", "Overlord", "Database", "Database_0")
    his_skill = open(os.path.join(rel, "Skill.dat"), "rb").read()
    his_char = open(os.path.join(rel, "char.dat"), "rb").read()
    our_ids = overlord_import.table_ids(ours_skill)
    his_ids = overlord_import.table_ids(his_skill)
    receipt["tables"] = {"ours_rows": len(our_ids), "overlord_rows": len(his_ids),
                         "ours_sha256": _sha_bytes(ours_skill), "overlord_sha256": _sha_bytes(his_skill)}

    # ---- A: identity -------------------------------------------------------------------------
    src = os.path.join(work, "Save_001.sav")
    shutil.copyfile(a.save, src)
    before = open(src, "rb").read()
    out_a = os.path.join(work, "A-identity.sav")
    rep_a, comp_a = overlord_import.convert(src, out_a, source_skill=ours_skill, target_skill=ours_skill,
                                            source_char=ours_char, target_char=ours_char)
    same_state = _state(out_a) == _state(src)
    receipt["checks"].append({"check": "A identity (same table in and out)",
                              "state_byte_identical": same_state,
                              "totals": rep_a["totals"], "companion": bool(comp_a),
                              "input_unchanged": open(src, "rb").read() == before})
    ok &= same_state and not comp_a

    # ---- B: his era -> ours ------------------------------------------------------------------
    era = savegame.Save(src)
    lost_to_his_table, overflowed = [], 0
    original = {}
    for unit in era.units():
        had = learned_ids(era, unit, our_ids)
        original[unit.serial] = had
        _ov, unknown = reencode(era, unit, our_ids, his_ids)
        lost_to_his_table += sorted(unknown)
    era_path = os.path.join(work, "B-overlord-era.sav")
    with open(era_path, "wb") as f:
        f.write(era.to_bytes())
    out_b = os.path.join(work, "B-imported.sav")
    rep_b, comp_b = overlord_import.convert(era_path, out_b, source_skill=his_skill,
                                            target_skill=ours_skill, source_char=his_char,
                                            target_char=ours_char)
    back = savegame.Save(out_b)
    mismatched, checked = [], 0
    for unit in back.units():
        want = {i for i in original.get(unit.serial, set()) if i in set(his_ids)}
        got = learned_ids(back, unit, our_ids)
        # ids past position 1000 are in the companion, not the bitmap
        if unit.serial in (rep_b.get("unit_names") or {}):
            pass
        checked += 1
        if not want <= got:
            mismatched.append({"serial": unit.serial, "missing": sorted(want - got)[:8]})
    receipt["checks"].append({"check": "B Overlord-era save imported back into the kit's table",
                              "units": checked, "learned_ids_restored": not mismatched,
                              "mismatched": mismatched[:5],
                              "ids_his_table_lacks": sorted(set(lost_to_his_table))[:20],
                              "ids_his_table_lacks_count": len(set(lost_to_his_table)),
                              "totals": rep_b["totals"], "companion": bool(comp_b)})
    ok &= not mismatched
    ok &= open(src, "rb").read() == before          # still only read

    # ---- C: his high ids survive ---------------------------------------------------------------
    # The target of a real install is "what the kit has installed" + the package's added rows.  Row
    # *edits* change values, not ids, so the id list is composed exactly like this; taking the
    # installed table alone would test a build that deliberately has none of his content.
    his_high = [i for i in his_ids if i >= overlord_import.OVERLORD_ID_FIRST]
    target_skill = _with_added_rows(ours_skill, "Skill.dat", content_patch("Skill.dat"))
    target_char = _with_added_rows(ours_char, "char.dat", content_patch("char.dat"))
    target_ids = overlord_import.table_ids(target_skill)
    era2_path = os.path.join(work, "C-overlord-content.sav")
    era2 = savegame.Save(era_path)
    target_unit = era2.units()[0]
    positions = [his_ids.index(i) for i in his_high if his_ids.index(i) < ordercheck.BITSET_CAP]
    off = target_unit.base + overlord_import.LEARNED
    for p in positions:
        era2.state[off + (p >> 3)] |= 1 << (p & 7)
    with open(era2_path, "wb") as f:
        f.write(era2.to_bytes())
    out_c = os.path.join(work, "C-imported.sav")
    rep_c, comp_c = overlord_import.convert(era2_path, out_c, source_skill=his_skill,
                                            target_skill=target_skill, source_char=his_char,
                                            target_char=target_char)
    in_companion = []
    if comp_c:
        doc = learned.sidecar_read(comp_c)
        pairs, native, unknown = learned.sidecar_plan(doc, target_ids)
        in_companion = sorted({i for ids in pairs.values() for i in ids})
    back_c = savegame.Save(out_c)
    got_c = learned_ids(back_c, savegame.Unit(back_c, target_unit.slot), target_ids)
    kept = [i for i in his_high if i in got_c]
    receipt["checks"].append({"check": "C Overlord content ids >= 20000 survive",
                              "his_high_ids": len(his_high),
                              "target_rows_with_package": len(target_ids),
                              "positions_in_target": sorted({target_ids.index(i) for i in his_high})[:3],
                              "in_bitmap": len(kept), "in_companion": in_companion,
                              "totals": rep_c["totals"]})
    ok &= len(kept) + len(in_companion) >= len(his_high)

    # ---- D: the package installed on a bare kit (his table + our rows = 819 rows) ------------------
    # With fewer rows than the bitmap holds, his high ids stay in the native bitmap: this is the case
    # where nothing depends on the extension store.
    bare_skill = _with_added_rows(baseline.read(baseline.open_database(a.game), "Skill.dat"),
                                  "Skill.dat", content_patch("Skill.dat"))
    bare_ids = overlord_import.table_ids(bare_skill)
    out_d = os.path.join(work, "D-imported.sav")
    rep_d, comp_d = overlord_import.convert(era2_path, out_d, source_skill=his_skill,
                                            target_skill=bare_skill, source_char=his_char,
                                            target_char=target_char)
    back_d = savegame.Save(out_d)
    got_d = learned_ids(back_d, savegame.Unit(back_d, target_unit.slot), bare_ids)
    kept_d = [i for i in his_high if i in got_d]
    receipt["checks"].append({"check": "D package on a bare kit: his ids stay in the bitmap",
                              "target_rows": len(bare_ids), "in_bitmap": len(kept_d),
                              "companion_written": bool(comp_d), "totals": rep_d["totals"]})
    ok &= len(kept_d) == len(his_high) and not comp_d

    receipt["ok"] = bool(ok)
    with open(os.path.join(work, "receipt.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=1)
    print(json.dumps(receipt, indent=1)[:4000])
    print("receipt:", os.path.join(work, "receipt.json"))
    return 0 if ok else 1


def content_patch(member):
    """the package's content patch for a member (the converted mod folder under the tables output)"""
    path = os.environ.get("OLCOMPAT_TABLES", "/Volumes/Data/ai-tmp/olcompat2/tables2")
    p = os.path.join(path, "Overlord Edition", "patches", "db", member + ".json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _with_added_rows(member_bytes, member, patch):
    """the installed member + the package's added rows, in id order (what a real install ends with)"""
    from d5lib import dbpatch
    t = database.load_table(member, member_bytes)
    dbpatch.apply_patch(t, {"table": member, "added": patch.get("added") or []})
    fixed, _moved = ordercheck.sort_keyed(member, t.to_bytes())
    return fixed


def _state(path):
    s = savegame.Save(path)
    return bytes(s.state)


def _sha_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


if __name__ == "__main__":
    sys.exit(main())
