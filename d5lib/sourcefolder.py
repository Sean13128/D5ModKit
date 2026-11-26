"""Where the user's prepared source files are (SOURCEPREP2).

Every importer that reads another Disgaea game's files should ask this module instead of naming a path.  One fixed
folder holds them, next to the Disgaea 5 install inside the kit folder the kit already uses for its own assets:

    <Disgaea 5 Complete>/D5ModKit/Source/
        manifest.json
        d4/     Data/DATA/ANM_HI.dat, Data/DATA/WF.dat, ...        (D4 install layout, needed files only)
        d1c/    data/SUBDATA.DAT                                    (Switch romfs or PS4 unpack; HD faces)
        d1pc/   Disgaea PC/DATA.DAT, SUBDATA.DAT                    (Disgaea 1 Steam; voices only, optional)
        dd2/    PS3_GAME/USRDIR/Data/START_4.dat, ...               (decrypted PS3 dump)
        drpg/   sprites/, looks.json, atlas-index.json, masters/, assetbundle/sounds/voice/battle/...

`tools/prep_source.py` fills it from the user's own game copies and writes `manifest.json`.  Game data never ships.

Resolution order (first one that is set wins):

1. environment ``D5_SOURCE_DIR`` (tests, or a hand-picked folder)
2. ``settings.json`` key ``source_dir`` (the kit's settings file)
3. the canonical ``<Disgaea 5 Complete>/D5ModKit/Source`` (Sean, 2026-11-18), found through
   ``d5lib.paths.game_dir()`` (settings, the kit's own location, Steam on Windows/macOS/Linux)
4. ``<kit>/Source`` only when no Disgaea 5 folder is found at all

``tools/prep_source.py`` writes to rule 3 for every user, whether the kit lives inside the game folder or elsewhere, so
prep and the resolver agree.  An explicit ``--dest`` is prep-only: point ``D5_SOURCE_DIR`` or ``settings.json``
``source_dir`` at the same folder so importers read it.

    from d5lib import sourcefolder
    path = sourcefolder.source_path("d4", "Data/DATA/ANM_HI.dat")
    if sourcefolder.have("d1pc", "Disgaea PC/DATA.DAT"): ...

``SourceMissing`` names the game, the file and the prep step that provides it.  The known-good table
(``d5lib/data/source_known.json``) carries SHA-256 hashes only, never game data.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import paths

MANIFEST_SCHEMA = "d5-source-manifest/1"
MANIFEST_FILE = "manifest.json"
KNOWN_SCHEMA = "d5-source-known/1"
KNOWN_FILE = Path(__file__).resolve().parent / "data" / "source_known.json"
SETTING = "source_dir"
ENV = "D5_SOURCE_DIR"

GAMES = ("d4", "d1c", "d1pc", "dd2", "drpg")
GAME_NAMES = {
    "d4": "Disgaea 4 Complete+",
    "d1c": "Disgaea 1 Complete",
    "d1pc": "Disgaea 1 PC (voices for D1 Complete)",
    "dd2": "Disgaea D2",
    "drpg": "Disgaea RPG (JP)",
}

# What the user does when a file is missing.  Kept short; tools/prep_source.py prints the long form.
HOW_TO_GET = {
    "d4": "run `python tools/prep_source.py` with Disgaea 4 Complete+ installed (Steam app 1233880), "
          "or pass --d4 <the game folder>",
    "d1c": "run `python tools/prep_source.py --d1c <folder holding data/SUBDATA.DAT>` with your own "
           "Switch romfs (HD faces) or PS4 unpack",
    "d1pc": "optional: install Disgaea 1 PC (Steam app 405900) and run `python tools/prep_source.py`, "
            "or pass --d1pc <the Disgaea PC folder>",
    "dd2": "run `python tools/prep_source.py --dd2 <decrypted PS3 dump folder holding PS3_GAME/USRDIR/Data>`",
    "drpg": "run `python tools/prep_source.py --drpg <your unpacked DRPG folder>`; prep does not run UnityPy, "
            "so the sprites/ PNGs, looks.json, atlas-index.json and the decoded masters JSON must already be "
            "unpacked",
}


class ForeignManifest(ValueError):
    """An existing ``manifest.json`` that is not a D5 source manifest; it is never replaced (review R5)."""


class SourceMissing(FileNotFoundError):
    """A prepared source file is not there; the message says how to supply it."""

    def __init__(self, game, rel, folder=None):
        self.game, self.rel, self.folder = game, rel, folder
        name = GAME_NAMES.get(game, game)
        where = f" in {folder}" if folder else ""
        super().__init__(
            f"Prepared source file missing: {game}/{rel}{where} ({name}). "
            f"To supply it, {HOW_TO_GET.get(game, 'run tools/prep_source.py')}.")


def game_source_dir():
    """``<Disgaea 5 Complete>/D5ModKit/Source``: the one canonical folder, or None when no game folder is found.

    This is the shared default: prep writes here and the resolver looks here, so the kit may live inside the game
    folder or anywhere else and both still agree (review finding 1).
    """
    game = paths.game_dir()
    return (Path(game) / "D5ModKit" / "Source") if game else None


def default_source_dir():
    """The folder used when neither ``D5_SOURCE_DIR`` nor ``settings.json source_dir`` overrides it."""
    return game_source_dir() or Path(paths.KIT_DIR) / "Source"


def source_dir():
    """The source folder in use: env D5_SOURCE_DIR, else settings.json source_dir, else the canonical default."""
    env = os.environ.get(ENV)
    if env and env.strip():
        return Path(env.strip()).expanduser()
    saved = paths.kit_setting(SETTING)
    if saved and str(saved).strip():
        return Path(str(saved).strip()).expanduser()
    return default_source_dir()


def source_path(game, rel, *, required=True):
    """Path of one prepared source file, or None when absent and ``required=False``.

    ``rel`` is the path inside the game's folder, exactly as prep_source.py lays it out
    (for example ``"data/SUBDATA.DAT"`` for d1c).
    """
    folder = source_dir()
    path = folder / game / rel
    if path.is_file():
        return path
    if required:
        raise SourceMissing(game, rel, folder)
    return None


def have(game, rel):
    """True when an optional prepared file is present."""
    return source_path(game, rel, required=False) is not None


# -------------------------------------------------------------------------------------------- known-good table
def load_known(path=None):
    """The known-good table (hashes only).  Raises ValueError on an unexpected schema."""
    doc = json.loads(Path(path or KNOWN_FILE).read_text(encoding="utf-8"))
    if doc.get("schema") != KNOWN_SCHEMA:
        raise ValueError(f"unsupported source known table schema: {doc.get('schema')!r}")
    return doc


def verify_file(game, rel, size, sha256, known=None):
    """Compare one file against every accepted build of that path.

    Returns ``(verified, known_build, note)`` where ``verified`` is ``"yes"`` (size and SHA-256 equal an accepted
    build), ``"no"`` (the path is known but the bytes differ) or ``"unknown"`` (the table has no row for it).
    """
    known = known if known is not None else load_known()
    rows = (known.get("games", {}).get(game, {}) or {}).get("files", {}).get(rel)
    if not rows:
        return "unknown", None, "not in the known-good table"
    for row in rows:
        if int(row.get("size", -1)) == int(size) and row.get("sha256") == sha256:
            return "yes", row.get("build"), row.get("note")
    builds = ", ".join(str(r.get("build")) for r in rows)
    note = next((r.get("note") for r in rows if r.get("note")), None)
    return "no", builds, note


def sha256_file(path):
    """SHA-256 of a file, read in chunks (no file contents are kept)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -------------------------------------------------------------------------------------------- manifest
