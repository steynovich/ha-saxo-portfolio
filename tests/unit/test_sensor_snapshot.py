"""Snapshot of every sensor's state, attributes and availability.

Guards behaviour-preserving refactors of the coordinator data model (#26)
and the coordinator module split (#27). A real coordinator runs full
updates against fixture API responses (served by a fake HTTP session), the
real sensor platform creates its entities, and every entity's observable
output is compared against a stored snapshot.

Scenarios cover the fully populated case, performance never fetched (#15),
a partial performance refresh that keeps last good values, sticky
availability during recent and sustained failures, and missing data.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.saxo_portfolio.const import (
    API_PERFORMANCE_V4_ENDPOINT,
    DOMAIN,
    PERFORMANCE_UPDATE_INTERVAL,
    SAXO_API_BASE_URL,
)
from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.saxo_portfolio.sensor import async_setup_entry

from .test_log_sanitization import _fake_session

# Wednesday, 11:00 in Amsterdam: inside market hours.
FROZEN_NOW = "2026-03-18 10:00:00+00:00"


def _config_entry(timezone: str) -> MagicMock:
    """Build a config entry with a token expiring in one hour (frozen time)."""
    now = dt_util.utcnow().timestamp()
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "snapshot_entry"
    entry.domain = DOMAIN
    entry.title = "Saxo Portfolio"
    entry.version = 1
    entry.options = {"enable_position_sensors": True}
    entry.pref_disable_polling = False
    entry.data = {
        "token": {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_at": now + 3600,
            "token_type": "Bearer",
            "token_issued_at": now,
        },
        "timezone": timezone,
    }
    return entry


def _session(failing: set[str]) -> MagicMock:
    """Fixture session; requests to paths starting with a ``failing`` prefix time out."""
    session = _fake_session()
    serve = session.get.side_effect

    def _get(url: str, params: dict[str, Any] | None = None, headers: Any = None):
        path = url.removeprefix(SAXO_API_BASE_URL)
        if any(path.startswith(prefix) for prefix in failing):
            raise TimeoutError
        return serve(url, params=params, headers=headers)

    session.get = MagicMock(side_effect=_get)
    return session


class _Harness:
    """A real coordinator plus the entities its sensor platform creates."""

    def __init__(self, timezone: str) -> None:
        self.hass = MagicMock(spec=HomeAssistant)
        self.hass.data = {}
        self.hass.config_entries = MagicMock()
        self.entry = _config_entry(timezone)
        oauth = MagicMock()
        oauth.token = self.entry.data["token"]
        oauth.async_ensure_token_valid = AsyncMock()
        self.coordinator = SaxoCoordinator(self.hass, self.entry, oauth)
        self.coordinator.config_entry = self.entry
        self.entry.runtime_data = MagicMock()
        self.entry.runtime_data.coordinator = self.coordinator
        self.entities: list[SensorEntity] = []
        # Endpoint path prefixes that currently fail (the API client, and so
        # its session, is reused across updates).
        self.failing: set[str] = set()
        self.session = _session(self.failing)

    async def update(self) -> None:
        """Run one coordinator update the way DataUpdateCoordinator would."""
        with (
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=self.session,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            self.coordinator.data = await self.coordinator._async_update_data()
        self.coordinator.last_update_success = True

    async def setup_sensors(self) -> None:
        """Create the sensor entities through the real platform setup."""

        def _add(entities: list[SensorEntity], update: bool = False) -> None:
            self.entities.extend(entities)

        # The new-position listener needs a running HA loop; not under test here.
        with patch.object(
            self.coordinator, "async_add_listener", return_value=lambda: None
        ):
            await async_setup_entry(self.hass, self.entry, _add)

    def snapshot(self) -> dict[str, Any]:
        """Observable output of every entity, keyed by unique id."""
        return {
            str(entity.unique_id): _entity_snapshot(entity) for entity in self.entities
        }


def _entity_snapshot(entity: SensorEntity) -> dict[str, Any]:
    """Everything Home Assistant reads from a sensor entity."""
    last_reset = entity.last_reset
    return {
        "available": entity.available,
        "native_value": entity.native_value,
        "extra_state_attributes": entity.extra_state_attributes,
        "last_reset": last_reset.isoformat() if last_reset else None,
        "translation_key": entity.translation_key,
        "translation_placeholders": dict(entity.translation_placeholders or {}),
        "device_class": entity.device_class,
        "state_class": entity.state_class,
        "native_unit_of_measurement": entity.native_unit_of_measurement,
        "suggested_display_precision": entity.suggested_display_precision,
        "entity_category": entity.entity_category,
        "entity_registry_enabled_default": entity.entity_registry_enabled_default,
        "options": entity.options,
        "device_info": entity.device_info,
    }


async def _diagnostics(harness: _Harness) -> dict[str, Any]:
    """Diagnostics sections that derive from coordinator data."""
    with (
        patch("custom_components.saxo_portfolio.diagnostics.er.async_get"),
        patch(
            "custom_components.saxo_portfolio.diagnostics.er.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        result = await async_get_config_entry_diagnostics(harness.hass, harness.entry)
    return {
        "coordinator": result["coordinator"],
        "data_snapshot": result["data_snapshot"],
    }


@pytest.fixture
def frozen() -> Iterator[Any]:
    """Freeze wall-clock time so timestamps and periods are deterministic."""
    with freeze_time(FROZEN_NOW) as frozen_time:
        yield frozen_time


async def _harness(
    timezone: str = "Europe/Amsterdam", failing: tuple[str, ...] = ()
) -> _Harness:
    harness = _Harness(timezone)
    harness.failing.update(failing)
    await harness.update()
    await harness.setup_sensors()
    return harness


async def test_full_data(frozen: Any, snapshot: SnapshotAssertion) -> None:
    """All endpoints succeed: every sensor has a value."""
    harness = await _harness()

    assert harness.snapshot() == snapshot
    assert await _diagnostics(harness) == snapshot(name="diagnostics")


async def test_fixed_schedule_timezone(
    frozen: Any, snapshot: SnapshotAssertion
) -> None:
    """The "any" timezone reports a fixed schedule."""
    harness = await _harness(timezone="any")

    assert harness.snapshot() == snapshot


async def test_performance_never_fetched(
    frozen: Any, snapshot: SnapshotAssertion
) -> None:
    """Performance endpoints fail on the first update: values are unknown."""
    harness = await _harness(failing=("/hist/",))

    assert harness.snapshot() == snapshot
    assert await _diagnostics(harness) == snapshot(name="diagnostics")


async def test_partial_refresh_keeps_last_good_values(
    frozen: Any, snapshot: SnapshotAssertion
) -> None:
    """After the cache expires, a v4 failure keeps the last good v4 values."""
    harness = await _harness()
    first_fetch = harness.coordinator.performance_last_updated

    frozen.tick(PERFORMANCE_UPDATE_INTERVAL + timedelta(minutes=1))
    harness.failing.add(API_PERFORMANCE_V4_ENDPOINT)
    await harness.update()

    # A partial fetch does not refresh the cache timestamp (#15).
    assert harness.coordinator.performance_last_updated == first_fetch
    assert harness.snapshot() == snapshot


@pytest.mark.parametrize(
    ("minutes_since_success", "label"),
    [(5, "recent"), (60, "sustained")],
)
async def test_failing_updates(
    frozen: Any,
    snapshot: SnapshotAssertion,
    minutes_since_success: int,
    label: str,
) -> None:
    """Sensors stay available through short outages, not sustained ones."""
    harness = await _harness()

    frozen.tick(timedelta(minutes=minutes_since_success))
    harness.coordinator.last_update_success = False
    harness.coordinator.last_exception = Exception("Network error")

    assert harness.snapshot() == snapshot(name=label)


async def test_no_data(frozen: Any, snapshot: SnapshotAssertion) -> None:
    """Entities whose coordinator has lost its data entirely."""
    harness = await _harness()
    harness.coordinator.data = None
    harness.coordinator.last_update_success = False

    assert harness.snapshot() == snapshot
    assert await _diagnostics(harness) == snapshot(name="diagnostics")
