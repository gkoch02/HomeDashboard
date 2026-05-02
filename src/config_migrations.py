"""Schema-versioned config migration runner.

Boot-time hook that upgrades older YAML config shapes to the current v5
schema in-memory, *before* :func:`src.config.load_config` parses them
into dataclasses. The runner is idempotent and intentionally minimal —
the v5 schema is a strict superset of v4, so the v4→v5 step is a
metadata bump plus a few field renames slot-in points for future work.

Adding a v5→v6 migration in a future release is a new function +
registration in :data:`_MIGRATIONS`.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from src.config_schema import CURRENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)


def _read_schema_version(raw: dict) -> int:
    """Return the schema version embedded in *raw*, defaulting to 4 if absent.

    v4 configs predate the ``schema_version`` field; treating a missing
    value as 4 lets the runner detect them and apply v4→v5 cleanup
    without requiring users to edit their YAML by hand.
    """
    value = raw.get("schema_version")
    if isinstance(value, int) and value > 0:
        return value
    return 4


def v4_to_v5(raw: dict) -> dict:
    """Upgrade a v4-shaped config dict to v5 in-place.

    v5 is a strict superset of v4 — every v4 field still parses unchanged.
    The migration only stamps the new ``schema_version`` and is the
    canonical attachment point for future v5-only renames (e.g. moving
    ``purpleair.*`` under ``air_quality.providers.purpleair.*`` once the
    multi-provider AQI work lands).
    """
    raw["schema_version"] = 5
    return raw


_MIGRATIONS: list[tuple[int, Callable[[dict], dict]]] = [
    (4, v4_to_v5),
]


def needs_migration(raw: dict) -> bool:
    """Return ``True`` iff *raw* declares an older schema_version than current."""
    return _read_schema_version(raw) < CURRENT_SCHEMA_VERSION


def migrate_in_memory(raw: dict) -> dict:
    """Apply every migration whose ``from_version`` matches *raw*'s version.

    Mutates a copy and returns it. Idempotent — re-running on a
    fully-migrated dict is a no-op.

    Defends against a misregistered step that doesn't bump
    ``schema_version``: if a step returns the same version it received,
    the runner stamps :data:`CURRENT_SCHEMA_VERSION` and bails rather
    than infinite-looping.
    """
    out = dict(raw)
    while True:
        from_version = _read_schema_version(out)
        if from_version >= CURRENT_SCHEMA_VERSION:
            return out
        step = _step_for(from_version)
        if step is None:
            logger.warning(
                "No migration registered from schema_version=%d to %d; "
                "stamping current and continuing.",
                from_version,
                CURRENT_SCHEMA_VERSION,
            )
            out["schema_version"] = CURRENT_SCHEMA_VERSION
            return out
        logger.info("Migrating config from schema_version %d", from_version)
        out = step(out)
        new_version = _read_schema_version(out)
        if new_version <= from_version:
            logger.error(
                "Migration step from schema_version=%d failed to advance the "
                "version (got %d); stamping current to avoid infinite loop. "
                "This is a bug in the migration step.",
                from_version,
                new_version,
            )
            out["schema_version"] = CURRENT_SCHEMA_VERSION
            return out


def _step_for(from_version: int) -> Callable[[dict], dict] | None:
    for fv, fn in _MIGRATIONS:
        if fv == from_version:
            return fn
    return None


def backup_path_for(config_path: str, from_version: int) -> Path:
    """Return the path the pre-migration backup will be written to."""
    p = Path(config_path)
    return p.with_suffix(f".yaml.bak-v{from_version}")


def write_pre_migration_backup(config_path: str, from_version: int) -> Path | None:
    """Copy *config_path* to a versioned ``.bak-v<from_version>`` sibling.

    Returns the backup path on success, ``None`` if the source doesn't
    exist or the copy fails. The runner calls this before mutating the
    on-disk file so a user can recover the original verbatim.
    """
    src = Path(config_path)
    if not src.is_file():
        return None
    dst = backup_path_for(config_path, from_version)
    try:
        shutil.copy2(src, dst)
        logger.info("Wrote pre-migration backup: %s", dst)
        return dst
    except OSError as exc:
        logger.warning("Could not write pre-migration backup %s: %s", dst, exc)
        return None
