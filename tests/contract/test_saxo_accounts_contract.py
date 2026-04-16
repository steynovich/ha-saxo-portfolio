"""Contract tests for Saxo Accounts API endpoint.

These tests validate that the Saxo API client returns accounts data
matching the expected schema from the contract specification.

The SaxoApiClient does not have `get_accounts` or `get_account_details` methods.
Account-related information is retrieved via `get_client_details()` which calls
`/port/v1/clients/me` and returns client details including ClientId, ClientKey,
DefaultAccountId, and Name.
"""

import pytest
from unittest.mock import AsyncMock, patch

from custom_components.saxo_portfolio.api.saxo_client import (
    SaxoApiClient,
    AuthenticationError,
    APIError,
)


@pytest.mark.contract
class TestSaxoAccountsContract:
    """Contract tests for /port/v1/clients/me endpoint (account/client details)."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Saxo API client with a base URL."""
        return SaxoApiClient(
            access_token="mock_token",
            base_url="https://gateway.saxobank.com/openapi",
        )

    @pytest.mark.asyncio
    async def test_client_details_response_schema(self, mock_client):
        """Test that client details response matches contract schema."""
        mock_response = {
            "ClientId": "123456",
            "ClientKey": "test_client_key",
            "DefaultAccountId": "ACC001",
            "Name": "Test User",
        }

        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            response = await mock_client.get_client_details()

        # Validate response is a dict
        assert isinstance(response, dict)

        # Required fields from contract
        assert "ClientId" in response
        assert "ClientKey" in response

        # Optional fields that might be present
        if "Name" in response:
            assert isinstance(response["Name"], str)
        if "DefaultAccountId" in response:
            assert isinstance(response["DefaultAccountId"], str)

    @pytest.mark.asyncio
    async def test_client_details_data_types(self, mock_client):
        """Test that client details fields have correct data types."""
        mock_response = {
            "ClientId": "123456",
            "ClientKey": "test_client_key",
            "DefaultAccountId": "ACC001",
            "Name": "Test User",
        }

        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            response = await mock_client.get_client_details()

        # Required field types
        assert isinstance(response["ClientId"], str)
        assert isinstance(response["ClientKey"], str)

        # String fields should not be empty
        assert len(response["ClientId"]) > 0
        assert len(response["ClientKey"]) > 0

    @pytest.mark.asyncio
    async def test_client_details_with_all_fields(self, mock_client):
        """Test that client details handles all optional fields."""
        mock_response = {
            "ClientId": "123456",
            "ClientKey": "test_client_key",
            "DefaultAccountId": "ACC001",
            "Name": "Test User",
            "ClientType": "Normal",
            "Currency": "EUR",
        }

        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            response = await mock_client.get_client_details()

        # All fields should be preserved
        assert response["ClientId"] == "123456"
        assert response["DefaultAccountId"] == "ACC001"
        assert response["Name"] == "Test User"

    @pytest.mark.asyncio
    async def test_client_details_currency_validation(self, mock_client):
        """Test that Currency field contains valid ISO codes."""
        mock_response = {
            "ClientId": "123456",
            "ClientKey": "test_client_key",
            "Currency": "EUR",
        }

        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            response = await mock_client.get_client_details()

        if "Currency" in response:
            currency = response["Currency"]
            # Basic ISO 4217 validation
            assert len(currency) == 3
            assert currency.isupper()
            assert currency.isalpha()

    @pytest.mark.asyncio
    async def test_client_details_name_handling(self, mock_client):
        """Test proper handling of Name field."""
        mock_response = {
            "ClientId": "123456",
            "ClientKey": "test_client_key",
            "Name": "John Doe",
        }

        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            response = await mock_client.get_client_details()

        if "Name" in response:
            name = response["Name"]
            assert isinstance(name, str)
            # Name should be non-empty if present
            assert len(name.strip()) > 0

    @pytest.mark.asyncio
    async def test_client_details_unique_identifiers(self, mock_client):
        """Test that client identifiers are present and unique."""
        mock_response = {
            "ClientId": "123456",
            "ClientKey": "test_client_key",
            "DefaultAccountId": "ACC001",
        }

        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            response = await mock_client.get_client_details()

        # ClientId and ClientKey should be different identifiers
        assert response["ClientId"] != response["ClientKey"]

    @pytest.mark.asyncio
    async def test_client_details_error_handling(self, mock_client):
        """Test contract for client details error responses."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = AuthenticationError("Authentication failed")

            with pytest.raises(AuthenticationError):
                await mock_client.get_client_details()

    @pytest.mark.asyncio
    async def test_client_details_returns_none_on_failure(self, mock_client):
        """Test that client details returns None on non-auth errors."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = APIError("Server error")
            response = await mock_client.get_client_details()

        assert response is None

    @pytest.mark.asyncio
    async def test_client_details_invalid_response(self, mock_client):
        """Test handling of invalid response structure."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = "not a dict"
            response = await mock_client.get_client_details()

        assert response is None
