# Aurora GitHub Runs Dashboard Implementation Plan

> **For agentic workers:** Execute this plan inline in the current checkout. Subagents and forks are prohibited by the repository instructions.

**Goal:** Build and verify a read-only, secret-link Aurora dashboard that indexes every GitHub Actions run and artifact, preserves normalized research results within a zero-cost Cloudflare archive budget, and serves a complete responsive web UI.

**Architecture:** A React/Vite static client is served by one Cloudflare Worker using Static Assets. The Worker exposes the secret-path API backed by D1 for searchable metadata and R2 for selected permanent files. A GitHub Actions synchronizer calls an authenticated ingestion endpoint, uses an extensible parser registry, and records every run/job/artifact even when a file is source-only.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, browser Fetch API, Cloudflare Workers, D1, R2, Python 3.14 standard library for GitHub ingestion and parser tests, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-20-aurora-github-runs-dashboard-design.md`

## Global Constraints

- Keep the web isolated under `web/`, `cloudflare/`, `scripts/aurora_dashboard_*`, and targeted dashboard tests.
- Do not modify, reformat, delete, stage, or commit unrelated dirty files.
- No subagents, forks, browser automation, workflow write actions, or research/backtest execution.
- The browser receives no GitHub or Cloudflare credential.
- Every workflow and artifact is indexed; unknown formats remain visible as unclassified/source-only records.
- R2 archiving stops below the free-tier quota; quota-blocked files remain indexed and linked to GitHub.
- All API lists use cursor pagination and return `schema_version`.
- Metrics retain phase, unit, period, baseline, cost model, provenance, source artifact, and parser version when available.
- Existing Streamlit live-trading dashboard remains unchanged.

---

### Task 1: Establish shared contracts, demo fixtures, and package commands

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/types.ts`
- Create: `web/src/fixtures.ts`
- Create: `web/src/types.test.ts`

**Interfaces:**
- Produces the frontend `DashboardApi` types consumed by every UI component.
- `types.ts` exports `Run`, `Job`, `Artifact`, `ResultMetric`, `Workflow`, `Overview`, `Page<T>`, `Health`, and `RunDetail`.
- `fixtures.ts` exports `demoOverview`, `demoRuns`, `demoWorkflows`, `demoArtifacts`, `demoResults`, and `demoRunDetail` for offline UI operation.

- [ ] **Step 1: Write the failing type-contract tests**

Create `web/src/types.test.ts` with runtime fixture assertions:

```ts
import { describe, expect, it } from "vitest";
import { demoRunDetail, demoRuns } from "./fixtures";

describe("dashboard contracts", () => {
  it("keeps stable run identity and pagination", () => {
    expect(demoRuns.schema_version).toBe(1);
    expect(demoRuns.items[0].run_id).toBeGreaterThan(0);
    expect(demoRuns.next_cursor).toBeNull();
  });

  it("links detail jobs, artifacts, and results to one run", () => {
    const detail = demoRunDetail;
    expect(detail.run.run_id).toBe(detail.jobs[0].run_id);
    expect(detail.artifacts[0].run_id).toBe(detail.run.run_id);
    expect(detail.results[0].run_id).toBe(detail.run.run_id);
  });
});
```

- [ ] **Step 2: Run the focused test and verify the expected missing-module failure**

Run: `npm --prefix web test -- --run src/types.test.ts`

Expected: FAIL because the web package and contract modules do not exist yet.

- [ ] **Step 3: Add the Vite/Vitest package and exact domain types**

Use `react`, `react-dom`, `vite`, `typescript`, `@vitejs/plugin-react`,
`vitest`, and `jsdom`. Keep the package independent from Aurora's Python
package. Define nullable provenance fields instead of inventing defaults.

- [ ] **Step 4: Add deterministic fixtures representing active, failed, successful, and source-only records**

Include one Atlas-like research run with parsed Calmar/Sharpe metrics, one
failed lint run, one active run, and one artifact with `archive_state:
"source_only"`. Use no live market data.

- [ ] **Step 5: Run the focused test and build**

Run: `npm --prefix web test -- --run src/types.test.ts`

Expected: PASS.

Run: `npm --prefix web run build`

Expected: Vite writes `web/dist` successfully.

- [ ] **Step 6: Commit only the new web contract files**

```powershell
git add -- web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html web/src/types.ts web/src/fixtures.ts web/src/types.test.ts
git commit --only -m "feat: add dashboard data contracts" -- web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html web/src/types.ts web/src/fixtures.ts web/src/types.test.ts
```

