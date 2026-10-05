"""Update-mode description shared by the Timezone sensor and diagnostics."""

from __future__ import annotations

from typing import Any

from .const import (
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    MARKET_HOURS,
    UPDATE_MODE_FIXED,
    UPDATE_MODE_MARKET_HOURS,
    UPDATE_MODE_UNKNOWN,
    market_hours_attributes,
)


def update_mode_attributes(
    timezone: str, is_market_hours: bool | None = None
) -> dict[str, Any]:
    """Describe how the configured timezone drives the update cadence.

    Args:
        timezone: Configured timezone, or "any" for the fixed schedule
        is_market_hours: Whether the market is open now; when None the
            current market status is left out

    """
    attrs: dict[str, Any] = {}

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
        if is_market_hours is not None:
            attrs["current_market_status"] = "Open" if is_market_hours else "Closed"
    else:
        attrs["mode"] = UPDATE_MODE_UNKNOWN
        attrs["error"] = f"Unknown timezone: {timezone}"

    return attrs
