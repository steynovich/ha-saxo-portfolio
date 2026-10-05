"""Sensor platform for Saxo Portfolio integration.

The entity classes live in the :mod:`.sensors` package, one module per family;
they are re-exported here so ``custom_components.saxo_portfolio.sensor`` stays
the single import point.
"""

from __future__ import annotations

import logging
import time  # noqa: F401  (patched by tests as ``sensor.time``)

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util  # noqa: F401  (patched by tests)

from .coordinator import SaxoCoordinator
from .data import UNKNOWN
from .sensors.balance import (
    SaxoBalanceSensorBase,
    SaxoCashBalanceSensor,
    SaxoCashTransferBalanceSensor,
    SaxoNonMarginPositionsValueSensor,
    SaxoTotalValueSensor,
    SaxoYTDCashTransferSensor,
)
from .sensors.base import SaxoSensorBase, SaxoValueSensorBase, ValueFn, finite_round
from .sensors.diagnostic import (
    SaxoAccountIDSensor,
    SaxoClientIDSensor,
    SaxoDiagnosticSensorBase,
    SaxoLastUpdateSensor,
    SaxoMarketDataAccessSensor,
    SaxoMarketStatusSensor,
    SaxoNameSensor,
    SaxoTimezoneSensor,
    SaxoTokenExpirySensor,
)
from .sensors.performance import (
    SaxoAccumulatedProfitLossSensor,
    SaxoInvestmentPerformanceSensor,
    SaxoMonthInvestmentPerformanceSensor,
    SaxoPerformanceSensorBase,
    SaxoQuarterInvestmentPerformanceSensor,
    SaxoYTDInvestmentPerformanceSensor,
    SaxoYTDProfitLossSensor,
)
from .sensors.position import SaxoPositionSensor

__all__ = [
    "PARALLEL_UPDATES",
    "SaxoAccountIDSensor",
    "SaxoAccumulatedProfitLossSensor",
    "SaxoBalanceSensorBase",
    "SaxoCashBalanceSensor",
    "SaxoCashTransferBalanceSensor",
    "SaxoClientIDSensor",
    "SaxoDiagnosticSensorBase",
    "SaxoInvestmentPerformanceSensor",
    "SaxoLastUpdateSensor",
    "SaxoMarketDataAccessSensor",
    "SaxoMarketStatusSensor",
    "SaxoMonthInvestmentPerformanceSensor",
    "SaxoNameSensor",
    "SaxoNonMarginPositionsValueSensor",
    "SaxoPerformanceSensorBase",
    "SaxoPositionSensor",
    "SaxoQuarterInvestmentPerformanceSensor",
    "SaxoSensorBase",
    "SaxoTimezoneSensor",
    "SaxoTokenExpirySensor",
    "SaxoTotalValueSensor",
    "SaxoValueSensorBase",
    "SaxoYTDCashTransferSensor",
    "SaxoYTDInvestmentPerformanceSensor",
    "SaxoYTDProfitLossSensor",
    "ValueFn",
    "async_setup_entry",
    "dt_util",
    "finite_round",
    "time",
]

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
                "Detected %d new positions, creating sensors", len(new_positions)
            )
            _LOGGER.debug("New position sensor slugs: %s", sorted(new_positions))
            new_entities = [
                SaxoPositionSensor(coordinator, position_slug)
                for position_slug in new_positions
            ]
            async_add_entities(new_entities, True)
            known_positions.update(new_positions)

    # Register listener for coordinator updates
    config_entry.async_on_unload(coordinator.async_add_listener(_check_new_positions))


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
