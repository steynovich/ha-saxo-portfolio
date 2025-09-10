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
from custom_components.saxo_portfolio.sensor import SaxoPortfolioSensor


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

        # Mock coordinator with data
        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "portfolio": {
                "total_value": 125000.00,
                "cash_balance": 5000.00,
                "unrealized_pnl": 2500.00,
                "positions_count": 5,
                "currency": "USD",
            },
            "accounts": [{"account_id": "acc_001", "balance": 50000.00}],
            "positions": [{"position_id": "pos_123", "current_value": 15500.00}],
            "last_updated": datetime.now().isoformat(),
        }

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

        # Should create expected sensor types
        sensor_types = [
            sensor._sensor_type for sensor in sensors if hasattr(sensor, "_sensor_type")
        ]
        expected_types = [
            "total_value",
            "cash_balance",
            "unrealized_pnl",
            "positions_count",
        ]

        for expected_type in expected_types:
            assert expected_type in sensor_types

    @pytest.mark.asyncio
    async def test_sensor_state_updates_from_coordinator_data(
        self, mock_hass, mock_config_entry
    ):
        """Test that sensors update their state when coordinator data changes."""
        # This test MUST FAIL initially - no implementation exists

        # Create mock coordinator
        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "portfolio": {"total_value": 100000.00, "currency": "USD"},
            "last_updated": datetime.now().isoformat(),
        }

        # Create sensor
        sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")

        # Initial state should reflect coordinator data
        initial_state = sensor.state
        assert float(initial_state) == 100000.00

        # Update coordinator data
        mock_coordinator.data["portfolio"]["total_value"] = 110000.00

        # Sensor state should update
        updated_state = sensor.state
        assert float(updated_state) == 110000.00

    @pytest.mark.asyncio
    async def test_sensor_attributes_populated_correctly(
        self, mock_hass, mock_config_entry
    ):
        """Test that sensor attributes are populated with correct metadata."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "portfolio": {"total_value": 125000.00, "currency": "USD"},
            "last_updated": "2023-12-01T10:30:00Z",
        }

        sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")

        # Check sensor attributes
        attributes = sensor.extra_state_attributes
        assert isinstance(attributes, dict)

        # Required attributes from quickstart validation
        assert "friendly_name" in attributes
        assert "unit_of_measurement" in attributes
        assert "currency" in attributes
        assert "last_updated" in attributes
        assert "attribution" in attributes

        # Validate attribute values
        assert attributes["currency"] == "USD"
        assert "Saxo" in attributes["attribution"]
        assert attributes["unit_of_measurement"] in ["USD", "$"]

    @pytest.mark.asyncio
    async def test_sensor_unique_ids_generated(self, mock_hass, mock_config_entry):
        """Test that sensors have unique IDs for entity registry."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.config_entry = mock_config_entry

        # Create multiple sensors
        total_value_sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")
        cash_balance_sensor = SaxoPortfolioSensor(mock_coordinator, "cash_balance")
        pnl_sensor = SaxoPortfolioSensor(mock_coordinator, "unrealized_pnl")

        # Each sensor should have unique ID
        unique_ids = {
            total_value_sensor.unique_id,
            cash_balance_sensor.unique_id,
            pnl_sensor.unique_id,
        }
        assert len(unique_ids) == 3  # All different

        # Unique IDs should include entry ID and sensor type
        for sensor_id in unique_ids:
            assert mock_config_entry.entry_id in sensor_id

    @pytest.mark.asyncio
    async def test_sensor_availability_based_on_coordinator_state(
        self, mock_hass, mock_config_entry
    ):
        """Test sensor availability tracking based on coordinator success."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)

        # Coordinator with successful data
        mock_coordinator.last_update_success = True
        mock_coordinator.data = {"portfolio": {"total_value": 100000.00}}

        sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")

        # Sensor should be available
        assert sensor.available is True

        # Coordinator with failed update
        mock_coordinator.last_update_success = False
        mock_coordinator.data = None

        # Sensor should be unavailable
        assert sensor.available is False

    @pytest.mark.asyncio
    async def test_multiple_account_sensors_created(self, mock_hass, mock_config_entry):
        """Test that individual account sensors are created for each account."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "accounts": [
                {"account_id": "acc_001", "balance": 50000.00, "display_name": "Main"},
                {
                    "account_id": "acc_002",
                    "balance": 75000.00,
                    "display_name": "Savings",
                },
            ]
        }

        from custom_components.saxo_portfolio.sensor import SaxoAccountSensor

        # Should be able to create sensors for each account
        account1_sensor = SaxoAccountSensor(mock_coordinator, "acc_001")
        account2_sensor = SaxoAccountSensor(mock_coordinator, "acc_002")

        # Sensors should have different unique IDs
        assert account1_sensor.unique_id != account2_sensor.unique_id

        # Sensors should reflect account data
        assert float(account1_sensor.state) == 50000.00
        assert float(account2_sensor.state) == 75000.00

    @pytest.mark.asyncio
    async def test_position_sensors_track_individual_holdings(
        self, mock_hass, mock_config_entry
    ):
        """Test that position sensors track individual position values."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        mock_coordinator.data = {
            "positions": [
                {
                    "position_id": "pos_123",
                    "symbol": "AAPL",
                    "current_value": 15500.00,
                    "unrealized_pnl": 500.00,
                },
                {
                    "position_id": "pos_456",
                    "symbol": "MSFT",
                    "current_value": 8200.00,
                    "unrealized_pnl": -300.00,
                },
            ]
        }

        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        # Create position sensors
        aapl_sensor = SaxoPositionSensor(mock_coordinator, "pos_123")
        msft_sensor = SaxoPositionSensor(mock_coordinator, "pos_456")

        # Should track individual position values
        assert float(aapl_sensor.state) == 15500.00
        assert float(msft_sensor.state) == 8200.00

        # Should have symbol in attributes
        assert "AAPL" in aapl_sensor.extra_state_attributes.get("symbol", "")
        assert "MSFT" in msft_sensor.extra_state_attributes.get("symbol", "")

    @pytest.mark.asyncio
    async def test_sensor_entity_registry_integration(
        self, mock_hass, mock_config_entry
    ):
        """Test sensors integrate properly with Home Assistant entity registry."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)
        sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")

        # Should have entity registry properties
        assert hasattr(sensor, "entity_registry_enabled_default")
        assert isinstance(sensor.entity_registry_enabled_default, bool)
        assert sensor.entity_registry_enabled_default is True

        # Should have device info for grouping
        if hasattr(sensor, "device_info"):
            device_info = sensor.device_info
            assert isinstance(device_info, dict)
            assert "identifiers" in device_info
            assert "name" in device_info

    @pytest.mark.asyncio
    async def test_sensor_state_transitions_during_updates(
        self, mock_hass, mock_config_entry
    ):
        """Test sensor state transitions during coordinator updates."""
        # This test MUST FAIL initially - no implementation exists

        mock_coordinator = Mock(spec=SaxoCoordinator)

        # Initial state - no data
        mock_coordinator.data = None
        mock_coordinator.last_update_success = False

        sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")

        # Should be unavailable initially
        assert sensor.state in [None, "unavailable", "unknown"]

        # Data becomes available
        mock_coordinator.data = {"portfolio": {"total_value": 100000.00}}
        mock_coordinator.last_update_success = True

        # Should show actual value
        assert float(sensor.state) == 100000.00

        # Data update fails
        mock_coordinator.last_update_success = False
        # But data is still there (coordinator keeps last good data)

        # Should still show last good value
        assert float(sensor.state) == 100000.00
