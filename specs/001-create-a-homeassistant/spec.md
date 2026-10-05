# Feature Specification: Saxo Portfolio Home Assistant Integration

**Feature Branch**: `001-create-a-homeassistant`  
**Created**: 2025-09-10  
**Status**: Implemented (shipped; kept in line with the code, README and `docs/adr/`)  
**Input**: User description: "Create a HomeAssistant integration using HACS. It should be compatible with HACS Gold status. The purpose of this HomeAssistant integration is to provide sensors from Saxo Portfolio. Data can be collected using the Saxo SaxoOpenApi"

## Execution Flow (main)
```
1. Parse user description from Input
   → Description provides clear purpose: Saxo Portfolio sensors for Home Assistant
2. Extract key concepts from description
   → Actors: Home Assistant users, HACS system
   → Actions: Install integration, configure portfolio access, monitor financial data
   → Data: Portfolio information, account balances, positions, performance metrics
   → Constraints: HACS Gold compatibility requirements
3. Clarifications resolved:
   → Portfolio metrics: Account balance, positions, P&L, total value
   → Authentication: OAuth 2.0 Authorization Code Grant for a confidential client, without PKCE (see FR-003 and ADR 0001)
   → Data refresh: Every 5 minutes during market hours, 30 minutes after hours
4. Fill User Scenarios & Testing section
   → Primary flow: Install via HACS → Configure API credentials → View portfolio sensors
5. Generate Functional Requirements
   → HACS compatibility, sensor creation, data fetching, error handling
6. Identify Key Entities
   → Portfolio, Account, Position, Sensor
7. Run Review Checklist
   → All clarifications resolved
8. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story
A Home Assistant user wants to monitor their Saxo Bank investment portfolio directly from their home automation dashboard, allowing them to track account performance, positions, and financial metrics alongside other home data without switching between applications.

### Acceptance Scenarios
1. **Given** a Home Assistant instance with HACS installed, **When** the user searches for "Saxo Portfolio" in HACS, **Then** the integration appears as an installable component
2. **Given** the integration is installed, **When** the user provides valid Saxo API credentials, **Then** the system successfully authenticates and creates portfolio sensors
3. **Given** portfolio sensors are configured, **When** the user views their Home Assistant dashboard, **Then** current account balance, positions, and performance data are displayed
4. **Given** the integration is running, **When** market data changes, **Then** sensors update automatically within 5 minutes during market hours

### Edge Cases
- What happens when Saxo API credentials are invalid or expired?
- How does the system handle network connectivity issues?
- What occurs when Saxo API rate limits are exceeded?
- How are multiple portfolios/accounts managed if user has several?

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: System MUST be installable through HACS (Home Assistant Community Store)
- **FR-002**: System MUST follow Home Assistant integration conventions and ship HACS metadata and documentation (README, SECURITY.md, ADRs), with Ruff linting and strict MyPy type checking. *Note (#41): the original wording asked for "HACS Gold status", which does not exist (see research.md); the Home Assistant Quality Scale is a Core concept. `custom_components/saxo_portfolio/quality_scale.yaml` is a self-assessment against the Quality Scale rules (several Gold rules are still `todo`); `manifest.json` has no `quality_scale` key, so no official tier is claimed.*
- **FR-003**: System MUST authenticate with Saxo OpenAPI using the OAuth 2.0 Authorization Code Grant for confidential clients (App Key and App Secret, no PKCE), with credentials supplied through Home Assistant Application Credentials (ADR 0001, ADR 0005)
  - *Note (2026-09, #23): PKCE is intentionally not used.* Saxo documents two separate grant types that are chosen when the app is registered: the **Authorization Code Grant** for server-side (confidential) apps, where the token request is authenticated with the AppKey and AppSecret via HTTP Basic Auth ([docs](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant)), and the **Authorization Code Grant with PKCE** for native (public) apps. The PKCE variant sends only `client_id` + `code_verifier`, with no secret, and requires the same `code_verifier` again on every refresh-token request ([docs](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant-pkce), [security overview](https://www.developer.saxo/openapi/learn/security)). Saxo does not document combining PKCE with a client secret. Home Assistant's `LocalOAuth2ImplementationWithPkce` also does not persist the verifier for refreshes. The integration therefore uses the confidential Authorization Code Grant: the App Secret is kept server-side in Home Assistant's Application Credentials, and the authorization code can only be redeemed with it. CSRF is covered by HA's signed `state` parameter. Verified live on SIM (2026-09-28): a Code-grant app accepts a `code_challenge` on the authorize request but does not check the `code_verifier` (a mismatching verifier still got a token), so PKCE adds no protection for this app type. LIVE was not tested for PKCE; the flow without PKCE was confirmed working on LIVE.
  - Users register their own Saxo app with the **Code** grant type and enter its App Key and App Secret in Home Assistant's Application Credentials.
  - The config flow validates the credentials against the API before the entry is created.
  - Reauthentication happens in the UI without removing the integration (including a user-triggered button). It MUST use the same Saxo account the entry was created with (same-account rule); a different account is rejected so entities and history are never re-attached to another account (ADR 0005).
- **FR-004**: System MUST create Home Assistant sensors displaying portfolio data
- **FR-005**: System MUST provide account balance, profit/loss and performance data, and total portfolio value as sensors; individual position sensors are opt-in through the options flow
- **FR-006**: System MUST handle API authentication failures gracefully with user-friendly error messages
- **FR-007**: System MUST refresh portfolio data every 5 minutes during market hours and every 30 minutes after market close (market-hours aware, fixed, not configurable; ADR 0004). With the market timezone set to "Any", market-hours scheduling is off and data refreshes at a fixed 15-minute interval at all times (ADR 0006)
  - *Known limitation:* market hours are the configured market's regular weekday open/close times, DST-aware. Exchange holidays, half days and lunch breaks (e.g. Tokyo, Hong Kong, Singapore) are not modelled, so a holiday weekday is polled at the market-hours rate (ADR 0006).
- **FR-008**: System MUST respect Saxo API rate limits and implement appropriate throttling (0.5 s between batched calls, random start stagger across accounts)
- **FR-009**: Users MUST be able to opt in to per-position sensors and set the market timezone through the options flow. The refresh interval is not user-configurable
- **FR-010**: System MUST log integration events for troubleshooting purposes
- **FR-011**: System MUST provide configuration validation to ensure OAuth 2.0 credentials are correct
- **FR-012**: System MUST securely store and refresh OAuth 2.0 access tokens
- **FR-013**: System MUST handle OAuth token expiration and automatic renewal using refresh tokens, refreshed proactively at half of the token lifetime (ADR 0005)
- **FR-014**: System MUST provide diagnostic sensors (Client ID, Account ID, Display Name, Token Expiry, Market Status, Last Update, Timezone and, when position sensors are enabled, Market Data Access). The Market Status sensor exposes the active and configured update intervals as attributes and the Timezone sensor exposes the configured timezone and market hours; there is no separate "update configuration" sensor
- **FR-015**: System MUST provide investment-performance sensors for all-time, year-to-date, month and quarter spans. The month and quarter figures are Saxo's trailing `StandardPeriod` windows (about 28 and 90 days, ending at the last completed day), not calendar month/quarter-to-date; the sensors expose the covered date range in their attributes (`STANDARD_PERIOD_*_SPAN` in `const.py`)
- **FR-016**: The config entry title MUST be updated from "Saxo Portfolio" to "Saxo Portfolio (<Client ID>)" once the client ID is known, so several entries (and reauthentication prompts) can be told apart
- **FR-017**: If the client name is unknown at first setup (so entity-prefix based sensors were skipped) and becomes known on a later update, System MUST reload the config entry once to create the sensors. A startup phase (the first 3 successful updates) and setup/sensor-initialised flags in the coordinator prevent reloads during normal setup

### Key Entities *(include if feature involves data)*
- **Portfolio**: Represents a Saxo investment portfolio with account information, total value, and performance metrics
- **Account**: Individual Saxo trading account containing positions and balance information. Each config entry covers one Saxo client; multiple clients are added as separate entries
- **Position**: Specific investment holdings with quantity, current value, and profit/loss data
- **Sensor**: Home Assistant entity that displays financial data with appropriate units and state information

---

## Review & Acceptance Checklist
*GATE: Automated checks run during main() execution*

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous  
- [x] Success criteria are measurable
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities resolved
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

---