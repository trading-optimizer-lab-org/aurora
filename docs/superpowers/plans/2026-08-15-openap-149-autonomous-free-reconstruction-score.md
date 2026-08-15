# OpenAP 149 Autonomous Free Reconstruction and Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct, classify and audit all 149 target OpenAP signals from free authorised sources, then publish an independently calculated Aurora provisional score without claiming unproved stock-level equivalence to OpenAP.

**Architecture:** A frozen 149-row registry controls formula, source, point-in-time and admission decisions. Bounded source collectors create hash-bound receipts; family calculators emit a common long panel; a fail-closed admission layer produces separate formula-exact and extended scores; a final diagnostic compares independently constructed portfolios with public OpenAP portfolio returns without using that comparison to tune formulas.

**Tech Stack:** Python 3.14, pandas, pyarrow, PyYAML, requests/httpx already declared by Aurora, pytest, GitHub Actions, SEC/FINRA/PatentsView/BEA/French public data, existing Aurora OpenAP family modules.

## Global Constraints

- Authoritative worktree only: `C:\Users\HP\AURORA-openap-proxy44`.
- Branch only: `codex/openap-proxy44-validation`.
- Never modify `C:\Users\HP\AURORA` or the pre-existing untracked `.artifacts/` directory.
- No subagents and no forks. Execute this plan with `superpowers:executing-plans`.
- Local activity is limited to reading, editing and non-destructive Git operations.
- Every test, download, calculation, merge, benchmark and validation run executes in GitHub Actions.
- OOS locked and forward tiers remain closed. No workflow may set an unlock variable.
- OpenAP supplies pinned formulas, signs and public portfolio rules only; it does not supply stock-level target values.
- `formula_exacta`, `aproximacion_solida` and `bloqueada_gratis` are calculation classes, not correlation claims.
- A portfolio-return Spearman of 0.90 or more is labelled only as portfolio-behaviour similarity; it is never stock-level fidelity.
- All commits are small, reviewable and pushed before the corresponding GitHub run.

---

### Task 1: Bootstrap the remote TDD workflow and canonical policy

**Files:**

- Create: `.github/workflows/openap-149-autonomous-reconstruction.yml`
- Create: `config/openap_149_autonomous_reconstruction.yaml`
- Create: `tests/test_openap_149_autonomous_policy.py`
- Modify: `docs/superpowers/plans/2026-08-15-openap-149-autonomous-free-reconstruction-score.md`

- [ ] **Step 1: Write the failing policy tests**

Test that the YAML freezes:

```python
def test_policy_is_fail_closed_and_never_claims_strict_equivalence(policy):
    assert policy["target_count"] == 149
    assert policy["calculation_classes"] == [
        "formula_exacta", "aproximacion_solida", "bloqueada_gratis"
    ]
    assert policy["strict_stock_level_equivalence"] is False
    assert policy["strict_score_eligible_default"] is False
    assert policy["broad_signal_gate"] == {
        "minimum_valid_securities": 500,
        "minimum_source_eligible_coverage": 0.70,
    }
    assert policy["oos_locked"] is True
    assert policy["forward_locked"] is True
```

Also test the approximation contribution cap, minimum portfolio overlap, source-priority list and absence of unlock flags.

- [ ] **Step 2: Add a manual workflow with a branch-only test bootstrap trigger**

GitHub does not register a brand-new `workflow_dispatch` file until it exists on
the default branch. Therefore the workflow also uses a path-limited `push`
trigger on `codex/openap-proxy44-validation` for focused tests only. Live
reconstruction and finalisation remain explicit modes and never run from an
ordinary push.

The workflow must:

- expose `workflow_dispatch` for registered manual use;
- limit the bootstrap `push` trigger to this branch and the autonomous OpenAP
  implementation/test paths;
- accept `mode` (`tests`, `reconstruct`, `finalize`) and optional upstream artifact run IDs;
- check out the exact dispatched SHA;
- install the package and declared test dependencies;
- run only the named focused test files in `tests` mode;
- reject any environment variable matching `*UNLOCK*`;
- upload test logs even on failure;
- upload reconstruction artifacts only in the corresponding modes.

