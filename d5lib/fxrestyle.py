"""Restyling a skill: its custom choreography and effect models moved to another palette -- fire to lightning --
keeping every shape and every timing, plus optional accents (lightning strikes at the hits).

Where a skill's colours are:
  * effect models: textures (RGB pictures; greyscale LA88 ones take the colour of the commands below), the mesh
    colours (mesh entry rgba bytes) and the vertex colours (0.5 = 1.0) -> a recoloured copy of a warm model:
    skills.json "effects": {"<new id>": {"from": <model>, "recolor": "lightning"}}, built at install and in the
    preview (recolor_obf);
  * script commands: effect colour 3c80 / 3c88 (percent), particle colours 4410 / 4418 (percent), backdrop
    2830 / 2832 / 2834 (128 = full), unit tint 6480 (percent) -> rewritten in the custom events (recolor_text).
Greys and whites stay as they are (a white flash stays white); only warm hues move.

Models with greyscale LA88 pictures carry no colour the kit can move, yet the game draws some of them orange, with a
colour command or without (seen 2026-10-12 in Girl Laharl's skills: 107 and the smoke 119 orange, 106 white; the
reason wasn't found -- not the slot colour, the vertex colours, the effect table, the picture header or its
brightness).  A copy whose pictures are coloured shows exactly its own colours (tested in game), so the restyle gives
every LA88 model of the skill (lightning ones aside) coloured pictures: "la": true in the effect entry -> every LA88
picture becomes DXT5 (ARGB8888 when its sides aren't multiples of 4), coloured along the palette's gradient by its
opacity (la_to_color); "layer": k bakes the softened layer the script picks most (cmd_3c30 ..., k), and those
commands then pick layer 0.  One copy per model, shared by the mod's skills.

restyle_skill(fs, mod, skill_id, palette, accents=True) does all of it on the skill's editable copy in `mod`.
"""
import re

import numpy as np

# ------------------------------------------------------------------------------------------------ palettes
WARM = (-70.0, 80.0)            # hue range (degrees, red = 0) that counts as fire (magenta glows included)


def _lightning_hue(h):
    """fire hue (degrees, -70..80) -> lightning: magenta -> purple, deep red -> violet, red -> indigo, orange ->
    azure, yellow -> cyan"""
    xs = np.array([-70.0, -40.0, 0.0, 25.0, 50.0, 80.0])
    ys = np.array([272.0, 280.0, 255.0, 222.0, 198.0, 185.0])
    return np.interp(h, xs, ys)


PALETTES = {"lightning": _lightning_hue}
# LA88 pictures made coloured: (edge colour, core colour) along the opacity, 0..255
GRADIENTS = {"lightning": ((20, 70, 255), (165, 210, 255))}
LA_SKIP_CATS = {"lightning"}            # LA88 models that keep their pictures (they already look the part)
PAINTED = {107}                         # LA88 models the game was seen drawing orange even with a colour command


