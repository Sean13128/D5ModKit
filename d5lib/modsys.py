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
import bisect
import json
import os
import shutil
import struct
import time

from . import crypt, fafs, nested, pac, sound, lzs
from .gamefs import GameFS, FLAT_FILES, EXE_FILE, split_path, encode_like, decode_member
from .nispack import ENTRY_SIZE, ALIGN, NisPack

KIT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# patch folder -> [(order, registration number, callable(ctx, mod, patch_dir)) ...]
#
# Several features may read their data from the same folder: a class mod ships `patches/classes/class_<family>.json`
# for the class registry and `patches/classes/mastery.json` for the class-mastery extension.  Registering a second
# handler for a folder used to replace the first one, which silently dropped the class specs whenever masteryext was
# installed (found live, EX-LIVE2).  Re-registering the *same* callable replaces its entry instead of adding one.
PATCH_HANDLERS = {}
_PATCH_SEQ = {}                 # callable -> registration number, so a handler keeps its slot when re-registered


def register_patch_handler(name, fn, order=100):
    """Register one feature's reader for a patch folder (several per folder are kept, see PATCH_HANDLERS)."""
    regs = [r for r in PATCH_HANDLERS.get(name, ()) if r[2] is not fn]
    seq = _PATCH_SEQ.setdefault(fn, len(_PATCH_SEQ))
    regs.append((order, seq, fn))
    regs.sort(key=lambda r: (r[0], r[1]))
    PATCH_HANDLERS[name] = regs


def ordered_patch_handlers():
    """Every registered handler as (order, registration number, folder, fn), sorted as one list.

    The order is global on purpose.  Sorting folder *names* instead would run `classes` (order 45) after `db`
    (order 10) simply because "classes" sorts first, and a handler that consumes another folder's output would see
    the wrong state.  The registration number breaks ties in a stable, name-independent way, and no two entries are
    ever compared as functions."""
    out = [(order, seq, folder, fn)
           for folder, regs in PATCH_HANDLERS.items()
           for order, seq, fn in regs]
    out.sort(key=lambda r: (r[0], r[1], r[2]))
    return out


# callables(ctx) run once after every enabled mod was built (e.g. hooks applied on top of the final exe)
FINALIZERS = []

# loose files next to the game's exe (not inside an archive): virtual path "GAME/<file name>"
GAME_PREFIX = "GAME/"
DIR_PROTECT = 1 << 20           # bytes of an archive's prefix the backup keeps: every byte the member
                                # directory can grow over, so a relocated member is read from vanilla bytes


def register_finalizer(fn):
    if fn not in FINALIZERS:
        FINALIZERS.append(fn)


def ordered_finalizers():
    """the finalizers in HANDLER_MODULES order, whatever imported their module first.  The order matters: the
    outfit finalizer starts from the original exe (every exe patch made before it would be lost), the runtime's and
    the grips' come last.  (A page importing d5lib.enemyitems at start-up registered it before the outfits.)"""
    rank = {m: i for i, m in enumerate(HANDLER_MODULES)}
    return sorted(FINALIZERS, key=lambda fn: (rank.get(getattr(fn, "__module__", ""), len(HANDLER_MODULES)),
                                              FINALIZERS.index(fn)))


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
        own = self.profile.id if self.profile.isolated else None
        separate = self.profiles.isolated_ids()
        for d in sorted(os.listdir(self.mods_dir)):
            full = os.path.join(self.mods_dir, d)
            if os.path.isdir(full):
                meta = Mod(full).meta
                owner = meta.get("profile")
                # a separate profile: its own mods only; the others: the shared ones (no owner, or its profile is
                # gone or shares again)
                if (owner == own) if own else (owner not in separate):
                    metas[d] = meta
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

    def visible(self, mod_id):
        """the mod is one of this profile's (a separate profile sees only its own)"""
        return bool(mod_id) and mod_id in self._snapshot()[0]

    def adopt(self, mod):
        """a mod made / brought in now belongs to this profile (a separate one), or is shared"""
        if self.profile.isolated:
            mod.meta["profile"] = self.profile.id
        else:
            mod.meta.pop("profile", None)
        mod.save_meta()
        return mod

    def other_profiles_mods(self):
        """[(Profile, [Mod])]: the mods the other profiles see that this one doesn't (Import from another profile)"""
        out = []
        mine = set(self._snapshot()[0])
        for p in self.profiles.all():
            if p.id == self.profile.id:
                continue
            o = ModManager.__new__(ModManager)
            o.kit_dir, o.mods_dir, o.profiles, o._cache = self.kit_dir, self.mods_dir, self.profiles, None
            o.profile, o.order_file = p, p.order_file
            mods = [m for m in o.all_mods() if m.id not in mine]
            if mods:
                out.append((p, sorted(mods, key=lambda m: m.name.lower())))
        return out

    def create(self, name, author="", description=""):
        base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip().replace(" ", "_") or "mod"
        folder = os.path.join(self.mods_dir, base)
        i = 2
        while os.path.exists(folder):
            folder = os.path.join(self.mods_dir, f"{base}_{i}")
            i += 1
        m = Mod(folder)
        m.meta.update({"name": name, "author": author, "description": description})
        if self.profile.isolated:
            m.meta["profile"] = self.profile.id
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


