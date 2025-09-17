"""Contract tests for Saxo Accounts API endpoint.

These tests validate that the Saxo API client returns accounts data
matching the expected schema from the contract specification.

⚠️  TDD REQUIREMENT: These tests MUST FAIL initially since no implementation exists.
"""

import pytest
from unittest.mock import AsyncMock

from custom_components.saxo_portfolio.api.saxo_client import SaxoApiClient


@pytest.mark.contract
class TestSaxoAccountsContract:
    """Contract tests for /port/v1/accounts/{AccountKey} endpoint."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Saxo API client."""
        return SaxoApiClient(access_token="mock_token")

    @pytest.mark.asyncio
    async def test_account_details_response_schema(self, mock_client):
        """Test that account details response matches contract schema."""
        # This test MUST FAIL initially - no implementation exists
        account_key = "test_account_key"
        response = await mock_client.get_account_details(account_key)

        # Validate response is a dict (single account, not list)
        assert isinstance(response, dict)

        # Required fields from contract
        assert "AccountId" in response
        assert "AccountKey" in response
        assert "Active" in response
        assert "AccountType" in response

        # Optional fields that might be present
        if "AccountGroupKey" in response:
            assert isinstance(response["AccountGroupKey"], str)
        if "Currency" in response:
            assert isinstance(response["Currency"], str)
        if "DisplayName" in response:
            assert isinstance(response["DisplayName"], str)

    @pytest.mark.asyncio
    async def test_account_data_types(self, mock_client):
        """Test that account fields have correct data types."""
        # This test MUST FAIL initially - no implementation exists
        account_key = "test_account_key"
        response = await mock_client.get_account_details(account_key)

        # Required field types
        assert isinstance(response["AccountId"], str)
        assert isinstance(response["AccountKey"], str)
        assert isinstance(response["Active"], bool)
        assert isinstance(response["AccountType"], str)

        # String fields should not be empty
        assert len(response["AccountId"]) > 0
        assert len(response["AccountKey"]) > 0
        assert len(response["AccountType"]) > 0

    @pytest.mark.asyncio
    async def test_account_type_enumeration(self, mock_client):
        """Test that AccountType values match contract enumeration."""
        # This test MUST FAIL initially - no implementation exists
        client_key = "test_client_key"
        response = await mock_client.get_accounts(client_key=client_key)

        valid_account_types = ["Normal", "Margin", "ISA", "SIPP"]

        for account in response["Data"]:
            account_type = account["AccountType"]
            assert account_type in valid_account_types

    @pytest.mark.asyncio
    async def test_account_currency_validation(self, mock_client):
        """Test that Currency field contains valid ISO codes."""
        # This test MUST FAIL initially - no implementation exists
        client_key = "test_client_key"
        response = await mock_client.get_accounts(client_key=client_key)

        for account in response["Data"]:
            if "Currency" in account:
                currency = account["Currency"]
                # Basic ISO 4217 validation
                assert len(currency) == 3
                assert currency.isupper()
                assert currency.isalpha()

    @pytest.mark.asyncio
    async def test_active_account_validation(self, mock_client):
        """Test that Active field is boolean and logical."""
        # This test MUST FAIL initially - no implementation exists
        client_key = "test_client_key"
        response = await mock_client.get_accounts(client_key=client_key)

        for account in response["Data"]:
            active = account["Active"]
            assert isinstance(active, bool)
            # Active accounts should have valid identifiers
            if active:
                assert len(account["AccountId"]) > 0
                assert len(account["AccountKey"]) > 0

    @pytest.mark.asyncio
    async def test_accounts_client_key_required(self, mock_client):
        """Test that ClientKey parameter is required for accounts endpoint."""
        # This test MUST FAIL initially - no implementation exists
        with pytest.raises(Exception) as exc_info:
            await mock_client.get_accounts()

        # Should raise exception about missing ClientKey
        error_msg = str(exc_info.value).lower()
        assert "client" in error_msg or "key" in error_msg or "required" in error_msg

    @pytest.mark.asyncio
    async def test_accounts_unique_identifiers(self, mock_client):
        """Test that account identifiers are unique within response."""
        # This test MUST FAIL initially - no implementation exists
        client_key = "test_client_key"
        response = await mock_client.get_accounts(client_key=client_key)

        # Collect all account IDs and keys
        account_ids = [account["AccountId"] for account in response["Data"]]
        account_keys = [account["AccountKey"] for account in response["Data"]]

        # Should not have duplicates
        assert len(account_ids) == len(set(account_ids))
        assert len(account_keys) == len(set(account_keys))

    @pytest.mark.asyncio
    async def test_accounts_error_handling(self, mock_client):
        """Test contract for accounts error responses."""
        # This test MUST FAIL initially - no implementation exists
        # Mock authentication error
        mock_client._session.get = AsyncMock()
        mock_client._session.get.return_value.status = 401

        with pytest.raises(Exception) as exc_info:
            client_key = "test_client_key"
            await mock_client.get_accounts(client_key=client_key)

        assert "auth" in str(exc_info.value).lower() or "401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_accounts_response(self, mock_client):
        """Test handling of empty accounts response."""
        # This test MUST FAIL initially - no implementation exists
        # Mock empty response
        mock_client._session.get = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"__count": 0, "Data": []}
        mock_client._session.get.return_value = mock_response

        client_key = "test_client_key"
        response = await mock_client.get_accounts(client_key=client_key)

        assert response["__count"] == 0
        assert response["Data"] == []

    @pytest.mark.asyncio
    async def test_display_name_handling(self, mock_client):
        """Test proper handling of DisplayName field."""
        # This test MUST FAIL initially - no implementation exists
        client_key = "test_client_key"
        response = await mock_client.get_accounts(client_key=client_key)

        for account in response["Data"]:
            if "DisplayName" in account:
                display_name = account["DisplayName"]
                assert isinstance(display_name, str)
                # Display name should be non-empty if present
                assert len(display_name.strip()) > 0
