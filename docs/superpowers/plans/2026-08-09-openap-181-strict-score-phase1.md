# OpenAP 181 Strict Score Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` inline. Subagents and forks are prohibited by project policy.

**Goal:** Add a fail-closed 181-signal implementation registry and validate a predeclared first SEC accounting batch (`Cash`, `GP`, `Investment`) without promoting any signal that lacks complete evidence.

**Architecture:** A new `implementation_status` module owns the 181-row gate contract, the strict score inventory, and the implementation report. The existing completion workflow produces baseline outputs with all 181 pending; a separate SEC batch workflow can later attach measured evidence. Promotion is a pure validation operation: every mandatory boolean gate and every evidence reference must be present before a signal can join the 31-signal strict inventory.

**Tech Stack:** Python 3.12, pandas, pytest, GitHub Actions, existing OpenAP completion/source-research modules.

## Global Constraints

- Authoritative worktree: `C:\Users\HP\AURORA-openap-proxy44`.
- Authoritative branch: `codex/openap-proxy44-validation`.
- Do not modify `C:\Users\HP\AURORA`.
- Do not use subagents or forks.
- All test, data, coverage, and validation executions run in GitHub Actions.
- Never access `OOS_LOCKED` or `FORWARD` data.
- Validation cannot select formulas, parameters, mappings, or candidates.
- Only free, permanently available, automation-authorized sources may provide implementation inputs.
- Commercial sources remain comparison references and never enter `best_free_source_option` or the production pipeline.
- A signal is score eligible only after formula, data, point-in-time, identity, coverage, fidelity, and evidence gates all pass.

---

### Task 1: Establish the 181-row fail-closed contract with RED tests

**Files:**
- Modify: `tests/test_openap_181_completion.py`

**Interfaces:**
- Consumes: `build_completion_manifest`, `build_signal_resolution`, `CURRENT_EXACT_31`.
- Produces: executable expectations for `build_signal_implementation_status`, `build_strict_score_inventory`, and `write_implementation_outputs`.

- [ ] **Step 1: Write a failing test for the default 181-row registry**

  Assert exactly 181 unique signals, the required output columns, all `score_eligible == False`, and concrete non-empty blockers.

- [ ] **Step 2: Write a failing test for promotion gates**

  Supply one evidence row with one missing mandatory gate and assert it cannot be promoted. Supply a complete evidence row with run URL, artifact, and commit and assert it is eligible.

- [ ] **Step 3: Write a failing test for the strict inventory**

  Assert that the default inventory contains exactly the literal 31 `CURRENT_EXACT_31` signals and that only a fully eligible new signal can extend it to 32.

- [ ] **Step 4: Push the tests and verify RED remotely**

  Run through `OpenAP 181 Completion Audit` on the exact pushed SHA. Expected failure: import error for the not-yet-created implementation-status interface.

### Task 2: Implement the status registry and strict inventory

**Files:**
- Create: `research/openap_181/implementation_status.py`
- Modify: `research/openap_181/__init__.py`

**Interfaces:**
- Consumes: 181-row manifest, 181-row resolution, optional measured evidence table.
- Produces:
  - `build_signal_implementation_status(manifest, resolution, evidence=None) -> pd.DataFrame`
  - `build_strict_score_inventory(status) -> pd.DataFrame`
  - `render_implementation_validation_report(status, strict_inventory) -> str`
  - `write_implementation_outputs(manifest, resolution, output_dir, evidence=None) -> dict[str, Any]`

- [ ] **Step 1: Define literal schema and allowed gate results**

  Required status columns are exactly those named by the user specification. Required strict results are `approved`, `blocked`, and `not_attempted`.

- [ ] **Step 2: Validate source frames before merging**

  Reject duplicate signals, non-181 universes, missing blockers, evidence for unknown signals, non-HTTPS evidence URLs, empty artifacts, and malformed 40-character implementation commits.

- [ ] **Step 3: Enforce the promotion conjunction**

  `score_eligible` is true only when formula, pipeline, PIT, identity, coverage, and fidelity booleans are all true, both result fields are explicit passes, strict result is `approved`, and run/artifact/commit evidence is complete.

- [ ] **Step 4: Build the strict inventory from code-owned exact signals**

  Start with exactly `CURRENT_EXACT_31`; append only eligible new signals. Emit `signal`, `eligibility_basis`, `implementation_commit`, `evidence_run_url`, and `evidence_artifact`.

- [ ] **Step 5: Push minimal implementation and verify GREEN remotely**

  Expected: focused tests pass without changing any current score membership.

### Task 3: Generate the three mandatory implementation artifacts

**Files:**
- Create: `scripts/run_openap_181_implementation_status.py`
- Modify: `.github/workflows/openap-181-completion-audit.yml`
- Modify: `tests/test_openap_181_completion.py`

