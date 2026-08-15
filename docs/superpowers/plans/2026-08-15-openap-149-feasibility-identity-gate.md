# OpenAP 149 Feasibility and Identity Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Subagents
> and forks are prohibited for this project.

**Goal:** Produce a reproducible 149-signal feasibility register and resolve or
conclusively block the zero-cost historical PERMNO identity gate before any
pilot reconstruction is allowed.

**Architecture:** Add two focused modules: one reconciles the existing 149-row
evidence into the approved 142/6/1 classes, and one validates source routes and
historical security-to-PERMNO intervals without consulting OpenAP signal
values. A GitHub-only runner writes hash-bound artifacts and a machine-readable
go/no-go decision. The existing manually dispatched correlation workflow gains
an isolated sentinel mode so the new code can run from this branch without
merging a new workflow into the default branch.

**Tech Stack:** Python 3.12, pandas, PyYAML, pytest, GitHub Actions, SHA-256.

## Global Constraints

- Authoritative worktree: `C:\Users\HP\AURORA-openap-proxy44`.
- Branch: `codex/openap-proxy44-validation`.
- Do not touch the dirty checkout `C:\Users\HP\AURORA`.
- No subagents and no forks.
- Cost is exactly zero; do not assume institutional CRSP or WRDS access.
- Local work is limited to inspection, editing, and non-destructive git.
- All tests, source probes, downloads, and audits run in GitHub Actions.
- OpenAP values are prohibited for identity selection, calculation, tuning, or
  correction.
- Protected OOS and forward tiers remain closed.
- Only a strict identity `pass` may unlock the later 10-signal pilot plan.

---

### Task 1: Freeze the feasibility classification contract

**Files:**

- Create: `config/openap_149_feasibility.yaml`
- Create: `research/openap_149/__init__.py`
- Create: `research/openap_149/feasibility.py`
- Create: `tests/test_openap_149_feasibility_gate.py`

**Interfaces:**

- Consumes: `docs/OPENAP_149_ACQUISITION_MATRIX.csv` and
  `docs/OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv`.
- Produces:
  `build_feasibility_register(acquisition: pd.DataFrame, reaudit: pd.DataFrame, contract: Mapping[str, object]) -> pd.DataFrame`
  and `summarize_feasibility(register: pd.DataFrame) -> dict[str, object]`.

- [ ] **Step 1: Write the frozen YAML contract**

```yaml
dataset_id: openap_149_feasibility_v1
target_count: 149
strict_threshold: 0.90
pilot_signals:
  - Beta
  - High52
  - RealizedVol
  - VolSD
  - VolumeTrend
  - Cash
  - BM
  - EP
  - GP
  - TotalAccruals
source_blocked_signals:
  Activism1: proprietary_governance_and_13f_inputs_without_complete_free_replacement
  Activism2: proprietary_governance_and_13f_inputs_without_complete_free_replacement
  Mom6mJunk: proprietary_historical_credit_ratings_without_complete_free_replacement
  CustomerMomentum: proprietary_customer_relationship_history_without_complete_free_replacement
  retConglomerate: proprietary_standardized_segment_history_without_complete_free_replacement
  sinAlgo: proprietary_standardized_segment_industry_history_without_complete_free_replacement
official_reference_unavailable:
  Size: omitted_from_downloadable_openap_stock_panel
expected_classes:
  unproved: 142
  blocked_source: 6
  not_evaluable_reference: 1
  approved: 0
```

- [ ] **Step 2: Write failing tests for exact inventory and fail-closed classes**

```python
def test_feasibility_register_reconciles_exactly_149() -> None:
    register = build_from_repository(ROOT)
    assert len(register) == 149
    assert register["signal"].is_unique
    assert register["feasibility_class"].value_counts().to_dict() == {
        "unproved": 142,
        "blocked_source": 6,
        "not_evaluable_reference": 1,
    }
    assert not register["strict_score_eligible"].any()


def test_previously_calculated_never_means_approved() -> None:
    register = build_from_repository(ROOT)
    calculated = register["current_value_calculated"]
    assert calculated.sum() == 115
    assert register.loc[calculated, "feasibility_class"].ne("approved").all()
```

- [ ] **Step 3: Implement strict reconciliation**

The module must reject duplicate signals, any target count other than 149,
missing acquisition rows, unexpected override names, a non-zero existing
`strict_score_eligible` value, or expected-class count drift. It must expose
these columns:

