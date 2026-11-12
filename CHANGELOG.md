# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.3] - 2026-11-12

### Fixed

- OpenAI-compatible model discovery no longer takes the first advertised
  model blindly when a server reports capability metadata: on a
  multi-purpose gateway that lists embedding, speech or image models
  first, the translator could pick a non-chat model and fail
  mid-translation with a confusing error. Discovery now selects the first
  explicitly chat-capable model, and when no entry can be identified as
  chat-capable it stops with a clear message (English/Persian) asking for
  the exact model ID in **Settings -> Model** instead.
  (Report and implementation contributed by @yibeibingmrishi in #1 / #2.)

### Changed

- Model discovery policy: explicit chat-capability metadata decides when
  a catalog carries any. Catalogs with no capability metadata at all -
  the norm for local servers such as Ollama and LM Studio - keep the
  historical behavior of selecting the first advertised model, so local
  setups with a blank Model field work exactly as before.

## [3.2.2] - 2026-11-11

### Fixed

- The status bar no longer stays on screen forever: it appears while a
  translation (or a short feedback message such as "Copied") needs it and
  hides itself a few seconds after the app goes idle. A paused batch
  keeps it visible, since the resume/cancel buttons live in that bar.

## [3.2.1] - 2026-11-11

### Fixed

- UI language switching is now complete in both directions: the hint under
  the language selectors and the progress percent follow the UI language,
  and every engine error message (Gemini quota / API / safety-guard /
  no-response, local-server quota / HTTP / connection failures, model
  discovery, saved-key decryption) is written in the selected UI language
  instead of hardcoded Persian.
- Light theme readability: stronger borders, darker secondary labels and
  hints, and disabled controls that stay legible instead of washed out.
- The Copy button now confirms visibly: the status bar appears with a
  "Copied" message and the button itself shows "Copied" for a moment, so
  there is no need to click repeatedly to be sure.
- HTML export is a single self-contained file: page images are embedded
  in the HTML (compressed JPEG) instead of a separate `images/` folder
  that broke as soon as the file was moved or sent on its own.
- Export headings and page labels (TXT / Markdown / HTML) now follow the
  translation's target language rather than always being Persian.
- Save failures are no longer silent: all three export actions report
  write errors in a dialog, the current-page TXT export has the same
  busy guard as the other exports, and HTML export creates the output
  folder when it does not exist yet.

## [3.2.0] - 2026-11-10

### Changed

- Complete visual redesign of the interface in a quiet paper-and-ink
  language: flat surfaces with hairline rules instead of filled cards,
  one restrained accent colour, and neutral controls throughout.
- Reading panes now use a serif typeface for long-form book text.
- Action labels no longer carry emoji; the interface reads as a tool,
  not a chat window.
- No changes to translation logic, engines, formats or settings:
  this release is presentation only.

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
- A fresh installation starts in Persian and follows the Windows system theme;
  light mode now paints the complete Settings content and scroll viewport.
- Leaving the model field blank on an OpenAI-compatible server now discovers
  its first advertised model through `/models`. Gemini keeps its default model.
- Arabic translation prompts now explicitly require Modern Standard Arabic and
  prevent unintended Persian or dialect mixing.
- Gemini errors now explain invalid keys, unavailable model IDs, and location
  or regional access restrictions in clear language.
- Gemini connection settings now accept an optional Gemini-native API gateway
  and an HTTP(S) network proxy; the Google SDK's system `HTTPS_PROXY` support
  also works. Temporary 500/502/503/504 and transport failures receive
  bounded exponential retries and a 90-second request timeout.
- The Gemini default is updated to `gemini-3.8-flash`; existing settings that
  still contain the app's former `gemini-2.5-flash` default migrate automatically.
- Gemini 3.6+ requests leave temperature at Google's recommended default, and
  partial `MAX_TOKENS` responses are rejected as truncated instead of saved.
- Book translations and context tails are now stored per language direction.
  Old jobs without language metadata are preserved and retranslated safely.
- EPUB cover images embedded as XHTML image blocks are now detected and sent
  through scanned-page translation instead of being silently skipped.

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
