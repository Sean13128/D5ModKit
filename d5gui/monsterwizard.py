"""New monster class from a Disgaea RPG monster, step by step (d5lib.monstermap, newclasses.create_monster).

1. the Disgaea RPG monster (its poses come from your Disgaea RPG folder; ten of them D5 doesn't have at all);
2. whose animations it moves with: a D5 monster class, the most similar build first (its D5 twin, then the stand
   height);
3. its poses: the kit guesses which drawing is the stand, the walk, the hit, the jump, the attack ... from the
   template's own poses; you check them one by one (click a pose, pick its role) -- Preview shows every template
   pose next to the drawing it gets;
4. Create: a mod of its own with the class (6 ranks, hired at the Netherworld registrar), its sprite drawn from the
   poses, and the role file kept (patches/monsters/roles_<uid>.json) so it can be made again the same way.
"""
import json
import os

import numpy as np
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget, QProgressDialog)

from d5lib import monstermap
from .common import Worker, error_box, info_box

ROLE = Qt.ItemDataRole.UserRole
ROLES = [("stand", "Stand (the neutral pose: the first idle drawing)"), ("walk", "Walk"), ("hit", "Hit (flinch)"),
         ("crouch", "Crouch (jump / lift take-off)"), ("jump", "Jump"), ("attack", "Attack"),
         ("other", "Other (used where nothing else fits)"), ("unused", "Not used (e.g. a white flash frame)")]
ROLE_TAG = {"stand": "STAND", "walk": "WALK", "hit": "HIT", "crouch": "CROUCH", "jump": "JUMP", "attack": "ATK",
            "other": "", "unused": "✖"}
THUMB = 96


def _pixmap(img, size=THUMB):
    a = np.ascontiguousarray(img)
    h, w = a.shape[:2]
    q = QImage(a.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(q.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))


