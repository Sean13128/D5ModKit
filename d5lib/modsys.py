"""Mod projects, build pipeline and the reversible in-place installer.

A mod is a folder under `D5ModKit/mods/<folder>/`:
    mod.json                       {"name", "author", "version", "description"}
    files/<virtual path>           replacement *logical* content for any game member, e.g.
                                   files/Anime/ANM_HI_JP.dat/anm00620.lzs   (decompressed anm data)
                                   files/Start/Start_JP.dat/Texture.dat/button.txf
                                   files/Map/Map_JP.dat/map30001.lzs/map30001.chr
                                   files/Script/talk.dat                    (decoded talk.dat)
    patches/<handler>/*.json       structured patches (database rows, dialogue lines, ...)
                                   applied by registered patch handlers, in mod priority order.

The active profile's load order (profiles/<id>/load_order.json, see d5lib/profiles.py) lists the enabled mods
(first = lowest priority).

Install strategy (fast and fully reversible):
  * NISPACK archives are patched *in place by appending*: new member data is written after the
    original end of file and the directory is rewritten.  A backup of the original directory
    region + original size lets us restore vanilla by rewriting the header and truncating.
  * Flat files (script.dat / talk.dat) are backed up whole and rewritten.
  * The voice archive (FAFULLFS, d5lib.fafs) gets new packs + a new index appended; its backup is the header.
"""
import json
import os
import shutil
import struct
import time

from . import crypt, fafs, nested, pac, sound
from .gamefs import GameFS, FLAT_FILES, EXE_FILE, split_path, encode_like, decode_member
from .nispack import ENTRY_SIZE, ALIGN, NisPack

KIT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# handler name -> callable(ctx: BuildContext, mod_dir: str, patch_dir: str)
PATCH_HANDLERS = {}


def register_patch_handler(name, fn, order=100):
    PATCH_HANDLERS[name] = (order, fn)


# callables(ctx) run once after every enabled mod was built (e.g. hooks applied on top of the final exe)
FINALIZERS = []

# loose files next to the game's exe (not inside an archive): virtual path "GAME/<file name>"
GAME_PREFIX = "GAME/"


def register_finalizer(fn):
    if fn not in FINALIZERS:
        FINALIZERS.append(fn)


# files a mod's runtime creates next to the exe (not written by the installer): removed with the mods
# (the auto-battle loader runs a copy of d5core.dll)
RUNTIME_FILES = ["d5core_live*.dll"]


# =============================================================================== mods
EDITS = [0]         # bumped by every write through a Mod (change_token: pages rebuild only when something changed)


