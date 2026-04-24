from __future__ import annotations

from datetime import datetime as _datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.models import DashboardData


def _resolve_scheduled_theme(entries, now: _datetime) -> str | None:
    """Return the active scheduled theme at *now*, or None if no entry applies.

    Entries are evaluated in time order; the last one whose ``time`` (HH:MM)
    is <= the current local time wins.  Returns None when all entries start
    after the current time (e.g. first entry is "06:00" and it's 3 AM).
    """
    if not entries:
        return None
    current_hm = now.strftime("%H:%M")
    active = None
    for entry in sorted(entries, key=lambda e: e.time):
        if entry.time <= current_hm:
            active = entry
    return active.theme if active is not None else None


def resolve_theme_name(
    cfg,
    override_theme: str | None,
    now: _datetime | None = None,
    data: DashboardData | None = None,
) -> str:
    """Resolve the concrete theme name to use for this run.

    Priority (highest → lowest):
    1. ``--theme`` CLI override — all other sources are bypassed.
    2. ``theme_rules`` — first matching context rule (weather / daypart /
       season / weekday).  Rules requiring weather data silently skip when
       ``data`` is ``None``, so pre-fetch calls fall through cleanly.
    3. ``theme_schedule`` — latest matching HH:MM entry for the current time.
    4. ``cfg.theme`` — static config value (may be ``"random"``).
    """
    if override_theme is not None:
        theme_name: str = override_theme
    else:
        theme_name = ""
        rules = getattr(getattr(cfg, "theme_rules", None), "rules", None) or []
        if rules and now is not None:
            from src.services.theme_rules import resolve_rule_theme

            theme_name = resolve_rule_theme(rules, now, data) or ""
        if not theme_name and now is not None and cfg.theme_schedule.entries:
            theme_name = _resolve_scheduled_theme(cfg.theme_schedule.entries, now) or ""
        if not theme_name:
            theme_name = cfg.theme

    if theme_name in ("random", "random_daily"):
        from src.render.random_theme import pick_random_theme

        theme_name = pick_random_theme(
            include=cfg.random_theme.include,
            exclude=cfg.random_theme.exclude,
            output_dir=cfg.state_dir,
        )
    elif theme_name == "random_hourly":
        from src.render.random_theme import pick_random_theme_hourly

        theme_name = pick_random_theme_hourly(
            include=cfg.random_theme.include,
            exclude=cfg.random_theme.exclude,
            output_dir=cfg.state_dir,
            now=now,
        )
    return theme_name
