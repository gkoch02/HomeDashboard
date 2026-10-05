"""Tests for src/services/theme_rules.py — context-aware theme selection."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.config import (
    ThemeRule,
    ThemeRuleCondition,
    ThemeScheduleEntry,
)
from src.data.models import (
    AirQualityData,
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
    @pytest.mark.parametrize(
        "month, season",
        [(4, "spring"), (7, "summer"), (10, "fall"), (1, "winter")],
        ids=["april", "july", "october", "january"],
    )
    def test_month_maps_to_season(self, month, season):
        assert _current_season(_now(month=month)) == season


class TestCurrentWeekday:
    @pytest.mark.parametrize(
        "now, expected",
        [
            (datetime(2026, 4, 20, 12), ("monday", "weekday")),
            (datetime(2026, 4, 25, 12), ("saturday", "weekend")),
        ],
        ids=["monday", "saturday"],
    )
    def test_day_name_and_kind(self, now, expected):
        assert _current_weekday(now) == expected


class TestCurrentDaypart:
    def test_fixed_ranges_without_weather(self):
        # Fallback ranges (no sunrise/sunset data) anchor on a nominal
        # 06:30 sunrise / 18:30 sunset, so 5-8 = dawn, 8-17:30 = day,
        # 17:30-18:30 = dusk, everything else = night.
        assert _current_daypart(_now(hour=6), None) == "dawn"
        assert _current_daypart(_now(hour=9), None) == "day"
        assert _current_daypart(_now(hour=14), None) == "day"
        assert _current_daypart(_now(hour=18), None) == "dusk"
        assert _current_daypart(_now(hour=23), None) == "night"
        assert _current_daypart(_now(hour=3), None) == "night"

    @pytest.mark.parametrize(
        ("hour", "minute", "expected"),
        [
            (3, 0, "night"),
            (6, 30, "dawn"),
            (10, 0, "day"),
            (15, 0, "day"),
            (18, 30, "day"),
            (18, 50, "dusk"),
            (19, 43, "dusk"),
            (19, 50, "night"),
            (21, 0, "night"),
            (23, 0, "night"),
        ],
        ids=[
            "before-dawn-window-is-night",
            "within-90-min-of-sunrise-is-dawn",
            "mid-morning-is-day",
            "afternoon-is-day",
            "just-before-dusk-start-is-day",
            "within-60-min-of-sunset-is-dusk",
            "sunset-itself-is-dusk",
            "just-past-sunset-is-night",
            "evening-is-night",
            "late-night-is-night",
        ],
    )
    def test_bucket_from_sun_times(self, hour, minute, expected):
        """With a 06:05 sunrise and 19:43 sunset: dawn is sunrise +/- 90 min, dusk is the
        hour up to and including sunset, day lies between, and everything else is night
        (there is no dusk window after sunset)."""
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        assert _current_daypart(_now(hour=hour, minute=minute), w) == expected

    def test_sun_times_from_a_previous_day_still_bucket_by_time_of_day(self):
        """Cached weather across midnight carries yesterday's sun times (#293)."""
        w = _wx(
            sunrise=datetime(2026, 4, 22, 6, 5),
            sunset=datetime(2026, 4, 22, 19, 43),
        )
        assert _current_daypart(_now(hour=7), w) == "dawn"
        assert _current_daypart(_now(hour=12), w) == "day"
        assert _current_daypart(_now(hour=19), w) == "dusk"
        assert _current_daypart(_now(hour=22), w) == "night"

    def test_aware_sun_times_are_read_in_nows_zone(self):
        from zoneinfo import ZoneInfo

        la = ZoneInfo("America/Los_Angeles")
        utc = ZoneInfo("UTC")
        # 06:05 PDT sunrise expressed in UTC is 13:05 the same day.
        w = _wx(
            sunrise=datetime(2026, 4, 23, 13, 5, tzinfo=utc),
            sunset=datetime(2026, 4, 24, 2, 43, tzinfo=utc),
        )
        assert _current_daypart(datetime(2026, 4, 23, 6, 30, tzinfo=la), w) == "dawn"
        assert _current_daypart(datetime(2026, 4, 23, 19, 0, tzinfo=la), w) == "dusk"

    def test_rule_daypart_day_matches_only_day_bucket(self):
        """``daypart: day`` matches the new dedicated ``day`` bucket."""
        rule = ThemeRule(when=ThemeRuleCondition(daypart="day"), theme="today")
        w = _wx(
            sunrise=datetime(2026, 4, 23, 6, 5),
            sunset=datetime(2026, 4, 23, 19, 43),
        )
        assert _rule_matches(rule, _now(hour=10), _data(w)) is True  # day
        assert _rule_matches(rule, _now(hour=15), _data(w)) is True  # day
        assert _rule_matches(rule, _now(hour=23), _data(w)) is False  # night
        assert _rule_matches(rule, _now(hour=6, minute=30), _data(w)) is False  # dawn