### Task 2: Add the D1 schema, Worker configuration, secret path, and read API

**Files:**
- Create: `cloudflare/wrangler.toml`
- Create: `cloudflare/migrations/0001_dashboard.sql`
- Create: `cloudflare/src/env.ts`
- Create: `cloudflare/src/auth.ts`
- Create: `cloudflare/src/db.ts`
- Create: `cloudflare/src/api.ts`
- Create: `cloudflare/src/index.ts`
- Create: `cloudflare/src/api.test.ts`

**Interfaces:**
- `auth.ts` exports `authorizePath(pathname: string, secret: string): AuthResult`.
- `db.ts` exports `queryOverview`, `queryRuns`, `queryRunDetail`, `queryWorkflows`, `queryArtifacts`, `queryResults`, and `queryHealth`.
- `api.ts` exports `handleApi(request, env, route)` and JSON helpers.
- `index.ts` exports the Worker `fetch` handler and serves Static Assets only after secret authorization.

- [ ] **Step 1: Write failing auth and pagination tests**

Cover an invalid secret, a valid `/s/<secret>/api/health` path, a missing
secret, and deterministic cursor encoding:

```ts
it("rejects paths without the exact secret segment", () => {
  expect(authorizePath("/s/wrong/api/health", "right").ok).toBe(false);
});

it("accepts the secret and preserves the API suffix", () => {
  expect(authorizePath("/s/right/api/runs", "right")).toEqual({
    ok: true,
    suffix: "/api/runs",
  });
});
```

- [ ] **Step 2: Run the Worker focused tests and verify the expected missing-module failure**

Run: `npm --prefix cloudflare test -- --run src/api.test.ts`

Expected: FAIL because the Worker package and modules are not present.

- [ ] **Step 3: Create the idempotent D1 schema and indexes**

Create `workflows`, `runs`, `jobs`, `artifacts`, `results`, and `sync_state`
with the exact fields from the specification. Add indexes for
`runs(updated_at)`, `runs(status, conclusion)`, `runs(workflow_id)`,
`artifacts(run_id)`, and `results(metric_key, phase)`.

- [ ] **Step 4: Implement secret authorization without leaking the secret**

Require `/s/<DASHBOARD_LINK_SECRET>/...`. Return a generic 404 for invalid
paths. Do not put the secret into response JSON, HTML, logs, or analytics.
Set `Cache-Control: no-store` on API responses and `Referrer-Policy:
no-referrer` on the application response.

- [ ] **Step 5: Implement read-only D1 queries and stable JSON envelopes**

Every list response has the form:

```ts
{ schema_version: 1, items: T[], next_cursor: string | null, stale: boolean }
```

Implement overview, health, workflow list, run list, run detail, artifact
list, and result list. Enforce a maximum page size of 100 and reject invalid
cursor/filter values with status 400.

- [ ] **Step 6: Implement the Worker fetch router and Static Assets fallback**

Authorize first, route `/api/*` to D1 queries, route `/archive/*` to R2 after
checking the stored archive key, and forward authorized non-API paths to
`env.ASSETS.fetch`. No route dispatches or mutates a GitHub workflow.

- [ ] **Step 7: Run Worker tests and validate the migration text**

Run: `npm --prefix cloudflare test -- --run src/api.test.ts`

Expected: PASS.

Run: `rg -n "CREATE TABLE|CREATE INDEX|DROP TABLE|DELETE FROM" cloudflare/migrations/0001_dashboard.sql`

Expected: only `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.

- [ ] **Step 8: Commit only the Worker files**

```powershell
git add -- cloudflare
git commit --only -m "feat: add dashboard Worker read API" -- cloudflare
```

### Task 3: Implement parser registry and quota-safe archive policy

**Files:**
- Create: `scripts/aurora_dashboard_parsers.py`
- Create: `scripts/aurora_dashboard_archive.py`
- Create: `tests/test_aurora_dashboard_parsers.py`
- Create: `tests/test_aurora_dashboard_archive.py`

**Interfaces:**
- `parse_artifact(name, payload, context) -> ParseReport`.
- `register_parser(key, matcher, parser)`.
- `archive_decision(name, size_bytes, mime_type, used_bytes, quota_bytes, duplicate) -> ArchiveDecision`.
- `NormalizedMetric` contains `metric_key`, `value`, `unit`, `phase`, `period_start`, `period_end`, `baseline`, `cost_model`, `candidate_id`, `passed`, and `evidence`.

- [ ] **Step 1: Write failing parser tests from real-shaped fixtures**

Cover JSON metrics, CSV metrics, Markdown tables, malformed content, unknown
binary content, Atlas/SWR/paper/OpenAP workflow names, and the rule that a
missing unit remains `None`.

- [ ] **Step 2: Run parser tests and verify the expected missing-module failure**

Run: `"C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_parsers.py -q`

