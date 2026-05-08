# Env Var Migration Plan (R76 -- sub-task of R23 Aurora rename)

## Status

Plan locked. Execution lands when R23 (the Aurora rename) ships.

## What changes

The Aurora rename touches every `QF_*` environment variable. They
become `AU_*`. A one-release-cycle compatibility shim reads both,
warns when the old name is hit, and is removed in the release after
that.

## Inventory (28 vars + provider-specific patterns)

Source of truth: `docs/ENV_VARS.md` (R57). Migration table below is
the rename specification.

### Runtime paths

| Old (QF_)              | New (AU_)              | Notes |
|------------------------|------------------------|-------|
| QF_DATA_DIR            | AU_DATA_DIR            | base data dir |
| QF_CACHE_DIR           | AU_CACHE_DIR           | price/data cache |
| QF_CACHE (legacy)      | AU_CACHE_DIR (alias)   | drop the legacy alias |
| QF_SNAPSHOT_ROOT       | AU_SNAPSHOT_ROOT       | snapshot store root |
| QF_AUDIT_LOG           | AU_AUDIT_LOG           | SOC2 audit JSONL |
| QF_GATEWAY_AUDIT       | AU_GATEWAY_AUDIT       | agent gateway chain |
| QF_OOS_LOCK            | AU_OOS_LOCK            | OOSGuard lock file |
| QF_RESEARCH_ARCHIVE    | AU_RESEARCH_ARCHIVE    | factory archive JSONL |
| QF_REVIEW_QUEUE        | AU_REVIEW_QUEUE        | factory review queue |
| QF_AUTO_LOOP_LOG       | AU_AUTO_LOOP_LOG       | auto-loop log |
| QF_CONFIG_DIR          | AU_CONFIG_DIR          | config search root |
| QF_JOURNAL             | AU_JOURNAL             | order/run journal |

### Security

| Old                    | New                    | Notes |
|------------------------|------------------------|-------|
| QF_GATEWAY_SECRET      | AU_GATEWAY_SECRET      | HMAC server secret |
| QF_OPERATOR_KEY        | AU_OPERATOR_KEY        | operator countersign |
| QF_PII_FERNET_KEY      | AU_PII_FERNET_KEY      | encryption-at-rest |
| QF_PII_HMAC_KEY        | AU_PII_HMAC_KEY        | PII pepper |
| QF_TOTP_SECRET         | AU_TOTP_SECRET         | 2FA seed |
| QF_SQLCIPHER_KEY       | AU_SQLCIPHER_KEY       | audit DB encryption |

### Operations / kill switch

| Old                    | New                    | Notes |
|------------------------|------------------------|-------|
| QF_REFRESH             | AU_REFRESH             | force-refresh flag |
| QF_ALLOW_FULL_TIER     | AU_ALLOW_FULL_TIER     | tier ceremony flag |
| QF_LEAN_LIVE_AUTH      | AU_LEAN_LIVE_AUTH      | Lean live auth env |
| QF_CCXT_DEFAULT_EXCHANGE | AU_CCXT_DEFAULT_EXCHANGE | crypto default |
| QF_CCXT_KILL_SWITCH    | AU_CCXT_KILL_SWITCH    | crypto kill switch |
| QFORGE_SMTP_PASSWORD   | AURORA_SMTP_PASSWORD   | alert email creds |

### Per-exchange CCXT pattern

`QF_CCXT_{EXCHANGE}_KEY` -> `AU_CCXT_{EXCHANGE}_KEY`
`QF_CCXT_{EXCHANGE}_SECRET` -> `AU_CCXT_{EXCHANGE}_SECRET`
`QF_CCXT_ALLOW_LIVE_{EXCHANGE}` -> `AU_CCXT_ALLOW_LIVE_{EXCHANGE}`

### Already-non-namespaced (DO NOT rename)

These don't carry the QuantForge brand and stay as-is:

- `ANTHROPIC_API_KEY`, `ALPACA_API_KEY`, `ALPACA_API_SECRET`
- `FRED_API_KEY`, `TRANSCRIPTS_API_KEY`, `ETHERSCAN_API_KEY`
- `TWITTER_BEARER_TOKEN`, `PLANET_API_KEY`
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`
- `QUANTFORGE_PG_DSN`, `QUANTFORGE_REDIS_URL`,
  `QUANTFORGE_TIMESCALE_DSN` -- stay (operator infra is owned by the
  operator; renaming the connection-string env breaks operator
  monitoring).
- `AZURE_STORAGE_CONNECTION_STRING` -- stays.

## Compatibility shim shape

A single helper resolves the env var with the rename:

```python
# core/env_compat.py (lands in the R23 PR, not before)
import os
import warnings

def aurora_env(new_name: str, old_name: str | None = None,
               default: str | None = None) -> str | None:
    if new_name in os.environ:
        return os.environ[new_name]
    if old_name and old_name in os.environ:
        warnings.warn(
            f"{old_name} is deprecated; use {new_name}.",
            DeprecationWarning, stacklevel=2,
        )
        return os.environ[old_name]
    return default
```

Every existing reader migrates to call `aurora_env("AU_X", "QF_X")`.
The `os.environ["QF_X"]` literal goes away.

## Deprecation timeline

- **v1.5 (rename release):** new `AU_*` names ship; `QF_*` reads
  emit `DeprecationWarning`. Both work.
- **v1.6 (one cycle later):** `QF_*` shim removed; CHANGELOG carries
  the breaking change.
- **v1.7+:** only `AU_*` is read. `QF_*` is undefined behaviour.

## Operator-side checklist (lands with the R23 PR)

- `CLAUDE.md` runtime-paths table updates.
- `README.md` operator quickstart updates.
- `docs/ZERO_TO_LIVE.md` examples updated.
- `docs/ENV_VARS.md` becomes the single canonical name list.
- `docs/RESEARCH_PROTOCOL.md` references updated.

## What this plan deliberately does NOT decide

- The Python package rename (`quantforge` -> `aurora`) -- handled
  by the main R23 plan.
- The CLI rename (`forge` -> `aurora`) -- handled by R23.
- Provider-credential format changes (e.g. moving from env vars to
  a vault) -- separate work track.

## Out of scope for this plan

- Tooling for operators to mass-rename their own export lines:
  shipping a `forge env-migrate` helper is a follow-up only if
  operators ask for it.
- Cross-host config sync: per-operator concern.
