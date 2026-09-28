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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import EntityCategory

from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.data import (
    BalanceData,
    ClientInfo,
    PerformanceData,
    SaxoPortfolioData,
)
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


@pytest.fixture(autouse=True)
def _mock_entity_registry():
    """Provide an (empty by default) entity registry for mock hass."""
    with (
        patch("custom_components.saxo_portfolio.diagnostics.er.async_get"),
        patch(
            "custom_components.saxo_portfolio.diagnostics.er.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# _get_coordinator_status
# ---------------------------------------------------------------------------


def _mock_coordinator(**attrs) -> MagicMock:
    """Build a coordinator mock limited to SaxoCoordinator's real interface."""
    coordinator = MagicMock(spec=SaxoCoordinator)
    coordinator.last_successful_update_time = None
    coordinator.last_update_success = True
    coordinator.update_interval = timedelta(minutes=5)
    coordinator.data = None
    coordinator.last_exception = None
    coordinator.timezone = "any"
    coordinator.is_market_hours = False
    coordinator.get_positions.return_value = {}
    for name, value in attrs.items():
        setattr(coordinator, name, value)
    return coordinator


def _data(
    balance: BalanceData | None = None,
    performance: PerformanceData | None = None,
    client: ClientInfo | None = None,
) -> SaxoPortfolioData:
    return SaxoPortfolioData(
        balance=balance or BalanceData(),
        performance=performance or PerformanceData(),
        client=client or ClientInfo(),
        last_updated=datetime(2026, 1, 1, 12, 0),
    )


class TestGetCoordinatorStatus:
    """Tests for _get_coordinator_status."""

    def test_no_data_yet(self):
        """A coordinator before its first update reports safe values."""
        result = _get_coordinator_status(_mock_coordinator())

        assert result["last_update_success"] is True
        assert result["last_update_time"] is None
        assert result["update_interval"] == str(timedelta(minutes=5))
        assert result["configured_timezone"] == "any"
        assert result["is_market_hours"] is False
        assert result["has_data"] is False
        assert result["last_exception"] is None

    def test_with_last_update_time(self):
        """last_update_time is the last successful update, as ISO."""
        dt = datetime(2026, 1, 15, 10, 30, 0)
        coordinator = _mock_coordinator(
            last_successful_update_time=dt,
            data=_data(),
            timezone="Europe/Amsterdam",
            is_market_hours=True,
        )

        result = _get_coordinator_status(coordinator)

        assert result["last_update_time"] == dt.isoformat()
        assert result["last_update_success"] is True
        assert result["update_interval"] == str(timedelta(minutes=5))
        assert result["configured_timezone"] == "Europe/Amsterdam"
        assert result["is_market_hours"] is True
        assert result["has_data"] is True

    def test_uses_public_properties(self):
        """Timezone and market status come from the public coordinator API."""
        coordinator = _mock_coordinator(timezone="America/New_York")
        coordinator.is_market_hours = True
        result = _get_coordinator_status(coordinator)
        assert result["configured_timezone"] == "America/New_York"
        assert result["is_market_hours"] is True

    def test_last_exception_formatted(self):
        """last_exception should be stringified when present."""
        coordinator = _mock_coordinator(last_exception=ValueError("test error"))

        result = _get_coordinator_status(coordinator)
        assert result["last_exception"] == "test error"


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

    def test_full_data(self):
        """Typed coordinator data populates all snapshot fields."""
        data = _data(
            balance=BalanceData(
                cash_balance=1000.0,
                currency="EUR",
                total_value=5000.0,
                non_margin_positions_value=4000.0,
            ),
            performance=PerformanceData(investment_performance_percentage=5.0),
            client=ClientInfo(
                client_id="12345", account_id="A1", client_name="Someone"
            ),
        )
        result = _get_data_snapshot(data)

        assert result["has_balance_data"] is True
        assert result["has_performance_data"] is True
        assert result["has_client_data"] is True
        assert result["currency"] == "EUR"
        assert result["data_keys"] == data.field_names
        assert "cash_balance" in result["data_keys"]
        assert "client_id" in result["data_keys"]
        # Only key names and flags - never the values
        assert "12345" not in str(result)
        assert "5000.0" not in str(result)
        assert "Someone" not in str(result)

    def test_partial_data_no_balance(self):
        """Non-numeric balance values report has_balance_data as False."""
        data = _data(
            balance=BalanceData.from_api(
                {
                    "CashBalance": None,
                    "TotalValue": None,
                    "NonMarginPositionsValue": None,
                    "Currency": "USD",
                }
            ),
            performance=PerformanceData(investment_performance_percentage=1.5),
        )
        result = _get_data_snapshot(data)

        assert result["has_balance_data"] is False
        assert result["has_performance_data"] is True
        assert result["has_client_data"] is False

    def test_non_numeric_balance_is_not_balance_data(self):
        """Non-numeric balance values do not count as balance data."""
        data = _data(
            balance=BalanceData.from_api(
                {
                    "CashBalance": "unexpected_string",
                    "TotalValue": None,
                    "NonMarginPositionsValue": {},
                }
            )
        )
        result = _get_data_snapshot(data)

        assert result["has_balance_data"] is False

    def test_default_currency(self):
        """A balance without a currency reports the USD default."""
        data = _data(balance=BalanceData.from_api({"CashBalance": 1.0}))
        result = _get_data_snapshot(data)

        assert result["currency"] == "USD"


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
            "title",
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
        coordinator = _mock_coordinator(
            last_successful_update_time=datetime(2026, 4, 1, 12, 0, 0),
            update_interval=timedelta(minutes=15),
            data=_data(
                balance=BalanceData(cash_balance=5000.0, currency="EUR"),
                client=ClientInfo(client_id="SECRET"),
            ),
        )

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
        assert result["data_snapshot"]["position_count"] == 0
        assert "SECRET" not in str(result)
        assert "5000.0" not in str(result)

    @pytest.mark.asyncio
    async def test_config_section_fields(self, mock_hass, mock_config_entry):
        """Config section should have the expected fields."""
        coordinator = _mock_coordinator()

        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        config = result["config"]
        assert config["entry_id"] == "test_entry_123"
        assert config["domain"] == "saxo_portfolio"
        # Title embeds the ClientId once known, so it is redacted
        assert config["title"] == "**REDACTED**"
        assert "has_token" in config
        assert "has_redirect_uri" in config

    @pytest.mark.asyncio
    async def test_sensitive_data_redacted(self, mock_hass, mock_config_entry):
        """Sensitive fields should be redacted in the output."""
        coordinator = _mock_coordinator(
            data=_data(client=ClientInfo(client_id="secret_id", client_name="visible"))
        )

        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        # token_status should have its sensitive fields redacted
        # (async_redact_data works recursively)
        # Check that the raw token values don't appear anywhere in the result
        result_str = str(result)
        assert "test_access_token" not in result_str
        assert "test_refresh_token" not in result_str
        assert "secret_id" not in result_str

    @pytest.mark.asyncio
    async def test_no_token_in_entry_data(self, mock_hass, mock_config_entry):
        """When no token is in entry data, token_status should be empty."""
        coordinator = _mock_coordinator()

        # Remove token from data
        mock_config_entry.data = {"timezone": "any"}
        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        assert result["token_status"] == {}

    @pytest.mark.asyncio
    async def test_integration_section_has_version(self, mock_hass, mock_config_entry):
        """Integration section should include version and sensor info."""
        coordinator = _mock_coordinator()

        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        integration = result["integration"]
        assert "version" in integration
        # No registered entities (e.g. sensor setup skipped) -> zero, not 16
        assert integration["sensors_configured"] == 0
        assert integration["sensor_types"] == []

    @pytest.mark.asyncio
    async def test_market_config_for_known_timezone(self, mock_hass, mock_config_entry):
        """When timezone is a known market, diagnostics should include market hours."""
        coordinator = _mock_coordinator()

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
    async def test_coordinator_without_data(self, mock_hass, mock_config_entry):
        """Before the first update there is no data snapshot."""
        coordinator = _mock_coordinator()
        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        assert result["data_snapshot"] == {}
        assert result["coordinator"]["has_data"] is False


# ---------------------------------------------------------------------------
# Real data availability and sensor inventory (issue #17)
# ---------------------------------------------------------------------------


async def _updated_coordinator(mock_hass, mock_config_entry, mock_oauth_session):
    """Run a real coordinator update against fixture API responses."""
    from custom_components.saxo_portfolio.coordinator import SaxoCoordinator

    from .test_log_sanitization import _fake_session

    mock_config_entry.options = {"enable_position_sensors": True}
    coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
    coordinator.config_entry = mock_config_entry
    with (
        patch(
            "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
            return_value=_fake_session(),
        ),
        patch(
            "custom_components.saxo_portfolio.coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        coordinator.data = await coordinator._async_update_data()
    coordinator.last_update_success = True
    return coordinator


async def _created_sensor_entities(mock_hass, mock_config_entry, coordinator):
    """Collect the entities the sensor platform actually creates."""
    from custom_components.saxo_portfolio.sensor import async_setup_entry

    mock_config_entry.runtime_data = MagicMock()
    mock_config_entry.runtime_data.coordinator = coordinator
    # The position listener would schedule real refreshes; not needed here.
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    created: list = []
    await async_setup_entry(
        mock_hass, mock_config_entry, lambda ents, *_: created.extend(ents)
    )
    return created


def _registry_entries_for(entities: list) -> list[MagicMock]:
    """Mimic entity-registry entries for created entities (plus a button)."""
    entries = []
    for entity in entities:
        entry = MagicMock()
        entry.domain = "sensor"
        entry.translation_key = entity.translation_key
        entry.entity_category = entity.entity_category
        entry.disabled_by = None
        entries.append(entry)
    button = MagicMock()
    button.domain = "button"
    button.translation_key = "refresh"
    button.entity_category = None
    button.disabled_by = None
    entries.append(button)
    return entries


class TestRealDataAvailability:
    """Flags and sensor inventory reflect what the integration really has."""

    @pytest.mark.asyncio
    async def test_healthy_entry_flags_and_sensor_inventory(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """A healthy entry reports true flags and the real sensor inventory."""
        from .test_log_sanitization import FORBIDDEN

        coordinator = await _updated_coordinator(
            mock_hass, mock_config_entry, mock_oauth_session
        )
        entities = await _created_sensor_entities(
            mock_hass, mock_config_entry, coordinator
        )
        mock_config_entry.title = (
            f"Saxo Portfolio ({coordinator.client_info.client_id})"
        )

        with patch(
            "custom_components.saxo_portfolio.diagnostics.er.async_entries_for_config_entry",
            return_value=_registry_entries_for(entities),
        ):
            result = await async_get_config_entry_diagnostics(
                mock_hass, mock_config_entry
            )

        snapshot = result["data_snapshot"]
        assert snapshot["has_balance_data"] is True
        assert snapshot["has_performance_data"] is True
        assert snapshot["has_client_data"] is True
        assert snapshot["position_count"] == 1

        integration = result["integration"]
        assert integration["sensors_configured"] == len(entities)
        expected_diagnostic = sum(
            1 for e in entities if e.entity_category == EntityCategory.DIAGNOSTIC
        )
        assert expected_diagnostic > 0
        assert integration["diagnostic_sensors"] == expected_diagnostic
        assert integration["position_sensors"] == 1
        types = integration["sensor_types"]
        assert "ytd_profit_loss" in types
        assert "ytd_cash_transfer" in types
        assert "cash_balance" in types
        # Per-position keys (which embed symbols) are counted, not listed.
        assert not any(t.startswith("position") for t in types)
        assert len(types) == len(entities) - 1
        assert "refresh" not in types

        # Still fully redacted: no fixture identifiers, balances or tokens.
        result_str = str(result)
        leaked = [v for v in FORBIDDEN if v in result_str]
        assert not leaked, f"Diagnostics leaked: {leaked}"

    def test_flags_false_without_performance_or_client_data(self):
        """Balance-only data (performance never fetched) is reported honestly."""
        data = _data(
            balance=BalanceData(
                cash_balance=1.0,
                currency="EUR",
                total_value=2.0,
                non_margin_positions_value=1.0,
            )
        )
        result = _get_data_snapshot(data)
        assert result["has_balance_data"] is True
        assert result["has_performance_data"] is False
        assert result["has_client_data"] is False

    def test_flags_false_without_balance(self):
        """Data without balance keys reports has_balance_data False."""
        result = _get_data_snapshot(
            _data(
                balance=BalanceData(
                    cash_balance=None,
                    currency="EUR",
                    total_value=None,
                    non_margin_positions_value=None,
                ),
                client=ClientInfo(client_id="C1"),
            )
        )
        assert result["has_balance_data"] is False
        assert result["has_client_data"] is True
