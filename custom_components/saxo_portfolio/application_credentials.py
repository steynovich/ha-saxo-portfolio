"""Application Credentials platform for Saxo Portfolio integration."""

from __future__ import annotations

import asyncio
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
    TOKEN_REFRESH_TIMEOUT,
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
        """Make a token request using HTTP Basic Auth with timeout and retry."""
        session = async_get_clientsession(self.hass)
        # Backoff schedule: 1s, 2s, 4s, 8s, 16s (~31s total) - long enough to
        # absorb a brief Saxo hiccup while still failing fast on bad credentials
        # (the 400/401 branch below short-circuits without retrying).
        max_attempts = 5
        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                async with asyncio.timeout(TOKEN_REFRESH_TIMEOUT):
                    resp = await session.post(
                        self.token_url,
                        data=data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        auth=aiohttp.BasicAuth(self.client_id, self.client_secret),
                    )

                if resp.status in (400, 401):
                    # Auth errors — no retry, credentials are bad
                    error_response = (
                        await resp.json()
                        if resp.content_type == "application/json"
                        else {}
                    )
                    _LOGGER.error(
                        "Token request failed (%s): %s",
                        error_response.get("error", "unknown"),
                        error_response.get("error_description", "unknown"),
                    )
                    resp.raise_for_status()

                if resp.status >= 500:
                    # Server error — retry
                    _LOGGER.warning(
                        "Token request server error (HTTP %s), attempt %d/%d",
                        resp.status,
                        attempt,
                        max_attempts,
                    )
                    last_exception = aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(2 ** (attempt - 1))
                        continue
                    resp.raise_for_status()

                if resp.status >= 400:
                    # Other 4xx — log and raise immediately
                    error_response = (
                        await resp.json()
                        if resp.content_type == "application/json"
                        else {}
                    )
                    _LOGGER.error(
                        "Token request failed (%s): %s",
                        error_response.get("error", "unknown"),
                        error_response.get("error_description", "unknown"),
                    )
                    resp.raise_for_status()

                result = await resp.json()
                result["token_issued_at"] = time.time()
                if attempt > 1:
                    _LOGGER.info(
                        "Token refresh succeeded on attempt %d/%d",
                        attempt,
                        max_attempts,
                    )
                return result

            except TimeoutError:
                _LOGGER.warning(
                    "Token refresh timed out after %ds, attempt %d/%d",
                    TOKEN_REFRESH_TIMEOUT,
                    attempt,
                    max_attempts,
                )
                last_exception = TimeoutError(
                    f"Token refresh timed out after {TOKEN_REFRESH_TIMEOUT}s"
                )
                if attempt < max_attempts:
                    await asyncio.sleep(2 ** (attempt - 1))

            except aiohttp.ClientResponseError as err:
                if err.status in (400, 401):
                    # Auth errors that escaped the status check — don't retry
                    raise
                _LOGGER.warning(
                    "Token refresh network error (%s), attempt %d/%d",
                    type(err).__name__,
                    attempt,
                    max_attempts,
                )
                last_exception = err
                if attempt < max_attempts:
                    await asyncio.sleep(2 ** (attempt - 1))

            except aiohttp.ClientError as err:
                _LOGGER.warning(
                    "Token refresh network error (%s), attempt %d/%d",
                    type(err).__name__,
                    attempt,
                    max_attempts,
                )
                last_exception = err
                if attempt < max_attempts:
                    await asyncio.sleep(2 ** (attempt - 1))

        # All attempts exhausted
        raise last_exception  # type: ignore[misc]


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
