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

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saxo Portfolio button entities."""
    coordinator: SaxoCoordinator = entry.runtime_data.coordinator

    # Check if client name is available
    client_name = coordinator.get_client_name()
    if client_name == "unknown":
        _LOGGER.warning(
            "Skipping button setup - client data not yet available. "
            "Buttons will be created when client data is fetched."
        )
        return

    async_add_entities([SaxoRefreshButton(coordinator)])
    _LOGGER.debug("Added Saxo Portfolio refresh button")


class SaxoRefreshButton(CoordinatorEntity[SaxoCoordinator], ButtonEntity):
    """Button to manually refresh Saxo Portfolio data."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)

        client_id = coordinator.get_client_id()
        entity_prefix = f"saxo_{client_id}".lower()

        self._attr_unique_id = f"{entity_prefix}_refresh"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        client_id = self.coordinator.get_client_id()
        device_name = f"Saxo {client_id} Portfolio"

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            configuration_url="https://www.developer.saxo/openapi/appmanagement",
            sw_version=None,
        )

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
