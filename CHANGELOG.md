# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.5.0] - 2026-01-04

### Added
- **Graceful Degradation for Data Fetching**: Performance API failures no longer block balance data
  - Balance sensors now work even when the performance API is slow or unresponsive
  - New `_fetch_performance_data_safely()` method with dedicated 30-second timeout
  - Performance data failures return cached/default values instead of failing the entire update
  - Cached performance values are kept indefinitely until API recovers

### Changed
- **Separate Timeout Handling**: Performance data now has its own timeout context
  - Balance fetch (required): Uses coordinator timeout, must succeed
  - Performance fetch (optional): Uses separate 30s timeout, fails gracefully
  - Added `PERFORMANCE_FETCH_TIMEOUT = 30` constant in `const.py`

### Technical Details
- Refactored `_fetch_portfolio_data()` to implement two-phase data fetching:
  1. **Phase 1**: Fetch balance data (required) - if this fails, update fails
  2. **Phase 2**: Fetch performance data (optional) - wrapped in try/except with 30s timeout
- New method `_fetch_performance_data_safely()` handles all performance and client detail fetching
  - Returns cached values on timeout or any exception
  - Logs warning on timeout to inform users without failing the update
  - Cache is never expired - shows last known values until API recovers
- This architecture ensures the integration remains functional even when Saxo's performance API is slow

### Why This Matters
- Previously: If performance API took >30s, entire 60s coordinator timeout was exceeded, ALL sensors became unavailable
- Now: Balance sensors (cash, total value, positions) work independently of performance API health
- Users see their balance data immediately while performance data may show cached values during API issues

## [2.4.1] - 2026-01-04

### Fixed
- **Critical**: Fixed integration setup timeout causing "Setup cancelled" errors
  - Staggered update offset was being applied during initial setup, adding 0-30 seconds of delay
  - Combined with slow/unresponsive Saxo performance API, this exceeded Home Assistant's 60-second setup timeout
  - Fix: Skip the staggered offset during initial setup (when `_last_successful_update` is None)
  - Offset now only applies on subsequent scheduled updates where it prevents rate limiting

### Root Cause Analysis
- **Symptom**: Integration showed "Error" and failed to setup after reauthentication or restart
- **Timeline in logs**:
  1. 16.5s staggered offset delay applied during setup
  2. Balance/client details fetch (~0.6s) - successful
  3. Performance API timeout (~30s+) - slow/unresponsive
  4. Total time >60s → Home Assistant cancelled setup
- **Solution**: Check `_last_successful_update is not None` before applying staggered offset
  - During initial setup: `_last_successful_update` is None → skip offset → data fetch starts immediately
  - On subsequent updates: `_last_successful_update` is set → apply offset to prevent rate limiting

### Technical Details
- Modified condition in `coordinator.py:628` from `if self._initial_update_offset > 0` to include `and self._last_successful_update is not None`
- The staggered offset design prevents multiple accounts from hitting the API simultaneously
- During initial setup, accounts are set up one at a time anyway, so the offset provided no benefit
- This fix eliminates the unnecessary delay during setup while preserving rate limiting protection for regular updates

## [2.4.0] - 2026-01-01

### Added
- **Manual Refresh Button**: Added a refresh button entity to each device
  - Entity ID: `button.saxo_{client_id}_refresh`
  - Appears on device page under configuration entities
  - Press to trigger immediate data refresh from Saxo Bank API
  - Can be added to dashboards or used in automations
  - Translations available in all 11 supported languages

- **Refresh Data Service**: Added `saxo_portfolio.refresh_data` service
  - Call from Developer Tools → Services or automations
  - Refreshes all registered Saxo Portfolio accounts
  - Bypasses normal update schedule for immediate data fetch

### Technical Details
- New `button.py` platform with `SaxoRefreshButton` entity
- Service registered once per domain in `__init__.py`
- Service automatically removed when last integration entry is unloaded
- Button uses `ButtonDeviceClass.UPDATE` and `EntityCategory.CONFIG`

## [2.3.9] - 2025-12-30

### Fixed
- **Reconfigure Dialog**: Fixed empty popup when clicking Reconfigure button
  - Simplified reconfigure flow to use single step with proper HA method `_get_reconfigure_entry()`
  - Changed step ID from `reconfigure_confirm` to `reconfigure` to match HA conventions
  - Dialog now properly displays title and description

### Added
- **Multi-language Support**: Added translations for 11 languages
  - English (en)
  - German (de)
  - French (fr)
  - Spanish (es)
  - Dutch (nl)
  - Italian (it)
  - Portuguese (pt)
  - Danish (da)
  - Swedish (sv)
  - Norwegian Bokmål (nb)
  - Finnish (fi)

## [2.3.8] - 2025-12-30

### Fixed
- **Reconfigure Dialog Empty**: Fixed empty popup when clicking Reconfigure button
  - Added missing `translations/en.json` file required by Home Assistant for runtime string loading
  - Reconfigure dialog now displays title and description correctly

## [2.3.7] - 2025-12-30

