# OpenAP 149 Identity Recovery V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagents and forks are prohibited for this work.

**Goal:** Build and execute a GitHub-only, fail-closed audit of all credible public zero-cost routes to a historical security-to-PERMNO bridge, authorising the frozen ten-signal pilot only if the bridge covers at least 70 percent in every month of 2023-2024 with zero ambiguity.

**Architecture:** A versioned YAML catalogue states documentary facts and probe policy for each route. A focused Python module validates the catalogue, records bounded HTTP probe receipts, classifies routes, normalises only eligible bridge rows, and delegates freezing and monthly coverage to the existing identity gate. A thin GitHub-only runner writes a reconciled artifact bundle, while an isolated workflow mode prevents the inherited heavy proxy audit from running.

**Tech Stack:** Python 3.12, dataclasses, `requests`, pandas, PyArrow, PyYAML, pytest, GitHub Actions, existing `aurora.research.openap_149.identity_gate` primitives.

## Global Constraints

- Work only in `C:\Users\HP\AURORA-openap-proxy44` on `codex/openap-proxy44-validation`.
- Never modify `C:\Users\HP\AURORA` or `.artifacts/`.
- No subagents and no forks.
- No local tests, probes, downloads, coverage calculations or research runs.
- All execution evidence comes from GitHub Actions at the exact tested SHA.
- OOS-locked and forward data remain closed.
- Never use OpenAP signal values to construct or repair identity.
- Require explicit zero-cost authority, direct PERMNO, a public security-level identifier, validity intervals, share-class specificity, broad 2023-2024 coverage and `target_derived=false` before a route can contribute rows.
- Require at least 70 percent coverage in every month from 2023-01 through 2024-12 and zero ambiguous links.
- A passing workflow means the audit executed correctly; only `identity_pass` authorises the pilot.

---

## File map

- Create `config/openap_149_identity_sources_v2.yaml`: frozen facts, evidence URLs, probe policies and expected blockers for the expanded route catalogue.
- Create `research/openap_149/identity_recovery_v2.py`: catalogue validation, probe receipts, schema observations, route classification, bridge extraction and aggregate decision.
- Create `scripts/run_openap_149_identity_recovery_v2.py`: GitHub-only CLI and artifact writer.
- Create `tests/test_openap_149_identity_recovery_v2.py`: deterministic unit, runner and workflow-contract tests.
- Modify `.github/workflows/openap-proxy-real-correlation-audit.yml`: add the isolated `IDENTITY_SOURCE_RECOVERY_V2` mode and prevent the heavy audit job from running in that mode.
- Modify `docs/OPENAP_149_IDENTITY_GATE_STATUS.md`: record the exact v2 run, artifact digest, route counts and final pilot decision after execution.

### Task 1: Freeze the v2 catalogue and RED contract

**Files:**
- Create: `config/openap_149_identity_sources_v2.yaml`
- Create: `tests/test_openap_149_identity_recovery_v2.py`
- Modify: `.github/workflows/openap-proxy-real-correlation-audit.yml`

**Interfaces:**
- Consumes: the route facts and source URLs frozen in the approved v2 design.
- Produces: `load_recovery_catalog(path: Path) -> list[RecoverySource]`, `classify_source(source: RecoverySource, receipt: ProbeReceipt | None) -> str`, and the workflow sentinel `IDENTITY_SOURCE_RECOVERY_V2`, which deliberately do not exist yet.

- [ ] **Step 1: Add the explicit source catalogue**

Create version `openap_149_identity_sources_v2` with exactly these stable route IDs:

```yaml
sources:
  - source_id: sec_company_tickers_exchange
  - source_id: sec_13f
  - source_id: openfigi
  - source_id: crsp_research_products
  - source_id: crsp_sample_data
  - source_id: wrds_demo
  - source_id: std_security_code
  - source_id: open_source_bond_asset_pricing
  - source_id: chuck_fang_bond_firm_link
  - source_id: corp_bond_data
  - source_id: oxford_ownership_productivity
  - source_id: michels_2017
  - source_id: field_ritter_ipo
  - source_id: kpss_patent_crsp_extended
  - source_id: openap_characteristic_fingerprint
```

