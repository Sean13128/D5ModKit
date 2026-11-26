"""One import command per source game: runner, result types, shared gates, compare.

See Subprojects/Engine-Extensions/IMPORTCORE-INTERFACE.md.  An importer plugin
(`d5lib/importers/<game>.py`) supplies `Importer.roster()` / `Importer.build()`;
this module owns everything that must behave the same for every game:

  * the CLI-shaped run loop (`run`), `--only` selection and per-entry failures,
  * `Entry` / `Result` records and `results.json` / `REPORT.md`,
  * shared gates: mod structure, strict db-patch readback (the logic of
    `Tools/check_dbpatches.py`), the wheel-freeze rule (exactly the installed
    bank's palette and image-header counts, of the same folder) and the
    builder's own finalization status,
  * `--compare-installed`: per-file comparison against the installed kit copy,
    classified `identical` / `expected` (with a named reason) / `regression` /
    `new`.

Read-only toward the installed kit, the Steam game and saves.  Builds are
dispatched to subprocesses by the plugin; this module never writes outside the
`--out` tree.

Prior art: `Tools/check_dbpatches.py` (QUICKFIX1) for the strict patch gate,
`d5lib/dbpatch.py` (the installer's loader it uses), `d5lib/anm.py` for palette
and image-header counts, and the per-game builders the plugins wrap.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import hashlib
import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from . import offlinepaths

ROOT = Path(__file__).resolve().parents[1]
DB_ARCHIVE = "Database/Database_0.dat"


def safe_name(value):
    """A filesystem-safe directory name for an entry id (`d4:1030` -> `d4-1030`).

    Entry ids are identifiers, not filenames.  A ':' in the build tree is not just
    cosmetic: the Zig compile of `d5auto.dll` keeps its scratch cache under the
    output tree, and Zig fails to parse its own `tmp/*.obj.d` manifests on a macOS
    path containing ':' (`ir: read_dir` / `stat_file`) — measured, CORED4B.
    """
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value)

FEATURES = ("stand", "walk", "attack", "hurt", "carried", "face", "cutin", "stats",
            "skills", "evilities", "voice", "specials", "ranks", "recruit")


@dataclasses.dataclass
class Entry:
    id: str
    kind: str                     # "class" | "unique"
    name: str
    mod_folder: str
    source_ref: dict = dataclasses.field(default_factory=dict)
    in_scope: bool = True
    why_not: str = ""
    detail: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Result:
    id: str
    mod_folder: str
    built: bool = False
    error: str = ""
    gates: dict = dataclasses.field(default_factory=dict)
    features: dict = dataclasses.field(default_factory=dict)
    notes: list = dataclasses.field(default_factory=list)
    compare: str = ""
    compare_reason: str = ""
    seconds: float = 0.0
    log: str = ""
    extra: dict = dataclasses.field(default_factory=dict)

    def gate_ok(self):
        return self.built and all(bool(v) for v in self.gates.values())


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_importer(game):
    mod = importlib.import_module(f"d5lib.importers.{game}")
    imp = mod.Importer()
    if imp.game != game:
        raise ValueError(f"importer {game} reports game {imp.game!r}")
    return imp


def as_entry(item):
    """Normalize a roster item: the interface allows an Entry or the equivalent dict."""
    if isinstance(item, Entry):
        return item
    d = dict(item)
    return Entry(id=d["id"], kind=d.get("kind", ""), name=d.get("name", ""),
                 mod_folder=d["mod_folder"], source_ref=d.get("source_ref") or {},
                 in_scope=bool(d.get("in_scope", True)), why_not=d.get("why_not") or "",
                 detail=d.get("detail") or {})


# --------------------------------------------------------------------------- gates
def stat_label_gate(mod, game, declared, ctx, cache):
    """STATORACLE1: the pack's stat fidelity label is present and the rows agree with it (d5lib.statfidelity).
    Label only: never fails on how close the stats are, only on a missing label or a claim the rows contradict.
    The per-row labels and the creation/recalc oracle (levels 1/100/9999) go into results.json (extra.stat_oracle)."""
    from . import statfidelity as sf
    try:
        if "stat_vanilla" not in cache:
            from .importers.dd2 import original_fs
            from . import database
            fs = original_fs(dict(game_path=ctx["game_path"], state_root=ctx["state_root"]))
            cache["stat_vanilla"] = [r.to_dict() for r in
                                     database.load_table("char.dat", fs.read(DB_ARCHIVE + "/char.dat")).rows]
        key = f"stat_source_{game}"
        if key not in cache:
            opts = ctx.get("options") or {}
            readers = dict(d4=lambda: sf.d4_rows(ctx.get("source_root")), d1c=sf.d1c_rows,
                           dd2=lambda: sf.dd2_rows(ctx.get("source_root")),
                           drpg=lambda: sf.drpg_rows(opts["drpg_master_cache"]) if opts.get("drpg_master_cache") else {})
            cache[key] = readers[game]() if game in readers else {}
        return sf.stat_label_gate(mod, game, cache["stat_vanilla"], cache[key], declared)
    except Exception as exc:                                   # noqa: BLE001  (no clean copy / source table)
        return False, f"stat oracle unavailable: {type(exc).__name__}: {exc}", {}


def structure_gate(mod):
    """mod.json parses, every patches/**/*.json parses, no absolute/escaping paths."""
    if not (mod / "mod.json").is_file():
        return False, "mod.json missing"
    try:
        meta = json.loads((mod / "mod.json").read_text())
    except Exception as exc:                                   # noqa: BLE001
        return False, f"mod.json: {exc}"
    if not meta.get("files") and not meta.get("name"):
        return False, "mod.json has no name/files"
    for path in sorted(mod.rglob("*.json")):
        rel = path.relative_to(mod)
        if rel.is_absolute() or ".." in rel.parts:
            return False, f"unsafe patch path {rel}"
        try:
            json.loads(path.read_text())
        except Exception as exc:                               # noqa: BLE001
            return False, f"{rel}: {exc}"
    return True, ""


_BARE_PERCENT = re.compile(r"%(?![ds%0-9])")


def text_gate(mod):
    """No bare `%` in any added/changed text field of `patches/db/*.json` (magic, Skill, charhelp, char, Quest...).

    The game feeds these strings to printf-style formatters, so a `%` that is not `%d`/`%s`/`%%`/a width
    digit is a crash class (D4-FIX5: u230 magic 13023 "30% Amnesia"); prose uses the full-width `％`
    (`textfmt.prose`, applied by both `set_langs` writers).  `%%` pairs are removed before the scan.
    """
    bad = []
    for pf in sorted((Path(mod) / "patches/db").glob("*.json")):
        try:
            doc = json.loads(pf.read_text())
        except Exception:                                      # noqa: BLE001  (structure_gate reports bad JSON)
            continue
        rows = [*(doc.get("added") or []), *((doc.get("rows") or {}).values())]
        for row in rows:
            for field, v in (row.items() if isinstance(row, dict) else ()):
                if isinstance(v, str) and _BARE_PERCENT.search(v.replace("%%", "")):
                    bad.append(f"{pf.name} {row.get('id', '?')}.{field}")
    return (not bad), ("bare % in " + ", ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "") if bad else "")


def dbpatch_gate(mods, game_path, state_root, table_cache=None):
    """Strict `dbpatch.apply_patch` over the bundle, on the game's own tables.

    Same loader call as `Tools/check_dbpatches.py` (strict=True), so a patch that
    names an unknown field fails here instead of dropping text on install.
    """
    from d5lib import database, dbpatch, gamefs, modsys
    game_path, state_root = Path(game_path), Path(state_root)
    if not (state_root / "backups.json").is_file():
        return False, f"no original backup state at {state_root}"
    installer = modsys.Installer(str(game_path), str(ROOT), log=lambda *a: None)
    fs = gamefs.GameFS(str(game_path), backup_resolver=installer.backup_resolver)
    tables = table_cache if table_cache is not None else {}
    failures = []
    try:
        for mod in sorted(Path(mods).iterdir()):
            db = mod / "patches/db"
            if not db.is_dir():
                continue
            for pf in sorted(db.glob("*.json")):
                try:
                    doc = json.loads(pf.read_text())
                except Exception as exc:                       # noqa: BLE001
                    failures.append(f"{mod.name}/{pf.name}: {exc}")
                    continue
                member = doc.get("table") or pf.name[:-5]
                if member not in tables:
                    try:
                        tables[member] = database.load_table(member, fs.read(DB_ARCHIVE + "/" + member))
                    except KeyError:
                        failures.append(f"{mod.name}/{pf.name}: table not in archive")
                        continue
                try:
                    dbpatch.apply_patch(tables[member], doc, strict=True)
                except Exception as exc:                       # noqa: BLE001
                    failures.append(f"{mod.name}/{pf.name}: {type(exc).__name__}: {exc}")
    finally:
        fs.reset()
    return (not failures), "; ".join(failures[:4])


# --------------------------------------------------------------------------- SCHEMA1 gates
# Field names are Sorrow's (research-20261014/database_fields.json); the legacy `unk_*` names are what packs built before
# SCHEMA1 still carry, so both spellings are read.
EXP_YIELD = ("exp_yield_weight", "unk_0E0")        # char.dat +0xE0, Sorrow VERIFIED
MANA_YIELD = ("mana_yield_rate", "unk_0EC")        # char.dat +0xEC, Sorrow PROBABLE (schema name stays unk_0EC)
BOUNTY_FIELDS = (("bounty_target_mode", "unk_15E4"), ("bounty_target_char_id", "unk_15E8"),
                 ("bounty_drop_item_id", "unk_15EC"), ("bounty_drop_permille", "unk_15F0"),
                 ("bounty_stage_id", "unk_15F4"))
MIN_LEVEL = ("min_level", "unk_138")
MODE_RESTRICTION = ("mode_restriction", "unk_15F8")  # 0 none, 1 normal mode only, 2 post-game only
MAX_LEVEL = 9999
YIELD_LABELS = ("source", "approximation")


def _pick(row, names, default=0):
    for n in names:
        if n in row:
            return row[n]
    return default


def _added_rows(mod, member):
    f = Path(mod) / "patches/db" / member
    if not f.is_file():
        return []
    try:
        return list(json.loads(f.read_text()).get("added") or [])
    except Exception:                                          # noqa: BLE001  (structure_gate reports bad JSON)
        return []


def yield_gate(mod):
    """Imported char rows carry `exp_yield_weight` / `mana_yield_rate` from the source game or a labelled approximation.

    The label is `mod.json` -> `source_import.yield_source`: {"exp_yield_weight": "source"|"approximation",
    "mana_yield_rate": ..., "note": "<why, required for an approximation>"}.  A field the builder left at the D5
    donor's value (listed in a `gameplay[].unchanged_fields`) never passes when labelled "source".
    """
    rows = _added_rows(mod, "char.dat.json")
    if not rows:
        return True, ""
    try:
        meta = json.loads((Path(mod) / "mod.json").read_text()).get("source_import") or {}
    except Exception:                                          # noqa: BLE001
        meta = {}
    decl = meta.get("yield_source") or {}
    donor_kept = {f for g in meta.get("gameplay") or [] for f in g.get("unchanged_fields") or []}
    bad = []
    for label, names in (("exp_yield_weight", EXP_YIELD), ("mana_yield_rate", MANA_YIELD)):
        lab = decl.get(label)
        if lab not in YIELD_LABELS:
            bad.append(f"{label} unlabelled (would be the D5 donor's value)")
        elif lab == "approximation" and not str(decl.get("note") or "").strip():
            bad.append(f"{label} approximation has no note")
        elif lab == "source" and donor_kept & set(names):
            bad.append(f"{label} labelled source but kept from the D5 donor")
    return (not bad), "; ".join(bad)


def donor_yield(source_note):
    """`source_import.yield_source` for a builder that keeps the D5 donor row's yield fields (every importer today).

    `source_note` says what the source reader holds for EXP/mana yield and why it is not mapped.  A field may be
    labelled "source" only when the builder writes the source game's own number into a D5 field whose meaning is
    VERIFIED on both sides; none is today (docs/IMPORT_YIELD.md has the per-game table).
    """
    return {"exp_yield_weight": "approximation", "mana_yield_rate": "approximation",
            "note": "D5 donor value kept for exp_yield_weight (+224) and mana_yield_rate (+236); " + source_note}


D4_YIELD_NOTE = ("D4 grade +0x1A2 (EXP-curve weight, same code role as D5 +224 but not used per class in D4 kill EXP) "
                 "and mana_value +0x1B2 (level-scaled kill reward rate) not mapped; docs/IMPORT_YIELD.md")
NO_YIELD_FIELD_NOTE = "the {} source reader exposes no EXP/mana yield field"


def recruit_quest_gate(mod):
    """An importer-added Quest row is a plain recruit quest: no bounty fields, sane min_level / mode_restriction."""
    bad = []
    for row in _added_rows(mod, "Quest.dat.json"):
        qid = row.get("id", "?")
        for names in BOUNTY_FIELDS:
            if _pick(row, names):
                bad.append(f"quest {qid} {names[0]}={_pick(row, names)}")
        lvl = _pick(row, MIN_LEVEL)
        if not isinstance(lvl, int) or not 0 <= lvl <= MAX_LEVEL:
            bad.append(f"quest {qid} min_level={lvl!r}")
        mode = _pick(row, MODE_RESTRICTION)
        if mode not in (0, 1, 2):
            bad.append(f"quest {qid} mode_restriction={mode!r}")
    return (not bad), "; ".join(bad[:6])


def learn_skill_gate(mod, magic_ids):
    """Every `learnN_skill` (N <= learn_count) on an imported char row exists in magic.dat.

    Vanilla is not gated: 432 of its learnset ids dangle (Sorrow finding 21, re-measured on the original Database_0.dat).
    ``magic_ids`` = vanilla magic.dat ids plus the ids the bundle adds.
    """
    bad = []
    for row in _added_rows(mod, "char.dat.json"):
        n = min(int(row.get("learn_count") or 0), 16)
        for i in range(1, n + 1):
            sid = row.get(f"learn{i}_skill") or 0
            if sid and sid not in magic_ids:
                bad.append(f"char {row.get('id', '?')} learn{i}_skill={sid}")
    return (not bad), "; ".join(bad[:6])


def unique_skill_gate(mod, maps_dir=None):
    """UNIQUESKILLS1: an imported unique (``D1C_Unique_N`` / ``D4_Unique_N``) with ``learn_count`` 0 fails unless the
    reviewed source map (``d5lib/sourcemaps/{d1c,d4}.json``) says the source game gives it no skills
    (``no_source_skills``, or ``donor_only``: D4GAP1, the source has skills but none has a D5 twin): a unique that learns nothing is recruitable but not playable."""
    m = re.match(r"(D1C|D4)_Unique_(\d+)$", Path(mod).name)
    if not m:
        return True, ""
    maps = Path(maps_dir) if maps_dir else Path(__file__).with_name("sourcemaps")
    doc = json.loads((maps / f"{m.group(1).lower()}.json").read_text())
    entry = (doc.get("characters") or doc.get("uniques") or {}).get(m.group(2)) or {}
    bad = [f"char {r.get('id', '?')} learn_count 0" for r in _added_rows(mod, "char.dat.json")
           if not int(r.get("learn_count") or 0) and not (entry.get("no_source_skills") or entry.get("donor_only"))]
    return (not bad), ("; ".join(bad) + " and the source map does not say 'no skills in source'") if bad else ""


def skill_motion_gate(mod, survey):
    """UNIQUESKILLS1: every learn-list skill's caster motions exist in the unit's battle bank (d5lib/skillmotions.py).

    FAIL = a motion absent from the bank (own bank, plus resident humanoid block 1 for humanoids) that vanilla D5
    never runs absent for that body type.  Absent-but-vanilla-does-it ("fallback") and unresolvable skills
    ("unknown") are counted in the message, not failed."""
    recs = survey.check_mod(mod)
    bad = [f"unit {r['unit']} skill {r['skill']} motion {r['missing']}" for r in recs if r["status"] == "missing"]
    note = "; ".join(bad[:6])
    extra = {k: sum(1 for r in recs if r["status"] == k) for k in ("fallback", "unknown")}
    if not bad and (extra["fallback"] or extra["unknown"]):
        note = f"{extra['fallback']} fallback, {extra['unknown']} unknown"
    return (not bad), note


def magic_ids(mods, game_path, state_root):
    """Vanilla magic.dat ids (original backup, read-only) plus every id the bundle's magic.dat patches add; None if
    the original state is not reachable."""
    from d5lib import database, gamefs, modsys
    ids = set()
    for mod in Path(mods).iterdir():
        for row in _added_rows(mod, "magic.dat.json"):
            ids.add(row.get("id"))
    state_root = Path(state_root)
    if not (state_root / "backups.json").is_file():
        return None
    installer = modsys.Installer(str(game_path), str(ROOT), log=lambda *a: None)
    fs = gamefs.GameFS(str(game_path), backup_resolver=installer.backup_resolver)
    try:
        ids |= {r["id"] for r in database.load_table("magic.dat", fs.read(DB_ARCHIVE + "/magic.dat")).rows}
    finally:
        fs.reset()
    return ids


def schema_gates(mod, ids):
    """-> {gate name: (ok, why)} for one built mod folder (`ids` from `magic_ids`, or None)."""
    out = {"yield": yield_gate(mod), "recruit_quest": recruit_quest_gate(mod)}
    if ids is None and _added_rows(mod, "char.dat.json"):
        out["learn_skills"] = (False, "magic.dat unreachable")
    else:
        out["learn_skills"] = learn_skill_gate(mod, ids or set())
    out["unique_skills"] = unique_skill_gate(mod)
    return out


def pin_installed_icons(mod, installed_mod):
    """REPROFIX1 (d): copy the installed pack's list-icon pairs into the rebuilt ``patches/outfits/outfits.json``.

    A costume's list-icon texturedatabase rows (``icons`` = {class id: [48 px row, 64 px row]}) are allocated when
    the pack is built from the machine's texturedatabase *as it is then*: an isolated rebuild always starts at the
    vanilla end (Creator Asagi 16640: 13173/13990), while the installed pair is where ``modshare`` moved it when
    the pack was imported after others (13427/14244; the shift is the number of icon pairs of the packs imported
    before it, so it differs per pack: +254 here, +205 for Bieko).  The art is the same, only the row ids
    differ.  The installed pair is the freeze reference (saves and load orders may name it), so a rebuild
    reuses it for the class ids both packs declare.  -> {class id: pair} that were changed."""
    mine, theirs = (Path(p) / "patches/outfits/outfits.json" for p in (mod, installed_mod or ""))
    if not (installed_mod and mine.is_file() and theirs.is_file()):
        return {}
    try:
        a, b = json.loads(mine.read_text()), json.loads(theirs.read_text())
    except ValueError:
        return {}
    have, want = a.get("icons") or {}, b.get("icons") or {}
    moved = {k: want[k] for k in have if k in want and list(have[k]) != list(want[k])}
    if moved:
        a["icons"] = dict(have, **{k: list(v) for k, v in moved.items()})
        mine.write_text(json.dumps(a, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return moved


def pin_recorded_icons(mod, recorded):
    """SOURCEPREP4-DRPG: ``pin_installed_icons`` for a machine with no installed pack: the pairs were recorded from the
    installed packs (``drpg-bank-shapes.json`` ``icons``, ids only) and are applied to the same class ids the same way."""
    mine = Path(mod) / "patches/outfits/outfits.json"
    if not (recorded and mine.is_file()):
        return {}
    try:
        a = json.loads(mine.read_text())
    except ValueError:
        return {}
    have = a.get("icons") or {}
    moved = {k: recorded[k] for k in have if k in recorded and list(have[k]) != list(recorded[k])}
    if moved:
        a["icons"] = dict(have, **{k: list(v) for k, v in moved.items()})
        mine.write_text(json.dumps(a, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return moved


# Options that change what a rebuild writes; recorded in mod.json (REPROFIX1 (e)) so a rebuild need not guess them.
# Per game: only the ones that game's importer reads.
RECORDED_OPTIONS = {
    "d1c": ("source_voices", "source_specials", "d1c_faces", "d1c_hold_blank", "d1c_rig"),
    "d4": ("source_voices", "source_specials", "d4_faithful_palettes", "d4_hold_blank",
           "d4_stub_xform", "d4_death_game_view", "d4_source_tracks", "d4_face_rule",
           "d4_mesh_nodes"),
    "dd2": ("source_voices", "source_specials", "dd2_reviewed_abilities", "dd2_hold_blank", "dd2_source_fields", "dd2_cutin_fit"),
    "drpg": ("source_voices", "source_specials", "no_icon_pin", "drpg_stats"),
}


VALUE_OPTIONS = ("drpg_stats", "d1c_faces", "d1c_rig")      # recorded as given, the others as booleans


def pin_installed_faces(mod, installed_mod):
    """REPROFIX1 (a): copy the installed pack's face pictures over the rebuilt pack's (D1C, ``--d1c-faces installed``;
    the default is ``hd`` since D1CHDFACE1).

    The installed D1C packs carry the D1CFACE2 faces (RGBA, own crops, class faces also under
    ``patches/classes``), made by a hand-tuned script from art outside the importer; the importer's own
    source face (opaque ``--d1c-faces opaque`` or the FACEFIX1 cut-out ``cutout``) differs in ~98% of pixels.
    Until hand-made cut-outs land, the installed picture is the reference, so every ``face_*.png`` under
    ``patches/characters`` and ``patches/classes`` of the installed pack replaces or joins the rebuilt one.
    A face only the rebuild has (a sixth colour the install lacks) stays.  -> sorted relative paths copied."""
    import shutil
    if not installed_mod or not Path(installed_mod).is_dir():
        return []
    copied = []
    for sub in ("patches/characters", "patches/classes"):
        for src in sorted((Path(installed_mod) / sub).glob("face_*.png")):
            dst = Path(mod) / sub / src.name
            if dst.is_file() and dst.read_bytes() == src.read_bytes():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied.append(f"{sub}/{src.name}")
    return copied


def record_importer_options(mod, game, options):
    """Write ``source_import.importer_options`` into the pack's mod.json: the importer flags this build used
    (booleans and ``drpg_stats``), plus the entry point.  Source paths and caches are not recorded."""
    path = Path(mod) / "mod.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    rec = {k: (options.get(k) if k in VALUE_OPTIONS else bool(options.get(k)))
           for k in RECORDED_OPTIONS.get(game, ())}
    for k in VALUE_OPTIONS:
        if rec.get(k) is None:
            rec.pop(k, None)
    rec["entry"] = f"tools/import_game.py {game}"
    si = doc.setdefault("source_import", {})
    if si.get("importer_options") == rec:
        return rec
    si["importer_options"] = rec
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return rec


# ASAGI4P (Sean, 2026-11-18, ASK-AD0982): "take the merged 4-page Creator Asagi atlas".  The SHEETFIX1 satellite
# merge gives DRPG look 20055 (HGC Asagi, class 30820, sprite 16650) four atlas pages where the installed bank has
# three; the fourth page (1024x512) holds the look's own merged drawings.  The extra image header is the wheel-count
# change the owner accepted.  A declaration here REPLACES the installed bank as that member's freeze reference --
# it is still compared for *equality* (page sizes included), so the bank cannot change shape again unnoticed, and
# once the rebuilt pack is installed the declaration agrees with the installed bank instead of overriding it.
# Key: (mod folder name, member path under files/).
APPROVED_SHAPE_CHANGES = {
    ("DRPG_Core_CreatorAsagi_20024", "Anime/ANM_HI_JP.dat/anm16650.lzs"):
        dict(textures=4, palettes=10, pages=((1024, 1024), (1024, 1024), (1024, 1024), (1024, 512)),
             why="merged 4-page Creator Asagi atlas (ASAGI4P, Sean 2026-11-18)"),
    ("DRPG_Core_CreatorAsagi_20024", "Anime/ANM_HI_JP.dat/anm16651.lzs"):
        dict(textures=4, palettes=10, pages=((1024, 1024), (1024, 1024), (1024, 1024), (1024, 512)),
             why="companion of the merged 4-page Creator Asagi atlas (ASAGI4P, Sean 2026-11-18)"),
}


def declared_shapes(mod):
    """{member under files/: declaration} an importer recorded in the pack's ``mod.json``
    (``source_import.shape_changes``), for a bank whose shape the build changes on purpose (D1CRIG1: a D1C humanoid
    built from the body's own sheets has the body's page count).  The wheel gate compares such a member with the
    declaration (equality, page sizes too) and names it in its note, exactly like ``APPROVED_SHAPE_CHANGES``; the
    owner still approves the change before an install (the note says so)."""
    path = Path(mod) / "mod.json"
    try:
        si = json.loads(path.read_text(encoding="utf-8")).get("source_import") or {}
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in (si.get("shape_changes") or {}).items() if isinstance(v, dict)}


def wheel_gate(mod, installed_mod, reference=None):
    """Wheel-freeze: the rebuild carries exactly the installed bank's palette and header counts.

    Compares, for every ANM member the rebuild ships that the installed copy also
    ships, the number of textures and palettes (image headers) parsed from the
    decompressed LZS; also counts PNGs the installed copy does not have.  The
    installed bank is the freeze reference, never a source of bytes.

    The comparison is *equality*, the same rule as the D1C importer's own
    ``_wheel_freeze``: a palette is one more image object in the loader's list, so a
    rebuild that drops palettes has changed the bank shape even though it cannot add
    to the wheel's resident set.  The older ``> 0`` test hid exactly that (the 34
    unique banks that went 20 palettes -> 10).

    A member named in ``APPROVED_SHAPE_CHANGES`` is compared against the declared
    shape instead (equality, page sizes too); the returned note names the declaration
    so a build report shows the deliberate change.

    ``reference`` ({relative member: (textures, palettes)}) is an optional recorded
    shape table for a machine with no installed pack (SOURCEPREP4-DD2: the DD2 importer
    passes ``dd2-wheel-reference.json``).  A member the installed copy has is still
    compared with the installed copy itself; the recorded shape only fills in when that
    copy is absent.
    """
    if not mod or not Path(mod).is_dir():
        return True, "no rebuilt bank to compare"
    if (not installed_mod or not Path(installed_mod).is_dir()) and not reference:
        return True, "no installed bank to freeze against"
    root_a = Path(mod) / "files"
    from d5lib import anm, gamefs
    root_b = Path(installed_mod) / "files" if installed_mod and Path(installed_mod).is_dir() else None
    added_png = 0
    worst = []
    declared_notes = []
    declared = declared_shapes(mod)
    for a in sorted(root_a.rglob("*")):
        if not a.is_file():
            continue
        rel = a.relative_to(root_a).as_posix()
        b = root_b / a.relative_to(root_a) if root_b is not None else None
        decl = APPROVED_SHAPE_CHANGES.get((Path(mod).name, rel)) or declared.get(rel)
        recorded = (reference or {}).get(rel)
        if a.suffix.lower() == ".png":
            # A per-colour face picture (patches/characters/face_<id>[_<colour>].png) is written by
            # the kit's own face writer; it is not an image header inside a bank and cannot freeze
            # the wheel. Every other added PNG still counts (CORED1CB).
            if not (b is not None and b.is_file()) and not rel.startswith("patches/characters/face_"):
                added_png += 1
            continue
        if a.suffix.lower() != ".lzs":
            continue
        if decl is None and not (b is not None and b.is_file()) and recorded is None:
            continue
        try:
            fa = anm.parse(gamefs.decode_member(a.read_bytes()))
            fb = anm.parse(gamefs.decode_member(b.read_bytes())) if b is not None and b.is_file() else None
        except Exception:                                      # noqa: BLE001
            continue
        got = (len(fa.textures), len(fa.palettes))
        if decl is not None:
            want = (int(decl["textures"]), int(decl["palettes"]))
            pages = tuple((int(t.width), int(t.height)) for t in fa.textures)
            if got != want:
                worst.append(f"{rel}: {got[1]} palettes/{got[0]} textures, declared {want[1]}/{want[0]} "
                             f"[{decl['why']}]")
            elif decl.get("pages") and pages != tuple(tuple(p) for p in decl["pages"]):
                worst.append(f"{rel}: page sizes {pages}, declared {tuple(decl['pages'])} [{decl['why']}]")
            else:
                same = fb is not None and (len(fb.textures), len(fb.palettes)) == got
                declared_notes.append(f"{rel} {got[1]} palettes/{got[0]} textures [{decl['why']}]"
                                + (" (installed bank already this shape)" if same else
                                   " (installed bank is " + (f"{len(fb.palettes)}/{len(fb.textures)}"
                                                             if fb is not None else "absent") + ")"))
            continue
        if fb is not None:
            want = (len(fb.textures), len(fb.palettes))
            where = "installed"
        elif recorded is not None:
            want = (int(recorded[0]), int(recorded[1]))
            where = "recorded"
        else:
            continue
        if got != want:
            worst.append(f"{rel}: {got[1]} palettes/{got[0]} textures, {where} {want[1]}/{want[0]}")
    if added_png:
        worst.append(f"{added_png} added PNG(s)")
    if not worst and declared_notes:
        return True, "declared shape change: " + "; ".join(declared_notes)
    return (not worst), "; ".join(worst[:4])


def cell_page_gate(mod):
    """D4CELL1: no key-drawn cell indexes a texture page its block does not have.

    Such a cell dangles in the built bank; once the installer's ``ownanim.banner_layout`` repacks the
    atlas onto more pages it draws whatever art lands on that page (the D4 humanoid packs had 144 per
    bank, from D4's shared block).  Only a missing page fails: a cell running past the edge of a page
    that exists ships in vanilla D5 too (anm00021/00031), and is not gated here."""
    from d5lib import anm, gamefs
    bad = []
    for path in sorted((Path(mod) / "files").rglob("anm*.lzs")):
        try:
            a = anm.parse(gamefs.decode_member(path.read_bytes()))
        except Exception:                                      # noqa: BLE001
            continue
        for b in a.blocks:
            pages = len(b.texture_infos) if len(a.blocks) > 1 else len(a.textures)
            n = len({k.cell for k in b.keys if 0 <= k.cell < len(b.cells)
                     and b.cells[k.cell].w and b.cells[k.cell].h and b.cells[k.cell].tex >= pages})
            if n:
                bad.append(f"{path.name} block {b.id}: {n} key-drawn cell(s) on a page past its {pages}")
    return (not bad), "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "")


IDLE_MOTIONS = (1001, 1007)      # front / back idle: what the battle actor selects for a unit standing still


PALETTE_BUFFER_COLOURS = 256     # the game's attack palette buffer 0x1469AF859 (0x1402F9550 copies the count it reads)


def palette_count_gate(mod):
    """WRITEWATCH1: every sprite bank a mod ships has palette counts the game's attack set-up can copy.

    `0x1402F9550` (start_basic_attack / start_skill_action) copies a monster's current palette into a fixed
    256-colour buffer 0x1469AF859, as many colours as the PaletteInfo row's i32 at +4 says, with no clamp.  A count
    above 256 overruns the globals after the buffer: DD2 banks carried D2's big-endian count (0x01000000) and the
    first Attack of DD2 Shark Dragon wrote 18 MB over the dlmalloc mspace handle 0x147B59E30 (write-watch capture,
    WRITEWATCH1-REPORT.md).  Fails a bank with any row count outside 1..256."""
    from d5lib import anm, gamefs
    bad = []
    for path in sorted(Path(mod).glob("files/Anime/*/anm*.lzs")):
        try:
            a = anm.parse(gamefs.decode_member(path.read_bytes()))
        except Exception:                                      # noqa: BLE001  (other gates report unreadable banks)
            continue
        counts = [p.num_colors | p.unk << 16 for b in a.blocks for p in b.palette_infos]
        wild = sorted({c for c in counts if not 0 < c <= PALETTE_BUFFER_COLOURS})
        if wild:
            bad.append(f"{path.name}: {sum(not 0 < c <= PALETTE_BUFFER_COLOURS for c in counts)} of {len(counts)} "
                       f"palette rows count {', '.join(hex(c) for c in wild[:3])} (game buffer holds "
                       f"{PALETTE_BUFFER_COLOURS})")
    return (not bad), "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "")


def idle_drawable_gate(mod):
    """NODRAW1: every sprite bank a mod ships for a char row draws a body for its idle motions.

    The game selects the unit's idle motion by id and, when the bank has no such animation, falls back to the
    bank's FIRST animation (`anm_actor_select_motion` 0x1402f4ba0), which is the empty id 0: the tile then shows a
    shadow and a HP bar and nothing else (SURVEY1: "selected motion reads 0").  So 1001 and 1007 must exist and
    their first frame, with the shared-pose stubs shown (nested), must put at least one opaque pixel on screen.
    Banks the mod does not ship (a class on its template's art) are not this gate's business."""
    import numpy as np
    from d5lib import anm, gamefs
    mod = Path(mod)
    sprites = set()
    pf = mod / "patches" / "db" / "char.dat.json"
    if pf.is_file():
        try:
            doc = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:                                      # noqa: BLE001  (structure_gate reports bad JSON)
            return True, ""
        sprites = {int(r["sprite_id"]) for r in (doc.get("added") or []) if r.get("sprite_id")}
    bad = []
    for n in sorted(sprites | {s + 1 for s in sprites}):          # bank N (front) and N+1 (back view)
        path = mod / "files" / "Anime" / "ANM_HI_JP.dat" / f"anm{n:05d}.lzs"
        if not path.is_file():
            continue
        try:
            a = anm.parse(gamefs.decode_member(path.read_bytes()))
        except Exception as exc:                               # noqa: BLE001
            bad.append(f"anm{n:05d}: unreadable ({exc})")
            continue
        for motion in IDLE_MOTIONS:
            if not anm.has_animation(a, motion):
                bad.append(f"anm{n:05d}: no animation {motion} (the game would fall back to the empty first motion)")
                continue
            items = anm.evaluate(a, ("id", motion), 0, nested=True)
            drawn = 0
            if items:
                img, _ = anm.render_items(a, items, 0)
                drawn = int((np.asarray(img)[..., 3] > 16).sum())
            if not drawn:
                bad.append(f"anm{n:05d}: motion {motion} draws no pixel on its first frame")
    return (not bad), "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "")


def required_motion_gate(mod, doc=None):
    """SHARKBANK1: the main bank a mod ships for a char row holds every motion id the clean game's banks of that
    body kind all hold (`d5lib/requiredmotions.py`: monster 58 ids incl. the normal attack 2071/2077, humanoid 0 /
    6001 / 6007).  A bank that lacks one makes the game select the empty first animation, or leave the motion
    pointer NULL (null seek, ANMTRACE1).  Banks the mod does not ship (a class on its template's art) are not this
    gate's business.  This is NOT shown to explain the Shark Dragon crash: that pack passes it."""
    from d5lib import anm, gamefs, requiredmotions
    mod = Path(mod)
    pf = mod / "patches" / "db" / "char.dat.json"
    if not pf.is_file():
        return True, ""
    try:
        rows = json.loads(pf.read_text(encoding="utf-8")).get("added") or []
    except Exception:                                          # noqa: BLE001  (structure_gate reports bad JSON)
        return True, ""
    kinds = {}
    for r in rows:
        if r.get("sprite_id"):
            kinds.setdefault(int(r["sprite_id"]), int(r.get("body_type") or 0))
    bad = []
    for sprite, kind in sorted(kinds.items()):
        path = mod / "files" / "Anime" / "ANM_HI_JP.dat" / f"anm{sprite:05d}.lzs"
        if not path.is_file():
            continue
        try:
            a = anm.parse(gamefs.decode_member(path.read_bytes()))
        except Exception as exc:                               # noqa: BLE001
            bad.append(f"anm{sprite:05d}: unreadable ({exc})")
            continue
        miss = requiredmotions.missing((x.id for x in a.blocks[0].animations), kind, doc)
        if miss:
            bad.append(f"anm{sprite:05d} ({'monster' if kind == 1 else 'humanoid'}): no animation "
                       + ", ".join(str(m) for m in miss[:8]) + (f" (+{len(miss) - 8} more)" if len(miss) > 8 else ""))
    return (not bad), "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "")


def render_root_gate(mod):
    """BACKVIEW1: every animation of every bank the mod ships draws in the game what the kit's renderer draws.

    The game draws node root+1 and its children, never the root's own links (anm_actor_build_render_root 0x1402f5450;
    anm.render_root_problems).  PT1030ANIM's 1001/1007 stubs were [body][root -> child body]: in the game 1001 played
    1007's body (the back idle seen from the front) and 1007 read past the node table and drew nothing (Kojiro, Chief,
    Garatea from behind: shadow and HP bar only), while the kit drew both.  A bank fails when, at some key time, the
    game model (anm.evaluate(game=True)) puts other parts on screen than the kit (anm.render_root_mismatches)."""
    from d5lib import anm, gamefs
    bad = []
    for path in sorted((Path(mod) / "files").rglob("anm*.lzs")):
        try:
            a = anm.parse(gamefs.decode_member(path.read_bytes()))
        except Exception:                                      # noqa: BLE001  (other gates report unreadable banks)
            continue
        hits = anm.render_root_mismatches(a)
        if hits:
            ids = sorted({aid for _, aid, _ in hits})
            bad.append(f"{path.name}: {len(ids)} animation(s) {ids[:6]}{' ...' if len(ids) > 6 else ''} "
                       f"(e.g. {hits[0][1]}: {hits[0][2]})")
    return (not bad), "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "")


def face_template_gate(mod):
    """SMALLFIX1: every low-row character (id < 1000) the pack adds has a face template the installer can clone.

    The installer (outfits._finalize_characters) gives a new character its status-panel face animation by cloning a
    template's, and it learns the template from `patches/characters/unique.json` (`template_colour`), or from a char
    row whose colour id differs from its own id.  A low row with neither (colour id == id, no declaration) looks
    "already faced" to newchars.find(), gets no face animation, and its status-panel portrait stays blank (Shark King
    931, Xenolith 941).  Returns (ok, why)."""
    import json
    mod = Path(mod)
    cpath = mod / "patches" / "db" / "char.dat.json"
    if not cpath.is_file():
        return True, "no char.dat rows"
    rows = json.loads(cpath.read_text(encoding="utf-8")).get("added") or []
    upath = mod / "patches" / "characters" / "unique.json"
    declared = set()
    if upath.is_file():
        data = json.loads(upath.read_text(encoding="utf-8"))
        declared = {int(d["identity"]) for d in (data.get("uniques") or [data])
                    if isinstance(d, dict) and d.get("identity") is not None and d.get("template_colour") is not None}
    bad = [int(r["id"]) for r in rows if int(r["id"]) < 1000 and int(r["color_id"]) == int(r["id"])
           and int(r["id"]) not in declared and "sprite_id" in r and int(r["sprite_id"]) == int(r["id"])]
    return (not bad), (f"char row(s) {bad}: colour id == id and no unique.json template, so no face animation is "
                       f"cloned at install (blank status-panel portrait)" if bad else "")


def resident_placeholder_gate(mod, resident_ids=None):
    """D4BANK-ID: a registry monster unique's placeholder anm N+2 ends up in anm_resident.

    In battle the game binds a monster to anim N+2 while bank N loads and finds it only among loaded records:
    every vanilla monster keeps N+2 in anm_resident, a loose one misses and the body never draws.  The installer
    adds it (newclasses._monster_pictures) from the mod's own anm{N+2}.  `resident_ids`: the block ids of an
    installed anm_resident to check the installed result instead of what this kit's finalizer will add."""
    import json
    from d5lib import newclasses
    path = Path(mod) / "patches" / "characters" / "unique.json"
    declared = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        declared = {int(d["identity"]): d for d in (data.get("uniques") or [data])
                    if isinstance(d, dict) and d.get("identity") is not None}
    monsters = newclasses.registry_monster_sprites(declared)
    # NODRAW2: a plain char.dat monster row (body_type 1) with a body bank of its own needs the same placeholder
    anime = Path(mod) / "files" / "Anime" / "ANM_HI_JP.dat"
    shipped = {f"anime/anm_hi_jp.dat/{p.name}".lower() for p in anime.glob("*.lzs")} if anime.is_dir() else set()
    cpath = Path(mod) / "patches" / "db" / "char.dat.json"
    rows = json.loads(cpath.read_text(encoding="utf-8")).get("added") or [] if cpath.is_file() else []
    rows = [r for r in rows if "sprite_id" in r and "body_type" in r]
    monsters += [n for n in newclasses.row_monster_sprites(rows, shipped, k=0) if n not in monsters]
    if not monsters:
        return True, "no monster-kind character"
    if resident_ids is None:
        # replay the installer's block collection on this mod's own files (no game: a missing N+2 stays missing)
        from types import SimpleNamespace
        outputs = {f"anime/anm_hi_jp.dat/{p.name}".lower(): (None, p.read_bytes()) for p in
                   (anime / f"anm{n + 2:05d}.lzs" for n in monsters) if p.is_file()}
        ctx = SimpleNamespace(outputs=outputs, fs=None, _char_uniques=declared, _monster_rows=rows,
                              log=lambda *a, **k: None)
        resident_ids = set(newclasses.monster_picture_blocks(ctx, {}))
    bad = [f"monster sprite {n}: anm_resident lacks placeholder block {n + 2}" for n in monsters
           if n + 2 not in resident_ids]
    return (not bad), "; ".join(bad)


def gfx_of(cid, colour, palette):
    """The game's graphics id (unit+0x2E36) for class `cid`: anm_id_for_variant (decomp 0x14021F4A0), ported by
    D4FREEZE1 (survey.py) and checked against three live reads (asserted in tests/test_d4gfx1.py).  `palette` is the
    unit's palette, the row's `tier` when unit_construct makes it."""
    if cid == 0x99C:
        b1 = False
    elif (cid - 0x7DA) & 0xFFFFFFFF < 0x123 or (cid - 1000) & 0xFFFFFFFF < 0x137:
        b1 = True
    else:
        b1 = cid > 999
    i2 = int(cid / 100)
    b4 = b1
    if i2 in (0x33, 0x34, 0x30) or (cid - 5000) & 0xFFFFFFFF < 10:
        b4 = b1 if i2 == 0x30 else False
    k = (cid - 0x35C) & 0xFFFFFFFF
    if (k < 0x3D and 0x1004010040100401 >> (k & 0x3F) & 1) or cid in (0x3A2, 0x3AC) or b4:
        return palette + int(colour / 10) * 10
    return colour


def gfx_contract(mod, owners=None, covered=None):
    """D4-GFX1: every char row the mod adds keeps its own colour id as its graphics id.

    The game keys faces, cut-ins and the battle face on the graphics id; for a class id > 999 it rounds the colour
    down to a multiple of 10 (gfx_of), so a registry unique leasing colour 643 showed Mao (640).  A row passes when
    the game's value equals its colour, or when the Kit's graphics-id hook covers its class: `covered` = those class
    ids, by default what the installer's finalizer will put in the hook (outfits.registry_gfx over the mod's
    declared registry uniques).  owners: {colour id: name} to say whose graphics the row would get."""
    from d5lib import outfits
    mod = Path(mod)
    try:
        rows = json.loads((mod / "patches/db/char.dat.json").read_text()).get("added") or []
    except FileNotFoundError:
        return True, ""
    if covered is None:
        try:
            doc = json.loads((mod / "patches/characters/unique.json").read_text())
        except FileNotFoundError:
            doc = {}
        declared = {int(d["identity"]): int(d["physical"]) for d in
                    doc.get("uniques") or ([doc] if doc.get("identity") is not None else [])}
        by_id = {int(r["id"]): r for r in rows}
        chars = {c: None for c, phys in declared.items() if c in by_id and int(by_id[c]["color_id"]) == phys}
        covered = {c for c, _ in outfits.registry_gfx(chars, by_id)}
    bad = []
    for r in rows:
        cid, colour = int(r["id"]), int(r["color_id"])
        g = gfx_of(cid, colour, int(r.get("tier", 0)))
        if g != colour and cid not in covered:
            who = (owners or {}).get(g)
            bad.append(f"{cid}: colour {colour} -> graphics {g}" + (f" ({who})" if who else ""))
    return (not bad), "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "")


# --------------------------------------------------------------------------- LEASEGATE1: used-id gate
# Each importer checked ids only against its own lease file, so two importers handed out the same sprite
# banks and only a live install noticed (D1CDD2INSTALL1 run 1).  This gate checks every id-like resource a
# built mod folder claims against (a) the vanilla game, (b) every OTHER importer's recorded lease and
# (c) every other mod folder under the extra roots (default: installed mods).  Claim extraction reuses
# `modclaims.scan_mods` for db rows; ANM numbers come from the shipped files and the declared physical window.
LIVE_MODS = Path(offlinepaths.INSTALLED_MODS_DEFAULT)
# charPersonal/Sugoroku rows are read by position and packs share appended ids on purpose (132-134 in 24 packs);
# charhelp is positional too, but a second pack claiming the same help id is an error (modclaims), so it is claimed.
UNCLAIMED_MEMBERS = {"charPersonal.dat", "SugorokuMapSetting.dat"}
QUEST_SLOT = "Quest.dat:slot"                  # Quest.dat sort_order, a second id space of the same member


def art_window(n):
    """The ANM numbers a registry unique leased at `n` owns: bank, its two placeholders, portrait and cut-in."""
    n = int(n)
    return (n, n + 1, n + 2, 10000 + n, 10001 + n)


def _add(claims, kind, values):
    claims.setdefault(kind, set()).update(int(v) if not isinstance(v, str) else v for v in values)


def mod_claims(mod):
    """{kind: {ids}} a mod folder claims: added db rows by member (charPersonal/Sugoroku excluded), Quest slots, ANM numbers it ships or declares, face file stems."""
    from . import modclaims
    mod = Path(mod)
    claims = {}
    scan = modclaims.scan_mods(str(mod.parent), only=[mod.name])
    for member, ids in scan.added.items():
        if member not in UNCLAIMED_MEMBERS:
            _add(claims, member, ids)
    qf = mod / "patches/db/Quest.dat.json"
    if qf.is_file():
        rows = json.loads(qf.read_text(encoding="utf-8-sig")).get("added") or []
        _add(claims, QUEST_SLOT, [r["sort_order"] for r in rows if "sort_order" in r])
    anime = mod / "files/Anime/ANM_HI_JP.dat"
    if anime.is_dir():
        _add(claims, "anm", [int(m.group(1)) for f in anime.glob("anm*.lzs")
                             if (m := re.fullmatch(r"anm(\d+)\.lzs", f.name))])
    uf = mod / "patches/characters/unique.json"
    if uf.is_file():
        doc = json.loads(uf.read_text(encoding="utf-8"))
        for d in doc.get("uniques") or [doc]:
            if isinstance(d, dict) and d.get("physical") is not None and not d.get("shares_art_with"):
                # D4-NPC1: a shared-art unique writes no bank/face/portrait; the owner pack's window is its own claim.
                _add(claims, "anm", art_window(d["physical"]))
    for sub in ("characters", "classes", "outfits"):
        _add(claims, "face", [f"{sub}/{f.stem}" for f in (mod / "patches" / sub).glob("face_*.png")])
    vf = mod / "patches/voices/voices.json"                # VOICE1: custom voice sets are ids two packs must not share
    if vf.is_file():
        _add(claims, "voice", [int(k) for k in json.loads(vf.read_text(encoding="utf-8")).get("voices") or {}])
    return claims


def lease_claims(manifest=None, *, d1c_leases=True):
    """[(source, owner folder, {kind: {ids}})] from every importer's recorded leases (read-only).

    d4-leases.json, dd2-leases.json (parked entries claim nothing), the D1C unique + roster-gap leases
    (`d1c.unique_leases`), unique_art_leases.json and the DRPG v2 manifest (owner `drpg:<id>`).

    ``d1c_leases=False`` skips the D1C lease read (it lives under Research until SOURCEPREP6 migrates
    it); SOURCEPREP4-DD2 uses that for the default DD2 build, whose proof blocks the research roots."""
    from .importers import d1c, drpg_leases
    out = []
    imp = ROOT / "d5lib/importers"
    for name, e in json.loads((imp / "dd2-leases.json").read_text())["entries"].items():
        if e.get("parked"):
            continue
        c = {}
        _add(c, "char.dat", [*e.get("rank_ids", []), e["target"]])
        _add(c, "charhelp.dat", [e["help"]] if e.get("help") else [])
        _add(c, "Quest.dat", e.get("quests", []))
        _add(c, QUEST_SLOT, [e["quest_slot"]] if e.get("quest_slot") else [])
        _add(c, "JobRank.dat", e.get("jobranks", []))
        _add(c, "anm", art_window(e["physical"]))
        out.append(("dd2", name, c))
    for e in json.loads((imp / "d4-leases.json").read_text())["characters"].values():
        st = e.get("storage") or {}
        c = {}
        _add(c, "char.dat", [e["identity"]])
        if not e.get("share_art_with"):
            # D4-NPC1: a shared-art NPC leases no art window; the owner entry claims it.
            _add(c, "anm", art_window(e["physical"]))
        _add(c, "charhelp.dat", [st["help_id"]] if st else [])
        _add(c, "Quest.dat", [st["quest_id"]] if st else [])
        _add(c, QUEST_SLOT, [st["quest_slot"]] if st else [])
        _add(c, "voice", [e["voice_id"]] if e.get("voice_id") else [])
        _add(c, "Skill.dat", list((e.get("evility_rows") or {}).values()))     # SOURCEPREP4-D4: leased evility rows
        out.append(("d4", e["mod"], c))
    for listing, e in (d1c.unique_leases().items() if d1c_leases else ()):
        c = {}
        _add(c, "char.dat", [e["identity"]])
        _add(c, "anm", art_window(e["physical"]))
        _add(c, "charhelp.dat", [e["help_id"]] if e.get("help_id") else [])
        _add(c, "Quest.dat", [e["quest_id"]] if e.get("quest_id") else [])
        _add(c, QUEST_SLOT, [e["quest_slot"]] if e.get("quest_slot") else [])
        out.append(("d1c", f"D1C_Unique_{listing}", c))
    # D4GAP1: the reviewed evility rows of every in-scope D4 class/unique (d4-evility-overlay.json, recorded since
    # 2026-11-03) are claimed for the other importers; D4 packs share some rows on purpose, so D4 folders skip this source
    overlay = json.loads((imp / "d4-evility-overlay.json").read_text())["mods"]
    scope = json.loads((imp / "d4-scope.json").read_text())
    d4_mods = {c["mod"]: c for c in json.loads((imp / "d4-leases.json").read_text())["characters"].values()}
    for mod, st in overlay.items():
        if mod.startswith("D4_Class_"):
            if not (scope.get(mod.rsplit("_", 1)[1]) or {}).get("in_scope"):
                continue
        elif mod not in d4_mods:
            continue
        c = {}
        _add(c, "Skill.dat", [int(r["id"]) for r in st.get("skill_rows", [])])
        out.append(("d4-overlay", mod, c))
    for name, e in json.loads((ROOT / "d5lib/data/unique_art_leases.json").read_text())["leases"].items():
        c = {}
        _add(c, "char.dat", [e["identity"]])
        _add(c, "anm", art_window(e["physical"]))
        out.append(("unique_art", name, c))
    manifest = manifest or drpg_leases.load()
    for b in [*(manifest.get("bases") or []), *(manifest.get("costumes") or [])]:
        cl, c = b.get("claims") or {}, {}
        _add(c, "char.dat", [b["class_id"], *([cl["row"]] if cl.get("row") is not None else [])])
        for k, v in cl.items():
            if k != "row" and isinstance(v, list):
                _add(c, "anm", v)
        _add(c, "Skill.dat", list((b.get("evilities") or {}).values()))   # D4GAP1: pinned sample evility rows
        out.append(("drpg", b["lease"], c))
    # OLCONV2: the converted Overlord characters (Stella / Rutile / Majin) record every id they hold here
    olf = Path(__file__).parent / "importers/overlord-leases.json"
    if olf.is_file():
        for folder, e in json.loads(olf.read_text(encoding="utf-8"))["entries"].items():
            c = {}
            _add(c, "char.dat", [e["identity"]])
            _add(c, "anm", art_window(e["physical"]))
            _add(c, "Skill.dat", e["evilities"])
            _add(c, "magic.dat", e["specials"])
            _add(c, "charhelp.dat", [e["help_id"]])
            _add(c, "WishDataBase.dat", [e["bill"]])
            _add(c, "voice", [e["voice"]])
            out.append(("overlord-conv", folder, c))
    from . import d1cvoice, dd2voice, drpgvoice
    for look, vid in drpgvoice.leases().items():          # VOICE1: recorded Disgaea RPG voice sets (7000-7499)
        out.append(("drpg", f"drpg:{look}", {"voice": {vid}}))
    for folder, vid in d1cvoice.leases().items():         # Disgaea 1 voice sets (7500-7599), owner = the pack folder
        out.append(("d1c-voice", folder, {"voice": {vid}}))
    for key, vid in dd2voice.leases().items():            # Disgaea D2 voice sets (7600-7699), owner = the voice key
        out.append(("dd2-voice", f"dd2-voice:{key}", {"voice": {vid}}))
    return out


class UsedIds:
    """The three claim sources, loaded once per run.  `check(mod)` -> (ok, text)."""

    def __init__(self, game_path, state_root, roots=(), *, d1c_leases=True):
        self.game_path, self.state_root = Path(game_path), Path(state_root)
        self.roots = [Path(r) for r in roots]
        self.d1c_leases = d1c_leases
        self._vanilla = None
        self._index = None

    def vanilla(self):
        """({member: {id: (name, fillable)}}, vanilla ANM numbers); tables loaded on demand."""
        if self._vanilla is None:
            from . import database, gamefs, sprites
            from .importers.dd2 import original_fs
            fs = original_fs(dict(game_path=self.game_path, state_root=self.state_root))
            self._fs, self._tables = fs, {}
            self._vanilla = (self._tables, set(sprites.used_sprite_numbers(fs)))
        return self._vanilla

    def vanilla_ids(self, kind):
        from . import database, modclaims
        tables, _ = self.vanilla()
        if kind not in tables:
            member = "Quest.dat" if kind == QUEST_SLOT else kind
            try:
                t = database.load_table(member, self._fs.read(DB_ARCHIVE + "/" + member))
            except KeyError:
                tables[kind] = {}
                return tables[kind]
            if kind == QUEST_SLOT:
                tables[kind] = {int(r["sort_order"]): ("slot", False) for r in t.rows}
            else:
                names = modclaims.vanilla_ids(t)
                fill = modclaims.fillable_ids(names)
                tables[kind] = {i: (n, i in fill) for i, n in names.items()}
        return tables[kind]

    def index(self):
        """{(kind, id): [(label, owner folder)]} over leases and every extra root."""
        if self._index is None:
            idx = {}
            for source, owner, c in lease_claims(d1c_leases=self.d1c_leases):
                for kind, ids in c.items():
                    for i in ids:
                        idx.setdefault((kind, i), []).append((f"lease {source}:{owner}", owner))
            # EVILFX3: a folder present in several roots is ONE mod; the copy in the last root that has it stands
            # for it (roots are installed first, staged builds after), because installing the staged copy replaces
            # the installed one.  Without this a row could never move from one staged pack to another: the
            # installed copy of the old owner would still claim it.
            latest = {}
            for root in self.roots:
                if not root.is_dir():
                    continue
                for f in sorted(root.iterdir()):
                    if (f / "mod.json").is_file():
                        latest[f.name] = (root, f)
            for root, f in latest.values():
                for kind, ids in mod_claims(f).items():
                    for i in ids:
                        idx.setdefault((kind, i), []).append((f"mod {root.parent.name}/{root.name}/{f.name}", f.name))
            self._index = idx
        return self._index

    def reference_problems(self, mod):
        """EVILGAP1b: a character's evility link to a D4 exact row (8188..8999) it does not own is a
        *reference*, not a claim: it holds only when a pack named in mod.json `requires` owns that row
        (Skill.dat added rows in an extra root, or the recorded D4 overlay for a pack not installed yet)."""
        mod = Path(mod)
        chf = mod / "patches/db/char.dat.json"
        if not chf.is_file():
            return []
        def rows(folder):
            f = Path(folder) / "patches/db/Skill.dat.json"
            return {int(r["id"]) for r in json.loads(f.read_text(encoding="utf-8-sig")).get("added") or []} if f.is_file() else set()
        own = rows(mod)
        refs = {int(r[k]) for r in json.loads(chf.read_text(encoding="utf-8-sig")).get("added") or []
                for k in ("evility1", "evility2", "evility3", "evility4") if 8188 <= int(r.get(k) or 0) <= 8999} - own
        if not refs:
            return []
        requires = json.loads((mod / "mod.json").read_text(encoding="utf-8-sig")).get("requires") or []
        overlay = json.loads((Path(__file__).parent / "importers/d4-evility-overlay.json").read_text())["mods"]
        out = []
        for ref in sorted(refs):
            ok = False
            for req in requires:
                held = {int(r["id"]) for r in overlay.get(req, {}).get("skill_rows", [])}
                ok = ok or ref in held or any(ref in rows(root / req) for root in self.roots)
            if not ok:
                out.append(ref)
        return out

    def check(self, mod):
        mod = Path(mod)
        found = {}                                        # holder label -> {kind: [ids]}
        bad = self.reference_problems(mod)
        if bad:
            found["reference"] = {"evility": bad}
        idx = self.index()
        _, vanilla_anm = self.vanilla()
        for kind, ids in sorted(mod_claims(mod).items()):
            for i in sorted(ids, key=str):
                if kind == "anm" and i in vanilla_anm:
                    found.setdefault("vanilla", {}).setdefault(kind, []).append(i)
                elif kind == "voice":
                    if not 6000 <= i <= 9999:                # the game's own voice ids end at 5321
                        found.setdefault("vanilla", {}).setdefault(kind, []).append(i)
                elif kind not in ("anm", "face"):
                    hit = self.vanilla_ids(kind).get(i)
                    if hit and not hit[1]:
                        found.setdefault("vanilla", {}).setdefault(kind, []).append(i)
                for label, owner in idx.get((kind, i), ()):
                    # a DRPG_* folder is checked by drpg_leases, whose owners are `drpg:<id>`, not folder names
                    if owner != mod.name and not (mod.name.startswith("DRPG_") and label.startswith("lease drpg:")) \
                            and not (mod.name.startswith("DD2_") and label.startswith("lease dd2-voice:")) \
                            and not (mod.name.startswith("D4_") and label.startswith("lease d4-overlay:")):
                        found.setdefault(label, {}).setdefault(kind, []).append(i)
        text = "; ".join(f"{label}: " + ", ".join(f"{k} {','.join(map(str, sorted(set(v), key=str)[:6]))}{'+' if len(set(v)) > 6 else ''}"
                                                  for k, v in sorted(kinds.items()))
                         for label, kinds in sorted(found.items())[:5])
        return (not found), text


def default_extra_roots(extra=()):
    """The installed mods folder (`D5_INSTALLED_MODS` or the live kit), the live kit too when the variable
    points elsewhere (a holding folder lacks the D4 packs), then any `extra` roots."""
    roots = [offlinepaths.installed_mods_root(), LIVE_MODS, *map(Path, extra)]
    return list(dict.fromkeys(roots))


# Games whose default build reads no installed pack (SOURCEPREP4-DD2, -D1C, -D4, -DRPG): an installed comparison
# is an explicit ``installed_reference`` opt-in; the references are recorded ids/counts/rules in the kit.
SOURCE_ONLY_GAMES = ("dd2", "d1c", "d4", "drpg")


def installed_pack(game, options, root, folder):
    """The installed pack a post-build pass may read, or None.

    SOURCEPREP4-DD2/D4: a source-only game's default build ('installed_reference' off) returns None,
    so icon pinning, the wheel freeze and baseline comparisons cannot read an installed pack; other
    games keep theirs.
    """
    options = options or {}
    if not options.get('installed_reference', game not in SOURCE_ONLY_GAMES):
        return None
    return Path(root) / folder if root else None


def reference_roots(game, options, extra=()):
    """The id-claim roots a build may scan.

    SOURCEPREP4-DD2/D4: a source-only game's build with ``installed_reference`` off scans only
    explicitly supplied roots; it never reaches the live kit or the default installed folder.  Every
    other game keeps the old set.
    """
    options = options or {}
    if not options.get('installed_reference', game not in SOURCE_ONLY_GAMES):
        return [Path(p) for p in extra]
    return default_extra_roots(extra)


# --------------------------------------------------------------------------- compare
def tree_diff(built, installed):
    """-> (added, missing, changed) relative POSIX paths."""
    built, installed = Path(built), Path(installed)
    a = {p.relative_to(built).as_posix(): p for p in built.rglob("*") if p.is_file()}
    b = {p.relative_to(installed).as_posix(): p for p in installed.rglob("*") if p.is_file()}
    added = sorted(set(a) - set(b))
    missing = sorted(set(b) - set(a))
    changed = [k for k in sorted(set(a) & set(b)) if a[k].read_bytes() != b[k].read_bytes()]
    return added, missing, changed


def evility_row_diff(built, installed):
    """Name the evility rows that differ between a built mod and the installed copy, by Skill.dat id:
    `Skill.dat rows installed-only [..] / rebuild-only [..]; char evility links ...`.  Empty when equal."""
    def state(root):
        root = Path(root)

        def load(rel):
            try:
                return json.loads((root / rel).read_text())
            except (OSError, ValueError):
                return {}
        rows = {int(r["id"]) for r in load("patches/db/Skill.dat.json").get("added", [])}
        beh = {int(k) for k in load("patches/evilities/evilities.json").get("evilities", {})}
        links = {(r["id"], k): r[k] for r in load("patches/db/char.dat.json").get("added", [])
                 for k in r if "evil" in k and r[k]}
        return rows | beh, links
    (ib, il), (bb, bl) = state(installed), state(built)
    parts = []
    if ib != bb:
        parts.append(f"evility rows installed-only {sorted(ib - bb)} / rebuild-only {sorted(bb - ib)}")
    if il != bl:
        parts.append("char evility links differ on rows " + str(sorted({k[0] for k in set(il.items()) ^ set(bl.items())})[:6]))
    return "; ".join(parts)


def classify(diff, entry, reason_fn=None, missing_ok=None, dirs=None):
    """Built-vs-installed verdict using the importer's per-entry expectations.

    `missing_ok(entry, path)` lets a plugin declare a missing installed file *explained* by a
    recorded allocation change (a re-leased id moves the files instead of dropping them); anything
    it does not explain stays a regression.
    """
    added, missing, changed = diff
    if not (added or missing or changed):
        return "identical", ""
    if reason_fn and dirs and "dirs" in inspect.signature(reason_fn).parameters:
        reason = reason_fn(entry, diff, dirs=dirs)
    else:
        reason = reason_fn(entry, diff) if reason_fn else ""
    if reason.startswith("regression: "):         # a plugin names a content loss no file listing shows (D4-FIX5)
        return "regression", reason[len("regression: "):]
    if missing:
        stray = [m for m in missing if not (missing_ok and missing_ok(entry, m))]
        if stray or not reason:
            return "regression", "rebuild lacks: " + ", ".join((stray or missing)[:6])
    if changed:
        if reason:
            return "expected", reason
        return "expected", f"{len(changed)} file(s) differ under the current trees: " + ", ".join(changed[:4])
    return "expected", reason or "rebuild adds files the installed copy predates: " + ", ".join(added[:4])


def source_voice_pass(game, mod, source_root, options=None):
    """VOICE1 post-pass for one built pack: convert the character's own source-game voice into patches/voices/ and
    link its char rows (d5lib/drpgvoice, dd2voice, d1cvoice), then run the voice gate.
    -> (feature label 'own' | 'own (some looks)' | 'donor' , gate ok, note).  A character the source game gives no
    voice keeps its donor and says why; D4 has its own voice pass in the importer."""
    from . import d1cvoice, dd2voice, drpgvoice
    options = options or {}
    if game == "drpg":
        from .importers import _drpg_source
        receipt = drpgvoice.apply(mod, _drpg_source.data(source_root))
    elif game == "dd2":
        receipt = dd2voice.apply(mod, source_root)
    elif game == "d1c":                               # clip audio comes from the Disgaea PC edition (docs/SOURCE_VOICES.md)
        if not options.get("d1_voice_source"):
            return "donor", True, "no Disgaea PC folder named for the voice clips (option d1_voice_source)"
        receipt = d1cvoice.apply(mod, options["d1_voice_source"])
    else:
        return "n/a", True, f"no source voice pass for {game}"
    ok, problems, _stats = drpgvoice.voice_gate(mod)
    kept = "; ".join(str(k.get("reason", "")) for k in receipt["donor_kept"])
    label = "donor" if not receipt["voices"] else ("own" if not receipt["donor_kept"] else "own (some looks)")
    return label, ok, "; ".join(problems[:4]) or kept


# --------------------------------------------------------------------------- run
def run(game, *, out_dir, only=None, compare=False, jobs=1, source_root=None,
        game_path=None, state_root=None, keep_builds=False, options=None, log=print):
    started = time.time()
    imp = load_importer(game)
    if hasattr(imp, "configure"):                 # SOURCEPREP4-DRPG: the install the roster's text references resolve against
        imp.configure(game_path=Path(game_path), state_root=Path(state_root))
    roster = [as_entry(e) for e in imp.roster(source_root)]
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        roster = [e for e in roster if e.id in wanted or e.mod_folder in wanted]
        found = {e.id for e in roster} | {e.mod_folder for e in roster}
        absent = sorted(wanted - found)
        if absent:
            log(f"warning: --only named ids not in the roster: {', '.join(absent)}")
    options = dict(options or {})
    for key in ("d1c_hold_blank", "d4_hold_blank", "dd2_hold_blank", "dd2_source_fields", "dd2_cutin_fit",
                "d4_stub_xform", "d4_death_game_view", "d4_source_tracks", "d4_face_rule",
                "d4_mesh_nodes"):
        options.setdefault(key, True)      # the importer defaults hold; record what the build did
    # SOURCEPREP4-DD2/-D1C/-D4: a source-only game's default build reads no installed pack at all.  Other
    # importers keep their installed references; an installed comparison is an explicit opt-in for every game.
    options.setdefault("installed_reference", game not in SOURCE_ONLY_GAMES)
    ctx = dict(output_root=Path(out_dir) / game, source_root=Path(source_root) if source_root else None,
               game_path=Path(game_path), state_root=Path(state_root), keep_builds=keep_builds,
               installed_root=offlinepaths.installed_mods_root(),
               installed_reference=bool(options["installed_reference"]),
               compare=compare, options=options)
    root = ctx["output_root"]
    build_root = root / "build"
    mods_root = root / "mods"
    mods_root.mkdir(parents=True, exist_ok=True)
    table_cache = {}

    def one(entry):
        t0 = time.time()
        r = Result(id=entry.id, mod_folder=entry.mod_folder)
        work = build_root / safe_name(entry.id)
        try:
            if not entry.in_scope:
                r.error = "out of scope: " + entry.why_not
                return r
            r = imp.build(entry, work, ctx)
            if isinstance(r, dict):
                # A plugin may return the interface's dict shape (d1c does, with its own art
                # record); normalize it into a Result without dropping what it reports.
                d = dict(r)
                r = Result(id=d.pop("id", entry.id), mod_folder=d.pop("mod_folder", entry.mod_folder),
                           built=bool(d.pop("built", False)), error=d.pop("error", "") or "",
                           gates=d.pop("gates", {}) or {}, features=d.pop("features", {}) or {},
                           notes=list(d.pop("notes", []) or []), extra=d)  # type: ignore[assignment]
            r.id, r.mod_folder = entry.id, entry.mod_folder
            if r.error:
                return r
            built = Path(r.extra.get("mod_path") or (work / "native-mods" / entry.mod_folder))
            if not built.is_dir():
                built = work / entry.mod_folder
            if not built.is_dir():
                found = sorted(work.glob(f"**/native-mods/{entry.mod_folder}"))
                built = found[0] if found else built
            if not built.is_dir():
                raise FileNotFoundError(f"builder produced no {entry.mod_folder}")
            ok, why = structure_gate(built)
            r.gates["structure"] = ok
            if not ok:
                r.notes.append(why)
            dest = mods_root / entry.mod_folder
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(built, dest)
            r.built = ok
            if game == "d1c" and options.get("d1c_faces", "hd") == "installed":
                pinned = pin_installed_faces(dest, ctx["installed_root"] / entry.mod_folder)
                if pinned:
                    r.notes.append(f"faces: {len(pinned)} installed face picture(s) kept (REPROFIX1; "
                                   f"--d1c-faces hd|opaque|cutout writes the importer's own)")
            record_importer_options(dest, game, {"d1c_faces": "hd", **options})
            installed = installed_pack(game, options, ctx["installed_root"], entry.mod_folder)
            # SOURCEPREP4-DD2: no installed icon pair and no installed bank are read by the default
            # DD2 build; with installed_reference off the recorded shape table is the freeze reference.
            if not options.get("no_icon_pin") and (installed is not None or game not in SOURCE_ONLY_GAMES):
                moved = pin_installed_icons(dest, installed)
            elif not options.get("no_icon_pin") and installed is None and hasattr(imp, "icon_pins"):
                moved = pin_recorded_icons(dest, imp.icon_pins(entry.mod_folder))      # SOURCEPREP4-DRPG: the recorded pairs
            else:
                moved = None
            if moved:
                r.notes.append(f"list-icon rows pinned to the installed pair for class id(s) {sorted(moved)} "
                               f"(REPROFIX1; --no-icon-pin keeps the isolated allocation)")
            reference = imp.wheel_reference(entry.mod_folder) if hasattr(imp, "wheel_reference") else None
            ok, why = wheel_gate(dest, installed, reference=reference)
            r.gates["wheel"] = ok
            if not ok:
                r.notes.append("wheel-freeze: " + why)
            elif why and why.startswith("declared shape change"):
                r.notes.append("wheel: " + why)
            ok, why = cell_page_gate(dest)
            r.gates["cell_pages"] = ok
            if not ok:
                r.notes.append("cell-pages: " + why)
            ok, why = resident_placeholder_gate(dest)
            r.gates["resident_placeholder"] = ok
            if not ok:
                r.notes.append("resident-placeholder: " + why)
            ok, why = face_template_gate(dest)
            r.gates["face_template"] = ok
            if not ok:
                r.notes.append("face-template: " + why)
            ok, why = idle_drawable_gate(dest)
            r.gates["idle_drawable"] = ok
            if not ok:
                r.notes.append("idle-drawable: " + why)
            ok, why = palette_count_gate(dest)
            r.gates["palette_count"] = ok
            if not ok:
                r.notes.append("palette-count: " + why)
            ok, why = required_motion_gate(dest)
            r.gates["required_motions"] = ok
            if not ok:
                r.notes.append("required-motions: " + why)
            ok, why = render_root_gate(dest)
            r.gates["render_root"] = ok
            if not ok:
                r.notes.append("render-root: " + why)
            ok, why = text_gate(dest)
            r.gates["text"] = ok
            if not ok:
                r.notes.append("text: " + why)
            ok, why, record = stat_label_gate(dest, game, r.features.get("stats"), ctx, table_cache)
            r.gates["stat_label"] = ok
            r.extra["stat_oracle"] = record
            if not ok:
                r.notes.append("stat-label: " + why)
            r.features.setdefault("recruit", "own")
            if options.get("source_voices"):          # VOICE1: the character's own source-game voice, after the
                label, ok, why = source_voice_pass(game, dest, ctx["source_root"], options)   # importer's own gates
                r.features["voice"], r.gates["voice"] = label, ok
                if label.startswith("own"):           # the builder's donor note no longer describes the pack
                    r.notes = [n for n in r.notes if "template donor" not in n]
                    r.notes.append("Voice: the character's own source-game recordings (patches/voices, receipt beside it).")
                if why:
                    r.notes.append("voice: " + why)
            if compare:
                if installed.is_dir():
                    diff = tree_diff(dest, installed)
                    hook = getattr(imp, "compare", None)
                    if hook:
                        r.compare, r.compare_reason = hook(entry, diff)
                    else:
                        r.compare, r.compare_reason = classify(diff, entry,
                                                               getattr(imp, "compare_reason", None),
                                                               getattr(imp, "explained_missing", None),
                                                               dirs=(dest, installed))
                else:
                    r.compare = "new"
        except Exception as exc:                               # noqa: BLE001
            r.built = False
            r.error = f"{type(exc).__name__}: {exc}"
            r.notes.append(traceback.format_exc(limit=3))
        r.seconds = round(time.time() - t0, 1)
        return r

    excluded = [dict(id=e.id, mod_folder=e.mod_folder, why=e.why_not) for e in roster if not e.in_scope]
    roster = [e for e in roster if e.in_scope]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
        for r in pool.map(one, roster):
            log(f"[{len(results) + 1}/{len(roster)}] {r.id} built={r.built} "
                f"compare={r.compare or '-'} {r.error or ''}".strip())
            results.append(r)

    # Pack-level steps first (manifest/catalogue guards), then shared gates.
    try:
        post = getattr(imp, "post", None)
        if post:
            post(mods_root, results)
    except Exception as exc:                                   # noqa: BLE001
        log(f"post() failed: {type(exc).__name__}: {exc}")
    ok, why = dbpatch_gate(mods_root, game_path, state_root, table_cache) if results else (True, "")
    for r in results:
        if r.built:
            r.gates["dbpatches"] = ok
            if not ok:
                r.notes.append("dbpatch: " + why)
    owners = {}
    for row in getattr(table_cache.get("char.dat"), "rows", ()):
        owners.setdefault(row["color_id"], row["name_EN"])
    for r in results:
        if r.built:
            ok, why = gfx_contract(mods_root / r.mod_folder, owners)
            r.gates["gfx"] = ok
            if not ok:
                r.notes.append("gfx: " + why)
    if options.get("source_specials") and game in ("d4", "d1c", "dd2"):    # SPECIALS2: the source's own specials
        from d5lib.importers import specials2                             # (serial: one lease file)
        for r in results:
            if r.built:
                try:
                    roots = [ctx["installed_root"], mods_root] if ctx["installed_reference"] else [mods_root]
                    label, ok, why = specials2.run(game, mods_root / r.mod_folder, roots)
                except Exception as exc:                                   # noqa: BLE001
                    label, ok, why = "failed", False, f"{type(exc).__name__}: {exc}"
                r.features["specials"], r.gates["specials2"] = label, ok
                if why:
                    r.notes.append("specials2: " + why)
    if results and not (options or {}).get("no_used_ids"):
        # SOURCEPREP4-DD2: with installed_reference off, only explicitly supplied roots are scanned;
        # the live kit and the default installed folder are not read at all.
        extra = reference_roots(game, options, (options or {}).get("extra_roots") or ())
        used = UsedIds(game_path, state_root, [*extra, mods_root],
                       d1c_leases=ctx["installed_reference"] or game not in SOURCE_ONLY_GAMES)
        for r in results:
            if r.built:
                try:
                    ok, why = used.check(mods_root / r.mod_folder)
                except Exception as exc:                       # noqa: BLE001  (no backup state, unreadable lease file)
                    ok, why = False, f"{type(exc).__name__}: {exc}"
                r.gates["used_ids"] = ok
                if not ok:
                    r.notes.append("used-ids: " + why)
    ids = magic_ids(mods_root, game_path, state_root) if results else set()
    survey = None
    for r in results:
        if r.built:
            for name, (ok, why) in schema_gates(mods_root / r.mod_folder, ids).items():
                r.gates[name] = ok
                if not ok:
                    r.notes.append(f"{name}: {why}")
            if survey is None:
                from d5lib import skillmotions
                survey = skillmotions.Survey(skill_roots=[mods_root / x.mod_folder for x in results if x.built])
            try:
                ok, why = skill_motion_gate(mods_root / r.mod_folder, survey)
            except Exception as exc:                           # noqa: BLE001 (no clean game copy)
                ok, why = False, f"{type(exc).__name__}: {exc}"
            r.gates["skill_motions"] = ok
            if not ok:
                r.notes.append("skill_motions: " + why)
    summary = dict(game=game, started=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - started, 1),
                   total=len(results), built=sum(r.built for r in results), out=str(root),
                   compare=compare, jobs=jobs, excluded=excluded, options=options,
                   results=[dataclasses.asdict(r) for r in results])
    summary["gates_passed"] = sum(1 for r in results if r.gate_ok())
    summary["regressions"] = [r.id for r in results if r.compare == "regression"]
    summary["exit"] = 0 if (summary["built"] == len(results) and not summary["regressions"]
                            and all(v for r in results for v in r.gates.values())) else 1
    (root / "results.json").write_text(json.dumps(summary, indent=1) + "\n")
    (root / "REPORT.md").write_text(report(summary))
    return summary


def report(summary):
    rows = summary["results"]
    lines = [f"# {summary['game']} import run — {summary['started']}", "",
             f"- entries: {summary['total']}, built: {summary['built']}, gates passed: {summary['gates_passed']}",
             f"- regressions: {len(summary['regressions'])}, runtime: {summary['seconds']}s, jobs: {summary['jobs']}",
             f"- out of scope (not built, not counted): {len(summary.get('excluded') or [])}"
             + ("".join(f"\n  * {x['id']}: {x['why']}" for x in summary.get('excluded') or [])),
             f"- output: `{summary['out']}`", "",
             "| id | kind | built | gates | compare | reason / error |",
             "|---|---|---:|---|---|---|"]
    kinds = {f"{x['id']}": x for x in rows}
    for r in rows:
        gates = " ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in r["gates"].items())
        why = (r["error"] or r["compare_reason"]).replace("|", "/")[:160]
        lines.append(f"| {r['id']} | {r['mod_folder']} | {'yes' if r['built'] else 'no'} | {gates} | "
                     f"{r['compare'] or '-'} | {why} |")
    return "\n".join(lines) + "\n"