Expected: FAIL because the parser module does not exist.

- [ ] **Step 3: Implement generic structured/text parsing**

Read UTF-8 JSON, CSV, Markdown tables, and text line pairs. Recognize only
explicit numeric keys and preserve source paths. Return `status="unclassified"`
for unsupported extensions and `status="error"` for malformed input.

- [ ] **Step 4: Implement named workflow-family adapters**

Register adapters for `atlas`, `swr`, `spy`, `btc`, `paper`, `literature`,
and `openap`. Adapters may add result kind and evidence labels but must use
the same normalized metric structure and must not infer phase or units.

- [ ] **Step 5: Implement archive policy and duplicate detection**

Archive readable reports and structured files under the reserved quota. Mark
large, binary, duplicate, expired, and quota-blocked objects as `source_only`
or the exact corresponding state. Never return an archive decision that would
make `used_bytes + size_bytes > quota_bytes`.

- [ ] **Step 6: Run parser and archive tests**

Run: `"C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_parsers.py tests/test_aurora_dashboard_archive.py -q`

Expected: PASS.

- [ ] **Step 7: Commit only parser and archive files**

```powershell
git add -- scripts/aurora_dashboard_parsers.py scripts/aurora_dashboard_archive.py tests/test_aurora_dashboard_parsers.py tests/test_aurora_dashboard_archive.py
git commit --only -m "feat: add dashboard result parsers and quota gate" -- scripts/aurora_dashboard_parsers.py scripts/aurora_dashboard_archive.py tests/test_aurora_dashboard_parsers.py tests/test_aurora_dashboard_archive.py
```

### Task 4: Implement the incremental GitHub synchronizer and ingestion endpoint

**Files:**
- Create: `scripts/aurora_dashboard_sync.py`
- Create: `tests/test_aurora_dashboard_sync.py`
- Modify: `cloudflare/src/api.ts`
- Modify: `cloudflare/src/db.ts`
- Modify: `cloudflare/src/index.ts`

**Interfaces:**
- `GitHubClient.list_runs(page, per_page)`, `list_jobs(run_id)`, and `list_artifacts(run_id)`.
- `SyncEngine.sync_page(cursor) -> SyncReport`.
- `POST /internal/sync/batch` accepts an authenticated batch and returns counts, archive decisions, and the next cursor.

- [ ] **Step 1: Write failing idempotency and resume tests**

Use a fake GitHub client and fake ingestion transport. Assert that the same
run/job/artifact batch twice produces one logical record and that a failed
second page leaves the first page checkpoint intact.

- [ ] **Step 2: Run the synchronizer tests and verify the expected failure**

Run: `"C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_sync.py -q`

Expected: FAIL because the synchronizer module does not exist.

- [ ] **Step 3: Implement the GitHub REST client with bounded retries**

Use Python standard-library `urllib.request`. Send `Accept:
application/vnd.github+json`, `X-GitHub-Api-Version`, and the token only in
the server-side request. Retry 429 and 5xx responses with a bounded backoff;
record the response error when the bound is exhausted.

- [ ] **Step 4: Implement normalization and cursor checkpoints**

Convert GitHub run/job/artifact payloads to the D1 contract. Use stable IDs,
store the current page and `updated_at` cursor, and make repeated batches
safe. Every artifact receives an archive decision and source URL.

- [ ] **Step 5: Implement authenticated Worker ingestion**

Require a separate `DASHBOARD_SYNC_TOKEN`, compare it server-side, accept
bounded JSON batches, upsert D1 rows, store selected R2 files, and update
`sync_state`. Return partial errors per item rather than failing the whole
batch.

- [ ] **Step 6: Add dry-run and fixture modes**

`--dry-run` may read GitHub but never writes. `--fixture path` runs the exact
normalizer against local JSON fixtures. Neither mode performs research,
backtests, mass downloads, or workflow writes.

- [ ] **Step 7: Run the full synchronizer test set**

Run: `"C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_sync.py tests/test_aurora_dashboard_parsers.py tests/test_aurora_dashboard_archive.py -q`

Expected: PASS.

- [ ] **Step 8: Commit synchronizer changes only**

