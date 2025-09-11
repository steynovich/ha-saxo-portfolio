"""Config flow for Saxo Portfolio integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .const import (
    DOMAIN,
    SAXO_AUTH_BASE_URL,
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
        self._user_input: dict[str, Any] = {}
        self._oauth_data: dict[str, Any] = {}

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {"scope": "openapi"}

    async def async_step_pick_implementation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle picking the OAuth implementation with environment-specific URLs."""
        if user_input is not None:
            # Store the implementation selection and continue with OAuth
            return await super().async_step_pick_implementation(user_input)

        # Check if application credentials are configured
        from homeassistant.helpers.config_entry_oauth2_flow import (
            async_get_implementations,
        )

        implementations = await async_get_implementations(self.hass, DOMAIN)

        _LOGGER.debug(
            "Pick implementation step - found implementations: %d",
            len(implementations) if implementations else 0,
        )

        if implementations:
            for impl_id, impl in implementations.items():
                _LOGGER.debug(
                    "Available OAuth implementation - ID: %s, domain: %s, name: %s",
                    impl_id,
                    getattr(impl, "domain", "unknown"),
                    getattr(impl, "name", "unknown"),
                )

        if not implementations:
            # No application credentials configured - abort with instructions
            _LOGGER.debug(
                "No OAuth implementations found for domain: %s, aborting with credentials setup instructions",
                DOMAIN,
            )

            return self.async_abort(
                reason="missing_credentials",
                description_placeholders={
                    "auth_base_url": SAXO_AUTH_BASE_URL,
                    "authorize_url": f"{SAXO_AUTH_BASE_URL}{OAUTH_AUTHORIZE_ENDPOINT}",
                    "token_url": f"{SAXO_AUTH_BASE_URL}{OAUTH_TOKEN_ENDPOINT}",
                    "setup_url": "/config/application_credentials",
                    "domain": DOMAIN,
                },
            )

        # Continue with standard OAuth implementation selection
        _LOGGER.debug(
            "Proceeding with OAuth implementation selection using parent class"
        )
        return await super().async_step_pick_implementation(user_input)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_pick_implementation()

    # Remove custom auth step - let parent class handle OAuth2 flow

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """Create an entry for the flow."""
        # Debug OAuth data structure (without sensitive info)
        debug_data = {k: v for k, v in data.items() if k != "token"}
        if "token" in data:
            token_info = data["token"]
            debug_token = {
                "has_access_token": bool(token_info.get("access_token")),
                "has_refresh_token": bool(token_info.get("refresh_token")),
                "token_type": token_info.get("token_type"),
                "expires_at": token_info.get("expires_at"),
            }
            debug_data["token_info"] = debug_token

        _LOGGER.debug("OAuth data structure: %s", debug_data)

        # Create entry with simple title - ClientId will be determined from API
        title = "Saxo Portfolio"

        _LOGGER.debug("Creating config entry with title: %s", title)

        return self.async_create_entry(
            title=title,
            data=data,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauthorization request."""
        return await self.async_step_user()
