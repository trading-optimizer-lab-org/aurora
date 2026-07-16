# Stock Protocol 36 Tests 360 Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Implement and launch a GitHub-only workflow that executes the 25 technically available tests from the 36-test stock protocol, records 11 tests as `unsupported_missing_data`, and never reads locked data.

**Architecture:** A single staged GitHub Actions DAG prepares a current-active US daily dataset, builds compact date-partitioned research packs, runs eight dependent layers with two matrices of 180 jobs, freezes each layer, and produces a final Pareto report. New protocol code is isolated under `research/stock_protocol` and `scripts/stock_protocol`; existing Aurora engines remain reusable primitives.

**Tech Stack:** Python 3.12, pandas, NumPy, PyArrow/Parquet, DuckDB, PyYAML, GitHub Actions, existing Aurora validation modules.

## Global Constraints

- Research and walk-forward dates are `1995-01-01` through `2015-12-31`.
- Final untouched holdout is `2016-01-01` through `2020-12-31`.
- Locked is closed from `2021-01-01`; every output must contain `locked_opened=false`.
- Execute tests `1,2,3,8,9,13,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,32,34,35,36` with explicit data limitations.
- Record tests `4,5,6,7,10,11,12,14,30,31,33` as `unsupported_missing_data`.
- Maximum requested concurrency is `360`, split into matrices of `180` and `180`; no matrix may exceed `256` entries.
- Do not run backtests, searches, optimizations, heavy merges, or tests locally; GitHub Actions is the execution environment.
- No data is uploaded to Git; tokens and cloud credentials stay in GitHub Secrets.
- Current-active-universe results are never labelled survivorship-free or fully protocol-compliant.

---

### Task 1: Protocol Manifest And Policy Contracts

**Files:**
- Create: `config/stock_protocol_36_tests.yaml`
- Create: `research/stock_protocol/__init__.py`
- Create: `research/stock_protocol/manifest.py`
- Create: `tests/test_stock_protocol_manifest.py`

**Interfaces:**
- `load_protocol_manifest(path: Path) -> ProtocolManifest` validates exactly 36 test IDs.
- `ProtocolManifest.executable_test_ids() -> tuple[int, ...]` returns the 25 approved IDs.
- `ProtocolManifest.unsupported_tests() -> tuple[UnsupportedTest, ...]` returns the 11 blocked IDs and reasons.
- `ProtocolManifest.policy_payload() -> dict[str, object]` returns dates, locked policy, concurrency and limitation fields for hashing.

- [ ] **Step 1: Write the manifest test cases**

```python
def test_manifest_has_36_tests_and_25_executable_11_unsupported():
    manifest = load_protocol_manifest(Path("config/stock_protocol_36_tests.yaml"))
    assert len(manifest.tests) == 36
    assert len(manifest.executable_test_ids()) == 25
    assert len(manifest.unsupported_tests()) == 11
    assert manifest.locked_opened is False
    assert manifest.data_end == "2020-12-31"
```

- [ ] **Step 2: Verify the test fails in GitHub CI**

Push the test and let the dedicated `validate` job run. Expected: failure because the manifest loader does not exist.

- [ ] **Step 3: Add the YAML manifest and loader**

The YAML must contain one record for every ID, an explicit `status`, `reason`, `requires`, and `variants`. Blocked records must have `status: unsupported_missing_data` and must not appear in worker matrices.

- [ ] **Step 4: Verify the manifest in GitHub**

Run the workflow validation job. Expected: the manifest test passes and the generated policy hash is deterministic.

- [ ] **Step 5: Commit**

```powershell
git add config/stock_protocol_36_tests.yaml research/stock_protocol tests/test_stock_protocol_manifest.py
git commit -m "feat: define stock protocol test manifest"
```

### Task 2: Date-Bounded Research Dataset And Audit

**Files:**
- Create: `research/stock_protocol/dataset.py`
- Create: `scripts/prepare_stock_protocol_data.py`
- Create: `scripts/build_stock_protocol_pack.py`
- Create: `tests/test_stock_protocol_dataset.py`
- Modify: `.github/workflows/free-global-yahoo-daily-data-lake.yml` only if an explicit end-date input is required by the reusable downloader.

**Interfaces:**
- `load_bounded_daily_panel(root: Path, end_date: str) -> ResearchPanel` rejects rows after the end date.
- `build_research_pack(source_root: Path, output_root: Path, manifest: ProtocolManifest) -> PackAudit` writes date partitions and hashes.
- `PackAudit.to_json() -> dict[str, object]` includes coverage, row counts, data end, survivorship limitation and hashes.

- [ ] **Step 1: Add tests for date and lock enforcement**

