# Quickstart Guide: Saxo Portfolio Home Assistant Integration

## Overview
This quickstart guide walks through the complete setup and validation of the Saxo Portfolio Home Assistant integration, from initial installation to verifying portfolio data is displayed correctly.

## Prerequisites

### Home Assistant Requirements
- Home Assistant Core 2026.3.0 or later (the first release on Python 3.14)
- HACS (Home Assistant Community Store) installed
- Admin access to Home Assistant configuration
- Internet connectivity for OAuth authentication

### Saxo Bank Requirements  
- Active Saxo Bank investment account
- Saxo Developer Account (free at https://www.developer.saxo/)
- Saxo Application registered with OAuth redirect URI
- Valid API credentials (App Key and App Secret) for a **production** app registered with the **Code** grant type (not PKCE; ADR 0001)
- Only Saxo's production environment is supported; Simulation/demo accounts are not

### Network Requirements
- Home Assistant accessible from external network (for OAuth callback)
- Firewall allows HTTPS connections to Saxo API endpoints
- DNS resolution for `gateway.saxobank.com` and `live.logonvalidation.net`

## Step 1: Saxo API Application Setup

### 1.1 Create Developer Account
1. Visit https://www.developer.saxo/openapi/appmanagement
2. Sign in with Saxo Bank credentials or create new account
3. Accept developer terms and conditions

### 1.2 Register Application
1. Click "Create New Application"
2. Fill in application details:
   - **Name**: "Home Assistant Portfolio Monitor"
   - **Description**: "Home Assistant integration for portfolio monitoring"
   - **Grant Type**: "Code" (Authorization Code Grant; do not choose PKCE)
   - **Redirect URI**: `https://my.home-assistant.io/redirect/oauth`
3. Save application and note the **Application Key** and **Application Secret**

### 1.3 Configure OAuth Permissions
1. Make sure the app has read access to portfolio balances, positions, client/account details and performance history, as shown in the Saxo developer portal
2. Save permission changes

## Step 2: Home Assistant Integration Installation

### 2.1 Install via HACS (custom repository)
1. Open Home Assistant web interface
2. Navigate to **HACS** → **Integrations** → three-dot menu → **Custom repositories**
3. Add `https://github.com/steynovich/ha-saxo-portfolio` as an Integration
4. Search for "Saxo Portfolio" and download it
5. Restart Home Assistant when prompted

### 2.2 Alternative: Manual Installation
```bash
# SSH into Home Assistant or use File Editor add-on
cd /config/custom_components
git clone https://github.com/steynovich/ha-saxo-portfolio.git
cp -r ha-saxo-portfolio/custom_components/saxo_portfolio .
# Restart Home Assistant
```

## Step 3: Integration Configuration

### 3.1 Add Application Credentials
1. Navigate to **Settings** → **Devices & Services** → **Application Credentials**
2. Add a credential for "Saxo Portfolio": **Client ID** = your App Key, **Client Secret** = your App Secret

### 3.2 Add Integration
1. Navigate to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Saxo Portfolio"
4. Click on "Saxo Portfolio" integration

### 3.3 OAuth Authentication Flow
1. **Authorize**: Pick the credentials from 3.1 and sign in with Saxo (production)
2. **Saxo Login**: Complete login on the Saxo Bank website and grant access
3. **Timezone**: Select the timezone of your main trading market
4. **Completion**: The integration fetches your Client ID and creates the entities (credentials are validated against the API before the entry is created)

### 3.4 Configuration Options
Under **Configure** on the integration:
- **Market Timezone**: the market whose hours set the update interval
- **Enable Position Sensors**: one sensor per open position (off by default)
- The update interval is **not configurable**: 5 minutes during market hours, 30 minutes after hours (15 minutes in "Any" mode). Performance data is cached for 2 hours.
- There is no base-currency or account selection; each config entry is one Saxo client, and the currency comes from the account.

### 3.5 Reauthentication
Home Assistant prompts for reauthentication when tokens can no longer be refreshed. You can also press the **Reauthenticate** button on the device or use **Reconfigure**. It must use the same Saxo account the entry was created with, otherwise it aborts with an account mismatch.

## Step 4: Verify Installation

### 4.1 Check Device Registration
1. Navigate to **Settings** → **Devices & Services**
2. Find "Saxo Portfolio" integration
3. Click to view device details
4. Verify device shows as "Connected" with last update timestamp

### 4.2 Verify Sensors Created
Expected sensors should appear (replace `123456` with your Saxo Client ID):
- `sensor.saxo_123456_total_value`
- `sensor.saxo_123456_cash_balance`
- `sensor.saxo_123456_non_margin_positions_value`
- `sensor.saxo_123456_accumulated_profit_loss`, plus the investment performance, YTD, month, quarter and cash transfer sensors
- Diagnostic sensors such as `sensor.saxo_123456_token_expiry` and `sensor.saxo_123456_market_status`
- `button.saxo_123456_refresh` and `button.saxo_123456_reauthenticate`

### 4.3 Test Data Refresh
1. Go to **Developer Tools** → **States**
2. Find Saxo Portfolio sensors
3. Verify all sensors show numeric values (not "unavailable")
4. Check **Attributes** tab for additional data like currency and last update time

### 4.4 Manual Refresh Test
1. Press `button.saxo_123456_refresh` (or call the `saxo_portfolio.refresh_data` service)
2. Verify `sensor.saxo_123456_last_update` shows the current time
4. Check Home Assistant logs for any error messages

## Step 5: Dashboard Integration

### 5.1 Create Portfolio Dashboard
```yaml
# Example dashboard card configuration
type: entities
title: Saxo Portfolio Overview
entities:
  - entity: sensor.saxo_123456_total_value
    name: Total Portfolio Value
  - entity: sensor.saxo_123456_cash_balance
    name: Available Cash
  - entity: sensor.saxo_123456_accumulated_profit_loss
    name: Accumulated Profit/Loss
  - entity: sensor.saxo_123456_ytd_investment_performance
    name: YTD Performance
show_header_toggle: false
```

### 5.2 Add Portfolio Charts
```yaml
# Historical value chart
type: history-graph
entities:
  - sensor.saxo_123456_total_value
hours_to_show: 24
refresh_interval: 300
```

### 5.3 Create Automation Examples
```yaml
# Alert on significant portfolio change
alias: Portfolio Change Alert
triggers:
  - trigger: numeric_state
    entity_id: sensor.saxo_123456_accumulated_profit_loss
    above: 1000  # Alert if profit/loss exceeds 1000
actions:
  - action: notify.mobile_app
    data:
      message: "Portfolio P/L is now {{ states('sensor.saxo_123456_accumulated_profit_loss') }}"
      title: "Portfolio Alert"
```

## Step 6: Validation and Testing

### 6.1 Data Accuracy Verification
1. Compare Home Assistant sensor values with Saxo Bank website/app
2. Verify currency conversions are correct
3. With position sensors enabled, check that the position sensors match actual holdings
4. Confirm timestamps indicate recent updates

### 6.2 OAuth Token Refresh Test
1. Watch `sensor.saxo_123456_token_expiry`; tokens are refreshed proactively at half of their lifetime
2. Verify sensors continue updating automatically
3. Check Home Assistant logs for successful token refresh messages
4. No user intervention should be required

### 6.3 Error Handling Test
1. **Network Disconnection**: Disconnect internet temporarily
   - Sensors keep their previous values and stay available for `max(15 min, 3 x update interval)` of consecutive failures, then go unavailable (ADR 0002)
   - Logs should indicate connection failures
   - Auto-recovery when connection restored
2. **Rate Limit Test**: Request multiple manual refreshes quickly
   - Integration should respect API rate limits
   - Calls are spaced 0.5 s apart; no error states in sensor values

### 6.4 Performance Validation
1. Check Home Assistant system resources during updates
2. Verify sensor updates complete within 5 seconds
3. Monitor memory usage remains under 100MB for integration

## Troubleshooting

### Common Issues

**Sensors show "Unavailable"**
- Check OAuth token status in integration configuration
- Verify Saxo API credentials are correct
- Check Home Assistant logs for authentication errors
- Reauthenticate (button, Reconfigure or the repair prompt) if needed

**Data not updating**
- Verify network connectivity to `gateway.saxobank.com`
- Check API rate limiting in logs
- Confirm Saxo account has active positions/balance

**OAuth authentication fails**
- Verify redirect URI exactly matches Saxo app configuration (`https://my.home-assistant.io/redirect/oauth`)
- Verify the Saxo app uses the Code grant type, not PKCE
- Check Home Assistant is accessible from external network
- Ensure system time is synchronized (OAuth requires accurate time)

**Sensors show old data**
- Check DataUpdateCoordinator error states in logs
- Verify Saxo API service status
- Review integration configuration for correct endpoints

### Log Analysis
Enable debug logging for detailed troubleshooting:
```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.saxo_portfolio: debug
    homeassistant.helpers.update_coordinator: debug
```

### Support Resources
- Integration GitHub Issues: https://github.com/steynovich/ha-saxo-portfolio/issues
- Home Assistant Community Forum: https://community.home-assistant.io/
- Saxo OpenAPI Documentation: https://www.developer.saxo/openapi/learn

## Success Criteria

✅ **Installation Complete** when:
- Integration appears in Home Assistant devices
- All expected sensors are created and show data
- OAuth authentication completes successfully
- Manual refresh works without errors

✅ **Validation Passed** when:
- Sensor values match Saxo Bank actual data
- Automatic updates occur every 5 minutes (market hours) or 30 minutes (after hours)
- Token refresh happens automatically
- Dashboard displays portfolio information correctly

✅ **Production Ready** when:
- System runs continuously for 24+ hours without issues  
- All error scenarios recover gracefully
- Performance remains within acceptable limits
- User documentation is complete and accessible

## Next Steps

After successful quickstart validation:
1. **Customize Dashboards**: Create personalized portfolio views
2. **Setup Automations**: Configure alerts and notifications
3. **Historical Analysis**: Use Home Assistant's long-term statistics
4. **Monitoring**: Set up integration health monitoring
5. **Backup**: Include integration configuration in Home Assistant backups