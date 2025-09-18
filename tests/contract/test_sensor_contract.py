"""Contract tests for Home Assistant sensor state schema.

These tests validate that sensor entities follow the correct
Home Assistant sensor interface and state schema.

⚠️  TDD REQUIREMENT: These tests MUST FAIL initially since no implementation exists.
"""

import pytest
from unittest.mock import Mock
from datetime import datetime, timedelta

from custom_components.saxo_portfolio.sensor import (
    SaxoCashBalanceSensor,
    SaxoTotalValueSensor,
    SaxoClientIDSensor,
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
            "cash_balance": 5000.00,
            "total_value": 125000.00,
            "currency": "USD",
            "client_id": "123456",
            "last_updated": datetime.now().isoformat(),
        }
        coordinator.last_update_success = True
        coordinator.get_client_id = Mock(return_value="123456")
        coordinator.get_cash_balance = Mock(return_value=5000.00)
        coordinator.get_total_value = Mock(return_value=125000.00)
        coordinator.get_currency = Mock(return_value="USD")
        return coordinator

    @pytest.fixture
    def portfolio_sensor(self, mock_coordinator):
        """Create a portfolio total value sensor."""
        return SaxoTotalValueSensor(mock_coordinator)

    @pytest.fixture
    def cash_balance_sensor(self, mock_coordinator):
        """Create a cash balance sensor."""
        return SaxoCashBalanceSensor(mock_coordinator)

    @pytest.fixture
    def client_id_sensor(self, mock_coordinator):
        """Create a client ID diagnostic sensor."""
        return SaxoClientIDSensor(mock_coordinator)

    def test_portfolio_sensor_state_schema(self, portfolio_sensor):
        """Test that portfolio sensor state matches SensorState schema."""
        # Validate sensor has required properties
        assert hasattr(portfolio_sensor, "entity_id")
        assert hasattr(portfolio_sensor, "native_value")
        assert hasattr(portfolio_sensor, "extra_state_attributes")

        # Validate entity_id format
        entity_id = portfolio_sensor.entity_id
        assert entity_id.startswith("sensor.saxo_123456_")
        assert "." in entity_id

        # Validate state is numeric
        state = portfolio_sensor.native_value
        assert isinstance(state, (int, float))
        assert state == 125000.00

    def test_portfolio_sensor_attributes_schema(self, portfolio_sensor):
        """Test that portfolio sensor attributes match contract."""
        attributes = portfolio_sensor.extra_state_attributes
        assert isinstance(attributes, dict)

        # Required attributes
        assert "currency" in attributes
        assert "last_updated" in attributes
        assert "attribution" in attributes

        # Validate attribute types
        assert isinstance(attributes["currency"], str)
        assert isinstance(attributes["attribution"], str)

        # Currency should be ISO 4217
        currency = attributes["currency"]
        assert len(currency) == 3
        assert currency.isupper()

    def test_portfolio_sensor_device_class(self, portfolio_sensor):
        """Test that portfolio sensor has correct device class."""
        # Financial sensors should have appropriate device class
        assert hasattr(portfolio_sensor, "device_class")

        # Balance sensors should have monetary device class
        device_class = portfolio_sensor.device_class
        assert device_class == "monetary"

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

    def test_cash_balance_sensor_unique_id(self, cash_balance_sensor):
        """Test that cash balance sensor has unique ID."""
        assert hasattr(cash_balance_sensor, "unique_id")
        unique_id = cash_balance_sensor.unique_id
        assert isinstance(unique_id, str)
        assert len(unique_id) > 0
        # Should contain client ID
        assert "123456" in unique_id
        assert unique_id == "saxo_123456_cash_balance"

    def test_client_id_sensor_state_validation(self, client_id_sensor):
        """Test that client ID sensor state is valid."""
        state = client_id_sensor.native_value

        if state is not None and state != "unavailable":
            # Should be string
            assert isinstance(state, str)
            # Should be the expected client ID
            assert state == "123456"

    def test_sensor_availability(self, portfolio_sensor):
        """Test that sensor correctly reports availability."""
        assert hasattr(portfolio_sensor, "available")

        # Should be available when coordinator has data and successful update
        availability = portfolio_sensor.available
        assert isinstance(availability, bool)
        assert (
            availability is True
        )  # Coordinator has mock data and last_update_success=True

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
        # Different sensor types
        total_value_sensor = SaxoTotalValueSensor(mock_coordinator)
        cash_balance_sensor = SaxoCashBalanceSensor(mock_coordinator)
        client_id_sensor = SaxoClientIDSensor(mock_coordinator)

        # Should have different entity IDs
        entity_ids = {
            total_value_sensor.entity_id,
            cash_balance_sensor.entity_id,
            client_id_sensor.entity_id,
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
        # Mock coordinator error state
        mock_coordinator.data = None
        mock_coordinator.last_update_success = False

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Sensor should handle missing data gracefully
        state = sensor.native_value
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

    def test_improved_availability_logic(self, mock_coordinator):
        """Test the improved sticky availability logic."""
        from datetime import datetime, timedelta

        # Create sensor with mock coordinator
        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Test 1: Normal operation - should be available
        mock_coordinator.last_update_success = True
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_successful_update_time = datetime.now() - timedelta(
            minutes=1
        )
        mock_coordinator.update_interval = timedelta(minutes=5)
        assert sensor.available is True, "Should be available during normal operation"

        # Test 2: Update in progress (temporary failure) - should stay available
        mock_coordinator.last_update_success = (
            False  # Simulating coordinator update in progress
        )
        mock_coordinator.last_successful_update_time = datetime.now() - timedelta(
            minutes=2
        )
        assert sensor.available is True, (
            "Should stay available during temporary update failure"
        )

        # Test 3: Sustained failure - should become unavailable
        mock_coordinator.last_update_success = False
        mock_coordinator.last_successful_update_time = datetime.now() - timedelta(
            minutes=20
        )
        assert sensor.available is False, (
            "Should become unavailable after sustained failure"
        )

        # Test 4: No data at all - should be unavailable
        mock_coordinator.data = None
        mock_coordinator.last_update_success = True
        assert sensor.available is False, "Should be unavailable when no data exists"

        # Test 5: First startup (no successful updates yet) - should be unavailable
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_update_success = False
        mock_coordinator.last_successful_update_time = None
        assert sensor.available is False, (
            "Should be unavailable on first startup before any successful update"
        )

    def test_availability_respects_update_intervals(self, mock_coordinator):
        """Test that availability thresholds adapt to different update intervals."""
        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Setup basic state
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_update_success = False
        current_time = datetime.now()

        # Test with short update interval (5 minutes)
        mock_coordinator.update_interval = timedelta(minutes=5)
        mock_coordinator.last_successful_update_time = current_time - timedelta(
            minutes=10
        )
        # Should still be available (10 min < 15 min minimum threshold)
        assert sensor.available is True, (
            "Should be available within 15 min minimum threshold"
        )

        # Test with long update interval (30 minutes)
        mock_coordinator.update_interval = timedelta(minutes=30)
        mock_coordinator.last_successful_update_time = current_time - timedelta(
            minutes=80
        )
        # Should be unavailable (80 min > 3 * 30 min = 90 min threshold... wait, should be available)
        assert sensor.available is True, (
            "Should be available within 3x update interval threshold"
        )

        # Push beyond 3x threshold
        mock_coordinator.last_successful_update_time = current_time - timedelta(
            minutes=100
        )
        # Should be unavailable (100 min > 90 min threshold)
        assert sensor.available is False, (
            "Should be unavailable beyond 3x update interval threshold"
        )
