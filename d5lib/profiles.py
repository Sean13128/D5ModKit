"""Profiles: separate modpacks, like Mod Organizer's profiles for Skyrim.

A profile is a named load order: which mods are switched on, in which order.  The mods themselves are shared (a mod
switched on in two profiles is the same folder), so a profile costs nothing and switching is instant; the game gets
the active profile's mods at the next Install.

    profiles/<id>/profile.json     {"name", "description", "separate_saves", "created"}
    profiles/<id>/load_order.json  the enabled mods, first = lowest priority (what mods/load_order.json was)
    profiles/<id>/saves/           the profile's own saves (only with separate_saves)
    profiles/.shared_saves/        the saves of the profiles without their own, while another profile's are live
    settings.json "profile"        the active profile

Separate saves (optional, per profile): a modpack's saves can depend on its mods (a unit in a class or outfit only
that modpack has), so a profile can keep its own.  The game has one save folder (%APPDATA%\\Nippon Ichi Software,
Inc\\Disgaea 5 Complete\\<id>\\SaveData); the saves in it follow the modpack in the game: Install (and Play) put the
saves of the profile being installed there, Restore original game the shared ones.  Before any swap the live saves
are copied to state/save_backups/<time>; a swap only replaces the .sav files of SaveData (config.ini and the key
bindings are the player's, not the profile's).  Only while the game is closed.
"""
import json
import os
import re
import shutil
import time

KIT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SHARED = ".shared_saves"
DEFAULT_ID = "Default"


def save_root():
    """the game's save folder (one subfolder per player id, each with SaveData)"""
    return os.path.join(os.environ.get("APPDATA", ""), "Nippon Ichi Software, Inc", "Disgaea 5 Complete")


def _json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


class Profile:
    def __init__(self, folder):
        self.folder = folder
        self.id = os.path.basename(folder)
        self.meta = _json(os.path.join(folder, "profile.json"), {}) or {}

    @property
    def name(self):
        return self.meta.get("name") or self.id

    @property
    def separate_saves(self):
        return bool(self.meta.get("separate_saves"))

    @property
    def order_file(self):
        return os.path.join(self.folder, "load_order.json")

    @property
    def saves_dir(self):
        return os.path.join(self.folder, "saves")

    def load_order(self):
        return list(_json(self.order_file, []) or [])

    def save_meta(self):
        _write_json(os.path.join(self.folder, "profile.json"), self.meta)