```python
def test_panel_rejects_rows_after_locked_boundary(tmp_path):
    with pytest.raises(ValueError, match="2020-12-31"):
        load_bounded_daily_panel(tmp_path, "2020-12-31")

def test_pack_audit_declares_active_universe_limitation():
    audit = PackAudit(data_end="2020-12-31", survivorship_free=False)
    assert audit.locked_opened is False
```

- [ ] **Step 2: Verify failure in GitHub**

Expected: missing dataset contract and pack builder.

- [ ] **Step 3: Implement bounded loading and compact partitions**

Use only rows with `date <= 2020-12-31`. Keep OHLC unadjusted for execution logic and adjusted returns separately. Include benchmark files and current metadata with `metadata_is_bitemporal=false`. Fail if the source contains locked rows instead of silently dropping them.

- [ ] **Step 4: Verify in GitHub**

The validation workflow must build a synthetic pack inside a runner and report `locked_rows=0`; it must not use a local execution.

- [ ] **Step 5: Commit**

```powershell
git add research/stock_protocol/dataset.py scripts/prepare_stock_protocol_data.py scripts/build_stock_protocol_pack.py tests/test_stock_protocol_dataset.py .github/workflows/free-global-yahoo-daily-data-lake.yml
git commit -m "feat: add date-bounded stock research pack"
```

### Task 3: Signal, Entry, Exit And Portfolio Primitives

**Files:**
- Create: `research/stock_protocol/signals.py`
- Create: `research/stock_protocol/execution.py`
- Create: `research/stock_protocol/portfolio.py`
- Create: `research/stock_protocol/metrics.py`
- Create: `tests/test_stock_protocol_engine.py`

**Interfaces:**
- `compute_signal(panel: ResearchPanel, test_id: int, variant: dict[str, object]) -> SignalFrame`.
- `execute_next_open(signal: SignalFrame, panel: ResearchPanel, exit_rule: dict[str, object]) -> TradeFrame`.
- `build_portfolio(trades: TradeFrame, portfolio_rule: dict[str, object]) -> PortfolioFrame`.
- `compute_metrics(returns: pd.Series, trades: TradeFrame, costs_bps: int) -> dict[str, float]`.

- [ ] **Step 1: Write causal execution tests**

```python
def test_close_signal_enters_next_open():
    result = execute_next_open(signal_frame, panel, {"kind": "none"})
    assert result.iloc[0].entry_date == "2020-01-03"
    assert result.iloc[0].entry_price == 101.0

def test_stop_gap_uses_open_and_never_future_close():
    result = execute_next_open(signal_frame, panel, {"kind": "catastrophe_atr", "k": 2})
    assert result.iloc[0].exit_reason == "gap_through_stop"
```

- [ ] **Step 2: Verify failure in GitHub**

Expected: missing engine modules.

- [ ] **Step 3: Implement the 25 supported test families**

Implement price-based momentum, H52, information-discreteness, breakouts, consolidation, RVOL, SMA filters, ranking hysteresis, breakout failure, trend exits, ATR stops, time exits, take profits, equal/inverse-volatility sizing, limits, regime exposure and fixed-cost scenarios. Every signal must carry `signal_date`, `available_at`, and `entry_date`.

- [ ] **Step 4: Verify in GitHub**

Run engine tests in the validation workflow. Expected: causal entry, conservative intraday ambiguity, non-negative exposure, cost scenarios and metric calculations pass.

- [ ] **Step 5: Commit**

```powershell
git add research/stock_protocol/signals.py research/stock_protocol/execution.py research/stock_protocol/portfolio.py research/stock_protocol/metrics.py tests/test_stock_protocol_engine.py
git commit -m "feat: add causal stock protocol engine"
```

### Task 4: Shard Runner, Layer Freeze And Merge

**Files:**
- Create: `scripts/run_stock_protocol_stage.py`
- Create: `scripts/merge_stock_protocol_phase.py`
- Create: `scripts/freeze_stock_protocol_layer.py`
- Create: `tests/test_stock_protocol_shards.py`

**Interfaces:**
- `run_stage(manifest_path: Path, pack_root: Path, phase: str, shard_id: int, shard_count: int) -> Path`.
- `merge_phase(shards_root: Path, expected: list[dict[str, object]], output_root: Path) -> PhaseAudit`.
- `freeze_layer(results_path: Path, layer: str, prior_snapshot: Path | None) -> Path`.

- [ ] **Step 1: Write shard integrity tests**

```python
def test_merge_rejects_missing_shard(tmp_path):
    with pytest.raises(ValueError, match="missing shard"):
        merge_phase(tmp_path, expected=[{"shard_id": 0}, {"shard_id": 1}], output_root=tmp_path)

def test_freeze_contains_dataset_and_policy_hashes(tmp_path):
    snapshot = freeze_layer(results_path, "layer_1_signal", None)
    assert snapshot.read_json()["locked_opened"] is False
```

