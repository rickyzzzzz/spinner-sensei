#!/usr/bin/env python3
"""Spinner Sensei — rotate vocabulary flashcards into Claude Code's spinnerVerbs.

Runs from the plugin's SessionStart hook (and from /spinner-sensei:configure via
--force). Stdlib only. This is the entire runtime.

It never crashes a session: any unexpected condition results in a clean exit 0.
It touches exactly one key in settings.json — `spinnerVerbs` — and writes it
atomically. If settings.json is malformed, it is left untouched.

Environment:
  CLAUDE_PLUGIN_ROOT   plugin install dir (bundled pools live here). Ephemeral.
  CLAUDE_PLUGIN_DATA   persistent data dir (config/state/generated pools).
  SPINNER_SENSEI_SETTINGS  test-only override for the settings.json path.
"""

import hashlib
import json
import math
import os
import pathlib
import random
import sys
import tempfile
from datetime import date, datetime

# ---- defaults (lowest precedence) -----------------------------------------

DEFAULTS = {
    "target_language": "japanese",
    "level": "N5",
    "meaning_language": "english",
    "words_per_batch": 20,
    "cadence_days": 7,
    "display_format": "full",
    "spinner_mode": "append",
    "review_ratio": 0.2,
    "paused": False,
}

MEANING_KEYS = {"english": "en", "chinese": "zh"}


def emit(system_message):
    """Print a SessionStart JSON payload with a user-visible systemMessage."""
    print(json.dumps({"systemMessage": system_message}, ensure_ascii=False))


def load_json(path, fallback):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback
    except (ValueError, OSError):
        return None  # signal "present but unreadable"


def coerce_number(value, default):
    try:
        n = float(value)
        return int(n) if n == int(n) else n
    except (TypeError, ValueError):
        return default


def resolve_config(data_dir):
    """Precedence: config.json > CLAUDE_PLUGIN_OPTION_* env > DEFAULTS."""
    cfg = dict(DEFAULTS)

    # env layer (from userConfig)
    for key in DEFAULTS:
        env_val = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key.upper())
        if env_val is not None and env_val != "":
            cfg[key] = env_val

    # config.json layer (highest)
    file_cfg = load_json(data_dir / "config.json", {})
    if isinstance(file_cfg, dict):
        for key, value in file_cfg.items():
            cfg[key] = value

    # type coercion
    cfg["words_per_batch"] = max(1, coerce_number(cfg.get("words_per_batch"), 20))
    cfg["cadence_days"] = max(0, coerce_number(cfg.get("cadence_days"), 7))
    try:
        cfg["review_ratio"] = float(cfg.get("review_ratio"))
    except (TypeError, ValueError):
        cfg["review_ratio"] = 0.2
    cfg["review_ratio"] = min(max(cfg["review_ratio"], 0.0), 0.9)
    cfg["paused"] = str(cfg.get("paused")).lower() in ("1", "true", "yes")

    # meaning languages -> ordered list
    langs = [p.strip().lower() for p in str(cfg["meaning_language"]).split(",")]
    cfg["_meaning_list"] = [l for l in langs if l]
    return cfg


def resolve_pool(root_dir, data_dir, language):
    """DATA/pools/<lang>.json (or bundled ROOT) + optional custom-<lang>.json."""
    language = str(language).lower()
    primary = None
    for base in (data_dir, root_dir):
        candidate = base / "pools" / (language + ".json")
        loaded = load_json(candidate, None) if candidate else None
        if isinstance(loaded, list) and loaded:
            primary = loaded
            break
    if primary is None:
        primary = []

    custom = load_json(data_dir / "pools" / ("custom-" + language + ".json"), [])
    if isinstance(custom, list):
        primary = primary + custom
    return primary


def filter_by_level(pool, level):
    level = str(level).lower()
    if level in ("all", "", "none"):
        return list(pool)
    filtered = [e for e in pool if str(e.get("level", "")).lower() == level]
    return filtered if filtered else list(pool)  # never leave an empty working set


def format_entry(entry, meaning_list, display_format):
    word = entry.get("w", "")
    reading = entry.get("r", "")
    head = f"{word} ({reading})" if reading else word

    meanings = []
    for lang in meaning_list:
        key = MEANING_KEYS.get(lang)
        if key and entry.get(key):
            meanings.append(entry[key])
    if not meanings:  # fall back to whatever meaning exists
        for key in ("en", "zh"):
            if entry.get(key):
                meanings.append(entry[key])
                break
    meaning_str = " · ".join(meanings)

    if display_format == "with_example" and entry.get("ex"):
        ex = entry["ex"]
        exr = entry.get("exr", "")
        ex_glosses = []
        for lang in meaning_list:
            key = MEANING_KEYS.get(lang)
            if key and entry.get("ex_" + key):
                ex_glosses.append(entry["ex_" + key])
        if not ex_glosses:  # fall back to whatever example gloss exists
            for key in ("en", "zh"):
                if entry.get("ex_" + key):
                    ex_glosses.append(entry["ex_" + key])
                    break
        sentence = f"{ex} ({exr})" if exr else ex
        ex_gloss = " · ".join(ex_glosses)
        if ex_gloss:
            sentence = f"{sentence} {ex_gloss}"
        head_with_meaning = f"{head} — {meaning_str}" if meaning_str else head
        return f"{head_with_meaning} · {sentence}"

    if display_format == "recognition":
        return head
    if display_format == "no_romaji":
        base = word if word else head
        return f"{base} — {meaning_str}" if meaning_str else base
    # full (and with_example fall-through when the entry has no example)
    return f"{head} — {meaning_str}" if meaning_str else head


