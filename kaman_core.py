# -*- coding: utf-8 -*-
"""
kaman_core — هستهٔ منطقی kaman ai translator نسخهٔ ۳ (بدون Qt).

شامل: پیکربندی + رمزنگاری کلید API (DPAPI ویندوز)، پرامپت‌های دوطرفه،
تکه‌تکه‌سازی خودکار، کنترل هوشمند کانتکست، تحلیل ساختار کتاب،
موتورهای ترجمه (Google Gemini و سازگار با OpenAI/لوکال)، QC،
ذخیرهٔ وضعیت کار (Job) و خروجی کامل کتاب (Markdown/HTML).
"""

import os
import sys
import json
import re
import time
import base64
import hashlib
import threading
import html as html_mod
import urllib.request
import urllib.error
import urllib.parse
from collections import Counter

import pymupdf  # PyMuPDF (نام جدید؛ fitz فقط نام قدیمی است و هشدار می‌دهد)

APP_NAME = "kaman-ai-translator"
APP_VERSION = "3.2.2"

# --------------------------------------------------------------------------
# خطاهای قابل تشخیص
# --------------------------------------------------------------------------

class TranslationError(Exception):
    """خطای عمومی ترجمه با پیام فارسی."""


class QuotaExhaustedError(TranslationError):
    """سهمیه/محدودیت نرخ API تمام شده — تردید موقت لازم است."""


class CancelledError(Exception):
    """عملیات توسط کاربر لغو شده."""


# --------------------------------------------------------------------------
# زبان پیام‌های هسته (هماهنگ با زبان رابط کاربری: fa | en)
# --------------------------------------------------------------------------

_UI_LANG = "fa"


def set_language(lang):
    global _UI_LANG
    _UI_LANG = "en" if lang == "en" else "fa"


def get_language():
    return _UI_LANG


_MSGS = {
    "fa": {
        "base_url_empty": "آدرس سرور (Base URL) خالی است.",
        "model_empty": "نام مدل را وارد کنید یا اجازه دهید برنامه مدل‌های سرور را پیدا کند.",
        "gemini_key_empty": "API key گوگل تنظیم نشده است. از دکمهٔ «تنظیمات» آن را وارد کنید.",
        "gemini_key_missing": "API key گوگل تنظیم نشده است.",
        "missing_pydantic": (
            "وابستگی pydantic نصب نیست. در محیط برنامه دستور "
            "pip install -r requirements.txt را اجرا کنید."
        ),
        "model_not_set": "نام مدل تنظیم نشده است (تنظیمات → مدل).",
        "empty_response": "پاسخ خالی از سرور دریافت شد.",
        "server_timeout": "زمان اتصال به سرور تمام شد (timeout).",
        "server_error": "خطای سرور: {detail}",
        "parse_error": (
            "خروجی مدل قابل تحلیل نبود (JSON نامعتبر و body_text هم قابل استخراج نشد).\n"
            "علت‌های محتمل:\n"
            "۱. مدل برای خروجی ساخت‌یافته ضعیف است — مدلی قوی‌تر انتخاب کنید "
            "(برای سرور لوکال مثلاً qwen2.5:14b یا بالاتر، یا موتور Gemini).\n"
            "۲. پاسخ مدل نصفه قطع شده است — در Ollama پنجرهٔ کانتکست پیش‌فرض کوچک است؛ "
            "num_ctx را بالا ببرید (مثلاً 16384) یا اندازهٔ تکه‌ها را کم کنید."
        ),
        "truncated_error": (
            "پاسخ مدل نصفه قطع شد (finish_reason = length) — پنجرهٔ کانتکست مدل پر شده است.\n"
            "راه‌حل: در Ollama مقدار num_ctx را بالا ببرید (مثلاً 16384، با Modelfile یا "
            "OLLAMA_CONTEXT_LENGTH) یا مدلی با کانتکست بزرگ‌تر انتخاب کنید."
        ),
        "test_ok": "اتصال موفق است ✅ پاسخ سرور: {reply}",
        "test_json_fail": (
            "اتصال برقرار است، اما مدل خروجی ساخت‌یافته (JSON) برنگرداند.\n"
            "برای ترجمهٔ کتاب، مدلی قوی‌تر لازم است (مثلاً qwen2.5:14b یا بالاتر)."
        ),
        "test_local_hint": (
            "\n⚠️ سرور لوکال است: برای کتاب‌های طولانی، پنجرهٔ کانتکست را بالا ببرید "
            "(در Ollama: ‏num_ctx‏ مثلاً 16384) وگرنه پاسخ‌ها نصفه قطع می‌شوند."
        ),
        "test_fail": "اتصال ناموفق ❌\n{detail}",
        "gemini_location": (
            "دسترسی Gemini از این موقعیت یا IP پشتیبانی نمی‌شود یا توسط Google محدود شده است. "
            "اگر از IP ایران استفاده می‌کنید، ممکن است محدودیت منطقه‌ای علت باشد. "
            "از شبکه/منطقهٔ پشتیبانی‌شده استفاده کنید یا موتور سرور سازگار با OpenAI را انتخاب کنید."
        ),
        "gemini_key_error": "کلید Gemini معتبر نیست یا دسترسی Generative Language API برای آن فعال نیست. کلید و فعال بودن API را بررسی کنید.",
        "gemini_model_error": "مدل Gemini «{model}» در دسترس این کلید نیست یا شناسهٔ آن معتبر نیست. شناسهٔ مدل را بررسی کنید یا فیلد مدل را خالی بگذارید تا مدل پیش‌فرض امتحان شود.",
        "gemini_http_error": "اتصال Gemini با خطای دسترسی/API ({code}) رد شد. کلید، دسترسی API و محدودیت‌های منطقه‌ای/شبکه را بررسی کنید. جزئیات: {detail}",
        "gemini_proxy_invalid": "آدرس پراکسی باید با http:// یا https:// شروع شود و میزبان/درگاه معتبر داشته باشد.",
        "gemini_blocked": "Google پاسخ Gemini را به‌دلیل فیلتر ایمنی رد کرد ({reason}). متن مبدأ را بررسی کنید یا از مدلی/سرویسی استفاده کنید که این محتوای کتاب را می‌پذیرد.",
        "gemini_network_error": "ارتباط با Google Gemini برقرار نشد یا بیش از حد طول کشید. اینترنت، پراکسی/فایروال و دسترسی منطقه‌ای را بررسی کنید. اگر از IP ایران استفاده می‌کنید، ممکن است محدودیت دسترسی Google دخیل باشد. جزئیات: {detail}",
        "gemini_fallback": "مدل پیش‌فرض شلوغ بود؛ اتصال با مدل جایگزین {model} موفق شد.",
        "gemini_quota": "سهمیه یا محدودیت نرخ API گوگل پر شد (خطای 429). کمی بعد دوباره ادامه دهید.",
        "gemini_api_error": "خطای API جمینای ({code}): {detail}",
        "gemini_error": "خطای API جمینای: {detail}",
        "gemini_recitation": "مدل به دلیل گارد کپی‌رایت (finish_reason=RECITATION) پاسخی برنگرداند. این بخش برای بازبینی دستی علامت‌گذاری شد.",
        "gemini_no_response": "پاسخی از سرور جمینای دریافت نشد.",
        "server_quota": "سرور درخواست‌ها را محدود کرد (429):\n{detail}",
        "server_http_error": "خطای HTTP {code} از سرور:\n{detail}",
        "server_connect_failed": "اتصال به سرور برقرار نشد ({url}):\n{detail}",
        "model_list_failed": "دریافت فهرست مدل‌ها از {url} ممکن نشد: {detail}",
        "model_none_returned": "سرور هیچ شناسهٔ مدلی برنگرداند ({url}). یک مدل روی سرور بارگذاری یا انتخاب کنید، یا شناسه‌اش را در تنظیمات وارد کنید.",
        "model_chat_not_identified": "فهرست سرور قابلیت گفت‌وگوی هیچ مدلی را مشخص نمی‌کند. شناسهٔ مدل مناسب گفت‌وگو را در تنظیمات → مدل وارد کنید؛ انتخاب خودکار انجام نشد.",
        "key_decrypt_failed": "بازگردانی کلید API رمزنگاری‌شده شکست خورد (احتمالاً کلید روی حساب کاربری دیگری ذخیره شده است):\n{detail}",
        "legacy_job_archived": "{n} ترجمهٔ ذخیره‌شده از نسخهٔ قدیمی زبان مقصد مشخصی نداشت؛ برای جلوگیری از نمایش ترجمه با زبان اشتباه، نگه‌داری شد اما برای این زبان دوباره ترجمه می‌شود.",
    },
    "en": {
        "base_url_empty": "The server address (Base URL) is empty.",
        "model_empty": "Enter a model name or let the app discover one from the server.",
        "gemini_key_empty": "The Google API key is not set. Enter it from the Settings button.",
        "gemini_key_missing": "The Google API key is not set.",
        "missing_pydantic": (
            "The pydantic dependency is missing. Install the app requirements with "
            "pip install -r requirements.txt."
        ),
        "model_not_set": "No model name is set (Settings → Model).",
        "empty_response": "The server returned an empty response.",
        "server_timeout": "The connection to the server timed out.",
        "server_error": "Server error: {detail}",
        "parse_error": (
            "The model output could not be parsed (invalid JSON and no extractable body_text).\n"
            "Likely causes:\n"
            "1. The model is too weak for structured output — choose a stronger model "
            "(for a local server, e.g. qwen2.5:14b or larger, or the Gemini engine).\n"
            "2. The reply was cut off — Ollama's default context window is small; "
            "raise num_ctx (e.g. 16384) or reduce the chunk size."
        ),
        "truncated_error": (
            "The model reply was cut off (finish_reason = length) — the model's context window is full.\n"
            "Fix: raise num_ctx in Ollama (e.g. 16384, via a Modelfile or "
            "OLLAMA_CONTEXT_LENGTH), or choose a model with a larger context."
        ),
        "test_ok": "Connection OK ✅ Server reply: {reply}",
        "test_json_fail": (
            "The connection works, but the model did not return structured (JSON) output.\n"
            "Book translation needs a stronger model (e.g. qwen2.5:14b or larger)."
        ),
        "test_local_hint": (
            "\n⚠️ This is a local server: for long books, raise the context window "
            "(in Ollama: num_ctx, e.g. 16384) or replies will be cut off."
        ),
        "test_fail": "Connection failed ❌\n{detail}",
        "gemini_location": (
            "Gemini access is unavailable or restricted from this location/IP. "
            "If you are connecting from Iran, a regional restriction may be the cause. "
            "Use a supported network/region or choose an OpenAI-compatible server."
        ),
        "gemini_key_error": "The Gemini API key is invalid, or the Generative Language API is not enabled for it. Check the key and API access.",
        "gemini_model_error": "Gemini model '{model}' is unavailable to this key or the model ID is invalid. Check its ID, or leave Model blank to try the default model.",
        "gemini_http_error": "Gemini rejected the request ({code}). Check the API key, API access, and regional/network restrictions. Details: {detail}",
        "gemini_proxy_invalid": "The proxy URL must start with http:// or https:// and include a valid host and port.",
        "gemini_blocked": "Google blocked the Gemini response with a safety filter ({reason}). Review the source passage or use a model/service that permits this book content.",
        "gemini_network_error": "Could not reach Google Gemini before the request timed out. Check your internet connection, proxy/firewall, and regional availability. If you are using an Iran IP, Google access restrictions may be involved. Details: {detail}",
        "gemini_fallback": "The default model was busy; connection succeeded with fallback model {model}.",
        "gemini_quota": "Google API quota or rate limit reached (error 429). Wait a bit, then resume.",
        "gemini_api_error": "Gemini API error ({code}): {detail}",
        "gemini_error": "Gemini API error: {detail}",
        "gemini_recitation": "The model returned no text because of the copyright guard (finish_reason=RECITATION). This section was marked for manual review.",
        "gemini_no_response": "No response was received from the Gemini server.",
        "server_quota": "The server rate-limited the requests (429):\n{detail}",
        "server_http_error": "HTTP {code} error from the server:\n{detail}",
        "server_connect_failed": "Could not connect to the server ({url}):\n{detail}",
        "model_list_failed": "Could not list models from {url}: {detail}",
        "model_none_returned": "The server returned no model IDs at {url}. Load/select a model on the server or enter its ID in Settings.",
        "model_chat_not_identified": "No model in the server catalog has explicit chat capability metadata. Enter a chat-capable model ID in Settings -> Model; no model was selected automatically.",
        "key_decrypt_failed": "Failed to decrypt the saved API key (it was probably stored under a different user account):\n{detail}",
        "legacy_job_archived": "{n} saved page translations from an older version had no target-language metadata. They were preserved, but this language will be translated again to prevent mixing languages.",
    },
}


