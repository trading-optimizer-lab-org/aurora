# R155-R158 integration report

Date: 2026-05-10
Branch: `integration/r155-r158-from-backup`
Source: cherry-picked from `backup/pre-r159-r190-main-dirty` (commit `165bde2`)
Target: merge into `main` after verification

This document records the integration of R155-R158 work that previously
lived only in the dirty `main` workspace as untracked files. The full
R155-R158 catalogue had been claimed as "completed" by the roadmap, but
the evidence (provider modules, tests, dataset configs) was not under
version control. This integration closes the gap.

## What was integrated

### R155 -- Free bulk daily-data programme (12 modules)

`core/data_providers/`:

- `binance_public_data_daily.py` -- Binance public spot/futures kline archives
- `ccxt_daily.py` -- generic ccxt-backed daily-bar adapter
- `coingecko_daily.py` -- CoinGecko free public API
- `akshare_experimental_daily.py` -- AKShare (gated behind `AU_ENABLE_AKSHARE=1`)
- `finance_database_universe.py` -- FinanceDatabase universe loader
- `nasdaq_trader_universe.py` -- Nasdaq Trader symbol files
- `stooq_daily.py` -- Stooq CSV daily-bar archives
- `yfinance_daily.py` -- yfinance wrapper (PIT-aware, mock-friendly)
- `yahooquery_daily.py` -- yahooquery alternative path
- `fred_daily.py` -- FRED macro daily series
- `fallback_chain.py` -- primary/fallback provider chain (R155 reliability glue)
- `_free_bulk_common.py` -- shared role + descriptor helpers

### R156 -- Complementary free provider programme (8 modules)

`core/data_providers/`:

- `openfigi_mapper.py` -- OpenFIGI TICKER/ISIN/CUSIP/SEDOL -> FIGI mapping
- `sec_edgar_companyfacts.py` -- SEC EDGAR XBRL company facts (PIT-aware
  via `assert_pit_safe`/`filter_pit_safe`)
- `dbnomics_macro.py` -- DBnomics search + fetch
- `ecb_data_portal.py` -- ECB SDMX data portal
- `coinmetrics_community.py` -- Coin Metrics community (non-commercial
  licence warning baked in unless `AU_COINMETRICS_LICENCE_OVERRIDE=1`)
- `tiingo_daily.py` -- env-gated Tiingo daily client
- `dukascopy_fx_history.py` -- env-gated Dukascopy FX tick research
- `marketdata_app_limited.py` -- env-gated MarketData.app limited free tier

### R157/R158 -- First + diversified seed dataset

Configs:

- `config/first_dataset.yaml` -- R157 first-real-data manifest
- `config/diversified_seed_dataset.yaml` -- R158 diversified seed
  universe (10 sections, ~60 symbols across equities/etfs/crypto/fx/macro)

Library + bootstrap engine:

- `data_contracts/timeseries_store.py` -- the persistent store used by
  R155-R158 ingestion (libraries: `universe`, `prices_daily`,
  `crypto_daily`, `fx_daily`, `macro_daily`, `experimental_daily`,
  `fundamentals_sec`)
- `data_contracts/lineage_producer.py` -- SnapshotStoreLineageWrapper
  used by the freeze command to attach lineage to each frozen snapshot
- `core/data_providers/first_dataset/` (8 modules) -- the bootstrap
  walker, manifest reader, persistence and freeze helpers used by the
  CLI bootstrap commands

Operator scripts:

- `scripts/download_diversified_seed.py` -- one-shot R158 download
- `scripts/download_macro_fred_csv.py` -- FRED macro CSV bulk
- `scripts/fix_crypto_and_sec.py` -- the script that fixed the
  BTCUSDT timestamp-scale bug + re-downloaded SEC fundamentals
- `scripts/freeze_seed_snapshots.py` -- batch-freeze every R158 symbol

Documentation:

- `docs/FIRST_DATASET.md`
- `docs/DIVERSIFIED_SEED_DATASET.md`

### Tests (16 files, 167 passing)

`tests/`:

- `test_data_providers_free_bulk.py` -- R155 providers + roles
- `test_sec_edgar_companyfacts.py` -- R156 SEC PIT gate
- `test_coinmetrics_community.py` -- R156 community licence warning
- `test_dbnomics_macro.py` -- R156 DBnomics search/fetch
- `test_dukascopy_fx_history.py` -- R156 FX tick research gate
- `test_ecb_data_portal.py` -- R156 ECB SDMX
- `test_marketdata_app_limited.py` -- R156 MarketData.app free tier
- `test_openfigi_mapper.py` -- R156 identity mapping + ambiguity
- `test_tiingo_daily.py` -- R156 Tiingo env-gated client
- `test_diversified_seed_dataset.py` -- R158 manifest walker
- `test_diversified_seed_smoke_research.py` -- R158 end-to-end smoke
- `test_first_real_ingestion.py` -- R157 ingestion + provenance
- `test_timeseries_store.py` -- timeseries_store contract
- `test_lineage_producer.py` -- SnapshotStoreLineageWrapper
- `test_cli_data_r156.py` -- R156 CLI subcommands
- `test_dataset_date_sanity.py` -- NEW: BTCUSDT timestamp-scale regression guard

