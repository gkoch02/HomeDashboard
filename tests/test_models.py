"""Tests for src/data/models.py — dataclass construction, defaults, and equality."""

from datetime import date, datetime, timezone
from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    StalenessLevel,
    WeatherAlert,
    WeatherData,
)


class TestStalenessLevel:
    def test_enum_values(self):
        assert StalenessLevel.FRESH.value == "fresh"
        assert StalenessLevel.AGING.value == "aging"
        assert StalenessLevel.STALE.value == "stale"
        assert StalenessLevel.EXPIRED.value == "expired"

    def test_all_four_levels_exist(self):
        levels = list(StalenessLevel)
        assert len(levels) == 4

    def test_ordering_by_name(self):
        names = {level.name for level in StalenessLevel}
        assert names == {"FRESH", "AGING", "STALE", "EXPIRED"}


class TestCalendarEvent:
    def _make(self, **kwargs):
        defaults = dict(
            summary="Test Event",
            start=datetime(2026, 3, 22, 10, 0),
            end=datetime(2026, 3, 22, 11, 0),
        )
        defaults.update(kwargs)
        return CalendarEvent(**defaults)

    def test_basic_construction(self):
        evt = self._make()
        assert evt.summary == "Test Event"
        assert evt.start == datetime(2026, 3, 22, 10, 0)
        assert evt.end == datetime(2026, 3, 22, 11, 0)

    def test_defaults_for_optional_fields(self):
        evt = self._make()
        assert evt.is_all_day is False
        assert evt.location is None
        assert evt.calendar_name is None
        assert evt.event_id is None

    def test_all_day_flag(self):
        evt = self._make(is_all_day=True)
        assert evt.is_all_day is True

    def test_location_field(self):
        evt = self._make(location="123 Main St, Springfield")
        assert evt.location == "123 Main St, Springfield"

    def test_calendar_name_field(self):
        evt = self._make(calendar_name="Work")
        assert evt.calendar_name == "Work"

    def test_event_id_field(self):
        evt = self._make(event_id="abc123")
        assert evt.event_id == "abc123"

    def test_equality_same_data(self):
        e1 = self._make()
        e2 = self._make()
        assert e1 == e2

    def test_inequality_different_summary(self):
        e1 = self._make(summary="A")
        e2 = self._make(summary="B")
        assert e1 != e2


class TestDayForecast:
    def test_basic_construction(self):
        fc = DayForecast(
            date=date(2026, 3, 23),
            high=65.0,
            low=48.0,
            icon="02d",
            description="partly cloudy",
        )
        assert fc.date == date(2026, 3, 23)
        assert fc.high == 65.0
        assert fc.low == 48.0
        assert fc.icon == "02d"
        assert fc.description == "partly cloudy"
        assert fc.precip_chance is None

    def test_precip_chance(self):
        fc = DayForecast(
            date=date(2026, 3, 24),
            high=55.0,
            low=42.0,
            icon="10d",
            description="rain",
            precip_chance=0.75,
        )
        assert fc.precip_chance == 0.75

    def test_precip_chance_zero(self):
        fc = DayForecast(
            date=date(2026, 3, 25),
            high=70.0,
            low=55.0,
            icon="01d",
            description="clear",
            precip_chance=0.0,
        )
        assert fc.precip_chance == 0.0


class TestWeatherAlert:
    def test_basic_construction(self):
        alert = WeatherAlert(event="Flood Watch")
        assert alert.event == "Flood Watch"

    def test_empty_event_string(self):
        alert = WeatherAlert(event="")
        assert alert.event == ""

    def test_equality(self):
        assert WeatherAlert(event="Wind Advisory") == WeatherAlert(event="Wind Advisory")


