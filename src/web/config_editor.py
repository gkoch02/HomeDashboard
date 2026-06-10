"""Safe config read/write for the web UI.

Only fields in EDITABLE_FIELD_PATHS may be changed via the API. Sensitive
fields (API keys, credential paths) appear in the read response as boolean
``_*_set`` flags only — never sent to the browser as plaintext.

Write strategy: load the raw YAML dict, apply only known-safe changes,
validate by parsing the result through load_config() + validate_config(),
then write back atomically. YAML comments are not preserved (PyYAML
limitation), but all values — including those we didn't touch — are retained.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

from src.config import load_config, validate_config

if TYPE_CHECKING:
    from src.config import Config

# Derived from src.config_schema — adding a new editable field is a single
# `FieldSpec` entry there, not a dict edit here.
from src.config_schema import editable_field_paths as _editable_field_paths

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


@contextlib.contextmanager
def config_write_lock():
    """Public accessor for the module's serialisation lock.

    Callers outside this module use this context manager to coordinate
    multi-step config mutations (e.g. file write + in-memory swap) so they
    cannot interleave with apply_patch / restore_latest_backup.
    """
    with _write_lock:
        yield


# ---------------------------------------------------------------------------
# Field registry
# ---------------------------------------------------------------------------

# Maps the flat API field path to the nested YAML key path.
# For top-level YAML keys the tuple has one element; for nested keys, two.
# theme_schedule is a special case: handled explicitly as a list.
EDITABLE_FIELD_PATHS: dict[str, tuple] = _editable_field_paths()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_config_backups(config_path: str, limit: int = 5) -> list[dict]:
    """Return available backup files for *config_path*, newest first."""
    path = Path(config_path)
    if not path.parent.exists():
        return []

    backups: list[dict] = []
    for candidate in sorted(path.parent.glob(f"{path.stem}.yaml.bak*"), reverse=True):
        try:
            stat = candidate.stat()
            backups.append(
                {
                    "name": candidate.name,
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
                        timespec="seconds"
                    ),
                }
            )
        except OSError:
            continue
        if len(backups) >= limit:
            break
    return backups


def restore_latest_backup(config_path: str) -> tuple[bool, str]:
    """Restore the most recent backup over the live config file."""
    path = Path(config_path)
    backups = list_config_backups(config_path, limit=1)
    if not backups:
        return False, "No backup file found."

    backup_path = path.parent / backups[0]["name"]
    try:
        raw = _load_raw_yaml(str(backup_path))
        _cfg, errors_obj, _warnings_obj = _validate_raw(raw)
        if errors_obj:
            return False, "Latest backup failed validation and was not restored."
        _write_raw_yaml(config_path, raw, rotate_backup=False)
        return True, f"Restored {backup_path.name}."
    except Exception as exc:
        return False, str(exc)


def get_config_for_web(config_path: str) -> dict:
    """Return the current config as a JSON-safe dict for the web UI.

    Sensitive fields are represented as boolean ``_*_set`` flags only.
    Read-only hardware fields are prefixed with ``_``.
    """
    cfg = load_config(config_path)

    return {
        "title": cfg.title,
        "theme": cfg.theme,
        "timezone": cfg.timezone,
        "log_level": cfg.log_level,
        "display": {
            "_model": cfg.display.model,
            "_width": cfg.display.width,
            "_height": cfg.display.height,
            "show_weather": cfg.display.show_weather,
            "show_birthdays": cfg.display.show_birthdays,
            "show_info_panel": cfg.display.show_info_panel,
            "week_days": cfg.display.week_days,
            "enable_partial_refresh": cfg.display.enable_partial_refresh,
            "max_partials_before_full": cfg.display.max_partials_before_full,
        },
        "schedule": {
            "quiet_hours_start": cfg.schedule.quiet_hours_start,
            "quiet_hours_end": cfg.schedule.quiet_hours_end,
        },
        "weather": {
            "_api_key_set": bool(cfg.weather.api_key),
            "latitude": cfg.weather.latitude,
            "longitude": cfg.weather.longitude,
            "units": cfg.weather.units,
        },
        "birthdays": {
            "source": cfg.birthdays.source,
            "lookahead_days": cfg.birthdays.lookahead_days,
            "calendar_keyword": cfg.birthdays.calendar_keyword,
        },
        "purpleair": {
            "_api_key_set": bool(cfg.purpleair.api_key),
            "_sensor_id_set": bool(cfg.purpleair.sensor_id),
        },
        "google": {
            "_service_account_set": Path(cfg.google.service_account_path).exists(),
            "_calendar_id": cfg.google.calendar_id,
            "_ical_url_set": bool(cfg.google.ical_url),
        },
        "filters": {
            "exclude_calendars": cfg.filters.exclude_calendars,
            "exclude_keywords": cfg.filters.exclude_keywords,
            "exclude_all_day": cfg.filters.exclude_all_day,
        },
        "cache": {
            "weather_ttl_minutes": cfg.cache.weather_ttl_minutes,
            "events_ttl_minutes": cfg.cache.events_ttl_minutes,
            "birthdays_ttl_minutes": cfg.cache.birthdays_ttl_minutes,
            "weather_fetch_interval": cfg.cache.weather_fetch_interval,
            "events_fetch_interval": cfg.cache.events_fetch_interval,
            "birthdays_fetch_interval": cfg.cache.birthdays_fetch_interval,
            "air_quality_ttl_minutes": cfg.cache.air_quality_ttl_minutes,
            "air_quality_fetch_interval": cfg.cache.air_quality_fetch_interval,
            "max_failures": cfg.cache.max_failures,
            "cooldown_minutes": cfg.cache.cooldown_minutes,
            "quote_refresh": cfg.cache.quote_refresh,
        },
        "random_theme": {
            "include": cfg.random_theme.include,
            "exclude": cfg.random_theme.exclude,
        },
        "theme_schedule": [{"time": e.time, "theme": e.theme} for e in cfg.theme_schedule.entries],
        "theme_rules_yaml": _theme_rules_yaml(config_path),
        "backups": list_config_backups(config_path),
    }


def _theme_rules_yaml(config_path: str) -> str:
    """Return the on-disk ``theme_rules`` list as YAML text for the editor textarea.

    Reads the raw file (not the parsed Config) so the round-trip is lossless —
    unknown keys a future version might add survive an unrelated save.
    """
    rules = _load_raw_yaml(config_path).get("theme_rules")
    if not rules:
        return ""
    return yaml.dump(rules, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _normalise_patch(patch: dict) -> tuple[dict, list[dict]]:
    """Pre-parse and shape-check patch values that arrive as YAML text.

    The web editor's theme-rules field is a YAML textarea, so its value is a
    string; parse it into the list shape the YAML file stores, then check
    every entry actually looks like a rule. load_config() silently skips
    malformed entries, so anything accepted here without a shape check would
    save successfully and then do nothing. Returns ``(patch, errors)`` — on
    any failure the field is dropped from the patch and a structured error is
    reported instead, which blocks the save.
    """
    if "theme_rules" not in patch:
        return patch, []

    _HINT = "Each entry is '- when: {<conditions>}' plus 'theme: <name>'."

    def _reject(message: str) -> tuple[dict, list[dict]]:
        rejected = {k: v for k, v in patch.items() if k != "theme_rules"}
        return rejected, [{"field": "theme_rules", "message": message, "hint": _HINT}]

    value = patch["theme_rules"]
    if isinstance(value, str):
        try:
            value = yaml.safe_load(value) or []
        except yaml.YAMLError as exc:
            return _reject(f"Not valid YAML: {exc}")
    if not isinstance(value, list):
        return _reject("theme_rules must be a YAML list of rules.")
    for i, entry in enumerate(value, start=1):
        if not isinstance(entry, dict):
            return _reject(f"Rule {i} is not a mapping (got {type(entry).__name__}).")
        if not isinstance(entry.get("theme"), str) or not entry["theme"]:
            return _reject(f"Rule {i} is missing a 'theme: <name>' value.")
        if "when" in entry and not isinstance(entry["when"], dict):
            return _reject(f"Rule {i} has a 'when:' that is not a mapping.")

    patch = dict(patch)
    patch["theme_rules"] = value
    return patch, []


def apply_patch(config_path: str, patch: dict) -> tuple[bool, list[dict], list[dict]]:
    """Validate and apply a partial config update.

    *patch* is a flat dict of ``{"field.path": value}`` pairs using the keys
    from EDITABLE_FIELD_PATHS.  Unknown and sensitive fields are silently
    ignored.  The special key ``"theme_schedule"`` accepts a list of
    ``{"time": "HH:MM", "theme": "<name>"}`` dicts.

    Returns ``(saved, errors, warnings)`` where *saved* is True only when
    the file was written with no fatal validation errors.
    """
    patch, parse_errors = _normalise_patch(patch)
    safe_patch = {k: v for k, v in patch.items() if k in EDITABLE_FIELD_PATHS}

    raw = _load_raw_yaml(config_path)
    updated_raw = _apply_to_raw(raw, safe_patch)

    _cfg, errors_obj, warnings_obj = _validate_raw(updated_raw)

    errors = parse_errors + [
        {"field": e.field, "message": e.message, "hint": e.hint} for e in errors_obj
    ]
    warnings = [{"field": w.field, "message": w.message, "hint": w.hint} for w in warnings_obj]

    if not errors_obj and not parse_errors:
        with _write_lock:
            _write_raw_yaml(config_path, updated_raw)
        return True, errors, warnings

    return False, errors, warnings


def build_patched_config(
    config_path: str, patch: dict
) -> tuple[Config | None, list[dict], list[dict]]:
    """Build a candidate Config with *patch* applied — without writing anything.

    Same allowlist and validation pipeline as :func:`apply_patch` (unknown and
    sensitive fields are silently dropped), but the patched YAML is only ever
    materialised in a temp file for parsing. Powers the web editor's
    patch-preview: "what would the dashboard look like with my unsaved edits?"

    Returns ``(cfg, errors, warnings)``; *cfg* is ``None`` when validation
    produced fatal errors.
    """
    patch, parse_errors = _normalise_patch(patch)
    safe_patch = {k: v for k, v in patch.items() if k in EDITABLE_FIELD_PATHS}

    raw = _load_raw_yaml(config_path)
    updated_raw = _apply_to_raw(raw, safe_patch)

    cfg, errors_obj, warnings_obj = _validate_raw(updated_raw)

    errors = parse_errors + [
        {"field": e.field, "message": e.message, "hint": e.hint} for e in errors_obj
    ]
    warnings = [{"field": w.field, "message": w.message, "hint": w.hint} for w in warnings_obj]

    if errors_obj or parse_errors:
        return None, errors, warnings
    return cfg, errors, warnings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_raw_yaml(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Could not load %s: %s", config_path, exc)
        return {}


def _write_raw_yaml(config_path: str, raw: dict, *, rotate_backup: bool = True) -> None:
    """Write *raw* to *config_path* atomically using a temp-file rename.

    A backup copy is written to ``<config>.bak`` before overwriting.  Backup
    failure is non-fatal — a warning is logged and the save proceeds normally.
    """
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomically back up the current file before overwriting.
    if rotate_backup and path.exists():
        bak = path.with_suffix(".yaml.bak")
        fd_b, tmp_b = tempfile.mkstemp(dir=path.parent, suffix=".bak.tmp")
        try:
            with os.fdopen(fd_b, "wb") as fb:
                fb.write(path.read_bytes())
            if bak.exists():
                timestamp = datetime.now().strftime(
                    "%Y%m%d-%H%M%S"
                )  # allow-naive-datetime — backup file naming
                bak.replace(path.with_name(f"{path.stem}.yaml.bak.{timestamp}"))
            os.replace(tmp_b, bak)
        except OSError as exc:
            logger.warning("Could not write config backup to %s: %s", bak, exc)
            try:
                os.unlink(tmp_b)
            except OSError:
                pass

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _apply_to_raw(raw: dict, patch: dict) -> dict:
    """Return a deep copy of *raw* with *patch* fields applied."""
    raw = copy.deepcopy(raw)

    for field_path, value in patch.items():
        yaml_path = EDITABLE_FIELD_PATHS.get(field_path)
        if not yaml_path:
            continue

        if field_path == "theme_schedule":
            # List of {time, theme} dicts — store directly as YAML list.
            raw["theme_schedule"] = value if isinstance(value, list) else []
            continue

        if field_path == "theme_rules":
            # List of {when, theme} dicts (already parsed from the YAML
            # textarea by _normalise_patch). An empty list removes the key so
            # the saved YAML stays clean.
            rules = value if isinstance(value, list) else []
            if rules:
                raw["theme_rules"] = rules
            else:
                raw.pop("theme_rules", None)
            continue

        # Navigate (and create) nested dicts, then set the leaf.
        obj = raw
        for key in yaml_path[:-1]:
            if not isinstance(obj.get(key), dict):
                obj[key] = {}
            obj = obj[key]
        obj[yaml_path[-1]] = value

    return raw


def _validate_raw(raw: dict) -> tuple:
    """Parse *raw* into a Config via a temp file and run validate_config().

    Returns ``(cfg, errors, warnings)``.
    """
    fd, tmp = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)
        cfg = load_config(tmp)
        errors, warnings = validate_config(cfg, config_path="")
        return cfg, errors, warnings
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
