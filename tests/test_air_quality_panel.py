"""Tests for src/render/components/air_quality_panel.py
and src/render/themes/air_quality.py.

Assertion discipline (see #229)
-------------------------------
These tests used to assert ``img.getbbox() is not None``, or nothing at all.
On the mode-``"1"`` canvas built below that assertion has no failing input:
the plate is filled with 1, ``getbbox()`` reports the bounds of *non-zero*
pixels, so it returns the full canvas even for a plate nothing was drawn to.
All 47 tests passed with ``draw_air_quality_full`` stubbed to a no-op.

Ink here therefore means **zero-valued** pixels, measured per zone. Three
structural measures carry most of the weight, because they check what the
panel is actually *for* rather than that it drew something:

* ``_card_count`` — ambient cards counted from their rounded-rect outlines.
* ``_pm_separator_count`` — PM columns counted from the rules between them.
* ``_scale_bar_fill`` — the AQI health bar's filled width, which must track
  the reading and clamp at 500.

Verification (the step that makes the rewrite worth anything): with
``draw_air_quality_full`` stubbed to a no-op, 42 of the 52 tests here fail.
Of the 10 survivors, 7 are ``TestAirQualityTheme`` cases that exercise the
theme factory and never draw through this entry point. The other three
assert an equivalence, which two blank plates satisfy by construction —
``test_returns_none``, ``test_default_region_and_style`` and
``test_today_does_not_affect_the_panel``. Each was checked the other way
instead, by breaking what it names (returning a value, defaulting to a
different region, making ``today`` alter the output) and confirming it goes
red. If you add a test here, do the same before you trust it.
"""

from datetime import date, timedelta

import pytest
from PIL import Image, ImageDraw

from src.data.models import AirQualityData, DashboardData, DayForecast, WeatherData
from src.render.components.air_quality_panel import draw_air_quality_full
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANVAS_W, CANVAS_H = 800, 480

# Zone geometry, mirrored from draw_air_quality_full's own proportions.
_HERO_H = int(CANVAS_H * 0.375)
_PM_H = int(CANVAS_H * 0.146)
_CARDS_H = int(CANVAS_H * 0.208)

HERO = (0, 0, CANVAS_W, _HERO_H)
PM = (0, _HERO_H, CANVAS_W, _HERO_H + _PM_H)
CARDS = (0, _HERO_H + _PM_H, CANVAS_W, _HERO_H + _PM_H + _CARDS_H)


def _weather_band(has_ambient: bool) -> tuple[int, int, int, int]:
    """The weather strip starts after the ambient cards, which collapse to
    zero height when the sensor reports none of temp/humidity/pressure."""
    top = _HERO_H + _PM_H + (_CARDS_H if has_ambient else 0)
    return (0, top, CANVAS_W, CANVAS_H)


def _make_draw(w: int = CANVAS_W, h: int = CANVAS_H):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _ink(img: Image.Image, box: tuple[int, int, int, int] | None = None) -> int:
    px = flatten_pixels(img)
    width = img.width
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _ink_x_extent(img: Image.Image, box: tuple[int, int, int, int]):
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    xs = [x for x in range(x0, x1) if any(px[y * width + x] == 0 for y in range(y0, y1))]
    return (xs[0], xs[-1] + 1) if xs else None


def _card_count(img: Image.Image) -> int:
    """Ambient cards, counted from their rounded-rect outlines.

    A scanline through the card bodies crosses each card's left and right
    edge, so the run count is exactly twice the number of cards.

    Only meaningful when the panel reserved a cards zone at all: with no
    ambient readings the zone collapses to zero height and this scanline
    lands in the weather strip instead. Use _has_cards_zone for that case.
    """
    px = flatten_pixels(img)
    width = img.width
    y = _HERO_H + _PM_H + 20
    runs = 0
    prev = False
    for x in range(CANVAS_W):
        cur = px[y * width + x] == 0
        if cur and not prev:
            runs += 1
        prev = cur
    return runs // 2


def _has_cards_zone(img: Image.Image) -> bool:
    """Whether the ambient-cards zone was reserved.

    Both candidate rules land on the same y when the zone collapses, so
    presence alone cannot tell them apart — they are distinguished by span.
    The cards rule is inset 20px each side; the weather strip's rule, which
    takes that y when there are no ambient readings, runs the full width. So
    an inked pixel at x=5 means the zone collapsed.
    """
    px = flatten_pixels(img)
    y = _HERO_H + _PM_H
    return px[y * img.width + 5] != 0


