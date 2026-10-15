"""The kit's look: a Disgaea 5 'Netherworld night' theme.

Like the game's own menus: deep indigo panels framed in blue, teal header strips with dark text (the Status
screen's APTITUDE bar), gold stat names, Disgaea pink for the main action of a page and cyan for what has the focus.
Every colour is a constant below; pages with their own style sheets (the skill editor) take them from here.
"""
import os

_ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons").replace("\\", "/")

BG = "#0f1124"            # window
BG_DEEP = "#0a0b1a"       # sidebar, status bar
PANEL = "#171a33"         # cards, group boxes
PANEL_HI = "#1f2342"      # raised / hovered
INPUT = "#0b0d1d"         # text boxes, lists
LINE = "#2b3160"          # frames
LINE_HI = "#3d4689"       # strong frames
TEXT = "#eef0ff"
TEXT2 = "#c3c8e8"         # labels
MUTED = "#8a90b8"
ACCENT = "#ff4f8b"        # Disgaea pink: the page's main action, selection
ACCENT_HI = "#ff74a5"
ACCENT2 = "#3fd0ff"       # cyan: focus, hover frames
GOLD = "#ffb547"          # stat names, section labels
TEAL_A, TEAL_B = "#5ee6d8", "#2aa3cf"   # header strips
SELECT = "#5a2a7e"        # selected rows
OK, WARN, BAD = "#3ecf8e", "#f5a524", "#ff5d6c"

_GRAD_BTN = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #262b55, stop:1 #1c2044)"
_GRAD_BTN_HI = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #30366a, stop:1 #232852)"
_GRAD_PINK = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ff6a9c, stop:1 #e8336f)"
_GRAD_PINK_HI = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ff8ab2, stop:1 #f44a82)"
_GRAD_TEAL = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {TEAL_A}, stop:1 {TEAL_B})"
_GRAD_SEL = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8a2f78, stop:1 #45307f)"

