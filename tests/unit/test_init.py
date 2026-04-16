"""Unit tests for custom_components/saxo_portfolio/__init__.py.

Covers async_setup_entry, async_unload_entry, async_options_updated,
async_migrate_entry, async_reload_entry, and the refresh_data service handler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from custom_components.saxo_portfolio import (
    SaxoRuntimeData,
    async_migrate_entry,
    async_options_updated,
    async_reload_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.saxo_portfolio.const import (
    DOMAIN,
    PLATFORMS,
    SERVICE_REFRESH_DATA,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**overrides: object) -> MagicMock:
    """Create a mock config entry with sensible defaults."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = overrides.get("entry_id", "test_entry_id")
    entry.domain = DOMAIN
    entry.title = "Saxo Portfolio"
    entry.version = overrides.get("version", 1)
    entry.options = {}
    entry.data = overrides.get(
        "data",
        {
            "token": {"access_token": "tok123"},
            "entity_prefix": "saxo",
            "timezone": "any",
        },
    )
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock()
    return entry


def _make_hass(
    *,
    service_registered: bool = False,
    existing_entries: list | None = None,
) -> MagicMock:
    """Create a mock HomeAssistant with helpers pre-configured."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=existing_entries or [])
    hass.config_entries.async_reload = AsyncMock()
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=service_registered)
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    return hass


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

SETUP_PATCHES = (
    "custom_components.saxo_portfolio.config_entry_oauth2_flow"
    ".async_get_config_entry_implementation"
)
COORDINATOR_PATH = "custom_components.saxo_portfolio.SaxoCoordinator"
OAUTH_SESSION_PATH = (
    "custom_components.saxo_portfolio.config_entry_oauth2_flow.OAuth2Session"
)


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """Successful setup creates coordinator, forwards platforms, and registers service."""
        hass = _make_hass()
        entry = _make_entry()

        mock_impl = AsyncMock()
        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.mark_setup_complete = MagicMock()

        with (
            patch(SETUP_PATCHES, return_value=mock_impl),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        mock_coordinator.async_refresh.assert_awaited_once()
        mock_coordinator.mark_setup_complete.assert_called_once()
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            entry, PLATFORMS
        )
        # Service registered
        hass.services.async_register.assert_called_once()
        # runtime_data assigned
        assert isinstance(entry.runtime_data, SaxoRuntimeData)
        assert entry.runtime_data.coordinator is mock_coordinator
        # Update listener registered
        entry.async_on_unload.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_not_re_registered_if_already_exists(self) -> None:
        """Service is not registered again when it already exists."""
        hass = _make_hass(service_registered=True)
        entry = _make_entry()

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.mark_setup_complete = MagicMock()

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        hass.services.async_register.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_error_raises_config_entry_not_ready(self) -> None:
        """Auth-related exception is re-raised as ConfigEntryNotReady."""
        hass = _make_hass()
        entry = _make_entry()

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock(
            side_effect=Exception("Authentication token invalid")
        )

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
            pytest.raises(ConfigEntryNotReady, match="Authentication error"),
        ):
            await async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_network_error_raises_config_entry_not_ready(self) -> None:
        """Network-related exception is re-raised as ConfigEntryNotReady."""
        hass = _make_hass()
        entry = _make_entry()

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock(
            side_effect=Exception("Network timeout occurred")
        )

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
            pytest.raises(ConfigEntryNotReady, match="Network error"),
        ):
            await async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_unknown_error_returns_false(self) -> None:
        """Unrecognized exception causes setup to return False."""
        hass = _make_hass()
        entry = _make_entry()

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock(
            side_effect=Exception("Something completely unexpected")
        )

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is False

    @pytest.mark.asyncio
    async def test_implementation_failure_returns_false(self) -> None:
        """Failure to get OAuth implementation returns False."""
        hass = _make_hass()
        entry = _make_entry()

        with patch(
            SETUP_PATCHES,
            side_effect=Exception("No implementation found"),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is False

    @pytest.mark.asyncio
    async def test_missing_token_in_data(self) -> None:
        """Entry with no token still proceeds (OAuth session handles it)."""
        hass = _make_hass()
        entry = _make_entry(data={"entity_prefix": "saxo"})

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.mark_setup_complete = MagicMock()

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True


# ---------------------------------------------------------------------------
# async_unload_entry
# ---------------------------------------------------------------------------


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """Successful unload shuts down coordinator and returns True."""
        hass = _make_hass(existing_entries=[])
        entry = _make_entry()
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        entry.runtime_data = SaxoRuntimeData(coordinator=mock_coordinator)

        result = await async_unload_entry(hass, entry)

        assert result is True
        hass.config_entries.async_unload_platforms.assert_awaited_once_with(
            entry, PLATFORMS
        )
        mock_coordinator.async_shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_service_removed_when_last_entry(self) -> None:
        """Service is removed when the last config entry is unloaded."""
        hass = _make_hass(existing_entries=[])
        hass.services.has_service.return_value = True
        entry = _make_entry()
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        entry.runtime_data = SaxoRuntimeData(coordinator=mock_coordinator)

        await async_unload_entry(hass, entry)

        hass.services.async_remove.assert_called_once_with(DOMAIN, SERVICE_REFRESH_DATA)

    @pytest.mark.asyncio
    async def test_service_not_removed_when_other_entries_remain(self) -> None:
        """Service is kept when other config entries still exist."""
        remaining = [_make_entry(entry_id="other")]
        hass = _make_hass(existing_entries=remaining)
        entry = _make_entry()
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        entry.runtime_data = SaxoRuntimeData(coordinator=mock_coordinator)

        await async_unload_entry(hass, entry)

        hass.services.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_unload_platforms_failure(self) -> None:
        """When platform unload fails, coordinator is NOT shut down."""
        hass = _make_hass()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        entry = _make_entry()
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        entry.runtime_data = SaxoRuntimeData(coordinator=mock_coordinator)

        result = await async_unload_entry(hass, entry)

        assert result is False
        mock_coordinator.async_shutdown.assert_not_awaited()


# ---------------------------------------------------------------------------
# async_options_updated
# ---------------------------------------------------------------------------


class TestAsyncOptionsUpdated:
    """Tests for async_options_updated."""

    @pytest.mark.asyncio
    async def test_with_existing_coordinator_skips_reload(self) -> None:
        """When coordinator exists, reload is skipped (it handles updates)."""
        hass = _make_hass()
        entry = _make_entry()
        entry.runtime_data = SaxoRuntimeData(coordinator=MagicMock())

        await async_options_updated(hass, entry)

        hass.config_entries.async_reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_without_coordinator_triggers_reload(self) -> None:
        """When runtime_data is None, config entry is reloaded."""
        hass = _make_hass()
        entry = _make_entry()
        entry.runtime_data = None

        await async_options_updated(hass, entry)

        hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)

    @pytest.mark.asyncio
    async def test_without_runtime_data_attr_triggers_reload(self) -> None:
        """When runtime_data attribute is absent, config entry is reloaded."""
        hass = _make_hass()
        entry = _make_entry()
        del entry.runtime_data

        await async_options_updated(hass, entry)

        hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


# ---------------------------------------------------------------------------
# async_migrate_entry
# ---------------------------------------------------------------------------


class TestAsyncMigrateEntry:
    """Tests for async_migrate_entry."""

    @pytest.mark.asyncio
    async def test_version_1_returns_true(self) -> None:
        """Current version 1 needs no migration."""
        hass = _make_hass()
        entry = _make_entry(version=1)

        result = await async_migrate_entry(hass, entry)
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_version_returns_false(self) -> None:
        """Unknown version fails migration."""
        hass = _make_hass()
        entry = _make_entry(version=99)

        result = await async_migrate_entry(hass, entry)
        assert result is False


# ---------------------------------------------------------------------------
# async_reload_entry
# ---------------------------------------------------------------------------


class TestAsyncReloadEntry:
    """Tests for async_reload_entry."""

    @pytest.mark.asyncio
    async def test_calls_unload_then_setup(self) -> None:
        """Reload calls unload followed by setup."""
        hass = _make_hass()
        entry = _make_entry()

        with (
            patch(
                "custom_components.saxo_portfolio.async_unload_entry",
                new_callable=AsyncMock,
            ) as mock_unload,
            patch(
                "custom_components.saxo_portfolio.async_setup_entry",
                new_callable=AsyncMock,
            ) as mock_setup,
        ):
            await async_reload_entry(hass, entry)

        mock_unload.assert_awaited_once_with(hass, entry)
        mock_setup.assert_awaited_once_with(hass, entry)


# ---------------------------------------------------------------------------
# handle_refresh_data service
# ---------------------------------------------------------------------------


class TestHandleRefreshData:
    """Tests for the handle_refresh_data service handler."""

    @pytest.mark.asyncio
    async def test_refreshes_all_entries(self) -> None:
        """Service refreshes coordinators for every loaded config entry."""
        hass = _make_hass()
        entry = _make_entry()

        coord1 = MagicMock()
        coord1.async_refresh = AsyncMock()
        coord1.mark_setup_complete = MagicMock()

        entry1 = _make_entry(entry_id="e1")
        entry1.runtime_data = SaxoRuntimeData(coordinator=coord1)

        coord2 = MagicMock()
        coord2.async_refresh = AsyncMock()
        coord2.mark_setup_complete = MagicMock()

        entry2 = _make_entry(entry_id="e2")
        entry2.runtime_data = SaxoRuntimeData(coordinator=coord2)

        hass.config_entries.async_entries.return_value = [entry1, entry2]

        # We need to register the service, then extract and call the handler
        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.mark_setup_complete = MagicMock()

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            await async_setup_entry(hass, entry)

        # Extract the registered handler
        handler = hass.services.async_register.call_args[0][2]

        # Now make hass return our two entries with coordinators
        hass.config_entries.async_entries.return_value = [entry1, entry2]

        call = MagicMock(spec=ServiceCall)
        await handler(call)

        coord1.async_refresh.assert_awaited_once()
        coord2.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_entries_without_runtime_data(self) -> None:
        """Service skips entries that have no runtime_data."""
        hass = _make_hass()
        entry = _make_entry()

        entry_no_data = _make_entry(entry_id="e_no_data")
        entry_no_data.runtime_data = None

        hass.config_entries.async_entries.return_value = [entry_no_data]

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.mark_setup_complete = MagicMock()

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            await async_setup_entry(hass, entry)

        handler = hass.services.async_register.call_args[0][2]
        hass.config_entries.async_entries.return_value = [entry_no_data]

        call = MagicMock(spec=ServiceCall)
        # Should not raise
        await handler(call)

    @pytest.mark.asyncio
    async def test_refresh_error_raises_ha_error(self) -> None:
        """Service wraps coordinator errors in HomeAssistantError."""
        hass = _make_hass()
        entry = _make_entry()

        coord = MagicMock()
        coord.async_refresh = AsyncMock(side_effect=Exception("API down"))
        coord.mark_setup_complete = MagicMock()

        entry_with_coord = _make_entry(entry_id="e1")
        entry_with_coord.runtime_data = SaxoRuntimeData(coordinator=coord)

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.mark_setup_complete = MagicMock()

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            await async_setup_entry(hass, entry)

        handler = hass.services.async_register.call_args[0][2]
        hass.config_entries.async_entries.return_value = [entry_with_coord]

        call = MagicMock(spec=ServiceCall)
        with pytest.raises(HomeAssistantError):
            await handler(call)

    @pytest.mark.asyncio
    async def test_skips_entries_without_runtime_data_attr(self) -> None:
        """Service handles entries where runtime_data attribute does not exist."""
        hass = _make_hass()
        entry = _make_entry()

        entry_no_attr = _make_entry(entry_id="e_no_attr")
        del entry_no_attr.runtime_data

        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.mark_setup_complete = MagicMock()

        with (
            patch(SETUP_PATCHES, return_value=AsyncMock()),
            patch(OAUTH_SESSION_PATH),
            patch(COORDINATOR_PATH, return_value=mock_coordinator),
        ):
            await async_setup_entry(hass, entry)

        handler = hass.services.async_register.call_args[0][2]
        hass.config_entries.async_entries.return_value = [entry_no_attr]

        call = MagicMock(spec=ServiceCall)
        await handler(call)  # Should not raise
