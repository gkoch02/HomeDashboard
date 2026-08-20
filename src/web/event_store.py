"""Structured recent-event helpers for the web UI.

This keeps a tiny append-only JSONL event stream in state/web_events.jsonl so the
status page can show meaningful actions/history without forcing users to read raw
logs. Failures are intentionally swallowed after logging so the UI never breaks
because the event file is missing or temporarily unwritable.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections import deque
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]

from src._time import now_utc

logger = logging.getLogger(__name__)

_EVENT_FILE = "web_events.jsonl"

# The stream used to carry only manual web actions, which are rare. Renderer
# runs land here too now (#218), and the default systemd timer ticks every five
# minutes — roughly 288 records a day — so the file needs a ceiling. When it
# grows past _TRIM_THRESHOLD_BYTES the oldest records are dropped and the
# newest _KEEP_EVENTS are rewritten in place. The status page never asks for
# more than a couple of dozen, so nothing useful is lost.
_KEEP_EVENTS = 500
_TRIM_THRESHOLD_BYTES = 256 * 1024

# Serialise concurrent appends within the web service process. POSIX O_APPEND
# is atomic only up to PIPE_BUF; Python's buffered I/O can split a long line
# across multiple write() syscalls, allowing two threads to interleave bytes
# inside a single record and produce a corrupt JSON line.
_append_lock = threading.Lock()

# The thread lock is not enough any more. Since #218 the stream has two
# writers: the long-running web service and the short-lived renderer, which are
# separate processes. The append itself survives that (each record is one small
# O_APPEND write), but the trim does not — it is read-all, write-elsewhere,
# rename, and anything the other process appends inside that window is dropped
# by the rename. An advisory lock on a sidecar file closes it. The sidecar
# rather than the stream itself, because the trim replaces the stream's inode
# and a lock held on the old one would guard nothing.
_LOCK_SUFFIX = ".lock"


@contextmanager
def _cross_process_lock(path: Path):
    """Hold an advisory lock covering one append (and any trim it triggers).

    Degrades to the in-process lock alone when ``fcntl`` is unavailable or the
    lock file cannot be opened: an audit log is not worth failing a render or a
    web request over.
    """
    if fcntl is None:
        yield
        return
    lock_path = path.with_suffix(path.suffix + _LOCK_SUFFIX)
    try:
        handle = open(lock_path, "w")
    except OSError as exc:
        logger.debug("Could not open the event-stream lock: %s", exc)
        yield
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def append_event(state_dir: str, kind: str, message: str, **details) -> None:
    path = Path(state_dir) / _EVENT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": now_utc().isoformat(timespec="seconds"),
        "kind": kind,
        "message": message,
        "details": details or {},
    }
    line = json.dumps(payload, sort_keys=True) + "\n"
    try:
        with _append_lock, _cross_process_lock(path):
            _trim_if_oversized(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as exc:
        logger.debug("Could not append web event: %s", exc)


def _trim_if_oversized(path: Path) -> None:
    """Drop the oldest records once the file grows past its ceiling.

    Called with both locks held. A stat is cheap enough to do on every append;
    the rewrite itself happens rarely. The rewrite goes through a tempfile +
    rename so a kill mid-trim cannot leave a half-written stream — the same
    discipline every other state file here uses. Failures are swallowed by the
    caller: a stream that cannot be trimmed is still a stream that can be
    appended to.
    """
    try:
        if path.stat().st_size <= _TRIM_THRESHOLD_BYTES:
            return
    except OSError:
        return

    with open(path, encoding="utf-8", errors="replace") as f:
        keep = deque(f, maxlen=_KEEP_EVENTS)

    # A unique temp name, not a fixed one: two processes trimming at once would
    # otherwise write the same path and each rename the other's half-file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(keep)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.debug("Trimmed web event stream to the most recent %d records", len(keep))


def read_recent_events(state_dir: str, limit: int = 20) -> list[dict]:
    path = Path(state_dir) / _EVENT_FILE
    if not path.exists():
        return []
    try:
        rows: deque[dict] = deque(maxlen=max(1, limit))
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(reversed(rows))
    except Exception as exc:
        logger.debug("Could not read web events: %s", exc)
        return []
