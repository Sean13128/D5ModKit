"""Area: where the skill hits (magic.dat range / attack_map / height reach + AttackMap.dat shapes; d5lib/skillarea.py)
and its numbers (SP cost, the main effect's strength, the power of each skill level).

A grid of panels around the caster (forward = up, as the skill faces): click panels to change the area, or switch
to "place enemies" and click hit panels to put enemies on them (the preview then plays the skill on all of them,
in the game's target order).  Changes show in the preview at once; Save (or Save area) writes them into the skill's
mod -- the active one, made on the spot when there is none."""
import copy

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QPolygonF
from PyQt6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
                             QFormLayout, QSpinBox, QRadioButton, QButtonGroup, QComboBox, QSizePolicy)

from d5lib import skillarea as sa
from d5lib import spellgrowth as sg

COLORS = {sa.HIT: QColor(235, 78, 60), sa.CURSOR: QColor(240, 150, 50), sa.USER_TO: QColor(70, 220, 150)}
REACH = QColor(80, 140, 240)
ENEMY = QColor(52, 72, 170)


BRUSHES = {
    "paint": ("🖌 Paint", "Left-click / drag adds panels, numbered in the order you paint them (the game's target "
                          "order); right-click / drag erases. Shift+drag paints a straight line."),
    "number": ("# Number", "Click panels to give them hit order # (then the next number): reorders the targets"),
    "cursor": ("◆ Cursor", "The cursor's panel (hit too): the panel the player points at"),
    "user_to": ("➜ Caster ends", "Where the caster ends up (skills that move the caster); click again to take it off"),
    "erase": ("✖ Erase", "Click / drag takes panels away"),
}
RENUMBER = {"near": "Nearest first (rings around the cursor)", "front": "Front row first, left to right",
            "back": "Back row first, left to right", "left": "Left column first, front to back"}


