"""Character voices: which voice a character, class or monster speaks with, and new voices made from your own
recordings.

How the game picks a voice line (disgaea5.exe):
  voice set  = kind * 100000 + char.dat voice_id * 10 + personality                      (0x1401602c0)
               personality = the unit's byte +0x2e26: 0-2 for generic classes (chosen when the unit is created),
               0 for story characters.  A few story voice ids switch to another one later in the story.
  kinds      0 = battle (situations 0-21; the skill animation command voice_play_actor always uses kind 0),
             1-3 = other situations the game itself triggers (22-28 / 29-30 / 0-2, 20, 21, 31-33)
  line       = a random row of the line table (Database Sound_Voice_EN_0.dat or _JP_0.dat, by the voice language)
               whose group is the voice set and whose flag of the situation is set                  (0x140226c00)
  sound      = file '%09d.vag' % line id in pack 'voice_en/%06d.dat' % group ('voice_jp/' for Japanese) of
               Data/Sound_Voice/Sound_Voice_0.dat (d5lib.fafs)
Line table row (48 bytes): u32 line id (= group * 1000 + n), u32 group, u16 volume (%), 34 x u8 situation flags
(+0x0a + situation), 4 bytes kept as they are (+0x2c).

Another character's voice: set char.dat voice_id to theirs (every tier row of a class).  Story characters have one
personality only, so a generic class given a story character's voice needs a custom voice (copies for the three
personalities) -- voice_for() makes one.

A custom voice is a new voice id (CUSTOM_FIRST..CUSTOM_LAST) kept in a mod: patches/voices/voices.json + the line
files next to it.  It starts as a copy of an existing voice's lines (all four kinds); any line can be replaced by a
recording, removed, or added.  The build writes its line table rows (EN and JP) and packs (voice_en/ and voice_jp/,
every kind, personalities 0-2; lines copied from a voice keep that voice's English / Japanese audio).

voices.json: {"voices": {"9000": {"name": ..., "template": [voice id, personality],
                                  "tail": "01000400",
                                  "lines": [{"kind": 0, "cats": [0, 10], "volume": 70, "src": 400001},
                                            {"kind": 0, "cats": [1], "volume": 80, "file": "9000_0007.vag"}]}}}
"""
import json
import os
import struct
from collections import defaultdict

from . import fafs, sound
from .modsys import register_patch_handler

ARCHIVE = "Sound_Voice/Sound_Voice_0.dat"
TABLES = {"EN": "Database/Database_0.dat/Sound_Voice_EN_0.dat", "JP": "Database/Database_0.dat/Sound_Voice_JP_0.dat"}
PREFIX = {"EN": "voice_en", "JP": "voice_jp"}
ROW = 48
SITUATIONS = 34
KINDS = 4
PERSONALITIES = 3
CUSTOM_FIRST, CUSTOM_LAST = 6000, 9999      # the game's ids end at 5321; voice set = kind x 100000 + id x 10 (< 10000)
CUSTOM_ORDER = list(range(9000, 10000)) + list(range(CUSTOM_FIRST, 9000))     # handed out from 9000 first
STORY_SWITCH = {10, 40, 50, 60, 70, 100, 130, 530, 570, 710}    # voice ids the game may swap (story progress)
FOLDER = "voices"
FILE = "voices.json"
DEFAULT_TAIL = "01000400"
DEFAULT_VOLUME = 70

KIND_NAMES = {0: "Battle", 1: "Kind 1", 2: "Kind 2", 3: "Kind 3"}
KIND_HELP = {
    0: "Battle lines (situations 0-21). Skill animations play these: a skill's script names the situation.",
    1: "Lines the game triggers itself (situations 22-28; 22 has most of a voice's lines).",
    2: "Lines the game triggers itself (situations 29-30; a voice has 1-4 of them).",
    3: "Lines the game triggers itself (situations 0-2, 20, 21, 31-33).",
}


