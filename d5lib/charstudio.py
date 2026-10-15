"""Character studio: what the Characters page uses to build a custom character out of what the game and the enabled
mods already have.

  * stat presets: a playable character of the game whose numbers a new character starts from (PRESETS), and
    copy_fields() -- base stats, aptitudes, movement, mastery, resistances, evilities, Overload, skills of any
    character or class onto another, base stats scaled by a power %;
  * a skill of the character's own: new_skill() -- a magic.dat row copied from an existing skill (its animation too:
    d5lib.skills.inherit), with its own id next to the character's (unique skills are 10000 + class id + n, like
    Killia's 10011-10014), learned at a level;
  * outfits as characters: outfit_sources() lists every outfit of the enabled mods, outfit_to_character() makes a
    new unique character with that look -- a Disgaea RPG outfit is drawn again from its DRPG unit as a complete
    character (outfits.create_drpg_character), any other outfit's sprite files are copied under new numbers.
    The outfit itself can be hidden from the in-game Outfit list by the new character's mod (outfits.json "hide"):
    the outfit's mod is never edited, and switching the character's mod off brings the outfit back.
Nothing here changes a row the game already has except the ones a mod already edits; new ids are always free ones
(saves keep working).
"""
import os

from . import dbpatch

CHAR = "char.dat"
MAGIC = "magic.dat"
LANGS = ("JP", "EN", "FR", "CHN", "KOR")
STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")

# (key, label, what it is like, the game's character the numbers come from)
PRESETS = [
    ("allrounder", "All-rounder", "Strong at close range, fast, a bit of everything (Killia's numbers)", 10),
    ("heavy", "Heavy hitter", "Lots of HP, ATK and DEF, little magic (Red Magnus' numbers)", 50),
    ("caster", "Spellcaster", "High INT, RES and SP for spells and magic skills (Christo's numbers)", 60),
    ("defender", "Defender", "High DEF, RES and SPD, steady all round (Usalia's numbers)", 70),
    ("speedster", "Speedster", "Very fast and evasive, moves far (Zeroken's numbers)", 100),
    ("gunner", "Gunner", "High HIT and SP: guns and accurate skills (Seraphina's numbers)", 40),
    ("healer", "Healer", "High RES, INT and SP: healing and support (Flonne's numbers)", 530),
    ("overlord", "Overlord", "Strong ATK and HP with good magic (Laharl's numbers)", 510),
]

GROUPS = {
    "base": [f"base_{s}" for s in STATS],
    "apt": [f"apt_{s}" for s in STATS],
    "move": ["MOV", "JMP", "throw", "counter", "crit", "attack_range"],
    "mastery": ["mastery_fist", "mastery_sword", "mastery_spear", "mastery_bow", "mastery_gun", "mastery_axe",
                "mastery_staff", "mastery_monster_phys", "mastery_monster_mag", "mastery_armor"],
    "res": ["res_fire", "res_wind", "res_ice", "res_star", "wres_fist", "wres_sword", "wres_spear", "wres_bow",
            "wres_gun", "wres_axe", "wres_staff", "wres_monster"],
    "evilities": list(dbpatch.EVILITIES) + ["evility_count"],
    "overload": ["overload_id"],
    "skills": [f"learn{k}_{w}" for k in range(1, 17) for w in ("skill", "level")] + ["learn_count"],
}
FRESH_GROUPS = ("skills", "evilities", "overload")     # what a new character doesn't take from its template


def start_fresh(row):
    """a new character's own start: no learned skills, evilities or Overload (its template's are that character's;
    give it its own on the Characters & Classes page) -> number of values cleared"""
    n = 0
    for g in FRESH_GROUPS:
        for f in GROUPS[g]:
            if f in row and row[f]:
                row.set(f, 0)
                n += 1
    return n


GROUP_LABELS = [("base", "Base stats"), ("apt", "Aptitudes"), ("move", "Movement & combat"),
                ("mastery", "Weapon mastery"), ("res", "Resistances"), ("evilities", "Evilities"),
                ("overload", "Overload"), ("skills", "Learned skills")]


