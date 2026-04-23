"""Tests for src/services/theme.py — schedule resolution and theme name resolution."""

from datetime import datetime
from unittest.mock import MagicMock, patch

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
    def test_empty_entries_returns_none(self):
        assert _resolve_scheduled_theme([], _now(12)) is None

    def test_single_entry_before_now_returns_theme(self):
        entries = _entries(("06:00", "default"))
        assert _resolve_scheduled_theme(entries, _now(10)) == "default"

    def test_single_entry_after_now_returns_none(self):
        """Entry starts at 22:00 but it's 08:00 — no match yet."""
        entries = _entries(("22:00", "terminal"))
        assert _resolve_scheduled_theme(entries, _now(8)) is None

    def test_entry_exactly_at_current_time_matches(self):
        entries = _entries(("14:00", "minimalist"))
        assert _resolve_scheduled_theme(entries, _now(14, 0)) == "minimalist"

    def test_latest_matching_entry_wins(self):
        """With entries at 06:00 and 20:00, the 20:00 one should win at 21:00."""
        entries = _entries(("06:00", "default"), ("20:00", "fuzzyclock_invert"))
        assert _resolve_scheduled_theme(entries, _now(21)) == "fuzzyclock_invert"

    def test_earlier_entry_wins_when_later_not_yet_reached(self):
        """It's 10:00 — the 06:00 entry matches, the 20:00 one does not."""
        entries = _entries(("06:00", "default"), ("20:00", "terminal"))
        assert _resolve_scheduled_theme(entries, _now(10)) == "default"

    def test_entries_evaluated_in_time_order_regardless_of_input_order(self):
        """Input order should not matter — only chronological order."""
        entries = _entries(("20:00", "terminal"), ("06:00", "default"))
        # At 10:00, only "06:00" has been reached
        assert _resolve_scheduled_theme(entries, _now(10)) == "default"

    def test_all_entries_before_midnight_wrap_correctly(self):
        """At 05:00, before the first entry at 06:00, returns None."""
        entries = _entries(("06:00", "default"), ("22:00", "terminal"))
        assert _resolve_scheduled_theme(entries, _now(5)) is None

    def test_three_entries_last_one_wins(self):
        entries = _entries(("06:00", "default"), ("18:00", "minimalist"), ("22:00", "terminal"))
        assert _resolve_scheduled_theme(entries, _now(23)) == "terminal"


# ---------------------------------------------------------------------------
# resolve_theme_name — priority chain
# ---------------------------------------------------------------------------


class TestResolveThemeName:
    def test_cli_override_bypasses_schedule(self):
        """--theme terminal should win even when a schedule entry applies."""
        entries = _entries(("00:00", "minimalist"))
        cfg = _make_cfg(theme="default", entries=entries)
        result = resolve_theme_name(cfg, override_theme="terminal", now=_now(12))
        assert result == "terminal"

    def test_cli_override_bypasses_random(self):
        cfg = _make_cfg(theme="random")
        result = resolve_theme_name(cfg, override_theme="today", now=_now(12))
        assert result == "today"

    def test_schedule_wins_over_cfg_theme(self):
        """When a schedule entry matches, it overrides cfg.theme."""
        entries = _entries(("06:00", "minimalist"))
        cfg = _make_cfg(theme="default", entries=entries)
        result = resolve_theme_name(cfg, override_theme=None, now=_now(10))
        assert result == "minimalist"

    def test_cfg_theme_used_when_no_schedule_entry_matches(self):
        """Before any entry fires (e.g. 04:00 with first entry at 06:00), cfg.theme is used."""
        entries = _entries(("06:00", "minimalist"))
        cfg = _make_cfg(theme="default", entries=entries)
        result = resolve_theme_name(cfg, override_theme=None, now=_now(4))
        assert result == "default"

    def test_empty_schedule_falls_through_to_cfg_theme(self):
        cfg = _make_cfg(theme="today", entries=[])
        result = resolve_theme_name(cfg, override_theme=None, now=_now(12))
        assert result == "today"

    def test_no_now_ignores_schedule(self):
        """When now=None (legacy call), schedule is not consulted."""
        entries = _entries(("00:00", "terminal"))
        cfg = _make_cfg(theme="default", entries=entries)
        result = resolve_theme_name(cfg, override_theme=None, now=None)
        assert result == "default"

    def test_random_theme_resolved_when_cfg_theme_is_random(self):
        cfg = _make_cfg(theme="random", entries=[])
        with patch(
            "src.render.random_theme.pick_random_theme", return_value="fantasy"
        ) as mock_pick:
            result = resolve_theme_name(cfg, override_theme=None, now=_now(12))
        assert result == "fantasy"
        mock_pick.assert_called_once()

    def test_random_theme_resolved_when_schedule_entry_is_random(self):
        """If a schedule entry maps to 'random', it falls through to pick_random_theme."""
        entries = _entries(("00:00", "random"))
        cfg = _make_cfg(theme="default", entries=entries)
        with patch("src.render.random_theme.pick_random_theme", return_value="today") as mock_pick:
            result = resolve_theme_name(cfg, override_theme=None, now=_now(12))
        assert result == "today"
        mock_pick.assert_called_once()

    def test_random_daily_alias_resolves_via_pick_random_theme(self):
        """'random_daily' routes through the same daily picker as 'random'."""
        cfg = _make_cfg(theme="random_daily", entries=[])
        with patch("src.render.random_theme.pick_random_theme", return_value="qotd") as mock_pick:
            result = resolve_theme_name(cfg, override_theme=None, now=_now(12))
        assert result == "qotd"
        mock_pick.assert_called_once()

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
        assert mock_pick.call_args.kwargs["output_dir"] == cfg.state_dir

    def test_random_hourly_from_schedule_entry(self):
        """A schedule entry mapping to 'random_hourly' also routes through the hourly picker."""
        entries = _entries(("00:00", "random_hourly"))
        cfg = _make_cfg(theme="default", entries=entries)
        with patch(
            "src.render.random_theme.pick_random_theme_hourly",
            return_value="tides",
        ) as mock_pick:
            result = resolve_theme_name(cfg, override_theme=None, now=_now(12))
        assert result == "tides"
        mock_pick.assert_called_once()
