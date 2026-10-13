"""Outfit system: an in-game 'Outfit' list in the unit menu that switches a unit between char.dat rows.

The feature itself (unit menu entry, outfit switching, per-outfit custom colours, faces) comes from the
"Outfit System" mod (patches/outfits/system.json); content mods only add outfits and need it enabled.

Mod data: patches/outfits/outfits.json
    {"pairs": [[550, 470]],               # [base class id, outfit class id]
     "names": {"470": "Swimsuit"},        # menu name of every outfit (default "Outfit N")
     "own_sprites": [9550, 9551],         # outfit sprites that carry their own full animation set
     "hide": [473]}                       # other mods' outfits this mod takes out of the Outfit list (e.g. an
                                          # outfit made into a character of its own, d5lib.charstudio); their
                                          # rows and files stay, so units wearing them keep working
    patches/outfits/face_470.png          # optional face picture (status panel / character list)
The outfit row re-uses an unused 'dummy' unique slot (id < 1000, so the game treats it as a unique
character and no row is inserted -> old saves stay valid).  It is a copy of the base row (same stats,
skills, name) with its own sprite number and its own colour id (= the slot id), which selects the face
(resident block 9017, animation = colour id) and the portrait / cut-in (anm 10000 + colour id).
At build time every enabled mod's outfits are collected: the exe gets the menu code (d5lib.exepatch),
StringListDataBase the menu strings, the resident sprite pack the faces (d5lib.facepatch).
"""
import json
import os
import pickle

from . import anm, database, dbpatch, exemap, exepatch, sprites
from .gamefs import EXE_FILE
from .modsys import register_patch_handler, register_finalizer

LABEL_ID = 40006        # "Outfit"
HELP_ID = 40007         # help line of the outfit entries
DEFAULT_ID = 40008      # "Default"
MORE_ID = 40009         # "More outfits" (the next page of a long list, exepatch.OUTFIT_PAGE per page)
NAME_BASE = 40010       # outfit names: 40010, 40011, ...
STRINGS = "Database/Database_0.dat/StringListDataBase.dat"
CHAR = "Database/Database_0.dat/char.dat"
RESIDENT = ("Anime/ANM_HI_JP.dat/anm_resident.lzs", "Anime/ANM_HI_EN.dat/anm_resident.lzs")
LANGS = ("JP", "EN", "FR", "CHN", "KOR")
LABELS = {"JP": "衣装", "EN": "Outfit", "FR": "Tenue", "CHN": "服裝", "KOR": "의상"}
HELPS = {"JP": "衣装を変更します", "EN": "Change into another outfit.", "FR": "Changer de tenue.",
         "CHN": "更換服裝。", "KOR": "의상을 변경합니다."}
DEFAULTS = {"JP": "デフォルト", "EN": "Default", "FR": "Par défaut", "CHN": "預設", "KOR": "기본"}
MORES = {"JP": "次の衣装へ", "EN": "More outfits...", "FR": "Autres tenues...", "CHN": "更多服裝", "KOR": "다른 의상"}
# Own colour ids for outfits: the game keys a character's graphics by colour id -- status/Status face
# (resident block 9017, anim 10000 + colour), framed battle face (9017, anim = colour), skill cut-in
# name banner (block 9018), portrait / cut-in (anm 10000 + colour), small list icons (texture.dat face
# atlases, SMALL_FACE_IDS).  All of them are created for the outfit's colour id (= its slot).
OWN_COLOUR_IDS = True     # for slots in SMALL_FACE_IDS (every colour-keyed resource is provided)
# small face icons (character list rows, 48 / 64 px): texturedatabase ids of the face cells the game
# uses for a colour id.  Verified in game: colour 470 -> cell 1 of wf_unique02 (colours 10..490 map to
# 10835 / 11652 + colour/10; 500+ start the next atlas).  Colours 470-490 belong only to the unused
# 'Unique Dummy' rows, so these outfit slots get their own colour id and list icon.  Other slots keep
# the base character's colour id (own sprite, faces in status / battle and portrait still work; the
# list icon is then the normal face).
SMALL_FACE_IDS = {470: (10882, 11699), 480: (10883, 11700), 490: (10884, 11701)}
SMALL_FACE_FILES = [(10836, 10881, "wf_unique01_48px.txf"), (10881, 10886, "wf_unique02_48px.txf"),
                    (10886, 10923, "wf_unique03_48px.txf"), (11653, 11698, "wf_unique01_64px.txf"),
                    (11698, 11703, "wf_unique02_64px.txf"), (11703, 11740, "wf_unique03_64px.txf")]
TEXTURES = "Start/Start_JP.dat/texture.dat"
# unused unique rows ('Unique Dummy' / 'DLC Dummy') that can hold outfits
FREE_SLOTS = [470, 480, 490, 950, 960, 970, 980, 990]
# more slots: new char.dat rows (unique ids below 1000 that the game doesn't use).  The game sorts the table by
# id, so later rows move; the kit's runtime re-points old saves' units (d5lib/native/d5rows.inc.c).
# (498 / 499 would need anm00500 / 00501, which are Seraphina's)
EXTRA_SLOTS = [i for d in (470, 480, 490) for i in range(d + 1, d + 10) if i < 498]


def _data(mod):
    return mod.load_patch("outfits", "outfits.json") or {}


def load(mod):
    return _data(mod).get("pairs", [])


def load_own(mod):
    return _data(mod).get("own_sprites", [])


def load_names(mod):
    return {int(k): v for k, v in _data(mod).get("names", {}).items()}


def outfit_name(mod, slot):
    return load_names(mod).get(int(slot)) or "Outfit"


def save(mod, pairs, own_sprites=None, names=None):
    if own_sprites is None:
        own_sprites = load_own(mod)
    if names is None:
        names = load_names(mod)
    data = {"pairs": [list(map(int, p)) for p in pairs]}
    slots = {int(p[1]) for p in pairs}
    names = {str(k): v for k, v in names.items() if int(k) in slots and v}
    if names:
        data["names"] = names
    if own_sprites:
        data["own_sprites"] = sorted({int(x) for x in own_sprites})
    hide = _data(mod).get("hide")
    if hide:
        data["hide"] = hide
    # own sprites alone (a new character before its outfits) keep the file: the exe's layer hook reads them
    mod.save_patch("outfits", "outfits.json", data if pairs or own_sprites or hide else None)
    # outfit content needs the Outfit System mod
    req = list(mod.meta.get("requires") or [])
    if pairs and not is_system_mod(mod) and SYSTEM_MOD_ID not in req:
        mod.meta["requires"] = req + [SYSTEM_MOD_ID]
        mod.save_meta()


def set_name(mod, slot, name):
    names = load_names(mod)
    names[int(slot)] = name.strip()
    save(mod, load(mod), names=names)


def face_path(mod, slot):
    return os.path.join(mod.patches_dir, "outfits", f"face_{int(slot)}.png")


def parts_path(mod, sprite):
    """Part info of an outfit sprite's colours (colorvariants.repartition), kept so the presets can be
    re-derived later -- also after recolouring parts in Sprites & Colors."""
    return os.path.join(mod.patches_dir, "outfits", f"parts_{int(sprite)}.json")


def _save_parts(mod, sprite, info):
    os.makedirs(os.path.dirname(parts_path(mod, sprite)), exist_ok=True)
    with open(parts_path(mod, sprite), "w", encoding="utf-8") as f:
        json.dump(info, f)


