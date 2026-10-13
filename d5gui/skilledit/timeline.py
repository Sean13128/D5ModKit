"""The timeline of a skill (works like Blender's dope sheet / Spine's timeline).

Rows are grouped (Camera, Characters, Effects, Particles, Sounds, Hits); click a group's ▾ to fold it.  The group
row shows a summary of everything in it.

Every clip shows where it starts and ends: its left and right edges (the selected one also on the ruler, with
the frame numbers), a picture of the effect or pose at its start.  Commands that happen at one moment are chips at
their frame.

Mouse
  click                select (Shift or Ctrl: add / remove)          drag a clip      move the WHOLE clip in time
  drag on empty space  box select (Shift: add, Ctrl: remove)                          (after 5 pixels; the old place
  click on empty space deselect and move the playhead                                 stays outlined; the selection
  ruler                scrub                                                          moves together; snaps to the
  a clip's right edge  drag to change when it ends                                    playhead and clip edges, Alt:
  Alt+drag a mark      move one command inside a clip                                 no snap; Esc cancels)
  track name           select its clips
  hover a track name   👁 hide / show it in the preview, 🗑 delete the track (everything in it)
  right-click          menu (add, delete, duplicate, select …)       Ctrl+wheel zoom, Shift+wheel scroll in time
Keys
  Delete / X delete    Shift+D / Ctrl+D duplicate    Ctrl+C / Ctrl+V copy, paste at the playhead
  A all  Alt+A none  Ctrl+I invert  [ / ] everything before / after the playhead
  G move the selection in time with the mouse (click / Enter: done, Esc: cancel)
  ← → frame (Shift: 10)  Home / End  F fit the whole skill"""
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QPolygonF, QCursor
from PyQt6.QtWidgets import QWidget, QMenu, QToolTip, QScrollBar

from d5lib import choreo

MIME = "application/x-d5-effect"
HEAD_W = 230
RULER_H = 28
ROW_H = 30
GROUP_H = 24
DRAG_PX = 5                              # a press only becomes a drag after moving this far
KIND_GLYPH = {"camera": "🎥", "sound": "🔊", "hit": "💥", "particle": "✦", "actor": "🧍", "extra": "👥",
              "other": "⋯", "slot": "✨"}
COLORS = {"camera": "#4fb3d9", "actor": "#8b5cf6", "motion": "#8b5cf6", "slot": "#e0457b", "particle": "#f5a524",
          "sound": "#3ecf8e", "hit": "#ff6b6b", "extra": "#a78bfa", "other": "#9a95b0"}
GROUPS = [("camera", "🎥  Camera"), ("actor", "🧍  Caster & targets"), ("slot", "✨  Effects"),
          ("particle", "🌟  Particles"), ("sound", "🔊  Sounds"), ("hit", "💥  Hits & damage"),
          ("extra", "👥  Extra characters, copies & markers"), ("other", "⋯  Other commands")]
FOLDED = {"extra", "other"}              # groups that start folded (helpers most edits don't need)
KIND_GROUPS = GROUPS                     # (kept for older imports)
SNAP_PX = 7


@dataclass(eq=False)
class Item:
    start: int
    end: int
    label: str
    ops: list
    kind: str                       # clip | motion | bar | key
    color: str
    tip: str = ""
    keys: list = field(default_factory=list)   # (frame, op) markers inside a clip
    thin: bool = False                         # drawn as a thin bar under the row's clips
    slot: object = None                        # effect clips: slot, effect id, index of the clip in its slot
    effect: object = None
    index: int = 0
    moves: bool = False                        # the clip moves / turns (drawn with a dotted line)
    removable_end: bool = False                # has a 'disappears' command: its end can be dragged


@dataclass
class Row:
    key: tuple
    title: str
    items: list
    color: str
    tip: str = ""

    @property
    def group(self):
        k = self.key[0]
        if k == "actor":
            a = self.key[1] if len(self.key) > 1 else None
            return "actor" if a == choreo.CASTER or choreo.is_target(a) else "extra"
        return k if k in COLORS and k not in ("motion",) else "other"


def build_rows(tl, names=None, motion_name=None):
    """names: d5lib.fxnames.Names (effect names) or None; motion_name(m) -> text or None"""
    rows = []
    for key, title, ops in tl.tracks():
        kind = key[0]
        col = COLORS.get(kind, "#999")
        items = []
        tip = ""
        if kind == "slot":
            effects = []
            for k, c in enumerate(tl.clips(key[1])):
                keys = [(o.frame, o) for o in c["ops"] if o.cid not in (0x3c00,) and o is not c["show"]]
                e = c["effect"]
                effects.append(e)
                if names is not None and e is not None:
                    label = names.name(e)
                    t = (f"{names.tooltip(e)}<br><i>slot {key[1]}, frames {c['start']}–{c['end']}</i>")
                else:
                    label = f"fx {e}"
                    t = f"Effect {e} in slot {key[1]}, frames {c['start']}–{c['end']}"
                moves = any(o.cid in (0x4140, 0x4170) for o in c["ops"])
                removable = any(o.cid == 0x3c02 for o in c["ops"])
                items.append(Item(c["start"], c["end"], label, c["ops"], "clip", col, t, keys, slot=key[1],
                                  effect=e, index=k, moves=moves, removable_end=removable))
            shown = {id(o) for it in items for o in it.ops}
            for o in ops:                                   # loads without a show, stray changes
                if id(o) not in shown:
                    items.append(Item(o.frame, o.end, o.label(), [o], "key" if not o.dur else "bar", col,
                                      _tip(o), slot=key[1]))
            uniq = [e for k, e in enumerate(effects) if e is not None and e not in effects[:k]]
            if uniq and names is not None:
                title = f"{names.name(uniq[0])}" + (f"  +{len(uniq) - 1}" if len(uniq) > 1 else "")
                tip = f"effect slot {key[1]}<br>" + "<br>".join(names.label(e) for e in uniq)
            else:
                title = f"Effect slot {key[1]}"
        elif kind == "actor":
            a = key[1]
            title = actor_title(a, title)
            for s, e, m, o in tl.motions(a):
                mn = motion_name(m) if motion_name else None
                items.append(Item(s, e, f"{mn} ({m})" if mn else f"pose {m}", [o], "motion", col,
                                  f"Pose {m}{' — ' + mn if mn else ''} from frame {s}"))
            for o in ops:
                if o.cid == 0x6510:
                    continue
                items.append(Item(o.frame, max(o.end, o.frame), o.label(), [o], "bar" if o.dur else "key",
                                  "#b49cff", _tip(o), thin=bool(o.dur)))
        else:
            for o in ops:
                items.append(Item(o.frame, max(o.end, o.frame), o.label(), [o], "bar" if o.dur else "key", col,
                                  _tip(o)))
        rows.append(Row(key, title, items, col, tip))
    # effects and particles in the order they first appear (the list reads like the skill plays)
    first = {id(r): min((it.start for it in r.items), default=1 << 30) for r in rows}
    for kind in ("slot", "particle"):
        idx = [k for k, r in enumerate(rows) if r.key[0] == kind]
        ordered = sorted((rows[k] for k in idx), key=lambda r: (first[id(r)], str(r.key)))
        for k, r in zip(idx, ordered):
            rows[k] = r
    return rows


