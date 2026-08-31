"""Random theme rotation — daily and hourly cadences.

Selects a theme from the eligible pool once per day (or once per hour) and
persists the choice so that every dashboard refresh within the same time bucket
uses the same theme.

The eligible pool is derived from ``AVAILABLE_THEMES`` minus pseudo-themes and
utility views, then filtered by the user's ``include`` / ``exclude`` lists:

- If *include* is non-empty, only those themes are candidates.
- Any theme in *exclude* is removed from the pool.
- *include* is applied first, then *exclude*.

Daily state is written to ``<output_dir>/random_theme_state.json``:
    {"date": "2026-03-22", "theme": "terminal"}

Hourly state is written to ``<output_dir>/random_theme_hourly_state.json``:
    {"hour": "2026-03-22T14", "theme": "minimalist"}

A new theme is picked whenever the stored bucket key differs from the current one,
which naturally rotates the theme at the start of each new day or hour.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime
from pathlib import Path

from src._io import atomic_write_json
from src.render.theme import AVAILABLE_THEMES

logger = logging.getLogger(__name__)

_DAILY_STATE_FILE = "random_theme_state.json"
_HOURLY_STATE_FILE = "random_theme_hourly_state.json"
# Pseudo-themes and utility views that must never appear in a rotation pool.
_EXCLUDED_FROM_POOL: frozenset[str] = frozenset(
    {"random", "random_daily", "random_hourly", "diags", "message", "photo", "countdown"}
)


def eligible_themes(include: list[str], exclude: list[str]) -> list[str]:
    """Return sorted list of theme names eligible for random selection.

    Args:
        include: If non-empty, only themes in this list are considered.
                 An empty list means *all* real themes are candidates.
        exclude: Themes to remove from the pool.

    Returns:
        Sorted list of eligible theme names (may be empty).
    """
    pool: set[str] = set(AVAILABLE_THEMES - _EXCLUDED_FROM_POOL)
    if include:
        pool = pool & set(include)
    if exclude:
        pool = pool - set(exclude)
    return sorted(pool)


def pick_random_theme(
    include: list[str],
    exclude: list[str],
    output_dir: str,
    today: date | None = None,
    persist: bool = True,
) -> str:
    """Return the theme chosen for *today*, persisting the selection across runs.

    If a theme was already chosen for today it is reused; otherwise a new one
    is drawn from the eligible pool and written to the state file.

    Falls back to ``"default"`` when the eligible pool is empty.

    Args:
        include: Allowlist of theme names (empty = all themes).
        exclude: Denylist of theme names.
        output_dir: Directory where the state file is stored.
        today: Override for the current date (useful in tests).
        persist: When False, *report* the stored pick without making one —
            no draw, no write. Returns ``""`` when today's bucket has no
            valid stored pick yet. This exists for read-only callers like the
            status page, whose 30-second poll otherwise won the race to pick
            the day's theme at almost every rollover (#238).

    Returns:
        A concrete theme name (never ``"random"`` or ``"random_daily"``), or
        ``""`` when ``persist=False`` and nothing has been picked yet.
    """
    if today is None:
        today = date.today()

    today_str = today.isoformat()
    state_path = Path(output_dir) / _DAILY_STATE_FILE

    # Try to reuse a persisted choice for today
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            if state.get("date") == today_str:
                chosen = state.get("theme", "")
                valid_pool = AVAILABLE_THEMES - _EXCLUDED_FROM_POOL
                if chosen in valid_pool:
                    logger.info("Random theme for %s: %s (persisted)", today_str, chosen)
                    return chosen
        except Exception as exc:
            logger.warning("Could not read random theme state: %s", exc)

    # Choose a new theme for today
    pool = eligible_themes(include, exclude)
    if not pool:
        # An empty pool is not a draw: every run resolves to "default" and
        # persists nothing, so reporting it needs no write either. Evaluated
        # before the persist check so the status page reports what the panel
        # is really showing rather than "not drawn yet" forever. The warning
        # stays on the renderer's path — the page polls every 30 seconds.
        if persist:
            logger.warning(
                "Random theme pool is empty (include=%r, exclude=%r) — falling back to 'default'",
                include,
                exclude,
            )
        return "default"

    if not persist:
        # Reporting only: drawing here would decide what the dashboard shows.
        return ""

    chosen = random.choice(pool)
    logger.info("Random theme for %s: %s (newly selected from pool: %s)", today_str, chosen, pool)

    # Persist the choice. Atomic (tempfile + rename) like every other JSON
    # state file — a truncated write here would be re-picked on the next tick,
    # so the theme would change mid-day after a power cut.
    try:
        atomic_write_json(state_path, {"date": today_str, "theme": chosen})
    except Exception as exc:
        logger.warning("Could not save random theme state: %s", exc)

    return chosen


def pick_random_theme_hourly(
    include: list[str],
    exclude: list[str],
    output_dir: str,
    now: datetime | None = None,
    persist: bool = True,
) -> str:
    """Return the theme chosen for the current hour, persisting the selection.

    If a theme was already chosen for the current hour it is reused; otherwise
    a new one is drawn from the eligible pool and written to the state file.
    The bucket key is ``YYYY-MM-DDTHH`` (local time), so the theme rotates at
    the top of each hour.

    Falls back to ``"default"`` when the eligible pool is empty.

    Args:
        include: Allowlist of theme names (empty = all themes).
        exclude: Denylist of theme names.
        output_dir: Directory where the state file is stored.
        now: Override for the current datetime (useful in tests).
        persist: When False, *report* the stored pick without making one —
            no draw, no write. Returns ``""`` when this hour's bucket has no
            valid stored pick yet (#238).

    Returns:
        A concrete theme name (never ``"random_hourly"``), or ``""`` when
        ``persist=False`` and nothing has been picked yet.
    """
    if now is None:
        now = datetime.now()  # allow-naive-datetime — naive local for hourly bucket

    hour_key = now.strftime("%Y-%m-%dT%H")
    state_path = Path(output_dir) / _HOURLY_STATE_FILE

    # Try to reuse a persisted choice for this hour
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            if state.get("hour") == hour_key:
                chosen = state.get("theme", "")
                valid_pool = AVAILABLE_THEMES - _EXCLUDED_FROM_POOL
                if chosen in valid_pool:
                    logger.info("Random hourly theme for %s: %s (persisted)", hour_key, chosen)
                    return chosen
        except Exception as exc:
            logger.warning("Could not read random hourly theme state: %s", exc)

    # Choose a new theme for this hour
    pool = eligible_themes(include, exclude)
    if not pool:
        # Same ordering as the daily variant — see pick_random_theme().
        if persist:
            logger.warning(
                "Random theme pool is empty (include=%r, exclude=%r) — falling back to 'default'",
                include,
                exclude,
            )
        return "default"

    if not persist:
        # Reporting only — see pick_random_theme().
        return ""

    chosen = random.choice(pool)
    logger.info(
        "Random hourly theme for %s: %s (newly selected from pool: %s)", hour_key, chosen, pool
    )

    # Persist the choice — atomic, same reasoning as the daily variant.
    try:
        atomic_write_json(state_path, {"hour": hour_key, "theme": chosen})
    except Exception as exc:
        logger.warning("Could not save random hourly theme state: %s", exc)

    return chosen
