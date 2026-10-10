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
from collections import Counter

import pymupdf  # PyMuPDF (نام جدید؛ fitz فقط نام قدیمی است و هشدار می‌دهد)

APP_NAME = "kaman-ai-translator"
APP_VERSION = "3.0.0"

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
# پیکربندی + رمزنگاری کلید API
# --------------------------------------------------------------------------

CONFIG_DEFAULTS = {
    "api_key": "",
    "provider": "gemini",                 # gemini | openai
    "base_url": "http://localhost:11434/v1",
    "model": "gemini-2.5-flash",
    "direction": "en2fa",                 # en2fa | fa2en
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


def encrypt_secret(plain: str) -> str:
    """رمزنگاری کلید API برای ذخیره روی دیسک (DPAPI ویندوز؛ بدون وابستگی اضافه)."""
    if not plain:
        return ""
    if sys.platform == "win32":
        try:
            blob = _win_crypt(plain.encode("utf-8"), _DPAPI_ENTROPY, unprotect=False)
            return _PREFIX_DPAPI + base64.b64encode(blob).decode("ascii")
        except Exception:
            pass  # اگر DPAPI در دسترس نبود، به رمزنگاری ضعیف‌تر برمی‌گردیم
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
        raise TranslationError(
            "بازگردانی کلید API رمزنگاری‌شده شکست خورد (احتمالاً کلید روی حساب کاربری "
            f"دیگری ذخیره شده است):\n{exc}"
        )
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


def load_config():
    cfg = dict(CONFIG_DEFAULTS)
    raw_key = ""
    try:
        with open(config_file_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in CONFIG_DEFAULTS})
            raw_key = data.get("api_key", "")
    except (OSError, ValueError):
        return cfg

    # مهاجرت: کلید قدیمیِ رمزنگاری‌نشده را همین حالا رمزنگاری و ذخیره می‌کنیم
    if raw_key and not is_encrypted(raw_key):
        cfg["api_key"] = raw_key
        save_config(cfg)
    else:
        cfg["api_key"] = decrypt_secret(raw_key)
    return cfg


def save_config(cfg):
    disk = dict(cfg)
    disk["api_key"] = encrypt_secret(cfg.get("api_key", ""))
    with open(config_file_path(), "w", encoding="utf-8") as fh:
        json.dump(disk, fh, ensure_ascii=False, indent=2)


def validate_config(cfg):
    """برگرداندن پیام خطای فارسی یا None اگر پیکربندی سالم است."""
    provider = cfg.get("provider", "gemini")
    if provider == "openai":
        if not (cfg.get("base_url") or "").strip():
            return "آدرس سرور (Base URL) خالی است."
        if not (cfg.get("model") or "").strip():
            return "نام مدل را وارد کنید (مثلاً llama3.2 یا qwen2.5:14b)."
        return None
    if not (cfg.get("api_key") or "").strip():
        return "API key گوگل تنظیم نشده است. از دکمهٔ «تنظیمات» آن را وارد کنید."
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

    raise TranslationError(
        "خروجی مدل قابل تحلیل نبود (JSON نامعتبر و body_text هم قابل استخراج نشد).\n"
        "پیشنهاد: در تنظیمات «تست اتصال» را بزنید یا مدل دیگری انتخاب کنید."
    )


def assemble_output(data, direction):
    d = DIRECTIONS[direction]
    labels = d["labels"]
    out = []
    for key in ("authors", "title_or_headings", "subtitles", "publisher"):
        value = (data.get(key) or "").strip()
        if value:
            out.append(f"{labels[key]}: {value}")
    body = (data.get("body_text") or "").strip()
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
                if looks_heading and text not in seen_headings:
                    # بریدن شمارهٔ صفحهٔ احتمالی از انتهای سرفصل
                    clean = re.sub(r"\s+\d{1,3}$", "", text).strip()
                    if len(clean) >= 3:
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
            ok_text = (out or "").strip()[:60] or "(خالی)"
            return True, f"اتصال موفق است ✅ پاسخ سرور: {ok_text}"
        except TranslationError as exc:
            return False, f"اتصال ناموفق ❌\n{exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"اتصال ناموفق ❌\n{exc}"


