# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2026-11-01

### Added

- Arabic as a translation language: all directions among English, Persian
  and Arabic (en⇄ar, fa⇄ar) with academic system prompts and native
  output labels.
- Bilingual interface (Persian / English) with automatic RTL/LTR layout,
  switchable in Settings.
- Per-engine settings memory: base URL, API key and model are stored
  separately for Gemini and for OpenAI-compatible servers, and restored
  when switching back.
- Local-server guidance inside Settings (recommended models and the
  Ollama context-window note) for OpenAI-compatible engines.
- Test Connection now also verifies structured (JSON) output — what book
  translation actually needs — and warns about small local context windows.

### Changed

- The "model output could not be parsed" error now explains the likely
  causes (a model too weak for structured output, or a truncated reply)
  and the concrete fix for each.

### Fixed

- Settings dialog could grow taller than the screen and slide under the
  Windows taskbar; it is now height-capped with a scrollable body and
  always-visible action buttons.
- Switching engines no longer leaks one engine's model, API key or base
  URL into the other engine's fields.
- Truncated model replies (finish_reason "length") are now detected and
  reported as a context-size problem instead of a generic parse error.
- HTML export now follows the target language's direction (LTR for
  English targets) instead of always rendering RTL.
- A batch-killing crash when a model returned JSON fields as arrays or
  numbers instead of strings.
- A startup crash when the stored API key could not be decrypted (e.g.
  the config was copied from another Windows account); the key is now
  treated as empty instead of aborting the launch.
- The AI structure pass could write one book's template into another
  book's job when a second file was opened while it was running.
- Job files silently reused translations after the source file was
  replaced at the same path; a size/mtime fingerprint now starts a fresh
  job and keeps the old one as a `.bak`.
- Scanned pages returned their entire translation as the next page's
  context (now capped like text pages), and truly blank pages (e.g.
  chapter separators) were sent as paid image-translation requests.
- The QC pass could silently replace a page with a much shorter
  "correction"; the acceptance floor is now half the original length.
- Duplicate headings in the auto structure template (dedupe compared the
  raw text but stored the cleaned one).
- Exports raced a running translation; Save is now disabled while busy
  and Markdown/HTML guard against active workers.
- A document/job desync and file-handle leak when reopening files.
- Config writes were not atomic (a crash mid-write could wipe the API
  key); a corrupt config is now preserved as `.corrupt.bak`.
- Gemini transport errors and local-server connection failures bypassed
  the retry logic.
- The "delay between requests" setting only applied between pages; it
  now also applies between the chunks of a page.
- The settings template editor could not clear a book's template.
- Closing the window during a translation now cancels the workers and
  waits briefly for a clean shutdown.
- Light theme colors in Settings now keep helper text and section headings
  readable against the light background.
- Changing the app language now updates the main window immediately and
  preserves the open book and current translation view.
- `pydantic` is an explicit Gemini dependency and missing-install errors now
  explain how to install the project requirements.
- Frozen Windows builds preload the system ICU DLLs before the first Qt import,
  preventing unrelated ICU copies on `PATH` from breaking Qt startup.

## [3.0.0] - 2026-10-10

### Changed

- Complete rewrite: the single-page translator became a full book-translation
  studio. Every line of code was rewritten and no v2 module was kept.
- Translation is now bidirectional — English ⇄ Persian.
- Whole-book automation and a quality pipeline for long documents.
- Encrypted in-app settings, and a fully RTL Persian interface.

### Added

- Encryption for stored settings, with the fallback reason written to
  `encrypt_fallback.log`.
- A button that opens the exact local data folder from Settings.

### Fixed

- Corrected the stale test-count badge and the English Quick start section.
- Removed the unused duplicate `icon..ico` asset.

## [2.0.0] - 2026-07-04

### Added

- Initial release: desktop translation of PDF and EPUB documents from English
  into academic Persian, using Google Gemini AI.
