"""Config flow for Saxo Portfolio integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant import config_entries

from .const import (
    CONF_TIMEZONE,
    DEFAULT_TIMEZONE,
    DOMAIN,
    OAUTH_AUTHORIZE_ENDPOINT,
    OAUTH_TOKEN_ENDPOINT,
    SAXO_AUTH_BASE_URL,
    TIMEZONE_OPTIONS,
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
        self._reauth_entry: config_entries.ConfigEntry | None = None

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
        # Add token_issued_at timestamp if not present
        # This helps accurately track refresh token expiry
        from datetime import datetime

        if "token" in data and "token_issued_at" not in data["token"]:
            data["token"]["token_issued_at"] = datetime.now().timestamp()

        # Check if this is a reauth flow
        if self._reauth_entry:
            # Update existing entry with new token
            _LOGGER.info(
                "Reauth successful, updating config entry: %s",
                self._reauth_entry.title,
            )

            # Preserve existing configuration (timezone, etc.) and update only the token
            new_data = {**self._reauth_entry.data}
            new_data["token"] = data["token"]

            # Preserve redirect_uri if available in new OAuth data
            if "redirect_uri" in data:
                new_data["redirect_uri"] = data["redirect_uri"]

            self.hass.config_entries.async_update_entry(
                self._reauth_entry,
                data=new_data,
            )

            # Reload the integration to use the new token
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)

            return self.async_abort(reason="reauth_successful")

        # Not a reauth flow - store OAuth data and proceed to timezone configuration
        self._oauth_data = data
        return await self.async_step_timezone()

    async def async_step_timezone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure timezone for market hours detection."""
        errors = {}

        if user_input is not None:
            # Combine OAuth data with timezone configuration
            data = {**self._oauth_data}
            data[CONF_TIMEZONE] = user_input[CONF_TIMEZONE]

            # Store redirect_uri from OAuth implementation for token refresh
            # This is retrieved dynamically by Home Assistant based on the configuration
            try:
                from homeassistant.helpers.config_entry_oauth2_flow import (
                    async_get_implementations,
                )

                implementations = await async_get_implementations(self.hass, DOMAIN)
                if implementations:
                    # Get the first (and typically only) implementation
                    implementation = next(iter(implementations.values()))
                    if hasattr(implementation, "redirect_uri"):
                        data["redirect_uri"] = implementation.redirect_uri
                        _LOGGER.debug(
                            "Stored redirect_uri from OAuth implementation: %s",
                            implementation.redirect_uri,
                        )
                    else:
                        _LOGGER.debug(
                            "OAuth implementation has no redirect_uri property, will retrieve dynamically during refresh"
                        )
                else:
                    _LOGGER.warning(
                        "No OAuth implementations found during setup, redirect_uri will be retrieved dynamically during refresh"
                    )
            except Exception as e:
                _LOGGER.warning(
                    "Could not retrieve redirect_uri during setup: %s, will retrieve dynamically during refresh",
                    type(e).__name__,
                )

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

            _LOGGER.debug("OAuth data structure with timezone: %s", debug_data)

            # Create entry with simple title - ClientId will be determined from API
            title = "Saxo Portfolio"

            _LOGGER.debug(
                "Creating config entry with title: %s, timezone: %s",
                title,
                data[CONF_TIMEZONE],
            )

            return self.async_create_entry(
                title=title,
                data=data,
            )

        # Show timezone selection form
        return self.async_show_form(
            step_id="timezone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TIMEZONE, default=DEFAULT_TIMEZONE): vol.In(
                        TIMEZONE_OPTIONS
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauthorization request."""
        # Get the config entry that triggered reauth
        entry_id = self.context.get("entry_id")
        if entry_id:
            self._reauth_entry = self.hass.config_entries.async_get_entry(entry_id)
            _LOGGER.info(
                "Starting reauth flow for config entry: %s",
                self._reauth_entry.title if self._reauth_entry else "unknown",
            )
        else:
            _LOGGER.warning("Reauth triggered but no entry_id in context")

        # Start the OAuth flow again
        return await self.async_step_pick_implementation()

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return SaxoOptionsFlowHandler()


class SaxoOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Saxo Portfolio options."""

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return config entry."""
        return self.hass.config_entries.async_get_entry(self.handler)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update the config entry with new timezone
            new_data = {**self.config_entry.data}
            new_data[CONF_TIMEZONE] = user_input[CONF_TIMEZONE]
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        current_timezone = self.config_entry.data.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TIMEZONE, default=current_timezone): vol.In(
                        TIMEZONE_OPTIONS
                    ),
                }
            ),
        )
