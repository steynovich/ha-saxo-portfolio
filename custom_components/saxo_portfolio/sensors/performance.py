"""Performance sensors (percentages and profit/loss from the performance API)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import SensorStateClass
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from ..const import STANDARD_PERIOD_MONTH_SPAN, STANDARD_PERIOD_QUARTER_SPAN
from ..coordinator import SaxoCoordinator
from .base import SaxoSensorBase, SaxoValueSensorBase, ValueFn


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


class SaxoPerformanceSensorBase(SaxoValueSensorBase):
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
            value_fn,
            unit_of_measurement="%",
        )
        self._time_period = time_period
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 2

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


class SaxoYTDProfitLossSensor(SaxoValueSensorBase):
    """Representation of a Saxo Portfolio YTD Profit/Loss sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "ytd_profit_loss",
            lambda data: data.performance.ytd_profit_loss,
            unavailable_without_value=True,
        )
        self._attr_native_unit_of_measurement = self._currency()
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor (kept through a failed update)."""
        return self._rounded_value()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        attributes = super().extra_state_attributes

        if self.coordinator.data is not None:
            attributes["currency"] = self._currency()

        return attributes


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
