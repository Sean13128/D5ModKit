"""New unique characters (ids below 1000 that mods add, or the unused dummy rows they fill in): their own colour id,
so they get their own list icon, faces, skill name banner and cut-in instead of sharing their template's.

The game keys a character's graphics by the char.dat colour id.  A new character starts as a copy of its template
row, colour id included, so it would show the template's face everywhere.  At install time (outfits._finalize, which
also owns the list icon hook) every new unique character gets colour id = its class id and copies of the template's
colour-keyed graphics under that id: faces (resident block 9017, anims id / 10000 + id), name banner (9018), cut-in /
status portrait (anm 10000 + id, from the character's own portrait anm sprite + 10000) and a list icon.

Mod data: patches/characters/face_<id>.png   optional face picture (status panel, battle face, character list icon);
without it the template's faces are used.
"""
import os

from .modsys import register_patch_handler

FOLDER = "characters"


def face_path(mod, cid):
    return os.path.join(mod.patches_dir, FOLDER, f"face_{int(cid)}.png")


def set_face(mod, cid, image, mirror=False):
    """Store a new character's face picture (any size, square).  mirror: flip it (the game's faces look left)."""
    from PIL import Image
    img = Image.open(image) if isinstance(image, str) else image
    img = img.convert("RGBA")
    if mirror:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    p = face_path(mod, cid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    img.save(p)


def remove_face(mod, cid):
    if os.path.exists(face_path(mod, cid)):
        os.remove(face_path(mod, cid))


def is_new_character(row, vanilla_rows, outfit_ids=(), registry=()):
    """a unique row (id < 1000) that a mod added or a filled-in dummy row, and no outfit

    `registry` = {identity: declaration} for a unique that leases a registry identity (>= 10000) with a
    separate low physical row for its art (patches/characters/unique.json).  Its identity row is new by
    definition, and its colour id stays the leased physical row instead of becoming its class id.
    """
    from .slots import DUMMY_ROWS
    cid = row["id"]
    if cid >= 1000 or cid in outfit_ids:
        if cid in registry:
            if registry[cid].get("shares_art_with"):
                # D4-NPC1: the row draws with an owner pack's keys; that character already has its
                # faces, list icon and graphics id, and cloning another template over them is wrong.
                return False
            return row["color_id"] == int(registry[cid]["physical"])
        return False
    v = vanilla_rows.get(cid)
    if v is None:
        return True
    return cid in DUMMY_ROWS and (row["name_EN"] != v["name_EN"] or row["sprite_id"] != v["sprite_id"])


def find(char_table, vanilla_table, outfit_ids=(), registry=()):
    """{class id: template colour id (None when the row already has its own colour id)} of every new character

    A registry unique maps its identity to the declared donor colour, because its own colour id is the
    leased physical row (d5lib/nativeimports.unique_identity).
    """
    van = {r["id"]: r for r in vanilla_table.rows}
    out = {}
    for r in char_table.rows:
        if is_new_character(r, van, outfit_ids, registry):
            if r["id"] in registry:
                out[r["id"]] = int(registry[r["id"]]["template_colour"])
            else:
                out[r["id"]] = r["color_id"] if r["color_id"] != r["id"] else None
    return out


DECLARATION = "unique.json"


def load_declared(mod):
    """{identity: declaration} for this mod's registry uniques (patches/characters/unique.json)."""
    data = mod.load_patch(FOLDER, DECLARATION) or {}
    out = {}
    for doc in data.get("uniques") or ([data] if data.get("identity") else []):
        if isinstance(doc, dict) and doc.get("identity") is not None:
            out[int(doc["identity"])] = doc
    return out


def _handler(ctx, mod, patch_dir):
    faces = getattr(ctx, "_char_faces", {})
    for name in os.listdir(patch_dir):
        if name.startswith("face_") and name.endswith(".png") and name[5:-4].isdigit():
            faces[int(name[5:-4])] = os.path.join(patch_dir, name)
    ctx._char_faces = faces
    declared = getattr(ctx, "_char_uniques", {})
    for identity, doc in load_declared(mod).items():
        declared[identity] = doc          # registry uniques: identity -> physical / donor colour
    ctx._char_uniques = declared


register_patch_handler(FOLDER, _handler, order=45)
