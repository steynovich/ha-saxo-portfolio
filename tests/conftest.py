"""Shared test fixtures for Saxo Portfolio integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.saxo_portfolio.const import DOMAIN


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
