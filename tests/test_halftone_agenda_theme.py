"""Tests for the halftone_agenda theme and halftone_agenda_panel component."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.data.models import CalendarEvent, DashboardData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.halftone_agenda_panel import (
    _DENSITY_TIERS,
    AGENDA_PAD_X,
    AGENDA_X,
    ART_W,
    BAND_Y,
    COND_PT,
    DIVIDER_W,
    FOOTER_H,
    HERO_H,
    HIGH_LOW_PT,
    RULE_H,
    SCENE_SCALE,
    TEMP_COL_W,
    TEMP_PT,
    _clock,
    _draw_time_cell,
    _fmt_temp,
    _location_text,
    _sun_times,
    agenda_metrics,
    compact_range,
    draw_halftone_agenda,
    event_times,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE, flatten_pixels
from src.render.skyart import (
    TYPESET_CUT,
    draw_bayer_rule,
    draw_weather_scene,
    harden_typeset,
)
from src.render.theme import (
    AVAILABLE_THEMES,
    INKY_RED,
    INKY_YELLOW,
    ComponentRegion,
    ThemeStyle,
    load_theme,
)

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
TODAY = FIXED_NOW.date()
MIDNIGHT = datetime.combine(TODAY, datetime.min.time())


def _event(hour: int, minute: int = 0, *, mins: int = 45, name: str = "Meeting", **kw):
    start = MIDNIGHT + timedelta(hours=hour, minutes=minute)
    return CalendarEvent(summary=name, start=start, end=start + timedelta(minutes=mins), **kw)


def _data_for(*, icon: str | None = "01d", events=None, weather: bool = True, now=FIXED_NOW):
    data = generate_dummy_data(now=now)
    if not weather:
        data.weather = None
    elif icon is not None and data.weather is not None:
        data.weather.current_icon = icon
    if events is not None:
        data.events = events
    return data


def _render(**kwargs):
    data = kwargs.pop("data", None) or generate_dummy_data(now=FIXED_NOW)
    cfg = kwargs.pop("config", None) or DisplayConfig()
    return render_dashboard(data, cfg, theme=load_theme("halftone_agenda"), **kwargs)


def _ink_count(img: Image.Image) -> int:
    return sum(1 for p in flatten_pixels(img) if p == 0)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestHalftoneAgendaRegistration:
    def test_in_available_themes(self):
        assert "halftone_agenda" in AVAILABLE_THEMES

    def test_load_theme(self):
        assert load_theme("halftone_agenda").name == "halftone_agenda"

    def test_region_visible_and_full_canvas(self):
        layout = load_theme("halftone_agenda").layout
        assert layout.halftone_agenda.visible is True
        assert (layout.halftone_agenda.w, layout.halftone_agenda.h) == (800, 480)

    def test_draw_order_only_halftone_agenda(self):
        assert load_theme("halftone_agenda").layout.draw_order == ["halftone_agenda"]

    def test_standard_regions_hidden(self):
        layout = load_theme("halftone_agenda").layout
        for name in ("header", "week_view", "weather", "birthdays", "info", "today_view"):
            assert getattr(layout, name).visible is False, name

    def test_greyscale_canvas_with_floyd_steinberg(self):
        layout = load_theme("halftone_agenda").layout
        assert layout.canvas_mode == "L"
        assert layout.preferred_quantization_mode == "floyd_steinberg"

    def test_color_on_inky(self):
        assert load_theme("halftone_agenda").layout.prefer_color_on_inky is True

    def test_light_canvas_invariant(self):
        # An "L"-mode light canvas must use bg=255; bg=1 is near-black there.
        style = load_theme("halftone_agenda").style
        assert (style.fg, style.bg) == (0, 255)

    def test_inky_palette(self):
        from src.render.themes.registry import get_inky_palette

        assert get_inky_palette("halftone_agenda") == (INKY_YELLOW, INKY_RED)
        assert load_theme("halftone_agenda").style.inky_palette == (INKY_YELLOW, INKY_RED)

    def test_in_random_rotation_pool(self):
        from src.render.random_theme import eligible_themes

        assert "halftone_agenda" in eligible_themes([], [])

    def test_does_not_disturb_halftone(self):
        # The variant shares halftone's scene composer; the parent theme must
        # keep its own registration, palette and layout untouched.
        halftone = load_theme("halftone")
        assert halftone.layout.draw_order == ["halftone"]
        assert halftone.layout.halftone_agenda.visible is False


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class TestGeometry:
    def test_panes_tile_the_canvas(self):
        assert AGENDA_X == ART_W + DIVIDER_W
        assert AGENDA_X < 800

    def test_band_sits_below_the_hero_and_its_rule(self):
        assert BAND_Y == HERO_H + RULE_H
        assert BAND_Y < 480

    def test_scene_scale_is_between_width_ratio_and_full(self):
        # Below the width ratio the illustration would strand a small disc in a
        # tall pane; at 1.0 the assemblies would run off the plate.
        assert ART_W / 800 < SCENE_SCALE < 1.0

    def test_density_tiers_shrink_monotonically(self):
        rows = [t[0] for t in _DENSITY_TIERS]
        heights = [t[1] for t in _DENSITY_TIERS]
        titles = [t[4] for t in _DENSITY_TIERS]
        assert rows == sorted(rows)
        assert heights == sorted(heights, reverse=True)
        assert titles == sorted(titles, reverse=True)

    def test_every_tier_fits_the_pane(self):
        # Each tier must be able to set its nominal row count in the height the
        # pane actually offers, or the tier can never be chosen for that count.
        avail = 480 - 14 - FOOTER_H - 60  # pane height minus header + footer
        for max_rows, row_h, *_ in _DENSITY_TIERS:
            assert max_rows * row_h <= avail + row_h, (max_rows, row_h)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_fmt_temp_rounds(self):
        assert _fmt_temp(41.6) == "42°"

    def test_fmt_temp_none(self):
        assert _fmt_temp(None) == "—"

    def test_clock_strips_leading_zero(self):
        assert _clock(datetime(2026, 4, 6, 6, 24)) == "6:24 AM"
        assert _clock(datetime(2026, 4, 6, 19, 51)) == "7:51 PM"

    def test_location_takes_first_segment(self):
        event = _event(9, location="Conference Room B, Floor 3, HQ")
        assert _location_text(event) == "Conference Room B"

    def test_location_empty_when_absent(self):
        assert _location_text(_event(9)) == ""

    def test_sun_times_none_without_weather(self):
        assert _sun_times(None, None) == (None, None)

    def test_sun_times_are_naive_local(self):
        # OWM hands back aware datetimes while events are naive local; mixing
        # the two blows up the rollover comparison in agenda_day.
        data = generate_dummy_data(now=FIXED_NOW)
        assert data.weather is not None
        data.weather.sunrise = datetime(2026, 4, 6, 10, 24, tzinfo=timezone.utc)
        data.weather.sunset = datetime(2026, 4, 6, 23, 51, tzinfo=timezone.utc)
        rise, down = _sun_times(data.weather, timezone.utc)
        assert rise is not None and rise.tzinfo is None
        assert down is not None and down.tzinfo is None

    def test_sun_times_handles_missing_pair(self):
        data = generate_dummy_data(now=FIXED_NOW)
        assert data.weather is not None
        data.weather.sunrise = None
        data.weather.sunset = None
        assert _sun_times(data.weather, None) == (None, None)


class TestAgendaMetrics:
    def test_few_events_get_the_roomiest_tier(self):
        assert agenda_metrics(1, 400) == _DENSITY_TIERS[0]

    def test_tier_steps_down_as_events_grow(self):
        picked = [agenda_metrics(n, 400)[1] for n in (1, 3, 5, 7, 10)]
        assert picked == sorted(picked, reverse=True)

    def test_capacity_is_measured_against_real_height(self):
        # A tier whose rows overrun the space available must not be chosen,
        # even when its nominal max_rows would cover the event count.
        tier = agenda_metrics(2, 60)
        assert tier[1] <= 60

    def test_impossible_counts_fall_back_to_the_densest_tier(self):
        assert agenda_metrics(99, 400) == _DENSITY_TIERS[-1]


# ---------------------------------------------------------------------------
# Scene composer (shared with halftone)
# ---------------------------------------------------------------------------


class TestWeatherScene:
    def test_paints_the_whole_rect(self):
        img = Image.new("L", (372, 292), 255)
        draw_weather_scene(img, (0, 0, 372, 292), "01d", TODAY, scale=SCENE_SCALE)
        px = img.load()
        assert any(px[x, y] != 255 for x in range(0, 372, 8) for y in range(0, 292, 8))

    def test_stays_inside_the_rect(self):
        # The composer is handed a sub-rect; nothing may leak outside of it.
        img = Image.new("L", (500, 400), 255)
        draw_weather_scene(img, (50, 40, 422, 332), "04d", TODAY, scale=SCENE_SCALE)
        px = img.load()
        assert all(px[x, 10] == 255 for x in range(500))
        assert all(px[10, y] == 255 for y in range(400))
        assert all(px[x, 390] == 255 for x in range(500))

    @pytest.mark.parametrize(
        "icon", ["01d", "01n", "02d", "02n", "03d", "04d", "09d", "10n", "11d", "13d", "50d", None]
    )
    def test_every_kind_draws_at_reduced_scale(self, icon):
        img = Image.new("L", (372, 292), 255)
        draw_weather_scene(img, (0, 0, 372, 292), icon, TODAY, scale=SCENE_SCALE)
        assert sum(1 for p in flatten_pixels(img) if p != 255) > 5000

    def test_rgb_canvas_does_not_crash(self):
        img = Image.new("RGB", (372, 292), (255, 255, 255))
        draw_weather_scene(img, (0, 0, 372, 292), "01n", TODAY, scale=SCENE_SCALE)
        assert any(p != (255, 255, 255) for p in flatten_pixels(img))

    def test_scale_changes_element_size(self):
        small = Image.new("L", (372, 292), 255)
        large = Image.new("L", (372, 292), 255)
        draw_weather_scene(small, (0, 0, 372, 292), "01d", TODAY, scale=0.4)
        draw_weather_scene(large, (0, 0, 372, 292), "01d", TODAY, scale=0.9)
        # The sun disc is the brightest element; a larger scale paints more of it.
        assert sum(1 for p in flatten_pixels(large) if p > 240) > sum(
            1 for p in flatten_pixels(small) if p > 240
        )


class TestVerticalBayerRule:
    def test_vertical_rule_draws_side_hairlines(self):
        img = Image.new("L", (20, 40), 255)
        draw_bayer_rule(img, 5, 0, 6, 40, "L", orientation="vertical")
        px = img.load()
        assert all(px[5, y] == 0 for y in range(40))
        assert all(px[10, y] == 0 for y in range(40))

    def test_horizontal_rule_is_unchanged_by_the_new_keyword(self):
        explicit = Image.new("L", (40, 8), 255)
        implicit = Image.new("L", (40, 8), 255)
        draw_bayer_rule(explicit, 0, 0, 40, 8, "L", orientation="horizontal")
        draw_bayer_rule(implicit, 0, 0, 40, 8, "L")
        assert explicit.tobytes() == implicit.tobytes()

    def test_vertical_rule_leaves_its_neighbours_alone(self):
        img = Image.new("L", (20, 40), 255)
        draw_bayer_rule(img, 5, 0, 6, 40, "L", orientation="vertical")
        px = img.load()
        assert all(px[4, y] == 255 for y in range(40))
        assert all(px[11, y] == 255 for y in range(40))


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
        assert _ink_count(_render(data=_data_for(events=[]))) > 1000

    def test_busy_day_overflows_gracefully(self):
        events = [_event(7 + i, name=f"Event {i}") for i in range(14)]
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
        event = _event(14, name="Standup", location="Conference Room B, Floor 3")
        assert _ink_count(_render(data=_data_for(events=[event]))) > 1000

    def test_event_in_progress(self):
        # The inverted "now" bar is the one solid field on the plate.
        event = _event(10, minute=0, mins=120, name="All hands")
        assert _ink_count(_render(data=_data_for(events=[event]))) > 1000

    def test_no_weather_still_renders(self):
        assert _ink_count(_render(data=_data_for(weather=False))) > 1000

    def test_missing_sun_times_still_render(self):
        data = _data_for()
        assert data.weather is not None
        data.weather.sunrise = None
        data.weather.sunset = None
        assert _ink_count(_render(data=data)) > 1000

    def test_three_digit_temperature_keeps_the_condition_column(self):
        data = _data_for()
        assert data.weather is not None
        data.weather.current_temp = 108.4
        data.weather.current_description = "heavy intensity rain"
        assert _ink_count(_render(data=data)) > 1000

    def test_empty_dashboard_data(self):
        assert _ink_count(_render(data=DashboardData(fetched_at=FIXED_NOW))) > 1000

    def test_night_rollover_renders(self):
        night = datetime(2026, 4, 6, 22, 30)
        img = _render(data=_data_for(icon="01n", events=[_event(8)], now=night))
        assert _ink_count(img) > 1000

    def test_aware_now_does_not_raise(self):
        # RenderContext.now is aware; event and sun times are naive local.
        aware = FIXED_NOW.replace(tzinfo=timezone.utc)
        data = _data_for(events=[_event(9), _event(15)], now=FIXED_NOW)
        data.fetched_at = aware
        assert _ink_count(_render(data=data)) > 1000


class TestRenderInkyPath:
    def _inky(self, **kw):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        return _render(config=cfg, **kw)

    def test_renders_rgb(self):
        img = self._inky(data=_data_for())
        assert img.mode == "RGB"
        assert img.size == (800, 480)

    def test_yellow_rings_the_sun(self):
        data = _data_for(events=[_event(10, minute=0, mins=120, name="All hands")])
        pixels = set(flatten_pixels(self._inky(data=data)))
        assert INKY_SPECTRA6_PALETTE[INKY_YELLOW] in pixels

    def test_the_calendar_side_carries_no_colour(self):
        # The colour story lives entirely in the art pane now: dropping the
        # state treatments took the only red mark off the agenda with them.
        # The Inky backend defers palette mapping to the device, so the pane
        # still holds greys here — what matters is that none of them is a hue.
        data = _data_for(events=[_event(10, minute=0, mins=120, name="All hands")])
        pane = self._inky(data=data).crop((AGENDA_X + DIVIDER_W, 0, 800, 480))
        hues = {p for p in flatten_pixels(pane) if len(set(p)) > 1}
        assert not hues, f"unexpected colour on the calendar side: {sorted(hues)[:4]}"

    def test_night_path_renders(self):
        night = datetime(2026, 4, 6, 22, 30)
        assert self._inky(data=_data_for(icon="01n", now=night)).mode == "RGB"


class TestPaneSeparation:
    def _plate(self, **kw):
        return _render(**kw).convert("L")

    def test_divider_column_is_inked_top_to_bottom(self):
        px = self._plate(data=_data_for(events=[])).load()
        assert all(px[ART_W, y] == 0 for y in range(480))
        assert all(px[ART_W + DIVIDER_W - 1, y] == 0 for y in range(480))

    def test_agenda_pane_stays_paper_white_beside_the_divider(self):
        # The dithered illustration must never bleed across the divider: the
        # gutter between it and the agenda's left margin stays pure paper.
        px = self._plate(data=_data_for(icon="01d", events=[])).load()
        for x in range(AGENDA_X, AGENDA_X + AGENDA_PAD_X - 2):
            assert all(px[x, y] == 255 for y in range(480)), f"ink in the gutter at x={x}"

    def test_weather_band_sits_on_clean_paper(self):
        px = self._plate(data=_data_for(icon="11d")).load()
        # The row just under the hero's Bayer rule belongs to the band, and the
        # band paints its own paper — a storm sky above it must not carry over.
        assert all(px[x, BAND_Y + 1] == 255 for x in range(2, ART_W - 2))

    def test_agenda_footer_caption_is_drawn(self):
        px = self._plate(data=_data_for(events=[])).load()
        footer_band = [
            (x, y)
            for x in range(AGENDA_X + AGENDA_PAD_X, 800 - AGENDA_PAD_X)
            for y in range(480 - FOOTER_H, 480)
        ]
        assert any(px[x, y] == 0 for x, y in footer_band)


class TestWeatherBandType:
    """The band's display type is sized to the room it actually has."""

    def _probe(self):
        from PIL import ImageDraw

        return ImageDraw.Draw(Image.new("L", (10, 10)))

    def test_three_digit_temperature_fits_its_column(self):
        # The column is a fixed reservation so the condition stack keeps its
        # width whatever the reading is; a numeral wider than it would push
        # into that stack.
        style = load_theme("halftone_agenda").style
        box = self._probe().textbbox((0, 0), "108°", font=style.font_title(TEMP_PT))
        assert box[2] - box[0] <= TEMP_COL_W

    def test_widest_condition_still_wraps_to_two_lines(self):
        # 19 pt is the largest size at which the widest OWM phrase breaks as
        # "HEAVY INTENSITY / RAIN"; past it the band needs a third line.
        from src.render.components.halftone_agenda_panel import ART_PAD_X, TEMP_COL_GAP
        from src.render.primitives import wrap_lines

        style = load_theme("halftone_agenda").style
        stack_w = (ART_W - ART_PAD_X) - (ART_PAD_X + TEMP_COL_W + TEMP_COL_GAP)
        wrapped = wrap_lines("HEAVY INTENSITY RAIN", style.font_section_label(COND_PT), stack_w)
        assert len(wrapped) <= 2, wrapped

    def test_high_low_fits_beside_the_numeral(self):
        from src.render.components.halftone_agenda_panel import ART_PAD_X, TEMP_COL_GAP

        style = load_theme("halftone_agenda").style
        stack_w = (ART_W - ART_PAD_X) - (ART_PAD_X + TEMP_COL_W + TEMP_COL_GAP)
        box = self._probe().textbbox(
            (0, 0), "H 108° · L 100°", font=style.font_semibold(HIGH_LOW_PT)
        )
        assert box[2] - box[0] <= stack_w

    def test_overlong_condition_is_ellipsized_not_silently_cut(self):
        # "thunderstorm with light drizzle" wraps to three lines; folding the
        # overflow into line two lets it ellipsize, so it reads as cut off
        # rather than as a complete but wrong "THUNDERSTORM WITH LIGHT".
        data = _data_for()
        assert data.weather is not None
        data.weather.current_description = "thunderstorm with light drizzle"
        band = _render(data=data).convert("L").crop((0, BAND_Y, ART_W, 480))
        with_long = _ink_count(band)
        data.weather.current_description = "thunderstorm with light"
        band = _render(data=data).convert("L").crop((0, BAND_Y, ART_W, 480))
        # The ellipsized version must differ from the phrase it would otherwise
        # be mistaken for.
        assert with_long != _ink_count(band)


