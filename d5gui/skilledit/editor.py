"""Skill timeline editor: preview a skill's whole choreography in the kit (no game needed) and edit it on a
timeline.  Backend: d5lib/choreo.py (simulation + edits), d5lib/fxmodel.py (effect models); docs/SKILL_EDITOR.md.

The first edit of a vanilla skill makes its editable copy in the active mod by itself (skills.make_custom), then
does the edit there.  Things you add go into small layer events of the copy; Save writes the changed events into
the mod (skills.json), ▶ Preview in game sends them to the running game."""
import copy
import math
import os
import time

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QComboBox, QCheckBox,
                             QLabel, QDoubleSpinBox, QInputDialog, QMessageBox, QSlider, QToolButton, QTabWidget,
                             QLineEdit, QFrame)

from d5lib import (choreo, database, dbpatch, fxnames, fxtools, particles, presets, sfx, skillarea, skills,
                   script)
from d5lib.modsys import KIT_DIR
from .arrange import ArrangePanel
from .areapanel import AreaPanel
from .presetpanel import PresetPanel
from .audio import Mixer
from ..common import Banner, error_box, info_box
from .props import PropertiesPanel, EffectPicker
from .library import EffectLibrary
from .preview import PreviewView
from .render import FxPainter
from .glview import StageRenderer
from d5lib.stage import facing_quarter, turn_offset
from .timeline import TimelineView, build_rows, KIND_GROUPS

# $60201 -> where the target is on screen with the battle camera's first view (stage.FACING_DIRS + the game's
# yaw of -45 degrees): 0 away to the left, 1 away to the right, 2 toward you on the right, 3 toward you on the left
FACINGS = [("Facing back-left", 0), ("Facing back-right", 1), ("Facing front-right", 2), ("Facing front-left", 3)]
SPEEDS = [("¼×", 0.25), ("½×", 0.5), ("1×", 1.0), ("2×", 2.0)]
WEAPONS = [("No weapon", None), ("Sword", 11), ("Spear", 12), ("Bow", 13), ("Gun", 14), ("Axe", 15), ("Staff", 16)]
MOTION_NAMES = {0: "stand", 100: "idle / ready", 101: "attack", 109: "cast", 151: "cast release", 400: "damage",
                401: "damage", 207: "attack (monster)", 102: "attack 2", 103: "attack 3", 104: "jump", 105: "land",
                106: "hurt", 107: "guard", 108: "dodge", 110: "walk", 111: "run", 200: "special", 201: "special 2",
                205: "slash", 300: "lift", 301: "throw"}
LABELS_FILE = os.path.join(KIT_DIR, "state", "effect_labels.json")


def _vline():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet("color: #3a3553;")
    return f


