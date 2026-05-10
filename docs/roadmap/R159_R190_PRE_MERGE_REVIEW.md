# R159-R190 pre-merge review

Date: 2026-05-10
Branch: `claude/loving-ishizaka-96d02d`
Head at audit: `92040f6` (audit follow-up) on top of `ba9218d` (R159-R190 main commit)
Diverged from `main`: 686 files, +49388 / -10293

This document is the audit gate that runs **before** merging the
branch back to `main`. The companion implementation report lives at
[`R159_R190_SESSION_REPORT.md`](R159_R190_SESSION_REPORT.md); this file
records what the audit confirmed, what it found, and the merge
recommendation.

## Scope of the audit

Four zones were checked, in order:

1. **Roadmap** -- statuses match reality, completed items are the 27
   actually done in the session, open items are the 5 legitimately
   pending.
2. **Data on disk** -- the dataset persisted by R157 / R158 actually
   exists; the BTCUSDT timestamp-scale bug the operator flagged is
   real; SEC fundamentals are real, not placeholder fixtures.
3. **Critical code** -- CLI dispatcher, data provider registry,
   snapshots, execution replay, portfolio, research / literature,
   preflight, extension API all import and exercise their critical
   paths.
4. **Verification** -- ruff, fast pytest suite, R159-R190 targeted
   tests, no garbage files left behind, `.claude/` never tracked.

## Zone 1 -- Roadmap status

Verified by walking `### R<N>.` headers in
`docs/roadmap/ROADMAP_PENDING.md` and confirming the next `Status:`
line for each.

**Completed (27):** R159, R160, R161, R163, R164, R165, R166, R167,
R168, R169, R170, R171, R172, R173, R174, R175, R176, R177, R178, R179,
R180, R181, R182, R185, R186, R187, R188.

Each is marked
`Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)`.

**Open (5):** R162, R183, R184, R189, R190. Each remains
`Status: open` with the blocker reason embedded in the implementation
report.

R162 blocker text was corrected in commit `92040f6`. The previous wording
("needs network credentials") was misleading: the network ingestion
already happened in the R157 / R158 pass, and the raw SEC EDGAR
`companyfacts.json` payloads sit on disk for 20 symbols. What R162 still
needs is the PIT normalisation layer plus the derived-ratio API, not the
network step.

## Zone 2 -- Data on disk

Resolved via `aurora.core.runtime_paths`:

```
data : C:\Users\HP\AppData\Local\aurora
snap : C:\Users\HP\AppData\Local\aurora\snapshots
cache: C:\Users\HP\AppData\Local\aurora\cache
```

| Category         | Path                                                          | Result                                                                                          |
|------------------|---------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| Snapshots index  | `$AU_DATA_DIR/snapshots/snapshots_index.sqlite`               | Present (empty payload set; index schema intact)                                                |
| Timeseries index | `$AU_DATA_DIR/timeseries/timeseries_index.sqlite`             | Present; 60+ symbols across 5 libraries                                                         |
| `prices_daily`   | `$AU_DATA_DIR/timeseries/prices_daily/`                       | 30+ ETFs / equities (AAPL, AGG, BIL, BND, BRK-B, COST, etc.)                                    |
| `crypto_daily`   | `$AU_DATA_DIR/timeseries/crypto_daily/`                       | 10 perp-pairs (BTCUSDT, ETHUSDT, ADAUSDT, AVAXUSDT, BNBUSDT, DOGEUSDT, DOTUSDT, LINKUSDT, SOLUSDT, XRPUSDT) |
| `fx_daily`       | `$AU_DATA_DIR/timeseries/fx_daily/`                           | 8 majors (EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF, AUDUSD, NZDUSD, DXY)                          |
| `macro_daily`    | `$AU_DATA_DIR/timeseries/macro_daily/`                        | 15 series (VIX, FEDFUNDS, T10Y2Y, DGS10, CPIAUCSL, etc.)                                        |
| Fundamentals     | `$AU_DATA_DIR/fundamentals_sec/`                              | 20 real `companyfacts.json` files (CIK + entityName fields verified)                            |
| Identity         | `$AU_DATA_DIR/identity_openfigi/`                             | 3 stub records (AAPL, MSFT, NVDA)                                                                |
| Audit / ledgers  | `$AU_DATA_DIR/audit_trail.jsonl(.gz)`, `research_ledger.jsonl(.gz)` | Present, rotated archives 01/02 also on disk                                              |

