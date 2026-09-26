"""wide_horizon: the next 72 hours of sky, temperature, rain and events on one axis.

Covers the data it needs (the forecast grid kept at 3-hour resolution, through
the fetcher, the cache and dummy data), the pure helpers the plate is built
from (the time axis, the sky colour ramp, the turning-point labels, the
outlook), and differential render assertions for each band. Every render
assertion here was checked by deleting the behaviour it names and watching it
go red (see CLAUDE.md, "Verify a render test by deleting what it names").
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.app import EXTRA_EVENT_DAYS, THEMES_NEEDING_TOMORROW
from src.astronomy import solar_altitude, sun_times
from src.config import DisplayConfig, WeatherConfig
from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    HourlyForecast,
    WeatherAlert,
    WeatherData,
)
from src.display.driver import WAVESHARE_G_PALETTE, image_hash
from src.dummy_data import generate_dummy_data
from src.fetchers.cache import _deser_weather, _ser_weather
from src.fetchers.weather import _parse_hourly, fetch_weather
from src.render import fonts
from src.render.canvas import render_dashboard
from src.render.components import wide_horizon_panel as wh
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED, INKY_YELLOW, ComponentRegion, load_theme
from tests.inkutils import ink

NOW = datetime(2026, 4, 6, 10, 30)  # a Monday; the window runs 09:00 Mon → 09:00 Thu
SF = (37.77, -122.42)
# The render tests hand the plate a naive clock, which reads as UTC; London
# keeps the sun where that clock says it is.
LONDON = (51.5, -0.12)
REGION = ComponentRegion(0, 0, 1360, 480)
NATIVE_G = DisplayConfig(provider="waveshare", model="epd10in85g", width=1360, height=480)
NATIVE_MONO = DisplayConfig(provider="waveshare", model="epd7in5_V2", width=1360, height=480)

SKY = wh.sky_rect(REGION)
SKY_Y1 = SKY[3]
RAIN_BAND = (SKY[0], SKY_Y1, SKY[2], SKY_Y1 + wh.RAIN_H)
EVENTS_Y0 = SKY_Y1 + wh.RAIN_H + wh.HOURS_H + wh.EVENTS_GAP
HERO = (0, 0, wh.HERO_W, 480)

RED = INKY_SPECTRA6_PALETTE[INKY_RED]
YELLOW = INKY_SPECTRA6_PALETTE[INKY_YELLOW]


def _axis(now: datetime = NOW) -> wh.TimeAxis:
    return wh.TimeAxis(wh.window_start(now), wh.WINDOW_HOURS, SKY[0], SKY[2])


def _slots(temps, start=datetime(2026, 4, 6, 9), icon="01d", pop=0.0, mm=None):
    return [
        HourlyForecast(start + timedelta(hours=3 * i), t, icon, precip_chance=pop, precip_mm=mm)
        for i, t in enumerate(temps)
    ]


def _weather(hourly=(), **kw) -> WeatherData:
    base = dict(
        current_temp=42.0,
        current_icon="01d",
        current_description="clear sky",
        high=48.0,
        low=35.0,
        humidity=60,
        hourly=list(hourly),
    )
    base.update(kw)
    return WeatherData(**base)


def _diurnal(n=26, start=datetime(2026, 4, 6, 9)):
    """A clear forecast with a real daily swing: low at 06:00, high at 15:00."""
    out = []
    for i in range(n):
        t = start + timedelta(hours=3 * i)
        temp = 45 + 8 * math.cos(math.pi * ((t.hour - 15) % 24) / 12)
        out.append(HourlyForecast(t, round(temp, 1), "01d", precip_chance=0.0))
    return out


def _plate(data: DashboardData, mode="RGB", now=NOW, coords=LONDON) -> Image.Image:
    img = Image.new(mode, (1360, 480), "white")
    wh.draw_wide_horizon(
        ImageDraw.Draw(img),
        data,
        now.date(),
        now,
        image=img,
        region=REGION,
        latitude=coords[0],
        longitude=coords[1],
    )
    return img


def _count(img: Image.Image, rgb, box) -> int:
    arr = np.asarray(img.crop(box).convert("RGB")).reshape(-1, 3)
    return int(np.all(arr == np.array(rgb, np.uint8), axis=1).sum())


# ---------------------------------------------------------------------------
# Data: the forecast grid at its own resolution
# ---------------------------------------------------------------------------


def _owm_slot(ts: datetime, temp=50.0, icon="10d", pop=0.4, rain=None, snow=None) -> dict:
    slot = {
        "dt": int(ts.timestamp()),
        "main": {"temp": temp, "temp_max": temp + 1, "temp_min": temp - 1},
        "weather": [{"icon": icon, "description": "light rain"}],
        "pop": pop,
    }
    if rain is not None:
        slot["rain"] = {"3h": rain}
    if snow is not None:
        slot["snow"] = {"3h": snow}
    return slot


class TestHourlyParsing:
    def test_keeps_every_usable_slot_in_time_order(self):
        base = datetime(2026, 4, 6, 12, tzinfo=timezone.utc)
        slots = [_owm_slot(base + timedelta(hours=3 * i), temp=40 + i) for i in (2, 0, 1)]
        hourly = _parse_hourly(slots, timezone.utc)
        assert [h.temp for h in hourly] == [40, 41, 42]
        assert all(h.time.tzinfo is not None for h in hourly)

    def test_sums_rain_and_snow_and_leaves_none_without_either(self):
        base = datetime(2026, 4, 6, 12, tzinfo=timezone.utc)
        hourly = _parse_hourly(
            [_owm_slot(base, rain=1.5, snow=0.5), _owm_slot(base + timedelta(hours=3))],
            timezone.utc,
        )
        assert hourly[0].precip_mm == pytest.approx(2.0)
        assert hourly[1].precip_mm is None
        assert hourly[0].precip_chance == pytest.approx(0.4)

    def test_skips_malformed_slots(self):
        base = datetime(2026, 4, 6, 12, tzinfo=timezone.utc)
        good = _owm_slot(base)
        no_main = {"dt": good["dt"] + 1, "weather": good["weather"]}
        no_weather = {**good, "dt": good["dt"] + 2, "weather": []}
        no_temp = {**good, "dt": good["dt"] + 3, "main": {"humidity": 50}}
        no_dt = {k: v for k, v in good.items() if k != "dt"}
        assert len(_parse_hourly([good, no_main, no_weather, no_temp, no_dt], timezone.utc)) == 1

    @patch("src.fetchers.weather.requests.Session")
    def test_fetch_weather_carries_the_grid(self, mock_session_cls):
        base = datetime(2026, 4, 6, 12, tzinfo=timezone.utc)
        current = MagicMock()
        current.json.return_value = {
            "main": {"temp": 42.0, "temp_max": 48.0, "temp_min": 35.0, "humidity": 65},
            "weather": [{"icon": "02d", "description": "partly cloudy"}],
        }
        forecast = MagicMock()
        forecast.json.return_value = {
            "list": [_owm_slot(base + timedelta(hours=3 * i)) for i in range(8)]
        }
        session = mock_session_cls.return_value.__enter__.return_value
        session.get.side_effect = [current, forecast]
        cfg = WeatherConfig(api_key="k", latitude=1.0, longitude=2.0, one_call_version="off")
        weather = fetch_weather(cfg, tz=timezone.utc)
        assert len(weather.hourly) == 8
        assert weather.hourly[0].time == base


class TestHourlyCache:
    def test_round_trips(self):
        hourly = [
            HourlyForecast(
                datetime(2026, 4, 6, 9, tzinfo=timezone.utc), 41.5, "10d", 0.8, precip_mm=2.5
            ),
            HourlyForecast(datetime(2026, 4, 6, 12, tzinfo=timezone.utc), 44.0, "02d"),
        ]
        back = _deser_weather(_ser_weather(_weather(hourly)))
        assert back.hourly == hourly

    def test_an_entry_from_before_the_grid_was_kept_loads_empty(self):
        blob = _ser_weather(_weather())
        del blob["hourly"]
        assert _deser_weather(blob).hourly == []


class TestDummyHourly:
    def test_forty_three_hour_slots_from_the_current_slot(self):
        data = generate_dummy_data(now=NOW)
        hourly = data.weather.hourly
        assert len(hourly) == 40
        assert hourly[0].time.replace(tzinfo=None) == datetime(2026, 4, 6, 9)
        assert {b.time - a.time for a, b in zip(hourly, hourly[1:])} == {timedelta(hours=3)}

    def test_curve_is_continuous_across_midnight(self):
        temps = [h.temp for h in generate_dummy_data(now=NOW).weather.hourly]
        assert max(abs(b - a) for a, b in zip(temps, temps[1:])) < 8


# ---------------------------------------------------------------------------
# Astronomy
# ---------------------------------------------------------------------------


class TestSolarAltitude:
    def test_solstice_noon_is_ninety_minus_latitude_plus_tilt(self):
        noon = sun_times(date(2026, 6, 21), *SF).solar_noon
        assert solar_altitude(noon, *SF) == pytest.approx(90 - SF[0] + 23.44, abs=0.3)

    def test_sunrise_sits_at_the_horizon(self):
        rise = sun_times(date(2026, 3, 20), *SF).sunrise
        assert solar_altitude(rise, *SF) == pytest.approx(-0.83, abs=0.3)

    def test_midnight_is_below_the_horizon_and_naive_reads_as_utc(self):
        midnight = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)  # 00:00 PST
        assert solar_altitude(midnight, *SF) < -50
        assert solar_altitude(midnight.replace(tzinfo=None), *SF) == solar_altitude(midnight, *SF)


# ---------------------------------------------------------------------------
# The time axis
# ---------------------------------------------------------------------------


class TestTimeAxis:
    def test_window_starts_at_the_current_slot(self):
        assert wh.window_start(datetime(2026, 4, 6, 10, 59)) == datetime(2026, 4, 6, 9)
        assert wh.window_start(datetime(2026, 4, 6, 0, 1)) == datetime(2026, 4, 6, 0)

    def test_spans_the_sky_and_inverts(self):
        axis = _axis()
        assert axis.x(axis.start) == SKY[0] and axis.x(axis.end) == SKY[2]
        for hours in (0.5, 13.25, 40, 71.9):
            t = axis.start + timedelta(hours=hours)
            assert abs((axis.t(axis.x(t)) - t).total_seconds()) < 1

    def test_clamps_outside_the_window(self):
        axis = _axis()
        assert axis.x(axis.start - timedelta(hours=5)) == SKY[0]
        assert axis.x(axis.end + timedelta(hours=5)) == SKY[2]

    def test_night_hours_are_compressed(self):
        axis = _axis()
        day = axis.x(datetime(2026, 4, 6, 15)) - axis.x(datetime(2026, 4, 6, 14))
        night = axis.x(datetime(2026, 4, 7, 3)) - axis.x(datetime(2026, 4, 7, 2))
        assert night == pytest.approx(day * wh.NIGHT_WEIGHT)
        assert axis.px_per_hour(14) == pytest.approx(day)

    def test_waking_hours_gain_width_over_a_linear_axis(self):
        axis = _axis()
        linear = (SKY[2] - SKY[0]) / wh.WINDOW_HOURS
        assert axis.px_per_hour(10) > 1.2 * linear
        assert axis.px_per_hour(10) / 2 >= 9  # a thirty-minute meeting


# ---------------------------------------------------------------------------
# Sky
# ---------------------------------------------------------------------------


class TestSkyField:
    def test_colour_sky_uses_only_the_four_inks(self):
        axis = _axis()
        alt = wh.column_altitudes(axis, SKY[2] - SKY[0], wh.altitude_fn(None, *SF, None))
        field = np.asarray(wh.sky_field(alt, wh.SKY_H, SKY[0], SKY[1], "RGB")).reshape(-1, 3)
        colours = {tuple(int(c) for c in px) for px in np.unique(field, axis=0)}
        assert colours == {(0, 0, 0), (255, 255, 255), RED, YELLOW}

    def test_mono_sky_is_bilevel(self):
        alt = np.linspace(-30, 40, 200)
        field = np.asarray(wh.sky_field(alt, 50, 0, 0, "L"))
        assert set(np.unique(field)) == {0, 255}

    def test_day_is_paper_and_deep_night_is_ink(self):
        alt = np.array([60.0] * 10 + [-40.0] * 10)
        for mode in ("L", "RGB"):
            field = np.asarray(wh.sky_field(alt, 40, 0, 0, mode).convert("L"))
            assert field[:, :10].min() == 255, mode
            assert field[:, 10:].max() == 0, mode

    def test_twilight_is_a_mixture_of_red_and_yellow(self):
        alt = np.full(64, -3.0)  # between sunset and civil dusk
        field = np.asarray(wh.sky_field(alt, 1, 0, 0, "RGB")).reshape(-1, 3)
        colours = {tuple(int(c) for c in px) for px in field}
        assert colours == {RED, YELLOW}

    def test_the_horizon_glows_brighter_than_the_zenith(self):
        alt = np.full(64, -8.0)
        field = np.asarray(wh.sky_field(alt, 200, 0, 0, "L"))
        assert field[-20:].mean() > field[:20].mean()

    def test_without_coordinates_the_reported_sun_times_place_the_night(self):
        weather = _weather(
            sunrise=datetime(2026, 4, 6, 6, 30, tzinfo=timezone.utc),
            sunset=datetime(2026, 4, 6, 19, 30, tzinfo=timezone.utc),
        )
        alt = wh.altitude_fn(weather, None, None, timezone.utc)
        assert alt(datetime(2026, 4, 6, 13)) > 40
        assert alt(datetime(2026, 4, 6, 1)) < -20
        assert alt(datetime(2026, 4, 6, 20)) == pytest.approx(-6.0)
        assert wh.altitude_fn(None, 0.0, 0.0, None)(datetime(2026, 4, 6, 13)) > 40

    def test_a_naive_clock_places_the_sun_by_longitude(self):
        assert wh.sun_zone(None, 40.7, -74.0) == timezone(timedelta(hours=-5))
        assert wh.sun_zone(timezone.utc, 40.7, -74.0) is timezone.utc
        assert wh.sun_zone(None, None, None) is None
        alt = wh.altitude_fn(None, 40.7, -74.0, wh.sun_zone(None, 40.7, -74.0))
        assert alt(datetime(2026, 4, 6, 13)) > 45  # early afternoon in New York
        assert alt(datetime(2026, 4, 6, 1)) < -20

    def test_sky_kind(self):
        assert wh.sky_kind("01d") == (0, "")
        assert wh.sky_kind("04n") == (3, "")
        assert wh.sky_kind("10d") == (2, "rain")
        assert wh.sky_kind("11d") == (3, "storm")
        assert wh.sky_kind("13n") == (3, "snow")
        assert wh.sky_kind("50d") == (1, "fog")
        assert wh.sky_kind(None) == (0, "")

    def test_a_wet_noon_hides_the_sun(self):
        noon = datetime(2026, 4, 6, 13)
        wet = [(datetime(2026, 4, 6, 12), HourlyForecast(noon, 40, "10d"))]
        dry = [(datetime(2026, 4, 6, 12), HourlyForecast(noon, 40, "02d"))]
        assert wh.sun_hidden(wet, noon)
        assert not wh.sun_hidden(dry, noon)
        assert not wh.sun_hidden([], noon)

    def test_moon_transit_follows_the_phase(self):
        # 2026-05-01 is full: its transit is near local midnight.
        transit = wh.moon_transit(date(2026, 5, 1))
        assert abs((transit - datetime(2026, 5, 2, 0)).total_seconds()) < 3 * 3600


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------


class TestTemperature:
    def test_window_slots_keep_one_neighbour_each_side(self):
        axis = _axis()
        hourly = _slots(range(40), start=datetime(2026, 4, 6, 3))
        kept = wh.window_slots(hourly, axis, None)
        assert kept[0][0] == datetime(2026, 4, 6, 6)
        assert kept[-1][0] == datetime(2026, 4, 9, 12)

    def test_extremes_are_turning_points_only(self):
        axis = _axis()
        slots = wh.window_slots(_diurnal(), axis, None)
        found = wh.daily_extremes(slots, axis)
        highs = [t for kind, t, _ in found if kind == "high"]
        lows = [t for kind, t, _ in found if kind == "low"]
        assert all(t.hour == 15 for t in highs) and len(highs) == 3
        assert all(t.hour == 3 for t in lows) and len(lows) == 3

    def test_a_falling_evening_at_the_window_edge_is_not_a_high(self):
        start = datetime(2026, 4, 6, 18)
        axis = wh.TimeAxis(start, wh.WINDOW_HOURS, SKY[0], SKY[2])
        hourly = _slots([52, 48, 44, 40, 38, 36], start=datetime(2026, 4, 6, 15))
        found = wh.daily_extremes(wh.window_slots(hourly, axis, None), axis)
        assert not [f for f in found if f[0] == "high" and f[1].date() == start.date()]

    def test_scale_widens_a_flat_day(self):
        assert wh.temp_scale([50, 52]) == (51 - wh.MIN_TEMP_SPAN / 2, 51 + wh.MIN_TEMP_SPAN / 2)
        assert wh.temp_scale([30, 70]) == (30, 70)

    def test_catmull_rom_passes_through_its_points(self):
        pts = [(0.0, 10.0), (40.0, 30.0), (80.0, 5.0), (120.0, 20.0)]
        curve = wh.catmull_rom(pts)
        for p in pts:
            assert p in curve
        assert wh.catmull_rom(pts[:2]) == pts[:2]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def _event(summary, start, hours=1.0, all_day=False):
    return CalendarEvent(summary, start, start + timedelta(hours=hours), is_all_day=all_day)


class TestEventSelection:
    def test_timed_events_overlapping_the_window(self):
        axis = _axis()
        inside = _event("In", datetime(2026, 4, 7, 10))
        running = _event("Running", datetime(2026, 4, 6, 8), hours=2)
        before = _event("Before", datetime(2026, 4, 6, 7))
        after = _event("After", datetime(2026, 4, 9, 10))
        allday = _event("All", datetime(2026, 4, 7), hours=24, all_day=True)
        got = wh.events_in_window([after, inside, running, before, allday], axis)
        assert [e.summary for e in got] == ["Running", "In"]

    def test_all_day_spans_and_birthdays(self):
        axis = _axis()
        conf = _event("Conference", datetime(2026, 4, 8), hours=24, all_day=True)
        gone = _event("Gone", datetime(2026, 4, 1), hours=24, all_day=True)
        bdays = [
            Birthday("Mom", date(1960, 4, 7)),
            Birthday("Jake", date(1996, 4, 8), age=30),
            Birthday("Later", date(1990, 5, 1)),
        ]
        rows = wh.allday_in_window([conf, gone], bdays, axis)
        assert [(r[2], r[3]) for r in rows] == [
            ("Mom's birthday", True),
            ("Conference", False),
            ("Jake turns 30", True),
        ]

    def test_all_day_with_date_bounds_and_zero_length(self):
        axis = _axis()
        e = CalendarEvent("Holiday", date(2026, 4, 7), date(2026, 4, 7), is_all_day=True)
        (row,) = wh.allday_in_window([e], [], axis)
        assert row[1] - row[0] == timedelta(days=1)


# ---------------------------------------------------------------------------
# Outlook
# ---------------------------------------------------------------------------


class TestOutlook:
    def test_warmest_coldest_and_first_rain(self):
        axis = _axis()
        hourly = _diurnal()
        hourly[5].precip_chance = 0.6  # Tue 00:00
        hourly[6].precip_chance = 0.8  # Tue 03:00
        rows = dict(wh.outlook(wh.window_slots(hourly, axis, None), axis))
        assert rows["WARMEST"].endswith("53°")
        assert rows["COLDEST"].endswith("37°")
        assert rows["RAIN"] == "Tue 12a–6a · 80%"

    def test_rain_ending_at_midnight_says_so(self):
        axis = _axis()
        hourly = _diurnal()
        hourly[4].precip_chance = 0.5  # Mon 21:00, ends at midnight
        assert dict(wh.outlook(wh.window_slots(hourly, axis, None), axis))["RAIN"] == (
            "Mon 9p–midnight · 50%"
        )

    def test_dry(self):
        axis = _axis()
        assert dict(wh.outlook(wh.window_slots(_diurnal(), axis, None), axis))["RAIN"] == (
            "none in sight"
        )
        assert wh.outlook([], axis) == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRender:
    def test_theme_shape(self):
        theme = load_theme("wide_horizon")
        assert (theme.layout.canvas_w, theme.layout.canvas_h) == (1360, 480)
        assert theme.layout.draw_order == ["wide_horizon"]
        assert theme.layout.preferred_quantization_mode == "ordered"
        assert not theme.allows_partial_refresh  # derived: the plate dithers

    def test_needs_three_days_past_the_week(self):
        assert EXTRA_EVENT_DAYS["wide_horizon"] == 3
        assert "wide_horizon" in THEMES_NEEDING_TOMORROW

    def test_native_colour_render_is_exact_inks(self):
        img = render_dashboard(
            generate_dummy_data(now=NOW),
            NATIVE_G,
            theme=load_theme("wide_horizon"),
            latitude=SF[0],
            longitude=SF[1],
        )
        arr = np.asarray(img.convert("RGB")).reshape(-1, 3)
        colours = {tuple(int(c) for c in px) for px in np.unique(arr, axis=0)}
        assert colours <= set(WAVESHARE_G_PALETTE)
        assert len(colours) == 4

    def test_native_mono_render_uses_all_its_bands(self):
        img = render_dashboard(
            generate_dummy_data(now=NOW),
            NATIVE_MONO,
            theme=load_theme("wide_horizon"),
            latitude=SF[0],
            longitude=SF[1],
        )
        assert img.size == (1360, 480)
        for box in (HERO, (SKY[0], 0, 1360, SKY[1]), SKY, (SKY[0], EVENTS_Y0, 1360, 480)):
            assert ink(img.convert("1"), box) > 500, box

    def test_temperature_curve_is_drawn_from_the_hourly_grid(self):
        # Monday's afternoon, where the sky is paper and red can only be the line.
        axis = _axis()
        x0, x1 = int(axis.x(datetime(2026, 4, 6, 11))), int(axis.x(datetime(2026, 4, 6, 16)))
        afternoon = (x0, SKY[1], x1, SKY[3])
        with_grid = _plate(DashboardData(weather=_weather(_diurnal())))
        without = _plate(DashboardData(weather=_weather()))
        assert _count(with_grid, RED, afternoon) > 300
        assert _count(without, RED, afternoon) == 0

    def test_temperature_labels_follow_the_data(self):
        warm = _plate(DashboardData(weather=_weather(_diurnal())), mode="L")
        hourly = _diurnal()
        for h in hourly:
            h.temp -= 30
        cold = _plate(DashboardData(weather=_weather(hourly)), mode="L")
        assert image_hash(warm.crop(SKY)) != image_hash(cold.crop(SKY))

    def test_rain_hangs_in_its_band_only_when_forecast(self):
        dry = _diurnal()
        wet = _diurnal()
        for h in wet[4:8]:
            h.precip_chance = 0.9
            h.precip_mm = 3.0
        dry_img = _plate(DashboardData(weather=_weather(dry)), mode="L")
        wet_img = _plate(DashboardData(weather=_weather(wet)), mode="L")
        assert ink(wet_img.convert("1"), RAIN_BAND) > ink(dry_img.convert("1"), RAIN_BAND) + 300

    @staticmethod
    def _with_icon(icon):
        hourly = _diurnal()
        for h in hourly:
            h.icon = icon
        return DashboardData(weather=_weather(hourly))

    def test_overcast_draws_clouds(self):
        # Tuesday 07:30-10:00: daylight, clear of the noon sun and of the curve.
        axis = _axis()
        x0, x1 = int(axis.x(datetime(2026, 4, 7, 7, 30))), int(axis.x(datetime(2026, 4, 7, 10)))
        cloud_row = (x0, SKY[1] + wh.CLOUD_TOP, x1, SKY[1] + wh.CLOUD_TOP + wh.CLOUD_ROW_H)
        clear = _plate(self._with_icon("01d"), mode="L").convert("1")
        overcast = _plate(self._with_icon("04d"), mode="L").convert("1")
        assert ink(clear, cloud_row) == 0
        assert ink(overcast, cloud_row) > 400

    def test_rain_falls_below_the_clouds(self):
        axis = _axis()
        x0, x1 = int(axis.x(datetime(2026, 4, 7, 7, 30))), int(axis.x(datetime(2026, 4, 7, 10)))
        below = wh.CLOUD_TOP + wh.CLOUD_ROW_H
        under = (x0, SKY[1] + below + 2, x1, SKY[1] + below + 26)
        overcast = _plate(self._with_icon("04d"), mode="L").convert("1")
        raining = _plate(self._with_icon("09d"), mode="L").convert("1")
        assert ink(raining, under) > ink(overcast, under) + 40

    def test_snow_falls_below_the_clouds(self):
        axis = _axis()
        x0, x1 = int(axis.x(datetime(2026, 4, 7, 7, 30))), int(axis.x(datetime(2026, 4, 7, 10)))
        below = wh.CLOUD_TOP + wh.CLOUD_ROW_H
        under = (x0, SKY[1] + below + 2, x1, SKY[1] + below + 34)
        overcast = _plate(self._with_icon("04d"), mode="L").convert("1")
        snowing = _plate(self._with_icon("13d"), mode="L").convert("1")
        assert ink(snowing, under) > ink(overcast, under) + 20

    def test_a_storm_carries_a_yellow_bolt(self):
        axis = _axis()
        x0, x1 = int(axis.x(datetime(2026, 4, 7, 6))), int(axis.x(datetime(2026, 4, 7, 12)))
        below = wh.CLOUD_TOP + wh.CLOUD_ROW_H
        under = (x0, SKY[1] + 20, x1, SKY[1] + below + 50)
        raining = _plate(self._with_icon("09d"))
        storm = _plate(self._with_icon("11d"))
        assert _count(storm, YELLOW, under) > _count(raining, YELLOW, under) + 50

    def test_fog_lies_in_bands_across_the_lower_sky(self):
        axis = _axis()
        x0, x1 = int(axis.x(datetime(2026, 4, 7, 7, 30))), int(axis.x(datetime(2026, 4, 7, 10)))
        low = (x0, SKY[1] + int(wh.SKY_H * 0.5), x1, SKY[1] + int(wh.SKY_H * 0.85))
        clear = _plate(self._with_icon("01d"), mode="L").convert("1")
        fog = _plate(self._with_icon("50d"), mode="L").convert("1")
        assert ink(fog, low) > ink(clear, low) + 100

    def test_an_overcast_noon_has_no_sun(self):
        axis = _axis()
        noon = sun_times(NOW.date(), *LONDON).solar_noon.replace(tzinfo=None)
        x = int(axis.x(noon))
        disc = (x - 30, SKY[1], x + 30, SKY[1] + 100)
        clear = _plate(self._with_icon("01d"))
        overcast = _plate(self._with_icon("04d"))
        assert _count(clear, YELLOW, disc) > 200
        assert _count(overcast, YELLOW, disc) == 0

    def test_an_event_is_a_bar_at_its_time(self):
        evt = _event("Dentist", datetime(2026, 4, 7, 14), hours=2)
        axis = _axis()
        x0, x1 = int(axis.x(evt.start)), int(axis.x(evt.end))
        band = (x0 + 2, EVENTS_Y0, x1 - 2, EVENTS_Y0 + wh.LANE_H)
        empty = _plate(DashboardData(), mode="L")
        booked = _plate(DashboardData(events=[evt]), mode="L")
        assert ink(booked.convert("1"), band) > ink(empty.convert("1"), band) + 200

    def test_overflowing_lanes_count_the_rest(self):
        day = datetime(2026, 4, 7, 10)
        events = [_event(f"Meeting {i}", day, hours=1) for i in range(12)]
        img = _plate(DashboardData(events=events), mode="L")
        few = _plate(DashboardData(events=events[:3]), mode="L")
        foot = (SKY[0], 480 - 22, 1360, 480)
        assert ink(img.convert("1"), foot) > ink(few.convert("1"), foot)

    def test_hero_shows_the_reading_and_an_alert(self):
        calm = _plate(DashboardData(weather=_weather(_diurnal())))
        alert = _plate(DashboardData(weather=_weather(_diurnal(), alerts=[WeatherAlert("Flood")])))
        assert _count(alert, RED, HERO) > _count(calm, RED, HERO) + 1000

    def test_hero_reading_shrinks_to_fit(self):
        img = _plate(DashboardData(weather=_weather(current_temp=-108.0)), mode="L")
        right_margin = (wh.HERO_W - wh.PAD + 2, 30, wh.HERO_W, 170)
        assert ink(img.convert("1"), right_margin) == (right_margin[2] - right_margin[0]) * 140

    def test_draws_on_every_canvas_mode_without_data(self):
        for mode in ("1", "L", "RGB"):
            img = _plate(DashboardData(), mode=mode, coords=(None, None))
            assert ink(img.convert("1"), HERO) > 1000, mode

    def test_idle_tick_is_stable_and_the_slot_boundary_is_not(self):
        data = generate_dummy_data(now=NOW)
        data.content_at = NOW  # the last fetch; captions read it, not the clock

        def at(now):
            return image_hash(_plate(data, now=now))

        assert at(NOW) == at(NOW + timedelta(minutes=25))
        assert at(NOW) != at(datetime(2026, 4, 6, 12, 5))

    def test_art_region_is_declared(self):
        from src.render.components.registry import RenderContext, get_component

        theme = load_theme("wide_horizon")
        img = Image.new("L", (1360, 480), 255)
        ctx = RenderContext(
            draw=ImageDraw.Draw(img),
            data=DashboardData(),
            today=NOW.date(),
            now=NOW,
            layout=theme.layout,
            style=theme.style,
            image=img,
        )
        get_component("wide_horizon")(ctx)
        assert ctx.dither_regions == [SKY]


class TestFonts:
    @pytest.mark.parametrize(
        "accessor",
        [fonts.big_shoulders_semibold, fonts.big_shoulders_extrabold, fonts.big_shoulders_black],
    )
    def test_loads_and_covers_the_glyphs_used(self, accessor):
        font = accessor(30)
        for ch in "0123456789°–·%ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert font.getmask(ch).getbbox() is not None, ch
