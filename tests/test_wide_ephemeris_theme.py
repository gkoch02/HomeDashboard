"""wide_ephemeris: HomeDashboardTV's Ephemeris plate on the panoramic strip.

The model functions are pinned directly (the strip's window, lanes and event
states, the agenda's rows, the check line's sources, the readings grid); the
render tests pin what the inks mean (gold is under way now, red is an alert)
and that the plate only moves on the clock hour.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    StalenessLevel,
    WeatherAlert,
    WeatherData,
)
from src.display.driver import image_hash
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components import wide_ephemeris_panel as ep
from src.render.quantize import flatten_pixels
from src.render.theme import load_theme
from tests.inkutils import record_text

NOW = datetime(2026, 4, 7, 10, 15)  # a Tuesday; the dentist runs 10–11
G_PANEL = DisplayConfig(model="epd10in85g", width=1360, height=480)
MONO = DisplayConfig(model="epd7in5_V2", width=1360, height=480)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
# The agenda's first row, where the event under way sits.
FIRST_ROW = (ep.MARGIN, ep.COLUMN_TOP, ep.MARGIN + ep.AGENDA_W, ep.COLUMN_TOP + ep.ROW_H)
CONDITIONS_X = ep.MARGIN + ep.AGENDA_W + ep.COLUMN_GAP
# Where the alert slab sits under the reading now.
ALERT_BOX = (CONDITIONS_X, ep.COLUMN_TOP + 68, CONDITIONS_X + ep.CONDITIONS_W, ep.COLUMN_TOP + 92)


def _at(hour: int) -> datetime:
    return NOW.replace(hour=hour, minute=0)


def _event(summary: str, start: datetime, minutes: int = 60, **kw) -> CalendarEvent:
    return CalendarEvent(summary=summary, start=start, end=start + timedelta(minutes=minutes), **kw)


def _data(now: datetime = NOW, **kw) -> DashboardData:
    data = generate_dummy_data(now=now, event_window_days=8)
    data.fetched_at = now
    data.content_at = now
    data.source_staleness = {}
    if data.weather is not None:
        data.weather.alerts = []
    for key, value in kw.items():
        setattr(data, key, value)
    return data


def _render(data: DashboardData, config: DisplayConfig = G_PANEL, now: datetime | None = None):
    if now is not None:
        data.fetched_at = now
    return render_dashboard(data, config, theme=load_theme("wide_ephemeris"))


def _count(img, colour, box) -> int:
    px, width = flatten_pixels(img), img.width
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == colour)


class TestTheme:
    def test_layout(self):
        theme = load_theme("wide_ephemeris")
        assert (theme.layout.canvas_w, theme.layout.canvas_h) == (1360, 480)
        assert theme.layout.draw_order == ["wide_ephemeris"]
        assert theme.layout.repaint_slot_hours == 1

    def test_dark_ground_derives_out_of_partial_refresh(self):
        assert load_theme("wide_ephemeris").allows_partial_refresh is False

    def test_renders_in_the_four_inks_exactly(self):
        img = _render(_data())
        assert img.size == (1360, 480)
        assert set(flatten_pixels(img)) <= {(0, 0, 0), (255, 255, 255), YELLOW, RED}


class TestWindow:
    def test_anchored_to_the_hour_holding_now(self):
        a = ep.Window.at(datetime(2026, 4, 7, 10, 2), 0, 2400)
        b = ep.Window.at(datetime(2026, 4, 7, 10, 58), 0, 2400)
        assert a == b
        assert a.start == datetime(2026, 4, 7, 9, 0)
        assert a.end == datetime(2026, 4, 8, 9, 0)

    def test_x_is_linear_in_time(self):
        w = ep.Window.at(datetime(2026, 4, 7, 10, 30), 0, 2400)
        assert w.px_per_hour == 100
        assert w.x(datetime(2026, 4, 7, 10, 30)) == 150

    def test_label_step_leaves_room_between_labels(self):
        assert ep.label_step(55) == 2
        assert ep.label_step(100) == 1
        assert ep.label_step(5) == 6


class TestSpans:
    def test_states(self):
        w = ep.Window.at(NOW, 0, 2400)
        events = [
            _event("over", _at(9), 30),
            _event("on", _at(10)),
            _event("soon", _at(13)),
            _event("later", _at(15)),
            _event("all day", _at(0), 24 * 60, is_all_day=True),
            _event("outside", NOW + timedelta(days=2)),
        ]
        states = {s.event.summary: s.state for s in ep.spans(events, NOW, w)}
        assert states == {"over": "past", "on": "active", "soon": "next", "later": "later"}


class TestLanes:
    def test_sequential_extents_share_a_lane(self):
        assert ep.lanes([(0, 10), (10, 20)], 2) == [0, 0]

    def test_overlaps_open_a_second_lane_then_drop(self):
        assert ep.lanes([(0, 10), (5, 15), (8, 18)], 2) == [0, 1, None]

    def test_what_is_ahead_claims_a_lane_before_what_is_over(self):
        past, upcoming = (0, 20), (10, 30)
        priority = [ep.LANE_PRIORITY["past"], ep.LANE_PRIORITY["next"]]
        assert ep.lanes([past, upcoming], 1, priority) == [None, 0]

    def test_a_late_extent_fills_a_gap_left_earlier(self):
        # Priority can place a later extent first; an earlier one still fits before it.
        assert ep.lanes([(0, 10), (20, 30)], 1, [1, 0]) == [0, 0]

    def test_render_keeps_the_next_event_on_the_strip(self):
        # At 10:15 the 9:00 standup is over and its label would run past the
        # 11:00 review; the review is next and must hold a lane.
        image = Image.new("L", (1360, 480))
        draw = ImageDraw.Draw(image)
        calls = record_text(draw)
        ep.draw_wide_ephemeris(draw, _data(), NOW.date(), NOW)
        on_strip = {text for text, (_, y0, _, _) in calls if ep.LANE_TOP <= y0 < ep.COLUMN_TOP}
        assert "Sprint Review" in on_strip
        assert "Morning Standup" not in on_strip


class TestAgenda:
    def test_under_way_first_then_next_then_the_rest(self):
        events = [
            _event("later", _at(15)),
            _event("next", _at(11)),
            _event("on", _at(10)),
            _event("over", _at(8)),
            _event("tomorrow", _at(9) + timedelta(days=1)),
        ]
        rows = ep.agenda_rows(events, [], NOW)
        assert [(r.title, r.tone, r.detail) for r in rows] == [
            ("on", "lit", "UNTIL 11A"),
            ("next", "next", "11A"),
            ("later", "dim", "3P"),
            ("tomorrow", "dim", "TOMORROW 9A"),
        ]

    def test_birthdays_within_the_fortnight_join_in_date_order(self):
        soon = Birthday(name="Mom", date=date(1956, 4, 12))
        far = Birthday(name="Dad", date=date(1955, 6, 1))
        events = [_event("standup", _at(9) + timedelta(days=1))]
        rows = ep.agenda_rows(events, [soon, far], NOW)
        assert [(r.title, r.kind, r.detail) for r in rows] == [
            ("standup", "event", "TOMORROW 9A"),
            ("Mom", "birthday", "SUNDAY"),
        ]

    def test_all_day_event_reads_all_day_today(self):
        conf = _event("conference", _at(0), 24 * 60, is_all_day=True)
        assert ep.agenda_rows([conf], [], NOW)[0].detail == "ALL DAY"

    def test_lit_row_is_gold_only_while_something_is_under_way(self):
        lit = _count(_render(_data()), YELLOW, FIRST_ROW)
        between = NOW.replace(hour=11, minute=0) - timedelta(minutes=1)
        idle_data = _data(now=between)
        idle_data.events = [e for e in idle_data.events if e.summary != "Dentist Appointment"]
        idle = _count(_render(idle_data), YELLOW, FIRST_ROW)
        assert lit > 5000  # a filled slab, not an edge
        assert idle < 400


class TestCheckLine:
    def test_flags_stale_and_expired_in_a_fixed_order(self):
        data = DashboardData(
            source_staleness={
                "air_quality": StalenessLevel.EXPIRED,
                "weather": StalenessLevel.AGING,
                "events": StalenessLevel.STALE,
            }
        )
        assert ep.stale_sources(data) == ["CALENDAR", "AIR"]

    def test_stale_source_turns_the_check_line_red(self):
        header = (300, 10, 900, ep.HEADER_H - 4)
        fresh = _count(_render(_data()), RED, header)
        stale = _count(
            _render(_data(source_staleness={"weather": StalenessLevel.STALE})), RED, header
        )
        assert fresh == 0
        assert stale > 100


class TestConditions:
    def _weather(self, **kw) -> WeatherData:
        base = dict(
            current_temp=42.0,
            current_icon="02d",
            current_description="partly cloudy",
            high=48.0,
            low=35.0,
            humidity=65,
        )
        base.update(kw)
        return WeatherData(**base)

    def test_readings_skip_what_is_missing(self):
        data = DashboardData(weather=self._weather())
        labels = [label for label, _ in ep.readings(data, NOW.date())]
        assert labels[0] == "HUMIDITY"
        assert "WIND" not in labels and "PRESSURE" not in labels
        assert len(labels) == 2  # humidity and the moon, which is always known

    def test_readings_stop_at_six(self):
        weather = self._weather(wind_speed=12, wind_deg=315, uv_index=5, pressure=1013)
        air = AirQualityData(aqi=42, category="Good", pm25=8.0)
        cells = ep.readings(DashboardData(weather=weather, air_quality=air), NOW.date())
        assert len(cells) == 6
        assert ("WIND", "12 NW mph") in cells
        assert ("AIR · GOOD", "42 AQI") in cells
        assert ("UV · MODERATE", "5") in cells

    def test_alert_is_red_on_colour_and_a_solid_slab_on_mono(self):
        quiet = _data()
        loud = _data()
        loud.weather.alerts = [WeatherAlert(event="Wind Advisory")]
        assert _count(_render(quiet), RED, ALERT_BOX) == 0
        assert _count(_render(loud), RED, ALERT_BOX) > 300
        white = 255
        mono_quiet = _count(_render(quiet, MONO), white, ALERT_BOX)
        mono_loud = _count(_render(loud, MONO), white, ALERT_BOX)
        assert mono_loud - mono_quiet > 5000


class TestClock:
    def test_the_plate_holds_still_within_the_hour(self):
        early, late = NOW.replace(minute=20), NOW.replace(minute=50)
        a = _data(now=early)
        b = _data(now=late)
        b.content_at = a.content_at
        assert image_hash(_render(a)) == image_hash(_render(b))

    def test_the_plate_steps_on_the_hour(self):
        a = _data(now=NOW.replace(minute=50))
        b = _data(now=NOW.replace(hour=11, minute=5))
        b.content_at = a.content_at
        b.events = a.events
        assert image_hash(_render(a)) != image_hash(_render(b))
