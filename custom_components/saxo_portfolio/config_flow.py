"""Config flow for Saxo Portfolio integration."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import aiohttp
import voluptuous as vol
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_ENVIRONMENT,
    DOMAIN,
    ENVIRONMENTS,
    ENV_SIMULATION,
    OAUTH_AUTHORIZE_ENDPOINT,
    OAUTH_TOKEN_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


class SaxoPortfolioFlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Saxo Portfolio OAuth2 authentication."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._oauth_data: Optional[Dict[str, Any]] = None
        self._oauth_state: Optional[str] = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> Dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {"scope": "openapi"}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_pick_implementation(user_input)

    async def async_step_auth(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the OAuth authorization step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                # Exchange authorization code for access token
                token_data = await self._exchange_code_for_token(
                    user_input["code"]
                )
                
                # Store OAuth data for entry creation
                self._oauth_data = {
                    "token": token_data,
                    "auth_implementation": DOMAIN,
                }
                
                return self.async_create_entry(
                    title="Saxo Portfolio",
                    data=self._oauth_data,
                )
                
            except Exception as e:
                _LOGGER.error("Error during OAuth authorization: %s", str(e))
                errors["base"] = "auth_error"

        # Show authorization form
        return self.async_show_form(
            step_id="auth",
            errors=errors,
        )

    async def async_oauth_create_entry(self, data: Dict[str, Any]) -> FlowResult:
        """Create an entry for the flow."""
        return self.async_create_entry(
            title="Saxo Portfolio",
            data=data,
        )

    async def _exchange_code_for_token(self, authorization_code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token.
        
        Args:
            authorization_code: OAuth authorization code
            
        Returns:
            Token data dictionary
            
        Raises:
            Exception: If token exchange fails
        """
        # Get environment configuration (default to simulation)
        environment = ENV_SIMULATION
        auth_base_url = ENVIRONMENTS[environment]["auth_base_url"]
        token_url = f"{auth_base_url}{OAUTH_TOKEN_ENDPOINT}"
        
        # Get application credentials
        # In a real implementation, these would come from application credentials
        # For now, use placeholder values that tests can override
        app_key = "test_app_key"
        app_secret = "test_app_secret"
        
        # Prepare token request
        token_data = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": "https://my.home-assistant.io/redirect/oauth",
        }
        
        # Use Home Assistant's session
        session = async_get_clientsession(self.hass)
        
        try:
            auth = aiohttp.BasicAuth(app_key, app_secret)
            async with session.post(token_url, data=token_data, auth=auth) as response:
                if response.status == 200:
                    token_response = await response.json()
                    
                    # Add expiry timestamp
                    from datetime import datetime, timedelta
                    expires_in = token_response.get("expires_in", 1200)
                    expires_at = (datetime.now() + timedelta(seconds=expires_in)).timestamp()
                    token_response["expires_at"] = expires_at
                    
                    return token_response
                else:
                    error_text = await response.text()
                    raise Exception(f"Token exchange failed: {error_text}")
                    
        except aiohttp.ClientError as e:
            raise Exception(f"Network error during token exchange: {str(e)}")

    async def async_step_oauth_callback(self, user_input: Dict[str, Any]) -> FlowResult:
        """Handle OAuth callback."""
        # Validate state parameter for security
        if hasattr(self, '_oauth_state') and self._oauth_state:
            received_state = user_input.get("state")
            if received_state != self._oauth_state:
                raise Exception("OAuth state parameter mismatch")
        
        # Extract authorization code
        auth_code = user_input.get("code")
        if not auth_code:
            raise Exception("No authorization code received")
        
        # Exchange code for token
        return await self.async_step_auth({"code": auth_code})

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> FlowResult:
        """Handle reauthorization request."""
        return await self.async_step_user()

    async def _refresh_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh OAuth access token.
        
        Args:
            token_data: Current token data with refresh_token
            
        Returns:
            New token data
            
        Raises:
            Exception: If token refresh fails
        """
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise Exception("No refresh token available")
        
        # Get environment configuration
        environment = ENV_SIMULATION
        auth_base_url = ENVIRONMENTS[environment]["auth_base_url"] 
        token_url = f"{auth_base_url}{OAUTH_TOKEN_ENDPOINT}"
        
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        
        # Application credentials
        app_key = "test_app_key"
        app_secret = "test_app_secret"
        
        session = async_get_clientsession(self.hass)
        
        try:
            auth = aiohttp.BasicAuth(app_key, app_secret)
            async with session.post(token_url, data=refresh_data, auth=auth) as response:
                if response.status == 200:
                    new_token_data = await response.json()
                    
                    # Add expiry timestamp
                    from datetime import datetime, timedelta
                    expires_in = new_token_data.get("expires_in", 1200)
                    expires_at = (datetime.now() + timedelta(seconds=expires_in)).timestamp()
                    new_token_data["expires_at"] = expires_at
                    
                    return new_token_data
                else:
                    error_text = await response.text()
                    raise Exception(f"Token refresh failed: {error_text}")
                    
        except aiohttp.ClientError as e:
            raise Exception(f"Network error during token refresh: {str(e)}")


class SaxoPortfolioOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Saxo Portfolio options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
        )