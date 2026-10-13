"""Skill editor backend: choreography (script.dat) and effect images (Effect.dat) of skills.

How the game plays a skill (found by tracing StartScript 0x14018F4A0 while skills ran):
  * the battle starts script event  SKILL_SCRIPT + skill id  (12000000 + magic.dat id); a skill without one falls
    back to 11000000 (a plain default sequence)
  * that event is usually a one-line wrapper:  call_event 15xxxxxx  -> the CHOREOGRAPHY, a script tree of
    15xxxxxx events (+ shared helpers 12000xxx: camera / damage / hit timing) made of commands for camera (0x32xx),
    effect slots (0x3Cxx: load an effect model into a slot, spawn it at an actor, colour / scale / rotate / fade it),
    particles (0x44xx), actors (0x64xx-0x6Cxx: motions, moves, extra actors), sound, waits and damage hits
  * effect models are Start/Start_JP.dat/Effect.dat/effectNNNN.obf (YKCMP-compressed .obf, textures inside), listed
    in EffectTableDataBase.dat; a choreography picks them with  cmd_3c00 <slot>, <effect id>

So a skill is edited entirely in data:
  * its choreography: assign any vanilla choreography, or an editable copy (new event ids MOD_CHOREO_BASE+...)
  * its images: copies of effect models (new ids from MOD_EFFECT_BASE) with replaced textures, referenced by the copy

Mod data (patches/skills/skills.json, images next to it):
  {"skills":  {"<skill id>": {"choreography": <root event id>}},
   "events":  {"<event id>": "<script text>"},                     custom choreography events
   "effects": {"<new effect id>": {"from": <effect id>, "textures": {"<index>": "<png file>"},
                                     "recolor": "<palette>" (optional, d5lib.fxrestyle: e.g. fire -> lightning),
                                     "la": true (optional: LA88 pictures made coloured in the palette first,
                                     "layer": k their softened layer k)}}}
"""
import json
import os
import re
import threading
import time

from . import database, nested, obf, script, ykcmp
from .modsys import register_patch_handler

SKILL_SCRIPT = 12000000
DEFAULT_SCRIPT = 11000000
CHOREO_MIN, CHOREO_MAX = 15000000, 16000000
MOD_CHOREO_BASE = 15900000          # custom choreographies: blocks of 1000 event ids, 15900000 .. 15999999 ...
# ... then event ids no game event uses, below 16777216 (call_event / spawn_event store an event id in 3 bytes):
# 14000000 .. 14999999, then 5000000 .. 10999999 -- 7 100 custom choreographies in all
MOD_CHOREO_EXT = [(14000000, 15000000), (5000000, 11000000)]
# Overloads aren't magic.dat skills to the script side: the game plays OverlordSkill.dat script_id (a wrapper like a
# skill's) and script_id + 100000 when animations are cut short.  Their animations live in "skills" under the key
# OVL_KEY + Overload id; a new Overload's wrapper is OVL_WRAPPER + id (13270300 ..; 13370300 .. the short one).
OVL_KEY = 1000000
OVL_WRAPPER = 13270000
OVL_SHORT = 100000
OVL_SHORT_BODY = "    call_event 15012900, 0\n    wait_children\n"          # what every game Overload's short one does
OVL_TABLE = "Database/Database_0.dat/OverlordSkill.dat"


def is_ovl_key(sid):
    return int(sid) >= OVL_KEY


def overload_scripts(get, mods=()):
    """{Overload id: its script_id} of OverlordSkill.dat (get = ctx.get / fs.read) with `mods`' db patches"""
    from . import dbpatch
    try:
        t = database.load_table("OverlordSkill.dat", get(OVL_TABLE))
    except Exception:
        return {}
    for m in mods:
        p = m.load_patch("db", "OverlordSkill.dat.json")
        if p:
            dbpatch.apply_patch(t, p)
    return {int(r["id"]): int(r["script_id"]) for r in t.rows}


def wrapper_id(sid, ovl_scripts=None):
    """the event that plays skill `sid` (an Overload key: its row's script_id)"""
    sid = int(sid)
    if is_ovl_key(sid):
        o = sid - OVL_KEY
        return int((ovl_scripts or {}).get(o) or OVL_WRAPPER + o)
    return SKILL_SCRIPT + sid


