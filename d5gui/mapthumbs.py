"""Pictures of the battle maps for choosing one: the map's own 3D terrain with its textures, seen from the battle
camera's corner (yaw -45, pitch 35), drawn with QPainter (textured triangles back to front, shaded by the map's
vertex colours).  Works on a QImage, so it runs in a background thread; pictures are cached in cache/map_thumbs."""
import math
import os

import numpy as np
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF, QTransform

from d5lib import battlemap, paths

CACHE = os.path.join(paths.KIT_DIR, "cache", "map_thumbs")
VERSION = 1                       # (bump when the drawing changes: old pictures are made again)
YAW, PITCH = math.radians(-45.0), math.radians(35.0)


def _project(pos):
    """map units (x, y up, z) -> (screen x, screen y down, depth: bigger = nearer)"""
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    c, s = math.cos(YAW), math.sin(YAW)
    xr = x * c - z * s
    zr = x * s + z * c
    sx = xr
    sy = zr * math.sin(PITCH) - y * math.cos(PITCH)
    depth = zr * math.cos(PITCH) + y * math.sin(PITCH)
    return sx, sy, depth


def _qimage(rgba):
    h, w = rgba.shape[:2]
    img = QImage(np.ascontiguousarray(rgba).data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
    return img.copy()                # (owns its pixels)


def render(bm, size=(320, 220), background=QColor(18, 16, 30)):
    """QImage of a battlemap.BattleMap"""
    tris = []                        # (depth, screen pts (3, 2), uv px (3, 2), tex index, shade rgb, alpha blend)
    for m in bm.meshes:
        pos = m["pos"]
        if not len(pos):
            continue
        sx, sy, d = _project(pos)
        n = len(pos) // 3
        sx, sy, d = sx[:n * 3].reshape(n, 3), sy[:n * 3].reshape(n, 3), d[:n * 3].reshape(n, 3)
        uv = m["uv"][:n * 3].reshape(n, 3, 2)
        shade = np.clip((m["vcol"][:n * 3, :3] * m["color"][:3]).reshape(n, 3, 3).mean(axis=1), 0, 1)
        dep = d.mean(axis=1)
        for k in range(n):
            tris.append((dep[k], np.stack([sx[k], sy[k]], 1), uv[k], m["tex"], shade[k]))
    img = QImage(size[0], size[1], QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(background)
    if not tris:
        return img
    # framed on the battlefield (the panel grid and 2 panels around it), not on a sea or plain that runs far out
    P = battlemap.PANEL
    g = bm.ground[~bm.no_panel] if (~bm.no_panel).any() else np.zeros(1)
    xs = np.array([-2, bm.width + 2]) * P
    zs = np.array([-2, bm.height + 2]) * P
    box = np.array([[x, y, z] for x in xs for z in zs for y in (float(g.min()), float(g.max()) + 4 * P)])
    bx, by, _ = _project(box)
    allp = np.concatenate([t[1] for t in tris])
    lo = np.maximum(allp.min(axis=0), [bx.min(), by.min()])
    hi = np.minimum(allp.max(axis=0), [bx.max(), by.max()])
    span = np.maximum(hi - lo, 1e-3)
    scale = min((size[0] - 8) / span[0], (size[1] - 8) / span[1])
    off = (np.array(size) - span * scale) / 2 - lo * scale
    tris.sort(key=lambda t: t[0])                         # far first
    textures = {}
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.setPen(Qt.PenStyle.NoPen)
    for dep, pts, uv, ti, shade in tris:
        sp = pts * scale + off
        tex = textures.get(ti)
        if tex is None:
            rgba = bm.rgba(ti)
            tex = textures[ti] = (_qimage(rgba), rgba.shape[1], rgba.shape[0])
        qimg, tw, th = tex
        t = uv * np.array([tw, th])
        # the affine map texture px -> screen for this triangle
        a = np.array([[t[0, 0], t[0, 1], 1.0], [t[1, 0], t[1, 1], 1.0], [t[2, 0], t[2, 1], 1.0]])
        poly = QPolygonF([QPointF(float(sp[i, 0]), float(sp[i, 1])) for i in range(3)])
        try:
            mx = np.linalg.solve(a, sp[:, 0])
            my = np.linalg.solve(a, sp[:, 1])
            br = QBrush(qimg)
            br.setTransform(QTransform(mx[0], my[0], mx[1], my[1], mx[2], my[2]))
        except np.linalg.LinAlgError:                     # (degenerate texture coordinates: flat colour)
            br = QBrush(QColor(int(shade[0] * 255), int(shade[1] * 255), int(shade[2] * 255)))
        p.setBrush(br)
        p.drawPolygon(poly)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        p.setBrush(QColor(int(shade[0] * 255), int(shade[1] * 255), int(shade[2] * 255)))
        p.drawPolygon(poly)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    p.end()
    return img


def thumb_path(map_id):
    return os.path.join(CACHE, f"map{int(map_id):05d}_v{VERSION}.png")


def thumbnail(map_id, data_dir, size=(320, 220)):
    """the cached picture of a map (made when missing) -> QImage, or None when the map can't be drawn"""
    path = thumb_path(map_id)
    if os.path.exists(path):
        img = QImage(path)
        if not img.isNull():
            return img
    bm = battlemap.BattleMap(map_id, data_dir)
    img = render(bm, size)
    os.makedirs(CACHE, exist_ok=True)
    img.save(path)
    return img