class TestEventTimes:
    """Rows show when an event ends, not just when it starts."""

    def test_compact_range_elides_a_shared_meridiem(self):
        assert compact_range("12:30p", "2p") == "12:30–2p"
        assert compact_range("8a", "8:45a") == "8–8:45a"

    def test_compact_range_keeps_both_across_the_meridiem(self):
        assert compact_range("11:30a", "1:15p") == "11:30a–1:15p"

    def test_all_day_has_no_range(self):
        event = _event(0, name="Conference", is_all_day=True)
        assert event_times(event) == ("ALL DAY", None)

    def test_timed_event_gives_both_ends(self):
        start, end = event_times(_event(12, minute=30, mins=90))
        assert (start, end) == ("12:30p", "2p")

    def test_event_running_past_midnight_shows_only_its_start(self):
        # A range that reads as ending before it starts is worse than no range.
        event = _event(23, mins=120, name="Night shift")
        assert event_times(event) == ("11p", None)

    def test_zero_length_event_shows_only_its_start(self):
        assert event_times(_event(9, mins=0))[1] is None

    def test_every_tier_can_show_an_end_time(self):
        """Each tier fits the widest range on one line, or can wrap it.

        The worst case is a range that crosses the meridiem with minutes on
        both sides. A tier that satisfies neither branch would silently drop
        the end time for those events.
        """
        from PIL import ImageDraw

        from src.render.fonts import dm_semibold

        probe = ImageDraw.Draw(Image.new("L", (10, 10)))
        worst = compact_range("11:30a", "1:15p")
        for _rows, row_h, time_w, time_pt, _title_pt, _loc in _DENSITY_TIERS:
            box = probe.textbbox((0, 0), worst, font=dm_semibold(time_pt))
            one_line = (box[2] - box[0]) <= time_w - 4
            end_pt = max(11, time_pt - 3)
            two_line = time_pt + end_pt + 3 <= row_h - 8
            assert one_line or two_line, (
                f"tier {time_pt}pt/{row_h}px can neither fit nor wrap {worst!r}"
            )

    def test_time_cell_never_overflows_its_column(self):
        # The column is what separates the time from the tick; ink past it
        # would collide with the rule between the two.
        from PIL import ImageDraw

        style = load_theme("halftone_agenda").style
        for _rows, row_h, time_w, time_pt, _title_pt, _loc in _DENSITY_TIERS:
            tile = Image.new("L", (time_w + 60, row_h), 255)
            draw = ImageDraw.Draw(tile)
            _draw_time_cell(
                draw,
                "11:30a",
                "1:15p",
                style,
                x0=0,
                y=0,
                time_w=time_w,
                time_pt=time_pt,
                row_h=row_h,
                fill=0,
            )
            px = tile.load()
            overflow = [
                (x, y) for y in range(row_h) for x in range(time_w, time_w + 60) if px[x, y] == 0
            ]
            assert not overflow, f"tier {time_pt}pt spills past its {time_w}px column"