### Added
- **Manual Reauthentication Button**: Users can now proactively reauthenticate via the "Reconfigure" menu option
  - Go to Settings → Devices & Services → Saxo Portfolio → three-dot menu → Reconfigure
  - Useful for refreshing tokens before they expire
  - Resolves authentication issues without removing the integration
  - All settings, entity history, and automations are preserved

### Technical Details
- Added `async_step_reconfigure()` and `async_step_reconfigure_confirm()` in config_flow.py:268-302
- Added `reconfigure_confirm` step strings in strings.json

## [2.3.6] - 2025-12-30

### Added
- **Multi-Account Identification**: Config entry titles now include the Client ID for clear account identification
  - Titles automatically update from "Saxo Portfolio" to "Saxo Portfolio (CLIENT_ID)" after first successful data fetch
  - Makes it easy to identify which account each integration represents in Settings → Devices & Services

### Changed
- **Improved Reauthentication Dialog**: Updated reauth UI to display the account identifier
  - Dialog title now shows "Reauthenticate Saxo Portfolio (CLIENT_ID)"
  - Description clearly states which account needs reauthentication
  - Essential for users with multiple Saxo accounts configured

### Technical Details
- Added `_update_config_entry_title_if_needed()` method in coordinator.py:1359-1387
- Method updates config entry title only when:
  - Client ID is successfully fetched (not "unknown")
  - Title is still generic ("Saxo Portfolio") or doesn't contain Client ID
- Updated strings.json reauth_confirm step to use `{title}` placeholder

## [2.3.5] - 2025-11-17

### Fixed
- **Critical**: Fixed reauthentication button not appearing when tokens expire
  - Added explicit `ConfigEntryAuthFailed` exception handler in coordinator.py:1058-1064
  - Previously, `ConfigEntryAuthFailed` was caught by generic `except Exception` handler and converted to `UpdateFailed`
  - `UpdateFailed` only makes sensors unavailable without triggering reauth flow
  - Now `ConfigEntryAuthFailed` properly propagates to Home Assistant core to trigger reauth UI

### Changed
- Added dedicated exception handler for `ConfigEntryAuthFailed` before generic `Exception` handler
- Handler re-raises the exception to allow Home Assistant to display reauthentication prompt
- Added informative log message when authentication failure triggers reauth flow

### Technical Details
- **Root Cause**: Exception handling order in `_fetch_portfolio_data()` method
  - Token refresh failures raise `ConfigEntryAuthFailed` at line 635
  - Generic `except Exception` handler at line 1066 caught it and converted to `UpdateFailed`
  - This prevented Home Assistant from detecting auth failure and showing reauth button
- **Solution**: Added specific handler at line 1058 that re-raises `ConfigEntryAuthFailed` unchanged
- **Flow**: Token expires → `_check_and_refresh_token()` raises `ConfigEntryAuthFailed` → new handler re-raises → Home Assistant shows reauth button

### User Experience Improvements
- **Before**: Tokens expire → sensors unavailable → no UI prompt → users confused
- **After**: Tokens expire → sensors unavailable → reauthentication button appears in UI → users can easily reauth

### How to Verify
1. After upgrading to 2.3.5, wait for tokens to expire (or force expiry)
2. Check Settings → Devices & Services → Saxo Portfolio
3. You should now see the reauthentication prompt/button appear
4. Click "Configure" or "Reauthenticate" to restore access

## [2.3.4] - 2025-11-16

### Fixed
- **Critical**: Fixed missing reauthentication UI in Home Assistant
  - Added `reauth_confirm` step to strings.json for proper UI display
  - Added `async_step_reauth_confirm()` to show confirmation dialog before OAuth flow
  - Users now see a clear "Reauthenticate Saxo Portfolio" dialog when tokens expire
  - Dialog explains that settings and history will be preserved during reauth

### Changed
- Enhanced `async_step_reauth()` to show confirmation form first (config_flow.py:247-248)
- Added `async_step_reauth_confirm()` method to handle user confirmation (config_flow.py:250-264)
- Updated strings.json with reauth_confirm step configuration (lines 22-25)

### User Experience Improvements
- **Before**: ConfigEntryAuthFailed raised but no UI appeared → users confused
- **After**: Clear dialog appears with "Submit" button → starts OAuth flow → seamless reauth
- Dialog message: "Your Saxo Bank authentication has expired. Please sign in again to continue using the integration. All your settings, entity history, and automations will be preserved."

### Technical Details
- **Root Cause**: Missing reauth_confirm step in UI configuration prevented Home Assistant from displaying the reauthentication prompt
- **Solution**: Added proper reauth confirmation flow following Home Assistant OAuth2 best practices
- **Flow**: ConfigEntryAuthFailed → async_step_reauth → async_step_reauth_confirm (show form) → user clicks Submit → async_step_pick_implementation → OAuth flow

### How to Trigger (After Upgrade)
1. Wait for tokens to expire OR restart HA after this upgrade
2. Look in Settings → Devices & Services
3. You should now see one of:
   - Yellow banner: "Authentication required for Saxo Portfolio"
   - Integration card with warning badge
   - Notification icon (🔔) with auth failure message
4. Click "Configure" or "Reauthenticate"
5. You'll see the new confirmation dialog
6. Click "Submit" to start OAuth flow