def copy_fields(dst, src, groups=("base", "apt", "move"), power=100):
    """copy the chosen groups of fields from row src to row dst; base stats are scaled by power % (at least 1)"""
    n = 0
    for g in groups:
        for f in GROUPS[g]:
            if f not in src.keys() or f not in dst.keys():
                continue
            v = src[f]
            if g == "base" and power != 100:
                v = max(1, int(round(v * power / 100.0)))
            if dst[f] != v:
                dst.set(f, v)
                n += 1
    return n


def preset(key):
    return next(p for p in PRESETS if p[0] == key)


def set_langs(row, prefix, text):
    for L in LANGS:
        if f"{prefix}_{L}" in row.keys():
            row.set(f"{prefix}_{L}", text, truncate=True)


# ------------------------------------------------------------------------------------------------ own skills
def free_skill_id(magic_table, char_id, taken=()):
    """a free magic.dat id for a new skill of character char_id: next to its own (10000 + id + n), else 13000+"""
    used = {r["id"] for r in magic_table.rows} | set(taken)
    if 0 < char_id < 1000:
        start = 10000 + char_id // 10 * 10 + 1
        for i in range(start, min(start + 99, 10999)):
            if i not in used:
                return i
    i = 13000
    while i in used:
        i += 1
    return i


def all_mod_skill_ids(mods):
    """magic.dat ids any of these mods adds (so two mods never pick the same new id)"""
    out = set()
    for m in mods:
        p = m.load_patch("db", "magic.dat.json") or {}
        out.update(int(r["id"]) for r in p.get("added") or [] if isinstance(r, dict) and "id" in r)
    return out


def new_skill(svc, fs, mod, char_row, copy_of, name, desc="", level=1, sp_cost=None, mods=()):
    """A new skill of the character's own: a copy of skill copy_of (numbers and animation) with a new name / id,
    learned by char_row at `level` (in a free learn slot).  svc: the kit's database service (tables in memory, saved
    by svc.commit).  -> new skill id"""
    magic = svc.table(MAGIC)
    src_i = magic.index_of(copy_of)
    if src_i < 0:
        raise ValueError(f"no skill {copy_of}")
    sid = free_skill_id(magic, int(char_row["id"]), all_mod_skill_ids(mods))
    r = magic.add_row(copy_from=src_i)
    r.set("id", sid)
    set_langs(r, "name", name)
    if desc:
        set_langs(r, "desc", desc)
    if sp_cost is not None:
        r.set("sp_cost", int(sp_cost))
    svc.mark_dirty(MAGIC)
    give_skill(char_row, sid, level)
    svc.mark_dirty(CHAR)
    from . import skills
    skills.inherit(fs, mod, sid, copy_of)                 # plays copy_of's animation until it gets its own
    return sid


def give_skill(row, sid, level):
    """put skill sid into a free learn slot of row (or update its level) -> slot number"""
    for k in range(1, 17):
        if row[f"learn{k}_skill"] == sid:
            row.set(f"learn{k}_level", int(level))
            return k
    for k in range(1, 17):
        if not row[f"learn{k}_skill"]:
            row.set(f"learn{k}_skill", sid)
            row.set(f"learn{k}_level", int(level))
            row.set("learn_count", sum(1 for j in range(1, 17) if row[f"learn{j}_skill"]))
            return k
    raise ValueError("this character already learns 16 skills: remove one first")


# ------------------------------------------------------------------------------------------------ outfits
def outfit_sources(mods, names=None):
    """[dict(mod, base, outfit, name, who, drpg_uid, sprite)] of every outfit in these mods"""
    from . import outfits
    out = []
    hidden = {h for m in mods for h in hidden_outfits(m)}     # not offered: they are another character's now
    for m in mods:
        pairs = outfits.load(m)
        if not pairs:
            continue
        nm = outfits.load_names(m)
        uids = {int(v): int(k) for k, v in (m.load_patch("outfits", "drpg_units.json") or {}).items()}
        for base, o in pairs:
            if int(o) in hidden:
                continue
            out.append(dict(mod=m, base=int(base), outfit=int(o), name=nm.get(int(o)) or f"Outfit {o}",
                            who=(names or {}).get(int(base)) or f"class {base}", drpg_uid=uids.get(int(o))))
    return out


