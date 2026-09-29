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
from zoneinfo import ZoneInfo

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
NY = ZoneInfo("America/New_York")
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


def to_local(t: datetime) -> datetime:
    """An aware instant as New York wall-clock time, naive — how the panel reads it."""
    return t.astimezone(NY).replace(tzinfo=None)


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
    def test_forty_slots_from_the_next_utc_boundary_like_owm(self):
        data = generate_dummy_data(now=NOW)
        hourly = data.weather.hourly
        assert len(hourly) == 40
        assert hourly[0].time == datetime(2026, 4, 6, 12, tzinfo=timezone.utc)
        ny = generate_dummy_data(tz=NY, now=datetime(2026, 4, 6, 9, 30, tzinfo=NY)).weather
        assert ny.hourly[0].time == datetime(2026, 4, 6, 15, tzinfo=timezone.utc)
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

    def test_moon_is_white_not_the_suns_yellow(self):
        # A full moon on a black night sky: every lit pixel is white, none yellow.
        ink = wh.inks_for("RGB")
        img = Image.new("RGB", (41, 41), ink.black)
        wh._moon_disc(img, ImageDraw.Draw(img), 20, 20, 15, date(2026, 5, 1), ink)
        colours = {c for _, c in img.getcolors(41 * 41)}
        assert ink.white in colours
        assert ink.yellow not in colours


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

    def test_lead_in_fills_the_gap_before_the_first_slot(self):
        # New York at 09:30: the window opens at 09:00 local, OWM's grid at
        # 15:00 UTC = 11:00 local.
        axis = _axis(datetime(2026, 4, 6, 9, 30))
        weather = _weather(current_temp=39.0, current_icon="04d")
        first = datetime(2026, 4, 6, 15, tzinfo=timezone.utc)
        hourly = [HourlyForecast(first + timedelta(hours=3 * i), 50, "01d") for i in range(30)]
        slots = wh.window_slots(hourly, axis, NY)
        assert slots[0][0] == datetime(2026, 4, 6, 11)
        filled = wh.lead_in(slots, weather, axis)
        assert filled[0][0] == datetime(2026, 4, 6, 8)
        assert (filled[0][1].temp, filled[0][1].icon) == (39.0, "04d")
        assert filled[1:] == slots

    def test_lead_in_covers_a_gap_of_two_slots_and_leaves_a_covered_window(self):
        axis = _axis(datetime(2026, 4, 6, 11, 50))  # opens 09:00
        slots = [(datetime(2026, 4, 6, 14), HourlyForecast(datetime(2026, 4, 6, 14), 50, "01d"))]
        filled = wh.lead_in(slots, _weather(), axis)
        assert [t.hour for t, _ in filled] == [8, 11, 14]
        covered = [(datetime(2026, 4, 6, 9), slots[0][1])]
        assert wh.lead_in(covered, _weather(), axis) is covered
        assert wh.lead_in([], _weather(), axis) == []
        assert wh.lead_in(slots, None, axis) is slots

    def test_stand_ins_are_never_labelled_or_in_the_outlook(self):
        # 20:10 in New York: the window opens at 18:00, the grid at 23:00, and
        # the stand-ins between hold the reading now flat — which would
        # otherwise pass as that evening's "high".
        axis = _axis(datetime(2026, 4, 6, 20, 10))
        first = datetime(2026, 4, 7, 3, tzinfo=timezone.utc)
        temps = [38, 35, 33, 36, 44, 48, 45, 40, 37, 35, 38, 45, 50, 47, 42, 39, 36, 40, 47]
        hourly = [
            HourlyForecast(first + timedelta(hours=3 * i), t, "01d") for i, t in enumerate(temps)
        ]
        forecast = wh.window_slots(hourly, axis, NY)
        slots = wh.lead_in(forecast, _weather(current_temp=60.0), axis)
        real_from = forecast[0][0]
        assert slots[0][1].temp == 60.0  # the stand-ins are there...
        labelled = {t for _, t, _ in wh.daily_extremes(slots, axis, real_from)}
        assert all(t >= real_from for t in labelled)  # ...but never labelled
        assert "60°" not in dict(wh.outlook(slots, axis, real_from))["WARMEST"]
        assert "60°" in dict(wh.outlook(slots, axis))["WARMEST"]  # the parameter is what does it

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


