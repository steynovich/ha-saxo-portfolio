"""Sensor platform for Saxo Portfolio integration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
import math
import time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    STANDARD_PERIOD_MONTH_SPAN,
    STANDARD_PERIOD_QUARTER_SPAN,
)
from .coordinator import SaxoCoordinator
from .data import DEFAULT_CURRENCY, UNKNOWN, SaxoPortfolioData
from .models import mask_sensitive_data

type ValueFn = Callable[[SaxoPortfolioData], float | None]

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


def _setup_position_listener(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: SaxoCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up listener for new positions.

    This listener creates new position sensors when positions are opened.
    """
    known_positions: set[str] = set(coordinator.get_position_ids())

    def _check_new_positions() -> None:
        """Check for new positions and create sensors."""
        nonlocal known_positions
        current_positions = set(coordinator.get_position_ids())

        new_positions = current_positions - known_positions

        if new_positions:
            _LOGGER.info(
                "Detected %d new positions, creating sensors: %s",
                len(new_positions),
                list(new_positions),
            )
            new_entities = [
                SaxoPositionSensor(coordinator, position_slug)
                for position_slug in new_positions
            ]
            async_add_entities(new_entities, True)
            known_positions.update(new_positions)

    # Register listener for coordinator updates
    config_entry.async_on_unload(coordinator.async_add_listener(_check_new_positions))


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
        client_id = coordinator.client_info.client_id
        entity_prefix = f"saxo_{client_id}".lower()

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
        client_id = self.coordinator.client_info.client_id
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

        # If we have data but the current update is failing, check if it's a sustained failure
        # We have data (checked above), so we should stay available unless there's a sustained failure
        last_success = self.coordinator.last_successful_update_time
        if last_success is None:
            # No successful update time recorded yet but we have data, stay available
            # This handles the case during initial startup when coordinator has data
            # but hasn't recorded a successful update time yet
            return True

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
        _LOGGER.debug("Sensor %s added to Home Assistant", self._attr_translation_key)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        _LOGGER.debug(
            "Sensor %s being removed from Home Assistant",
            self._attr_translation_key,
        )
        await super().async_will_remove_from_hass()


class SaxoBalanceSensorBase(SaxoSensorBase):
    """Base class for Saxo Portfolio balance sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        value_fn: ValueFn,
    ) -> None:
        """Initialize the balance sensor.

        Args:
            coordinator: The coordinator instance
            sensor_type: Type identifier (unique ID suffix and translation key)
            value_fn: Reads this sensor's value from the coordinator data

        """
        super().__init__(
            coordinator,
            sensor_type,
            device_class=SensorDeviceClass.MONETARY,
        )
        self._attr_native_unit_of_measurement = self._currency()
        self._value_fn = value_fn
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        data = self.coordinator.data
        if not self.coordinator.last_update_success or data is None:
            return None

        balance = self._value_fn(data)
        if balance is None:
            return None

        if not math.isfinite(balance):
            _LOGGER.warning(
                "Invalid (non-finite) %s value",
                self._attr_translation_key,
            )
            return None

        # Round financial value to 2 decimal places
        return round(balance, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes

        if self.coordinator.data is not None:
            # Add currency information
            attributes["currency"] = self._currency()

        return attributes


class SaxoDiagnosticSensorBase(SaxoSensorBase):
    """Base class for Saxo Portfolio diagnostic sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(
            coordinator,
            sensor_type,
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

    coordinator: SaxoCoordinator = config_entry.runtime_data.coordinator

    client_name = coordinator.client_info.client_name
    if client_name == UNKNOWN:
        _LOGGER.warning(
            "Client name is unknown - skipping sensor setup for entry %s. "
            "This usually means the initial API call failed or is still in progress. "
            "Sensors will be created after a successful config entry reload when client data is available.",
            config_entry.entry_id,
        )
        return

    _LOGGER.debug(
        "Client name available - proceeding with sensor setup for entry %s",
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
        SaxoYTDProfitLossSensor(coordinator),
        SaxoYTDCashTransferSensor(coordinator),
        # Diagnostic sensors
        SaxoClientIDSensor(coordinator),
        SaxoAccountIDSensor(coordinator),
        SaxoNameSensor(coordinator),
        SaxoTokenExpirySensor(coordinator),
        SaxoMarketStatusSensor(coordinator),
        SaxoLastUpdateSensor(coordinator),
        SaxoTimezoneSensor(coordinator),
    ]

    # Add position sensors if enabled
    if coordinator.position_sensors_enabled:
        # Add market data access diagnostic sensor
        entities.append(SaxoMarketDataAccessSensor(coordinator))

        position_ids = coordinator.get_position_ids()
        _LOGGER.debug(
            "Position sensors enabled - creating %d position sensors + market data access sensor",
            len(position_ids),
        )
        for position_slug in position_ids:
            entities.append(SaxoPositionSensor(coordinator, position_slug))

    _LOGGER.info(
        "Setting up %d Saxo Portfolio sensors (entry %s)",
        len(entities),
        config_entry.entry_id,
    )
    async_add_entities(entities, True)

    # Set up listener for position changes if enabled
    if coordinator.position_sensors_enabled:
        _setup_position_listener(hass, config_entry, coordinator, async_add_entities)

    # Mark sensors as initialized in the coordinator
    coordinator.mark_sensors_initialized()


class SaxoCashBalanceSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Cash Balance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "cash_balance",
            lambda data: data.balance.cash_balance,
        )


class SaxoTotalValueSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Total Value sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "total_value",
            lambda data: data.balance.total_value,
        )


class SaxoNonMarginPositionsValueSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Non-Margin Positions Value sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "non_margin_positions_value",
            lambda data: data.balance.non_margin_positions_value,
        )


class SaxoAccumulatedProfitLossSensor(SaxoSensorBase):
    """Representation of a Saxo Portfolio Accumulated Profit/Loss sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "accumulated_profit_loss",
        )
        self._attr_native_unit_of_measurement = self._currency()
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None

        return self.coordinator.data.performance.ytd_earnings_percentage

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        attributes = super().extra_state_attributes

        if self.coordinator.data is not None:
            # Add currency information
            attributes["currency"] = self._currency()

        return attributes


class SaxoPerformanceSensorBase(SaxoSensorBase):
    """Base class for Saxo Portfolio Performance sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        value_fn: ValueFn,
        time_period: str,
    ) -> None:
        """Initialize the performance sensor.

        Args:
            coordinator: The coordinator instance
            sensor_type: Type identifier for the sensor (e.g., "investment_performance", "ytd_investment_performance")
            value_fn: Reads this sensor's percentage from the coordinator data
            time_period: Period the percentage covers (AllTime, YearToDate, Month, Quarter)

        """
        super().__init__(
            coordinator,
            sensor_type,
            unit_of_measurement="%",
        )
        self._value_fn = value_fn
        self._time_period = time_period
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        data = self.coordinator.data
        if not self.coordinator.last_update_success or data is None:
            return None

        performance_percentage = self._value_fn(data)
        if performance_percentage is None:
            return None

        if not math.isfinite(performance_percentage):
            _LOGGER.warning(
                "%s performance percentage is not finite",
                self._attr_translation_key,
            )
            return None

        # Round to 2 decimal places for percentage display
        return round(performance_percentage, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        # Get base attributes from parent class
        attrs = super().extra_state_attributes

        if self.coordinator.data is None:
            return attrs

        attrs["time_period"] = self._time_period

        # Add last updated timestamp from performance cache, fallback to general timestamp
        performance_last_updated = self.coordinator.performance_last_updated
        if performance_last_updated:
            attrs["last_updated"] = performance_last_updated.isoformat()

        # Add From and Thru attributes based on time period
        period_dates = self._get_period_dates()
        if period_dates:
            attrs.update(period_dates)

        return attrs

    def _get_period_dates(self) -> dict[str, str] | None:
        """Calculate From and Thru dates based on the time period.

        Returns:
            Dictionary with 'from' and 'thru' date strings in ISO format, or None if not applicable

        """
        time_period = self._time_period
        now = dt_util.now()

        if time_period == "YearToDate":
            # Year-to-date: January 1st to today (explicit FromDate/ToDate)
            from_date = date(now.year, 1, 1)
            thru_date = now.date()
        elif time_period in ("Month", "Quarter"):
            # StandardPeriod=Month/Quarter are trailing windows ending at the
            # last completed day, not calendar month/quarter-to-date
            span = (
                STANDARD_PERIOD_MONTH_SPAN
                if time_period == "Month"
                else STANDARD_PERIOD_QUARTER_SPAN
            )
            thru_date = now.date() - timedelta(days=1)
            from_date = thru_date - span
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
            lambda data: data.performance.investment_performance_percentage,
            "AllTime",
        )


class SaxoCashTransferBalanceSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Cash Transfer Balance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "cash_transfer_balance",
            lambda data: data.performance.cash_transfer_balance,
        )


class SaxoYTDProfitLossSensor(SaxoSensorBase):
    """Representation of a Saxo Portfolio YTD Profit/Loss sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "ytd_profit_loss",
        )
        self._attr_native_unit_of_measurement = self._currency()
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        data = self.coordinator.data
        if data is None:
            return None

        value = data.performance.ytd_profit_loss
        if value is None or not math.isfinite(value):
            return None
        return round(value, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        attributes = super().extra_state_attributes

        if self.coordinator.data is not None:
            attributes["currency"] = self._currency()

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False

        data = self.coordinator.data
        return data is not None and data.performance.ytd_profit_loss is not None


class SaxoYTDCashTransferSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio YTD Net Transfers sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "ytd_cash_transfer",
            lambda data: data.performance.ytd_cash_transfer,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False

        data = self.coordinator.data
        return data is not None and data.performance.ytd_cash_transfer is not None

    @property
    def last_reset(self) -> datetime:
        """Return the start of the current year.

        Unlike its all-time sibling, this metric's source window (the
        Jan-1 anchored FromDate/ToDate range) resets to zero every 1
        January. Recorder only zeroes its long-term-statistics reference
        point when this attribute *changes*, so it must be recomputed on
        every access (not cached at __init__ time) to re-anchor at the
        year boundary without requiring a restart.
        """
        now = dt_util.now()
        return dt_util.start_of_local_day(date(now.year, 1, 1))


class SaxoYTDInvestmentPerformanceSensor(SaxoPerformanceSensorBase):
    """Representation of a Saxo Portfolio YTD Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        # Not a StandardPeriod: ``StandardPeriod=Year`` is a trailing 12-month
        # window, so this sensor requests an explicit 1 January-to-today range.
        super().__init__(
            coordinator,
            "ytd_investment_performance",
            lambda data: data.performance.ytd_investment_performance_percentage,
            "YearToDate",
        )


class SaxoMonthInvestmentPerformanceSensor(SaxoPerformanceSensorBase):
    """Representation of a Saxo Portfolio Month Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "month_investment_performance",
            lambda data: data.performance.month_investment_performance_percentage,
            "Month",
        )


class SaxoQuarterInvestmentPerformanceSensor(SaxoPerformanceSensorBase):
    """Representation of a Saxo Portfolio Quarter Investment Performance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "quarter_investment_performance",
            lambda data: data.performance.quarter_investment_performance_percentage,
            "Quarter",
        )


class SaxoClientIDSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Client ID diagnostic sensor."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "client_id",
        )

    @property
    def native_value(self) -> str:
        """Return the Client ID."""
        return self.coordinator.client_info.client_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.client_info.client_id != UNKNOWN


class SaxoAccountIDSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Account ID diagnostic sensor."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "account_id",
        )

    @property
    def native_value(self) -> str:
        """Return the Account ID."""
        return self.coordinator.client_info.account_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.client_info.account_id != UNKNOWN


class SaxoNameSensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Name diagnostic sensor."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "name",
        )

    @property
    def native_value(self) -> str:
        """Return the client Name."""
        return self.coordinator.client_info.client_name

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.client_info.client_name != UNKNOWN


