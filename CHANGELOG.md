# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.1.9] - 2025-09-18

### Enhanced
- **Documentation Updates**: Updated project documentation with correct dates and current state
  - Refreshed CLAUDE.md development guidelines with current implementation status
  - Updated changelog with proper release version and date formatting
  - Enhanced technical documentation for better developer onboarding

### Technical Improvements
- Improved documentation accuracy and consistency across project files
- Enhanced development environment setup instructions
- Updated project status and implementation details

## [2.1.8] - 2025-09-18

### Fixed
- **Unclosed Client Session During Token Refresh**: Enhanced fix for memory leak from unclosed aiohttp sessions
  - Improved api_client property with safer old client closure handling
  - Added dedicated `_close_old_client()` method with proper error handling and logging
  - Enhanced token comparison logic to detect when client needs recreation
  - Uses async_create_task to properly close old client sessions during token refresh
  - Eliminates "Unclosed client session" errors during OAuth token refresh cycles
  - Prevents memory leaks and improves resource management with comprehensive error handling

## [2.1.7] - 2025-01-18

### Fixed
- **Options Flow Deprecation Warning**: Fixed deprecated config_entry assignment for Home Assistant 2025.12 compatibility
  - Replaced manual config_entry assignment with dynamic property retrieval
  - Updated SaxoOptionsFlowHandler to use modern Home Assistant pattern
  - Resolves deprecation warning: "sets option flow config_entry explicitly"
  - Ensures compatibility with future Home Assistant versions

## [2.1.6] - 2025-09-18

### Fixed
- **Performance Sensor Inception Date Issue**: Resolved misleading inception date display
  - Removed hardcoded "2020-01-01" fallback that was showing incorrect inception dates for all performance sensors
  - Removed `inception_day` attribute entirely as the required API FieldGroups are not available in the timeseries endpoint
  - Validated against Saxo API specifications - `InceptionDay` field is only available in `/hist/v4/performance/summary` endpoint
  - AllTime performance sensors now show generic "inception" indicator instead of specific dates
  - Prevents display of misleading dates while maintaining sensor functionality

### Improved
- **Major Sensor Architecture Optimization**: Implemented shared base class hierarchy
  - Reduced code duplication by 31% (from 1,472+ lines to 1,017 lines)
  - Created `SaxoSensorBase` for common functionality across all sensors
  - Created `SaxoBalanceSensorBase` for monetary balance sensors with currency handling
  - Created `SaxoDiagnosticSensorBase` for diagnostic sensors with proper categorization
  - Enhanced `SaxoPerformanceSensorBase` to inherit from `SaxoSensorBase`
  - Maintained all existing functionality while improving maintainability
- **Enhanced Sensor Availability During Updates**: Fixed sensors briefly showing as unavailable during coordinator updates
  - Implemented "sticky availability" logic that keeps sensors available during normal update cycles
  - Sensors only become unavailable after sustained failures (15+ minutes or 3 failed update cycles)
  - Prevents UI flashing and maintains stable sensor states during API fetches
  - Graceful handling of startup scenarios and genuine failures
  - Enhanced availability logic in all sensor base classes
- **Device Info Cleanup**: Removed firmware version from device information display
  - Explicitly set `sw_version=None` in `DeviceInfo` to prevent automatic version display
  - Cleaner device presentation in Home Assistant UI

### Technical Improvements
- Balance sensors reduced from ~100 lines each to ~10 lines each
- Diagnostic sensors reduced from ~40-60 lines each to ~15-25 lines each
- Comprehensive test suite updated to validate new architecture
- Enhanced availability logic with adaptive thresholds based on update intervals
- Improved code maintainability and extensibility for future sensor additions

## [2.1.5] - 2025-09-17

### Fixed
- **Performance Sensor Last Updated Attribute**: Fixed performance sensors last_updated attribute showing as unknown or missing
  - Performance sensors now use performance cache timestamp (`_performance_last_updated`) when available
  - Added fallback to general coordinator timestamp when performance cache is not yet populated
  - Ensures performance sensors always display accurate last updated information

## [2.1.3] - 2025-09-17

### Fixed
- **Performance Sensor Availability**: Fixed performance sensors showing as unavailable despite API data being correctly fetched
  - Added proper `available` property to `SaxoPerformanceSensorBase` class
  - Performance sensors now check if they can retrieve performance values from coordinator
  - Affects Investment Performance, YTD, Month, and Quarter performance sensors

### Technical Improvements
- Enhanced availability logic for performance sensors to validate data accessibility
- Improved error handling when checking performance value availability

