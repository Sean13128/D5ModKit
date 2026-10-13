"""Event poses in the outfit's look.

A few skills show their user through an "event pose" actor: Killia's Macrocosm / Avidya Holy Water and Seraphina's
Dazzling Eyes, Heart Ensemble, Malicious Eye and Overload spawn `cmd_6402 / cmd_6405 actor, 7000 / 7002` (an anm of
whole-body drawings made for events: anims 8501-8801) when the caster's sprite is 10 / 40
(scalepatch.script_sprite_patch lets an outfit take that branch).  Vanilla gives alternate forms their own sheet
(Seraphina 500 -> 7013, Killia 20 / 30 -> 7001 / 7018); a DRPG outfit gets one here:

* the vanilla sheet is copied with every animation, transform and effect cell (sparkles, hearts);
* each whole-body drawing is matched by silhouette against the character's DRPG twin (a DRPG unit drawn exactly like
  the vanilla sprite; front / back / idle frames, mirrored too) and replaced by the outfit DRPG unit's frame in the
  same slot, placed the same way (new cells on new indexed textures; new pivots / mesh corners keep each drawing
  where the old one stood).  The game draws every cell with the colour variant's palette, whatever the cell's own
  palette number says, so the sheet gets one palette for the outfit's drawings and the kept effect drawings (whose
  pixels are re-indexed), in every variant;
* smaller drawings of the character (face / hand close-ups laid over a body) are hidden: they belong to the default
  look.

The sheet is numbered outfit sprite + 3 (inside the outfit's family of numbers) and listed in
patches/outfits/event_sheets.json {"slot": {"7002": sprite}}.  At install the exe (section .d5ev) swaps the number a
skill spawns when the caster is in that outfit: cmd_6402 (0x140168390, number = class or sprite) and
cmd_6405 (0x1401686b0, sprite); the caster is actor 6101 there.
"""
import numpy as np

from . import anm, drpg, drpgmap, exepatch, sprites

EVENT_SHEETS = {10: 7000, 40: 7002}            # character class -> the event sheet its skills spawn
SHEETS = (7000, 7001, 7002, 7013, 7018)         # every event sheet a skill spawns (forms included)
FILE = "event_sheets.json"
VIEWS = ("front", "wait_front", "back", "wait_back")
BODY_W, BODY_H, BODY_PX = 60, 100, 2000         # a whole-body drawing: at least this big / this many pixels
PAD = 48                                        # room around a drawing when matching (the twin frame may be larger)
MIN_IOU = 0.5                                   # below: the closest standing frame is used instead
CHAR_COLOURS = 0.4                              # colour overlap with the body drawings from which a small cell is
                                                # the character (a close-up), not an effect
PAGE = 1024


def load(mod):
    return {int(k): {int(e): int(n) for e, n in v.items()}
            for k, v in (mod.load_patch("outfits", FILE) or {}).items()}


def save(mod, data):
    mod.save_patch("outfits", FILE, {str(k): {str(e): int(n) for e, n in v.items()}
                                     for k, v in sorted(data.items()) if v} or None)


# ------------------------------------------------------------------------------------------------- matching
def _hist(px):
    q = (px[:, :3] // 32).astype(np.int32)
    h = np.bincount(q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2], minlength=512).astype(np.float64)
    return h / max(1.0, h.sum())


