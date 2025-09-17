"""Sensor platform for Saxo Portfolio integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    DATA_COORDINATOR,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
)
from .coordinator import SaxoCoordinator

_LOGGER = logging.getLogger(__name__)



async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saxo Portfolio sensors from a config entry."""
    _LOGGER.debug("Setting up sensor platform for entry %s", config_entry.entry_id)

    # Check if coordinator exists
    if config_entry.entry_id not in hass.data.get(DOMAIN, {}):
        _LOGGER.error("Coordinator not found for entry %s", config_entry.entry_id)
        return

    coordinator: SaxoCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        DATA_COORDINATOR
    ]

    # Create sensors for balance data
    entities: list[SensorEntity] = [
        SaxoCashBalanceSensor(coordinator),
        SaxoTotalValueSensor(coordinator),
        SaxoNonMarginPositionsValueSensor(coordinator),
        SaxoAccumulatedProfitLossSensor(coordinator),
        SaxoInvestmentPerformanceSensor(coordinator),
        SaxoCashTransferBalanceSensor(coordinator),
        # Diagnostic sensors
        SaxoTokenExpirySensor(coordinator),
        SaxoMarketStatusSensor(coordinator),
        SaxoLastUpdateSensor(coordinator),
    ]

    _LOGGER.info(
        "Setting up %d Saxo Portfolio sensors for entry %s",
        len(entities),
        config_entry.entry_id,
    )
    async_add_entities(entities, True)


class SaxoCashBalanceSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Portfolio Cash Balance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_cash_balance"
        self._attr_name = f"Saxo {client_id} Portfolio Cash Balance"
        # Use object_id to control the entity_id generation
        self.entity_id = f"sensor.{entity_prefix}_cash_balance"
        self._attr_device_class = "monetary"
        self._attr_icon = "mdi:cash"
        self._attr_entity_category = None

        # Set unit of measurement to currency from coordinator
        self._attr_native_unit_of_measurement = coordinator.get_currency()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Get ClientId for device name
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            # Get cash balance using coordinator method
            cash_balance = self.coordinator.get_cash_balance()

            if cash_balance is None:
                return None

            # Validate and format numeric value
            if isinstance(cash_balance, int | float):
                import math

                if not math.isfinite(cash_balance):
                    _LOGGER.warning("Invalid cash balance value: %s", cash_balance)
                    return None

                # Round financial value to 2 decimal places
                return round(float(cash_balance), 2)

            return cash_balance

        except Exception as e:
            _LOGGER.error(
                "Error getting cash balance: %s",
                type(e).__name__,
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "attribution": ATTRIBUTION,
        }

        if self.coordinator.data:
            # Add currency information
            currency = self.coordinator.get_currency()
            attributes["currency"] = currency

            # Add last updated timestamp
            last_updated = self.coordinator.data.get("last_updated")
            if last_updated:
                attributes["last_updated"] = last_updated

            # Add total portfolio value for context
            total_value = self.coordinator.data.get("total_value")
            if total_value:
                attributes["total_value"] = total_value

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("Cash balance sensor %s added to Home Assistant", self.entity_id)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Cash balance sensor %s being removed from Home Assistant", self.entity_id
        )
        await super().async_will_remove_from_hass()


class SaxoTotalValueSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Portfolio Total Value sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_total_value"
        self._attr_name = f"Saxo {client_id} Portfolio Total Value"
        # Use object_id to control the entity_id generation
        self.entity_id = f"sensor.{entity_prefix}_total_value"
        self._attr_device_class = "monetary"
        self._attr_icon = "mdi:wallet"
        self._attr_entity_category = None

        # Set unit of measurement to currency from coordinator
        self._attr_native_unit_of_measurement = coordinator.get_currency()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Get ClientId for device name
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            # Get total value using coordinator method
            total_value = self.coordinator.get_total_value()

            if total_value is None:
                return None

            # Validate and format numeric value
            if isinstance(total_value, int | float):
                import math

                if not math.isfinite(total_value):
                    _LOGGER.warning("Invalid total value: %s", total_value)
                    return None

                # Round financial value to 2 decimal places
                return round(float(total_value), 2)

            return total_value

        except Exception as e:
            _LOGGER.error(
                "Error getting total value: %s",
                type(e).__name__,
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "attribution": ATTRIBUTION,
        }

        if self.coordinator.data:
            # Add currency information
            currency = self.coordinator.get_currency()
            attributes["currency"] = currency

            # Add last updated timestamp
            last_updated = self.coordinator.data.get("last_updated")
            if last_updated:
                attributes["last_updated"] = last_updated

            # Add cash balance for context
            cash_balance = self.coordinator.get_cash_balance()
            if cash_balance:
                attributes["cash_balance"] = cash_balance

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("Total value sensor %s added to Home Assistant", self.entity_id)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Total value sensor %s being removed from Home Assistant", self.entity_id
        )
        await super().async_will_remove_from_hass()


