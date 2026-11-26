"""STATORACLE1: the game's own unit-creation + recalc code, run offline on any char.dat row.

What it does
  For a char row (vanilla, built or installed mod) it creates a fresh unit the way the game does and returns
  its eight stats (HP SP ATK DEF INT RES HIT SPD) at level 1, 100 and 9999, no equipment, no evilities:

    creation  unit_init_stats 0x140218590(rec, level)   stat_k = u32(r_k * base_k * (level+1)) / 100,
              r_k = 47 + (LCG >> 32) % 7 (the game's LCG, so a fresh unit varies by -6%..+6%)
    recalc    unit_recalc     0x14021BFB0(rec, 0, 0)    HP x clamp(100 + f(level), 0, 800)%, group clamps
    level-up  the recalc's own loop (exp set to level 100, RNG draw stubbed to its mean 5): per level
              stat += (40 + draw) * growth_k * 1% with growth_k = the LOW BYTE of base_k (u8 copy at creation).

  Two engines, same answers (checked row by row by `--validate`):
    * `Emu`      the pinned exe under Unicorn (Sorrow's rig design, data__data-unitstats.md App. B; tables loaded
                 into the exe's table globals, HUD/achievement/RNG stubbed);
    * `formula`  the transcription (Sorrow §2 + §4 S1/S8/S17) used for bulk runs.
  Aptitudes (char +0x350) do NOT enter these eight numbers: the recalc copies them to the "potency" words
  (rec+12392, clamp 10..300) that damage formulas read.  The oracle reports them beside the stats.

Usage (kit venv; the Unicorn shim loads from tests/):
    D5Modkit/.venv-macos/bin/python tools/stat_oracle.py --validate [--out v.json]
    D5Modkit/.venv-macos/bin/python tools/stat_oracle.py --row-json patches/db/char.dat.json [--emu]

Reads the clean game copy (Disgaea Source/Disgaea 5 Complete) read-only.  Writes nothing but --out.
Prior art: Sorrow (The Unlicense) research-20261014/states/leaves/data__data-unitstats.md §2, §4, §10, App. B.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")
LEVELS = (1, 100, 9999)
ROW = 908
SOURCE_D5 = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)")
EXE_SHA = "49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce"

# exe addresses (Sorrow §0.2, §11; decomp /Volumes/Data/Decomp/d5)
INIT, RECALC, RNG_DRAW = 0x140218590, 0x14021BFB0, 0x140136660
STUBS_LOG = (0x1403EF830, 0x1400A1C70, 0x1402B2750, 0x1402B2BF0)
LCG = 0x147B10AC8
EXP_TABLE = 0x147B10C80
BLOCK, BLOCK_SIZE = 0x144FCCB00, 0x89B8C8
ROSTER = 0x145207DB8
REC = 18256
HEAP, HEAP_SIZE = 0x200000000, 0x4000000
STACK, RET = 0x10000000, 0x300000000


# ------------------------------------------------------------------------------------------- the formula
def f_exp(x):
    """ExpTable::raw(x+1) (Sorrow rig.py f_exp, verified there against the exe's table fill)"""
    xf = float(x)
    c = xf
    ratio = xf / 25.0 + 1.0
    if xf > 98.0:
        t = xf - 98.0
        c = t / (t / 20.0 + 1.0) + 103.0
    cap = struct.unpack('<f', struct.pack('<f', 4.92))[0]
    m = cap if cap < ratio else ratio
    return int((c + 1.0) * (xf + 1.0) * (xf + 2.0) * m * 0.25)


def lcg_rolls(state):
    """the 8 creation rolls r_k (47..53) unit_init_stats draws from LCG state `state`, and the state after"""
    out = []
    for _ in range(8):
        state = (state * 877 + 57377) & 0xFFFFFFFFFFFFFFFF
        out.append((state >> 32) % 7 + 47)
    return out, state


from d5lib.statfidelity import (CLAMP_G0, CLAMP_G1, hp_pct, oracle as oracle_levels, row_flags,  # noqa: E402
                                stats_at as formula, stats_leveled as formula_leveled)


def oracle_row(row):
    base = [int(row['base_' + s]) for s in STATS]
    return {"base": base, "aptitude": [int(row['apt_' + s]) for s in STATS], "levels": oracle_levels(base),
            "flags": row_flags(base)}


# ------------------------------------------------------------------------------------------- tables
def vanilla_db():
    from d5lib import database
    return database.load_database(str(SOURCE_D5 / "Data/Database/Database_0.dat"))


def char_table_with(db, rows):
    """vanilla char.dat + extra row dicts (learnset/evilities zeroed: the oracle is "no evilities"), sorted by id.
    Returns (member bytes, {id: sorted row index of the LAST row with that id})"""
    from d5lib import database
    t = database.load_table("char.dat", db.raw["char.dat"])
    for r in rows:
        nr = t.add_row(copy_from=0)
        for k, v in r.items():
            if k in nr:
                nr.set(k, bytes.fromhex(v) if k.startswith('pad_') and isinstance(v, str) else v, truncate=True)
        for i in range(1, 17):
            nr.set(f'learn{i}_skill', 0)
            nr.set(f'learn{i}_level', 0)
        nr.set('learn_count', 0)
        for i in range(1, 5):
            nr.set(f'evility{i}', 0)
        nr.set('evility_count', 0)
    raws = sorted((bytes(r.raw) for r in t.rows), key=lambda b: struct.unpack_from('<I', b, 0xD0)[0])
    idx = {}
    for i, b in enumerate(raws):
        idx[struct.unpack_from('<I', b, 0xD0)[0]] = i
    return struct.pack('<I', len(raws)) + b''.join(raws), idx, raws


# ------------------------------------------------------------------------------------------- the emulator
class Emu:
    """the pinned exe under Unicorn with the database tables in its globals (Sorrow App. B.1 design)"""

    def __init__(self, exe_path=None, db=None, rng_stub=True):
        sys.path.insert(0, str(KIT / "tests"))
        import unicorn_darwin_shim                                    # noqa: F401  (Darwin/ARM64 CTR_EL0)
        unicorn_darwin_shim.install()
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
        from unicorn import x86_const as X
        from test_recruit_runtime import sections
        self.X = X
        exe_path = Path(exe_path or SOURCE_D5 / "disgaea5.exe")
        exe = exe_path.read_bytes()
        import hashlib
        self.exe_sha = hashlib.sha256(exe).hexdigest()
        base, size, secs = sections(exe)
        self.base = base
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(0, 0x10000)                                       # page 0: the exe's NULL+off reads see zero
        mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in secs:
            if rs:
                mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
        self.image = bytes(mu.mem_read(base, (size + 0xFFF) // 0x1000 * 0x1000))
        mu.mem_map(HEAP, HEAP_SIZE)
        mu.mem_map(STACK, 0x200000)
        mu.mem_map(RET, 0x1000)
        mu.mem_write(RET, b"\xf4")
        self.brk = HEAP
        self.calls = []
        self.draw = 5
        self.stubs = {}
        for a in STUBS_LOG:
            self.stubs[a] = lambda a=a: (self.calls.append(hex(a)), 0)[1]
        if rng_stub:                                                 # off: the game's own game_rng_draw runs
            self.stubs[RNG_DRAW] = lambda: (self.draw % max(1, self.mu.reg_read(X.UC_X86_REG_RCX) & 0xFFFFFFFF))
        for a in self.stubs:
            mu.hook_add(UC_HOOK_CODE, self._stub, begin=a, end=a)
        self.db = db or vanilla_db()
        self.load_tables()
        self.mu.mem_write(EXP_TABLE, b''.join(struct.pack('<q', f_exp(k - 1) if k > 0 else 0) for k in range(10001)))
        self.vec = self.alloc(bytes(1024))
        s = self.alloc(bytes(0x100))
        self.put(0x147B45B68, s)
        self.put(s + 0x30, self.vec)
        self.put(s + 0x38, self.vec + 1024)
        self.heap_mark = self.brk

    def _stub(self, mu, addr, size, _):
        X = self.X
        rax = self.stubs[addr]()
        rsp = mu.reg_read(X.UC_X86_REG_RSP)
        ret = struct.unpack('<Q', mu.mem_read(rsp, 8))[0]
        mu.reg_write(X.UC_X86_REG_RAX, rax or 0)
        mu.reg_write(X.UC_X86_REG_RSP, rsp + 8)
        mu.reg_write(X.UC_X86_REG_RIP, ret)

    def alloc(self, data):
        p = self.brk
        self.mu.mem_write(p, bytes(data))
        self.brk = (p + len(data) + 0xF) & ~0xF
        if self.brk >= HEAP + HEAP_SIZE:
            raise MemoryError("emulator heap")
        return p

    def put(self, va, v, fmt='<Q'):
        self.mu.mem_write(va, struct.pack(fmt, v))

    def read(self, va, n):
        return bytes(self.mu.mem_read(va, n))

    def read_range(self, row):
        mn, mx = struct.unpack('<qq', self.read(0x140A185B8 + 24 * row, 16))
        return mn, mx

    def check_clamps(self):
        """the clamp rows the formula hard-codes, re-read from the exe (groups at 0x140A18530)"""
        got = {}
        for g, want in ((0, CLAMP_G0), (1, CLAMP_G1)):
            rows = struct.unpack('<4i', self.read(0x140A18530 + 16 * g, 16))[1:]
            got[g] = {k: self.read_range(r) for k, r in enumerate(rows)}
            want = dict(enumerate(want))
            if got[g] != want:
                raise AssertionError(f"clamp group {g}: exe {got[g]} != formula {want}")
        return got

    def _plain(self, name, data_ptr, count_ptr, stride=None, keyoff=None, raw=None):
        b = raw if raw is not None else self.db.raw[name]
        cnt = struct.unpack('<H', b[:2])[0]
        body = b[4:]
        if stride:
            rows = [body[stride * i:stride * (i + 1)] for i in range(cnt)]
            rows.sort(key=lambda r: struct.unpack_from('<I', r, keyoff)[0])
            body = b''.join(rows) + body[stride * cnt:]
        p = self.alloc(body)
        self.put(data_ptr, p)
        self.put(count_ptr, cnt, '<I')
        return p

    def load_tables(self, char_raw=None):
        self._plain('char.dat', 0x140A03880, 0x140A03888, raw=char_raw)
        self._plain('item.dat', 0x140A038C8, 0x140A038D0, 1120, 72)
        self._plain('HABIT.dat', 0x140A03808, 0x140A03810)
        self._plain('magic.dat', 0x140A03868, 0x140A03870, 1140, 0)
        self._plain('Group.dat', 0x140A03B80, 0x140A03B88)
        self._plain('Quest.dat', 0x140A03B50, 0x140A03B58)
        b = self.db.raw['Skill.dat']
        cnt = struct.unpack('<H', b[:2])[0]
        recs = b[4:4 + cnt * 96]
        keys = b''.join(recs[i * 96:i * 96 + 4] for i in range(cnt))
        pr, pk = self.alloc(recs), self.alloc(keys)
        self.mu.mem_write(0x140A04E38, struct.pack('<H', cnt))
        self.put(0x140A04E48, pk)
        self.put(0x140A04E50, pr)

    def set_chars(self, char_raw):
        """replace char.dat (heap is reset to the mark: tables after char.dat are re-loaded too)"""
        self.brk = self.heap_mark
        self.load_tables(char_raw)

    def call(self, fn, args):
        X = self.X
        rsp = STACK + 0x100000 - 8
        self.mu.mem_write(rsp, struct.pack('<Q', RET))
        self.mu.reg_write(X.UC_X86_REG_RSP, rsp)
        for reg, v in zip((X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8), args):
            self.mu.reg_write(reg, v)
        self.mu.emu_start(fn, RET, count=50_000_000)
        return self.mu.reg_read(X.UC_X86_REG_RAX)

    def fresh(self, row_bytes, row_index, level, lcg_state, exp_to=None):
        """create a unit of this row at `level` with LCG `lcg_state`; optional exp up to level `exp_to`; recalc.
        Returns the 8 max stats (rec+11480), the 8 potency words (rec+12392) and the stub log."""
        d = row_bytes
        self.mu.mem_write(BLOCK, bytes(BLOCK_SIZE))                  # zero save block (flags, squads, bills, roster)
        rec = bytearray(REC)
        struct.pack_into('<I', rec, 0, 1)
        struct.pack_into('<i', rec, 11780, struct.unpack_from('<I', d, 0xD0)[0])
        struct.pack_into('<h', rec, 11786, row_index)
        struct.pack_into('<i', rec, 17224, -1)
        for k in range(5):
            struct.pack_into('<H', rec, 12014 + 2 * k, 9999)
        struct.pack_into('<h', rec, 12026, 1)
        rec[12448], rec[12449] = 0xFF, 1
        for k in range(8):
            struct.pack_into('<H', rec, 12408 + 2 * k, d[848 + k])
        for off in range(4):
            rec[11794 + off] = d[876 + off]
        rec[11802], rec[11804], rec[11806], rec[11808], rec[11810] = d[892], d[226], d[894], d[893], d[896]
        rec[11817], rec[11813] = d[228], d[888]
        rec[13758] = 0xFF
        self.mu.mem_write(ROSTER, bytes(rec))
        self.put(LCG, lcg_state)
        self.calls = []
        self.call(INIT, [ROSTER, level])
        if exp_to:
            rate = struct.unpack_from('<h', d, 224)[0]
            self.put(ROSTER + 8, f_exp(exp_to - 1) * rate, '<q')
        self.call(RECALC, [ROSTER, 0, 0])
        out = self.read(ROSTER, REC)
        return (list(struct.unpack_from('<8q', out, 11480)), list(struct.unpack_from('<8H', out, 12392)),
                struct.unpack_from('<H', out, 11772)[0], list(self.calls))


# ------------------------------------------------------------------------------------------- validation
LIVE_READINGS = {   # status panel, recruited fresh at LV1, no equipment (coordinator, 2026-11-10)
    "Beatrice": {"mod": "DRPG_Core_Beatrice_20033", "level": 1, "stats": [27, 15, 13, 14, 14, 15, 20, 16]},
    "Colossal Prinny Blue": {"mod": "DRPG_Core_ColossalPrinnyBlue_60019", "level": 1,
                             "stats": [25, 15, 13, 15, 15, 15, 22, 15]},
}
VANILLA_CHECK = (10, 40, 1010, 1040, 2015)        # Killia, Seraphina, Warrior, (1040), Prinny rank 6


def rolls_consistent(base, level, stats):
    """per stat, the creation rolls r (47..53) that give exactly the observed value"""
    out = []
    for k in range(8):
        ok = [r for r in range(47, 54) if formula(base, level, [r] * 8)[k] == stats[k]]
        out.append(ok)
    return out


def validate(mods_root, emu_rows=None, seeds=(1, 777, 123456789, 0xDEADBEEF)):
    db = vanilla_db()
    emu = Emu(db=db)
    report = {"exe_sha256": emu.exe_sha, "exe_pinned": emu.exe_sha == EXE_SHA, "clamps": None,
              "vanilla": [], "live": [], "mods_differential": {"rows": 0, "cases": 0, "mismatches": []}}
    emu.check_clamps()
    report["clamps"] = "exe group-0/1 clamp rows equal the formula's"
    extra = []
    for name, live in LIVE_READINGS.items():
        doc = json.loads((Path(mods_root) / live["mod"] / "patches/db/char.dat.json").read_text())
        extra.append(doc["added"][0])
    for r in (emu_rows or []):
        extra.append(r)
    char_raw, idx, raws = char_table_with(db, extra)
    emu.set_chars(char_raw)

    def case(cid, label):
        i = idx[cid]
        d = raws[i]
        base = list(struct.unpack_from('<8H', d, 4))
        rows = []
        for lv in LEVELS:
            for s in seeds:
                stats, pot, lvl, calls = emu.fresh(d, i, lv, s)
                rolls, _ = lcg_rolls(s)
                want = formula(base, lv, rolls)
                rows.append({"level": lv, "seed": s, "emu": stats, "formula": want, "ok": stats == want,
                             "potency": pot, "aptitude": list(d[848:856]), "level_after": lvl, "calls": calls})
        stats, pot, lvl, calls = emu.fresh(d, i, 1, seeds[0], exp_to=100)
        rolls, _ = lcg_rolls(seeds[0])
        want = formula_leveled(base, 100, rolls)
        rows.append({"level": "1->100 (draw 5)", "seed": seeds[0], "emu": stats, "formula": want,
                     "ok": stats == want and lvl == 100, "level_after": lvl, "calls": calls})
        return {"id": cid, "name": label, "base": base, "cases": rows, "ok": all(r["ok"] for r in rows)}

    names = {struct.unpack_from('<I', b, 0xD0)[0]: b for b in raws}
    vnames = {r['id']: r['name_EN'] for r in db['char.dat'].rows}
    for cid in VANILLA_CHECK:
        if cid in names:
            report["vanilla"].append(case(cid, vnames.get(cid, "")))
    for name, live in LIVE_READINGS.items():
        doc = json.loads((Path(mods_root) / live["mod"] / "patches/db/char.dat.json").read_text())
        row = doc["added"][0]
        base = [row['base_' + s] for s in STATS]
        c = case(row["id"], name)
        rc = rolls_consistent(base, live["level"], live["stats"])
        c.update(live=live["stats"], live_min=formula(base, 1, [47] * 8), live_max=formula(base, 1, [53] * 8),
                 rolls_matching=rc, live_ok=all(rc))
        report["live"].append(c)
    for r in (emu_rows or []):
        c = case(r["id"], r.get("name_EN", ""))
        report["mods_differential"]["rows"] += 1
        report["mods_differential"]["cases"] += len(c["cases"])
        if not c["ok"]:
            report["mods_differential"]["mismatches"].append(c)
    report["ok"] = (report["exe_pinned"] and all(c["ok"] for c in report["vanilla"]) and
                    all(c["ok"] and c["live_ok"] for c in report["live"]) and
                    not report["mods_differential"]["mismatches"])
    return report


def run_survey(mods_root, out, drpg_cache=None):
    from d5lib import statfidelity as sf
    db = vanilla_db()
    vrows = [r.to_dict() for r in db["char.dat"].rows]
    tables = {"d4": sf.d4_rows(), "d1c": sf.d1c_rows(), "dd2": sf.dd2_rows(), "drpg": sf.drpg_rows(drpg_cache)}
    results = sf.survey(mods_root, vrows, tables)
    rows = []
    for r in results:
        doc = json.loads((Path(mods_root) / r["mod"] / "patches/db/char.dat.json").read_text())
        rows.append(next(x for x in doc["added"] if x["id"] == r["id"]))
    seen, uniq = set(), []
    for x in rows:                                   # one emulated row per distinct stat-relevant content
        key = (x["id"], tuple(x["base_" + s] for s in STATS))
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    emu = validate(mods_root, emu_rows=uniq)
    summary = {}
    for g in ("d4", "d1c", "dd2", "drpg"):
        rs = [r for r in results if r["game"] == g]
        cnt = {k: sum(r["base_labels"].count(k) for r in rs) for k in sf.LABELS}
        acnt = {k: sum(r["apt_labels"].count(k) for r in rs) for k in sf.LABELS}
        summary[g] = dict(packs=len({r["mod"] for r in rs}), rows=len(rs), base_label_counts=cnt,
                          apt_label_counts=acnt, rank_agreement=sf.rank_agreement(results, g),
                          flagged=[(r["mod"], r["id"], r["flags"]) for r in rs if r["flags"]],
                          worst=[dict(mod=r["mod"], id=r["id"], name=r["name"], source_id=r["source_id"],
                                      distance=r.get("profile_distance"), cause=r["cause"], base=r["base"],
                                      source=(r["source"] or {}).get("base"), proposed=r.get("proposed"))
                                 for r in sorted(rs, key=lambda r: -(r.get("profile_distance") or 0))[:20]])
    doc = dict(card="STATORACLE1", generated=__import__("time").strftime("%Y-%m-%d %H:%M"),
               exe_sha256=emu["exe_sha256"], validation=dict(ok=emu["ok"], vanilla=[(c["name"], c["ok"]) for c in emu["vanilla"]],
                   live=[dict(name=c["name"], live=c["live"], min=c["live_min"], max=c["live_max"], ok=c["live_ok"],
                              rolls=c["rolls_matching"]) for c in emu["live"]],
                   emulated_rows=emu["mods_differential"]["rows"], emulated_cases=emu["mods_differential"]["cases"],
                   mismatches=len(emu["mods_differential"]["mismatches"])),
               drpg_mapping=sf.drpg_context(vrows, tables["drpg"]), summary=summary, rows=results)
    Path(out).write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(json.dumps(dict(validation=doc["validation"] | {"live": len(doc["validation"]["live"])},
                          summary={g: {k: v for k, v in s.items() if k not in ("flagged", "worst", "rank_agreement")} | {"flagged": len(s["flagged"])}
                                   for g, s in summary.items()}), ensure_ascii=False, indent=1))
    return 0 if emu["ok"] else 1


def apply_drpg(mods_root, folders, build_dir, cache, out):
    import shutil
    from d5lib import gamefs, modsys, statfidelity as sf
    from d5lib.importers._drpg_build import apply_source_stats
    fs = gamefs.GameFS(str(SOURCE_D5))
    build = Path(build_dir)
    build.mkdir(parents=True, exist_ok=True)
    report = []
    for name in folders:
        dest = build / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(Path(mods_root) / name, dest, symlinks=True)
        mod = modsys.Mod(str(dest))
        before = [dict(r) for r in json.loads((dest / "patches/db/char.dat.json").read_text())["added"]]
        sid = mod.meta["source_import"]["source"]["row"]["base_id"]
        notes = []
        label = apply_source_stats(mod, fs, sid, dict(drpg_stats="source", drpg_master_cache=cache), notes)
        after = json.loads((dest / "patches/db/char.dat.json").read_text())["added"]
        for rp in dest.glob("*receipt*.json"):                 # what the importer's receipt says with the flag on
            rd = json.loads(rp.read_text())
            rd.setdefault("features", {})["stats"] = label
            rp.write_text(json.dumps(rd, indent=1, ensure_ascii=False))
        emu = validate(mods_root, emu_rows=after)
        report.append(dict(mod=name, source_id=sid, label=label, notes=notes,
                           rows=[dict(id=b["id"], before=oracle_row(b), after=oracle_row(x))
                                 for b, x in zip(before, after)],
                           emulated=dict(rows=emu["mods_differential"]["rows"], cases=emu["mods_differential"]["cases"],
                                         mismatches=len(emu["mods_differential"]["mismatches"]))))
    Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    for r in report:
        x = r["rows"][0]
        print(r["mod"], r["label"], x["before"]["base"], "->", x["after"]["base"],
              "LV100", x["after"]["levels"]["100"]["nominal"], "emu", r["emulated"])
    return 0 if all(r["emulated"]["mismatches"] == 0 for r in report) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--mods", default=str(Path("/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods")))
    ap.add_argument("--row-json", help="a char.dat.json patch: oracle every added row")
    ap.add_argument("--emu", action="store_true", help="with --row-json: also run each row under Unicorn")
    ap.add_argument("--survey", help="every installed D4/D1C/DD2/DRPG pack: write results JSON here")
    ap.add_argument("--drpg-cache", help="JSON cache of the DRPG character master (scratch, never the repo)")
    ap.add_argument("--apply-drpg", nargs="+", metavar="MOD",
                    help="clone these installed DRPG packs into --build-dir and map their char rows (the importer "
                         "flag's own function); everything else is copied unchanged")
    ap.add_argument("--build-dir")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.apply_drpg:
        return apply_drpg(a.mods, a.apply_drpg, a.build_dir, a.drpg_cache, a.out)
    if a.survey:
        return run_survey(a.mods, a.survey, a.drpg_cache)
    if a.validate:
        res = validate(a.mods)
    else:
        rows = json.loads(Path(a.row_json).read_text())["added"]
        res = {"rows": [dict(id=r["id"], name=r.get("name_EN", ""), **oracle_row(r)) for r in rows]}
        if a.emu:
            res["emu"] = validate(a.mods, emu_rows=rows)
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text)
    print(text if not a.validate else json.dumps({k: res[k] for k in ("exe_pinned", "ok")} | {
        "vanilla": [(c["name"], c["ok"]) for c in res["vanilla"]],
        "live": [(c["name"], c["ok"], c["live_ok"], c["rolls_matching"]) for c in res["live"]]}, ensure_ascii=False))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