def _load_parts(mod, sprite):
    try:
        with open(parts_path(mod, sprite), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def set_face(mod, slot, image, mirror=False):
    """Store the outfit's face picture (any size; shown 204x204 in the status panel).  mirror: flip it
    horizontally (the game's faces look to the left)."""
    from PIL import Image
    img = Image.open(image) if isinstance(image, str) else image
    img = img.convert("RGBA")
    if mirror:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    p = face_path(mod, slot)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    img.save(p)


# ------------------------------------------------------------------------------------------ build
def _ensure_strings(ctx, names):
    """names: {string id: text} for the outfit names (all languages use the same text)."""
    t = database.load_table("StringListDataBase.dat", ctx.get(STRINGS))
    rows = {r["id"]: r for r in t.rows}
    fixed = [(LABEL_ID, LABELS), (HELP_ID, HELPS), (DEFAULT_ID, DEFAULTS), (MORE_ID, MORES)]
    fixed += [(sid, {L: text for L in LANGS}) for sid, text in sorted(names.items())]
    for sid, texts in fixed:
        row = rows.get(sid)
        if row is None:
            row = t.new_row()
            row.set("id", sid)
            t.rows.append(row)
            rows[sid] = row
        for L in LANGS:
            if f"name_{L}" in row:
                row.set(f"name_{L}", texts[L])
    t.rows.sort(key=lambda r: r["id"])
    ctx.put(STRINGS, t.to_bytes())


def _groups(pairs, names, rows=None, hidden=()):
    """-> ([(group, class id, label id)] menu records, {string id: text}, bases, {base: [slots]}, {slot: outfit
    key}).  A generic pair [F, T] gives one group per rank: F+k with T+k (outfit key T: name, face).
    hidden: outfit keys taken out of the list (records with label 0: still members of the group, like legacy ids,
    so a unit wearing one keeps its character's identity and can switch back)."""
    bases, members, aliases, key_of = [], {}, [], {}
    for a, b in pairs:
        a, b = int(a), int(b)
        if a >= 1000 and b < 1000:      # legacy row that only leads back to a character
            aliases.append((a, b))
            continue
        ks = generic_tiers(rows, a) if (a >= 1000 and rows is not None) else [0]
        for k in ks:
            base, slot = a + k, b + k
            key_of[slot] = b
            if base not in members:
                bases.append(base)
                members[base] = []
            if slot not in members[base]:
                members[base].append(slot)
    strings, records, name_ids = {}, [], {}
    for g, base in enumerate(bases):
        records.append((g, base, DEFAULT_ID))
        k = 0
        for slot in members[base]:
            if key_of.get(slot, slot) in hidden:
                records.append((g, slot, 0))
                continue
            k += 1
            text = names.get(key_of.get(slot, slot)) or f"Outfit {k}"
            if text not in name_ids:
                name_ids[text] = NAME_BASE + len(name_ids)
                strings[name_ids[text]] = text
            records.append((g, slot, name_ids[text]))
    for a, b in aliases:
        g = next((g for g, c, _ in records if c == b), None)
        if g is not None:
            records.append((g, a, 0))
    return records, strings, bases, members, key_of


def own_colour(slot):
    """True when the outfit slot gets its own colour id (= the slot: own faces, banner, portrait and list icon --
    slots without a game cell for the list icon get a new one, see _add_icons)."""
    return OWN_COLOUR_IDS


def small_face_ids(colour):
    """(48px, 64px) texturedatabase ids of a colour id's small face (verified: 470, 550)."""
    colour = int(colour)
    if colour in SMALL_FACE_IDS:
        return SMALL_FACE_IDS[colour]
    if 10 <= colour < 500 and colour % 10 == 0:
        return 10835 + colour // 10, 11652 + colour // 10
    if 500 <= colour < 870 and colour % 10 == 0:
        return 10886 + (colour - 500) // 10, 11703 + (colour - 500) // 10
    return None


def _small_face_cell(ctx, tid):
    """(vpath, raw txf, rect) of a small face cell."""
    from . import txf
    tdb = database.load_table("texturedatabase.dat", ctx.get("Database/Database_0.dat/texturedatabase.dat"))
    rects = {r["id"]: (r["x_EN"], r["y_EN"], r["w_EN"], r["h_EN"]) for r in tdb.rows}
    name = next((n for lo, hi, n in SMALL_FACE_FILES if lo <= tid < hi), None)
    if not name or tid not in rects:
        return None
    vp = f"{TEXTURES}/{name}"
    return vp, ctx.get(vp), rects[tid]


def _copy_small_faces(ctx, src_ids, dst_ids):
    """Copy the base character's small faces into the outfit's cells (outfit without a face picture)."""
    from . import txf
    for s_id, d_id in zip(src_ids, dst_ids):
        src, dst = _small_face_cell(ctx, s_id), _small_face_cell(ctx, d_id)
        if not src or not dst:
            continue
        sx, sy, sw, sh = src[2]
        face = txf.to_image(src[1]).crop((sx, sy, sx + sw, sy + sh))
        vp, raw, (x, y, w, h) = dst
        atlas = txf.to_image(raw)
        from PIL import Image
        atlas.paste(Image.new("RGBA", (w, h), (0, 0, 0, 0)), (x, y))
        atlas.paste(face.resize((w, h), Image.LANCZOS), (x, y))
        ctx.put(vp, txf.from_image(atlas, raw))


def _paint_small_faces(ctx, tex_ids, img):
    """Draw the face picture into the small face atlas cells (texturedatabase ids)."""
    from PIL import Image
    from . import txf
    tdb = database.load_table("texturedatabase.dat", ctx.get("Database/Database_0.dat/texturedatabase.dat"))
    rects = {r["id"]: (r["x_EN"], r["y_EN"], r["w_EN"], r["h_EN"]) for r in tdb.rows}
    for tid in tex_ids:
        name = next((n for lo, hi, n in SMALL_FACE_FILES if lo <= tid < hi), None)
        if not name or tid not in rects:
            continue
        vp = f"{TEXTURES}/{name}"
        raw = ctx.get(vp)
        atlas = txf.to_image(raw)
        x, y, w, h = rects[tid]
        atlas.paste(Image.new("RGBA", (w, h), (0, 0, 0, 0)), (x, y))
        atlas.paste(img.resize((w, h), Image.LANCZOS), (x, y))
        ctx.put(vp, txf.from_image(atlas, raw))


def _sync_outfit_copies(ctx, mod):
    """Colour edits are made on the outfit sprite N (Sprites & Colors); its copy N+1 and the small
    standing pictures (N+2, slot+2) follow automatically."""
    from . import ownanim
    own = {int(x) for x in load_own(mod)}
    try:
        rows = {r["id"]: r for r in database.load_table("char.dat", ctx.get(CHAR)).rows}
    except Exception:
        return
    for a, slot in load(mod):
        if int(a) >= 1000 or slot not in rows:
            continue
        N = rows[slot]["sprite_id"]
        vp = f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"
        if not mod.has_file(vp):
            continue
        raw = ctx.get(vp)
        main = None
        if N in own and N + 1 in own:
            ctx.put(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.bytes_with_id(raw, N, N + 1))
        for icon_id in (N + 2, int(slot) + 2):
            ivp = f"Anime/ANM_HI_JP.dat/anm{icon_id:05d}.lzs"
            if mod.has_file(ivp):
                icon = anm.load(ctx.get(ivp))
                if icon.palettes and all(t.indexed for t in icon.textures):
                    main = main or anm.load(raw)
                    ctx.put(ivp, _sync_palettes(icon, main).to_bytes())


SYSTEM_FILE = "system.json"      # patches/outfits/system.json marks the Outfit System mod
SYSTEM_MOD_ID = "Outfit_System"


def is_system_mod(mod):
    return bool(mod.load_patch("outfits", SYSTEM_FILE))


def _handler(ctx, mod, patch_dir):
    if is_system_mod(mod):
        ctx._outfit_system = mod.name
    pairs = getattr(ctx, "_outfit_pairs", [])
    for p in load(mod):
        if tuple(p) not in {tuple(x) for x in pairs}:
            pairs.append(list(p))
    ctx._outfit_pairs = pairs
    hidden = getattr(ctx, "_outfit_hidden", set())
    hidden.update(int(x) for x in _data(mod).get("hide", []))
    ctx._outfit_hidden = hidden
    own = getattr(ctx, "_outfit_own", set())
    own.update(int(x) for x in load_own(mod))
    ctx._outfit_own = own
    names = getattr(ctx, "_outfit_names", {})
    names.update(load_names(mod))
    ctx._outfit_names = names
    faces = getattr(ctx, "_outfit_faces", {})
    for a, b in load(mod):
        if os.path.exists(face_path(mod, b)):
            faces[int(b)] = face_path(mod, b)
    ctx._outfit_faces = faces
    from . import eventpose
    events = getattr(ctx, "_outfit_events", set())
    events.update((slot, e, n) for slot, v in eventpose.load(mod).items() for e, n in v.items())
    ctx._outfit_events = events
    if load(mod):
        _sync_outfit_copies(ctx, mod)


def _finalize(ctx):
    """After every mod: the menu strings, colour ids, faces and the exe code for all collected outfits, and the
    own colour ids, faces and list icons of new unique characters (d5lib.newchars)."""
    from . import facepatch, newchars
    pairs = getattr(ctx, "_outfit_pairs", [])
    outfit_ids = {int(b) for _, b in pairs}
    hidden = getattr(ctx, "_outfit_hidden", set()) & outfit_ids
    if hidden:                                 # still outfits of their group (faces, identity), just not listed
        ctx.log(f"  outfits hidden from the Outfit list: {', '.join(map(str, sorted(hidden)))}")
    if pairs and not getattr(ctx, "_outfit_system", None):
        ctx.log("  warning: outfits found, but the 'Outfit System' mod is not enabled: no Outfit menu in game")
        pairs = []
    if not pairs and CHAR.lower() not in ctx.outputs:
        return
    t = database.load_table("char.dat", ctx.get(CHAR))
    rows = {r["id"]: r for r in t.rows}
    synced = _follow_base(rows, pairs)
    if synced:
        ctx.log(f"  outfits: {synced} outfit row(s) follow their character's changes (stats, skills, evilities ...)")
    chars = newchars.find(t, database.load_table("char.dat", ctx.fs.read(CHAR)), outfit_ids) \
        if OWN_COLOUR_IDS else {}
    classes = getattr(ctx, "_class_specs", {})
    if not pairs and not chars and not classes:
        return
    class_sprites = {n for fam in classes for n in (fam, fam + 1)}
    exe, face_list, banners, icon_owners, changed = None, [], [], [], False
    if pairs:
        ctx._outfit_own = set(getattr(ctx, "_outfit_own", set())) | class_sprites
        exe, face_list, banners, icon_owners, changed = _finalize_outfits(ctx, pairs, t, rows)
    if chars:
        changed |= _finalize_characters(ctx, chars, rows, face_list, banners, icon_owners)
    if classes:
        _finalize_classes(ctx, classes, face_list, icon_owners)
    if changed or synced:
        ctx.put(CHAR, t.to_bytes())
    if exe is None:
        exe = ctx.get(EXE_FILE)
        lone = set(getattr(ctx, "_outfit_own", set())) | class_sprites     # new characters' own animation sets too
        if lone:
            exe = exepatch.build_layer_patch(exe, lone)
    if icon_owners:
        exe = _install_icons(ctx, exe, icon_owners)
    if pairs:
        # the game recognises its characters by class id: a unit in an outfit must still count as its character
        from . import identitypatch
        records, _, bases, _, _ = _groups(pairs, {}, rows)
        exe = identitypatch.patch(exe, identitypatch.class_map(records, bases), log=ctx.log)
    # own animation blocks numbered 10000+ would be drawn at the portraits' 0.67 size
    from . import scalepatch
    own_all = set(getattr(ctx, "_outfit_own", set())) | class_sprites
    exe = scalepatch.patch(exe, own_all, log=ctx.log)
    # humanoid own sprites numbered above 2000 must not count as monsters (monster families keep their companion file)
    monsters = {n for fam, spec in classes.items() if 2000 <= int(spec.get("template", 0)) < 3000 for n in (fam, fam + 1)}
    exe = scalepatch.humanoid_patch(exe, own_all - monsters, log=ctx.log)
    # skill scripts branch on the caster's sprite number (event poses, offsets, hit timings per character)
    exe = scalepatch.script_sprite_patch(exe, _script_sprites(ctx, pairs, rows, chars, classes, own_all),
                                         log=ctx.log)
    # ... and the event poses they spawn come in the outfit's look (d5lib.eventpose)
    if pairs:
        from . import eventpose
        slots = {int(b) for _, b in pairs}
        exe = eventpose.patch(exe, [x for x in getattr(ctx, "_outfit_events", ()) if x[0] in slots], log=ctx.log)
    ctx.put(EXE_FILE, exe)
    for vp in (RESIDENT if face_list or banners else ()):
        try:
            raw = ctx.fs.read_raw(vp)
        except KeyError:
            continue
        ctx.put(vp, facepatch.add_faces(raw, face_list, banners=banners,
                                        grow_now=int(os.environ.get("D5_FACE_GROW_TEST") or 0)))


LOOK_FIELDS = {"id", "sprite_id", "color_id"}


def _follow_base(rows, pairs):
    """An outfit is its character in other clothes: its char.dat row (a copy of the character's, made when the outfit
    was) follows the character's row as all the mods left it -- stats, aptitudes, skills, evilities, Overload, names
    -- so a change to the character applies whatever it wears.  Its own: the look (sprite, colour id) and, for a
    humanoid outfit of a monster-type character, the body fields it got from its humanoid template.  -> rows changed"""
    n = 0
    for a, b in pairs:
        a, b = int(a), int(b)
        if a >= 1000 or a == b or a not in rows or b not in rows:
            continue
        A, B = rows[a], rows[b]
        keep = set(LOOK_FIELDS)
        if A["body_type"] != B["body_type"]:
            keep |= set(HUMANOID_FIELDS) | {k for k in A.keys() if k.startswith("mastery_")}
        changed = False
        for f in A.keys():
            if f not in keep and A[f] != B[f]:
                B.set(f, A[f])
                changed = True
        n += changed
    return n


def _script_sprites(ctx, pairs, rows, chars, classes, own):
    """{kit sprite: the vanilla sprite the skill scripts should see (scalepatch.script_sprite_patch)}: an outfit's
    own sprite -> its character's, a new class's -> its template class's (their animations follow those).  Outfits
    wearing another vanilla sprite (an alternate form) keep theirs: the scripts know those.  New characters and
    their outfits keep their own number too: they move like their template (Laharl-chan for the Disgaea RPG ones),
    which the scripts don't single out, while the character they show (Usalia) may have branches of her own."""
    van = {r["id"]: r for r in database.load_table("char.dat", ctx.fs.read(CHAR)).rows}

    def vanilla_sprite(cid):
        r = van.get(cid) if cid not in chars else None
        return int(r["sprite_id"]) if r is not None else None

    out = {}

    def put(sprite, target):
        if target is not None and int(sprite) in own and int(sprite) != target:
            out.setdefault(int(sprite), target)

    if pairs:
        _, _, bases, members, _ = _groups(pairs, {}, rows)
        for b in bases:
            target = vanilla_sprite(b)
            for slot in members[b]:
                if slot in rows:
                    put(rows[slot]["sprite_id"], target)
    for fam, spec in classes.items():
        put(fam, vanilla_sprite(int(spec.get("template", 0))))
    return out


def _finalize_outfits(ctx, pairs, t, rows):
    """-> (exe, face list, banners, list icon owners, char.dat changed)"""
    own = getattr(ctx, "_outfit_own", set())
    names = getattr(ctx, "_outfit_names", {})
    faces = getattr(ctx, "_outfit_faces", {})
    faces_by_key = dict(faces)
    records, strings, bases, members, key_of = _groups(pairs, names, rows, getattr(ctx, "_outfit_hidden", ()))
    _ensure_strings(ctx, strings)
    changed = False
    for base in bases:
        for slot in members[base]:
            if slot in rows and base in rows:
                want = slot if own_colour(slot) else rows[base]["color_id"]
                if rows[slot]["color_id"] != want:
                    rows[slot].set("color_id", want)
                    changed = True
    # faces: the status panel / Status screen face is animation 10000 + colour id of resident block
    # 9017; an outfit with a face picture gets animation 10000 + its class id (a copy of the base
    # character's face animation showing the picture) and the exe picks it while the outfit is worn
    from PIL import Image
    face_list, face_map, banners = [], [], []
    anims = face_anim_ids(ctx.fs)
    faces = {slot: faces[key_of.get(slot, slot)] for b_ in bases for slot in members[b_]
             if key_of.get(slot, slot) in faces}
    for base in bases:
        tmpl = rows[base]["color_id"] if base in rows else base
        for slot in members[base]:
            if is_generic(slot):
                # generic rank: face anims of its own colour id, from the base rank's
                img = Image.open(faces[slot]).convert("RGBA") if slot in faces else None
                for new, src in ((slot, tmpl), (10000 + slot, 10000 + tmpl)):
                    if src in anims:
                        face_list.append((new, src, img))
                if img is not None:
                    face_map.append((slot, 10000 + slot))
                continue
            if own_colour(slot):
                banners.append((slot, tmpl))
                if slot not in faces:
                    face_list.append((10000 + slot, 10000 + tmpl, None))
                    face_list.append((slot, tmpl, None))
                    if small_face_ids(tmpl):
                        _copy_small_faces(ctx, small_face_ids(tmpl), SMALL_FACE_IDS[slot])
            if slot in faces:
                img = Image.open(faces[slot]).convert("RGBA")
                face_list.append((10000 + slot, 10000 + tmpl, img))   # status panel / Status screen
                face_list.append((slot, tmpl, img))                   # framed face (battle)
                face_map.append((slot, 10000 + slot))
                if slot in SMALL_FACE_IDS:
                    _paint_small_faces(ctx, SMALL_FACE_IDS[slot], img)
    monster_pairs = [(int(rows[b_]["sprite_id"]), int(rows[sl]["sprite_id"])) for b_ in bases for sl in members[b_]
                     if b_ in rows and sl in rows and int(rows[b_]["body_type"]) == 1
                     and rows[sl]["sprite_id"] != rows[b_]["sprite_id"]]
    if monster_pairs:
        _monster_scripts(ctx, monster_pairs)
    exe = ctx.fs.read(EXE_FILE)  # vanilla exe (installer backup when already patched)
    looks = _looks(records, rows)
    # generic families: the extra colours (ids T+6 .. T+9) get faces like the ranks
    for a, b in pairs:
        a, b = int(a), int(b)
        if a >= 1000 and b >= 1000:
            img = Image.open(faces_by_key[b]).convert("RGBA") if b in faces_by_key else None
            for j in range(GENERIC_COLOURS):
                if b + j in rows:
                    continue
                for new, src in ((b + j, a + j), (10000 + b + j, 10000 + a + j)):
                    if src in anims:
                        face_list.append((new, src, img))
    exe = exepatch.build_outfit_patch(exe, records, LABEL_ID, HELP_ID, sorted(own), face_map, looks=looks,
                                      more_label=MORE_ID)
    owners = _outfit_icon_owners(ctx, pairs, rows, faces_by_key) if OWN_COLOUR_IDS else []
    if any(n > 3 for _, n in looks.values()):
        ctx.needs_runtime = True        # more looks than colour sets: the runtime keeps each look's colours
    ctx.log(f"  outfits: {sum(len(m) for m in members.values())} outfit(s) for {len(bases)} character(s), "
            f"{len(faces)} face picture(s), {len(own)} own-animation sprite(s)")
    return exe, face_list, banners, owners, changed


def _anm_data(ctx, n):
    """anm n as the build has it (a mod's file, else the game's), or None"""
    vp = f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs"
    if vp.lower() in ctx.outputs:
        return ctx.outputs[vp.lower()][1]
    try:
        return ctx.fs.read(sprites.sprite_vpath(ctx.fs, n, "EN"))
    except Exception:
        return None


def _finalize_classes(ctx, classes, face_list, owners):
    """New generic classes (d5lib.newclasses): faces of colours family .. family+9 copied from the template class's
    (with the face picture), and one list icon for them."""
    from PIL import Image
    anims = face_anim_ids(ctx.fs)
    for fam, s in sorted(classes.items()):
        tmpl = int(s["template"])
        img = Image.open(s["_face"]).convert("RGBA") if s.get("_face") else None
        for j in range(GENERIC_COLOURS):
            for new, src in ((fam + j, tmpl + j), (10000 + fam + j, 10000 + tmpl + j)):
                if src in anims:
                    face_list.append((new, src, img))
        icon = img if img is not None else base_face_image(ctx.fs, tmpl)
        if icon is not None:
            owners.append((fam, [fam + j for j in range(GENERIC_COLOURS)], icon))


def _finalize_characters(ctx, chars, rows, face_list, banners, owners):
    """New unique characters (d5lib.newchars): colour id = class id, with the template's colour-keyed graphics
    copied to it (the face picture, when the mod has one, in its faces and list icon).  -> char.dat changed"""
    from PIL import Image
    pics = getattr(ctx, "_char_faces", {})
    anims = face_anim_ids(ctx.fs)
    changed = False
    for cid, tmpl in sorted(chars.items()):
        r = rows[cid]
        img = Image.open(pics[cid]).convert("RGBA") if cid in pics else None
        if tmpl is not None:
            r.set("color_id", cid)
            changed = True
            for new, src in ((10000 + cid, 10000 + tmpl), (cid, tmpl)):
                if src in anims:
                    face_list.append((new, src, img))
            banners.append((cid, tmpl))
            # cut-in / status portrait by colour id: the character's own portrait (sprite + 10000), else the template's
            vp = f"Anime/ANM_HI_JP.dat/anm{10000 + cid:05d}.lzs"
            if _anm_data(ctx, 10000 + cid) is None:
                for src in (r["sprite_id"] + 10000, 10000 + tmpl):
                    data = _anm_data(ctx, src)
                    if data is not None:
                        a = anm.load(data)
                        for b in a.blocks:
                            if b.id == src:
                                b.id = 10000 + cid
                        ctx.put(vp, a.to_bytes())
                        break
        icon = img if img is not None else (_small_face_image(ctx, tmpl) if tmpl is not None else None)
        if icon is not None:
            owners.append((cid, [cid], icon))
    ctx.log(f"  new characters: own colour ids for {', '.join(map(str, sorted(chars)))} "
            f"({sum(1 for c in chars if c in pics)} face picture(s))")
    return changed


# characters whose alternate forms already use the unit's colour set 1 (the game's own list): their outfits
# share one set of custom colours
FORM_CLASSES = {20, 80, 500, 780, 790, 800, 810}


def _looks(records, rows):
    """{class: (look index, looks in the group)}: the menu order of the visible members; a hidden legacy id is
    the visible look with the same sprite (else the first).  Groups touching FORM_CLASSES get 0 looks."""
    groups = {}
    for g, c, lab in records:
        groups.setdefault(g, []).append((int(c), int(lab)))
    out = {}
    for g, mem in groups.items():
        visible = [c for c, lab in mem if lab]
        n = len(visible)
        if any(c in FORM_CLASSES for c, _ in mem):
            n = 0
        spr = {c: rows[c]["sprite_id"] for c, _ in mem if c in rows}
        for c, lab in mem:
            if lab:
                k = visible.index(c)
            else:
                k = next((visible.index(v) for v in visible if spr.get(v) == spr.get(c)), 0)
            out[c] = (k, n)
    return out


register_patch_handler("outfits", _handler, order=40)
register_finalizer(_finalize)


# ------------------------------------------------------------------------------------------ authoring
def _char_tables(fs, mod):
    van = database.load_table("char.dat", fs.read(CHAR))
    ed = database.load_table("char.dat", fs.read(CHAR))
    patch = mod.load_patch("db", "char.dat.json")
    if patch:
        dbpatch.apply_patch(ed, patch)
    return van, ed


def _all_mods(mod):
    """Every mod next to `mod` (slots and sprite numbers must be unique across all mods)."""
    import os
    from .modsys import Mod
    root = os.path.dirname(mod.folder)
    return [Mod(os.path.join(root, d)) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]


def used_slots(mod):
    return {b for m in _all_mods(mod) for a, b in load(m)}


def free_slot(mod, fs=None):
    """a free char.dat id below 1000 for a unique character's outfit (slots.unique_pool: ~570 ids)"""
    from . import slots
    if fs is None:
        used = used_slots(mod) | slots.used_dummy_ids(mod)
        for s in FREE_SLOTS + EXTRA_SLOTS:
            if s not in used:
                return s
        raise RuntimeError("all outfit slots are in use")
    ids = slots.free_unique_ids(fs, mod, extra_taken=used_slots(mod))
    if not ids:
        raise RuntimeError("no free character id below 1000 is left for an outfit")
    return ids[0]


def outfit_slots(mod):
    """the outfit rows of a mod (pairs whose first id is a real character; ids >= 1000 there are legacy links)"""
    return {int(b) for a, b in load(mod) if int(a) < 1000 or int(b) >= 1000}


# sprite numbers for new looks, in groups of 10 (N, N+1, N+2 and portraits 10000+N, +1): 9500 .. 22760 first (the
# portrait must stay below 32768: char.dat's sprite id is signed 16 bit), then the free groups between 2400 and 9500
# (below: the game's generic class ranges 1000-1310 / 2010-2300 and the reserved class families)
SPRITE_NUMBERS = list(range(9500, 22760, 10)) + list(range(2400, 9500, 10))


def _free_sprite(fs, mod):
    used = sprites.used_sprite_numbers(fs)
    for f in (f for m in _all_mods(mod) for f in m.list_files()):
        n = f.split("/")[-1]
        if n.startswith("anm") and n[3:8].isdigit():
            used.add(int(n[3:8]))
    for n in SPRITE_NUMBERS:
        if not {n, n + 1, n + 2, n + 10000, n + 10001} & used:
            return n
    raise RuntimeError("no free sprite number (every free group 2400 .. 22760 is in use)")


def _clone(fs, mod, src, dst):
    """Copy anm `src` to `dst` in the mod (block ids renamed). Returns False if src doesn't exist."""
    try:
        vp = sprites.sprite_vpath(fs, src, "EN")
        a = anm.parse(fs.read(vp))
    except KeyError:
        return False
    for b in a.blocks:
        if b.id == src:
            b.id = dst
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{dst:05d}.lzs", a.to_bytes())
    return True


def _resident_icon(fs, block_id):
    """Standalone AnmFile holding resident block `block_id` (list icon) with its images (cached)."""
    import os
    path = os.path.join(sprites.CACHE_DIR, f"icon_{block_id}.pickle")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    res = anm.parse(fs.read("Anime/ANM_HI_JP.dat/anm_resident.lzs"))
    os.makedirs(sprites.CACHE_DIR, exist_ok=True)
    found = None
    for b in res.blocks:
        if b.id % 10 != 2 or not b.texture_infos:
            continue
        tex = res.textures[b.tex_base:b.tex_base + len(b.texture_infos)]
        pal = res.palettes[b.pal_base:b.pal_base + len(b.palette_infos)]
        nb = pickle.loads(pickle.dumps(b))
        nb.tex_base = nb.pal_base = 0
        f = anm.AnmFile([nb], [pickle.loads(pickle.dumps(t)) for t in tex], [pickle.loads(pickle.dumps(p)) for p in pal])
        with open(os.path.join(sprites.CACHE_DIR, f"icon_{b.id}.pickle"), "wb") as fh:
            pickle.dump(f, fh)
        if b.id == block_id:
            found = f
    return found


def create_outfit(fs, mod, base_id, sheet_sequences=None, log=print, name=None):
    """Add an outfit to unique character `base_id`.
    sheet_sequences: {(anim name, 'front'|'back'): [PIL frames]} from a frame-dump sheet, or None to
    start from a copy of the character's own sprite (repaint it later in Sprites & Colors).
    Returns dict(slot, sprite)."""
    # an outfit row is a copy of its character (same name in lists): the outfit belongs to the character
    if base_id in outfit_slots(mod):
        base_id = base_of(mod, base_id) or base_id
    if is_generic(base_id):
        return create_generic_outfit(fs, mod, base_id, sheet_sequences, log, name)
    van, ed = _char_tables(fs, mod)
    base_row = next((r for r in ed.rows if r["id"] == base_id), None)
    if base_row is None:
        raise ValueError(f"character id {base_id} not found")
    if base_id >= 1000:
        raise ValueError("outfits are for unique characters (class id below 1000)")
    slot = free_slot(mod, fs)
    si = next((i for i, r in enumerate(ed.rows) if r["id"] == slot), None)
    base_sprite = base_row["sprite_id"]
    N = _free_sprite(fs, mod)
    twin = base_row.copy()
    twin.set("id", slot)
    twin.set("sprite_id", N)
    if si is None:
        ed.rows.append(twin)            # a new row (see EXTRA_SLOTS)
    else:
        ed.rows[si] = twin
    mod.save_patch("db", "char.dat.json", dbpatch.diff_table(van, ed))
    log(f"outfit slot {slot} (copy of {base_row['name_EN']}), sprite anm{N:05d}")

    names = load_names(mod)
    if name:
        names[slot] = name
    save(mod, load(mod) + [[base_id, slot]], names=names)
    try:
        _create_files(fs, mod, base_row, slot, N, sheet_sequences, log)
    except BaseException:
        # don't leave a half-made outfit behind
        try:
            remove_outfit(fs, mod, slot)
        except Exception:
            pass
        raise
    return {"slot": slot, "sprite": N}


def create_drpg_outfit(fs, mod, base_id, uid, name, log=print, roots=None, hybrid=None, template=None):
    """Outfit of unique character `base_id` from Disgaea RPG unit `uid`: the character's complete animation set
    (shared motions + its own idle and skill poses) drawn with the unit's drawings by the exact pose map
    (drpgmap.build, specials=True; the character's own poses must have been learned from its DRPG twin first:
    drpgmap.learn_unique / tools/drpg_outfits.py learn), colour presets per part from the character's presets, the
    small standing picture, and the unit's face icon (mirrored) and cut-in when the DRPG assets have them.
    Monster-type characters (char.dat body_type 1, e.g. Usalia) need `hybrid`: dict(template=humanoid template
    sprite drawing the unit, sources=animation table, keep=animation ids drawn as in the game) -- the outfit keeps
    the character's own animation set drawn by the humanoid unit (d5lib.hybridanim).
    template: the vanilla character sprite whose animation set the sprite gets (default: the character's own; a
    character a mod adds has its sprite only in the mod -- create_drpg_character passes its template).
    Returns dict(slot, sprite, report)."""
    from . import colorvariants, drpg, drpgmap, ownanim
    if base_id in outfit_slots(mod):
        base_id = base_of(mod, base_id) or base_id
    van, ed = _char_tables(fs, mod)
    base_row = next((r for r in ed.rows if r["id"] == base_id), None)
    if base_row is None or base_id >= 1000:
        raise ValueError(f"unique character id {base_id} not found")
    base_sprite = int(template) if template else base_row["sprite_id"]
    monster = int(base_row["body_type"]) == 1
    if monster and not hybrid:
        raise ValueError(f"{base_row['name_EN']} is a monster-type unit: a humanoid DRPG unit needs hybrid=... "
                         f"(d5lib.hybridanim)")
    if not monster and not os.path.exists(drpgmap.own_map_path(base_sprite)):
        raise ValueError(f"{base_row['name_EN']}'s own poses are not mapped yet: run drpgmap.learn_unique "
                         f"(tools/drpg_outfits.py learn {base_id})")
    drpg.unit_sheets(uid, roots)                        # the unit's sprites must exist
    slot = free_slot(mod, fs)
    si = next((i for i, r in enumerate(ed.rows) if r["id"] == slot), None)
    N = _free_sprite(fs, mod)
    twin = base_row.copy()
    twin.set("id", slot)
    twin.set("sprite_id", N)
    if monster and hybrid.get("template"):  # a humanoid drawing: the name tag / cursor height of the template
        hrow = next((r for r in van.rows if r["id"] == hybrid["template"]), None)
        if hrow is not None:
            twin.set("height2", hrow["height2"])
    if si is None:
        ed.rows.append(twin)
    else:
        ed.rows[si] = twin
    mod.save_patch("db", "char.dat.json", dbpatch.diff_table(van, ed))
    names = load_names(mod)
    names[slot] = name
    save(mod, load(mod) + [[base_id, slot]], names=names)
    log(f"outfit '{name}': slot {slot} (copy of {base_row['name_EN']}), DRPG unit {uid} -> sprite anm{N:05d}")
    if monster:
        try:
            _create_hybrid_files(fs, mod, base_row, slot, N, uid, hybrid, log, roots)
        except BaseException:
            try:
                remove_outfit(fs, mod, slot)
            except Exception:
                pass
            raise
        return {"slot": slot, "sprite": N, "report": _create_hybrid_files.report}
    try:
        motion = sprites.motion_block(fs, 1, log)
        base = anm.parse(fs.read(sprites.sprite_vpath(fs, base_sprite, "EN")))
        known = int(uid) in drpgmap.load_hands()
        out, rep = drpgmap.build(fs, uid, base_sprite, N, log=log, roots=roots, auto_hands=not known, specials=True)
        save_source(mod, N, out)
        _save_parts(mod, N, colorvariants.repartition(out, base, fs=fs))
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs", out.to_bytes())
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(out, N + 1).to_bytes())
        save(mod, load(mod), set(load_own(mod)) | {N, N + 1})
        icon = _resident_icon(fs, base_sprite + 2)
        if icon is not None:
            icon = repaint_stand_icon(pickle.loads(pickle.dumps(icon)), base, motion, out)
            for new_id in (N + 2, slot + 2):
                f = pickle.loads(pickle.dumps(icon))
                f.blocks[0].id = new_id
                mod.write_file(f"Anime/ANM_HI_JP.dat/anm{new_id:05d}.lzs", f.to_bytes())
        portrait = base_row["color_id"] + 10000 if not template else int(template) + 10000
        _clone(fs, mod, portrait, N + 10000)
        _clone(fs, mod, portrait, slot + 10000)
        ex = drpg.unit_extras(uid, roots)
        if "icon" in ex:
            set_face(mod, slot, ex["icon"], True)       # DRPG faces look right, the game's look left
        if "cutin" in ex:
            set_cutin(fs, mod, slot, ex["cutin"], drpg=True)
    except BaseException:
        try:
            remove_outfit(fs, mod, slot)
        except Exception:
            pass
        raise
    return {"slot": slot, "sprite": N, "report": rep}


