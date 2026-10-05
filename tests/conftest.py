"""Shared test fixtures for Saxo Portfolio integration tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.saxo_portfolio.const import DOMAIN
from custom_components.saxo_portfolio.data import (
    BalanceData,
    ClientInfo,
    PerformanceData,
    SaxoPortfolioData,
)


@pytest.fixture(autouse=True)
def _patch_frame_helper():
    """Patch HA frame helper for all tests.

    DataUpdateCoordinator.__init__ calls frame.report_usage() which
    requires the full HA async runtime. Patch it out for unit/integration tests.
    """
    with patch("homeassistant.helpers.frame.report_usage"):
        yield


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry with valid OAuth token."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_123"
    entry.domain = DOMAIN
    entry.title = "Saxo Portfolio"
    entry.version = 1
    entry.options = {}
    entry.data = {
        "token": {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_at": (datetime.now() + timedelta(hours=1)).timestamp(),
            "token_type": "Bearer",
            "token_issued_at": datetime.now().timestamp(),
        },
        "timezone": "any",
    }
    return entry


@pytest.fixture
def mock_oauth_session(mock_config_entry):
    """Create a mock OAuth2 session."""
    session = MagicMock()
    session.token = mock_config_entry.data["token"]
    session.async_ensure_token_valid = AsyncMock()
    return session


def portfolio_data(**fields: Any) -> SaxoPortfolioData:
    """Build typed coordinator data from flat field names.

    Accepts any field of BalanceData, PerformanceData or ClientInfo (the
    names of the former coordinator data dict keys) plus ``last_updated``.
    Unset fields keep their dataclass defaults.
    """
    last_updated = fields.pop("last_updated", datetime(2026, 1, 1, 12, 0))
    groups: dict[type, dict[str, Any]] = {}
    for cls in (BalanceData, PerformanceData, ClientInfo):
        groups[cls] = {
            name: fields.pop(name)
            for name in list(fields)
            if name in cls.__dataclass_fields__
        }
    if fields:
        raise TypeError(f"Unknown portfolio data fields: {sorted(fields)}")
    return SaxoPortfolioData(
        balance=BalanceData(**groups[BalanceData]),
        performance=PerformanceData(**groups[PerformanceData]),
        client=ClientInfo(**groups[ClientInfo]),
        last_updated=last_updated,
    )


@pytest.fixture
def make_portfolio_data() -> Callable[..., SaxoPortfolioData]:
    """Return the ``portfolio_data`` factory."""
    return portfolio_data


def attach_portfolio_data(coordinator: Any, **fields: Any) -> SaxoPortfolioData:
    """Give a mock coordinator typed data and the matching ``client_info``."""
    data = portfolio_data(**fields)
    coordinator.data = data
    coordinator.client_info = data.client
    coordinator.client_id = data.client.client_id
    return data


@pytest.fixture
def set_portfolio_data() -> Callable[..., SaxoPortfolioData]:
    """Return the ``attach_portfolio_data`` helper."""
    return attach_portfolio_data