def set_of(kind, voice_id, personality=0):
    return kind * 100000 + int(voice_id) * 10 + personality


def split_set(group):
    """voice set -> (kind, voice id, personality)"""
    return group // 100000, group % 100000 // 10, group % 10


# ------------------------------------------------------------------------------------------ line table
class Line:
    __slots__ = ("id", "group", "volume", "cats", "tail")

    def __init__(self, id, group, volume=DEFAULT_VOLUME, cats=(), tail=DEFAULT_TAIL):
        self.id, self.group, self.volume = int(id), int(group), int(volume)
        self.cats = sorted(set(int(c) for c in cats if 0 <= int(c) < SITUATIONS))
        self.tail = tail

    @classmethod
    def parse(cls, row):
        i, g, vol = struct.unpack_from("<IIH", row, 0)
        return cls(i, g, vol, [c for c in range(SITUATIONS) if row[0xA + c]], row[0x2C:0x30].hex())

    def pack(self):
        flags = bytes(1 if c in self.cats else 0 for c in range(SITUATIONS))
        return struct.pack("<IIH", self.id, self.group, self.volume) + flags + bytes.fromhex(self.tail)


def read_table(data):
    n = struct.unpack_from("<I", data)[0]
    return [Line.parse(data[4 + ROW * k:4 + ROW * (k + 1)]) for k in range(n)]


def write_table(lines):
    lines = sorted(lines, key=lambda l: l.id)       # the game looks rows up by id with a binary search
    return struct.pack("<I", len(lines)) + b"".join(l.pack() for l in lines)


class Catalog:
    """the voices of the game (line table + char.dat): which voice ids exist, whose they are, their lines"""

    def __init__(self, get, char_rows=(), lang="EN"):
        self.lines = read_table(get(TABLES[lang]))
        self.by_group = defaultdict(list)
        for l in self.lines:
            self.by_group[l.group].append(l)
        self.ids = sorted({split_set(g)[1] for g in self.by_group})
        self.owners = defaultdict(list)                 # voice id -> ["Killia", ...]
        for r in char_rows:
            try:
                v, name = int(r["voice_id"]), r["name_EN"]
            except (KeyError, TypeError, ValueError):
                continue
            if name and name not in self.owners[v]:
                self.owners[v].append(name)

    def personalities(self, vid):
        return sorted({p for p in range(10) if any(set_of(k, vid, p) in self.by_group for k in range(KINDS))})

    def lines_of(self, vid, personality=0, kind=None):
        ks = range(KINDS) if kind is None else [kind]
        return [l for k in ks for l in self.by_group.get(set_of(k, vid, personality), [])]

    def label(self, vid):
        names = self.owners.get(vid) or []
        if vid >= CUSTOM_FIRST and not names:
            names = ["custom voice"]
        who = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "") if names else "unused"
        return f"{who}  (voice {vid})"


# ------------------------------------------------------------------------------------------ mod data
def folder(mod):
    return os.path.join(mod.patches_dir, FOLDER)


def load(mod):
    p = os.path.join(folder(mod), FILE)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("voices", {})
        return d
    return {"voices": {}}


def save(mod, data):
    os.makedirs(folder(mod), exist_ok=True)
    p = os.path.join(folder(mod), FILE)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(p + ".tmp", p)
    used = {ln.get("file") for v in data["voices"].values() for ln in v.get("lines", []) if ln.get("file")}
    for fn in os.listdir(folder(mod)):                  # recordings no line uses any more
        if fn.lower().endswith(".vag") and fn not in used:
            try:
                os.remove(os.path.join(folder(mod), fn))
            except OSError:
                pass


def used_voice_ids(mods, catalog=None):
    used = set(catalog.ids) if catalog else set()
    for m in mods:
        used |= {int(v) for v in load(m)["voices"]}
    return used


def free_voice_id(mods, catalog=None):
    used = used_voice_ids(mods, catalog)
    for v in CUSTOM_ORDER:
        if v not in used:
            return v
    raise RuntimeError("no free custom voice id left")


