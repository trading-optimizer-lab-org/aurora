# First Dataset (R157)

R157 bridges the R155 + R156 provider connectors into a real, audited,
locally-persisted seed dataset. This is the *operational smoke
dataset*, not production research truth.

## What R157 is

- A small audited slice covering one ETF/equity series, one crypto
  series, one macro series, one identity mapping and one fundamentals
  bundle.
- A persistent on-disk store under `aurora.core.runtime_paths`
  (parquet + sqlite via `TimeSeriesStore`), plus at least one approved
  `SnapshotStore` row.
- Deterministic in tests: every provider client is injectable; nothing
  in the unit-test path opens the network.

## What R157 is NOT

- Not a global bulk download.
- Not production trading data.
- Not a substitute for paid / institutional providers.
- Not a full survivorship / corporate-actions solution.

## Workflow

### 1. Inspect what is registered

```
aurora data provider-status --include-complementary
```

Lists the R155 + R156 providers and reports which ones are env-gated
(SEC EDGAR User-Agent, OpenFIGI HTTP transport, DBnomics / ECB HTTP
transport, etc).

### 2. Dry-run the manifest

```
aurora data bootstrap-first-dataset \
    --manifest config/first_dataset.yaml \
    --dry-run
```

A dry-run runs every fetcher + contract validator but does NOT call
`TimeSeriesStore.put`. It is the safe way to confirm provider auth and
response shape before persisting.

### 3. Real bootstrap

```
aurora data bootstrap-first-dataset --manifest config/first_dataset.yaml
```

Operator action required for several providers:

- **Stooq**: rate-limited at the source. May return CAPTCHA / API-key
  pages when stressed. The orchestrator detects these and falls back
  to `yfinance_daily` / `yahooquery_daily` (recorded in the report
  with reliability=`COMMUNITY`).
- **SEC EDGAR**: requires `AU_SEC_EDGAR_USER_AGENT="<name> <email>"`.
- **OpenFIGI**: requires an injected `http_post` callable. Real
  callers wire `requests.post` (or equivalent) via a factory under
  `AU_OPENFIGI_HTTP_POST_FACTORY=<module>:<callable>`.
- **FRED**: routes through `aurora.altdata.fred_macro`; an API key is
  optional (raises rate limit ceiling).

The bootstrap writes a JSON report to
`<AU_CACHE_DIR>/first_dataset_report.json`.

### 4. Read the coverage report

```
aurora data coverage-report --dataset first
```

Reads the JSON report saved above and explains each section in plain
language: requested vs fetched vs failed, which provider won, which
fell back, and the contract errors that blocked any rejected rows.

### 5. Freeze a snapshot

```
aurora data freeze --dataset first --symbol SPY --library prices_daily
```

Refuses to freeze if the requested symbol / library is missing from
the timeseries store, or if the stored frame has duplicate / non-
monotonic timestamps. The frozen `<sha256>.parquet` lands under
`<AU_SNAPSHOT_ROOT>` alongside `snapshots_index.sqlite`.

### 6. Run a backtest from local data

```
aurora run --symbol SPY --source snapshot --strategy ma_cross
```

Or, equivalently, in Python:

```python
from aurora.core.data_providers.first_dataset import (
    load_from_first_dataset,
)
df = load_from_first_dataset("SPY", library="prices_daily")
```

The backtest never opens the network -- the snapshot is read from
disk and the index hash is verified.

## Manifest format

`config/first_dataset.yaml` declares one top-level mapping with
`name`, `start`, `end` and `sections`. Each section is keyed by
asset-class name and carries:

- `symbols`: the symbols / FRED series ids / tickers to fetch
- `providers`: ordered fallback chain. The first that returns a
  contract-valid frame wins; rejections are recorded in the report.
- `library`: target `TimeSeriesStore` library
  (`prices_daily`, `crypto_daily`, `macro_daily`, `identity`,
  `fundamentals`).
- `allow_fallback`: when False, only the first provider is tried; if
  it fails, the symbol is recorded as failed with no fallback
  attempts.

## Reliability matrix

| Section       | Primary               | Reliability | Notes                                          |
|---------------|-----------------------|-------------|------------------------------------------------|
| equities      | `stooq`               | OFFICIAL    | Rate-limited; falls back to community sources. |
| equities      | `yfinance_daily`      | COMMUNITY   | Fallback only. Tagged `unofficial_source`.     |
| equities      | `yahooquery_daily`    | COMMUNITY   | Fallback only. Tagged `unofficial_source`.     |
| crypto        | `binance_public_data` | OFFICIAL    | Per-month ZIP archives.                        |
| macro         | `fred_macro`          | OFFICIAL    | API-key optional.                              |
| macro         | `dbnomics_macro`      | OFFICIAL    | Series-key map required (skipped by default).  |
| macro         | `ecb_data_portal`     | OFFICIAL    | Series-key map required (skipped by default).  |
| identity      | `openfigi_mapper`     | OFFICIAL    | Preserves ambiguity by default.                |
| fundamentals  | `sec_edgar_companyfacts` | OFFICIAL | PIT-aware. User-Agent env required.            |

## Out of scope

- Live trading.
- Treating Yahoo fallback data as institutional truth.
- Full corporate-actions / survivorship handling.
- Bulk downloads of the entire OpenFIGI / FRED / SEC universe.
- Paid provider strategy.

## Inspecting / rebuilding

The store is content-addressed. To rebuild a section, delete the
relevant entries via the timeseries-store API or simply re-run the
bootstrap (a fresh ISO timestamp version is appended; older versions
remain available for diffing).

```python
from aurora.data_contracts.timeseries_store import default_store
store = default_store()
print(store.list_versions("prices_daily", "SPY"))
```

## Related rules / files

- `core/data_providers/first_dataset.py` -- orchestrator + report
  dataclasses.
- `cli/cmd_data.py` -- `bootstrap-first-dataset`, `freeze`,
  `coverage-report --dataset first` subcommands.
- `data_contracts/timeseries_store.py` -- versioned parquet+sqlite
  store.
- `core/snapshots.py` -- approved snapshot store with locked-tier
  unlock ceremony enforcement.
- `tests/test_first_real_ingestion.py` -- 17 unit tests covering
  every section, fallback, contract violation, freeze and CLI path.