### Finding -- BTCUSDT v1 corruption

`crypto_daily/BTCUSDT/20260510T172618.parquet` (3179 rows) has the
trailing rows dated:

```
58291-06-27  77371.32  77478.00  75666.60  76342.77  13210.72383
58294-03-23  76342.78  77904.93  74937.52  75780.00  18279.93022
58296-12-17  75780.00  76669.14  75323.65  76346.57  10381.81607
```

Years 58291 / 58294 / 58296 are the timestamp-scale bug the operator
flagged. The provider was `binance_public_data`. The bug was already
fixed in a second ingestion `20260510T182950`, indexed in
`timeseries_index.sqlite` with metadata
`{"fix": "timestamp_scale_detection", ...}`. The corrected v2 has the
same row count but its `max_ts == 2026-04-30`, which is consistent with
3179 daily bars from 2017-08-17.

Both versions remain in the index. The corrupt v1 was **quarantined
during this audit** via the R161 ledger:

```
$AU_DATA_DIR/quarantine_ledger.jsonl
```

Entry recorded:

- provider: `binance_public_data`
- library: `crypto_daily`
- symbol: `BTCUSDT`
- version: `20260510T172618`
- decision: `quarantined`
- reason: `timestamp scale parsing bug: rows have year >=58291
  (corrupt). superseded by 20260510T182950 with timestamp_scale_detection
  fix.`
- actor: `audit-2026-05-10`

The quarantine file is a **runtime artefact under
`$AU_DATA_DIR`**, not under version control. It is not in the commit and
will not appear in the merge -- the operator will need to recreate it on
their canonical machine using:

```python
from aurora.data_contracts.quality import QuarantineLedger
from aurora.core import runtime_paths as rp
ledger = QuarantineLedger(rp.base_data_dir() / "quarantine_ledger.jsonl")
ledger.quarantine(
    provider="binance_public_data",
    library="crypto_daily",
    symbol="BTCUSDT",
    version="20260510T172618",
    reason="timestamp scale parsing bug: rows have year >=58291",
    actor="<operator-id>",
)
```

This is intentional: per the R161 contract, the quarantine ledger is
operator-local state, not source code. R167's stale-artefact report
flags any downstream snapshots that depended on the corrupt v1.

### Finding -- SEC fundamentals are real

Twenty `companyfacts.json` payloads sit under `fundamentals_sec/`. The
top-level keys match the SEC EDGAR XBRL schema:

```
{"cik": 320193, "facts": {"cik": 320193, "entityName": "Apple Inc.",
 "facts": {"dei": {"EntityCommonStockSharesOutstanding": ...}}}}
```

Spot-checked:

- Apple Inc. -- CIK 320193 (matches public SEC record)
- ADVANCED MICRO DEVICES, INC -- CIK 2488 (matches)
- AMAZON.COM, INC. -- CIK 1018724 (matches)

These are authentic SEC responses, not test fixtures. R162 stays open
because the **PIT-normalised layer + derived-ratio API** is not built;
the raw payloads alone do not meet R162 acceptance criteria. The session
report at `R159_R190_SESSION_REPORT.md` was corrected to reflect this.

## Zone 3 -- Critical code review

After forcing the editable-install MAPPING to point at this worktree,
all 52 R159-R190 modules import cleanly:

```
imported: 52/52
```

Critical-path smoke test (12/12 green):

