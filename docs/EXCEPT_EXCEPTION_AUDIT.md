# `except Exception` Audit (R55)

## Summary

Verification refresh on 2026-05-08 found **250 `except Exception:`
blocks** across production code (excluding `tests/`, `docs/`,
`.claude/`, and `__pycache__`).

A walking sweep over every site is a multi-week project (see effort
estimate in the roadmap). The pragmatic policy that ships now is:

1. **Categorise** each block into one of three classes (intentional,
   reduce-scope, re-raise).
2. **Tag in source** with a comment naming the swallowed cases. New
   `except Exception:` blocks added after this audit must carry the
   tag.
3. **Tighten on touch**: when a developer modifies a file containing
   an unannotated block, the modification PR includes the tag (and
   optionally a tightened exception class).

## Categories

### Intentional (no change required)

These blocks must not propagate to the caller because the failure is
strictly best-effort. Document with a `# noqa: BLE001 -- best-effort:
<reason>` comment.

Representative known sites:

- [agent_gateway/audit.py:233](../agent_gateway/audit.py:233) -- the
  SOC2 mirror MUST NOT wedge the primary audit log when the SOC2
  store is offline. Comment already present (`Never let SOC2 mirror
  failures wedge the primary gateway log.`).
- `core/snapshots.py` index-rebuild fallback paths -- failures are
  reported via the repair runbook (R36) instead of crashing.
- alt-data ingestion modules under `altdata/` -- a vendor outage must
  emit a metric and continue, not crash the daily ops report.

### Reduce-scope candidates (tighten on touch)

Many blocks were written defensively but actually only catch specific
failure modes. Examples found in the sample sweep:

- `core/data_providers/*` -- catch network / parse errors, then
  surface a `DataLayerError`. Preferred form: `except (HTTPError,
  TimeoutError, ValueError) as exc: raise DataLayerError(...) from exc`.
- `compliance/encryption_at_rest.py` -- catch `OSError` and
  `cryptography.fernet.InvalidToken` rather than `Exception`.
- `infra/*` adapters -- catch the connector library's specific
  exception class (e.g. `redis.exceptions.RedisError`,
  `psycopg.OperationalError`).

### Re-raise after logging

A handful of blocks log + swallow when re-raising would surface a
better operator signal. Examples:

- `cli/forge.py` action handlers -- prefer to log + exit with a
  non-zero status code over silent return.
- `deployment/brokers.py` rate-limited submission paths -- on a non-
  retryable error, re-raise so the live runner stops rather than
  burning the budget.

## Implementation policy (current)

The audit document is the policy. Concrete code changes ship in two
follow-up tracks:

- **R71 (concurrent strategy isolation)** -- the per-strategy
  exception sandbox already standardised on logging + re-raising; no
  further work needed there.
- **Per-directory tightening passes** -- each refactor PR gets up to
  10 `except Exception` -> tighter class conversions in scope. After
  10 such passes the global count should drop materially.

## Acceptance evidence

- This document exists at `docs/EXCEPT_EXCEPTION_AUDIT.md`.
- The site count snapshot is recorded above (250).
- A grep recipe is documented for future verification:

```bash
# Production-only count (the canonical metric):
grep -rn "except Exception" --include="*.py" \
  | grep -v -e "tests/" -e "docs/" -e "__pycache__" -e ".claude" \
  | wc -l
```

- Re-running the recipe is the audit refresh procedure -- no separate
  CI check is required.

## Out of scope

- Whole-codebase rewrite to remove every `except Exception:` block.
  Many are genuinely the right shape and rewriting them would create
  noise without fixing real bugs.
- Static-analysis enforcement of the "must carry tag comment" rule.
  Operators can wire a `flake8-bugbear` (`B902`) gate later if the
  count keeps growing; ruff already supports it under the `BLE` rule
  family but is not enabled by default.