class MonsterWizard(QDialog):
    def __init__(self, page, class_names):
        super().__init__(page)
        self.page = page
        self.ws = page.ws
        self.names = class_names                 # {class id: name}
        self.uid = None
        self.regs = {}                           # the new monster's poses (front sheet)
        self.roles = {}                          # {region key (int): role}
        self.order = {}                          # {region key: place in its sequence role}
        self.setWindowTitle("New monster class")
        self.resize(1250, 820)
        lay = QVBoxLayout(self)
        intro = QLabel("A new recruitable monster class drawn from a Disgaea RPG monster. Pick the monster, whose "
                       "moves it uses, and check the poses the kit chose for it (click a pose, then its role). "
                       "Preview shows every pose of the template next to the drawing it gets.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)
        split = QSplitter()
        # 1. the monster
        left = QGroupBox("1 · The Disgaea RPG monster")
        ll = QVBoxLayout(left)
        self.mlist = QListWidget()
        self.mlist.setIconSize(QSize(56, 56))
        self.mlist.currentItemChanged.connect(self._monster_picked)
        ll.addWidget(self.mlist, 1)
        self.mnote = QLabel("Looking for Disgaea RPG monsters in your Disgaea RPG folder…")
        self.mnote.setWordWrap(True)
        self.mnote.setObjectName("muted")
        ll.addWidget(self.mnote)
        split.addWidget(left)
        # 2. template + names, 3. poses
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("2 · Moves like, and its names")
        f = QFormLayout(box)
        self.template = QComboBox()
        self.template.setToolTip("The D5 monster whose animations, skills and choreography it gets. A similar "
                                 "build works best: its D5 twin, or a monster of about the same height.")
        self.template.currentIndexChanged.connect(self._template_changed)
        f.addRow("Moves like", self.template)
        self.name = QLineEdit()
        f.addRow("Class name", self.name)
        self.titles = QLineEdit()
        self.titles.setPlaceholderText("six rank names, comma-separated (empty: the class name six times)")
        f.addRow("Rank names", self.titles)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("the line the registrar shows")
        f.addRow("Description", self.desc)
        ml.addWidget(box)
        pbox = QGroupBox("3 · Its poses (front; the back and wait sheets follow the same layout)")
        pl = QVBoxLayout(pbox)
        self.poses = QListWidget()
        self.poses.setViewMode(QListView.ViewMode.IconMode)
        self.poses.setIconSize(QSize(THUMB, THUMB))
        self.poses.setResizeMode(QListView.ResizeMode.Adjust)
        self.poses.setMovement(QListView.Movement.Static)
        self.poses.setSpacing(6)
        self.poses.setWordWrap(True)
        self.poses.currentItemChanged.connect(self._pose_picked)
        pl.addWidget(self.poses, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("This pose is"))
        self.role = QComboBox()
        for k, lab in ROLES:
            self.role.addItem(lab, k)
        self.role.activated.connect(self._role_set)
        row.addWidget(self.role, 1)
        row.addWidget(QLabel("step"))
        self.step = QSpinBox()
        self.step.setRange(1, 12)
        self.step.setToolTip("Its place in the walk / jump / attack (1 = first)")
        self.step.valueChanged.connect(self._step_set)
        row.addWidget(self.step)
        b = QPushButton("Guess again")
        b.setToolTip("The kit's guess from the template's poses (your choices are replaced)")
        b.clicked.connect(self._guess)
        row.addWidget(b)
        pl.addLayout(row)
        self.rsum = QLabel()
        self.rsum.setWordWrap(True)
        self.rsum.setObjectName("muted")
        pl.addWidget(self.rsum)
        ml.addWidget(pbox, 1)
        split.addWidget(mid)
        # 4. preview
        right = QGroupBox("4 · Preview: template pose → its new drawing")
        rl = QVBoxLayout(right)
        self.b_prev = QPushButton("🔍 Preview the pairing")
        self.b_prev.clicked.connect(self._preview)
        rl.addWidget(self.b_prev)
        self.prev_area = QScrollArea()
        self.prev_area.setWidgetResizable(True)
        self.prev_img = QLabel("Preview shows here.")
        self.prev_img.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.prev_area.setWidget(self.prev_img)
        rl.addWidget(self.prev_area, 1)
        split.addWidget(right)
        split.setSizes([330, 540, 380])
        lay.addWidget(split, 1)
        bb = QDialogButtonBox()
        self.b_create = bb.addButton("🐉 Create the monster class", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._create)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.result_mod = None
        self._load_monsters()

    # ---------------------------------------------------------------- 1. monsters
    def _load_monsters(self):
        from d5lib import drpgsource
        chosen = self.ws.settings.get(drpgsource.SETTING)

        def work():
            with drpgsource.using(chosen):
                out = []
                for uid, name, twin in monstermap.drpg_monsters():
                    regs = monstermap.regions(uid)
                    front = monstermap.grid_order([k for k in regs if k[0] == "front"])
                    out.append((uid, name, twin, regs[front[0]]["img"] if front else None))
                return out
        self._mw = w = Worker(work)
        w.done.connect(self._monsters_ready)
        w.failed.connect(lambda msg: self.mnote.setText(f"Couldn't read the Disgaea RPG monsters: {msg[-300:]}"))
        w.start()

    def _monsters_ready(self, items):
        self.mlist.clear()
        for uid, name, twin, img in items:
            label = (f"{name}  ·  new to D5" if name else
                     f"{self.names.get(twin, f'class {twin}')} (Disgaea RPG look)") + f"\nunit {uid}"
            it = QListWidgetItem(label)
            if img is not None:
                it.setIcon(QIcon(_pixmap(img, 56)))
            it.setData(ROLE, uid)
            self.mlist.addItem(it)
        self.mnote.setText(f"{len(items)} Disgaea RPG monsters found. The ones 'new to D5' have no D5 class yet; "
                           "the others give a D5 monster a Disgaea RPG look as a class of its own.")
        if not items:
            self.mnote.setText("No Disgaea RPG monster sheets found: set your Disgaea RPG folder on the Characters "
                               "page (New character › Look › Disgaea RPG sprites).")

    def _monster_picked(self, it, prev=None):
        if it is None:
            return
        self.uid = it.data(ROLE)
        name = monstermap.NEW.get(self.uid)
        if name and not self.name.text():
            self.name.setText(name)
        from d5lib import drpgsource
        chosen = self.ws.settings.get(drpgsource.SETTING)
        fs = self.ws.fs
        uid = self.uid
        self.template.blockSignals(True)
        self.template.clear()
        self.template.addItem("(finding similar monsters…)", None)
        self.template.blockSignals(False)

        def work():
            with drpgsource.using(chosen):
                regs = monstermap.regions(uid)
                rec, h = monstermap.recommend_templates(fs, uid)
            return uid, regs, rec, h
        self._tw = w = Worker(work)
        w.done.connect(self._templates_ready)
        w.failed.connect(lambda msg: error_box(self, "New monster", msg))
        w.start()

    def _templates_ready(self, r):
        uid, regs, rec, h = r
        if uid != self.uid:
            return
        self.regs = {k: v for k, v in regs.items() if k[0] == "front"}
        self.template.blockSignals(True)
        self.template.clear()
        for i, (cls, th) in enumerate(rec):
            self.template.addItem(f"{self.names.get(cls, cls)}  ·  {th} px tall" + ("  (recommended)" if i == 0 else ""),
                                  cls)
        self.template.blockSignals(False)
        self.template.setToolTip(f"The new monster stands {h} px tall in its Disgaea RPG drawing; the closest "
                                 "builds come first.")
        self._fill_poses()
        self._guess()

    # ---------------------------------------------------------------- 3. poses
    def _template_changed(self, *_):
        if self.uid is not None and self.template.currentData() is not None:
            self._guess()

    def _fill_poses(self):
        self.poses.clear()
        for k in monstermap.grid_order(list(self.regs)):
            it = QListWidgetItem(QIcon(_pixmap(self.regs[k]["img"])), str(k[2]))
            it.setData(ROLE, k[2])
            self.poses.addItem(it)

    def _guess(self):
        cls = self.template.currentData()
        if self.uid is None or cls is None:
            return
        from d5lib import drpgsource
        chosen = self.ws.settings.get(drpgsource.SETTING)
        fs, uid = self.ws.fs, self.uid
        self.rsum.setText("Guessing the poses from the template's…")

        def work():
            with drpgsource.using(chosen):
                return uid, cls, monstermap.auto_roles(fs, cls, uid)
        self._gw = w = Worker(work)
        w.done.connect(self._guessed)
        w.failed.connect(lambda msg: self.rsum.setText(f"Couldn't guess: {msg[-300:]}"))
        w.start()

    def _guessed(self, r):
        uid, cls, roles = r
        if uid != self.uid or cls != self.template.currentData():
            return
        self.roles, self.order = {}, {}
        for role, v in roles["front"].items():
            for i, k in enumerate(v if isinstance(v, list) else [v]):
                self.roles[int(k)] = role
                self.order[int(k)] = i
        for k in roles.get("_flash", []):
            self.roles[int(k)] = "unused"
        self._labels()

    def _labels(self):
        for i in range(self.poses.count()):
            it = self.poses.item(i)
            k = it.data(ROLE)
            role = self.roles.get(k, "other")
            tag = ROLE_TAG.get(role, "")
            if role in monstermap.SEQ_ROLES:
                tag += f" {self.order.get(k, 0) + 1}"
            it.setText(f"{k}\n{tag}" if tag else str(k))
        parts = []
        for role, lab in ROLES[:6]:
            ks = sorted((k for k, r in self.roles.items() if r == role), key=lambda k: self.order.get(k, 0))
            parts.append(f"{lab.split(' (')[0]}: {', '.join(map(str, ks)) or '—'}")
        missing = [lab.split(" (")[0] for role, lab in ROLES[:3] if role not in self.roles.values()]
        self.rsum.setText(" · ".join(parts) + (f"   ⚠ no {', '.join(missing)} yet" if missing else ""))

    def _pose_picked(self, it, prev=None):
        if it is None:
            return
        k = it.data(ROLE)
        role = self.roles.get(k, "other")
        self.role.setCurrentIndex(max(0, self.role.findData(role)))
        self.step.blockSignals(True)
        self.step.setValue(self.order.get(k, 0) + 1)
        self.step.setEnabled(role in monstermap.SEQ_ROLES)
        self.step.blockSignals(False)

    def _role_set(self, *_):
        it = self.poses.currentItem()
        if it is None:
            return
        k, role = it.data(ROLE), self.role.currentData()
        if role in ("stand", "hit", "crouch"):                 # one pose each
            for kk, r in list(self.roles.items()):
                if r == role and kk != k:
                    self.roles[kk] = "other"
        if role in monstermap.SEQ_ROLES and self.roles.get(k) != role:
            self.order[k] = sum(1 for r in self.roles.values() if r == role)
        self.roles[k] = role
        self._pose_picked(it)
        self._labels()

    def _step_set(self, v):
        it = self.poses.currentItem()
        if it is not None:
            self.order[it.data(ROLE)] = v - 1
            self._labels()

    def role_file(self):
        """the role file of the choices (monstermap.load_roles format)"""
        front = {}
        for role in monstermap.FRONT_ROLES:
            ks = sorted((k for k, r in self.roles.items() if r == role), key=lambda k: self.order.get(k, 0))
            if not ks:
                continue
            front[role] = ks if role in monstermap.SEQ_ROLES else ks[0]
        front["other"] = [k for k, r in self.roles.items() if r == "other"]
        known = set(self.roles)
        front["other"] += [k[2] for k in self.regs if k[2] not in known]
        return {"_about": f"made with the kit's monster wizard (template {self.template.currentData()})",
                "front": front, "back": "grid", "wait_front": "grid", "wait_back": "grid"}

    # ---------------------------------------------------------------- 4. preview / create
    def _pairs_work(self):
        from d5lib import drpgsource
        chosen = self.ws.settings.get(drpgsource.SETTING)
        fs, uid, cls, roles = self.ws.fs, self.uid, self.template.currentData(), self.role_file()
        return chosen, fs, uid, cls, roles

    def _preview(self):
        if self.uid is None or self.template.currentData() is None:
            return
        chosen, fs, uid, cls, roles = self._pairs_work()
        import tempfile
        path = os.path.join(tempfile.gettempdir(), f"d5_monster_{uid}_{cls}.png")
        self.b_prev.setEnabled(False)
        self.prev_img.setText("Pairing the poses…")

        def work():
            from d5lib import drpgsource
            with drpgsource.using(chosen):
                pairs = monstermap.pairs_from_roles(fs, cls, uid, roles)
                monstermap.pose_sheet(fs, cls, uid, pairs, path)
            return path, len(pairs)
        self._pw = w = Worker(work)

        def done(r):
            self.b_prev.setEnabled(True)
            p, n = r
            self.prev_img.setPixmap(QPixmap(p))
            self.prev_img.setToolTip(f"{n} template poses, each with the drawing it gets")
        w.done.connect(done)
        w.failed.connect(lambda msg: (self.b_prev.setEnabled(True), error_box(self, "Preview", msg)))
        w.start()

    def _create(self):
        if self.uid is None or self.template.currentData() is None:
            QMessageBox.information(self, "New monster", "Pick the Disgaea RPG monster first.")
            return
        name = self.name.text().strip()
        if not name:
            QMessageBox.information(self, "New monster", "Give the class a name.")
            return
        if "stand" not in self.roles.values():
            QMessageBox.information(self, "New monster", "Choose its stand pose (click a pose, then 'Stand').")
            return
        titles = [t.strip() for t in self.titles.text().split(",") if t.strip()]
        titles = (titles + [titles[-1]] * 6)[:6] if titles else None
        chosen, fs, uid, cls, roles = self._pairs_work()
        mm = self.ws.mods
        log = self.ws.log
        desc = self.desc.text().strip()
        from d5lib import newclasses
        family = None
        for m in mm.all_mods():                  # a class of this monster made before: redraw it, same class ids
            for spec in newclasses.load_specs(m):
                if int(spec.get("drpg") or 0) == int(uid):
                    r = QMessageBox.question(
                        self, "New monster class",
                        f"'{m.name}' has a class of this monster already (class ids {spec['family']}-"
                        f"{int(spec['family']) + 5}). Redraw that class with these poses? (No: make another class.)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                        QMessageBox.StandardButton.Cancel)
                    if r == QMessageBox.StandardButton.Cancel:
                        return
                    if r == QMessageBox.StandardButton.Yes:
                        family = int(spec["family"])
                        name = spec.get("name") or name      # (the same mod: it is found by the class's name)
                    break
            if family is not None:
                break

        def work():
            from d5lib import drpgsource, newclasses
            with drpgsource.using(chosen):
                pairs = monstermap.pairs_from_roles(fs, cls, uid, roles)
                mod = newclasses.create_monster(fs, mm, uid, cls, name, pairs, family=family, titles=titles,
                                                hire_desc=desc, log=log)
            mod.save_patch("monsters", f"roles_{uid}.json", roles)
            fam = max(s["family"] for s in newclasses.load_specs(mod))
            return mod, fam
        prog = QProgressDialog(f"Drawing the monster class '{name}' from Disgaea RPG unit {uid} on "
                               f"{self.names.get(cls, cls)}'s animations…\n(a minute or two; the log shows the steps)",
                               None, 0, 0, self)
        prog.setWindowTitle("New monster class")
        prog.setMinimumDuration(0)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.show()
        self._cw = w = Worker(work)

        def done(r):
            prog.close()
            self.result_mod, self.result_family = r
            self.accept()

        def failed(msg):
            prog.close()
            error_box(self, "New monster class", msg)
        w.done.connect(done)
        w.failed.connect(failed)
        w.start()
