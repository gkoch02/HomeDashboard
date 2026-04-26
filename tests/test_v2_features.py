"""Tests for v2 features: location display, weather alerts, busy-ness heatmap,
per-source cache, and incremental calendar sync.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image, ImageDraw

from src.data.models import (
    CalendarEvent,
    DashboardData,
    DayForecast,
    WeatherAlert,
    WeatherData,
)
from src.fetchers.cache import (
    load_cached,
    load_cached_source,
    save_cache,
    save_source,
)
from src.fetchers.calendar import (
    _apply_delta,
    _deser_sync_event,
    _fetch_incremental,
    _filter_to_window,
    _ser_sync_event,
)
from src.render.components.weather_panel import draw_weather
from src.render.components.week_view import draw_week

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _timed(day: date, h_start: int, h_end: int, summary: str = "Evt", location: str | None = None):
    return CalendarEvent(
        summary=summary,
        start=datetime.combine(day, datetime.min.time().replace(hour=h_start)),
        end=datetime.combine(day, datetime.min.time().replace(hour=h_end)),
        location=location,
    )


def _make_weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=55.0,
        current_icon="01d",
        current_description="clear",
        high=60.0,
        low=45.0,
        humidity=50,
        forecast=[
            DayForecast(
                date=date.today() + timedelta(days=1),
                high=58.0,
                low=44.0,
                icon="02d",
                description="cloudy",
            )
        ],
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


# ---------------------------------------------------------------------------
# Event location display (week_view)
# ---------------------------------------------------------------------------


class TestEventLocationDisplay:
    def test_event_with_location_renders(self):
        """Smoke test: events with location should not crash draw_week."""
        today = date(2024, 3, 15)
        events = [_timed(today, 9, 10, "Meeting", location="Conference Room A")]
        img, draw = _make_draw()
        draw_week(draw, events, today)
        assert img.getbbox() is not None

    def test_event_location_split_on_comma(self):
        """Location with comma: only the first component should appear (tested via no-crash)."""
        today = date(2024, 3, 15)
        events = [_timed(today, 9, 10, "Dentist", location="123 Main St, Suite 4, Springfield")]
        img, draw = _make_draw()
        draw_week(draw, events, today)
        assert img.getbbox() is not None

    def test_event_without_location_renders(self):
        """Events without location should still render correctly."""
        today = date(2024, 3, 15)
        events = [_timed(today, 9, 10, "No Location")]
        img, draw = _make_draw()
        draw_week(draw, events, today)
        assert img.getbbox() is not None

    def test_many_events_with_locations_overflow(self):
        """Overflow (+N more) should still work when events have locations."""
        today = date(2024, 3, 15)
        events = [_timed(today, 8 + i, 9 + i, f"Evt {i}", location=f"Room {i}") for i in range(8)]
        img, draw = _make_draw()
        draw_week(draw, events, today)
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# Week view header rendering (busyness indicators removed)
# ---------------------------------------------------------------------------


class TestBusynessHeatmap:
    def test_no_crash_with_max_events(self):
        """10+ events (> _MAX_DOTS cap) should not crash."""
        today = date(2024, 3, 18)
        events = [_timed(today, 7, 8, f"Evt {i}") for i in range(12)]
        img, draw = _make_draw()
        draw_week(draw, events, today)
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# Weather alerts
# ---------------------------------------------------------------------------


class TestWeatherAlerts:
    def test_alert_renders_without_crash(self):
        weather = _make_weather(alerts=[WeatherAlert(event="Flood Watch")])
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_no_alerts_renders_normally(self):
        weather = _make_weather(alerts=[])
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_long_alert_name_truncated(self):
        """Very long alert names should be truncated, not overflow."""
        weather = _make_weather(alerts=[WeatherAlert(event="A" * 200)])
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_weather_alert_model(self):
        a = WeatherAlert(event="Tornado Warning")
        assert a.event == "Tornado Warning"

    def test_weather_data_has_alerts_field(self):
        w = _make_weather()
        assert w.alerts == []

    def test_fetch_alerts_returns_empty_on_failure(self):
        """_fetch_alerts_and_uv must silently return ([], None) on any HTTP error."""
        from src.fetchers.weather import _fetch_alerts_and_uv

        params = {"lat": 0, "lon": 0, "appid": "key", "units": "imperial"}
        session = MagicMock()
        session.get.side_effect = Exception("network")
        alerts, uv = _fetch_alerts_and_uv(session, params)
        assert alerts == []
        assert uv is None

    def test_fetch_alerts_parses_response(self):
        """_fetch_alerts_and_uv should parse event names from a valid response."""
        from src.fetchers.weather import _fetch_alerts_and_uv

        params = {"lat": 0, "lon": 0, "appid": "key", "units": "imperial"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "alerts": [
                {"event": "Dense Fog Advisory", "description": "..."},
                {"event": "Winter Storm Warning", "description": "..."},
            ],
            "current": {"uvi": 6.5},
        }
        session = MagicMock()
        session.get.return_value = mock_resp
        alerts, uv = _fetch_alerts_and_uv(session, params)
        assert len(alerts) == 2
        assert alerts[0].event == "Dense Fog Advisory"
        assert alerts[1].event == "Winter Storm Warning"
        assert uv == 6.5

    def test_fetch_alerts_skips_empty_event_names(self):
        from src.fetchers.weather import _fetch_alerts_and_uv

        params = {"lat": 0, "lon": 0, "appid": "key", "units": "imperial"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"alerts": [{"event": "  "}, {"event": "Real Alert"}]}
        session = MagicMock()
        session.get.return_value = mock_resp
        alerts, uv = _fetch_alerts_and_uv(session, params)
        assert len(alerts) == 1
        assert alerts[0].event == "Real Alert"

    def test_fetch_weather_includes_alerts(self):
        """Full fetch_weather call includes alerts in the returned WeatherData."""
        from src.config import WeatherConfig
        from src.fetchers.weather import fetch_weather

        cfg = WeatherConfig(api_key="key", latitude=0.0, longitude=0.0)
        current_resp = MagicMock()
        current_resp.raise_for_status = MagicMock()
        current_resp.json.return_value = {
            "main": {"temp": 50.0, "temp_max": 55.0, "temp_min": 45.0, "humidity": 60},
            "weather": [{"icon": "01d", "description": "clear sky"}],
        }
        forecast_resp = MagicMock()
        forecast_resp.raise_for_status = MagicMock()
        forecast_resp.json.return_value = {"list": []}

        alert_resp = MagicMock()
        alert_resp.raise_for_status = MagicMock()
        alert_resp.json.return_value = {"alerts": [{"event": "Flood Watch"}]}

        session = MagicMock()
        session.get.side_effect = [current_resp, forecast_resp, alert_resp]
        with patch("src.fetchers.weather.requests.Session") as mock_session_cls:
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = fetch_weather(cfg)

        assert len(result.alerts) == 1
        assert result.alerts[0].event == "Flood Watch"


# ---------------------------------------------------------------------------
# Per-source cache (v2 format)
# ---------------------------------------------------------------------------


class TestPerSourceCache:
    def test_save_source_creates_v2_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                CalendarEvent(
                    summary="Evt", start=datetime(2024, 3, 15, 9), end=datetime(2024, 3, 15, 10)
                )
            ]
            save_source("events", events, datetime(2024, 3, 15, 8), tmpdir)
            cache_path = Path(tmpdir) / "dashboard_cache.json"
            assert cache_path.exists()
            with open(cache_path) as f:
                raw = json.load(f)
            assert raw["schema_version"] == 2
            assert "events" in raw
            assert raw["events"]["fetched_at"] == "2024-03-15T08:00:00"

    def test_load_cached_source_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                CalendarEvent(
                    summary="Evt", start=datetime(2024, 3, 15, 9), end=datetime(2024, 3, 15, 10)
                )
            ]
            ts = datetime(2024, 3, 15, 8)
            save_source("events", events, ts, tmpdir)
            result = load_cached_source("events", tmpdir)
            assert result is not None
            data, fetched_at = result
            assert len(data) == 1
            assert data[0].summary == "Evt"
            # Naive timestamps written to disk are normalised to UTC on read-back.
            assert fetched_at == ts.replace(tzinfo=timezone.utc)

    def test_load_cached_source_weather(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            weather = _make_weather(alerts=[WeatherAlert(event="Storm")])
            ts = datetime(2024, 3, 15, 9)
            save_source("weather", weather, ts, tmpdir)
            result = load_cached_source("weather", tmpdir)
            assert result is not None
            w, fetched_at = result
            assert w.current_temp == weather.current_temp
            assert len(w.alerts) == 1
            assert w.alerts[0].event == "Storm"

    def test_save_source_preserves_other_sources(self):
        """Saving one source should not wipe out other sources already in the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            weather = _make_weather()
            save_source("weather", weather, datetime(2024, 3, 15, 9), tmpdir)
            events = [
                CalendarEvent(
                    summary="Evt", start=datetime(2024, 3, 15, 9), end=datetime(2024, 3, 15, 10)
                )
            ]
            save_source("events", events, datetime(2024, 3, 15, 9, 30), tmpdir)

            w_result = load_cached_source("weather", tmpdir)
            e_result = load_cached_source("events", tmpdir)
            assert w_result is not None
            assert e_result is not None

    def test_load_cached_source_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert load_cached_source("events", tmpdir) is None

    def test_load_cached_source_v1_fallback(self):
        """load_cached_source should work with legacy v1 cache files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a v1 format cache manually
            v1 = {
                "fetched_at": "2024-03-15T08:00:00",
                "events": [
                    {
                        "summary": "Old Evt",
                        "start": "2024-03-15T09:00:00",
                        "end": "2024-03-15T10:00:00",
                        "is_all_day": False,
                        "location": None,
                        "calendar_name": None,
                    }
                ],
                "weather": None,
                "birthdays": [],
            }
            cache_path = Path(tmpdir) / "dashboard_cache.json"
            with open(cache_path, "w") as f:
                json.dump(v1, f)

            result = load_cached_source("events", tmpdir)
            assert result is not None
            data, fetched_at = result
            assert data[0].summary == "Old Evt"

    def test_save_cache_writes_v2_format(self):
        """save_cache (legacy full-dump API) should write v2 format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data = DashboardData(
                fetched_at=datetime(2024, 3, 15, 8),
                events=[],
                weather=_make_weather(),
                birthdays=[],
            )
            save_cache(data, tmpdir)
            with open(Path(tmpdir) / "dashboard_cache.json") as f:
                raw = json.load(f)
            assert raw["schema_version"] == 2

    def test_load_cached_reads_v2_format(self):
        """load_cached (legacy API) should correctly deserialise v2 files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", _make_weather(), datetime(2024, 3, 15, 9), tmpdir)
            result = load_cached(tmpdir)
            assert result is not None
            assert result.weather is not None

    def test_stale_sources_populated_on_partial_failure(self):
        """fetch_live_data should populate stale_sources for each failed source."""
        from src.config import Config
        from src.data_pipeline import DataPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-populate cache for weather (recent enough to be within TTL)
            from datetime import timedelta

            save_source(
                "weather",
                _make_weather(),
                datetime.now(timezone.utc) - timedelta(hours=3),
                tmpdir,
            )

            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", side_effect=RuntimeError("down")),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                data = DataPipeline(Config(), cache_dir=tmpdir).fetch()

        assert "weather" in data.stale_sources
        assert "events" not in data.stale_sources
        assert data.is_stale is True


# ---------------------------------------------------------------------------
# Incremental calendar sync
# ---------------------------------------------------------------------------


class TestIncrementalSync:
    def _make_service(self, result: dict):
        svc = MagicMock()
        svc.events().list().execute.return_value = result
        return svc

    def test_apply_delta_adds_new_event(self):
        """New events in delta are appended to the stored list."""
        stored = []
        new_item = {
            "id": "evt1",
            "summary": "New Meeting",
            "start": {"dateTime": "2024-03-15T09:00:00+00:00"},
            "end": {"dateTime": "2024-03-15T09:30:00+00:00"},
            "status": "confirmed",
        }
        merged = _apply_delta(stored, [new_item], "Cal")
        assert len(merged) == 1
        assert merged[0]["summary"] == "New Meeting"

    def test_apply_delta_removes_cancelled_event(self):
        """Cancelled events in delta are removed from the stored list."""
        stored_event = CalendarEvent(
            summary="To Delete",
            event_id="evt1",
            start=datetime(2024, 3, 15, 9),
            end=datetime(2024, 3, 15, 10),
        )
        stored = [_ser_sync_event(stored_event)]
        cancelled_item = {"id": "evt1", "status": "cancelled"}
        merged = _apply_delta(stored, [cancelled_item], "Cal")
        assert len(merged) == 0

    def test_apply_delta_updates_existing_event(self):
        """Updated events replace their previous version by event_id."""
        stored_event = CalendarEvent(
            summary="Old Title",
            event_id="evt1",
            start=datetime(2024, 3, 15, 9),
            end=datetime(2024, 3, 15, 10),
        )
        stored = [_ser_sync_event(stored_event)]
        updated_item = {
            "id": "evt1",
            "summary": "New Title",
            "start": {"dateTime": "2024-03-15T09:00:00+00:00"},
            "end": {"dateTime": "2024-03-15T10:00:00+00:00"},
            "status": "confirmed",
        }
        merged = _apply_delta(stored, [updated_item], "Cal")
        assert len(merged) == 1
        assert merged[0]["summary"] == "New Title"

    def test_apply_delta_preserves_events_without_id(self):
        """Events without an event_id (legacy) are left untouched."""
        stored = [
            {
                "summary": "No ID Event",
                "start": "2024-03-15T09:00:00",
                "end": "2024-03-15T10:00:00",
                "is_all_day": False,
            }
        ]
        merged = _apply_delta(stored, [], "Cal")
        assert len(merged) == 1

    def test_ser_deser_sync_event_roundtrip(self):
        event = CalendarEvent(
            summary="Roundtrip",
            start=datetime(2024, 3, 15, 9),
            end=datetime(2024, 3, 15, 10),
            location="Room A",
            calendar_name="Work",
            event_id="abc123",
        )
        d = _ser_sync_event(event)
        restored = _deser_sync_event(d)
        assert restored.summary == event.summary
        assert restored.location == event.location
        assert restored.event_id == event.event_id

    def test_filter_to_window_includes_events_in_range(self):
        week_start = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)  # Monday
        week_end = week_start + timedelta(days=7)

        event = CalendarEvent(
            summary="In Window",
            start=datetime(2024, 3, 13, 9),  # Wednesday, naive
            end=datetime(2024, 3, 13, 10),
            event_id="e1",
        )
        stored = [_ser_sync_event(event)]
        result = _filter_to_window(stored, week_start, week_end)
        assert len(result) == 1

    def test_filter_to_window_excludes_events_outside_range(self):
        week_start = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        week_end = week_start + timedelta(days=7)

        old_event = CalendarEvent(
            summary="Old",
            start=datetime(2024, 3, 1, 9),  # before window
            end=datetime(2024, 3, 1, 10),
            event_id="old",
        )
        stored = [_ser_sync_event(old_event)]
        result = _filter_to_window(stored, week_start, week_end)
        assert len(result) == 0

    def test_fetch_incremental_handles_410_gone(self):
        """HTTP 410 Gone should set needs_reset=True without raising."""
        from googleapiclient.errors import HttpError

        svc = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 410
        svc.events().list().execute.side_effect = HttpError(mock_resp, b"Gone")

        delta, cal_name, new_token, needs_reset = _fetch_incremental(svc, "primary", "bad-token")
        assert needs_reset is True
        assert delta == []

    def test_sync_state_persisted_across_calls(self):
        """Sync token is stored in the state file after a full fetch."""
        from src.fetchers.calendar import _load_sync_state, _save_sync_state

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"primary": {"sync_token": "tok123", "events": []}}
            _save_sync_state(state, tmpdir)
            loaded = _load_sync_state(tmpdir)
            assert loaded["primary"]["sync_token"] == "tok123"

    def test_load_sync_state_returns_empty_when_missing(self):
        from src.fetchers.calendar import _load_sync_state

        with tempfile.TemporaryDirectory() as tmpdir:
            result = _load_sync_state(tmpdir)
        assert result == {}
