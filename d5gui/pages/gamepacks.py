"""Explicit local catalogue selection and offline native pack staging only.

No Workspace construction, discovery, persisted settings or live-profile writes.
Native Home already owns installed mod groups; this page only prepares new kits.
"""
import json
import re
import stat
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem, QComboBox, QCheckBox,
                             QPlainTextEdit, QFileDialog, QHeaderView, QSplitter,
                             QAbstractItemView, QScrollArea)
from d5lib import gamepacks
from ..common import Card, PageHeader

LABELS = dict(zip(gamepacks.CATEGORIES, ("Characters", "Humanoid classes", "Monsters")))


def _read_metadata(path):
    """Bounded regular JSON file only; never follow a supplied symlink chain."""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink metadata paths are not supported")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
        raise ValueError("Choose a regular JSON metadata file smaller than 16 MiB")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


class GamePacksPage(QWidget):
    def __init__(self, ws=None, main=None):
        super().__init__()
        # Deliberately do not access ws: it may reference the live canonical kit.
        self.catalogue = self.plan = None
        self.artifacts, self.game_checks, self.overrides = {}, {}, {}
        outer = QVBoxLayout(self)
        outer.addWidget(PageHeader("Game Content Packs", "Local catalogues → new staging folder; never installed here."))
        note = QLabel("Staged ≠ installed. Built artifacts are existing native child mods, not proof of playability. "
                      "Catalogue-only entries cannot be built or played from this page. Later installation must use "
                      "the existing Home/profile workflow and its conflict/save checks. Disabling content can break "
                      "saves that depend on it: back up saves and use a separate-save profile before live changes.")
        note.setWordWrap(True)
        outer.addWidget(note)
        bar = QHBoxLayout()
        self.open_button = QPushButton("Open catalogue…")
        self.open_button.clicked.connect(self.choose_catalogue)
        bar.addWidget(self.open_button)
        self.artifact_button = QPushButton("Add artifact folder…")
        self.artifact_button.setToolTip("Choose one exact native mod folder containing mod.json. Add required dependency folders separately; nothing is scanned.")
        self.artifact_button.clicked.connect(self.choose_artifact)
        bar.addWidget(self.artifact_button)
        self.forget_button = QPushButton("Forget artifacts")
        self.forget_button.clicked.connect(self.forget_artifacts)
        bar.addWidget(self.forget_button)
        self.clear_button = QPushButton("Clear selection")
        self.clear_button.clicked.connect(self.clear_selection)
        bar.addWidget(self.clear_button)
        outer.addLayout(bar)
        self.catalogue_label = QLabel("No catalogue open. No autodiscovery or source-art scans.")
        self.catalogue_label.setTextFormat(Qt.TextFormat.PlainText)
        self.catalogue_label.setWordWrap(True)
        outer.addWidget(self.catalogue_label)
        self.artifact_label = QLabel("No explicit artifact folders supplied.")
        self.artifact_label.setTextFormat(Qt.TextFormat.PlainText)
        self.artifact_label.setWordWrap(True)
        outer.addWidget(self.artifact_label)
        filters = Card()
        self.games_layout = QVBoxLayout()
        games_widget = QWidget()
        games_widget.setLayout(self.games_layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(games_widget)
        scroll.setMaximumHeight(115)
        filters.lay.addWidget(scroll)
        row = QHBoxLayout()
        row.addWidget(QLabel("Bulk categories:"))
        self.category_checks = {}
        for key, label in LABELS.items():
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self.recompute)
            self.category_checks[key] = box
            row.addWidget(box)
        filters.lay.addLayout(row)
        hint = QLabel("Game + category ticks select bulk roots. Entry overrides: Inherit / Include / Exclude. "
                      "Explicit includes and required dependencies remain selected regardless of bulk filters.")
        hint.setWordWrap(True)
        filters.lay.addWidget(hint)
        outer.addWidget(filters)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Entry / edition", "Game", "Category", "Artifact status", "Fidelity", "Override", "Selection"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_details)
        splitter.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select an entry for source provenance, fidelity, adaptations and missing mappings.")
        splitter.addWidget(self.details)
        splitter.setSizes([320, 130])
        outer.addWidget(splitter, 1)
        self.summary = QLabel("Open a real local catalogue to begin. No content is preselected or discovered.")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        self.build_button = QPushButton("Build to new folder…")
        self.build_button.setEnabled(False)
        self.build_button.clicked.connect(self.choose_build)
        outer.addWidget(self.build_button)
        self.result = QLabel()
        self.result.setTextFormat(Qt.TextFormat.PlainText)
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.result)

    def choose_catalogue(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open local content catalogue", "", "JSON metadata (*.json)")
        if path:
            self.open_catalogue(path)

    def open_catalogue(self, path):
        try:
            doc = gamepacks.validate_catalogue(_read_metadata(path))
        except (ValueError, OSError) as exc:
            self.result.setText(f"Catalogue not opened: {exc}")
            return False
        self.catalogue = doc
        self.artifacts.clear()
        self.artifact_label.setText("No explicit artifact folders supplied.")
        self.catalogue_label.setText(f"{doc['name']} — {Path(path).absolute()}")
        self.result.clear()
        self.game_checks.clear()
        while self.games_layout.count():
            widget = self.games_layout.takeAt(0).widget()
            widget.deleteLater()
        for game in doc["games"]:
            box = QCheckBox(game["name"])
            box.setToolTip(game["id"])
            box.toggled.connect(self.recompute)
            self.game_checks[game["id"]] = box
            self.games_layout.addWidget(box)
        self.table.setRowCount(len(doc["entries"]))
        self.overrides.clear()
        games = {g["id"]: g["name"] for g in doc["games"]}
        for row, entry in enumerate(doc["entries"]):
            values = [f"{entry['name']} / {entry['source']['edition']}", games[entry["game"]],
                      LABELS[entry["category"]], "", entry["fidelity"]["mode"], "", ""]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
            combo = QComboBox()
            combo.addItems(["Inherit", "Include", "Exclude"])
            combo.setToolTip("Catalogue-only inclusion records intent, never creates playable content.")
            combo.currentIndexChanged.connect(self.recompute)
            self.overrides[entry["id"]] = combo
            self.table.setCellWidget(row, 5, combo)
        self.details.clear()
        self.recompute()
        return True

    def choose_artifact(self):
        path = QFileDialog.getExistingDirectory(self, "Choose ONE native child mod folder (mod.json)")
        if path:
            self.add_artifact(path)

    def add_artifact(self, path):
        try:
            folder = Path(path).absolute()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", folder.name):
                raise ValueError("Invalid native mod folder ID")
            if not isinstance(_read_metadata(folder / "mod.json"), dict):
                raise ValueError("mod.json must contain an object")
            if folder.name in self.artifacts and self.artifacts[folder.name] != folder:
                raise ValueError("Duplicate native mod ID; forget artifacts before replacing its folder")
            self.artifacts[folder.name] = folder
        except (ValueError, OSError) as exc:
            self.result.setText(f"Artifact not added: {exc}")
            return False
        self.artifact_label.setText("Explicit folders: " + ", ".join(sorted(self.artifacts)))
        self.artifact_label.setToolTip("\n".join(str(p) for p in self.artifacts.values()))
        self.result.clear()
        self.recompute()
        return True

    def forget_artifacts(self):
        self.artifacts.clear()
        self.artifact_label.setText("No explicit artifact folders supplied.")
        self.recompute()

    def clear_selection(self):
        for box in self.game_checks.values():
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        for combo in self.overrides.values():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.recompute()

    def recompute(self, *_):
        self.plan = None
        self.build_button.setEnabled(False)
        if self.catalogue is None:
            return
        try:
            self.plan = gamepacks.resolve_selection(
                self.catalogue, artifacts=self.artifacts,
                games=[key for key, box in self.game_checks.items() if box.isChecked()],
                categories=[key for key, box in self.category_checks.items() if box.isChecked()],
                entries=[key for key, box in self.overrides.items() if box.currentIndex() == 1],
                exclude_entries=[key for key, box in self.overrides.items() if box.currentIndex() == 2])
            plan = self.plan
            self.summary.setText(f"Closure: {len(plan.entry_ids) + len(plan.catalogue_only)} selected entries; native load order: "
                                 f"{', '.join(plan.mod_ids) or '(none)'}. Catalogue-only (not buildable): "
                                 f"{', '.join(plan.catalogue_only) or '(none)'}.")
            self.build_button.setEnabled(bool(plan.mod_ids))
        except (ValueError, OSError) as exc:
            self.summary.setText(f"Selection error — Build blocked: {exc}")
        for row, entry in enumerate(self.catalogue["entries"]):
            if entry["status"] == "catalogue":
                status = "Catalogue-only — unavailable"
            else:
                try:
                    gamepacks.validate_catalogue(dict(self.catalogue, entries=[dict(entry, requires=[], conflicts=[])]), artifacts=self.artifacts)
                    status = "Built artifact verified (not installed)"
                except (ValueError, OSError):
                    status = "Build-ready claim — artifact missing/invalid"
            self.table.item(row, 3).setText(status)
            included = self.plan is not None and entry["id"] in self.plan.entry_ids
            intent = self.plan is not None and entry["id"] in self.plan.catalogue_only
            self.table.item(row, 6).setText("Catalogue-only intent" if intent else "Included / required" if included
                                          else "Not selected" if self.plan else "Unresolved")

    def show_details(self):
        row = self.table.currentRow()
        if self.catalogue is not None and 0 <= row < len(self.catalogue["entries"]):
            self.details.setPlainText(json.dumps(self.catalogue["entries"][row], indent=2, ensure_ascii=False))

    def choose_build(self):
        path, _ = QFileDialog.getSaveFileName(self, "Name a NEW staging folder (must not exist)", "", "All paths (*)",
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.build_to(path)

    def build_to(self, path):
        # Re-read selected native metadata/payload even if changed since last click.
        self.recompute()
        if self.plan is None or not self.plan.mod_ids:
            self.result.setText("Build blocked: " + self.summary.text())
            return False
        try:
            gamepacks.materialize(self.catalogue, self.plan, artifacts=self.artifacts, staging_path=path)
        except (ValueError, OSError) as exc:
            self.result.setText(f"Build failed (nothing installed): {exc}")
            return False
        self.result.setText(f"Staged native mods + pack groups + isolated Default profile at {Path(path).absolute()}. "
                            "Nothing installed; live profiles and saves unchanged. Catalogue-only entries remain unavailable.")
        return True
