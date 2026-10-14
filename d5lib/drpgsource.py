"""Disgaea RPG sprites for the editors: where they are, which units there are and what each one has.

A DRPG unit is drawn from four sprite sheets (packed atlases of all its poses): the battle sheets seen from the front
and the back, and the idle ("wait") sheets from the front and the back.  A face picture and a cut-in portrait are
optional.  They are looked for in the folder chosen in the editor (settings.json "drpg_folder"), then in
D5ModKit/DRPG Assets (Updated) and D5ModKit/DRPG Assets, in either of the two layouts DRPG rips come in:

    Characters/Sprites/front/front<unit>.png      Sprites/Standard/BattleFront/front<unit>.png
    Characters/Sprites/back/back<unit>.png        Sprites/Standard/BattleBack/back<unit>.png
    Characters/Sprites/wait_front/front<unit>.png Sprites/Standard/WaitFront/front<unit>.png
    Characters/Sprites/wait_back/back<unit>.png   Sprites/Standard/WaitBack/back<unit>.png
    Characters/Icons/<unit>.png  (face)           Chara Icons/<unit>.png
    Characters/Cut-Ins/<unit>.png (cut-in)        Cutins/<unit>.png

Sheets from anywhere else (four files picked by hand) are copied to state/drpg_custom/<unit>/ under a unit number
of their own (900001 and up) and used like any other unit.  "Units IDs.txt" in the folder names the units.
"""
import json
import os
import re
import shutil
from contextlib import contextmanager

from . import drpg
from .modsys import KIT_DIR

SETTING = "drpg_folder"
CUSTOM_DIR = os.path.join(KIT_DIR, "state", "drpg_custom")
CUSTOM_FIRST = 900001
DEFAULT_ROOTS = [os.path.join(KIT_DIR, "DRPG Assets (Updated)"), os.path.join(KIT_DIR, "DRPG Assets")]

# the four sheets every unit needs: key, label, what it is, file name
SHEETS = [
    ("front", "Battle sprites, front", "every battle pose seen from the front (walk, attacks, damage …)", "front{uid}.png"),
    ("back", "Battle sprites, back", "the same poses seen from the back", "back{uid}.png"),
    ("wait_front", "Idle, front", "the standing / breathing loop seen from the front", "front{uid}.png"),
    ("wait_back", "Idle, back", "the standing loop seen from the back", "back{uid}.png"),
]
# the battle sheets must be packed in a known slot layout (which drawing is which pose); idle frames are found by
# their shape, so the idle sheets only need to be there
LAYOUT_REQUIRED = ("front", "back")
EXTRAS = [("icon", "Face picture", "the square face (status panel, lists, battle)"),
          ("cutin", "Cut-in portrait", "the tall picture of special attacks")]
LAYOUTS = [  # (sprite folder relative to a root, {sheet: subfolder}, face folders, cut-in folders)
    (("Characters", "Sprites"), {"front": "front", "back": "back", "wait_front": "wait_front", "wait_back": "wait_back"}),
    (("Sprites", "Standard"), {"front": "BattleFront", "back": "BattleBack", "wait_front": "WaitFront",
                               "wait_back": "WaitBack"}),
]
_FILE = re.compile(r"^(front|back)(\d+)\.png$", re.I)
GROUPS = {"UNIQUES (Humans)": "unique", "UNIQUES (Monsters)": "unique monster",
          "GENERICS (Humans)": "generic", "GENERICS (Monsters)": "generic monster"}


# ------------------------------------------------------------------------------------------------ the folders
def chosen_folder():
    from .paths import kit_setting
    f = kit_setting(SETTING)
    return f if f and os.path.isdir(f) else None


def custom_roots():
    if not os.path.isdir(CUSTOM_DIR):
        return []
    return [os.path.join(CUSTOM_DIR, d) for d in sorted(os.listdir(CUSTOM_DIR)) if d.isdigit()]