Every row must explicitly set all contract booleans, `evidence_url`,
`retrieval_url`, `probe_policy`, `expected_media_type`, `parser`,
`upstream_provenance`, `universe_limit`, and `documentary_blocker`. Use
`download_small` only for `michels_2017`, bounded evidence-page GETs where
useful, and `documentary_only` for paid or rights-blocked data endpoints.

- [ ] **Step 2: Write failing catalogue and classification tests**

Add tests that import the not-yet-created module and require:

```python
def test_v2_catalogue_has_fifteen_explicit_unique_routes() -> None:
    sources = load_recovery_catalog(CATALOGUE)
    assert len(sources) == 15
    assert len({source.source_id for source in sources}) == 15
    assert all(source.documentary_blocker for source in sources)


def test_target_fingerprint_is_always_disqualified() -> None:
    source = next(
        item for item in load_recovery_catalog(CATALOGUE)
        if item.source_id == "openap_characteristic_fingerprint"
    )
    assert classify_source(source, None) == "blocked_target_derived"


def test_static_wrds_derived_table_is_not_licensed_by_repository_license() -> None:
    source = next(
        item for item in load_recovery_catalog(CATALOGUE)
        if item.source_id == "std_security_code"
    )
    assert classify_source(source, None) == "blocked_rights"
```

Also require malformed booleans, duplicate IDs, missing blockers and non-HTTPS
URLs to raise `IdentityRecoveryError`.

- [ ] **Step 3: Add the isolated workflow contract in RED state**

Add `identity_source_recovery_v2` with:

```yaml
if: ${{ inputs.proxy_panel_url == 'IDENTITY_SOURCE_RECOVERY_V2' }}
```

Make the inherited `audit` job run only when `proxy_panel_url` is neither
`IDENTITY_FEASIBILITY_ONLY` nor `IDENTITY_SOURCE_RECOVERY_V2`. Add the new test
file and not-yet-created module/runner to the `validate` job so the first run
fails before any source request.

- [ ] **Step 4: Commit and push the RED state**

```powershell
git add -- config/openap_149_identity_sources_v2.yaml tests/test_openap_149_identity_recovery_v2.py .github/workflows/openap-proxy-real-correlation-audit.yml
git commit -m "test: define OpenAP identity recovery v2 contract"
git push origin codex/openap-proxy44-validation
```

- [ ] **Step 5: Run the RED workflow on GitHub**

```powershell
gh workflow run openap-proxy-real-correlation-audit.yml --ref codex/openap-proxy44-validation -f proxy_panel_url=IDENTITY_SOURCE_RECOVERY_V2
```

Expected: `validate` fails because `aurora.research.openap_149.identity_recovery_v2`
or the v2 runner is absent. Record the run ID and exact failure; do not treat
this expected RED run as source evidence.

- [ ] **Step 6: Commit task checkpoint only after confirming RED**

No additional commit is needed if the pushed RED commit is unchanged. Record
the run ID in the execution notes used for the final status document.

### Task 2: Implement catalogue validation and fail-closed classification

**Files:**
- Create: `research/openap_149/identity_recovery_v2.py`
- Test: `tests/test_openap_149_identity_recovery_v2.py`

**Interfaces:**
- Consumes: `config/openap_149_identity_sources_v2.yaml`.
- Produces: `RecoverySource`, `ProbeReceipt`, `IdentityRecoveryError`, `load_recovery_catalog`, `classify_source`, `probe_source`, `audit_sources`, and `build_candidate_bridge`.

- [ ] **Step 1: Define immutable source and receipt types**

Use these public fields:

```python
@dataclass(frozen=True)
class RecoverySource:
    source_id: str
    evidence_url: str
    retrieval_url: str
    checked_at: str
    probe_policy: str
    expected_media_type: str
    parser: str
    public_access_without_login: bool
    public_zero_cost: bool
    authorized_for_internal_research: bool
    upstream_license_required: bool
    provides_permno: bool
    provides_public_security_id: bool
    historical_intervals: bool
    share_class_specific: bool
    covers_2023_2024: bool
    broad_universe: bool
    target_derived: bool
    upstream_provenance: str
    universe_limit: str
    documentary_blocker: str


@dataclass(frozen=True)
class ProbeReceipt:
    source_id: str
    attempted: bool
    status_code: int | None
    final_url: str
    content_type: str
    bytes_observed: int
    sha256: str
    observed_columns: tuple[str, ...]
    retrieved_at: str
    error: str
```