class TestDayHeaders:
    # A headline "pixel" per character times 3, a caption one per character:
    # enough to put each rung of the fallback in or out of reach.
    @staticmethod
    def _measure(text, caption):
        return len(text) * (1 if caption else 3)

    def _label(self, day, room, now=datetime(2026, 4, 6, 20, 10)):
        return wh.header_label(day, now, _axis(now), room, self._measure)

    def test_today_that_fits_is_a_headline(self):
        assert self._label(date(2026, 4, 6), 21) == ("TONIGHT", False)

    def test_a_sliver_of_today_is_a_caption_not_its_weekday(self):
        assert self._label(date(2026, 4, 6), 20) == ("TONIGHT", True)

    def test_another_day_falls_back_to_its_short_weekday(self):
        assert self._label(date(2026, 4, 8), 27) == ("WEDNESDAY", False)
        assert self._label(date(2026, 4, 8), 26) == ("WED", False)

    def test_nothing_fits_nothing_is_drawn(self):
        assert self._label(date(2026, 4, 6), 6) == ("", False)
        assert self._label(date(2026, 4, 8), 8) == ("", False)

    def test_today_reads_today_before_the_evening_slot(self):
        morning = datetime(2026, 4, 6, 10, 30)
        assert self._label(date(2026, 4, 6), 100, now=morning) == ("TODAY", False)


class TestLabelPlacement:
    def test_a_label_clear_of_bodies_stays_centred(self):
        assert wh.place_label(500, 50, 40, 30, [], 236, 1360) == 480

    def test_a_label_on_a_sun_slides_to_the_nearer_side(self):
        sun = (470, 40, 520, 90)
        # The point is right of the sun's centre, so the label goes right.
        assert wh.place_label(505, 50, 40, 30, [sun], 236, 1360) == 524
        # Left of centre: it goes left.
        assert wh.place_label(480, 50, 40, 30, [sun], 236, 1360) == 470 - 40 - 4

    def test_boxed_in_it_stays_centred(self):
        bodies = [(470, 40, 520, 90), (400, 40, 466, 90), (524, 40, 600, 90)]
        assert wh.place_label(495, 50, 40, 30, bodies, 236, 1360) == 475


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

    def test_a_chip_too_narrow_for_its_label_uses_the_short_form(self):
        measure = len  # one "pixel" per character keeps the arithmetic visible
        pad = wh.CHIP_PAD
        assert wh.chip_label("Mom's birthday", "Mom", 14 + pad, measure) == "Mom's birthday"
        assert wh.chip_label("Mom's birthday", "Mom", 13 + pad, measure) == "Mom"

    def test_a_birthday_carries_a_short_label(self):
        (row,) = wh.allday_in_window([], [Birthday("Mom", date(1960, 4, 7))], _axis())
        assert (row[2], row[4]) == ("Mom's birthday", "Mom")

    def test_all_day_with_date_bounds_and_zero_length(self):
        axis = _axis()
        e = CalendarEvent("Holiday", date(2026, 4, 7), date(2026, 4, 7), is_all_day=True)
        (row,) = wh.allday_in_window([e], [], axis)
        assert row[1] - row[0] == timedelta(days=1)


# ---------------------------------------------------------------------------
# Outlook
# ---------------------------------------------------------------------------