# ---------------------------------------------------------------------------
# _rule_matches
# ---------------------------------------------------------------------------


class TestRuleMatches:
    def test_empty_condition_always_matches(self):
        rule = ThemeRule(when=ThemeRuleCondition(), theme="default")
        assert _rule_matches(rule, _now(), _data()) is True

    @pytest.mark.parametrize(
        ("weather", "description", "expected"),
        [
            ("rain", "light rain", True),
            ("rain", "clear sky", False),
            (["rain", "snow", "thunderstorm"], "heavy snow", True),
        ],
        ids=["substring-match", "no-match", "list-of-alternatives"],
    )
    def test_weather_rule_matches_description(self, weather, description, expected):
        """``weather`` matches a substring of the description; a list matches any entry."""
        rule = ThemeRule(when=ThemeRuleCondition(weather=weather), theme="weather")
        data = _data(_wx(description=description))
        assert _rule_matches(rule, _now(), data) is expected

    @pytest.mark.parametrize(
        ("when", "data"),
        [
            ({"weather": "rain"}, None),
            ({"weather": "rain"}, _data(None)),
            ({"weather_alert_present": True}, None),
        ],
        ids=["weather-no-data", "weather-data-without-weather", "alert-present-no-data"],
    )
    def test_weather_dependent_rule_fails_without_weather(self, when, data):
        """Rules that need weather data silently fail when data or its weather is missing."""
        rule = ThemeRule(when=ThemeRuleCondition(**when), theme="weather")
        assert _rule_matches(rule, _now(), data) is False

    def test_alert_present_true_matches_when_alerts_exist(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather_alert_present=True), theme="message")
        data = _data(_wx(alerts=[WeatherAlert(event="Tornado Watch")]))
        assert _rule_matches(rule, _now(), data) is True

    def test_alert_present_false_matches_when_no_alerts(self):
        rule = ThemeRule(when=ThemeRuleCondition(weather_alert_present=False), theme="default")
        data = _data(_wx(alerts=[]))
        assert _rule_matches(rule, _now(), data) is True

    def test_season_autumn_alias_for_fall(self):
        rule = ThemeRule(when=ThemeRuleCondition(season="autumn"), theme="today")
        # October is fall in our bucket
        assert _rule_matches(rule, _now(month=10), _data()) is True

    @pytest.mark.parametrize(
        ("when", "matching", "other"),
        [
            ({"daypart": "night"}, _now(hour=23), _now(hour=12)),
            ({"season": "spring"}, _now(month=4), _now(month=11)),
            ({"weekday": "monday"}, datetime(2026, 4, 20, 12), datetime(2026, 4, 21, 12)),
            ({"weekday": "weekend"}, datetime(2026, 4, 25, 12), datetime(2026, 4, 20, 12)),
        ],
        ids=["daypart", "season", "weekday_day_name", "weekday_weekend_key"],
    )
    def test_clock_condition(self, when, matching, other):
        """A daypart, season or weekday condition matches inside its window only."""
        rule = ThemeRule(when=ThemeRuleCondition(**when), theme="today")
        assert _rule_matches(rule, matching, _data()) is True
        assert _rule_matches(rule, other, _data()) is False

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
    @pytest.mark.parametrize(
        ("rule_weather", "schedule_theme", "cfg_theme", "override", "data", "expected"),
        [
            ("rain", None, "default", "terminal", _data(_wx("light rain")), "terminal"),
            ("rain", "minimalist", "default", None, _data(_wx("light rain")), "weather"),
            ("snow", "minimalist", "default", None, _data(_wx("clear sky")), "minimalist"),
            ("snow", None, "today", None, _data(_wx("clear sky")), "today"),
            ("rain", None, "default", None, None, "default"),
        ],
        ids=[
            "cli-override-beats-rules",
            "rules-beat-schedule",
            "schedule-when-no-rule-matches",
            "cfg-theme-when-nothing-matches",
            "weather-rule-skipped-pre-fetch",
        ],
    )
    def test_priority_chain(
        self, rule_weather, schedule_theme, cfg_theme, override, data, expected
    ):
        """CLI override > matching rule > schedule > ``cfg.theme``; on the pre-fetch pass
        (``data=None``) a weather rule cannot match and resolution falls through."""
        rules = [ThemeRule(when=ThemeRuleCondition(weather=rule_weather), theme="weather")]
        schedule = (
            [ThemeScheduleEntry(time="00:00", theme=schedule_theme)] if schedule_theme else []
        )
        cfg = _cfg(rules=rules, schedule=schedule, theme=cfg_theme)
        assert resolve_theme_name(cfg, override, now=_now(), data=data) == expected

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

    @pytest.mark.parametrize(
        ("hour", "minute", "active"),
        [(10, 30, True), (11, 0, False)],
        ids=["inside-event-is-active", "event-ending-exactly-now-is-done"],
    )
    def test_active_versus_done(self, hour, minute, active):
        """``start <= now < end`` is active; an event whose end equals now is done."""
        now = _now(hour=hour, minute=minute)
        events = [_event(now.replace(hour=10, minute=0), now.replace(hour=11, minute=0))]
        states = _calendar_states(now, _data(events=events))
        assert ("active" in states) is active
        assert ("done" in states) is not active

    @pytest.mark.parametrize(
        ("lead_minutes", "expected"),
        [(15, True), (31, False)],
        ids=["15-minutes-out", "31-minutes-out"],
    )
    def test_upcoming_soon_window(self, lead_minutes, expected):
        """``upcoming_soon`` covers events starting within the next 30 minutes."""
        now = _now(hour=10)
        start = now + timedelta(minutes=lead_minutes)
        events = [_event(start, start + timedelta(minutes=30))]
        assert ("upcoming_soon" in _calendar_states(now, _data(events=events))) is expected

    def test_event_starting_now_is_active_not_upcoming(self):
        now = _now(hour=10)
        events = [_event(now, now + timedelta(hours=1))]
        states = _calendar_states(now, _data(events=events))
        assert "active" in states
        assert "upcoming_soon" not in states

    @pytest.mark.parametrize(
        ("hours", "expected"),
        [((8, 9, 11, 13, 14), True), ((8, 9, 11, 13), False)],
        ids=["five-events-at-threshold", "four-events-below-threshold"],
    )
    def test_busy_threshold(self, hours, expected):
        """Five events in a day is ``busy``; four is not."""
        now = _now(hour=10)
        events = [_event(now.replace(hour=h), now.replace(hour=h, minute=30)) for h in hours]
        assert ("busy" in _calendar_states(now, _data(events=events))) is expected

    @pytest.mark.parametrize(
        ("birthday", "expected"),
        [(date(1990, 4, 23), True), (date(1990, 4, 24), False)],
        ids=["same-month-and-day", "other-day"],
    )
    def test_birthday_today_matches_month_and_day(self, birthday, expected):
        """``birthday_today`` compares month and day only, ignoring the birth year."""
        now = _now(year=2026, month=4, day=23)
        b = Birthday(name="Alex", date=birthday)
        assert ("birthday_today" in _calendar_states(now, _data(birthdays=[b]))) is expected

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

    @pytest.mark.parametrize(
        ("hour", "state"),
        [(10, "active"), (22, "done")],
        ids=["not-active", "not-done"],
    )
    def test_all_day_event_produces_neither_active_nor_done(self, hour, state):
        """``active`` and ``done`` are reserved for timed events; an ongoing all-day
        event alone never produces them."""
        now = _now(hour=hour)
        vacation = _event(
            datetime(2026, 4, 22),
            datetime(2026, 4, 25),
            is_all_day=True,
        )
        assert state not in _calendar_states(now, _data(events=[vacation]))

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
    @pytest.mark.parametrize(
        ("calendar", "expected"),
        [("empty", True), ("bogus", False)],
        ids=["empty-matches-empty-day", "unknown-token-never-matches"],
    )
    def test_calendar_token_on_empty_day(self, calendar, expected):
        """``empty`` matches a day with no events; unknown tokens never match (validation
        surfaces them as warnings)."""
        rule = ThemeRule(when=ThemeRuleCondition(calendar=calendar), theme="qotd")
        assert _rule_matches(rule, _now(), _data()) is expected

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

    @pytest.mark.parametrize(
        "data",
        [None, _data(events_loaded=False)],
        ids=["pre-fetch-data-none", "fetch-outage-no-cache"],
    )
    def test_calendar_empty_skips_without_event_data(self, data):
        """Missing event data silently skips a calendar rule, as with weather rules, rather
        than matching a false-positive ``empty`` state."""
        rule = ThemeRule(when=ThemeRuleCondition(calendar="empty"), theme="qotd")
        assert _rule_matches(rule, _now(), data) is False

    def test_calendar_combines_with_other_conditions(self):
        now = datetime(2026, 4, 25, 10)  # Saturday
        rule = ThemeRule(
            when=ThemeRuleCondition(calendar="empty", weekday="weekend"),
            theme="qotd",
        )
        assert _rule_matches(rule, now, _data()) is True
        # Weekday — same calendar state, but condition fails on weekday
        assert _rule_matches(rule, datetime(2026, 4, 20, 10), _data()) is False


