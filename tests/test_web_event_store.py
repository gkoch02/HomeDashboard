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


# ---------------------------------------------------------------------------
# Bounded growth (#218)
# ---------------------------------------------------------------------------


class TestTrimming:
    """Renderer runs land here now, so the stream needs a ceiling."""

    def _fill(self, tmp_path, count: int) -> None:
        from src.web.event_store import _EVENT_FILE

        path = tmp_path / _EVENT_FILE
        path.write_text(
            "".join(
                json.dumps({"timestamp": "2026-08-19T00:00:00+00:00", "kind": "old", "n": i}) + "\n"
                for i in range(count)
            )
        )

    def test_small_streams_are_left_alone(self, tmp_path):
        from src.web.event_store import _EVENT_FILE, append_event

        self._fill(tmp_path, 10)
        append_event(str(tmp_path), "run_completed", "fresh")
        assert len((tmp_path / _EVENT_FILE).read_text().splitlines()) == 11

    def _fill_oversized(self, tmp_path) -> Path:
        """Write more records than the keep count, past the byte threshold."""
        from src.web.event_store import _EVENT_FILE, _KEEP_EVENTS

        path = tmp_path / _EVENT_FILE
        path.write_text(
            "".join(
                json.dumps({"kind": "old", "n": i, "pad": "x" * 1000}) + "\n"
                for i in range(_KEEP_EVENTS + 200)
            )
        )
        return path

    def test_oversized_stream_is_trimmed(self, tmp_path):
        from src.web.event_store import _KEEP_EVENTS, append_event

        path = self._fill_oversized(tmp_path)
        append_event(str(tmp_path), "run_completed", "fresh")

        assert len(path.read_text().splitlines()) == _KEEP_EVENTS + 1

    def test_trimming_keeps_the_newest_records(self, tmp_path):
        from src.web.event_store import _KEEP_EVENTS, append_event, read_recent_events

        self._fill_oversized(tmp_path)
        append_event(str(tmp_path), "run_completed", "newest")

        rows = read_recent_events(str(tmp_path), limit=5)
        assert rows[0]["message"] == "newest"
        assert rows[1]["n"] == _KEEP_EVENTS + 199

    def test_trimming_drops_the_oldest_records(self, tmp_path):
        from src.web.event_store import _KEEP_EVENTS, append_event, read_recent_events

        self._fill_oversized(tmp_path)
        append_event(str(tmp_path), "run_completed", "newest")

        kept = {r.get("n") for r in read_recent_events(str(tmp_path), limit=_KEEP_EVENTS + 10)}
        assert 0 not in kept
        assert 199 not in kept

    def test_trimming_leaves_no_tempfile_behind(self, tmp_path):
        from src.web.event_store import _EVENT_FILE, append_event

        self._fill_oversized(tmp_path)
        append_event(str(tmp_path), "run_completed", "fresh")

        names = {p.name for p in tmp_path.iterdir()}
        assert _EVENT_FILE in names
        assert not any(n.endswith(".tmp") for n in names)
        # The advisory-lock sidecar is the only other file allowed here.
        assert names <= {_EVENT_FILE, _EVENT_FILE + ".lock"}

    def test_repeated_appends_stay_bounded(self, tmp_path):
        from src.web.event_store import _EVENT_FILE, _TRIM_THRESHOLD_BYTES, append_event

        path = tmp_path / _EVENT_FILE
        for i in range(50):
            append_event(str(tmp_path), "run_completed", "x" * 2000, n=i)
        # A few appends can land between trims; the point is it never runs away.
        assert path.stat().st_size < _TRIM_THRESHOLD_BYTES * 2

    def test_a_missing_file_is_not_a_trim_error(self, tmp_path):
        from src.web.event_store import append_event, read_recent_events

        append_event(str(tmp_path / "fresh"), "run_completed", "first")
        assert len(read_recent_events(str(tmp_path / "fresh"))) == 1


