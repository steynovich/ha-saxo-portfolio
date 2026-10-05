"""Integration tests for the refresh_data service lifecycle.

The service is registered once in async_setup (HA quality-scale rule
action-setup) and must stay available while entries are set up, unloaded
and reloaded.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.saxo_portfolio.const import DOMAIN, SERVICE_REFRESH_DATA

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allow loading the custom integration in the test hass instance.

    ``custom_components`` is a namespace package; with an editable install its
    ``__path__`` also contains a non-directory path hook (and possibly other
    checkouts), which HA's loader cannot scan. Pin it to the directory that
    holds the integration under test.
    """
    import custom_components
    import custom_components.saxo_portfolio as integration

    monkeypatch.setattr(
        custom_components,
        "__path__",
        [str(Path(integration.__file__).resolve().parents[1])],
    )


@pytest.fixture
def coordinators() -> Generator[dict[str, MagicMock]]:
    """Patch OAuth and the coordinator; yield created coordinators by entry_id."""
    created: dict[str, MagicMock] = {}

    def _make_coordinator(hass: HomeAssistant, entry, oauth_session) -> MagicMock:
        coordinator = MagicMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.async_refresh = AsyncMock()
        coordinator.async_shutdown = AsyncMock()
        coordinator.mark_setup_complete = MagicMock()
        created[entry.entry_id] = coordinator
        return coordinator

    with (
        patch(
            "custom_components.saxo_portfolio.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.saxo_portfolio.config_entry_oauth2_flow.OAuth2Session"
        ),
        patch(
            "custom_components.saxo_portfolio.SaxoCoordinator",
            side_effect=_make_coordinator,
        ),
        patch("custom_components.saxo_portfolio.PLATFORMS", []),
    ):
        yield created


def _add_entry(hass: HomeAssistant, unique_id: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Saxo {unique_id}",
        unique_id=unique_id,
        data={
            "auth_implementation": DOMAIN,
            "token": {"access_token": "tok", "refresh_token": "ref"},
            "timezone": "any",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_service_registered_at_integration_setup(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """The service exists as soon as the integration loads, without any entry."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_REFRESH_DATA)


async def test_service_without_loaded_entries_raises_validation_error(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """Calling the service with no loaded entries raises a translated error."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(DOMAIN, SERVICE_REFRESH_DATA, {}, blocking=True)
    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "no_loaded_entries"


async def test_service_survives_unload_and_reload(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """Setup, unload and reload an entry: the service stays available."""
    entry = _add_entry(hass, "client_1")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, SERVICE_REFRESH_DATA)

    coordinator = coordinators[entry.entry_id]
    coordinator.async_refresh.reset_mock()
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_DATA, {}, blocking=True)
    coordinator.async_refresh.assert_awaited_once()

    # Unload: service remains, but calling it is a validation error
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.services.has_service(DOMAIN, SERVICE_REFRESH_DATA)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, SERVICE_REFRESH_DATA, {}, blocking=True)

    # Reload: service still there and refreshes the new coordinator
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, SERVICE_REFRESH_DATA)

    reloaded = coordinators[entry.entry_id]
    reloaded.async_refresh.reset_mock()
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_DATA, {}, blocking=True)
    reloaded.async_refresh.assert_awaited_once()


async def test_service_refreshes_all_loaded_entries(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """Without a target, every loaded entry is refreshed."""
    entry1 = _add_entry(hass, "client_1")
    entry2 = _add_entry(hass, "client_2")
    # Setting up the integration loads every entry of the domain
    assert await hass.config_entries.async_setup(entry1.entry_id)
    await hass.async_block_till_done()
    assert entry2.state is ConfigEntryState.LOADED

    for coordinator in coordinators.values():
        coordinator.async_refresh.reset_mock()

    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_DATA, {}, blocking=True)

    coordinators[entry1.entry_id].async_refresh.assert_awaited_once()
    coordinators[entry2.entry_id].async_refresh.assert_awaited_once()


async def test_service_refreshes_only_targeted_entry(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """With config_entry_id, only that entry is refreshed."""
    entry1 = _add_entry(hass, "client_1")
    entry2 = _add_entry(hass, "client_2")
    # Setting up the integration loads every entry of the domain
    assert await hass.config_entries.async_setup(entry1.entry_id)
    await hass.async_block_till_done()
    assert entry2.state is ConfigEntryState.LOADED

    for coordinator in coordinators.values():
        coordinator.async_refresh.reset_mock()

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REFRESH_DATA,
        {"config_entry_id": entry2.entry_id},
        blocking=True,
    )

    coordinators[entry1.entry_id].async_refresh.assert_not_awaited()
    coordinators[entry2.entry_id].async_refresh.assert_awaited_once()


async def test_service_targeting_unknown_entry_raises(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """Targeting an entry that does not exist is a validation error."""
    entry = _add_entry(hass, "client_1")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REFRESH_DATA,
            {"config_entry_id": "does_not_exist"},
            blocking=True,
        )
    assert exc_info.value.translation_key == "entry_not_found"


async def test_service_targeting_unloaded_entry_raises(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """Targeting an entry that is not loaded is a validation error."""
    loaded = _add_entry(hass, "client_1")
    not_loaded = _add_entry(hass, "client_2")
    assert await hass.config_entries.async_setup(loaded.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(not_loaded.entry_id)

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REFRESH_DATA,
            {"config_entry_id": not_loaded.entry_id},
            blocking=True,
        )
    assert exc_info.value.translation_key == "entry_not_loaded"


async def test_service_refresh_failure_raises_translated_error(
    hass: HomeAssistant, coordinators: dict[str, MagicMock]
) -> None:
    """A failing refresh surfaces as a translated HomeAssistantError."""
    entry = _add_entry(hass, "client_1")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinators[entry.entry_id].async_refresh.side_effect = RuntimeError("down")

    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(DOMAIN, SERVICE_REFRESH_DATA, {}, blocking=True)
    assert not isinstance(exc_info.value, ServiceValidationError)
    assert exc_info.value.translation_key == "refresh_failed"