```python
REGISTER_COLUMNS = (
    "signal", "category", "feasibility_class", "classification_reason",
    "current_value_calculated", "current_status", "strict_score_eligible",
    "original_input_class", "proposed_free_sources", "remaining_blocker",
    "official_formula_url", "source_checked_at",
)
```

- [ ] **Step 4: Add summary tests and implementation**

```python
def test_summary_uses_only_independent_approval_count() -> None:
    summary = summarize_feasibility(build_from_repository(ROOT))
    assert summary["target_count"] == 149
    assert summary["strictly_approved"] == 0
    assert summary["previously_calculated_non_strict"] == 115
    assert summary["identity_gate_status"] == "not_run"
```

- [ ] **Step 5: Run in GitHub and commit after the focused tests pass**

GitHub command:

```bash
python -m pytest tests/test_openap_149_feasibility_gate.py -q
```

Commit:

```bash
git add config/openap_149_feasibility.yaml research/openap_149 tests/test_openap_149_feasibility_gate.py
git commit -m "feat: freeze OpenAP 149 feasibility classes"
```

### Task 2: Define the non-circular identity-source catalogue

**Files:**

- Create: `config/openap_149_identity_sources.yaml`
- Create: `research/openap_149/identity_sources.py`
- Modify: `tests/test_openap_149_feasibility_gate.py`

**Interfaces:**

- Consumes: versioned source declarations with official evidence URLs.
- Produces:
  `load_identity_source_catalog(path: Path) -> list[IdentitySource]` and
  `evaluate_public_identity_routes(sources: Sequence[IdentitySource]) -> pd.DataFrame`.

- [ ] **Step 1: Write source declarations**

The catalogue must include SEC company tickers/exchanges, SEC 13F, OpenFIGI,
OpenAP stock panel, CRSP/CRSP10, Field-Ritter IPO dates, and the public patent
PERMNO subset. Each record must state booleans for `provides_permno`,
`provides_public_identifier`, `historical_intervals`, `share_class_specific`,
`broad_universe`, `public_zero_cost`, `authorized_for_internal_research`, and
`target_derived` plus an official evidence URL and checked date.

- [ ] **Step 2: Write failing route tests**

```python
def test_no_declared_route_currently_passes_all_identity_requirements() -> None:
    decisions = evaluate_public_identity_routes(load_default_identity_sources())
    assert not decisions["route_pass"].any()
    assert set(decisions.loc[decisions["source_id"].eq("openfigi"), "missing_requirements"].iloc[0].split("|")) >= {
        "provides_permno", "historical_intervals"
    }


def test_target_derived_source_can_never_build_bridge() -> None:
    decisions = evaluate_public_identity_routes(load_default_identity_sources())
    openap = decisions.set_index("source_id").loc["openap_stock_panel"]
    assert not bool(openap["route_pass"])
    assert "target_derived" in openap["disqualifiers"]
```

- [ ] **Step 3: Implement immutable dataclass and all-requirements evaluator**

```python
@dataclass(frozen=True)
class IdentitySource:
    source_id: str
    evidence_url: str
    checked_at: str
    provides_permno: bool
    provides_public_identifier: bool
    historical_intervals: bool
    share_class_specific: bool
    broad_universe: bool
    public_zero_cost: bool
    authorized_for_internal_research: bool
    target_derived: bool
```

`route_pass` is true only when every positive requirement is true and
`target_derived` is false. Missing fields, duplicate source IDs, non-HTTPS URLs,
or unchecked dates fail closed.

- [ ] **Step 4: Run focused tests in GitHub and commit**

```bash
python -m pytest tests/test_openap_149_feasibility_gate.py -q
git add config/openap_149_identity_sources.yaml research/openap_149/identity_sources.py tests/test_openap_149_feasibility_gate.py
git commit -m "feat: audit free PERMNO source routes"
```

### Task 3: Validate and freeze a candidate historical bridge

**Files:**

- Create: `research/openap_149/identity_gate.py`
- Create: `tests/test_openap_149_identity_gate.py`

**Interfaces:**

- Consumes: a candidate CSV/Parquet bridge and, only after freezing the bridge,
  an OpenAP identifier-only spine containing `permno` and `yyyymm`.
- Produces:
  `validate_bridge(frame: pd.DataFrame) -> pd.DataFrame`,
  `freeze_bridge(frame: pd.DataFrame, output: Path) -> BridgeManifest`, and
  `evaluate_bridge_coverage(bridge: pd.DataFrame, reference_spine: pd.DataFrame) -> IdentityGateDecision`.

- [ ] **Step 1: Write failing schema, interval, and anti-circularity tests**

