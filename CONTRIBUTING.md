# Contributing to Kaman AI Translator

Thanks for helping improve the app. This project is a Persian-first desktop translator, so a few conventions keep everything consistent.

## Development setup

```bash
git clone https://github.com/Mohammad-Hasan-Kaman/kaman-ai-translator.git
cd kaman-ai-translator
pip install -r requirements.txt
python translator_app_v3.py
```

- **Python 3.11+** on Windows (the app uses Windows DPAPI for key encryption).
- Entry point: `translator_app_v3.py` (PyQt6 UI + background workers).
- All logic lives in `kaman_core.py` (no Qt imports) so it can be tested headlessly.

## Before you open a pull request

1. Run the offline suite — it must stay green:
   ```bash
   python tests/test_v3.py
   ```
2. Add tests for whatever you change. The suite uses fake engine objects; no network or API key is required.
3. Keep `README.md` accurate: if you change behavior, update the docs in the same PR.

## Coding conventions

- **English** for all code comments, docstrings, docs and commit messages.
- The UI text is **Persian** and the layout is **100% RTL** — never hard-code left/right positions; rely on the app-wide right-to-left direction.
- Use Persian digits (`fa_number`) when showing numbers to the user.
- No Qt imports inside `kaman_core.py`.
- Do not block the GUI thread: long work belongs in a `QThread` worker with signals.

## Reporting issues

Include:

- OS and Python version (or the executable version you used),
- the engine/provider and model (e.g. Gemini `gemini-2.5-flash`, or “OpenAI-compatible local server”),
- steps to reproduce and the exact error text from the status bar / log.

## Security

- **Never** paste your API key into issues, screenshots, commits or test files.
- Keys are stored encrypted (Windows DPAPI) in the user profile — keep it that way.
- If you find a security issue, open a private security advisory instead of a public issue.

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
