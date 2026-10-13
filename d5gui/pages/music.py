import os
import shutil
import struct
import subprocess
import tempfile

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
                             QLabel, QFileDialog, QMessageBox, QHeaderView, QSlider, QDialog, QFormLayout,
                             QLineEdit, QDialogButtonBox, QCheckBox)

from d5lib import music, sound
from ..common import PageHeader, SearchBox, Card, human_size, error_box, info_box

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
except Exception:  # pragma: no cover
    QMediaPlayer = None

BGM = "Sound_BGM/Sound_BGM_0.dat"
# a leftover of the last patch (one other song, also named 542.ogg): the game loads only Sound_BGM_0.dat (its music
# loader 0x1400bf9f0 is set up for one archive), so this copy is listed for listening, never played in game
BGM_EXTRA = "Sound_BGM/Sound_BGM_1.dat"
MUSIC_DB = "Database/Database_0.dat/music.dat"
ROLE = Qt.ItemDataRole.UserRole


def read_music_titles(data: bytes):
    """file number -> (title_EN, desc_EN).  Record layout from music.dat (1048 bytes)."""
    out = {}
    count = struct.unpack_from("<I", data, 0)[0]
    rs = (len(data) - 4) // count if count else 0
    if rs != 1048:
        return out
    for i in range(count):
        r = 4 + i * rs
        fnum = struct.unpack_from("<i", data, r + 8)[0]
        title = data[r + 16 + 44: r + 16 + 88].split(b"\0")[0].decode("utf-8", "replace")
        desc = data[r + 16 + 220 + 160: r + 16 + 220 + 320].split(b"\0")[0].decode("utf-8", "replace")
        out.setdefault(fnum, (title, desc))
    return out


def ffmpeg():
    return shutil.which("ffmpeg")


def to_ogg(path):
    """Return Ogg Vorbis bytes for an audio file (converts with ffmpeg if needed)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"OggS" and b"vorbis" in data[:200]:
        return data
    exe = ffmpeg()
    if not exe:
        raise RuntimeError("This file is not Ogg Vorbis and ffmpeg was not found to convert it.\n"
                           "Install ffmpeg (and add it to PATH) or convert to .ogg (Vorbis, 48000 Hz) yourself.")
    out = tempfile.mktemp(suffix=".ogg")
    subprocess.run([exe, "-y", "-i", path, "-vn", "-ar", "48000", "-ac", "2", "-c:a", "libvorbis", "-q:a", "6", out],
                   check=True, capture_output=True)
    with open(out, "rb") as f:
        data = f.read()
    os.remove(out)
    return data


class ReplaceDialog(QDialog):
    def __init__(self, parent=None, new=False):
        super().__init__(parent)
        self.setWindowTitle("Add a new music track" if new else "Replace music track")
        f = QFormLayout(self)
        f.addRow(QLabel("Pick the song to use. Optionally split it into an intro (played once)\n"
                        "and a loop part (repeats forever). Most people only need the loop file.\n"
                        + ("MP3/WAV/FLAC are converted automatically (ffmpeg found)." if ffmpeg() else
                           "Files must be .ogg (Vorbis). Install ffmpeg to import MP3/WAV/FLAC.")))
        self.loop = QLineEdit()
        self.intro = QLineEdit()
        self.loop.setToolTip("The song, or the part that repeats forever. Required.")
        self.intro.setToolTip("Played once before the loop starts (e.g. a song's opening). Leave empty to loop "
                              "the whole song.")
        for label, edit in (("Loop / whole song *", self.loop), ("Intro (optional)", self.intro)):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            b = QPushButton("Browse…")
            b.clicked.connect(lambda _, e=edit: self._browse(e))
            row.addWidget(b)
            f.addRow(label, row)
        self.title = self.name = self.listed = None
        if new:
            self.title = QLineEdit()
            self.title.setPlaceholderText("e.g. MOD 01")
            self.title.setToolTip("The label in the game's music list (like the game's own 'BGM 54').")
            self.name = QLineEdit()
            self.name.setPlaceholderText("e.g. My Battle Theme")
            self.name.setToolTip("The song's name, shown under the label.")
            self.listed = QCheckBox("List it in the game's music list (always available)")
            self.listed.setChecked(True)
            self.listed.setToolTip("Adds the song to the in-game music list, where you choose the music of your "
                                   "base and battles. Off: the song only plays where you put its number "
                                   "(a stage's music, an event script).")
            f.addRow("List label", self.title)
            f.addRow("Song name", self.name)
            f.addRow("", self.listed)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.resize(560, 180)

    def _browse(self, edit):
        p, _ = QFileDialog.getOpenFileName(self, "Audio file", "", "Audio (*.ogg *.mp3 *.wav *.flac *.m4a);;All (*)")
        if p:
            edit.setText(p)


SE = "Sound_SE/Sound_SE_0.dat"


def to_wav_adpcm(path, channels=1):
    """Convert any audio file into an MS-ADPCM 48 kHz WAV like the game's sound effects."""
    exe = ffmpeg()
    with open(path, "rb") as f:
        data = f.read()
    if not exe:
        if data[:4] != b"RIFF":
            raise RuntimeError("Sound effects must be .wav files (install ffmpeg to import other formats).")
        return data
    out = tempfile.mktemp(suffix=".wav")
    subprocess.run([exe, "-y", "-i", path, "-vn", "-ar", "48000", "-ac", str(channels), "-c:a", "adpcm_ms", out],
                   check=True, capture_output=True)
    with open(out, "rb") as f:
        data = f.read()
    os.remove(out)
    return data


