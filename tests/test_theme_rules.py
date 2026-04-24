"""Tests for src/services/theme_rules.py — context-aware theme selection."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from src.config import (
    ThemeRule,
    ThemeRuleCondition,
    ThemeScheduleEntry,
)
from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    StalenessLevel,
    WeatherAlert,
    WeatherData,
)
from src.services.theme import resolve_theme_name
from src.services.theme_rules import (
    _calendar_states,
    _current_daypart,
    _current_season,
    _current_weekday,
    _listify,
    _rule_matches,
    resolve_rule_theme,
)


def _wx(description: str = "clear sky", alerts: list | None = None, **kwargs) -> WeatherData:
    base = dict(
        current_temp=60.0,
        current_icon="01d",
        current_description=description,
        high=70.0,
        low=50.0,
        humidity=50,
    )
    base.update(kwargs)
    wd = WeatherData(**base)
    if alerts:
        wd.alerts = alerts
    return wd


def _data(
    weather: WeatherData | None = None,
    events: list[CalendarEvent] | None = None,
    birthdays: list[Birthday] | None = None,
    events_loaded: bool = True,
    birthdays_loaded: bool = True,
) -> DashboardData:
    """Build a DashboardData for tests.

    ``events_loaded`` / ``birthdays_loaded`` mark those sources as present in
    ``source_staleness`` — set False to simulate a fetch outage with no cache.
    """
    staleness: dict[str, StalenessLevel] = {}
    if events_loaded:
        staleness["events"] = StalenessLevel.FRESH
    if birthdays_loaded:
        staleness["birthdays"] = StalenessLevel.FRESH
    return DashboardData(
        events=events or [],
        weather=weather,
        birthdays=birthdays or [],
        source_staleness=staleness,
    )


def _event(
    start: datetime, end: datetime, summary: str = "Meeting", is_all_day: bool = False
) -> CalendarEvent:
    return CalendarEvent(summary=summary, start=start, end=end, is_all_day=is_all_day)


def _now(year=2026, month=4, day=23, hour=12, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute)


def _cfg(rules=None, schedule=None, theme="default") -> MagicMock:
    cfg = MagicMock()
    cfg.theme = theme
    cfg.random_theme.include = []
    cfg.random_theme.exclude = []
    cfg.output_dir = "output"
    cfg.state_dir = "state"
    cfg.theme_schedule.entries = schedule or []
    cfg.theme_rules.rules = rules or []
    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestListify:
    def test_none_returns_empty(self):
        assert _listify(None) == []

    def test_scalar_wrapped(self):
        assert _listify("Rain") == ["rain"]

    def test_list_lowered(self):
        assert _listify(["Rain", "SNOW"]) == ["rain", "snow"]


class TestCurrentSeason:
    def test_april_is_spring(self):
        assert _current_season(_now(month=4)) == "spring"

    def test_july_is_summer(self):
        assert _current_season(_now(month=7)) == "summer"

    def test_october_is_fall(self):
        assert _current_season(_now(month=10)) == "fall"

    def test_january_is_winter(self):
        assert _current_season(_now(month=1)) == "winter"


class TestCurrentWeekday:
    def test_monday_weekday(self):
        now = datetime(2026, 4, 20, 12)  # Monday
        assert _current_weekday(now) == ("monday", "weekday")

    def test_saturday_weekend(self):
        now = datetime(2026, 4, 25, 12)  # Saturday
        assert _current_weekday(now) == ("saturday", "weekend")


class TestCurrentDaypart:
    def test_fixed_ranges_without_weather(self):
        assert _current_daypart(_now(hour=6), None) == "dawn"
        assert _current_daypart(_now(hour=9), None) == "morning"
        assert _current_daypart(_now(hour=14), None) == "afternoon"
        assert _current_daypart(_now(hour=18), None) == "dusk"
        assert _current_daypart(_now(hour=23), None) == "night"

    def test_sunrise_defines_dawn_bucket(self):
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        # 6:30 AM is within 90 minutes of 6:05 AM sunrise → dawn
        assert _current_daypart(_now(hour=6, minute=30), w) == "dawn"

    def test_sunset_defines_dusk_bucket(self):
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        # 7:50 PM is within 60 minutes of 7:43 PM sunset → dusk
        assert _current_daypart(_now(hour=19, minute=50), w) == "dusk"

    def test_morning_after_dawn_before_noon(self):
        """With weather data, the morning bucket is still reachable (pre-review fix)."""
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        # 10 AM is past the dawn window (90 min from sunrise) and before local noon.
        assert _current_daypart(_now(hour=10), w) == "morning"

    def test_afternoon_after_noon_before_dusk(self):
        """With weather data, the afternoon bucket is still reachable (pre-review fix)."""
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        # 3 PM is past local noon and before the dusk window.
        assert _current_daypart(_now(hour=15), w) == "afternoon"

    def test_before_sunrise_is_night(self):
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        assert _current_daypart(_now(hour=3), w) == "night"

    def test_rule_daypart_day_matches_morning_and_afternoon(self):
        """``daypart: day`` is a convenience alias for morning ∪ afternoon."""
        rule = ThemeRule(when=ThemeRuleCondition(daypart="day"), theme="today")
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        assert _rule_matches(rule, _now(hour=10), _data(w)) is True  # morning
        assert _rule_matches(rule, _now(hour=15), _data(w)) is True  # afternoon
        assert _rule_matches(rule, _now(hour=23), _data(w)) is False  # night


# ---------------------------------------------------------------------------
# _rule_matches
# ---------------------------------------------------------------------------


class TestRuleMatches:
    def test_empty_condition_always_matches(self):
        rule = ThemeRule(when=ThemeRuleCondition(), theme="default")
        assert _rule_matches(rule, _now(), _data()) is True

    def test_weather_rule_matches_description_substring(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather")
        data = _data(_wx(description="light rain"))
        assert _rule_matches(rule, _now(), data) is True

    def test_weather_rule_no_match(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather")
        data = _data(_wx(description="clear sky"))
        assert _rule_matches(rule, _now(), data) is False

    def test_weather_rule_fails_when_no_data(self):
        """Rules that need weather data silently fail when data is None."""
        rule = ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather")
        assert _rule_matches(rule, _now(), None) is False

    def test_weather_rule_fails_when_data_has_no_weather(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather")
        assert _rule_matches(rule, _now(), _data(None)) is False

    def test_weather_rule_accepts_list_of_alternatives(self):
        rule = ThemeRule(
            when=ThemeRuleCondition(weather=["rain", "snow", "thunderstorm"]),
            theme="weather",
        )
        data = _data(_wx(description="heavy snow"))
        assert _rule_matches(rule, _now(), data) is True

    def test_alert_present_true_matches_when_alerts_exist(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather_alert_present=True), theme="message")
        data = _data(_wx(alerts=[WeatherAlert(event="Tornado Watch")]))
        assert _rule_matches(rule, _now(), data) is True

    def test_alert_present_false_matches_when_no_alerts(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather_alert_present=False), theme="default")
        data = _data(_wx(alerts=[]))
        assert _rule_matches(rule, _now(), data) is True

    def test_alert_present_requires_weather_data(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather_alert_present=True), theme="message")
        assert _rule_matches(rule, _now(), None) is False

    def test_daypart_matches(self):
        rule = ThemeRule(when=ThemeRuleCondition(daypart="night"), theme="moonphase")
        assert _rule_matches(rule, _now(hour=23), _data()) is True
        assert _rule_matches(rule, _now(hour=12), _data()) is False

    def test_season_matches(self):
        rule = ThemeRule(when=ThemeRuleCondition(season="spring"), theme="today")
        assert _rule_matches(rule, _now(month=4), _data()) is True
        assert _rule_matches(rule, _now(month=11), _data()) is False

    def test_season_autumn_alias_for_fall(self):
        rule = ThemeRule(when=ThemeRuleCondition(season="autumn"), theme="today")
        # October is fall in our bucket
        assert _rule_matches(rule, _now(month=10), _data()) is True

    def test_weekday_name_match(self):
        rule = ThemeRule(when=ThemeRuleCondition(weekday="monday"), theme="today")
        assert _rule_matches(rule, datetime(2026, 4, 20, 12), _data()) is True
        assert _rule_matches(rule, datetime(2026, 4, 21, 12), _data()) is False

    def test_weekday_weekend_key(self):
        rule = ThemeRule(when=ThemeRuleCondition(weekday="weekend"), theme="today")
        assert _rule_matches(rule, datetime(2026, 4, 25, 12), _data()) is True
        assert _rule_matches(rule, datetime(2026, 4, 20, 12), _data()) is False

    def test_all_conditions_must_match(self):
        rule = ThemeRule(
            when=ThemeRuleCondition(weather="clear", daypart="night"),
            theme="moonphase",
        )
        # Clear but not night → no match
        assert _rule_matches(rule, _now(hour=12), _data(_wx(description="clear sky"))) is False
        # Night but not clear → no match
        assert _rule_matches(rule, _now(hour=23), _data(_wx(description="cloudy"))) is False
        # Both match
        assert _rule_matches(rule, _now(hour=23), _data(_wx(description="clear sky"))) is True


# ---------------------------------------------------------------------------
# resolve_rule_theme
# ---------------------------------------------------------------------------


class TestResolveRuleTheme:
    def test_empty_rules_returns_none(self):
        assert resolve_rule_theme([], _now(), _data()) is None

    def test_first_match_wins(self):
        rules = [
            ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather"),
            ThemeRule(when=ThemeRuleCondition(season="spring"), theme="today"),
        ]
        data = _data(_wx(description="light rain"))
        # Both rules match; first one wins
        assert resolve_rule_theme(rules, _now(month=4), data) == "weather"

    def test_no_match_returns_none(self):
        rules = [ThemeRule(when=ThemeRuleCondition(weather="snow"), theme="weather")]
        data = _data(_wx(description="clear sky"))
        assert resolve_rule_theme(rules, _now(), data) is None


# ---------------------------------------------------------------------------
# Integration with resolve_theme_name priority chain
# ---------------------------------------------------------------------------


class TestResolveThemeNamePriority:
    def test_cli_override_beats_rules(self):
        rules = [ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather")]
        cfg = _cfg(rules=rules, theme="default")
        data = _data(_wx(description="light rain"))
        result = resolve_theme_name(cfg, "terminal", now=_now(), data=data)
        assert result == "terminal"

    def test_rules_beat_schedule(self):
        rules = [ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather")]
        schedule = [ThemeScheduleEntry(time="00:00", theme="minimalist")]
        cfg = _cfg(rules=rules, schedule=schedule)
        data = _data(_wx(description="light rain"))
        result = resolve_theme_name(cfg, None, now=_now(), data=data)
        assert result == "weather"

    def test_schedule_used_when_no_rule_matches(self):
        rules = [ThemeRule(when=ThemeRuleCondition(weather="snow"), theme="weather")]
        schedule = [ThemeScheduleEntry(time="00:00", theme="minimalist")]
        cfg = _cfg(rules=rules, schedule=schedule)
        data = _data(_wx(description="clear sky"))
        result = resolve_theme_name(cfg, None, now=_now(), data=data)
        assert result == "minimalist"

    def test_cfg_theme_used_when_no_rule_or_schedule_matches(self):
        rules = [ThemeRule(when=ThemeRuleCondition(weather="snow"), theme="weather")]
        cfg = _cfg(rules=rules, schedule=[], theme="today")
        data = _data(_wx(description="clear sky"))
        result = resolve_theme_name(cfg, None, now=_now(), data=data)
        assert result == "today"

    def test_weather_rule_skipped_when_data_none(self):
        """Pre-fetch calls pass data=None; weather rules shouldn't match."""
        rules = [ThemeRule(when=ThemeRuleCondition(weather="rain"), theme="weather")]
        cfg = _cfg(rules=rules, theme="default")
        result = resolve_theme_name(cfg, None, now=_now(), data=None)
        assert result == "default"

    def test_rule_theme_random_falls_through_to_random_picker(self):
        """A rule whose theme is 'random' triggers random_theme resolution."""
        rules = [ThemeRule(when=ThemeRuleCondition(), theme="random")]
        cfg = _cfg(rules=rules, theme="default")
        with patch("src.render.random_theme.pick_random_theme", return_value="fantasy"):
            result = resolve_theme_name(cfg, None, now=_now(), data=_data())
        assert result == "fantasy"


