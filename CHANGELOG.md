# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
