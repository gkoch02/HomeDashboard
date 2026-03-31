"""Daily random theme rotation.

Selects a theme from the eligible pool once per day and persists the choice
so that every dashboard refresh within the same calendar day uses the same theme.

The eligible pool is derived from ``AVAILABLE_THEMES`` minus ``"random"``, then
filtered by the user's ``include`` / ``exclude`` lists:

- If *include* is non-empty, only those themes are candidates.
- Any theme in *exclude* is removed from the pool.
- *include* is applied first, then *exclude*.

State is written to ``<output_dir>/random_theme_state.json``:
    {"date": "2026-03-22", "theme": "terminal"}

A new theme is picked whenever the stored date differs from today's date,
which naturally rotates the theme overnight (the first refresh after midnight).
"""

from __future__ import annotations

import json
import logging
import random
from datetime import date
from pathlib import Path

from src.render.theme import AVAILABLE_THEMES

logger = logging.getLogger(__name__)

_STATE_FILE = "random_theme_state.json"
# "random" is not a real theme and must never appear in its own rotation pool.
# "diags" is a utility/diagnostic view, not a daily-driver aesthetic — excluded by default.
_EXCLUDED_FROM_POOL: frozenset[str] = frozenset({"random", "diags", "air_quality"})


def eligible_themes(include: list[str], exclude: list[str]) -> list[str]:
    """Return sorted list of theme names eligible for random selection.

    Args:
        include: If non-empty, only themes in this list are considered.
                 An empty list means *all* real themes are candidates.
        exclude: Themes to remove from the pool.

    Returns:
        Sorted list of eligible theme names (may be empty).
    """
    pool: set[str] = AVAILABLE_THEMES - _EXCLUDED_FROM_POOL
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

    Returns:
        A concrete theme name (never ``"random"``).
    """
    if today is None:
        today = date.today()

    today_str = today.isoformat()
    state_path = Path(output_dir) / _STATE_FILE

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
        logger.warning(
            "Random theme pool is empty (include=%r, exclude=%r) — "
            "falling back to 'default'",
            include,
            exclude,
        )
        return "default"

    chosen = random.choice(pool)
    logger.info("Random theme for %s: %s (newly selected from pool: %s)",
                today_str, chosen, pool)

    # Persist the choice
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"date": today_str, "theme": chosen}))
    except Exception as exc:
        logger.warning("Could not save random theme state: %s", exc)

    return chosen
