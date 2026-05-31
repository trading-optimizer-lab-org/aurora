# Contributing to Aurora

Aurora (renamed from Aurora in v1.5.0 / R23) is a quant research
engine with a militant anti-overfit pipeline. This guide covers the
rules contributors must follow.

## Setup

`pyproject.toml` lives at the repo root and the package is imported as
`aurora`. From the repo root:

```bash
pip install -e ".[dev,ml,ga]"
```

For the full stack:

```bash
pip install -e ".[dev,all]"
```

The legacy `aurora` namespace remains importable as a thin compat
shim that emits a `DeprecationWarning`; the shim is removed in v1.6.

## Running tests

```bash
# Fast suite
pytest -v -m "not slow and not integration"

# With coverage (requires `dev` extras: pytest-cov)
pytest -v --cov=aurora --cov-report=term-missing --cov-config=.coveragerc -m "not slow and not integration"

# Full suite (includes slow)
pytest -v
```

Coverage is configured via `.coveragerc` (branch coverage on, 80%
fail-under threshold, omits tests and examples). The `--cov` flag
is intentionally not in `addopts` in `pyproject.toml` so the test suite
can run without pytest-cov installed; pass `--cov` explicitly when the
`dev` extras are installed.

The pytest markers are declared in `pyproject.toml`:

- `slow` - long-running tests
- `integration` - real network or broker tests

Optional-dependency tests (torch, gymnasium, stable_baselines3, etc.)
use `pytest.importorskip` at module load time rather than dedicated
markers, so the suite reports them as skipped automatically when the
extras are not installed.

## Integration tests

Live broker integration tests live in
`tests/test_live_integration.py`. They are skipped by default
because they hit a real broker API. To enable them:

1. Install the Alpaca SDK:

   ```bash
   pip install alpaca-py
   ```

2. Export Alpaca paper-trading credentials:

   ```bash
   export ALPACA_API_KEY="your-paper-key"
   export ALPACA_API_SECRET="your-paper-secret"
   ```

   (On Windows PowerShell, use `$env:ALPACA_API_KEY = "..."`.)

3. Run with the `integration` marker:

   ```bash
   pytest -v -m integration tests/test_live_integration.py
   ```

The smoke test submits a single $1 limit order on SPY (which should
never fill), then cancels it. Never run integration tests against a
funded live account.

## OOS sagrado rule

The out-of-sample partition is locked. Optimization, GA search, and
hyperparameter tuning have **zero** access to OOS data. The runtime
guard lives in `core/data_layer.py::OOSGuard` (file-lock + git hash
check, hardened in v1.0 batch F).

If you write code that reads OOS data during a search or fitness
evaluation, the guard will fail and the test suite will reject it.
Do not work around the guard.

## Anti-lookahead requirement

Any new strategy or feature pipeline must pass
`validation/lookahead_check.py`. The AST scanner checks for:

- Indexing into future bars (`series[i+1]`, `data.shift(-1)`, etc.)
- Using forward-looking labels at training time
- Aggregations whose window includes the current bar's future

Run it before opening a PR:

```bash
pytest -k lookahead
```

Note: `aurora preflight` runs the runtime preflight gates (data, sizing,
broker, marker, ...). It does NOT execute the AST anti-lookahead scanner;
use the `lookahead` test selection above for that check.

## Validation gates (do not skip)

A strategy is mergeable only after every gate documented in
`docs/ARCHITECTURE.md` (the canonical enumeration) passes. The full
sequence has 13 gates plus the final OOS hold-out:

1. Walk-forward
2. MC bootstrap
3. MC trade reorder
4. SPP +/-10%
5. Deflated Sharpe
6. Lookahead AST + runtime
7. Noise injection (optional)
8. Gap simulation (optional)
9. Purged K-Fold CV
10. CSCV / PBO
11. Synthetic crash scenarios
12. Tail-risk amplification
13. Correlation-breakdown stress

Survivors then pass through the single OOS hold-out gate before paper
trading. `validation/pipeline.py` orchestrates gates 1-8; gates 9-13
run as standalone checks.

Headline thresholds:

1. OOS sagrado (>= 30 percent of data, never seen during search)
2. Walk-forward (Calmar > buy-and-hold Calmar in each window)
3. Monte Carlo (real MDD between P20-P80 of bootstrap distribution)
4. System Parameter Permutation (Calmar variance < 30 percent over
   +/- 10 percent neighborhood)

Plus DSR > 1.96 post candidate selection.

## Agent batching pattern

Larger features land via the SDD parallel-batch pattern documented in
`docs/v1_*_COMPLETION_REPORT.md`:

1. Plan the batch in `docs/DEVELOPMENT_PLAN_v*.md`
2. Dispatch 4-6 sub-agents in parallel, one per task
3. Each sub-agent ships code + tests in its module
4. Run the full suite after the batch closes
5. Code review pass for the batch
6. Update the matching `v*_COMPLETION_REPORT.md`

If you are touching a single module, normal single-PR flow is fine -
do not invent batches for trivial work.

## Lint and format

```bash
ruff check .
ruff format .
```

Configuration is in `pyproject.toml`. The release-blocking rule set is
focused on correctness checks (`F821`, `F541`, `B008`, `B023`, `B904`);
broader style/modernization passes can be run explicitly when doing a
dedicated cleanup.
Line length 100. Target Python 3.10.

## Commit style

Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
`chore:`, `perf:`, `ci:`.
