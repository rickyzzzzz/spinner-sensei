---
name: configure
description: Configure Spinner Sensei — change settings (cadence, level, meaning language, display format, append/replace mode, words per batch), generate a vocabulary pool for a new language, add custom words, check learning progress, pause/resume, or rotate the spinner words now. Use whenever the user wants to adjust, inspect, or extend their Spinner Sensei setup.
---

# /spinner-sensei:configure — Tune Spinner Sensei

Configure Spinner Sensei: change settings, generate word pools for new
languages, add custom words, check progress, pause/resume, or rotate now.

Spinner Sensei rotates language-learning flashcards into Claude Code's spinner
verbs on a schedule, at zero token cost. The four enable-time options
(`target_language`, `level`, `meaning_language`, `words_per_batch`) are set when
the plugin is enabled. Everything else — and richer control — lives here.

## Where things live

All runtime state is under the plugin data dir (persistent across updates):

- `${CLAUDE_PLUGIN_DATA}/config.json` — the settings you manage here (highest precedence).
- `${CLAUDE_PLUGIN_DATA}/state.json` — rotation bookkeeping (`last_rotation`, `rotation_count`, `pool_index`, `seen`, `pool_hash`).
- `${CLAUDE_PLUGIN_DATA}/pools/<language>.json` — a generated or user pool for a language (overrides the bundled one).
- `${CLAUDE_PLUGIN_DATA}/pools/custom-<language>.json` — extra words merged on top of the main pool.
- `${CLAUDE_PLUGIN_ROOT}/pools/<language>.json` — the bundled pool (Japanese ships here). Read-only; never write here.
- The runtime script: `${CLAUDE_PLUGIN_ROOT}/scripts/rotate.py`.

`config.json` schema (all keys optional; unset keys fall back to the enable-time
options, then to defaults):

```json
{
  "target_language": "japanese",
  "level": "N5",                 // N5 | N4 | N3 | all
  "meaning_language": "english", // comma-separated, e.g. "english, chinese"
  "words_per_batch": 20,         // 1–60
  "cadence_days": 7,             // 1 = daily, 7 = weekly
  "display_format": "full",      // full | recognition | no_romaji
  "spinner_mode": "append",      // append | replace
  "review_ratio": 0.2,           // 0.0–0.9 fraction resampled from seen words
  "paused": false
}
```

`display_format`: `full` = `勉強 (benkyō) — study · 学习`; `recognition` =
`勉強 (benkyō)`; `no_romaji` = `勉強 — study`.

## How to apply a change (do this after every write)

1. Read the current `${CLAUDE_PLUGIN_DATA}/config.json` (may not exist yet — treat as `{}`).
2. Merge the requested change and write it back (valid JSON, UTF-8).
3. Apply immediately by force-rotating:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rotate.py" --force`
4. Confirm what changed and show the new effective batch (read `spinnerVerbs`
   from the user's `~/.claude/settings.json`).

`--force` bypasses the cadence gate and the pause flag, so the change is visible
on the next spinner immediately.

## Behaviors

### Show current settings
Read and summarize `config.json`, `state.json`, and the enable-time options
(exported as `CLAUDE_PLUGIN_OPTION_TARGET_LANGUAGE`, `..._LEVEL`,
`..._MEANING_LANGUAGE`, `..._WORDS_PER_BATCH`). Show the effective value of each
setting and note where it comes from (config.json > enable-time > default).

### Change a setting
Any key in the schema above. Validate ranges (`words_per_batch` 1–60,
`review_ratio` 0.0–0.9, `level` in N5/N4/N3/all, `display_format` and
`spinner_mode` in their enums). Write config.json, then force-rotate.

### Generate a pool for a new language
The bundled pool covers Japanese only. For any other language the user wants,
author `${CLAUDE_PLUGIN_DATA}/pools/<language>.json` yourself as a JSON array of
entries in this structured format:

```json
[{"w": "hablar", "r": "", "en": "to speak", "zh": "说", "level": "A1"}]
```

- `w` = the word/phrase in the target language; `r` = reading/romanization
  (leave `""` if not applicable, e.g. Spanish); include a meaning key for each
  of the user's configured `meaning_language`s (`en` for english, `zh` for
  chinese); `level` = a difficulty tag (use the language's own scale, or `A1`/`A2`/`B1`, or just `all`).
- Author ~300+ good entries, most-common words first. Correctness matters — this
  teaches people. Double-check readings and meanings.
- Then set `target_language` to that language in config.json and force-rotate.

### Add custom words
Given a pasted list or a file (e.g. an Anki export), convert to the structured
format and write/append to
`${CLAUDE_PLUGIN_DATA}/pools/custom-<language>.json` (a JSON array). These merge
on top of the main pool. Force-rotate to surface them.

### Progress / stats
From `state.json`: `pool_index` and `seen` (how many distinct words shown),
`rotation_count`, `last_rotation`. Estimate pool exhaustion: remaining unseen
words ÷ (`words_per_batch` × (1 − `review_ratio`)) × `cadence_days` = days until
you've seen the whole pool.

### Rotate now
Just run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rotate.py" --force`.

### Pause / resume
Pause: set `"paused": true` in config.json (rotate.py then exits early on
SessionStart; the current spinner words stay frozen). Resume: set
`"paused": false` and force-rotate.

### Uninstall cleanup
Uninstalling the plugin deletes `${CLAUDE_PLUGIN_DATA}` but cannot edit
`settings.json`. Tell the user to remove the leftover `spinnerVerbs` key from
`~/.claude/settings.json` themselves (or you may edit it for them, touching only
that key) so Claude Code returns to its default spinner.
