"""Overloads: new ones for any character (vanilla or new), and changes to the game's own.

How the game does it (traced 2026-10-12, docs/EXE_ANALYSIS.md "Overloads"):
  * char.dat +0xCC (u16) = the character's Overload id.  OverlordSkill.dat (binary-searched by id) holds its name,
    three description lines and the event that plays it (script_id; script_id + 100000 when animations are cut
    short -- the game's own call 15012900).  The battle side is a magic.dat row of skill_type 4: 0x1401dd050 maps
    Overload 1-19 / 100-114 / 200-213 to magic 3000-3047 and any other id to none (its menu entry stays grey).
  * Overloads need Revenge Mode: unit +0x35bc (u16 gauge) == 10000.
  * Damage / drain / heal / status Overloads (formula 2 / 3 / 4 / 6) are plain magic rows: numbers, effects,
    element and area are data.  The others (formula 5) are code: 0x140163bf0 switches on the Overload id the unit
    is using (battle record +0xe60) and keeps the result as a timed state keyed by the magic id (3003 giant and
    stats ...) that stat, AI and display code check all over the exe; a few checks compare the Overload id itself
    (in 0x140163bf0: 2 charm males, 3 control males, 5 / 213 giant size, 211; usability 0x14014efe5 ..).
  * The title banner shown while an Overload plays: 0x1404b2fc0 switches on the Overload id -> animation 100 ..
    500 of the UI block 9032 (resident pack, one per language), which shows the name picture 1000 + that value.
  Magic ids 3000-3255 are the Overload range (a unit keeps 256 words for them in its data), so an Overload with
  numbers of its own takes one of 3048-3255 (208 in all, every mod together); one that works like a game Overload
  uses that Overload's magic row and code, and costs nothing (new Overload ids: 300 .. 29999).

Hooks (code section .d5ov): the mapping (new or changed ids -> magic id), the dispatch and the id checks (-> the
Overload it works like) and the banner, all from one table {id, magic id, works like, banner}.  A new Overload, or a
game one renamed, gets a banner of its own (facepatch.add_overload_banners): its name drawn in the banner style of
a game Overload (gradient, black outline, shadow), or a picture of the mod's (patches/overloads/banner_<id>.png).

Mod data:
  patches/overloads/overloads.json   {"overloads": {"<id>": {"like": <game Overload id> (0: none),
                                                             "skill": <own magic id 3048-3255> (optional),
                                                             "banner": <game Overload whose banner style>,
                                                             "colors": [[r, g, b] top, [r, g, b] bottom] (optional)}}}
  patches/db/OverlordSkill.dat.json  name, description lines, script_id (new ones: WRAPPER_BASE + id)
  patches/db/magic.dat.json          the numbers of an Overload with its own ("skill")
  patches/db/char.dat.json           who has which Overload (overload_id)
  patches/skills/skills.json         its animation: "skills" {"<skills.OVL_KEY + id>": {"choreography": root}}
                                     (edited on the Skills page like any skill)
"""
import struct

from . import database, dbpatch, script, skills
from .dbpatch import DB_ARCHIVE
from .exepatch import IMAGE_BASE, add_hook_section
from .gamefs import EXE_FILE
from .modsys import register_finalizer, register_patch_handler

FOLDER = "overloads"
DATA_FILE = "overloads.json"
SECTION_NAME = b".d5ov"
TABLE = "OverlordSkill.dat"
MAGIC = "magic.dat"
CHAR = "char.dat"
OVL_PATH = f"{DB_ARCHIVE}/{TABLE}"
MAGIC_PATH = f"{DB_ARCHIVE}/{MAGIC}"

