"""Tests for the overall coordinator update timeout (issue #35)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.saxo_portfolio.data import BalanceData
from .test_coordinator import _bare_coordinator

_TIMEOUT = "custom_components.saxo_portfolio.coordinator.COORDINATOR_UPDATE_TIMEOUT"


async def _hang(*_args, **_kwargs):
    await asyncio.sleep(3600)


class TestCoordinatorUpdateTimeout:
    """The whole fetch is bounded by COORDINATOR_UPDATE_TIMEOUT."""

    async def test_hanging_token_refresh_raises_update_failed(self):
        """A hung token refresh/retry loop is cut off and surfaces UpdateFailed."""
        coord = _bare_coordinator()
        with (
            patch(_TIMEOUT, 0.05),
            patch.object(coord, "_ensure_token_valid", side_effect=_hang),
            pytest.raises(UpdateFailed, match="timeout"),
        ):
            await asyncio.wait_for(coord._fetch_portfolio_data(), timeout=5)

    async def test_hanging_balance_fetch_raises_update_failed(self):
        """A hung data fetch is cut off and surfaces UpdateFailed."""
        coord = _bare_coordinator()
        with (
            patch(_TIMEOUT, 0.05),
            patch.object(coord, "_ensure_token_valid", new_callable=AsyncMock),
            patch.object(coord, "_fetch_balance_with_logging", side_effect=_hang),
            patch.object(coord, "_api_client", MagicMock(), create=True),
            pytest.raises(UpdateFailed, match="timeout"),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            await asyncio.wait_for(coord._fetch_portfolio_data(), timeout=5)

    async def test_stagger_offset_not_counted_against_timeout(self):
        """The one-shot multi-account stagger sleep happens outside the timeout."""
        coord = _bare_coordinator()
        coord._last_successful_update = datetime.now()
        coord._initial_update_offset = 0.2  # longer than the patched timeout
        with (
            patch(_TIMEOUT, 0.1),
            patch.object(coord, "_ensure_token_valid", new_callable=AsyncMock),
            patch.object(
                coord,
                "_fetch_balance_with_logging",
                new_callable=AsyncMock,
                return_value=BalanceData(),
            ),
            patch.object(coord._performance, "async_update", new_callable=AsyncMock),
            patch.object(coord._positions, "async_fetch", new_callable=AsyncMock),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            result = await coord._fetch_portfolio_data()
        assert result.balance == BalanceData()
