"""Unit tests for config_flow.py to achieve 95%+ coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.saxo_portfolio.config_flow import (
    SaxoOptionsFlowHandler,
    SaxoPortfolioFlowHandler,
)
from custom_components.saxo_portfolio.const import (
    CONF_ENABLE_POSITION_SENSORS,
    CONF_TIMEZONE,
    DOMAIN,
)


@pytest.fixture
def mock_hass():
    hass = Mock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    hass.config_entries = Mock()
    hass.config_entries.async_entries = Mock(return_value=[])
    hass.config_entries.flow.async_progress_by_handler = Mock(return_value=[])
    return hass


@pytest.fixture
def flow(mock_hass):
    f = SaxoPortfolioFlowHandler()
    f.hass = mock_hass
    return f


class TestPickImplementation:
    @pytest.mark.asyncio
    async def test_with_user_input_delegates_to_parent(self, flow):
        """Line 64: user_input is not None branch."""
        with patch.object(
            SaxoPortfolioFlowHandler.__bases__[0],
            "async_step_pick_implementation",
            new_callable=AsyncMock,
            return_value={"type": "external"},
        ) as mock_parent:
            await flow.async_step_pick_implementation(
                user_input={"implementation": "test"}
            )
            mock_parent.assert_called_once()


class TestOAuthCreateEntryReauth:
    @pytest.mark.asyncio
    async def test_reauth_preserves_redirect_uri(self, flow):
        """Line 144: redirect_uri preservation in reauth."""
        mock_entry = Mock()
        mock_entry.data = {
            "token": {"access_token": "old"},
            "timezone": "Europe/Amsterdam",
        }
        mock_entry.title = "Saxo"
        mock_entry.entry_id = "e1"
        flow._reauth_entry = mock_entry
        flow.hass.config_entries.async_update_entry = Mock()
        flow.hass.config_entries.async_reload = AsyncMock()

        new_data = {
            "token": {"access_token": "new", "refresh_token": "r", "expires_at": 9e9},
            "redirect_uri": "https://example.com/callback",
        }
        result = await flow.async_oauth_create_entry(new_data)
        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"
        update_data = flow.hass.config_entries.async_update_entry.call_args[1]["data"]
        assert update_data["redirect_uri"] == "https://example.com/callback"


class TestOAuthCreateEntryErrors:
    @pytest.mark.asyncio
    async def test_auth_error(self, flow):
        """Lines 168-169: AuthenticationError → invalid_auth."""
        from custom_components.saxo_portfolio.api.saxo_client import AuthenticationError

        mock_client = AsyncMock()
        mock_client.get_client_details = AsyncMock(side_effect=AuthenticationError)
        with (
            patch(
                "custom_components.saxo_portfolio.config_flow.async_get_clientsession"
            ),
            patch(
                "custom_components.saxo_portfolio.config_flow.SaxoApiClient",
                return_value=mock_client,
            ),
        ):
            result = await flow.async_oauth_create_entry(
                {"token": {"access_token": "t", "expires_at": 9e9}}
            )
        assert result["reason"] == "invalid_auth"

    @pytest.mark.asyncio
    async def test_timeout_error(self, flow):
        """Lines 170-171: TimeoutError → cannot_connect."""
        mock_client = AsyncMock()
        mock_client.get_client_details = AsyncMock(side_effect=TimeoutError)
        with (
            patch(
                "custom_components.saxo_portfolio.config_flow.async_get_clientsession"
            ),
            patch(
                "custom_components.saxo_portfolio.config_flow.SaxoApiClient",
                return_value=mock_client,
            ),
        ):
            result = await flow.async_oauth_create_entry(
                {"token": {"access_token": "t", "expires_at": 9e9}}
            )
        assert result["reason"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_api_error(self, flow):
        """Lines 172-173: APIError → api_validation_failed."""
        from custom_components.saxo_portfolio.api.saxo_client import APIError

        mock_client = AsyncMock()
        mock_client.get_client_details = AsyncMock(side_effect=APIError)
        with (
            patch(
                "custom_components.saxo_portfolio.config_flow.async_get_clientsession"
            ),
            patch(
                "custom_components.saxo_portfolio.config_flow.SaxoApiClient",
                return_value=mock_client,
            ),
        ):
            result = await flow.async_oauth_create_entry(
                {"token": {"access_token": "t", "expires_at": 9e9}}
            )
        assert result["reason"] == "api_validation_failed"

    @pytest.mark.asyncio
    async def test_missing_client_key(self, flow):
        """Line 176: missing ClientKey → api_validation_failed."""
        mock_client = AsyncMock()
        mock_client.get_client_details = AsyncMock(return_value={"Name": "Test"})
        with (
            patch(
                "custom_components.saxo_portfolio.config_flow.async_get_clientsession"
            ),
            patch(
                "custom_components.saxo_portfolio.config_flow.SaxoApiClient",
                return_value=mock_client,
            ),
        ):
            result = await flow.async_oauth_create_entry(
                {"token": {"access_token": "t", "expires_at": 9e9}}
            )
        assert result["reason"] == "api_validation_failed"

    @pytest.mark.asyncio
    async def test_none_client_details(self, flow):
        """Line 175: None client_details → api_validation_failed."""
        mock_client = AsyncMock()
        mock_client.get_client_details = AsyncMock(return_value=None)
        with (
            patch(
                "custom_components.saxo_portfolio.config_flow.async_get_clientsession"
            ),
            patch(
                "custom_components.saxo_portfolio.config_flow.SaxoApiClient",
                return_value=mock_client,
            ),
        ):
            result = await flow.async_oauth_create_entry(
                {"token": {"access_token": "t", "expires_at": 9e9}}
            )
        assert result["reason"] == "api_validation_failed"


class TestTimezoneStepRedirectUri:
    @pytest.mark.asyncio
    async def test_stores_redirect_uri(self, flow):
        """Lines 213-221: redirect_uri from implementation."""
        flow._oauth_data = {"token": {"access_token": "t"}}
        mock_impl = Mock()
        mock_impl.redirect_uri = "https://example.com/redirect"
        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={"test": mock_impl},
        ):
            result = await flow.async_step_timezone({CONF_TIMEZONE: "America/New_York"})
        assert result["type"] == "create_entry"
        assert result["data"]["redirect_uri"] == "https://example.com/redirect"

    @pytest.mark.asyncio
    async def test_no_redirect_uri_attr(self, flow):
        """Lines 221-224: impl without redirect_uri."""
        flow._oauth_data = {"token": {"access_token": "t"}}
        mock_impl = Mock(spec=[])  # No redirect_uri attribute
        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={"test": mock_impl},
        ):
            result = await flow.async_step_timezone({CONF_TIMEZONE: "America/New_York"})
        assert result["type"] == "create_entry"
        assert "redirect_uri" not in result["data"]

    @pytest.mark.asyncio
    async def test_no_implementations(self, flow):
        """Lines 225-228: no implementations found."""
        flow._oauth_data = {"token": {"access_token": "t"}}
        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            return_value={},
        ):
            result = await flow.async_step_timezone({CONF_TIMEZONE: "any"})
        assert result["type"] == "create_entry"

    @pytest.mark.asyncio
    async def test_exception_getting_redirect_uri(self, flow):
        """Lines 228-232: exception during redirect_uri retrieval."""
        flow._oauth_data = {"token": {"access_token": "t"}}
        with patch(
            "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
            side_effect=RuntimeError("fail"),
        ):
            result = await flow.async_step_timezone({CONF_TIMEZONE: "any"})
        assert result["type"] == "create_entry"


class TestReauthFlow:
    @pytest.mark.asyncio
    async def test_reauth_with_entry_id(self, flow):
        """Lines 278-284: reauth with entry_id in context."""
        mock_entry = Mock()
        mock_entry.title = "Saxo"
        flow.context = {"entry_id": "test_entry"}
        flow.hass.config_entries.async_get_entry = Mock(return_value=mock_entry)
        result = await flow.async_step_reauth({})
        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm"
        assert flow._reauth_entry == mock_entry

    @pytest.mark.asyncio
    async def test_reauth_without_entry_id(self, flow):
        """Lines 286-287: reauth without entry_id in context."""
        flow.context = {}
        result = await flow.async_step_reauth({})
        assert result["type"] == "form"
        assert flow._reauth_entry is None


class TestReconfigureFlow:
    @pytest.mark.asyncio
    async def test_reconfigure_submit(self, flow):
        """Line 325: user_input is not None starts OAuth."""
        mock_entry = Mock()
        mock_entry.title = "Saxo"
        mock_entry.entry_id = "e1"
        with (
            patch.object(flow, "_get_reconfigure_entry", return_value=mock_entry),
            patch(
                "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
                return_value={},
            ),
        ):
            result = await flow.async_step_reconfigure(user_input={})
        assert result["type"] == "abort"
        assert result["reason"] == "missing_credentials"


class TestOptionsFlow:
    @pytest.fixture
    def options_flow(self, mock_hass):
        handler = SaxoOptionsFlowHandler()
        handler.hass = mock_hass
        handler.handler = "test_entry_id"
        mock_entry = Mock()
        mock_entry.data = {
            CONF_TIMEZONE: "America/New_York",
            CONF_ENABLE_POSITION_SENSORS: False,
        }
        mock_entry.options = {}
        mock_hass.config_entries.async_get_entry = Mock(return_value=mock_entry)
        mock_hass.config_entries.async_update_entry = Mock()
        mock_hass.async_create_task = Mock()
        mock_hass.config_entries.async_reload = AsyncMock()
        return handler

    @pytest.mark.asyncio
    async def test_init_shows_form(self, options_flow):
        """Lines 391-401: show form with current values."""
        result = await options_flow.async_step_init()
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_init_saves_without_reload(self, options_flow):
        """Lines 358-389: save options, no reload needed."""
        result = await options_flow.async_step_init(
            {CONF_TIMEZONE: "Europe/London", CONF_ENABLE_POSITION_SENSORS: False}
        )
        assert result["type"] == "create_entry"
        options_flow.hass.config_entries.async_update_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_saves_with_reload(self, options_flow):
        """Lines 367-388: position sensors toggled triggers reload."""
        result = await options_flow.async_step_init(
            {CONF_TIMEZONE: "Europe/London", CONF_ENABLE_POSITION_SENSORS: True}
        )
        assert result["type"] == "create_entry"
        options_flow.hass.async_create_task.assert_called_once()

    def test_config_entry_property(self, options_flow):
        """Lines 350-352: config_entry property."""
        entry = options_flow.config_entry
        assert entry is not None

    def test_async_get_options_flow(self):
        """Line 341: static method returns handler."""
        handler = SaxoPortfolioFlowHandler.async_get_options_flow(Mock())
        assert isinstance(handler, SaxoOptionsFlowHandler)
