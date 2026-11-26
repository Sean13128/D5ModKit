"""Disgaea 4 Complete+ (PC) source data: read-only readers used to import D4 classes into D5.

Reads the user's own D4 install; nothing here copies game data into the repository.  Every layout below was
read from the actual files and cross-checked across classes (see docs/D4_IMPORT.md for the evidence and what is
still unknown).  Readers return plain dicts/lists so importers and the inspection tool share one source of truth.

Files (relative to the D4 install folder):
  Data/DATA/<LANG>/DATABASE_<LANG>.dat   NSAC v2 archive: char.dat, mskill.dat (evilities), magic.dat (skills) ...
  Data/SOUND/<LANG>/voice.dat            FAFS pack (d5lib.fafs): en/<group>/voice_<line>.nlsd = 28-byte header + RIFF
                                         MS-ADPCM mono (rate per line, ~22 kHz); readable by d5lib.sfx.read_wav as is
  Data/SOUND/SoundData_Voice_<LANG>.dat  voice line table: 12-byte header {u32 row size 64, u32 count, u32 0},
                                         rows {u32 line, u32 group, f32 gain, s32 rate input, 12 x u32 categories}
"""
from __future__ import annotations

import json
import math
import os
import re
import struct
from pathlib import Path

DATABASE = "Data/DATA/{lang}/DATABASE_{lang}.dat"
ANM_PACK = "Data/DATA/ANM_HI.dat"       # NSAC: anmNNNNN.lzs (LZS, decoded by d5lib.gamefs.decode_member)
HELP_STRIDE, HELP_LINE = 386, 128      # charhelp.dat: u16 id, then three 128-byte text lines
VOICE_PACK = "Data/SOUND/{lang}/voice.dat"
VOICE_TABLE = "Data/SOUND/SoundData_Voice_{lang}.dat"

CHAR_STRIDE = 0x2AC          # char.dat: u32 count, rows of 684 bytes
EVILITY_STRIDE = 212         # mskill.dat: u32 count, rows of 212 bytes
SKILL_STRIDE = 356           # magic.dat: u32 count, rows of 356 bytes
VOICE_FLAGS = 13             # legacy raw-dword interface; includes rate input at index 0
VOICE_CATEGORIES = 12        # native category flags at row +16, indexed 0..11
VOICE_STRIDE = 64
STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")
NATIVE_TO_CANONICAL = (0, 1, 2, 3, 4, 7, 6, 5)   # D4 stores HP SP ATK DEF INT SPD HIT RES

