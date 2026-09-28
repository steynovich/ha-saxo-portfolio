"""Unit tests for custom_components/saxo_portfolio/__init__.py.

Covers async_setup_entry, async_unload_entry, async_options_updated,
async_migrate_entry, async_reload_entry, async_setup and the refresh_data
service handler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)

from custom_components.saxo_portfolio import (
    SaxoRuntimeData,
    _async_handle_refresh_data,
    async_migrate_entry,
    async_options_updated,
    async_reload_entry,
    async_setup,
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
        """Successful setup creates coordinator and forwards platforms."""
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
        # Services are registered in async_setup, not per entry
        hass.services.async_register.assert_not_called()
        # runtime_data assigned
        assert isinstance(entry.runtime_data, SaxoRuntimeData)
        assert entry.runtime_data.coordinator is mock_coordinator
        # Update listener registered
        entry.async_on_unload.assert_called_once()

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
    async def test_service_kept_when_last_entry_unloaded(self) -> None:
        """Service stays registered when the last config entry is unloaded."""
        hass = _make_hass(existing_entries=[])
        hass.services.has_service.return_value = True
        entry = _make_entry()
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        entry.runtime_data = SaxoRuntimeData(coordinator=mock_coordinator)

        await async_unload_entry(hass, entry)

        hass.services.async_remove.assert_not_called()

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


class TestAsyncSetup:
    """Tests for the integration-level async_setup."""

    @pytest.mark.asyncio
    async def test_registers_refresh_service_once(self) -> None:
        """async_setup registers the refresh_data service with a schema."""
        hass = _make_hass()

        assert await async_setup(hass, {}) is True

        hass.services.async_register.assert_called_once()
        args, kwargs = hass.services.async_register.call_args
        assert args[:2] == (DOMAIN, SERVICE_REFRESH_DATA)
        assert kwargs["schema"] is not None


def _make_call(hass: MagicMock, data: dict | None = None) -> MagicMock:
    call = MagicMock(spec=ServiceCall)
    call.hass = hass
    call.data = data or {}
    return call


class TestHandleRefreshData:
    """Tests for the refresh_data service handler."""

    @pytest.mark.asyncio
    async def test_refreshes_all_loaded_entries(self) -> None:
        """Without a target, every loaded config entry is refreshed."""
        hass = _make_hass()
        coord1 = MagicMock(async_refresh=AsyncMock())
        coord2 = MagicMock(async_refresh=AsyncMock())
        entry1 = _make_entry(entry_id="e1")
        entry1.runtime_data = SaxoRuntimeData(coordinator=coord1)
        entry2 = _make_entry(entry_id="e2")
        entry2.runtime_data = SaxoRuntimeData(coordinator=coord2)
        hass.config_entries.async_loaded_entries = MagicMock(
            return_value=[entry1, entry2]
        )

        await _async_handle_refresh_data(_make_call(hass))

        hass.config_entries.async_loaded_entries.assert_called_once_with(DOMAIN)
        coord1.async_refresh.assert_awaited_once()
        coord2.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_loaded_entries_raises_validation_error(self) -> None:
        """With nothing loaded, a translated ServiceValidationError is raised."""
        hass = _make_hass()
        hass.config_entries.async_loaded_entries = MagicMock(return_value=[])

        with pytest.raises(ServiceValidationError) as exc_info:
            await _async_handle_refresh_data(_make_call(hass))

        assert exc_info.value.translation_domain == DOMAIN
        assert exc_info.value.translation_key == "no_loaded_entries"

    @pytest.mark.asyncio
    async def test_targets_single_entry(self) -> None:
        """With config_entry_id, only that loaded entry is refreshed."""
        hass = _make_hass()
        coord = MagicMock(async_refresh=AsyncMock())
        entry = _make_entry(entry_id="e1")
        entry.state = ConfigEntryState.LOADED
        entry.runtime_data = SaxoRuntimeData(coordinator=coord)
        hass.config_entries.async_get_entry = MagicMock(return_value=entry)
        hass.config_entries.async_loaded_entries = MagicMock()

        await _async_handle_refresh_data(_make_call(hass, {"config_entry_id": "e1"}))

        hass.config_entries.async_get_entry.assert_called_once_with("e1")
        hass.config_entries.async_loaded_entries.assert_not_called()
        coord.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_target_other_domain_entry_raises(self) -> None:
        """An entry id belonging to another integration is rejected."""
        hass = _make_hass()
        entry = _make_entry(entry_id="e1")
        entry.domain = "other"
        hass.config_entries.async_get_entry = MagicMock(return_value=entry)

        with pytest.raises(ServiceValidationError) as exc_info:
            await _async_handle_refresh_data(
                _make_call(hass, {"config_entry_id": "e1"})
            )
        assert exc_info.value.translation_key == "entry_not_found"

    @pytest.mark.asyncio
    async def test_target_not_loaded_entry_raises(self) -> None:
        """A targeted entry that is not loaded is rejected."""
        hass = _make_hass()
        entry = _make_entry(entry_id="e1")
        entry.state = ConfigEntryState.SETUP_RETRY
        hass.config_entries.async_get_entry = MagicMock(return_value=entry)

        with pytest.raises(ServiceValidationError) as exc_info:
            await _async_handle_refresh_data(
                _make_call(hass, {"config_entry_id": "e1"})
            )
        assert exc_info.value.translation_key == "entry_not_loaded"

    @pytest.mark.asyncio
    async def test_refresh_error_raises_ha_error(self) -> None:
        """Coordinator errors are wrapped in a translated HomeAssistantError."""
        hass = _make_hass()
        coord = MagicMock(async_refresh=AsyncMock(side_effect=Exception("API down")))
        entry = _make_entry(entry_id="e1")
        entry.runtime_data = SaxoRuntimeData(coordinator=coord)
        hass.config_entries.async_loaded_entries = MagicMock(return_value=[entry])

        with pytest.raises(HomeAssistantError) as exc_info:
            await _async_handle_refresh_data(_make_call(hass))
        assert exc_info.value.translation_key == "refresh_failed"


def test_service_exceptions_are_translated_everywhere() -> None:
    """refresh_data exception keys exist in strings.json and every translation."""
    import json
    from pathlib import Path

    base = Path(__file__).parents[2] / "custom_components" / "saxo_portfolio"
    files = [base / "strings.json", *sorted((base / "translations").glob("*.json"))]
    assert len(files) > 1
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "refresh_failed",
            "no_loaded_entries",
            "entry_not_found",
            "entry_not_loaded",
        ):
            assert data["exceptions"][key]["message"], f"{path.name}: {key}"
        fields = data["services"]["refresh_data"]["fields"]
        assert fields["config_entry_id"]["name"], path.name
