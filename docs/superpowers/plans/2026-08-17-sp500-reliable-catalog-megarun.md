# Reliable SP500 Catalog Mega-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Subagents and forks are prohibited for this project, so execution is inline in the authoritative worktree.

**Goal:** Implement and launch a finite, train-only SP500 catalog campaign that uses static shards, exact future-valid deduplication, a twenty-minute calibration, the three approved objectives, balanced robustness filters, and complete result preservation without DEHB coordination.

**Architecture:** Reuse the verified catalog optimizer, component store, recipe compiler, scheduler, cache, vector engine, resume manifests and result reducer. Add an Atlas run contract around those modules, a short calibration workflow, a deterministic family-admission manifest, Pareto ranking for weeks/months/annual joint success, and a fail-closed static workflow. The first campaign is `SP500_ATLAS_1`; higher-order combinations remain for a later catalogue selected only after the first campaign is reviewed.

**Tech Stack:** Python 3.11/3.14-compatible package code, NumPy, pandas, Pydantic frozen contracts, GitHub Actions, JSONL/NPY/Parquet-compatible artifacts, pytest. Scientific execution is GitHub Actions only.

## Global Constraints

- Train data ends at `2010-12-31`.
- `validation_opened=false` and `locked_opened=false` are mandatory everywhere.
- No subagents and no forks.
- No DEHB search loop, central coordination database, continuous claim queue, or automatic continuation.
- Do not deduplicate recipes merely because historical positions match.
- Only formal equivalence under the frozen evaluator, data contract, numeric profile and missing-data semantics may share a result.
- The three primary objectives are positive-week percentage, positive-month percentage, and years simultaneously positive and above SPY.
- Sharpe, drawdown, costs and annualized return are descriptive only and cannot rank the Pareto frontier.
- Every declared recipe must be completed or the run is incomplete.
- The twenty-minute calibration is a hard wall-clock limit.
- The target finish is approximately `2026-08-20T07:31:00+02:00`; it is not a cutoff that permits incomplete results.
- All heavy scientific work runs in GitHub Actions; local work is limited to inspection, editing and tests.

---

## Current file map

### Reuse without redesign

- `infra/sp500_megarun/catalog_optimization_contract.py`: immutable optimization admission and execution contract.
- `infra/sp500_megarun/catalog_component_store.py`: hash-bound reusable `{-1,0,+1}` component store.
- `infra/sp500_megarun/catalog_evaluation_cache.py`: result cache bound to evaluator, data, recipe and numeric profile.
- `infra/sp500_megarun/catalog_scheduler.py`: deterministic weighted scheduling.
- `infra/sp500_megarun/catalog_vector_engine.py`: train-only vectorized metrics.
- `infra/sp500_megarun/catalog_recipe_compiler.py`: recipe DAG and component references.
- `infra/sp500_megarun/catalog_resume.py`: immutable resume work manifests.
- `scripts/plan_sp500_optimized_catalog_run.py`: plan and admission generation.
- `scripts/run_sp500_optimized_recipe_worker.py`: static recipe-block worker.
- `scripts/reduce_sp500_optimized_catalog_run.py`: verified result reduction.
- `.github/workflows/catalog-optimized-run.yml`: existing static optimized workflow.

### Files to create or modify