class TestDaylightSaving:
    """OWM slots are 3 h of real time; the axis is the wall clock (Codex, #316)."""

    @staticmethod
    def _ny_slots(first_utc: datetime, n: int, pop: float = 0.0):
        grid = [
            HourlyForecast(first_utc + timedelta(hours=3 * i), 40.0, "10d", precip_chance=pop)
            for i in range(n)
        ]
        axis = wh.TimeAxis(
            to_local(first_utc - timedelta(hours=3)), wh.WINDOW_HOURS, SKY[0], SKY[2]
        )
        return wh.window_slots(grid, axis, NY), axis

    def test_spring_forward_leaves_no_gap(self):
        # 2026-03-08: 06:00Z is 01:00 EST and 09:00Z is 05:00 EDT.
        slots, _ = self._ny_slots(datetime(2026, 3, 8, 3, tzinfo=timezone.utc), 5)
        starts = [t for t, _ in slots]
        assert datetime(2026, 3, 8, 1) in starts and datetime(2026, 3, 8, 5) in starts
        spans = wh.slot_spans(slots)
        assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
        spring = next(sp for sp in spans if sp[0] == datetime(2026, 3, 8, 1))
        assert spring[1] == datetime(2026, 3, 8, 5)

    def test_fall_back_does_not_overlap(self):
        # 2026-11-01: 03:00Z is 23:00 EDT, 06:00Z is 01:00 EST — two wall hours.
        slots, _ = self._ny_slots(datetime(2026, 11, 1, 0, tzinfo=timezone.utc), 5)
        spans = wh.slot_spans(slots)
        assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
        fall = next(sp for sp in spans if sp[0] == datetime(2026, 10, 31, 23))
        assert fall[1] == datetime(2026, 11, 1, 1)

    def test_a_missing_slot_stays_a_gap(self):
        t0 = datetime(2026, 4, 6, 9)
        slots = [
            (t0, HourlyForecast(t0, 40, "10d")),
            (t0 + timedelta(hours=6), HourlyForecast(t0, 40, "10d")),
        ]
        assert wh.slot_spans(slots)[0][1] == t0 + timedelta(hours=3)

    def test_rain_across_spring_forward_is_one_run(self):
        slots, axis = self._ny_slots(datetime(2026, 3, 8, 3, tzinfo=timezone.utc), 5, pop=0.8)
        rain = dict(wh.outlook(slots, axis))["RAIN"]
        # Through the last slot (11a-2p), not stopped at the jump (would end 4a).
        assert rain == "Sat 10p–2p · 80%"


