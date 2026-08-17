# SP500 Selected-12 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Subagents and forks are prohibited for this repository.

**Goal:** Evaluate the twelve preselected SP500 strategies exactly once on 2011-2020 while keeping every date from 2021 onward closed.

**Architecture:** A committed selection manifest freezes recipes before validation. A fail-closed GitHub-only runner verifies and combines immutable train and validation snapshots for signal warm-up, evaluates unchanged recipes, scores only validation dates, and writes hash-bound evidence.

**Tech Stack:** Python 3.11/3.14, pandas, NumPy, PyArrow, pytest, GitHub Actions.

## Global Constraints

- Scientific execution occurs only in GitHub Actions.
- Validation is exactly 2011-01-01 through 2020-12-31.
- Any date from 2021-01-01 onward aborts execution.
- Exactly twelve unique frozen strategies are accepted.
- Locked remains false in every input, intermediate receipt and output.
- No parameter fitting, tuning, retries with changed recipes, subagents or forks.

---

### Task 1: Authorized snapshot boundary

**Files:**
- Modify: `infra/sp500_megarun/dehb_lane_registry.py`
- Create: `infra/sp500_megarun/selected_validation.py`
- Test: `tests/test_sp500_megarun_selected_validation.py`

**Interfaces:**
- Produces: `build_authorized_validation_snapshot(train_dir: Path, validation_dir: Path, output_dir: Path, authorization: str) -> ValidationSnapshotReceipt`
- Produces: `AuthorizedValidationLaneEvaluator`, restricted to an authorized snapshot ending on 2020-12-31.

- [ ] **Step 1: Write failing tests** proving the merge rejects the wrong authorization, any locked row/date, mismatched dataset sets and a validation manifest already marked opened; prove the evaluator rejects a normal train constructor being pointed at validation.
- [ ] **Step 2: Run RED** with `C:\Python314\python.exe -m pytest tests/test_sp500_megarun_selected_validation.py -q`; expected failure is missing validation APIs.
- [ ] **Step 3: Implement minimal boundary code** that verifies source file hashes, exact partitions, disjoint dates, maximum date 2020-12-31 and emits a manifest with `partition=authorized_validation`, `validation_opened=true`, `locked_opened=false`.
- [ ] **Step 4: Run GREEN** with the same pytest command; expected result is all tests passing.
- [ ] **Step 5: Commit** snapshot boundary and tests.

### Task 2: Frozen strategy evaluation and metrics

**Files:**
- Create: `config/sp500_megarun_selected_validation_12.json`
- Modify: `infra/sp500_megarun/selected_validation.py`
- Test: `tests/test_sp500_megarun_selected_validation.py`

**Interfaces:**
- Consumes: authorized snapshot and exact twelve-entry manifest.
- Produces: `validate_selection_manifest(payload: Mapping[str, Any]) -> tuple[SelectedStrategy, ...]`
- Produces: `score_validation_returns(strategy_returns: pd.Series, spy_returns: pd.Series) -> Mapping[str, Any]`.

- [ ] **Step 1: Write failing tests** for exactly twelve unique recipes, allowed composition semantics, ten annual rows, weekly union without double counting, negative-SPY-year average and strict locked flags.
- [ ] **Step 2: Run RED**; expected failures are missing selection and scoring functions.
- [ ] **Step 3: Add the exact twelve recipes** from train-only evidence and implement validation-only scoring for 2011-2020.
- [ ] **Step 4: Run GREEN** and check the manifest digest is stable across repeated loads.
- [ ] **Step 5: Commit** frozen selection and evaluator.

### Task 3: GitHub-only one-shot workflow

**Files:**
- Create: `scripts/run_sp500_megarun_selected_validation.py`
- Create: `.github/workflows/sp500-megarun-selected-validation-once.yml`
- Test: `tests/test_sp500_megarun_selected_validation.py`

**Interfaces:**
- Consumes train runtime run `31418682679`, closed validation run `31418658411`, exact commit SHA and acknowledgment `OPEN_SP500_MEGARUN_VALIDATION_2011_2020_SELECTED_12_ONCE`.
- Produces artifact `sp500-megarun-selected-validation-12-<run_id>` containing `results.jsonl`, `summary.csv`, `receipt.json` and the frozen selection.

- [ ] **Step 1: Write failing source-contract tests** asserting exact acknowledgment, pinned source runs, no locked input and artifact completeness.
- [ ] **Step 2: Run RED**; expected failure is absent script/workflow.
- [ ] **Step 3: Implement runner and workflow** with `require_github_only_execution`, immutable artifact downloads, one evaluation job and fail-closed upload.
- [ ] **Step 4: Run GREEN**, Ruff, `git diff --check` and YAML/source assertions.
- [ ] **Step 5: Commit and push** the exact validation revision.

### Task 4: Execute and verify once

**Files:**
- Evidence only: GitHub Actions artifact and durable local download under `C:\Users\HP\Desktop\CODEX`.

**Interfaces:**
- Consumes the committed exact SHA and one-shot acknowledgment.
- Produces verified validation results and a user-facing comparison.

- [ ] **Step 1: Dispatch once** with exact SHA, source run IDs and acknowledgment.
- [ ] **Step 2: Monitor** until completion; inspect every failure before any retry and never change a strategy recipe.
- [ ] **Step 3: Download final artifact** to a new run-specific directory.
- [ ] **Step 4: Verify** twelve unique results, ten annual rows each, `validation_opened=true`, `locked_opened=false`, maximum date 2020-12-31 and artifact hashes.
- [ ] **Step 5: Report** all twelve results without opening 2021+.