Initial focused command:

```yaml
python -m pytest -q tests/test_openap_149_autonomous_policy.py
```

- [ ] **Step 3: Commit and push the RED test/workflow**

```powershell
git add .github/workflows/openap-149-autonomous-reconstruction.yml tests/test_openap_149_autonomous_policy.py docs/superpowers/plans/2026-08-15-openap-149-autonomous-free-reconstruction-score.md
git commit -m "test: define OpenAP 149 autonomous policy"
git push origin codex/openap-proxy44-validation
gh workflow run openap-149-autonomous-reconstruction.yml --ref codex/openap-proxy44-validation -f mode=tests
gh run list --workflow openap-149-autonomous-reconstruction.yml --branch codex/openap-proxy44-validation --limit 1
```

Expected: failure because the policy file does not exist.

- [ ] **Step 4: Implement the minimum frozen YAML policy**

Include source priorities, collector limits, three classes, point-in-time rules, broad/sparse admission policies, formula-exact and extended score names, family caps, approximation cap, and no-strict-equivalence flags.

- [ ] **Step 5: Commit, push and obtain GREEN remotely**

```powershell
git add config/openap_149_autonomous_reconstruction.yaml
git commit -m "feat: freeze OpenAP 149 autonomous policy"
git push origin codex/openap-proxy44-validation
gh workflow run openap-149-autonomous-reconstruction.yml --ref codex/openap-proxy44-validation -f mode=tests
$openapRunId = gh run list --workflow openap-149-autonomous-reconstruction.yml --branch codex/openap-proxy44-validation --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $openapRunId --exit-status
```

Expected: policy test passes on the exact implementation SHA.

---

### Task 2: Build the exact 149-row reconstruction registry

**Files:**

- Create: `research/openap_149/reconstruction_registry.py`
- Create: `tests/test_openap_149_reconstruction_registry.py`
- Modify: `.github/workflows/openap-149-autonomous-reconstruction.yml`

**Interfaces:**

```python
@dataclass(frozen=True)
class ReconstructionPolicy:
    target_count: int
    broad_minimum_valid: int
    broad_minimum_coverage: float
    approximation_weight_cap: float

def load_policy(path: Path) -> ReconstructionPolicy: ...
def build_registry(
    acquisition_matrix: pd.DataFrame,
    formula_inventory: pd.DataFrame,
    policy: ReconstructionPolicy,
) -> pd.DataFrame: ...
def validate_registry(registry: pd.DataFrame, policy: ReconstructionPolicy) -> None: ...
def classify_signal(row: pd.Series) -> str: ...
```

- [ ] **Step 1: Write failing registry-contract tests**

Cover exactly 149 unique signals, pinned formula URL/hash, required inputs, sign/orientation, source route, eligible-universe rule, PIT rule, maximum staleness, implementation ID, calculation class, admission state and blocker. Reject duplicate/missing names, unknown classes, blank hashes and automatic strict admission.

- [ ] **Step 2: Extend the remote focused test list and prove RED**

```powershell
git add tests/test_openap_149_reconstruction_registry.py .github/workflows/openap-149-autonomous-reconstruction.yml
git commit -m "test: define OpenAP 149 registry contract"
git push origin codex/openap-proxy44-validation
gh workflow run openap-149-autonomous-reconstruction.yml --ref codex/openap-proxy44-validation -f mode=tests
```

Expected: import failure because `reconstruction_registry.py` does not exist.

- [ ] **Step 3: Implement registry loading, classification and validation**

Use `docs/OPENAP_149_ACQUISITION_MATRIX.csv` and the pinned official inventory as input evidence. Do not preserve legacy `reconstructed` or `proxy` labels as final classifications; translate them through explicit evidence fields. Make every terminal classification deterministic and fail closed.

- [ ] **Step 4: Emit the registry from a tiny CLI entry point**

The module's `main()` accepts input paths and writes:

- `openap_149_reconstruction_registry.csv`;
- `openap_149_reconstruction_registry_summary.json`;
- policy and input SHA-256 values.