```python
REQUIRED_BRIDGE_COLUMNS = {
    "canonical_security_id", "permno", "valid_from", "valid_to",
    "share_class_id", "evidence_url", "evidence_kind", "source_id",
    "source_retrieved_at", "source_sha256", "zero_cost_authorized",
}


def test_bridge_rejects_ticker_only_and_target_derived_evidence() -> None:
    with pytest.raises(IdentityGateError, match="canonical_security_id"):
        validate_bridge(pd.DataFrame({"ticker": ["AAA"], "permno": [10001]}))
    frame = valid_bridge_frame()
    frame["evidence_kind"] = "openap_characteristic_match"
    with pytest.raises(IdentityGateError, match="target-derived"):
        validate_bridge(frame)


def test_bridge_rejects_overlapping_many_to_one_intervals() -> None:
    frame = pd.concat([valid_bridge_frame(), valid_bridge_frame()])
    frame.loc[1, "canonical_security_id"] = "sec:other"
    with pytest.raises(IdentityGateError, match="overlap"):
        validate_bridge(frame)
```

- [ ] **Step 2: Implement deterministic normalization and validation**

Dates are UTC-normalized; PERMNO is a positive integer; SHA-256 is exactly 64
lowercase hexadecimal characters; all rows require
`zero_cost_authorized == True`; and simultaneous one-to-many or many-to-one
interval overlaps fail. Allowed evidence kinds are direct identifier histories,
issuer filings, exchange records, and independently licensed identifier links.

- [ ] **Step 3: Write and implement bridge freezing**

```python
@dataclass(frozen=True)
class BridgeManifest:
    rows: int
    min_valid_from: str
    max_valid_to: str
    bridge_sha256: str
    frozen_before_reference_read: bool
```

The normalized bridge is written to `openap_permno_bridge.parquet`; the manifest
is written before the caller may load a reference spine. Tests must prove stable
hashes across input row order and reject a caller-supplied
`frozen_before_reference_read=False` state.

- [ ] **Step 4: Write and implement monthly coverage decisions**

```python
def test_coverage_requires_every_month_and_seventy_percent() -> None:
    decision = evaluate_bridge_coverage(bridge, reference_spine)
    assert decision.minimum_monthly_coverage >= 0.70
    assert decision.ambiguous_links == 0
    assert decision.status == "pass"
```

The decision reports coverage for every month from 2023-01 through 2024-12,
minimum/median/maximum coverage, retained pairs, excluded ambiguous pairs, and
fails if any required month is below 0.70.

- [ ] **Step 5: Run focused tests in GitHub and commit**

```bash
python -m pytest tests/test_openap_149_identity_gate.py -q
git add research/openap_149/identity_gate.py tests/test_openap_149_identity_gate.py
git commit -m "feat: enforce historical PERMNO identity gate"
```

### Task 4: Build the GitHub-only evidence runner

**Files:**

- Create: `scripts/run_openap_149_identity_gate.py`
- Modify: `tests/test_openap_149_identity_gate.py`

**Interfaces:**

- Consumes: repository matrices/configs, optional `--candidate-bridge`, and
  optional `--reference-spine` only after a bridge freeze.
- Produces the Phase 0/1 artifacts and always exits zero for a scientifically
  valid no-go; malformed or internally inconsistent evidence exits non-zero.

- [ ] **Step 1: Write runner-output tests**

```python
def test_runner_without_candidate_bridge_emits_valid_no_go(tmp_path: Path) -> None:
    assert run(make_args(output_dir=tmp_path, candidate_bridge=None)) == 0
    decision = json.loads((tmp_path / "openap_identity_gate_decision.json").read_text())
    assert decision["status"] == "blocked_identity"
    assert decision["strictly_approved"] == 0
    assert decision["pilot_authorized"] is False
    assert decision["reason"] == "no_authorized_zero_cost_historical_permno_bridge"
```

- [ ] **Step 2: Implement the fail-closed runner**

The script must call
`require_github_actions_or_explicit_local_permission("OpenAP 149 identity gate")`
from `aurora.core.execution_policy`. It writes:

```text
openap_149_feasibility_register.csv
openap_149_feasibility_summary.json
openap_149_identity_source_audit.csv
openap_permno_bridge.parquet
openap_permno_bridge_manifest.json
openap_permno_bridge_audit.csv
openap_identity_gate_decision.json
openap_149_feasibility_summary.md
```

On a no-go, the bridge Parquet and audit CSV have their declared schemas but
zero rows. The decision records repository SHA, source/config hashes,
`locked_opened=false`, `validation_used_for_identity=false`,
`strictly_approved=0`, and `pilot_authorized=false`.

