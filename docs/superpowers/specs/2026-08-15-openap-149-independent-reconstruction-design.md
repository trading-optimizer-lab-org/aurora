# OpenAP 149 Independent Free Reconstruction

Date: 2026-08-15

Status: user-approved design, pending written-spec review

## 1. Purpose

Aurora will independently reconstruct the 149 targeted Open Asset Pricing
signals from zero-cost raw sources. The official OpenAP stock-level panel may be
used only after the independent outputs are frozen, and only to evaluate
historical fidelity. Official values must never be read by production
calculation code or used to calculate, correct, fit, tune, or select a proxy.

The target is not merely to produce a number for every signal. A signal may
enter the current stock score only when it demonstrates stock-level monthly
out-of-sample Spearman correlation of at least 0.90 against OpenAP, together
with sufficient coverage, point-in-time correctness, reliable identity, and
the other gates defined below.

## 2. Scope

The program covers all 149 targeted signals:

| Family | Count |
|---|---:|
| Accounting | 87 |
| Price | 27 |
| Trading | 9 |
| Event | 8 |
| 13F | 7 |
| Other | 11 |
| **Total** | **149** |

Every signal receives:

- a versioned formula contract;
- a zero-cost source route or a documented source block;
- point-in-time input rules;
- an independently calculated monthly output or a deterministic failure state;
- historical validation evidence when identity and reference coverage permit;
- a final status explaining whether the signal may enter the score.

The work is divided into independently reviewable subprojects: data and
identity foundation, market and trading signals, accounting signals, event and
13F signals, special-source signals, and final validation and score integration.
Each subproject requires its own implementation plan and acceptance evidence.

## 3. Non-goals

- Copying, mirroring, interpolating, or carrying forward official OpenAP values.
- Anchoring current estimates to the last official OpenAP percentile.
- Training a machine-learning model to imitate the OpenAP panel.
- Calling a signal reliable because it has the same name or a similar formula.
- Treating a calculated proxy as equivalent before independent validation.
- Filling unavailable observations with zero.
- Weakening the 0.90 threshold by averaging good and bad months.
- Purchasing Compustat, CRSP, IBES, OptionMetrics, LSEG, or another paid feed.
- Unlocking protected OOS or forward data.
- Running heavy research locally.

## 4. Fixed decisions

| Decision | Value |
|---|---|
| Reconstruction method | Independent calculation from raw free sources |
| Cost | Exactly zero; free accounts and API keys are allowed |
| OpenAP role | Post-freeze historical examination only |
| Current calculation dependency on OpenAP values | Prohibited |
| Primary fidelity gate | Monthly stock-level Spearman >= 0.90 |
| Validation periods | 2023 first examination, 2024 final examination |
| Formula changes after viewing OpenAP | Prohibited for the same examination |
| Missing values | Remain missing; never converted to zero |
| Ambiguous security identity | Excluded and reported |
| Heavy execution | GitHub Actions only, after explicit launch authorization |
| Local work | Inspection, editing, searching, and non-destructive git only |
| Subagents and forks | Prohibited |
| Dirty primary checkout | Read-only; all changes use the authoritative worktree |

Free service credentials must be supplied through GitHub secrets or another
approved secret store. They must never enter commits, artifacts, logs, cache
keys, command lines, or reports.

## 5. Architecture

The pipeline has seven isolated stages:

1. **Immutable raw source archive** records each source object, retrieval time,
   published-at time, license or access basis, and SHA-256 digest.
2. **Security identity timeline** resolves issuer and share-class identity,
   ticker changes, exchange changes, splits, mergers, delistings, and other
   corporate actions.
3. **Formula registry** defines each of the 149 calculations and all temporal,
   universe, unit, sign, and missing-data rules.
4. **Family calculators** transform only independent source data into one value
   per security and formation month.
5. **Freeze boundary** hashes formulas, source snapshots, identity maps, code,
   dependencies, and calculated results before reference values are exposed.
6. **Isolated OpenAP evaluator** joins frozen outputs to official historical
   values and computes the declared metrics. Production calculators cannot
   import or read this component's reference datasets.
7. **Score admission gate** exposes only signals that pass every mandatory
   criterion. All other signals retain explicit failure states.

The intended data flow is:

```text
free raw sources
  -> immutable snapshots
  -> point-in-time normalization
  -> historical security identity
  -> frozen formulas
  -> monthly independent signals
  -> frozen candidate artifact
  -> isolated OpenAP comparison
  -> approved / rejected / pending / blocked / not_evaluable
  -> score input (approved only)
```

## 6. Source policy

The primary zero-cost source stack is:

