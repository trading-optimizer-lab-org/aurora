# OpenAP Current Data Quality Contract

## Purpose

This pipeline produces a current cross-sectional Open Asset Pricing score. It
does not backtest the score and does not claim that a value such as 80 means an
80 percent probability of a price increase.

## Universe

Only one primary US common security per SEC CIK can enter the scoring universe.
ETFs, ETNs, funds, investment companies, foreign SEC filers, ADRs, preferred
shares, warrants, rights, units, SPACs and stale securities are excluded.

A common stock enters the ranking only when it also has:

- market capitalization of at least USD 100 million;
- price of at least USD 1;
- 21-day average volume of at least 10,000 shares;
- 21-day average dollar volume of at least USD 1 million;
- at least 252 clean daily price observations;
- no severe price anomaly in the recent quality window.

Every exclusion is retained in `security_universe_exclusions.csv`.

## Prices

`prices_daily` preserves downloaded observations. Features use a cleaned view:
non-positive prices, invalid OHLC rows, duplicate dates and extreme return
breaks are quarantined. History before the last unresolved split-like break is
not used for current features. The decision is recorded per symbol in
`price_quality_current`.

## SEC EDGAR

SEC data is downloaded once per unique CIK. Exact duplicates are removed at
merge. Actual SEC acceptance timestamps are used when available; filing date
plus one day is retained only as a disclosed fallback.

Selected accounting inputs must satisfy all of the following:

- `available_at` is not after the snapshot time;
- `period_end` is not after the snapshot date;
- monetary values use USD;
- share counts use the `shares` unit;
- employee counts use a recognised employee/person unit.

No foreign-currency accounting value is divided by a USD market value.

## Options

Current option proxies use only contracts that are fresh, within the configured
days-to-expiry range, near the current stock price, inside the configured IV
bounds and free of crossed quotes. Realized volatility is annualized before it
is compared with implied volatility.

## Feature Status

`implementation_status` describes whether the formula is exact, proxy or not
implemented. `value_status` describes whether a current value exists. `status`
is usable status: a formula with no current value is `unavailable` and receives
no score weight.

## Redundancy And Score

Signals are direction-aligned before redundancy analysis. A shared redundancy
group requires positive correlation above the threshold, the same economic
family and complete-link agreement with every existing group member. Inverse
signals are recorded as diversification relationships and are not merged.

The score uses one bounded vote per redundancy group. Metric weights and family
weights use the configured caps. Unallocated family weight is neutral at 50,
so a narrow set of related features cannot manufacture an extreme score.

The public leaderboard requires all five horizons and minimum aggregate
confidence. Partial scores remain available for research but cannot enter the
leaderboard.

## Mandatory Gates

The workflow fails if it finds duplicate price keys, future dates, missing SEC
availability timestamps, future selected SEC periods, invalid selected units,
duplicate SEC records, inconsistent feature status or an ineligible leaderboard
row. `data_quality_issues` and `schema_contract` persist these checks in DuckDB.

Locked data is not used. Backtesting and validation-based selection remain
disabled in this current-snapshot pipeline.
