"""New generic classes: first the game's reserved 'Human Dummy' class families (char.dat 1270 .. 1350) and 'Monster
Dummy' families (2220 .. 2330), six rank rows each, already in comb.dat -- a class mod fills the six rows in place
(old saves stay valid); then families of their own (humans 1360 .. 1990, monsters 2340 .. 2390 and 2620 .. 2890:
six rows appended, a description row, a comb.dat slot at install).  119 classes in all (the unlock flags below).  A
class mod also adds the JobRank chain and patches/classes/class_<family>.json; everything else happens at install
time.  The game sorts char.dat when it loads it and tells humanoids from monsters by sprite number (< 2000), so a
family's sprite (anm <family>) keeps it on the right side.

Class unlock flags
------------------
The game keeps one "class unlocked" flag per class rank (FlagList 17001 .. 17282, FLAG_CHARAMAKE_*) and maps a class
id to its flag through a fixed table in the exe (0x140A484C0: 282 (class id, flag) pairs).  The dummy families have
no entries, so they never show.  Two hooks (section .d5cl):
  0x14008d3f0  the table lookup used by "is this class rank unlocked" (0x1401c5790): for a modded rank it returns an
               index whose table entry lies in our section (the reader reads [table + 8 * index + 4]); a class
               marked "unlocked" gets its first rank's flag set right there, so it is in the list from the start
  0x1401c5920  "unlock this class rank" (quest rewards, rank ups): same entries, so rank ups are stored too
Flags: 17283 + 6 * (index in ALL_FAMILIES) + rank -- the rest of the game's class unlock block 17001 .. 17999 (named
up to 17282, unused after): dummies 17283-17408, then the families of their own up to 17996.

Two things a live check must know (both cost a session on 2026-10-26, EX-LIVE2 check 3):

* The flag bitmap is at the *game build's* address, not the kit's: it is ``exemap.ACTIVE(FLAGS_VA)``
  (``0x144FCCB0E`` on the pinned build; the kit's ``0x144FFA9AE`` is the known build's).  Reading or writing
  ``0x144FFA9AE`` in the running game touches unrelated bytes, so "the flags read 0" says nothing.
* ``char.dat`` is loaded at boot, so a class family is only known to the game -- and its flags can only be set --
  after the game is *relaunched* following the install.  A wheel opened in a process that was already running when
  Install ran cannot show an imported class, whatever the exe on disk says.  The first unlock lookup sets the rank
  flags itself (the ``au_set`` path above), so a save with every class flag at 0 is normal and still lists the class.

Evility aliases (section .d5cl as well)
---------------------------------------
Evility effects are checked by id against the unit's sorted active evility list (unit +0x2f30, count +0x3030,
built by 0x140218090, which ends by sorting it).  A new evility row can't carry an effect of its own, so a class's new
evilities name an existing one: just before the sort, every listed new id adds its existing id to the list (values
come from that row: the new row repeats them for the description).

Graphics (outfits._finalize, with the outfits' faces and list icons)
--------------------------------------------------------------------
Sprite anm <family> (+1 companion, +2 standing picture) with 10 palettes (one per rank + extra colours), portraits
anm 10000 + family + 0..9, faces 9017 anims <colour> / 10000 + <colour> copied from the template class with the face
picture (patches/classes/face_<family>.png), list icons for colours family .. family + 9.  The sprite carries its
own animation set (registered like the outfits' own sprites).
"""
import json
import os
import pickle

from . import anm, database, dbpatch, exemap, sprites, textfmt
from .modsys import register_finalizer, register_patch_handler

FOLDER = "classes"
CHAR = "Database/Database_0.dat/char.dat"
JOBRANK = "Database/Database_0.dat/JobRank.dat"
HELP = "Database/Database_0.dat/charhelp.dat"
HUMAN_DUMMIES = list(range(1270, 1351, 10))
MONSTER_DUMMIES = list(range(2220, 2331, 10))
DUMMY_FAMILIES = HUMAN_DUMMIES + MONSTER_DUMMIES
NEW_HUMAN = list(range(1360, 2000, 10))                                     # rows of their own (appended)
NEW_MONSTER = list(range(2340, 2400, 10)) + list(range(2620, 2900, 10))    # (2400 .. 2610: corpses, bosses ...)
ALL_FAMILIES = DUMMY_FAMILIES + NEW_HUMAN + NEW_MONSTER                    # order = unlock flag order (fixed)
HUMAN_FAMILIES = HUMAN_DUMMIES + NEW_HUMAN
MONSTER_FAMILIES = MONSTER_DUMMIES + NEW_MONSTER
FLAG_BASE, FLAG_LAST = 17283, 17999
assert FLAG_BASE + 6 * len(ALL_FAMILIES) - 1 <= FLAG_LAST
COLOURS = 10
LANGS = ("JP", "EN", "FR", "CHN", "KOR")


def _spec_map(specs):
    return specs if isinstance(specs, dict) else {int(s['family']): s for s in (specs or ())}


def sprite_family(family, spec=None):
    return int((spec or {}).get('sprite_family', family))


def class_kind(family, spec=None):
    return (spec or {}).get('kind', 'monster' if 2000 <= int(family) < 3000 else 'humanoid')


def validate_specs(specs):
    """Registry identities lease existing physical slots and their persistent flags.

    Leases belong in the mod manifest and must stay fixed after recruitment. Two
    enabled definitions cannot share a lease, including a legacy low-ID class.
    This retains the existing 119-slot capacity; it does not allocate save bits.
    """
    specs = _spec_map(specs)
    used = {}
    for family, spec in specs.items():
        family = int(family)
        if int(spec.get('family', family)) != family:
            raise ValueError('class descriptor key disagrees with its family')
        if family % 10 or family < 1000 or family > 32760 or 20000 <= family < 22000:
            raise ValueError(f'unsupported or reserved class family {family}')
        if family not in ALL_FAMILIES and not 10000 <= family:
            raise ValueError(f'class family {family} is neither a Kit slot nor a registry identity')
        if family not in ALL_FAMILIES and not {'kind', 'sprite_family'} <= spec.keys():
            raise ValueError(f'registry class {family} requires kind and sprite_family')
        slot = sprite_family(family, spec)
        kind = class_kind(family, spec)
        if slot not in ALL_FAMILIES or kind not in ('humanoid', 'monster'):
            raise ValueError(f'invalid physical class lease for {family}')
        if (slot in MONSTER_FAMILIES) != (kind == 'monster'):
            raise ValueError(f'class {family} kind disagrees with physical sprite slot {slot}')
        if family in ALL_FAMILIES and (slot != family or kind != class_kind(family)):
            raise ValueError(f'legacy class {family} cannot change its persistent slot')
        if slot in used and used[slot] != family:
            raise ValueError(f'class families {used[slot]} and {family} share physical slot {slot}')
        used[slot] = family
    return specs


def flag_of(cls, specs=None):
    family = cls // 10 * 10
    spec = _spec_map(specs).get(family)
    if family not in ALL_FAMILIES and spec is None:
        raise ValueError(f'registry class {family} requires an explicit persistent slot lease')
    if family not in ALL_FAMILIES and cls % 10 >= 6:
        raise ValueError('registry rank digits 6-9 are reserved')
    return FLAG_BASE + 6 * ALL_FAMILIES.index(sprite_family(family, spec)) + cls % 10


def spec_path(mod, family):
    return os.path.join(mod.patches_dir, FOLDER, f"class_{int(family)}.json")


def face_path(mod, family, colour=0):
    """the class's face picture (colour 0: every colour without one of its own), or colour n's own (1-9)"""
    name = f"face_{int(family)}.png" if not colour else f"face_{int(family)}_{int(colour)}.png"
    return os.path.join(mod.patches_dir, FOLDER, name)


def load_specs(mod):
    d = os.path.join(mod.patches_dir, FOLDER)
    out = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            if n.startswith("class_") and n.endswith(".json"):
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    out.append(json.load(f))
    return out


