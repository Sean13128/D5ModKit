"""Disgaea 4 face and cut-in art, extracted straight from the player's own D4 game files (D4FACETOOL1).

Reads only `Data/DATA/WF.dat` (faces) and `Data/DATA/ANM_HI.dat` (cut-ins) of a Disgaea 4 Complete+ install and
writes PNGs.  Nothing is decrypted: both archives are plain NSAC containers.  No Forge, no derived art folder.

  face   `swf<N>.nltx` in WF.dat: "NMPLTEX1" header, linear BC7 texture (256x256), zlib "YKCMP_V1" envelope.
         BC7 is decoded by Pillow (wrapped in a DDS header), so there is no extra dependency.
  cut-in `anm<10000+N>.lzs` in ANM_HI.dat: a D4 ANM whose cells are rectangles of an 8-bit indexed page; the
         cell crop with the file's palette is the cut-in (390x1248 for the main cut-in, cell 1).

Output keeps the layout the D4 importer reads (`d5lib/importers/d4.py`), one folder per resource id N:

    character_id_<N:05d>/face/swf<N:04d>.png
    character_id_<N:05d>/cutin/ANM_HI__anm<10000+N>/native_frames/p<pal>_t<tex>_b<blk>_r<cell:05d>.png
    manifest.json   (sha256 of every PNG, source file sizes, counts)

D4FACEWIRE1: `face_rel` / `cutin_rel` are the one place those names are spelled, so the extractor, the importer and
`tools/d4_prepare_art.py` cannot drift (the cast id 70 is `swf0070.png`, never `swf70.png`).  `screen_art_dir` is the one
place the art folder is chosen: env `D5_D4_SCREEN_ART`, settings key `d4_screen_art`, else `<SOURCEPREP source>/d4-screen-art`
(SOURCEPREP2 resolver when that module is present, else `<kit>/Source`).  The October Character Forge extraction is
never a default input (SOURCEPREP4-D4); a machine that still has it names it through the env/setting, where it is
read-only (`is_legacy`).

Checked byte-equal against the October Character Forge extraction (see D4FACETOOL1-REPORT.md).
"""
import hashlib
import io
import json
import os
import re
import struct
import tempfile
import threading
import zlib
from contextlib import contextmanager
from pathlib import Path

from . import anm, d4source, lzs

FACE_SIZE_LIMIT = 4096

# ---------------------------------------------------------------- where the extracted art lives (D4FACEWIRE1)
SCREEN_ART_ENV = "D5_D4_SCREEN_ART"        # explicit folder wins over everything
SCREEN_ART_SETTING = "d4_screen_art"       # settings.json key, same precedence idea as SOURCEPREP2
ART_FOLDER = "d4-screen-art"               # under the SOURCEPREP source folder
# The October 2026 Character Forge extraction on the development workstation.  Only a fallback for machines that
# have it: every new build reads the extractor output above.  Never treated as evidence of what the game contains.
LEGACY_ART = Path("/Volumes/Data/CharForge-Backup/2026-10-16-211736/Extracted artwork (DImages)/Disgaea 4 Complete+")

TOOL = "d5lib.d4screenart"                  # the `tool` marker that says a `manifest.json` is ours


class ForeignReceipt(ValueError):
    """A `manifest.json` in the art folder is not ours (another tool's JSON, plain text, a non-dict).

    R5: an existing receipt this module did not write is user data.  Nothing may be extracted or published over
    it: the caller is told, and the file keeps every byte."""


def face_rel(n):
    """Relative path of resource id `n`'s face inside the art folder: `character_id_00070/face/swf0070.png`."""
    return f"character_id_{int(n):05d}/face/swf{int(n):04d}.png"


def cutin_dir_rel(n):
    """Relative folder of resource id `n`'s cut-in cells: `character_id_00070/cutin/ANM_HI__anm10070`."""
    return f"character_id_{int(n):05d}/cutin/ANM_HI__anm{10000 + int(n)}"


FRAMES_FOLDER = "native_frames"          # the folder inside an ANM cut-in that holds its cell PNGs


def cutin_rel(n, pal=0, tex=0, block=0, cell=1):
    """Relative path of one cut-in cell.  The importer reads palette 0, texture 0, block 0, cell 1."""
    return (f"{cutin_dir_rel(n)}/{FRAMES_FOLDER}/p{int(pal):03d}_t{int(tex):03d}_b{int(block):02d}"
            f"_r{int(cell):05d}.png")


_FACE_ID = re.compile(r"swf(\d+)\.png$")
_CUTIN_ID = re.compile(r"ANM_HI__anm(\d+)")
_ANM_ID = re.compile(r"(?:^|/)anm(\d+)(?:\.|/|$)")