def _hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.max(rgb[..., :3], -1)
    mn = np.min(rgb[..., :3], -1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-9
    i = nz & (mx == r)
    h[i] = ((g[i] - b[i]) / d[i]) % 6
    i = nz & (mx == g) & ~(mx == r)
    h[i] = (b[i] - r[i]) / d[i] + 2
    i = nz & (mx == b) & ~(mx == r) & ~(mx == g)
    h[i] = (r[i] - g[i]) / d[i] + 4
    h = h * 60.0
    s = np.where(mx > 1e-9, d / np.maximum(mx, 1e-9), 0.0)
    return h, s, mx


def _rgb(h, s, v):
    h = (h % 360.0) / 60.0
    c = v * s
    x = c * (1 - np.abs(h % 2 - 1))
    m = v - c
    z = np.zeros_like(h)
    k = np.floor(h).astype(int) % 6
    r = np.choose(k, [c, x, z, z, x, c])
    g = np.choose(k, [x, c, c, x, z, z])
    b = np.choose(k, [z, z, x, c, c, x])
    return np.stack([r + m, g + m, b + m], -1)


def recolor_array(rgb, palette, min_sat=0.12):
    """(..., 3) float colours 0..1 (or any scale: done relative to the brightest channel) -> recoloured"""
    fn = PALETTES[palette] if isinstance(palette, str) else palette
    rgb = np.asarray(rgb, float)
    scale = np.maximum(np.max(rgb, -1, keepdims=True), 1e-9)
    big = scale > 1.0
    unit = np.where(big, rgb / scale, rgb)
    h, s, v = _hsv(unit)
    a = np.where(h > 180, h - 360, h)
    warm = (a >= WARM[0]) & (a <= WARM[1]) & (s >= min_sat)
    nh = np.where(warm, fn(a), h)
    out = _rgb(nh, s, v)
    out = np.where(big, out * scale, out)
    return np.where(warm[..., None], out, rgb)


def warm_share(rgb, weight=None, min_sat=0.25):
    """share (0..1) of the colours (weighted) that are warm and saturated"""
    rgb = np.asarray(rgb, float).reshape(-1, 3)
    if not len(rgb):
        return 0.0
    w = np.ones(len(rgb)) if weight is None else np.asarray(weight, float).reshape(-1)
    scale = np.maximum(rgb.max(1, keepdims=True), 1e-9)
    h, s, v = _hsv(rgb / scale)
    a = np.where(h > 180, h - 360, h)
    warm = (a >= WARM[0]) & (a <= WARM[1]) & (s >= min_sat) & (v > 0.05)
    tot = w.sum()
    return float((w * warm).sum() / tot) if tot > 0 else 0.0


# ------------------------------------------------------------------------------------------------ models
def obf_warmth(o):
    """how much of an effect model is warm (max of its pictures, mesh colours, vertex colours)"""
    from . import obf
    shares = []
    for t in o.textures:
        if t.fmt == obf.FMT_LA:
            continue
        try:
            a = np.asarray(t.to_image().convert("RGBA"), float) / 255.0
        except ValueError:
            continue
        shares.append(warm_share(a[..., :3], a[..., 3]))
    cols = [np.array(m.color[:3], float) / 255.0 for m in o.meshes]
    if cols:
        shares.append(warm_share(np.array(cols)))
    v = o.vertices()
    if len(v):
        shares.append(warm_share(v[:, 9:12], v[:, 12]))
    return max(shares) if shares else 0.0


def la_to_color(o, palette, layer=0):
    """every LA88 picture of an effect model -> ARGB8888 in the palette's gradient colours (in place): colour from
    edge to core along the opacity (x the brightness), opacity kept; of a stack of softened layers, `layer` is kept"""
    import struct
    from . import obf
    edge, core = (np.array(c, float) for c in GRADIENTS[palette])
    for t in o.textures:
        if t.fmt != obf.FMT_LA or not t.decodable:
            continue
        la = np.frombuffer(t.txf[16:16 + t.data_size()], np.uint8).reshape(t.layers, t.height, t.width, 2)
        la = la[min(max(0, int(layer)), t.layers - 1)].astype(float)
        a = la[..., 1] / 255.0
        rgb = (edge + (core - edge) * (a[..., None] ** 0.7)) * (la[..., 0:1] / 255.0)
        rgba = np.dstack([rgb, la[..., 1]]).round().clip(0, 255).astype(np.uint8)
        if t.width % 4 == 0 and t.height % 4 == 0:      # DXT5: a quarter of ARGB8888's size (the game's memory)
            fmt, data, endian = obf.FMT_DXT5, obf.encode_bc(rgba, obf.FMT_DXT5), ">"
        else:
            fmt, data, endian = obf.FMT_ARGB, rgba[:, :, (3, 0, 1, 2)].tobytes(), "<"
        t.txf = bytes([fmt]) + t.txf[1:4] + struct.pack(endian + "HHII", t.width, t.height, t.unk, len(data)) + data
        t.fmt, t.size_field, t.layers, t.endian = fmt, len(data), 1, endian
        t.attr = bytes([1]) + t.attr[1:]
    return o


def recolor_obf(o, palette, la=False, layer=0):
    """recolour an effect model in place: RGB pictures, mesh colours, vertex colours; la: LA88 pictures become
    coloured ones first (la_to_color, keeping softened layer `layer`)"""
    from PIL import Image
    from . import obf
    if la:
        la_to_color(o, palette, layer)
    for t in o.textures:
        if t.fmt == obf.FMT_LA:
            continue
        try:
            img = t.to_image().convert("RGBA")
        except ValueError:
            continue
        a = np.asarray(img, float) / 255.0
        a[..., :3] = recolor_array(a[..., :3], palette)
        new = Image.fromarray(np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8), "RGBA")
        keep = t.fmt in (obf.FMT_ARGB, obf.FMT_DXT1, obf.FMT_DXT3, obf.FMT_DXT5)
        t.replace_image(new, keep_format=keep)
    for m in o.meshes:
        c = np.array(m.raw_head[8:11], float)
        n = np.clip(np.round(recolor_array(c, palette)), 0, 255).astype(int)
        m.raw_head[8:11] = bytes(int(x) for x in n)
        m.color = tuple(m.raw_head[8:12])
    v = np.array(o.vertices(), copy=True)
    if len(v):
        v[:, 9:12] = recolor_array(v[:, 9:12], palette)
        o.set_vertices(v)
    return o


