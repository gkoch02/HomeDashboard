"""Tests for src/services/theme.py — schedule resolution and theme name resolution."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.config import ThemeScheduleEntry
from src.services.theme import _resolve_scheduled_theme, resolve_theme_name


def _entries(*pairs):
    """Build a list of ThemeScheduleEntry from (time, theme) tuples."""
    return [ThemeScheduleEntry(time=t, theme=th) for t, th in pairs]


def _now(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 3, 15, hour, minute)


def _make_cfg(theme="default", entries=None):
    cfg = MagicMock()
    cfg.theme = theme
    cfg.random_theme.include = []
    cfg.random_theme.exclude = []
    cfg.output_dir = "output"
    cfg.theme_schedule.entries = entries or []
    return cfg


# ---------------------------------------------------------------------------
# _resolve_scheduled_theme
# ---------------------------------------------------------------------------


class TestResolveScheduledTheme:
    @pytest.mark.parametrize(
        ("pairs", "now", "expected"),
        [
            ((), _now(12), None),
            ((("06:00", "default"),), _now(10), "default"),
            ((("22:00", "terminal"),), _now(8), None),
            ((("14:00", "monthly"),), _now(14, 0), "monthly"),
            ((("06:00", "default"), ("20:00", "fuzzyclock_invert")), _now(21), "fuzzyclock_invert"),
            ((("06:00", "default"), ("20:00", "terminal")), _now(10), "default"),
            ((("20:00", "terminal"), ("06:00", "default")), _now(10), "default"),
            ((("06:00", "default"), ("22:00", "terminal")), _now(5), None),
            (
                (("06:00", "default"), ("18:00", "monthly"), ("22:00", "terminal")),
                _now(23),
                "terminal",
            ),
        ],
        ids=[
            "empty-entries",
            "single-entry-already-reached",
            "single-entry-not-yet-reached",
            "entry-exactly-at-now",
            "latest-reached-entry-wins",
            "earlier-entry-when-later-not-reached",
            "input-order-ignored",
            "before-first-entry",
            "three-entries-last-wins",
        ],
    )
    def test_resolves_last_entry_at_or_before_now(self, pairs, now, expected):
        """The active entry is the chronologically last one whose time is at or before
        ``now``, whatever the input order; before the first entry nothing applies."""
        assert _resolve_scheduled_theme(_entries(*pairs), now) == expected


# ---------------------------------------------------------------------------
# resolve_theme_name — priority chain
# ---------------------------------------------------------------------------


class TestResolveThemeName:
    @pytest.mark.parametrize(
        ("cfg_theme", "pairs", "override", "now", "expected"),
        [
            ("default", (("00:00", "monthly"),), "terminal", _now(12), "terminal"),
            ("random", (), "day_arc", _now(12), "day_arc"),
            ("default", (("06:00", "monthly"),), None, _now(10), "monthly"),
            ("default", (("06:00", "monthly"),), None, _now(4), "default"),
            ("day_arc", (), None, _now(12), "day_arc"),
            ("default", (("00:00", "terminal"),), None, None, "default"),
        ],
        ids=[
            "cli-override-beats-schedule",
            "cli-override-beats-random",
            "schedule-beats-cfg-theme",
            "cfg-theme-before-first-entry",
            "empty-schedule-uses-cfg-theme",
            "no-now-ignores-schedule",
        ],
    )
    def test_priority_chain(self, cfg_theme, pairs, override, now, expected):
        """CLI override beats the schedule and random; a matching schedule entry beats
        ``cfg.theme``; with no match, no entries, or no ``now``, ``cfg.theme`` applies."""
        cfg = _make_cfg(theme=cfg_theme, entries=_entries(*pairs))
        assert resolve_theme_name(cfg, override_theme=override, now=now) == expected

    @pytest.mark.parametrize(
        ("cfg_theme", "pairs", "picker", "picked"),
        [
            ("random", (), "pick_random_theme", "fantasy"),
            ("default", (("00:00", "random"),), "pick_random_theme", "day_arc"),
            ("random_daily", (), "pick_random_theme", "qotd"),
            ("default", (("00:00", "random_hourly"),), "pick_random_theme_hourly", "trends"),
        ],
        ids=[
            "cfg-random",
            "schedule-entry-random",
            "cfg-random-daily-alias",
            "schedule-entry-random-hourly",
        ],
    )
    def test_pseudo_theme_routes_through_picker(self, cfg_theme, pairs, picker, picked):
        """A random pseudo-theme, whether from ``cfg.theme`` or a schedule entry, is
        resolved by the matching daily or hourly picker exactly once."""
        cfg = _make_cfg(theme=cfg_theme, entries=_entries(*pairs))
        with patch(f"src.render.random_theme.{picker}", return_value=picked) as mock_pick:
            result = resolve_theme_name(cfg, override_theme=None, now=_now(12))
        assert result == picked
        mock_pick.assert_called_once()

    @pytest.mark.parametrize(
        ("cfg_theme", "pairs"),
        [("minimalist", ()), ("default", (("00:00", "tides"),))],
        ids=["cfg-theme", "schedule-entry"],
    )
    def test_retired_theme_falls_back_to_default(self, cfg_theme, pairs, caplog):
        """A config still naming a retired theme renders ``default`` rather than
        raising in ``load_theme()`` on every run."""
        cfg = _make_cfg(theme=cfg_theme, entries=_entries(*pairs))
        with caplog.at_level("WARNING", logger="src.services.theme"):
            assert resolve_theme_name(cfg, override_theme=None, now=_now(12)) == "default"
        assert "retired" in caplog.text

    def test_random_hourly_resolves_via_pick_random_theme_hourly(self):
        """'random_hourly' routes through pick_random_theme_hourly with the current time."""
        cfg = _make_cfg(theme="random_hourly", entries=[])
        now = _now(14, 30)
        with patch(
            "src.render.random_theme.pick_random_theme_hourly",
            return_value="moonphase",
        ) as mock_pick:
            result = resolve_theme_name(cfg, override_theme=None, now=now)
        assert result == "moonphase"
        mock_pick.assert_called_once()
        # ``now`` must be forwarded so the picker can bucket by hour correctly.
        assert mock_pick.call_args.kwargs["now"] == now
        assert mock_pick.call_args.kwargs["state_dir"] == cfg.state_dir