def save_spec(mod, spec):
    validate_specs([spec])
    p = spec_path(mod, spec["family"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1, ensure_ascii=False)


def set_face(mod, family, image, mirror=False, colour=0):
    from PIL import Image
    img = (Image.open(image) if isinstance(image, str) else image).convert("RGBA")
    if mirror:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    p = face_path(mod, family, colour)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    img.save(p)


# ------------------------------------------------------------------------------------------ tables
def _tables(fs, mod, member):
    van = database.load_table(member.split("/")[-1], fs.read(member))
    ed = database.load_table(member.split("/")[-1], fs.read(member))
    p = mod.load_patch("db", member.split("/")[-1] + ".json")
    if p:
        dbpatch.apply_patch(ed, p)
    return van, ed


def _save(mod, member, van, ed):
    d = dbpatch.diff_table(van, ed)
    mod.save_patch("db", member.split("/")[-1] + ".json", None if dbpatch.is_empty(d) else d)


def set_langs(row, field, text):
    for L in LANGS:
        k = f"{field}_{L}"
        if k in row:
            row.set(k, textfmt.prose(text), truncate=True)


def fill_class(fs, mod, family, template, name, titles, help_lines=(), edit=None, log=print,
               sprite_family=None):
    """Rows family .. family+5 = copies of the template class's rank rows (in place: the dummy rows), with the class's
    own sprite / colour ids, names, description and the JobRank chain.  edit(row, rank) customises each row."""
    if family not in ALL_FAMILIES:
        if sprite_family is None:
            raise ValueError('registry rows require an explicit physical sprite_family')
        validate_specs([dict(family=family, sprite_family=sprite_family,
                             kind='monster' if 2000 <= template < 3000 else 'humanoid')])
    van, ed = _tables(fs, mod, CHAR)
    rows = {r["id"]: i for i, r in enumerate(ed.rows)}
    trows = {r["id"]: r for r in ed.rows}
    for k in range(6):
        src = trows[template + k]
        new = src.copy()
        new.set("id", family + k)
        physical = family if sprite_family is None else int(sprite_family)
        new.set("sprite_id", physical)
        new.set("color_id", physical + k)
        new.set("help_id", family)
        new.set("voice_id", src["voice_id"])
        new.set("is_dummy_slot", 0)
        set_langs(new, "name", name)
        set_langs(new, "title", titles[k])
        if edit:
            edit(new, k)
        if family + k in rows:                   # a reserved dummy row: filled in place
            ed.rows[rows[family + k]] = new
        else:                                    # a family of its own: a new row (the game sorts char.dat on load)
            ed.rows.append(new)
    _save(mod, CHAR, van, ed)
    jv, je = _tables(fs, mod, JOBRANK)
    je.rows[:] = [r for r in je.rows if not family <= r["id"] < family + 10]
    jt = {r["id"]: r for r in je.rows}
    for k in range(6):
        r = jt[template + k].copy()
        r.set("id", family + k)
        nxt = jt[template + k]["next_id"]
        r.set("next_id", family + (nxt - template) if template <= nxt < template + 10 else nxt)
        je.rows.append(r)
    _save(mod, JOBRANK, jv, je)
    hv, he = _tables(fs, mod, HELP)
    if not any(r["char_id"] == family or r["id"] == family for r in he.rows):
        src = next((r for r in he.rows if r["char_id"] == template), None)
        if src is not None:                      # a family of its own: a description row of its own
            r = src.copy()
            r.set("id", family)
            r.set("char_id", family)
            he.rows.append(r)
    lines = dbpatch.help_lines(help_lines)
    for r in he.rows:
        if r["char_id"] == family or r["id"] == family:
            for n in range(3):
                set_langs(r, f"line{n + 1}", lines[n])
    _save(mod, HELP, hv, he)
    log(f"class {name}: rows {family}-{family + 5} from {trows[template]['name_EN']}")


MAGIC = "Database/Database_0.dat/magic.dat"
SKILL = "Database/Database_0.dat/Skill.dat"


def add_skill(fs, mod, new_id, copy_of, name, desc, users=(), **fields):
    """magic.dat row new_id = copy of copy_of with a new name / description (all languages) and fields"""
    van, ed = _tables(fs, mod, MAGIC)
    ed.rows[:] = [r for r in ed.rows if r["id"] != new_id]
    r = next(x for x in ed.rows if x["id"] == copy_of).copy()
    r.set("id", new_id)
    set_langs(r, "name", name)
    if desc is not None:                              # None: keep the copied skill's description
        set_langs(r, "desc", desc)
    for k, v in fields.items():
        r.set(k, v)
    if users:
        for n in range(4):
            r.set(f"user{n + 1}", users[n] if n < len(users) else 0)
        r.set("user_count", len(users))
    ed.rows.append(r)
    _save(mod, MAGIC, van, ed)
    from . import skills
    skills.inherit(fs, mod, new_id, copy_of)          # same choreography as the skill it was copied from


def add_evility(fs, mod, new_id, alias_of, name, desc, owner, order, **fields):
    """Skill.dat row new_id: the values of evility alias_of (whose effect it has in game, see the evility hook),
    owned by class `owner` as its class evility `order` (6 = the class's unique one)."""
    van, ed = _tables(fs, mod, SKILL)
    ed.rows[:] = [r for r in ed.rows if r["id"] != new_id]
    src = next(x for x in ed.rows if x["id"] == alias_of)
    r = src.copy()
    r.set("id", new_id)
    set_langs(r, "name", name)
    if desc is not None:                              # None: keep the aliased evility's description (its numbers)
        set_langs(r, "desc", textfmt.format_text(desc))
    r.set("owner", owner)
    r.set("class_order", order)
    if order == 6:
        r.set("kind", 1)
        r.set("slot_cost", 0)
    else:
        r.set("kind", 0)
    for k, v in fields.items():
        r.set(k, v)
    ed.rows.append(r)
    _save(mod, SKILL, van, ed)


PERSONAL = "Database/Database_0.dat/charPersonal.dat"


def personality_names(fs, template):
    """The donor class's own three personality names (charPersonal.dat group = template // 10)."""
    table = database.load_table(PERSONAL.split("/")[-1], fs.read(PERSONAL))
    group = int(template) // 10
    rows = sorted((r for r in table.rows if int(r["voice_group"]) == group), key=lambda r: r["variant"])
    if len(rows) < 3:
        raise ValueError(f"template {template} has fewer than three personality rows")
    return [r["name_EN"] or r["name_JP"] for r in rows[:3]]


def add_personalities(fs, mod, family, template, names):
    """Character creation's personality choices (charPersonal.dat, 3 per class): voice group = 100 + (family - 1000)
    / 10.  Rows copied from the template class's group with new names; without them the creation screen crashes."""
    van, ed = _tables(fs, mod, PERSONAL)
    group, tgroup = 100 + (family - 1000) // 10, 100 + (template - 1000) // 10
    src = sorted((r for r in ed.rows if r["voice_group"] == tgroup), key=lambda r: r["variant"])
    # Cryswar's Overlord checks the same three-row requirement before the
    # Recruiter personality page, which dereferences all three choices.
    if len(src) < 3:
        raise ValueError(f"template {template} has fewer than three personality rows")
    ed.rows[:] = [r for r in ed.rows if r["voice_group"] != group]
    nid = max(r["id"] for r in ed.rows) + 1
    for k, s in enumerate(src[:3]):
        r = s.copy()
        r.set("id", nid + k)
        r.set("voice_group", group)
        set_langs(r, "name", names[k])
        ed.rows.append(r)
    _save(mod, PERSONAL, van, ed)


# ------------------------------------------------------------------------------------------ sprite
def build_sprite(fs, mod, template_sprite, N, uid, log=print):
    """DRPG unit `uid` -> class sprite N: the template class's whole animation set (shared motions + its own idle and
    special poses), every pose the unit's drawing of the same pose placed exactly where the vanilla drawing was
    (d5lib.drpgmap), 10 palettes derived per part from the template class's colours; companion N+1, standing picture
    N+2, the full-colour source."""
    from . import colorvariants, drpgmap, ownanim, outfits
    motion = sprites.motion_block(fs, 1, log)
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, template_sprite, "EN")))
    known = int(uid) in drpgmap.load_hands()
    out, rep = drpgmap.build(fs, uid, template_sprite, N, log=log, auto_hands=not known)
    if not known and log:
        log(f"  DRPG unit {uid} has no hand points in d5lib/data/drpg_hands.json: the idle weapon was placed by "
            f"automatic hand detection, which is often a few pixels off. Check it on the Weapon Grips page "
            f"(anm{N:05d}, Idle 6001 / 6007) and drag it into the hand.")
    outfits.save_source(mod, N, out)
    info = colorvariants.repartition(out, base, fs=fs)
    ref = colorvariants.reference_for(uid)        # the class's own colours from the Disgaea wiki (data/wiki_colors)
    if ref:
        colorvariants.from_reference(out, ref, info, log)
    outfits._save_parts(mod, N, info)
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs", out.to_bytes())
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(out, N + 1).to_bytes())
    icon = outfits._resident_icon(fs, template_sprite + 2)
    if icon is None:
        try:
            icon = anm.parse(fs.read(sprites.sprite_vpath(fs, template_sprite + 2, "EN")))
        except KeyError:
            icon = None
    if icon is not None:
        icon = outfits.repaint_stand_icon(pickle.loads(pickle.dumps(icon)), base, motion, out)
        icon.blocks[0].id = N + 2
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 2:05d}.lzs", icon.to_bytes())
    return out


def monster_companion(fs, sprite, template_sprite, N):
    """anm N+1 of a monster: the vanilla companion file holds only part of the animation set (Dragon King's 2181: 47 of
    62, no attacks).  A full copy hangs the enemy turn when the monster counterattacks, so the companion keeps exactly
    the template companion's animation ids (with the new drawings)."""
    from . import ownanim
    comp = ownanim.with_id(sprite, N + 1)
    try:
        tc = anm.parse(fs.read(sprites.sprite_vpath(fs, template_sprite + 1, "EN")))
    except KeyError:
        return comp
    keep = {a.id for b in tc.blocks for a in b.animations}
    for b in comp.blocks:
        b.animations = [a for a in b.animations if a.id in keep]
    return comp


def build_monster_sprite(fs, mod, template_sprite, N, uid, pairs, log=print):
    """DRPG monster `uid` -> sprite N with vanilla monster `template_sprite`'s animations (d5lib.monstermap; pairs:
    the new monster's pose for each of the template twin's poses), palettes per part like the classes, companion
    N+1, standing picture N+2."""
    from . import colorvariants, monstermap, ownanim, outfits
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, template_sprite, "EN")))
    out, rep = monstermap.build(fs, uid, template_sprite, N, pairs, log=log)
    outfits.save_source(mod, N, out)
    info = colorvariants.repartition(out, base, fs=fs)
    ref = colorvariants.reference_for(uid)
    if ref:
        colorvariants.from_reference(out, ref, info, log)
    outfits._save_parts(mod, N, info)
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs", out.to_bytes())
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", monster_companion(fs, out, template_sprite, N).to_bytes())
    icon = outfits._resident_icon(fs, template_sprite + 2)
    if icon is not None:
        icon = outfits.repaint_stand_icon(pickle.loads(pickle.dumps(icon)), base, None, out)
        icon.blocks[0].id = N + 2
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 2:05d}.lzs", icon.to_bytes())
    return out


def used_families(mods):
    return {n for m in mods for s in load_specs(m)
            for n in (int(s['family']), sprite_family(s['family'], s))}


def is_monster(family):
    return 2000 <= int(family) < 3000


def free_family(mods, monster=False, fs=None):
    """the first family no mod uses (reserved dummies first) whose sprite numbers (anm family .. +2, portraits
    10000 + family .. +9) no game file and no mod file uses"""
    import re
    used = used_families(mods)
    taken = set()
    if fs is not None:
        try:
            taken |= set(sprites.used_sprite_numbers(fs))
        except Exception:
            pass
    rx = re.compile(r"anm(\d{5})\.lzs$", re.I)
    in_mods = set()
    for m in mods:
        for f in m.list_files():
            mm = rx.search(f)
            if mm:
                in_mods.add(int(mm.group(1)))
    taken |= in_mods
    for f in (MONSTER_FAMILIES if monster else HUMAN_FAMILIES):
        if f in used:
            continue
        numbers = {f, f + 1, f + 2} | {10000 + f + j for j in range(COLOURS)}
        # the game's own reserved families have its dummy files there (the class fills them); another mod's files
        # there (an outfit sprite numbered 11290 = a portrait of family 1290) rule it out
        if numbers & (in_mods if f in DUMMY_FAMILIES else taken):
            continue
        return f
    return None


def templates():
    """vanilla classes a DRPG class can take its animations from (their own poses are mapped)"""
    from . import drpgmap
    return [c for c, u in drpgmap.TWINS if os.path.exists(drpgmap.own_map_path(c))]


def create_class(fs, mm, uid, template, name, family=None, titles=None, hire_desc="", help_lines=(),
                 personalities=None, unlocked=True, log=print):
    """A new recruitable generic class from Disgaea RPG unit `uid`, animated exactly like vanilla class `template`
    (templates()): its own mod 'Class_<name>' with sprite, face, portraits, rank rows (copies of the template's,
    renamed), rank chain, description, personalities and class spec.  Stats / skills / evilities can be edited
    afterwards (Characters page or add_skill / add_evility).  -> the mod"""
    from . import drpg, modsys
    if template not in templates():
        raise ValueError(f"template {template} has no pose map; use one of {templates()}")
    family = family or free_family(mm.all_mods(), fs=fs)
    if family is None:
        raise RuntimeError(f"all {len(HUMAN_FAMILIES)} class slots for humanoids are in use")
    mid = "Class_" + "".join(ch if ch.isalnum() else "_" for ch in name)
    mod = mm.get(mid) or mm.create("Class " + name, "D5 Mod Kit",
                                   f"New generic class {name} (Disgaea RPG unit {uid}) in class slot {family}.")
    build_sprite(fs, mod, template, family, uid, log=log)
    ex = drpg.unit_extras(uid)
    if "icon" in ex:
        set_face(mod, family, ex["icon"], mirror=True)
    if "cutin" in ex:
        set_portraits(fs, mod, family, template, ex["cutin"])
    titles = list(titles or [name] * 6)
    add_personalities(fs, mod, family, template, personalities or ["Diligent", "Proud", "Newbie"])
    fill_class(fs, mod, family, template, name, titles, help_lines)
    save_spec(mod, dict(family=family, template=template, name=name, unlocked=unlocked, unlocked_ranks=6,
                        hire_desc=hire_desc, evility_alias={}))
    log(f"class {name}: mod {mod.id}, class ids {family}-{family + 5}, sprite anm{family:05d}")
    return mod