class AreaGrid(QWidget):
    """the panels around the caster; emits edited() after a change of the area, enemiesEdited() of the enemies.
    Painting: `brush` (BRUSHES), `number` (the next hit order of the # brush), undo() / redo(), transforms."""
    edited = pyqtSignal()
    enemiesEdited = pyqtSignal()
    brushChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.area = sa.default_area()
        self.cursor = 1
        self.enemies = None                  # None: the first hit panel
        self.mode = "area"
        self.editable = True
        self.brush = "paint"
        self.number = 1                      # the # brush's next hit order (1-based)
        self.show_order = True               # hit order numbers on the panels
        self.diff = set()                    # cells (x, y) that differ from the game's shape (outlined)
        self._drag = None                    # (adding, visited, start, before) while painting
        self._undo, self._redo = [], []
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def heightForWidth(self, w):
        return w

    def hasHeightForWidth(self):
        return True

    # ---- geometry
    def _radius(self):
        r = 4
        for x, y, _ in self.area.panels(self.cursor):
            r = max(r, abs(x) + 1, abs(y) + 1)
        if 0 < self.area.range < sa.MAP_WIDE:
            r = max(r, self.area.range + 1)
        return min(r, 15)

    def _cell(self):
        n = 2 * self._radius() + 1
        side = min(self.width(), self.height()) - 4
        return side / n, (self.width() - side) / 2 + 2, (self.height() - side) / 2 + 2

    def _rect(self, x, y):
        c, ox, oy = self._cell()
        r = self._radius()
        return QRectF(ox + (x + r) * c, oy + (r - y) * c, c, c)

    def _at(self, pos):
        c, ox, oy = self._cell()
        r = self._radius()
        gx, gy = int((pos.x() - ox) // c) - r, r - int((pos.y() - oy) // c)
        if abs(gx) > r or abs(gy) > r:
            return None
        return gx, gy

    def _shift(self):
        return self.cursor if self.area.centred else 0

    # ---- drawing
    def paintEvent(self, e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c, ox, oy = self._cell()
        r = self._radius()
        n = 2 * r + 1
        qp.fillRect(QRectF(ox, oy, c * n, c * n), QColor(28, 26, 38))
        for x, y in self.area.reach():
            col = QColor(REACH)
            col.setAlpha(55)
            qp.fillRect(self._rect(x, y).adjusted(1, 1, -1, -1), col)
        panels = self.area.panels(self.cursor)
        for x, y, k in panels:
            col = QColor(COLORS.get(k, COLORS[sa.HIT]))
            col.setAlpha(170)
            qp.fillRect(self._rect(x, y).adjusted(1, 1, -1, -1), col)
        if self.diff:                                # panels that differ from the game's own shape
            sh = self._shift()
            qp.setPen(QPen(QColor(110, 170, 255), max(1.5, c * 0.07)))
            qp.setBrush(Qt.BrushStyle.NoBrush)
            for x, y in self.diff:
                qp.drawRect(self._rect(x, y + sh).adjusted(2, 2, -2, -2))
        if self.show_order and self.mode == "area" and c >= 14:
            qp.setFont(QFont("Segoe UI", max(6, int(c * 0.26)), QFont.Weight.Bold))
            order = 0
            for x, y, k in panels:
                rc = self._rect(x, y).adjusted(3, 1, -2, -1)
                if k == sa.USER_TO:
                    txt = "➜"
                else:
                    order += 1
                    txt = str(order) + ("◆" if k == sa.CURSOR else "")
                qp.setPen(QColor(0, 0, 0, 150))
                qp.drawText(rc.translated(1, 1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, txt)
                qp.setPen(QColor(255, 255, 255))
                qp.drawText(rc, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, txt)
        qp.setPen(QPen(QColor(60, 56, 78), 1))
        for i in range(n + 1):
            qp.drawLine(QPointF(ox + i * c, oy), QPointF(ox + i * c, oy + n * c))
            qp.drawLine(QPointF(ox, oy + i * c), QPointF(ox + n * c, oy + i * c))
        # the cursor (skills with a reach)
        if self.area.centred:
            rc = self._rect(0, self.cursor).center()
            d = c * 0.22
            qp.setPen(QPen(QColor(255, 240, 150), max(1.0, c * 0.06)))
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.drawPolygon(QPolygonF([QPointF(rc.x() - d, rc.y()), QPointF(rc.x(), rc.y() - d),
                                      QPointF(rc.x() + d, rc.y()), QPointF(rc.x(), rc.y() + d)]))
        # the caster: a star, facing up
        rc = self._rect(0, 0)
        qp.setPen(QColor(255, 255, 255))
        qp.setFont(QFont("Segoe UI Symbol", max(6, int(c * 0.45))))
        qp.drawText(rc, Qt.AlignmentFlag.AlignCenter, "★")
        # enemies, numbered in the game's target order
        hits = [(x, y) for x, y, k in panels if k != sa.USER_TO]
        tg = self.area.target_panels(self.cursor, self.enemies) if self.mode == "enemies" or self.enemies else []
        qp.setFont(QFont("Segoe UI", max(6, int(c * 0.32)), QFont.Weight.Bold))
        for i, (x, y) in enumerate(tg):
            rc = self._rect(x, y).adjusted(c * 0.2, c * 0.2, -c * 0.2, -c * 0.2)
            qp.setPen(QPen(QColor(220, 225, 255), max(1.0, c * 0.04)))
            qp.setBrush(ENEMY)
            qp.drawEllipse(rc)
            qp.setPen(QColor(255, 255, 255))
            qp.drawText(rc, Qt.AlignmentFlag.AlignCenter, str(i + 1))
        # forward arrow
        qp.setPen(QColor(185, 180, 205))
        qp.setFont(QFont("Segoe UI", 8))
        qp.drawText(QRectF(ox, oy - 2, c * n, 14), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    "▲ forward" if c > 18 else "▲")
        if not hits:
            qp.drawText(QRectF(ox, oy, c * n, c * n), Qt.AlignmentFlag.AlignCenter, "no hit panels")
        qp.end()

    # ---- editing
    def _cell_of(self, p):
        """grid panel (relative to the caster) -> shape cell (relative to the cursor when centred)"""
        return p[0], p[1] - self._shift()

    def set_brush(self, b):
        if b in BRUSHES and b != self.brush:
            self.brush = b
            self.brushChanged.emit()

    def mousePressEvent(self, e):
        p = self._at(e.position())
        if p is None or not self.editable:
            return
        self.setFocus()
        if self.mode == "enemies":
            self._toggle_enemy(p)
            return
        cx, cy = self._cell_of(p)
        right = e.button() == Qt.MouseButton.RightButton
        before = list(self.area.cells)
        if not right and self.brush in ("number", "cursor", "user_to"):
            self._remember(before)
            getattr(self, f"_click_{self.brush}")(cx, cy)
            return
        adding = not right and self.brush == "paint"
        self._drag = (adding, {(cx, cy)}, (cx, cy), before)
        self._apply(cx, cy, adding, record=False)

    def mouseMoveEvent(self, e):
        p = self._at(e.position())
        if p is not None:
            cx, cy = self._cell_of(p)
            cells = self.area.cells
            i = next((i for i, (x, y, _) in enumerate(cells) if (x, y) == (cx, cy)), None)
            where = f"{abs(p[0])} {'right' if p[0] > 0 else 'left'}, " if p[0] else ""
            where += f"{abs(p[1])} {'ahead' if p[1] >= 0 else 'behind'}"
            extra = ""
            if i is not None:
                k = cells[i][2]
                n = sum(1 for x, y, kk in cells[:i + 1] if kk != sa.USER_TO)
                extra = f" — {sa.KIND_NAMES[k]}" + (f", hit #{n}" if k != sa.USER_TO else "")
            self.setToolTip(f"Panel {where} of the caster{extra}")
        if self._drag is None or p is None:
            return
        cx, cy = self._cell_of(p)
        adding, seen, start, before = self._drag
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:      # a straight line from where the drag began
            line = _line(start, (cx, cy))
            cells = [c for c in before]
            have = {(x, y) for x, y, _ in cells}
            if adding:
                cells += [(x, y, sa.HIT) for x, y in line if (x, y) not in have]
            else:
                cells = [c for c in cells if (c[0], c[1]) not in set(line)]
            self._set_cells(cells, record=False)
            return
        if (cx, cy) not in seen:
            seen.add((cx, cy))
            self._apply(cx, cy, adding, record=False)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            before = self._drag[3]
            if before != self.area.cells:
                self._remember(before)
        self._drag = None

    def keyPressEvent(self, e):
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl and e.key() == Qt.Key.Key_Z:
            self.undo()
        elif ctrl and e.key() == Qt.Key.Key_Y:
            self.redo()
        else:
            super().keyPressEvent(e)

    def _apply(self, cx, cy, adding, record=True):
        cells = list(self.area.cells)
        have = any((x, y) == (cx, cy) for x, y, _ in cells)
        if adding and not have:
            cells.append((cx, cy, sa.HIT))
        elif not adding and have:
            cells = [c for c in cells if (c[0], c[1]) != (cx, cy)]
        else:
            return
        self._set_cells(cells, record=record)

    def _click_number(self, cx, cy):
        """the panel gets hit order self.number (the others keep their order around it); then the next number"""
        cells = list(self.area.cells)
        i = next((i for i, (x, y, _) in enumerate(cells) if (x, y) == (cx, cy)), None)
        cell = cells.pop(i) if i is not None else (cx, cy, sa.HIT)
        if cell[2] == sa.USER_TO:
            cell = (cx, cy, sa.HIT)
        hits = [c for c in cells if c[2] != sa.USER_TO]
        rest = [c for c in cells if c[2] == sa.USER_TO]
        k = max(0, min(len(hits), self.number - 1))
        hits.insert(k, cell)
        self.number = k + 2
        self.brushChanged.emit()
        self._set_cells(hits + rest, record=False)

    def _click_cursor(self, cx, cy):
        cells = [(x, y, sa.HIT if k == sa.CURSOR else k) for x, y, k in self.area.cells]
        i = next((i for i, (x, y, _) in enumerate(cells) if (x, y) == (cx, cy)), None)
        if i is None:
            cells.insert(0, (cx, cy, sa.CURSOR))
        else:
            cells[i] = (cx, cy, sa.CURSOR)
        self._set_cells(cells, record=False)

    def _click_user_to(self, cx, cy):
        cells = list(self.area.cells)
        i = next((i for i, (x, y, _) in enumerate(cells) if (x, y) == (cx, cy)), None)
        if i is None:
            cells.append((cx, cy, sa.USER_TO))
        elif cells[i][2] == sa.USER_TO:
            del cells[i]
        else:
            cells[i] = (cx, cy, sa.USER_TO)
        self._set_cells(cells, record=False)

    # ---- whole-shape tools
    def transform(self, how):
        """'flip' (left / right), 'rot' (a quarter turn), 'up' / 'down' / 'left' / 'right' (one panel), 'clear'"""
        cells = list(self.area.cells)
        if how == "flip":
            cells = [(-x, y, k) for x, y, k in cells]
        elif how == "rot":
            cells = [(y, -x, k) for x, y, k in cells]
        elif how in ("up", "down", "left", "right"):
            dx, dy = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}[how]
            cells = [(x + dx, y + dy, k) for x, y, k in cells]
        elif how == "clear":
            cells = [(0, 0, sa.CURSOR)] if self.area.centred else [(0, 1, sa.HIT)]
        self._set_cells(cells)

    def renumber(self, how):
        """the hit order (the game's target order) from the panels' places (RENUMBER)"""
        hits = [c for c in self.area.cells if c[2] != sa.USER_TO]
        rest = [c for c in self.area.cells if c[2] == sa.USER_TO]
        if how == "near":
            key = lambda c: (c[2] != sa.CURSOR, abs(c[0]) + abs(c[1]), -c[1], c[0])
        elif how == "front":
            key = lambda c: (-c[1], c[0])
        elif how == "back":
            key = lambda c: (c[1], c[0])
        else:
            key = lambda c: (c[0], -c[1])
        self._set_cells(sorted(hits, key=key) + rest)

    def set_cells_from(self, cells):
        """replace the whole shape (undoable)"""
        self._set_cells([tuple(int(v) for v in c) for c in cells])

    # ---- history
    def _remember(self, before):
        self._undo.append(list(before))
        del self._undo[:-200]
        self._redo = []

    def reset_history(self):
        self._undo, self._redo = [], []

    def undo(self):
        if self._undo:
            self._redo.append(list(self.area.cells))
            self._set_cells(self._undo.pop(), record=False)

    def redo(self):
        if self._redo:
            self._undo.append(list(self.area.cells))
            self._set_cells(self._redo.pop(), record=False)

    def _set_cells(self, cells, record=True):
        if len(cells) > sa.MAX_CELLS or not cells:
            return
        if record and list(cells) != list(self.area.cells):
            self._remember(self.area.cells)
        self.area.cells = cells
        self.area.known = True
        if self.enemies is not None:
            hits = {(x, y) for x, y, k in self.area.panels(self.cursor) if k != sa.USER_TO}
            self.enemies = [p for p in self.enemies if p in hits] or None
        self.update()
        self.edited.emit()

    def _toggle_enemy(self, p):
        hits = [(x, y) for x, y, k in self.area.panels(self.cursor) if k != sa.USER_TO]
        if p not in hits:
            return
        cur = list(self.area.target_panels(self.cursor, self.enemies))
        if p in cur:
            if len(cur) == 1:
                return                       # one enemy at least
            cur.remove(p)
        else:
            cur.append(p)
        self.enemies = cur
        self.update()
        self.enemiesEdited.emit()


def _line(a, b):
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x1 > x0 else -1), (1 if y1 > y0 else -1)
    err, out = dx + dy, []
    while True:
        out.append((x0, y0))
        if (x0, y0) == (x1, y1) or len(out) > 400:
            return out
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


class BrushBar(QWidget):
    """the painting tools of an AreaGrid: brushes, the # brush's number, renumber, turn / flip / shift, undo"""

    def __init__(self, grid, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QToolButton, QMenu
        self.grid = grid
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.buttons = {}
        grp = QButtonGroup(self)
        for k, (lab, tip) in BRUSHES.items():
            b = QToolButton()
            b.setText(lab)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(k == grid.brush)
            b.clicked.connect(lambda _, k=k: grid.set_brush(k))
            grp.addButton(b)
            self.buttons[k] = b
            row.addWidget(b)
        self.num = QSpinBox()
        self.num.setRange(1, sa.MAX_CELLS)
        self.num.setPrefix("#")
        self.num.setToolTip("The hit order the # brush gives next")
        self.num.valueChanged.connect(lambda v: setattr(grid, "number", v))
        row.addWidget(self.num)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(4)
        rn = QToolButton()
        rn.setText("Renumber ▾")
        rn.setToolTip("Put the hit order (the game's target order: 1 = the main target) in a tidy order")
        rn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(rn)
        for k, lab in RENUMBER.items():
            m.addAction(lab, lambda k=k: grid.renumber(k))
        rn.setMenu(m)
        row.addWidget(rn)
        for how, lab, tip in (("rot", "↻", "A quarter turn"), ("flip", "⇋", "Mirror left / right"),
                              ("up", "↑", "One panel forward"), ("down", "↓", "One panel back"),
                              ("left", "←", "One panel left"), ("right", "→", "One panel right"),
                              ("clear", "Clear", "Start again from one panel")):
            b = QToolButton()
            b.setText(lab)
            b.setToolTip(tip)
            b.clicked.connect(lambda _, h=how: grid.transform(h))
            row.addWidget(b)
        self.order = QToolButton()
        self.order.setText("1 2 3")
        self.order.setCheckable(True)
        self.order.setChecked(grid.show_order)
        self.order.setToolTip("Show the hit order on the panels")
        self.order.toggled.connect(lambda on: (setattr(grid, "show_order", on), grid.update()))
        row.addWidget(self.order)
        b = QToolButton()
        b.setText("↶")
        b.setToolTip("Undo (Ctrl+Z on the grid)")
        b.clicked.connect(grid.undo)
        row.addWidget(b)
        b = QToolButton()
        b.setText("↷")
        b.setToolTip("Redo (Ctrl+Y)")
        b.clicked.connect(grid.redo)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.count = QLabel()
        self.count.setObjectName("muted")
        lay.addWidget(self.count)
        grid.brushChanged.connect(self.sync)
        grid.edited.connect(self.sync)
        self.sync()

    def sync(self):
        g = self.grid
        for k, b in self.buttons.items():
            b.setChecked(k == g.brush)
        self.num.blockSignals(True)
        self.num.setValue(max(1, g.number))
        self.num.blockSignals(False)
        hits = sum(1 for _, _, k in g.area.cells if k != sa.USER_TO)
        self.count.setText(f"{hits} hit panel{'s' if hits != 1 else ''} · next # {min(g.number, hits + 1)} · "
                           f"{sa.MAX_CELLS - len(g.area.cells)} more possible")


class AreaPanel(QScrollArea):
    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.saved = None                    # the area as saved (Area)
        self.shape_users = {}
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.summary = QLabel("Open a skill to see where it hits.")
        self.summary.setWordWrap(True)
        self.summary.setMinimumWidth(10)
        self.summary.setObjectName("cardTitle")
        lay.addWidget(self.summary)
        help_ = QLabel("The caster (★) faces up. Red panels are hit, orange is the cursor's panel (hit too), green is "
                       "where the caster ends up, blue is where the player can put the cursor. Paint with the "
                       "brushes below: the numbers are the order the targets are hit in (1 = the main target); "
                       "right-click erases, Shift+drag paints a line, Ctrl+Z undoes.")
        help_.setWordWrap(True)
        help_.setMinimumWidth(10)
        help_.setObjectName("muted")
        lay.addWidget(help_)
        mode = QHBoxLayout()
        mode.addWidget(QLabel("Click to:"))
        self.m_area = QRadioButton("change the area")
        self.m_area.setChecked(True)
        self.m_en = QRadioButton("place enemies")
        self.m_en.setToolTip("Click hit panels to put enemies on them: the preview plays the skill on all of them, "
                             "numbered in the game's target order (1 = the main target)")
        grp = QButtonGroup(self)
        grp.addButton(self.m_area)
        grp.addButton(self.m_en)
        self.m_area.toggled.connect(lambda on: setattr(self.grid, "mode", "area" if on else "enemies"))
        mode.addWidget(self.m_area)
        mode.addWidget(self.m_en)
        mode.addStretch(1)
        lay.addLayout(mode)
        self.grid = AreaGrid()
        self.grid.edited.connect(self._edited)
        self.grid.enemiesEdited.connect(self._enemies)
        self.brushes = BrushBar(self.grid)
        lay.addWidget(self.brushes)
        lay.addWidget(self.grid, 1)
        row = QHBoxLayout()
        b = QPushButton("Enemies on every hit panel")
        b.clicked.connect(self._fill_enemies)
        row.addWidget(b)
        b = QPushButton("One enemy")
        b.clicked.connect(self._one_enemy)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        # ---- spells: reach and area from the level
        self.spell_box = QGroupBox("A spell: reach and area grow with its level")
        sv = QVBoxLayout(self.spell_box)
        self.spell_text = QLabel()
        self.spell_text.setWordWrap(True)
        self.spell_text.setMinimumWidth(10)
        self.spell_text.setObjectName("muted")
        sv.addWidget(self.spell_text)
        row = QHBoxLayout()
        row.addWidget(QLabel("Area"))
        self.spell_shape = QComboBox()
        self.spell_shape.setToolTip("The nine area shapes every spell shares. Which of them a unit may pick is kept "
                                    "with that unit's spell (one at first; the level doesn't change it).")
        self.spell_shape.currentIndexChanged.connect(lambda *_: self._spell_preview())
        row.addWidget(self.spell_shape, 1)
        sv.addLayout(row)
        row = QHBoxLayout()
        self.b_edit_shape = QPushButton("✎ Edit this shape (every spell)")
        self.b_edit_shape.setToolTip("Change the shape's panels in the grid above; Save writes it into AttackMap.dat "
                                     "for every spell")
        self.b_edit_shape.clicked.connect(self._edit_shape)
        row.addWidget(self.b_edit_shape)
        self.b_fixed = QPushButton("Give this spell an area of its own")
        self.b_fixed.setToolTip("The spell stops growing with its level: it gets one reach and one area, like a "
                                "weapon skill (set them above, then Save)")
        self.b_fixed.clicked.connect(self._make_fixed)
        row.addWidget(self.b_fixed)
        self.b_grow = QPushButton("Back to growing with the level")
        self.b_grow.setToolTip("Take the spell's own reach and area away: the level rules again (Save)")
        self.b_grow.clicked.connect(self._make_growing)
        row.addWidget(self.b_grow)
        row.addStretch(1)
        sv.addLayout(row)
        gl = QFormLayout()
        gl.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.levels = []
        for row_k in range(2):
            hl = QHBoxLayout()
            hl.setSpacing(3)
            for k in range(row_k * 4, row_k * 4 + 4):
                sb = QSpinBox()
                sb.setRange(1, sg.MAX_LEVEL)
                sb.setPrefix(f"tier {k + 1} to L")
                sb.setToolTip(f"The last level with reach {k + 1}; one level more gives reach {k + 2}")
                sb.setMinimumWidth(96)
                sb.valueChanged.connect(self._levels_edited)
                self.levels.append(sb)
                hl.addWidget(sb)
            gl.addRow("Tiers end at" if row_k == 0 else "", hl)
        row = QHBoxLayout()
        self.b_levels_reset = QPushButton("The game's levels")
        self.b_levels_reset.clicked.connect(lambda: self.set_levels(sg.DEFAULT_LEVELS))
        row.addWidget(self.b_levels_reset)
        self.levels_note = QLabel()
        self.levels_note.setWordWrap(True)
        self.levels_note.setObjectName("muted")
        row.addWidget(self.levels_note, 1)
        gl.addRow("", row)
        sv.addLayout(gl)
        lay.addWidget(self.spell_box)
        self.spell_box.hide()
        self.spell = False                    # a spell is shown (attack_map 0)
        self.fixed = False                    # the user wants it to have an area of its own
        self.edit_shape = None                # the spell shape being edited (1-9)
        self.growing_back = False             # the user asked for the spell to grow again (Save clears its area)
        self.levels0 = list(sg.DEFAULT_LEVELS)

        self.reach_box = g = QGroupBox("Reach")
        f = QFormLayout(g)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.range = QSpinBox()
        self.range.setRange(0, sa.MAP_WIDE)
        self.range.setSpecialValueText("0 (from the caster)")
        self.range.setToolTip("How far away the player can put the cursor (panels). With a reach the area is centred "
                              "on the cursor; 0 = no cursor, the area is placed from the caster; 99 = anywhere")
        self.range.valueChanged.connect(self._range)
        f.addRow("Cursor reach", self.range)
        self.cursor = QSpinBox()
        self.cursor.setRange(1, 20)
        self.cursor.setSuffix(" ahead")
        self.cursor.setToolTip("Where the cursor is in the preview (the same as ↔ in the Scene bar)")
        self.cursor.valueChanged.connect(self._cursor)
        f.addRow("Cursor at", self.cursor)
        self.up = QSpinBox()
        self.up.setRange(0, 255)
        self.up.setToolTip("How much higher than the caster a target may stand (height units of the map)")
        self.down = QSpinBox()
        self.down.setRange(0, 255)
        self.down.setToolTip("How much lower than the caster a target may stand")
        hr = QHBoxLayout()
        hr.addWidget(QLabel("up"))
        hr.addWidget(self.up)
        hr.addWidget(QLabel("down"))
        hr.addWidget(self.down)
        f.addRow("Height reach", hr)
        for w in (self.up, self.down):
            w.valueChanged.connect(self._heights)
        lay.addWidget(g)

        g = QGroupBox("Numbers")
        f = QFormLayout(g)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.sp = QSpinBox()
        self.sp.setRange(0, 9999)
        self.sp.setToolTip("SP the skill costs at level 1 (the game raises it with the skill's level)")
        f.addRow("SP cost", self.sp)
        self.effect = QSpinBox()
        self.effect.setRange(-9999, 9999)
        self.effect.setSuffix(" %")
        self.effect.setToolTip("The main effect's strength: damage and heals = a bonus on the attack formula "
                               "(Fire -10, Mega Fire 5, Giga 30, Omega 50, Tera 70; Big Bang 30); buffs and "
                               "debuffs = the stat change")
        self.effect_label = QLabel("Power")
        f.addRow(self.effect_label, self.effect)
        self.power = []
        for row_k in range(2):
            hl = QHBoxLayout()
            hl.setSpacing(3)
            for k in range(5):
                lv = row_k * 5 + k + 1
                sb = QSpinBox()
                sb.setRange(-9999, 9999)
                sb.setPrefix(f"L{lv} ")
                sb.setToolTip(f"The skill's power at skill level {lv} (% of its level-1 power: 100, 107, 114 … "
                              "for the game's attacks; buffs 30 … 75)")
                sb.setMinimumWidth(72)
                self.power.append(sb)
                hl.addWidget(sb)
            f.addRow("Per level" if row_k == 0 else "", hl)
        hl = QHBoxLayout()
        self.step = QSpinBox()
        self.step.setRange(-500, 500)
        self.step.setValue(7)
        self.step.setPrefix("+")
        self.step.setSuffix(" per level")
        hl.addWidget(self.step)
        b = QPushButton("Fill levels 2-10 from level 1")
        b.setToolTip("Level 1's power plus the step for every level after it")
        b.clicked.connect(self._fill_levels)
        hl.addWidget(b)
        hl.addStretch(1)
        f.addRow("", hl)
        self.at_level = QSpinBox()
        self.at_level.setRange(1, sg.MAX_LEVEL)
        self.at_level.setPrefix("level ")
        self.at_level.setToolTip("The skill level to look at: its power, and for a spell its reach and areas")
        self.at_level.valueChanged.connect(self._level_preview)
        self.at_level.valueChanged.connect(lambda *_: self._spell_preview())
        self.level_text = QLabel()
        self.level_text.setObjectName("muted")
        hl = QHBoxLayout()
        hl.addWidget(self.at_level)
        hl.addWidget(self.level_text, 1)
        f.addRow("Preview at", hl)
        for w in (self.sp, self.effect) + tuple(self.power):
            w.valueChanged.connect(self._numbers_edited)
        lay.addWidget(g)
        self.numbers0 = None                  # the numbers as saved

        self.start_box = g = QGroupBox("Start from a game shape")
        v = QVBoxLayout(g)
        self.shapes = QComboBox()
        self.shapes.setToolTip("Every area shape of the game (AttackMap.dat) and skills that use it")
        self.shapes.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.shapes.setMinimumContentsLength(14)
        self.shapes.view().setMinimumWidth(380)
        v.addWidget(self.shapes)
        b = QPushButton("Use this shape")
        b.clicked.connect(self._use_shape)
        v.addWidget(b)
        lay.addWidget(g)

        row = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save area")
        self.save_btn.setObjectName("primary")
        self.save_btn.setToolTip("Write the reach and the area into the active mod (magic.dat, AttackMap.dat). "
                                 "Install to use it in the game")
        self.save_btn.clicked.connect(lambda: self.ed.save_area())
        row.addWidget(self.save_btn)
        self.revert_btn = QPushButton("↺ Undo changes")
        self.revert_btn.clicked.connect(self.revert)
        row.addWidget(self.revert_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setMinimumWidth(10)
        self.note.setObjectName("muted")
        lay.addWidget(self.note)
        self._sync_buttons()

    # ---- data in
    def set_shapes(self, shape_map, names_of):
        """shape_map: {id: Shape}; names_of(shape id) -> skill names using it"""
        self.shapes.blockSignals(True)
        self.shapes.clear()
        for sid, sh in sorted(shape_map.items()):
            n = sum(1 for _, _, k in sh.cells if k != sa.USER_TO)
            who = names_of(sid)
            label = f"{sid} · {n} panel{'s' if n != 1 else ''}" + (f" · {', '.join(who[:2])}" if who else "") + \
                    (f" +{len(who) - 2}" if len(who) > 2 else "")
            self.shapes.addItem(label, sid)
        self.shapes.blockSignals(False)
        self.shape_map = shape_map

    def set_area(self, area, editable=True, cursor=1):
        self.saved = copy.deepcopy(area)
        self.grid.area = copy.deepcopy(area)
        self.grid.enemies = None
        self.grid.editable = editable
        self.grid.reset_history()
        self.grid.number = sum(1 for _, _, k in area.cells if k != sa.USER_TO) + 1
        if hasattr(self, "brushes"):
            self.brushes.sync()
            self.brushes.setEnabled(editable)
        self.grid.cursor = cursor
        for w, v in ((self.range, area.range), (self.up, area.height_up), (self.down, area.height_down),
                     (self.cursor, cursor)):
            w.blockSignals(True)
            w.setValue(int(v))
            w.blockSignals(False)
        k = self.shapes.findData(area.shape)
        if k >= 0:
            self.shapes.setCurrentIndex(k)
        self.grid.update()
        self._sync_buttons()

    # ---- numbers
    NUMBERS = ("sp_cost", "effect1_value") + tuple(f"power_lv{k}" for k in range(1, 11))

    def set_numbers(self, row):
        """the skill's magic.dat row (None: no numbers to edit)"""
        vals = None
        if row is not None:
            try:
                vals = {f: int(row[f]) for f in self.NUMBERS}
                vals["effect1_type"] = int(row["effect1_type"])
            except Exception:
                vals = None
        self.numbers0 = dict(vals) if vals else None
        on = vals is not None
        for w in (self.sp, self.effect) + tuple(self.power):
            w.setEnabled(on)
            w.blockSignals(True)
        if on:
            self.sp.setValue(vals["sp_cost"])
            self.effect.setValue(vals["effect1_value"])
            for k, sb in enumerate(self.power):
                sb.setValue(vals[f"power_lv{k + 1}"])
            t = vals["effect1_type"]
            self.effect_label.setText("Power bonus" if t == 1 else "Buff / debuff" if t in (11, 12) else
                                      f"Effect {t} value")
        for w in (self.sp, self.effect) + tuple(self.power):
            w.blockSignals(False)
        self._level_preview()

    def numbers(self):
        out = {"sp_cost": self.sp.value(), "effect1_value": self.effect.value()}
        for k, sb in enumerate(self.power):
            out[f"power_lv{k + 1}"] = sb.value()
        return out

    def numbers_changed(self):
        n0 = self.numbers0
        return n0 is not None and any(self.numbers()[f] != n0[f] for f in self.NUMBERS)

    def apply_numbers(self, row):
        """-> True when a field of the row changed"""
        if self.numbers0 is None or row is None:
            return False
        changed = False
        for f, v in self.numbers().items():
            if int(row[f]) != int(v):
                row.set(f, int(v))
                changed = True
        if changed:
            self.numbers0 = dict(self.numbers0, **self.numbers())
        return changed

    def _numbers_edited(self, *_):
        self._level_preview()
        self._sync_buttons()
        fn = getattr(self.ed, "_update_buttons", None)
        if fn:
            fn()

    def _fill_levels(self):
        base, step = self.power[0].value(), self.step.value()
        for k, sb in enumerate(self.power[1:], 1):
            sb.setValue(base + step * k)

    def _level_preview(self, *_):
        if self.numbers0 is None:
            self.level_text.setText("")
            return
        lv = self.at_level.value()
        pw = self.power[min(lv, 10) - 1].value()
        sp = self.sp.value()
        self.level_text.setText(f"power {pw} % of level 1" + (" (the table ends at level 10)" if lv > 10 else "") +
                                f", bonus {self.effect.value():+d} %, {sp} SP at level 1 (the game raises SP with "
                                "the level)")

    # ---- spells
    def set_spell(self, on, levels=None, owner=None, fixed=False):
        """on: the skill is a spell (generic magic: its reach and area come from its level); fixed: it was given a
        reach and an area of its own (magic.dat), which Save keeps editing like a weapon skill's -- 'Back to growing
        with the level' takes them away.  levels: the thresholds in force (sg.effective), owner: their mod"""
        self.spell = bool(on)
        self.fixed = bool(on and fixed)
        self.edit_shape = None
        self.growing_back = False
        self.spell_box.setVisible(self.spell)
        self.levels0 = list(levels or sg.DEFAULT_LEVELS)
        self.set_levels(self.levels0)
        self.levels_note.setText(("The game's own levels." if owner is None else f"Set by the mod '{owner.name}'.") +
                                 " One setting for every spell; the install patches the game for it.")
        self._spell_buttons()
        if self.spell and not self.fixed:
            self._spell_preview()
        elif self.spell:
            self.spell_text.setText("This spell has a reach and an area of its own (set below, like a weapon "
                                    "skill's): its level no longer grows them. 'Back to growing with the level' "
                                    "takes them away again.")
        else:
            self.reach_box.setVisible(True)
            self.start_box.setVisible(True)

    def set_levels(self, levels):
        for sb, v in zip(self.levels, sg.clean(levels)):
            sb.blockSignals(True)
            sb.setValue(int(v))
            sb.blockSignals(False)
        self._levels_edited()

    def levels_now(self):
        return sg.clean([sb.value() for sb in self.levels])

    def levels_changed(self):
        return self.spell and self.levels_now() != sg.clean(self.levels0)

    def _levels_edited(self, *_):
        self._spell_preview()
        self._sync_buttons()
        fn = getattr(self.ed, "_update_buttons", None)
        if fn:
            fn()

    def _spell_buttons(self):
        preview = self.spell and not self.fixed
        self.b_edit_shape.setVisible(preview)
        self.b_fixed.setVisible(preview)
        self.b_grow.setVisible(self.spell and self.fixed)
        self.spell_shape.setEnabled(preview)
        for sb in self.levels:
            sb.setEnabled(preview)
        self.b_levels_reset.setEnabled(preview)
        self.reach_box.setVisible(not preview)
        self.start_box.setVisible(not preview or self.edit_shape is not None)

    def _spell_preview(self):
        """the grid shows the chosen shape at the reach of the level previewed (reach = tier)"""
        if not self.spell or self.fixed:
            return
        shape_map = getattr(self, "shape_map", {})
        t = sg.tier(self.at_level.value(), self.levels_now())
        cur = self.spell_shape.currentData() or t
        self.spell_shape.blockSignals(True)
        self.spell_shape.clear()
        for sid in sg.SPELL_SHAPES:
            sh = shape_map.get(sid)
            n = len(sh.cells) if sh else 0
            self.spell_shape.addItem(f"shape {sid} · {n} panel{'s' if n != 1 else ''}", sid)
        pick = self.edit_shape or int(cur)
        self.spell_shape.setCurrentIndex(self.spell_shape.findData(pick))
        self.spell_shape.blockSignals(False)
        sid = self.spell_shape.currentData()
        sh = shape_map.get(sid)
        if self.edit_shape == sid and self.grid.area.shape == sid:
            cells = self.grid.area.cells                      # being edited: keep the edits
        else:
            cells = list(sh.cells) if sh else [(0, 0, sa.CURSOR)]
        skill = self.grid.area.skill
        self.grid.area = sa.Area(skill=skill, range=t, shape=sid, cells=cells, height_up=self.up.value(),
                                 height_down=self.down.value(), known=True)
        self.grid.editable = self.edit_shape == sid
        self.grid.update()
        self.spell_text.setText(
            f"In battle a spell takes nothing from the table: its level sets a tier -- {sg.reach_text(self.levels_now())}"
            f" -- and the tier is its reach in panels (+1 with a staff, some classes add more). Level "
            f"{self.at_level.value()}: reach {t}. Its area is one of the nine spell shapes; how many of them a unit may "
            f"pick is kept with that unit's spell (one at first, more as the game unlocks them; the level doesn't "
            f"change it). The grid shows the shape chosen above at that reach.")
        self._spell_buttons()
        self._sync_buttons()
        self.ed.area_edited()

    def _edit_shape(self):
        sid = self.spell_shape.currentData()
        if sid is None:
            return
        self.edit_shape = int(sid)
        self._spell_preview()
        self.summary.setText(f"Editing spell shape {sid}: click panels, then Save. Every spell uses it.")

    def _make_fixed(self):
        """the spell gets a reach and an area of its own (saved like a weapon skill's)"""
        self.fixed = True
        self.edit_shape = None
        a = self.grid.area
        self.saved = sa.default_area(a.skill)
        self.grid.area = sa.Area(skill=a.skill, range=a.range, shape=0, cells=list(a.cells), height_up=a.height_up,
                                 height_down=a.height_down, known=True)
        self.grid.editable = True
        self.range.blockSignals(True)
        self.range.setValue(a.range)
        self.range.blockSignals(False)
        self._spell_buttons()
        self.spell_text.setText("This spell will have a reach and an area of its own, whatever its level: set them "
                                "here and Save. 'Back to growing with the level' undoes it.")
        self.grid.update()
        self._edited()

    def _make_growing(self):
        self.growing_back = True
        self.fixed = False
        self._spell_buttons()
        self._spell_preview()
        self.summary.setText("Save takes the spell's own area away: its level rules again.")
        fn = getattr(self.ed, "_update_buttons", None)
        if fn:
            fn()

    def shape_edit_changed(self):
        if not self.spell or self.edit_shape is None:
            return False
        sh = getattr(self, "shape_map", {}).get(self.edit_shape)
        return sh is None or list(self.grid.area.cells) != list(sh.cells)

    def pending(self):
        """what Save has to write for a spell: ("shape", sid, cells) / ("fixed", area) / ("grow",) and the levels"""
        out = {"levels": self.levels_now() if self.levels_changed() else None}
        if not self.spell:
            return out
        if self.growing_back:
            out["kind"] = "grow"
        elif self.fixed and self.changed():
            out["kind"] = "fixed"
        elif self.shape_edit_changed():
            out["kind"] = "shape"
            out["sid"] = self.edit_shape
            out["cells"] = list(self.grid.area.cells)
        return out

    def set_cursor(self, n):
        self.grid.cursor = int(n)
        self.cursor.blockSignals(True)
        self.cursor.setValue(int(n))
        self.cursor.blockSignals(False)
        self.grid.update()

    def area(self):
        return self.grid.area

    def changed(self):
        if self.spell and not self.fixed:
            return self.shape_edit_changed() or self.growing_back
        a, s = self.grid.area, self.saved
        return s is not None and (a.cells != s.cells or a.range != s.range or a.height_up != s.height_up
                                  or a.height_down != s.height_down)

    # ---- edits
    def _sync_buttons(self):
        ch = self.changed() or self.numbers_changed() or self.levels_changed()
        self.save_btn.setEnabled(ch and self.grid.editable)
        self.revert_btn.setEnabled(ch)
        a = self.grid.area
        if self.spell and not self.fixed and self.edit_shape is None and not self.growing_back:
            self.summary.setText(f"Spell at level {self.at_level.value()}: " + sa.describe(a) +
                                 ("  · not saved" if ch else ""))
        else:
            self.summary.setText(sa.describe(a) + ("  · not saved" if ch else ""))
        self.cursor.setEnabled(a.centred)
        shared = [n for n in self.shape_users_of(a.shape) if n != a.skill] if a.shape else []
        if self.spell and not self.fixed:
            self.note.setText("Edit this shape changes it for every spell; the tier levels (the reach) are one "
                              "setting for all spells (the install patches the game). Saved into the skill's mod; "
                              "Install to use it in the game.")
        else:
            self.note.setText(
                ("Changing it makes a new shape for this skill only (shape "
                 f"{a.shape} stays as it is for the other skills that use it). " if shared else "")
                + "Saved into the active mod's database changes; Install to use it in the game.")

    def shape_users_of(self, sid):
        return self.shape_users.get(sid, [])

    def _edited(self):
        self._sync_buttons()
        self.ed.area_edited()
        fn = getattr(self.ed, "_update_buttons", None)
        if fn:
            fn()

    def _enemies(self):
        self.ed.area_enemies(self.grid.enemies)

    def _range(self, v):
        self.grid.area.range = int(v)
        self.grid.update()
        self._edited()

    def _cursor(self, v):
        self.grid.cursor = int(v)
        self.grid.update()
        self.ed.area_cursor(int(v))

    def _heights(self, *_):
        self.grid.area.height_up = self.up.value()
        self.grid.area.height_down = self.down.value()
        self._edited()

    def _use_shape(self):
        sid = self.shapes.currentData()
        sh = getattr(self, "shape_map", {}).get(sid)
        if sh is None:
            return
        self.grid._set_cells(list(sh.cells))

    def _fill_enemies(self):
        g = self.grid
        g.enemies = [(x, y) for x, y, k in g.area.panels(g.cursor) if k != sa.USER_TO] or None
        g.update()
        self._enemies()

    def _one_enemy(self):
        self.grid.enemies = None
        self.grid.update()
        self._enemies()

    def revert(self):
        if self.spell:
            self.set_levels(self.levels0)
            self.edit_shape = None
            self.growing_back = False
            if self.fixed:
                self.fixed = False
            self._spell_buttons()
            self._spell_preview()
        if self.numbers0 is not None:
            for w, f in ((self.sp, "sp_cost"), (self.effect, "effect1_value")):
                w.blockSignals(True)
                w.setValue(self.numbers0[f])
                w.blockSignals(False)
            for k, sb in enumerate(self.power):
                sb.blockSignals(True)
                sb.setValue(self.numbers0[f"power_lv{k + 1}"])
                sb.blockSignals(False)
            self._level_preview()
        if self.saved is not None:
            self.grid.area = copy.deepcopy(self.saved)
            for w, v in ((self.range, self.saved.range), (self.up, self.saved.height_up),
                         (self.down, self.saved.height_down)):
                w.blockSignals(True)
                w.setValue(int(v))
                w.blockSignals(False)
            self.grid.update()
            self._edited()
        fn = getattr(self.ed, "_update_buttons", None)
        if fn:
            fn()
