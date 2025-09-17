"""Diagnostics support for Saxo Portfolio."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TIMEZONE, DOMAIN
from .coordinator import SaxoCoordinator

REDACT_KEYS = {
    "access_token",
    "refresh_token",
    "client_id",
    "client_secret",
    "token",
    "ClientId",
    "ClientKey",
    "AccountId",
    "AccountKey",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SaxoCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Get config data without sensitive information
    config_data = {
        "entry_id": entry.entry_id,
        "version": entry.version,
        "domain": entry.domain,
        "title": entry.title,
        "timezone": entry.data.get(CONF_TIMEZONE, "Not configured"),
        "has_token": bool(entry.data.get("token")),
        "has_redirect_uri": bool(entry.data.get("redirect_uri")),
    }

    # Get coordinator status
    coordinator_data = {
        "last_update_success": coordinator.last_update_success
        if hasattr(coordinator, "last_update_success")
        else None,
        "last_update_time": (
            coordinator.last_update_time_utc.isoformat()
            if hasattr(coordinator, "last_update_time_utc")
            and coordinator.last_update_time_utc
            else None
        ),
        "update_interval": str(coordinator.update_interval)
        if hasattr(coordinator, "update_interval")
        else None,
        "configured_timezone": getattr(coordinator, "_timezone", "Unknown"),
        "is_market_hours": coordinator._is_market_hours()
        if hasattr(coordinator, "_is_market_hours")
        else None,
        "has_data": coordinator.data is not None
        if hasattr(coordinator, "data")
        else False,
        "last_exception": str(coordinator.last_exception)
        if hasattr(coordinator, "last_exception") and coordinator.last_exception
        else None,
    }

    # Get data snapshot (redacted)
    data_snapshot = {}
    if coordinator.data:
        # Include non-sensitive data points
        data_snapshot = {
            "has_balance_data": bool(coordinator.data.get("balance")),
            "has_performance_data": bool(coordinator.data.get("performance")),
            "has_client_data": bool(coordinator.data.get("client")),
            "currency": coordinator.data.get("currency", "Unknown"),
            "data_keys": list(coordinator.data.keys()),
        }

        # Add some numeric values if available (non-sensitive)
        if "balance" in coordinator.data:
            balance = coordinator.data["balance"]
            data_snapshot["balance_fields"] = (
                list(balance.keys()) if isinstance(balance, dict) else "Not a dict"
            )

    # Market hours configuration
    from .const import MARKET_HOURS, DEFAULT_TIMEZONE, DEFAULT_UPDATE_INTERVAL_ANY
    from .const import (
        DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
        DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    )

    configured_tz = entry.data.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)
    market_config = {}

    if configured_tz == "any":
        market_config = {
            "mode": "Fixed interval (no market hours)",
            "update_interval": str(DEFAULT_UPDATE_INTERVAL_ANY),
        }
    elif configured_tz in MARKET_HOURS:
        market_info = MARKET_HOURS[configured_tz]
        market_config = {
            "timezone": configured_tz,
            "market_open": f"{market_info['open'][0]:02d}:{market_info['open'][1]:02d}",
            "market_close": f"{market_info['close'][0]:02d}:{market_info['close'][1]:02d}",
            "trading_days": market_info["weekdays"],
            "update_interval_market": str(DEFAULT_UPDATE_INTERVAL_MARKET_HOURS),
            "update_interval_after": str(DEFAULT_UPDATE_INTERVAL_AFTER_HOURS),
        }
    else:
        market_config = {
            "error": f"Unknown timezone: {configured_tz}",
            "fallback": DEFAULT_TIMEZONE,
        }

    # Token status (without exposing the actual token)
    token_status = {}
    if "token" in entry.data:
        token_data = entry.data["token"]
        current_time = time.time()

        token_status = {
            "has_access_token": bool(token_data.get("access_token")),
            "has_refresh_token": bool(token_data.get("refresh_token")),
            "token_type": token_data.get("token_type", "Unknown"),
        }

        if "expires_at" in token_data:
            expires_at = token_data["expires_at"]
            time_until_expiry = expires_at - current_time

            # Calculate human-readable expiry information
            expiry_datetime = datetime.fromtimestamp(expires_at)
            current_datetime = datetime.fromtimestamp(current_time)

            token_status.update(
                {
                    "expires_at_timestamp": expires_at,
                    "expires_at_iso": expiry_datetime.isoformat(),
                    "current_time_iso": current_datetime.isoformat(),
                    "expires_in_seconds": int(time_until_expiry),
                    "expires_in_minutes": round(time_until_expiry / 60, 1),
                    "expires_in_hours": round(time_until_expiry / 3600, 2),
                    "is_expired": time_until_expiry <= 0,
                    "needs_refresh_soon": time_until_expiry <= 300,  # 5 minutes
                    "needs_refresh_urgent": time_until_expiry <= 60,  # 1 minute
                }
            )

            # Add human-readable status
            if time_until_expiry <= 0:
                token_status["status"] = "EXPIRED"
            elif time_until_expiry <= 60:
                token_status["status"] = "CRITICAL - Expires in less than 1 minute"
            elif time_until_expiry <= 300:
                token_status["status"] = "WARNING - Expires in less than 5 minutes"
            elif time_until_expiry <= 3600:
                token_status["status"] = (
                    f"OK - Expires in {round(time_until_expiry / 60)} minutes"
                )
            else:
                token_status["status"] = (
                    f"OK - Expires in {round(time_until_expiry / 3600, 1)} hours"
                )

    # Get version from manifest
    manifest_path = Path(__file__).parent / "manifest.json"
    version = "unknown"
    try:
        manifest = json.loads(manifest_path.read_text())
        version = manifest.get("version", "unknown")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Integration information
    integration_info = {
        "version": version,
        "sensors_configured": 6,
        "sensor_types": [
            "cash_balance",
            "total_value",
            "non_margin_positions_value",
            "accumulated_profit_loss",
            "investment_performance",
            "cash_transfer_balance",
        ],
    }

    # Compile all diagnostics
    diagnostics = {
        "config": config_data,
        "coordinator": coordinator_data,
        "data_snapshot": data_snapshot,
        "market_configuration": market_config,
        "token_status": token_status,
        "integration": integration_info,
    }

    # Redact any sensitive information that might have slipped through
    return async_redact_data(diagnostics, REDACT_KEYS)