HANDLER_MODULES = ["d5lib.dbpatch", "d5lib.textpatch", "d5lib.scriptpatch", "d5lib.skills", "d5lib.newchars", "d5lib.outfits", "d5lib.newclasses", "d5lib.masteryext", "d5lib.voices", "d5lib.overloads", "d5lib.evility",
                   "d5lib.questpatch", "d5lib.wishrecruit",   # recruit wishes (.d5wr): after the quest recruit hook
                   "d5lib.subclasstab",    # sub-class from the Class tab (.d5sb): reads newclasses' Class tab buffer
                   "d5lib.subclassguard",  # Assembly sub-class panel guard (.d5sv): every build, the save outlives mods
                   "d5lib.unlockpatch", "d5lib.weaponlevels", "d5lib.spellgrowth", "d5lib.enemyitems", "d5lib.musiclist", "d5lib.standins", "d5lib.customcolors", "d5lib.fxpool",
                   "d5lib.learned",        # learned-evility capacity (.d5lc): after dbpatch's final Skill.dat and .d5el
                   "d5lib.runtime", "d5lib.autobattle",     # the runtime DLL (auto-battle: only where it exists)
                   "d5lib.exebytes",       # mods' own exe bytes after every kit exe patch: the mod is the one refused on an overlap
                   "d5lib.grips"]                           # grips last: its finalizer edits the final sprites


def mod_file_allowed(rel):
    """may a mod's own file go into the game?  Only files inside the game's data archives: the exe ("EXE/") and
    loose files next to it ("GAME/": DLLs, the runtime's settings) are written by the kit's own finalizers alone, so
    a shared mod can't bring files into the exe.  (A patches/exe mod can still change the game's code bytes: those
    are same-length patches checked against their originals, logged at install and import, and listed.)"""
    top = rel.replace("\\", "/").lstrip("/").split("/", 1)[0].upper()
    return top not in ("EXE", "GAME") and ".." not in rel.replace("\\", "/").split("/")


def load_handlers(log=print):
    import importlib
    for m in HANDLER_MODULES:
        try:
            importlib.import_module(m)
        except ImportError as e:
            if m not in str(e):
                log(f"warning: patch handler {m} failed to load: {e}")


def missing_requirements(mods):
    """[(mod, required mod id)] for enabled mods whose "requires" (mod.json) aren't enabled before them, or whose
    "needs" aren't enabled at all.  "needs" is the order-free form: the mod uses rows another mod adds (e.g. a
    generated skill scene spawning another pack's character, SPECBULK2), so only presence matters, and two packs may
    need each other."""
    out = []
    seen = set()
    enabled = {mod.id for mod in mods}
    for mod in mods:
        for req in mod.meta.get("requires") or []:
            if req not in seen:
                out.append((mod, req))
        for req in mod.meta.get("needs") or []:
            if req not in enabled and (mod, req) not in out:
                out.append((mod, req))
        seen.add(mod.id)
    return out


