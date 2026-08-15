# OpenAP 149: autonomous free reconstruction and Aurora provisional score

Date: 2026-08-15

## 1. Decision

Aurora will reconstruct and classify all 149 target signals without making the
calculation campaign depend on a PERMNO bridge. PERMNO remains necessary only
for independent stock-by-stock comparison with the official OpenAP panel.

The program will produce an explicitly named **Aurora provisional score**. It
must not be represented as an OpenAP score or as having 0.90 stock-level
fidelity. It may include only signals that pass the independent formula,
source, point-in-time, coverage and cross-sectional quality gates defined here.

The user's instruction to execute the entire program autonomously is treated as
approval of this recommended design. No subagents or forks are authorised.

## 2. Verified starting point

The authoritative worktree is `C:\Users\HP\AURORA-openap-proxy44` on branch
`codex/openap-proxy44-validation`. The dirty primary checkout
`C:\Users\HP\AURORA` and the pre-existing untracked `.artifacts/` directory are
outside scope and remain untouched.

The current 149-row acquisition ledger reports:

- 120 signals with some acquired data;
- 115 signals with a current numeric value;
- 82 reconstructed values and 33 unvalidated proxies;
- 34 signals without a current value;
- 0 signals eligible for the strict OpenAP score.

The 34 unresolved rows comprise 21 source failures, 10 fidelity failures and 3
coverage failures. The existing coverage denominator is the broad acquisition
universe and is not automatically the source-eligible universe required by an
individual signal.

## 3. Approaches considered

### A. Use the existing 115 values immediately

This is fastest but would mix reconstruction quality, sparse values and
unvalidated proxies. It is rejected as the default because a numeric value is
not evidence of faithful construction.

### B. Rebuild all 149 in one monolithic run

This maximises apparent throughput but makes formula drift, source substitution
and partial failures difficult to isolate. It is rejected.

### C. Frozen registry and controlled family waves

This is the selected approach. Every target receives a formula and source
contract first. Existing evidence is reused only through hash-bound artifacts.
Signals are then reconstructed in source-family waves and admitted to the
provisional score only after the common quality gate passes.

## 4. Source policy

Sources must be public, zero-cost for this use and authorised for internal
research. Public access is not enough if the data depends on an unlicensed
upstream product.

Priority order:

1. official public APIs or bulk files;
2. official public HTML or filing documents;
3. public academic data with affirmative terms and traceable upstream inputs;
4. already preserved private derived artifacts whose terms permit internal use;
5. a documented terminal block.

The primary routes are:

- SEC submissions, Company Facts, Financial Statement Data Sets and Financial
  Statement and Notes Data Sets for accounting, events and filing metadata;
- preserved historical market artifacts for prices, volume and corporate
  actions;
- Kenneth French's public factor library for factor-dependent calculations;
- FINRA short-interest downloads/API for the available rolling history;
- USPTO PatentsView public bulk tables for patent records;
- BEA input-output tables for industry relationship signals;
- OpenAP's pinned repository for formulas, signs and portfolio rules only.

Official documentation confirms that SEC APIs need no key, bulk data are
available, and automated access must use a declared agent and remain below the
fair-access ceiling. FINRA publishes short interest twice monthly with public
downloads and an API. PatentsView publishes bulk research tables under CC BY
4.0. BEA publishes current and historical input-output accounts. Kenneth French
publishes daily and monthly factors and portfolios. OpenAP's repository exposes
formula code and portfolio construction, while many original inputs still
depend on WRDS.

## 5. Scraping contract

The collector uses an API or bulk file before HTML. HTML scraping is allowed
only when the page is public, its automated-access rules permit it, and no
equivalent structured route exists.

Every route declares:

- source ID, evidence URL, retrieval URL and media type;
- licence/terms evidence and upstream provenance;
- request limit, timeout, retry policy and user agent;
- expected schema and parser version;
- release/effective/filing/retrieval timestamps;
- content length and SHA-256;
- checkpoint and deterministic deduplication key.