- [ ] **Step 5: Commit, push and prove GREEN**

```powershell
git add research/openap_149/reconstruction_registry.py tests/test_openap_149_reconstruction_registry.py .github/workflows/openap-149-autonomous-reconstruction.yml
git commit -m "feat: add canonical OpenAP 149 reconstruction registry"
git push origin codex/openap-proxy44-validation
gh workflow run openap-149-autonomous-reconstruction.yml --ref codex/openap-proxy44-validation -f mode=tests
$openapRunId = gh run list --workflow openap-149-autonomous-reconstruction.yml --branch codex/openap-proxy44-validation --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $openapRunId --exit-status
```

---

### Task 3: Implement bounded free-source collection and evidence receipts

**Files:**

- Create: `config/openap_149_free_source_routes.yaml`
- Create: `research/openap_149/source_collector.py`
- Create: `tests/test_openap_149_source_collector.py`
- Modify: `.github/workflows/openap-149-autonomous-reconstruction.yml`

**Interfaces:**

```python
@dataclass(frozen=True)
class SourceRoute:
    source_id: str
    evidence_url: str
    retrieval_url: str
    media_type: str
    requests_per_second: float
    timeout_seconds: int
    parser_version: str
    licence: str

@dataclass(frozen=True)
class SourceReceipt:
    source_id: str
    retrieved_at: str
    effective_at: str | None
    byte_count: int
    sha256: str
    http_status: int
    route_hash: str
    disposition: str

def load_routes(path: Path) -> dict[str, SourceRoute]: ...
def fetch_route(route: SourceRoute, destination: Path, session: Any) -> SourceReceipt: ...
def validate_receipt(receipt: SourceReceipt) -> None: ...
```

- [ ] **Step 1: Write fixture-only failing tests**

Simulate 200, redirects, 403, 429 with `Retry-After`, timeouts, changed content type, HTML login/CAPTCHA/payment pages, duplicate payloads and schema drift. Tests must assert bounded retries, declared user agent, deterministic destination, byte count/hash and terminal block rather than bypass.

- [ ] **Step 2: Prove RED in GitHub**

Commit/push the tests and workflow update, dispatch `mode=tests`, and retain the failing log artifact.

- [ ] **Step 3: Implement the collector without real network calls in unit tests**

Prefer API/bulk routes. Enforce route-specific rate limits below official ceilings. Never use a visible browser. Do not introduce paid services, credentials, Gemini, Notion or generic crawling dependencies.

- [ ] **Step 4: Freeze the initial route catalogue**

Include SEC submissions, Company Facts, FSD and notes; FINRA short interest; PatentsView bulk tables; BEA input-output tables; French factors; public OpenAP formula and portfolio references. Each route records terms evidence and upstream provenance.

- [ ] **Step 5: Commit, push and prove GREEN**

Expected: all fixture tests pass and no live request occurs in `mode=tests`.

---

### Task 4: Normalise independent values and calculate honest coverage

**Files:**

- Create: `research/openap_149/provisional_score.py`
- Create: `tests/test_openap_149_score_admission.py`
- Modify: `.github/workflows/openap-149-autonomous-reconstruction.yml`

**Interfaces:**

```python
def canonicalize_values(values: pd.DataFrame) -> pd.DataFrame: ...
def calculate_source_eligible_coverage(
    values: pd.DataFrame,
    eligible_universe: pd.DataFrame,
) -> pd.DataFrame: ...
def build_score_admission(
    registry: pd.DataFrame,
    values: pd.DataFrame,
    eligible_universe: pd.DataFrame,
    policy: ReconstructionPolicy,
) -> pd.DataFrame: ...
```

- [ ] **Step 1: Write failing PIT, denominator and admission tests**

Test that:

- `available_at <= formation_at` is mandatory;
- amendments retain version history;
- broad coverage divides by the signal-specific eligible universe, not the 8,252-company global universe;
- 499 observations fail and 500 can pass;
- 69.9% fails and 70% can pass;
- sparse/event rows use their frozen applicability rule;
- constant, infinite, unit-invalid and stale values fail;
- the 31-item historical exact inventory is only a candidate list, never automatic admission;
- legacy calculated/proxy status cannot satisfy the new gate.

