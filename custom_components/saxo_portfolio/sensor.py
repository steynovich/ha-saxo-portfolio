"""Sensor platform for Saxo Portfolio integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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


class SaxoSensorBase(CoordinatorEntity[SaxoCoordinator], SensorEntity):
    """Base class for all Saxo Portfolio sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        display_name: str,
        *,
        device_class: SensorDeviceClass | None = None,
        icon: str | None = None,
        unit_of_measurement: str | None = None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the base sensor."""
        super().__init__(coordinator)

        # Get entity prefix from ClientId with saxo_ prefix
        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_{sensor_type}"
        self._attr_name = f"Saxo {client_id} {display_name}"
        self.entity_id = f"sensor.{entity_prefix}_{sensor_type}"
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._attr_entity_category = entity_category
        self._attr_native_unit_of_measurement = unit_of_measurement

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
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
            sw_version=None,  # Explicitly remove firmware version from device info
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the base state attributes."""
        attributes = {"attribution": ATTRIBUTION}

        if self.coordinator.data:
            last_updated = self.coordinator.data.get("last_updated")
            if last_updated:
                attributes["last_updated"] = last_updated

        return attributes

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

        # If we have data but the current update is failing, check if it's a sustained failure
        # We have data (checked above), so we should stay available unless there's a sustained failure
        if not hasattr(self.coordinator, "last_successful_update_time"):
            # If we have data but no successful update time tracking, stay available
            # This ensures compatibility with older coordinators and first updates
            return True

        last_success = self.coordinator.last_successful_update_time
        if last_success is None:
            # No successful update time recorded yet but we have data, stay available
            # This handles the case during initial startup when coordinator has data
            # but hasn't recorded a successful update time yet
            return True

        from homeassistant.util import dt as dt_util

        # Calculate how long it's been since last successful update
        # Ensure both timestamps are timezone-aware for comparison
        current_time = dt_util.utcnow()
        if last_success.tzinfo is None:
            # Convert naive datetime to UTC-aware using dt_util
            last_success = dt_util.as_utc(last_success)
        time_since_success = current_time - last_success

        # Allow for up to 3 update cycles before marking unavailable
        # Use the longer of 15 minutes or 3x the current update interval
        update_interval_seconds = (
            self.coordinator.update_interval.total_seconds()
            if self.coordinator.update_interval
            else 300  # Default to 5 minutes
        )
        max_failure_time = max(15 * 60, 3 * update_interval_seconds)  # 15 min minimum

        # Stay available if we haven't exceeded the failure threshold
        if time_since_success.total_seconds() < max_failure_time:
            return True
        else:
            # Sustained failure detected
            return False

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            "%s sensor %s added to Home Assistant", self._attr_name, self.entity_id
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "%s sensor %s being removed from Home Assistant",
            self._attr_name,
            self.entity_id,
        )
        await super().async_will_remove_from_hass()


