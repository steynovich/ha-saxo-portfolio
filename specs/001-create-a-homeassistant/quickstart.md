# Quickstart Guide: Saxo Portfolio Home Assistant Integration

## Overview
This quickstart guide walks through the complete setup and validation of the Saxo Portfolio Home Assistant integration, from initial installation to verifying portfolio data is displayed correctly.

## Prerequisites

### Home Assistant Requirements
- Home Assistant Core 2024.1.0 or later
- HACS (Home Assistant Community Store) installed
- Admin access to Home Assistant configuration
- Internet connectivity for OAuth authentication

### Saxo Bank Requirements  
- Active Saxo Bank investment account
- Saxo Developer Account (free at https://www.developer.saxo/)
- Saxo Application registered with OAuth redirect URI
- Valid API credentials (Application Key and Secret)

### Network Requirements
- Home Assistant accessible from external network (for OAuth callback)
- Firewall allows HTTPS connections to Saxo API endpoints
- DNS resolution for `gateway.saxobank.com` and `sim.logonvalidation.net`

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
   - **Application Type**: "Web Application"
   - **Redirect URI**: `https://my.home-assistant.io/redirect/oauth`
3. Save application and note the **Application Key** and **Application Secret**

### 1.3 Configure OAuth Permissions
1. In application settings, ensure the following permissions are enabled:
   - `Portfolio - Read access to balances`
   - `Portfolio - Read access to positions`
   - `Account - Read access to account information`
2. Save permission changes

## Step 2: Home Assistant Integration Installation

### 2.1 Install via HACS
1. Open Home Assistant web interface
2. Navigate to **HACS** → **Integrations**
3. Click **+ Explore & Download Repositories**
4. Search for "Saxo Portfolio"
5. Click **Download** → **Download** to install
6. Restart Home Assistant when prompted

### 2.2 Alternative: Manual Installation
```bash
# SSH into Home Assistant or use File Editor add-on
cd /config/custom_components
git clone https://github.com/your-username/ha-saxo-portfolio.git saxo_portfolio
# Restart Home Assistant
```

## Step 3: Integration Configuration

### 3.1 Add Integration
1. Navigate to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Saxo Portfolio"
4. Click on "Saxo Portfolio" integration

### 3.2 OAuth Authentication Flow
1. **Application Credentials**: Enter your Saxo Application Key and Secret from Step 1.2
2. **Environment Selection**: Choose "Simulation" for testing or "Production" for live data
3. **Authorize**: Click "Authorize with Saxo Bank"
4. **Saxo Login**: Complete login on Saxo Bank website
5. **Grant Permissions**: Authorize Home Assistant to access portfolio data
6. **Completion**: Return to Home Assistant with successful authentication

### 3.3 Configuration Options
- **Update Interval**: Default 5 minutes (market hours) / 30 minutes (after hours)
- **Base Currency**: Select preferred currency for portfolio aggregation
- **Accounts**: Choose which Saxo accounts to monitor (if multiple)
- **Sensors**: Select which portfolio metrics to track

## Step 4: Verify Installation

### 4.1 Check Device Registration
1. Navigate to **Settings** → **Devices & Services**
2. Find "Saxo Portfolio" integration
3. Click to view device details
4. Verify device shows as "Connected" with last update timestamp

### 4.2 Verify Sensors Created
Expected sensors should appear:
- `sensor.saxo_portfolio_total_value`
- `sensor.saxo_portfolio_cash_balance`  
- `sensor.saxo_portfolio_unrealized_pnl`
- `sensor.saxo_portfolio_positions_count`

### 4.3 Test Data Refresh
1. Go to **Developer Tools** → **States**
2. Find Saxo Portfolio sensors
3. Verify all sensors show numeric values (not "unavailable")
4. Check **Attributes** tab for additional data like currency and last update time

### 4.4 Manual Refresh Test
1. Navigate to **Settings** → **Devices & Services** → **Saxo Portfolio**
2. Click **Configure** → **Reload**
3. Verify sensors update with current timestamp
4. Check Home Assistant logs for any error messages

## Step 5: Dashboard Integration

### 5.1 Create Portfolio Dashboard
```yaml
# Example dashboard card configuration
type: entities
title: Saxo Portfolio Overview
entities:
  - entity: sensor.saxo_portfolio_total_value
    name: Total Portfolio Value
    icon: mdi:chart-line
  - entity: sensor.saxo_portfolio_cash_balance  
    name: Available Cash
    icon: mdi:cash
  - entity: sensor.saxo_portfolio_unrealized_pnl
    name: Unrealized P&L
    icon: mdi:trending-up
  - entity: sensor.saxo_portfolio_positions_count
    name: Open Positions
    icon: mdi:format-list-numbered
show_header_toggle: false
```

### 5.2 Add Portfolio Charts
```yaml
# Historical value chart
type: history-graph
entities:
  - sensor.saxo_portfolio_total_value
hours_to_show: 24
refresh_interval: 300
```

### 5.3 Create Automation Examples
```yaml
# Alert on significant portfolio change
alias: Portfolio Change Alert
trigger:
  - platform: numeric_state
    entity_id: sensor.saxo_portfolio_unrealized_pnl
    above: 1000  # Alert if P&L exceeds $1000
action:
  - service: notify.mobile_app
    data:
      message: "Portfolio P&L is now ${{ states('sensor.saxo_portfolio_unrealized_pnl') }}"
      title: "Portfolio Alert"
```

## Step 6: Validation and Testing

### 6.1 Data Accuracy Verification
1. Compare Home Assistant sensor values with Saxo Bank website/app
2. Verify currency conversions are correct
3. Check that position counts match actual holdings
4. Confirm timestamps indicate recent updates

### 6.2 OAuth Token Refresh Test
1. Wait for token expiration (typically 20 minutes for Saxo)
2. Verify sensors continue updating automatically
3. Check Home Assistant logs for successful token refresh messages
4. No user intervention should be required

### 6.3 Error Handling Test
1. **Network Disconnection**: Disconnect internet temporarily
   - Sensors should show previous values
   - Logs should indicate connection failures
   - Auto-recovery when connection restored
2. **Rate Limit Test**: Request multiple manual refreshes quickly
   - Integration should respect API rate limits
   - No error states in sensor values

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
- Re-run OAuth flow if needed

**Data not updating**
- Verify network connectivity to `gateway.saxobank.com`
- Check API rate limiting in logs
- Confirm Saxo account has active positions/balance

**OAuth authentication fails**
- Verify redirect URI exactly matches Saxo app configuration
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
- Integration GitHub Issues: https://github.com/your-username/ha-saxo-portfolio/issues
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
- Automatic updates occur every 5-30 minutes
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