- [ ] **Step 2: Prove RED remotely**

Commit/push tests, dispatch and preserve failing logs.

- [ ] **Step 3: Implement canonical panel and fail-closed admission**

Canonical columns:

```text
security_id,symbol,cik,signal,formation_at,period_end,available_at,retrieved_at,
source_id,source_sha256,formula_sha256,value,calculation_class,caveat
```

Admission output includes every one of the 149 signals and explicit booleans/reasons for formula, source, PIT, freshness, denominator, count, variation and final admission.

- [ ] **Step 4: Commit, push and prove GREEN**

Expected: all policy, registry, collector and admission tests pass.

---

### Task 5: Build two provisional score layers with fixed influence

**Files:**

- Modify: `research/openap_149/provisional_score.py`
- Create: `tests/test_openap_149_provisional_score.py`
- Reference only: `research/openap_current_score.py`

**Interfaces:**

```python
def build_provisional_scores(
    values: pd.DataFrame,
    admission: pd.DataFrame,
    metadata: pd.DataFrame,
    policy: ReconstructionPolicy,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]: ...
```

- [ ] **Step 1: Write failing hand-calculated score tests**

Use tiny cross sections to prove signed percentiles, OpenAP orientation, one fixed vote per redundancy group, economic-family caps, neutral missingness, confidence reduction and the approximation contribution cap. Assert that blocked and non-admitted rows contribute zero and cannot change the basket per company.

- [ ] **Step 2: Prove RED remotely**

Commit/push and dispatch the focused tests.

- [ ] **Step 3: Implement by extracting/reusing proven pure logic**

Reuse `signed_percentile` semantics and the existing redundancy/family-cap design without importing current-run side effects. Produce:

- `aurora_formula_exact_score.parquet`, formula-exact admitted signals only;
- `aurora_extended_provisional_score.parquet`, exact plus capped solid approximations;
- `aurora_provisional_score_audit.json`, including per-family and approximation contributions.

- [ ] **Step 4: Commit, push and prove GREEN**

Expected: deterministic scores under shuffled input rows and complete audit reconciliation.

---

### Task 6: Orchestrate family reconstruction and terminal free-source classification

**Files:**

- Create: `research/openap_149/family_orchestrator.py`
- Create: `tests/test_openap_149_family_orchestrator.py`
- Create: `scripts/run_openap_149_autonomous_reconstruction.py`
- Modify: `.github/workflows/openap-149-autonomous-reconstruction.yml`
- Reuse: existing `research/openap_181/*`, `research/openap_149/*` and corresponding scripts only through explicit adapters

**Interfaces:**

```python
@dataclass(frozen=True)
class FamilyResult:
    family: str
    values: pd.DataFrame
    decisions: pd.DataFrame
    source_receipts: pd.DataFrame

def run_family(
    family: str,
    registry: pd.DataFrame,
    inputs: Path,
    output: Path,
) -> FamilyResult: ...
def reconcile_family_results(results: Sequence[FamilyResult]) -> tuple[pd.DataFrame, pd.DataFrame]: ...
```

- [ ] **Step 1: Write failing orchestration tests**

Cover partial family success, duplicate signal rejection, deterministic merges, exact failure reasons, no zero-imputation, hash propagation, and final reconciliation to exactly 149 decisions.

- [ ] **Step 2: Prove RED remotely**

- [ ] **Step 3: Implement Wave 0 adapters**

Re-read the existing hash-bound 149 bundle and exact-signal inventory. Translate each existing value into the new canonical schema; do not relabel unsupported proxies as exact.

- [ ] **Step 4: Implement Wave 1 adapters**

Use preserved price/volume/corporate-action inputs plus SEC face statements and French factors. Prioritise the unresolved formulas recoverable from these inputs, including factor residual/skew, valuation components and multi-year accounting histories.

- [ ] **Step 5: Implement Wave 2 adapters**