# ------------------------------------------------------------------------------------------------ scripts
# (command, index of the first r, scale, number of colours)
COLOUR_CMDS = {"cmd_3c80": (2, 100, 1), "cmd_3c88": (2, 100, 1), "cmd_4410": (1, 100, 1), "cmd_4418": (1, 100, 1),
               "cmd_2830": (1, 128, 4), "cmd_2832": (1, 128, 2), "cmd_2834": (1, 128, 1), "cmd_6480": (1, 100, 1),
               # the screen fade's colour (0x2800, 128 = full): Meteor Impact flashes the whole screen orange with it
               "screen_color": (0, 128, 1), "cmd_2800": (0, 128, 1)}
LINE_RE = re.compile(r"^(\s*)(cmd_[0-9a-f]{4}|screen_color)(\s+)(.*)$")


def is_instruction(line):
    """a line of an event's text that is an instruction (not the header, a label, a comment or blank)"""
    s = line.strip()
    return bool(s) and not s.startswith(("event ", ";", "#")) and not (s.endswith(":") and " " not in s)


def recolor_text(text, palette, keep=()):
    """event text with every literal colour of COLOUR_CMDS recoloured, except the instructions (indices) in `keep`
    -> (text, number of colours changed)"""
    out, n, pc = [], 0, -1
    for line in text.splitlines():
        if is_instruction(line):
            pc += 1
        m = LINE_RE.match(line)
        spec = COLOUR_CMDS.get(m.group(2)) if m and pc not in keep else None
        if spec:
            comment = ""
            body = m.group(4)
            if ";" in body:
                body, comment = body.split(";", 1)
                comment = ";" + comment
            args = [a.strip() for a in body.split(",")]
            first, scale, count = spec
            for k in range(count):
                idx = list(first) if isinstance(first, tuple) else [first + 3 * k + j for j in range(3)]
                if max(idx) >= len(args):
                    continue
                vals = [args[i] for i in idx]
                if not all(re.fullmatch(r"-?\d+", x) for x in vals):
                    continue
                rgb = np.array([int(x) for x in vals], float) / scale
                new = recolor_array(rgb, palette) * scale
                nv = [str(int(round(x))) for x in new]
                if nv != vals:
                    for i, v in zip(idx, nv):
                        args[i] = v
                    n += 1
            line = f"{m.group(1)}{m.group(2)}{m.group(3)}{', '.join(args)}" + (f" {comment}" if comment else "")
        out.append(line)
    return "\n".join(out) + "\n", n


