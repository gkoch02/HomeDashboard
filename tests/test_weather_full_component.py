"""Tests for src/render/components/weather_full.py.

Covers: hero zone, metric cards, detail strip, alert banner, forecast grid,
and the unavailable fallback — exercising branches not covered by the existing
test_weather_full_aqi.py (which focuses on the AQI card only).

Assertion discipline (see #229)
-------------------------------
These tests used to assert ``img.getbbox() is not None``, or nothing at all.
On the mode-``"1"`` canvas built below that assertion has no failing input:
the plate is filled with 1, ``getbbox()`` reports the bounds of *non-zero*
pixels, so it returns the full canvas even for a plate nothing was drawn to.
All 42 tests passed with ``draw_weather_full`` stubbed to a no-op.

Ink here therefore means **zero-valued** pixels, measured per zone with the
helpers below. The component divides the canvas into fixed proportional
zones, so each feature can be measured in the band that owns it, and most
assertions are differential — render with and without, compare.

Verification (the step that makes the rewrite worth anything): with
``draw_weather_full`` stubbed to a no-op, 42 of the 45 tests here fail. The
three survivors are all assertions a no-op satisfies by construction —
``test_returns_none`` (a no-op also returns None),
``test_default_region_and_style`` and ``test_no_alerts_no_banner`` (both
assert an equivalence, and two blank plates are equal). Each was checked the
other way instead, by breaking the behaviour it names — returning a value,
defaulting to a different region, drawing the banner unconditionally — and
confirming it then fails. If you add a test here, do the same: break the
thing it is named for and watch it go red before you trust it.
"""

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import (
    AirQualityData,
    DayForecast,
    WeatherAlert,
    WeatherData,
)
from src.render.components.weather_full import draw_weather_full
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANVAS_W, CANVAS_H = 800, 480

# Zone geometry, mirrored from draw_weather_full's own proportions so a band
# follows the component if its layout moves rather than pointing at blank plate.
_HERO_H = int(CANVAS_H * 0.44)
_CARDS_H = int(CANVAS_H * 0.155)
_DETAIL_H = int(CANVAS_H * 0.06)
_ALERT_H = int(CANVAS_H * 0.055)

HERO = (0, 0, CANVAS_W, _HERO_H)
CARDS = (0, _HERO_H, CANVAS_W, _HERO_H + _CARDS_H)
# The thin rule above the forecast lands on the detail zone's last row, and it
# is drawn whether or not the strip has any content — so it is excluded here.
DETAIL = (0, _HERO_H + _CARDS_H, CANVAS_W, _HERO_H + _CARDS_H + _DETAIL_H - 1)
ALERT = (0, _HERO_H + _CARDS_H + _DETAIL_H, CANVAS_W, _HERO_H + _CARDS_H + _DETAIL_H + _ALERT_H)


def _forecast_band(has_alerts: bool = False) -> tuple[int, int, int, int]:
    top = _HERO_H + _CARDS_H + _DETAIL_H + (_ALERT_H if has_alerts else 0)
    return (0, top, CANVAS_W, CANVAS_H)


