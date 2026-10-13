"""partcli -- edit an outfit's colour parts pose by pose from the command line (the part painter's data: what is
done here shows in the GUI painter, and the other way round).

    python tools/partcli.py SLOT overview OUT.png [first] [count]   numbered poses in part colours (find bad ones)
    python tools/partcli.py SLOT view OUT.png POSE [POSE ...]       original | parts, 5x, grid every 10 px
    python tools/partcli.py SLOT ingame OUT.png [palette]           many animation frames as the game shows them
    python tools/partcli.py SLOT parts                              part numbers and names
    python tools/partcli.py SLOT do "OP; OP; ..."                   edits (kept as brush painting), then saved:
        rect P x0 y0 x1 y1 PART [filters]   pixels in the box (pose coordinates, x1/y1 included) -> PART
            filters: from=A,B (now in those parts)  col=#RRGGBB,.. / notcol=..  hue=h0,h1 (degrees, may wrap:
                     330,20 = reds)  sat=min[,max] saturation (0-1)  light=l0,l1 (0-1)
                     chroma=c0,c1 / L=l0,l1 (Lab: chroma ~0 grey/white, skin ~15-30; L 0-100)
        flood P x y PART [tol=0]        the connected area of the part under (x, y) -> PART
        pick P x y                      print part / colour under (x, y)
        colours P x0 y0 x1 y1           colours in the box: count, current parts
        region P x y PART [from=A,B]    the region under (x, y) (an area bounded by lines / colour edges) -> PART
        zone fx0 fy0 fx1 fy1 PART [from=..] [col=..] [poses=a-b]   the same box in EVERY pose, in % of the pose's
                                        size (e.g. zone 0 88 100 100 6 col=#..: the bottom 12 %)
        poly P x,y x,y x,y ... PART [from=A,B]   pixels inside the polygon -> PART
        unpaint P x0 y0 x1 y1           brush painting in the box removed (back to automatic)
        key P                           pose P is (no longer) a key pose: painted right, the others learn from it
        transfer A B                    poses A..B take their parts from the key poses (local patch matching)
    python tools/partcli.py SLOT build                              rebuild the outfit sprite from the parts (Save)

POSE numbers come from `overview` (every separate drawing on the sheets, sorted by sheet / row / column)."""
import colorsys
import json
import os
import pickle
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
import numpy as np                                                    # noqa: E402
from PIL import Image, ImageDraw                                     # noqa: E402
from scipy import ndimage                                            # noqa: E402
from d5lib import modsys, outfits, partpaint, partmap, anm, sprites, colorvariants  # noqa: E402
from d5lib.gamefs import GameFS                                      # noqa: E402

LEGEND = np.array(partmap.LEGEND + [(255, 255, 255)] * 16, np.uint8)
HUES = {1: 0.0, 2: 0.33, 3: 0.62, 4: 0.15, 5: 0.83, 6: 0.5, 7: 0.08, 8: 0.72, 9: 0.42, 10: 0.92, 11: 0.25,
        12: 0.56, 13: 0.04, 14: 0.38, 15: 0.68}