def create_monster(fs, mm, uid, template, name, pairs, family=None, titles=None, hire_desc="", help_lines=(),
                   personalities=None, unlocked=True, log=print):
    """A new recruitable generic monster from Disgaea RPG monster `uid`, animated like vanilla monster `template`
    (monstermap.templates()) with the poses `pairs` (monstermap.suggest / load_pairs), in a monster family
    (MONSTER_FAMILIES).  Same parts as create_class.  -> the mod"""
    from . import drpg, monstermap
    if template not in monstermap.templates():
        raise ValueError(f"template {template} has no twin map; use one of {monstermap.templates()}")
    family = family or free_family(mm.all_mods(), monster=True, fs=fs)
    if family is None:
        raise RuntimeError(f"all {len(MONSTER_FAMILIES)} class slots for monsters are in use")
    mid = "Monster_" + "".join(ch if ch.isalnum() else "_" for ch in name)
    mod = mm.get(mid) or mm.create("Monster " + name, "D5 Mod Kit",
                                   f"New generic monster {name} (Disgaea RPG unit {uid}) in class slot {family}.")
    monstermap.save_pairs(pairs, os.path.join(mod.patches_dir, FOLDER, f"poses_{family}.json"))
    build_monster_sprite(fs, mod, template, family, uid, pairs, log=log)
    ex = drpg.unit_extras(uid)
    if "icon" in ex:
        set_face(mod, family, ex["icon"], mirror=True)
    if "cutin" in ex:
        set_portraits(fs, mod, family, template, ex["cutin"])
    titles = list(titles or [name] * 6)
    add_personalities(fs, mod, family, template, personalities or ["Diligent", "Proud", "Newbie"])
    fill_class(fs, mod, family, template, name, titles, help_lines)
    save_spec(mod, dict(family=family, template=template, name=name, unlocked=unlocked, unlocked_ranks=6,
                        hire_desc=hire_desc, evility_alias={}, drpg=uid))
    log(f"monster {name}: mod {mod.id}, class ids {family}-{family + 5}, sprite anm{family:05d}")
    return mod


def set_portraits(fs, mod, family, template, image, matte=None, fit="stretch"):
    """anm 10000 + family + j (j = 0..9): the template class's portrait files with `image` (cut-in) drawn in;
    `image` may be a list of one picture per colour.  Background handling goes through
    imgtools.screen_picture: the picture is pasted as it is (white background kept) unless the caller names
    matte options AND the D5MODKIT_D4_MATTE=1 opt-in is set -- owner decision 2026-10-27, playtest PT1027 S3.
    False keeps the picture (the historical spelling, still allowed).
    `fit` is imgtools.cutin_placement's mode ("stretch" = the historical whole-texture resize); returns one
    placement record per file written (DD2CUTIN1)."""
    import numpy as np
    from PIL import Image
    from .imgtools import fit_cutin, screen_picture
    placements = []
    pictures = list(image) if isinstance(image, (list, tuple)) else [image]
    pictures = [(Image.open(p) if isinstance(p, str) else p).convert("RGBA") for p in pictures]
    pictures = [screen_picture(p, matte) for p in pictures]
    for j in range(COLOURS):
        img = pictures[j] if j < len(pictures) else pictures[0]
        src = 10000 + template + j
        try:
            a = anm.parse(fs.read(sprites.sprite_vpath(fs, src, "EN")))
        except KeyError:
            continue
        for b in a.blocks:
            if b.id == src:
                b.id = 10000 + family + j
        t = a.textures[0]
        if not t.indexed:
            fitted, place = fit_cutin(img, (t.width, t.height), fit)
            t.data = anm._rgba_to_argb(np.asarray(fitted)).tobytes()
            placements.append(dict(place, source_size=list(img.size), texture=[t.width, t.height], bank=10000 + family + j))
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{10000 + family + j:05d}.lzs", a.to_bytes())
    return placements


# ------------------------------------------------------------------------------------------ exe hooks
SECTION = b".d5cl"
TABLE_VA = 0x140A484C0            # (class id, flag) pairs, 282 entries
FLAGS_VA = 0x144FFA9AE            # game flag bits (save data)
LOOKUP_VA = 0x14008D3F0           # xor r10d, r10d / lea r11, [table]   (r8d = class -> eax = index or -1)
LOOKUP_ORIG = bytes.fromhex("4533d24c8d1dc6b09b00")
SETTER_VA = 0x1401C5920           # sub rsp, 0x28 / lea eax, [rcx - 0x7da]   (ecx = class rank to unlock)
SETTER_ORIG = bytes.fromhex("4883ec288d8126f8ffff")
SETTER_TAIL = 0x1401C59A3         # flag of table entry rcx (rbx = image base) is set, then the "all classes" check
EVI_VA = 0x14021878C              # movsxd rdx, [rdi + 0x3030] (count) before sorting the active evility list
EVI_ORIG = bytes.fromhex("486397303000" + "00")
EVI_RET = 0x140218793


def _table_src(classes, specs=None):
    nl = chr(10)
    return nl.join(["    .align 8", "cls_table:"] + [f"    .long {c}, {flag_of(c, specs)}" for c in classes] +
                   ["    .long 0, 0"])


def _lookup_src(classes, auto, specs=None):
    nl = chr(10)
    return nl.join([
        "    lea r10, [rip + cls_table]",
        "lk_loop:",
        "    mov eax, dword ptr [r10]",
        "    test eax, eax",
        "    je lk_orig",
        "    cmp eax, r8d",
        "    je lk_hit",
        "    add r10, 8",
        "    jmp lk_loop",
        "lk_hit:",
        "    lea r9, [rip + auto_ids]",
        "au_loop:",
        "    mov edx, dword ptr [r9]",
        "    test edx, edx",
        "    je au_done",
        "    cmp edx, r8d",
        "    je au_set",
        "    add r9, 4",
        "    jmp au_loop",
        "au_set:",
        "    mov edx, dword ptr [r10 + 4]",
        "    mov r9d, edx",
        "    shr r9d, 3",
        "    and edx, 7",
        "    lea rcx, [rip + flags_sym]",
        "    movzx r11d, byte ptr [rcx + r9]",
        "    bts r11d, edx",
        "    mov byte ptr [rcx + r9], r11b",
        "au_done:",
        "    mov rax, r10",
        "    lea rcx, [rip + table_sym]",
        "    sub rax, rcx",
        "    sar rax, 3",
        "    ret",
        "lk_orig:",
        "    xor r10d, r10d",
        "    lea r11, [rip + table_sym]",
        f"    jmp {exemap.at(LOOKUP_VA, len(LOOKUP_ORIG))}",
        "    .align 4",
        "auto_ids:",
        "    .long " + ", ".join(str(c) for c in list(auto) + [0]),
        _table_src(classes, specs),
        f"table_sym = {TABLE_VA:#x}",
        f"flags_sym = {FLAGS_VA:#x}",
    ])


def _setter_src(classes, specs=None):
    nl = chr(10)
    return nl.join([
        "    sub rsp, 0x28",
        "    lea r10, [rip + cls_table]",
        "st_loop:",
        "    mov eax, dword ptr [r10]",
        "    test eax, eax",
        "    je st_orig",
        "    cmp eax, ecx",
        "    je st_hit",
        "    add r10, 8",
        "    jmp st_loop",
        "st_hit:",
        "    mov qword ptr [rsp + 0x20], rbx",
        "    mov r9d, ecx",
        "    lea rbx, [rip + base_sym]",
        "    mov rcx, r10",
        "    lea rax, [rip + table_sym]",
        "    sub rcx, rax",
        "    sar rcx, 3",
        f"    jmp {SETTER_TAIL:#x}",
        "st_orig:",
        "    lea eax, [rcx - 0x7da]",
        f"    jmp {exemap.at(SETTER_VA, len(SETTER_ORIG))}",
        _table_src(classes, specs),
        "base_sym = 0x140000000",
        f"table_sym = {TABLE_VA:#x}",
    ])


def _evility_src(aliases):
    nl = chr(10)
    rows = [f"    .long {a}, {b}" for a, b in sorted(aliases.items())] + ["    .long 0, 0"]
    return nl.join([
        "    xor r10d, r10d",
        "ev_loop:",
        "    cmp r10d, dword ptr [rdi + 0x3030]",
        "    jge ev_done",
        "    mov eax, dword ptr [rdi + r10*4 + 0x2f30]",
        "    lea r9, [rip + ev_map]",
        "ev_m:",
        "    mov edx, dword ptr [r9]",
        "    test edx, edx",
        "    je ev_next",
        "    cmp edx, eax",
        "    je ev_add",
        "    add r9, 8",
        "    jmp ev_m",
        "ev_add:",
        "    movsxd rdx, dword ptr [rdi + 0x3030]",
        "    cmp edx, 0x40",
        "    jge ev_next",
        "    mov eax, dword ptr [r9 + 4]",
        "    mov dword ptr [rdi + rdx*4 + 0x2f30], eax",
        "    inc dword ptr [rdi + 0x3030]",
        "ev_next:",
        "    inc r10d",
        "    jmp ev_loop",
        "ev_done:",
        "    movsxd rdx, dword ptr [rdi + 0x3030]",
        f"    jmp {EVI_RET:#x}",
        "    .align 4",
        "ev_map:",
    ] + rows)


# Hire Character (Recruiter): the class carousel is built from a fixed list of the hireable families (0x14091B820, 26
# human + 21 monster, 47 entries) into the scene (+0x1e404, room for 53 entries, count +0x1e4d8; the first entry
# may be the current unit's class): the loop walks our copy of that list with the new families after the humans.
HIRE_VA = 0x1402A36B6             # lea rsi, [family list] / mov r14d, 47
HIRE_ORIG = bytes.fromhex("488d356381670041be2f000000")
HIRE_RET = 0x1402A36C3
HIRE_LIST = [1010, 1020, 1030, 1040, 1050, 1060, 1070, 1080, 1090, 1100, 1110, 1120, 1130, 1140, 1150, 1160, 1170,
             1180, 1190, 1200, 1210, 1220, 1230, 1240, 1250, 1260,
             2010, 2020, 2030, 2040, 2050, 2060, 2070, 2080, 2090, 2100, 2110, 2120, 2130, 2140, 2150, 2160, 2170,
             2180, 2190, 2200, 2210]


def _hire_src(families):
    lst = HIRE_LIST[:26] + list(families) + HIRE_LIST[26:]
    return chr(10).join([
        "    lea rsi, [rip + fam_list]",
        f"    mov r14d, {len(lst)}",
        f"    jmp {HIRE_RET:#x}",
        "    .align 4",
        "fam_list:",
        "    .long " + ", ".join(map(str, lst)),
    ])


# The Hire Character carousel itself (0x1406673b0): the same 47 families from a copy on the stack; each unlocked one
# goes into scene +0x90 + 8 * n (class, number of unlocked ranks; 47 slots, n at +0x208).  After that loop our families
# are added the same way while there is a free slot.
CAROUSEL_VA = 0x140667500         # cmp rbp, 0x2f / jl loop
CAROUSEL_ORIG = bytes.fromhex("4883fd2f7c9a")
CAROUSEL_LOOP = 0x1406674A0
CAROUSEL_DONE = 0x140667506
IS_UNLOCKED = 0x1401C5790


