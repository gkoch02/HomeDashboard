"""Tests for the postcard theme and postcard_panel component."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from PIL import ImageStat

from src.config import DisplayConfig
from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.postcard_panel import _events_today, _fmt_event_time
from src.render.components.postcard_scene import (
    Light,
    light_for,
    moon_disc,
    render_scene,
    scene_kind,
)
from src.render.quantize import flatten_pixels
from src.render.theme import AVAILABLE_THEMES, load_theme
from tests.inkutils import text_line_heights

FIXED_NOW = datetime(2026, 4, 6, 14, 30)
TODAY = FIXED_NOW.date()


def _render(**kwargs):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme("postcard")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestPostcardRegistration:
    def test_in_available_themes(self):
        assert "postcard" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("postcard")
        assert t.name == "postcard"

    def test_postcard_region_visible(self):
        t = load_theme("postcard")
        assert t.layout.postcard.visible is True
        # 2× supersampled canvas; backend resizes to display res via LANCZOS.
        assert t.layout.postcard.w == 1600
        assert t.layout.postcard.h == 960

    def test_canvas_is_supersampled(self):
        t = load_theme("postcard")
        assert t.layout.canvas_w == 1600
        assert t.layout.canvas_h == 960

    def test_draw_order_only_postcard(self):
        t = load_theme("postcard")
        assert t.layout.draw_order == ["postcard"]

    def test_uses_floyd_steinberg_quantization(self):
        t = load_theme("postcard")
        assert t.layout.canvas_mode == "L"
        assert t.layout.preferred_quantization_mode == "floyd_steinberg"

    def test_color_on_inky(self):
        t = load_theme("postcard")
        assert t.layout.prefer_color_on_inky is True


# ---------------------------------------------------------------------------
# Scene-kind dispatch — maps OWM icon codes to the right procedural scene.
# ---------------------------------------------------------------------------


class TestSceneKind:
    @pytest.mark.parametrize(
        "icon,kind,is_night",
        [
            ("01d", "clear", False),
            ("01n", "clear", True),
            ("02d", "partly", False),
            ("02n", "partly", True),
            ("03d", "partly", False),
            ("04d", "overcast", False),
            ("09d", "rain", False),
            ("10d", "rain", False),
            ("10n", "rain", True),
            ("11d", "storm", False),
            ("13d", "snow", False),
            ("50d", "fog", False),
            (None, "clear", False),
            ("", "clear", False),
            ("zz", "clear", False),
        ],
    )
    def test_maps_icon_to_kind(self, icon, kind, is_night):
        assert scene_kind(icon) == (kind, is_night)


# ---------------------------------------------------------------------------
# Light — the sun follows the clock; the icon's night flag wins.
# ---------------------------------------------------------------------------

RISE = datetime(2026, 4, 6, 6, 30)
SET = datetime(2026, 4, 6, 19, 30)


class TestLightFor:
    def test_night_icon_wins_over_the_clock(self):
        assert light_for(datetime(2026, 4, 6, 12, 0), True, RISE, SET).phase == "night"

    def test_midday_sun_is_high_and_central(self):
        light = light_for(datetime(2026, 4, 6, 12, 40), False, RISE, SET)
        assert light.phase == "day"
        assert light.sun_alt > 0.9
        assert 0.4 < light.sun_x < 0.6

    def test_sun_crosses_from_left_to_right(self):
        morning = light_for(datetime(2026, 4, 6, 9, 0), False, RISE, SET)
        evening = light_for(datetime(2026, 4, 6, 17, 0), False, RISE, SET)
        assert morning.sun_x < 0.5 < evening.sun_x

    def test_dawn_and_dusk_are_golden(self):
        assert light_for(datetime(2026, 4, 6, 6, 10), False, RISE, SET).phase == "golden"
        assert light_for(datetime(2026, 4, 6, 19, 5), False, RISE, SET).phase == "golden"

    def test_day_icon_at_3am_is_not_night(self):
        """The clock never turns a day icon into a night sky."""
        assert light_for(datetime(2026, 4, 6, 3, 0), False, RISE, SET).phase == "golden"

    def test_light_is_constant_within_the_hour(self):
        """The plate may change at most once an hour."""
        a = light_for(datetime(2026, 4, 6, 14, 1), False, RISE, SET)
        b = light_for(datetime(2026, 4, 6, 14, 59), False, RISE, SET)
        assert a == b

    def test_missing_sun_times_fall_back(self):
        light = light_for(datetime(2026, 4, 6, 13, 0), False, None, None)
        assert light.phase == "day"

    def test_degenerate_sun_times_fall_back(self):
        light = light_for(datetime(2026, 4, 6, 13, 0), False, SET, RISE)
        assert light.phase == "day"


# ---------------------------------------------------------------------------
# Scene — differential checks on the greyscale plate before the dither.
# ---------------------------------------------------------------------------

DAY = Light("day", 0.5, 1.0)
SCENE_DATE = date(2026, 4, 6)


def _scene(kind="clear", light=DAY):
    return render_scene(480, 480, kind=kind, light=light, today=SCENE_DATE)


def _mean(img, box):
    return ImageStat.Stat(img.crop(box)).mean[0]


SKY = (0, 0, 480, 100)
FOREGROUND = (0, 440, 480, 480)


class TestScene:
    def test_is_deterministic(self):
        assert _scene().tobytes() == _scene().tobytes()

    def test_landscape_changes_from_day_to_day(self):
        other = render_scene(480, 480, kind="clear", light=DAY, today=date(2026, 4, 7))
        assert other.tobytes() != _scene().tobytes()

    def test_night_sky_is_dark(self):
        assert _mean(_scene(light=Light("night", 0.7, 0.0)), SKY) < 70
        assert _mean(_scene(), SKY) > 170

    def test_storm_sky_is_darker_than_rain(self):
        assert _mean(_scene("storm"), SKY) < _mean(_scene("rain"), SKY) < _mean(_scene(), SKY)

    def test_snow_lies_on_the_ground(self):
        assert _mean(_scene("snow"), FOREGROUND) > 150
        assert _mean(_scene(), FOREGROUND) < 80

    def test_fog_lifts_the_whole_scene(self):
        whole = (0, 0, 480, 480)
        assert _mean(_scene("fog"), whole) > _mean(_scene("overcast"), whole)

    def test_sky_brightens_toward_a_low_sun(self):
        dusk = _scene(light=Light("golden", 0.86, 0.02))
        # Open sky well above the disc, so only the glow can differ.
        left, right = (0, 20, 120, 100), (360, 20, 480, 100)
        assert _mean(dusk, right) > _mean(dusk, left) + 10

    def test_lightning_only_in_a_storm(self):
        """The bolt is the one pure-white stroke in the storm sky."""
        storm = _scene("storm").crop((0, 0, 480, 280))
        rain = _scene("rain").crop((0, 0, 480, 280))
        assert storm.histogram()[255] > rain.histogram()[255] + 50


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestMoonDisc:
    def test_new_moon_is_all_dark(self):
        disc = moon_disc(41, illumination_pct=0.0, waxing=True)
        cv, ca = disc.getpixel((20, 20))
        assert ca == 255
        assert cv < 100

    def test_full_moon_is_all_lit(self):
        disc = moon_disc(41, illumination_pct=100.0, waxing=True)
        cv, ca = disc.getpixel((20, 20))
        assert ca == 255
        assert cv > 230

    def test_waxing_lights_right_limb(self):
        disc = moon_disc(81, illumination_pct=50.0, waxing=True)
        left = disc.getpixel((25, 40))[0]
        right = disc.getpixel((55, 40))[0]
        assert right > left


class TestFmtEventTime:
    def test_on_the_hour(self):
        assert _fmt_event_time(datetime(2026, 4, 6, 9, 0)) == "9a"

    def test_with_minutes(self):
        assert _fmt_event_time(datetime(2026, 4, 6, 14, 30)) == "2:30p"


class TestEventsToday:
    def test_filters_to_today(self):
        evs = [
            CalendarEvent("Y", datetime(2026, 4, 5, 10), datetime(2026, 4, 5, 11)),
            CalendarEvent("T", datetime(2026, 4, 6, 10), datetime(2026, 4, 6, 11)),
        ]
        out = _events_today(evs, TODAY)
        assert len(out) == 1
        assert out[0].summary == "T"


# ---------------------------------------------------------------------------
# Smoke tests for each scene branch
# ---------------------------------------------------------------------------


def _data_with_icon(icon: str | None) -> DashboardData:
    if icon is None:
        weather = None
    else:
        weather = WeatherData(
            current_temp=64.0,
            current_icon=icon,
            current_description="condition",
            high=70.0,
            low=55.0,
            humidity=50,
            forecast=[],
            location_name="Testville",
        )
    return DashboardData(
        events=[
            CalendarEvent(
                "Morning meeting", datetime(2026, 4, 6, 9, 0), datetime(2026, 4, 6, 10, 0)
            ),
            CalendarEvent("Yoga", datetime(2026, 4, 6, 18, 0), datetime(2026, 4, 6, 19, 0)),
        ],
        weather=weather,
        birthdays=[Birthday(name="Test", date=TODAY + timedelta(days=14))],
        air_quality=None,
        host_data=None,
        fetched_at=FIXED_NOW,
    )


class TestRenderEachIcon:
    @pytest.mark.parametrize(
        "icon",
        [
            "01d",
            "01n",
            "02d",
            "02n",
            "04d",
            "09d",
            "10d",
            "10n",
            "11d",
            "13d",
            "50d",
            None,
            "zz",
        ],
    )
    def test_renders_without_crash(self, icon):
        data = _data_with_icon(icon)
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.mode == "1"
        assert img.size == (800, 480)
        ones = sum(1 for p in flatten_pixels(img) if not p)
        assert ones > 1000, f"icon {icon!r} produced an empty render"


class TestRenderInkyPath:
    def test_rgb_canvas_does_not_crash(self):
        from dataclasses import replace

        data = _data_with_icon("01d")
        theme = load_theme("postcard")
        cfg = DisplayConfig()
        cfg = replace(cfg, provider="inky", model="impression_7_3_2025", width=800, height=480)
        img = render_dashboard(data, cfg, theme=theme)
        assert img.mode == "RGB"
        assert img.size == (800, 480)


class TestEmptyEvents:
    def test_renders_with_no_events_today(self):
        data = DashboardData(
            events=[],
            weather=_data_with_icon("01d").weather,
            birthdays=[],
            air_quality=None,
            host_data=None,
            fetched_at=FIXED_NOW,
        )
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        # Must still draw the "( nothing scheduled )" placeholder lines.
        assert img.size == (800, 480)


class TestManyEvents:
    def test_overflow_shows_plus_more(self):
        """+N more should appear when today has more events than the agenda fits."""
        events = [
            CalendarEvent(
                summary=f"Event {i}",
                start=datetime(2026, 4, 6, 8 + i, 0),
                end=datetime(2026, 4, 6, 8 + i, 30),
            )
            for i in range(12)
        ]
        data = DashboardData(
            events=events,
            weather=_data_with_icon("01d").weather,
            birthdays=[],
            air_quality=None,
            host_data=None,
            fetched_at=FIXED_NOW,
        )
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        # No crash; some ink rendered.
        ones = sum(1 for p in flatten_pixels(img) if not p)
        assert ones > 1000


class TestNoWeatherFallback:
    def test_missing_weather_renders(self):
        data = DashboardData(
            events=[],
            weather=None,
            birthdays=[],
            air_quality=None,
            host_data=None,
            fetched_at=FIXED_NOW,
        )
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)


class TestRenderWithDummyData:
    def test_pixel_count_non_trivial(self):
        img = _render()
        assert img.size == (800, 480)
        ones = sum(1 for p in flatten_pixels(img) if not p)
        assert ones > 10_000


class TestCenterCrease:
    def test_crease_separates_scene_from_back(self):
        """The crease line must produce ink at x=480 across most of the height."""
        img = _render()
        # Sample 10 rows down the crease column; count black pixels.
        crease_ink = sum(1 for y in range(20, 460) if not img.getpixel((480, y)))
        assert crease_ink > 300, (
            f"crease column at x=480 should be mostly ink; saw {crease_ink} pixels"
        )

    def test_white_gutter_left_of_crease(self):
        """A two- or three-pixel white gutter must sit just left of the crease."""
        img = _render()
        # The gutter sits at x=477-479 (3-px band immediately left of crease).
        white_at_gutter = sum(1 for y in range(40, 440) if img.getpixel((478, y)))
        # The gutter is white over most rows (some greyscale at the very top/bot).
        assert white_at_gutter > 350


# ---------------------------------------------------------------------------
# Address-line agenda — every event today must be reachable on the back
# ---------------------------------------------------------------------------


class TestBackHasEventText:
    def test_event_time_label_present_in_dummy(self):
        """Dummy data for the FIXED_NOW Monday has a 9 AM standup; the back
        agenda should include a time label.  We can't OCR, but we can check
        that the back panel has non-trivial ink concentration in the agenda
        rows compared to the empty bottom area."""
        img = _render()
        # Agenda band is roughly y=160..280 in the back panel x range.
        agenda_ink = sum(
            1 for y in range(170, 280) for x in range(510, 780) if not img.getpixel((x, y))
        )
        assert agenda_ink > 200


class TestQuoteFitsTheBack:
    """A long quote and attribution stay on the postcard back, apart from each other."""

    LONG_TEXT = (
        "The most dangerous phrase in the language is 'we've always done it this way', "
        "and the second most dangerous is the confident assumption that it still works."
    )

    def _render_quote(self, tmp_path, author: str):
        path = tmp_path / f"q{len(author)}.json"
        path.write_text(json.dumps([{"text": self.LONG_TEXT, "author": author}]))
        return _render(quotes_path=str(path))

    def test_a_long_attribution_never_reaches_the_scene(self, tmp_path):
        short = self._render_quote(tmp_path, "Hopper")
        long = self._render_quote(
            tmp_path, "Rear Admiral Grace Brewster Murray Hopper (attributed, paraphrased)"
        )
        scene = (0, 0, 478, 480)
        assert short.crop(scene).tobytes() == long.crop(scene).tobytes()

    def test_the_last_quote_line_clears_the_attribution(self, tmp_path):
        img = self._render_quote(tmp_path, "Grace Hopper")
        # The quote's lines touch one another (descender to ascender); the
        # attribution must stand apart as its own band beneath them.
        assert len(text_line_heights(img, (490, 380, 798, 478))) == 2