class SkillTimelineEditor(QWidget):
    def __init__(self, ws, page):
        super().__init__()
        self.ws, self.page = ws, page
        self.sc = None
        self.skill = None
        self.root = None
        self.mod = None
        self.edit = None
        self.tl = None
        self.frame = 0
        self.dirty = False
        self.ctx = choreo.Context(loading=True)     # the game's loading pauses of a first cast (cmd_640a)
        self.fx = None
        self.names = None
        self.renderer = None
        self.playing = False
        self._acc = 0.0
        self._t0 = 0.0
        self.chars = []
        self.drag_slot = None
        self.prefetch = []
        self.mixer = None
        self.sebank = self.vbank = None
        self.voice_ids = {}
        self._sound_at = -1
        self._live = None
        self._live_t = 0.0

        self.setObjectName("skillEditor")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#skillEditor { background: #17151f; }"
                           "#editorBar { background: #1d1a29; border: 1px solid #2d2940; border-radius: 9px; }"
                           "#editorBar QLabel { color: #b9b4cc; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)

        # --- toolbar: transport | volume | edit
        barw = QFrame()
        barw.setObjectName("editorBar")
        bar = QHBoxLayout(barw)
        bar.setContentsMargins(8, 5, 8, 5)
        bar.setSpacing(6)
        self.play_btn = QPushButton("▶")
        self.play_btn.setToolTip("Play / pause (Space)")
        self.play_btn.setFixedWidth(44)
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_btn)
        for txt, tip, fn in (("⏮", "Start (Home)", lambda: self.set_frame(0)),
                             ("◀", "Previous frame (←)", lambda: self.set_frame(self.frame - 1)),
                             ("▶|", "Next frame (→)", lambda: self.set_frame(self.frame + 1))):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.setFixedWidth(38)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.speed = QComboBox()
        for label, v in SPEEDS:
            self.speed.addItem(label, v)
        self.speed.setCurrentIndex(2)
        self.speed.setToolTip("Playback speed")
        bar.addWidget(self.speed)
        self.loop = QCheckBox("Loop")
        self.loop.setChecked(True)
        bar.addWidget(self.loop)
        bar.addWidget(_vline())
        self.sound = QCheckBox("🔊")
        self.sound.setChecked(True)
        self.sound.setToolTip("Play the skill's sound effects and voice lines while it plays (click a sound key on "
                              "the timeline to hear it alone)")
        self.sound.toggled.connect(lambda on: on or self._mixer_stop())
        bar.addWidget(self.sound)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 150)
        self.volume.setFixedWidth(130)
        self.volume.setToolTip("Volume of the preview's sounds and voices (click it, then drag or use the wheel)")
        self.volume.setValue(int(self.ws.settings.get("skill_editor_volume", 70)))
        self.volume.valueChanged.connect(self._volume_changed)
        self.volume.sliderReleased.connect(self.ws.save_settings)
        bar.addWidget(self.volume)
        self.vol_label = QLabel(f"{self.volume.value()}%")
        self.vol_label.setFixedWidth(40)
        bar.addWidget(self.vol_label)
        bar.addWidget(_vline())
        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("Undo (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("Redo (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo)
        for b in (self.undo_btn, self.redo_btn):
            b.setFixedWidth(38)
            bar.addWidget(b)
        bar.addStretch(1)
        self.focus_btn = QPushButton("⤢ Focus")
        self.focus_btn.setCheckable(True)
        self.focus_btn.setToolTip("Give the editor the whole window (hides the skill list and the page header). "
                                  "Click again to bring them back.")
        self.focus_btn.toggled.connect(self._focus)
        bar.addWidget(self.focus_btn)
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setToolTip("Write the changes into the mod (Ctrl+S)")
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        self.game_btn = QPushButton("▶ Preview in game")
        self.game_btn.setObjectName("primary")
        self.game_btn.clicked.connect(self.preview_in_game)
        bar.addWidget(self.game_btn)
        lay.addWidget(barw)

        # --- scene: who, facing, distance, camera (can be folded away)
        scw = QFrame()
        scw.setObjectName("editorBar")
        sc = QHBoxLayout(scw)
        sc.setContentsMargins(8, 4, 8, 4)
        sc.setSpacing(6)
        self.scene_toggle = QToolButton()
        self.scene_toggle.setText("▾ Scene")
        self.scene_toggle.setCheckable(True)
        self.scene_toggle.setChecked(True)
        self.scene_toggle.setToolTip("Show / hide the scene settings")
        sc.addWidget(self.scene_toggle)
        self.scene_box = QWidget()
        sb = QHBoxLayout(self.scene_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(6)
        sb.addWidget(QLabel("Caster"))
        self.caster = QComboBox()
        self.caster.setMinimumWidth(170)
        self.caster.currentIndexChanged.connect(self._look_changed)
        sb.addWidget(self.caster, 2)
        sb.addWidget(self._pick_button(self.caster, "Choose the caster by picture"))
        self.weapon = QComboBox()
        for label, v in WEAPONS:
            self.weapon.addItem(label, v)
        self.weapon.currentIndexChanged.connect(self._look_changed)
        sb.addWidget(self.weapon)
        sb.addWidget(QLabel("Target"))
        self.target = QComboBox()
        self.target.setMinimumWidth(170)
        self.target.currentIndexChanged.connect(self._look_changed)
        sb.addWidget(self.target, 2)
        sb.addWidget(self._pick_button(self.target, "Choose the target by picture"))
        sb.addWidget(_vline())
        self.facing = QComboBox()
        for label, v in FACINGS:
            self.facing.addItem(label, v)
        self.facing.setToolTip("Which way the caster faces ($60201): skills place their effects per facing")
        self.facing.currentIndexChanged.connect(self._ctx_changed)
        sb.addWidget(self.facing)
        self.dist = QDoubleSpinBox()
        self.dist.setRange(0.5, 8)
        self.dist.setSingleStep(0.5)
        self.dist.setValue(1.0)
        self.dist.setPrefix("↔ ")
        self.dist.setSuffix(" panels")
        self.dist.setToolTip("Panels from the caster to the cursor (skills with a reach) or to the target")
        self.dist.valueChanged.connect(self._look_changed)
        sb.addWidget(self.dist)
        self.stage = QComboBox()
        self.stage.setToolTip("Where the skill is shown: a battle map (as in the game) or a flat floor with a grid")
        self.stage.setMinimumWidth(150)
        self.stage.addItem("Flat floor (grid)", 0)
        self.stage.currentIndexChanged.connect(self._stage_changed)
        sb.addWidget(self.stage)
        self.big = QCheckBox("Big unit")
        self.big.setToolTip("The caster is a big (2x2) monster ($62802)")
        self.big.toggled.connect(self._ctx_changed)
        sb.addWidget(self.big)
        self.game_cam = QCheckBox("Game camera")
        self.game_cam.setToolTip("See it as the game shows it: the skill's own camera, 16:9.  Looking around with "
                                 "the mouse switches to a free camera (the badge in the view says which one is on); "
                                 "tick this, press C or play the skill to go back")
        self.game_cam.setChecked(True)
        self.game_cam.toggled.connect(self._cam_toggled)
        sb.addWidget(self.game_cam)
        self.hud_box = QCheckBox("HUD")
        self.hud_box.setToolTip("The battle HUD over the game camera: the skill's name and a number for every hit "
                                "(its share of the skill's damage, in percent)")
        self.hud_box.setChecked(True)
        self.hud_box.toggled.connect(lambda on: (setattr(self.view, "show_hud", on), self.view.update()))
        sb.addWidget(self.hud_box)
        self.area_box = QCheckBox("Area")
        self.area_box.setToolTip("Draw the skill's panels on the ground: red = hit, orange = the cursor's panel, green "
                                 "= where the caster ends up, blue = where the cursor can go (the game shows them "
                                 "while aiming, not during the skill). Change them on the 🟥 Area tab")
        self.area_box.setChecked(True)
        self.area_box.toggled.connect(self.area_display)
        sb.addWidget(self.area_box)
        sc.addWidget(self.scene_box, 1)
        self.scene_toggle.toggled.connect(lambda on: (self.scene_box.setVisible(on),
                                                      self.scene_toggle.setText("▾ Scene" if on else "▸ Scene")))
        lay.addWidget(scw)
        self.banner = Banner()
        self.banner.hide()
        lay.addWidget(self.banner)

        # --- views: preview | tabs (inspector, effects, arrange) over the timeline
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.setHandleWidth(7)
        top = QSplitter()
        top.setHandleWidth(7)
        self.view = PreviewView(None)
        self.view.set_game_camera(True)
        top.addWidget(self.view)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(330)
        self.inspector = PropertiesPanel()
        self.inspector.editable = self._can_edit
        self.inspector.valueEdited.connect(self.set_value)
        self.inspector.retime.connect(self.retime)
        self.inspector.trimTo.connect(lambda it, end: self.trim(it, end - it.end))
        self.inspector.deleteOps.connect(self.delete_ops)
        self.inspector.moveClipBy.connect(self.move_clip)
        self.inspector.pickEffect.connect(self.pick_effect)
        self.inspector.playSound.connect(lambda op: (self._mixer_stop(), self.play_sound(op)))
        self.inspector.actionRequested.connect(self._props_action)
        self.inspector.putAtShow.connect(self.put_at_show)
        self.inspector.pickPose.connect(self.pick_pose)
        self.inspector.pickSound.connect(self.pick_sound)
        self.tabs.addTab(self.inspector, "✏ Properties")
        self.library = None
        self.lib_holder = QWidget()
        QVBoxLayout(self.lib_holder).setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(self.lib_holder, "➕ Add effects")
        self.arrange = ArrangePanel(self)
        self.tabs.addTab(self.arrange, "🎯 Group && paths")
        self.preset_panel = PresetPanel(self)
        self.tabs.addTab(self.preset_panel, "🧩 Presets")
        self.area_panel = AreaPanel(self)
        self.tabs.addTab(self.area_panel, "🟥 Area")
        self.tabs.setTabToolTip(0, "What is selected, in plain words: picture, place, size, timing, moves")
        self.tabs.setTabToolTip(1, "All effect pictures: drag one onto the timeline or double-click to add it")
        self.tabs.setTabToolTip(2, "Several effects at once: spacing, shapes, flight paths (homing missile …)")
        self.tabs.setTabToolTip(3, "Ready-made building blocks: dashes, jumps, camera moves, shakes, fades, hits, "
                                   "effect motions")
        self.tabs.setTabToolTip(4, "Where the skill hits: its panels, how far the cursor reaches, and enemies to "
                                   "try it on")
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget() is self.preset_panel
                                         and self.preset_panel.refresh())
        top.addWidget(self.tabs)
        top.setStretchFactor(0, 1)
        top.setSizes([980, 420])
        self.vsplit.addWidget(top)
        tlw = QWidget()
        tll = QVBoxLayout(tlw)
        tll.setContentsMargins(0, 0, 0, 0)
        tll.setSpacing(4)
        fbar = QHBoxLayout()
        fbar.setSpacing(4)
        self.kind_btns = {}
        self.row_search = QLineEdit()
        self.row_search.setPlaceholderText("Find tracks: effect name, slot, sound…")
        self.row_search.setClearButtonEnabled(True)
        self.row_search.setMaximumWidth(320)
        self.row_search.setMinimumWidth(200)
        self.row_search.textChanged.connect(self._filter_rows)
        fbar.addWidget(self.row_search)
        tip = QLabel("click ▾ to fold a group · drag empty space to box-select · drag a clip's right edge to change "
                     "when it ends · Del deletes · Shift+D duplicates · Ctrl+C / Ctrl+V · G moves in time")
        tip.setObjectName("muted")
        from PyQt6.QtWidgets import QSizePolicy
        tip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tip.setToolTip(tip.text())
        fbar.addWidget(tip, 1)
        for txt, tip_, fn in (("－", "Zoom out (Ctrl+wheel)", lambda: self.timeline.zoom(1 / 1.4)),
                              ("Fit", "Whole skill (F)", lambda: self.timeline.fit()),
                              ("＋", "Zoom in (Ctrl+wheel)", lambda: self.timeline.zoom(1.4))):
            b = QToolButton()
            b.setText(txt)
            b.setToolTip(tip_)
            b.clicked.connect(fn)
            fbar.addWidget(b)
        tll.addLayout(fbar)
        self.timeline = TimelineView()
        self.timeline.frameChanged.connect(self.set_frame)
        self.timeline.selected.connect(self._selected)
        self.timeline.selectionChanged.connect(self._selection_changed)
        self.timeline.moveRequested.connect(self.move)
        self.timeline.deleteRequested.connect(self.delete)
        self.timeline.addRequested.connect(self.add)
        self.timeline.effectDropped.connect(self.drop_effect)
        self.timeline.trimRequested.connect(self.trim)
        self.timeline.duplicateRequested.connect(lambda items, d: self.duplicate(items, d))
        self.timeline.copyRequested.connect(self.copy)
        self.timeline.pasteRequested.connect(self.paste)
        self.timeline.trackDeleteRequested.connect(self.delete_track)
        self.timeline.trackHideToggled.connect(self.hide_track)
        tll.addWidget(self.timeline, 1)
        self.vsplit.addWidget(tlw)
        self.vsplit.setStretchFactor(0, 3)
        self.vsplit.setStretchFactor(1, 2)
        self.vsplit.setSizes([520, 340])
        lay.addWidget(self.vsplit, 1)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        lay.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self._tick)
        self.pre_timer = QTimer(self)
        self.pre_timer.setInterval(30)
        self.pre_timer.timeout.connect(self._prefetch)
        self._clipboard = []
        for keys, fn in (("Space", self.toggle_play), ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo),
                         ("Ctrl+Shift+Z", self.redo), ("Ctrl+S", self.save),
                         ("Ctrl+C", lambda: self.copy(self.selected_clip_items())),
                         ("Ctrl+V", lambda: self.paste(self.frame))):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self._update_buttons()

    def _volume_changed(self, v):
        self.vol_label.setText(f"{v}%")
        if self.mixer is not None:
            self.mixer.master = v / 100.0
        self.ws.settings["skill_editor_volume"] = int(v)
        if not self.volume.isSliderDown():
            self.ws.save_settings()

    def _focus(self, on):
        self.focus_btn.setText("⤡ Normal" if on else "⤢ Focus")
        if hasattr(self.page, "set_focus_mode"):
            self.page.set_focus_mode(on)

    def _filter_rows(self, *_):
        self.timeline.set_filter(None, self.row_search.text())

    # ================================================================== setup
    def _ensure_tools(self):
        if self.fx is not None:
            return
        mods = self.page.mods()
        self.fx = FxPainter(self.ws.fs.read, self.page.members, mods)
        self.names = fxnames.Names(mods, LABELS_FILE)

        def owner_read(vp):
            o = self.ws.owner(vp)
            return o.read_file(vp) if o else None
        self.renderer = StageRenderer(self.ws.fs, mods, owner_read, self.page.members)
        self.view.r = self.renderer
        from .hud import Hud
        self.view.hud = Hud(self.ws.fs)
        self._fill_stages()
        self.view.cameraFreed.connect(self._cam_freed)
        self.view.cameraChanged.connect(self._cam_changed)
        self.view.gizmo = self.gizmo_info
        self.view.gizmoStart.connect(self._gizmo_start)
        self.view.gizmoDrag.connect(self._gizmo_drag)
        self.view.gizmoEnd.connect(self._gizmo_end)
        self.view.gizmoCancel.connect(self._gizmo_cancel)
        self.view.pickRequested.connect(self._pick)
        self.view.deleteRequested.connect(self.delete_selected)
        self.view.duplicateRequested.connect(lambda: self.duplicate(self.selected_clip_items(), 0, then_move=True))
        self.view.selectAllRequested.connect(self._select_all_on_screen)
        self.view.menuRequested.connect(self._view_menu)
        self.view.pivotChanged.connect(self._sync_pivot)
        self.arrange.pivot.currentIndexChanged.connect(lambda _: self._sync_pivot(self.arrange.pivot.currentData()))
        self.inspector.names = self.names
        self.inspector.thumb = self._thumb
        from .thumbs import Thumbs
        self.thumbs = Thumbs(self.renderer.assets)
        self.inspector.thumbs = self.thumbs
        self.inspector.sprite_of = self.sprite_of
        self.inspector.model_queues = self.model_queues
        self.timeline.icon_for = self.timeline_icon
        self.library = EffectLibrary(self.fx, self.names)
        self.library.picked.connect(lambda e: self.drop_effect(e, self.frame, None))
        self.library.renamed.connect(lambda e: self.resim(self.timeline.selection_key()))
        self.lib_holder.layout().addWidget(self.library)
        ids = sorted(int(n[6:10]) for n in self.page.members if n.startswith("effect") and n[6:10].isdigit())
        for m in mods:
            ids += [int(k) for k in (skills.load(m).get("effects") or {}) if int(k) not in ids]
        self.library.fill(ids)
        self._fill_chars()

    def _fill_chars(self):
        try:
            t = database.load_table("char.dat", self.ws.fs.read(f"{dbpatch.DB_ARCHIVE}/char.dat"))
            for mod in self.page.mods():
                patch = mod.load_patch("db", "char.dat.json")
                if patch:
                    dbpatch.apply_patch(t, patch)
            rows = t.rows
        except Exception:
            rows = []
        self.class_sprite = {r["id"]: r["sprite_id"] for r in rows}
        try:                                       # who learns each skill (magic.dat user1): the default caster
            mt = database.load_table("magic.dat", self.ws.fs.read(f"{dbpatch.DB_ARCHIVE}/magic.dat"))
            for mod in self.page.mods():
                patch = mod.load_patch("db", "magic.dat.json")
                if patch:
                    dbpatch.apply_patch(mt, patch)
            self.skill_users = {r["id"]: r["user1"] for r in mt.rows if r["user1"]}
            self.skill_names = {r["id"]: r["name_EN"] or "" for r in mt.rows}
        except Exception:
            self.skill_users = {}
            self.skill_names = {}
        seen, chars = set(), []
        for r in rows:
            s, name = r["sprite_id"], r["name_EN"]
            if not s or not name or s in seen or s >= 10000:
                continue
            seen.add(s)
            chars.append((f"{name} — {r['title_EN']}" if r["title_EN"] else name, s))
            try:
                self.voice_ids[s] = int(r["voice_id"])
            except (KeyError, TypeError, ValueError):
                self.voice_ids[s] = 0
        self.chars = chars
        for cb, default in ((self.caster, 0), (self.target, 1)):
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("(placeholder)", None)
            for label, s in chars:
                cb.addItem(f"{label}  · anm{s:05d}", s)
            cb.setCurrentIndex(min(cb.count() - 1, 1 + default))
            cb.blockSignals(False)
        prinny = next((k for k in range(self.target.count()) if "Prinny" in self.target.itemText(k)), None)
        if prinny is not None:
            self.target.setCurrentIndex(prinny)

    def open(self, skill, root, mod, custom, editable, force=False):
        """show a skill (called by the Skills page whenever its selection or data changes; force: drop the
        editor's copy and re-read the mod, after the script text was saved on the Choreography tab)"""
        if self.dirty and skill != self.skill:
            r = QMessageBox.question(self, "Skill editor", "Save your timeline changes first?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard)
            if r == QMessageBox.StandardButton.Save:
                self.save()
        self._ensure_tools()
        same = skill == self.skill and root == self.root and self.edit is not None and editable and not force
        self.sc = self.page.sc
        self.skill, self.root, self.mod = skill, root, mod
        self.view.hud_title = (getattr(self, "skill_names", {}).get(skill, "")
                               or str(getattr(self.page, "names", {}).get(skill, "")).lstrip("⚡ ") or "")
        if not same:
            self._load_area()
            self.dirty = False
            self.edit = None
            if root and editable:
                eids = skills.custom_events(mod, root)
                self.edit = choreo.Edit(self.sc.ev, eids, root)
            self.frame = 0
            self.inspector.show_item(None)
            self.banner.hide()
        self.resim(keep=self.timeline.selection_key() if same else None)
        if not same:
            self.timeline.fit()
            self.view.face(self.facing.currentData())
            self._default_caster()

    # ================================================================== simulation
    def events(self):
        return self.edit.events() if self.edit else (self.sc.ev if self.sc else {})

    def resim(self, keep=None):
        if not self.root:
            self.tl = None
            self.timeline.set_rows([], 1)
            self.view.show_scene(None, 0)
            self.status.setText("No choreography: this skill plays the default sequence.")
            return
        t0 = time.perf_counter()
        try:
            self.tl = choreo.Simulator(self.events(), self.root, self.ctx).run()
        except Exception as e:
            self.status.setText(f"simulation failed: {e}")
            return
        rows = build_rows(self.tl, self.names, lambda m: MOTION_NAMES.get(m))
        if self.renderer is not None:
            self.renderer.particles = particles.ParticleSim(self.tl.ops)
            self.renderer.bind(self.tl)
        group = self.timeline.clip_keys() if len(self.timeline.multi) > 1 else None
        self.timeline.set_rows(rows, self.tl.length, keep)
        if group:
            self.timeline.select_clip_keys(group, emit=False)
        self._selected(self.timeline.sel, quiet=True)
        self._selection_changed(self.timeline.multi, quiet=True)
        if self._live is None:
            self._refresh_props_later()
        used = sorted({o.args[1] for o in self.tl.ops if o.cid == 0x3c00})
        if self.library:
            self.library.set_used(used)
        self.inspector.motions = self._motions()
        n_fx = sum(1 for r in rows if r.key[0] == "slot")
        mode = "editable copy" if self.edit else "read only — your first change makes an editable copy"
        self.status.setText(f"{self.tl.length} frames ({self.tl.length / 60:.1f} s) · {n_fx} effect slots · "
                            f"{len(used)} effect models · {mode}" + ("  · unsaved" if self.dirty else "")
                            + f"  ({(time.perf_counter() - t0) * 1000:.0f} ms)")
        self.set_frame(min(self.frame, self.tl.length))
        self._start_prefetch()
        self._update_buttons()

    def set_frame(self, f):
        if self.tl is None:
            return
        self.frame = max(0, min(int(f), self.tl.length))
        self.timeline.set_frame(self.frame)
        if self.tabs.currentWidget() is self.preset_panel:
            self.preset_panel.refresh()
        scene = self.tl.scene(self.frame)
        self.view.show_scene(scene, self.frame)

    # ================================================================== playback
    def toggle_play(self):
        if self.tl is None:
            return
        self.playing = not self.playing
        self.play_btn.setText("⏸" if self.playing else "▶")
        if self.playing:
            if not self.view.game_cam and not self.view.free_pinned:
                self.view.set_game_camera(True)        # looking around stops when the skill plays again
            if self.frame >= self.tl.length:
                self.set_frame(0)
            self._t0 = time.perf_counter()
            self._acc = float(self.frame)
            self._sound_at = self.frame - 1          # sounds on the current frame play too
            self.timer.start()
        else:
            self.timer.stop()
            self._mixer_stop()

    def _tick(self):
        now = time.perf_counter()
        dt, self._t0 = now - self._t0, now
        self._acc += dt * 60.0 * (self.speed.currentData() or 1.0)
        f = int(self._acc)
        if f > self.tl.length:
            if self.loop.isChecked():
                self._acc = 0.0
                f = 0
            else:
                self.toggle_play()
                f = self.tl.length
        if f != self.frame:
            if f < self._sound_at:                   # looped: start over
                self._mixer_stop()
                self._sound_at = -1
            self._sounds(self._sound_at, f)
            self._sound_at = f
            self.set_frame(f)

    # ================================================================== sound
    def _audio(self):
        if self.mixer is None:
            data = os.path.join(self.ws.game_dir, "Data")
            self.mixer = Mixer(self)
            self.mixer.master = self.volume.value() / 100.0
            self.sebank = sfx.SoundBank(data)
            self.vbank = sfx.VoiceBank(self.ws.fs, self.page.mods())    # custom voices of the mods too
        return self.mixer

    def _mixer_stop(self):
        if self.mixer is not None:
            self.mixer.stop()

    def _sounds(self, f0, f1):
        """play the sounds of frames f0 < frame <= f1"""
        if not self.sound.isChecked() or self.tl is None:
            return
        for op in self.tl.ops:
            if op.kind == "sound" and f0 < op.frame <= f1:
                self.play_sound(op)

    def play_sound(self, op):
        """one se_play / voice line as the game would play it"""
        m = self._audio()
        a = op.args
        try:
            if op.cid in (0x4612, 0x4610, 0x4618):
                pcm = self.sebank.get(a[0])
                speed = a[2] / 1000.0 if op.cid in (0x4612, 0x4618) and a[2] > 0 else 1.0
                if pcm:
                    m.play(pcm[0], pcm[1], a[1] / 100.0, speed)
            elif op.cid == 0x4632:                   # the actor's own voice: category v // 10000
                actor = choreo.actor_id(a[0] % 10000) if a[0] % 10000 else choreo.CASTER
                sprite = self.renderer.target_sprite if choreo.is_target(actor) else self.renderer.caster_sprite
                line = self.vbank.pick(self.voice_ids.get(sprite, 0), a[0], seed=op.frame)
                pcm = self.vbank.get(line) if line else None
                if pcm:
                    m.play(pcm[0], pcm[1], a[1] / 100.0)
            elif op.cid == 0x4630:
                pcm = self.vbank.get(a[0])
                if pcm:
                    m.play(pcm[0], pcm[1], a[1] / 100.0)
        except (IndexError, TypeError, ValueError):
            pass

    def _start_prefetch(self):
        """render the sprites' frames ahead (the first play is smooth too)"""
        r = self.renderer
        if r is None or self.tl is None:
            return
        todo = []
        for a, num in ((choreo.CASTER, r.caster_sprite), (choreo.TARGET, r.target_sprite)):
            if not num:
                continue
            spans = self.tl.motions(a) or [(0, self.tl.length, 0, None)]
            for s, e, m, _ in spans:
                aid = r.spr.anim_for(num, m)
                for t in range(0, e - s + 1):
                    todo.append((num, aid, t, a))
        self.prefetch = todo
        self.pre_timer.start()

    def _prefetch(self):
        r = self.renderer
        for _ in range(4):
            if not self.prefetch:
                self.pre_timer.stop()
                return
            num, aid, t, a = self.prefetch.pop(0)
            try:
                r.assets.sprite_items(num, aid, t, r.weapon if a == choreo.CASTER else None)
            except Exception:
                pass

    # ================================================================== context
    def _in_battle(self):
        """sprite numbers the battle holds before the skill starts (no loading pause for them)"""
        return tuple(int(s) for s in (self.caster.currentData(), self.target.currentData()) if s)

    def _ctx_changed(self, *_):
        self.ctx.in_battle = self._in_battle()
        self.ctx.vars[60201] = self.facing.currentData()
        self.ctx.vars[62802] = 1 if self.big.isChecked() else 0
        self.ctx.vars[62199] = self._script_sprite()
        if self.renderer:
            self.renderer.facing = self.facing.currentData()
            self.view.face(self.facing.currentData())
        self.ctx.vars.update(self._target_vars())
        self.resim(self.timeline.selection_key())

    def _default_caster(self):
        """the character who learns the skill casts it in the preview (Seraphina for Dazzling Eyes)"""
        user = getattr(self, "skill_users", {}).get(self.skill)
        sprite = getattr(self, "class_sprite", {}).get(user) if user else None
        i = self.caster.findData(sprite) if sprite else -1
        if i >= 0 and i != self.caster.currentIndex():
            self.caster.setCurrentIndex(i)

    def _quarter(self):
        """the quarter turns the game gives this skill's offsets at the chosen facing"""
        return facing_quarter(int(self.facing.currentData() or 0))

    def _script_sprite(self):
        """$62199 as the game gives it: the caster's sprite number (skills branch on it: event poses of Killia /
        Seraphina...); an outfit's own sprite counts as its character's (scalepatch.script_sprite_patch)"""
        s = self.caster.currentData() or 0
        return getattr(self, "script_sprites", {}).get(s, s)

    def _look_changed(self, *_):
        r = self.renderer
        if r is None:
            return
        r.caster_sprite = self.caster.currentData()
        r.target_sprite = self.target.currentData()
        r.weapon = self.weapon.currentData()
        r.distance = self.dist.value()
        r.facing = self.facing.currentData()
        self.inspector.motions = self._motions()
        self._char_icons()
        new = self._script_sprite()
        self.area_panel.set_cursor(r.cursor())
        tv = self._target_vars()
        if (self.ctx.vars.get(62199) != new or any(self.ctx.vars.get(k) != v for k, v in tv.items())
                or self.ctx.in_battle != self._in_battle()):
            # the skill takes other branches for this caster / distance / targets ($62199, $64000, $60400 + i)
            self.ctx.in_battle = self._in_battle()
            self.ctx.vars[62199] = new
            self.ctx.vars.update(tv)
            self.resim(self.timeline.selection_key())
            return
        r.bind(self.tl)
        self.set_frame(self.frame)

    def _pick_button(self, combo, tip):
        b = QToolButton()
        b.setText("🖼")
        b.setToolTip(tip + " (every character's picture)")
        b.clicked.connect(lambda: self.choose_character(combo))
        return b

    def choose_character(self, combo):
        """the character picker (pictures of every class / character) for the Scene bar's caster or target"""
        if getattr(self, "thumbs", None) is None:
            return
        from .pickers import CharacterPicker
        chars = [(combo.itemText(k).split("  · ")[0], combo.itemData(k)) for k in range(combo.count())
                 if combo.itemData(k)]
        dlg = CharacterPicker(self, self.thumbs, chars, combo.currentData(),
                              "Choose the caster" if combo is self.caster else "Choose the target")
        if dlg.exec() and dlg.value() is not None:
            k = combo.findData(dlg.value())
            if k >= 0:
                combo.setCurrentIndex(k)

    def _char_icons(self):
        """the chosen caster and target show their picture in the Scene bar (their sprites are loaded anyway)"""
        if getattr(self, "thumbs", None) is None:
            return
        from PyQt6.QtGui import QIcon
        for cb in (self.caster, self.target):
            k, num = cb.currentIndex(), cb.currentData()
            if k < 0 or not num or cb.itemData(k, Qt.ItemDataRole.DecorationRole) is not None:
                continue
            try:
                pm = self.thumbs.pose_icon(num, 0, size=40)
            except Exception:
                pm = None
            if pm is not None:
                cb.setItemIcon(k, QIcon(pm))

    def _target_vars(self):
        """$64000 (panels to the main target) and $60400 + i (area target i exists) for the preview's enemies"""
        r = self.renderer
        if r is None:
            return {64000: max(1, int(round(self.dist.value())))}
        out = {64000: r.target_distance()}
        out.update(skillarea.target_vars(len(r.target_panels())))
        return out

    # ================================================================== area
    def _load_area(self):
        """the skill's reach and area from the database (with the mods' changes) -> preview + Area tab"""
        r = self.renderer
        if r is None:
            return
        area = None
        if self.skill is not None and int(self.skill) < skills.CHOREO_MIN:
            try:
                svc = self.page.svc
                mt, at = svc.table("magic.dat"), svc.table("AttackMap.dat")
                shape_map = skillarea.shapes(at)
                names = getattr(self, "skill_names", {})
                users = {}
                for row in mt.rows:
                    sid = int(row["attack_map"] or 0)
                    if sid and names.get(int(row["id"])):
                        users.setdefault(sid, []).append(names[int(row["id"])])
                self.area_panel.shape_users = users
                self.area_panel.set_shapes(shape_map, lambda sid: users.get(sid, []))
                area = skillarea.area_for(mt, at, self._area_skill()[0])
            except Exception as e:
                self.ws.log(f"skill area: {e}")
        r.area = copy.deepcopy(area) if area is not None else None
        r.enemies = None
        self.dist.setEnabled(area is None or area.centred)
        if area is not None:
            self.area_panel.set_area(area, True, r.cursor())
            self.area_panel.setEnabled(True)
        else:
            self.area_panel.set_area(skillarea.default_area(), False, r.cursor())
            self.area_panel.summary.setText("This choreography isn't a skill of magic.dat: one target, "
                                            "↔ panels away.")
            self.area_panel.setEnabled(False)
        self.ctx.vars.update(self._target_vars())

    def _area_refresh(self):
        tv = self._target_vars()
        if any(self.ctx.vars.get(k) != v for k, v in tv.items()):
            self.ctx.vars.update(tv)
            self.resim(self.timeline.selection_key())
        elif self.renderer is not None and self.tl is not None:
            self.renderer.bind(self.tl)
            self.set_frame(self.frame)

    def area_edited(self):
        r = self.renderer
        if r is None:
            return
        r.area = copy.deepcopy(self.area_panel.area())
        r.enemies = self.area_panel.grid.enemies
        self.dist.setEnabled(r.area.centred)
        self._area_refresh()

    def area_enemies(self, enemies):
        if self.renderer is not None:
            self.renderer.enemies = enemies
            self._area_refresh()

    def area_cursor(self, n):
        self.dist.setValue(float(n))

    def area_display(self, on):
        if self.renderer is not None:
            self.renderer.show_area = on
            self.renderer.gl.show_area = on
            self.view.update()

    def _area_skill(self):
        """(magic.dat row of the skill shown, may its area change): an Overload's is its skill row"""
        fn = getattr(self.page, "area_skill", None)
        return fn(self.skill) if fn else (self.skill, True)

    def save_area(self):
        """the Area tab's reach and panels -> the active mod (magic.dat / AttackMap.dat row changes)"""
        if self.skill is None or not self.ws.require_mod(self):
            return
        magic, own = self._area_skill()
        if not own:
            return info_box(self, "Area", "This Overload uses the numbers of a game Overload: give it numbers of "
                                          "its own (⚡ Overload tab) to change its area.")
        svc = self.page.svc
        area = self.area_panel.area()
        try:
            base = svc.base("AttackMap.dat")
            sid = skillarea.store(svc.table("magic.dat"), svc.table("AttackMap.dat"), magic, area,
                                  len(base.rows), len(base.sections["cells"].rows))
        except Exception as e:
            return error_box(self, "Area", e)
        for m in ("AttackMap.dat", "magic.dat"):
            svc.mark_dirty(m)
            if not svc.commit(m, self):
                return
        self.ws.log(f"{self.skill_names.get(self.skill, self.skill)}: area saved (shape {sid}, reach {area.range}) "
                    f"into {self.ws.active_mod.name} — Install to use it in the game")
        enemies = self.area_panel.grid.enemies
        self._load_area()
        if enemies is not None and self.renderer is not None:
            self.renderer.enemies = self.area_panel.grid.enemies = enemies
        self._area_refresh()

    def _fill_stages(self):
        """battle maps for the Stage list: dungeon.dat's stages (named), the first Netherworld's first by default"""
        from d5lib import mapfile
        self.stage.blockSignals(True)
        try:
            t = mapfile.DungeonTable(self.ws.fs.read(f"{dbpatch.DB_ARCHIVE}/dungeon.dat"))
            seen = set()
            for rec in t.records:
                if rec.map_id in seen:
                    continue
                seen.add(rec.map_id)
                self.stage.addItem(f"{rec.name() or 'Stage'} · map{rec.map_id:05d}", rec.map_id)
        except Exception:
            self.stage.addItem("map00101", 101)
        want = int(self.ws.settings.get("skill_editor_stage", 101) or 0) if hasattr(self.ws, "settings") else 101
        k = self.stage.findData(want)
        self.stage.setCurrentIndex(k if k >= 0 else 0)
        self.stage.blockSignals(False)
        self.renderer.set_stage(self.stage.currentData() or None)

    def _stage_changed(self, *_):
        if self.renderer is None:
            return
        mid = self.stage.currentData() or None
        self.renderer.set_stage(mid)
        try:
            self.ws.settings["skill_editor_stage"] = mid or 0
            self.ws.save_settings()
        except Exception:
            pass
        self.renderer.bind(self.tl)
        self.set_frame(self.frame)

    def _cam_toggled(self, on):
        self.view.set_game_camera(on, pinned=True)

    def _cam_freed(self):
        self._cam_changed(False)

    def _cam_changed(self, on):
        self.game_cam.blockSignals(True)
        self.game_cam.setChecked(on)
        self.game_cam.blockSignals(False)

    def _motions(self):
        r = self.renderer
        if r is None or not r.caster_sprite:
            return [(f"{m}  {n}", m) for m, n in sorted(MOTION_NAMES.items())]
        a, ids = r.spr.file(r.caster_sprite)
        out = []
        for aid in sorted(ids):
            if aid % 10 == 1:
                m = aid // 10
                out.append((f"{m}  {MOTION_NAMES.get(m, '')}  (anim {aid})", m))
        return out

    # ================================================================== editing
    def _can_edit(self, op, i):
        if self.edit is None:
            # a vanilla skill: editable after the automatic copy unless the value is inside a shared helper
            return bool(op.src[i] if i < len(op.src) else None) and \
                skills.is_choreo(op.src[i][0] if op.src[i] else 0)
        return self.edit.can_set(op, i)

    def _make_copy(self):
        """first edit of a skill without an editable copy in the active mod: make one -> eid mapping or None"""
        mod = self.ws.require_mod(self)
        if not mod:
            return None
        m, d, root, custom = self.page._data()
        if custom and m and m.id == mod.id:
            self.edit = choreo.Edit(self.sc.ev, skills.custom_events(mod, root), root)
            return {}
        old_tree = self.sc.tree(root) if root else []
        try:
            new_root = skills.make_custom(self.ws.fs, mod, self.skill, root or skills.DEFAULT_SCRIPT, self.sc)
        except Exception as e:
            error_box(self, "Editable copy", e)
            return None
        mapping = {old: new_root + k for k, old in enumerate(old_tree)}
        self.page.reload_quiet()
        self.sc = self.page.sc
        self.root, self.mod = new_root, mod
        self.edit = choreo.Edit(self.sc.ev, skills.custom_events(mod, new_root), new_root)
        self.page._show(self.skill, editor=False)
        self.banner.show_text(f"Made an editable copy of this skill's animation in your mod <b>{mod.name}</b> "
                              f"(events {new_root}…). Your changes go there; 💾 Save writes them.", False)
        self.banner.show()
        return mapping

    def _translate(self, ops, mapping):
        """the same ops in the copy's timeline"""
        if not mapping:
            return ops
        tl = choreo.Simulator(self.events(), self.root, self.ctx).run()
        self.tl = tl

        def key(chain, eid, pc):
            return tuple((mapping.get(e, e), p) for e, p in chain) + ((mapping.get(eid, eid), pc),)
        index = {}
        for o in tl.ops:
            index.setdefault(key(o.chain, o.eid, o.pc), []).append(o)
        out = []
        for o in ops:
            cands = index.get(key(o.chain, o.eid, o.pc))
            if cands:
                out.append(min(cands, key=lambda c: abs(c.frame - o.frame)))
        return out

    def _do(self, ops, fn, keep=None):
        """run edit fn(ops) with an undo point, making the editable copy first when needed"""
        if self.tl is None:
            return
        if self.edit is None:
            mapping = self._make_copy()
            if mapping is None:
                return
            ops = self._translate(ops, mapping)
            keep = None
        self.edit.checkpoint()
        try:
            res = fn(ops)
        except Exception as e:
            self.edit.undo()
            self.edit.future.clear()
            error_box(self, "Skill editor", e)
            return
        self.dirty = True
        self.resim(keep if keep is not None else self.timeline.selection_key())
        return res

    @staticmethod
    def _sel_ops(sel):
        if sel is None:
            return []
        if isinstance(sel, list):
            return [o for it in sel for o in (it.ops if not isinstance(it, tuple) else [it[2]])]
        if isinstance(sel, tuple):
            return [sel[2]]
        return list(sel.ops)

    def move(self, sel, delta):
        ops = self._sel_ops(sel)
        if not ops or not delta:
            return
        moved = self._do(ops, lambda ops: self.edit.move(ops, delta, self.tl))
        if moved is not None and moved != delta:
            self.status.setText(f"moved {moved} frames (it can't start before the command it waits for)")

    def retime(self, sel, frame):
        if sel is None:
            return
        if len(self.timeline.multi) > 1 and not isinstance(sel, tuple):
            sel = list(self.timeline.multi)
            start = min(it.start for it in sel)
            return self.move(sel, int(frame) - int(start))
        start = sel[1] if isinstance(sel, tuple) else sel.start
        self.move(sel, int(frame) - int(start))

    def delete(self, sel):
        ops = self._sel_ops(sel)
        if not ops:
            return
        self._do(ops, lambda ops: self.edit.delete(ops, self.tl), keep=("none", None))
        self.timeline.clear_selection()
        self.inspector.show_item(None)

    def set_value(self, op, i, v):
        if self.edit is not None and not self.edit.can_set(op, i):
            return
        shared = self.edit is not None and self.edit.shared(op, i, self.tl)
        self._do([op], lambda ops: ops and self.edit.set_value(ops[0], i, v))
        if shared:
            self.status.setText("note: this value belongs to a helper used several times — all its uses changed")

    def effect_from_library(self, load_op):
        it = self.library.list.currentItem() if self.library else None
        if it is None:
            self.tabs.setCurrentWidget(self.lib_holder)
            return QMessageBox.information(self, "Effect library", "Pick an effect in the ✨ Effects tab first, then "
                                           "press “From library” again.")
        self.set_value(load_op, 1, int(it.data(Qt.ItemDataRole.UserRole)))

    # ---------------------------------------------------------------- adding
    def _row_actor(self, row):
        return row[1] if row and row[0] == "actor" and choreo.is_target(row[1]) else choreo.CASTER

    def drop_effect(self, eid, frame, row):
        actor = self._row_actor(row)
        res = self._do([], lambda ops: self.edit.add_effect(frame, eid, actor, (0, 60, 0), 1000, 40, 10, self.tl),
                       keep=("none", None))
        if res:
            self._select_slot(res[1])

    def _select_slot(self, slot):
        for r in self.timeline.rows:
            if r.key == ("slot", slot) and r.items:
                self.timeline.sel = r.items[0]
                self._selected(r.items[0])
                self.timeline.update()
                return

    def add(self, what, frame, row):
        actor = self._row_actor(row)
        I, W = choreo.ins, choreo.WAIT
        if what.startswith("preset:"):
            key = what.split(":", 1)[1]
            pr = presets.BY_KEY[key]
            vals = {}
            if any(p.kind == "actor" for p in pr.params) and row and row[0] == "actor" and \
                    (row[1] == choreo.CASTER or choreo.is_target(row[1])):
                vals["who"] = row[1]                      # right-clicked on a character's track: done to them
            return self.add_preset(key, vals, frame)
        if what == "effect":
            it = self.library.list.currentItem() if self.library else None
            eid = it.data(Qt.ItemDataRole.UserRole) if it else None
            if eid is None:
                eid, ok = QInputDialog.getInt(self, "Add effect", "Effect number (see the library):", 106, 1, 9999)
                if not ok:
                    return
            return self.drop_effect(int(eid), frame, row)
        if what == "camera":
            lines = [I("cmd_3220", actor, 0, 40, 0, 20, 700, 0)]
        elif what == "shake":
            lines = [I("cmd_32a0", 0, 60, 10)]          # the game's hit shake (12000045 uses 0, 80, 6)
        elif what == "motion":
            m = self.choose_pose(actor)
            if m is None:
                return
            lines = [I("cmd_6510", actor, m, 10)]
        elif what == "flash":
            lines = [I("cmd_6480", actor, 200, 200, 200, 100, 3), script.Ins(W, [8]),
                     I("cmd_6480", actor, 100, 100, 100, 100, 8)]
        elif what == "sound":
            sid = self.choose_sound()
            if sid is None:
                return
            lines = [I("se_play", sid, 100, 500)]
        elif what == "fade":
            lines = [I("screen_fade", 100, 10), script.Ins(W, [20]), I("screen_fade", 0, 10)]
        else:
            return
        self._do([], lambda ops: self.edit.add_layer(frame, lines), keep=("none", None))

    def preset_effect(self):
        """the selected effect clip for the 'Selected effect' presets: {slot, actor, pos} or None"""
        it = self.timeline.sel
        if it is None or isinstance(it, tuple) or it.kind != "clip" or it.slot is None:
            return None
        try:
            slot = int(it.slot)
        except (TypeError, ValueError):
            return None                                  # a slot computed while the skill runs
        show = next((o for o in it.ops if o.cid in choreo.SHOW_CMDS), None)
        if show is None:
            return dict(slot=slot)
        return dict(slot=slot, actor=show.args[1], pos=tuple(int(v) for v in show.args[2:5]))

    def add_preset(self, key, values=None, frame=None):
        """a preset (d5lib/presets.py) as a new layer at the playhead (or frame)"""
        pr = presets.BY_KEY[key]
        ctx = {}
        if pr.needs_effect:
            ctx = self.preset_effect()
            if ctx is None:
                QMessageBox.information(self, "Presets", "Select an effect clip first (click it on the timeline or "
                                                         "in the preview).")
                return
        f = self.frame if frame is None else int(frame)
        try:
            lines = presets.build(key, values or {}, ctx)
        except Exception as e:
            return error_box(self, "Presets", e)
        self._do([], lambda ops: self.edit.add_layer(f, lines), keep=("none", None))
        self.ws.log(f"Added '{pr.name}' at frame {f}")

    # ================================================================== selection
    def _selected(self, sel, quiet=False):
        self.inspector.show_item(sel, self.timeline.multi)
        ops = self._sel_ops(sel)
        if not quiet and not self.playing and ops and ops[0].kind == "sound" and self.sound.isChecked():
            self._mixer_stop()
            self.play_sound(ops[0])
        clip = sel if sel is not None and not isinstance(sel, tuple) and sel.kind == "clip" else None
        if clip is not None and not quiet:
            if not (clip.start <= self.frame < clip.end) and len(self.timeline.multi) <= 1:
                self.set_frame(clip.start + min(8, max(0, clip.end - clip.start - 1)))
            if clip.effect is not None and self.library is not None:
                self.library.select(clip.effect)
        self.view.update()

    def _selection_changed(self, items, quiet=False):
        self.arrange.set_selection(items)
        self.preset_panel.refresh()
        if not quiet or len(items) > 1:
            self.inspector.show_item(self.timeline.sel, items)
        slots = {it.slot for it in items if not isinstance(it, tuple) and it.kind == "clip" and it.slot is not None}
        if self.renderer:
            self.renderer.highlights = slots
            self.renderer.highlight = None            # the preview's gizmo marks the selected effects
        if not quiet and self._live is not None and sorted(self._live["keys"]) != sorted(self.timeline.clip_keys()):
            self.arrange.commit()                 # a new selection keeps what was done to the old one
        self.view.update()

    # ================================================================== live group edits (Arrange tab, gizmo)
    def live_active(self):
        return self._live is not None

    def live_begin(self):
        """start changing the selected clips live: an undo point and the state every change starts from"""
        if self.tl is None:
            return False
        keys = self.timeline.clip_keys()
        if not keys:
            return False
        if self.edit is None:
            if self._make_copy() is None:
                return False
            self.resim()
            self.timeline.select_clip_keys(keys, emit=False)
        self.edit.checkpoint()
        self._live = dict(base=self.edit._snap(), keys=keys, dirty=self.dirty)
        self._update_buttons()
        return True

    def live_update(self, fn):
        """fn(edit, tl, clips) on the starting state; clips = the selected clips of tl (dicts: start, end, effect,
        ops, show, slot, index)"""
        L = self._live
        if L is None:
            return None
        ev, changed = L["base"]
        self.edit.ev = {k: copy.deepcopy(v) for k, v in ev.items()}
        self.edit.changed = set(changed)
        tl = choreo.Simulator(self.events(), self.root, self.ctx).run()
        clips = []
        for slot, i in L["keys"]:
            cs = tl.clips(slot)
            if i < len(cs):
                clips.append(dict(cs[i], slot=slot, index=i))
        try:
            res = fn(self.edit, tl, clips)
        except Exception as e:
            self.status.setText(f"could not apply: {e}")
            res = None
        self.dirty = True
        self.resim()
        self.timeline.select_clip_keys(L["keys"], emit=False)
        self._selection_changed(self.timeline.multi, quiet=True)
        self._refresh_props_later()
        return res

    def live_commit(self):
        if self._live is None:
            return
        self._live = None
        self._update_buttons()
        self._refresh_props_later()

    def _refresh_props_later(self):
        """rebuild the properties a moment after the last change (not on every step of a drag)"""
        t = getattr(self, "_props_timer", None)
        if t is None:
            t = self._props_timer = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda: (setattr(self.inspector, "idents", None),
                                       self.inspector.show_item(self.timeline.sel, self.timeline.multi)))
        t.start(180)

    def live_cancel(self):
        L = self._live
        if L is None:
            return
        self.edit.ev, self.edit.changed = L["base"]
        if self.edit.history:
            self.edit.history.pop()
        self.dirty = L["dirty"]
        self._live = None
        self.resim()
        self.timeline.select_clip_keys(L["keys"], emit=False)
        self._selection_changed(self.timeline.multi, quiet=True)

    def _clip_world(self, scene, c):
        """where a clip's effect is (world) at the editor's frame, or where it is shown"""
        r = self.renderer
        st = scene["slots"].get(c["slot"])
        if st is not None and st.get("effect") == c["effect"] and c["start"] <= self.frame < c["end"]:
            return r.slot_pos(scene, st)
        show = c["show"]
        try:
            return r.actor_pos(scene, choreo.actor_id(show.args[1])) + np.array(show.args[2:5], float)
        except Exception:
            return r.actor_pos(scene, choreo.CASTER)

    def pivot_world(self, scene, clips, pivot):
        r = self.renderer
        if pivot == "target":
            return r.actor_pos(scene, choreo.TARGET)
        if pivot in ("centre", "own") and clips:
            return np.mean([self._clip_world(scene, c) for c in clips], axis=0)
        return r.actor_pos(scene, choreo.CASTER)

    def live_transform(self, p):
        """spread / turn around the pivot, then lift / move, and resize the selected clips"""
        def fn(edit, tl, clips):
            r = self.renderer
            scene = tl.scene(self.frame)
            caster = r.actor_pos(scene, choreo.CASTER)
            pv = self.pivot_world(scene, clips, p["pivot"]) - caster
            refs = fxtools.refs_of([o for c in clips for o in c["ops"]])
            offsets = {choreo.CASTER: np.zeros(3)}
            for rf in refs:
                a = rf.actor
                if a is None or a in offsets or (a == choreo.TARGET and not p["with_target"]):
                    continue
                try:
                    offsets[a] = r.actor_pos(scene, a) - caster
                except Exception:
                    pass
            k = float(p["spread"])
            kv = np.array([k, k if p["spread_y"] else 1.0, k])
            a = math.radians(p["turn"])
            ca, sa = math.cos(a), math.sin(a)

            def rot(v):
                return np.array([v[0] * ca - v[2] * sa, v[1], v[0] * sa + v[2] * ca])
            mv = np.array([p["move"][0], p["lift"], p["move"][2]], float)
            fixed = fxtools.transform(edit, refs, quarter=self._quarter(),
                                      point=lambda q: pv + rot((q - pv) * kv) + mv,
                                      vector=lambda v: rot(v * kv), offsets=offsets)
            if abs(p["size"] - 1.0) > 1e-6:
                fixed += fxtools.resize(edit, [c["show"] for c in clips], p["size"])
            if abs(p.get("roll", 0.0)) > 1e-6:
                fixed += fxtools.roll(edit, tl, clips, -p["roll"])      # rz turns the other way on screen (FLIP_XZ)
            return fixed
        fixed = self.live_update(fn)
        if fixed:
            self.status.setText(f"{fixed} value(s) are inside shared game helpers and stayed as they were")

    def live_path(self, p):
        """new flight paths for the selected clips (d5lib/fxtools.py presets)"""
        preset, params = p["preset"], p["params"]
        to_target = fxtools.targets_target(preset)

        def fn(edit, tl, clips):
            r = self.renderer
            keys = [(c["slot"], c["index"]) for c in clips]

            def fresh(key):
                """the script changes as we go: simulate again so every command is found where it is now"""
                t = choreo.Simulator(self.events(), self.root, self.ctx).run()
                cs = t.clips(key[0])
                return t, (dict(cs[key[1]], slot=key[0], index=key[1]) if key[1] < len(cs) else None)

            def fly_start(c):
                fl = fxtools.flight_of(c["ops"])
                return fl.frame if p["keep"] and to_target and fl is not None else c["start"]
            order = sorted(range(len(clips)), key=lambda i: (fly_start(clips[i]), clips[i]["slot"]))
            n = len(order)
            for rank, i in enumerate(order):
                tl, c = fresh(keys[i])
                if c is None:
                    continue
                fl = fxtools.flight_of(c["ops"])
                if p["keep"] and to_target and fl is not None:
                    start, frames = fl.frame, max(2, int(fl.args[5]))
                    if p.get("length"):
                        # a longer / shorter flight: what follows it in the same script (hit, damage) moves along
                        delta = int(p["length"]) - frames
                        after = [o for o in tl.ops if o.eid == fl.eid and o.chain == fl.chain and o is not fl
                                 and o.frame >= fl.frame + frames]
                        if delta and after:
                            try:
                                edit.move(after, delta, tl)
                            except ValueError:
                                pass
                            tl, c = fresh(keys[i])
                        frames = int(p["length"])
                else:
                    start = max(c["start"], self.frame + rank * p["stagger"])
                    frames = int(p["duration"])
                start = min(start, max(c["start"], c["end"] - 1))
                scene = tl.scene(start)
                caster = r.actor_pos(scene, choreo.CASTER)
                st = scene["slots"].get(c["slot"])
                S = (r.slot_pos(scene, st) if st is not None else self._clip_world(scene, c)) - caster
                E = r.actor_pos(scene, choreo.TARGET) + np.array([0.0, p["aim_y"], 0.0]) - caster
                old = [o for o in fxtools.movement_in(c["ops"], start, start + frames)
                       if (edit.anchor(o, tl) or (None, None))[1] is o.ins]
                if old:
                    edit.delete(old, tl)
                # the game turns script offsets by the skill's facing: the path in the skill's own frame (the same
                # values then fit every facing)
                back = (4 - self._quarter()) % 4
                S_loc, E_loc = turn_offset(S, back), turn_offset(E, back)
                per = {f: (S_loc, E_loc) for f in range(4)}
                body = fxtools.path_event_body(c["slot"], preset, per, rank, n, frames, params, p["ease"],
                                               target_offset=(0, p["aim_y"], 0))
                edit.add_layer_text(start, body)
            return n
        n = self.live_update(fn)
        if n:
            self.status.setText(f"{fxtools.PRESETS[preset][0]} path for {n} effect{'s' if n != 1 else ''} — "
                                f"✔ Keep path keeps it")

    # ---------------------------------------------------------------- gizmo (preview)
    def gizmo_info(self):
        """what the preview's gizmo needs: world positions of the selected effects (and whether they're on screen),
        their flight paths, the selection centre and the pivot"""
        if self.tl is None or self.renderer is None:
            return None
        keys = self.timeline.clip_keys()
        if not keys:
            return None
        scene = self.tl.scene(self.frame)
        clips = []
        for slot, i in keys:
            cs = self.tl.clips(slot)
            if i < len(cs):
                clips.append(dict(cs[i], slot=slot, index=i))
        if not clips:
            return None
        pts = [self._clip_world(scene, c) for c in clips]
        shown = [c["start"] <= self.frame < c["end"] and c["slot"] in scene["slots"] for c in clips]
        return dict(points=pts, shown=shown, centre=np.mean(pts, axis=0), paths=self._paths(clips),
                    pivot=self.pivot_world(scene, clips, self.view.pivot_mode()))

    def _paths(self, clips):
        """world polylines of the selected clips over their time on screen (cached per simulation + selection)"""
        key = (id(self.tl), tuple((c["slot"], c["index"]) for c in clips), self.dist.value(), self.facing.currentIndex())
        cache = getattr(self, "_path_cache", None)
        if cache and cache[0] == key:
            return cache[1]
        r = self.renderer
        f0 = min(c["start"] for c in clips)
        f1 = min(self.tl.length, max(c["end"] for c in clips))
        step = max(1, (f1 - f0) // 120)
        paths = [[] for _ in clips]
        for f in range(f0, f1 + 1, step):
            sc = self.tl.scene(f)
            for k, c in enumerate(clips):
                st = sc["slots"].get(c["slot"])
                if st is not None and c["start"] <= f < c["end"] and st.get("effect") == c["effect"]:
                    try:
                        paths[k].append(r.slot_pos(sc, st))
                    except Exception:
                        pass
        self._path_cache = (key, paths)
        return paths

    def live_formation(self, p):
        """put the selected effects' start places into a formation (each effect's whole path moves along)"""
        def fn(edit, tl, clips):
            r = self.renderer
            scene = tl.scene(self.frame)
            caster = r.actor_pos(scene, choreo.CASTER)
            pv = self.pivot_world(scene, clips, p["pivot"]) - caster
            fixed = 0
            n = len(clips)
            rng = np.random.default_rng(int(p.get("seed", 1)))
            order = sorted(range(n), key=lambda i: (clips[i]["start"], clips[i]["slot"]))
            tgt = r.actor_pos(scene, choreo.TARGET) - caster
            fwd = np.array([tgt[0], 0.0, tgt[2]])
            fwd = fwd / np.linalg.norm(fwd) if np.linalg.norm(fwd) > 1e-6 else np.array([1.0, 0.0, 0.0])
            side = np.array([-fwd[2], 0.0, fwd[0]])
            for rank, i in enumerate(order):
                c = clips[i]
                cur = self._clip_world(scene, c) - caster
                kind = p["shape"]
                if kind == "circle":
                    a = 2 * math.pi * rank / max(1, n) + math.radians(p["angle"])
                    want = np.array([pv[0] + p["radius"] * math.cos(a), p["height"], pv[2] + p["radius"] * math.sin(a)])
                elif kind == "arc":
                    span = math.radians(p["spread_deg"])
                    a = -span / 2 + span * rank / max(1, n - 1)
                    d = fwd * math.cos(a) + side * math.sin(a)
                    want = np.array([pv[0], 0.0, pv[2]]) + d * p["radius"] + np.array([0.0, p["height"], 0.0])
                elif kind == "line":
                    off = (rank - (n - 1) / 2.0) * p["spacing"]
                    want = np.array([pv[0], 0.0, pv[2]]) + side * off + np.array([0.0, p["height"], 0.0])
                else:                                               # scatter
                    v = rng.uniform(-1, 1, 3) * np.array([p["radius"], p["radius"] * 0.4, p["radius"]])
                    want = np.array([pv[0], 0.0, pv[2]]) + v + np.array([0.0, p["height"], 0.0])
                d = want - cur
                refs = [rf for rf in fxtools.refs_of(c["ops"]) if rf.actor != choreo.TARGET]
                offsets = {choreo.CASTER: np.zeros(3)}
                for rf in refs:
                    if rf.actor is not None and rf.actor not in offsets:
                        try:
                            offsets[rf.actor] = r.actor_pos(scene, rf.actor) - caster
                        except Exception:
                            pass
                fixed += fxtools.move(edit, refs, d, offsets=offsets, quarter=self._quarter())
            return fixed
        fixed = self.live_update(fn)
        if fixed:
            self.status.setText(f"{fixed} value(s) are inside shared game helpers and stayed as they were")

    def _gizmo_start(self):
        if self.arrange.mode is not None:
            self.arrange.commit()
        if not self.live_active() and not self.live_begin():
            self._gizmo = None
            return
        self._gizmo = dict(move=np.zeros(3), spread=1.0, turn=0.0, roll=0.0, size=1.0)

    def _gizmo_drag(self, kind, value):
        g = getattr(self, "_gizmo", None)
        if g is None:
            return
        if kind == "both":
            g["spread"] = g["size"] = value
        else:
            g[kind] = value
        now = time.perf_counter()
        if now - self._live_t >= 0.04:
            self._live_t = now
            self._apply_gizmo()

    def _apply_gizmo(self):
        g = self._gizmo
        self.live_transform(dict(pivot=self.view.pivot_mode(), spread=g["spread"], spread_y=False,
                                 turn=g["turn"], roll=g["roll"], lift=g["move"][1],
                                 move=(g["move"][0], 0.0, g["move"][2]), size=g["size"],
                                 with_target=self.arrange.with_target.isChecked()))

    def _gizmo_end(self):
        if getattr(self, "_gizmo", None) is None:
            return
        self._apply_gizmo()
        self.live_commit()
        self._gizmo = None

    def _gizmo_cancel(self):
        if getattr(self, "_gizmo", None) is None:
            return
        self._gizmo = None
        self.live_cancel()

    # ================================================================== properties panel actions
    def _thumb(self, eid):
        cache = self.__dict__.setdefault("_thumbs", {})
        if eid not in cache:
            from PyQt6.QtGui import QPixmap
            from .library import render_thumb
            try:
                cache[eid] = QPixmap.fromImage(render_thumb(self.fx, eid, None, 96))
            except Exception:
                cache[eid] = None
        return cache[eid]

    def delete_ops(self, ops):
        if ops:
            self._do(list(ops), lambda ops: self.edit.delete(ops, self.tl))

    def move_clip(self, item, d):
        """move a whole effect (its show and every move it makes, except landings on the target) by d"""
        d = np.asarray(d, float)
        scene = self.tl.scene(self.frame) if self.tl else None

        def fn(ops):
            refs = [r for r in fxtools.refs_of(ops) if r.actor != choreo.TARGET]
            offsets = {choreo.CASTER: np.zeros(3)}
            if scene is not None and self.renderer is not None:
                caster = self.renderer.actor_pos(scene, choreo.CASTER)
                for r in refs:
                    if r.actor is not None and r.actor not in offsets:
                        try:
                            offsets[r.actor] = self.renderer.actor_pos(scene, r.actor) - caster
                        except Exception:
                            pass
            return fxtools.move(self.edit, refs, d, offsets=offsets, quarter=self._quarter())
        self._do(list(item.ops), fn)

    # ================================================================== choosing by sight / by ear
    def sprite_of(self, actor):
        """the sprite number the preview shows for an actor (caster, targets, or whatever the skill made it)"""
        r = self.renderer
        if r is None:
            return None
        a = choreo.actor_id(actor)
        if a == choreo.CASTER:
            return r.caster_sprite
        if choreo.is_target(a):
            return r.target_sprite
        try:
            st = r.stage_at(self.tl.scene(self.frame)) if self.tl is not None else None
            ac = st.actors.get(a) if st is not None else None
            return ac.sprite if ac is not None and ac.sprite else r.caster_sprite
        except Exception:
            return r.caster_sprite

    def model_queues(self, eid):
        """the draw queues the parts of effect eid go into by themselves (mesh layer byte + 2)"""
        try:
            m = self.renderer.assets.model(eid)
            return {g.flags[1] + 2 for part in m.parts for g in part if len(g.flags) > 1} if m else set()
        except Exception:
            return set()

    def _poses_of(self, actor):
        num = self.sprite_of(actor)
        if not num:
            return num, list(self.inspector.motions)
        a, ids = self.renderer.spr.file(num)
        out = []
        for aid in sorted(ids):
            if aid % 10 == 1:
                m = aid // 10
                name = MOTION_NAMES.get(m, "")
                out.append((f"{name} ({m})" if name else f"pose {m}", m))
        return num, out

    def choose_pose(self, actor, current=None):
        """the pose picker (animated pictures of every pose of that character) -> pose number or None"""
        from .pickers import PosePicker
        num, poses = self._poses_of(actor)
        if not poses:
            return None
        if not num or self.thumbs is None:
            label, ok = QInputDialog.getItem(self, "Pose", "Pose:", [l for l, _ in poses], 0, False)
            return dict(poses)[label] if ok else None
        dlg = PosePicker(self, self.thumbs, num, poses, current, choreo.who(actor))
        return dlg.value() if dlg.exec() else None

    def pick_pose(self, op):
        m = self.choose_pose(op.args[0], op.args[1])
        if m is not None and m != op.args[1]:
            self.set_value(op, 1, m)

    def _sound_users(self):
        """{sound effect: [skill names]} from the vanilla skills' scripts (made once)"""
        if getattr(self, "_sfx_users", None) is not None:
            return self._sfx_users
        out = {}
        try:
            sc = skills.vanilla_scripts(self.ws.fs)
            names = dict(getattr(self.page, "names", None) or {})
            for sid, name in names.items():
                root = sc.root_of(sid)
                if not root:
                    continue
                for eid in sc.tree(root):
                    e = sc.ev.get(eid)
                    if e is None:
                        continue
                    for i in e.code:
                        if i.cid in (0x4610, 0x4612) and i.args and isinstance(i.args[0], int):
                            lst = out.setdefault(int(i.args[0]), [])
                            if name not in lst:
                                lst.append(name)
        except Exception:
            pass
        self._sfx_users = out
        return out

    def choose_sound(self, current=None):
        """the sound picker (waveforms, the skills that use each, click to hear) -> sound number or None"""
        from .pickers import SoundPicker
        self._audio()
        if self.thumbs is None or self.sebank is None or self.sebank.pack is None:
            sid, ok = QInputDialog.getInt(self, "Sound", "Sound effect number (Sound_SE):", current or 350, 0, 9999)
            return sid if ok else None
        self.inspector.sound_bank = self.sebank
        dlg = SoundPicker(self, self.thumbs, self.sebank, self._sound_users(), current)
        dlg.play.connect(lambda sid: (self._mixer_stop(), self.play_sound(choreo_sound(sid))))
        sid = dlg.value() if dlg.exec() else None
        self._mixer_stop()
        return sid

    def pick_sound(self, op):
        sid = self.choose_sound(op.args[0] if op.args else None)
        if sid is not None and op.args and sid != op.args[0]:
            self.set_value(op, 0, sid)

    def put_at_show(self, show, existing, name, args):
        """a drawing / turn setting of an effect where it is shown (Properties → Drawing / Transform)"""
        res = self._do([show] + list(existing),
                       lambda ops: fxtools.put_at_show(self.edit, self.tl, ops[0], ops[1:], name, args))
        if res:
            self.status.setText("this effect is shown inside a shared game helper: that setting can't be added "
                                "here")

    def timeline_icon(self, item):
        """a small picture for a timeline item: the effect, the pose (cached: the timeline asks on every paint)"""
        r = self.renderer
        try:
            if item.kind == "clip" and item.effect is not None:
                key = ("fx", item.effect)
            elif item.kind == "motion" and self.thumbs is not None and item.ops:
                op = item.ops[0]
                key = ("pose", choreo.actor_id(op.args[0]), op.args[1], r.caster_sprite if r else None,
                       r.target_sprite if r else None)
            else:
                return None
        except Exception:
            return None
        cache = self.__dict__.setdefault("_tl_icons", {})
        if key not in cache:
            try:
                if key[0] == "fx":
                    cache[key] = self._thumb(item.effect)
                else:
                    num = self.sprite_of(key[1])
                    cache[key] = self.thumbs.pose_icon(num, key[2], size=40) if num else None
            except Exception:
                cache[key] = None
        return cache[key]

    def pick_effect(self, load_op):
        cur = load_op.args[1] if len(load_op.args) > 1 else None
        dlg = EffectPicker(self, self.fx, self.names, cur)
        if dlg.exec() and dlg.value() is not None:
            self.set_value(load_op, 1, dlg.value())

    def _props_action(self, act):
        if act == "delete":
            self.delete_selected()
        elif act == "duplicate":
            self.duplicate(self.selected_clip_items(), 0)
        elif act == "arrange":
            self.tabs.setCurrentWidget(self.arrange)
        elif act == "frame":
            self.view.frame_selected()

    # ================================================================== viewport / timeline actions
    def _clip_key_at(self, slot, frame=None):
        """(slot, clip index) of the clip of `slot` on screen at `frame` (else the nearest one), or None"""
        if self.tl is None:
            return None
        f = self.frame if frame is None else frame
        cs = self.tl.clips(slot)
        if not cs:
            return None
        for i, c in enumerate(cs):
            if c["start"] <= f < c["end"]:
                return (slot, i)
        return (slot, min(range(len(cs)), key=lambda i: min(abs(cs[i]["start"] - f), abs(cs[i]["end"] - f))))

    def _pick(self, slots, mode):
        keys = [k for k in (self._clip_key_at(s) for s in slots) if k is not None]
        if mode == "replace":
            self.timeline.select_clip_keys(keys)
        elif mode == "add":
            self.timeline.select_clip_keys(keys, add=True)
        else:                                               # toggle
            cur = self.timeline.clip_keys()
            want = [k for k in cur if k not in keys] + [k for k in keys if k not in cur]
            self.timeline.select_clip_keys(want)
        if keys and self.tabs.currentWidget() is self.lib_holder:
            self.tabs.setCurrentWidget(self.inspector)

    def _select_all_on_screen(self, on):
        if not on or self.tl is None:
            return self.timeline.clear_selection()
        scene = self.tl.scene(self.frame)
        self._pick(sorted(scene["slots"]), "replace")

    def selected_clip_items(self):
        return [it for it in self.timeline.multi if not isinstance(it, tuple) and it.kind == "clip"]

    def delete_selected(self):
        items = self.selected_clip_items()
        if items:
            self.delete(items)
            self.status.setText(f"deleted {len(items)} effect{'s' if len(items) != 1 else ''} (Ctrl+Z brings "
                                f"{'them' if len(items) != 1 else 'it'} back)")

    def _copy_lines(self, items):
        """[(start frame, lines with slot placeholder)] of clips, values as they run"""
        out = []
        for it in items:
            if it.kind != "clip":
                continue
            t0, lines = fxtools.duplicate_lines(it.ops, 0)
            out.append((t0, lines))
        return out

    def copy(self, items):
        self._clipboard = self._copy_lines(items)
        if self._clipboard:
            self.status.setText(f"copied {len(self._clipboard)} effect{'s' if len(self._clipboard) != 1 else ''} — "
                                f"Ctrl+V pastes at the playhead (in this or another skill)")

    def _add_copies(self, entries, dframe, offset=(0, 0, 0)):
        """layers for copied clips -> their new clip keys"""
        new_keys = []

        def fn(ops):
            for t0, lines in entries:
                slot = self.edit.free_slot(self.tl)
                ls = []
                for i in lines:
                    a = list(i.args)
                    if i.cid != choreo.WAIT and a:
                        a[0] = slot
                        if (i.cid in fxtools.SHOW or i.cid in fxtools.FLY) and \
                                choreo.actor_id(a[1]) != choreo.TARGET and any(offset):
                            for k in range(3):
                                a[2 + k] = int(a[2 + k]) + int(round(offset[k]))
                    ls.append(script.Ins(i.cid, a))
                self.edit.add_layer(max(0, t0 + dframe), ls)
                new_keys.append((slot, 0))
        self._do([], fn, keep=("none", None))
        if new_keys:
            self.timeline.select_clip_keys(new_keys)
        return new_keys

    def paste(self, frame):
        cb = getattr(self, "_clipboard", None)
        if not cb:
            return self.status.setText("nothing copied yet (select effects, Ctrl+C)")
        t0 = min(t for t, _ in cb)
        self._add_copies(cb, frame - t0)

    def duplicate(self, items, dframe=0, then_move=False):
        entries = self._copy_lines(items)
        if not entries:
            return
        keys = self._add_copies(entries, dframe)
        if keys:
            self.status.setText(f"duplicated {len(keys)} effect{'s' if len(keys) != 1 else ''}")
            if then_move:
                self.view.start_modal("move")

    def trim(self, item, delta):
        """change when a clip ends: move its 'disappears' command"""
        rem = [o for o in item.ops if o.cid == 0x3c02]
        if not rem or not delta:
            return
        self._do([rem[-1]], lambda ops: self.edit.move(ops, delta, self.tl))

    def delete_track(self, row):
        ops = [o for it in row.items for o in (it.ops if not isinstance(it, tuple) else [it[2]])]
        if not ops:
            return
        self._do(ops, lambda ops: self.edit.delete(ops, self.tl), keep=("none", None))
        self.timeline.clear_selection()
        self.status.setText(f"deleted the track “{row.title}” (Ctrl+Z brings it back)")

    def hide_track(self, row, hidden):
        if row.key[0] == "slot" and self.renderer is not None:
            (self.renderer.hidden_slots.add if hidden else self.renderer.hidden_slots.discard)(row.key[1])
            self.view.update()

    def _view_menu(self, gpos, slot):
        from PyQt6.QtWidgets import QMenu
        if slot is not None:
            key = self._clip_key_at(slot)
            if key is not None and key not in self.timeline.clip_keys():
                self.timeline.select_clip_keys([key])
        items = self.selected_clip_items()
        m = QMenu(self)
        if items:
            n = len(items)
            m.addAction(f"🗑  Delete{f' {n} effects' if n > 1 else ''}\tDel", self.delete_selected)
            m.addAction(f"⧉  Duplicate\tShift+D", lambda: self.duplicate(items, 0, then_move=True))
            m.addAction("📋  Copy\tCtrl+C", lambda: self.copy(items))
            m.addSeparator()
            m.addAction("✥  Move\tG", lambda: self.view.start_modal("move"))
            m.addAction("⟳  Rotate\tR", lambda: self.view.start_modal("rotate"))
            m.addAction("⤡  Scale\tS", lambda: self.view.start_modal("scale"))
            m.addSeparator()
            m.addAction("🔁  Select all with this effect", self.timeline.select_similar)
            m.addAction("⌖  Frame the selection\tF", self.view.frame_selected)
            m.addAction("✏  Properties", lambda: self.tabs.setCurrentWidget(self.inspector))
            m.addAction("🎯  Group tools && paths", lambda: self.tabs.setCurrentWidget(self.arrange))
        m.addAction(f"📋  Paste at frame {self.frame}\tCtrl+V", lambda: self.paste(self.frame))
        m.addAction("✨  Add an effect here…", lambda: self.tabs.setCurrentWidget(self.lib_holder))
        m.exec(gpos)

    def _sync_pivot(self, key):
        for cb in (self.view.pivot, self.arrange.pivot):
            k = cb.findData(key)
            if k >= 0 and cb.currentIndex() != k:
                cb.blockSignals(True)
                cb.setCurrentIndex(k)
                cb.blockSignals(False)
        self.view.update()

    # ================================================================== undo / save
    def undo(self):
        if self.edit and self.edit.undo():
            self.dirty = True
            self.resim()

    def redo(self):
        if self.edit and self.edit.redo():
            self.dirty = True
            self.resim()

    def _update_buttons(self):
        e = self.edit
        self.undo_btn.setEnabled(bool(e and e.history))
        self.redo_btn.setEnabled(bool(e and e.future))
        self.save_btn.setEnabled(bool(e and self.dirty))
        self.save_btn.setText("💾 Save*" if self.dirty else "💾 Save")

    def save(self):
        if not self.edit or not self.dirty:
            return True
        mod = self.mod or self.ws.active_mod
        try:
            texts = self.edit.events_text()
            for eid, text in texts.items():
                skills.set_event(mod, eid, text)
            d = skills.load(mod)
            gone = [k for k in d["events"] if self.root <= int(k) < self.root + 1000 and int(k) not in self.edit.ev]
            for k in gone:
                d["events"].pop(k)
            if gone:
                skills.save(mod, d)
        except Exception as e:
            error_box(self, "Save", e)
            return False
        self.dirty = False
        self.edit.changed.clear()
        self.page.reload_quiet()
        self.sc = self.page.sc
        self.edit.base = self.sc.ev
        self.page._show(self.skill, editor=False)
        self.ws.file_changed.emit(skills.SCRIPT)
        self.status.setText(f"saved {len(texts)} event{'s' if len(texts) != 1 else ''} into {mod.name}")
        self._update_buttons()
        return True

    def preview_in_game(self):
        if self.dirty and not self.save():
            return
        self.page.preview()

    def hideEvent(self, e):
        if self.playing:
            self.toggle_play()
        super().hideEvent(e)


class _SoundOp:
    """just enough of a choreo Op for play_sound: a se_play of sound sid"""

    def __init__(self, sid):
        self.cid, self.args, self.kind = 0x4610, [int(sid), 100, 500], "sound"


def choreo_sound(sid):
    return _SoundOp(sid)