| Need | Primary source | Secondary or audit source |
|---|---|---|
| Financial statements and filing dates | SEC EDGAR APIs, Company Facts, filing facts and notes | SEC filing documents |
| Prices, returns, volume, trades and quotes | Alpaca historical market data | Tiingo free tier where its limits permit |
| Splits, dividends and corporate actions | Alpaca corporate actions and issuer filings | SEC filings |
| Earnings and corporate events | SEC 8-K and related filings | Issuer filings and corporate-action records |
| Institutional holdings | SEC structured Form 13F datasets | Original 13F filings |
| Short interest | FINRA equity short-interest data | Exchange or issuer evidence when freely available |
| Market factors | Kenneth French Data Library | Independently derived market series when required |
| Patent data | USPTO PatentsView | USPTO bulk research datasets |
| Public identifiers | SEC ticker and exchange files, OpenFIGI, corporate actions | Issuer and exchange records |

No secondary source may silently replace a failed primary source. The output
must identify which route supplied every field. If a free tier changes, loses
history, becomes chargeable, or prohibits the intended use, the affected route
blocks until an approved zero-cost replacement is validated.

## 7. Raw observation and signal contracts

Every normalized raw observation must carry at least:

- canonical issuer and security identifiers;
- source identifiers and ticker where available;
- observation start and end dates;
- publication or acceptance timestamp;
- retrieval timestamp;
- original and normalized units and currency;
- source URL or source-object identity;
- source and schema versions;
- restatement or revision identity;
- original-object SHA-256 digest;
- point-in-time eligibility flag and reason.

Every calculated signal row must carry at least:

- `signal_name` and formula version;
- canonical security identifier;
- formation month and exact available-at cutoff;
- raw calculated value and cross-sectional percentile;
- input snapshot, identity-map, code, dependency, and policy hashes;
- required and observed input counts;
- coverage and quality flags;
- calculation state and deterministic reason code;
- validation eligibility without any official result value.

## 8. Formula registry

Each signal contract freezes:

- the published definition and citation;
- source family and required raw fields;
- numerator, denominator, transformations, winsorization, and scaling;
- lookback and holding periods;
- accounting availability lag and event timing;
- price and share adjustment policy;
- security universe and exclusions;
- required minimum history;
- sign and score orientation;
- treatment of missing, zero, negative, and non-finite inputs;
- sparse-event rules where applicable;
- expected unit and output invariants;
- formula-text and executable-implementation hashes.

SEC tag alternatives must be selected from accounting meaning and filing
structure, never by choosing the tag that correlates best with OpenAP. As-filed
facts are evaluated using their SEC acceptance timestamps. Later restatements
must not rewrite what was knowable at an earlier formation date.

Market adjustments are reconstructed from raw prices and corporate actions
under a versioned policy. A vendor-adjusted series may be retained for auditing
but cannot silently determine the canonical result.

## 9. Identity contract and central blocker

Production uses a canonical issuer key and a distinct canonical security key.
The timeline must preserve multiple share classes and must not assume that one
ticker permanently identifies one company or security.

The OpenAP reference is keyed by PERMNO. No complete, authoritative, free
historical PERMNO crosswalk has yet been demonstrated. Therefore the identity
foundation must first seek a non-circular public identifier chain supported by
historical source evidence. Direct identifier evidence has priority over names,
tickers, or statistical resemblance.

An identity link may enter strict validation only when it is:

- historically valid for the evaluated month;
- specific to the security or share class, not merely the issuer;
- supported by independent public evidence;
- one-to-one for the relevant interval;
- frozen before target signal values are compared.

The target signal itself, or another official OpenAP characteristic, must not be
used to choose the identity that maximizes its measured correlation. Ambiguous
links are excluded. If a sufficiently complete non-circular bridge cannot be
built, independent values may still be calculated for production identifiers,
but strict OpenAP correlation remains `blocked_identity` and must not be
claimed.

## 10. Calculation by family

### 10.1 Accounting

The 87 accounting signals use point-in-time SEC financial statements and notes.
The calculator resolves taxonomy changes, custom tags, statement context,
duration versus instant facts, fiscal calendars, currencies, amendments, and
restatements. Formula-specific availability lags are part of the frozen
contract.

### 10.2 Price and trading

The 27 price and 9 trading signals use historical bars, trades, quotes, volume,
corporate actions, and market factors as required. Calculations enforce trading
calendars, delistings, minimum observations, stale-price rules, and explicit
adjustment policy. A quote-dependent signal cannot fall back to bar-only data
without becoming a separately named candidate that still requires validation.

### 10.3 Events

The 8 event signals use documented publication and effective timestamps. They
are represented as events first and converted to formation-month values only by
the published signal rule. A monthly approximation is not an acceptable
substitute for an unknown event date.

### 10.4 Form 13F

