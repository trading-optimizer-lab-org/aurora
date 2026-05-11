# Diversified seed dataset (R158)

The diversified seed manifest extends the R157 smoke dataset into a
~133-symbol diversified seed covering 10 sections. It is meant as
research orientation -- enough breadth to test market regimes, sector
rotation, risk-on / risk-off, term structure, FX, crypto, and SEC
fundamentals, while staying small enough that a human can audit
failures in the bootstrap report.

This is **not** institutional truth. Most series are research-tier
(Yahoo / Stooq / Binance public data). Use SEC EDGAR for PIT-safe
fundamentals and FRED for macro context.

## Manifest layout

The manifest lives at `config/diversified_seed_dataset.yaml`. The 10
sections are:

| Section             | Asset group           | Trust level     | Library        | Symbols |
|---------------------|-----------------------|-----------------|----------------|---------|
| broad_us_etfs       | equity_index          | research_seed   | prices_daily   | 6       |
| us_sector_etfs      | equity_sector         | research_seed   | prices_daily   | 11      |
| us_large_caps       | equity_single_name    | research_seed   | prices_daily   | 30      |
| international_etfs  | equity_international  | research_seed   | prices_daily   | 15      |
| bonds_rates_etfs    | rates_fixed_income    | research_seed   | prices_daily   | 9       |
| commodities         | commodity             | research_seed   | prices_daily   | 9       |
| fx                  | fx_spot               | reference_seed  | fx_daily       | 8       |
| crypto              | crypto_spot           | reference_seed  | crypto_daily   | 10      |
| macro               | macro_indicator       | context_seed    | macro_daily    | 15      |
| fundamentals        | company_fundamentals  | official_pit    | fundamentals   | 20      |

Trust levels are documented in
`core/data_providers/first_dataset/_manifest.py::_KNOWN_TRUST_LEVELS`:

* `research_seed` -- third-party redistribution (Yahoo, Stooq). Treat
  as orientation only; survivorship and adjustment posture are not
  guaranteed.
* `reference_seed` -- vendor-curated daily series (Binance public,
  Stooq with vendor tags). Closer to canonical than Yahoo.
* `context_seed` -- macro filters (FRED / ECB). Used as regime
  context; never a strategy's only signal.
* `official_pit` -- regulator-published, point-in-time (SEC EDGAR
  XBRL company facts). Apply
  `aurora.core.data_providers.sec_edgar_companyfacts.filter_pit_safe`
  before consumption.

## Inspecting the manifest (no network)

```
aurora data manifest-summary --manifest config/diversified_seed_dataset.yaml
```

Add `--output json` for a machine-readable form. This subcommand only
parses the YAML; it does not fetch or persist anything, so it stays
distinct from "what has actually been ingested".

## Dry-running and bootstrapping

```
# Dry run -- exercises providers + validators without writing.
aurora data bootstrap-manifest \
    --manifest config/diversified_seed_dataset.yaml \
    --dry-run

# Real run.
aurora data bootstrap-manifest \
    --manifest config/diversified_seed_dataset.yaml
```

`bootstrap-manifest` is an alias for `bootstrap-first-dataset`; use the
new name when the manifest is no longer "first". A JSON report is
written to `runtime_paths.cache_dir() / 'first_dataset_report.json'`.

## Coverage report

```
# Per-symbol detail (R157 form).
aurora data coverage-report --dataset diversified_seed

# R158 compact requested-vs-persisted table.
aurora data coverage-report \
    --dataset diversified_seed \
    --requested-vs-persisted
```

The compact form prints per-section counts of requested vs attempted
vs persisted vs failed vs fallback symbols, plus a grand total row.
Failures are explained in plain English in the per-symbol detail
listing -- contract violations carry the validator's error tuple.

## Freezing snapshots

Single symbol (R157):

```
aurora data freeze --dataset diversified_seed \
    --symbol SPY --library prices_daily
```

Multi-symbol (R158):

```
# Explicit list -- per-symbol failures are reported but the loop
# keeps going across the rest.
aurora data freeze --dataset diversified_seed \
    --symbols SPY,TLT,GLD,EFA,BTCUSDT,DGS10 \
    --library prices_daily

# All persisted symbols in a section, walked from the bootstrap
# report (libraries are pulled per-section).
aurora data freeze --dataset diversified_seed --section equities
```

The recommended seed of frozen snapshots after a fresh run is one
symbol per major section: `SPY` (equity), `BTCUSDT` (crypto),
`DGS10` (macro). That trio is enough to drive a smoke backtest and
the smoke research suite.

## Symbol normalisation table

