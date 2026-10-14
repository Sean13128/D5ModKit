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

from . import anm, database, dbpatch, exemap, sprites
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


def flag_of(cls):
    return FLAG_BASE + 6 * ALL_FAMILIES.index(cls // 10 * 10) + cls % 10


def spec_path(mod, family):
    return os.path.join(mod.patches_dir, FOLDER, f"class_{int(family)}.json")


def face_path(mod, family):
    return os.path.join(mod.patches_dir, FOLDER, f"face_{int(family)}.png")


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
    p = spec_path(mod, spec["family"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1, ensure_ascii=False)


def set_face(mod, family, image, mirror=False):
    from PIL import Image
    img = (Image.open(image) if isinstance(image, str) else image).convert("RGBA")
    if mirror:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    p = face_path(mod, family)
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
            row.set(k, text, truncate=True)


def fill_class(fs, mod, family, template, name, titles, help_lines=(), edit=None, log=print):
    """Rows family .. family+5 = copies of the template class's rank rows (in place: the dummy rows), with the class's
    own sprite / colour ids, names, description and the JobRank chain.  edit(row, rank) customises each row."""
    van, ed = _tables(fs, mod, CHAR)
    rows = {r["id"]: i for i, r in enumerate(ed.rows)}
    trows = {r["id"]: r for r in ed.rows}
    for k in range(6):
        src = trows[template + k]
        new = src.copy()
        new.set("id", family + k)
        new.set("sprite_id", family)
        new.set("color_id", family + k)
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
    set_langs(r, "desc", desc)
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


def add_personalities(fs, mod, family, template, names):
    """Character creation's personality choices (charPersonal.dat, 3 per class): voice group = 100 + (family - 1000)
    / 10.  Rows copied from the template class's group with new names; without them the creation screen crashes."""
    van, ed = _tables(fs, mod, PERSONAL)
    group, tgroup = 100 + (family - 1000) // 10, 100 + (template - 1000) // 10
    ed.rows[:] = [r for r in ed.rows if r["voice_group"] != group]
    src = sorted((r for r in ed.rows if r["voice_group"] == tgroup), key=lambda r: r["variant"])
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
    return {int(s["family"]) for m in mods for s in load_specs(m)}


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
    for m in mods:
        for f in m.list_files():
            mm = rx.search(f)
            if mm:
                taken.add(int(mm.group(1)))
    for f in (MONSTER_FAMILIES if monster else HUMAN_FAMILIES):
        if f in used:
            continue
        if f not in DUMMY_FAMILIES and ({f, f + 1, f + 2} | {10000 + f + j for j in range(COLOURS)}) & taken:
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
    save_spec(mod, dict(family=family, template=template, name=name, unlocked=unlocked, hire_desc=hire_desc,
                        evility_alias={}))
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
    save_spec(mod, dict(family=family, template=template, name=name, unlocked=unlocked, hire_desc=hire_desc,
                        evility_alias={}, drpg=uid))
    log(f"monster {name}: mod {mod.id}, class ids {family}-{family + 5}, sprite anm{family:05d}")
    return mod


def set_portraits(fs, mod, family, template, image):
    """anm 10000 + family + j (j = 0..9): the template class's portrait files with `image` (cut-in) drawn in."""
    import numpy as np
    from PIL import Image
    from .imgtools import remove_white_background
    img = Image.open(image) if isinstance(image, str) else image
    img = remove_white_background(img.convert("RGBA"))
    for j in range(COLOURS):
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
            t.data = anm._rgba_to_argb(np.asarray(img.resize((t.width, t.height), Image.LANCZOS))).tobytes()
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{10000 + family + j:05d}.lzs", a.to_bytes())


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


def _table_src(classes):
    nl = chr(10)
    return nl.join(["    .align 8", "cls_table:"] + [f"    .long {c}, {flag_of(c)}" for c in classes] +
                   ["    .long 0, 0"])


def _lookup_src(classes, auto):
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
        _table_src(classes),
        f"table_sym = {TABLE_VA:#x}",
        f"flags_sym = {FLAGS_VA:#x}",
    ])


def _setter_src(classes):
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
        _table_src(classes),
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


