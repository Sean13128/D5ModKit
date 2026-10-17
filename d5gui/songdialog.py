"""Your song as a game track: pick the file, set where its loop starts and ends on the waveform, listen to the
join, and the kit cuts it into the intro (played once) and the loop part (played over and over) and converts both to
the game's format (d5lib.audiotools)."""
import os
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from d5lib import audiotools

FILTER = "Audio (*.wav *.flac *.ogg *.mp3 *.m4a *.aif *.aiff);;All files (*)"


class Waveform(QWidget):
    """the song's waveform with the loop start (green) and end (red) markers; drag them, click to set where ▶
    starts"""
    moved = pyqtSignal(float, float)       # loop start, loop end (seconds)
    clicked = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        self.length = 0.0
        self.peaks = None
        self.a, self.b, self.head = 0.0, 0.0, None
        self._drag = None

    def set_audio(self, pcm, rate):
        self.length = len(pcm) / float(rate) if rate else 0.0
        self._pcm, self._rate = pcm, rate
        self.peaks = None
        self.update()

    def set_markers(self, a, b):
        self.a, self.b = a, b
        self.update()

    def _x(self, t):
        return 0 if self.length <= 0 else t / self.length * (self.width() - 1)

    def _t(self, x):
        return max(0.0, min(self.length, x / max(1, self.width() - 1) * self.length))

    def paintEvent(self, e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(20, 18, 34))
        if self.length <= 0:
            p.setPen(QColor(150, 150, 170))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Pick a song file")
            return
        if self.peaks is None or len(self.peaks[0]) != w:
            self.peaks = audiotools.peaks(self._pcm, w)
        lo, hi = self.peaks
        mid = h / 2
        xa, xb = self._x(self.a), self._x(self.b)
        p.fillRect(QRectF(xa, 0, max(1, xb - xa), h), QColor(63, 208, 255, 40))
        pts = [QPointF(x, mid - hi[x] * mid * 0.95) for x in range(w)] + \
              [QPointF(x, mid - lo[x] * mid * 0.95) for x in range(w - 1, -1, -1)]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 79, 139, 200))
        p.drawPolygon(QPolygonF(pts))
        for x, col, label in ((xa, QColor("#3ecf8e"), "loop start"), (xb, QColor("#ff6b6b"), "loop end")):
            p.setPen(QPen(col, 2))
            p.drawLine(int(x), 0, int(x), h)
            p.drawText(int(x) + 4, 14, label)
        if self.head is not None:
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.drawLine(int(self._x(self.head)), 0, int(self._x(self.head)), h)

    def mousePressEvent(self, e):
        if self.length <= 0:
            return
        x = e.position().x()
        da, db = abs(x - self._x(self.a)), abs(x - self._x(self.b))
        if min(da, db) < 8:
            self._drag = "a" if da <= db else "b"
        else:
            self.clicked.emit(self._t(x))

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag:
            t = self._t(x)
            if self._drag == "a":
                self.a = min(t, self.b - 0.05)
            else:
                self.b = max(t, self.a + 0.05)
            self.update()
            self.moved.emit(self.a, self.b)
        elif self.length > 0:
            near = min(abs(x - self._x(self.a)), abs(x - self._x(self.b))) < 8
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        self._drag = None


