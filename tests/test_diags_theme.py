"""Tests for the diags theme and its render pipeline integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    StalenessLevel,
    WeatherAlert,
    WeatherData,
)
from src.render.canvas import render_dashboard
from src.render.quantize import flatten_pixels
from src.render.theme import AVAILABLE_THEMES, load_theme
from src.render.themes.diags import diags_theme

# Assertion discipline (see #229): the render tests here asserted only
# isinstance/size, or nothing at all — all 40 passed with draw_diags stubbed
# to a no-op. They now measure ink per column: the panel is two columns split
# by a vertical divider at x=400, weather/forecast/host on the left and
# calendar/air-quality/birthdays/status on the right, so each test measures
# the column that owns what it changes. The three truncation caps
# (_MAX_BIRTHDAYS=5, _MAX_FORECAST=6, _MAX_ALERTS=2) are pinned by asserting
# that going past each one renders byte-identically to hitting it exactly.

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_data(today: date | None = None) -> DashboardData:
    today = today or date(2026, 3, 24)  # Monday
    now = datetime.combine(today, datetime.min.time().replace(hour=9, minute=15))
    return DashboardData(
        fetched_at=now,
        events=[
            CalendarEvent(
                summary="Team Standup",
                start=datetime.combine(today, datetime.min.time().replace(hour=9)),
                end=datetime.combine(today, datetime.min.time().replace(hour=9, minute=30)),
            ),
            CalendarEvent(
                summary="Design review",
                start=datetime.combine(
                    today + timedelta(days=2), datetime.min.time().replace(hour=14)
                ),
                end=datetime.combine(
                    today + timedelta(days=2), datetime.min.time().replace(hour=15)
                ),
            ),
        ],
        weather=WeatherData(
            current_temp=72.0,
            current_icon="02d",
            current_description="partly cloudy",
            high=78.0,
            low=61.0,
            humidity=54,
            feels_like=69.0,
            wind_speed=12.0,
            wind_deg=315.0,
            pressure=1013.0,
            uv_index=4.0,
            sunrise=datetime.combine(today, datetime.min.time().replace(hour=6, minute=42)),
            sunset=datetime.combine(today, datetime.min.time().replace(hour=19, minute=18)),
            forecast=[
                DayForecast(
                    date=today + timedelta(days=i + 1),
                    high=70.0 + i,
                    low=55.0 + i,
                    icon="02d",
                    description="partly cloudy",
                    precip_chance=0.20,
                )
                for i in range(5)
            ],
        ),
        air_quality=AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            pm10=14.2,
            pm1=6.1,
            sensor_id=99999,
            temperature=68.4,
            humidity=52.0,
            pressure=1014.3,
        ),
        birthdays=[
            Birthday(name="Alice Smith", date=today + timedelta(days=1), age=34),
            Birthday(name="Bob Jones", date=today + timedelta(days=9)),
        ],
        source_staleness={
            "weather": StalenessLevel.FRESH,
            "events": StalenessLevel.AGING,
        },
    )


# ---------------------------------------------------------------------------
# Ink measurement
# ---------------------------------------------------------------------------

# Column geometry, from diags_panel's own layout constants.
HEADER = (0, 0, 800, 28)
LEFT_COL = (10, 34, 388, 480)
RIGHT_COL = (412, 34, 788, 480)
_DIVIDER_X = 400


def _ink(img, box=None) -> int:
    """Count ink (value-0) pixels, optionally only inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _divider_height(img) -> int:
    """Inked rows in the vertical column divider."""
    px = flatten_pixels(img)
    width = img.width
    return sum(1 for y in range(28, img.height - 1) if px[y * width + _DIVIDER_X] == 0)


def _section_rules(img, column) -> int:
    """Full-width horizontal separator rules inside a column."""
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = column
    return sum(
        1
        for y in range(y0, y1)
        if sum(1 for x in range(x0, x1) if px[y * width + x] == 0) > (x1 - x0) * 0.9
    )


# ---------------------------------------------------------------------------
# Theme structure
# ---------------------------------------------------------------------------


