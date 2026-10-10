# Kaman AI Translator

**A Persian-first desktop app that translates PDF & EPUB books and papers into fluent, academic Persian (and Persian → English) — one page or an entire book, fully automated.**

![version](https://img.shields.io/badge/version-3.0.0-blue)
![python](https://img.shields.io/badge/python-3.11%2B-orange)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-294%20offline%20checks-brightgreen)

> **v3.0.0 is a complete rewrite** of the original single-page app: whole-book automation, a quality-engine for long documents, an in-app settings system with encrypted API keys, and a 100% RTL Persian interface. See the [release notes](../../releases) for the full changelog.

---

## Highlights

### 📚 Whole-book automation
- Translate an **entire book or a page range** with one click; every finished page is saved instantly.
- **Pause / Resume / Cancel** at any time — nothing is lost.
- The view **follows the worker live**, showing each page as it is being translated, while page navigation stays fully unlocked.
- **Resume or restart:** when saved pages exist, the dialog asks whether to continue from the first unfinished page or re-translate everything from scratch.
- Editing ⚙️ Settings is allowed **while paused** (and after a quota stop) — changes apply from the very next page.
- Optional **request delay** to stay under rate limits.

### 🧠 Quality engine (built for long, real books)
- **Smart automatic chunking** at paragraph boundaries with a **rolling context tail**, so chapter-long text stays consistent from the first page to the last.
- **Book-specific structure template:** font hierarchy, chapter headings and recurring section labels (e.g. “Did you know?”, “Activities”) are detected per book and injected into the prompt so every label is translated *the same way* throughout the book. Three independent switches in Settings: auto-analyze on open (free, local), an optional **AI deep pass** (one API request), and a **manual template editor**.
- **High-accuracy page reading:** repeated running headers / page numbers are detected and excluded from the text sent to the model; hyphen-broken words (`exam-` + `ple`) are rejoined; list numbers and mid-text formulas are protected.
- **Prompts enforce completeness:** never omit, never summarize — structure, numbers, citations (`[12]`) and equations are preserved, with one consistent term per concept.
- **Automatic QC review loop** (optional, doubles API cost): the model compares each translation against the source, flags meaning drift and omissions, and returns a corrected translation.
- **Scanned pages** are translated through image-based OCR instead of being skipped.

### 🔁 Two-way translation
- A dedicated language bar with explicit *Source* and *Target* selectors (English ⇄ Persian). Changing either one flips the other automatically; the choice is remembered across sessions.

### 🔌 Any engine you want
- **Google Gemini** (official SDK), or
- **Any OpenAI-compatible endpoint** — local servers (Ollama, LM Studio, …) or cloud aggregators.
- Built-in **connection test**, retry-on-broken-JSON, and automatic fallback if the model replies with raw JSON instead of prose.
- The API key is entered once in the app and stored **encrypted with Windows DPAPI** — it never appears in code, in the repository, or on disk in plain text.

### 💾 Save & export
- Each translated page is auto-saved to a per-file job (resume works across restarts).
- Export the current page (**TXT**), the whole book (**Markdown**), or a complete **RTL HTML book with page images** (open in a browser → Print → Save as PDF).
- Per-page **“Reviewed ✓”** human-approval checkbox with live statistics (translated vs. reviewed).

### 🇮🇷 Persian-first, 100% RTL interface
- The whole UI is right-to-left with Persian numerals; themes: **System / Dark / Light**.

---

## Install

### Option A — Windows executable (recommended)
1. Download `kaman-ai-translator-3.0.0.exe` from the [Releases](../../releases) page.
2. Run it — no Python required.

### Option B — Run from source
```bash
git clone https://github.com/Mohammad-Hasan-Kaman/kaman-ai-translator.git
cd kaman-ai-translator
pip install -r requirements.txt
python translator_app_v3.py
```

---

## Getting started

1. **⚙️ Settings** → choose the engine (Gemini or OpenAI-compatible), paste your API key, set the model name, press **Test connection**.
2. **📂 انتخاب کتاب** → open a PDF or EPUB.
3. Use **ترجمهٔ این صفحه** for a single page, or **ترجمهٔ کل کتاب** for the whole book:
   - pick the range,
   - keep *analyze book structure* on (free, local),
   - enable the *QC review loop* if you want higher quality at double cost,
   - set a delay if your provider rate-limits you,
   - choose **continue** or **re-translate from scratch** when saved pages exist.
4. During a run: **⏸ توقف** pauses (Settings becomes editable), **■ لغو** cancels safely; the page being translated is shown automatically, but you can browse freely.
5. When a page finishes, read it, tick **✓ بازبینی شد** if you approve it, then **📋 کپی** or export the book.

### Settings reference
| Setting | What it does |
|---|---|
| Engine / Base URL / Model / API key | Your translation provider. The key is encrypted with Windows DPAPI and stored only in your `%APPDATA%\kaman-ai-translator\`. |
| Theme | System (follows Windows) / Dark / Light |
| *Auto-analyze structure on file open* | Free, fully local detection of headings and recurring labels of the opened book. |
| *AI deep structure pass* | One extra API request that reads the table of contents and extracts headings/labels/summary. |
| *Show Template editor* | Two text areas (headings / recurring labels, one item per line) saved **per open book** — they steer term consistency in the prompt. |
| Chunk size / context tail / delay | Advanced batching parameters of the translation pipeline. |

---

## How the translation stays accurate

```
PDF/EPUB page
   └─ extraction (reading order, de-hyphenation, header/footer removal)
        └─ smart chunking at paragraph boundaries
             └─ per chunk: prompt = source + rolling context + book template
                  └─ response parsed (JSON-safe, raw-JSON fallback)
                       └─ optional QC pass vs. the source
                            └─ page saved → resume-safe job store
```

The API is called **only** for the text of the page itself — headers, page numbers and duplicates never reach the model.

---

## Data & privacy

- Your API key, settings, translations and review marks live **only on your machine**, in `%APPDATA%\kaman-ai-translator\` (the key is encrypted with Windows DPAPI).
- There is **no telemetry** and no server of ours: the only network traffic goes from your computer **to the provider you configured**.
- Nothing personal is bundled into the source code, the releases, or the Windows executable.

---

## Project layout

```
kaman-ai-translator/
├── translator_app_v3.py   # PyQt6 UI & background workers (entry point)
├── kaman_core.py          # Core logic: config + encryption, prompts, chunking,
│                          # structure analysis, engines, jobs, exports (no Qt)
├── tests/test_v3.py       # Offline test-suite (294 checks; no network needed)
├── icon.png / icon..ico   # App icons
├── requirements.txt
├── LICENSE                # MIT
└── CONTRIBUTING.md
```

## Running the tests

The suite is fully offline (fake engines, temporary profiles):

```bash
python tests/test_v3.py
# expected: ALL V3 TESTS PASSED
```

It covers prompts, chunking, structure detection, resume jobs, RTL geometry, the batch UI state machine and the export pipeline.

## Building the Windows executable

```bash
pip install auto-py-to-exe
auto-py-to-exe -nu -o dist -i icon..ico -n kaman-ai-translator-3.0.0 -w --onefile translator_app_v3.py
```

---

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © Mohammad Hasan Kaman.
