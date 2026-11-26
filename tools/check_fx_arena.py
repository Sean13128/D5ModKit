"""Vertex-arena gate (POOLLEAK1): on-demand effect loads must not leak the game's 1024 model-block records.

    python tools/check_fx_arena.py --exe <disgaea5.exe> [--native d5lib/native/d5fx.inc.c]
        [--stage <stage dir with BULK.json> ...] [--fxdat <d5fx.dat with the stage's event lists>]
        [--rounds 3] [--baseline 60] [--json out.json]

1. exe: the loader the runtime calls already builds the vertex block (once, on its only path); the release frees
   the one block stored in the slot (d5lib.fxarena.exe_facts).
2. runtime: how d5fx.inc.c's fx_load builds ('once' or 'twice', d5lib.fxarena.runtime_policy).
3. emulation: the game's own build step and release, 1100 load+release cycles in Unicorn with that policy: the
   arena's record count must stay flat (the old sequence faults in the record scan at cycle ~1023, the LIVE1120G
   crash site).
4. sessions: every converted attack of each stage cast `rounds` times in one session, each on its four routes
   (normal, start skip, mid skip: the same root prefetch; stock fallback: the original choreography's lists),
   against the runtime's cache (400 entries, oldest released): records in use after every cast must stay below
   1024 - FX_ARENA_SPARE with `baseline` records taken by the rest of the game, and no record may be orphaned
   (records in use = baseline + models in the cache, at the end of every scene).
   Event lists come from --fxdat when given (exact: the installed or built d5fx.dat); otherwise each attack is
   taken to load `effects` models of its own plus the 19 stock models every converted root prefetches (an upper
   bound: models a pack shares count once per attack).
Exit 1 on any failure."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import fxarena  # noqa: E402

COMMON = 19          # stock models every converted D4 root prefetches (installed d5fx.dat, SPECBULK3C)
SPARE = 24           # d5fx.inc.c FX_ARENA_SPARE


def read_fxdat(path):
    import struct
    with open(path, "rb") as f:
        magic, ver, n = struct.unpack("<4sII", f.read(12))
        if magic != b"D5FX":
            raise SystemExit(f"{path}: not a d5fx.dat")
        f.seek(12 * n, 1)
        m = struct.unpack("<I", f.read(4))[0]
        heads = [struct.unpack("<III", f.read(12)) for _ in range(m)]
        k = struct.unpack("<I", f.read(4))[0]
        ids = struct.unpack(f"<{k}I", f.read(4 * k))
    return {ev: list(ids[a:a + c]) for ev, a, c in heads}


def stage_casts(stage, lists, rounds):
    bulk = json.loads((Path(stage) / "BULK.json").read_text())
    conv = [x for x in bulk if x.get("status") == "converted"]
    exact = lists is not None
    lists = dict(lists or {})
    known = set(lists)
    casts = []
    for r in range(rounds):
        order = conv if r % 2 == 0 else list(reversed(conv))
        for x in order:
            root = x["root"]
            if root not in lists:
                own = [("m", x["owner"], x.get("d5_skill"), i) for i in range(int(x.get("effects") or 0))]
                lists[root] = [("stock", i) for i in range(COMMON)] + own
            casts += [root, root, root]                               # normal, start skip, mid skip
            fb = x.get("original_choreography")
            if fb:
                casts.append(fb)                                      # stock fallback (several targets)
    exact = exact and all(x["root"] in known for x in conv)
    return casts, lists, len(conv), exact


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--native", default=str(Path(__file__).resolve().parents[1] / "d5lib/native/d5fx.inc.c"))
    ap.add_argument("--stage", action="append", default=[])
    ap.add_argument("--fxdat")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--baseline", type=int, default=60)
    ap.add_argument("--cycles", type=int, default=1100)
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    exe = Path(a.exe).read_bytes()
    out, fails = {}, []
    facts = fxarena.exe_facts(exe)
    out["exe"] = {k: (hex(v) if isinstance(v, int) and v > 0xFFFF else v) for k, v in facts.items()}
    if facts.get("loader_builds") != 1 or not facts.get("loader_build_unconditional"):
        fails.append("exe: the loader does not build the vertex block exactly once on its only path")
    if facts.get("release_frees") != 1 or not facts.get("release_reads_slot_block"):
        fails.append("exe: the release does not free the slot's vertex block")

    policy = fxarena.runtime_policy(Path(a.native).read_text(encoding="utf-8", errors="replace"))
    out["runtime_policy"] = policy
    builds = 1 + (policy != "once")          # the loader's own build, plus FX_FINISH when it is unconditional
    emu = fxarena.emulate(exe, a.cycles, extra=builds == 2, facts=facts)
    used = emu["used"]
    out["emulation"] = {"cycles": emu["cycles"], "fault": emu["fault"] and [hex(x) for x in emu["fault"][:2]],
                        "records_first": used[:3], "records_last": used[-1] if used else None}
    if emu["fault"] or (used and max(used) != min(used)):
        fails.append(f"emulation: {builds} builds per load leave records behind "
                     f"(after {emu['cycles']} cycles: {used[-1] if used else '-'} records, fault {out['emulation']['fault']})")

    lists = read_fxdat(a.fxdat) if a.fxdat else None
    out["stages"] = {}
    for st in a.stage:
        casts, l2, n, exact = stage_casts(st, lists, a.rounds)
        sim = fxarena.simulate(casts, l2, "once" if builds == 1 else "twice", baseline=a.baseline)
        peak = max(sim["used"]) if sim["used"] else 0
        limit = fxarena.ARENA_RECORDS - SPARE
        first = next((i for i, u in enumerate(sim["used"]) if u > limit), None)
        out["stages"][st] = {"attacks": n, "casts": len(casts), "lists": "d5fx.dat" if exact else "receipts (bound)",
                             "loads": sim["loads"], "orphans": sim["orphans"], "peak_records": peak,
                             "over_limit_at_cast": first, "limit": limit}
        if sim["orphans"] or first is not None:
            fails.append(f"{st}: {sim['orphans']} orphaned records, peak {peak} of {limit}"
                         + (f" (over at cast {first} of {len(casts)})" if first is not None else ""))
    out["failures"] = fails
    out["result"] = "FAIL" if fails else "PASS"
    text = json.dumps(out, indent=1)
    if a.json:
        Path(a.json).write_text(text)
    print(text)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