class TestAgendaRowTreatment:
    """The pane is a plain list: no state is encoded in the rendering.

    It used to invert the in-progress event into a solid bar, perforate
    elapsed rows on a Bayer lattice and accent the next one up. All three
    depended on large or dithered areas of ink surviving the panel, which they
    do not under partial refresh — Waveshare's fast waveform leaves a filled
    bar reading as charcoal and a screened row as mud.
    """

    def _agenda(self, img):
        return img.convert("L").crop((AGENDA_X, 0, 800, 480 - FOOTER_H))

    def test_rows_do_not_change_with_the_clock(self):
        # The same day rendered before and after an event has passed must
        # produce identical pixels in the agenda pane.
        events = [_event(9, name="Standup"), _event(15, name="Retro")]
        morning = _render(data=_data_for(events=events, now=MIDNIGHT.replace(hour=8)))
        midday = _render(data=_data_for(events=events, now=MIDNIGHT.replace(hour=12)))
        assert self._agenda(morning).tobytes() == self._agenda(midday).tobytes()

    def test_no_filled_blocks_in_the_pane(self):
        # No inverted bar, no inverted TOMORROW chip. Width alone doesn't say
        # it — the header's Bayer rule spans the pane — so this looks for a
        # *band*: several consecutive rows that are each broadly inked. The
        # rule is 3 px tall; the bar this replaces was 30-60.
        events = [_event(7 + i, name=f"Event {i}") for i in range(6)]
        img = _render(data=_data_for(events=events)).convert("L")
        px = img.load()
        broad = []
        for y in range(480):
            run = longest = 0
            for x in range(AGENDA_X + 2, 800):
                run = run + 1 if px[x, y] == 0 else 0
                longest = max(longest, run)
            broad.append(longest >= 100)
        streak = best = 0
        for wide in broad:
            streak = streak + 1 if wide else 0
            best = max(best, streak)
        assert best <= 4, f"{best} consecutive broadly-inked rows — that is a filled block"

    def test_elapsed_rows_are_not_screened(self):
        # A screened row is a lattice of isolated pixels; solid type is not.
        events = [_event(7, name="Long gone")]
        img = _render(data=_data_for(events=events)).convert("L")
        px = img.load()
        iso = tot = 0
        for y in range(80, 200):
            for x in range(AGENDA_X + 20, 780):
                if px[x, y] == 0:
                    tot += 1
                    if all(
                        px[x + dx, y + dy] != 0 for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                    ):
                        iso += 1
        assert tot > 100, "no row drawn"
        assert iso / tot < 0.05, f"{100 * iso / tot:.0f}% isolated ink — row looks screened"

    def test_rows_are_top_justified(self):
        # A light day and a busy one must start their first row at the same y:
        # the list hangs from the rule, and the day's free space falls below
        # it. Measured on the draw call rather than on ink, because different
        # tiers set different type and so put their first pixel at different
        # offsets inside the row.
        import src.render.components.halftone_agenda_panel as mod

        def first_row_y(events):
            seen: list[int] = []
            original = mod._draw_event_row

            def spy(*args, **kwargs):
                seen.append(kwargs["y"])
                return original(*args, **kwargs)

            mod._draw_event_row = spy
            try:
                _render(data=_data_for(events=events))
            finally:
                mod._draw_event_row = original
            assert seen, "no rows drawn"
            return seen[0]

        light = first_row_y([_event(9), _event(15)])
        busy = first_row_y([_event(7 + i, name=f"Event {i}") for i in range(8)])
        assert light == busy, f"light starts at {light}, busy at {busy}"

    def test_row_pitch_is_sized_to_its_type(self):
        # Rows are spaced to their content, not stretched to fill the pane, so
        # a two-event day is a short list rather than a sparse one.
        leading = 26  # generous, but well short of stretch-to-fill
        for _max_rows, row_h, _time_w, _time_pt, title_pt, show_loc in _DENSITY_TIERS:
            content = title_pt + (title_pt - 4 if show_loc else 0)
            assert row_h <= content + leading, (row_h, title_pt, show_loc)