def is_choreo(e):
    """an event id of a skill choreography: the game's (15xxxxxx) or a mod's own"""
    e = int(e)
    return CHOREO_MIN <= e < CHOREO_MAX or any(lo <= e < hi for lo, hi in MOD_CHOREO_EXT)


def is_custom_choreo(e):
    """an event id of a mod's own choreography (an editable copy)"""
    e = int(e)
    return MOD_CHOREO_BASE <= e < CHOREO_MAX or any(lo <= e < hi for lo, hi in MOD_CHOREO_EXT)


def next_block(b):
    """the custom choreography block after `b`: 15900000 .. 15999000, then the MOD_CHOREO_EXT ranges"""
    ranges = [(MOD_CHOREO_BASE, CHOREO_MAX)] + MOD_CHOREO_EXT
    b += 1000
    for k, (lo, hi) in enumerate(ranges):
        if lo <= b < hi:
            return b
        if b == hi and k + 1 < len(ranges):
            return ranges[k + 1][0]
    raise RuntimeError("no free choreography block (all 7 100 are in use)")
MOD_EFFECT_BASE = 3000              # new effect models
EFFECT_MAX_ID = 32767               # a script names an effect model in a signed 16-bit operand (cmd_3c00)
EFFECT_LIMIT = EFFECT_MAX_ID + 1 - MOD_EFFECT_BASE   # new models: 29 768 (the game's own 400 is lifted: d5lib.fxpool)
SCRIPT = "Script/script.dat"
EFFECT_DAT = "Start/Start_JP.dat/Effect.dat"
EFFECT_TABLE = "Database/Database_0.dat/EffectTableDataBase.dat"
MAGIC = "Database/Database_0.dat/magic.dat"
FOLDER = "skills"
DATA_FILE = "skills.json"

REF_RE = re.compile(r"^(\s*)(call_event|spawn_event|call_event_b)\s+(\d+)")
EFFECT_RE = re.compile(r"^(\s*cmd_3c00\s+[^,]+,\s*)(\d+)")


# ------------------------------------------------------------------------------------------ scripts
class Scripts:
    """script.dat events by id (the game uses the first of duplicate ids, like ScriptFile.get)"""

    def __init__(self, data: bytes, pause=None):
        self.sf = script.ScriptFile.from_bytes(data, pause=pause)
        self.ovl_scripts = {}
        self.ev = {}
        for e in self.sf.events:
            self.ev.setdefault(e.id, e)

    @classmethod
    def load(cls, fs_or_ctx, pause=None):
        get = getattr(fs_or_ctx, "get", None) or fs_or_ctx.read
        sc = cls(get(SCRIPT), pause)
        sc.ovl_scripts = overload_scripts(get)
        return sc

    def text(self, eid):
        e = self.ev.get(int(eid))
        if e is None:
            return None
        lines = [l for l in script.disassemble_event(e) if l.strip()]
        return "\n".join(lines) + "\n"

    def refs(self, eid):
        e = self.ev.get(int(eid))
        if e is None:
            return []
        return [i.args[0] for i in e.code if i.cid in (0x0100, 0x0104, 0x0106) and isinstance(i.args[0], int)]

    def root_of(self, skill_id):
        """choreography root event of a skill (None: the skill falls back to the default sequence)"""
        w = wrapper_id(skill_id, getattr(self, "ovl_scripts", None))
        if w not in self.ev:
            return None
        for r in self.refs(w):
            if is_choreo(r):
                return r
        return w

    def tree(self, root):
        """events of a choreography: the root and every 15xxxxxx event it reaches (helpers 12xxxxxx are shared)"""
        out, todo = [], [int(root)]
        while todo:
            e = todo.pop(0)
            if e in out or e not in self.ev:
                continue
            out.append(e)
            todo += [r for r in self.refs(e) if is_choreo(r)]
        return out

    def effects(self, eids):
        found = []
        for e in eids:
            for line in (self.text(e) or "").splitlines():
                m = EFFECT_RE.match(line)
                if m and int(m.group(2)) not in found:
                    found.append(int(m.group(2)))
        return found


