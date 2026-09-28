"""Unit tests for position sensor functionality.

These tests cover slug generation, sensor state/attributes, and availability logic.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.saxo_portfolio.coordinator import PositionData


class TestPositionDataSlugGeneration:
    """Tests for PositionData.generate_slug() method."""

    def test_simple_stock_symbol(self):
        """Test slug generation for simple stock symbol."""
        slug = PositionData.generate_slug("AAPL", "Stock")
        assert slug == "aapl_stock"

    def test_forex_pair_symbol(self):
        """Test slug generation for forex pair with special characters."""
        slug = PositionData.generate_slug("EUR/USD", "FxSpot")
        assert slug == "eur_usd_fxspot"

    def test_symbol_with_spaces(self):
        """Test slug generation handles spaces."""
        slug = PositionData.generate_slug("SOME STOCK", "Etf")
        assert slug == "some_stock_etf"

    def test_symbol_with_dots(self):
        """Test slug generation handles dots."""
        slug = PositionData.generate_slug("BRK.B", "Stock")
        assert slug == "brk_b_stock"

    def test_symbol_with_multiple_special_chars(self):
        """Test slug generation handles multiple special characters."""
        slug = PositionData.generate_slug("XAU/USD.OTC", "CfdOnFutures")
        assert slug == "xau_usd_otc_cfdonfutures"

    def test_uppercase_to_lowercase(self):
        """Test that slugs are lowercase."""
        slug = PositionData.generate_slug("TSLA", "STOCK")
        assert slug == "tsla_stock"
        assert slug == slug.lower()

    def test_consecutive_special_chars(self):
        """Test handling of consecutive special characters."""
        slug = PositionData.generate_slug("A--B..C", "Stock")
        assert slug == "a_b_c_stock"
        assert "__" not in slug

    def test_leading_trailing_special_chars(self):
        """Test handling of leading/trailing special characters."""
        slug = PositionData.generate_slug("-AAPL-", "Stock")
        assert slug == "aapl_stock"
        assert not slug.startswith("_")
        assert slug.count("_") == 1  # Only one underscore between symbol and type


class TestPositionDataClass:
    """Tests for PositionData dataclass."""

    def test_position_data_creation(self):
        """Test creating a PositionData instance."""
        position = PositionData(
            position_id="pos_123",
            symbol="AAPL",
            description="Apple Inc.",
            asset_type="Stock",
            amount=100.0,
            current_price=150.25,
            market_value=15025.00,
            profit_loss=1025.50,
            uic=123456,
            currency="USD",
        )

        assert position.position_id == "pos_123"
        assert position.symbol == "AAPL"
        assert position.description == "Apple Inc."
        assert position.asset_type == "Stock"
        assert position.amount == 100.0
        assert position.current_price == 150.25
        assert position.market_value == 15025.00
        assert position.profit_loss == 1025.50
        assert position.uic == 123456
        assert position.currency == "USD"

    def test_position_data_default_currency(self):
        """Test that currency defaults to USD."""
        position = PositionData(
            position_id="pos_123",
            symbol="AAPL",
            description="Apple Inc.",
            asset_type="Stock",
            amount=100.0,
            current_price=150.25,
            market_value=15025.00,
            profit_loss=1025.50,
            uic=123456,
        )

        assert position.currency == "USD"

    def test_position_data_negative_profit_loss(self):
        """Test that negative profit/loss is allowed."""
        position = PositionData(
            position_id="pos_123",
            symbol="TSLA",
            description="Tesla Inc.",
            asset_type="Stock",
            amount=50.0,
            current_price=200.00,
            market_value=10000.00,
            profit_loss=-500.00,
            uic=789012,
        )

        assert position.profit_loss == -500.00


class TestPositionSensorIntegration:
    """Tests for position sensor behavior."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator."""
        coordinator = MagicMock()
        coordinator.get_client_id.return_value = "123456"
        coordinator.last_update_success = True
        coordinator.data = {"last_updated": "2024-01-01T12:00:00"}
        coordinator.update_interval = MagicMock()
        coordinator.update_interval.total_seconds.return_value = 300

        # Mock position data
        position = PositionData(
            position_id="pos_123",
            symbol="AAPL",
            description="Apple Inc.",
            asset_type="Stock",
            amount=100.0,
            current_price=150.25,
            market_value=15025.00,
            profit_loss=1025.50,
            uic=123456,
            currency="USD",
        )
        coordinator.get_position.return_value = position
        coordinator.get_position_ids.return_value = ["aapl_stock"]

        return coordinator

    def test_position_sensor_unique_id_and_translation(self, mock_coordinator):
        """Test that position sensor has correct unique_id and has_entity_name."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        sensor = SaxoPositionSensor(mock_coordinator, "aapl_stock")

        # Unique ID should follow pattern: saxo_{client_id}_position_{slug}
        assert sensor._attr_unique_id == "saxo_123456_position_aapl_stock"
        # Position sensors use a shared translation key with a symbol placeholder
        assert sensor._attr_has_entity_name is True
        assert sensor._attr_translation_key == "position"
        assert sensor._attr_translation_placeholders == {"symbol": "AAPL"}
        # The name comes from translations, not a hard-coded English string
        assert not hasattr(sensor, "_attr_name")

    def test_position_sensor_placeholder_falls_back_to_slug(self, mock_coordinator):
        """Without cached position data the slug is used as the symbol."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        mock_coordinator.get_position.return_value = None
        sensor = SaxoPositionSensor(mock_coordinator, "aapl_stock")

        assert sensor._attr_translation_key == "position"
        assert sensor._attr_translation_placeholders == {"symbol": "aapl_stock"}
        assert sensor._attr_unique_id == "saxo_123456_position_aapl_stock"

    def test_position_sensor_state_is_current_price(self, mock_coordinator):
        """Test that position sensor state is the current price."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        sensor = SaxoPositionSensor(mock_coordinator, "aapl_stock")


        assert sensor.native_value == 150.25

    def test_position_sensor_attributes(self, mock_coordinator):
        """Test that position sensor has expected attributes."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        sensor = SaxoPositionSensor(mock_coordinator, "aapl_stock")

        attrs = sensor.extra_state_attributes

        assert attrs["symbol"] == "AAPL"
        assert attrs["description"] == "Apple Inc."
        assert attrs["asset_type"] == "Stock"
        assert attrs["amount"] == 100.0
        assert attrs["market_value"] == 15025.00
        assert attrs["profit_loss"] == 1025.50
        assert attrs["uic"] == 123456
        assert attrs["currency"] == "USD"

    def test_position_sensor_unavailable_when_position_not_found(
        self, mock_coordinator
    ):
        """Test that sensor is unavailable when position is not in cache."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        mock_coordinator.get_position.return_value = None

        sensor = SaxoPositionSensor(mock_coordinator, "nonexistent_stock")

        # Sensor should be unavailable if position doesn't exist
        assert sensor.available is False

    def test_position_sensor_state_none_when_position_closed(self, mock_coordinator):
        """Test that sensor state is None when position is closed."""
        from custom_components.saxo_portfolio.sensor import SaxoPositionSensor

        mock_coordinator.get_position.return_value = None

        sensor = SaxoPositionSensor(mock_coordinator, "closed_stock")

        assert sensor.native_value is None


_PKG_ROOT = Path(__file__).parents[2] / "custom_components" / "saxo_portfolio"
_TRANSLATION_FILES = [
    _PKG_ROOT / "strings.json",
    *sorted((_PKG_ROOT / "translations").glob("*.json")),
]


def _position_name(path: Path) -> str:
    return json.loads(path.read_text())["entity"]["sensor"]["position"]["name"]


class TestPositionSensorTranslations:
    """The position sensor name is translated in every language file."""

    def test_all_translation_files_present(self):
        # strings.json + 11 languages
        assert len(_TRANSLATION_FILES) == 12

    @pytest.mark.parametrize("path", _TRANSLATION_FILES, ids=lambda p: p.name)
    def test_position_name_has_symbol_placeholder(self, path):
        assert "{symbol}" in _position_name(path)

    @pytest.mark.parametrize(
        "path",
        [_PKG_ROOT / "strings.json", _PKG_ROOT / "translations" / "en.json"],
        ids=lambda p: p.name,
    )
    def test_english_name_matches_previous_hard_coded_name(self, path):
        """HA derives entity IDs from the English name; it must be unchanged."""
        assert _position_name(path).format(symbol="AAPL") == "Position AAPL"