QSS = f"""
* {{ font-family: 'Segoe UI', 'Yu Gothic UI', sans-serif; font-size: 10pt; }}
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog, QMessageBox, QInputDialog, QProgressDialog {{ background: {BG}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QToolTip {{ background: #1b1f3d; color: #fff; border: 1px solid {ACCENT2}; border-radius: 4px; padding: 6px; }}

#sidebar {{ background: {BG_DEEP}; border-right: 1px solid {LINE}; }}
#sidebar QPushButton {{ text-align: left; padding: 7px 12px; border: none; border-left: 3px solid transparent;
    border-radius: 7px; background: transparent; color: #b8bde0; font-size: 10pt; }}
#sidebar QPushButton:hover {{ background: #161a34; color: #fff; }}
#sidebar QPushButton:checked {{ background: {_GRAD_SEL}; color: #fff; font-weight: 600;
    border-left: 3px solid {ACCENT}; }}
#sidebar QPushButton#primary {{ background: {_GRAD_PINK}; color: white; font-weight: 700; text-align: center;
    padding: 9px 10px; border: none; }}
#sidebar QPushButton#primary:hover {{ background: {_GRAD_PINK_HI}; }}
#sidebar QPushButton#primary:disabled {{ background: #2d2238; color: #9a8a96; }}
#brand {{ font-size: 15pt; font-weight: 800; color: #fff; padding: 10px 12px 0 12px; letter-spacing: 1px; }}
#brandSub {{ color: {ACCENT}; padding: 0 12px 8px 12px; font-size: 7.5pt; font-weight: 700; letter-spacing: 2px; }}
#sectionLabel {{ color: {GOLD}; font-size: 7.5pt; font-weight: 700; padding: 10px 12px 3px 12px; letter-spacing: 2px; }}

#statusPanel, #statusPanelLarge {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
#statusTitle {{ font-weight: 700; color: #fff; }}
#statusTitleLarge {{ font-size: 13.5pt; font-weight: 700; color: #fff; }}
#stepCard {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; }}
#stepNum {{ font-size: 17pt; font-weight: 800; color: {ACCENT}; padding-right: 6px; }}

#pageTitle {{ font-size: 17pt; font-weight: 800; color: #fff; letter-spacing: 0.5px; }}
#pageSubtitle {{ color: {MUTED}; font-size: 9.5pt; }}
#card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; }}
#cardTitle {{ font-size: 11.5pt; font-weight: 700; color: #fff; padding-bottom: 2px; }}
#muted {{ color: {MUTED}; }}
#hint {{ color: {MUTED}; }}
#ok {{ color: {OK}; }}
#warn {{ color: {WARN}; }}
#bigNumber {{ font-size: 21pt; font-weight: 800; color: {ACCENT}; }}
#fieldLabel {{ color: {TEXT2}; font-size: 9pt; font-weight: 600; }}
#statLabel {{ color: {GOLD}; font-size: 10.5pt; font-weight: 800; letter-spacing: 1px; }}
#slotNumber {{ color: {MUTED}; font-size: 8.5pt; font-weight: 700; }}
#banner {{ background: #1c1f42; border: 1px solid #3a3f86; border-radius: 9px; padding: 7px 11px; color: #dfe3ff; }}
#bannerWarn {{ background: #33281a; border: 1px solid #6a4f1f; border-radius: 9px; padding: 7px 11px;
    color: #f5d9a8; }}

QPushButton {{ background: {_GRAD_BTN}; border: 1px solid {LINE_HI}; border-radius: 7px; padding: 6px 13px;
    color: #f0f2ff; }}
QPushButton:hover {{ background: {_GRAD_BTN_HI}; border-color: {ACCENT2}; }}
QPushButton:pressed {{ background: #161a36; }}
QPushButton:disabled {{ color: #5f648a; background: #14172c; border-color: #23284a; }}
QPushButton:checked {{ background: {_GRAD_SEL}; border-color: {ACCENT}; }}
QPushButton#primary {{ background: {_GRAD_PINK}; border: 1px solid #ff8fb5; color: white; font-weight: 700;
    padding: 7px 18px; }}
QPushButton#primary:hover {{ background: {_GRAD_PINK_HI}; }}
QPushButton#primary:disabled {{ background: #2d2238; border-color: #3d2a44; color: #9a8a96; }}
QPushButton#danger {{ background: #4a1c2a; border-color: #7a2a3c; }}
QPushButton#danger:hover {{ background: #5e2234; border-color: {BAD}; }}
QPushButton#subtle {{ background: transparent; border: 1px solid transparent; color: {MUTED}; }}
QPushButton#subtle:hover {{ color: #fff; border-color: {LINE_HI}; }}
QPushButton#chip {{ background: #141836; border: 1px solid {LINE}; border-radius: 12px; padding: 3px 10px;
    color: {TEXT2}; font-size: 9pt; font-weight: 600; }}
QPushButton#chip:hover {{ border-color: {ACCENT2}; color: #fff; background: #1b2045; }}
QPushButton::menu-indicator {{ width: 0; }}
QToolButton {{ background: {_GRAD_BTN}; border: 1px solid {LINE_HI}; border-radius: 7px; padding: 4px 9px;
    color: #f0f2ff; }}
QToolButton:hover {{ border-color: {ACCENT2}; }}
QToolButton:checked {{ background: {_GRAD_SEL}; border-color: {ACCENT}; }}
QToolButton#logToggle {{ background: transparent; border: none; color: {MUTED}; font-weight: 600; padding: 1px 4px; }}
QToolButton#logToggle:hover {{ color: #fff; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {INPUT}; border: 1px solid {LINE}; border-radius: 7px; padding: 4px 7px; color: {TEXT};
    selection-background-color: {ACCENT}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {LINE_HI}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT2}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: #6a6f96; background: #10122a; }}
QAbstractSpinBox {{ padding-right: 20px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 19px; background: #151935; border-left: 1px solid {LINE}; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 7px;
    border-bottom: 1px solid #20254a; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 7px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #252a55; }}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{ background: {ACCENT}; }}
QAbstractSpinBox::up-arrow {{ image: url({_ICONS}/spin_up.png); width: 8px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url({_ICONS}/spin_down.png); width: 8px; height: 6px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url({_ICONS}/spin_up_off.png); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url({_ICONS}/spin_down_off.png); }}
QComboBox QAbstractItemView {{ background: #141836; border: 1px solid {LINE_HI}; selection-background-color: {ACCENT};
    outline: none; }}

QTableView, QTreeView, QListView, QTableWidget, QTreeWidget, QListWidget {{
    background: {INPUT}; alternate-background-color: #10132a; border: 1px solid {LINE}; border-radius: 10px;
    gridline-color: #1e2244; selection-background-color: {SELECT}; selection-color: #fff; outline: none; }}
QListWidget::item, QTreeWidget::item {{ padding: 3px 5px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: #181c3a; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {_GRAD_SEL}; color: #fff; }}
QListView::indicator, QTreeView::indicator, QTableView::indicator {{ width: 14px; height: 14px;
    border: 1px solid #5a60a0; border-radius: 3px; background: {INPUT}; }}
QListView::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked {{ background: {ACCENT};
    border-color: {ACCENT}; }}
QTreeView::indicator:indeterminate {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT},
    stop:0.5 {ACCENT}, stop:0.51 {INPUT}, stop:1 {INPUT}); border-color: {ACCENT}; }}
QHeaderView::section {{ background: #171b38; color: {GOLD}; border: none; border-right: 1px solid {LINE};
    border-bottom: 1px solid {LINE}; padding: 5px; font-weight: 700; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 10px; top: -1px; }}
QTabBar::tab {{ background: #141733; color: #a6abd2; padding: 7px 15px; border-top-left-radius: 8px;
    border-top-right-radius: 8px; margin-right: 2px; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: #fff; background: #1b1f40; }}
QTabBar::tab:selected {{ background: {PANEL_HI}; color: #fff; font-weight: 600; border-bottom: 2px solid {ACCENT2}; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #333a73; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a53a0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #333a73; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #4a53a0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QFormLayout QLabel, QGroupBox QLabel {{ color: {TEXT2}; }}
QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:hover {{ background: {ACCENT2}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; margin-top: 15px;
    padding: 16px 10px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: 3px;
    padding: 3px 12px; color: #08121c; background: {_GRAD_TEAL}; border-radius: 7px; font-weight: 800; }}
QStatusBar {{ background: {BG_DEEP}; color: {MUTED}; }}
QProgressBar {{ background: {INPUT}; border: none; border-radius: 3px; text-align: center; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 3px; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #5a60a0; border-radius: 4px; background: {INPUT}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 3px solid {INPUT}; outline: 1px solid {ACCENT}; }}
QCheckBox::indicator:disabled {{ background: #151832; border-color: #2c3160; }}
QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid #5a60a0; border-radius: 8px;
    background: {INPUT}; }}
QRadioButton::indicator:hover {{ border-color: {ACCENT2}; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
    stop:0 {ACCENT}, stop:0.55 {ACCENT}, stop:0.62 {INPUT}, stop:1 {INPUT}); border-color: {ACCENT}; }}
QRadioButton::indicator:disabled {{ background: #151832; border-color: #2c3160; }}
QSlider::groove:horizontal {{ height: 6px; background: #232850; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: #fff; border: 2px solid {ACCENT}; width: 12px; margin: -5px 0;
    border-radius: 8px; }}
QMenu {{ background: #141836; border: 1px solid {LINE_HI}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 20px; border-radius: 5px; }}
QMenu::item:selected {{ background: {_GRAD_SEL}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
"""



