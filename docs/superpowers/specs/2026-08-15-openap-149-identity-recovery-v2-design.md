# OpenAP 149 identity recovery v2

Date: 2026-08-15

Status: approved under the user's explicit instruction to continue autonomously
without further questions.

## 1. Outcome sought

Find out, with executable evidence rather than search-result claims, whether a
public, zero-cost and authorised source can build an independent historical
security-to-PERMNO bridge for the OpenAP 149 validation. If one exists, freeze
the bridge before reading OpenAP signal values and apply the existing strict
identity gate. If none exists, produce a current, reproducible no-go and do not
start the ten-signal pilot.

This phase does not lower the previously approved scientific standard. A source
is useful only if it can contribute unambiguous, share-class-specific links for
every required month from 2023-01 through 2024-12. The completed bridge must
cover at least 70 percent of the official non-missing identity spine in every
month. A merely downloadable table, a formula that emits numbers, or a
company-level approximation is not a pass.

## 2. Fixed boundaries

- Authoritative worktree: `C:\Users\HP\AURORA-openap-proxy44`.
- Authoritative branch: `codex/openap-proxy44-validation`.
- The dirty primary checkout `C:\Users\HP\AURORA` is never modified, cleaned,
  restored or used for execution.
- `.artifacts/` is pre-existing user content and is never modified.
- No subagents and no forks.
- Source downloads, endpoint probes, coverage calculations and research runs
  execute only in GitHub Actions.
- Local work is restricted to inspection, design, editing and non-destructive
  Git operations.
- OOS-locked and forward data remain closed.
- OpenAP stock-level signal values cannot be used to select, tune or repair an
  identity link.
- No source that may incur a charge or requires an unprovided licensed account
  is queried.

## 3. Evidence already established

The first identity audit examined seven routes and found no strict candidate.
The v2 investigation adds the strongest newly discovered routes and records why
documentation alone cannot promote them.

| Candidate | Evidence | Current finding before executable probe |
|---|---|---|
| CRSP research products | https://indexes.morningstar.com/research-data-products | PERMNO and its historical security files are licensed products, not a public zero-cost source. |
| CRSP sample data | https://www.crsp.org/wp-content/uploads/2023/09/CRSP_Sample_Data_and_Software_Guide.pdf | Promotional sample only: 25 stock securities, through 2019. It cannot cover 2023-2024. |
| WRDS demo | https://wrds-www.wharton.upenn.edu/pages/about/demo-wrds/ | Illustrative sample access, not a broad licensed data export. |
| Std_Security_Code | https://github.com/Wenzhi-Ding/Std_Security_Code | Public files include useful static links, but the author says the relevant tables are mostly from WRDS, users must ensure access rights, links are static, and independent verification is required. It therefore cannot be presumed authorised or historical. |
| Open Source Bond Asset Pricing | https://openbondassetpricing.com/data/ | Current public downloads explicitly exclude proprietary fields such as the identifiers needed here; full construction requires WRDS and valid licences. |
| Chuck Fang Bond-Firm Link | https://www.chuckfang.finance/ | The current link is distributed through WRDS and is issuer/bond oriented. It is not a free broad equity-security bridge. |
| Corporate Bond Factors pipeline | https://github.com/Cstolborg/corp-bond-data | The code documents PERMNO output, but its inputs require WRDS TRACE, FISD and CRSP link files. Public code is not public source data. |
| Oxford Ownership and Productivity | https://ora.ox.ac.uk/objects/uuid%3Ae2758f97-6250-4407-9f1c-1e98e377f674 | The public archive exposes the thesis. The described identifier panel was built from CRSP/Compustat, covers only through 2020, and is not supplied as a public data file. |
| `farr::michels_2017` / csvbase | https://csvbase.com/rmirror/michels-2017/details | Public and small enough to probe; it has CUSIP, CIK and PERMNO, but only 423 event-sample rows and no monthly validity intervals. It is a partial historical clue, not a broad bridge. |
| KPSS patent data | https://github.com/KPSS2017/Technological-Innovation-Resource-Allocation-and-Growth-Extended-Data | Public PERMNO data for patent-linked firms, but no public security identifier suitable for the bridge and only a selected firm subset. |
| SEC plus OpenFIGI | https://www.sec.gov/files/company_tickers_exchange.json and https://www.openfigi.com/api/documentation | Supplies public identifiers but neither source supplies PERMNO. Combining two tables without PERMNO cannot create PERMNO. |
| OpenAP characteristic fingerprint | https://www.openassetpricing.com/data/ | Technically capable of suggesting matches using disjoint signals, but target-derived. It is permitted only as a labelled diagnostic upper bound and can never pass the independent bridge gate. |

