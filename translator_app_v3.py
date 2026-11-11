# -*- coding: utf-8 -*-
"""
kaman ai translator v3 — ترجمهٔ کتاب‌های PDF/EPUB با هوش مصنوعی.

نسخهٔ ۳ شامل:
  - ترجمه بین سه زبان (انگلیسی، فارسی، عربی) در همهٔ جهت‌ها
  - رابط کاربری دوزبانه (فارسی / English) با چیدمان RTL/LTR خودکار
  - تکه‌تکه‌سازی خودکار + کنترل هوشمند کانتکست بین تکه‌ها و صفحات
  - ترجمهٔ خودکار کل کتاب با صف، توقف/ادامه و Resume از صفحهٔ ناتمام
  - تحلیل ساختار کتاب و Template اختصاصی هر کتاب (محلی و رایگان)
  - بازبینی و اصلاح خودکار کیفیت (QC loop) + علامت «بازبینی شد» انسانی
  - نمایش موازی متن مبدأ / تصویر صفحه در کنار ترجمه
  - ذخیرهٔ صفحه (TXT)، کل کتاب (Markdown)، خروجی کامل با تصاویر (HTML)
  - تنظیمات گرافیکی: API Key رمزنگاری‌شده (DPAPI)، موتور Gemini یا سرور
    سازگار با OpenAI (Ollama/LM Studio/…)، تم سیستم/دارک/لایت
"""

import os
import sys
import ctypes
import threading
import time

# In PyInstaller one-file builds, make the bundled Qt DLL directory explicit
# before importing any Qt extension module. Keep the handle alive for the
# process lifetime so Windows continues searching this directory first.
_QT_DLL_DIRECTORY_HANDLE = None
_QT_SYSTEM_ICU_HANDLES = []
if sys.platform == "win32" and getattr(sys, "frozen", False):
    _qt_dll_dir = os.path.join(sys._MEIPASS, "PyQt6", "Qt6", "bin")
    if os.path.isdir(_qt_dll_dir):
        os.environ["PATH"] = _qt_dll_dir + os.pathsep + os.environ.get("PATH", "")
        _QT_DLL_DIRECTORY_HANDLE = os.add_dll_directory(_qt_dll_dir)
    # QtCore imports the Windows ICU API. Preload the OS copies by absolute
    # path so unrelated ICU DLLs earlier on PATH cannot shadow those APIs.
    _system_dll_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for _icu_name in ("icuuc.dll", "icuin.dll"):
        _icu_path = os.path.join(_system_dll_dir, _icu_name)
        if os.path.isfile(_icu_path):
            try:
                _QT_SYSTEM_ICU_HANDLES.append(ctypes.WinDLL(_icu_path))
            except OSError:
                pass

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QFileDialog, QProgressBar, QFrame, QMessageBox,
    QScrollArea, QDialog, QComboBox, QLineEdit, QCheckBox, QSpinBox,
    QRadioButton, QMenu,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent, QObject, QTimer
from PyQt6.QtGui import QFont, QPixmap, QIcon, QTextCursor, QGuiApplication
import pymupdf  # PyMuPDF (نام جدید؛ بدون هشدار قدیمی fitz)

import kaman_core as core
from kaman_core import (
    APP_VERSION, DIRECTIONS, CONFIG_DEFAULTS,
    TranslationError, CancelledError, QuotaExhaustedError,
    load_config, save_config, validate_config, make_engine, resource_path,
    translate_page, review_translation, analyze_structure, structure_prompt_block,
    ai_structure_pass, ensure_indicator_assets, extract_page_text,
    JobStore, export_page_text, export_markdown, export_html,
)


# ============================== تم برنامه ==============================
# زبان بصری: «کاغذ و جوهر» — خنثی‌های گرمِ کاغذی/جوهری، یک لهجهٔ واحد
# (آبیِ جوهرِ نوشتار) فقط برای کنش اصلی، پیشرفت و انتخاب. ردیف‌های ابزار
# کارتِ شناور نیستند؛ با خط مویی (hairline) از هم جدا می‌شوند و دو پنلِ
# متن، مثل دو صفحهٔ روبه‌روی کتاب، تنها سطوحِ برجستهٔ پنجره‌اند.
# چند مقدار قدیمی عمداً نگه داشته شده‌اند چون تست‌های رگرسیون مالک آن‌ها
# را قفل کرده‌اند: #64748b راهنماهای تنظیمات در تم روشن، #cbd5e1 خط زیر
# عنوان بخش در تم روشن، #e2e8f0 شیار نوار پیشرفت در تم روشن، و
# قانون‌های وضعیت‌دارِ دکمهٔ کپی (QPushButton#btnCopy) در هر دو تم.

DARK_STYLESHEET = """
    QMainWindow { background-color: #171713; }
    QFrame { background: transparent; border: none; }
    QFrame#bar { border-bottom: 1px solid #37362c; padding: 2px 2px 10px; }
    QLabel { color: #ede9df; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 11pt; }
    QPushButton { background-color: #26261f; color: #ede9df; border: 1px solid #37362c; border-radius: 6px; padding: 8px 16px; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 10pt; }
    QPushButton:hover { background-color: #2e2d24; border-color: #4a493c; }
    QPushButton:pressed { background-color: #201f1a; }
    QPushButton:disabled { background-color: #1c1b16; color: #6f6c60; border-color: #2b2a22; }
    QPushButton#btnCopy { background-color: #26261f; color: #ede9df; border: 1px solid #37362c; }
    QPushButton#btnCopy:hover { background-color: #2e2d24; border-color: #4a493c; }
    QPushButton#btnCopy:disabled { background-color: #1c1b16; color: #6f6c60; border-color: #2b2a22; }
    QTextEdit { background-color: #201f1a; color: #f0ece1; border: 1px solid #37362c; border-radius: 8px; padding: 14px; selection-background-color: #1e40af; selection-color: white; }
    QProgressBar { border: none; background-color: #2b2b22; height: 6px; border-radius: 3px; }
    QProgressBar::chunk { background-color: #5b8def; border-radius: 3px; }
    QScrollArea { border: 1px solid #37362c; border-radius: 8px; background-color: #201f1a; }
    QComboBox { background-color: #201f1a; color: #ede9df; border: 1px solid #37362c; border-radius: 6px; padding: 7px 12px; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 10pt; }
    QComboBox:hover { background-color: #26261f; border-color: #4a493c; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox QAbstractItemView { background-color: #201f1a; color: #ede9df; border: 1px solid #37362c; selection-background-color: #1e40af; selection-color: white; }
    QLineEdit { background-color: #201f1a; color: #f0ece1; border: 1px solid #37362c; border-radius: 6px; padding: 8px 12px; font-size: 10pt; selection-background-color: #1e40af; selection-color: white; }
    QSpinBox { background-color: #201f1a; color: #f0ece1; border: 1px solid #37362c; border-radius: 6px; padding: 5px 8px 5px 26px; font-size: 10pt; }
    QSpinBox:disabled { background-color: #26261f; color: #a09c8f; border-color: #37362c; }
    QDialog { background-color: #171713; }
    QCheckBox, QRadioButton { color: #ede9df; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 10pt; background: transparent; spacing: 8px; }
    QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #6f6c60; background-color: #201f1a; }
    QCheckBox::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
    QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px; border: 1px solid #6f6c60; background-color: #201f1a; }
    QRadioButton::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
    QMenu { background-color: #201f1a; color: #ede9df; border: 1px solid #37362c; }
    QMenu::item:selected { background-color: #1e40af; color: white; }
    QMessageBox { background-color: #201f1a; }
    QDialog#settingsDialog { background-color: #171713; color: #ede9df; }
    QWidget#settingsContent { background-color: #171713; color: #ede9df; }
    QScrollArea#settingsScroll, QScrollArea#settingsScroll QWidget#settingsContent { background-color: #171713; border: none; }
"""

LIGHT_STYLESHEET = """
    QMainWindow { background-color: #f3f0e8; }
    QFrame { background: transparent; border: none; }
    QFrame#bar { border-bottom: 1px solid #c4b998; padding: 2px 2px 10px; }
    QLabel { color: #2b2723; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 11pt; }
    QPushButton { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; border-radius: 6px; padding: 8px 16px; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 10pt; }
    QPushButton:hover { background-color: #f7f1de; border-color: #978a68; }
    QPushButton:pressed { background-color: #ece2c8; }
    QPushButton:disabled { background-color: #e7dfc9; color: #7d7462; border-color: #c9bda0; }
    QPushButton#btnCopy { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; }
    QPushButton#btnCopy:hover { background-color: #f7f1de; border-color: #978a68; }
    QPushButton#btnCopy:disabled { background-color: #e7dfc9; color: #7d7462; border-color: #c9bda0; }
    QTextEdit { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; border-radius: 8px; padding: 14px; selection-background-color: #1e40af; selection-color: white; }
    QProgressBar { border: none; background-color: #e2e8f0; height: 6px; border-radius: 3px; }
    QProgressBar::chunk { background-color: #1e40af; border-radius: 3px; }
    QScrollArea { border: 1px solid #b3a888; border-radius: 8px; background-color: #fdfcf8; }
    QComboBox { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; border-radius: 6px; padding: 7px 12px; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 10pt; }
    QComboBox:hover { background-color: #f7f1de; border-color: #978a68; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox QAbstractItemView { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; selection-background-color: #1e40af; selection-color: white; }
    QLineEdit { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; border-radius: 6px; padding: 8px 12px; font-size: 10pt; selection-background-color: #1e40af; selection-color: white; }
    QSpinBox { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; border-radius: 6px; padding: 5px 8px 5px 26px; font-size: 10pt; }
    QSpinBox:disabled { background-color: #e7dfc9; color: #57534a; border-color: #c9bda0; }
    QDialog { background-color: #f3f0e8; }
    QCheckBox, QRadioButton { color: #2b2723; font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 10pt; background: transparent; spacing: 8px; }
    QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #8a7f66; background-color: #fdfcf8; }
    QCheckBox::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
    QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px; border: 1px solid #8a7f66; background-color: #fdfcf8; }
    QRadioButton::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
    QMenu { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; }
    QMenu::item:selected { background-color: #1e40af; color: white; }
    QMessageBox { background-color: #fdfcf8; }
    QDialog#settingsDialog { background-color: #f3f0e8; color: #2b2723; }
    QWidget#settingsContent { background-color: #f3f0e8; color: #2b2723; }
    QScrollArea#settingsScroll, QScrollArea#settingsScroll QWidget#settingsContent { background-color: #f3f0e8; border: none; }
"""


def system_scheme_is_dark():
    try:
        scheme = QApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            use_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return not bool(use_light)
        except (OSError, ImportError):
            pass
    app = QApplication.instance()
    if app is not None:
        try:
            return app.palette().color(app.palette().ColorRole.Window).lightness() < 128
        except Exception:
            pass
    return False


def effective_theme(cfg):
    theme = cfg.get("theme", "system")
    if theme == "system":
        return "dark" if system_scheme_is_dark() else "light"
    return "light" if theme == "light" else "dark"


def section_label(text, dark=True):
    """عنوان بخش با خط جداکننده — برای گروه‌بندی منظم دیالوگ‌ها."""
    lbl = QLabel(text)
    if dark:
        lbl.setStyleSheet(
            "font-weight: bold; font-size: 11pt; color: #d8d2c2;"
            "border-bottom: 1px solid #37362c; padding-bottom: 5px;"
        )
    else:
        lbl.setStyleSheet(
            "font-weight: bold; font-size: 11pt; color: #2b2723;"
            "border-bottom: 1px solid #cbd5e1; padding-bottom: 5px;"
        )
    return lbl


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_number(value):
    """عدد را با ارقام فارسی نمایش می‌دهد."""
    return str(value).translate(_FA_DIGITS)


# ============================== زبان رابط کاربری ==============================

_UI_LANG = "fa"