TOOLTIP_DELAY_MS = 250      # hover time before a tooltip shows (Qt's default: 700)
TOOLTIP_MIN_MS = 30000      # how long it stays up at least (Qt's: 10 s); +60 ms per character of longer texts


def tooltip_ms(text):
    return TOOLTIP_MIN_MS + 60 * max(0, len(text or "") - 200)


def install_tooltips(app):
    """Tooltips show sooner and stay up to be read (until the mouse leaves the widget, a key or button is pressed,
    or the time is up).  The delay comes from the style (a proxy of the platform style, which the style sheet then
    wraps).  The time: a widget's own tooltip gets a toolTipDuration before it shows; a list / tree / table item's
    is shown here with no area to stay inside, so it no longer vanishes when the mouse drifts off the item.
    Call before setStyleSheet."""
    from PyQt6.QtCore import QEvent, QObject, QRect, Qt
    from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QProxyStyle, QStyle, QToolTip, QWidget

    class _Style(QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, ret=None):
            if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
                return TOOLTIP_DELAY_MS
            if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
                return 4000                     # moving on to another widget within 4 s: its tip shows at once
            return super().styleHint(hint, option, widget, ret)

    class _Keep(QObject):
        def eventFilter(self, obj, e):
            if e.type() != QEvent.Type.ToolTip or not isinstance(obj, QWidget):
                return False
            view = obj.parentWidget()
            if isinstance(view, QAbstractItemView) and not isinstance(view, QHeaderView) and view.viewport() is obj:
                index = view.indexAt(e.pos())
                tip = index.data(Qt.ItemDataRole.ToolTipRole) if index.isValid() else None
                if not tip:
                    return False                # the view's own handling (hides a tip that was up)
                QToolTip.showText(e.globalPos(), str(tip), obj, QRect(), tooltip_ms(str(tip)))
                return True
            if obj.toolTip() and obj.toolTipDuration() < 0:
                obj.setToolTipDuration(tooltip_ms(obj.toolTip()))
            return False

    app.setStyle(_Style())
    app._tooltip_keeper = _Keep(app)
    app.installEventFilter(app._tooltip_keeper)