# ---------------------------------------------------------------------------
# Numeric conditions — temperature and AQI (#215)
# ---------------------------------------------------------------------------


def _aq(aqi: int) -> AirQualityData:
    return AirQualityData(aqi=aqi, category="Moderate", pm25=12.0)


def _data_with_aq(air_quality: AirQualityData | None, **kwargs) -> DashboardData:
    data = _data(**kwargs)
    data.air_quality = air_quality
    return data


def _rule(theme: str = "weatherglass", **when) -> ThemeRule:
    return ThemeRule(when=ThemeRuleCondition(**when), theme=theme)


class TestTemperatureConditions:
    @pytest.mark.parametrize(
        "bound, temp, matches",
        [
            ({"temp_at_most": 32.0}, 28.0, True),
            ({"temp_at_most": 32.0}, 32.0, True),
            ({"temp_at_most": 32.0}, 33.0, False),
            ({"temp_at_least": 90.0}, 95.0, True),
            ({"temp_at_least": 90.0}, 90.0, True),
            ({"temp_at_least": 90.0}, 89.9, False),
            ({"temp_at_most": 0.0}, -4.0, True),
        ],
        ids=[
            "at_most_below",
            "at_most_inclusive",
            "at_most_above",
            "at_least_above",
            "at_least_inclusive",
            "at_least_below",
            "negative_temperature",
        ],
    )
    def test_single_bound(self, bound, temp, matches):
        data = _data(weather=_wx(current_temp=temp))
        assert _rule_matches(_rule(**bound), _now(), data) is matches

    def test_both_bounds_form_a_band(self):
        rule = _rule(temp_at_least=60.0, temp_at_most=75.0)
        assert _rule_matches(rule, _now(), _data(weather=_wx(current_temp=68.0)))
        assert not _rule_matches(rule, _now(), _data(weather=_wx(current_temp=55.0)))
        assert not _rule_matches(rule, _now(), _data(weather=_wx(current_temp=80.0)))

    def test_skips_silently_when_weather_is_absent(self):
        """Same contract as the weather condition: no data means no match."""
        assert not _rule_matches(_rule(temp_at_most=32.0), _now(), _data(weather=None))

    def test_skips_silently_on_the_pre_fetch_pass(self):
        assert not _rule_matches(_rule(temp_at_most=32.0), _now(), None)
        assert not _rule_matches(_rule(temp_at_least=90.0), _now(), None)

    def test_combines_with_other_conditions(self):
        rule = _rule(temp_at_most=32.0, daypart="day")
        cold_day = _data(weather=_wx(current_temp=20.0))
        assert _rule_matches(rule, _now(hour=12), cold_day)
        assert not _rule_matches(rule, _now(hour=23), cold_day)

    def test_unset_bounds_do_not_constrain(self):
        assert _rule_matches(_rule(daypart="day"), _now(hour=12), _data(weather=_wx()))


