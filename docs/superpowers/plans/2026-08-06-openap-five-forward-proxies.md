# OpenAP Five Forward Proxies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Subagents are prohibited by repository policy unless the user explicitly requests them.

**Goal:** Calculate five current OpenAP-derived stock signals independently from public data and admit each one to Aurora's score only after it passes frozen 2011-2020 correlation gates against the official OpenAP portfolio.

**Architecture:** Existing OpenAP 93 source-specific pipelines remain responsible for signal calculations. A new validation module selects public-data formula variants on data ending in 2010, evaluates the frozen variant on 2011-2020, signs a hash-bound certificate, and applies that certificate to the current score. The GitHub-only workflow collects inputs, reconstructs candidates, validates them, calculates today's values, and publishes score-ready rows separately from failed signals.

**Tech Stack:** Python 3.11+, pandas, NumPy, DuckDB, PyArrow, pytest, GitHub Actions, YFinance public endpoints, SEC EDGAR bulk data, Kenneth French public factors.

## Global Constraints

- No local tests, smokes, backtests, mass downloads, or heavy merges.
- Every RED and GREEN verification runs in GitHub Actions.
- `locked_opened=false`; 2021+ returns are not read by selection or validation.
- `validation_used_for_selection=false`.
- A current snapshot may use data known at `as_of`, but no future return labels.
- Pearson >= 0.80, Spearman >= 0.80, sign agreement >= 0.75, and common validation months >= 60.
- Failed or stale certificates contribute zero score weight.
- No official-source mirror can satisfy independent reconstruction.
- Work inline in the current task; do not dispatch subagents.

---

### Task 1: Validation certificate contract

**Files:**
- Create: `research/openap_93/forward_proxy_validation.py`
- Create: `tests/test_openap_93_forward_proxy_validation.py`

**Interfaces:**
- Produces: `ForwardProxyGate`, `ForwardProxyCertificate`, `select_train_variant`, `validate_frozen_variant`, `certificate_sha256`, `apply_certificates`.
- Consumes: candidate monthly spread rows with `signal`, `variant_id`, `month`, `proxy_return`; official rows with `signal`, `month`, `official_return`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_validation_selects_on_train_and_measures_frozen_variant_only():
    selected = select_train_variant(candidates, official, train_end="2010-12-31")
    certificate = validate_frozen_variant(
        selected, candidates, official,
        validation_start="2011-01-01", validation_end="2020-12-31",
    )
    assert certificate.variant_id == "faithful"
    assert certificate.validation_used_for_selection is False

def test_failed_certificate_contributes_zero_score_weight():
    result = apply_certificates(current_rows, [failed_certificate])
    assert result["current_usable"].eq(False).all()
    assert result["effective_score_weight"].eq(0.0).all()

def test_certificate_hash_changes_when_formula_or_source_changes():
    assert certificate_sha256(base) != certificate_sha256(changed_formula)
```

- [ ] **Step 2: Push the test-only commit and verify RED in GitHub**

Run through branch CI. Expected failure: imports from
`aurora.research.openap_93.forward_proxy_validation` do not exist.

- [ ] **Step 3: Implement immutable gate and certificate records**

Use frozen dataclasses. `select_train_variant` ranks by minimum of Pearson and
Spearman, then sign agreement, then lower tracking error. It may inspect only
months through 2010. `validate_frozen_variant` computes metrics only for the
already selected `variant_id` and 2011-2020.

- [ ] **Step 4: Verify GREEN in GitHub and commit**

Expected: new validation tests pass and existing OpenAP tests remain green.

### Task 2: Source-faithful DivSeason

**Files:**
- Modify: `research/openap_93/event_pipeline.py`
- Modify: `tests/test_openap_93_max_free.py`

**Interfaces:**
- Produces: `infer_dividend_frequency(dividend_months) -> str` and current
  `DivSeason` rows with `variant_id`, `value`, and causal evidence.

- [ ] **Step 1: Write hand-calculated RED fixtures**

Cover quarterly lags `2/5/8/11`, semiannual lags `5/11`, annual lag `11`,
monthly-payer exclusion, unknown-frequency quarterly fallback, and no payer
history. The test must fail against the current single quarterly inference.

- [ ] **Step 2: Push and verify the expected RED failure in GitHub**

- [ ] **Step 3: Implement frequency inference and official lag sets**

Infer frequency only from completed payments known at formation. Preserve the
existing Yahoo special-dividend caveat and label formula variants explicitly.

- [ ] **Step 4: Push and verify GREEN in GitHub**

### Task 3: Earnings announcement evidence and two earnings signals

**Files:**
- Modify: `scripts/run_openap_yfinance_sec_current.py`
- Modify: `research/openap_93/quarterly_pipeline.py`
- Modify: `research/openap_93/current_pipeline.py`
- Modify: `tests/test_openap_yfinance_sec_current.py`
- Modify: `tests/test_openap_93_max_free.py`

**Interfaces:**
- Produces normalized `earnings_events` columns: `symbol`, `event_at`,
  `reported_eps`, `consensus_eps`, `source_id`, `source_priority`, `retrieved_at`.
- Produces source variants `sec_8k_item_202`, `yahoo_earnings_actual`, and
  diagnostic-only `periodic_filing_date`.

- [ ] **Step 1: Write RED tests for event-source precedence**

```python
def test_item_202_precedes_periodic_filing_date():
    chosen = choose_earnings_event(item_202, yahoo_event, ten_q)
    assert chosen.source_id == "sec_8k_item_202"

