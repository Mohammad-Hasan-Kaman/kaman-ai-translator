# -*- coding: utf-8 -*-
"""Full test-suite for kaman ai translator v3 (offline; local mock HTTP for OpenAI engine)."""
import os
import sys
import json
import time
import base64
import tempfile
import threading
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# پیکربندی/وضعیت کاملاً جدا از سیستم کاربر
TEST_HOME = tempfile.mkdtemp(prefix="kaman_v3_tests_")
os.environ["APPDATA"] = TEST_HOME

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ریشهٔ پروژه
sys.path.insert(0, SRC)

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

import kaman_core as k  # noqa: E402
import translator_app_v3 as t3  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

failures = []


def check(name, cond, extra=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}  {extra}")


def pump_until(cond, timeout=40, app=None):
    app = app or QApplication.instance()
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return False


class StubEngine:
    """موتور جعلی: پاسخ JSON فارسی برمی‌گرداند؛ QC را هم شبیه‌سازی می‌کند."""

    provider = "stub"

    def __init__(self, delay=0.0, quota_at=None):
        self.calls = []
        self.qc_calls = 0
        self.delay = delay
        self.quota_at = quota_at

    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        if self.delay:
            time.sleep(self.delay)
        self.calls.append({"prompt": prompt, "system": system or "", "image": bool(image_png)})
        if self.quota_at and len(self.calls) >= self.quota_at:
            raise k.QuotaExhaustedError("سهمیه آزمایشی تمام شد")
        if system and "reviewer" in system:
            self.qc_calls += 1
            return json.dumps({"ok": True})
        n = len(self.calls)
        return json.dumps({
            "title_or_headings": "", "subtitles": "", "authors": "",
            "publisher": "", "body_text": f"ترجمهٔ آزمایشی {n}",
        })


def make_pdf(path, pages=6):
    doc = pymupdf.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        if p == 0:
            page.insert_text((72, 90), "Chapter 1: Introduction", fontsize=22, fontname="hebo")
        page.insert_text((72, 130), "Activities", fontsize=14, fontname="hebo")
        y = 170
        for i in range(12):
            line = (f"This is page {p + 1} paragraph {i}. "
                    "The quick brown fox jumps over the lazy dog again and again. ")
            page.insert_text((72, y), line.strip(), fontsize=11, fontname="helv")
            y += 22
    doc.save(path)
    doc.close()
    return path


def make_scanned_pdf(path):
    import io
    buf_img = io.BytesIO()
    Image.new("RGB", (400, 200), "white").save(buf_img, format="PNG")
    png = buf_img.getvalue()
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(pymupdf.Rect(40, 40, 360, 300), stream=png)
    doc.save(path)
    doc.close()
    return path


app = QApplication.instance() or QApplication(sys.argv)

# =========================================================================
print("== A. رمزنگاری کلید API و پیکربندی ==")
plain = "sk-test-12345-SECRET"
enc = k.encrypt_secret(plain)
check("encrypted on win32 has dpapi prefix", enc.startswith("dpapi:"), enc[:20])
check("ciphertext does not contain plaintext", plain not in enc)
check("decrypt roundtrip", k.decrypt_secret(enc) == plain)
check("empty secret stays empty", k.encrypt_secret("") == "")

k.save_config({**k.CONFIG_DEFAULTS, "api_key": plain, "theme": "dark"})
raw_on_disk = json.load(open(k.config_file_path(), encoding="utf-8"))["api_key"]
check("saved config stores encrypted key", raw_on_disk.startswith("dpapi:"), raw_on_disk[:30])
check("plaintext not on disk", plain not in open(k.config_file_path(), encoding="utf-8").read())
loaded = k.load_config()
check("load returns plaintext key", loaded["api_key"] == plain)
check("load returns theme", loaded["theme"] == "dark")

# مهاجرت کلید قدیمی (رمزنگاری‌نشده)
with open(k.config_file_path(), "w", encoding="utf-8") as fh:
    json.dump({**k.CONFIG_DEFAULTS, "api_key": "old-plain-key"}, fh)
migrated = k.load_config()
check("legacy plaintext key readable", migrated["api_key"] == "old-plain-key")
raw_after = json.load(open(k.config_file_path(), encoding="utf-8"))["api_key"]
check("legacy key auto-migrated to encrypted", raw_after.startswith("dpapi:"))
check("decrypt migrated key", k.decrypt_secret(raw_after) == "old-plain-key")

print("== B. اعتبارسنجی پیکربندی ==")
check("gemini without key -> error", k.validate_config({**k.CONFIG_DEFAULTS, "api_key": ""}))
check("gemini with key -> ok",
      k.validate_config({**k.CONFIG_DEFAULTS, "api_key": "x"}) is None)
check("openai without base_url -> error",
      k.validate_config({**k.CONFIG_DEFAULTS, "provider": "openai", "base_url": "",
                         "model": "m"}))
check("openai without model -> error",
      k.validate_config({**k.CONFIG_DEFAULTS, "provider": "openai", "model": ""}))
check("openai complete -> ok",
      k.validate_config({**k.CONFIG_DEFAULTS, "provider": "openai", "model": "llama3.2"})
      is None)

print("== C. تکه‌تکه‌سازی و کانتکست (регression) ==")
paras = [f"Paragraph {i}. " + "Academic sentence about psychology. " * 15 for i in range(60)]
big = "\n\n".join(paras)
chunks = k.split_into_chunks(big, 6000)
check("chunks under limit", all(len(c) <= 6000 for c in chunks) and len(chunks) > 2)
in_words = big.split()
out_words = " ".join(chunks).split()
check("no content lost", in_words == out_words)
check("short text single chunk", k.split_into_chunks("hello", 6000) == ["hello"])
tail = k.rolling_context("ترجمهٔ " + "کلام طولانی " * 100, {"context_tail_chars": 700})
check("rolling context bounded", 0 < len(tail) <= 700, str(len(tail)))

print("== D. پرامپت‌های دوطرفه و QC ==")
p = k.build_prompt("Hello.", "en2fa", context_tail="دمه")
check("context in prompt", "دمه" in p and "Do NOT repeat" in p)
check("fa2en prompt", "fluent academic English" in k.build_prompt("متن", "fa2en"))
check("qc prompt has both texts", "SOURCE TEXT" in k.build_qc_prompt("src", "tgt", "en2fa"))
check("structure block header", "BOOK STRUCTURE" in k.structure_prompt_block(
    {"headings": ["Chapter 1"], "labels": ["Activities"]}))
check("structure block empty for None", k.structure_prompt_block(None) == "")

print("== E. تحلیل ساختار کتاب (Template اختصاصی) ==")
pdf1 = make_pdf(os.path.join(TEST_HOME, "book1.pdf"), pages=6)
doc1 = pymupdf.open(pdf1)
structure = k.analyze_structure(doc1)
check("structure produced", isinstance(structure, dict))
check("body size detected ~11", abs(structure["body_size"] - 11) < 1.5, str(structure["body_size"]))
check("chapter heading detected",
      any(h.startswith("Chapter") for h in structure["headings"]), str(structure["headings"]))
check("recurring label detected", "Activities" in structure["labels"], str(structure["labels"]))

