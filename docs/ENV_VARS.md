# Environment Variable Inventory (R57 + R58)

Single canonical reference for every environment variable Aurora
reads. Operators wiring credentials should source from this list, not
from `grep`.

## Conventions

- All `QF_*` variables migrate to `AU_*` once roadmap R23 / R76 ships.
  During the deprecation window, both forms are honoured with a warning
  on the legacy `QF_*` form.
- Security-sensitive variables MUST come from a secrets manager
  (Vault, 1Password, AWS Secrets Manager, ...). They MUST NOT live
  in a `.env` file committed to any repository. They MUST NOT be
  printed by any logger.
- Optional provider variables are unset by default; the corresponding
  feature is no-op or refuses to call the provider when unset.

## Security-sensitive (MUST come from a secrets manager)

| Variable | Purpose |
|---|---|
| `QF_GATEWAY_SECRET` | HMAC server secret for agent token signing. |
| `QF_OPERATOR_KEY` | HMAC operator countersign secret for live commits. |
| `QF_PII_FERNET_KEY` | Encryption-at-rest for PII columns. |
| `QF_PII_HMAC_KEY` | Deterministic PII masking pepper. |
| `QF_TOTP_SECRET` | Two-factor auth seed for operator login. |
| `QF_SQLCIPHER_KEY` | Audit DB encryption key. |
| `QFORGE_SMTP_PASSWORD` | Alert email credential. |

## Runtime paths (override defaults; honoured by `runtime_paths.py`)

| Variable | Default | Purpose |
|---|---|---|
| `QF_DATA_DIR` | platformdirs user-data dir | Base dir for all runtime artefacts. |
| `QF_CACHE_DIR` | `$QF_DATA_DIR/cache` | Price / data cache. |
| `QF_CACHE` | (legacy alias of `QF_CACHE_DIR`) | Legacy alias; honoured for back-compat. |
| `QF_SNAPSHOT_ROOT` | `$QF_DATA_DIR/snapshots` | SnapshotStore root (parquet + sqlite). |
| `QF_AUDIT_LOG` | `$QF_DATA_DIR/audit_trail.jsonl` | SOC2 audit JSONL trail. |
| `QF_GATEWAY_AUDIT` | `$QF_DATA_DIR/gateway_audit.jsonl` | Agent gateway hash-chained audit. |
| `QF_OOS_LOCK` | `$QF_DATA_DIR/.oos_lock.json` | OOSGuard cross-process lock file. |
| `QF_RESEARCH_ARCHIVE` | `$QF_DATA_DIR/research_archive.jsonl` | Factory rejection archive. |
| `QF_REVIEW_QUEUE` | `$QF_DATA_DIR/research_review_queue.jsonl` | Factory review queue. |
| `QF_AUTO_LOOP_LOG` | `$QF_DATA_DIR/auto_loop.jsonl` | Auto-research-loop cycle summary log. |
| `QF_CONFIG_DIR` | `$QF_DATA_DIR/config` | User-overridable config dir. |
| `QF_JOURNAL` | `$QF_DATA_DIR/journal.db` | TradeJournal SQLite path. |

## Tier ceremonies

| Variable | Purpose |
|---|---|
| `QF_AGENT_LIVE_AUTH` | Set to `1` to allow the agent gateway to commit live actions. |
| `QF_LEAN_LIVE_AUTH` | Set to `1` to allow `deploy_to_lean_cloud` to invoke the Lean CLI. |
| `QF_ALLOW_FULL_TIER` | Set to `1` to permit `--tier full` reads (combined with `OOSGuard("explicit_unlock_full_tier")`). |

R58: `QF_ALLOW_OOS_LOCKED` was previously documented as a separate
ceremony env flag. The current code uses the per-ceremony OOSGuard
instance (`OOSGuard("explicit_unlock_oos_locked")`) plus
`--i-understand-ceremony` for the locked-tier path. Treat older
references to `QF_ALLOW_OOS_LOCKED` as stale documentation; it has
been removed from `CLAUDE.md` and `docs/ZERO_TO_LIVE.md`.

## CCXT crypto exchanges (pattern-based)

Per-exchange variables, where `<EXCHANGE>` is the upper-case CCXT
exchange id (`BINANCE`, `KRAKEN`, `COINBASE`, ...):

| Pattern | Purpose |
|---|---|
| `QF_CCXT_<EXCHANGE>_KEY` | Exchange API key. |
| `QF_CCXT_<EXCHANGE>_SECRET` | Exchange API secret. |
| `QF_CCXT_ALLOW_LIVE_<EXCHANGE>` | Set to `1` to allow live trading on that exchange. |
| `QF_CCXT_DEFAULT_EXCHANGE` | Default exchange when not specified per call. |
| `QF_CCXT_KILL_SWITCH` | Global kill switch; set to `1` to halt every CCXT live order. |

## External provider credentials

| Variable | Provider |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic SDK (R8 LLM augmenter). |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | Alpaca paper / live trading. |
| `FRED_API_KEY` | FRED macro time series. |
| `TRANSCRIPTS_API_KEY` | Earnings transcript provider. |
| `ETHERSCAN_API_KEY` | On-chain crypto provider. |
| `TWITTER_BEARER_TOKEN` | Twitter sentiment feed. |
| `PLANET_API_KEY` | Satellite imagery provider. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit scraper. |

## Infra DSNs

| Variable | Purpose |
|---|---|
| `AURORA_PG_DSN` | PostgreSQL backend (R7 future remote driver). |
| `AURORA_REDIS_URL` | Redis cache backend. |
| `AURORA_TIMESCALE_DSN` | TimescaleDB backend. |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob Storage. |

## Runtime tuning

| Variable | Purpose |
|---|---|
| `QF_REFRESH` | Force re-fetch of cached data. |
| `HYPOTHESIS_PROFILE` | `dev` (default) / `ci` / `thorough`; selects Hypothesis profile from `tests/conftest.py`. |
| `MAX_THINKING_TOKENS` | Claude Code budget cap. |
| `NUMBA_DISABLE_JIT` | Set to `1` for mutmut sweeps so source mutations are not shadowed by compiled kernels (R72). |

## Display / test-only (informational)

These are read by tests or third-party libs, not by Aurora code:
`DISPLAY`, `MPLBACKEND`, `PYCHARM_HOSTED`, `PYTHONHASHSEED`.

## Verification

A grep against the source establishes that every entry above maps to
at least one read. The list is regenerated as part of R57 whenever a
new env var is introduced. Adding a new env var without updating this
file is a soft policy violation -- pre-commit may grow a check.
