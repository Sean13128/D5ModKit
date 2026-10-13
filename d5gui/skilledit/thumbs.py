"""Small pictures for choosing things by sight: a character's poses (animated: a few frames of the animation, drawn
from the same sprite data as the preview) and sound effects (their waveform).  Everything is cached; pose frames are
made on demand (a few milliseconds each), so pickers fill in while they are open."""
import math

import numpy as np
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QPainterPath

from d5lib import anm

BG = QColor("#15131c")


def _compose(items, bounds, scale):
    """[(anm file, DrawItem)] -> RGBA numpy image of the bounds (x0, y0, x1, y1) in sprite pixels x scale"""
    from PIL import Image
    x0, y0, x1, y1 = bounds
    W = max(1, int(math.ceil((x1 - x0) * scale)))
    H = max(1, int(math.ceil((y1 - y0) * scale)))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    caches = {}
    for f, it in items:
        c = it.cell
        if c.w == 0 or c.h == 0:
            continue
        try:
            src = anm._cell_image(f, it, 0, caches.setdefault(id(f), {}))
        except Exception:
            src = None
        if src is None:
            continue
        col = it.color
        if len(col) >= 4 and tuple(col[:4]) != (128, 128, 128, 255):
            arr = np.asarray(src, np.float32).copy()
            arr[..., :3] *= np.array(col[:3], np.float32) / 128.0
            arr[..., 3] *= col[3] / 255.0
            src = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
        dst = (np.asarray(it.quad, float) - [x0, y0]) * scale
        e1, e2 = dst[1] - dst[0], dst[3] - dst[0]
        if abs(e1[0] * e2[1] - e1[1] * e2[0]) < 1e-6:
            continue
        try:
            Hm = anm._homography(dst, [(0, 0), (c.w, 0), (c.w, c.h), (0, c.h)])
        except np.linalg.LinAlgError:
            continue
        layer = src.transform((W, H), Image.PERSPECTIVE, data=tuple(Hm.reshape(-1)[:8]), resample=Image.BILINEAR)
        canvas.alpha_composite(layer)
    return np.asarray(canvas)


def _bounds(items):
    pts = [np.asarray(it.quad, float) for _, it in items if it.cell.w and it.cell.h]
    if not pts:
        return None
    p = np.concatenate(pts)
    return float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max())


