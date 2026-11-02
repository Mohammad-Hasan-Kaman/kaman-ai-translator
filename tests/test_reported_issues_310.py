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

    def test_saved_pages_are_isolated_by_translation_direction(self):
        with tempfile.TemporaryDirectory(dir=_TEST_HOME) as folder:
            source = os.path.join(folder, "book.epub")
            with open(source, "wb") as fh:
                fh.write(b"source")
            job = core.JobStore(source).load()
            job.switch_direction("en2ar")
            job.set(0, "ترجمة عربية")
            job.context_tail = "سياق عربي"
            job.save()

            job.switch_direction("en2fa")
            self.assertIsNone(job.get(0))
            self.assertEqual(job.context_tail, "")
            job.set(0, "ترجمهٔ فارسی")
            job.context_tail = "بافت فارسی"
            job.save()

            job.switch_direction("en2ar")
            self.assertEqual(job.get(0), "ترجمة عربية")
            self.assertEqual(job.context_tail, "سياق عربي")
            reloaded = core.JobStore(source).load()
            reloaded.switch_direction("en2fa")
            self.assertEqual(reloaded.get(0), "ترجمهٔ فارسی")

    def test_legacy_job_without_direction_is_not_reused(self):
        with tempfile.TemporaryDirectory(dir=_TEST_HOME) as folder:
            source = os.path.join(folder, "legacy.pdf")
            with open(source, "wb") as fh:
                fh.write(b"source")
            job = core.JobStore(source)
            job.data["translations"] = {"0": "possibly Arabic"}
            job.save()
            # Emulate an old job by removing direction metadata and the maps.
            import json
            with open(job.path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            stored.pop("direction", None)
            stored.pop("translations_by_direction", None)
            stored.pop("reviewed_by_direction", None)
            stored.pop("context_by_direction", None)
            with open(job.path, "w", encoding="utf-8") as fh:
                json.dump(stored, fh)

            migrated = core.JobStore(source).load()
            migrated.switch_direction("en2fa")
            self.assertIsNone(migrated.get(0))
            self.assertEqual(
                migrated.data["legacy_translations"], {"0": "possibly Arabic"}
            )

    def test_gemini_3_uses_model_default_temperature(self):
        engine = core.GeminiEngine("test-key", "gemini-3.8-flash", temperature=0.1)
        config = engine._generation_config("translate", json_mode=True)
        self.assertIsNone(config.temperature)
        self.assertEqual(config.response_mime_type, "application/json")

    def test_legacy_gemini_default_migrates_to_current_stable(self):
        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini", model="gemini-2.5-flash")
        core._ensure_profiles(cfg, {
            "gemini": {"api_key": "", "base_url": "", "model": "gemini-2.5-flash"}
        })
        self.assertEqual(cfg["model"], "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
