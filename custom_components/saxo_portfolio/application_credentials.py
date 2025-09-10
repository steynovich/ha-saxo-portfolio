"""Application Credentials platform for Saxo Portfolio integration."""

from __future__ import annotations

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import (
    ENVIRONMENTS,
    ENV_SIMULATION,
    OAUTH_AUTHORIZE_ENDPOINT,
    OAUTH_TOKEN_ENDPOINT,
)


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return authorization server for OAuth flow.
    
    This provides the OAuth endpoints for Home Assistant's
    application credentials system.
    """
    # Default to simulation environment for setup
    # Users can switch to production in the config flow
    environment = ENV_SIMULATION
    auth_base_url = ENVIRONMENTS[environment]["auth_base_url"]
    
    return AuthorizationServer(
        authorize_url=f"{auth_base_url}{OAUTH_AUTHORIZE_ENDPOINT}",
        token_url=f"{auth_base_url}{OAUTH_TOKEN_ENDPOINT}",
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return description placeholders for the credentials dialog.
    
    These placeholders are used in the Home Assistant UI to guide users
    through the application credentials setup process.
    """
    return {
        "oauth_url": "https://www.developer.saxo/openapi/appmanagement",
        "redirect_uri": "https://my.home-assistant.io/redirect/oauth",
        "more_info_url": "https://www.developer.saxo/openapi/learn/security",
        "setup_instructions": (
            "1. Go to the Saxo Developer Portal\n"
            "2. Create a new application\n"  
            "3. Set the redirect URI to the provided URL\n"
            "4. Copy the App Key and App Secret\n"
            "5. Paste them into the fields below"
        ),
    }