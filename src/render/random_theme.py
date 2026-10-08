"""Random theme rotation — daily and hourly cadences.

Selects a theme from the eligible pool once per day (or once per hour) and
persists the choice so that every dashboard refresh within the same time bucket
uses the same theme.

The eligible pool is derived from ``AVAILABLE_THEMES`` minus pseudo-themes and
utility views, then filtered by the user's ``include`` / ``exclude`` lists:

- If *include* is non-empty, only those themes are candidates.
- Any theme in *exclude* is removed from the pool.
- *include* is applied first, then *exclude*.

Daily state is written to ``<state_dir>/random_theme_state.json``:
    {"date": "2026-03-22", "theme": "terminal"}

Hourly state is written to ``<state_dir>/random_theme_hourly_state.json``:
    {"hour": "2026-03-22T14", "theme": "terminal"}

A new theme is picked whenever the stored bucket key differs from the current one,
which naturally rotates the theme at the start of each new day or hour.
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime
from pathlib import Path

from src._io import atomic_write_json, read_json
from src.render.theme import AVAILABLE_THEMES

logger = logging.getLogger(__name__)

_DAILY_STATE_FILE = "random_theme_state.json"
_HOURLY_STATE_FILE = "random_theme_hourly_state.json"
# Pseudo-themes and utility views that must never appear in a rotation pool.
_EXCLUDED_FROM_POOL: frozenset[str] = frozenset(
    {
        "random",
        "random_daily",
        "random_hourly",
        "diags",
        "wide_diags",
        "message",
        "photo",
        "countdown",
        # Night plates, meant to be scheduled for after dark, not drawn at noon.
        "wide_night",
        "wide_night_invert",
    }
)


def theme_fits_panel(name: str, panel: tuple[int, int]) -> bool:
    """Whether *name*'s canvas is the panel's shape, near enough to stretch.

    A theme whose canvas would be fitted with padding on this panel (the
    panoramic 1360x480 themes on an 800x480 panel, or the reverse) has no
    business in a random rotation there: the point of the rotation is a
    different plate each day, not a letterboxed band. The test is the same
    one ``display.scaling: auto`` applies.
    """
    from src.display.backend import FIT_DISTORTION_THRESHOLD, distortion
    from src.render.theme import load_theme

    try:
        layout = load_theme(name).layout
    except ValueError:
        return True
    return distortion((layout.canvas_w, layout.canvas_h), panel) <= FIT_DISTORTION_THRESHOLD


def eligible_themes(
    include: list[str], exclude: list[str], panel: tuple[int, int] | None = None
) -> list[str]:
    """Return sorted list of theme names eligible for random selection.

    Args:
        include: If non-empty, only themes in this list are considered.
                 An empty list means *all* real themes are candidates.
        exclude: Themes to remove from the pool.
        panel: The panel's (width, height); when given, themes that would be
            padded on it (see :func:`theme_fits_panel`) are dropped.

    Returns:
        Sorted list of eligible theme names (may be empty).
    """
    pool: set[str] = set(AVAILABLE_THEMES - _EXCLUDED_FROM_POOL)
    if include:
        pool = pool & set(include)
    if exclude:
        pool = pool - set(exclude)
    if panel is not None:
        pool = {name for name in pool if theme_fits_panel(name, panel)}
    return sorted(pool)


def _pick(
    include: list[str],
    exclude: list[str],
    state_path: Path,
    *,
    bucket_field: str,
    bucket_key: str,
    label: str,
    state_label: str,
    persist: bool,
    panel: tuple[int, int] | None,
) -> str:
    """The shared body of the two cadences, parameterised by bucket and state file.

    A persisted pick is reused when its *bucket_field* matches *bucket_key*;
    otherwise a new one is drawn from the eligible pool and written back.
    *label* / *state_label* only shape the log lines.
    """
    # Try to reuse a persisted choice for this bucket
    state = read_json(state_path, default=None)
    if isinstance(state, dict) and state.get(bucket_field) == bucket_key:
        chosen = state.get("theme", "")
        # Validate against the pool this run would draw from, panel filter
        # included: a pick persisted before the panel changed (or by a run
        # configured for another one) would otherwise letterbox for the rest
        # of the bucket.
        if isinstance(chosen, str) and chosen in eligible_themes(include, exclude, panel):
            logger.info("%s for %s: %s (persisted)", label, bucket_key, chosen)
            return chosen

    # Choose a new theme for this bucket
    pool = eligible_themes(include, exclude, panel)
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
    logger.info("%s for %s: %s (newly selected from pool: %s)", label, bucket_key, chosen, pool)

    # Persist the choice. Atomic (tempfile + rename) like every other JSON
    # state file — a truncated write here would be re-picked on the next tick,
    # so the theme would change mid-bucket after a power cut.
    try:
        atomic_write_json(state_path, {bucket_field: bucket_key, "theme": chosen})
    except Exception as exc:
        logger.warning("Could not save %s: %s", state_label, exc)

    return chosen


def pick_random_theme(
    include: list[str],
    exclude: list[str],
    state_dir: str,
    today: date | None = None,
    persist: bool = True,
    panel: tuple[int, int] | None = None,
) -> str:
    """Return the theme chosen for *today*, persisting the selection across runs.

    If a theme was already chosen for today it is reused; otherwise a new one
    is drawn from the eligible pool and written to the state file.

    Falls back to ``"default"`` when the eligible pool is empty.

    Args:
        include: Allowlist of theme names (empty = all themes).
        exclude: Denylist of theme names.
        state_dir: Directory where the state file is stored.
        today: Override for the current date (useful in tests).
        persist: When False, *report* the stored pick without making one —
            no draw, no write. Returns ``""`` when today's bucket has no
            valid stored pick yet. For read-only callers like the status
            page, whose poll must not be what picks the day's theme.
        panel: The panel's (width, height), passed to :func:`eligible_themes`.

    Returns:
        A concrete theme name (never ``"random"`` or ``"random_daily"``), or
        ``""`` when ``persist=False`` and nothing has been picked yet.
    """
    if today is None:
        today = date.today()
    return _pick(
        include,
        exclude,
        Path(state_dir) / _DAILY_STATE_FILE,
        bucket_field="date",
        bucket_key=today.isoformat(),
        label="Random theme",
        state_label="random theme state",
        persist=persist,
        panel=panel,
    )


def pick_random_theme_hourly(
    include: list[str],
    exclude: list[str],
    state_dir: str,
    now: datetime | None = None,
    persist: bool = True,
    panel: tuple[int, int] | None = None,
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
        state_dir: Directory where the state file is stored.
        now: Override for the current datetime (useful in tests).
        persist: When False, *report* the stored pick without making one —
            no draw, no write. Returns ``""`` when this hour's bucket has no
            valid stored pick yet.
        panel: The panel's (width, height), passed to :func:`eligible_themes`.

    Returns:
        A concrete theme name (never ``"random_hourly"``), or ``""`` when
        ``persist=False`` and nothing has been picked yet.
    """
    if now is None:
        now = datetime.now()  # allow-naive-datetime — naive local for hourly bucket
    return _pick(
        include,
        exclude,
        Path(state_dir) / _HOURLY_STATE_FILE,
        bucket_field="hour",
        bucket_key=now.strftime("%Y-%m-%dT%H"),
        label="Random hourly theme",
        state_label="random hourly theme state",
        persist=persist,
        panel=panel,
    )
