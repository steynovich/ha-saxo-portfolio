"""Contract tests for Saxo Balance API endpoint.

These tests validate that the Saxo API client returns data matching
the expected schema from the contract specification.

The balance tests mock `_make_request` to return contract-conforming
responses, then assert that `get_account_balance()` validates and
returns the data correctly.
"""

import pytest
from unittest.mock import AsyncMock, patch

from custom_components.saxo_portfolio.api.saxo_client import (
    SaxoApiClient,
    AuthenticationError,
    RateLimitError,
    APIError,
)


@pytest.mark.contract
class TestSaxoBalanceContract:
    """Contract tests for /port/v1/balances/me endpoint."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Saxo API client with a base URL."""
        return SaxoApiClient(
            access_token="mock_token",
            base_url="https://gateway.saxobank.com/openapi",
        )

    @pytest.fixture
    def mock_balance_response(self):
        """Return a valid balance API response."""
        return {
            "CashBalance": 5000.00,
            "Currency": "USD",
            "TotalValue": 125000.00,
            "MarginAvailableForTrading": 50000.00,
            "UnrealizedMarginProfitLoss": 2500.00,
            "OpenPositionsCount": 5,
        }

    @pytest.mark.asyncio
    async def test_balance_response_schema(self, mock_client, mock_balance_response):
        """Test that balance response matches contract schema."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_balance_response
            response = await mock_client.get_account_balance()

        # Validate required fields from contract
        assert "CashBalance" in response
        assert "Currency" in response
        assert "TotalValue" in response

        # Validate field types
        assert isinstance(response["CashBalance"], int | float)
        assert isinstance(response["Currency"], str)
        assert isinstance(response["TotalValue"], int | float)

        # Validate optional fields if present
        if "MarginAvailableForTrading" in response:
            assert isinstance(response["MarginAvailableForTrading"], int | float)
        if "UnrealizedMarginProfitLoss" in response:
            assert isinstance(response["UnrealizedMarginProfitLoss"], int | float)
        if "OpenPositionsCount" in response:
            assert isinstance(response["OpenPositionsCount"], int)

    @pytest.mark.asyncio
    async def test_balance_currency_code_valid(
        self, mock_client, mock_balance_response
    ):
        """Test that currency code is valid ISO 4217."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_balance_response
            response = await mock_client.get_account_balance()

        currency = response["Currency"]
        # Basic validation - should be 3-letter uppercase code
        assert len(currency) == 3
        assert currency.isupper()
        assert currency.isalpha()

    @pytest.mark.asyncio
    async def test_balance_calculation_reliability(
        self, mock_client, mock_balance_response
    ):
        """Test that CalculationReliability field has valid values."""
        mock_balance_response["CalculationReliability"] = "Ok"

        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_balance_response
            response = await mock_client.get_account_balance()

        if "CalculationReliability" in response:
            reliability = response["CalculationReliability"]
            assert reliability in ["Ok", "Delayed", "Warning"]

    @pytest.mark.asyncio
    async def test_balance_error_handling(self, mock_client):
        """Test contract for error responses."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = AuthenticationError(
                "Authentication failed. Please reconfigure the integration."
            )

            with pytest.raises(AuthenticationError) as exc_info:
                await mock_client.get_account_balance()

        # Should raise authentication-related exception
        assert "auth" in str(exc_info.value).lower() or "401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_balance_rate_limit_handling(self, mock_client):
        """Test contract for rate limit responses."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = RateLimitError(
                "API rate limit exceeded. Please wait before retrying. (reset: 1640995200)"
            )

            with pytest.raises(RateLimitError) as exc_info:
                await mock_client.get_account_balance()

        # Should raise rate limit exception
        assert "rate limit" in str(exc_info.value).lower() or "429" in str(
            exc_info.value
        )

    @pytest.mark.asyncio
    async def test_balance_data_types_strict(self, mock_client, mock_balance_response):
        """Test strict type validation for financial data."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_balance_response
            response = await mock_client.get_account_balance()

        # Financial values must be finite numbers (not NaN or infinity)
        import math

        cash_balance = response["CashBalance"]
        assert math.isfinite(cash_balance)

        total_value = response["TotalValue"]
        assert math.isfinite(total_value)
        assert total_value >= 0  # Total value cannot be negative

        # Positions count must be non-negative integer
        if "OpenPositionsCount" in response:
            positions_count = response["OpenPositionsCount"]
            assert isinstance(positions_count, int)
            assert positions_count >= 0
