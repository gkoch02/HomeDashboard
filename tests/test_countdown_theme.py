"""Tests for the countdown theme and countdown_panel component."""

from __future__ import annotations

from datetime import date, datetime

from PIL import Image, ImageDraw

from src.config import CountdownConfig, CountdownEvent, DisplayConfig, load_config
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.countdown_panel import (
    _parse_events,
    _Resolved,
    draw_countdown,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 23, 12, 0)
TODAY = FIXED_NOW.date()


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _render(countdown_events):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme("countdown")
    return render_dashboard(data, DisplayConfig(), theme=theme, countdown_events=countdown_events)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestCountdownRegistration:
    def test_in_available_themes(self):
        assert "countdown" in AVAILABLE_THEMES

    def test_load_theme(self):
        theme = load_theme("countdown")
        assert theme.name == "countdown"

    def test_countdown_region_visible(self):
        theme = load_theme("countdown")
        assert theme.layout.countdown.visible is True


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


class TestParseEvents:
    def test_empty_input_returns_empty(self):
        assert _parse_events([], TODAY) == []

    def test_drops_past_events(self):
        out = _parse_events(
            [CountdownEvent(name="Past", date="2020-01-01")],
            TODAY,
        )
        assert out == []

    def test_drops_events_without_name(self):
        out = _parse_events(
            [CountdownEvent(name="", date="2026-06-04")],
            TODAY,
        )
        assert out == []

    def test_drops_events_without_date(self):
        out = _parse_events(
            [CountdownEvent(name="X", date="")],
            TODAY,
        )
        assert out == []

    def test_drops_events_with_invalid_date(self):
        out = _parse_events(
            [CountdownEvent(name="X", date="nope")],
            TODAY,
        )
        assert out == []

    def test_today_event_kept_with_zero_days(self):
        out = _parse_events(
            [CountdownEvent(name="Today", date=TODAY.isoformat())],
            TODAY,
        )
        assert len(out) == 1
        assert out[0].days_until == 0

    def test_sorted_by_days_ascending(self):
        out = _parse_events(
            [
                CountdownEvent(name="Later", date="2026-08-01"),
                CountdownEvent(name="Sooner", date="2026-05-01"),
            ],
            TODAY,
        )
        assert out[0].name == "Sooner"
        assert out[1].name == "Later"

    def test_caps_at_five_events(self):
        events = [CountdownEvent(name=f"E{i}", date=f"2026-{6 + i:02d}-01") for i in range(8)]
        out = _parse_events(events, TODAY)
        assert len(out) == 5


# ---------------------------------------------------------------------------
# Rendering smoke tests
# ---------------------------------------------------------------------------


class TestCountdownRender:
    def test_renders_correct_size_with_events(self):
        img = _render([CountdownEvent(name="Paris", date="2026-06-04")])
        assert img.size == (800, 480)
        assert img.mode == "1"

    def test_renders_non_blank_with_events(self):
        img = _render([CountdownEvent(name="Paris", date="2026-06-04")])
        assert not all(p == 255 for p in img.tobytes())

    def test_renders_non_blank_empty(self):
        img = _render([])
        assert not all(p == 255 for p in img.tobytes())

    def test_renders_hero_layout_for_single_event(self):
        """Single event uses hero layout — test that it doesn't crash."""
        img = _render([CountdownEvent(name="Paris", date="2026-06-04")])
        assert img.size == (800, 480)

    def test_renders_list_layout_for_multiple_events(self):
        img = _render(
            [
                CountdownEvent(name="A", date="2026-06-01"),
                CountdownEvent(name="B", date="2026-07-01"),
                CountdownEvent(name="C", date="2026-08-01"),
            ]
        )
        assert img.size == (800, 480)

    def test_renders_with_today_event(self):
        img = _render([CountdownEvent(name="Now", date=TODAY.isoformat())])
        assert img.size == (800, 480)

    def test_long_name_does_not_crash(self):
        img = _render([CountdownEvent(name="a" * 200, date="2026-06-04")])
        assert img.size == (800, 480)


class TestDrawCountdownDirect:
    def test_defaults_region_and_style(self):
        img, d = _make_draw()
        draw_countdown(d, [], TODAY)
        # Empty state should still produce pixels
        assert img.getbbox() is not None

    def test_none_events_treated_as_empty(self):
        img, d = _make_draw()
        draw_countdown(d, None, TODAY)  # type: ignore[arg-type]
        assert img.getbbox() is not None

    def test_resolved_dataclass_instance(self):
        r = _Resolved(name="X", target=date(2026, 5, 1), days_until=8)
        assert r.name == "X"


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TestCountdownConfig:
    def test_empty_config_has_no_events(self):
        cfg = CountdownConfig()
        assert cfg.events == []

    def test_loads_from_yaml(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            """
countdown:
  events:
    - name: "Paris Trip"
      date: "2026-06-04"
    - name: "Anniversary"
      date: "2026-08-12"
""".strip()
        )
        cfg = load_config(str(cfg_file))
        assert len(cfg.countdown.events) == 2
        assert cfg.countdown.events[0].name == "Paris Trip"
        assert cfg.countdown.events[0].date == "2026-06-04"

    def test_invalid_event_entries_are_skipped(self, tmp_path):
        """Non-dict items are ignored; partial dicts get empty-string fields."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            """
countdown:
  events:
    - "not a dict"
    - {}
    - name: "Good"
      date: "2026-06-04"
""".strip()
        )
        cfg = load_config(str(cfg_file))
        # 2 entries survive — the bare {} (empty name/date) and "Good"
        assert len(cfg.countdown.events) == 2
        assert cfg.countdown.events[1].name == "Good"