def build(fs: GameFS, mods, log=print):
    """build the enabled mods.  A mod with game-program patches (patches/exe) must be approved, and one whose patches
    can't apply is left out whole (its files and patches too): the build runs again without it, saying why."""
    from . import exebytes
    keep, notes, snaps = [], [], {}
    for m in mods:
        snap, why = exebytes.assess(m)      # one read: the build applies these exact bytes and settings
        if why:
            notes.append((f"mod {m.name} ({m.id})", why))
            log(f"warning: mod '{m.name}' left out whole: {why}")
        else:
            keep.append(m)
            if snap is not None:
                snaps[m.id] = snap
    while True:
        ctx = _build(fs, keep, log, notes, exe_snapshots=snaps)
        drop = getattr(ctx, "drop_mods", None)
        if not drop:
            return ctx
        notes = notes + [(what, f"left out whole: {why}") for what, why in drop.values()]
        keep = [m for m in keep if m.id not in drop]
        log("Building again without " + ", ".join(sorted(drop)) + " (its game-program patches can't apply)")


def _build(fs: GameFS, mods, log, notes=(), exe_snapshots=None):
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
    ctx.exe_snapshots = exe_snapshots if exe_snapshots is not None else {}
    if notes:
        ctx.skipped_features = list(notes)
    from . import overlord_compat
    exemap.reset_ledger(reserved=True)      # the exe patch sites claimed in this build (d5lib.exemap.LEDGER)
    overlord_compat.configure(ctx)          # who owns a contested site: one decision per build
    for mod, req in missing_requirements(mods):
        log(f"warning: mod '{mod.name}' requires '{req}', which is not enabled (or loads after it)"
            + ("" if req in (mod.meta.get("requires") or []) else
               ": its generated scenes would spawn characters from a pack that is off"))
    for mod in mods:
        log(f"Building mod: {mod.name}")
        for rel in mod.list_files():
            if not mod_file_allowed(rel):
                log(f"warning: mod '{mod.name}': {rel} left out (a mod can't put the game's program or files next to "
                    "it: those are made by the kit itself)")
                continue
            ctx.put(rel, mod.read_file(rel))
        for order, seq, folder, fn in ordered_patch_handlers():
            pdir = os.path.join(mod.patches_dir, folder)
            if os.path.isdir(pdir) and os.listdir(pdir):
                with exemap.owner(f"{mod.id}:{folder}"):
                    _tolerant(ctx, f"{mod.name}: {folder}", fn, ctx, mod, pdir)
    for fn in ordered_finalizers():
        with exemap.owner(fn.__module__.split('.')[-1]):
            _tolerant(ctx, f"{fn.__module__.split('.')[-1]}", fn, ctx)
    ctx.exe_sites = list(exemap.LEDGER) + [dict(e, reserved=True) for e in exemap.RESERVED]   # Installer.install writes it to <game state>/exe_sites.json
    claimed = list(exemap.LEDGER)
    exemap.reset_ledger(reserved=True)      # a later direct call of a patch builder starts clean, not against this build
    if claimed:
        log(f"exe sites: {len(claimed)} claimed by {len({e['owner'] for e in claimed})} features")
    overlord_compat.report(ctx)
    if getattr(ctx, "drop_mods", None):
        return ctx                          # build() builds again without these mods
    skipped = getattr(ctx, "skipped_features", [])
    if skipped:
        log("Not installed (the game build differs there, or another mod or kit feature already patches those bytes): "
            + "; ".join(f"{what} ({why})" for what, why in skipped))
    ctx._flush()
    return ctx


def _tolerant(ctx, what, fn, *args):
    """run a handler / finalizer; a part that doesn't fit this build of the game (a patch site that isn't where the
    kit expects it, an address the build lacks) is left out with a note instead of stopping the whole install"""
    from . import exemap
    try:
        fn(*args)
    except (exemap.Unmapped, exemap.SiteClash) as e:
        _left_out(ctx, what, str(e).strip("'\""), e, exemap)
    except ValueError as e:
        if "unexpected exe version" not in str(e):
            raise
        _left_out(ctx, what, str(e), e, exemap)


def _left_out(ctx, what, why, e, exemap):
    """a feature left out whole leaves none of its exe site claims behind"""
    exemap.release(exemap._owner[0])
    ctx.skipped_features = getattr(ctx, "skipped_features", []) + [(what, why)]
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
# bumped when the installer writes the same output differently: archives written by an older kit are rewritten
INSTALL_FORMAT = b"1"