NEW_FIRST, NEW_LAST = 300, 29999          # ids of new Overloads (their animation events WRAPPER_BASE + id)
SKILL_FIRST, SKILL_LAST = 3048, 3255      # magic ids of Overloads with numbers of their own
NONE = 0xFFFF                             # "works like nothing": the dispatch's default case (no special code)
# the dispatch case shared by 16 / 18 / 103 / 105 only applies the Overload's own skill row to its targets (through
# placeholder skill 3603): what an Overload with numbers of its own needs (without it nothing is hit; tested)
GENERIC = 105
DEFAULT_BANNER = 100
NEW_BANNERS = 2000                        # banner animations of new pictures: 2000, 2002 .. (+1: the name picture)
RESIDENT = ("Anime/ANM_HI_JP.dat/anm_resident.lzs", "Anime/ANM_HI_EN.dat/anm_resident.lzs")
BANNER_H = 84
# gradient (top, bottom) of the game's name pictures (sampled from the EN ones)
BANNER_COLORS = {
    1: ((75, 116, 220), (170, 177, 229)), 2: ((145, 63, 179), (222, 86, 189)), 3: ((144, 62, 178), (223, 87, 190)),
    4: ((191, 32, 63), (226, 112, 62)), 5: ((189, 32, 62), (227, 112, 62)), 6: ((45, 203, 158), (173, 227, 188)),
    7: ((45, 207, 161), (173, 227, 188)), 8: ((220, 164, 44), (227, 203, 103)), 9: ((159, 159, 171), (208, 201, 219)),
    10: ((145, 115, 88), (219, 193, 48)), 11: ((117, 79, 225), (168, 153, 228)), 12: ((117, 79, 225), (168, 153, 228)),
    13: ((106, 91, 126), (184, 45, 99)), 14: ((103, 91, 125), (181, 45, 98)), 15: ((106, 92, 127), (184, 46, 99)),
    16: ((107, 93, 128), (181, 45, 97)), 17: ((102, 91, 125), (187, 42, 97)), 18: ((103, 92, 126), (184, 46, 99)),
    19: ((103, 91, 125), (181, 45, 98)), 100: ((198, 60, 116), (224, 126, 211)), 101: ((220, 58, 68), (229, 155, 79)),
    102: ((144, 101, 220), (88, 212, 172)), 105: ((146, 50, 187), (220, 111, 135)),
    107: ((116, 86, 213), (218, 215, 226)), 109: ((195, 92, 181), (227, 163, 186)),
    110: ((163, 50, 54), (221, 73, 107)), 111: ((107, 99, 94), (210, 174, 105)),
    112: ((118, 115, 132), (181, 146, 135)), 114: ((118, 101, 113), (206, 40, 42)),
    200: ((47, 99, 217), (121, 200, 229)), 201: ((223, 47, 47), (228, 149, 149)),
    202: ((223, 142, 220), (219, 202, 228)), 203: ((182, 10, 20), (184, 94, 185)),
    204: ((161, 9, 206), (137, 108, 227)), 205: ((225, 115, 140), (196, 41, 50)), 206: ((71, 196, 36), (176, 186, 33)),
    207: ((185, 33, 59), (224, 102, 49)), 208: ((162, 15, 68), (199, 159, 7)), 209: ((127, 0, 0), (197, 0, 0)),
    210: ((86, 21, 198), (208, 181, 201)), 211: ((193, 11, 87), (226, 107, 147)), 212: ((208, 148, 93), (195, 49, 10)),
    213: ((192, 35, 63), (226, 112, 62))}
FONTS = ("ARLRDBD.TTF", "segoeuib.ttf", "arialbd.ttf", "tahomabd.ttf")      # Arial Rounded first: closest to the game's
WRAPPER_BASE = skills.OVL_WRAPPER
SHORT = skills.OVL_SHORT

# the game's switches (decoded from the exe, see vanilla_tables)
MAP_VA, MAP_ORIG, MAP_NEXT = 0x1401DD050, bytes.fromhex("ffc981f9d4000000"), 0x1401DD058
MAP_INDEX, MAP_JUMPS, MAP_COUNT = 0x1401DD268, 0x1401DD1A4, 0xD5
DISPATCH_VA, DISPATCH_ORIG, DISPATCH_NEXT = 0x140163C6E, bytes.fromhex("8b88600e0000"), 0x140163C74
BANNER_VA, BANNER_ORIG, BANNER_NEXT, BANNER_SET = 0x1404B2FFC, bytes.fromhex("ffc83dd4000000"), 0x1404B3003, \
    0x1404B317B
BANNER_INDEX, BANNER_JUMPS = 0x1404B3268, 0x1404B31C0
GETTER = 0x140160810                      # unit -> the Overload it has (or uses: Brigante Eclipse's stolen one)
# calls of GETTER whose result picks behaviour (-> the Overload it works like); the others (names, scripts,
# the battle record, the banner) keep the id
ALIAS_CALLS = [0x14014EFE5, 0x14014EFF2, 0x14014F036,                  # may it be used now (state already on?)
               0x140163DEE, 0x140163E3B, 0x140163E9F, 0x140163EBA,      # 0x140163bf0: charm / control / giant
               0x1401664D6]


# ------------------------------------------------------------------------------------------ the game's tables
def _rva_reader(exe):
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)

    def rd(va, n):
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        return exe[off:off + n]
    return rd


_vanilla = {}


