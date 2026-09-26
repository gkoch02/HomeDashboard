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

from src.config import is_known_log_level, load_config, validate_config

if TYPE_CHECKING:
    from src.config import Config

# Derived from src.config_schema — adding a new editable field is a single
# `FieldSpec` entry there, not a dict edit here.
from src.config_schema import editable_field_paths as _editable_field_paths

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

# How many rotated ``config.yaml.bak.<timestamp>`` archives to keep. Every save
# used to add one and nothing ever removed them, so the directory grew without
# bound — and each file is a byte-for-byte copy of the config, API keys
# included. The UI only ever lists five, so anything past this is unreachable
# from the app as well as unbounded on disk.
_MAX_ROTATED_BACKUPS = 10


class ConfigReadError(Exception):
    """The on-disk config could not be read or parsed.

    Raised instead of degrading to an empty dict: a save that starts from
    ``{}`` validates (everything defaults), and then *replaces* the file with
    only the patched keys — API keys, calendar URLs and every field not on the
    form gone, reported as "Saved" (#260). Callers turn this into a structured
    error that blocks the write.
    """


class ConfigBackupError(Exception):
    """The pre-write backup could not be taken, so the write did not happen.

    The backup is the only recovery path a web save leaves behind; proceeding
    without one turns an ordinary I/O hiccup into an unrecoverable overwrite.
    """


_READ_ERROR_HINT = "Fix the file on disk (or its permissions) and reload this page before saving."


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
    """Return available backup files for *config_path*, newest first.

    Ordering is *not* lexicographic on the filename: ``config.yaml.bak.<ts>``
    sorts after the shorter ``config.yaml.bak``, so a reverse name sort puts a
    rotated archive ahead of the plain backup that is actually the newest one.
    Instead the plain ``.bak`` — which ``_write_raw_yaml`` guarantees is the
    snapshot taken by the immediately preceding save — always ranks first, and
    the rotated archives follow by modification time (newest first). The
    embedded name timestamp only breaks mtime ties, since a rotation renames
    the file and carries the original mtime with it.

    Versioned pre-migration backups (``config.yaml.bak-v4``, written by
    ``src.config_migrations``) are a different kind of artifact — restoring one
    would roll the file back to an older schema — so they are not listed here.
    """
    path = Path(config_path)
    if not path.parent.exists():
        return []

    plain_name = f"{path.stem}.yaml.bak"
    rotated_prefix = f"{plain_name}."

    plain: list[dict] = []
    rotated: list[tuple[int, str, dict]] = []
    for candidate in path.parent.glob(f"{plain_name}*"):
        is_plain = candidate.name == plain_name
        if not is_plain and not candidate.name.startswith(rotated_prefix):
            continue  # e.g. a .bak-v4 pre-migration backup
        try:
            stat = candidate.stat()
        except OSError:
            continue
        entry = {
            "name": candidate.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        }
        if is_plain:
            plain.append(entry)
        else:
            rotated.append((stat.st_mtime_ns, candidate.name, entry))

    rotated.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return (plain + [entry for _mtime, _name, entry in rotated])[:limit]