def _fingerprint(changes):
    """sha1 of one archive's changes ({member path tuple: logical bytes}): equal = the install would write the same"""
    import hashlib
    h = hashlib.sha1(INSTALL_FORMAT)
    for parts in sorted(changes):
        data = changes[parts]
        h.update("/".join(parts).lower().encode("utf-8") + b"\0" + len(data).to_bytes(8, "little"))
        h.update(data)
    return h.hexdigest()


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
    def __init__(self, game_dir, kit_dir=KIT_DIR, log=print, vanilla_dir=None):
        self.game_dir = os.path.abspath(game_dir)
        self.data_dir = os.path.join(self.game_dir, "Data")
        # A pristine copy of the game (same version) that a stale backup prefix can be rebuilt from.
        # Optional: without it a stale prefix is reported, not guessed at.  D5MODKIT_VANILLA_GAME also works.
        self.vanilla_dir = vanilla_dir or os.environ.get("D5MODKIT_VANILLA_GAME") or None
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
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.index_file)

    # ---------------------------------------------------------------- interrupted install / restore
    def _begin(self, archive, op):
        """Record, durably, that `archive` is about to be changed.  If the process dies before the change is
        finished the record is still in the index, and `recover()` puts the file back from its verified backup
        instead of trusting a `modified` flag that may never have been written."""
        rec = self.index.setdefault(archive, {"mode": "new", "vanilla_size": 0, "modified": False,
                                              "time": time.time()})
        rec["intent"] = {"op": op, "time": time.time()}
        self._save_index()

    def _clear(self, archive):
        rec = self.index.get(archive)
        if rec and "intent" in rec:
            rec.pop("intent", None)
            self._save_index()

    def _backup_ok(self, archive, rec):
        """a backup this kit can restore from, with the size it recorded"""
        if rec.get("mode") == "new":
            return True
        ext = ".full" if rec.get("mode") in ("full", None) else ".hdr"
        b = self._bfile(archive, ext)
        return os.path.exists(b) and (ext == ".hdr" or os.path.getsize(b) == rec.get("vanilla_size"))

    def recover(self):
        """Finish or undo whatever an interrupted run left half-done.  Called on open and before every install or
        restore, so a crashed run can never leave a file that the index believes is still vanilla."""
        pending = [a for a, r in self.index.items() if r.get("intent")]
        for archive in sorted(pending):
            rec = self.index[archive]
            op = (rec.get("intent") or {}).get("op", "?")
            if not self._backup_ok(archive, rec):
                self.log(f"warning: {archive} was interrupted during '{op}' and has no usable backup; "
                         f"re-install from a clean copy of the game")
                rec.pop("intent", None)
                self._save_index()
                continue
            self.log(f"  {archive}: undoing an interrupted '{op}' from the backup")
            rec["modified"] = True                   # force restore() to run
            rec.pop("intent", None)
            self._save_index()
            self.restore(archive)
        return pending

    def _tempfile_for(self, path):
        return path + ".d5-new"

    def _atomic_write(self, path, data):
        tmp = self._tempfile_for(path)
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _staged_copy(self, path):
        """a working copy next to `path` that a multi-step patcher can change; swapped in only when it finished"""
        tmp = self._tempfile_for(path)
        shutil.copyfile(path, tmp)
        return tmp

    def apath(self, archive):
        if archive == EXE_FILE:
            return os.path.join(self.game_dir, "disgaea5.exe")
        if archive.startswith(GAME_PREFIX):
            return os.path.join(self.game_dir, archive[len(GAME_PREFIX):])
        return os.path.join(self.data_dir, archive.replace("/", os.sep))

    def _bfile(self, archive, ext):
        return os.path.join(self.backup_dir, archive.replace("/", "__") + ext)

    # ---------------------------------------------------------------- stale backup prefix
    def vanilla_path(self, archive):
        """the same archive inside self.vanilla_dir, or None when no pristine copy is configured"""
        if not self.vanilla_dir:
            return None
        if archive == EXE_FILE:
            return os.path.join(self.vanilla_dir, "disgaea5.exe")
        if archive.startswith(GAME_PREFIX):
            return os.path.join(self.vanilla_dir, archive[len(GAME_PREFIX):])
        return os.path.join(self.vanilla_dir, "Data", archive.replace("/", os.sep))

    def stale_prefix(self, archive):
        """(True, hlen) when this archive's backup prefix was written by a kit older than the 1 MiB
        protection (PT1029 2026-10-29): the old backup saved only the directory size of its day, so the
        next install cannot prove the leading members' bytes.  LIVE11 had to clear this by hand
        (ANM_HI_JP.dat, 167,348 B, pre-PT1029) before TEST16 would install."""
        rec = self.index.get(archive)
        if not rec or rec.get("mode") != "append":
            return False, 0
        hp = self._bfile(archive, ".hdr")
        if not os.path.exists(hp):
            return False, 0
        hlen = os.path.getsize(hp)
        return hlen < DIR_PROTECT, hlen

    def rebuild_backup_prefix(self, archive, log=None):
        """Grow a stale prefix from the pristine copy of the same archive.  Returns the new length or None.

        Only when the current prefix is a byte-exact prefix of the vanilla file: that proves it is this
        archive, unmodified, so the extra bytes are vanilla bytes and not something a previous install
        wrote.  Anything else is left alone and reported -- growing it from the live file is exactly what
        corrupted anm00010.lzs.  The old prefix is kept next to the new one."""
        stale, hlen = self.stale_prefix(archive)
        vp = self.vanilla_path(archive)
        if not stale or not vp or not os.path.exists(vp):
            return None
        hp = self._bfile(archive, ".hdr")
        with open(hp, "rb") as f:
            old = f.read()
        size = os.path.getsize(vp)
        live = self.apath(archive)
        need = DIR_PROTECT
        try:
            with open(live, "rb") as f:
                head = crypt.decode(f.read(16))
            if head[:8] == b"NISPACK\0":
                need = max(need, 16 + struct.unpack_from("<I", head, 12)[0] * ENTRY_SIZE)
        except OSError:
            pass
        protect = min(need, size)
        with open(vp, "rb") as f:
            fresh = f.read(protect)
        if crypt.decode(fresh[:16])[:8] != b"NISPACK\0" or fresh[:hlen] != old:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        keep = f"{hp}.stale-{stamp}"
        shutil.copyfile(hp, keep)
        tmp = hp + ".rebuild"
        with open(tmp, "wb") as f:
            f.write(fresh)
        os.replace(tmp, hp)
        (log or self.log)(f"  {archive}: stale backup prefix rebuilt from the vanilla copy "
                          f"({hlen} -> {protect} bytes; the old one is {os.path.basename(keep)})")
        return protect

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

    def game_stamp(self):
        """sizes and times of the game's archives, its exe and every file the last install wrote: equal to the one
        stored at the install = nothing (Steam, the kit, a restore) has touched the game since"""
        import hashlib
        paths = {os.path.join(self.game_dir, "disgaea5.exe")}
        paths.update(self.apath(a) for a in self.modified_archives())
        for root, dirs, files in os.walk(self.data_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            paths.update(os.path.join(root, fn) for fn in files if not fn.startswith("."))
        h = hashlib.sha1()
        for p in sorted(paths):
            try:
                st = os.stat(p)
                h.update(f"{os.path.relpath(p, self.game_dir)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
            except OSError:
                h.update(f"{p}|missing\n".encode())
        return h.hexdigest()

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
                # The backup prefix is what restore() writes back and what a relocated "leading member" is
                # read from, so it must cover every byte the member directory can ever grow over - not just
                # up to the first member's offset today.  Growing it lazily (the old behaviour) let the
                # directory bytes of one install be saved as if they were a member's art, and the next
                # install appended that garbage as the member (anm00002.lzs 2026-10-09, anm00010.lzs 2026-10-29:
                # Killia's default body no longer decoded).
                protect = min(max(first, DIR_PROTECT), size)
                f.seek(0)
                header = f.read(protect)
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
        self._begin(archive, "restore")
        if rec["mode"] == "new":           # a file the mods added: remove it
            if os.path.exists(path):
                os.remove(path)
        elif rec["mode"] in ("append", "psfs", "fafs"):
            with open(self._bfile(archive, ".hdr"), "rb") as f:
                header = f.read()
            with open(path, "r+b") as f:    # header + truncate: idempotent, so recover() can simply redo it
                f.seek(0)
                f.write(header)
                f.truncate(rec["vanilla_size"])
        else:
            tmp = self._tempfile_for(path)
            shutil.copyfile(self._bfile(archive, ".full"), tmp)
            os.replace(tmp, path)           # never a half-written program file
        rec["modified"] = False
        rec.pop("intent", None)
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
        self.recover()
        self.ensure_unlocked(self.modified_archives())
        for a in list(self.modified_archives()):
            self.restore(a)
        self._remove_runtime_files()
        try:
            os.remove(os.path.join(self.game_state, "exe_sites.json"))      # vanilla again: no sites to list
        except OSError:
            pass

    def _remove_runtime_files(self):
        import glob
        for pattern in RUNTIME_FILES:
            for path in glob.glob(os.path.join(self.game_dir, pattern)):
                try:
                    os.remove(path)
                except OSError:
                    pass                    # in use: the game is running (the loader tidies up itself)

    # ---------------------------------------------------------------- install
    def _unchanged(self, archive, fp):
        """the archive already holds exactly this output (written by the last install, untouched since)"""
        rec = self.index.get(archive)
        if not rec or not rec.get("modified") or rec.get("output") != fp:
            return False
        try:
            st = os.stat(self.apath(archive))
        except OSError:
            return False
        return [st.st_size, st.st_mtime_ns] == rec.get("written")

    def install(self, fs: GameFS, ctx: BuildContext):
        groups = _group_outputs(ctx)
        self.recover()
        self.ensure_unlocked(list(self.modified_archives()) + list(groups))
        self.log("Restoring vanilla archives...")
        self.restore_all()
        fs.reset()
        done = []
        try:
            for archive, changes in sorted(groups.items()):
                self._install_one(fs, archive, changes)
                done.append(archive)
        except BaseException:
            # put back everything this run already changed, so a failed install leaves vanilla, not a mix
            self.log("Install failed -- rolling back the archives this run had already written")
            for a in reversed(done):
                rec = self.index.get(a)
                if rec:
                    rec["modified"] = True
                    self.restore(a)
            raise
        fs.reset()
        sites = getattr(ctx, "exe_sites", None)
        if sites is not None:
            os.makedirs(self.game_state, exist_ok=True)
            with open(os.path.join(self.game_state, "exe_sites.json"), "w") as f:
                json.dump(sites, f, indent=1)
        self.log("Install complete.")

    def _install_one(self, fs: GameFS, archive, changes):
        t = time.time()
        path = self.apath(archive)
        if archive.startswith(GAME_PREFIX):
            if archive not in self.index:
                if os.path.exists(path):
                    self._ensure_backup(archive, "full")
                else:
                    self.index[archive] = {"mode": "new", "vanilla_size": 0, "modified": False,
                                           "time": time.time()}
            self._begin(archive, "install")
            self._atomic_write(path, changes.get(()))
        elif archive in FLAT_FILES or archive == EXE_FILE:
            self._ensure_backup(archive, "full")
            data = changes.get(())
            if data is None:
                raise ValueError(f"{archive}: flat file needs full replacement")
            self._begin(archive, "install")
            self._atomic_write(path, data if archive == EXE_FILE else crypt.encode(data))
        elif fs.archive_kind(archive) == "fafs":
            rec = self._ensure_backup(archive, "fafs")
            with open(self._bfile(archive, ".hdr"), "rb") as f:
                header = f.read()
            members = {"/".join(parts[:2]): data for parts, data in changes.items() if len(parts) == 2}
            if len(members) != len(changes):
                raise ValueError(f"{archive}: only whole packs (voice_xx/NNNNNN.dat) can be replaced")
            self._begin(archive, "install")
            self._swap_in(archive, path, lambda p: fafs.append_patch(p, header, rec["vanilla_size"], members,
                                                                     self.log))
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
                self._begin(archive, "install")
                self._swap_in(archive, path, lambda p: self._append_patch_psfs(archive, raw_members, p))
            else:
                self._ensure_backup(archive, "append")
                self._begin(archive, "install")
                self._swap_in(archive, path, lambda p: self._append_patch(archive, raw_members, p))
        self.index[archive]["modified"] = True
        self.index[archive].pop("intent", None)
        self._save_index()
        self.log(f"  patched {archive}: {len(changes)} change(s) in {time.time() - t:.1f}s")

    def _swap_in(self, archive, path, patch_fn):
        """run a multi-step patcher on a working copy and replace the real file only when it returns.  A patcher that
        fails or is interrupted therefore cannot leave a half-written archive behind."""
        tmp = self._staged_copy(path)
        try:
            patch_fn(tmp)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _append_patch(self, archive, raw_members, path=None):
        path = path or self.apath(archive)
        rec = self.index[archive]
        # A prefix written by a kit older than the 1 MiB protection is too short to prove the leading
        # members' bytes.  Rebuild it from a pristine copy when the kit has one (the bytes must match
        # exactly); otherwise the refusal below names it.  LIVE11 had to do this by hand for
        # Anime/ANM_HI_JP.dat (167,348 B) before TEST16 would install.
        if self.stale_prefix(archive)[0]:
            self.rebuild_backup_prefix(archive)
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
                    k = bisect.bisect_left(names_l, name.lower())
                    names_l.insert(k, name.lower())
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
            # The member directory grows into the data of the leading members (their offsets are lower than
            # `need`).  Their bytes are not read from this file: the prefix [0, hlen) comes from the backup,
            # which holds the vanilla bytes, and only the part past the prefix is read here (the directory
            # never reaches past hlen, so that part is untouched).  The old code grew the prefix lazily from
            # this file, which saved one install's directory bytes as if they were member art; the next
            # install appended them as the member and the member stopped decoding (anm00002.lzs 2026-10-09,
            # anm00010.lzs 2026-10-29 -- Killia's default body).
            hp = self._bfile(archive, ".hdr")
            hlen = os.path.getsize(hp)
            if need > hlen:
                stale, _ = self.stale_prefix(archive)
                why = ("this game's backup prefix is STALE: it was written by a kit older than the 1 MiB "
                       "protection, so it cannot prove the leading members' bytes"
                       if stale else
                       "the backup prefix is shorter than the member directory")
                raise RuntimeError(
                    f"{archive}: the member directory needs {need} bytes but this game's backup prefix holds "
                    f"{hlen} ({why}).  Refusing to grow it from the live file: that is what corrupted a "
                    "member's art before.  Two ways out, both without clearing anything by hand: point the "
                    "kit at a pristine copy of the game (D5MODKIT_VANILLA_GAME=/path/to/vanilla, or "
                    "Installer(vanilla_dir=...)) and install again -- the prefix is then rebuilt from it and "
                    "the old one is kept as <backup>.hdr.stale-<date>; or restore the game's files "
                    "(Steam > Verify integrity of game files) and install again, so the kit re-backs it up "
                    "with the current protection.")
            # relocate leading members if the directory grew into their data
            in_place = sorted((e for e in entries if id(e) not in pending_ids), key=lambda e: e[1])
            with open(hp, "rb") as hf:
                prefix = hf.read(hlen)
            for e in in_place:
                if e[1] >= need:
                    break
                covered = max(0, min(e[2], hlen - e[1]))
                data = crypt.decode(prefix[e[1]:e[1] + covered])
                if covered < e[2]:
                    f.seek(e[1] + covered)
                    data += crypt.decode(f.read(e[2] - covered))
                if e[0].lower().endswith(".lzs"):
                    try:
                        lzs.decompress(data)
                    except Exception as exc:
                        raise RuntimeError(
                            f"{archive}: relocated member {e[0]} does not decode ({exc}).  Its art is already "
                            "damaged on disk; install again after restoring the game's files (Steam › Verify "
                            "integrity of game files).  Nothing was written.") from exc
                pending.append((e, data))
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


    def _append_patch_psfs(self, archive, raw_members, path=None):
        """Append-patch for PS_FS_V1 (music) and DSARC FL (sound effect) archives."""
        path = path or self.apath(archive)
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
