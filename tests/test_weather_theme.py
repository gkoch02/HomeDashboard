"""Tests for the full-screen weather theme and weather_full component.

Assertion discipline (see #229)
-------------------------------
The rendering tests asserted only isinstance/size, and every component test
in this file called draw_weather_full and asserted nothing at all. All 25
passed with the component stubbed to a no-op.

The zone geometry mirrors draw_weather_full's own proportions and matches
tests/test_weather_full_component.py, which covers the component directly;
this file's focus is the theme wiring and the paths that file does not
reach. Ink means zero-valued pixels.
"""

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import (
    DashboardData,
    DayForecast,
    WeatherAlert,
    WeatherData,
)
from src.render.canvas import render_dashboard
from src.render.components.weather_full import draw_weather_full
from src.render.quantize import flatten_pixels
from src.render.theme import (
    AVAILABLE_THEMES,
    ComponentRegion,
    ThemeLayout,
    load_theme,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_weather(**overrides) -> WeatherData:
    defaults = dict(
        current_temp=72.0,
        current_icon="01d",
        current_description="clear sky",
        high=78.0,
        low=60.0,
        humidity=45,
        forecast=[
            DayForecast(
                date=date(2024, 3, 16) + timedelta(days=i),
                high=58.0 + i * 2,
                low=42.0 + i,
                icon="02d",
                description="partly cloudy",
                precip_chance=0.1 * i,
            )
            for i in range(5)
        ],
        feels_like=70.0,
        wind_speed=5.0,
        wind_deg=315.0,
        pressure=1013.0,
        uv_index=3.0,
        sunrise=datetime(2024, 3, 15, 6, 24),
        sunset=datetime(2024, 3, 15, 19, 45),
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


def _make_data(weather=None) -> DashboardData:
    today = date(2024, 3, 15)
    now = datetime.combine(today, datetime.min.time().replace(hour=8))
    return DashboardData(
        fetched_at=now,
        events=[],
        weather=weather,
        birthdays=[],
    )


def _draw_surface():
    img = Image.new("1", (800, 480), 1)
    return ImageDraw.Draw(img)


# ---------------------------------------------------------------------------
# Theme registration tests
# ---------------------------------------------------------------------------


class TestWeatherThemeRegistration:
    def test_weather_in_available_themes(self):
        assert "weather" in AVAILABLE_THEMES

    def test_load_theme_returns_weather(self):
        theme = load_theme("weather")
        assert theme.name == "weather"

    def test_weather_full_region_covers_canvas(self):
        theme = load_theme("weather")
        r = theme.layout.weather_full
        assert r.x == 0
        assert r.y == 0
        assert r.w == 800
        assert r.h == 480
        assert r.visible is True

    def test_standard_regions_hidden(self):
        theme = load_theme("weather")
        layout = theme.layout
        assert not layout.header.visible
        assert not layout.week_view.visible
        assert not layout.birthdays.visible
        assert not layout.info.visible
        assert not layout.today_view.visible

    def test_draw_order_uses_weather_full(self):
        theme = load_theme("weather")
        assert theme.layout.draw_order == ["weather_full"]

    def test_style_borderless(self):
        theme = load_theme("weather")
        assert theme.style.show_borders is False

    def test_style_black_on_white(self):
        theme = load_theme("weather")
        assert theme.style.fg == 0
        assert theme.style.bg == 1

    def test_weather_full_default_invisible_on_other_themes(self):
        """The weather_full region should be hidden by default on non-weather themes."""
        layout = ThemeLayout()
        assert not layout.weather_full.visible


# ---------------------------------------------------------------------------
# Rendering integration tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Ink measurement — zones mirrored from draw_weather_full's proportions
# ---------------------------------------------------------------------------

CANVAS_W, CANVAS_H = 800, 480
_HERO_H = int(CANVAS_H * 0.44)
_CARDS_H = int(CANVAS_H * 0.155)
_DETAIL_H = int(CANVAS_H * 0.06)
_ALERT_H = int(CANVAS_H * 0.055)

HERO = (0, 0, CANVAS_W, _HERO_H)
CARDS = (0, _HERO_H, CANVAS_W, _HERO_H + _CARDS_H)
# The rule above the forecast lands on the detail zone's last row and is drawn
# either way, so it is excluded here.
DETAIL = (0, _HERO_H + _CARDS_H, CANVAS_W, _HERO_H + _CARDS_H + _DETAIL_H - 1)
ALERT = (0, _HERO_H + _CARDS_H + _DETAIL_H, CANVAS_W, _HERO_H + _CARDS_H + _DETAIL_H + _ALERT_H)


def _forecast_band(has_alerts: bool = False) -> tuple[int, int, int, int]:
    top = _HERO_H + _CARDS_H + _DETAIL_H + (_ALERT_H if has_alerts else 0)
    return (0, top, CANVAS_W, CANVAS_H)


def _ink(img, box=None) -> int:
    """Count ink (value-0) pixels, optionally only inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _ink_clusters(img, box, min_gap: int = 12) -> int:
    """Count horizontally separated groups of ink — one per forecast column."""
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    cols = [x for x in range(x0, x1) if any(px[y * width + x] == 0 for y in range(y0, y1))]
    if not cols:
        return 0
    return 1 + sum(1 for p, q in zip(cols, cols[1:]) if q - p > min_gap)


def _card_count(img) -> int:
    """Metric cards, counted from their rounded-rect outlines (two edges each)."""
    px = flatten_pixels(img)
    width = img.width
    y = _HERO_H + 10
    runs = 0
    prev = False
    for x in range(CANVAS_W):
        cur = px[y * width + x] == 0
        if cur and not prev:
            runs += 1
        prev = cur
    return runs // 2


def _component(weather, today=date(2024, 3, 15), **kwargs):
    """Render the component alone onto a fresh plate."""
    img = Image.new("1", (CANVAS_W, CANVAS_H), 1)
    draw_weather_full(draw_surface := ImageDraw.Draw(img), weather, today=today, **kwargs)
    del draw_surface
    return img


class TestWeatherThemeRendering:
    def _render(self, weather):
        return render_dashboard(
            _make_data(weather=weather), DisplayConfig(), theme=load_theme("weather")
        )

    def test_renders_valid_image_with_full_data(self):
        """The theme wires the component through: every zone gets content."""
        img = self._render(_make_weather())
        assert img.size == (CANVAS_W, CANVAS_H)
        assert _ink(img, HERO) > 0, "hero zone empty"
        assert _ink(img, CARDS) > 0, "metric cards empty"
        assert _ink(img, _forecast_band()) > 0, "forecast grid empty"

    def test_renders_with_none_weather(self):
        """No weather draws the fallback and none of the furniture."""
        img = self._render(None)
        assert _ink(img) > 0, "no fallback message"
        assert _card_count(img) == 0, "metric cards drawn without weather"
        assert _ink(img, _forecast_band()) == 0, "forecast grid drawn without weather"

    def test_renders_with_alerts(self):
        """Alerts invert their own banner band and push the forecast down."""
        alerts = [WeatherAlert(event="Flood Watch"), WeatherAlert(event="Wind Advisory")]
        img = self._render(_make_weather(alerts=alerts))
        area = CANVAS_W * _ALERT_H
        assert _ink(img, ALERT) > area * 0.5, "alert banner is not inverted"
        assert _ink(img, _forecast_band(has_alerts=True)) > 0, "forecast lost to the banner"

    def test_renders_with_minimal_data(self):
        """Only the required fields still fills all four cards, with less in them."""
        minimal = WeatherData(
            current_temp=55.0,
            current_icon="03d",
            current_description="overcast",
            high=60.0,
            low=45.0,
            humidity=80,
        )
        img = self._render(minimal)
        assert _card_count(img) == 4
        assert _ink(img, CARDS) < _ink(self._render(_make_weather()), CARDS)


# ---------------------------------------------------------------------------
# Component unit tests
# ---------------------------------------------------------------------------


class TestDrawWeatherFull:
    def test_none_weather_does_not_crash(self):
        img = _component(None)
        assert _ink(img) > 0
        assert _card_count(img) == 0

    def test_basic_weather(self):
        img = _component(_make_weather())
        assert _ink(img, HERO) > 0
        assert _card_count(img) == 4

    def test_all_optional_fields(self):
        """Every optional field set draws more than none of them."""
        full = _component(_make_weather())
        bare = _component(
            WeatherData(
                current_temp=72.0,
                current_icon="01d",
                current_description="clear sky",
                high=78.0,
                low=60.0,
                humidity=45,
            )
        )
        assert _ink(full, CARDS) > _ink(bare, CARDS)

    def test_no_optional_fields(self):
        """Missing optionals fall back to placeholders, not to blank cards."""
        img = _component(
            WeatherData(
                current_temp=55.0,
                current_icon="01d",
                current_description="clear",
                high=60.0,
                low=45.0,
                humidity=50,
            )
        )
        assert _card_count(img) == 4
        assert _ink(img, CARDS) > 0

    def test_with_alerts(self):
        img = _component(_make_weather(alerts=[WeatherAlert(event="Tornado Warning")]))
        assert _ink(img, ALERT) > CANVAS_W * _ALERT_H * 0.5

    def test_empty_forecast(self):
        """No days draws the single centred fallback, not five columns."""
        img = _component(_make_weather(forecast=[]))
        band = _forecast_band()
        assert _ink(img, band) > 0, "no fallback message"
        assert _ink_clusters(img, band) == 1, "columns drawn for an empty forecast"

    def test_many_forecast_days_capped_at_five(self):
        """Ten days draw five columns — the same plate as exactly five."""

        def with_days(n):
            return _component(
                _make_weather(
                    forecast=[
                        DayForecast(
                            date=date(2024, 3, 16) + timedelta(days=i),
                            high=60.0 + i,
                            low=40.0 + i,
                            icon="02d",
                            description="cloudy",
                        )
                        for i in range(n)
                    ]
                )
            )

        five = with_days(5)
        assert _ink_clusters(with_days(10), _forecast_band()) == 5
        assert with_days(10).tobytes() == five.tobytes(), "a sixth forecast day reached the plate"

    def test_wind_without_direction(self):
        """No bearing drops the compass suffix from the wind card."""
        assert _ink(_component(_make_weather(wind_speed=10.0, wind_deg=None)), CARDS) < _ink(
            _component(_make_weather(wind_speed=10.0, wind_deg=270.0)), CARDS
        )

    def test_negative_temperature(self):
        """A minus sign draws more than the equivalent positive."""
        assert _ink(
            _component(_make_weather(current_temp=-15.0, high=-5.0, low=-20.0)), HERO
        ) > _ink(_component(_make_weather(current_temp=15.0, high=5.0, low=20.0)), HERO)

    def test_custom_region(self):
        """An inset region moves the content in from the canvas edges."""
        inset = _component(_make_weather(), region=ComponentRegion(10, 10, 780, 460))
        assert inset.tobytes() != _component(_make_weather()).tobytes()
        assert _ink(inset, (0, 0, CANVAS_W, 8)) == 0, "content ignored the region y offset"

    def test_no_today_date(self):
        """Moon phase is skipped when today is None, so the strip carries less."""
        assert _ink(_component(_make_weather(), today=None), DETAIL) < _ink(
            _component(_make_weather()), DETAIL
        )

    def test_pressure_shown_in_detail_when_uv_in_cards(self):
        """UV takes the card slot, so pressure goes to the detail strip."""
        with_pressure = _component(_make_weather(uv_index=5.0, pressure=1020.0))
        without = _component(_make_weather(uv_index=5.0, pressure=None))
        assert _ink(with_pressure, DETAIL) > _ink(without, DETAIL), "pressure missed the strip"

    def test_pressure_in_cards_when_no_uv(self):
        """With UV absent, pressure takes the 4th card and leaves the strip alone."""
        no_uv = _component(_make_weather(uv_index=None, pressure=1015.0))
        no_uv_no_pressure = _component(_make_weather(uv_index=None, pressure=None))
        assert _ink(no_uv, CARDS) != _ink(no_uv_no_pressure, CARDS), "the barometer card is missing"
        assert _ink(no_uv, DETAIL) == _ink(no_uv_no_pressure, DETAIL), (
            "pressure reached the strip as well as the card"
        )