class TestCrossProcessSafety:
    """Since #218 the stream has two writers: the web service and the renderer."""

    def test_trim_does_not_drop_a_concurrent_append(self, tmp_path):
        """The read-all → rename window used to swallow the other writer's records."""
        import subprocess
        import sys

        from src.web.event_store import _EVENT_FILE, _KEEP_EVENTS, read_recent_events

        path = tmp_path / _EVENT_FILE
        path.write_text(
            "".join(
                json.dumps({"kind": "old", "n": i, "pad": "x" * 1000}) + "\n"
                for i in range(_KEEP_EVENTS + 200)
            )
        )

        repo = Path(__file__).resolve().parent.parent
        code = (
            f"import sys; sys.path.insert(0, {str(repo)!r});"
            "from src.web.event_store import append_event;"
            f"append_event({str(tmp_path)!r}, 'run_completed', 'from-the-renderer')"
        )

        # Two processes appending (and therefore trimming) the same stream.
        procs = [subprocess.Popen([sys.executable, "-c", code], cwd=str(repo)) for _ in range(4)]
        for proc in procs:
            assert proc.wait(timeout=60) == 0

        messages = [
            r.get("message") for r in read_recent_events(str(tmp_path), limit=_KEEP_EVENTS + 10)
        ]
        assert messages.count("from-the-renderer") == 4

    def test_every_line_stays_valid_json_under_concurrency(self, tmp_path):
        import subprocess
        import sys

        from src.web.event_store import _EVENT_FILE

        repo = Path(__file__).resolve().parent.parent
        code = (
            f"import sys; sys.path.insert(0, {str(repo)!r});"
            "from src.web.event_store import append_event;"
            f"[append_event({str(tmp_path)!r}, 'run_completed', 'x' * 300, n=i) "
            "for i in range(20)]"
        )

        procs = [subprocess.Popen([sys.executable, "-c", code], cwd=str(repo)) for _ in range(4)]
        for proc in procs:
            assert proc.wait(timeout=60) == 0

        lines = (tmp_path / _EVENT_FILE).read_text().splitlines()
        assert len(lines) == 80
        for line in lines:
            json.loads(line)  # must not raise

    def test_a_unique_tempfile_is_used_per_trim(self, tmp_path, monkeypatch):
        """A fixed .tmp name lets two trimming processes rename each other's half-file."""
        import src.web.event_store as es

        seen: list[str] = []
        real_mkstemp = es.tempfile.mkstemp

        def _spy(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            seen.append(name)
            return fd, name

        monkeypatch.setattr(es.tempfile, "mkstemp", _spy)

        for _ in range(2):
            (tmp_path / es._EVENT_FILE).write_text(
                "".join(
                    json.dumps({"kind": "old", "n": i, "pad": "x" * 1000}) + "\n"
                    for i in range(es._KEEP_EVENTS + 200)
                )
            )
            es.append_event(str(tmp_path), "run_completed", "fresh")

        assert len(seen) == 2
        assert seen[0] != seen[1]

    def test_append_still_works_without_fcntl(self, tmp_path, monkeypatch):
        """Non-POSIX degrades to the in-process lock rather than failing."""
        import src.web.event_store as es

        monkeypatch.setattr(es, "fcntl", None)
        es.append_event(str(tmp_path), "run_completed", "no fcntl here")

        assert es.read_recent_events(str(tmp_path))[0]["message"] == "no fcntl here"

    def test_an_unwritable_lock_path_does_not_break_the_append(self, tmp_path, monkeypatch):
        import builtins

        import src.web.event_store as es

        real_open = builtins.open

        def _fail_lock(path, *args, **kwargs):
            if str(path).endswith(es._LOCK_SUFFIX):
                raise OSError("read-only filesystem")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _fail_lock)
        es.append_event(str(tmp_path), "run_completed", "still recorded")
        monkeypatch.undo()

        assert es.read_recent_events(str(tmp_path))[0]["message"] == "still recorded"


# ---------------------------------------------------------------------------
# Cross-process safety
# ---------------------------------------------------------------------------


def _append_burst(state_dir: str, tag: str, count: int, payload: str = "") -> None:
    """Module-level so it is picklable by multiprocessing's spawn start method."""
    from src.web.event_store import append_event

    for i in range(count):
        append_event(state_dir, "run_completed", f"{tag}-{i}", filler=payload)


