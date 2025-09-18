"""Integration tests for sensor creation and updates.

These tests validate the complete sensor lifecycle from integration setup
to data display, following user validation scenarios from quickstart.md.

⚠️  TDD REQUIREMENT: These tests MUST FAIL initially since no implementation exists.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from custom_components.saxo_portfolio import async_setup_entry
from custom_components.saxo_portfolio.const import DOMAIN
from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.sensor import (
    SaxoCashBalanceSensor,
    SaxoTotalValueSensor,
    SaxoAccountIDSensor,
    SaxoNameSensor,
)


@pytest.mark.integration
class TestSensorCreationAndUpdates:
    """Integration tests for complete sensor creation and update cycle."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
        hass.states = Mock()
        hass.states.async_set = AsyncMock()
        hass.config_entries = Mock()
        return hass

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry with OAuth token."""
        config_entry = Mock(spec=ConfigEntry)
        config_entry.entry_id = "test_entry_123"
        config_entry.domain = DOMAIN
        config_entry.data = {
            "token": {
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "expires_at": (datetime.now() + timedelta(hours=1)).timestamp(),
                "token_type": "Bearer",
            }
        }
        return config_entry

    @pytest.fixture
    def mock_saxo_api_data(self):
        """Mock Saxo API response data."""
        return {
            "balance": {
                "CashBalance": 5000.00,
                "Currency": "USD",
                "TotalValue": 125000.00,
                "UnrealizedMarginProfitLoss": 2500.00,
                "OpenPositionsCount": 5,
            },
            "positions": {
                "__count": 2,
                "Data": [
                    {
                        "NetPositionId": "pos_123",
                        "PositionBase": {
                            "AccountId": "acc_001",
                            "Amount": 100,
                            "AssetType": "Stock",
                            "OpenPrice": 150.00,
                            "Status": "Open",
                            "Symbol": "AAPL",
                        },
                        "PositionView": {
                            "CurrentPrice": 155.00,
                            "ProfitLossOnTrade": 500.00,
                            "MarketValue": 15500.00,
                        },
                    }
                ],
            },
            "accounts": {
                "__count": 1,
                "Data": [
                    {
                        "AccountId": "acc_001",
                        "AccountKey": "ak_001",
                        "AccountType": "Normal",
                        "Active": True,
                        "Currency": "USD",
                        "DisplayName": "Main Trading Account",
                    }
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_integration_setup_creates_coordinator(
        self, mock_hass, mock_config_entry
    ):
        """Test that integration setup creates DataUpdateCoordinator.

        This validates Step 4.1 from quickstart.md: Check Device Registration
        """
        # This test MUST FAIL initially - no implementation exists

        # Mock the coordinator creation and API calls
        with patch(
            "custom_components.saxo_portfolio.coordinator.SaxoCoordinator"
        ) as mock_coordinator_class:
            mock_coordinator = Mock(spec=SaxoCoordinator)
            mock_coordinator.async_config_entry_first_refresh = AsyncMock(
                return_value=True
            )
            mock_coordinator_class.return_value = mock_coordinator

            # Setup integration
            result = await async_setup_entry(mock_hass, mock_config_entry)

            # Should succeed
            assert result is True

            # Should create coordinator
            mock_coordinator_class.assert_called_once_with(mock_hass, mock_config_entry)

            # Should store coordinator in hass data
            assert DOMAIN in mock_hass.data
            assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_sensor_platform_setup(
        self, mock_hass, mock_config_entry, mock_saxo_api_data
    ):
        """Test that sensor platform creates expected sensors."""
        # This test MUST FAIL initially - no implementation exists

        # Mock coordinator with current data structure
        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "cash_balance": 5000.00,
            "currency": "USD",
            "total_value": 125000.00,
            "non_margin_positions_value": 120000.00,
            "ytd_earnings_percentage": 15.5,
            "investment_performance_percentage": 25.0,
            "ytd_investment_performance_percentage": 12.5,
            "cash_transfer_balance": 1000.00,
            "client_id": "123456",
            "account_id": "ACC001",
            "display_name": "Main Trading Account",
            "last_updated": datetime.now().isoformat(),
        }
        mock_coordinator.get_client_id = Mock(return_value="123456")
        mock_coordinator.get_account_id = Mock(return_value="ACC001")
        mock_coordinator.get_client_name = Mock(return_value="Main Trading Account")

        # Setup sensor platform
        from custom_components.saxo_portfolio.sensor import (
            async_setup_entry as setup_sensors,
        )

        mock_add_entities = Mock()

        await setup_sensors(mock_hass, mock_config_entry, mock_add_entities)

        # Should create and add sensor entities
        mock_add_entities.assert_called_once()

        # Get the sensors that were created
        call_args = mock_add_entities.call_args
        sensors = call_args[0][0]  # First argument (entities list)

        # Should create 16 sensors total
        assert len(sensors) == 16

        # Should create expected sensor classes
        sensor_classes = [type(sensor).__name__ for sensor in sensors]
        expected_classes = [
            "SaxoCashBalanceSensor",
            "SaxoTotalValueSensor",
            "SaxoNonMarginPositionsValueSensor",
            "SaxoAccumulatedProfitLossSensor",
            "SaxoInvestmentPerformanceSensor",
            "SaxoCashTransferBalanceSensor",
            "SaxoYTDInvestmentPerformanceSensor",
            "SaxoMonthInvestmentPerformanceSensor",
            "SaxoQuarterInvestmentPerformanceSensor",
            "SaxoClientIDSensor",
            "SaxoAccountIDSensor",
            "SaxoNameSensor",
            "SaxoTokenExpirySensor",
            "SaxoMarketStatusSensor",
            "SaxoLastUpdateSensor",
            "SaxoTimezoneSensor",
        ]

        for expected_class in expected_classes:
            assert expected_class in sensor_classes

    @pytest.mark.asyncio
    async def test_sensor_state_updates_from_coordinator_data(
        self, mock_hass, mock_config_entry
    ):
        """Test that sensors update their state when coordinator data changes."""
        # This test MUST FAIL initially - no implementation exists

        # Create mock coordinator with current data structure
        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "total_value": 100000.00,
            "currency": "USD",
            "last_updated": datetime.now().isoformat(),
        }
        mock_coordinator.last_update_success = True
        mock_coordinator.get_total_value = Mock(return_value=100000.00)
        mock_coordinator.get_currency = Mock(return_value="USD")

        # Create sensor using actual sensor class
        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Initial state should reflect coordinator data
        initial_state = sensor.native_value
        assert float(initial_state) == 100000.00

        # Update coordinator data
        mock_coordinator.data["total_value"] = 110000.00
        mock_coordinator.get_total_value = Mock(return_value=110000.00)

        # Sensor state should update
        updated_state = sensor.native_value
        assert float(updated_state) == 110000.00

    @pytest.mark.asyncio
    async def test_sensor_attributes_populated_correctly(
        self, mock_hass, mock_config_entry
    ):
        """Test that sensor attributes are populated with correct metadata."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "total_value": 125000.00,
            "currency": "USD",
            "last_updated": "2023-12-01T10:30:00Z",
        }
        mock_coordinator.get_currency = Mock(return_value="USD")

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Check sensor attributes
        attributes = sensor.extra_state_attributes
        assert isinstance(attributes, dict)

        # Required attributes for balance sensors
        assert "attribution" in attributes
        assert "currency" in attributes
        assert "last_updated" in attributes

        # Validate attribute values
        assert attributes["currency"] == "USD"
        assert "Saxo" in attributes["attribution"]
        assert attributes["last_updated"] == "2023-12-01T10:30:00Z"

    @pytest.mark.asyncio
    async def test_sensor_unique_ids_generated(self, mock_hass, mock_config_entry):
        """Test that sensors have unique IDs for entity registry."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.config_entry = mock_config_entry
        mock_coordinator.get_client_id = Mock(return_value="123456")

        # Create multiple sensors using actual sensor classes
        total_value_sensor = SaxoTotalValueSensor(mock_coordinator)
        cash_balance_sensor = SaxoCashBalanceSensor(mock_coordinator)
        account_id_sensor = SaxoAccountIDSensor(mock_coordinator)

        # Each sensor should have unique ID
        unique_ids = {
            total_value_sensor.unique_id,
            cash_balance_sensor.unique_id,
            account_id_sensor.unique_id,
        }
        assert len(unique_ids) == 3  # All different

        # Unique IDs should follow saxo_{client_id}_{sensor_type} pattern
        assert total_value_sensor.unique_id == "saxo_123456_total_value"
        assert cash_balance_sensor.unique_id == "saxo_123456_cash_balance"
        assert account_id_sensor.unique_id == "saxo_123456_account_id"

    @pytest.mark.asyncio
    async def test_sensor_availability_based_on_coordinator_state(
        self, mock_hass, mock_config_entry
    ):
        """Test sensor availability tracking with improved sticky logic."""
        from datetime import timedelta

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.get_client_id = Mock(return_value="123456")
        mock_coordinator.update_interval = timedelta(minutes=5)

        # Scenario 1: Coordinator with successful data - should be available
        mock_coordinator.last_update_success = True
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_successful_update_time = datetime.now() - timedelta(
            minutes=1
        )

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Sensor should be available
        assert sensor.available is True

        # Scenario 2: Temporary failure during update - should stay available
        mock_coordinator.last_update_success = False  # Update in progress
        mock_coordinator.last_successful_update_time = datetime.now() - timedelta(
            minutes=2
        )

        # Sensor should still be available (sticky availability)
        assert sensor.available is True

        # Scenario 3: Genuine sustained failure - should be unavailable
        mock_coordinator.last_update_success = False
        mock_coordinator.data = None  # No data available

        # Sensor should be unavailable when there's no data
        assert sensor.available is False

    @pytest.mark.asyncio
    async def test_account_diagnostic_sensors_created(
        self, mock_hass, mock_config_entry
    ):
        """Test that account diagnostic sensors are created with correct data."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.get_client_id = Mock(return_value="123456")
        mock_coordinator.get_account_id = Mock(return_value="ACC001")
        mock_coordinator.get_client_name = Mock(return_value="Main Trading Account")

        # Create account diagnostic sensors
        account_id_sensor = SaxoAccountIDSensor(mock_coordinator)
        name_sensor = SaxoNameSensor(mock_coordinator)

        # Sensors should have different unique IDs
        assert account_id_sensor.unique_id != name_sensor.unique_id

        # Sensors should reflect account data
        assert account_id_sensor.native_value == "ACC001"
        assert name_sensor.native_value == "Main Trading Account"

        # Should have proper entity IDs
        assert account_id_sensor.entity_id == "sensor.saxo_123456_account_id"
        assert name_sensor.entity_id == "sensor.saxo_123456_name"

    @pytest.mark.asyncio
    async def test_sensor_entity_registry_integration(
        self, mock_hass, mock_config_entry
    ):
        """Test sensors integrate properly with Home Assistant entity registry."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.config_entry = mock_config_entry
        mock_coordinator.get_client_id = Mock(return_value="123456")
        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Should have device info for grouping
        device_info = sensor.device_info
        assert isinstance(device_info, dict)
        assert "identifiers" in device_info
        assert "name" in device_info
        assert device_info["name"] == "Saxo 123456 Portfolio"

        # Should not have firmware version
        assert device_info.get("sw_version") is None, (
            "Firmware version should not be displayed"
        )

    @pytest.mark.asyncio
    async def test_sensor_state_transitions_during_updates(
        self, mock_hass, mock_config_entry
    ):
        """Test sensor state transitions during coordinator updates."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.get_client_id = Mock(return_value="123456")

        # Initial state - no data
        mock_coordinator.data = None
        mock_coordinator.last_update_success = False
        mock_coordinator.get_total_value = Mock(return_value=None)

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Should be unavailable initially
        assert sensor.native_value is None

        # Data becomes available
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_update_success = True
        mock_coordinator.get_total_value = Mock(return_value=100000.00)

        # Should show actual value
        assert float(sensor.native_value) == 100000.00

        # Data update fails
        mock_coordinator.last_update_success = False
        # But data is still there (coordinator keeps last good data)

        # Should still show last good value (coordinator keeps data)
        assert float(sensor.native_value) == 100000.00

    @pytest.mark.asyncio
    async def test_sensor_sticky_availability_during_updates(
        self, mock_hass, mock_config_entry
    ):
        """Test that sensors don't flash unavailable during normal coordinator updates."""
        from datetime import timedelta

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.get_client_id = Mock(return_value="123456")
        mock_coordinator.get_total_value = Mock(return_value=100000.00)
        mock_coordinator.get_currency = Mock(return_value="USD")
        mock_coordinator.update_interval = timedelta(minutes=5)

        # Start with successful state
        mock_coordinator.last_update_success = True
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_successful_update_time = datetime.now() - timedelta(
            minutes=1
        )

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Initially available
        assert sensor.available is True
        assert sensor.native_value == 100000.00

        # Simulate coordinator update cycle (temporary failure state)
        mock_coordinator.last_update_success = (
            False  # Coordinator sets this False during update
        )
        # Data and last_successful_update_time remain from previous successful update

        # Sensor should remain available during update cycle
        assert sensor.available is True, (
            "Sensor should stay available during coordinator update"
        )
        assert sensor.native_value == 100000.00, (
            "Sensor should keep showing data during update"
        )

        # Update completes successfully
        mock_coordinator.last_update_success = True
        mock_coordinator.last_successful_update_time = datetime.now()

        # Sensor should still be available
        assert sensor.available is True
        assert sensor.native_value == 100000.00

    @pytest.mark.asyncio
    async def test_sensor_availability_different_sensor_types(
        self, mock_hass, mock_config_entry
    ):
        """Test availability logic works consistently across different sensor types."""
        from datetime import timedelta

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.get_client_id = Mock(return_value="123456")
        mock_coordinator.get_total_value = Mock(return_value=100000.00)
        mock_coordinator.get_cash_balance = Mock(return_value=5000.00)
        mock_coordinator.get_client_name = Mock(return_value="Test Account")
        mock_coordinator.update_interval = timedelta(minutes=5)

        # Setup coordinator state
        mock_coordinator.last_update_success = False  # Simulating update in progress
        mock_coordinator.data = {"total_value": 100000.00, "cash_balance": 5000.00}
        mock_coordinator.last_successful_update_time = datetime.now() - timedelta(
            minutes=2
        )

        # Test different sensor types
        total_value_sensor = SaxoTotalValueSensor(mock_coordinator)
        cash_balance_sensor = SaxoCashBalanceSensor(mock_coordinator)
        name_sensor = SaxoNameSensor(mock_coordinator)  # Diagnostic sensor

        # Balance sensors should use sticky availability
        assert total_value_sensor.available is True, (
            "Total value sensor should use sticky availability"
        )
        assert cash_balance_sensor.available is True, (
            "Cash balance sensor should use sticky availability"
        )

        # Diagnostic sensors may have different availability logic
        assert name_sensor.available is True, "Name sensor should be available"
