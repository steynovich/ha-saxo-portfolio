# Saxo Portfolio - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License](https://img.shields.io/github/license/steynovich/ha-saxo-portfolio.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/release/steynovich/ha-saxo-portfolio)](https://github.com/steynovich/ha-saxo-portfolio/releases)
[![HACS Action](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hacs.yml/badge.svg)](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hassfest.yml/badge.svg)](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hassfest.yml)

A Home Assistant integration that monitors your Saxo Bank portfolio through the Saxo OpenAPI. It meets the Platinum tier of the Home Assistant Quality Scale. It signs in with OAuth 2.0, updates more often while your market is open, and names entities after your Saxo Client ID. You get eleven portfolio sensors, up to eight diagnostic sensors, a manual refresh button and a reauthenticate button.

## Features

- OAuth 2.0 sign-in through Home Assistant's Application Credentials, with encrypted token storage and sensitive values masked in logs.
- Eleven portfolio sensors for balances, performance and cash transfers, fed by several Saxo API endpoints.
- Eight diagnostic sensors for integration health, account identification, token expiry and market status. Seven are always present; Market Data Access is added when position sensors are enabled.
- Performance data is cached for 2 hours, while balance data follows the normal update schedule, to keep API usage down.
- Performance sensors record Home Assistant long-term statistics, so you can track trends over time.
- Entity IDs include your Saxo Client ID (e.g. `saxo_123456_cash_balance`).
- A configurable market timezone sets the update interval: 5 minutes during market hours, 30 minutes after hours.
- A refresh button entity and a `saxo_portfolio.refresh_data` service for on-demand updates.
- Tracks all-time profit/loss, investment returns and the cash transfer balance.
- Uses Saxo's production API endpoints for live data.
- Rate limiting, exponential backoff and automatic retries for API calls.
- CSRF protection, SSL certificate verification and sanitized logging.
- Passes HACS validation, with tests and checks running in GitHub Actions.
- Fully typed codebase.

## Supported sensors

The integration creates eleven sensors, each with your Saxo Client ID in its entity ID:

### Balance and portfolio sensors
- **Cash Balance**: available cash in your Saxo portfolio (`sensor.saxo_{clientid}_cash_balance`)
- **Total Value**: total portfolio value, cash plus investments (`sensor.saxo_{clientid}_total_value`)
- **Non-Margin Positions Value**: value of non-margin trading positions (`sensor.saxo_{clientid}_non_margin_positions_value`)

### Performance and transfer sensors
- **Accumulated Profit/Loss**: all-time profit/loss from Saxo's historical API (`sensor.saxo_{clientid}_accumulated_profit_loss`)
- **Investment Performance**: all-time portfolio return percentage from the performance timeseries (`sensor.saxo_{clientid}_investment_performance`)
- **YTD Investment Performance**: year-to-date portfolio return percentage (`sensor.saxo_{clientid}_ytd_investment_performance`)
- **Month Investment Performance**: portfolio return percentage over a rolling ~28 days. Despite the name, it is not aligned to the calendar month (`sensor.saxo_{clientid}_month_investment_performance`)
- **Quarter Investment Performance**: portfolio return percentage over a rolling ~90 days. Despite the name, it is not aligned to the calendar quarter (`sensor.saxo_{clientid}_quarter_investment_performance`)
- **Cash Transfer Balance**: latest cash transfer value, tracking deposits and withdrawals (`sensor.saxo_{clientid}_cash_transfer_balance`)
- **YTD Profit/Loss**: year-to-date profit/loss in your account currency (`sensor.saxo_{clientid}_ytd_profit_loss`)
- **YTD Net Transfers**: year-to-date net deposits and withdrawals (`sensor.saxo_{clientid}_ytd_cash_transfer`)

**Long-term statistics**: all performance sensors use `state_class: measurement`, so Home Assistant keeps long-term statistics for them. That gives you:
- history beyond the default 10-day recorder purge period
- trend graphs in the History and Energy panels
- min, max and mean values
- support for negative values as well as positive ones

**YTD Net Transfers reset**: the YTD Net Transfers sensor uses `state_class: total` with a `last_reset` anchored to 1 January (00:00 local time) of the current year. Its source window starts on 1 January, so the value returns to zero at the start of each year and long-term statistics start a new cycle at that point.