class TestAgendaWeight:
    """The calendar side must lay down as much ink as the weather side.

    Both panes are pure black on pure white by the time the panel sees them,
    so "not black enough" is a question of stroke mass, not of tone: at 22 px
    Righteous sets ~4.4 px stems and DM Sans SemiBold ~3.7 px, which reads as
    grey text next to it. The agenda therefore runs one weight heavier than
    the role each element fills.
    """

    def _mean_stem(self, font, text="12:30p Grocery run") -> float:
        from PIL import ImageDraw

        from src.render.skyart import TYPESET_CUT

        tile = Image.new("L", (320, 34), 255)
        ImageDraw.Draw(tile).text((2, 4), text, font=font, fill=0)
        px = tile.point(lambda v: 0 if v < TYPESET_CUT else 255).load()
        runs = total = 0
        for y in range(34):
            run = 0
            for x in range(320):
                if px[x, y] == 0:
                    run += 1
                else:
                    if run:
                        runs += 1
                        total += run
                    run = 0
        return total / max(1, runs)

    def test_bold_role_is_dm_sans_not_the_display_face(self):
        # Righteous is reached through font_title / font_section_label /
        # font_date_number, which frees the bold role for the agenda rows.
        from src.render.fonts import dm_bold, righteous

        style = load_theme("halftone_agenda").style
        assert style.font_bold is dm_bold
        assert style.font_title is righteous

    def test_agenda_titles_match_the_weather_pane_for_stroke_mass(self):
        from src.render.fonts import righteous

        style = load_theme("halftone_agenda").style
        target = self._mean_stem(righteous(22))
        title = self._mean_stem(style.font_bold(22))
        assert title >= target * 0.95, f"agenda {title:.2f}px vs weather {target:.2f}px"

    def test_every_agenda_role_is_a_step_heavier(self):
        style = load_theme("halftone_agenda").style
        light = self._mean_stem(style.font_regular(17))
        used = self._mean_stem(style.font_medium(17))  # what locations now use
        assert used > light