def resource_id(flag, recorded):
    """The resource id encoded in a recorded `--face-path` / `--cutin-path`, or ``None``.

    A named character's screen art need not be its own row: row 180 records `swf0054.png` / `anm10054` (id 54)
    and row 220 records id 74, and the containing folder (`character_id_00050`) is not the id either.  Only the
    file or member name is authoritative.  ``None`` means the path is not a screen-art name (a deliberate
    prepared-image fallback), which the caller must keep as it is.
    """
    name = str(recorded).replace("\\", "/")
    if flag == "--face-path":
        m = _FACE_ID.search(name)
        return int(m.group(1)) if m else None
    m = _CUTIN_ID.search(name) or _ANM_ID.search(name)
    if not m:
        return None
    value = int(m.group(1))
    return value - 10000 if value >= 10000 else value


def _resolved_inside(path, root):
    """True when `path` resolves to `root` or anywhere below it (symlinks and `..` resolved; a missing tail is fine)."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def is_legacy(path):
    """True when `path` is the October Character Forge archive or lies inside it, through a symlink or `..` spelling.

    R4: an explicitly selected descendant of the archive, or a cache folder whose per-id directory is a symlink into
    it, is the archive too: nothing may be written through either."""
    try:
        return _resolved_inside(path, LEGACY_ART)
    except OSError:
        return False


def _guard_destination(path):
    """Refuse to write a file whose resolved path lands inside the October Forge archive.

    `is_legacy` on the cache root covers the folder itself and descendants; this covers a destination that only
    aliases the archive (a per-id directory symlink), which the PNG writer would otherwise follow."""
    if is_legacy(path):
        raise ValueError(f"refusing to write into the October Forge archive: {path}")


def source_root():
    """The SOURCEPREP source folder in use (SOURCEPREP2 `sourcefolder` when merged, else `<kit>/Source`)."""
    try:
        from .sourcefolder import source_dir            # SOURCEPREP2, merged separately
        return Path(source_dir())
    except Exception:                                   # noqa: BLE001 - the module is not on every branch yet
        from . import paths
        return Path(paths.KIT_DIR) / "Source"


def explicit_art_dir():
    """The folder the user named (env `D5_D4_SCREEN_ART`, else settings `d4_screen_art`), or None."""
    env = os.environ.get(SCREEN_ART_ENV)
    if env and env.strip():
        return Path(env.strip()).expanduser()
    try:
        from . import paths
        saved = paths.kit_setting(SCREEN_ART_SETTING)
    except Exception:                                   # noqa: BLE001 - a bare tools import
        saved = None
    if saved and str(saved).strip():
        return Path(str(saved).strip()).expanduser()
    return None


def screen_art_dir(required=False):
    """The folder holding `character_id_*/face|cutin` PNGs for the D4 importer and the art preparation.

    Order: ``D5_D4_SCREEN_ART``, settings.json ``d4_screen_art``, ``<source folder>/d4-screen-art`` when it exists,
    then the October Forge extraction when that exists (older machines), then the source-folder default.
    Raises FileNotFoundError with the extractor command when ``required`` and the chosen folder is absent.
    """
    env = os.environ.get(SCREEN_ART_ENV)
    if env and env.strip():
        chosen = Path(env.strip()).expanduser()
        if not required or chosen.is_dir():
            return chosen
        raise FileNotFoundError(
            f"{SCREEN_ART_ENV} points at {chosen}, which is not a folder. Run "
            f"`python tools/d4_extract_screen_art.py <Disgaea 4 Complete+ folder> {chosen}` to fill it.")
    try:
        from . import paths
        saved = paths.kit_setting(SCREEN_ART_SETTING)
    except Exception:                                   # noqa: BLE001 - a bare tools import
        saved = None
    if saved and str(saved).strip():
        chosen = Path(str(saved).strip()).expanduser()
        if not required or chosen.is_dir():
            return chosen
        raise FileNotFoundError(
            f"settings.json {SCREEN_ART_SETTING} points at {chosen}, which is not a folder. Run "
            f"`python tools/d4_extract_screen_art.py <Disgaea 4 Complete+ folder> {chosen}` to fill it.")
    default = source_root() / ART_FOLDER
    if default.is_dir():
        return default
    # SOURCEPREP4-D4: the October Forge extraction is never a default input.  A machine that wants it names it
    # explicitly through D5_D4_SCREEN_ART / settings.json d4_screen_art (above), where it is read-only.
    if required:
        raise FileNotFoundError(
            f"No extracted D4 face/cut-in art at {default}. Extract it from your own game files with "
            f"`python tools/d4_extract_screen_art.py <Disgaea 4 Complete+ folder> {default}` "
            f"(the source folder is prepared by tools/prep_source.py).")
    return default


def art_paths(n, folder=None):
    """`(face, cutin)` paths of resource id `n` in the art folder (default: `screen_art_dir()`)."""
    folder = Path(folder) if folder is not None else screen_art_dir()
    return folder / face_rel(n), folder / cutin_rel(n)


# D4 stores a class's colour variants as consecutive face ids: swf2090..swf2099 is Demon Beast in its ten colours.
# `sourceimports.colour_variants` (the class builder) reads exactly that run, so the importer must have it extracted.
COLOUR_VARIANTS = 10


def family_ids(n, colours=COLOUR_VARIANTS):
    """The face ids a class's colour variants read: `n` .. `n + colours - 1`."""
    return list(range(int(n), int(n) + int(colours)))


