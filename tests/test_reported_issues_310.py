"""Focused regressions for the reported v3.1.0 UI and Gemini issues."""
import builtins
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_HOME = tempfile.mkdtemp(prefix="kaman_v310_reported_")
os.environ["APPDATA"] = _TEST_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kaman_core as core
import translator_app_v3 as ui
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel


class ReportedIssueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_light_theme_uses_readable_settings_colors(self):
        cfg = dict(core.CONFIG_DEFAULTS, theme="light", ui_lang="fa")
        window = ui.ModernTranslatorApp()
        window.cfg = cfg
        window.apply_theme()
        dialog = ui.SettingsDialog(cfg, window)

        self.assertEqual(dialog._theme_mode, "light")
        self.assertIn("#64748b", dialog.lbl_local_hint.styleSheet())
        self.assertIn("#64748b", dialog.lbl_encrypt.styleSheet())
        self.assertTrue(any(
            "#cbd5e1" in label.styleSheet()
            for label in dialog.findChildren(QLabel)
        ))

        dialog.close()
        window.close()

    def test_language_change_updates_main_window_without_losing_open_book(self):
        cfg = dict(core.CONFIG_DEFAULTS, theme="light", ui_lang="fa")
        ui.set_ui_lang("fa")
        window = ui.ModernTranslatorApp()
        window.cfg = cfg
        window.current_file = os.path.join(_TEST_HOME, "book.pdf")
        window.current_page = 2
        window.total_pages = 8

        changed = dict(cfg, ui_lang="en")
        window.on_settings_saved(changed)

        self.assertIn("book.pdf", window.lbl_file.text())
        self.assertEqual(window.btn_settings.text(), "⚙️ Settings")
        self.assertEqual(window.lbl_src_lang.text(), "🌐 Source language:")
        self.assertIn("3", window.lbl_page.text())
        self.assertEqual(
            self.app.layoutDirection(), Qt.LayoutDirection.LeftToRight
        )
        self.assertEqual(
            window.txt_output.toPlainText(),
            ui.STRINGS["en"]["output_placeholder"],
        )

        window.on_settings_saved(dict(changed, ui_lang="fa"))
        self.assertIn("book.pdf", window.lbl_file.text())
        self.assertEqual(
            self.app.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )
        self.assertEqual(
            window.txt_output.toPlainText(),
            ui.STRINGS["fa"]["output_placeholder"],
        )

        window.close()
        ui.set_ui_lang("fa")

    def test_missing_pydantic_shows_install_instructions(self):
        original_import = builtins.__import__

        def import_without_pydantic(name, globals=None, locals=None,
                                    fromlist=(), level=0):
            if name == "google" and "genai" in fromlist:
                raise ModuleNotFoundError(
                    "No module named 'pydantic'", name="pydantic"
                )
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = import_without_pydantic
        try:
            with self.assertRaises(core.TranslationError) as caught:
                core.GeminiEngine("key", "model")
        finally:
            builtins.__import__ = original_import

        self.assertIn("pip install -r requirements.txt", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