Use SEC filing/notes, FINRA, PatentsView and BEA inputs. Custom XBRL tags require an explicit semantic map and filing evidence.

- [ ] **Step 6: Implement Wave 3 terminal audit**

Governance, analyst, options, ratings, customer/supplier and other proprietary families receive either an executed public route or a precise `bloqueada_gratis` decision naming the missing input/history/identity/semantics.

- [ ] **Step 7: Implement runner outputs and reconciliation**

Required outputs:

```text
openap_149_reconstruction_registry.csv
openap_149_source_route_audit.csv
openap_149_source_snapshot_manifest.json
openap_149_point_in_time_input_audit.parquet
openap_149_independent_values.parquet
openap_149_calculation_decisions.csv
openap_149_score_admission.csv
aurora_formula_exact_score.parquet
aurora_extended_provisional_score.parquet
aurora_provisional_score_audit.json
```

Every file records exact repository SHA, policy hash and source hashes. Empty outputs need a machine-readable reason.

- [ ] **Step 8: Commit, push and prove GREEN with fixture inputs**

No live source acquisition is part of the unit-test run.

---

### Task 7: Validate portfolio behaviour without tuning or overclaim

**Files:**

- Create: `research/openap_149/portfolio_behavior.py`
- Create: `tests/test_openap_149_portfolio_behavior.py`
- Modify: `scripts/run_openap_149_autonomous_reconstruction.py`
- Modify: `.github/workflows/openap-149-autonomous-reconstruction.yml`

**Interfaces:**

```python
def construct_signal_portfolios(
    values: pd.DataFrame,
    returns: pd.DataFrame,
    rules: pd.DataFrame,
) -> pd.DataFrame: ...
def compare_portfolio_behavior(
    independent_returns: pd.DataFrame,
    official_returns: pd.DataFrame,
    minimum_overlap_months: int,
) -> tuple[pd.DataFrame, dict[str, Any]]: ...
```

- [ ] **Step 1: Write failing synthetic portfolio tests**

Prove formation lag, sign, filters, quantiles, weighting, holding period, overlap count, Pearson, Spearman, sign agreement and tracking error. Assert that `high_portfolio_behaviour_similarity` requires the frozen overlap/coverage and Spearman threshold, and never changes `strict_score_eligible`.

- [ ] **Step 2: Prove RED remotely**

- [ ] **Step 3: Implement frozen behaviour diagnostics**

Official portfolio returns are read-only benchmark evidence. No formula, source, parameter, universe or winsorisation choice may change after inspecting them.

- [ ] **Step 4: Add outputs**

```text
openap_149_portfolio_behaviour.csv
openap_149_portfolio_behaviour_summary.json
```

- [ ] **Step 5: Commit, push and prove GREEN**

---

### Task 8: Execute live free-source reconstruction in GitHub Actions

**Files:**

- Modify: `.github/workflows/openap-149-autonomous-reconstruction.yml`
- Modify: `scripts/run_openap_149_autonomous_reconstruction.py`

- [ ] **Step 1: Add live reconstruction job protections**

The `reconstruct` mode must:

- download named upstream artifacts by immutable run ID;
- verify each expected artifact and SHA before use;
- acquire only configured zero-cost public routes;
- use checkpoints and bounded source-specific retries;
- never request secrets for paid sources;
- never set OOS/forward unlock variables;
- run the full reconstruction and focused regression tests;
- emit and upload the complete result bundle on partial success;
- fail the job only for integrity/reconciliation violations, not for an honestly blocked signal.

- [ ] **Step 2: Commit/push the exact workflow SHA**

```powershell
git add .github/workflows/openap-149-autonomous-reconstruction.yml scripts/run_openap_149_autonomous_reconstruction.py
git commit -m "ci: run free OpenAP 149 reconstruction"
git push origin codex/openap-proxy44-validation
```

- [ ] **Step 3: Dispatch the live run**