_M32 = 0xFFFFFFFF


def uses_own_colour_face(char_id, story_flag_d58=0):
    """FUN_1401b1430 (D4-FACE-02): True when the game draws the char.dat colour id as the face number for this
    character id (ids below 1000 outside a few ranges, 0x1518..0x157b except 0x1530..0x1539); False for class and
    rank rows (1000 and up) and NPC rows, which use the colour id rounded down to tens."""
    p = int(char_id) & _M32
    if ((p - 0x1518) & _M32) < 100:
        return ((p - 0x1530) & _M32) > 9
    signed = p - (1 << 32) if p & 0x80000000 else p
    return bool(((p - 0x7DA) & _M32) > 0x122
                and (story_flag_d58 == 0 or ((p - 0xDB8) & _M32) > 0x12)
                and ((p - 1000) & _M32) > 0x136
                and signed < 1000)


def game_face_number(char_id, color_id, story_flag_d58=0):
    """FUN_14047bfb0 (D4-FACE-02, proven under Unicorn on the real char.dat, 154,613 cases, 0 mismatches): the face
    texture number `swf<N>` the game draws for a character row.  -1 for id 0.  The colour id for the ids
    `uses_own_colour_face` accepts (Des X colour 54, Nemo 74), the colour id rounded down to tens otherwise, so all six
    rank rows of a class share the class face (Armor Knight 1081 -> 1080) and NPC rows use their class face
    (Chief 1154 -> 1150, Kojiro 1142 -> 1140, Arsailles 2144 -> 2140)."""
    if int(char_id) == 0:
        return -1
    color_id = int(color_id)
    if uses_own_colour_face(char_id, story_flag_d58):
        return color_id
    return (color_id // 10) * 10 if color_id >= 0 else -((-color_id) // 10) * 10


def missing(ids, folder=None, kind="face"):
    """The ids of `ids` whose face (or cut-in) PNG is absent from `folder` (default: `screen_art_dir()`)."""
    folder = Path(folder) if folder is not None else screen_art_dir()
    rel = face_rel if kind == "face" else cutin_rel
    return [int(i) for i in ids if not (folder / rel(i)).is_file()]


_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(folder):
    """One `threading.Lock` per art folder, shared by the importer's worker threads (import_game --jobs)."""
    key = str(Path(folder).resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _cache_lock(folder):
    """Serialise manifest read/update/publish for one art folder, across threads and processes.

    Threads share `_thread_lock` (flock is per open file description, so it would also work, but the
    threading lock keeps same-process waits off the file system); `flock` covers a second process."""
    folder = Path(folder)
    _guard_destination(folder)                             # R5: the folder itself, through a symlink chain
    folder.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:                                 # pragma: no cover - POSIX-only kit
        fcntl = None
    with _thread_lock(folder):
        lock_path = folder / ".manifest.lock"
        # R5: `open(..., "a+")` creates the file, so a dangling lock symlink into the archive wrote there.
        _guard_destination(lock_path)
        handle = open(lock_path, "a+")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _read_manifest(folder):
    path = Path(folder) / "manifest.json"
    try:
        if path.stat().st_size:
            doc = json.loads(path.read_text())
            return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _owned_manifest(folder):
    """The existing receipt in `folder`, which must be ours; a foreign or unreadable one is rejected untouched.

    R5: `_read_manifest()` maps a malformed document, a JSON non-dict or another tool's receipt to `{}`, so a
    later merge/publish silently destroyed a user file.  A folder whose `manifest.json` is not a D4 art receipt
    is not our cache: raise `ForeignReceipt` *before* any PNG is written or the receipt is replaced, and leave
    the existing file byte-identical.  A missing or empty file holds nothing to lose and counts as absent."""
    path = Path(folder) / "manifest.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ForeignReceipt(f"cannot read {path} ({exc}); refusing to overwrite it") from exc
    if not raw.strip():
        return {}
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise ForeignReceipt(f"{path} is not JSON ({exc}); refusing to overwrite it") from exc
    if not isinstance(doc, dict) or doc.get("tool") != TOOL:
        raise ForeignReceipt(f"{path} is not a {TOOL} receipt; refusing to overwrite it")
    return doc


def _merge_manifests(old, docs):
    """The previous manifest plus what each extraction just wrote; entries are kept, never replaced wholesale.

    A cut-in's rows are merged per relative filename, not per id: filling the palette-0 frames of an id whose
    palette-1..15 frames already exist must not drop those rows."""
    merged = {"tool": TOOL, "source": {}, "palettes": [], "faces": {}, "cutins": {},
              "errors": {}, "missing": {"face": [], "cutin": []}}
    if isinstance(old, dict) and old.get("tool") == merged["tool"]:
        merged["source"] = dict(old.get("source") or {})
        merged["palettes"] = list(old.get("palettes") or [])
        for key in ("faces", "cutins", "errors"):
            merged[key] = dict(old.get(key) or {})
    for doc in docs:
        merged["source"].update(doc.get("source") or {})
        merged["palettes"] = sorted(set(merged["palettes"]) | set(doc.get("palettes") or []))
        for key in ("faces", "errors"):
            merged[key].update(doc.get(key) or {})
        for n, rows in (doc.get("cutins") or {}).items():
            by_file = {row.get("file"): row for row in merged["cutins"].get(str(n)) or []}
            for row in rows or []:
                by_file[row.get("file")] = row
            merged["cutins"][str(n)] = sorted(by_file.values(), key=lambda row: str(row.get("file")))
    for kind, key in (("face", "faces"), ("cutin", "cutins")):
        absent = set((old.get("missing") or {}).get(kind) or []) if isinstance(old, dict) else set()
        for doc in docs:
            absent |= set((doc.get("missing") or {}).get(kind) or [])
        present = {int(x) for x in merged[key] if str(x).isdigit()}
        absent -= present                               # an id that is now present is no longer missing
        merged["missing"][kind] = sorted(absent)
    return merged


def _publish_manifest(folder, doc):
    """Write `manifest.json` atomically: a crash mid-write leaves the previous manifest intact."""
    folder = Path(folder)
    _guard_destination(folder)
    _guard_destination(folder / "manifest.json")
    _owned_manifest(folder)                  # R5: never replace someone else's receipt, whatever the caller
    real_folder = folder.resolve()           # R5: stage and replace in the folder actually written
    _guard_destination(real_folder)
    fd, tmp = tempfile.mkstemp(dir=str(real_folder), prefix=".manifest-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(doc, indent=1) + "\n")
        os.replace(tmp, real_folder / "manifest.json")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_CELL_FILE = re.compile(r"^p\d{3}_t\d{3}_b\d{2}_r\d{5}\.png$")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _png_size(path):
    """`[width, height]` from the file's IHDR, or ``None`` when it is not a readable PNG."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return list(struct.unpack(">2I", head[16:24]))


def _file_entry(path, folder, with_size=False):
    """A manifest row for a PNG already on disk (never rewrites it)."""
    entry = {"file": Path(path).relative_to(folder).as_posix(), "sha256": _sha256(path)}
    if with_size:
        size = _png_size(path)
        if size is not None:
            entry["size"] = size
    return entry


_CELL_PALETTE = re.compile(r"^p(\d{3})_")


def _unrecorded(folder, doc, face_ids, cutin_ids):
    """True when a requested PNG on disk is unrecorded in `doc` (a manifest) or no longer matches its row.

    The digest part is bounded to the requested ids: a file replaced after its row was recorded (a run that
    wrote new bytes and failed to publish) is repaired on the next call instead of being certified by the old
    digest.  Files are hashed again under the cache lock; this pre-check only decides whether to take it."""
    faces = doc.get("faces") or {}
    cutins = doc.get("cutins") or {}
    for n in face_ids:
        path = folder / face_rel(n)
        if path.is_file():
            row = faces.get(str(n))
            if row is None or row.get("sha256") != _sha256(path):
                return True
    for n in cutin_ids:
        known = {row.get("file"): row for row in cutins.get(str(n)) or []}
        d = folder / cutin_dir_rel(n) / FRAMES_FOLDER
        if not d.is_dir():
            continue
        for path in d.iterdir():
            if not _CELL_FILE.match(path.name):
                continue
            rel = path.relative_to(folder).as_posix()
            row = known.get(rel)
            if row is None or row.get("sha256") != _sha256(path):
                return True
    return False


def _source_sizes(game):
    """`{"WF.dat": bytes, "ANM_HI.dat": bytes}` of the copy `game` names, or {} when it cannot be read."""
    if game is None:
        return {}
    try:
        paths = archive_paths(game)
    except (FileNotFoundError, OSError, ValueError):
        return {}
    sizes = {}
    for name, path in zip(("WF.dat", "ANM_HI.dat"), paths):
        try:
            sizes[name] = path.stat().st_size
        except OSError:
            pass
    return sizes


def _reconcile(folder, doc, face_ids, cutin_ids, game=None):
    """Manifest entries for PNGs on disk that `doc` does not certify, and rows whose file changed.

    This is the repair half of the cache contract: `extract()` writes PNGs, then ONE merged receipt is
    published.  If that publish fails, the next call for the same ids finds the files present (so there is
    nothing to extract) and would otherwise return early, leaving the receipt incomplete forever.  Rows are
    repaired as well as added: a regenerated file whose publish failed no longer matches its old digest, and a
    row whose file is gone is dropped instead of certifying a file that no longer exists.  Extraction metadata
    is recovered too: an empty cache whose first publish failed gets the source sizes back from `game` and the
    palettes back from the cell file names, documents that died with the failed publish.  Files are hashed,
    never rewritten."""
    found = {"tool": TOOL, "source": {} if doc.get("source") else _source_sizes(game),
             "palettes": [], "faces": {}, "cutins": {}, "errors": {},
             "missing": {"face": [], "cutin": []}}
    palettes = set()
    faces = doc.get("faces") or {}
    cutins = doc.get("cutins") or {}
    for n in face_ids:
        path = folder / face_rel(n)
        row = faces.get(str(n))
        if path.is_file() and (row is None or row.get("sha256") != _sha256(path)):
            found["faces"][str(n)] = _file_entry(path, folder)
    for n in cutin_ids:
        rows = list(cutins.get(str(n)) or [])
        changed = False
        kept = []
        for row in rows:
            path = folder / str(row.get("file") or "")
            if not path.is_file():
                changed = True                 # the receipt must not certify a file that is gone
                continue
            actual = _sha256(path)
            if row.get("sha256") != actual:
                row = dict(row, sha256=actual)
                changed = True
            kept.append(row)
            m = _CELL_PALETTE.match(str(row.get("file") or "").rsplit("/", 1)[-1])
            if m:
                palettes.add(int(m.group(1)))
        known = {row.get("file") for row in kept}
        d = folder / cutin_dir_rel(n) / FRAMES_FOLDER
        if d.is_dir():
            for path in sorted(d.iterdir(), key=lambda p: p.name):
                if not _CELL_FILE.match(path.name):
                    continue
                palettes.add(int(path.name[1:4]))
                rel = path.relative_to(folder).as_posix()
                if rel not in known:
                    kept.append(_file_entry(path, folder, with_size=True))
                    known.add(rel)
                    changed = True
        if changed:
            found["cutins"][str(n)] = kept
    found["palettes"] = sorted(palettes)
    return found


def _receipted(folder, doc, face_ids, cutin_ids):
    """(face ids, cut-in ids) whose requested PNG is on disk AND recorded in `doc` with the SHA-256 it still has.

    A file that sits in the folder without a matching receipt row is not trusted: `ensure(verified=True)`
    extracts it again instead of using or certifying it."""
    faces, cutins = doc.get("faces") or {}, doc.get("cutins") or {}
    good_faces = []
    for n in face_ids:
        row, path = faces.get(str(n)), folder / face_rel(n)
        if row and row.get("file") == face_rel(n) and path.is_file() and row.get("sha256") == _sha256(path):
            good_faces.append(n)
    good_cutins = []
    for n in cutin_ids:
        rows = {row.get("file"): row for row in cutins.get(str(n)) or []}
        primary = cutin_rel(n)
        row, path = rows.get(primary), folder / primary
        if row and path.is_file() and row.get("sha256") == _sha256(path):
            good_cutins.append(n)
    return good_faces, good_cutins


def ensure(ids=None, game=None, folder=None, palettes=(0,), log=None, face_ids=None, cutin_ids=None,
           verified=False):
    """Extract the ids that `folder` lacks from the D4 data at `game`.

    `game` is the D4 install (or a prepared source folder holding `Data/DATA/WF.dat` and `ANM_HI.dat`).
    `face_ids` and `cutin_ids` are independent requests: the class builder asks only for the faces of a
    colour-variant run, and a face fill must not drag its cut-ins along.  `ids` means the same list for both
    kinds (kept for callers that want both).

    Faces and cut-ins are filled independently: an id missing only its cut-in has just the cut-in written, so
    an existing face is never rewritten (and the reverse; an existing sibling cut-in frame is kept too).  The
    extraction receipts stay private: the previous `manifest.json` is read first, the new entries are merged
    into it, and ONE merged receipt is published atomically under a per-folder cache lock, so an interrupted
    update never exposes a subset and parallel jobs cannot drop each other's entries.  A retry whose files
    were already written by such an interrupted update records them instead of extracting again.

    `verified=True` is the importer's own build folder: a PNG counts as present only when this folder's receipt
    records it with the SHA-256 it still has, a file without such a row is extracted again over the top, and no
    unknown file is ever certified (no repair of the receipt from what happens to be on disk).

    Returns the ids written; `[]` when nothing had to be extracted (including a receipt repair)."""
    folder = Path(folder) if folder is not None else screen_art_dir()
    if face_ids is None and cutin_ids is None:
        face_ids = cutin_ids = list(ids or [])
    face_ids = [int(i) for i in face_ids or []]
    cutin_ids = [int(i) for i in cutin_ids or []]
    if verified:
        return _ensure_verified(game, folder, palettes, log, face_ids, cutin_ids)
    need_face = missing(face_ids, folder, "face")
    need_cutin = missing(cutin_ids, folder, "cutin")
    if not need_face and not need_cutin and not _unrecorded(folder, _read_manifest(folder),
                                                            face_ids, cutin_ids):
        return []
    with _cache_lock(folder):
        need_face = missing(face_ids, folder, "face")   # re-check: another worker may have filled them
        need_cutin = missing(cutin_ids, folder, "cutin")
        old = _owned_manifest(folder)                   # R5: reject a foreign receipt before anything is written
        docs = []
        if need_face:
            docs.append(extract(game, folder, ids=need_face, palettes=palettes, log=log,
                                kinds=("face",), publish=False))
        if need_cutin:
            docs.append(extract(game, folder, ids=need_cutin, palettes=palettes, log=log,
                                kinds=("cutin",), publish=False))
        merged = _merge_manifests(old, docs)
        repaired = _reconcile(folder, merged, face_ids, cutin_ids, game=game)
        if any(repaired[key] for key in ("faces", "cutins", "source", "palettes")):
            merged = _merge_manifests(merged, [repaired])
        _publish_manifest(folder, merged)                # ONE publish, complete
        written = set()
        for doc in docs:
            written |= {int(x) for x in (doc.get("faces") or {})}
            written |= {int(x) for x in (doc.get("cutins") or {})}
        return sorted(written)


def archive_paths(game):
    """`(WF.dat, ANM_HI.dat)` of `game`: a verified source set (`_d4_source.D4Files`, whose `path` refuses an
    unlisted file and re-proves the manifest SHA-256), or a folder the old shapes accept (diagnostic runs)."""
    if hasattr(game, "files") and callable(getattr(game, "path", None)):
        return game.path("Data/DATA/WF.dat"), game.path("Data/DATA/ANM_HI.dat")
    d = data_dir(game)
    return d / "WF.dat", d / "ANM_HI.dat"


def _ensure_verified(game, folder, palettes, log, face_ids, cutin_ids):
    with _cache_lock(folder):
        old = _owned_manifest(folder)
        good_faces, good_cutins = _receipted(folder, old, face_ids, cutin_ids)
        need_face = [n for n in face_ids if n not in good_faces]
        need_cutin = [n for n in cutin_ids if n not in good_cutins]
        docs = []
        if need_face:
            docs.append(extract(game, folder, ids=need_face, palettes=palettes, log=log,
                                kinds=("face",), publish=False, preserve_existing=False))
        if need_cutin:
            docs.append(extract(game, folder, ids=need_cutin, palettes=palettes, log=log,
                                kinds=("cutin",), publish=False, preserve_existing=False))
        if docs:
            _publish_manifest(folder, _merge_manifests(old, docs))
        written = set()
        for doc in docs:
            written |= {int(x) for x in (doc.get("faces") or {})}
            written |= {int(x) for x in (doc.get("cutins") or {})}
        return sorted(written)


def data_dir(root):
    """Accept the game folder, its `Data` folder or `Data/DATA`; return the folder holding WF.dat / ANM_HI.dat."""
    root = Path(root)
    for cand in (root, root / "DATA", root / "Data" / "DATA", root / "Disgaea 4 Complete+" / "Data" / "DATA"):
        if (cand / "WF.dat").is_file() and (cand / "ANM_HI.dat").is_file():
            return cand
    raise FileNotFoundError(f"no Disgaea 4 Data/DATA with WF.dat and ANM_HI.dat under {root}")


def _dds_bc7(pixels, width, height):
    """Minimal DDS file (DX10 header, DXGI_FORMAT_BC7_UNORM) around raw BC7 blocks, for Pillow's decoder."""
    header = (b"DDS " + struct.pack("<7I", 124, 0x1007 | 0x80000, height, width, len(pixels), 0, 0) + bytes(44)
              + struct.pack("<2I4s5I", 32, 4, b"DX10", 0, 0, 0, 0, 0) + struct.pack("<5I", 0x1000, 0, 0, 0, 0))
    return header + struct.pack("<5I", 98, 3, 0, 1, 0) + pixels


def decode_face(raw):
    """One `swf*.nltx` member -> PIL RGBA image."""
    from PIL import Image
    if len(raw) < 148 or raw[:8] != b"NMPLTEX1":
        raise ValueError("not a D4 face texture")
    width, height = struct.unpack_from("<2I", raw, 24)
    if raw[20] != 6 or not 0 < width <= FACE_SIZE_LIMIT or not 0 < height <= FACE_SIZE_LIMIT:
        raise ValueError("unverified D4 face texture format")
    kind, packed, size = struct.unpack_from("<3I", raw, 136)
    expected = ((width + 3) // 4) * ((height + 3) // 4) * 16
    if raw[128:136] != b"YKCMP_V1" or kind != 7 or packed != len(raw) - 128 or size != expected:
        raise ValueError("invalid D4 face compression envelope")
    d = zlib.decompressobj()
    pixels = d.decompress(raw[148:], expected + 1)
    if len(pixels) != expected or not d.eof or d.unused_data:
        raise ValueError("D4 face payload exceeds its declared size")
    image = Image.open(io.BytesIO(_dds_bc7(pixels, width, height)))
    image.load()
    return image.convert("RGBA")


def cutin_cells(raw_lzs, palettes=(0,)):
    """`anm1xxxx.lzs` member -> [(palette, cell texture, block, cell index, RGBA image)] for each visible cell."""
    a = d4source.read_anm(lzs.decompress(raw_lzs))
    out = []
    for bi, block in enumerate(a.blocks):
        for pal in palettes:
            if pal >= max(1, len(a.palettes)):
                continue
            pages = {}
            for ci, c in enumerate(block.cells):
                if c.w <= 0 or c.h <= 0:
                    continue
                tex = block.tex_base + c.tex
                if tex >= len(a.textures):
                    continue
                if tex not in pages:
                    pages[tex] = anm.texture_to_image(a, tex, block.pal_base + pal)
                page = pages[tex]
                if c.x + c.w > page.width or c.y + c.h > page.height:
                    continue
                out.append((pal, c.tex, bi, ci, page.crop((c.x, c.y, c.x + c.w, c.y + c.h))))
    return out


def _write_atomic(path, data):
    """Write `data` to `path` through a temp file in the same folder: no partial file ever reaches `path`.

    A failed write or replace raises and removes the temp file; whatever was already at `path` is untouched.
    R4: a direct write could leave a truncated PNG that the receipt then certified as complete."""
    path = Path(path)
    _guard_destination(path)
    parent = path.parent
    # R5: the leaf can resolve outside the archive while its directory resolves inside (a face-directory symlink
    # into the archive with the PNG symlinked back out).  The temp file is created in the parent and `replace`
    # acts on the parent's directory entry, so the parent itself must be guarded and its resolved path used.
    _guard_destination(parent)
    parent.mkdir(parents=True, exist_ok=True)
    real_parent = parent.resolve()
    _guard_destination(real_parent)
    fd, tmp = tempfile.mkstemp(dir=str(real_parent), prefix=".png-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)               # mkstemp creates 0600; keep the readable PNG the direct write made
        os.replace(tmp, real_parent / path.name)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _png(path, image):
    buf = io.BytesIO()
    # The October Character Forge extraction (which the installed packs' screen art came from) saved with
    # PIL's compress_level=1.  The pixels are identical, so keep the encoder setting and every rebuilt pack
    # carries byte-identical face/cut-in PNGs (SOURCEPREP4-D4 acceptance 1).
    image.save(buf, "PNG", compress_level=1)
    data = buf.getvalue()
    _write_atomic(path, data)
    return hashlib.sha256(data).hexdigest()


def extract(game, out_dir, ids=None, palettes=(0,), log=None, kinds=("face", "cutin"),
            publish=True, preserve_existing=True):
    """Write faces and cut-ins for resource ids `ids` (default: every one the game has) under `out_dir`.

    `kinds` limits the members written (`"face"`, `"cutin"`): a cache can fill a face without rewriting the
    cut-in it already has.  `publish=False` returns the receipt without touching `out_dir/manifest.json`:
    `ensure()` uses it so that the live receipt is never replaced by a subset.  `preserve_existing` keeps a
    PNG that is already on disk (and records it from the file) instead of rewriting it; a cut-in whose primary
    frame is missing therefore keeps its sibling frames byte-for-byte.  Returns the manifest dict (also saved
    as out_dir/manifest.json when `publish`)."""
    out = Path(out_dir)
    if is_legacy(out):
        raise ValueError(f"refusing to write into the October Forge archive: {out}")
    if publish:
        _owned_manifest(out)                    # R5: a foreign `manifest.json` is not ours to replace
    wf_path, am_path = archive_paths(game)
    out.mkdir(parents=True, exist_ok=True)
    kinds = tuple(kinds)
    wf, am = d4source.Nsac(wf_path), d4source.Nsac(am_path)
    faces = {int(n[3:7]): n for n in wf.members if n.startswith("swf") and n.endswith(".nltx") and n[3:7].isdigit()}
    cutins = {int(n[3:8]) - 10000: n for n in am.members
              if n.startswith("anm1") and n.endswith(".lzs") and n[3:8].isdigit()}
    wanted = sorted(set(faces) | set(cutins)) if ids is None else sorted(set(ids))
    for n in wanted:                        # a per-id directory symlink into the archive is the archive too
        face_path = out / face_rel(n)
        frames = out / cutin_dir_rel(n) / FRAMES_FOLDER
        # R5: the writer stages a temp in the parent and replaces the parent's directory entry, so an aliased
        # output parent (face dir or ANM frames dir into the archive) is the archive even when the leaf symlinks
        # back out.  Guarded here, outside the per-member handler, so a containment refusal stops the run.
        for dest in (face_path, face_path.parent, frames.parent, frames):
            _guard_destination(dest)
    manifest = {"tool": TOOL, "source": {"WF.dat": wf_path.stat().st_size, "ANM_HI.dat": am_path.stat().st_size},
                "palettes": list(palettes), "faces": {}, "cutins": {}, "errors": {},
                "missing": {"face": [], "cutin": []}}
    for n in wanted:
        if "face" in kinds:
            if n in faces:
                try:
                    rel = face_rel(n)
                    if preserve_existing and (out / rel).is_file():
                        manifest["faces"][str(n)] = _file_entry(out / rel, out)
                    else:
                        manifest["faces"][str(n)] = {"file": rel,
                                                     "sha256": _png(out / rel, decode_face(wf.read(faces[n])))}
                except Exception as exc:  # one bad member must not stop the run
                    manifest["errors"][faces[n]] = str(exc)
            else:
                manifest["missing"]["face"].append(n)
        if "cutin" in kinds:
            if n in cutins:
                try:
                    rows = []
                    for pal, tex, bi, ci, img in cutin_cells(am.read(cutins[n]), palettes):
                        rel = cutin_rel(n, pal, tex, bi, ci)
                        if preserve_existing and (out / rel).is_file():
                            rows.append(_file_entry(out / rel, out, with_size=True))
                        else:
                            rows.append({"file": rel, "size": list(img.size),
                                         "sha256": _png(out / rel, img)})
                    manifest["cutins"][str(n)] = sorted(rows, key=lambda row: row["file"])
                except Exception as exc:
                    manifest["errors"][cutins[n]] = str(exc)
            else:
                manifest["missing"]["cutin"].append(n)
        if log:
            log(n)
    if publish:
        _publish_manifest(out, manifest)
    return manifest


def extract_locked(game, folder, ids=None, palettes=(0,), log=None, refresh=False):
    """The documented extractor CLI's path into a shared cache: one locked read/merge/publish per run.

    R4: `extract()` publishes only its own receipt, so a CLI run over a folder the importer also uses could
    replace unrelated rows or race a parallel importer update.  This takes the same per-folder lock and merges
    the previous receipt exactly like `ensure()`, so a subset run adds its ids and keeps every other row.  A
    PNG already on disk is kept and re-hashed (never certified against a stale row); `refresh=True` is the
    deliberate way to replace the requested ids' PNGs with freshly extracted bytes.  Returns the receipt for
    the ids this run touched."""
    folder = Path(folder)
    if is_legacy(folder):
        raise ValueError(f"refusing to write into the October Forge archive: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    with _cache_lock(folder):
        old = _owned_manifest(folder)                # R5: reject a foreign receipt before PNGs are written
        doc = extract(game, folder, ids=ids, palettes=palettes, log=log, publish=False,
                      preserve_existing=not refresh)
        merged = _merge_manifests(old, [doc])
        face_ids = sorted({int(x) for x in (doc.get("faces") or {})}
                          | {int(x) for x in (doc.get("missing") or {}).get("face") or []})
        cutin_ids = sorted({int(x) for x in (doc.get("cutins") or {})}
                           | {int(x) for x in (doc.get("missing") or {}).get("cutin") or []})
        repaired = _reconcile(folder, merged, face_ids, cutin_ids, game=game)
        if any(repaired[key] for key in ("faces", "cutins", "source", "palettes")):
            merged = _merge_manifests(merged, [repaired])
        _publish_manifest(folder, merged)                # ONE publish of the whole cache
        return doc
