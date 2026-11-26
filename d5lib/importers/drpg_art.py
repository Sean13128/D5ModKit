"""The DRPG costume art contract (card K2): every id a declared costume look claims resolves to art the build wrote.

A declared costume look is one outfit row at a leased high class id `C` whose art is its leased high number `N`
(`d5lib/importers/drpg-leases.json`, K0; the builder half is K1).  The natives ask for exactly this set:

| what the game asks for | key |
|---|---|
| body / animation set | `anm N`      (block N) |
| the look's own animation copy | `anm N+1` |
| standing picture (list / status) | `anm N+2` |
| portrait + skill cut-in | `anm 10000+N` (block 10000+N) |
| status-panel / Status-screen face | resident block 9017, animation `10000+N` |
| framed battle face | resident block 9017, animation `N` |
| name banner of the cut-in | resident block 9018, animation `N` |
| small list icon | an assigned texturedatabase cell pair + the icon hook's table entry |
| the row itself | `char.dat C`: `sprite_id = color_id = N` |

`check()` is deliberately literal: a missing file, a file whose block carries another id, a resident animation the
build did not write, an icon cell with no pixels, or an icon table without the colour, each fails with its own
message.  It reads only the finalized build's own outputs (the Kit's `BuildContext.get`), never the game, the
installed kit or a save.

Prior art: `d5lib/outfits.py` (`_finalize_outfits` writes faces/banners/face_map; `_install_icons`/`_new_icons` is
the Kit's assigned-icon path), `d5lib/facepatch.py` (blocks 9017/9018), `d5lib/anm.py`, and the id rules recorded in
DRPGHIGHID2-REPORT.md (`anm_id_for_variant` 0x14021F4A0, `FUN_14021bef0` 0x14021BEF0, `char_portrait_anm`
0x14021BE10).  Static evidence only: this is a build-time contract, not a native proof.
"""
from __future__ import annotations

import struct

from .. import anm, database, txf
from ..gamefs import EXE_FILE

FACE_BLOCK = 9017
BANNER_BLOCK = 9018
RESIDENT = "Anime/ANM_HI_JP.dat/anm_resident.lzs"
ANIME = "Anime/ANM_HI_JP.dat/anm{:05d}.lzs"
TDB = "Database/Database_0.dat/texturedatabase.dat"
TEXTURES = "Start/Start_JP.dat/texture.dat"
ICON_FILES = ("wf_unique02_48px.txf", "wf_unique02_64px.txf")
ICON_SECTION = b".d5fi"          # the Kit's list-icon hook section (d5lib/outfits.py:ICON_SECTION)


def look_ids(lease) -> dict:
    """The contract's key set for one costume lease (K0 manifest record)."""
    n, c = int(lease["art"]), int(lease["class_id"])
    return {"class_id": c, "art": n, "body": n, "own_anim": n + 1, "standing": n + 2,
            "portrait": n + 10000, "face_framed": n, "face_status": 10000 + n, "banner": n}


def _anm_ids(get, n):
    """block ids of anm `n` (its file's own blocks), or None when the file is missing."""
    try:
        data = get(ANIME.format(n))
    except (KeyError, FileNotFoundError, OSError):
        return None
    if data is None:
        return None
    return [b.id for b in anm.load(data).blocks]


def _resident_anims(get):
    """{block id: {animation id}} of the resident ANM pack, or {} when it is not in the build."""
    try:
        data = get(RESIDENT)
    except (KeyError, FileNotFoundError, OSError):
        return {}
    if data is None:
        return {}
    res = anm.load(data)
    return {b.id: {a.id for a in b.animations} for b in res.blocks}


def _icon_problem(get, colour, cells):
    """'' when the declared look's assigned list icon resolves to pixels and a hook entry, else the cause."""
    if not cells:
        return f"icon: no list-icon cell assigned for colour {colour} (the native 10835+colour/10 is meaningless here)"
    r48, r64 = (int(x) for x in cells)
    tdb = database.load_table("texturedatabase.dat", get(TDB))
    rows = {r["id"]: r for r in tdb.rows}
    blanks = []
    for tid in (r48, r64):
        row = rows.get(tid)
        if row is None:
            return f"icon: texturedatabase row {tid} is not in the build"
        x, y, w, h = (int(row[k]) for k in ("x_EN", "y_EN", "w_EN", "h_EN"))
        if w <= 0 or h <= 0:
            return f"icon: texturedatabase row {tid} has an empty rect"
        blank = True
        for name in ICON_FILES:
            try:
                raw = get(f"{TEXTURES}/{name}")
            except (KeyError, FileNotFoundError, OSError):
                continue
            if raw is None:
                continue
            img = txf.to_image(raw).convert("RGBA")
            if x + w <= img.width and y + h <= img.height:
                if img.crop((x, y, x + w, y + h)).getextrema()[3][1] > 0:
                    blank = False
                    break
        if blank:
            blanks.append(tid)
    if blanks:
        return f"icon: cells {blanks} of colour {colour} have no pixels in any list-icon atlas"
    try:
        exe = get(EXE_FILE)
    except (KeyError, FileNotFoundError, OSError):
        exe = None
    if exe is not None:
        if ICON_SECTION not in exe:
            return f"icon: the build has no {ICON_SECTION.decode()} icon section"
        if struct.pack("<II", int(colour), int(r48)) not in exe:
            return f"icon: the icon hook table has no entry for colour {colour} -> row {r48}"
    return ""