def new_voice(catalog, mod, mods, name, template, personality=0):
    """a custom voice copying voice `template` (personality `personality`): returns its id (saved in the mod)"""
    vid = free_voice_id(mods, catalog)
    lines = []
    tails = defaultdict(int)
    for l in catalog.lines_of(template, personality):
        lines.append({"kind": split_set(l.group)[0], "cats": l.cats, "volume": l.volume, "src": l.id})
        tails[l.tail] += 1
    data = load(mod)
    data["voices"][str(vid)] = {"name": name, "template": [int(template), int(personality)],
                                "tail": max(tails, key=tails.get) if tails else DEFAULT_TAIL, "lines": lines}
    save(mod, data)
    return vid


def import_line(mod, vid, path, normalize=True, trim=True):
    """an audio file -> a line file of custom voice `vid` in the mod; returns its file name"""
    from . import sfx
    a, rate = sfx.load_audio(path)
    if not len(a):
        raise ValueError("the file has no sound")
    vag = sfx.make_vag(a, rate, normalize, trim)
    os.makedirs(folder(mod), exist_ok=True)
    k = 1
    while os.path.exists(os.path.join(folder(mod), f"{vid}_{k:04d}.vag")):
        k += 1
    fn = f"{vid}_{k:04d}.vag"
    with open(os.path.join(folder(mod), fn), "wb") as f:
        f.write(vag)
    return fn


def voice_for(catalog, mod, mods, source, is_class, name):
    """the voice id a character should get to speak with voice `source`: `source` itself, or (a generic class
    given a voice with fewer than three personalities) a custom voice copying it for all three"""
    if not is_class or len(catalog.personalities(source)) >= PERSONALITIES or source >= CUSTOM_FIRST:
        return source
    return new_voice(catalog, mod, mods, name, source, catalog.personalities(source)[0]
                     if catalog.personalities(source) else 0)


# ------------------------------------------------------------------------------------------ build
def custom_lines(vid, voice):
    """[(Line, source)] of a custom voice, every kind and personality; source = ('src', line id) or ('file', name)"""
    out = []
    tail = voice.get("tail") or DEFAULT_TAIL
    for p in range(PERSONALITIES):
        n = defaultdict(int)
        for ln in voice.get("lines", []):
            k = int(ln.get("kind", 0))
            if not 0 <= k < KINDS or not (ln.get("file") or ln.get("src")):
                continue
            n[k] += 1
            g = set_of(k, vid, p)
            line = Line(g * 1000 + n[k], g, ln.get("volume", DEFAULT_VOLUME), ln.get("cats", []),
                        ln.get("tail") or tail)
            out.append((line, ("file", ln["file"]) if ln.get("file") else ("src", int(ln["src"]))))
    return out


def _vanilla_line(get, lang, line_id, group, cache):
    pack = f"{ARCHIVE}/{PREFIX[lang]}/{group:06d}.dat"
    if pack not in cache:
        try:
            cache[pack] = fafs.pack_members(get(pack))
        except (KeyError, ValueError, OSError):
            cache[pack] = {}
    return cache[pack].get(f"{line_id:09d}.vag")