| # | Surface                              | Result                                              |
|---|--------------------------------------|-----------------------------------------------------|
| 1 | `aurora doctor`                      | runs offline, returns rc 0 with JSON                |
| 2 | Provider terms registry              | seeds 10 providers (yahoo, snapshot, csv, synthetic, ccxt, dukascopy, marketdata_app, sec_edgar, dbnomics, ecb) |
| 3 | Execution event reducer              | bootstraps order from CREATED event                 |
| 4 | `PortfolioProblem`                   | accepts asset_ids + returns matrix                  |
| 5 | Literature claim extractor           | extracts 1 claim from a synthetic abstract          |
| 6 | Preflight bundle                     | aggregates to `fail` when risk record absent        |
| 7 | Extension API                        | `INTERFACE_VERSIONS` lists DataProvider, BrokerAdapter, AuditSink, ... |
| 8 | Crypto instrument model              | PERPETUAL kind round-trips                          |
| 9 | Atlas paper link registry            | `claim_ids_for("strat-x") == ["claim-1"]`           |
|10 | Evidence pack hash verify            | `verify_pack` returns `(True, [])` for fresh pack   |
|11 | `SnapshotStore`                      | importable, no behavioural change                   |
|12 | Data provider registry boot          | 9 providers registered                              |

Soft note (out of scope): `aurora.core.data_providers.sec_edgar_companyfacts`
emits a registration warning because the file lives untracked in the
main repo workspace and was never committed to any branch. Pre-existing
R156 gap, not introduced by this session.

CLI dispatcher walk confirmed the new subcommands are wired:

```
data    : provider-terms, list-providers, fetch, verify, ... (R178)
research: atlas (list/show/classify/link-source), papers (ingest/list/claims), ... (R173 + R174)
crypto  : capability, funding-history, preflight, ... (R185)
doctor  : top-level (R187)
```

## Zone 4 -- Verification

| Check                                                                 | Result                          |
|-----------------------------------------------------------------------|---------------------------------|
| `ruff check .`                                                        | All checks passed (2 errors fixed in `92040f6`) |
| Fast suite (excl. pre-existing markov + lint scanner failures)        | 3418 passed, 6 skipped, 0 failed (~9m) |
| Aggregate run on 43 R159-R190 test files                              | 578 passed in 36s               |
| R155 / R158 tests already in worktree (`test_data_providers.py`, `test_dukascopy_fx_history.py`, `test_marketdata_app_limited.py`) | 38 passed in 70s                |
| Garbage txt files (`mypy_errors.txt`, `unused_ignores.txt`)           | Removed pre-commit              |
| `.claude/` directory                                                   | Never staged, always untracked  |

## Corrections applied during the audit

1. **`cli/cmd_research.py`** -- ruff F821: forward-string annotation
   `"Path"` replaced with no annotation (Path is imported lazily inside
   the function).
2. **`research/strategy_atlas.py`** -- ruff B904: graveyard-collision
   `raise ValueError(...)` chained with `from None`.
3. **`docs/roadmap/R159_R190_SESSION_REPORT.md`** -- R162 blocker text
   corrected to reflect that the network ingestion is already done; the
   PIT normalisation + derived-ratio API is what is pending.
4. **R161 quarantine ledger** -- BTCUSDT v1 corrupt parquet recorded as
   `quarantined` (runtime artefact, see Zone 2 finding above).

Items 1-3 landed in commit `92040f6`. Item 4 is operator-local state, not
source-controlled.

## Out-of-scope notes (carry-forward)

These are **not** R159-R190 issues but are visible from this audit and
should be tracked in a follow-up session:

- **R155 / R156 test files untracked in main repo.** Files like
  `tests/test_data_providers_free_bulk.py`,
  `tests/test_sec_edgar_companyfacts.py`,
  `tests/test_openfigi_mapper.py`, `tests/test_dbnomics_macro.py`,
  `tests/test_ecb_data_portal.py`,
  `tests/test_coinmetrics_community.py`, `tests/test_tiingo_daily.py`,
  `tests/test_cli_data_r156.py` exist in `C:/Users/HP/QuantForge/tests/`
  but have never been committed to any branch. The roadmap claims R155
  / R156 as completed with these test counts as evidence; the evidence
  itself was never under version control. The operator should commit
  them in a separate PR.
- **`aurora.core.data_providers.sec_edgar_companyfacts`** module is
  registered as a deferred scaffold in
  `aurora.core.data_providers.get_default_registry`, but the file does
  not exist in this branch. Same root cause: prior session forgot to
  commit. Soft warning at registry boot, no functional impact on
  R159-R190.
