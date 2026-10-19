"""Isolated typography policy tests: never import app/workspace or show a window."""
import importlib.util
from pathlib import Path
import unittest

from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo
from PyQt6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton, QLineEdit, QTableWidget

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("isolated_theme", ROOT / "d5gui/theme.py")
theme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(theme)


class TypographyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.native = QFont(cls.app.font())

    def tearDown(self):
        self.app.setStyleSheet("")
        self.app.setFont(self.native)

    def test_native_baseline_and_larger_baseline_are_not_masked(self):
        for size in (13.0, 17.0):
            baseline = QFont(self.native)
            baseline.setPointSizeF(size)
            self.app.setFont(baseline)
            self.app.setStyleSheet(theme.system_typography_qss(baseline))
            label = QLabel("Native ordinary text")
            label.ensurePolished()
            self.assertEqual(label.font().pointSizeF(), size)
            self.assertEqual(label.font().families(), baseline.families())
            self.assertFalse(label.isVisible())

    def test_original_qss_is_a_discriminating_negative_control(self):
        baseline = QFont(self.native)
        baseline.setPointSizeF(17)
        self.app.setFont(baseline)
        self.app.setStyleSheet(theme.QSS)
        label = QLabel("Original absolute size masks enlarged baseline")
        label.ensurePolished()
        self.assertEqual(label.font().pointSizeF(), 10)
        self.assertNotEqual(label.font().pointSizeF(), baseline.pointSizeF())

    def test_explicit_fixed_font_outside_plain_edit_is_not_masked(self):
        self.app.setStyleSheet(theme.system_typography_qss(self.native))
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed.setPointSizeF(15)
        label = QLabel("Explicit code role")
        label.setFont(fixed)
        label.ensurePolished()
        self.assertEqual(label.font().families(), fixed.families())
        self.assertEqual(label.font().pointSizeF(), 15)

    def test_code_policy_is_fixed_but_wrapped_prose_is_standard(self):
        self.app.setStyleSheet(theme.system_typography_qss(self.native))
        prose = QPlainTextEdit()
        prose.setFont(QFont("Segoe UI", 10))  # existing dialogue request
        code = QPlainTextEdit()
        code.setFont(QFont("Consolas", 9))  # existing script/hex request
        code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for widget in (prose, code):
            widget.ensurePolished()
            self.assertEqual(widget.font().pointSizeF(), self.native.pointSizeF())
        self.assertEqual(QFontInfo(code.font()).family(), QFontInfo(fixed).family())
        self.assertEqual(QFontInfo(prose.font()).family(), QFontInfo(self.native).family())

    def test_sidebar_fits_long_navigation_and_wraps_support_labels(self):
        # Load only this UI function's AST, not side-effectful app imports.
        import ast
        from PyQt6.QtWidgets import QWidget, QVBoxLayout
        tree = ast.parse((ROOT / "d5gui/app.py").read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fit_sidebar"]
        namespace = {"QLabel": QLabel, "QPushButton": QPushButton}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "sidebar-only", "exec"), namespace)
        fit = namespace["fit_sidebar"]
        for size in (13, 17):
            baseline = QFont(self.native)
            baseline.setPointSize(size)
            self.app.setFont(baseline)
            self.app.setStyleSheet(theme.system_typography_qss(baseline))
            side = QWidget()
            side.setObjectName("sidebar")
            layout = QVBoxLayout(side)
            layout.setContentsMargins(8, 8, 8, 10)
            sub = QLabel("DISGAEA 5 MODDING STUDIO")
            sub.setObjectName("brandSub")
            button = QPushButton("⚔  Item World Auto-Battle")
            layout.addWidget(sub)
            layout.addWidget(button)
            fit(side)
            self.assertGreaterEqual(side.width() - 16, button.sizeHint().width())
            self.assertTrue(sub.wordWrap())
            self.assertFalse(side.isVisible())

    def test_roles_keep_hierarchy_colors_and_native_derived_support_sizes(self):
        before = self.native.toString()
        original = theme.QSS
        self.app.setStyleSheet(theme.system_typography_qss(self.native))
        for name, ratio in (("brandSub", .9), ("sectionLabel", .9), ("fieldLabel", .9),
                            ("slotNumber", .9), ("pageSubtitle", .95), ("pageTitle", 1.7),
                            ("cardTitle", 1.15), ("bigNumber", 2.1)):
            label = QLabel(name)
            label.setObjectName(name)
            label.ensurePolished()
            self.assertAlmostEqual(label.font().pointSizeF(), self.native.pointSizeF() * ratio, places=2)
        self.assertEqual(theme.QSS, original)
        self.assertEqual(self.native.toString(), before)
        self.assertIn(theme.ACCENT, theme.system_typography_qss(self.native))
        for cls in (QPushButton, QLineEdit, QTableWidget):
            widget = cls()
            widget.ensurePolished()
            self.assertEqual(widget.font().pointSizeF(), self.native.pointSizeF())


if __name__ == "__main__":
    unittest.main()
