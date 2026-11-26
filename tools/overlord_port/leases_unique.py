"""OLCONV2: lease every id the converted Overlord characters need, from the Kit's own used-id index.

Nothing is hand-picked: each id is the first free one in the Kit band the ownership manifest names for it,
free against vanilla, every importer's recorded lease, every installed mod and any extra root (the same
`importcore.UsedIds` index the LEASEGATE1 gate uses).  The result is recorded in
`d5lib/importers/overlord-leases.json`, which `importcore.lease_claims` reads, so the gate keeps the ids
reserved from then on (a rebuild reads the record; it never recomputes).

  python tools/overlord_port/leases_unique.py "Overlord Character - Stella" ... [--extra-roots DIR ...] [--dry]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True

RECORD = KIT / "d5lib/importers/overlord-leases.json"
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = Path("/Volumes/Data/Projects/D5/D5Modkit/state/games/Disgaea_5_Complete-d8040a88")

SPECIALS = {"Overlord Character - Stella": 3, "Overlord Character - Rutile": 3, "Overlord Character - Majin": 0}
EVILITIES = {"Overlord Character - Stella": 4, "Overlord Character - Rutile": 1, "Overlord Character - Majin": 5}
# Majin: Divine General (one row carrying two behaviours) + the three revenge-gated learnables = 4 source rows;
# one spare row is not needed, so 4.  Stella: buff + aura half + Mighty Elements + Heat Depression.
EVILITIES["Overlord Character - Majin"] = 4

UNIQUE_IDENTITY = (10000, 10990)         # manifest job_class_id.unique_registry_lease, step 10
EVILITY_LATE = (29000, 29099)            # manifest evility_id band added by OLCONV2 (above every in-use id)
BILLS = (22000, 22099)                   # manifest wish_id band added by OLCONV2
VOICES = (9000, 9999)                    # kit custom voices, handed out from 9000
LOW_RUNS = ((223, 403), (853, 999))      # whole-band reservations: no carve needed
THIRD_RUN = (404, 852)                   # needs a record in unique_art_leases.json + manifest regeneration


def load():
    return json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.is_file() else {
        "schema": "overlord-conv-leases/1",
        "note": ("Ids held by the converted Overlord characters (OLCONV2). Written by "
                 "tools/overlord_port/leases_unique.py from the used-id index; read by importcore.lease_claims. "
                 "Never recomputed at build time."), "entries": {}}


def _index(extra_roots):
    from d5lib import importcore
    u = importcore.UsedIds(GAME, STATE, importcore.default_extra_roots(extra_roots))
    return u, u.index()


def allocate(names, extra_roots=(), dry=False):
    doc = load()
    u, idx = _index(extra_roots)
    _, vanilla_anm = u.vanilla()
    used = {}                       # (kind, id) claimed during this run
    for e in doc["entries"].values():
        used.update({("char.dat", e["identity"]): 1})

    def taken(kind, i):
        if (kind, i) in used:
            return True
        # an entry of this record is "own": the record is read by lease_claims, so ignore labels from it
        for label, owner in idx.get((kind, i), ()):
            if not label.startswith("lease overlord-conv:"):
                return True
        hit = u.vanilla_ids(kind).get(i) if kind not in ("anm", "voice") else None
        return bool(hit and not hit[1])

    def anm_taken(n):
        if n in vanilla_anm or n in used_anm:
            return True
        return any(not label.startswith("lease overlord-conv:") for label, _ in idx.get(("anm", n), ()))

    used_anm = set()
    for e in doc["entries"].values():
        used_anm |= {e["physical"] + k for k in (0, 1, 2)} | {10000 + e["physical"], 10001 + e["physical"]}
    out = {}
    for name in names:
        if name in doc["entries"]:
            out[name] = doc["entries"][name]
            continue
        ident = next(i for i in range(UNIQUE_IDENTITY[0], UNIQUE_IDENTITY[1] + 1, 10)
                     if not taken("char.dat", i) and i not in {e["identity"] for e in doc["entries"].values()}
                     and i not in {e["identity"] for e in out.values()})
        phys = None
        for lo, hi in (*LOW_RUNS, THIRD_RUN):
            for n in range(lo, hi + 1):
                keys = {n, n + 1, n + 2, 10000 + n, 10001 + n}
                if not any(anm_taken(k) for k in keys) and not (keys & used_anm):
                    phys = n
                    break
            if phys is not None:
                break
        if phys is None:
            raise SystemExit("no free art window")
        used_anm |= {phys, phys + 1, phys + 2, 10000 + phys, 10001 + phys}
        used_ev = {i for e in [*doc["entries"].values(), *out.values()] for i in e["evilities"]}
        evs = []
        for i in range(EVILITY_LATE[0], EVILITY_LATE[1] + 1):
            if len(evs) == EVILITIES[name]:
                break
            if i not in used_ev and not taken("Skill.dat", i):
                evs.append(i)
        used_sp = {i for e in [*doc["entries"].values(), *out.values()] for i in e["specials"]}
        sps = []
        for i in range(10000 + ident, 10000 + ident + 10):      # the unique's own window: 10000 + identity + 0..9
            if len(sps) == SPECIALS[name]:
                break
            if i not in used_sp and not taken("magic.dat", i):
                sps.append(i)
        if len(sps) != SPECIALS[name]:
            raise SystemExit(f"identity {ident}: no {SPECIALS[name]} free special ids in {10000 + ident}..{10009 + ident}")
        used_v = {e["voice"] for e in [*doc["entries"].values(), *out.values()]}
        voice = next(v for v in range(VOICES[0], VOICES[1] + 1) if v not in used_v and not taken("voice", v))
        used_bills = {e["bill"] for e in [*doc["entries"].values(), *out.values()]}
        bill = next(b for b in range(BILLS[0], BILLS[1] + 1) if b not in used_bills and not taken("WishDataBase.dat", b))
        used_h = {e["help_id"] for e in [*doc["entries"].values(), *out.values()]}
        top = max([i for (k, i) in idx if k == "charhelp.dat" and isinstance(i, int)] + list(used_h) + [9040])
        out[name] = dict(identity=ident, physical=phys, evilities=evs, specials=sps, voice=voice,
                         bill=bill, help_id=top + 1,
                         third_run=THIRD_RUN[0] <= phys <= THIRD_RUN[1])
        # later names in this call must not reuse these
        doc["entries"] = {**doc["entries"], name: out[name]}
    if not dry:
        RECORD.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="+")
    ap.add_argument("--extra-roots", nargs="*", type=Path, default=[])
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    res = allocate(a.names, a.extra_roots, a.dry)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
