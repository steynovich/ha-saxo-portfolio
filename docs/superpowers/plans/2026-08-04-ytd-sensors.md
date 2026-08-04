# YTD Sensors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two currency-denominated YTD sensors (profit/loss, net transfers) and repoint the existing YTD percentage sensor to a genuine January-1 window.

**Architecture:** The Saxo v4 performance endpoint's `StandardPeriod=Year` is a trailing 12-month window, not year-to-date. A `FromDate`/`ToDate` pair anchored to January 1 replaces it in the existing four-call batch, so all three YTD values come from one response at no extra API cost. Sensors read the parsed values through coordinator getters.

**Tech Stack:** Home Assistant custom integration, Python 3.14+, aiohttp via HA's shared websession, pytest, ruff, mypy (strict).

## Global Constraints

- Python 3.14+ only. The codebase uses PEP 758 unparenthesized `except A, B:` syntax — the `venv/` directory is a stale 3.13 environment and **cannot** run the tests.
- Run tests with `uv run --extra dev pytest`. Baseline before this plan: **634 passed**.
- Lint and type checks must stay clean: `uv run --extra dev ruff check custom_components/`, `uv run --extra dev ruff format custom_components/`, `uv run --extra dev mypy custom_components/` (strict, 11 source files).
- Sanitized logging — never log tokens, client IDs, or monetary amounts. New monetary values must not be added to log statements, not even at DEBUG.
- All entities use `_attr_has_entity_name = True` with `_attr_translation_key`; user-facing strings live in `strings.json` and the 11 files under `translations/`, icons in `icons.json`.
- Rate limiting: keep the 0.5s delay between batched API calls.
- Spec: `docs/superpowers/specs/2026-08-04-ytd-sensors-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `custom_components/saxo_portfolio/api/saxo_client.py` | HTTP calls to Saxo | Delete 4 dead helpers; batch takes `(key, params)` specs incl. Jan-1 window |
| `custom_components/saxo_portfolio/coordinator.py` | Fetch orchestration, parsing, getters | Parse 2 new metrics, repoint YTD %, drop `Year`, 2 new getters |
| `custom_components/saxo_portfolio/sensor.py` | Entity definitions | 2 new sensor classes + registration |
| `custom_components/saxo_portfolio/strings.json` + `translations/*.json` | Entity names | 2 new keys × 12 files |
| `custom_components/saxo_portfolio/icons.json` | Entity icons | 2 new keys |
| `tests/unit/test_saxo_client.py` | Client tests | Delete 21 dead tests; add batch spec tests |
| `tests/unit/test_coordinator.py` | Coordinator tests | Extraction + getter tests |
| `tests/unit/test_sensor_coverage.py` | Sensor tests | New sensor tests |
| `README.md`, `CHANGELOG.md` | Docs | Sensor list + repoint warning |

---

### Task 1: Remove dead v4 client helpers

`get_performance_v4`, `get_performance_v4_ytd`, `get_performance_v4_month` and
`get_performance_v4_quarter` are referenced only by their own tests — no production
code calls them. Removing them first means Task 2 refactors a clean file instead of
adding a fifth near-duplicate.

**Files:**
- Modify: `custom_components/saxo_portfolio/api/saxo_client.py:529-694`
- Modify: `tests/unit/test_saxo_client.py:1261-1575` (delete), `:12-14` (docstring)

**Interfaces:**
- Consumes: nothing
- Produces: `saxo_client.py` containing exactly one v4 method, `get_performance_v4_batch(client_key: str) -> dict[str, dict[str, Any]]` (signature unchanged in this task)

- [ ] **Step 1: Confirm the four methods are unreferenced**

```bash
grep -rn "get_performance_v4_ytd\|get_performance_v4_month\|get_performance_v4_quarter\|get_performance_v4(" \
  custom_components/ | grep -v "def get_performance_v4"
```

Expected: no output. If anything prints, STOP — a caller exists and this task's premise is wrong.

- [ ] **Step 2: Delete the four methods**

In `custom_components/saxo_portfolio/api/saxo_client.py`, delete from the line
`    async def get_performance_v4(self, client_key: str) -> dict[str, Any]:`
(line 529) through the blank line immediately before
`    async def get_net_positions(self) -> dict[str, Any]:` (line 695).

The result must read:

```python
        return results

    async def get_net_positions(self) -> dict[str, Any]:
```

- [ ] **Step 3: Delete their tests**

In `tests/unit/test_saxo_client.py`, delete from the separator comment block
preceding `# Endpoint: get_performance_v4` (line 1261) through the last line of
`TestGetPerformanceV4Quarter` (line 1575). The file must go straight from the end of
`TestGetPerformanceV4Batch` into:

```python
# ---------------------------------------------------------------------------
# Endpoint: get_net_positions
# ---------------------------------------------------------------------------
```

- [ ] **Step 4: Update the module docstring**

Replace lines 12-14 of `tests/unit/test_saxo_client.py`:

```python
- All endpoint methods: get_account_balance, get_client_details, get_performance,
  get_performance_v4_batch, get_net_positions
```

- [ ] **Step 5: Run the suite**

Run: `uv run --extra dev pytest -q`
Expected: `613 passed` (634 minus the 21 deleted tests). Any failure means a
still-live reference was removed.

- [ ] **Step 6: Lint, format, type-check**

```bash
uv run --extra dev ruff format custom_components/ tests/
uv run --extra dev ruff check custom_components/ tests/
uv run --extra dev mypy custom_components/
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add custom_components/saxo_portfolio/api/saxo_client.py tests/unit/test_saxo_client.py
git commit -m "refactor: Drop unused single-period v4 performance helpers

get_performance_v4, _ytd, _month and _quarter were referenced only by
their own tests; get_performance_v4_batch is the sole production caller
of the v4 endpoint."
```

---

### Task 2: Batch fetches a January-1 anchored window

Replace the StandardPeriod-only loop with `(key, params)` specs so one entry can be
date-ranged. The trailing `Year` call is dropped — Task 4 repoints its only consumer.
The caller supplies the dates so the client stays clock-free and trivially testable.

Making the new arguments required breaks that sole caller, so this task also applies
Task 4's Step 4 call-site edit; otherwise the branch carries a commit where mypy fails.

**Files:**
- Modify: `custom_components/saxo_portfolio/api/saxo_client.py:460-527`
- Test: `tests/unit/test_saxo_client.py` (class `TestGetPerformanceV4Batch`)

**Interfaces:**
- Consumes: `get_performance_v4_batch` from Task 1
- Produces: `get_performance_v4_batch(client_key: str, *, ytd_from: str, ytd_to: str) -> dict[str, dict[str, Any]]`, returning keys `alltime`, `ytd`, `month`, `quarter`. `ytd_from`/`ytd_to` are ISO dates (`YYYY-MM-DD`). Task 4 calls this.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_saxo_client.py` inside `class TestGetPerformanceV4Batch`:

```python
    @pytest.mark.asyncio
    async def test_ytd_spec_uses_date_range(self):
        """YTD entry must use FromDate/ToDate, not StandardPeriod."""
        captured: list[dict] = []

        async def mock_make_request(endpoint, params=None):
            captured.append(dict(params or {}))
            return {"KeyFigures": {}}

        client = _make_client(session=MagicMock())
        with (
            patch.object(client, "_make_request", side_effect=mock_make_request),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            await client.get_performance_v4_batch(
                "ck", ytd_from="2026-01-01", ytd_to="2026-08-04"
            )

        assert len(captured) == 4
        ytd_params = captured[1]
        assert ytd_params["FromDate"] == "2026-01-01"
        assert ytd_params["ToDate"] == "2026-08-04"
        assert "StandardPeriod" not in ytd_params
        assert "Balance_YearlyProfitLoss" in ytd_params["FieldGroups"]
        assert "Balance_CashTransfer" in ytd_params["FieldGroups"]

    @pytest.mark.asyncio
    async def test_trailing_year_period_not_requested(self):
        """StandardPeriod=Year is a trailing 12m window and must not be fetched."""
        captured: list[dict] = []

        async def mock_make_request(endpoint, params=None):
            captured.append(dict(params or {}))
            return {"KeyFigures": {}}

        client = _make_client(session=MagicMock())
        with (
            patch.object(client, "_make_request", side_effect=mock_make_request),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            await client.get_performance_v4_batch(
                "ck", ytd_from="2026-01-01", ytd_to="2026-08-04"
            )

        periods = [p.get("StandardPeriod") for p in captured]
        assert "Year" not in periods
        assert periods == ["AllTime", None, "Month", "Quarter"]

    @pytest.mark.asyncio
    async def test_month_quarter_request_keyfigures_only(self):
        """Month/Quarter Balance data has no reader; don't fetch it."""
        captured: list[dict] = []

        async def mock_make_request(endpoint, params=None):
            captured.append(dict(params or {}))
            return {"KeyFigures": {}}

        client = _make_client(session=MagicMock())
        with (
            patch.object(client, "_make_request", side_effect=mock_make_request),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            await client.get_performance_v4_batch(
                "ck", ytd_from="2026-01-01", ytd_to="2026-08-04"
            )

        assert captured[2]["FieldGroups"] == "KeyFigures"
        assert captured[3]["FieldGroups"] == "KeyFigures"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_saxo_client.py::TestGetPerformanceV4Batch -q`
Expected: FAIL — `TypeError: get_performance_v4_batch() got an unexpected keyword argument 'ytd_from'`

- [ ] **Step 3: Replace the method body**

Replace `get_performance_v4_batch` in `custom_components/saxo_portfolio/api/saxo_client.py` (lines 460-527) with:

```python
    async def get_performance_v4_batch(
        self,
        client_key: str,
        *,
        ytd_from: str,
        ytd_to: str,
    ) -> dict[str, dict[str, Any]]:
        """Get all performance timeseries data from Saxo v4 performance API.

        Fetches AllTime, year-to-date, Month and Quarter performance data with
        delays between calls to prevent rate limiting.

        Note that StandardPeriod=Year is a *trailing 12 month* window, not
        year-to-date, so the YTD entry uses an explicit FromDate/ToDate range
        anchored to 1 January. The API rejects FromDate without ToDate.

        Args:
            client_key: Client key for the request
            ytd_from: Start of the year-to-date window, ISO date (YYYY-MM-DD)
            ytd_to: End of the year-to-date window, ISO date (YYYY-MM-DD)

        Returns:
            Dictionary with keys: 'alltime', 'ytd', 'month', 'quarter'
            Each containing performance timeseries data

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        specs: list[tuple[str, dict[str, str]]] = [
            (
                "alltime",
                {
                    "ClientKey": client_key,
                    "StandardPeriod": "AllTime",
                    "FieldGroups": "Balance_CashTransfer,KeyFigures",
                },
            ),
            (
                "ytd",
                {
                    "ClientKey": client_key,
                    "FromDate": ytd_from,
                    "ToDate": ytd_to,
                    "FieldGroups": (
                        "Balance_CashTransfer,Balance_YearlyProfitLoss,KeyFigures"
                    ),
                },
            ),
            (
                "month",
                {
                    "ClientKey": client_key,
                    "StandardPeriod": "Month",
                    "FieldGroups": "KeyFigures",
                },
            ),
            (
                "quarter",
                {
                    "ClientKey": client_key,
                    "StandardPeriod": "Quarter",
                    "FieldGroups": "KeyFigures",
                },
            ),
        ]

        results: dict[str, dict[str, Any]] = {}

        for i, (key, params) in enumerate(specs):
            try:
                response = await self._make_request(API_PERFORMANCE_V4_ENDPOINT, params)

                # Validate response structure
                if not isinstance(response, dict):
                    raise APIError(f"Invalid performance v4 {key} response format")

                _LOGGER.debug(
                    "Performance v4 %s API response structure: %s",
                    key,
                    list(response.keys()) if response else "empty",
                )

                results[key] = response

                # Add delay between calls (except after last one) to prevent rate limiting
                if i < len(specs) - 1:
                    await asyncio.sleep(0.5)

            except AuthenticationError, RateLimitError:
                raise
            except Exception as e:
                _LOGGER.error(
                    "Error fetching performance v4 %s data: %s",
                    key,
                    type(e).__name__,
                )
                raise APIError(f"Failed to fetch performance v4 {key} data")

        return results
```

Note the unparenthesized `except AuthenticationError, RateLimitError:` — that is
PEP 758 syntax and matches the rest of this file. Do not "fix" it.

- [ ] **Step 4: Run the batch tests**

Run: `uv run --extra dev pytest tests/unit/test_saxo_client.py::TestGetPerformanceV4Batch -q`
Expected: the three new tests PASS. Pre-existing tests in this class that call
`get_performance_v4_batch("ck")` without the new keyword arguments will now FAIL.

- [ ] **Step 5: Update the pre-existing batch tests**

Every call to `client.get_performance_v4_batch("ck")` or `("ck_123")` in that class
needs the new keyword arguments. Find them:

```bash
grep -n 'get_performance_v4_batch(' tests/unit/test_saxo_client.py
```

Change each call site to pass the dates, e.g.:

```python
            result = await client.get_performance_v4_batch(
                "ck_123", ytd_from="2026-01-01", ytd_to="2026-08-04"
            )
```

`test_success_all_periods` asserts on the four returned keys — those key names are
unchanged (`alltime`, `ytd`, `month`, `quarter`), so only the call signature moves.
`test_delays_between_calls` still expects `mock_sleep.call_count == 3`; the batch is
still four calls.

- [ ] **Step 6: Run the full suite**

Run: `uv run --extra dev pytest -q`
Expected: `616 passed` (613 + 3 new). The coordinator tests still pass because
`tests/unit/test_coordinator.py` mocks `get_performance_v4_batch` with `AsyncMock`,
which accepts any signature.

- [ ] **Step 7: Lint, format, type-check**

```bash
uv run --extra dev ruff format custom_components/ tests/
uv run --extra dev ruff check custom_components/ tests/
uv run --extra dev mypy custom_components/
```

Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add custom_components/saxo_portfolio/api/saxo_client.py tests/unit/test_saxo_client.py
git commit -m "feat: Fetch a January-1 anchored window in the v4 batch

StandardPeriod=Year is a trailing 12-month window, not year-to-date.
Replace it with an explicit FromDate/ToDate range (the API rejects
FromDate alone) and trim Month/Quarter to KeyFigures, which is all
anything reads. Still four requests per refresh."
```

---

### Task 3: Parse the new YTD metrics

Pure-function work on `_extract_v4_batch_metrics`, a `@staticmethod` — the easiest
place to pin the parsing rules down with tests.

**Files:**
- Modify: `custom_components/saxo_portfolio/coordinator.py:399-426`
- Test: `tests/unit/test_coordinator.py` (class `TestExtractV4BatchMetrics`)

**Interfaces:**
- Consumes: the `ytd` response shape produced by Task 2
- Produces: `_extract_v4_batch_metrics()` additionally returns `ytd_profit_loss: float | None` and `ytd_cash_transfer: float | None`; `ytd_investment_performance_percentage` now derives from the Jan-1 window. Two new private statics: `_current_year_bucket(series) -> float | None`, `_last_series_value(series) -> float | None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_coordinator.py` inside `class TestExtractV4BatchMetrics`:

```python
    def test_ytd_profit_loss_and_transfers(self):
        """YTD currency metrics come from the Jan-1 anchored response."""
        v4_batch = {
            "alltime": {
                "KeyFigures": {"ReturnFraction": 0.32},
                "Balance": {"CashTransfer": [{"Value": 500}, {"Value": 1000}]},
            },
            "ytd": {
                "KeyFigures": {"ReturnFraction": 0.09},
                "Balance": {
                    "YearlyProfitLoss": [
                        {"Date": "2026-12-31", "Value": 1234.56},
                    ],
                    "CashTransfer": [
                        {"Date": "2026-01-02", "Value": 0},
                        {"Date": "2026-04-01", "Value": 250.0},
                    ],
                },
            },
            "month": {"KeyFigures": {"ReturnFraction": 0.02}},
            "quarter": {"KeyFigures": {"ReturnFraction": 0.03}},
        }
        with patch(
            "custom_components.saxo_portfolio.coordinator.dt_util.now"
        ) as mock_now:
            mock_now.return_value = datetime(2026, 8, 4, 12, 0)
            metrics = SaxoCoordinator._extract_v4_batch_metrics(v4_batch)

        assert metrics["ytd_profit_loss"] == pytest.approx(1234.56)
        assert metrics["ytd_cash_transfer"] == pytest.approx(250.0)
        assert metrics["ytd_investment_performance_percentage"] == pytest.approx(9.0)

    def test_ytd_profit_loss_picks_current_year_bucket(self):
        """A multi-year bucket list must select the current calendar year."""
        v4_batch = {
            "ytd": {
                "Balance": {
                    "YearlyProfitLoss": [
                        {"Date": "2025-12-31", "Value": 999.0},
                        {"Date": "2026-12-31", "Value": 111.0},
                    ]
                }
            }
        }
        with patch(
            "custom_components.saxo_portfolio.coordinator.dt_util.now"
        ) as mock_now:
            mock_now.return_value = datetime(2026, 8, 4, 12, 0)
            metrics = SaxoCoordinator._extract_v4_batch_metrics(v4_batch)

        assert metrics["ytd_profit_loss"] == pytest.approx(111.0)

    def test_ytd_metrics_none_when_absent(self):
        """Missing YTD balance data yields None, not 0.0."""
        v4_batch = {"ytd": {"KeyFigures": {"ReturnFraction": 0.09}}}
        metrics = SaxoCoordinator._extract_v4_batch_metrics(v4_batch)

        assert metrics["ytd_profit_loss"] is None
        assert metrics["ytd_cash_transfer"] is None

    def test_ytd_profit_loss_none_when_no_matching_year(self):
        """A bucket list without the current year yields None."""
        v4_batch = {
            "ytd": {"Balance": {"YearlyProfitLoss": [{"Date": "2024-12-31", "Value": 5.0}]}}
        }
        with patch(
            "custom_components.saxo_portfolio.coordinator.dt_util.now"
        ) as mock_now:
            mock_now.return_value = datetime(2026, 8, 4, 12, 0)
            metrics = SaxoCoordinator._extract_v4_batch_metrics(v4_batch)

        assert metrics["ytd_profit_loss"] is None

    def test_ytd_cash_transfer_skips_non_numeric(self):
        """Non-numeric trailing entries are skipped, not returned."""
        v4_batch = {
            "ytd": {
                "Balance": {
                    "CashTransfer": [
                        {"Date": "2026-01-02", "Value": 100.0},
                        {"Date": "2026-04-01", "Value": None},
                    ]
                }
            }
        }
        metrics = SaxoCoordinator._extract_v4_batch_metrics(v4_batch)

        assert metrics["ytd_cash_transfer"] == pytest.approx(100.0)
```

`datetime` and `patch` are already imported at the top of this test file — no import
changes needed.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_coordinator.py::TestExtractV4BatchMetrics -q`
Expected: FAIL with `KeyError: 'ytd_profit_loss'`

- [ ] **Step 3: Implement the parsing**

In `custom_components/saxo_portfolio/coordinator.py`, replace `_extract_v4_batch_metrics` (lines 399-426) with:

```python
    @staticmethod
    def _current_year_bucket(series: list[dict[str, Any]]) -> float | None:
        """Value of the calendar-year bucket matching the current year.

        ``YearlyProfitLoss`` returns one bucket per calendar year. Match on the
        year rather than assuming a single-element list, so a response spanning
        a year boundary cannot select the wrong bucket.
        """
        current_year = str(dt_util.now().year)
        for point in series:
            if str(point.get("Date", "")).startswith(current_year):
                value = point.get("Value")
                if isinstance(value, int | float):
                    return float(value)
        return None

    @staticmethod
    def _last_series_value(series: list[dict[str, Any]]) -> float | None:
        """Last numeric value of a TimeValuePair series, or None."""
        for point in reversed(series):
            value = point.get("Value")
            if isinstance(value, int | float):
                return float(value)
        return None

    @staticmethod
    def _extract_v4_batch_metrics(
        v4_batch: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Parse the v4 performance batch into flat metrics."""
        metrics: dict[str, Any] = {}

        alltime = v4_batch.get("alltime", {})
        alltime_return = alltime.get("KeyFigures", {}).get("ReturnFraction", 0.0)
        metrics["investment_performance_percentage"] = alltime_return * 100.0

        cash_transfer_list = alltime.get("Balance", {}).get("CashTransfer", [])
        if cash_transfer_list:
            metrics["cash_transfer_balance"] = cash_transfer_list[-1].get("Value", 0.0)

        for period_key, result_key in (
            ("ytd", "ytd_investment_performance_percentage"),
            ("month", "month_investment_performance_percentage"),
            ("quarter", "quarter_investment_performance_percentage"),
        ):
            period_return = (
                v4_batch.get(period_key, {})
                .get("KeyFigures", {})
                .get("ReturnFraction", 0.0)
            )
            metrics[result_key] = period_return * 100.0

        # Currency-denominated YTD metrics, from the Jan-1 anchored window.
        # These default to None rather than 0.0: on a money sensor a zero reads
        # as "you earned nothing this year" rather than "no data".
        ytd_balance = v4_batch.get("ytd", {}).get("Balance", {})
        metrics["ytd_profit_loss"] = SaxoCoordinator._current_year_bucket(
            ytd_balance.get("YearlyProfitLoss", [])
        )
        metrics["ytd_cash_transfer"] = SaxoCoordinator._last_series_value(
            ytd_balance.get("CashTransfer", [])
        )

        return metrics
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev pytest tests/unit/test_coordinator.py::TestExtractV4BatchMetrics -q`
Expected: PASS, including the pre-existing `test_full_response` and
`test_empty_response` (they assert on keys this change does not remove).

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest -q`
Expected: `621 passed` (616 + 5 new).

- [ ] **Step 6: Lint, format, type-check**

```bash
uv run --extra dev ruff format custom_components/ tests/
uv run --extra dev ruff check custom_components/ tests/
uv run --extra dev mypy custom_components/
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add custom_components/saxo_portfolio/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat: Parse YTD profit/loss and net transfers from the Jan-1 window

Adds ytd_profit_loss (current calendar-year YearlyProfitLoss bucket) and
ytd_cash_transfer (last CashTransfer value, cumulative within the window).
Both default to None rather than 0.0 so missing data cannot render as a
plausible-looking zero on a currency sensor."
```

---

### Task 4: Wire the coordinator to the new window

Supply the dates, carry the new keys through defaults and cache, and expose getters.

**Files:**
- Modify: `custom_components/saxo_portfolio/coordinator.py:280-301` (defaults), `:379-397` (call site), `:1200-1220` (getters)
- Test: `tests/unit/test_coordinator.py`

**Interfaces:**
- Consumes: `get_performance_v4_batch(client_key, *, ytd_from, ytd_to)` from Task 2; the metric keys from Task 3
- Produces: `SaxoCoordinator.get_ytd_profit_loss() -> float | None` and `SaxoCoordinator.get_ytd_cash_transfer() -> float | None`. Task 5 calls both.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_coordinator.py` (top level, alongside the other coordinator test classes):

```python
class TestYtdGetters:
    """Tests for the YTD currency getters."""

    def test_get_ytd_profit_loss(self):
        """YTD profit/loss is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"ytd_profit_loss": 1234.56}
        assert coord.get_ytd_profit_loss() == pytest.approx(1234.56)

    def test_get_ytd_profit_loss_none_when_missing(self):
        """Missing key returns None, not 0.0."""
        coord = _bare_coordinator()
        coord.data = {}
        assert coord.get_ytd_profit_loss() is None

    def test_get_ytd_profit_loss_none_without_data(self):
        """No data returns None."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_ytd_profit_loss() is None

    def test_get_ytd_cash_transfer(self):
        """YTD net transfers is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"ytd_cash_transfer": 250.0}
        assert coord.get_ytd_cash_transfer() == pytest.approx(250.0)

    def test_get_ytd_cash_transfer_none_when_missing(self):
        """Missing key returns None, not 0.0."""
        coord = _bare_coordinator()
        coord.data = {}
        assert coord.get_ytd_cash_transfer() is None
```

And a test that the batch is called with a January-1 anchor — add it to the existing
`class TestFetchPerformanceMetrics` (line ~530), following that class's style: a real
coordinator from `_bare_coordinator()` and an `AsyncMock()` client.

```python
    async def test_batch_called_with_january_first_anchor(self):
        """The YTD window must start on 1 January of the current year."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_performance = AsyncMock(return_value={})
        client.get_performance_v4_batch = AsyncMock(
            return_value={"alltime": {}, "ytd": {}, "month": {}, "quarter": {}}
        )
        result: dict = {}

        with patch(
            "custom_components.saxo_portfolio.coordinator.dt_util.now"
        ) as mock_now:
            mock_now.return_value = datetime(2026, 8, 4, 12, 0)
            await coord._fetch_performance_metrics(client, "ck1", result)

        kwargs = client.get_performance_v4_batch.call_args.kwargs
        assert kwargs["ytd_from"] == "2026-01-01"
        assert kwargs["ytd_to"] == "2026-08-04"
```

Patching `dt_util.now` here also affects `_current_year_bucket`, which is what the
2026 dates in the mocked response rely on. `datetime`, `patch` and `AsyncMock` are
already imported in this file.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_coordinator.py::TestYtdGetters -q`
Expected: FAIL with `AttributeError: <class 'SaxoCoordinator'> does not have the attribute 'get_ytd_profit_loss'`

- [ ] **Step 3: Add the new keys to the defaults**

In `_build_performance_defaults` (line 280), add two entries to the returned dict,
after `"cash_transfer_balance"`:

```python
            "ytd_profit_loss": cache.get("ytd_profit_loss"),
            "ytd_cash_transfer": cache.get("ytd_cash_transfer"),
```

`cache.get()` without a default returns `None`, which is intentional — unlike the
surrounding metrics these must not fall back to `0.0`.

- [ ] **Step 4: Pass the dates at the call site**

In `_fetch_performance_metrics` (around line 380), replace:

```python
            v4_batch = await client.get_performance_v4_batch(client_key)
```

with:

```python
            now = dt_util.now()
            v4_batch = await client.get_performance_v4_batch(
                client_key,
                ytd_from=f"{now.year:04d}-01-01",
                ytd_to=now.date().isoformat(),
            )
```

- [ ] **Step 5: Keep monetary values out of the logs**

The debug statement immediately below that call logs percentages and
`cash_transfer_balance`. Do **not** add `ytd_profit_loss` or `ytd_cash_transfer` to
it — they are monetary amounts and the project forbids logging balances. Change the
trailing part of the existing call to log presence only:

```python
            _LOGGER.debug(
                "Retrieved batched performance v4 data - AllTime: %s%%, YTD: %s%%, "
                "Month: %s%%, Quarter: %s%%, YTD currency metrics present: %s",
                result["investment_performance_percentage"],
                result["ytd_investment_performance_percentage"],
                result["month_investment_performance_percentage"],
                result["quarter_investment_performance_percentage"],
                result.get("ytd_profit_loss") is not None,
            )
```

Note this also drops `cash_transfer_balance` from the log line, which was a monetary
amount being logged at DEBUG.

- [ ] **Step 6: Add the getters**

In `custom_components/saxo_portfolio/coordinator.py`, after `get_cash_transfer_balance` (line 1209):

```python
    def get_ytd_profit_loss(self) -> float | None:
        """Get year-to-date profit/loss in the account's base currency.

        Returns:
            YTD profit/loss, or None when unavailable

        """
        if not self.data:
            return None
        value = self.data.get("ytd_profit_loss")
        return float(value) if isinstance(value, int | float) else None

    def get_ytd_cash_transfer(self) -> float | None:
        """Get year-to-date net deposits/withdrawals.

        Returns:
            YTD net cash transferred, or None when unavailable

        """
        if not self.data:
            return None
        value = self.data.get("ytd_cash_transfer")
        return float(value) if isinstance(value, int | float) else None
```

- [ ] **Step 7: Run the tests**

Run: `uv run --extra dev pytest tests/unit/test_coordinator.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run --extra dev pytest -q`
Expected: `627 passed` (621 + 6 new).

- [ ] **Step 9: Lint, format, type-check**

```bash
uv run --extra dev ruff format custom_components/ tests/
uv run --extra dev ruff check custom_components/ tests/
uv run --extra dev mypy custom_components/
```

Expected: all clean.

- [ ] **Step 10: Commit**

```bash
git add custom_components/saxo_portfolio/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat: Anchor the YTD performance window to 1 January

Coordinator owns the clock and passes the window to the client. Adds
get_ytd_profit_loss/get_ytd_cash_transfer getters returning float | None,
and stops logging monetary amounts at DEBUG."
```

---

### Task 5: The two new sensors

Both entities plus everything a user sees: names in 12 JSON files, icons, README.
Shipping a sensor without its `strings.json` entry would surface a raw translation
key in the UI, so those belong in this task.

**Files:**
- Modify: `custom_components/saxo_portfolio/sensor.py:311-329` (registration), append two classes near `sensor.py:644`
- Modify: `custom_components/saxo_portfolio/strings.json`, `icons.json`, `translations/{da,de,en,es,fi,fr,it,nb,nl,pt,sv}.json`
- Modify: `README.md:37-42` and `:130-135`
- Test: `tests/unit/test_sensor_coverage.py`

**Interfaces:**
- Consumes: `get_ytd_profit_loss()`, `get_ytd_cash_transfer()` from Task 4
- Produces: entities `ytd_profit_loss` and `ytd_cash_transfer` (unique IDs `saxo_{client_id}_ytd_profit_loss` / `_ytd_cash_transfer`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_sensor_coverage.py`. Extend the `coord` fixture (line ~51)
with the two new return values first:

```python
    c.get_ytd_profit_loss.return_value = 1234.56
    c.get_ytd_cash_transfer.return_value = 250.0
```

and add `"ytd_profit_loss": 1234.56, "ytd_cash_transfer": 250.0` to the `c.data`
dict in that fixture (around line 63). Then add:

```python
class TestYTDCurrencySensors:
    def test_ytd_profit_loss_value(self, coord):
        sensor = SaxoYTDProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == pytest.approx(1234.56)

    def test_ytd_profit_loss_state_class(self, coord):
        sensor = SaxoYTDProfitLossSensor(coord)
        assert sensor._attr_state_class == "measurement"

    def test_ytd_profit_loss_unavailable_when_none(self, coord):
        coord.get_ytd_profit_loss.return_value = None
        sensor = SaxoYTDProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None
        assert sensor.available is False

    def test_ytd_profit_loss_currency_attr(self, coord):
        sensor = SaxoYTDProfitLossSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.extra_state_attributes["currency"] == coord.get_currency()

    def test_ytd_cash_transfer_value(self, coord):
        sensor = SaxoYTDCashTransferSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value == pytest.approx(250.0)

    def test_ytd_cash_transfer_state_class(self, coord):
        sensor = SaxoYTDCashTransferSensor(coord)
        assert sensor._attr_state_class == "total"

    def test_ytd_cash_transfer_unavailable_when_none(self, coord):
        coord.get_ytd_cash_transfer.return_value = None
        sensor = SaxoYTDCashTransferSensor(coord)
        type(sensor).coordinator = PropertyMock(return_value=coord)
        assert sensor.native_value is None
        assert sensor.available is False
```

Add both class names to the `from custom_components.saxo_portfolio.sensor import (...)`
block at the top of the file.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_sensor_coverage.py::TestYTDCurrencySensors -q`
Expected: FAIL with `ImportError: cannot import name 'SaxoYTDProfitLossSensor'`

- [ ] **Step 3: Add the sensor classes**

In `custom_components/saxo_portfolio/sensor.py`, after `SaxoCashTransferBalanceSensor` (ends line 643):

```python
class SaxoYTDProfitLossSensor(SaxoSensorBase):
    """Representation of a Saxo Portfolio YTD Profit/Loss sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "ytd_profit_loss",
            unit_of_measurement=coordinator.get_currency(),
        )
        self._attr_state_class = "measurement"
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.coordinator.get_ytd_profit_loss()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        attributes = super().extra_state_attributes

        if self.coordinator.data:
            attributes["currency"] = self.coordinator.get_currency()

        return attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False

        return self.coordinator.get_ytd_profit_loss() is not None


class SaxoYTDCashTransferSensor(SaxoBalanceSensorBase):
    """Representation of a Saxo Portfolio YTD Net Transfers sensor."""

    def __init__(self, coordinator: SaxoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            "ytd_cash_transfer",
            "get_ytd_cash_transfer",
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False

        return self.coordinator.get_ytd_cash_transfer() is not None
```

- [ ] **Step 4: Register them**

In `async_setup_entry` (line 311), add to the `entities` list after
`SaxoQuarterInvestmentPerformanceSensor(coordinator),`:

```python
        SaxoYTDProfitLossSensor(coordinator),
        SaxoYTDCashTransferSensor(coordinator),
```

- [ ] **Step 5: Add names and icons**

In `custom_components/saxo_portfolio/icons.json`, inside `entity.sensor`, after the
`cash_transfer_balance` entry:

```json
    "ytd_profit_loss": {
      "default": "mdi:trending-up"
    },
    "ytd_cash_transfer": {
      "default": "mdi:bank-transfer"
    },
```

In `custom_components/saxo_portfolio/strings.json` **and each of the 11 files** in
`custom_components/saxo_portfolio/translations/`, inside `entity.sensor`, after the
`ytd_investment_performance` entry:

```json
      "ytd_profit_loss": {
        "name": "YTD Profit/Loss"
      },
      "ytd_cash_transfer": {
        "name": "YTD Net Transfers"
      },
```

The non-English files already carry English names for the existing YTD key, so use
the same English strings rather than inventing translations.

Verify every file parses and got both keys:

```bash
python3 -c "
import json, pathlib
files = ['custom_components/saxo_portfolio/strings.json'] + \
        sorted(str(p) for p in pathlib.Path('custom_components/saxo_portfolio/translations').glob('*.json'))
for f in files:
    d = json.load(open(f))
    s = d.get('entity', {}).get('sensor', {})
    missing = [k for k in ('ytd_profit_loss','ytd_cash_transfer') if k not in s]
    print(('OK   ' if not missing else 'MISS ') + f, missing or '')
"
```

Expected: 12 lines, all `OK`.

- [ ] **Step 6: Update the README**

In `README.md`, add to the performance sensor list (after line 42):

```markdown
- **YTD Profit/Loss**: Year-to-Date profit/loss in your account currency (`sensor.saxo_{clientid}_ytd_profit_loss`)
- **YTD Net Transfers**: Year-to-Date net deposits and withdrawals (`sensor.saxo_{clientid}_ytd_cash_transfer`)
```

and to the example entity list (after line 135):

```markdown
- `sensor.saxo_123456_ytd_profit_loss` - Year-to-Date profit/loss
- `sensor.saxo_123456_ytd_cash_transfer` - Year-to-Date net deposits and withdrawals
```

- [ ] **Step 7: Run the tests**

Run: `uv run --extra dev pytest tests/unit/test_sensor_coverage.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run --extra dev pytest -q`
Expected: `634 passed` (627 + 7 new). Note `tests/integration/test_sensor_creation.py`
and `tests/contract/test_sensor_contract.py` may assert on the number of created
entities — if either fails, update the expected count to include the two new sensors.

- [ ] **Step 9: Lint, format, type-check**

```bash
uv run --extra dev ruff format custom_components/ tests/
uv run --extra dev ruff check custom_components/ tests/
uv run --extra dev mypy custom_components/
```

Expected: all clean.

- [ ] **Step 10: Commit**

```bash
git add custom_components/saxo_portfolio/sensor.py \
        custom_components/saxo_portfolio/strings.json \
        custom_components/saxo_portfolio/icons.json \
        custom_components/saxo_portfolio/translations/ \
        tests/unit/test_sensor_coverage.py README.md
git commit -m "feat: Add YTD profit/loss and YTD net transfers sensors

Two currency-denominated year-to-date sensors reading the Jan-1 anchored
window. Both go unavailable rather than reporting 0.0 when data is missing."
```

---

### Task 6: Document the repoint

The YTD percentage sensor changes value on upgrade. That needs to be findable by a
user who notices, so it doesn't read as a regression.

**Files:**
- Modify: `CHANGELOG.md:8` (the `## [Unreleased]` section)

**Interfaces:**
- Consumes: everything above
- Produces: nothing consumed downstream

- [ ] **Step 1: Write the changelog entry**

In `CHANGELOG.md`, replace the bare `## [Unreleased]` heading (line 8) with:

```markdown
## [Unreleased]

### Added
- **YTD Profit/Loss sensor**: Year-to-date profit/loss in the account's base currency (`sensor.saxo_{clientid}_ytd_profit_loss`)
- **YTD Net Transfers sensor**: Year-to-date net deposits and withdrawals (`sensor.saxo_{clientid}_ytd_cash_transfer`)

### Fixed
- **YTD Investment Performance now measures year-to-date**: the sensor previously used Saxo's `StandardPeriod=Year`, which is a *trailing 12-month* window rather than year-to-date. It now uses an explicit window anchored to 1 January.

  **This changes the reported value.** On a test account the sensor read 17.83% (trailing 12 months) where true year-to-date was 9.32%. The `from`/`thru` attributes already claimed a 1 January start, so they were previously inaccurate; they are now correct.

  Long-term statistics recorded for this entity before the upgrade are trailing-12-month figures, so historical graphs will show a discontinuity at the upgrade point. The `entity_id` is unchanged — dashboards and automations continue to work.

### Changed
- Performance data no longer fetches the trailing `Year` window; the January-anchored request takes its place, keeping the refresh at four API calls
- `Month` and `Quarter` performance requests trimmed to the `KeyFigures` field group
- Removed unused `get_performance_v4`, `get_performance_v4_ytd`, `get_performance_v4_month` and `get_performance_v4_quarter` client methods

### Known Issues
- **Month and Quarter Investment Performance are also trailing windows**, not month-to-date and quarter-to-date: `StandardPeriod=Month` returns a rolling ~28 days and `Quarter` a rolling ~90 days. Their `from`/`thru` attributes are therefore inaccurate. Correcting these is deferred; see `docs/superpowers/specs/2026-08-04-ytd-sensors-design.md`.
```

- [ ] **Step 2: Full verification sweep**

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff format --check custom_components/ tests/
uv run --extra dev ruff check custom_components/ tests/
uv run --extra dev mypy custom_components/
```

Expected: `634 passed`, `already formatted`, `All checks passed!`, `Success: no issues found in 11 source files`.

- [ ] **Step 3: Confirm the API call count did not grow**

```bash
grep -c '"ClientKey": client_key' custom_components/saxo_portfolio/api/saxo_client.py
```

Expected: `4` (one per batch spec). Together with the v3 `get_performance` call and
`get_client_details`, the performance refresh is unchanged in request count.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: Changelog for YTD sensors and the YTD window correction"
```

---

## Post-Deploy Verification

The design rests on ratio evidence rather than absolute amounts — the probe script
deliberately never printed balances. Once deployed, confirm against the Saxo web
platform:

1. `sensor.saxo_{id}_ytd_profit_loss` matches the platform's year-to-date P/L.
2. `sensor.saxo_{id}_ytd_cash_transfer` matches net deposits since 1 January.
3. `sensor.saxo_{id}_ytd_investment_performance` matches the platform's YTD return
   (expected ≈9.32% and ≈20.27% for the two accounts as of 2026-08-04).

The probe script used during design is in the session scratchpad and can be re-run
with `--storage --verify` against the HA host if any value looks wrong.