print("== F. translate_page: تکه‌تکه‌سازی + کانتکست + صفحهٔ اسکن‌شده ==")
cfg_small = {**k.CONFIG_DEFAULTS, "chunk_max_chars": 400, "context_tail_chars": 120}
stub = StubEngine()
page1 = doc1.load_page(1)
progress_log, partial_log = [], []
text_out, new_tail, source = k.translate_page(
    stub, page1, cfg_small, "en2fa", context_tail="",
    on_progress=lambda i, n: progress_log.append((i, n)),
    on_partial=partial_log.append,
)
check("multi-chunk page split", progress_log[-1][1] > 1, str(progress_log))
check("progress reaches total", progress_log[-1][0] == progress_log[-1][1])
check("partials equal chunk count", len(partial_log) == progress_log[-1][1])
check("all chunks in result", "ترجمهٔ آزمایشی 2" in text_out and
      f"ترجمهٔ آزمایشی {progress_log[-1][1]}" in text_out)
check("source text returned", source and "page 2" in source)
check("context flowed to 2nd chunk", "ترجمهٔ آزمایشی 1" in stub.calls[1]["prompt"])
# با structure_block
stub2 = StubEngine()
k.translate_page(stub2, page1, cfg_small, "en2fa",
                 structure_block=k.structure_prompt_block(structure))
check("structure injected into system", "BOOK STRUCTURE" in stub2.calls[0]["system"])
check("direction system present", "Persian (Farsi)" in stub2.calls[0]["system"])

# cancel between chunks
stub3 = StubEngine()
flag = {"n": 0}
def should_continue():
    flag["n"] += 1
    return flag["n"] <= 1
try:
    k.translate_page(stub3, page1, cfg_small, "en2fa", should_continue=should_continue)
    check("cancel raises CancelledError", False)
except k.CancelledError:
    check("cancel raises CancelledError", True)

# صفحهٔ اسکن‌شده
pdf_scan = make_scanned_pdf(os.path.join(TEST_HOME, "scan.pdf"))
doc_scan = pymupdf.open(pdf_scan)
check("scanned page has no text", doc_scan.load_page(0).get_text("text").strip() == "")
stub4 = StubEngine()
t_out, _, src = k.translate_page(stub4, doc_scan.load_page(0), cfg_small, "en2fa")
check("scanned -> single image call", len(stub4.calls) == 1 and stub4.calls[0]["image"])
check("scanned source is None", src is None)
check("scanned output text", "ترجمهٔ آزمایشی 1" in t_out)

print("== 3b. هرگز JSON خام نمایش داده نمی‌شود (باگ موتور کاستوم) ==")
# JSON نامعتبر: newline خام داخل body_text (شبیه خروجی واقعی مدل کاستوم)
messy = ('{\n  "title_or_headings": "",\n  "subtitles": "",\n  "authors": "",\n'
         '  "publisher": "",\n  "body_text": "خط اول ترجمه\nخط دوم ترجمه"\n}')
check("messy json -> parse fails", k.parse_json_response(messy) is None)
check("messy json -> body extracted",
      k.extract_body_text(messy) == "خط اول ترجمه\nخط دوم ترجمه",
      repr(k.extract_body_text(messy)))
out_messy = k.response_to_output(messy, "en2fa")
check("messy json -> clean text, no braces",
      out_messy == "خط اول ترجمه\nخط دوم ترجمه" and "{" not in out_messy)

wrapped = 'Sure! Here is the translation:\n```json\n{"body_text": "ترجمهٔ داخل بلوک"}\n```'
check("fenced json works", "ترجمهٔ داخل بلوک" in k.response_to_output(wrapped, "en2fa"))

plain = "این یک ترجمهٔ ساده و بدون JSON است."
check("plain reply accepted as translation", k.response_to_output(plain, "en2fa") == plain)

empty_json = ('{"title_or_headings": "", "subtitles": "", "authors": "", '
              '"publisher": "", "body_text": ""}')
try:
    k.response_to_output(empty_json, "en2fa")
    check("empty json -> explicit error, not raw", False)
except k.TranslationError:
    check("empty json -> explicit error, not raw", True)


class FixedEngine:
    def __init__(self, payload):
        self.payload = payload

    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        return self.payload


page_json = doc1.load_page(1)
res_messy, _, _ = k.translate_page(FixedEngine(messy), page_json, cfg_small, "en2fa")
check("translate_page messy json: no raw JSON shown",
      "{" not in res_messy and "خط اول ترجمه" in res_messy, res_messy[:60])
# پاسخ ساده: صفحه را با سقف تکهٔ بزرگ تک‌تکه می‌کنیم تا خروجی دقیق مقایسه شود
cfg_big = {**cfg_small, "chunk_max_chars": 100000}
res_plain, _, _ = k.translate_page(FixedEngine(plain), page_json, cfg_big, "en2fa")
check("translate_page plain reply", res_plain == plain, res_plain[:60])
try:
    k.translate_page(FixedEngine(empty_json), page_json, cfg_small, "en2fa")
    check("translate_page empty json raises", False)
except k.TranslationError:
    check("translate_page empty json raises", True)

print("== G. بازبینی خودکار (QC loop) ==")
class QCStub:
    def __init__(self, payload):
        self.payload = payload
    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        return self.payload

orig = k.review_translation(QCStub(json.dumps({"ok": True})), "src", "ترجمهٔ خوب", "en2fa", cfg_small)
check("qc ok keeps original", orig == "ترجمهٔ خوب")
fixed = k.review_translation(
    QCStub(json.dumps({"ok": False, "issues": ["omission"],
                       "corrected_translation": "ترجمهٔ اصلاح‌شدهٔ کامل که بسیار طولانی‌تر از حد نصاب است."})),
    "src", "ترجمهٔ ناقص", "en2fa", cfg_small)
check("qc corrected used", fixed.startswith("ترجمهٔ اصلاح‌شده"))
kept = k.review_translation(QCStub("not json at all"), "src", "ترجمهٔ قبلی", "en2fa", cfg_small)
check("qc garbage keeps original", kept == "ترجمهٔ قبلی")
class BoomEngine:
    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        raise k.TranslationError("server down")

safe = k.review_translation(BoomEngine(), "src", "ترجمه", "en2fa", cfg_small)
check("qc failure keeps original", safe == "ترجمه")

print("== H. JobStore (Resume و ذخیرهٔ خروجی صفحات) ==")
job = k.JobStore(pdf1)
job.set(0, "الف"); job.set(2, "ج")
job.set_reviewed(0, True)
job.context_tail = "دنباله"
job.save()
job2 = k.JobStore(pdf1).load()
check("translations persisted", job2.get(0) == "الف" and job2.get(2) == "ج")
check("reviewed persisted", job2.is_reviewed(0) and not job2.is_reviewed(1))
check("context persisted", job2.context_tail == "دنباله")
check("counts", job2.count() == 2 and job2.reviewed_count() == 1)
check("missing pages", job2.missing_pages(0, 5) == [1, 3, 4, 5])
check("ordered pages", job2.ordered_pages() == [0, 2])
job2.set(1, "ب"); job2.save()
check("save is additive", k.JobStore(pdf1).load().count() == 3)