# ---------------------------------------------------------------------------
# YAML round-trip: load_config → cfg.theme_rules.rules
# ---------------------------------------------------------------------------


class TestThemeRulesYamlRoundTrip:
    def test_parses_full_rule_shape(self, tmp_path):
        from src.config import load_config

        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            """
theme_rules:
  - when:
      weather: ["rain", "snow"]
      weather_alert_present: true
      daypart: night
      season: winter
      weekday: weekend
    theme: "weather"
  - when:
      daypart: ["dawn", "dusk"]
    theme: "sunrise"
""".strip()
        )
        cfg = load_config(str(cfg_file))
        assert len(cfg.theme_rules.rules) == 2

        r0 = cfg.theme_rules.rules[0]
        assert r0.theme == "weather"
        assert r0.when.weather == ["rain", "snow"]
        assert r0.when.weather_alert_present is True
        assert r0.when.daypart == "night"
        assert r0.when.season == "winter"
        assert r0.when.weekday == "weekend"

        r1 = cfg.theme_rules.rules[1]
        assert r1.theme == "sunrise"
        assert r1.when.daypart == ["dawn", "dusk"]
        # Unset fields stay None — the rule doesn't constrain on them.
        assert r1.when.weather is None
        assert r1.when.weather_alert_present is None

    def test_missing_when_block_defaults_to_empty_condition(self, tmp_path):
        """A rule without ``when:`` matches unconditionally (useful as a fallback)."""
        from src.config import load_config

        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            """
theme_rules:
  - theme: "default"
""".strip()
        )
        cfg = load_config(str(cfg_file))
        assert len(cfg.theme_rules.rules) == 1
        assert cfg.theme_rules.rules[0].theme == "default"
        c = cfg.theme_rules.rules[0].when
        assert c.weather is None
        assert c.daypart is None

    def test_non_dict_entries_are_skipped(self, tmp_path):
        """Malformed list entries don't crash; they're silently dropped."""
        from src.config import load_config

        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            """
theme_rules:
  - "not a dict"
  - when:
      weather: rain
    theme: weather
""".strip()
        )
        cfg = load_config(str(cfg_file))
        assert len(cfg.theme_rules.rules) == 1
        assert cfg.theme_rules.rules[0].theme == "weather"

    def test_non_dict_when_block_becomes_empty_condition(self, tmp_path):
        """`when: "garbage"` is coerced to an empty condition rather than crashing."""
        from src.config import load_config

        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            """
theme_rules:
  - when: "not a mapping"
    theme: "default"
""".strip()
        )
        cfg = load_config(str(cfg_file))
        assert len(cfg.theme_rules.rules) == 1
        assert cfg.theme_rules.rules[0].when.weather is None

    def test_calendar_field_round_trip(self, tmp_path):
        from src.config import load_config

        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            """
theme_rules:
  - when: { calendar: "empty" }
    theme: "qotd"
  - when: { calendar: ["busy", "active"] }
    theme: "today"
""".strip()
        )
        cfg = load_config(str(cfg_file))
        assert cfg.theme_rules.rules[0].when.calendar == "empty"
        assert cfg.theme_rules.rules[1].when.calendar == ["busy", "active"]