def folders(chosen=None):
    """where units are looked for, first match wins: the chosen folder, the kit's own DRPG folders, the hand-picked
    units"""
    out = []
    for f in [chosen or chosen_folder()] + DEFAULT_ROOTS + custom_roots():
        if f and os.path.isdir(f) and os.path.normcase(os.path.abspath(f)) not in \
                [os.path.normcase(os.path.abspath(o)) for o in out]:
            out.append(f)
    return out


def apply(chosen=None):
    """make the DRPG builders (d5lib.drpg, drpgmap, newclasses ...) look in folders()"""
    drpg.ROOTS[:] = folders(chosen) or list(DEFAULT_ROOTS)
    return drpg.ROOTS


@contextmanager
def using(chosen=None):
    old = list(drpg.ROOTS)
    apply(chosen)
    try:
        yield drpg.ROOTS
    finally:
        drpg.ROOTS[:] = old


def looks_like_drpg_root(path):
    """does `path` hold DRPG sprites in one of the known layouts (or is it one level above such a folder)?
    -> the root to use, or None"""
    for cand in (path, os.path.join(path, "DRPG Assets (Updated)"), os.path.join(path, "DRPG Assets")):
        for sub, dirs in LAYOUTS:
            if os.path.isdir(os.path.join(cand, *sub, dirs["front"])):
                return cand
    return None


# ------------------------------------------------------------------------------------------------ the units
class Unit:
    def __init__(self, uid, root, layout):
        self.uid = uid
        self.root = root
        self.layout = layout          # index into LAYOUTS
        self.name = ""
        self.group = ""               # unique / generic / unique monster / generic monster / "" (unknown)
        self.custom = root.startswith(CUSTOM_DIR)

    @property
    def monster(self):
        return "monster" in self.group

    def sheet_paths(self):
        sub, dirs = LAYOUTS[self.layout]
        base = os.path.join(self.root, *sub)
        return {k: os.path.join(base, dirs[k], fname.format(uid=self.uid)) for k, _, _, fname in SHEETS}

    def sheets(self):
        """{key: path or None}"""
        return {k: (p if os.path.exists(p) else None) for k, p in self.sheet_paths().items()}

    def extras(self):
        return drpg.unit_extras(self.uid, roots=[self.root])

    def missing(self):
        return [k for k, p in self.sheets().items() if not p]

    def label(self):
        return f"{self.uid}  {self.name}" if self.name else f"Unit {self.uid}"


# 'Units IDs.txt' names three units one place off: these are what their sprites show
NAME_FIXES = {405: ("Netherworld President Axel", "Hero Rozalin"),
              406: ("Yomawari Ao", "Netherworld President Axel"),
              407: ("Hero Rozalin", "Yomawari Ao")}


def unit_names(root):
    """{uid: (name, group)} from the folder's 'Units IDs.txt' (NAME_FIXES applied)"""
    out = {}
    for p in (os.path.join(root, "Units IDs.txt"), os.path.join(os.path.dirname(root), "Units IDs.txt")):
        if not os.path.exists(p):
            continue
        group = ""
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                m = re.match(r"^-+\s*(.+?)\s*-+$", s)
                if m:
                    group = GROUPS.get(m.group(1), group)
                    continue
                m = re.match(r"^(\d+)\s+(.+)$", s)
                if m:
                    out.setdefault(int(m.group(1)), (m.group(2).strip(), group))
        break
    for uid, (listed, real) in NAME_FIXES.items():
        if uid in out and out[uid][0] == listed:
            out[uid] = (real, out[uid][1])
    return out


def scan(chosen=None):
    """{uid: Unit} of every unit with at least its front battle sheet in folders()"""
    units = {}
    for root in folders(chosen):
        names = unit_names(root)
        for li, (sub, dirs) in enumerate(LAYOUTS):
            d = os.path.join(root, *sub, dirs["front"])
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                m = _FILE.match(f)
                if not m or m.group(1).lower() != "front":
                    continue
                uid = int(m.group(2))
                if uid in units:
                    continue
                u = Unit(uid, root, li)
                u.name, u.group = names.get(uid, ("", ""))
                if u.custom:
                    u.name, u.group = _custom_meta(root)
                units[uid] = u
    return units


