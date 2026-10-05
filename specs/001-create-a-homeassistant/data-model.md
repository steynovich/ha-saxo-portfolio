# Data Model: Saxo Portfolio Home Assistant Integration

> Rewritten to match the code (`custom_components/saxo_portfolio/data.py`, `positions.py`, `sensor.py`). The original v1 model (Portfolio/Account aggregation, `unrealized_pnl`, `positions_count`, multi-account totals, currency conversion, account and position limits) was never implemented and is superseded.

## Scope
- One config entry = one Saxo client (unique ID is the Saxo `ClientKey`). Several clients are added as separate entries; nothing is aggregated or currency-converted across entries.
- One `SaxoCoordinator` (DataUpdateCoordinator) per entry. Runtime state is `entry.runtime_data = SaxoRuntimeData(coordinator)`.
- `coordinator.data` is a `SaxoPortfolioData` (or `None` before the first update). Sensors read typed attributes; they never index by string key.
- Parsing lives outside the coordinator: balance in `data.py`, client details and performance in `performance.py` (`PerformanceFetcher`), net positions in `positions.py` (`PositionsFetcher`).

## Typed coordinator data (`data.py`, frozen slotted dataclasses)

### SaxoPortfolioData
| Field | Type | Notes |
|-------|------|-------|
| `balance` | `BalanceData` | From `/port/v1/balances/me`; refreshed every update |
| `last_updated` | `datetime` | Time of the last successful update |
| `performance` | `PerformanceData` | Defaults to all `None`; cached for 2 h |
| `client` | `ClientInfo` | Defaults to `"unknown"` values |

`field_names` lists the field names only (for diagnostics, never values).

### BalanceData
| Field | Type | Default |
|-------|------|---------|
| `cash_balance` | `float \| None` | `0.0` |
| `currency` | `str` | `"USD"` (the real value is the account currency) |
| `total_value` | `float \| None` | `0.0` |
| `non_margin_positions_value` | `float \| None` | `0.0` |

`from_api()` builds it from the balances response. A missing field reads as `0.0`; a value is `None` only when the API returned something that is not a number. `has_any_value` is true when at least one figure is numeric.

### PerformanceData
Every field is `None` until fetched successfully at least once, so Home Assistant never records a fake `0.0` in long-term statistics.

| Field | Source |
|-------|--------|
| `ytd_earnings_percentage` | v3 `BalancePerformance.AccumulatedProfitLoss`. A currency amount despite the historical name; backs the Accumulated Profit/Loss sensor |
| `investment_performance_percentage` | v4 all-time `ReturnFraction * 100` |
| `ytd_investment_performance_percentage` | v4 year-to-date `ReturnFraction * 100` |
| `month_investment_performance_percentage` | v4 `StandardPeriod=Month` (rolling ~28 days) |
| `quarter_investment_performance_percentage` | v4 `StandardPeriod=Quarter` (rolling ~90 days) |
| `cash_transfer_balance` | v4 all-time `Balance.CashTransfer`, latest value |
| `ytd_profit_loss` | v4 year-to-date `Balance.YearlyProfitLoss` |
| `ytd_cash_transfer` | v4 year-to-date `Balance.CashTransfer` |

Only a complete fetch refreshes the cache timestamp; a partial one keeps the last good values and retries on the next update. Performance-API failures never block balance data (ADR 0003).

### ClientInfo
`client_id`, `account_id`, `client_name` (all `str`, default `"unknown"`), from `/port/v1/clients/me` and the account details. `client_id` forms the entity prefix.

## Positions (`positions.py`, opt-in)
Fetched from `/port/v1/netpositions/me` only when "Enable Position Sensors" is on; cached separately from `SaxoPortfolioData`.

### PositionData
`position_id: str`, `symbol: str`, `description: str`, `asset_type: str`, `amount: float`, `current_price: float`, `market_value: float`, `profit_loss: float`, `uic: int`, `currency: str = "USD"`. `generate_slug(symbol, asset_type)` yields e.g. `aapl_stock`, `eur_usd_fxspot` for the unique ID suffix.

### PositionsCache
`positions: dict[str, PositionData]` (keyed by slug), `last_updated: datetime | None`, `position_ids: list[str]`. `has_market_data_access()` derives the Market Data Access diagnostic from the first raw position (`CurrentPriceType`, `CalculationReliability`).

## Entities
Entity IDs are `<platform>.saxo_<clientid>_<translation_key>` (unique ID `saxo_<clientid>_<key>`, lower-cased; all use `_attr_has_entity_name` and translation keys). Examples use Client ID `123456`.

| Group | Entities | State class |
|-------|----------|-------------|
| Balance | `cash_balance`, `total_value`, `non_margin_positions_value`, `cash_transfer_balance`, `ytd_cash_transfer` | `TOTAL` |
| Performance | `accumulated_profit_loss`, `investment_performance`, `ytd_investment_performance`, `month_investment_performance`, `quarter_investment_performance`, `ytd_profit_loss` | `MEASUREMENT` |
| Diagnostic sensors | `client_id`, `account_id`, `name`, `token_expiry`, `market_status`, `last_update`, `timezone`; `market_data_access` only with position sensors | n/a |
| Buttons | `button.saxo_123456_refresh`, `button.saxo_123456_reauthenticate` | n/a |
| Positions (opt-in) | one per open position, named "Position `<symbol>`" (unique ID `saxo_123456_position_<slug>`); state is the current price, attributes include market value and profit/loss | `MEASUREMENT` |

Monetary device class is deliberately not used because HA only allows `TOTAL` for it. The device is named "Saxo `<clientid>` Portfolio".

## Availability and state
- Sticky availability: sensors keep their last value through transient failures and go unavailable only after `max(15 min, 3 x update_interval)` of consecutive failures (ADR 0002).
- Update cadence is market-hours aware: 5 min during market hours, 30 min after (15 min in "Any" timezone mode); not user-configurable (ADR 0004).
- Rate limiting: 0.5 s between batched API calls and a 0-30 s random start stagger across entries.

## Configuration storage
- App Key and App Secret live in Home Assistant Application Credentials, not in the entry. The entry holds the OAuth token, `auth_implementation`, `entity_prefix` (Client ID) and the timezone; options hold `timezone` and `enable_position_sensors`.
- Tokens refresh proactively at half their lifetime. Reauthentication keeps the entry and must use the same Saxo account (ADR 0005).
- No sensitive data (tokens, client IDs, balances) in logs; diagnostics report field names only.