## 4. Approaches considered

### A. Use a public pre-linked table

This is the shortest route if a table has a direct public security identifier,
PERMNO, validity dates, share-class detail, broad coverage and clear usage
rights. The newly found tables each miss at least one mandatory property. The
v2 workflow still probes their current endpoint, schema and stated terms so the
decision is based on preserved bytes rather than this design document alone.

### B. Compose official public identifiers

SEC CIK/ticker data, 13F CUSIPs and OpenFIGI can construct a strong public
security master. They cannot independently assign a proprietary PERMNO because
none contains that field. This route remains useful only on the public side of
a bridge whose PERMNO side comes from an independently acceptable source.

### C. Infer PERMNO from a data fingerprint

Matching a public ticker panel to OpenAP rows using prices, momentum or the 31
pre-existing signals could generate many technically plausible links. It would
also use the target publisher's values to recover identity and would make the
subsequent fidelity test partly circular. This route may quantify an upper
bound or help diagnose a future licensed bridge, but its rows carry
`target_derived=true` and are prohibited from strict coverage.

### Decision

Implement A as a fail-closed, source-by-source recovery audit; retain B as the
public identifier side of any future accepted bridge; encode C only as an
explicitly disqualified route. Do not weaken the gate or launch the pilot when
all candidates fail.

## 5. Candidate contract

The v2 catalogue has one row per independently auditable route. Every field is
explicit; missing evidence is a failure, not an inferred `true` value.

Required fields:

- stable `source_id`, evidence URL and retrieval URL;
- evidence date and expected media type;
- current public accessibility without login;
- zero-cost status;
- affirmative authority for the intended internal research use;
- original provenance and whether upstream licensed data is required;
- direct PERMNO field;
- direct public security-level identifier field;
- share-class specificity;
- historical `valid_from` and `valid_to` semantics;
- 2023-2024 availability;
- broad-universe claim and documented universe limitation;
- target-derived flag;
- expected schema evidence and documentary blocker.

A route passes documentary preflight only when all positive requirements are
explicitly true, `target_derived` is false, and no upstream licence or usage
right is unresolved. A repository software licence is not automatically
treated as a licence for third-party data inside the repository.

## 6. GitHub-only probe

The isolated workflow mode is `IDENTITY_SOURCE_RECOVERY_V2`. It performs the
following steps in order:

1. validate the frozen catalogue and its URLs;
2. make bounded HTTP requests only to candidates marked public and zero-cost;
3. preserve status, final URL, response headers, byte count, SHA-256 and a
   bounded evidence snapshot;
4. inspect supported CSV, JSON, Parquet or text schemas without a mass download;
5. reconcile observed fields with the candidate contract;
6. classify every route with exactly one terminal reason;
7. build a candidate bridge only from routes that pass documentary, access,
   schema, provenance and semantic gates;
8. freeze that bridge before reading the OpenAP identifier-only spine;
9. evaluate ambiguity and monthly coverage for all 24 required months;
10. authorise the pilot only if every strict identity gate passes.

The probe may download the complete Michels table because it is approximately
39 kB and its small size is itself part of the evidence. Large or unclear
sources are sampled with an HTTP range or metadata request. Redirects to login,
WRDS, payment or unavailable objects are recorded and not bypassed.

## 7. Route classifications

Each route ends in one of:

- `pass_candidate`: all pre-reference requirements passed and rows may enter a
  candidate bridge;