- Create `infra/sp500_megarun/catalog_atlas_contract.py`: Atlas-specific frozen contract and target-time policy.
- Create `infra/sp500_megarun/catalog_atlas_objective.py`: exact weekly/monthly/annual-joint objective metrics and Pareto comparison.
- Create `infra/sp500_megarun/catalog_atlas_robustness.py`: balanced train-only robustness classification.
- Create `infra/sp500_megarun/catalog_family_admission.py`: deterministic new-family admission and duplicate classification.
- Create `infra/sp500_megarun/catalog_calibration.py`: twenty-minute stratified sample and break-even calculation.
- Create `scripts/build_sp500_atlas_catalog.py`: build `ATLAS_1` from the current contract plus admitted new families.
- Create `scripts/audit_sp500_atlas_families.py`: classify candidate family definitions before catalog construction.
- Create `scripts/calibrate_sp500_atlas_run.py`: bounded twenty-minute calibration entrypoint.
- Create `scripts/reduce_sp500_atlas_run.py`: Atlas reduction, Pareto frontier and robustness report.
- Create `.github/workflows/sp500-atlas-calibration.yml`: hard-capped calibration workflow.
- Create `.github/workflows/sp500-atlas-run.yml`: static Atlas workflow with no DEHB coordinator.
- Modify `scripts/run_sp500_optimized_recipe_worker.py`: add the explicit `--atlas-objective` mode and emit the complete Atlas result receipt while preserving the existing optimized mode.
- Modify `scripts/plan_sp500_optimized_catalog_run.py`: accept Atlas catalog directory, target end, calibration evidence and static-run mode.
- Modify `scripts/reduce_sp500_optimized_catalog_run.py`: keep backward compatibility and expose common verified partition loading to Atlas reduction.
- Create `tests/test_sp500_atlas_contract.py`.
- Create `tests/test_sp500_atlas_objective.py`.
- Create `tests/test_sp500_atlas_robustness.py`.
- Create `tests/test_sp500_atlas_family_admission.py`.
- Create `tests/test_sp500_atlas_calibration.py`.
- Create `tests/test_sp500_atlas_workflow_contract.py`.

---

## Task 1: Freeze the Atlas contract and train-only boundaries

**Files:**
- Create: `infra/sp500_megarun/catalog_atlas_contract.py`
- Test: `tests/test_sp500_atlas_contract.py`

**Interfaces:**

```python
class AtlasTargetWindowV1(FrozenModel):
    target_end_iso: str
    available_minutes: float
    safety_fraction: float = 0.80

class AtlasCatalogSpecV1(FrozenModel):
    catalog_id: str
    catalog_dir: str
    train_end: Literal["2010-12-31"]
    validation_opened: Literal[False]
    locked_opened: Literal[False]
    include_inverses: Literal[True]
    max_strategy_arity: Literal[2]
    target_window: AtlasTargetWindowV1

class AtlasRunContractV1(FrozenModel):
    schema_version: Literal["1"]
    mode: Literal["atlas_static"]
    science: CatalogScienceIdentityV1
    atlas: AtlasCatalogSpecV1
    optimization: RunOptimizationContractV1
    contract_sha256: Sha256
```

- [ ] Write tests that reject a train end after `2010-12-31`, either protected period opened, inverses disabled, arity above 2 for `ATLAS_1`, target time before the current plan time, or a safety fraction outside `[0.5, 0.9]`.
- [ ] Write a test proving the contract hash changes when catalog, evaluator, data, numeric profile or target policy changes.
- [ ] Implement frozen Pydantic models and canonical hash calculation.
- [ ] Implement `load_and_validate_atlas_contract(path)` with fail-closed errors.
- [ ] Run `python -m pytest tests/test_sp500_atlas_contract.py -q` and commit `feat: add static Atlas run contract`.

## Task 2: Implement the three Atlas objectives and Pareto frontier

**Files:**
- Create: `infra/sp500_megarun/catalog_atlas_objective.py`
- Test: `tests/test_sp500_atlas_objective.py`
- Modify: `scripts/run_sp500_optimized_recipe_worker.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class AtlasObjectiveResult:
    positive_weeks: int
    total_weeks: int
    positive_week_fraction: float
    positive_months: int
    total_months: int
    positive_month_fraction: float
    joint_positive_above_spy_years: int
    total_years: int
    joint_positive_above_spy_fraction: float
    annual_rows: tuple[dict[str, float | int | bool], ...]

def score_atlas_decisions(
    decisions: np.ndarray,
    spy_returns: np.ndarray,
    dates: np.ndarray,
    *,
    train_end: str = "2010-12-31",
) -> AtlasObjectiveResult: ...

def dominates_atlas(a: AtlasObjectiveResult, b: AtlasObjectiveResult) -> bool: ...

def pareto_frontier(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]: ...
```

