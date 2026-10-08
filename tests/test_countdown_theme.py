"""Tests for the countdown theme and countdown_panel component."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.config import CountdownConfig, CountdownEvent, DisplayConfig, load_config
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.countdown_panel import (
    _parse_events,
    _Resolved,
    draw_countdown,
)
from src.render.theme import AVAILABLE_THEMES, load_theme
from tests.conftest import make_draw
from tests.inkutils import ink, record_text

FIXED_NOW = datetime(2026, 4, 23, 12, 0)
TODAY = FIXED_NOW.date()


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

    @pytest.mark.parametrize(
        "name, when",
        [("Past", "2020-01-01"), ("", "2026-06-04"), ("X", ""), ("X", "nope")],
        ids=["past", "no-name", "no-date", "invalid-date"],
    )
    def test_drops_unusable_events(self, name, when):
        assert _parse_events([CountdownEvent(name=name, date=when)], TODAY) == []

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
# Rendering
# ---------------------------------------------------------------------------

PARIS = CountdownEvent(name="Paris", date="2026-06-04")  # 42 days after TODAY


def _drawn(events) -> list[str]:
    """The strings draw_countdown sets for *events*, in order."""
    _img, d = make_draw()
    calls = record_text(d)
    draw_countdown(d, events, TODAY)
    return [text for text, _box in calls]


class TestCountdownRender:
    def test_theme_renders_the_panel(self):
        img = _render([PARIS])
        assert img.size == (800, 480)
        assert ink(img) > 0, "the countdown theme drew nothing"

    def test_events_change_the_plate(self):
        assert _render([PARIS]).tobytes() != _render([]).tobytes()

    def test_a_single_event_takes_the_hero_layout(self):
        drawn = _drawn([PARIS])
        assert "COUNTING DOWN TO" in drawn
        assert {"42", "DAYS", "PARIS"} <= set(drawn)

    def test_several_events_take_the_list_layout(self):
        drawn = _drawn(
            [
                CountdownEvent(name="A", date="2026-06-01"),
                CountdownEvent(name="B", date="2026-07-01"),
                CountdownEvent(name="C", date="2026-08-01"),
            ]
        )
        assert "COUNTING DOWN TO" not in drawn
        assert {"A", "B", "C"} <= set(drawn)

    def test_an_event_today_has_arrived(self):
        drawn = _drawn([CountdownEvent(name="Now", date=TODAY.isoformat())])
        assert "ARRIVED" in drawn and "0" in drawn

    def test_a_long_name_is_truncated_inside_the_panel(self):
        _img, d = make_draw()
        calls = record_text(d)
        draw_countdown(d, [CountdownEvent(name="a" * 200, date="2026-06-04")], TODAY)
        name = [(text, box) for text, box in calls if text.startswith("AAA")]
        assert len(name) == 1
        text, box = name[0]
        assert text.endswith("...") and box[2] <= 800


class TestDrawCountdownDirect:
    def test_defaults_region_and_style(self):
        img, d = make_draw()
        draw_countdown(d, [], TODAY)
        # Empty state should still produce pixels
        assert ink(img) > 0, "the empty countdown state drew nothing"

    def test_none_events_treated_as_empty(self):
        img, d = make_draw()
        draw_countdown(d, None, TODAY)  # type: ignore[arg-type]
        empty, ed = make_draw()
        draw_countdown(ed, [], TODAY)
        assert img.tobytes() == empty.tobytes(), (
            "events=None was not treated the same as an empty list"
        )

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
