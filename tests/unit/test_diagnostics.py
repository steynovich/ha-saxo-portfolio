"""Unit tests for the Saxo Portfolio diagnostics module.

Tests cover:
- _get_coordinator_status: various coordinator states
- _get_market_config: all timezone branches
- _format_token_status: expired, critical, warning, OK, missing fields
- _get_data_snapshot: empty data, partial data, full data
- _load_manifest_version: success and error paths
- async_get_config_entry_diagnostics: full integration test of diagnostics output
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.saxo_portfolio.const import (
    DEFAULT_TIMEZONE,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    MARKET_HOURS,
)
from custom_components.saxo_portfolio.diagnostics import (
    REDACT_KEYS,
    _format_token_status,
    _get_coordinator_status,
    _get_data_snapshot,
    _get_market_config,
    _load_manifest_version,
    async_get_config_entry_diagnostics,
)


# ---------------------------------------------------------------------------
# _get_coordinator_status
# ---------------------------------------------------------------------------


class TestGetCoordinatorStatus:
    """Tests for _get_coordinator_status."""

    def test_minimal_coordinator(self):
        """A bare object with no attributes should produce safe defaults."""
        coordinator = object()
        result = _get_coordinator_status(coordinator)

        assert result["last_update_success"] is None
        assert result["last_update_time"] is None
        assert result["update_interval"] is None
        assert result["configured_timezone"] == "Unknown"
        assert result["is_market_hours"] is None
        assert result["has_data"] is False
        assert result["last_exception"] is None

    def test_with_last_update_time(self):
        """last_update_time should be formatted as ISO when set."""
        coordinator = MagicMock()
        dt = datetime(2026, 1, 15, 10, 30, 0)
        coordinator.last_update_time_utc = dt
        coordinator.last_update_success = True
        coordinator.update_interval = timedelta(minutes=5)
        coordinator.data = {"balance": {}}
        coordinator.last_exception = None
        coordinator._timezone = "Europe/Amsterdam"
        coordinator._is_market_hours.return_value = True

        result = _get_coordinator_status(coordinator)

        assert result["last_update_time"] == dt.isoformat()
        assert result["last_update_success"] is True
        assert result["update_interval"] == str(timedelta(minutes=5))
        assert result["configured_timezone"] == "Europe/Amsterdam"
        assert result["is_market_hours"] is True
        assert result["has_data"] is True

    def test_last_update_time_none(self):
        """When last_update_time_utc is None, output should be None."""
        coordinator = MagicMock()
        coordinator.last_update_time_utc = None
        coordinator.last_exception = None
        coordinator.data = None

        result = _get_coordinator_status(coordinator)
        assert result["last_update_time"] is None
        assert result["has_data"] is False

    def test_last_exception_formatted(self):
        """last_exception should be stringified when present."""
        coordinator = MagicMock()
        coordinator.last_update_time_utc = None
        coordinator.last_exception = ValueError("test error")
        coordinator.data = None

        result = _get_coordinator_status(coordinator)
        assert result["last_exception"] == "test error"

    def test_is_market_hours_not_callable(self):
        """When _is_market_hours is not callable, result should be None."""
        coordinator = MagicMock()
        coordinator._is_market_hours = "not_callable"
        coordinator.last_update_time_utc = None
        coordinator.last_exception = None
        coordinator.data = None

        result = _get_coordinator_status(coordinator)
        assert result["is_market_hours"] is None

    def test_data_is_sentinel_when_missing(self):
        """When coordinator has no data attr at all, has_data should be False."""
        coordinator = MagicMock(spec=[])  # empty spec = no attributes
        result = _get_coordinator_status(coordinator)
        assert result["has_data"] is False


# ---------------------------------------------------------------------------
# _get_market_config
# ---------------------------------------------------------------------------


class TestGetMarketConfig:
    """Tests for _get_market_config."""

    def test_any_timezone(self):
        """'any' timezone should return fixed interval mode."""
        result = _get_market_config("any")

        assert result["mode"] == "Fixed interval (no market hours)"
        assert result["update_interval"] == str(DEFAULT_UPDATE_INTERVAL_ANY)

    def test_known_timezone_new_york(self):
        """A known timezone should return its market hours details."""
        result = _get_market_config("America/New_York")

        assert result["timezone"] == "America/New_York"
        assert result["market_open"] == "09:30"
        assert result["market_close"] == "16:00"
        assert result["trading_days"] == [0, 1, 2, 3, 4]
        assert result["update_interval_market"] == str(
            DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
        )
        assert result["update_interval_after"] == str(
            DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
        )

    def test_known_timezone_amsterdam(self):
        """Amsterdam timezone should have correct open/close."""
        result = _get_market_config("Europe/Amsterdam")

        assert result["market_open"] == "09:00"
        assert result["market_close"] == "17:30"

    @pytest.mark.parametrize("tz", list(MARKET_HOURS.keys()))
    def test_all_known_timezones_produce_valid_config(self, tz):
        """Every timezone in MARKET_HOURS should produce a valid config."""
        result = _get_market_config(tz)
        assert "timezone" in result
        assert "market_open" in result
        assert "market_close" in result

    def test_unknown_timezone(self):
        """An unknown timezone should return an error with fallback."""
        result = _get_market_config("Mars/Olympus_Mons")

        assert "error" in result
        assert "Unknown timezone" in result["error"]
        assert result["fallback"] == DEFAULT_TIMEZONE


# ---------------------------------------------------------------------------
# _format_token_status
# ---------------------------------------------------------------------------


class TestFormatTokenStatus:
    """Tests for _format_token_status."""

    def test_missing_tokens(self):
        """Empty token data should report no tokens."""
        result = _format_token_status({})

        assert result["has_access_token"] is False
        assert result["has_refresh_token"] is False
        assert result["token_type"] == "Unknown"

    def test_has_tokens_no_expiry(self):
        """Tokens present but no expires_at should return basic status only."""
        result = _format_token_status(
            {
                "access_token": "abc",
                "refresh_token": "def",
                "token_type": "Bearer",
            }
        )

        assert result["has_access_token"] is True
        assert result["has_refresh_token"] is True
        assert result["token_type"] == "Bearer"
        assert "expires_at_timestamp" not in result

    def test_expired_token(self):
        """An expired token should have status EXPIRED."""
        expired_at = time.time() - 3600  # 1 hour ago
        result = _format_token_status(
            {"access_token": "abc", "refresh_token": "def", "expires_at": expired_at}
        )

        assert result["is_expired"] is True
        assert result["status"] == "EXPIRED"
        assert result["needs_refresh_soon"] is True
        assert result["needs_refresh_urgent"] is True

    def test_critical_token(self):
        """A token expiring in < 1 minute should have CRITICAL status."""
        expires_at = time.time() + 30  # 30 seconds from now
        result = _format_token_status(
            {"access_token": "abc", "refresh_token": "def", "expires_at": expires_at}
        )

        assert result["is_expired"] is False
        assert "CRITICAL" in result["status"]
        assert result["needs_refresh_urgent"] is True
        assert result["needs_refresh_soon"] is True

    def test_warning_token(self):
        """A token expiring in 1-5 minutes should have WARNING status."""
        expires_at = time.time() + 180  # 3 minutes from now
        result = _format_token_status(
            {"access_token": "abc", "refresh_token": "def", "expires_at": expires_at}
        )

        assert result["is_expired"] is False
        assert "WARNING" in result["status"]
        assert result["needs_refresh_soon"] is True
        assert result["needs_refresh_urgent"] is False

    def test_ok_less_than_hour(self):
        """A token expiring in 5-60 minutes should have OK status with minutes."""
        expires_at = time.time() + 1800  # 30 minutes from now
        result = _format_token_status(
            {"access_token": "abc", "refresh_token": "def", "expires_at": expires_at}
        )

        assert result["is_expired"] is False
        assert result["status"].startswith("OK")
        assert "minutes" in result["status"]
        assert result["needs_refresh_soon"] is False

    def test_ok_more_than_hour(self):
        """A token expiring in > 1 hour should have OK status with hours."""
        expires_at = time.time() + 7200  # 2 hours from now
        result = _format_token_status(
            {"access_token": "abc", "refresh_token": "def", "expires_at": expires_at}
        )

        assert result["is_expired"] is False
        assert result["status"].startswith("OK")
        assert "hours" in result["status"]

    def test_iso_timestamps_present(self):
        """When expires_at is present, ISO timestamps should be included."""
        expires_at = time.time() + 3600
        result = _format_token_status({"access_token": "abc", "expires_at": expires_at})

        assert "expires_at_iso" in result
        assert "current_time_iso" in result
        assert "expires_in_seconds" in result
        assert "expires_in_minutes" in result
        assert "expires_in_hours" in result


# ---------------------------------------------------------------------------
# _get_data_snapshot
# ---------------------------------------------------------------------------


class TestGetDataSnapshot:
    """Tests for _get_data_snapshot."""

    def test_none_data(self):
        """None data should return an empty dict."""
        assert _get_data_snapshot(None) == {}

    def test_empty_dict(self):
        """Empty dict should return an empty dict (falsy)."""
        assert _get_data_snapshot({}) == {}

    def test_full_data(self):
        """Full data should populate all snapshot fields."""
        data = {
            "balance": {"CashAvailableForTrading": 1000},
            "performance": {"returns": 0.05},
            "client": {"ClientId": "12345"},
            "currency": "EUR",
        }
        result = _get_data_snapshot(data)

        assert result["has_balance_data"] is True
        assert result["has_performance_data"] is True
        assert result["has_client_data"] is True
        assert result["currency"] == "EUR"
        assert set(result["data_keys"]) == {
            "balance",
            "performance",
            "client",
            "currency",
        }
        assert result["balance_fields"] == ["CashAvailableForTrading"]

    def test_partial_data_no_balance(self):
        """Data without balance should report has_balance_data as False."""
        data = {"performance": {"returns": 0.05}, "currency": "USD"}
        result = _get_data_snapshot(data)

        assert result["has_balance_data"] is False
        assert result["has_performance_data"] is True
        assert result["has_client_data"] is False
        assert "balance_fields" not in result

    def test_balance_not_dict(self):
        """If balance is not a dict, balance_fields should say so."""
        data = {"balance": "unexpected_string"}
        result = _get_data_snapshot(data)

        assert result["has_balance_data"] is True
        assert result["balance_fields"] == "Not a dict"

    def test_default_currency(self):
        """Missing currency key should default to 'Unknown'."""
        data = {"balance": {}}
        result = _get_data_snapshot(data)

        assert result["currency"] == "Unknown"


# ---------------------------------------------------------------------------
# _load_manifest_version
# ---------------------------------------------------------------------------


class TestLoadManifestVersion:
    """Tests for _load_manifest_version."""

    def test_successful_load(self):
        """Should read version from manifest.json."""
        manifest_content = json.dumps({"version": "1.2.3"})
        with patch.object(Path, "read_text", return_value=manifest_content):
            assert _load_manifest_version() == "1.2.3"

    def test_missing_version_key(self):
        """Missing version key should return 'unknown'."""
        manifest_content = json.dumps({"domain": "saxo_portfolio"})
        with patch.object(Path, "read_text", return_value=manifest_content):
            assert _load_manifest_version() == "unknown"

    def test_file_not_found(self):
        """Missing manifest.json should return 'unknown'."""
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            assert _load_manifest_version() == "unknown"

    def test_invalid_json(self):
        """Invalid JSON should return 'unknown'."""
        with patch.object(Path, "read_text", return_value="not json{{{"):
            assert _load_manifest_version() == "unknown"


# ---------------------------------------------------------------------------
# REDACT_KEYS
# ---------------------------------------------------------------------------


class TestRedactKeys:
    """Tests for the REDACT_KEYS constant."""

    def test_contains_sensitive_keys(self):
        """REDACT_KEYS should contain all expected sensitive field names."""
        expected = {
            "access_token",
            "refresh_token",
            "client_id",
            "client_secret",
            "token",
            "ClientId",
            "ClientKey",
            "AccountId",
            "AccountKey",
            "expires_at",
            "expires_at_timestamp",
            "expires_at_iso",
            "current_time_iso",
            "token_issued_at",
            "token_type",
        }
        assert expected == REDACT_KEYS


# ---------------------------------------------------------------------------
# async_get_config_entry_diagnostics
# ---------------------------------------------------------------------------


class TestAsyncGetConfigEntryDiagnostics:
    """Tests for the main diagnostics entry point."""

    @pytest.mark.asyncio
    async def test_full_diagnostics(self, mock_hass, mock_config_entry):
        """Full diagnostics should contain all top-level sections."""
        coordinator = MagicMock()
        coordinator.last_update_time_utc = datetime(2026, 4, 1, 12, 0, 0)
        coordinator.last_update_success = True
        coordinator.update_interval = timedelta(minutes=15)
        coordinator.data = {
            "balance": {"CashAvailableForTrading": 5000},
            "client": {"ClientId": "SECRET"},
            "currency": "EUR",
        }
        coordinator.last_exception = None
        coordinator._timezone = "any"
        coordinator._is_market_hours.return_value = False

        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        # Top-level sections
        assert "config" in result
        assert "coordinator" in result
        assert "data_snapshot" in result
        assert "market_configuration" in result
        assert "token_status" in result
        assert "integration" in result

    @pytest.mark.asyncio
    async def test_config_section_fields(self, mock_hass, mock_config_entry):
        """Config section should have the expected fields."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_time_utc = None
        coordinator.last_exception = None

        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        config = result["config"]
        assert config["entry_id"] == "test_entry_123"
        assert config["domain"] == "saxo_portfolio"
        assert config["title"] == "Saxo Portfolio"
        assert "has_token" in config
        assert "has_redirect_uri" in config

    @pytest.mark.asyncio
    async def test_sensitive_data_redacted(self, mock_hass, mock_config_entry):
        """Sensitive fields should be redacted in the output."""
        coordinator = MagicMock()
        coordinator.data = {
            "balance": {},
            "client": {"ClientId": "secret_id", "Name": "visible"},
            "currency": "USD",
        }
        coordinator.last_update_time_utc = None
        coordinator.last_update_success = True
        coordinator.update_interval = timedelta(minutes=5)
        coordinator.last_exception = None
        coordinator._timezone = "any"
        coordinator._is_market_hours.return_value = False

        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        # token_status should have its sensitive fields redacted
        # (async_redact_data works recursively)
        # Check that the raw token values don't appear anywhere in the result
        result_str = str(result)
        assert "test_access_token" not in result_str
        assert "test_refresh_token" not in result_str

    @pytest.mark.asyncio
    async def test_no_token_in_entry_data(self, mock_hass, mock_config_entry):
        """When no token is in entry data, token_status should be empty."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_time_utc = None
        coordinator.last_exception = None

        # Remove token from data
        mock_config_entry.data = {"timezone": "any"}
        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        assert result["token_status"] == {}

    @pytest.mark.asyncio
    async def test_integration_section_has_version(self, mock_hass, mock_config_entry):
        """Integration section should include version and sensor info."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_time_utc = None
        coordinator.last_exception = None

        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        integration = result["integration"]
        assert "version" in integration
        assert integration["sensors_configured"] == 16
        assert isinstance(integration["sensor_types"], list)
        assert len(integration["sensor_types"]) == 16

    @pytest.mark.asyncio
    async def test_market_config_for_known_timezone(self, mock_hass, mock_config_entry):
        """When timezone is a known market, diagnostics should include market hours."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_time_utc = None
        coordinator.last_exception = None

        mock_config_entry.data = {
            "timezone": "Europe/Amsterdam",
            "token": {
                "access_token": "tok",
                "refresh_token": "ref",
                "expires_at": time.time() + 7200,
                "token_type": "Bearer",
            },
        }
        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        market = result["market_configuration"]
        assert market["timezone"] == "Europe/Amsterdam"
        assert "market_open" in market

    @pytest.mark.asyncio
    async def test_coordinator_without_data_attr(self, mock_hass, mock_config_entry):
        """When coordinator has no data attribute, diagnostics should not crash."""
        coordinator = MagicMock(spec=[])  # No attributes at all
        # But we need runtime_data.coordinator to work
        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        # hasattr(coordinator, "data") will be False for spec=[]
        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        assert result["data_snapshot"] == {}
