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

from .const import (
    CONF_TIMEZONE,
    DEFAULT_TIMEZONE,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    MARKET_HOURS,
)
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


def _get_coordinator_status(coordinator: SaxoCoordinator) -> dict[str, Any]:
    """Return a defensive snapshot of coordinator runtime state."""
    _sentinel = object()
    last_update_time_utc: datetime | None = getattr(
        coordinator, "last_update_time_utc", None
    )
    update_interval = getattr(coordinator, "update_interval", _sentinel)
    data_attr = getattr(coordinator, "data", _sentinel)
    last_exception = getattr(coordinator, "last_exception", None)
    is_market_hours = getattr(coordinator, "_is_market_hours", None)

    return {
        "last_update_success": getattr(coordinator, "last_update_success", None),
        "last_update_time": last_update_time_utc.isoformat()
        if last_update_time_utc
        else None,
        "update_interval": str(update_interval)
        if update_interval is not _sentinel
        else None,
        "configured_timezone": getattr(coordinator, "_timezone", "Unknown"),
        "is_market_hours": is_market_hours() if callable(is_market_hours) else None,
        "has_data": data_attr is not None if data_attr is not _sentinel else False,
        "last_exception": str(last_exception) if last_exception else None,
    }


def _get_market_config(configured_tz: str) -> dict[str, Any]:
    """Return market-hours configuration for the configured timezone."""
    if configured_tz == "any":
        return {
            "mode": "Fixed interval (no market hours)",
            "update_interval": str(DEFAULT_UPDATE_INTERVAL_ANY),
        }
    if configured_tz in MARKET_HOURS:
        market_info = MARKET_HOURS[configured_tz]
        return {
            "timezone": configured_tz,
            "market_open": f"{market_info['open'][0]:02d}:{market_info['open'][1]:02d}",
            "market_close": f"{market_info['close'][0]:02d}:{market_info['close'][1]:02d}",
            "trading_days": market_info["weekdays"],
            "update_interval_market": str(DEFAULT_UPDATE_INTERVAL_MARKET_HOURS),
            "update_interval_after": str(DEFAULT_UPDATE_INTERVAL_AFTER_HOURS),
        }
    return {
        "error": f"Unknown timezone: {configured_tz}",
        "fallback": DEFAULT_TIMEZONE,
    }


def _format_token_status(token_data: dict[str, Any]) -> dict[str, Any]:
    """Return a human-readable token-expiry status dict (no secrets)."""
    token_status: dict[str, Any] = {
        "has_access_token": bool(token_data.get("access_token")),
        "has_refresh_token": bool(token_data.get("refresh_token")),
        "token_type": token_data.get("token_type", "Unknown"),
    }

    if "expires_at" not in token_data:
        return token_status

    current_time = time.time()
    expires_at = token_data["expires_at"]
    time_until_expiry = expires_at - current_time

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

    return token_status


def _get_data_snapshot(coordinator_data: dict[str, Any] | None) -> dict[str, Any]:
    """Return a non-sensitive snapshot of the coordinator's latest data."""
    if not coordinator_data:
        return {}

    snapshot: dict[str, Any] = {
        "has_balance_data": bool(coordinator_data.get("balance")),
        "has_performance_data": bool(coordinator_data.get("performance")),
        "has_client_data": bool(coordinator_data.get("client")),
        "currency": coordinator_data.get("currency", "Unknown"),
        "data_keys": list(coordinator_data.keys()),
    }

    if "balance" in coordinator_data:
        balance = coordinator_data["balance"]
        snapshot["balance_fields"] = (
            list(balance.keys()) if isinstance(balance, dict) else "Not a dict"
        )

    return snapshot


def _load_manifest_version() -> str:
    """Return the integration version from manifest.json, or 'unknown'."""
    manifest_path = Path(__file__).parent / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        return str(manifest.get("version", "unknown"))
    except FileNotFoundError, json.JSONDecodeError:
        return "unknown"


_INTEGRATION_INFO_STATIC: dict[str, Any] = {
    "sensors_configured": 16,
    "sensor_types": [
        "cash_balance",
        "total_value",
        "non_margin_positions_value",
        "accumulated_profit_loss",
        "investment_performance",
        "ytd_investment_performance",
        "month_investment_performance",
        "quarter_investment_performance",
        "cash_transfer_balance",
        "client_id",
        "account_id",
        "name",
        "token_expiry",
        "market_status",
        "last_update",
        "timezone",
    ],
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SaxoCoordinator = entry.runtime_data.coordinator

    config_data = {
        "entry_id": entry.entry_id,
        "version": entry.version,
        "domain": entry.domain,
        "title": entry.title,
        "timezone": entry.data.get(CONF_TIMEZONE, "Not configured"),
        "has_token": bool(entry.data.get("token")),
        "has_redirect_uri": bool(entry.data.get("redirect_uri")),
    }

    configured_tz = entry.data.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)
    token_status = (
        _format_token_status(entry.data["token"]) if "token" in entry.data else {}
    )

    diagnostics = {
        "config": config_data,
        "coordinator": _get_coordinator_status(coordinator),
        "data_snapshot": _get_data_snapshot(
            coordinator.data if hasattr(coordinator, "data") else None
        ),
        "market_configuration": _get_market_config(configured_tz),
        "token_status": token_status,
        "integration": {
            "version": _load_manifest_version(),
            **_INTEGRATION_INFO_STATIC,
        },
    }

    return async_redact_data(diagnostics, REDACT_KEYS)