class TestWeatherData:
    def _make(self, **kwargs):
        defaults = dict(
            current_temp=72.0,
            current_icon="01d",
            current_description="clear sky",
            high=78.0,
            low=58.0,
            humidity=45,
        )
        defaults.update(kwargs)
        return WeatherData(**defaults)

    def test_required_fields(self):
        w = self._make()
        assert w.current_temp == 72.0
        assert w.current_icon == "01d"
        assert w.current_description == "clear sky"
        assert w.high == 78.0
        assert w.low == 58.0
        assert w.humidity == 45

    def test_optional_defaults_none(self):
        w = self._make()
        assert w.feels_like is None
        assert w.wind_speed is None
        assert w.wind_deg is None
        assert w.pressure is None
        assert w.uv_index is None
        assert w.sunrise is None
        assert w.sunset is None

    def test_empty_lists_by_default(self):
        w = self._make()
        assert w.forecast == []
        assert w.alerts == []

    def test_forecast_list(self):
        fc = DayForecast(
            date=date(2026, 3, 23),
            high=70.0, low=52.0,
            icon="02d", description="cloudy",
        )
        w = self._make(forecast=[fc])
        assert len(w.forecast) == 1
        assert w.forecast[0].icon == "02d"

    def test_alerts_list(self):
        w = self._make(alerts=[WeatherAlert(event="Winter Storm Warning")])
        assert len(w.alerts) == 1
        assert w.alerts[0].event == "Winter Storm Warning"

    def test_all_optional_fields(self):
        sunrise = datetime(2026, 3, 22, 6, 30, tzinfo=timezone.utc)
        sunset = datetime(2026, 3, 22, 19, 45, tzinfo=timezone.utc)
        w = self._make(
            feels_like=68.0,
            wind_speed=10.5,
            wind_deg=180.0,
            pressure=1013.0,
            uv_index=5.2,
            sunrise=sunrise,
            sunset=sunset,
        )
        assert w.feels_like == 68.0
        assert w.wind_speed == 10.5
        assert w.wind_deg == 180.0
        assert w.pressure == 1013.0
        assert w.uv_index == 5.2
        assert w.sunrise == sunrise
        assert w.sunset == sunset


class TestBirthday:
    def test_basic_construction(self):
        b = Birthday(name="Alice", date=date(1990, 4, 15))
        assert b.name == "Alice"
        assert b.date == date(1990, 4, 15)
        assert b.age is None

    def test_with_age(self):
        b = Birthday(name="Bob", date=date(1985, 7, 20), age=40)
        assert b.age == 40

    def test_equality(self):
        b1 = Birthday(name="Carol", date=date(2000, 1, 1))
        b2 = Birthday(name="Carol", date=date(2000, 1, 1))
        assert b1 == b2

    def test_inequality_different_name(self):
        b1 = Birthday(name="Dave", date=date(1995, 3, 10))
        b2 = Birthday(name="Eve", date=date(1995, 3, 10))
        assert b1 != b2


class TestDashboardData:
    def test_empty_construction(self):
        d = DashboardData()
        assert d.events == []
        assert d.weather is None
        assert d.birthdays == []
        assert d.is_stale is False
        assert d.stale_sources == []
        assert d.source_staleness == {}

    def test_fetched_at_defaults_to_now(self):
        before = datetime.now()
        d = DashboardData()
        after = datetime.now()
        assert before <= d.fetched_at <= after

    def test_with_data(self):
        evt = CalendarEvent(
            summary="Meeting",
            start=datetime(2026, 3, 22, 9, 0),
            end=datetime(2026, 3, 22, 10, 0),
        )
        weather = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear",
            high=65.0,
            low=50.0,
            humidity=40,
        )
        birthday = Birthday(name="Frank", date=date(1988, 3, 22))

        d = DashboardData(
            events=[evt],
            weather=weather,
            birthdays=[birthday],
        )
        assert len(d.events) == 1
        assert d.weather is not None
        assert len(d.birthdays) == 1

    def test_stale_flags(self):
        d = DashboardData(
            is_stale=True,
            stale_sources=["events", "weather"],
            source_staleness={
                "events": StalenessLevel.STALE,
                "weather": StalenessLevel.AGING,
            },
        )
        assert d.is_stale is True
        assert "events" in d.stale_sources
        assert d.source_staleness["events"] == StalenessLevel.STALE
        assert d.source_staleness["weather"] == StalenessLevel.AGING

    def test_independent_mutable_defaults(self):
        """Each DashboardData instance gets its own list/dict, not a shared reference."""
        d1 = DashboardData()
        d2 = DashboardData()
        d1.events.append(CalendarEvent(
            summary="X",
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 1, 1),
        ))
        assert d2.events == []
