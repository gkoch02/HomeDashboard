"""Tests for concurrent cache write safety.

Verifies that the _cache_lock in cache.py prevents corruption when
multiple threads write to the cache simultaneously.
"""

import json
import threading
from datetime import datetime

from src.data.models import CalendarEvent, WeatherData
from src.fetchers.cache import load_cached_source, save_source


def _make_weather(temp: float) -> WeatherData:
    return WeatherData(
        current_temp=temp,
        current_icon="01d",
        current_description="clear",
        high=temp + 10,
        low=temp - 10,
        humidity=50,
    )


def _make_events(count: int) -> list[CalendarEvent]:
    return [
        CalendarEvent(
            summary=f"Event {i}",
            start=datetime(2024, 3, 15, 9, i),
            end=datetime(2024, 3, 15, 10, i),
        )
        for i in range(count)
    ]


class TestConcurrentCacheWrites:
    """Verify cache file integrity under concurrent writes."""

    def test_concurrent_writes_dont_corrupt(self, tmp_path):
        """Multiple threads writing different sources simultaneously
        should not produce a corrupt JSON file."""
        cache_dir = str(tmp_path)
        now = datetime(2024, 3, 15, 8, 0, 0)
        errors = []

        def write_weather():
            try:
                for i in range(20):
                    save_source("weather", _make_weather(60.0 + i), now, cache_dir)
            except Exception as e:
                errors.append(e)

        def write_events():
            try:
                for i in range(20):
                    save_source("events", _make_events(i + 1), now, cache_dir)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=write_weather)
        t2 = threading.Thread(target=write_events)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Concurrent writes raised errors: {errors}"

        # Both sources should be readable and intact
        weather_data = load_cached_source("weather", cache_dir)
        events_data = load_cached_source("events", cache_dir)
        assert weather_data is not None, "Weather cache should be readable"
        assert events_data is not None, "Events cache should be readable"

        weather, _ = weather_data
        events, _ = events_data
        assert isinstance(weather, WeatherData)
        assert isinstance(events, list)
        assert len(events) > 0

    def test_concurrent_reads_during_writes(self, tmp_path):
        """Reads should not fail while writes are in progress."""
        cache_dir = str(tmp_path)
        now = datetime(2024, 3, 15, 8, 0, 0)
        read_errors = []
        write_errors = []

        # Seed initial data
        save_source("weather", _make_weather(50.0), now, cache_dir)

        def writer():
            try:
                for i in range(30):
                    save_source("weather", _make_weather(50.0 + i), now, cache_dir)
            except Exception as e:
                write_errors.append(e)

        def reader():
            try:
                for _ in range(30):
                    result = load_cached_source("weather", cache_dir)
                    # Result can be None if we catch it between writes,
                    # but it should never be corrupt
                    if result is not None:
                        data, _ = result
                        assert isinstance(data, WeatherData)
            except Exception as e:
                read_errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not write_errors, f"Writer errors: {write_errors}"
        assert not read_errors, f"Reader errors: {read_errors}"


class TestCrossProcessCacheWrites:
    """The web UI clears entries from a separate process (#242).

    ``save_source`` is read-modify-write. Unlocked, a source the renderer had
    just refreshed could be resurrected from the web process's stale read, or
    one it had just saved silently dropped.
    """

    def test_a_source_written_by_another_process_survives(self, tmp_path):
        from src.fetchers.cache import save_source

        save_source("weather", None, datetime(2026, 4, 6, 10, 0), str(tmp_path))

        # Another process adds a source between our writes.
        path = tmp_path / "dashboard_cache.json"
        raw = json.loads(path.read_text())
        raw["birthdays"] = {"fetched_at": "2026-04-06T09:00:00", "data": []}
        path.write_text(json.dumps(raw))

        save_source("events", [], datetime(2026, 4, 6, 10, 5), str(tmp_path))

        merged = json.loads(path.read_text())
        assert set(merged) == {"schema_version", "weather", "birthdays", "events"}

    def test_a_clear_between_writes_is_not_undone(self, tmp_path):
        from src.fetchers.cache import save_source

        save_source("weather", None, datetime(2026, 4, 6, 10, 0), str(tmp_path))
        save_source("events", [], datetime(2026, 4, 6, 10, 0), str(tmp_path))

        # The web UI clears everything.
        path = tmp_path / "dashboard_cache.json"
        path.write_text(json.dumps({"schema_version": 2}))

        # The renderer's next write must add only its own source back.
        save_source("events", [], datetime(2026, 4, 6, 10, 5), str(tmp_path))

        merged = json.loads(path.read_text())
        assert set(merged) == {"schema_version", "events"}

    def test_save_source_goes_through_the_shared_locked_helper(self):
        from src import _io
        from src.fetchers import cache as cache_mod

        assert cache_mod.locked_update_json is _io.locked_update_json
