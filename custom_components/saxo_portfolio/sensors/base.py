"""Base classes and helpers shared by every Saxo Portfolio sensor family."""

from __future__ import annotations

from collections.abc import Callable
import logging
import math
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from ..const import (
    ATTRIBUTION,
    AVAILABILITY_FAILURE_FLOOR,
    AVAILABILITY_FAILURE_INTERVAL_MULTIPLIER,
    AVAILABILITY_FALLBACK_UPDATE_INTERVAL,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
)
from ..coordinator import SaxoCoordinator
from ..data import DEFAULT_CURRENCY, SaxoPortfolioData

type ValueFn = Callable[[SaxoPortfolioData], float | None]

_LOGGER = logging.getLogger(__name__)


def finite_round(
    value: float | None, digits: int = 2, *, label: str | None = None
) -> float | None:
    """Return ``value`` rounded to ``digits``, or None if missing or non-finite.

    Args:
        value: The raw reading
        digits: Decimal places to keep
        label: Sensor name for the warning logged on a non-finite value

    """
    if value is None:
        return None
    if not math.isfinite(value):
        if label is not None:
            _LOGGER.warning("Invalid (non-finite) %s value", label)
        return None
    return round(value, digits)


class SaxoSensorBase(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Base class for all Saxo Portfolio sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        *,
        device_class: SensorDeviceClass | None = None,
        unit_of_measurement: str | None = None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the base sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        entity_prefix = f"saxo_{coordinator.client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_{sensor_type}"
        self._attr_translation_key = sensor_type
        self._attr_device_class = device_class
        self._attr_entity_category = entity_category
        self._attr_native_unit_of_measurement = unit_of_measurement

        _LOGGER.debug("Initialized sensor - translation_key: %s", sensor_type)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        assert self.coordinator.config_entry is not None
        device_name = f"Saxo {self.coordinator.client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
            sw_version=None,  # Explicitly remove firmware version from device info
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the base state attributes."""
        attributes = {"attribution": ATTRIBUTION}

        if self.coordinator.data is not None:
            attributes["last_updated"] = self.coordinator.data.last_updated.isoformat()

        return attributes

    def _currency(self) -> str:
        """Return the account base currency (USD before any data)."""
        data = self.coordinator.data
        return data.balance.currency if data is not None else DEFAULT_CURRENCY

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Uses improved availability logic to prevent sensors from flashing
        unavailable during normal coordinator updates. Sensors remain available
        as long as they have data and haven't had sustained failures.
        """
        # If we have no data at all, we're definitely unavailable
        if self.coordinator.data is None:
            return False

        # If the last update was successful, we're available
        if self.coordinator.last_update_success:
            return True

        # We have data but the current update is failing: stay available unless
        # the failure is sustained
        last_success = self.coordinator.last_successful_update_time
        if last_success is None:
            # No successful update time recorded yet but we have data, stay available
            # This handles the case during initial startup when coordinator has data
            # but hasn't recorded a successful update time yet
            return True

        # Ensure both timestamps are timezone-aware for comparison
        if last_success.tzinfo is None:
            last_success = dt_util.as_utc(last_success)
        time_since_success = dt_util.utcnow() - last_success

        update_interval = (
            self.coordinator.update_interval or AVAILABILITY_FALLBACK_UPDATE_INTERVAL
        )
        max_failure_time = max(
            AVAILABILITY_FAILURE_FLOOR,
            AVAILABILITY_FAILURE_INTERVAL_MULTIPLIER * update_interval,
        )

        return time_since_success < max_failure_time

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("Sensor %s added to Home Assistant", self._attr_translation_key)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Sensor %s being removed from Home Assistant",
            self._attr_translation_key,
        )
        await super().async_will_remove_from_hass()


class SaxoValueSensorBase(SaxoSensorBase):
    """Sensor whose state is a rounded, finite number read by a ``value_fn``."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        value_fn: ValueFn,
        *,
        device_class: SensorDeviceClass | None = None,
        unit_of_measurement: str | None = None,
        unavailable_without_value: bool = False,
    ) -> None:
        """Initialize the value sensor.

        Args:
            coordinator: The coordinator instance
            sensor_type: Type identifier (unique ID suffix and translation key)
            value_fn: Reads this sensor's value from the coordinator data
            device_class: Optional device class
            unit_of_measurement: Optional unit
            unavailable_without_value: Report unavailable while ``value_fn``
                returns None (instead of an unknown state)

        """
        super().__init__(
            coordinator,
            sensor_type,
            device_class=device_class,
            unit_of_measurement=unit_of_measurement,
        )
        self._value_fn = value_fn
        self._unavailable_without_value = unavailable_without_value

    def _rounded_value(self) -> float | None:
        """Return the finite value rounded to 2 decimals (no update-success guard)."""
        data = self.coordinator.data
        if data is None:
            return None
        return finite_round(self._value_fn(data), 2, label=self._attr_translation_key)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success:
            return None
        return self._rounded_value()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False
        if not self._unavailable_without_value:
            return True

        data = self.coordinator.data
        return data is not None and self._value_fn(data) is not None
