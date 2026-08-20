#!/usr/bin/env python3
"""Render every registered theme to a preview PNG in one process.

Replaces the hand-maintained theme list that used to live in the Makefile's
``previews`` rule. That list named 24 of the concrete themes and spawned a full
``python -m src.main`` per theme, so every render paid a fresh interpreter
startup and re-imported PIL and numpy. Worse, a new theme needed a Makefile
edit that nothing enforced — ``make docs-check`` validates the docs inventories,
not the Makefile.

Themes come from the registry here, so adding one needs no edit to this script
either. Exclusions are the single ``EXCLUDED`` set below.

Usage::

    python3 scripts/build_previews.py                    # Waveshare set
    python3 scripts/build_previews.py --provider inky    # Inky Spectra-6 set
    python3 scripts/build_previews.py --theme moonphase --theme qotd
    python3 scripts/build_previews.py --date 2026-04-06  # pin the render date
"""

from __future__ import annotations

import argparse
import sys
from datetime import date as _date
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import CountdownEvent, load_config  # noqa: E402
from src.dummy_data import generate_dummy_data  # noqa: E402
from src.render.canvas import render_dashboard  # noqa: E402
from src.render.theme import load_theme  # noqa: E402
from src.render.themes.registry import all_theme_names  # noqa: E402

PREVIEW_DIR = REPO_ROOT / "assets" / "previews"
EXAMPLE_CONFIG = REPO_ROOT / "config" / "config.example.yaml"

# Themes deliberately left out of the batch. Empty today — the old Makefile
# list omitted twelve themes with no rationale recorded, and every one of them
# renders. Add a name here (with the reason) rather than trimming the loop.
EXCLUDED: frozenset[str] = frozenset()

# `default` is a pseudo-name resolved by load_theme() rather than a registry
# entry, so all_theme_names() does not list it — but docs/themes.md embeds
# theme_default.png, so the batch has to ask for it by name.
EXTRA_NAMES: tuple[str, ...] = ("default",)

# Pinned so a rerun on a different day produces the same plate. The moon-phase
# themes are the visible case — their whole subject is the date — but the
# dateline on every other theme moves too, which makes an unpinned batch churn
# every committed PNG. Matches the theme pixel-snapshot fixture.
DEFAULT_DATE = _date(2026, 4, 6)
DEFAULT_TIME = (10, 30)

# The two themes that render an empty-state placeholder without extra input.
# Everything else — coordinates included — comes from the config, so a preview
# shows what that config actually produces.
PREVIEW_MESSAGE = "Preview Message"
PREVIEW_COUNTDOWNS = [
    CountdownEvent(name="Midsummer", date="2026-06-21"),
    CountdownEvent(name="Paris trip", date="2026-09-14"),
]

_SUFFIX = {"waveshare": "", "inky": "_inky"}


def _build_config(provider: str, config_path: str):
    """Load *config_path* and point it at the requested display."""
    cfg = load_config(config_path)
    cfg.display.provider = provider
    cfg.display.model = "impression_7_3_2025" if provider == "inky" else "epd7in5_V2"
    # Auto-derived native dimensions follow the model, so clear any width and
    # height the example config pinned for the other provider.
    cfg.display.width, cfg.display.height = (
        (800, 480) if provider == "inky" else (cfg.display.width, cfg.display.height)
    )
    return cfg


def _theme_names(requested: list[str] | None) -> list[str]:
    renderable = set(all_theme_names()) | set(EXTRA_NAMES)
    if requested:
        unknown = sorted(set(requested) - renderable)
        if unknown:
            raise SystemExit(f"Unknown theme(s): {', '.join(unknown)}")
        return sorted(requested)
    return sorted(renderable - EXCLUDED)


def render_preview(theme_name: str, cfg, now: datetime, out_path: Path) -> None:
    """Render one theme against dummy data and write it to *out_path*."""
    data = generate_dummy_data(now=now)
    theme = load_theme(theme_name)
    if theme_name == "photo":
        theme.style.photo_path = cfg.photo.path

    # Same (0.0, 0.0) == "unset" convention DashboardApp uses, so a config
    # without coordinates previews the graceful-degradation path rather than
    # silently borrowing coordinates this script invented.
    lat, lon = cfg.weather.latitude, cfg.weather.longitude
    coords_set = not (lat == 0.0 and lon == 0.0)

    image = render_dashboard(
        data,
        cfg.display,
        title=cfg.title,
        theme=theme,
        quote_refresh=cfg.cache.quote_refresh,
        quotes_path=cfg.quotes.path or None,
        message_text=PREVIEW_MESSAGE,
        countdown_events=list(cfg.countdown.events) or PREVIEW_COUNTDOWNS,
        latitude=lat if coords_set else None,
        longitude=lon if coords_set else None,
        # No state_dir: a preview must not persist anything (the weatherglass
        # barometer trend would learn from dummy pressure otherwise).
        state_dir=None,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("waveshare", "inky"),
        default="waveshare",
        help="Display backend to render for (default: waveshare).",
    )
    parser.add_argument(
        "--theme",
        action="append",
        dest="themes",
        help="Render only this theme (repeatable). Default: every registered theme.",
    )
    parser.add_argument(
        "--date",
        default=DEFAULT_DATE.isoformat(),
        help=f"Render date, YYYY-MM-DD (default: {DEFAULT_DATE.isoformat()}).",
    )
    parser.add_argument(
        "--config",
        default=str(EXAMPLE_CONFIG),
        help="Config to render against (default: config/config.example.yaml).",
    )
    parser.add_argument(
        "--out-dir",
        default=str(PREVIEW_DIR),
        help="Directory to write previews into (default: assets/previews).",
    )
    args = parser.parse_args(argv)

    try:
        render_date = _date.fromisoformat(args.date)
    except ValueError:
        raise SystemExit(f"Invalid --date {args.date!r}; expected YYYY-MM-DD") from None
    now = datetime.combine(render_date, datetime.min.time()).replace(
        hour=DEFAULT_TIME[0], minute=DEFAULT_TIME[1]
    )

    cfg = _build_config(args.provider, args.config)
    out_dir = Path(args.out_dir)
    suffix = _SUFFIX[args.provider]

    names = _theme_names(args.themes)
    failures: list[str] = []
    for name in names:
        out_path = out_dir / f"theme_{name}{suffix}.png"
        try:
            render_preview(name, cfg, now, out_path)
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  FAILED {name}: {exc}", file=sys.stderr)
            continue
        try:
            shown = out_path.relative_to(REPO_ROOT)
        except ValueError:  # --out-dir outside the repo
            shown = out_path
        print(f"  {shown}")

    print(f"{len(names) - len(failures)}/{len(names)} previews written to {out_dir}")
    if failures:
        print(f"{len(failures)} theme(s) failed:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