class TestAqiCondition:
    @pytest.mark.parametrize(
        ("aqi", "expected"),
        [(150, True), (100, True), (42, False)],
        ids=["above", "at-threshold-inclusive", "below"],
    )
    def test_matches_at_or_above_the_threshold(self, aqi, expected):
        assert _rule_matches(_rule(aqi_at_least=100), _now(), _data_with_aq(_aq(aqi))) is expected

    def test_skips_silently_when_air_quality_is_absent(self):
        """The common case: PurpleAir is optional, so the source is often missing."""
        assert not _rule_matches(_rule(aqi_at_least=100), _now(), _data_with_aq(None))

    def test_skips_silently_on_the_pre_fetch_pass(self):
        assert not _rule_matches(_rule(aqi_at_least=100), _now(), None)

    def test_first_match_still_wins_across_numeric_rules(self):
        rules = [
            _rule("air_quality", aqi_at_least=150),
            _rule("weather", aqi_at_least=50),
        ]
        data = _data_with_aq(_aq(160))
        assert resolve_rule_theme(rules, _now(), data) == "air_quality"

    def test_falls_through_when_nothing_matches(self):
        rules = [_rule("air_quality", aqi_at_least=150)]
        assert resolve_rule_theme(rules, _now(), _data_with_aq(_aq(20))) is None