STRINGS = {
    "fa": {
        "no_file": "هیچ فایلی انتخاب نشده است",
        "settings": "⚙️ تنظیمات",
        "settings_title": "تنظیمات",
        "open_book": "انتخاب کتاب (PDF / EPUB)",
        "next_page": "◀ صفحه بعد",
        "prev_page": "صفحه قبل ▶",
        "page_label": "صفحه: {cur} / {total}",
        "translate_page": "ترجمهٔ این صفحه",
        "translate_book": "ترجمهٔ کل کتاب",
        "copy": "کپی",
        "copy_tip": "کل متن ترجمهٔ صفحهٔ فعلی را کپی می‌کند.\nفقط وقتی این صفحه ترجمه شده باشد فعال می‌شود؛ حالت خاکستری = غیرفعال.",
        "save": "ذخیره",
        "save_page_act": "ترجمهٔ صفحهٔ فعلی (TXT)…",
        "save_md_act": "کل کتاب (Markdown)…",
        "save_html_act": "کل کتاب با تصاویر (HTML)…",
        "src_lang": "🌐 زبان مبدأ:",
        "tgt_lang": "زبان مقصد:",
        "lang_en": "انگلیسی",
        "lang_fa": "فارسی",
        "lang_ar": "عربی",
        "lang_hint": "اگر مبدأ و مقصد یکی شود، دیگری خودکار جابه‌جا می‌شود و انتخابتان در همهٔ کتاب‌ها می‌ماند.",
        "view_source": "نمایش متن مبدأ",
        "view_image": "نمایش تصویر صفحه",
        "reviewed": "✓ بازبینی شد (تأیید انسانی)",
        "reviewed_tip": "✓ وقتی ترجمهٔ این صفحه را خودتان خواندید و تأیید کردید تیک بزنید.\nدر آمار (بازبینی‌شده) و خروجی نهایی کتاب لحاظ می‌شود.",
        "ready": "آماده",
        "legacy_job_archived": "{n} ترجمهٔ ذخیره‌شده از نسخهٔ قدیمی زبان مقصد مشخصی نداشت؛ برای جلوگیری از نمایش ترجمه با زبان اشتباه، نگه‌داری شد اما برای این زبان دوباره ترجمه می‌شود.",
        "pause": "⏸ توقف",
        "resume_btn": "▶ ادامه",
        "cancel_btn": "■ لغو",
        "cancel_plain": "انصراف",
        "page_image_title": "تصویر صفحه فعلی کتاب",
        "page_text_title": "متن مبدأ صفحهٔ فعلی",
        "image_placeholder": "تصویر صفحهٔ کتاب به محض بارگذاری اینجا رندر می‌شود.",
        "source_placeholder": "متن استخراج‌شدهٔ مبدأ این صفحه اینجا نمایش داده می‌شود.",
        "output_title": "📝 ترجمه",
        "output_placeholder": "پس از شروع ترجمه، متن ترجمه‌شده در این بخش ظاهر می‌شود.",
        "preparing": "در حال آماده‌سازی…",
        "page_done": "ترجمهٔ این صفحه تمام شد ✅",
        "page_failed": "ترجمه ناتمام ماند ❌",
        "unexpected": "خطای غیرمنتظره رخ داد:\n{detail}",
        "file_error": "خطا در باز کردن فایل:\n{detail}",
        "extract_error": "خطا در استخراج متن:\n{detail}",
        "render_error": "خطا در رندر تصویری صفحه:\n{detail}",
        "no_text_page": "(این صفحه متن استخراج‌پذیری ندارد — تصویر اسکن‌شده است)",
        "click_translate": "برای ترجمهٔ این صفحه روی «ترجمهٔ این صفحه» کلیک کنید.",
        "stats": "ترجمه‌شده: {done} از {total} | بازبینی‌شده: {rev}",
        "resume_hint": "🔄 {n} صفحه قبلاً ترجمه شده — برای ادامه «ترجمهٔ کل کتاب» را بزنید.",
        "structure_ai_running": "🧩 در حال تحلیل عمیق ساختار با هوش مصنوعی…",
        "structure_ai_done": "🧩 ساختار عمیق AI ذخیره شد ✅",
        "structure_ai_failed": "⚠️ تحلیل عمیق AI ناموفق بود (در تنظیمات قابل قطع است)",
        "open_title": "انتخاب کتاب",
        "settings_applied": "⚙️ تنظیمات جدید در ادامهٔ ترجمه اعمال می‌شود",
        "lang_changed_note": "زبان رابط برنامه تغییر کرد.",
        "restart_cleared": "🗑 ذخیرهٔ قبلی حذف شد — ترجمه از اول شروع می‌شود",
        "batch_header": "📚 ترجمهٔ خودکار — صفحهٔ {a} تا {b}",
        "qc_on": " | QC: روشن",
        "batch_starting": "شروع ترجمهٔ خودکار…",
        "copied": "📋 کپی شد",
        "percent": "{n}٪",
        "page_sep": "── صفحهٔ {p} ──",
        "paused_status": "⏸ توقف — ترجمه متوقف شد (ذخیره‌شده)",
        "resumed_status": "▶ ادامهٔ ترجمه…",
        "quota_status": "⏳ سهمیه پر شد — با «ادامه» دوباره شروع کنید",
        "quota_title": "سهمیهٔ API",
        "batch_done_title": "ترجمهٔ کل کتاب",
        "batch_failed_status": "❌ ترجمه ناتمام ماند",
        "error_title": "خطا در ترجمه",
        "resume_from_missing": "ادامهٔ ترجمه از صفحهٔ ناتمام…",
        "cancelling": "در حال لغو…",
        "cancelled_status": "ترجمه لغو شد",
        "wk_chunk": "تکهٔ {i} از {n}…",
        "wk_page": "در حال ترجمهٔ صفحه…",
        "wk_page_chunk": "صفحهٔ {p} — تکهٔ {i} از {n}",
        "wk_page_working": "صفحهٔ {p} — در حال ترجمه…",
        "wk_qc": "صفحهٔ {p} — بازبینی و اصلاح کیفیت (QC)…",
        "wk_all_done": "همهٔ صفحات این محدوده قبلاً ترجمه شده‌اند.",
        "wk_done": "ترجمهٔ {n} صفحه با موفقیت تمام شد.",
        "wk_remaining": "\n{n} صفحه باقی مانده است.",
        "wk_cancelled": "ترجمه لغو شد — {n} صفحه در این اجرا ترجمه شد.",
        "wk_quota_suffix": "\nترجمه‌های انجام‌شده ذخیره شد؛ با دکمهٔ «ادامه» از همان‌جا ادامه دهید.",
        "save_title": "ذخیره",
        "save_error": "ذخیره‌سازی انجام نشد:\n{detail}",
        "save_first_page": "ابتدا این صفحه را ترجمه کنید.",
        "save_page_title": "ذخیرهٔ ترجمهٔ صفحه",
        "saved_msg": "ذخیره شد:\n{path}",
        "save_none": "هنوز صفحه‌ای ترجمه نشده است.",
        "save_book_title": "ذخیرهٔ کل کتاب",
        "html_title": "خروجی HTML",
        "html_busy": "حین ترجمهٔ کل کتاب در دسترس نیست (همزمانی با PDF). می‌توانید Markdown را همین حالا ذخیره کنید.",
        "export_busy": "حین ترجمه در دسترس نیست؛ بعد از پایان یا توقف ترجمه دوباره تلاش کنید.",
        "html_dir_title": "پوشهٔ خروجی کتاب HTML",
        "html_done": "کتاب کامل با تصاویر ساخته شد:\n{path}\n\nهمهٔ تصاویر داخل همین یک فایل هستند و فایل پوشهٔ جانبی ندارد؛ می‌توانید آن را به‌تنهایی جابه‌جا یا ارسال کنید.\nبرای تبدیل به PDF: فایل را در مرورگر باز کنید و Print → Save as PDF.",
        "engine_label": "موتور ترجمه:",
        "provider_gemini": "Google Gemini",
        "provider_openai": "سرور سازگار با OpenAI (لوکال/ابری)",
        "base_label": "آدرس سرور سازگار با OpenAI (Base URL):",
        "gemini_endpoint_label": "درگاه/پراکسی Gemini (اختیاری):",
        "gemini_endpoint_ph": "خالی = اتصال مستقیم به Google؛ یا آدرس درگاه Gemini-native",
        "gemini_endpoint_hint": "اگر اتصال مستقیم Google از شبکهٔ شما کار نمی‌کند، آدرس یک درگاه سازگار با Gemini API را وارد کنید. متغیر HTTPS_PROXY ویندوز نیز پشتیبانی می‌شود. آدرس سرور OpenAI-compatible را اینجا وارد نکنید.",
        "gemini_proxy_label": "آدرس پراکسی شبکه (اختیاری):",
        "gemini_proxy_ph": "مثلاً http://127.0.0.1:7890",
        "gemini_proxy_hint": "اگر پراکسی/VPN شما آدرس محلی دارد، اینجا وارد کنید. اگر خالی بماند، برنامه متغیر سیستم HTTPS_PROXY را استفاده می‌کند.",
        "api_label": "API Key:",
        "show_key": "نمایش",
        "model_label": "مدل:",
        "key_ph_gemini": "کلید Google AI Studio",
        "key_ph_local": "کلید (برای سرور لوکال معمولاً دلخواه است)",
        "model_ph_openai": "خالی بگذارید تا برنامه از سرور مدل پیدا کند؛ مثلاً qwen2.5:14b",
        "model_ph_gemini": "gemini-3.8-flash",
        "encrypt_note": "کلید API به‌صورت رمزنگاری‌شده (DPAPI ویندوز) ذخیره می‌شود. تنظیمات و ترجمه‌های شما فقط در این پوشهٔ رایانهٔ شماست:",
        "open_folder": "باز کردن پوشه",
        "open_folder_tip": "پوشهٔ ذخیرهٔ تنظیمات، کلید رمزنگاری‌شده و ترجمه‌های شما را در ویندوز باز می‌کند.",
        "theme_label": "تم برنامه:",
        "theme_system": "سیستم (خودکار)",
        "theme_dark": "دارک",
        "theme_light": "لایت",
        "ui_lang_label": "زبان برنامه:",
        "ui_lang_hint": "زبان رابط پس از ذخیره فوراً اعمال می‌شود.",
        "local_hint": "سرور لوکال: مدل پیشنهادی qwen2.5:14b یا قوی‌تر است. در Ollama پنجرهٔ کانتکست پیش‌فرض کوچک است؛ برای کتاب‌های طولانی num_ctx را بالا ببرید (مثلاً 16384) وگرنه پاسخ‌ها نصفه قطع می‌شوند.",
        "structure_section": "ساختار کتاب و تمپلیت",
        "struct_auto": "تحلیل خودکار ساختار هنگام باز شدن فایل (محلی و رایگان)",
        "struct_ai": "تشخیص عمیق ساختار با هوش مصنوعی (۱ درخواست API برای هر فایل)",
        "struct_editor": "نمایش ویرایشگر تمپلیت (ویرایش دستی سرفصل‌ها و برچسب‌ها)",
        "headings_label": "سرفصل‌ها (هر خط یک مورد):",
        "headings_ph": "مثلاً: فصل اول: مقدمه / Chapter 1: Introduction",
        "labels_label": "برچسب‌های تکرارشونده (هر خط یک مورد):",
        "labels_ph": "مثلاً: بیشتر بدانید / فعالیت کنید / تمرین کنید / Key Terms",
        "editor_hint_job": "این فهرست‌ها در پرامپت ترجمه استفاده می‌شوند تا هر سرفصل/برچسبِ تکرارشوندهٔ همین کتاب همیشه یک‌جور ترجمه شود. پس از باز کردن فایل به‌صورت خودکار پر می‌شوند (رایگان و محلی)؛ اینجا می‌توانید اصلاح یا افزایششان کنید و با «ذخیرهٔ تنظیمات» برای همین فایل ثبت کنید.",
        "editor_hint_nojob": "این فهرست‌ها بعد از باز کردن یک فایل به‌صورت خودکار تحلیل و پر می‌شوند (رایگان و محلی). برای ویرایش دستی، ابتدا فایلی باز کنید.",
        "testing": "در حال تست اتصال…",
        "test_btn": "تست اتصال",
        "save_btn": "ذخیره",
        "batch_title": "ترجمهٔ خودکار کل کتاب",
        "range_section": "۱. محدودهٔ ترجمه",
        "all_pages": "کل کتاب ({n} صفحه)",
        "range_radio": "محدودهٔ خاصی از صفحات",
        "from_page": "از صفحهٔ:",
        "to_page": "تا صفحهٔ:",
        "resume_text": "🔄 {n} صفحه قبلاً ترجمه و ذخیره شده است — انتخاب کنید:",
        "keep_radio": "ادامه از اولین صفحهٔ ناتمام (ذخیرهٔ قبلی حفظ می‌شود — سریع‌تر)",
        "restart_radio": "ترجمه از اول شروع شود (ذخیرهٔ قبلی حذف می‌شود)",
        "options_section": "۲. گزینه‌ها",
        "structure_chk": "تحلیل ساختار کتاب و Template اختصاصی آن (محلی و رایگان)",
        "qc_chk": "بازبینی و اصلاح خودکار ترجمه (QC loop) — پیشنهادی؛ هزینهٔ API دو برابر",
        "delay_label": "تاخیر بین درخواست‌ها:",
        "delay_suffix": " ثانیه",
        "estimate": "صفحات این اجرا: {count} | ترجمه‌نشده: {remaining}",
        "start_btn": "▶ شروع ترجمه",
    },
    "en": {
        "no_file": "No file selected",
        "settings": "⚙️ Settings",
        "settings_title": "Settings",
        "open_book": "Open book (PDF / EPUB)",
        "next_page": "Next page ▶",
        "prev_page": "◀ Previous page",
        "page_label": "Page: {cur} / {total}",
        "translate_page": "Translate this page",
        "translate_book": "Translate whole book",
        "copy": "Copy",
        "copy_tip": "Copies the full translation of the current page.\nIt is enabled only when this page is translated; grey = disabled.",
        "save": "Save",
        "save_page_act": "Current page translation (TXT)…",
        "save_md_act": "Whole book (Markdown)…",
        "save_html_act": "Whole book with images (HTML)…",
        "src_lang": "🌐 Source language:",
        "tgt_lang": "Target language:",
        "lang_en": "English",
        "lang_fa": "Persian",
        "lang_ar": "Arabic",
        "lang_hint": "If source and target collide, the other one swaps automatically; your choice persists across all books.",
        "view_source": "Show source text",
        "view_image": "Show page image",
        "reviewed": "✓ Reviewed (human-approved)",
        "reviewed_tip": "✓ Tick this once you have read and approved this page's translation yourself.\nIt counts in the stats (reviewed) and in the final book output.",
        "ready": "Ready",
        "legacy_job_archived": "{n} saved page translations from an older version had no target-language metadata. They were preserved, but this language will be translated again to prevent mixing languages.",
        "pause": "⏸ Pause",
        "resume_btn": "▶ Resume",
        "cancel_btn": "■ Cancel",
        "cancel_plain": "Cancel",
        "page_image_title": "Current page image",
        "page_text_title": "Current page source text",
        "image_placeholder": "The page image will be rendered here once a book is loaded.",
        "source_placeholder": "The extracted source text of this page will appear here.",
        "output_title": "📝 Translation",
        "output_placeholder": "The translation will appear here once translation starts.",
        "preparing": "Preparing…",
        "page_done": "This page is translated ✅",
        "page_failed": "Translation stopped ❌",
        "unexpected": "Unexpected error:\n{detail}",
        "file_error": "Error opening the file:\n{detail}",
        "extract_error": "Error extracting text:\n{detail}",
        "render_error": "Error rendering the page image:\n{detail}",
        "no_text_page": "(This page has no extractable text — it is a scanned image)",
        "click_translate": "Click “Translate this page” to translate this page.",
        "stats": "Translated: {done} of {total} | Reviewed: {rev}",
        "resume_hint": "🔄 {n} pages already translated — press “Translate whole book” to continue.",
        "structure_ai_running": "🧩 Running deep AI structure analysis…",
        "structure_ai_done": "🧩 Deep AI structure saved ✅",
        "structure_ai_failed": "⚠️ Deep AI structure analysis failed (can be turned off in Settings)",
        "open_title": "Open book",
        "settings_applied": "⚙️ New settings will apply to the rest of the translation",
        "lang_changed_note": "App interface language changed.",
        "restart_cleared": "🗑 Previous progress cleared — translation restarts from the beginning",
        "batch_header": "📚 Auto translation — pages {a} to {b}",
        "qc_on": " | QC: on",
        "batch_starting": "Starting auto translation…",
        "copied": "📋 Copied",
        "percent": "{n}%",
        "page_sep": "── Page {p} ──",
        "paused_status": "⏸ Paused — translation stopped (saved)",
        "resumed_status": "▶ Resuming translation…",
        "quota_status": "⏳ Quota exhausted — press “Resume” to continue",
        "quota_title": "API quota",
        "batch_done_title": "Whole-book translation",
        "batch_failed_status": "❌ Translation stopped",
        "error_title": "Translation error",
        "resume_from_missing": "Resuming from the unfinished page…",
        "cancelling": "Cancelling…",
        "cancelled_status": "Translation cancelled",
        "wk_chunk": "Chunk {i} of {n}…",
        "wk_page": "Translating page…",
        "wk_page_chunk": "Page {p} — chunk {i} of {n}",
        "wk_page_working": "Page {p} — translating…",
        "wk_qc": "Page {p} — quality review (QC)…",
        "wk_all_done": "All pages in this range are already translated.",
        "wk_done": "Translated {n} pages successfully.",
        "wk_remaining": "\n{n} pages remaining.",
        "wk_cancelled": "Translation cancelled — {n} pages were translated in this run.",
        "wk_quota_suffix": "\nCompleted translations were saved; press “Resume” to continue from the same place.",
        "save_title": "Save",
        "save_error": "Saving failed:\n{detail}",
        "save_first_page": "Translate this page first.",
        "save_page_title": "Save page translation",
        "saved_msg": "Saved:\n{path}",
        "save_none": "No page has been translated yet.",
        "save_book_title": "Save whole book",
        "html_title": "HTML export",
        "html_busy": "Not available during whole-book translation (concurrent PDF access). You can save Markdown right now.",
        "export_busy": "Not available while translating; try again after it finishes or is paused.",
        "html_dir_title": "HTML book output folder",
        "html_done": "Full book with images created:\n{path}\n\nAll images are embedded in this single file — there is no side folder, so you can move or send the file on its own.\nTo make a PDF: open the file in a browser and use Print → Save as PDF.",
        "engine_label": "Translation engine:",
        "provider_gemini": "Google Gemini",
        "provider_openai": "OpenAI-compatible server (local/cloud)",
        "base_label": "OpenAI-compatible server URL (Base URL):",
        "gemini_endpoint_label": "Gemini gateway/proxy (optional):",
        "gemini_endpoint_ph": "Blank = direct Google connection; or enter a Gemini-native gateway URL",
        "gemini_endpoint_hint": "If direct Google access fails on your network, enter a Gemini API-compatible gateway URL. Windows HTTPS_PROXY is also supported. Do not enter an OpenAI-compatible endpoint here.",
        "gemini_proxy_label": "Network proxy URL (optional):",
        "gemini_proxy_ph": "e.g. http://127.0.0.1:7890",
        "gemini_proxy_hint": "If your proxy/VPN exposes a local address, enter it here. If blank, the app uses the system HTTPS_PROXY variable.",
        "api_label": "API Key:",
        "show_key": "Show",
        "model_label": "Model:",
        "key_ph_gemini": "Google AI Studio key",
        "key_ph_local": "Key (for local servers, usually arbitrary)",
        "model_ph_openai": "Leave blank to discover a server model; e.g. qwen2.5:14b",
        "model_ph_gemini": "gemini-3.8-flash",
        "encrypt_note": "The API key is stored encrypted (Windows DPAPI). Your settings and translations live only in this folder on your computer:",
        "open_folder": "Open folder",
        "open_folder_tip": "Opens the folder holding your settings, encrypted key and translations in Windows Explorer.",
        "theme_label": "App theme:",
        "theme_system": "System (auto)",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "ui_lang_label": "App language:",
        "ui_lang_hint": "The interface language takes effect as soon as you save.",
        "local_hint": "Local server: a recommended model is qwen2.5:14b or stronger. Ollama's default context window is small; for long books raise num_ctx (e.g. 16384) or replies will be cut off.",
        "structure_section": "Book structure & template",
        "struct_auto": "Automatic structure analysis when a file opens (local & free)",
        "struct_ai": "Deep structure detection with AI (1 API request per file)",
        "struct_editor": "Show template editor (manual heading/label editing)",
        "headings_label": "Headings (one per line):",
        "headings_ph": "e.g. Chapter 1: Introduction",
        "labels_label": "Repeated labels (one per line):",
        "labels_ph": "e.g. Key Terms / Did you know",
        "editor_hint_job": "These lists are used in the translation prompt so every repeated heading/label in this book is always translated the same way. They are filled automatically after opening a file (free & local); you can edit or extend them here and press “Save settings” to store them for this file.",
        "editor_hint_nojob": "These lists are analysed and filled automatically after you open a file (free & local). To edit them manually, open a file first.",
        "testing": "Testing connection…",
        "test_btn": "Test connection",
        "save_btn": "Save",
        "batch_title": "Whole-book auto translation",
        "range_section": "1. Translation range",
        "all_pages": "Whole book ({n} pages)",
        "range_radio": "A specific page range",
        "from_page": "From page:",
        "to_page": "To page:",
        "resume_text": "🔄 {n} pages are already translated and saved — choose:",
        "keep_radio": "Continue from the first unfinished page (previous progress kept — faster)",
        "restart_radio": "Restart translation from the beginning (previous progress deleted)",
        "options_section": "2. Options",
        "structure_chk": "Book structure analysis & its custom Template (local & free)",
        "qc_chk": "Automatic review & correction (QC loop) — recommended; doubles API cost",
        "delay_label": "Delay between requests:",
        "delay_suffix": " s",
        "estimate": "Pages in this run: {count} | Untranslated: {remaining}",
        "start_btn": "▶ Start translation",
    },
}


