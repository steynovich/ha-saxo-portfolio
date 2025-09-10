"""Sensor platform for Saxo Portfolio integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ACCOUNT_SENSOR_TYPES,
    ATTRIBUTION,
    DATA_COORDINATOR,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    POSITION_SENSOR_TYPES,
    SENSOR_TYPES,
)
from .coordinator import SaxoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saxo Portfolio sensors from a config entry."""
    coordinator: SaxoCoordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]

    entities: list[SensorEntity] = []

    # Always add portfolio-level sensors (these are static)
    for sensor_type in SENSOR_TYPES:
        entities.append(SaxoPortfolioSensor(coordinator, sensor_type))

    # Add account sensors if accounts are available
    if coordinator.data and "accounts" in coordinator.data:
        for account in coordinator.data["accounts"]:
            account_id = account.get("account_id")
            if account_id:
                _LOGGER.debug("Adding account sensor for account %s", account_id)
                entities.append(SaxoAccountSensor(coordinator, account_id))

    # Add position sensors if positions are available
    if coordinator.data and "positions" in coordinator.data:
        for position in coordinator.data["positions"]:
            position_id = position.get("position_id")
            if position_id:
                _LOGGER.debug("Adding position sensor for position %s", position_id)
                entities.append(SaxoPositionSensor(coordinator, position_id))

    if entities:
        _LOGGER.info("Setting up %d Saxo Portfolio sensors", len(entities))
        async_add_entities(entities, True)
    else:
        _LOGGER.warning("No sensors to add for Saxo Portfolio integration")


class SaxoPortfolioSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Portfolio sensor."""

    def __init__(self, coordinator: SaxoCoordinator, sensor_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{sensor_type}"

        # Get sensor configuration
        sensor_config = SENSOR_TYPES[sensor_type]
        self._attr_name = sensor_config["name"]
        self._attr_device_class = sensor_config["device_class"]
        self._attr_state_class = sensor_config["state_class"]
        self._attr_icon = sensor_config["icon"]
        self._attr_entity_category = sensor_config.get("entity_category")

        # Set unit of measurement
        if sensor_config["unit"]:
            self._attr_native_unit_of_measurement = sensor_config["unit"]
        else:
            # Use currency code for financial sensors
            self._attr_native_unit_of_measurement = coordinator.get_currency()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name="Saxo Portfolio",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            sw_version="1.0.0",
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            value = self.coordinator.get_portfolio_sensor_data(self._sensor_type)

            if value is None:
                return None

            # Validate and format numeric values
            if isinstance(value, int | float):
                # Check for invalid numeric values
                import math
                if not math.isfinite(value):
                    _LOGGER.warning("Invalid numeric value for %s: %s", self._sensor_type, value)
                    return None

                # Round financial values to 2 decimal places
                if self._sensor_type in ["total_value", "cash_balance", "unrealized_pnl"]:
                    return round(float(value), 2)
                # Round percentages to 2 decimal places
                elif self._sensor_type == "pnl_percentage":
                    return round(float(value), 2)
                # Position count should be integer
                elif self._sensor_type == "positions_count":
                    return max(0, int(value))  # Ensure non-negative

            return value

        except Exception as e:
            _LOGGER.error("Error getting native value for %s: %s", self._sensor_type, type(e).__name__)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "attribution": ATTRIBUTION,
            "integration": DOMAIN,
        }

        if self.coordinator.data:
            portfolio_data = self.coordinator.data.get("portfolio", {})

            # Add currency information
            currency = portfolio_data.get("currency", "USD")
            attributes["currency"] = currency

            # Add last updated timestamp
            last_updated = self.coordinator.data.get("last_updated")
            if last_updated:
                attributes["last_updated"] = last_updated

            # Add sensor-specific attributes
            if self._sensor_type == "total_value":
                attributes["positions_count"] = portfolio_data.get("positions_count", 0)
                if portfolio_data.get("margin_available"):
                    attributes["margin_available"] = portfolio_data["margin_available"]

            elif self._sensor_type == "unrealized_pnl":
                attributes["pnl_percentage"] = portfolio_data.get("pnl_percentage")

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("Portfolio sensor %s added to Home Assistant", self.entity_id)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug("Portfolio sensor %s being removed from Home Assistant", self.entity_id)
        await super().async_will_remove_from_hass()


class SaxoAccountSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Account sensor."""

    def __init__(self, coordinator: SaxoCoordinator, account_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_account_{account_id}"

        # Get sensor configuration
        sensor_config = ACCOUNT_SENSOR_TYPES["balance"]
        self._attr_device_class = sensor_config["device_class"]
        self._attr_state_class = sensor_config["state_class"]
        self._attr_icon = sensor_config["icon"]
        self._attr_entity_category = sensor_config.get("entity_category")

        # Get account display name or use ID
        account_data = coordinator.get_account_sensor_data(account_id)
        if account_data and account_data.get("display_name"):
            account_name = account_data["display_name"]
        else:
            account_name = f"Account {account_id}"

        self._attr_name = f"{account_name} Balance"

        # Set unit of measurement
        if sensor_config["unit"]:
            self._attr_native_unit_of_measurement = sensor_config["unit"]
        else:
            # Use account currency or default
            if account_data and account_data.get("currency"):
                self._attr_native_unit_of_measurement = account_data["currency"]
            else:
                self._attr_native_unit_of_measurement = coordinator.get_currency()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name="Saxo Portfolio",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            sw_version="1.0.0",
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            account_data = self.coordinator.get_account_sensor_data(self._account_id)
            if not account_data:
                return None

            balance = account_data.get("balance")
            if balance is not None:
                import math
                if not math.isfinite(float(balance)):
                    _LOGGER.warning("Invalid balance value for account %s: %s", self._account_id, balance)
                    return None
                return round(float(balance), 2)

            return None

        except Exception as e:
            _LOGGER.error("Error getting account balance for %s: %s", self._account_id, type(e).__name__)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "attribution": ATTRIBUTION,
            "integration": DOMAIN,
            "account_id": self._account_id,
        }

        account_data = self.coordinator.get_account_sensor_data(self._account_id)
        if account_data:
            attributes["currency"] = account_data.get("currency", "USD")
            attributes["account_type"] = account_data.get("account_type")
            attributes["active"] = account_data.get("active", True)

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.coordinator.get_account_sensor_data(self._account_id) is not None
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("Account sensor %s added to Home Assistant", self.entity_id)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug("Account sensor %s being removed from Home Assistant", self.entity_id)
        await super().async_will_remove_from_hass()


class SaxoPositionSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Position sensor."""

    def __init__(self, coordinator: SaxoCoordinator, position_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._position_id = position_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_position_{position_id}"

        # Get sensor configuration
        sensor_config = POSITION_SENSOR_TYPES["value"]
        self._attr_device_class = sensor_config["device_class"]
        self._attr_state_class = sensor_config["state_class"]
        self._attr_icon = sensor_config["icon"]
        self._attr_entity_category = sensor_config.get("entity_category")

        # Get position symbol for name
        position_data = coordinator.get_position_sensor_data(position_id)
        if position_data and position_data.get("symbol"):
            symbol = position_data["symbol"]
        else:
            symbol = f"Position {position_id}"

        self._attr_name = f"{symbol} Value"

        # Set unit of measurement
        if sensor_config["unit"]:
            self._attr_native_unit_of_measurement = sensor_config["unit"]
        else:
            # Use position currency or default
            if position_data and position_data.get("currency"):
                self._attr_native_unit_of_measurement = position_data["currency"]
            else:
                self._attr_native_unit_of_measurement = coordinator.get_currency()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name="Saxo Portfolio",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            sw_version="1.0.0",
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            position_data = self.coordinator.get_position_sensor_data(self._position_id)
            if not position_data:
                return None

            current_value = position_data.get("current_value")
            if current_value is not None:
                import math
                if not math.isfinite(float(current_value)):
                    _LOGGER.warning("Invalid current value for position %s: %s", self._position_id, current_value)
                    return None

                # Position values should generally be non-negative
                value = float(current_value)
                if value < 0:
                    _LOGGER.warning("Negative position value for %s: %s", self._position_id, value)
                    # Still return it as some positions might have negative values (shorts)

                return round(value, 2)

            return None

        except Exception as e:
            _LOGGER.error("Error getting position value for %s: %s", self._position_id, type(e).__name__)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "attribution": ATTRIBUTION,
            "integration": DOMAIN,
            "position_id": self._position_id,
        }

        position_data = self.coordinator.get_position_sensor_data(self._position_id)
        if position_data:
            attributes["symbol"] = position_data.get("symbol")
            attributes["quantity"] = position_data.get("quantity")
            attributes["currency"] = position_data.get("currency", "USD")
            attributes["asset_type"] = position_data.get("asset_type")

            # Add P&L information
            if position_data.get("unrealized_pnl") is not None:
                attributes["unrealized_pnl"] = position_data["unrealized_pnl"]
            if position_data.get("pnl_percentage") is not None:
                attributes["pnl_percentage"] = round(position_data["pnl_percentage"], 2)

            # Add price information
            if position_data.get("open_price") is not None:
                attributes["open_price"] = position_data["open_price"]
            if position_data.get("current_price") is not None:
                attributes["current_price"] = position_data["current_price"]

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.coordinator.get_position_sensor_data(self._position_id) is not None
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("Position sensor %s added to Home Assistant", self.entity_id)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug("Position sensor %s being removed from Home Assistant", self.entity_id)
        await super().async_will_remove_from_hass()