- [ ] Write tests for strict positivity, zero not positive, complete week/month/year grouping, SPY annual comparison, and equal rows remaining distinct.
- [ ] Write a test that any date after `2010-12-31` raises before scoring.
- [ ] Implement week and month grouping using the SPY trading calendar and full-period masks.
- [ ] Implement annual joint condition `strategy_return > 0 and strategy_return > spy_return`.
- [ ] Implement non-weighted Pareto dominance and deterministic strategy-id tie ordering.
- [ ] Update the optimized worker to emit the Atlas objective fields while retaining old fields for compatibility.
- [ ] Run the objective tests and commit `feat: add Atlas Pareto objectives`.

## Task 3: Add formal equivalence and family admission manifests

**Files:**
- Create: `infra/sp500_megarun/catalog_family_admission.py`
- Create: `scripts/audit_sp500_atlas_families.py`
- Create: `scripts/build_sp500_atlas_catalog.py`
- Create: `tests/test_sp500_atlas_family_admission.py`

**Interfaces:**

```python
class FamilyAdmissionV1(FrozenModel):
    family_id: str
    status: Literal["accepted", "duplicate", "insufficient_history", "not_verifiable", "not_free"]
    source_ids: tuple[str, ...]
    source_sha256: Sha256 | None
    available_through: str | None
    duplicate_of: str | None
    reason: str

def classify_family(candidate: Mapping[str, object], existing: Mapping[str, object]) -> FamilyAdmissionV1: ...

def formal_recipe_equivalence(left: Mapping[str, object], right: Mapping[str, object]) -> bool: ...

def build_atlas_catalog(
    *,
    existing_catalog_dir: Path,
    family_manifest: Path,
    output_dir: Path,
    catalog_id: str = "sp500-atlas-1",
) -> Mapping[str, object]: ...
```

- [ ] Write tests for duplicate, non-free, insufficient-history and accepted family records.
- [ ] Write tests proving empirical equal positions do not deduplicate two different recipes.
- [ ] Write tests for commutative composition, proportional weights and exact duplicate recipe equivalence.
- [ ] Implement canonical family admission without downloading data or reading protected periods.
- [ ] Implement the Atlas builder by reusing the current 240-family catalog entries, adding only manifest entries with `status=accepted`, and emitting inverse recipes with new scientific identities.
- [ ] Make the builder fail if an accepted family has no source digest, causal availability rule or train-only boundary.
- [ ] Run tests and generate a fixture manifest containing the existing 240-family inventory with zero unverified additions.
- [ ] Commit `feat: build deterministic Atlas catalog admission`.

## Task 4: Implement the twenty-minute calibration and break-even policy

**Files:**
- Create: `infra/sp500_megarun/catalog_calibration.py`
- Create: `scripts/calibrate_sp500_atlas_run.py`
- Create: `tests/test_sp500_atlas_calibration.py`

**Interfaces:**

```python
class CalibrationReceiptV1(FrozenModel):
    schema_version: Literal["1"]
    catalog_sha256: Sha256
    started_at_iso: str
    stopped_at_iso: str
    wall_seconds: float
    hard_limit_seconds: Literal[1200.0]
    timed_out_cleanly: bool
    physical_recipe_count: int
    cache_hit_count: int
    physical_component_seconds: float
    recipe_seconds: float
    result_store_seconds: float
    recipes_per_minute: float
    recommended_mode: Literal["cold", "component_warm"]
    target_recipe_count_with_margin: int
    validation_opened: Literal[False]
    locked_opened: Literal[False]

def select_stratified_calibration_rows(catalog: Path, *, max_rows: int) -> list[dict[str, object]]: ...

def choose_atlas_mode(
    *,
    cold_total_seconds: float,
    prepared_total_seconds: float,
    future_catalog_count: int,
) -> Literal["cold", "component_warm"]: ...
```

- [ ] Write tests that a calibration receipt cannot exceed 1200 seconds, cannot use post-2010 rows, and selects every family/composition/inverse class before repeating a class.
- [ ] Write a test proving the break-even decision includes preparation time rather than comparing only warm evaluation time.
- [ ] Implement monotonic deadline handling with a twenty-minute wall-clock stop and atomic receipt write.
- [ ] Implement target calculation `floor(available_minutes * measured_rate * 0.80)`.
- [ ] Implement the calibration CLI using the existing worker primitives and a deterministic stratified sample.
- [ ] Run the calibration unit tests and commit `feat: add twenty-minute Atlas calibration`.