EFFECT_LOAD_RE = re.compile(r"^\s*cmd_3c00\s+([^,]+),\s*(\d+)")


def effects_of(events):
    """effect model ids loaded (cmd_3c00) by these event texts"""
    ids = set()
    for text in events.values():
        for line in text.splitlines():
            m = EFFECT_LOAD_RE.match(line)
            if m:
                ids.add(int(m.group(2)))
    return ids


def slots_of(events):
    used = set()
    for text in events.values():
        for line in text.splitlines():
            m = re.match(r"^\s*cmd_3c[0-9a-f]{2}\s+(\d+)\b", line)
            if m:
                used.add(int(m.group(1)))
    return used


# ------------------------------------------------------------------------------------------------ a whole skill
KEEP_CATS = {"object", "backdrop"}          # rocks, boxes, planets, skies: they keep their own colours
KEEP_MAX_SAT = 0.6                          # ... unless the script tints them strongly (a meteor glowing orange)


def _saturation(rgb):
    try:
        r, g, b = (float(x) for x in rgb)
    except (TypeError, ValueError):
        return 0.0
    mx, mn = max(r, g, b), min(r, g, b)
    return (mx - mn) / mx if mx > 0 else 0.0


def _effect_cats():
    import json
    import os
    try:
        with open(os.path.join(os.path.dirname(__file__), "data", "effect_names.json"), encoding="utf-8") as f:
            return {int(k): v.get("cat") for k, v in json.load(f)["effects"].items()}
    except (OSError, ValueError, KeyError):
        return {}


def _object_tints(fs, mod, skill_id, block, cats):
    """({event id: {instruction index}} of colour commands on slots holding an object / backdrop model at that time,
    models with a colour command on them, {model: Counter(layer)} of cmd_3c30, [(event, instruction, model)] of the
    cmd_3c30 in the skill's own events) -- from a simulation"""
    import collections
    from . import choreo, skills
    sc = skills.with_mods(fs, [mod])
    tl = choreo.simulate(sc.ev, sc.root_of(skill_id), choreo.Context())
    loaded, keep, tinted = {}, {}, set()
    layered, layer_ops = collections.defaultdict(collections.Counter), []
    own = {int(k): int(v["from"]) for k, v in skills.load(mod)["effects"].items() if v.get("from") is not None}
    for op in tl.ops:
        if op.cid == 0x3c00 and len(op.args) > 1:
            loaded[op.args[0]] = op.args[1]
        elif op.cid in (0x3c80, 0x3c88) and op.args:
            model = loaded.get(op.args[0])
            tinted.add(model)
            if (block <= op.eid < block + 1000 and cats.get(own.get(model, model)) in KEEP_CATS
                    and _saturation(op.args[2:5]) < KEEP_MAX_SAT):
                keep.setdefault(op.eid, set()).add(op.pc)
        elif op.cid == 0x3c30 and op.args:
            model = loaded.get(op.args[0])
            layered[model][int(op.args[2] if len(op.args) > 2 else op.args[1])] += 1
            if block <= op.eid < block + 1000:
                layer_ops.append((op.eid, op.pc, model))
    return keep, tinted, layered, layer_ops


def set_layer_zero(text, pcs):
    """event text with the cmd_3c30 instructions at indices `pcs` picking layer 0"""
    out, pc = [], -1
    for line in text.splitlines():
        if is_instruction(line):
            pc += 1
            m = LINE_RE.match(line)
            if pc in pcs and m and m.group(2) == "cmd_3c30":
                args = [a.strip() for a in m.group(4).split(",")]
                args[-1] = "0"
                line = f"{m.group(1)}{m.group(2)}{m.group(3)}{', '.join(args)}"
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


# ------------------------------------------------------------------------------------------------
# accents per palette: at each hit (cmd_7220) a strike, and where a recoloured burst / flame shows a crackle
ACCENT_MODELS = {"lightning": {"hit": [(612, 2200), (614, 1600), (611, 1400)], "burst": [(611, 1.0)]}}
BURST_CATS = {"fire", "explosion", "impact"}             # effect_names.json categories that get a crackle


