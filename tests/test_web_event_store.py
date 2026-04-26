"""Tests for src/web/event_store.py

Covers: append_event (writes JSONL, creates dirs, swallows write errors),
read_recent_events (returns newest-first, respects limit, handles missing file,
handles corrupt lines, returns empty on read error).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.web.event_store import append_event, read_recent_events

_EVENT_FILE = "web_events.jsonl"


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------


class TestAppendEvent:
    def test_creates_file_on_first_write(self, tmp_path):
        append_event(str(tmp_path), "refresh", "Manual refresh triggered")
        assert (tmp_path / _EVENT_FILE).exists()

    def test_event_contains_required_fields(self, tmp_path):
        append_event(str(tmp_path), "refresh", "Test message", source="web")
        lines = (tmp_path / _EVENT_FILE).read_text().strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["kind"] == "refresh"
        assert payload["message"] == "Test message"
        assert "timestamp" in payload
        assert payload["details"] == {"source": "web"}

    def test_multiple_events_appended(self, tmp_path):
        append_event(str(tmp_path), "refresh", "First")
        append_event(str(tmp_path), "cache_clear", "Second")
        lines = (tmp_path / _EVENT_FILE).read_text().strip().splitlines()
        assert len(lines) == 2

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "state"
        append_event(str(nested), "test", "msg")
        assert (nested / _EVENT_FILE).exists()

    def test_details_empty_when_no_kwargs(self, tmp_path):
        append_event(str(tmp_path), "kind", "msg")
        payload = json.loads((tmp_path / _EVENT_FILE).read_text().strip())
        assert payload["details"] == {}

    def test_swallows_write_error(self, tmp_path, monkeypatch):
        # Patch open() inside the try/except so the write itself fails
        import builtins

        real_open = builtins.open

        def bad_open(path, *args, **kwargs):
            if "web_events.jsonl" in str(path):
                raise OSError("Simulated write failure")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", bad_open)
        # Should not raise — error is swallowed inside append_event
        append_event(str(tmp_path), "kind", "msg")

    def test_timestamp_is_utc_iso(self, tmp_path):
        append_event(str(tmp_path), "kind", "msg")
        payload = json.loads((tmp_path / _EVENT_FILE).read_text().strip())
        ts = payload["timestamp"]
        # ISO format with UTC offset (+00:00)
        assert "T" in ts
        assert ts.endswith("+00:00") or ts.endswith("Z")

    def test_extra_kwargs_in_details(self, tmp_path):
        append_event(str(tmp_path), "breaker_reset", "Reset calendar", source_name="calendar")
        payload = json.loads((tmp_path / _EVENT_FILE).read_text().strip())
        assert payload["details"]["source_name"] == "calendar"

    def test_concurrent_appends_produce_valid_jsonl(self, tmp_path):
        """Two threads writing 100 events each must produce 200 valid JSON lines.

        Without the module-level append lock, Python's buffered I/O can split
        a long write across two syscalls and let a second thread's bytes land
        inside the first thread's record — corrupting the JSONL.
        """
        import threading

        N = 100
        # A long details payload makes interleaving more likely if unlocked.
        long_detail = "x" * 4096

        def worker(thread_id: int) -> None:
            for i in range(N):
                append_event(
                    str(tmp_path),
                    "stress",
                    f"thread {thread_id} event {i}",
                    payload=long_detail,
                )

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        lines = (tmp_path / _EVENT_FILE).read_text().splitlines()
        assert len(lines) == 2 * N, f"expected {2 * N} lines, got {len(lines)}"
        # Every line must parse as JSON — interleaving would produce corrupt records.
        for line in lines:
            json.loads(line)


# ---------------------------------------------------------------------------
# read_recent_events
# ---------------------------------------------------------------------------


class TestReadRecentEvents:
    def _write_events(self, path: Path, count: int) -> None:
        for i in range(count):
            append_event(str(path.parent), "kind", f"Event {i}", index=i)

    def test_returns_empty_when_no_file(self, tmp_path):
        result = read_recent_events(str(tmp_path))
        assert result == []

    def test_returns_events_newest_first(self, tmp_path):
        for i in range(3):
            append_event(str(tmp_path), "kind", f"msg {i}")
        events = read_recent_events(str(tmp_path))
        messages = [e["message"] for e in events]
        # newest-first means last written comes first
        assert messages[0] == "msg 2"
        assert messages[-1] == "msg 0"

    def test_limit_respected(self, tmp_path):
        for i in range(10):
            append_event(str(tmp_path), "kind", f"msg {i}")
        events = read_recent_events(str(tmp_path), limit=3)
        assert len(events) == 3

    def test_default_limit_is_20(self, tmp_path):
        for i in range(25):
            append_event(str(tmp_path), "kind", f"msg {i}")
        events = read_recent_events(str(tmp_path))
        assert len(events) == 20

    def test_fewer_events_than_limit(self, tmp_path):
        for i in range(5):
            append_event(str(tmp_path), "kind", f"msg {i}")
        events = read_recent_events(str(tmp_path), limit=20)
        assert len(events) == 5

    def test_corrupt_lines_skipped(self, tmp_path):
        event_file = tmp_path / _EVENT_FILE
        event_file.write_text(
            '{"kind":"ok","message":"good","timestamp":"2024-01-01T00:00:00+00:00","details":{}}\n'
            "not json at all\n"
            '{"kind":"ok","message":"also good","timestamp":"2024-01-01T00:00:01+00:00","details":{}}\n'
        )
        events = read_recent_events(str(tmp_path))
        assert len(events) == 2
        assert all(e["kind"] == "ok" for e in events)

    def test_blank_lines_skipped(self, tmp_path):
        event_file = tmp_path / _EVENT_FILE
        event_file.write_text(
            "\n"
            '{"kind":"ok","message":"msg","timestamp":"2024-01-01T00:00:00+00:00","details":{}}\n'
            "\n\n"
        )
        events = read_recent_events(str(tmp_path))
        assert len(events) == 1

    def test_limit_1_returns_most_recent(self, tmp_path):
        for i in range(5):
            append_event(str(tmp_path), "kind", f"msg {i}")
        events = read_recent_events(str(tmp_path), limit=1)
        assert len(events) == 1
        assert events[0]["message"] == "msg 4"

    def test_returns_empty_when_file_unreadable(self, tmp_path, monkeypatch):
        """Outer Exception path: if open() blows up on an existing file, return []."""
        import builtins

        # Create the file so the existence check passes; then fail on open().
        (tmp_path / _EVENT_FILE).write_text(
            '{"kind":"k","message":"m","timestamp":"2024-01-01T00:00:00+00:00","details":{}}\n'
        )

        real_open = builtins.open

        def bad_open(path, *args, **kwargs):
            if _EVENT_FILE in str(path):
                raise OSError("Simulated read failure")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", bad_open)
        assert read_recent_events(str(tmp_path)) == []