class TestDiagsTheme:
    def test_name(self):
        assert diags_theme().name == "diags"

    def test_in_available_themes(self):
        assert "diags" in AVAILABLE_THEMES

    def test_load_theme(self):
        assert load_theme("diags").name == "diags"

    def test_diags_region_visible(self):
        assert diags_theme().layout.diags.visible is True

    def test_diags_region_full_canvas(self):
        layout = diags_theme().layout
        assert layout.diags.x == 0
        assert layout.diags.y == 0
        assert layout.diags.w == 800
        assert layout.diags.h == 480

    def test_standard_regions_hidden(self):
        layout = diags_theme().layout
        assert layout.header.visible is False
        assert layout.week_view.visible is False
        assert layout.weather.visible is False
        assert layout.birthdays.visible is False
        assert layout.info.visible is False

    def test_draw_order(self):
        assert diags_theme().layout.draw_order == ["diags"]

    def test_canvas_size(self):
        layout = diags_theme().layout
        assert layout.canvas_w == 800
        assert layout.canvas_h == 480

    def test_no_inversion(self):
        style = diags_theme().style
        assert style.invert_header is False
        assert style.invert_today_col is False
        assert style.invert_allday_bars is False

    def test_no_borders(self):
        assert diags_theme().style.show_borders is False


# ---------------------------------------------------------------------------
# Render smoke tests
# ---------------------------------------------------------------------------


