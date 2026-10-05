"""Tests for the shared sensor helpers, update-mode attributes and accessors."""

from __future__ import annotations

import logging
import math
from unittest.mock import MagicMock

import pytest

from custom_components.saxo_portfolio.const import (
    DEFAULT_UPDATE_INTERVAL_ANY,
    UPDATE_MODE_FIXED,
    UPDATE_MODE_MARKET_HOURS,
    UPDATE_MODE_UNKNOWN,
)
from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.data import ClientInfo
from custom_components.saxo_portfolio.sensors.base import finite_round
from custom_components.saxo_portfolio.token_expiry import (
    TOKEN_EXPIRY_STATES,
    TokenExpiryStatus,
    token_expiry_status,
)
from custom_components.saxo_portfolio.update_mode import update_mode_attributes


class TestFiniteRound:
    """finite_round: the shared guard/isfinite/round sequence."""

    def test_rounds(self):
        assert finite_round(1.23456) == 1.23
        assert finite_round(1.23456, 4) == 1.2346

    def test_none(self):
        assert finite_round(None) is None

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_non_finite_logs_label_only(self, bad, caplog):
        with caplog.at_level(logging.WARNING):
            assert finite_round(bad, label="cash_balance") is None
        assert "cash_balance" in caplog.text

    def test_non_finite_without_label_is_silent(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert finite_round(math.nan) is None
        assert not caplog.records


class TestTokenExpiryStatus:
    """The state strings are pinned by strings.json and translations."""

    def test_state_values_unchanged(self):
        assert TOKEN_EXPIRY_STATES == ["valid", "warning", "critical", "expired"]

    @pytest.mark.parametrize(
        ("remaining", "expected"),
        [
            (0, "expired"),
            (60, "critical"),
            (300, "warning"),
            (301, "valid"),
        ],
    )
    def test_classification(self, remaining, expected):
        status = token_expiry_status(remaining)
        assert status == expected
        assert isinstance(status, TokenExpiryStatus)


class TestUpdateModeAttributes:
    """update_mode_attributes: one description for sensor and diagnostics."""

    def test_any(self):
        attrs = update_mode_attributes("any")
        assert attrs["mode"] == UPDATE_MODE_FIXED
        assert attrs["update_interval"] == str(DEFAULT_UPDATE_INTERVAL_ANY)
        assert attrs["market_hours_detection"] is False

    def test_market_hours_with_status(self):
        open_attrs = update_mode_attributes("America/New_York", True)
        closed_attrs = update_mode_attributes("America/New_York", False)
        assert open_attrs["mode"] == UPDATE_MODE_MARKET_HOURS
        assert open_attrs["market_hours_detection"] is True
        assert open_attrs["current_market_status"] == "Open"
        assert closed_attrs["current_market_status"] == "Closed"

    def test_market_status_omitted_when_unknown(self):
        assert "current_market_status" not in update_mode_attributes("Europe/Amsterdam")

    def test_unknown_timezone(self):
        attrs = update_mode_attributes("Mars/Olympus_Mons")
        assert attrs["mode"] == UPDATE_MODE_UNKNOWN
        assert "Mars/Olympus_Mons" in attrs["error"]


class TestCoordinatorAccessors:
    """client_id / token_data / update_mode_attributes on the coordinator."""

    @pytest.fixture
    def coord(self):
        c = MagicMock(spec=SaxoCoordinator)
        c.config_entry = MagicMock()
        return c

    def test_client_id(self):
        coord = MagicMock()
        coord.client_info = ClientInfo(client_id="ABC")
        assert SaxoCoordinator.client_id.fget(coord) == "ABC"

    def test_token_data(self, coord):
        coord.config_entry.data = {"token": {"access_token": "x"}}
        assert SaxoCoordinator.token_data.fget(coord) == {"access_token": "x"}
        coord.config_entry.data = {}
        assert SaxoCoordinator.token_data.fget(coord) is None

    def test_update_mode_attributes(self, coord):
        coord.timezone = "any"
        coord.is_market_hours = False
        attrs = SaxoCoordinator.update_mode_attributes(coord)
        assert attrs["mode"] == UPDATE_MODE_FIXED


def test_position_sensor_non_numeric_price_is_none_and_unlogged(caplog):
    """A malformed price yields None; the value itself is never logged."""
    from custom_components.saxo_portfolio.sensors.position import SaxoPositionSensor

    coord = MagicMock()
    coord.client_id = "123"
    position = MagicMock(symbol="AAPL", currency="EUR", current_price="secret-1234")
    coord.get_position.return_value = position
    sensor = SaxoPositionSensor(coord, "aapl_stock")
    with caplog.at_level(logging.DEBUG):
        assert sensor.native_value is None
    assert "secret-1234" not in caplog.text
