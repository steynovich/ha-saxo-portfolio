# YTD Sensors — Design

Date: 2026-08-04
Status: Approved for planning

## Problem

The integration exposes one YTD sensor (`ytd_investment_performance`, a percentage).
Two currency-denominated YTD datapoints are missing: profit/loss for the year and
net deposits/withdrawals for the year.

While investigating available datapoints, a defect surfaced: **`StandardPeriod=Year`
is a trailing 12-month window, not year-to-date.** The existing "YTD" sensor reports
rolling-1-year performance.

## Evidence

Probed both live accounts on 2026-08-04 against `/hist/v4/performance/timeseries`
with `FieldGroups=Balance,KeyFigures,TimeWeighted`.

### StandardPeriod windows are trailing, not to-date

| Period | Window returned | Span | Anchored to period start? |
|---|---|---|---|
| Month | 2026-07-06 .. 2026-08-03 | 28d | No — MTD starts 2026-07-01 |
| Quarter | 2026-05-05 .. 2026-08-03 | 90d | No — QTD starts 2026-07-01 |
| Year | 2025-08-04 .. 2026-08-03 | 364d | No — YTD starts 2026-01-01 |
| AllTime | inception .. 2026-08-03 | — | n/a |

Identical on both accounts. Impact on the shipped sensor:

| | Displayed (trailing 12m) | True YTD |
|---|---|---|
| Account 1 | 17.83% | 9.32% |
| Account 2 | 29.38% | 20.27% |

### FromDate requires ToDate

`FromDate` alone returns `HTTP 400 InvalidQueryParameters`. With both, the window is
correctly anchored: `FromDate=2026-01-01&ToDate=2026-08-04` → `2026-01-02 .. 2026-08-03`,
n=152.

### Series semantics

- `Balance.CashTransfer` is **cumulative within the requested window**, starting at
  zero at window start. Under `Year` it showed 179 zeros then 81 identical values
  (`sum/last = 81.0`, exactly the nonzero count) — a step function from a single deposit.
- `Balance.YearlyProfitLoss` is **per-calendar-year buckets**, not cumulative
  (AllTime account 1: `[0.321, 1.0, 0.789]` for 2024/2025/2026 — non-monotone).
- The current-year bucket is window-independent: earlier years get clipped by a
  narrower window, but the current year has nothing to clip.

### Cross-window consistency (both accounts, exact)

```
YearlyProfitLoss[2026]  FromDate / AllTime = 1.000000
YearlyProfitLoss[2026]  Year     / AllTime = 1.000000
CashTransfer YTD  FromDate-last / AllTime-delta = 1.000000
(both routes zero this year? False)
```

The transfer check was meaningful — real transfers occurred this year, so it is not a
zero-equals-zero false pass.

### Incidental

- `PerformanceFraction` is identical to `ReturnFraction` in every response — not a
  distinct datapoint.
- `TotalGrossAccruals` is empty; `SecurityTransfer` is all zeros on both accounts.
- `/port/v1/clients/me` carries no `Currency` key; the currency unit comes from the
  balance endpoint via `get_currency()` (`coordinator.py:881`).

## Scope

In scope:

1. New sensor: YTD profit/loss (currency).
2. New sensor: YTD net deposits/withdrawals (currency).
3. Repoint `ytd_investment_performance` to a genuine Jan-1 window, in place.

Out of scope: Month/Quarter remain trailing windows. Their mislabelling is recorded
here but deferred to separate work. No Group A KeyFigures sensors (drawdown, Sharpe,
trade counts) — not requested.

## Design

### Net API cost: zero

Once the YTD percentage is repointed, nothing reads the trailing-`Year` response —
it is that metric's sole source. The `Year` call is dropped and the Jan-1 call takes
its slot. The batch stays at four requests per 2h performance refresh.

All three YTD values come from the single Jan-1-anchored response, so no date
arithmetic against the AllTime series is needed.

### A. API layer — `api/saxo_client.py`

`get_performance_v4_batch()` iterates StandardPeriods only. Refactor to iterate
`(key, params)` specs so one entry can be date-ranged, preserving the existing 0.5s
inter-call stagger and single error path.

| Key | Params | FieldGroups |
|---|---|---|
| `alltime` | `StandardPeriod=AllTime` | `Balance_CashTransfer,KeyFigures` |
| `ytd` | `FromDate=<year>-01-01`, `ToDate=<today>` | `Balance_CashTransfer,Balance_YearlyProfitLoss,KeyFigures` |
| `month` | `StandardPeriod=Month` | `KeyFigures` |
| `quarter` | `StandardPeriod=Quarter` | `KeyFigures` |