def msg(key, **kwargs):
    table = _MSGS.get(_UI_LANG, _MSGS["fa"])
    text = table.get(key) or _MSGS["fa"][key]
    return text.format(**kwargs) if kwargs else text


# --------------------------------------------------------------------------
# پیکربندی + رمزنگاری کلید API
# --------------------------------------------------------------------------

CONFIG_DEFAULTS = {
    "api_key": "",
    "provider": "gemini",                 # gemini | openai
    "base_url": "http://localhost:11434/v1",
    "gemini_proxy": "",
    "gemini_endpoint_version": 1,
    "model": "gemini-3.8-flash",
    "direction": "en2fa",                 # en2fa | fa2en | en2ar | ar2en | fa2ar | ar2fa
    "ui_lang": "fa",                      # fa | en — زبان رابط کاربری
    "profiles": {},                       # حافظهٔ جدا برای هر موتور (در load_config ساخته می‌شود)
    "theme": "system",                    # system | dark | light
    "temperature": 0.1,
    "chunk_max_chars": 6000,
    "context_tail_chars": 700,
    "request_delay_sec": 0,
    "structure_auto": True,      # (الف) تحلیل محلی ساختار هنگام باز کردن فایل
    "structure_ai": False,       # (ب) پاس عمیق AI (۱ درخواست) — هزینه‌دار
    "structure_editor": True,    # (ج) نمایش ویرایشگر تمپلیت در تنظیمات
}

_DPAPI_ENTROPY = b"kaman-ai-translator|dpapi|v3"
_PREFIX_DPAPI = "dpapi:"
_PREFIX_B64 = "b64:"


