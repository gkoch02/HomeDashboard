"""Tests for the cross-process JSON locking helpers in src/_io.py (#242).

``atomic_write_json`` makes each write atomic, which prevents a torn file but
says nothing about interleaving. Several state files have two writers in two
processes — the long-running web service and the short-lived renderer — so the
lock has to cover the whole read-modify-write.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import subprocess
import sys
from pathlib import Path

import pytest

import src._io as io_
from src._io import atomic_write_json, file_lock, locked_update_json, read_json

REPO = Path(__file__).resolve().parent.parent


class TestReadJson:
    def test_missing_file_returns_default(self, tmp_path):
        assert read_json(tmp_path / "nope.json", default={"a": 1}) == {"a": 1}

    def test_corrupt_file_returns_default(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{not json")
        assert read_json(path, default={}) == {}

    def test_reads_existing_content(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"weather": "ok"}))
        assert read_json(path) == {"weather": "ok"}


class TestLockedUpdateJson:
    def test_creates_the_file_from_the_default(self, tmp_path):
        path = tmp_path / "state.json"

        def add(raw):
            raw["events"] = 1
            return raw

        assert locked_update_json(path, add, default={}) == {"events": 1}
        assert json.loads(path.read_text()) == {"events": 1}

    def test_preserves_keys_the_mutator_does_not_touch(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"weather": "keep", "events": "replace"}))

        def touch_events(raw):
            raw["events"] = "new"
            return raw

        locked_update_json(path, touch_events, default={})
        assert json.loads(path.read_text()) == {"weather": "keep", "events": "new"}

    def test_returning_none_writes_nothing(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"a": 1}))
        assert locked_update_json(path, lambda raw: None, default={}) is None
        assert json.loads(path.read_text()) == {"a": 1}

    def test_default_is_not_shared_between_calls(self, tmp_path):
        """A mutated default would leak into the next caller's starting state."""
        default: dict = {}

        def add(raw):
            raw["x"] = 1
            return raw

        locked_update_json(tmp_path / "a.json", add, default=default)
        locked_update_json(tmp_path / "b.json", add, default=default)
        assert default == {}

    def test_corrupt_file_starts_from_the_default(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{ truncated")
        locked_update_json(path, lambda raw: {**raw, "ok": True}, default={"seed": 1})
        assert json.loads(path.read_text()) == {"seed": 1, "ok": True}

    def test_the_write_is_still_atomic(self, tmp_path, monkeypatch):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"a": 1}))
        monkeypatch.setattr(io_, "atomic_write_json", atomic_write_json)
        with pytest.raises(TypeError):
            locked_update_json(path, lambda raw: {"bad": {object()}}, default={})
        assert json.loads(path.read_text()) == {"a": 1}
        assert not any(p.suffix == ".tmp" for p in tmp_path.iterdir())


class TestFileLock:
    def test_the_lock_lives_on_a_sidecar_not_the_target(self, tmp_path):
        """An atomic write replaces the target's inode; a lock on it guards nothing."""
        path = tmp_path / "state.json"
        with file_lock(path):
            pass
        assert (tmp_path / "state.json.lock").exists()
        assert not path.exists()

    def test_missing_fcntl_degrades_to_a_no_op(self, tmp_path, monkeypatch):
        monkeypatch.setattr(io_, "fcntl", None)
        with file_lock(tmp_path / "state.json"):
            pass
        assert not (tmp_path / "state.json.lock").exists()

    def test_an_unopenable_lock_path_does_not_block_the_update(self, tmp_path, monkeypatch):
        """Bookkeeping must never be what fails a render."""
        import builtins

        real_open = builtins.open

        def fail_lock(target, *args, **kwargs):
            if str(target).endswith(".lock"):
                raise OSError("read-only filesystem")
            return real_open(target, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fail_lock)
        path = tmp_path / "state.json"
        locked_update_json(path, lambda raw: {**raw, "written": True}, default={})
        monkeypatch.undo()

        assert json.loads(path.read_text()) == {"written": True}


def _hammer(path_str: str, key: str, rounds: int) -> None:
    """Module-level so multiprocessing's spawn start method can pickle it."""
    from src._io import locked_update_json

    for i in range(rounds):
        locked_update_json(Path(path_str), lambda raw, i=i: {**raw, key: i}, default={}, indent=2)


class TestCrossProcessUpdates:
    def test_concurrent_updaters_do_not_erase_each_other(self, tmp_path):
        """The losing sequence: read, other process writes, write stale copy back."""
        path = tmp_path / "state.json"
        ctx = mp.get_context("spawn")
        procs = [ctx.Process(target=_hammer, args=(str(path), f"writer{n}", 40)) for n in range(4)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=120)
            assert proc.exitcode == 0

        raw = json.loads(path.read_text())
        # Every writer's final value survived — none was clobbered by another.
        assert {f"writer{n}": 39 for n in range(4)} == raw

    def test_the_file_is_always_valid_json_mid_flight(self, tmp_path):
        path = tmp_path / "state.json"
        code = (
            f"import sys; sys.path.insert(0, {str(REPO)!r});"
            "from pathlib import Path;"
            "from src._io import locked_update_json;"
            f"[locked_update_json(Path({str(path)!r}), "
            "lambda raw, i=i: {**raw, 'n': i}, default={}, indent=2) for i in range(50)]"
        )
        procs = [subprocess.Popen([sys.executable, "-c", code], cwd=str(REPO)) for _ in range(3)]
        for proc in procs:
            assert proc.wait(timeout=120) == 0
        json.loads(path.read_text())  # must not raise