The collector must respect `robots.txt` where applicable, never bypass login,
CAPTCHA, paywalls or rate limits, never use visible browser tabs, and stop
before any paid request. Source outages preserve the last verified snapshot but
cannot silently convert stale evidence into current evidence.

## 6. Canonical 149-row registry

The registry contains exactly one row per target and is the control plane for
the campaign. Required fields include:

- signal, category, OpenAP code URL and pinned SHA-256;
- exact formula inputs, units, lookback and orientation;
- source route and source-eligible universe definition;
- point-in-time rule and maximum staleness;
- minimum observations and sparse-signal applicability rule;
- implementation and test IDs;
- calculation class and score-admission state;
- exact terminal blocker when a free reconstruction is impossible.

Every row ends in exactly one calculation class:

- `formula_exacta`: implemented formula and input semantics match the pinned
  OpenAP contract using independent source data;
- `aproximacion_solida`: economically close, point-in-time and useful, but at
  least one input or semantic differs and is declared;
- `bloqueada_gratis`: a required source, history, identity or semantic cannot be
  recovered publicly and lawfully at zero cost.

These classes do not assert stock-level similarity with OpenAP.

## 7. Reconstruction waves

### Wave 0: reconcile and admit existing evidence

Re-read the hash-bound 149 artifact and the pre-existing exact-signal inventory.
No old `exact`, `proxy` or `reconstructed` label is accepted without mapping it
to the new contract. Recalculate the applicable universe and quality evidence.

### Wave 1: market and standard accounting

Run the reusable price, volume, SEC face-statement and factor pipelines. This
wave includes the easiest unresolved historical-price and accounting formulas,
including factor residuals, return skew, valuation components and multi-year
accounting histories where point-in-time shares can be recovered.

### Wave 2: filings, notes and public specialist data

Run filing-event, SEC notes, FINRA, PatentsView and BEA collectors. Custom XBRL
tags are accepted only through explicit semantic mappings and filing evidence;
missing values are never replaced with zero merely to increase coverage.

### Wave 3: terminal specialist audit

Audit governance, analyst, options, credit-rating, customer/supplier and other
historically proprietary families. If a complete public route is absent, retain
a precise `bloqueada_gratis` result rather than a weak web substitute.

## 8. Point-in-time rules

A value can use only information publicly available at formation time.

- SEC values use filing acceptance time, not fiscal period end.
- Amendments and restatements preserve version history.
- Events use publication/effective timestamps required by the formula.
- Market data stop at the last completed session before formation.
- Factor and macro releases use their public availability dates.
- Historical ticker or issuer changes cannot be backfilled from a current
  snapshot without a dated source.

The panel retains `security_id`, ticker, CIK where known, formation time,
period end, available time, retrieved time, source ID, source hash, formula hash,
value, class and caveat.

## 9. Quality and score-admission gate

The provisional score uses a stricter subset than the set of calculated rows.
A signal is admitted only when:

1. its formula hash and implementation are frozen;
2. all required inputs come from allowed sources;
3. point-in-time and staleness checks pass;
4. the source-eligible universe denominator is explicit;
5. broad signals have at least 500 valid securities and at least 70 percent of
   their applicable universe;
6. sparse/event signals pass a formula-specific applicability and variation
   rule instead of the broad-signal count;
7. values are finite, non-degenerate and survive unit/schema checks;
8. no OpenAP stock-level value was used to select formula, source or parameter;
9. the signal is `formula_exacta`, or the provisional policy explicitly admits
   a separately reported `aproximacion_solida` with reduced influence.

The first published score has two layers:

- `aurora_formula_exact_score`, using only admitted `formula_exacta` signals;
- `aurora_extended_provisional_score`, adding admitted solid approximations at
  a capped weight and reporting their contribution separately.

Both apply OpenAP orientation, percentile ranking, redundancy-group caps and
economic-family caps. Missing values lower confidence and contribute the frozen
neutral policy; they do not change the metric basket per company.