# ---------------------------------------------------------------------------
# Calendar state derivation
# ---------------------------------------------------------------------------


class TestCalendarStates:
    def test_empty_when_no_events_today(self):
        now = _now(hour=10)
        assert _calendar_states(now, _data()) == {"empty"}

    def test_yesterdays_event_does_not_count_as_today(self):
        now = _now(hour=10)
        yesterday = now - timedelta(days=1)
        events = [_event(yesterday.replace(hour=9), yesterday.replace(hour=10))]
        assert _calendar_states(now, _data(events=events)) == {"empty"}

    def test_done_when_all_todays_events_have_ended(self):
        now = _now(hour=15)
        events = [
            _event(now.replace(hour=8), now.replace(hour=9)),
            _event(now.replace(hour=10), now.replace(hour=11)),
        ]
        states = _calendar_states(now, _data(events=events))
        assert "done" in states
        assert "empty" not in states
        assert "active" not in states

    def test_active_when_inside_an_event(self):
        now = _now(hour=10, minute=30)
        events = [_event(now.replace(hour=10), now.replace(hour=11))]
        states = _calendar_states(now, _data(events=events))
        assert "active" in states
        assert "done" not in states

    def test_event_ending_exactly_now_is_not_active(self):
        """``start <= now < end`` — an event whose end == now is treated as past."""
        now = _now(hour=11)
        events = [_event(now.replace(hour=10), now.replace(hour=11))]
        states = _calendar_states(now, _data(events=events))
        assert "active" not in states
        assert "done" in states

    def test_upcoming_soon_within_30_minutes(self):
        now = _now(hour=10)
        events = [_event(now + timedelta(minutes=15), now + timedelta(minutes=45))]
        assert "upcoming_soon" in _calendar_states(now, _data(events=events))

    def test_event_31_minutes_out_is_not_upcoming_soon(self):
        now = _now(hour=10)
        events = [_event(now + timedelta(minutes=31), now + timedelta(minutes=60))]
        assert "upcoming_soon" not in _calendar_states(now, _data(events=events))

    def test_event_starting_now_is_active_not_upcoming(self):
        now = _now(hour=10)
        events = [_event(now, now + timedelta(hours=1))]
        states = _calendar_states(now, _data(events=events))
        assert "active" in states
        assert "upcoming_soon" not in states

    def test_busy_at_threshold(self):
        now = _now(hour=10)
        events = [
            _event(now.replace(hour=h), now.replace(hour=h, minute=30)) for h in (8, 9, 11, 13, 14)
        ]
        assert "busy" in _calendar_states(now, _data(events=events))

    def test_not_busy_below_threshold(self):
        now = _now(hour=10)
        events = [
            _event(now.replace(hour=h), now.replace(hour=h, minute=30)) for h in (8, 9, 11, 13)
        ]
        assert "busy" not in _calendar_states(now, _data(events=events))

    def test_birthday_today_matches_month_and_day(self):
        now = _now(year=2026, month=4, day=23)
        # Birthday in a different year but matching month/day
        b = Birthday(name="Alex", date=date(1990, 4, 23))
        assert "birthday_today" in _calendar_states(now, _data(birthdays=[b]))

    def test_birthday_other_day_does_not_match(self):
        now = _now(year=2026, month=4, day=23)
        b = Birthday(name="Alex", date=date(1990, 4, 24))
        assert "birthday_today" not in _calendar_states(now, _data(birthdays=[b]))

    def test_states_can_overlap(self):
        """A busy day with an in-progress event reports both ``busy`` and ``active``."""
        now = _now(hour=10, minute=30)
        events = [_event(now.replace(hour=10), now.replace(hour=11))] + [
            _event(now.replace(hour=h), now.replace(hour=h, minute=30)) for h in (8, 9, 13, 14)
        ]
        states = _calendar_states(now, _data(events=events))
        assert {"busy", "active"} <= states

    def test_tz_aware_now_does_not_raise(self):
        """Regression: naive events must not blow up against a tz-aware ``now``.

        Fetchers strip tzinfo from event datetimes; ``DashboardApp._resolve_now()``
        passes an aware ``now``.  ``_calendar_states`` normalizes internally.
        """
        from datetime import timezone

        aware_now = datetime(2026, 4, 23, 10, 30, tzinfo=timezone.utc)
        naive_event = _event(
            datetime(2026, 4, 23, 10, 0),
            datetime(2026, 4, 23, 11, 0),
        )
        # Must not raise TypeError and must correctly flag ``active``.
        assert "active" in _calendar_states(aware_now, _data(events=[naive_event]))

    def test_all_day_event_spanning_today_is_not_empty(self):
        """Multi-day all-day events (e.g. vacations) count as covering today."""
        now = _now(hour=10)
        # Vacation started yesterday, ends tomorrow (iCal exclusive-end convention).
        vacation = _event(
            datetime(2026, 4, 22),
            datetime(2026, 4, 25),
            summary="Vacation",
            is_all_day=True,
        )
        states = _calendar_states(now, _data(events=[vacation]))
        assert "empty" not in states

    def test_all_day_event_contributes_to_busy_count(self):
        """Spanning all-day events count toward the ``busy`` threshold."""
        now = _now(hour=10)
        vacation = _event(
            datetime(2026, 4, 22),
            datetime(2026, 4, 25),
            is_all_day=True,
        )
        timed = [
            _event(now.replace(hour=h), now.replace(hour=h, minute=30)) for h in (8, 11, 13, 14)
        ]
        assert "busy" in _calendar_states(now, _data(events=[vacation] + timed))

    def test_all_day_event_does_not_produce_active(self):
        """``active`` is reserved for timed events — all-day events don't apply."""
        now = _now(hour=10)
        vacation = _event(
            datetime(2026, 4, 22),
            datetime(2026, 4, 25),
            is_all_day=True,
        )
        assert "active" not in _calendar_states(now, _data(events=[vacation]))

    def test_all_day_only_day_does_not_produce_done(self):
        """A day with only an ongoing all-day event isn't ``done`` either."""
        now = _now(hour=22)
        vacation = _event(
            datetime(2026, 4, 22),
            datetime(2026, 4, 25),
            is_all_day=True,
        )
        assert "done" not in _calendar_states(now, _data(events=[vacation]))

    def test_event_ending_today_excluded_by_exclusive_end(self):
        """An all-day event with end=today does not cover today (exclusive end)."""
        now = _now(year=2026, month=4, day=23, hour=10)
        ended = _event(
            datetime(2026, 4, 22),
            datetime(2026, 4, 23),
            is_all_day=True,
        )
        assert "empty" in _calendar_states(now, _data(events=[ended]))

    def test_empty_not_emitted_when_events_source_missing(self):
        """Calendar fetch outage with no cache → no event-derived states fire."""
        now = _now(hour=10)
        states = _calendar_states(now, _data(events_loaded=False))
        assert "empty" not in states

    def test_birthday_today_not_emitted_when_birthdays_source_missing(self):
        now = _now(year=2026, month=4, day=23)
        b = Birthday(name="Alex", date=date(1990, 4, 23))
        data = _data(birthdays=[b], birthdays_loaded=False)
        assert "birthday_today" not in _calendar_states(now, data)

    def test_events_unavailable_still_allows_birthday_today(self):
        """Birthdays and events are independent sources — one can skip without the other."""
        now = _now(year=2026, month=4, day=23)
        b = Birthday(name="Alex", date=date(1990, 4, 23))
        data = _data(birthdays=[b], events_loaded=False)
        assert _calendar_states(now, data) == {"birthday_today"}


