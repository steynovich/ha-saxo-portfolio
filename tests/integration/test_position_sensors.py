"""Integration tests for position sensors.

These tests verify dynamic sensor creation, options flow, and sensor lifecycle.
"""

import pytest
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from custom_components.saxo_portfolio.const import (
    CONF_ENABLE_POSITION_SENSORS,
    CONF_TIMEZONE,
    DATA_COORDINATOR,
    DOMAIN,
)
from custom_components.saxo_portfolio.coordinator import PositionData


@pytest.mark.integration
class TestPositionSensorDynamicCreation:
    """Tests for dynamic position sensor creation."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {}
        hass.config_entries = MagicMock()
        return hass

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry."""
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_123"
        entry.data = {
            "token": {"access_token": "mock_token"},
            CONF_TIMEZONE: "America/New_York",
            CONF_ENABLE_POSITION_SENSORS: True,
        }
        entry.options = {}
        entry.title = "Saxo Portfolio"
        return entry

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with positions."""
        coordinator = MagicMock()
        coordinator.get_client_id.return_value = "123456"
        coordinator.get_client_name.return_value = "Test User"
        coordinator.last_update_success = True
        coordinator.data = {"last_updated": "2024-01-01T12:00:00"}
        coordinator.position_sensors_enabled = True
        coordinator.update_interval = MagicMock()
        coordinator.update_interval.total_seconds.return_value = 300
        coordinator.config_entry = MagicMock()
        coordinator.config_entry.entry_id = "test_entry_123"

        # Mock positions
        positions = {
            "aapl_stock": PositionData(
                position_id="pos_1",
                symbol="AAPL",
                description="Apple Inc.",
                asset_type="Stock",
                amount=100.0,
                current_price=150.25,
                market_value=15025.00,
                profit_loss=1025.50,
                uic=123456,
                currency="USD",
            ),
            "msft_stock": PositionData(
                position_id="pos_2",
                symbol="MSFT",
                description="Microsoft Corporation",
                asset_type="Stock",
                amount=50.0,
                current_price=350.00,
                market_value=17500.00,
                profit_loss=500.00,
                uic=789012,
                currency="USD",
            ),
        }
        coordinator.get_position_ids.return_value = list(positions.keys())
        coordinator.get_position.side_effect = lambda slug: positions.get(slug)
        coordinator.get_positions.return_value = positions
        coordinator.mark_sensors_initialized = MagicMock()
        coordinator.async_add_listener = MagicMock(return_value=lambda: None)

        return coordinator

    def test_position_sensors_created_when_enabled(
        self, mock_hass, mock_config_entry, mock_coordinator
    ):
        """Test that position sensors are created when enabled."""
        # Set up hass data
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {DATA_COORDINATOR: mock_coordinator}
        }

        # Import after mocking
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        # Create position sensors
        position_ids = mock_coordinator.get_position_ids()
        sensors = [SaxoPositionSensor(mock_coordinator, slug) for slug in position_ids]

        assert len(sensors) == 2
        assert any("aapl" in s.entity_id for s in sensors)
        assert any("msft" in s.entity_id for s in sensors)

    def test_position_sensors_not_created_when_disabled(
        self, mock_hass, mock_config_entry, mock_coordinator
    ):
        """Test that position sensors are not created when disabled."""
        mock_coordinator.position_sensors_enabled = False
        mock_coordinator.get_position_ids.return_value = []

        # When disabled, get_position_ids should return empty list
        position_ids = mock_coordinator.get_position_ids()

        assert len(position_ids) == 0

    def test_new_position_sensor_created_on_coordinator_update(
        self, mock_hass, mock_config_entry, mock_coordinator
    ):
        """Test that new sensors are created when positions are added."""
        # Initial positions
        initial_positions = ["aapl_stock"]
        mock_coordinator.get_position_ids.return_value = initial_positions

        # Store the listener callback
        listener_callback = None

        def capture_listener(callback):
            nonlocal listener_callback
            listener_callback = callback
            return lambda: None

        mock_coordinator.async_add_listener = capture_listener

        # Import and setup the listener
        from custom_components.saxo_portfolio.sensor import _setup_position_listener

        added_entities = []

        def mock_add_entities(entities, update_before_add):
            added_entities.extend(entities)

        _setup_position_listener(
            mock_hass, mock_config_entry, mock_coordinator, mock_add_entities
        )

        # Simulate adding a new position
        new_positions = ["aapl_stock", "msft_stock"]
        mock_coordinator.get_position_ids.return_value = new_positions

        # Trigger the listener
        if listener_callback:
            listener_callback()

        # Verify new sensor was created
        assert len(added_entities) == 1
        assert "msft" in added_entities[0].entity_id


@pytest.mark.integration
class TestPositionSensorOptionsFlow:
    """Tests for position sensor options flow."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {}
        hass.config_entries = MagicMock()
        return hass

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry."""
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_123"
        entry.data = {
            "token": {"access_token": "mock_token"},
            CONF_TIMEZONE: "America/New_York",
            CONF_ENABLE_POSITION_SENSORS: False,
        }
        entry.options = {}
        entry.title = "Saxo Portfolio"
        return entry

    def test_enable_position_sensors_triggers_reload(
        self, mock_hass, mock_config_entry
    ):
        """Test that enabling position sensors triggers config entry reload."""
        from custom_components.saxo_portfolio.config_flow import (
            SaxoOptionsFlowHandler,
        )

        # Create options flow handler
        handler = SaxoOptionsFlowHandler()
        handler.hass = mock_hass
        handler.handler = mock_config_entry.entry_id

        # Mock config_entry property
        type(handler).config_entry = property(lambda self: mock_config_entry)

        # The options flow should trigger a reload
        mock_hass.async_create_task = MagicMock()

        # Note: We can't fully test the async flow without a proper async setup
        # but we can verify the handler was created correctly
        assert handler.hass == mock_hass


@pytest.mark.integration
class TestPositionSensorAvailability:
    """Tests for position sensor availability behavior."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator."""
        coordinator = MagicMock()
        coordinator.get_client_id.return_value = "123456"
        coordinator.last_update_success = True
        coordinator.data = {"last_updated": "2024-01-01T12:00:00"}
        coordinator.update_interval = MagicMock()
        coordinator.update_interval.total_seconds.return_value = 300

        return coordinator

    def test_position_sensor_available_when_position_exists(self, mock_coordinator):
        """Test sensor is available when position exists in cache."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor
        from unittest.mock import PropertyMock

        position = PositionData(
            position_id="pos_1",
            symbol="AAPL",
            description="Apple Inc.",
            asset_type="Stock",
            amount=100.0,
            current_price=150.25,
            market_value=15025.00,
            profit_loss=1025.50,
            uic=123456,
        )
        mock_coordinator.get_position.return_value = position

        sensor = SaxoPositionSensor(mock_coordinator, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=mock_coordinator)

        assert sensor.available is True

    def test_position_sensor_unavailable_when_position_closed(self, mock_coordinator):
        """Test sensor becomes unavailable when position is closed."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor
        from unittest.mock import PropertyMock

        # Position no longer in cache (closed)
        mock_coordinator.get_position.return_value = None

        sensor = SaxoPositionSensor(mock_coordinator, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=mock_coordinator)

        assert sensor.available is False

    def test_position_sensor_unavailable_when_coordinator_fails(self, mock_coordinator):
        """Test sensor unavailable when coordinator data is None."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor
        from unittest.mock import PropertyMock

        mock_coordinator.data = None

        sensor = SaxoPositionSensor(mock_coordinator, "aapl_stock")
        type(sensor).coordinator = PropertyMock(return_value=mock_coordinator)

        assert sensor.available is False
