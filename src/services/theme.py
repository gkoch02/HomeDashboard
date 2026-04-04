from datetime import datetime as _datetime


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
    cfg, override_theme: str | None, now: _datetime | None = None
) -> str:
    """Resolve the concrete theme name to use for this run.

    Priority (highest → lowest):
    1. ``--theme`` CLI override — schedule is bypassed entirely.
    2. ``theme_schedule`` — first matching time window for the current hour.
    3. ``cfg.theme`` — static config value (may be ``"random"``).
    """
    if override_theme is not None:
        # CLI override: ignore schedule and random
        theme_name = override_theme
    elif now is not None and cfg.theme_schedule.entries:
        scheduled = _resolve_scheduled_theme(cfg.theme_schedule.entries, now)
        theme_name = scheduled if scheduled is not None else cfg.theme
    else:
        theme_name = cfg.theme

    if theme_name in ("random", "random_daily"):
        from src.render.random_theme import pick_random_theme
        theme_name = pick_random_theme(
            include=cfg.random_theme.include,
            exclude=cfg.random_theme.exclude,
            output_dir=cfg.output_dir,
        )
    elif theme_name == "random_hourly":
        from src.render.random_theme import pick_random_theme_hourly
        theme_name = pick_random_theme_hourly(
            include=cfg.random_theme.include,
            exclude=cfg.random_theme.exclude,
            output_dir=cfg.output_dir,
            now=now,
        )
    return theme_name