def _win_crypt(data: bytes, entropy: bytes, unprotect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
    ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    func = crypt32.CryptUnprotectData if unprotect else crypt32.CryptProtectData
    ok = func(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(ent_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(f"DPAPI error: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(out_blob.pbData)


def _log_encrypt_fallback(exc: Exception) -> None:
    """ثبت علت ناتوانی DPAPI تا خطا بی‌صدا بلعیده نشود.

    خروجی در فایل کوچکی کنار تنظیمات نوشته می‌شود (بدون هیچ دادهٔ محرمانه —
    فقط زمان، علت و پیام خطا).
    """
    try:
        from datetime import datetime, timezone

        path = os.path.join(config_dir(), "encrypt_fallback.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                f"DPAPI unavailable -> fell back to base64 storage: {exc!r}\n"
            )
    except OSError:
        pass  # حتی لاگ هم در دسترس نبود؛ رفتار قبلی (ادامهٔ ذخیره‌سازی) حفظ می‌شود


def encrypt_secret(plain: str) -> str:
    """رمزنگاری کلید API برای ذخیره روی دیسک (DPAPI ویندوز؛ بدون وابستگی اضافه)."""
    if not plain:
        return ""
    if sys.platform == "win32":
        try:
            blob = _win_crypt(plain.encode("utf-8"), _DPAPI_ENTROPY, unprotect=False)
            return _PREFIX_DPAPI + base64.b64encode(blob).decode("ascii")
        except Exception as exc:
            # اگر DPAPI در دسترس نبود، به رمزنگاری ضعیف‌تر برمی‌گردیم —
            # ولی علت خطا را بی‌صدا دور نمی‌ریزیم: در encrypt_fallback.log ثبت می‌شود.
            _log_encrypt_fallback(exc)
    return _PREFIX_B64 + base64.b64encode(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(stored: str) -> str:
    """بازگرداندن کلید ذخیره‌شده به متن ساده (پشتیبانی از قالب قدیمی/بدون رمزنگاری)."""
    if not stored:
        return ""
    try:
        if stored.startswith(_PREFIX_DPAPI):
            raw = base64.b64decode(stored[len(_PREFIX_DPAPI):])
            return _win_crypt(raw, _DPAPI_ENTROPY, unprotect=True).decode("utf-8")
        if stored.startswith(_PREFIX_B64):
            return base64.b64decode(stored[len(_PREFIX_B64):]).decode("utf-8")
    except Exception as exc:
        raise TranslationError(msg("key_decrypt_failed", detail=exc))
    return stored  # قالب قدیمی: متن ساده


def is_encrypted(stored: str) -> bool:
    return bool(stored) and (
        stored.startswith(_PREFIX_DPAPI) or stored.startswith(_PREFIX_B64)
    )


def config_dir():
    base = os.environ.get("APPDATA") or os.path.dirname(os.path.abspath(__file__))
    folder = os.path.join(base, APP_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.dirname(os.path.abspath(__file__))
    return folder


def config_file_path():
    return os.path.join(config_dir(), "config.json")


def jobs_dir():
    folder = os.path.join(config_dir(), "jobs")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return folder


def default_profiles():
    """حافظهٔ پیش‌فرض هر موتور: کلید، آدرس سرور و مدلِ مخصوص خودش."""
    return {
        "gemini": {"api_key": "", "base_url": "", "proxy": "", "model": "gemini-3.8-flash"},
        "openai": {
            "api_key": "",
            "base_url": "http://localhost:11434/v1",
            "model": "",
        },
    }


def _sync_active_profile(cfg):
    """مقادیر تخت (موتور فعال) را داخل پروفایل همان موتور می‌نویسد."""
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        profiles = default_profiles()
        cfg["profiles"] = profiles
    provider = cfg.get("provider", "gemini")
    slot = profiles.get(provider)
    if not isinstance(slot, dict):
        slot = dict(default_profiles().get(provider, {}))
        profiles[provider] = slot
    slot["api_key"] = cfg.get("api_key", "")
    slot["base_url"] = cfg.get("base_url", "")
    slot["model"] = cfg.get("model", "")
    if provider == "gemini":
        slot["proxy"] = cfg.get("gemini_proxy", "")
    return cfg


def switch_provider(cfg, new_provider):
    """تعویض موتور: مقادیر فعلی در پروفایل موتور قبلی ذخیره می‌شود و
    مقادیر ذخیره‌شدهٔ موتور جدید در فیلدهای تخت بارگذاری می‌شود —
    پس هیچ مقداری (کلید/آدرس/مدل) از یک موتور به موتور دیگر نشت نمی‌کند
    و با برگشتن به موتور قبلی، اطلاعاتش دقیقاً برمی‌گردد."""
    _sync_active_profile(cfg)
    slot = cfg["profiles"].get(new_provider)
    if not isinstance(slot, dict):
        slot = default_profiles()[new_provider]
        cfg["profiles"][new_provider] = slot
    cfg["provider"] = new_provider
    cfg["api_key"] = slot.get("api_key", "")
    cfg["base_url"] = slot.get("base_url", "")
    cfg["model"] = slot.get("model", "")
    cfg["gemini_proxy"] = slot.get("proxy", "") if new_provider == "gemini" else cfg.get("gemini_proxy", "")
    return cfg


def _ensure_profiles(cfg, stored_profiles=None):
    """پروفایل‌ها را از دادهٔ ذخیره‌شده کامل می‌کند؛ مقادیر تختِ فعلی
    (قالب قدیمیِ بدون پروفایل) به‌عنوان پروفایل موتور فعال مهاجرت می‌یابند."""
    profiles = default_profiles()
    if isinstance(stored_profiles, dict):
        for name, slot in stored_profiles.items():
            if name in profiles and isinstance(slot, dict):
                for key in ("api_key", "base_url", "model", "proxy"):
                    if key in slot:
                        profiles[name][key] = slot[key]
    gemini_stored = stored_profiles.get("gemini", {}) if isinstance(stored_profiles, dict) else {}
    if "proxy" not in gemini_stored and cfg.get("gemini_proxy"):
        profiles["gemini"]["proxy"] = cfg["gemini_proxy"]
    # Gemini 2.5 Flash is now restricted for new API users. Migrate the old
    # shipped default (including blank values) to Google's current stable Flash.
    gemini = profiles["gemini"]
    if cfg.get("gemini_endpoint_version", 0) != 1:
        # Before this setting existed, Gemini ignored Base URL. Old loopback
        # values usually belonged to the OpenAI engine; don't route Gemini to
        # that server during one-time migration.
        host = urllib.parse.urlparse(gemini.get("base_url", "")).hostname
        if host in ("localhost", "127.0.0.1", "::1"):
            gemini["base_url"] = ""
            if cfg.get("provider", "gemini") == "gemini":
                cfg["base_url"] = ""
        cfg["gemini_endpoint_version"] = 1
    # The old app's OpenAI-compatible default should not become Gemini's
    # endpoint when migrating a config with no per-engine profiles.
    if gemini.get("base_url", "").rstrip("/") == "http://localhost:11434/v1":
        gemini["base_url"] = ""
    if (
        cfg.get("provider", "gemini") == "gemini"
        and (cfg.get("base_url") or "").rstrip("/") == "http://localhost:11434/v1"
    ):
        cfg["base_url"] = ""
    if gemini.get("model") in (None, "", "gemini-2.5-flash"):
        gemini["model"] = "gemini-3.8-flash"
    if cfg.get("provider", "gemini") == "gemini" and cfg.get("model") in (
        None, "", "gemini-2.5-flash"
    ):
        cfg["model"] = "gemini-3.8-flash"
    cfg["profiles"] = profiles
    if cfg.get("provider", "gemini") == "gemini":
        cfg["gemini_proxy"] = profiles["gemini"].get("proxy", "")
    _sync_active_profile(cfg)
    return cfg


def _safe_decrypt(stored):
    """رمزگشایی بدون کرش: کلیدی که روی حساب/ماشین دیگری ساخته شده (کانفیگ
    کپی‌شده) نباید جلوی باز شدن برنامه را بگیرد — خالی برمی‌گردد تا کاربر
    دوباره واردش کند."""
    try:
        return decrypt_secret(stored)
    except Exception:  # noqa: BLE001
        return ""


def load_config():
    cfg = dict(CONFIG_DEFAULTS)
    raw_key = ""
    stored_profiles = None
    migrated_gemini_endpoint = False
    try:
        with open(config_file_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update({
                k: v for k, v in data.items()
                if k in CONFIG_DEFAULTS and k != "profiles"
            })
            raw_key = data.get("api_key", "")
            if "gemini_endpoint_version" not in data:
                cfg["gemini_endpoint_version"] = 0
                migrated_gemini_endpoint = True
            raw_proxy = data.get("gemini_proxy", "")
            cfg["gemini_proxy"] = (
                _safe_decrypt(raw_proxy) if is_encrypted(raw_proxy) else raw_proxy
            )
            stored_profiles = data.get("profiles")
    except (OSError, ValueError):
        # کانفیگ خراب را کنار می‌گذاریم تا کلید رمزنگاری‌شده قابل بازیابی بماند
        try:
            os.replace(config_file_path(), config_file_path() + ".corrupt.bak")
        except OSError:
            pass
        _ensure_profiles(cfg)
        return cfg

    if isinstance(stored_profiles, dict):
        decrypted = {}
        for name, slot in stored_profiles.items():
            if isinstance(slot, dict):
                slot = dict(slot)
                if "api_key" in slot:
                    slot["api_key"] = _safe_decrypt(slot.get("api_key", ""))
                if "proxy" in slot and is_encrypted(slot.get("proxy", "")):
                    slot["proxy"] = _safe_decrypt(slot.get("proxy", ""))
                decrypted[name] = slot
        stored_profiles = decrypted
    _ensure_profiles(cfg, stored_profiles)

    # مهاجرت: کلید قدیمیِ رمزنگاری‌نشده را همین حالا رمزنگاری و ذخیره می‌کنیم
    if (raw_key and not is_encrypted(raw_key)) or migrated_gemini_endpoint:
        if raw_key and not is_encrypted(raw_key):
            cfg["api_key"] = raw_key
        else:
            cfg["api_key"] = _safe_decrypt(raw_key)
        save_config(cfg)
    else:
        cfg["api_key"] = _safe_decrypt(raw_key)
    _sync_active_profile(cfg)
    return cfg


def save_config(cfg):
    _sync_active_profile(cfg)
    disk = dict(cfg)
    disk["api_key"] = encrypt_secret(cfg.get("api_key", ""))
    disk["gemini_proxy"] = encrypt_secret(cfg.get("gemini_proxy", ""))
    profiles = {}
    for name, slot in (cfg.get("profiles") or {}).items():
        slot = dict(slot)
        slot["api_key"] = encrypt_secret(slot.get("api_key", ""))
        slot["proxy"] = encrypt_secret(slot.get("proxy", ""))
        profiles[name] = slot
    disk["profiles"] = profiles
    path = config_file_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(disk, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def validate_config(cfg):
    """برگرداندن پیام خطا (به زبان رابط کاربری) یا None اگر پیکربندی سالم است."""
    provider = cfg.get("provider", "gemini")
    if provider == "openai":
        if not (cfg.get("base_url") or "").strip():
            return msg("base_url_empty")
        return None
    if not (cfg.get("api_key") or "").strip():
        return msg("gemini_key_empty")
    proxy = (cfg.get("gemini_proxy") or "").strip()
    if proxy:
        parsed = urllib.parse.urlparse(proxy)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return msg("gemini_proxy_invalid")
    return None


def resource_path(name):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


# --------------------------------------------------------------------------
# جهت ترجمه (دوطرفه)
# --------------------------------------------------------------------------

JSON_SCHEMA_PART = (
    "You MUST return the output inside a valid JSON object with these exact keys:\n"
    "{\n"
    "  \"title_or_headings\": \"Main title or headings (if none, leave empty)\",\n"
    "  \"subtitles\": \"Subtitles (if none, leave empty)\",\n"
    "  \"authors\": \"Author names translated (if none, leave empty)\",\n"
    "  \"publisher\": \"Publisher name (if none, leave empty)\",\n"
    "  \"body_text\": \"Main paragraph and content translation (if none, leave empty)\"\n"
    "}\n"
)

DIRECTIONS = {
    "en2fa": {
        "label": "انگلیسی ⟶ فارسی",
        "source": "English",
        "target": "Persian (Farsi)",
        "rtl": True,
        "source_rtl": False,
        "system": (
            "You are an elite academic translator specializing in psychology and philosophy books. "
            "Your translation must NOT sound like machine translation. "
            "Use fluent, dignified, and formal Persian (Farsi) academic prose.\n"
            "CRITICAL RULES:\n"
            "- Do not translate word-for-word. Translate meaning-for-meaning with appropriate "
            "Persian academic idioms.\n"
            "- COMPLETENESS: translate EVERY sentence of the input — never omit, skip, summarize "
            "or truncate, even if the text repeats or looks unusual.\n"
            "- Preserve structure: paragraph breaks, headings, lists, captions, footnote markers "
            "and emphasis must survive in the same order.\n"
            "- Keep numbers, units, equations, variable names, code, URLs and citation markers "
            "(like [12]) unchanged; translate only the words around them.\n"
            "- Use ONE consistent Persian equivalent for each key term throughout the book; when a "
            "BOOK STRUCTURE CONTEXT is provided, follow it as the house style.\n"
            "- If the text looks like table cells or figure captions, keep the cell separation and "
            "caption labels intact.\n"
            "- Keep the JSON structure perfectly clean."
        ),
        "labels": {
            "authors": "✍️ نویسنده/نویسندگان",
            "title_or_headings": "🔖 عنوان",
            "subtitles": "🔍 عنوان فرعی",
            "publisher": "🏢 ناشر",
        },
    },
    "fa2en": {
        "label": "فارسی ⟶ انگلیسی",
        "source": "Persian (Farsi)",
        "target": "English",
        "rtl": False,
        "source_rtl": True,
        "system": (
            "You are an elite academic translator specializing in psychology and philosophy books, "
            "working from Persian (Farsi) into English. "
            "Your translation must NOT sound like machine translation. "
            "Write fluent, natural academic English prose.\n"
            "CRITICAL RULES:\n"
            "- Do not translate word-for-word. Translate meaning-for-meaning with idiomatic "
            "academic English.\n"
            "- COMPLETENESS: translate EVERY sentence of the input — never omit, skip, summarize "
            "or truncate, even if the text repeats or looks unusual.\n"
            "- Preserve structure: paragraph breaks, headings, lists, captions, footnote markers "
            "and emphasis must survive in the same order.\n"
            "- Keep numbers, units, equations, variable names, code, URLs and citation markers "
            "(like [12]) unchanged; translate only the words around them.\n"
            "- Use ONE consistent English equivalent for each key term throughout the book.\n"
            "- Keep the JSON structure perfectly clean."
        ),
        "labels": {
            "authors": "✍️ Author(s)",
            "title_or_headings": "🔖 Title",
            "subtitles": "🔍 Subtitle",
            "publisher": "🏢 Publisher",
        },
    },
    "en2ar": {
        "label": "انگلیسی ⟶ عربی",
        "source": "English",
        "target": "Arabic",
        "rtl": True,
        "source_rtl": False,
        "system": (
            "You are an elite academic translator specializing in psychology and philosophy books, "
            "working from English into Arabic. "
            "Your translation must NOT sound like machine translation. "
            "Use fluent, dignified, formal Modern Standard Arabic (Fusha) academic prose.\n"
            "CRITICAL RULES:\n"
            "- Do not translate word-for-word. Translate meaning-for-meaning with appropriate "
            "Arabic academic idioms.\n"
            "- COMPLETENESS: translate EVERY sentence of the input — never omit, skip, summarize "
            "or truncate, even if the text repeats or looks unusual.\n"
            "- Preserve structure: paragraph breaks, headings, lists, captions, footnote markers "
            "and emphasis must survive in the same order.\n"
            "- Keep numbers, units, equations, variable names, code, URLs and citation markers "
            "(like [12]) unchanged; translate only the words around them.\n"
            "- Use ONE consistent Arabic equivalent for each key term throughout the book; when a "
            "BOOK STRUCTURE CONTEXT is provided, follow it as the house style.\n"
            "- Write exclusively in Modern Standard Arabic (الفصحى), in Arabic script. Do not leave "
            "Persian wording in the translation, do not use colloquial dialect, and do not mix "
            "Arabic with Persian. Preserve technical names and citations only when they should "
            "remain unchanged. Use standard Arabic punctuation where appropriate.\n"
            "- If the text looks like table cells or figure captions, keep the cell separation and "
            "caption labels intact.\n"
            "- Keep the JSON structure perfectly clean."
        ),
        "labels": {
            "authors": "✍️ المؤلف/المؤلفون",
            "title_or_headings": "🔖 العنوان",
            "subtitles": "🔍 العنوان الفرعي",
            "publisher": "🏢 الناشر",
        },
    },
    "ar2en": {
        "label": "عربی ⟶ انگلیسی",
        "source": "Arabic",
        "target": "English",
        "rtl": False,
        "source_rtl": True,
        "system": (
            "You are an elite academic translator specializing in psychology and philosophy books, "
            "working from Arabic into English. "
            "Your translation must NOT sound like machine translation. "
            "Write fluent, natural academic English prose.\n"
            "CRITICAL RULES:\n"
            "- Do not translate word-for-word. Translate meaning-for-meaning with idiomatic "
            "academic English.\n"
            "- COMPLETENESS: translate EVERY sentence of the input — never omit, skip, summarize "
            "or truncate, even if the text repeats or looks unusual.\n"
            "- Preserve structure: paragraph breaks, headings, lists, captions, footnote markers "
            "and emphasis must survive in the same order.\n"
            "- Keep numbers, units, equations, variable names, code, URLs and citation markers "
            "(like [12]) unchanged; translate only the words around them.\n"
            "- Use ONE consistent English equivalent for each key term throughout the book.\n"
            "- Keep the JSON structure perfectly clean."
        ),
        "labels": {
            "authors": "✍️ Author(s)",
            "title_or_headings": "🔖 Title",
            "subtitles": "🔍 Subtitle",
            "publisher": "🏢 Publisher",
        },
    },
    "fa2ar": {
        "label": "فارسی ⟶ عربی",
        "source": "Persian (Farsi)",
        "target": "Arabic",
        "rtl": True,
        "source_rtl": True,
        "system": (
            "You are an elite academic translator specializing in psychology and philosophy books, "
            "working from Persian (Farsi) into Arabic. "
            "Your translation must NOT sound like machine translation. "
            "Use fluent, dignified, formal Modern Standard Arabic (Fusha) academic prose.\n"
            "CRITICAL RULES:\n"
            "- Do not translate word-for-word. Translate meaning-for-meaning with appropriate "
            "Arabic academic idioms.\n"
            "- COMPLETENESS: translate EVERY sentence of the input — never omit, skip, summarize "
            "or truncate, even if the text repeats or looks unusual.\n"
            "- Preserve structure: paragraph breaks, headings, lists, captions, footnote markers "
            "and emphasis must survive in the same order.\n"
            "- Keep numbers, units, equations, variable names, code, URLs and citation markers "
            "(like [12]) unchanged; translate only the words around them.\n"
            "- Use ONE consistent Arabic equivalent for each key term throughout the book; when a "
            "BOOK STRUCTURE CONTEXT is provided, follow it as the house style.\n"
            "- Write exclusively in Modern Standard Arabic (الفصحى), in Arabic script. Do not leave "
            "Persian wording in the translation, do not use colloquial dialect, and do not mix "
            "Arabic with Persian. Preserve technical names and citations only when they should "
            "remain unchanged. Use standard Arabic punctuation where appropriate.\n"
            "- Keep the JSON structure perfectly clean."
        ),
        "labels": {
            "authors": "✍️ المؤلف/المؤلفون",
            "title_or_headings": "🔖 العنوان",
            "subtitles": "🔍 العنوان الفرعي",
            "publisher": "🏢 الناشر",
        },
    },
    "ar2fa": {
        "label": "عربی ⟶ فارسی",
        "source": "Arabic",
        "target": "Persian (Farsi)",
        "rtl": True,
        "source_rtl": True,
        "system": (
            "You are an elite academic translator specializing in psychology and philosophy books, "
            "working from Arabic into Persian (Farsi). "
            "Your translation must NOT sound like machine translation. "
            "Use fluent, dignified, and formal Persian (Farsi) academic prose.\n"
            "CRITICAL RULES:\n"
            "- Do not translate word-for-word. Translate meaning-for-meaning with appropriate "
            "Persian academic idioms.\n"
            "- COMPLETENESS: translate EVERY sentence of the input — never omit, skip, summarize "
            "or truncate, even if the text repeats or looks unusual.\n"
            "- Preserve structure: paragraph breaks, headings, lists, captions, footnote markers "
            "and emphasis must survive in the same order.\n"
            "- Keep numbers, units, equations, variable names, code, URLs and citation markers "
            "(like [12]) unchanged; translate only the words around them.\n"
            "- Use ONE consistent Persian equivalent for each key term throughout the book; when a "
            "BOOK STRUCTURE CONTEXT is provided, follow it as the house style.\n"
            "- Keep the JSON structure perfectly clean."
        ),
        "labels": {
            "authors": "✍️ نویسنده/نویسندگان",
            "title_or_headings": "🔖 عنوان",
            "subtitles": "🔍 عنوان فرعی",
            "publisher": "🏢 ناشر",
        },
    },
}


def build_prompt(text, direction, context_tail=""):
    d = DIRECTIONS[direction]
    prompt = (
        f"Translate the following {d['source']} text into fluent academic {d['target']}.\n"
        "RULES:\n"
        "- Output the COMPLETE translation of the given text — never omit, summarize or add "
        "commentary; if part of it repeats, translate it as-is.\n"
        "- Keep paragraph boundaries and the order of the source exactly.\n"
        "- Do not translate numbers, units, equations, code, URLs or citation markers.\n"
        + JSON_SCHEMA_PART
    )
    if context_tail:
        prompt += (
            "\nCONTEXT — your own earlier output, provided ONLY for style and terminology "
            "consistency. Do NOT repeat, translate or answer it:\n"
            f"\"\"\"{context_tail}\"\"\"\n"
            "Continue seamlessly from where that context ends.\n"
        )
    prompt += f"Text to translate:\n{text}"
    return prompt


def build_image_prompt(direction):
    d = DIRECTIONS[direction]
    return (
        f"This is a scanned image of a book page. Read the {d['source']} text from this image "
        f"and translate it into fluent academic {d['target']}.\n"
        "Transcribe and translate EVERY visible sentence completely — headings, captions and "
        "footnotes included; never summarize or skip. Keep numbers and citation markers "
        "unchanged.\n" + JSON_SCHEMA_PART
    )


QC_SYSTEM = (
    "You are a meticulous bilingual translation reviewer. You compare a source passage with "
    "its translation and return ONLY a valid JSON object, never prose."
)


def build_qc_prompt(source, translation, direction):
    d = DIRECTIONS[direction]
    return (
        f"SOURCE TEXT ({d['source']}):\n\"\"\"{source}\"\"\"\n\n"
        f"TRANSLATION ({d['target']}):\n\"\"\"{translation}\"\"\"\n\n"
        "Check carefully:\n"
        "1. Completeness — every sentence and caption must be present, nothing skipped.\n"
        "2. Terminology consistency across the passage.\n"
        "3. Natural, fluent academic output (no machine-translation smell).\n"
        "4. Valid, well-formed output.\n"
        "5. Meaning fidelity — flag any sentence whose meaning drifted from the SOURCE, and fix "
        "it in the corrected translation.\n"
        "Return ONLY JSON: {\"ok\": true} if the translation is already high quality, otherwise "
        "{\"ok\": false, \"issues\": [\"...\"], \"corrected_translation\": \"<full corrected "
        "translation>\"}"
    )


# --------------------------------------------------------------------------
# تکه‌تکه‌سازی خودکار
# --------------------------------------------------------------------------

def _pack_units(units, max_chars, sep="\n\n"):
    chunks, current = [], ""
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        if current and len(current) + len(sep) + len(unit) > max_chars:
            chunks.append(current)
            current = unit
        else:
            current = unit if not current else current + sep + unit
    if current:
        chunks.append(current)
    return chunks


def _split_long_unit(unit, max_chars):
    sentences = re.split(r"(?<=[.!?؟…:])\s+", unit)
    out, buf = [], ""
    for sent in sentences:
        if len(sent) > max_chars:
            if buf:
                out.append(buf)
                buf = ""
            words, wbuf = sent.split(), ""
            for w in words:
                if wbuf and len(wbuf) + 1 + len(w) > max_chars:
                    out.append(wbuf)
                    wbuf = w
                else:
                    wbuf = w if not wbuf else wbuf + " " + w
            if wbuf:
                out.append(wbuf)
        elif buf and len(buf) + 1 + len(sent) > max_chars:
            out.append(buf)
            buf = sent
        else:
            buf = sent if not buf else buf + " " + sent
    if buf:
        out.append(buf)
    return out


def split_into_chunks(text, max_chars):
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    units = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            units.extend(_split_long_unit(para, max_chars))
        else:
            units.append(para)
    return _pack_units(units, max_chars)


def rolling_context(translation, cfg):
    tail_len = int(cfg.get("context_tail_chars", CONFIG_DEFAULTS["context_tail_chars"]))
    if tail_len <= 0:
        return ""
    if len(translation) <= tail_len:
        return translation
    tail = translation[-tail_len:]
    cut = tail.find(" ")
    if 0 < cut < 80:
        tail = tail[cut:]
    return tail


# --------------------------------------------------------------------------
# خروجی مدل
# --------------------------------------------------------------------------

def parse_json_response(raw, _depth=0):
    """پاسخ مدل را به dict تبدیل می‌کند؛ در صورت شکست None برمی‌گرداند.

    هرگز متن خام را به‌عنوان dict برنمی‌گرداند — مدیریت پاسخِ بدون JSON
    بر عهدهٔ response_to_output است تا JSON خام هرگز به کاربر نمایش داده نشود.
    """
    raw = (raw or "").strip()
    if not raw or _depth > 2:
        return None

    # پاسخ رشته‌ای دوباره‌کدشده (بعضی سرورها content را string می‌فرستند)
    if raw.startswith('"') and _depth < 2:
        try:
            inner = json.loads(raw)
            if isinstance(inner, str) and inner.strip():
                return parse_json_response(inner, _depth + 1)
        except ValueError:
            pass

    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    candidates = [cleaned]
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    # اصلاح خطای متداول مدل‌ها: کامای انتهایی آیتم‌ها
    for cand in candidates:
        try:
            obj = json.loads(re.sub(r",\s*([}\]])", r"\1", cand))
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    return None


def _json_unescape(s):
    def repl(m):
        esc = m.group(1)
        if esc.startswith("u") and len(esc) == 5:
            try:
                return chr(int(esc[1:], 16))
            except ValueError:
                return esc
        return {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(esc, esc)

    return re.sub(r"\\(u[0-9a-fA-F]{4}|.)", repl, s, flags=re.DOTALL)


def extract_body_text(raw):
    """متن body_text را حتی از JSONِ نامعتبر (مثل newline خام داخل رشته) بیرون می‌کشد."""
    if not raw:
        return None
    match = re.search(r'"body_text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if match:
        text = _json_unescape(match.group(1)).strip()
        return text or None
    return None


def response_to_output(raw, direction):
    """تبدیل خروجی خامِ مدل به متن ترجمهٔ تمیز — هرگز JSON خام نمایش داده نمی‌شود.

    ترتیب: JSON معتبر → استخراج body_text از JSON خراب → پاسخ سادهٔ بدون JSON
    (رایج در مدل‌های کاستوم/لوکال) → خطای صریح فارسی.
    """
    raw = (raw or "").strip()
    data = parse_json_response(raw)
    if isinstance(data, dict):
        out = assemble_output(data, direction)
        if out.strip():
            return out

    body = extract_body_text(raw)
    if body:
        return body

    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if cleaned and not cleaned.lstrip().startswith("{") and not cleaned.lstrip().startswith('"'):
        # مدلِ بدون JSON پاسخ داده — همان متن، ترجمه است
        return cleaned

    raise TranslationError(msg("parse_error"))


def _as_text(value):
    """مقدار فیلد مدل را امن به متن تبدیل می‌کند — مدل‌های کوچک گاهی به‌جای
    رشته، آرایه یا عدد برمی‌گردانند و .strip() روی آن‌ها کرش می‌کرد و کل
    اجرای کتاب را متوقف می‌کرد."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(t for t in (_as_text(v) for v in value) if t)
    return str(value)


def assemble_output(data, direction):
    d = DIRECTIONS[direction]
    labels = d["labels"]
    out = []
    for key in ("authors", "title_or_headings", "subtitles", "publisher"):
        value = _as_text(data.get(key)).strip()
        if value:
            out.append(f"{labels[key]}: {value}")
    body = _as_text(data.get("body_text")).strip()
    if body:
        out.append("\n" + body)
    return "\n".join(out).strip()


def response_text(response):
    try:
        text = response.text
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:
        pass
    return None


def finish_reason_name(response):
    try:
        finish = response.candidates[0].finish_reason
        return getattr(finish, "name", None) or str(finish)
    except Exception:
        return None


# --------------------------------------------------------------------------
# تحلیل ساختار کتاب (محلی و رایگان — پایهٔ Template اختصاصی هر کتاب)
# --------------------------------------------------------------------------

def analyze_structure(doc, sample_pages=15):
    """نمونه‌برداری از صفحات: اندازهٔ فونت بدنه، سرفصل‌ها و برچسب‌های تکرارشونده."""
    total = len(doc)
    if total == 0:
        return None

    indices = list(range(min(8, total)))
    if total > 8:
        step = max(1, (total - 8) // max(1, sample_pages - 8))
        indices.extend(range(8, total, step)[: max(1, sample_pages - 8)])
    indices = sorted(set(i for i in indices if 0 <= i < total))

    size_counter = Counter()
    headings, seen_headings = [], set()
    label_counter = Counter()

    for i in indices:
        try:
            page_dict = doc.load_page(i).get_text("dict")
        except Exception:
            continue
        for block in page_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(sp.get("text", "") for sp in spans).strip()
                if not text:
                    continue
                size = max(sp.get("size", 0.0) for sp in spans)
                size_counter[round(size, 1)] += 1

                is_bold = any(sp.get("flags", 0) & 16 for sp in spans)
                short = len(text) <= 90
                no_period = not text.endswith((".", ",", ";", ":"))
                looks_heading = short and no_period and (
                    size >= 1.0 and len(text) < 60 and (
                        is_bold or re.match(
                            r"^(chapter|part|section|appendix|book|\d+(\.\d+)*\s+\S)",
                            text, re.IGNORECASE,
                        )
                    )
                )
                if looks_heading:
                    # بریدن شمارهٔ صفحهٔ احتمالی از انتهای سرفصل — مقایسهٔ
                    # تکراری‌نبودن باید روی همان متن پاک‌شده باشد، نه متن خام
                    clean = re.sub(r"\s+\d{1,3}$", "", text).strip()
                    if len(clean) >= 3 and clean not in seen_headings:
                        seen_headings.add(clean)
                        headings.append(clean)

                if 3 <= len(text) <= 45 and no_period:
                    label_counter[text] += 1

    if not size_counter:
        return None

    body_size = size_counter.most_common(1)[0][0]
    labels = [text for text, count in label_counter.most_common(12) if count >= 2]

    return {
        "body_size": body_size,
        "headings": headings[:20],
        "labels": labels[:12],
        "sampled_pages": len(indices),
    }


def structure_prompt_block(structure):
    """بخشی از system instruction که Template اختصاصی همان کتاب را می‌سازد."""
    if not structure:
        return ""
    parts = [
        "BOOK STRUCTURE CONTEXT (extracted automatically from THIS book — use it to keep the "
        "translation book-specific and consistent):"
    ]
    if structure.get("headings"):
        parts.append(
            "- Recurring headings/chapters detected: "
            + "; ".join(structure["headings"][:20])
        )
    if structure.get("labels"):
        parts.append(
            "- Recurring section labels detected (translate each one ALWAYS the same way): "
            + "; ".join(structure["labels"][:12])
        )
    if structure.get("ai_summary"):
        parts.append(f"- Book structure summary: {structure['ai_summary']}")
    parts.append(
        "- When these strings appear in the source, render them with ONE consistent "
        "translation every time."
    )
    return "\n".join(parts)


def ai_structure_pass(engine, sample_text, local=None, max_chars=12000):
    """پاس عمیقِ AI برای شناسایی ساختار (۱ درخواست) — با ساختار محلی ادغام می‌شود.

    خروجی: dict ساختار با آیتم‌های محلی + موارد جدید AI، یا None اگر چیزی برنگشت.
    """
    sample = (sample_text or "").strip()
    if not sample:
        return local
    prompt = (
        "You are analyzing a book to build a translation style guide for this specific book.\n"
        "From the table of contents / sample pages below, extract:\n"
        "1) headings: chapter and section titles (as written in the source)\n"
        "2) labels: recurring short section labels (like \"Activities\", \"Did you know\", "
        "\"Key terms\") that appear multiple times\n"
        "Return ONLY a JSON object:\n"
        '{"headings": ["..."], "labels": ["..."], "summary": "one short line describing '
        'this book\'s structure"}\n\n'
        f"TEXT:\n{sample[:max_chars]}"
    )
    try:
        raw = engine.generate(prompt, system="You return only valid JSON, nothing else.")
    except TranslationError:
        return None
    data = parse_json_response(raw)
    if not isinstance(data, dict):
        return None

    def as_list(value):
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]

    new_headings = as_list(data.get("headings"))[:30]
    new_labels = as_list(data.get("labels"))[:20]
    if not new_headings and not new_labels:
        return None

    merged = dict(local or {})
    old_h = [str(h) for h in merged.get("headings", [])]
    old_l = [str(x) for x in merged.get("labels", [])]
    merged["headings"] = old_h + [h for h in new_headings if h not in old_h]
    merged["labels"] = old_l + [x for x in new_labels if x not in old_l]
    summary = data.get("summary")
    if isinstance(summary, str) and summary.strip():
        merged["ai_summary"] = summary.strip()
    merged["ai"] = True
    if "sampled_pages" not in merged:
        merged["sampled_pages"] = 0
    return merged


def ensure_indicator_assets():
    """ساخت آیکون‌های تیک ☑، رادیوی انتخاب‌شده و فلش‌های اسپینر (PNG شفاف)."""
    assets = os.path.join(config_dir(), "assets")
    try:
        os.makedirs(assets, exist_ok=True)
    except OSError:
        return None, None, None, None

    from PIL import Image, ImageDraw

    check_path = os.path.join(assets, "check.png")
    radio_path = os.path.join(assets, "radio.png")
    up_path = os.path.join(assets, "up.png")
    down_path = os.path.join(assets, "down.png")

    if not os.path.exists(check_path):
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([2, 2, 29, 29], radius=7, fill=(37, 99, 235, 255))
        draw.line([(9, 17), (14, 23), (24, 9)],
                  fill=(255, 255, 255, 255), width=5, joint="curve")
        img.save(check_path)

    if not os.path.exists(radio_path):
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 29, 29], fill=(37, 99, 235, 255))
        draw.ellipse([9, 9, 22, 22], fill=(255, 255, 255, 255))
        draw.ellipse([13, 13, 18, 18], fill=(37, 99, 235, 255))
        img.save(radio_path)

    if not os.path.exists(up_path):
        img = Image.new("RGBA", (16, 14), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.polygon([(8, 3), (3, 11), (13, 11)], fill=(248, 250, 252, 255))
        img.save(up_path)

    if not os.path.exists(down_path):
        img = Image.new("RGBA", (16, 14), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.polygon([(8, 11), (3, 3), (13, 3)], fill=(248, 250, 252, 255))
        img.save(down_path)

    return tuple(
        p.replace("\\", "/")
        for p in (check_path, radio_path, up_path, down_path)
    )


# --------------------------------------------------------------------------
# موتورهای ترجمه
# --------------------------------------------------------------------------

class BaseEngine:
    provider = "?"

    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        raise NotImplementedError

    def test(self):
        try:
            out = self.generate(
                "Reply with the single word: OK",
                system="You answer with one word.",
                json_mode=False,
            )
            ok_text = (out or "").strip()[:60] or ("(خالی)" if get_language() == "fa" else "(empty)")
            return True, msg("test_ok", reply=ok_text)
        except TranslationError as exc:
            return False, msg("test_fail", detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            return False, msg("test_fail", detail=str(exc))


class GeminiEngine(BaseEngine):
    provider = "gemini"

    def __init__(self, api_key, model, temperature=0.1, base_url="", proxy_url=""):
        try:
            from google import genai  # ایمپورت تنبل برای حالت بدون gemini
        except ModuleNotFoundError as exc:
            if exc.name == "pydantic":
                raise TranslationError(msg("missing_pydantic")) from exc
            raise

        from google.genai import types

        http_options = {"timeout": 90_000}
        if (base_url or "").strip():
            # Allows a user-configured Gemini-native API gateway/proxy. The
            # official Google endpoint remains the default when left blank.
            http_options["base_url"] = base_url.strip().rstrip("/")
        if (proxy_url or "").strip():
            proxy = proxy_url.strip()
            http_options["client_args"] = {"proxy": proxy}
            http_options["async_client_args"] = {"proxy": proxy}
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(**http_options),
        )
        self.model = model or "gemini-3.8-flash"
        self.temperature = float(temperature)
        self.last_used_model = self.model

    def _generation_config(self, system, json_mode):
        from google.genai import types

        cfg_kwargs = {}
        # Gemini 3.6+ ignores or may reject custom sampling parameters; Google
        # recommends leaving temperature at the model default.
        if not self.model.startswith(("gemini-3", "gemini-4")):
            cfg_kwargs["temperature"] = self.temperature
        if system:
            cfg_kwargs["system_instruction"] = system
        if json_mode:
            cfg_kwargs["response_mime_type"] = "application/json"
        return types.GenerateContentConfig(**cfg_kwargs)

    def _call(self, contents, system, json_mode):
        from google.genai.errors import APIError
        config = self._generation_config(system, json_mode)
        models = [self.model]
        # Google may temporarily return 503 for a hot model. Only when using
        # the shipped default, fall back to another stable structured-output
        # model; custom model choices remain under the user's control.
        if self.model == "gemini-3.8-flash":
            models.append("gemini-3.6-flash")
        last_err = None
        for model_index, model in enumerate(models):
            delay = 2
            try_next_model = False
            for attempt in range(4):
                try:
                    response = self.client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    self.last_used_model = model
                    return response
                except APIError as err:
                    last_err = err
                    detail = str(err)
                    folded = detail.casefold()
                    code = str(err.code)
                    if any(marker in folded for marker in (
                        "user location is not supported", "location is not supported",
                        "not available in your country", "unsupported location",
                        "region is not supported", "geographic location",
                    )):
                        raise TranslationError(msg("gemini_location")) from err
                    if code in ("401", "403") and any(marker in folded for marker in (
                        "api key", "permission_denied", "permission denied", "unauthorized",
                    )):
                        raise TranslationError(msg("gemini_key_error")) from err
                    if code in ("400", "404") and any(marker in folded for marker in (
                        "model", "not found", "not supported for generatecontent",
                    )):
                        raise TranslationError(msg("gemini_model_error", model=model)) from err
                    if err.code in (429, 500, 502, 503, 504) and attempt < 3:
                        time.sleep(delay)
                        delay *= 2
                        continue
                    if err.code == 429:
                        if model_index + 1 < len(models):
                            try_next_model = True
                            break
                        raise QuotaExhaustedError(msg("gemini_quota")) from err
                    if err.code in (500, 502, 503, 504):
                        if model_index + 1 < len(models):
                            try_next_model = True
                            break
                        raise TranslationError(
                            msg("gemini_network_error", detail=f"Gemini API returned HTTP {code}: {err}")
                        ) from err
                    if code in ("400", "401", "403", "404"):
                        raise TranslationError(msg("gemini_http_error", code=code, detail=detail)) from err
                    raise TranslationError(
                        msg("gemini_api_error", code=err.code, detail=err)
                    ) from err
                except Exception as err:  # noqa: BLE001
                    last_err = err
                    if attempt < 3:
                        time.sleep(delay)
                        delay *= 2
                        continue
                    if model_index + 1 < len(models):
                        try_next_model = True
                        break
                    raise TranslationError(
                        msg("gemini_network_error", detail=err)
                    ) from err
            if try_next_model:
                continue
        raise TranslationError(msg("gemini_error", detail=last_err))

    def test(self):
        ok, message = super().test()
        if ok and self.last_used_model != self.model:
            message += "\n" + msg("gemini_fallback", model=self.last_used_model)
        return ok, message

    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        if image_png:
            from google.genai import types

            contents = [
                types.Part.from_bytes(data=image_png, mime_type="image/png"),
                prompt,
            ]
        else:
            contents = prompt

        response = self._call(contents, system, json_mode)
        raw = response_text(response)

        if not raw and finish_reason_name(response) == "RECITATION":
            # گارد کپی‌رایت جمینای: یک بار با دستور بازنویسی تلاش مجدد
            retry_prompt = (
                prompt
                + "\nNOTE: If a direct translation is blocked, paraphrase the passage in your "
                "own words while preserving the meaning."
            )
            response = self._call(retry_prompt, system, json_mode)
            raw = response_text(response)
            if not raw:
                raise TranslationError(msg("gemini_recitation"))
        finish = (finish_reason_name(response) or "").upper()
        if "MAX_TOKENS" in finish:
            raise TranslationError(msg("truncated_error"))
        if not raw and any(reason in finish for reason in (
            "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"
        )):
            raise TranslationError(msg("gemini_blocked", reason=finish))
        if not raw:
            raise TranslationError(msg("gemini_no_response"))
        return raw


class OpenAICompatEngine(BaseEngine):
    """اتصال به هر سرور سازگار با OpenAI: Ollama، LM Studio، vLLM، …"""

    provider = "openai"

    def __init__(self, base_url, api_key, model, temperature=0.1):
        self.base_url = (base_url or "http://localhost:11434/v1").rstrip("/")
        self.api_key = api_key or "not-needed"
        self.model = model or ""
        self.temperature = float(temperature)

    @staticmethod
    def _has_chat_capability(item):
        """Recognize explicit optional chat metadata, never infer it from an ID."""
        capabilities = item.get("capabilities")
        if isinstance(capabilities, dict):
            if capabilities.get("chat") is False:
                return False
            if capabilities.get("chat") is True:
                return True
        elif isinstance(capabilities, list) and "chat" in capabilities:
            return True
        endpoints = item.get("supported_endpoints")
        return isinstance(endpoints, list) and any(
            endpoint in ("/v1/chat/completions", "/chat/completions")
            for endpoint in endpoints
        )

    def _discover_model(self):
        """Select the first explicitly chat-capable model, or require manual entry."""
        if self.model:
            return self.model
        url = f"{self.base_url}/models"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.api_key}"}, method="GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise TranslationError(
                f"{msg('model_not_set')}\n{msg('model_empty')}\n"
                f"{msg('model_list_failed', url=url, detail=exc)}"
            ) from exc
        items = payload.get("data", []) if isinstance(payload, dict) else []
        if not items and isinstance(payload, dict):
            items = payload.get("models", [])
        if not isinstance(items, list):
            items = []
        has_model_id = False
        for item in items:
            if isinstance(item, str):
                has_model_id = has_model_id or bool(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            candidate = item.get("id") or item.get("name")
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            has_model_id = True
            if self._has_chat_capability(item):
                self.model = candidate.strip()
                return self.model
        if has_model_id:
            raise TranslationError(msg("model_chat_not_identified"))
        raise TranslationError(
            f"{msg('model_not_set')}\n{msg('model_none_returned', url=url)}"
        )

    def _post(self, payload, timeout=600):
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        delay = 2
        last_error = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                if exc.code == 429 and attempt == 3:
                    raise QuotaExhaustedError(
                        msg("server_quota", detail=body)
                    ) from exc
                if exc.code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    last_error = exc
                    continue
                raise TranslationError(
                    msg("server_http_error", code=exc.code, detail=body)
                ) from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TranslationError(
                    msg("server_connect_failed", url=self.base_url, detail=exc.reason)
                ) from exc
            except TimeoutError as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TranslationError(msg("server_timeout")) from exc
        raise TranslationError(msg("server_error", detail=last_error))

    @staticmethod
    def _extract_content(resp):
        try:
            content = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):  # بعضی سرورها آرایه‌ای برمی‌گردانند
            texts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in (None, "text")
            ]
            joined = "\n".join(t for t in texts if t).strip()
            return joined or None
        return None

    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        self._discover_model()

        if image_png:
            content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,"
                        + base64.b64encode(image_png).decode("ascii")
                    },
                },
            ]
        else:
            content = prompt

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if json_mode:
            # درخواست JSONِ ساختاریافته؛ بعضی سرورها پشتیبانی نمی‌کنند → تلاش مجدد بدون آن
            payload["response_format"] = {"type": "json_object"}
            try:
                resp = self._post(payload)
            except TranslationError as exc:
                err_text = str(exc)
                if "response_format" in err_text or "HTTP 400" in err_text or "HTTP 422" in err_text:
                    payload.pop("response_format", None)
                    resp = self._post(payload)
                else:
                    raise
        else:
            resp = self._post(payload)
        # پاسخ نصفه (پر شدن کانتکست) را همین‌جا تشخیص بده؛ وگرنه پایین‌دست
        # به‌صورت خطای گنگ «JSON نامعتبر» دیده می‌شود و کاربر علت را نمی‌فهمد.
        try:
            finish = resp["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError):
            finish = None
        if finish in ("length", "max_tokens"):
            raise TranslationError(msg("truncated_error"))
        text = self._extract_content(resp)
        if not text:
            raise TranslationError(msg("empty_response"))
        return text

    def test(self):
        ok, message = super().test()
        if not ok:
            return ok, message
        # تست واقعی‌تر: خروجی ساخت‌یافته (JSON) — همان چیزی که ترجمهٔ کتاب
        # لازم دارد؛ تست تک‌کلمه‌ای با کانتکست کوچک هم پاس می‌شود و کافی نیست.
        try:
            raw = self.generate(
                'Return ONLY this JSON object: {"body_text": "OK"}',
                system="You answer with JSON only.",
                json_mode=True,
            )
            if not isinstance(parse_json_response(raw), dict):
                return False, msg("test_json_fail")
        except TranslationError as exc:
            return False, msg("test_fail", detail=str(exc))
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            message += msg("test_local_hint")
        return True, message


def make_engine(cfg):
    provider = cfg.get("provider", "gemini")
    if provider == "openai":
        return OpenAICompatEngine(
            cfg.get("base_url", ""),
            cfg.get("api_key", ""),
            cfg.get("model", ""),
            cfg.get("temperature", 0.1),
        )
    key = (cfg.get("api_key") or "").strip()
    if not key:
        raise TranslationError(msg("gemini_key_missing"))
    gemini_endpoint = (cfg.get("base_url") or "").strip()
    if gemini_endpoint.rstrip("/") == "http://localhost:11434/v1":
        gemini_endpoint = ""
    return GeminiEngine(
        key,
        cfg.get("model", "gemini-3.8-flash"),
        cfg.get("temperature", 0.1),
        base_url=gemini_endpoint,
        proxy_url=cfg.get("gemini_proxy", ""),
    )


# --------------------------------------------------------------------------
# دقت خواندن صفحه: حذف هدر/پاصفحهٔ تکرارشونده + تصحیح خط‌تجزیه
# --------------------------------------------------------------------------

_TEXT_FLAGS = None
_BOILER_CACHE = {}


def _page_text_flags():
    """پرچم‌های استخراج متن: تصحیح کلمات شکسته‌شده با خط تیرهٔ انتها سطر."""
    global _TEXT_FLAGS
    if _TEXT_FLAGS is None:
        flags = getattr(pymupdf, "TEXTFLAGS_TEXT", 0)
        flags |= getattr(pymupdf, "TEXT_DEHYPHENATE", 0)
        _TEXT_FLAGS = int(flags)
    return _TEXT_FLAGS


def _norm_line(line):
    return " ".join(line.split()).casefold()


def _is_number_only(norm):
    stripped = re.sub(r"[\d\u06f0-\u06f9\u0660-\u0669]+", "", norm)
    return not stripped.strip(" .:-|/»«()")


def detect_repeated_lines(doc, sample=40, edge=2, min_ratio=0.25, min_hits=3):
    """خطوط هدر/پاصفحهٔ تکرارشونده (نام کتاب، شمارهٔ صفحه) را شناسایی می‌کند.

    روی نمونه‌ای از صفحات، ۲ خط اول و ۲ خط آخر جمع می‌شود؛ خطی که در
    ≥۲۵٪ صفحات تکرار شود هدر/پاصفحه است و هنگام ترجمه حذف می‌شود
    (نتیجه برای هر فایل کش می‌شود).
    """
    if doc is None:
        return set()
    try:
        page_count = int(doc.page_count)
    except Exception:
        return set()
    if page_count <= 0:
        return set()

    key = (getattr(doc, "name", "") or "", page_count, id(doc))
    cached = _BOILER_CACHE.get(key)
    if cached is not None:
        return cached

    if page_count <= sample:
        indexes = list(range(page_count))
    else:
        step = page_count / float(sample)
        indexes = sorted({min(page_count - 1, int(i * step)) for i in range(sample)})

    counts = {}
    seen_pages = 0
    for i in indexes:
        try:
            text = doc.load_page(int(i)).get_text("text", flags=_page_text_flags())
        except Exception:
            continue
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        seen_pages += 1
        page_seen = set()
        for ln in lines[:edge] + lines[-edge:]:
            norm = _norm_line(ln)
            if not norm or len(norm) > 120:
                continue
            if _is_number_only(norm):
                norm = "<number>"
            if norm in page_seen:
                continue
            page_seen.add(norm)
            counts[norm] = counts.get(norm, 0) + 1

    if not seen_pages:
        return set()
    threshold = max(min_hits, int(seen_pages * min_ratio))
    boiler = {k for k, v in counts.items() if v >= threshold}

    if len(_BOILER_CACHE) > 16:
        _BOILER_CACHE.clear()
    _BOILER_CACHE[key] = boiler
    return boiler


def clean_page_text(text, boiler=None):
    """خطوط هدر/پاصفحهٔ شناسایی‌شده را از متن حذف می‌کند.

    خطوطِ فقط-عددی فقط در لبهٔ بالا/پایین حذف می‌شوند تا شماره‌گذاری
    لیست یا اعداد وسط متن (فرمول و غیره) دست نخورد.
    """
    if not text or not boiler:
        return text
    lines = text.splitlines()
    nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
    edge_positions = set(nonempty[:2] + nonempty[-2:])
    kept = []
    for i, ln in enumerate(lines):
        norm = _norm_line(ln)
        if not norm:
            kept.append(ln)
            continue
        if _is_number_only(norm):
            if i not in edge_positions:
                kept.append(ln)
                continue
            norm = "<number>"
        if norm in boiler:
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


def extract_page_text(page_obj):
    """متن صفحه با دقت بالا: تصحیح خط‌تجزیه + حذف هدر/پاصفحهٔ تکرارشونده."""
    try:
        text = page_obj.get_text("text", flags=_page_text_flags())
    except TypeError:
        text = page_obj.get_text("text")
    parent = getattr(page_obj, "parent", None)
    if parent is not None:
        text = clean_page_text(text, detect_repeated_lines(parent))
    return text


# --------------------------------------------------------------------------
# لولهٔ ترجمهٔ یک صفحه (مشترک بین تک‌صفحه و کل کتاب)
# --------------------------------------------------------------------------

def _page_has_embedded_images(page_obj):
    """Detect images in PDFs and EPUB XHTML pages rendered as image blocks."""
    try:
        if page_obj.get_images(full=True):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        blocks = page_obj.get_text("dict").get("blocks", [])
        return any(
            block.get("type") == 1 and block.get("image")
            for block in blocks if isinstance(block, dict)
        )
    except Exception:  # noqa: BLE001
        return False


def translate_page(engine, page_obj, cfg, direction, context_tail="",
                   structure_block=None, on_progress=None, on_partial=None,
                   should_continue=None):
    """
    ترجمهٔ یک صفحه: تکه‌تکه‌سازی خودکار + کانتکست هوشمند.
    برمی‌گرداند: (متن ترجمه، دنبالهٔ کانتکست جدید، متن مبدأ یا None)
    """
    d = DIRECTIONS[direction]
    system = d["system"]
    if structure_block:
        system = system + "\n\n" + structure_block

    source = extract_page_text(page_obj).strip()

    # صفحهٔ اسکن‌شده: یک درخواست تصویری
    if not source:
        # صفحه‌ای که فقط هدر/شماره داشته و بعد از پاک‌سازی خالی شده اسکن‌شده
        # نیست: درخواست تصویری نفرست (هزینه + خروجی توهمی روی صفحهٔ خالی)
        has_image = _page_has_embedded_images(page_obj)
        if not has_image:
            if on_progress:
                on_progress(1, 1)
            return "", context_tail, None
        if on_progress:
            on_progress(0, 1)
        pix = page_obj.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        raw = engine.generate(
            build_image_prompt(direction), system=system, image_png=pix.tobytes("png")
        )
        out = response_to_output(raw, direction)
        if on_progress:
            on_progress(1, 1)
        if on_partial:
            on_partial(out)
        # دم کانتکست مثل مسیر عادی محدود است، نه کل صفحه
        return out, rolling_context(out, cfg), None

    max_chars = int(cfg.get("chunk_max_chars", CONFIG_DEFAULTS["chunk_max_chars"]))
    chunks = split_into_chunks(source, max_chars)
    total = len(chunks)
    if on_progress:
        on_progress(0, total)

    results = []
    tail = context_tail
    delay = float(cfg.get("request_delay_sec", 0) or 0)
    for index, chunk in enumerate(chunks, start=1):
        if should_continue and not should_continue():
            raise CancelledError()
        if index > 1 and delay > 0:
            # «تاخیر بین درخواست‌ها» بین تکه‌های یک صفحه هم اعمال می‌شود،
            # نه فقط بین صفحه‌ها — وگرنه صفحهٔ چندتکه‌ای 429 می‌سازد
            waited = 0.0
            while waited < delay:
                if should_continue and not should_continue():
                    raise CancelledError()
                step = min(0.2, delay - waited)
                time.sleep(step)
                waited += step
        prompt = build_prompt(chunk, direction, tail)
        raw = engine.generate(prompt, system=system)
        out = response_to_output(raw, direction)
        results.append(out)
        tail = rolling_context(out, cfg)
        if on_progress:
            on_progress(index, total)
        if on_partial:
            on_partial(out)

    return "\n\n".join(results), tail, source


def review_translation(engine, source, translation, direction, cfg):
    """حلقهٔ بازبینی خودکار (QC): بررسی و در صورت نیاز اصلاح ترجمه."""
    prompt = build_qc_prompt(source, translation, direction)
    try:
        raw = engine.generate(prompt, system=QC_SYSTEM)
    except TranslationError:
        return translation  # شکست QC نباید ترجمهٔ موجود را از بین ببرد
    data = parse_json_response(raw)
    if not isinstance(data, dict):
        return translation
    if data.get("ok") is True:
        return translation
    corrected = data.get("corrected_translation")
    # اصلاحیه باید دست‌کم نصف ترجمه باشد؛ آستانهٔ شل‌تر یعنی QC می‌تواند
    # بی‌سروصدا تا دو سوم صفحه را حذف کند و صفحه «ترجمه‌شده» ثبت شود
    if isinstance(corrected, str) and len(corrected.strip()) >= max(40, len(translation) // 2):
        return corrected.strip()
    return translation


# --------------------------------------------------------------------------
# ذخیرهٔ وضعیت کار (Job): ترجمه‌های انجام‌شده + ساختار + بازبینی‌ها
# --------------------------------------------------------------------------

class JobStore:
    """وضعیت ترجمهٔ هر فایل، برای Resume و از دست نرفتن خروجی صفحات."""

    def __init__(self, source_path):
        self.source_path = os.path.abspath(source_path)
        digest = hashlib.sha1(self.source_path.encode("utf-8")).hexdigest()[:16]
        self.path = os.path.join(jobs_dir(), f"{digest}.json")
        self._fingerprint = self._file_fingerprint()
        self._lock = threading.Lock()
        self.direction = None
        self.data = {
            "source": self.source_path,
            "fingerprint": self._fingerprint,
            "translations": {},
            "reviewed": {},
            "translations_by_direction": {},
            "reviewed_by_direction": {},
            "context_by_direction": {},
            "legacy_translations": {},
            "structure": None,
            "context_tail": "",
            "updated": 0,
        }

    def _file_fingerprint(self):
        """اثر انگشت سبک فایل (حجم + زمان ویرایش) برای تشخیص تعویض فایل."""
        try:
            st = os.stat(self.source_path)
            return f"{st.st_size}:{int(st.st_mtime)}"
        except OSError:
            return None

    def reset_translations(self):
        """حذف همهٔ ترجمه‌های ذخیره‌شده (برای «شروع از اول») — ساختار کتاب حفظ می‌شود."""
        with self._lock:
            self.data["translations"] = {}
            self.data["reviewed"] = {}
            self.data["context_tail"] = ""
        self.save()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict) and stored.get("source") == self.source_path:
                stored_fp = stored.get("fingerprint")
                if stored_fp and self._fingerprint and stored_fp != self._fingerprint:
                    # فایل روی همان مسیر عوض شده (مثلاً ویرایش جدید کتاب):
                    # ترجمه‌های فایل قبلی نباید به این فایل بچسبند — فایل کار
                    # قبلی به‌صورت پشتیبان نگه داشته می‌شود و کار تازه شروع می‌شود
                    try:
                        os.replace(self.path, self.path + ".bak")
                    except OSError:
                        pass
                    return self
                if isinstance(stored.get("translations"), dict):
                    stored["translations"] = {
                        str(k): v for k, v in stored["translations"].items()
                        if isinstance(v, str)
                    }
                if isinstance(stored.get("reviewed"), dict):
                    stored["reviewed"] = {
                        str(k): True for k, v in stored["reviewed"].items() if v
                    }
                self.data.update(stored)
                self.direction = stored.get("direction")
                for key in (
                    "translations_by_direction", "reviewed_by_direction",
                    "context_by_direction",
                ):
                    if not isinstance(self.data.get(key), dict):
                        self.data[key] = {}
                self._repair_buried_legacy()
        except (OSError, ValueError):
            pass
        return self

    def _repair_buried_legacy(self):
        """بازگردانی ترجمه‌هایی که نسخهٔ جهت‌آگاهِ اول به «legacy» تبعید کرد.

        آن نسخه هنگام اولین باز کردنِ کارهای قدیمی (بدون فرادادهٔ جهت) همهٔ
        صفحات ترجمه‌شده را داخل legacy_translations بایگانی می‌کرد و کار را
        خالی نشان می‌داد — کاربر عملاً پیشرفت آماده‌اش را از دست‌رفته می‌دید.
        اگر آن صفحات تنها محتوای کارند (هیچ ترجمه‌ای برای هیچ جهتی وجود
        ندارد)، متعلق به همین کار و همان جهتِ ثبت‌شده‌اند: سر جایشان
        برمی‌گردند و نتیجه روی دیسک هم ذخیره می‌شود.
        """
        legacy = self.data.get("legacy_translations")
        if not isinstance(legacy, dict) or not legacy:
            return
        by_dir = self.data.get("translations_by_direction", {})
        has_any = bool(self.data.get("translations")) or any(
            isinstance(slot, dict) and slot for slot in by_dir.values()
        )
        if has_any:
            return
        restored = {
            str(k): v for k, v in legacy.items() if isinstance(v, str)
        }
        if not restored:
            return
        self.data["translations"] = restored
        if self.direction:
            by_dir[self.direction] = dict(restored)
        self.data["legacy_translations"] = {}
        try:
            self.save()
        except OSError:
            pass

    def switch_direction(self, direction):
        """Keep page results and rolling context isolated by target direction.

        Jobs created before direction metadata existed kept a single
        translations dict — exactly the set the user saw, reviewed and
        exported in those releases. On the first direction-aware open those
        pages are ADOPTED under the direction the job is opened with (the
        semantics every previous release had), never hidden in an
        unreachable archive: burying them made finished books reopen at
        zero progress, like a brand-new app.
        """
        direction = str(direction or "")
        if not direction or direction == self.direction:
            return False
        translations_by = self.data.setdefault("translations_by_direction", {})
        reviewed_by = self.data.setdefault("reviewed_by_direction", {})
        context_by = self.data.setdefault("context_by_direction", {})

        if self.direction:
            translations_by[self.direction] = dict(self.data.get("translations", {}))
            reviewed_by[self.direction] = dict(self.data.get("reviewed", {}))
            context_by[self.direction] = self.data.get("context_tail", "") or ""
        elif self.data.get("translations"):
            # Legacy single-dict job: adopt its pages under the direction it
            # is opened with, so the user's finished work stays visible.
            translations_by[direction] = dict(self.data.get("translations", {}))
            reviewed_by[direction] = dict(self.data.get("reviewed", {}))
            context_by[direction] = self.data.get("context_tail", "") or ""

        self.direction = direction
        self.data["direction"] = direction
        self.data["translations"] = dict(translations_by.get(direction, {}))
        self.data["reviewed"] = dict(reviewed_by.get(direction, {}))
        self.data["context_tail"] = context_by.get(direction, "") or ""
        self.save()
        return True

    def save(self):
        with self._lock:
            if self.direction:
                self.data["direction"] = self.direction
                self.data.setdefault("translations_by_direction", {})[
                    self.direction
                ] = dict(self.data.get("translations", {}))
                self.data.setdefault("reviewed_by_direction", {})[
                    self.direction
                ] = dict(self.data.get("reviewed", {}))
                self.data.setdefault("context_by_direction", {})[
                    self.direction
                ] = self.data.get("context_tail", "") or ""
            self.data["updated"] = int(time.time())
            if self._fingerprint:
                self.data["fingerprint"] = self._fingerprint
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False)
            os.replace(tmp, self.path)

    # --- دسترسی‌ها ---
    @property
    def translations(self):
        return self.data["translations"]

    @property
    def reviewed(self):
        return self.data["reviewed"]

    @property
    def structure(self):
        return self.data.get("structure")

    @structure.setter
    def structure(self, value):
        self.data["structure"] = value

    @property
    def context_tail(self):
        return self.data.get("context_tail", "")

    @context_tail.setter
    def context_tail(self, value):
        self.data["context_tail"] = value or ""

    def get(self, page):
        return self.data["translations"].get(str(page))

    def set(self, page, text):
        self.data["translations"][str(page)] = text

    def is_reviewed(self, page):
        return bool(self.data["reviewed"].get(str(page)))

    def set_reviewed(self, page, flag):
        if flag:
            self.data["reviewed"][str(page)] = True
        else:
            self.data["reviewed"].pop(str(page), None)

    def count(self):
        return len(self.data["translations"])

    def reviewed_count(self):
        return len(self.data["reviewed"])

    def ordered_pages(self):
        return sorted(int(k) for k in self.data["translations"])

    def missing_pages(self, start, end):
        return [p for p in range(start, end + 1) if str(p) not in self.data["translations"]]


# --------------------------------------------------------------------------
# خروجی کتاب
# --------------------------------------------------------------------------

# برچسب‌های خروجی (عنوان و شمارهٔ صفحه) به زبان مقصد ترجمه نوشته می‌شوند،
# نه به زبان رابط کاربری: کتابی که مقصدش انگلیسی است، سرفصل انگلیسی می‌گیرد.
_EXPORT_LABELS = {
    "fa": {"doc_title": "ترجمهٔ {name}", "page": "صفحهٔ {n}", "page_rule": "— صفحهٔ {n} —"},
    "en": {"doc_title": "Translation of {name}", "page": "Page {n}", "page_rule": "— Page {n} —"},
    "ar": {"doc_title": "ترجمة {name}", "page": "صفحة {n}", "page_rule": "— صفحة {n} —"},
}


def _export_labels(direction):
    lang = direction.split("2")[-1] if direction and "2" in direction else "fa"
    return _EXPORT_LABELS.get(lang, _EXPORT_LABELS["fa"])


def export_page_text(text, source_name, page, path, direction="en2fa"):
    labels = _export_labels(direction)
    header = (
        f"{labels['doc_title'].format(name=source_name)}"
        f" — {labels['page'].format(n=page + 1)}\n" + "=" * 40 + "\n\n"
    )
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(header + text + "\n")


def export_markdown(job, source_name, path, direction="en2fa"):
    labels = _export_labels(direction)
    lines = [f"# {labels['doc_title'].format(name=source_name)}", ""]
    for page in job.ordered_pages():
        lines.append(f"## {labels['page'].format(n=page + 1)}")
        lines.append("")
        lines.append(job.get(page) or "")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _page_image_data_uri(doc, page):
    """تصویر صفحه به‌صورت data URI (JPEG فشرده) تا فایل HTML تک‌فایل و مستقل بماند.

    قبلاً تصاویر در پوشهٔ images/ جدا ذخیره می‌شدند و با جابه‌جایی index.html
    همهٔ تصاویر می‌شکستند؛ حالا خود فایل HTML همه‌چیز را در بر دارد."""
    pix = doc.load_page(page).get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3))
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    try:
        raw = pix.tobytes("jpg", jpg_quality=78)
        mime = "image/jpeg"
    except Exception:
        raw = pix.tobytes("png")
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def export_html(job, doc, source_name, out_dir, direction="en2fa"):
    """کتاب کامل HTML با تصاویر توکار (قابل چاپ / ذخیره به‌صورت PDF).

    خروجی فقط یک فایل index.html است و تصاویر صفحات داخل خودش قرار می‌گیرند.
    جهت و زبان سند از زبان مقصد ترجمه پیروی می‌کند (مقصد انگلیسی → LTR)."""
    d = DIRECTIONS.get(direction, DIRECTIONS["en2fa"])
    dir_attr = "rtl" if d.get("rtl", True) else "ltr"
    lang = direction.split("2")[-1] if "2" in direction else "fa"
    labels = _export_labels(direction)
    os.makedirs(out_dir, exist_ok=True)

    sections = []
    for page in job.ordered_pages():
        text = job.get(page) or ""
        img_tag = ""
        try:
            uri = _page_image_data_uri(doc, page)
            alt = labels["page"].format(n=page + 1)
            img_tag = f'<img class="page-img" src="{uri}" alt="{alt}">'
        except Exception:
            img_tag = ""
        sections.append(
            f'<section id="page-{page + 1}">'
            f'<div class="page-num">{labels["page_rule"].format(n=page + 1)}</div>'
            f'<div class="translation">{html_mod.escape(text)}</div>'
            f"{img_tag}"
            f"</section>"
        )

    document = f"""<!DOCTYPE html>
<html dir="{dir_attr}" lang="{lang}">
<head>
<meta charset="utf-8">
<title>{html_mod.escape(labels['doc_title'].format(name=source_name))}</title>
<style>
  body {{ font-family: "Vazirmatn", "Tahoma", "Segoe UI", sans-serif; direction: {dir_attr};
         line-height: 1.9; max-width: 860px; margin: 0 auto; padding: 24px;
         color: #0f172a; background: #ffffff; }}
  h1 {{ font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 8px; }}
  section {{ margin: 28px 0; page-break-inside: avoid; }}
  .page-num {{ color: #2563eb; font-weight: bold; text-align: center; margin-bottom: 10px; }}
  .translation {{ white-space: pre-wrap; font-size: 15px; text-align: justify; }}
  .page-img {{ width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; margin-top: 16px; }}
  @media print {{ .page-img {{ max-height: 90vh; object-fit: contain; }} }}
</style>
</head>
<body>
<h1>{html_mod.escape(labels['doc_title'].format(name=source_name))}</h1>
{chr(10).join(sections)}
</body>
</html>
"""
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(document)
    return index_path
