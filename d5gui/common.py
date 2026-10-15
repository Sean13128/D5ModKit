"""Reusable widgets & helpers for the D5 Mod Kit GUI."""
import traceback

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF, QSize, QObject, QEvent, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QBrush, QWheelEvent
from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QGraphicsView,
                             QGraphicsScene, QMessageBox, QPushButton, QSizePolicy, QLineEdit, QApplication,
                             QAbstractSpinBox, QComboBox, QAbstractSlider, QScrollBar, QAbstractScrollArea)

LANGS = ["JP", "EN", "FR", "CHN", "KOR"]


def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    q = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return q.copy()


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(img))


def qimage_to_pil(q: QImage) -> Image.Image:
    q = q.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = q.constBits()
    ptr.setsize(q.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(q.height(), q.bytesPerLine())[:, :q.width() * 4]
    return Image.fromarray(arr.reshape(q.height(), q.width(), 4).copy(), "RGBA")


def checker_brush(size=8):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(QColor(60, 60, 66))
    p = QPainter(pm)
    p.fillRect(0, 0, size, size, QColor(80, 80, 88))
    p.fillRect(size, size, size, size, QColor(80, 80, 88))
    p.end()
    return QBrush(pm)


def error_box(parent, title, exc):
    tb = traceback.format_exc()
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(f"{title}\n\n{exc}")
    box.setDetailedText(tb)
    box.exec()


def info_box(parent, title, text):
    QMessageBox.information(parent, title, text)


class ImageView(QGraphicsView):
    """Zoomable, pannable image viewer with a checkerboard background for transparency."""
    clicked = pyqtSignal(int, int)  # image pixel coords

    def __init__(self, parent=None, smooth=False):
        """smooth: zoomed pictures are filtered like the game draws its sprites (character / outfit previews);
        off: hard pixels, for pixel work (sheets, textures, parts)"""
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = None
        self.smooth = smooth
        self.setBackgroundBrush(checker_brush())
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        self.setMinimumSize(200, 200)
        self._zoom = 1.0

    def set_image(self, img, fit=False):
        self._scene.clear()
        self._item = None
        if img is None:
            return
        pm = img if isinstance(img, QPixmap) else pil_to_pixmap(img)
        self._item = self._scene.addPixmap(pm)
        if self.smooth:
            self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.setSceneRect(QRectF(pm.rect()))
        if fit:
            self.fit()

    def fit(self):
        if self._item:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()

    def set_zoom(self, z):
        self.resetTransform()
        self.scale(z, z)
        self._zoom = z

    def wheelEvent(self, e: QWheelEvent):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self._zoom *= f
        self.scale(f, f)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self._item and e.button() == Qt.MouseButton.LeftButton:
            p = self.mapToScene(e.position().toPoint())
            self.clicked.emit(int(p.x()), int(p.y()))


class Refresher(QObject):
    """A page refresh that runs once after the current event, and only while the page shows: a hidden page refreshes
    when it is shown next.  Pages listen to several signals that fire together (a mod made or deleted: mods_changed,
    every table's table_changed, file_changed); refreshing every page at once froze the editor for about a second.
    Call it (any arguments are ignored); `done()` from the refresh itself clears a pending call."""

    def __init__(self, widget, fn):
        super().__init__(widget)
        self.w, self.fn = widget, fn
        self.pending = self.queued = False
        widget.installEventFilter(self)

    def __call__(self, *_):
        self.pending = True
        self._queue()

    def done(self):
        self.pending = False

    def _queue(self):
        if self.pending and not self.queued and self.w.isVisible():
            from PyQt6.QtCore import QTimer
            self.queued = True
            QTimer.singleShot(0, self._run)

    def _run(self):
        self.queued = False
        if self.pending and self.w.isVisible():
            self.pending = False
            self.fn()

    def eventFilter(self, obj, e):
        if obj is self.w and e.type() == QEvent.Type.Show:
            self._queue()
        return False


class Worker(QThread):
    """Run a function in a background thread; emits done(result) or failed(exc_text)."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    alive = set()           # running workers: kept referenced, and waited for when the kit closes (wait_all)

    def __init__(self, fn, *args, **kw):
        super().__init__()
        self.fn, self.args, self.kw = fn, args, kw
        self.finished.connect(lambda: Worker.alive.discard(self))

    def start(self, *a):
        Worker.alive.add(self)
        super().start(*a)

    @staticmethod
    def wait_all(ms=8000):
        """at exit: a QThread destroyed while it runs aborts the program"""
        for w in list(Worker.alive):
            w.wait(ms)

    def run(self):
        try:
            self.done.emit(self.fn(*self.args, **self.kw))
        except Exception as e:  # noqa
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class Card(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        if title:
            t = QLabel(title)
            t.setObjectName("cardTitle")
            self.lay.addWidget(t)


class PageHeader(QWidget):
    """Page title with its explanation beside it (one line where it fits: more room for the editor)."""

    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(14)
        t = QLabel(title)
        t.setObjectName("pageTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(t, 0)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("pageSubtitle")
            s.setWordWrap(True)
            s.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(s, 1)


class Banner(QLabel):
    """One-line notice above an editor (where edits go, what to do next)."""

    def __init__(self, text="", warn=False, parent=None):
        super().__init__(text, parent)
        self.setObjectName("bannerWarn" if warn else "banner")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)

    def show_text(self, text, warn=False):
        self.setObjectName("bannerWarn" if warn else "banner")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText(text)
        self.setVisible(bool(text))


class SearchBox(QLineEdit):
    def __init__(self, placeholder="Search...", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)


class ResponsiveGrid(QWidget):
    """Cells (widgets) in as many equal columns as fit (each at least `min_cell` px, at most `max_cols`): a form
    that reflows into more rows in a narrow window instead of being squeezed and cut off."""

    def __init__(self, min_cell=110, max_cols=8, spacing=8, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QGridLayout, QLayout
        self.min_cell, self.max_cols, self.cols, self.cells = min_cell, max_cols, 0, []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(spacing)
        self.grid.setVerticalSpacing(spacing)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumWidth(min_cell)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def add(self, w):
        self.cells.append(w)
        self._place(force=True)
        return w

    def add_cell(self, *items, tip=None):
        """a cell of widgets stacked top to bottom (a label text first: a caption) -> the cell"""
        cell = QWidget()
        v = QVBoxLayout(cell)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        for it in items:
            if isinstance(it, str):
                lab = QLabel(it)
                lab.setObjectName("fieldLabel")
                if tip:
                    lab.setToolTip(tip)
                v.addWidget(lab)
            elif isinstance(it, QWidget):
                v.addWidget(it)
            else:
                v.addLayout(it)
        return self.add(cell)

    def _columns(self, width):
        return max(1, min(self.max_cols, len(self.cells) or 1, int(width + self.grid.horizontalSpacing())
                          // (self.min_cell + self.grid.horizontalSpacing())))

    def _place(self, force=False):
        cols = self._columns(self.width() if self.width() > 0 else self.min_cell * self.max_cols)
        if cols == self.cols and not force:
            return
        self.cols = cols
        for w in self.cells:
            self.grid.removeWidget(w)
        for i, w in enumerate(self.cells):
            self.grid.addWidget(w, i // cols, i % cols)
        for c in range(self.max_cols):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        # (scroll areas don't ask a widget its height for a width: the rows' height is set as the minimum)
        self.setMinimumHeight(self._height(cols))
        self.updateGeometry()

    def _height(self, cols):
        rows = (len(self.cells) + cols - 1) // cols
        if not rows:
            return 0
        heights = [max(c.sizeHint().height(), c.minimumSizeHint().height()) for c in self.cells]
        per_row = [max(heights[r * cols:(r + 1) * cols]) for r in range(rows)]
        return sum(per_row) + self.grid.verticalSpacing() * (rows - 1)

    def _refit(self):
        h = self._height(max(1, self.cols))
        if h != self.minimumHeight():
            self.setMinimumHeight(h)
            self.updateGeometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()
        self._refit()

    def showEvent(self, e):
        super().showEvent(e)
        self._refit()                        # (the style sheet can change the cells' height once shown)

    def sizeHint(self):
        return QSize(self.min_cell * min(self.max_cols, max(1, len(self.cells))), self.minimumHeight())

    def minimumSizeHint(self):
        return QSize(self.min_cell, self.minimumHeight())


class _TypeToSearch(QObject):
    """The text box of a searchable drop-down: clicking (or tabbing) into it selects the whole entry, so what is typed
    replaces it and the list shows every entry containing the words (a click put the cursor inside the shown name:
    'star' typed into 'Mega Fire' searched for 'Mega starFire' and found nothing).  A search left unfinished shows
    the chosen entry again when the box is left (restore(combo))."""

    def __init__(self, combo, restore=None):
        super().__init__(combo)
        self.combo, self.restore, self.armed = combo, restore, False
        combo.installEventFilter(self)                # (the focus goes to the drop-down, which hands it on)
        combo.lineEdit().installEventFilter(self)

    WATCHED = (QEvent.Type.FocusIn, QEvent.Type.MouseButtonRelease, QEvent.Type.FocusOut)

    def eventFilter(self, obj, ev):
        # The drop-down's events only: while a QComboBox is destroyed it still sends its filters an event (its list
        # deleted: ChildRemoved) when its Python side is already gone -- touching self.combo then raised, and an
        # error in a Qt callback closed the whole kit (1.5: deleting any searchable drop-down, e.g. closing a
        # dialog or the kit, crashed it).
        t = ev.type()
        if t not in self.WATCHED:
            return False
        try:
            edit = self.combo.lineEdit()
            if edit is None:
                return False
            if t == QEvent.Type.FocusIn and ev.reason() not in (Qt.FocusReason.PopupFocusReason,
                                                                Qt.FocusReason.ActiveWindowFocusReason):
                self.armed = True
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._select_all)
            elif t == QEvent.Type.MouseButtonRelease and obj is edit and self.armed:
                self.armed = False
                edit.selectAll()
            elif t == QEvent.Type.FocusOut:
                self.armed = False
        except RuntimeError:                          # (the drop-down is being deleted)
            pass
        return False

    def _select_all(self):
        try:
            self.combo.lineEdit().selectAll()
        except (RuntimeError, AttributeError):        # (gone, or no longer editable)
            pass


def _search_owner(w):
    while w is not None:
        if getattr(w, "_d5_search", None) is not None:
            return w
        w = w.parentWidget()
    return None


def _focus_moved(old, new):
    """the focus left a searchable drop-down (its list of matches holds it for a moment, so the drop-down's own
    focus-out comes too early or not at all): a search left unfinished shows the chosen entry again"""
    try:                                              # (the focus also moves when a widget is being deleted)
        combo = _search_owner(old)
        if combo is None or combo is _search_owner(new) or combo._d5_search.restore is None:
            return
    except RuntimeError:
        return
    from PyQt6.QtCore import QTimer

    def later():
        try:
            if combo.hasFocus() or combo.lineEdit().hasFocus():
                return
            if combo.completer() is not None:
                combo.completer().popup().hide()
            combo._d5_search.restore(combo)
        except RuntimeError:                          # (the drop-down is gone)
            pass
    QTimer.singleShot(0, later)


def type_to_search(combo, restore=None):
    """make an editable QComboBox searchable by typing (see _TypeToSearch)"""
    app = QApplication.instance()
    if app is not None and not getattr(app, "_d5_search_focus", False):
        app._d5_search_focus = True
        app.focusChanged.connect(_focus_moved)
    combo.lineEdit().setPlaceholderText("type to search…")
    combo._d5_search = _TypeToSearch(combo, restore)
    return combo


def human_size(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class WheelGuard(QObject):
    """App-wide: number boxes, drop-downs and sliders take the mouse wheel only after they were clicked (have the
    focus).  Scrolling a page over them scrolls the page instead of changing their values."""
    TYPES = (QAbstractSpinBox, QComboBox, QAbstractSlider)

    def _guarded(self, obj):
        return isinstance(obj, self.TYPES) and not isinstance(obj, QScrollBar)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Polish and self._guarded(obj):
            # the default (wheel focus) would give them the focus -- and the wheel -- just by scrolling over them
            if obj.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        elif t == QEvent.Type.Wheel and self._guarded(obj) and not obj.hasFocus():
            p = obj.parentWidget()
            while p is not None and not isinstance(p, QAbstractScrollArea):
                p = p.parentWidget()
            if p is not None:                      # scroll the page / panel under the mouse instead
                target = p.viewport()
                pos = obj.mapTo(target, ev.position().toPoint())
                from PyQt6.QtGui import QWheelEvent
                fwd = QWheelEvent(QPointF(pos), ev.globalPosition(), ev.pixelDelta(), ev.angleDelta(),
                                  ev.buttons(), ev.modifiers(), ev.phase(), ev.inverted())
                QApplication.sendEvent(target, fwd)
            return True
        return False


def install_wheel_guard():
    app = QApplication.instance()
    if app is not None and not getattr(app, "_d5_wheel_guard", None):
        app._d5_wheel_guard = WheelGuard(app)
        app.installEventFilter(app._d5_wheel_guard)