## 10. Behaviour validation without PERMNO

Aurora will construct historical long-short portfolios from its independently
calculated values using the pinned OpenAP sign, quantile, filtering, weighting
and holding-period rules. Their monthly returns are compared with official
OpenAP portfolio returns.

This diagnostic reports Pearson and Spearman correlation, sign agreement,
overlap months, tracking error and period coverage. A monthly-return Spearman
of at least 0.90 may be labelled `high_portfolio_behaviour_similarity` only when
the frozen minimum history and coverage pass. It never becomes a claim of 0.90
stock-level fidelity and never changes a formula after viewing the benchmark.

PERMNO-based stock-level validation remains a separate blocked gate.

## 11. Artifacts

The campaign produces at least:

```text
openap_149_reconstruction_registry.csv
openap_149_source_route_audit.csv
openap_149_source_snapshot_manifest.json
openap_149_point_in_time_input_audit.parquet
openap_149_independent_values.parquet
openap_149_calculation_decisions.csv
openap_149_score_admission.csv
openap_149_portfolio_behaviour.csv
openap_149_portfolio_behaviour_summary.json
aurora_formula_exact_score.parquet
aurora_extended_provisional_score.parquet
aurora_provisional_score_audit.json
openap_149_autonomous_reconstruction_summary.md
```

Counts reconcile to 149. Empty outputs require a machine-readable reason.
Every artifact records repository revision, policy hash and source hashes.

## 12. Error handling

- HTTP 403/429: bounded retry or the already approved source-specific fallback;
  otherwise block the route.
- Login, CAPTCHA or payment: stop before interaction and classify the route.
- Schema/unit drift: quarantine the source version.
- Formula ambiguity: retain candidates, do not choose by OpenAP performance.
- Insufficient coverage: exclude the signal from score admission.
- Hash mismatch: invalidate the bundle.
- Partial family failure: preserve successful independent signals and emit
  exact failed rows; do not fail the 149-row reconciliation.

## 13. Execution and tests

Local work is limited to reading, editing and non-destructive Git operations.
Tests, downloads, calculations, merges and validation execute in GitHub Actions.
OOS and forward tiers remain closed.

The test layers are:

1. 149-row and unique-name reconciliation;
2. formula/source contract schemas and hashes;
3. source-response, rate-limit, redirect and licence fixtures;
4. point-in-time, amendments and no-look-ahead fixtures;
5. known hand calculations by formula family;
6. coverage-denominator and sparse-applicability fixtures;
7. score admission, redundancy, family caps and missingness;
8. synthetic portfolio-behaviour validation;
9. GitHub artifact, hash and count reconciliation;
10. exact-head lint and focused regression checks.

## 14. Completion criteria

The objective is complete when:

- all 149 signals have a frozen formula/source contract and one final class;
- every available free route has been executed or has an evidence-backed block;
- all calculated rows pass point-in-time and provenance checks;
- the formula-exact and extended provisional scores are produced or have an
  exact machine-readable no-score reason;
- portfolio-behaviour results are reported without stock-level overclaim;
- strict OpenAP equivalence remains zero unless independent PERMNO validation
  later passes;
- GitHub artifacts, hashes, counts, tests and documentation reconcile;
- the main checkout and `.artifacts/` remain untouched.

## 15. Primary source references

- SEC EDGAR APIs and bulk files:
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC developer resources and fair-access guidance:
  https://www.sec.gov/about/developer-resources
- SEC Financial Statement Data Sets:
  https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets
- OpenAP formula and portfolio repository:
  https://github.com/OpenSourceAP/CrossSection
- FINRA equity short-interest data:
  https://www.finra.org/finra-data/browse-catalog/equity-short-interest
- FINRA developer documentation:
  https://developer.finra.org/docs
- PatentsView bulk research data:
  https://patentsview.org/download/data-download-tables
- BEA input-output accounts:
  https://www.bea.gov/data/industries/input-output-accounts-data
- Kenneth French Data Library:
  https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
