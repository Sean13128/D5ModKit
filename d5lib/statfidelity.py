"""STATORACLE1: how an imported row's D5 stats compare with its source game, per stat.

The numbers a fresh D5 unit gets come from `unit_init_stats` 0x140218590 + `unit_recalc` 0x14021BFB0 (proven
row by row under Unicorn by tools/stat_oracle.py; the transcription is `stats_at`).  D4 (0x1401b2690) and D1C
(Switch 0x710006d388) roll creation stats with the same expression, base * (47 + rand 7) * (level + 1) / 100,
so for D4/D1C an equal stored base IS the source's own creation behaviour.  DD2 has no decomp here: equal stored
values are compared as table values only.  Disgaea RPG has a different model (lv1 value + per-level gain, six
stats, no SP/HIT, no stat aptitudes), so only its SHAPE can be compared.

Fidelity label per stat (base and aptitude separately):
  exact    built value == source stored value (D1 aptitudes are stored /10 in the source: compared x10)
  scaled   same profile, other scale: built ~= source * s (s = row total ratio), within max(1, 5 %)
  donor    the built row is a vanilla D5 row's values (whole row), or this stat has no source and keeps the donor's
  adapted  anything else (a rule, a fill, an error) -- the comparison names the likely cause

Pure functions; no Unicorn, no writes.  Source tables are read from `Disgaea Source/` only, except DD2,
whose rows come from the prepared source folder (`d5lib/sourcefolder.py`, SOURCEPREP4-DD2).
"""
from __future__ import annotations

import json
import statistics
import struct
from pathlib import Path

STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")
LEVELS = (1, 100, 9999)
LABELS = ("exact", "scaled", "adapted", "donor")
SOURCE = Path("/Volumes/Data/Projects/D5/Disgaea Source")
D4_ROOT = SOURCE / "Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+"
D1C_SLICE = (25866128, 81328, "8c6a76467fc1c9edd9b231bf9a2ebc216dcfe197ecebf613cb673bef353d59a1")
DRPG_MASTERS = SOURCE / ("Disgaea RPG JP (Android)/extracted/sdcard/Android/data/com.disgaearpg.forwardworks/"
                         "files/assetbundle/masters")
NATIVE_TO_CANONICAL = (0, 1, 2, 3, 4, 7, 6, 5)       # D4/D1 store HP SP ATK DEF INT SPD HIT RES


# ------------------------------------------------------------------------------------------- D5 formula
CLAMP_G0 = ((1, 99999999999), (1, 99999999), (1, 99999999))      # exe range rows via groups 0x140A18530
CLAMP_G1 = ((1, 1000000000), (1, 10000000), (1, 10000000))


def _cl(rows, k, v):
    lo, hi = rows[min(k, 2)]
    return max(lo, min(v, hi))


def hp_pct(level):
    f = 7 * level - 7 if level <= 34 else (4 * level + 95 if level <= 67 else level + 296)
    return max(0, min(f + 100, 800))