```powershell
git add -- scripts/aurora_dashboard_sync.py tests/test_aurora_dashboard_sync.py cloudflare/src/api.ts cloudflare/src/db.ts cloudflare/src/index.ts
git commit --only -m "feat: add incremental GitHub dashboard sync" -- scripts/aurora_dashboard_sync.py tests/test_aurora_dashboard_sync.py cloudflare/src/api.ts cloudflare/src/db.ts cloudflare/src/index.ts
```

### Task 5: Build the complete dashboard interface

**Files:**
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/api.ts`
- Create: `web/src/styles.css`
- Create: `web/src/components/Layout.tsx`
- Create: `web/src/components/StatusPill.tsx`
- Create: `web/src/components/MetricCard.tsx`
- Create: `web/src/components/RunTable.tsx`
- Create: `web/src/components/RunDetail.tsx`
- Create: `web/src/components/ResultsView.tsx`
- Create: `web/src/components/ArtifactsView.tsx`
- Create: `web/src/components/WorkflowsView.tsx`
- Create: `web/src/components/Charts.tsx`
- Create: `web/src/components/EmptyState.tsx`
- Create: `web/src/components/ErrorState.tsx`
- Create: `web/src/App.test.tsx`

**Interfaces:**
- `api.ts` exports `DashboardClient` with `getOverview`, `getRuns`, `getRunDetail`, `getResults`, `getArtifacts`, `getWorkflows`, and `getHealth`.
- `App.tsx` owns the hash route and page state; components receive typed data and callbacks, not raw fetch logic.
- `Charts.tsx` exports `Sparkline`, `ConclusionBars`, and `JobTimeline` using SVG only.

- [ ] **Step 1: Write failing UI behavior tests**

Cover the default overview, route changes, active-run refresh badge, stale
data warning, source-only artifact badge, filters, and run-detail links.

- [ ] **Step 2: Run the UI tests and verify the expected failure**

Run: `npm --prefix web test -- --run src/App.test.tsx`

Expected: FAIL because the application components do not exist.

- [ ] **Step 3: Implement the API client with demo fallback**

Derive the secret prefix from `window.location.pathname`. Fetch the Worker
endpoints with `AbortController`, preserve `stale`, and fall back to fixtures
only when `VITE_DEMO_MODE=true`; production errors must remain visible.

- [ ] **Step 4: Implement the application shell and navigation**

Use a compact left rail on desktop and bottom navigation on small screens.
Show Aurora branding, current sync timestamp, archive percentage, and a
clear `solo lectura` label. No dispatch or destructive controls exist.

- [ ] **Step 5: Implement all six views**

Build Inicio, Todos los runs, Detalle del run, Backtests, Artefactos, and
Workflows with loading, empty, stale, error, pagination, filter, and raw-data
states. Keep CI/test/security runs visible in the generic run table.

- [ ] **Step 6: Implement charts and semantic metric display**

Render conclusion bars, job timelines, run-duration sparklines, and metric
cards. Display phase/unit/baseline/source beside values and block comparison
when semantic fields differ.

- [ ] **Step 7: Add responsive CSS and accessibility checks**

Use keyboard-focusable controls, visible focus rings, table captions, status
text in addition to color, reduced-motion support, and layouts that work from
mobile widths to large monitors.

- [ ] **Step 8: Run UI tests and production build**

Run: `npm --prefix web test -- --run src/types.test.ts src/App.test.tsx`

Expected: PASS.

Run: `npm --prefix web run build`

Expected: PASS with `web/dist/index.html`.

- [ ] **Step 9: Commit frontend files only**

```powershell
git add -- web
git commit --only -m "feat: add Aurora research dashboard UI" -- web
```

### Task 6: Wire Cloudflare deployment and GitHub synchronization workflow

**Files:**
- Modify: `cloudflare/wrangler.toml`
- Create: `.github/workflows/aurora-dashboard-sync.yml`
- Create: `.github/workflows/aurora-dashboard-deploy.yml`
- Create: `docs/AURORA_DASHBOARD.md`
- Create: `cloudflare/.dev.vars.example`
- Create: `.gitignore` entries only if required for `web/dist` and local secrets

**Interfaces:**
- `aurora-dashboard-sync.yml` runs on a bounded schedule and manual dispatch,
  reads `GITHUB_TOKEN`, calls the Worker ingestion endpoint, and writes no
  workflow state.
- `aurora-dashboard-deploy.yml` builds `web`, runs Worker tests, applies the
  D1 migration when explicitly configured, and deploys with Wrangler.
- Documentation lists exact secret names without values and contains the
  generated secret-link format.

- [ ] **Step 1: Write workflow contract tests**

Create `tests/test_aurora_dashboard_workflows.py` to parse both YAML files and
assert `workflow_dispatch`, bounded `schedule`, read-only permissions for the
sync job, required secret names, and absence of `gh workflow run`, `cancel`,
or `rerun` commands.

- [ ] **Step 2: Run the workflow tests and verify the expected failure**

Run: `"C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_workflows.py -q`

