# OpenAP 149 Free Feasibility and Independent Reconstruction

Date: 2026-08-15

Status: approved for phased implementation

## 1. Purpose

Aurora will first determine whether the 149 targeted Open Asset Pricing signals
can be faithfully reconstructed from zero-cost raw sources. It will not build
all 149 merely because a formula can produce numeric values. Reconstruction
expands only after historical identity is independently solved and a frozen
10-signal pilot demonstrates that the free-source method can reproduce OpenAP
at the required fidelity.

The official OpenAP stock-level panel may be used only after independent
outputs are frozen, and only to evaluate historical fidelity. Official values
must never be read by production calculation code or used to calculate,
correct, fit, tune, select, or rescue a proxy.

The target is not merely to produce a number for every signal. A signal may
enter the current stock score only when it demonstrates stock-level monthly
out-of-sample Spearman correlation of at least 0.90 against OpenAP, together
with sufficient coverage, point-in-time correctness, reliable identity, and
the other gates defined below.

## 2. Scope

The feasibility register covers all 149 targeted signals:

| Family | Count |
|---|---:|
| Accounting | 87 |
| Price | 27 |
| Trading | 9 |
| Event | 8 |
| 13F | 7 |
| Other | 11 |
| **Total** | **149** |

Every signal eventually receives:

- a versioned formula contract;
- a zero-cost source route or a documented source block;
- point-in-time input rules;
- an independently calculated monthly output or a deterministic failure state;
- historical validation evidence when identity and reference coverage permit;
- a final status explaining whether the signal may enter the score.

The work is divided into strict go/no-go stages: identity feasibility, a
10-signal pilot, source-family expansion for methods that pass, and final score
integration. Failure of the identity gate stops strict OpenAP validation.
Failure of a pilot method stops expansion of that method or source family.

## 2.1 Evidence at the design freeze

The existing project evidence supports only the following claims:

| Current evidence class | Count | Meaning |
|---|---:|---|
| Strictly approved | 0 | No independent signal has demonstrated the agreed monthly stock-level Spearman threshold |
| Not ruled out, still unproved | 142 | No decisive source block is recorded, but source equivalence and fidelity are unknown and strict comparison is currently blocked by identity |
| No complete zero-cost replacement found | 6 | A required proprietary source has no complete authorised free counterpart currently demonstrated |
| Official comparison unavailable | 1 | `Size` is omitted from the downloadable OpenAP stock-level panel used for the agreed test |
| **Total** | **149** | These classes describe feasibility evidence, not score eligibility |

The six currently source-blocked signals are `Activism1`, `Activism2`,
`Mom6mJunk`, `CustomerMomentum`, `retConglomerate`, and `sinAlgo`. This is not a
claim of mathematical impossibility. It means that no complete, authorised,
zero-cost source replacement has been demonstrated for their required original
inputs.

The project's 115 previously calculated signals are non-strict research
proxies. They are not accepted inputs to the score and do not reduce the count
of signals that still require independent validation.

## 3. Non-goals

- Copying, mirroring, interpolating, or carrying forward official OpenAP values.
- Anchoring current estimates to the last official OpenAP percentile.
- Training a machine-learning model to imitate the OpenAP panel.
- Calling a signal reliable because it has the same name or a similar formula.
- Treating a calculated proxy as equivalent before independent validation.
- Implementing all 149 before the identity and pilot gates establish viability.
- Reporting the number of candidate calculations as the number of faithful signals.
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
| Current number proven to meet that gate | 0 |
| First implementation target | Identity gate, then frozen 10-signal pilot |
| Expansion rule | Only passing methods and source families may expand |
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

The pipeline has eight isolated stages:

1. **Feasibility register** classifies all 149 without equating a documented
   route with a faithful reconstruction.
2. **Immutable raw source archive** records each source object, retrieval time,
   published-at time, license or access basis, and SHA-256 digest.
3. **Security identity timeline** resolves issuer and share-class identity,
   ticker changes, exchange changes, splits, mergers, delistings, and other
   corporate actions.
4. **Formula registry** defines each calculation and all temporal,
   universe, unit, sign, and missing-data rules.