The orchestrator carries the canonical (Aurora) spelling everywhere
and translates per provider only at the wire boundary. Top entries
in the registry (full table in
`core/data_providers/first_dataset/_symbol_map.py`):

| Canonical | Provider              | Provider symbol |
|-----------|-----------------------|-----------------|
| BRK-B     | stooq                 | BRK-B.US        |
| BRK-B     | yfinance_daily        | BRK-B           |
| BRK-B     | yahooquery_daily      | BRK-B           |
| EURUSD    | yfinance_daily        | EURUSD=X        |
| EURUSD    | yahooquery_daily      | EURUSD=X        |
| EURUSD    | stooq                 | EURUSD.FX       |
| EURUSD    | dukascopy_fx_history  | EUR/USD         |
| GBPUSD    | yfinance_daily        | GBPUSD=X        |
| USDJPY    | stooq                 | USDJPY.FX       |
| DXY       | yfinance_daily        | DX-Y.NYB        |
| DXY       | stooq                 | ^DXY            |

When a symbol has no registered mapping, `normalise_symbol` returns
the canonical spelling unchanged. Any successful normalisation is
recorded in the lineage extras (`symbol_canonical`,
`symbol_normalised_from`, `symbol_normalised_to`) and surfaced as a
warning in the bootstrap report.

## Strict contract gates

In addition to the per-provider contract validator, R158 layers
defence-in-depth checks at persistence time
(`core/data_providers/first_dataset/_persist.py`):

* **required_columns** -- per-section spec from `expected_fields`.
* **monotonic_dates / no_duplicates** -- redundant with the contract
  gate; refuses anyway.
* **OHLC bands** -- high >= max(open, close); low <= min(open, close).
* **non-positive prices** -- any zero / negative price -> reject.
* **extreme_return_spike** -- `|daily_return| > 100%` -> reject;
  `> 50%` -> warning. Catches feed corruption (a 200% one-day move
  on SPY is technically valid OHLCV, but it is a feed bug).
* **calendar_gap** -- daily series with a gap > 5 calendar days
  between consecutive timestamps -> warning. Holidays are fine; a
  10-day gap is suspect.
* **timezone policy** -- any non-UTC timezone -> reject.
* **empty frame** -- explicit reject so the failure is recorded.

Hard rejects raise `PersistenceContractViolation`; the walker turns
the exception into a per-symbol failure with `contract_errors`
populated and no row written to the store.

## What is NOT in this dataset

* Survivorship-corrected universes -- the manifest is a fixed list;
  delisted issuers are absent unless the symbol is still present at
  list time. Use `aurora data universe` for time-aware universes.
* Adjusted price series with PIT-correct dividend / split histories.
  Stooq is `MIXED` posture; Yahoo is `RAW` for `=X` FX pairs.
  Verify before consuming for backtests longer than a few months.
* Roll-adjusted futures continuous series. The commodity ETFs are
  proxies, not the underlyings.
* Order-book / tick data. FX is daily-only; intraday FX is gated by
  the deferred Dukascopy provider behind `AU_ENABLE_DUKASCOPY=1`.

## Deleting + rebuilding

The timeseries store and snapshot store live under
`runtime_paths.base_data_dir()`:

* `$AU_DATA_DIR/timeseries_index.sqlite` and
  `$AU_DATA_DIR/<library>/<symbol>/<version>.parquet`
* `$AU_DATA_DIR/snapshots/<sha256>.parquet`
* `$AU_CACHE_DIR/first_dataset_report.json`

Removing the data directory rebuilds the store on the next run; the
snapshot store rebuilds itself idempotently as long as the timeseries
data is present.

## Operator runbook (live mode)

Live network ingestion is **not** exercised in unit tests. To run
against real providers, supply `http_clients` factories via the
`AU_FIRST_DATASET_HTTP_CLIENTS_FACTORY` environment variable. The CLI
will not open a network socket on its own. See
`tests/test_first_real_ingestion.py::test_cli_bootstrap_first_dataset_dry_run`
for the factory wiring.

Real-run acceptance checklist:

1. `aurora data manifest-summary` shows the expected section / symbol
   counts.
2. `aurora data bootstrap-manifest --dry-run` reports zero contract
   violations.
3. `aurora data bootstrap-manifest` (no dry run) reports
   `requested == persisted` per section, modulo intentional gaps that
   surface as documented warnings (calendar gap, fallback used).
4. `aurora data freeze --section <section>` produces a SnapshotStore
   row per persisted symbol.
5. Smoke research (see `tests/test_diversified_seed_smoke_research.py`)
   runs from the local store with no network access.