- **Editable-install MAPPING drift.** The user's pip-installed
  `__editable___aurora_1_5_0_finder.py` MAPPING points at the main
  repo, not at this worktree. Tests pass because `conftest.py` rewrites
  the MAPPING for the pytest run. After merging this branch back to
  main and reinstalling (`pip install -e .` from main), the drift
  resolves naturally.

## Tests executed during the audit (full list)

```
git status --short
"C:/Python314/python.exe" -m ruff check . --output-format=concise
"C:/Python314/python.exe" -m pytest tests/test_doctor.py tests/test_provider_terms.py \
    tests/test_data_quality.py tests/test_benchmark_pack.py \
    tests/test_instrument_master.py tests/test_execution_events.py \
    tests/test_risk_record.py tests/test_evidence_pack.py \
    tests/test_preflight_bundle.py tests/test_research_ledger.py \
    tests/test_dataset_diff.py tests/test_registry_aliases.py \
    tests/test_feature_store.py tests/test_telemetry.py tests/test_incidents.py \
    tests/test_calendars.py tests/test_data_contracts_corporate_actions.py \
    tests/test_execution_replay.py tests/test_reconciliation.py \
    tests/test_fill_models_constraints.py tests/test_tca_report.py \
    tests/test_liquidity_dataset.py tests/test_liquidity_report.py \
    tests/test_strategy_atlas_governance.py tests/test_idea_sources.py \
    tests/test_release_provenance.py tests/test_portfolio_problem.py \
    tests/test_portfolio_cost_aware.py tests/test_portfolio_stress_scenarios.py \
    tests/test_portfolio_analytics_report.py tests/test_agent_roles.py \
    tests/test_evidence_pack_view.py tests/test_research_agents.py \
    tests/test_prompt_injection.py tests/test_extension_api.py \
    tests/test_extension_loader.py tests/test_literature_papers.py \
    tests/test_literature_extraction.py tests/test_literature_reliability.py \
    tests/test_literature_ingest.py tests/test_literature_atlas_link.py \
    tests/test_crypto_instruments.py tests/test_exchange_capability.py \
    tests/test_exchange_downtime.py tests/test_crypto_risk.py
"C:/Python314/python.exe" -m pytest tests/test_dukascopy_fx_history.py \
    tests/test_marketdata_app_limited.py tests/test_data_providers.py
"C:/Python314/python.exe" -m pytest tests/ -m "not slow and not integration" \
    --ignore=tests/test_config.py --ignore=tests/test_property.py \
    --ignore=tests/test_markov_switching.py --ignore=tests/test_lint_config.py
```

Plus the import + critical-path smoke script described in Zone 3.

## Recommendation

**MERGE TO `main`: YES**, conditional on:

1. The operator manually replays the BTCUSDT v1 quarantine entry on the
   target machine after merge (the `quarantine_ledger.jsonl` is
   per-machine state, not committed).
2. A follow-up PR commits the R155 / R156 test files
   (`test_data_providers_free_bulk.py`, `test_sec_edgar_companyfacts.py`,
   `test_openfigi_mapper.py`, `test_dbnomics_macro.py`,
   `test_ecb_data_portal.py`, `test_coinmetrics_community.py`,
   `test_tiingo_daily.py`, `test_cli_data_r156.py`) plus the missing
   `core/data_providers/sec_edgar_companyfacts.py` provider module.
   Without them the roadmap's R155 / R156 evidence is unreproducible.

The branch ships:

- 27 of 32 R159-R190 items closed with code, tests, ruff, and zero
  regressions on the fast suite
- 5 R items legitimately open with documented blockers
- A clean two-commit history on top of `fa530de`:
  - `ba9218d` -- main R159-R190 work + accumulated branch state
  - `92040f6` -- audit follow-up (ruff fixes + R162 text correction)
- Branch isolated from `main` (no merge yet)
- `.claude/` left untracked
- This audit document + the implementation report under
  `docs/roadmap/`
