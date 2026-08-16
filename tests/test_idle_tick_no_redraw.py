"""A tick that fetched nothing must render byte-identically.

The display is only written when the rendered image differs from the last one
(`OutputService.publish` → `image_changed`). Anything on the plate that reads
the render clock therefore forces a hardware refresh on every tick — on a
5-minute timer that is ~12 writes an hour to repaint a few hundred pixels, and
on Waveshare's fast waveform those accumulate as static ink drifting grey
between full refreshes. Captions must read ``DashboardData.content_at``, which
only advances when a source actually produced new data.

Themes whose *content* genuinely tracks the clock are exempt and listed below.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.config import DisplayConfig
from src.display.driver import image_hash
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import AVAILABLE_THEMES, load_theme

NOW = datetime(2026, 8, 15, 12, 45)
LAST_FETCH = NOW - timedelta(minutes=12)

# Themes that redraw on the clock by design: the position of a sun, a needle,
# a "now" line, or the words of a fuzzy clock are the content, not chrome.
TIME_DRIVEN = {
    "day_arc",
    "fuzzyclock",
    "fuzzyclock_invert",
    "light_cycle",
    "timeline",
    "weatherglass",
    # Datelines that show the current time as part of the design, and
    # constellation_map's label, which names the moment the chart is projected
    # for and so must agree with the stars.
    "constellation_map",
    "scorecard",
    "sunrise",
    "tides",
    "trends",
}

# Not driven by DashboardData in a way this test can hold still.
NOT_APPLICABLE = {"random", "random_daily", "random_hourly", "photo", "message", "countdown"}

CANDIDATES = sorted(set(AVAILABLE_THEMES) - TIME_DRIVEN - NOT_APPLICABLE)


def _render(theme_name: str, tick: datetime) -> str:
    data = generate_dummy_data(now=NOW)
    data.fetched_at = tick  # the render clock advances every run
    data.content_at = LAST_FETCH  # ...but nothing was fetched this tick
    return image_hash(render_dashboard(data, DisplayConfig(), theme=load_theme(theme_name)))


@pytest.mark.parametrize("theme_name", CANDIDATES)
def test_idle_tick_does_not_change_the_image(theme_name: str):
    first = _render(theme_name, NOW)
    second = _render(theme_name, NOW + timedelta(minutes=5))
    assert first == second, (
        f"{theme_name} redraws on an idle tick — something on the plate is reading the "
        "render clock instead of DashboardData.content_at"
    )


@pytest.mark.parametrize("theme_name", sorted(TIME_DRIVEN))
def test_time_driven_themes_still_track_the_clock(theme_name: str):
    # The exemption list must not silently collect themes that have since
    # stopped depending on the clock.
    first = _render(theme_name, NOW)
    second = _render(theme_name, NOW + timedelta(minutes=5))
    assert first != second, (
        f"{theme_name} no longer redraws on the clock — drop it from TIME_DRIVEN"
    )