class SaxoBalanceSensorBase(SaxoSensorBase):
    """Base class for Saxo Portfolio balance sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        display_name: str,
        icon: str,
        coordinator_method: str,
    ) -> None:
        """Initialize the balance sensor."""
        super().__init__(
            coordinator,
            sensor_type,
            display_name,
            device_class=SensorDeviceClass.MONETARY,
            icon=icon,
            unit_of_measurement=coordinator.get_currency(),
        )
        self._coordinator_method = coordinator_method
        self._attr_state_class = "total"

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            # Get balance using coordinator method
            balance = getattr(self.coordinator, self._coordinator_method)()

            if balance is None:
                return None

            # Validate and format numeric value
            if isinstance(balance, int | float):
                import math

                if not math.isfinite(balance):
                    _LOGGER.warning("Invalid %s value: %s", self._attr_name, balance)
                    return None

                # Round financial value to 2 decimal places
                return round(float(balance), 2)

            return balance

        except Exception as e:
            _LOGGER.error(
                "Error getting %s: %s",
                self._attr_name,
                type(e).__name__,
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes

        if self.coordinator.data:
            # Add currency information
            currency = self.coordinator.get_currency()
            attributes["currency"] = currency

        return attributes


class SaxoDiagnosticSensorBase(SaxoSensorBase):
    """Base class for Saxo Portfolio diagnostic sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        display_name: str,
        icon: str,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(
            coordinator,
            sensor_type,
            display_name,
            icon=icon,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Diagnostic sensors are generally always available
        return True


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

    # Check if client name is available - do not create sensors if unknown
    client_name = coordinator.get_client_name()
    if client_name == "unknown":
        _LOGGER.warning(
            "Client name is unknown - skipping sensor setup for entry %s. "
            "This usually means the initial API call failed or is still in progress. "
            "Sensors will be created after a successful config entry reload when client data is available.",
            config_entry.entry_id,
        )
        return

    _LOGGER.debug(
        "Client name '%s' available - proceeding with sensor setup for entry %s",
        client_name,
        config_entry.entry_id,
    )

    # Create sensors for balance data
    entities: list[SensorEntity] = [
        SaxoCashBalanceSensor(coordinator),
        SaxoTotalValueSensor(coordinator),
        SaxoNonMarginPositionsValueSensor(coordinator),
        SaxoAccumulatedProfitLossSensor(coordinator),
        SaxoInvestmentPerformanceSensor(coordinator),
        SaxoCashTransferBalanceSensor(coordinator),
        SaxoYTDInvestmentPerformanceSensor(coordinator),
        SaxoMonthInvestmentPerformanceSensor(coordinator),
        SaxoQuarterInvestmentPerformanceSensor(coordinator),
        # Diagnostic sensors
        SaxoClientIDSensor(coordinator),
        SaxoAccountIDSensor(coordinator),
        SaxoNameSensor(coordinator),
        SaxoTokenExpirySensor(coordinator),
        SaxoMarketStatusSensor(coordinator),
        SaxoLastUpdateSensor(coordinator),
        SaxoTimezoneSensor(coordinator),
    ]

    _LOGGER.info(
        "Setting up %d Saxo Portfolio sensors for client '%s' (entry %s)",
        len(entities),
        client_name,
        config_entry.entry_id,
    )
    async_add_entities(entities, True)

    # Mark sensors as initialized in the coordinator
    coordinator.mark_sensors_initialized()


class SaxoCashBalanceSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Cash Balance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "cash_balance",
            "Portfolio Cash Balance",
            "mdi:cash",
            "get_cash_balance",
        )


class SaxoTotalValueSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Total Value sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "total_value",
            "Portfolio Total Value",
            "mdi:wallet",
            "get_total_value",
        )


class SaxoNonMarginPositionsValueSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Non-Margin Positions Value sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "non_margin_positions_value",
            "Portfolio Non-Margin Positions Value",
            "mdi:finance",
            "get_non_margin_positions_value",
        )