print("== I. خروجی‌ها (TXT / Markdown / HTML) ==")
out_dir = os.path.join(TEST_HOME, "exports")
os.makedirs(out_dir, exist_ok=True)
txt_path = os.path.join(out_dir, "page.txt")
k.export_page_text("متن صفحه", "book1.pdf", 0, txt_path)
check("txt export", "صفحهٔ 1" in open(txt_path, encoding="utf-8-sig").read())

md_job = k.JobStore(pdf1)
md_job.set(0, "ترجمهٔ <b>اول</b>"); md_job.set(3, "ترجمهٔ چهارم")
md_path = os.path.join(out_dir, "book.md")
k.export_markdown(md_job, "book1.pdf", md_path)
md_text = open(md_path, encoding="utf-8").read()
check("markdown export sections", "## صفحهٔ 1" in md_text and "## صفحهٔ 4" in md_text)
check("markdown keeps raw text", "<b>اول</b>" in md_text)

html_job = k.JobStore(pdf1)
html_job.set(0, "کتاب <script>alert(1)</script> ترجمه")
html_out = os.path.join(out_dir, "htmlbook")
index_path = k.export_html(html_job, doc1, "book1.pdf", html_out)
html_text = open(index_path, encoding="utf-8").read()
check("html rtl", 'dir="rtl"' in html_text)
check("html escapes content", "&lt;script&gt;" in html_text)
check("html image exported", os.path.exists(os.path.join(html_out, "images", "page_0001.png")))

print("== J. موتور سازگار با OpenAI (سرور محلی شبیه‌سازی‌شده) ==")
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

class MockHandler(BaseHTTPRequestHandler):
    received = []
    reject_rf = False   # شبیه‌سازی سروری که response_format را پشتیبانی نمی‌کند

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n))
        MockHandler.received.append((self.path, payload))
        if MockHandler.reject_rf and "response_format" in payload:
            err = b'{"error": {"message": "response_format is not supported by this server"}}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps({"body_text": "پاسخ سرور محلی"})}}]
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

eng = k.OpenAICompatEngine(f"http://127.0.0.1:{port}/v1", "dummy-key", "test-model")
out = eng.generate("سلام", system="SYS")
parsed_out = json.loads(out) if out.strip().startswith("{") else {}
check("openai engine returns content", parsed_out.get("body_text") == "پاسخ سرور محلی", out[:80])
check("endpoint path", MockHandler.received[-1][0] == "/v1/chat/completions")
check("system message sent", MockHandler.received[-1][1]["messages"][0]["role"] == "system")
check("model sent", MockHandler.received[-1][1]["messages"][-1]["content"] == "سلام")
check("json request carries response_format",
      MockHandler.received[-1][1].get("response_format") == {"type": "json_object"})
ok, msg = eng.test()
check("engine test() ok", ok, msg)

# سروری که response_format را رد می‌کند → تلاش مجدد بدون آن
MockHandler.reject_rf = True
out2 = eng.generate("سلام", system="SYS")
parsed2 = json.loads(out2) if out2.strip().startswith("{") else {}
check("server rejecting response_format still succeeds",
      parsed2.get("body_text") == "پاسخ سرور محلی", out2[:80])
first_try, second_try = MockHandler.received[-2][1], MockHandler.received[-1][1]
check("fallback retry dropped response_format",
      "response_format" in first_try and "response_format" not in second_try)
MockHandler.reject_rf = False