def _handler(ctx, mod, pdir):
    data = load(mod)
    if not data["voices"]:
        return
    mine = {set_of(k, int(v), p) for v in data["voices"] for k in range(KINDS) for p in range(PERSONALITIES)}
    for lang in ("EN", "JP"):
        table = read_table(ctx.get(TABLES[lang]))
        group_of = {l.id: l.group for l in table}
        table = [l for l in table if l.group not in mine]   # a later mod's voice with the same id replaces it
        packs = defaultdict(dict)
        cache = {}
        for vid, voice in data["voices"].items():
            for line, (kind, ref) in custom_lines(int(vid), voice):
                if kind == "file":
                    p = os.path.join(pdir, ref)
                    if not os.path.exists(p):
                        ctx.log(f"  warning: voice {vid}: missing line file {ref}")
                        continue
                    with open(p, "rb") as f:
                        audio = f.read()
                else:
                    audio = _vanilla_line(ctx.get, lang, ref, group_of.get(ref, ref // 1000), cache)
                    if audio is None:
                        ctx.log(f"  warning: voice {vid}: line {ref} not found ({lang})")
                        continue
                packs[line.group][f"{line.id:09d}.vag"] = audio
                table.append(line)
        ctx.put(TABLES[lang], write_table(table))
        for g, files in packs.items():
            ctx.put(f"{ARCHIVE}/{PREFIX[lang]}/{g:06d}.dat", fafs.build_pack(files))
    ctx.log(f"  voices: {len(data['voices'])} custom voice(s)")


register_patch_handler(FOLDER, _handler, order=50)


# ------------------------------------------------------------------------------------------ preview
class VoiceBank:
    """voice lines for the kit's previews: the game's (as the mods change them: custom voices included), decoded on
    first use.  pick() chooses the line a voice_play_actor would play."""

    def __init__(self, fs, mods=(), lang="EN", get=None):
        self.fs, self.lang = fs, lang
        self.get_db = get or fs.read
        self.cache = {}
        self.packs = {}
        try:
            self.lines = read_table(self.get_db(TABLES[lang]))
        except Exception:
            self.lines = []
        self.custom = {}                                # line id -> path of a recording / vanilla line id
        for m in mods:
            for vid, voice in load(m)["voices"].items():
                for line, (kind, ref) in custom_lines(int(vid), voice):
                    self.custom[line.id] = os.path.join(folder(m), ref) if kind == "file" else ref
                    self.lines.append(line)
        self.by_group = defaultdict(list)
        self.group_of = {}
        seen = set()
        for l in reversed(self.lines):
            if l.id in seen:
                continue
            seen.add(l.id)
            self.by_group[l.group].append(l)
            self.group_of[l.id] = l.group
        for g in self.by_group:
            self.by_group[g].sort(key=lambda l: l.id)

    def lines_in(self, group, category=None):
        return [l.id for l in self.by_group.get(group, []) if category is None or category in l.cats]

    def _raw(self, line_id):
        ref = self.custom.get(line_id)
        if isinstance(ref, str):
            with open(ref, "rb") as f:
                return f.read()
        if ref is not None:
            line_id = ref
        group = self.group_of.get(line_id, line_id // 1000)
        pack = f"{ARCHIVE}/{PREFIX[self.lang]}/{group:06d}.dat"
        if pack not in self.packs:
            try:
                self.packs[pack] = fafs.pack_members(self.fs.read_raw(pack))
            except Exception:
                self.packs[pack] = {}
        return self.packs[pack].get(f"{line_id:09d}.vag")

    def get(self, line_id):
        """(mono float32 array, rate) or None"""
        line_id = int(line_id)
        if line_id not in self.cache:
            pcm = None
            try:
                raw = self._raw(line_id)
                if raw:
                    from .sfx import decode_msadpcm
                    a, rate = decode_msadpcm(sound.parse_se(raw)["wav"])
                    pcm = (a.mean(axis=1) if a.ndim == 2 else a, rate)
            except (ValueError, struct.error, OSError):
                pcm = None
            self.cache[line_id] = pcm
        return self.cache[line_id]

    def get_file(self, path):
        from .sfx import decode_msadpcm
        with open(path, "rb") as f:
            a, rate = decode_msadpcm(sound.parse_se(f.read())["wav"])
        return (a.mean(axis=1) if a.ndim == 2 else a, rate)

    def pick(self, voice_id, v, seed=0, personality=0, kind=0):
        """the line `voice_play_actor v` plays for a character with char.dat voice_id (deterministic here)"""
        if not voice_id:
            return None
        cat = int(v) // 10000
        for p in (personality, 0):
            ls = self.lines_in(set_of(kind, voice_id, p), cat)
            if ls:
                return ls[seed % len(ls)]
        return None
