"""Tests for src/render/components/weather_panel.py

Assertion discipline (see #229)
-------------------------------
These tests used to assert ``img.getbbox() is not None``. On the mode-``"1"``
canvas built below that is not a weak assertion, it is an *impossible* one:
the canvas is filled with 1, ``getbbox()`` reports the bounds of non-zero
pixels, so it returns the full canvas even when nothing was drawn at all.
Every test in this file passed with ``draw_weather`` stubbed to a no-op.

So ink here means **zero-valued** pixels, counted via ``_ink`` / ``_ink_bbox``
(``flatten_pixels``, not the deprecated ``Image.getdata()``). Assertions are
differential wherever possible — render with and without the feature and
compare the band it owns — so they survive font and padding changes while
still failing if the behaviour they name is deleted.

Verification (the step that makes the rewrite worth anything): with
``draw_weather`` stubbed to a no-op, 36 of the 47 tests here fail. The 11
that still pass are the nine pure-helper tests for ``_fmt_time`` and
``_aqi_accent``, which never touch a canvas, plus two *negative* tests
(``test_wind_deg_without_wind_speed_no_crash`` and
``test_aqi_column_suppressed_when_alerts_present``) which assert something is
NOT drawn and so cannot distinguish a no-op by construction. Both were
checked the other way instead, by deleting the suppression each names and
confirming the test then fails. If you add a test here, do the same: delete
the behaviour it is named for and watch it go red before you trust it.
"""

from datetime import date, datetime, timedelta, timezone

from PIL import Image, ImageDraw

from src.data.models import (
    AirQualityData,
    DayForecast,
    StalenessLevel,
    WeatherAlert,
    WeatherData,
)
from src.render import layout as L
from src.render.components.weather_panel import (
    _aqi_accent,
    _draw_aqi_column,
    _fmt_time,
    draw_weather,
)
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion, ThemeStyle

REGION = ComponentRegion(L.WEATHER_X, L.WEATHER_Y, L.WEATHER_W, L.WEATHER_H)


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=55.0,
        current_icon="01d",
        current_description="clear",
        high=60.0,
        low=45.0,
        humidity=50,
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


# ---------------------------------------------------------------------------
# Ink measurement
# ---------------------------------------------------------------------------