def vanilla_tables(exe):
    """({Overload id: magic id}, {Overload id: banner}) of the game's two switches (ids 1 .. 213)"""
    from . import exemap
    key = len(exe), exe[:0x400], exemap.ACTIVE.id
    if key in _vanilla:
        return _vanilla[key]
    rd = _rva_reader(exe)
    from . import exemap
    T = exemap.ACTIVE                       # the tables of the game build being patched
    magic, banner = {}, {}
    idx = rd(T(MAP_INDEX), MAP_COUNT)
    for i, k in enumerate(idx):
        tgt = IMAGE_BASE + struct.unpack("<i", rd(T(MAP_JUMPS) + 4 * k, 4))[0]
        code = rd(tgt, 6)
        if code[0] == 0xB8 and code[5] == 0xC3:                 # mov eax, imm32 / ret
            v = struct.unpack_from("<i", code, 1)[0]
            if v > 0:
                magic[i + 1] = v
    idx = rd(T(BANNER_INDEX), MAP_COUNT)
    for i, k in enumerate(idx):
        tgt = IMAGE_BASE + struct.unpack("<i", rd(T(BANNER_JUMPS) + 4 * k, 4))[0]
        code = rd(tgt, 5)
        banner[i + 1] = struct.unpack_from("<i", code, 1)[0] if code[0] == 0xBB else DEFAULT_BANNER
    _vanilla[key] = magic, banner
    return magic, banner


def vanilla_magic(ovl):
    """magic id of a game Overload (the switch is regular: 1-19, 100-114, 200-213 -> 3000-3047)"""
    o = int(ovl)
    if 1 <= o <= 19:
        return 2999 + o
    if 100 <= o <= 114:
        return 2919 + o
    if 200 <= o <= 213:
        return 2834 + o
    return None


def is_game_overload(ovl):
    return vanilla_magic(ovl) is not None


# ------------------------------------------------------------------------------------------ mod data
def load(mod):
    d = mod.load_patch(FOLDER, DATA_FILE) or {}
    d.setdefault("overloads", {})
    return d


def save(mod, d):
    mod.save_patch(FOLDER, DATA_FILE, d if d.get("overloads") else None)


def merged(mods):
    """{id: entry} of every mod (later mods win per field)"""
    out = {}
    for m in mods:
        for k, e in load(m)["overloads"].items():
            out.setdefault(int(k), {}).update(e)
    return out


def _base_mods(mod):
    """the enabled mods other than `mod`, in load order (what the kit's table editors diff a mod's patch against)"""
    import os
    from .modsys import ModManager
    try:
        mm = ModManager(os.path.dirname(os.path.dirname(mod.folder)))
        return [m for m in mm.enabled_mods() if m.id != mod.id]
    except Exception:
        return []


def _tables(fs, mod, member):
    """(base, edited): the table as the other enabled mods leave it, and with `mod`'s patch on top"""
    others = _base_mods(mod)
    van = table_with(fs, others, member)
    ed = table_with(fs, others + [mod], member)
    return van, ed


def _save_table(mod, member, van, ed):
    d = dbpatch.diff_table(van, ed)
    mod.save_patch("db", member + ".json", None if dbpatch.is_empty(d) else d)


def table_with(fs, mods, member):
    """a table as `mods` leave it (their db patches applied in order)"""
    t = database.load_table(member, fs.read(f"{DB_ARCHIVE}/{member}"))
    for m in mods:
        p = m.load_patch("db", member + ".json")
        if p:
            dbpatch.apply_patch(t, p)
    return t


def _all_mods(mod):
    return skills._all_mods(mod)


def used_ids(fs, mod):
    """Overload ids and own magic ids in use (the game's and every mod's)"""
    ids, magic = set(), set()
    for m in [None] + _all_mods(mod):
        if m is None:
            ids |= {int(r["id"]) for r in database.load_table(TABLE, fs.read(OVL_PATH)).rows}
            magic |= {int(r["id"]) for r in database.load_table(MAGIC, fs.read(MAGIC_PATH)).rows}
            continue
        for member, bucket in ((TABLE, ids), (MAGIC, magic)):
            p = m.load_patch("db", member + ".json") or {}
            bucket |= {int(r["id"]) for r in p.get("added", []) if "id" in r}
            bucket |= {int(f["id"]) for f in (p.get("rows") or {}).values() if "id" in f}
        for k, e in load(m)["overloads"].items():
            ids.add(int(k))
            if e.get("skill"):
                magic.add(int(e["skill"]))
    return ids, magic


def next_id(fs, mod):
    ids, _ = used_ids(fs, mod)
    for i in range(NEW_FIRST, NEW_LAST + 1):
        if i not in ids:
            return i
    raise RuntimeError(f"no free Overload id ({NEW_FIRST}-{NEW_LAST} are all in use)")


