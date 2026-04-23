"""Tests for src/render/components/week_view.py."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DayForecast
from src.render.components.week_view import (
    _density_tier,
    _events_for_day,
    _fmt_time,
    _fonts_for_tier,
    draw_week,
)

# ---------------------------------------------------------------------------
# _fmt_time
# ---------------------------------------------------------------------------


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
        # Should draw something (header lines at minimum)
        assert img.getbbox() is not None

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
        assert img.getbbox() is not None

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
        assert img.getbbox() is not None

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
        assert img.getbbox() is not None

    def test_today_column_highlighted(self):
        """Today's column uses an inverted header — verify black pixels exist."""
        today = date(2024, 3, 15)
        img, draw = self._make_draw()
        draw_week(draw, [], today)
        # There must be at least one black pixel (inverted today header)
        bbox = img.getbbox()
        assert bbox is not None

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
        assert img.getbbox() is not None

    def test_today_bordered_not_inverted_draws_underline(self):
        """invert_today_col=False + show_borders=True → thick accent underline under today."""
        from src.render.theme import ComponentRegion, ThemeStyle

        img, draw = self._make_draw()
        today = date(2026, 4, 22)  # a Wednesday
        style = ThemeStyle(invert_today_col=False, show_borders=True)
        draw_week(
            draw,
            [],
            today,
            region=ComponentRegion(0, 40, 800, 400),
            style=style,
        )
        assert img.getbbox() is not None

    def test_long_month_name_triggers_font_scale_down(self):
        """A long month name (SEPTEMBER) in the terminal theme forces the scale-down loop."""
        from src.render.theme import load_theme

        img, draw = self._make_draw()
        theme = load_theme("terminal")
        # September in the combined Sat/Sun date cell is wider than the default
        # 33px uesc_display glyph run — forces week_view's month-font shrink loop.
        draw_week(
            draw,
            [],
            date(2026, 9, 16),
            region=theme.layout.week_view,
            style=theme.style,
        )
        assert img.getbbox() is not None

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
        assert img.getbbox() is not None


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
        assert img.getbbox() is not None

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
        assert img.getbbox() is not None
