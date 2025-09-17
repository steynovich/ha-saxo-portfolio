# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.1] - 2025-09-17

### Fixed
- **Options Flow Deprecation**: Removed explicit `self.config_entry = config_entry` assignment in options flow handler to fix Home Assistant 2025.12 deprecation warning

## [2.1.0] - 2025-09-17

### Added
- **Diagnostics Support**: Comprehensive diagnostic information for debugging and support
  - Timezone configuration and market hours settings
  - Detailed token expiry information with human-readable timestamps
  - Coordinator status and update intervals
  - Market hours detection status
  - Dynamic version reading from manifest.json
- **Diagnostic Sensors**: Four dedicated diagnostic entities for real-time monitoring
  - Token Expiry sensor with countdown and status indicators
  - Market Status sensor showing current market state
  - Last Update sensor with timestamp tracking
  - Timezone sensor displaying configuration details

### Enhanced
- **Token Diagnostics**: Comprehensive expiry tracking with status indicators (OK/WARNING/CRITICAL/EXPIRED)
- **Market Configuration**: Clear visibility into configured timezone and update intervals
- **Security**: All sensitive data automatically redacted in diagnostics

### Fixed (from beta.2)
- **Token Refresh**: Added redirect_uri to config entry to fix OAuth token refresh failures
- **State Class**: Changed accumulated profit/loss sensor state_class from 'measurement' to 'total' for proper Home Assistant compatibility

### Added (from beta.1)
- **Configurable Market Timezone**: Select from 9 major market timezones for intelligent scheduling
- **"Any" Mode**: Option to disable market hours detection with fixed 15-minute update intervals
- **Options Flow**: Change timezone configuration after initial setup through integration options
- **Global Market Support**: NYSE, LSE, Euronext, XETRA, TSE, HKEX, SGX, ASX markets
- **Timezone Selection Step**: New configuration step during initial setup to select market timezone

### Enhanced
- **Intelligent Scheduling**: Dynamic update intervals based on selected market hours
- **Backward Compatibility**: Default timezone set to America/New_York for existing installations
- **Market Hours Detection**: Automatic DST handling for all supported timezones
- **Update Intervals**: 5 min (market hours), 30 min (after hours), 15 min ("any" mode)

### Technical Improvements
- Added comprehensive timezone constants and market hours configuration
- Updated coordinator to use configurable timezone instead of hardcoded ET
- Enhanced config flow with timezone selection and options flow handler
- Added UI strings for timezone configuration in strings.json

## [2.0.3] - 2025-09-12

### Added
- **Investment Performance Sensor**: New sensor tracking overall portfolio return percentage from `/hist/v4/performance/timeseries` endpoint
- **Cash Transfer Balance Sensor**: New sensor showing latest cash transfer value from performance timeseries data
- **Enhanced API Coverage**: Added v4 performance endpoint support alongside existing v3 endpoint

### Enhanced
- **Comprehensive Portfolio Monitoring**: Now provides 6 sensors covering all key portfolio metrics
- **Performance Analytics**: ReturnFraction data converted to percentage for easy interpretation
- **Historical Data Integration**: Cash transfer tracking from timeseries performance data

### Technical Improvements
- Added `get_performance_v4()` method to API client for v4 performance endpoint
- Enhanced coordinator with investment performance and cash transfer data fetching
- Improved sensor naming consistency with client_id integration
- All code validated with ruff formatting and quality checks

### Sensor Updates
- Total sensors increased from 4 to 6:
  - Cash Balance (existing)
  - Total Value (existing) 
  - Non-Margin Positions Value (existing)
  - Accumulated Profit/Loss (existing)
  - Investment Performance (new)
  - Cash Transfer Balance (new)

## [2.0.0] - 2025-09-11

### Breaking Changes
- **Automatic Entity Naming**: Entity prefixes now automatically use Saxo Client ID (e.g., `saxo_123456_cash_balance`)
- **Removed Options Flow**: No longer configurable entity prefixes - all entities use `saxo_{clientid}` format
- **Removed Cash Deposit Sensor**: Streamlined to 4 core sensors for better focus on available data