Expected: FAIL because the workflows do not exist.

- [ ] **Step 3: Add Wrangler configuration and local variables template**

Bind `ASSETS`, `DB`, and `ARCHIVE`; keep IDs and secrets outside committed
files. Set the Worker compatibility date to `2026-08-20` and default archive
quota below the free-tier ceiling.

- [ ] **Step 4: Add the sync workflow with least-privilege permissions**

Use `contents: read` and `actions: read`. Pass the repository token to the
sync script and the Worker URL/token through GitHub Actions secrets. Do not
download every large binary by default.

- [ ] **Step 5: Add the deploy workflow and exact setup documentation**

Document Cloudflare account setup, D1/R2 creation, `wrangler secret put`,
GitHub secret names, deployment commands, link rotation, quota behavior, and
how to run demo mode locally. Do not claim publication until a deployment URL
responds successfully.

- [ ] **Step 6: Run workflow tests and YAML parse checks**

Run: `"C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_workflows.py -q`

Expected: PASS.

Run: `npx --yes wrangler deploy --dry-run --config cloudflare/wrangler.toml`

Expected: configuration parses; if Cloudflare account credentials are absent,
the command must stop before network deployment and the documentation must
record that as an external setup requirement.

- [ ] **Step 7: Commit deployment files only**

```powershell
git add -- cloudflare/wrangler.toml cloudflare/.dev.vars.example .github/workflows/aurora-dashboard-sync.yml .github/workflows/aurora-dashboard-deploy.yml docs/AURORA_DASHBOARD.md tests/test_aurora_dashboard_workflows.py
git commit --only -m "ci: add free Cloudflare dashboard deployment" -- cloudflare/wrangler.toml cloudflare/.dev.vars.example .github/workflows/aurora-dashboard-sync.yml .github/workflows/aurora-dashboard-deploy.yml docs/AURORA_DASHBOARD.md tests/test_aurora_dashboard_workflows.py
```

### Task 7: Verify against current Aurora state and close the implementation

**Files:**
- Modify: `docs/AURORA_DASHBOARD.md` with observed verification evidence
- Modify: `docs/superpowers/plans/2026-08-20-aurora-github-runs-dashboard-implementation.md` only to mark completed steps if desired

- [ ] **Step 1: Run targeted Python and frontend test suites**

Run: `"C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_*.py -q`

Expected: PASS for all new dashboard tests.

Run: `npm --prefix web test -- --run`

Expected: PASS for all frontend tests.

- [ ] **Step 2: Build the production frontend and validate Worker bundle**

Run: `npm --prefix web run build`

Expected: PASS.

Run: `npx --yes wrangler deploy --dry-run --config cloudflare/wrangler.toml`

Expected: bundle and asset manifest validate without a deployment side effect.

- [ ] **Step 3: Perform read-only live API verification**

Use `gh api` against `trading-optimizer-lab-org/aurora` to capture one active
run when available, one failed run, one completed research run, workflow count,
and artifact metadata. Run the synchronizer in `--dry-run` mode only. Do not
dispatch, cancel, rerun, download en masse, or modify GitHub state.

- [ ] **Step 4: Verify the completion matrix**

Confirm evidence for every requirement in the design spec: all-workflow
indexing, secret path, no client credential, pagination, parser fallback,
archive quota stop, stale badges, metric provenance, responsive build,
read-only workflows, and free-tier configuration.

- [ ] **Step 5: Commit only verification documentation**

```powershell
git add -- docs/AURORA_DASHBOARD.md
git commit --only -m "docs: record dashboard verification" -- docs/AURORA_DASHBOARD.md
```

- [ ] **Step 6: Attempt publication only if Cloudflare credentials already exist**

Run `npx --yes wrangler whoami` first. If already authenticated, deploy the
validated Worker and run a read-only HTTP health check. If not authenticated,
leave the complete deploy workflow and exact setup steps in the repository and
report the external credential blocker without claiming a public URL.

