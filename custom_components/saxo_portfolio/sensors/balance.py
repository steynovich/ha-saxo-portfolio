"""Balance sensors (account balance and cash-transfer totals)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.util import dt as dt_util

from ..coordinator import SaxoCoordinator
from .base import SaxoValueSensorBase, ValueFn


class SaxoBalanceSensorBase(SaxoValueSensorBase):
    """Base class for Saxo Portfolio balance sensors."""

    def __init__(
        self,
        coordinator: SaxoCoordinator,
        sensor_type: str,
        value_fn: ValueFn,
        *,
        unavailable_without_value: bool = False,
    ) -> None:
        """Initialize the balance sensor.

        Args:
            coordinator: The coordinator instance
            sensor_type: Type identifier (unique ID suffix and translation key)
            value_fn: Reads this sensor's value from the coordinator data
            unavailable_without_value: Report unavailable while the value is None

        """
        super().__init__(
            coordinator,
            sensor_type,
            value_fn,
            device_class=SensorDeviceClass.MONETARY,
            unavailable_without_value=unavailable_without_value,
        )
        self._attr_native_unit_of_measurement = self._currency()
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes

        if self.coordinator.data is not None:
            # Add currency information
            attributes["currency"] = self._currency()

        return attributes


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


class SaxoCashTransferBalanceSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio Cash Transfer Balance sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "cash_transfer_balance",
            lambda data: data.performance.cash_transfer_balance,
        )


class SaxoYTDCashTransferSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio YTD Net Transfers sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "ytd_cash_transfer",
            lambda data: data.performance.ytd_cash_transfer,
            unavailable_without_value=True,
        )

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