def _wheel_page_src(state=None):
    """asm: choose the wheel page and rebuild the entry list from the snapshot (see WHEEL_PAGES).

    Runs at the end of the native list builder -- the instruction at CAROUSEL_VA -- after the vanilla entries and the
    mods' families are in the relocated buffer and the unfiltered list was captured.  The page is chosen only here,
    when the list is built, which is Cryswar's page key in d5_custom_classes.c (The Unlicense): the menu never has
    its actors replaced under it, and nothing reads an entry this code has not written.

      Shift held as the wheel opens -> the next wheel (cycles, 5 wheels)
      Shift + 1..5                  -> that wheel directly (1 = D5, 2 = D4, 3 = D1C, 4 = DD2, 5 = Overlord)
      no key                        -> all entries initially, then the previous selected wheel

    A page with no class returns to the full captured list. Fewer than six entries are repeated in whole cycles,
    as Cryswar's CC_GRID_MIN does, because the grid
    indexes `(cursor - 6 + count) % count` and a shorter list reads before its start.  `rdi` is the window, `rbp` the
    builder's loop index (saved), `rsp%16 == 0` on entry; only volatile registers are used.

    The key is read straight from the game's own per-frame key state (`state`, WHEEL_KEY_STATE; `_asm` translates
    it), the array the input update fills from GetKeyboardState / DirectInput every frame -- no call, no stack
    switch, no code of another module running inside the list builder.  WHEELS2 called the GetKeyboardState import
    slot as an address and WHEELS3 called through it; TEST17 (which ships WHEELS3) still froze the game on the first
    Hire Character build with the filter in, so the call itself is what WHEELS4 removed -- the page key never needed
    it (Cryswar reads the same state with GetAsyncKeyState; The Unlicense, credit Cryswar).  See WHEELS4-REPORT.md.
    """
    h = WHEEL_HEADER
    if state is None:
        raise ValueError("the wheel page needs the game's key state array for this build")
    return [
        "# ---- one wheel per game: page from the game's own key state, list rebuilt from the capture ----",
        f"    mov r10, {state:#x}",           # the game's per-frame key state (no call: see WHEEL_KEY_STATE)
        "    lea r11, [rip + carousel_buf]",
        f"    cmp dword ptr [r11 + {h + WHEEL_ENABLED}], 0",
        "    je wh_done",
        f"    cmp dword ptr [r11 + {h + WHEEL_NSNAP}], 0",
        "    je wh_done",
        f"    mov r9d, dword ptr [r11 + {h + WHEEL_PAGE}]",
        f"    cmp r9d, {WHEEL_PAGES}",
        "    jbe wh_page_ok",                   # WHEEL_PAGES means the initial unfiltered list
        f"    mov r9d, {WHEEL_PAGES}",
        "wh_page_ok:",
        # The pointer immediately before the state array selects its indexing scheme.
        "    cmp qword ptr [r10 - 8], 0",
        "    je wh_vk_keys",
        f"    test byte ptr [r10 + {DIK_LSHIFT}], 0x80",
        "    jnz wh_di_shift",
        f"    test byte ptr [r10 + {DIK_RSHIFT}], 0x80",
        "    jz wh_page",
        "wh_di_shift:",
        f"    mov eax, {DIK_DIGIT_1}",
        "    jmp wh_keys_ready",
        "wh_vk_keys:",
        f"    test byte ptr [r10 + {KEY_SHIFT}], 0x80",
        "    jz wh_page",
        f"    mov eax, {KEY_DIGIT_1}",
        "wh_keys_ready:",
        "    xor ecx, ecx",
        "wh_digit:",
        "    lea rdx, [r10 + rax]",
        "    movzx edx, byte ptr [rdx + rcx]",
        "    test dl, 0x80",
        "    jnz wh_digit_hit",
        "    inc ecx",
        f"    cmp ecx, {WHEEL_PAGES}",
        "    jb wh_digit",
        "    inc r9d",                          # Shift alone: the next wheel
        f"    cmp r9d, {WHEEL_PAGES}",
        "    jb wh_page",
        "    xor r9d, r9d",
        "    jmp wh_page",
        "wh_digit_hit:",
        "    mov r9d, ecx",
        "wh_page:",
        f"    cmp r9d, {WHEEL_PAGES}",
        "    je wh_done",                      # no key on first opening: keep the entire captured list
        "    push rbp",
        "    xor ebp, ebp",
        "wh_try:",
        "    xor esi, esi",                     # n: entries kept
        "    xor ecx, ecx",                     # i: entry in the capture
        "wh_entry:",
        f"    cmp ecx, dword ptr [r11 + {h + WHEEL_NSNAP}]",
        "    jae wh_built",
        f"    mov eax, dword ptr [r11 + rcx*8 + {WHEEL_SNAPSHOT}]",
        "    xor r8d, r8d",
        "    xor edx, edx",                     # the family's wheel: 0 (the D5 wheel) unless a mod owns it
        "wh_owner:",
        f"    cmp r8d, dword ptr [r11 + {h + WHEEL_NOWNERS}]",
        "    jae wh_owner_done",
        f"    lea r10, [r11 + r8*4 + {WHEEL_OWNERS}]",
        "    cmp ax, word ptr [r10]",
        "    jne wh_owner_next",
        "    movzx edx, byte ptr [r10 + 2]",
        "    jmp wh_owner_done",
        "wh_owner_next:",
        "    inc r8d",
        "    jmp wh_owner",
        "wh_owner_done:",
        "    cmp edx, r9d",
        "    jne wh_next",
        f"    mov eax, dword ptr [r11 + rcx*8 + {WHEEL_SNAPSHOT}]",
        "    mov dword ptr [r11 + rsi*8], eax",
        f"    mov edx, dword ptr [r11 + rcx*8 + {WHEEL_SNAPSHOT + 4}]",
        "    mov dword ptr [r11 + rsi*8 + 4], edx",
        "    inc esi",
        "wh_next:",
        "    inc ecx",
        "    jmp wh_entry",
        "wh_built:",
        "    test esi, esi",
        "    jnz wh_filled",
        f"    mov dword ptr [r11 + {h + WHEEL_PAGE}], {WHEEL_PAGES}",
        f"    mov dword ptr [r11 + {h + WHEEL_PAGE2}], {WHEEL_PAGES}",
        "    pop rbp",                          # empty page: retain the full captured list
        "    jmp wh_done",
        "wh_filled:",
        "    pop rbp",
        "    mov edx, esi",                     # one whole cycle of the wheel
        "wh_cycle:",
        "    cmp esi, 6",
        "    jae wh_count",
        "    xor ecx, ecx",
        "wh_repeat:",
        "    cmp esi, 6",
        "    jae wh_count",
        "    mov eax, dword ptr [r11 + rcx*8]",
        "    mov dword ptr [r11 + rsi*8], eax",
        "    mov eax, dword ptr [r11 + rcx*8 + 4]",
        "    mov dword ptr [r11 + rsi*8 + 4], eax",
        "    inc esi",
        "    inc ecx",
        "    cmp ecx, edx",
        "    jb wh_repeat",
        "    jmp wh_cycle",
        "wh_count:",
        "    mov ecx, esi",                     # the entries the vanilla list left behind are -1, as at init
        "    mov edx, dword ptr [rdi + 0x208]",
        f"    cmp edx, {CAROUSEL_CAP}",
        "    jbe wh_clear",
        f"    mov edx, {CAROUSEL_CAP}",
        "wh_clear:",
        "    cmp ecx, edx",
        "    jae wh_clear_done",
        "    mov dword ptr [r11 + rcx*8], 0xffffffff",
        "    mov dword ptr [r11 + rcx*8 + 4], 0xffffffff",
        "    inc ecx",
        "    jmp wh_clear",
        "wh_clear_done:",
        "    mov dword ptr [rdi + 0x208], esi",
        f"    mov dword ptr [r11 + {h + WHEEL_PAGE}], r9d",
        f"    mov dword ptr [r11 + {h + WHEEL_PAGE2}], r9d",
        "wh_done:",
    ]


def stack_mod16(exe, va_known, site=None):
    """RSP % 16 where the hook for `va_known` runs: decoded from the containing function's prologue.

    The hook replaces one instruction in the middle of a function entered by CALL: RSP%16 is 8 there, and the
    prologue's pushes/sub leave it at a fixed value for the rest of the body.  Windows x64 wants RSP%16 == 0 at a CALL
    instruction, so a stub that calls needs this.  A function whose stack the decoder cannot follow raises: a silently
    misaligned call would corrupt the caller.
    """
    import capstone
    import pefile
    from .exepatch import IMAGE_BASE
    site = site or (exemap.ACTIVE(va_known) if hasattr(exemap, "ACTIVE") else va_known)
    pe = pefile.PE(data=exe, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXCEPTION"]])
    base = pe.OPTIONAL_HEADER.ImageBase
    start = None
    for f in getattr(pe, "DIRECTORY_ENTRY_EXCEPTION", []):
        s, e = base + f.struct.BeginAddress, base + f.struct.EndAddress
        if s <= site < e:
            start = s
            break
    if start is None:
        raise ValueError(f"no unwind entry covers the hook site {site:#x}")
    rva = start - base
    for s in pe.sections:
        if s.VirtualAddress <= rva < s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData):
            code = s.get_data()[rva - s.VirtualAddress:rva - s.VirtualAddress + (site - start) + 16]
            break
    else:
        raise ValueError("the hook site is not in a section")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    delta = 8                                       # the CALL that entered the function pushed the return address
    for i in md.disasm(code, start):
        if i.address >= site:
            break
        m, o = i.mnemonic, i.op_str
        dest = o.split(",", 1)[0].strip()
        if m == "push":
            delta -= 8
        elif m == "pop" and dest != "rsp":
            delta += 8
        elif m in ("sub", "add") and dest == "rsp":
            delta += (-1 if m == "sub" else 1) * int(o.split(",", 1)[1], 0)
        elif dest == "rsp" or m in ("leave", "ret"):
            raise ValueError(f"unfollowed stack write at {i.address:#x}: {m} {o}")
    return delta % 16


def _carousel_src(families, capture=False, page_filter=False, key_state=None):
    # One buffer serves every Hire Character / Reincarnation / Sub Class scene, so two builds at once would overwrite
    # a list the other scene is still showing.  The kit cannot prove that only one scene exists, so it at least
    # refuses to rebuild while another build is inside this hook: the inner scene keeps the outer scene's list (a
    # wrong list) instead of corrupting the buffer under it.  A per-scene buffer is the real fix and needs a scene
    # key the relocated read stubs can see -- they only get `base + idx*8`, not the scene.
    filter_src = _wheel_page_src(key_state) if page_filter else []
    return chr(10).join([
        "    cmp rbp, 0x2f",                  # rcx must stay untouched until the vanilla path is taken
        f"    jl {CAROUSEL_LOOP:#x}",
        "    lea rcx, [rip + carousel_buf]",
        f"    cmp dword ptr [rcx + {BUF_GUARD}], 0",
        "    jne cr_busy",
        f"    mov dword ptr [rcx + {BUF_GUARD}], 1",
        "    lea rbx, [rip + new_fams]",
        "cr_next:",
        "    mov esi, dword ptr [rbx]",
        "    test esi, esi",
        "    je cr_done",
        f"    cmp dword ptr [rdi + 0x208], {CAROUSEL_CAP}",
        "    jge cr_done",
        "    mov ecx, esi",
        "    sub rsp, 0x20",                 # the callee's home space: the Windows x64 CALL contract
        f"    call {IS_UNLOCKED:#x}",
        "    add rsp, 0x20",
        "    test al, al",
        "    je cr_skip",
        "    movsxd rax, dword ptr [rdi + 0x208]",
        "    lea rdx, [rip + carousel_buf]",
        "    mov dword ptr [rdx + rax*8], esi",
        "    mov dword ptr [rdx + rax*8 + 4], 1",
        "    mov r15d, 1",
        "cr_rank:",
        "    lea ecx, [rsi + r15]",
        "    sub rsp, 0x20",
        f"    call {IS_UNLOCKED:#x}",
        "    add rsp, 0x20",
        "    test al, al",
        "    je cr_rank_next",
        "    lea eax, [r15 + 1]",
        "    movsxd rdx, dword ptr [rdi + 0x208]",
        "    lea rcx, [rip + carousel_buf]",
        "    mov dword ptr [rcx + rdx*8 + 4], eax",
        "cr_rank_next:",
        "    inc r15d",
        "    cmp r15d, 6",
        "    jl cr_rank",
        "    inc dword ptr [rdi + 0x208]",
        "cr_skip:",
        "    add rbx, 4",
        "    jmp cr_next",
        "cr_done:",
    ] + ([
        # Preserve volatile registers that the original continuation may use.
        "    push r8", "    push r9", "    push r10",
        "    lea rcx, [rip + carousel_buf]",
        f"    mov dword ptr [rcx + {WHEEL_HEADER + WHEEL_NSNAP}], 0",   # only a completed capture publishes
        "    mov r9d, dword ptr [rdi + 0x208]",
        f"    cmp r9d, {CAROUSEL_CAP}",
        "    ja cr_capture_done",
        "    xor r8d, r8d",
        "cr_capture_loop:",
        "    cmp r8d, r9d", "    jae cr_capture_publish",
        "    mov eax, dword ptr [rcx + r8*8]",
        "    test eax, eax", "    jz cr_capture_done",
        "    cmp eax, 65535", "    ja cr_capture_done",
        "    mov edx, dword ptr [rcx + r8*8 + 4]",
        "    lea r10d, [rdx - 1]", "    cmp r10d, 5", "    ja cr_capture_done",
        f"    mov dword ptr [rcx + r8*8 + {WHEEL_SNAPSHOT}], eax",
        f"    mov dword ptr [rcx + r8*8 + {WHEEL_SNAPSHOT + 4}], edx",
        "    inc r8d", "    jmp cr_capture_loop",
        "cr_capture_publish:",
        f"    mov dword ptr [rcx + {WHEEL_HEADER + WHEEL_NSNAP}], r9d",
        "cr_capture_done:",
        "    pop r10", "    pop r9", "    pop r8",
    ] if capture else []) + filter_src + [
        "    lea rcx, [rip + carousel_buf]",
        f"    mov dword ptr [rcx + {BUF_GUARD}], 0",
        f"    jmp {CAROUSEL_DONE:#x}",
        "cr_busy:",                       # another build owns the buffer: leave its list alone
        f"    jmp {CAROUSEL_DONE:#x}",
        "    .align 4",
        "new_fams:",
        "    .long " + ", ".join(map(str, list(families) + [0])),
        "carousel_buf = {shared}",
    ])