def hidden_outfits(mod):
    from . import outfits
    return [int(x) for x in outfits._data(mod).get("hide", [])]


def hide_outfit(mod, outfit_id, hide=True):
    """this mod hides (or stops hiding) outfit_id from the in-game Outfit list; the outfit's own mod is untouched"""
    from . import outfits
    d = outfits._data(mod)
    h = set(int(x) for x in d.get("hide", []))
    (h.add if hide else h.discard)(int(outfit_id))
    d["hide"] = sorted(h)
    if not d["hide"]:
        d.pop("hide")
    if d:
        mod.save_patch("outfits", "outfits.json", d)
    elif os.path.exists(os.path.join(mod.patches_dir, "outfits", "outfits.json")):
        os.remove(os.path.join(mod.patches_dir, "outfits", "outfits.json"))


def outfit_to_character(fs, mod, src, name, title=None, desc=(), quest=None, hide=False, log=print):
    """A new unique character with the look of outfit src (an outfit_sources() entry), its stats / skills /
    evilities from the outfit's character, made in `mod`.  A Disgaea RPG outfit is drawn again from its DRPG unit
    (complete animation set, face, portrait, cut-in); another outfit's sprite files are copied under new numbers.
    hide: `mod` hides the outfit from the Outfit list.  -> dict(id, sprite, quest)"""
    from . import outfits
    if src.get("drpg_uid") is not None:
        res = outfits.create_drpg_character(fs, mod, src["base"], src["base"], src["drpg_uid"], name, title=title,
                                            desc=desc, quest=quest, log=log)
    else:
        res = _copy_outfit_character(fs, mod, src, name, title, desc, quest, log)
    if hide:
        hide_outfit(mod, src["outfit"])
    return res


def _copy_outfit_character(fs, mod, src, name, title, desc, quest, log):
    """a non-DRPG outfit: its char.dat row and sprite files (sprite N .. N+2, portraits N+10000 / N+10001, own
    animation set, colour parts, face) copied to a new character id and sprite number in `mod`"""
    from . import anm, database, newchars, outfits, slots
    som = src["mod"]
    van, ed = outfits._char_tables(fs, mod)
    every = database_with(fs, som, "char.dat")             # the outfit's row as its mod makes it
    orow = next((r for r in every.rows if r["id"] == src["outfit"]), None)
    if orow is None:
        raise ValueError(f"outfit {src['outfit']} has no character row")
    ids = slots.free_unique_ids(fs, mod, extra_taken=outfits.used_slots(mod))
    if not ids:
        raise RuntimeError("no free character id below 1000")
    cid = ids[0]
    N0, N = orow["sprite_id"], outfits._free_sprite(fs, mod)
    r = orow.copy()
    r.set("id", cid)
    r.set("sprite_id", N)
    r.set("color_id", orow["color_id"])
    set_langs(r, "name", name)
    if title:
        set_langs(r, "title", title)
    outfits.put_row(ed, r)                           # a reserved dummy id: its row, in place
    mod.save_patch("db", "char.dat.json", dbpatch.diff_table(van, ed))
    copied = _copy_look(som, mod, N0, N)
    face = outfits.face_path(som, src["outfit"])
    if os.path.exists(face):
        newchars.set_face(mod, cid, face)
    qid = _desc_and_quest(fs, mod, cid, name, r, desc, quest) if (any(desc) or quest) else None
    log(f"character '{name}': id {cid}, sprite anm{N:05d} copied from outfit {src['outfit']} "
        f"({len(copied)} sprite files)")
    return {"id": cid, "sprite": N, "quest": qid}