## Task 5: Add static Atlas planning and result verification

**Files:**
- Modify: `scripts/plan_sp500_optimized_catalog_run.py`
- Modify: `infra/sp500_megarun/catalog_scheduler.py` only if an Atlas-specific invariant is missing.
- Create: `scripts/reduce_sp500_atlas_run.py`
- Create: `infra/sp500_megarun/catalog_atlas_robustness.py`
- Create: `tests/test_sp500_atlas_robustness.py`

**Interfaces:**

```python
class AtlasRobustnessResult(FrozenModel):
    status: Literal["green", "amber", "red", "invalid"]
    zero_tolerance_failures: tuple[str, ...]
    red_tests: tuple[str, ...]
    test_rows: tuple[Mapping[str, object], ...]

def classify_atlas_robustness(
    base: Mapping[str, object],
    perturbations: Sequence[Mapping[str, object]],
) -> AtlasRobustnessResult: ...

def reduce_atlas_partitions(
    partitions_root: Path,
    catalog_path: Path,
    contract_path: Path,
    output_dir: Path,
) -> Mapping[str, object]: ...
```

- [ ] Write tests for zero-tolerance failures, one red reserve, two independent reds, and green/amber classification.
- [ ] Implement train-only delayed decision, neighboring parameter, leave-one-year-out, three-period, date-boundary, component-ablation, missing-data and exceptional-period perturbation receipts using existing robustness primitives where compatible.
- [ ] Make any protected-period access a hard error before a perturbation runs.
- [ ] Extend the reducer to require every catalog recipe exactly once, reject result hash conflicts, compute the three objectives, and emit the Pareto frontier.
- [ ] Keep every original result even when its frontier/robustness status is rejected.
- [ ] Run focused tests and commit `feat: reduce Atlas objectives and robustness`.

## Task 6: Create the twenty-minute calibration workflow

**Files:**
- Create: `.github/workflows/sp500-atlas-calibration.yml`
- Test: `tests/test_sp500_atlas_workflow_contract.py`

- [ ] Write workflow-contract tests asserting checkout uses the supplied immutable commit, runtime inputs are train-only, the job timeout is twenty minutes plus fixed setup allowance, no validation/locked environment is present, and no DEHB job is called.
- [ ] Add `workflow_dispatch` inputs for exact commit, runtime pack, catalog manifest and optional component-store run.
- [ ] Add a `preflight` job that validates the Atlas contract and catalog hashes.
- [ ] Add a bounded calibration job whose scientific sample is stopped by an in-process monotonic deadline of exactly 1200 seconds; setup and artifact upload are outside the scientific receipt and have a fixed workflow allowance.
- [ ] Upload the receipt even when the scientific sample reaches its twenty-minute deadline cleanly.
- [ ] Add an explicit fail-closed step when the receipt is missing, protected boundaries are false, or the catalog hash differs.
- [ ] Run YAML and workflow tests and commit `ci: add bounded Atlas calibration workflow`.

## Task 7: Create the static Atlas full-run workflow

**Files:**
- Create: `.github/workflows/sp500-atlas-run.yml`
- Modify: `scripts/run_sp500_optimized_recipe_worker.py` to expose `--atlas-objective` and persist Atlas objective fields in every worker row.
- Test: `tests/test_sp500_atlas_workflow_contract.py`

- [ ] Write workflow-contract tests asserting no DEHB continuous workflow, database service, dynamic claim loop or automatic continuation is referenced.
- [ ] Add inputs for exact commit, catalog, calibration receipt, target end, runtime pack, compatible component store and prior result cache.
- [ ] Add a preflight job that checks calibration hard limit, mode break-even receipt, target end and all protected flags.
- [ ] Reuse the static plan, component, worker and reducer jobs from the optimized workflow through explicit immutable artifacts.
- [ ] Set `fail-fast: false`, bounded retries, and no automatic rerun of successful shards.
- [ ] Store one result artifact per block and a final verified manifest.
- [ ] Make the final job fail when any recipe is absent, duplicated with conflicting content, or unverified.
- [ ] Run workflow tests and commit `ci: add reliable static Atlas workflow`.