def next_skill(fs, mod):
    _, magic = used_ids(fs, mod)
    for i in range(SKILL_FIRST, SKILL_LAST + 1):
        if i not in magic:
            return i
    raise RuntimeError(f"all {SKILL_LAST - SKILL_FIRST + 1} Overload skill ids ({SKILL_FIRST}-{SKILL_LAST}) are in "
                       "use: give the new Overload the numbers of a game Overload ('works like') instead")


def _set_text(row, field, text):
    for L in ("JP", "EN", "FR", "CHN", "KOR"):
        k = f"{field}_{L}"
        if k in row:
            row.set(k, text, truncate=True)


def magic_of(entry, ovl):
    """magic id an Overload uses: its own, or the one of the Overload it works like (or its own game row)"""
    if entry.get("skill"):
        return int(entry["skill"])
    like = int(entry.get("like") or 0)
    return vanilla_magic(like) if like else vanilla_magic(ovl)


def info(fs, mods, ovl):
    """{"id", "name", "desc": [3 lines], "script", "like", "skill", "magic", "banner", "colors", "own_numbers",
    "game"}"""
    ovl = int(ovl)
    t = table_with(fs, mods, TABLE)
    row = next((r for r in t.rows if int(r["id"]) == ovl), None)
    e = merged(mods).get(ovl, {})
    like = int(e["like"]) if "like" in e else (ovl if is_game_overload(ovl) else 0)
    return {"id": ovl, "name": row["name_EN"] if row else "", "game": is_game_overload(ovl),
            "desc": [row[f"desc{n}_EN"] if row else "" for n in (1, 2, 3)],
            "script": int(row["script_id"]) if row else None, "like": like,
            "skill": int(e["skill"]) if e.get("skill") else None, "magic": magic_of(e, ovl) if (e or like) else None,
            "banner": int(e.get("banner") or like or 0), "colors": e.get("colors"),
            "own_numbers": bool(e.get("skill"))}


def create(fs, mod, name, desc=("", "", ""), like=1, own_numbers=False, animation_of=None):
    """a new Overload (id returned) that works like game Overload `like` (0: none -- then it has numbers of its own,
    copied from Overload `animation_of`'s or 107 Comet Disaster's), with the animation of `animation_of` (default
    `like`) as an editable copy later on the Skills page"""
    ovl = next_id(fs, mod)
    like = int(like or 0)
    van, ed = _tables(fs, mod, TABLE)
    src = next((r for r in ed.rows if int(r["id"]) == (like or animation_of or 1)), ed.rows[1])
    r = src.copy()
    r.set("id", ovl)
    _set_text(r, "name", name)
    for n in range(3):
        _set_text(r, f"desc{n + 1}", desc[n] if n < len(desc) else "")
    r.set("script_id", WRAPPER_BASE + ovl)
    ed.rows.append(r)
    _save_table(mod, TABLE, van, ed)
    d = load(mod)
    d["overloads"][str(ovl)] = {"like": like or 0, "banner": like or animation_of or 1}
    save(mod, d)
    if own_numbers or not like:
        give_numbers(fs, mod, ovl, from_ovl=like or animation_of or 107)
    anim = animation_of or like or 1
    root = skills.vanilla_scripts(fs).root_of(skills.OVL_KEY + anim)
    if root:
        skills.assign(mod, skills.OVL_KEY + ovl, root)
    return ovl


def give_numbers(fs, mod, ovl, from_ovl=None):
    """an Overload gets a magic row of its own (copy of from_ovl's, default its current one): its power, effects,
    element and area can then be changed (set_numbers) without touching any other Overload"""
    ovl = int(ovl)
    d = load(mod)
    e = d["overloads"].setdefault(str(ovl), {"like": ovl if is_game_overload(ovl) else 0})
    if e.get("skill"):
        return int(e["skill"])
    src = vanilla_magic(from_ovl) if from_ovl else magic_of(e, ovl)
    new = next_skill(fs, mod)
    van, ed = _tables(fs, mod, MAGIC)
    r = next(x for x in ed.rows if int(x["id"]) == int(src or 3026)).copy()
    r.set("id", new)
    name = info(fs, [mod], ovl)["name"]
    if name:
        _set_text(r, "name", name)
    ed.rows.append(r)
    _save_table(mod, MAGIC, van, ed)
    e["skill"] = new
    if e.get("like") and int(r["formula"]) != 5:
        e["like"] = 0                       # numbers of its own: the special code of the old one doesn't run
    save(mod, d)
    return new