- [ ] **Step 3: Add artifact reconciliation tests**

Tests assert exact 149 rows, exact 142/6/1 classes, zero approved, matching
hashes, no target-derived source accepted, and consistency between CSV, JSON,
Markdown, and Parquet artifacts.

- [ ] **Step 4: Run focused tests in GitHub and commit**

```bash
python -m pytest tests/test_openap_149_feasibility_gate.py tests/test_openap_149_identity_gate.py -q
git add scripts/run_openap_149_identity_gate.py tests/test_openap_149_identity_gate.py
git commit -m "feat: emit OpenAP identity go-no-go evidence"
```

### Task 5: Add isolated execution mode to the existing workflow

**Files:**

- Modify: `.github/workflows/openap-proxy-real-correlation-audit.yml`
- Modify: `tests/test_openap_149_identity_gate.py`

**Interfaces:**

- Consumes: existing dispatch input `proxy_panel_url` set exactly to
  `IDENTITY_FEASIBILITY_ONLY`; this avoids adding an input unknown to the
  default-branch workflow dispatcher.
- Produces artifact `openap-149-identity-feasibility-results`.

- [ ] **Step 1: Write failing workflow-contract tests**

```python
def test_existing_workflow_has_isolated_identity_mode() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    assert jobs["identity_feasibility"]["if"] == (
        "${{ inputs.proxy_panel_url == 'IDENTITY_FEASIBILITY_ONLY' }}"
    )
    assert "run_openap_149_identity_gate.py" in workflow_text
    assert jobs["audit"]["if"] == (
        "${{ inputs.proxy_panel_url != 'IDENTITY_FEASIBILITY_ONLY' }}"
    )
```

- [ ] **Step 2: Add validation and identity jobs**

The existing `validate` job runs both new test files. The new
`identity_feasibility` job checks out the requested branch, installs only
declared dependencies, executes the runner without a candidate bridge, verifies
the decision is exactly `blocked_identity` or `pass`, asserts `locked_opened`
and `validation_used_for_identity` are false, and uploads the complete artifact
for 30 days. The legacy heavy `audit` job is skipped in sentinel mode.

- [ ] **Step 3: Run YAML/static checks through the workflow and commit**

```bash
git add .github/workflows/openap-proxy-real-correlation-audit.yml tests/test_openap_149_identity_gate.py
git commit -m "ci: add OpenAP identity feasibility mode"
```

### Task 6: Execute and close the identity gate

**Files:**

- Create: `docs/OPENAP_149_IDENTITY_GATE_STATUS.md`
- Modify: `docs/OPENAP_149_ACQUISITION_STATUS.md` only if its current strict
  status conflicts with the new evidence.

**Interfaces:**

- Consumes: completed GitHub artifact and run metadata.
- Produces: a committed evidence-backed decision and either the next pilot plan
  or a final identity no-go report.

- [ ] **Step 1: Push the branch without touching the primary checkout**

```bash
git push origin codex/openap-proxy44-validation
```

- [ ] **Step 2: Dispatch the existing workflow in isolated mode**

```bash
gh workflow run openap-proxy-real-correlation-audit.yml \
  --ref codex/openap-proxy44-validation \
  -f proxy_panel_url=IDENTITY_FEASIBILITY_ONLY
```

- [ ] **Step 3: Monitor to terminal state and download only the new artifact**

Use non-interactive `gh run view` and `gh api`/`gh run download`. Do not launch
another run while this one is active. Record run ID, URL, head SHA, conclusion,
artifact ID, artifact digest where exposed, and file SHA-256 values.

- [ ] **Step 4: Validate the artifact in a temporary directory**

Check exact schemas, 149 rows, 142/6/1 reconciliation, zero strict approvals,
all manifest hashes, and the decision/pilot flag. This validation is inspection
of a completed GitHub artifact, not a local research run.

- [ ] **Step 5: Commit the evidence status**

```bash
git add docs/OPENAP_149_IDENTITY_GATE_STATUS.md
git add -u docs/OPENAP_149_ACQUISITION_STATUS.md
git commit -m "docs: record OpenAP identity gate decision"
git push origin codex/openap-proxy44-validation
```

- [ ] **Step 6: Follow the machine decision autonomously**

If `pilot_authorized=true`, write the separate frozen 10-signal pilot plan and
execute it with `superpowers:executing-plans`. If false, do not build pilot
calculators; close the approved design with Outcome A and report precisely what
new authorised source or user-supplied institutional access would be required
to reopen the gate.
