"""Application Credentials platform for Saxo Portfolio integration."""

from __future__ import annotations

import logging
import time

import aiohttp
from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    SAXO_AUTH_BASE_URL,
    OAUTH_AUTHORIZE_ENDPOINT,
    OAUTH_TOKEN_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


class SaxoAuthImplementation(AuthImplementation):
    """Saxo-specific OAuth implementation.

    Saxo requires:
    - HTTP Basic Auth for token requests (not POST body params)
    - redirect_uri in refresh token requests
    """

    async def _async_refresh_token(self, token: dict) -> dict:
        """Refresh tokens with redirect_uri included."""
        new_token = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
                "redirect_uri": self.redirect_uri,
            }
        )
        return {**token, **new_token}

    async def _token_request(self, data: dict) -> dict:
        """Make a token request using HTTP Basic Auth."""
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=aiohttp.BasicAuth(self.client_id, self.client_secret),
        )

        if resp.status >= 400:
            error_response = (
                await resp.json() if resp.content_type == "application/json" else {}
            )
            _LOGGER.error(
                "Token request failed (%s): %s",
                error_response.get("error", "unknown"),
                error_response.get("error_description", "unknown"),
            )
        resp.raise_for_status()

        result = await resp.json()
        result["token_issued_at"] = time.time()
        return result


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> SaxoAuthImplementation:
    """Return a custom auth implementation for Saxo.

    This replaces async_get_authorization_server() and provides
    Saxo-specific token request handling (Basic Auth + redirect_uri).
    """
    authorize_url = f"{SAXO_AUTH_BASE_URL}{OAUTH_AUTHORIZE_ENDPOINT}"
    token_url = f"{SAXO_AUTH_BASE_URL}{OAUTH_TOKEN_ENDPOINT}"

    _LOGGER.debug(
        "Creating Saxo OAuth implementation - authorize_url: %s, token_url: %s",
        authorize_url,
        token_url,
    )

    return SaxoAuthImplementation(
        hass,
        auth_domain,
        credential,
        AuthorizationServer(
            authorize_url=authorize_url,
            token_url=token_url,
        ),
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
            "5. Paste them into the fields below\n"
            "Note: This integration uses production endpoints only"
        ),
    }