## [2.3.3] - 2025-11-16

### Fixed
- **Critical**: Fixed refresh token expiration by implementing proactive refresh token rotation
  - Integration now checks refresh token expiry INDEPENDENTLY of access token expiry
  - Proactively refreshes access token when refresh token has less than 5 minutes remaining
  - Ensures we get a new refresh token before the old one expires (if Saxo supports refresh token rotation)
  - Prevents "Refresh token has expired" errors when HA is running continuously
  - Solves the core issue: access token expires in 20min, refresh token expires in 5min → now we refresh at 5min mark

### Changed
- Added `REFRESH_TOKEN_BUFFER` constant (5 minutes) in const.py:150-152
- Enhanced `_check_and_refresh_token()` to check refresh token expiry first (coordinator.py:278-371)
- Implemented two-step token validation:
  - **STEP 1**: Check if refresh token will expire soon (proactive) - Lines 299-352
  - **STEP 2**: Check if access token needs refresh (normal) - Lines 354-371
- Added detailed logging for refresh token expiry monitoring

### Technical Details
- **Root Cause**: Old logic only checked refresh token when access token needed refresh, missing cases where refresh token expires before access token
- **Example Scenario**:
  - Access token expires in 20 minutes
  - Refresh token expires in 5 minutes
  - Old behavior: Wait 20 minutes → refresh token already expired ❌
  - New behavior: Check at 5 minutes → proactive refresh → get new refresh token ✅
- **Refresh Token Rotation**: If Saxo Bank provides a new refresh_token in the token refresh response, we now ensure we refresh often enough to keep getting new ones
- **Compatibility**: Works alongside v2.3.2's accurate timestamp tracking

### Important Notes
- **This does NOT eliminate the need for reauthentication** - When HA is shut down longer than refresh token lifetime, manual reauth is still required (by design)
- **This DOES prevent refresh token expiry** during normal HA operation by refreshing proactively
- **Requires Saxo support**: If Saxo Bank does NOT provide new refresh tokens during token refresh, manual reauth will eventually be needed

## [2.3.2] - 2025-11-16

### Fixed
- **Critical**: Fixed refresh token expiry calculation after Home Assistant shutdown
  - Integration now stores `token_issued_at` timestamp during initial OAuth and token refresh
  - Refresh token expiry is now calculated using actual issuance time instead of inferred time
  - Prevents incorrect expiry calculations after the first token refresh
  - Fixes issue where HA shutdown for hours could cause premature or missed refresh token expiry detection
  - Includes backward compatibility fallback for existing installations without stored timestamp

### Changed
- Enhanced token refresh logic to store accurate token issuance timestamp (coordinator.py:498-510)
- Updated refresh token expiry validation to use stored timestamp (coordinator.py:303-316)
- Added `token_issued_at` timestamp storage during initial OAuth flow (config_flow.py:114-119)

### Technical Details
- **Root Cause**: After token refresh, the integration calculated `token_issued_at = expires_at - expires_in`, but this used the NEW access token expiry with the OLD refresh token lifetime, causing incorrect calculations
- **Solution**: Store actual `token_issued_at` timestamp whenever tokens are obtained or refreshed
- **Impact**: Prevents unnecessary reauthentication requests and ensures refresh tokens work correctly after long HA downtime
- **Compatibility**: Existing installations automatically benefit after next token refresh

## [2.3.1] - 2025-11-16

### Changed
- **Improved User Messaging**: Updated error messages to guide users to the reauthentication button
  - Changed "Delete and re-add the integration" message to "click the Reauthenticate button"
  - Reduced log level from ERROR to INFO for user guidance message
  - Makes it clearer that users don't need to delete the integration when tokens expire
  - Improves user experience by directing to the correct GUI-based reauth flow

### Fixed
- Updated expired token error message to properly guide users to the reauthentication button in Settings > Devices & Services
- Prevents user confusion about needing to delete and re-add the integration

## [2.3.0] - 2025-10-27

### Added
- **GUI-Based Reauthentication**: Seamless reauthentication flow when OAuth tokens expire
  - Users can now reauthenticate directly from the Home Assistant UI
  - Home Assistant automatically displays a "Reauthenticate" button when tokens expire or become invalid
  - No need to delete and re-add the integration when tokens expire
  - All configuration settings (timezone, entity customizations, etc.) are preserved
  - All entity history and statistics are maintained
  - Only OAuth tokens are updated during reauthentication

### Changed
- Enhanced `async_step_reauth()` in config_flow.py to properly initiate OAuth flow for reauthentication
- Updated `async_oauth_create_entry()` in config_flow.py to detect reauth flows and update existing config entry
- Added `_reauth_entry` tracking to flow handler to preserve config entry during reauth
- Added user-facing success message for completed reauthentication

### Technical Details
- Reauth flow triggered automatically when coordinator raises `ConfigEntryAuthFailed`
- Config entry is updated in place rather than creating a new entry
- Integration reloads after successful reauth to apply new tokens
- Preserves all existing data including timezone configuration and redirect_uri
- Follows Home Assistant OAuth2 reauth best practices