class SaxoNonMarginPositionsValueSensor(
    CoordinatorEntity[SaxoCoordinator], SensorEntity
):
    """Representation of a Saxo Portfolio Non-Margin Positions Value sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_non_margin_positions_value"
        self._attr_name = f"Saxo {client_id} Portfolio Non-Margin Positions Value"
        # Use object_id to control the entity_id generation
        self.entity_id = f"sensor.{entity_prefix}_non_margin_positions_value"
        self._attr_device_class = "monetary"
        self._attr_icon = "mdi:finance"
        self._attr_entity_category = None

        # Set unit of measurement to currency from coordinator
        self._attr_native_unit_of_measurement = coordinator.get_currency()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Get ClientId for device name
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            # Get non-margin positions value using coordinator method
            positions_value = self.coordinator.get_non_margin_positions_value()

            if positions_value is None:
                return None

            # Validate and format numeric value
            if isinstance(positions_value, int | float):
                import math

                if not math.isfinite(positions_value):
                    _LOGGER.warning(
                        "Invalid non-margin positions value: %s", positions_value
                    )
                    return None

                # Round financial value to 2 decimal places
                return round(float(positions_value), 2)

            return positions_value

        except Exception as e:
            _LOGGER.error(
                "Error getting non-margin positions value: %s",
                type(e).__name__,
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "attribution": ATTRIBUTION,
        }

        if self.coordinator.data:
            # Add currency information
            currency = self.coordinator.get_currency()
            attributes["currency"] = currency

            # Add last updated timestamp
            last_updated = self.coordinator.data.get("last_updated")
            if last_updated:
                attributes["last_updated"] = last_updated

            # Add other values for context
            total_value = self.coordinator.get_total_value()
            if total_value:
                attributes["total_value"] = total_value

            cash_balance = self.coordinator.get_cash_balance()
            if cash_balance:
                attributes["cash_balance"] = cash_balance

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Non-margin positions value sensor %s added to Home Assistant",
            self.entity_id,
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Non-margin positions value sensor %s being removed from Home Assistant",
            self.entity_id,
        )
        await super().async_will_remove_from_hass()


class SaxoAccumulatedProfitLossSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Portfolio Accumulated Profit/Loss sensor."""

    _attr_device_class = "monetary"
    _attr_state_class = "total"
    _attr_icon = "mdi:trending-up"

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_accumulated_profit_loss"
        self._attr_name = f"Saxo {client_id} Portfolio Accumulated Profit/Loss"

        # Set unit of measurement to currency from coordinator
        self._attr_native_unit_of_measurement = coordinator.get_currency()

        _LOGGER.debug(
            "Initialized accumulated profit/loss sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Get ClientId for device name
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        if self.coordinator.data:
            return self.coordinator.get_currency()
        return None

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        accumulated_profit_loss = self.coordinator.get_ytd_earnings_percentage()
        _LOGGER.debug(
            "Accumulated profit/loss sensor %s returning value: %s",
            self.entity_id,
            accumulated_profit_loss,
        )
        return accumulated_profit_loss

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        if not self.coordinator.data:
            return {}

        attrs = {
            "attribution": ATTRIBUTION,
            "last_updated": self.coordinator.data.get("last_updated"),
        }

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "ytd_earnings_percentage" in self.coordinator.data
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Accumulated profit/loss sensor %s added to Home Assistant", self.entity_id
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Accumulated profit/loss sensor %s being removed from Home Assistant",
            self.entity_id,
        )
        await super().async_will_remove_from_hass()


class SaxoInvestmentPerformanceSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Portfolio Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_investment_performance"
        self._attr_name = f"Saxo {client_id} Portfolio Investment Performance"
        # Use object_id to control the entity_id generation
        self.entity_id = f"sensor.{entity_prefix}_investment_performance"
        self._attr_device_class = None
        self._attr_icon = "mdi:trending-up"
        self._attr_entity_category = None
        self._attr_native_unit_of_measurement = "%"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Get ClientId for device name
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            # Get investment performance percentage using coordinator method
            performance_percentage = (
                self.coordinator.get_investment_performance_percentage()
            )

            if performance_percentage is None:
                return None

            # Validate and format numeric value
            if isinstance(performance_percentage, int | float):
                import math

                if not math.isfinite(performance_percentage):
                    _LOGGER.warning(
                        "Investment performance percentage is not finite: %s",
                        performance_percentage,
                    )
                    return None

                # Round to 2 decimal places for percentage display
                return round(performance_percentage, 2)
            else:
                _LOGGER.warning(
                    "Investment performance percentage is not numeric: %s (type: %s)",
                    performance_percentage,
                    type(performance_percentage),
                )
                return None

        except Exception as e:
            _LOGGER.error(
                "Error getting investment performance percentage: %s", type(e).__name__
            )
            return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "investment_performance_percentage" in self.coordinator.data
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Investment performance sensor %s added to Home Assistant", self.entity_id
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Investment performance sensor %s being removed from Home Assistant",
            self.entity_id,
        )
        await super().async_will_remove_from_hass()


class SaxoCashTransferBalanceSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Portfolio Cash Transfer Balance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_cash_transfer_balance"
        self._attr_name = f"Saxo {client_id} Portfolio Cash Transfer Balance"
        # Use object_id to control the entity_id generation
        self.entity_id = f"sensor.{entity_prefix}_cash_transfer_balance"
        self._attr_device_class = "monetary"
        self._attr_icon = "mdi:bank-transfer"
        self._attr_entity_category = None

        # Set unit of measurement to currency from coordinator
        self._attr_native_unit_of_measurement = coordinator.get_currency()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Get ClientId for device name
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            # Get cash transfer balance using coordinator method
            cash_transfer_balance = self.coordinator.get_cash_transfer_balance()

            if cash_transfer_balance is None:
                return None

            # Validate and format numeric value
            if isinstance(cash_transfer_balance, int | float):
                import math

                if not math.isfinite(cash_transfer_balance):
                    _LOGGER.warning(
                        "Cash transfer balance is not finite: %s",
                        cash_transfer_balance,
                    )
                    return None

                # Round to 2 decimal places for currency display
                return round(cash_transfer_balance, 2)
            else:
                _LOGGER.warning(
                    "Cash transfer balance is not numeric: %s (type: %s)",
                    cash_transfer_balance,
                    type(cash_transfer_balance),
                )
                return None

        except Exception as e:
            _LOGGER.error("Error getting cash transfer balance: %s", type(e).__name__)
            return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "cash_transfer_balance" in self.coordinator.data
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Cash transfer balance sensor %s added to Home Assistant", self.entity_id
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Cash transfer balance sensor %s being removed from Home Assistant",
            self.entity_id,
        )
        await super().async_will_remove_from_hass()


class SaxoTokenExpirySensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Token Expiry diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_token_expiry"
        self._attr_name = f"Saxo {client_id} Token Expiry"
        self.entity_id = f"sensor.{entity_prefix}_token_expiry"

        _LOGGER.debug(
            "Initialized token expiry sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def native_value(self) -> str | None:
        """Return the token expiry status."""
        import time

        token_data = self.coordinator.config_entry.data.get("token", {})
        if not token_data or "expires_at" not in token_data:
            return "Unknown"

        expires_at = token_data["expires_at"]
        current_time = time.time()
        time_until_expiry = expires_at - current_time

        if time_until_expiry <= 0:
            return "Expired"
        elif time_until_expiry <= 60:
            return "Critical - < 1 minute"
        elif time_until_expiry <= 300:
            return f"Warning - {round(time_until_expiry / 60, 1)} minutes"
        elif time_until_expiry <= 3600:
            return f"{round(time_until_expiry / 60)} minutes"
        else:
            return f"{round(time_until_expiry / 3600, 1)} hours"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        import time
        from datetime import datetime

        attrs = {}
        token_data = self.coordinator.config_entry.data.get("token", {})

        if token_data and "expires_at" in token_data:
            expires_at = token_data["expires_at"]
            current_time = time.time()
            time_until_expiry = expires_at - current_time

            expiry_datetime = datetime.fromtimestamp(expires_at)

            attrs["expires_at"] = expiry_datetime.isoformat()
            attrs["expires_in_seconds"] = int(time_until_expiry)
            attrs["is_expired"] = time_until_expiry <= 0
            attrs["needs_refresh"] = time_until_expiry <= 300

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.config_entry.data.get("token") is not None


class SaxoMarketStatusSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Market Status diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_market_status"
        self._attr_name = f"Saxo {client_id} Market Status"
        self.entity_id = f"sensor.{entity_prefix}_market_status"

        _LOGGER.debug(
            "Initialized market status sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def native_value(self) -> str:
        """Return the market status."""
        timezone = getattr(self.coordinator, "_timezone", "Unknown")

        if timezone == "any":
            return "Fixed Schedule"

        is_market_hours = (
            self.coordinator._is_market_hours()
            if hasattr(self.coordinator, "_is_market_hours")
            else False
        )

        if is_market_hours:
            return "Market Open"
        else:
            return "After Hours"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import (
            MARKET_HOURS,
            DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
            DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
            DEFAULT_UPDATE_INTERVAL_ANY,
        )

        timezone = getattr(self.coordinator, "_timezone", "Unknown")
        attrs = {
            "timezone": timezone,
            "update_interval": str(self.coordinator.update_interval)
            if hasattr(self.coordinator, "update_interval")
            else None,
        }

        if timezone != "any" and timezone in MARKET_HOURS:
            market_info = MARKET_HOURS[timezone]
            attrs["market_open"] = (
                f"{market_info['open'][0]:02d}:{market_info['open'][1]:02d}"
            )
            attrs["market_close"] = (
                f"{market_info['close'][0]:02d}:{market_info['close'][1]:02d}"
            )
            attrs["trading_days"] = market_info["weekdays"]

            is_market_hours = (
                self.coordinator._is_market_hours()
                if hasattr(self.coordinator, "_is_market_hours")
                else False
            )
            attrs["interval_active"] = str(
                DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
                if is_market_hours
                else DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
            )
        elif timezone == "any":
            attrs["interval_active"] = str(DEFAULT_UPDATE_INTERVAL_ANY)

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True


class SaxoLastUpdateSensor(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Representation of a Saxo Last Update diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:update"

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_last_update"
        self._attr_name = f"Saxo {client_id} Last Update"
        self.entity_id = f"sensor.{entity_prefix}_last_update"

        _LOGGER.debug(
            "Initialized last update sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the last update time."""
        # The DataUpdateCoordinator sets last_update_time_utc after first successful update
        # It may be None initially until the first update completes
        if (
            hasattr(self.coordinator, "last_update_time_utc")
            and self.coordinator.last_update_time_utc is not None
        ):
            return self.coordinator.last_update_time_utc

        # Check if we have last_update_success_time as fallback
        if (
            hasattr(self.coordinator, "last_update_success_time")
            and self.coordinator.last_update_success_time is not None
        ):
            return self.coordinator.last_update_success_time

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "update_success": self.coordinator.last_update_success
            if hasattr(self.coordinator, "last_update_success")
            else None,
            "has_data": self.coordinator.data is not None
            if hasattr(self.coordinator, "data")
            else False,
        }

        if (
            hasattr(self.coordinator, "last_exception")
            and self.coordinator.last_exception
        ):
            attrs["last_error"] = str(self.coordinator.last_exception)

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Always available since it's a diagnostic sensor
        # But we could check if coordinator has been initialized
        return self.coordinator is not None