def change_token(mods_dir):
    """cheap fingerprint of the mods' state: the kit's own writes (EDITS) plus, for writes made around the Mod
    class, the times of each mod's mod.json, its folders and patch folders (files added / removed) and the load
    order / packs files"""
    out = [EDITS[0]]
    try:
        names = sorted(os.listdir(mods_dir))
    except OSError:
        return tuple(out)
    for n in names:
        d = os.path.join(mods_dir, n)
        paths = [d]
        if os.path.isdir(d):
            paths += [os.path.join(d, "mod.json"), os.path.join(d, "files"), os.path.join(d, "patches")]
            try:
                paths += [e.path for e in os.scandir(os.path.join(d, "patches")) if e.is_dir()]
            except OSError:
                pass
        for p in paths:
            try:
                out.append(os.stat(p).st_mtime_ns)
            except OSError:
                out.append(None)
    # the profiles' load orders and the active profile (settings.json)
    kit = os.path.dirname(os.path.abspath(mods_dir))
    prof = os.path.join(kit, "profiles")
    try:
        extra = [os.path.join(kit, "settings.json")] + [os.path.join(prof, n, "load_order.json")
                                                        for n in sorted(os.listdir(prof))]
    except OSError:
        extra = []
    for p in extra:
        try:
            out.append(os.stat(p).st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


class Mod:
    def __init__(self, folder):
        self.folder = folder
        self.id = os.path.basename(folder)
        self.meta = {"name": self.id, "author": "", "version": "1.0", "description": ""}
        mj = os.path.join(folder, "mod.json")
        if os.path.exists(mj):
            with open(mj, encoding="utf-8") as f:
                self.meta.update(json.load(f))

    @property
    def name(self):
        return self.meta.get("name") or self.id

    @property
    def files_dir(self):
        return os.path.join(self.folder, "files")

    @property
    def patches_dir(self):
        return os.path.join(self.folder, "patches")

    def save_meta(self):
        EDITS[0] += 1
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, "mod.json"), "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2, ensure_ascii=False)

    # --- loose file overrides
    def file_path(self, vpath):
        return os.path.join(self.files_dir, *vpath.replace("\\", "/").split("/"))

    def has_file(self, vpath):
        return os.path.isfile(self.file_path(vpath))

    def read_file(self, vpath):
        with open(self.file_path(vpath), "rb") as f:
            return f.read()

    def write_file(self, vpath, data: bytes):
        EDITS[0] += 1
        p = self.file_path(vpath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def remove_file(self, vpath):
        EDITS[0] += 1
        p = self.file_path(vpath)
        if os.path.exists(p):
            os.remove(p)

    def list_files(self):
        out = []
        for root, _, files in os.walk(self.files_dir):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), self.files_dir).replace(os.sep, "/")
                out.append(rel)
        return sorted(out)

    # --- structured patches
    def patch_path(self, handler, name):
        return os.path.join(self.patches_dir, handler, name)

    def load_patch(self, handler, name, default=None):
        p = self.patch_path(handler, name)
        if not os.path.exists(p):
            return default
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def save_patch(self, handler, name, obj):
        EDITS[0] += 1
        p = self.patch_path(handler, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if obj in (None, {}, []):
            if os.path.exists(p):
                os.remove(p)
            return
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)

    def list_patches(self, handler):
        d = os.path.join(self.patches_dir, handler)
        if not os.path.isdir(d):
            return []
        return sorted(f for f in os.listdir(d) if f.endswith(".json"))


class ModManager:
    def __init__(self, kit_dir=KIT_DIR, profile=None):
        """the mods of the kit; enabled / their order: the profile `profile` (an id), else the active one"""
        from .profiles import Profiles
        self.kit_dir = kit_dir
        self.mods_dir = os.path.join(kit_dir, "mods")
        os.makedirs(self.mods_dir, exist_ok=True)
        self.profiles = Profiles(kit_dir)
        self._cache = None
        self.set_profile(profile)

    def set_profile(self, profile=None):
        """work on another profile's load order (an id; None = the active one)"""
        self.profile = (self.profiles.get(profile) if profile else None) or self.profiles.active()
        self.order_file = self.profile.order_file
        self._cache = None
        return self.profile

    def _snapshot(self):
        """({mod id: meta}, load order), read once and kept while nothing changed: pages asked for the mods once per
        list row (Textures read ~13 000 files to open).  Read again when the kit wrote anything through a Mod or the
        manager (EDITS), the mods folder or the load order file changed, or after a second (edits made outside the
        kit)."""
        try:
            key = (EDITS[0], os.stat(self.mods_dir).st_mtime_ns, self.order_file,
                   os.stat(self.order_file).st_mtime_ns if os.path.exists(self.order_file) else None)
        except OSError:
            key = None
        now = time.monotonic()
        c = self._cache
        if c is not None and key is not None and c[0] == key and now - c[1] < 1.0:
            return c[2]
        metas = {}
        for d in sorted(os.listdir(self.mods_dir)):
            full = os.path.join(self.mods_dir, d)
            if os.path.isdir(full):
                metas[d] = Mod(full).meta
        if os.path.exists(self.order_file):
            with open(self.order_file, encoding="utf-8") as f:
                order = json.load(f)
        else:
            order = []
        # each mod once (an entry of a deleted mod came back when a new mod got its folder name: installed twice)
        snap = (metas, list(dict.fromkeys(m for m in order if m in metas)))
        self._cache = (key, now, snap)
        return snap

    def _mod(self, mod_id, meta):
        m = Mod.__new__(Mod)                # a Mod of its own (callers change meta), without reading mod.json again
        m.folder = os.path.join(self.mods_dir, mod_id)
        m.id = mod_id
        m.meta = dict(meta)
        return m

    def all_mods(self):
        return [self._mod(i, meta) for i, meta in self._snapshot()[0].items()]

    def get(self, mod_id):
        full = os.path.join(self.mods_dir, mod_id)
        return Mod(full) if os.path.isdir(full) else None

    def create(self, name, author="", description=""):
        base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip().replace(" ", "_") or "mod"
        folder = os.path.join(self.mods_dir, base)
        i = 2
        while os.path.exists(folder):
            folder = os.path.join(self.mods_dir, f"{base}_{i}")
            i += 1
        m = Mod(folder)
        m.meta.update({"name": name, "author": author, "description": description})
        m.save_meta()
        os.makedirs(m.files_dir, exist_ok=True)
        order = self.load_order()
        order.append(m.id)
        self.save_load_order(order)
        return m

    def delete(self, mod_id):
        EDITS[0] += 1
        shutil.rmtree(os.path.join(self.mods_dir, mod_id), ignore_errors=True)
        self.profiles.without_mod(mod_id)                # every profile's load order

    def load_order(self):
        return list(self._snapshot()[1])

    def save_load_order(self, order):
        EDITS[0] += 1
        os.makedirs(os.path.dirname(self.order_file), exist_ok=True)
        with open(self.order_file, "w", encoding="utf-8") as f:
            json.dump(list(dict.fromkeys(order)), f, indent=2)

    def enabled_mods(self):
        metas, order = self._snapshot()
        return [self._mod(i, metas[i]) for i in order]

    def set_enabled(self, mod_id, enabled):
        order = self.load_order()
        if enabled and mod_id not in order:
            order.append(mod_id)
        if not enabled and mod_id in order:
            order.remove(mod_id)
        self.save_load_order(order)