### User Impact
- **Significantly improved user experience**: No more deleting and re-adding the integration
- **No data loss**: All historical data and statistics are preserved
- **Automatic detection**: System detects expired tokens and prompts for reauth
- **One-click solution**: Simple button click starts the reauth process

## [2.2.18] - 2025-10-27

### Fixed
- **Critical**: Fixed integration not detecting expired refresh tokens
  - Saxo refresh tokens have a limited lifetime (typically 1 hour)
  - Integration now checks if refresh token is expired before attempting refresh
  - Triggers automatic reauth flow when refresh token has expired
  - Prevents 401 errors from trying to use expired refresh tokens
  - Provides clear error messages explaining the issue

### Changed
- Enhanced `_check_and_refresh_token()` to validate refresh token expiry (coordinator.py:299-329)
  - Calculates refresh token expiration time based on `refresh_token_expires_in`
  - Logs refresh token expiration information for debugging
  - Raises ConfigEntryAuthFailed with helpful message when refresh token expired
  - Home Assistant will automatically prompt for reauth when this occurs

### Technical Details
- Refresh token expiry calculation: `token_issued_at + refresh_token_expires_in`
- Prevents wasted API calls with expired credentials
- Clearer user experience with automatic reauth prompts
- INFO-level logging shows refresh token expiration time

## [2.2.17] - 2025-10-27

### Changed
- **Enhanced Diagnostics**: Added comprehensive logging for OAuth token refresh debugging
  - INFO-level logging now shows client_id and redirect_uri being used for token refresh
  - Logs source of redirect_uri (OAuth implementation vs config entry vs none)
  - Added helpful error messages for 401 errors with troubleshooting steps
  - Logs masked client_id (first 8 characters) to help identify configuration issues
  - Provides clear guidance on potential causes: redirect_uri mismatch, invalid credentials, reconfiguration needed

### Technical Details
- Enhanced `_refresh_oauth_token()` method with comprehensive diagnostic logging
- All key OAuth refresh parameters now logged at INFO level (no debug logging needed)
- 401 errors now include specific troubleshooting suggestions
- Helps diagnose redirect_uri mismatches and credential issues

## [2.2.16] - 2025-10-27

### Fixed
- **Critical**: Fixed OAuth token refresh 401 Unauthorized errors (partial fix)
  - Token refresh was using hardcoded redirect_uri instead of the actual redirect_uri from initial authorization
  - OAuth 2.0 requires redirect_uri in refresh requests to match the one used during initial authorization
  - Now properly retrieves redirect_uri from OAuth implementation object (coordinator.py:355-407)
  - Falls back to stored redirect_uri in config entry if implementation is unavailable
  - Integration will now successfully refresh tokens and maintain authentication

### Changed
- Enhanced config flow to properly store redirect_uri during initial setup (config_flow.py:128-157)
  - Retrieves redirect_uri from OAuth implementation instead of using hardcoded value
  - Includes proper error handling and fallback mechanisms
  - Improves reliability of token refresh operations

### Technical Details
- Modified `_refresh_oauth_token()` in coordinator.py to use `implementation.redirect_uri`
- Enhanced logging to show which redirect_uri is being used for token refresh
- Only uses hardcoded fallback as last resort with warning message
- Ensures OAuth 2.0 compliance for token refresh operations

## [2.2.15] - 2025-10-13

### Added
- **Long-term Statistics Support**: All balance sensors now support Home Assistant long-term statistics
  - Changed from `state_class = "measurement"` (v2.2.14) to `state_class = "total"` (compatible with monetary device class)
  - Enables historical tracking for Cash Balance, Total Value, Non-Margin Positions, and Cash Transfer Balance sensors
  - Provides extended history beyond standard 10-day retention
  - Enables statistics cards with min, max, mean values and trend analysis
  - All balance sensors now have same long-term statistics support as Accumulated Profit/Loss sensor

### Fixed
- Fixed Home Assistant validation errors from v2.2.14
  - Changed `state_class` from "measurement" to "total" for balance sensors (sensor.py:180)
  - Home Assistant's `monetary` device class only supports `state_class = "total"`, not "measurement"
  - Fixes warnings: "Entity is using state class 'measurement' which is impossible considering device class ('monetary')"

### Technical Details
- Modified `SaxoBalanceSensorBase.__init__()` to set `self._attr_state_class = "total"`
- All balance sensors inheriting from this base class now support long-term statistics
- Compatible with Home Assistant's monetary device class requirements
- No breaking changes - existing functionality remains unchanged

## [2.2.14] - 2025-10-13 [YANKED]

### Note
This release was yanked due to Home Assistant validation errors. See v2.2.15 for the fix.

### Added (Reverted in v2.2.15)
- Attempted to add long-term statistics support to balance sensors
  - Added `state_class = "measurement"` to `SaxoBalanceSensorBase`
  - This configuration is incompatible with `device_class = "monetary"` in Home Assistant

## [2.2.13] - 2025-09-30

### Fixed
- Fixed "Unclosed client session" error during OAuth token refresh
  - Old API client session wasn't being closed before creating new one
  - Added proper cleanup: close old client before setting to None
  - Prevents resource leaks and error messages in logs
  - Client closure happens in background to avoid blocking

