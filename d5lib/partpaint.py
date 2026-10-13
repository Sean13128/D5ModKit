"""Part painter model (no GUI): which colour part every pixel of a sprite belongs to.

Layers, from broad to fine:
  assign     colour index -> part, for the whole sprite (every frame agrees); starts from the automatic
             materials (partauto) and is changed by "material -> part" and "colour -> part"
  cleanup    partauto.cleanup rules on top (enclosed patches, inner black lines, eyes, specks) -- optional
  learned    parts carried over from the reference poses to every other frame (partlearn), on top of the rules
  overrides  painted pixels (brush / fill): always win
final() = the parts the sprite is rebuilt from (outfits.apply_rows).
"""
import copy

import numpy as np
from scipy import ndimage

from . import anm, partauto, partlearn

MAX_PART = 15
UNDO = 30
NEAREST = -2          # assign value: shading shared by several parts -> the part right next to each pixel


class PartModel:
    def __init__(self, sprite, state=None, overrides=None, learned=None):
        self.sprite = sprite
        self.pal, self.texs, self.ind, self.op, self.count, self.adj = partauto.stats(sprite)
        self.rgba = {t: anm.get_palette(sprite, 0)[self.ind[t]] for t in self.texs}
        self.mat, self.minfo = partauto.materials(sprite)
        self.names = {0: "Details"}
        self.assign = {}
        self.clean = True
        self.moves = []
        self.absorbs = []
        self.eye_from = []
        self.refs = []
        self.learned_stale = False
        if state:
            self.refs = [tuple(int(v) for v in r) for r in state.get("refs", [])]
            self.learned_stale = bool(state.get("learned_stale", False))
            self.eye_from = list(state.get("eye_from", []))
            self.moves = [tuple(m) for m in state.get("moves", [])]
            self.absorbs = [tuple(m) for m in state.get("absorbs", [])]
            self.names.update(state.get("names", {}))
            self.assign = dict(state.get("assign", {}))
            self.clean = state.get("cleanup", True)
        else:
            self.auto()
        self.over = {t: np.full(self.ind[t].shape, -1, np.int8) for t in self.texs}
        self.learned = {t: np.full(self.ind[t].shape, -1, np.int8) for t in self.texs}
        for k, t in enumerate(self.texs):
            if overrides and k in overrides and overrides[k].shape == self.ind[t].shape:
                self.over[t] = overrides[k].astype(np.int8)
            if learned and k in learned and learned[k].shape == self.ind[t].shape:
                self.learned[t] = learned[k].astype(np.int8)
        self._undo, self._redo = [], []
        self.recompute()

    # ------------------------------------------------------------------ building
    def auto(self):
        """the automatic parts: one part per material (biggest first), outline colours = details"""
        order = [m for m in sorted(self.minfo, key=lambda m: -self.minfo[m]["count"]) if m != 0]
        self.names = {0: "Details"}
        self.assign = {}
        keep = order[:partauto.MAX_PARTS]
        for k, m in enumerate(keep, 1):
            self.names[k] = self.minfo[m]["name"]
            for c in self.minfo[m]["colours"]:
                self.assign[c] = k
        for m in order[partauto.MAX_PARTS:]:
            to = min(keep, key=lambda q: float(((self.minfo[q]["lab"] - self.minfo[m]["lab"]) ** 2).sum()))
            for c in self.minfo[m]["colours"]:
                self.assign[c] = keep.index(to) + 1
        if 0 in self.minfo:
            for c in self.minfo[0]["colours"]:
                self.assign[c] = 0
        eyes = max(self.names) + 1
        self.names[eyes] = "Eyes"
        partauto._dedupe(self.names)

    def eyes_part(self):
        return next((p for p, n in self.names.items() if n.lower().startswith("eye")), None)

    def recompute(self):
        table = np.full(256, 0, np.int32)
        for c, p in self.assign.items():
            table[c] = p
        base = {}
        for t in self.texs:
            r = np.where(self.op[t], table[self.ind[t]], -1)
            near = r == NEAREST
            if near.any():
                firm = r >= 1
                if firm.any():
                    _, (iy, ix) = ndimage.distance_transform_edt(~firm, return_indices=True)
                    r[near] = r[iy[near], ix[near]]
                else:
                    r[near] = 0
            base[t] = r
        if self.clean:
            skin = [p for p, n in self.names.items() if n.lower().startswith("skin")]
            partauto.cleanup(base, eyes_part=self.eyes_part(), skin_parts=skin, moves=self.moves,
                             absorbs=[self._absorb_rule(a) for a in self.absorbs],
                             eye_from=self.eye_from, ind=self.ind)
        self.base = base

    def _absorb_rule(self, a):
        """absorb rules may name colours as "#RRGGBB" (palette indices move when the sprite is rebuilt)"""
        if len(a) <= 3:
            return tuple(a)
        hexes = {f"#{int(r):02X}{int(g):02X}{int(b):02X}": c for c, (r, g, b, _) in enumerate(self.pal)}
        return (a[0], a[1], a[2], [hexes[h.upper()] if isinstance(h, str) else int(h) for h in a[3]
                                   if not isinstance(h, str) or h.upper() in hexes])

    def final(self):
        return {t: np.where(self.over[t] >= 0, self.over[t],
                            np.where(self.learned[t] >= 0, self.learned[t], self.base[t])).astype(np.int32)
                for t in self.texs}

    def state(self):
        return {"names": dict(self.names), "assign": dict(self.assign), "cleanup": self.clean,
                "moves": [list(m) for m in self.moves], "absorbs": [list(m) for m in self.absorbs], "eye_from": list(self.eye_from),
                "refs": [list(r) for r in self.refs], "learned_stale": self.learned_stale}

    def overrides(self):
        return {k: self.over[t].astype(np.int32) for k, t in enumerate(self.texs)}

    def learned_rows(self):
        return {k: self.learned[t].astype(np.int32) for k, t in enumerate(self.texs)}

    # ------------------------------------------------------------------ reference poses
    def has_learned(self):
        return any((r >= 0).any() for r in self.learned.values())

    def is_ref(self, rects):
        rects = [tuple(int(v) for v in r) for r in rects]
        return bool(rects) and all(r in self.refs for r in rects)

    def toggle_ref(self, rects):
        """rects [(tex, x0, y0, x1, y1)] of one pose: add them as a reference, or remove them if they are one
        -> True when added"""
        rects = [tuple(int(v) for v in r) for r in rects]
        if self.is_ref(rects):
            self.refs = [r for r in self.refs if r not in rects]
            return False
        self.refs += [r for r in rects if r not in self.refs]
        return True

    def poses(self):
        """the sprite's frames: [(tex, x0, y0, x1, y1)] -- every separate drawing on the sheets (cells of the
        sprite, smaller cells inside a bigger one left out), sorted by sheet / row / column"""
        if getattr(self, "_poses", None) is None:
            rects = set()
            for blk in self.sprite.blocks:
                for c in blk.cells:
                    t = blk.tex_base + c.tex
                    if c.w * c.h >= 300 and t in self.ind:
                        rects.add((int(t), int(c.x), int(c.y), int(c.x + c.w), int(c.y + c.h)))

            def inside(p, q):
                return p != q and p[0] == q[0] and q[1] <= p[1] and q[2] <= p[2] and p[3] <= q[3] and p[4] <= q[4]
            out = [r for r in rects if not any(inside(r, q) for q in rects)]
            out.sort(key=lambda p: (p[0], p[2] // 40, p[1]))
            self._poses = out
        return self._poses

    def pose_of(self, rect):
        """the frame (pose) a rectangle overlaps most"""
        def area(q):
            if q[0] != rect[0]:
                return 0
            return max(0, min(rect[3], q[3]) - max(rect[1], q[1])) * max(0, min(rect[4], q[4]) - max(rect[2], q[2]))
        best = max(self.poses(), key=area, default=None)
        return best if best is not None and area(best) > 0 else None

    def key_rects(self):
        """the reference poses as whole frames"""
        out = []
        for r in self.refs:
            q = self.pose_of(tuple(int(v) for v in r))
            if q is not None and q not in out:
                out.append(q)
        return out

    def learn(self, log=None, targets=None):
        """carry the reference poses' parts over to the other frames (the learned layer): every pixel takes the part
        of the reference spot whose 5x5 surroundings look most like its own (partlearn.transfer); colours the
        references always give one part keep it.  targets: frames to do (default all) -> pixels changed"""
        keys = self.key_rects()
        if not keys:
            return 0
        fin = self.final()
        K = [(self.ind[t][y0:y1, x0:x1], self.op[t][y0:y1, x0:x1], fin[t][y0:y1, x0:x1])
             for t, x0, y0, x1, y1 in keys]
        firm = partlearn.firm_colours(K, len(self.pal))
        labpal = partlearn._lab_of(self.pal)
        todo = [p for p in (targets or self.poses()) if p not in keys]
        changed = 0
        for n, (t, x0, y0, x1, y1) in enumerate(todo):
            ind, op = self.ind[t][y0:y1, x0:x1], self.op[t][y0:y1, x0:x1]
            lab, _ = partlearn.transfer(K, (ind, op), labpal)
            f = firm[ind]
            out = np.where(op, np.where(f >= 0, f, lab), -1)
            old = fin[t][y0:y1, x0:x1]
            changed += int(((out >= 0) & (out != old)).sum())
            self.learned[t][y0:y1, x0:x1] = out.astype(np.int8)
            if log and (n % 5 == 0 or n == len(todo) - 1):
                log(f"Fixing frame {n + 1} of {len(todo)} from {len(keys)} reference pose(s)…")
        self.learned_stale = False
        return changed

    def clear_learned(self):
        for r in self.learned.values():
            r[:] = -1
        self.learned_stale = False

    # ------------------------------------------------------------------ undo
    def snapshot(self):
        self._undo.append(self._snap())
        self._undo = self._undo[-UNDO:]
        self._redo.clear()

    def _snap(self):
        return (copy.deepcopy(self.names), dict(self.assign), self.clean, {t: o.copy() for t, o in self.over.items()},
                {t: o.copy() for t, o in self.learned.items()}, list(self.refs), self.learned_stale)

    def _restore(self, snap):
        (self.names, self.assign, self.clean, self.over, self.learned, self.refs,
         self.learned_stale) = snap
        self.recompute()

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self._snap())
        self._restore(self._undo.pop())
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self._snap())
        self._restore(self._redo.pop())
        return True

    # ------------------------------------------------------------------ edits
    def colour_at(self, t, x, y):
        return int(self.ind[t][y, x]) if self.op[t][y, x] else None

    def part_at(self, t, x, y):
        v = int(self.final_px(t, x, y))
        return v if v >= 0 else None

    def final_px(self, t, x, y):
        o = int(self.over[t][y, x])
        if o < 0:
            o = int(self.learned[t][y, x])
        return o if o >= 0 else int(self.base[t][y, x])

    def set_colours(self, colours, part):
        """these palette colours -> part, everywhere"""
        for c in colours:
            self.assign[int(c)] = int(part)
        self.recompute()

    def set_material(self, m, part):
        self.set_colours(self.minfo[m]["colours"], part)

    def material_part(self, m):
        """the part most of the material's colours have (NEAREST = shared shading)"""
        ps = [self.assign.get(c, 0) for c in self.minfo[m]["colours"]]
        return max(set(ps), key=ps.count) if ps else 0

    def paint(self, t, mask, part):
        """brush: part on these pixels (-1 = remove painting: back to the automatic part)"""
        m = mask & self.op[t]
        self.over[t][m] = part

    def fill(self, t, x, y, part, tolerance=1):
        """region fill: the connected pixels of the clicked colour's material (tolerance 1) or exact colour (0)"""
        if not self.op[t][y, x]:
            return 0
        c = self.ind[t][y, x]
        if tolerance:
            same = self.op[t] & (self.mat[self.ind[t]] == self.mat[c])
        else:
            same = self.op[t] & (self.ind[t] == c)
        lab, _ = ndimage.label(same, structure=np.ones((3, 3)))
        region = lab == lab[y, x]
        self.over[t][region] = part
        return int(region.sum())

    def clear_overrides(self):
        for o in self.over.values():
            o[:] = -1

    def rename(self, part, name):
        self.names[int(part)] = name

    def add_part(self, name="New part"):
        free = [p for p in range(1, MAX_PART + 1) if p not in self.names]
        if not free:
            return None
        self.names[free[0]] = name
        return free[0]

    def remove_part(self, part, into=0):
        """the part's colours and painted pixels go to `into`"""
        if part == 0:
            return
        for c, p in list(self.assign.items()):
            if p == part:
                self.assign[c] = into
        for o in list(self.over.values()) + list(self.learned.values()):
            o[o == part] = into
        self.names.pop(part, None)
        self.recompute()

    def counts(self):
        f = self.final()
        out = {}
        for r in f.values():
            v, c = np.unique(r[r >= 0], return_counts=True)
            for a, b in zip(v, c):
                out[int(a)] = out.get(int(a), 0) + int(b)
        return out