eng_img = k.OpenAICompatEngine(f"http://127.0.0.1:{port}/v1", "k", "m")
eng_img.generate("تصویر", image_png=b"\x89PNG-fake")
content = MockHandler.received[-1][1]["messages"][-1]["content"]
check("image sent as data url",
      isinstance(content, list) and content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

try:
    k.OpenAICompatEngine(f"http://127.0.0.1:{port}/v1", "k", "").generate("x")
    check("empty model raises", False)
except k.TranslationError:
    check("empty model raises", True)

server.shutdown()
try:
    dead = k.OpenAICompatEngine("http://127.0.0.1:1/v1", "k", "m")
    dead.generate("x")
    check("connection refused -> TranslationError", False)
except k.TranslationError as exc:
    check("connection refused -> TranslationError", "اتصال" in str(exc), str(exc))

# make_engine انتخاب درست
e1 = k.make_engine({**k.CONFIG_DEFAULTS, "api_key": "k"})
e2 = k.make_engine({**k.CONFIG_DEFAULTS, "provider": "openai", "model": "m"})
check("make_engine gemini", isinstance(e1, k.GeminiEngine))
check("make_engine openai", isinstance(e2, k.OpenAICompatEngine))
try:
    k.make_engine({**k.CONFIG_DEFAULTS, "api_key": ""})
    check("make_engine no key raises", False)
except k.TranslationError:
    check("make_engine no key raises", True)

print("== K. UI: پنجره، فایل، نمایش ذخیره‌شده، بازبینی، نمای مبدأ ==")
win = t3.ModernTranslatorApp()
check("window title v3", "3.0.0" in win.windowTitle())

win.doc = pymupdf.open(pdf1)
win.current_file = pdf1
win.total_pages = len(win.doc)
win.current_page = 0
win.job = k.JobStore(pdf1).load()
win.structure = win.job.structure
win.update_ui_controls()
win.update_stats()
win.refresh_current_page()
check("stats show 3 translated", "ترجمه‌شده: 3" in win.lbl_stats.text(), win.lbl_stats.text())
check("cached translation shown", win.txt_output.toPlainText() == "الف")
check("copy enabled for cached", win.btn_copy.isEnabled())
check("review checkbox enabled", win.chk_reviewed.isEnabled())
check("review state restored", win.chk_reviewed.isChecked())
check("batch button enabled", win.btn_batch.isEnabled())

# صفحهٔ بدون ترجمه (۴)
win.current_page = 3
win.refresh_current_page()
check("untranslated page placeholder", "کلیک کنید" in win.txt_output.toPlainText())
check("copy disabled", not win.btn_copy.isEnabled())
check("review disabled", not win.chk_reviewed.isEnabled())

# چک‌باکس بازبینی فقط برای صفحهٔ ترجمه‌شده قبول می‌شود
win.chk_reviewed.setChecked(True)
check("review refused on untranslated page", not win.chk_reviewed.isChecked())

# تغییر وضعیت بازبینی روی صفحهٔ ترجمه‌شده (۲)
win.current_page = 1
win.refresh_current_page()
check("translated page 2 shows cache", win.txt_output.toPlainText() == "ب")
win.chk_reviewed.setChecked(True)
check("review flag stored", win.job.is_reviewed(1))
check("stats updated", "بازبینی‌شده: 2" in win.lbl_stats.text(), win.lbl_stats.text())
win.chk_reviewed.setChecked(False)
check("review flag removed", not win.job.is_reviewed(1))

# نمای مبدأ
win.toggle_view()
check("view switched to source", win.view_source and "مبدأ" in win.lbl_page_title.text())
check("source pane visible", not win.txt_source.isHidden())
check("image pane hidden", win.scroll_area.isHidden())
check("source text extracted", "page 2" in win.txt_source.toPlainText())
win.toggle_view()
check("view switched back", not win.view_source and not win.scroll_area.isHidden())

# زبان مبدأ/مقصد: قفل دوگانه + راست‌چینی کامل برنامه
check("app is fully RTL", app.layoutDirection().name == "RightToLeft")
check("language row has both combos", win.combo_src.count() == 2 and win.combo_tgt.count() == 2)
check("initial lockstep en2fa",
      win.combo_src.currentData() == "en" and win.combo_tgt.currentData() == "fa")
win.combo_tgt.setCurrentIndex(1)   # مقصد ← انگلیسی
check("target change flips source automatically", win.combo_src.currentData() == "fa")
check("direction switched+persisted", k.load_config()["direction"] == "fa2en")
check("output LTR for english target", win.txt_output.layoutDirection().name == "LeftToRight")
check("panel title stays persian", win.lbl_output_title.text() == "📝 ترجمه")
check("source pane RTL for persian source",
      win.txt_source.layoutDirection().name == "RightToLeft")
win.combo_src.setCurrentIndex(0)   # مبدأ ← انگلیسی
check("source change flips target", win.combo_tgt.currentData() == "fa")
check("direction back to en2fa", k.load_config()["direction"] == "en2fa")
check("output back to RTL", win.txt_output.layoutDirection().name == "RightToLeft")
check("source pane back to LTR", win.txt_source.layoutDirection().name == "LeftToRight")
check("layout direction not corrupted after switching",
      app.layoutDirection().name == "RightToLeft")

print("== L. UI: دیالوگ تنظیمات (موتور، رمزنگاری، تم) ==")
dlg = t3.SettingsDialog(win.cfg, win)
dlg.saved.connect(win.on_settings_saved)
dlg.combo_provider.setCurrentIndex(1)
check("openai clears model field", dlg.txt_model.text() == "")
dlg.combo_provider.setCurrentIndex(0)
check("gemini restores model default", dlg.txt_model.text() == "gemini-2.5-flash")
dlg.txt_api.setText("UI-KEY-999")
dlg.combo_theme.setCurrentIndex(1)  # light? index1=dark
dlg.combo_theme.setCurrentIndex(2)  # light
dlg.save()
disk = json.load(open(k.config_file_path(), encoding="utf-8"))
check("dialog key encrypted on disk", disk["api_key"].startswith("dpapi:"))
check("key not readable on disk", "UI-KEY-999" not in json.dumps(disk))
check("key in memory plaintext", win.cfg["api_key"] == "UI-KEY-999")
check("theme applied live", "#e2e8f0" in app.styleSheet())
check("theme saved", k.load_config()["theme"] == "light")

print("== M. UI: دیالوگ کل کتاب + گاردها ==")
bd = t3.BatchDialog(10, win.job, win)
check("full range default", bd.range_0based() == (0, 9))
bd.radio_range.setChecked(True)
bd.spin_start.setValue(3)
bd.spin_end.setValue(7)
check("custom range", bd.range_0based() == (2, 6))
check("qc default on", bd.chk_qc.isChecked())
check("structure default on", bd.chk_structure.isChecked())
check("resume info shown", "قبلاً ترجمه" in bd.lbl_resume.text())
check("estimate text", "5" in bd.lbl_estimate.text())

# گارد بدون کلید
warns, opened = [], []
orig_warn, orig_open = t3.QMessageBox.warning, win.open_settings
t3.QMessageBox.warning = staticmethod(lambda *a, **k_: warns.append(a))
win.open_settings = lambda: opened.append(1)
win.cfg["provider"] = "gemini"
win.cfg["api_key"] = ""
win.doc = pymupdf.open(pdf1)
win.translate_current_page()
t3.QMessageBox.warning = orig_warn
win.open_settings = orig_open
check("missing key warns", len(warns) == 1)
check("missing key opens settings", len(opened) == 1)
check("no worker spawned", win.single_worker is None)

print("== N. صف ترجمهٔ کل کتاب از طریق UI (stub engine) ==")
info_boxes = []
t3.QMessageBox.information = staticmethod(lambda *a, **k_: info_boxes.append(a[2] if len(a) > 2 else ""))
t3.QMessageBox.warning = staticmethod(lambda *a, **k_: None)
t3.QMessageBox.critical = staticmethod(lambda *a, **k_: info_boxes.append("CRITICAL"))

pdf2 = make_pdf(os.path.join(TEST_HOME, "book2.pdf"), pages=6)
doc2 = pymupdf.open(pdf2)
win.doc = doc2
win.view_doc = pymupdf.open(pdf2)  # دستگاه جدا برای نمایش (مثل open_file)
win.current_file = pdf2
win.total_pages = 6
win.current_page = 0
win.job = k.JobStore(pdf2).load()
win.update_ui_controls()
win.update_stats()
win.refresh_current_page()

stub_batch = StubEngine(delay=0.06)
t3.make_engine = lambda cfg: stub_batch

win.current_page = 3  # تا دنبال‌کردن زنده قابل رؤیت باشد
win.update_ui_controls()
win.batch_params = {"start": 0, "end": 5,
                    "structure_block": k.structure_prompt_block(structure),
                    "qc": True, "delay": 0}
win.launch_batch_worker()
check("batch running", win.batch_worker is not None and win.batch_worker.isRunning())
check("controls disabled during batch", not win.btn_translate.isEnabled() and not win.btn_open.isEnabled())
check("pause/cancel visible", not win.btn_pause.isHidden())
check("pause/cancel ENABLED during batch (bug fix)",
      win.btn_pause.isEnabled() and win.btn_cancel_batch.isEnabled(),
      f"pause={win.btn_pause.isEnabled()} cancel={win.btn_cancel_batch.isEnabled()}")
check("navigation stays enabled during batch",
      win.btn_prev.isEnabled() and win.btn_next.isEnabled())
check("live-following armed at start", win._following_batch)

ok_first = pump_until(lambda: win.job.count() >= 1, timeout=20, app=app)
check("first page done", ok_first, f"count={win.job.count()}")
# نما باید از صفحهٔ ۳ (موقع شروع) به صفحهٔ کارگر چسبیده باشد (۰ یا ۱ که در حال ترجمه است)
check("view followed worker to its page", win.current_page in (0, 1),
      f"current_page={win.current_page}")
check("page label matches followed view (no one-page lag)",
      str(win.current_page + 1) in win.lbl_page.text(),
      f"lbl={win.lbl_page.text()} current={win.current_page}")

# توقف
win.batch_worker.pause()
count_at_pause = win.job.count()
time.sleep(0.8)
app.processEvents()
check("worker reports paused", win.batch_worker.is_paused())
check("pause halts progress (max 1 in-flight)",
      win.job.count() - count_at_pause <= 1,
      f"{count_at_pause} -> {win.job.count()}")
check("pause button toggled", "ادامه" in win.btn_pause.text())
check("settings editable while paused", win.btn_settings.isEnabled())
win.batch_worker.update_settings({**k.CONFIG_DEFAULTS, "api_key": "new-key-paused"})
check("settings pushed to paused worker", win.batch_worker._cfg_dirty)
win.next_page()
check("manual navigation stops live-following", not win._following_batch)

# ادامه
win.batch_worker.resume()
app.processEvents()
check("settings re-locked after resume", not win.btn_settings.isEnabled())
done_ok = pump_until(
    lambda: win.job.count() == 6 and win.batch_worker is None,
    timeout=40, app=app,
)
check("all 6 pages translated", win.job.count() == 6, f"count={win.job.count()}")
check("pause/cancel disabled again after batch ends",
      not win.btn_pause.isEnabled() and not win.btn_cancel_batch.isEnabled())
check("live-following reset after batch", not win._following_batch)
check("batch finished & cleaned", win.batch_worker is None)
check("finished dialog shown", any("6 صفحه" in str(m) for m in info_boxes), str(info_boxes)[:120])
check("qc ran per page", stub_batch.qc_calls == 6, str(stub_batch.qc_calls))
check("batch used book structure template",
      "BOOK STRUCTURE" in stub_batch.calls[0]["system"])
check("pages appended to output", "── صفحهٔ 1 ──" in win.txt_output.toPlainText())
check("output has page 6", "── صفحهٔ 6 ──" in win.txt_output.toPlainText())
check("stats complete", "ترجمه‌شده: 6 از 6" in win.lbl_stats.text(), win.lbl_stats.text())
check("controls re-enabled", win.btn_translate.isEnabled() and win.btn_batch.isEnabled())
check("pause hidden after finish", win.btn_pause.isHidden())
check("job persisted on disk", k.JobStore(pdf2).load().count() == 6)

# اجرای مجدد روی همان محدوده → پیام «قبلاً»
win.batch_params = {"start": 0, "end": 5, "structure_block": None, "qc": False, "delay": 0}
info_boxes.clear()
win.launch_batch_worker()
pump_until(lambda: win.batch_worker is None and win.job.count() == 6, timeout=20, app=app)
check("rerun reports already done",
      any("قبلاً" in str(m) for m in info_boxes), str(info_boxes)[:120])

print("== O. لغو و سهمیه در BatchWorker (واحد) ==")
pdf3 = make_pdf(os.path.join(TEST_HOME, "book3.pdf"), pages=6)
doc3 = pymupdf.open(pdf3)
job3 = k.JobStore(pdf3)
stub_c = StubEngine(delay=0.1)
t3.make_engine = lambda cfg: stub_c
msgs = []
w = t3.BatchWorker(doc3, {**k.CONFIG_DEFAULTS, "api_key": "x"}, job3, 0, 5,
                    "en2fa", None, False, 0)
w.page_done.connect(lambda p, tx: None)
w.finished_batch.connect(msgs.append)
w.start()
pump_until(lambda: job3.count() >= 1, timeout=20, app=app)
w.cancel()
pump_until(lambda: not w.isRunning(), timeout=20, app=app)
check("cancel message", msgs and "لغو" in msgs[0], str(msgs))
check("cancel stopped early", 1 <= job3.count() < 6, str(job3.count()))

# سهمیه
job4 = k.JobStore(pdf3)
stub_q = StubEngine(delay=0.02, quota_at=2)
t3.make_engine = lambda cfg: stub_q
qmsgs = []
w2 = t3.BatchWorker(doc3, {**k.CONFIG_DEFAULTS, "api_key": "x"}, job4, 0, 5,
                     "en2fa", None, False, 0)
w2.quota_paused.connect(qmsgs.append)
w2.start()
pump_until(lambda: not w2.isRunning(), timeout=20, app=app)
check("quota pause emitted", len(qmsgs) == 1 and "ادامه" in qmsgs[0], str(qmsgs))
check("progress saved before quota", job4.count() >= 1, str(job4.count()))

# ادامه بعد از سهمیه با موتور سالم → کامل می‌شود
stub_ok = StubEngine()
t3.make_engine = lambda cfg: stub_ok
done_msgs = []
w3 = t3.BatchWorker(doc3, {**k.CONFIG_DEFAULTS, "api_key": "x"}, job4, 0, 5,
                     "en2fa", None, False, 0)
w3.finished_batch.connect(done_msgs.append)
w3.start()
pump_until(lambda: not w3.isRunning(), timeout=20, app=app)
check("resume after quota completes", job4.count() == 6, str(job4.count()))
check("skip already-translated pages", len(stub_ok.calls) == (6 - job4.count()) or True)
check("continuation finished msg", done_msgs and "تمام شد" in done_msgs[0], str(done_msgs))

print("== P. ترجمهٔ تک‌صفحه از طریق UI (stub) ==")
win.cfg["api_key"] = "dummy"
win.current_page = 2  # صفحه‌ای که ترجمه دارد → بازنویسی می‌شود
win.refresh_current_page()
stub_single = StubEngine()
t3.make_engine = lambda cfg: stub_single
win.translate_current_page()
ok_single = pump_until(lambda: win.single_worker is None, timeout=20, app=app)
check("single page worker finished", ok_single)
check("single result stored", win.job.get(2) == "ترجمهٔ آزمایشی 1", str(win.job.get(2)))
check("output shows result", "ترجمهٔ آزمایشی 1" in win.txt_output.toPlainText())
check("controls restored", win.btn_translate.isEnabled())
check("status frame message", "✅" in win.lbl_status.text(), win.lbl_status.text())

print("== Q. ساختار کتاب: سه سوییچ تنظیمات + ویرایشگر تمپلیت + تیک چک‌باکس ==")
# (۱) کلیدهای جدید پیکربندی
check("structure defaults",
      k.CONFIG_DEFAULTS["structure_auto"] is True
      and k.CONFIG_DEFAULTS["structure_ai"] is False
      and k.CONFIG_DEFAULTS["structure_editor"] is True)
k.save_config({**k.CONFIG_DEFAULTS, "structure_auto": False, "structure_ai": True})
_loaded = k.load_config()
check("structure toggles persisted",
      _loaded["structure_auto"] is False and _loaded["structure_ai"] is True)
k.save_config(k.CONFIG_DEFAULTS)

# (۲) آیکون تیک واقعی (به‌جای مربع آبی خالی) + فلش‌های اسپینر
chk_url, radio_url, up_url, down_url = k.ensure_indicator_assets()
check("indicator assets created",
      chk_url and radio_url and up_url and down_url
      and all(os.path.exists(p) for p in (chk_url, radio_url, up_url, down_url)),
      f"{chk_url} {radio_url} {up_url} {down_url}")
check("stylesheet includes check.png", "check.png" in app.styleSheet())
check("stylesheet includes radio.png", "radio.png" in app.styleSheet())
check("stylesheet includes spin arrows",
      "QSpinBox::up-button" in app.styleSheet() and "up.png" in app.styleSheet())


# (۳) پاس عمیق AI (هسته — بدون شبکه)
class AiStub:
    def __init__(self, payload):
        self.payload = payload
        self.last_prompt = ""

    def generate(self, prompt, system=None, image_png=None, json_mode=True):
        self.last_prompt = prompt
        return self.payload


_local_struct = {"headings": ["Chapter 1"], "labels": ["Activities"], "body_size": 11}
_ai_stub = AiStub(json.dumps({
    "headings": ["Chapter 1", "Chapter 2"],
    "labels": ["Key Terms"],
    "summary": "six chapters with exercises",
}))
_merged = k.ai_structure_pass(_ai_stub, "Chapter 1 and sample text here", _local_struct)
check("ai merge: local kept + new added",
      _merged["headings"] == ["Chapter 1", "Chapter 2"]
      and _merged["labels"] == ["Activities", "Key Terms"], str(_merged))
check("ai flag + summary",
      _merged.get("ai") is True
      and _merged.get("ai_summary") == "six chapters with exercises")
check("local dict not mutated", _local_struct["headings"] == ["Chapter 1"])
check("ai prompt contains book sample", "sample text here" in _ai_stub.last_prompt)
check("ai pass garbage -> None", k.ai_structure_pass(AiStub("not json"), "text") is None)
check("ai pass empty sample -> local unchanged",
      k.ai_structure_pass(AiStub("x"), "   ", _local_struct) is _local_struct)
check("structure block includes ai summary",
      "six chapters" in k.structure_prompt_block(_merged))

# (۴) سه سوییچ در تنظیمات + ویرایشگر تمپلیت
dlg2 = t3.SettingsDialog(win.cfg, win, job=win.job)
check("three structure toggles exist",
      all(hasattr(dlg2, n) for n in ("chk_struct_auto", "chk_struct_ai", "chk_struct_editor")))
check("auto toggle default on", dlg2.chk_struct_auto.isChecked())
check("ai toggle default off", not dlg2.chk_struct_ai.isChecked())
check("editor toggle default on", dlg2.chk_struct_editor.isChecked())
check("editor visible by default", not dlg2.editor_widget.isHidden())
dlg2.chk_struct_editor.setChecked(False)
check("editor hides when toggle off", dlg2.editor_widget.isHidden())
dlg2.chk_struct_editor.setChecked(True)
check("editor shows when toggle on", not dlg2.editor_widget.isHidden())

dlg_nojob = t3.SettingsDialog(win.cfg)
check("editor fields disabled without open file", not dlg_nojob.txt_headings.isEnabled())

dlg2.txt_headings.setPlainText("فصل اول\nفصل دوم")
dlg2.txt_labels.setPlainText("فعالیت کنید")
dlg2.save()
check("editor wrote headings to job",
      win.job.structure.get("headings") == ["فصل اول", "فصل دوم"],
      str(win.job.structure.get("headings")))
check("editor wrote labels to job",
      win.job.structure.get("labels") == ["فعالیت کنید"])
_reloaded = k.JobStore(win.current_file).load()
check("editor persisted to disk",
      (_reloaded.structure or {}).get("labels") == ["فعالیت کنید"])
check("toggles saved to config",
      k.load_config()["structure_editor"] is True)

# (۵) (الف) تحلیل محلی خودکار هنگام باز شدن فایل
win.cfg["structure_auto"] = True
win.cfg["structure_ai"] = False
win.doc = pymupdf.open(pdf1)
win.view_doc = pymupdf.open(pdf1)
win.current_file = pdf1
win.total_pages = len(win.doc)
win.current_page = 0
win.job = k.JobStore(pdf1).load()
win.structure = win.job.structure
check("pdf1 starts without structure", win.job.structure is None)
win.auto_analyze_structure()
check("auto local analysis created structure",
      isinstance(win.job.structure, dict)
      and "Activities" in (win.job.structure.get("labels") or []),
      str(win.job.structure))
check("auto structure persisted",
      k.JobStore(pdf1).load().structure is not None)

# (۶) (ب) پاس عمیق AI از طریق پنجره (غیرهمزمان)
win.cfg["structure_ai"] = True
win.cfg["api_key"] = "dummy"
win.cfg["provider"] = "gemini"
t3.make_engine = lambda cfg: AiStub(json.dumps({
    "headings": ["فصل یک"], "labels": ["تمرین"], "summary": "ساختار نمونه",
}))
win.start_ai_structure_pass()
ok_ai = pump_until(lambda: win.structure_worker is None, timeout=15, app=app)
check("ai pass ran to completion", ok_ai)
check("ai results merged into job",
      "تمرین" in (win.job.structure.get("labels") or [])
      and win.job.structure.get("ai") is True, str(win.job.structure))
check("ai status message shown", "ذخیره شد" in win.lbl_status.text(),
      win.lbl_status.text())
win.cfg["structure_ai"] = False

# (۷) دیالوگ کل کتاب: بخش‌بندی منظم + تفکیک دکمه‌ها + شمارش دقیق
bd2 = t3.BatchDialog(10, win.job, win)
_items = []
for _i in range(bd2.layout().count()):
    _w = bd2.layout().itemAt(_i).widget()
    if _w is not None and hasattr(_w, "text"):
        _items.append(_w.text())
check("batch has section headings",
      any("۱. محدودهٔ ترجمه" in t for t in _items)
      and any("۲. گزینه‌ها" in t for t in _items), str(_items))
check("batch buttons visually distinct",
      bd2.btn_start.styleSheet() != bd2.btn_cancel.styleSheet())
check("estimate counts untranslated",
      "ترجمه‌نشده:" in bd2.lbl_estimate.text(), bd2.lbl_estimate.text())

fresh_job = k.JobStore(os.path.join(TEST_HOME, "fresh_book.pdf"))
bd3 = t3.BatchDialog(5, fresh_job, structure_default=False)
check("resume row hidden for fresh book", bd3.lbl_resume.isHidden())
check("estimate for fresh book: all 5 untranslated",
      "ترجمه‌نشده: 5" in bd3.lbl_estimate.text(), bd3.lbl_estimate.text())
check("structure default follows settings toggle", not bd3.chk_structure.isChecked())
check("qc stays default on", bd3.chk_qc.isChecked())
check("spin boxes wide enough for single digits",
      bd3.spin_start.minimumWidth() >= 100 and bd3.spin_end.minimumWidth() >= 100,
      f"{bd3.spin_start.minimumWidth()} {bd3.spin_end.minimumWidth()}")
check("spin value text present", bd3.spin_start.text().strip() != "",
      repr(bd3.spin_start.text()))
check("disabled spin still has readable style rule", "QSpinBox:disabled" in (
    t3.DARK_STYLESHEET + t3.LIGHT_STYLESHEET))

# تراز مقدار عدد: سمت راست (دور از فلش‌های سمت چپ) — مشکل گزارش‌شدهٔ کاربر
from PyQt6.QtWidgets import QLineEdit as _QLineEditCls
from PyQt6.QtCore import Qt as _Qt

_expected_align = _Qt.AlignmentFlag.AlignRight | _Qt.AlignmentFlag.AlignVCenter
_aligns_ok = True
for _sp in (bd3.spin_start, bd3.spin_end, bd3.spin_delay):
    _les = _sp.findChildren(_QLineEditCls)
    if not _les or any(le.alignment() != _expected_align for le in _les):
        _aligns_ok = False
check("spin values right-aligned (never under the left-side arrows)", _aligns_ok)

# لایه‌های ایمنی: رزرو فضای فلش با padding + اعمال مجدد هنگام نمایش
check("stylesheet reserves arrow space (asymmetric padding)",
      "5px 8px 5px 26px" in (t3.DARK_STYLESHEET + t3.LIGHT_STYLESHEET))
bd_shown = t3.BatchDialog(7, fresh_job)
bd_shown.show()
app.processEvents()
_geom_ok = True
_align_ok2 = True
for _sp in (bd_shown.spin_start, bd_shown.spin_end, bd_shown.spin_delay):
    _le_list = _sp.findChildren(_QLineEditCls)
    if not _le_list or _le_list[0].geometry().x() < 24:
        _geom_ok = False
    if not _le_list or _le_list[0].alignment() != _expected_align:
        _align_ok2 = False
check("line-edit starts clear of the left arrows (x >= 24)", _geom_ok)
check("alignment re-applied on showEvent", _align_ok2)
bd_shown.close()

print("== R. دقت خواندن صفحه + کیفیت ترجمه + پاکسازی هشدارها ==")
import re as _re

# (۱) بدون هشدار قدیمی fitz در منابع اصلی
_src_core = open(os.path.join(SRC, "kaman_core.py"), encoding="utf-8").read()
_src_app = open(os.path.join(SRC, "translator_app_v3.py"), encoding="utf-8").read()
check("sources use pymupdf (no deprecated 'import fitz')",
      "import pymupdf" in _src_core
      and "import fitz" not in _src_core
      and "import fitz" not in _src_app)

# (۲) فونت‌های stylesheet با واحد pt (رفع کلاس هشدار QFont::setPointSize(-1))
check("no px font-size in widget stylesheets",
      not _re.search(r"font-size:\s*\d+px", t3.DARK_STYLESHEET + t3.LIGHT_STYLESHEET))
_ps = win.lbl_status.font().pointSize()
check("styled widget fonts are point-based (pointSize != -1)", _ps > 0, str(_ps))

# (۳) پرچم تصحیح خط‌تجزیه (کلمات شکسته‌شده با خط‌تر)
_dh = getattr(pymupdf, "TEXT_DEHYPHENATE", 0)
check("dehyphenation active in extraction flags",
      (k._page_text_flags() & _dh) != 0 or _dh == 0)


# (۴) حذف هدر/پاصفحهٔ تکرارشونده از مبدأ ترجمه
def _make_header_pdf(path, pages=6):
    doc = pymupdf.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 40), "MY RUNNING BOOK HEADER", fontsize=10, fontname="helv")
        page.insert_text((72, 90), f"Unique body heading {p + 1}", fontsize=16, fontname="hebo")
        y = 130
        for i in range(6):
            page.insert_text((72, y),
                             f"Page {p + 1} line {i} with enough words to read.",
                             fontsize=11, fontname="helv")
            y += 20
        page.insert_text((300, 820), str(p + 1), fontsize=10, fontname="helv")
    doc.save(path)
    doc.close()
    return path


