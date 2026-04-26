"""Tiny I/O utilities shared across modules.

Kept deliberately small — no helpers beyond what is reused at multiple call
sites. Anything else belongs in the module that owns the data.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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
