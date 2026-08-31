"""Tiny I/O utilities shared across modules.

Kept deliberately small — no helpers beyond what is reused at multiple call
sites. Anything else belongs in the module that owns the data.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_LOCK_SUFFIX = ".lock"


def atomic_write_json(path: Path, data: Any, *, indent: int | None = None) -> None:
    """Write *data* as JSON to *path* atomically via tempfile + rename.

    Prevents truncated/corrupt state files when the process is killed mid-write
    or the system loses power. The parent directory is created if missing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def file_lock(path: Path):
    """Hold an advisory cross-process lock covering operations on *path*.

    ``atomic_write_json`` makes each individual write atomic, which prevents a
    torn file — but it does nothing about interleaving. Several state files
    have **two** writers in **separate processes**: the long-running web
    service and the short-lived renderer, which the systemd timer starts every
    five minutes. Read-all → mutate → write is a losing sequence there — the
    web process reads the breaker state, the renderer records a failure, the
    web process writes its stale copy back and the failure is gone (or, in the
    other order, the user's reset is gone while the UI reports success). The
    lock has to cover the whole read-modify-write, not just the write.

    The lock lives on a **sidecar** file rather than the target: an atomic
    write replaces the target's inode, and a lock held on the old one would
    guard nothing.

    Degrades to a no-op when ``fcntl`` is unavailable or the lock file cannot
    be opened — bookkeeping must never be the thing that fails a render.
    """
    if fcntl is None:
        yield
        return
    path = Path(path)
    lock_path = path.with_suffix(path.suffix + _LOCK_SUFFIX)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "w")
    except OSError as exc:
        logger.debug("Could not open the lock for %s: %s", path, exc)
        yield
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def read_json(path: Path, default: Any = None) -> Any:
    """Return the JSON at *path*, or *default* when it is absent or unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return default


def locked_update_json(
    path: Path,
    mutate: Callable[[Any], Any],
    *,
    default: Any = None,
    indent: int | None = None,
) -> Any:
    """Read *path*, apply *mutate*, and write the result — all under one lock.

    This is the sanctioned way to change a JSON state file that another process
    also writes. *mutate* receives the decoded contents (or a **copy** of
    *default* when the file is absent or unreadable) and returns the value to
    persist; returning ``None`` writes nothing and leaves the file alone.

    Returns whatever *mutate* returned, so callers can inspect the merged
    result without re-reading the file.
    """
    path = Path(path)
    with file_lock(path):
        raw = read_json(path, default=None)
        if raw is None:
            raw = json.loads(json.dumps(default)) if default is not None else None
        updated = mutate(raw)
        if updated is not None:
            atomic_write_json(path, updated, indent=indent)
        return updated