## [2.2.12] - 2025-09-30

### Fixed
- Fixed repeated market hours debug logging
  - Multiple sensors were calling `_is_market_hours()` simultaneously during state updates
  - Added 1-second cache to `_is_market_hours()` to avoid redundant calculations
  - Reduces log noise from 3+ identical messages to 1 per second
  - Improves performance by caching timezone calculations

## [2.2.11] - 2025-09-30

### Fixed
- **Critical**: Fixed integration reloading every time OAuth token is refreshed
  - Token refresh triggered config entry update listener causing full integration reload
  - Now coordinator handles token updates internally without triggering reload
  - Prevents unnecessary integration restarts every 20 minutes during token refresh
  - Only reloads when actual configuration changes (not token updates)

## [2.2.10] - 2025-09-30

### Fixed
- **Critical**: Fixed performance cache never updating when client details are successfully fetched
  - Incorrect indentation in coordinator.py:826-840 caused cache update to only occur when client_details was None
  - This defeated the entire caching mechanism and caused unnecessary API calls
  - Performance cache now properly updates every 2 hours as designed
- Fixed duplicate condition check in SaxoLastUpdateSensor.native_value
  - Removed redundant hasattr() check that was executed twice
  - Simplified logic for better readability
- Fixed naive datetime usage in sensor availability check
  - Now uses dt_util.as_utc() instead of manual pytz.UTC.localize()
  - More consistent with Home Assistant datetime handling standards
- Improved error handling in coordinator client details fetch
  - Now logs exception type and message for better debugging
  - Previously used generic `except Exception` without logging details

### Changed
- Removed unused `_fetch_performance_data()` method from coordinator
  - Dead code cleanup - method was defined but never called
  - Reduces code complexity and maintenance burden

### Tests
- Updated test_sticky_availability.py to use UTC-aware datetimes (dt_util.utcnow())
  - All datetime comparisons now use timezone-aware timestamps
  - Fixed test expectations to match actual sticky availability behavior
  - All 8 sticky availability tests now pass

## [2.2.9] - 2025-09-30

### Fixed - Rate Limiting and Integration Stability
- **Comprehensive Rate Limiting Prevention**: Eliminated 429 rate limiting errors
  - Batched v4 API calls: Reduced from 7 calls to 4 calls per performance update (43% reduction)
  - New `get_performance_v4_batch()` method fetches AllTime/YTD/Month/Quarter with built-in 0.5s delays
  - Added inter-call delays between balance and client details calls
  - Staggered multi-account updates with random 0-30s offset to prevent simultaneous API requests
  - Impact: 14 calls in <2s → 8 calls over 4+ seconds (with 2 accounts)

- **Integration Reload Loop Fix**: Fixed integration repeatedly loading/unloading on startup
  - Added `_setup_complete` flag to properly track initial setup completion
  - Reload check now only triggers after platform setup finishes, not during initial refresh
  - Prevents unnecessary reload when client name is fetched during normal startup
  - Preserves reload functionality for genuinely skipped sensors (unknown client data)

- **AttributeError Fix**: Fixed crash during coordinator initialization
  - Removed premature access to `self.data` before parent class initialization
  - Simplified `_last_known_client_name` initialization to always start as "unknown"

### Changed
- **Performance Cache Interval**: Increased from 1 hour to 2 hours
  - Reduces performance update frequency by 50%
  - Balance data still updates every 5-30 minutes based on market hours
  - Performance data changes slowly, 2-hour cache is acceptable

- **API Client** (`api/saxo_client.py`):
  - Added `get_performance_v4_batch()` method for batched performance data fetching
  - Existing individual v4 methods maintained for backwards compatibility

- **Coordinator** (`coordinator.py`):
  - Added `random` import for stagger offset generation
  - Added `_setup_complete` flag and `mark_setup_complete()` method
  - Added `_initial_update_offset` property with 0-30s random value
  - Refactored performance data fetch to use batched method
  - Added strategic delays between API calls to prevent burst traffic
  - Enhanced reload logic with setup completion tracking

- **Init** (`__init__.py`):
  - Call `coordinator.mark_setup_complete()` after platform setup
  - Enhanced error logging with full traceback for debugging

- **Constants** (`const.py`):
  - `PERFORMANCE_UPDATE_INTERVAL`: Changed from 1 hour to 2 hours

### Performance Impact
- **Before**: 14 API calls in <2 seconds (2 accounts × 7 calls each)
- **After**: 8 API calls spread over 4+ seconds, staggered between accounts
- **Rate Limit Risk**: Eliminated (well under 120/min threshold)

### Notes
- All changes are backwards compatible
- No breaking changes to sensor entities or data structure
- Integration now handles multiple accounts gracefully without rate limiting
- Startup is clean with no reload loops or crashes

## [2.2.9-beta.4] - 2025-09-30

### Fixed - Integration Reload Loop (FINAL FIX) (PRERELEASE)
- **Reload Loop Prevention (Correct Fix)**: Finally fixed the reload loop with proper timing logic
  - Added `_setup_complete` flag to track when platform setup finishes
  - Reload check now uses `self._setup_complete` instead of `self.last_update_success_time`
  - Only triggers reload AFTER initial setup completes, not DURING it