def _pm_separator_count(img: Image.Image) -> int:
    """Full-height vertical rules in the PM zone: one fewer than the columns."""
    px = flatten_pixels(img)
    width = img.width
    top, bottom = _HERO_H + 12, _HERO_H + _PM_H - 12
    return sum(
        1 for x in range(CANVAS_W) if all(px[y * width + x] == 0 for y in range(top, bottom))
    )


def _pm_column_count(img: Image.Image) -> int:
    return _pm_separator_count(img) + 1


def _scale_bar_fill(img: Image.Image) -> int:
    """Ink inside the AQI scale bar, which fills left-to-right with the reading."""
    split = int(CANVAS_W * 0.28)
    bar_x = split + 8
    bar_w = CANVAS_W - split - 16
    bar_y = int(_HERO_H * 0.28)
    return _ink(img, (bar_x, bar_y + 2, bar_x + bar_w, bar_y + 38))


def _scale_bar_crop_greyscale(aqi: int):
    """The scale-bar region rendered on an L plate with a distinct accent.

    On the 1-bit plate every accent collapses to ``fg``, which hides anything
    the panel expresses through colour alone — including whether an
    out-of-range AQI was clamped. A greyscale plate with accents at mid-grey
    separates the two so the difference is visible.
    """
    aq = AirQualityData(aqi=aqi, category="Hazardous", pm25=9.8)
    img = Image.new("L", (CANVAS_W, CANVAS_H), 255)
    draw = ImageDraw.Draw(img)
    style = ThemeStyle(fg=0, bg=255, accent_good=128, accent_warn=128, accent_alert=128)
    draw_air_quality_full(
        draw,
        DashboardData(events=[], weather=None, birthdays=[], air_quality=aq),
        date(2024, 3, 15),
        style=style,
    )
    split = int(CANVAS_W * 0.28)
    bar_x = split + 8
    bar_w = CANVAS_W - split - 16
    bar_y = int(_HERO_H * 0.28)
    return img.crop((bar_x, bar_y, bar_x + bar_w, bar_y + 62)).tobytes()


def _make_aq(**overrides) -> AirQualityData:
    defaults = dict(
        aqi=42,
        category="Good",
        pm25=9.8,
        pm10=14.2,
        pm1=6.1,
        sensor_id=99999,
        temperature=72.0,
        humidity=55.0,
        pressure=1013.0,
    )
    defaults.update(overrides)
    return AirQualityData(**defaults)


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
                high=70.0 + i,
                low=55.0 + i,
                icon="02d",
                description="partly cloudy",
                precip_chance=0.20,
            )
            for i in range(4)
        ],
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


def _make_data(**overrides) -> DashboardData:
    data = DashboardData(air_quality=_make_aq(), weather=_make_weather())
    for k, v in overrides.items():
        setattr(data, k, v)
    return data


def _render(data=None, today=date(2024, 3, 15), *, region=None, style=None, **aq_overrides):
    """Render onto a fresh plate. Leftover kwargs override the AirQualityData."""
    if data is None:
        data = _make_data(air_quality=_make_aq(**aq_overrides)) if aq_overrides else _make_data()
    img, draw = _make_draw()
    draw_air_quality_full(draw, data, today, region=region, style=style)
    return img


# ---------------------------------------------------------------------------
# Smoke tests — full data
# ---------------------------------------------------------------------------


class TestDrawAirQualityFullSmoke:
    def test_renders_with_full_data(self):
        """Every zone receives content."""
        img = _render()
        assert _ink(img, HERO) > 0, "hero zone empty"
        assert _ink(img, PM) > 0, "PM row empty"
        assert _ink(img, CARDS) > 0, "ambient cards empty"
        assert _ink(img, _weather_band(has_ambient=True)) > 0, "weather strip empty"

    def test_returns_none(self):
        """Contract check. A no-op also returns None; verified instead by
        making the component return a value and watching this fail."""
        _, draw = _make_draw()
        assert draw_air_quality_full(draw, _make_data(), date(2024, 3, 15)) is None

    def test_produces_non_blank_image(self):
        """Genuinely non-blank: ink pixels exist, which getbbox could never show."""
        assert _ink(_render()) > 0

    def test_default_region_and_style(self):
        """region=None/style=None fill in the full-canvas defaults."""
        explicit = _render(region=ComponentRegion(0, 0, CANVAS_W, CANVAS_H), style=ThemeStyle())
        assert _render(region=None, style=None).tobytes() == explicit.tobytes()

    def test_custom_region_offset_moves_the_content(self):
        at_origin = _render(region=ComponentRegion(0, 0, 400, 240))
        offset = _render(region=ComponentRegion(120, 0, 400, 240))
        assert _ink(at_origin) > 0
        left_a = _ink_x_extent(at_origin, (0, 0, CANVAS_W, CANVAS_H))
        left_b = _ink_x_extent(offset, (0, 0, CANVAS_W, CANVAS_H))
        assert left_a is not None and left_b is not None
        assert left_b[0] > left_a[0], "region.x offset did not move the content"

    def test_custom_style_changes_the_plate(self):
        """An inverted style is not the same plate as the default.

        Note it is inverted fg/bg rather than show_borders=False: this panel
        rules its zone separators unconditionally and never reads
        show_borders, so that flag would render an identical plate.
        """
        inverted = _render(style=ThemeStyle(fg=1, bg=0))
        assert inverted.tobytes() != _render().tobytes()


