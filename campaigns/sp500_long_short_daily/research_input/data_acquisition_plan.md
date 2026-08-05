# Data acquisition and point-in-time plan

## Objective

Build an immutable, reproducible daily panel that can calculate every eligible candidate at the close of day `t`, execute at the next SPY open, and prove that no value was available only later. The inventory assesses 73 sources; 55 are free and classified as usable now or after explicit repair.

## 1. Directory and provenance contract

Use repository-relative paths under `campaigns/sp500_long_short_daily/`:

```text
data/raw/<provider>/<snapshot_date>/<original_filename>
data/raw_manifest.jsonl
data/normalized/<dataset_id>.parquet
data/normalized_manifest.json
metadata/release_calendar.parquet
metadata/trading_calendar.parquet
metadata/data_lineage.jsonl
```

Every raw object stores URL, retrieval UTC timestamp, HTTP status, content length, SHA-256, provider terms note, parser version and original filename. Raw files are immutable. Any corrected download receives a new snapshot, never an overwrite.

## 2. SPY target and total-return accounting

1. Obtain daily SPY OHLCV from the preferred free source and cross-check date/price continuity against an independent free source.
2. Obtain sponsor distribution events from State Street.
3. Preserve raw prices and events. Do not use adjusted close as if it supplied an adjusted open.
4. Construct split-adjusted OHLC using cumulative split factors only.
5. Compute open-to-next-open total return for a position established at `open(t)`:

```text
long_return_t  = (open_{t+1} + cash_distributions_ex_between_t_and_t+1 - open_t) / open_t
short_return_t = -long_return_t
strategy_return_t = position_t * long_return_t
```

The implementation must specify ex-date treatment and test it against sponsor distributions. With costs fixed to zero, no other deductions are allowed.

## 3. Timestamps and as-of joins

- Daily market values: available only after the official finalization timestamp; a close-t decision cannot use a value published after that decision cutoff.
- Weekly/monthly releases: join on `published_at`, not the economic observation date. Carry the latest released vintage forward until the next release.
- ALFRED: use `realtime_start`/vintage observations. Never query only the latest value for historical feature construction.
- CFTC: Tuesday positions become usable only after the Friday publication timestamp.
- Cross-market closes: convert to UTC and lag any market whose final value was not known by the SPY decision time.
- Backfilled indexes: store both `calculation_date` and `first_dissemination_date`; a backfill is not available before dissemination unless the underlying formula is independently reconstructed from causal inputs.

## 4. Source priority by layer

### Core runnable layer

- SPY daily prices: Stooq as primary free file after adjustment/calendar audit; Yahoo only as an independent reconciliation source; State Street for official distributions.
- VIX/VXO/SKEW/VVIX/term indexes and VIX futures: Cboe official files/dashboards.
- Rates: U.S. Treasury and Federal Reserve H.15/FRED.
- Macro vintages: ALFRED and Philadelphia Fed real-time datasets.
- Positioning: CFTC historical compressed files and FINRA official files.

### Repair-required layer

- ICE BofA spreads and financial-condition indexes: preserve release snapshots; use only vintage-safe/reconstructed histories.
- Breadth archives: validate definitions, provenance, calendars and missing days. Label exchange breadth as a proxy.
- Research convenience files such as Goyal-Welch, Shiller and Baker-Wurgler: acceptable for replication, but causal live history requires component release lags and revisions to be reconstructed.

### Prohibited core dependencies

Paid CRSP/Compustat/OptionMetrics/CME DataMine/Norgate data, current-member Wikipedia reconstruction, sampled Google Trends history and any unversioned scrape that cannot be reproduced.

## 5. Fail-closed missing-data policy

A candidate is not silently imputed. Predeclared rules are:

- release-frequency series: carry the last causally published observation;
- daily market series: no forward fill across a missing expected market session;
- isolated provider outage: retry and use the documented free fallback only if values reconcile within the source-specific tolerance;
- unresolved mismatch: candidate/day is ineligible, and the missingness report records it;
- excessive missingness: the candidate fails the data gate before performance is examined.

## 6. Mandatory data tests

- unique, monotonic dates and contract identifiers;
- expected NYSE sessions and explicit holiday calendar;
- OHLC inequalities and non-negative volume;
- split/distribution reconciliation;
- duplicate and stale-value detection;
- cross-source price-return tolerance report;
- release-date versus observation-date tests;
- ALFRED vintage test using known revised observations;
- CFTC Tuesday/Friday lag test;
- time-zone cutoff test;
- no dates on/after 2021 in train/validation workspaces;
- raw/normalized hash reproducibility;
- schema-drift fixtures for Cboe/CFTC/XLSX sources.

## 7. Data-classification counts

| Classification | Count |
| --- | --- |
| not_free | 11 |
| proxy_only | 4 |
| rejected_bias | 1 |
| rejected_unverifiable | 2 |
| usable_after_repair | 16 |
| usable_now | 39 |

A `usable_after_repair` label is not permission to proceed automatically. The repair tests and source hash must pass before the corresponding candidate enters the computational campaign.