### Root Cause (Beta.3 was wrong)
The timing was misunderstood:
1. `async_setup_entry` calls `coordinator.async_refresh()` (first update)
2. **During this refresh**, `_async_update_data()` runs the reload check
3. At this point: `last_update_success_time` gets set by coordinator base class
4. Sensors haven't been initialized yet (`_sensors_initialized == False`)
5. Beta.3's condition `last_update_success_time is not None` was True!
6. Reload triggered immediately during initial setup

### Correct Solution
- New `_setup_complete` flag starts as False
- Reload requires: `_setup_complete == True` (instead of checking last_update_success_time)
- `mark_setup_complete()` called AFTER platform setup finishes
- Reload logic only activates after initial setup completes

### Changed
- **Coordinator** (`coordinator.py`):
  - Line 71: Added `_setup_complete` flag (starts False)
  - Line 1038: Changed condition from `last_update_success_time is not None` to `self._setup_complete`
  - Line 1233-1241: Added `mark_setup_complete()` method
- **Init** (`__init__.py:49`):
  - Call `coordinator.mark_setup_complete()` after platform setup

### Notes
- This is the CORRECT fix based on proper understanding of async_refresh timing
- All rate limiting improvements from beta.1 remain unchanged
- This is a **beta prerelease** for final verification before stable release

## [2.2.9-beta.3] - 2025-09-30

### Fixed - Integration Reload Loop (Complete Fix) (PRERELEASE)
- **Reload Loop Prevention (Improved)**: Completely fixed integration reload loop on startup
  - Added 4th condition to reload check: `self.last_update_success_time is not None`
  - Prevents reload during initial setup when client name is legitimately fetched for first time
  - Only triggers reload when client name changes from unknown→known AFTER initial setup
  - This is the scenario where sensors were skipped and need to be created later

### Root Cause Analysis
Beta.2's fix was incomplete:
1. Initial setup: coordinator created, `self.data` is None
2. First refresh: fetches client_name = "20482598"
3. Beta.2 still triggered reload because this looked like unknown→known transition
4. Reload executed even though sensors were about to be created normally
5. Created load/unload cycle

### Complete Solution
Reload now requires ALL 4 conditions:
1. ✅ Previous client name was "unknown"
2. ✅ Current client name is valid (not "unknown")
3. ✅ Sensors not initialized (`_sensors_initialized == False`)
4. ✅ **NOT the first update** (`last_update_success_time is not None`)

Condition #4 ensures reload only happens AFTER initial setup completes, when sensors were genuinely skipped due to unknown client name.

### Changed
- **Coordinator** (`coordinator.py:1023-1028`):
  - Added `self.last_update_success_time is not None` to reload condition
  - Prevents reload during normal initial setup flow
  - Preserves reload functionality for genuinely skipped sensor scenarios

### Notes
- This completely fixes the reload loop from beta.1 and beta.2
- All rate limiting improvements from beta.1 remain unchanged
- This is a **beta prerelease** for final testing before stable release

## [2.2.9-beta.2] - 2025-09-30

### Fixed - Integration Reload Loop (PRERELEASE)
- **Reload Loop Prevention**: Fixed integration repeatedly loading and unloading on startup
  - Initialize `_last_known_client_name` from cached coordinator data if available
  - Prevents unnecessary config entry reload when client name hasn't actually changed
  - Coordinator now properly detects when client name genuinely changes vs already-known values
  - Integration loads once and stays loaded (no more load/unload cycles)

### Changed
- **Coordinator** (`coordinator.py:67-69`):
  - `_last_known_client_name` now initialized from `self.data` if available
  - Only triggers reload when client name **genuinely** changes from unknown to known
  - Fixes issue introduced in v2.2.3's conditional sensor creation feature

### Notes
- This fixes the reload loop observed in beta.1
- All rate limiting improvements from beta.1 remain unchanged
- This is a **beta prerelease** for testing the reload fix

## [2.2.9-beta.1] - 2025-09-30

### Fixed - Rate Limiting Prevention (PRERELEASE)
- **Batched v4 API Calls**: Consolidated 4 separate performance v4 API calls into single batched method
  - Reduces from 7 API calls per performance update to 4 calls (43% reduction)
  - With 2 accounts: 14 calls → 8 calls per performance update cycle
  - New `get_performance_v4_batch()` method fetches AllTime/YTD/Month/Quarter in sequence with delays
  - Prevents 429 rate limiting errors (120 requests/minute limit)

- **Inter-Call Delays**: Added 0.5s delays between sequential API calls
  - Spreads API calls over time instead of instant burst
  - Delay between balance and client details calls
  - Delay before batched performance calls
  - Internal delays between v4 batch calls (AllTime → YTD → Month → Quarter)
  - 4 calls now spread over ~2 seconds instead of <1 second

- **Staggered Multi-Account Updates**: Added random 0-30s offset per config entry on startup
  - Prevents multiple accounts from hitting performance updates simultaneously
  - Each account coordinator has unique `_initial_update_offset`
  - Offset applied once on first update, then cleared
  - Reduces peak load when multiple accounts configured