def remap(text, mapping):
    """event ids in call_event / spawn_event lines and the 'event <id>' header -> mapping"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("event "):
            eid = int(s.split()[1])
            line = f"event {mapping.get(eid, eid)}"
        else:
            m = REF_RE.match(line)
            if m and int(m.group(3)) in mapping:
                line = f"{m.group(1)}{m.group(2)} {mapping[int(m.group(3))]}" + line[m.end():]
        out.append(line)
    return "\n".join(out) + "\n"


def replace_effect(text, old, new):
    out = []
    for line in text.splitlines():
        m = EFFECT_RE.match(line)
        if m and int(m.group(2)) == int(old):
            line = f"{m.group(1)}{new}" + line[m.end():]
        out.append(line)
    return "\n".join(out) + "\n"


def wrapper_text(skill_id, root, ovl_scripts=None):
    return f"event {wrapper_id(skill_id, ovl_scripts)}\n    call_event {int(root)}\n    wait_children\n"


# ------------------------------------------------------------------------------------------ command reference
_ref = None


def reference():
    """{mnemonic: {"args": [...], "desc": str, "sure": verified|high|guess}} (data/choreo_commands.json)"""
    global _ref
    if _ref is None:
        p = os.path.join(os.path.dirname(__file__), "data", "choreo_commands.json")
        with open(p, encoding="utf-8") as f:
            _ref = json.load(f)["commands"]
    return _ref


def annotate(text):
    """choreography text with '; arg=value ... | what it does' after each known command (lines that already have a
    comment are left alone; the assembler ignores comments)"""
    ref = reference()
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or ";" in s or s.startswith(("event ", "if ", "endif", "loop", "endloop")) or s.endswith(":"):
            out.append(line)
            continue
        name, _, rest = s.partition(" ")
        r = ref.get(name)
        if not r:
            out.append(line)
            continue
        vals = [v.strip() for v in rest.split(",")] if rest else []
        names = r["args"]
        pairs = [f"{names[i] if i < len(names) and not names[i].endswith('...') else 'arg'}={v}"
                 for i, v in enumerate(vals)]
        note = " ".join(pairs[:6]) + (" " if pairs else "") + "| " + r["desc"].split(". ")[0]
        if r["sure"] == "guess":
            note += " (?)"
        out.append(f"{line:<48} ; {note}")
    return "\n".join(out) + "\n"


def strip_comments(text):
    return "\n".join(l.split(";", 1)[0].rstrip() if not l.lstrip().startswith("set_string") else l
                     for l in text.splitlines()) + "\n"


# ------------------------------------------------------------------------------------------ effects
def effect_members(get):
    raw = get(EFFECT_DAT)
    return {n: d for n, d, _ in nested.read_plain(raw)}


def effect_name(eid):
    return f"effect{int(eid):04d}.obf"


def load_effect(get, eid, members=None):
    members = members or effect_members(get)
    data = members.get(effect_name(eid))
    if data is None:
        return None
    return obf.ObfFile(ykcmp.decompress(data))


def geometry(o):
    """what an effect model draws, for choosing pictures: 'flat' (one plane: circles, sprites, flashes),
    'wall' (a ring / cylinder around the spot: the texture's width wraps once around it, so tile pictures),
    'mesh' (anything else)"""
    import numpy as np
    v = o.vertices()
    if not len(v):
        return "mesh"
    p = v[:, :3]
    span = p.max(0) - p.min(0)
    if (span < 1e-3).any():
        return "flat"
    r = np.hypot(p[:, 0], p[:, 2])
    if span[1] > 1e-3 and r.min() > 0.5 * r.max():
        return "wall"
    return "mesh"


def effect_room(fs, mod):
    """how many more new effect models there are ids for (MOD_EFFECT_BASE .. EFFECT_MAX_ID) next to the enabled mods'
    new ones (`mod`'s own counted too).  The game's own limit of 400 models is lifted by d5lib.fxpool."""
    from . import modsys
    kit = os.path.dirname(os.path.dirname(os.path.abspath(mod.folder)))
    ids = set()
    mods = [m for m in modsys.ModManager(kit).enabled_mods() if m.id != mod.id] + [mod]
    for m in mods:
        ids |= {int(k) for k in (m.load_patch(FOLDER, DATA_FILE) or {}).get("effects", {})}
    return EFFECT_LIMIT - len(ids)


def effect_model(get, eid, members=None, mods=()):
    """ObfFile of effect `eid`: a vanilla one, or a mod's new one (built from its source and pictures)"""
    o = load_effect(get, eid, members)
    if o is not None:
        return o
    for m in mods:
        e = (m.load_patch(FOLDER, DATA_FILE) or {}).get("effects", {}).get(str(int(eid)))
        if e:
            from PIL import Image
            pdir = os.path.join(m.patches_dir, FOLDER)
            if e.get("obf"):                       # a whole model of its own (fxbuild)
                with open(os.path.join(pdir, e["obf"]), "rb") as f:
                    src = obf.ObfFile(f.read())
            else:
                src = load_effect(get, e["from"], members)
            if e.get("recolor"):
                from . import fxrestyle
                fxrestyle.recolor_obf(src, e["recolor"], la=bool(e.get("la")), layer=int(e.get("layer", 0)))
            imgs = {int(i): Image.open(os.path.join(pdir, f)) for i, f in e.get("textures", {}).items()}
            return obf.ObfFile(ykcmp.decompress(build_effect(src, imgs)))
    return None


def effect_info(get, eid, members=None, mods=()):
    """{'id', 'geometry', 'textures': [(index, PIL image or None, w, h, format, layers, additive)], 'from': source
    effect of a mod's new one}"""
    o = effect_model(get, eid, members, mods)
    if o is None:
        return None
    tex = []
    for i, t in enumerate(o.textures):
        try:
            img = t.to_image()
        except ValueError:
            img = None
        tex.append((i, img, t.width, t.height, t.format_name, t.layers, img is not None and is_additive(t)))
    src = next(((m.load_patch(FOLDER, DATA_FILE) or {}).get("effects", {}).get(str(int(eid)), {}).get("from")
                for m in mods if str(int(eid)) in (m.load_patch(FOLDER, DATA_FILE) or {}).get("effects", {})), None)
    return {"id": int(eid), "geometry": geometry(o), "textures": tex, "from": src}


def effect_textures(get, eid):
    """[(index, PIL image or None, (w, h, format))] of an effect model"""
    o = load_effect(get, eid)
    out = []
    for i, t in enumerate(o.textures if o else []):
        try:
            img = t.to_image()
        except ValueError:
            img = None
        out.append((i, img, (t.width, t.height, t.format_name)))
    return out


def build_effect(src_obf, images):
    """copy of an effect model with textures replaced: images {index: PIL image} (resized to the texture)
    -> YKCMP bytes for Effect.dat"""
    from PIL import Image
    for i, img in images.items():
        t = src_obf.textures[int(i)]
        img = img.convert("RGBA")
        if img.size not in ((t.width, t.height), (t.width, t.height * t.layers)):
            img = img.resize((t.width, t.height), Image.LANCZOS)
        keep = t.fmt in (obf.FMT_ARGB, obf.FMT_DXT1, obf.FMT_DXT3, obf.FMT_DXT5)
        t.replace_image(img, keep_format=keep)
    return ykcmp.compress(src_obf.to_bytes())


# ------------------------------------------------------------------------------------------ mod data
def load(mod):
    d = mod.load_patch(FOLDER, DATA_FILE) or {}
    d.setdefault("skills", {})
    d.setdefault("events", {})
    d.setdefault("effects", {})
    return d


def save(mod, d):
    empty = not (d.get("skills") or d.get("events") or d.get("effects"))
    mod.save_patch(FOLDER, DATA_FILE, None if empty else d)


def folder(mod):
    p = os.path.join(mod.patches_dir, FOLDER)
    os.makedirs(p, exist_ok=True)
    return p


def _all_mods(mod):
    from .modsys import Mod
    root = os.path.dirname(mod.folder)
    return [Mod(os.path.join(root, n)) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]


def used_ids(mod):
    ev, fx = set(), set()
    for m in _all_mods(mod):
        d = m.load_patch(FOLDER, DATA_FILE) or {}
        ev |= {int(k) for k in d.get("events", {})}
        fx |= {int(k) for k in d.get("effects", {})}
    return ev, fx


_cache = {}
_cache_lock = threading.Lock()


def vanilla_scripts(fs, background=False):
    """Scripts of the vanilla game, parsed once per GameFS and shared by the whole kit (Skills & Animations, Event
    Scripts, the builders): 1.6 million commands, ~2 s.  Never changed in place (Event Scripts edits a copy of the
    event list).  The collector is off while they are made (its passes nearly doubled the time) and they are
    frozen out of its later passes: each full pass over them took ~0.4 s, a stutter anywhere in the kit.
    background: a worker thread's load -- the GUI thread gets the interpreter every 256 events."""
    k = id(fs)
    with _cache_lock:                    # a second caller waits for the first load instead of parsing again
        if k not in _cache:
            import gc
            was = gc.isenabled()
            gc.disable()
            try:
                _cache[k] = Scripts.load(fs, (lambda: time.sleep(0.001)) if background else None)
            finally:
                gc.freeze()
                if was:
                    gc.enable()
        return _cache[k]


def vanilla_scripts_ready(fs):
    return id(fs) in _cache


def inherit(fs, mod, skill_id, copy_of):
    """a skill copied from another plays that skill's choreography (unless the mod already set one)"""
    d = load(mod)
    if str(int(skill_id)) in d["skills"]:
        return None
    src = d["skills"].get(str(int(copy_of)), {}).get("choreography") or vanilla_scripts(fs).root_of(copy_of)
    if src:
        assign(mod, skill_id, src)
    return src


def assign(mod, skill_id, root):
    """skill plays the choreography starting at event `root` (vanilla or custom)"""
    d = load(mod)
    d["skills"][str(int(skill_id))] = {"choreography": int(root)}
    save(mod, d)


def make_custom(fs, mod, skill_id, from_root, sc=None):
    """editable copy of choreography `from_root` (vanilla, or a custom one of any mod) for a skill -> new root id"""
    sc = sc or with_mods(fs, _all_mods(mod))
    used, _ = used_ids(mod)
    used_blocks = {int(u) // 1000 * 1000 for u in used}
    block = MOD_CHOREO_BASE
    while block in used_blocks:
        block = next_block(block)
    ids = sc.tree(from_root)
    mapping = {old: block + k for k, old in enumerate(ids)}
    d = load(mod)
    for old in ids:
        d["events"][str(mapping[old])] = remap(sc.text(old), mapping)
    d["skills"][str(int(skill_id))] = {"choreography": block, "copied_from": int(from_root)}
    save(mod, d)
    return block


def with_mods(fs, mods):
    """vanilla scripts + the skill events / wrappers of `mods` (what the game runs once they are installed)"""
    base = vanilla_scripts(fs)
    sc = Scripts.__new__(Scripts)
    sc.sf = base.sf
    sc.ev = dict(base.ev)
    sc.ovl_scripts = overload_scripts(fs.read, mods)
    from . import scriptpatch
    for m in mods:
        d = m.load_patch(FOLDER, DATA_FILE) or {}
        events = dict(d.get("events", {}))
        for sid, e in d.get("skills", {}).items():
            if e.get("choreography"):
                events[str(wrapper_id(sid, sc.ovl_scripts))] = wrapper_text(sid, e["choreography"], sc.ovl_scripts)
        for k, t in events.items():
            try:
                sc.ev[int(k)] = scriptpatch.parse_event_text(t)
            except Exception:
                pass
    return sc


def custom_events(mod, root):
    d = load(mod)
    root = int(root)
    return sorted(int(k) for k in d["events"] if root <= int(k) < root + 1000)


def set_event(mod, eid, text):
    """store edited event text (checked by assembling it; comments are dropped)"""
    from . import scriptpatch
    text = strip_comments(text)
    ev = scriptpatch.parse_event_text(text)
    if ev.id != int(eid):
        raise ValueError(f"the text is event {ev.id}, expected {eid}")
    d = load(mod)
    d["events"][str(int(eid))] = text if text.endswith("\n") else text + "\n"
    save(mod, d)


def is_additive(tex):
    """opaque ARGB effect textures are drawn additively: black is invisible, colours add light (RGB565 ones are
    always opaque)"""
    if tex.fmt == obf.FMT_565:
        return True
    if tex.fmt != obf.FMT_ARGB:
        return False
    import numpy as np
    return int(np.asarray(tex.to_image())[..., 3].min()) == 255


def prepare(img, tex, fit="contain", scale=1.0, rotate=0.0, layer_count=None, trim=True, tile=1, brightness=None):
    """picture -> image for effect texture `tex`: trimmed to its visible part, rotated (degrees, counter-clockwise),
    fitted (contain: whole picture, centred | cover: fills, cropped | stretch) and scaled into one layer, or into
    each of `tile` columns (wall effects wrap the width once around a cylinder about 6x wider than tall: tile ~ 10 with
    fit='stretch' shows upright pictures).
    Additive textures (black = nothing, light adds up) get the picture on black, dimmed so it adds about as much
    light as the original (brightness: None = that automatic factor, else a fixed one). LA88 textures get the
    picture in every layer."""
    from PIL import Image
    img = (Image.open(img) if isinstance(img, (str, os.PathLike)) else img).convert("RGBA")
    box = img.getchannel("A").getbbox() if trim else None
    if box:
        img = img.crop(box)
    if rotate:
        img = img.rotate(rotate, Image.BICUBIC, expand=True)
    full_w, h = tex.width, tex.height
    tile = max(1, int(tile))
    w = max(1, full_w // tile)
    if fit == "stretch":
        pic = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    else:
        f = (min if fit == "contain" else max)(w / img.width, h / img.height) * scale
        pic = img.resize((max(1, round(img.width * f)), max(1, round(img.height * f))), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(pic, ((w - pic.width) // 2, (h - pic.height) // 2)) if pic.width <= w and pic.height <= h         else out.alpha_composite(pic.crop(((pic.width - w) // 2, (pic.height - h) // 2,
                                            (pic.width - w) // 2 + w, (pic.height - h) // 2 + h)))
    if tile > 1:
        row = Image.new("RGBA", (full_w, h), (0, 0, 0, 0))
        for k in range(tile):
            row.alpha_composite(out, (k * full_w // tile + (full_w // tile - w) // 2, 0))
        out, w = row, full_w
    if is_additive(tex):
        import numpy as np
        bg = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        bg.alpha_composite(out)
        out = bg
        if brightness is None:
            ref = np.asarray(tex.to_image().convert("RGB"), np.float32).mean()
            now = max(1.0, np.asarray(out.convert("RGB"), np.float32).mean())
            brightness = min(1.0, max(0.25, 3.0 * ref / now))
    if brightness is not None and brightness != 1.0:
        import numpy as np
        a = np.asarray(out, np.float32)
        a[..., :3] *= brightness
        out = Image.fromarray(a.clip(0, 255).astype(np.uint8), "RGBA")
    k = layer_count or getattr(tex, "layers", 1)
    if k > 1:
        out = obf._stack([out] * k)
    return out


def new_effect(fs, mod, from_id, images, effect_id=None):
    """effect model copy with replaced textures (images {index: path or PIL, already prepared}) -> new effect id"""
    from PIL import Image
    _, used = used_ids(mod)
    if effect_id is None:
        effect_id = MOD_EFFECT_BASE
        while effect_id in used:
            effect_id += 1
        if effect_id > EFFECT_MAX_ID:
            raise RuntimeError(f"no free effect id (scripts name effect models up to {EFFECT_MAX_ID})")
    d = load(mod)
    tex = dict(d["effects"].get(str(effect_id), {}).get("textures", {}))
    for i, img in images.items():
        name = f"fx{effect_id}_{int(i)}.png"
        im = Image.open(img) if isinstance(img, str) else img
        im.convert("RGBA").save(os.path.join(folder(mod), name))
        tex[str(int(i))] = name
    d["effects"][str(effect_id)] = {"from": int(from_id), "textures": tex}
    save(mod, d)
    return effect_id


def set_picture(fs, mod, skill_id, effect_id, index, picture, **prep):
    """the skill shows `picture` (path or PIL image) as texture `index` of effect `effect_id`: the skill gets an
    editable choreography copy if it has none, a vanilla effect gets a copy of its own (new id) used by that copy
    only, and the picture is fitted to the texture (prepare(): fit, scale, rotate, tile, brightness, trim).
    -> the effect id the skill uses now"""
    skill_id, effect_id = int(skill_id), int(effect_id)
    d = load(mod)
    s = d["skills"].get(str(skill_id), {})
    root = s.get("choreography")
    if not root or not is_custom_choreo(root):
        root = make_custom(fs, mod, skill_id, root or vanilla_scripts(fs).root_of(skill_id) or DEFAULT_SCRIPT)
        d = load(mod)
    own = d["effects"].get(str(effect_id))
    src = own["from"] if own else effect_id
    o = load_effect(fs.read, src)
    if o is None:
        raise ValueError(f"effect {src} not found")
    img = prepare(picture, o.textures[int(index)], **prep)
    if own:
        new_effect(fs, mod, src, {int(index): img}, effect_id=effect_id)
        return effect_id
    nid = new_effect(fs, mod, src, {int(index): img})
    use_effect(mod, root, effect_id, nid)
    return nid


def use_effect(mod, root, old, new):
    """in a custom choreography, every 'cmd_3c00 slot, <old>' loads <new> instead"""
    d = load(mod)
    for eid in custom_events(mod, root):
        d["events"][str(eid)] = replace_effect(d["events"][str(eid)], old, new)
    save(mod, d)


# ------------------------------------------------------------------------------------------ build
# The battle starts a skill as 12000000 + id, or, when its effects are skipped (Ally / Enemy Effects 'skip', the skip
# button, AI use), 12100000 + id (then 12100000 + id // 10 * 10, then 11100000); skipping midway restarts it as
# 12200000 + id.  A monster's normal attack works the same way on 12010000 / 12110000 / 12210000 + sprite id.  Vanilla
# has no 11100000 / 11200000, so an action whose events are all missing starts no script and the battle waits forever.
SKIP_SCRIPT, SKIPPED_SCRIPT = 12100000, 12200000
SKIP_BODY = "    call_event 15019700, 0, 0, 0, 0\n    wait_children\n"      # what 516 of 618 vanilla 121xxxxx do
SKIPPED_BODY = "    call_event 11120000, 0, 0, 0, 0\n    wait_children\n"   # ... and 515 of 593 122xxxxx
FALLBACKS = {11100000: SKIP_BODY, 11200000: SKIPPED_BODY}


END_WORDS = ("wait_children", "wait_children_b")


def ensure_end(text):
    """an event's text ends with wait_children (the game needs it: a thread without it runs on and the skill stalls;
    events added by older kit versions lacked it)"""
    lines = [l for l in text.rstrip().splitlines() if l.strip()]
    last = lines[-1].strip() if lines else ""
    if last and last.split()[0] in END_WORDS:
        return text
    return text.rstrip() + "\n    wait_children\n"


def apply_scripts(sf, d, log=None, ovl_scripts=None):
    """mod data -> script.ScriptFile: custom events, a wrapper per skill with a choreography, and the skill's
    skip / skipped-midway events (without them a skill used with its effects skipped stalls the battle); an
    Overload's wrapper is its script_id (ovl_scripts {Overload id: script_id}), with the short one beside it"""
    from . import scriptpatch
    events = {k: ensure_end(t) for k, t in d.get("events", {}).items()}
    have = None
    for sid, s in d.get("skills", {}).items():
        if s.get("choreography") and is_ovl_key(sid):
            w = wrapper_id(sid, ovl_scripts)
            events[str(w)] = wrapper_text(sid, s["choreography"], ovl_scripts)
            have = have if have is not None else {e.id for e in sf.events}
            if w + OVL_SHORT not in have:
                events.setdefault(str(w + OVL_SHORT), f"event {w + OVL_SHORT}\n" + OVL_SHORT_BODY)
        elif s.get("choreography"):
            sid = int(sid)
            events[str(SKILL_SCRIPT + sid)] = wrapper_text(sid, s["choreography"])
            events.setdefault(str(SKIP_SCRIPT + sid), f"event {SKIP_SCRIPT + sid}\n" + SKIP_BODY)
            events.setdefault(str(SKIPPED_SCRIPT + sid), f"event {SKIPPED_SCRIPT + sid}\n" + SKIPPED_BODY)
    scriptpatch.apply(sf, {"events": events})
    add_fallbacks(sf)
    return len(events)


def add_fallbacks(sf):
    """11100000 / 11200000 (missing in vanilla): the last resort of every skipped action"""
    from . import scriptpatch
    have = {e.id for e in sf.events}
    extra = {str(k): f"event {k}\n" + body for k, body in FALLBACKS.items() if k not in have}
    if extra:
        scriptpatch.apply(sf, {"events": extra})
    return len(extra)


def _handler(ctx, mod, patch_dir):
    d = load(mod)
    ctx.needs_runtime = ctx.live_skills = True      # the runtime DLL's live preview (d5live.inc.c)
    n = 0
    if d["skills"] or d["events"]:
        sf = ctx.parsed(SCRIPT, script.ScriptFile.from_bytes)
        n = apply_scripts(sf, d, ovl_scripts=overload_scripts(ctx.get))
        ctx.changed(SCRIPT, script.ScriptFile.to_bytes)
    if d["effects"]:
        members = effect_members(ctx.get)
        t = database.load_table("EffectTableDataBase.dat", ctx.get(EFFECT_TABLE))
        rows = {r["effect_id"]: r for r in t.rows}
        for nid, e in d["effects"].items():
            nid = int(nid)
            if e.get("obf"):                       # a whole model of its own (fxbuild)
                with open(os.path.join(patch_dir, e["obf"]), "rb") as f:
                    src = obf.ObfFile(f.read())
            else:
                src = obf.ObfFile(ykcmp.decompress(members[effect_name(e["from"])]))
            from PIL import Image
            if e.get("recolor"):
                from . import fxrestyle
                fxrestyle.recolor_obf(src, e["recolor"], la=bool(e.get("la")), layer=int(e.get("layer", 0)))
            imgs = {int(i): Image.open(os.path.join(patch_dir, f)) for i, f in e.get("textures", {}).items()}
            ctx.put(f"{EFFECT_DAT}/{effect_name(nid)}", build_effect(src, imgs))
            if nid not in rows:
                r = rows[int(e["from"])].copy()
                r.set("effect_id", nid)
                t.rows.append(r)
                rows[nid] = r
        t.rows.sort(key=lambda r: r["effect_id"])      # TableDataBase: binary-searched in file order
        if max(rows) > EFFECT_MAX_ID:
            raise ValueError(f"effect id {max(rows)}: scripts name effect models up to {EFFECT_MAX_ID}")
        ctx.put(EFFECT_TABLE, t.to_bytes())
    ctx.log(f"  skills: {len(d['skills'])} skill(s), {n} script event(s), {len(d['effects'])} effect model(s)")


register_patch_handler(FOLDER, _handler, order=32)


# ------------------------------------------------------------------------------------------ live preview
LIVE_FILE = "d5live_script.dat"
SPAWN_CMDS = ("cmd_3c10", "cmd_3c18", "cmd_3c20", "cmd_3c22")


def live_script(fs, mods, solo=None):
    """plain script.dat as installing `mods` would make it (their script patches and skill edits, in load order).
    solo {skill id: [slots]}: that skill's custom choreography only shows those effect slots (to see which slot
    draws what)."""
    from . import scriptpatch
    sf = script.ScriptFile.from_bytes(fs.read(SCRIPT))
    ovl_scripts = overload_scripts(fs.read, mods)
    for m in mods:
        for fname in m.list_patches("script"):
            scriptpatch.apply(sf, m.load_patch("script", fname) or {})
        d = m.load_patch(FOLDER, DATA_FILE)
        if not d:
            continue
        d = {k: dict(v) for k, v in d.items()}
        for sid, slots in (solo or {}).items():
            root = d.get("skills", {}).get(str(int(sid)), {}).get("choreography")
            if not root:
                continue
            for k in list(d.get("events", {})):
                if int(root) <= int(k) < int(root) + 1000:
                    d["events"][k] = _solo(d["events"][k], {int(x) for x in slots})
        apply_scripts(sf, d, ovl_scripts=ovl_scripts)
    from . import newclasses                    # what the install adds for new classes (attack / class events)
    specs = {int(sp["family"]): sp for m in mods for sp in newclasses.load_specs(m)}
    if specs:
        vanilla = script.ScriptFile.from_bytes(fs.read(SCRIPT))
        newclasses.add_class_scripts(sf, vanilla, specs)
        add_fallbacks(sf)
    return sf.to_bytes()


def _solo(text, slots):
    out = []
    for line in text.splitlines():
        s = line.strip()
        slot = s.split()[1].rstrip(",") if s.startswith(SPAWN_CMDS) else ""
        if slot.isdigit() and int(slot) not in slots:
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def send_live(game_dir, data):
    """hand the script data to the running game (runtime [skills] live_reload, d5live.inc.c): written to a temp
    file and renamed, so the game never reads half a file"""
    p = os.path.join(game_dir, LIVE_FILE)
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)
    return p