class Profiles:
    def __init__(self, kit_dir=KIT_DIR, settings_file=None):
        self.kit_dir = kit_dir
        self.dir = os.path.join(kit_dir, "profiles")
        self.settings_file = settings_file or os.path.join(kit_dir, "settings.json")
        self.ensure()

    # ---------------------------------------------------------------- the list
    def ensure(self):
        """at least one profile: the first start after kit 1.2 turns mods/load_order.json into the profile Default"""
        if self.all():
            return
        p = Profile(os.path.join(self.dir, DEFAULT_ID))
        os.makedirs(p.folder, exist_ok=True)
        p.meta = {"name": DEFAULT_ID, "description": "", "separate_saves": False, "created": time.time()}
        p.save_meta()
        legacy = os.path.join(self.kit_dir, "mods", "load_order.json")
        order = _json(legacy, []) or []
        _write_json(p.order_file, order)
        if os.path.exists(legacy):
            os.replace(legacy, legacy + ".moved-to-profiles")

    def all(self):
        if not os.path.isdir(self.dir):
            return []
        out = [Profile(os.path.join(self.dir, d)) for d in sorted(os.listdir(self.dir))
               if not d.startswith(".") and os.path.isfile(os.path.join(self.dir, d, "profile.json"))]
        return sorted(out, key=lambda p: (p.id != DEFAULT_ID, p.name.lower()))

    def get(self, pid):
        if not pid or pid.startswith(".") or os.sep in pid or "/" in pid:
            return None
        f = os.path.join(self.dir, pid)
        return Profile(f) if os.path.isfile(os.path.join(f, "profile.json")) else None

    def active(self):
        s = _json(self.settings_file, {}) or {}
        return self.get(s.get("profile")) or self.get(DEFAULT_ID) or self.all()[0]

    def set_active(self, pid):
        if not self.get(pid):
            raise ValueError(f"no profile {pid!r}")
        s = _json(self.settings_file, {}) or {}
        s["profile"] = pid
        _write_json(self.settings_file, s)

    def _new_id(self, name):
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:40] or "Profile"
        pid, i = base, 2
        while os.path.exists(os.path.join(self.dir, pid)):
            pid, i = f"{base}_{i}", i + 1
        return pid

    def create(self, name, copy_from=None, separate_saves=False, description=""):
        """a new profile: the load order of copy_from (a Profile), else none switched on"""
        name = name.strip() or "Profile"
        if any(p.name.lower() == name.lower() for p in self.all()):
            raise ValueError(f"there is a profile called '{name}' already")
        p = Profile(os.path.join(self.dir, self._new_id(name)))
        os.makedirs(p.folder)
        p.meta = {"name": name, "description": description, "separate_saves": False, "created": time.time()}
        p.save_meta()
        _write_json(p.order_file, copy_from.load_order() if copy_from else [])
        return p

    def rename(self, pid, name):
        name = name.strip()
        if not name:
            raise ValueError("a profile needs a name")
        if any(p.name.lower() == name.lower() and p.id != pid for p in self.all()):
            raise ValueError(f"there is a profile called '{name}' already")
        p = self.get(pid)
        p.meta["name"] = name
        p.save_meta()
        return p

    def delete(self, pid, live_owner=None):
        """remove a profile (not the last one, not the active one, not the one whose saves are in the game)"""
        p = self.get(pid)
        if not p:
            return
        if len(self.all()) < 2:
            raise ValueError("the last profile can't be deleted")
        if self.active().id == pid:
            raise ValueError("switch to another profile first")
        if live_owner == pid:
            raise ValueError(f"the game's save folder holds the saves of '{p.name}' right now: install another "
                             "profile first, so they are put back into the profile")
        trash = os.path.join(self.kit_dir, "state", "deleted_profiles", f"{pid}-{time.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(os.path.dirname(trash), exist_ok=True)
        shutil.move(p.folder, trash)            # kept (with its saves): deleting a profile never loses a save
        return trash

    def without_mod(self, mod_id):
        """a deleted mod leaves every profile's load order"""
        for p in self.all():
            order = p.load_order()
            if mod_id in order:
                _write_json(p.order_file, [m for m in order if m != mod_id])

    def set_separate_saves(self, pid, on, saves=None, start="copy", installed=None, log=print):
        """switch a profile's own saves on / off (the game must be closed).
        On: its saves start as a copy of the saves in the game now (start="copy"), as none (a new game,
        start="empty") or, when it had its own saves before, as those (start="keep").  When it is the profile in
        the game (installed) a copy / new start takes the live folder at once (the shared saves keep a copy);
        otherwise its saves go into the game when it is installed.  Saves a profile had before are never
        overwritten: a new start moves them to saves.old-<time>.
        Off: its own saves stay in its folder; the shared ones come back at its next install."""
        p = self.get(pid)
        if on and not p.separate_saves and saves is not None:
            claim = installed == pid and saves.live_owner() == SHARED
            if start == "keep" and self.has_own_saves(p):
                claim = False                     # its earlier saves go in at its next install
            else:
                if os.path.isdir(p.saves_dir):
                    os.replace(p.saves_dir, p.saves_dir + time.strftime(".old-%Y%m%d_%H%M%S"))
                if start == "empty":
                    os.makedirs(p.saves_dir)
                else:
                    saves.copy_live_to(p.saves_dir)
            if claim:
                saves.copy_live_to(os.path.join(self.dir, SHARED))      # the shared saves as they are now
                if start != "copy":
                    backup = saves.backup_live()
                    saves.clear_live()
                    log(f"  saves: '{p.name}' starts without saves (the game's saves are kept as the shared ones; "
                        f"a copy in {os.path.relpath(backup, self.kit_dir)})")
                saves.claim(pid)
        p.meta["separate_saves"] = bool(on)
        p.save_meta()
        return p

    @staticmethod
    def has_own_saves(profile):
        d = profile.saves_dir
        return os.path.isdir(d) and any(f.endswith(".sav") for _, _, fs in os.walk(d) for f in fs)

    def store_of(self, profile):
        """where a profile's saves are kept while they aren't in the game"""
        return profile.saves_dir if profile and profile.separate_saves else os.path.join(self.dir, SHARED)

    def owner_id(self, profile):
        return profile.id if profile and profile.separate_saves else SHARED


class Saves:
    """the game's save folder and which profile's saves it holds (state/saves_live.json)"""

    def __init__(self, kit_dir=KIT_DIR, root=None):
        self.kit_dir = kit_dir
        self.root = root or save_root()
        self.live_file = os.path.join(kit_dir, "state", "saves_live.json")
        self.backup_dir = os.path.join(kit_dir, "state", "save_backups")

    def live_owner(self):
        return (_json(self.live_file, {}) or {}).get("owner", SHARED)

    def _set_owner(self, owner):
        _write_json(self.live_file, {"owner": owner, "time": time.time()})

    def claim(self, owner):
        """the live saves now count as owner's (no files move)"""
        self._set_owner(owner)

    def clear_live(self):
        for pl in self.players():
            live = os.path.join(self.root, pl, "SaveData")
            for f in self._sav_files(live):
                os.remove(os.path.join(live, f))

    def players(self, store=None):
        """the player folders (each with SaveData) in the live folder, or in a store"""
        base = store or self.root
        if not os.path.isdir(base):
            return []
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d, "SaveData")))

    @staticmethod
    def _sav_files(folder):
        if not os.path.isdir(folder):
            return []
        return sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))

    def copy_live_to(self, store):
        """store := the live saves (SaveData of every player folder), replacing what it held"""
        tmp = store.rstrip("\\/") + ".new"
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp)
        for pl in self.players():
            src = os.path.join(self.root, pl, "SaveData")
            dst = os.path.join(tmp, pl, "SaveData")
            os.makedirs(dst)
            for f in self._sav_files(src):
                shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
        old = store.rstrip("\\/") + ".old"
        if os.path.exists(old):
            shutil.rmtree(old)
        if os.path.exists(store):
            os.replace(store, old)
        os.replace(tmp, store)
        if os.path.exists(old):
            shutil.rmtree(old)

    def backup_live(self):
        """a copy of the live saves in state/save_backups/<time> (kept)"""
        dst = os.path.join(self.backup_dir, time.strftime("%Y%m%d_%H%M%S"))
        n = 2
        while os.path.exists(dst):
            dst = os.path.join(self.backup_dir, time.strftime("%Y%m%d_%H%M%S") + f"_{n}")
            n += 1
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        self.copy_live_to(dst)
        return dst

    def switch(self, store, owner, log=print):
        """make the live folder hold the saves of `owner` (kept in `store`): the saves there now go back to their
        own store first.  Nothing happens when they already are owner's.  -> True when saves were swapped"""
        cur = self.live_owner()
        if cur == owner:
            return False
        if not os.path.isdir(self.root):
            self._set_owner(owner)
            return False
        cur_store = self._store_path(cur)
        backup = self.backup_live()
        self.copy_live_to(cur_store)                   # the saves in the game now: back into their own store
        for pl in sorted(set(self.players()) | set(self.players(store) if os.path.isdir(store) else [])):
            live = os.path.join(self.root, pl, "SaveData")
            os.makedirs(live, exist_ok=True)
            for f in self._sav_files(live):
                os.remove(os.path.join(live, f))
            src = os.path.join(store, pl, "SaveData")
            for f in self._sav_files(src):
                shutil.copy2(os.path.join(src, f), os.path.join(live, f))
        self._set_owner(owner)
        log(f"  saves: the game now has the saves of {'the shared saves' if owner == SHARED else owner} "
            f"(the ones it had are in {os.path.relpath(cur_store, self.kit_dir)}; a copy in "
            f"{os.path.relpath(backup, self.kit_dir)})")
        return True

    def _store_path(self, owner):
        prof = os.path.join(self.kit_dir, "profiles")
        return os.path.join(prof, SHARED) if owner == SHARED else os.path.join(prof, owner, "saves")