def _ink(img: Image.Image, box: tuple[int, int, int, int] | None = None) -> int:
    """Count ink (value-0) pixels, optionally only inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _ink_bbox(img: Image.Image, box: tuple[int, int, int, int] | None = None):
    """Bounding box of ink pixels as (x0, y0, x1, y1), or None if there is none.

    The honest replacement for ``Image.getbbox()`` on a white mode-``"1"``
    plate, where every pixel is non-zero and getbbox can never return None.
    """
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box if box else (0, 0, img.width, img.height)
    xs, ys = [], []
    for y in range(y0, y1):
        row = y * width
        for x in range(x0, x1):
            if px[row + x] == 0:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _bands(region: ComponentRegion = REGION, *, show_forecast: bool = True) -> dict:
    """Row bands of the panel, mirroring weather_panel's proportional layout.

    Derived from the same fractions the component uses, so a band follows the
    component if its layout moves rather than silently pointing at blank plate.
    """
    h, w, x0, y0 = region.h, region.w, region.x, region.y
    content = int(h * 0.233)
    hilo = content + int(h * 0.117)
    d3 = content + int(h * 0.217)
    d4 = content + int(h * 0.317)
    fh = int(h * 0.317) if show_forecast else 0
    rx = x0 + int(w * 0.513)
    return {
        "label": (x0, y0, x0 + w, y0 + content - 2),
        "hilo": (rx, y0 + hilo - 2, x0 + w, y0 + d3 - 2),
        "row3": (rx, y0 + d3 - 2, x0 + w, y0 + d4 - 2),
        "row4": (rx, y0 + d4 - 2, x0 + w, y0 + h - fh - 1),
        "icon": (x0, y0 + content, x0 + 60, y0 + content + 45),
        "forecast": (x0, y0 + h - fh, x0 + w, y0 + h),
        "corner": (x0 + w - 24, y0 + h - 20, x0 + w, y0 + h),
    }


def _fcol(i: int, n_cols: int, region: ComponentRegion = REGION):
    """Bounding box of forecast column *i* of *n_cols*."""
    col_w = region.w // n_cols
    fh = int(region.h * 0.317)
    top = region.y + region.h - fh
    return (region.x + i * col_w, top, region.x + (i + 1) * col_w, region.y + region.h)


def _content_style(**kwargs) -> ThemeStyle:
    """A style with borders off, for measuring content rather than chrome.

    The panel's right separator and forecast rule span whole bands, so ink
    counts inside a band include them. Turning borders off keeps a band's
    count about what was drawn into it.
    """
    kwargs.setdefault("show_borders", False)
    return ThemeStyle(**kwargs)


_UNSET = object()


def _render(**kwargs) -> Image.Image:
    """Render a weather panel onto a fresh plate and return the image.

    Any leftover kwargs build the WeatherData. Pass ``weather=`` to supply one
    directly — including ``weather=None``, which is why this needs a sentinel
    rather than a default argument.
    """
    today = kwargs.pop("today", None)
    air_quality = kwargs.pop("air_quality", None)
    staleness = kwargs.pop("staleness", None)
    region = kwargs.pop("region", None)
    style = kwargs.pop("style", None)
    weather = kwargs.pop("weather", _UNSET)
    if weather is _UNSET:
        weather = _make_weather(**kwargs)
    img, draw = _make_draw()
    draw_weather(
        draw,
        weather,
        today=today,
        air_quality=air_quality,
        region=region,
        style=style,
        staleness=staleness,
    )
    return img


class TestDrawWeatherNone:
    def test_none_weather_renders_unavailable(self):
        """The 'Unavailable' message is drawn, and none of the data furniture is."""
        img = _render(weather=None, style=_content_style())
        bands = _bands()
        centre = (
            REGION.x,
            REGION.y + REGION.h // 2 - 14,
            REGION.x + REGION.w,
            REGION.y + REGION.h // 2 + 14,
        )

        assert _ink(img, centre) > 0, "no message drawn in the centre of the panel"
        # The early return happens before the icon and forecast strip.
        assert _ink(img, bands["icon"]) == 0, "weather icon drawn for None weather"
        assert _ink(img, bands["forecast"]) == 0, "forecast strip drawn for None weather"
        assert _ink(img) < _ink(_render(style=_content_style())), (
            "None plate should carry less ink than a real one"
        )

    def test_none_weather_with_today_renders_moon(self):
        """today= adds the moon glyph to the label row even when weather is None."""
        without = _render(weather=None)
        with_moon = _render(weather=None, today=date(2024, 3, 15))
        label = _bands()["label"]

        assert _ink(with_moon, label) > _ink(without, label), "moon glyph not drawn"
        # It belongs in the right-hand end of the label row, beside the label.
        bbox = _ink_bbox(with_moon, label)
        assert bbox is not None and bbox[2] > REGION.x + REGION.w * 0.7


class TestDrawWeatherDetails:
    """Row 3 carries feels-like / wind, falling back to humidity when both are unset."""

    def test_feels_like_renders(self):
        row3 = _bands()["row3"]
        assert _ink(_render(feels_like=48.0), row3) != _ink(_render(), row3)

    def test_wind_speed_renders(self):
        row3 = _bands()["row3"]
        assert _ink(_render(wind_speed=15.0), row3) != _ink(_render(), row3)

    def test_both_feels_like_and_wind_renders(self):
        """Both set joins them, so row 3 carries more ink than either alone."""
        row3 = _bands()["row3"]
        both = _ink(_render(feels_like=48.0, wind_speed=12.0), row3)
        assert both > _ink(_render(feels_like=48.0), row3)
        assert both > _ink(_render(wind_speed=12.0), row3)

    def test_neither_feels_like_nor_wind_falls_back_to_humidity(self):
        """The fallback shows the humidity *value* — changing it changes the row."""
        row3 = _bands()["row3"]
        humid_72 = _render(feels_like=None, wind_speed=None, humidity=72)
        humid_11 = _render(feels_like=None, wind_speed=None, humidity=11)

        assert _ink(humid_72, row3) > 0
        assert _ink(humid_72, row3) != _ink(humid_11, row3), (
            "row 3 did not change with humidity — the fallback is not being drawn"
        )

    def _sun(self, hour: int, minute: int) -> datetime:
        return datetime(2024, 3, 15, hour, minute, tzinfo=timezone.utc)

    def test_sunrise_and_sunset_render(self):
        row4 = _bands()["row4"]
        both = _render(sunrise=self._sun(6, 24), sunset=self._sun(19, 51), today=date(2024, 3, 15))
        neither = _render(today=date(2024, 3, 15))
        assert _ink(both, row4) > _ink(neither, row4)

    def test_only_sunrise_renders(self):
        row4 = _bands()["row4"]
        one = _render(sunrise=self._sun(6, 24), sunset=None, today=date(2024, 3, 15))
        both = _render(sunrise=self._sun(6, 24), sunset=self._sun(19, 51), today=date(2024, 3, 15))
        neither = _render(today=date(2024, 3, 15))
        assert _ink(neither, row4) < _ink(one, row4) < _ink(both, row4)

    def test_only_sunset_renders(self):
        row4 = _bands()["row4"]
        one = _render(sunrise=None, sunset=self._sun(19, 51), today=date(2024, 3, 15))
        both = _render(sunrise=self._sun(6, 24), sunset=self._sun(19, 51), today=date(2024, 3, 15))
        neither = _render(today=date(2024, 3, 15))
        assert _ink(neither, row4) < _ink(one, row4) < _ink(both, row4)


class TestDrawWeatherForecastStrip:
    """The strip splits into columns; alert columns are inverted (filled) bars."""

    # An alert column is a filled_rect, so it inks the great majority of its
    # box; a forecast column is icon + two short text rows. Measured on the
    # default region the two sit at ~92% and ~10%, so the midpoint separates
    # them with a very wide margin.
    FILLED = 0.5

    def _forecast(self, n: int) -> list[DayForecast]:
        return [
            DayForecast(
                date=date(2024, 3, 16) + timedelta(days=i),
                high=55.0 + i,
                low=40.0 + i,
                icon="01d",
                description="clear",
            )
            for i in range(n)
        ]

    def _fill_fraction(self, img, i: int, n_cols: int) -> float:
        box = _fcol(i, n_cols)
        area = (box[2] - box[0]) * (box[3] - box[1])
        return _ink(img, box) / area

    def test_no_forecast_no_crash(self):
        """No forecast and no alerts means no columns — the strip stays empty.

        Measured borderless: the strip's top rule and the panel's right
        separator are chrome and are drawn either way.
        """
        img = _render(forecast=[], style=_content_style())
        assert _ink(img, _bands()["forecast"]) == 0
        populated = _render(forecast=self._forecast(3), style=_content_style())
        assert _ink(populated, _bands()["forecast"]) > 0

    def test_three_forecast_columns_no_alerts(self):
        """Three days fill three columns, none of them inverted."""
        img = _render(forecast=self._forecast(3))
        for i in range(3):
            assert _ink(img, _fcol(i, 3)) > 0, f"column {i} is empty"
            assert self._fill_fraction(img, i, 3) < self.FILLED, f"column {i} is inverted"

    def test_one_alert_plus_two_forecast_columns(self):
        """One alert takes column 0 as a filled bar; the two forecasts follow."""
        img = _render(forecast=self._forecast(2), alerts=[WeatherAlert(event="Flood Watch")])
        assert self._fill_fraction(img, 0, 3) > self.FILLED, "alert column is not inverted"
        for i in (1, 2):
            assert 0 < _ink(img, _fcol(i, 3))
            assert self._fill_fraction(img, i, 3) < self.FILLED

    def test_two_alerts_plus_one_forecast_column(self):
        """Two alerts take columns 0 and 1; one forecast column remains."""
        img = _render(
            forecast=self._forecast(1),
            alerts=[WeatherAlert(event="Flood Watch"), WeatherAlert(event="Wind Advisory")],
        )
        assert self._fill_fraction(img, 0, 3) > self.FILLED
        assert self._fill_fraction(img, 1, 3) > self.FILLED
        assert self._fill_fraction(img, 2, 3) < self.FILLED

    def test_two_alerts_no_forecast(self):
        """With no forecast the two alerts split the strip in half."""
        img = _render(
            forecast=[],
            alerts=[
                WeatherAlert(event="Dense Fog Advisory"),
                WeatherAlert(event="Winter Storm Warning"),
            ],
        )
        assert self._fill_fraction(img, 0, 2) > self.FILLED
        assert self._fill_fraction(img, 1, 2) > self.FILLED

    def _one_day(self, precip: float, icon: str = "10d") -> list[DayForecast]:
        return [
            DayForecast(
                date=date(2024, 3, 16),
                high=50.0,
                low=38.0,
                icon=icon,
                description="rain",
                precip_chance=precip,
            )
        ]

    def test_forecast_with_precip_chance(self):
        """A precip chance at or above the 5% threshold adds a third text row."""
        box = _fcol(0, 1)
        third_row = (box[0], box[1] + 23, box[2], box[3])
        assert _ink(_render(forecast=self._one_day(0.75)), third_row) > 0

    def test_forecast_below_precip_threshold_no_third_row(self):
        """Below 5% the percentage row is suppressed — the band loses its ink."""
        box = _fcol(0, 1)
        third_row = (box[0], box[1] + 23, box[2], box[3])
        below = _ink(_render(forecast=self._one_day(0.02, icon="01d")), third_row)
        above = _ink(_render(forecast=self._one_day(0.75, icon="01d")), third_row)
        assert below < above, "the 5% precip threshold is not being applied"

    def test_with_moon_phase(self):
        """today= draws the moon glyph in the label row."""
        label = _bands()["label"]
        with_moon = _render(forecast=self._forecast(2), today=date(2024, 3, 15))
        without = _render(forecast=self._forecast(2))
        assert _ink(with_moon, label) > _ink(without, label)


class TestEnhancedWeatherRendering:
    """Wind compass and UV index."""

    def test_wind_compass_rendered_when_wind_deg_present(self):
        """wind_deg appends a compass point to the wind string."""
        row3 = _bands()["row3"]
        with_deg = _ink(_render(wind_speed=12.0, wind_deg=270.0), row3)
        without = _ink(_render(wind_speed=12.0), row3)
        assert with_deg > without, "compass suffix not drawn"

    def test_wind_compass_all_cardinal_directions(self):
        """Each sector draws its own label, so the eight are not all identical."""
        row3 = _bands()["row3"]
        counts = {
            deg: _ink(_render(wind_speed=10.0, wind_deg=float(deg)), row3)
            for deg in (0, 45, 90, 135, 180, 225, 270, 315)
        }
        for deg, count in counts.items():
            assert count > 0, f"nothing drawn for {deg}°"
        assert len(set(counts.values())) > 1, (
            "every compass sector produced identical ink — the label is not varying"
        )

    def test_wind_deg_without_wind_speed_no_crash(self):
        """wind_deg alone draws no compass: the suffix lives inside the wind branch."""
        row3 = _bands()["row3"]
        deg_only = _render(wind_speed=None, wind_deg=90.0)
        neither = _render(wind_speed=None, wind_deg=None)
        assert _ink(deg_only, row3) == _ink(neither, row3), (
            "a compass appeared without a wind speed to attach it to"
        )

    def test_uv_index_renders_in_hilo_row(self):
        hilo = _bands()["hilo"]
        assert _ink(_render(uv_index=5.0), hilo) > _ink(_render(), hilo)

    def test_uv_index_zero_renders(self):
        """UV 0 is a real reading, not a missing one — it still renders."""
        hilo = _bands()["hilo"]
        assert _ink(_render(uv_index=0.0), hilo) > _ink(_render(uv_index=None), hilo)

    def test_uv_index_high_value_renders(self):
        hilo = _bands()["hilo"]
        assert _ink(_render(uv_index=11.0), hilo) > _ink(_render(), hilo)

    def test_uv_index_none_no_crash(self):
        """uv_index=None renders the plain hi/lo row and nothing more."""
        hilo = _bands()["hilo"]
        img = _render(uv_index=None)
        assert _ink(img, hilo) > 0
        assert _ink(img, hilo) < _ink(_render(uv_index=5.0), hilo)

    def test_all_enhanced_fields_together(self):
        """Every optional field set at once still lands in its own row."""
        bands = _bands()
        img = _render(wind_speed=15.0, wind_deg=135.0, uv_index=8.0, feels_like=52.0)
        plain = _render()
        assert _ink(img, bands["hilo"]) > _ink(plain, bands["hilo"]), "UV missing"
        assert _ink(img, bands["row3"]) > _ink(plain, bands["row3"]), "feels/wind missing"


class TestLocationName:
    def test_location_name_in_label_renders(self):
        """A short name is appended to the WEATHER label."""
        label = _bands()["label"]
        assert _ink(_render(location_name="San Francisco"), label) > _ink(_render(), label)

    def test_location_name_none_renders_the_bare_label(self):
        """With no name the row still carries the bare label, shorter than with one.

        (The old test compared `location_name=None` against the default, which
        is the same input — it asserted X == X.)
        """
        label = _bands()["label"]
        bare = _render(location_name=None, style=_content_style())
        named = _render(location_name="San Francisco", style=_content_style())
        assert _ink(bare, label) > 0, "no label drawn at all"
        assert _ink(bare, label) < _ink(named, label)

    def test_very_long_location_name_is_dropped_not_overflowed(self):
        """A name that cannot fit is omitted entirely rather than truncated or spilled.

        The component only appends the city when the combined string measures
        within the label width, so the plate must be identical to the bare one.
        """
        label = _bands()["label"]
        long_name = _render(location_name="A" * 100, style=_content_style())
        bare = _render(style=_content_style())
        assert _ink(long_name, label) == _ink(bare, label), (
            "an oversized location name reached the plate"
        )
        # And nothing escaped into the strip reserved for the moon glyph.
        bbox = _ink_bbox(long_name, label)
        assert bbox is not None and bbox[2] <= REGION.x + REGION.w - L.PAD


class TestStalenessGlyph:
    """The '!' badge is painted into the region's bottom-right corner."""

    def _corner(self, region: ComponentRegion):
        return (
            region.x + region.w - 24,
            region.y + region.h - 20,
            region.x + region.w,
            region.y + region.h,
        )

    def test_stale_weather_renders_glyph(self):
        """Regression: this case (no forecast, no alerts) used to drop the badge.

        With the strip enabled but nothing to put in it, draw_weather returned
        at `n_cols == 0` before reaching the staleness call at the end of the
        function — so the badge was silently skipped in precisely the degraded
        state it exists to announce. The old vacuous assertion here could not
        see it. Found while rewriting this file for #229.
        """
        region = ComponentRegion(0, 0, 300, 120)
        corner = self._corner(region)
        stale = _render(region=region, staleness=StalenessLevel.STALE)
        none = _render(region=region, staleness=None)
        assert _ink(stale, corner) > _ink(none, corner), "no staleness badge drawn"

    def test_expired_weather_renders_glyph(self):
        region = ComponentRegion(0, 0, 300, 120)
        corner = self._corner(region)
        expired = _render(region=region, staleness=StalenessLevel.EXPIRED)
        none = _render(region=region, staleness=None)
        assert _ink(expired, corner) > _ink(none, corner)

    def test_fresh_weather_draws_no_glyph(self):
        """FRESH is not a warning, so its corner stays clear of the badge STALE draws.

        Compared against STALE, not against staleness=None: both of those are
        badge-free, so an always-draw regression would keep them equal and the
        test would not notice.
        """
        region = ComponentRegion(0, 0, 300, 120)
        corner = self._corner(region)
        fresh = _render(region=region, staleness=StalenessLevel.FRESH)
        stale = _render(region=region, staleness=StalenessLevel.STALE)
        assert _ink(fresh, corner) < _ink(stale, corner), "FRESH drew a staleness badge"

    def test_stale_weather_without_forecast_strip_still_renders_glyph(self):
        """show_forecast_strip=False returns early — the badge must still be emitted."""
        region = ComponentRegion(0, 0, 300, 240)
        style = ThemeStyle(show_forecast_strip=False)
        corner = self._corner(region)
        stale = _render(region=region, style=style, staleness=StalenessLevel.STALE)
        none = _render(region=region, style=style, staleness=None)
        assert _ink(stale, corner) > _ink(none, corner), (
            "the early-return branch skipped the staleness badge"
        )

    def test_stale_weather_with_populated_forecast_renders_glyph(self):
        """Forecast strip drawn AND EXPIRED → the badge is painted at the tail end."""
        region = ComponentRegion(0, 0, 400, 160)
        corner = self._corner(region)
        weather = _make_weather(forecast=_make_forecast(3))
        expired = _render(weather=weather, region=region, staleness=StalenessLevel.EXPIRED)
        none = _render(weather=weather, region=region, staleness=None)
        assert _ink(expired, corner) > _ink(none, corner)

    def test_none_staleness_draws_no_glyph(self):
        """The default draws no badge either — again measured against STALE."""
        region = ComponentRegion(0, 0, 300, 120)
        corner = self._corner(region)
        default = _render(region=region, staleness=None)
        stale = _render(region=region, staleness=StalenessLevel.STALE)
        assert _ink(default, corner) < _ink(stale, corner), "staleness=None drew a badge"
        assert _ink(default, corner) == _ink(
            _render(region=region, staleness=StalenessLevel.FRESH), corner
        )