Month and Quarter trim to `KeyFigures`; nothing reads their Balance data.

Delete `get_performance_v4`, `get_performance_v4_ytd`, `get_performance_v4_month`,
`get_performance_v4_quarter`. All four are dead production code — referenced only by
their own tests — and a date-ranged fifth variant would compound the duplication.

### B. Coordinator — `coordinator.py`

`_extract_v4_batch_metrics()` gains three reads from the `ytd` response:

- `ytd_investment_performance_percentage` = `KeyFigures.ReturnFraction × 100`
  (repointed from the trailing window)
- `ytd_profit_loss` = the `Balance.YearlyProfitLoss` bucket whose `Date` year matches
  the current year. Matched by year rather than assuming `n == 1`, so a response
  spanning a year boundary cannot silently select the wrong bucket.
- `ytd_cash_transfer` = last value of `Balance.CashTransfer`

The `Year` entry is removed from the batch and from `_extract_v4_batch_metrics()`.

Both `FromDate` and `ToDate` derive from `dt_util.now()` (HA local time), not the
configured market timezone — that setting can be `"any"` (`coordinator.py:151`), and
a user's YTD should follow their wall clock. `ToDate` is the current local date.

Unlike the existing metrics, the two new keys default to `None` rather than `0.0` in
`_build_performance_defaults()`. On a currency sensor, `0.0` reads as "you earned
nothing this year" rather than "no data". The existing 0.0 defaults are left alone.

New getters `get_ytd_profit_loss()` and `get_ytd_cash_transfer()` return `float | None`.

### C. Sensors — `sensor.py`

- `SaxoYTDProfitLossSensor(SaxoSensorBase)` — unit from `get_currency()`,
  `state_class="measurement"`, matching its sibling `SaxoAccumulatedProfitLossSensor`
  (`sensor.py:406`).
- `SaxoYTDCashTransferSensor(SaxoBalanceSensorBase)` — matching
  `SaxoCashTransferBalanceSensor` (`sensor.py:624`), the same kind of cumulative balance.

Both override `available` keyed on their data key being present, following the
existing convention, and return `None` when their value is `None`.
`SaxoBalanceSensorBase` already short-circuits on `None` (`sensor.py:223-224`), so
the `None`-default decision needs no base-class change.

### D. Presentation

New `ytd_profit_loss` and `ytd_cash_transfer` keys in `strings.json`, `icons.json`,
and the 11 files under `translations/`. Locale files already carry English names for
the existing YTD key; new keys follow that pattern rather than inventing translations.

### E. Tests

- Coordinator: extraction of both new metrics; year-matching selects the correct
  bucket; missing bucket yields `None`; absent `ytd` response degrades gracefully.
- Client: batch emits the four expected specs with correct params, including
  `ToDate`; the 0.5s stagger still applies.
- Remove the test classes for the four deleted helpers.
- Update `tests/unit/test_sensor_coverage.py` and the contract tests, which enumerate
  the sensor set.

### F. Docs

README sensor list, and a CHANGELOG entry flagging the repoint prominently: the YTD
percentage drops from 17.83% to 9.32% on account 1 at upgrade, and recorded long-term
statistics for that entity become a mix of trailing-12m history and true YTD going
forward. The discontinuity is inherent to repointing in place.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| YTD window source | `FromDate`/`ToDate` call | Only way to get a true Jan-1 anchor; `ToDate` is mandatory |
| Existing YTD entity | Repoint in place | Keeps `entity_id`; dashboards and automations keep working |
| Trailing-`Year` call | Drop | No reader once repointed; keeps net API cost at zero |
| Missing-data value | `None` → unavailable | `0.0` on a currency sensor is misleading |
| Month/Quarter mislabel | Deferred | Recorded above; correcting all three needs 2 more calls |

## Risks

- **Statistics discontinuity** on the repointed entity. Accepted; mitigated by a
  CHANGELOG note.
- **Year-boundary behaviour** around 1 January: the Jan-1 window is one day wide and
  `YearlyProfitLoss` may hold two buckets. Year-matching handles selection; the
  narrow window is correct, not a bug.
- **Inference on bucket equality** rests on the 1.000000 ratios above rather than on
  absolute amounts, which were deliberately not disclosed. Verifiable post-deploy
  against the Saxo web platform.
