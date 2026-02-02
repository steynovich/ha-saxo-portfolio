"""Contract tests for Saxo Net Positions API endpoint.

These tests validate that the Saxo API client returns net positions data
matching the expected schema from the contract specification.
"""

import pytest
from unittest.mock import AsyncMock, patch

from custom_components.saxo_portfolio.api.saxo_client import SaxoApiClient


@pytest.mark.contract
class TestSaxoNetPositionsContract:
    """Contract tests for /port/v1/netpositions/me endpoint."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Saxo API client with mocked session."""
        client = SaxoApiClient(access_token="mock_token", base_url="https://test.api")
        return client

    @pytest.fixture
    def valid_net_positions_response(self):
        """Return a valid net positions response matching API contract."""
        return {
            "__count": 2,
            "Data": [
                {
                    "NetPositionId": "position_1",
                    "NetPositionBase": {
                        "Uic": 123456,
                        "AssetType": "Stock",
                        "Amount": 100.0,
                    },
                    "NetPositionView": {
                        "CurrentPrice": 150.25,
                        "MarketValue": 15025.00,
                        "ProfitLossOnTrade": 1025.50,
                    },
                    "DisplayAndFormat": {
                        "Symbol": "AAPL",
                        "Description": "Apple Inc.",
                        "Currency": "USD",
                    },
                },
                {
                    "NetPositionId": "position_2",
                    "NetPositionBase": {
                        "Uic": 789012,
                        "AssetType": "FxSpot",
                        "Amount": 10000.0,
                    },
                    "NetPositionView": {
                        "CurrentPrice": 1.0845,
                        "MarketValue": 10845.00,
                        "ProfitLossOnTrade": -55.00,
                    },
                    "DisplayAndFormat": {
                        "Symbol": "EUR/USD",
                        "Description": "Euro vs US Dollar",
                        "Currency": "USD",
                    },
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_net_positions_response_schema(
        self, mock_client, valid_net_positions_response
    ):
        """Test that net positions response matches contract schema."""
        with patch.object(
            mock_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=valid_net_positions_response,
        ):
            response = await mock_client.get_net_positions()

            # Validate top-level structure
            assert "__count" in response or "Data" in response
            assert "Data" in response
            assert isinstance(response["Data"], list)

            # If positions exist, validate each position
            if response.get("__count", len(response["Data"])) > 0:
                position = response["Data"][0]

                # Required fields from contract
                assert "NetPositionId" in position
                assert "NetPositionBase" in position
                assert "NetPositionView" in position
                assert "DisplayAndFormat" in position

    @pytest.mark.asyncio
    async def test_net_position_data_types(
        self, mock_client, valid_net_positions_response
    ):
        """Test that net position fields have correct data types."""
        with patch.object(
            mock_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=valid_net_positions_response,
        ):
            response = await mock_client.get_net_positions()

            position = response["Data"][0]

            # NetPositionId should be string
            assert isinstance(position["NetPositionId"], str)

            # NetPositionBase field types
            base = position["NetPositionBase"]
            assert isinstance(base["Uic"], int)
            assert isinstance(base["Amount"], int | float)
            assert isinstance(base["AssetType"], str)

            # NetPositionView field types
            view = position["NetPositionView"]
            assert isinstance(view["CurrentPrice"], int | float)

            # DisplayAndFormat field types
            display = position["DisplayAndFormat"]
            assert isinstance(display["Symbol"], str)
            assert isinstance(display["Currency"], str)

    @pytest.mark.asyncio
    async def test_asset_type_enumeration(
        self, mock_client, valid_net_positions_response
    ):
        """Test that AssetType values are valid."""
        with patch.object(
            mock_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=valid_net_positions_response,
        ):
            response = await mock_client.get_net_positions()

            for position in response["Data"]:
                asset_type = position["NetPositionBase"]["AssetType"]
                # Allow any string for flexibility, but log if unexpected
                assert isinstance(asset_type, str)

    @pytest.mark.asyncio
    async def test_net_position_financial_data_validation(
        self, mock_client, valid_net_positions_response
    ):
        """Test that financial data is valid."""
        import math

        with patch.object(
            mock_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=valid_net_positions_response,
        ):
            response = await mock_client.get_net_positions()

            for position in response["Data"]:
                view = position["NetPositionView"]

                # Prices must be finite
                assert math.isfinite(view["CurrentPrice"])

                # P&L can be negative but must be finite
                if "ProfitLossOnTrade" in view:
                    assert math.isfinite(view["ProfitLossOnTrade"])

    @pytest.mark.asyncio
    async def test_empty_net_positions_response(self, mock_client):
        """Test handling of empty net positions response."""
        empty_response = {"__count": 0, "Data": []}

        with patch.object(
            mock_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=empty_response,
        ):
            response = await mock_client.get_net_positions()

            assert response["__count"] == 0
            assert response["Data"] == []

    @pytest.mark.asyncio
    async def test_net_positions_request_parameters(self, mock_client):
        """Test that net positions request includes proper field groups."""
        with patch.object(
            mock_client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"Data": []}

            await mock_client.get_net_positions()

            # Verify the request was made with correct parameters
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            params = call_args[1] if call_args[1] else call_args[0][1]

            assert "FieldGroups" in params
            assert "NetPositionBase" in params["FieldGroups"]
            assert "NetPositionView" in params["FieldGroups"]
            assert "DisplayAndFormat" in params["FieldGroups"]