The 7 institutional-position signals use original and structured SEC 13F data,
including filing and amendment dates. Holdings become available only when the
filing was public, not at the quarter end.

### 10.5 Other sources

The remaining 11 signals receive specific contracts for sources such as FINRA,
Kenneth French, USPTO, or another demonstrably free official source. Signals
whose original proprietary input has no defensible free equivalent may still
produce a clearly named candidate reconstruction, but cannot enter the score
without passing all validation gates.

## 11. First 40-signal wave

The first calculation wave is selected for expected coverage, economic
relevance, source reuse, and independent reconstructability. Selection does not
assert that any signal already passes the fidelity threshold.

**Market and trading (16):** Beta, BetaFP, High52, IdioVol3F, IdioVolAHT,
RealizedVol, ResidualMomentum, ReturnSkew3F, CoskewACX, Coskewness, Size,
PriceDelayRsq, PriceDelaySlope, PriceDelayTstat, VolMkt, and VolumeTrend.

**Accounting (20):** AM, BM, BookLeverage, Cash, CashProd, CF, cfp, EP, GP,
Investment, InvGrowth, Leverage, NOA, OperProf, PctTotAcc, RD, roaq, SP, tang,
and TotalAccruals.

**Event and positioning (4):** AnnouncementReturn, DivInit, DivOmit, and
ShortInterest.

After the foundation and first wave are accepted, the same source-family
engines expand to all remaining signals until all 149 have terminal evidence.

## 12. Freeze and independent examination

Before any official stock-level value is opened, the candidate bundle must
contain and hash:

- all formula contracts;
- source manifests and snapshots;
- historical identity map;
- universe and formation-month definitions;
- code and dependency lock;
- all independently calculated rows;
- expected validation joins and metrics;
- immutable run and policy identifiers.

The isolated evaluator then performs two sequential examinations:

1. all evaluable 2023 formation months;
2. all evaluable 2024 formation months, without changing formulas, sources,
   identities, parameters, or results after viewing 2023.

A bug proven without using OpenAP outcomes may invalidate the entire candidate
bundle, but the corrected version requires a genuinely untouched examination
period. It may not reuse an exposed period and still call it out-of-sample.

## 13. Validation gates

### 13.1 Continuous signals

Every evaluable month must satisfy all of the following:

- stock-level Spearman correlation of at least 0.90;
- at least 500 paired securities for broad-universe signals;
- at least 70 percent coverage of the applicable official non-missing universe;
- correct sign and orientation;
- at least 80 percent overlap in both the top and bottom deciles;
- no look-ahead or post-formation input;
- valid point-in-time security identity;
- frozen formula, source, and result provenance.

The reported evidence also includes Pearson correlation, paired counts,
coverage, missingness, decile agreement, distribution diagnostics, and monthly
minimum, median, and maximum. These supporting statistics never replace the
Spearman gate.

### 13.2 Sparse and binary signals

Months with no cross-sectional variation are reported as not evaluable rather
than converted into successful correlations. Evaluable months still require
Spearman of at least 0.90. Across the frozen examination period, sparse signals
also require:

- precision of at least 0.90;
- recall of at least 0.90;
- formula-specific event-date agreement;
- complete reporting of true positives, false positives, false negatives, and
  non-evaluable months.

### 13.3 No averaging escape

A high average does not compensate for a month below 0.90. A signal fails the
strict fidelity gate if any evaluable required month falls below the threshold.

## 14. Status model

Every signal ends in exactly one current status:

- `approved`: calculated and passed every mandatory gate;
- `rejected`: calculable and evaluable but failed at least one gate;
- `pending`: evidence is incomplete but a defined free route remains;
- `blocked`: a required zero-cost source, identity, or legal access route is
  unavailable;
- `not_evaluable`: OpenAP or the independent universe lacks enough comparable
  observations for the declared test.

These statuses are fail-closed. Only `approved` is score eligible. Reports must
distinguish source acquisition, numeric calculation, independent validation,
and score eligibility.

## 15. Score integration

The score consumes only approved percentiles and their declared orientation. It
must not:

- read OpenAP stock-level values;
- substitute a rejected or blocked proxy;
- convert missing signals to neutral or zero values without an independently
  approved missing-data policy;
- allow one economic family to dominate because it has many redundant signals.

Before production use, the combined score requires its own separately approved
frozen validation design. Its score-level gates may be stricter, but must never
weaken or replace any per-signal gate defined in this document.

## 16. Delivery phases

### Phase 1: data and identity foundation

- Freeze schemas, source policy, and all 149 formula manifests.
- Implement immutable snapshots and point-in-time normalization contracts.
- Build issuer and security timelines.
- Resolve or formally block the historical PERMNO bridge.
- Produce synthetic and small frozen fixtures without running heavy research.

