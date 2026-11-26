#!/usr/bin/env python3
"""Prepare the kit's Source folder from the user's own game copies (SOURCEPREP2).

    python tools/prep_source.py [--dest DIR] [--d4 DIR] [--d1c DIR] [--d1pc DIR] [--dd2 DIR] [--drpg DIR]
                                [--drpg-masters DIR] [--drpg-catalogs FILE] [--link] [--dry-run] [--json]

The destination is `<Disgaea 5 Complete>/D5ModKit/Source/` unless --dest says otherwise: one canonical folder that
`d5lib/sourcefolder.py` resolves too, whether the kit lives inside the game folder or elsewhere.  One subfolder per
game keeps the source game's own layout, and `manifest.json` records size, SHA-256 and whether each file equals a
known-good build (`d5lib/data/source_known.json`).  A scoped run keeps the manifest entries of games it did not touch.

What it never does: decrypt, use keys, run UnityPy, or write inside `Disgaea Source/`.  Disgaea 1 Complete and
Disgaea D2 must already be dumped/decrypted by the user's own tools; Disgaea RPG must already be unpacked (the
sprites/, looks.json, atlas-index.json and decoded masters JSON), because Sean chose no UnityPy in the prep tool
(2026-11-18, ASK-778EF7).  Disgaea 5 itself is not copied: the kit reads the installed base game through its own
`state/games/*/backups`.

D1 Complete faces: the Switch `SUBDATA.DAT` holds the HD faces (anmdat.fad, D1CHDFACE1) and is the preferred
source.  When a folder holds both dumps the Switch build is chosen; a PS4-only input is reported as incomplete for
D1C (exit 1) because the current HD-face reader decodes the Switch layout only.  A PS4 warning is printed only for a
file that really hashes to the PS4 build, never for a merely unrecognized one.

Exit codes: 0 every required file verified; 1 a required file differs, is unknown or is missing; 2 refused or
bad usage.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from d5lib import paths, sourcefolder  # noqa: E402
from d5lib.offlinepaths import contains  # noqa: E402

TOOL = "prep_source/1"
STEAM_APPS = {
    "d4": (1233880, "Disgaea 4 Complete+"),
    "d1pc": (405900, "Disgaea PC"),
    "d5": (803600, "Disgaea 5 Complete"),
}
DRPG_FILES_PREFIX = "sdcard/Android/data/com.disgaearpg.forwardworks/files"
DRPG_VOICE_PREFIX = "assetbundle/sounds/voice/battle/"
DRPG_MASTERS = ("character", "charactercommand", "command", "leaderskill")
# Optional: read into the text pool the reviewed class titles resolve against (TEXTHASH-DRPG); omitted = titles refuse by name.
DRPG_TEXT_MASTERS = ("characterclassname",)

# Steam discovery lives in d5lib.paths (cross-platform); this alias keeps it stubbable in tests.
steam_app = paths.steam_app

D4_FILES = (
    "Data/DATA/ANM_HI.dat",
    "Data/DATA/WF.dat",
    "Data/DATA/EN/DATABASE_EN.dat",
    "Data/DATA/JP/DATABASE.dat",
    "Data/SOUND/EN/voice.dat",
    "Data/SOUND/JP/voice.dat",
    "Data/SOUND/SoundData_Voice_EN.dat",
    "Data/SOUND/SoundData_Voice_JP.dat",
)
DD2_FILES = (["START.dat"] + [f"START_{i}.dat" for i in range(1, 7)] +
             ["ANM_HI.dat"] + [f"ANM_HI_{i}.dat" for i in range(1, 7)] +
             ["SOUND/SndPakVoiceEN/SndPakVoiceEN_0.pak",
              "SOUND/SndPakVoiceJP/SndPakVoiceJP_0.pak"])


# ------------------------------------------------------------------------------------------------ locating
def find_root(base, marker, depth=3):
    """A directory under ``base`` (or ``base`` itself) that holds ``marker``, breadth first, or None."""
    base = Path(base)
    if (base / marker).exists():
        return base
    if not base.is_dir():
        return None
    frontier = [(base, 0)]
    while frontier:
        directory, level = frontier.pop(0)
        if level >= depth:
            continue
        try:
            children = sorted((c for c in directory.iterdir() if c.is_dir()), key=lambda p: p.name)
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            if (child / marker).exists():
                return child
            frontier.append((child, level + 1))
    return None


def find_roots(base, marker, depth=3):
    """Every directory under ``base`` that holds ``marker``, breadth first (deduplicated by resolved path)."""
    base = Path(base)
    if not base.is_dir():
        return [base] if (base / marker).exists() else []
    out, seen, frontier = [], set(), [(base, 0)]
    while frontier:
        directory, level = frontier.pop(0)
        try:
            key = directory.resolve()
        except OSError:
            key = directory
        if key in seen:
            continue
        seen.add(key)
        if (directory / marker).exists():
            out.append(directory)
        if level >= depth:
            continue
        try:
            children = sorted((c for c in directory.iterdir() if c.is_dir()), key=lambda p: p.name)
        except OSError:
            continue
        for child in children:
            if not child.name.startswith("."):
                frontier.append((child, level + 1))
    return out


def d4_root(given):
    base = Path(given) if given else steam_app(*STEAM_APPS["d4"])
    if not base:
        return None
    return find_root(base, "Data/DATA/ANM_HI.dat", depth=2)


def d1pc_root(given):
    base = Path(given) if given else steam_app(*STEAM_APPS["d1pc"])
    if not base:
        return None
    root = find_root(base, "DATA.DAT", depth=3)
    return root if root and (root / "SUBDATA.DAT").is_file() else None


def dd2_root(given):
    if not given:
        return None
    base = Path(given)
    for candidate in (base, base / "PS3_GAME/USRDIR/Data", base / "USRDIR/Data", base / "Data"):
        if (candidate / "START_4.dat").is_file():
            return candidate
    return find_root(base, "START_4.dat", depth=5)


def drpg_parts(given):
    """(index root, sprites root, voice root) for an unpacked DRPG folder."""
    if not given:
        return None, None, None
    base = Path(given)
    index = None
    for candidate in (base, base / "sprites"):
        if (candidate / "looks.json").is_file():
            index = candidate
            break
    if index is None:
        index = find_root(base, "looks.json", depth=3)
    sprites = None
    if index is not None:
        if (index / "sprites").is_dir():
            sprites = index / "sprites"
        elif (index / "Sprites").is_dir():
            sprites = index
    if sprites is None:
        sprites = find_root(base, "Sprites/Standard", depth=3)
    voice = None
    for candidate in (base, base / DRPG_FILES_PREFIX, base / "files"):
        if (candidate / DRPG_VOICE_PREFIX).is_dir():
            voice = candidate
            break
    if voice is None:
        voice = find_root(base, DRPG_VOICE_PREFIX.rstrip("/"), depth=5)
    return index, sprites, voice


# ------------------------------------------------------------------------------------------------ verification
def classify_file(game, rel, path, known):
    """(size, sha256, state, build) for one file, skipping the hash when the size cannot match any row."""
    path = Path(path)
    size = path.stat().st_size
    rows = (known.get("games", {}).get(game, {}) or {}).get("files", {}).get(rel) or []
    if rows and not any(int(row.get("size", -1)) == size for row in rows):
        return size, None, "unknown", None
    sha = sourcefolder.sha256_file(path)
    state, build, _note = sourcefolder.verify_file(game, rel, size, sha, known=known)
    return size, sha, state, build


def d1c_candidates(given, known):
    """Every ``data/SUBDATA.DAT`` under the supplied folder with its build classification."""
    out = []
    if not given:
        return out
    for root in find_roots(Path(given), "data/SUBDATA.DAT", depth=4):
        path = root / "data/SUBDATA.DAT"
        try:
            size, sha, state, build = classify_file("d1c", "data/SUBDATA.DAT", path, known)
        except OSError:
            continue
        out.append({"root": root, "path": path, "size": size, "sha256": sha, "state": state, "build": build})
    return out


def d1c_choice(candidates):
    """Prefer the recognized Switch build, then any other recognized build, then an unrecognized dump."""
    def rank(rec):
        if rec["state"] == "yes" and "switch" in str(rec["build"]).lower():
            return 0
        if rec["state"] == "yes":
            return 1
        return 2
    return sorted(candidates, key=rank)[0] if candidates else None


D1C_PS4_PROBLEM = ("PS4 SUBDATA.DAT is incomplete for D1C: the current HD-face reader decodes the Switch "
                   "anmdat.fad layout only (D1CHDFACE1). Supply the Switch romfs.")
D1C_UNRECOGNIZED_WARNING = ("SUBDATA.DAT is not a recognized D1 Complete build; HD-face readiness cannot be "
                            "confirmed (expected the Switch 01004B100AF18000 build)")


def build_kind(build):
    """``switch``, ``ps4`` or ``recognized`` for a build label; None when the label is absent."""
    text = str(build or "").lower()
    if "switch" in text:
        return "switch"
    if "ps4" in text:
        return "ps4"
    return "recognized" if text else None


def d1c_hd_state(rec):
    """HD-face readiness of the ``data/SUBDATA.DAT`` actually in the destination (review R2 finding 2).

    Derived from the retained file, never from the input that was offered: a PS4-only retry must not relabel a
    prepared Switch dump, and a failed Switch copy over a PS4 file must not claim Switch readiness.
    """
    if not rec or not rec.get("sha256"):
        return "missing"
    if rec.get("verified") != "yes":
        return "unrecognized"
    return build_kind(rec.get("known_build")) or "recognized"


# ------------------------------------------------------------------------------------------------ plan
class Job:
    """One file to check/place.  ``src`` is None when the input was deliberately not supplied (review R3): the row
    is still planned so the manifest describes the omission, and ``note`` carries the input diagnostic."""

    __slots__ = ("game", "rel", "src", "optional", "note")

    def __init__(self, game, rel, src, optional=False, note=None):
        self.game, self.rel, self.optional, self.note = game, rel, optional, note
        self.src = Path(src) if src is not None else None


def drpg_extras_jobs(args, absent):
    """The four required master rows and the optional catalog row, planned whether or not the index was found.

    The masters and the catalog do not depend on ``looks.json``, so a supplied ``--drpg`` folder whose index is
    missing (or a run that supplies no DRPG input at all) still plans these rows: a prepared copy is rechecked and
    kept, and nothing on disk yields ``missing`` (review R3/R4).  The flag diagnostics stay in ``absent`` so the run
    still reports the unsupplied input and exits 1.
    """
    jobs = []
    masters = Path(args.drpg_masters) if args.drpg_masters else None
    if masters:
        jobs += [Job("drpg", f"masters/{name}.json", masters / f"{name}.json") for name in DRPG_MASTERS]
        jobs += [Job("drpg", f"masters/{name}.json", masters / f"{name}.json", optional=True) for name in DRPG_TEXT_MASTERS
                 if (masters / f"{name}.json").is_file()]
    else:
        absent["drpg-masters"] = ("decoded masters not supplied (--drpg-masters); prep never runs UnityPy "
                                  "(Sean, 2026-11-18)")
        jobs += [Job("drpg", f"masters/{name}.json", None, note=absent["drpg-masters"])
                 for name in DRPG_MASTERS]
    if args.drpg_catalogs and Path(args.drpg_catalogs).is_file():
        jobs.append(Job("drpg", "d5-catalogs.json", args.drpg_catalogs, optional=True))
    else:
        absent["drpg-catalogs"] = "D5 catalogs not supplied (--drpg-catalogs); reviewed DRPG family mapping needs it"
        # The optional catalog row is planned too: a retry without the flag keeps and rechecks a prepared copy
        # (review R3), and a first run records the omission as `missing` rather than dropping the row.
        jobs.append(Job("drpg", "d5-catalogs.json", None, optional=True, note=absent["drpg-catalogs"]))
    return jobs


def drpg_inventory_jobs(found, sprites, voice, known, fallback=None):
    """Expected sprite and battle-voice paths from the known table that the supplied folder does not have.

    A folder with empty sprite or voice directories must not pass just because the indices and masters verify
    (review finding 3): every inventory path is planned, so an omission is reported ``missing`` and exits 1.  When
    a whole sprite or battle-voice directory is absent the rows still appear (as ``missing``) instead of vanishing
    from the manifest, so a consumer that only rechecks manifest rows sees the omission (review R2, DRPG gap).
    """
    planned = {job.rel for job in found if job.game == "drpg"}
    inventory = (known.get("games", {}).get("drpg", {}) or {}).get("files", {}) or {}
    extra = []
    for rel, rows in inventory.items():
        if rel in planned:
            continue
        if rows and all(row.get("optional") for row in rows):
            continue        # SOURCEPREP4-DRPG: the vanilla monster twins' sheets are planned only when supplied
        if rel.startswith("sprites/"):
            src = Path(sprites) / rel[len("sprites/"):] if sprites is not None else None
        elif rel.startswith(DRPG_VOICE_PREFIX):
            src = Path(voice) / rel if voice is not None else None
        else:
            continue
        if src is None:
            if fallback is None:
                continue
            src = Path(fallback) / rel
        extra.append(Job("drpg", rel, src))
    return extra


def build_plan(args, known):
    """Jobs per game, a per-game reason when a whole game was not supplied, and D1C HD readiness notes."""
    jobs, absent, notes = [], {}, {}

    root = d4_root(args.d4)
    if root:
        jobs += [Job("d4", rel, root / rel) for rel in D4_FILES]
    else:
        absent["d4"] = ("Disgaea 4 Complete+ not found" + ("" if args.d4 else " (Steam app 1233880)") +
                        "; " + sourcefolder.HOW_TO_GET["d4"])

    candidates = d1c_candidates(args.d1c, known)
    chosen = d1c_choice(candidates)
    if chosen:
        kind = ("unrecognized" if chosen["state"] != "yes"
                else (build_kind(chosen["build"]) or "recognized"))
        note = ("Switch romfs: anmdat.fad holds the HD faces (D1CHDFACE1)" if kind == "switch"
                else "PS4 dump: the current HD-face reader decodes the Switch layout only (D1CHDFACE1)")
        jobs.append(Job("d1c", "data/SUBDATA.DAT", chosen["path"], note=note))
        notes["d1c"] = {"chosen": str(chosen["path"]), "checked": len(candidates), "input_kind": kind}
        if kind == "switch" and len(candidates) > 1:
            rejected = [str(c["path"]) for c in candidates if c is not chosen]
            notes["d1c"]["warning"] = ("Switch SUBDATA.DAT chosen for the HD faces; ignored " +
                                       ", ".join(rejected))
    else:
        absent["d1c"] = "D1 Complete dump not supplied (--d1c); " + sourcefolder.HOW_TO_GET["d1c"]

    root = d1pc_root(args.d1pc)
    if root:
        jobs += [Job("d1pc", f"Disgaea PC/{name}", root / name, optional=True)
                 for name in ("DATA.DAT", "SUBDATA.DAT")]
    else:
        absent["d1pc"] = "Disgaea 1 PC voices not found (optional); " + sourcefolder.HOW_TO_GET["d1pc"]

    root = dd2_root(args.dd2)
    if root:
        jobs += [Job("dd2", f"PS3_GAME/USRDIR/Data/{rel}", root / rel) for rel in DD2_FILES]
    else:
        absent["dd2"] = "Disgaea D2 dump not supplied (--dd2); " + sourcefolder.HOW_TO_GET["dd2"]

    index, sprites, voice = drpg_parts(args.drpg)
    if index:
        for name in ("looks.json", "atlas-index.json"):
            jobs.append(Job("drpg", name, index / name))
        if sprites:
            for png in sorted(sprites.rglob("*.png")):
                jobs.append(Job("drpg", "sprites/" + png.relative_to(sprites).as_posix(), png))
        else:
            absent["drpg-sprites"] = ("DRPG sprite PNGs not found under the supplied folder; unpack them with "
                                      "your own tools (prep never runs UnityPy)")
        if voice:
            battle = voice / DRPG_VOICE_PREFIX.rstrip("/")
            for p in sorted(battle.rglob("*")):
                if p.is_file():
                    jobs.append(Job("drpg", DRPG_VOICE_PREFIX + p.relative_to(battle).as_posix(), p))
        else:
            absent["drpg-voices"] = "DRPG battle voices not found under the supplied folder"
        jobs += drpg_inventory_jobs(jobs, sprites, voice, known, fallback=Path(args.drpg))
        jobs += drpg_extras_jobs(args, absent)
    else:
        if args.drpg:
            absent["drpg"] = ("unpacked DRPG folder supplied but its index (looks.json) was not found; "
                              "unpack it with your own tools (prep never runs UnityPy)")
        else:
            absent["drpg"] = "unpacked DRPG folder not supplied (--drpg); " + sourcefolder.HOW_TO_GET["drpg"]
        # Review R4: the required master and catalog rows do not depend on the index.  Plan them on every path that
        # selects DRPG, so a first run (or a retry against a prior manifest that lacks them) can never leave the
        # manifest looking complete while a master is missing.  run() rechecks and keeps a prepared copy.
        jobs += drpg_extras_jobs(args, absent)

    return jobs, absent, notes


# ------------------------------------------------------------------------------------------------ placing
class UnsafeDestination(RuntimeError):
    """A resolved destination parent leaves the destination (for example a nested symlink into an input)."""


def _resolved_target(path):
    """Resolve ``path`` through its existing ancestors, keeping the still-missing tail lexical."""
    path = Path(path)
    missing = []
    probe = path
    while not probe.exists():
        if probe == probe.parent:
            break
        missing.append(probe.name)
        probe = probe.parent
    resolved = probe.resolve()
    for part in reversed(missing):
        resolved = resolved / part
    return resolved


def _validate_parent(dst, dest_root, inputs):
    """Refuse a write whose resolved parent is outside ``dest_root`` or inside one of the inputs."""
    parent = _resolved_target(Path(dst).parent)
    root = _resolved_target(dest_root)
    if parent != root and not parent.is_relative_to(root):
        raise UnsafeDestination(f"destination parent escapes the source folder: {Path(dst).parent} -> {parent}")
    for label, item in inputs:
        if item and Path(item).is_dir() and contains(item, parent):
            raise UnsafeDestination(f"refusing to write into the {label} input through {Path(dst).parent}")


def destination_record(path, game, rel, known):
    """The record of the file actually in the destination, following a link target, or None."""
    path = Path(path)
    try:
        if path.is_symlink():
            target = Path(os.readlink(path))
            if not target.is_absolute():
                target = path.parent / target
            if not target.is_file():
                return None
            stat = target.stat()
        elif path.is_file():
            stat = path.stat()
        else:
            return None
        sha = sourcefolder.sha256_file(path)
        state, build, note = sourcefolder.verify_file(game, rel, stat.st_size, sha, known=known)
        rec = {"path": rel, "size": stat.st_size, "sha256": sha, "known_build": build, "verified": state}
        if note:
            rec["note"] = note
        return rec
    except OSError:
        return None


def place(job, dest, link, size, sha, state, known, inputs, build=None):
    """Put one verified input into the source folder.

    Returns ``kept``, ``copied``, ``linked`` or ``preserved``.  A verified destination file is never replaced by a
    mismatched input (``preserved``), and a prepared Switch SUBDATA.DAT is never replaced by a PS4 build that the
    HD-face reader cannot decode; a replacement is staged in the destination directory and published with
    ``os.replace`` only after the staged bytes match the input (review findings 4 and R2-1/R2-2).  In ``--link``
    mode the replacement symlink is staged at a unique path and renamed over the target, so a failed link never
    deletes the verified output first (review R2 finding 1).
    """
    dst = dest / job.game / job.rel
    existing = destination_record(dst, job.game, job.rel, known)
    if existing and existing["size"] == size and existing["sha256"] == sha:
        return "kept"
    if existing and existing["verified"] == "yes":
        if state != "yes":
            return "preserved"
        if (job.game == "d1c" and build_kind(existing.get("known_build")) == "switch"
                and build_kind(build) == "ps4"):
            return "preserved"
    _validate_parent(dst, dest, inputs)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if link:
        stage = Path(tempfile.mkdtemp(prefix="." + dst.name + ".", suffix=".link", dir=str(dst.parent)))
        staged = stage / dst.name
        try:
            os.symlink(job.src.resolve(), staged)
            os.replace(staged, dst)
        finally:
            for cleanup in (staged.unlink, stage.rmdir):
                try:
                    cleanup()
                except OSError:
                    pass
        return "linked"
    fd, tmp_name = tempfile.mkstemp(prefix="." + dst.name + ".", suffix=".part", dir=str(dst.parent))
    os.close(fd)
    try:
        shutil.copy2(job.src, tmp_name)
        staged = Path(tmp_name)
        if staged.stat().st_size != size or sourcefolder.sha256_file(staged) != sha:
            raise OSError(f"staged copy of {job.src} does not match the input")
        os.replace(tmp_name, dst)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return "copied"


# ------------------------------------------------------------------------------------------------ run
def refuse_dest(dest, inputs):
    """Reject a destination inside an input copy or any 'Disgaea Source' tree."""
    resolved = Path(dest).resolve()
    if "Disgaea Source" in resolved.parts:
        raise SystemExit(f"refusing to write inside Disgaea Source/: {resolved}")
    for label, root in inputs:
        if root and Path(root).is_dir() and contains(root, resolved):
            raise SystemExit(f"refusing to write inside the {label} input: {resolved} is under {Path(root).resolve()}")


def refuse_foreign_manifest(dest):
    """Refuse a ``manifest.json`` prep cannot read as a D5 source manifest, before anything is copied (review R5).

    ``_prior_games()`` treats an unreadable manifest as "no prior run", which is right for the row policy but would
    let a failing run replace another tool's file.  Refuse instead, in dry runs too, so the user learns about it
    before any game file lands and the foreign file is always left byte-identical.
    """
    path = Path(dest) / sourcefolder.MANIFEST_FILE
    if not (path.exists() or path.is_symlink()):
        return
    try:
        sourcefolder.read_manifest(dest)
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"refusing: {path} exists but is not a D5 source manifest ({exc}); "
            f"choose a fresh destination for the prepared folder or move that file away "
            f"(nothing was copied or written)")


def _prior_games(dest):
    """Manifest entries from an earlier run, so a scoped run does not discard untouched games."""
    try:
        prior = sourcefolder.read_manifest(dest)
    except (OSError, ValueError):
        return {}
    if not (Path(dest) / "manifest.json").is_file():
        return {}
    return {g: e for g, e in (prior.get("games") or {}).items() if (Path(dest) / g).is_dir()}


def retained_game_rows(dest, game, known):
    """Recheck the files already in ``dest/<game>`` when that game's input is unavailable.

    A scoped retry whose input cannot be found (Steam gone, flag omitted) must not erase the manifest rows of
    prepared bytes that are still on disk (review R2 finding 3).  Every row describes the destination: its size and
    SHA-256 when a file is really there, ``missing`` when it is not.
    """
    folder = Path(dest) / game
    try:
        prior_entry = (sourcefolder.read_manifest(dest).get("games") or {}).get(game) or {}
        rels = [rec["path"] for rec in prior_entry.get("files", []) if rec.get("path")]
    except (OSError, ValueError):
        rels = []
    if not rels and folder.is_dir():
        rels = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                      if p.is_file() or p.is_symlink())
    rows = []
    for rel in rels:
        rec = destination_record(folder / rel, game, rel, known)
        if rec:
            rec["note"] = (f"source input not available; rechecked the prepared copy already present "
                           f"(verified: {rec['verified']})")
            rows.append(rec)
        else:
            rows.append({"path": rel, "size": None, "sha256": None, "known_build": None,
                         "verified": "missing",
                         "note": "source input not available and no prepared copy is present"})
    return rows


def run(args):
    if not args.dest:
        canonical = sourcefolder.game_source_dir()
        if not canonical:
            raise SystemExit("Disgaea 5 Complete was not found; pass --dest <the D5ModKit/Source folder>.")
        args.dest = str(canonical)
    dest = Path(args.dest).expanduser()
    inputs = [("d4", args.d4 or steam_app(*STEAM_APPS["d4"])), ("d1c", args.d1c),
              ("d1pc", args.d1pc or steam_app(*STEAM_APPS["d1pc"])), ("dd2", args.dd2),
              ("drpg", args.drpg), ("drpg-masters", args.drpg_masters)]
    refuse_dest(dest, inputs)
    refuse_foreign_manifest(dest)

    selected = sourcefolder.GAMES
    if args.only:
        selected = tuple(g.strip() for g in args.only.split(",") if g.strip())
        bad = [g for g in selected if g not in sourcefolder.GAMES]
        if bad:
            raise SystemExit(f"unknown game(s) for --only: {', '.join(bad)} (choose from {', '.join(sourcefolder.GAMES)})")
    known = sourcefolder.load_known(args.known) if args.known else sourcefolder.load_known()
    jobs, absent, notes = build_plan(args, known)

    games = {}
    summary = {}
    problems = []
    warnings = []
    for game in selected:
        game_jobs = [j for j in jobs if j.game == game]
        # "Supplied" describes the game's own input (the folder/index), not whether placeholder rows were planned:
        # DRPG master rows exist even when --drpg was not recognized (review R4).
        supplied = game not in absent
        entry = {"edition": known.get("games", {}).get(game, {}).get("edition"),
                 "origin": "user-supplied", "root": game, "supplied": supplied, "files": []}
        counts = {"yes": 0, "no": 0, "unknown": 0, "missing": 0}
        if game in absent:
            entry["error"] = absent[game]
            if game != "d1pc":
                problems.append((game, "*", "missing", absent[game]))
            else:
                warnings.append(absent[game])
            # The input is unavailable, but prepared bytes may still be present: recheck and keep their rows
            # instead of replacing the entry with an empty file list (review R2 finding 3).  Paths already covered by
            # a planned job are left to the job loop, which rechecks the destination itself (review R4), so a
            # required master row can never be duplicated or dropped by an older manifest that lacks it.
            planned = {job.rel for job in game_jobs}
            retained = [rec for rec in retained_game_rows(dest, game, known) if rec["path"] not in planned]
            entry["files"] = retained
            for rec in retained:
                counts[rec["verified"]] += 1
                if rec["verified"] != "yes":
                    message = f"{game}/{rec['path']}: {rec['verified']} ({rec.get('note') or 'no note'})"
                    if game == "d1pc":
                        warnings.append(message)
                    else:
                        problems.append((game, rec["path"], rec["verified"], rec.get("note") or ""))
        for job in game_jobs:
            dst = dest / job.game / job.rel
            failed = False
            if job.src is None or not job.src.is_file():
                if job.src is None:
                    reason = job.note or "source input not supplied"
                else:
                    reason = f"source file not found: {job.src}"
                kept = None if args.dry_run else destination_record(dst, game, job.rel, known)
                if kept:
                    rec = dict(kept)
                    if kept["verified"] == "yes":
                        rec["note"] = f"{reason}; kept the prepared copy already present"
                        warnings.append(f"{game}/{job.rel}: source input missing; kept the verified prepared file")
                    else:
                        rec["note"] = f"{reason}; the folder holds a {kept['verified']} copy"
                else:
                    rec = {"path": job.rel, "size": None, "sha256": None, "known_build": None,
                           "verified": "missing", "note": reason}
            else:
                size = job.src.stat().st_size
                sha = sourcefolder.sha256_file(job.src)
                state, build, note = sourcefolder.verify_file(game, job.rel, size, sha, known=known)
                rec = {"path": job.rel, "size": size, "sha256": sha, "known_build": build, "verified": state}
                if note:
                    rec["note"] = note
                if not args.dry_run:
                    try:
                        outcome = place(job, dest, args.link, size, sha, state, known, inputs, build=build)
                    except UnsafeDestination as exc:
                        raise SystemExit(f"refusing: {exc}")
                    except OSError as exc:
                        failed = True
                        kept = destination_record(dst, game, job.rel, known)
                        if kept:
                            rec = dict(kept)
                            rec["note"] = f"update failed ({exc}); the previous file was kept"
                        else:
                            # The failed update left nothing: the manifest must describe the destination (no
                            # file), never the input's hash (review R2 finding 3).
                            rec = {"path": job.rel, "size": None, "sha256": None, "known_build": None,
                                   "verified": "missing",
                                   "note": f"update failed ({exc}); no prepared copy is present"}
                    else:
                        kept = destination_record(dst, game, job.rel, known)
                        if kept:
                            rec = dict(kept)
                            if outcome == "preserved":
                                if (game == "d1c" and build_kind(kept.get("known_build")) == "switch"
                                        and build_kind(build) == "ps4"):
                                    rec["note"] = ("kept the verified Switch dump; the supplied PS4 build is "
                                                   "incomplete for D1C (D1CHDFACE1)")
                                else:
                                    rec["note"] = "kept the verified prepared file; the supplied input differs"
                                    warnings.append(f"{game}/{job.rel}: supplied input does not verify "
                                                    f"({state}); kept the verified file already present")
            counts[rec["verified"]] += 1
            if rec["verified"] != "yes" and not failed:
                if job.optional:
                    warnings.append(f"{game}/{job.rel}: {rec['verified']} ({rec.get('note') or 'no note'})")
                elif job.src is None and rec["verified"] == "missing":
                    # The input was deliberately not supplied: the directory-level diagnostic below already
                    # reports it, and the row still records `missing` in the manifest (review R3).
                    pass
                else:
                    problems.append((game, job.rel, rec["verified"], rec.get("note") or ""))
            if failed:
                problems.append((game, job.rel, "error", rec.get("note") or "update failed"))
            entry["files"].append(rec)
        info = notes.get(game) or {}
        if game == "d1c":
            # HD readiness describes the SUBDATA.DAT that is actually in the destination, not the input offered
            # (review R2 finding 2).
            rec = next((r for r in entry["files"] if r["path"] == "data/SUBDATA.DAT"), None)
            hd = d1c_hd_state(rec)
            entry["hd_faces"] = "ps4-incomplete" if hd == "ps4" else hd
            if info.get("chosen"):
                entry["hd_source"] = info["chosen"]
                entry["hd_candidates_checked"] = info.get("checked", 0)
            if hd == "ps4":
                problems.append(("d1c", "data/SUBDATA.DAT", "incomplete", D1C_PS4_PROBLEM))
            elif hd == "unrecognized":
                warnings.append(D1C_UNRECOGNIZED_WARNING)
            elif hd == "switch" and info.get("warning"):
                warnings.append(info["warning"])
            if hd == "switch" and info.get("input_kind") == "ps4":
                warnings.append("kept the prepared Switch SUBDATA.DAT for the HD faces; the supplied PS4 build "
                                "is incomplete for D1C (D1CHDFACE1)")
        elif info.get("hd_faces"):
            entry["hd_faces"] = info["hd_faces"]
        if info.get("warning") and game != "d1c":
            warnings.append(info["warning"])
        games[game] = entry
        summary[game] = {"edition": entry["edition"], "files": len(entry["files"]), **counts,
                         "supplied": supplied}

    if "drpg" in selected:
        if absent.get("drpg-masters"):
            problems.append(("drpg", "masters/*.json", "missing", absent["drpg-masters"]))
        if absent.get("drpg-catalogs"):
            warnings.append(absent["drpg-catalogs"])
        if absent.get("drpg-sprites"):
            problems.append(("drpg", "sprites/", "missing", absent["drpg-sprites"]))
        if absent.get("drpg-voices"):
            problems.append(("drpg", DRPG_VOICE_PREFIX.rstrip("/"), "missing", absent["drpg-voices"]))

    if not args.dry_run:
        for game, entry in _prior_games(dest).items():
            if game not in games:
                games[game] = entry
        try:
            sourcefolder.write_manifest(dest, games, tool=TOOL,
                                        extra={"known_table": sourcefolder.KNOWN_SCHEMA,
                                               "source_dir": str(dest)})
        except sourcefolder.ForeignManifest as exc:
            # A foreign manifest that appeared after the preflight: keep it, like the preflight would have.
            raise SystemExit(f"refusing: {exc}; the manifest was not replaced")

    if args.json:
        print(json.dumps({"dest": str(dest), "dry_run": args.dry_run, "link": args.link,
                          "games": summary, "problems": [list(p) for p in problems],
                          "warnings": warnings}, indent=1, sort_keys=True))
    else:
        print(f"Source folder: {dest}{'  (dry run)' if args.dry_run else ''}")
        for game in selected:
            s = summary[game]
            if not s["supplied"]:
                print(f"  {game:5s} not supplied - {absent.get(game, '')}")
                continue
            print(f"  {game:5s} {s['files']:5d} files: {s['yes']} verified, {s['no']} differ, "
                  f"{s['unknown']} unknown, {s['missing']} missing  ({s['edition'] or game})")
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"  - {w}")
        if problems:
            print("Problems:")
            for game, rel, state, note in problems[:40]:
                print(f"  - {game}/{rel}: {state}{' - ' + note if note else ''}")
            if len(problems) > 40:
                print(f"  ... and {len(problems) - 40} more (see manifest.json)")
        print("D5 base game is read in place through the kit's state/games backups; nothing was copied.")
        if not args.dry_run:
            print(f"Manifest: {dest / 'manifest.json'}")
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", help="destination folder (default <D5>/D5ModKit/Source)")
    ap.add_argument("--d4", help="Disgaea 4 Complete+ folder (default: found through Steam, app 1233880)")
    ap.add_argument("--d1c", help="folder holding data/SUBDATA.DAT (Switch romfs or PS4 unpack)")
    ap.add_argument("--d1pc", help="Disgaea PC folder (default: found through Steam, app 405900; optional)")
    ap.add_argument("--dd2", help="decrypted PS3 dump folder holding PS3_GAME/USRDIR/Data")
    ap.add_argument("--drpg", help="unpacked Disgaea RPG folder (sprites/, looks.json, atlas-index.json, voices)")
    ap.add_argument("--drpg-masters", help="folder with the decoded character/charactercommand/command/leaderskill JSON (and, optional, characterclassname for the class titles)")
    ap.add_argument("--drpg-catalogs", help="d5-catalogs.json used by the reviewed DRPG family mapping")
    ap.add_argument("--link", action="store_true", help="symlink instead of copy (same disk, saves space)")
    ap.add_argument("--dry-run", action="store_true", help="report only; copy nothing and write no manifest")
    ap.add_argument("--json", action="store_true", help="print a machine-readable summary")
    ap.add_argument("--only", help="prepare only these games, comma separated (default: all)")
    ap.add_argument("--known", help="known-good table to use (default d5lib/data/source_known.json)")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