# ---------------------------------------------------------------------------
# Unavailable fallback
# ---------------------------------------------------------------------------


class TestDrawAirQualityUnavailable:
    def test_renders_when_air_quality_is_none(self):
        """The fallback message is drawn and none of the zones are."""
        img = _render(_make_data(air_quality=None))
        assert _ink(img) > 0, "no fallback message drawn"
        assert _card_count(img) == 0, "ambient cards drawn without air quality"
        assert _pm_separator_count(img) == 0, "PM columns drawn without air quality"
        assert _scale_bar_fill(img) == 0, "AQI scale bar drawn without air quality"

    def test_unavailable_message_is_centred(self):
        img = _render(_make_data(air_quality=None))
        extent = _ink_x_extent(img, (0, 0, CANVAS_W, CANVAS_H))
        assert extent is not None
        midpoint = (extent[0] + extent[1]) / 2
        assert abs(midpoint - CANVAS_W / 2) < 12, f"message off-centre: midpoint {midpoint}"

    def test_unavailable_does_not_crash_with_weather_also_none(self):
        """Weather is irrelevant once air quality is missing — same plate."""
        no_aq = _render(_make_data(air_quality=None))
        neither = _render(_make_data(air_quality=None, weather=None))
        assert _ink(neither) > 0
        assert neither.tobytes() == no_aq.tobytes()


# ---------------------------------------------------------------------------
# Weather strip
# ---------------------------------------------------------------------------


class TestWeatherStrip:
    BAND = _weather_band(has_ambient=True)

    def test_renders_without_weather(self):
        """No weather leaves the strip nearly bare, but does not break the panel."""
        no_wx = _render(_make_data(weather=None))
        assert _ink(no_wx, self.BAND) < _ink(_render(), self.BAND)
        assert _ink(no_wx, HERO) > 0, "losing weather should not cost the AQI hero"

    def test_renders_without_forecast(self):
        """An empty forecast drops the columns but keeps current conditions."""
        no_fc = _render(_make_data(weather=_make_weather(forecast=[])))
        assert 0 < _ink(no_fc, self.BAND) < _ink(_render(), self.BAND)

    def test_renders_with_empty_precip_chance(self):
        """precip_chance=None omits the percentage from each column."""
        none_precip = _make_weather(
            forecast=[
                DayForecast(
                    date=date(2024, 3, 16) + timedelta(days=i),
                    high=70.0,
                    low=55.0,
                    icon="01d",
                    description="clear",
                    precip_chance=None,
                )
                for i in range(4)
            ]
        )
        assert _ink(_render(_make_data(weather=none_precip)), self.BAND) < _ink(
            _render(), self.BAND
        )

    def test_renders_with_high_precip_chance(self):
        """A high chance draws a wider percentage than a low one."""

        def _fc(chance):
            return _make_weather(
                forecast=[
                    DayForecast(
                        date=date(2024, 3, 16) + timedelta(days=i),
                        high=70.0,
                        low=55.0,
                        icon="10d",
                        description="rain",
                        precip_chance=chance,
                    )
                    for i in range(4)
                ]
            )

        high = _ink(_render(_make_data(weather=_fc(1.0))), self.BAND)
        low = _ink(_render(_make_data(weather=_fc(0.1))), self.BAND)
        assert high != low, "the precipitation chance is not being drawn"

    def test_today_does_not_affect_the_panel(self):
        """`today` is threaded through this panel but never read.

        draw_air_quality_full passes it to _draw_weather_strip, which passes
        it to _draw_forecast_columns, which does not use it — the forecast
        columns take their dates from the DayForecast entries. Asserted as an
        equality rather than described as a rendering behaviour, because that
        is what is actually true today.
        """
        assert _render(today=None).tobytes() == _render(today=date(2024, 3, 15)).tobytes()


