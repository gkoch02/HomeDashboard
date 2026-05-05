"""Contract tests for ``src.config_migrations``.

Guards the schema-versioning machinery so adding a future migration step
doesn't silently regress the v4→v5 entry path users will follow on first
upgrade.
"""

from __future__ import annotations

from src.config_migrations import (
    backup_path_for,
    migrate_in_memory,
    needs_migration,
    v4_to_v5,
    write_pre_migration_backup,
)
from src.config_schema import CURRENT_SCHEMA_VERSION


class TestNeedsMigration:
    def test_missing_schema_version_treated_as_v4(self):
        assert needs_migration({}) is True
        assert needs_migration({"title": "X"}) is True

    def test_v4_explicitly_needs_migration(self):
        assert needs_migration({"schema_version": 4}) is True

    def test_current_version_does_not_need_migration(self):
        assert needs_migration({"schema_version": CURRENT_SCHEMA_VERSION}) is False

    def test_future_version_does_not_need_migration(self):
        # Future-versioned configs are left alone — the runner stamps the
        # current version only when older.
        assert needs_migration({"schema_version": CURRENT_SCHEMA_VERSION + 1}) is False


class TestV4ToV5:
    def test_stamps_schema_version_5(self):
        out = v4_to_v5({})
        assert out["schema_version"] == 5

    def test_preserves_existing_keys(self):
        raw = {"title": "Home", "theme": "agenda", "weather": {"latitude": 1.0}}
        out = v4_to_v5(dict(raw))
        for k, v in raw.items():
            assert out[k] == v


class TestMigrateInMemory:
    def test_misregistered_step_does_not_infinite_loop(self):
        """Regression: a step that fails to bump ``schema_version`` must NOT
        infinite-loop the runner. The defensive branch stamps current and
        bails with an error log."""
        from src import config_migrations as cm

        bad_step_calls = {"n": 0}

        def _bad_step(raw):
            bad_step_calls["n"] += 1
            return raw  # forgot to set schema_version — this is the bug.

        original_migrations = cm._MIGRATIONS
        cm._MIGRATIONS = [(4, _bad_step)]
        try:
            out = cm.migrate_in_memory({"title": "X"})
        finally:
            cm._MIGRATIONS = original_migrations

        assert out["schema_version"] == cm.CURRENT_SCHEMA_VERSION
        # Step ran exactly once — we did not infinite-loop.
        assert bad_step_calls["n"] == 1

    def test_v4_dict_becomes_current_version(self):
        out = migrate_in_memory({"title": "X"})
        assert out["schema_version"] == CURRENT_SCHEMA_VERSION
        assert out["title"] == "X"

    def test_already_current_is_passthrough(self):
        raw = {"schema_version": CURRENT_SCHEMA_VERSION, "title": "X"}
        out = migrate_in_memory(raw)
        assert out == raw

    def test_input_dict_is_not_mutated(self):
        raw = {"title": "X"}
        migrate_in_memory(raw)
        assert "schema_version" not in raw

    def test_idempotent_when_called_twice(self):
        once = migrate_in_memory({"title": "X"})
        twice = migrate_in_memory(once)
        assert once == twice


class TestBackup:
    def test_backup_path_uses_versioned_suffix(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        assert backup_path_for(str(cfg), 4) == tmp_path / "config.yaml.bak-v4"

    def test_write_pre_migration_backup_copies_file(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("title: test\n")
        backup = write_pre_migration_backup(str(cfg), 4)
        assert backup is not None
        assert backup.read_text() == "title: test\n"
        # Original is untouched.
        assert cfg.read_text() == "title: test\n"

    def test_write_pre_migration_backup_missing_source(self, tmp_path):
        cfg = tmp_path / "missing.yaml"
        assert write_pre_migration_backup(str(cfg), 4) is None

    def test_write_pre_migration_backup_oserror_returns_none(self, tmp_path):
        """When shutil.copy2 raises OSError, return None and log a warning."""
        import shutil
        from unittest.mock import patch

        cfg = tmp_path / "config.yaml"
        cfg.write_text("title: test\n")
        with patch("shutil.copy2", side_effect=OSError("disk full")):
            result = write_pre_migration_backup(str(cfg), 4)
        assert result is None


class TestMigrateInMemoryNoStep:
    def test_no_registered_step_stamps_current_and_continues(self):
        """When a config is at an unknown old version with no migration step
        registered, migrate_in_memory must NOT loop — it stamps current and
        returns safely."""
        from src import config_migrations as cm

        original = cm._MIGRATIONS
        cm._MIGRATIONS = []  # empty — no step covers any version
        try:
            # Feed a dict at version 3 (no step covers 3 → 5)
            out = cm.migrate_in_memory({"schema_version": 3, "title": "X"})
        finally:
            cm._MIGRATIONS = original

        assert out["schema_version"] == cm.CURRENT_SCHEMA_VERSION
        assert out["title"] == "X"
