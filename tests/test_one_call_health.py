"""Tests for src/fetchers/one_call_health.py — One Call failure classification (#223).

The degradation contract is unchanged: a One Call failure never breaks a
render. What these pin is that a *permanent* failure is observable rather
than silent, and that a transient one stays quiet.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.fetchers import one_call_health as och


def _http_error(status: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


class TestClassify:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_statuses_are_permanent(self, status):
        outcome, seen = och.classify(_http_error(status))
        assert outcome == och.AUTH_FAILED
        assert seen == status

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_other_http_statuses_are_transient(self, status):
        outcome, seen = och.classify(_http_error(status))
        assert outcome == och.TRANSIENT
        assert seen == status

    def test_timeout_is_transient(self):
        outcome, status = och.classify(requests.Timeout("read timed out"))
        assert outcome == och.TRANSIENT
        assert status is None

    def test_connection_error_is_transient(self):
        outcome, _ = och.classify(requests.ConnectionError("dns failure"))
        assert outcome == och.TRANSIENT

    def test_payload_error_is_transient(self):
        """An unexpected shape is not something an operator can act on."""
        assert och.classify(KeyError("data"))[0] == och.TRANSIENT

    def test_a_401_in_the_message_alone_is_not_an_auth_failure(self):
        """Only a real response status counts; text is not evidence."""
        assert och.classify(Exception("401 Unauthorized"))[0] == och.TRANSIENT

    def test_a_response_without_a_numeric_status_is_transient(self):
        exc = requests.HTTPError("weird", response=MagicMock(status_code="401"))
        assert och.classify(exc)[0] == och.TRANSIENT


class TestDescribe:
    def test_auth_message_names_the_version_and_the_knob(self):
        message = och.describe(och.AUTH_FAILED, "4.0", 401)
        assert "4.0" in message
        assert "401" in message
        assert "one_call_version" in message

    def test_transient_message_is_generic(self):
        assert "subscription" not in och.describe(och.TRANSIENT, "3.0", None)


class TestLogging:
    def test_permanent_failure_warns_on_the_first_occurrence(self, tmp_path, caplog):
        with caplog.at_level(logging.DEBUG):
            och.record_failure(str(tmp_path), "3.0", _http_error(401))
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "one_call_version" in warnings[0].message

    def test_persistent_failure_does_not_warn_again(self, tmp_path, caplog):
        """A misconfiguration must not emit a line every fetch interval."""
        och.record_failure(str(tmp_path), "3.0", _http_error(401))
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            for _ in range(5):
                och.record_failure(str(tmp_path), "3.0", _http_error(401))
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

    def test_failure_warns_again_after_a_recovery(self, tmp_path, caplog):
        och.record_failure(str(tmp_path), "3.0", _http_error(401))
        och.record_success(str(tmp_path), "3.0")
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            och.record_failure(str(tmp_path), "3.0", _http_error(401))
        assert [r for r in caplog.records if r.levelname == "WARNING"]

    def test_transient_failure_never_warns(self, tmp_path, caplog):
        with caplog.at_level(logging.DEBUG):
            for _ in range(3):
                och.record_failure(str(tmp_path), "3.0", requests.Timeout("slow"))
        assert not [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("alerts/UV fetch skipped" in r.message for r in caplog.records)

    def test_recovery_is_announced_once(self, tmp_path, caplog):
        och.record_failure(str(tmp_path), "3.0", _http_error(401))
        with caplog.at_level(logging.INFO):
            och.record_success(str(tmp_path), "3.0")
            och.record_success(str(tmp_path), "3.0")
        assert len([r for r in caplog.records if "answering again" in r.message]) == 1

    def test_a_first_ever_success_is_not_announced(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO):
            och.record_success(str(tmp_path), "3.0")
        assert not [r for r in caplog.records if "answering again" in r.message]

    def test_classification_still_happens_without_a_state_dir(self, caplog):
        """Dry runs and previews pass state_dir=None; they still get the warning."""
        with caplog.at_level(logging.DEBUG):
            outcome = och.record_failure(None, "4.0", _http_error(401))
        assert outcome == och.AUTH_FAILED
        assert [r for r in caplog.records if r.levelname == "WARNING"]


class TestState:
    def test_success_records_ok(self, tmp_path):
        och.record_success(str(tmp_path), "3.0")
        assert och.read_health(str(tmp_path))["outcome"] == och.OK

    def test_failure_records_the_details(self, tmp_path):
        och.record_failure(str(tmp_path), "4.0", _http_error(401))
        health = och.read_health(str(tmp_path))
        assert health["outcome"] == och.AUTH_FAILED
        assert health["version"] == "4.0"
        assert health["http_status"] == 401
        assert health["checked_at"]

    def test_success_clears_a_recorded_failure(self, tmp_path):
        och.record_failure(str(tmp_path), "3.0", _http_error(401))
        och.record_success(str(tmp_path), "3.0")
        assert och.read_health(str(tmp_path))["outcome"] == och.OK

    def test_missing_state_reads_as_empty(self, tmp_path):
        assert och.read_health(str(tmp_path / "nowhere")) == {}

    def test_corrupt_state_reads_as_empty(self, tmp_path):
        (tmp_path / och.STATE_FILENAME).write_text("{not json")
        assert och.read_health(str(tmp_path)) == {}

    def test_non_object_state_reads_as_empty(self, tmp_path):
        (tmp_path / och.STATE_FILENAME).write_text(json.dumps([1, 2, 3]))
        assert och.read_health(str(tmp_path)) == {}

    def test_no_state_dir_writes_nothing(self, tmp_path):
        och.record_failure(None, "3.0", _http_error(401))
        assert not list(tmp_path.iterdir())

    def test_an_unwritable_state_dir_does_not_raise(self, tmp_path):
        """Health bookkeeping must never be what breaks a fetch."""
        with patch(
            "src.fetchers.one_call_health.atomic_write_json",
            side_effect=OSError("read-only filesystem"),
        ):
            assert och.record_failure(str(tmp_path), "3.0", _http_error(401)) == och.AUTH_FAILED
            och.record_success(str(tmp_path), "3.0")