### Changed
- **Performance Cache Interval**: Increased from 1 hour to 2 hours
  - Reduces performance update frequency by 50%
  - Balance data still updates every 5-30 minutes (unchanged)
  - Performance data changes slowly, 2-hour cache is acceptable
  - Further reduces rate limiting risk

- **API Client** (`api/saxo_client.py`):
  - Added `get_performance_v4_batch()` method with built-in rate limiting
  - Existing individual v4 methods maintained for backwards compatibility

- **Coordinator** (`coordinator.py`):
  - Added `random` import for stagger offset generation
  - Added `_initial_update_offset` property with 0-30s random value
  - Refactored performance data fetch to use batched method
  - Added strategic delays between API calls to prevent burst traffic

- **Constants** (`const.py`):
  - `PERFORMANCE_UPDATE_INTERVAL`: Changed from 1 hour to 2 hours

### Expected Outcome
- **Before**: 14 API calls in <2 seconds (2 accounts × 7 calls each)
- **After**: 8 API calls spread over 4+ seconds, staggered between accounts
- **Rate Limit Risk**: Eliminated (well under 120/min threshold)

### Notes
- All 4 rate limiting improvements implemented together for maximum effectiveness
- Batched calls maintain all existing functionality and data
- This is a **beta prerelease** for testing rate limiting fixes

## [2.2.8-beta.2] - 2025-09-30

### Fixed - Timeout Duration Adjustment (PRERELEASE)
- **Coordinator Timeout**: Increased from 30s to 60s to accommodate sequential API calls
  - Testing beta.1 showed API calls succeeding but hitting 30s timeout
  - Balance fetch (0.11s), client details, and performance data all succeed
  - 60s provides enough time for all sequential API calls to complete
  - Maintains single-layer timeout structure (no nested contexts)

### Changed
- **const.py**: `COORDINATOR_UPDATE_TIMEOUT` increased from 30s to 60s
- No other logic changes from beta.1

### Notes
- Builds on beta.1's nested timeout fix
- API calls were working correctly in beta.1, just needed more time
- This is a **beta prerelease** for testing the adjusted timeout

## [2.2.8-beta.1] - 2025-09-30

### Fixed - Critical Startup Timeout Issue (PRERELEASE)
- **Nested Timeout Problem**: Fixed integration startup failures caused by triple-nested timeout contexts
  - Removed nested `API_TIMEOUT_BALANCE`, `API_TIMEOUT_PERFORMANCE`, `API_TIMEOUT_CLIENT_INFO` constants
  - Restored `COORDINATOR_UPDATE_TIMEOUT` from 90s back to 30s (v2.2.2 value)
  - Removed 5 nested `async_timeout.timeout()` calls in coordinator
  - Integration now starts successfully without repeated timeout warnings

### Root Cause
- v2.2.5 introduced triple-nested timeout contexts that raced with each other
- Nested timeouts (coordinator → balance/performance → API client) interrupted API client retry logic
- Caused retry counter to reset repeatedly, showing "Request timeout (attempt 1/3)" indefinitely
- Integration would wait 132+ seconds and fail to start, even when Saxo API was fully operational

### Solution
- Reverted to v2.2.2's proven timeout structure
- Single coordinator timeout layer (30s) lets API client handle its own timeouts and retries
- Eliminates timeout race conditions
- Restores working behavior from v2.2.2

### Changed
- **const.py**: Removed progressive timeout constants, restored simple 30s coordinator timeout
- **coordinator.py**: Removed nested timeout logic from 5 locations:
  - Balance data fetch
  - Client details fetch
  - Performance v3 fetch
  - Performance v4 fetch
  - Individual performance period fetches

### Technical Details
- All code quality checks passing: Ruff (linting), Python syntax
- No functionality changes beyond timeout handling
- Backwards compatible with v2.2.2 timeout behavior

### Notes
- This is a **beta prerelease** for testing the timeout fix
- Versions v2.2.5, v2.2.6, v2.2.7 all had this nested timeout issue
- v2.2.2 and earlier worked correctly
- Please test and report results before stable v2.2.8 release

## [2.3.0-beta.1] - 2025-09-30 [REVERTED]

**Note**: This refactoring release was reverted due to startup timeout issues discovered during testing.

## [2.2.7] - 2025-09-30 [REVERTED]

**Note**: This version reverted the v2.3.0-beta.1 refactoring but still contained the nested timeout issue from v2.2.5.

## [2.2.6] - 2025-09-29

### Improved
- **Enhanced Rate Limiting Messages**: Improved rate limiting error reporting for better user experience
  - Changed first rate limit occurrence from WARNING to DEBUG level to reduce startup noise
  - Added context-aware messages explaining rate limiting is normal during startup and high API usage
  - Enhanced error messages to distinguish between expected rate limiting and potential issues
  - Added startup phase tracking to provide better context for initial integration setup

### Fixed
- **Startup Experience**: Reduced confusing rate limit warnings during integration startup
  - Rate limiting during startup is normal behavior and no longer generates warning messages
  - Subsequent rate limit hits still generate warnings to indicate potential issues
  - Added helpful context about when rate limiting is expected vs concerning