## Task 8: Integrate the new catalog and run acceptance checks

**Files:**
- Modify: `config/sp500_megarun_strategy_catalog_v1/README.md` or create the Atlas README under its generated directory.
- Create: `config/sp500_atlas_1/family_admission.json` as generated immutable input.
- Create: `config/sp500_atlas_1/README.md` as generated documentation.
- Modify: `docs/superpowers/specs/2026-08-17-sp500-reliable-catalog-megarun-design.md` only to record implementation evidence after tests.

- [ ] Generate the Atlas family admission manifest and verify it contains no unverified accepted family.
- [ ] Generate the Atlas catalog twice in a GitHub Actions preflight and compare artifact hashes.
- [ ] Run the focused Atlas test suite:

```powershell
& 'C:/Python314/python.exe' -m pytest `
  tests/test_sp500_atlas_contract.py `
  tests/test_sp500_atlas_objective.py `
  tests/test_sp500_atlas_robustness.py `
  tests/test_sp500_atlas_family_admission.py `
  tests/test_sp500_atlas_calibration.py `
  tests/test_sp500_atlas_workflow_contract.py -q
```

- [ ] Run the existing catalog optimization suite and require it to remain green.
- [ ] Run a train-only GitHub Actions smoke with a bounded sample and inspect its artifact manifest.
- [ ] Commit `test: verify Atlas catalog admission and smoke`.

## Task 9: Run calibration, plan the full workload and launch `ATLAS_1`

**Files:**
- No source changes unless a fail-closed acceptance check identifies a concrete bug.
- Artifacts: GitHub Actions calibration receipt, full-run plan, final result manifest and reduction report.

- [ ] Dispatch the calibration workflow using the exact implementation commit and the immutable train-only runtime pack.
- [ ] Verify the receipt is at most five minutes for the scientific sample and records zero protected-period access.
- [ ] Calculate cold versus component-warm total time including preparation and apply the 20 % safety margin.
- [ ] Generate the final static catalog plan and verify its recipe count, component count, shard count, target window and hashes.
- [ ] Launch the full Atlas workflow only after the plan is internally consistent.
- [ ] Monitor only run state, failed blocks, artifact counts and protected flags; do not change the catalog mid-run.
- [ ] Retry only failed blocks within the declared retry budget.
- [ ] Run the final reducer and verify 100 % recipe coverage, zero conflicts, Pareto output, robustness outputs and closed boundaries.
- [ ] Preserve every artifact and report the actual total duration separately from the scientific evaluation duration.

## Task 10: Final verification and branch handoff

- [ ] Run `git status --short --branch` and confirm only intentional, committed changes remain.
- [ ] Verify the final implementation commit, calibration run id, full-run id, catalog hash, result hash and boundary flags.
- [ ] Run the focused suite again from the final implementation commit.
- [ ] Record any unrelated full-suite failures separately; do not call them Atlas failures without evidence.
- [ ] Do not design or launch `ATLAS_2` in this plan.
- [ ] Use the finishing-development-branch procedure only after all acceptance evidence exists.

## Verification command summary

Local non-scientific checks:

```powershell
& 'C:/Python314/python.exe' -m pytest `
  tests/test_sp500_atlas_contract.py `
  tests/test_sp500_atlas_objective.py `
  tests/test_sp500_atlas_robustness.py `
  tests/test_sp500_atlas_family_admission.py `
  tests/test_sp500_atlas_calibration.py `
  tests/test_sp500_atlas_workflow_contract.py -q
```

Scientific checks:

- GitHub Actions calibration, hard-capped at five minutes for the scientific sample.
- GitHub Actions bounded smoke, train-only.
- GitHub Actions full static Atlas campaign, train-only.
- Final reduction and manifest verification in GitHub Actions.

No local backtest, optimization campaign, mass download or full scientific reduction is permitted.