- `blocked_access`: unavailable, login-gated or paid;
- `blocked_rights`: intended use is not affirmatively authorised or upstream
  proprietary rights are unresolved;
- `blocked_schema`: required identifier or interval fields are absent;
- `blocked_semantics`: issuer-level, static, non-share-class or otherwise not a
  valid historical security link;
- `blocked_coverage_claim`: source declares a subset that cannot plausibly meet
  the broad-universe gate;
- `blocked_target_derived`: uses OpenAP values or another validation target;
- `probe_error`: bounded retrieval failed without proving a permanent source
  property.

`probe_error` is not silently converted into a scientific no-go. The aggregate
decision distinguishes unavailable evidence from a source that was observed
and failed a substantive requirement.

## 8. Bridge and coverage gate

Accepted source rows are normalised to the existing bridge schema:

```text
canonical_security_id
permno
valid_from
valid_to
share_class_id
evidence_url
evidence_kind
source_id
source_retrieved_at
source_sha256
zero_cost_authorized
```

Rows with missing identifiers, inferred share classes, invalid dates, ambiguous
overlaps or non-affirmative rights are rejected before freeze. Multiple
independent sources may be unioned only when each row independently passes and
conflicts are quarantined rather than resolved by OpenAP values.

The reference read is identifier-only: `permno` and `yyyymm`. Signal columns
are neither loaded nor available to bridge construction. The existing gate
then requires:

- no ambiguous active link;
- at least 70 percent coverage in every month from 2023-01 to 2024-12;
- bridge hash and row count frozen before reference read;
- zero target-derived rows;
- complete source and retrieval provenance.

## 9. Artifacts

The workflow uploads a single immutable bundle containing at least:

```text
openap_149_identity_sources_v2_audit.csv
openap_149_identity_source_probe_receipts.jsonl
openap_149_identity_source_evidence_manifest.json
openap_149_identity_recovery_v2_decision.json
openap_149_identity_recovery_v2_summary.md
openap_permno_bridge_v2.parquet
openap_permno_bridge_v2_manifest.json
openap_permno_bridge_v2_monthly_coverage.csv
```

The summary reports route counts by terminal classification, bridge rows,
ambiguities, minimum/median/maximum monthly coverage, pilot authorisation,
repository SHA, source hashes, locked-data status and whether target-derived
data influenced identity.

## 10. Tests

Tests are written before implementation and run in GitHub Actions. They cover:

- complete explicit catalogue fields and stable source IDs;
- rejection of unknown, missing or contradictory booleans;
- software-licence versus source-data-rights separation;
- bounded retrieval, redirects, content-type drift and deterministic hashes;
- schema observations for representative CSV, JSON, Parquet and HTML fixtures;
- fail-closed route classifications;
- prohibition of target-derived rows;
- issuer-level and static-link rejection;
- deterministic bridge union and conflict quarantine;
- freeze-before-reference enforcement;
- every-month 70 percent coverage and zero ambiguity;
- exact 149-signal reconciliation and zero strict approvals before a pilot;
- isolated workflow dispatch that skips the inherited heavy audit.

## 11. Apply decision

If at least one route yields a valid bridge and the combined bridge passes the
monthly gate, the same run records `identity_pass` and permits a separate,
frozen ten-signal pilot. It does not calculate the pilot in the source-probe
job.

If no route can contribute a valid row, or coverage is below 70 percent in any
month, the run records `blocked_identity_v2`, keeps strict approvals at zero,
does not launch the pilot, and updates the status document with exact route and
artifact evidence. This is the expected outcome from current documentation,
but only the GitHub run may establish the executable result.

## 12. Completion criteria

This phase is complete when:

- every v2 candidate has a current probe receipt or a documentary reason why a
  request was prohibited;
- all classifications reconcile to the frozen catalogue count;
- the bridge is either valid and coverage-tested or intentionally empty with a
  machine-readable reason;
- the pilot decision follows the strict gate mechanically;
- the workflow and focused tests pass at the exact repository SHA;
- the final status distinguishes technical accessibility, legal/provenance
  suitability, identity semantics, coverage and OpenAP fidelity.