# a monster-type source made humanoid: the template's body, weapon masteries, (no) Magichange, overload and motion group
# (unk_0CA: Usalia's group 104 draws her companion next to her in attacks; a monster's overload plays its companion's
# animations, which the humanoid sprite doesn't have)
HUMANOID_FIELDS = ("body_type", "size_radius", "height", "height2", "magichange_type", "magichange_weapon",
                   "overload_id", "unk_0CA")


def create_drpg_character(fs, mod, source_id, template, uid, name, title=None, skills=None, desc=(), quest=None,
                          log=print, roots=None, stats_from=None):
    """A new recruitable unique character (an id below 1000 from slots.unique_pool) drawn from Disgaea RPG unit `uid`:
    a copy of character `source_id`'s row (stats, aptitudes, evilities ...) made a HUMANOID unit (body type, size and
    height of `template`), with the complete animation set of vanilla character sprite `template` drawn by the
    unit (drpgmap.build, specials=True; the template's own poses must be learned: drpgmap.learn_unique), its own
    face / list icon / portrait (newchars at install), the DRPG cut-in, optional description lines and a recruit
    quest (quest = dict(title, client, text); objective copied from 'Combat Lecture').
    skills: [(skill id, level)] replacing the learnset (None: keep the source's).
    stats_from: character whose base stats and aptitudes the new one gets (an NPC source is too weak to play).
    Returns dict(id, sprite, quest, report)."""
    from . import colorvariants, drpg, drpgmap, newchars, ownanim, slots
    van, ed = _char_tables(fs, mod)
    src = next((r for r in ed.rows if r["id"] == source_id), None)
    tpl = next((r for r in van.rows if r["id"] == template), None)
    if src is None or tpl is None:
        raise ValueError("source / template character not found")
    if not os.path.exists(drpgmap.own_map_path(tpl["sprite_id"])):
        raise ValueError(f"the template's own poses are not mapped: tools/drpg_outfits.py learn {template}")
    ids = slots.free_unique_ids(fs, mod, extra_taken=used_slots(mod))
    if not ids:
        raise RuntimeError("no free character id below 1000")
    cid = ids[0]
    N = _free_sprite(fs, mod)
    r = src.copy()
    r.set("id", cid)
    r.set("sprite_id", N)
    for f in HUMANOID_FIELDS + tuple(k for k in tpl.keys() if k.startswith("mastery_")):
        r.set(f, tpl[f])
    if stats_from is not None:
        sf = next(x for x in van.rows if x["id"] == stats_from)
        for f in (k for k in sf.keys() if k.startswith(("base_", "apt_"))):
            r.set(f, sf[f])
    for L in LANGS:
        if f"name_{L}" in r:
            r.set(f"name_{L}", name)
        if title and f"title_{L}" in r:
            r.set(f"title_{L}", title)
    if skills is not None:
        for k in range(1, 17):
            sk, lv = skills[k - 1] if k <= len(skills) else (0, 0)
            r.set(f"learn{k}_skill", sk)
            r.set(f"learn{k}_level", lv)
        r.set("learn_count", len(skills))
    if any(desc):
        hv, he = _table_pair(fs, mod, "charhelp.dat")
        si = next((i for i, h in enumerate(he.rows) if h["char_id"] == src["help_id"]), None)
        hr = he.add_row(copy_from=si)
        hid = _free_help_id(fs, mod)
        hr.set("id", hid)
        hr.set("char_id", hid)
        for k in range(3):
            for L in LANGS:
                if f"line{k + 1}_{L}" in hr:
                    hr.set(f"line{k + 1}_{L}", desc[k] if k < len(desc) else "")
        for fl in ("flag_off1", "flag_off2", "flag_off3"):
            if fl in hr:
                hr.set(fl, 0)
        r.set("help_id", hid)
        mod.save_patch("db", "charhelp.dat.json", dbpatch.diff_table(hv, he))
    ed.rows.append(r)
    mod.save_patch("db", "char.dat.json", dbpatch.diff_table(van, ed))
    qid = None
    if quest:
        qv, qe = _table_pair(fs, mod, "Quest.dat")
        qid, qslot = _free_quest(fs, mod)
        si = next((i for i, q in enumerate(qe.rows) if q["id"] == 1), 0)          # 'Combat Lecture'
        qr = qe.add_row(copy_from=si)
        qr.set("id", qid)
        text = dbpatch.quest_lines(quest.get("text", ""))
        for L in LANGS:
            for fld, val in (("name", quest.get("title", "A New Ally")), ("client", quest.get("client", name))):
                if f"{fld}_{L}" in qr:
                    qr.set(f"{fld}_{L}", val)
            for k in range(1, 6):
                if f"desc{k}_{L}" in qr:
                    qr.set(f"desc{k}_{L}", text[k - 1])
        qr.set("sort_order", qslot)
        qr.set("reward_type", 5)                      # recruit (questpatch creates the unit when needed)
        qr.set("reward_value", cid)
        qr.set("reward_count", 1)
        qr.set("important", 1)
        mod.save_patch("db", "Quest.dat.json", dbpatch.diff_table(qv, qe))
    log(f"character '{name}': id {cid}, DRPG unit {uid} -> sprite anm{N:05d}" + (f", recruit quest {qid}" if qid else ""))
    tsprite = tpl["sprite_id"]
    motion = sprites.motion_block(fs, 1, log)
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, tsprite, "EN")))
    known = int(uid) in drpgmap.load_hands()
    out, rep = drpgmap.build(fs, uid, tsprite, N, log=log, roots=roots, auto_hands=not known, specials=True)
    save_source(mod, N, out)
    _save_parts(mod, N, colorvariants.repartition(out, base, fs=fs))
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs", out.to_bytes())
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(out, N + 1).to_bytes())
    save(mod, load(mod), set(load_own(mod)) | {N, N + 1})          # own animation set: the exe's layer hook
    icon = _resident_icon(fs, tsprite + 2)
    if icon is not None:
        icon = repaint_stand_icon(pickle.loads(pickle.dumps(icon)), base, motion, out)
        icon.blocks[0].id = N + 2
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 2:05d}.lzs", icon.to_bytes())
    ex = drpg.unit_extras(uid, roots)
    if "icon" in ex:
        newchars.set_face(mod, cid, ex["icon"], True)
    _clone(fs, mod, tpl["color_id"] + 10000, N + 10000)
    if "cutin" in ex:
        _set_portrait(mod, N + 10000, ex["cutin"])
    return {"id": cid, "sprite": N, "quest": qid, "report": rep}