def restyle_skill(fs, mod, skill_id, palette="lightning", accents=True, min_gap=12, max_accents=8,
                  warm_limit=0.2, log=print):
    """the skill's editable choreography in `mod` (made if needed) moved to `palette`: warm effect models get
    recoloured copies, script colours are recoloured, and (accents) a lightning strike plays on the target at its
    hits (at most max_accents, at least min_gap frames apart).  -> summary dict"""
    from . import choreo, skills
    d = skills.load(mod)
    root = (d["skills"].get(str(int(skill_id))) or {}).get("choreography")
    if not root or not skills.is_custom_choreo(root) or str(root) not in d["events"]:
        src = root or skills.vanilla_scripts(fs).root_of(skill_id)
        root = skills.make_custom(fs, mod, skill_id, src)
        d = skills.load(mod)
    block = int(root) // 1000 * 1000
    mine = {k: v for k, v in d["events"].items() if block <= int(k) < block + 1000}
    # ---- effect models: recoloured copies of the warm ones
    members = skills.effect_members(fs.read)
    used_ev, used_fx = skills.used_ids(mod)
    new_ids = {}
    cats = _effect_cats()
    keep, tinted, layered, layer_ops = _object_tints(fs, mod, skill_id, block, cats)
    from . import obf
    la_ids = set()
    room = skills.effect_room(fs, mod)
    cands = []
    for eid in sorted(effects_of(mine)):
        if str(eid) in d["effects"] or cats.get(eid) in KEEP_CATS:     # the mod's own / an object, a backdrop
            continue
        o = skills.load_effect(fs.read, eid, members)
        if o is None:
            continue
        # greyscale pictures: coloured copies (the game may paint them orange by itself), with the softened layer the
        # script uses most
        la = (palette in GRADIENTS and bool(o.textures) and all(t.fmt == obf.FMT_LA for t in o.textures)
              and cats.get(eid) not in LA_SKIP_CATS)
        layer = layered[eid].most_common(1)[0][0] if la and layered.get(eid) else 0
        if not la and obf_warmth(o) < warm_limit:
            continue
        cands.append((bool(la), eid, la, layer))
    for _, eid, la, layer in sorted(cands):            # warm pictures first: they matter most
        extra = {"la": True, **({"layer": layer} if layer else {})} if la else {}
        # one copy per model
        nid = next((int(k) for k, v in d["effects"].items() if v.get("from") == eid and v.get("recolor") == palette
                    and bool(v.get("la")) == bool(la)), None)
        if nid is None:
            if room <= 0:
                log(f"  effect {eid} keeps its colours: every new effect id ({skills.MOD_EFFECT_BASE} .. "
                    f"{skills.EFFECT_MAX_ID}) is in use")
                continue
            nid = skills.MOD_EFFECT_BASE
            while nid in used_fx or str(nid) in d["effects"]:
                nid += 1
            d["effects"][str(nid)] = {"from": int(eid), "recolor": palette, **extra}
            used_fx.add(nid)
            room -= 1
        new_ids[eid] = nid
        if la:
            la_ids.add(eid)
    zero = {}
    for ev, pc, model in layer_ops:                     # the coloured copies have one layer
        if model in la_ids:
            zero.setdefault(ev, set()).add(pc)
    n_col = 0
    for k, text in list(mine.items()):
        t = text
        for old, new in new_ids.items():
            t = skills.replace_effect(t, old, new)
        t, n = recolor_text(t, palette, keep.get(int(k), ()))
        if int(k) in zero:
            t = set_layer_zero(t, zero[int(k)])
        n_col += n
        d["events"][k] = t
    skills.save(mod, d)
    # ---- accents at the hits
    n_acc = 0
    if accents and palette in ACCENT_MODELS:
        n_acc = _add_accents(fs, mod, skill_id, block, palette, min_gap, max_accents)
    log(f"skill {skill_id}: {len(new_ids)} effect model(s) recoloured, {n_col} colour(s) in the script, "
        f"{n_acc} accent(s)")
    return {"root": int(root), "models": new_ids, "colours": n_col, "accents": n_acc}