# char.dat row layout (offset, struct format).  Confidence: "high" = value matches the wiki and stays consistent
# across all classes; "medium" = consistent across classes, meaning inferred from D5's equivalent field.
CHAR_LAYOUT = {
    "base":            (0x004, "8H",  "high"),    # native order, see NATIVE_TO_CANONICAL
    "learn_skill":     (0x014, "16H", "high"),    # magic.dat ids (Armor Knight 13081 Lift Catch, 13082 Legit Shield)
    "learn_level":     (0x034, "16H", "high"),    # levels (10, 20: as the wiki)
    "weapon_skills":   (0x094, "16H", "medium"),  # weapon skills: code - 10000 = magic.dat id (10301 -> 301 Impaler Drop)
    "weapon_skill_thresholds": (0x114, "16H", "medium"),  # parallel learning thresholds (unit not established)
    "id":              (0x194, "H",   "high"),
    "sprite":          (0x196, "H",   "high"),
    "height":          (0x19A, "H",   "medium"),
    "help_id":         (0x19E, "H",   "medium"),
    "color_id":        (0x1A0, "H",   "medium"),
    "grade":           (0x1A2, "H",   "medium"),  # D5 unk_0E0
    "MOV":             (0x1A4, "H",   "medium"),  # Thief 6, Ninja 5, Armor Knight 3, Magician 3
    "move_type":       (0x1A6, "H",   "medium"),  # 1 for flyers (Masked Hero, Succubus, Death ...)
    "attack_range":    (0x1A8, "H",   "medium"),  # Succubus 4, Rifle Demon 5
    "hl_value":        (0x1AA, "H",   "medium"),
    "exp_value":       (0x1AC, "H",   "medium"),
    "rank_bonus":      (0x1B0, "H",   "medium"),  # 10 + 3 per rank (D5 unk_0EE)
    "mana_value":      (0x1B2, "H",   "medium"),  # 100, 85, 70 ... per rank (D5 mana_value)
    "innate_evility":  (0x1B4, "H",   "high"),    # mskill.dat id (Armor Knight 392 Aegis)
    "magichange":      (0x1B8, "H",   "medium"),
    "body":            (0x1BA, "H",   "high"),    # legacy key: voice-group base, NOT necessarily the art sprite (+0x196)
    "evility_list":    (0x1BE, "16H", "high"),    # learnable evilities at this rank (grows with rank, as the wiki)
    "evility_flags":   (0x1DE, "16H", "medium"),  # 1 per used entry of evility_list
    "name":            (0x1FE, "64s", "high"),
    "title":           (0x23E, "64s", "high"),
    "aptitudes":       (0x27E, "8B",  "high"),    # native order
    "res_fire":        (0x28E, "b",   "medium"),  # D4 has three elements
    "res_wind":        (0x28F, "b",   "medium"),
    "res_ice":         (0x290, "b",   "medium"),
    "kind_gender":     (0x292, "B",   "high"),    # same codes as D5: 11/12 human male/female, 21/22 monster
    "tier":            (0x294, "B",   "high"),
    "JMP":             (0x296, "B",   "high"),    # Ninja 35, Thief/Archer 25, Armor Knight 15
    "body_type":       (0x298, "B",   "high"),    # original native0x1401aef10: independent humanoid0/monster1 discriminator
    "throw":           (0x299, "B",   "medium"),  # Magician 3 (as D5), Armor Knight 6 ("high throwing power")
    "counter":         (0x29A, "B",   "medium"),  # Magician 0 (as D5)
    "category":        (0x29B, "B",   "medium"),  # D5 unk_381 (Healer 7 = D5 Clergy 7)
    "crit":            (0x29D, "B",   "medium"),  # grows with rank (Armor Knight 6 -> 12)
}

# D4 field -> D5 char.dat field, applied as "source battle profile" by importers.  D4 has no Star element, no
# per-class weapon mastery letters and no weapon-type resistances: those stay the D5 template's (documented).
D5_BATTLE_FIELDS = ("MOV", "move_type", "attack_range", "JMP", "throw", "counter", "crit",
                    "res_fire", "res_wind", "res_ice", "kind_gender", "body_type")


class Nsac:
    """NSAC v2 archive (D4 DATABASE_*.dat): {member name: (offset, size)}; read(name) -> bytes"""

    def __init__(self, path):
        self.path = Path(path)
        size = self.path.stat().st_size
        with self.path.open("rb") as f:
            head = f.read(28)
            magic, version, count, declared, data_at, index_size, names_size, _ = struct.unpack("<4sHH5I", head)
            if magic != b"NSAC" or version != 2 or declared != size or index_size != count * 10:
                raise ValueError(f"not a D4 NSAC v2 archive: {self.path}")
            f.read(index_size)
            names = f.read(names_size)
        self.members, pos = {}, 0
        for _ in range(count):
            name_size, offset, length = struct.unpack_from("<HII", names, pos)
            pos += 10
            name = names[pos:pos + name_size].decode("ascii")
            pos += name_size + 1
            if offset < data_at or offset + length > size:
                raise ValueError(f"member {name} outside the archive")
            self.members[name] = (offset, length)

    def read(self, name):
        offset, length = self.members[name]
        with self.path.open("rb") as f:
            f.seek(offset)
            return f.read(length)


def _rows(data, stride):
    n = struct.unpack_from("<I", data, 0)[0]
    if 4 + n * stride != len(data):
        raise ValueError(f"table size {len(data)} is not 4 + {n} x {stride}")
    return [data[4 + i * stride: 4 + (i + 1) * stride] for i in range(n)]


def _texts(raw):
    return [t.decode("ascii", "replace") for t in re.findall(rb"[\x20-\x7e]{3,}", raw)]