class SoundEffectsTab(QWidget):
    def __init__(self, ws, player):
        super().__init__()
        self.ws, self.player = ws, player
        self.tmpdir = tempfile.mkdtemp(prefix="d5se_")
        lay = QVBoxLayout(self)
        self.search = SearchBox("Filter sound effects by number…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Sound", "Channels", "Length (s)", "Size", "Status"])
        for c, tip in enumerate(["File name of the sound effect in the game's sound pack",
                                 "1 = mono, 2 = stereo", "Length in seconds", "Size in the game files",
                                 "✏ replaced = your mod changes this sound"]):
            self.table.horizontalHeaderItem(c).setToolTip(tip)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.play)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        tips = {"▶ Play": "Play the selected sound effect (double-click a row does the same).",
                "Export .wav…": "Save the selected sound effect as a WAV file.",
                "Replace with my sound…": "Replace the selected sound with your own file (converted to the game's "
                                          "format; same number of channels). Saved into the active mod.",
                "Revert": "Undo your replacement: the original sound is used again."}
        for text, fn in [("▶ Play", self.play), ("Export .wav…", self.export),
                         ("Replace with my sound…", self.replace), ("Revert", self.revert)]:
            b = QPushButton(text)
            b.setToolTip(tips[text])
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self._loaded = False

    def load(self):
        self._loaded = True
        ents = self.ws.fs.pack(SE).entries
        self.table.setRowCount(len(ents))
        for i, e in enumerate(ents):
            vpath = f"{SE}/{e.name}"
            try:
                se = sound.parse_se(self.ws.read(vpath))
                inf = sound.wav_info(se["wav"])
                vals = [e.name, str(inf.get("channels", "?")), f"{se['samples'] / max(se['rate'], 1):.2f}",
                        human_size(e.size), "✏ replaced" if self.ws.is_modified(vpath) else ""]
            except Exception as ex:
                vals = [e.name, "?", "?", human_size(e.size), str(ex)]
            tip = (f"<qt><b>Sound effect {e.name}</b><br>{vals[1]} channel(s), {vals[2]} s"
                   + ("<br>✏ replaced by your mod" if vals[4] else "") + "<br>Double-click to play</qt>")
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(ROLE, vpath)
                it.setToolTip(tip)
                self.table.setItem(i, c, it)

    def _filter(self, t):
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, bool(t) and t.lower() not in self.table.item(r, 0).text().lower())

    def _cur(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(ROLE) if r >= 0 else None

    def play(self, *a):
        v = self._cur()
        if not v or not self.player:
            return
        path = os.path.join(self.tmpdir, v.split("/")[-1] + (".mod" if self.ws.is_modified(v) else "") + ".wav")
        with open(path, "wb") as f:
            f.write(sound.parse_se(self.ws.read(v))["wav"])
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def export(self):
        v = self._cur()
        if not v:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export", v.split("/")[-1].replace(".vag", ".wav"), "WAV (*.wav)")
        if p:
            with open(p, "wb") as f:
                f.write(sound.parse_se(self.ws.read(v))["wav"])

    def replace(self):
        v = self._cur()
        if not v:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Sound file", "", "Audio (*.wav *.ogg *.mp3 *.flac);;All (*)")
        if not p:
            return
        try:
            orig = sound.parse_se(self.ws.read(v))
            ch = sound.wav_info(orig["wav"]).get("channels", 1)
            wav = to_wav_adpcm(p, ch)
            if self.ws.write(v, sound.build_se(wav, orig["rate"]), self):
                self.load()
        except Exception as e:
            error_box(self, "Could not import sound", e)

    def revert(self):
        v = self._cur()
        if v:
            self.ws.revert(v)
            self.load()


class MusicPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.tmpdir = tempfile.mkdtemp(prefix="d5music_")
        outer = QVBoxLayout(self)
        outer.addWidget(PageHeader("Music & Sound",
                                   "Listen to every background track and sound effect and replace any of them with your own. "
                                   "Music loops seamlessly: give an optional intro plus a loop section."))
        from PyQt6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        bgm = QWidget()
        lay = QVBoxLayout(bgm)
        self.tabs.addTab(bgm, "Background music")
        top = QHBoxLayout()
        self.search = SearchBox("Filter tracks…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        lay.addLayout(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["File #", "Gallery label", "Song name", "Size", "Status"])
        for c, tip in enumerate(["Number of the music file (stages and scripts refer to it)",
                                 "Where the song appears in the in-game music gallery",
                                 "Title of the song", "Size in the game files",
                                 "✏ replaced = your mod plays your song instead"]):
            self.table.horizontalHeaderItem(c).setToolTip(tip)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 260)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.play)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        tips = {"➕ Add new track…": "Add a song of your own under a new track number (the game's tracks stay as they "
                                      "are). It can be listed in the game's music list, and plays wherever its "
                                      "number is used (a stage's music, an event script). Saved into the active mod.",
                "▶ Play": "Play the selected track (double-click a row does the same).",
                "■ Stop": "Stop playback.",
                "Export .ogg…": "Save the selected track as an .ogg file.",
                "Replace with my song…": "Use your own song for this track (optional intro + loop part). "
                                         "MP3/WAV/FLAC are converted when ffmpeg is installed. Saved into the "
                                         "active mod.",
                "Revert": "Undo your replacement: the original track plays again. On a new track: remove it."}
        for text, fn in [("➕ Add new track…", self.add_track), ("▶ Play", self.play), ("■ Stop", self.stop),
                         ("Export .ogg…", self.export), ("Replace with my song…", self.replace),
                         ("Revert", self.revert)]:
            b = QPushButton(text)
            b.setToolTip(tips[text])
            b.clicked.connect(fn)
            row.addWidget(b)
        self.pos = QSlider(Qt.Orientation.Horizontal)
        self.pos.setToolTip("Playback position — drag to jump")
        self.pos.sliderMoved.connect(lambda v: self.player and self.player.setPosition(v))
        row.addWidget(self.pos, 1)
        self.now = QLabel("")
        row.addWidget(self.now)
        lay.addLayout(row)
        self.player = None
        if QMediaPlayer:
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.6)
            self.player.setAudioOutput(self.audio)
            self.player.durationChanged.connect(self.pos.setMaximum)
            self.player.positionChanged.connect(self._pos)
            self.player.mediaStatusChanged.connect(self._status)
        self._seq = 0
        self._loop_url = None
        self._part = ""
        self._loaded = False
        ws.file_changed.connect(lambda v: v.startswith("Sound_BGM") and self.load())
        self.se_tab = SoundEffectsTab(ws, self.player)
        self.tabs.addTab(self.se_tab, "Sound effects")
        self.tabs.currentChanged.connect(lambda i: i == 1 and not self.se_tab._loaded and self.se_tab.load())

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.load()

    def _pos(self, p):
        if not self.pos.isSliderDown():
            self.pos.setValue(p)
        self.now.setText(f"{self._part}{p // 60000}:{p // 1000 % 60:02d}")

    def _status(self, st):
        """the intro has played: the loop part follows and repeats, as in the game"""
        if st == QMediaPlayer.MediaStatus.EndOfMedia and self._loop_url is not None:
            url, self._loop_url = self._loop_url, None
            self._part = "loop "
            self.player.setSource(url)
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
            self.player.play()

    def load(self):
        try:
            titles = read_music_titles(self.ws.read(MUSIC_DB))
        except Exception:
            titles = {}
        rows = []
        for arc in (BGM, BGM_EXTRA):
            for e in self.ws.fs.pack(arc).entries:
                rows.append((arc, e))
        rows.sort(key=lambda r: int(r[1].name.split(".")[0]) if r[1].name.split(".")[0].isdigit() else 99999)
        # tracks the mods add (new numbers): after the game's
        self._new = {}
        mods = self.ws.mods.enabled_mods()
        if self.ws.active_mod and all(m.id != self.ws.active_mod.id for m in mods):
            mods.append(self.ws.active_mod)
        for m in mods:
            for num in music.mod_tracks(m):
                if num in self._new:
                    continue
                self._new[num] = m
                vp = music.track_vpath(num)
                size = len(m.read_file(vp))

                class _E:
                    pass
                e = _E()
                e.name, e.size = f"{num}.ogg", size
                rows.append((BGM, e))
        self.table.setRowCount(len(rows))
        for i, (arc, e) in enumerate(rows):
            num = e.name.split(".")[0]
            t, d = titles.get(int(num), ("", "")) if num.isdigit() else ("", "")
            unused = arc == BGM_EXTRA
            if unused:
                t, d = "(not used by the game)", "Another song also numbered " + num + " (Sound_BGM_1.dat)"
            new = num.isdigit() and int(num) in self._new
            if new:
                ls = music.listing(self.ws.fs, self._new[int(num)], int(num))
                t, d = ls if ls else ("(not in the music list)", f"New track {num}")
            vpath = f"{arc}/{e.name}"
            modified = self.ws.is_modified(vpath)
            try:
                meta = struct.unpack_from("<7I", self.ws.read(vpath)[:28]) if modified else None
            except Exception:
                meta = None
            samples = meta[3] if meta else None
            items = [num + (" (extra)" if unused else ""), t or "(not in music gallery)", d, "",
                     f"✚ new (mod {self._new[int(num)].name})" if new else
                     "✏ replaced" if modified else ("unused copy" if unused else "")]
            tip = (f"<qt><b>{d or 'Track ' + num}</b><br>"
                   + ("This song is in Sound_BGM_1.dat, which the game never loads: the game's track " + num +
                      " is the other row. You can listen to it and export it.<br>" if unused else
                      f"A track your mod adds: use number {num} for a stage's music or in an event script "
                      "(bgm_play).<br>" if new else
                      f"Music gallery: {t}<br>" if t else "Not listed in the music gallery<br>")
                   + f"file {num} · {human_size(e.size)}"
                   + ("<br>✏ replaced by your mod" if modified else "") + "<br>Double-click to play</qt>")
            for c, v in enumerate(items):
                it = QTableWidgetItem(v)
                it.setData(ROLE, vpath)
                it.setToolTip(tip)
                self.table.setItem(i, c, it)
            self.table.item(i, 3).setText(human_size(e.size))

    def _filter(self, t):
        t = t.lower()
        for r in range(self.table.rowCount()):
            txt = " ".join(self.table.item(r, c).text().lower() for c in range(3))
            self.table.setRowHidden(r, bool(t) and t not in txt)

    def _cur(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(ROLE) if r >= 0 else None

    def play(self, *a):
        """the intro once, then the loop part over and over, as the game plays it.  The parts are separate files:
        the track's single chained Ogg (intro + loop streams) tripped the player at the join.  Every play writes
        files of its own: the same name for the two tracks numbered 542 kept the second from playing (the player
        still had the first file open)."""
        v = self._cur()
        if not v or not self.player:
            return
        try:
            t = sound.parse_track(self.ws.read(v))
        except Exception as e:
            error_box(self, "Could not read the track", e)
            return
        self.player.stop()
        self.player.setSource(QUrl())                  # let go of the previous files
        self._clean_tmp()
        self._seq += 1
        arc = v.split("/")[-2].split(".")[0]
        base = os.path.join(self.tmpdir, f"{self._seq}_{arc}_{v.split('/')[-1].split('.')[0]}")
        with open(base + "_loop.ogg", "wb") as f:
            f.write(t["loop"])
        loop = QUrl.fromLocalFile(base + "_loop.ogg")
        if t["intro"]:
            with open(base + "_intro.ogg", "wb") as f:
                f.write(t["intro"])
            self._loop_url, self._part = loop, "intro "
            self.player.setSource(QUrl.fromLocalFile(base + "_intro.ogg"))
            self.player.setLoops(1)
        else:
            self._loop_url, self._part = None, "loop "
            self.player.setSource(loop)
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.play()

    def _clean_tmp(self):
        for f in os.listdir(self.tmpdir):
            try:
                os.remove(os.path.join(self.tmpdir, f))
            except OSError:
                pass                                   # still open: removed next time

    def stop(self):
        if self.player:
            self._loop_url = None
            self.player.stop()

    def export(self):
        v = self._cur()
        if not v:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export", v.split("/")[-1], "Ogg (*.ogg)")
        if p:
            with open(p, "wb") as f:
                f.write(sound.track_to_ogg(self.ws.read(v)))

    def add_track(self):
        mod = self.ws.require_mod(self)
        if not mod:
            return
        dlg = ReplaceDialog(self, new=True)
        if not dlg.exec() or not dlg.loop.text():
            return
        try:
            loop = to_ogg(dlg.loop.text())
            intro = to_ogg(dlg.intro.text()) if dlg.intro.text() else b""
            mods = self.ws.mods.all_mods()
            num = music.add_track(self.ws.fs, mod, mods, loop, intro, dlg.title.text().strip(),
                                  dlg.name.text().strip(), listed=dlg.listed.isChecked())
        except Exception as e:
            error_box(self, "Could not add the song", e)
            return
        self.ws.file_changed.emit(music.track_vpath(num))
        self.ws.log(f"New music track {num} in mod '{mod.name}'")
        info_box(self, "New track added",
                 f"Your song is track {num}." +
                 (" It is in the game's music list once you install." if dlg.listed.isChecked() else "") +
                 f"\n\nUse {num} wherever a music number is asked for: a stage's music (Stages & Maps), or "
                 f"bgm_play {num} in an event script.")
        self.load()

    def replace(self):
        v = self._cur()
        if not v:
            return
        if v.startswith(BGM_EXTRA):
            QMessageBox.information(self, "Not used by the game",
                                    "This song is in Sound_BGM_1.dat, which the game never loads, so replacing it "
                                    "would change nothing in game. Replace the other row with the same number "
                                    "instead: that's the track the game plays.")
            return
        dlg = ReplaceDialog(self)
        if not dlg.exec() or not dlg.loop.text():
            return
        try:
            loop = to_ogg(dlg.loop.text())
            intro = to_ogg(dlg.intro.text()) if dlg.intro.text() else b""
            self.stop()
            if self.ws.write(v, sound.build_track(loop, intro), self):
                self.ws.log(f"Replaced {v}")
        except Exception as e:
            error_box(self, "Could not import song", e)

    def revert(self):
        v = self._cur()
        if not v:
            return
        num = v.split("/")[-1].split(".")[0]
        if num.isdigit() and int(num) in getattr(self, "_new", {}):
            mod = self._new[int(num)]
            if QMessageBox.question(self, "Remove track", f"Remove your track {num} (and its place in the game's "
                                    f"music list) from mod '{mod.name}'?") != QMessageBox.StandardButton.Yes:
                return
            self.stop()
            music.remove_track(self.ws.fs, mod, int(num))
            self.ws.file_changed.emit(v)
            self.load()
            return
        self.stop()
        self.ws.revert(v)
