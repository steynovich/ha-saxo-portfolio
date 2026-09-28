"""Portfolio positions for the Saxo Portfolio integration.

Fetches ``/port/v1/netpositions/me`` for the opt-in position sensors,
parses it into typed :class:`PositionData`, keeps the last good result
cached and tracks whether the account has real-time market data access.
Failures degrade gracefully and never block balance data.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import re
from typing import Any

from .api.saxo_client import SaxoApiClient
from .const import API_REQUEST_DELAY

_LOGGER = logging.getLogger(__name__)


@dataclass
class PositionData:
    """Data class for a single portfolio position."""

    position_id: str
    symbol: str
    description: str
    asset_type: str
    amount: float
    current_price: float
    market_value: float
    profit_loss: float
    uic: int
    currency: str = "USD"

    @staticmethod
    def generate_slug(symbol: str, asset_type: str) -> str:
        """Generate a URL-safe slug for the position.

        Args:
            symbol: The position symbol (e.g., "AAPL", "EUR/USD")
            asset_type: The asset type (e.g., "Stock", "FxSpot")

        Returns:
            A lowercase slug suitable for entity IDs (e.g., "aapl_stock", "eur_usd_fxspot")

        """
        # Clean and lowercase the symbol
        clean_symbol = re.sub(r"[^a-zA-Z0-9]", "_", symbol.lower())
        # Remove consecutive underscores and strip leading/trailing underscores
        clean_symbol = re.sub(r"_+", "_", clean_symbol).strip("_")

        # Clean and lowercase the asset type
        clean_asset_type = re.sub(r"[^a-zA-Z0-9]", "_", asset_type.lower())
        clean_asset_type = re.sub(r"_+", "_", clean_asset_type).strip("_")

        return f"{clean_symbol}_{clean_asset_type}"


@dataclass
class PositionsCache:
    """Cache for portfolio positions data."""

    positions: dict[str, PositionData] = field(default_factory=dict)
    last_updated: datetime | None = None
    position_ids: list[str] = field(default_factory=list)


def has_market_data_access(first_position: dict[str, Any]) -> bool:
    """Determine market-data access from a raw net position.

    Without a market data subscription Saxo reports no current price type,
    or an approximated / no-market-access calculation reliability.
    """
    first_view = first_position.get("NetPositionView", {})
    current_price_type = first_view.get("CurrentPriceType", "")
    calc_reliability = first_view.get("CalculationReliability", "")

    _LOGGER.debug(
        "Market data access check - CurrentPriceType: %r, CalculationReliability: %r",
        current_price_type,
        calc_reliability,
    )

    return not (
        current_price_type == "None"
        or calc_reliability in ("NoMarketAccess", "ApproximatedPrice")
    )


def parse_position(raw_position: dict[str, Any]) -> tuple[str, PositionData] | None:
    """Parse a single raw net position into a (slug, PositionData) pair.

    Returns None and logs the error if parsing fails, or if the position
    has no symbol.
    """
    try:
        _LOGGER.debug(
            "Raw position keys: %s",
            list(raw_position.keys()),
        )

        net_position_base = raw_position.get("NetPositionBase", {})
        net_position_view = raw_position.get("NetPositionView", {})
        display_and_format = raw_position.get("DisplayAndFormat", {})

        position_id = raw_position.get("NetPositionId", "")
        uic = net_position_base.get("Uic", 0)
        asset_type = net_position_base.get("AssetType", "Unknown")
        amount = net_position_base.get("Amount", 0.0)

        symbol = display_and_format.get("Symbol", "")
        description = display_and_format.get("Description", "")
        currency = display_and_format.get("Currency", "USD")

        # Skip if no symbol
        if not symbol:
            _LOGGER.debug("Skipping position without symbol")
            return None

        profit_loss = (
            net_position_view.get("ProfitLossOnTrade")
            or net_position_view.get("ProfitLossOnTradeInBaseCurrency")
            or 0.0
        )

        # MarketValueOpen is the cost basis (negative = money spent)
        # Current market value = abs(cost basis) + profit/loss
        market_value_open = net_position_view.get("MarketValueOpen", 0.0)
        if market_value_open != 0.0:
            market_value = abs(market_value_open) + profit_loss
        else:
            market_value = net_position_view.get("Exposure", 0.0)

        current_price = net_position_view.get("CurrentPrice", 0.0)
        if current_price == 0.0 and market_value != 0.0 and amount != 0.0:
            current_price = market_value / abs(amount)
            _LOGGER.debug("Calculated price for %s from cost basis and P/L", symbol)

        slug = PositionData.generate_slug(symbol, asset_type)
        position_data = PositionData(
            position_id=position_id,
            symbol=symbol,
            description=description,
            asset_type=asset_type,
            amount=amount,
            current_price=current_price,
            market_value=market_value,
            profit_loss=profit_loss,
            uic=uic,
            currency=currency,
        )

        _LOGGER.debug("Parsed position: %s (%s)", symbol, asset_type)
        return slug, position_data

    except Exception as pos_error:
        _LOGGER.debug(
            "Error parsing position: %s",
            type(pos_error).__name__,
        )
        return None


class PositionsFetcher:
    """Fetches, parses and caches net positions."""

    def __init__(self, enabled: bool) -> None:
        """Initialize with an empty cache.

        Args:
            enabled: Whether position sensors are enabled (otherwise nothing
                is fetched)

        """
        self.enabled = enabled
        self.cache = PositionsCache()
        # None = unknown/not checked yet (no positions fetched)
        self.has_market_data_access: bool | None = None
        self._market_data_warning_logged = False

    async def async_fetch(self, client: SaxoApiClient) -> dict[str, PositionData]:
        """Fetch positions, returning the cached ones if the fetch fails.

        Returns:
            Dictionary mapping position slugs to PositionData objects (empty
            when position sensors are disabled)

        """
        if not self.enabled:
            _LOGGER.debug("Position sensors disabled, skipping fetch")
            return {}

        try:
            # Add delay before positions call to prevent rate limiting
            await asyncio.sleep(API_REQUEST_DELAY)

            positions_response = await client.get_net_positions()
            raw_positions = positions_response.get("Data", [])

            _LOGGER.debug(
                "Fetched %d raw positions from API, response keys: %s",
                len(raw_positions) if raw_positions else 0,
                list(positions_response.keys()),
            )

            if raw_positions:
                self._check_market_data_access(raw_positions[0])
            else:
                _LOGGER.debug(
                    "No positions in portfolio - cannot determine market data access status"
                )

            positions: dict[str, PositionData] = {}
            for raw_position in raw_positions:
                parsed = parse_position(raw_position)
                if parsed is not None:
                    slug, position_data = parsed
                    positions[slug] = position_data

            self._update_cache(positions)
            return positions

        except Exception as e:
            _LOGGER.debug(
                "Positions data fetch failed: %s, returning cached/empty",
                type(e).__name__,
            )
            return self.cache.positions

    def _check_market_data_access(self, first_position: dict[str, Any]) -> None:
        """Record market-data access, warning once when it is unavailable."""
        _LOGGER.debug(
            "Processing positions for market data access check",
        )

        access = has_market_data_access(first_position)
        self.has_market_data_access = access

        _LOGGER.debug(
            "Market data access determined: %s",
            "Available" if access else "Unavailable",
        )

        if not access and not self._market_data_warning_logged:
            _LOGGER.warning(
                "Market data access not available for positions API. "
                "Position prices are calculated from P/L data and may not "
                "reflect real-time values. Real-time market data may require "
                "a separate market data subscription on your Saxo account. "
                "Contact Saxo support for more information"
            )
            self._market_data_warning_logged = True

    def _update_cache(self, positions: dict[str, PositionData]) -> None:
        """Persist parsed positions to cache and log the summary."""
        self.cache.positions = positions
        self.cache.position_ids = list(positions.keys())
        self.cache.last_updated = datetime.now()
        _LOGGER.debug("%d positions parsed, positions cache updated", len(positions))