class GeminiEngine(BaseEngine):
    provider = "gemini"

    def __init__(self, api_key, model, temperature=0.1):
        from google import genai  # ایمپورت تنبل برای حالت بدون gemini

        self.client = genai.Client(api_key=api_key)
        self.model = model or "gemini-2.5-flash"
        self.temperature = float(temperature)

    def _call(self, contents, system, json_mode):
        from google.genai import types
        from google.genai.errors import APIError

        cfg_kwargs = {"temperature": self.temperature}
        if system:
            cfg_kwargs["system_instruction"] = system
        if json_mode:
            cfg_kwargs["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**cfg_kwargs)

        delay = 4
        last_err = None
        for attempt in range(4):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except APIError as err:
                last_err = err
                if err.code == 429 and attempt == 3:
                    raise QuotaExhaustedError(
                        "سهمیهٔ API گوگل پر شد (خطای 429). کمی بعد دوباره ادامه دهید."
                    ) from err
                if err.code in (429, 503) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TranslationError(f"خطای API جمینای ({err.code}): {err}") from err
        raise TranslationError(f"خطای API جمینای: {last_err}")

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
                raise TranslationError(
                    "مدل به دلیل گارد کپی‌رایت (finish_reason=RECITATION) پاسخی برنگرداند. "
                    "این بخش برای بازبینی دستی علامت‌گذاری شد."
                )
        if not raw:
            raise TranslationError("پاسخی از سرور جمینای دریافت نشد.")
        return raw


class OpenAICompatEngine(BaseEngine):
    """اتصال به هر سرور سازگار با OpenAI: Ollama، LM Studio، vLLM، …"""

    provider = "openai"

    def __init__(self, base_url, api_key, model, temperature=0.1):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or "not-needed"
        self.model = model or ""
        self.temperature = float(temperature)

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
                        f"سرور درخواست‌ها را محدود کرد (429):\n{body}"
                    ) from exc
                if exc.code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    last_error = exc
                    continue
                raise TranslationError(f"خطای HTTP {exc.code} از سرور:\n{body}") from exc
            except urllib.error.URLError as exc:
                raise TranslationError(
                    f"اتصال به سرور برقرار نشد ({self.base_url}):\n{exc.reason}"
                ) from exc
            except TimeoutError as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TranslationError("زمان اتصال به سرور تمام شد (timeout).") from exc
        raise TranslationError(f"خطای سرور: {last_error}")

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
        if not self.model:
            raise TranslationError("نام مدل تنظیم نشده است (تنظیمات → مدل).")

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
                msg = str(exc)
                if "response_format" in msg or "HTTP 400" in msg or "HTTP 422" in msg:
                    payload.pop("response_format", None)
                    resp = self._post(payload)
                else:
                    raise
        else:
            resp = self._post(payload)
        text = self._extract_content(resp)
        if not text:
            raise TranslationError("پاسخ خالی از سرور دریافت شد.")
        return text


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
        raise TranslationError("API key گوگل تنظیم نشده است.")
    return GeminiEngine(key, cfg.get("model", "gemini-2.5-flash"),
                        cfg.get("temperature", 0.1))


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
        return out, out, None

    max_chars = int(cfg.get("chunk_max_chars", CONFIG_DEFAULTS["chunk_max_chars"]))
    chunks = split_into_chunks(source, max_chars)
    total = len(chunks)
    if on_progress:
        on_progress(0, total)

    results = []
    tail = context_tail
    for index, chunk in enumerate(chunks, start=1):
        if should_continue and not should_continue():
            raise CancelledError()
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
    if isinstance(corrected, str) and len(corrected.strip()) >= max(40, len(translation) // 3):
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
        self._lock = threading.Lock()
        self.data = {
            "source": self.source_path,
            "translations": {},
            "reviewed": {},
            "structure": None,
            "context_tail": "",
            "updated": 0,
        }

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
        except (OSError, ValueError):
            pass
        return self

    def save(self):
        with self._lock:
            self.data["updated"] = int(time.time())
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

def export_page_text(text, source_name, page, path):
    header = f"ترجمهٔ {source_name} — صفحهٔ {page + 1}\n" + "=" * 40 + "\n\n"
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(header + text + "\n")


def export_markdown(job, source_name, path):
    lines = [f"# ترجمهٔ {source_name}", ""]
    for page in job.ordered_pages():
        lines.append(f"## صفحهٔ {page + 1}")
        lines.append("")
        lines.append(job.get(page) or "")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def export_html(job, doc, source_name, out_dir):
    """کتاب کامل HTML راست‌به‌چپ + تصاویر صفحات (قابل چاپ / ذخیره به‌صورت PDF)."""
    images_dir = os.path.join(out_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    sections = []
    for page in job.ordered_pages():
        text = job.get(page) or ""
        img_tag = ""
        try:
            pix = doc.load_page(page).get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3))
            img_name = f"page_{page + 1:04d}.png"
            pix.save(os.path.join(images_dir, img_name))
            img_tag = f'<img class="page-img" src="images/{img_name}" alt="صفحهٔ {page + 1}">'
        except Exception:
            img_tag = ""
        sections.append(
            f'<section id="page-{page + 1}">'
            f'<div class="page-num">— صفحهٔ {page + 1} —</div>'
            f'<div class="translation">{html_mod.escape(text)}</div>'
            f"{img_tag}"
            f"</section>"
        )

    document = f"""<!DOCTYPE html>
<html dir="rtl" lang="fa">
<head>
<meta charset="utf-8">
<title>ترجمهٔ {html_mod.escape(source_name)}</title>
<style>
  body {{ font-family: "Vazirmatn", "Tahoma", "Segoe UI", sans-serif; direction: rtl;
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
<h1>ترجمهٔ {html_mod.escape(source_name)}</h1>
{chr(10).join(sections)}
</body>
</html>
"""
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(document)
    return index_path
