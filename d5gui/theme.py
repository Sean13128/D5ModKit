"""Dark 'Netherworld' theme."""

ACCENT = "#e0457b"
ACCENT2 = "#8b5cf6"
BG = "#17151f"
PANEL = "#201d2b"
LINE = "#2d2940"

QSS = f"""
* {{ font-family: 'Segoe UI', 'Yu Gothic UI', sans-serif; font-size: 9.5pt; }}
QWidget {{ color: #e8e6f0; }}
QMainWindow, QDialog, QMessageBox, QInputDialog, QProgressDialog {{ background: {BG}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QToolTip {{ background: #2a2638; color: #fff; border: 1px solid {ACCENT}; padding: 5px; }}

#sidebar {{ background: #110f18; border-right: 1px solid #2a2638; }}
#sidebar QPushButton {{ text-align: left; padding: 6px 12px; border: none; border-radius: 7px;
    background: transparent; color: #b8b4c8; font-size: 10pt; }}
#sidebar QPushButton:hover {{ background: #221f2e; color: #fff; }}
#sidebar QPushButton:checked {{ background: {ACCENT}; color: #fff; font-weight: 600; }}
#sidebar QPushButton#primary {{ background: {ACCENT}; color: white; font-weight: 700; text-align: center;
    padding: 8px 10px; }}
#sidebar QPushButton#primary:hover {{ background: #f05a8e; }}
#sidebar QPushButton#primary:disabled {{ background: #3a2a38; color: #9a8a96; }}
#brand {{ font-size: 14pt; font-weight: 800; color: #fff; padding: 8px 12px 0 12px; }}
#brandSub {{ color: {ACCENT}; padding: 0 12px 6px 12px; font-size: 7.5pt; letter-spacing: 1px; }}
#sectionLabel {{ color: #6f6a85; font-size: 7.5pt; padding: 8px 12px 2px 12px; letter-spacing: 1px; }}

#statusPanel, #statusPanelLarge {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
#statusTitle {{ font-weight: 700; color: #fff; }}
#statusTitleLarge {{ font-size: 13pt; font-weight: 700; color: #fff; }}
#stepCard {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
#stepNum {{ font-size: 16pt; font-weight: 800; color: {ACCENT}; padding-right: 6px; }}

#pageTitle {{ font-size: 15pt; font-weight: 700; color: #fff; }}
#pageSubtitle {{ color: #9a95b0; }}
#card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
#cardTitle {{ font-size: 10.5pt; font-weight: 700; color: #fff; padding-bottom: 2px; }}
#muted {{ color: #8e89a6; }}
#hint {{ color: #8e89a6; }}
#ok {{ color: #3ecf8e; }}
#warn {{ color: #f5a524; }}
#bigNumber {{ font-size: 20pt; font-weight: 800; color: {ACCENT}; }}
#banner {{ background: #2a2238; border: 1px solid #4b3a6a; border-radius: 8px; padding: 6px 10px; color: #ddd6f5; }}
#bannerWarn {{ background: #33281a; border: 1px solid #6a4f1f; border-radius: 8px; padding: 6px 10px;
    color: #f5d9a8; }}

QPushButton {{ background: #2b2740; border: 1px solid #3a3553; border-radius: 6px; padding: 5px 12px; color: #eee; }}
QPushButton:hover {{ background: #36304f; border-color: {ACCENT2}; }}
QPushButton:pressed {{ background: #241f36; }}
QPushButton:disabled {{ color: #666; background: #1f1c2a; }}
QPushButton:checked {{ background: #4b2a5e; border-color: {ACCENT2}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 700; padding: 7px 16px; }}
QPushButton#primary:hover {{ background: #f05a8e; }}
QPushButton#primary:disabled {{ background: #3a2a38; color: #9a8a96; }}
QPushButton#danger {{ background: #5a2230; border-color: #7a2a3c; }}
QPushButton#subtle {{ background: transparent; border: 1px solid transparent; color: #9a95b0; }}
QPushButton#subtle:hover {{ color: #fff; border-color: #3a3553; }}
QPushButton::menu-indicator {{ width: 0; }}
QToolButton {{ background: #2b2740; border: 1px solid #3a3553; border-radius: 6px; padding: 3px 8px; color: #eee; }}
QToolButton:hover {{ border-color: {ACCENT2}; }}
QToolButton:checked {{ background: #4b2a5e; border-color: {ACCENT2}; }}
QToolButton#logToggle {{ background: transparent; border: none; color: #9a95b0; font-weight: 600; padding: 1px 4px; }}
QToolButton#logToggle:hover {{ color: #fff; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: #0f0d15; border: 1px solid #332e48; border-radius: 6px; padding: 3px 6px; color: #eee;
    selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT2}; }}
QComboBox QAbstractItemView {{ background: #1c1928; selection-background-color: {ACCENT}; }}

QTableView, QTreeView, QListView, QTableWidget, QTreeWidget, QListWidget {{
    background: #13111b; alternate-background-color: #181622; border: 1px solid #2a2638; border-radius: 8px;
    gridline-color: #262234; selection-background-color: #4b2a5e; selection-color: #fff; }}
QListWidget::item {{ padding: 2px 4px; }}
QListView::indicator, QTreeView::indicator, QTableView::indicator {{ width: 14px; height: 14px; border: 1px solid #5a547a;
    border-radius: 3px; background: #0f0d15; }}
QListView::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked {{ background: {ACCENT};
    border-color: {ACCENT}; }}
QTreeView::indicator:indeterminate {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT},
    stop:0.5 {ACCENT}, stop:0.51 #0f0d15, stop:1 #0f0d15); border-color: {ACCENT}; }}
QHeaderView::section {{ background: #1f1c2a; color: #c9c5da; border: none; border-right: 1px solid #2a2638;
    border-bottom: 1px solid #2a2638; padding: 4px; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid #2a2638; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: #1c1928; color: #aaa; padding: 6px 14px; border-top-left-radius: 7px;
    border-top-right-radius: 7px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: #2b2740; color: #fff; }}
QScrollBar:vertical {{ background: #13111b; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3a3553; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: #13111b; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #3a3553; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QFormLayout QLabel, QGroupBox QLabel {{ color: #d6d2e4; }}
QSplitter::handle {{ background: #2a2638; }}
QSplitter::handle:hover {{ background: {ACCENT2}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 9px; margin-top: 12px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT}; font-weight: 700; }}
QStatusBar {{ background: #110f18; color: #9a95b0; }}
QProgressBar {{ background: #0f0d15; border: none; border-radius: 3px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT2}; border-radius: 3px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #5a547a; border-radius: 4px;
    background: #0f0d15; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 3px solid #0f0d15; outline: 1px solid {ACCENT}; }}
QCheckBox::indicator:disabled {{ background: #1f1c2a; border-color: #3a3553; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid #5a547a; border-radius: 8px;
    background: #0f0d15; }}
QRadioButton::indicator:hover {{ border-color: {ACCENT2}; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
    stop:0 {ACCENT}, stop:0.55 {ACCENT}, stop:0.62 #0f0d15, stop:1 #0f0d15); border-color: {ACCENT}; }}
QRadioButton::indicator:disabled {{ background: #1f1c2a; border-color: #3a3553; }}
QSlider::groove:horizontal {{ height: 6px; background: #2b2740; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -5px 0; border-radius: 7px; }}
QMenu {{ background: #1c1928; border: 1px solid #332e48; }}
QMenu::item {{ padding: 5px 18px; }}
QMenu::item:selected {{ background: {ACCENT}; }}
"""