### Data sources
- **API endpoints used**: `/port/v1/balances/me`, `/port/v1/clients/me`, `/port/v1/accounts/{AccountKey}`, `/hist/v3/perf/`, `/hist/v4/performance/timeseries`
- **Currency**: the unit is taken from your account currency
- **Performance metrics**: investment returns as a percentage (all-time and YTD) and the cash transfer balance
- **Caching**: performance and account data are cached for 2 hours to reduce API calls; balance data is not cached
- **Client ID**: entity names use your Saxo Client ID so every account gets unique entities

## Prerequisites

1. **Saxo Bank account**: you need an active Saxo Bank account
2. **Developer application**: create an application in the [Saxo Developer Portal](https://www.developer.saxo/openapi/appmanagement)
3. **Home Assistant**: version 2026.3 or later (the first release that runs on Python 3.14, which this integration requires)

## Installation

### Via HACS (recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed
2. Go to HACS → Integrations
3. Click the three dots menu → Custom repositories
4. Add `https://github.com/steynovich/ha-saxo-portfolio` as Integration
5. Search for "Saxo Portfolio" and install
6. Restart Home Assistant

### Manual installation

1. Download the latest release
2. Copy `custom_components/saxo_portfolio/` to your Home Assistant `custom_components/` directory
3. Restart Home Assistant

## Configuration

### Step 1: Application credentials

1. Go to Home Assistant Settings → Devices & Services → Application Credentials
2. Click "Add Credential" and select "Saxo Portfolio"
3. Enter your Saxo application credentials:
   - **Client ID**: your App Key from the Saxo Developer Portal
   - **Client Secret**: your App Secret from the Saxo Developer Portal

### Step 2: Add the integration

1. Go to Settings → Devices & Services
2. Click "Add Integration" and search for "Saxo Portfolio"
3. Complete the OAuth sign-in with Saxo's production environment
4. Select the timezone of your main trading market (or "Any" to turn off market-hours scheduling)
5. The integration fetches your Client ID and creates the entities

### Reauthentication

When your tokens expire, Home Assistant shows a **Reauthenticate** prompt for the entry. You can also start it yourself by pressing the **Reauthenticate** button on the device (`button.saxo_123456_reauthenticate`), or via the entry's menu → **Reconfigure**. Until you sign in again, the integration keeps using the current token. Sign in again and the new token is stored on the existing entry. Your settings, entities, history and automations stay as they are.

Reauthentication must use the **same Saxo account** the entry was created with. The integration checks the account you signed in with against the entry. If it is a different account, reauthentication is aborted with an "account mismatch" message and the entry is left unchanged. To monitor another Saxo account, add it as a new integration entry.

## Configuration options

Open **Settings → Devices & Services → Saxo Portfolio → Configure** to change these options:

| Option | Description | Default |
|--------|-------------|---------|
| Market Timezone | The trading market whose hours set the update interval | America/New_York |
| Enable Position Sensors | Create one sensor per open position (current price, market value, profit/loss attributes) | Off |

Update intervals are not configurable: balance data refreshes every 5 minutes during market hours and every 30 minutes after hours (every 15 minutes in "Any" mode), and performance data is cached for 2 hours. See [Market hours detection](#market-hours-detection).

### Reconfigure (re-authenticate)

To sign in to Saxo again without removing the integration, open **Settings → Devices & Services → Saxo Portfolio**, click the three-dot menu and select **Reconfigure**. This runs the OAuth flow again and refreshes your tokens. Settings, entity history and automations are kept.

### Supported market timezones
- **America/New_York**: NYSE/NASDAQ (9:30 AM - 4:00 PM ET)
- **Europe/London**: LSE (8:00 AM - 4:30 PM GMT/BST)
- **Europe/Amsterdam**: Euronext (9:00 AM - 5:30 PM CET/CEST)
- **Europe/Paris**: Euronext (9:00 AM - 5:30 PM CET/CEST)
- **Europe/Berlin**: XETRA (9:00 AM - 5:30 PM CET/CEST)
- **Asia/Tokyo**: TSE (9:00 AM - 3:00 PM JST)
- **Asia/Hong_Kong**: HKEX (9:30 AM - 4:00 PM HKT)
- **Asia/Singapore**: SGX (9:00 AM - 5:00 PM SGT)
- **Australia/Sydney**: ASX (10:00 AM - 4:00 PM AEDT/AEST)
- **Any**: no market-hours scheduling (fixed 15-minute intervals)

Entity prefixes come from your Saxo Client ID, so there is nothing to configure for them. You can change the market timezone at any time in the integration options.

## Entities created

The integration creates **twenty entities**, named with your Saxo Client ID: eleven portfolio sensors, seven diagnostic sensors, a refresh button and a reauthenticate button. Enabling position sensors adds the Market Data Access diagnostic sensor (eight diagnostic sensors in total) plus one sensor per open position.

### Portfolio sensors (example: Client ID "123456")
- `sensor.saxo_123456_cash_balance` - Available cash balance
- `sensor.saxo_123456_total_value` - Total portfolio value
- `sensor.saxo_123456_non_margin_positions_value` - Non-margin positions value
- `sensor.saxo_123456_accumulated_profit_loss` - All-time profit/loss
- `sensor.saxo_123456_investment_performance` - All-time portfolio return percentage
- `sensor.saxo_123456_ytd_investment_performance` - Year-to-date portfolio return percentage
- `sensor.saxo_123456_month_investment_performance` - Trailing 28-day portfolio return percentage (Saxo's `StandardPeriod=Month`; not calendar month-to-date)
- `sensor.saxo_123456_quarter_investment_performance` - Trailing 90-day portfolio return percentage (Saxo's `StandardPeriod=Quarter`; not calendar quarter-to-date)
- `sensor.saxo_123456_cash_transfer_balance` - Latest cash transfer balance
- `sensor.saxo_123456_ytd_profit_loss` - Year-to-date profit/loss
- `sensor.saxo_123456_ytd_cash_transfer` - Year-to-date net deposits and withdrawals

### Diagnostic sensors (example: Client ID "123456")
- `sensor.saxo_123456_client_id` - Saxo Client ID, for troubleshooting
- `sensor.saxo_123456_account_id` - Saxo Account ID from the account details API
- `sensor.saxo_123456_name` - Client name from the client details API
- `sensor.saxo_123456_token_expiry` - OAuth token expiry status (seconds remaining in the `expires_in_seconds` attribute)
- `sensor.saxo_123456_market_status` - Current market status
- `sensor.saxo_123456_last_update` - Time of the last successful data update
- `sensor.saxo_123456_timezone` - Configured timezone and market hours
- `sensor.saxo_123456_market_data_access` - Whether the API has real-time market data access (only created when position sensors are enabled)

#### Diagnostic sensor states
Market Status, Token Expiry and Market Data Access are enum sensors. Their states are fixed values, which Home Assistant shows translated into your language. Automations and templates should match on these values:

| Sensor | States |
|---|---|
| Market Status | `market_open`, `after_hours`, `fixed_schedule` |
| Token Expiry | `valid`, `warning` (≤ 5 minutes left), `critical` (≤ 1 minute left), `expired` |
| Market Data Access | `available`, `not_available` |

A sensor whose status cannot be determined reports Home Assistant's standard `unknown` state.

> **Breaking change in 2.9.0:** before 2.9.0 (and up to 2.9.0-beta.4) these sensors reported English text such as `Market Open`, `After Hours`, `Fixed Schedule`, `Critical - < 1 minute`, `Warning - 4.2 minutes`, `45 minutes`, `2.3 hours`, `Available`, `Unavailable` and `Unknown`. Automations or templates matching the old strings must be updated to the values above.

### Buttons (example: Client ID "123456")
- `button.saxo_123456_refresh` - Refresh portfolio data now (configuration entity)
- `button.saxo_123456_reauthenticate` - Start reauthentication with Saxo (configuration entity); see [Reauthentication](#reauthentication)

### Entity attributes
- **Currency**: portfolio currency (EUR, USD, etc.), taken from the account
- **Last Updated**: time of the last data refresh. Balance sensors use the balance API timestamp, performance sensors the performance API timestamp
- **Time Period**: performance sensors have a `time_period` attribute naming the window the value covers:
  - Investment Performance: `AllTime` (the `StandardPeriod=AllTime` API window)
  - YTD Investment Performance: `YearToDate`, an explicit window from 1 January to today (Saxo's `StandardPeriod=Year` is a trailing 12 months, so it is not used)
  - Month Investment Performance: `Month` (the `StandardPeriod=Month` API window, a trailing 28 days)
  - Quarter Investment Performance: `Quarter` (the `StandardPeriod=Quarter` API window, a trailing 90 days)
- **From/Thru Dates**: performance sensors have `from`/`thru` dates for the window the value was computed over: `inception` to today for all-time, 1 January to today for YTD, and for Month/Quarter the trailing 28/90 days ending yesterday (the last completed day)
- **Performance Metrics**: historical profit/loss and returns, labelled with their time period
- **Attribution**: the data source

## Security and privacy

- **Authentication**: OAuth 2.0 Authorization Code Grant as a confidential client, with the App Secret kept in Home Assistant's Application Credentials. PKCE is not used because Saxo offers it only as a separate grant for apps without a secret; see [SECURITY.md](SECURITY.md)
- **Tokens**: stored encrypted, refreshed automatically, with expiry handled
- **Network**: HTTPS only, with explicit SSL certificate verification
- **Logging**: sensitive data is masked in all log output
- **CSRF protection**: state parameters generated with `secrets.token_urlsafe(32)`
- **Error messages**: sanitized so they never expose credentials or other sensitive data
- **Rate limiting**: API calls are throttled on the client side, and the integration backs off when Saxo's server signals a limit
- **Guidelines**: follows the Home Assistant security guidelines

See [SECURITY.md](SECURITY.md) for the full security documentation and user guidelines.

## Market hours detection

How often data updates depends on the market timezone you configured and on the type of data.

### Balance data
- **Market hours**: every 5 minutes while your selected market is open
- **After hours**: every 30 minutes while your selected market is closed
- **"Any" mode**: every 15 minutes, whatever the time (no market-hours detection)

### Performance data (cached)
- All performance sensors update every 2 hours, regardless of market hours
- This covers investment performance, YTD performance, accumulated profit/loss and cash transfers
- These figures change slowly, so caching them saves API calls without leaving them noticeably stale

Daylight saving time transitions are handled for all supported markets.

### Data update strategy

| Data Type | Update Interval | Source |
|-----------|----------------|--------|
| Cash balance, total value | 5 min (market hours) / 30 min (after hours) | `/port/v1/balances/me` |
| Performance metrics (all-time, YTD, month, quarter) | 2 hours (cached) | `/hist/v4/performance/timeseries` |
| Accumulated profit/loss | 2 hours (cached) | `/hist/v3/perf/` |
| Client/account details | 2 hours (cached) | `/port/v1/clients/me` |
| Position data (opt-in) | Same as balance | `/port/v1/netpositions/me` |

One coordinator fetches all data. Balance refreshes drive the updates; performance and position data are fetched along with them but cached separately to reduce API load.

### Manual refresh

- **Refresh button** (`button.saxo_123456_refresh`): press it to fetch data immediately for that account.
- **`saxo_portfolio.refresh_data` service**: refreshes every loaded Saxo Portfolio account at once, or only one when you pass the optional `config_entry_id`. You can call it from automations or scripts. Calling it when no matching account is loaded raises an error.

A manual refresh fetches balance data straight away. Performance data still honours its 2-hour cache and is only fetched again once that cache has expired.

## Troubleshooting

### Common issues

**Authentication failed**
- Check your application credentials in the Saxo Developer Portal
- Make sure the redirect URI is set to: `https://my.home-assistant.io/redirect/oauth`
- Check that your Saxo application has the right permissions

**Rate limit errors**
- The integration handles rate limiting itself, with exponential backoff
- Update intervals are fixed. If other applications use the same credentials, their calls count toward the same rate limit

**Missing data**
- Make sure your Saxo account has the permissions needed for portfolio data
- Check that your production application credentials are configured correctly

### Diagnostic information

**Diagnostic sensors** show the integration's health as it runs:
- **Client ID**: the Saxo Client ID used for entity naming and troubleshooting
- **Account ID**: the Account ID from the account details API, useful for telling accounts apart
- **Display Name**: the account display name from the account details API
- **Token Expiry**: token status (`valid`, `warning`, `critical` or `expired`), with the seconds remaining in an attribute
- **Market Status**: the current market state (`market_open`, `after_hours` or `fixed_schedule`) and update intervals
- **Last Update**: time of the last successful data refresh
- **Timezone**: the configured timezone and market hours
- **Market Data Access**: whether the API has real-time market data access (only created when position sensors are enabled)

**Built-in diagnostics**: download them via Settings → Devices & Services → Saxo Portfolio → Download Diagnostics. They include:
- timezone configuration and market hours detection
- token expiry information with readable timestamps
- coordinator status and update intervals
- data availability and error information

Sensitive information is redacted automatically.

### Enable debug logging

Add to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.saxo_portfolio: debug
```

## API limits

Saxo allows at most 120 requests per minute. The integration stays within that limit: it backs off when the server asks it to, and retries failed requests with exponential backoff.

## Development and quality assurance

### GitHub Actions workflows
- **HACS validation**: checks that the repository meets HACS publication requirements
- **Hassfest**: validates the integration and its manifest against Home Assistant's rules
- **Tests**: the full pytest suite on Python 3.14, installed from the locked dependency set
- **Code quality**: linting and formatting with Ruff, type checking with MyPy

### Tests
- **Structure tests**: repository structure and configuration
- **Contract tests**: API contract compliance and data validation
- **Integration tests**: end-to-end behaviour
- **Security tests**: credential handling and data masking

### Code quality
- Type annotations throughout the codebase
- Sanitized logging and careful handling of sensitive data
- Follows the official Home Assistant integration development guidelines

### Development setup
```bash
# Clone the repository
git clone https://github.com/steynovich/ha-saxo-portfolio.git
cd ha-saxo-portfolio

# Set up development environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -e ".[dev]"

# Run tests
pytest tests/
ruff check .
ruff format .
```

## Uninstallation

1. Go to **Settings → Devices & Services → Saxo Portfolio**
2. Click the three-dot menu and select **Delete**
3. If installed via HACS: go to **HACS → Integrations → Saxo Portfolio → Remove**
4. Restart Home Assistant

## Use cases

- **Portfolio dashboard**: a Lovelace dashboard with your cash balance, total portfolio value and performance figures
- **Market-hours notifications**: automations that fire when the market opens or closes, using the Market Status sensor
- **Performance tracking**: long-term statistics show how your investment performance changes over weeks and months
- **Token monitoring**: an alert before your OAuth token expires, so you can re-authenticate in time

## Automation examples

### Alert on significant portfolio drop
```yaml
automation:
  - alias: "Portfolio value drop alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.saxo_123456_total_value
        below: 100000
    action:
      - service: notify.mobile_app
        data:
          title: "Portfolio Alert"
          message: "Portfolio value dropped below €100,000"
```

### Notify on token expiry warning
```yaml
automation:
  - alias: "Saxo token expiry warning"
    trigger:
      - platform: state
        entity_id: sensor.saxo_123456_token_expiry
    condition:
      - condition: state
        entity_id: sensor.saxo_123456_token_expiry
        state: "warning"
    action:
      - service: notify.mobile_app
        data:
          title: "Saxo Token Expiring"
          message: "Your Saxo OAuth token is expiring soon. Please re-authenticate."
```

## Known limitations

- **Production API only**: the integration uses Saxo's production OpenAPI endpoints. Simulation/demo accounts are not supported.
- **No trading**: the integration is read-only. It cannot place orders or change positions.
- **Refresh token lifetime**: Saxo refresh tokens expire after 24 hours. If Home Assistant is offline for longer, you'll need to re-authenticate.
- **One account per entry**: each config entry monitors one Saxo account. Add the integration again for each extra account.
- **Market data subscription**: real-time position prices need a market data subscription on your Saxo account. Without one, position prices may be delayed or unavailable.
- **Performance data delay**: historical performance figures are cached for 2 hours, so the most recent trades may not show up right away.

## Support

- **Bug reports**: [GitHub Issues](https://github.com/steynovich/ha-saxo-portfolio/issues)
- **Feature requests**: [GitHub Issues](https://github.com/steynovich/ha-saxo-portfolio/issues)
- **Documentation**: [Saxo OpenAPI Docs](https://www.developer.saxo/openapi/learn)

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Disclaimer

This integration is not officially affiliated with Saxo Bank. Use at your own risk. Always check financial data against official Saxo Bank sources before making investment decisions.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and changes.
