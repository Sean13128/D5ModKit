"""Area: where the skill hits (magic.dat range / attack_map / height reach + AttackMap.dat shapes; d5lib/skillarea.py).

A grid of panels around the caster (forward = up, as the skill faces): click panels to change the area, or switch
to "place enemies" and click hit panels to put enemies on them (the preview then plays the skill on all of them,
in the game's target order).  Changes show in the preview at once; Save area writes them into the active mod."""
import copy

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QPolygonF
from PyQt6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
                             QFormLayout, QSpinBox, QRadioButton, QButtonGroup, QComboBox, QSizePolicy)

from d5lib import skillarea as sa

COLORS = {sa.HIT: QColor(235, 78, 60), sa.CURSOR: QColor(240, 150, 50), sa.USER_TO: QColor(70, 220, 150)}
REACH = QColor(80, 140, 240)
ENEMY = QColor(52, 72, 170)


class AreaGrid(QWidget):
    """the panels around the caster; emits edited() after a change of the area, enemiesEdited() of the enemies"""
    edited = pyqtSignal()
    enemiesEdited = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.area = sa.default_area()
        self.cursor = 1
        self.enemies = None                  # None: the first hit panel
        self.mode = "area"
        self.editable = True
        self._drag = None                    # (adding, visited) while painting
        self.setMouseTracking(True)
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
        tg = self.area.target_panels(self.cursor, self.enemies)
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

    def mousePressEvent(self, e):
        p = self._at(e.position())
        if p is None or not self.editable:
            return
        if self.mode == "enemies":
            self._toggle_enemy(p)
            return
        cx, cy = self._cell_of(p)
        cells = list(self.area.cells)
        idx = next((i for i, (x, y, _) in enumerate(cells) if (x, y) == (cx, cy)), None)
        if e.button() == Qt.MouseButton.RightButton:
            order = [sa.HIT, sa.CURSOR, sa.USER_TO]
            if idx is None:
                cells.append((cx, cy, sa.HIT))
            else:
                k = cells[idx][2]
                cells[idx] = (cx, cy, order[(order.index(k) + 1) % 3] if k in order else sa.HIT)
            self._set_cells(cells)
            return
        adding = idx is None
        self._drag = (adding, {(cx, cy)})
        self._apply(cx, cy, adding)

    def mouseMoveEvent(self, e):
        p = self._at(e.position())
        if p is not None:
            cx, cy = self._cell_of(p)
            k = next((k for x, y, k in self.area.cells if (x, y) == (cx, cy)), None)
            where = f"{abs(p[0])} {'right' if p[0] > 0 else 'left'}, " if p[0] else ""
            where += f"{abs(p[1])} {'ahead' if p[1] >= 0 else 'behind'}"
            self.setToolTip(f"Panel {where} of the caster" + (f" — {sa.KIND_NAMES[k]}" if k else ""))
        if self._drag is None or p is None:
            return
        cx, cy = self._cell_of(p)
        adding, seen = self._drag
        if (cx, cy) not in seen:
            seen.add((cx, cy))
            self._apply(cx, cy, adding)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def _apply(self, cx, cy, adding):
        cells = list(self.area.cells)
        have = any((x, y) == (cx, cy) for x, y, _ in cells)
        if adding and not have:
            cells.append((cx, cy, sa.HIT))
        elif not adding and have:
            cells = [c for c in cells if (c[0], c[1]) != (cx, cy)]
        else:
            return
        self._set_cells(cells)

    def _set_cells(self, cells):
        if len(cells) > sa.MAX_CELLS:
            return
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
                       "where the caster ends up, blue is where the player can put the cursor. Click or drag to "
                       "add / remove panels, right-click a panel to change its kind.")
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

        g = QGroupBox("Reach")
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

        g = QGroupBox("Start from a game shape")
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

    def set_cursor(self, n):
        self.grid.cursor = int(n)
        self.cursor.blockSignals(True)
        self.cursor.setValue(int(n))
        self.cursor.blockSignals(False)
        self.grid.update()

    def area(self):
        return self.grid.area

    def changed(self):
        a, s = self.grid.area, self.saved
        return s is not None and (a.cells != s.cells or a.range != s.range or a.height_up != s.height_up
                                  or a.height_down != s.height_down)

    # ---- edits
    def _sync_buttons(self):
        ch = self.changed()
        self.save_btn.setEnabled(ch and self.grid.editable)
        self.revert_btn.setEnabled(ch)
        a = self.grid.area
        self.summary.setText(sa.describe(a) + ("  · not saved" if ch else ""))
        self.cursor.setEnabled(a.centred)
        shared = [n for n in self.shape_users_of(a.shape) if n != a.skill] if a.shape else []
        self.note.setText(
            ("Changing it makes a new shape for this skill only (shape "
             f"{a.shape} stays as it is for the other skills that use it). " if shared else "")
            + "Saved into the active mod's database changes; Install to use it in the game.")

    def shape_users_of(self, sid):
        return self.shape_users.get(sid, [])

    def _edited(self):
        self._sync_buttons()
        self.ed.area_edited()

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
        if self.saved is not None:
            self.grid.area = copy.deepcopy(self.saved)
            for w, v in ((self.range, self.saved.range), (self.up, self.saved.height_up),
                         (self.down, self.saved.height_down)):
                w.blockSignals(True)
                w.setValue(int(v))
                w.blockSignals(False)
            self.grid.update()
            self._edited()