class SongDialog(QDialog):
    def __init__(self, parent=None, new=False, title=None):
        super().__init__(parent)
        self.setWindowTitle(title or ("Add a new music track" if new else "Replace with my song"))
        self.resize(860, 560)
        self.pcm, self.rate = None, 0
        lay = QVBoxLayout(self)
        head = QLabel("The game plays a track's <b>intro</b> once, then its <b>loop</b> part over and over. Set where "
                      "the loop starts and ends: the song jumps from the loop end back to the loop start. Put both "
                      "on the beat, the same place in two bars, then press <b>Hear the loop join</b> to check you "
                      "can't hear the jump.")
        head.setWordWrap(True)
        lay.addWidget(head)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("WAV, FLAC, OGG or MP3" + (" (other formats with ffmpeg)" if audiotools.ffmpeg()
                                                                else ""))
        self.path.editingFinished.connect(lambda: self._load(self.path.text()))
        row.addWidget(self.path, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row.addWidget(b)
        lay.addLayout(row)
        self.wave = Waveform()
        self.wave.moved.connect(self._markers_moved)
        self.wave.clicked.connect(self._play_from)
        lay.addWidget(self.wave, 1)
        f = QFormLayout()
        self.a = QDoubleSpinBox()
        self.b = QDoubleSpinBox()
        for s in (self.a, self.b):
            s.setDecimals(3)
            s.setSuffix(" s")
            s.setSingleStep(0.01)
            s.setRange(0, 0)
            s.valueChanged.connect(self._spins_changed)
        self.a.setToolTip("Everything before this is the intro, played once")
        self.b.setToolTip("When the song gets here it jumps back to the loop start (the rest is never played)")
        self.whole = QCheckBox("Loop the whole song (no intro)")
        self.whole.toggled.connect(self._whole)
        f.addRow("Loop starts at", self.a)
        f.addRow("Loop ends at", self.b)
        f.addRow("", self.whole)
        lay.addLayout(f)
        row = QHBoxLayout()
        for text, fn, tip in (("▶ Play", lambda: self._play_from(self.wave.head or 0.0), "From the start, or from where "
                                                                                          "you clicked the waveform"),
                              ("▶ Hear the loop join", self._play_join, "The 4 seconds before the loop end, then the "
                                                                        "loop start: what the game plays"),
                              ("■ Stop", self._stop, "")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.info = QLabel()
        self.info.setObjectName("muted")
        row.addWidget(self.info)
        lay.addLayout(row)
        self.parts_mode = QCheckBox("I have the intro and the loop as two separate files")
        self.parts_mode.toggled.connect(self._mode)
        lay.addWidget(self.parts_mode)
        self.parts = QWidget()
        pf = QFormLayout(self.parts)
        self.loop_file, self.intro_file = QLineEdit(), QLineEdit()
        for label, edit in (("Loop part *", self.loop_file), ("Intro (optional)", self.intro_file)):
            r = QHBoxLayout()
            r.addWidget(edit, 1)
            b = QPushButton("Browse…")
            b.clicked.connect(lambda _, e=edit: self._browse_part(e))
            r.addWidget(b)
            pf.addRow(label, r)
        self.parts.hide()
        lay.addWidget(self.parts)
        self.title = self.name = self.listed = None
        if new:
            nf = QFormLayout()
            self.title = QLineEdit()
            self.title.setPlaceholderText("e.g. MOD 01")
            self.title.setToolTip("The label in the game's music list (like the game's own 'BGM 54').")
            self.name = QLineEdit()
            self.name.setPlaceholderText("e.g. My Battle Theme")
            self.name.setToolTip("The song's name, shown under the label.")
            self.listed = QCheckBox("List it in the game's music list (always available)")
            self.listed.setChecked(True)
            nf.addRow("List label", self.title)
            nf.addRow("Song name", self.name)
            nf.addRow("", self.listed)
            lay.addLayout(nf)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._mixer = None
        self._t0 = None
        self._play_offset = 0.0
        self._play_map = None
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ the song
    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Your song", "", FILTER)
        if p:
            self.path.setText(p)
            self._load(p)

    def _browse_part(self, edit):
        p, _ = QFileDialog.getOpenFileName(self, "Audio file", "", FILTER)
        if p:
            edit.setText(p)

    def _load(self, path):
        if not path or not os.path.exists(path) or getattr(self, "_loaded", None) == path:
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pcm, rate = audiotools.read_audio(path)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Your song", f"{os.path.basename(path)} can't be read:\n\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self._loaded = path
        self.pcm, self.rate = pcm, rate
        n = len(pcm) / float(rate)
        self.wave.set_audio(pcm, rate)
        for s in (self.a, self.b):
            s.blockSignals(True)
            s.setRange(0, n)
            s.blockSignals(False)
        self.a.setValue(0.0)
        self.b.setValue(n)
        self.whole.setChecked(True)
        self.info.setText(f"{n:.2f} s, {rate} Hz, {pcm.shape[1]} channel(s)")
        self._spins_changed()

    def _whole(self, on):
        if self.pcm is None:
            return
        if on:
            self.a.setValue(0.0)
            self.b.setValue(len(self.pcm) / float(self.rate))
        self.a.setEnabled(not on)
        self.b.setEnabled(not on)

    def _markers_moved(self, a, b):
        self.whole.setChecked(False)
        for s, v in ((self.a, a), (self.b, b)):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)

    def _spins_changed(self, *_):
        if self.b.value() <= self.a.value():
            self.b.blockSignals(True)
            self.b.setValue(min(self.b.maximum(), self.a.value() + 0.05))
            self.b.blockSignals(False)
        self.wave.set_markers(self.a.value(), self.b.value())

    def _mode(self, on):
        self.parts.setVisible(on)
        for w in (self.wave, self.a, self.b, self.whole, self.path):
            w.setEnabled(not on)

    # ------------------------------------------------------------------ listening
    def _mixer_(self):
        if self._mixer is None:
            from .skilledit.audio import Mixer
            self._mixer = Mixer(self)
        return self._mixer

    def _play(self, pcm, offset, mapping=None):
        m = self._mixer_()
        m.stop()
        m.play(pcm.mean(axis=1).astype(np.float32), self.rate)
        self._t0, self._play_offset, self._play_map = time.time(), offset, mapping
        self._timer.start()

    def _play_from(self, t):
        if self.pcm is None:
            return
        self.wave.head = t
        k = int(t * self.rate)
        self._play(self.pcm[k:k + self.rate * 60], t)

    def _play_join(self):
        if self.pcm is None:
            return
        a, b = int(self.a.value() * self.rate), int(self.b.value() * self.rate)
        pre = max(a, b - 4 * self.rate)
        clip = np.concatenate([self.pcm[pre:b], self.pcm[a:a + 4 * self.rate]])
        self._play(clip, pre / self.rate, mapping=((b - pre) / self.rate, a / self.rate))

    def _tick(self):
        if self._t0 is None:
            return
        el = time.time() - self._t0
        if self._play_map and el >= self._play_map[0]:
            t = self._play_map[1] + el - self._play_map[0]
        else:
            t = self._play_offset + el
        if el > 64 or (self._play_map and el > self._play_map[0] + 4.2):
            self._stop()
            return
        self.wave.head = t
        self.wave.update()

    def _stop(self):
        if self._mixer is not None:
            self._mixer.stop()
        self._timer.stop()
        self._t0 = None

    # ------------------------------------------------------------------ result
    def _ok(self):
        if self.parts_mode.isChecked():
            if not self.loop_file.text().strip():
                QMessageBox.warning(self, "Your song", "Choose the loop part's file.")
                return
        elif self.pcm is None:
            QMessageBox.warning(self, "Your song", "Choose your song first.")
            return
        self._stop()
        self.accept()

    def track_parts(self):
        """(loop Ogg Vorbis bytes, intro Ogg Vorbis bytes or b"") in the game's format"""
        if self.parts_mode.isChecked():
            def conv(p):
                pcm, rate = audiotools.read_audio(p)
                return audiotools.encode_ogg(pcm, rate)
            loop = conv(self.loop_file.text().strip())
            intro = conv(self.intro_file.text().strip()) if self.intro_file.text().strip() else b""
            return loop, intro
        intro, loop = audiotools.split(self.pcm, self.rate, self.a.value(), self.b.value())
        return (audiotools.encode_ogg(loop, self.rate),
                audiotools.encode_ogg(intro, self.rate) if len(intro) > self.rate // 100 else b"")

    def done(self, r):
        self._stop()
        super().done(r)
