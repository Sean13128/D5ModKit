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