- [ ] **Step 2: Verify failure in GitHub**

Expected: runner and merge interfaces absent.

- [ ] **Step 3: Implement deterministic shards and freezes**

Each output must include `phase`, `test_id`, `variant_id`, `time_block`, `shard_id`, `dataset_hash`, `config_hash`, `policy_hash`, `locked_opened`, `rows`, and metrics. Merge must isolate every artifact in its own directory and fail on missing, duplicate, extra or incompatible records.

- [ ] **Step 4: Verify in GitHub**

Run shard tests with synthetic data inside Actions. Expected: missing and duplicate shards fail, complete merge passes, and snapshots cannot include final holdout metrics during selection.

- [ ] **Step 5: Commit**

```powershell
git add scripts/run_stock_protocol_stage.py scripts/merge_stock_protocol_phase.py scripts/freeze_stock_protocol_layer.py tests/test_stock_protocol_shards.py
git commit -m "feat: add stock protocol sharding and freezes"
```

### Task 5: GitHub Actions DAG And Final Artifact

**Files:**
- Create: `.github/workflows/stock-protocol-36-tests-360jobs.yml`
- Create: `scripts/finalize_stock_protocol.py`
- Create: `tests/test_stock_protocol_workflow_contract.py`

**Interfaces:**
- Workflow dispatch inputs: `data_source_run_id`, `data_artifact_name`, `max_parallel_requested` default `360`, and `validation_only` default `false`.
- `finalize_stock_protocol(input_root: Path, output_root: Path) -> Path` writes `final_summary.json` and `run_audit.md`.

- [ ] **Step 1: Write workflow contract tests**

```python
def test_workflow_has_two_180_matrices_and_locked_boundary():
    text = Path(".github/workflows/stock-protocol-36-tests-360jobs.yml").read_text()
    assert "max-parallel: 180" in text
    assert text.count("matrix_a") >= 1
    assert "2021-01-01" in text
    assert "2020-12-31" in text
```

- [ ] **Step 2: Verify failure in GitHub**

Expected: workflow and finalizer absent.

- [ ] **Step 3: Implement the DAG**

Use `needs` to enforce `validate -> prepare_data -> pack -> layer -> freeze` ordering. Build two JSON matrices of 180 shards. Use unique artifact names and a final artifact named `stock-protocol-36-tests-360jobs-results`. Never allow a later layer to start after a partial freeze.

- [ ] **Step 4: Verify workflow in GitHub**

Dispatch with `validation_only=true`. Expected: YAML validation, Python syntax checks, manifest checks and synthetic shard checks pass without executing a research backtest.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/stock-protocol-36-tests-360jobs.yml scripts/finalize_stock_protocol.py tests/test_stock_protocol_workflow_contract.py
git commit -m "feat: add 360-job stock protocol workflow"
```

### Task 6: Publish, Validate And Launch

**Files:**
- Modify: `docs/superpowers/plans/2026-07-12-stock-protocol-36-tests-360jobs.md` only for progress checkboxes.
- Modify: `.superpowers/sdd/progress.md` as the durable execution ledger.

- [ ] **Step 1: Review the complete branch diff**

Run `git diff origin/codex/universal-robustness...HEAD --check` and inspect the workflow, manifest, runner, merge and final summary files.

- [ ] **Step 2: Commit the completed implementation**

```powershell
git status --short
git log --oneline --max-count=12
```

- [ ] **Step 3: Push the isolated branch**

```powershell
git push -u origin codex/pit-limited-36tests-360jobs
```

- [ ] **Step 4: Run validation-only on GitHub**

```powershell
gh workflow run stock-protocol-36-tests-360jobs.yml --repo trading-optimizer-lab-org/aurora --ref codex/pit-limited-36tests-360jobs -f validation_only=true -f max_parallel_requested=360
```

Wait for the run, inspect all jobs, and do not launch the full run if validation fails.

- [ ] **Step 5: Launch the full GitHub run**

```powershell
gh workflow run stock-protocol-36-tests-360jobs.yml --repo trading-optimizer-lab-org/aurora --ref codex/pit-limited-36tests-360jobs -f validation_only=false -f max_parallel_requested=360
```

- [ ] **Step 6: Verify launch and final artifact**

Inspect the run until completion. Confirm the final artifact contains all required files, `locked_opened=false`, `data_end=2020-12-31`, `tests_executed_with_limitations=25`, `tests_unsupported_missing_data=11`, and a complete shard audit.