def _free_help_id(fs, mod):
    """a charhelp id (>= 4000: the game doesn't round it) no mod uses yet"""
    vp = "Database/Database_0.dat/charhelp.dat"
    allh = database.load_table("charhelp.dat", fs.read(vp))
    for m in _all_mods(mod):
        patch = m.load_patch("db", "charhelp.dat.json")
        if patch:
            dbpatch.apply_patch(allh, patch)
    return max({h["id"] for h in allh.rows} | {h["char_id"] for h in allh.rows} | {3999}) + 1


def _free_quest(fs, mod):
    """(quest id, progress slot) no mod uses yet: every mod's Quest.dat patch applied together"""
    vp = "Database/Database_0.dat/Quest.dat"
    allq = database.load_table("Quest.dat", fs.read(vp))
    for m in _all_mods(mod):
        patch = m.load_patch("db", "Quest.dat.json")
        if patch:
            dbpatch.apply_patch(allq, patch)
    qid = max(q["id"] for q in allq.rows if q["id"] < 2000) + 1
    probe = allq.add_row(copy_from=0)
    probe.set("id", qid)
    slot = dbpatch.free_quest_slot(allq, exclude=probe)
    return qid, slot


def rebuild_drpg_sprite(fs, mod, N, uid, template_sprite, log=print, roots=None):
    """Draw sprite N of this mod (a DRPG outfit or new character) again from Disgaea RPG unit `uid` with vanilla sprite
    `template_sprite`'s animation set, after a builder fix: same slot, number, faces, portraits and standing picture;
    new drawings, companion copy N+1, full-colour source and colour parts."""
    from . import colorvariants, drpgmap, ownanim
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, template_sprite, "EN")))
    known = int(uid) in drpgmap.load_hands()
    out, rep = drpgmap.build(fs, uid, template_sprite, N, log=log, roots=roots, auto_hands=not known, specials=True)
    save_source(mod, N, out)
    _save_parts(mod, N, colorvariants.repartition(out, base, fs=fs))
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs", out.to_bytes())
    if N + 1 in {int(x) for x in load_own(mod)}:
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(out, N + 1).to_bytes())
    return rep