def _copy_look(som, mod, N0, N):
    """an outfit's sprite N0 of mod `som` copied to sprite N of `mod`: anm N .. N+2, portraits 10000 + N / N+1
    (block ids renumbered), its own animation set registered, its colour parts and full-colour source.
    -> numbers written"""
    import shutil
    from . import anm, outfits
    copied = []
    for a, b in ((N0, N), (N0 + 1, N + 1), (N0 + 2, N + 2), (N0 + 10000, N + 10000), (N0 + 10001, N + 10001)):
        vp = f"Anime/ANM_HI_JP.dat/anm{a:05d}.lzs"
        data = som.read_file(vp) if som.has_file(vp) else None
        if data is None:
            continue
        f = anm.parse(data)
        for blk in f.blocks:
            if blk.id == a:
                blk.id = b
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{b:05d}.lzs", f.to_bytes())
        copied.append(b)
    own = {int(x) for x in outfits.load_own(som)}
    if N0 in own:                                          # it carries its own animation set
        outfits.save(mod, outfits.load(mod), set(outfits.load_own(mod)) | {N, N + 1})
    for path in (outfits.parts_path, outfits.source_path):
        sp = path(som, N0)
        if os.path.exists(sp):
            os.makedirs(os.path.dirname(path(mod, N)), exist_ok=True)
            shutil.copyfile(sp, path(mod, N))
    return copied


def copy_outfit(fs, mod, src, base_cid, name=None, log=print):
    """outfit src (an outfit_sources() entry, any mod) copied as an outfit of character base_cid (a row of `mod`, or
    of the game): a free outfit slot whose row is the character's with the outfit's look (its sprite files copied
    to a new number in `mod`), its face, its menu name.  -> dict(slot, sprite)"""
    from . import outfits
    som = src["mod"]
    van, ed = outfits._char_tables(fs, mod)
    base = next((r for r in ed.rows if r["id"] == int(base_cid)), None)
    if base is None:
        raise ValueError(f"no character {base_cid}")
    every = database_with(fs, som, "char.dat")
    orow = next((r for r in every.rows if r["id"] == src["outfit"]), None)
    if orow is None:
        raise ValueError(f"outfit {src['outfit']} has no character row")
    slot = outfits.free_slot(mod, fs)
    N0, N = orow["sprite_id"], outfits._free_sprite(fs, mod)
    r = base.copy()
    r.set("id", slot)
    r.set("sprite_id", N)
    outfits.put_row(ed, r)
    mod.save_patch("db", "char.dat.json", dbpatch.diff_table(van, ed))
    copied = _copy_look(som, mod, N0, N)
    face = outfits.face_path(som, src["outfit"])
    if os.path.exists(face):
        import shutil
        os.makedirs(os.path.dirname(outfits.face_path(mod, slot)), exist_ok=True)
        shutil.copyfile(face, outfits.face_path(mod, slot))
    names = outfits.load_names(mod)
    names[slot] = name or src["name"]
    outfits.save(mod, outfits.load(mod) + [[int(base_cid), slot]], names=names)
    log(f"outfit '{names[slot]}' of {base['name_EN']}: slot {slot}, sprite anm{N:05d} copied from outfit "
        f"{src['outfit']} ({len(copied)} sprite files)")
    return {"slot": slot, "sprite": N}


def database_with(fs, mod, name):
    """table `name` as the game has it with `mod`'s patch applied"""
    from . import database
    t = database.load_table(name, fs.read(f"Database/Database_0.dat/{name}"))
    p = mod.load_patch("db", f"{name}.json")
    if p:
        dbpatch.apply_patch(t, p)
    return t