class TestCrossProcessAppends:
    """The stream has two writers in production and they are separate processes.

    Since #218 the renderer records run events here alongside the long-running
    web service. The module-level ``threading.Lock`` orders writers inside one
    process; only the ``fcntl`` sidecar lock orders them across two. These
    tests exercise the real thing with real processes — the existing coverage
    only tests the *fallback* taken when ``fcntl`` is unavailable.
    """

    @staticmethod
    def _run(procs):
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        for p in procs:
            assert p.exitcode == 0, f"worker failed with exit code {p.exitcode}"

    def test_concurrent_appends_lose_no_records(self, tmp_path):
        import multiprocessing as mp

        ctx = mp.get_context("spawn")
        per_proc = 40
        writers = 4
        self._run(
            [
                ctx.Process(target=_append_burst, args=(str(tmp_path), f"p{n}", per_proc))
                for n in range(writers)
            ]
        )

        lines = (tmp_path / _EVENT_FILE).read_text().splitlines()
        assert len(lines) == writers * per_proc

    def test_concurrent_appends_produce_no_torn_lines(self, tmp_path):
        """Every line must still parse as JSON.

        Python's buffered I/O can split one record across several write()
        syscalls, so without the lock two processes can interleave bytes inside
        a single record. A long filler payload makes that far more likely.
        """
        import multiprocessing as mp

        ctx = mp.get_context("spawn")
        filler = "x" * 4096
        self._run(
            [
                ctx.Process(target=_append_burst, args=(str(tmp_path), f"p{n}", 30, filler))
                for n in range(4)
            ]
        )

        lines = (tmp_path / _EVENT_FILE).read_text().splitlines()
        assert len(lines) == 120
        for line in lines:
            record = json.loads(line)  # raises on a torn record
            assert record["details"]["filler"] == filler

    def test_appends_during_a_trim_are_not_dropped(self, tmp_path, monkeypatch):
        """The trim is read-all → tempfile → rename.

        Anything another process appends inside that window is lost to the
        rename unless the lock covers the whole critical section. Seed the
        stream past the trim threshold so every worker's first append triggers
        a trim, then assert the newest records all survived.
        """
        import multiprocessing as mp

        import src.web.event_store as es

        seed = (
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "kind": "seed",
                    "message": "x" * 512,
                    "details": {},
                }
            )
            + "\n"
        )
        target = es._TRIM_THRESHOLD_BYTES // len(seed) + 50
        (tmp_path / _EVENT_FILE).write_text(seed * target)
        assert (tmp_path / _EVENT_FILE).stat().st_size > es._TRIM_THRESHOLD_BYTES

        ctx = mp.get_context("spawn")
        per_proc = 20
        writers = 3
        self._run(
            [
                ctx.Process(target=_append_burst, args=(str(tmp_path), f"p{n}", per_proc))
                for n in range(writers)
            ]
        )

        lines = (tmp_path / _EVENT_FILE).read_text().splitlines()
        # The trim caps the stream: it keeps the newest _KEEP_EVENTS and each
        # append that follows a trim adds one more on top.
        assert len(lines) <= es._KEEP_EVENTS + writers * per_proc
        records = [json.loads(line) for line in lines]
        seeds = sum(1 for r in records if r["kind"] == "seed")
        assert seeds < target, "the trim must actually have dropped old records"
        # No writer's records may be swallowed by another writer's rename.
        messages = {r["message"] for r in records}
        for n in range(writers):
            for i in range(per_proc):
                assert f"p{n}-{i}" in messages

    def test_trim_leaves_no_temp_files_behind(self, tmp_path):
        """Two processes trimming at once must not orphan their tempfiles."""
        import multiprocessing as mp

        import src.web.event_store as es

        seed = (
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "kind": "seed",
                    "message": "x" * 512,
                    "details": {},
                }
            )
            + "\n"
        )
        target = es._TRIM_THRESHOLD_BYTES // len(seed) + 50
        (tmp_path / _EVENT_FILE).write_text(seed * target)

        ctx = mp.get_context("spawn")
        self._run(
            [ctx.Process(target=_append_burst, args=(str(tmp_path), f"p{n}", 10)) for n in range(3)]
        )

        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []


class TestTrimFailureHandling:
    def test_failed_rename_cleans_up_and_does_not_break_the_append(self, tmp_path, monkeypatch):
        """A stream that cannot be trimmed is still a stream that logs.

        The trim re-raises so the caller can log it; the temp file must not be
        left behind either way.
        """
        import src.web.event_store as es

        seed = (
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "kind": "seed",
                    "message": "x" * 512,
                    "details": {},
                }
            )
            + "\n"
        )
        target = es._TRIM_THRESHOLD_BYTES // len(seed) + 50
        path = tmp_path / _EVENT_FILE
        path.write_text(seed * target)

        def _boom(*args, **kwargs):
            raise OSError("rename failed")

        monkeypatch.setattr(es.os, "replace", _boom)
        append_event(str(tmp_path), "run_completed", "trim exploded")  # must not raise

        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == [], "a failed trim must not orphan its temp file"
