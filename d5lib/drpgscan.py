"""Find Disgaea RPG sprites anywhere under a folder or in a zip: every layout the rips and the game come in.

drpgsource reads two fixed layouts at the top of one folder.  This walks the whole tree instead and recognises a
unit's sheets wherever they sit, by the folder a sheet is in and its file name:

    <...>/front/front<uid>[.png]        battle, front   (also BattleFront/)
    <...>/back/back<uid>[.png]          battle, back    (also BattleBack/)
    <...>/wait_front/front<uid>[.png]   idle, front     (also WaitFront/)
    <...>/wait_back/back<uid>[.png]     idle, back      (also WaitBack/)
    <...>/Icons|Chara Icons/<uid>.png, <...>/chara/face/<uid>.png        face
    <...>/Cut-Ins|Cutins/<uid>.png, <...>/chara/ci/<uid>.png             cut-in

That covers the flat PNG rip (Characters/Sprites/...), the Sprites/Standard rip, a decoded client dump
(tex/atlas/chara/battle/...) and the game's own asset bundles, a Unity-native rip or the install's files/ folder
(atlas/chara/battle/front/front<uid>, no extension, each a UnityFS bundle).  A bundle is turned into a PNG the first
time a builder asks for it (needs the optional UnityPy: pip install UnityPy), into state/drpg_scan/.

The sheets of one folder holding the four role folders are one "set" (Characters/Sprites, tex/atlas/chara/battle
...).  A unit takes all its sheets from one set, the one that has the most of them: sets are never mixed, a flat rip's
numbers don't always match the game's.  Suffixed names (front20105_non_eff, front20082_1) are the same unit; the plain
name wins.  Names: any "Units IDs.txt" in the tree; unique / generic from the game's masters/character if UnityPy can
read it.  Story characters (atlas/chara/story), the decoded dump's cut poses (sprite/.../front1/) and the
*_inversion folders are left out.
"""
import hashlib
import os
import re
import shutil
import zipfile

from .modsys import KIT_DIR

CACHE_DIR = os.path.join(KIT_DIR, "state", "drpg_scan")
ROLES = ("front", "back", "wait_front", "wait_back")
ROLE_DIRS = {"front": "front", "battlefront": "front", "back": "back", "battleback": "back",
             "wait_front": "wait_front", "waitfront": "wait_front", "wait_back": "wait_back", "waitback": "wait_back"}
EXTRA_DIRS = {"icons": "icon", "chara icons": "icon", "cut-ins": "cutin", "cutins": "cutin"}
CHARA_EXTRA_DIRS = {"face": "icon", "ci": "cutin"}      # only right under a "chara" folder (tex/images/chara/face)
SKIP_DIRS = {"__macosx", "story", "illustrations", "dialogue portraits"}
_SHEET = re.compile(r"^(front|back)(\d+)(?:_([0-9a-z_]+))?(\.png)?$", re.I)
_EXTRA = re.compile(r"^(\d+)\.png$", re.I)
_POSE_DIR = re.compile(r"^(front|back)\d+", re.I)        # a decoded dump's folder of cut poses: not a sheet
UNITYFS = b"UnityFS"
NAMES_FILE = "units ids.txt"


class ScanError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ the sources
class _Dir:
    """a folder: entries are paths relative to it, '/'-separated"""
    def __init__(self, root):
        self.root = root

    def walk(self):
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x.lower() not in SKIP_DIRS
                       and not _POSE_DIR.match(x) and not x.lower().endswith("_inversion")]
            rel = os.path.relpath(d, self.root).replace(os.sep, "/")
            for f in files:
                yield f if rel == "." else f"{rel}/{f}"

    def head(self, rel, n=8):
        try:
            with open(self.path(rel), "rb") as f:
                return f.read(n)
        except OSError:
            return b""

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def local(self, rel):
        """a path on disk for the entry"""
        return self.path(rel)


