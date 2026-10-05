"""Position sensors (current price per open net position)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorStateClass
from homeassistant.helpers.typing import StateType

from ..coordinator import SaxoCoordinator
from ..data import DEFAULT_CURRENCY
from .base import SaxoSensorBase, finite_round

_LOGGER = logging.getLogger(__name__)


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
            unit_of_measurement=position.currency if position else DEFAULT_CURRENCY,
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
            return finite_round(position.current_price, 4)
        except TypeError as err:
            # A non-numeric price is a parsing bug; never log the value itself
            _LOGGER.debug(
                "Position price is not numeric: %s",
                type(err).__name__,
            )
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