class SaxoTokenExpirySensor(SaxoDiagnosticSensorBase):
    """Representation of a Saxo Token Expiry diagnostic sensor."""

    _attr_options = ["valid", "warning", "critical", "expired"]

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "token_expiry",
        )
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def native_value(self) -> str | None:
        """Return the token expiry status."""
        assert self.coordinator.config_entry is not None
        token_data = self.coordinator.config_entry.data.get("token", {})
        if not token_data or "expires_at" not in token_data:
            return None

        # The exact countdown is exposed as the expires_in_seconds attribute
        time_until_expiry = token_data["expires_at"] - time.time()

        if time_until_expiry <= 0:
            return "expired"
        if time_until_expiry <= 60:
            return "critical"
        if time_until_expiry <= 300:
            return "warning"
        return "valid"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes.

        Omits the absolute ``expires_at`` timestamp so the HA state machine
        doesn't expose exact token-rotation timing to every local consumer.
        """
        assert self.coordinator.config_entry is not None
        attrs: dict[str, Any] = {}
        token_data = self.coordinator.config_entry.data.get("token", {})

        if token_data and "expires_at" in token_data:
            expires_at = token_data["expires_at"]
            time_until_expiry = expires_at - time.time()

            attrs["expires_in_seconds"] = int(time_until_expiry)
            attrs["is_expired"] = time_until_expiry <= 0
            attrs["needs_refresh"] = time_until_expiry <= 300

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        assert self.coordinator.config_entry is not None
        return self.coordinator.config_entry.data.get("token") is not None


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
        from .const import (
            MARKET_HOURS,
            market_hours_attributes,
            DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
            DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
            DEFAULT_UPDATE_INTERVAL_ANY,
        )

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
        from .const import (
            MARKET_HOURS,
            UPDATE_MODE_FIXED,
            UPDATE_MODE_MARKET_HOURS,
            UPDATE_MODE_UNKNOWN,
            market_hours_attributes,
            CONF_TIMEZONE,
            DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
            DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
            DEFAULT_UPDATE_INTERVAL_ANY,
        )

        assert self.coordinator.config_entry is not None
        timezone = self.coordinator.timezone
        attrs: dict[str, Any] = {
            "configured_timezone": timezone,
            "config_entry_timezone": self.coordinator.config_entry.data.get(
                CONF_TIMEZONE, "Not configured"
            ),
        }

        if timezone == "any":
            attrs["mode"] = UPDATE_MODE_FIXED
            attrs["update_interval"] = str(DEFAULT_UPDATE_INTERVAL_ANY)
            attrs["market_hours_detection"] = False
        elif timezone in MARKET_HOURS:
            attrs["mode"] = UPDATE_MODE_MARKET_HOURS
            attrs["market_hours_detection"] = True
            attrs.update(market_hours_attributes(timezone))
            attrs["update_interval_market"] = str(DEFAULT_UPDATE_INTERVAL_MARKET_HOURS)
            attrs["update_interval_after"] = str(DEFAULT_UPDATE_INTERVAL_AFTER_HOURS)

            # Show current market status
            attrs["current_market_status"] = (
                "Open" if self.coordinator.is_market_hours else "Closed"
            )
        else:
            attrs["mode"] = UPDATE_MODE_UNKNOWN
            attrs["error"] = f"Unknown timezone: {timezone}"

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True


class SaxoMarketDataAccessSensor(SaxoDiagnosticSensorBase):
    """Diagnostic sensor showing if API has access to real-time market data."""

    # Not "unavailable": that is HA's reserved state for unavailable entities
    _attr_options = ["available", "not_available"]

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "market_data_access",
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

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Available as long as position sensors are enabled
        return self.coordinator.position_sensors_enabled


class SaxoPositionSensor(SaxoSensorBase):
    """Representation of a Saxo Portfolio Position sensor."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        position_slug: str,
    ) -> None:
        """Initialize the position sensor.

        Args:
            coordinator: The coordinator instance
            position_slug: Unique slug for the position (e.g., "aapl_stock")

        """
        self._position_slug = position_slug
        position = coordinator.get_position(position_slug)

        # Get display info from position
        symbol = position.symbol if position else position_slug

        # Note: We don't use device_class=MONETARY because HA only allows
        # state_class='total' for monetary sensors. We need state_class='measurement'
        # to enable historical statistics tracking for price changes.
        super().__init__(
            coordinator,
            f"position_{position_slug}",
            unit_of_measurement=position.currency if position else "USD",
        )

        # All position sensors share one translation key; the symbol is a
        # placeholder. The unique ID (set by the base class) keeps its
        # per-position suffix, so registry entries are unchanged.
        self._attr_translation_key = "position"
        self._attr_translation_placeholders = {"symbol": symbol}

        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> StateType:
        """Return the current price of the position."""
        position = self.coordinator.get_position(self._position_slug)
        if position is None:
            return None

        try:
            if not math.isfinite(position.current_price):
                return None

            return round(position.current_price, 4)
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return position-specific attributes."""
        attributes = super().extra_state_attributes
        position = self.coordinator.get_position(self._position_slug)

        if position:
            attributes["symbol"] = position.symbol
            attributes["description"] = position.description
            attributes["asset_type"] = position.asset_type
            attributes["amount"] = position.amount
            attributes["market_value"] = round(position.market_value, 2)
            attributes["profit_loss"] = round(position.profit_loss, 2)
            attributes["uic"] = position.uic
            attributes["currency"] = position.currency

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Use improved availability from base class
        if not super().available:
            return False

        # Position is available if it exists in cache
        return self.coordinator.get_position(self._position_slug) is not None