class _Matcher:
    def __init__(self, twin_regs, outfit_regs):
        self.tw, self.ow = twin_regs, outfit_regs
        self.masks = {}
        names = drpg.load_slots()
        for k, r in twin_regs.items():
            if k[1] != "slot" or k[0] not in VIEWS or k not in outfit_regs:
                continue
            if any(x in names[k[0]][k[2]]["name"] for x in drpgmap.POSE_SKIP):     # tumbling / loose hands
                continue
            for mir in (0, 1):
                im = r["img"][:, ::-1] if mir else r["img"]
                self.masks[(k, mir)] = (im[..., 3] > 0).astype(np.float32)

    def best(self, img):
        """img: RGBA drawing -> (iou, slot key, mirrored, x, y) of the twin frame laid over it (x, y: the frame's
        top-left in the drawing, which may be negative)"""
        from scipy.signal import fftconvolve
        h, w = img.shape[:2]
        R = np.zeros((h + 2 * PAD, w + 2 * PAD), np.float32)
        R[PAD:PAD + h, PAD:PAD + w] = img[..., 3] > 0
        best = None
        for (k, mir), m in self.masks.items():
            if m.shape[0] > R.shape[0] or m.shape[1] > R.shape[1]:
                continue
            cor = fftconvolve(R, m[::-1, ::-1], mode="valid")
            y, x = np.unravel_index(int(cor.argmax()), cor.shape)
            ov = cor[y, x]
            iou = float(ov / (R.sum() + m.sum() - ov + 1e-6))
            if best is None or iou > best[0]:
                best = (iou, k, mir, int(x) - PAD, int(y) - PAD)
        return best

    def outfit_frame(self, key, mir, x, y):
        """the outfit's drawing for twin frame `key` laid at (x, y) -> (RGBA, left, top) in the same coordinates"""
        t, o = self.tw[key], self.ow[key]
        sw = t["size"][0]
        th, tw_ = t["img"].shape[:2]
        oh, ow_ = o["img"].shape[:2]
        tl = sw - t["org"][0] - tw_ if mir else t["org"][0]
        ol = sw - o["org"][0] - ow_ if mir else o["org"][0]
        sx, sy = x - tl, y - t["org"][1]                       # the slot's origin
        img = o["img"][:, ::-1] if mir else o["img"]
        return np.ascontiguousarray(img), sx + ol, sy + o["org"][1]


def _palette(px):
    """RGBA colours (n, 4) -> a 256 x 4 palette: index 0 transparent, up to 255 colours (octree when there are more)"""
    from PIL import Image
    u = np.unique(px.reshape(-1, 4), axis=0)
    u = u[u[:, 3] > 0]
    if len(u) > 255:
        q = Image.fromarray(u[None].astype(np.uint8), "RGBA").quantize(255, method=Image.Quantize.FASTOCTREE)
        u = np.array(q.getpalette("RGBA")[:255 * 4], np.uint8).reshape(-1, 4)
    out = np.zeros((256, 4), np.uint8)
    out[1:1 + len(u)] = u
    return out


# ------------------------------------------------------------------------------------------------- the sheet
def _local_affine(b, node, key, cell):
    """2x3 matrix: cell pixel (x, y) -> the node's parent space for this key (its own transform / mesh corners)"""
    t = b.transforms[key.xform] if 0 <= key.xform < len(b.transforms) else anm.Transform(0, 0, 0, 0, 100, 100, 0)
    if node.mesh:
        v = [b.pivots[t.pivot + j] if 0 <= t.pivot + j < len(b.pivots) else anm.Pivot(0, 0) for j in range(4)]
        m = anm._mat(t.x, t.y, t.sx, t.sy, t.rot)
        p = [m @ np.array([q.x, q.y, 1.0]) for q in v]
        ex = (p[1] - p[0]) / max(1, cell.w)
        ey = (p[3] - p[0]) / max(1, cell.h)
        return np.array([[ex[0], ey[0], p[0][0]], [ex[1], ey[1], p[0][1]]])
    pv = b.pivots[t.pivot] if 0 <= t.pivot < len(b.pivots) else anm.Pivot(0, 0)
    m = anm._mat(t.x, t.y, t.sx, t.sy, t.rot) @ np.array([[1, 0, -pv.x], [0, 1, -pv.y], [0, 0, 1.0]])
    return m[:2]


def _orientation(A):
    """the 90-degree turn / mirror closest to an affine's linear part -> 2x2 int matrix (None: not such a turn)"""
    L = A[:, :2]
    s = np.abs(L).max()
    if s < 0.5:
        return None
    R = np.round(L / s).astype(int)
    if round(abs(np.linalg.det(R))) != 1 or np.abs(R).sum() != 2:
        return None
    return R


def _turn(img, R):
    """img (h, w, ...) shown through R (cell axes -> screen axes) -> (screen image, t): screen = R @ cell + t"""
    h, w = img.shape[:2]
    corners = np.array([[0, 0], [w, 0], [0, h], [w, h]]).T
    sc = R @ corners
    t = -sc.min(1)
    W, H = (sc.max(1) - sc.min(1)).astype(int)
    out = np.zeros((H, W) + img.shape[2:], img.dtype)
    ys, xs = np.mgrid[0:H, 0:W]
    Ri = np.round(np.linalg.inv(R)).astype(int)
    c = Ri @ (np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5]) - t[:, None])     # screen pixel centre -> cell
    cx, cy = np.floor(c).astype(int)
    out.reshape((H * W,) + img.shape[2:])[:] = img[cy.clip(0, h - 1), cx.clip(0, w - 1)]
    return out, t


