"""Tests for the day_arc theme and day_arc_panel component."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import Birthday, CalendarEvent, DashboardData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.day_arc_panel import (
    AXIS_MAX_HOUR,
    AXIS_MIN_HOUR,
    DAY_FRACTION,
    _next_birthdays,
    _resolve_day_bounds,
    _sky_marks,
    agenda_day,
    agenda_metrics,
    build_time_axis,
    draw_day_arc,
    event_state,
    sky_tone_at,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE, flatten_pixels
from src.render.skyart import bayer_screen, screened_paste
from src.render.theme import (
    AVAILABLE_THEMES,
    INKY_RED,
    INKY_YELLOW,
    ThemeStyle,
    load_theme,
)

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
TODAY = FIXED_NOW.date()
MIDNIGHT = datetime.combine(TODAY, datetime.min.time())

# A plausible spring day at ~40°N, used by the pure-function tests.
SUNRISE = MIDNIGHT + timedelta(hours=6, minutes=30)
SUNSET = MIDNIGHT + timedelta(hours=19, minutes=30)
CIVIL_DAWN = SUNRISE - timedelta(minutes=30)
CIVIL_DUSK = SUNSET + timedelta(minutes=30)

NYC = (40.7128, -74.006)


def _event(hour: int, minute: int = 0, *, mins: int = 45, name: str = "Meeting", **kw):
    start = MIDNIGHT + timedelta(hours=hour, minutes=minute)
    return CalendarEvent(summary=name, start=start, end=start + timedelta(minutes=mins), **kw)


def _axis(events=None, sunrise=SUNRISE, sunset=SUNSET, now=FIXED_NOW, x1=799):
    return build_time_axis(TODAY, now, events or [], sunrise, sunset, CIVIL_DAWN, CIVIL_DUSK, 0, x1)


def _render(**kwargs):
    data = kwargs.pop("data", None) or generate_dummy_data(now=FIXED_NOW)
    cfg = kwargs.pop("config", None) or DisplayConfig()
    kwargs.setdefault("latitude", NYC[0])
    kwargs.setdefault("longitude", NYC[1])
    return render_dashboard(data, cfg, theme=load_theme("day_arc"), **kwargs)


def _data_for(*, icon: str | None = "01d", events=None, weather: bool = True, now=FIXED_NOW):
    data = generate_dummy_data(now=now)
    if not weather:
        data.weather = None
    elif icon is not None and data.weather is not None:
        data.weather.current_icon = icon
    if events is not None:
        data.events = events
    return data


def _ink_count(img: Image.Image) -> int:
    return sum(1 for p in flatten_pixels(img) if p == 0)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestDayArcRegistration:
    def test_in_available_themes(self):
        assert "day_arc" in AVAILABLE_THEMES

    def test_load_theme(self):
        assert load_theme("day_arc").name == "day_arc"

    def test_region_visible_and_full_canvas(self):
        layout = load_theme("day_arc").layout
        assert layout.day_arc.visible is True
        assert (layout.day_arc.w, layout.day_arc.h) == (800, 480)

    def test_draw_order_only_day_arc(self):
        assert load_theme("day_arc").layout.draw_order == ["day_arc"]

    def test_standard_regions_hidden(self):
        layout = load_theme("day_arc").layout
        for name in ("header", "week_view", "weather", "birthdays", "info", "today_view"):
            assert getattr(layout, name).visible is False, name

    def test_greyscale_canvas_with_floyd_steinberg(self):
        layout = load_theme("day_arc").layout
        assert layout.canvas_mode == "L"
        assert layout.preferred_quantization_mode == "floyd_steinberg"

    def test_color_on_inky(self):
        assert load_theme("day_arc").layout.prefer_color_on_inky is True

    def test_light_canvas_invariant(self):
        # An "L"-mode light canvas must use bg=255; bg=1 is near-black there.
        style = load_theme("day_arc").style
        assert (style.fg, style.bg) == (0, 255)

    def test_inky_palette(self):
        from src.render.themes.registry import get_inky_palette

        assert get_inky_palette("day_arc") == (INKY_YELLOW, INKY_RED)
        assert load_theme("day_arc").style.inky_palette == (INKY_YELLOW, INKY_RED)

    def test_in_random_rotation_pool(self):
        from src.render.random_theme import eligible_themes

        assert "day_arc" in eligible_themes([], [])


# ---------------------------------------------------------------------------
# Time axis (pure)
# ---------------------------------------------------------------------------


class TestTimeAxis:
    def test_monotonic_across_the_day(self):
        axis = _axis()
        xs = [axis.x_for(MIDNIGHT + timedelta(minutes=15 * i)) for i in range(96)]
        assert xs == sorted(xs)

    def test_clamped_to_bounds(self):
        axis = _axis()
        assert axis.x_for(MIDNIGHT) == axis.x0
        assert axis.x_for(MIDNIGHT + timedelta(days=1)) == axis.x1
        assert all(
            axis.x0 <= axis.x_for(MIDNIGHT + timedelta(hours=h)) <= axis.x1 for h in range(25)
        )

    def test_sunrise_and_sunset_land_on_segment_joins(self):
        axis = _axis()
        assert axis.x_for(SUNRISE) == axis.x0 + axis.dawn_w
        assert axis.x_for(SUNSET) == axis.x0 + axis.dawn_w + axis.day_w

    def test_daylight_core_gets_the_configured_share(self):
        axis = _axis()
        assert axis.day_w == pytest.approx(axis.width * DAY_FRACTION, abs=axis.width * 0.02)

    def test_widths_sum_to_the_full_axis(self):
        axis = _axis()
        assert axis.dawn_w + axis.day_w + axis.dusk_w == axis.width

    def test_bounds_expand_to_cover_events(self):
        # A 21:00 dinner sits past sunset+1h; the axis must still reach it.
        axis = _axis(events=[_event(21, name="Dinner")])
        assert axis.end >= MIDNIGHT + timedelta(hours=21, minutes=45)
        assert axis.x_for(MIDNIGHT + timedelta(hours=21)) < axis.x1

    def test_bounds_never_leave_today(self):
        # An event running past midnight must not stretch the axis into tomorrow.
        long_event = CalendarEvent(
            summary="Red-eye",
            start=MIDNIGHT + timedelta(hours=22),
            end=MIDNIGHT + timedelta(hours=30),
        )
        axis = _axis(events=[long_event])
        assert axis.start >= MIDNIGHT + timedelta(hours=AXIS_MIN_HOUR)
        assert axis.end <= MIDNIGHT + timedelta(hours=AXIS_MAX_HOUR)

    def test_whole_week_of_events_does_not_stretch_the_axis(self):
        # Regression: passing unfiltered events once spread the axis over days.
        week = [
            CalendarEvent(
                summary="Far",
                start=MIDNIGHT + timedelta(days=d, hours=9),
                end=MIDNIGHT + timedelta(days=d, hours=10),
            )
            for d in (-3, 0, 4)
        ]
        axis = _axis(events=week)
        assert (axis.end - axis.start) <= timedelta(hours=AXIS_MAX_HOUR - AXIS_MIN_HOUR)

    def test_all_day_events_do_not_expand_bounds(self):
        all_day = CalendarEvent(
            summary="Conference",
            start=MIDNIGHT,
            end=MIDNIGHT + timedelta(days=1),
            is_all_day=True,
        )
        assert _axis(events=[all_day]).start == _axis().start

    def test_no_sun_data_falls_back_to_one_segment(self):
        axis = _axis(sunrise=None, sunset=None)
        assert (axis.dawn_w, axis.dusk_w) == (0, 0)
        assert axis.day_w == axis.width
        xs = [axis.x_for(MIDNIGHT + timedelta(hours=h)) for h in range(5, 23)]
        assert xs == sorted(xs)

    def test_sunset_before_sunrise_falls_back(self):
        axis = _axis(sunrise=SUNSET, sunset=SUNRISE)
        assert axis.day_w == axis.width

    def test_zero_width_axis_does_not_raise(self):
        axis = _axis(x1=0)
        assert axis.x_for(FIXED_NOW) == 0

    def test_polar_sunrise_outside_window_falls_back(self):
        # Sunrise at 02:00 sits before AXIS_MIN_HOUR, so the segmented map
        # can't apply; the axis degrades rather than producing a negative width.
        axis = _axis(sunrise=MIDNIGHT + timedelta(hours=2), sunset=MIDNIGHT + timedelta(hours=23))
        assert axis.dawn_w + axis.day_w + axis.dusk_w == axis.width


class TestResolveDayBounds:
    def test_prefers_computed_sun_times_when_located(self):
        data = _data_for()
        _, sunrise, sunset, _ = _resolve_day_bounds(TODAY, data.weather, *NYC, timezone.utc)
        assert sunrise is not None and sunset is not None
        # Computed, not the dummy feed's 06:24 / 19:51.
        assert (sunrise.hour, sunrise.minute) != (6, 24)

    def test_falls_back_to_weather_when_no_location(self):
        data = _data_for()
        _, sunrise, sunset, _ = _resolve_day_bounds(TODAY, data.weather, None, None, None)
        assert sunrise is not None and sunrise.hour == 6 and sunrise.minute == 24
        assert sunset is not None and sunset.hour == 19 and sunset.minute == 51

    def test_zero_zero_counts_as_unset(self):
        data = _data_for()
        _, sunrise, _, _ = _resolve_day_bounds(TODAY, data.weather, 0.0, 0.0, None)
        assert sunrise is not None and sunrise.hour == 6

    def test_all_none_without_weather_or_location(self):
        assert _resolve_day_bounds(TODAY, None, None, None, None) == (None, None, None, None)


# ---------------------------------------------------------------------------
# Sky tone (pure)
# ---------------------------------------------------------------------------


class TestSkyTone:
    def setup_method(self):
        self.marks = _sky_marks(_axis())

    def test_noon_is_brighter_than_dawn_and_midnight(self):
        _, x_sr, x_mid, _, _ = self.marks
        assert sky_tone_at(x_mid, self.marks) > sky_tone_at(x_sr, self.marks)
        assert sky_tone_at(x_sr, self.marks) > sky_tone_at(0, self.marks)

    def test_symmetric_about_solar_midpoint(self):
        _, x_sr, x_mid, x_ss, _ = self.marks
        assert sky_tone_at(x_sr + 5, self.marks) == pytest.approx(
            sky_tone_at(x_ss - 5, self.marks), abs=3
        )

    def test_storm_darkens_the_peak_but_not_below_night(self):
        _, _, x_mid, _, _ = self.marks
        clear = sky_tone_at(x_mid, self.marks)
        stormy = sky_tone_at(x_mid, self.marks, storm=True)
        assert stormy < clear
        assert stormy > sky_tone_at(0, self.marks)

    def test_night_dims_every_sample_but_keeps_the_arc(self):
        xs = [0, self.marks[1], self.marks[2], self.marks[3], 799]
        day = [sky_tone_at(x, self.marks) for x in xs]
        night = [sky_tone_at(x, self.marks, night=True) for x in xs]
        assert all(n <= d for n, d in zip(night, day))
        assert night[2] > night[0]  # the arc survives the dimming

    def test_all_values_in_range(self):
        assert all(0 <= sky_tone_at(x, self.marks) <= 255 for x in range(0, 800, 7))


# ---------------------------------------------------------------------------
# Event state + rollover (pure)
# ---------------------------------------------------------------------------


class TestEventState:
    def test_past_now_next(self):
        assert event_state(_event(8), FIXED_NOW) == "past"
        assert event_state(_event(10, 15), FIXED_NOW) == "now"
        assert event_state(_event(14), FIXED_NOW) == "next"

    def test_boundaries(self):
        # end == now is over; start == now has begun.
        assert event_state(_event(9, 45, mins=45), FIXED_NOW) == "past"
        assert event_state(_event(10, 30), FIXED_NOW) == "now"

    def test_all_day_is_never_past_or_now(self):
        all_day = CalendarEvent(
            summary="Conference",
            start=MIDNIGHT,
            end=MIDNIGHT + timedelta(days=1),
            is_all_day=True,
        )
        assert event_state(all_day, FIXED_NOW) == "next"

    def test_aware_event_times_are_handled(self):
        aware = CalendarEvent(
            summary="Tz",
            start=(MIDNIGHT + timedelta(hours=8)).replace(tzinfo=timezone.utc),
            end=(MIDNIGHT + timedelta(hours=9)).replace(tzinfo=timezone.utc),
        )
        assert event_state(aware, FIXED_NOW) == "past"


class TestAgendaDay:
    def test_midday_stays_on_today_even_when_all_events_ended(self):
        assert agenda_day([_event(8)], TODAY, FIXED_NOW, SUNSET) == (TODAY, False)

    def test_rolls_over_after_sunset_when_everything_ended(self):
        evening = MIDNIGHT + timedelta(hours=21)
        day, is_tomorrow = agenda_day([_event(8)], TODAY, evening, SUNSET)
        assert (day, is_tomorrow) == (TODAY + timedelta(days=1), True)

    def test_stays_on_today_while_an_evening_event_runs(self):
        evening = MIDNIGHT + timedelta(hours=20)
        assert agenda_day([_event(19, 30, mins=90)], TODAY, evening, SUNSET) == (TODAY, False)

    def test_empty_day_rolls_over_after_sunset(self):
        evening = MIDNIGHT + timedelta(hours=21)
        assert agenda_day([], TODAY, evening, SUNSET)[1] is True

    def test_empty_day_before_sunset_stays(self):
        assert agenda_day([], TODAY, FIXED_NOW, SUNSET) == (TODAY, False)

    def test_all_day_events_do_not_block_rollover(self):
        all_day = CalendarEvent(
            summary="Conference",
            start=MIDNIGHT,
            end=MIDNIGHT + timedelta(days=1),
            is_all_day=True,
        )
        evening = MIDNIGHT + timedelta(hours=21)
        assert agenda_day([all_day], TODAY, evening, SUNSET)[1] is True

    def test_no_sunset_uses_the_fallback_hour(self):
        assert agenda_day([_event(8)], TODAY, MIDNIGHT + timedelta(hours=17), None) == (
            TODAY,
            False,
        )
        assert agenda_day([_event(8)], TODAY, MIDNIGHT + timedelta(hours=19), None)[1] is True


class TestAgendaMetrics:
    # The agenda region is ~196 px tall once the header and rule are taken out.
    AVAIL = 196

    @pytest.mark.parametrize("n", [1, 3, 4, 6, 7, 12, 40])
    def test_every_tier_fits_the_region(self, n):
        max_rows, row_h, *_ = agenda_metrics(n, self.AVAIL)
        assert max_rows * row_h <= self.AVAIL

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7])
    def test_days_that_fit_are_shown_whole(self, n):
        # Regression: a tier whose rows overran the region collapsed a 3-event
        # day down to a single row plus "+2 more".
        max_rows, row_h, *_ = agenda_metrics(n, self.AVAIL)
        assert min(max_rows, self.AVAIL // row_h) >= n

    def test_density_increases_with_event_count(self):
        assert agenda_metrics(2, self.AVAIL)[4] > agenda_metrics(12, self.AVAIL)[4]  # title pt
        assert agenda_metrics(2, self.AVAIL)[1] > agenda_metrics(12, self.AVAIL)[1]  # row height

    def test_large_counts_use_the_densest_tier(self):
        assert agenda_metrics(99, self.AVAIL) == agenda_metrics(30, self.AVAIL)

    def test_a_cramped_region_falls_through_to_the_densest_tier(self):
        assert agenda_metrics(3, 40) == agenda_metrics(99, self.AVAIL)


class TestNextBirthdays:
    def test_sorted_soonest_first_and_capped(self):
        people = [
            Birthday(name="Far", date=TODAY + timedelta(days=200)),
            Birthday(name="Soon", date=TODAY + timedelta(days=2)),
            Birthday(name="Mid", date=TODAY + timedelta(days=40)),
            Birthday(name="Extra", date=TODAY + timedelta(days=50)),
        ]
        out = _next_birthdays(people, TODAY, limit=3)
        assert [name for name, _ in out] == ["Soon", "Mid", "Extra"]

    def test_past_birthday_rolls_to_next_year(self):
        [(_, days)] = _next_birthdays([Birthday(name="Past", date=date(1990, 1, 1))], TODAY)
        assert days > 0

    def test_leap_day_birthday_does_not_crash(self):
        # 2026 is not a leap year; Feb 29 must roll to Feb 28.
        out = _next_birthdays([Birthday(name="Leap", date=date(2000, 2, 29))], TODAY)
        assert len(out) == 1

    def test_age_is_included_in_the_label(self):
        [(label, _)] = _next_birthdays(
            [Birthday(name="Jake", date=TODAY + timedelta(days=3), age=30)], TODAY
        )
        assert "30" in label


# ---------------------------------------------------------------------------
# Bayer screening helpers
# ---------------------------------------------------------------------------


class TestBayerScreen:
    def test_threshold_controls_ink_density(self):
        light = bayer_screen(64, 64, 0, 0, 64)
        heavy = bayer_screen(64, 64, 0, 0, 192)
        assert sum(flatten_pixels(heavy)) > sum(flatten_pixels(light))

    def test_zero_threshold_passes_nothing(self):
        assert set(flatten_pixels(bayer_screen(16, 16, 0, 0, 0))) == {0}

    def test_phase_locked_to_canvas_coordinates(self):
        assert list(flatten_pixels(bayer_screen(16, 16, 0, 0, 128))) != list(
            flatten_pixels(bayer_screen(16, 16, 1, 0, 128))
        )
        # A 4-px shift is a whole lattice period, so it repeats.
        assert list(flatten_pixels(bayer_screen(16, 16, 0, 0, 128))) == list(
            flatten_pixels(bayer_screen(16, 16, 4, 0, 128))
        )

    def test_screened_paste_leaves_paper_untouched(self):
        img = Image.new("L", (60, 30), 255)
        screened_paste(img, (5, 5, 40, 20), lambda d: d.rectangle((0, 0, 39, 19), fill=0))
        # Outside the box nothing was drawn.
        assert img.getpixel((1, 1)) == 255
        # Inside, some ink landed but not all of it.
        vals = [img.getpixel((x, y)) for x in range(5, 45) for y in range(5, 25)]
        assert 0 in vals and 255 in vals

    def test_screened_paste_emits_only_pure_values(self):
        # Pure 0/255 is what lets Floyd-Steinberg pass the region through
        # untouched and keeps the Inky palette mapping unambiguous.
        img = Image.new("L", (40, 20), 255)
        screened_paste(img, (0, 0, 40, 20), lambda d: d.text((0, 0), "Hello", fill=0))
        assert set(flatten_pixels(img)) <= {0, 255}

    def test_screened_paste_works_on_rgb(self):
        img = Image.new("RGB", (40, 20), (255, 255, 255))
        screened_paste(img, (0, 0, 40, 20), lambda d: d.rectangle((0, 0, 39, 19), fill=0))
        assert (0, 0, 0) in flatten_pixels(img)

    @pytest.mark.parametrize("box", [(0, 0, 0, 10), (0, 0, 10, 0), (0, 0, -5, -5)])
    def test_degenerate_boxes_are_no_ops(self, box):
        img = Image.new("L", (20, 20), 255)
        screened_paste(img, box, lambda d: d.rectangle((0, 0, 19, 19), fill=0))
        assert set(flatten_pixels(img)) == {255}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRenderEachIcon:
    @pytest.mark.parametrize(
        "icon",
        [
            "01d",
            "01n",
            "02d",
            "02n",
            "03d",
            "04d",
            "09d",
            "10d",
            "10n",
            "11d",
            "13d",
            "50d",
            None,
            "zz9",
        ],
    )
    def test_renders_without_crashing(self, icon):
        img = _render(data=_data_for(icon=icon))
        assert img.mode == "1"
        assert img.size == (800, 480)
        assert _ink_count(img) > 1000


class TestRenderStates:
    def test_empty_day(self):
        img = _render(data=_data_for(events=[]))
        assert _ink_count(img) > 1000

    def test_busy_day_overflows_gracefully(self):
        events = [_event(8 + i, name=f"Event {i}") for i in range(12)]
        assert _ink_count(_render(data=_data_for(events=events))) > 1000

    def test_all_day_event(self):
        all_day = CalendarEvent(
            summary="Conference",
            start=MIDNIGHT,
            end=MIDNIGHT + timedelta(days=1),
            is_all_day=True,
        )
        assert _ink_count(_render(data=_data_for(events=[all_day, _event(14)]))) > 1000

    def test_event_with_location(self):
        ev = _event(14, name="Standup", location="Conference Room B, Floor 3")
        assert _ink_count(_render(data=_data_for(events=[ev]))) > 1000

    def test_no_weather_still_renders(self):
        # Unlike halftone, the ribbon's subject is time, not weather — it must
        # still draw a full plate with the weather source missing.
        assert _ink_count(_render(data=_data_for(weather=False))) > 1000

    def test_no_location_falls_back_to_weather_sun_times(self):
        img = _render(data=_data_for(), latitude=None, longitude=None)
        assert _ink_count(img) > 1000

    def test_no_birthdays(self):
        data = _data_for()
        data.birthdays = []
        assert _ink_count(_render(data=data)) > 1000

    def test_empty_dashboard_data(self):
        assert _ink_count(_render(data=DashboardData(fetched_at=FIXED_NOW))) > 1000

    def test_night_rollover_renders(self):
        night = datetime(2026, 4, 6, 22, 30)
        img = _render(data=_data_for(icon="01n", events=[_event(8)], now=night))
        assert _ink_count(img) > 1000


class TestRenderInkyPath:
    def _inky(self, **kw):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        return _render(config=cfg, **kw)

    def test_renders_rgb(self):
        img = self._inky(data=_data_for())
        assert img.mode == "RGB"
        assert img.size == (800, 480)

    def test_uses_the_registered_palette(self):
        pixels = set(flatten_pixels(self._inky(data=_data_for())))
        assert INKY_SPECTRA6_PALETTE[INKY_YELLOW] in pixels  # sun ring / daylight bar
        assert INKY_SPECTRA6_PALETTE[INKY_RED] in pixels  # NOW caret

    def test_night_path_renders(self):
        night = datetime(2026, 4, 6, 22, 30)
        assert self._inky(data=_data_for(icon="01n", now=night)).mode == "RGB"


class TestDeterminism:
    def test_two_renders_are_byte_identical(self):
        # Star fields and jitter are seeded from today.toordinal(); an unseeded
        # RNG here would make the theme's pixel snapshot flap.
        first = _render(data=_data_for(icon="01n"))
        second = _render(data=_data_for(icon="01n"))
        assert first.tobytes() == second.tobytes()


class TestInkCoverage:
    def test_ribbon_band_has_ink_in_every_column(self):
        img = _render(data=_data_for(icon="01d"))
        px = img.convert("L").load()
        for x in range(0, 800, 20):
            assert any(px[x, y] == 0 for y in range(0, 168)), f"no ink in ribbon column {x}"

    def test_agenda_band_is_neither_blank_nor_solid(self):
        img = _render(data=_data_for(events=[_event(9), _event(14)]))
        band = img.convert("L").crop((0, 240, 548, 450))
        vals = set(flatten_pixels(band))
        assert 0 in vals and 255 in vals

    def test_past_events_carry_less_ink_than_upcoming_ones(self):
        # The Bayer screen is the theme's way of saying "this already happened";
        # if the two treatments rendered alike the encoding would be invisible.
        past = _render(data=_data_for(events=[_event(8, name="Aaaaaaaaaaaa")]))
        future = _render(data=_data_for(events=[_event(15, name="Aaaaaaaaaaaa")]))
        band = (0, 240, 548, 330)
        assert _ink_count(past.convert("L").crop(band)) < _ink_count(future.convert("L").crop(band))


# ---------------------------------------------------------------------------
# Defensive entry-point behaviour
# ---------------------------------------------------------------------------


def test_draw_day_arc_default_style_does_not_crash():
    # No region, no style, and no image kwarg — the panel falls back to the
    # draw handle's backing image.
    image = Image.new("L", (800, 480), 255)
    draw_day_arc(ImageDraw.Draw(image), _data_for(), TODAY, FIXED_NOW)
    assert image.getbbox() is not None


def test_draw_day_arc_accepts_an_explicit_style():
    image = Image.new("L", (800, 480), 255)
    draw_day_arc(
        ImageDraw.Draw(image),
        _data_for(),
        TODAY,
        FIXED_NOW,
        image=image,
        style=ThemeStyle(fg=0, bg=255),
        latitude=NYC[0],
        longitude=NYC[1],
    )
    assert image.getbbox() is not None


def test_draw_day_arc_with_aware_now():
    # Production passes an aware ``now``; sun times must convert into its zone
    # rather than against the host machine's.
    image = Image.new("L", (800, 480), 255)
    aware = FIXED_NOW.replace(tzinfo=timezone.utc)
    draw_day_arc(ImageDraw.Draw(image), _data_for(), TODAY, aware, image=image)
    assert image.getbbox() is not None