class _Zip:
    """a zip file: entries are its member names; a member is unpacked into the cache when it is needed"""
    def __init__(self, root):
        self.root = root
        self.zf = zipfile.ZipFile(root)

    def walk(self):
        for name in self.zf.namelist():
            if name.endswith("/"):
                continue
            parts = name.split("/")
            if any(p.startswith(".") or p.lower() in SKIP_DIRS or p.lower().endswith("_inversion")
                   or _POSE_DIR.match(p) for p in parts[:-1]):
                continue
            yield name

    def head(self, rel, n=8):
        with self.zf.open(rel) as f:
            return f.read(n)

    def local(self, rel):
        out = os.path.join(_cache_for(self.root), "zip", *rel.split("/"))
        if not os.path.exists(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with self.zf.open(rel) as src, open(out + ".part", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(out + ".part", out)
        return out


def _open(root):
    if os.path.isdir(root):
        return _Dir(root)
    if os.path.isfile(root) and zipfile.is_zipfile(root):
        return _Zip(root)
    raise ScanError(f"{root} is not a folder or a zip file")


def _cache_for(root):
    key = hashlib.sha1(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE_DIR, key)


# ------------------------------------------------------------------------------------------------ one scan
class Sheet:
    def __init__(self, rel, variant, bundle):
        self.rel = rel
        self.variant = variant or ""      # '' for the plain name, else '1', 'non_eff' ...
        self.bundle = bundle              # a UnityFS bundle (needs unpacking into a PNG)


class Found:
    """what a scan of one root found"""
    def __init__(self, root):
        self.root = root
        self.sets = {}         # set folder (rel) -> {uid: {role: Sheet}}
        self.extras = {}       # extras folder (rel) -> {uid: {key: rel}}
        self.names = {}        # uid -> (name, group)
        self.masters = []      # rels of masters/character bundles
        self.best = {}         # uid -> set folder
        self.source = None

    @property
    def uids(self):
        return sorted(self.best)

    def sheet_entries(self, uid):
        """{role: Sheet} of the unit (from its best set)"""
        s = self.best.get(uid)
        return dict(self.sets[s][uid]) if s is not None else {}

    def extra_entries(self, uid):
        """{'icon'/'cutin': rel}: from the extras folder nearest the unit's set"""
        base = self.best.get(uid, "")
        out = {}
        for folder in sorted(self.extras, key=lambda f: -_common(f, base)):
            for k, rel in self.extras[folder].get(uid, {}).items():
                out.setdefault(k, rel)
        return out


def _common(a, b):
    n = 0
    for x, y in zip(a.split("/"), b.split("/")):
        if x != y:
            break
        n += 1
    return n


def _better(sheet, old):
    """prefer the plain name, then a PNG over a bundle"""
    return (sheet.variant == "", not sheet.bundle) > (old.variant == "", not old.bundle)


def scan_root(root):
    """walk `root` (a folder or a zip) -> Found"""
    src = _open(root)
    found = Found(root)
    found.source = src
    names_files = []
    for rel in src.walk():
        parts = rel.split("/")
        fname, parent = parts[-1], (parts[-2].lower() if len(parts) > 1 else "")
        low = fname.lower()
        if low == NAMES_FILE:
            names_files.append(rel)
            continue
        if low == "character" and parent == "masters":
            found.masters.append(rel)
            continue
        role = ROLE_DIRS.get(parent)
        if role:
            m = _SHEET.match(fname)
            if not m or m.group(1).lower() != role.split("_")[-1]:
                continue
            bundle = not m.group(4)
            if bundle and src.head(rel, len(UNITYFS)) != UNITYFS:
                continue
            uid = int(m.group(2))
            sheet = Sheet(rel, m.group(3), bundle)
            units = found.sets.setdefault("/".join(parts[:-2]), {})
            old = units.setdefault(uid, {}).get(role)
            if old is None or _better(sheet, old):
                units[uid][role] = sheet
            continue
        key = EXTRA_DIRS.get(parent)
        if key is None and len(parts) > 2 and parts[-3].lower() == "chara":
            key = CHARA_EXTRA_DIRS.get(parent)
        if key:
            m = _EXTRA.match(fname)
            if m:
                found.extras.setdefault("/".join(parts[:-1]), {}).setdefault(int(m.group(1)), {})[key] = rel
    # a unit's set: the one with the most of its sheets; on a tie, the one needing no unpacking, then the first
    for s in sorted(found.sets):
        for uid, sheets in found.sets[s].items():
            cur = found.best.get(uid)
            if cur is None or _rank(sheets) > _rank(found.sets[cur][uid]):
                found.best[uid] = s
    for rel in names_files:
        for uid, v in _read_names(src.local(rel)).items():
            found.names.setdefault(uid, v)
    for rel in found.masters:
        for uid, group in _read_master_groups(src, rel).items():
            name, g = found.names.get(uid, ("", ""))
            found.names[uid] = (name, g or group)
    return found


def _rank(sheets):
    return len(sheets), -sum(s.bundle for s in sheets.values())


def _read_names(path):
    from .drpgsource import parse_unit_names
    try:
        return parse_unit_names(path)
    except OSError:
        return {}


def _read_master_groups(src, rel):
    """{uid: 'unique' / 'generic'} from the game's masters/character (unique_flg), {} without UnityPy"""
    try:
        import UnityPy
    except ImportError:
        return {}
    out = {}
    try:
        env = UnityPy.load(src.local(rel))
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            tree = obj.read_typetree()
            rows = tree.get("DataList") or tree.get("dataList") or []
            for row in rows:
                if isinstance(row, dict) and "id" in row and "unique_flg" in row:
                    out[int(row["id"])] = "unique" if int(row["unique_flg"]) else "generic"
    except Exception:
        return {}
    return out


# ------------------------------------------------------------------------------------------------ turning entries into PNGs
def _bundle_png(src, sheet, root):
    """the largest picture in a UnityFS bundle, as a PNG in the cache"""
    out = os.path.join(_cache_for(root), "png", *sheet.rel.split("/")) + ".png"
    if os.path.exists(out):
        return out
    try:
        import UnityPy
    except ImportError:
        raise ScanError("this Disgaea RPG folder holds the game's own asset bundles: reading them needs UnityPy "
                        "(pip install UnityPy)") from None
    env = UnityPy.load(src.local(sheet.rel))
    best = None
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        img = obj.read().image
        if best is None or img.width * img.height > best.width * best.height:
            best = img
    if best is None:
        raise ScanError(f"no picture in {sheet.rel}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    best.convert("RGBA").save(out + ".part.png")
    os.replace(out + ".part.png", out)
    return out


def resolve(found, sheet):
    """a PNG path on disk for a Sheet (a bundle is unpacked, a zip member extracted, once)"""
    if sheet.bundle:
        return _bundle_png(found.source, sheet, found.root)
    return found.source.local(sheet.rel)


# ------------------------------------------------------------------------------------------------ what the kit asks
_SCANS = {}


def _key(root):
    return os.path.normcase(os.path.abspath(root))


def get(root, refresh=False):
    """the (remembered) scan of `root`, or None if it isn't a folder / zip"""
    k = _key(root)
    if refresh or k not in _SCANS:
        try:
            _SCANS[k] = scan_root(root)
        except (ScanError, OSError, zipfile.BadZipFile):
            _SCANS[k] = None
    return _SCANS[k]


def forget(root=None):
    if root is None:
        _SCANS.clear()
    else:
        _SCANS.pop(_key(root), None)


def unit_sheets(root, uid):
    """{role: png path} of unit `uid` found under `root` (unpacked as needed), or None"""
    found = get(root)
    if not found or int(uid) not in found.best:
        return None
    return {role: resolve(found, s) for role, s in found.sheet_entries(int(uid)).items()}


def unit_extras(root, uid):
    """{'icon'/'cutin': png path} of unit `uid` under `root`"""
    found = get(root)
    if not found:
        return {}
    return {k: found.source.local(rel) for k, rel in found.extra_entries(int(uid)).items()}