def _burst_models(recoloured):
    """recoloured effect ids (new id -> source) whose source is a burst / flame / explosion"""
    import json
    import os
    try:
        with open(os.path.join(os.path.dirname(__file__), "data", "effect_names.json"), encoding="utf-8") as f:
            names = json.load(f)["effects"]
    except (OSError, ValueError, KeyError):
        names = {}
    return {n for n, src in recoloured.items() if names.get(str(src), {}).get("cat") in BURST_CATS}


def _add_accents(fs, mod, skill_id, block, palette, min_gap, max_accents):
    """insert accents into the custom events: at each cmd_7220 hit a strike on the hit actor, and where a recoloured
    burst shows a crackle at the same place (load + show right before that instruction)"""
    from . import choreo, skills
    d = skills.load(mod)
    sc = skills.with_mods(fs, [mod])
    tl = choreo.simulate(sc.ev, sc.root_of(skill_id), choreo.Context())
    recoloured = {int(k): int(v["from"]) for k, v in d["effects"].items() if v.get("recolor") == palette}
    bursts = _burst_models(recoloured)
    loaded = {}
    cands = []                                          # (frame, op, kind)
    for op in tl.ops:
        if not (block <= op.eid < block + 1000):
            continue
        if op.cid == 0x3c00 and len(op.args) > 1:
            loaded[op.args[0]] = op.args[1]
        elif op.cid == 0x7220:
            cands.append((op.frame, op, "hit"))
        elif op.cid in (0x3c10, 0x3c18) and loaded.get(op.args[0]) in bursts and len(op.args) > 5:
            cands.append((op.frame, op, "burst"))
    chosen, last = [], -10 ** 9
    for frame, op, kind in sorted(cands, key=lambda c: (c[0], c[2] != "hit")):
        if kind == "hit" or frame - last >= min_gap:
            chosen.append((op, kind))
            last = frame
    hits = [c for c in chosen if c[1] == "hit"]
    chosen = hits + [c for c in chosen if c[1] != "hit"][:max(0, max_accents - len(hits))]
    if not chosen:
        return 0
    events = {k: v for k, v in d["events"].items() if block <= int(k) < block + 1000}
    free = [s for s in range(250, 120, -1) if s not in slots_of(events)]
    spec = ACCENT_MODELS[palette]
    inserts = {}                                        # eid -> {pc: [lines]}
    k = 0
    for op, kind in chosen:
        if op.pc in inserts.get(op.eid, {}):           # an event that runs again: once is enough
            continue
        lines = []
        if kind == "hit":
            actor, off, scale = (op.args[0] if op.args else 1256), (0, 0, 0), None
        else:                                           # the burst's own place and size
            actor, off, scale = op.args[1], tuple(op.args[2:5]), op.args[5]
        for model, size in spec[kind]:
            slot = free[k % len(free)]
            k += 1
            sz = int(size) if scale is None else int(max(300, min(3000, float(scale) * float(size))))                 if isinstance(scale, (int, float)) else 1000
            lines += [f"    cmd_3c00 {slot}, {model}",
                      f"    cmd_3c10 {slot}, {actor}, {off[0]}, {off[1]}, {off[2]}, {sz}, 1000, 1"]
        inserts.setdefault(op.eid, {}).setdefault(op.pc, []).extend(lines)
    for eid, at in inserts.items():
        text_lines = d["events"][str(eid)].splitlines()
        # instruction index pc -> line number: count instruction lines (not the header, comments, labels, blanks)
        idx, out = -1, []
        for line in text_lines:
            if is_instruction(line):
                idx += 1
                if idx in at:
                    out += at[idx]
            out.append(line)
        d["events"][str(eid)] = "\n".join(out) + "\n"
    skills.save(mod, d)
    return len(chosen)
