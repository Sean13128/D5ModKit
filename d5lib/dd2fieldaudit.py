"""DD2 source-versus-built field audit (DD2FIELDS1): report and gate.

For every built DD2 pack (a folder with mod.json and patches/db/char.dat.json) it reads the pack's source ranks, looks
the same rows up in the Disgaea D2 `char.dat` (START_4.dat, 558 rows x 676 bytes) and compares the battle block the
unit builder copies to the unit with the built D5 row:

    MOV, flying (move_type), attack range, JMP, throw, counter, crit, resistances fire/wind/ice, the seven weapon
    aptitudes, kind/gender, immunity (none or all)

and, for a unique, the default palette: every opaque entry of the built bank's slot 0 must be a colour of the source
palette the row selects (+0x28B).  The earlier DD2 importer inherited all of these from the D5 donor row, which no
other gate noticed (SRCFID2-DD2, 2026-11-23: 385 of 2830 value comparisons differed, 12 of 12 packs).

The offsets are written out here on purpose and independently of `d5lib/dd2source.py`; the evidence for each one is in
Research/import-checklist/source-values/dd2-FIELD-MAP.md.  Fields that stay on the donor (HL, EXP, Mana, is_unique,
Star and weapon resistances) are listed as `donor` and never fail the gate.

    python tools/dd2_field_audit.py --mods DIR [--source-root DIR] [--json OUT] [--gate]

The importer runs `audit_pack` as the gate `source_fields` on every DD2 pack it builds with `dd2_source_fields` on.

Exit 0 unless --gate is given and a carried field differs from the source (or a palette check fails).
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


CHAR_STRIDE, CHAR_COUNT = 676, 558

# D5 field -> (offset, struct format).  Read here, not imported from the importer.
CARRIED = {
    "MOV": (0x1A2, ">H"), "attack_range": (0x1A6, ">H"),
    "JMP": (0x28D, ">B"), "throw": (0x290, ">B"), "counter": (0x291, ">B"), "crit": (0x292, ">B"),
    "res_fire": (0x285, ">b"), "res_wind": (0x286, ">b"), "res_ice": (0x287, ">b"),
    "mastery_fist": (0x27C, ">B"), "mastery_sword": (0x27D, ">B"), "mastery_spear": (0x27E, ">B"),
    "mastery_bow": (0x27F, ">B"), "mastery_gun": (0x280, ">B"), "mastery_axe": (0x281, ">B"),
    "mastery_staff": (0x282, ">B"), "kind_gender": (0x289, ">B"),
}
FLAG = (0x1A4, ">H")            # flying -> move_type 0/1
IMMUNITY = (0x000, ">i")        # 0 -> 0, 0x0FFFFFFF -> -1, anything else stays donor
DONOR = {"hl_value": (0x1A8, ">H"), "exp_value": (0x1AA, ">H"), "mana_value": (0x1B0, ">H"), "is_unique": (0x298, ">B")}
PALETTE = (0x28B, ">B")
ALL_BITS = 0x0FFFFFFF


def load_rows(source):
    """{char id: 676-byte row} from a NISPACK path, an in-memory char.dat, or a mapping {'char.dat': bytes}."""
    if isinstance(source, (str, Path)):
        from d5lib import dd2source
        raw = dd2source.Nispack(Path(source).read_bytes()).read("char.dat")
    elif isinstance(source, dict):
        raw = source["char.dat"]
    else:
        raw = source
    raw = bytes(raw)
    count = struct.unpack_from(">H", raw, 0)[0]
    if count != CHAR_COUNT or len(raw) != 4 + count * CHAR_STRIDE:
        raise ValueError(f"char.dat is not {CHAR_COUNT} x {CHAR_STRIDE} bytes")
    rows = {}
    for index in range(count):
        row = raw[4 + index * CHAR_STRIDE: 4 + (index + 1) * CHAR_STRIDE]
        rows[struct.unpack_from(">H", row, 0x194)[0]] = row
    return rows


def expected(row):
    """Independent reading of one source row -> {D5 field: value} for the carried fields."""
    out = {name: struct.unpack_from(fmt, row, offset)[0] for name, (offset, fmt) in CARRIED.items()}
    out["move_type"] = struct.unpack_from(FLAG[1], row, FLAG[0])[0]
    mask = struct.unpack_from(IMMUNITY[1], row, IMMUNITY[0])[0]
    if mask == 0:
        out["immunity_flags"] = 0
    elif mask == ALL_BITS:
        out["immunity_flags"] = -1
    return out


def built_rows(pack):
    patch = json.loads((Path(pack) / "patches/db/char.dat.json").read_text())
    rows = patch.get("added")
    if not rows:
        raise ValueError(f"{pack}: patches/db/char.dat.json has no added rows")
    return rows


def palette_check(pack, row):
    """-> dict(checked, entries, in_source, fraction) for a unique's slot 0 against the source default palette, or None."""
    try:
        from d5lib.importers import _dd2_source as _src
        sys.path.insert(0, str(_src.forge_root()))
        import numpy.testing  # noqa: F401  (the reader package expects it imported first)
        from forge.backend.d2_character_export import anm_pages
        from forge import nisfiles
        from d5lib import anm, gamefs
        from d5lib.importers import _dd2_prepare as prep, _dd2_source as src
    except Exception as exc:                                         # pragma: no cover - needs the reader package
        return dict(checked=False, reason=f"readers unavailable: {type(exc).__name__}")
    palette = struct.unpack_from(PALETTE[1], row, PALETTE[0])[0]
    body = struct.unpack_from(">h", row, 0x196)[0]
    data = src.data_dir(None)
    raw = nisfiles.expand(prep.archive_member(data, "ANM_HI", f"anm{body:05d}.lzs")[0])
    banks = {}
    for page in anm_pages(raw, include_rgba=False, palette_indices=[palette]):
        banks.setdefault(page["palette"], page["colors"])
    colours = {tuple(int(x) for x in c[:3]) for c in banks[palette]}
    files = sorted((Path(pack) / "files/Anime/ANM_HI_JP.dat").glob("anm*.lzs"))
    for path in files:
        bank = anm.parse(gamefs.decode_member(path.read_bytes()))
        if len(bank.palettes) < 2:
            continue
        slot0 = anm.get_palette(bank, 0)
        used = [tuple(int(x) for x in slot0[i, :3]) for i in range(len(slot0)) if slot0[i, 3]]
        hit = sum(1 for c in used if c in colours)
        return dict(checked=True, source_palette=palette, entries=len(used), in_source=hit,
                    fraction=round(hit / len(used), 4) if used else 0.0, file=path.name)
    return dict(checked=False, reason="no multi-palette bank in the pack")