class TestNumericConditionParsing:
    """load_config() must not turn an unreadable threshold into 'no constraint'."""

    def _rules_from(self, tmp_path, yaml_text: str):
        from src.config import load_config

        path = tmp_path / "rules.yaml"
        path.write_text(yaml_text)
        return load_config(str(path)).theme_rules.rules

    def test_numeric_thresholds_parse(self, tmp_path):
        rules = self._rules_from(
            tmp_path,
            "theme_rules:\n"
            "  - when: {temp_at_most: 32, temp_at_least: 10, aqi_at_least: 101}\n"
            "    theme: weatherglass\n",
        )
        assert len(rules) == 1
        assert rules[0].when.temp_at_most == 32.0
        assert rules[0].when.temp_at_least == 10.0
        assert rules[0].when.aqi_at_least == 101

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("32.5", 32.5), ('"32"', 32.0)],
        ids=["float", "quoted-numeric-string"],
    )
    def test_temperature_threshold_reads_as_float(self, tmp_path, value, expected):
        """A float survives, and a quoted number is still a number."""
        rules = self._rules_from(
            tmp_path,
            f"theme_rules:\n  - when: {{temp_at_most: {value}}}\n    theme: weatherglass\n",
        )
        assert rules[0].when.temp_at_most == expected

    def test_unset_thresholds_are_none(self, tmp_path):
        rules = self._rules_from(
            tmp_path, "theme_rules:\n  - when: {weekday: weekend}\n    theme: today\n"
        )
        assert rules[0].when.temp_at_most is None
        assert rules[0].when.temp_at_least is None
        assert rules[0].when.aqi_at_least is None

    @pytest.mark.parametrize(
        "bad_rule",
        [
            "  - when: {temp_at_most: chilly}\n    theme: weatherglass\n",
            "  - when: {aqi_at_least: [100]}\n    theme: air_quality\n",
        ],
        ids=["unreadable_string", "list"],
    )
    def test_unreadable_threshold_drops_the_rule(self, tmp_path, bad_rule):
        """Widening the rule to 'always' would be worse than dropping it.

        The list case matters separately: int()/float() reject it with TypeError,
        not ValueError, and letting that escape crashes load_config() itself —
        every renderer run, --check-config, and both web pages — over one rule.
        """
        rules = self._rules_from(
            tmp_path,
            "theme_rules:\n" + bad_rule + "  - when: {weekday: weekend}\n    theme: today\n",
        )
        assert [r.theme for r in rules] == ["today"]

    @pytest.mark.parametrize(
        "yaml_rule",
        [
            "  - when: {temp_at_most: {a: 1}}\n    theme: weatherglass\n",
            "  - when: {aqi_at_least: yes}\n    theme: air_quality\n",
        ],
        ids=["mapping", "boolean"],
    )
    def test_non_numeric_shape_drops_the_rule(self, tmp_path, yaml_rule):
        """A mapping is unreadable, and a boolean is rejected because YAML 1.1 reads 'yes'
        as True and int(True) is a plausible-looking 1."""
        assert self._rules_from(tmp_path, "theme_rules:\n" + yaml_rule) == []

    def test_an_explicit_null_threshold_means_unset(self, tmp_path):
        """`null` is absence, not a malformed value — the rule survives."""
        rules = self._rules_from(
            tmp_path,
            "theme_rules:\n  - when: {aqi_at_least: null, weekday: weekend}\n    theme: today\n",
        )
        assert [r.theme for r in rules] == ["today"]
        assert rules[0].when.aqi_at_least is None