def stats_at(base, level, rolls=None):
    """the 8 stats of a fresh unit at `level`; rolls None = nominal 50 (middle of the 47..53 creation roll)"""
    lv = max(1, min(int(level), 9999))
    out = []
    for k in range(8):
        r = 50 if rolls is None else rolls[k]
        b = base[k] - 0x10000 if base[k] >= 0x8000 else base[k]        # i16 in the row
        out.append(_cl(CLAMP_G1, k, ((r * (b & 0xFFFFFFFF) * (lv + 1)) & 0xFFFFFFFF) // 100))
    out[0] = max(1, min(hp_pct(lv) * out[0] // 100, 1000000000))
    return [_cl(CLAMP_G0, k, v) for k, v in enumerate(out)]


def stats_leveled(base, to_level, rolls=None, draw=5):
    """created at level 1, levelled to `to_level` by the recalc's loop, every RNG draw = `draw` (5 = mean of 0..10).
    Growth per level is (40 + draw)% of the LOW BYTE of the base (the game copies base to a u8 at creation)."""
    cur = [(((50 if rolls is None else rolls[k]) * base[k] * 2) & 0xFFFFFFFF) // 100 for k in range(8)]
    frac = [0] * 8
    for _ in range(1, to_level):
        for k in range(8):
            pts = max(1, min(base[k] & 0xFF, 1500))
            total = frac[k] + 100 * cur[k] + (draw + 40) * pts
            frac[k], cur[k] = total % 100, total // 100
    cur = [_cl(CLAMP_G1, k, v) for k, v in enumerate(cur)]
    cur[0] = max(1, min(hp_pct(to_level) * cur[0] // 100, 1000000000))
    return [_cl(CLAMP_G0, k, v) for k, v in enumerate(cur)]


def oracle(base):
    out = {str(lv): {"nominal": stats_at(base, lv), "min": stats_at(base, lv, [47] * 8),
                     "max": stats_at(base, lv, [53] * 8)} for lv in LEVELS}
    out["100_leveled"] = {"nominal": stats_leveled(base, 100)}
    return out


def row_flags(base):
    flags = []
    if any(b > 255 for b in base):
        flags.append("growth_byte_wrap: a base > 255 levels up with (base & 0xFF)")
    if any(b <= 0 for b in base):
        flags.append("zero_or_negative_base")
    return flags


# ------------------------------------------------------------------------------------------- source tables
def d4_rows(root=None):
    """D4 stat rows from the verified prepared source set (SOURCEPREP4-D4), or an explicit install folder
    (unverified diagnostic route)."""
    from .importers import _d4_source
    data = root if isinstance(root, _d4_source.D4Files) else _d4_source.data_dir(root)
    return {cid: dict(name=c["name"], base=c["base"], apt=c["aptitudes"])
            for cid, c in data.data("EN").chars.items()}


def dd2_rows(root=None):
    """DD2 stat rows from the verified prepared source set (SOURCEPREP4-DD2), or an explicit root.

    ``root`` may be a resolved ``_dd2_source.Dd2Data`` (the build passes the same set the worker
    reads), a prepared folder (resolved through the manifest) or an explicit dump root (diagnostic).
    """
    from . import dd2source
    from .importers import _dd2_source
    data = root if isinstance(root, _dd2_source.Dd2Data) else _dd2_source.data_dir(root)
    path = data.path('START_4.dat')
    t = dd2source.Tables(dd2source.Nispack(path.read_bytes()))
    # DD2 stores the D5 order (Healer RES apt 115 / SPD 80, Masked Hero SPD apt 130: checked against role)
    return {cid: dict(name=c["name"], base=c["base"], apt=c["aptitudes"]) for cid, c in t.chars.items()}


def d1c_rows():
    import hashlib
    off, size, sha = D1C_SLICE
    from .importers import _d1c_source
    with open(_d1c_source.subdata_path(), "rb") as f:      # the verified prepared SUBDATA.DAT (SOURCEPREP4-D1C)
        f.seek(off)
        b = f.read(size)
    if hashlib.sha256(b).hexdigest() != sha:
        raise ValueError("D1C char_e.dat slice of SUBDATA.DAT does not match the pinned sha256")
    out = {}
    for i in range(struct.unpack_from("<I", b, 0)[0]):
        r = b[8 + 224 * i:8 + 224 * (i + 1)]
        cid = struct.unpack_from("<H", r, 94)[0]
        base = struct.unpack_from("<8H", r, 106)
        apt = r[84:92]
        out.setdefault(cid, dict(name="", base=[base[k] for k in NATIVE_TO_CANONICAL],
                                 apt=[apt[k] * 10 for k in NATIVE_TO_CANONICAL]))
    return out


def drpg_rows(cache=None):
    """{character id: {name, base: [HP, None, ATK, DEF, INT, RES, None, SPD] at lv1, per_lv, kind}} from masters"""
    if cache and Path(cache).is_file():
        return {int(k): v for k, v in json.loads(Path(cache).read_text()).items()}
    import UnityPy
    env = UnityPy.load(str(DRPG_MASTERS / "character"))
    rows = None
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            for v in obj.read_typetree().values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    rows = v
    out = {}
    for r in rows:
        out[r["id"]] = dict(name=r["name"], unique=r["unique_flg"], type=r["character_type"],
                            base=[r["hp_min"], None, r["atk_min"], r["def_min"], r["inte_min"], r["res_min"], None,
                                  r["spd_min"]],
                            per_lv=[r["hp_per_lv"], None, r["atk_per_lv"], r["def_per_lv"], r["inte_per_lv"],
                                    r["res_per_lv"], None, r["spd_per_lv"]],
                            mastery=[r[f"weapon_mastery_rank_{i}"] for i in range(1, 10)])
    if cache:
        Path(cache).write_text(json.dumps(out, ensure_ascii=False))
    return out


# ------------------------------------------------------------------------------------------- labels
def profile(v):
    keep = [x for x in v if x is not None]
    s = sum(keep) or 1
    return [None if x is None else x / s for x in v]


def profile_distance(built, src):
    """L1 distance of the stat-share profiles over the stats the source has (0 = same shape, 2 = disjoint)"""
    idx = [k for k in range(8) if src[k] is not None]
    pb, ps = profile([built[k] for k in idx]), profile([src[k] for k in idx])
    return round(sum(abs(a - b) for a, b in zip(pb, ps)), 4)


def label_vector(built, src, donor=None, scale_ok=True):
    """per-stat labels for one vector (base or aptitude). donor = the vanilla row this row copies, if any"""
    idx = [k for k in range(8) if src[k] is not None]
    s = (sum(built[k] for k in idx) / (sum(src[k] for k in idx) or 1)) if idx else 1.0
    out = []
    for k in range(8):
        if donor is not None and src[k] is not None and built[k] != src[k] and list(built) == list(donor):
            out.append("donor")
        elif src[k] is None:
            out.append("donor" if donor is not None and built[k] == donor[k] else "adapted")
        elif built[k] == src[k]:
            out.append("exact")
        elif scale_ok and abs(built[k] - src[k] * s) <= max(1.0, 0.05 * built[k]):
            out.append("scaled")
        else:
            out.append("adapted")
    return out


def summarize(labels):
    """one word for a row: the label every stat shares, or 'mixed:<counts>'"""
    c = {k: labels.count(k) for k in LABELS if labels.count(k)}
    return next(iter(c)) if len(c) == 1 else "mixed:" + ",".join(f"{k}{v}" for k, v in c.items())


def likely_cause(built, src, donor_name):
    idx = [k for k in range(8) if src[k] is not None]
    if all(built[k] == src[k] for k in idx):
        return "none (exact)" + (f"; the source values equal vanilla D5 '{donor_name}'" if donor_name else "")
    if donor_name:
        return f"donor stats: the row is vanilla D5 '{donor_name}'"
    for a, b in ((5, 7), (5, 6), (6, 7)):
        sw = list(src)
        sw[a], sw[b] = sw[b], sw[a]
        if all(sw[k] is None or built[k] == sw[k] for k in range(8)):
            return f"stat order: {STATS[a]}/{STATS[b]} swapped"
    diff = [STATS[k] for k in idx if built[k] != src[k]]
    return "differs in " + "/".join(diff)


def vanilla_index(char_table_rows):
    """{tuple(base+apt): name} of vanilla D5 rows, for donor detection"""
    out = {}
    for r in char_table_rows:
        key = tuple(r["base_" + s] for s in STATS)
        out.setdefault(key, f"{r['name_EN']} ({r['id']})")
    return out


def built_rows(mod):
    p = Path(mod) / "patches/db/char.dat.json"
    if not p.is_file():
        return []
    return json.loads(p.read_text()).get("added") or []


def source_ids(mod, rows):
    """[(row, source id or None)] from the mod's own source record (mod.json source_import)"""
    meta = json.loads((Path(mod) / "mod.json").read_text())
    si = meta.get("source_import") or {}
    ranks = si.get("source_ranks") or []
    if ranks:
        by_tier = sorted(rows, key=lambda r: (r.get("tier", 0), r["id"]))
        return [(r, ranks[i]["id"] if i < len(ranks) else None) for i, r in enumerate(by_tier)]
    if "source_id" in si:
        return [(r, si["source_id"]) for r in rows]
    src = (si.get("source") or {}).get("row") or {}
    if "base_id" in src:
        return [(r, src["base_id"]) for r in rows]
    return [(r, None) for r in rows]


def compare_row(row, src, vanilla, game, drpg=None):
    base = [int(row["base_" + s]) for s in STATS]
    apt = [int(row["apt_" + s]) for s in STATS]
    donor_name = vanilla.get(tuple(base))
    donor = base if donor_name else None
    if src is None:
        labels = ["donor" if donor else "adapted"] * 8
        return dict(base=base, apt=apt, base_labels=labels, apt_labels=labels, source=None,
                    donor=donor_name, cause="no source row recorded", oracle=oracle(base), flags=row_flags(base))
    sb = src["base"]
    sa = src.get("apt") or [None] * 8
    bl = label_vector(base, sb, donor)
    al = label_vector(apt, sa, apt if donor_name else None, scale_ok=False)
    dist = profile_distance(base, sb)
    extra = {}
    if game == "drpg" and drpg:                                  # RPG has no SP/HIT/aptitudes: those are filled
        donor_base, med = drpg["donor_base"], drpg["medians"]
        proposed = drpg_map(sb, donor_base, med)
        dist = drpg_profile_distance(base, sb, donor_base, med)
        if not donor_name:
            bl = [("scaled" if abs(base[k] - proposed[k]) <= 1 else "adapted") if k in DRPG_STATS else
                  ("donor" if base[k] == donor_base[k] else "adapted") for k in range(8)]
            al = ["donor" if apt == drpg.get("donor_apt") else "adapted"] * 8
        extra = dict(proposed=proposed, proposed_oracle=oracle(proposed),
                     proposed_distance=drpg_profile_distance(proposed, sb, donor_base, med))
    return dict(base=base, apt=apt, source=dict(base=sb, apt=sa, name=src.get("name", "")),
                base_labels=bl, apt_labels=al, donor=donor_name, **extra,
                profile_distance=dist, cause=likely_cause(base, sb, donor_name),
                oracle=oracle(base), source_oracle=oracle(sb) if None not in sb else None, flags=row_flags(base))


# ------------------------------------------------------------------------------------------- DRPG mapping
DRPG_STATS = (0, 2, 3, 4, 5, 7)                   # HP ATK DEF INT RES SPD: what an RPG character has
DRPG_DONOR_ID = 40                                # Seraphina: the template donor every DRPG pack carries today


def drpg_medians(rpg_rows):
    """per-stat median lv1 value over the RPG unique cast (unique_flg 1): the RPG side of the scale"""
    cast = [r["base"] for r in rpg_rows.values() if r.get("unique") == 1 and all(r["base"][k] for k in DRPG_STATS)]
    return {k: statistics.median(b[k] for b in cast) for k in DRPG_STATS}


def drpg_map(src_base, donor_base, medians):
    """DECISION-PENDING proposal (STATORACLE1): profile-preserving RPG -> D5 base stats.
    HP ATK DEF INT RES: each RPG stat relative to the RPG cast median scales the donor's same stat, then the five are
    renormalised to the donor's five-stat total (the donor's D5 tier).  SPD (flat in RPG: spd_per_lv is 0) is scaled
    on its own, not renormalised, so weak RPG units do not pour their total into SPD.  SP, HIT and the aptitudes
    (no RPG equivalent) stay donor."""
    grow = (0, 2, 3, 4, 5)
    raw = {k: donor_base[k] * src_base[k] / medians[k] for k in grow}
    f = sum(donor_base[k] for k in grow) / sum(raw.values())
    out = list(donor_base)
    for k in grow:
        out[k] = max(1, min(255, round(raw[k] * f)))   # <= 255: the level-up growth is the low byte of the base
    out[7] = max(1, min(255, round(donor_base[7] * src_base[7] / medians[7])))
    return out


def drpg_profile_distance(built, src_base, donor_base, medians):
    """L1 distance of cast-relative profiles: built / donor (D5 side) vs source / RPG median (RPG side)"""
    rb = profile([built[k] / donor_base[k] for k in DRPG_STATS])
    rs = profile([src_base[k] / medians[k] for k in DRPG_STATS])
    return round(sum(abs(a - b) for a, b in zip(rb, rs)), 4)


GAME_OF = {"D4_": "d4", "D1C_": "d1c", "DD2_": "dd2", "DRPG_Core_": "drpg", "DRPG_Sample_": "drpg"}


def game_of(folder):
    return next((g for p, g in GAME_OF.items() if folder.startswith(p)), None)


def drpg_context(vanilla_rows, rpg_rows):
    d = next(r for r in vanilla_rows if r["id"] == DRPG_DONOR_ID)
    return dict(donor_id=DRPG_DONOR_ID, donor_base=[d["base_" + s] for s in STATS],
                donor_apt=[d["apt_" + s] for s in STATS], medians=drpg_medians(rpg_rows))


def survey(mods_root, vanilla_rows, tables, only=None):
    """every installed importer pack: per row labels + oracle; tables = {game: {source id: row}}"""
    vanilla = vanilla_index(vanilla_rows)
    drpg = drpg_context(vanilla_rows, tables["drpg"]) if tables.get("drpg") else None
    out = []
    for mod in sorted(Path(mods_root).iterdir()):
        game = game_of(mod.name)
        if not game or (only and game not in only) or not (mod / "mod.json").is_file():
            continue
        rows = built_rows(mod)
        for row, sid in source_ids(mod, rows):
            src = tables.get(game, {}).get(sid) if sid is not None else None
            c = compare_row(row, src, vanilla, game, drpg)
            c.update(game=game, mod=mod.name, id=row["id"], name=row.get("name_EN", ""), tier=row.get("tier", 0),
                     source_id=sid)
            out.append(c)
    return out


def rank_agreement(results, game):
    """per stat: Spearman rank correlation of built vs source over the game's tier-0 rows (cast order kept?)"""
    rows = [r for r in results if r["game"] == game and r["source"] and r["tier"] == 0]
    out = {}
    for k, s in enumerate(STATS):
        pairs = [(r["base"][k], r["source"]["base"][k]) for r in rows if r["source"]["base"][k] is not None]
        if len(pairs) < 3:
            out[s] = None
            continue

        def ranks(v):
            order = sorted(range(len(v)), key=lambda i: v[i])
            rk = [0.0] * len(v)
            i = 0
            while i < len(v):
                j = i
                while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                    j += 1
                for t in range(i, j + 1):
                    rk[order[t]] = (i + j) / 2
                i = j + 1
            return rk
        a, b = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
        try:
            out[s] = round(statistics.correlation(a, b), 3)
        except statistics.StatisticsError:
            out[s] = None
    return out


# ------------------------------------------------------------------------------------------- the gate
DECLARED = {"exact": ("exact stored source bases", "exact"), "donor": ("donor stats", "donor"),
            "adapted": ("adapted",), "scaled": ("scaled",)}


def declared_label(mod, features_stats=None):
    """what the pack says about its stats: features['stats'] if it is a fidelity word, else mod.json text"""
    if features_stats in LABELS:
        return features_stats
    meta = json.loads((Path(mod) / "mod.json").read_text())
    text = json.dumps(meta).lower()
    for f in Path(mod).glob("*receipt*.json"):
        st = (json.loads(f.read_text()).get("features") or {}).get("stats")
        if st in LABELS:
            return st
    if any(t in text for t in ("exact stored source bases", "exact source stored bases", "static stats",
                                "stored stats")):
        return "exact"
    if "donor stats" in text:
        return "donor"
    return None


def stat_label_gate(mod, game, vanilla_rows, table, features_stats=None):
    """(ok, why, record): the pack declares a stat label and the oracle agrees with it.
    Label only: how close a scaled/adapted row is never fails; a claim the rows contradict does."""
    rows = built_rows(mod)
    if not rows:
        return True, "no char rows", {}
    vanilla = vanilla_index(vanilla_rows)
    drpg = drpg_context(vanilla_rows, table) if game == "drpg" and table else None
    recs = []
    for row, sid in source_ids(mod, rows):
        src = table.get(sid) if sid is not None else None
        c = compare_row(row, src, vanilla, game, drpg)
        covered = [k for k in range(8) if src is None or src["base"][k] is not None]
        recs.append(dict(id=row["id"], source_id=sid, base=summarize([c["base_labels"][k] for k in covered]),
                         filled={STATS[k]: c["base_labels"][k] for k in range(8) if k not in covered},
                         apt=summarize(c["apt_labels"]), flags=c["flags"],
                         oracle={lv: c["oracle"][lv]["nominal"] for lv in ("1", "100", "9999")}))
    computed = {r["base"] for r in recs}
    declared = declared_label(mod, features_stats)
    record = dict(declared=declared, computed=sorted(computed), rows=recs)
    if declared is None:
        return False, f"no stat fidelity label declared; oracle says {sorted(computed)}", record
    contradiction = [r for r in recs if r["base"] != declared and not
                     (declared == "adapted" and r["base"] != "exact")]
    if contradiction:
        return False, (f"declared '{declared}' but oracle labels "
                       + ", ".join(f"{r['id']}={r['base']}" for r in contradiction[:4])), record
    return True, "", record
