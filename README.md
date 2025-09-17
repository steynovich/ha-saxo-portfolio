# Saxo Portfolio - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License](https://img.shields.io/github/license/steynovich/ha-saxo-portfolio.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/release/steynovich/ha-saxo-portfolio)](https://github.com/steynovich/ha-saxo-portfolio/releases)
[![HACS Action](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hacs.yml/badge.svg)](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hassfest.yml/badge.svg)](https://github.com/steynovich/ha-saxo-portfolio/actions/workflows/hassfest.yml)

A **Platinum-grade** Home Assistant integration for monitoring your Saxo Bank portfolio through their OpenAPI. Features OAuth 2.0 authentication, intelligent update scheduling based on market hours, automatic entity naming based on your Saxo Client ID, and comprehensive portfolio monitoring with six dedicated sensors.

## Features

- 🔐 **Enterprise-Grade Security**: OAuth 2.0 with Home Assistant credential management, encrypted token storage, and comprehensive data masking
- 💰 **Six Comprehensive Sensors**: Real-time balance, performance metrics, and cash transfer tracking from multiple Saxo API endpoints
- 🏷️ **Automatic Entity Naming**: Entity names auto-generated using your Saxo Client ID (e.g., `saxo_123456_cash_balance`)
- 🕒 **Intelligent Scheduling**: Configurable market timezone with dynamic update intervals (5 min during market hours, 30 min after hours)
- 📊 **Performance Analytics**: All-time profit/loss, investment returns, and cash transfer balance tracking
- 🏭 **Production Ready**: Uses production Saxo API endpoints for live data
- 🔄 **Robust API Handling**: Advanced rate limiting, exponential backoff, and automatic retry logic
- 🛡️ **Security-First Design**: CSRF protection, SSL certificate verification, and sanitized logging
- ✅ **HACS Compliant**: Comprehensive testing and GitHub Actions workflows
- 🏆 **Platinum Quality**: Meets Home Assistant Quality Scale Platinum tier with fully typed codebase and comprehensive documentation

## Supported Sensors

The integration provides **six comprehensive sensors** that automatically use your Saxo Client ID for unique entity naming:

### Balance & Portfolio Sensors
- **Cash Balance**: Available cash in your Saxo portfolio (`sensor.saxo_{clientid}_cash_balance`)
- **Total Value**: Total portfolio value including cash and investments (`sensor.saxo_{clientid}_total_value`)
- **Non-Margin Positions Value**: Value of non-margin trading positions (`sensor.saxo_{clientid}_non_margin_positions_value`)

### Performance & Transfer Analytics
- **Accumulated Profit/Loss**: All-time performance tracking from Saxo's historical API (`sensor.saxo_{clientid}_accumulated_profit_loss`)
- **Investment Performance**: Overall portfolio return percentage from performance timeseries (`sensor.saxo_{clientid}_investment_performance`)
- **Cash Transfer Balance**: Latest cash transfer value tracking deposits and withdrawals (`sensor.saxo_{clientid}_cash_transfer_balance`)

### Key Features
- **API Endpoints Used**: `/port/v1/balances/me`, `/port/v1/clients/me`, `/hist/v3/perf/`, `/hist/v4/performance/timeseries`
- **Currency Support**: Automatically detects and displays the appropriate currency unit
- **Performance Metrics**: Investment returns as percentage, cash transfer balance tracking
- **Client ID Integration**: Entity names automatically use your actual Saxo Client ID for unique identification

## Prerequisites

1. **Saxo Bank Account**: You need an active Saxo Bank account
2. **Developer Application**: Create an application in the [Saxo Developer Portal](https://www.developer.saxo/openapi/appmanagement)
3. **Home Assistant**: Version 2023.1 or later

## Installation

### Via HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed
2. Go to HACS → Integrations
3. Click the three dots menu → Custom repositories
4. Add `https://github.com/steynovich/ha-saxo-portfolio` as Integration
5. Search for "Saxo Portfolio" and install
6. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy `custom_components/saxo_portfolio/` to your Home Assistant `custom_components/` directory
3. Restart Home Assistant

## Configuration

### Step 1: Application Credentials

1. Go to Home Assistant Settings → Devices & Services → Application Credentials
2. Click "Add Credential" and select "Saxo Portfolio"
3. Enter your Saxo application credentials:
   - **Client ID**: Your App Key from Saxo Developer Portal
   - **Client Secret**: Your App Secret from Saxo Developer Portal

### Step 2: Add Integration

1. Go to Settings → Devices & Services
2. Click "Add Integration" and search for "Saxo Portfolio"
3. Follow the OAuth authentication flow with Saxo's production environment
4. Select your primary trading market timezone (or "Any" to disable intelligent scheduling)
5. The integration will automatically fetch your Client ID and create appropriately named entities

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| Market Timezone | Select your primary trading market for intelligent scheduling | America/New_York |
| Update Interval (Market Hours) | How often to fetch data during market hours | 5 minutes |
| Update Interval (After Hours) | How often to fetch data after market hours | 30 minutes |
| Update Interval (Any Mode) | Fixed interval when "Any" timezone is selected | 15 minutes |

### Supported Market Timezones
- **America/New_York**: NYSE/NASDAQ (9:30 AM - 4:00 PM ET)
- **Europe/London**: LSE (8:00 AM - 4:30 PM GMT/BST)
- **Europe/Amsterdam**: Euronext (9:00 AM - 5:30 PM CET/CEST)
- **Europe/Paris**: Euronext (9:00 AM - 5:30 PM CET/CEST)
- **Europe/Frankfurt**: XETRA (9:00 AM - 5:30 PM CET/CEST)
- **Asia/Tokyo**: TSE (9:00 AM - 3:00 PM JST)
- **Asia/Hong_Kong**: HKEX (9:30 AM - 4:00 PM HKT)
- **Asia/Singapore**: SGX (9:00 AM - 5:00 PM SGT)
- **Australia/Sydney**: ASX (10:00 AM - 4:00 PM AEDT/AEST)
- **Any**: Disable intelligent scheduling (fixed 15-minute intervals)

**Note**: Entity prefixes are now automatically generated using your Saxo Client ID, eliminating the need for manual configuration. You can change the market timezone at any time through the integration options.

## Entities Created

The integration automatically creates **ten entities** using your Saxo Client ID:

### Portfolio Sensors (Example: Client ID "123456")
- `sensor.saxo_123456_cash_balance` - Available cash balance
- `sensor.saxo_123456_total_value` - Total portfolio value
- `sensor.saxo_123456_non_margin_positions_value` - Non-margin positions value
- `sensor.saxo_123456_accumulated_profit_loss` - All-time profit/loss performance
- `sensor.saxo_123456_investment_performance` - Overall portfolio return percentage
- `sensor.saxo_123456_cash_transfer_balance` - Latest cash transfer balance

### Diagnostic Sensors (Example: Client ID "123456")
- `sensor.saxo_123456_token_expiry` - OAuth token expiration countdown and status
- `sensor.saxo_123456_market_status` - Current market status (Open/Closed/Fixed Schedule)
- `sensor.saxo_123456_last_update` - Last successful data update timestamp
- `sensor.saxo_123456_timezone` - Configured timezone and market hours settings

### Entity Attributes
- **Currency**: Portfolio currency (EUR, USD, etc.) - automatically detected
- **Cross-Reference**: Sensors include related values for context
- **Last Updated**: Timestamp of last data refresh
- **Performance Metrics**: Historical profit/loss and return calculations
- **Attribution**: Data source identification

## Security & Privacy

This integration implements enterprise-grade security practices:

- **🔐 Authentication**: OAuth 2.0 with Home Assistant's secure credential management system
- **🔒 Token Security**: Encrypted storage with automatic refresh and proper expiration handling  
- **🌐 Network Security**: Mandatory HTTPS with explicit SSL certificate verification
- **📝 Data Protection**: Comprehensive sensitive data masking in all log outputs
- **🛡️ CSRF Protection**: Cryptographically secure state parameters using `secrets.token_urlsafe(32)`
- **🚫 Information Leakage Prevention**: Sanitized error messages that never expose credentials or sensitive data
- **⏰ Rate Limiting**: Intelligent API throttling with server-side and client-side protection
- **📋 Compliance**: Follows Home Assistant security guidelines and best practices

See [SECURITY.md](SECURITY.md) for comprehensive security documentation and user guidelines.

## Market Hours Detection

The integration intelligently adjusts update frequency based on your configured market timezone:
- **Market Hours**: Updates every 5 minutes when your selected market is open
- **After Hours**: Updates every 30 minutes when your selected market is closed
- **"Any" Mode**: Fixed 15-minute updates regardless of time (no market hours detection)

The integration automatically handles daylight saving time transitions for all supported markets.

## Troubleshooting

### Common Issues

**Authentication Failed**
- Verify your application credentials in the Saxo Developer Portal
- Ensure redirect URI is set to: `https://my.home-assistant.io/redirect/oauth`
- Check if your Saxo application has appropriate permissions

**Rate Limit Errors**
- The integration automatically handles rate limiting with exponential backoff
- Consider reducing update frequency if you have other applications using the same credentials

**Missing Data**
- Ensure your Saxo account has the required permissions for portfolio data
- Verify your production application credentials are correctly configured

### Diagnostic Information

The integration provides comprehensive diagnostic sensors and data to help troubleshoot issues:

**Diagnostic Sensors**: Monitor integration health in real-time
- **Token Expiry**: Shows countdown to token expiration with status indicators (OK/WARNING/CRITICAL/EXPIRED)
- **Market Status**: Displays current market state (Open/Closed) and update intervals
- **Last Update**: Timestamp of the last successful data refresh
- **Timezone**: Shows configured timezone and market hours settings

**Built-in Diagnostics**: Available via Settings → Devices & Services → Saxo Portfolio → Download Diagnostics
- Timezone configuration and market hours detection
- Token expiry information with human-readable timestamps
- Coordinator status and update intervals
- Data availability and error information
- All sensitive information automatically redacted

### Enable Debug Logging

Add to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.saxo_portfolio: debug
```

## API Limits

The integration respects Saxo's API limits:
- Maximum 120 requests per minute
- Intelligent rate limiting with server-side backoff
- Automatic retry with exponential backoff on errors

## Development & Quality Assurance

This integration maintains high code quality standards with comprehensive CI/CD:

### 🚀 **GitHub Actions Workflows**
- **HACS Validation**: Ensures repository meets HACS standards for publication
- **Hassfest**: Validates Home Assistant integration compliance and manifest structure
- **Automated Testing**: Multi-version Python testing (3.11, 3.12) with dependency management
- **Code Quality**: Linting, formatting, and type checking with Ruff and MyPy

### 🧪 **Testing Framework**
- **Structure Tests**: Repository structure and configuration validation
- **Contract Tests**: API contract compliance and data validation
- **Integration Tests**: End-to-end functionality testing
- **Security Tests**: Credential handling and data masking verification

### 📊 **Code Quality Metrics**
- **372+ Linting Issues Resolved**: Comprehensive code cleanup and standardization
- **Modern Type Annotations**: Full typing coverage for better IDE support and reliability
- **Security-Focused**: Sanitized logging and secure data handling patterns
- **Home Assistant Best Practices**: Follows official integration development guidelines

### 🔧 **Development Setup**
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

## Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/steynovich/ha-saxo-portfolio/issues)
- 💡 **Feature Requests**: [GitHub Issues](https://github.com/steynovich/ha-saxo-portfolio/issues)
- 📖 **Documentation**: [Saxo OpenAPI Docs](https://www.developer.saxo/openapi/learn)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This integration is not officially affiliated with Saxo Bank. Use at your own risk. Always verify financial data from official Saxo Bank sources before making investment decisions.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and changes.