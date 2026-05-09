# File Split Plan (R49 / R50 / R51 / R52)

## Status

Plan locked. The actual splits ship as separate human-driven PRs
because each touches a hot file and risks subtle import-resolution
regressions if rushed in a batched session.

## Why plan-first

The four oversized modules (`cli/forge.py` 3583 lines,
`deployment/brokers.py` 1866, `reporting/tearsheet.py` 1313, plus the
five secondary files in R52) all carry one of:

- argparse subcommand registration that depends on local helpers
- broker-class hierarchy with shared mutable state
- HTML rendering with deeply-nested f-strings and shared CSS

Splitting them mechanically without a careful walk introduces
silent breakage that automated test suites do not always catch
(import-time side effects, argparse subcommand visibility,
metaclass registration order). One commit per file with a focused
human review is the right shape.

Each section below records the exact split structure so the
follow-up PRs do not need to re-derive it.

## R49 -- `cli/forge.py` (3583 -> ~7 modules)

Target package layout:

```
cli/
├── __init__.py                # already exposes `main` (R73)
├── forge.py                   # dispatcher only (~400 lines)
├── _shared.py                 # _arg_error, _runtime_error, _ccxt_load_config,
│                              # _resolve_strategy, _costs_from, _add_tier_arg,
│                              # _strategy_library, _policy_tier_choices, etc.
├── cmd_run.py                 # cmd_validate, cmd_search, cmd_run, cmd_list_strategies,
│                              # cmd_tearsheet, cmd_bench, cmd_label, cmd_factor,
│                              # cmd_attribute, cmd_purge_cv, cmd_fracdiff, cmd_cscv,
│                              # cmd_preflight, cmd_search_multi, cmd_freeze,
│                              # cmd_dashboard, cmd_config_*
├── cmd_data.py                # cmd_data_list_providers, cmd_data_fetch, cmd_data_verify
├── cmd_crypto.py              # cmd_crypto_*
├── cmd_policy.py              # cmd_policy_show, cmd_policy_verify
├── cmd_research.py            # cmd_research_*
├── cmd_audit.py               # cmd_audit_*
├── cmd_agent.py               # cmd_agent_*
├── cmd_ops.py                 # cmd_ops_*
└── cmd_export.py              # cmd_export_lean*
```

### Per-subcommand worksheet

Each `cmd_*` function moves to its target module + the dispatcher's
`subparsers.add_parser(...)` call follows it. Helpers used by exactly
one group move with that group; helpers used by 2+ groups go to
`_shared.py`.

Boundary discipline:

- `forge.py` keeps `main(argv=None)` and the top-level
  `argparse.ArgumentParser` construction. Each `cmd_*` module exposes
  a `register(subparsers)` function that adds its own subparser. The
  dispatcher imports the module and calls `register()`.
- Per-module test files are added under `tests/test_cli_<name>.py`
  smoke-testing the `register()` and one happy-path invocation.
- No subcommand module exceeds 800 lines. If one would, it splits
  again (`cmd_research_submit.py`, `cmd_research_promote.py` etc).

### Acceptance

- `forge --help` output BYTE-IDENTICAL to pre-split output.
  Compare with `diff` of saved help captures.
- `forge <each subcommand> --help` byte-identical too.
- Full fast suite green without modification.
- `cli/forge.py` shrinks to <= 800 lines.

### Out of scope for the split PR

- Refactoring helpers beyond mechanical move + import.
- Behaviour changes to any subcommand.
- Adding new subcommands.

## R50 -- `deployment/brokers.py` (1866 -> 1 package)

Target layout:

```
deployment/brokers/
├── __init__.py                # re-exports the public surface
├── base.py                    # Order, Position, BrokerError, the abstract base
├── paper.py                   # PaperBroker
├── alpaca.py                  # AlpacaBroker
├── ib.py                      # IBKRBroker / IBBrokerAdapter
├── coinbase.py                # CoinbaseBroker
├── kraken.py                  # KrakenBroker
└── lumibot.py                 # LumibotBroker (already separate adapter; consolidate)
```

### Acceptance

- `from quantforge.deployment.brokers import PaperBroker, AlpacaBroker,
  IBKRBroker, ...` continues to work.
- Per-broker module <= 500 lines.
- Tests under `tests/test_brokers_*.py` already partition by broker;
  no test changes required.
- Live-trading triple-gate audit unchanged.

## R51 -- `reporting/tearsheet.py` (1313 -> 1 package)

Target layout:

```
reporting/tearsheet/
├── __init__.py                # public render() entry point
├── header.py                  # hero + run-summary block
├── metrics_table.py           # headline + risk metrics tables
├── equity.py                  # cumulative + per-period equity charts
├── drawdown.py                # underwater + stats
├── factor.py                  # factor-exposure section
├── attribution.py             # signal attribution + cost breakdown
└── styles.py                  # shared CSS
```

### Acceptance

- The same HTML output as before (modulo whitespace).
- Tests in `tests/test_tearsheet.py` reuse the existing assertions
  on the rendered HTML.
- The existing `render(...)` function stays the public entry point.
- The PDF renderer (R84) keeps working without modification because
  it consumes the same HTML.

## R52 -- Remaining oversized modules

Files still over 800 lines after R49 / R50 / R51:

| File | Lines | Split target |
|---|---|---|
| `reporting/daily_ops/builder.py` | 994 | by panel: hero, alerts, equity, no-trade, cost decomposition |
| `analytics/metrics_full.py` | 924 | by metric family: returns, risk, drawdown, attribution |
| `core/data_layer.py` | 925 | by tier: train, valid, oos_dev, oos_locked, oos_plus, forward |
| `research/factory/factory.py` | 882 | by phase: ingest, triage, validate, promote |
| `deployment/preflight.py` | 822 | by check: cost, liquidity, position, broker, kill-switch |

One commit per split. Behaviour identical. No bundling with semantic
changes.

## Roll-out order

1. R49 first because it lowers the maintenance load on the most
   actively edited file.
2. R50 next because it un-blocks the per-broker test partitioning
   already in place.
3. R51 last because it touches the tearsheet renderer that R84 PDF
   export depends on.
4. R52 in any order; each file is independent.

## Definition of done (whole batch)

- Every file above is <= 800 lines.
- `forge --help` output unchanged.
- Full test suite green.
- Public API (the symbols other modules import from these files)
  unchanged.
- No mass renames, no behaviour changes, no bundled refactors.

## Why this is the canonical reference

This document is the source of truth for the split plan. Future
sessions referencing R49 / R50 / R51 / R52 should consult this file
before re-deriving the structure. The plan keeps the splits focused
and mechanical, which is the only safe shape for refactors at this
size.
