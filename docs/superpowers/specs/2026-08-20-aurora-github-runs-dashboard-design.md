# Aurora GitHub Runs and Research Dashboard Design

## Status

Approved design, 2026-08-20. This specification covers a read-only web portal
for the public `trading-optimizer-lab-org/aurora` repository. It is separate
from the existing Streamlit live-trading dashboard in
`monitoring/dashboard.py`.

## Goal

Provide one secret-link web application that shows every GitHub Actions
workflow run, active execution, job, log, artifact, historical backtest
result, and provenance record produced by Aurora, while keeping the service
within a zero-cost Cloudflare free-tier budget.

## User-visible requirements

1. The web link works from any computer without a login form.
2. The link is an unguessable secret path. Anyone who obtains it can read the
   dashboard; that is an accepted trade-off.
3. All workflows are visible, including CI, tests, security, documentation,
   data, research, backtest, and paper-trading workflows.
4. Active runs refresh automatically and show the real last-sync timestamp.
5. Historical runs remain searchable after GitHub's artifact retention period
   where the dashboard has archived the relevant material.
6. Every artifact is indexed even when its contents are not copied.
7. Known JSON, CSV, Markdown, TXT, HTML, and report formats are interpreted;
   unknown formats remain available as raw/unclassified records.
8. Backtest metrics are displayed with phase, unit, period, baseline, cost
   model, candidate, source artifact, parser version, and provenance when
   present. Incompatible metrics are not silently compared.
9. The dashboard has no action controls for dispatching, cancelling, rerunning,
   publishing, or deleting workflows.
10. No GitHub or Cloudflare credential reaches the browser.
11. The archive never deliberately crosses the free storage budget. When the
    archive budget is reached, large-file copying pauses while metadata and
    source links continue to be indexed.

## Explicit scale boundary

The current repository API surface contains thousands of historical runs and
hundreds of thousands of artifacts. A literal permanent copy of every binary
artifact cannot be guaranteed at zero cost. The archive therefore uses three
tiers:

- **Index:** every workflow, run, job, artifact, status, timestamp, size,
  expiry, URL, and sync state.
- **Permanent result archive:** normalized summaries plus readable reports,
  metrics, manifests, CSV/JSON/Markdown/TXT/HTML outputs, and selected logs
  until the reserved free-tier storage budget is reached.
- **Source reference:** a direct GitHub link for large, duplicate, binary, or
  quota-blocked artifacts. The UI labels these as source-only rather than
  pretending they are permanently archived.

## Architecture

The deployment uses Cloudflare Workers Static Assets, D1, and R2. A GitHub
Actions synchronizer performs incremental ingestion. The browser talks only to
the Worker API.

```text
GitHub Actions REST API
        |
        v
GitHub sync workflow + parser registry
        |
        +--> D1: searchable index and normalized metric rows
        +--> R2: archived manifests, readable reports, selected files
        |
        v
Cloudflare Worker: secret path, read-only API, quota gate, cache
        |
        v
Static React dashboard served by Worker Static Assets
```

### Frontend

The frontend is a small React + TypeScript application built with Vite. It
uses hand-written CSS and SVG for charts so the first release does not need a
paid charting service or a large UI dependency. It has a static shell and
loads all data through the Worker API.

### Worker

The Worker serves static assets and owns all `/api` routes. It validates the
secret path before returning either the application shell or data. It reads
D1 and R2 through bindings, proxies short-lived GitHub data only when needed,
and never exposes secrets.

### Synchronizer

The synchronizer runs in GitHub Actions with the repository's workflow token
and Cloudflare credentials stored as Actions secrets. It is incremental,
checkpointed, idempotent, and safe to rerun. It uses stable GitHub IDs as
primary keys and records partial failures instead of dropping records.

## Navigation

The application has six primary areas:

- **Inicio:** active runs, recent failures, recent successes, sync health,
  archive usage, and notable parsed results.
- **Todos los runs:** paginated table for every workflow run with filters for
  workflow, status, conclusion, event, branch, date, and parser state.
- **Detalle del run:** run metadata, job timeline, step status, logs, artifacts,
  parsed results, provenance, and source links.
- **Backtests:** normalized metrics, result families, phase filters, charts,
  and comparisons only where the semantic contract matches.
- **Artefactos:** every indexed artifact, archive state, size, expiry, source
  URL, and available preview/download.
- **Workflows:** all workflow definitions, last run, counts by conclusion,
  parser coverage, and latest activity.

## Data model

The D1 schema uses the following tables. Large raw payloads remain in R2.

### `workflows`

`workflow_id`, `name`, `path`, `state`, `triggers_json`, `parser_key`,
`parser_status`, `first_seen_at`, `last_seen_at`, `run_count`,
`success_count`, `failure_count`, `updated_at`.

### `runs`