def decode_voice_table(data):
    """Strict D4 voice rows; legacy flags are raw indices, never native categories.

    Native selection tests row+16+4*category. Row+12 is a signed integer
    playback-rate input, separately multiplied/truncated by the native player.
    Keep the old 13-dword/flags interface for callers holding earlier evidence.
    """
    if len(data) < 12:
        raise ValueError("truncated D4 voice table header")
    size, count, reserved = struct.unpack_from("<III", data)
    if size != VOICE_STRIDE or len(data) != 12 + count * size:
        raise ValueError("D4 voice table must contain exactly count x 64-byte rows")
    rows = {}
    for index in range(count):
        row = data[12 + index * size:12 + (index + 1) * size]
        line, group, gain, *raw = struct.unpack("<IIf13I", row)
        if line in rows:
            raise ValueError(f"duplicate D4 voice table line {line}")
        if not math.isfinite(gain):
            raise ValueError(f"non-finite D4 voice gain for line {line}")
        legacy = [i for i, value in enumerate(raw) if value]
        rows[line] = dict(group=group, volume=round(gain, 1), volume_raw=gain,
                          flags=legacy, legacy_flags=list(legacy), legacy_raw_dwords=raw,
                          flags_semantics="legacy raw dword indices at row+12; index0 is rate input, not an event",
                          native_rate_input_signed=struct.unpack_from("<i", row, 12)[0],
                          native_category_flags=raw[1:],
                          native_active_categories=[i for i, value in enumerate(raw[1:]) if value],
                          table_row_index=index, table_header_reserved=reserved)
    return rows


def decode_voice_member(raw):
    """Validate the original 28-byte wrapper and RIFF extents without converting audio."""
    if len(raw) < 40:
        raise ValueError("truncated D4 voice wrapper/RIFF")
    header = struct.unpack_from("<7I", raw)
    riff = raw[28:]
    if (header[0] != 5 or header[1] != len(riff) or header[5] != len(riff)
            or not header[2] or header[4] or header[6]):
        raise ValueError("invalid D4 voice wrapper fields/extents")
    if riff[:4] != b"RIFF" or riff[8:12] != b"WAVE" or struct.unpack_from("<I", riff, 4)[0] + 8 != len(riff):
        raise ValueError("invalid D4 voice RIFF header/extent")
    pos, fmt, audio = 12, None, None
    while pos + 8 <= len(riff):
        tag, size = struct.unpack_from("<4sI", riff, pos)
        end = pos + 8 + size
        if end + (size & 1) > len(riff):
            raise ValueError("truncated D4 voice RIFF chunk")
        if tag == b"fmt ":
            if fmt is not None or size < 16:
                raise ValueError("invalid/duplicate D4 voice fmt chunk")
            fmt = riff[pos + 8:end]
        elif tag == b"data":
            if audio is not None:
                raise ValueError("duplicate D4 voice data chunk")
            audio = size
        pos = end + (size & 1)
    if pos != len(riff) or fmt is None or audio is None:
        raise ValueError("missing or malformed D4 voice RIFF chunks")
    codec, channels, rate, _, align, bits = struct.unpack_from("<HHIIHH", fmt)
    if not channels or not rate or not align or not bits:
        raise ValueError("invalid D4 voice fmt fields")
    return dict(riff=riff, wrapper_hex=raw[:28].hex(), wrapper_u32=list(header),
                riff_codec=codec, riff_channels=channels, riff_sample_rate=rate)


def decode_char(row):
    """one D4 char.dat row -> dict of CHAR_LAYOUT fields (+ canonical base/aptitudes, learnset, evilities)"""
    out = {}
    for name, (off, fmt, _) in CHAR_LAYOUT.items():
        v = struct.unpack_from("<" + fmt, row, off)
        if fmt.endswith("s"):
            v = v[0].split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        elif len(v) == 1:
            v = v[0]
        out[name] = v if not isinstance(v, tuple) else list(v)
    out["base"] = [out["base"][k] for k in NATIVE_TO_CANONICAL]
    out['art_sprite'] = out['sprite']
    out['voice_group_base'] = out['body']
    out["aptitudes"] = [out["aptitudes"][k] for k in NATIVE_TO_CANONICAL]
    out["learnset"] = [(s, l) for s, l in zip(out.pop("learn_skill"), out.pop("learn_level")) if s]
    flags = out.pop("evility_flags")
    out["evilities"] = [e for e, f in zip(out.pop("evility_list"), flags) if e and f]
    out["weapon_skills"] = [s for s in out["weapon_skills"] if s]
    out["battle"] = {k: out[k] for k in D5_BATTLE_FIELDS}
    return out


