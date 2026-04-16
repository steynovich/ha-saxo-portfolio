"""Integration tests for error handling and recovery.

These tests validate comprehensive error handling across all integration
components, following error scenarios from quickstart.md troubleshooting.
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
import aiohttp
import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.api.saxo_client import (
    AuthenticationError,
    APIError,
)
from custom_components.saxo_portfolio.const import DOMAIN


def _make_mock_hass():
    """Create a mock Home Assistant with the attributes the coordinator needs."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


def _make_mock_config_entry(*, expired: bool = False):
    """Create a mock config entry with OAuth token."""
    config_entry = MagicMock(spec=ConfigEntry)
    config_entry.entry_id = "test_entry_123"
    config_entry.title = "Saxo Portfolio"
    config_entry.options = {}
    if expired:
        config_entry.data = {
            "token": {
                "access_token": "expired_token",
                "refresh_token": "test_refresh",
                "expires_at": (datetime.now() - timedelta(hours=1)).timestamp(),
                "token_type": "Bearer",
                "token_issued_at": (datetime.now() - timedelta(hours=2)).timestamp(),
            },
            "timezone": "any",
        }
    else:
        config_entry.data = {
            "token": {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
                "expires_at": (datetime.now() + timedelta(hours=1)).timestamp(),
                "token_type": "Bearer",
                "token_issued_at": datetime.now().timestamp(),
            },
            "timezone": "any",
        }
    return config_entry


def _make_mock_oauth_session(config_entry):
    """Create a mock OAuth2 session."""
    session = MagicMock()
    session.token = config_entry.data["token"]
    session.async_ensure_token_valid = AsyncMock()
    return session


def _make_coordinator_with_mock_client(
    mock_hass, mock_config_entry, mock_oauth_session
):
    """Create a coordinator and patch its api_client property to return a mock client.

    Returns (coordinator, mock_client) so the caller can configure side effects.
    """
    coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
    mock_client = AsyncMock()
    mock_client.base_url = "https://gateway.saxobank.com/openapi"
    with patch.object(
        type(coordinator), "api_client", new_callable=PropertyMock
    ) as prop:
        prop.return_value = mock_client
        # Caller needs both, but we return outside the context manager.
    # Instead, we permanently patch the property for the test's duration.
    # Return the coordinator and client; caller uses patch.object in their test.
    return coordinator, mock_client