```powershell
$acquisitionRunId = 31506361550
$formulaRunId = 31501243811
$priceRunId = 31504207654
gh workflow run openap-149-autonomous-reconstruction.yml --ref codex/openap-proxy44-validation -f mode=reconstruct -f acquisition_run_id=$acquisitionRunId -f formula_run_id=$formulaRunId -f price_run_id=$priceRunId
gh run list --workflow openap-149-autonomous-reconstruction.yml --branch codex/openap-proxy44-validation --limit 1
$openapRunId = gh run list --workflow openap-149-autonomous-reconstruction.yml --branch codex/openap-proxy44-validation --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $openapRunId --exit-status
```

- [ ] **Step 4: Inspect results outside the repository**

Create a fresh explicit temporary directory with PowerShell `New-Item`, verify its resolved path is outside both repository checkouts, download the artifact there, inspect counts/hashes/schemas read-only, then preserve the evidence path. Do not use or alter `.artifacts/`.

- [ ] **Step 5: Rerun only evidence-backed recoverable failures**

Retry only bounded transport failures or code defects. A source requiring login, CAPTCHA, payment, forbidden automation or unavailable history becomes terminally blocked; it does not justify a substitute chosen for apparent correlation.

---

### Task 9: Reconcile final artifacts, documentation and exact-head evidence

**Files:**

- Create: `docs/OPENAP_149_AUTONOMOUS_RECONSTRUCTION_STATUS.md`
- Modify: `docs/OPENAP_149_ACQUISITION_MATRIX.csv`
- Modify: `docs/superpowers/plans/2026-08-15-openap-149-autonomous-free-reconstruction-score.md`
- Modify: `.github/workflows/openap-149-autonomous-reconstruction.yml`

- [ ] **Step 1: Update the ledger from generated decisions, never by hand inference**

Reconcile exactly 149 rows and report numerical counts for:

- formula exact;
- solid approximation;
- blocked free;
- PIT-valid calculated;
- score admitted exact;
- score admitted approximation;
- strict stock-level equivalent (expected zero unless independent identity validation exists);
- portfolio-behaviour high similarity;
- source and coverage failures.

- [ ] **Step 2: Write the status document**

Record exact Git SHA, GitHub run URL/ID, artifact name/hash, source snapshots, maximum data date, row/security/month counts, score availability, limitations and next genuine blocker. State plainly that the Aurora score is not the OpenAP score.

- [ ] **Step 3: Add final artifact-verifier tests**

Verify required filenames, schemas, non-empty or reason fields, SHA manifest, 149 reconciliation, no strict overclaim and score/audit totals.

- [ ] **Step 4: Commit/push and run final exact-head workflow**

```powershell
git add docs/OPENAP_149_AUTONOMOUS_RECONSTRUCTION_STATUS.md docs/OPENAP_149_ACQUISITION_MATRIX.csv docs/superpowers/plans/2026-08-15-openap-149-autonomous-free-reconstruction-score.md .github/workflows/openap-149-autonomous-reconstruction.yml tests
git commit -m "docs: reconcile autonomous OpenAP 149 reconstruction"
git push origin codex/openap-proxy44-validation
$reconstructionRunId = gh run list --workflow openap-149-autonomous-reconstruction.yml --branch codex/openap-proxy44-validation --limit 1 --json databaseId --jq '.[0].databaseId'
gh workflow run openap-149-autonomous-reconstruction.yml --ref codex/openap-proxy44-validation -f mode=finalize -f reconstruction_run_id=$reconstructionRunId
$finalRunId = gh run list --workflow openap-149-autonomous-reconstruction.yml --branch codex/openap-proxy44-validation --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $finalRunId --exit-status
```

- [ ] **Step 5: Verify repository boundaries and exact HEAD**

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/codex/openap-proxy44-validation
git -C C:\Users\HP\AURORA status --short --branch
```

Expected: authoritative branch and remote hashes match; only the pre-existing `.artifacts/` remains untracked; primary checkout has not changed because of this objective.

- [ ] **Step 6: Close only with evidence**

The objective is complete only when the final exact-head GitHub run passes, the uploaded bundle reconciles, all 149 rows have one terminal class, the two provisional score outputs exist or carry an exact no-score reason, and remaining strict/PERMNO limitations are explicit.