class TestDayLists:
    def test_columns_run_midnight_to_midnight(self):
        axis = _axis()
        cols = wh.day_columns(axis)
        assert [d for *_x, d in cols] == [date(2026, 4, d) for d in (6, 7, 8, 9)]
        assert cols[0][0] == axis.x0 and cols[-1][1] == axis.x1
        assert all(a[1] == b[0] for a, b in zip(cols, cols[1:]))

    def test_an_event_is_listed_on_its_start_day_or_the_first(self):
        axis = _axis()
        late = _event("Late", datetime(2026, 4, 7, 23), hours=3)
        assert wh.column_day(late, axis) == date(2026, 4, 7)
        early = _event("Running", datetime(2026, 4, 5, 20), hours=16)
        assert wh.column_day(early, axis) == date(2026, 4, 6)

    def test_row_time_is_the_start_or_the_end_of_one_already_running(self):
        axis = _axis()
        assert wh.row_time(_event("A", datetime(2026, 4, 7, 15, 30)), axis) == "3:30p"
        assert wh.row_time(_event("B", datetime(2026, 4, 6, 8), hours=3), axis) == "–11a"

    def test_list_rows(self):
        assert wh.list_rows(3, 0, 6) == (3, 0)
        assert wh.list_rows(6, 0, 6) == (6, 0)
        # One too many: the last row is the count, never a silent cut.
        assert wh.list_rows(7, 0, 6) == (5, 2)
        # Hidden all-day items are counted even when the events fit.
        assert wh.list_rows(2, 1, 6) == (2, 1)
        assert wh.list_rows(6, 1, 6) == (5, 2)
        assert wh.list_rows(4, 0, 0) == (0, 4)

    def test_allday_depth_counts_only_chips_over_the_column(self):
        chips = [(0, 100, 300), (1, 250, 400)]
        assert wh.allday_depth(chips, 0, 90) == 0
        assert wh.allday_depth(chips, 90, 200) == 1
        assert wh.allday_depth(chips, 350, 500) == 2

    def test_fit_text(self):
        assert wh.fit_text("Standup", 7, len) == "Standup"
        assert wh.fit_text("Design review", 7, len) == "Design…"
        assert wh.fit_text("Design review", 0, len) == ""

    @staticmethod
    def _list(img, day, top=0, h=None):
        """Ink in a day's column below the strip (optionally a slice of it)."""
        axis = _axis()
        x0, x1 = next((a, b) for a, b, d in wh.day_columns(axis) if d == day)
        y0 = EVENTS_Y0 + wh.STRIP_H + wh.STRIP_GAP + top
        return ink(img, (int(x0) + 3, y0, int(x1) - 3, 480 - 6 if h is None else y0 + h))

    def test_events_are_listed_in_their_days_column(self):
        evt = _event("Dentist appointment", datetime(2026, 4, 7, 14))
        empty = _plate(DashboardData(), mode="L").convert("1")
        booked = _plate(DashboardData(events=[evt]), mode="L").convert("1")
        tue, wed = date(2026, 4, 7), date(2026, 4, 8)
        assert self._list(booked, tue, h=wh.ROW_H) > self._list(empty, tue, h=wh.ROW_H) + 200
        assert self._list(booked, wed) == self._list(empty, wed)

    def test_one_line_per_event_not_a_staircase(self):
        # Six back-to-back events whose labels would overlap on the time axis
        # fill six rows, and all of them are drawn.
        day = datetime(2026, 4, 7, 9)
        events = [_event(f"Meeting {i}", day + timedelta(hours=i)) for i in range(6)]
        img = _plate(DashboardData(events=events), mode="L").convert("1")
        rows = [self._list(img, day.date(), top=i * wh.ROW_H, h=wh.ROW_H) for i in range(6)]
        assert all(r > 100 for r in rows)

    @staticmethod
    def _stem(font) -> int:
        """The median width of an ``l``'s ink rows: its stem, serifs averaged out."""
        img = Image.new("1", (60, 60), 1)
        ImageDraw.Draw(img).text((5, 5), "l", font=font, fill=0)
        widths = sorted(n for n in (ink(img, (0, y, 60, y + 1)) for y in range(60)) if n)
        return widths[len(widths) // 2]

    def test_rows_are_set_in_literata_with_heavy_stems(self):
        # Read at a glance across a room: DM Sans Bold at 18 px set a 2-px stem.
        title, time = fonts.literata_bold(wh.ROW_TITLE_PT), fonts.literata_bold(wh.ROW_TIME_PT)
        assert self._stem(title) >= 4
        assert self._stem(time) >= 3

    def test_the_rows_draw_in_literata(self):
        evt = _event("Dentist Appointment", datetime(2026, 4, 7, 14))
        data = DashboardData(events=[evt])
        tue = date(2026, 4, 7)
        lit = self._list(_plate(data, mode="L").convert("1"), tue, h=wh.ROW_H)
        with patch.object(fonts, "literata_bold", fonts.dm_bold):
            dm = self._list(_plate(data, mode="L").convert("1"), tue, h=wh.ROW_H)
        assert lit > dm * 1.15

    def test_a_chip_on_another_day_does_not_push_the_list_down(self):
        evt = _event("Dentist", datetime(2026, 4, 7, 14))
        chip = _event("Conference", datetime(2026, 4, 8), hours=24, all_day=True)
        alone = _plate(DashboardData(events=[evt]), mode="L").convert("1")
        beside = _plate(DashboardData(events=[evt, chip]), mode="L").convert("1")
        tue = date(2026, 4, 7)
        # The first row, not the column: a list pushed down keeps its ink.
        first = dict(h=wh.ROW_H)
        assert self._list(beside, tue, **first) == self._list(alone, tue, **first)
        assert self._list(alone, tue, **first) > 200

    def test_a_chip_over_the_day_starts_its_list_below_it(self):
        evt = _event("Dentist", datetime(2026, 4, 7, 14))
        chip = _event("Holiday", datetime(2026, 4, 7), hours=24, all_day=True)
        alone = _plate(DashboardData(events=[evt]), mode="L").convert("1")
        under = _plate(DashboardData(events=[evt, chip]), mode="L").convert("1")
        tue = date(2026, 4, 7)
        second = dict(top=wh.ALLDAY_H + 4, h=wh.ROW_H - 4)
        assert self._list(under, tue, **second) > self._list(alone, tue, **second) + 100


class TestChipHierarchy:
    def test_spans_take_the_top_rows(self):
        # A single day starting with a span, or before it, would win row 0 on
        # a left-to-right packing; the span takes it here.
        items = [(0, 50, False, "dentist"), (0, 300, True, "trip"), (100, 150, False, "gym")]
        assert wh.stack_chips(items) == [["trip"], ["dentist", "gym"]]

    def test_a_single_day_stays_below_every_span_it_crosses(self):
        # Two overlapping spans take rows 0 and 1; a day under the second span
        # goes below it even where row 0 is free.
        items = [(0, 200, True, "a"), (150, 400, True, "b"), (250, 300, False, "day")]
        assert wh.stack_chips(items) == [["a"], ["b"], ["day"]]

    def test_a_day_no_span_crosses_starts_at_the_top(self):
        items = [(0, 200, True, "trip"), (300, 350, False, "day")]
        assert wh.stack_chips(items) == [["trip", "day"]]

    def test_longer_span_first_when_spans_start_together(self):
        items = [(0, 100, True, "short"), (0, 300, True, "long")]
        assert wh.stack_chips(items) == [["long"], ["short"]]

    def test_render_puts_the_span_on_the_top_row(self):
        tue = datetime(2026, 4, 7)
        single = _event("Holiday", tue, hours=24, all_day=True)
        trip = _event("Trip", tue, hours=48, all_day=True)
        axis = _axis()
        x = int(axis.x(datetime(2026, 4, 8, 12)))  # Wednesday: only the trip covers it
        y0 = EVENTS_Y0 + wh.STRIP_H + wh.STRIP_GAP
        top = (x - 20, y0, x + 20, y0 + wh.ALLDAY_H - 4)
        img = _plate(DashboardData(events=[single, trip]))
        assert _count(img, RED, top) > 300


class TestOverflow:
    def test_counts_by_day_with_an_early_start_on_the_first(self):
        axis = _axis()
        starts = [
            datetime(2026, 4, 5, 20),  # began before the window
            datetime(2026, 4, 6, 14),
            datetime(2026, 4, 8, 9),
        ]
        assert wh.overflow_counts(starts, axis) == {date(2026, 4, 6): 2, date(2026, 4, 8): 1}

    def test_a_busy_day_ends_on_a_count_in_its_own_column(self):
        day = datetime(2026, 4, 7, 8)
        events = [_event(f"Meeting {i}", day + timedelta(hours=i)) for i in range(9)]
        many = _plate(DashboardData(events=events))
        six = _plate(DashboardData(events=events[:6]))
        x0, x1 = next((a, b) for a, b, d in wh.day_columns(_axis()) if d == day.date())
        y0 = EVENTS_Y0 + wh.STRIP_H + wh.STRIP_GAP + 5 * wh.ROW_H
        last = (int(x0), y0, int(x1), y0 + wh.ROW_H)
        assert _count(many, RED, last) > 50  # "+4 more" in the accent
        assert _count(six, RED, last) == 0  # six fit exactly: no count

    def test_an_all_day_item_past_the_rows_is_counted(self):
        day = datetime(2026, 4, 7)
        chips = [_event(f"Holiday {i}", day, hours=24, all_day=True) for i in range(3)]
        two = _plate(DashboardData(events=chips[:2]), mode="L").convert("1")
        three = _plate(DashboardData(events=chips), mode="L").convert("1")
        first = dict(top=2 * wh.ALLDAY_H, h=wh.ROW_H)
        assert TestDayLists._list(three, day.date(), **first) > (
            TestDayLists._list(two, day.date(), **first) + 50
        )

    def test_a_count_for_a_narrow_first_day_stays_on_the_plate(self):
        # At 21:30 the window opens at 21:00 and today is a ~45-px sliver, too
        # narrow for a row — the count must not slide into the hero block.
        now = datetime(2026, 4, 6, 21, 30)
        events = [_event(f"Late {i}", datetime(2026, 4, 6, 21, 30), hours=1) for i in range(8)]
        x1 = int(wh.day_columns(_axis(now))[0][1])
        y0 = EVENTS_Y0 + wh.STRIP_H + wh.STRIP_GAP
        col = (SKY[0], y0, x1 - 2, y0 + wh.ROW_H)
        edge = (SKY[0], y0, SKY[0] + 2, y0 + wh.ROW_H)  # where a clipped count would cross
        busy = _plate(DashboardData(events=events), mode="L", now=now).convert("1")
        none = _plate(DashboardData(), mode="L", now=now).convert("1")
        assert ink(busy, col) > ink(none, col) + 20
        assert ink(busy, edge) == ink(none, edge)


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
        # Monday's afternoon below the sun's reach (its rays are red too), where
        # the sky is paper and red can only be the line.
        axis = _axis()
        x0, x1 = int(axis.x(datetime(2026, 4, 6, 11))), int(axis.x(datetime(2026, 4, 6, 16)))
        afternoon = (x0, SKY[1] + 80, x1, SKY[3])
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

    def test_a_negligible_chance_draws_no_bar(self):
        slight = _diurnal()
        for h in slight:
            h.precip_chance = 0.07  # a stated literal: tying it to the constant tests nothing
        img = _plate(DashboardData(weather=_weather(slight)), mode="L").convert("1")
        dry = _plate(DashboardData(weather=_weather(_diurnal())), mode="L").convert("1")
        assert ink(img, RAIN_BAND) == ink(dry, RAIN_BAND)

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

    def test_the_curve_reaches_the_left_edge_before_the_first_slot(self):
        # New York at 09:30: the window opens at 09:00, OWM's grid at 11:00.
        now = datetime(2026, 4, 6, 9, 30, tzinfo=NY)
        first = datetime(2026, 4, 6, 15, tzinfo=timezone.utc)
        hourly = [HourlyForecast(first + timedelta(hours=3 * i), 45.0, "01d") for i in range(30)]
        img = _plate(DashboardData(weather=_weather(hourly)), now=now, coords=(40.7, -74.0))
        left_edge = (SKY[0], SKY[1], SKY[0] + 30, SKY[3])
        assert _count(img, RED, left_edge) > 60

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

    def test_an_event_is_a_block_on_the_strip_at_its_time(self):
        evt = _event("Dentist", datetime(2026, 4, 7, 14), hours=2)
        axis = _axis()
        x0, x1 = int(axis.x(evt.start)), int(axis.x(evt.end))
        band = (x0 + 2, EVENTS_Y0, x1 - 2, EVENTS_Y0 + wh.STRIP_H)
        elsewhere = (x1 + 10, EVENTS_Y0, x1 + 60, EVENTS_Y0 + wh.STRIP_H)
        empty = _plate(DashboardData(), mode="L").convert("1")
        booked = _plate(DashboardData(events=[evt]), mode="L").convert("1")
        assert ink(booked, band) > ink(empty, band) + (x1 - x0 - 6) * (wh.STRIP_H - 1)
        assert ink(booked, elsewhere) == ink(empty, elsewhere)

    def test_back_to_back_events_stay_two_blocks(self):
        a = _event("A", datetime(2026, 4, 7, 10))
        b = _event("B", datetime(2026, 4, 7, 11))
        x = int(round(_axis().x(b.start)))
        seam = (x - 1, EVENTS_Y0, x + 1, EVENTS_Y0 + wh.STRIP_H - 1)
        img = _plate(DashboardData(events=[a, b]), mode="L").convert("1")
        assert ink(img, seam) < 2 * (wh.STRIP_H - 1)

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

    def test_native_pipeline_changes_nothing_but_the_ink_snap(self):
        """The plate is exact inks; the four-ink backend must leave it alone.

        The sky is deliberately not an art region: re-diffusing a tile of exact
        inks is not the identity (its neutral pass dithers the tile's
        luminance, which flips pixels beside red and yellow).
        """
        from src.render.quantize import quantize_to_palette_nearest

        tz = NY
        now = datetime(2026, 4, 6, 17, 30, tzinfo=tz)  # dusk in the window
        data = generate_dummy_data(tz=tz, now=now)
        data.fetched_at = now
        rendered = render_dashboard(
            data, NATIVE_G, theme=load_theme("wide_horizon"), latitude=40.7, longitude=-74.0
        )
        plate = Image.new("RGB", (1360, 480), "white")
        wh.draw_wide_horizon(
            ImageDraw.Draw(plate),
            data,
            now.date(),
            now,
            image=plate,
            region=REGION,
            latitude=40.7,
            longitude=-74.0,
        )
        snapped = quantize_to_palette_nearest(plate, list(WAVESHARE_G_PALETTE))
        assert image_hash(rendered.convert("RGB")) == image_hash(snapped)


class TestFonts:
    @pytest.mark.parametrize(
        "accessor",
        [
            fonts.big_shoulders_semibold,
            fonts.big_shoulders_extrabold,
            fonts.big_shoulders_black,
        ],
    )
    def test_loads_and_covers_the_glyphs_used(self, accessor):
        font = accessor(30)
        for ch in "0123456789°–·%ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert font.getmask(ch).getbbox() is not None, ch