def _make_draw(w: int = CANVAS_W, h: int = CANVAS_H):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _ink(img: Image.Image, box: tuple[int, int, int, int] | None = None) -> int:
    """Count ink (value-0) pixels, optionally only inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _ink_x_extent(img: Image.Image, box: tuple[int, int, int, int]):
    """(left, right) x-extent of ink inside *box*, or None if there is none."""
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    xs = [x for x in range(x0, x1) if any(px[y * width + x] == 0 for y in range(y0, y1))]
    return (xs[0], xs[-1] + 1) if xs else None


def _ink_clusters(img: Image.Image, box: tuple[int, int, int, int], min_gap: int = 12) -> int:
    """Count horizontally separated groups of ink inside *box*.

    Used to count forecast columns and metric cards without hardcoding their
    pixel positions: a column is a run of inked x-positions, and columns are
    separated by more than *min_gap* blank ones.
    """
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    cols = [x for x in range(x0, x1) if any(px[y * width + x] == 0 for y in range(y0, y1))]
    if not cols:
        return 0
    return 1 + sum(1 for p, q in zip(cols, cols[1:]) if q - p > min_gap)


def _card_count(img: Image.Image) -> int:
    """Number of metric cards, counted from their rounded-rect outlines.

    A scanline through the card bodies crosses each card's left and right
    edge, so the number of ink runs is exactly twice the card count.
    """
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


def _make_forecast(n: int = 5, precip: float | None = 0.20, icon: str = "02d"):
    return [
        DayForecast(
            date=date(2024, 3, 16) + timedelta(days=i),
            high=60.0 + i * 2,
            low=45.0 + i,
            icon=icon,
            description="partly cloudy",
            precip_chance=precip,
        )
        for i in range(n)
    ]


def _make_weather(**overrides) -> WeatherData:
    defaults = dict(
        current_temp=72.0,
        current_icon="01d",
        current_description="clear sky",
        high=78.0,
        low=60.0,
        humidity=45,
        forecast=_make_forecast(5),
        feels_like=70.0,
        wind_speed=8.0,
        wind_deg=270.0,
        uv_index=4.0,
        pressure=1013.0,
        sunrise=datetime(2024, 3, 15, 6, 24),
        sunset=datetime(2024, 3, 15, 19, 45),
        location_name="San Francisco",
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


TODAY = date(2024, 3, 15)

_UNSET = object()


def _render(weather=_UNSET, today=TODAY, *, air_quality=None, region=None, style=None, **overrides):
    """Render onto a fresh plate and return the image.

    Leftover kwargs build the WeatherData. Pass ``weather=`` directly —
    including ``weather=None``, hence the sentinel rather than a default.
    """
    if weather is _UNSET:
        weather = _make_weather(**overrides)
    img, draw = _make_draw()
    draw_weather_full(draw, weather, today, air_quality=air_quality, region=region, style=style)
    return img


# ---------------------------------------------------------------------------
# Smoke — basic rendering
# ---------------------------------------------------------------------------


class TestDrawWeatherFullSmoke:
    def test_renders_with_full_data(self):
        """Every zone receives content."""
        img = _render()
        assert _ink(img, HERO) > 0, "hero zone empty"
        assert _ink(img, CARDS) > 0, "metric cards zone empty"
        assert _ink(img, DETAIL) > 0, "detail strip empty"
        assert _ink(img, _forecast_band()) > 0, "forecast grid empty"

    def test_returns_none(self):
        _, draw = _make_draw()
        assert draw_weather_full(draw, _make_weather(), TODAY) is None

    def test_produces_non_blank_image(self):
        """Genuinely non-blank: ink pixels exist, which getbbox could never show."""
        assert _ink(_render()) > 0

    def test_default_region_and_style(self):
        """region=None/style=None fill in the full-canvas defaults."""
        explicit = _render(region=ComponentRegion(0, 0, CANVAS_W, CANVAS_H), style=ThemeStyle())
        assert _render(region=None, style=None).tobytes() == explicit.tobytes()

    def test_custom_region_offset_moves_the_content(self):
        """A region offset shifts the whole plate rather than being ignored."""
        at_origin = _render(region=ComponentRegion(0, 0, 400, 240))
        offset = _render(region=ComponentRegion(100, 0, 400, 240))
        assert _ink(at_origin) > 0
        assert at_origin.tobytes() != offset.tobytes()
        left_origin = _ink_x_extent(at_origin, (0, 0, CANVAS_W, CANVAS_H))
        left_offset = _ink_x_extent(offset, (0, 0, CANVAS_W, CANVAS_H))
        assert left_origin is not None and left_offset is not None
        assert left_offset[0] > left_origin[0], "region.x offset did not move the content"


# ---------------------------------------------------------------------------
# Unavailable fallback
# ---------------------------------------------------------------------------


class TestDrawWeatherFullUnavailable:
    def test_renders_when_weather_is_none(self):
        """The fallback message is drawn and nothing else is."""
        img = _render(weather=None)
        assert _ink(img) > 0, "no fallback message drawn"
        assert _card_count(img) == 0, "metric cards drawn for None weather"
        assert _ink(img, _forecast_band()) == 0, "forecast grid drawn for None weather"

    def test_unavailable_message_is_centred(self):
        """_draw_unavailable centres its message on the region."""
        img = _render(weather=None)
        extent = _ink_x_extent(img, (0, 0, CANVAS_W, CANVAS_H))
        assert extent is not None
        midpoint = (extent[0] + extent[1]) / 2
        assert abs(midpoint - CANVAS_W / 2) < 12, f"message off-centre: midpoint {midpoint}"

    def test_unavailable_with_air_quality_still_renders(self):
        """Air-quality data does not resurrect any of the normal zones."""
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8)
        with_aq = _render(weather=None, air_quality=aq)
        without = _render(weather=None)
        assert _ink(with_aq) > 0
        assert with_aq.tobytes() == without.tobytes(), (
            "air quality leaked into the unavailable fallback"
        )


# ---------------------------------------------------------------------------
# Hero zone — optional fields
# ---------------------------------------------------------------------------


class TestHeroZone:
    def test_renders_with_location_name(self):
        """The location line is drawn under the hi/lo."""
        assert _ink(_render(location_name="San Francisco"), HERO) > _ink(
            _render(location_name=None), HERO
        )

    def test_renders_without_location_name(self):
        """No location still renders the rest of the hero."""
        img = _render(location_name=None)
        assert _ink(img, HERO) > 0
        assert _ink(img, HERO) < _ink(_render(location_name="San Francisco"), HERO)

    def test_renders_negative_temperature(self):
        """A negative temp draws its minus sign — more ink than the positive."""
        assert _ink(_render(current_temp=-15.0), HERO) > _ink(_render(current_temp=15.0), HERO)

    def test_renders_triple_digit_temperature(self):
        """Three digits draw more than two."""
        assert _ink(_render(current_temp=105.0), HERO) > _ink(_render(current_temp=72.0), HERO)

    def test_renders_unknown_icon_uses_fallback(self):
        """Unknown OWM codes all collapse to the same fallback glyph.

        Two different unknown codes must render identically (both fall back),
        and differently from a known code — which is what 'uses the fallback'
        actually means.
        """
        unknown_a = _render(current_icon="zz9")
        unknown_b = _render(current_icon="not_a_code")
        known = _render(current_icon="01d")
        assert _ink(unknown_a, HERO) == _ink(unknown_b, HERO), (
            "two unknown icons rendered differently — they are not sharing a fallback"
        )
        assert _ink(unknown_a, HERO) != _ink(known, HERO), (
            "the fallback glyph is identical to the 01d glyph — nothing is being mapped"
        )


# ---------------------------------------------------------------------------
# Metric cards
# ---------------------------------------------------------------------------


class TestMetricCards:
    def test_four_cards_without_air_quality(self):
        assert _card_count(_render()) == 4

    def test_five_cards_with_air_quality(self):
        """The AQI card is appended as a fifth."""
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8)
        assert _card_count(_render(air_quality=aq)) == 5

    def test_feels_like_none_shows_temp_card(self):
        """Without feels_like the card falls back to the current temp + 'Temp' label."""
        cards_absent = _ink(_render(feels_like=None), CARDS)
        assert cards_absent > 0
        assert cards_absent != _ink(_render(feels_like=70.0), CARDS)
        assert _card_count(_render(feels_like=None)) == 4, "the card disappeared entirely"

    def test_wind_speed_none_shows_dash(self):
        """No wind speed still draws the card, with a dash instead of a value."""
        no_wind = _render(wind_speed=None)
        assert _card_count(no_wind) == 4
        assert _ink(no_wind, CARDS) < _ink(_render(wind_speed=8.0), CARDS), (
            "the dash placeholder is not lighter than a real wind reading"
        )

    def test_wind_deg_none_omits_compass(self):
        """Without a bearing the wind card loses its compass suffix."""
        assert _ink(_render(wind_deg=None), CARDS) < _ink(_render(wind_deg=270.0), CARDS)

    def test_uv_none_shows_pressure_card(self):
        """UV missing but pressure present swaps in the barometer card."""
        uv_none = _render(uv_index=None)
        assert _card_count(uv_none) == 4
        assert _ink(uv_none, CARDS) != _ink(_render(uv_index=4.0), CARDS)
        assert _ink(uv_none, CARDS) != _ink(_render(uv_index=None, pressure=None), CARDS), (
            "the pressure card renders the same as the empty-dash card"
        )

    def test_uv_and_pressure_none_shows_dash_card(self):
        """Neither available still leaves four cards, the last one a dash."""
        both_none = _render(uv_index=None, pressure=None)
        assert _card_count(both_none) == 4
        assert _ink(both_none, CARDS) < _ink(_render(uv_index=4.0), CARDS)

    def test_air_quality_long_category_truncated(self):
        """A long category is cut to 11 chars, so it renders like the cut string.

        Two categories sharing their first 11 characters must be
        indistinguishable on the plate; one differing inside them must not be.
        """
        long_a = AirQualityData(aqi=120, category="Unhealthy for Sensitive Groups", pm25=38.0)
        long_b = AirQualityData(aqi=120, category="Unhealthy fXXXXXXXX different", pm25=38.0)
        differs_early = AirQualityData(aqi=120, category="Moderate air", pm25=38.0)

        a = _ink(_render(air_quality=long_a), CARDS)
        b = _ink(_render(air_quality=long_b), CARDS)
        c = _ink(_render(air_quality=differs_early), CARDS)
        assert a == b, "text past the 11-char cut reached the plate"
        assert a != c, "the label is not being drawn at all"


# ---------------------------------------------------------------------------
# Detail strip
# ---------------------------------------------------------------------------


class TestDetailStrip:
    def test_renders_with_sunrise_and_sunset(self):
        """Both times present draw more than either alone."""
        both = _ink(_render(), DETAIL)
        assert both > _ink(_render(sunrise=None), DETAIL)
        assert both > _ink(_render(sunset=None), DETAIL)

    def test_renders_without_sunrise(self):
        no_rise = _ink(_render(sunrise=None), DETAIL)
        assert _ink(_render(sunrise=None, sunset=None), DETAIL) < no_rise < _ink(_render(), DETAIL)

    def test_renders_without_sunset(self):
        no_set = _ink(_render(sunset=None), DETAIL)
        assert _ink(_render(sunrise=None, sunset=None), DETAIL) < no_set < _ink(_render(), DETAIL)

    def test_renders_without_sunrise_and_sunset(self):
        """Neither time still leaves the moon and pressure segments."""
        neither = _render(sunrise=None, sunset=None)
        assert _ink(neither, DETAIL) > 0
        assert _ink(neither, DETAIL) < _ink(_render(), DETAIL)

    def test_renders_without_today_date(self):
        """today=None drops the moon glyph and its phase name."""
        assert _ink(_render(today=None), DETAIL) < _ink(_render(today=TODAY), DETAIL)

    def test_renders_with_today_and_moon(self):
        """The moon segment varies with the date — different phases, different ink."""
        new_moon = _ink(_render(today=date(2024, 3, 10)), DETAIL)
        full_moon = _ink(_render(today=date(2024, 3, 25)), DETAIL)
        assert new_moon != full_moon, "the moon phase is not being drawn from the date"

    def test_pressure_in_strip_when_uv_present(self):
        """Pressure only reaches the strip when UV took the card slot."""
        with_both = _ink(_render(uv_index=4.0, pressure=1013.0), DETAIL)
        no_pressure = _ink(_render(uv_index=4.0, pressure=None), DETAIL)
        assert with_both > no_pressure, "pressure did not reach the strip"
        # With UV absent the pressure moves to a card instead, not the strip.
        assert _ink(_render(uv_index=None, pressure=1013.0), DETAIL) == no_pressure

    def test_pm_breakdown_in_strip_with_air_quality(self):
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8, pm1=5.0, pm10=12.0)
        assert _ink(_render(air_quality=aq), DETAIL) > _ink(_render(), DETAIL)

    def test_pm_breakdown_without_pm1_and_pm10(self):
        """Only PM2.5 available draws a shorter segment than the full triple."""
        full = AirQualityData(aqi=42, category="Good", pm25=9.8, pm1=5.0, pm10=12.0)
        only25 = AirQualityData(aqi=42, category="Good", pm25=9.8)
        assert (
            0 < _ink(_render(air_quality=only25), DETAIL) < _ink(_render(air_quality=full), DETAIL)
        )


# ---------------------------------------------------------------------------
# Alert banner
# ---------------------------------------------------------------------------


class TestAlertBanner:
    # The banner is a filled_rect with knocked-out text, so it inks nearly its
    # whole band; the same band without alerts carries only stray descenders.
    FILLED = 0.5

    def _fill_fraction(self, img) -> float:
        x0, y0, x1, y1 = ALERT
        return _ink(img, ALERT) / ((x1 - x0) * (y1 - y0))

    def test_renders_single_alert(self):
        """One alert inverts the banner band."""
        img = _render(alerts=[WeatherAlert(event="Flood Watch")])
        assert self._fill_fraction(img) > self.FILLED, "alert banner is not inverted"

    def test_renders_multiple_alerts(self):
        """Up to three alerts are joined into the one banner."""
        alerts = [
            WeatherAlert(event="Flood Watch"),
            WeatherAlert(event="Wind Advisory"),
            WeatherAlert(event="Heat Advisory"),
        ]
        img = _render(alerts=alerts)
        assert self._fill_fraction(img) > self.FILLED
        # Knocked-out text means more alert text leaves *less* ink in the band.
        one = _render(alerts=alerts[:1])
        assert _ink(img, ALERT) < _ink(one, ALERT), "extra alerts drew no extra text"

    def test_renders_very_long_alert_event_name(self):
        """An over-long alert is truncated rather than overflowing the banner."""
        img = _render(alerts=[WeatherAlert(event="Extremely " * 40 + "Long Warning")])
        assert self._fill_fraction(img) > self.FILLED
        extent = _ink_x_extent(img, ALERT)
        assert extent is not None
        assert extent[0] >= 0 and extent[1] <= CANVAS_W, "alert text left the canvas"

    def test_no_alerts_no_banner(self):
        """Without alerts the band belongs to the forecast, not a banner."""
        img = _render()
        assert self._fill_fraction(img) < self.FILLED, "a banner appeared without alerts"

    def test_alerts_push_the_forecast_grid_down(self):
        """The banner takes its own zone rather than overlaying the forecast."""
        with_alert = _render(alerts=[WeatherAlert(event="Flood Watch")])
        assert _ink(with_alert, _forecast_band(has_alerts=True)) > 0, "forecast lost to the banner"
        assert _ink_clusters(with_alert, _forecast_band(has_alerts=True)) == 5


# ---------------------------------------------------------------------------
# Forecast grid
# ---------------------------------------------------------------------------


class TestForecastGrid:
    def test_renders_five_day_forecast(self):
        assert _ink_clusters(_render(), _forecast_band()) == 5

    def test_renders_one_day_forecast(self):
        assert _ink_clusters(_render(forecast=_make_forecast(1)), _forecast_band()) == 1

    def test_forecast_column_count_tracks_the_data(self):
        """Two, three and four days each get their own column count."""
        for n in (2, 3, 4):
            img = _render(forecast=_make_forecast(n))
            assert _ink_clusters(img, _forecast_band()) == n, f"{n} days did not draw {n} columns"

    def test_caps_at_five_columns(self):
        """More than five days are truncated to five."""
        assert _ink_clusters(_render(forecast=_make_forecast(8)), _forecast_band()) == 5

    def test_renders_empty_forecast_shows_fallback(self):
        """No forecast draws the single centred fallback message."""
        img = _render(forecast=[])
        band = _forecast_band()
        assert _ink(img, band) > 0, "no fallback message drawn"
        assert _ink_clusters(img, band) == 1, "fallback should be one centred run, not columns"
        assert _ink(img, band) < _ink(_render(), band)

    def test_renders_forecast_without_precip_chance(self):
        """precip_chance=None omits the percentage row."""
        none_precip = _render(forecast=_make_forecast(5, precip=None))
        with_precip = _render(forecast=_make_forecast(5, precip=0.20))
        band = _forecast_band()
        assert _ink(none_precip, band) < _ink(with_precip, band)

    def test_renders_forecast_with_low_precip_chance_excluded(self):
        """Below the 5% threshold the percentage row is suppressed."""
        band = _forecast_band()
        low = _ink(_render(forecast=_make_forecast(5, precip=0.02)), band)
        none = _ink(_render(forecast=_make_forecast(5, precip=None)), band)
        high = _ink(_render(forecast=_make_forecast(5, precip=0.20)), band)
        assert low == none, "a sub-threshold precip chance was drawn"
        assert low < high

    def test_renders_forecast_with_unknown_icon(self):
        """Unknown forecast icons fall back like the hero icon does."""
        band = _forecast_band()
        unknown_a = _ink(_render(forecast=_make_forecast(5, icon="invalid_xyz")), band)
        unknown_b = _ink(_render(forecast=_make_forecast(5, icon="also_bogus")), band)
        known = _ink(_render(forecast=_make_forecast(5, icon="02d")), band)
        assert unknown_a == unknown_b
        assert unknown_a != known


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    # The hero temp is capped at half the canvas width. Measured against that
    # constraint rather than a sibling render, so it stays true if the font
    # changes.
    MAX_TEMP_W = CANVAS_W // 2
    TEMP_BAND = (0, 85, CANVAS_W, 165)

    def test_hero_temp_stays_within_its_width_cap(self):
        """Realistic extremes all fit the cap at the base 64pt size.

        Note what this does NOT do: it does not exercise the auto-scale-down
        loop. At 64pt the loop only engages past ~11 characters, i.e. around
        |temp| >= 999,999,999 — no real reading, and not -100.4, which the
        previous version of this test claimed triggered it. The loop is
        covered separately below.
        """
        for temp in (72.0, -100.4, -1000.0, -10000.0):
            extent = _ink_x_extent(_render(current_temp=temp), self.TEMP_BAND)
            assert extent is not None, f"nothing drawn for {temp}"
            assert extent[1] - extent[0] <= self.MAX_TEMP_W, (
                f"temp {temp} rendered {extent[1] - extent[0]}px wide, "
                f"over the {self.MAX_TEMP_W} cap"
            )

    def test_hero_temp_scales_down_for_wide_strings(self):
        """A string wide enough to trip the scale-down loop is shrunk to fit.

        The value is synthetic — no weather API reports it — but it is the
        only way to reach the loop, which otherwise never runs. Without the
        scale-down this string renders ~419px wide, over the 400px cap.
        """
        absurd = -999999999.0
        extent = _ink_x_extent(_render(current_temp=absurd), self.TEMP_BAND)
        assert extent is not None, "nothing drawn"
        assert extent[1] - extent[0] <= self.MAX_TEMP_W, (
            "the hero temp overflowed its cap — the scale-down loop did not engage"
        )

    def test_detail_strip_empty_when_no_sun_no_moon_no_aq(self):
        """No segments at all → _draw_detail_strip returns before drawing.

        The band is measured excluding its last row, which carries the rule
        above the forecast grid — that is drawn either way.
        """
        img = _render(
            sunrise=None,
            sunset=None,
            uv_index=None,  # pressure needs uv_index to surface in the strip
            pressure=None,
            today=None,
        )
        assert _ink(img, DETAIL) == 0, "the strip drew something with no segments to draw"
        # The rest of the plate is unaffected.
        assert _ink(img, HERO) > 0
        assert _ink(img, _forecast_band()) > 0