# The carousel's one-line class description (0x140667ac0: family r8d -> StringListDataBase id from a table parallel
# to the 47 families, 0x27ab "None" for others): our families get their own strings (DESC_BASE + n).
DESC_VA = 0x140667C61             # mov eax, 0x27ab / jmp done
DESC_ORIG = bytes.fromhex("b8ab270000eb07")
DESC_DONE = 0x140667C6F
DESC_BASE = 41000
DESC_TEXT_MAX = 255               # bytes the menu's 0x100 description field can hold (classcheck R9)
STRINGS = "Database/Database_0.dat/StringListDataBase.dat"


def desc_text(text, limit=DESC_TEXT_MAX):
    """The wheel's one-line class description, bounded to the menu's fixed text field.

    The game copies this string into `msgbox_object + 0x1c2c` with a NUL loop and no length check
    (`0x140663200 movzx eax,[rcx]` / `0x140663203 mov [rcx+rdx+0x1c2c],al` / `jne`; the same copy in
    the panel draw at 0x14065feb0), then writes the dirty byte at `+0x1d2c` - one byte past the
    256-byte field.  Past that sit the two floats at +0x1d30/+0x1d34 (17.0f / 16.0f, 0x1403ea680)
    and the list-pane pointer at +0x1d38 that the s28to33 screens call through (vt+0xa8), so a long
    description is a memory-corruption bug, not a layout choice.  A text that does not fit is cut on
    a word boundary and marked with " ...".
    """
    raw = str(text or "")
    if len(raw.encode("utf-8")) <= limit:
        return raw
    room = limit - 4                       # " ..."
    cut = raw.encode("utf-8")[:room].decode("utf-8", "ignore")
    space = cut.rfind(" ")
    if space > room // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + " ..."



def _desc_src(pairs):
    return chr(10).join([
        "    lea rcx, [rip + desc_map]",
        "ds_loop:",
        "    mov eax, dword ptr [rcx]",
        "    test eax, eax",
        "    je ds_none",
        "    cmp eax, r8d",
        "    je ds_hit",
        "    add rcx, 8",
        "    jmp ds_loop",
        "ds_hit:",
        "    mov eax, dword ptr [rcx + 4]",
        f"    jmp {DESC_DONE:#x}",
        "ds_none:",
        "    mov eax, 0x27ab",
        f"    jmp {DESC_DONE:#x}",
        "    .align 4",
        "desc_map:",
    ] + [f"    .long {f}, {s}" for f, s in pairs] + ["    .long 0, 0"])


# ------------------------------------------------------------------------------------------ bigger class lists
# The class carousel (Hire Character, Reincarnation, Sub Class: 8-byte entries at object +0x90 / +0x94, 47 of them,
# count +0x208) and the Status screen's Class tab list (4-byte entries at +0x1e404, 53, count +0x1e4d8) only have room
# for the vanilla classes.  Both move into buffers in our (writable) section: every instruction that reads or writes
# an entry (found by scanning the exe: indexed by the list's selection / count, see docs/CLASSES.md) jumps to a stub
# doing the same with the buffer as base; the counts stay where they are.  One buffer per list is shared by every
# scene using it (only one is open at a time; each rebuilds its list when it opens).
CAROUSEL_CAP = 512
CLASSTAB_CAP = 512
BUF_CAROUSEL = 0                          # offsets in the section's leading buffer
BUF_CLASSTAB = CAROUSEL_CAP * 8
BUF_PROF = BUF_CLASSTAB + CLASSTAB_CAP * 4
BUF_GUARD = BUF_PROF + CLASSTAB_CAP * 4   # "a carousel build is running" flag (see _carousel_src)
BUF_SIZE = BUF_GUARD + 16
# Wheel metadata and staging follow the existing shared buffers. The original
# offsets remain unchanged for all existing relocation hooks.
WHEEL_HEADER = (BUF_SIZE + 7) & ~7
# header fields (WHEEL_HEADER + n); the pack format below and the asm offsets both come from these names
WHEEL_MAGIC = 0          # 8 bytes "D5WHEEL1"
WHEEL_ENABLED = 8        # u32 1: filter the carousel by wheel page (a mod declared a wheel)
WHEEL_NOWNERS = 12       # u32 owner rows
WHEEL_NSNAP = 16         # u32 entries captured by the last build (the unfiltered list)
WHEEL_PAGE = 20          # u32 the wheel page the next build shows (kept across openings)
WHEEL_PAGE2 = 24         # u32 same for the other menu; the kit shows one wheel in both
WHEEL_HEADER_SIZE = 28
WHEEL_OWNERS = WHEEL_HEADER + WHEEL_HEADER_SIZE
WHEEL_SNAPSHOT = WHEEL_OWNERS + CAROUSEL_CAP * 4
WHEEL_STAGE = WHEEL_SNAPSHOT + CAROUSEL_CAP * 8
WHEEL_KEYS = WHEEL_STAGE + CAROUSEL_CAP * 8      # 256 bytes: the page-test buffer of WHEELS2/WHEELS3 (now unused)
WHEEL_SHARED_SIZE = WHEEL_KEYS + 256
# GetKeyboardState's IMPORT ADDRESS SLOT in the game exe: the 8-byte pointer in .rdata that the loader fills (the
# same address d5lib/native/d5auto.c replaces to see injected keys).  It is data, not code -- a `call` to this
# address runs the pointer's bytes.  WHEELS2 did that (the scene-enter thread died there, wheels/WHEELS3-DIAGNOSIS.md)
# and WHEELS3 called THROUGH it; TEST17 still wedged the Hire Character list build, so WHEELS4 stopped calling the
# import altogether and reads the game's own key state (WHEEL_KEY_STATE).  Kept for the WHEELS3 A/B proofs.
KEYS_SLOT = 0x1408D5640
# The game's OWN per-frame key state: 256 bytes, 0x80 = held, refreshed every frame by the input
# update `FUN_14089d890` (decomp /Volumes/Data/Decomp/d5/functions/14089d890_FUN_14089d890.c):
#
#     if (!DAT_147b100a0) GetKeyboardState(local_118);          // no DirectInput pad/keyboard -> Win32
#     else (*DAT_147b100a0->vtbl[0x48])(DAT_147b100a0, 0x100, local_118);   // DirectInput
#     do {
#         bVar1 = local_118[i];
#         (&DAT_147b101a8)[i] = (bVar1 ^ (&DAT_147b100a8)[i]) & bVar1;      // pressed this frame
#         (&DAT_147b103a8)[i] = ~bVar1 & (bVar1 ^ (&DAT_147b100a8)[i]);      // released
#         ...
#         (&DAT_147b100a8)[i] = bVar1;                                        // <-- the state we read
#     } while (...);
#
# The array uses DIK scan codes when the device pointer is nonzero, otherwise VK codes. It is already there when a
# menu builds its list. Reading it is Cryswar's d5_custom_classes.c page key in spirit
# (his `GetAsyncKeyState(g_cc_page_key)` is a read of the game's input state at build time; The Unlicense, credit
# Cryswar) -- but with no call: the list builder runs inside the menu thread, and a filter that calls into the
# runtime's Win32 input path there is what TEST17 could not survive (WHEELS4-REPORT.md).
# Reference (known) venue: 0x147b100a8.  .data did not move between the reference build and this one, and
# wheel_key_state() checks the mapped address before a build uses it.
WHEEL_KEY_STATE = 0x147B100A8
KEY_SHIFT = 0x10
KEY_DIGIT_1 = 0x31                                   # VK_1 .. VK_5 pick a wheel directly
DIK_LSHIFT = 0x2A
DIK_RSHIFT = 0x36
DIK_DIGIT_1 = 0x02                                  # DIK_1 .. DIK_5
WHEEL_PAGES = 5


def wheel_key_state(exe):
    """The game's per-frame key state array (WHEEL_KEY_STATE) in the build being patched.

    Raises when exemap does not know the address for this build, or when it does not land in a writable section
    with the preceding device pointer and 256 key bytes inside it.
    """
    import struct
    va = exemap.ACTIVE(WHEEL_KEY_STATE)
    pe = __import__("pefile").PE(data=exe, fast_load=True)
    for s in pe.sections:
        start = pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress
        if start <= va - 8 and va + 256 <= start + max(s.Misc_VirtualSize, s.SizeOfRawData):
            if not s.Characteristics & 0x80000000:          # IMAGE_SCN_MEM_WRITE
                break
            return va
    raise ValueError(f"the key state array {va:#x} is not in a writable section of this build")


def wheel_shared_bytes(entries, page=WHEEL_PAGES):
    """Build the shared section with a validated immutable family owner map.

    Header: magic, filter enabled, owner count, snapshot count, Recruiter page, Rebirth page.
    Owner rows are <u16 family, u8 wheel, u8 zero>; snapshot/stage are
    512 <u32 family, u32 rank count> rows each, initially empty; the last 256
    bytes are reserved from the earlier keyboard-state buffer.
    `page` is the initial selection (WHEEL_PAGES = all entries; 0 = the D5 wheel).
    """
    import struct
    from .wheelmeta import WHEELS
    entries = list(entries)
    if len(entries) > CAROUSEL_CAP:
        raise ValueError("too many wheel family owners")
    previous = 0
    for family, wheel in entries:
        if (isinstance(family, bool) or not isinstance(family, int) or
                family <= previous or family > 65535 or
                isinstance(wheel, bool) or not isinstance(wheel, int) or
                not 0 <= wheel < len(WHEELS)):
            raise ValueError("invalid or unsorted wheel family owners")
        previous = family
    data = bytearray(WHEEL_SHARED_SIZE)
    struct.pack_into("<8sIIIII", data, WHEEL_HEADER, b"D5WHEEL1", 1 if entries else 0, len(entries), 0, page, page)
    for i, (family, wheel) in enumerate(entries):
        struct.pack_into("<HBB", data, WHEEL_OWNERS + 4 * i, family, wheel, 0)
    return bytes(data)