def test_announcement_return_uses_four_trading_sessions_minus2_plus1():
    assert announcement_return(fixture) == pytest.approx(0.04)

def test_earnings_streak_requires_two_same_sign_consensus_surprises():
    assert earnings_streak(two_positive_surprises).value == pytest.approx(0.02)
    assert earnings_streak(opposite_sign_surprises).value is None
```

- [ ] **Step 2: Push and verify RED in GitHub**

- [ ] **Step 3: Persist Yahoo earnings and SEC Item 2.02 events**

Use SEC submission items and acceptance timestamps; use Yahoo
`get_earnings_dates` rows only when reported and estimated EPS are both finite.
Preserve raw rows and hashes. Never infer a consensus estimate from SEC actuals.

- [ ] **Step 4: Calculate AnnouncementReturn and EarningsStreak**

Announcement excess return is the sum of stock return minus `Mkt-RF` minus `RF`
over four trading sessions. EarningsStreak uses prior-session close and remains
live for no more than six months.

- [ ] **Step 5: Push and verify GREEN in GitHub**

### Task 4: Point-in-time IndRetBig

**Files:**
- Modify: `research/openap_93/market_pipeline.py`
- Modify: `research/openap_93/historical_proxy_validation.py`
- Modify: `tests/test_openap_93_max_free.py`
- Modify: `tests/test_openap_93_five_proxy_validation.py`

**Interfaces:**
- Produces: monthly `IndRetBig` variants using PIT SIC, FF48, PIT shares,
  unadjusted close, relative industry rank, and arithmetic mean return.

- [ ] **Step 1: Write RED fixture with one industry and five firms**

Hand-derive ranks and assert that only firms strictly above the 70th percentile
form the big-firm mean, big firms receive missing values, and adjusted-close or
current-share contamination changes the expected result and is rejected.

- [ ] **Step 2: Push and verify RED in GitHub**

- [ ] **Step 3: Replace contaminated market equity inputs**

Join shares by SEC `available_at <= month_end`, use raw close, use the latest SIC
accepted by month-end, and calculate a simple mean exactly as OpenAP does.

- [ ] **Step 4: Push and verify GREEN in GitHub**

### Task 5: Exact DelNetFin component semantics

**Files:**
- Modify: `research/openap_93/accounting_pipeline.py`
- Modify: `research/openap_93/historical_proxy_validation.py`
- Create: `config/openap_93/delnetfin_sec_aliases.yaml`
- Modify: `tests/test_openap_93_max_free.py`
- Modify: `tests/test_openap_93_five_proxy_validation.py`

**Interfaces:**
- Produces deterministic component resolution with `resolved_tag`, `value`,
  `available_at`, and `missing_reason` for `ivst`, `ivao`, `dltt`, `dlc`, `pstk`,
  and `at`.

- [ ] **Step 1: Write RED tests for alias precedence and missingness**

Hand-calculate two annual observations. Assert exact 12-month matching, average
assets scaling, preferred-stock zero fallback, and missing output when any
other required component is unresolved.

- [ ] **Step 2: Push and verify RED in GitHub**

- [ ] **Step 3: Add audited alias table and resolver**

The alias table records Compustat target, SEC tags in precedence order, expected
balance, and sign. Do not fill investments or debt with zero.

- [ ] **Step 4: Push and verify GREEN in GitHub**

### Task 6: Historical candidate portfolios and frozen certification

**Files:**
- Modify: `research/openap_93/historical_proxy_validation.py`
- Modify: `research/openap_93/official_portfolio_similarity.py`
- Create: `scripts/certify_openap_five_forward_proxies.py`
- Modify: `tests/test_openap_93_five_proxy_validation.py`
- Modify: `tests/test_openap_93_official_portfolio_similarity.py`

**Interfaces:**
- Produces `forward_proxy_candidate_metrics.csv`,
  `forward_proxy_validation_metrics.csv`, and
  `forward_proxy_certificates.jsonl`.

- [ ] **Step 1: Write RED tests for chronological isolation**

Use fixtures where variant A wins train and variant B wins validation. Assert A
remains frozen. Add a 2021+ mutation and assert selection and validation outputs
remain byte-identical.

- [ ] **Step 2: Push and verify RED in GitHub**

- [ ] **Step 3: Build monthly decile spreads per variant**

Use next-month returns, official signal sign, a common eligible universe, and no
post-2020 observations. Calculate train and validation metrics separately.

- [ ] **Step 4: Emit hash-bound pass/fail certificates**

Include formula hash, source manifest hash, gate version, dates, correlations,
sign agreement, overlap, and all policy booleans.

- [ ] **Step 5: Push and verify GREEN in GitHub**

### Task 7: Current score integration

**Files:**
- Modify: `research/openap_93/current_pipeline.py`
- Modify: `research/openap_current_score.py`
- Modify: `scripts/run_openap_93_max_free.py`
- Modify: `tests/test_openap_93_max_free.py`
- Modify: `tests/test_openap_yfinance_sec_current.py`

**Interfaces:**
- Consumes: current values and frozen certificates.
- Produces: score-ready current rows with `certificate_sha256`,
  `effective_score_weight`, and a precise rejection reason.

- [ ] **Step 1: Write RED integration tests**

Assert passing certificates promote only matching signal/variant/source hashes;
failed, absent, stale, or mismatched certificates withhold the signal and set
weight to zero.

- [ ] **Step 2: Push and verify RED in GitHub**

- [ ] **Step 3: Integrate certificate application before score assembly**

Do not change the score formula for the other predictors. Add the five values as
signed cross-sectional percentiles only after certification.

- [ ] **Step 4: Push and verify GREEN in GitHub**

### Task 8: GitHub-only end-to-end workflow

**Files:**
- Create: `.github/workflows/openap-five-forward-proxies.yml`
- Modify: `tests/test_ci_workflows.py`

**Interfaces:**
- Produces artifact `openap-five-forward-proxies-results` with all files from the
  design specification.

- [ ] **Step 1: Write RED workflow contract test**

The behavior test loads the YAML, verifies reusable future-run contract use,
manual dispatch, job dependencies, no local bypass, exact historical date
boundaries, final artifact name, and fail-closed publication.

- [ ] **Step 2: Push and verify RED in GitHub**

- [ ] **Step 3: Implement workflow jobs**

Use existing OpenAP data artifacts where provenance matches; otherwise collect
fresh public inputs. Do not expose credentials or publish large raw archives.

- [ ] **Step 4: Push and verify GREEN in GitHub**

### Task 9: Real GitHub execution and completion audit

**Files:**
- No production source changes unless a failing real-data test is first added.

- [ ] **Step 1: Dispatch the workflow on the feature branch**

Run with current formation date and the full eligible US common-stock universe.

- [ ] **Step 2: Inspect every job and final artifact**

Confirm `partial=false`, policy booleans, hashes, current row counts, source
coverage, and per-signal validation metrics.

- [ ] **Step 3: Audit acceptance signal by signal**

For each signal, record whether all four gates pass. Do not average metrics
across signals. At least one independently calculated signal must be certified
for the objective to be complete.

- [ ] **Step 4: Run full branch CI and inspect exit status**

Require all mandatory checks to pass. Existing unrelated known failures must be
reported and must not mask OpenAP failures.

- [ ] **Step 5: Commit final audit, push branch, and create PR**

The PR description lists exact correlations and explicitly distinguishes
certified current signals from rejected ones.