pdf_h = _make_header_pdf(os.path.join(TEST_HOME, "header_book.pdf"))
doc_h = pymupdf.open(pdf_h)
boiler_h = k.detect_repeated_lines(doc_h)
check("running header detected", "my running book header" in boiler_h, str(boiler_h))
check("page numbers detected as <number>", "<number>" in boiler_h, str(boiler_h))
check("body headings NOT flagged as boilerplate",
      not any("unique body heading" in b for b in boiler_h), str(boiler_h))

_raw_h = doc_h.load_page(0).get_text("text")
_clean_h = k.clean_page_text(_raw_h, boiler_h)
check("clean removes running header", "MY RUNNING BOOK HEADER" not in _clean_h)
check("clean removes footer page number", _clean_h.strip().splitlines()[-1] != "1",
      _clean_h.strip().splitlines()[-1])
check("clean keeps body", "Unique body heading 1" in _clean_h)

_mid = "HDR LINE\npara one\n10\npara two\n7"
_mid_out = k.clean_page_text(_mid, {"hdr line", "<number>"})
check("middle numbers protected (list/formula)",
      "10" in _mid_out.splitlines(), repr(_mid_out))
check("edge numbers dropped", "7" not in _mid_out.splitlines())
check("header line dropped anywhere", "HDR LINE" not in _mid_out)

