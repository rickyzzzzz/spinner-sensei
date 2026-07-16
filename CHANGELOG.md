# Changelog

All notable changes to Spinner Sensei are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] — 2026-07-15

### Changed
- `with_example` now includes the word's own meaning gloss before the example
  sentence, so you get both the standalone definition and it in context
  (`勉強 (benkyō) — study · 学习 · 毎日勉強します (mainichi benkyō shimasu) I study every day`).
  Previously the standalone gloss was dropped and only the sentence translation
  carried the meaning.

## [1.1.0] — 2026-07-15

### Added
- `with_example` display format — shows a word alongside an example sentence
  with its reading and translation
  (`勉強 (benkyō) · 毎日勉強します (mainichi benkyō shimasu) I study every day`).
  Opt-in via `/spinner-sensei:configure`; the default `full` format is unchanged.
- Optional pool schema fields `ex` / `exr` / `ex_en` / `ex_zh` (example sentence,
  its reading, and per-language translations). Entries without an example fall
  back to the `full` rendering.
- Full example-sentence backfill of the bundled Japanese pool (all ~461 entries).

## [1.0.0] — 2026-07-12

### Added
- Initial release.
- `SessionStart` hook that rotates a batch of vocabulary words into Claude Code's
  `spinnerVerbs` setting on a configurable cadence — zero token cost.
- Bundled Japanese pool (~450 entries) tagged by JLPT level (N5/N4/N3), each with
  English and Chinese (simplified) meanings and macron rōmaji.
- Four enable-time settings: `target_language`, `level`, `meaning_language`,
  `words_per_batch`.
- `/spinner-sensei:configure` skill for richer settings (cadence, display format,
  append/replace mode, review ratio), pool generation for new languages, custom
  word lists, progress stats, pause/resume, and rotate-now.
- Sequential no-repeat word walk with a configurable review ratio that resurfaces
  previously-seen words.
- Atomic single-key write to `settings.json` (touches only `spinnerVerbs`).