**Interfaces:**
- Consumes: generated manifest and resolution CSV files; optional measured evidence CSV.
- Produces:
  - `signal_implementation_status_181.csv`
  - `strict_score_signal_inventory.csv`
  - `IMPLEMENTATION_VALIDATION_REPORT.md`

- [ ] **Step 1: Write RED writer and local-execution-guard tests**

  The writer must create all three non-empty files. The CLI must call `require_github_actions_or_explicit_local_permission` and fail closed outside GitHub.

- [ ] **Step 2: Implement the guarded CLI and workflow step**

  Generate baseline outputs after source research. No evidence input means 181 blocked rows and a 31-row strict inventory.

- [ ] **Step 3: Strengthen workflow invariants**

  Assert 181 unique status rows, 31 strict signals at baseline, no score-eligible pending signals, no commercial source promotion, and all mandatory files non-empty.

- [ ] **Step 4: Push and inspect the uploaded artifact**

  Download the exact run artifact and independently inspect counts, schemas, blockers, and strict inventory membership.

### Task 4: Freeze the first SEC accounting batch before observing fidelity

**Files:**
- Create: `research/openap_181/sec_accounting_batch.py`
- Create: `tests/test_openap_181_sec_accounting_batch.py`
- Create: `scripts/run_openap_181_sec_accounting_batch.py`

**Interfaces:**
- Consumes: official SEC FSD `SUB`, `TAG`, `NUM`, and `PRE` tables; original filing acceptance dates; pinned OpenAP formulas; a predeclared identity input.
- Produces: causal monthly observations and gate evidence for exactly `Cash`, `GP`, and `Investment`.

- [ ] **Step 1: Write RED formula-fixture tests with hand-derived values**

  Use literal as-filed fixtures for cash/assets, gross profit/assets, and annual asset growth. Include amendments, taxonomy aliases, missing denominators, duplicate facts, and observations unavailable at formation time.

- [ ] **Step 2: Implement deterministic SEC fact selection**

  Select facts by accession, accepted timestamp, period, form, unit, taxonomy, and statement presentation. Preserve original and amended submissions and never backfill a later amendment into an earlier formation date.

- [ ] **Step 3: Implement exact formulas and monthly formation rules**

  Keep the batch predeclared. Do not add or remove signals after validation results are visible.

- [ ] **Step 4: Emit evidence without promotion by default**

  Formula and pipeline gates may pass from deterministic tests; PIT, identity, coverage, and fidelity remain false until measured in GitHub.

### Task 5: Measure SEC coverage and OpenAP fidelity in GitHub

**Files:**
- Create: `.github/workflows/openap-181-sec-accounting-batch.yml`
- Modify: `research/openap_181/sec_accounting_batch.py`
- Modify: `tests/test_openap_181_sec_accounting_batch.py`

**Interfaces:**
- Consumes: SEC quarterly FSD archives, pinned OpenAP stock-level reference, frozen identity bridge, predeclared thresholds.
- Produces: `sec_accounting_batch_evidence.csv`, coverage detail, fidelity detail, hashes, run URL, artifact name, and implementation SHA.

- [ ] **Step 1: Freeze thresholds in code before the data run**

  Require a minimum paired sample, cross-sectional coverage, Spearman correlation, sign agreement, and extreme-decile agreement. The workflow must print the frozen thresholds before downloading validation data.

- [ ] **Step 2: Download only official/free inputs with bounded access**

  Use SEC fair-access headers and retries. Record URL, size, SHA-256, retrieval time, archive quarter, and failure reason.

- [ ] **Step 3: Measure coverage and fidelity without candidate selection**

  Evaluate all three predeclared signals. Never alter formulas, aliases, thresholds, or the batch based on validation outcomes.

- [ ] **Step 4: Feed evidence into the 181 status writer**

  Promote only rows satisfying the complete conjunction. Failed rows retain measured results and concrete blockers.

### Task 6: Integrate proven signals into the score and close Phase 1

**Files:**
- Modify only if at least one signal passes: the canonical strict-score membership module used by `research/openap_93/current_pipeline.py`.
- Modify: `tests/test_openap_181_completion.py`
- Modify: `IMPLEMENTATION_VALIDATION_REPORT.md` through the writer.

**Interfaces:**
- Consumes: verified evidence from Task 5.
- Produces: score membership matching `strict_score_signal_inventory.csv` exactly.

- [ ] **Step 1: Write RED integration test for every passing signal**

  Assert that a passing signal is included and a failed signal remains unavailable. If no signal passes, assert membership remains exactly 31.

- [ ] **Step 2: Make the minimal score membership change**

  Do not change weighting, OOS protection, validation thresholds, or unrelated pipelines.

- [ ] **Step 3: Run focused tests, lint, and completion audit in GitHub**

  Require exact-SHA green runs and inspect the uploaded artifacts rather than relying only on check status.

- [ ] **Step 4: Commit, push, and verify clean synchronization**

  Record commit SHA, workflow URLs, artifact IDs, final strict inventory count, and all remaining blockers.