def drop_numbers(fs, mod, ovl):
    """back to the numbers of the Overload it works like (its own magic row is removed)"""
    d = load(mod)
    e = d["overloads"].get(str(int(ovl)))
    if not e or not e.get("skill"):
        return
    van, ed = _tables(fs, mod, MAGIC)
    ed.rows[:] = [r for r in ed.rows if int(r["id"]) != int(e["skill"])]
    _save_table(mod, MAGIC, van, ed)
    e.pop("skill")
    if not e.get("like"):
        e["like"] = int(ovl) if is_game_overload(ovl) else 1
    save(mod, d)


NUMBER_FIELDS = ("formula", "element", "attack_map", "height_up", "height_down", "range", "sp_cost")


def set_numbers(fs, mod, ovl, power=None, effects=None, **fields):
    """change the numbers of an Overload with its own magic row: power % (every level), effects [(type, value)],
    and NUMBER_FIELDS"""
    e = load(mod)["overloads"].get(str(int(ovl)), {})
    if not e.get("skill"):
        raise ValueError("this Overload uses the numbers of the Overload it works like: give it its own first")
    van, ed = _tables(fs, mod, MAGIC)
    r = next(x for x in ed.rows if int(x["id"]) == int(e["skill"]))
    if power is not None:
        for n in range(1, 11):
            r.set(f"power_lv{n}", int(power))
    if effects is not None:
        effects = list(effects)[:6]
        for n in range(6):
            t, v = effects[n] if n < len(effects) else (0, effects[0][1] if effects else 0)
            r.set(f"effect{n + 1}_type", int(t))
            r.set(f"effect{n + 1}_value", int(v))
    for k, v in fields.items():
        if k not in NUMBER_FIELDS:
            raise KeyError(k)
        r.set(k, int(v))
    _save_table(mod, MAGIC, van, ed)


def set_text(fs, mod, ovl, name=None, desc=None):
    van, ed = _tables(fs, mod, TABLE)
    r = next((x for x in ed.rows if int(x["id"]) == int(ovl)), None)
    if r is None:
        raise KeyError(f"no Overload {ovl}")
    if name is not None:
        _set_text(r, "name", name)
    for n, line in enumerate(desc or ()):
        _set_text(r, f"desc{n + 1}", line)
    _save_table(mod, TABLE, van, ed)
    e = load(mod)["overloads"].get(str(int(ovl)), {})
    if name is not None and e.get("skill"):
        van, ed = _tables(fs, mod, MAGIC)
        for x in ed.rows:
            if int(x["id"]) == int(e["skill"]):
                _set_text(x, "name", name)
        _save_table(mod, MAGIC, van, ed)


def set_like(fs, mod, ovl, like):
    """the special code (and, without numbers of its own, the numbers) of game Overload `like` (0: none)"""
    d = load(mod)
    e = d["overloads"].setdefault(str(int(ovl)), {})
    e["like"] = int(like or 0)
    if not e["like"] and not e.get("skill"):
        save(mod, d)
        give_numbers(fs, mod, ovl, from_ovl=int(ovl) if is_game_overload(ovl) else 107)
        return
    if is_game_overload(ovl) and e["like"] == int(ovl) and not e.get("skill") and set(e) <= {"like", "banner"} \
            and int(e.get("banner") or ovl) == int(ovl):
        d["overloads"].pop(str(int(ovl)))
    save(mod, d)


def set_banner(mod, ovl, style=None, colors=None, picture=None):
    """the Overload's title banner: the style (lightning bar, colours) of game Overload `style`, the name's
    gradient colors ((r, g, b) top, (r, g, b) bottom; None: the style's), or a picture of its own (any size: fitted
    to the banner's height; None keeps the current one, "" removes it)"""
    d = load(mod)
    e = d["overloads"].setdefault(str(int(ovl)), {"like": int(ovl) if is_game_overload(ovl) else 0})
    if style is not None:
        e["banner"] = int(style)
    if colors is not None:
        if colors:
            e["colors"] = [list(map(int, c)) for c in colors]
        else:
            e.pop("colors", None)
    save(mod, d)
    if picture is not None:
        import os
        path = picture_path(mod, ovl)
        if picture == "":
            if os.path.exists(path):
                os.remove(path)
        else:
            from PIL import Image
            img = Image.open(picture) if isinstance(picture, str) else picture
            os.makedirs(os.path.dirname(path), exist_ok=True)
            img.convert("RGBA").save(path)


def picture_path(mod, ovl):
    import os
    return os.path.join(mod.patches_dir, FOLDER, f"banner_{int(ovl)}.png")