5. **Pilot and family calculators** transform only independent source data into one value
   per security and formation month.
6. **Freeze boundary** hashes formulas, source snapshots, identity maps, code,
   dependencies, and calculated results before reference values are exposed.
7. **Isolated OpenAP evaluator** joins frozen outputs to official historical
   values and computes the declared metrics. Production calculators cannot
   import or read this component's reference datasets.
8. **Score admission gate** exposes only signals that pass every mandatory
   criterion. All other signals retain explicit failure states.

The intended data flow is:

```text
149-signal feasibility register
  -> identity go/no-go gate
  -> free raw sources for the 10-signal pilot
  -> immutable snapshots
  -> point-in-time normalization
  -> historical security identity
  -> frozen pilot formulas
  -> monthly independent pilot signals
  -> frozen candidate artifact
  -> isolated OpenAP comparison
  -> method/source-family go/no-go decisions
  -> controlled expansion only for passing methods
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

These sources are candidate routes, not evidence that the corresponding OpenAP
inputs can be reproduced closely enough. SEC filings do not automatically
replace Compustat's normalisation and history; free market feeds do not
automatically replace CRSP; SEC 13F does not supply a PERMNO bridge; and public
segment, rating, customer, or governance disclosures may be incomplete.

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

This is the first implementation gate. Before any historical pilot calculation
is launched, the bridge must demonstrate, using identity evidence only:

- monthly security-level links to PERMNO for 2023 and 2024;
- one-to-one share-class resolution for every retained interval;
- at least 70 percent coverage of the applicable official comparison universe;
- explicit treatment of ticker changes, reused tickers, mergers, delistings,
  multiple share classes, and ambiguous links;
- a frozen bridge and audit artifact created before any target values are read.

If no authorised zero-cost route can satisfy these requirements, the program
records a no-go decision: zero signals are claimed as meeting the agreed OpenAP
fidelity test. Access to CRSP or WRDS supplied by the user or an institution may
remove this block at no marginal cost, but it is not classified as publicly
free and must not be assumed.

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

## 11. Feasibility-first 10-signal pilot

No 40-signal wave is authorised. After the identity gate passes, the first and
only calculation wave is a frozen 10-signal pilot chosen to test the two
largest, most reusable source families with comparatively direct formulas:

- **Market and trading:** `Beta`, `High52`, `RealizedVol`, `VolSD`, and
  `VolumeTrend`.
- **Accounting:** `Cash`, `BM`, `EP`, `GP`, and `TotalAccruals`.

Selection means only that these signals offer the best early test of whether
free market and SEC data can reproduce OpenAP. It does not imply that any is
currently accurate, score eligible, or expected to pass.

For each pilot signal, work stops at the first failed gate:

1. the exact OpenAP formula and original input semantics are documented;
2. the free source proves adequate historical fields, timestamps, units, and
   coverage without substituting a merely related concept;
3. the formula and identity bridge are frozen before reference values are read;
4. the 2023 examination is run once and classified without target-driven
   changes;
5. only a 2023 pass proceeds unchanged to the 2024 final examination;
6. only a 2024 pass becomes `approved` and score eligible.

A failed signal is reported as `rejected` or `blocked`; it is not adjusted to
look more like OpenAP after viewing the result. Implementation patterns and
source routes may expand to related signals only when their pilot evidence
passes all mandatory gates. If the supposedly direct pilot signals fail, the
corresponding family does not expand to dozens of weaker proxies.

The remaining 139 signals stay in the feasibility register until a passing
pilot establishes a reusable route. The six known source-blocked signals remain
blocked unless new authoritative zero-cost evidence changes their source
classification. `Size` remains `not_evaluable` under this specific OpenAP
comparison unless an official stock-level reference is made available.

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

## 16. Delivery phases and stop conditions

### Phase 0: reconcile feasibility evidence

- Freeze the 149-signal register and the evidence behind the 142/6/1 split.
- Record exact original inputs, proposed free substitutes, historical coverage,
  licensing basis, and unresolved equivalence risks.
- Do not count a documented route or numeric proxy as a fidelity success.

### Phase 1: identity go/no-go

- Build and audit the issuer, security, and PERMNO timelines using identity
  evidence only.
- Produce the frozen bridge before exposing target signal values.
- **Stop condition:** if the bridge cannot meet the coverage and ambiguity
  rules in section 9 at zero cost, mark strict validation `blocked_identity` and
  do not implement the 149-signal reconstruction campaign.

### Phase 2: frozen 10-signal pilot

- Implement only the five market/trading and five accounting signals in
  section 11.
- Run source and formula checks, freeze candidates, then examine 2023 once.
- Proceed unchanged to 2024 only for signals that pass 2023.
- **Stop condition:** reject or block each failed signal; do not retune it from
  OpenAP outcomes and do not expand a failed method or source route.

### Phase 3: controlled family expansion

- Expand only methods whose pilot evidence passed both periods.
- Give each additional source family a small representative pilot before broad
  implementation.
- Reconcile exactly 149 formula contracts and evidence states, including
  blocked and not-evaluable signals.

### Phase 4: score integration

- Admit approved signals only.
- Apply redundancy and economic-family controls.
- Produce current score, provenance, coverage, and strict limitations.

Each phase gets a focused implementation plan and acceptance review. A no-go
result is a valid, conclusive deliverable and prevents further expenditure on
unvalidated proxies.

## 17. Required artifacts

At minimum, the program produces:

```text
openap_149_feasibility_register.csv
openap_149_feasibility_summary.md
openap_149_formula_registry.csv
openap_149_source_routes.csv
raw_source_manifest.parquet
security_identity_timeline.parquet
openap_permno_bridge.parquet
openap_permno_bridge_audit.csv
point_in_time_input_audit.parquet
openap_10_pilot_signal_values.parquet
openap_10_pilot_manifest.json
openap_10_pilot_freeze_manifest.json
openap_10_pilot_2023_validation.parquet
openap_10_pilot_2024_validation.parquet
openap_10_pilot_gate_decisions.csv
independent_approved_signal_values.parquet
independent_approved_signal_manifest.json
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