### Technical Improvements
- Startup phase detection in coordinator for first 3 successful updates
- Context-aware rate limiting messages in API client with better user guidance
- Enhanced logging to help users understand normal vs problematic rate limiting scenarios

## [2.2.5] - 2025-09-29

### Improved
- **Enhanced Timeout Handling**: Significantly improved timeout management and error reporting
  - Increased coordinator timeout from 30s to 90s to accommodate multiple API calls
  - Added progressive timeouts: Balance (45s), Performance (60s), Client Info (30s)
  - Enhanced timeout error messages with actual timing information and user guidance
  - Implemented smart timeout warning system (first warning, then debug level for 5 minutes)
  - Added comprehensive timing logs for debugging API performance issues

### Fixed
- **Network Resilience**: Better handling of network connectivity issues and high API load scenarios
  - Timeout errors now provide actionable guidance instead of generic error messages
  - Improved error recovery with detailed context about network conditions
  - Reduced timeout error noise while maintaining visibility into genuine issues

### Technical Improvements
- Progressive timeout implementation for different API endpoint types
- Enhanced logging with request timing information for troubleshooting
- Improved error message context with actual vs expected timing
- Better separation of concerns between critical and optional data fetching

## [2.2.4] - 2025-09-29

### Improved
- **Logging Optimization**: Reduced log noise by changing token refresh warnings to debug level
  - Changed "Token expires very soon, immediate refresh needed" from WARNING to DEBUG level
  - Token refresh operations are normal behavior and don't require user attention
  - Cleaner Home Assistant logs with less verbose OAuth token management messaging

## [2.2.3] - 2025-09-29

### Added
- **Conditional Sensor Creation**: Enhanced integration robustness with unknown client name protection
  - Sensors are only created when valid client data is successfully retrieved from the Saxo API
  - Prevents orphaned devices and entities when API authentication initially fails
  - Automatic config entry reload when client data becomes available
  - Clear warning messages with user guidance when sensor setup is skipped

### Improved
- **Enhanced Error Handling**: Better handling of scenarios where client information is unavailable
  - Integration gracefully handles temporary API unavailability during initial setup
  - Automatic recovery when client data becomes available without user intervention
  - Prevents unnecessary entity registry entries for incomplete integrations
- **Testing Coverage**: Added comprehensive tests for conditional sensor creation behavior
  - Tests validate both successful creation and proper skipping scenarios
  - Enhanced test coverage for config entry reload functionality

### Technical Details
- Added client name validation in `async_setup_entry()` before sensor creation
- Implemented automatic config entry reload detection and scheduling
- Enhanced coordinator tracking for sensor initialization status
- Improved logging with actionable user guidance for troubleshooting

## [2.2.2] - 2025-09-29

### Fixed
- **Sensor Availability Stability**: Improved sensor availability logic to prevent brief unavailability during updates
  - Enhanced sticky availability system to maintain sensor availability during normal coordinator updates
  - Sensors now only become unavailable after sustained failures (15+ minutes or 3x update interval)
  - Fixed timezone-aware datetime comparison issues in availability calculations
  - Improved edge case handling for initial startup and missing update timestamps
  - Sensors remain available during OAuth token refresh operations
  - Better handling of coordinators without last_successful_update_time attribute

### Technical Improvements
- Refactored availability logic in SaxoSensorBase for better maintainability
- Added proper timezone conversion for datetime comparisons (UTC-aware)
- Improved graceful degradation when update timestamps are unavailable
- Enhanced code readability with clearer logic flow and documentation

## [2.2.1] - 2025-09-18

### Fixed
- **HTTP Session Management**: Enhanced session cleanup to prevent "Unclosed client session" errors
  - Improved error handling in API client close methods with comprehensive logging
  - Enhanced session recreation detection and logging in API client
  - Added robust error handling to coordinator shutdown methods
  - Better exception logging with stack traces for debugging session issues
  - Ensures proper cleanup during integration unload and token refresh operations

### Technical Improvements
- Added detailed logging for session creation, closure, and error scenarios
- Enhanced async_shutdown method with proper exception handling
- Improved _close_old_client method with comprehensive error recovery
- Better debugging capabilities for HTTP session lifecycle management

## [2.2.0] - 2025-09-18

### Breaking Changes
- **Python Version Requirement**: Updated minimum Python version requirement to 3.13+
  - Removed support for Python 3.11 and 3.12
  - Updated all project configuration files to require Python 3.13+
  - GitHub Actions workflows now test only Python 3.13
  - Enhanced compatibility with latest Python features and improvements

### Enhanced
- **Python 3.13 Support**: Full compatibility with Python 3.13
  - Updated pyproject.toml with Python 3.13 classifiers and requirements
  - Updated ruff configuration to target Python 3.13
  - Updated MyPy configuration for Python 3.13 type checking
  - Enhanced development toolchain for modern Python features

### Technical Improvements
- Streamlined Python version support for better maintainability
- Updated CI/CD pipeline to use Python 3.13 exclusively
- Enhanced type checking and linting with Python 3.13 target
- Improved code quality tools configuration for latest Python version

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