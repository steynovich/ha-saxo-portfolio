"""Diagnostics support for Saxo Portfolio."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_TIMEZONE,
    DEFAULT_TIMEZONE,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    MARKET_HOURS,
)
from .coordinator import SaxoCoordinator
from .data import SaxoPortfolioData

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
    "expires_at",
    "expires_at_timestamp",
    "expires_at_iso",
    "current_time_iso",
    "token_issued_at",
    "token_type",
    # The entry title embeds the Saxo ClientId once it is known
    "title",
}


def _get_coordinator_status(coordinator: SaxoCoordinator) -> dict[str, Any]:
    """Return a snapshot of coordinator runtime state."""
    last_update = coordinator.last_successful_update_time
    last_exception = coordinator.last_exception

    return {
        "last_update_success": coordinator.last_update_success,
        "last_update_time": last_update.isoformat() if last_update else None,
        "update_interval": str(coordinator.update_interval),
        "configured_timezone": coordinator.timezone,
        "is_market_hours": coordinator.is_market_hours,
        "has_data": coordinator.data is not None,
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


def _get_data_snapshot(coordinator_data: SaxoPortfolioData | None) -> dict[str, Any]:
    """Return a non-sensitive snapshot of the coordinator's latest data.

    Only field names and presence flags are reported, never values.
    """
    if coordinator_data is None:
        return {}

    return {
        "has_balance_data": coordinator_data.balance.has_any_value,
        "has_performance_data": coordinator_data.performance.has_any_value,
        "has_client_data": coordinator_data.client.has_any_value,
        "currency": coordinator_data.balance.currency,
        "data_keys": coordinator_data.field_names,
    }


def _get_entity_inventory(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Describe the sensors this entry actually registered.

    Derived from the entity registry rather than a hard-coded list, so it
    reflects YTD sensors, optional position sensors and diagnostic sensors
    exactly as created. Positions are counted but not listed, because
    their unique IDs embed the holding's symbol.
    """
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    sensors = [e for e in entries if e.domain == "sensor"]

    position_sensors = [
        e for e in sensors if str(e.translation_key or "").startswith("position")
    ]
    other_sensors = [e for e in sensors if e not in position_sensors]

    return {
        "sensors_configured": len(sensors),
        "sensor_types": sorted(
            str(e.translation_key) for e in other_sensors if e.translation_key
        ),
        "position_sensors": len(position_sensors),
        "diagnostic_sensors": sum(
            1 for e in sensors if e.entity_category == EntityCategory.DIAGNOSTIC
        ),
        "disabled_sensors": sum(1 for e in sensors if e.disabled_by is not None),
    }


def _load_manifest_version() -> str:
    """Return the integration version from manifest.json, or 'unknown'."""
    manifest_path = Path(__file__).parent / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        return str(manifest.get("version", "unknown"))
    except FileNotFoundError, json.JSONDecodeError:
        return "unknown"


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

    data_snapshot = _get_data_snapshot(coordinator.data)
    if data_snapshot:
        data_snapshot["position_count"] = len(coordinator.get_positions())

    diagnostics = {
        "config": config_data,
        "coordinator": _get_coordinator_status(coordinator),
        "data_snapshot": data_snapshot,
        "market_configuration": _get_market_config(configured_tz),
        "token_status": token_status,
        "integration": {
            "version": _load_manifest_version(),
            **_get_entity_inventory(hass, entry),
        },
    }

    return async_redact_data(diagnostics, REDACT_KEYS)