`run_id`, `workflow_id`, `name`, `status`, `conclusion`, `event`, `branch`,
`commit_sha`, `actor`, `run_number`, `run_attempt`, `created_at`,
`updated_at`, `started_at`, `completed_at`, `duration_seconds`, `html_url`,
`raw_manifest_key`, `captured_at`.

### `jobs`

`job_id`, `run_id`, `name`, `status`, `conclusion`, `started_at`,
`completed_at`, `duration_seconds`, `runner_name`, `html_url`, `steps_json`,
`captured_at`.

### `artifacts`

`artifact_id`, `run_id`, `name`, `size_bytes`, `created_at`, `expires_at`,
`expired`, `archive_state`, `archive_key`, `content_type`, `parser_status`,
`source_url`, `captured_at`.

`archive_state` is one of `indexed`, `archived`, `source_only`, `expired`,
`quota_blocked`, or `error`.

### `results`

One row represents one normalized metric or result datum:
`result_id`, `run_id`, `artifact_id`, `result_kind`, `parser_key`,
`parser_version`, `status`, `metric_key`, `metric_value`, `unit`, `phase`,
`period_start`, `period_end`, `baseline`, `cost_model`, `candidate_id`,
`passed`, `source_path`, `evidence_json`, `captured_at`.

### `sync_state`

`key`, `cursor_json`, `last_started_at`, `last_success_at`, `last_error`,
`runs_seen`, `jobs_seen`, `artifacts_seen`, `results_seen`, `r2_bytes_used`,
`quota_bytes`, `updated_at`.

## API contract

All endpoints are below the secret prefix and return JSON with a stable
`schema_version`.

- `GET /api/health` — deployment, sync timestamp, archive quota, and version.
- `GET /api/overview` — dashboard cards and current active-run snapshot.
- `GET /api/workflows` — all workflows with counts and parser coverage.
- `GET /api/runs` — cursor-paginated runs with filters.
- `GET /api/runs/:runId` — one run with jobs, artifacts, results, and links.
- `GET /api/jobs/:jobId` — one job and step-level detail.
- `GET /api/artifacts` — cursor-paginated artifact index with filters.
- `GET /api/results` — normalized results with semantic filters.
- `GET /api/archive/:key` — authorized R2 preview/download stream.

Pagination is cursor-based, not offset-based. Lists never load the full
repository into the browser. The Worker marks data as stale when the API
source or synchronizer has not succeeded within the expected window.

## Parser contract

Every parser implements a common interface:

```text
parse(source_bytes, source_name, context) -> ParseReport
```

`ParseReport` contains parser key/version, status, result kind, normalized
metrics, evidence paths, warnings, and errors. Parsers may return zero
metrics while still returning a successful raw archive record.

The generic parser handles common structured and text formats. Specialized
parsers are registered by workflow family and artifact naming patterns. A
parser must preserve the source artifact ID and may not invent a unit, phase,
baseline, pass state, or provenance hash.

## Free-tier guardrails

- The application uses Cloudflare Free services only.
- R2 writes are stopped before a reserved internal threshold below the free
  allowance; the threshold is configurable but defaults below 8 GB.
- Large and duplicate objects are source-only when the archive policy rejects
  them.
- D1 rows store searchable fields, not full raw files.
- The UI exposes current usage and the reason for every archive omission.
- No billing upgrade or paid resource is initiated by code or workflow.

## Failure handling

- GitHub API failures use bounded retry with exponential backoff, then persist
  a sync error and leave the last known data visible with a stale badge.
- A single malformed artifact cannot fail the run-level sync.
- D1 and R2 writes are idempotent and can be replayed from the checkpoint.
- A quota rejection is a visible archive state, not a silent success.
- Expired GitHub artifacts remain in D1 with their historical metadata and a
  clear expired/source-only label.
- Missing optional fields remain null; they are never inferred from display
  names alone.

## Verification and acceptance

The implementation is complete only when these checks pass:

1. Unit tests cover schema mapping, cursors, secret path handling, quota
   decisions, parser states, metric semantics, and stale-data badges.
2. Fixture tests cover active, successful, failed, cancelled, skipped, and
   artifact-less runs.
3. Parser fixtures include current Atlas/SWR/SPY/BTC/paper/literature/OpenAP
   output shapes plus generic CI/test/security outputs.
4. An integration test proves an incremental sync is idempotent and resumes
   after a failed page.
5. An archive test proves quota-blocked files remain indexed and source-linked.
6. Frontend tests prove filters, pagination, run detail rendering, raw-data
   fallback, and no-token-in-client behavior.
7. A live read-only verification checks the current Aurora API, one active run,
   one failed run, one completed research run, and their artifact metadata.
8. The free deployment configuration contains no paid-plan setting, and the
   deployment documentation states exactly which user-created secrets are
   required.

## Out of scope

- Workflow dispatch, cancellation, reruns, or other write actions.
- User accounts, multi-user RBAC, or password recovery.
- Replacing or extending the existing Streamlit live-trading dashboard.
- A guarantee that large GitHub binaries remain available after both GitHub
  retention and the free archive quota have ended.