def banner_picture(text, colors=((75, 116, 220), (170, 177, 229)), font=None, height=BANNER_H, max_width=940):
    """the name drawn like the game's Overload titles: a vertical gradient, a thick black outline and a shadow"""
    import os
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    sc = 2                                                   # drawn at twice the size, then scaled down
    size = 54 * sc
    f = None
    for name in ([font] if font else []) + [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", n)
                                            for n in FONTS]:
        try:
            f = ImageFont.truetype(name, size)
            break
        except (OSError, TypeError):
            continue
    if f is None:
        f = ImageFont.load_default(size)
    text = text or " "
    l, t, r, b = f.getbbox(text)
    ol, sh = 4 * sc, 3 * sc
    W, H = (r - l) + 2 * ol + sh + 8 * sc, height * sc
    mask = Image.new("L", (W, H), 0)
    y0 = (H - (b - t)) // 2 - t - sh // 2
    ImageDraw.Draw(mask).text((ol + 4 * sc - l, y0), text, font=f, fill=255)
    outline = mask.filter(ImageFilter.MaxFilter(2 * ol + 1))
    shadow = Image.new("L", (W, H), 0)
    shadow.paste(outline, (sh, sh))
    rows = [y for y in range(H) if mask.crop((0, y, W, y + 1)).getbbox()]
    top, bot = (rows[0], rows[-1]) if rows else (0, H - 1)
    (r0, g0, b0), (r1, g1, b1) = colors
    grad = Image.new("RGBA", (1, H))
    for y in range(H):
        k = min(1.0, max(0.0, (y - top) / max(1, bot - top)))
        grad.putpixel((0, y), (int(r0 + (r1 - r0) * k), int(g0 + (g1 - g0) * k), int(b0 + (b1 - b0) * k), 255))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.paste((0, 0, 0, 255), (0, 0), shadow.point(lambda v: v * 160 // 255))
    img.paste((0, 0, 0, 255), (0, 0), outline)
    img.paste(grad.resize((W, H)), (0, 0), mask)
    img = img.resize((W // sc, height), Image.LANCZOS)
    if img.width > max_width:
        img = img.resize((max_width, height), Image.LANCZOS)
    return img


def give(fs, mod, char_id, ovl):
    """character / class rank `char_id` gets Overload `ovl` (0: none)"""
    van, ed = _tables(fs, mod, CHAR)
    for r in ed.rows:
        if int(r["id"]) == int(char_id):
            r.set("overload_id", int(ovl))
    _save_table(mod, CHAR, van, ed)


def remove(fs, mod, ovl):
    """delete a new Overload of this mod (its row, numbers, animation; characters having it get none)"""
    ovl = int(ovl)
    if is_game_overload(ovl):
        raise ValueError("a game Overload can't be deleted (Back to vanilla undoes changes)")
    drop = load(mod)
    e = drop["overloads"].pop(str(ovl), {})
    save(mod, drop)
    for member, keep in ((TABLE, lambda r: int(r["id"]) != ovl),
                         (MAGIC, lambda r: not e.get("skill") or int(r["id"]) != int(e["skill"]))):
        van, ed = _tables(fs, mod, member)
        ed.rows[:] = [r for r in ed.rows if keep(r)]
        _save_table(mod, member, van, ed)
    van, ed = _tables(fs, mod, CHAR)
    for r in ed.rows:
        if int(r["overload_id"]) == ovl:
            r.set("overload_id", 0)
    _save_table(mod, CHAR, van, ed)
    sd = skills.load(mod)
    s = sd["skills"].pop(str(skills.OVL_KEY + ovl), None)
    if s and skills.is_custom_choreo(s.get("choreography", 0)):
        root = int(s["choreography"])
        for k in [k for k in sd["events"] if root <= int(k) < root + 1000]:
            sd["events"].pop(k)
    skills.save(mod, sd)


def reset(fs, mod, ovl):
    """undo this mod's changes to a game Overload (text, numbers, works like, banner; the animation stays: the
    Skills page's Back to vanilla removes it)"""
    ovl = int(ovl)
    drop_numbers(fs, mod, ovl)
    d = load(mod)
    d["overloads"].pop(str(ovl), None)
    save(mod, d)
    van, ed = _tables(fs, mod, TABLE)
    vrow = next(r for r in van.rows if int(r["id"]) == ovl)
    for i, r in enumerate(ed.rows):
        if int(r["id"]) == ovl:
            ed.rows[i] = vrow.copy()
    _save_table(mod, TABLE, van, ed)


# ------------------------------------------------------------------------------------------ install
def _handler(ctx, mod, patch_dir):
    import os
    d = load(mod)
    acc = getattr(ctx, "_overloads", {})
    for k, e in d["overloads"].items():
        acc.setdefault(int(k), {}).update(e)
        pic = os.path.join(patch_dir, f"banner_{int(k)}.png")
        if os.path.exists(pic):
            acc[int(k)]["_picture"] = pic
    ctx._overloads = acc
    if d["overloads"]:
        ctx.log(f"  overloads: {len(d['overloads'])} new or changed")


def _hook_shared(entries):
    """find: ecx = Overload id -> rax = its entry {id, magic, like, banner} or 0 (only rax changes)"""
    nl = chr(10)
    rows = [f"    .long {o}, {m}, {a}, {mu}" for o, m, a, mu in entries] + ["    .long 0, 0, 0, 0"]
    return nl.join([
        "    lea rax, [rip + ovl_tbl]",
        "ovl_find:",
        "    cmp dword ptr [rax], 0",
        "    je ovl_none",
        "    cmp dword ptr [rax], ecx",
        "    je ovl_done",
        "    add rax, 16",
        "    jmp ovl_find",
        "ovl_none:",
        "    xor eax, eax",
        "ovl_done:",
        "    ret",
        "    .align 16",
        "ovl_tbl:",
    ] + rows)


def _map_src():
    # 0x1401dd050 entry: ecx = Overload id -> eax = magic id (ret to the caller), else the game's switch
    return chr(10).join([
        "    call {shared}",
        "    test rax, rax",
        "    je orig",
        "    mov eax, dword ptr [rax + 4]",
        "    ret",
        "orig:",
        "    dec ecx",
        "    cmp ecx, 0xd4",
        f"    jmp {MAP_NEXT:#x}",
    ])


def _dispatch_src():
    # 0x140163c6e: ecx = the Overload in use (battle record +0xe60) -> the one it works like
    return chr(10).join([
        "    mov ecx, dword ptr [rax + 0xe60]",
        "    call {shared}",
        "    test rax, rax",
        "    je done",
        "    mov ecx, dword ptr [rax + 8]",
        "done:",
        f"    jmp {DISPATCH_NEXT:#x}",
    ])


def _alias_src():
    # replaces `call GETTER` where the result picks behaviour: eax = the Overload the unit's one works like
    return chr(10).join([
        "    push rcx",
        "    sub rsp, 0x20",
        f"    call {GETTER:#x}",
        "    add rsp, 0x20",
        "    mov ecx, eax",
        "    call {shared}",
        "    test rax, rax",
        "    je keep",
        "    mov eax, dword ptr [rax + 8]",
        "    jmp out",
        "keep:",
        "    mov eax, ecx",
        "out:",
        "    pop rcx",
        "    ret",
    ])


def _banner_src():
    # 0x1404b2ffc: eax = Overload id, ebx = 100 (default banner) -> its banner
    return chr(10).join([
        "    mov ecx, eax",
        "    call {shared}",
        "    test rax, rax",
        "    je orig",
        "    mov ebx, dword ptr [rax + 12]",
        f"    jmp {BANNER_SET:#x}",
        "orig:",
        "    mov eax, ecx",
        "    dec eax",
        "    cmp eax, 0xd4",
        f"    jmp {BANNER_NEXT:#x}",
    ])


def table_entries(exe, overloads, banners=None):
    """[(id, magic id, works like, banner)] for every new or changed Overload (banners: {id: banner value} of the
    ones with a picture of their own)"""
    vmagic, vban = vanilla_tables(exe)
    out = []
    for ovl, e in sorted(overloads.items()):
        like = int(e.get("like") or 0)
        magic = int(e["skill"]) if e.get("skill") else vmagic.get(like or ovl)
        if not magic:
            raise ValueError(f"Overload {ovl}: works like {like}, which has no battle skill")
        style = int(e.get("banner") or like or ovl)
        alias = like or (GENERIC if e.get("skill") else NONE)
        out.append((ovl, magic, alias, (banners or {}).get(ovl) or vban.get(style, DEFAULT_BANNER)))
    return out


def build_patch(exe, overloads, banners=None):
    if SECTION_NAME in exe[:0x400]:
        return exe
    entries = table_entries(exe, overloads, banners)
    hooks = [(MAP_VA, MAP_ORIG, _map_src(), 0xE9), (DISPATCH_VA, DISPATCH_ORIG, _dispatch_src(), 0xE9),
             (BANNER_VA, BANNER_ORIG, _banner_src(), 0xE9)]
    for va in ALIAS_CALLS:
        rel = GETTER - (va + 5)
        hooks.append((va, b"\xE8" + struct.pack("<i", rel), _alias_src(), 0xE8))
    return add_hook_section(exe, SECTION_NAME, hooks, _hook_shared(entries))


def _finalize(ctx):
    ovls = getattr(ctx, "_overloads", {})
    if not ovls:
        return
    t = database.load_table(TABLE, ctx.get(OVL_PATH))
    rows = {int(r["id"]): r for r in t.rows}
    mt = database.load_table(MAGIC, ctx.get(MAGIC_PATH))
    magic_ids = {int(r["id"]) for r in mt.rows}
    for ovl, e in ovls.items():
        if ovl not in rows:
            raise ValueError(f"Overload {ovl}: no OverlordSkill.dat row (a mod lists it but doesn't add it)")
        if e.get("skill") and not (SKILL_FIRST <= int(e["skill"]) <= SKILL_LAST and int(e["skill"]) in magic_ids):
            raise ValueError(f"Overload {ovl}: skill {e['skill']} must be a magic.dat row {SKILL_FIRST}-{SKILL_LAST}")
    # every Overload's events exist (a new one without an animation of its own plays the one it works like)
    sf = ctx.parsed(skills.SCRIPT, script.ScriptFile.from_bytes)
    have = {ev.id for ev in sf.events}
    van = database.load_table(TABLE, ctx.fs.read(OVL_PATH))
    vscript = {int(r["id"]): int(r["script_id"]) for r in van.rows}
    extra = {}
    for ovl in ovls:
        w = int(rows[ovl]["script_id"])
        like = int(ovls[ovl].get("like") or 0)
        if w not in have:
            body = f"    call_event {vscript.get(like or 1, 13200000)}\n    wait_children\n"
            extra[str(w)] = f"event {w}\n" + body
        if w + SHORT not in have:
            extra[str(w + SHORT)] = f"event {w + SHORT}\n" + skills.OVL_SHORT_BODY
    if extra:
        from . import scriptpatch
        scriptpatch.apply(sf, {"events": extra})
        ctx.changed(skills.SCRIPT, script.ScriptFile.to_bytes)
    t.rows.sort(key=lambda r: int(r["id"]))
    ctx.put(OVL_PATH, t.to_bytes())
    banners = _add_banners(ctx, ovls, rows, {int(r["id"]): r for r in van.rows})
    ctx.put(EXE_FILE, build_patch(ctx.get(EXE_FILE), ovls, banners))
    new = sorted(o for o in ovls if not is_game_overload(o))
    ctx.log(f"  Overloads: {len(new)} new, {len(ovls) - len(new)} game one(s) changed "
            f"({sum(1 for e in ovls.values() if e.get('skill'))} with numbers of their own)")


def needs_banner(ovl, e, row, vrow):
    """a new Overload, a renamed game one, or one with banner colours or a picture of its own"""
    if vrow is None or e.get("_picture") or e.get("colors"):
        return True
    return any(row[f"name_{L}"] != vrow[f"name_{L}"] for L in ("EN", "JP"))


def _add_banners(ctx, ovls, rows, vrows):
    """title banners of their own (both languages' resident packs) -> {Overload id: banner value}"""
    from PIL import Image
    from . import facepatch
    exe = ctx.get(EXE_FILE)
    _, vban = vanilla_tables(exe)
    todo = [o for o in sorted(ovls) if needs_banner(o, ovls[o], rows[o], vrows.get(o))]
    if not todo:
        return {}
    values = {o: NEW_BANNERS + 2 * k for k, o in enumerate(todo)}
    for vp, lang in zip(RESIDENT, ("JP", "EN")):
        items = []
        for o in todo:
            e = ovls[o]
            style = int(e.get("banner") or e.get("like") or (o if is_game_overload(o) else 1))
            tmpl = vban.get(style, DEFAULT_BANNER)
            if e.get("_picture"):
                img = Image.open(e["_picture"]).convert("RGBA")
                img = img.resize((max(1, round(img.width * BANNER_H / img.height)), BANNER_H), Image.LANCZOS)
                if img.width > 940:
                    img = img.resize((940, BANNER_H), Image.LANCZOS)
            else:
                colors = e.get("colors") or BANNER_COLORS.get(style) or BANNER_COLORS[1]
                img = banner_picture(rows[o][f"name_{lang}"] or rows[o]["name_EN"], colors)
            items.append((values[o], tmpl, img))
        k = vp.lower()                    # the LZS pack as is (an earlier finalizer's, e.g. outfits' faces)
        raw = ctx.outputs[k][1] if k in ctx.outputs else ctx.fs.read_raw(vp)
        ctx.put(vp, facepatch.add_overload_banners(raw, items))
    ctx.log(f"  Overload title banners: {len(todo)} of their own")
    return values


register_patch_handler(FOLDER, _handler, order=47)
register_finalizer(_finalize)