def layouts(unit):
    """{sheet key: recognised layout name or None} -- None: the sheet isn't packed like a DRPG atlas"""
    out = {}
    for k, p in unit.sheets().items():
        out[k] = sheet_layout(p, k) if p else None
    return out


def sheet_layout(path, key):
    try:
        name, _, _ = drpg.fit_layout(drpg.atlas_pieces(path), key)
    except Exception:
        return None
    return name


def preview(unit, key="wait_front"):
    """a PIL picture of the unit: its first idle frame (or face)"""
    p = unit.sheets().get(key) or unit.sheets().get("front")
    if p:
        try:
            pieces = drpg.atlas_pieces(p)
            if pieces:
                from PIL import Image
                big = max(pieces, key=lambda q: q["rgba"].shape[0] * q["rgba"].shape[1])
                return Image.fromarray(big["rgba"], "RGBA")
        except Exception:
            pass
    ex = unit.extras()
    if "icon" in ex:
        from PIL import Image
        return Image.open(ex["icon"]).convert("RGBA")
    return None


def thumbnail_path(unit):
    """a small picture for lists: the face if the folder has one"""
    return unit.extras().get("icon")


# ------------------------------------------------------------------------------------------------ hand-picked sheets
def _custom_meta(root):
    try:
        with open(os.path.join(root, "unit.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d.get("name", ""), d.get("group", "")
    except (OSError, ValueError):
        return "", ""


def stage_custom(files, name="", extras=None):
    """four sheet files picked by hand ({sheet key: path}; extras {'icon'/'cutin': path}) -> (uid, root): copied
    under a unit number of their own so every builder finds them like a DRPG folder's unit"""
    missing = [k for k, *_ in SHEETS if not files.get(k)]
    if missing:
        raise ValueError("these sheets are missing: " + ", ".join(missing))
    os.makedirs(CUSTOM_DIR, exist_ok=True)
    taken = {int(d) for d in os.listdir(CUSTOM_DIR) if d.isdigit()}
    uid = CUSTOM_FIRST
    while uid in taken:
        uid += 1
    root = os.path.join(CUSTOM_DIR, str(uid))
    sub, dirs = LAYOUTS[0]
    for k, _, _, fname in SHEETS:
        d = os.path.join(root, *sub, dirs[k])
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(files[k], os.path.join(d, fname.format(uid=uid)))
    for k, folder in (("icon", ("Characters", "Icons")), ("cutin", ("Characters", "Cut-Ins"))):
        if (extras or {}).get(k):
            d = os.path.join(root, *folder)
            os.makedirs(d, exist_ok=True)
            shutil.copyfile(extras[k], os.path.join(d, f"{uid}.png"))
    with open(os.path.join(root, "unit.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name or f"My sheets {uid}", "group": "", "sources": files, "extras": extras or {}}, f,
                  indent=1)
    return uid, root


# ------------------------------------------------------------------------------------------------ what can use them
def _twins_ok():
    p = os.path.join(os.path.dirname(__file__), "data", "drpg_outfit_twins.json")
    try:
        with open(p, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return set()
    return {int(k) for k, v in rep.items() if v.get("twin_ok")}


def character_sprites():
    """game characters (class ids) whose poses the kit has learned: they can wear a DRPG outfit, and a new character
    can take their animations"""
    from . import drpgmap
    return sorted(c for c in _twins_ok() if c < 1000 and os.path.exists(drpgmap.own_map_path(c)))


def class_templates():
    """generic classes a new DRPG class can take its animations from"""
    from . import newclasses
    return newclasses.templates()