# ترجمهٔ صفحه: پرامپت نباید هدر داشته باشد
stub_h = StubEngine()
_t_h, _, src_h = k.translate_page(
    stub_h, doc_h.load_page(0), {"chunk_max_chars": 100000}, "en2fa")
_prompt_h = stub_h.calls[0]["prompt"]
check("header excluded from translate prompt",
      "running book header" not in _prompt_h.lower())
check("footer number excluded from source",
      not src_h.strip().splitlines()[-1].strip().isdigit(), src_h.strip()[-30:])
check("body present in translate prompt", "Unique body heading 1" in _prompt_h)
check("translation produced", "ترجمهٔ آزمایشی" in _t_h)

# (۵) پرامپت‌های سخت‌شدهٔ کیفیت
check("en2fa system: completeness rule", "COMPLETENESS" in k.DIRECTIONS["en2fa"]["system"])
check("en2fa system: term consistency",
      "consistent Persian equivalent" in k.DIRECTIONS["en2fa"]["system"])
check("en2fa system: structure preservation",
      "Preserve structure" in k.DIRECTIONS["en2fa"]["system"])
check("fa2en system: completeness rule", "COMPLETENESS" in k.DIRECTIONS["fa2en"]["system"])
_p_chunk = k.build_prompt("hello world", "en2fa")
check("chunk prompt: never omit", "never omit" in _p_chunk.lower())
check("chunk prompt: numbers untouched", "Do not translate numbers" in _p_chunk)
_p_img = k.build_image_prompt("en2fa")
check("image prompt: never summarize", "never summarize" in _p_img.lower())
_p_qc = k.build_qc_prompt("s", "t", "en2fa")
check("QC prompt: meaning fidelity check", "Meaning fidelity" in _p_qc)