### Added
- **Client ID Integration**: Automatically fetches Client ID from `/port/v1/clients/me` endpoint
- **Performance Analytics**: Added all-time profit/loss tracking via `/hist/v3/perf/` endpoint
- **Non-Margin Positions**: Added sensor for non-margin trading positions value
- **Accumulated Profit/Loss**: Historical performance tracking with BalancePerformance data

### Enhanced
- **Simplified Setup**: No configuration needed - entities automatically named using your Saxo Client ID
- **Better API Coverage**: Now uses 3 Saxo endpoints for comprehensive portfolio data
- **Streamlined Sensors**: Focused on 4 core sensors that provide meaningful data
- **Unique Entity IDs**: Each Saxo client gets unique entity names preventing conflicts

### Technical Improvements
- Removed problematic accounts endpoint dependency
- Cleaner API client with focused endpoint usage
- Simplified configuration flow without user input requirements
- Enhanced error handling for client details retrieval

### Removed
- Custom entity prefix configuration (now automatic)
- Cash deposit sensor (was returning 0.0 without proper data source)
- Options flow for prefix changes
- Manual entity naming system

## [1.0.1] - 2025-09-10

### Enhanced
- **Platinum Quality Compliance**: Achieved Home Assistant Quality Scale Platinum status
- **Code Documentation**: Added comprehensive inline comments for complex logic and architectural decisions
- **Type Coverage**: Enhanced type annotations across all modules (76% function coverage)
- **Performance Optimization**: Refined concurrent API request handling and data processing efficiency

### Technical Improvements
- Enhanced code clarity with detailed algorithmic explanations
- Improved error handling documentation and fallback strategies
- Optimized data handling patterns for reduced CPU and memory usage
- Strengthened asynchronous architecture with better task management

## [1.0.0] - 2025-09-10

### Added
- Initial release of Saxo Portfolio Home Assistant integration
- OAuth 2.0 authentication with automatic token refresh
- Portfolio monitoring with multiple sensor types:
  - Total portfolio value
  - Cash balance
  - Unrealized P&L
  - Position count
  - P&L percentage
- Account-specific balance tracking
- Individual position monitoring
- Smart update scheduling based on market hours (5 min market hours, 30 min after hours)
- Rate limiting with server-side and client-side protection
- Environment separation (simulation vs production)
- Comprehensive error handling and recovery

### Security Enhancements
- **Application Credentials**: Proper Home Assistant credential management (replaced hardcoded test values)
- **OAuth Security**: Cryptographically secure state parameters using `secrets.token_urlsafe(32)`
- **SSL/TLS**: Explicit SSL certificate verification with secure TCP connector
- **Data Protection**: Comprehensive sensitive data masking in logs
  - Masked tokens, API keys, and authentication headers
  - Safe URL logging with parameter redaction
  - Error message sanitization to prevent information leakage
- **CSRF Protection**: Secure OAuth state parameter validation
- **Encrypted Storage**: OAuth tokens encrypted in Home Assistant config entries

### Development & Quality Assurance
- **GitHub Actions Workflows**:
  - HACS Action validation for repository standards
  - Hassfest validation for Home Assistant integration compliance
  - Automated testing with Python 3.11/3.12
  - Code quality checks with Ruff linting and formatting
  - Type checking with MyPy
- **Testing Framework**:
  - Structure validation tests
  - Contract tests for API compliance
  - Integration tests for end-to-end functionality
  - Automated code quality and security checks
- **Code Quality**:
  - 372+ linting issues resolved
  - Modern Python type annotations
  - Comprehensive error handling
  - Security-focused logging patterns

### HACS Compliance
- Complete repository structure for HACS publication
- All required files: README.md, LICENSE, CHANGELOG.md, hacs.json
- Proper manifest.json configuration
- GitHub Actions for continuous validation
- Security documentation (SECURITY.md)

### Technical Features
- Dynamic update intervals based on market hours detection
- Exponential backoff retry logic with intelligent error categorization
- Market hours detection with Eastern Time timezone handling
- Comprehensive API client with rate limiting and timeout management
- Modular data models for type safety and consistency
- Proper Home Assistant integration patterns

[2.1.1]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.1
[2.1.0]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.0
[2.0.3]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.0.3
[2.0.0]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.0.0
[1.0.1]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v1.0.1
[1.0.0]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v1.0.0