"""Diagnostic and schedule sensors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import time
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory

from ..const import (
    CONF_TIMEZONE,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    MARKET_HOURS,
    market_hours_attributes,
)
from ..coordinator import SaxoCoordinator
from ..data import UNKNOWN, ClientInfo
from ..models import mask_sensitive_data
from ..token_expiry import (
    TOKEN_EXPIRY_STATES,
    TOKEN_EXPIRY_WARNING_SECONDS,
    token_expiry_status,
    token_seconds_remaining,
)
from .base import SaxoSensorBase

type AvailableFn = Callable[[SaxoCoordinator], bool]


class SaxoDiagnosticSensorBase(SaxoSensorBase):
    """Base class for Saxo Portfolio diagnostic sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        *,
        is_available_fn: AvailableFn | None = None,
    ) -> None:
        """Initialize the diagnostic sensor.

        Args:
            coordinator: The coordinator instance
            sensor_type: Type identifier (unique ID suffix and translation key)
            is_available_fn: Decides availability; diagnostic sensors skip the
                sticky-availability logic and are otherwise always available

        """
        super().__init__(
            coordinator,
            sensor_type,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._is_available_fn = is_available_fn

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if self._is_available_fn is None:
            return True
        return self._is_available_fn(self.coordinator)


class _SaxoClientFieldSensor(SaxoDiagnosticSensorBase):
    """Diagnostic sensor exposing one client-identity field."""

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        field_fn: Callable[[ClientInfo], str],
    ) -> None:
        """Initialize the sensor; unavailable while the field is unknown."""
        super().__init__(
            coordinator,
            sensor_type,
            is_available_fn=lambda coord: field_fn(coord.client_info) != UNKNOWN,
        )
        self._field_fn = field_fn

    @property
    def native_value(self) -> str:
        """Return the client-identity field."""
        return self._field_fn(self.coordinator.client_info)


class SaxoClientIDSensor(_SaxoClientFieldSensor):
    """Representation of a Saxo Client ID diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "client_id", lambda info: info.client_id)


class SaxoAccountIDSensor(_SaxoClientFieldSensor):
    """Representation of a Saxo Account ID diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "account_id", lambda info: info.account_id)


class SaxoNameSensor(_SaxoClientFieldSensor):
    """Representation of a Saxo Name diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "name", lambda info: info.client_name)


class SaxoTokenExpirySensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Token Expiry diagnostic sensor."""

    _attr_options = TOKEN_EXPIRY_STATES

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "token_expiry",
            is_available_fn=lambda coord: coord.token_data is not None,
        )
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def native_value(self) -> str | None:
        """Return the token expiry status."""
        remaining = token_seconds_remaining(self.coordinator.token_data, time.time())
        if remaining is None:
            return None

        # The exact countdown is exposed as the expires_in_seconds attribute
        return token_expiry_status(remaining).value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes.

        Omits the absolute ``expires_at`` timestamp so the HA state machine
        doesn't expose exact token-rotation timing to every local consumer.
        """
        attrs: dict[str, Any] = {}
        remaining = token_seconds_remaining(self.coordinator.token_data, time.time())

        if remaining is not None:
            attrs["expires_in_seconds"] = int(remaining)
            attrs["is_expired"] = remaining <= 0
            attrs["needs_refresh"] = remaining <= TOKEN_EXPIRY_WARNING_SECONDS

        return attrs


class SaxoMarketStatusSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Market Status diagnostic sensor."""

    _attr_options = ["market_open", "after_hours", "fixed_schedule"]

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "market_status",
        )
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def native_value(self) -> str:
        """Return the market status."""
        if self.coordinator.timezone == "any":
            return "fixed_schedule"

        if self.coordinator.is_market_hours:
            return "market_open"
        return "after_hours"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        timezone = self.coordinator.timezone
        attrs: dict[str, Any] = {
            "timezone": timezone,
            "update_interval": str(self.coordinator.update_interval),
        }

        if timezone != "any" and timezone in MARKET_HOURS:
            attrs.update(market_hours_attributes(timezone))

            attrs["interval_active"] = str(
                DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
                if self.coordinator.is_market_hours
                else DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
            )
        elif timezone == "any":
            attrs["interval_active"] = str(DEFAULT_UPDATE_INTERVAL_ANY)

        return attrs


class SaxoLastUpdateSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Last Update diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "last_update",
        )
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the last update time."""
        # Use our custom property that tracks successful updates
        return self.coordinator.last_successful_update_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs: dict[str, Any] = {
            "update_success": self.coordinator.last_update_success,
            "has_data": self.coordinator.data is not None,
        }

        if self.coordinator.last_exception:
            attrs["last_error"] = mask_sensitive_data(
                str(self.coordinator.last_exception)
            )

        return attrs


class SaxoTimezoneSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Timezone Configuration diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "timezone",
        )

    @property
    def native_value(self) -> str:
        """Return the configured timezone."""
        timezone = self.coordinator.timezone

        if timezone == "any":
            return "Any (Fixed Schedule)"

        return timezone

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        assert self.coordinator.config_entry is not None
        attrs: dict[str, Any] = {
            "configured_timezone": self.coordinator.timezone,
            "config_entry_timezone": self.coordinator.config_entry.data.get(
                CONF_TIMEZONE, "Not configured"
            ),
        }
        attrs.update(self.coordinator.update_mode_attributes())
        return attrs


class SaxoMarketDataAccessSensor(SaxoDiagnosticSensorBase):
    """Diagnostic sensor showing if API has access to real-time market data."""

    # Not "unavailable": that is HA's reserved state for unavailable entities
    _attr_options = ["available", "not_available"]

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "market_data_access",
            # Available as long as position sensors are enabled
            is_available_fn=lambda coord: coord.position_sensors_enabled,
        )
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def native_value(self) -> str | None:
        """Return market data access status (None until it has been checked)."""
        has_access = self.coordinator.has_market_data_access()

        if has_access is None:
            return None
        return "available" if has_access else "not_available"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        has_access = self.coordinator.has_market_data_access()

        attrs: dict[str, Any] = {
            "has_real_time_prices": has_access if has_access is not None else "unknown",
        }

        if has_access is False:
            attrs["note"] = (
                "Prices are calculated from P/L data. Real-time market data may "
                "require a separate subscription on your Saxo account."
            )

        return attrs