# =============================================================================== build
class BuildContext:
    """Collects the final logical content of every changed member."""

    def __init__(self, fs: GameFS, log=print):
        self.fs = fs
        self.log = log
        self.outputs = {}  # vpath (lower-cased key) -> (vpath, logical bytes)
        self._objs = {}    # vpath key -> (vpath, parsed object, serializer or None when unchanged)

    def get(self, vpath):
        """Current logical content (already-modded if an earlier mod changed it)."""
        k = vpath.lower()
        self._flush(k)
        if k in self.outputs:
            return self.outputs[k][1]
        return self.fs.read(vpath)

    def put(self, vpath, data: bytes):
        self._objs.pop(vpath.lower(), None)
        self.outputs[vpath.lower()] = (vpath, data)

    def parsed(self, vpath, parse):
        """The current content of `vpath` parsed once and shared by every handler (big files such as script.dat take
        seconds to parse / encode).  After changing the object call changed(vpath, serialize); it is serialized
        once, when the build ends or someone reads the bytes with get()."""
        k = vpath.lower()
        if k not in self._objs:
            self._objs[k] = (vpath, parse(self.get(vpath)), None)
        return self._objs[k][1]

    def changed(self, vpath, serialize):
        k = vpath.lower()
        vp, obj, _ = self._objs[k]
        self._objs[k] = (vp, obj, serialize)

    def _flush(self, k=None):
        for key in ([k] if k is not None else list(self._objs)):
            ent = self._objs.get(key)
            if ent and ent[2] is not None:
                vp, obj, ser = ent
                self.outputs[key] = (vp, ser(obj))
                self._objs[key] = (vp, obj, None)


HANDLER_MODULES = ["d5lib.dbpatch", "d5lib.textpatch", "d5lib.scriptpatch", "d5lib.skills", "d5lib.newchars", "d5lib.outfits", "d5lib.newclasses", "d5lib.voices", "d5lib.overloads",
                   "d5lib.questpatch",
                   "d5lib.unlockpatch", "d5lib.weaponlevels", "d5lib.spellgrowth", "d5lib.standins", "d5lib.customcolors", "d5lib.fxpool",
                   "d5lib.runtime", "d5lib.autobattle",     # the runtime DLL (auto-battle: only where it exists)
                   "d5lib.grips"]                           # grips last: its finalizer edits the final sprites


def load_handlers(log=print):
    import importlib
    for m in HANDLER_MODULES:
        try:
            importlib.import_module(m)
        except ImportError as e:
            if m not in str(e):
                log(f"warning: patch handler {m} failed to load: {e}")