# ---------------------------------------------------------------------------
# PM row
# ---------------------------------------------------------------------------


class TestPMRow:
    def test_only_pm25_when_pm1_and_pm10_absent(self):
        """One reading means one column and no separators."""
        img = _render(pm1=None, pm10=None)
        assert _pm_column_count(img) == 1
        assert _ink(img, PM) > 0

    def test_pm25_and_pm10_only(self):
        assert _pm_column_count(_render(pm1=None)) == 2

    def test_pm1_and_pm25_only(self):
        assert _pm_column_count(_render(pm10=None)) == 2

    def test_all_three_pm_columns(self):
        assert _pm_column_count(_render()) == 3

    def test_zero_pm_values(self):
        """Zero is a real reading, not a missing one — the columns stay."""
        img = _render(pm1=0.0, pm25=0.0, pm10=0.0)
        assert _pm_column_count(img) == 3
        assert _ink(img, PM) != _ink(_render(), PM), "PM values are not being drawn"


# ---------------------------------------------------------------------------
# Ambient cards
# ---------------------------------------------------------------------------


class TestAmbientCards:
    def test_no_ambient_fields(self):
        """With no ambient readings the zone collapses and the weather moves up."""
        img = _render(temperature=None, humidity=None, pressure=None)
        assert not _has_cards_zone(img), "a cards zone was reserved with nothing to put in it"
        assert _has_cards_zone(_render()), "sanity: the full-data plate does reserve one"
        assert _ink(img, _weather_band(has_ambient=False)) > 0, "weather strip did not move up"
        assert img.tobytes() != _render().tobytes()

    def test_temperature_only(self):
        assert _card_count(_render(humidity=None, pressure=None)) == 1

    def test_humidity_only(self):
        assert _card_count(_render(temperature=None, pressure=None)) == 1

    def test_pressure_only(self):
        assert _card_count(_render(temperature=None, humidity=None)) == 1

    def test_each_single_card_draws_its_own_reading(self):
        """The three one-card cases are not interchangeable plates."""
        temp = _render(humidity=None, pressure=None)
        humid = _render(temperature=None, pressure=None)
        press = _render(temperature=None, humidity=None)
        inks = {_ink(temp, CARDS), _ink(humid, CARDS), _ink(press, CARDS)}
        assert len(inks) == 3, "two ambient cards rendered identically"

    def test_temp_and_humidity_only(self):
        assert _card_count(_render(pressure=None)) == 2

    def test_all_three_cards(self):
        assert _card_count(_render()) == 3

    def test_temperature_hidden_when_from_fallback(self):
        """A temperature sourced from OWM rather than the sensor is suppressed."""
        fallback = _render(fallback_fields={"temperature"})
        assert _card_count(fallback) == 2, "the fallback temperature card was drawn"
        assert _card_count(_render()) == 3

    def test_only_humidity_shown_when_temp_from_fallback(self):
        """Suppressed temp + no pressure leaves exactly the humidity card.

        Equal to the plate where temperature was never reported at all —
        which is the point of the suppression.
        """
        fallback = _render(pressure=None, fallback_fields={"temperature"})
        never_had = _render(temperature=None, pressure=None)
        assert _card_count(fallback) == 1
        assert _ink(fallback, CARDS) == _ink(never_had, CARDS)

    def test_humidity_and_pressure_shown_without_temperature(self):
        img = _render(temperature=None)
        assert _card_count(img) == 2
        assert _ink(img, CARDS) > 0


# ---------------------------------------------------------------------------
# AQI hero + scale bar
# ---------------------------------------------------------------------------