CAROUSEL_SITES = [                       # [base + idx*8 + 0x90 / 0x94]
    0x140472260, 0x1404724E9, 0x140472949, 0x140476126, 0x140476887, 0x140476E61, 0x140476F7E, 0x1404779E4,
    0x140477EAD, 0x140477F50, 0x140477FB3, 0x140478063, 0x1404783B0, 0x140478BF0, 0x140480323, 0x140480A62,
    0x140480CD7, 0x1404810AF, 0x1404811CC, 0x140481D79, 0x140481DD3, 0x140482374, 0x1404823B9, 0x1404823FA,
    0x140482791, 0x140482A9E, 0x140482B01, 0x140482B5E, 0x140482F8D, 0x140483DC0, 0x140659215, 0x14066257E,
    0x140662CE4, 0x140662F57, 0x1406632D9, 0x1406633F7, 0x140663FCA, 0x140664132, 0x140664721, 0x140664768,
    0x1406647A9, 0x140664B03, 0x140664ED0, 0x140664F33, 0x140664F95, 0x140665604, 0x14066581C, 0x1406674C6,
    0x1406674E4, 0x14066A7B5, 0x14066A7C9, 0x14066ACE2, 0x14066AF8F, 0x14066B4C7]
CAROUSEL_CLEAR = 0x140666966             # add rcx, 0x90 (-> memset(list, -1, 0x178))
CAROUSEL_CLEAR_ORIG = bytes.fromhex("4881c190000000")
CLASSTAB_SITES = [0x14029C1F0, 0x1402A40B1, 0x1402A41F8, 0x1402A36B0]   # [base (+ idx*4) + 0x1e404]
CLASSTAB_APPEND = 0x1402A37F1            # mov [rcx + 0x1e404], eax   with rcx = rbx + idx*4
CLASSTAB_APPEND_ORIG = bytes.fromhex("898104e40100")
# the Class tab's proficiency per listed class (4-byte entries at +0x1e330, parallel to the list): two loops fill it
# for the first 47 list entries walking a pointer (lea rsi, [obj + 0x1e330] ... [rsi + 0xd4]); they are replaced by
# loops over the whole list, and its readers moved like the others
PROF_SITES = [0x14029C0BF, 0x1402A41E7]   # [base + idx*4 + 0x1e330]
PROF_LOOPS = [  # (va, original lea, list object register, start index register, return)
    (0x14029A2A8, bytes.fromhex("488db330e30100"), "rbx", "edi", 0x14029A2E9),
    (0x14029CEB4, bytes.fromhex("488db730e30100"), "rdi", "ebx", 0x14029CEEA)]
PROF_OF = 0x1402A3BF0                    # (list object, class) -> proficiency


def _scratch(text):
    import re
    forms = {"r11": ("r11", "r11d", "r11w", "r11b"), "r10": ("r10", "r10d", "r10w", "r10b"),
             "r9": ("r9", "r9d", "r9w", "r9b"), "r8": ("r8", "r8d", "r8w", "r8b"),
             "rcx": ("rcx", "ecx", "cx", "cl", "ch"), "rdx": ("rdx", "edx", "dx", "dl", "dh")}
    words = set(re.findall(r"[a-z0-9]+", text))
    for r, fs in forms.items():
        if not words & set(fs):
            return r
    raise ValueError("no free register: " + text)


def _reloc_stub(exe, va, disp, entry, buf_off):
    """stub for the instruction at va: its memory operand [base (+ idx*entry) + disp + k] -> [buffer + idx*entry + k]"""
    import re
    import capstone
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    nva = exemap.ACTIVE(va)                 # the instruction in the game build being patched
    off = pe.get_offset_from_rva(nva - IMAGE_BASE)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    ins = next(md.disasm(exe[off:off + 16], nva))
    text = f"{ins.mnemonic} {ins.op_str}"
    m = re.search(r"\[(\w+)(?: \+ (\w+)\*(\d))? \+ (0x[0-9a-f]+)\]", ins.op_str)
    if not m or int(m.group(4), 16) - disp not in range(0, entry):
        raise ValueError(f"unexpected instruction at {va:#x}: {text}")
    k = int(m.group(4), 16) - disp
    S = _scratch(text)
    idx = f" + {m.group(2)}*{m.group(3)}" if m.group(2) else ""
    new = ins.op_str[:m.start()] + f"[{S}{idx}" + (f" + {k}" if k else "") + "]" + ins.op_str[m.end():]
    src = chr(10).join([f"    push {S}", f"    lea {S}, [rip + bufsym]", f"    {ins.mnemonic} {new}", f"    pop {S}",
                        f"    jmp {nva + ins.size}", f"bufsym = {{shared}} + {buf_off}"])
    return (va, bytes(ins.bytes), src, 0xE9)


def _reloc_hooks(exe):
    hooks = [_reloc_stub(exe, va, 0x90, 8, BUF_CAROUSEL) for va in CAROUSEL_SITES]
    hooks.append((CAROUSEL_CLEAR, CAROUSEL_CLEAR_ORIG, chr(10).join([
        "    lea rcx, [rip + bufsym]", f"    mov r8d, {CAROUSEL_CAP * 8}", f"    jmp {exemap.at(CAROUSEL_CLEAR, 7)}",
        f"bufsym = {{shared}} + {BUF_CAROUSEL}"]), 0xE9))
    hooks += [_reloc_stub(exe, va, 0x1E404, 4, BUF_CLASSTAB) for va in CLASSTAB_SITES]
    hooks += [_reloc_stub(exe, va, 0x1E330, 4, BUF_PROF) for va in PROF_SITES]
    for va, orig, obj, start, ret in PROF_LOOPS:
        hooks.append((va, orig, chr(10).join([
            f"    mov ebp, {start}",
            "    xor r14d, r14d",
            "pl_loop:",
            f"    cmp r14d, {CLASSTAB_CAP}",
            "    jge pl_done",
            "    mov edx, 0xffffffff",
            f"    cmp ebp, dword ptr [{obj} + 0x1e4d8]",
            "    jae pl_call",
            "    lea rax, [rip + classbuf]",
            "    mov edx, dword ptr [rax + r14*4]",
            "pl_call:",
            f"    mov rcx, {obj}",
            f"    call {PROF_OF:#x}",
            "    lea rcx, [rip + profbuf]",
            "    mov dword ptr [rcx + r14*4], eax",
            "    inc ebp",
            "    inc r14d",
            "    jmp pl_loop",
            "pl_done:",
            f"    jmp {ret:#x}",
            f"classbuf = {{shared}} + {BUF_CLASSTAB}",
            f"profbuf = {{shared}} + {BUF_PROF}"]), 0xE9))
    hooks.append((CLASSTAB_APPEND, CLASSTAB_APPEND_ORIG, chr(10).join([
        "    sub rcx, rbx", "    push rdx", "    lea rdx, [rip + bufsym]", "    mov dword ptr [rdx + rcx], eax",
        "    pop rdx", "    add rcx, rbx", f"    jmp {exemap.at(CLASSTAB_APPEND, 6)}",
        f"bufsym = {{shared}} + {BUF_CLASSTAB}"]), 0xE9))
    return hooks


# ------------------------------------------------------------------------------------------ generic class ids
# The game asks "is this a generic class" inline in ~60 places: (unsigned)(id - 2010) <= 0x122 (monsters 2010-2300) or
# (unsigned)(id - 1000) <= 0x136 (humans 1000-1310) -- "is this rank unlocked" (0x1401c5790) among them, so a class
# outside those ids never shows (that held the reserved rows 1320-1350 and 2310-2330 back too).  For families of their
# own: the human test is widened in place to 1000-1999 (nothing of the game's lies in 1320-1999); each monster test
# jumps to a stub taking 2010-2390 and 2620-2990 (the game's corpses, bottle mail and bosses 2400-2610 stay out).  A
# few places keep the bounds in registers: both tests go to stubs there.  The sites are found in the exe at install.
GEN_MON = ((0x7DA, 0x17C), (0xA3C, 0x172))      # (low id, span): 2010-2390, 2620-2990
GEN_HUM_SPAN = 0x3E7                            # 1000-1999
GEN_SKIP = {0x1401C5924}                        # "unlock rank": our classes leave before it (SETTER hook)


def outside_vanilla(fam):
    return not (1000 <= fam <= 1310 or 2010 <= fam <= 2300)


