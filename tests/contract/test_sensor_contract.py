"""Contract tests for Home Assistant sensor state schema.

These tests validate that sensor entities follow the correct
Home Assistant sensor interface and state schema.

⚠️  TDD REQUIREMENT: These tests MUST FAIL initially since no implementation exists.
"""

import pytest
from unittest.mock import Mock
from datetime import datetime

from custom_components.saxo_portfolio.sensor import (
    SaxoPortfolioSensor,
    SaxoAccountSensor,
    SaxoPositionSensor,
)
from custom_components.saxo_portfolio.coordinator import SaxoCoordinator


@pytest.mark.contract
class TestSaxoSensorContract:
    """Contract tests for Saxo Portfolio sensor entities."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with sample data."""
        coordinator = Mock(spec=SaxoCoordinator)
        coordinator.data = {
            "portfolio": {
                "total_value": 125000.00,
                "cash_balance": 5000.00,
                "currency": "USD",
                "unrealized_pnl": 2500.00,
                "positions_count": 5,
            },
            "accounts": [
                {
                    "account_id": "ACC001",
                    "balance": 50000.00,
                    "currency": "USD",
                    "display_name": "Main Account",
                }
            ],
            "positions": [
                {
                    "position_id": "POS001",
                    "symbol": "AAPL",
                    "current_value": 15000.00,
                    "unrealized_pnl": 500.00,
                    "currency": "USD",
                }
            ],
            "last_updated": datetime.now().isoformat(),
        }
        return coordinator

    @pytest.fixture
    def portfolio_sensor(self, mock_coordinator):
        """Create a portfolio total value sensor."""
        # This MUST FAIL initially - no implementation exists
        return SaxoPortfolioSensor(mock_coordinator, "total_value")

    @pytest.fixture
    def account_sensor(self, mock_coordinator):
        """Create an account balance sensor."""
        # This MUST FAIL initially - no implementation exists
        return SaxoAccountSensor(mock_coordinator, "ACC001")

    @pytest.fixture
    def position_sensor(self, mock_coordinator):
        """Create a position value sensor."""
        # This MUST FAIL initially - no implementation exists
        return SaxoPositionSensor(mock_coordinator, "POS001")

    def test_portfolio_sensor_state_schema(self, portfolio_sensor):
        """Test that portfolio sensor state matches SensorState schema."""
        # This test MUST FAIL initially - no implementation exists
        # Validate sensor has required properties
        assert hasattr(portfolio_sensor, "entity_id")
        assert hasattr(portfolio_sensor, "state")
        assert hasattr(portfolio_sensor, "extra_state_attributes")

        # Validate entity_id format
        entity_id = portfolio_sensor.entity_id
        assert entity_id.startswith("sensor.saxo_portfolio_")
        assert "." in entity_id

        # Validate state is numeric string
        state = portfolio_sensor.state
        assert isinstance(state, str | int | float)
        if isinstance(state, str):
            # Should be convertible to float
            float(state)

    def test_portfolio_sensor_attributes_schema(self, portfolio_sensor):
        """Test that portfolio sensor attributes match contract."""
        # This test MUST FAIL initially - no implementation exists
        attributes = portfolio_sensor.extra_state_attributes
        assert isinstance(attributes, dict)

        # Required attributes from SensorState schema
        assert "friendly_name" in attributes
        assert "unit_of_measurement" in attributes
        assert "currency" in attributes
        assert "last_updated" in attributes
        assert "attribution" in attributes

        # Validate attribute types
        assert isinstance(attributes["friendly_name"], str)
        assert isinstance(attributes["unit_of_measurement"], str)
        assert isinstance(attributes["currency"], str)
        assert isinstance(attributes["attribution"], str)

        # Currency should be ISO 4217
        currency = attributes["currency"]
        assert len(currency) == 3
        assert currency.isupper()

    def test_portfolio_sensor_device_class(self, portfolio_sensor):
        """Test that portfolio sensor has correct device class."""
        # This test MUST FAIL initially - no implementation exists
        # Financial sensors should have appropriate device class
        assert hasattr(portfolio_sensor, "device_class")

        # For financial data, device class should be None or monetary
        # (due to Home Assistant limitation with monetary + state_class)
        device_class = portfolio_sensor.device_class
        assert device_class is None or device_class == "monetary"

    def test_portfolio_sensor_state_class(self, portfolio_sensor):
        """Test that portfolio sensor has correct state class."""
        # This test MUST FAIL initially - no implementation exists
        if hasattr(portfolio_sensor, "state_class"):
            state_class = portfolio_sensor.state_class
            if state_class is not None:
                # If state_class is set, should be measurement for financial tracking
                assert state_class == "measurement"
                # And device_class should be None (HA limitation)
                assert portfolio_sensor.device_class is None

    def test_account_sensor_unique_id(self, account_sensor):
        """Test that account sensor has unique ID."""
        # This test MUST FAIL initially - no implementation exists
        assert hasattr(account_sensor, "unique_id")
        unique_id = account_sensor.unique_id
        assert isinstance(unique_id, str)
        assert len(unique_id) > 0
        # Should contain account identifier
        assert "ACC001" in unique_id

    def test_position_sensor_state_validation(self, position_sensor):
        """Test that position sensor state is valid financial data."""
        # This test MUST FAIL initially - no implementation exists
        state = position_sensor.state

        if state is not None and state != "unavailable":
            # Should be numeric
            numeric_state = float(state)

            # Should be finite (not NaN or infinity)
            import math

            assert math.isfinite(numeric_state)

            # Position value should be non-negative
            assert numeric_state >= 0

    def test_sensor_availability(self, portfolio_sensor):
        """Test that sensor correctly reports availability."""
        # This test MUST FAIL initially - no implementation exists
        assert hasattr(portfolio_sensor, "available")

        # Should be available when coordinator has data
        availability = portfolio_sensor.available
        assert isinstance(availability, bool)
        assert availability is True  # Coordinator has mock data

    def test_sensor_coordinator_dependency(self, portfolio_sensor):
        """Test that sensor properly depends on coordinator."""
        # This test MUST FAIL initially - no implementation exists
        from homeassistant.helpers.update_coordinator import CoordinatorEntity

        # Should inherit from CoordinatorEntity
        assert isinstance(portfolio_sensor, CoordinatorEntity)

        # Should have coordinator reference
        assert hasattr(portfolio_sensor, "coordinator")
        assert portfolio_sensor.coordinator is not None

    def test_sensor_icon_assignment(self, portfolio_sensor):
        """Test that sensor has appropriate icon."""
        # This test MUST FAIL initially - no implementation exists
        if hasattr(portfolio_sensor, "icon"):
            icon = portfolio_sensor.icon
            if icon is not None:
                # Should be Material Design icon
                assert icon.startswith("mdi:")
                assert len(icon) > 4

    def test_multiple_sensor_types(self, mock_coordinator):
        """Test that different sensor types can be created."""
        # This test MUST FAIL initially - no implementation exists
        # Portfolio sensors for different metrics
        total_value_sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")
        cash_balance_sensor = SaxoPortfolioSensor(mock_coordinator, "cash_balance")
        pnl_sensor = SaxoPortfolioSensor(mock_coordinator, "unrealized_pnl")

        # Should have different entity IDs
        entity_ids = {
            total_value_sensor.entity_id,
            cash_balance_sensor.entity_id,
            pnl_sensor.entity_id,
        }
        assert len(entity_ids) == 3  # All unique

    def test_sensor_update_method(self, portfolio_sensor):
        """Test that sensor has proper update method."""
        # This test MUST FAIL initially - no implementation exists
        # Should have async_update method or rely on coordinator
        if hasattr(portfolio_sensor, "async_update"):
            assert callable(portfolio_sensor.async_update)
        else:
            # Should rely on coordinator updates
            assert hasattr(portfolio_sensor, "coordinator")

    def test_sensor_error_state_handling(self, mock_coordinator):
        """Test that sensor handles coordinator error states."""
        # This test MUST FAIL initially - no implementation exists
        # Mock coordinator error state
        mock_coordinator.data = None
        mock_coordinator.last_update_success = False

        sensor = SaxoPortfolioSensor(mock_coordinator, "total_value")

        # Sensor should handle missing data gracefully
        state = sensor.state
        # Should be None, "unavailable", or "unknown"
        assert state in [None, "unavailable", "unknown"] or state == 0

    def test_sensor_data_type_consistency(self, portfolio_sensor):
        """Test that sensor maintains consistent data types."""
        # This test MUST FAIL initially - no implementation exists
        # Get state multiple times
        state1 = portfolio_sensor.state
        state2 = portfolio_sensor.state

        # Type should be consistent
        assert type(state1) is type(state2)

        # Value should be consistent (unless data changed)
        if portfolio_sensor.coordinator.data is not None:
            assert state1 == state2

    def test_sensor_registry_info(self, portfolio_sensor):
        """Test that sensor provides entity registry information."""
        # This test MUST FAIL initially - no implementation exists
        # Should have registry-related properties
        assert hasattr(portfolio_sensor, "entity_registry_enabled_default")

        # Default enabled state should be boolean
        if hasattr(portfolio_sensor, "entity_registry_enabled_default"):
            enabled_default = portfolio_sensor.entity_registry_enabled_default
            assert isinstance(enabled_default, bool)