def set_ui_lang(lang):
    """زبان رابط کاربری + جهت چیدمان و زبان پیام‌های هسته را تنظیم می‌کند."""
    global _UI_LANG
    _UI_LANG = "en" if lang == "en" else "fa"
    core.set_language(_UI_LANG)


def S(key, **kwargs):
    table = STRINGS.get(_UI_LANG, STRINGS["fa"])
    text = table.get(key) or STRINGS["fa"][key]
    return text.format(**kwargs) if kwargs else text


def num(value):
    """عدد با ارقام متناسب با زبان رابط (فارسی → ارقام فارسی)."""
    return fa_number(value) if _UI_LANG == "fa" else str(value)


class _SpinAlignFilter(QObject):
    """فیلتر رویداد: تراز عدد اسپینر را بعد از نمایش/تعویض استایل دوباره اعمال می‌کند."""

    def __init__(self, apply_fn):
        super().__init__()
        self._apply = apply_fn

    def eventFilter(self, obj, event):
        if event.type() in (
            QEvent.Type.Show,
            QEvent.Type.StyleChange,
            QEvent.Type.Polish,
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            self._apply()
        return False


def align_spin_value_right(spin):
    """مقدار عددی اسپینر را سمت راست فیلد می‌گذارد (شروع سطر RTL).

    بدون این تراز صریح، عدد سمت چپ می‌افتد و زیر فلش‌های اسپینر
    (که در RTL سمت چپ هستند) گم و نامرئی می‌شود.
    لایه‌های ایمنی: اعمال فوری + تکرار هنگام تغییر مقدار، نمایش
    و تعویض استایل (تا هیچ‌وقت به حالت چپ برنگردد).
    """
    def _apply(*_args):
        for edit in spin.findChildren(QLineEdit):
            edit.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

    _apply()
    if not getattr(spin, "_kaman_align_hooked", False):
        spin.valueChanged.connect(_apply)
        filt = _SpinAlignFilter(_apply)
        spin.installEventFilter(filt)
        spin._kaman_align_filter = filt  # نگه‌داشتن مرجع تا GC نزند
        spin._kaman_align_hooked = True


# ============================== تردها ==============================

class ApiTestWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = dict(cfg)

    def run(self):
        try:
            engine = make_engine(self.cfg)
            ok, msg = engine.test()
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, str(exc)
        self.done.emit(ok, msg)


class AiStructureWorker(QThread):
    """پاس اختیاری AI برای شناسایی عمیق‌تر ساختار کتاب (۱ درخواست)."""

    done = pyqtSignal(object, dict)   # job صاحب نمونه، ساختار ادغام‌شده
    failed = pyqtSignal(str)

    def __init__(self, cfg, sample, local_structure=None, job=None):
        super().__init__()
        self.cfg = dict(cfg)
        self.sample = sample
        self.local = local_structure
        self.job = job   # کتابی که این پاس برای آن است (ضد نشت بین کتاب‌ها)

    def run(self):
        try:
            engine = make_engine(self.cfg)
            merged = ai_structure_pass(engine, self.sample, self.local)
            if merged:
                self.done.emit(self.job, merged)
            else:
                self.failed.emit("پاس AI چیزی برای افزودن برنگرداند.")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"تشخیص ساختار با AI ناموفق بود:\n{exc}")


class SinglePageWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    partial = pyqtSignal(str)
    result_ready = pyqtSignal(str, str)   # متن ترجمه، دنبالهٔ کانتکست جدید
    failed = pyqtSignal(str)

    def __init__(self, doc, page, cfg, direction, structure_block=None):
        super().__init__()
        self.doc = doc
        self.page = page
        self.cfg = dict(cfg)
        self.direction = direction
        self.structure_block = structure_block

    def run(self):
        try:
            err = validate_config(self.cfg)
            if err:
                self.failed.emit(err)
                return
            engine = make_engine(self.cfg)
            page_obj = self.doc.load_page(self.page)

            def on_prog(i, n):
                self.status.emit(
                    S("wk_chunk", i=i, n=n) if n > 1 else S("wk_page")
                )

            text, tail, _source = translate_page(
                engine, page_obj, self.cfg, self.direction,
                context_tail="", structure_block=self.structure_block,
                on_progress=on_prog, on_partial=self.partial.emit,
            )
            self.result_ready.emit(text, tail)
        except QuotaExhaustedError as exc:
            self.failed.emit(str(exc))
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(S("unexpected", detail=exc))


class BatchWorker(QThread):
    page_status = pyqtSignal(str)
    page_progress = pyqtSignal(int, int)
    page_done = pyqtSignal(int, str)
    page_started = pyqtSignal(int)   # شروع هر صفحه — برای دنبال‌کردن زنده در نما
    paused = pyqtSignal()
    resumed = pyqtSignal()
    quota_paused = pyqtSignal(str)
    finished_batch = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, doc, cfg, job, start, end, direction, structure_block,
                 qc, delay):
        super().__init__()
        self.doc = doc
        self.cfg = dict(cfg)
        self.cfg["request_delay_sec"] = float(delay or 0)  # تاخیر بین تکه‌ها هم اعمال شود
        self.job = job
        self.job.switch_direction(direction)
        self.start_page = start      # 0-based شامل
        self.end_page = end          # 0-based شامل
        self.direction = direction
        self.structure_block = structure_block
        self.qc = qc
        self.delay = float(delay or 0)
        self._run = threading.Event()
        self._run.set()
        self._cancel = False
        self._paused = False
        self._cfg_dirty = False   # تنظیمات ویرایش‌شده حین توقف

    # --- کنترل ---
    def is_paused(self):
        return self._paused

    def pause(self):
        self._run.clear()
        self._paused = True
        self.paused.emit()

    def resume(self):
        self._paused = False
        self._run.set()
        self.resumed.emit()

    def update_settings(self, cfg):
        """اعمال تنظیمات جدید حین توقف — موتور در صفحهٔ بعد بازساخته می‌شود."""
        self.cfg = dict(cfg)
        self.cfg["request_delay_sec"] = self.delay
        self._cfg_dirty = True

    def cancel(self):
        self._cancel = True
        self._run.set()

    def _continue(self):
        """ایست بین تکه‌ها هنگام توقف؛ لغو را فوراً اعمال می‌کند."""
        while not self._run.is_set():
            if self._cancel:
                return False
            time.sleep(0.1)
        return not self._cancel

    def _sleep(self, seconds):
        end_at = time.time() + seconds
        while time.time() < end_at:
            if not self._continue():
                raise CancelledError()
            time.sleep(0.1)

    def run(self):
        done_this_run = 0
        try:
            engine = make_engine(self.cfg)
            todo = self.job.missing_pages(self.start_page, self.end_page)
            total_todo = len(todo)
            if total_todo == 0:
                self.finished_batch.emit(S("wk_all_done"))
                return

            context = self.job.context_tail
            self.page_progress.emit(0, total_todo)

            for page in todo:
                if not self._continue():
                    raise CancelledError()
                if self._cfg_dirty:
                    engine = make_engine(self.cfg)  # تنظیمات جدید (کلید/مدل/آدرس) اعمال شد
                    self._cfg_dirty = False
                page_obj = self.doc.load_page(page)
                self.page_started.emit(page)

                def on_prog(i, n, page=page):
                    self.page_status.emit(S("wk_page_chunk", p=page + 1, i=i, n=n))

                def on_partial(_text, page=page):
                    self.page_status.emit(S("wk_page_working", p=page + 1))

                text, context, source = translate_page(
                    engine, page_obj, self.cfg, self.direction,
                    context_tail=context, structure_block=self.structure_block,
                    on_progress=on_prog, on_partial=on_partial,
                    should_continue=self._continue,
                )

                if self.qc and source:
                    if not self._continue():
                        raise CancelledError()
                    self.page_status.emit(S("wk_qc", p=page + 1))
                    text = review_translation(
                        engine, source, text, self.direction, self.cfg
                    )

                self.job.set(page, text)
                self.job.context_tail = context
                self.job.save()
                self.page_done.emit(page, text)

                done_this_run += 1
                self.page_progress.emit(done_this_run, total_todo)

                if self.delay > 0:
                    self._sleep(self.delay)

            remaining = len(self.job.missing_pages(self.start_page, self.end_page))
            msg = S("wk_done", n=done_this_run)
            if remaining:
                msg += S("wk_remaining", n=remaining)
            self.finished_batch.emit(msg)

        except CancelledError:
            self.finished_batch.emit(S("wk_cancelled", n=done_this_run))
        except QuotaExhaustedError as exc:
            self.quota_paused.emit(f"{exc}" + S("wk_quota_suffix"))
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(S("unexpected", detail=exc))