def _table_pair(fs, mod, name):
    """(vanilla, vanilla + this mod's patch) of database table `name`"""
    vp = f"Database/Database_0.dat/{name}"
    van = database.load_table(name, fs.read(vp))
    ed = database.load_table(name, fs.read(vp))
    patch = mod.load_patch("db", f"{name}.json")
    if patch:
        dbpatch.apply_patch(ed, patch)
    return van, ed


# Cut-in / Status screen portraits (336 x 1080 textures) are full-bleed close-ups, like the game's own: the Status
# screen shows a window of the picture, a skill's cut-in the whole strip (on a white panel -- an empty margin shows as
# a white bar).  Disgaea RPG cut-ins (260 x 836) have exactly these proportions: they are scaled to fill the texture.
# (A portrait that looked too big and spilled out of the frame was drawn at the wrong scale: scalepatch.)
def fit_portrait(img, size=(336, 1080)):
    """an RGBA cut-in -> a portrait texture it fills (scaled to cover, centred across, kept at the top)"""
    from PIL import Image
    s = max(size[0] / img.width, size[1] / img.height)
    w, h = max(size[0], round(img.width * s)), max(size[1], round(img.height * s))
    x = (w - size[0]) // 2
    return img.convert("RGBA").resize((w, h), Image.LANCZOS).crop((x, 0, x + size[0], size[1]))


def _set_portrait(mod, anm_id, image):
    """the cut-in / status portrait file anm `anm_id` (in the mod) painted with the Disgaea RPG cut-in `image`"""
    import numpy as np
    from PIL import Image
    from .imgtools import remove_white_background
    vp = f"Anime/ANM_HI_JP.dat/anm{anm_id:05d}.lzs"
    a = anm.load(mod.read_file(vp))
    t = a.textures[0]
    img = Image.open(image) if isinstance(image, str) else image
    img = fit_portrait(remove_white_background(img, threshold=246, spread=10, upper=0.25), (t.width, t.height))
    t.data = anm._rgba_to_argb(np.asarray(img)).tobytes()
    mod.write_file(vp, a.to_bytes())


def _create_hybrid_files(fs, mod, base_row, slot, N, uid, hybrid, log, roots=None):
    """sprite files of a monster-type character's outfit drawn by a humanoid DRPG unit (create_drpg_outfit)"""
    from . import colorvariants, drpg, drpgmap, hybridanim, newclasses
    base_sprite = base_row["sprite_id"]
    tmpl = anm.parse(fs.read(sprites.sprite_vpath(fs, base_sprite, "EN")))
    if hybrid.get("pairs"):
        # a monster-type DRPG variant of the character (Santa Usalia on her companion): the monster pipeline, pose
        # for pose against the character's own twin (d5lib/data/monster_twins/<sprite>.json)
        from . import monstermap
        out, rep = monstermap.build(fs, uid, base_sprite, N, hybrid["pairs"], log=log, roots=roots)
    else:
        known = int(uid) in drpgmap.load_hands()
        hum, rep = drpgmap.build(fs, uid, hybrid["template"], N, log=log, roots=roots, auto_hands=not known,
                                 specials=True)
        out = hybridanim.compose(tmpl, hum, N, hybrid.get("sources"), hybrid.get("keep", ()), log)
        rep = dict(rep, animations=hybridanim.compose.report)
    save_source(mod, N, out)
    _save_parts(mod, N, colorvariants.repartition(out, tmpl, fs=fs))
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs", out.to_bytes())
    # the companion file keeps exactly the template companion's animation ids (a full copy hangs counterattacks);
    # neither file is an 'own sprite': monster-type units always play their sprite's own animations
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs",
                   newclasses.monster_companion(fs, out, base_sprite, N).to_bytes())
    icon = _resident_icon(fs, base_sprite + 2)
    if icon is not None:
        icon = repaint_stand_icon(pickle.loads(pickle.dumps(icon)), tmpl, None, out)
        for new_id in (N + 2, slot + 2):
            f = pickle.loads(pickle.dumps(icon))
            f.blocks[0].id = new_id
            mod.write_file(f"Anime/ANM_HI_JP.dat/anm{new_id:05d}.lzs", f.to_bytes())
    _clone(fs, mod, base_row["color_id"] + 10000, N + 10000)
    _clone(fs, mod, base_row["color_id"] + 10000, slot + 10000)
    ex = drpg.unit_extras(uid, roots)
    if "icon" in ex:
        set_face(mod, slot, ex["icon"], True)
    if "cutin" in ex:
        set_cutin(fs, mod, slot, ex["cutin"], drpg=True)
    _create_hybrid_files.report = rep


def _monster_scripts(ctx, sprite_pairs):
    """Monster-type characters' outfits: the engine starts a monster-type unit's normal attack as script event
    12010000 + sprite (12110000 / 12210000 when effects are skipped) -- without copies for the outfit sprite a
    counterattack waits forever (as the Dragon class did).  sprite_pairs: [(base sprite, outfit sprite)]"""
    from . import newclasses, script, scriptpatch, skills
    sf = ctx.parsed(skills.SCRIPT, script.ScriptFile.from_bytes)
    vev = {}
    for e in newclasses.vanilla_script(ctx).events:
        vev.setdefault(e.id, e)
    have = {e.id for e in sf.events}
    add = {}
    for bs, ns in sprite_pairs:
        for p in newclasses.MONSTER_SCRIPTS:
            for k in range(10):
                src = vev.get(p + bs + k)
                nid = p + ns + k
                if src is None or nid in have:
                    continue
                add[str(nid)] = scriptpatch.event_text(src, annotate=False).replace(f"event {src.id}",
                                                                                    f"event {nid}", 1)
    if add:
        scriptpatch.apply(sf, {"events": add})
        ctx.changed(skills.SCRIPT, script.ScriptFile.to_bytes)
        ctx.log(f"  outfits: {len(add)} normal-attack script(s) for monster-type characters' outfits")


def _create_files(fs, mod, base_row, slot, N, sheet_sequences, log):
    base_sprite = base_row["sprite_id"]
    # body sprite (+ companion)
    if sheet_sequences:
        write_sheet_sprite(fs, mod, base_sprite, N, sheet_sequences, log)
    else:
        _clone(fs, mod, base_sprite, N)
        _clone(fs, mod, base_sprite + 1, N + 1)
    # portrait / cut-in: the game loads anm (sprite number + 10000) -- the Status screen crashes when
    # it is missing -- and, with own colour ids, anm (10000 + colour id)
    _clone(fs, mod, base_row["color_id"] + 10000, N + 10000)
    _clone(fs, mod, base_row["color_id"] + 10000, slot + 10000)
    icon = _resident_icon(fs, base_sprite + 2)
    if icon is not None:
        for new_id in (N + 2, slot + 2):
            f = pickle.loads(pickle.dumps(icon))
            f.blocks[0].id = new_id
            mod.write_file(f"Anime/ANM_HI_JP.dat/anm{new_id:05d}.lzs", f.to_bytes())


def write_sheet_sprite(fs, mod, base_sprite, N, sheet_sequences, log=print):
    """Convert a frame-dump sheet into outfit sprite N (and its companion N+1): a sprite with its own
    complete animation set (see ownanim), registered so the exe patch lets the game use it."""
    from . import ownanim
    motion = sprites.motion_block(fs, 1, log)
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, base_sprite, "EN")))
    rep = {}
    out = ownanim.build(sheet_sequences, base, motion, N, report=rep)
    save_source(mod, N, out)
    from . import colorvariants
    # every part (hair, hoodie, skin ...) gets its own palette colours, presets derived per part
    _save_parts(mod, N, colorvariants.repartition(out, base, fs=fs))
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs", out.to_bytes())
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(out, N + 1).to_bytes())
    # small standing picture (N+2, and the outfit class slot's copy) redrawn from the new sprite
    icon = _resident_icon(fs, base_sprite + 2)
    if icon is not None:
        icon = repaint_stand_icon(pickle.loads(pickle.dumps(icon)), base, motion, out)
        ids = [N + 2] + [p[1] + 2 for p in load(mod) if outfit_sprite(fs, mod, p[1]) == N]
        for new_id in ids:
            f = pickle.loads(pickle.dumps(icon))
            f.blocks[0].id = new_id
            mod.write_file(f"Anime/ANM_HI_JP.dat/anm{new_id:05d}.lzs", f.to_bytes())
    save(mod, load(mod), set(load_own(mod)) | {N, N + 1})
    log(f"converted the sprite sheet: {rep.get('matched')} of {rep.get('cells')} original poses matched, "
        f"{rep.get('frames')} sheet frames used")
    return rep


def _quantize_variants(rgba, npal):
    """RGBA array -> (index array, [npal palettes]) using the outfit colour variants."""
    from PIL import Image
    import numpy as np
    from .frameconvert import recolor
    from .ownanim import VARIANTS
    q = Image.fromarray(rgba, "RGBA").quantize(colors=255, method=Image.Quantize.FASTOCTREE,
                                               dither=Image.Dither.NONE)
    qp = np.array(q.getpalette("RGBA")[:255 * 4], np.uint8).reshape(-1, 4)
    pal0 = np.zeros((256, 4), np.uint8)
    pal0[1:1 + len(qp)] = qp
    idx = np.asarray(q, np.int32) + 1
    idx[rgba[:, :, 3] == 0] = 0
    pals = []
    for p in range(npal):
        hue, sat, light = VARIANTS[p % len(VARIANTS)]
        pals.append(recolor(pal0, hue, sat, light) if (hue or sat or light) else pal0)
    return idx.astype(np.uint8), pals