def actor_title(a, default):
    """friendlier names for the helper actors skills use"""
    if a == choreo.CASTER:
        return "Caster"
    if a == choreo.TARGET:
        return "Target"
    if choreo.is_target(a):
        return choreo.ACTOR_NAMES.get(a, default)
    if isinstance(a, int) and 10000 <= a < 20000:
        base = choreo.actor_id(a - 10000) if a > 10000 else choreo.CASTER     # 10000: the skill's user
        who = {choreo.CASTER: "the caster", choreo.TARGET: "the target"}.get(base, f"actor {a - 10000}")
        return f"Where {who} stood (marker {a})"
    if isinstance(a, int) and 1000 <= a < 1100:
        return f"Extra character {a} (copy / summon)"
    return default


def _tip(op):
    names = choreo.arg_names(op.cid)
    args = ", ".join(f"{n} {v}" for n, v in zip(names, op.args)) if names else ", ".join(map(str, op.args))
    return f"<b>{op.name}</b> at frame {op.frame}<br>{choreo.describe(op.cid)}<br><i>{args}</i>"


class TimelineView(QWidget):
    frameChanged = pyqtSignal(int)
    selected = pyqtSignal(object)                 # primary selection: Item, ('key', frame, op, item) or None
    selectionChanged = pyqtSignal(list)           # all selected Items
    moveRequested = pyqtSignal(object, int)       # Item / key / [Items], delta frames
    deleteRequested = pyqtSignal(object)          # Item / key / [Items]
    addRequested = pyqtSignal(str, int, object)   # what, frame, row key
    effectDropped = pyqtSignal(int, int, object)  # effect id, frame, row key
    trimRequested = pyqtSignal(object, int)       # Item, delta frames of its end
    duplicateRequested = pyqtSignal(list, int)    # Items, frame offset
    pasteRequested = pyqtSignal(int)              # playhead frame
    copyRequested = pyqtSignal(list)
    trackDeleteRequested = pyqtSignal(object)     # Row
    trackHideToggled = pyqtSignal(object, bool)   # Row, hidden

    def __init__(self):
        super().__init__()
        self.icon_for = None           # callable(Item) -> QPixmap or None (effect / pose pictures)
        self._ver = 0                  # bumped whenever the rows change (the cached picture is redrawn)
        self._glyphs = {}
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(160)
        self.all_rows = []
        self.lines = []                # display: ("group", gkey, title, rows) / ("row", Row)
        self.rows = []                 # visible track rows
        self.collapsed = set(FOLDED)
        self.hidden_tracks = set()     # row keys hidden in the preview
        self.filter_text = ""
        self.length = 60
        self.frame = 0
        self.ppf = 6.0
        self.xoff = 0.0
        self.yoff = 0
        self.sel = None
        self.multi = []
        self.drag = None               # moving / trimming items
        self.band = None               # box select
        self.press = None              # a press on empty space (click or box)
        self.grab = None               # G: move with the mouse
        self.scrubbing = False
        self.drop_frame = None
        self.snap_frame = None
        self.hover_line = None
        self.hscroll = QScrollBar(Qt.Orientation.Horizontal, self)
        self.hscroll.valueChanged.connect(self._hscrolled)
        self.vscroll = QScrollBar(Qt.Orientation.Vertical, self)
        self.vscroll.valueChanged.connect(self._vscrolled)

    def sizeHint(self):
        return QSize(900, 320)

    # ---------------------------------------------------------------- data
    def set_rows(self, rows, length, keep=None):
        self.all_rows = rows
        self.length = max(1, length)
        self._layout()
        self.sel = self._find(keep) if keep else None
        self.multi = [self.sel] if isinstance(self.sel, Item) else []
        self._scrollbars()
        self.update()

    def set_filter(self, hidden_kinds=None, text=None):
        if text is not None:
            self.filter_text = text.strip().lower()
        self._layout()
        self._scrollbars()
        self.update()

    def _layout(self):
        self._ver += 1
        q = self.filter_text
        groups = {}
        for r in self.all_rows:
            if q and q not in r.title.lower() and not any(q in it.label.lower() for it in r.items):
                continue
            groups.setdefault(r.group, []).append(r)
        self.lines, self.rows = [], []
        for gk, title in GROUPS:
            rs = groups.get(gk)
            if not rs:
                continue
            self.lines.append(("group", gk, title, rs))
            if gk not in self.collapsed or q:                 # a search shows its hits in folded groups too
                for r in rs:
                    self.lines.append(("row", r))
                    self.rows.append(r)

    def _line_h(self, ln):
        return GROUP_H if ln[0] == "group" else ROW_H

    def _line_y(self, k):
        return RULER_H + sum(self._line_h(self.lines[i]) for i in range(k)) - self.yoff

    def _line_at(self, y):
        if y < RULER_H:
            return None
        yy = RULER_H - self.yoff
        for k, ln in enumerate(self.lines):
            h = self._line_h(ln)
            if yy <= y < yy + h:
                return k
            yy += h
        return None

    def _row_index_y(self, row):
        for k, ln in enumerate(self.lines):
            if ln[0] == "row" and ln[1] is row:
                return self._line_y(k)
        return None

    def _find(self, key):
        kind, ident = key
        for r in self.all_rows:
            for it in r.items:
                if kind == "item" and it.ops and _ident(it.ops[0]) == ident:
                    return it
                if kind == "key":
                    for f, o in it.keys:
                        if _ident(o) == ident:
                            return ("key", f, o, it)
        return None

    def selection_key(self):
        s = self.sel
        if s is None:
            return None
        if isinstance(s, tuple):
            return ("key", _ident(s[2]))
        return ("item", _ident(s.ops[0])) if s.ops else None

    def clip_keys(self):
        return [(it.slot, it.index) for it in self.multi if it.kind == "clip" and it.slot is not None]

    def select_clip_keys(self, keys, emit=True, add=False):
        want = set(keys)
        found = [it for r in self.all_rows for it in r.items if it.kind == "clip" and (it.slot, it.index) in want]
        if add:
            found = self.multi + [it for it in found if not any(it is m for m in self.multi)]
        self._set_selection(found, found[0] if found else None, emit)

    def _set_selection(self, items, primary, emit=True):
        self.multi = list(items)
        self.sel = primary
        self.update()
        if emit:
            self.selected.emit(primary)
            self.selectionChanged.emit(list(self.multi))

    def select_similar(self):
        effects = {it.effect for it in self.multi if it.kind == "clip" and it.effect is not None}
        if not effects:
            return
        found = [it for r in self.all_rows for it in r.items if it.kind == "clip" and it.effect in effects]
        self._set_selection(found, self.sel if self.sel in found else found[0])

    def select_rows_of_selection(self):
        rows = {id(r) for r in self.all_rows if any(it in r.items for it in self.multi)}
        found = [it for r in self.all_rows if id(r) in rows for it in r.items if it.kind == "clip"]
        if found:
            self._set_selection(found, found[0])

    def clear_selection(self):
        self._set_selection([], None)

    def _all_items(self):
        return [it for r in self.rows for it in r.items]

    def set_frame(self, f):
        self.frame = max(0, min(int(f), self.length))
        x = self._x(self.frame)
        if x < HEAD_W + 10 or x > self.width() - 30:
            self.xoff = max(0.0, self.frame * self.ppf - (self.width() - HEAD_W) * 0.3)
            self._scrollbars()
        self.update()

    def fit(self):
        self.ppf = max(1.0, (self.width() - HEAD_W - 30) / max(10, self.length + 10))
        self.xoff = 0
        self._scrollbars()
        self.update()

    def zoom(self, factor):
        f = self._f(HEAD_W + (self.width() - HEAD_W) / 2)
        self.ppf = max(0.5, min(40.0, self.ppf * factor))
        self.xoff = max(0.0, f * self.ppf - (self.width() - HEAD_W) / 2)
        self._scrollbars()
        self.update()

    # ---------------------------------------------------------------- geometry
    def _x(self, f):
        return HEAD_W + f * self.ppf - self.xoff

    def _f(self, x):
        return (x - HEAD_W + self.xoff) / self.ppf

    def _item_rect(self, y, it):
        x0 = self._x(it.start)
        if it.kind in ("clip", "motion", "bar") and it.end > it.start:
            x1 = self._x(it.end)
            if it.thin:
                return QRectF(x0, y + ROW_H - 7, max(6.0, x1 - x0), 5)
            return QRectF(x0, y + 3, max(6.0, x1 - x0), ROW_H - 6)
        return QRectF(x0 - 6, y + 7, 12, ROW_H - 14)

    def _scrollbars(self):
        w, h = self.width(), self.height()
        content_w = (self.length + 30) * self.ppf
        view_w = max(1, w - HEAD_W - 14)
        self.hscroll.setGeometry(HEAD_W, h - 14, w - HEAD_W - 14, 14)
        self.hscroll.setRange(0, int(max(0, content_w - view_w)))
        self.hscroll.setPageStep(int(view_w))
        self.hscroll.blockSignals(True)
        self.hscroll.setValue(int(self.xoff))
        self.hscroll.blockSignals(False)
        content_h = sum(self._line_h(ln) for ln in self.lines)
        view_h = max(1, h - RULER_H - 14)
        self.vscroll.setGeometry(w - 14, RULER_H, 14, h - RULER_H - 14)
        self.vscroll.setRange(0, int(max(0, content_h - view_h)))
        self.vscroll.setPageStep(int(view_h))
        self.vscroll.setVisible(content_h > view_h)
        self.yoff = min(self.yoff, self.vscroll.maximum())

    def _hscrolled(self, v):
        self.xoff = float(v)
        self.update()

    def _vscrolled(self, v):
        self.yoff = v
        self.update()

    def resizeEvent(self, e):
        self._scrollbars()

    # ---------------------------------------------------------------- hit test
    def _hit(self, pos, keys=False):
        """-> (item / key tuple / None, line index, part: 'body' | 'end'); keys: the marks inside a selected clip
        count (Alt) -- otherwise a press on a clip always takes the whole clip"""
        k = self._line_at(pos.y())
        if k is None or pos.x() < HEAD_W or self.lines[k][0] != "row":
            return None, k, None
        r = self.lines[k][1]
        y = self._line_y(k)
        p = QPointF(pos.x(), pos.y())
        for it in reversed(r.items):
            if keys and (it in self.multi or it is self.sel or self._is_selected(it)):
                for f, o in it.keys:
                    if abs(self._x(f) - pos.x()) <= 5 and pos.y() >= y + ROW_H / 2 - 2:
                        return ("key", f, o, it), k, "body"
        for it in reversed(r.items):
            rect = self._item_rect(y, it)
            if it.kind == "clip" and it.removable_end and abs(pos.x() - rect.right()) <= 5 and \
                    rect.top() <= pos.y() <= rect.bottom() and rect.width() > 14:
                return it, k, "end"
            if rect.adjusted(-2, 0, 2, 0).contains(p):
                return it, k, "body"
        return None, k, None

    def _header_buttons(self, y):
        """(eye rect, bin rect) of a track header at y"""
        return (QRectF(HEAD_W - 52, y + 4, 20, ROW_H - 8), QRectF(HEAD_W - 28, y + 4, 20, ROW_H - 8))

    def _is_selected(self, it):
        return it is self.sel or any(it is m for m in self.multi) or \
            (isinstance(self.sel, tuple) and self.sel[3] is it)

    # ---------------------------------------------------------------- paint
    def _state_key(self):
        """everything the picture shows except the playhead (playback only moves the playhead: the rest is reused)"""
        d = self.drag
        g = self.grab
        return (self.width(), self.height(), self.devicePixelRatioF(), self.xoff, self.yoff, self.ppf, self.length,
                self._ver, len(self.lines), tuple(sorted(self.collapsed)), len(self.hidden_tracks),
                tuple(sorted(map(str, self.hidden_tracks))), self.filter_text, id(self.sel),
                tuple(id(m) for m in self.multi), self.hover_line, self.drop_frame, self.snap_frame,
                tuple(self.band) if self.band else None,
                (d["mode"], d.get("armed"), d["delta"], id(d["target"])) if d else None,
                (g["delta"], len(g["items"])) if g else None)

    def paintEvent(self, e):
        from PyQt6.QtGui import QPixmap
        w, h = self.width(), self.height()
        key = self._state_key()
        if getattr(self, "_cache_key", None) != key or getattr(self, "_cache", None) is None:
            dpr = self.devicePixelRatioF()
            pm = QPixmap(int(w * dpr), int(h * dpr))
            pm.setDevicePixelRatio(dpr)
            cq = QPainter(pm)
            self._paint_static(cq, w, h)
            cq.end()
            self._cache, self._cache_key = pm, key
        qp = QPainter(self)
        qp.drawPixmap(0, 0, self._cache)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont("Segoe UI", 9)
        qp.setFont(font)
        # the frame readout and the playhead: the only things that change while it plays
        qp.fillRect(QRectF(0, 0, HEAD_W, RULER_H), QColor("#110f18"))
        qp.setPen(QColor("#9a95b0"))
        n = len(self.multi)
        txt = f"frame {self.frame} / {self.length}  ·  {self.frame / 60:.2f} s" + (f"  ·  {n} selected" if n > 1 else "")
        if self.grab:
            txt = f"move: {'+' if self.grab['delta'] >= 0 else ''}{self.grab['delta']} frames (click / Enter, Esc)"
        qp.drawText(QRectF(10, 0, HEAD_W, RULER_H), Qt.AlignmentFlag.AlignVCenter, txt)
        x = self._x(self.frame)
        if x >= HEAD_W:
            qp.setPen(QPen(QColor("#e0457b"), 2))
            qp.drawLine(QPointF(x, 0), QPointF(x, h))
            qp.setBrush(QColor("#e0457b"))
            qp.drawPolygon(QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 9)]))
        qp.end()

    def _paint_static(self, qp, w, h):
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        qp.fillRect(0, 0, w, h, QColor("#17151f"))
        font = QFont("Segoe UI", 9)
        bold = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        qp.setFont(font)
        fm = QFontMetrics(font)
        # lines
        for k, ln in enumerate(self.lines):
            y = self._line_y(k)
            lh = self._line_h(ln)
            if y + lh < RULER_H or y > h:
                continue
            if ln[0] == "group":
                qp.fillRect(QRectF(HEAD_W, y, w, lh), QColor("#221f30"))
                for r in ln[3]:                                  # summary
                    for it in r.items:
                        x0, x1 = self._x(it.start), self._x(max(it.end, it.start + 1))
                        c = QColor(r.color)
                        c.setAlpha(130)
                        qp.fillRect(QRectF(x0, y + lh / 2 - 2, max(2.0, x1 - x0), 4), c)
                continue
            r = ln[1]
            qp.fillRect(QRectF(HEAD_W, y, w, lh), QColor("#1b1925" if k % 2 else "#1f1c2a"))
            if r.key in self.hidden_tracks:
                qp.fillRect(QRectF(HEAD_W, y, w, lh), QColor(0, 0, 0, 70))
            starts = sorted(it.start for it in r.items)
            for it in r.items:
                nxt = next((s for s in starts if s > it.start), None)
                room = (nxt - it.start) * self.ppf if nxt is not None else 999.0
                if it.kind not in ("clip", "motion", "bar") and any(
                        o is not it and (o.start == it.start or o.kind in ("clip", "motion") and
                                         o.start <= it.start < o.end) for o in r.items):
                    room = 0.0
                self._draw_item(qp, fm, y, it, room, faded=r.key in self.hidden_tracks)
        # snap / drop markers
        for f, col in ((self.drop_frame, "#3ecf8e"), (self.snap_frame, "#ffd166")):
            if f is not None:
                x = self._x(f)
                qp.setPen(QPen(QColor(col), 1.5, Qt.PenStyle.DashLine))
                qp.drawLine(QPointF(x, RULER_H), QPointF(x, h))
        if self.band:
            x0, y0, x1, y1 = self.band
            qp.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine))
            qp.setBrush(QColor(255, 255, 255, 25))
            qp.drawRect(QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)))
        # headers
        qp.fillRect(QRectF(0, RULER_H, HEAD_W, h), QColor("#211e2d"))
        for k, ln in enumerate(self.lines):
            y = self._line_y(k)
            lh = self._line_h(ln)
            if y + lh < RULER_H or y > h:
                continue
            if ln[0] == "group":
                qp.fillRect(QRectF(0, y, HEAD_W, lh), QColor("#2a2639"))
                qp.setFont(bold)
                qp.setPen(QColor("#f2eff9"))
                arrow = "▸" if ln[1] in self.collapsed else "▾"
                n = sum(len([i for i in r.items if i.kind in ("clip", "motion")]) or len(r.items) for r in ln[3])
                qp.drawText(QRectF(8, y, HEAD_W - 12, lh), Qt.AlignmentFlag.AlignVCenter,
                            f"{arrow}  {ln[2].split('  ', 1)[-1]}   ({len(ln[3])} track{'s' if len(ln[3]) != 1 else ''})")
                qp.setFont(font)
                continue
            r = ln[1]
            sel_row = any(self._is_selected(it) for it in r.items)
            if sel_row:
                qp.fillRect(QRectF(0, y, HEAD_W, lh), QColor("#2f2944"))
            qp.fillRect(QRectF(14, y + 5, 3, lh - 10), QColor(r.color))
            hovered = self.hover_line == k
            right = HEAD_W - (60 if hovered else 10)
            qp.setPen(QColor("#8e89a6") if r.key in self.hidden_tracks else QColor("#ece9f6"))
            qp.drawText(QRectF(24, y, right - 24, lh), Qt.AlignmentFlag.AlignVCenter,
                        fm.elidedText(r.title, Qt.TextElideMode.ElideRight, int(right - 26)))
            if hovered or r.key in self.hidden_tracks:
                eye, bin_ = self._header_buttons(y)
                if r.key[0] == "slot":
                    qp.setPen(QColor("#ffd166") if r.key in self.hidden_tracks else QColor("#c9c5da"))
                    qp.drawText(eye, Qt.AlignmentFlag.AlignCenter, "◌" if r.key in self.hidden_tracks else "👁")
                if hovered:
                    qp.setPen(QColor("#ff8a8a"))
                    qp.drawText(bin_, Qt.AlignmentFlag.AlignCenter, "🗑")
        qp.setPen(QPen(QColor("#2d2940")))
        qp.drawLine(HEAD_W, RULER_H, HEAD_W, h)
        # ruler
        qp.fillRect(QRectF(0, 0, w, RULER_H), QColor("#110f18"))
        step = 1
        for s in (1, 2, 5, 10, 15, 30, 60, 120, 300):
            if s * self.ppf >= 44:
                step = s
                break
        f = max(0, int(self._f(HEAD_W)) // step * step)
        while self._x(f) < w:
            x = self._x(f)
            if x >= HEAD_W:
                qp.setPen(QColor("#6f6a85"))
                qp.drawLine(QPointF(x, RULER_H - 8), QPointF(x, RULER_H))
                qp.drawText(QPointF(x + 3, RULER_H - 11), f"{f}" + (f"  {f / 60:.1f}s" if step >= 30 else ""))
            f += step
        end_x = self._x(self.length)
        qp.setPen(QPen(QColor("#6f6a85"), 1, Qt.PenStyle.DotLine))
        qp.drawLine(QPointF(end_x, RULER_H), QPointF(end_x, h))
        self._ruler_span(qp, fm)
        self._drag_readout(qp, fm)

    def _primary(self):
        s = self.sel
        if isinstance(s, tuple):
            return s[3]
        return s if isinstance(s, Item) else None

    def _ruler_span(self, qp, fm):
        """the selected item's start and end marked on the ruler, with their frames"""
        it = self._primary()
        if it is None:
            return
        s0, s1 = self._moved_span(it)
        x0, x1 = self._x(s0), self._x(max(s1, s0))
        if x1 < HEAD_W or x0 > self.width():
            return
        col = QColor(it.color)
        band = QColor(col)
        band.setAlpha(150)
        qp.fillRect(QRectF(max(HEAD_W, x0), RULER_H - 6, max(2.0, x1 - max(HEAD_W, x0)), 6), band)
        qp.setPen(QPen(QColor("#ffffff"), 1.5))
        for x in (x0, x1) if s1 > s0 else (x0,):
            if x >= HEAD_W:
                qp.drawLine(QPointF(x, RULER_H - 14), QPointF(x, RULER_H))
        f = qp.font()
        b = QFont(f)
        b.setBold(True)
        qp.setFont(b)
        if x0 >= HEAD_W:
            t = f"{s0}"
            qp.fillRect(QRectF(x0 - fm.horizontalAdvance(t) - 7, 1, fm.horizontalAdvance(t) + 6, 13), QColor("#110f18"))
            qp.drawText(QPointF(x0 - fm.horizontalAdvance(t) - 4, 12), t)
        if s1 > s0 and x1 >= HEAD_W:
            t = f"{s1}"
            qp.fillRect(QRectF(x1 + 1, 1, fm.horizontalAdvance(t) + 6, 13), QColor("#110f18"))
            qp.drawText(QPointF(x1 + 4, 12), t)
        qp.setFont(f)

    def _drag_readout(self, qp, fm):
        """while moving: where it was, where it goes"""
        d = self.drag
        it, txt = None, None
        if d and d.get("armed") and d["delta"]:
            it = d["target"] if isinstance(d["target"], Item) else (d["hit"][3] if isinstance(d["hit"], tuple)
                                                                     else None)
            n = len(d.get("items") or []) or 1
            what = f"{n} items" if n > 1 else (it.label if it is not None else "it")
            if d["mode"] == "end" and it is not None:
                txt = f"{what}: ends at frame {it.end} → {it.end + d['delta']}  ({it.end + d['delta'] - it.start} " \
                      f"frames on screen)"
            elif it is not None:
                txt = f"{what}: frame {it.start} → {it.start + d['delta']}  ({'+' if d['delta'] > 0 else ''}" \
                      f"{d['delta']}){'  · snapped' if self.snap_frame is not None else ''}   Esc: cancel"
        elif self.grab and self.grab["items"]:
            it = self.grab["items"][0]
            txt = f"move {len(self.grab['items'])} item(s) by {'+' if self.grab['delta'] >= 0 else ''}" \
                  f"{self.grab['delta']} frames   (click / Enter: done, Esc: cancel)"
        if not txt:
            return
        w = fm.horizontalAdvance(txt) + 16
        x = max(HEAD_W + 4, min(self.width() - w - 18, self._x(self._moved_span(it)[0]) if it else HEAD_W + 4))
        r = QRectF(x, RULER_H + 2, w, 20)
        qp.setPen(QPen(QColor("#ffd166"), 1))
        qp.setBrush(QColor(30, 26, 44, 235))
        qp.drawRoundedRect(r, 4, 4)
        qp.setPen(QColor("#ffd166"))
        qp.drawText(r.adjusted(8, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, txt)

    def _delta_for(self, it):
        if self.grab and any(it is m for m in self.grab["items"]):
            return self.grab["delta"]
        d = self.drag
        if d and d.get("mode") == "move" and d["delta"] and (d["target"] is it or (d.get("group") and
                                                                                   any(it is m for m in self.multi))):
            return d["delta"]
        return 0

    def _glyph(self, kind):
        g = self._glyphs.get(kind)
        if g is None:
            from .thumbs import glyph
            g = self._glyphs[kind] = glyph(KIND_GLYPH.get(kind, "•"), 18)
        return g

    def _icon(self, it):
        if self.icon_for is None or it.kind not in ("clip", "motion"):
            return None
        try:
            return self.icon_for(it)
        except Exception:
            return None

    def _moved_span(self, it):
        """(start, end) of an item as the current drag / grab shows it"""
        d = self._delta_for(it)
        s0, s1 = it.start + d, it.end + d
        if self.drag and self.drag.get("mode") == "end" and self.drag["target"] is it and self.drag.get("armed"):
            s1 = it.end + self.drag["delta"]
        return s0, s1

    def _draw_item(self, qp, fm, y, it, room=999.0, faded=False):
        rect = self._item_rect(y, it)
        sel = self._is_selected(it)
        d = self._delta_for(it)
        if d:                                             # the old place stays outlined while it moves
            qp.setPen(QPen(QColor(255, 255, 255, 110), 1, Qt.PenStyle.DashLine))
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.drawRoundedRect(rect, 5, 5)
        dx = d * self.ppf
        rect.translate(dx, 0)
        if self.drag and self.drag.get("mode") == "end" and self.drag["target"] is it and self.drag.get("armed"):
            rect.setRight(rect.right() + self.drag["delta"] * self.ppf)
        if rect.right() < HEAD_W or rect.left() > self.width():
            return
        col = QColor(it.color)
        if it.kind in ("clip", "motion", "bar") and it.end > it.start:
            fill = QColor(col)
            fill.setAlpha(80 if faded else (225 if sel else (170 if it.kind != "bar" else 115)))
            if sel:
                fill = fill.lighter(118)
            qp.setPen(QPen(QColor("#ffffff") if sel else col.darker(150), 2 if sel else 1))
            qp.setBrush(fill)
            qp.drawRoundedRect(rect, 5, 5)
            if it.thin:
                return
            # where it starts and where it ends: bright caps on both edges
            cap = QColor(255, 255, 255, 235 if sel else 140)
            qp.fillRect(QRectF(rect.left() + 1, rect.top() + 2, 3, rect.height() - 4), cap)
            qp.fillRect(QRectF(rect.right() - 4, rect.top() + 2, 3, rect.height() - 4), cap)
            if it.removable_end and sel:                 # a grip: the end can be dragged
                qp.setPen(QPen(QColor(255, 255, 255, 200), 1))
                for gx in (rect.right() - 8, rect.right() - 10.5):
                    qp.drawLine(QPointF(gx, rect.center().y() - 4), QPointF(gx, rect.center().y() + 4))
            if it.moves:
                qp.setPen(QPen(QColor(255, 255, 255, 110), 1, Qt.PenStyle.DotLine))
                qp.drawLine(QPointF(rect.left() + 6, rect.bottom() - 3), QPointF(rect.right() - 6, rect.bottom() - 3))
            tx = rect.left() + 8
            pm = self._icon(it) if rect.width() >= 64 else None
            if pm is not None and not pm.isNull():
                sz = rect.height() - 4
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(QColor(15, 13, 22, 200))
                qp.drawRoundedRect(QRectF(rect.left() + 5, rect.top() + 2, sz, sz), 3, 3)
                qp.drawPixmap(QRectF(rect.left() + 5, rect.top() + 2, sz, sz), pm, QRectF(pm.rect()))
                tx += sz + 2
            qp.setPen(QColor("#ffffff"))
            avail = int(rect.right() - 8 - tx)
            if avail > 14:
                qp.drawText(QRectF(tx, rect.top(), avail, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                            fm.elidedText(it.label, Qt.TextElideMode.ElideRight, avail))
            if sel and it.keys:                          # what happens inside it: small marks at the bottom
                for f, o in it.keys:
                    kx = self._x(f) + dx
                    if not (rect.left() + 2 <= kx <= rect.right() - 2):
                        continue
                    ksel = isinstance(self.sel, tuple) and self.sel[2] is o
                    if self.drag and self.drag.get("armed") and self.drag["target"] is o:
                        kx += self.drag["delta"] * self.ppf          # Alt-dragging this one command
                    qp.setPen(QPen(QColor("#ffffff" if ksel else "#ffd6e6"), 2 if ksel else 1.2))
                    qp.drawLine(QPointF(kx, rect.bottom() - 7), QPointF(kx, rect.bottom() - 1))
        else:
            # one moment: a mark exactly at its frame and a chip with what it does
            x = self._x(it.start) + dx
            qp.setPen(QPen(col if not sel else QColor("#ffffff"), 1.5))
            qp.drawLine(QPointF(x, y + 4), QPointF(x, y + ROW_H - 4))
            self._diamond(qp, x, y + ROW_H / 2, 5, QColor("#ffffff") if sel else col)
            if room > 44:
                txt = fm.elidedText(it.label, Qt.TextElideMode.ElideRight, int(min(room, 200)) - 20)
                w = fm.horizontalAdvance(txt) + 12
                chip = QRectF(x + 8, y + 6, w, ROW_H - 12)
                c = QColor(col)
                c.setAlpha(70 if not sel else 140)
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(c)
                qp.drawRoundedRect(chip, 4, 4)
                qp.setPen(QColor("#ffffff") if sel else QColor("#d9d5e8"))
                qp.drawText(chip.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, txt)

    @staticmethod
    def _diamond(qp, x, y, r, col):
        qp.setPen(QPen(col.darker(160), 1))
        qp.setBrush(col)
        qp.drawPolygon(QPolygonF([QPointF(x, y - r), QPointF(x + r, y), QPointF(x, y + r), QPointF(x - r, y)]))

    # ---------------------------------------------------------------- snapping
    def _snap(self, frame, exclude, alt):
        """nearest snap frame (playhead, other items' starts / ends) within SNAP_PX, or None"""
        if alt:
            return None
        cands = [self.frame]
        ex = {id(i) for i in exclude}
        for r in self.rows:
            for it in r.items:
                if id(it) in ex:
                    continue
                cands += [it.start, it.end]
        best = None
        for c in cands:
            if abs(c - frame) * self.ppf <= SNAP_PX and (best is None or abs(c - frame) < abs(best - frame)):
                best = c
        return best

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        mods = e.modifiers()
        add = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        if self.grab:                                   # G: a click ends it
            if e.button() == Qt.MouseButton.LeftButton:
                self._grab_done()
            else:
                self._grab_cancel()
            return
        if pos.y() < RULER_H and pos.x() >= HEAD_W:
            self.scrubbing = True
            self.frameChanged.emit(max(0, round(self._f(pos.x()))))
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if pos.x() < HEAD_W:
            k = self._line_at(pos.y())
            if k is None:
                return
            ln = self.lines[k]
            if ln[0] == "group":
                (self.collapsed.discard if ln[1] in self.collapsed else self.collapsed.add)(ln[1])
                self._layout()
                self._scrollbars()
                self.update()
                return
            r = ln[1]
            eye, bin_ = self._header_buttons(self._line_y(k))
            if bin_.contains(pos):
                self.trackDeleteRequested.emit(r)
                return
            if eye.contains(pos) and r.key[0] == "slot":
                self.toggle_hidden(r)
                return
            items = [it for it in r.items if it.kind == "clip"] or list(r.items)
            if add:
                items = self.multi + [it for it in items if not any(it is m for m in self.multi)]
            self._set_selection(items, items[0] if items else None)
            return
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        hit, k, part = self._hit(e.position().toPoint(), keys=alt)
        if hit is None:
            self.press = dict(x=pos.x(), y=pos.y(), mods=mods, base=list(self.multi))
            return
        if isinstance(hit, tuple):                     # Alt: one command inside a clip
            self._set_selection([], hit)
            self.drag = dict(mode="move", x=pos.x(), target=hit[2], hit=hit, delta=0, group=False, items=[],
                             armed=False)
            return
        mark = self._hit(e.position().toPoint(), keys=True)[0]      # a click (no drag) on a mark selects it
        mark = mark if isinstance(mark, tuple) and mark[3] is hit and self._is_selected(hit) else None
        if part == "end":
            self._set_selection([hit], hit)
            self.drag = dict(mode="end", x=pos.x(), target=hit, hit=hit, delta=0, items=[hit], armed=False)
            return
        if add:
            if any(hit is m for m in self.multi):
                rest = [m for m in self.multi if m is not hit]
                self._set_selection(rest, rest[0] if rest else None)
            else:
                self._set_selection(self.multi + [hit], hit)
            return
        if any(hit is m for m in self.multi) and len(self.multi) > 1:
            self.sel = hit
            self.selected.emit(hit)
            self.drag = dict(mode="move", x=pos.x(), target=hit, hit=list(self.multi), delta=0, group=True,
                             items=list(self.multi), armed=False, mark=mark)
            self.update()
            return
        if not (self.sel is hit and len(self.multi) <= 1):
            self._set_selection([hit], hit)
        self.drag = dict(mode="move", x=pos.x(), target=hit, hit=hit, delta=0, group=False, items=[hit],
                         armed=False, mark=mark)

    def mouseMoveEvent(self, e):
        pos = e.position()
        alt = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
        if self.grab:
            d = round((pos.x() - self.grab["x"]) / self.ppf)
            if self.grab["items"]:
                s0 = min(i.start for i in self.grab["items"])
                sn = self._snap(s0 + d, self.grab["items"], alt)
                if sn is not None:
                    d = sn - s0
                self.snap_frame = sn
            self.grab["delta"] = d
            self.update()
            return
        if self.scrubbing:
            self.frameChanged.emit(max(0, round(self._f(pos.x()))))
            return
        if self.press is not None:
            if self.band is None and (abs(pos.x() - self.press["x"]) > 4 or abs(pos.y() - self.press["y"]) > 4):
                self.band = [self.press["x"], self.press["y"], pos.x(), pos.y()]
            if self.band is not None:
                self.band[2], self.band[3] = pos.x(), pos.y()
                self._band_select()
            return
        if self.drag:
            if not self.drag.get("armed"):
                if abs(pos.x() - self.drag["x"]) < DRAG_PX:   # a click, not a move (yet)
                    return
                self.drag["armed"] = True
            d = round((pos.x() - self.drag["x"]) / self.ppf)
            tgt = self.drag["target"]
            if self.drag["mode"] == "end":
                sn = self._snap(tgt.end + d, [tgt], alt)
                if sn is not None:
                    d = sn - tgt.end
                d = max(d, tgt.start + 1 - tgt.end)
            elif self.drag.get("items"):
                s0 = min(i.start for i in self.drag["items"])
                sn = self._snap(s0 + d, self.drag["items"], alt)
                if sn is not None:
                    d = sn - s0
            else:
                sn = None
            self.snap_frame = sn if self.drag["mode"] in ("move", "end") else None
            if d != self.drag["delta"]:
                self.drag["delta"] = d
                self.update()
            return
        k = self._line_at(pos.y())
        line = k if (k is not None and pos.x() < HEAD_W and self.lines[k][0] == "row") else None
        if line != self.hover_line:
            self.hover_line = line
            self.update()
        hit, k, part = self._hit(pos.toPoint(), keys=True)
        if isinstance(hit, tuple):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(_tip(hit[2]) + "<br><i>click: its values · Alt+drag: move just this command</i>")
            return
        self.setCursor(Qt.CursorShape.SizeHorCursor if part == "end" else
                       (Qt.CursorShape.OpenHandCursor if hit is not None else Qt.CursorShape.ArrowCursor))
        if hit is not None:
            tip = hit.tip
            if part == "end":
                tip = "drag to change when it ends"
            elif hit.end > hit.start:
                tip = (tip or hit.label) + f"<br><i>frames {hit.start}–{hit.end} ({(hit.end - hit.start) / 60:.2f} s)" \
                                           f" · drag: move it in time</i>"
            self.setToolTip(tip)
        elif line is not None:
            r = self.lines[line][1]
            self.setToolTip((r.tip or r.title) + "<br><i>click: select its clips · 👁 hide in the preview · "
                                                  "🗑 delete the track</i>")
        else:
            self.setToolTip("")

    def leaveEvent(self, e):
        if self.hover_line is not None:
            self.hover_line = None
            self.update()

    def _band_select(self):
        x0, y0, x1, y1 = self.band
        f0, f1 = sorted((self._f(x0), self._f(x1)))
        ya, yb = sorted((y0, y1))
        sub = bool(self.press["mods"] & Qt.KeyboardModifier.ControlModifier)
        add = bool(self.press["mods"] & Qt.KeyboardModifier.ShiftModifier)
        inside = []
        for k, ln in enumerate(self.lines):
            if ln[0] != "row":
                continue
            y = self._line_y(k)
            if y + ROW_H < ya or y > yb:
                continue
            for it in ln[1].items:
                if (it.kind in ("clip", "bar", "motion") and it.end > f0 and it.start < f1) or \
                        (it.kind == "key" and f0 <= it.start <= f1):
                    inside.append(it)
        base = self.press["base"]
        if sub:
            found = [m for m in base if not any(m is i for i in inside)]
        elif add:
            found = base + [i for i in inside if not any(i is m for m in base)]
        else:
            found = inside
        self.multi = found
        self.sel = found[0] if found else None
        self.update()

    def mouseReleaseEvent(self, e):
        self.scrubbing = False
        self.snap_frame = None
        if self.press is not None:
            p = self.press
            self.press = None
            if self.band is not None:
                self.band = None
                self._set_selection(self.multi, self.sel)
            else:                                   # a click on empty space
                if not (p["mods"] & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)):
                    if self.multi or self.sel is not None:
                        self._set_selection([], None)
                    self.frameChanged.emit(max(0, round(self._f(p["x"]))))
            self.update()
            return
        if self.drag:
            d, hit, mode = self.drag["delta"], self.drag["hit"], self.drag["mode"]
            armed, mark = self.drag.get("armed"), self.drag.get("mark")
            self.drag = None
            self.update()
            if not armed:
                if mark is not None:                    # a click on a mark inside the clip: show that command
                    self._set_selection([], mark)
                return
            if d:
                if mode == "end":
                    self.trimRequested.emit(hit, d)
                else:
                    self.moveRequested.emit(hit, d)

    def mouseDoubleClickEvent(self, e):
        hit, k, part = self._hit(e.position().toPoint())
        if hit is None and k is not None and e.position().x() >= HEAD_W and self.lines[k][0] == "row":
            self._menu(e.globalPosition().toPoint(), round(self._f(e.position().x())), self.lines[k][1].key)

    def contextMenuEvent(self, e):
        k = self._line_at(e.pos().y())
        if e.pos().x() < HEAD_W and k is not None and self.lines[k][0] == "row":
            return self._track_menu(e.globalPos(), self.lines[k][1])
        hit, k, part = self._hit(e.pos())
        if hit is not None and not (isinstance(hit, Item) and any(hit is m for m in self.multi)):
            self._set_selection([hit] if isinstance(hit, Item) else [], hit)
        row = self.lines[k][1].key if k is not None and self.lines[k][0] == "row" else None
        self._menu(e.globalPos(), max(0, round(self._f(e.pos().x()))), row, hit)

    def toggle_hidden(self, r):
        hide = r.key not in self.hidden_tracks
        (self.hidden_tracks.add if hide else self.hidden_tracks.discard)(r.key)
        self.trackHideToggled.emit(r, hide)
        self.update()

    def _track_menu(self, gpos, r):
        m = QMenu(self)
        m.addAction("☰  Select everything in this track", lambda: self._set_selection(
            list(r.items), r.items[0] if r.items else None))
        if r.key[0] == "slot":
            m.addAction("◌  Show in the preview" if r.key in self.hidden_tracks else "👁  Hide in the preview",
                        lambda: self.toggle_hidden(r))
        m.addSeparator()
        m.addAction("🗑  Delete this track (everything in it)", lambda: self.trackDeleteRequested.emit(r))
        m.exec(gpos)

    def _menu(self, gpos, frame, row, hit=None):
        m = QMenu(self)
        if hit is not None:
            target = list(self.multi) if len(self.multi) > 1 and isinstance(hit, Item) else hit
            n = len(target) if isinstance(target, list) else 1
            items = target if isinstance(target, list) else ([target] if isinstance(target, Item) else [])
            m.addAction(f"🗑  Delete{f' {n} items' if n > 1 else ''}\tDel", lambda: self.deleteRequested.emit(target))
            if items and all(i.kind == "clip" for i in items):
                m.addAction(f"⧉  Duplicate{f' {n}' if n > 1 else ''}\tShift+D",
                            lambda: self.duplicateRequested.emit(items, 0))
                m.addAction("📋  Copy\tCtrl+C", lambda: self.copyRequested.emit(items))
            m.addAction("⇤  Move to the playhead", lambda: self.moveRequested.emit(
                target, self.frame - (hit[1] if isinstance(hit, tuple) else hit.start)))
            if isinstance(hit, Item) and hit.kind == "clip":
                m.addAction("🔁  Select all with this effect", self.select_similar)
                m.addAction("☰  Select the whole tracks", self.select_rows_of_selection)
            m.addSeparator()
        m.addAction(f"📋  Paste at frame {self.frame}\tCtrl+V", lambda: self.pasteRequested.emit(self.frame))
        m.addAction(f"✨  Add effect at frame {frame}…", lambda: self.addRequested.emit("effect", frame, row))
        m.addAction("🎥  Add camera move", lambda: self.addRequested.emit("camera", frame, row))
        m.addAction("📳  Add camera shake", lambda: self.addRequested.emit("shake", frame, row))
        m.addAction("🏃  Add pose…", lambda: self.addRequested.emit("motion", frame, row))
        m.addAction("💡  Add flash (tint)", lambda: self.addRequested.emit("flash", frame, row))
        m.addAction("🔊  Add sound…", lambda: self.addRequested.emit("sound", frame, row))
        m.addAction("🌑  Add screen fade", lambda: self.addRequested.emit("fade", frame, row))
        from d5lib import presets
        pm = m.addMenu("🧩  Add preset")
        for g in presets.GROUP_ORDER:
            sub = pm.addMenu(g)
            for pr in presets.PRESETS:
                if pr.group == g:
                    a = sub.addAction(pr.name, lambda k=pr.key: self.addRequested.emit(f"preset:{k}", frame, row))
                    a.setToolTip(pr.desc)
            sub.setToolTipsVisible(True)
        m.exec(gpos)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            f = self._f(e.position().x())
            self.ppf = max(0.5, min(40.0, self.ppf * (1.2 if dy > 0 else 1 / 1.2)))
            self.xoff = max(0.0, f * self.ppf - (e.position().x() - HEAD_W))
        elif e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.xoff = max(0.0, self.xoff - dy)
        else:
            self.yoff = max(0, min(self.vscroll.maximum(), self.yoff - dy // 2))
            self.vscroll.setValue(self.yoff)
        self._scrollbars()
        self.update()

    # ---------------------------------------------------------------- keys
    def _grab_done(self):
        g, self.grab = self.grab, None
        self.snap_frame = None
        self.update()
        if g and g["delta"] and g["items"]:
            self.moveRequested.emit(list(g["items"]) if len(g["items"]) > 1 else g["items"][0], g["delta"])

    def _grab_cancel(self):
        self.grab = None
        self.snap_frame = None
        self.update()

    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        ctrl = mods & Qt.KeyboardModifier.ControlModifier
        shift = mods & Qt.KeyboardModifier.ShiftModifier
        alt = mods & Qt.KeyboardModifier.AltModifier
        if self.grab:
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._grab_done()
            elif k == Qt.Key.Key_Escape:
                self._grab_cancel()
            return
        if self.drag and k == Qt.Key.Key_Escape:            # cancel a drag: everything stays where it was
            self.drag = None
            self.snap_frame = None
            self.update()
            return
        sel_items = [m for m in self.multi if isinstance(m, Item)]
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace, Qt.Key.Key_X) and not ctrl and (self.multi or self.sel):
            self.deleteRequested.emit(list(self.multi) if len(self.multi) > 1 else self.sel)
        elif k == Qt.Key.Key_D and (shift or ctrl) and sel_items:
            self.duplicateRequested.emit(sel_items, 0)
        elif k == Qt.Key.Key_C and ctrl and sel_items:
            self.copyRequested.emit(sel_items)
        elif k == Qt.Key.Key_V and ctrl:
            self.pasteRequested.emit(self.frame)
        elif k == Qt.Key.Key_A and alt:
            self.clear_selection()
        elif k == Qt.Key.Key_A:
            items = [it for r in self.rows for it in r.items if it.kind == "clip"] or self._all_items()
            self._set_selection(items, items[0] if items else None)
        elif k == Qt.Key.Key_I and ctrl:
            items = [it for it in self._all_items() if not any(it is m for m in self.multi)]
            self._set_selection(items, items[0] if items else None)
        elif k in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            before = k == Qt.Key.Key_BracketLeft
            items = [it for it in self._all_items() if (it.start <= self.frame if before else it.start >= self.frame)]
            self._set_selection(items, items[0] if items else None)
        elif k == Qt.Key.Key_G and sel_items:
            self.grab = dict(x=self.mapFromGlobal(QCursor.pos()).x(), delta=0, items=sel_items)
            self.update()
        elif k == Qt.Key.Key_Escape:
            self.clear_selection()
        elif k == Qt.Key.Key_F:
            self.fit()
        elif k == Qt.Key.Key_Left:
            self.frameChanged.emit(max(0, self.frame - (10 if shift else 1)))
        elif k == Qt.Key.Key_Right:
            self.frameChanged.emit(self.frame + (10 if shift else 1))
        elif k == Qt.Key.Key_Home:
            self.frameChanged.emit(0)
        elif k == Qt.Key.Key_End:
            self.frameChanged.emit(self.length)
        else:
            super().keyPressEvent(e)

    # ---------------------------------------------------------------- drops from the effect library
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            self.drop_frame = max(0, round(self._f(e.position().x())))
            e.acceptProposedAction()
            self.update()

    def dragLeaveEvent(self, e):
        self.drop_frame = None
        self.update()

    def dropEvent(self, e):
        self.drop_frame = None
        if not e.mimeData().hasFormat(MIME):
            return
        eid = int(bytes(e.mimeData().data(MIME)).decode())
        k = self._line_at(e.position().y())
        row = self.lines[k][1].key if k is not None and self.lines[k][0] == "row" else None
        self.effectDropped.emit(eid, max(0, round(self._f(e.position().x()))), row)
        e.acceptProposedAction()
        self.update()


def _ident(op):
    return op.ident