def _carousel_src(families):
    return chr(10).join([
        "    cmp rbp, 0x2f",
        f"    jl {CAROUSEL_LOOP:#x}",
        "    lea rbx, [rip + new_fams]",
        "cr_next:",
        "    mov esi, dword ptr [rbx]",
        "    test esi, esi",
        "    je cr_done",
        f"    cmp dword ptr [rdi + 0x208], {CAROUSEL_CAP}",
        "    jge cr_done",
        "    mov ecx, esi",
        f"    call {IS_UNLOCKED:#x}",
        "    test al, al",
        "    je cr_skip",
        "    movsxd rax, dword ptr [rdi + 0x208]",
        "    lea rdx, [rip + carousel_buf]",
        "    mov dword ptr [rdx + rax*8], esi",
        "    mov dword ptr [rdx + rax*8 + 4], 1",
        "    mov r15d, 1",
        "cr_rank:",
        "    lea ecx, [rsi + r15]",
        f"    call {IS_UNLOCKED:#x}",
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
STRINGS = "Database/Database_0.dat/StringListDataBase.dat"


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
BUF_SIZE = BUF_PROF + CLASSTAB_CAP * 4
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


def _generic_sites(exe):
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

    mon, hum_reg, hum_imm = [], [], []
    for m in re.finditer(re.escape(b"\x26\xf8\xff\xff"), code):          # disp32 -0x7da
        lea = lea_before(m.start(), "0x7da")
        t = lea and test(lea, "0x122")
        if not t or t[0] in GEN_SKIP:
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
            hum_imm.append(text.PointerToRawData + (i.address - start) + k)
    return mon, hum_reg, hum_imm


def _mon_stub(r1, mem, mid, back):
    lines = []
    for k, (lo, span) in enumerate(GEN_MON):
        lines += [f"    lea {r1}, {mem.replace('0x7da', hex(lo))}", f"    cmp {r1}, {span:#x}", "    jbe g_yes"]
    lines += [f"    mov {r1}, -1", f"    cmp {r1}, 0x122", "    jmp g_out",
              "g_yes:", f"    xor {r1}, {r1}", f"    cmp {r1}, 0x122",
              "g_out:", f"    lea {r1}, {mem}"]             # the value it had (lea keeps the flags)
    lines += [f"    {x}" for x in mid] + [f"    jmp {back:#x}"]
    return chr(10).join(lines)


def _hum_stub(r1, mem, mid, back):
    return chr(10).join([f"    lea {r1}, {mem}", f"    cmp {r1}, {GEN_HUM_SPAN:#x}"] + [f"    {x}" for x in mid]
                        + [f"    jmp {back:#x}"])


def generic_patch(exe, taken=()):
    """-> (exe with the human tests widened in place, [hooks] for the others); sites inside `taken` [(va, length)]
    (other hooks) are left alone"""
    import pefile
    from .exepatch import IMAGE_BASE
    mon, hum_reg, hum_imm = _generic_sites(exe)
    out = bytearray(exe)
    for off in hum_imm:
        out[off:off + 4] = GEN_HUM_SPAN.to_bytes(4, "little")
    pe = pefile.PE(data=exe, fast_load=True)
    busy = [(va, va + n) for va, n in taken]
    hooks = []
    for kind, lst in (("mon", mon), ("hum", hum_reg)):
        for va, n, r1, mem, mid, back in lst:
            if any(a < va + n and va < b for a, b in busy):
                continue
            off = pe.get_offset_from_rva(va - IMAGE_BASE)
            src = (_mon_stub if kind == "mon" else _hum_stub)(r1, mem, mid, back)
            hooks.append((va, bytes(exe[off:off + n]), src, 0xE9))
            busy.append((va, va + n))
    return bytes(out), hooks, (len(mon), len(hum_reg), len(hum_imm))


def build_hooks(exe, classes, auto, aliases, descs=()):
    """classes: every modded class rank id; auto: ranks unlocked from the start; aliases {new evility: existing}"""
    from .exepatch import add_hook_section
    hooks = []
    if classes:
        fams = sorted({c // 10 * 10 for c in classes})
        hooks += [(LOOKUP_VA, LOOKUP_ORIG, _lookup_src(classes, auto), 0xE9),
                  (SETTER_VA, SETTER_ORIG, _setter_src(classes), 0xE9),
                  (HIRE_VA, HIRE_ORIG, _hire_src(fams[:CLASSTAB_CAP - 1 - len(HIRE_LIST)]), 0xE9),
                  (CAROUSEL_VA, CAROUSEL_ORIG, _carousel_src(fams), 0xE9)]
        hooks += _reloc_hooks(exe)
    if descs:
        hooks.append((DESC_VA, DESC_ORIG, _desc_src(descs), 0xE9))
    if aliases:
        hooks.append((EVI_VA, EVI_ORIG, _evility_src(aliases), 0xE9))
    if any(outside_vanilla(c // 10 * 10) for c in classes):
        exe, gen, _ = generic_patch(exe, [(va, len(orig)) for va, orig, _, _ in hooks])
        hooks += gen
    if not hooks:
        return exe
    return add_hook_section(exe, SECTION, hooks, writable=True,
                            shared_bytes=bytes(BUF_SIZE) if classes else b"")


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
        for p in CLASS_SCRIPTS + (MONSTER_SCRIPTS if is_monster(fam) else ()):
            for k in range(10):
                src = vev.get(p + t + k)
                if src is None:
                    continue
                nid = p + int(fam) + k
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


def _finalize(ctx):
    from .gamefs import EXE_FILE
    specs = getattr(ctx, "_class_specs", {})
    own_aliases = getattr(ctx, "_evility_aliases", {})        # characters' own evilities (patches/evilities)
    if not specs and not own_aliases:
        return
    n_scripts = _class_scripts(ctx, specs) if specs else 0
    if specs:
        _comb_slots(ctx, specs)
    classes, auto, aliases = [], [], dict(own_aliases)
    for fam, s in sorted(specs.items()):
        classes += [fam + k for k in range(6)]
        if s.get("unlocked", True):
            auto.append(fam)
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
        row = next((r for r in st.rows if r["id"] == sid), None)
        if row is None:
            row = st.new_row()
            row.set("id", sid)
            st.rows.append(row)
        for L in LANGS:
            if f"name_{L}" in row:
                row.set(f"name_{L}", s["hire_desc"], truncate=True)
        descs.append((fam, sid))
    if descs:
        st.rows.sort(key=lambda r: r["id"])
        ctx.put(STRINGS, st.to_bytes())
    ctx.put(EXE_FILE, build_hooks(ctx.get(EXE_FILE), classes, auto, aliases, descs))
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
                f"(unlock flags {flag_of(classes[0])}+, {len(aliases)} evility alias(es), {n_scripts} class script(s))")
    else:
        ctx.log(f"  evilities of their own: {len(aliases)} (each works like the evility it names)")


COMB = "Database/Database_0.dat/comb.dat"
RESIDENT = ("Anime/ANM_HI_JP.dat/anm_resident.lzs", "Anime/ANM_HI_EN.dat/anm_resident.lzs")


def _monster_pictures(ctx, specs):
    """a monster family's standing picture (sprite family + 2) as a block of the resident pack: the game takes it
    from there only (the Hire Character list crashed on a monster family without one: 2250, 2340 tested; the dummies
    2220-2240 have placeholders, which the class's own picture replaces)"""
    from . import facepatch, outfits
    blocks = {}
    for fam in sorted(specs):
        if not is_monster(fam):
            continue
        data = outfits._anm_data(ctx, fam + 2)
        if data is None:
            ctx.log(f"  warning: monster class {fam} has no standing picture anm{fam + 2:05d}")
            continue
        a = anm.load(data)
        b = next((x for x in a.blocks if x.id == fam + 2), a.blocks[0])
        i = a.blocks.index(b)
        tex = a.textures[b.tex_base:b.tex_base + len(b.texture_infos)]
        pal = a.palettes[b.pal_base:b.pal_base + len(b.palette_infos)]
        b.tex_base = b.pal_base = 0
        blocks[fam + 2] = anm.AnmFile([b], tex, pal) if i or len(a.blocks) > 1 else a
    if not blocks:
        return
    for vp in RESIDENT:
        k = vp.lower()
        try:
            raw = ctx.outputs[k][1] if k in ctx.outputs else ctx.fs.read_raw(vp)
        except KeyError:
            continue
        ctx.put(vp, facepatch.add_resident_blocks(raw, blocks, log=ctx.log if vp == RESIDENT[0] else None))


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
    specs = getattr(ctx, "_class_specs", {})
    for s in load_specs(mod):
        s = dict(s)
        if os.path.exists(face_path(mod, s["family"])):
            s["_face"] = face_path(mod, s["family"])
        specs[int(s["family"])] = s
    ctx._class_specs = specs


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