- [ ] **Step 2: Validate catalogue values strictly**

`load_recovery_catalog` must reject implicit/non-boolean flags, unknown probe
policies, unknown parsers, duplicate or blank IDs, non-HTTPS URLs, invalid
dates, blank provenance/limits, and missing documentary blockers.

- [ ] **Step 3: Implement deterministic terminal-priority classification**

Apply this order:

```python
if source.target_derived:
    return "blocked_target_derived"
if not source.public_zero_cost or not source.public_access_without_login:
    return "blocked_access"
if not source.authorized_for_internal_research or source.upstream_license_required:
    return "blocked_rights"
if not source.provides_permno or not source.provides_public_security_id:
    return "blocked_schema"
if not source.historical_intervals or not source.share_class_specific:
    return "blocked_semantics"
if not source.covers_2023_2024 or not source.broad_universe:
    return "blocked_coverage_claim"
if receipt is None or (receipt.attempted and receipt.error):
    return "probe_error"
return "pass_candidate"
```

The audit output also preserves every failed dimension, so terminal priority
does not hide secondary blockers.

- [ ] **Step 4: Implement bounded probes with dependency injection**

`probe_source(source, *, getter, now) -> ProbeReceipt` must:

- return a non-attempted receipt for `documentary_only`;
- cap GET response consumption at 1 MiB except `download_small` at 256 KiB;
- use connect/read timeouts and a descriptive User-Agent;
- reject redirects to login/payment hosts;
- hash exactly the observed bytes;
- extract CSV headers, JSON keys, Parquet schema or HTML/text evidence terms;
- never log credentials or query parameters.

- [ ] **Step 5: Build only canonical bridge rows**

`build_candidate_bridge(audit, payloads) -> pd.DataFrame` may parse rows only
from `pass_candidate` routes with parser `canonical_bridge_csv`. It must require
the existing `BRIDGE_COLUMNS`, add no inferred dates/classes, and return an
empty DataFrame with those columns when no route passes.

- [ ] **Step 6: Push implementation and run focused GREEN validation**

```powershell
git add -- research/openap_149/identity_recovery_v2.py tests/test_openap_149_identity_recovery_v2.py
git commit -m "feat: audit OpenAP identity recovery sources"
git push origin codex/openap-proxy44-validation
gh workflow run openap-proxy-real-correlation-audit.yml --ref codex/openap-proxy44-validation -f proxy_panel_url=IDENTITY_SOURCE_RECOVERY_V2
```

Expected: catalogue/classification/probe unit tests pass. The source job may
still fail because the runner is intentionally absent until Task 3.

### Task 3: Implement the GitHub-only runner and reconciled artifacts

**Files:**
- Create: `scripts/run_openap_149_identity_recovery_v2.py`
- Modify: `tests/test_openap_149_identity_recovery_v2.py`
- Modify: `.github/workflows/openap-proxy-real-correlation-audit.yml`

**Interfaces:**
- Consumes: `audit_sources`, `build_candidate_bridge`, `freeze_bridge`, optional identifier-only reference spine.
- Produces: `run(args: argparse.Namespace) -> int` and the eight artifact paths specified by the design.

- [ ] **Step 1: Add failing runner tests**

Mock all HTTP responses and require a no-candidate execution to emit:

```python
assert decision["status"] == "blocked_identity_v2"
assert decision["pilot_authorized"] is False
assert decision["strictly_approved"] == 0
assert decision["candidate_routes"] == 0
assert decision["bridge_rows"] == 0
assert decision["locked_opened"] is False
assert decision["target_derived_used_for_identity"] is False
assert len(audit) == 15
assert sum(decision["route_class_counts"].values()) == 15
```

Require JSONL receipt count 15, including non-attempted documentary receipts;
stable hashes; an empty bridge with the canonical schema; and exact SHA binding
for the catalogue, audit, receipts and bridge.

- [ ] **Step 2: Add a synthetic pass-path test**