class TestDiagsRender:
    """Rendered content, measured per column.

    The panel is two columns split by a vertical divider at x=400: weather /
    forecast / host on the left, calendar / air quality / birthdays / status
    on the right. Each test measures the column that owns what it changes.
    """

    def _render(self, data=None, config=None, theme=None) -> Image.Image:
        return render_dashboard(
            data if data is not None else _make_data(),
            config or DisplayConfig(),
            theme=theme or diags_theme(),
        )

    def test_render_returns_image(self):
        assert isinstance(self._render(), Image.Image)

    def test_render_correct_size(self):
        result = self._render(config=DisplayConfig(width=800, height=480))
        assert result.size == (800, 480)

    def test_render_draws_both_columns_and_the_divider(self):
        """The two-column structure is present, not just some ink somewhere."""
        img = self._render()
        assert _ink(img, LEFT_COL) > 0, "left column empty"
        assert _ink(img, RIGHT_COL) > 0, "right column empty"
        assert _divider_height(img) > 300, "no vertical column divider"
        assert _section_rules(img, LEFT_COL) == 2, "left column section rules missing"
        assert _section_rules(img, RIGHT_COL) == 3, "right column section rules missing"

    def test_render_no_weather(self):
        """Weather and forecast both live in the left column, so it loses ink."""
        data = _make_data()
        full = _ink(self._render(data), LEFT_COL)
        data.weather = None
        assert _ink(self._render(data), LEFT_COL) < full, "weather section still drawn"

    def test_render_no_air_quality(self):
        """Air quality is a right-column section."""
        data = _make_data()
        full = _ink(self._render(data), RIGHT_COL)
        data.air_quality = None
        without = _ink(self._render(data), RIGHT_COL)
        assert without != full, "the air-quality section is not being drawn"
        assert _section_rules(self._render(data), RIGHT_COL) == 3, "a section rule disappeared"

    def test_render_empty_events(self):
        data = _make_data()
        full = _ink(self._render(data), RIGHT_COL)
        data.events = []
        assert _ink(self._render(data), RIGHT_COL) != full

    def test_render_empty_birthdays(self):
        data = _make_data()
        full = _ink(self._render(data), RIGHT_COL)
        data.birthdays = []
        assert _ink(self._render(data), RIGHT_COL) != full

    def test_render_stale_data(self):
        """Staleness surfaces in the right-hand status section."""
        data = _make_data()
        fresh = _ink(self._render(data), RIGHT_COL)
        data.is_stale = True
        data.stale_sources = ["weather"]
        data.source_staleness = {"weather": StalenessLevel.STALE}
        assert _ink(self._render(data), RIGHT_COL) != fresh, "staleness is not reported"

    def test_render_all_sources_stale(self):
        """Each staleness level prints its own label, so the three differ."""
        data = _make_data()
        plates = set()
        for levels in (
            {"weather": StalenessLevel.FRESH},
            {"weather": StalenessLevel.STALE},
            {"weather": StalenessLevel.EXPIRED},
        ):
            data.source_staleness = levels
            plates.add(self._render(data).tobytes())
        assert len(plates) == 3, "different staleness levels rendered the same"

    def test_render_minimal_weather(self):
        """Weather with no optional fields draws less than the full record."""
        data = _make_data()
        full = _ink(self._render(data), LEFT_COL)
        data.weather = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear sky",
            high=65.0,
            low=50.0,
            humidity=45,
        )
        minimal = _ink(self._render(data), LEFT_COL)
        assert minimal < full, "optional weather fields are not being drawn"
        assert minimal > 0

    def test_render_weather_with_alerts(self):
        data = _make_data()
        without = _ink(self._render(data), LEFT_COL)
        data.weather.alerts = [WeatherAlert(event="Flood Watch")]
        assert _ink(self._render(data), LEFT_COL) > without, "alerts are not drawn"

    def test_alerts_capped_at_two(self):
        """_MAX_ALERTS=2 — a third alert must not reach the plate."""
        data = _make_data()

        def with_alerts(n):
            data.weather.alerts = [WeatherAlert(event=f"Alert {i}") for i in range(n)]
            return _ink(self._render(data), LEFT_COL)

        two = with_alerts(2)
        assert with_alerts(5) == two, "more than two alerts were drawn"
        assert two > with_alerts(1), "the second alert was dropped too"

    def test_render_aq_partial_fields(self):
        """Only the required AQ fields draws less than the full sensor record."""
        data = _make_data()
        full = _ink(self._render(data), RIGHT_COL)
        data.air_quality = AirQualityData(aqi=55, category="Moderate", pm25=12.5)
        partial = _ink(self._render(data), RIGHT_COL)
        assert 0 < partial < full, "the optional sensor fields are not being drawn"

    def test_render_aq_all_sensor_fields(self):
        """Every PurpleAir field populated draws the most of the three cases."""
        data = _make_data()
        data.air_quality = AirQualityData(aqi=42, category="Good", pm25=9.8)
        bare = _ink(self._render(data), RIGHT_COL)
        data.air_quality = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            pm10=14.2,
            pm1=6.1,
            sensor_id=12345,
            temperature=71.2,
            humidity=48.0,
            pressure=1012.5,
        )
        assert _ink(self._render(data), RIGHT_COL) > bare

    def test_birthdays_capped_at_five(self):
        """_MAX_BIRTHDAYS=5 — the sixth and later entries are dropped."""
        data = _make_data()
        today = data.fetched_at.date()

        def with_birthdays(n):
            data.birthdays = [
                Birthday(name=f"Person {i}", date=today + timedelta(days=i + 1), age=30 + i)
                for i in range(n)
            ]
            return _ink(self._render(data), RIGHT_COL)

        five = with_birthdays(5)
        assert with_birthdays(9) == five, "more than five birthdays were drawn"
        assert five > with_birthdays(4), "the fifth birthday was dropped too"

    def test_forecast_capped_at_six(self):
        """_MAX_FORECAST=6 — a seventh day must not reach the plate."""
        data = _make_data()
        today = data.fetched_at.date()

        def with_days(n):
            data.weather.forecast = [
                DayForecast(
                    date=today + timedelta(days=i + 1),
                    high=70.0 + i,
                    low=55.0 + i,
                    icon="02d",
                    description="partly cloudy",
                    precip_chance=0.20,
                )
                for i in range(n)
            ]
            return _ink(self._render(data), LEFT_COL)

        six = with_days(6)
        assert with_days(10) == six, "more than six forecast days were drawn"
        assert six > with_days(5), "the sixth day was dropped too"

    def test_render_via_load_theme(self):
        """The registry's theme renders the same plate as the factory's."""
        via_registry = self._render(theme=load_theme("diags"))
        assert isinstance(via_registry, Image.Image)
        assert via_registry.tobytes() == self._render().tobytes()


