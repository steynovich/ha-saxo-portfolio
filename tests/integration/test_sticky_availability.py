"""Integration tests for sticky availability behavior.

These tests validate that sensors remain available during normal coordinator
updates and only become unavailable after sustained failures.
"""

import pytest
from unittest.mock import Mock
from datetime import timedelta
from homeassistant.util import dt as dt_util

from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.sensor import (
    SaxoCashBalanceSensor,
    SaxoTotalValueSensor,
    SaxoAccumulatedProfitLossSensor,
    SaxoInvestmentPerformanceSensor,
    SaxoCashTransferBalanceSensor,
    SaxoClientIDSensor,
    SaxoTokenExpirySensor,
)


@pytest.mark.integration
class TestStickyAvailabilityBehavior:
    """Test sticky availability behavior prevents sensor flashing."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with reasonable defaults."""
        coordinator = Mock(spec=SaxoCoordinator)
        coordinator.update_interval = timedelta(minutes=5)
        coordinator.data = {
            "cash_balance": 5000.00,
            "total_value": 100000.00,
            "currency": "USD",
            "ytd_earnings_percentage": 15.5,
            "cash_transfer_balance": 1000.00,
        }
        coordinator.last_update_success = True
        coordinator.last_successful_update_time = dt_util.utcnow() - timedelta(
            minutes=1
        )

        # Mock coordinator methods
        coordinator.get_client_id = Mock(return_value="123456")
        coordinator.get_cash_balance = Mock(return_value=5000.00)
        coordinator.get_total_value = Mock(return_value=100000.00)
        coordinator.get_currency = Mock(return_value="USD")
        coordinator.get_ytd_earnings_percentage = Mock(return_value=15.5)
        coordinator.get_investment_performance_percentage = Mock(return_value=25.0)
        coordinator.get_cash_transfer_balance = Mock(return_value=1000.00)

        return coordinator

    @pytest.mark.asyncio
    async def test_balance_sensors_sticky_availability(self, mock_coordinator):
        """Test that balance sensors use sticky availability logic."""

        # Create balance sensors
        cash_sensor = SaxoCashBalanceSensor(mock_coordinator)
        total_sensor = SaxoTotalValueSensor(mock_coordinator)

        # Initially available
        assert cash_sensor.available is True
        assert total_sensor.available is True

        # Simulate coordinator update in progress
        mock_coordinator.last_update_success = False  # Temporary failure
        mock_coordinator.last_successful_update_time = dt_util.utcnow() - timedelta(
            minutes=2
        )

        # Sensors should remain available (sticky)
        assert cash_sensor.available is True, (
            "Cash balance sensor should stay available during update"
        )
        assert total_sensor.available is True, (
            "Total value sensor should stay available during update"
        )

        # Simulate sustained failure (20 minutes)
        mock_coordinator.last_successful_update_time = dt_util.utcnow() - timedelta(
            minutes=20
        )

        # Sensors should now become unavailable
        assert cash_sensor.available is False, (
            "Cash balance sensor should become unavailable after sustained failure"
        )
        assert total_sensor.available is False, (
            "Total value sensor should become unavailable after sustained failure"
        )

    @pytest.mark.asyncio
    async def test_performance_sensors_sticky_availability(self, mock_coordinator):
        """Test that performance sensors use enhanced sticky availability logic."""

        # Create performance sensors
        profit_loss_sensor = SaxoAccumulatedProfitLossSensor(mock_coordinator)
        investment_sensor = SaxoInvestmentPerformanceSensor(mock_coordinator)

        # Initially available
        assert profit_loss_sensor.available is True
        assert investment_sensor.available is True

        # Simulate coordinator update in progress
        mock_coordinator.last_update_success = False
        mock_coordinator.last_successful_update_time = dt_util.utcnow() - timedelta(
            minutes=3
        )

        # Sensors should remain available (sticky)
        assert profit_loss_sensor.available is True, (
            "Profit/loss sensor should stay available during update"
        )
        assert investment_sensor.available is True, (
            "Investment performance sensor should stay available during update"
        )

    @pytest.mark.asyncio
    async def test_sensors_with_data_requirements(self, mock_coordinator):
        """Test sensors with specific data requirements use sticky availability correctly."""

        # Create sensor with specific data requirements
        cash_transfer_sensor = SaxoCashTransferBalanceSensor(mock_coordinator)

        # Initially available with required data
        assert cash_transfer_sensor.available is True

        # Simulate update in progress
        mock_coordinator.last_update_success = False
        mock_coordinator.last_successful_update_time = dt_util.utcnow() - timedelta(
            minutes=2
        )

        # Should stay available if data is still present
        assert cash_transfer_sensor.available is True, (
            "Should stay available when data present during update"
        )

        # Remove specific data requirement
        mock_coordinator.data = {"total_value": 100000.00}  # No cash_transfer_balance

        # Should become unavailable when specific data is missing
        assert cash_transfer_sensor.available is False, (
            "Should become unavailable when required data missing"
        )

    @pytest.mark.asyncio
    async def test_diagnostic_sensors_availability_logic(self, mock_coordinator):
        """Test that diagnostic sensors have appropriate availability logic."""

        # Create diagnostic sensors
        client_id_sensor = SaxoClientIDSensor(mock_coordinator)
        token_sensor = SaxoTokenExpirySensor(mock_coordinator)

        # Mock config entry for token sensor
        mock_coordinator.config_entry = Mock()
        mock_coordinator.config_entry.data = {
            "token": {
                "access_token": "test_token",
                "expires_at": (dt_util.utcnow() + timedelta(hours=1)).timestamp(),
            }
        }

        # Client ID sensor should be available if client ID is not "unknown"
        assert client_id_sensor.available is True

        # Token sensor should be available if token exists
        assert token_sensor.available is True

        # These sensors don't use sticky availability - they have their own logic
        mock_coordinator.last_update_success = False
        mock_coordinator.last_successful_update_time = dt_util.utcnow() - timedelta(
            minutes=30
        )

        # Should still be available based on their own criteria
        assert client_id_sensor.available is True, (
            "Client ID sensor availability based on client ID, not coordinator"
        )
        assert token_sensor.available is True, (
            "Token sensor availability based on token presence, not coordinator"
        )

    @pytest.mark.asyncio
    async def test_availability_threshold_adaptation(self, mock_coordinator):
        """Test that availability thresholds adapt to different update intervals."""

        sensor = SaxoTotalValueSensor(mock_coordinator)
        current_time = dt_util.utcnow()

        # Test with short interval (5 minutes)
        mock_coordinator.update_interval = timedelta(minutes=5)
        mock_coordinator.last_update_success = False

        # 10 minutes since last success (< 15 min minimum threshold)
        mock_coordinator.last_successful_update_time = current_time - timedelta(
            minutes=10
        )
        assert sensor.available is True, (
            "Should be available within minimum 15-minute threshold"
        )

        # Test with long interval (30 minutes)
        mock_coordinator.update_interval = timedelta(minutes=30)

        # 80 minutes since last success (< 3 * 30 = 90 minutes)
        mock_coordinator.last_successful_update_time = current_time - timedelta(
            minutes=80
        )
        assert sensor.available is True, (
            "Should be available within 3x update interval threshold"
        )

        # 100 minutes since last success (> 90 minutes)
        mock_coordinator.last_successful_update_time = current_time - timedelta(
            minutes=100
        )
        assert sensor.available is False, (
            "Should be unavailable beyond 3x update interval threshold"
        )

    @pytest.mark.asyncio
    async def test_no_data_scenarios(self, mock_coordinator):
        """Test availability behavior when coordinator has no data."""

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # No data at all - should be unavailable regardless of other factors
        mock_coordinator.data = None
        mock_coordinator.last_update_success = True
        mock_coordinator.last_successful_update_time = dt_util.utcnow()

        assert sensor.available is False, "Should be unavailable when no data exists"

        # No data and failed update - should be unavailable
        mock_coordinator.last_update_success = False
        assert sensor.available is False, (
            "Should be unavailable when no data and failed update"
        )

    @pytest.mark.asyncio
    async def test_first_startup_scenarios(self, mock_coordinator):
        """Test availability behavior during first startup."""

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # First startup: has data but no successful update history
        # According to sticky availability logic, if we have data but no
        # last_successful_update_time, we stay available (line 110-114 in sensor.py)
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_update_success = False
        mock_coordinator.last_successful_update_time = None

        assert sensor.available is True, (
            "Should stay available on first startup when data exists (sticky availability)"
        )

        # First successful update
        mock_coordinator.last_update_success = True
        mock_coordinator.last_successful_update_time = dt_util.utcnow()

        assert sensor.available is True, (
            "Should remain available after first successful update"
        )

    @pytest.mark.asyncio
    async def test_coordinator_update_simulation(self, mock_coordinator):
        """Test realistic coordinator update cycle simulation."""

        sensor = SaxoTotalValueSensor(mock_coordinator)

        # Step 1: Normal operation
        mock_coordinator.last_update_success = True
        mock_coordinator.data = {"total_value": 100000.00}
        mock_coordinator.last_successful_update_time = dt_util.utcnow() - timedelta(
            minutes=1
        )
        assert sensor.available is True, "Step 1: Normal operation"

        # Step 2: Coordinator starts update (sets last_update_success = False)
        mock_coordinator.last_update_success = False
        # Data and last_successful_update_time remain unchanged
        assert sensor.available is True, (
            "Step 2: Should stay available during coordinator update start"
        )

        # Step 3: Update completes successfully
        mock_coordinator.last_update_success = True
        mock_coordinator.last_successful_update_time = dt_util.utcnow()
        assert sensor.available is True, (
            "Step 3: Should remain available after successful update"
        )

        # Step 4: Update starts again (next cycle)
        mock_coordinator.last_update_success = False
        assert sensor.available is True, (
            "Step 4: Should stay available during next update cycle"
        )

        # This cycle demonstrates no flashing unavailable states
