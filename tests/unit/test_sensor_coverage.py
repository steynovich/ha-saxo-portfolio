"""Unit tests for sensor.py to achieve 95%+ coverage."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.saxo_portfolio.coordinator import PositionData, SaxoCoordinator
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
    SaxoYTDInvestmentPerformanceSensor,
    _setup_position_listener,
    async_setup_entry,
)


@pytest.fixture
def coord():
    """Create a mock coordinator."""
    c = MagicMock(spec=SaxoCoordinator)
    c.get_client_id.return_value = "TEST123"
    c.get_currency.return_value = "EUR"
    c.get_client_name.return_value = "Test User"
    c.get_cash_balance.return_value = 1000.50
    c.get_total_value.return_value = 50000.0
    c.get_non_margin_positions_value.return_value = 48000.0
    c.get_ytd_earnings_percentage.return_value = 5.5
    c.get_investment_performance_percentage.return_value = 12.34
    c.get_ytd_investment_performance_percentage.return_value = 8.76
    c.get_month_investment_performance_percentage.return_value = 2.1
    c.get_quarter_investment_performance_percentage.return_value = 3.45
    c.get_cash_transfer_balance.return_value = 10000.0
    c.get_account_id.return_value = "ACC456"
    c.last_update_success = True
    c.data = {
        "cash_balance": 1000.50,
        "total_value": 50000.0,
        "last_updated": "2026-01-01T12:00:00",
        "ytd_earnings_percentage": 5.5,
        "investment_performance_percentage": 12.34,
        "cash_transfer_balance": 10000.0,
    }
    c.config_entry = MagicMock()
    c.config_entry.entry_id = "test_entry"
    c.config_entry.data = {
        "token": {"expires_at": time.time() + 3600, "access_token": "test"},
        "timezone": "Europe/Amsterdam",
    }
    c.update_interval = timedelta(minutes=5)
    c._performance_last_updated = datetime(2026, 1, 1, 12, 0)
    c._timezone = "Europe/Amsterdam"
    c._is_market_hours.return_value = True
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
        # 16 base + 1 market data + 1 position = 18
        assert len(entities) >= 17
        coord.mark_sensors_initialized.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_skips_unknown_client(self, coord):
        coord.get_client_name.return_value = "unknown"
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
        assert len(entities) == 16  # No position or market data sensors


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
        type(sensor).coordinator = PropertyMock(return_value=coord)
        info = sensor.device_info
        assert info["name"] == "Saxo TEST123 Portfolio"

    def test_extra_state_attributes(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert "attribution" in attrs
        assert attrs["last_updated"] == "2026-01-01T12:00:00"

    def test_extra_state_attributes_no_data(self, coord):
        coord.data = None
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert "last_updated" not in attrs

    def test_available_with_data(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_unavailable_no_data(self, coord):
        coord.data = None
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_available_update_failing_but_recent(self, coord):
        coord.last_update_success = False
        coord.last_successful_update_time = datetime.now()
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_unavailable_sustained_failure(self, coord):
        coord.last_update_success = False
        coord.last_successful_update_time = datetime.now() - timedelta(hours=1)
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        with patch("homeassistant.util.dt.utcnow", return_value=datetime.now()):
            with patch("homeassistant.util.dt.as_utc", side_effect=lambda x: x):
                assert sensor.available is False

    def test_available_no_last_success_time(self, coord):
        coord.last_update_success = False
        coord.last_successful_update_time = None
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_available_no_last_successful_update_attr(self, coord):
        coord.last_update_success = False
        del coord.last_successful_update_time
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
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
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == 1000.50

    def test_total_value(self, coord):
        sensor = SaxoTotalValueSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == 50000.0

    def test_non_margin_value(self, coord):
        sensor = SaxoNonMarginPositionsValueSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == 48000.0

    def test_balance_none_when_no_data(self, coord):
        coord.data = None
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_balance_none_when_update_failed(self, coord):
        coord.last_update_success = False
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_balance_none_when_value_is_nan(self, coord):
        coord.get_cash_balance.return_value = float("nan")
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_balance_none_when_value_is_inf(self, coord):
        coord.get_cash_balance.return_value = float("inf")
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_balance_none_when_exception(self, coord):
        coord.get_cash_balance.side_effect = RuntimeError("fail")
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_balance_none_when_method_returns_none(self, coord):
        coord.get_cash_balance.return_value = None
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_balance_non_numeric_passthrough(self, coord):
        coord.get_cash_balance.return_value = "string_value"
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "string_value"

    def test_balance_extra_attrs_include_currency(self, coord):
        sensor = SaxoCashBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
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
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == 10000.0

    def test_cash_transfer_available(self, coord):
        sensor = SaxoCashTransferBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_cash_transfer_unavailable(self, coord):
        coord.data = {"other_key": 1}
        sensor = SaxoCashTransferBalanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False


class TestAccumulatedProfitLossSensor:
    def test_value(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == 5.5

    def test_none_without_data(self, coord):
        coord.data = None
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_attrs_include_currency(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["currency"] == "EUR"

    def test_available(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_unavailable_no_data_key(self, coord):
        coord.data = {"other": 1}
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_state_class(self, coord):
        sensor = SaxoAccumulatedProfitLossSensor(coord)
        assert sensor._attr_state_class == "measurement"


class TestPerformanceSensors:
    @pytest.mark.parametrize(
        "cls,method,expected,period",
        [
            (
                SaxoInvestmentPerformanceSensor,
                "get_investment_performance_percentage",
                12.34,
                "AllTime",
            ),
            (
                SaxoYTDInvestmentPerformanceSensor,
                "get_ytd_investment_performance_percentage",
                8.76,
                "Year",
            ),
            (
                SaxoMonthInvestmentPerformanceSensor,
                "get_month_investment_performance_percentage",
                2.1,
                "Month",
            ),
            (
                SaxoQuarterInvestmentPerformanceSensor,
                "get_quarter_investment_performance_percentage",
                3.45,
                "Quarter",
            ),
        ],
    )
    def test_performance_value(self, coord, cls, method, expected, period):
        sensor = cls(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == expected
        assert sensor._get_time_period() == period

    def test_performance_none_no_data(self, coord):
        coord.data = None
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_performance_none_update_failed(self, coord):
        coord.last_update_success = False
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_performance_nan_returns_none(self, coord):
        coord.get_investment_performance_percentage.return_value = float("nan")
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_performance_non_numeric_returns_none(self, coord):
        coord.get_investment_performance_percentage.return_value = "not_a_number"
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_performance_exception_returns_none(self, coord):
        coord.get_investment_performance_percentage.side_effect = RuntimeError
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_performance_none_value(self, coord):
        coord.get_investment_performance_percentage.return_value = None
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_performance_extra_attrs(self, coord):
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["time_period"] == "AllTime"
        assert "from" in attrs
        assert attrs["from"] == "inception"

    def test_ytd_period_dates(self, coord):
        sensor = SaxoYTDInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["time_period"] == "Year"
        assert "from" in attrs
        assert "thru" in attrs

    def test_month_period_dates(self, coord):
        sensor = SaxoMonthInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["time_period"] == "Month"

    def test_quarter_period_dates(self, coord):
        sensor = SaxoQuarterInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["time_period"] == "Quarter"

    def test_attrs_no_data(self, coord):
        coord.data = None
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert "time_period" not in attrs

    def test_available_true(self, coord):
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_available_false_none_value(self, coord):
        coord.get_investment_performance_percentage.return_value = None
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_available_false_exception(self, coord):
        coord.get_investment_performance_percentage.side_effect = RuntimeError
        sensor = SaxoInvestmentPerformanceSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_performance_base_get_value_not_implemented(self, coord):
        sensor = SaxoPerformanceSensorBase(coord, "test", "test_key")
        with pytest.raises(NotImplementedError):
            sensor._get_performance_value()

    def test_performance_base_get_period_not_implemented(self, coord):
        sensor = SaxoPerformanceSensorBase(coord, "test", "test_key")
        with pytest.raises(NotImplementedError):
            sensor._get_time_period()

    def test_state_class(self, coord):
        sensor = SaxoInvestmentPerformanceSensor(coord)
        assert sensor._attr_state_class == "measurement"


class TestDiagnosticSensors:
    def test_client_id_value(self, coord):
        sensor = SaxoClientIDSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "TEST123"
        assert sensor._attr_entity_registry_enabled_default is False

    def test_client_id_available(self, coord):
        sensor = SaxoClientIDSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_client_id_unavailable(self, coord):
        coord.get_client_id.return_value = "unknown"
        sensor = SaxoClientIDSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_account_id_value(self, coord):
        sensor = SaxoAccountIDSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "ACC456"
        assert sensor._attr_entity_registry_enabled_default is False

    def test_account_id_unavailable(self, coord):
        coord.get_account_id.return_value = "unknown"
        sensor = SaxoAccountIDSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_name_value(self, coord):
        sensor = SaxoNameSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Test User"
        assert sensor._attr_entity_registry_enabled_default is False

    def test_name_unavailable(self, coord):
        coord.get_client_name.return_value = "unknown"
        sensor = SaxoNameSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_diagnostic_base_always_available(self, coord):
        SaxoClientIDSensor(coord)
        # SaxoDiagnosticSensorBase.available always returns True
        # but SaxoClientIDSensor overrides it
        from custom_components.saxo_portfolio.sensor import SaxoDiagnosticSensorBase

        base = SaxoDiagnosticSensorBase(coord, "test_diag")
        assert base.available is True


class TestTokenExpirySensor:
    def test_expired(self, coord):
        coord.config_entry.data = {"token": {"expires_at": time.time() - 100}}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Expired"

    def test_critical(self, coord):
        coord.config_entry.data = {"token": {"expires_at": time.time() + 30}}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert "Critical" in sensor.native_value

    def test_warning(self, coord):
        coord.config_entry.data = {"token": {"expires_at": time.time() + 200}}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert "Warning" in sensor.native_value

    def test_minutes(self, coord):
        coord.config_entry.data = {"token": {"expires_at": time.time() + 1800}}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert "minutes" in sensor.native_value

    def test_hours(self, coord):
        coord.config_entry.data = {"token": {"expires_at": time.time() + 7200}}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert "hours" in sensor.native_value

    def test_unknown_no_token(self, coord):
        coord.config_entry.data = {}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Unknown"

    def test_extra_attrs(self, coord):
        coord.config_entry.data = {"token": {"expires_at": time.time() + 3600}}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
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
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert len(attrs) == 0

    def test_available_with_token(self, coord):
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_unavailable_no_token(self, coord):
        coord.config_entry.data = {}
        sensor = SaxoTokenExpirySensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False


class TestMarketStatusSensor:
    def test_open(self, coord):
        coord._is_market_hours.return_value = True
        sensor = SaxoMarketStatusSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Market Open"

    def test_closed(self, coord):
        coord._is_market_hours.return_value = False
        sensor = SaxoMarketStatusSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "After Hours"

    def test_fixed_schedule(self, coord):
        coord._timezone = "any"
        sensor = SaxoMarketStatusSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Fixed Schedule"

    def test_extra_attrs(self, coord):
        sensor = SaxoMarketStatusSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert "timezone" in attrs
        assert "update_interval" in attrs


class TestLastUpdateSensor:
    def test_value_with_time(self, coord):
        now = datetime(2026, 1, 1, 12, 0)
        coord.last_successful_update_time = now
        sensor = SaxoLastUpdateSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == now

    def test_value_none(self, coord):
        coord.last_successful_update_time = None
        sensor = SaxoLastUpdateSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_extra_attrs(self, coord):
        sensor = SaxoLastUpdateSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert "update_success" in attrs
        assert "has_data" in attrs

    def test_extra_attrs_with_exception(self, coord):
        coord.last_exception = RuntimeError("test error")
        sensor = SaxoLastUpdateSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert "last_error" in attrs

    def test_available(self, coord):
        sensor = SaxoLastUpdateSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True


class TestTimezoneSensor:
    def test_value(self, coord):
        sensor = SaxoTimezoneSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Europe/Amsterdam"

    def test_value_any(self, coord):
        coord._timezone = "any"
        sensor = SaxoTimezoneSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Any (Fixed Schedule)"

    def test_extra_attrs_market_timezone(self, coord):
        sensor = SaxoTimezoneSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["configured_timezone"] == "Europe/Amsterdam"
        assert "mode" in attrs
        assert attrs["market_hours_detection"] is True

    def test_extra_attrs_any_timezone(self, coord):
        coord._timezone = "any"
        sensor = SaxoTimezoneSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["mode"] == "Fixed interval"
        assert attrs["market_hours_detection"] is False

    def test_extra_attrs_unknown_timezone(self, coord):
        coord._timezone = "Unknown"
        sensor = SaxoTimezoneSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["mode"] == "Unknown configuration"


class TestMarketDataAccessSensor:
    def test_available_true(self, coord):
        sensor = SaxoMarketDataAccessSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Available"

    def test_unavailable_false(self, coord):
        coord.has_market_data_access.return_value = False
        sensor = SaxoMarketDataAccessSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Unavailable"

    def test_unknown(self, coord):
        coord.has_market_data_access.return_value = None
        sensor = SaxoMarketDataAccessSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == "Unknown"

    def test_extra_attrs(self, coord):
        sensor = SaxoMarketDataAccessSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert "has_real_time_prices" in attrs

    def test_entity_category(self, coord):
        sensor = SaxoMarketDataAccessSensor(coord)
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC


class TestPositionSensor:
    def test_value(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == 150.0

    def test_value_none(self, coord):
        coord.get_position.return_value = None
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None

    def test_attrs(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=coord)
        attrs = sensor.extra_state_attributes
        assert attrs["symbol"] == "AAPL"
        assert attrs["amount"] == 10.0

    def test_available_true(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is True

    def test_available_false(self, coord):
        coord.get_position.return_value = None
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.available is False

    def test_name(self, coord):
        sensor = SaxoPositionSensor(coord, "aapl_stock")
        assert sensor._attr_name == "Position AAPL"
        assert sensor._attr_has_entity_name is True