Supply a canonical bridge CSV fixture with three securities active through all
24 months and an identifier-only reference spine of four securities per month.
Require `identity_pass`, 0.75 minimum monthly coverage and pilot authorisation.
No signal value column is permitted in the reference fixture.

- [ ] **Step 3: Implement the runner**

The CLI accepts:

```text
--catalogue
--output-dir
--repository-sha
--reference-spine (optional)
```

Call `require_github_actions_or_explicit_local_permission` before `run`. Probe
routes, write receipts/audit, build and freeze the bridge, and read the optional
reference spine only after freeze. If the bridge is empty, write an empty
monthly coverage CSV and `blocked_identity_v2`. If rows exist but the reference
spine is absent, write `candidate_bridge_requires_reference_spine` with pilot
false rather than opening unrelated data.

- [ ] **Step 4: Complete the workflow source job**

Install only `requests`, pandas, PyArrow and PyYAML, run:

```bash
python scripts/run_openap_149_identity_recovery_v2.py \
  --catalogue config/openap_149_identity_sources_v2.yaml \
  --repository-sha "${GITHUB_SHA}" \
  --output-dir outputs/openap_149_identity_recovery_v2
```

Validate all invariants in a separate step, upload
`openap-149-identity-recovery-v2-results` for 30 days, and assert that the
inherited heavy `audit` job is skipped for this sentinel.

- [ ] **Step 5: Push and execute the real v2 audit**

```powershell
git add -- scripts/run_openap_149_identity_recovery_v2.py research/openap_149/identity_recovery_v2.py tests/test_openap_149_identity_recovery_v2.py .github/workflows/openap-proxy-real-correlation-audit.yml
git commit -m "feat: execute OpenAP identity recovery v2"
git push origin codex/openap-proxy44-validation
gh workflow run openap-proxy-real-correlation-audit.yml --ref codex/openap-proxy44-validation -f proxy_panel_url=IDENTITY_SOURCE_RECOVERY_V2
```

Expected: `validate` and `identity_source_recovery_v2` succeed; inherited
`audit` is skipped. The scientific decision is expected to be
`blocked_identity_v2`, not inferred from workflow colour.

### Task 4: Inspect the exact-head evidence and apply the gate

**Files:**
- Modify only if evidence supports it: `docs/OPENAP_149_IDENTITY_GATE_STATUS.md`

**Interfaces:**
- Consumes: GitHub run metadata and downloaded v2 artifact bundle.
- Produces: a source-hash-bound status document and either a pilot authorisation or a conclusive v2 no-go.

- [ ] **Step 1: Verify run identity before reading results**

Use non-interactive GitHub commands to require branch
`codex/openap-proxy44-validation`, event `workflow_dispatch`, exact current HEAD,
and successful `validate` plus `identity_source_recovery_v2` jobs. Reject stale
or superseded runs.

- [ ] **Step 2: Download outside `.artifacts/` and verify the bundle**

Use a new `New-TemporaryFile`/temporary directory path, download the named
artifact, compare GitHub's digest, recompute each file SHA-256, verify all JSON
and CSV reconciliations, and remove only the explicitly verified temporary
directory after the evidence has been recorded.

- [ ] **Step 3: Apply the strict decision**

If `identity_pass`, create a new frozen pilot plan before any signal
calculation. If `blocked_identity_v2`, do not launch any pilot, correlation or
score run. If evidence is incomplete or inconsistent, keep the phase open and
fix only the auditing defect without changing source criteria.

- [ ] **Step 4: Update the status document with exact evidence**

Record run ID/URL, SHA, job conclusions, artifact ID/digest, route class counts,
all route terminal reasons, bridge rows, coverage, ambiguities, pilot flag,
strict approvals, locked status and target-derived status. State explicitly
that workflow success proves execution, not identity success.

- [ ] **Step 5: Commit, push and verify final HEAD**

```powershell
git add -- docs/OPENAP_149_IDENTITY_GATE_STATUS.md
git commit -m "docs: record OpenAP identity recovery v2 decision"
git push origin codex/openap-proxy44-validation
```

Wait for all automatic exact-HEAD checks, verify `git diff --check`, confirm
only `.artifacts/` remains untracked, and ensure local HEAD equals the remote
branch before claiming completion.