# ---------------------------------------------------------------------------
# Calendar rule matching
# ---------------------------------------------------------------------------


class TestCalendarRule:
    def test_calendar_empty_matches(self):
        rule = ThemeRule(when=ThemeRuleCondition(calendar="empty"), theme="qotd")
        assert _rule_matches(rule, _now(), _data()) is True

    def test_calendar_empty_does_not_match_when_events_exist(self):
        now = _now(hour=10)
        rule = ThemeRule(when=ThemeRuleCondition(calendar="empty"), theme="qotd")
        events = [_event(now.replace(hour=14), now.replace(hour=15))]
        assert _rule_matches(rule, now, _data(events=events)) is False

    def test_calendar_list_matches_any(self):
        now = _now(hour=15)
        rule = ThemeRule(
            when=ThemeRuleCondition(calendar=["empty", "done"]),
            theme="qotd",
        )
        events = [_event(now.replace(hour=8), now.replace(hour=9))]
        assert _rule_matches(rule, now, _data(events=events)) is True

    def test_calendar_skips_when_data_is_none(self):
        """Pre-fetch resolution passes data=None — calendar rules silently skip."""
        rule = ThemeRule(when=ThemeRuleCondition(calendar="empty"), theme="qotd")
        assert _rule_matches(rule, _now(), None) is False

    def test_calendar_combines_with_other_conditions(self):
        now = datetime(2026, 4, 25, 10)  # Saturday
        rule = ThemeRule(
            when=ThemeRuleCondition(calendar="empty", weekday="weekend"),
            theme="qotd",
        )
        assert _rule_matches(rule, now, _data()) is True
        # Weekday — same calendar state, but condition fails on weekday
        assert _rule_matches(rule, datetime(2026, 4, 20, 10), _data()) is False

    def test_calendar_unknown_value_does_not_match(self):
        """Unknown calendar tokens never match — validation surfaces them as warnings."""
        rule = ThemeRule(when=ThemeRuleCondition(calendar="bogus"), theme="qotd")
        assert _rule_matches(rule, _now(), _data()) is False

    def test_calendar_empty_does_not_fire_on_fetch_outage(self):
        """No cached events + fetch failure must NOT trip ``calendar: empty`` rules.

        Mirrors the weather-rule behavior: missing data silently skips rather
        than matching a false-positive empty state.
        """
        rule = ThemeRule(when=ThemeRuleCondition(calendar="empty"), theme="qotd")
        assert _rule_matches(rule, _now(), _data(events_loaded=False)) is False