class TestTypesetHardening:
    """Text must not dither.

    PIL antialiases TrueType glyphs on an "L" canvas and the theme's
    Floyd-Steinberg pass then diffuses that edge error across glyph boundaries,
    which eats notches out of stems (a doubled "l" is the usual casualty) and
    speckles the white type inside the inverted bar. Snapping the typeset
    regions to pure ink/paper first is what keeps the plate legible on a panel.
    """

    def _pre_quantize(self, **kw):
        """Render and capture the L canvas as handed to the display backend."""
        import src.render.canvas as canvas_mod

        captured = {}
        original = canvas_mod.build_display_backend

        def spy(cfg):
            backend = original(cfg)
            inner = backend.resize_and_finalize

            def wrapper(image, *a, **kwargs):
                captured["image"] = image.copy()
                return inner(image, *a, **kwargs)

            backend.resize_and_finalize = wrapper
            return backend

        canvas_mod.build_display_backend = spy
        try:
            _render(**kw)
        finally:
            canvas_mod.build_display_backend = original
        return captured["image"]

    def _mid_greys(self, image, box):
        return sum(image.crop(box).histogram()[8:248])

    def test_agenda_pane_has_no_mid_greys(self):
        events = [_event(9), _event(10, minute=0, mins=120, name="All hands"), _event(15)]
        canvas = self._pre_quantize(data=_data_for(events=events))
        assert self._mid_greys(canvas, (AGENDA_X, 0, 800, 480)) == 0

    def test_weather_band_has_no_mid_greys(self):
        canvas = self._pre_quantize(data=_data_for())
        assert self._mid_greys(canvas, (0, BAND_Y, ART_W, 480)) == 0

    def test_illustration_still_dithers(self):
        # The hardening must be confined to the typeset regions — the whole
        # point of the theme is that the art keeps its greyscale gradient.
        canvas = self._pre_quantize(data=_data_for(icon="01d"))
        assert self._mid_greys(canvas, (0, 0, ART_W, 280)) > 1000


