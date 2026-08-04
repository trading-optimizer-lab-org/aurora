# SP500 Long/Short Daily Campaign Mapping

## Immutable contract

- Instrument: SPY only.
- Position: exactly `+1` or `-1`; never cash or leverage.
- Decision: after regular close `t`.
- Execution: next tradable SPY open `t+1`.
- Headline costs: all six cost fields are exactly zero.
- Train: no later than `2010-12-31`.
- Validation: `2011-01-01` through `2020-12-31`, once after freeze.
- Locked: every observation dated `2021-01-01` or later is forbidden.

The authoritative research package is preserved byte-for-byte under
`input_package/` and extracted under `research_input/`.

## Repository mapping

| Research responsibility | Aurora implementation |
| --- | --- |
| Package hashes, cardinality, immutable boundaries | `infra/sp500_long_short_daily/contracts.py` |
| Bounded acquisition, release-time joins, source reconciliation | `infra/sp500_long_short_daily/data.py` |
| Open-to-open total-return accounting | `infra/sp500_long_short_daily/ledger.py` |
| Candidate and benchmark state machines | `infra/sp500_long_short_daily/signals.py` |
| Multiple testing and frozen train score | `infra/sp500_long_short_daily/statistics.py` |
| GitHub scientific workload, merge, freeze, outputs | `infra/sp500_long_short_daily/workload.py` |
| Unit and boundary tests | `tests/test_sp500_long_short_daily_campaign.py` |
| GitHub orchestration | `.github/workflows/sp500-long-short-daily-campaign.yml` |

## Family coverage

Every family has six frozen candidates. A rejection is terminal and remains in
`eligibility_and_rejections.csv`; it is never converted to a zero return.

### Implemented exactly from the frozen rules

`price_trend_sma`, `time_series_momentum`, `short_horizon_reversal`,
`trend_ensemble`, `dual_ma_cross`, `price_breakout`,
`volume_conditioned_reversal`, `variance_risk_premium_proxy`,
`vix_extreme_reversal`, `vix_level_change`, `realized_volatility_state`,
`yield_curve_regime`, `credit_spread_regime`,
`financial_conditions_regime`, `monetary_inflation_regime`,
`calendar_seasonality`, `overnight_futures_proxy`,
`volatility_conditioned_trend`, `vix_term_structure`, and
`simple_rule_ensemble`.

An implemented family can still fail its data gate. In particular, VIX3M was
first disseminated after the train boundary and a bounded causal VIX-futures
adapter is unavailable.

### Precise frozen rejections

| Family | Reason |
| --- | --- |
| `breadth_trend_proxy` | `DATA_INELIGIBLE:PROXY_ONLY_DS071` |
| `breadth_thrust_proxy` | `DATA_INELIGIBLE:PROXY_ONLY_DS071` |
| `correlation_dispersion_proxy` | `DATA_ADAPTER_REQUIRED:DS056_CAUSAL_SECTOR_TOTAL_RETURN_PANEL` |
| `cross_asset_risk_off` | `INCOMPLETE_FROZEN_RULE_SPEC:CROSS_ASSET_COMPONENT_SIGNS` |
| `markov_regime_filtered` | `INCOMPLETE_FROZEN_MODEL_SPEC:MARKOV_MODEL_RESTART_AND_CONVERGENCE_GRID` |
| `regularized_logit` | `INCOMPLETE_FROZEN_MODEL_SPEC:MISSING_DECLARED_HYPERPARAMETER_GRID` |
| `sentiment_positioning` | `INCOMPLETE_FROZEN_RULE_SPEC:CAUSAL_STANDARDIZATION_WINDOW_AND_STALENESS` |
| `valuation_equity_premium` | `INCOMPLETE_FROZEN_MODEL_SPEC:VALUATION_RECURSIVE_ESTIMATION_CONSTRAINTS` |

`STRAT0126` is additionally rejected as
`INCOMPLETE_FROZEN_RULE_SPEC:INFLATION_ACCELERATION_HORIZON`; the pack names
inflation acceleration but does not freeze its horizon.

## External inputs and fail-closed behavior

Training dividend events are Yahoo operational rows accepted only after a
two-layer official audit: exact State Street events for 2006-2010 and audited
SEC fiscal totals for 1993-2009. The overlap is intentional. The ledger never
uses an unaudited event.

Validation still requires an exact State Street file containing only
`2011-01-01..2020-12-31` and remains unopened until the frozen one-shot gate.

A FRED API key enables ALFRED initial-release vintages. If it is absent or one
series fails, only candidates requiring that dataset are rejected. Price-only
and other fully available candidates continue; there is no silent substitution.

## Metrics and diagnostics

Static rules have no fitted parameters, so their calendar-year 1998-2010 rows
are labelled explicitly as out-of-fold static evaluations with one-session
embargo. Families needing estimation are rejected when the frozen package does
not specify the complete fitting protocol.

The non-binding market-regime diagnostic uses the already mandatory symmetric
SMA-200 benchmark's next-open executed state: `spy_above_sma200` and
`spy_at_or_below_sma200`. This definition is frozen before performance is run,
does not alter candidate signals and is excluded from selection.
