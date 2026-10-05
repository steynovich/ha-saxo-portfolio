"""The Saxo Portfolio integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENTITY_PREFIX,
    CONF_TIMEZONE,
    DOMAIN,
    PLATFORMS,
    SERVICE_REFRESH_DATA,
)
from .coordinator import SaxoCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class SaxoRuntimeData:
    """Runtime data stored in the config entry."""

    coordinator: SaxoCoordinator


type SaxoConfigEntry = ConfigEntry[SaxoRuntimeData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

SERVICE_REFRESH_DATA_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string},
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Saxo Portfolio integration.

    Services are registered here, once, so they exist regardless of the
    state of individual config entries (quality-scale rule action-setup).
    """
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_DATA,
        _async_handle_refresh_data,
        schema=SERVICE_REFRESH_DATA_SCHEMA,
    )
    _LOGGER.debug("Registered service: %s.%s", DOMAIN, SERVICE_REFRESH_DATA)
    return True


def _entries_to_refresh(hass: HomeAssistant, call: ServiceCall) -> list[ConfigEntry]:
    """Resolve the loaded config entries a refresh_data call targets."""
    entry_id: str | None = call.data.get(ATTR_CONFIG_ENTRY_ID)

    if entry_id is not None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"title": entry.title},
            )
        return [entry]

    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_loaded_entries",
        )
    return entries


async def _async_handle_refresh_data(call: ServiceCall) -> None:
    """Handle the refresh_data service call."""
    _LOGGER.debug("Service call: %s", SERVICE_REFRESH_DATA)
    for config_entry in _entries_to_refresh(call.hass, call):
        coordinator: SaxoCoordinator = config_entry.runtime_data.coordinator
        _LOGGER.debug("Refreshing coordinator for entry %s", config_entry.entry_id)
        try:
            await coordinator.async_refresh()
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_failed",
                translation_placeholders={"error": str(err)},
            ) from err


async def async_setup_entry(hass: HomeAssistant, entry: SaxoConfigEntry) -> bool:
    """Set up Saxo Portfolio from a config entry."""
    has_prefix = CONF_ENTITY_PREFIX in entry.data
    has_token = bool(entry.data.get("token", {}).get("access_token"))

    # Title and entity prefix contain the Saxo ClientId - never log them.
    _LOGGER.debug(
        "Setting up Saxo Portfolio integration - entry_id: %s, has_prefix: %s, has_token: %s",
        entry.entry_id,
        has_prefix,
        has_token,
    )

    try:
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
    except config_entry_oauth2_flow.ImplementationUnavailableError as err:
        raise ConfigEntryNotReady("OAuth implementation unavailable") from err

    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    coordinator = SaxoCoordinator(hass, entry, oauth_session)

    # Raises ConfigEntryNotReady on a transient failure (HA retries the setup)
    # and ConfigEntryAuthFailed on rejected credentials (HA starts reauth).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SaxoRuntimeData(coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Enables the reload logic for sensors skipped due to an unknown client name
    coordinator.mark_setup_complete()

    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    _LOGGER.info("Successfully set up Saxo Portfolio integration")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SaxoConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Saxo Portfolio integration for entry %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Shutdown coordinator
        await entry.runtime_data.coordinator.async_shutdown()

        _LOGGER.info("Successfully unloaded Saxo Portfolio integration")

    return unload_ok


async def async_options_updated(hass: HomeAssistant, entry: SaxoConfigEntry) -> None:
    """Handle a config entry update.

    Also called for token-only updates; the coordinator ignores those because
    it only reacts to a changed market timezone. A change to the position
    sensors setting reloads the entry from the options flow.
    """
    if getattr(entry, "runtime_data", None):
        await entry.runtime_data.coordinator.async_apply_options()
        return

    _LOGGER.debug(
        "No active coordinator, triggering reload for entry %s", entry.entry_id
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_reload_entry(hass: HomeAssistant, entry: SaxoConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating Saxo Portfolio entry from version %s", config_entry.version
    )

    if config_entry.version == 1:
        if config_entry.minor_version < 2:
            # "Europe/Frankfurt" is not an IANA zone; XETRA uses Europe/Berlin
            data = dict(config_entry.data)
            if data.get(CONF_TIMEZONE) == "Europe/Frankfurt":
                data[CONF_TIMEZONE] = "Europe/Berlin"
                _LOGGER.info("Migrated market timezone to Europe/Berlin")
            hass.config_entries.async_update_entry(
                config_entry, data=data, minor_version=2
            )
        return True

    _LOGGER.error("Unknown configuration version: %s", config_entry.version)
    return False
