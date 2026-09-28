"""Button platform for Saxo Portfolio integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
)
from .coordinator import SaxoCoordinator
from .data import UNKNOWN

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saxo Portfolio button entities."""
    coordinator: SaxoCoordinator = entry.runtime_data.coordinator

    if coordinator.client_info.client_name == UNKNOWN:
        _LOGGER.warning(
            "Skipping button setup - client data not yet available. "
            "Buttons will be created when client data is fetched."
        )
        return

    async_add_entities([SaxoRefreshButton(coordinator), SaxoReauthButton(coordinator)])
    _LOGGER.debug("Added Saxo Portfolio refresh and reauthenticate buttons")


class SaxoButtonEntity(CoordinatorEntity[SaxoCoordinator], ButtonEntity):
    """Base class for Saxo Portfolio buttons on the portfolio device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the button with a unique ID from its translation key."""
        super().__init__(coordinator)

        client_id = coordinator.client_info.client_id
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_{self._attr_translation_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        assert self.coordinator.config_entry is not None
        client_id = self.coordinator.client_info.client_id
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
            sw_version=None,
        )


class SaxoRefreshButton(SaxoButtonEntity):
    """Button to manually refresh Saxo Portfolio data."""

    _attr_translation_key = "refresh"
    _attr_device_class = ButtonDeviceClass.UPDATE

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.debug("Refresh button pressed, triggering coordinator update")
        try:
            await self.coordinator.async_refresh()
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_failed",
                translation_placeholders={"error": str(err)},
            ) from err


class SaxoReauthButton(SaxoButtonEntity):
    """Button that forces reauthentication with Saxo.

    Starts Home Assistant's reauth flow for this entry, the same flow that
    runs when Saxo rejects the refresh token. The current token stays in use
    until the user completes the new sign-in.
    """

    _attr_translation_key = "reauthenticate"

    async def async_press(self) -> None:
        """Start the reauth flow for this config entry."""
        assert self.coordinator.config_entry is not None
        _LOGGER.info(
            "Reauthenticate button pressed for config entry %s",
            self.coordinator.config_entry.entry_id,
        )
        self.coordinator.config_entry.async_start_reauth(self.hass)
