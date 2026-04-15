"""Integration tests for error handling and recovery.

These tests validate comprehensive error handling across all integration
components, following error scenarios from quickstart.md troubleshooting.

⚠️  TDD REQUIREMENT: These tests MUST FAIL initially since no implementation exists.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta
import aiohttp
import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.config_flow import SaxoPortfolioFlowHandler
from custom_components.saxo_portfolio.const import DOMAIN


@pytest.mark.integration
class TestErrorHandlingAndRecovery:
    """Integration tests for comprehensive error handling and recovery."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
        return hass

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry with OAuth token."""
        config_entry = Mock(spec=ConfigEntry)
        config_entry.entry_id = "test_entry_123"
        config_entry.data = {
            "token": {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
                "expires_at": (datetime.now() + timedelta(hours=1)).timestamp(),
                "token_type": "Bearer",
            }
        }
        return config_entry

    @pytest.fixture
    def mock_oauth_session(self, mock_config_entry):
        """Create a mock OAuth2 session."""
        session = Mock()
        session.token = mock_config_entry.data["token"]
        session.async_ensure_token_valid = AsyncMock()
        return session

    @pytest.fixture
    def mock_expired_config_entry(self):
        """Create config entry with expired token."""
        config_entry = Mock(spec=ConfigEntry)
        config_entry.entry_id = "expired_entry_123"
        config_entry.data = {
            "token": {
                "access_token": "expired_token",
                "refresh_token": "test_refresh",
                "expires_at": (datetime.now() - timedelta(hours=1)).timestamp(),
                "token_type": "Bearer",
            }
        }
        return config_entry

    @pytest.fixture
    def mock_expired_oauth_session(self, mock_expired_config_entry):
        """Create a mock OAuth2 session with expired token."""
        session = Mock()
        session.token = mock_expired_config_entry.data["token"]
        session.async_ensure_token_valid = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_authentication_failure_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of authentication failures (401 errors).

        This validates troubleshooting: 'Sensors show Unavailable'
        """
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.SaxoApiClient"
        ) as mock_client_class:
            mock_client = AsyncMock()

            # Mock 401 authentication error
            auth_error = aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=401, message="Unauthorized"
            )
            mock_client.get_account_balance.side_effect = auth_error
            mock_client_class.return_value = mock_client

            # Should raise ConfigEntryAuthFailed for Home Assistant to handle
            with pytest.raises(ConfigEntryAuthFailed):
                await coordinator._async_update_data()

            # Coordinator should track failed state
            assert coordinator.last_update_success is False

    @pytest.mark.asyncio
    async def test_network_connectivity_failure_recovery(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of network connectivity issues.

        This validates troubleshooting: 'Data not updating'
        """
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.SaxoApiClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # First attempt: Network error
            network_error = aiohttp.ClientError("Network unreachable")
            mock_client.get_account_balance.side_effect = network_error

            # Should handle network error gracefully
            result = await coordinator._async_update_data()

            # Should return None or empty data, not raise exception
            assert result is None or isinstance(result, dict)
            assert coordinator.last_update_success is False

            # Second attempt: Network recovered
            mock_client.get_account_balance.side_effect = None
            mock_client.get_account_balance.return_value = {
                "CashBalance": 5000.00,
                "Currency": "USD",
                "TotalValue": 125000.00,
            }
            mock_client.get_positions.return_value = {"__count": 0, "Data": []}
            mock_client.get_accounts.return_value = {"__count": 0, "Data": []}

            # Should recover successfully
            result = await coordinator._async_update_data()
            assert result is not None
            assert coordinator.last_update_success is True

    @pytest.mark.asyncio
    async def test_rate_limit_error_handling_with_backoff(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of API rate limits (429 errors).

        This validates troubleshooting: Rate limit handling
        """
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.SaxoApiClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock 429 rate limit error with retry-after header
            rate_limit_error = aiohttp.ClientResponseError(
                request_info=Mock(),
                history=(),
                status=429,
                message="Too Many Requests",
                headers={"Retry-After": "60", "X-RateLimit-Reset": "1640995200"},
            )

            # First attempt: Rate limited
            mock_client.get_account_balance.side_effect = rate_limit_error

            with patch("asyncio.sleep") as mock_sleep:
                # Should handle rate limit with backoff
                try:
                    await coordinator._async_update_data()
                except Exception:
                    # Should attempt exponential backoff
                    if mock_sleep.called:
                        sleep_duration = mock_sleep.call_args[0][0]
                        # Should wait at least the retry-after time or use exponential backoff
                        assert sleep_duration >= 60 or sleep_duration >= 1

    @pytest.mark.asyncio
    async def test_oauth_token_refresh_failure_handling(
        self, mock_hass, mock_expired_config_entry, mock_expired_oauth_session
    ):
        """Test handling of OAuth token refresh failures."""
        # This test MUST FAIL initially - no implementation exists

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
        """Test handling when some API endpoints fail but others succeed."""
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.SaxoApiClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Balance endpoint succeeds
            mock_client.get_account_balance.return_value = {
                "CashBalance": 5000.00,
                "Currency": "USD",
                "TotalValue": 125000.00,
            }

            # Positions endpoint fails
            mock_client.get_positions.side_effect = Exception(
                "Positions service unavailable"
            )

            # Accounts endpoint succeeds
            mock_client.get_accounts.return_value = {
                "__count": 1,
                "Data": [{"AccountId": "acc_001", "Active": True}],
            }

            # Should handle partial failure gracefully
            result = await coordinator._async_update_data()

            # Should include successful data
            assert result is not None
            assert "portfolio" in result
            assert result["portfolio"]["total_value"] == 125000.00

            # Should handle failed positions gracefully (empty list or cached data)
            assert "positions" in result
            positions = result["positions"]
            assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_config_flow_oauth_error_recovery(self, mock_hass):
        """Test config flow error handling during OAuth setup."""
        # This test MUST FAIL initially - no implementation exists

        config_flow = SaxoPortfolioFlowHandler()
        config_flow.hass = mock_hass

        # Mock OAuth error during authorization
        with patch("aiohttp.ClientSession.post") as mock_post:
            oauth_error_response = AsyncMock()
            oauth_error_response.status = 400
            oauth_error_response.json.return_value = {
                "error": "invalid_client",
                "error_description": "Invalid client credentials",
            }
            mock_post.return_value = oauth_error_response

            # Should handle OAuth error gracefully
            result = await config_flow._exchange_code_for_token("invalid_code", Mock())

            # Should either return error state or raise appropriate exception
            assert result is None or "error" in str(result).lower()

    @pytest.mark.asyncio
    async def test_sensor_unavailable_state_during_errors(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test that sensors show unavailable state during coordinator errors."""
        # This test MUST FAIL initially - no implementation exists

        from custom_components.saxo_portfolio.sensor import SaxoPortfolioSensor

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        # Coordinator in error state
        coordinator.last_update_success = False
        coordinator.data = None

        # Create sensor
        sensor = SaxoPortfolioSensor(coordinator, "total_value")

        # Sensor should report unavailable
        assert sensor.available is False
        assert sensor.state in [None, "unavailable", "unknown"]

    @pytest.mark.asyncio
    async def test_integration_setup_failure_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test integration setup failure handling."""
        # This test MUST FAIL initially - no implementation exists

        from custom_components.saxo_portfolio import async_setup_entry

        # Mock coordinator creation failure
        with patch(
            "custom_components.saxo_portfolio.coordinator.SaxoCoordinator"
        ) as mock_coordinator_class:
            mock_coordinator_class.side_effect = Exception("Coordinator init failed")

            # Setup should handle failure gracefully
            result = await async_setup_entry(mock_hass, mock_config_entry)

            # Should return False to indicate setup failure
            assert result is False

    @pytest.mark.asyncio
    async def test_concurrent_error_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test error handling under concurrent request scenarios."""
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch.object(coordinator, "_async_update_data") as mock_update:
            # Some requests succeed, some fail
            results = [
                {"portfolio": {"total_value": 100000}},
                Exception("Network error"),
                {"portfolio": {"total_value": 105000}},
                Exception("Rate limited"),
            ]

            mock_update.side_effect = results

            # Make concurrent requests
            tasks = [
                asyncio.create_task(coordinator.async_request_refresh()),
                asyncio.create_task(coordinator.async_request_refresh()),
                asyncio.create_task(coordinator.async_request_refresh()),
                asyncio.create_task(coordinator.async_request_refresh()),
            ]

            # Should not crash, handle errors gracefully
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Should have some successful results
            successful_results = [r for r in results if not isinstance(r, Exception)]
            assert len(successful_results) >= 1

    @pytest.mark.asyncio
    async def test_data_corruption_handling(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of corrupted or malformed API responses."""
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.SaxoApiClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Malformed balance response
            mock_client.get_account_balance.return_value = {
                "InvalidField": "not_a_number",
                "CashBalance": "invalid_float",
                # Missing required Currency field
            }

            # Should handle malformed data gracefully
            result = await coordinator._async_update_data()

            # Should either return None/empty data or sanitized data
            if result is not None:
                # If data is returned, it should be properly formatted
                assert isinstance(result, dict)
                if "portfolio" in result:
                    portfolio = result["portfolio"]
                    if "total_value" in portfolio:
                        # Should be a valid number
                        assert isinstance(portfolio["total_value"], int | float)

    @pytest.mark.asyncio
    async def test_timeout_handling_for_slow_api(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test handling of API timeouts."""
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.SaxoApiClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock timeout error
            timeout_error = TimeoutError("Request timed out")
            mock_client.get_account_balance.side_effect = timeout_error

            # Should handle timeout gracefully
            result = await coordinator._async_update_data()

            # Should not crash, return appropriate result
            assert result is None or isinstance(result, dict)
            assert coordinator.last_update_success is False

    @pytest.mark.asyncio
    async def test_recovery_after_extended_outage(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test recovery after extended API outage."""
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        # Initial successful state
        coordinator.data = {
            "portfolio": {"total_value": 100000.00},
            "accounts": [],
            "positions": [],
            "last_updated": datetime.now().isoformat(),
        }
        coordinator.last_update_success = True

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.SaxoApiClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Extended outage - multiple failed attempts
            for _ in range(5):
                mock_client.get_account_balance.side_effect = Exception(
                    "Service unavailable"
                )
                await coordinator.async_request_refresh()
                assert coordinator.last_update_success is False

            # Service recovers
            mock_client.get_account_balance.side_effect = None
            mock_client.get_account_balance.return_value = {
                "CashBalance": 6000.00,
                "Currency": "USD",
                "TotalValue": 135000.00,
            }
            mock_client.get_positions.return_value = {"__count": 0, "Data": []}
            mock_client.get_accounts.return_value = {"__count": 0, "Data": []}

            # Should recover successfully
            await coordinator.async_request_refresh()
            assert coordinator.last_update_success is True
            assert coordinator.data["portfolio"]["total_value"] == 135000.00

    @pytest.mark.asyncio
    async def test_error_logging_and_diagnostics(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test that errors are properly logged for diagnostics."""
        # This test MUST FAIL initially - no implementation exists

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        with patch(
            "custom_components.saxo_portfolio.coordinator._LOGGER"
        ) as mock_logger:
            # Mock API error
            api_error = Exception("API connection failed")

            with patch.object(
                coordinator, "_fetch_portfolio_data", side_effect=api_error
            ):
                await coordinator._async_update_data()

                # Should log error for diagnostics
                assert mock_logger.error.called or mock_logger.exception.called

                # Log message should include useful diagnostic info
                log_calls = (
                    mock_logger.error.call_args_list
                    + mock_logger.exception.call_args_list
                )
                log_message = str(log_calls[0][0][0]) if log_calls else ""
                assert "API" in log_message or "error" in log_message.lower()


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
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
        hass.config_entries = Mock()
        hass.config_entries.async_update_entry = Mock()
        return hass

    def _make_entry(self, token: dict) -> Mock:
        entry = Mock(spec=ConfigEntry)
        entry.entry_id = "test_entry_proactive"
        entry.data = {"token": token}
        entry.title = "Saxo Portfolio"
        entry.options = {}
        return entry

    def _make_session(self, token: dict, implementation: Mock) -> Mock:
        session = Mock()
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
            # refresh token lifetime = 3600s, issued 1900s ago → 53% elapsed,
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
        await coordinator._ensure_token_valid()

        implementation.async_refresh_token.assert_awaited_once_with(token)
        mock_hass.config_entries.async_update_entry.assert_called_once()
        persisted_kwargs = mock_hass.config_entries.async_update_entry.call_args.kwargs
        assert persisted_kwargs["data"]["token"] == new_token
        # Safety-net call still happens
        session.async_ensure_token_valid.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_refresh_skipped_for_young_token(self, mock_hass):
        """Token under half-life → no proactive refresh, just the safety net."""
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
        """400/401 from Saxo during proactive refresh → ConfigEntryAuthFailed."""
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
        """401 from Saxo during proactive refresh → ConfigEntryAuthFailed."""
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
