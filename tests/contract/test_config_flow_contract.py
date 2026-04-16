"""Contract tests for OAuth Configuration Flow data schema.

These tests validate that the config flow follows Home Assistant
OAuth2 patterns and returns correct data structures.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from custom_components.saxo_portfolio.config_flow import (
    SaxoOptionsFlowHandler,
    SaxoPortfolioFlowHandler,
)
from custom_components.saxo_portfolio.const import DOMAIN


@pytest.mark.contract
class TestSaxoConfigFlowContract:
    """Contract tests for Saxo Portfolio OAuth configuration flow."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = Mock(spec=HomeAssistant)
        hass.data = {}
        hass.config_entries = Mock()
        hass.config_entries.async_entries = Mock(return_value=[])
        hass.config_entries.flow.async_progress_by_handler = Mock(return_value=[])
        return hass

    @pytest.fixture
    def config_flow(self, mock_hass):
        """Create a config flow instance."""
        flow = SaxoPortfolioFlowHandler()
        flow.hass = mock_hass
        return flow

    def test_config_flow_domain(self, config_flow):
        """Test that config flow has correct domain."""
        assert hasattr(config_flow, "DOMAIN")
        assert config_flow.DOMAIN == DOMAIN
        assert DOMAIN == "saxo_portfolio"

    def test_config_flow_version(self, config_flow):
        """Test that config flow has version defined."""
        assert hasattr(config_flow, "VERSION")
        assert isinstance(config_flow.VERSION, int)
        assert config_flow.VERSION >= 1

    def test_config_flow_oauth2_inheritance(self, config_flow):
        """Test that config flow inherits from OAuth2 flow handler."""
        assert isinstance(
            config_flow, config_entry_oauth2_flow.AbstractOAuth2FlowHandler
        )

    def test_config_flow_logger(self, config_flow):
        """Test that config flow has proper logging."""
        assert hasattr(config_flow, "logger")
        logger = config_flow.logger
        assert logger is not None
        assert hasattr(logger, "debug")
        assert hasattr(logger, "error")

    def test_config_flow_extra_authorize_data(self, config_flow):
        """Test that extra authorize data includes required scope."""
        data = config_flow.extra_authorize_data
        assert isinstance(data, dict)
        assert "scope" in data
        assert data["scope"] == "openapi"

    @pytest.mark.asyncio
    async def test_config_flow_user_step_aborts_without_credentials(self, config_flow):
        """Test that user step aborts when no application credentials exist."""
        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={},
        ):
            result = await config_flow.async_step_user()

        assert isinstance(result, dict)
        assert result["type"] == "abort"
        assert result["reason"] == "missing_credentials"
        assert "description_placeholders" in result

    @pytest.mark.asyncio
    async def test_config_flow_user_step_proceeds_with_credentials(self, config_flow):
        """Test that user step proceeds when application credentials exist."""
        mock_impl = Mock()
        mock_impl.domain = DOMAIN

        with (
            patch(
                "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
                return_value={"test_impl": mock_impl},
            ),
            patch.object(
                config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
                "async_step_pick_implementation",
                return_value={"type": "external", "step_id": "auth"},
            ) as mock_pick,
        ):
            await config_flow.async_step_pick_implementation()
            mock_pick.assert_called_once()

    @pytest.mark.asyncio
    async def test_config_flow_oauth_create_entry_routes_to_timezone(self, config_flow):
        """Test OAuth entry creation routes to timezone step for new entries."""
        mock_oauth_data = {
            "token": {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_at": 1640995200,
                "token_type": "Bearer",
            },
        }

        mock_client = AsyncMock()
        mock_client.get_client_details = AsyncMock(
            return_value={"ClientKey": "test_key_123", "ClientId": "test_id"}
        )

        with (
            patch(
                "custom_components.saxo_portfolio.config_flow.async_get_clientsession",
                return_value=Mock(),
            ),
            patch(
                "custom_components.saxo_portfolio.config_flow.SaxoApiClient",
                return_value=mock_client,
            ),
            patch.object(config_flow, "async_set_unique_id", new_callable=AsyncMock),
            patch.object(config_flow, "_abort_if_unique_id_configured"),
        ):
            result = await config_flow.async_oauth_create_entry(mock_oauth_data)

        # New entries route to timezone step
        assert result["type"] == "form"
        assert result["step_id"] == "timezone"

    @pytest.mark.asyncio
    async def test_config_flow_oauth_create_entry_adds_token_issued_at(
        self, config_flow
    ):
        """Test that token_issued_at is added if missing."""
        mock_oauth_data = {
            "token": {
                "access_token": "test",
                "refresh_token": "test",
                "expires_at": 9999999999,
                "token_type": "Bearer",
            },
        }

        mock_client = AsyncMock()
        mock_client.get_client_details = AsyncMock(
            return_value={"ClientKey": "test_key_123", "ClientId": "test_id"}
        )

        with (
            patch(
                "custom_components.saxo_portfolio.config_flow.async_get_clientsession",
                return_value=Mock(),
            ),
            patch(
                "custom_components.saxo_portfolio.config_flow.SaxoApiClient",
                return_value=mock_client,
            ),
            patch.object(config_flow, "async_set_unique_id", new_callable=AsyncMock),
            patch.object(config_flow, "_abort_if_unique_id_configured"),
        ):
            await config_flow.async_oauth_create_entry(mock_oauth_data)

        # token_issued_at should be added to the stored data
        assert "token_issued_at" in config_flow._oauth_data["token"]

    @pytest.mark.asyncio
    async def test_config_flow_reauth_updates_existing_entry(self, config_flow):
        """Test that reauth flow updates existing entry rather than creating new."""
        mock_entry = Mock()
        mock_entry.data = {"token": {"access_token": "old"}, "timezone": "any"}
        mock_entry.title = "Saxo Portfolio"
        mock_entry.entry_id = "test_entry"

        config_flow._reauth_entry = mock_entry
        config_flow.hass.config_entries.async_update_entry = Mock()
        config_flow.hass.config_entries.async_reload = AsyncMock()

        mock_oauth_data = {
            "token": {
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_at": 9999999999,
                "token_type": "Bearer",
            },
        }

        result = await config_flow.async_oauth_create_entry(mock_oauth_data)

        # Should abort with reauth_successful
        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"

        # Should update existing entry with new token
        config_flow.hass.config_entries.async_update_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_config_flow_abort_conditions_missing_credentials(self, config_flow):
        """Test that config flow aborts with correct reason when no credentials."""
        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={},
        ):
            result = await config_flow.async_step_user()

        assert result["type"] == "abort"
        assert result["reason"] == "missing_credentials"

    def test_config_flow_options_support(self):
        """Test that config flow declares options flow support."""
        # Should have async_get_options_flow
        assert hasattr(SaxoPortfolioFlowHandler, "async_get_options_flow")

    def test_options_flow_handler_class(self):
        """Test that options flow handler is properly defined."""
        handler = SaxoOptionsFlowHandler()
        assert hasattr(handler, "async_step_init")