def _generic_sites(exe, human_sites=False):
    """-> (monster tests [(va, length, r1, mem, [mid instructions], jcc va)], human tests with a register bound [same],
    human immediates [file offset of the imm32 0x136])"""
    import re
    import capstone
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    text = next(x for x in pe.sections if x.Name.startswith(b".text"))
    code = exe[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
    start = IMAGE_BASE + text.VirtualAddress
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

    def at(va):
        off = va - start
        return next(md.disasm(code[off:off + 16], va), None)

    # instruction boundaries: each hit is decoded from the start of its function (the exception table .pdata lists
    # every function), so a prefix byte is never taken for part of the instruction before
    import bisect
    import struct
    pdata = next((x for x in pe.sections if x.Name.startswith(b".pdata")), None)
    funcs = []
    if pdata is not None:
        raw = exe[pdata.PointerToRawData:pdata.PointerToRawData + pdata.Misc_VirtualSize]
        funcs = sorted(struct.unpack_from("<II", raw, k) for k in range(0, len(raw) - 11, 12))
    begins = [b for b, _ in funcs]
    cache = {}

    def lea_before(h, disp):
        va = start + h
        k = bisect.bisect_right(begins, va - IMAGE_BASE) - 1
        if k >= 0 and funcs[k][0] <= va - IMAGE_BASE < funcs[k][1]:
            b, e = funcs[k]
        else:                                   # a leaf function (no .pdata entry): from the int3 padding before it
            pad = code.rfind(bytes([0xCC, 0xCC]), max(0, h - 0x4000), h)
            if pad < 0:
                return None
            b = start + pad + 2 - IMAGE_BASE
            while code[b + IMAGE_BASE - start] == 0xCC:
                b += 1
            e = va - IMAGE_BASE + 16
        if (b, e) not in cache:
            cache[(b, e)] = {i.address: i for i in md.disasm(code[IMAGE_BASE + b - start:IMAGE_BASE + e - start],
                                                             IMAGE_BASE + b)}
        for back in (2, 3, 4):
            i = cache[(b, e)].get(va - back)
            if i and i.mnemonic == "lea" and i.address + i.size == va + 4 and f"- {disp}" in i.op_str:
                return i
        return None

    def test(lea, imm):
        """lea R1, [R2 - k]; (mov / lea)*; cmp R1, imm|reg; jcc -> (va, length, r1, mem, mid, jcc va, reg bound?)"""
        r1, mem = [x.strip() for x in lea.op_str.split(",", 1)]
        va, mid = lea.address + lea.size, []
        for _ in range(3):
            i = at(va)
            if i is None:
                return None
            va += i.size
            if i.mnemonic == "cmp" and i.op_str.split(",")[0] == r1:
                arg = i.op_str.split(",")[1].strip()
                j = at(va)
                if j is None or j.mnemonic not in ("jbe", "ja"):
                    return None
                if arg == imm:
                    return lea.address, va - lea.address, r1, mem, mid, va, False
                if re.fullmatch(r"[a-z0-9]+", arg) and not arg.startswith("0x") and not arg.isdigit():
                    return lea.address, va - lea.address, r1, mem, mid, va, True
                return None
            if i.mnemonic not in ("mov", "lea") or r1 in i.op_str.split(",")[0]:
                return None
            mid.append(f"{i.mnemonic} {i.op_str}")
        return None

    # The scanner yields this exe's VAs, not the known build's VAs.
    skip = {exemap.ACTIVE(va) for va in GEN_SKIP}
    mon, hum_reg, hum_imm = [], [], []
    for m in re.finditer(re.escape(b"\x26\xf8\xff\xff"), code):          # disp32 -0x7da
        lea = lea_before(m.start(), "0x7da")
        t = lea and test(lea, "0x122")
        if not t or t[0] in skip:
            continue
        nxt = at(t[5])
        after = at(t[5] + nxt.size)
        h = test(after, "0x136") if after is not None and after.mnemonic == "lea" and "- 0x3e8" in after.op_str \
            else None
        if t[6] and not (h and h[6]):
            continue                                  # a register bound without the human test after it
        mon.append(t[:6])
        if h and h[6]:
            hum_reg.append(h[:6])
    for m in re.finditer(re.escape(b"\x18\xfc\xff\xff"), code):          # disp32 -0x3e8
        lea = lea_before(m.start(), "0x3e8")
        i = lea and at(lea.address + lea.size)
        if i is not None and i.mnemonic == "cmp" and i.op_str == f"{lea.op_str.split(',')[0]}, 0x136":
            k = bytes(i.bytes).find(b"\x36\x01\x00\x00")
            site = test(lea, "0x136")
            if human_sites:
                if site:
                    hum_imm.append(site[:6])
            else:
                hum_imm.append(text.PointerToRawData + (i.address - start) + k)
    return mon, hum_reg, hum_imm


def _mon_stub(r1, mem, mid, back, families=()):
    lines = []
    for k, (lo, span) in enumerate(GEN_MON):
        lines += [f"    lea {r1}, {mem.replace('0x7da', hex(lo))}", f"    cmp {r1}, {span:#x}", "    jbe g_yes"]
    for lo in families:
        lines += [f"    lea {r1}, {mem.replace('0x7da', hex(lo))}", f"    cmp {r1}, 5", "    jbe g_yes"]
    lines += [f"    mov {r1}, -1", f"    cmp {r1}, 0x122", "    jmp g_out",
              "g_yes:", f"    xor {r1}, {r1}", f"    cmp {r1}, 0x122",
              "g_out:", f"    lea {r1}, {mem}"]             # the value it had (lea keeps the flags)
    lines += [f"    {x}" for x in mid] + [f"    jmp {back}"]  # native VA: don't translate again
    return chr(10).join(lines)


def _hum_stub(r1, mem, mid, back, families=()):
    if not families:
        return chr(10).join([f"    lea {r1}, {mem}", f"    cmp {r1}, {GEN_HUM_SPAN:#x}"] + [f"    {x}" for x in mid]
                            + [f"    jmp {back}"])
    lines = [f"    lea {r1}, {mem}", f"    cmp {r1}, {GEN_HUM_SPAN:#x}", "    jbe g_yes"]
    for lo in families:
        lines += [f"    lea {r1}, {mem.replace('0x3e8', hex(lo))}", f"    cmp {r1}, 5", "    jbe g_yes"]
    lines += [f"    mov {r1}, -1", f"    cmp {r1}, {GEN_HUM_SPAN:#x}", "    jmp g_out",
              'g_yes:', f'    xor {r1}, {r1}', f'    cmp {r1}, {GEN_HUM_SPAN:#x}',
              'g_out:', f'    lea {r1}, {mem}']
    return chr(10).join(lines + [f"    {x}" for x in mid] + [f"    jmp {back}"])


def generic_patch(exe, taken=(), specs=None):
    """-> (exe with the human tests widened in place, [hooks] for the others); sites inside `taken` [(va, length)]
    (other hooks) are left alone. Both `taken` and returned hook VAs belong to this exe, not the known build."""
    import pefile
    from .exepatch import IMAGE_BASE
    specs = validate_specs(specs or {})
    registry = {kind: sorted(f for f, s in specs.items() if f not in ALL_FAMILIES and class_kind(f, s) == kind)
                for kind in ('humanoid', 'monster')}
    high = any(registry.values())
    mon, hum_reg, hum_imm = _generic_sites(exe, human_sites=high)
    out = bytearray(exe)
    pe = pefile.PE(data=exe, fast_load=True)
    if not high:
        for off in hum_imm:
            exemap.claim(IMAGE_BASE + pe.get_rva_from_offset(off), 4, "human test immediate")   # written in place
            out[off:off + 4] = GEN_HUM_SPAN.to_bytes(4, "little")
    busy = [(va, va + n) for va, n in taken]
    hooks = []
    for kind, lst in (("mon", mon), ("hum", hum_reg + (hum_imm if high else []))):
        for va, n, r1, mem, mid, back in lst:
            if any(a < va + n and va < b for a, b in busy):
                continue
            off = pe.get_offset_from_rva(va - IMAGE_BASE)
            src = (_mon_stub if kind == "mon" else _hum_stub)(r1, mem, mid, back,
                    registry['monster' if kind == 'mon' else 'humanoid'])
            hooks.append((va, bytes(exe[off:off + n]), src, 0xE9))
            busy.append((va, va + n))
    return bytes(out), hooks, (len(mon), len(hum_reg), len(hum_imm))


def build_hooks(exe, classes, auto, aliases, descs=(), specs=None, wheel_entries=None, wheel_page=WHEEL_PAGES):
    """classes: every modded class rank id; auto: ranks unlocked from the start; aliases {new evility: existing}"""
    from .exepatch import add_hook_section
    specs = validate_specs(specs or {})
    if any(c // 10 * 10 not in ALL_FAMILIES and c // 10 * 10 not in specs for c in classes):
        raise ValueError('registry class hooks require explicit physical slot leases')
    hooks = []
    native_hooks = []
    wheels = bool(wheel_entries)
    if classes:
        fams = sorted({c // 10 * 10 for c in classes})
        hooks += [(LOOKUP_VA, LOOKUP_ORIG, _lookup_src(classes, auto, specs), 0xE9),
                  (SETTER_VA, SETTER_ORIG, _setter_src(classes, specs), 0xE9),
                  (HIRE_VA, HIRE_ORIG, _hire_src(fams[:CLASSTAB_CAP - 1 - len(HIRE_LIST)]), 0xE9),
                  (CAROUSEL_VA, CAROUSEL_ORIG, _carousel_src(fams, capture=wheel_entries is not None,
                                                             page_filter=wheels,
                                                             key_state=wheel_key_state(exe) if wheels else None),
                   0xE9)]
        hooks += _reloc_hooks(exe)
    if descs:
        hooks.append((DESC_VA, DESC_ORIG, _desc_src(descs), 0xE9))
    if aliases:
        hooks.append((EVI_VA, EVI_ORIG, _evility_src(aliases), 0xE9))
    if any(outside_vanilla(c // 10 * 10) for c in classes):
        exe, native_hooks, _ = generic_patch(exe, [(exemap.ACTIVE(va), len(orig))
                                                  for va, orig, _, _ in hooks], specs=specs)
    if not hooks:
        return exe
    return add_hook_section(exe, SECTION, hooks, writable=True, native_hooks=native_hooks,
                            shared_bytes=(wheel_shared_bytes(wheel_entries, page=wheel_page)
                                          if wheel_entries is not None else bytes(BUF_SIZE))
                            if classes else b"")


CLASS_SCRIPTS = (3100000,)                        # + class id, per rank (class-specific sequence)
MONSTER_SCRIPTS = (12010000, 12110000, 12210000)  # + sprite id: a monster's normal attack (shown / effects skipped /
                                                  # skipped midway)


def add_class_scripts(sf, vanilla, specs):
    """The template's script events keyed by class or sprite id, copied to every new class in ScriptFile `sf`:
    3100000 + class id (per rank) and, for monsters, the normal-attack events 12010000 / 12110000 / 12210000 + sprite
    id.  The launcher (0x1405474b1) starts 12010000 + sprite (12110000 + sprite when the effects are skipped, falling
    back to the non-existent 11100000): without them a new monster's attack starts no script, and a counterattack in
    the enemy phase waits forever.  A mod's own version of an event wins; the dummy families' placeholders are
    replaced.  `vanilla`: the game's own ScriptFile.  -> number of events added"""
    from . import scriptpatch
    vev = {}
    for e in vanilla.events:
        vev.setdefault(e.id, e)
    cur = {}
    for e in sf.events:
        cur.setdefault(e.id, e)
    add = {}
    for fam, s in specs.items():
        t = int(s["template"])
        for p in CLASS_SCRIPTS + (MONSTER_SCRIPTS if class_kind(fam, s) == 'monster' else ()):
            for k in range(10):
                src = vev.get(p + t + k)
                if src is None:
                    continue
                nid = p + (sprite_family(fam, s) if p in MONSTER_SCRIPTS else int(fam)) + k
                if nid in cur and (nid not in vev or cur[nid].encode() != vev[nid].encode()):
                    continue                    # a mod made its own
                add[str(nid)] = scriptpatch.event_text(src, annotate=False).replace(f"event {src.id}", f"event {nid}", 1)
    if add:
        scriptpatch.apply(sf, {"events": add})
    return len(add)


def _class_scripts(ctx, specs):
    """add_class_scripts on the build's script.dat (+ the skipped-action fallbacks) -> number of events added"""
    from . import script, skills
    sf = ctx.parsed(skills.SCRIPT, script.ScriptFile.from_bytes)
    n = add_class_scripts(sf, vanilla_script(ctx), specs)
    n += skills.add_fallbacks(sf)
    if n:
        ctx.changed(skills.SCRIPT, script.ScriptFile.to_bytes)
    return n


def vanilla_script(ctx):
    """the game's own script.dat, parsed once per build"""
    from . import script, skills
    if getattr(ctx, "_vanilla_script", None) is None:
        ctx._vanilla_script = script.ScriptFile.from_bytes(ctx.fs.read(skills.SCRIPT))
    return ctx._vanilla_script


def auto_ranks(family, spec):
    """the rank ids of a class unlocked from the start: none unless "unlocked"; then the first "unlocked_ranks"
    (1-6, default 6) ranks.  The Recruiter and Reincarnation rank rows offer exactly the classes whose unlock flag
    is set (vanilla list builder 0x140664df0 writes entry+4 = highest unlocked rank; the hire screen's option loop and
    the rebirth window both read it), so six flags = six ranks, recruit and rebirth, without levelling the class
    first.  An explicit "unlocked_ranks": 1-5 keeps a lower ceiling for a partial import."""
    if not spec.get("unlocked", True):
        return []
    return [family + k for k in range(max(1, min(6, int(spec.get("unlocked_ranks", 6)))))]


def _finalize(ctx):
    from .gamefs import EXE_FILE
    specs = getattr(ctx, "_class_specs", {})
    own_aliases = getattr(ctx, "_evility_aliases", {})        # characters' own evilities (patches/evilities)
    if not specs and not own_aliases:
        _monster_pictures(ctx, specs)                 # registry monster uniques need theirs without any class
        return
    validate_specs(specs)
    n_scripts = _class_scripts(ctx, specs) if specs else 0
    if specs:
        _comb_slots(ctx, specs)
    classes, auto, aliases = [], [], dict(own_aliases)
    for fam, s in sorted(specs.items()):
        classes += [fam + k for k in range(6)]
        auto += auto_ranks(fam, s)
        aliases.update({int(a): int(b) for a, b in (s.get("evility_alias") or {}).items()})
    if len(specs) + len(HIRE_LIST) > CAROUSEL_CAP:
        ctx.log(f"  warning: the class lists have room for {CAROUSEL_CAP - len(HIRE_LIST)} new classes")
    # one-line descriptions of the Hire Character carousel -> StringListDataBase (kept sorted by id)
    descs = []
    st = database.load_table("StringListDataBase.dat", ctx.get(STRINGS))
    for n, (fam, s) in enumerate(sorted(specs.items())):
        if not s.get("hire_desc"):
            continue
        sid = DESC_BASE + n
        text = desc_text(s["hire_desc"])
        if text != s["hire_desc"]:
            ctx.log("  warning: class %s description is %d bytes; the menu field holds %d, "
                    "written truncated" % (fam, len(s["hire_desc"].encode("utf-8")), DESC_TEXT_MAX))
        row = next((r for r in st.rows if r["id"] == sid), None)
        if row is None:
            row = st.new_row()
            row.set("id", sid)
            st.rows.append(row)
        for L in LANGS:
            if f"name_{L}" in row:
                row.set(f"name_{L}", text, truncate=True)

        descs.append((fam, sid))
    if descs:
        st.rows.sort(key=lambda r: r["id"])
        ctx.put(STRINGS, st.to_bytes())
    from .wheelmeta import runtime_entries
    wheel_entries = runtime_entries(getattr(ctx, "_wheel_mod_specs", []))
    ctx.put(EXE_FILE, build_hooks(ctx.get(EXE_FILE), classes, auto, aliases, descs, specs=specs,
                                 wheel_entries=wheel_entries, wheel_page=getattr(ctx, "_wheel_page", WHEEL_PAGES)))
    _monster_pictures(ctx, specs)
    # Skill.dat is binary-searched in file order: new evility rows (appended by the db patches) go in id order
    vp = "Database/Database_0.dat/Skill.dat"
    if vp.lower() in ctx.outputs:
        t = database.load_table("Skill.dat", ctx.get(vp))
        if [r["id"] for r in t.rows] != sorted(r["id"] for r in t.rows):
            t.rows.sort(key=lambda r: r["id"])
            ctx.put(vp, t.to_bytes())
    if specs:
        ctx.log(f"  classes: {', '.join(s.get('name', str(f)) for f, s in sorted(specs.items()))} "
                f"(unlock flags {flag_of(classes[0], specs)}+, {len(aliases)} evility alias(es), {n_scripts} class script(s))")
    else:
        ctx.log(f"  evilities of their own: {len(aliases)} (each works like the evility it names)")


COMB = "Database/Database_0.dat/comb.dat"
RESIDENT = ("Anime/ANM_HI_JP.dat/anm_resident.lzs", "Anime/ANM_HI_EN.dat/anm_resident.lzs")


def registry_monster_sprites(declared):
    """{identity: unique.json doc} -> physical sprite numbers of the registry uniques declared kind "monster"."""
    return sorted({int(d["physical"]) for d in declared.values()
                   if d.get("kind") == "monster" and d.get("physical") is not None
                   and not d.get("shares_art_with")})          # D4-NPC1: the owner already keeps N+2 resident


def row_monster_sprites(rows, members, k=2):
    """sprite N of every monster-kind char row (body_type 1, unit_set_appearance 0x14014ea10 reads row+0x386) whose
    anm N+k is among `members` (lower-case ANM_HI_JP vpaths).  k=2: the build ships the placeholder loose, so it must
    go into anm_resident; k=0: the row has a body bank of its own.  NODRAW2: plain char.dat monster uniques (the 37
    DRPG monster-template packs) were neither class specs nor registry uniques and stayed invisible in battle."""
    out = []
    for r in rows:
        n = int(r["sprite_id"] or 0)
        if int(r["body_type"] or 0) == 1 and n and f"anime/anm_hi_jp.dat/anm{n + k:05d}.lzs" in members \
                and n not in out:
            out.append(n)
    return sorted(out)


def char_monster_sprites(ctx):
    """row_monster_sprites over the build's char.dat (every mod's rows applied), placeholders the build ships"""
    rows = getattr(ctx, "_monster_rows", None)
    if rows is None:
        if not hasattr(ctx, "get"):
            return []
        rows = database.load_table("char.dat", ctx.get(CHAR)).rows
    return row_monster_sprites(rows, ctx.outputs)


def _monster_pictures(ctx, specs):
    """a monster family's standing picture (sprite family + 2) as a block of the resident pack: the game takes it
    from there only (the Hire Character list crashed on a monster family without one: 2250, 2340 tested; the dummies
    2220-2240 have placeholders, which the class's own picture replaces).

    A registry monster unique (patches/characters/unique.json, kind "monster") needs the same for its leased physical
    sprite N: in battle `ui_sprite_set_anm` (0x14014e7e0) binds the unit to anim N+2 while bank N loads, and for a
    monster that is the owner's own anim, found only among loaded records.  A loose N+2 misses (0x1402f4b3a) and the
    body never draws (D4BANK-ID: Pringer X 643/645; every vanilla monster's N+2 is resident).  Design after
    Cryswar's Overlord d5_anm_resident.c (a placeholder per custom family merged into anm_resident; The Unlicense)."""
    from . import facepatch
    blocks = monster_picture_blocks(ctx, specs)
    if not blocks:
        return
    for vp in RESIDENT:
        k = vp.lower()
        try:
            raw = ctx.outputs[k][1] if k in ctx.outputs else ctx.fs.read_raw(vp)
        except KeyError:
            continue
        ctx.put(vp, facepatch.add_resident_blocks(raw, blocks, log=ctx.log if vp == RESIDENT[0] else None))


def humanoid_class_pictures(ctx, specs):
    """sprite family N of every humanoid class whose build ships anm N+2 loose (PAGECRASH2).

    A humanoid unit binds part slot 0 to N+2 while bank N loads (unit_bind_anm_owner 0x14014dfd0 ->
    unit_bind_part_anm 0x14014ed00); the render node caches that record by id (anm_node_resolve_bindings
    0x1402f6870, node+0x40) without a reference.  A loose N+2 package is released when its last holder lets go
    (game_frame -> anm_release_package 0x1402eee00), and the node keeps drawing from the freed record: a NULL texture
    (flush 0x1402f3744) or junk texture headers (anm_emit_node_geometry 0x1402f7a4c), the Recruiter D4-page crashes.
    Every vanilla humanoid row keeps N+2 in anm_resident, and anm_acquire_lzs (0x1403ffcb0) finds a resident id
    before it would load the loose file, so a resident N+2 is never released.  Families whose N+2 the build does
    not ship (a vanilla family's is already resident) are left alone."""
    out = getattr(ctx, "outputs", {}) or {}
    return [f for f in (sprite_family(i, s) for i, s in sorted(specs.items()) if class_kind(i, s) != 'monster')
            if f"anime/anm_hi_jp.dat/anm{f + 2:05d}.lzs" in out]


def monster_picture_blocks(ctx, specs):
    """{block id N+2: one-block AnmFile} that _monster_pictures adds to anm_resident (monster classes' families,
    humanoid classes that ship N+2 loose, registry monster uniques' physical sprites; the build's own anm N+2, else
    the game's)"""
    from . import outfits
    blocks = {}
    fams = [sprite_family(identity, spec) for identity, spec in sorted(specs.items())
            if class_kind(identity, spec) == 'monster']
    fams += humanoid_class_pictures(ctx, specs)
    fams += registry_monster_sprites(getattr(ctx, "_char_uniques", {}))
    fams += [n for n in char_monster_sprites(ctx) if n not in fams]
    for fam in fams:
        data = outfits._anm_data(ctx, fam + 2)
        if data is None:
            ctx.log(f"  warning: monster sprite {fam} has no standing picture anm{fam + 2:05d}")
            continue
        a = anm.load(data)
        b = next((x for x in a.blocks if x.id == fam + 2), a.blocks[0])
        i = a.blocks.index(b)
        tex = a.textures[b.tex_base:b.tex_base + len(b.texture_infos)]
        pal = a.palettes[b.pal_base:b.pal_base + len(b.palette_infos)]
        b.tex_base = b.pal_base = 0
        blocks[fam + 2] = anm.AnmFile([b], tex, pal) if i or len(a.blocks) > 1 else a
    return blocks


def _comb_slots(ctx, specs):
    """team-attack affinity (comb.dat: u32 count, u16 ids[256], u8 rates[256][256]): a family of its own gets the
    template family's row and column (the dummies have theirs).  The game finds a family by a 16-bit binary search
    over the first `count` ids (0x1400a0f90; not found: rate 30), so the ids stay sorted -- the matrix is reordered
    with them.  An id out of order made the search run away and the start-up load hang (tested).  256 at most."""
    import struct
    import numpy as np
    from .database import Row
    t = database.load_table("comb.dat", ctx.get(COMB))
    n = struct.unpack_from("<I", bytes(t.header.raw), 0)[0]
    ids = [int(r["id"]) for r in t.rows]
    M = np.array([np.frombuffer(bytes(r.raw[2:]), np.uint8) for r in t.rows])
    used = list(range(n))
    todo = [f for f in sorted(specs) if f not in ids[:n]]
    if not todo:
        return
    added = []
    dim = len(ids)
    for fam in todo:
        if len(used) >= dim:
            ctx.log(f"  warning: comb.dat is full: class {fam} gets no team-attack rates of its own")
            break
        slot = next(i for i in range(dim) if i not in used)
        tmpl = int(specs[fam]["template"]) // 10 * 10
        src = ids.index(tmpl) if tmpl in ids[:n] else None
        ids[slot] = fam
        if src is not None:
            M[slot, :] = M[src, :]
            M[:, slot] = M[:, src]
            M[slot, slot] = M[src, src]
        else:
            M[slot, :] = 30
            M[:, slot] = 30
        used.append(slot)
        added.append(fam)
    order = sorted(used, key=lambda i: ids[i])
    k = len(order)
    M2 = np.zeros_like(M)
    M2[:k, :k] = M[np.ix_(order, order)]
    ids2 = [ids[i] for i in order] + [0] * (dim - k)
    t.rows = [Row(t.schema, struct.pack("<H", ids2[i]) + M2[i].tobytes()) for i in range(dim)]
    hdr = bytearray(t.header.raw)
    struct.pack_into("<I", hdr, 0, k)
    t.header.raw = hdr
    ctx.put(COMB, t.to_bytes())
    ctx.log(f"  comb.dat: team-attack rates for class(es) {', '.join(map(str, added))}")


# ------------------------------------------------------------------------------------------ build
def _handler(ctx, mod, patch_dir):
    from .wheelmeta import runtime_entries
    loaded = load_specs(mod)
    wheel_mod_specs = list(getattr(ctx, "_wheel_mod_specs", [])) + [(dict(mod.meta), loaded)]
    # Validate across all enabled definitions before a later mod can replace one.
    runtime_entries(wheel_mod_specs)
    specs = getattr(ctx, "_class_specs", {})
    for s in loaded:
        s = dict(s)
        if os.path.exists(face_path(mod, s["family"])):
            s["_face"] = face_path(mod, s["family"])
        s["_faces"] = {j: face_path(mod, s["family"], j) for j in range(1, COLOURS)
                       if os.path.exists(face_path(mod, s["family"], j))}      # colours with a face of their own
        existing = specs.get(int(s['family']))
        if existing and int(s['family']) not in ALL_FAMILIES and (
                sprite_family(s['family'], existing) != sprite_family(s['family'], s)
                or class_kind(s['family'], existing) != class_kind(s['family'], s)):
            raise ValueError(f"registry class {s['family']} has conflicting persistent leases")
        specs[int(s["family"])] = s
    ctx._class_specs = specs
    ctx._wheel_mod_specs = wheel_mod_specs


def _evility_handler(ctx, mod, patch_dir):
    """patches/evilities/aliases.json {"new evility id": existing evility id}: a character's own evility (a new
    Skill.dat row with its own name and description) works like the existing one in game (the alias hook above)"""
    al = getattr(ctx, "_evility_aliases", {})
    for a, b in (mod.load_patch("evilities", "aliases.json") or {}).items():
        al[int(a)] = int(b)
    ctx._evility_aliases = al


register_patch_handler(FOLDER, _handler, order=45)
register_patch_handler("evilities", _evility_handler, order=45)
register_finalizer(_finalize)
