"""Integration tests for OAuth authentication flow.

These tests validate the OAuth setup and authentication process,
including config entry creation, reauth, and token handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.saxo_portfolio.config_flow import SaxoPortfolioFlowHandler
from custom_components.saxo_portfolio.const import CONF_TIMEZONE, DOMAIN


@pytest.mark.integration
class TestOAuthAuthenticationFlow:
    """Integration tests for OAuth authentication flow."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
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

    @pytest.mark.asyncio
    async def test_complete_oauth_setup_flow_no_credentials(self, config_flow):
        """Test that user step aborts when no OAuth credentials are configured."""
        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={},
        ):
            result = await config_flow.async_step_user()

        assert result["type"] == "abort"
        assert result["reason"] == "missing_credentials"
        assert "developer_portal_url" in result["description_placeholders"]

    @pytest.mark.asyncio
    async def test_oauth_callback_routes_to_timezone(self, config_flow):
        """Test OAuth callback routes to timezone selection for new entries."""
        oauth_data = {
            "token": {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
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
            patch.object(
                config_flow, "async_set_unique_id", new_callable=AsyncMock
            ),
            patch.object(config_flow, "_abort_if_unique_id_configured"),
        ):
            result = await config_flow.async_oauth_create_entry(oauth_data)

        # New entries route to timezone selection
        assert result["type"] == "form"
        assert result["step_id"] == "timezone"

    @pytest.mark.asyncio
    async def test_timezone_step_creates_entry(self, config_flow):
        """Test that timezone step creates config entry with all data."""
        # Simulate OAuth data already stored
        config_flow._oauth_data = {
            "token": {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
                "expires_at": 9999999999,
                "token_type": "Bearer",
            },
        }

        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={},
        ):
            result = await config_flow.async_step_timezone(
                {CONF_TIMEZONE: "America/New_York"}
            )

        assert result["type"] == "create_entry"
        assert result["title"] == "Saxo Portfolio"
        assert result["data"][CONF_TIMEZONE] == "America/New_York"
        assert "token" in result["data"]

    @pytest.mark.asyncio
    async def test_config_entry_creation_includes_token(self, config_flow):
        """Test config entry data includes proper token structure."""
        config_flow._oauth_data = {
            "token": {
                "access_token": "saxo_token_abc",
                "refresh_token": "saxo_refresh_xyz",
                "expires_at": 9999999999,
                "token_type": "Bearer",
            },
        }

        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={},
        ):
            result = await config_flow.async_step_timezone({CONF_TIMEZONE: "any"})

        entry_data = result["data"]
        assert entry_data["token"]["access_token"] == "saxo_token_abc"
        assert entry_data["token"]["refresh_token"] == "saxo_refresh_xyz"
        assert entry_data["token"]["token_type"] == "Bearer"

    @pytest.mark.asyncio
    async def test_reauth_flow_preserves_settings(self, config_flow):
        """Test reauth preserves existing timezone and settings."""
        mock_entry = Mock(spec=ConfigEntry)
        mock_entry.data = {
            "token": {"access_token": "old"},
            "timezone": "Europe/Amsterdam",
            "redirect_uri": "https://example.com/redirect",
        }
        mock_entry.title = "Saxo Portfolio"
        mock_entry.entry_id = "existing_entry"

        config_flow._reauth_entry = mock_entry
        config_flow.hass.config_entries.async_update_entry = Mock()
        config_flow.hass.config_entries.async_reload = AsyncMock()

        new_oauth_data = {
            "token": {
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_at": 9999999999,
                "token_type": "Bearer",
            },
        }

        result = await config_flow.async_oauth_create_entry(new_oauth_data)

        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"

        # Check that existing settings were preserved
        update_call = config_flow.hass.config_entries.async_update_entry.call_args
        new_data = update_call[1]["data"]
        assert new_data["timezone"] == "Europe/Amsterdam"
        assert new_data["token"]["access_token"] == "new_token"

    @pytest.mark.asyncio
    async def test_reauth_confirm_step_shows_form(self, config_flow):
        """Test reauth confirm step shows confirmation form."""
        mock_entry = Mock()
        mock_entry.title = "Saxo Portfolio"
        config_flow._reauth_entry = mock_entry

        result = await config_flow.async_step_reauth_confirm()

        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm"

    @pytest.mark.asyncio
    async def test_reauth_confirm_submit_starts_oauth(self, config_flow):
        """Test reauth confirm submission starts OAuth flow."""
        config_flow._reauth_entry = Mock(title="Saxo Portfolio")

        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={},
        ):
            result = await config_flow.async_step_reauth_confirm(user_input={})

        # With no implementations, aborts with missing_credentials
        assert result["type"] == "abort"
        assert result["reason"] == "missing_credentials"

    @pytest.mark.asyncio
    async def test_token_issued_at_added_to_entry(self, config_flow):
        """Test that token_issued_at is added when creating entry."""
        oauth_data = {
            "token": {
                "access_token": "test",
                "refresh_token": "test",
                "expires_at": 9999999999,
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
            patch.object(
                config_flow, "async_set_unique_id", new_callable=AsyncMock
            ),
            patch.object(config_flow, "_abort_if_unique_id_configured"),
        ):
            await config_flow.async_oauth_create_entry(oauth_data)

        # token_issued_at should be added
        assert "token_issued_at" in config_flow._oauth_data["token"]
        assert isinstance(config_flow._oauth_data["token"]["token_issued_at"], float)

    @pytest.mark.asyncio
    async def test_reconfigure_step_shows_form(self, config_flow):
        """Test reconfigure step shows confirmation form."""
        mock_entry = Mock()
        mock_entry.title = "Saxo Portfolio"
        mock_entry.entry_id = "test_entry"

        with patch.object(
            config_flow, "_get_reconfigure_entry", return_value=mock_entry
        ):
            result = await config_flow.async_step_reconfigure()

        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"

    @pytest.mark.asyncio
    async def test_application_credentials_integration(self, mock_hass):
        """Test integration with HA application credentials framework."""
        from custom_components.saxo_portfolio.application_credentials import (
            SaxoAuthImplementation,
            async_get_auth_implementation,
        )
        from homeassistant.components.application_credentials import ClientCredential

        credential = ClientCredential("test_key", "test_secret")
        impl = await async_get_auth_implementation(
            mock_hass, DOMAIN, credential
        )

        assert isinstance(impl, SaxoAuthImplementation)