# ============================== دیالوگ تنظیمات ==============================

class SettingsDialog(QDialog):
    saved = pyqtSignal(dict)

    def __init__(self, cfg, parent=None, job=None):
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle(S("settings"))
        self.setMinimumWidth(560)
        self.cfg = core.switch_provider(
            dict(cfg), cfg.get("provider", "gemini")
        )
        self.job = job   # فایلِ باز جاری (برای ویرایشگر تمپلیت)
        self._test_worker = None
        self._provider = self.cfg.get("provider", "gemini")
        self._theme_mode = effective_theme(cfg)

        # پنجره نباید از صفحه بزرگ‌تر شود (گزارش کاربران: رفتن زیر تسک‌بار):
        # ارتفاع سقف‌دار + محتوای اسکرول‌دار، با دکمه‌های ثابت در پایین.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail_h = screen.availableGeometry().height()
            self.setMaximumHeight(max(420, avail_h - 30))
            self.resize(720, min(840, max(420, avail_h - 30)))

        outer = QVBoxLayout(self)
        content = QWidget()
        content.setObjectName("settingsContent")
        content.setAutoFillBackground(True)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)
        self._content_layout = layout

        # --- موتور ترجمه ---
        row = QHBoxLayout()
        row.addWidget(QLabel(S("engine_label")))
        self.combo_provider = QComboBox()
        self.combo_provider.addItem(S("provider_gemini"), "gemini")
        self.combo_provider.addItem(S("provider_openai"), "openai")
        provider = self.cfg.get("provider", "gemini")
        self.combo_provider.setCurrentIndex(0 if provider == "gemini" else 1)
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        row.addWidget(self.combo_provider, 1)
        layout.addLayout(row)

        # --- آدرس endpoint: پروفایل جدا برای OpenAI-compatible و Gemini ---
        hint_color = "#a39e93" if self._theme_mode == "dark" else "#64748b"
        self.row_base = QHBoxLayout()
        self.lbl_base = QLabel(S("base_label"))
        self.txt_base = QLineEdit(self.cfg.get("base_url", ""))
        self.txt_base.setPlaceholderText("http://localhost:11434/v1")
        self.row_base.addWidget(self.lbl_base)
        self.row_base.addWidget(self.txt_base, 1)
        layout.addLayout(self.row_base)
        self.lbl_gemini_hint = QLabel(S("gemini_endpoint_hint"))
        self.lbl_gemini_hint.setWordWrap(True)
        self.lbl_gemini_hint.setStyleSheet(f"color: {hint_color}; font-size: 9pt;")
        layout.addWidget(self.lbl_gemini_hint)
        proxy_row = QHBoxLayout()
        self.lbl_gemini_proxy = QLabel(S("gemini_proxy_label"))
        self.txt_gemini_proxy = QLineEdit(self.cfg.get("gemini_proxy", ""))
        self.txt_gemini_proxy.setPlaceholderText(S("gemini_proxy_ph"))
        proxy_row.addWidget(self.lbl_gemini_proxy)
        proxy_row.addWidget(self.txt_gemini_proxy, 1)
        layout.addLayout(proxy_row)
        self.lbl_gemini_proxy_hint = QLabel(S("gemini_proxy_hint"))
        self.lbl_gemini_proxy_hint.setWordWrap(True)
        self.lbl_gemini_proxy_hint.setStyleSheet(f"color: {hint_color}; font-size: 9pt;")
        layout.addWidget(self.lbl_gemini_proxy_hint)

        # --- API Key ---
        self.row_api = QHBoxLayout()
        self.row_api.addWidget(QLabel(S("api_label")))
        self.txt_api = QLineEdit(self.cfg.get("api_key", ""))
        self.txt_api.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_api.setPlaceholderText(S("key_ph_gemini"))
        self.chk_show = QCheckBox(S("show_key"))
        self.chk_show.toggled.connect(
            lambda on: self.txt_api.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        self.row_api.addWidget(self.txt_api, 1)
        self.row_api.addWidget(self.chk_show)
        layout.addLayout(self.row_api)

        # --- مدل ---
        self.row_model = QHBoxLayout()
        self.row_model.addWidget(QLabel(S("model_label")))
        self.txt_model = QLineEdit(self.cfg.get("model", ""))
        self.row_model.addWidget(self.txt_model, 1)
        layout.addLayout(self.row_model)

        # راهنمای سرور لوکال (فقط برای موتور سازگار با OpenAI دیده می‌شود)
        self.lbl_local_hint = QLabel(S("local_hint"))
        self.lbl_local_hint.setWordWrap(True)
        hint_color = "#a39e93" if self._theme_mode == "dark" else "#64748b"
        self.lbl_local_hint.setStyleSheet(f"color: {hint_color}; font-size: 9pt;")
        layout.addWidget(self.lbl_local_hint)

        self.lbl_encrypt = QLabel(S("encrypt_note"))
        self.lbl_encrypt.setStyleSheet(f"color: {hint_color}; font-size: 9pt;")
        layout.addWidget(self.lbl_encrypt)

        data_row = QHBoxLayout()
        self.lbl_data_dir = QLabel(core.config_dir())
        dir_color = "#b3aea0" if self._theme_mode == "dark" else "#57534a"
        self.lbl_data_dir.setStyleSheet(
            f"color: {dir_color}; font-size: 9pt; font-family: Consolas, monospace;"
        )
        self.lbl_data_dir.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        data_row.addWidget(self.lbl_data_dir, 1)
        self.btn_open_data = QPushButton(S("open_folder"))
        self.btn_open_data.setToolTip(S("open_folder_tip"))
        self.btn_open_data.clicked.connect(self.open_data_folder)
        data_row.addWidget(self.btn_open_data)
        layout.addLayout(data_row)

        # --- تم ---
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel(S("theme_label")))
        self.combo_theme = QComboBox()
        self.combo_theme.addItem(S("theme_system"), "system")
        self.combo_theme.addItem(S("theme_dark"), "dark")
        self.combo_theme.addItem(S("theme_light"), "light")
        wanted = self.cfg.get("theme", "system")
        for i in range(self.combo_theme.count()):
            if self.combo_theme.itemData(i) == wanted:
                self.combo_theme.setCurrentIndex(i)
                break
        theme_row.addWidget(self.combo_theme, 1)
        layout.addLayout(theme_row)

        # --- زبان رابط کاربری ---
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(S("ui_lang_label")))
        self.combo_ui_lang = QComboBox()
        self.combo_ui_lang.addItem("فارسی", "fa")
        self.combo_ui_lang.addItem("English", "en")
        wanted_lang = self.cfg.get("ui_lang", "fa")
        for i in range(self.combo_ui_lang.count()):
            if self.combo_ui_lang.itemData(i) == wanted_lang:
                self.combo_ui_lang.setCurrentIndex(i)
                break
        lang_row.addWidget(self.combo_ui_lang, 1)
        layout.addLayout(lang_row)
        lbl_lang_hint = QLabel(S("ui_lang_hint"))
        lbl_lang_hint.setWordWrap(True)
        lbl_lang_hint.setStyleSheet(f"color: {hint_color}; font-size: 9pt;")
        layout.addWidget(lbl_lang_hint)

        # --- ساختار کتاب / تمپلیت (سه سوییچ جداگانه) ---
        layout.addWidget(section_label(
            S("structure_section"), dark=(self._theme_mode == "dark")
        ))

        self.chk_struct_auto = QCheckBox(S("struct_auto"))
        self.chk_struct_auto.setChecked(bool(self.cfg.get("structure_auto", True)))
        layout.addWidget(self.chk_struct_auto)

        self.chk_struct_ai = QCheckBox(S("struct_ai"))
        self.chk_struct_ai.setChecked(bool(self.cfg.get("structure_ai", False)))
        layout.addWidget(self.chk_struct_ai)

        self.chk_struct_editor = QCheckBox(S("struct_editor"))
        self.chk_struct_editor.setChecked(bool(self.cfg.get("structure_editor", True)))
        layout.addWidget(self.chk_struct_editor)

        self.editor_widget = QWidget()
        ev = QVBoxLayout(self.editor_widget)
        ev.setContentsMargins(4, 8, 4, 0)
        ev.setSpacing(6)
        ev.addWidget(QLabel(S("headings_label")))
        self.txt_headings = QTextEdit()
        self.txt_headings.setFixedHeight(84)
        self.txt_headings.setPlaceholderText(S("headings_ph"))
        ev.addWidget(self.txt_headings)
        ev.addWidget(QLabel(S("labels_label")))
        self.txt_labels = QTextEdit()
        self.txt_labels.setFixedHeight(64)
        self.txt_labels.setPlaceholderText(S("labels_ph"))
        ev.addWidget(self.txt_labels)
        self.lbl_editor_hint = QLabel("")
        self.lbl_editor_hint.setWordWrap(True)
        self.lbl_editor_hint.setStyleSheet(f"color: {hint_color}; font-size: 9pt;")
        ev.addWidget(self.lbl_editor_hint)

        if self.job and self.job.structure:
            self.txt_headings.setPlainText(
                "\n".join(self.job.structure.get("headings", []))
            )
            self.txt_labels.setPlainText(
                "\n".join(self.job.structure.get("labels", []))
            )
        if self.job:
            self.lbl_editor_hint.setText(S("editor_hint_job"))
        else:
            self.lbl_editor_hint.setText(S("editor_hint_nojob"))
            self.txt_headings.setEnabled(False)
            self.txt_labels.setEnabled(False)
        self.chk_struct_editor.toggled.connect(self.editor_widget.setVisible)
        self.editor_widget.setVisible(self.chk_struct_editor.isChecked())
        layout.addWidget(self.editor_widget)

        # --- مونتاژ نهایی: محتوای اسکرول‌دار + وضعیت و دکمه‌های ثابت ---
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        outer.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        self.btn_test = QPushButton(S("test_btn"))
        self.btn_test.clicked.connect(self.test_connection)
        btn_save = QPushButton(S("save_btn"))
        btn_save.clicked.connect(self.save)
        btn_cancel = QPushButton(S("cancel_plain"))
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_test)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        outer.addLayout(btn_row)

        self._on_provider_changed()

    def open_data_folder(self):
        """باز کردن پوشهٔ داده‌ها (%APPDATA%) در اکسپلورر ویندوز."""
        path = core.config_dir()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _on_provider_changed(self, *_args):
        new_provider = self.combo_provider.currentData()
        if new_provider != self._provider:
            # حافظهٔ جدا برای هر موتور: مقادیر فعلی فیلدها در پروفایل موتور
            # قبلی ذخیره و مقادیر ذخیره‌شدهٔ موتور جدید بارگذاری می‌شود —
            # هیچ کلید/آدرس/مدلی از یک موتور به دیگری نمی‌رسد و با برگشتن
            # به موتور قبلی، اطلاعاتش دقیقاً همان قبلی است.
            self.cfg["api_key"] = self.txt_api.text().strip()
            self.cfg["base_url"] = self.txt_base.text().strip()
            self.cfg["model"] = self.txt_model.text().strip()
            self.cfg["gemini_proxy"] = self.txt_gemini_proxy.text().strip()
            if self._provider == "gemini":
                self.cfg["gemini_endpoint_version"] = 1
            if self._provider == "gemini":
                self.cfg["gemini_endpoint_version"] = 1
            core.switch_provider(self.cfg, new_provider)
            self.txt_base.setText(self.cfg.get("base_url", ""))
            self.txt_api.setText(self.cfg.get("api_key", ""))
            self.txt_model.setText(self.cfg.get("model", ""))
            self.txt_gemini_proxy.setText(self.cfg.get("gemini_proxy", ""))
            self._provider = new_provider
        is_openai = new_provider == "openai"
        self.lbl_base.setText(S("base_label") if is_openai else S("gemini_endpoint_label"))
        self.txt_base.setPlaceholderText(
            "http://localhost:11434/v1" if is_openai else S("gemini_endpoint_ph")
        )
        self.lbl_base.setVisible(True)
        self.txt_base.setVisible(True)
        self.lbl_local_hint.setVisible(is_openai)
        self.lbl_gemini_hint.setVisible(not is_openai)
        self.lbl_gemini_proxy.setVisible(not is_openai)
        self.txt_gemini_proxy.setVisible(not is_openai)
        self.lbl_gemini_proxy_hint.setVisible(not is_openai)
        if is_openai:
            self.txt_api.setPlaceholderText(S("key_ph_local"))
            self.txt_model.setPlaceholderText(S("model_ph_openai"))
        else:
            self.txt_api.setPlaceholderText(S("key_ph_gemini"))
            self.txt_model.setPlaceholderText(S("model_ph_gemini"))

    def _collect(self):
        cfg = dict(self.cfg)
        cfg["provider"] = self.combo_provider.currentData()
        cfg["base_url"] = self.txt_base.text().strip()
        cfg["api_key"] = self.txt_api.text().strip()
        cfg["model"] = self.txt_model.text().strip()
        cfg["gemini_proxy"] = self.txt_gemini_proxy.text().strip()
        if cfg["provider"] == "gemini":
            cfg["gemini_endpoint_version"] = 1
        if cfg["provider"] == "gemini":
            cfg["gemini_endpoint_version"] = 1
        cfg["theme"] = self.combo_theme.currentData()
        cfg["ui_lang"] = self.combo_ui_lang.currentData()
        cfg["structure_auto"] = self.chk_struct_auto.isChecked()
        cfg["structure_ai"] = self.chk_struct_ai.isChecked()
        cfg["structure_editor"] = self.chk_struct_editor.isChecked()
        return cfg

    def test_connection(self):
        cfg = self._collect()
        err = validate_config(cfg)
        if err:
            self.lbl_status.setText(f"❌ {err}")
            return
        self.btn_test.setEnabled(False)
        self.lbl_status.setText(S("testing"))
        self._test_worker = ApiTestWorker(cfg)
        self._test_worker.done.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self, ok, message):
        self.lbl_status.setText(message)
        self.btn_test.setEnabled(True)
        self._test_worker = None

    def save(self):
        cfg = self._collect()
        self.cfg = cfg
        save_config(cfg)
        # ثبت ویرایشگر تمپلیت برای فایلِ باز جاری
        if self.job is not None and self.chk_struct_editor.isChecked():
            structure = dict(self.job.structure or {})
            structure["headings"] = [
                x.strip() for x in self.txt_headings.toPlainText().splitlines() if x.strip()
            ]
            structure["labels"] = [
                x.strip() for x in self.txt_labels.toPlainText().splitlines() if x.strip()
            ]
            had_template = bool(
                (self.job.structure or {}).get("headings")
                or (self.job.structure or {}).get("labels")
            )
            # خالی کردن هر دو کادر هم باید ثبت شود (حذف تمپلیت) — ولی ذخیرهٔ
            # دست‌نخوردهٔ ویرایشگر خالی، تمپلیت خالیِ بازدارنده نمی‌سازد
            if structure["headings"] or structure["labels"] or had_template:
                self.job.structure = structure
                self.job.save()
        self.saved.emit(dict(cfg))
        self.accept()


