# Contributing to Kaman AI Translator

Thanks for investing your time in this project — contributions of any size are welcome and credited.

This is a **Persian-first desktop application**: the UI speaks Persian and is fully right-to-left, while all code, documentation and communication happen in English. A few conventions keep that duality clean.

---

## Table of contents

- [Ways to help](#ways-to-help)
- [Development setup](#development-setup)
- [Architecture at a glance](#architecture-at-a-glance)
- [Before you open a pull request](#before-you-open-a-pull-request)
- [Coding conventions](#coding-conventions)
- [RTL & Persian UI rules](#rtl--persian-ui-rules)
- [Commit & pull request guidelines](#commit--pull-request-guidelines)
- [Reporting issues](#reporting-issues)
- [Security](#security)
- [License](#license)

---

## Ways to help

- 🐛 Report bugs and rough edges (especially with PDF/EPUB layouts that break extraction)
- 🌍 Improve Persian wording, or help port the interface to other languages
- 🧪 Extend the offline test-suite
- ✨ Ship features from the [roadmap](README.md#roadmap)
- 📖 Improve documentation and examples

---

## Development setup

```bash
git clone https://github.com/Mohammad-Hasan-Kaman/kaman-ai-translator.git
cd kaman-ai-translator
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python translator_app_v3.py
```

Requirements:

- **Windows + Python 3.11+** (key encryption uses Windows DPAPI).
- No API key is needed to develop or test — the suite runs on fake engines.

---

## Architecture at a glance

| Layer | File | Rule |
|---|---|---|
| UI & workers | `translator_app_v3.py` | PyQt6, RTL, `QThread` workers with signals — never block the GUI thread |
| Core | `kaman_core.py` | **No Qt imports.** Config + DPAPI encryption, prompts, chunking, structure analysis, engines, job store, exporters — fully testable headlessly |
| Tests | `tests/test_v3.py` | Offline suite (fake engines, temporary profiles) |

Long operations (translation, structure analysis, exports) always run in a worker thread; the UI only reacts to signals.

---

## Before you open a pull request

1. **Run the suite — it must stay green:**
   ```bash
   python tests/test_v3.py
   ```
   Expected tail: `ALL V3 TESTS PASSED` (294 checks).
2. **Add tests for whatever you change.** New behavior without a test will usually be asked for one.
3. **Update the docs in the same PR** if you change behavior (`README.md` features/settings tables).
4. Keep the executable build working:
   ```bash
   pyinstaller --noconfirm --onefile --windowed --icon icon.ico --add-data "icon.png;." translator_app_v3.py
   ```

---

## Coding conventions

- **English** everywhere in code: comments, docstrings, identifiers, commit messages, docs.
- **No Qt in `kaman_core.py`** — that separation is what makes the pipeline testable.
- Threads: background work lives in a `QThread` subclass emitting signals; never touch widgets from a worker.
- Errors shown to the user are **Persian** and actionable; technical detail goes to the status bar/log, never with secrets.
- Prefer small, focused modules of logic inside `kaman_core.py` over growing the UI file.
- Dependencies: think twice before adding one; the executable size is a feature.

---

## RTL & Persian UI rules

- The application sets **one app-wide right-to-left direction** — never hard-code left/right geometry; rely on the layout direction so mirroring stays automatic.
- Never call `setDirection()` on individual layouts (it breaks inheritance and can flip boxes back to LTR).
- Show numbers to users with **Persian digits** (`fa_number`).
- Every user-facing control gets a **tooltip** explaining *when* to use it, and a visible enabled/disabled state.
- Persian text in outputs uses the formal academic register; keep wording consistent with the rest of the UI.

---

## Commit & pull request guidelines

- **Commit messages:** English, imperative, scoped — `Fix: resume keeps reviewed marks`, `Docs: document build flags`.
- **One topic per PR.** Mixed refactors and features are hard to review.
- **PR description:** what changed, why, and how you verified it (test output, screenshots of the RTL UI are gold).
- Reference issues with `Fixes #123` when applicable.
- Releases are cut from `main`; keep it always releasable.

---

## Reporting issues

Include:

- OS and Python version (or the exact executable version),
- engine/provider and model (e.g. Gemini `gemini-2.5-flash`, or “OpenAI-compatible local server”),
- a **minimal PDF/EPUB sample** that reproduces extraction problems (sanitized, no personal content),
- steps to reproduce and the exact error text from the status bar.

Feature ideas are welcome too — please describe the *problem* you are solving, not only the solution.

---

## Security

- **Never** paste API keys into issues, screenshots, commits, tests or logs.
- Keys are stored encrypted (Windows DPAPI) in the user profile — keep it that way.
- Found a vulnerability? Please use a **private security advisory** instead of a public issue.

---

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE), the same license as the project.