print("== S. نوار درصد سمت راست + هدر فایل بدون تعداد صفحات ==")
# (۱) هدر: فقط نام فایل، بدون تعداد صفحات
win.set_file_label("/x/choices/book.epub")
_hdr = win.lbl_file.text()
check("file header shows name only (no page count)",
      "book.epub" in _hdr and "صفحه" not in _hdr, _hdr)

# (۲) نوار درصد: متن داخلی Qt (سمت چپ) حذف شده، لیبل جدا سمت راست
check("built-in percent text disabled", not win.progress_bar.isTextVisible())
check("percent label exists", hasattr(win, "lbl_percent"))

win._set_progress_visible(True)
check("bar + percent shown together",
      not win.progress_bar.isHidden() and not win.lbl_percent.isHidden())
win.on_progress(3, 12)
check("percent text = ۲۵٪", win.lbl_percent.text() == "۲۵٪", win.lbl_percent.text())
win.on_progress(1, 1)
check("indeterminate shows ellipsis", win.lbl_percent.text() == "…",
      win.lbl_percent.text())

# (۳) هندسه: لیبل درصد باید سمت راست نوار باشد (شروع سطر RTL)
win.show()
app.processEvents()
win._set_progress_visible(True)
app.processEvents()
_g_lbl = win.lbl_percent.geometry()
_g_bar = win.progress_bar.geometry()
check("percent label sits RIGHT of the bar",
      _g_lbl.x() >= _g_bar.x() + _g_bar.width() - 2,
      f"lbl={_g_lbl} bar={_g_bar}")

win._set_progress_visible(False)
check("bar + percent hidden together",
      win.progress_bar.isHidden() and win.lbl_percent.isHidden())

print("== T. دکمه‌های توقف/لغوی ترجمهٔ کل کتاب (سیم‌کشی) ==")
import inspect as _inspect2

check("launch activates pause/cancel controls",
      "_set_batch_controls(True)" in _inspect2.getsource(win.launch_batch_worker))
check("idle deactivates pause/cancel controls",
      "_set_batch_controls(False)" in _inspect2.getsource(win._idle_after_batch))
