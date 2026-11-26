"""Prove the character bank on copies of a real save: export one unit, import it into another copy.

Run (offline, copies only, no game and no install):

    Local/python-macos/bin/python tools/prove_unitbank.py <A.sav> <B.sav> <workdir> [unit name]

Both files must be copies (the script refuses a path under the live save folder), and it never writes to
A: it reads A, imports into B and then reads both back with the save parser the Kit ships.
"""
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from d5lib import savegame, unitbank          # noqa: E402


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def under_live(path):
    root = os.path.abspath(savegame.save_root() or "/nonexistent")
    return os.path.abspath(path).startswith(root + os.sep)


def ranges(state_a, state_b):
    """[(start, length)] of the byte runs that differ, as one list per run"""
    out, start, n = [], None, 0
    for i in range(min(len(state_a), len(state_b))):
        if state_a[i] != state_b[i]:
            if start is None:
                start = i
            n += 1
        elif start is not None:
            out.append((start, n))
            start, n = None, 0
    if start is not None:
        out.append((start, n))
    return out


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    a_path, b_path, work = argv[1], argv[2], argv[3]
    want = argv[4] if len(argv) > 4 else None
    for p in (a_path, b_path):
        if under_live(p):
            print(f"refused: {p} is under the live save folder; work on a copy")
            return 2
    report = {"files": {"a": a_path, "b": b_path}, "sha_before": {"a": sha(a_path), "b": sha(b_path)}}

    a = savegame.Save(a_path)
    print(f"A: army {a.army_count}, reserve {a.reserve_count}, next serial {unitbank.uid_next(a)}")
    pick = None
    for u in a.units():
        if want is None or u.name == want:
            pick = u.slot
            if want is not None:
                break
    if pick is None:
        print(f"no unit named {want!r} in A")
        return 2
    src = savegame.Unit(a, pick)
    print(f"export: slot {pick} {src.name!r} class {src.cls} Lv{src.level} serial {src.serial}")

    # the companion, when there is one: the learning past the native bitmap, keyed by serial
    extra, companion = {}, None
    side = a_path + ".d5learn.json"
    if os.path.exists(side):
        from d5lib import learned  # noqa: F401  (the companion's format lives there)
        doc = json.load(open(side))
        for key, unit in (doc.get("units") or {}).items():
            extra.setdefault(int(key, 16), []).extend(int(i) for i in unit.get("learned") or [])
        companion = side
    entry = unitbank.export_unit(a, pick, extra_learned=extra, sha=sha(a_path))
    bank = unitbank.bank_doc([entry], note="unitbank proof")
    os.makedirs(work, exist_ok=True)
    bank_path = os.path.join(work, "bank.json")
    with open(bank_path, "w") as f:
        json.dump(bank, f, indent=1, sort_keys=True)
    report["bank"] = {"path": bank_path, "bytes": os.path.getsize(bank_path),
                      "unit": {k: entry[k] for k in ("name", "class", "level", "serial")},
                      "learned_extra": entry["learned_extra"], "companion_seen": companion}

    b = savegame.Save(b_path)
    before_b = bytes(b.state)
    other = {u.slot: b.state[u.base:u.base + savegame.UNIT] for u in b.units() if u.name != entry["name"]}
    out = unitbank.import_unit(b, entry)
    print(f"import: B slot {out['slot']}, serial {out['serial']}, warnings {out['warnings']}")
    b.write()
    del b

    # --- read both back with the parser
    a2 = savegame.Save(a_path)
    b2 = savegame.Save(b_path)
    report["readback"] = {"a_army": a2.army_count, "a_reserve": a2.reserve_count,
                          "b_army": b2.army_count, "b_reserve": b2.reserve_count,
                          "b_verify": unitbank.verify(b2), "a_verify": unitbank.verify(a2)}
    dst = savegame.Unit(b2, out["slot"])
    report["imported"] = {"name": dst.name, "title": dst.title, "class": dst.cls, "level": dst.level,
                          "serial": dst.serial, "squad": dst.squad, "group": dst.group,
                          "index": b2.state[dst.base + savegame.U_INDEX]}
    print(f"B now: {dst.name!r} class {dst.cls} Lv{dst.level} serial {dst.serial} "
          f"(army {b2.army_count}); verify {len(report['readback']['b_verify'])} problem(s)")

    # --- the record is the source's, byte for byte (outside the re-addressed ids)
    src_rec, dst_rec = entry["record"], bytes(b2.state[dst.base:dst.base + savegame.UNIT]).hex()
    skip = set()
    for off, n in ((savegame.U_SERIAL, 8), (savegame.U_INDEX, 1), (savegame.U_SQUAD, 2),
                   (savegame.U_GROUP, 1), (savegame.U_ROW, 2)):
        skip |= set(range(off, off + n))
    diff = [i for i in range(savegame.UNIT) if src_rec[2 * i:2 * i + 2] != dst_rec[2 * i:2 * i + 2]]
    report["record"] = {"differing_bytes_outside_readdressed_ids": [i for i in diff if i not in skip],
                        "items_identical": src_rec[2 * unitbank.ITEMS:2 * unitbank.ITEMS_END] ==
                                           dst_rec[2 * unitbank.ITEMS:2 * unitbank.ITEMS_END]}

    # --- nothing else moved
    moved = [u.slot for u in b2.units() if u.slot in other and
             bytes(b2.state[u.base:u.base + savegame.UNIT]) != other[u.slot]]
    runs = ranges(before_b, bytes(b2.state))
    rec_lo = savegame.ROSTER + out["slot"] * savegame.UNIT
    rec_hi = rec_lo + savegame.UNIT
    allowed = [(rec_lo, rec_hi), (savegame.ARMY_COUNT, savegame.ARMY_COUNT + 2),
               (unitbank.UID_NEXT, unitbank.UID_NEXT + 4)]
    stray = [(s, n) for s, n in runs
             if not any(lo <= s and s + n <= hi for lo, hi in allowed)]
    report["state"] = {"differing_runs": len(runs),
                       "runs_inside_the_imported_record": sum(1 for s, n in runs if s >= rec_lo and s < rec_hi),
                       "runs_outside_the_record_and_counters": [[s, n] for s, n in stray],
                       "other_units_changed": moved,
                       "counter_before": struct.unpack_from("<I", before_b, unitbank.UID_NEXT)[0],
                       "counter_after": unitbank.uid_next(b2)}
    report["sha_after"] = {"a": sha(a_path), "b": sha(b_path)}
    report["a_unchanged"] = report["sha_before"]["a"] == report["sha_after"]["a"]
    report["ok"] = (not report["readback"]["b_verify"] and not report["readback"]["a_verify"]
                    and not report["record"]["differing_bytes_outside_readdressed_ids"]
                    and report["record"]["items_identical"] and not moved
                    and not stray and report["a_unchanged"])
    out_path = os.path.join(work, "proof.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=1)
    print(json.dumps({k: report[k] for k in ("ok", "state", "record", "sha_after", "a_unchanged")},
                     indent=1))
    print(f"proof: {out_path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