def pool_hash(pool, level):
    payload = json.dumps([pool, level], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_batch(pool, state, batch_size, review_ratio):
    """Sequential no-repeat walk + deterministic review resampling.

    Returns (indices, new_pool_index, updated_seen).
    """
    n = len(pool)
    batch_size = min(batch_size, n)
    pool_index = state.get("pool_index", 0) % n if n else 0
    seen = [i for i in state.get("seen", []) if 0 <= i < n]
    seen_set = set(seen)

    prior_seen = list(seen)  # words known *before* this rotation
    review_count = int(math.floor(review_ratio * batch_size))
    review_count = min(review_count, len(prior_seen), max(batch_size - 1, 0))
    new_count = batch_size - review_count

    # sequential new words
    new_indices = []
    idx = pool_index
    guard = 0
    while len(new_indices) < new_count and guard < n:
        if idx not in new_indices:
            new_indices.append(idx)
        idx = (idx + 1) % n
        guard += 1
    new_pool_index = idx

    for i in new_indices:
        if i not in seen_set:
            seen.append(i)
            seen_set.add(i)

    # deterministic review picks from prior_seen (exclude this batch's new ones)
    review_pool = [i for i in prior_seen if i not in set(new_indices)]
    rng = random.Random(state.get("rotation_count", 0))
    if review_count > 0 and review_pool:
        review_indices = rng.sample(review_pool, min(review_count, len(review_pool)))
    else:
        review_indices = []

    # top up if review pool was too small
    shortfall = batch_size - len(new_indices) - len(review_indices)
    while shortfall > 0 and len(new_indices) + len(review_indices) < n:
        if idx not in new_indices and idx not in review_indices:
            new_indices.append(idx)
            if idx not in seen_set:
                seen.append(idx)
                seen_set.add(idx)
        idx = (idx + 1) % n
        new_pool_index = idx
        shortfall -= 1

    ordered = new_indices + review_indices
    return ordered, new_pool_index, seen


def write_settings_atomic(settings_path, verbs, mode):
    settings_path = pathlib.Path(settings_path)
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False  # malformed — never destroy the user's settings
        if not isinstance(settings, dict):
            return False
    else:
        settings = {}

    settings["spinnerVerbs"] = {"mode": mode, "verbs": verbs}

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(settings_path.parent), prefix=".spinner-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, settings_path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


def settings_has_spinner(settings_path):
    settings = load_json(settings_path, {})
    if settings is None:  # malformed
        return None
    return isinstance(settings, dict) and "spinnerVerbs" in settings


def days_between(iso_date):
    try:
        then = datetime.fromisoformat(iso_date).date()
    except (TypeError, ValueError):
        return None
    return (date.today() - then).days


def main():
    force = "--force" in sys.argv[1:]

    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        return 0  # not enough context to do anything safely
    root_dir = pathlib.Path(root) if root else None
    data_dir = pathlib.Path(data)
    data_dir.mkdir(parents=True, exist_ok=True)

    settings_path = os.environ.get("SPINNER_SENSEI_SETTINGS") or str(
        pathlib.Path.home() / ".claude" / "settings.json"
    )

    cfg = resolve_config(data_dir)
    if cfg["paused"] and not force:
        return 0

    state = load_json(data_dir / "state.json", {}) or {}
    language = str(cfg["target_language"]).lower()

    pool = resolve_pool(root_dir, data_dir, language)
    if not pool:
        # nag at most once per cadence window
        last_nag = state.get("last_nag")
        gap = days_between(last_nag) if last_nag else None
        if force or gap is None or gap >= max(cfg["cadence_days"], 1):
            emit(
                f"Spinner Sensei: no {language} word pool yet — run "
                f"/spinner-sensei:configure to generate one."
            )
            state["last_nag"] = date.today().isoformat()
            _save_state(data_dir, state)
        return 0

    pool = filter_by_level(pool, cfg["level"])
    cur_hash = pool_hash(pool, str(cfg["level"]).lower())

    # reset the walk if the effective pool changed
    if state.get("pool_hash") != cur_hash:
        state["pool_index"] = 0
        state["seen"] = []
        state["pool_hash"] = cur_hash

    # settings state / cadence gate
    has_spinner = settings_has_spinner(settings_path)
    if has_spinner is None:
        return 0  # malformed settings — leave untouched

    should_rotate = force or not has_spinner
    if not should_rotate:
        last = state.get("last_rotation")
        if last is None:
            should_rotate = True
        else:
            gap = days_between(last)
            should_rotate = gap is None or gap >= cfg["cadence_days"]
    if not should_rotate:
        return 0

    indices, new_index, seen = select_batch(
        pool, state, int(cfg["words_per_batch"]), cfg["review_ratio"]
    )
    verbs = [
        format_entry(pool[i], cfg["_meaning_list"], cfg["display_format"])
        for i in indices
    ]
    if not verbs:
        return 0

    if not write_settings_atomic(settings_path, verbs, str(cfg["spinner_mode"])):
        return 0

    state["pool_index"] = new_index
    state["seen"] = seen
    state["pool_hash"] = cur_hash
    state["last_rotation"] = date.today().isoformat()
    state["rotation_count"] = int(state.get("rotation_count", 0)) + 1
    state["language"] = language
    _save_state(data_dir, state)

    emit(f"🈴 Spinner Sensei: {len(verbs)} fresh {language} words this rotation")
    return 0


def _save_state(data_dir, state):
    path = data_dir / "state.json"
    fd, tmp = tempfile.mkstemp(dir=str(data_dir), prefix=".state-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never crash a session, whatever happens.
        sys.exit(0)