VERIFIED_SET_ENV = "D5_D4_VERIFIED_SET"


def _verified_locate(root):
    """The verified source set's ``path`` when ``D5_D4_VERIFIED_SET`` names the set a parent import resolved for
    this same ``root`` (a child builder process reads D4 only through it), else None."""
    config = os.environ.get(VERIFIED_SET_ENV)
    if not config:
        return None
    try:
        doc = json.loads(Path(config).read_text())
    except (OSError, ValueError):
        raise ValueError(f"{VERIFIED_SET_ENV} names an unreadable verified-set file: {config}")
    if Path(doc.get("root", "")).resolve() != Path(root).resolve():
        return None
    from .importers import _d4_source
    return _d4_source.D4Files.from_config(doc).path


class D4Data:
    """the D4 tables an importer needs, read once from an install folder"""

    def __init__(self, root, lang="EN", locate=None):
        """``locate(relative path) -> Path`` is the only way this reader finds a file when given (the importer
        passes the verified source set's ``path``, which refuses a file the manifest does not list); without it
        the relative names below are joined onto ``root``."""
        self.root = Path(root)
        self.lang = lang
        self._locate = locate if locate is not None else _verified_locate(self.root)
        self.db = Nsac(self._file(DATABASE.format(lang=lang)))
        self._chars = self._evilities = self._skills = None

    def _file(self, rel):
        locate = getattr(self, "_locate", None)
        return Path(locate(rel)) if locate else self.root / rel

    @property
    def chars(self):
        if self._chars is None:
            self._chars = {}
            for row in _rows(self.db.read("char.dat"), CHAR_STRIDE):
                c = decode_char(row)
                self._chars.setdefault(c["id"], c)
        return self._chars

    @property
    def evilities(self):
        """{id: {name, desc, mana, value}} from mskill.dat.  value = byte +13, the number the description's %d shows
        (all 432 rows with a %d have one; Aegis 30, Advance Guard 80, ...: Codex character BOM, re-checked here)"""
        if self._evilities is None:
            self._evilities = {}
            for r in _rows(self.db.read("mskill.dat"), EVILITY_STRIDE):
                t = _texts(r[12:])
                self._evilities[struct.unpack_from("<H", r, 8)[0]] = dict(
                    mana=struct.unpack_from("<I", r, 0)[0], value=r[13], name=t[0] if t else "",
                    desc=" ".join(t[1:2]))
        return self._evilities

    @property
    def skills(self):
        """{id: {name, desc}} from magic.dat (id u32 +40, description +56, name +184)"""
        if self._skills is None:
            self._skills = {}
            for r in _rows(self.db.read("magic.dat"), SKILL_STRIDE):
                sid = struct.unpack_from("<I", r, 40)[0]
                desc = r[56:184].split(b"\0", 1)[0].decode("ascii", "replace")
                name = r[184:248].split(b"\0", 1)[0].decode("ascii", "replace")
                self._skills[sid] = dict(name=name, desc=desc)
        return self._skills

    def family(self, first_id, ranks=6):
        """the rank rows of a class (first_id .. first_id + ranks - 1), each decoded"""
        return [self.chars[first_id + k] for k in range(ranks)]

    def class_profile(self, first_id, ranks=6):
        """everything an importer maps for one class: per-rank battle fields, innate + rank evilities, learnset"""
        rows = self.family(first_id, ranks)
        ev = self.evilities
        sk = self.skills
        out = []
        for r in rows:
            out.append(dict(id=r["id"], name=r["name"], title=r["title"], tier=r["tier"], base=r["base"],
                            aptitudes=r["aptitudes"], battle=r["battle"],
                            innate_evility=dict(id=r["innate_evility"], **ev.get(r["innate_evility"], {})),
                            evilities=[dict(id=e, **ev.get(e, {})) for e in r["evilities"]],
                            skills=[dict(id=s, level=l, **sk.get(s, {})) for s, l in r["learnset"]]))
        return out

    def help_lines(self, help_id):
        """the three lines of a class / character description (charhelp.dat), or [] if none"""
        for r in _rows(self.db.read("charhelp.dat"), HELP_STRIDE):
            if struct.unpack_from("<H", r, 0)[0] == help_id:
                return [r[2 + n * HELP_LINE: 2 + (n + 1) * HELP_LINE].split(b"\0", 1)[0].decode("utf-8", "replace")
                        for n in range(3)]
        return []

    def personality_rows(self, first_id):
        """Every stored source variant, including classes with more than three."""
        found = {}
        for row in _rows(self.db.read('charPersonal.dat'), 70):
            _, group, variant = struct.unpack_from('<HHB', row)
            if group != first_id // 10:
                continue
            if variant in found:
                raise ValueError('Ambiguous D4 personality variant')
            found[variant] = row[5:].split(b'\0', 1)[0].decode('utf-8', 'strict')
        return [dict(variant=k, name=found[k]) for k in sorted(found)]

    def personality_names(self, first_id, variants=None):
        """Three explicit D5 choices; do not silently truncate extra source rows."""
        found = {r['variant']: r['name'] for r in self.personality_rows(first_id)}
        variants = sorted(found) if variants is None else list(variants)
        if len(variants) != 3 or len(set(variants)) != 3 or any(k not in found for k in variants):
            raise ValueError(f'D4 class has {len(found)} source personalities; choose three explicit existing variants')
        return [found[k] for k in variants]

    # ------------------------------------------------------------------ animation files
    def anm(self, number, mesh_nodes=False):
        """D4 anmNNNNN.lzs as a d5lib.anm.AnmFile (read_anm; `mesh_nodes`: D4MESH1, mesh nodes carried as mesh)"""
        from . import gamefs
        pack = getattr(self, "_anm_pack", None) or Nsac(self._file(ANM_PACK))
        self._anm_pack = pack
        return read_anm(gamefs.decode_member(pack.read(f"anm{int(number):05d}.lzs")), mesh_nodes=mesh_nodes)

    def body_palettes(self, body):
        """the body's palettes, one (256, 4) RGBA array per colour (a class: one per rank + extra colours)"""
        from . import anm
        f = self.anm(body)
        return [anm.get_palette(f, k) for k in range(len(f.palettes))]

    # ------------------------------------------------------------------ voices
    def voice_lines(self, groups):
        """Original lines with native categories and explicitly labelled legacy raw flags.

        Selected table rows and archive members must agree one-to-one. Missing
        rows/audio, duplicate line IDs and malformed wrappers fail explicitly.
        Group IDs are source identities; they do not themselves prove personality.
        """
        from . import fafs
        groups = set(groups)
        if not groups or any(type(group) is not int or not 0 <= group <= 0xffffffff for group in groups):
            raise ValueError("D4 voice groups must be nonempty unsigned integer IDs")
        table = self._file(VOICE_TABLE.format(lang=self.lang)).read_bytes()
        rows = decode_voice_table(table)
        selected = {line for line, row in rows.items() if row["group"] in groups}
        absent = groups - {rows[line]["group"] for line in selected}
        if absent:
            raise ValueError(f"D4 voice groups absent from table: {sorted(absent)}")
        pack = fafs.FafsPack(str(self._file(VOICE_PACK.format(lang=self.lang))))
        out, seen = [], set()
        try:
            for e in pack.entries:
                parts = e.name.split("/")
                if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) not in groups:
                    continue
                match = re.fullmatch(r"voice_(\d+)\.nlsd", parts[2], re.IGNORECASE) if len(parts) == 3 else None
                if parts[0].casefold() != self.lang.casefold() or match is None:
                    raise ValueError(f"malformed D4 voice member name: {e.name}")
                line = int(match[1])
                if line in seen:
                    raise ValueError(f"duplicate selected D4 voice archive line {line}")
                if line not in rows or rows[line]["group"] != int(parts[1]):
                    raise ValueError(f"D4 voice member/table group or line mismatch: {e.name}")
                raw = pack.read(e)
                if len(raw) != e.size:
                    raise ValueError(f"truncated D4 voice archive member: {e.name}")
                out.append(dict(line=line, **rows[line], **decode_voice_member(raw)))
                seen.add(line)
            if selected != seen:
                raise ValueError(f"D4 voice table lines missing audio: {sorted(selected - seen)}")
        finally:
            pack.close()
        return sorted(out, key=lambda x: x["line"])