def audit_pack(pack, rows, *, palettes=True):
    """One pack -> dict(pack, ranks=[...], mismatches=[...], donor=[...], palette=...)."""
    pack = Path(pack)
    meta = json.loads((pack / "mod.json").read_text())
    si = meta["source_import"]
    built = built_rows(pack)
    out = dict(pack=pack.name, ranks=[], mismatches=[], donor=[], palette=None,
               carried_by_importer=bool(si.get("battle_fields")))
    if len(built) != len(si["source_ranks"]):
        raise ValueError(f"{pack.name}: {len(built)} built rows for {len(si['source_ranks'])} source ranks")
    for k, (rank, b) in enumerate(zip(si["source_ranks"], built)):
        row = rows[rank["id"]]
        want = expected(row)
        differing = {}
        for field, value in want.items():
            if b.get(field) != value:
                differing[field] = dict(source=value, built=b.get(field))
                out["mismatches"].append(dict(rank=k, source_id=rank["id"], field=field, source=value, built=b.get(field)))
        for field, (offset, fmt) in DONOR.items():
            value = struct.unpack_from(fmt, row, offset)[0]
            out["donor"].append(dict(rank=k, field=field, source=value, built=b.get(field), equal=value == b.get(field)))
        mask = struct.unpack_from(IMMUNITY[1], row, IMMUNITY[0])[0]
        if mask not in (0, ALL_BITS):
            out["donor"].append(dict(rank=k, field="immunity_flags", source=mask, built=b.get("immunity_flags"), equal=False,
                                     note="partial D2 mask: bit order differs from D5, not carried"))
        out["ranks"].append(dict(rank=k, source_id=rank["id"], compared=len(want), differing=sorted(differing)))
    if palettes and meta.get("category") == "characters":
        out["palette"] = palette_check(pack, rows[si["source_ranks"][0]["id"]])
    return out


def run(mods, source, packs=None, *, palettes=True):
    rows = load_rows(source)
    mods = Path(mods)
    names = packs or sorted(p.name for p in mods.iterdir() if p.name.startswith("DD2_") and (p / "mod.json").is_file())
    results = [audit_pack(mods / n, rows, palettes=palettes) for n in names]
    failed = [r["pack"] for r in results
              if r["mismatches"] or (r["palette"] and r["palette"].get("checked") and r["palette"]["fraction"] < 1.0)]
    total = sum(sum(x["compared"] for x in r["ranks"]) for r in results)
    return dict(schema="dd2-field-audit/1", mods=str(mods), compared=total,
                mismatches=sum(len(r["mismatches"]) for r in results), failed_packs=failed, packs=results)


def render(report):
    lines = [f"DD2 field audit: {len(report['packs'])} packs, {report['compared']} carried-field comparisons, "
             f"{report['mismatches']} differ from the source row"]
    for r in report["packs"]:
        by = {}
        for m in r["mismatches"]:
            by.setdefault(m["field"], []).append(m)
        pal = r.get("palette") or {}
        palette = (f"palette {pal['source_palette']}: {pal['in_source']}/{pal['entries']} slot-0 colours in the source bank"
                   if pal.get("checked") else "")
        status = "PASS" if r["pack"] not in report["failed_packs"] else "FAIL"
        lines.append(f"  {status} {r['pack']:<18} differing {len(r['mismatches']):>3}  "
                     + ", ".join(f"{f} x{len(v)}" for f, v in sorted(by.items())) + ("  " + palette if palette else ""))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mods", type=Path, required=True, help="folder of built DD2_* packs (a staged mods folder or the install)")
    ap.add_argument("--source-root", type=Path, help="a START_4.dat path (default: the prepared DD2 source folder)")
    ap.add_argument("--packs", help="comma-separated pack folders (default: every DD2_* pack in --mods)")
    ap.add_argument("--json", type=Path, help="write the full report here")
    ap.add_argument("--no-palette", action="store_true", help="skip the unique default-palette check")
    ap.add_argument("--gate", action="store_true", help="exit 1 when a carried field or palette differs from the source")
    args = ap.parse_args(argv)
    source = args.source_root
    if source is None:
        from d5lib.importers import _dd2_source as src
        source = src.data_dir(None).path("START_4.dat")
    report = run(args.mods, source, [p for p in (args.packs or "").split(",") if p] or None, palettes=not args.no_palette)
    print(render(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    return 1 if args.gate and report["failed_packs"] else 0