class TestFmtTime:
    def test_formats_am_time(self):
        dt = datetime(2024, 3, 15, 6, 24, tzinfo=timezone.utc)
        result = _fmt_time(dt)
        assert "6" in result
        assert "a" in result

    def test_formats_pm_time(self):
        dt = datetime(2024, 3, 15, 19, 51, tzinfo=timezone.utc)
        result = _fmt_time(dt)
        assert "7" in result
        assert "p" in result

    def test_on_the_hour_drops_minutes(self):
        dt = datetime(2024, 3, 15, 8, 0, tzinfo=timezone.utc)
        result = _fmt_time(dt)
        assert ":00" not in result


def _make_aqi(aqi=42, category="Good", **kwargs):
    return AirQualityData(aqi=aqi, category=category, pm25=kwargs.pop("pm25", 9.0), **kwargs)


def _make_forecast(day_count=3):
    base = date(2026, 4, 20)
    return [
        DayForecast(
            date=base + timedelta(days=i + 1),
            icon="01d",
            description="clear",
            high=60 + i,
            low=50 + i,
            precip_chance=0.15,
        )
        for i in range(day_count)
    ]


class TestAQIForecastColumn:
    """Exercises the air-quality column that replaces a forecast slot when AQ data exists."""

    def test_aqi_column_renders_when_air_quality_present(self):
        """The last column becomes the AQI card, and it renders the AQI *value*."""
        weather = _make_weather(forecast=_make_forecast(3))
        last = _fcol(2, 3)

        good = _render(weather=weather, today=date(2026, 4, 20), air_quality=_make_aqi(42, "Good"))
        unhealthy = _render(
            weather=weather, today=date(2026, 4, 20), air_quality=_make_aqi(199, "Unhealthy")
        )
        no_aq = _render(weather=weather, today=date(2026, 4, 20))

        assert _ink(good, last) > 0
        assert _ink(good, last) != _ink(no_aq, last), "AQI column looks like a forecast column"
        assert _ink(good, last) != _ink(unhealthy, last), (
            "the AQI reading is not being drawn — two different values rendered identically"
        )

    def test_aqi_column_truncates_long_category_label(self):
        """A long category is truncated so the label stays inside its column."""
        img, draw = _make_draw()
        col_x, col_w = 100, 100
        _draw_aqi_column(
            draw,
            _make_aqi(
                aqi=175, category="Unhealthy for Sensitive Groups with Extra Long Descriptor"
            ),
            cx=col_x,
            top=0,
            col_w=col_w,
            col_h=38,
            style=ThemeStyle(),
        )
        bbox = _ink_bbox(img, (0, 0, img.width, 38))
        assert bbox is not None, "nothing drawn"
        assert bbox[0] >= col_x, "AQI label spilled off the left of its column"
        assert bbox[2] <= col_x + col_w, "AQI label spilled off the right of its column"

    def test_aqi_column_suppressed_when_alerts_present(self):
        """An alert outranks air quality — the plate must equal the no-AQ render."""
        weather = _make_weather(
            forecast=_make_forecast(3),
            alerts=[WeatherAlert(event="Heat Advisory")],
        )
        with_aq = _render(
            weather=weather, today=date(2026, 4, 20), air_quality=_make_aqi(42, "Good")
        )
        without_aq = _render(weather=weather, today=date(2026, 4, 20))
        assert with_aq.tobytes() == without_aq.tobytes(), (
            "an AQI column was drawn despite an active weather alert"
        )

    def test_draw_aqi_column_direct(self):
        """Directly exercise _draw_aqi_column: it fills, and stays inside, its column."""
        img, draw = _make_draw(w=200, h=100)
        _draw_aqi_column(
            draw,
            _make_aqi(aqi=87, category="Moderate"),
            cx=0,
            top=0,
            col_w=80,
            col_h=80,
            style=ThemeStyle(),
        )
        bbox = _ink_bbox(img)
        assert bbox is not None, "nothing drawn"
        assert bbox[2] <= 80, "content escaped the column width"
        assert bbox[3] <= 80, "content escaped the column height"