def repaint_stand_icon(icon: anm.AnmFile, base_sprite: anm.AnmFile, motion_block, new_sprite: anm.AnmFile):
    """The small front/back standing picture (resident block N+2, 256x512, front left half, back right
    half) redrawn from the outfit sprite at the same scale and place as the original drawing.
    motion_block None: base_sprite has its own animations (monsters)."""
    import numpy as np
    from PIL import Image
    tex = np.asarray(anm.texture_to_image(icon, 0, 0))
    H, W = tex.shape[:2]
    if motion_block is None:            # monsters: the sprite carries its own animations
        view = base_sprite
    else:
        view = anm.bind_motion_set(anm.AnmFile([motion_block], [], []), 0, base_sprite)
    B = (-160, -300, 160, 40)
    out = np.zeros_like(tex)
    ids_old = {x["id"]: x["index"] for x in anm.list_animations(view)}
    ids_new = {x["id"]: x["index"] for x in anm.list_animations(new_sprite)}
    for half, aid in ((0, 1), (1, 7)):
        x0 = half * W // 2
        region = tex[:, x0:x0 + W // 2]
        ys, xs = np.nonzero(region[:, :, 3] > 0)
        if not len(ys) or aid not in ids_old or aid not in ids_new:
            continue
        old = np.asarray(anm.render_frame(view, ids_old[aid], time=0, bounds=B))
        oy, ox = np.nonzero(old[:, :, 3] > 0)
        scale = (ys.max() - ys.min() + 1) / (oy.max() - oy.min() + 1)
        # the original drawing's bottom-centre in the icon <-> in the full-size rendering
        tx = (xs.min() + xs.max()) / 2 - (ox.min() + ox.max()) / 2 * scale
        ty = ys.max() - oy.max() * scale
        new = anm.render_frame(new_sprite, ids_new[aid], time=0, bounds=B)
        nw, nh = max(1, round(new.width * scale)), max(1, round(new.height * scale))
        small = new.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGBA", (W // 2, H), (0, 0, 0, 0))
        canvas.paste(small, (int(round(tx)), int(round(ty))), small)   # paste clips negative offsets
        out[:, x0:x0 + W // 2] = np.asarray(canvas)
    idx, pals = _quantize_variants(out, len(icon.palettes))
    icon.textures[0].data = idx.tobytes()
    for p, pal in enumerate(pals):
        anm.set_palette(icon, p, pal)
    return icon


def base_of(mod, slot):
    """the character (or generic family) an outfit belongs to"""
    return next((int(a) for a, b in load(mod) if int(b) == int(slot) and (int(a) < 1000 or int(b) >= 1000)), None)


def set_cutin(fs, mod, slot, image, drpg=False):
    """Replace the outfit's cut-in / status portrait (anm 10000 + slot, one tall ARGB picture) with
    `image` (path or PIL image), resized to the original picture's size.  drpg: a Disgaea RPG cut-in (pure
    white background, close-up): only the white around it goes, scaled to fill (fit_portrait)."""
    import numpy as np
    from PIL import Image
    vp = f"Anime/ANM_HI_JP.dat/anm{slot + 10000:05d}.lzs"
    if not mod.has_file(vp):
        base = base_of(mod, slot)
        if base is None or not _clone(fs, mod, base + 10000, slot + 10000):
            raise ValueError("the base character has no portrait file to start from")
    a = anm.load(mod.read_file(vp))
    t = a.textures[0]
    N = next((int(r["sprite_id"]) for r in _char_tables(fs, mod)[1].rows if r["id"] == slot), None)
    img = Image.open(image) if isinstance(image, str) else image
    from .imgtools import remove_white_background
    if drpg:
        img = fit_portrait(remove_white_background(img, threshold=246, spread=10, upper=0.25), (t.width, t.height))
    else:
        img = remove_white_background(img).resize((t.width, t.height), Image.LANCZOS)
    if t.indexed:
        raise ValueError("unexpected indexed portrait texture")
    t.data = anm._rgba_to_argb(np.asarray(img)).tobytes()
    mod.write_file(vp, a.to_bytes())
    if N:                                      # the copy the game loads by sprite number
        for b in a.blocks:
            if b.id == slot + 10000:
                b.id = N + 10000
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 10000:05d}.lzs", a.to_bytes())


def regenerate_presets(fs, mod, slot, log=print):
    """Colour variants 1.. of the outfit sprite re-derived from the base character's own presets."""
    from . import colorvariants, ownanim
    N = outfit_sprite(fs, mod, slot)
    base_id = base_of(mod, slot)
    base_sprite = next(r for r in _char_tables(fs, mod)[1].rows if r["id"] == base_id)["sprite_id"]
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, base_sprite, "EN")))
    vp = f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"
    a = anm.load(mod.read_file(vp))
    info = _load_parts(mod, N)
    if info and all(0 < int(k) < 256 for k in info.get("entries", {})):
        colorvariants.derive_parts(a, base, info, fs=fs, log=log)    # parts known: follow the current colours
    else:
        _save_parts(mod, N, colorvariants.repartition(a, base, fs=fs))
    mod.write_file(vp, a.to_bytes())
    if N in load_own(mod):
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(a, N + 1).to_bytes())
    log(f"colour presets of anm{N:05d} re-derived from the character's presets (per part)")


def _sync_palettes(dst, src):
    """Give dst (e.g. the small standing picture) the colour variants of src: every colour of dst's
    first palette follows its nearest colour of src's first palette."""
    import numpy as np
    s0 = anm.get_palette(src, 0).astype(np.int32)
    d0 = anm.get_palette(dst, 0).astype(np.int32)
    valid = np.nonzero(s0[:, 3] > 0)[0]
    near = valid[np.argmin(((d0[:, None, :3] - s0[None, valid, :3]) ** 2).sum(-1), axis=1)]
    for p in range(1, len(dst.palettes)):
        sp = anm.get_palette(src, min(p, len(src.palettes) - 1))
        pal = d0.copy().astype(np.uint8)
        pal[1:, :3] = sp[near[1:], :3]
        anm.set_palette(dst, p, pal)
    return dst


def outfit_sprite(fs, mod, slot):
    _, ed = _char_tables(fs, mod)
    r = next((r for r in ed.rows if r["id"] == slot), None)
    return r["sprite_id"] if r is not None else None


def outfit_sprites(fs, mod):
    """{slot: sprite id} of all of a mod's outfits (one table load for all of them)"""
    slots = {int(s) for _, s in load(mod)}
    if not slots:
        return {}
    _, ed = _char_tables(fs, mod)
    return {r["id"]: r["sprite_id"] for r in ed.rows if r["id"] in slots}


def remove_outfit(fs, mod, slot):
    pairs = load(mod)
    pair = next((p for p in pairs if p[1] == slot), None)
    if not pair:
        return
    N = outfit_sprite(fs, mod, slot)
    van, ed = _char_tables(fs, mod)
    ids = set(range(slot, slot + 10)) if is_generic(slot) else {slot}
    vrows = {r["id"]: r for r in van.rows}
    keep = []
    for r in ed.rows:
        if r["id"] in ids:
            if r["id"] in vrows:             # a dummy row: back to the game's own
                keep.append(vrows[r["id"]].copy())
            continue                         # a row the outfit added
        keep.append(r)
    ed.rows[:] = keep
    d = dbpatch.diff_table(van, ed)
    mod.save_patch("db", "char.dat.json", None if dbpatch.is_empty(d) else d)
    if is_generic(slot):
        jvan, jed = _jobrank_tables(fs, mod)
        jed.rows[:] = [r for r in jed.rows if r["id"] not in ids]
        d = dbpatch.diff_table(jvan, jed)
        mod.save_patch("db", "JobRank.dat.json", None if dbpatch.is_empty(d) else d)
    if N:
        extra = range(N + 10000, N + 10000 + GENERIC_COLOURS) if is_generic(slot) else (N + 10000, N + 10001)
        for n in [N, N + 1, N + 2, *extra] + ([] if is_generic(slot) else [slot + 2, slot + 10000]):
            mod.remove_file(f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs")
    if os.path.exists(face_path(mod, slot)):
        os.remove(face_path(mod, slot))
    if N and not any(outfit_sprite(fs, mod, p[1]) == N for p in pairs if p[1] != slot) \
            and os.path.exists(parts_path(mod, N)):
        os.remove(parts_path(mod, N))
    save(mod, [p for p in pairs if p[1] != slot],
         [x for x in load_own(mod) if not N or x not in (N, N + 1)])


def preview_image(fs, mod, slot):
    """One picture of an outfit for the kit: standing (front / back), walk frames, face, cut-in."""
    from PIL import Image, ImageDraw
    N = outfit_sprite(fs, mod, slot)
    tiles = []
    if N:
        vp = f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"
        try:
            a = anm.load(mod.read_file(vp) if mod.has_file(vp) else fs.read(vp))
            src = a if sum(len(b.animations) for b in a.blocks) > 20 else sprites.preview_file(fs, a)
            ids = {x["id"]: x["index"] for x in anm.list_animations(src)}
            B = (-110, -230, 110, 20)
            for label, aid, times in (("front", 1, (0,)), ("back", 7, (0,)),
                                      ("walk", 21, (0, 6, 12, 18, 24, 30)), ("walk (back)", 27, (0, 12, 24))):
                if aid in ids:
                    for k, t in enumerate(times):
                        tiles.append((label if k == 0 else "", anm.render_frame(src, ids[aid], time=t, bounds=B)))
            # the colour presets (Strategy Assembly extra colours)
            while len(tiles) % 6:
                tiles.append(("", Image.new("RGBA", (220, 250))))
            if 1 in ids:
                for p in range(min(6, len(a.palettes))):
                    tiles.append((f"colour {p}" + (" (default)" if p == 0 else ""),
                                  anm.render_frame(src, ids[1], time=0, palette_index=p, bounds=B)))
        except Exception as e:
            tiles.append((f"sprite: {e}", Image.new("RGBA", (220, 250))))
    face = Image.open(face_path(mod, slot)).convert("RGBA") if os.path.exists(face_path(mod, slot)) else None
    cut = None
    for n in ([N + 10000] if N else []) + [int(slot) + 10000]:
        vp = f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs"
        if mod.has_file(vp):
            cut = anm.texture_to_image(anm.load(mod.read_file(vp)), 0, 0)
            break
    W = 220 * max(1, min(6, len(tiles))) + 20
    rows = (len(tiles) + 5) // 6
    cut_w = 190
    img = Image.new("RGBA", (W + cut_w + 230, max(rows * 270 + 20, 640)), (38, 70, 52, 255))
    d = ImageDraw.Draw(img)
    for k, (label, t) in enumerate(tiles):
        x, y = 10 + (k % 6) * 220, 10 + (k // 6) * 270
        img.alpha_composite(t.resize((220, 250)) if t.size != (220, 250) else t, (x, y + 18))
        if label:
            d.text((x + 4, y), label, fill=(255, 230, 120, 255))
    x0 = W + 10
    d.text((x0, 10), "face", fill=(255, 230, 120, 255))
    if face:
        f = face.copy()
        f.thumbnail((204, 204))
        img.alpha_composite(f, (x0, 30))
    else:
        d.text((x0, 40), "(character's normal face)", fill=(200, 200, 200, 255))
    d.text((x0 + 220, 10), "cut-in", fill=(255, 230, 120, 255))
    if cut:
        c = cut.copy()
        c.thumbnail((cut_w, 600))
        img.alpha_composite(c, (x0 + 220, 30))
    return img


# ------------------------------------------------------------------------------ hand-painted colour parts
def source_path(mod, sprite):
    """the outfit sprite as converted, before it was split into parts (full colours): parts are always rebuilt
    from it, so repeated part edits never lose shades"""
    return os.path.join(mod.patches_dir, "outfits", f"source_{int(sprite)}.anm")


def save_source(mod, sprite, a):
    p = source_path(mod, sprite)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(a.to_bytes())


def load_source(mod, sprite):
    """the full-colour source sprite, or None (older outfits: the current, already split sprite is used)"""
    p = source_path(mod, sprite)
    return anm.load(p) if os.path.exists(p) else None


def partmap_dir(mod, sprite):
    """painted parts kept in the mod (reapplied when the outfit's colours are rebuilt)"""
    return os.path.join(mod.patches_dir, "outfits", f"partmap_{int(sprite)}")


def export_folder(mod, slot, sprite):
    from .modsys import KIT_DIR
    safe = "".join(ch if ch.isalnum() else "_" for ch in outfit_name(mod, slot))
    return os.path.join(KIT_DIR, "partmaps", mod.id, f"{safe}_anm{int(sprite):05d}")


def export_partmap(fs, mod, slot, folder=None):
    """Sheets + current parts + legend of the outfit sprite for painting.  -> folder"""
    from . import partmap
    N = outfit_sprite(fs, mod, slot)
    a = anm.load(mod.read_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"))
    folder = folder or export_folder(mod, slot, N)
    rows = None
    if os.path.isdir(partmap_dir(mod, N)):          # continue from the last painted parts
        try:
            rows = partmap.propagate(a, partmap.read_painted(a, partmap_dir(mod, N)))
        except Exception:
            rows = None
    partmap.export(a, folder, name=f"{outfit_name(mod, slot)} (anm{N:05d})", rows=rows)
    return folder


def painting_sprite(fs, mod, slot):
    """(sprite number, the sprite parts are painted on: the full-colour source, duplicate colours merged)"""
    from . import colorvariants
    N = outfit_sprite(fs, mod, slot)
    a = load_source(mod, N) or anm.load(mod.read_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"))
    colorvariants._dedupe(a)
    return N, a


def painter_path(mod, sprite):
    return os.path.join(partmap_dir(mod, sprite), "painter.json")


def load_painter(mod, sprite):
    """saved part-painter state: names {part: name}, assign {colour index: part}, cleanup, eyes"""
    import json
    p = painter_path(mod, sprite)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    d["names"] = {int(k): v for k, v in d.get("names", {}).items()}
    d["assign"] = {int(k): int(v) for k, v in d.get("assign", {}).items()}
    return d


def save_painter(mod, sprite, state, overrides=None, learned=None):
    """state as load_painter; overrides {texture position: part per pixel (-1 = not painted)} -> override_<k>.png,
    learned (parts carried over from the reference poses, same form) -> learned_<k>.png"""
    import json
    from . import partmap
    d = partmap_dir(mod, sprite)
    os.makedirs(d, exist_ok=True)
    out = dict(state)
    out["names"] = {str(k): v for k, v in state.get("names", {}).items()}
    out["assign"] = {str(k): int(v) for k, v in state.get("assign", {}).items()}
    with open(painter_path(mod, sprite), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    for layer, rows in (("override", overrides), ("learned", learned)):
        if rows is None:
            continue
        for k, r in rows.items():
            p = os.path.join(d, f"{layer}_{k}.png")
            if (r >= 0).any():
                partmap.rows_image(r).save(p)
            elif os.path.exists(p):
                os.remove(p)


def load_overrides(mod, sprite, shapes, layer="override"):
    """{texture position: part per pixel (-1 = not painted)} from <layer>_<k>.png (override / learned)"""
    from . import partmap
    import numpy as np
    from PIL import Image
    leg = np.array(partmap.LEGEND, np.float64)
    out = {}
    for k, shape in enumerate(shapes):
        r = np.full(shape, -1, np.int32)
        p = os.path.join(partmap_dir(mod, sprite), f"{layer}_{k}.png")
        if os.path.exists(p):
            img = np.asarray(Image.open(p).convert("RGBA"))
            if img.shape[:2] == shape:
                d = np.linalg.norm(img[..., :3].astype(np.float64)[..., None, :] - leg[None, None], axis=-1)
                ok = (img[..., 3] >= 128) & (d.min(-1) <= partmap.MATCH)
                r[ok] = d.argmin(-1)[ok]
        out[k] = r
    return out


def base_sprite(fs, mod, slot):
    """the outfit's base character sprite (its colour presets are what the outfit's presets follow)"""
    base_id = base_of(mod, slot)
    num = next(r for r in _char_tables(fs, mod)[1].rows if r["id"] == base_id)["sprite_id"]
    return anm.parse(fs.read(sprites.sprite_vpath(fs, num, "EN")))


def apply_rows(fs, mod, slot, rows, log=print, sprite=None):
    """Rebuild the outfit sprite from parts: rows {texture index: part per pixel (-1 transparent)} on the
    painting sprite (painting_sprite).  Part N = in-game "Part N"; the colour presets are derived per part."""
    from . import colorvariants, ownanim, partmap
    N = outfit_sprite(fs, mod, slot)
    a = sprite if sprite is not None else painting_sprite(fs, mod, slot)[1]
    base_id = base_of(mod, slot)
    base_sprite = next(r for r in _char_tables(fs, mod)[1].rows if r["id"] == base_id)["sprite_id"]
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, base_sprite, "EN")))
    info = colorvariants.repartition_rows(a, base, rows, log=log, fs=fs)
    vp = f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"
    mod.write_file(vp, a.to_bytes())
    if N in load_own(mod):
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(a, N + 1).to_bytes())
    _save_parts(mod, N, info)
    keep = partmap_dir(mod, N)
    os.makedirs(keep, exist_ok=True)
    texs = [i for i, t in enumerate(a.textures) if t.indexed]
    for k, t in enumerate(texs):
        partmap.rows_image(rows[t]).save(os.path.join(keep, f"parts_{k}.png"))
    log(f"parts of anm{N:05d} rebuilt ({len({int(v) for r in rows.values() for v in set(r.ravel().tolist())} - {-1})} "
        "parts)")
    return N


def import_partmap(fs, mod, slot, folder, log=print):
    """Rebuild the outfit sprite's palette from painted parts_<k>.png files (see d5lib.partmap)."""
    import shutil
    from . import colorvariants, ownanim, partmap
    N = outfit_sprite(fs, mod, slot)
    vp = f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"
    a = load_source(mod, N) or anm.load(mod.read_file(vp))
    base_id = base_of(mod, slot)
    base_sprite = next(r for r in _char_tables(fs, mod)[1].rows if r["id"] == base_id)["sprite_id"]
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, base_sprite, "EN")))
    rows = partmap.import_rows(a, folder)
    info = colorvariants.repartition_rows(a, base, rows, log=log, fs=fs)
    mod.write_file(vp, a.to_bytes())
    if N in load_own(mod):
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(a, N + 1).to_bytes())
    _save_parts(mod, N, info)
    keep = partmap_dir(mod, N)
    os.makedirs(keep, exist_ok=True)
    for f in os.listdir(folder):
        if f.startswith("parts_") and f.endswith(".png"):
            shutil.copy2(os.path.join(folder, f), os.path.join(keep, f))
    log(f"parts of anm{N:05d} rebuilt from the painted map ({folder})")
    return N


