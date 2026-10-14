"""Source-clock RPG costume idles with coupled equipment tracks and planted feet.

The input is one kit body resource and one unit from a portable source manifest.
Game identity and non-idle animation metadata are preserved. Missing body frames
reuse existing palette indices; exact custom-color part mapping remains heuristic.
"""

import copy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree

from . import anm

FOOT_CACHE = {}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(b):
    return hashlib.sha256(b).hexdigest()


def foot(im):
    yy, xx = np.nonzero(np.asarray(im.getchannel("A")) >= 64)
    if not len(xx):
        raise ValueError("Transparent body")
    ground = int(yy.max())
    band = xx[yy >= ground - 20]
    return ((int(band.min()) + int(band.max())) // 2, ground)


def canon(im):
    fx, fy = foot(im)
    out = Image.new("RGBA", (640, 640))
    out.alpha_composite(im, (round(320 - fx), round(560 - fy)))
    return np.asarray(out.resize((96, 96), Image.Resampling.BILINEAR), float) / 255


def score(a, b):
    aa = a[..., 3]
    bb = b[..., 3]
    weight = np.minimum(aa, bb)
    iou = weight.sum() / max(1e-9, np.maximum(aa, bb).sum())
    rgb = (np.abs(a[..., :3] - b[..., :3]).sum(axis=2) * weight).sum() / max(
        1e-9, 3 * weight.sum()
    )
    return float(iou - 0.15 * rgb)


def key_at(keys, t):
    return max((k for k in keys if k.time <= t), key=lambda k: k.time, default=keys[0])


def body_node(block, animation):
    """Identify the complete anonymous body, allowing smaller hand-overlay nodes."""
    candidates = []
    for index, _, parent in block.walk(animation.root):
        node = block.nodes[index]
        if node.id != 0:
            continue
        areas = [
            block.cells[k.cell].w * block.cells[k.cell].h
            for k in block.node_keys(node)
            if 0 < k.cell < len(block.cells)
        ]
        if areas:
            candidates.append((float(np.median(areas)), index, parent))
    candidates.sort(reverse=True)
    if not candidates or candidates[0][2] < 0:
        raise ValueError("Idle has no supported enclosing body group")
    if len(candidates) > 1 and candidates[0][0] < 2 * candidates[1][0]:
        raise ValueError("Ambiguous idle body and overlay layers")
    return candidates[0][1], candidates[0][2]


def world_foot(a, aid, t):
    b = a.blocks[0]
    an = next(x for x in b.animations if x.id == aid)
    ni, _ = body_node(b, an)
    items = [it for it in anm.evaluate(a, ("id", aid), t) if it.node == ni]
    _require(len(items) == 1, "Unsupported idle structure or preservation check failed")
    it = items[0]
    c = it.cell
    cachekey = (id(a), it.tex_global, c.x, c.y, c.w, c.h)
    if cachekey not in FOOT_CACHE:
        im = anm.texture_to_image(a, it.tex_global, 0).crop(
            (c.x, c.y, c.x + c.w, c.y + c.h)
        )
        FOOT_CACHE[cachekey] = foot(im)
    fx, fy = FOOT_CACHE[cachekey]
    # Translation-only planted body geometry is enforced for repaired body tracks.
    xy = (
        it.quad[0]
        + (it.quad[1] - it.quad[0]) * (fx / c.w)
        + (it.quad[3] - it.quad[0]) * (fy / c.h)
    )
    return tuple(float(x) for x in xy)


def quantized_missing(a, src, reference):
    c = a.blocks[0].cells[reference.cell]
    indices = anm.texture_indices(a, c.tex)[c.y : c.y + c.h, c.x : c.x + c.w]
    ref = anm.texture_to_image(a, c.tex, 0).crop((c.x, c.y, c.x + c.w, c.y + c.h))
    # Spatial/color nearest neighbors retain duplicate palette colors' part indices.
    rp = np.asarray(ref)
    yy, xx = np.nonzero(rp[..., 3] >= 64)
    rfx, rfy = foot(ref)
    feats = np.column_stack(
        [rp[yy, xx, :].astype(float), 0.35 * (xx - rfx), 0.35 * (yy - rfy)]
    )
    tree = cKDTree(feats)
    sp = np.asarray(src)
    sy, sx = np.nonzero(sp[..., 3] >= 64)
    sfx, sfy = foot(src)
    target = np.column_stack(
        [sp[sy, sx, :].astype(float), 0.35 * (sx - sfx), 0.35 * (sy - sfy)]
    )
    _, chosen = tree.query(target)
    out = np.zeros(sp.shape[:2], np.uint8)
    out[sy, sx] = indices[yy[chosen], xx[chosen]]
    # Keep the original normal palette and every existing preset; no palette is rewritten.
    tex = anm.add_texture(a, src.width, src.height)
    a.textures[a.blocks[0].tex_base + tex].data = out.tobytes()
    b = a.blocks[0]
    cell = copy.deepcopy(c)
    cell.tex = tex
    cell.x = cell.y = 0
    cell.w = src.width
    cell.h = src.height
    b.cells.append(cell)
    return len(b.cells) - 1


def validate_unit(unit):
    for view in ("front", "back"):
        facing = unit["facings"][view]
        duration = facing["duration_ticks60"]
        if type(duration) is not int or not 0 < duration < 65536:
            raise ValueError("Idle duration must fit a native 60 Hz tick field")
        switches = facing["switches"]
        times = [s["ticks60"] for s in switches]
        if (
            not times
            or times[0] != 0
            or any(type(t) is not int or t < 0 or t > duration for t in times)
        ):
            raise ValueError(
                "Idle switches must start at zero and stay within their loop"
            )
        if any(a >= b for a, b in zip(times, times[1:])):
            raise ValueError("Idle switch times must be strictly increasing")
        for switch in switches:
            with Image.open(switch["png"]) as im:
                im.verify()


def load_units(manifest):
    """Load a portable manifest, resolving images only inside its source folder."""
    path = Path(manifest).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    units = data["units"]
    for unit in units.values():
        for facing in unit["facings"].values():
            for switch in facing["switches"]:
                png = Path(switch["png"])
                resolved = (png if png.is_absolute() else path.parent / png).resolve()
                try:
                    resolved.relative_to(path.parent)
                except ValueError as exc:
                    raise ValueError("Idle image escapes its source folder") from exc
                switch["png"] = str(resolved)
        validate_unit(unit)
    return units


@lru_cache(maxsize=8)
def _cached_units(path, size, mtime_ns):
    return load_units(path)


def source_for(uid, roots):
    """Find optional exported source clocks alongside the editor's RPG sheets."""
    for root in roots:
        for path in (
            Path(root) / "rpg-idle-timings.json",
            Path(root) / "rpg-idle-sources/rpg-idle-timings.json",
        ):
            if path.is_file():
                stat = path.stat()
                unit = _cached_units(
                    str(path.resolve()), stat.st_size, stat.st_mtime_ns
                ).get(str(uid))
                if unit is not None:
                    return unit
    return None


def repair_sprite(before, unit):
    """Return (repaired AnmFile, per-facing audit); never mutate the input.

    Source facings supply integer duration_ticks60 and ordered switches with
    ticks60, sprite_name and png. Unsupported geometry/track topology fails
    before a caller writes a mod. Source images must be local PNG files.
    """
    if len(before.blocks) != 1:
        raise ValueError("A costume body must contain exactly one animation block")
    validate_unit(unit)
    FOOT_CACHE.clear()
    after = copy.deepcopy(before)
    b, bb = after.blocks[0], before.blocks[0]
    number = b.id
    expected = {6001, 6007}
    _require(
        expected <= set(x.id for x in b.animations),
        "Unsupported idle structure or preservation check failed",
    )
    allowed_nodes = set()
    loops = []
    for view, aid in [("front", 6001), ("back", 6007)]:
        source = unit["facings"][view]
        duration = source["duration_ticks60"]
        switches = [s for s in source["switches"] if 0 <= s["ticks60"] < duration]
        # Any closing first-frame switch remains exactly where the source places it.
        srcnames = list(dict.fromkeys(s["sprite_name"] for s in switches))
        srcimgs = {
            s["sprite_name"]: Image.open(s["png"]).convert("RGBA") for s in switches
        }
        an = next(x for x in b.animations if x.id == aid)
        walk = list(b.walk(an.root))
        allowed_nodes.update(i for i, _, _ in walk)
        ni, parent = body_node(b, an)
        oldkeys = copy.deepcopy(b.node_keys(b.nodes[ni]))
        oldend = anm.animation_info(b, an)["loop"][1]
        candidates = []
        seen = set()
        for k in oldkeys:
            if k.cell and k.time <= oldend and k.cell not in seen:
                seen.add(k.cell)
                candidates.append(k)
        textures = [
            anm.texture_to_image(before, i, 0) for i in range(len(before.textures))
        ]
        oldimgs = []
        for k in candidates:
            c = bb.cells[k.cell]
            oldimgs.append(textures[c.tex].crop((c.x, c.y, c.x + c.w, c.y + c.h)))
        oldcan = [canon(i) for i in oldimgs]
        choices = []
        for flip in [False, True]:
            images = [
                ImageOps.mirror(srcimgs[n]) if flip else srcimgs[n] for n in srcnames
            ]
            mat = np.array([[score(canon(im), c) for c in oldcan] for im in images])
            ri, ci = linear_sum_assignment(-mat)
            choices.append(
                (float(mat[ri, ci].sum()), flip, images, mat, dict(zip(ri, ci)))
            )
        _, flip, images, mat, assignment = max(choices, key=lambda x: x[0])
        pose = {}
        synth = []
        for j, nm in enumerate(srcnames):
            closest = int(np.argmax(mat[j]))
            ref = copy.deepcopy(candidates[closest])
            reuse = assignment.get(j)
            if reuse is not None and mat[j, reuse] >= 0.88:
                ref = copy.deepcopy(candidates[reuse])
                cell = ref.cell
                xf = copy.deepcopy(b.transforms[ref.xform])
            else:
                cell = quantized_missing(after, images[j], ref)
                synth.append(nm)
                xf = copy.deepcopy(b.transforms[ref.xform])
                fx, fy = foot(images[j])
                # Place the new complete drawing at the existing frame's local boot point.
                oldlocal = foot(oldimgs[closest])
                oldpivot = bb.pivots[xf.pivot]
                px = round(fx - (oldlocal[0] - oldpivot.x))
                py = round(fy - (oldlocal[1] - oldpivot.y))
                xf.pivot = len(b.pivots)
                b.pivots.append(anm.Pivot(px, py))
            # Preserve native body scale/orientation. All source body poses are step frames.
            _require(
                xf.rot == 0 and abs(xf.sx) == abs(xf.sy) == 100,
                (
                    number,
                    aid,
                    "unsupported body geometry",
                    xf,
                ),
            )
            xi = len(b.transforms)
            b.transforms.append(xf)
            pose[nm] = {
                "cell": cell,
                "xform": xi,
                "reference": ref,
                "score": float(mat[j, closest]),
            }
        # Sample all pose/attachment tracks from the same corresponding donor pose time.
        first_keys = {i: copy.deepcopy(b.node_keys(b.nodes[i])) for i, _, _ in walk}
        for i, _, _ in walk:
            if i == an.root:
                continue
            old = first_keys[i]
            if not old:
                continue
            new = []
            for j, s in enumerate(switches):
                ref = pose[s["sprite_name"]]["reference"]
                k = copy.deepcopy(key_at(old, ref.time))
                k.time = s["ticks60"]
                k.flags &= 0xFF00  # source drawings are discrete; remove donor pose interpolation
                if j == 0:
                    k.flags = (k.flags & 0x00FF) | (old[0].flags & 0xFF00)
                if i == ni:
                    k.cell = pose[s["sprite_name"]]["cell"]
                    k.xform = pose[s["sprite_name"]]["xform"]
                new.append(k)
            b.nodes[i].first_key = len(b.keys)
            b.nodes[i].num_keys = len(new)
            b.keys.extend(new)
        # Root control carries only loop commands and source duration; gameplay events are untouched.
        rootold = first_keys[an.root]
        _require(
            all((k.flags & 255) in [1, 2] for k in rootold),
            "Unsupported idle structure or preservation check failed",
        )
        start = copy.deepcopy(rootold[0])
        start.time = 0
        start.flags = (start.flags & 0xFF00) | 1
        end = copy.deepcopy(rootold[-1])
        end.time = duration
        end.flags = (end.flags & 0xFF00) | 2
        b.nodes[an.root].first_key = len(b.keys)
        b.nodes[an.root].num_keys = 2
        b.keys.extend([start, end])
        # Plant the feet while shifting equipment under the same enclosing pose group.
        target = world_foot(before, aid, oldkeys[0].time)
        group = b.nodes[parent]
        groupold = copy.deepcopy(b.node_keys(group))
        new = []
        zero = next(i for i, p in enumerate(b.pivots) if p.x == p.y == 0)
        for s in switches:
            t = s["ticks60"]
            root = world_foot(after, aid, t)
            dx, dy = target[0] - root[0], target[1] - root[1]
            _require(
                abs(dx - round(dx)) < 1e-6 and abs(dy - round(dy)) < 1e-6,
                (
                    number,
                    aid,
                    "fractional placement",
                    dx,
                    dy,
                ),
            )
            k = (
                copy.deepcopy(key_at(groupold, t))
                if groupold
                else anm.Key(t, 0, 0, 0, oldkeys[0].color, 0)
            )
            xf = (
                copy.deepcopy(b.transforms[k.xform])
                if groupold
                else anm.Transform(0, 0, zero, 0, 100, 100, 0)
            )
            _require(
                xf.rot == 0 and xf.sx == xf.sy == 100,
                "Unsupported idle structure or preservation check failed",
            )
            xf.x += round(dx)
            xf.y += round(dy)
            k.time = t
            k.flags &= 0xFF00
            k.xform = len(b.transforms)
            b.transforms.append(xf)
            new.append(k)
        group.first_key = len(b.keys)
        group.num_keys = len(new)
        b.keys.extend(new)
        # No drift between transitions: controls/pictures/groups all share source clock.
        for t in range(duration):
            actual = world_foot(after, aid, t)
            _require(
                np.allclose(actual, target, atol=1e-6, rtol=0),
                (
                    number,
                    aid,
                    t,
                    actual,
                    target,
                ),
            )
        _require(
            [k.time for k in b.node_keys(b.nodes[ni])]
            == [s["ticks60"] for s in switches],
            "Unsupported idle structure or preservation check failed",
        )
        loops.append(
            {
                "view": view,
                "animation": aid,
                "source_loop_ticks": duration,
                "old_loop_ticks": oldend,
                "times": [s["ticks60"] for s in switches],
                "frames": [s["sprite_name"] for s in switches],
                "mirrored": flip,
                "synthesized_frames": synth,
                "match_scores": {n: pose[n]["score"] for n in srcnames},
                "fixed_foot_root": target,
            }
        )
    # Original textures/palettes/keys/transforms are immutable, including combat geometry.
    _require(
        after.textures[: len(before.textures)] == before.textures
        and after.palettes == before.palettes,
        "Unsupported idle structure or preservation check failed",
    )
    _require(
        b.keys[: len(bb.keys)] == bb.keys
        and b.transforms[: len(bb.transforms)] == bb.transforms,
        "Unsupported idle structure or preservation check failed",
    )
    _require(
        b.cells[: len(bb.cells)] == bb.cells
        and b.pivots[: len(bb.pivots)] == bb.pivots,
        "Unsupported idle structure or preservation check failed",
    )
    _require(
        b.animations == bb.animations,
        "Unsupported idle structure or preservation check failed",
    )
    for i, n in enumerate(bb.nodes):
        if i not in allowed_nodes:
            _require(
                b.nodes[i] == n,
                "Unsupported idle structure or preservation check failed",
            )
    if len(b.keys) > 32767 or len(b.nodes) > 32767 or len(b.transforms) > 65535:
        raise ValueError("Repaired animation exceeds native table capacity")
    data = after.to_bytes()
    roundtrip = anm.load(data)
    _require(
        roundtrip.blocks[0].keys == b.keys and roundtrip.blocks[0].nodes == b.nodes,
        "Unsupported idle structure or preservation check failed",
    )
    return after, loops
