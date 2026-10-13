"""The battle HUD over the game view of the skill preview: the skill's name at the top, a number above the target
for every hit (cmd_7220: its share of the skill's damage, in percent) and the running total at the bottom right --
drawn with the game's own digit pictures (Start/Texture_opt.dat number02.txf: white and orange italic digits)."""
import numpy as np
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QLinearGradient

from d5lib import choreo, nested, txf, ykcmp

DIGITS = "Start/Start_EN.dat/Texture_opt.dat"
WHITE_ROW = (6, 78, [(4, 69), (88, 135), (154, 221), (231, 294), (304, 372), (379, 446), (456, 518), (533, 595),
                     (602, 671), (682, 743)])
ORANGE_ROW = (90, 168, [(6, 73), (85, 140), (155, 220), (230, 296), (304, 371), (379, 444), (453, 520), (530, 597),
                        (605, 672), (681, 747)])
HIT_FRAMES = 50


class Hud:
    def __init__(self, fs):
        self.white, self.orange, self.crit = [], [], None
        try:
            mem = {n: d for n, d, _ in nested.read_plain(fs.read(DIGITS))}

            def qimg(name):
                d = mem[name]
                if d[:4] == b"YKCM":
                    d = ykcmp.decompress(d)
                a = np.ascontiguousarray(np.asarray(txf.to_image(d).convert("RGBA"), np.uint8))
                return QImage(a.data, a.shape[1], a.shape[0], 4 * a.shape[1], QImage.Format.Format_RGBA8888).copy()
            num = qimg("number02.txf")
            for (y0, y1, cols), out in ((WHITE_ROW, self.white), (ORANGE_ROW, self.orange)):
                for x0, x1 in cols:
                    out.append(num.copy(x0, y0, x1 - x0, y1 - y0))
            self.crit = qimg("battlemessage01.txf").copy(8, 73, 200, 46)
        except Exception:
            pass

    # ---------------------------------------------------------------- pieces
    def _number(self, qp, value, x, y, height, digits, alpha=1.0, align="center"):
        """the digits of value with their bottom-left... centred / right-aligned at x, baseline y"""
        if not digits:
            qp.setOpacity(alpha)
            qp.setPen(QColor("white"))
            qp.setFont(QFont("Georgia", max(6, int(height * 0.8)), QFont.Weight.Bold, True))
            qp.drawText(QRectF(x - 200, y - height, 400, height), Qt.AlignmentFlag.AlignCenter, str(value))
            qp.setOpacity(1.0)
            return
        s = str(int(value))
        k = height / digits[0].height()
        widths = [digits[int(c)].width() * k * 0.82 for c in s]
        total = sum(widths)
        cx = x - total / 2 if align == "center" else x - total
        qp.setOpacity(max(0.0, min(1.0, alpha)))
        for c, wd in zip(s, widths):
            im = digits[int(c)]
            qp.drawImage(QRectF(cx, y - height, im.width() * k, height), im)
            cx += wd
        qp.setOpacity(1.0)

    def _banner(self, qp, rect, title):
        x, y, w, h = rect
        bw, bh = w * 0.36, h * 0.075
        bx, by = x + w * 0.155, y + h * 0.045
        grad = QLinearGradient(bx, by, bx, by + bh)
        grad.setColorAt(0.0, QColor(58, 54, 66, 235))
        grad.setColorAt(1.0, QColor(24, 22, 30, 235))
        qp.setPen(QPen(QColor(150, 140, 160, 220), max(1.0, h * 0.003)))
        qp.setBrush(grad)
        qp.drawRoundedRect(QRectF(bx, by, bw, bh), bh * 0.25, bh * 0.25)
        qp.setPen(QColor(235, 232, 240))
        qp.setFont(QFont("Georgia", max(6, int(bh * 0.42)), QFont.Weight.DemiBold))
        qp.drawText(QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, title)

    # ---------------------------------------------------------------- the HUD of a frame
    def draw(self, qp, rect, stage, view, title, w, h):
        """rect: the game picture inside the widget (x, y, w, h); stage: d5lib.stage.Stage at the frame"""
        if stage is None:
            return
        qp.save()
        qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        qp.setClipRect(QRectF(*rect))
        x, y, rw, rh = rect
        if title:
            self._banner(qp, rect, title)
        t = stage.frame
        total, any_hit = 0.0, False
        for f, actor, pct in stage.hits:
            if f > t:
                continue
            any_hit = True
            total += float(pct or 0)
            age = t - f
            if age >= HIT_FRAMES:
                continue
            p = stage.where(actor if actor not in (None, 0) else choreo.TARGET)
            p = p + np.array([0.0, 130.0, 0.0])
            sp, _ = view.project(p[None], w, h)
            px, py = sp[0]
            rise = min(age, 10) * rh * 0.004
            pop = 1.0 + max(0.0, (6 - age) / 6.0) * 0.6          # pops in, then settles
            fade = 1.0 if age < HIT_FRAMES - 10 else (HIT_FRAMES - age) / 10.0
            self._number(qp, int(round(pct or 0)), px, py - rise, rh * 0.075 * pop, self.white, fade)
        if any_hit:
            # running total, bottom right (the game: "TOTAL DAMAGE" over orange digits)
            qp.setOpacity(0.9)
            qp.setPen(QColor(255, 200, 60))
            qp.setFont(QFont("Georgia", max(6, int(rh * 0.03)), QFont.Weight.Bold, True))
            qp.drawText(QRectF(x + rw * 0.62, y + rh * 0.78, rw * 0.33, rh * 0.05),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "TOTAL  %")
            qp.setOpacity(1.0)
            self._number(qp, int(round(total)), x + rw * 0.95, y + rh * 0.92, rh * 0.085, self.orange, 1.0,
                         align="right")
        qp.restore()