1. feasibility-register count and evidence reconciliation;
2. schema and formula-contract tests;
3. point-in-time and no-look-ahead tests;
4. SEC tag and filing-context fixtures;
5. corporate-action and security-identity fixtures;
6. identity coverage, interval, ambiguity, and anti-circularity tests;
7. known-formula hand calculations;
8. provider-response and rate-limit fixtures;
9. missing, zero, negative, non-finite, and sparse-event cases;
10. deterministic freeze and hash checks;
11. isolated evaluator tests using synthetic reference data;
12. GitHub identity audit, pilot reconstruction, sequential 2023/2024 pilot
    examination, and only then authorised family expansion.

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

The feasibility-first program has three legitimate completion outcomes.

### Outcome A: identity no-go

- all 149 signals have reconciled feasibility classifications;
- the missing free identity route is documented with exact evidence;
- strict validation and score eligibility remain zero;
- no large reconstruction campaign is started and no 90 percent claim is made.

### Outcome B: pilot no-go or partial pass

- the identity gate passed;
- all 10 pilot signals have frozen source, formula, and 2023 decisions;
- only 2023 passes were examined unchanged in 2024;
- each pilot has an evidence-backed `approved`, `rejected`, `blocked`, or
  `not_evaluable` status;
- only methods passing both periods are eligible for later expansion.

### Outcome C: controlled successful expansion

- all 149 signals have frozen formula and source contracts or documented
  zero-cost blocks;
- every implemented signal has independently frozen results and required
  monthly validation evidence;
- every signal has exactly one evidence-backed status;
- no signal enters the score without passing every mandatory gate;
- current score rows retain complete formula, source, identity, code, policy,
  and snapshot provenance;
- all counts reconcile and the result is reproducible from preserved source
  objects and the frozen repository revision.

Under every outcome, the meaningful reported number is the count independently
demonstrated at the agreed threshold. Candidate, calculated, reconstructed,
source-documented, and identity-blocked counts must be reported separately and
must never be presented as faithful OpenAP signals.