def parts_preview(fs, mod, slot):
    """poses of the outfit with every part in its legend colour"""
    from . import partmap
    N = outfit_sprite(fs, mod, slot)
    a = anm.load(mod.read_file(f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"))
    motion = None if N in load_own(mod) else sprites.motion_block(fs, 1)
    return partmap.preview(a, motion)


def stabilize_outfit(fs, mod, slot, ref_slot, log=print):
    """Steady placement for an outfit made from unlabelled (DRPG) frames: its feet follow those of `ref_slot`
    (an outfit of the same character made from a labelled sheet) key by key -- see d5lib.stabilize.  Only
    pivots change; the sheets and the painted parts stay.  The full-colour source gets the same fix, so part
    edits later keep it."""
    from . import ownanim, stabilize
    N, R = outfit_sprite(fs, mod, slot), outfit_sprite(fs, mod, ref_slot)
    vp = f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"
    a = anm.load(mod.read_file(vp))
    ref = sprites.preview_file(fs, anm.load(mod.read_file(f"Anime/ANM_HI_JP.dat/anm{R:05d}.lzs")))
    pa = sprites.preview_file(fs, a)
    if pa is not a:
        raise ValueError(f"anm{N:05d} is not an own-animation sprite")
    fixes = stabilize.corrections(a, ref, log=log)
    n = stabilize.apply(a, fixes)
    stand = stabilize.stand_like_idle(a)
    stabilize.apply_cells(a, stand)
    mod.write_file(vp, a.to_bytes())
    if N in load_own(mod):
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(a, N + 1).to_bytes())
    src = load_source(mod, N)
    if src is not None:
        if len(src.blocks[0].keys) == len(a.blocks[0].keys):
            stabilize.apply(src, fixes)
            stabilize.apply_cells(src, stand)
            save_source(mod, N, src)
        else:
            log(f"  source_{N}.anm has other animation tables: not changed")
    log(f"anm{N:05d}: {n} frames placed steadily (following anm{R:05d}), stand pose = idle frame in "
        f"{len(stand)} places")
    return n


def lock_idle(fs, mod, slot, log=print, ref_slot=None):
    """Idle loops of the outfit sprite with the feet exactly still (stabilize.lock_idle_feet), in the sprite, its
    companion and the full-colour source"""
    from . import ownanim, stabilize
    N = outfit_sprite(fs, mod, slot)
    vp = f"Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"
    a = anm.load(mod.read_file(vp))
    fixes = stabilize.lock_idle_feet(sprites.preview_file(fs, a), log=log)
    stabilize.apply(a, fixes)
    if ref_slot is not None:
        R = outfit_sprite(fs, mod, ref_slot)
        ref = sprites.preview_file(fs, anm.load(mod.read_file(f"Anime/ANM_HI_JP.dat/anm{R:05d}.lzs")))
        ground = stabilize.idle_ground(sprites.preview_file(fs, a), ref, log=log)
        stabilize.apply(a, ground)
        fixes = {**fixes, **{k: fixes.get(k, 0) + v for k, v in ground.items()}}
    mod.write_file(vp, a.to_bytes())
    if N in load_own(mod):
        mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 1:05d}.lzs", ownanim.with_id(a, N + 1).to_bytes())
    src = load_source(mod, N)
    if src is not None and len(src.blocks[0].keys) == len(a.blocks[0].keys):
        stabilize.apply(src, fixes)
        save_source(mod, N, src)
    return len(fixes)


# ------------------------------------------------------------------------------------------ list icons
# Every outfit gets its own colour id (= its slot) and its own small face in the character list.  The game picks
# the list icon with 0x1401a2460(category, colour id) -> texturedatabase id (48 px; the 64 px one is +817), and
# 0x14019fbc0 finds the texture of a texturedatabase id by fixed id ranges.  Outfit slots without one of the
# game's own cells (SMALL_FACE_IDS) get new texturedatabase rows after the last one, drawn into the free cells of
# wf_unique02_48px / _64px (512 x 128: 20 / 16 cells, the game uses 4): one hook returns an outfit colour's row,
# the other gives those rows the unique02 textures.
ICON_SECTION = b".d5fi"
ICON_PICK_VA = 0x1401A2460        # sub rsp, 0x28 / movsx r11, cx
ICON_PICK_ORIG = bytes.fromhex("4883ec284c0fbfd9")
ICON_RES_VA = 0x14019FBC0         # xor eax, eax / mov [rip+..], rax   (texture of a texturedatabase id)
ICON_RES_ORIG = bytes.fromhex("33c0488905b70be607")
ICON_RES_STRUCT = 0x148000780     # the resolver's result: texture pointer, +8 row index
ICON_TEX48 = 0x140AA04B0          # wf_unique02_48px texture (ids 10881-10885)
ICON_TEX64 = 0x140AA0520          # wf_unique02_64px texture (ids 11698-11702)
ICON_64 = 817                     # the 64 px row = 48 px row + 817 (the list adds it)
ICON_FILES = ("wf_unique02_48px.txf", "wf_unique02_64px.txf")
ICON_USED = 4                     # cells of those atlases the game itself uses
ICON_BLOCK = 2 * ICON_64          # texture rows come in blocks: 817 48 px rows, then their 817 64 px rows
TEX_MAX = 16384                   # largest texture side (D3D11)


