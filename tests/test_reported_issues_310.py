"""Focused regressions for the reported v3.1.0 UI and Gemini issues."""
import builtins
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_HOME = tempfile.mkdtemp(prefix="kaman_v310_reported_")
os.environ["APPDATA"] = _TEST_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kaman_core as core
import translator_app_v3 as ui
from PyQt6.QtCore import QThread, Qt
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

    def test_legacy_job_without_direction_is_adopted(self):
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
            # Legacy single-dict jobs are adopted under the direction they
            # are opened with — the user's finished pages must stay visible
            # (burying them made books reopen at zero progress).
            self.assertEqual(migrated.get(0), "possibly Arabic")
            self.assertEqual(migrated.data["legacy_translations"], {})

    def test_buried_legacy_translations_are_restored_on_load(self):
        with tempfile.TemporaryDirectory(dir=_TEST_HOME) as folder:
            source = os.path.join(folder, "buried.epub")
            with open(source, "wb") as fh:
                fh.write(b"source")
            job = core.JobStore(source)
            job.direction = "en2fa"
            job.data["direction"] = "en2fa"
            job.data["translations"] = {}
            job.data["translations_by_direction"] = {"en2fa": {}}
            job.data["legacy_translations"] = {"0": "صفحهٔ یک", "1": "صفحهٔ دو"}
            job.save()

            reloaded = core.JobStore(source).load()
            self.assertEqual(reloaded.count(), 2)
            self.assertEqual(reloaded.get(1), "صفحهٔ دو")
            self.assertEqual(reloaded.data["legacy_translations"], {})
            self.assertEqual(
                reloaded.data["translations_by_direction"]["en2fa"].get("0"),
                "صفحهٔ یک",
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

    def test_legacy_openai_default_is_not_migrated_as_gemini_endpoint(self):
        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini")
        cfg["base_url"] = "http://localhost:11434/v1"
        core._ensure_profiles(cfg)
        self.assertEqual(cfg["profiles"]["gemini"]["base_url"], "")

    def test_old_ignored_loopback_endpoint_is_migrated_away(self):
        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini", base_url="http://localhost:20128/v1", gemini_endpoint_version=0)
        core._ensure_profiles(cfg, {
            "gemini": {"api_key": "", "base_url": "http://localhost:20128/v1", "model": "gemini-3.8-flash"}
        })
        self.assertEqual(cfg["profiles"]["gemini"]["base_url"], "")
        self.assertEqual(cfg["gemini_endpoint_version"], 1)

    def test_explicit_new_gemini_endpoint_is_preserved(self):
        endpoint = "http://localhost:9000/gemini"
        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini", base_url=endpoint, gemini_endpoint_version=1)
        core._ensure_profiles(cfg, {
            "gemini": {"api_key": "", "base_url": endpoint, "model": "gemini-3.8-flash"}
        })
        self.assertEqual(cfg["profiles"]["gemini"]["base_url"], endpoint)

    def test_gemini_can_use_custom_native_api_gateway(self):
        gateway = "https://gemini-gateway.example/v1beta"
        engine = core.GeminiEngine("test-key", "gemini-3.8-flash", base_url=gateway)
        self.assertEqual(
            engine.client._api_client._http_options.base_url,
            gateway,
        )
        self.assertEqual(engine.client._api_client._http_options.timeout, 90_000)

    def test_gemini_proxy_is_passed_to_transport_and_profile_isolated(self):
        proxy = "http://127.0.0.1:7890"
        engine = core.GeminiEngine("test-key", "gemini-3.8-flash", proxy_url=proxy)
        opts = engine.client._api_client._http_options
        self.assertEqual(opts.client_args["proxy"], proxy)
        self.assertEqual(opts.async_client_args["proxy"], proxy)

        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini", api_key="key", gemini_proxy=proxy)
        core._ensure_profiles(cfg)
        core.switch_provider(cfg, "openai")
        self.assertEqual(cfg["profiles"]["gemini"]["proxy"], proxy)
        core.switch_provider(cfg, "gemini")
        self.assertEqual(cfg["gemini_proxy"], proxy)

    def test_gemini_proxy_is_encrypted_and_restored(self):
        proxy = "http://proxy-user:proxy-pass@127.0.0.1:7890"
        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini", api_key="key", gemini_proxy=proxy)
        core._ensure_profiles(cfg)
        core.save_config(cfg)
        with open(core.config_file_path(), encoding="utf-8") as fh:
            stored = fh.read()
        self.assertNotIn(proxy, stored)
        restored = core.load_config()
        self.assertEqual(restored["gemini_proxy"], proxy)

    def test_invalid_gemini_proxy_is_rejected_before_connection(self):
        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini", api_key="key", gemini_proxy="bad-url")
        self.assertIn("http://", core.validate_config(cfg))

    def test_settings_proxy_field_is_separate_from_openai_base_url(self):
        cfg = dict(core.CONFIG_DEFAULTS, provider="gemini", api_key="key", gemini_proxy="http://127.0.0.1:7890")
        core._ensure_profiles(cfg)
        window = ui.ModernTranslatorApp()
        dialog = ui.SettingsDialog(cfg, window)
        self.assertFalse(dialog.txt_gemini_proxy.isHidden())
        dialog.combo_provider.setCurrentIndex(1)
        self.assertTrue(dialog.txt_gemini_proxy.isHidden())
        self.assertEqual(dialog.txt_base.text(), cfg["profiles"]["openai"]["base_url"])
        dialog.combo_provider.setCurrentIndex(0)
        self.assertFalse(dialog.txt_gemini_proxy.isHidden())
        self.assertEqual(dialog.txt_gemini_proxy.text(), "http://127.0.0.1:7890")
        dialog.close()
        window.close()

    def test_gemini_retries_transient_gateway_deadlines(self):
        from google.genai.errors import APIError

        engine = core.GeminiEngine("test-key", "gemini-3.8-flash")
        failure = APIError(504, {"message": "DEADLINE_EXCEEDED"})
        expected = object()
        engine.client.models.generate_content = mock.Mock(
            side_effect=[failure, failure, expected]
        )
        with mock.patch("kaman_core.time.sleep"):
            response = engine._call("prompt", None, False)
        self.assertIs(response, expected)
        self.assertEqual(engine.client.models.generate_content.call_count, 3)

    def test_default_gemini_falls_back_after_temporary_model_overload(self):
        from google.genai.errors import APIError

        engine = core.GeminiEngine("test-key", "gemini-3.8-flash")
        overloaded = APIError(503, {"message": "model currently experiencing high demand"})
        expected = object()
        engine.client.models.generate_content = mock.Mock(
            side_effect=[overloaded, overloaded, overloaded, overloaded, expected]
        )
        with mock.patch("kaman_core.time.sleep"):
            response = engine._call("prompt", None, False)
        self.assertIs(response, expected)
        called_models = [call.kwargs["model"] for call in engine.client.models.generate_content.call_args_list]
        self.assertEqual(called_models, ["gemini-3.8-flash"] * 4 + ["gemini-3.6-flash"])
        self.assertEqual(engine.last_used_model, "gemini-3.6-flash")

    # ---- v3.2.1: گزارش‌های تست کاربر روی v3.2.0 ----

    def test_language_change_also_updates_direction_hint(self):
        cfg = dict(core.CONFIG_DEFAULTS, theme="light", ui_lang="fa")
        ui.set_ui_lang("fa")
        window = ui.ModernTranslatorApp()
        window.cfg = cfg
        self.assertEqual(window.lbl_lang_hint.text(), ui.STRINGS["fa"]["lang_hint"])
        window.on_settings_saved(dict(cfg, ui_lang="en"))
        self.assertEqual(window.lbl_lang_hint.text(), ui.STRINGS["en"]["lang_hint"])
        window.on_settings_saved(dict(cfg, ui_lang="fa"))
        self.assertEqual(window.lbl_lang_hint.text(), ui.STRINGS["fa"]["lang_hint"])
        window.close()
        ui.set_ui_lang("fa")

    def test_core_error_messages_follow_ui_language(self):
        import re

        fa_re = re.compile(r"[\u0600-\u06FF]")
        keys = (
            "gemini_quota", "gemini_api_error", "gemini_error",
            "gemini_recitation", "gemini_no_response", "server_quota",
            "server_http_error", "server_connect_failed", "model_list_failed",
            "model_none_returned", "key_decrypt_failed",
        )
        core.set_language("en")
        try:
            for key in keys:
                text = core.msg(key, code=500, detail="d", url="u")
                self.assertFalse(fa_re.search(text), f"{key} not English: {text}")
        finally:
            core.set_language("fa")
        for key in keys:
            text = core.msg(key, code=500, detail="d", url="u")
            self.assertTrue(fa_re.search(text), f"{key} not Persian: {text}")

    def test_copy_shows_visible_feedback(self):
        cfg = dict(core.CONFIG_DEFAULTS, theme="light", ui_lang="fa")
        ui.set_ui_lang("fa")
        window = ui.ModernTranslatorApp()
        window.cfg = cfg
        window.txt_output.setText("متن ترجمه‌شده")
        window.copy_translation()
        self.assertEqual(
            QApplication.clipboard().text(), "متن ترجمه‌شده"
        )
        self.assertFalse(window._status_frame.isHidden())
        self.assertEqual(window.lbl_status.text(), ui.STRINGS["fa"]["copied"])
        self.assertEqual(window.btn_copy.text(), ui.STRINGS["fa"]["copied"])
        window._restore_copy_label()
        self.assertEqual(window.btn_copy.text(), ui.STRINGS["fa"]["copy"])
        window.close()

    def test_status_bar_hides_when_idle(self):
        # v3.2.2: the status bar must not stay on screen forever; once
        # nothing is running it hides again (the copy feedback test above
        # still requires it to be visible right after the action).
        cfg = dict(core.CONFIG_DEFAULTS, theme="light", ui_lang="fa")
        ui.set_ui_lang("fa")
        window = ui.ModernTranslatorApp()
        window.cfg = cfg
        window._show_status("پیام آزمایشی")
        self.assertFalse(window._status_frame.isHidden())
        window._hide_status_if_idle()
        self.assertTrue(window._status_frame.isHidden())
        window.close()

    def test_status_bar_stays_while_worker_runs(self):
        cfg = dict(core.CONFIG_DEFAULTS, theme="light", ui_lang="fa")
        ui.set_ui_lang("fa")
        window = ui.ModernTranslatorApp()
        window.cfg = cfg
        thread = QThread()
        thread.start()
        try:
            window.single_worker = thread
            window._show_status("در حال ترجمه")
            window._hide_status_if_idle()
            self.assertFalse(window._status_frame.isHidden())
        finally:
            window.single_worker = None
            thread.quit()
            thread.wait()
        window._hide_status_if_idle()
        self.assertTrue(window._status_frame.isHidden())
        window.close()

    def test_export_labels_follow_target_language(self):
        with tempfile.TemporaryDirectory(dir=_TEST_HOME) as folder:
            src = os.path.join(folder, "book.pdf")
            with open(src, "wb") as fh:
                fh.write(b"source")
            job = core.JobStore(src)
            job.set(0, "Hello")

            txt_en = os.path.join(folder, "page_en.txt")
            core.export_page_text("Hello", "book.pdf", 0, txt_en,
                                  direction="fa2en")
            en_text = open(txt_en, encoding="utf-8-sig").read()
            self.assertIn("Translation of book.pdf", en_text)
            self.assertIn("Page 1", en_text)

            md_en = os.path.join(folder, "book_en.md")
            core.export_markdown(job, "book.pdf", md_en, direction="fa2en")
            self.assertIn("## Page 1", open(md_en, encoding="utf-8").read())

            md_fa = os.path.join(folder, "book_fa.md")
            core.export_markdown(job, "book.pdf", md_fa)
            self.assertIn("## صفحهٔ 1", open(md_fa, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