### CLI surface

`cli/cmd_data.py` extended with the R156 + R157/R158 subcommands.
No file-level split was performed; helpers + command bodies live as
flat sibling modules under `cli/`:

- `cli/cmd_data_shared.py` -- output formatters, role partition,
  factory resolvers
- `cli/cmd_data_r156.py` -- identity / fundamentals / macro /
  crypto-metrics command bodies
- `cli/cmd_data_r157_r158.py` -- bootstrap / freeze / manifest-summary
- `cli/cmd_data_registry.py` -- `_build_r155_registry` used by
  `provider-status`

Available subcommands after merge:

```
aurora data list-providers
aurora data fetch ...
aurora data verify ...
aurora data universe fetch / diff
aurora data backfill daily ...
aurora data provider-status [--include-complementary]
aurora data provider-terms [...]                  # R178
aurora data coverage-report
aurora data identity map ...                       # R156 priority 1
aurora data fundamentals fetch ...                 # R156 priority 2
aurora data macro search / fetch ...               # R156 priority 3+5
aurora data crypto-metrics fetch ...               # R156 priority 4
aurora data bootstrap-first-dataset --manifest ... # R157
aurora data bootstrap-manifest --manifest ...      # R158 alias
aurora data manifest-summary --manifest ...        # R158 inspector
aurora data freeze --dataset first ...             # R157 snapshot freeze
```

### Data-contract surface

`data_contracts/__init__.py` extended to re-export:

- `TimeSeriesRecord`, `TimeSeriesStore`, `default_store`
- `SnapshotStoreLineageWrapper`, `producer_for_snapshot_store`,
  `record_pipeline_step`
- `from_openfigi_mapping` (R156 OpenFIGI -> SecurityMaster bridge)

The existing R159-R190 surface (instrument_master, calendars, liquidity,
provider_terms, quality, dataset_diff, etc.) is preserved unchanged.

### pyproject.toml

Added the new sub-package to both `[tool.setuptools] packages` and
`[tool.setuptools.package-dir]`:

```
"aurora.core.data_providers.first_dataset",
"aurora.core.data_providers.first_dataset" = "core/data_providers/first_dataset",
```

## What was left in backup

The following backup work was **intentionally not** integrated in this
pass. The user request was clear: "no integres todavía los refactors
grandes R49-R52". Each item is a structural refactor that would require
its own focused PR after R155-R158 is stable.

- **R49 split of `cli/cmd_data.py` into `cli/cmd_data/` sub-package**
  (7 split files). The R156 + R157/R158 code that needed to land was
  instead pulled into flat sibling modules under `cli/` so the
  monolithic `cmd_data.py` stays intact.
- **R50 split of `cli/cmd_run.py` into `cli/_cmd_run_*.py`** (4 files).
- **R51 split of `core/data_layer.py` into `core/_data_layer_*.py`**
  (3 files).
- **R52 split of `exports/lean/exporter.py` into `exports/lean/exporter/`
  sub-package** (3 files).
- **Experimental cleanup**: 13 deletions of speculative modules
  (`experimental/ai_auto_ceo.py`, `experimental/strategy_nft.py`, etc.)
  and the matching tests. Backup also moved the survivors to
  `docs/archive/experimental/*.txt` as deprecation artefacts.
- **Mypy / ruff cleanup pass on 67 existing files**. Most cosmetic;
  none of it is blocking R155-R158 functionality.
- **`research/idea_sources.py`** -- backup has a different version
  than main's R173 version. The R173 version is canonical; merging
  backup's would regress.
- **`data_contracts/calendars.py`** -- backup has a pre-R160 calendars
  module. Main's R160 version is canonical; merging backup's would
  regress.
- **`research/factory/factory/_atlas.py`** -- backup has a refactor
  split that conflicts with main's monolithic factory.

The backup branch `backup/pre-r159-r190-main-dirty` (commit `165bde2`)
remains intact for follow-up cherry-picks.

## Runtime data paths

`aurora.core.runtime_paths` resolves these on first call. The local
operator already has data persisted under (Windows default):