# ---------------------------------------------------------------------------------- D4 animation files
ANM_STRIDES = [4, 16, 12, 8, 12, 18, 16, 4, 20, 4]     # table row sizes; D5's node rows are 20 bytes


def d5_node(row, mesh_nodes=False):
    """One D4 node row (id, flags, +4, +6, first_key, num_keys, child, next) -> `anm.Node`.

    D4MESH1: the word at D4 +4 is the mesh flag.  `mesh_nodes=True` moves a 1 there to the node's `mesh` word (D5 +8)
    and clears `unk2`; otherwise it stays in `unk2` and `mesh` is 0 (the kit's old reading)."""
    from . import anm
    nid, fl, u2, u3, fk, nk, ch, nx = row
    if mesh_nodes and u2 == 1:
        return anm.Node(nid, fl, 0, u3, 1, 0, fk, nk, ch, nx)
    return anm.Node(nid, fl, u2, u3, 0, 0, fk, nk, ch, nx)


def read_anm(raw, mesh_nodes=False):
    """decoded D4 ANM bytes -> d5lib.anm.AnmFile.  A D4 ANM is laid out like a D5 one (32-byte header, blocks with a
    0x44 header and ten tables, 16-byte image headers, image data at header[0] + 0x10) except that the node table
    has 16-byte rows (id, flags, unk2, unk3, first_key, num_keys, child, next): D5's two extra words (mesh, unk5)
    are 0 here, so the kit's evaluate / render helpers read the result unchanged.  Palette records are 256 colours
    (their header's second size word is not a row count).  From the D4 timing research
    (/Volumes/Data/ai-tmp/claude/d4-timing/d4anm.py), palette sizing corrected.

    D4MESH1 (D4-ANM-08): the word at D4 node +4 is the MESH flag (1 on 45 of 5,582 nodes of the 44 in-scope bodies,
    never another value): such a node draws its cell on four stored vertices (the transform's pivot index names a
    group of ten points; the first four are TL, TR, BR, BL relative to the node, no pivot subtraction).  Disgaea 5
    keeps the same flag at its node +8 (`Node.mesh`, one i32; `anm_render_node_hierarchy` 0x1402f7c60 reads five points
    from the pivot table and negates them for flips, as D4 does), so `mesh_nodes=True` carries it there and the kit's
    `anm.evaluate` draws these nodes as the game does.  The default False keeps the old reading (flag left in `unk2`,
    mesh 0: the cell is placed as a pivoted rectangle), which draws 37 motions of Death, Hugo, Des X and Prinny Kurtis
    wrong."""
    from . import anm
    h0, _dsize, ntex, npal, nblk = struct.unpack_from("<5I", raw, 0)
    cur, blocks, tb, pb = 32, [], 0, 0
    for _ in range(nblk):
        size, bid, nanim = struct.unpack_from("<IHH", raw, cur)
        counts = struct.unpack_from("<10H", raw, cur + 8)
        offs = struct.unpack_from("<10I", raw, cur + 0x1C)
        cnt = [nanim] + list(counts[:9])
        b = anm.AnmBlock(bid, count9=counts[9])
        for i, (cls, sz) in enumerate(zip(anm.TABLES, ANM_STRIDES)):
            o = cur + offs[i]
            if i == 1:
                for j in range(cnt[i]):
                    b.nodes.append(d5_node(struct.unpack_from("<HHHHhHhh", raw, o + j * 16), mesh_nodes))
            else:
                b.tables()[i].extend(anm._unpack_table(cls, raw, o, cnt[i], sz))
        b.tex_base, b.pal_base = tb, pb
        tb += len(b.texture_infos)
        pb += len(b.palette_infos)
        blocks.append(b)
        cur += size
    base = h0 + 0x10
    imgs = []
    for i in range(ntex + npal):
        r = cur + i * 16
        fmt = bytes(raw[r:r + 4])
        w, h, unk, off = struct.unpack_from("<HHII", raw, r + 4)
        n = 256 * 4 if i >= ntex else w * h * (1 if fmt[0] == anm.FMT_INDEXED8 else 4)
        if i >= ntex:
            w, h = 256, 1
        imgs.append(anm.Image8(fmt, w, h, unk, bytes(raw[base + off:base + off + n])))
    if cur + (ntex + npal) * 16 != base:
        raise ValueError("unexpected D4 ANM header layout")
    return anm.AnmFile(blocks, imgs[:ntex], imgs[ntex:])