def write_manifest(dest, games, *, tool="prep_source", extra=None):
    """Write ``<dest>/manifest.json`` atomically and return its path.

    The temporary file is unique and created inside ``dest`` (``mkstemp``), so a concurrent run cannot collide with
    a fixed ``.tmp`` name and the replace publishes only inside the validated destination (review finding 4).

    An existing ``manifest.json`` that cannot be read as a D5 source manifest is never replaced: the caller gets
    ``ForeignManifest`` and the file stays byte-identical (review R5).  The same check runs in ``tools/prep_source.py``
    before anything is copied, so a failed prep cannot publish over a foreign file either.
    """
    dest = Path(dest)
    path = dest / MANIFEST_FILE
    if path.exists() or path.is_symlink():
        try:
            read_manifest(dest)
        except (OSError, ValueError) as exc:
            raise ForeignManifest(
                f"{path} exists but is not a D5 source manifest ({exc}); "
                f"pick a fresh destination or move that file away") from exc
    doc = {
        "schema": MANIFEST_SCHEMA,
        "written": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "games": games,
    }
    if extra:
        doc.update(extra)
    dest.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=str(dest))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def read_manifest(dest):
    """Load ``<dest>/manifest.json``; raises ValueError on anything that is not a D5 source manifest.

    ``json.JSONDecodeError`` is a ``ValueError`` too, so a truncated file, another tool's JSON and a wrong schema
    all reach the caller the same way (review R5).
    """
    doc = json.loads((Path(dest) / MANIFEST_FILE).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"source manifest is not a JSON object: {type(doc).__name__}")
    if doc.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"unsupported source manifest schema: {doc.get('schema')!r}")
    if doc.get("games") is not None and not isinstance(doc.get("games"), dict):
        raise ValueError("source manifest has no games object")
    return doc


def verify_manifest(dest, known=None):
    """Re-hash every file a manifest lists and compare it with the known-good table.

    Returns one dict per file with game, path, expected/actual size and SHA-256 and the verified state
    (``yes`` / ``no`` / ``unknown`` / ``missing``).  Expensive: it reads every file.
    """
    known = known if known is not None else load_known()
    dest = Path(dest)
    out = []
    for game, entry in sorted((read_manifest(dest).get("games") or {}).items()):
        for rec in entry.get("files", []):
            rel = rec.get("path")
            path = dest / game / rel
            actual = None
            if path.is_file():
                actual = (path.stat().st_size, sha256_file(path))
            state = "missing" if actual is None else verify_file(game, rel, *actual, known=known)[0]
            out.append({
                "game": game,
                "path": rel,
                "expected_size": rec.get("size"),
                "expected_sha256": rec.get("sha256"),
                "actual_size": actual[0] if actual else None,
                "actual_sha256": actual[1] if actual else None,
                "verified": state,
            })
    return out