def restore_latest_backup(config_path: str) -> tuple[bool, str]:
    """Restore the most recent backup over the live config file."""
    path = Path(config_path)
    backups = list_config_backups(config_path, limit=1)
    if not backups:
        return False, "No backup file found."

    backup_path = path.parent / backups[0]["name"]
    try:
        # The whole read → validate → write runs under the lock: a Save
        # from another tab interleaving here would be discarded by this
        # write while both requests reported success (#281).
        with _write_lock:
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

    Sensitive fields are represented as boolean ``_<name>_set`` flags only,
    where ``<name>`` is the field's own key — ``google.service_account_path``
    is ``google._service_account_path_set`` — so ``/api/config/schema`` can
    find each secret's flag by its schema path (#308). Read-only hardware
    fields are prefixed with ``_``.
    """
    cfg = load_config(config_path)

    return {
        "title": cfg.title,
        "theme": cfg.theme,
        "timezone": cfg.timezone,
        # Upper-cased when it is a level name, so the dropdown (whose options
        # are canonical names) can select `level: info` from the file.
        "log_level": (
            str(cfg.log_level).strip().upper()
            if is_known_log_level(cfg.log_level)
            else cfg.log_level
        ),
        "display": {
            "_provider": cfg.display.provider,
            "_model": cfg.display.model,
            "_width": cfg.display.width,
            "_height": cfg.display.height,
            "show_weather": cfg.display.show_weather,
            "show_birthdays": cfg.display.show_birthdays,
            "show_info_panel": cfg.display.show_info_panel,
            "enable_partial_refresh": cfg.display.enable_partial_refresh,
            "max_partials_before_full": cfg.display.max_partials_before_full,
            "scaling": cfg.display.scaling,
            "quantization_mode": cfg.display.quantization_mode,
            "min_refresh_interval_seconds": cfg.display.min_refresh_interval_seconds,
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
            "one_call_version": cfg.weather.one_call_version,
        },
        "birthdays": {
            "source": cfg.birthdays.source,
            "lookahead_days": cfg.birthdays.lookahead_days,
            "calendar_keyword": cfg.birthdays.calendar_keyword,
            "file_path": cfg.birthdays.file_path,
        },
        "purpleair": {
            "_api_key_set": bool(cfg.purpleair.api_key),
            "_sensor_id_set": bool(cfg.purpleair.sensor_id),
            "_sensor_id": cfg.purpleair.sensor_id,
        },
        "google": {
            "_service_account_path_set": Path(cfg.google.service_account_path).exists(),
            "_calendar_id": cfg.google.calendar_id,
            "_contacts_email": cfg.google.contacts_email,
            "_ical_url_set": bool(cfg.google.ical_url),
            "_additional_ical_urls_set": bool(cfg.google.additional_ical_urls),
            "_caldav_url": cfg.google.caldav_url,
            "_caldav_username": cfg.google.caldav_username,
            "_caldav_password_file_set": bool(cfg.google.caldav_password_file),
            "_caldav_calendar_url": cfg.google.caldav_calendar_url,
            "additional_calendars": cfg.google.additional_calendars,
            "daily_quota_warning": cfg.google.daily_quota_warning,
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
        "quotes": {
            "path": cfg.quotes.path,
        },
        "photo": {
            "path": cfg.photo.path,
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
    try:
        rules = _load_raw_yaml(config_path).get("theme_rules")
    except ConfigReadError as exc:
        logger.warning("Could not load theme_rules from %s: %s", config_path, exc)
        return ""
    if not rules:
        return ""
    return yaml.dump(rules, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ``when:`` conditions that must parse as plain numbers. YAML 1.1 turns
# ``yes``/``on`` into booleans, which would otherwise sail through as 1/0.
_NUMERIC_RULE_CONDITIONS = ("temp_at_least", "temp_at_most", "aqi_at_least")


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
        # load_config() drops a rule whose numeric threshold it cannot read, so
        # a save that accepted one would silently discard the rule on load.
        for key in _NUMERIC_RULE_CONDITIONS:
            threshold = (entry.get("when") or {}).get(key)
            if threshold is None:
                continue
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                return _reject(f"Rule {i}: '{key}' must be a number, got {threshold!r}.")

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

    # Read → patch → validate → write is one critical section. Locking only
    # the write let two saves (or a save and a restore) from different tabs
    # interleave: the later write silently discarded the earlier patch while
    # both responded ``saved: true``, and the .bak rotation raced on the same
    # filenames. Validation is a temp-file parse, cheap enough to serialise
    # (#281).
    with _write_lock:
        try:
            raw = _load_raw_yaml(config_path)
        except ConfigReadError as exc:
            return False, [_read_error(exc)], []
        updated_raw = _apply_to_raw(raw, safe_patch)

        _cfg, errors_obj, warnings_obj = _validate_raw(updated_raw)

        errors = parse_errors + [
            {"field": e.field, "message": e.message, "hint": e.hint} for e in errors_obj
        ]
        warnings = [{"field": w.field, "message": w.message, "hint": w.hint} for w in warnings_obj]

        if not errors_obj and not parse_errors:
            try:
                _write_raw_yaml(config_path, updated_raw)
            except ConfigBackupError as exc:
                return False, [_backup_error(exc)], warnings
            return True, errors, warnings

    return False, errors, warnings


def _read_error(exc: ConfigReadError) -> dict:
    return {"field": "config", "message": str(exc), "hint": _READ_ERROR_HINT}


def _backup_error(exc: ConfigBackupError) -> dict:
    return {
        "field": "config",
        "message": str(exc),
        "hint": "Nothing was written. Check the config directory's free space and permissions.",
    }


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

    try:
        raw = _load_raw_yaml(config_path)
    except ConfigReadError as exc:
        return None, [_read_error(exc)], []
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
    """Return the raw YAML mapping at *config_path*.

    A missing file is an empty mapping — a first save creates it. Anything
    else that stops the file being read as a mapping raises
    :class:`ConfigReadError`; degrading to ``{}`` here is how a save came to
    overwrite the whole config with just the patched keys (#260).
    """
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except OSError as exc:
        raise ConfigReadError(f"Could not read {path.name}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigReadError(f"{path.name} is not valid YAML: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigReadError(
            f"{path.name} must be a YAML mapping at the top level, got {type(raw).__name__}"
        )
    return raw


def _rotated_backup_path(path: Path) -> Path:
    """Return an unused ``<config>.yaml.bak.<timestamp>`` path for a rotation.

    The timestamp carries microseconds because two saves landing in the same
    second would otherwise rotate onto the same filename, and the second
    ``replace()`` would silently discard the first archive. The suffix loop is
    belt-and-braces for a clock that repeats a microsecond.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")  # allow-naive-datetime — file naming
    base = f"{path.stem}.yaml.bak.{stamp}"
    candidate = path.with_name(base)
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{base}-{counter}")
        counter += 1
    return candidate


def _prune_rotated_backups(path: Path, keep: int = _MAX_ROTATED_BACKUPS) -> None:
    """Delete all but the newest *keep* rotated archives for *path*.

    Only files matching the rotation shape written by
    :func:`_rotated_backup_path` are considered — the plain ``.bak`` is the
    live backup and the versioned ``.bak-v<N>`` pre-migration snapshots are a
    different artifact, so neither is ever a candidate. Ordering matches
    :func:`list_config_backups` (mtime first, name as the tie-break) so the
    files the UI lists are the files that survive.

    Failure is non-fatal: a backup that cannot be deleted must not fail the
    save that created it.
    """
    prefix = f"{path.stem}.yaml.bak."
    rotated: list[tuple[int, str, Path]] = []
    for candidate in path.parent.glob(f"{prefix}*"):
        try:
            rotated.append((candidate.stat().st_mtime_ns, candidate.name, candidate))
        except OSError:
            continue
    if len(rotated) <= keep:
        return
    rotated.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _mtime, name, stale in rotated[keep:]:
        try:
            stale.unlink()
        except OSError as exc:
            logger.warning("Could not prune old config backup %s: %s", name, exc)


def _write_raw_yaml(config_path: str, raw: dict, *, rotate_backup: bool = True) -> None:
    """Write *raw* to *config_path* atomically using a temp-file rename.

    A backup copy is written to ``<config>.bak`` before overwriting. A backup
    that cannot be taken raises :class:`ConfigBackupError` *before* the target
    is touched: the backup is the one recovery path a web save leaves behind,
    and proceeding without it used to turn a read failure into a silent
    overwrite with no way back (#260).
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
                bak.replace(_rotated_backup_path(path))
                _prune_rotated_backups(path)
            os.replace(tmp_b, bak)
        except OSError as exc:
            logger.warning("Could not write config backup to %s: %s", bak, exc)
            try:
                os.unlink(tmp_b)
            except OSError:
                pass
            raise ConfigBackupError(f"Could not write config backup to {bak.name}: {exc}") from exc

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