def icon_atlas_size(count):
    """(width, height) of the enlarged list icon atlases for `count` icons: 1024 wide (the game's 512 x 128 stays top
    left), as tall as needed in steps of 128; wider when 16384 isn't tall enough"""
    for w in (1024, 2048, 4096, 8192, TEX_MAX):
        need = max(-(-(ICON_USED + count) // (w // size)) * size for size in (48, 64))
        h = max(1024, -(-need // 128) * 128)
        if h <= TEX_MAX:
            return w, h
    raise ValueError(f"{count} list icons don't fit a {TEX_MAX} x {TEX_MAX} texture")


def icon_rows(first, k):
    """texture rows (48 px, 64 px) of icon k: blocks of 817 + 817, since the list adds 817 for the 64 px row"""
    b, i = divmod(k, ICON_64)
    r = first + b * ICON_BLOCK + i
    return r, r + ICON_64


def _icon_src(table):
    """table [(colour id, 48 px row id)]"""
    nl = chr(10)
    rows = ", ".join(f"{c}, {t}" for c, t in table) + ", 0, 0"
    return nl.join([
        "    movzx eax, dx",
        "    lea r9, [rip + icons]",
        "icon_loop:",
        "    mov r10d, dword ptr [r9]",
        "    test r10d, r10d",
        "    je icon_none",
        "    cmp r10d, eax",
        "    je icon_hit",
        "    add r9, 8",
        "    jmp icon_loop",
        "icon_hit:",
        "    mov eax, dword ptr [r9 + 4]",
        "    ret",
        "icon_none:",
        "    sub rsp, 0x28",
        "    movsx r11, cx",
        f"    jmp {exemap.at(ICON_PICK_VA, 8)}",
        "    .align 4",
        "icons:",
        "    .long " + rows,
    ])


def _icon_res_src(first, count):
    """texture rows first .. (blocks of 817 48 px rows + 817 64 px rows) -> the enlarged unique02 textures"""
    nl = chr(10)
    S = ICON_RES_STRUCT
    last48, last64 = icon_rows(first, count - 1)
    return nl.join([
        "    xor eax, eax",
        "    mov qword ptr [rip + res_struct], rax",
        f"    cmp edx, {first}",
        "    jl res_back",
        f"    cmp edx, {last64}",
        "    jg res_back",
        # (edx - first) % 1634 < 817: a 48 px row, else a 64 px one; past the last icon of its kind: not ours
        "    push rdx",
        f"    lea eax, [rdx - {first}]",
        "    xor edx, edx",
        f"    mov r10d, {ICON_BLOCK}",
        "    div r10d",
        "    mov r10d, edx",
        "    pop rdx",
        f"    cmp r10d, {ICON_64}",
        "    jl res_48",
        f"    cmp edx, {last64}",
        "    jg res_back",
        "    mov rax, qword ptr [rip + res_tex64]",
        "    jmp res_set",
        "res_48:",
        f"    cmp edx, {last48}",
        "    jg res_back",
        "    mov rax, qword ptr [rip + res_tex48]",
        "res_set:",
        "    mov qword ptr [rip + res_struct], rax",
        "    lea eax, [rdx - 0x2710]",
        "    mov dword ptr [rip + res_index], eax",
        "    lea rax, [rip + res_struct]",
        "    ret",
        "res_back:",
        "    xor eax, eax",
        f"    jmp {exemap.at(ICON_RES_VA, len(ICON_RES_ORIG))}",
        # symbols after their use: keystone makes [rip + symbol] rip-relative
        f"res_struct = {S:#x}",
        f"res_index = {exemap.at(S, 8)}",
        f"res_tex48 = {ICON_TEX48:#x}",
        f"res_tex64 = {ICON_TEX64:#x}",
    ])


def _new_icons(ctx, slots, images):
    """New list icons for `slots` (no cell of their own in the game): texturedatabase rows + atlas cells.
    images: {slot: PIL face}.  -> ([(colour id, 48 px row id)], first new row id, count)"""
    from PIL import Image
    from . import txf
    tpath = "Database/Database_0.dat/texturedatabase.dat"
    tdb = database.load_table("texturedatabase.dat", ctx.get(tpath))
    first = max(r["id"] for r in tdb.rows) + 1
    skip = int(os.environ.get("D5_ICON_TEST") or 0)       # testing: icons start at position `skip`
    count = len(slots) + skip
    langs = [k[2:] for k in tdb.rows[0].keys() if k.startswith("x_")]
    rects = {}
    atlas_size = icon_atlas_size(count)
    W = atlas_size[0]
    pos = {slot: skip + k for k, slot in enumerate(slots)}
    for k, slot in enumerate(slots):
        cell = ICON_USED + pos[slot]
        r48, r64 = icon_rows(first, pos[slot])
        rects[r48] = (cell % (W // 48) * 48, cell // (W // 48) * 48, 48)
        rects[r64] = (cell % (W // 64) * 64, cell // (W // 64) * 64, 64)
    # rows up to the last 64 px one (the ones in between stay empty): the table is indexed by id - 10000
    for tid in range(first, icon_rows(first, count - 1)[1] + 1):
        row = tdb.new_row()
        row.set("id", tid)
        x, y, s = rects.get(tid, (0, 0, 0))
        for L in langs:
            for key, v in (("x", x), ("y", y), ("w", s), ("h", s), ("draw_w", s), ("draw_h", s)):
                if f"{key}_{L}" in row:
                    row.set(f"{key}_{L}", v)
        tdb.rows.append(row)
    ctx.put(tpath, tdb.to_bytes())
    for name, size in zip(ICON_FILES, (48, 64)):
        vp = f"{TEXTURES}/{name}"
        raw = ctx.get(vp)
        old = txf.to_image(raw).convert("RGBA")
        atlas = Image.new("RGBA", atlas_size, (0, 0, 0, 0))
        atlas.paste(old, (0, 0))
        for k, slot in enumerate(slots):
            img = images.get(slot)
            if img is None:
                continue
            x, y, s = rects[icon_rows(first, pos[slot])[1 if size == 64 else 0]]
            atlas.paste(Image.new("RGBA", (s, s), (0, 0, 0, 0)), (x, y))
            atlas.paste(img.resize((s, s), Image.LANCZOS), (x, y))
        ctx.put(vp, txf.from_image(atlas, raw))
    return [(slot, icon_rows(first, pos[slot])[0]) for slot in slots], first, count


def _small_face_image(ctx, colour):
    """the game's small (64 px) face of a colour id, or None"""
    from . import txf
    ids = small_face_ids(colour)
    if not ids:
        return None
    cell = _small_face_cell(ctx, ids[1])
    if not cell:
        return None
    x, y, w, h = cell[2]
    return txf.to_image(cell[1]).crop((x, y, x + w, y + h)).convert("RGBA")


def _outfit_icon_owners(ctx, pairs, rows, faces):
    """[(outfit key, [colour ids], image)] for every outfit without a game cell of its own.  faces: {key: path}"""
    from PIL import Image
    owners = []
    for a, b in pairs:
        a, b = int(a), int(b)
        if a >= 1000 and b < 1000:
            continue                 # legacy link
        if b in SMALL_FACE_IDS or (b not in rows):
            continue
        if b in faces:
            img = Image.open(faces[b]).convert("RGBA")
        elif a >= 1000:
            img = base_face_image(ctx.fs, a)
        else:
            img = _small_face_image(ctx, rows[a]["color_id"] if a in rows else a)
        colours = [b + j for j in range(GENERIC_COLOURS)] if a >= 1000 else [b]
        owners.append((b, colours, img))
    return owners


def _install_icons(ctx, exe, owners):
    """owners [(key, [colour ids], image)] (outfits, new characters) -> exe with the list icon hooks"""
    if not owners:
        return exe
    keys = [k for k, _, _ in owners]
    rows_of, first, count = _new_icons(ctx, keys, {k: img for k, _, img in owners})
    row_of = dict(rows_of)
    table = [(c, row_of[k]) for k, cs, _ in owners if k in row_of for c in cs]
    exe = exepatch.add_hook_section(exe, ICON_SECTION, [
        (ICON_PICK_VA, ICON_PICK_ORIG, _icon_src(table), 0xE9),
        (ICON_RES_VA, ICON_RES_ORIG, _icon_res_src(first, count), 0xE9)])
    w, h = icon_atlas_size(count)
    ctx.log(f"  {count} list icon(s) of their own (texture rows {first}+, atlases {w} x {h})")
    return exe


# ------------------------------------------------------------------------------------------ generic classes
# A generic class is a family of char.dat rows F .. F+5 (the ranks Fighter, Warrior ... Battle Master), all drawn
# by sprite F with one palette per rank (colour id = the row id), portraits anm 10000+F .. +9, faces 9017 anims
# F+j / 10000+F+j and a rank chain in JobRank.dat.  An outfit for it is a whole new family T .. T+5 laid out the
# same way with T = its sprite number N: the game finds every graphic by the same rules as for its own classes.
# In the Outfit menu a unit of rank F+k switches to T+k (one menu group per rank), and ranking up inside the
# outfit follows the copied JobRank chain.  outfits.json keeps it as the pair [F, T] (both >= 1000).
JOBRANK = "Database/Database_0.dat/JobRank.dat"
GENERIC_COLOURS = 10           # palettes / portraits / faces per generic family (6 ranks + extra colours)


def is_generic(cls):
    return int(cls) >= 1000


def generic_family(cls):
    return int(cls) // 10 * 10


def generic_tiers(rows, fam):
    """rank offsets k with a char.dat row fam + k"""
    return [k for k in range(10) if fam + k in rows]


def _jobrank_tables(fs, mod):
    van = database.load_table("JobRank.dat", fs.read(JOBRANK))
    ed = database.load_table("JobRank.dat", fs.read(JOBRANK))
    patch = mod.load_patch("db", "JobRank.dat.json")
    if patch:
        dbpatch.apply_patch(ed, patch)
    return van, ed


def _free_generic_family(fs, mod, chars, jobs):
    """a sprite number N (multiple of 10) usable as a whole generic family: char.dat / JobRank ids N .. N+9 and
    anm N .. N+2, 10000+N .. 10000+N+9 all free, in every mod"""
    used = sprites.used_sprite_numbers(fs)
    for f in (f for m in _all_mods(mod) for f in m.list_files()):
        n = f.split("/")[-1]
        if n.startswith("anm") and n[3:8].isdigit():
            used.add(int(n[3:8]))
    ids = {r["id"] for r in chars.rows} | {r["id"] for r in jobs.rows}
    from . import slots
    for m in _all_mods(mod):
        ids |= slots.used_dummy_ids(m) if m.folder != mod.folder else set()
        for a, b in load(m):
            ids.add(int(b))
    n = 9500
    while n + 10000 + GENERIC_COLOURS <= 32767:
        fam = set(range(n, n + 10))
        if not fam & ids and not {n, n + 1, n + 2} & used and \
                not set(range(n + 10000, n + 10000 + GENERIC_COLOURS)) & used:
            return n
        n += 10
    raise RuntimeError("no free sprite number for a generic outfit")


def create_generic_outfit(fs, mod, base_id, sheet_sequences=None, log=print, name=None):
    """Outfit for generic class family of `base_id` (any rank).  -> dict(slot = new family id, sprite)"""
    F = generic_family(base_id)
    van, ed = _char_tables(fs, mod)
    rows = {r["id"]: r for r in ed.rows}
    tiers = generic_tiers(rows, F)
    if not tiers:
        raise ValueError(f"class {base_id} not found")
    jvan, jed = _jobrank_tables(fs, mod)
    T = N = _free_generic_family(fs, mod, ed, jed)
    for k in tiers:
        r = rows[F + k].copy()
        r.set("id", T + k)
        r.set("sprite_id", N)
        r.set("color_id", T + k)
        ed.rows.append(r)
    mod.save_patch("db", "char.dat.json", dbpatch.diff_table(van, ed))
    jrows = {r["id"]: r for r in jed.rows}
    for k in tiers:
        if F + k in jrows:
            r = jrows[F + k].copy()
            r.set("id", T + k)
            nxt = jrows[F + k]["next_id"]
            if nxt and generic_family(nxt) == F:
                r.set("next_id", T + nxt - F)
            jed.rows.append(r)
    mod.save_patch("db", "JobRank.dat.json", dbpatch.diff_table(jvan, jed))
    log(f"outfit family {T}-{T + max(tiers)} (copy of {rows[F]['name_EN']}), sprite anm{N:05d}")
    names = load_names(mod)
    if name:
        names[T] = name
    save(mod, load(mod) + [[F, T]], names=names)
    try:
        if sheet_sequences:
            write_sheet_sprite(fs, mod, F, N, sheet_sequences, log)
        else:
            _clone(fs, mod, F, N)
            _clone(fs, mod, F + 1, N + 1)
        for j in range(GENERIC_COLOURS):
            _clone(fs, mod, F + 10000 + j, N + 10000 + j)
        icon = _resident_icon(fs, F + 2)
        if icon is not None:
            f = pickle.loads(pickle.dumps(icon))
            f.blocks[0].id = N + 2
            mod.write_file(f"Anime/ANM_HI_JP.dat/anm{N + 2:05d}.lzs", f.to_bytes())
    except BaseException:
        try:
            remove_outfit(fs, mod, T)
        except Exception:
            pass
        raise
    return {"slot": T, "sprite": N}


def _face_file(fs=None):
    """the game's face block 9017 as an AnmFile (cached)"""
    path = os.path.join(sprites.CACHE_DIR, "face_block_9017.pickle")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    res = anm.parse(fs.read("Anime/ANM_HI_JP.dat/anm_resident.lzs"))
    b = next(x for x in res.blocks if x.id == 9017)
    tex = res.textures[b.tex_base:b.tex_base + len(b.texture_infos)]
    nb = pickle.loads(pickle.dumps(b))
    nb.tex_base = nb.pal_base = 0
    out = anm.AnmFile([nb], tex, [])
    with open(path, "wb") as f:
        pickle.dump(out, f)
    return out


def face_anim_ids(fs=None):
    return {a.id for a in _face_file(fs).blocks[0].animations}


def base_face_image(fs, colour):
    """the game's 204 px face picture of a colour id (status panel), or None"""
    try:
        f = _face_file(fs)
        items = anm.evaluate(f, ("id", 10000 + int(colour)), 0)
    except Exception:
        return None
    face = next((it for it in items if it.cell.w == 204), None)
    if face is None:
        return None
    c = face.cell
    return anm.texture_to_image(f, face.tex_global, 0).crop((c.x, c.y, c.x + c.w, c.y + c.h)).convert("RGBA")