class TestHardenTypeset:
    def test_snaps_greys_to_ink_or_paper(self):
        img = Image.new("L", (4, 1))
        img.putdata([0, TYPESET_CUT - 1, TYPESET_CUT, 255])
        harden_typeset(img, (0, 0, 4, 1))
        assert list(flatten_pixels(img)) == [0, 0, 255, 255]

    def test_leaves_pixels_outside_the_box_alone(self):
        img = Image.new("L", (4, 1), 200)
        harden_typeset(img, (0, 0, 2, 1))
        assert list(flatten_pixels(img)) == [255, 255, 200, 200]

    def test_no_op_on_rgb_canvas(self):
        # The Inky path resolves each pixel independently, so no error crosses a
        # glyph edge — and snapping there would flatten the palette accents.
        img = Image.new("RGB", (2, 1), (120, 30, 30))
        harden_typeset(img, (0, 0, 2, 1))
        assert set(flatten_pixels(img)) == {(120, 30, 30)}

    def test_empty_box_is_a_no_op(self):
        img = Image.new("L", (2, 1), 120)
        harden_typeset(img, (0, 0, 0, 0))
        assert list(flatten_pixels(img)) == [120, 120]

    def test_already_pure_content_is_unchanged(self):
        # Bayer rules and screened rows are pure 0/255 and must survive intact.
        img = Image.new("L", (8, 8), 255)
        draw_bayer_rule(img, 0, 0, 8, 4, "L")
        before = img.tobytes()
        harden_typeset(img, (0, 0, 8, 8))
        assert img.tobytes() == before