class Session:
    def __init__(self, slot):
        inst = modsys.Installer(paths.require_game_dir(), KIT, log=lambda *a: None)
        self.fs = GameFS(paths.require_game_dir(), backup_resolver=inst.backup_resolver)
        self.mod = modsys.ModManager(KIT).get("Girl_Laharl_Outfits")
        self.slot = slot
        self.N, self.sprite = outfits.painting_sprite(self.fs, self.mod, slot)
        state = outfits.load_painter(self.mod, self.N)
        shapes = [anm.texture_indices(self.sprite, t).shape for t, x in enumerate(self.sprite.textures) if x.indexed]
        over = outfits.load_overrides(self.mod, self.N, shapes) if state else None
        learned = outfits.load_overrides(self.mod, self.N, shapes, "learned") if state else None
        self.m = partpaint.PartModel(self.sprite, state, over, learned)
        self.poses = self._poses()

    def _poses(self):
        self.m.refs = self.m.key_rects()
        return self.m.poses()

    # -------------------------------------------------------------- pictures
    def part_rgba(self, t, fin=None):
        f = (fin or self.m.final())[t]
        rgb = self.m.rgba[t][..., :3].astype(np.float32) / 255
        light = rgb.max(-1) * 0.5 + rgb.min(-1) * 0.5
        out = np.zeros(f.shape + (4,), np.uint8)
        for p in np.unique(f[f >= 0]):
            msk = f == p
            if p == 0:
                out[msk] = self.m.rgba[t][msk]
                continue
            h = HUES.get(int(p), 0.0)
            l = 0.18 + 0.7 * light[msk]
            cols = np.array([colorsys.hls_to_rgb(h, v, 0.85) for v in np.round(l, 2)]) * 255
            out[msk, :3] = cols.astype(np.uint8)
            out[msk, 3] = 255
        return out

    def legend(self, width):
        names = sorted(self.m.names.items())
        im = Image.new("RGBA", (width, 16 * ((len(names) + 3) // 4) + 4), (20, 20, 24, 255))
        d = ImageDraw.Draw(im)
        for k, (p, n) in enumerate(names):
            x, y = (k % 4) * (width // 4), (k // 4) * 16 + 2
            c = (128, 128, 128) if p == 0 else tuple(int(v * 255) for v in colorsys.hls_to_rgb(HUES.get(p, 0), .5, .85))
            d.rectangle([x + 3, y + 2, x + 13, y + 12], fill=c)
            d.text((x + 17, y + 1), f"{p} {n}", fill=(255, 255, 255))
        return im

    def overview(self, out, first=0, count=40, scale=2):
        fin = self.m.final()
        cache = {}
        tiles = []
        for i in range(first, min(len(self.poses), first + count)):
            t, x0, y0, x1, y1 = self.poses[i]
            if t not in cache:
                cache[t] = self.part_rgba(t, fin)
            crop = Image.fromarray(cache[t][y0:y1, x0:x1])
            crop = crop.resize((crop.width * scale, crop.height * scale), Image.NEAREST)
            tile = Image.new("RGBA", (max(crop.width, 60), crop.height + 12), (40, 70, 50, 255))
            tile.alpha_composite(crop, (0, 12))
            ImageDraw.Draw(tile).text((2, 0), str(i), fill=(255, 255, 0, 255))
            tiles.append(tile)
        W = 1900
        rows, row, w = [], [], 0
        for tl in tiles:
            if w + tl.width > W and row:
                rows.append(row)
                row, w = [], 0
            row.append(tl)
            w += tl.width + 4
        if row:
            rows.append(row)
        H = sum(max(t.height for t in r) + 4 for r in rows)
        leg = self.legend(W)
        sheet = Image.new("RGBA", (W, H + leg.height), (40, 70, 50, 255))
        y = 0
        for r in rows:
            x = 0
            for tl in r:
                sheet.alpha_composite(tl, (x, y))
                x += tl.width + 4
            y += max(t.height for t in r) + 4
        sheet.alpha_composite(leg, (0, H))
        sheet.save(out)
        print(f"poses {first}..{min(len(self.poses), first + count) - 1} of {len(self.poses)} -> {out}")

    def view(self, out, poses, Z=5):
        """poses: ints, or "P:x0,y0,x1,y1" (a box of the pose, pose coordinates; zoomed so it fills ~500 px)"""
        fin = self.m.final()
        panels = []
        for spec in poses:
            ox = oy = 0
            if isinstance(spec, str) and ":" in spec:
                i, box = spec.split(":")
                i = int(i)
                bx0, by0, bx1, by1 = map(int, box.split(","))
                t, X0, Y0, _, _ = self.poses[i]
                t, x0, y0, x1, y1 = t, X0 + bx0, Y0 + by0, X0 + bx1 + 1, Y0 + by1 + 1
                ox, oy = bx0, by0
                Z = max(4, min(16, 520 // max(x1 - x0, y1 - y0)))
                step = 2 if Z >= 12 else 5
            else:
                i = int(spec)
                t, x0, y0, x1, y1 = self.poses[i]
                step = 10
            a = self.m.rgba[t][y0:y1, x0:x1]
            b = self.part_rgba(t, fin)[y0:y1, x0:x1]
            for k, img in enumerate((a, b)):
                big = Image.fromarray(img).resize(((x1 - x0) * Z, (y1 - y0) * Z), Image.NEAREST)
                pan = Image.new("RGBA", (big.width + 26, big.height + 26), (40, 70, 50, 255))
                pan.alpha_composite(big, (24, 24))
                d = ImageDraw.Draw(pan)
                for gx in range(-(ox % step) % step, x1 - x0 + 1, step):
                    X = 24 + gx * Z
                    v = gx + ox
                    d.line([(X, 24), (X, pan.height - 2)], fill=(255, 255, 255, 140 if v % (step * 5) == 0 else 60))
                    d.text((X - 6, 2 if (v // step) % 2 == 0 else 12), str(v), fill=(255, 255, 0, 255))
                for gy in range(-(oy % step) % step, y1 - y0 + 1, step):
                    Y = 24 + gy * Z
                    v = gy + oy
                    d.line([(24, Y), (pan.width - 2, Y)], fill=(255, 255, 255, 140 if v % (step * 5) == 0 else 60))
                    d.text((0, Y - 5), str(v), fill=(255, 255, 0, 255))
                if k == 0:
                    d.text((26, pan.height - 14), f"pose {i}", fill=(255, 255, 255, 255))
                panels.append(pan)
        W = sum(p.width + 6 for p in panels)
        H = max(p.height for p in panels)
        leg = self.legend(max(W, 600))
        sheet = Image.new("RGBA", (max(W, 600), H + leg.height), (30, 30, 34, 255))
        x = 0
        for p in panels:
            sheet.alpha_composite(p, (x, 0))
            x += p.width + 6
        sheet.alpha_composite(leg, (0, H))
        sheet.save(out)
        print("->", out)

    def ingame(self, out, palette=1):
        base = outfits.base_sprite(self.fs, self.mod, self.slot)
        a = pickle.loads(pickle.dumps(self.sprite))
        colorvariants.repartition_rows(a, base, self.m.final())
        p = sprites.preview_file(self.fs, a)
        anims = {x["id"]: x for x in anm.list_animations(p) if x["layers"]}
        show = [(1, 0), (7, 0), (21, 0), (21, 16), (21, 32), (27, 8), (1021, 8), (1027, 8), (3011, 12),
                (3001, 16), (2011, 16), (4041, 12), (5011, 8), (6001, 0)]
        tiles = []
        for aid, fr in show:
            if aid in anims:
                im, _ = anm.render_items(p, anm.evaluate(p, anims[aid]["index"], fr), palette,
                                         bounds=(-80, -170, 80, 25))
                tiles.append(im.resize((im.width * 2, im.height * 2), Image.NEAREST))
        cols = 7
        W, H = tiles[0].size
        sheet = Image.new("RGBA", (W * cols, H * ((len(tiles) + cols - 1) // cols)), (40, 70, 50, 255))
        for k, tl in enumerate(tiles):
            sheet.alpha_composite(tl, ((k % cols) * W, (k // cols) * H))
        sheet.save(out)
        print("->", out)

    # -------------------------------------------------------------- edits
    def _hexes(self):
        return {f"#{int(r):02X}{int(g):02X}{int(b):02X}": c for c, (r, g, b, _) in enumerate(self.m.pal)}

    def _filter(self, t, sl, opts, fin):
        msk = self.m.op[t][sl].copy()
        if "from" in opts:
            msk &= np.isin(fin[t][sl], [int(v) for v in opts["from"].split(",")])
        if "col" in opts:
            hx = self._hexes()
            cs = [hx[h.upper()] for h in opts["col"].split(",") if h.upper() in hx]
            msk &= np.isin(self.m.ind[t][sl], cs)
        if "hue" in opts or "sat" in opts or "light" in opts:
            hls = self._hls()
            ind = self.m.ind[t][sl]
            if "hue" in opts:
                h0, h1 = (float(v) / 360 for v in opts["hue"].split(","))
                h = hls[ind, 0]
                msk &= ((h >= h0) & (h <= h1)) if h0 <= h1 else ((h >= h0) | (h <= h1))
            if "sat" in opts:
                v = [float(x) for x in opts["sat"].split(",")]
                msk &= hls[ind, 2] >= v[0]
                if len(v) > 1:
                    msk &= hls[ind, 2] <= v[1]
            if "light" in opts:
                l0, l1 = (float(v) for v in opts["light"].split(","))
                msk &= (hls[ind, 1] >= l0) & (hls[ind, 1] <= l1)
        if "chroma" in opts or "L" in opts:
            if not hasattr(self, "_labp"):
                from d5lib.partregions import _lab
                self._labp = _lab(self.m.pal[:, :3])
            lab = self._labp[self.m.ind[t][sl]]
            if "chroma" in opts:
                c0, c1 = (float(v) for v in opts["chroma"].split(","))
                ch = np.hypot(lab[..., 1], lab[..., 2])
                msk &= (ch >= c0) & (ch <= c1)
            if "L" in opts:
                l0, l1 = (float(v) for v in opts["L"].split(","))
                msk &= (lab[..., 0] >= l0) & (lab[..., 0] <= l1)
        if "notcol" in opts:
            hx = self._hexes()
            msk &= ~np.isin(self.m.ind[t][sl], [hx[h.upper()] for h in opts["notcol"].split(",") if h.upper() in hx])
        return msk

    def _hls(self):
        if not hasattr(self, "_hls_cache"):
            self._hls_cache = np.array([colorsys.rgb_to_hls(*(c[:3] / 255.0)) for c in self.m.pal.astype(float)])
        return self._hls_cache

    def do(self, script):
        for op in [s.strip() for s in script.split(";") if s.strip()]:
            words = op.split()
            opts = dict(w.split("=", 1) for w in words if "=" in w)
            args = [w for w in words if "=" not in w]
            cmd = args[0]
            fin = self.m.final()
            if cmd == "zone":
                fx0, fy0, fx1, fy1, part = map(float, args[1:6])
                lo, hi = 0, len(self.poses) - 1
                if "poses" in opts:
                    lo, hi = map(int, opts["poses"].split("-"))
                n = 0
                for P in range(lo, hi + 1):
                    t, X0, Y0, X1, Y1 = self.poses[P]
                    w, h = X1 - X0, Y1 - Y0
                    sl = (slice(Y0 + int(h * fy0 / 100), Y0 + int(np.ceil(h * fy1 / 100))),
                          slice(X0 + int(w * fx0 / 100), X0 + int(np.ceil(w * fx1 / 100))))
                    msk = self._filter(t, sl, opts, fin)
                    self.m.over[t][sl][msk] = int(part)
                    n += int(msk.sum())
                print(f"{op}: {n} px")
                continue
            P = int(args[1])
            t, X0, Y0, X1, Y1 = self.poses[P]
            if cmd == "rect":
                x0, y0, x1, y1, part = map(int, args[2:7])
                sl = (slice(Y0 + y0, Y0 + y1 + 1), slice(X0 + x0, X0 + x1 + 1))
                msk = self._filter(t, sl, opts, fin)
                self.m.over[t][sl][msk] = part
                print(f"{op}: {int(msk.sum())} px")
            elif cmd == "poly":
                pts = [tuple(map(int, a.split(","))) for a in args[2:-1]]
                part = int(args[-1])
                im = Image.new("L", (X1 - X0, Y1 - Y0), 0)
                ImageDraw.Draw(im).polygon(pts, fill=1, outline=1)
                inside = np.asarray(im, bool)
                sl = (slice(Y0, Y1), slice(X0, X1))
                msk = self._filter(t, sl, opts, fin) & inside
                self.m.over[t][sl][msk] = part
                print(f"{op}: {int(msk.sum())} px")
            elif cmd == "flood":
                x, y, part = map(int, args[2:5])
                sl = (slice(Y0, Y1), slice(X0, X1))
                cur = fin[t][sl]
                lab, _ = ndimage.label(cur == cur[y, x], structure=np.ones((3, 3)))
                msk = lab == lab[y, x]
                self.m.over[t][sl][msk] = part
                print(f"{op}: {int(msk.sum())} px (was part {int(cur[y, x])})")
            elif cmd == "pick":
                x, y = map(int, args[2:4])
                c = int(self.m.ind[t][Y0 + y, X0 + x])
                r, g, b, _ = self.m.pal[c]
                print(f"pose {P} ({x},{y}): part {int(fin[t][Y0 + y, X0 + x])}, colour #{r:02X}{g:02X}{b:02X}")
            elif cmd == "colours":
                x0, y0, x1, y1 = map(int, args[2:6])
                sl = (slice(Y0 + y0, Y0 + y1 + 1), slice(X0 + x0, X0 + x1 + 1))
                ind, op_, f = self.m.ind[t][sl], self.m.op[t][sl], fin[t][sl]
                rows = {}
                for c, p in zip(ind[op_].tolist(), f[op_].tolist()):
                    rows.setdefault(c, {}).setdefault(p, 0)
                    rows[c][p] += 1
                for c, ps in sorted(rows.items(), key=lambda kv: -sum(kv[1].values())):
                    r, g, b, _ = self.m.pal[c]
                    print(f"  #{r:02X}{g:02X}{b:02X} mat {int(self.m.mat[c]):2d}: " +
                          ", ".join(f"part {p} x{n}" for p, n in sorted(ps.items())))
            elif cmd == "region":
                x, y, part = map(int, args[2:5])
                reg = self.regions(P)
                msk = (reg == reg[y, x]) & self._filter(t, (slice(Y0, Y1), slice(X0, X1)), opts, fin)
                self.m.over[t][Y0:Y1, X0:X1][msk] = part
                print(f"{op}: {int(msk.sum())} px")
            elif cmd == "key":
                rect = (t, X0, Y0, X1, Y1)
                if rect in [tuple(r) for r in self.m.refs]:
                    self.m.refs = [r for r in self.m.refs if tuple(r) != rect]
                    print(f"pose {P}: no longer a key pose")
                else:
                    self.m.refs.append(rect)
                    print(f"pose {P}: key pose")
            elif cmd == "transfer":
                lo, hi = (int(v) for v in args[1:3]) if len(args) > 2 else (P, P)
                self.transfer(range(lo, hi + 1))
            elif cmd == "unpaint":
                x0, y0, x1, y1 = map(int, args[2:6])
                self.m.over[t][Y0 + y0:Y0 + y1 + 1, X0 + x0:X0 + x1 + 1] = -1
            else:
                raise SystemExit(f"unknown op {cmd}")
        self.store()

    def regions(self, P):
        from d5lib import partregions
        t, X0, Y0, X1, Y1 = self.poses[P]
        return partregions.segment(self.m.ind[t][Y0:Y1, X0:X1], self.m.op[t][Y0:Y1, X0:X1], self.m.pal, k=120)

    def key_poses(self):
        return [i for i, p in enumerate(self.poses) if (p[0],) + tuple(p[1:]) in [tuple(r) for r in self.m.refs]]

    def transfer(self, targets, log=print):
        """carry the key poses' parts over to the target poses -> learned layer (same as the painter's button)"""
        if not self.key_poses():
            raise SystemExit("no key poses (do: key P)")
        n = self.m.learn(log=log, targets=[self.poses[i] for i in targets])
        log(f"  {n} px changed")

    def store(self):
        outfits.save_painter(self.mod, self.N, self.m.state(), self.m.overrides(), self.m.learned_rows())

    def build(self):
        a = pickle.loads(pickle.dumps(self.sprite))
        outfits.apply_rows(self.fs, self.mod, self.slot, self.m.final(), log=print, sprite=a)
        self.store()


def main(argv):
    slot, cmd = int(argv[0]), argv[1]
    s = Session(slot)
    if cmd == "overview":
        s.overview(argv[2], int(argv[3]) if len(argv) > 3 else 0, int(argv[4]) if len(argv) > 4 else 40,
                   int(argv[5]) if len(argv) > 5 else 2)
    elif cmd == "view":
        s.view(argv[2], [v if ":" in v else int(v) for v in argv[3:]])
    elif cmd == "ingame":
        s.ingame(argv[2], int(argv[3]) if len(argv) > 3 else 1)
    elif cmd == "parts":
        for p, n in sorted(s.m.names.items()):
            print(p, n)
        print(len(s.poses), "poses")
    elif cmd == "do":
        s.do(argv[2])
    elif cmd == "build":
        s.build()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
