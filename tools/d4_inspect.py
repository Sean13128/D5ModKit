"""Inspect Disgaea 4 Complete+ source data before importing it (read-only; nothing is written except --export).

  python tools/d4_inspect.py --d4 "<D4 install>" class 1080          # a class: battle profile, evilities, skills
  python tools/d4_inspect.py --d4 "<D4 install>" classes            # every class family (rank 1 rows)
  python tools/d4_inspect.py --d4 "<D4 install>" evility 392        # evilities by id or by name text
  python tools/d4_inspect.py --d4 "<D4 install>" skill "Lift"       # skills by id or by name text
  python tools/d4_inspect.py --d4 "<D4 install>" voice 1080 1081 1082 --export DIR
        # voice lines of groups (a class's personalities are first_id .. +2); --export writes PCM WAVs named
        # <line>_p<group-offset>_c<native-categories>.wav; audio export is a decoded PCM comparison copy

Add --json for machine-readable output.  The mapping status shown for evilities/skills comes from
d5lib/sourcemaps/d4.json (see docs/D4_IMPORT.md).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import wave

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import d4source, sourceimports, offlinepaths  # noqa: E402


def _mapped(kind, d4id, mapping):
    m = mapping.get(kind, {}).get(str(d4id))
    if not m:
        return "unmapped"
    target = m.get("works_like_name") or m.get("copy_of_name") or ""
    return m["relation"] + (f" -> {target}" if target else "")


def cmd_class(d4, mapping, args):
    prof = d4.class_profile(args.id, args.ranks)
    if args.json:
        return prof
    first = prof[0]
    print(f"{first['name']} ({first['id']}..{prof[-1]['id']})")
    for r in prof:
        b = r["battle"]
        print(f"  rank {r['tier'] + 1} {r['title']:16s} base {r['base']} apt {r['aptitudes']}")
        print(f"      MOV {b['MOV']} JMP {b['JMP']} throw {b['throw']} counter {b['counter']} crit {b['crit']} "
              f"fire/wind/ice {b['res_fire']}/{b['res_wind']}/{b['res_ice']} gender "
              f"{'male' if b['kind_gender'] % 10 == 1 else 'female' if b['kind_gender'] % 10 == 2 else b['kind_gender']}"
              f"{' flies' if b['move_type'] == 1 else ''} range {b['attack_range']}")
        ev = [r["innate_evility"]] + r["evilities"]
        print("      evilities: " + "; ".join(f"{e.get('name')} [{e['id']}: {_mapped('evilities', e['id'], mapping)}]"
                                           for e in ev if e["id"]))
        print("      skills:    " + "; ".join(f"{s.get('name')} Lv{s['level']} [{s['id']}: {_mapped('skills', s['id'], mapping)}]"
                                           for s in r["skills"]))


def cmd_classes(d4, mapping, args):
    out = [dict(id=c["id"], name=c["name"], title=c["title"], gender=c["kind_gender"])
           for i, c in sorted(d4.chars.items()) if 1000 <= i < 2400 and i % 10 == 0 and c["name"]]
    if args.json:
        return out
    for c in out:
        print(f"{c['id']:5d} {c['name']:20s} {c['title']}")


def _search(table, query):
    if query.isdigit():
        return {int(query): table[int(query)]} if int(query) in table else {}
    return {k: v for k, v in table.items() if query.lower() in (v.get("name", "") + " " + v.get("desc", "")).lower()}


def cmd_evility(d4, mapping, args):
    found = _search(d4.evilities, args.query)
    if args.json:
        return found
    for k, v in sorted(found.items()):
        text = v["desc"].replace("%d", str(v.get("value", "?"))).replace("%%", "%")
        print(f"{k:5d} {v['name']:22s} mana {v['mana']:<10d} {text}  [{_mapped('evilities', k, mapping)}]")


def cmd_skill(d4, mapping, args):
    found = _search(d4.skills, args.query)
    if args.json:
        return found
    for k, v in sorted(found.items()):
        print(f"{k:6d} {v['name']:24s} {v['desc']}  [{_mapped('skills', k, mapping)}]")


def cmd_voice(d4, mapping, args):
    export = None
    if args.export:
        export = offlinepaths.offline_output(args.export, (Path(__file__).resolve().parents[1], d4.root))
        if export.exists():
            raise ValueError("voice export requires a new directory")
    lines = d4.voice_lines(set(args.groups))
    out = [{k: v for k, v in l.items() if k != "riff"} for l in lines]
    if args.export:
        from d5lib import sfx
        import numpy as np
        d = export
        d.mkdir(parents=True)
        for l, o in zip(lines, out):
            a, rate = sfx.read_wav(l["riff"])
            a = a.mean(axis=1) if a.ndim == 2 else a
            p = d / f"{l['line']}_p{l['group'] - min(args.groups)}_c{'-'.join(map(str, l['native_active_categories'])) or 'none'}.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes((np.clip(a, -1, 1) * 32767).astype("<i2").tobytes())
            o["file"] = str(p)
            o["seconds"] = round(len(a) / rate, 2)
    if args.json:
        return out
    for o in out:
        print(f"{o['line']:6d} group {o['group']} native categories {o['native_active_categories']} "
              f"rate input {o['native_rate_input_signed']} legacy raw flags {o['flags']} "
              f"{o.get('seconds', '')} {o.get('file', '')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--d4", required=True, type=Path, help="Disgaea 4 Complete+ install folder")
    ap.add_argument("--lang", default="EN")
    ap.add_argument("--mapping", type=Path, help="mapping JSON (default d5lib/sourcemaps/d4.json)")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("class")
    c.add_argument("id", type=int)
    c.add_argument("--ranks", type=int, default=6)
    sub.add_parser("classes")
    for name in ("evility", "skill"):
        sub.add_parser(name).add_argument("query")
    v = sub.add_parser("voice")
    v.add_argument("groups", type=int, nargs="+")
    v.add_argument("--export", type=Path)
    args = ap.parse_args()
    if args.cmd == "voice" and args.export:
        offlinepaths.offline_output(args.export, (Path(__file__).resolve().parents[1], args.d4))
        if args.export.exists():
            ap.error("voice export requires a new directory")
    d4 = d4source.D4Data(args.d4, args.lang)
    mapping = sourceimports.load_d4_mapping(args.mapping)
    result = globals()["cmd_" + args.cmd](d4, mapping, args)
    if args.json:
        print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
