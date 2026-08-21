"""Tests for src/render/components/week_view.py."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DayForecast
from src.render import layout as L
from src.render.components.week_view import (
    _density_tier,
    _events_for_day,
    _fmt_time,
    _fonts_for_tier,
    draw_week,
)
from src.render.quantize import flatten_pixels
from tests.inkutils import ink

# ---------------------------------------------------------------------------
# _fmt_time
# ---------------------------------------------------------------------------


WEEK_BOX = (L.WEEK_X, L.WEEK_Y, L.WEEK_X + L.WEEK_W, L.WEEK_Y + L.WEEK_H)


class TestFmtTime:
    def test_on_the_hour_am(self):
        dt = datetime(2024, 3, 15, 9, 0)
        assert _fmt_time(dt) == "9a"

    def test_on_the_hour_pm(self):
        dt = datetime(2024, 3, 15, 14, 0)
        assert _fmt_time(dt) == "2p"

    def test_with_minutes_am(self):
        dt = datetime(2024, 3, 15, 9, 30)
        assert _fmt_time(dt) == "9:30a"

    def test_with_minutes_pm(self):
        dt = datetime(2024, 3, 15, 15, 45)
        assert _fmt_time(dt) == "3:45p"

    def test_noon(self):
        dt = datetime(2024, 3, 15, 12, 0)
        assert _fmt_time(dt) == "12p"

    def test_midnight(self):
        dt = datetime(2024, 3, 15, 0, 0)
        assert _fmt_time(dt) == "12a"


# ---------------------------------------------------------------------------
# _events_for_day
# ---------------------------------------------------------------------------


class TestEventsForDay:
    def _timed(
        self, day: date, hour_start: int, hour_end: int, summary: str = "Event"
    ) -> CalendarEvent:
        return CalendarEvent(
            summary=summary,
            start=datetime.combine(day, datetime.min.time().replace(hour=hour_start)),
            end=datetime.combine(day, datetime.min.time().replace(hour=hour_end)),
        )

    def _all_day(self, start: date, end: date, summary: str = "All Day") -> CalendarEvent:
        return CalendarEvent(
            summary=summary,
            start=datetime.combine(start, datetime.min.time()),
            end=datetime.combine(end, datetime.min.time()),
            is_all_day=True,
        )

    def test_returns_events_on_matching_day(self):
        day = date(2024, 3, 15)
        e = self._timed(day, 9, 10)
        result = _events_for_day([e], day)
        assert e in result

    def test_excludes_events_on_other_days(self):
        day = date(2024, 3, 15)
        other = self._timed(date(2024, 3, 16), 9, 10)
        assert _events_for_day([other], day) == []

    def test_all_day_event_included_on_start_day(self):
        day = date(2024, 3, 15)
        e = self._all_day(day, day + timedelta(days=1))
        result = _events_for_day([e], day)
        assert e in result

    def test_all_day_event_excluded_on_end_day(self):
        """End date is exclusive (half-open interval)."""
        start = date(2024, 3, 15)
        end = date(2024, 3, 16)
        e = self._all_day(start, end)
        assert _events_for_day([e], end) == []

    def test_multi_day_event_included_on_middle_day(self):
        start = date(2024, 3, 14)
        end = date(2024, 3, 17)
        e = self._all_day(start, end)
        assert e in _events_for_day([e], date(2024, 3, 15))
        assert e in _events_for_day([e], date(2024, 3, 16))
        assert _events_for_day([e], date(2024, 3, 17)) == []

    def test_all_day_sorted_before_timed(self):
        day = date(2024, 3, 15)
        timed = self._timed(day, 8, 9, summary="Early Meeting")
        allday = self._all_day(day, day + timedelta(days=1), summary="Conference")
        result = _events_for_day([timed, allday], day)
        assert result[0] == allday
        assert result[1] == timed

    def test_timed_events_sorted_by_start(self):
        day = date(2024, 3, 15)
        late = self._timed(day, 15, 16, summary="Afternoon")
        early = self._timed(day, 9, 10, summary="Morning")
        result = _events_for_day([late, early], day)
        assert result[0] == early
        assert result[1] == late

    def test_empty_events_list(self):
        assert _events_for_day([], date(2024, 3, 15)) == []


# ---------------------------------------------------------------------------
# draw_week smoke test
# ---------------------------------------------------------------------------


class TestDrawWeek:
    def _make_draw(self):
        img = Image.new("1", (800, 480), 1)
        return img, ImageDraw.Draw(img)

    def test_smoke_no_events(self):
        img, draw = self._make_draw()
        draw_week(draw, [], date(2024, 3, 15))
        # The empty grid is still the day headers + column rules.
        assert ink(img, WEEK_BOX) > 0

    def test_smoke_with_timed_events(self):
        img, draw = self._make_draw()
        today = date(2024, 3, 15)
        events = [
            CalendarEvent(
                summary="Standup",
                start=datetime.combine(today, datetime.min.time().replace(hour=9)),
                end=datetime.combine(today, datetime.min.time().replace(hour=9, minute=30)),
            ),
        ]
        draw_week(draw, events, today)
        empty, empty_draw = self._make_draw()
        draw_week(empty_draw, [], today)
        assert ink(img, WEEK_BOX) > ink(empty, WEEK_BOX), "the event was not drawn"

    def test_location_newlines_are_normalized_before_truncation(self):
        img, draw = self._make_draw()
        today = date(2024, 3, 15)
        events = [
            CalendarEvent(
                summary="Client Meeting",
                start=datetime.combine(today, datetime.min.time().replace(hour=9)),
                end=datetime.combine(today, datetime.min.time().replace(hour=10)),
                location="123 Main St\nSuite 200, Springfield",
            ),
        ]
        seen_texts: list[str] = []

        def _capture_text(*args, **kwargs):
            # signature: (draw, xy, text, font, max_width, fill=...)
            seen_texts.append(args[2])
            return 0

        with patch(
            "src.render.components.week_view.draw_text_truncated", side_effect=_capture_text
        ):
            draw_week(draw, events, today)

        assert any("Suite 200" in t for t in seen_texts)
        assert all("\n" not in t for t in seen_texts)

    def test_smoke_with_all_day_event(self):
        img, draw = self._make_draw()
        today = date(2024, 3, 15)
        events = [
            CalendarEvent(
                summary="Conference",
                start=datetime.combine(today, datetime.min.time()),
                end=datetime.combine(today + timedelta(days=1), datetime.min.time()),
                is_all_day=True,
            ),
        ]
        draw_week(draw, events, today)
        empty, empty_draw = self._make_draw()
        draw_week(empty_draw, [], today)
        assert ink(img, WEEK_BOX) > ink(empty, WEEK_BOX), "the all-day bar was not drawn"

    def test_smoke_many_events_per_day(self):
        """Overflow indicator (+N more) should not crash."""
        img, draw = self._make_draw()
        today = date(2024, 3, 15)
        events = [
            CalendarEvent(
                summary=f"Event {i}",
                start=datetime.combine(today, datetime.min.time().replace(hour=8 + i)),
                end=datetime.combine(today, datetime.min.time().replace(hour=9 + i)),
            )
            for i in range(10)
        ]
        draw_week(draw, events, today)
        few, few_draw = self._make_draw()
        draw_week(few_draw, events[:2], today)
        assert ink(img, WEEK_BOX) > ink(few, WEEK_BOX), "ten events drew no more than two"

    @staticmethod
    def _header_ink_by_column(img, region=None):
        """Ink fraction of each of the 7 day-header cells.

        ``img.getbbox() is not None`` is true of any non-blank plate, so it
        cannot tell an inverted today column from a missing one. Measuring the
        header band per column can.
        """
        from src.render.layout import WEEK_H, WEEK_W, WEEK_X, WEEK_Y

        x0, y0, w, h = region or (WEEK_X, WEEK_Y, WEEK_W, WEEK_H)
        header_h = max(24, h * 32 // 320)
        col_w = w // 7
        fractions = []
        for col in range(7):
            cell = img.crop((x0 + col * col_w, y0, x0 + col * col_w + col_w, y0 + header_h))
            pixels = flatten_pixels(cell)
            fractions.append(sum(1 for px in pixels if px == 0) / len(pixels))
        return fractions

    def test_today_column_header_is_inverted(self):
        """Today's header cell is filled with fg, so it is mostly ink.

        Asserted against the other six columns rather than in absolute terms,
        so the test survives font and padding changes.
        """
        today = date(2024, 3, 15)  # a Friday → column index 4 (Monday-first)
        img, draw = self._make_draw()
        draw_week(draw, [], today)

        ink = self._header_ink_by_column(img)
        assert ink[4] == max(ink), "today's header must be the most-inked column"
        others = [v for i, v in enumerate(ink) if i != 4]
        assert ink[4] > 0.5, "an inverted cell should be more than half ink"
        assert ink[4] > 2 * max(others), "today must stand out from the other days"

    def test_today_highlight_tracks_the_date(self):
        """The highlight follows today rather than being drawn at a fixed column."""
        for offset, expected_col in ((0, 0), (2, 2), (6, 6)):
            img, draw = self._make_draw()
            monday = date(2024, 3, 11)
            draw_week(draw, [], monday + timedelta(days=offset))
            ink = self._header_ink_by_column(img)
            assert ink.index(max(ink)) == expected_col

    def test_invert_today_col_false_leaves_the_header_light(self):
        """Turning the inversion off must actually remove the filled cell."""
        from src.render.theme import ThemeStyle

        today = date(2024, 3, 15)
        img, draw = self._make_draw()
        draw_week(draw, [], today, style=ThemeStyle(invert_today_col=False))

        ink = self._header_ink_by_column(img)
        assert ink[4] < 0.5, "the today cell must not be filled when inversion is off"

    def test_smoke_with_forecast_icons(self):
        """draw_week with forecast data should not crash."""
        img, draw = self._make_draw()
        today = date(2024, 3, 18)  # Monday
        forecast = [
            DayForecast(
                date=today + timedelta(days=i),
                high=50.0 + i,
                low=35.0,
                icon="01d",
                description="clear",
                precip_chance=0.1,
            )
            for i in range(5)
        ]
        draw_week(draw, [], today, forecast=forecast)
        # NOTE: draw_week accepts `forecast` and never reads it — see the
        # finding recorded in tests/test_v3_features.py::TestWeekViewForecast.
        # This asserts the grid renders, not that a forecast appears.
        plain, plain_draw = self._make_draw()
        draw_week(plain_draw, [], today)
        assert ink(img, WEEK_BOX) > 0
        assert img.tobytes() == plain.tobytes(), "draw_week started using its forecast argument"

    def test_today_bordered_not_inverted_draws_underline(self):
        """invert_today_col=False + show_borders=True → thick accent underline under today.

        Compared against the borderless variant of the same plate, so the
        assertion is about the underline itself and not about the plate merely
        being non-blank.
        """
        from src.render.theme import ComponentRegion, ThemeStyle

        today = date(2026, 4, 22)  # a Wednesday → column index 2
        region = ComponentRegion(0, 40, 800, 400)

        def _render(show_borders):
            img, draw = self._make_draw()
            draw_week(
                draw,
                [],
                today,
                region=region,
                style=ThemeStyle(invert_today_col=False, show_borders=show_borders),
            )
            return img

        bordered = _render(True)
        borderless = _render(False)
        assert bordered.tobytes() != borderless.tobytes()

        # The extra ink lands in today's column, in the band just under the header.
        header_h = max(24, region.h * 32 // 320)
        col_w = region.w // 7
        band = (2 * col_w, region.y + header_h - 6, 3 * col_w, region.y + header_h + 6)
        bordered_ink = sum(1 for px in flatten_pixels(bordered.crop(band)) if px == 0)
        borderless_ink = sum(1 for px in flatten_pixels(borderless.crop(band)) if px == 0)
        assert bordered_ink > borderless_ink, "the underline must add ink under today"

    @staticmethod
    def _unscaled_month_width(theme, name):
        """Width of *name* at the band's starting 33px size, before any shrink."""
        probe = ImageDraw.Draw(Image.new("1", (10, 10), 1))
        bbox = probe.textbbox((0, 0), name, font=theme.style.font_month_title(33))
        return bbox[2] - bbox[0]

    def test_long_month_name_is_scaled_down_to_fit_the_cell(self):
        """SEPTEMBER overflows the combined Sat/Sun date cell at the starting
        33px size, so week_view's shrink loop must bring it back inside.

        Measured against the cell, not against a short month: SEPTEMBER has
        three times MAY's letters and is legitimately wider on the plate even
        after shrinking. The property that matters is that it *fits*.
        """
        from src.render.theme import load_theme

        theme = load_theme("terminal")
        cell_w = theme.layout.week_view.w // 7 * 2  # last two columns, merged

        assert self._unscaled_month_width(theme, "SEPTEMBER") > cell_w, (
            "fixture no longer exercises the shrink loop — pick a longer month"
        )

        band = self._month_band(theme, date(2026, 9, 16))
        assert band is not None, "the month band must actually be drawn"
        assert band[2] <= cell_w, (
            f"SEPTEMBER renders {band[2]}px wide in a {cell_w}px cell — "
            f"the font shrink loop did not bring it inside"
        )

    def test_short_month_name_is_not_scaled_down(self):
        """MAY already fits, so the shrink loop must leave it at full size."""
        from src.render.theme import load_theme

        theme = load_theme("terminal")
        unscaled = self._unscaled_month_width(theme, "MAY")
        cell_w = theme.layout.week_view.w // 7 * 2
        assert unscaled <= cell_w, "MAY should fit without shrinking"

        band = self._month_band(theme, date(2026, 5, 13))
        assert band is not None
        # Drawn ink is a few px narrower than the advance-width probe.
        assert band[2] >= unscaled - 8, (
            f"MAY renders {band[2]}px against a {unscaled}px unscaled width — "
            f"it was shrunk when it did not need to be"
        )

    @staticmethod
    def _month_band(theme, day):
        """Bounding box of the ink in the month band, as (x0, y0, width)."""
        img = Image.new("1", (800, 480), 1)
        draw = ImageDraw.Draw(img)
        region = theme.layout.week_view
        draw_week(draw, [], day, region=region, style=theme.style)

        header_h = max(24, region.h * 32 // 320)
        body_h = region.h - header_h
        date_section_h = body_h // 2
        col_w = region.w // 7
        # Combined Sat/Sun date cell: the last two columns, lower half of body.
        band = (
            5 * col_w,
            region.y + header_h + body_h - date_section_h,
            region.x + region.w,
            region.y + region.h,
        )
        # getbbox() finds *non-zero* pixels, and in mode "1" the blank canvas
        # is all 1s — so it would return the full crop even with nothing drawn.
        # Invert first so the measurement tracks ink.
        ink = img.crop(band).point(lambda v: 0 if v else 1, mode="1")
        bbox = ink.getbbox()
        if bbox is None:
            return None
        return (bbox[0], bbox[1], bbox[2] - bbox[0])

    def test_smoke_spanning_event_excludes_from_per_day(self):
        """Multi-day spanning events don't crash and render as bars."""
        img, draw = self._make_draw()
        today = date(2024, 3, 18)  # Monday
        week_start = today - timedelta(days=today.weekday())
        spanning = CalendarEvent(
            summary="Conference",
            start=datetime.combine(week_start + timedelta(days=1), datetime.min.time()),
            end=datetime.combine(week_start + timedelta(days=4), datetime.min.time()),
            is_all_day=True,
        )
        draw_week(draw, [spanning], today)
        empty, empty_draw = self._make_draw()
        draw_week(empty_draw, [], today)
        assert ink(img, WEEK_BOX) > ink(empty, WEEK_BOX), "the spanning bar was not drawn"


# ---------------------------------------------------------------------------
# _density_tier
# ---------------------------------------------------------------------------


class TestDensityTier:
    # --- Weekday thresholds ---
    def test_weekday_normal_zero_events(self):
        assert _density_tier(0, is_weekend=False) == "normal"

    def test_weekday_normal_four_events(self):
        assert _density_tier(4, is_weekend=False) == "normal"

    def test_weekday_compact_five_events(self):
        assert _density_tier(5, is_weekend=False) == "compact"

    def test_weekday_compact_seven_events(self):
        assert _density_tier(7, is_weekend=False) == "compact"

    def test_weekday_dense_eight_events(self):
        assert _density_tier(8, is_weekend=False) == "dense"

    def test_weekday_dense_many_events(self):
        assert _density_tier(20, is_weekend=False) == "dense"

    # --- Weekend thresholds (lower) ---
    def test_weekend_normal_zero_events(self):
        assert _density_tier(0, is_weekend=True) == "normal"

    def test_weekend_normal_two_events(self):
        assert _density_tier(2, is_weekend=True) == "normal"

    def test_weekend_compact_three_events(self):
        assert _density_tier(3, is_weekend=True) == "compact"

    def test_weekend_compact_four_events(self):
        assert _density_tier(4, is_weekend=True) == "compact"

    def test_weekend_dense_five_events(self):
        assert _density_tier(5, is_weekend=True) == "dense"

    def test_weekend_dense_many_events(self):
        assert _density_tier(10, is_weekend=True) == "dense"

    # --- Boundary: weekday threshold does NOT apply to weekend ---
    def test_weekend_one_event_is_still_normal(self):
        """1 event on a weekend stays normal (threshold is ≥3 for compact)."""
        assert _density_tier(1, is_weekend=True) == "normal"

    def test_weekday_three_events_is_still_normal(self):
        """3 events on a weekday stays normal (threshold is ≥5 for compact)."""
        assert _density_tier(3, is_weekend=False) == "normal"


# ---------------------------------------------------------------------------
# _fonts_for_tier
# ---------------------------------------------------------------------------


class TestFontsForTier:
    def test_normal_tier_returns_7_tuple(self):
        result = _fonts_for_tier("normal")
        assert len(result) == 7

    def test_compact_tier_returns_7_tuple(self):
        result = _fonts_for_tier("compact")
        assert len(result) == 7

    def test_dense_tier_returns_7_tuple(self):
        result = _fonts_for_tier("dense")
        assert len(result) == 7

    def test_normal_tier_show_location_true(self):
        _, _, _, _, _, show_location, _ = _fonts_for_tier("normal")
        assert show_location is True

    def test_compact_tier_show_location_false(self):
        _, _, _, _, _, show_location, _ = _fonts_for_tier("compact")
        assert show_location is False

    def test_dense_tier_show_location_false(self):
        _, _, _, _, _, show_location, _ = _fonts_for_tier("dense")
        assert show_location is False

    def test_normal_tier_max_title_lines_two(self):
        _, _, _, _, max_lines, _, _ = _fonts_for_tier("normal")
        assert max_lines == 2

    def test_compact_tier_max_title_lines_one(self):
        _, _, _, _, max_lines, _, _ = _fonts_for_tier("compact")
        assert max_lines == 1

    def test_dense_tier_max_title_lines_one(self):
        _, _, _, _, max_lines, _, _ = _fonts_for_tier("dense")
        assert max_lines == 1

    def test_normal_tier_spacing_larger_than_dense(self):
        _, _, _, normal_spacing, _, _, _ = _fonts_for_tier("normal")
        _, _, _, dense_spacing, _, _, _ = _fonts_for_tier("dense")
        assert normal_spacing > dense_spacing

    def test_tiers_have_different_spacings(self):
        _, _, _, normal_spacing, _, _, _ = _fonts_for_tier("normal")
        _, _, _, compact_spacing, _, _, _ = _fonts_for_tier("compact")
        _, _, _, dense_spacing, _, _, _ = _fonts_for_tier("dense")
        # normal > compact > dense
        assert normal_spacing > compact_spacing > dense_spacing


# ---------------------------------------------------------------------------
# _draw_day_events — allday_font default (line 392) and overflow (lines 404-406)
# ---------------------------------------------------------------------------


class TestDrawDayEvents:
    """Exercise _draw_day_events directly for edge-case branches."""

    def _make_draw(self):
        img = Image.new("1", (800, 480), 1)
        return img, ImageDraw.Draw(img)

    def _timed(self, hour_start: int, hour_end: int, summary: str = "Event") -> CalendarEvent:
        day = date(2024, 3, 15)
        return CalendarEvent(
            summary=summary,
            start=datetime.combine(day, datetime.min.time().replace(hour=hour_start)),
            end=datetime.combine(day, datetime.min.time().replace(hour=hour_end)),
        )

    def test_default_allday_font_is_used_when_none(self):
        """Calling _draw_day_events without allday_font triggers the default (line 392)."""
        from src.render.components.week_view import _draw_day_events
        from src.render.fonts import regular, semibold

        img, draw = self._make_draw()
        event = CalendarEvent(
            summary="All Day Event",
            start=datetime(2024, 3, 15),
            end=datetime(2024, 3, 16),
            is_all_day=True,
        )
        # Pass allday_font=None (the default) — exercises line 392
        _draw_day_events(
            draw=draw,
            events=[event],
            cx=0,
            y_start=40,
            col_w=114,
            max_h=280,
            time_font=regular(10),
            title_font=semibold(13),
            allday_font=None,  # triggers line 392
        )
        assert ink(img) > 0, "the allday_font=None fallback drew nothing"

    def test_overflow_indicator_shown_when_events_exceed_space(self):
        """When events don't fit, '+N more' is shown (lines 404-406)."""
        from src.render.components.week_view import _draw_day_events
        from src.render.fonts import regular, semibold

        img, draw = self._make_draw()
        # Create many events
        events = [self._timed(h, h + 1, f"Event {h}") for h in range(8, 18)]

        # Use a very small max_h so events overflow quickly
        _draw_day_events(
            draw=draw,
            events=events,
            cx=0,
            y_start=40,
            col_w=114,
            max_h=50,  # tiny — forces overflow after first event
            time_font=regular(10),
            title_font=semibold(13),
        )
        # A 50px column cannot hold ten events, so most become "+N more".
        assert ink(img) > 0, "nothing drawn"
        roomy, roomy_draw = self._make_draw()
        _draw_day_events(
            draw=roomy_draw,
            events=events,
            cx=0,
            y_start=40,
            col_w=114,
            max_h=280,
            time_font=regular(10),
            title_font=semibold(13),
        )
        assert ink(img) < ink(roomy), "the tiny column listed as much as a roomy one"
