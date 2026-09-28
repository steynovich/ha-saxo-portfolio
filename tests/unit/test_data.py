"""Unit tests for the typed coordinator data (issue #26)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from custom_components.saxo_portfolio.data import (
    DEFAULT_CURRENCY,
    UNKNOWN,
    BalanceData,
    ClientInfo,
    PerformanceData,
    SaxoPortfolioData,
    numeric_or_none,
    to_float,
)


class TestConversions:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(1, 1.0), (2.5, 2.5), ("3.25", 3.25), (None, None), ("abc", None), ([], None)],
    )
    def test_to_float(self, value, expected):
        assert to_float(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(1, 1.0), (2.5, 2.5), ("3.25", None), (None, None), ({}, None)],
    )
    def test_numeric_or_none(self, value, expected):
        assert numeric_or_none(value) == expected


class TestClientInfo:
    def test_defaults_unknown(self):
        client = ClientInfo()
        assert (client.client_id, client.account_id, client.client_name) == (
            UNKNOWN,
            UNKNOWN,
            UNKNOWN,
        )
        assert client.has_any_value is False

    @pytest.mark.parametrize(
        "client",
        [
            ClientInfo(client_id="C1"),
            ClientInfo(account_id="A1"),
            ClientInfo(client_name="Someone"),
        ],
    )
    def test_any_known_field_counts(self, client):
        assert client.has_any_value is True

    def test_empty_string_is_not_known(self):
        assert ClientInfo(client_id="", client_name="").has_any_value is False

    def test_frozen(self):
        with pytest.raises(FrozenInstanceError):
            ClientInfo().client_id = "x"  # type: ignore[misc]


class TestBalanceData:
    def test_from_api(self):
        balance = BalanceData.from_api(
            {
                "CashBalance": 1000,
                "Currency": "EUR",
                "TotalValue": 5000.5,
                "NonMarginPositionsValue": 4000.25,
                "Ignored": "x",
            }
        )
        assert balance == BalanceData(
            cash_balance=1000.0,
            currency="EUR",
            total_value=5000.5,
            non_margin_positions_value=4000.25,
        )
        assert isinstance(balance.cash_balance, float)

    def test_missing_fields_default_to_zero_and_usd(self):
        balance = BalanceData.from_api({})
        assert balance == BalanceData(
            cash_balance=0.0,
            currency=DEFAULT_CURRENCY,
            total_value=0.0,
            non_margin_positions_value=0.0,
        )
        assert balance.currency == "USD"
        assert balance.has_any_value is True

    def test_non_numeric_values_are_none(self):
        balance = BalanceData.from_api(
            {
                "CashBalance": "garbage",
                "TotalValue": None,
                "NonMarginPositionsValue": {},
            }
        )
        assert balance.cash_balance is None
        assert balance.total_value is None
        assert balance.non_margin_positions_value is None
        assert balance.has_any_value is False

    def test_numeric_strings_are_converted(self):
        assert BalanceData.from_api({"CashBalance": "12.5"}).cash_balance == 12.5


class TestPerformanceData:
    def test_defaults_are_none(self):
        performance = PerformanceData()
        assert performance.has_any_value is False
        assert performance.ytd_earnings_percentage is None
        assert performance.investment_performance_percentage is None
        assert performance.ytd_investment_performance_percentage is None
        assert performance.month_investment_performance_percentage is None
        assert performance.quarter_investment_performance_percentage is None
        assert performance.cash_transfer_balance is None
        assert performance.ytd_profit_loss is None
        assert performance.ytd_cash_transfer is None

    @pytest.mark.parametrize(
        "field",
        [
            "ytd_earnings_percentage",
            "investment_performance_percentage",
            "ytd_investment_performance_percentage",
            "month_investment_performance_percentage",
            "quarter_investment_performance_percentage",
            "cash_transfer_balance",
            "ytd_profit_loss",
            "ytd_cash_transfer",
        ],
    )
    def test_any_value_counts(self, field):
        assert PerformanceData(**{field: 0.0}).has_any_value is True


class TestSaxoPortfolioData:
    def test_defaults(self):
        data = SaxoPortfolioData(balance=BalanceData(), last_updated=datetime.now())
        assert data.performance == PerformanceData()
        assert data.client == ClientInfo()

    def test_field_names_match_previous_flat_keys(self):
        """Diagnostics' data_keys keep the names and order of the old dict."""
        data = SaxoPortfolioData(balance=BalanceData(), last_updated=datetime.now())
        assert data.field_names == [
            "cash_balance",
            "currency",
            "total_value",
            "non_margin_positions_value",
            "ytd_earnings_percentage",
            "investment_performance_percentage",
            "ytd_investment_performance_percentage",
            "month_investment_performance_percentage",
            "quarter_investment_performance_percentage",
            "cash_transfer_balance",
            "ytd_profit_loss",
            "ytd_cash_transfer",
            "client_id",
            "account_id",
            "client_name",
            "last_updated",
        ]