# ============================== دیالوگ ترجمهٔ کل کتاب ==============================

class BatchDialog(QDialog):
    """دیالوگ ترجمهٔ کل کتاب — بخش‌بندی منظم با حاشیه و فاصله‌های یکنواخت."""

    def __init__(self, total_pages, job, parent=None, structure_default=True):
        super().__init__(parent)
        self.setWindowTitle(S("batch_title"))
        self.setMinimumWidth(560)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setMaximumHeight(max(380, screen.availableGeometry().height() - 30))
        self._total = total_pages
        self.job = job
        self._theme_mode = effective_theme(parent.cfg if parent else {})

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # --- بخش ۱: محدوده ---
        layout.addWidget(section_label(
            S("range_section"), dark=(self._theme_mode == "dark")
        ))
        self.radio_all = QRadioButton(S("all_pages", n=num(total_pages)))
        self.radio_all.setChecked(True)
        self.radio_range = QRadioButton(S("range_radio"))
        layout.addWidget(self.radio_all)
        layout.addWidget(self.radio_range)

        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        range_row.addWidget(QLabel(S("from_page")))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(1, max(1, total_pages))
        self.spin_start.setValue(1)
        # حداقل عرض کافی تا عدد تک‌رقمی («۱») هم دیده شود و اسپینر فشرده نشود
        self.spin_start.setMinimumWidth(110)
        align_spin_value_right(self.spin_start)
        range_row.addWidget(self.spin_start)
        range_row.addWidget(QLabel(S("to_page")))
        self.spin_end = QSpinBox()
        self.spin_end.setRange(1, max(1, total_pages))
        self.spin_end.setValue(max(1, total_pages))
        self.spin_end.setMinimumWidth(110)
        align_spin_value_right(self.spin_end)
        range_row.addWidget(self.spin_end)
        range_row.addStretch()
        layout.addLayout(range_row)

        self.radio_all.toggled.connect(self._update_range_enabled)
        self.spin_start.valueChanged.connect(self._update_estimate)
        self.spin_end.valueChanged.connect(self._update_estimate)

        # --- اطلاع ادامه + انتخاب «ادامه یا شروع از اول» ---
        self.radio_keep = None
        self.radio_restart = None
        self.lbl_resume = QLabel("")
        self.lbl_resume.setWordWrap(True)
        resume_color = "#8fb0ea" if self._theme_mode == "dark" else "#1e40af"
        self.lbl_resume.setStyleSheet(f"color: {resume_color}; font-size: 9pt;")
        layout.addWidget(self.lbl_resume)
        completed = job.count() if job else 0
        if completed:
            self.lbl_resume.setText(S("resume_text", n=num(completed)))
            self.radio_keep = QRadioButton(S("keep_radio"))
            self.radio_restart = QRadioButton(S("restart_radio"))
            self.radio_keep.setChecked(True)
            layout.addWidget(self.radio_keep)
            layout.addWidget(self.radio_restart)
            self.radio_restart.toggled.connect(self._update_estimate)
        else:
            self.lbl_resume.hide()

        # --- بخش ۲: گزینه‌ها ---
        layout.addWidget(section_label(
            S("options_section"), dark=(self._theme_mode == "dark")
        ))
        self.chk_structure = QCheckBox(S("structure_chk"))
        self.chk_structure.setChecked(bool(structure_default))
        layout.addWidget(self.chk_structure)

        self.chk_qc = QCheckBox(S("qc_chk"))
        self.chk_qc.setChecked(True)
        layout.addWidget(self.chk_qc)

        delay_row = QHBoxLayout()
        delay_row.setSpacing(8)
        delay_row.addWidget(QLabel(S("delay_label")))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 30)
        self.spin_delay.setSuffix(S("delay_suffix"))
        self.spin_delay.setValue(int(CONFIG_DEFAULTS["request_delay_sec"]))
        self.spin_delay.setMinimumWidth(110)
        align_spin_value_right(self.spin_delay)
        delay_row.addWidget(self.spin_delay)
        delay_row.addStretch()
        layout.addLayout(delay_row)

        # --- جمع‌بندی + دکمه‌ها (تفویق بصری: شروع پررنگ، انصراف خنثی) ---
        self.lbl_estimate = QLabel("")
        estimate_color = "#a39e93" if self._theme_mode == "dark" else "#57534a"
        self.lbl_estimate.setStyleSheet(f"color: {estimate_color}; font-size: 9pt;")
        layout.addWidget(self.lbl_estimate)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()
        self.btn_cancel = QPushButton(S("cancel_plain"))
        self.btn_cancel.setMinimumWidth(120)
        if self._theme_mode == "dark":
            self.btn_cancel.setStyleSheet(
                "QPushButton { background-color: #26261f; color: #ede9df; border: 1px solid #37362c; border-radius: 6px; padding: 8px 16px; }"
                "QPushButton:hover { background-color: #2e2d24; }"
            )
        else:
            self.btn_cancel.setStyleSheet(
                "QPushButton { background-color: #fdfcf8; color: #2b2723; border: 1px solid #b3a888; border-radius: 6px; padding: 8px 16px; }"
                "QPushButton:hover { background-color: #f7f1de; }"
            )
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_start = QPushButton(S("start_btn"))
        self.btn_start.setMinimumWidth(150)
        if self._theme_mode == "dark":
            self.btn_start.setStyleSheet(
                "QPushButton { background-color: #1e40af; color: #ffffff; font-weight: bold; border: 1px solid #1e40af; border-radius: 6px; padding: 8px 16px; }"
                "QPushButton:hover { background-color: #2a52b8; border-color: #2a52b8; }"
            )
        else:
            self.btn_start.setStyleSheet(
                "QPushButton { background-color: #1e40af; color: #ffffff; font-weight: bold; border: 1px solid #1e40af; border-radius: 6px; padding: 8px 16px; }"
                "QPushButton:hover { background-color: #1e3a8a; border-color: #1e3a8a; }"
            )
        self.btn_start.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_start)
        layout.addLayout(btn_row)

        self._update_range_enabled()

    def showEvent(self, event):
        """آخرین لایهٔ ایمنی: تراز عدد اسپین‌ها درست پیش از نمایش دوباره اعمال می‌شود."""
        super().showEvent(event)
        for spin in (self.spin_start, self.spin_end, self.spin_delay):
            align_spin_value_right(spin)

    def _update_range_enabled(self, *_args):
        enabled = self.radio_range.isChecked()
        self.spin_start.setEnabled(enabled)
        self.spin_end.setEnabled(enabled)
        self._update_estimate()

    def wants_restart(self):
        """آیا کاربر خواسته ترجمه از اول (با حذف ذخیرهٔ قبلی) شروع شود؟"""
        return self.radio_restart is not None and self.radio_restart.isChecked()

    def _update_estimate(self, *_args):
        start, end = self.range_0based()
        count = end - start + 1
        if self.wants_restart():
            remaining = count  # همه از نو ترجمه می‌شوند
        else:
            remaining = count
            if self.job is not None:
                remaining = len(self.job.missing_pages(start, end))
        self.lbl_estimate.setText(
            S("estimate", count=num(count), remaining=num(remaining))
        )

    def range_0based(self):
        if self.radio_range.isChecked():
            a = self.spin_start.value() - 1
            b = self.spin_end.value() - 1
            if a > b:
                a, b = b, a
            return a, b
        return 0, self._total - 1


# ============================== پنجرهٔ اصلی ==============================

class ModernTranslatorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = None
        self.current_file = None
        self.current_page = 0
        self.total_pages = 0
        self.job = None
        self.structure = None
        self.view_source = False

        self.single_worker = None
        self.batch_worker = None
        self.batch_params = None
        self.structure_worker = None
        self._awaiting_first_chunk = False
        self.view_doc = None      # دستگاه دوم pymupdf برای نمایش (ایمنی ریسمان حین ترجمهٔ کل کتاب)
        self._following_batch = False  # دنبال‌کردن زندهٔ صفحهٔ در حال ترجمه
        self._src_lang = "en"          # زبان مبدأ فعلی (همگام با cfg.direction)
        self._tgt_lang = "fa"          # زبان مقصد فعلی

        self.cfg = load_config()
        set_ui_lang(self.cfg.get("ui_lang", "fa"))

        # جهت چیدمان سراسری از زبان رابط پیروی می‌کند (فارسی → راست‌چین،
        # انگلیسی → چپ‌چین)؛ همهٔ دیالوگ‌ها، منوها و چیدمان‌های بدون جهتِ
        # صریح از همین‌جا ارث می‌برند.
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.setLayoutDirection(
                Qt.LayoutDirection.RightToLeft if _UI_LANG == "fa"
                else Qt.LayoutDirection.LeftToRight
            )

        self.init_ui()
        self.apply_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
        except Exception:
            pass

    def closeEvent(self, event):
        # بستن امن حین ترجمه: اول لغو را علامت می‌زنیم و کمی صبر می‌کنیم تا
        # تردها تمیز تمام شوند؛ اگر درخواستی گیر کرده باشد بستن معطل نمی‌ماند
        workers = (self.single_worker, self.batch_worker, self.structure_worker)
        for worker in workers:
            if worker is not None and worker.isRunning() and hasattr(worker, "cancel"):
                worker.cancel()
        for worker in workers:
            if worker is not None and worker.isRunning():
                worker.wait(1500)
        event.accept()

    # ----------------------------- UI -----------------------------
    def init_ui(self):
        self.setWindowTitle(f"kaman ai translator v{APP_VERSION}")
        self.setWindowIcon(QIcon(resource_path("icon.png")))
        self.resize(1280, 880)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        # راست‌چینیِ سراسری از app.setLayoutDirection(RightToLeft) ارث برده می‌شود.
        # هرگز روی لایوت‌ها setDirection(RightToLeft) صریح نگذارید: در ترکیب با
        # RTL سراسری، Qt آن را دوباره می‌چرخاند و خروجی LTR می‌شود (تست شده).
        # همچنین setDirection روی QVBoxLayout لایوت را «افقی» می‌کند.
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # هدر
        header_frame = QFrame()
        header_frame.setObjectName("bar")
        header_layout = QHBoxLayout(header_frame)
        self.lbl_file = QLabel(S("no_file"))
        self.btn_settings = QPushButton(S("settings"))
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_open = QPushButton(S("open_book"))
        self.btn_open.clicked.connect(self.open_file)
        header_layout.addWidget(self.lbl_file)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_settings)
        header_layout.addWidget(self.btn_open)

        # ناوبری
        nav_frame = QFrame()
        nav_frame.setObjectName("bar")
        nav_layout = QHBoxLayout(nav_frame)
        self.btn_next = QPushButton(S("next_page"))
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self.next_page)
        self.lbl_page = QLabel(S("page_label", cur=num(0), total=num(0)))
        self.btn_prev = QPushButton(S("prev_page"))
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self.prev_page)

        self.btn_translate = QPushButton(S("translate_page"))
        self.btn_translate.setEnabled(False)
        self.btn_translate.clicked.connect(self.translate_current_page)

        self.btn_batch = QPushButton(S("translate_book"))
        self.btn_batch.setEnabled(False)
        self.btn_batch.clicked.connect(self.start_batch)

        self.btn_copy = QPushButton(S("copy"))
        self.btn_copy.setObjectName("btnCopy")  # رنگ فعال/غیرفعال از stylesheet (بدون خاکستری دائمی)
        self.btn_copy.setToolTip(S("copy_tip"))
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_translation)

        self.btn_save = QPushButton(S("save"))
        self.btn_save.setEnabled(False)
        save_menu = QMenu(self)
        self.act_save_page = save_menu.addAction(
            S("save_page_act"), self.save_current_page
        )
        self.act_save_md = save_menu.addAction(
            S("save_md_act"), self.save_book_markdown
        )
        self.act_save_html = save_menu.addAction(
            S("save_html_act"), self.save_book_html
        )
        self.btn_save.setMenu(save_menu)

        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(self.lbl_page)
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_copy)
        nav_layout.addWidget(self.btn_save)
        nav_layout.addWidget(self.btn_translate)
        nav_layout.addWidget(self.btn_batch)

        # ردیف زبان مبدأ / مقصد (قفل دوگانه: هرگز یکی نمی‌شوند)
        lang_frame = QFrame()
        lang_frame.setObjectName("bar")
        lang_layout = QHBoxLayout(lang_frame)

        self.lbl_src_lang = QLabel(S("src_lang"))
        self.combo_src = QComboBox()
        self.combo_src.addItem(S("lang_en"), "en")
        self.combo_src.addItem(S("lang_fa"), "fa")
        self.combo_src.addItem(S("lang_ar"), "ar")

        self.lbl_tgt_lang = QLabel(S("tgt_lang"))
        self.combo_tgt = QComboBox()
        self.combo_tgt.addItem(S("lang_en"), "en")
        self.combo_tgt.addItem(S("lang_fa"), "fa")
        self.combo_tgt.addItem(S("lang_ar"), "ar")

        direction = self.cfg.get("direction", "en2fa")
        parts = direction.split("2")
        if len(parts) == 2 and parts[0] in ("en", "fa", "ar") and parts[1] in ("en", "fa", "ar"):
            self._src_lang, self._tgt_lang = parts
        self._sync_combo(self.combo_src, self._src_lang)
        self._sync_combo(self.combo_tgt, self._tgt_lang)
        self.combo_src.currentIndexChanged.connect(self.on_src_changed)
        self.combo_tgt.currentIndexChanged.connect(self.on_tgt_changed)

        self.lbl_lang_hint = QLabel(S("lang_hint"))
        lang_hint_color = "#a39e93" if effective_theme(self.cfg) == "dark" else "#57534a"
        self.lbl_lang_hint.setStyleSheet(f"color: {lang_hint_color}; font-size: 9pt;")

        lang_layout.addWidget(self.lbl_src_lang)
        lang_layout.addWidget(self.combo_src)
        lang_layout.addSpacing(20)
        lang_layout.addWidget(self.lbl_tgt_lang)
        lang_layout.addWidget(self.combo_tgt)
        lang_layout.addSpacing(20)
        lang_layout.addWidget(self.lbl_lang_hint)
        lang_layout.addStretch()

        # ردیف بازبینی
        review_frame = QFrame()
        review_frame.setObjectName("bar")
        review_layout = QHBoxLayout(review_frame)
        self.btn_view_source = QPushButton(S("view_source"))
        self.btn_view_source.setEnabled(False)
        self.btn_view_source.clicked.connect(self.toggle_view)
        self.chk_reviewed = QCheckBox(S("reviewed"))
        self.chk_reviewed.setToolTip(S("reviewed_tip"))
        self.chk_reviewed.setEnabled(False)
        self.chk_reviewed.toggled.connect(self.on_reviewed_toggled)
        self.lbl_stats = QLabel("")
        review_layout.addWidget(self.btn_view_source)
        review_layout.addWidget(self.chk_reviewed)
        review_layout.addWidget(self.lbl_stats)
        review_layout.addStretch()

        # نوار وضعیت / کنترل ترجمه (مشترک تک‌صفحه و کل کتاب)
        status_frame = QFrame()
        status_frame.setObjectName("bar")
        status_layout = QHBoxLayout(status_frame)
        self.lbl_status = QLabel(S("ready"))
        self.lbl_status.setStyleSheet("font-weight: bold;")
        self.btn_pause = QPushButton(S("pause"))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_cancel_batch = QPushButton(S("cancel_btn"))
        self.btn_cancel_batch.setEnabled(False)
        self.btn_cancel_batch.clicked.connect(self.on_cancel_batch)
        status_layout.addWidget(self.btn_pause)
        status_layout.addWidget(self.btn_cancel_batch)
        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()
        self._status_controls = (self.btn_pause, self.btn_cancel_batch)
        status_frame.setVisible(False)
        self._status_frame = status_frame
        # نوار وضعیت فقط هنگام فعالیت دیده می‌شود: وقتی کاری در جریان نیست،
        # چند ثانیه بعد از آخرین پیام خودش مخفی می‌شود (قبلاً هر وقت ظاهر
        # می‌شد تا بستن برنامه می‌ماند و صفحه را شلوغ می‌کرد).
        self._status_hide_timer = QTimer(self)
        self._status_hide_timer.setSingleShot(True)
        self._status_hide_timer.timeout.connect(self._hide_status_if_idle)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)  # متن داخلی Qt سمت چپ رسم می‌شد؛ حذف شد
        self.progress_bar.setVisible(False)
        # درصد، جداگانه و در سمت راست نوار (شروع سطر RTL)
        self.lbl_percent = QLabel(S("percent", n=num(0)))
        self.lbl_percent.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.lbl_percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_percent.setMinimumWidth(48)
        self.lbl_percent.setVisible(False)

        # فضای کاری: پنل صفحهٔ مبدأ سمت راست، پنل ترجمه سمت چپ
        # (در RTL اولین آیتمِ لایوت افقی، سمت راست قرار می‌گیرد)
        workspace_layout = QHBoxLayout()
        workspace_layout.setSpacing(12)

        page_column = QVBoxLayout()
        self.lbl_page_title = QLabel(S("page_image_title"))
        self.lbl_page_title.setStyleSheet("font-weight: bold;")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.lbl_image_viewer = QLabel()
        self.lbl_image_viewer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image_viewer.setText(S("image_placeholder"))
        self.scroll_area.setWidget(self.lbl_image_viewer)

        self.txt_source = QTextEdit()
        self.txt_source.setReadOnly(True)
        self.txt_source.setFont(QFont("Georgia", 11))
        self.txt_source.setVisible(False)
        self.txt_source.setPlaceholderText(S("source_placeholder"))

        page_column.addWidget(self.lbl_page_title)
        page_column.addWidget(self.scroll_area)
        page_column.addWidget(self.txt_source)

        translation_column = QVBoxLayout()
        self.lbl_output_title = QLabel(S("output_title"))
        self.lbl_output_title.setStyleSheet("font-weight: bold;")
        self.txt_output = QTextEdit()
        self.txt_output.setReadOnly(True)
        self.txt_output.setFont(QFont("Georgia", 12))
        self.txt_output.setText(S("output_placeholder"))
        translation_column.addWidget(self.lbl_output_title)
        translation_column.addWidget(self.txt_output)

        workspace_layout.addLayout(page_column, stretch=1)
        workspace_layout.addLayout(translation_column, stretch=1)

        main_layout.addWidget(header_frame)
        main_layout.addWidget(nav_frame)
        main_layout.addWidget(lang_frame)
        main_layout.addWidget(review_frame)
        main_layout.addWidget(status_frame)
        # نوار پیشرفت: درصد سمت راست (شروع RTL)، نوار در امتداد آن به سمت چپ
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        progress_row.addWidget(self.lbl_percent)
        progress_row.addWidget(self.progress_bar, 1)
        main_layout.addLayout(progress_row)
        main_layout.addLayout(workspace_layout)

        self.apply_output_direction()

    # ----------------------------- تم -----------------------------
    def apply_theme(self):
        mode = effective_theme(self.cfg)
        app = QApplication.instance()
        if app is not None:
            sheet = LIGHT_STYLESHEET if mode == "light" else DARK_STYLESHEET
            # تیک واقعی برای چک‌باکس/رادیو + فلش‌های شفاف اسپینر
            check_url, radio_url, up_url, down_url = ensure_indicator_assets()
            extra = ""
            if check_url:
                extra += (
                    f'\nQCheckBox::indicator:checked {{ image: url("{check_url}"); '
                    "border: none; width: 18px; height: 18px; }"
                )
            if radio_url:
                extra += (
                    f'\nQRadioButton::indicator:checked {{ image: url("{radio_url}"); '
                    "border: none; width: 16px; height: 16px; }"
                )
            if up_url and down_url:
                extra += (
                    "\nQSpinBox::up-button, QSpinBox::down-button {"
                    " subcontrol-origin: border; width: 16px; height: 12px;"
                    " background-color: #787165; border: none; border-radius: 3px;"
                    " margin: 2px; }"
                    f'\nQSpinBox::up-button {{ image: url("{up_url}"); }}'
                    f'\nQSpinBox::down-button {{ image: url("{down_url}"); }}'
                )
            app.setStyleSheet(sheet + extra)

        if mode == "light":
            self.lbl_page.setStyleSheet("font-weight: bold; font-size: 11pt; color: #2b2723;")
            self.lbl_status.setStyleSheet("color: #1e40af; font-weight: bold;")
            self.lbl_percent.setStyleSheet("color: #1e40af; font-weight: bold; font-size: 11pt;")
            self.lbl_page_title.setStyleSheet("font-weight: bold; color: #57534a;")
            self.lbl_output_title.setStyleSheet("font-weight: bold; color: #57534a;")
            self.lbl_image_viewer.setStyleSheet("background-color: #fdfcf8; color: #57534a;")
            self.lbl_lang_hint.setStyleSheet("color: #57534a; font-size: 9pt;")
            self.btn_translate.setStyleSheet("")
            self.btn_batch.setStyleSheet(
                "QPushButton { background-color: #1e40af; color: #ffffff; font-weight: bold; border: 1px solid #1e40af; border-radius: 6px; padding: 8px 16px; }"
                "QPushButton:hover { background-color: #1e3a8a; border-color: #1e3a8a; }"
                "QPushButton:disabled { background-color: #e7dfc9; color: #7d7462; border-color: #c9bda0; }"
            )
        else:
            self.lbl_page.setStyleSheet("font-weight: bold; font-size: 11pt; color: #ede9df;")
            self.lbl_status.setStyleSheet("color: #5b8def; font-weight: bold;")
            self.lbl_percent.setStyleSheet("color: #5b8def; font-weight: bold; font-size: 11pt;")
            self.lbl_page_title.setStyleSheet("font-weight: bold; color: #b3aea0;")
            self.lbl_output_title.setStyleSheet("font-weight: bold; color: #b3aea0;")
            self.lbl_image_viewer.setStyleSheet("background-color: #201f1a; color: #a39e93;")
            self.lbl_lang_hint.setStyleSheet("color: #a39e93; font-size: 9pt;")
            self.btn_translate.setStyleSheet("")
            self.btn_batch.setStyleSheet(
                "QPushButton { background-color: #1e40af; color: #ffffff; font-weight: bold; border: 1px solid #1e40af; border-radius: 6px; padding: 8px 16px; }"
                "QPushButton:hover { background-color: #2a52b8; border-color: #2a52b8; }"
                "QPushButton:disabled { background-color: #1c1b16; color: #6f6c60; border-color: #2b2a22; }"
            )

    def refresh_ui_language(self, previous_language=None):
        """Refresh all main-window labels without discarding the open book."""
        self.lbl_file.setText(
            f"{os.path.basename(self.current_file)}"
            if self.current_file else S("no_file")
        )
        self.btn_settings.setText(S("settings"))
        self.btn_open.setText(S("open_book"))
        self.lbl_page.setText(
            S("page_label", cur=num(self.current_page + 1), total=num(self.total_pages))
        )
        self.lbl_src_lang.setText(S("src_lang"))
        self.lbl_tgt_lang.setText(S("tgt_lang"))
        self.lbl_lang_hint.setText(S("lang_hint"))
        for combo in (self.combo_src, self.combo_tgt):
            for i in range(combo.count()):
                lang = combo.itemData(i)
                label_key = {"en": "lang_en", "fa": "lang_fa", "ar": "lang_ar"}.get(lang)
                if label_key:
                    combo.setItemText(i, S(label_key))

        self.btn_next.setText(S("next_page"))
        self.btn_prev.setText(S("prev_page"))
        self.btn_translate.setText(S("translate_page"))
        self.btn_batch.setText(S("translate_book"))
        self.btn_copy.setText(S("copy"))
        self.btn_copy.setToolTip(S("copy_tip"))
        self.btn_save.setText(S("save"))
        self.act_save_page.setText(S("save_page_act"))
        self.act_save_md.setText(S("save_md_act"))
        self.act_save_html.setText(S("save_html_act"))
        self.btn_view_source.setText(S("view_image") if self.view_source else S("view_source"))
        self.chk_reviewed.setText(S("reviewed"))
        self.chk_reviewed.setToolTip(S("reviewed_tip"))
        self.lbl_output_title.setText(S("output_title"))
        self.txt_output.setPlaceholderText(S("output_placeholder"))
        self.txt_source.setPlaceholderText(S("source_placeholder"))
        old_strings = STRINGS.get(previous_language, {})
        current_output = self.txt_output.toPlainText()
        if current_output == old_strings.get("output_placeholder"):
            self.txt_output.setText(S("output_placeholder"))
        elif current_output == old_strings.get("click_translate"):
            self.txt_output.setText(S("click_translate"))
        self.lbl_page_title.setText(
            S("page_text_title") if self.view_source else S("page_image_title")
        )
        if not self.doc:
            self.lbl_image_viewer.setText(S("image_placeholder"))

        paused = self.batch_worker is not None and self.batch_worker.is_paused()
        self.btn_pause.setText(S("resume_btn") if paused else S("pause"))
        self.btn_cancel_batch.setText(S("cancel_btn"))
        if self.job and self.job.count():
            self.lbl_status.setText(S("resume_hint", n=num(self.job.count())))
        else:
            self.lbl_status.setText(S("ready"))
        self.update_stats()

        # درصد حتی وقتی نوار پیشرفت پنهان است هم با زبان تازه نوشته می‌شود
        # تا با ارقام زبان قبلی باقی نماند.
        if self.progress_bar.maximum() > self.progress_bar.minimum():
            pct = round(100 * self.progress_bar.value() / self.progress_bar.maximum())
            self.lbl_percent.setText(S("percent", n=num(pct)))
        elif self.progress_bar.isVisible():
            self.lbl_percent.setText("…")
        else:
            self.lbl_percent.setText(S("percent", n=num(0)))

        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(
                Qt.LayoutDirection.RightToLeft if _UI_LANG == "fa"
                else Qt.LayoutDirection.LeftToRight
            )

    def _on_system_scheme(self, *_args):
        if self.cfg.get("theme", "system") == "system":
            self.apply_theme()

    # ----------------------------- تنظیمات -----------------------------
    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self, job=self.job)
        dlg.saved.connect(self.on_settings_saved)
        dlg.exec()

    def on_settings_saved(self, new_cfg):
        self.cfg = new_cfg
        self.apply_theme()
        self.apply_output_direction()
        if new_cfg.get("ui_lang", "fa") != _UI_LANG:
            previous_language = _UI_LANG
            set_ui_lang(new_cfg.get("ui_lang", "fa"))
            self.refresh_ui_language(previous_language)
            self.lbl_status.setText(S("lang_changed_note"))
        # اگر ویرایشگر تمپلیت تغییر کرده باشد، ساختار همگام می‌شود
        if self.job is not None:
            self.structure = self.job.structure
        # اعمال فوری به ترجمهٔ کل کتابِ متوقفشده (موتور در صفحهٔ بعد بازساخته می‌شود)
        if self.batch_worker is not None:
            self.batch_worker.update_settings(self.cfg)
            self.lbl_status.setText(S("settings_applied"))

    # ----------------------------- جهت ترجمه (مبدأ/مقصد) -----------------------------
    def on_src_changed(self, _index):
        src = self.combo_src.currentData()
        if src == self._tgt_lang:
            # قفل دوگانه: مقصد با مبدأ یکی نمی‌شود — مقصد به مبدأ قبلی جابه‌جا می‌شود
            self._sync_combo(self.combo_tgt, self._src_lang)
            self._tgt_lang = self._src_lang
        self._src_lang = src
        self._apply_direction(f"{self._src_lang}2{self._tgt_lang}")

    def on_tgt_changed(self, _index):
        tgt = self.combo_tgt.currentData()
        if tgt == self._src_lang:
            # قفل دوگانه: مبدأ با مقصد یکی نمی‌شود — مبدأ به مقصد قبلی جابه‌جا می‌شود
            self._sync_combo(self.combo_src, self._tgt_lang)
            self._src_lang = self._tgt_lang
        self._tgt_lang = tgt
        self._apply_direction(f"{self._src_lang}2{self._tgt_lang}")

    @staticmethod
    def _sync_combo(combo, lang):
        """تنظیم کومبو بدون شلیک سیگنال (جلوگیری از حلقه و پرش چیدمان)."""
        if combo.currentData() == lang:
            return
        combo.blockSignals(True)
        for i in range(combo.count()):
            if combo.itemData(i) == lang:
                combo.setCurrentIndex(i)
                break
        combo.blockSignals(False)

    def _apply_direction(self, direction):
        parts = direction.split("2")
        if len(parts) == 2:
            self._src_lang, self._tgt_lang = parts
        if self.cfg.get("direction") != direction:
            self.cfg["direction"] = direction
            save_config(self.cfg)
        if self.job is not None:
            self.job.switch_direction(direction)
            self.update_stats()
            if self.doc:
                self.refresh_current_page()
        self.apply_output_direction()

    def apply_output_direction(self):
        d = DIRECTIONS.get(self.cfg.get("direction", "en2fa"), DIRECTIONS["en2fa"])
        # پنل ترجمه: جهت متن از زبانِ مقصد پیروی می‌کند (انگلیسی → چپ‌چین)
        self.txt_output.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if d["rtl"] else Qt.LayoutDirection.LeftToRight
        )
        # پنل متن مبدأ: جهت از زبانِ مبدأ پیروی می‌کند (فارسی/عربی → راست‌چین)
        self.txt_source.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if d.get("source_rtl")
            else Qt.LayoutDirection.LeftToRight
        )
        # عنوان پنل‌ها ثابت می‌ماند تا با تعویض جهت، چیدمان نپرد

    # ----------------------------- فایل و صفحات -----------------------------
    def set_file_label(self, file_path):
        """فقط نام فایل در هدر — بدون تعداد صفحات (به درخواست کاربر)."""
        self.lbl_file.setText(f"{os.path.basename(file_path)}")

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, S("open_title"), "", "Books (*.pdf *.epub)"
        )
        if not file_path:
            return
        old_doc, old_view = self.doc, self.view_doc
        try:
            self.doc = pymupdf.open(file_path)
            self.view_doc = pymupdf.open(file_path)
        except Exception as exc:  # noqa: BLE001
            # بازگرداندن وضعیت قبلی تا سند و job از هم جدا نیفتند
            if self.doc is not old_doc:
                try:
                    self.doc.close()
                except Exception:  # noqa: BLE001
                    pass
            self.doc, self.view_doc = old_doc, old_view
            self.txt_output.setText(S("file_error", detail=exc))
            return
        # بستن اسناد قبلی (نشت هندل/حافظه در باز کردن‌های پشت‌سرهم)
        for old in (old_doc, old_view):
            if old is not None:
                try:
                    old.close()
                except Exception:  # noqa: BLE001
                    pass

        self.current_file = file_path
        self.total_pages = len(self.doc)
        self.current_page = 0
        self.job = JobStore(file_path).load()
        self.job.switch_direction(self.cfg.get("direction", "en2fa"))
        self.structure = self.job.structure
        self.view_source = False

        self.set_file_label(file_path)
        self.update_ui_controls()
        self.update_stats()
        self.refresh_current_page()

        legacy_done = len(self.job.data.get("legacy_translations", {}))
        done = self.job.count()
        if legacy_done:
            self.lbl_status.setText(
                S("legacy_job_archived", n=num(legacy_done))
            )
        elif done:
            self.lbl_status.setText(S("resume_hint", n=num(done)))
        else:
            self.lbl_status.setText(S("ready"))

        # (الف) تحلیل محلی ساختار + (ب) پاس عمیق AI — در صورت فعال بودن در تنظیمات
        self.auto_analyze_structure()

    # ----------------------------- ساختار کتاب (الف/ب) -----------------------------
    def auto_analyze_structure(self):
        """تحلیل محلی هنگام باز شدن فایل و پاس اختیاری AI (هر دو از تنظیمات قابل قطع)."""
        if not self.doc or not self.job:
            return
        if self.cfg.get("structure_auto", True) and not self.job.structure:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
            try:
                structure = analyze_structure(self.doc)
                if structure:
                    self.job.structure = structure
                    self.job.save()
                    self.structure = structure
            finally:
                QApplication.restoreOverrideCursor()
        if self.cfg.get("structure_ai", False):
            self.start_ai_structure_pass()

    def start_ai_structure_pass(self):
        """پاس عمیق AI (۱ درخواست) — غیرهمزمان؛ نتیجه در job ذخیره می‌شود."""
        if (not self.doc or not self.job
                or self.structure_worker is not None
                or validate_config(self.cfg)):
            return
        parts = []
        for i in range(min(5, self.total_pages)):
            try:
                parts.append(self.doc.load_page(i).get_text("text"))
            except Exception:  # noqa: BLE001
                continue
        sample = "\n".join(parts)
        if not sample.strip():
            return
        self.lbl_status.setText(S("structure_ai_running"))
        self.structure_worker = AiStructureWorker(
            self.cfg, sample, self.job.structure, job=self.job
        )
        self.structure_worker.done.connect(self.on_structure_ai_done)
        self.structure_worker.failed.connect(self.on_structure_ai_failed)
        self.structure_worker.finished.connect(self._cleanup_structure_worker)
        self.structure_worker.start()

    def on_structure_ai_done(self, job, merged):
        # نتیجه در job همان کتابی ذخیره می‌شود که نمونه از آن بود — حتی اگر
        # کاربر وسط پاس، کتاب دیگری باز کرده باشد (ضد نشت تمپلیت بین کتاب‌ها)
        target = job if job is not None else self.job
        if target is None:
            return
        target.structure = merged
        target.save()
        if target is self.job:
            self.structure = merged
            self.lbl_status.setText(S("structure_ai_done"))

    def on_structure_ai_failed(self, _message):
        self.lbl_status.setText(S("structure_ai_failed"))

    def _cleanup_structure_worker(self):
        w = self.sender()
        if isinstance(w, QThread):
            w.deleteLater()
            if w is self.structure_worker:
                self.structure_worker = None

    def update_ui_controls(self):
        if self.doc:
            self.lbl_page.setText(S("page_label", cur=num(self.current_page + 1), total=num(self.total_pages)))
            self.btn_prev.setEnabled(self.current_page > 0)
            self.btn_next.setEnabled(self.current_page < self.total_pages - 1)
            self.btn_translate.setEnabled(True)
            self.btn_batch.setEnabled(True)
            self.btn_view_source.setEnabled(True)
            self.btn_save.setEnabled(True)

    def update_stats(self):
        if not self.job:
            self.lbl_stats.setText("")
            return
        self.lbl_stats.setText(
            S("stats", done=num(self.job.count()), total=num(self.total_pages),
              rev=num(self.job.reviewed_count()))
        )

    def refresh_current_page(self, keep_output=False):
        """نمایش تصویر/مبدأ در پنل راست و ترجمهٔ ذخیره‌شده در پنل چپ.

        keep_output=True: متن پنل چپ دست‌نخورده می‌ماند (بعد از ترجمهٔ کل کتاب)."""
        if not self.doc:
            return
        view = self.view_doc or self.doc  # حین ترجمهٔ کل کتاب از دستگاه جدا خوانده می‌شود
        self.lbl_page.setText(S("page_label", cur=num(self.current_page + 1), total=num(self.total_pages)))

        # پنل صفحهٔ مبدأ (راست)
        if self.view_source:
            try:
                text = extract_page_text(view.load_page(self.current_page))
                self.txt_source.setPlainText(text.strip() or S("no_text_page"))
            except Exception as exc:  # noqa: BLE001
                self.txt_source.setPlainText(S("extract_error", detail=exc))
        else:
            self.render_page_image()

        # پنل ترجمه (چپ)
        cached = self.job.get(self.current_page) if self.job else None
        if cached:
            if not keep_output:
                self.txt_output.setText(cached)
            self.btn_copy.setEnabled(True)
            self.chk_reviewed.setEnabled(True)
            self.chk_reviewed.blockSignals(True)
            self.chk_reviewed.setChecked(self.job.is_reviewed(self.current_page))
            self.chk_reviewed.blockSignals(False)
        else:
            if not keep_output:
                self.txt_output.setText(S("click_translate"))
            self.btn_copy.setEnabled(False)
            self.chk_reviewed.blockSignals(True)
            self.chk_reviewed.setChecked(False)
            self.chk_reviewed.blockSignals(False)
            self.chk_reviewed.setEnabled(False)

    def render_page_image(self):
        if not self.doc:
            return
        view = self.view_doc or self.doc
        try:
            pix = view.load_page(self.current_page).get_pixmap(
                matrix=pymupdf.Matrix(1.5, 1.5)
            )
            pixmap = QPixmap()
            pixmap.loadFromData(pix.tobytes("png"))
            self.lbl_image_viewer.setPixmap(pixmap)
        except Exception as exc:  # noqa: BLE001
            self.lbl_image_viewer.setText(S("render_error", detail=exc))

    def _sync_nav_buttons(self):
        """همگام‌سازی فقط دکمه‌های ناوبری (بدون بیدارکردن دکمه‌های قفل‌شدهٔ حالت اشغال)."""
        has = bool(self.doc)
        self.btn_prev.setEnabled(has and self.current_page > 0)
        self.btn_next.setEnabled(has and self.current_page < self.total_pages - 1)

    def next_page(self):
        if self.doc and self.current_page < self.total_pages - 1:
            self._following_batch = False  # کاربر خودش جابجا شد — دنبال‌کردن متوقف
            self.current_page += 1
            if self.batch_worker is None:
                self.update_ui_controls()
            else:
                self._sync_nav_buttons()
            self.refresh_current_page(keep_output=self.batch_worker is not None)

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self._following_batch = False
            self.current_page -= 1
            if self.batch_worker is None:
                self.update_ui_controls()
            else:
                self._sync_nav_buttons()
            self.refresh_current_page(keep_output=self.batch_worker is not None)

    def toggle_view(self):
        self.view_source = not self.view_source
        self.scroll_area.setVisible(not self.view_source)
        self.txt_source.setVisible(self.view_source)
        self.lbl_page_title.setText(
            S("page_text_title") if self.view_source
            else S("page_image_title")
        )
        self.btn_view_source.setText(
            S("view_image") if self.view_source
            else S("view_source")
        )
        self.refresh_current_page()

    def on_reviewed_toggled(self, checked):
        if not self.job or not self.job.get(self.current_page):
            self.chk_reviewed.setChecked(False)
            return
        self.job.set_reviewed(self.current_page, checked)
        self.job.save()
        self.update_stats()

    # ----------------------------- حالت اشغال -----------------------------
    def set_busy(self, busy, lock_navigation=True):
        widgets = [
            self.btn_translate, self.btn_batch, self.btn_open, self.btn_settings,
            self.btn_save,
            self.combo_src, self.combo_tgt, self.chk_reviewed, self.btn_view_source,
        ]
        if lock_navigation:
            # در ترجمهٔ تک‌صفحه ناوبری قفل است (نتیجه به صفحهٔ جاری نوشته می‌شود)؛
            # در ترجمهٔ کل کتاب آزاد می‌ماند (call با lock_navigation=False).
            widgets += [self.btn_prev, self.btn_next]
        for widget in widgets:
            widget.setEnabled(not busy)
        if busy:
            self.btn_copy.setEnabled(False)

    def _status_bar_busy(self):
        """آیا فعالیتی در جریان است که نوار وضعیت باید برایش بماند؟

        ترجمهٔ تک‌صفحه یا کل کتاب؛ حالت توقفِ موقت هم «در جریان» حساب
        می‌شود، چون دکمه‌های ادامه/لغو داخل همین نوارند."""
        if self.single_worker is not None and self.single_worker.isRunning():
            return True
        w = self.batch_worker
        return w is not None and w.isRunning()

    def _arm_status_hide(self, delay=6000):
        """اگر کاری در جریان نیست، مخفی‌شدن نوار را زمان‌بندی کن؛
        وگرنه تایمر را نگه دار تا نوار وسط کار ناپدید نشود."""
        if self._status_bar_busy():
            self._status_hide_timer.stop()
        else:
            self._status_hide_timer.start(delay)

    def _hide_status_if_idle(self):
        if not self._status_bar_busy():
            self._status_frame.setVisible(False)

    def _show_status(self, text, controls=None):
        self.lbl_status.setText(text)
        self._status_frame.setVisible(True)
        self._arm_status_hide(4000)
        if controls is not None:
            self.btn_pause.setVisible(controls)
            self.btn_cancel_batch.setVisible(controls)

    def _set_batch_controls(self, active):
        """دکمه‌های توقف/لغو فقط هنگام اجرای ترجمهٔ کل کتاب فعال می‌شوند.

        (این دکمه‌ها در سازنده غیرفعال می‌شوند؛ بدون این تابع عملاً
        هیچ‌وقت قابل کلیک نبودند — «کلا خاموش» بودند.)
        """
        self.btn_pause.setVisible(active)
        self.btn_cancel_batch.setVisible(active)
        self.btn_pause.setEnabled(active)
        self.btn_cancel_batch.setEnabled(active)

    # ----------------------------- ترجمهٔ تک‌صفحه -----------------------------
    def translate_current_page(self):
        if not self.doc or self.single_worker or self.batch_worker:
            return
        err = validate_config(self.cfg)
        if err:
            QMessageBox.warning(self, S("settings_title"), err)
            self.open_settings()
            return

        self.set_busy(True)
        self._show_status(S("preparing"))
        self.btn_pause.setVisible(False)
        self.btn_cancel_batch.setVisible(False)
        self._set_progress_visible(True)
        self.progress_bar.setRange(0, 0)
        self.lbl_percent.setText("…")
        self._awaiting_first_chunk = True
        self.txt_output.clear()

        structure_block = structure_prompt_block(self.structure)
        self.single_worker = SinglePageWorker(
            self.doc, self.current_page, self.cfg,
            self.cfg.get("direction", "en2fa"), structure_block or None,
        )
        self.single_worker.status.connect(self._show_status)
        self.single_worker.progress.connect(self.on_progress)
        self.single_worker.partial.connect(self.on_single_partial)
        self.single_worker.result_ready.connect(self.on_single_result)
        self.single_worker.failed.connect(self.on_single_failed)
        self.single_worker.finished.connect(self._cleanup_single)
        self.single_worker.start()

    def _cleanup_single(self):
        w = self.sender()
        if isinstance(w, QThread):
            w.deleteLater()
            if w is self.single_worker:
                self.single_worker = None
                self._arm_status_hide()

    def on_progress(self, done, total):
        if total > 1:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
            pct = int(round(done * 100.0 / total))
            self.lbl_percent.setText(S("percent", n=num(pct)))
        else:
            self.progress_bar.setRange(0, 0)
            self.lbl_percent.setText("…")

    def _set_progress_visible(self, visible):
        """نمایش/پنهان‌سازی هم‌زمان نوار و لیبل درصد."""
        self.progress_bar.setVisible(visible)
        self.lbl_percent.setVisible(visible)
        if not visible:
            self.lbl_percent.setText(S("percent", n=num(0)))

    def on_single_partial(self, text):
        if self._awaiting_first_chunk:
            self.txt_output.clear()
            self._awaiting_first_chunk = False
        self.txt_output.append(text)

    def on_single_result(self, text, tail):
        if self.job:
            self.job.set(self.current_page, text)
            self.job.context_tail = tail
            self.job.save()
        self._end_status(S("page_done"))
        self.set_busy(False)
        self.update_ui_controls()
        self.update_stats()
        self.refresh_current_page()

    def on_single_failed(self, message):
        self._end_status(S("page_failed"))
        self.set_busy(False)
        self.update_ui_controls()
        self.txt_output.setText(message)

    def _end_status(self, text):
        self._set_progress_visible(False)
        self._status_frame.setVisible(True)
        self._set_batch_controls(False)
        self.lbl_status.setText(text)
        self._arm_status_hide()

    # ----------------------------- ترجمهٔ کل کتاب -----------------------------
    def start_batch(self):
        if not self.doc or self.single_worker or self.batch_worker:
            return
        err = validate_config(self.cfg)
        if err:
            QMessageBox.warning(self, S("settings_title"), err)
            self.open_settings()
            return

        dlg = BatchDialog(
            self.total_pages, self.job, self,
            structure_default=bool(self.cfg.get("structure_auto", True)),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.wants_restart():
            self.job.reset_translations()
            self.update_stats()
            self.lbl_status.setText(S("restart_cleared"))

        start, end = dlg.range_0based()
        use_structure = dlg.chk_structure.isChecked()
        qc = dlg.chk_qc.isChecked()
        delay = dlg.spin_delay.value()

        structure_block = None
        if use_structure:
            if not self.job.structure:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                QApplication.processEvents()
                try:
                    self.job.structure = analyze_structure(self.doc)
                    self.job.save()
                finally:
                    QApplication.restoreOverrideCursor()
                self.structure = self.job.structure
            structure_block = structure_prompt_block(self.job.structure)
            if self.cfg.get("structure_ai", False):
                # پاس عمیق AI به‌صورت غیرهمزمان؛ برای این اجرا و اجراهای بعد ذخیره می‌شود
                self.start_ai_structure_pass()

        self.batch_params = {
            "start": start, "end": end,
            "structure_block": structure_block, "qc": qc, "delay": delay,
        }

        self.txt_output.clear()
        header = S("batch_header", a=num(start + 1), b=num(end + 1))
        if qc:
            header += S("qc_on")
        self.txt_output.append(header)
        self.txt_output.append("")

        self.launch_batch_worker()
        self.lbl_status.setText(S("batch_starting"))

    def launch_batch_worker(self):
        p = self.batch_params
        self.batch_worker = BatchWorker(
            self.doc, self.cfg, self.job, p["start"], p["end"],
            self.cfg.get("direction", "en2fa"),
            p["structure_block"], p["qc"], p["delay"],
        )
        self.batch_worker.page_status.connect(self._show_status)
        self.batch_worker.page_progress.connect(self.on_progress)
        self.batch_worker.page_started.connect(self.on_batch_page_started)
        self.batch_worker.page_done.connect(self.on_batch_page_done)
        self.batch_worker.paused.connect(self.on_batch_paused)
        self.batch_worker.resumed.connect(self.on_batch_resumed)
        self.batch_worker.quota_paused.connect(self.on_batch_quota)
        self.batch_worker.finished_batch.connect(self.on_batch_finished)
        self.batch_worker.failed.connect(self.on_batch_failed)
        self.batch_worker.finished.connect(self._cleanup_batch)

        self.set_busy(True, lock_navigation=False)  # ناوبری حین ترجمهٔ کل کتاب آزاد می‌ماند
        self._set_progress_visible(True)
        self.progress_bar.setRange(0, 0)
        self.lbl_percent.setText("…")
        self._status_frame.setVisible(True)
        self._status_hide_timer.stop()
        self._set_batch_controls(True)
        self.btn_pause.setText(S("pause"))
        self._following_batch = True  # نمایش زندهٔ صفحهٔ در حال ترجمه
        self.batch_worker.start()

    def _cleanup_batch(self):
        w = self.sender()
        if isinstance(w, QThread):
            w.deleteLater()
            if w is self.batch_worker:
                self.batch_worker = None
                self._arm_status_hide()

    def on_batch_page_started(self, page):
        """دنبال‌کردن زنده: صفحهٔ در حال ترجمه نمایش داده می‌شود.

        اگر کاربر خودش جابجا شده باشد (_following_batch=False) دیگر مزاحم نمی‌شویم.
        """
        if not self._following_batch or page == self.current_page:
            return
        self.current_page = page
        self._sync_nav_buttons()
        self.refresh_current_page(keep_output=True)

    def on_batch_page_done(self, page, text):
        self.txt_output.append(S("page_sep", p=num(page + 1)))
        self.txt_output.append(text)
        self.txt_output.append("")
        self.lbl_page.setText(S("page_label", cur=num(page + 1), total=num(self.total_pages)))
        self.update_stats()
        cursor = self.txt_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.txt_output.setTextCursor(cursor)

    def on_batch_paused(self):
        self.btn_pause.setText(S("resume_btn"))
        self.btn_settings.setEnabled(True)  # حین توقف می‌توان تنظیمات را ویرایش کرد
        self.lbl_status.setText(S("paused_status"))

    def on_batch_resumed(self):
        self.btn_pause.setText(S("pause"))
        self.btn_settings.setEnabled(False)
        self.lbl_status.setText(S("resumed_status"))

    def on_batch_quota(self, message):
        self.lbl_status.setText(S("quota_status"))
        self.btn_pause.setText(S("resume_btn"))
        self.btn_settings.setEnabled(True)  # تا تنظیمات را اصلاح کنید
        QMessageBox.warning(self, S("quota_title"), message)

    def on_batch_finished(self, message):
        self._idle_after_batch()
        self.lbl_status.setText(message)
        QMessageBox.information(self, S("batch_done_title"), message)

    def on_batch_failed(self, message):
        self._idle_after_batch()
        self.lbl_status.setText(S("batch_failed_status"))
        QMessageBox.critical(self, S("error_title"), message)

    def _idle_after_batch(self):
        self.batch_params = None
        self._following_batch = False
        self._set_progress_visible(False)
        self._set_batch_controls(False)
        self.set_busy(False)
        self.update_ui_controls()
        self.update_stats()
        # خروجی جریانیِ کل کتاب حفظ می‌شود تا کاربر بتواند آن را مرور/ذخیره کند
        self.refresh_current_page(keep_output=True)

    def on_pause_clicked(self):
        w = self.batch_worker
        if w is not None and w.isRunning():
            if w.is_paused():
                w.resume()
            else:
                w.pause()
            return
        # ترد قبلاً تمام شده (مثلاً سهمیه) — اجرای جدید با همان پارامترها
        if self.batch_params:
            self.lbl_status.setText(S("resume_from_missing"))
            self.launch_batch_worker()

    def on_cancel_batch(self):
        w = self.batch_worker
        if w is not None and w.isRunning():
            self.lbl_status.setText(S("cancelling"))
            w.cancel()
        else:
            self._idle_after_batch()
            self.lbl_status.setText(S("cancelled_status"))

    # ----------------------------- ذخیره و خروجی -----------------------------
    def _translation_active(self):
        """آیا ترجمه‌ای در حال اجراست؟ (خروجی گرفتن هم‌زمان با تردها امن نیست:
        job در حال تغییر است و سند pymupdf هم thread-safe نیست.)"""
        if self.single_worker is not None and self.single_worker.isRunning():
            return True
        w = self.batch_worker
        return w is not None and w.isRunning() and not w.is_paused()

    def _source_name(self):
        return os.path.basename(self.current_file or "book")

    def save_current_page(self):
        if not self.job or not self.job.get(self.current_page):
            QMessageBox.information(self, S("save_title"), S("save_first_page"))
            return
        if self._translation_active():
            QMessageBox.information(self, S("save_title"), S("export_busy"))
            return
        stem = os.path.splitext(self._source_name())[0]
        path, _ = QFileDialog.getSaveFileName(
            self, S("save_page_title"),
            f"{stem}_page{self.current_page + 1}.txt", "Text (*.txt)",
        )
        if not path:
            return
        try:
            export_page_text(
                self.job.get(self.current_page), self._source_name(),
                self.current_page, path,
                direction=self.cfg.get("direction", "en2fa"),
            )
        except Exception as exc:  # noqa: BLE001 — خطای نوشتن نباید برنامه را بیندازد
            QMessageBox.critical(
                self, S("save_title"), S("save_error", detail=exc)
            )
            return
        QMessageBox.information(self, S("save_title"), S("saved_msg", path=path))

    def save_book_markdown(self):
        if not self.job or self.job.count() == 0:
            QMessageBox.information(self, S("save_title"), S("save_none"))
            return
        if self._translation_active():
            QMessageBox.information(self, S("save_title"), S("export_busy"))
            return
        stem = os.path.splitext(self._source_name())[0]
        path, _ = QFileDialog.getSaveFileName(
            self, S("save_book_title"), f"{stem}_translated.md",
            "Markdown (*.md)",
        )
        if not path:
            return
        try:
            export_markdown(
                self.job, self._source_name(), path,
                direction=self.cfg.get("direction", "en2fa"),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, S("save_title"), S("save_error", detail=exc)
            )
            return
        QMessageBox.information(self, S("save_title"), S("saved_msg", path=path))

    def save_book_html(self):
        if not self.job or self.job.count() == 0:
            QMessageBox.information(self, S("save_title"), S("save_none"))
            return
        if self._translation_active():
            QMessageBox.information(self, S("html_title"), S("export_busy"))
            return
        out_dir = QFileDialog.getExistingDirectory(self, S("html_dir_title"))
        if not out_dir:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            index_path = export_html(
                self.job, self.doc, self._source_name(), out_dir,
                direction=self.cfg.get("direction", "en2fa"),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, S("html_title"), S("save_error", detail=exc)
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, S("html_title"), S("html_done", path=index_path)
        )

    def copy_translation(self):
        text = self.txt_output.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        # بازخورد باید جلوی چشم کاربر باشد: هم نوار وضعیت (که ممکن است پنهان
        # باشد) نمایش داده می‌شود، هم خود دکمه موقتاً «کپی شد» نشان می‌دهد
        # تا کاربر برای اطمینان چند بار کلیک نکند.
        self._show_status(S("copied"))
        self.btn_copy.setText(S("copied"))
        QTimer.singleShot(1600, self._restore_copy_label)

    def _restore_copy_label(self):
        self.btn_copy.setText(S("copy"))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernTranslatorApp()
    window.show()
    sys.exit(app.exec())