def build_sheet(fs, sheet_no, twin, uid, new_id, roots=None, log=print):
    """the event sheet `sheet_no` in DRPG unit `uid`'s look (twin: the character's DRPG twin) -> (AnmFile numbered
    new_id, report)"""
    a = anm.parse(fs.read(sprites.sprite_vpath(fs, sheet_no, "EN")))
    b = a.blocks[0]
    texs = [np.asarray(anm.texture_to_image(a, b.tex_base + i, b.pal_base).convert("RGBA"))
            for i in range(len(b.texture_infos))]
    m = _Matcher(drpgmap.regions(twin, roots), drpgmap.regions(uid, roots))
    if not m.masks:
        raise ValueError(f"DRPG units {twin} / {uid} have no common frames")

    def drawing(c):
        return texs[c.tex][c.y:c.y + c.h, c.x:c.x + c.w] if 0 <= c.tex < len(texs) and c.w and c.h else None

    body, small = {}, {}
    for ci, c in enumerate(b.cells):
        img = drawing(c)
        if img is None:
            continue
        n = int((img[..., 3] > 0).sum())
        big = (c.w >= BODY_W and c.h >= BODY_H) or (c.h >= BODY_W and c.w >= BODY_H)
        if big and n >= BODY_PX:
            body[ci] = img
        elif n:
            small[ci] = img
    # how each body drawing is shown: upright if any key shows it so (other keys turn it on purpose: a spin), else
    # the turn / mirror most keys give it (a drawing stored sideways)
    seen = {}
    for node in b.nodes:
        for k in b.node_keys(node):
            if k.cell in body:
                R = _orientation(_local_affine(b, node, k, b.cells[k.cell]))
                if R is not None:
                    seen.setdefault(k.cell, []).append(R)
    uses = {}
    for ci, rs in seen.items():
        if any((R == np.eye(2, dtype=int)).all() for R in rs):
            uses[ci] = np.eye(2, dtype=int)
        else:
            keys = [tuple(R.ravel()) for R in rs]
            uses[ci] = np.array(max(set(keys), key=keys.count)).reshape(2, 2)
    stand = next((k for k in (("wait_front", "slot", 0), ("front", "slot", 0)) if (k, 0) in m.masks), None)
    frames, report = {}, []
    for ci, img in body.items():
        R = uses.get(ci)
        if R is None:                   # unused, or skewed / scaled: left as it is
            continue
        shown, t = _turn(img, R)
        iou, key, mir, x, y = m.best(shown)
        if iou < MIN_IOU and stand is not None:
            tw = m.tw[stand]["img"]
            key, mir, x, y = stand, 0, (shown.shape[1] - tw.shape[1]) // 2, shown.shape[0] - tw.shape[0]
        o, left, top = m.outfit_frame(key, mir, x, y)
        # back into the cell's own orientation: cell = R^-1 (screen - t)
        Ri = np.round(np.linalg.inv(R)).astype(int)
        oc, _ = _turn(o, Ri)
        corners = np.array([[left, top], [left + o.shape[1], top], [left, top + o.shape[0]],
                            [left + o.shape[1], top + o.shape[0]]], float).T
        cc = Ri @ (corners - t[:, None])
        frames[ci] = (np.ascontiguousarray(oc), int(round(cc[0].min())), int(round(cc[1].min())))
        report.append(dict(cell=ci, slot=f"{key[0]}/{key[2]}", mirror=mir, iou=round(iou, 3)))
    # the character's own small drawings (close-ups over a body): hidden
    char_h = _hist(np.concatenate([im[im[..., 3] > 0] for im in body.values()])) if body else None
    hidden = set()
    for ci, img in small.items():
        px = img[img[..., 3] > 0]
        if char_h is not None and len(px) >= 150 and np.minimum(_hist(px), char_h).sum() >= CHAR_COLOURS:
            hidden.add(ci)
    # one palette for everything the sheet still shows: the game draws every cell with the colour variant's palette
    # whatever its own palette number says (cells pointing at appended outfit palettes came out in the sheet's colours,
    # scrambled), so the kept drawings (sparkles, hearts) are re-indexed into a palette shared with the outfit's
    old_pal = anm.get_palette(a, b.pal_base)
    old_idx = [anm.texture_indices(a, b.tex_base + i) for i in range(len(b.texture_infos))]
    kept = [ci for ci, c in enumerate(b.cells) if c.w and c.h and ci not in frames and ci not in hidden
            and 0 <= c.tex < len(old_idx)]
    used = np.unique(np.concatenate([old_idx[b.cells[ci].tex][b.cells[ci].y:b.cells[ci].y + b.cells[ci].h,
                                                              b.cells[ci].x:b.cells[ci].x + b.cells[ci].w].ravel()
                                     for ci in kept] or [np.zeros(1, np.uint8)]))
    colours = [old_pal[used]] + [f[0][f[0][..., 3] > 0] for f in frames.values()]
    pal = _palette(np.concatenate(colours))
    remap = anm.quantize_to_palette(old_pal[None], pal)[0]
    for i, idx in enumerate(old_idx):
        a.textures[b.tex_base + i].data = remap[idx].astype(np.uint8).tobytes()
    for i in range(len(b.palette_infos)):
        anm.set_palette(a, b.pal_base + i, pal)
    # the outfit's drawings on new texture(s)
    order = sorted(frames)
    sizes = [(frames[ci][0].shape[1], frames[ci][0].shape[0]) for ci in order]
    from .ownanim import _pack
    pos, pages = _pack(sizes, page=PAGE, pad=2)
    canvases = [np.zeros((PAGE, PAGE), np.uint8) for _ in range(pages)]
    tex_ids = [anm.add_texture(a, PAGE, PAGE, indexed=True) for _ in range(pages)]
    new_cell = {}
    for ci, (p, x, y) in zip(order, pos):
        idx = anm.quantize_to_palette(frames[ci][0], pal)
        h, w = idx.shape
        canvases[p][y:y + h, x:x + w] = idx
        old = b.cells[ci]
        b.cells.append(anm.Cell(tex_ids[p], 0, old.unk2, old.flags, x, y, w, h, old.unk8))
        new_cell[ci] = len(b.cells) - 1
    for p, cv in zip(tex_ids, canvases):
        a.textures[b.tex_base + p].data = cv.tobytes()
    if not b.cells or b.cells[0].w or b.cells[0].h:
        raise ValueError(f"anm {sheet_no}: cell 0 is not empty")
    # keys: the new cell; a plain node gets its pivot moved by the drawing's offset, a mesh node new corners (one new
    # transform per old transform and cell)
    xf_cache = {}
    for node in b.nodes:
        for k in b.node_keys(node):
            if k.cell in hidden:
                k.cell = 0
                continue
            if k.cell not in new_cell:
                continue
            ci = k.cell
            img, x0, y0 = frames[ci]
            ck = (k.xform, ci, bool(node.mesh))
            if ck not in xf_cache:
                t = b.transforms[k.xform] if 0 <= k.xform < len(b.transforms) else \
                    anm.Transform(0, 0, 0, 0, 100, 100, 0)
                if node.mesh:
                    A = _local_affine(b, node, k, b.cells[ci])
                    h, w = img.shape[:2]
                    inv = np.linalg.inv(anm._mat(t.x, t.y, t.sx, t.sy, t.rot))
                    first = len(b.pivots)
                    for u, v in ((x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)):
                        q = inv @ np.array([*(A @ np.array([u, v, 1.0])), 1.0])
                        b.pivots.append(anm.Pivot(int(round(q[0])), int(round(q[1]))))
                else:
                    pv = b.pivots[t.pivot] if 0 <= t.pivot < len(b.pivots) else anm.Pivot(0, 0)
                    b.pivots.append(anm.Pivot(pv.x - x0, pv.y - y0))
                    first = len(b.pivots) - 1
                b.transforms.append(anm.Transform(t.x, t.y, first, t.unk, t.sx, t.sy, t.rot))
                xf_cache[ck] = len(b.transforms) - 1
            k.cell, k.xform = new_cell[ci], xf_cache[ck]
    b.id = new_id
    if log:
        weak = sum(1 for r in report if r["iou"] < MIN_IOU)
        log(f"  event sheet {sheet_no} -> {new_id}: {len(frames)} drawings in the outfit's look "
            f"({weak} as the standing frame), {len(hidden)} close-up(s) hidden")
    return a, report