def _standing_problem(get, n):
    """'' when the standing picture anm `n` exists and its front/back atlas has pixels, else the cause."""
    try:
        data = get(ANIME.format(n))
    except (KeyError, FileNotFoundError, OSError):
        return f"standing: anm{n:05d}.lzs was not written"
    if data is None:
        return f"standing: anm{n:05d}.lzs was not written"
    a = anm.load(data)
    block = next((b for b in a.blocks if b.id == n), None)
    if block is None:
        return f"standing: anm{n:05d}.lzs carries block(s) {[b.id for b in a.blocks]}, not {n}"
    if not block.texture_infos:
        return f"standing: anm{n:05d} has no texture"
    tex = a.textures[a_tex_index(a, block)]
    if not tex.width or not tex.height:
        return f"standing: anm{n:05d} has an empty texture"
    img = anm.texture_to_image(a, a_tex_index(a, block), 0).convert("RGBA")
    if img.getextrema()[3][1] <= 0:
        return f"standing: anm{n:05d} atlas has no pixels (blank standing picture)"
    return ""


def a_tex_index(anm_file, block):
    """index of the block's first texture in the file's texture list (blocks may share one)."""
    return int(getattr(block, "tex_base", 0))



def check(lease, get, icon_cells=None, row=None):
    """-> (problems, table).  `get(vpath)` is the finalized build's own accessor (modsys.BuildContext.get);
    `icon_cells` = {colour: (48 px row, 64 px row)} as recorded by the builder; `row` = the costume's char.dat
    row (a dict or row object) when the caller has the finalized table."""
    ids = look_ids(lease)
    n = ids["art"]
    problems, table = [], {}
    for key in ("body", "own_anim", "standing", "portrait"):
        want = ids[key]
        blocks = _anm_ids(get, want)
        table[key] = want
        if blocks is None:
            problems.append(f"{key}: anm{want:05d}.lzs was not written")
        elif want not in blocks:
            problems.append(f"{key}: anm{want:05d}.lzs carries block(s) {blocks}, not {want}")
    # the standing picture (N+2) is a 256x512 front/back atlas painted into its texture, not animation
    # geometry: its block's cell is 0x0 in the vanilla resident data, so it is checked by pixels.
    why = _standing_problem(get, ids["standing"])
    if why:
        problems.append(why)
    res = _resident_anims(get)
    table["resident"] = {"9017": sorted(res.get(FACE_BLOCK, set()) &
                                       {ids["face_framed"], ids["face_status"]}),
                         "9018": sorted(res.get(BANNER_BLOCK, set()) & {ids["banner"]})}
    for key, block in (("face_framed", FACE_BLOCK), ("face_status", FACE_BLOCK), ("banner", BANNER_BLOCK)):
        anims = res.get(block)
        table[key] = ids[key]
        if anims is None:
            problems.append(f"{key}: resident block {block} is not in the build (no face/banner pack written)")
        elif ids[key] not in anims:
            problems.append(f"{key}: resident block {block} has no animation {ids[key]}")
    cells = None if icon_cells is None else icon_cells.get(n)
    table["icon"] = list(cells) if cells else None
    why = _icon_problem(get, n, cells)
    if why:
        problems.append(why)
    if row is not None:
        sprite, colour = int(row["sprite_id"]), int(row["color_id"])
        table["row"] = {"class_id": ids["class_id"], "sprite_id": sprite, "color_id": colour}
        if sprite != n or colour != n:
            problems.append(f"row {ids['class_id']}: sprite_id={sprite} color_id={colour}, expected both {n}")
    return problems, table


def contract(lease, get, icon_cells=None, row=None):
    """-> (ok, problems, table) for one look, the shape the DRPG build receipt records."""
    problems, table = check(lease, get, icon_cells=icon_cells, row=row)
    return (not problems), problems, table


def summary(problems) -> str:
    """Failures by cause, for a receipt note or a batch tally."""
    out = {}
    for p in problems:
        out[p.split(":", 1)[0]] = out.get(p.split(":", 1)[0], 0) + 1
    return ", ".join(f"{k} x{v}" for k, v in sorted(out.items()))