def missing_requirements(mods):
    """[(mod, required mod id)] for enabled mods whose "requires" (mod.json) aren't enabled before them."""
    out = []
    seen = set()
    for mod in mods:
        for req in mod.meta.get("requires") or []:
            if req not in seen:
                out.append((mod, req))
        seen.add(mod.id)
    return out


def build(fs: GameFS, mods, log=print):
    load_handlers(log)
    # the game build being patched: the game addresses the kit's exe patches and runtime name are translated to it
    from . import exemap
    try:
        t = exemap.use(exemap.translator_for(fs.read(EXE_FILE), log))
        if not t.identity:
            log(f"Game build {t.sha1[:12]} ({'the kit knows it' if t.source == 'map' else 'found automatically'})")
    except Exception as e:                       # no exe (tests): the known build
        exemap.use(exemap.Translator(exemap.KNOWN_SHA1))
        log(f"  (game build not read: {e})")
    ctx = BuildContext(fs, log)
    ctx.mod_ids = [m.id for m in mods]
    ctx.mod_folders = [m.folder for m in mods]
    for mod, req in missing_requirements(mods):
        log(f"warning: mod '{mod.name}' requires '{req}', which is not enabled (or loads after it)")
    for mod in mods:
        log(f"Building mod: {mod.name}")
        for rel in mod.list_files():
            ctx.put(rel, mod.read_file(rel))
        for name, (order, fn) in sorted(PATCH_HANDLERS.items(), key=lambda kv: kv[1][0]):
            pdir = os.path.join(mod.patches_dir, name)
            if os.path.isdir(pdir) and os.listdir(pdir):
                _tolerant(ctx, f"{mod.name}: {name}", fn, ctx, mod, pdir)
    for fn in FINALIZERS:
        _tolerant(ctx, f"{fn.__module__.split('.')[-1]}", fn, ctx)
    skipped = getattr(ctx, "skipped_features", [])
    if skipped:
        log("Not installed, as this build of the game differs where they change it: "
            + "; ".join(f"{what} ({why})" for what, why in skipped))
    ctx._flush()
    return ctx


def _tolerant(ctx, what, fn, *args):
    """run a handler / finalizer; a part that doesn't fit this build of the game (a patch site that isn't where the
    kit expects it, an address the build lacks) is left out with a note instead of stopping the whole install"""
    from . import exemap
    try:
        fn(*args)
    except exemap.Unmapped as e:
        ctx.skipped_features = getattr(ctx, "skipped_features", []) + [(what, str(e).strip("'\""))]
        ctx.log(f"  warning: {what} left out: {e}")
    except ValueError as e:
        if "unexpected exe version" not in str(e):
            raise
        ctx.skipped_features = getattr(ctx, "skipped_features", []) + [(what, str(e))]
        ctx.log(f"  warning: {what} left out: {e}")


def _group_outputs(ctx: BuildContext):
    """archive -> {member path tuple -> logical bytes}"""
    groups = {}
    for vpath, data in ctx.outputs.values():
        archive, parts = split_path(vpath)
        groups.setdefault(archive, {})[tuple(parts)] = data
    return groups


def _assemble_member(fs: GameFS, archive, member, changes):
    """Produce the final *raw* bytes of top-level member `member` given changes under it.
    changes: {subpath tuple (may be empty) -> logical bytes}"""
    vpath = f"{archive}/{member}"
    try:
        orig_raw = fs.read_raw(vpath)
    except KeyError:
        orig_raw = None
    if () in changes and len(changes) == 1:
        return encode_like(changes[()], orig_raw, member)
    # container edit: nested NISPACK or pac
    base_logical = changes.get((), None)
    if base_logical is None:
        base_logical = decode_member(orig_raw) if orig_raw is not None else None
    if base_logical is None:
        raise ValueError(f"cannot add children to missing member {vpath}")
    sub = {}
    for k, v in changes.items():
        if k:
            sub.setdefault(k[0], {})[k[1:]] = v
    if nested.is_plain_nispack(base_logical):
        items = [list(x) for x in nested.read_plain(base_logical)]
        names = {n.lower(): i for i, (n, _, _) in enumerate(items)}
        stamp = items[0][2] if items else 0
        for child, ch in sub.items():
            if list(ch.keys()) != [()]:
                raise ValueError(f"nesting too deep under {vpath}/{child}")
            i = names.get(child.lower())
            orig_child = items[i][1] if i is not None else None
            raw_child = encode_like(ch[()], orig_child)
            if i is None:
                items.append([child, raw_child, stamp])
            else:
                items[i][1] = raw_child
        # original order kept, new children appended
        new_logical = nested.write_plain([tuple(it) for it in items])
    else:
        entries = [list(x) for x in pac.read_pac(base_logical)]
        names = {n.lower(): i for i, (n, _) in enumerate(entries)}
        for child, ch in sub.items():
            data = ch[()]
            i = names.get(child.lower())
            if i is None:
                entries.append([child, data])
            else:
                entries[i][1] = data
        new_logical = pac.write_pac([tuple(e) for e in entries])
    return encode_like(new_logical, orig_raw, member)


