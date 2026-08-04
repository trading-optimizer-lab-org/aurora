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

## External inputs still required

The campaign intentionally fails before performance calculation until both are
available:

1. A State Street SPY distribution CSV bounded to the active phase. The train
   file must contain only events through `2010-12-31`; the validation file must
   contain only `2011-01-01..2020-12-31`. Columns are `ex_date,distribution`.
2. A free FRED API key in GitHub secret `FRED_API_KEY`, required to request
   ALFRED initial-release vintages instead of revised current history.

Current State Street downloads contain locked dates and are deliberately not
used. Yahoo distributions are only a reconciliation source and never silently
replace the required sponsor snapshot.

## Metrics and declared limitation

Train metrics are based on calendar outer folds 1998-2010. The package requires
performance by a "frozen market regime" but provides no regime definition. The
output records
`INCOMPLETE_FROZEN_DIAGNOSTIC_REGIME_DEFINITION` for that non-selection
diagnostic rather than inventing one.