class SaxoAccumulatedProfitLossSensor(SaxoSensorBase):
    """Representation of a Saxo Portfolio Accumulated Profit/Loss sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "accumulated_profit_loss",
            "Portfolio Accumulated Profit/Loss",
            device_class=SensorDeviceClass.MONETARY,
            icon="mdi:trending-up",
            unit_of_measurement=coordinator.get_currency(),
        )
        self._attr_state_class = "total"

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
        attributes = super().extra_state_attributes

        if self.coordinator.data:
            # Add currency information
            currency = self.coordinator.get_currency()
            attributes["currency"] = currency

        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Use improved availability from base class
        if not super().available:
            return False

        # Additional check: ensure ytd_earnings_percentage data is present
        return "ytd_earnings_percentage" in (self.coordinator.data or {})


class SaxoPerformanceSensorBase(SaxoSensorBase):
    """Base class for Saxo Portfolio Performance sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        display_name: str,
        data_key: str,
    ) -> None:
        """Initialize the performance sensor.

        Args:
            coordinator: The coordinator instance
            sensor_type: Type identifier for the sensor (e.g., "investment_performance", "ytd_investment_performance")
            display_name: Human readable name for the sensor
            data_key: Key to fetch data from coordinator data dict

        """
        super().__init__(
            coordinator,
            sensor_type,
            f"Portfolio {display_name}",
            icon="mdi:trending-up",
            unit_of_measurement="%",
        )
        self._data_key = data_key

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        try:
            # Get performance percentage using coordinator method
            performance_percentage = self._get_performance_value()

            if performance_percentage is None:
                return None

            # Validate and format numeric value
            if isinstance(performance_percentage, int | float):
                import math

                if not math.isfinite(performance_percentage):
                    _LOGGER.warning(
                        "%s performance percentage is not finite: %s",
                        self._attr_name,
                        performance_percentage,
                    )
                    return None

                # Round to 2 decimal places for percentage display
                return round(performance_percentage, 2)
            else:
                _LOGGER.warning(
                    "%s performance percentage is not numeric: %s (type: %s)",
                    self._attr_name,
                    performance_percentage,
                    type(performance_percentage),
                )
                return None

        except Exception as e:
            _LOGGER.error(
                "Error getting %s performance percentage: %s",
                self._attr_name,
                type(e).__name__,
            )
            return None

    def _get_performance_value(self) -> float | None:
        """Get the performance value from coordinator data.

        This method should be overridden by subclasses to call the appropriate coordinator method.
        """
        raise NotImplementedError(
            "Subclasses must implement _get_performance_value method"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        # Get base attributes from parent class
        attrs = super().extra_state_attributes

        if not self.coordinator.data:
            return attrs

        attrs["time_period"] = self._get_time_period()

        # Add last updated timestamp from performance cache, fallback to general timestamp
        if (
            hasattr(self.coordinator, "_performance_last_updated")
            and self.coordinator._performance_last_updated
        ):
            attrs["last_updated"] = (
                self.coordinator._performance_last_updated.isoformat()
            )

        # Add From and Thru attributes based on time period
        period_dates = self._get_period_dates()
        if period_dates:
            attrs.update(period_dates)

        return attrs

    def _get_time_period(self) -> str:
        """Get the time period for this sensor.

        This method should be overridden by subclasses to return the appropriate time period.
        """
        raise NotImplementedError("Subclasses must implement _get_time_period method")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Use improved availability from base class
        if not super().available:
            return False

        # Additional check: ensure we can get a performance value
        try:
            performance_value = self._get_performance_value()
            return performance_value is not None
        except Exception:
            return False

    def _get_period_dates(self) -> dict[str, str] | None:
        """Calculate From and Thru dates based on the time period.

        Returns:
            Dictionary with 'from' and 'thru' date strings in ISO format, or None if not applicable

        """
        from datetime import datetime, date

        time_period = self._get_time_period()
        now = datetime.now()

        if time_period == "Year":
            # Year-to-date: January 1st to today
            from_date = date(now.year, 1, 1)
            thru_date = now.date()
        elif time_period == "Month":
            # Month-to-date: 1st of current month to today
            from_date = date(now.year, now.month, 1)
            thru_date = now.date()
        elif time_period == "Quarter":
            # Quarter-to-date: 1st day of current quarter to today
            quarter_start_month = ((now.month - 1) // 3) * 3 + 1
            from_date = date(now.year, quarter_start_month, 1)
            thru_date = now.date()
        elif time_period == "AllTime":
            # All-time: No specific from date, just indicate it's all-time
            return {"from": "inception", "thru": now.date().isoformat()}
        else:
            # Unknown time period
            return None

        return {"from": from_date.isoformat(), "thru": thru_date.isoformat()}


class SaxoInvestmentPerformanceSensor(SaxoPerformanceSensorBase):
    """Representation of a Saxo Portfolio Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "investment_performance",
            "Investment Performance",
            "investment_performance_percentage",
        )

    def _get_performance_value(self) -> float | None:
        """Get the investment performance value from coordinator."""
        return self.coordinator.get_investment_performance_percentage()

    def _get_time_period(self) -> str:
        """Get the time period for this sensor."""
        return "AllTime"


class SaxoCashTransferBalanceSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Cash Transfer Balance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "cash_transfer_balance",
            "Portfolio Cash Transfer Balance",
            "mdi:bank-transfer",
            "get_cash_transfer_balance",
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Use improved availability from base class
        if not super().available:
            return False

        # Additional check: ensure cash_transfer_balance data is present
        return "cash_transfer_balance" in (self.coordinator.data or {})


class SaxoYTDInvestmentPerformanceSensor(SaxoPerformanceSensorBase):
    """Representation of a Saxo Portfolio YTD Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "ytd_investment_performance",
            "YTD Investment Performance",
            "ytd_investment_performance_percentage",
        )

    def _get_performance_value(self) -> float | None:
        """Get the YTD investment performance value from coordinator."""
        return self.coordinator.get_ytd_investment_performance_percentage()

    def _get_time_period(self) -> str:
        """Get the time period for this sensor."""
        return "Year"


class SaxoMonthInvestmentPerformanceSensor(SaxoPerformanceSensorBase):
    """Representation of a Saxo Portfolio Month Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "month_investment_performance",
            "Month Investment Performance",
            "month_investment_performance_percentage",
        )

    def _get_performance_value(self) -> float | None:
        """Get the Month investment performance value from coordinator."""
        return self.coordinator.get_month_investment_performance_percentage()

    def _get_time_period(self) -> str:
        """Get the time period for this sensor."""
        return "Month"


class SaxoQuarterInvestmentPerformanceSensor(SaxoPerformanceSensorBase):
    """Representation of a Saxo Portfolio Quarter Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "quarter_investment_performance",
            "Quarter Investment Performance",
            "quarter_investment_performance_percentage",
        )

    def _get_performance_value(self) -> float | None:
        """Get the Quarter investment performance value from coordinator."""
        return self.coordinator.get_quarter_investment_performance_percentage()

    def _get_time_period(self) -> str:
        """Get the time period for this sensor."""
        return "Quarter"


class SaxoClientIDSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Client ID diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "client_id",
            "Client ID",
            "mdi:identifier",
        )

    @property
    def native_value(self) -> str:
        """Return the Client ID."""
        return self.coordinator.get_client_id()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.get_client_id() != "unknown"


class SaxoAccountIDSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Account ID diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "account_id",
            "Account ID",
            "mdi:account",
        )

    @property
    def native_value(self) -> str:
        """Return the Account ID."""
        return self.coordinator.get_account_id()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.get_account_id() != "unknown"


class SaxoNameSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Name diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "name",
            "Name",
            "mdi:account-box",
        )

        _LOGGER.debug(
            "Initialized Name sensor - unique_id: %s, name: %s, icon: %s",
            self._attr_unique_id,
            self._attr_name,
            self._attr_icon,
        )

    @property
    def native_value(self) -> str:
        """Return the client Name."""
        return self.coordinator.get_client_name()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.get_client_name() != "unknown"

    @property
    def icon(self) -> str:
        """Return the icon for this sensor."""
        _LOGGER.debug("Name sensor icon property called - returning mdi:account-box")
        return "mdi:account-box"


class SaxoTokenExpirySensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Token Expiry diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "token_expiry",
            "Token Expiry",
            "mdi:clock-alert-outline",
        )

        _LOGGER.debug(
            "Initialized token expiry sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
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


class SaxoMarketStatusSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Market Status diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "market_status",
            "Market Status",
            "mdi:chart-timeline-variant",
        )

        _LOGGER.debug(
            "Initialized market status sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
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


class SaxoLastUpdateSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Last Update diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "last_update",
            "Last Update",
            "mdi:update",
        )
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

        _LOGGER.debug(
            "Initialized last update sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the last update time."""
        # Use our custom property that tracks successful updates
        if (
            hasattr(self.coordinator, "last_successful_update_time")
            and self.coordinator.last_successful_update_time is not None
        ):
            return self.coordinator.last_successful_update_time

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


class SaxoTimezoneSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Timezone Configuration diagnostic sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "timezone",
            "Timezone",
            "mdi:earth",
        )

        _LOGGER.debug(
            "Initialized timezone sensor with unique_id: %s, name: %s",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def native_value(self) -> str:
        """Return the configured timezone."""
        timezone = getattr(self.coordinator, "_timezone", "Unknown")

        if timezone == "any":
            return "Any (Fixed Schedule)"

        return timezone

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import (
            MARKET_HOURS,
            CONF_TIMEZONE,
            DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
            DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
            DEFAULT_UPDATE_INTERVAL_ANY,
        )

        timezone = getattr(self.coordinator, "_timezone", "Unknown")
        attrs = {
            "configured_timezone": timezone,
            "config_entry_timezone": self.coordinator.config_entry.data.get(
                CONF_TIMEZONE, "Not configured"
            ),
        }

        if timezone == "any":
            attrs["mode"] = "Fixed interval"
            attrs["update_interval"] = str(DEFAULT_UPDATE_INTERVAL_ANY)
            attrs["market_hours_detection"] = False
        elif timezone in MARKET_HOURS:
            market_info = MARKET_HOURS[timezone]
            attrs["mode"] = "Market hours detection"
            attrs["market_hours_detection"] = True
            attrs["market_open"] = (
                f"{market_info['open'][0]:02d}:{market_info['open'][1]:02d}"
            )
            attrs["market_close"] = (
                f"{market_info['close'][0]:02d}:{market_info['close'][1]:02d}"
            )
            attrs["trading_days"] = market_info["weekdays"]
            attrs["update_interval_market"] = str(DEFAULT_UPDATE_INTERVAL_MARKET_HOURS)
            attrs["update_interval_after"] = str(DEFAULT_UPDATE_INTERVAL_AFTER_HOURS)

            # Show current market status
            is_market_hours = (
                self.coordinator._is_market_hours()
                if hasattr(self.coordinator, "_is_market_hours")
                else False
            )
            attrs["current_market_status"] = "Open" if is_market_hours else "Closed"
        else:
            attrs["mode"] = "Unknown configuration"
            attrs["error"] = f"Unknown timezone: {timezone}"

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True
