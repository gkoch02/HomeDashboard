"""End-to-end integration tests for DataPipeline.

Exercises the full fetch → cache → resolve flow with mocked fetchers
to verify thread pool coordination, cache fallback, and circuit breaker
interaction work together correctly.
"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config, PurpleAirConfig
from src.data.models import (
    Birthday,
    CalendarEvent,
    StalenessLevel,
    WeatherData,
)
from src.data_pipeline import DataPipeline, retry_fetch


def _make_weather():
    return WeatherData(
        current_temp=68.0,
        current_icon="01d",
        current_description="clear",
        high=75.0,
        low=55.0,
        humidity=40,
    )


def _make_events():
    return [
        CalendarEvent(
            summary="Meeting",
            start=datetime(2024, 3, 15, 10, 0),
            end=datetime(2024, 3, 15, 11, 0),
        )
    ]


def _make_birthdays():
    from datetime import date

    return [Birthday(name="Alice", date=date(2024, 3, 20), age=30)]


def _make_pipeline(tmp_path, **kwargs):
    cfg = Config()
    cfg.purpleair = PurpleAirConfig(api_key="", sensor_id=0)
    return DataPipeline(cfg, cache_dir=str(tmp_path), **kwargs)


class TestDataPipelineE2E:
    """Integration tests exercising the full fetch → resolve pipeline."""

    def test_successful_fetch_all_sources(self, tmp_path):
        """All sources fetch successfully → DashboardData has fresh data."""
        pipeline = _make_pipeline(tmp_path, force_refresh=True)
        events = _make_events()
        weather = _make_weather()
        birthdays = _make_birthdays()

        with (
            patch("src.data_pipeline.fetch_events", return_value=events),
            patch("src.data_pipeline.fetch_weather", return_value=weather),
            patch("src.data_pipeline.fetch_birthdays", return_value=birthdays),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline.fetch()

        assert len(data.events) == 1
        assert data.weather is not None
        assert data.weather.current_temp == 68.0
        assert len(data.birthdays) == 1
        assert not data.is_stale
        assert data.source_staleness.get("events") == StalenessLevel.FRESH
        assert data.source_staleness.get("weather") == StalenessLevel.FRESH
        assert data.source_staleness.get("birthdays") == StalenessLevel.FRESH

    def test_content_at_is_the_fetch_time_on_a_live_fetch(self, tmp_path):
        pipeline = _make_pipeline(tmp_path, force_refresh=True)
        with (
            patch("src.data_pipeline.fetch_events", return_value=_make_events()),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=_make_birthdays()),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline.fetch()

        assert data.content_at == pipeline.fetched_at

    def test_content_at_stays_put_when_every_source_comes_from_cache(self, tmp_path):
        """The whole point: a run that fetched nothing must not advance it.

        `fetched_at` is a render clock and moves every run. If a caption read
        that, the rendered image would differ on every tick and force a panel
        write for content that has not changed.
        """
        first = _make_pipeline(tmp_path, force_refresh=True)
        with (
            patch("src.data_pipeline.fetch_events", return_value=_make_events()),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=_make_birthdays()),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            first_data = first.fetch()

        # Second run a few minutes later: every source is within its interval,
        # so nothing is fetched and the cache is served.
        second = _make_pipeline(tmp_path)
        with patch("src.data_pipeline.fetch_host_data", return_value=None):
            second_data = second.fetch()

        assert second.fetched_at > first.fetched_at, "render clock should advance"
        assert second_data.content_at == first_data.content_at

    def test_content_at_is_the_newest_source_timestamp(self, tmp_path):
        # Populate the cache, then re-fetch only weather: content_at should
        # track the newer weather fetch, not the older cached calendar.
        first = _make_pipeline(tmp_path, force_refresh=True)
        with (
            patch("src.data_pipeline.fetch_events", return_value=_make_events()),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=_make_birthdays()),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            first_data = first.fetch()

        second = _make_pipeline(tmp_path)
        second.interval_map["weather"] = 0  # weather is due again
        with (
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            second_data = second.fetch()

        assert second_data.content_at == second.fetched_at
        assert second_data.content_at > first_data.content_at

    def test_content_at_is_none_without_any_source(self, tmp_path):
        cfg = Config()
        cfg.purpleair = PurpleAirConfig(api_key="", sensor_id=0)
        cfg.google.calendar_ids = []
        pipeline = DataPipeline(cfg, cache_dir=str(tmp_path), force_refresh=True)
        with (
            patch("src.data_pipeline.fetch_events", side_effect=RuntimeError("no calendar")),
            patch("src.data_pipeline.fetch_weather", side_effect=RuntimeError("no key")),
            patch("src.data_pipeline.fetch_birthdays", side_effect=RuntimeError("no creds")),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline.fetch()

        assert data.content_at is None

    def test_fetch_failure_falls_back_to_cache(self, tmp_path):
        """When a fetcher fails, pipeline falls back to cached data."""
        # First run: populate cache
        pipeline1 = _make_pipeline(tmp_path, force_refresh=True)
        events = _make_events()
        weather = _make_weather()
        birthdays = _make_birthdays()

        with (
            patch("src.data_pipeline.fetch_events", return_value=events),
            patch("src.data_pipeline.fetch_weather", return_value=weather),
            patch("src.data_pipeline.fetch_birthdays", return_value=birthdays),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            pipeline1.fetch()

        # Second run: weather fails → should use cached weather
        pipeline2 = _make_pipeline(tmp_path, force_refresh=True)

        with (
            patch("src.data_pipeline.fetch_events", return_value=events),
            patch("src.data_pipeline.fetch_weather", side_effect=ConnectionError("timeout")),
            patch("src.data_pipeline.fetch_birthdays", return_value=birthdays),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline2.fetch()

        # Weather should still be available from cache
        assert data.weather is not None
        assert data.weather.current_temp == 68.0
        assert data.is_stale

    def test_calendar_network_failure_preserves_cache(self, tmp_path):
        """Regression for issue #145: when the Google Calendar fetch raises
        (e.g. DNS/auth/network failure), previously-cached events must be
        returned — NOT overwritten with an empty list that blanks the
        rendered calendar panel."""
        # First run populates the cache with real events.
        events = _make_events()
        weather = _make_weather()
        birthdays = _make_birthdays()

        pipeline1 = _make_pipeline(tmp_path, force_refresh=True)
        with (
            patch("src.data_pipeline.fetch_events", return_value=events),
            patch("src.data_pipeline.fetch_weather", return_value=weather),
            patch("src.data_pipeline.fetch_birthdays", return_value=birthdays),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            pipeline1.fetch()

        # Second run: calendar fetch raises a DNS-style error (as would happen
        # when oauth2.googleapis.com is unreachable).
        pipeline2 = _make_pipeline(tmp_path, force_refresh=True)
        with (
            patch(
                "src.data_pipeline.fetch_events",
                side_effect=OSError("Unable to find the server at oauth2.googleapis.com"),
            ),
            patch("src.data_pipeline.fetch_weather", return_value=weather),
            patch("src.data_pipeline.fetch_birthdays", return_value=birthdays),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline2.fetch()

        # Cached events preserved, not clobbered with [].
        assert len(data.events) == 1
        assert data.events[0].summary == "Meeting"
        assert data.is_stale
        # events is listed among the stale sources so the UI surfaces it
        # (the staleness level itself depends on cache age; the contract we
        # care about is that the fallback path fired at all).
        assert "events" in data.stale_sources
        assert data.source_staleness.get("events") != StalenessLevel.EXPIRED

    def test_birthday_network_failure_preserves_cache(self, tmp_path):
        """Regression for issue #146: when the birthday fetch raises
        (e.g. DNS/auth/network failure in the calendar or contacts path),
        previously-cached birthdays must be returned — NOT overwritten with
        an empty list that blanks the birthday panel on the dashboard."""
        events = _make_events()
        weather = _make_weather()
        birthdays = _make_birthdays()

        # First run populates the cache with a known birthday list.
        pipeline1 = _make_pipeline(tmp_path, force_refresh=True)
        with (
            patch("src.data_pipeline.fetch_events", return_value=events),
            patch("src.data_pipeline.fetch_weather", return_value=weather),
            patch("src.data_pipeline.fetch_birthdays", return_value=birthdays),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            pipeline1.fetch()

        # Second run: birthday fetch raises a DNS-style error.
        pipeline2 = _make_pipeline(tmp_path, force_refresh=True)
        with (
            patch("src.data_pipeline.fetch_events", return_value=events),
            patch("src.data_pipeline.fetch_weather", return_value=weather),
            patch(
                "src.data_pipeline.fetch_birthdays",
                side_effect=OSError("Unable to find the server at oauth2.googleapis.com"),
            ),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline2.fetch()

        # Cached birthdays preserved, not clobbered with [].
        assert len(data.birthdays) == 1
        assert data.birthdays[0].name == "Alice"
        assert data.is_stale
        assert "birthdays" in data.stale_sources
        assert data.source_staleness.get("birthdays") != StalenessLevel.EXPIRED

    def test_all_sources_fail_no_cache(self, tmp_path):
        """When all fetchers fail and no cache exists, returns empty data."""
        pipeline = _make_pipeline(tmp_path, force_refresh=True)

        with (
            patch("src.data_pipeline.fetch_events", side_effect=ConnectionError("fail")),
            patch("src.data_pipeline.fetch_weather", side_effect=ConnectionError("fail")),
            patch("src.data_pipeline.fetch_birthdays", side_effect=ConnectionError("fail")),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline.fetch()

        assert data.events == []
        assert data.weather is None
        assert data.birthdays == []

    def test_skip_when_cache_is_recent(self, tmp_path):
        """When cache is recent, fetchers are not called."""
        # Populate cache
        pipeline1 = _make_pipeline(tmp_path, force_refresh=True)
        events = _make_events()
        weather = _make_weather()
        birthdays = _make_birthdays()

        with (
            patch("src.data_pipeline.fetch_events", return_value=events),
            patch("src.data_pipeline.fetch_weather", return_value=weather),
            patch("src.data_pipeline.fetch_birthdays", return_value=birthdays),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            pipeline1.fetch()

        # Second run: cache is fresh, no force_refresh
        pipeline2 = _make_pipeline(tmp_path, force_refresh=False)
        mock_events = MagicMock()
        mock_weather = MagicMock()

        with (
            patch("src.data_pipeline.fetch_events", mock_events),
            patch("src.data_pipeline.fetch_weather", mock_weather),
            patch("src.data_pipeline.fetch_birthdays", MagicMock()),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline2.fetch()

        # Fetchers should not have been called
        mock_events.assert_not_called()
        mock_weather.assert_not_called()
        # But data should still be present from cache
        assert len(data.events) == 1
        assert data.weather is not None

    def test_events_refetch_when_requested_window_changes(self, tmp_path):
        """A recent events cache should not be reused across window changes."""
        pipeline1 = _make_pipeline(
            tmp_path,
            force_refresh=True,
            event_window_start=date(2026, 4, 6),
            event_window_days=7,
        )
        weekly_events = _make_events()

        with (
            patch("src.data_pipeline.fetch_events", return_value=weekly_events),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=_make_birthdays()),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            pipeline1.fetch()

        monthly_events = [
            CalendarEvent(
                summary="Monthly",
                start=datetime(2026, 4, 20, 10, 0),
                end=datetime(2026, 4, 20, 11, 0),
            )
        ]
        pipeline2 = _make_pipeline(
            tmp_path,
            force_refresh=False,
            event_window_start=date(2026, 3, 29),
            event_window_days=35,
        )

        with (
            patch("src.data_pipeline.fetch_events", return_value=monthly_events) as mock_events,
            patch("src.data_pipeline.fetch_weather", MagicMock()),
            patch("src.data_pipeline.fetch_birthdays", MagicMock()),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            data = pipeline2.fetch()

        mock_events.assert_called_once()
        assert [event.summary for event in data.events] == ["Monthly"]


class TestRetryFetch:
    """Tests for the retry_fetch helper."""

    def test_succeeds_first_try(self):
        result = retry_fetch("test", lambda: 42)
        assert result == 42

    def test_retries_on_transient_failure(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionError("transient")
            return "ok"

        result = retry_fetch("test", flaky)
        assert result == "ok"
        assert len(calls) == 2

    def test_no_retry_on_runtime_error(self):
        with pytest.raises(RuntimeError, match="permanent"):
            retry_fetch("test", lambda: (_ for _ in ()).throw(RuntimeError("permanent")))

    def test_no_retry_on_value_error(self):
        with pytest.raises(ValueError):
            retry_fetch("test", lambda: (_ for _ in ()).throw(ValueError("bad")))

    def test_retry_failure_raises(self):
        """When retry also fails, the exception from the retry is raised."""

        def always_fail():
            raise ConnectionError("network down")

        with pytest.raises(ConnectionError, match="network down"):
            retry_fetch("test", always_fail)


class TestCalendarOutageKeepsTheCache:
    """The behaviour #234 was really about, verified through the pipeline.

    The backend-level tests prove an unreachable feed now raises; these prove
    what that buys — the last complete calendar survives the outage and is
    flagged stale, instead of being overwritten by an empty one.
    """

    def _run(self, tmp_path, events_result):
        """Run one pipeline pass with *events_result* as the events outcome."""
        kwargs = (
            {"side_effect": events_result}
            if isinstance(events_result, Exception)
            else {"return_value": events_result}
        )
        with (
            patch("src.data_pipeline.fetch_events", **kwargs),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=[]),
        ):
            cfg = Config()
            cfg.purpleair = PurpleAirConfig(api_key="", sensor_id=0)
            cfg.cache.events_fetch_interval = 0
            return DataPipeline(cfg, cache_dir=str(tmp_path)).fetch()

    def test_outage_serves_the_cached_calendar_and_flags_it(self, tmp_path):
        from src.fetchers.errors import CalendarFetchError

        first = self._run(tmp_path, _make_events())
        assert [e.summary for e in first.events] == ["Meeting"]

        during_outage = self._run(tmp_path, CalendarFetchError("all feeds down"))

        # The panel still shows the meeting, and says the data is not live.
        assert [e.summary for e in during_outage.events] == ["Meeting"]
        assert "events" in during_outage.stale_sources
        assert during_outage.is_stale

    def test_outage_does_not_overwrite_the_cached_calendar(self, tmp_path):
        import json

        from src.fetchers.errors import CalendarFetchError

        self._run(tmp_path, _make_events())
        self._run(tmp_path, CalendarFetchError("all feeds down"))

        cached = json.loads((tmp_path / "dashboard_cache.json").read_text())
        assert [e["summary"] for e in cached["events"]["data"]] == ["Meeting"]

    def test_outage_counts_against_the_breaker(self, tmp_path):
        import json

        from src.fetchers.errors import CalendarFetchError

        self._run(tmp_path, _make_events())
        self._run(tmp_path, CalendarFetchError("all feeds down"))

        breakers = json.loads((tmp_path / "dashboard_breaker_state.json").read_text())
        # Recorded as a failure, not the success an empty-list return looked like.
        assert breakers["events"]["consecutive_failures"] >= 1

    def test_a_genuinely_empty_week_is_still_cached_as_empty(self, tmp_path):
        """The fix must not turn "no events this week" into an error — only a
        failed *fetch* is a failure."""
        import json

        self._run(tmp_path, _make_events())
        empty = self._run(tmp_path, [])

        assert empty.events == []
        assert "events" not in empty.stale_sources
        cached = json.loads((tmp_path / "dashboard_cache.json").read_text())
        assert cached["events"]["data"] == []

    def test_real_ics_outage_end_to_end_keeps_the_cache(self, tmp_path):
        """The whole #234 chain with nothing mocked but the HTTP call.

        The sibling tests above patch `fetch_events` and so only guard the
        pipeline half. This one drives the real ICS backend, so it fails if
        either half regresses: the feed returning [] on an outage, or the
        pipeline caching a failure as fresh.
        """
        import json

        monday = date.today() - timedelta(days=date.today().weekday())
        feed = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Home\r\n"
            "BEGIN:VEVENT\r\n"
            f"DTSTART:{(monday + timedelta(days=1)).strftime('%Y%m%d')}T120000Z\r\n"
            f"DTEND:{(monday + timedelta(days=1)).strftime('%Y%m%d')}T130000Z\r\n"
            "SUMMARY:Dentist\r\nUID:dentist-1\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )

        def _response(text, status=200):
            resp = MagicMock()
            resp.text = text
            resp.status_code = status
            if status >= 400:
                resp.raise_for_status.side_effect = Exception(f"{status} Server Error")
            else:
                resp.raise_for_status.return_value = None
            return resp

        def _run(response):
            cfg = Config()
            cfg.purpleair = PurpleAirConfig(api_key="", sensor_id=0)
            cfg.google.ical_url = "https://example.com/home.ics"
            cfg.cache.events_fetch_interval = 0
            with (
                patch("src.fetchers.calendar_ical.requests.get", return_value=response),
                patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                return DataPipeline(cfg, cache_dir=str(tmp_path)).fetch()

        live = _run(_response(feed))
        assert [e.summary for e in live.events] == ["Dentist"]

        outage = _run(_response("", status=500))

        assert [e.summary for e in outage.events] == ["Dentist"], (
            "the feed went down and the calendar went blank"
        )
        assert "events" in outage.stale_sources
        cached = json.loads((tmp_path / "dashboard_cache.json").read_text())
        assert [e["summary"] for e in cached["events"]["data"]] == ["Dentist"], (
            "the outage overwrote the good cache"
        )
