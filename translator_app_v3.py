# -*- coding: utf-8 -*-
"""
kaman ai translator v3 — ترجمهٔ کتاب‌های PDF/EPUB با هوش مصنوعی.

نسخهٔ ۳ شامل:
  - ترجمهٔ دوطرفه (انگلیسی ⟶ فارسی / فارسی ⟶ انگلیسی)
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
import threading
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QFileDialog, QProgressBar, QFrame, QMessageBox,
    QScrollArea, QDialog, QComboBox, QLineEdit, QCheckBox, QSpinBox,
    QRadioButton, QMenu,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent, QObject
from PyQt6.QtGui import QFont, QPixmap, QIcon, QTextCursor
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

DARK_STYLESHEET = """
    QMainWindow { background-color: #0f172a; }
    QFrame { background-color: #1e293b; border-radius: 12px; padding: 8px; }
    QLabel { color: #f1f5f9; font-family: 'Tahoma'; font-size: 11pt; }
    QPushButton { background-color: #3b82f6; color: white; border-radius: 8px; padding: 10px 18px; font-family: 'Tahoma'; font-size: 10pt; font-weight: bold; }
    QPushButton:hover { background-color: #2563eb; }
    QPushButton:disabled { background-color: #475569; color: #94a3b8; }
    QPushButton#btnCopy { background-color: #2563eb; color: white; font-weight: bold; }
    QPushButton#btnCopy:hover { background-color: #1d4ed8; }
    QPushButton#btnCopy:disabled { background-color: #475569; color: #94a3b8; }
    QTextEdit { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 12px; padding: 15px; font-size: 11pt; }
    QProgressBar { border: none; background-color: #334155; height: 6px; border-radius: 3px; }
    QProgressBar::chunk { background-color: #10b981; border-radius: 3px; }
    QScrollArea { border: 1px solid #334155; border-radius: 12px; background-color: #1e293b; }
    QComboBox { background-color: #334155; color: #f1f5f9; border: 1px solid #475569; border-radius: 8px; padding: 8px 14px; font-family: 'Tahoma'; font-size: 10pt; }
    QComboBox:hover { background-color: #3f4f66; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox QAbstractItemView { background-color: #1e293b; color: #f1f5f9; border: 1px solid #334155; selection-background-color: #2563eb; selection-color: white; }
    QLineEdit { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 8px; padding: 8px 12px; font-size: 10pt; selection-background-color: #2563eb; selection-color: white; }
    QSpinBox { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 5px 8px 5px 26px; font-size: 10pt; }
    QSpinBox:disabled { background-color: #334155; color: #cbd5e1; border-color: #475569; }
    QDialog { background-color: #0f172a; }
    QCheckBox, QRadioButton { color: #f1f5f9; font-family: 'Tahoma'; font-size: 10pt; background: transparent; spacing: 8px; }
    QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #64748b; background-color: #1e293b; }
    QCheckBox::indicator:checked { background-color: #3b82f6; border-color: #3b82f6; }
    QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px; border: 1px solid #64748b; background-color: #1e293b; }
    QRadioButton::indicator:checked { background-color: #3b82f6; border-color: #3b82f6; }
    QMenu { background-color: #1e293b; color: #f1f5f9; border: 1px solid #334155; }
    QMenu::item:selected { background-color: #2563eb; }
    QMessageBox { background-color: #1e293b; }
"""

LIGHT_STYLESHEET = """
    QMainWindow { background-color: #f1f5f9; }
    QFrame { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px; }
    QLabel { color: #0f172a; font-family: 'Tahoma'; font-size: 11pt; }
    QPushButton { background-color: #2563eb; color: white; border-radius: 8px; padding: 10px 18px; font-family: 'Tahoma'; font-size: 10pt; font-weight: bold; }
    QPushButton:hover { background-color: #1d4ed8; }
    QPushButton:disabled { background-color: #cbd5e1; color: #94a3b8; }
    QPushButton#btnCopy { background-color: #2563eb; color: white; font-weight: bold; }
    QPushButton#btnCopy:hover { background-color: #1d4ed8; }
    QPushButton#btnCopy:disabled { background-color: #cbd5e1; color: #94a3b8; }
    QTextEdit { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 12px; padding: 15px; font-size: 11pt; }
    QProgressBar { border: none; background-color: #e2e8f0; height: 6px; border-radius: 3px; }
    QProgressBar::chunk { background-color: #10b981; border-radius: 3px; }
    QScrollArea { border: 1px solid #cbd5e1; border-radius: 12px; background-color: #ffffff; }
    QComboBox { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 14px; font-family: 'Tahoma'; font-size: 10pt; }
    QComboBox:hover { background-color: #f8fafc; border-color: #94a3b8; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox QAbstractItemView { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; selection-background-color: #2563eb; selection-color: white; }
    QLineEdit { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 12px; font-size: 10pt; selection-background-color: #2563eb; selection-color: white; }
    QSpinBox { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 8px 5px 26px; font-size: 10pt; }
    QSpinBox:disabled { background-color: #e2e8f0; color: #475569; border-color: #cbd5e1; }
    QDialog { background-color: #f8fafc; }
    QCheckBox, QRadioButton { color: #0f172a; font-family: 'Tahoma'; font-size: 10pt; background: transparent; spacing: 8px; }
    QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #94a3b8; background-color: #ffffff; }
    QCheckBox::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
    QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px; border: 1px solid #94a3b8; background-color: #ffffff; }
    QRadioButton::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
    QMenu { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; }
    QMenu::item:selected { background-color: #2563eb; color: white; }
    QMessageBox { background-color: #ffffff; }
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
    return True


def effective_theme(cfg):
    theme = cfg.get("theme", "system")
    if theme == "system":
        return "dark" if system_scheme_is_dark() else "light"
    return "light" if theme == "light" else "dark"


def section_label(text):
    """عنوان بخش با خط جداکننده — برای گروه‌بندی منظم دیالوگ‌ها."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "font-weight: bold; font-size: 11pt; color: #3b82f6;"
        "border-bottom: 1px solid #64748b; padding-bottom: 5px;"
    )
    return lbl


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_number(value):
    """عدد را با ارقام فارسی نمایش می‌دهد."""
    return str(value).translate(_FA_DIGITS)


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

    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, cfg, sample, local_structure=None):
        super().__init__()
        self.cfg = dict(cfg)
        self.sample = sample
        self.local = local_structure

    def run(self):
        try:
            engine = make_engine(self.cfg)
            merged = ai_structure_pass(engine, self.sample, self.local)
            if merged:
                self.done.emit(merged)
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
                    f"تکهٔ {i} از {n}…" if n > 1 else "در حال ترجمهٔ صفحه…"
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
            self.failed.emit(f"خطای غیرمنتظره رخ داد:\n{exc}")


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
        self.job = job
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
                self.finished_batch.emit("همهٔ صفحات این محدوده قبلاً ترجمه شده‌اند.")
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
                    self.page_status.emit(f"صفحهٔ {page + 1} — تکهٔ {i} از {n}")

                def on_partial(_text, page=page):
                    self.page_status.emit(f"صفحهٔ {page + 1} — در حال ترجمه…")

                text, context, source = translate_page(
                    engine, page_obj, self.cfg, self.direction,
                    context_tail=context, structure_block=self.structure_block,
                    on_progress=on_prog, on_partial=on_partial,
                    should_continue=self._continue,
                )

                if self.qc and source:
                    if not self._continue():
                        raise CancelledError()
                    self.page_status.emit(
                        f"صفحهٔ {page + 1} — بازبینی و اصلاح کیفیت (QC)…"
                    )
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
            msg = f"ترجمهٔ {done_this_run} صفحه با موفقیت تمام شد."
            if remaining:
                msg += f"\n{remaining} صفحه باقی مانده است."
            self.finished_batch.emit(msg)

        except CancelledError:
            self.finished_batch.emit(
                f"ترجمه لغو شد — {done_this_run} صفحه در این اجرا ترجمه شد."
            )
        except QuotaExhaustedError as exc:
            self.quota_paused.emit(
                f"{exc}\nترجمه‌های انجام‌شده ذخیره شد؛ با دکمهٔ «ادامه» از همان‌جا ادامه دهید."
            )
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"خطای غیرمنتظره رخ داد:\n{exc}")


# ============================== دیالوگ تنظیمات ==============================

class SettingsDialog(QDialog):
    saved = pyqtSignal(dict)

    def __init__(self, cfg, parent=None, job=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ تنظیمات")
        self.setMinimumWidth(560)
        self.cfg = dict(cfg)
        self.job = job   # فایلِ باز جاری (برای ویرایشگر تمپلیت)
        self._test_worker = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- موتور ترجمه ---
        row = QHBoxLayout()
        row.addWidget(QLabel("موتور ترجمه:"))
        self.combo_provider = QComboBox()
        self.combo_provider.addItem("Google Gemini", "gemini")
        self.combo_provider.addItem("سرور سازگار با OpenAI (لوکال/ابری)", "openai")
        provider = self.cfg.get("provider", "gemini")
        self.combo_provider.setCurrentIndex(0 if provider == "gemini" else 1)
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        row.addWidget(self.combo_provider, 1)
        layout.addLayout(row)

        # --- Base URL (فقط سازگار با OpenAI) ---
        self.row_base = QHBoxLayout()
        self.lbl_base = QLabel("آدرس سرور (Base URL):")
        self.txt_base = QLineEdit(self.cfg.get("base_url", ""))
        self.txt_base.setPlaceholderText("http://localhost:11434/v1")
        self.row_base.addWidget(self.lbl_base)
        self.row_base.addWidget(self.txt_base, 1)
        layout.addLayout(self.row_base)

        # --- API Key ---
        self.row_api = QHBoxLayout()
        self.row_api.addWidget(QLabel("API Key:"))
        self.txt_api = QLineEdit(self.cfg.get("api_key", ""))
        self.txt_api.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_api.setPlaceholderText("کلید Google AI Studio")
        self.chk_show = QCheckBox("نمایش")
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
        self.row_model.addWidget(QLabel("مدل:"))
        self.txt_model = QLineEdit(self.cfg.get("model", ""))
        self.row_model.addWidget(self.txt_model, 1)
        layout.addLayout(self.row_model)

        self.lbl_encrypt = QLabel(
            "🔒 کلید API به‌صورت رمزنگاری‌شده (DPAPI ویندوز) ذخیره می‌شود. "
            "تنظیمات و ترجمه‌های شما فقط در این پوشهٔ رایانهٔ شماست:"
        )
        self.lbl_encrypt.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        layout.addWidget(self.lbl_encrypt)

        data_row = QHBoxLayout()
        self.lbl_data_dir = QLabel(core.config_dir())
        self.lbl_data_dir.setStyleSheet(
            "color: #38bdf8; font-size: 9pt; font-family: Consolas, monospace;"
        )
        self.lbl_data_dir.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        data_row.addWidget(self.lbl_data_dir, 1)
        self.btn_open_data = QPushButton("📂 باز کردن پوشه")
        self.btn_open_data.setToolTip(
            "پوشهٔ ذخیرهٔ تنظیمات، کلید رمزنگاری‌شده و ترجمه‌های شما را در ویندوز باز می‌کند."
        )
        self.btn_open_data.clicked.connect(self.open_data_folder)
        data_row.addWidget(self.btn_open_data)
        layout.addLayout(data_row)

        # --- تم ---
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("تم برنامه:"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItem("سیستم (خودکار)", "system")
        self.combo_theme.addItem("دارک", "dark")
        self.combo_theme.addItem("لایت", "light")
        wanted = self.cfg.get("theme", "system")
        for i in range(self.combo_theme.count()):
            if self.combo_theme.itemData(i) == wanted:
                self.combo_theme.setCurrentIndex(i)
                break
        theme_row.addWidget(self.combo_theme, 1)
        layout.addLayout(theme_row)

        # --- ساختار کتاب / تمپلیت (سه سوییچ جداگانه) ---
        layout.addWidget(section_label("🧩 ساختار کتاب و تمپلیت"))

        self.chk_struct_auto = QCheckBox(
            "تحلیل خودکار ساختار هنگام باز شدن فایل (محلی و رایگان)"
        )
        self.chk_struct_auto.setChecked(bool(self.cfg.get("structure_auto", True)))
        layout.addWidget(self.chk_struct_auto)

        self.chk_struct_ai = QCheckBox(
            "تشخیص عمیق ساختار با هوش مصنوعی (۱ درخواست API برای هر فایل)"
        )
        self.chk_struct_ai.setChecked(bool(self.cfg.get("structure_ai", False)))
        layout.addWidget(self.chk_struct_ai)

        self.chk_struct_editor = QCheckBox(
            "نمایش ویرایشگر تمپلیت (ویرایش دستی سرفصل‌ها و برچسب‌ها)"
        )
        self.chk_struct_editor.setChecked(bool(self.cfg.get("structure_editor", True)))
        layout.addWidget(self.chk_struct_editor)

        self.editor_widget = QWidget()
        ev = QVBoxLayout(self.editor_widget)
        ev.setContentsMargins(4, 8, 4, 0)
        ev.setSpacing(6)
        ev.addWidget(QLabel("سرفصل‌ها (هر خط یک مورد):"))
        self.txt_headings = QTextEdit()
        self.txt_headings.setFixedHeight(84)
        self.txt_headings.setPlaceholderText(
            "مثلاً: فصل اول: مقدمه / Chapter 1: Introduction"
        )
        ev.addWidget(self.txt_headings)
        ev.addWidget(QLabel("برچسب‌های تکرارشونده (هر خط یک مورد):"))
        self.txt_labels = QTextEdit()
        self.txt_labels.setFixedHeight(64)
        self.txt_labels.setPlaceholderText(
            "مثلاً: بیشتر بدانید / فعالیت کنید / تمرین کنید / Key Terms"
        )
        ev.addWidget(self.txt_labels)
        self.lbl_editor_hint = QLabel("")
        self.lbl_editor_hint.setWordWrap(True)
        self.lbl_editor_hint.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        ev.addWidget(self.lbl_editor_hint)

        if self.job and self.job.structure:
            self.txt_headings.setPlainText(
                "\n".join(self.job.structure.get("headings", []))
            )
            self.txt_labels.setPlainText(
                "\n".join(self.job.structure.get("labels", []))
            )
        if self.job:
            self.lbl_editor_hint.setText(
                "این فهرست‌ها در پرامپت ترجمه استفاده می‌شوند تا هر سرفصل/برچسبِ "
                "تکرارشوندهٔ همین کتاب همیشه یک‌جور ترجمه شود. پس از باز کردن فایل "
                "به‌صورت خودکار پر می‌شوند (رایگان و محلی)؛ اینجا می‌توانید اصلاح یا "
                "افزایششان کنید و با «ذخیرهٔ تنظیمات» برای همین فایل ثبت کنید."
            )
        else:
            self.lbl_editor_hint.setText(
                "این فهرست‌ها بعد از باز کردن یک فایل به‌صورت خودکار تحلیل و پر "
                "می‌شوند (رایگان و محلی). برای ویرایش دستی، ابتدا فایلی باز کنید."
            )
            self.txt_headings.setEnabled(False)
            self.txt_labels.setEnabled(False)
        self.chk_struct_editor.toggled.connect(self.editor_widget.setVisible)
        self.editor_widget.setVisible(self.chk_struct_editor.isChecked())
        layout.addWidget(self.editor_widget)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        self.btn_test = QPushButton("🧪 تست اتصال")
        self.btn_test.clicked.connect(self.test_connection)
        btn_save = QPushButton("ذخیره")
        btn_save.clicked.connect(self.save)
        btn_cancel = QPushButton("انصراف")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_test)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self._on_provider_changed()

    def open_data_folder(self):
        """باز کردن پوشهٔ داده‌ها (%APPDATA%) در اکسپلورر ویندوز."""
        path = core.config_dir()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _on_provider_changed(self, *_args):
        is_openai = self.combo_provider.currentData() == "openai"
        self.lbl_base.setVisible(is_openai)
        self.txt_base.setVisible(is_openai)
        if is_openai:
            self.txt_api.setPlaceholderText("کلید (برای سرور لوکال معمولاً دلخواه است)")
            self.txt_model.setPlaceholderText("مثلاً llama3.2 یا qwen2.5:14b")
            if self.txt_model.text() in ("", "gemini-2.5-flash"):
                self.txt_model.setText("")
        else:
            self.txt_api.setPlaceholderText("کلید Google AI Studio")
            self.txt_model.setPlaceholderText("gemini-2.5-flash")
            if self.txt_model.text() in ("",):
                self.txt_model.setText("gemini-2.5-flash")

    def _collect(self):
        cfg = dict(self.cfg)
        cfg["provider"] = self.combo_provider.currentData()
        cfg["base_url"] = self.txt_base.text().strip()
        cfg["api_key"] = self.txt_api.text().strip()
        cfg["model"] = self.txt_model.text().strip()
        cfg["theme"] = self.combo_theme.currentData()
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
        self.lbl_status.setText("در حال تست اتصال…")
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
            if structure["headings"] or structure["labels"]:
                self.job.structure = structure
                self.job.save()
        self.saved.emit(dict(cfg))
        self.accept()


# ============================== دیالوگ ترجمهٔ کل کتاب ==============================

class BatchDialog(QDialog):
    """دیالوگ ترجمهٔ کل کتاب — بخش‌بندی منظم با حاشیه و فاصله‌های یکنواخت."""

    def __init__(self, total_pages, job, parent=None, structure_default=True):
        super().__init__(parent)
        self.setWindowTitle("📚 ترجمهٔ خودکار کل کتاب")
        self.setMinimumWidth(560)
        self._total = total_pages
        self.job = job

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # --- بخش ۱: محدوده ---
        layout.addWidget(section_label("۱. محدودهٔ ترجمه"))
        self.radio_all = QRadioButton(f"کل کتاب ({total_pages} صفحه)")
        self.radio_all.setChecked(True)
        self.radio_range = QRadioButton("محدودهٔ خاصی از صفحات")
        layout.addWidget(self.radio_all)
        layout.addWidget(self.radio_range)

        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        range_row.addWidget(QLabel("از صفحهٔ:"))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(1, max(1, total_pages))
        self.spin_start.setValue(1)
        # حداقل عرض کافی تا عدد تک‌رقمی («۱») هم دیده شود و اسپینر فشرده نشود
        self.spin_start.setMinimumWidth(110)
        align_spin_value_right(self.spin_start)
        range_row.addWidget(self.spin_start)
        range_row.addWidget(QLabel("تا صفحهٔ:"))
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
        self.lbl_resume.setStyleSheet("color: #38bdf8; font-size: 9pt;")
        layout.addWidget(self.lbl_resume)
        completed = job.count() if job else 0
        if completed:
            self.lbl_resume.setText(
                f"🔄 {completed} صفحه قبلاً ترجمه و ذخیره شده است — انتخاب کنید:"
            )
            self.radio_keep = QRadioButton(
                "ادامه از اولین صفحهٔ ناتمام (ذخیرهٔ قبلی حفظ می‌شود — سریع‌تر)"
            )
            self.radio_restart = QRadioButton(
                "ترجمه از اول شروع شود (ذخیرهٔ قبلی حذف می‌شود)"
            )
            self.radio_keep.setChecked(True)
            layout.addWidget(self.radio_keep)
            layout.addWidget(self.radio_restart)
            self.radio_restart.toggled.connect(self._update_estimate)
        else:
            self.lbl_resume.hide()

        # --- بخش ۲: گزینه‌ها ---
        layout.addWidget(section_label("۲. گزینه‌ها"))
        self.chk_structure = QCheckBox(
            "تحلیل ساختار کتاب و Template اختصاصی آن (محلی و رایگان)"
        )
        self.chk_structure.setChecked(bool(structure_default))
        layout.addWidget(self.chk_structure)

        self.chk_qc = QCheckBox(
            "بازبینی و اصلاح خودکار ترجمه (QC loop) — پیشنهادی؛ هزینهٔ API دو برابر"
        )
        self.chk_qc.setChecked(True)
        layout.addWidget(self.chk_qc)

        delay_row = QHBoxLayout()
        delay_row.setSpacing(8)
        delay_row.addWidget(QLabel("تاخیر بین درخواست‌ها:"))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 30)
        self.spin_delay.setSuffix(" ثانیه")
        self.spin_delay.setValue(int(CONFIG_DEFAULTS["request_delay_sec"]))
        self.spin_delay.setMinimumWidth(110)
        align_spin_value_right(self.spin_delay)
        delay_row.addWidget(self.spin_delay)
        delay_row.addStretch()
        layout.addLayout(delay_row)

        # --- جمع‌بندی + دکمه‌ها (تفویق بصری: شروع پررنگ، انصراف خنثی) ---
        self.lbl_estimate = QLabel("")
        self.lbl_estimate.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        layout.addWidget(self.lbl_estimate)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()
        self.btn_cancel = QPushButton("انصراف")
        self.btn_cancel.setMinimumWidth(120)
        self.btn_cancel.setStyleSheet(
            "QPushButton { background-color: #475569; color: #e2e8f0; }"
            "QPushButton:hover { background-color: #64748b; }"
        )
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_start = QPushButton("▶ شروع ترجمه")
        self.btn_start.setMinimumWidth(150)
        self.btn_start.setStyleSheet(
            "QPushButton { background-color: #f59e0b; color: #451a03; font-weight: bold; }"
            "QPushButton:hover { background-color: #fbbf24; }"
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
            f"صفحات این اجرا: {count} | ترجمه‌نشده: {remaining}"
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

        self.cfg = load_config()

        # برنامه به‌طور کامل راست‌چین (مخاطب فارسی‌زبان)؛ همهٔ دیالوگ‌ها،
        # منوها و چیدمان‌های بدون جهتِ صریح، از همین‌جا راست‌چین می‌شوند.
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.init_ui()
        self.apply_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
        except Exception:
            pass

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
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        # هدر
        header_frame = QFrame()
        header_layout = QHBoxLayout(header_frame)
        self.lbl_file = QLabel("هیچ فایلی انتخاب نشده است")
        self.btn_settings = QPushButton("⚙️ تنظیمات")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_open = QPushButton("📂 انتخاب کتاب (PDF / EPUB)")
        self.btn_open.clicked.connect(self.open_file)
        header_layout.addWidget(self.lbl_file)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_settings)
        header_layout.addWidget(self.btn_open)

        # ناوبری
        nav_frame = QFrame()
        nav_layout = QHBoxLayout(nav_frame)
        self.btn_next = QPushButton("◀ صفحه بعد")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self.next_page)
        self.lbl_page = QLabel("صفحه: ۰ / ۰")
        self.btn_prev = QPushButton("صفحه قبل ▶")
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self.prev_page)

        self.btn_translate = QPushButton("🚀 ترجمهٔ این صفحه")
        self.btn_translate.setEnabled(False)
        self.btn_translate.clicked.connect(self.translate_current_page)

        self.btn_batch = QPushButton("📚 ترجمهٔ کل کتاب")
        self.btn_batch.setEnabled(False)
        self.btn_batch.clicked.connect(self.start_batch)

        self.btn_copy = QPushButton("📋 کپی")
        self.btn_copy.setObjectName("btnCopy")  # رنگ فعال/غیرفعال از stylesheet (بدون خاکستری دائمی)
        self.btn_copy.setToolTip(
            "📋 کل متن ترجمهٔ صفحهٔ فعلی را کپی می‌کند.\n"
            "فقط وقتی این صفحه ترجمه شده باشد فعال (آبی) می‌شود؛ حالت خاکستری = غیرفعال."
        )
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_translation)

        self.btn_save = QPushButton("💾 ذخیره")
        self.btn_save.setEnabled(False)
        save_menu = QMenu(self)
        self.act_save_page = save_menu.addAction(
            "ترجمهٔ صفحهٔ فعلی (TXT)…", self.save_current_page
        )
        self.act_save_md = save_menu.addAction(
            "کل کتاب (Markdown)…", self.save_book_markdown
        )
        self.act_save_html = save_menu.addAction(
            "کل کتاب با تصاویر (HTML)…", self.save_book_html
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
        lang_layout = QHBoxLayout(lang_frame)

        self.lbl_src_lang = QLabel("🌐 زبان مبدأ:")
        self.combo_src = QComboBox()
        self.combo_src.addItem("انگلیسی", "en")
        self.combo_src.addItem("فارسی", "fa")

        self.lbl_tgt_lang = QLabel("زبان مقصد:")
        self.combo_tgt = QComboBox()
        self.combo_tgt.addItem("فارسی", "fa")
        self.combo_tgt.addItem("انگلیسی", "en")

        direction = self.cfg.get("direction", "en2fa")
        src_lang = "en" if direction == "en2fa" else "fa"
        tgt_lang = "fa" if src_lang == "en" else "en"
        self.combo_src.setCurrentIndex(0 if src_lang == "en" else 1)
        self.combo_tgt.setCurrentIndex(0 if tgt_lang == "fa" else 1)
        self.combo_src.currentIndexChanged.connect(self.on_src_changed)
        self.combo_tgt.currentIndexChanged.connect(self.on_tgt_changed)

        lbl_lang_hint = QLabel(
            "تعویض هر کدام، دیگری را خودکار تنظیم می‌کند و در همهٔ کتاب‌ها می‌ماند."
        )
        lbl_lang_hint.setStyleSheet("color: #94a3b8; font-size: 9pt;")

        lang_layout.addWidget(self.lbl_src_lang)
        lang_layout.addWidget(self.combo_src)
        lang_layout.addSpacing(20)
        lang_layout.addWidget(self.lbl_tgt_lang)
        lang_layout.addWidget(self.combo_tgt)
        lang_layout.addSpacing(20)
        lang_layout.addWidget(lbl_lang_hint)
        lang_layout.addStretch()

        # ردیف بازبینی
        review_frame = QFrame()
        review_layout = QHBoxLayout(review_frame)
        self.btn_view_source = QPushButton("📝 نمایش متن مبدأ")
        self.btn_view_source.setEnabled(False)
        self.btn_view_source.clicked.connect(self.toggle_view)
        self.chk_reviewed = QCheckBox("✓ بازبینی شد (تأیید انسانی)")
        self.chk_reviewed.setToolTip(
            "✓ وقتی ترجمهٔ این صفحه را خودتان خواندید و تأیید کردید تیک بزنید.\n"
            "در آمار (بازبینی‌شده) و خروجی نهایی کتاب لحاظ می‌شود."
        )
        self.chk_reviewed.setEnabled(False)
        self.chk_reviewed.toggled.connect(self.on_reviewed_toggled)
        self.lbl_stats = QLabel("")
        review_layout.addWidget(self.btn_view_source)
        review_layout.addWidget(self.chk_reviewed)
        review_layout.addWidget(self.lbl_stats)
        review_layout.addStretch()

        # نوار وضعیت / کنترل ترجمه (مشترک تک‌صفحه و کل کتاب)
        status_frame = QFrame()
        status_layout = QHBoxLayout(status_frame)
        self.lbl_status = QLabel("آماده")
        self.lbl_status.setStyleSheet("color: #38bdf8; font-weight: bold;")
        self.btn_pause = QPushButton("⏸ توقف")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_cancel_batch = QPushButton("■ لغو")
        self.btn_cancel_batch.setEnabled(False)
        self.btn_cancel_batch.clicked.connect(self.on_cancel_batch)
        status_layout.addWidget(self.btn_pause)
        status_layout.addWidget(self.btn_cancel_batch)
        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()
        self._status_controls = (self.btn_pause, self.btn_cancel_batch)
        status_frame.setVisible(False)
        self._status_frame = status_frame

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)  # متن داخلی Qt سمت چپ رسم می‌شد؛ حذف شد
        self.progress_bar.setVisible(False)
        # درصد، جداگانه و در سمت راست نوار (شروع سطر RTL)
        self.lbl_percent = QLabel("۰٪")
        self.lbl_percent.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11pt;")
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
        self.lbl_page_title = QLabel("📖 تصویر صفحه فعلی کتاب")
        self.lbl_page_title.setStyleSheet("font-weight: bold; color: #3b82f6;")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.lbl_image_viewer = QLabel()
        self.lbl_image_viewer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image_viewer.setText("تصویر صفحهٔ کتاب به محض بارگذاری اینجا رندر می‌شود.")
        self.scroll_area.setWidget(self.lbl_image_viewer)

        self.txt_source = QTextEdit()
        self.txt_source.setReadOnly(True)
        self.txt_source.setFont(QFont("Tahoma", 11))
        self.txt_source.setVisible(False)
        self.txt_source.setPlaceholderText("متن استخراج‌شدهٔ مبدأ این صفحه اینجا نمایش داده می‌شود.")

        page_column.addWidget(self.lbl_page_title)
        page_column.addWidget(self.scroll_area)
        page_column.addWidget(self.txt_source)

        translation_column = QVBoxLayout()
        self.lbl_output_title = QLabel("📝 ترجمه")
        self.lbl_output_title.setStyleSheet("font-weight: bold; color: #10b981;")
        self.txt_output = QTextEdit()
        self.txt_output.setReadOnly(True)
        self.txt_output.setFont(QFont("Tahoma", 12))
        self.txt_output.setText("پس از شروع ترجمه، متن ترجمه‌شده در این بخش ظاهر می‌شود.")
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
                    " background-color: #64748b; border: none; border-radius: 3px;"
                    " margin: 2px; }"
                    f'\nQSpinBox::up-button {{ image: url("{up_url}"); }}'
                    f'\nQSpinBox::down-button {{ image: url("{down_url}"); }}'
                )
            app.setStyleSheet(sheet + extra)

        if mode == "light":
            self.lbl_page.setStyleSheet("font-weight: bold; font-size: 11pt; color: #0284c7;")
            self.lbl_status.setStyleSheet("color: #0284c7; font-weight: bold;")
            self.lbl_image_viewer.setStyleSheet("background-color: #ffffff; color: #64748b;")
            self.btn_translate.setStyleSheet(
                "background-color: #10b981; color: #064e3b; font-weight: bold;"
            )
            self.btn_batch.setStyleSheet(
                "background-color: #f59e0b; color: #451a03; font-weight: bold;"
            )
        else:
            self.lbl_page.setStyleSheet("font-weight: bold; font-size: 11pt; color: #38bdf8;")
            self.lbl_status.setStyleSheet("color: #38bdf8; font-weight: bold;")
            self.lbl_image_viewer.setStyleSheet("background-color: #1e293b; color: #94a3b8;")
            self.btn_translate.setStyleSheet(
                "background-color: #5de387; color: #052e16; font-weight: bold;"
            )
            self.btn_batch.setStyleSheet(
                "background-color: #fbbf24; color: #451a03; font-weight: bold;"
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
        # اگر ویرایشگر تمپلیت تغییر کرده باشد، ساختار همگام می‌شود
        if self.job is not None:
            self.structure = self.job.structure
        # اعمال فوری به ترجمهٔ کل کتابِ متوقفشده (موتور در صفحهٔ بعد بازساخته می‌شود)
        if self.batch_worker is not None:
            self.batch_worker.update_settings(self.cfg)
            self.lbl_status.setText("⚙️ تنظیمات جدید در ادامهٔ ترجمه اعمال می‌شود")

    # ----------------------------- جهت ترجمه (مبدأ/مقصد) -----------------------------
    def on_src_changed(self, _index):
        src = self.combo_src.currentData()
        tgt = "fa" if src == "en" else "en"
        self._sync_combo(self.combo_tgt, tgt)
        self._apply_direction("en2fa" if src == "en" else "fa2en")

    def on_tgt_changed(self, _index):
        tgt = self.combo_tgt.currentData()
        src = "en" if tgt == "fa" else "fa"
        self._sync_combo(self.combo_src, src)
        self._apply_direction("en2fa" if src == "en" else "fa2en")

    @staticmethod
    def _sync_combo(combo, lang):
        """تنظیم کومبو بدون شلیک سیگنال (جلوگیری از حلقه و پرش چیدمان)."""
        if combo.currentData() != lang:
            combo.blockSignals(True)
            combo.setCurrentIndex(0 if combo.itemData(0) == lang else 1)
            combo.blockSignals(False)

    def _apply_direction(self, direction):
        if self.cfg.get("direction") != direction:
            self.cfg["direction"] = direction
            save_config(self.cfg)
        self.apply_output_direction()

    def apply_output_direction(self):
        d = DIRECTIONS.get(self.cfg.get("direction", "en2fa"), DIRECTIONS["en2fa"])
        # پنل ترجمه: جهت متن از زبانِ مقصد پیروی می‌کند (انگلیسی → چپ‌چین)
        self.txt_output.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if d["rtl"] else Qt.LayoutDirection.LeftToRight
        )
        # پنل متن مبدأ: جهت از زبانِ مبدأ پیروی می‌کند
        self.txt_source.setLayoutDirection(
            Qt.LayoutDirection.LeftToRight if d["rtl"] else Qt.LayoutDirection.RightToLeft
        )
        # عنوان پنل عمداً ثابت فارسی می‌ماند تا با تعویض زبان چیدمان نپرد

    # ----------------------------- فایل و صفحات -----------------------------
    def set_file_label(self, file_path):
        """فقط نام فایل در هدر — بدون تعداد صفحات (به درخواست کاربر)."""
        self.lbl_file.setText(f"📂 {os.path.basename(file_path)}")

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب کتاب", "", "Books (*.pdf *.epub)"
        )
        if not file_path:
            return
        try:
            self.doc = pymupdf.open(file_path)
            self.view_doc = pymupdf.open(file_path)
        except Exception as exc:  # noqa: BLE001
            self.txt_output.setText(f"خطا در باز کردن فایل:\n{exc}")
            return

        self.current_file = file_path
        self.total_pages = len(self.doc)
        self.current_page = 0
        self.job = JobStore(file_path).load()
        self.structure = self.job.structure
        self.view_source = False

        self.set_file_label(file_path)
        self.update_ui_controls()
        self.update_stats()
        self.refresh_current_page()

        done = self.job.count()
        if done:
            self.lbl_status.setText(
                f"🔄 {done} صفحه قبلاً ترجمه شده — برای ادامه «ترجمهٔ کل کتاب» را بزنید."
            )
        else:
            self.lbl_status.setText("آماده")

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
        self.lbl_status.setText("🧩 در حال تحلیل عمیق ساختار با هوش مصنوعی…")
        self.structure_worker = AiStructureWorker(
            self.cfg, sample, self.job.structure
        )
        self.structure_worker.done.connect(self.on_structure_ai_done)
        self.structure_worker.failed.connect(self.on_structure_ai_failed)
        self.structure_worker.finished.connect(self._cleanup_structure_worker)
        self.structure_worker.start()

    def on_structure_ai_done(self, merged):
        self.job.structure = merged
        self.job.save()
        self.structure = merged
        self.lbl_status.setText("🧩 ساختار عمیق AI ذخیره شد ✅")

    def on_structure_ai_failed(self, _message):
        self.lbl_status.setText("⚠️ تحلیل عمیق AI ناموفق بود (در تنظیمات قابل قطع است)")

    def _cleanup_structure_worker(self):
        w = self.sender()
        if isinstance(w, QThread):
            w.deleteLater()
            if w is self.structure_worker:
                self.structure_worker = None

    def update_ui_controls(self):
        if self.doc:
            self.lbl_page.setText(f"صفحه: {self.current_page + 1} / {self.total_pages}")
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
            f"ترجمه‌شده: {self.job.count()} از {self.total_pages} "
            f"| بازبینی‌شده: {self.job.reviewed_count()}"
        )

    def refresh_current_page(self, keep_output=False):
        """نمایش تصویر/مبدأ در پنل راست و ترجمهٔ ذخیره‌شده در پنل چپ.

        keep_output=True: متن پنل چپ دست‌نخورده می‌ماند (بعد از ترجمهٔ کل کتاب)."""
        if not self.doc:
            return
        view = self.view_doc or self.doc  # حین ترجمهٔ کل کتاب از دستگاه جدا خوانده می‌شود
        self.lbl_page.setText(f"صفحه: {self.current_page + 1} / {self.total_pages}")

        # پنل صفحهٔ مبدأ (راست)
        if self.view_source:
            try:
                text = extract_page_text(view.load_page(self.current_page))
                self.txt_source.setPlainText(text.strip() or "(این صفحه متن استخراج‌پذیری ندارد — تصویر اسکن‌شده است)")
            except Exception as exc:  # noqa: BLE001
                self.txt_source.setPlainText(f"خطا در استخراج متن:\n{exc}")
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
                self.txt_output.setText(
                    "برای ترجمهٔ این صفحه روی «ترجمهٔ این صفحه» کلیک کنید."
                )
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
            self.lbl_image_viewer.setText(f"خطا در رندر تصویری صفحه:\n{exc}")

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
            "📝 متن مبدأ صفحهٔ فعلی" if self.view_source
            else "📖 تصویر صفحهٔ فعلی کتاب"
        )
        self.btn_view_source.setText(
            "🖼 نمایش تصویر صفحه" if self.view_source
            else "📝 نمایش متن مبدأ"
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

    def _show_status(self, text, controls=None):
        self.lbl_status.setText(text)
        self._status_frame.setVisible(True)
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
            QMessageBox.warning(self, "تنظیمات", err)
            self.open_settings()
            return

        self.set_busy(True)
        self._show_status("در حال آماده‌سازی…")
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

    def on_progress(self, done, total):
        if total > 1:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
            pct = int(round(done * 100.0 / total))
            self.lbl_percent.setText(f"{fa_number(pct)}٪")
        else:
            self.progress_bar.setRange(0, 0)
            self.lbl_percent.setText("…")

    def _set_progress_visible(self, visible):
        """نمایش/پنهان‌سازی هم‌زمان نوار و لیبل درصد."""
        self.progress_bar.setVisible(visible)
        self.lbl_percent.setVisible(visible)
        if not visible:
            self.lbl_percent.setText("۰٪")

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
        self._end_status("ترجمهٔ این صفحه تمام شد ✅")
        self.set_busy(False)
        self.update_ui_controls()
        self.update_stats()
        self.refresh_current_page()

    def on_single_failed(self, message):
        self._end_status("ترجمه ناتمام ماند ❌")
        self.set_busy(False)
        self.update_ui_controls()
        self.txt_output.setText(message)

    def _end_status(self, text):
        self._set_progress_visible(False)
        self._status_frame.setVisible(True)
        self._set_batch_controls(False)
        self.lbl_status.setText(text)

    # ----------------------------- ترجمهٔ کل کتاب -----------------------------
    def start_batch(self):
        if not self.doc or self.single_worker or self.batch_worker:
            return
        err = validate_config(self.cfg)
        if err:
            QMessageBox.warning(self, "تنظیمات", err)
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
            self.lbl_status.setText("🗑 ذخیرهٔ قبلی حذف شد — ترجمه از اول شروع می‌شود")

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
        header = f"📚 ترجمهٔ خودکار — صفحهٔ {start + 1} تا {end + 1}"
        if qc:
            header += " | QC: روشن"
        self.txt_output.append(header)
        self.txt_output.append("")

        self.launch_batch_worker()
        self.lbl_status.setText("شروع ترجمهٔ خودکار…")

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
        self._set_batch_controls(True)
        self.btn_pause.setText("⏸ توقف")
        self._following_batch = True  # نمایش زندهٔ صفحهٔ در حال ترجمه
        self.batch_worker.start()

    def _cleanup_batch(self):
        w = self.sender()
        if isinstance(w, QThread):
            w.deleteLater()
            if w is self.batch_worker:
                self.batch_worker = None

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
        self.txt_output.append(f"── صفحهٔ {page + 1} ──")
        self.txt_output.append(text)
        self.txt_output.append("")
        self.lbl_page.setText(f"صفحه: {page + 1} / {self.total_pages}")
        self.update_stats()
        cursor = self.txt_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.txt_output.setTextCursor(cursor)

    def on_batch_paused(self):
        self.btn_pause.setText("▶ ادامه")
        self.btn_settings.setEnabled(True)  # حین توقف می‌توان تنظیمات را ویرایش کرد
        self.lbl_status.setText("⏸ توقف — ترجمه متوقف شد (ذخیره‌شده)")

    def on_batch_resumed(self):
        self.btn_pause.setText("⏸ توقف")
        self.btn_settings.setEnabled(False)
        self.lbl_status.setText("▶ ادامهٔ ترجمه…")

    def on_batch_quota(self, message):
        self.lbl_status.setText("⏳ سهمیه پر شد — با «ادامه» دوباره شروع کنید")
        self.btn_pause.setText("▶ ادامه")
        self.btn_settings.setEnabled(True)  # تا تنظیمات را اصلاح کنید
        QMessageBox.warning(self, "سهمیهٔ API", message)

    def on_batch_finished(self, message):
        self._idle_after_batch()
        self.lbl_status.setText(message)
        QMessageBox.information(self, "ترجمهٔ کل کتاب", message)

    def on_batch_failed(self, message):
        self._idle_after_batch()
        self.lbl_status.setText("❌ ترجمه ناتمام ماند")
        QMessageBox.critical(self, "خطا در ترجمه", message)

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
            self.lbl_status.setText("ادامهٔ ترجمه از صفحهٔ ناتمام…")
            self.launch_batch_worker()

    def on_cancel_batch(self):
        w = self.batch_worker
        if w is not None and w.isRunning():
            self.lbl_status.setText("در حال لغو…")
            w.cancel()
        else:
            self._idle_after_batch()
            self.lbl_status.setText("ترجمه لغو شد")

    # ----------------------------- ذخیره و خروجی -----------------------------
    def _source_name(self):
        return os.path.basename(self.current_file or "book")

    def save_current_page(self):
        if not self.job or not self.job.get(self.current_page):
            QMessageBox.information(self, "ذخیره", "ابتدا این صفحه را ترجمه کنید.")
            return
        stem = os.path.splitext(self._source_name())[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ ترجمهٔ صفحه",
            f"{stem}_page{self.current_page + 1}.txt", "Text (*.txt)",
        )
        if not path:
            return
        export_page_text(
            self.job.get(self.current_page), self._source_name(),
            self.current_page, path,
        )
        QMessageBox.information(self, "ذخیره", f"ذخیره شد:\n{path}")

    def save_book_markdown(self):
        if not self.job or self.job.count() == 0:
            QMessageBox.information(self, "ذخیره", "هنوز صفحه‌ای ترجمه نشده است.")
            return
        stem = os.path.splitext(self._source_name())[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ کل کتاب", f"{stem}_translated.md",
            "Markdown (*.md)",
        )
        if not path:
            return
        export_markdown(self.job, self._source_name(), path)
        QMessageBox.information(self, "ذخیره", f"ذخیره شد:\n{path}")

    def save_book_html(self):
        if not self.job or self.job.count() == 0:
            QMessageBox.information(self, "ذخیره", "هنوز صفحه‌ای ترجمه نشده است.")
            return
        if self.batch_worker is not None and self.batch_worker.isRunning():
            QMessageBox.information(
                self, "خروجی HTML",
                "حین ترجمهٔ کل کتاب در دسترس نیست (همزمانی با PDF). "
                "می‌توانید Markdown را همین حالا ذخیره کنید.",
            )
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "پوشهٔ خروجی کتاب HTML"
        )
        if not out_dir:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            index_path = export_html(self.job, self.doc, self._source_name(), out_dir)
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, "خروجی HTML",
            f"کتاب کامل با تصاویر ساخته شد:\n{index_path}\n\n"
            "برای تبدیل به PDF: فایل را در مرورگر باز کنید و Print → Save as PDF.",
        )

    def copy_translation(self):
        text = self.txt_output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.lbl_status.setText("📋 کپی شد")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernTranslatorApp()
    window.show()
    sys.exit(app.exec())