## [2.1.2] - 2025-09-17

### Fixed
- **Performance Sensor Last Updated**: Fixed "last_updated" attribute showing as "unknown" for performance sensors
  - Converted datetime objects to ISO format strings for proper display in Home Assistant
  - Performance sensors now properly show when performance data was last fetched
- **Display Name Sensor Icon**: Fixed missing icon for Display Name diagnostic sensor
  - Changed from invalid `mdi:account-card-details` to valid `mdi:account-box` icon
  - Added proper icon property method to ensure display in Home Assistant interface
- **OAuth Token Refresh**: Added fallback redirect_uri for token refresh operations
  - Prevents token refresh failures when redirect_uri is missing from config entry
  - Uses standard Home Assistant OAuth redirect URL as fallback

### Technical Improvements
- Enhanced error handling for OAuth token refresh with proper fallback mechanisms
- Added debug logging for sensor initialization and icon property calls
- Improved timestamp formatting for performance sensor attributes

## [2.2.1] - 2025-09-17

### Enhanced
- **Sensor Attribute Improvements**: Cleaned up cross-reference attributes and enhanced performance sensor metadata
  - Removed "total_value" attribute from Cash Balance sensor to eliminate circular references
  - Removed "cash_balance" attribute from Total Value sensor to eliminate circular references
  - Added "time_period" attribute to performance sensors showing StandardPeriod values ("AllTime" or "Year")
  - Fixed "last_updated" attribute in Accumulated Profit/Loss sensor to use performance API timestamp instead of balance API
  - Performance sensors now include proper time period identification matching API parameters

### Technical Improvements
- Enhanced SaxoPerformanceSensorBase with time_period support and abstract _get_time_period() method
- Improved attribute consistency across all sensor types with appropriate data source timestamps
- Fixed data source mapping for last_updated attributes ensuring accuracy and consistency

## [2.2.0] - 2025-09-17

### Added
- **YTD Investment Performance Sensor**: New Year-to-Date portfolio return percentage sensor (`sensor.saxo_{clientid}_ytd_investment_performance`)
- **Smart Performance Caching**: Intelligent hourly caching system for performance data to optimize API usage
  - Balance data: Real-time updates (5-30 minutes based on market hours)
  - Performance data: Cached updates (1 hour) reducing API calls by ~90%

### Added
- **Account/Client ID Diagnostic Sensors**: New diagnostic entities for troubleshooting and multi-account identification
  - Client ID sensor (`sensor.saxo_{clientid}_client_id`) showing the Saxo Client ID used for entity naming
  - Account ID sensor (`sensor.saxo_{clientid}_account_id`) displaying Account ID from balance data

### Enhanced
- **API Optimization**: Performance endpoints now called hourly instead of every 5-30 minutes
- **Code Quality**: Refactored performance sensors with shared base class (SaxoPerformanceSensorBase) to reduce code duplication
- **Entity Count**: Expanded from 10 to 13 total entities (7 portfolio + 6 diagnostic sensors)
- **Diagnostic Suite**: Complete integration monitoring with account identification, health status, and configuration visibility
- **v4 API Integration**: Added YTD performance support using "Year" StandardPeriod parameter

### Technical Improvements
- Added `get_performance_v4_ytd()` method to API client for year-to-date performance data
- Implemented performance data caching with `_should_update_performance_data()` validation
- Enhanced coordinator with smart update logic balancing real-time and cached data
- Added `get_account_id()` method to coordinator for Account ID access
- Enhanced balance data structure to include Account ID from API response
- Added `PERFORMANCE_UPDATE_INTERVAL` constant (1 hour) for cache management
- Reduced code duplication by ~24 lines through base class implementation
- Added two new diagnostic sensor classes (SaxoClientIDSensor, SaxoAccountIDSensor)

### Documentation
- Updated README.md with new YTD sensor, performance caching, and diagnostic sensors
- Enhanced CLAUDE.md with implementation details and updated file references for 13 entities
- Added configuration table showing different update intervals for balance vs performance data
- Updated entity count documentation from 11 to 13 total entities across all files

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

[2.2.1]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.2.1
[2.2.0]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.2.0
[2.1.8]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.8
[2.1.7]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.7
[2.1.6]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.6
[2.1.5]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.5
[2.1.1]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.1
[2.1.0]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.1.0
[2.0.3]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.0.3
[2.0.0]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v2.0.0
[1.0.1]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v1.0.1
[1.0.0]: https://github.com/steynovich/ha-saxo-portfolio/releases/tag/v1.0.0