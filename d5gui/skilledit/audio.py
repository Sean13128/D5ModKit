"""A small software mixer for the skill preview: sound effects and voice lines (d5lib/sfx.py) mixed into one
QAudioSink stream (48 kHz mono 16-bit).  play() starts a sound now; stop() silences everything."""
import numpy as np
from PyQt6.QtCore import QObject, QTimer

RATE = 48000
CHUNK = 960                       # 20 ms


class Mixer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.voices = []          # [pcm, position (source samples), step, gain]
        self.sink = None
        self.io = None
        self.enabled = True
        self.master = 1.0         # master volume (the editor's volume slider), applies to what is playing too
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._feed)
        self.error = None

    def _open(self):
        if self.sink is not None and self.io is not None and self._stopped():
            self._close()                                 # the device went away / failed: a new stream
        if self.sink is not None:
            return self.io is not None
        try:
            from PyQt6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
            fmt = QAudioFormat()
            fmt.setSampleRate(RATE)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            dev = QMediaDevices.defaultAudioOutput()
            if dev.isNull():
                raise RuntimeError("no audio output device")
            self.sink = QAudioSink(dev, fmt, self)
            self.sink.setBufferSize(RATE * 2 // 8)        # 125 ms
            self.io = self.sink.start()
        except Exception as e:                            # no sound: the preview still runs
            self.error = str(e)
            self.sink = self.sink or object()
            self.io = None
        return self.io is not None

    def _stopped(self):
        """the stream ended by itself (an audio device unplugged or failing): writing to it is no use"""
        try:
            from PyQt6.QtMultimedia import QAudio
            return self.sink.state() == QAudio.State.StoppedState
        except Exception:
            return True

    def _close(self):
        s, self.sink, self.io = self.sink, None, None
        try:
            if hasattr(s, "stop"):
                s.stop()
                s.deleteLater()
        except Exception:
            pass

    def play(self, pcm, rate, volume=1.0, speed=1.0):
        """pcm: mono float32 -1..1 at `rate`; speed: 1 = normal (also raises the pitch, as the game does)"""
        if not self.enabled or pcm is None or not len(pcm) or not self._open():
            return
        step = rate / RATE * max(0.05, speed)
        self.voices.append([pcm, 0.0, step, max(0.0, volume)])
        if len(self.voices) > 24:
            self.voices.pop(0)
        if not self.timer.isActive():
            self.timer.start()

    def stop(self):
        self.voices.clear()

    def _feed(self):
        try:
            self._feed_once()
        except Exception as e:                            # a broken stream never stops the kit: quiet until a
            self.error = str(e)                           # next sound opens a new one
            self.voices.clear()
            self.timer.stop()
            self._close()

    def _feed_once(self):
        if self.io is None:
            self.timer.stop()
            return
        if self._stopped():
            raise RuntimeError("the audio stream stopped")
        free = self.sink.bytesFree() // 2
        if free < CHUNK:
            return
        n = min(free, CHUNK * 4)
        out = np.zeros(n, np.float32)
        keep = []
        for v in self.voices:
            pcm, pos, step, gain = v
            idx = pos + step * np.arange(n, dtype=np.float64)
            ok = idx < len(pcm) - 1
            if ok.any():
                i = idx[ok]
                i0 = i.astype(np.int64)
                fr = (i - i0).astype(np.float32)
                out[:len(i)] += (pcm[i0] * (1 - fr) + pcm[i0 + 1] * fr) * gain
            v[1] = pos + step * n
            if v[1] < len(pcm) - 1:
                keep.append(v)
        self.voices = keep
        out = np.tanh(out * 0.9 * self.master)            # soft limit when many sounds overlap
        self.io.write((out * 32767).astype("<i2").tobytes())
        if not self.voices and self.sink.bytesFree() >= self.sink.bufferSize():
            self.timer.stop()