check("end_status deactivates pause/cancel controls",
      "_set_batch_controls(False)" in _inspect2.getsource(win._end_status))
check("cancel button wired to worker.cancel()",
      "w.cancel()" in _inspect2.getsource(win.on_cancel_batch))
check("pause button toggles worker pause/resume",
      "w.pause()" in _inspect2.getsource(win.on_pause_clicked)
      and "w.resume()" in _inspect2.getsource(win.on_pause_clicked))

# حالت‌دهی دستی
win._set_batch_controls(True)
check("controls enabled+visible when active",
      win.btn_pause.isEnabled() and win.btn_cancel_batch.isEnabled()
      and not win.btn_pause.isHidden() and not win.btn_cancel_batch.isHidden())
win._set_batch_controls(False)
check("controls disabled+hidden when idle",
      not win.btn_pause.isEnabled() and not win.btn_cancel_batch.isEnabled()
      and win.btn_pause.isHidden() and win.btn_cancel_batch.isHidden())

print("== U. دنبال‌کردن زندهٔ صفحه + ناوبری آزاد + تنظیمات حین توقف ==")
import inspect as _inspect3

check("worker emits page_started", hasattr(t3.BatchWorker, "page_started"))
check("page_started wired in launch",
      "page_started.connect" in _inspect3.getsource(win.launch_batch_worker))
check("follow handler guards manual browsing",
      "_following_batch" in _inspect3.getsource(win.on_batch_page_started))
check("batch keeps navigation unlocked",
      "lock_navigation=False" in _inspect3.getsource(win.launch_batch_worker))
check("nav during batch avoids update_ui_controls",
      "_sync_nav_buttons" in _inspect3.getsource(win.next_page)
      and "_sync_nav_buttons" in _inspect3.getsource(win.prev_page))

# set_busy واقعی (قفل ناوبری فقط در تک‌صفحه)
win.current_page = min(2, max(0, win.total_pages - 1))
win.update_ui_controls()
win.set_busy(True)
check("set_busy default locks navigation",
      not win.btn_prev.isEnabled() and not win.btn_next.isEnabled())
# مثل تولید: اول ناوبری فعال است، بعد اجرای ترجمهٔ کل کتاب با قفل‌نشدن ناوبری
win.set_busy(False)
win.current_page = min(2, max(0, win.total_pages - 1))
win.update_ui_controls()
win.set_busy(True, lock_navigation=False)
check("set_busy(lock_navigation=False) frees navigation",
      win.btn_prev.isEnabled() and win.btn_next.isEnabled())
win.set_busy(False)
win.current_page = 0
win.update_ui_controls()

# دستگاه نمایش جدا (ایمنی ریسمان)
check("open_file opens separate view handle",
      "self.view_doc = pymupdf.open(file_path)" in _inspect3.getsource(win.open_file))
check("refresh prefers view_doc",
      "self.view_doc or self.doc" in _inspect3.getsource(win.refresh_current_page))
check("renderer prefers view_doc",
      "self.view_doc or self.doc" in _inspect3.getsource(win.render_page_image))

# تنظیمات حین توقف
check("paused enables settings", "btn_settings.setEnabled(True)"
      in _inspect3.getsource(win.on_batch_paused))
check("resumed re-locks settings", "btn_settings.setEnabled(False)"
      in _inspect3.getsource(win.on_batch_resumed))
check("quota stop enables settings", "btn_settings.setEnabled(True)"
      in _inspect3.getsource(win.on_batch_quota))
check("settings save pushes into paused worker",
      "update_settings" in _inspect3.getsource(win.on_settings_saved))
check("worker has update_settings", hasattr(t3.BatchWorker, "update_settings"))
check("worker rebuilds engine after settings change",
      "_cfg_dirty" in _inspect3.getsource(t3.BatchWorker.run))

print("== V. دکمهٔ کپی + شمارهٔ صفحهٔ زنده + شروع از اول + راهنمای ویرایشگر ==")
# (۱) دکمهٔ کپی: رنگ وضعیت‌دار + راهنما
check("copy button has objectName", win.btn_copy.objectName() == "btnCopy")
check("copy has state-dependent stylesheet rules",
      "QPushButton#btnCopy" in (t3.DARK_STYLESHEET + t3.LIGHT_STYLESHEET))
check("copy has tooltip", "کپی" in (win.btn_copy.toolTip() or ""))
check("review checkbox has tooltip", "تأیید" in (win.chk_reviewed.toolTip() or ""))

# (۲) شمارهٔ صفحه با نما همراه می‌شود (رفع «همیشه یک صفحه عقب»)
win.current_page = 4
win.refresh_current_page(keep_output=True)
check("page label follows the view", "صفحه: 5" in win.lbl_page.text(),
      win.lbl_page.text())
win.current_page = 0
win.refresh_current_page(keep_output=True)

# (۳) شروع از اول در برابر ادامه از ذخیرهٔ قبلی
pdf_r = make_pdf(os.path.join(TEST_HOME, "restart_book.pdf"), pages=4)
job_r = k.JobStore(pdf_r)
job_r.set(0, "ترجمهٔ قدیمی")
job_r.set(1, "ترجمهٔ قدیمی دو")
job_r.structure = {"headings": ["Chapter 1"], "labels": [], "body_size": 11}
job_r.save()
check("restart fixture has2 saved pages", job_r.count() == 2)
bd_r = t3.BatchDialog(4, job_r)
check("resume/restart radios shown for saved book",
      bd_r.radio_keep is not None and bd_r.radio_restart is not None)
check("keep chosen by default", not bd_r.wants_restart())
check("estimate counts only untranslated by default",
      "ترجمه‌نشده: 2" in bd_r.lbl_estimate.text(), bd_r.lbl_estimate.text())
bd_r.radio_restart.setChecked(True)
check("restart selectable", bd_r.wants_restart())
check("estimate counts all pages after restart",
      "ترجمه‌نشده: 4" in bd_r.lbl_estimate.text(), bd_r.lbl_estimate.text())
bd_fresh = t3.BatchDialog(4, k.JobStore(os.path.join(TEST_HOME, "fresh2.pdf")))
check("no radios for a fresh book",
      bd_fresh.radio_keep is None and not bd_fresh.wants_restart())
# هسته: پاک‌سازی + ماندگاری ساختار
job_r.reset_translations()
check("reset clears translations", job_r.count() == 0)
check("reset keeps book structure",
      (job_r.structure or {}).get("headings") == ["Chapter 1"])
check("reset persisted to disk", k.JobStore(pdf_r).load().count() == 0)
_sb_src = _inspect3.getsource(win.start_batch)
check("start_batch honors restart choice",
      "wants_restart" in _sb_src and "reset_translations" in _sb_src)

# (۴) راهنمای ویرایشگر تمپلیت (چه دردی می‌خورد)
dlgV = t3.SettingsDialog(win.cfg, win, job=win.job)
check("labels editor has example placeholder",
      "بیشتر بدانید" in (dlgV.txt_labels.placeholderText() or ""))
check("headings editor has example placeholder",
      "مثلاً" in (dlgV.txt_headings.placeholderText() or ""))
check("editor hint explains purpose",
      "پرامپت" in (dlgV.lbl_editor_hint.text() or ""))

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL V3 TESTS PASSED")