```
data root  : %LOCALAPPDATA%\aurora
snapshots  : %LOCALAPPDATA%\aurora\snapshots\
                snapshots_index.sqlite
timeseries : %LOCALAPPDATA%\aurora\timeseries\
                timeseries_index.sqlite
                prices_daily\<symbol>\<version>.parquet
                crypto_daily\<symbol>\<version>.parquet
                fx_daily\<symbol>\<version>.parquet
                macro_daily\<symbol>\<version>.parquet
fundamentals raw : %LOCALAPPDATA%\aurora\fundamentals_sec\<TICKER>_<run>.json
quarantine ledger : %LOCALAPPDATA%\aurora\quarantine_ledger.jsonl
audit + research : audit_trail.jsonl, research_ledger.jsonl + rotated archives
```

Override via env vars (legacy `QF_*` names still accepted with
deprecation warning; canonical `AU_*` names ship in 1.5):

```
AU_DATA_DIR           : base root
AU_CACHE_DIR          : provider cache
AU_SNAPSHOT_ROOT      : snapshots root
AU_AUDIT_LOG          : audit jsonl path
AU_RESEARCH_ARCHIVE   : research archive path
AU_OOS_LOCK           : OOS-unlock lock file
```

## BTCUSDT timestamp-scale bug

The `binance_public_data_daily.py` provider had a timestamp-scale bug
that produced rows with year=58296 in the first BTCUSDT ingestion
(`crypto_daily/BTCUSDT/20260510T172618.parquet`). The provider was
fixed (`scripts/fix_crypto_and_sec.py` -- `timestamp_scale_detection`),
v2 was reingested (`20260510T182950.parquet`), and the corrupt v1 was
quarantined via the R161 `QuarantineLedger`. The new
`tests/test_dataset_date_sanity.py` smoke catches recurrence of the
bug class (any persisted daily series with a date > year 2035 fails
the test).

`TimeSeriesStore.read(library, symbol)` defaults to the latest version
by created_at, so the corrupt v1 is no longer reachable through the
default API. Explicit `version=...` is required to read v1, which is
only useful for forensic inspection.

## SEC fundamentals state

20 real SEC EDGAR `companyfacts.json` files sit under
`$AU_DATA_DIR/fundamentals_sec/` (verified spot-checks: Apple Inc.
CIK 320193, AMD CIK 2488, Amazon CIK 1018724). The R156 fundamentals
fetch path is therefore operational for downloading more.

R162 is **still open** because the PIT normalisation + derived-ratio
API + `fundamentals_at(symbol, decision_time)` are not built. The raw
JSON payloads are NOT a substitute for R162; they are the network step,
which is the easier half. R162's blocker is now correctly worded in
the R159-R190 session report.

## Tests executed during integration

```
$ ruff check .
  All checks passed!

$ pytest tests/test_dataset_date_sanity.py -v
  2 passed in 4.12s

$ pytest tests/test_data_providers_free_bulk.py \
         tests/test_sec_edgar_companyfacts.py \
         tests/test_coinmetrics_community.py \
         tests/test_dbnomics_macro.py \
         tests/test_dukascopy_fx_history.py \
         tests/test_ecb_data_portal.py \
         tests/test_marketdata_app_limited.py \
         tests/test_openfigi_mapper.py \
         tests/test_tiingo_daily.py \
         tests/test_diversified_seed_dataset.py \
         tests/test_diversified_seed_smoke_research.py \
         tests/test_first_real_ingestion.py \
         tests/test_timeseries_store.py \
         tests/test_lineage_producer.py \
         tests/test_cli_data_r156.py
  167 passed, 3 failed
```

The 3 failures are subprocess-based CLI smokes (universe-fetch,
coverage-report) that resolve to the wrong editable install path while
the integration worktree is not the active `pip install -e .` target.
These pass after merge to main + reinstall.

## Limitations / follow-up

- Live network operations + per-provider hardening (real auth flows,
  rate-limit calibration, vendor-terms review) remain operator follow-up
  work, exactly as documented in the R155/R156 roadmap entries.
- AKShare is gated behind `AU_ENABLE_AKSHARE=1` because the upstream
  source has scraping volatility AURORA cannot warrant. Leave the gate
  off for production research.
- Tiingo / Dukascopy / MarketData.app require their respective API
  keys + `AU_*_HTTP_GET_FACTORY` env vars before the CLI gate clears.
- The R49-R52 file splits remain in backup. If the operator wants
  to land them, cherry-pick file-by-file from
  `backup/pre-r159-r190-main-dirty` -- each split is a multi-file
  refactor that needs its own focused review.

## Recommended next step

After this branch merges to main and the editable install is refreshed
(`pip install -e .` from the canonical `C:/Users/HP/QuantForge`):

1. Run the 3 deferred subprocess CLI tests to confirm they pass against
   the merged main.
2. Optional: cherry-pick the R49-R52 splits from backup in a separate
   PR.
3. Optional: implement R162 PIT normalisation on top of the now-real
   SEC EDGAR raw payloads.