# =============================================================================== install
def _same_file(a, b, chunk=1 << 20):
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(chunk), fb.read(chunk)
            if x != y:
                return False
            if not x:
                return True


def game_state_dir(game_dir, kit_dir=KIT_DIR):
    """the kit's state of one game folder (the backups of its original files): state/games/<folder>-<path hash>.
    One kit can look after several copies of the game (a Steam copy and another one) without mixing them up."""
    import hashlib
    import re
    g = os.path.abspath(game_dir).rstrip("\\/")
    name = re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(g) or "game").strip("_")[:40] or "game"
    h = hashlib.sha1(os.path.normcase(g).encode("utf-8")).hexdigest()[:8]
    return os.path.join(kit_dir, "state", "games", f"{name}-{h}")


class Installer:
    def __init__(self, game_dir, kit_dir=KIT_DIR, log=print):
        self.game_dir = os.path.abspath(game_dir)
        self.data_dir = os.path.join(self.game_dir, "Data")
        self.state_dir = os.path.join(kit_dir, "state")
        self.game_state = game_state_dir(self.game_dir, kit_dir)
        self.backup_dir = os.path.join(self.game_state, "backups")
        self.index_file = os.path.join(self.game_state, "backups.json")
        self.log = log
        if not os.path.exists(self.index_file):
            self._adopt_legacy()
        os.makedirs(self.backup_dir, exist_ok=True)
        about = os.path.join(self.game_state, "game.json")
        if not os.path.exists(about):
            with open(about, "w", encoding="utf-8") as f:
                json.dump({"game_dir": self.game_dir}, f, indent=2)
        self.index = self._load_index()

    def _adopt_legacy(self):
        """Kit versions before 1.2 kept one set of backups (state/backups, state/backups.json) for whichever game
        folder they were used with.  They move to the folder they were made from -- recognised by its program file:
        modded by this kit (the backups say so), or, unmodded, the very file the backup holds."""
        old_index = os.path.join(self.state_dir, "backups.json")
        old_dir = os.path.join(self.state_dir, "backups")
        if not os.path.exists(old_index):
            return
        try:
            with open(old_index, encoding="utf-8") as f:
                index = json.load(f)
        except (OSError, ValueError):
            return
        exe = os.path.join(self.game_dir, "disgaea5.exe")
        rec = index.get(EXE_FILE)
        try:
            from .gamecheck import kit_sections
            modded = bool(kit_sections(exe))
        except OSError:
            return
        if modded:
            mine = bool(rec and rec.get("modified"))
        else:
            b = os.path.join(old_dir, EXE_FILE.replace("/", "__") + ".full")
            mine = bool(rec) and os.path.exists(b) and os.path.getsize(b) == os.path.getsize(exe) and \
                _same_file(b, exe)
        if not mine:
            return
        os.makedirs(self.game_state, exist_ok=True)
        if os.path.isdir(old_dir):
            os.replace(old_dir, self.backup_dir)
        os.replace(old_index, self.index_file)
        self.log(f"  the backups of {self.game_dir} now live in "
                 f"{os.path.relpath(self.game_state, os.path.dirname(self.state_dir))}")

    # ---------------------------------------------------------------- what is installed in this game folder
    @property
    def installed_file(self):
        return os.path.join(self.game_state, "installed.json")

    def installed_info(self):
        """{"signature", "profile", "profile_name", "mods", "time"} of the last install into this folder, or {}"""
        try:
            with open(self.installed_file, encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}

    def set_installed(self, info):
        tmp = self.installed_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(info or {}, time=time.time()) if info else {}, f, indent=2)
        os.replace(tmp, self.installed_file)

    # ---------------------------------------------------------------- bookkeeping
    def _load_index(self):
        if os.path.exists(self.index_file):
            with open(self.index_file, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_index(self):
        tmp = self.index_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2)
        os.replace(tmp, self.index_file)

    def apath(self, archive):
        if archive == EXE_FILE:
            return os.path.join(self.game_dir, "disgaea5.exe")
        if archive.startswith(GAME_PREFIX):
            return os.path.join(self.game_dir, archive[len(GAME_PREFIX):])
        return os.path.join(self.data_dir, archive.replace("/", os.sep))

    def _bfile(self, archive, ext):
        return os.path.join(self.backup_dir, archive.replace("/", "__") + ext)

    def backup_resolver(self, archive):
        """For GameFS: vanilla header bytes / full vanilla copy of a currently modified archive."""
        rec = self.index.get(archive)
        if not rec:
            return None, None
        if rec["mode"] in ("append", "psfs", "fafs"):
            with open(self._bfile(archive, ".hdr"), "rb") as f:
                return f.read(), None
        return None, self._bfile(archive, ".full")

    def modified_archives(self):
        return [a for a, r in self.index.items() if r.get("modified")]

    def _ensure_backup(self, archive, mode):
        rec = self.index.get(archive)
        path = self.apath(archive)
        size = os.path.getsize(path)
        if rec and not rec.get("modified") and rec["vanilla_size"] != size:
            self.log(f"  {archive}: changed on disk since backup (game update?) - refreshing backup")
            rec = None
        if rec:
            return rec
        if mode == "fafs":
            with open(path, "rb") as f:
                header = f.read(fafs.HEADER)
            with open(self._bfile(archive, ".hdr"), "wb") as f:
                f.write(header)
        elif mode == "psfs":
            n = sound.header_length(path)
            with open(path, "rb") as f:
                header = f.read(n)
            with open(self._bfile(archive, ".hdr"), "wb") as f:
                f.write(header)
        elif mode == "append":
            with open(path, "rb") as f:
                head = crypt.decode(f.read(16))
                count = struct.unpack_from("<I", head, 12)[0]
                table = crypt.decode(f.read(count * ENTRY_SIZE))
                first = min((struct.unpack_from("<I", table, i * ENTRY_SIZE + 32)[0] for i in range(count)),
                            default=16 + count * ENTRY_SIZE)
                f.seek(0)
                header = f.read(first)
            with open(self._bfile(archive, ".hdr"), "wb") as f:
                f.write(header)
        else:
            shutil.copyfile(path, self._bfile(archive, ".full"))
        rec = {"mode": mode, "vanilla_size": size, "modified": False, "time": time.time()}
        self.index[archive] = rec
        self._save_index()
        self.log(f"  backed up {archive} ({mode})")
        return rec

    # ---------------------------------------------------------------- restore
    def restore(self, archive):
        rec = self.index.get(archive)
        if not rec or not rec.get("modified"):
            return
        path = self.apath(archive)
        if rec["mode"] == "new":           # a file the mods added: remove it
            if os.path.exists(path):
                os.remove(path)
        elif rec["mode"] in ("append", "psfs", "fafs"):
            with open(self._bfile(archive, ".hdr"), "rb") as f:
                header = f.read()
            with open(path, "r+b") as f:
                f.seek(0)
                f.write(header)
                f.truncate(rec["vanilla_size"])
        else:
            shutil.copyfile(self._bfile(archive, ".full"), path)
        rec["modified"] = False
        self._save_index()
        self.log(f"  restored {archive}")

    def ensure_unlocked(self, archives):
        """Refuse BEFORE touching anything when a game file can't be written (the game is running):
        a half-done restore/install leaves the game partly vanilla, partly modded."""
        for a in sorted(set(archives)):
            path = self.apath(a)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r+b"):
                    pass
            except PermissionError:
                raise RuntimeError(f"{a} is in use -- Disgaea 5 is probably still running.\n\n"
                                   "Close the game and try again. Nothing was changed.") from None

    def restore_all(self):
        self.ensure_unlocked(self.modified_archives())
        for a in list(self.modified_archives()):
            self.restore(a)
        import glob
        for pattern in RUNTIME_FILES:
            for path in glob.glob(os.path.join(self.game_dir, pattern)):
                try:
                    os.remove(path)
                except OSError:
                    pass                    # in use: the game is running (the loader tidies up itself)

    # ---------------------------------------------------------------- install
    def install(self, fs: GameFS, ctx: BuildContext):
        groups = _group_outputs(ctx)
        self.ensure_unlocked(list(self.modified_archives()) + list(groups))
        self.log("Restoring vanilla archives...")
        self.restore_all()
        fs.reset()
        for archive, changes in sorted(groups.items()):
            t = time.time()
            if archive.startswith(GAME_PREFIX):
                path = self.apath(archive)
                if archive not in self.index:
                    if os.path.exists(path):
                        self._ensure_backup(archive, "full")
                    else:
                        self.index[archive] = {"mode": "new", "vanilla_size": 0, "modified": False,
                                               "time": time.time()}
                data = changes.get(())
                with open(path, "wb") as f:
                    f.write(data)
            elif archive in FLAT_FILES or archive == EXE_FILE:
                self._ensure_backup(archive, "full")
                data = changes.get(())
                if data is None:
                    raise ValueError(f"{archive}: flat file needs full replacement")
                with open(self.apath(archive), "wb") as f:
                    f.write(data if archive == EXE_FILE else crypt.encode(data))
            elif fs.archive_kind(archive) == "fafs":
                rec = self._ensure_backup(archive, "fafs")
                with open(self._bfile(archive, ".hdr"), "rb") as f:
                    header = f.read()
                members = {"/".join(parts[:2]): data for parts, data in changes.items() if len(parts) == 2}
                if len(members) != len(changes):
                    raise ValueError(f"{archive}: only whole packs (voice_xx/NNNNNN.dat) can be replaced")
                fafs.append_patch(self.apath(archive), header, rec["vanilla_size"], members, self.log)
            else:
                per_member = {}
                for parts, data in changes.items():
                    if not parts:
                        raise ValueError(f"{archive}: cannot replace a whole archive")
                    per_member.setdefault(parts[0], {})[parts[1:]] = data
                raw_members = {}
                total_members = len(per_member)
                for member_number, (m, ch) in enumerate(per_member.items(), 1):
                    self.log(f"  Preparing {archive}: {member_number}/{total_members} — {m}")
                    raw_members[m] = _assemble_member(fs, archive, m, ch)
                self.log(f"  Writing {archive}: {total_members} member(s)")
                if fs.archive_kind(archive) == "psfs":
                    self._ensure_backup(archive, "psfs")
                    self._append_patch_psfs(archive, raw_members)
                else:
                    self._ensure_backup(archive, "append")
                    self._append_patch(archive, raw_members)
            self.index[archive]["modified"] = True
            self._save_index()
            self.log(f"  patched {archive}: {len(changes)} change(s) in {time.time() - t:.1f}s")
        fs.reset()
        self.log("Install complete.")

    def _append_patch(self, archive, raw_members):
        path = self.apath(archive)
        rec = self.index[archive]
        with open(self._bfile(archive, ".hdr"), "rb") as f:
            header = crypt.decode(f.read())
        unk, count = struct.unpack_from("<II", header, 8)
        entries = []
        for i in range(count):
            name, off, size, stamp = struct.unpack_from("<32sIII", header, 16 + i * ENTRY_SIZE)
            entries.append([name.split(b"\0")[0].decode("ascii", "replace"), off, size, stamp])
        by_name = {e[0].lower(): e for e in entries}
        stamp = entries[0][3] if entries else 0
        names_l = [e[0].lower() for e in entries]
        was_sorted = names_l == sorted(names_l)
        pending = []  # (entry, data)
        for name, data in raw_members.items():
            e = by_name.get(name.lower())
            if e is None:
                e = [name, 0, 0, stamp]
                if was_sorted:
                    # keep sorted archives sorted (the anime loader may rely on name order)
                    import bisect
                    k = bisect.bisect_left([x[0].lower() for x in entries], name.lower())
                    entries.insert(k, e)
                else:
                    entries.append(e)
                by_name[name.lower()] = e
            pending.append((e, data))
        # existing entries keep their original order; new names are inserted in sorted position for
        # sorted archives (Anime/Map/Skit) and appended otherwise (Database/Object)
        pending_ids = {id(e) for e, _ in pending}
        need = 16 + len(entries) * ENTRY_SIZE
        with open(path, "r+b") as f:
            # The directory grows into the data of the leading members: the vanilla bytes it will overwrite join the
            # backup header first, so a restore puts them back.  (Before, a restore left the grown directory there
            # and the next install relocated the member's damaged bytes: anm00002.lzs, found 2026-10-09.)
            hp = self._bfile(archive, ".hdr")
            hlen = os.path.getsize(hp)
            if need > hlen:
                f.seek(hlen)
                more = f.read(need - hlen)
                with open(hp, "ab") as hf:
                    hf.write(more)
                self.log(f"  {archive}: backup header extended to {need} bytes (the directory grows into member data)")
            # relocate leading members if the directory grew into their data
            in_place = sorted((e for e in entries if id(e) not in pending_ids), key=lambda e: e[1])
            for e in in_place:
                if e[1] >= need:
                    break
                f.seek(e[1])
                pending.append((e, crypt.decode(f.read(e[2]))))
                pending_ids.add(id(e))
            end = (rec["vanilla_size"] + ALIGN - 1) // ALIGN * ALIGN
            f.seek(rec["vanilla_size"])
            f.write(crypt.encode(b"\0" * (end - rec["vanilla_size"])))
            for e, data in pending:
                f.seek(end)
                f.write(crypt.encode(data))
                e[1], e[2] = end, len(data)
                end = (end + len(data) + ALIGN - 1) // ALIGN * ALIGN
                pad = end - (e[1] + len(data))
                if pad:
                    f.write(crypt.encode(b"\0" * pad))
            f.truncate(end)
            table = b"".join(struct.pack("<32sIII", e[0].encode("ascii")[:32], e[1], e[2], e[3]) for e in entries)
            f.seek(0)
            f.write(crypt.encode(b"NISPACK\0" + struct.pack("<II", unk, len(entries)) + table))


    def _append_patch_psfs(self, archive, raw_members):
        """Append-patch for PS_FS_V1 (music) and DSARC FL (sound effect) archives."""
        path = self.apath(archive)
        rec = self.index[archive]
        with open(self._bfile(archive, ".hdr"), "rb") as f:
            header = f.read()
        magic = header[:8]
        entries = sound.parse_toc(header)
        by_name = {e.name.lower(): e for e in entries}
        # the game's music archive lists its tracks sorted by name and finds them by name ("%d.ogg"): a new track
        # (Music & Sound: Add new track) goes into its place in the order, not at the end
        was_sorted = len(entries) > 1 and [e.name for e in entries] == sorted(e.name for e in entries)
        pending = []
        for name, data in raw_members.items():
            e = by_name.get(name.lower())
            if e is None:
                e = sound.Entry(name, 0, 0)
                entries.append(e)
            pending.append((e, data))
        if was_sorted:
            entries.sort(key=lambda e: e.name)
        # keep original order; new names are appended
        need = 16 + len(entries) * sound.entry_size(magic)
        pend_ids = {id(e) for e, _ in pending}
        A = sound.ALIGN
        with open(path, "r+b") as f:
            for e in sorted((e for e in entries if id(e) not in pend_ids), key=lambda e: e.offset):
                if e.offset >= need:
                    break
                f.seek(e.offset)
                pending.append((e, f.read(e.size)))
            end = (rec["vanilla_size"] + A - 1) // A * A
            for e, data in pending:
                f.seek(end)
                f.write(data)
                e.offset, e.size = end, len(data)
                end = (end + len(data) + A - 1) // A * A
            f.truncate(end)
            f.seek(0)
            f.write(sound.write_toc(entries, magic))


# =============================================================================== helpers
def open_game(game_dir):
    inst = Installer(game_dir)
    fs = GameFS(game_dir, backup_resolver=inst.backup_resolver)
    return fs, inst