# ---------------------------------------------------------------------------
# AirQualityData model — new fields
# ---------------------------------------------------------------------------


class TestAirQualityDataNewFields:
    def test_new_fields_default_to_none(self):
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8)
        assert aq.temperature is None
        assert aq.humidity is None
        assert aq.pressure is None

    def test_new_fields_can_be_set(self):
        aq = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            temperature=68.4,
            humidity=52.0,
            pressure=1014.3,
        )
        assert aq.temperature == 68.4
        assert aq.humidity == 52.0
        assert aq.pressure == 1014.3


# ---------------------------------------------------------------------------
# Cache roundtrip for new AirQualityData fields
# ---------------------------------------------------------------------------


class TestAirQualityCacheRoundtrip:
    def test_roundtrip_with_new_fields(self):
        from src.fetchers.cache import _deser_air_quality, _ser_air_quality  # noqa: PLC0415

        original = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            pm10=14.2,
            pm1=6.1,
            sensor_id=99999,
            temperature=68.4,
            humidity=52.0,
            pressure=1014.3,
        )
        serialized = _ser_air_quality(original)
        restored = _deser_air_quality(serialized)
        assert restored.temperature == pytest.approx(68.4)
        assert restored.humidity == pytest.approx(52.0)
        assert restored.pressure == pytest.approx(1014.3)

    def test_roundtrip_without_new_fields(self):
        """Old cache entries (missing new keys) deserialize without error."""
        from src.fetchers.cache import _deser_air_quality  # noqa: PLC0415

        old_dict = {"aqi": 30, "category": "Good", "pm25": 8.0}
        restored = _deser_air_quality(old_dict)
        assert restored.temperature is None
        assert restored.humidity is None
        assert restored.pressure is None

    def test_serialized_dict_includes_new_keys(self):
        from src.fetchers.cache import _ser_air_quality  # noqa: PLC0415

        aq = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            temperature=70.0,
            humidity=55.0,
            pressure=1010.0,
        )
        d = _ser_air_quality(aq)
        assert "temperature" in d
        assert "humidity" in d
        assert "pressure" in d
        assert d["temperature"] == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# Random pool exclusion
# ---------------------------------------------------------------------------


class TestDiagsPanelDefaults:
    """draw_diags called directly: default region/style/today branches."""

    def _make_draw(self):
        from PIL import ImageDraw

        img = Image.new("1", (800, 480), 1)
        return img, ImageDraw.Draw(img)

    def test_default_region_and_style(self):
        """region=None/style=None fill in the full-canvas defaults."""
        from src.render.components.diags_panel import draw_diags
        from src.render.theme import ComponentRegion, ThemeStyle

        img_default, draw = self._make_draw()
        draw_diags(draw, _make_data(), region=None, style=None)
        img_explicit, draw2 = self._make_draw()
        draw_diags(
            draw2,
            _make_data(),
            region=ComponentRegion(0, 0, 800, 480),
            style=ThemeStyle(),
        )
        assert _ink(img_default) > 0
        assert img_default.tobytes() == img_explicit.tobytes()

    def test_today_derived_from_datetime_fetched_at(self):
        """today=None with a datetime fetched_at uses now.date().

        Checked against the same date passed explicitly. Note the resolution:
        `today` reaches the plate only through _calendar_section, which
        buckets by ISO week, so this detects a derivation off by a week but
        not one off by a day or two. Verified by shifting the derived date —
        +3 days still passes, +7 fails. The birthday section ignores `today`
        entirely.
        """
        from src.render.components.diags_panel import draw_diags

        data = _make_data()
        derived, draw = self._make_draw()
        draw_diags(draw, data, today=None)
        explicit, draw2 = self._make_draw()
        draw_diags(draw2, data, today=data.fetched_at.date())
        assert derived.tobytes() == explicit.tobytes(), "today was not derived from fetched_at"

    def test_today_derived_from_date_fetched_at(self):
        """A plain-date fetched_at falls back to date.today() rather than raising."""
        from datetime import date as _date

        from src.render.components.diags_panel import draw_diags

        data = _make_data()
        data.fetched_at = _date(2026, 3, 24)
        img, draw = self._make_draw()
        draw_diags(draw, data, today=None)
        explicit, draw2 = self._make_draw()
        draw_diags(draw2, data, today=_date.today())
        assert _ink(img) > 0
        assert img.tobytes() == explicit.tobytes(), "the date.today() fallback was not taken"

    def test_header_non_datetime_fetched_at(self):
        """A plain date in the header renders via the str(now) branch.

        It must differ from the datetime header — that branch exists because
        a date has no time to format.
        """
        data = _make_data()
        with_datetime = render_dashboard(data, DisplayConfig(), theme=diags_theme())
        data.fetched_at = date(2026, 3, 24)
        with_date = render_dashboard(data, DisplayConfig(), theme=diags_theme())
        assert _ink(with_date, HEADER) > 0
        assert _ink(with_date, HEADER) != _ink(with_datetime, HEADER)