def _pixmap(rgba, size, bg=True):
    """an RGBA array centred on a square size x size pixmap (bottom-aligned like a standing unit)"""
    h, w = rgba.shape[:2]
    img = QImage(np.ascontiguousarray(rgba).data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
    pm = QPixmap(size, size)
    pm.fill(BG if bg else QColor(0, 0, 0, 0))
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    k = min((size - 4) / max(1, w), (size - 4) / max(1, h))
    dw, dh = w * k, h * k
    qp.drawImage(QRectF((size - dw) / 2, size - 2 - dh, dw, dh), img)
    qp.end()
    return pm


class Thumbs:
    """pose pictures of battle sprites (glrender.Assets) and sound waveforms"""

    FRAMES = 8                         # frames per animated pose

    def __init__(self, assets):
        self.assets = assets
        self._poses = {}                # (num, aid, size, n) -> [QPixmap]
        self._waves = {}

    # ---- poses
    def aid_for(self, num, motion):
        """the animation a pose number shows on a sprite (as the preview picks it: front view)"""
        try:
            return self.assets.anim_for(num, int(motion))
        except Exception:
            return None

    def pose_frames(self, num, aid, size=72, n=None):
        """[QPixmap] of an animation (n frames spread over it, the same scale for all), [] if none"""
        n = n or self.FRAMES
        key = (num, aid, size, n)
        hit = self._poses.get(key)
        if hit is not None:
            return hit
        out = []
        aid = self._shown(num, aid)
        try:
            a, ids = self.assets.sprite(num)
            if a is not None and aid in ids:
                inf = self.assets.info(num, aid)
                length = max(1, int(inf.get("length", 1) or 1))
                loop = inf.get("loop")
                end = loop[1] if loop and loop[1] > 0 else length
                times = sorted({int(round(end * k / max(1, n))) for k in range(n)})
                frames = [self.assets.sprite_items(num, aid, t) for t in times]
                bs = [b for b in (_bounds(f) for f in frames) if b is not None]
                if bs:
                    b = (min(x[0] for x in bs), min(x[1] for x in bs), max(x[2] for x in bs), max(x[3] for x in bs))
                    span = max(b[2] - b[0], b[3] - b[1], 1.0)
                    scale = min(2.0, size * 1.6 / span)
                    out = [_pixmap(_compose(f, b, scale), size) for f in frames if f]
        except Exception:
            out = []
        self._poses[key] = out
        return out

    def _shown(self, num, aid, depth=0):
        """the animation that really shows: the shared motions' short stubs (nothing drawn, a control key at their
        end) go on with the class's own animation -- the picture is that one"""
        try:
            if depth > 6 or aid is None:
                return aid
            self.assets.chain(num, aid, 0)                         # fills in where it continues
            end, target = self.assets.anim_info.get(("chain", num, aid), (None, None))
            if target is not None and target != aid and not self.assets.sprite_items(num, aid, 0):
                return self._shown(num, target, depth + 1)
        except Exception:
            pass
        return aid

    def draws(self, num, aid):
        """True when the animation draws anything on this sprite (some shared poses are empty for some classes)"""
        aid = self._shown(num, aid)
        try:
            inf = self.assets.info(num, aid)
            end = max(1, int(inf.get("length", 1) or 1))
            return any(self.assets.sprite_items(num, aid, t) for t in (0, end // 3, 2 * end // 3, end))
        except Exception:
            return False

    def pose_icon(self, num, motion=None, aid=None, size=72):
        """one picture of a pose (its first frame), or None"""
        if aid is None:
            aid = self.aid_for(num, motion)
        if aid is None:
            return None
        fr = self.pose_frames(num, aid, size, 1)
        return fr[0] if fr else None

    def char_icon(self, num, size=72):
        """a character's standing picture for the character picker; sprites that weren't loaded before are let go
        again afterwards (the picker shows hundreds)"""
        key = ("char", num, size)
        hit = self._poses.get(key)
        if hit is not None:
            return hit[0] if hit else None
        A = self.assets
        had = num in A.sprite_files
        pm = None
        try:
            fr = self.pose_frames(num, self.aid_for(num, 0), size, 1)
            pm = fr[0] if fr else None
        finally:
            if not had:
                A.sprite_files.pop(num, None)
                for k in [k for k in A.items if k and k[0] == num]:
                    A.items.pop(k, None)
                for k in [k for k in A.anim_info if isinstance(k, tuple) and (k[0] == num or (len(k) > 1 and
                                                                                           k[1] == num))]:
                    A.anim_info.pop(k, None)
                for k in [k for k in self._poses if k[0] == num and k != key]:
                    self._poses.pop(k, None)
        self._poses[key] = [pm] if pm is not None else []
        return pm

    # ---- sounds
    def wave(self, bank, sid, w=180, h=34, colour="#3ecf8e"):
        """a waveform picture of sound effect sid ((None, seconds) when it has no data)"""
        key = (id(bank), sid, w, h, colour)
        hit = self._waves.get(key)
        if hit is not None:
            return hit
        pm = QPixmap(w, h)
        pm.fill(BG)
        secs = 0.0
        pcm = bank.get(sid) if bank is not None else None
        if pcm is not None:
            a, rate = pcm
            secs = len(a) / float(max(1, rate))
            if len(a):
                cols = np.array_split(np.abs(np.asarray(a, np.float32)), w)
                peaks = np.array([c.max() if len(c) else 0.0 for c in cols])
                peaks = peaks / max(1e-4, peaks.max())
                qp = QPainter(pm)
                qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                qp.setPen(QPen(QColor(colour), 1))
                mid = h / 2.0
                for x, p in enumerate(peaks):
                    qp.drawLine(QPointF(x + 0.5, mid - p * (mid - 2)), QPointF(x + 0.5, mid + p * (mid - 2)))
                qp.end()
        self._waves[key] = (pm, secs)
        return self._waves[key]


def glyph(text, size=22, bg="#2a2639", fg="#ece9f6"):
    """a round icon with an emoji / letter (for things without a picture: camera, sound, hit…)"""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    qp.setPen(Qt.PenStyle.NoPen)
    qp.setBrush(QColor(bg))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    qp.drawPath(path)
    f = qp.font()
    f.setPixelSize(int(size * 0.62))
    qp.setFont(f)
    qp.setPen(QColor(fg))
    qp.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
    qp.end()
    return pm
