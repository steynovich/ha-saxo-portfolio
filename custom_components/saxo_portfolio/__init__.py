"""The Saxo Portfolio integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DATA_COORDINATOR, DATA_UNSUB, DOMAIN, PLATFORMS, CONF_ENTITY_PREFIX
from .coordinator import SaxoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Saxo Portfolio from a config entry."""
    entity_prefix = entry.data.get(CONF_ENTITY_PREFIX, "unknown")
    has_token = bool(entry.data.get("token", {}).get("access_token"))

    _LOGGER.debug(
        "Setting up Saxo Portfolio integration - entry_id: %s, title: %s, prefix: %s, has_token: %s",
        entry.entry_id,
        entry.title,
        entity_prefix,
        has_token,
    )

    # Initialize integration data storage
    hass.data.setdefault(DOMAIN, {})

    try:
        # Create the coordinator
        coordinator = SaxoCoordinator(hass, entry)

        # Perform initial refresh to validate configuration
        await coordinator.async_refresh()

        # Store coordinator
        hass.data[DOMAIN][entry.entry_id] = {
            DATA_COORDINATOR: coordinator,
        }

        # Set up platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Mark setup as complete to enable reload logic for skipped sensors
        coordinator.mark_setup_complete()

        # Add update listener for options changes
        entry.async_on_unload(entry.add_update_listener(async_options_updated))

        _LOGGER.info("Successfully set up Saxo Portfolio integration")
        return True

    except Exception as e:
        _LOGGER.error(
            "Failed to set up Saxo Portfolio integration: %s", type(e).__name__
        )
        # Clean up any partial setup
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            coordinator = hass.data[DOMAIN][entry.entry_id].get(DATA_COORDINATOR)
            if coordinator:
                await coordinator.async_shutdown()
            del hass.data[DOMAIN][entry.entry_id]

        # Re-raise as ConfigEntryNotReady if it's a temporary issue
        if "auth" in str(e).lower() or "token" in str(e).lower():
            raise ConfigEntryNotReady("Authentication error") from e
        elif "network" in str(e).lower() or "timeout" in str(e).lower():
            raise ConfigEntryNotReady("Network error") from e
        else:
            # For other errors, let the config entry fail
            return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Saxo Portfolio integration for entry %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up coordinator and data
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})

        # Shutdown coordinator
        coordinator = entry_data.get(DATA_COORDINATOR)
        if coordinator:
            await coordinator.async_shutdown()

        # Remove update listeners
        unsub = entry_data.get(DATA_UNSUB)
        if unsub:
            unsub()

        # Remove entry data
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove domain data if no more entries
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)

        _LOGGER.info("Successfully unloaded Saxo Portfolio integration")

    return unload_ok


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Options updated for entry %s, triggering reload", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating Saxo Portfolio entry from version %s", config_entry.version
    )

    if config_entry.version == 1:
        # Migration logic for future versions
        _LOGGER.info("Entry already at current version")
        return True

    _LOGGER.error("Unknown configuration version: %s", config_entry.version)
    return False