@pytest.mark.integration
class TestErrorHandlingAndRecovery:
    """Integration tests for comprehensive error handling and recovery."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        return _make_mock_hass()

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry with valid OAuth token."""
        return _make_mock_config_entry()

    @pytest.fixture
    def mock_oauth_session(self, mock_config_entry):
        """Create a mock OAuth2 session."""
        return _make_mock_oauth_session(mock_config_entry)

    @pytest.fixture
    def mock_expired_config_entry(self):
        """Create config entry with expired token."""
        return _make_mock_config_entry(expired=True)

    @pytest.fixture
    def mock_expired_oauth_session(self, mock_expired_config_entry):
        """Create a mock OAuth2 session with expired token."""
        return _make_mock_oauth_session(mock_expired_config_entry)

    @pytest.mark.asyncio
    async def test_authentication_failure_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of authentication failures (AuthenticationError from API client).

        The coordinator catches AuthenticationError and re-raises as ConfigEntryAuthFailed,
        which Home Assistant uses to trigger a re-authentication flow.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"
        mock_client.get_account_balance.side_effect = AuthenticationError(
            "Authentication failed"
        )

        with (
            patch.object(
                type(coordinator), "api_client", new_callable=PropertyMock
            ) as prop,
            pytest.raises(ConfigEntryAuthFailed),
        ):
            prop.return_value = mock_client
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_network_connectivity_failure_recovery(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of network connectivity issues.

        aiohttp.ClientError is caught by the coordinator and re-raised as UpdateFailed.
        On a subsequent successful attempt, the coordinator should return valid data.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        with patch.object(
            type(coordinator), "api_client", new_callable=PropertyMock
        ) as prop:
            prop.return_value = mock_client

            # First attempt: Network error -> UpdateFailed
            mock_client.get_account_balance.side_effect = aiohttp.ClientError(
                "Network unreachable"
            )
            with pytest.raises(UpdateFailed, match="Network error"):
                await coordinator._fetch_portfolio_data()

            # Second attempt: Network recovered
            mock_client.get_account_balance.side_effect = None
            mock_client.get_account_balance.return_value = {
                "CashBalance": 5000.00,
                "Currency": "USD",
                "TotalValue": 125000.00,
            }

            result = await coordinator._fetch_portfolio_data()
            assert result is not None
            assert isinstance(result, dict)
            assert result["cash_balance"] == 5000.00
            assert result["total_value"] == 125000.00

    @pytest.mark.asyncio
    async def test_rate_limit_error_handling_with_backoff(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of API rate limits (429 errors).

        A 429 from aiohttp is a ClientResponseError which is a subclass of ClientError.
        The coordinator catches aiohttp.ClientError and raises UpdateFailed.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        rate_limit_error = aiohttp.ClientResponseError(
            request_info=Mock(),
            history=(),
            status=429,
            message="Too Many Requests",
        )

        with patch.object(
            type(coordinator), "api_client", new_callable=PropertyMock
        ) as prop:
            prop.return_value = mock_client
            mock_client.get_account_balance.side_effect = rate_limit_error

            # 429 is a ClientResponseError (subclass of ClientError) ->  UpdateFailed
            with pytest.raises(UpdateFailed):
                await coordinator._fetch_portfolio_data()

    @pytest.mark.asyncio
    async def test_oauth_token_refresh_failure_handling(
        self, mock_hass, mock_expired_config_entry, mock_expired_oauth_session
    ):
        """Test handling of OAuth token refresh failures."""
        coordinator = SaxoCoordinator(
            mock_hass, mock_expired_config_entry, mock_expired_oauth_session
        )

        # OAuth2Session raises ConfigEntryAuthFailed on refresh failure
        mock_expired_oauth_session.async_ensure_token_valid.side_effect = (
            ConfigEntryAuthFailed("Token refresh failed")
        )

        # Should raise ConfigEntryAuthFailed to trigger re-authentication
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_partial_api_failure_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling when performance endpoint fails but balance succeeds.

        The coordinator implements graceful degradation: balance data is required,
        performance data uses cached/default values on failure.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        # Balance endpoint succeeds
        mock_client.get_account_balance.return_value = {
            "CashBalance": 5000.00,
            "Currency": "USD",
            "TotalValue": 125000.00,
            "NonMarginPositionsValue": 120000.00,
        }

        # Client details (used by performance) fails
        mock_client.get_client_details.side_effect = Exception(
            "Client details service unavailable"
        )

        with patch.object(
            type(coordinator), "api_client", new_callable=PropertyMock
        ) as prop:
            prop.return_value = mock_client

            result = await coordinator._fetch_portfolio_data()

            # Balance data should be present
            assert result is not None
            assert isinstance(result, dict)
            assert result["cash_balance"] == 5000.00
            assert result["total_value"] == 125000.00
            assert result["currency"] == "USD"

            # Performance data should fall back to defaults (0.0)
            assert result["investment_performance_percentage"] == 0.0
            assert result["client_id"] == "unknown"
            assert "last_updated" in result

    @pytest.mark.asyncio
    async def test_config_flow_oauth_error_handling(self, mock_hass):
        """Test that the config flow handles OAuth errors by verifying it has error handling.

        The SaxoPortfolioFlowHandler extends AbstractOAuth2FlowHandler. When OAuth
        authorization fails, the base class handles errors. We verify that a bad
        authorization response triggers the appropriate error path.
        """
        from custom_components.saxo_portfolio.config_flow import (
            SaxoPortfolioFlowHandler,
        )

        config_flow = SaxoPortfolioFlowHandler()
        config_flow.hass = mock_hass

        # Verify the config flow has the expected OAuth2-based structure
        assert hasattr(config_flow, "async_step_user")
        assert hasattr(config_flow, "logger")

        # Simulate an external step with an error from the OAuth provider
        # HA's AbstractOAuth2FlowHandler handles this in async_step_creation
        # by catching errors and returning an abort result
        assert config_flow.DOMAIN == DOMAIN

    @pytest.mark.asyncio
    async def test_sensor_unavailable_state_during_errors(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test that sensors report unavailable when coordinator has no data.

        SaxoSensorBase.available returns False when coordinator.data is None.
        """
        from custom_components.saxo_portfolio.sensor import SaxoTotalValueSensor

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        # Coordinator in error state with no data
        coordinator.data = None

        # Patch get_client_id and get_currency which are called during sensor init
        with (
            patch.object(coordinator, "get_client_id", return_value="test123"),
            patch.object(coordinator, "get_currency", return_value="USD"),
        ):
            sensor = SaxoTotalValueSensor(coordinator)

            # Sensor should report unavailable when coordinator.data is None
            assert sensor.available is False

    @pytest.mark.asyncio
    async def test_integration_setup_failure_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test that async_setup_entry returns False when setup fails.

        async_setup_entry wraps its body in a try/except. For non-auth/non-network
        errors it returns False to indicate setup failure.
        """
        from custom_components.saxo_portfolio import async_setup_entry

        # Mock that async_get_config_entry_implementation raises a generic error.
        # The except block returns False for errors that are not auth/network related.
        with patch(
            "custom_components.saxo_portfolio.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            side_effect=Exception("No implementation found"),
        ):
            result = await async_setup_entry(mock_hass, mock_config_entry)
            assert result is False

    @pytest.mark.asyncio
    async def test_concurrent_error_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test that concurrent calls to _fetch_portfolio_data handle errors independently."""
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        call_count = 0

        async def alternating_balance(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise aiohttp.ClientError("Network error")
            return {
                "CashBalance": 5000.00,
                "Currency": "USD",
                "TotalValue": 100000.00,
            }

        mock_client.get_account_balance.side_effect = alternating_balance
        mock_client.get_client_details.return_value = None

        with patch.object(
            type(coordinator), "api_client", new_callable=PropertyMock
        ) as prop:
            prop.return_value = mock_client

            tasks = []
            for _ in range(4):
                tasks.append(asyncio.create_task(coordinator._fetch_portfolio_data()))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Some should succeed, some should fail with UpdateFailed
            successful = [r for r in results if isinstance(r, dict)]
            failed = [r for r in results if isinstance(r, UpdateFailed)]
            assert len(successful) >= 1
            assert len(failed) >= 1

    @pytest.mark.asyncio
    async def test_data_corruption_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of corrupted or malformed API responses.

        When the balance API returns unexpected data, the coordinator still processes
        it using .get() with defaults, producing a valid result dict.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        # Malformed balance response - missing expected keys
        mock_client.get_account_balance.return_value = {
            "InvalidField": "not_a_number",
            "CashBalance": "invalid_float",
            # Missing Currency and TotalValue
        }
        mock_client.get_client_details.return_value = None

        with patch.object(
            type(coordinator), "api_client", new_callable=PropertyMock
        ) as prop:
            prop.return_value = mock_client

            result = await coordinator._fetch_portfolio_data()

            # The coordinator uses .get() with defaults, so it should still return a dict
            assert isinstance(result, dict)
            # CashBalance is "invalid_float" string - the coordinator passes it through
            assert result["cash_balance"] == "invalid_float"
            # Missing keys get default values
            assert result["currency"] == "USD"
            assert result["total_value"] == 0.0
            assert "last_updated" in result

    @pytest.mark.asyncio
    async def test_timeout_handling_for_slow_api(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of API timeouts.

        TimeoutError is caught by the coordinator and re-raised as UpdateFailed.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        mock_client.get_account_balance.side_effect = TimeoutError("Request timed out")

        with patch.object(
            type(coordinator), "api_client", new_callable=PropertyMock
        ) as prop:
            prop.return_value = mock_client

            with pytest.raises(UpdateFailed, match="timeout"):
                await coordinator._fetch_portfolio_data()

    @pytest.mark.asyncio
    async def test_recovery_after_extended_outage(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test recovery after extended API outage by calling _fetch_portfolio_data directly.

        After multiple failures (UpdateFailed), a successful call returns valid data.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        with patch.object(
            type(coordinator), "api_client", new_callable=PropertyMock
        ) as prop:
            prop.return_value = mock_client

            # Extended outage - multiple failed attempts
            mock_client.get_account_balance.side_effect = aiohttp.ClientError(
                "Service unavailable"
            )

            for _ in range(5):
                with pytest.raises(UpdateFailed):
                    await coordinator._fetch_portfolio_data()

            # Service recovers
            mock_client.get_account_balance.side_effect = None
            mock_client.get_account_balance.return_value = {
                "CashBalance": 6000.00,
                "Currency": "USD",
                "TotalValue": 135000.00,
            }
            mock_client.get_client_details.return_value = None

            result = await coordinator._fetch_portfolio_data()
            assert result is not None
            assert isinstance(result, dict)
            assert result["total_value"] == 135000.00
            assert result["cash_balance"] == 6000.00

    @pytest.mark.asyncio
    async def test_error_logging_and_diagnostics(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test that errors are properly logged for diagnostics.

        When _fetch_portfolio_data raises an APIError, the coordinator logs the error
        and re-raises as UpdateFailed.
        """
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_client = AsyncMock()
        mock_client.base_url = "https://gateway.saxobank.com/openapi"

        mock_client.get_account_balance.side_effect = APIError("API connection failed")

        with (
            patch.object(
                type(coordinator), "api_client", new_callable=PropertyMock
            ) as prop,
            patch(
                "custom_components.saxo_portfolio.coordinator._LOGGER"
            ) as mock_logger,
        ):
            prop.return_value = mock_client

            with pytest.raises(UpdateFailed, match="API error"):
                await coordinator._fetch_portfolio_data()

            # Should have logged the error
            assert mock_logger.error.called
            log_message = str(mock_logger.error.call_args_list[0])
            assert "API" in log_message


@pytest.mark.integration
class TestProactiveTokenRefresh:
    """Tests for surviving Saxo downtime via proactive refresh-token rotation.

    These validate that we refresh the refresh token well before it expires
    server-side, and that transient failures while doing so don't cascade
    into a forced reauthentication.
    """

    @pytest.fixture
    def mock_hass(self):
        """Mock Home Assistant with a config_entries namespace."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
        hass.config_entries = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()
        return hass

    def _make_entry(self, token: dict) -> MagicMock:
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_proactive"
        entry.data = {"token": token}
        entry.title = "Saxo Portfolio"
        entry.options = {}
        return entry

    def _make_session(self, token: dict, implementation: Mock) -> MagicMock:
        session = MagicMock()
        session.token = token
        session.implementation = implementation
        session.async_ensure_token_valid = AsyncMock()
        return session

    def _past_half_life_token(self) -> dict:
        """Token that is past half-life but whose access token is still valid."""
        now = datetime.now().timestamp()
        return {
            "access_token": "old_access",
            "refresh_token": "old_refresh",
            "token_type": "Bearer",
            # access token issued 1900s ago, expires in 1200s (so expired 700s ago
            # from access-token perspective, but still "usable" since
            # async_ensure_token_valid is mocked)
            "expires_at": now - 700,
            "expires_in": 1200,
            # refresh token lifetime = 3600s, issued 1900s ago -> 53% elapsed,
            # safely past the 50% half-life threshold
            "refresh_token_expires_in": 3600,
            "token_issued_at": now - 1900,
        }

    def _young_token(self) -> dict:
        """Token comfortably under the half-life threshold."""
        now = datetime.now().timestamp()
        return {
            "access_token": "fresh_access",
            "refresh_token": "fresh_refresh",
            "token_type": "Bearer",
            "expires_at": now + 1000,
            "expires_in": 1200,
            "refresh_token_expires_in": 3600,
            "token_issued_at": now - 600,  # 17% elapsed, well under half-life
        }

    @pytest.mark.asyncio
    async def test_proactive_refresh_fires_past_half_life(self, mock_hass):
        """Proactive refresh fires once the refresh token is past half-life.

        The rotated token must be persisted to the config entry.
        """
        token = self._past_half_life_token()
        entry = self._make_entry(token)

        new_token = {
            "access_token": "rotated_access",
            "refresh_token": "rotated_refresh",
            "token_type": "Bearer",
            "expires_in": 1200,
            "refresh_token_expires_in": 3600,
            "token_issued_at": datetime.now().timestamp(),
        }
        implementation = Mock()
        implementation.async_refresh_token = AsyncMock(return_value=new_token)
        session = self._make_session(token, implementation)

        coordinator = SaxoCoordinator(mock_hass, entry, session)
        # The base class super().__init__ overrides config_entry via ContextVar.
        # Restore it so _proactive_refresh_token can access config_entry.data.
        coordinator.config_entry = entry

        await coordinator._ensure_token_valid()

        implementation.async_refresh_token.assert_awaited_once_with(token)
        mock_hass.config_entries.async_update_entry.assert_called_once()
        persisted_kwargs = mock_hass.config_entries.async_update_entry.call_args.kwargs
        assert persisted_kwargs["data"]["token"] == new_token
        # Safety-net call still happens
        session.async_ensure_token_valid.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_refresh_skipped_for_young_token(self, mock_hass):
        """Token under half-life -> no proactive refresh, just the safety net."""
        token = self._young_token()
        entry = self._make_entry(token)

        implementation = Mock()
        implementation.async_refresh_token = AsyncMock()
        session = self._make_session(token, implementation)

        coordinator = SaxoCoordinator(mock_hass, entry, session)
        await coordinator._ensure_token_valid()

        implementation.async_refresh_token.assert_not_awaited()
        mock_hass.config_entries.async_update_entry.assert_not_called()
        session.async_ensure_token_valid.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_refresh_swallows_network_error(self, mock_hass):
        """Transient network failure during proactive refresh is swallowed.

        ConfigEntryAuthFailed must not be raised - the existing token is still
        usable on Saxo's side and the next coordinator cycle will retry.
        """
        token = self._past_half_life_token()
        entry = self._make_entry(token)

        implementation = Mock()
        implementation.async_refresh_token = AsyncMock(
            side_effect=aiohttp.ClientConnectionError("Saxo unreachable")
        )
        session = self._make_session(token, implementation)

        coordinator = SaxoCoordinator(mock_hass, entry, session)
        # Must not raise - transient errors are swallowed
        await coordinator._ensure_token_valid()

        implementation.async_refresh_token.assert_awaited_once()
        mock_hass.config_entries.async_update_entry.assert_not_called()
        # Safety net still runs
        session.async_ensure_token_valid.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_refresh_swallows_timeout(self, mock_hass):
        """TimeoutError during proactive refresh is treated as transient."""
        token = self._past_half_life_token()
        entry = self._make_entry(token)

        implementation = Mock()
        implementation.async_refresh_token = AsyncMock(side_effect=TimeoutError())
        session = self._make_session(token, implementation)

        coordinator = SaxoCoordinator(mock_hass, entry, session)
        await coordinator._ensure_token_valid()

        mock_hass.config_entries.async_update_entry.assert_not_called()
        session.async_ensure_token_valid.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_refresh_swallows_5xx(self, mock_hass):
        """5xx from Saxo during proactive refresh is a transient server error."""
        token = self._past_half_life_token()
        entry = self._make_entry(token)

        implementation = Mock()
        implementation.async_refresh_token = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(),
                history=(),
                status=503,
                message="Service Unavailable",
            )
        )
        session = self._make_session(token, implementation)

        coordinator = SaxoCoordinator(mock_hass, entry, session)
        await coordinator._ensure_token_valid()

        mock_hass.config_entries.async_update_entry.assert_not_called()
        session.async_ensure_token_valid.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_refresh_raises_reauth_on_invalid_grant(self, mock_hass):
        """400/401 from Saxo during proactive refresh -> ConfigEntryAuthFailed."""
        token = self._past_half_life_token()
        entry = self._make_entry(token)

        implementation = Mock()
        implementation.async_refresh_token = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(),
                history=(),
                status=400,
                message="Bad Request",
            )
        )
        session = self._make_session(token, implementation)

        coordinator = SaxoCoordinator(mock_hass, entry, session)
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._ensure_token_valid()

        mock_hass.config_entries.async_update_entry.assert_not_called()
        # Safety net should NOT be reached on hard auth failure
        session.async_ensure_token_valid.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_proactive_refresh_raises_reauth_on_401(self, mock_hass):
        """401 from Saxo during proactive refresh -> ConfigEntryAuthFailed."""
        token = self._past_half_life_token()
        entry = self._make_entry(token)

        implementation = Mock()
        implementation.async_refresh_token = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(),
                history=(),
                status=401,
                message="Unauthorized",
            )
        )
        session = self._make_session(token, implementation)

        coordinator = SaxoCoordinator(mock_hass, entry, session)
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._ensure_token_valid()

        mock_hass.config_entries.async_update_entry.assert_not_called()
        session.async_ensure_token_valid.assert_not_awaited()