class TestAqiHeroAndScaleBar:
    @pytest.mark.parametrize(
        "aqi,category",
        [
            (0, "Good"),
            (25, "Good"),
            (50, "Good"),
            (75, "Moderate"),
            (100, "Moderate"),
            (125, "Unhealthy for Sensitive Groups"),
            (151, "Unhealthy"),
            (201, "Very Unhealthy"),
            (301, "Hazardous"),
            (500, "Hazardous"),
        ],
    )
    def test_aqi_zones_render_the_reading_and_the_bar(self, aqi, category):
        img = _render(aqi=aqi, category=category)
        assert _ink(img, HERO) > 0, f"hero empty for AQI {aqi}"
        # AQI 0 leaves the bar outline only; every other reading fills some of it.
        assert _scale_bar_fill(img) > 0

    def test_scale_bar_fill_tracks_the_reading(self):
        """The bar is a gauge: a worse reading fills strictly more of it."""
        fills = [_scale_bar_fill(_render(aqi=v)) for v in (0, 50, 150, 300, 500)]
        assert fills == sorted(fills), f"scale bar not monotonic in AQI: {fills}"
        assert fills[0] < fills[-1]
        assert len(set(fills)) == len(fills), "different readings drew the same bar"

    def test_aqi_zero_renders_an_empty_bar(self):
        """Zero is the floor — the bar outline is there but nothing is filled."""
        zero = _scale_bar_fill(_render(aqi=0))
        assert zero < _scale_bar_fill(_render(aqi=50))

    def test_aqi_max_fills_the_bar(self):
        assert _scale_bar_fill(_render(aqi=500)) > _scale_bar_fill(_render(aqi=300))

    def test_aqi_above_max_is_clamped(self):
        """Readings past 500 clamp to 500 rather than running off the scale.

        Measured on a greyscale plate: on the 1-bit canvas the fill saturates
        the bar either way (PIL clips the overflowing rectangle) and every
        accent collapses to fg, so the clamp is invisible there — an earlier
        version of this test passed with `min(aqi, _AQI_MAX)` deleted. With a
        distinct accent the zone labels expose it.
        """
        at_max = _scale_bar_crop_greyscale(500)
        assert _scale_bar_crop_greyscale(900) == at_max, "AQI 900 did not clamp to 500"
        assert _scale_bar_crop_greyscale(1500) == at_max, "AQI 1500 did not clamp to 500"
        assert _scale_bar_crop_greyscale(300) != at_max, (
            "sanity: an in-range reading should not match the top of the scale"
        )

    def test_aqi_number_stays_inside_its_column(self):
        """The hero numeral is capped to the left column across the real range."""
        split = int(CANVAS_W * 0.28)
        max_w = split - 40  # column width minus 2×pad, per _draw_aqi_hero
        for value in (5, 42, 350, 500):
            extent = _ink_x_extent(_render(aqi=value), (0, 60, split, _HERO_H - 40))
            assert extent is not None, f"nothing drawn for AQI {value}"
            assert extent[1] - extent[0] <= max_w, (
                f"AQI {value} rendered {extent[1] - extent[0]}px wide, over the {max_w} cap"
            )

    def test_category_text_is_drawn(self):
        """A longer category leaves more ink than a short one."""
        assert _ink(_render(category="Hazardous"), HERO) > _ink(_render(category="Good"), HERO)


# ---------------------------------------------------------------------------
# air_quality theme factory — src/render/themes/air_quality.py
# ---------------------------------------------------------------------------


class TestAirQualityTheme:
    def test_theme_name(self):
        from src.render.themes.air_quality import air_quality_theme

        assert air_quality_theme().name == "air_quality"

    def test_theme_in_available_themes(self):
        from src.render.theme import AVAILABLE_THEMES

        assert "air_quality" in AVAILABLE_THEMES

    def test_load_theme_returns_air_quality(self):
        from src.render.theme import load_theme

        assert load_theme("air_quality").name == "air_quality"

    def test_air_quality_full_region_visible(self):
        from src.render.themes.air_quality import air_quality_theme

        assert air_quality_theme().layout.air_quality_full.visible is True

    def test_standard_regions_hidden(self):
        from src.render.themes.air_quality import air_quality_theme

        layout = air_quality_theme().layout
        assert layout.header.visible is False
        assert layout.week_view.visible is False
        assert layout.weather.visible is False

    def test_uses_space_grotesk_fonts(self):
        from src.render.fonts import sg_bold, sg_regular
        from src.render.themes.air_quality import air_quality_theme

        style = air_quality_theme().style
        assert style.font_regular is sg_regular
        assert style.font_bold is sg_bold

    def test_renders_via_canvas(self):
        from PIL import Image as PILImage

        from src.config import DisplayConfig
        from src.render.canvas import render_dashboard
        from src.render.theme import load_theme

        result = render_dashboard(_make_data(), DisplayConfig(), theme=load_theme("air_quality"))
        assert isinstance(result, PILImage.Image)
        assert result.size == (800, 480)