class TestAQIAccent:
    def test_good_uses_accent_good(self):
        style = ThemeStyle(accent_good=1, fg=0)
        assert _aqi_accent(style, 20) == 1

    def test_good_falls_back_to_fg_when_accent_unset(self):
        style = ThemeStyle(fg=7)
        assert _aqi_accent(style, 20) == 7

    def test_moderate_uses_accent_warn(self):
        style = ThemeStyle(accent_warn=2, fg=0)
        # AQI 51–150 range
        assert _aqi_accent(style, 100) == 2
        assert _aqi_accent(style, 150) == 2  # upper boundary inclusive

    def test_unhealthy_uses_accent_alert(self):
        style = ThemeStyle(accent_alert=3, fg=0)
        assert _aqi_accent(style, 200) == 3
        assert _aqi_accent(style, 500) == 3

    def test_boundary_51_is_warn_not_good(self):
        style = ThemeStyle(accent_good=1, accent_warn=2, accent_alert=3, fg=0)
        assert _aqi_accent(style, 50) == 1  # still good
        assert _aqi_accent(style, 51) == 2  # transition

    def test_boundary_151_is_alert(self):
        style = ThemeStyle(accent_good=1, accent_warn=2, accent_alert=3, fg=0)
        assert _aqi_accent(style, 150) == 2
        assert _aqi_accent(style, 151) == 3