class TestDeterminism:
    def test_two_renders_are_byte_identical(self):
        # Star fields and jitter are seeded from today.toordinal(); an unseeded
        # RNG here would make the theme's pixel snapshot flap.
        first = _render(data=_data_for(icon="01n"))
        second = _render(data=_data_for(icon="01n"))
        assert first.tobytes() == second.tobytes()


def test_draw_halftone_agenda_defaults_do_not_crash():
    # Called the way a bare unit test would: no image, region or style.
    from PIL import ImageDraw

    img = Image.new("L", (800, 480), 255)
    draw = ImageDraw.Draw(img)
    draw_halftone_agenda(draw, _data_for(), TODAY, FIXED_NOW)
    assert sum(1 for p in flatten_pixels(img) if p != 255) > 1000


def test_draw_halftone_agenda_into_a_sub_region():
    img = Image.new("L", (800, 480), 255)
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw_halftone_agenda(
        draw,
        _data_for(),
        TODAY,
        FIXED_NOW,
        image=img,
        region=ComponentRegion(0, 0, 700, 420),
        style=ThemeStyle(fg=0, bg=255),
    )
    px = img.load()
    # Nothing drawn outside the region it was handed.
    assert all(px[x, 470] == 255 for x in range(800))
    assert all(px[790, y] == 255 for y in range(480))
