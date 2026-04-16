"""Unit tests for the Saxo Portfolio button platform.

Tests cover:
- async_setup_entry with valid and unknown client names
- SaxoRefreshButton initialization, unique_id, device_info
- async_press success and error handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.button import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from custom_components.saxo_portfolio.button import (
    PARALLEL_UPDATES,
    SaxoRefreshButton,
    async_setup_entry,
)
from custom_components.saxo_portfolio.const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    client_name: str = "John Doe",
    client_id: str = "12345",
    entry_id: str = "test_entry_123",
) -> MagicMock:
    """Create a mock SaxoCoordinator with the minimum attributes needed."""
    coordinator = MagicMock()
    coordinator.get_client_name.return_value = client_name
    coordinator.get_client_id.return_value = client_id
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.entry_id = entry_id
    coordinator.async_refresh = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_valid_client_name_adds_entities(self, mock_hass, mock_config_entry):
        """When client name is available, entities should be added."""
        coordinator = _make_coordinator(client_name="John Doe")
        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        async_add_entities = MagicMock()
        await async_setup_entry(mock_hass, mock_config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities = async_add_entities.call_args[0][0]
        assert len(entities) == 1
        assert isinstance(entities[0], SaxoRefreshButton)

    @pytest.mark.asyncio
    async def test_unknown_client_name_skips_setup(self, mock_hass, mock_config_entry):
        """When client name is 'unknown', setup should return early."""
        coordinator = _make_coordinator(client_name="unknown")
        mock_config_entry.runtime_data = MagicMock()
        mock_config_entry.runtime_data.coordinator = coordinator

        async_add_entities = MagicMock()
        await async_setup_entry(mock_hass, mock_config_entry, async_add_entities)

        async_add_entities.assert_not_called()


# ---------------------------------------------------------------------------
# SaxoRefreshButton.__init__
# ---------------------------------------------------------------------------


class TestSaxoRefreshButtonInit:
    """Tests for SaxoRefreshButton initialisation."""

    def test_unique_id_format(self):
        """unique_id should follow the saxo_{client_id}_refresh pattern."""
        coordinator = _make_coordinator(client_id="67890")
        with patch.object(SaxoRefreshButton, "__init__", lambda self, coord: None):
            btn = SaxoRefreshButton.__new__(SaxoRefreshButton)
        # Call the real __init__ logic manually
        btn = SaxoRefreshButton(coordinator)
        assert btn._attr_unique_id == "saxo_67890_refresh"

    def test_unique_id_lowercased(self):
        """Client IDs should be lowercased in the unique_id."""
        coordinator = _make_coordinator(client_id="ABC123")
        btn = SaxoRefreshButton(coordinator)
        assert btn._attr_unique_id == "saxo_abc123_refresh"

    def test_instance_attributes(self):
        """Instance attributes should be set correctly after init."""
        coordinator = _make_coordinator()
        btn = SaxoRefreshButton(coordinator)
        assert btn._attr_has_entity_name is True
        assert btn._attr_translation_key == "refresh"
        assert btn._attr_device_class == ButtonDeviceClass.UPDATE
        assert btn._attr_entity_category == EntityCategory.CONFIG


# ---------------------------------------------------------------------------
# SaxoRefreshButton.device_info
# ---------------------------------------------------------------------------


class TestSaxoRefreshButtonDeviceInfo:
    """Tests for the device_info property."""

    def test_device_info_returns_correct_values(self):
        """device_info should return correct DeviceInfo fields."""
        coordinator = _make_coordinator(client_id="99999", entry_id="entry_abc")
        btn = SaxoRefreshButton(coordinator)

        info = btn.device_info
        assert info["identifiers"] == {(DOMAIN, "entry_abc")}
        assert info["name"] == "Saxo 99999 Portfolio"
        assert info["manufacturer"] == DEVICE_MANUFACTURER
        assert info["model"] == DEVICE_MODEL
        assert (
            info["configuration_url"]
            == "https://www.developer.saxo/openapi/appmanagement"
        )
        assert info["sw_version"] is None

    def test_device_info_uses_current_client_id(self):
        """device_info should use the client_id from the coordinator at call time."""
        coordinator = _make_coordinator(client_id="111")
        btn = SaxoRefreshButton(coordinator)

        # Change the coordinator return value after creation
        coordinator.get_client_id.return_value = "222"
        info = btn.device_info
        assert info["name"] == "Saxo 222 Portfolio"


# ---------------------------------------------------------------------------
# SaxoRefreshButton.async_press
# ---------------------------------------------------------------------------


class TestSaxoRefreshButtonAsyncPress:
    """Tests for async_press."""

    @pytest.mark.asyncio
    async def test_async_press_calls_coordinator_refresh(self):
        """Pressing the button should call coordinator.async_refresh()."""
        coordinator = _make_coordinator()
        btn = SaxoRefreshButton(coordinator)

        await btn.async_press()
        coordinator.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_press_wraps_exception_in_ha_error(self):
        """Exceptions from async_refresh should be wrapped in HomeAssistantError."""
        coordinator = _make_coordinator()
        coordinator.async_refresh = AsyncMock(
            side_effect=ConnectionError("network failure")
        )
        btn = SaxoRefreshButton(coordinator)

        with pytest.raises(HomeAssistantError) as exc_info:
            await btn.async_press()

        err = exc_info.value
        assert err.translation_domain == DOMAIN
        assert err.translation_key == "refresh_failed"
        assert "network failure" in err.translation_placeholders["error"]

    @pytest.mark.asyncio
    async def test_async_press_preserves_original_cause(self):
        """The HomeAssistantError should chain the original exception."""
        original = RuntimeError("boom")
        coordinator = _make_coordinator()
        coordinator.async_refresh = AsyncMock(side_effect=original)
        btn = SaxoRefreshButton(coordinator)

        with pytest.raises(HomeAssistantError) as exc_info:
            await btn.async_press()

        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_parallel_updates_is_zero(self):
        """PARALLEL_UPDATES should be 0 (unlimited parallelism for HA)."""
        assert PARALLEL_UPDATES == 0