def free_number(fs, mod, sprite):
    """a number for the outfit's event sheet: sprite + 3 .. + 9 (the outfit's own family), not used anywhere and
    no char.dat row (cmd_6402 reads its number as a class first)"""
    from .outfits import _all_mods, _char_tables
    used = sprites.used_sprite_numbers(fs)
    for m in _all_mods(mod):
        for f in m.list_files():
            n = f.split("/")[-1]
            if n.startswith("anm") and n[3:8].isdigit():
                used.add(int(n[3:8]))
        used.update(n for v in load(m).values() for n in v.values())
    used.update(r["id"] for r in _char_tables(fs, mod)[1].rows)
    for n in range(sprite + 3, sprite + 10):
        if n not in used:
            return n
    raise RuntimeError(f"no free number next to sprite {sprite}")


def create_for_outfit(fs, mod, slot, uid, character, twin, roots=None, log=print):
    """the event sheet of character `character`'s skills in outfit `slot` (DRPG unit uid) -> its sprite number, or
    None when the character has none"""
    from .outfits import _char_tables
    sheet_no = EVENT_SHEETS.get(int(character))
    if sheet_no is None:
        return None
    rows = {r["id"]: r for r in _char_tables(fs, mod)[1].rows}
    N = int(rows[int(slot)]["sprite_id"])
    data = load(mod)
    n = data.get(int(slot), {}).get(sheet_no) or free_number(fs, mod, N)
    a, _ = build_sheet(fs, sheet_no, twin, uid, n, roots, log)
    mod.write_file(f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs", a.to_bytes())
    data.setdefault(int(slot), {})[sheet_no] = n
    save(mod, data)
    return n


# --------------------------------------------------------------------------------------------- game code (.d5ev)
SECTION = b".d5ev"
LOOKUP = 0x1402EAC10            # actor by script id (ecx = id, rdx = [context + 8])
CASTER = 6101                   # the skill's user as the lookup knows it (the $62199 getter asks for it; the
                                # scripts' 1256 is translated before the lookup, which returns nothing for it)
SITES = [
    # cmd_6402: movsx edx, si / mov rcx, rbx   (-> setup(actor, class or sprite, -1, 0, 0) at 0x14016840b)
    (0x1401683FD, "0fbfd6488bcb", 0x140168403),
    # cmd_6405: movsx edx, si / mov rcx, rbx   (-> sprite load at 0x140168743)
    (0x140168729, "0fbfd6488bcb", 0x14016872F),
]


def patch(exe: bytes, table, log=print) -> bytes:
    """table: [(outfit class, event sheet, its outfit version)]"""
    rows = sorted({(int(c), int(e), int(n)) for c, e, n in table})
    if not rows:
        return exe
    lo, hi = min(e for _, e, _ in rows), max(e for _, e, _ in rows)
    # ev_swap: edx = the number a skill spawns, rdi = the script context -> edx (all other registers kept)
    shared = "\n".join([
        "ev_swap:", f"cmp edx, {lo}", "jl ev_ret", f"cmp edx, {hi}", "jg ev_ret",
        "push rax", "push rcx", "push r8", "push r9", "push r10", "push r11",
        "sub rsp, 0x28", "mov dword ptr [rsp + 0x20], edx",
        "mov rdx, qword ptr [rdi + 8]", f"mov ecx, {CASTER}", f"call {LOOKUP:#x}",
        "mov edx, dword ptr [rsp + 0x20]",
        "test rax, rax", "je ev_done", "mov rax, qword ptr [rax + 0x240]", "test rax, rax", "je ev_done",
        "mov ecx, dword ptr [rax + 0x2e04]",
        "lea r8, [rip + ev_table]", f"mov r9d, {len(rows)}",
        "ev_loop:", "test r9d, r9d", "je ev_done",
        "cmp ecx, dword ptr [r8]", "jne ev_next", "cmp edx, dword ptr [r8 + 4]", "jne ev_next",
        "mov edx, dword ptr [r8 + 8]", "jmp ev_done",
        "ev_next:", "add r8, 12", "dec r9d", "jmp ev_loop",
        "ev_done:", "add rsp, 0x28", "pop r11", "pop r10", "pop r9", "pop r8", "pop rcx", "pop rax",
        "ev_ret:", "ret",
        ".align 4", "ev_table:"] + [f".long {c}, {e}, {n}" for c, e, n in rows])
    hooks = [(va, bytes.fromhex(orig), "\n".join(["movsx edx, si", "call {shared}", "mov rcx, rbx", f"jmp {back:#x}"]),
              0xE9) for va, orig, back in SITES]
    log(f"  event poses: {len(rows)} outfit version(s) of the skills' event poses")
    return exepatch.add_hook_section(exe, SECTION, hooks, shared)