class TestFmtUptime:
    def test_with_days(self):
        from src.render.components.diags_panel import _fmt_uptime

        result = _fmt_uptime(90061)  # 1 day, 1 hour, 1 minute
        assert "1d" in result
        assert "1h" in result
        assert "1m" in result

    def test_without_days(self):
        from src.render.components.diags_panel import _fmt_uptime

        result = _fmt_uptime(3661)  # 1 hour, 1 minute, no days
        assert "d" not in result
        assert "1h" in result
        assert "1m" in result

    def test_zero_seconds(self):
        from src.render.components.diags_panel import _fmt_uptime

        result = _fmt_uptime(0)
        assert "0h" in result
        assert "0m" in result


class TestHostSectionFullData:
    """The host section is the bottom of the left column."""

    @staticmethod
    def _full_host():
        from src.data.models import HostData

        return HostData(
            hostname="pi-dashboard",
            uptime_seconds=90061.0,  # 1d 1h 1m — exercises the days branch
            load_1m=0.42,
            load_5m=0.38,
            load_15m=0.31,
            ram_total_mb=4096.0,
            ram_used_mb=1024.0,
            disk_total_gb=32.0,
            disk_used_gb=12.0,
            cpu_temp_c=42.7,
            ip_address="192.168.1.100",
        )

    def _left_ink(self, host) -> int:
        data = _make_data()
        data.host_data = host
        return _ink(render_dashboard(data, DisplayConfig(), theme=diags_theme()), LEFT_COL)

    def test_render_with_all_host_fields(self):
        """Every field populated draws more than the unavailable row."""
        assert self._left_ink(self._full_host()) > self._left_ink(None)

    def test_render_with_none_host_data(self):
        """host_data=None renders the 'unavailable' row, not a blank section."""
        assert self._left_ink(None) > 0

    def test_partial_host_data_is_distinguishable(self):
        """Fields that are None are omitted rather than printed as placeholders."""
        from src.data.models import HostData

        partial = HostData(hostname="pi-dashboard", uptime_seconds=90061.0)
        assert self._left_ink(partial) != self._left_ink(self._full_host())
        assert self._left_ink(partial) != self._left_ink(None)


class TestDiagsNotInRandomPool:
    def test_diags_excluded_from_pool_by_default(self):
        from src.render.random_theme import eligible_themes  # noqa: PLC0415

        pool = eligible_themes(include=[], exclude=[])
        assert "diags" not in pool

    def test_diags_excluded_even_with_include(self):
        """diags is a hard exclusion (like 'random') — include list cannot override it."""
        from src.render.random_theme import eligible_themes  # noqa: PLC0415

        pool = eligible_themes(include=["diags"], exclude=[])
        assert "diags" not in pool