### Phase 2: first 40 signals

- Implement the shared market, accounting, event, and short-interest engines.
- Produce independent current and historical candidate outputs.
- Run source-level and formula-level checks before any OpenAP comparison.

### Phase 3: expansion to all 149

- Complete all source-family calculators.
- Reconcile exactly 149 formula contracts and result states.
- Freeze the full independent candidate bundle.

### Phase 4: isolated 2023 and 2024 examination

- Join only through the accepted identity bridge.
- Produce monthly per-signal evidence and strict status decisions.
- Preserve exposed periods and prohibit retrospective retuning.

### Phase 5: score integration

- Admit approved signals only.
- Apply redundancy and economic-family controls.
- Produce current score, provenance, coverage, and strict limitations.

Because the program contains multiple independent subsystems, each phase gets a
focused implementation plan and acceptance review before the next phase starts.

## 17. Required artifacts

At minimum, the program produces:

```text
openap_149_formula_registry.csv
openap_149_source_routes.csv
raw_source_manifest.parquet
security_identity_timeline.parquet
openap_permno_bridge.parquet
openap_permno_bridge_audit.csv
point_in_time_input_audit.parquet
independent_signal_values.parquet
independent_signal_manifest.json
candidate_freeze_manifest.json
openap_2023_monthly_validation.parquet
openap_2024_monthly_validation.parquet
openap_149_strict_status.csv
openap_149_validation_summary.md
openap_current_approved_score.parquet
openap_current_approved_score_audit.json
openap_149_requirements_traceability.csv
```

An artifact may be intentionally empty only with a machine-readable reason and
matching terminal status. Every table records schema and provenance versions.

## 18. Error handling

- Source outage: bounded retries, preserve prior verified state, then
  `blocked_source` without substituting an undeclared provider.
- API limit: honor retry instructions and resume from immutable checkpoints.
- Paid-tier response or possible charge: stop before the request and report the
  route as blocked until a zero-cost path is approved.
- SEC tag ambiguity: retain candidates, fail the field selection, and require
  accounting evidence; never select by OpenAP correlation.
- Corporate-action conflict: quarantine the affected security-months.
- Ambiguous identity: exclude the link and report `blocked_identity`.
- Missing history: report missingness; never shorten the published lookback
  silently.
- Schema or unit drift: block the affected source version.
- Failed 2023 or 2024 fidelity gate: mark `rejected`; do not retune against the
  exposed period.
- Corrupt or mismatched artifact hash: invalidate the candidate bundle.

## 19. Testing and verification

Local work is limited by repository policy. Heavy downloads, reconstruction,
correlation, and full validation run only in GitHub Actions after explicit user
authorization to launch them.

The test layers are:

1. schema and formula-contract tests;
2. point-in-time and no-look-ahead tests;
3. SEC tag and filing-context fixtures;
4. corporate-action and security-identity fixtures;
5. known-formula hand calculations;
6. provider-response and rate-limit fixtures;
7. missing, zero, negative, non-finite, and sparse-event cases;
8. deterministic freeze and hash checks;
9. isolated evaluator tests using synthetic reference data;
10. GitHub source smoke, first-wave reconstruction, full reconstruction, and
    sequential 2023/2024 examination.

OpenAP reference files must not appear in calculator dependency graphs, test
fixtures for production formulas, or score runtime paths.

## 20. Operational boundaries

- Authoritative worktree: `C:\Users\HP\AURORA-openap-proxy44`.
- Authoritative branch at design time: `codex/openap-proxy44-validation`.
- The dirty primary checkout `C:\Users\HP\AURORA` remains untouched.
- No subagents or forks are used.
- No GitHub Actions run is launched merely by committing the design or plan.
- Heavy workflows use manual dispatch and require explicit user authorization.
- Existing protected OOS and forward tiers remain closed.

## 21. Completion criteria

The reconstruction program is complete only when:

- all 149 signals have frozen formula and source contracts;
- all 149 have an independently calculated result or a documented zero-cost
  block;
- every signal has exactly one evidence-backed terminal status;
- 2023 and 2024 monthly validation reports exist for every evaluable signal;
- no signal enters the score without passing every mandatory gate;
- current score rows retain complete formula, source, identity, code, policy,
  and snapshot provenance;
- expected, calculated, approved, rejected, pending, blocked, and not-evaluable
  counts reconcile exactly;
- the entire result can be reproduced from preserved raw source objects and the
  frozen repository revision;
- no claim of 90 percent fidelity is made where identity or independent
  correlation evidence is missing.

The objective does not require all 149 signals to pass. It requires all 149 to
be reconstructed or conclusively classified, and it requires the score to use
only the subset that independently demonstrates the requested fidelity.
