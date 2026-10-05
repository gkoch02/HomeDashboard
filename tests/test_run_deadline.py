"""The run's lifetime is bounded: one fetch deadline, and a clean exit on SIGTERM.

systemd ends a run past ``TimeoutStartSec=`` with SIGTERM. The process must then
leave even though a fetch thread is still stuck, after running the ``finally``
blocks that put the panel to sleep and writing ``output/last_error.txt``.
"""

import json
import signal
import subprocess
import sys
import textwrap
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.app import RunTerminated
from src.config import Config
from src.data_pipeline import DataPipeline

ROOT = Path(__file__).resolve().parents[1]


def _pipeline(tmp_path) -> DataPipeline:
    return DataPipeline(Config(), cache_dir=str(tmp_path))


class TestSharedFetchDeadline:
    def test_a_passed_deadline_does_not_wait(self, tmp_path):
        pipeline = _pipeline(tmp_path)
        pending = Future()  # never completes, like a hung fetch

        started = time.monotonic()
        with patch.object(pipeline, "_use_cache", return_value=None):
            result = pipeline._resolve_source(
                "weather", pending, "current", deadline=time.monotonic() - 1
            )

        assert result == "current"
        assert time.monotonic() - started < 1

    def test_every_source_shares_one_deadline(self, tmp_path):
        pipeline = _pipeline(tmp_path)
        seen = []

        def spy(source, future, current, success_log_fn=None, deadline=None):
            seen.append(deadline)
            return current

        with (
            patch.object(pipeline, "_launch_fetches", return_value={}),
            patch.object(pipeline, "_resolve_source", side_effect=spy),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
        ):
            pipeline.fetch()

        assert len(seen) > 1
        assert all(d is not None for d in seen)
        assert len(set(seen)) == 1


class TestRunTerminatedIsNotAFetchFailure:
    def test_resolve_source_lets_it_through(self, tmp_path):
        pipeline = _pipeline(tmp_path)
        future = MagicMock()
        future.result.side_effect = RunTerminated("stopped by signal 15")

        with pytest.raises(RunTerminated):
            pipeline._resolve_source("weather", future, None)

    def test_app_run_writes_the_error_marker(self, tmp_path):
        from src.app import DashboardApp

        cfg = Config()
        cfg.output_dir = str(tmp_path / "output")
        cfg.state_dir = str(tmp_path / "state")
        app = DashboardApp(cfg, MagicMock(dry_run=True))

        with (
            patch.object(app, "_run", side_effect=RunTerminated("stopped")),
            pytest.raises(RunTerminated),
        ):
            app.run()

        marker = json.loads((tmp_path / "output" / "last_error.txt").read_text())
        assert marker["exception_type"] == "RunTerminated"


_CHILD = textwrap.dedent(
    """
    import runpy, sys, threading
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import src.app

    out, mode = Path(sys.argv[1]), sys.argv[2]

    def hang():
        threading.Event().wait()

    def stuck_run(self):
        # A pool worker that never finishes, like a hung fetch: the pipeline
        # shuts the pool down with wait=False, and the interpreter would join
        # the worker forever at exit.
        pool = ThreadPoolExecutor(max_workers=1)
        pool.submit(hang)
        pool.shutdown(wait=False)
        if mode == "finished":
            return
        if mode == "raised":
            raise RuntimeError("render failed")
        try:
            (out / "ready").write_text("")
            hang()
        finally:
            (out / "cleanup_ran").write_text("yes")

    src.app.DashboardApp._run = stuck_run
    sys.argv = ["src.main", "--dry-run", "--dummy", "--config", str(out / "config.yaml")]
    runpy.run_module("src.main", run_name="__main__")
    """
)


def _start_child(tmp_path, mode: str) -> subprocess.Popen:
    (tmp_path / "config.yaml").write_text(
        yaml.dump(
            {
                "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
                "output": {"dry_run_dir": str(tmp_path / "output")},
                "state_dir": str(tmp_path / "state"),
            }
        )
    )
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(tmp_path), mode],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _finish(proc: subprocess.Popen) -> tuple[int, str]:
    try:
        output, _ = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return proc.returncode, output


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_ends_a_run_held_open_by_a_stuck_thread(tmp_path):
    proc = _start_child(tmp_path, "blocked")
    deadline = time.monotonic() + 20
    while not (tmp_path / "ready").exists():
        if proc.poll() is not None or time.monotonic() > deadline:
            proc.kill()
            pytest.fail(f"child never got ready: {proc.communicate()[0]}")
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)

    returncode, output = _finish(proc)

    assert returncode == 128 + signal.SIGTERM, output
    assert (tmp_path / "cleanup_ran").read_text() == "yes"
    marker = json.loads((tmp_path / "output" / "last_error.txt").read_text())
    assert marker["exception_type"] == "RunTerminated"


@pytest.mark.parametrize(("mode", "expected"), [("finished", 0), ("raised", 1)])
def test_a_run_that_ends_does_not_wait_for_a_stuck_thread(tmp_path, mode, expected):
    returncode, output = _finish(_start_child(tmp_path, mode))

    assert returncode == expected, output
    assert "Exiting without waiting for stuck threads" in output
    if mode == "raised":
        assert "RuntimeError: render failed" in output