def _desc_and_quest(fs, mod, cid, name, row, desc, quest):
    """description lines and a recruit quest for a new character made by _copy_outfit_character"""
    from . import outfits
    van, ed = outfits._char_tables(fs, mod)
    r = next(x for x in ed.rows if x["id"] == cid)
    desc = [d for d in (desc or ()) if d] or dbpatch.default_help(name, r["title_EN"])
    if any(desc):
        hv, he = outfits._table_pair(fs, mod, "charhelp.dat")
        si = next((i for i, h in enumerate(he.rows) if h["char_id"] == r["help_id"]), None)
        hr = he.add_row(copy_from=si)
        hid = outfits._free_help_id(fs, mod)
        hr.set("id", hid)
        hr.set("char_id", hid)
        lines = dbpatch.help_lines(desc)
        for k in range(3):
            set_langs(hr, f"line{k + 1}", lines[k])
        for fl in ("flag_off1", "flag_off2", "flag_off3"):
            if fl in hr.keys():
                hr.set(fl, 0)
        r.set("help_id", hid)
        mod.save_patch("db", "charhelp.dat.json", dbpatch.diff_table(hv, he))
        mod.save_patch("db", "char.dat.json", dbpatch.diff_table(van, ed))
    if quest:
        qv, qe = outfits._table_pair(fs, mod, "Quest.dat")
        qid, qslot = outfits._free_quest(fs, mod)
        si = next((i for i, q in enumerate(qe.rows) if q["id"] == 1), 0)
        qr = qe.add_row(copy_from=si)
        qr.set("id", qid)
        set_langs(qr, "name", quest.get("title", "A New Ally"))
        set_langs(qr, "client", quest.get("client", name))
        for k, line in enumerate(dbpatch.quest_lines(quest.get("text", "")), 1):
            set_langs(qr, f"desc{k}", line)
        qr.set("sort_order", qslot)
        qr.set("reward_type", 5)
        qr.set("reward_value", cid)
        qr.set("reward_count", 1)
        qr.set("important", 1)
        mod.save_patch("db", "Quest.dat.json", dbpatch.diff_table(qv, qe))
        return qid
    return None


# ------------------------------------------------------------------------------------------------ own evilities
SKILL = "Skill.dat"


def free_evility_id(skill_table, char_id, taken=()):
    """a free Skill.dat id for a character's own evility: next to its class id (the game's unique evilities are
    the character's id + n, e.g. Killia's 10 and 11), else 7000+"""
    used = {r["id"] for r in skill_table.rows} | set(taken)
    if 0 < char_id < 1000:
        for i in range(char_id, min(char_id // 10 * 10 + 10, 1000)):
            if i not in used:
                return i
    i = 7000
    while i in used:
        i += 1
    return i


def all_mod_evility_ids(mods):
    out = set()
    for m in mods:
        p = m.load_patch("db", "Skill.dat.json") or {}
        out.update(int(r["id"]) for r in p.get("added") or [] if isinstance(r, dict) and "id" in r)
        out.update(int(a) for a in (m.load_patch("evilities", "aliases.json") or {}))
    return out


def new_evility(svc, mod, char_row, works_like, name, desc=None, slot=None, mods=()):
    """An evility of the character's own: a new Skill.dat row named `name` that works like evility `works_like`
    in game (the alias hook of d5lib.newclasses; its numbers are that evility's), put into the character's evility
    slot `slot` (1-4; None = the first free one).  -> new evility id"""
    skills_t = svc.table(SKILL)
    si = skills_t.index_of(works_like)
    if si < 0:
        raise ValueError(f"no evility {works_like}")
    cid = int(char_row["id"])
    eid = free_evility_id(skills_t, cid, all_mod_evility_ids(mods))
    r = skills_t.add_row(copy_from=si)
    r.set("id", eid)
    set_langs(r, "name", name)
    if desc:
        set_langs(r, "desc", desc)
    r.set("owner", cid)
    r.set("kind", 1)                        # a unique evility (like the main cast's)
    r.set("class_order", 0)
    r.set("slot_cost", 0)
    svc.mark_dirty(SKILL)
    al = mod.load_patch("evilities", "aliases.json") or {}
    al[str(eid)] = int(works_like)
    mod.save_patch("evilities", "aliases.json", al)
    ev = list(dbpatch.EVILITIES)
    if slot is None:
        slot = next((k for k, f in enumerate(ev, 1) if not char_row[f]), None)
        if slot is None:
            raise ValueError("this character has 4 evilities already: choose the slot to replace")
    char_row.set(ev[int(slot) - 1], eid)
    char_row.set("evility_count", sum(1 for f in ev if char_row[f]))
    svc.mark_dirty(CHAR)
    return eid
