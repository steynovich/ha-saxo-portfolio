"""Unit tests for sensor.py to achieve 95%+ coverage."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.util import dt as dt_util

from custom_components.saxo_portfolio.coordinator import PositionData, SaxoCoordinator
from custom_components.saxo_portfolio.data import (
    BalanceData,
    ClientInfo,
    PerformanceData,
    SaxoPortfolioData,
)
from custom_components.saxo_portfolio.sensor import (
    PARALLEL_UPDATES,
    SaxoAccumulatedProfitLossSensor,
    SaxoAccountIDSensor,
    SaxoCashBalanceSensor,
    SaxoCashTransferBalanceSensor,
    SaxoClientIDSensor,
    SaxoInvestmentPerformanceSensor,
    SaxoLastUpdateSensor,
    SaxoMarketDataAccessSensor,
    SaxoMarketStatusSensor,
    SaxoMonthInvestmentPerformanceSensor,
    SaxoNameSensor,
    SaxoNonMarginPositionsValueSensor,
    SaxoPerformanceSensorBase,
    SaxoPositionSensor,
    SaxoQuarterInvestmentPerformanceSensor,
    SaxoSensorBase,
    SaxoTimezoneSensor,
    SaxoTokenExpirySensor,
    SaxoTotalValueSensor,
    SaxoYTDCashTransferSensor,
    SaxoYTDInvestmentPerformanceSensor,
    SaxoYTDProfitLossSensor,
    _setup_position_listener,
    async_setup_entry,
)


@pytest.fixture
def coord():
    """Create a mock coordinator."""
    c = MagicMock(spec=SaxoCoordinator)
    c.client_info = ClientInfo(
        client_id="TEST123", account_id="ACC456", client_name="Test User"
    )
    c.last_update_success = True
    c.last_exception = None
    c.data = SaxoPortfolioData(
        balance=BalanceData(
            cash_balance=1000.50,
            currency="EUR",
            total_value=50000.0,
            non_margin_positions_value=48000.0,
        ),
        performance=PerformanceData(
            ytd_earnings_percentage=5.5,
            investment_performance_percentage=12.34,
            ytd_investment_performance_percentage=8.76,
            month_investment_performance_percentage=2.1,
            quarter_investment_performance_percentage=3.45,
            cash_transfer_balance=10000.0,
            ytd_profit_loss=1234.56,
            ytd_cash_transfer=250.0,
        ),
        client=c.client_info,
        last_updated=datetime(2026, 1, 1, 12, 0),
    )
    c.config_entry = MagicMock()
    c.config_entry.entry_id = "test_entry"
    c.config_entry.data = {
        "token": {"expires_at": time.time() + 3600, "access_token": "test"},
        "timezone": "Europe/Amsterdam",
    }
    c.update_interval = timedelta(minutes=5)
    c.performance_last_updated = datetime(2026, 1, 1, 12, 0)
    c.timezone = "Europe/Amsterdam"
    c.is_market_hours = True
    c.position_sensors_enabled = True
    c.get_position_ids.return_value = ["aapl_stock"]
    c.get_positions.return_value = {}
    c.get_position.return_value = PositionData(
        position_id="p1",
        symbol="AAPL",
        description="Apple Inc.",
        asset_type="Stock",
        amount=10.0,
        current_price=150.0,
        market_value=1500.0,
        profit_loss=100.0,
        uic=123,
        currency="USD",
    )
    c.has_market_data_access.return_value = True
    c.last_successful_update_time = datetime.now()
    return c


def _set_balance(coord, **values):
    coord.data = replace(coord.data, balance=replace(coord.data.balance, **values))


def _set_performance(coord, **values):
    coord.data = replace(
        coord.data, performance=replace(coord.data.performance, **values)
    )


def _set_client(coord, **values):
    coord.client_info = replace(coord.client_info, **values)
    coord.data = replace(coord.data, client=coord.client_info)


class TestModuleLevel:
    def test_parallel_updates(self):
        assert PARALLEL_UPDATES == 0


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_setup_with_valid_client(self, coord):
        entry = MagicMock()
        entry.entry_id = "test"
        entry.runtime_data.coordinator = coord
        add_entities = MagicMock()
        await async_setup_entry(MagicMock(), entry, add_entities)
        add_entities.assert_called_once()
        entities = add_entities.call_args[0][0]
        # 18 base + 1 market data + 1 position = 20
        assert len(entities) >= 19
        coord.mark_sensors_initialized.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_skips_unknown_client(self, coord):
        _set_client(coord, client_name="unknown")
        entry = MagicMock()
        entry.runtime_data.coordinator = coord
        add_entities = MagicMock()
        await async_setup_entry(MagicMock(), entry, add_entities)
        add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_setup_without_positions(self, coord):
        coord.position_sensors_enabled = False
        entry = MagicMock()
        entry.entry_id = "test"
        entry.runtime_data.coordinator = coord
        add_entities = MagicMock()
        await async_setup_entry(MagicMock(), entry, add_entities)
        entities = add_entities.call_args[0][0]
        assert len(entities) == 18  # No position or market data sensors


class TestSetupPositionListener:
    def test_listener_creates_new_positions(self, coord):
        coord.get_position_ids.return_value = ["aapl_stock"]
        add_entities = MagicMock()
        _setup_position_listener(MagicMock(), MagicMock(), coord, add_entities)
        # Get the listener callback
        callback = coord.async_add_listener.call_args[0][0]
        # Simulate new position appearing
        coord.get_position_ids.return_value = ["aapl_stock", "tsla_stock"]
        callback()
        add_entities.assert_called_once()


class TestSaxoSensorBase:
    def test_init_sets_attributes(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor._attr_has_entity_name is True
        assert sensor._attr_translation_key == "cash_balance"
        assert sensor._attr_unique_id == "saxo_test123_cash_balance"

    def test_device_info(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        info = sensor.device_info
        assert info["name"] == "Saxo TEST123 Portfolio"

    def test_extra_state_attributes(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        attrs = sensor.extra_state_attributes
        assert "attribution" in attrs
        assert attrs["last_updated"] == "2026-01-01T12:00:00"

    def test_extra_state_attributes_no_data(self, coord):
        coord.data = None
        sensor = SaxoCashBalanceSensor(coord)
        attrs = sensor.extra_state_attributes
        assert "last_updated" not in attrs

    def test_available_with_data(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.available is True

    def test_unavailable_no_data(self, coord):
        coord.data = None
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.available is False

    def test_available_update_failing_but_recent(self, coord):
        coord.last_update_success = False
        coord.last_successful_update_time = datetime.now()
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.available is True

    def test_unavailable_sustained_failure(self, coord):
        coord.last_update_success = False
        coord.last_successful_update_time = datetime.now() - timedelta(hours=1)
        sensor = SaxoCashBalanceSensor(coord)
        with patch("homeassistant.util.dt.utcnow", return_value=datetime.now()):
            with patch("homeassistant.util.dt.as_utc", side_effect=lambda x: x):
                assert sensor.available is False

    def test_available_no_last_success_time(self, coord):
        coord.last_update_success = False
        coord.last_successful_update_time = None
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.available is True

    @pytest.mark.asyncio
    async def test_async_added_to_hass(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        with patch.object(
            SaxoSensorBase.__bases__[0], "async_added_to_hass", new_callable=AsyncMock
        ):
            await sensor.async_added_to_hass()

    @pytest.mark.asyncio
    async def test_async_will_remove_from_hass(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        with patch.object(
            SaxoSensorBase.__bases__[0],
            "async_will_remove_from_hass",
            new_callable=AsyncMock,
        ):
            await sensor.async_will_remove_from_hass()


class TestBalanceSensors:
    def test_cash_balance_value(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value == 1000.50

    def test_total_value(self, coord):
        sensor = SaxoTotalValueSensor(coord)
        assert sensor.native_value == 50000.0

    def test_non_margin_value(self, coord):
        sensor = SaxoNonMarginPositionsValueSensor(coord)
        assert sensor.native_value == 48000.0

    def test_balance_none_when_no_data(self, coord):
        coord.data = None
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value is None

    def test_balance_none_when_update_failed(self, coord):
        coord.last_update_success = False
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value is None

    def test_balance_none_when_value_is_nan(self, coord):
        _set_balance(coord, cash_balance=float("nan"))
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value is None

    def test_balance_none_when_value_is_inf(self, coord):
        _set_balance(coord, cash_balance=float("inf"))
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value is None

    def test_balance_none_when_api_value_not_numeric(self, coord):
        coord.data = replace(
            coord.data, balance=BalanceData.from_api({"CashBalance": "garbage"})
        )
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value is None

    def test_balance_none_when_value_is_none(self, coord):
        _set_balance(coord, cash_balance=None)
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value is None

    def test_balance_value_is_rounded(self, coord):
        _set_balance(coord, cash_balance=1000.5049)
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor.native_value == 1000.5

    def test_balance_extra_attrs_include_currency(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        attrs = sensor.extra_state_attributes
        assert attrs["currency"] == "EUR"

    def test_balance_state_class(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor._attr_state_class == "total"

    def test_balance_device_class(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        assert sensor._attr_device_class == SensorDeviceClass.MONETARY

    def test_cash_transfer_balance(self, coord):
        sensor = SaxoCashTransferBalanceSensor(coord)
        assert sensor.native_value == 10000.0

    def test_cash_transfer_available(self, coord):
        sensor = SaxoCashTransferBalanceSensor(coord)
        assert sensor.available is True

    def test_cash_transfer_unavailable(self, coord):
        coord.data = None
        sensor = SaxoCashTransferBalanceSensor(coord)
        assert sensor.available is False

    def test_cash_transfer_unknown_before_first_fetch(self, coord):
        _set_performance(coord, cash_transfer_balance=None)
        sensor = SaxoCashTransferBalanceSensor(coord)
        assert sensor.available is True
        assert sensor.native_value is None


class TestAccumulatedProfitLossSensor:
    def test_value(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        assert sensor.native_value == 5.5

    def test_none_without_data(self, coord):
        coord.data = None
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        assert sensor.native_value is None

    def test_attrs_include_currency(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        attrs = sensor.extra_state_attributes
        assert attrs["currency"] == "EUR"

    def test_available(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        assert sensor.available is True

    def test_unavailable_no_data(self, coord):
        coord.data = None
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        assert sensor.available is False

    def test_unknown_before_first_fetch(self, coord):
        _set_performance(coord, ytd_earnings_percentage=None)
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        assert sensor.available is True
        assert sensor.native_value is None

    def test_state_class(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        assert sensor._attr_state_class == "measurement"


class TestPerformanceSensors:
    @pytest.mark.parametrize(
        "cls,field,expected,period",
        [
            (
                SaxoInvestmentPerformanceSensor,
                "investment_performance_percentage",
                12.34,
                "AllTime",
            ),
            (
                SaxoYTDInvestmentPerformanceSensor,
                "ytd_investment_performance_percentage",
                8.76,
                "YearToDate",
            ),
            (
                SaxoMonthInvestmentPerformanceSensor,
                "month_investment_performance_percentage",
                2.1,
                "Month",
            ),
            (
                SaxoQuarterInvestmentPerformanceSensor,
                "quarter_investment_performance_percentage",
                3.45,
                "Quarter",
            ),
        ],
    )
    def test_performance_value(self, coord, cls, field, expected, period):
        sensor = cls(coord)
        assert sensor.native_value == expected
        assert sensor.extra_state_attributes["time_period"] == period

        _set_performance(coord, **{field: 1.23456})
        assert sensor.native_value == 1.23

    def test_performance_none_no_data(self, coord):
        coord.data = None
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.native_value is None

    def test_performance_none_update_failed(self, coord):
        coord.last_update_success = False
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.native_value is None

    def test_performance_nan_returns_none(self, coord):
        _set_performance(coord, investment_performance_percentage=float("nan"))
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.native_value is None

    def test_performance_inf_returns_none(self, coord):
        _set_performance(coord, investment_performance_percentage=float("-inf"))
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.native_value is None

    def test_performance_none_value(self, coord):
        _set_performance(coord, investment_performance_percentage=None)
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.native_value is None

    def test_performance_extra_attrs(self, coord):
        sensor = SaxoInvestmentPerformanceSensor(coord)
        attrs = sensor.extra_state_attributes
        assert attrs["time_period"] == "AllTime"
        assert "from" in attrs
        assert attrs["from"] == "inception"

    def test_ytd_period_dates(self, coord):
        """YTD reports the 1 January-anchored window, not StandardPeriod=Year."""
        sensor = SaxoYTDInvestmentPerformanceSensor(coord)
        fixed_now = datetime(2026, 8, 4, 10, 0, tzinfo=dt_util.UTC)
        with patch(
            "custom_components.saxo_portfolio.sensor.dt_util.now",
            return_value=fixed_now,
        ):
            attrs = sensor.extra_state_attributes
        assert attrs["time_period"] == "YearToDate"
        assert attrs["from"] == "2026-01-01"
        assert attrs["thru"] == "2026-08-04"

    # StandardPeriod=Month/Quarter are trailing windows ending at the last
    # completed day: probed on 2026-08-04 the API returned 2026-07-06..2026-08-03
    # (28 days) and 2026-05-05..2026-08-03 (90 days). See
    # docs/superpowers/specs/2026-08-04-ytd-sensors-design.md.
    @pytest.mark.parametrize(
        "cls,period,today,expected_from,expected_thru",
        [
            (
                SaxoMonthInvestmentPerformanceSensor,
                "Month",
                datetime(2026, 8, 4, 10, 0),
                "2026-07-06",
                "2026-08-03",
            ),
            (
                SaxoQuarterInvestmentPerformanceSensor,
                "Quarter",
                datetime(2026, 8, 4, 10, 0),
                "2026-05-05",
                "2026-08-03",
            ),
            # Not calendar-to-date: on the 1st the window still spans the
            # previous month / quarter
            (
                SaxoMonthInvestmentPerformanceSensor,
                "Month",
                datetime(2026, 3, 1, 10, 0),
                "2026-01-31",
                "2026-02-28",
            ),
            (
                SaxoQuarterInvestmentPerformanceSensor,
                "Quarter",
                datetime(2026, 1, 1, 10, 0),
                "2025-10-02",
                "2025-12-31",
            ),
        ],
    )
    def test_trailing_period_dates(
        self, coord, cls, period, today, expected_from, expected_thru
    ):
        sensor = cls(coord)
        with patch(
            "custom_components.saxo_portfolio.sensor.dt_util.now",
            return_value=today.replace(tzinfo=dt_util.UTC),
        ):
            attrs = sensor.extra_state_attributes
        assert attrs["time_period"] == period
        assert attrs["from"] == expected_from
        assert attrs["thru"] == expected_thru

    def test_attrs_no_data(self, coord):
        coord.data = None
        sensor = SaxoInvestmentPerformanceSensor(coord)
        attrs = sensor.extra_state_attributes
        assert "time_period" not in attrs

    def test_available_true(self, coord):
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.available is True

    def test_available_with_unknown_state_when_none(self, coord):
        """A not-yet-fetched value is reported as unknown, not unavailable."""
        _set_performance(coord, investment_performance_percentage=None)
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.available is True
        assert sensor.native_value is None

    def test_available_false_without_data(self, coord):
        coord.data = None
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor.available is False

    def test_performance_base_uses_value_fn_and_period(self, coord):
        sensor = SaxoPerformanceSensorBase(
            coord, "test", lambda data: data.performance.ytd_profit_loss, "Month"
        )
        assert sensor.native_value == 1234.56
        assert sensor.extra_state_attributes["time_period"] == "Month"

    def test_performance_base_unknown_period_has_no_dates(self, coord):
        sensor = SaxoPerformanceSensorBase(
            coord, "test", lambda data: None, "SomethingElse"
        )
        attrs = sensor.extra_state_attributes
        assert "from" not in attrs
        assert "thru" not in attrs

    def test_state_class(self, coord):
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor._attr_state_class == "measurement"


class TestDiagnosticSensors:
    def test_client_id_value(self, coord):
        sensor = SaxoClientIDSensor(coord)
        assert sensor.native_value == "TEST123"
        assert sensor._attr_entity_registry_enabled_default is False

    def test_client_id_available(self, coord):
        sensor = SaxoClientIDSensor(coord)
        assert sensor.available is True

    def test_client_id_unavailable(self, coord):
        _set_client(coord, client_id="unknown")
        sensor = SaxoClientIDSensor(coord)
        assert sensor.available is False

    def test_account_id_value(self, coord):
        sensor = SaxoAccountIDSensor(coord)
        assert sensor.native_value == "ACC456"
        assert sensor._attr_entity_registry_enabled_default is False

    def test_account_id_unavailable(self, coord):
        _set_client(coord, account_id="unknown")
        sensor = SaxoAccountIDSensor(coord)
        assert sensor.available is False

    def test_name_value(self, coord):
        sensor = SaxoNameSensor(coord)
        assert sensor.native_value == "Test User"
        assert sensor._attr_entity_registry_enabled_default is False

    def test_name_unavailable(self, coord):
        _set_client(coord, client_name="unknown")
        sensor = SaxoNameSensor(coord)
        assert sensor.available is False

    def test_diagnostic_base_always_available(self, coord):
        SaxoClientIDSensor(coord)
        # SaxoDiagnosticSensorBase.available always returns True
        # but SaxoClientIDSensor overrides it
        from custom_components.saxo_portfolio.sensor import SaxoDiagnosticSensorBase

        base = SaxoDiagnosticSensorBase(coord, "test_diag")
        assert base.available is True


class TestTokenExpirySensor:
    def test_enum_options(self, coord):
        sensor = SaxoTokenExpirySensor(coord)
        assert sensor.device_class == SensorDeviceClass.ENUM
        assert sensor.options == ["valid", "warning", "critical", "expired"]

    @pytest.mark.parametrize(
        "offset,expected",
        [
            (-100, "expired"),
            (0, "expired"),
            (30, "critical"),
            (60, "critical"),
            (200, "warning"),
            (300, "warning"),
            (1800, "valid"),
            (7200, "valid"),
        ],
    )
    def test_state(self, coord, offset, expected):
        now = 1_800_000_000.0
        coord.config_entry.data = {"token": {"expires_at": now + offset}}
        sensor = SaxoTokenExpirySensor(coord)
        with patch(
            "custom_components.saxo_portfolio.sensor.time.time", return_value=now
        ):
            assert sensor.native_value == expected
        assert sensor.native_value in sensor.options

    def test_unknown_no_token(self, coord):
        coord.config_entry.data = {}
        sensor = SaxoTokenExpirySensor(coord)
        # None renders as HA's own (translated) "unknown" state
        assert sensor.native_value is None

    def test_extra_attrs(self, coord):
        coord.config_entry.data = {"token": {"expires_at": time.time() + 3600}}
        sensor = SaxoTokenExpirySensor(coord)
        attrs = sensor.extra_state_attributes
        # Absolute `expires_at` is intentionally omitted so the state machine
        # doesn't expose exact token-rotation timing to local consumers.
        assert "expires_at" not in attrs
        assert "expires_in_seconds" in attrs
        assert "is_expired" in attrs
        assert "needs_refresh" in attrs

    def test_extra_attrs_no_token(self, coord):
        coord.config_entry.data = {}
        sensor = SaxoTokenExpirySensor(coord)
        attrs = sensor.extra_state_attributes
        assert len(attrs) == 0

    def test_available_with_token(self, coord):
        sensor = SaxoTokenExpirySensor(coord)
        assert sensor.available is True

    def test_unavailable_no_token(self, coord):
        coord.config_entry.data = {}
        sensor = SaxoTokenExpirySensor(coord)
        assert sensor.available is False


class TestMarketStatusSensor:
    def test_enum_options(self, coord):
        sensor = SaxoMarketStatusSensor(coord)
        assert sensor.device_class == SensorDeviceClass.ENUM
        assert sensor.options == ["market_open", "after_hours", "fixed_schedule"]

    def test_open(self, coord):
        coord.is_market_hours = True
        sensor = SaxoMarketStatusSensor(coord)
        assert sensor.native_value == "market_open"

    def test_closed(self, coord):
        coord.is_market_hours = False
        sensor = SaxoMarketStatusSensor(coord)
        assert sensor.native_value == "after_hours"

    def test_fixed_schedule(self, coord):
        coord.timezone = "any"
        sensor = SaxoMarketStatusSensor(coord)
        assert sensor.native_value == "fixed_schedule"

    def test_extra_attrs(self, coord):
        sensor = SaxoMarketStatusSensor(coord)
        attrs = sensor.extra_state_attributes
        assert "timezone" in attrs
        assert "update_interval" in attrs


class TestLastUpdateSensor:
    def test_value_with_time(self, coord):
        now = datetime(2026, 1, 1, 12, 0)
        coord.last_successful_update_time = now
        sensor = SaxoLastUpdateSensor(coord)
        assert sensor.native_value == now

    def test_value_none(self, coord):
        coord.last_successful_update_time = None
        sensor = SaxoLastUpdateSensor(coord)
        assert sensor.native_value is None

    def test_extra_attrs(self, coord):
        sensor = SaxoLastUpdateSensor(coord)
        attrs = sensor.extra_state_attributes
        assert "update_success" in attrs
        assert "has_data" in attrs

    def test_extra_attrs_with_exception(self, coord):
        coord.last_exception = RuntimeError("test error")
        sensor = SaxoLastUpdateSensor(coord)
        attrs = sensor.extra_state_attributes
        assert "last_error" in attrs

    def test_available(self, coord):
        sensor = SaxoLastUpdateSensor(coord)
        assert sensor.available is True


class TestTimezoneSensor:
    def test_value(self, coord):
        sensor = SaxoTimezoneSensor(coord)
        assert sensor.native_value == "Europe/Amsterdam"

    def test_value_any(self, coord):
        coord.timezone = "any"
        sensor = SaxoTimezoneSensor(coord)
        assert sensor.native_value == "Any (Fixed Schedule)"

    def test_extra_attrs_market_timezone(self, coord):
        sensor = SaxoTimezoneSensor(coord)
        attrs = sensor.extra_state_attributes
        assert attrs["configured_timezone"] == "Europe/Amsterdam"
        assert "mode" in attrs
        assert attrs["market_hours_detection"] is True

    def test_extra_attrs_any_timezone(self, coord):
        coord.timezone = "any"
        sensor = SaxoTimezoneSensor(coord)
        attrs = sensor.extra_state_attributes
        assert attrs["mode"] == "Fixed interval"
        assert attrs["market_hours_detection"] is False

    def test_extra_attrs_unknown_timezone(self, coord):
        coord.timezone = "Unknown"
        sensor = SaxoTimezoneSensor(coord)
        attrs = sensor.extra_state_attributes
        assert attrs["mode"] == "Unknown configuration"


class TestMarketDataAccessSensor:
    def test_enum_options(self, coord):
        sensor = SaxoMarketDataAccessSensor(coord)
        assert sensor.device_class == SensorDeviceClass.ENUM
        # Not "unavailable": that is HA's reserved state for unavailable entities
        assert sensor.options == ["available", "not_available"]

    def test_available_true(self, coord):
        sensor = SaxoMarketDataAccessSensor(coord)
        assert sensor.native_value == "available"

    def test_unavailable_false(self, coord):
        coord.has_market_data_access.return_value = False
        sensor = SaxoMarketDataAccessSensor(coord)
        assert sensor.native_value == "not_available"

    def test_unknown(self, coord):
        coord.has_market_data_access.return_value = None
        sensor = SaxoMarketDataAccessSensor(coord)
        # None renders as HA's own (translated) "unknown" state
        assert sensor.native_value is None

    def test_extra_attrs(self, coord):
        sensor = SaxoMarketDataAccessSensor(coord)
        attrs = sensor.extra_state_attributes
        assert "has_real_time_prices" in attrs

    def test_entity_category(self, coord):
        sensor = SaxoMarketDataAccessSensor(coord)
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC


class TestPositionSensor:
    def test_value(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        assert sensor.native_value == 150.0

    def test_value_none(self, coord):
        coord.get_position.return_value = None
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        assert sensor.native_value is None

    def test_attrs(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        attrs = sensor.extra_state_attributes
        assert attrs["symbol"] == "AAPL"
        assert attrs["amount"] == 10.0

    def test_available_true(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        assert sensor.available is True

    def test_available_false(self, coord):
        coord.get_position.return_value = None
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        assert sensor.available is False

    def test_name(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        assert sensor._attr_translation_key == "position"
        assert sensor._attr_translation_placeholders == {"symbol": "AAPL"}
        assert sensor._attr_unique_id == "saxo_test123_position_aapl_stock"
        assert sensor._attr_has_entity_name is True


class TestYTDCurrencySensors:
    def test_ytd_profit_loss_value(self, coord):
        sensor = SaxoYTDProfitLossSensor(coord)
        assert sensor.native_value == pytest.approx(1234.56)

    def test_ytd_profit_loss_state_class(self, coord):
        sensor = SaxoYTDProfitLossSensor(coord)
        assert sensor._attr_state_class == "measurement"

    def test_ytd_profit_loss_unavailable_when_none(self, coord):
        _set_performance(coord, ytd_profit_loss=None)
        sensor = SaxoYTDProfitLossSensor(coord)
        assert sensor.native_value is None
        assert sensor.available is False

    def test_ytd_profit_loss_currency_attr(self, coord):
        sensor = SaxoYTDProfitLossSensor(coord)
        assert sensor.extra_state_attributes["currency"] == "EUR"

    def test_ytd_cash_transfer_value(self, coord):
        sensor = SaxoYTDCashTransferSensor(coord)
        assert sensor.native_value == pytest.approx(250.0)

    def test_ytd_cash_transfer_state_class(self, coord):
        sensor = SaxoYTDCashTransferSensor(coord)
        assert sensor._attr_state_class == "total"

    def test_ytd_cash_transfer_unavailable_when_none(self, coord):
        _set_performance(coord, ytd_cash_transfer=None)
        sensor = SaxoYTDCashTransferSensor(coord)
        assert sensor.native_value is None
        assert sensor.available is False

    def test_ytd_cash_transfer_last_reset_is_jan_1_current_year(self, coord):
        sensor = SaxoYTDCashTransferSensor(coord)
        last_reset = sensor.last_reset

        now = dt_util.now()
        assert last_reset.year == now.year
        assert last_reset.month == 1
        assert last_reset.day == 1
        assert last_reset.tzinfo is not None

    def test_ytd_cash_transfer_last_reset_is_recomputed_not_frozen(self, coord):
        """last_reset must be a property re-derived from the current time.

        A value fixed at __init__ would go stale on 1 January until Home
        Assistant restarts; simulating a year change must shift the
        reported last_reset accordingly.
        """
        sensor = SaxoYTDCashTransferSensor(coord)

        next_year = dt_util.now().year + 1
        future = dt_util.now().replace(year=next_year, month=1, day=2)
        with patch(
            "custom_components.saxo_portfolio.sensor.dt_util.now",
            return_value=future,
        ):
            last_reset = sensor.last_reset

        assert last_reset.year == next_year
        assert last_reset.month == 1
        assert last_reset.day == 1
        assert last_reset.tzinfo is not None


_PKG_ROOT = Path(__file__).parents[2] / "custom_components" / "saxo_portfolio"
_TRANSLATION_FILES = [
    _PKG_ROOT / "strings.json",
    *sorted((_PKG_ROOT / "translations").glob("*.json")),
]


class TestEnumStateTranslations:
    """Every ENUM diagnostic sensor option is translated in every language."""

    @pytest.mark.parametrize(
        "cls",
        [SaxoMarketStatusSensor, SaxoTokenExpirySensor, SaxoMarketDataAccessSensor],
    )
    @pytest.mark.parametrize("path", _TRANSLATION_FILES, ids=lambda p: p.name)
    def test_all_options_translated(self, coord, cls, path):
        assert len(_TRANSLATION_FILES) == 12  # strings.json + 11 languages
        sensor = cls(coord)
        states = json.loads(path.read_text())["entity"]["sensor"][
            sensor.translation_key
        ]["state"]
        assert set(states) == set(sensor.options)
        assert all(isinstance(v, str) and v for v in states.values())
