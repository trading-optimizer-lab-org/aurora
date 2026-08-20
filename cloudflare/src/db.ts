import type { Artifact, Job, ResultMetric, Run, RunDetail, Workflow } from "../../web/src/types";
import type { Env } from "./env";

type Row = Record<string, unknown>;

function rows<T extends Row>(result: D1Result<T>): T[] {
  return result.results || [];
}

function numberValue(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function nullableString(value: unknown): string | null {
  return value === null || value === undefined || value === "" ? null : String(value);
}

function decodeCursor(cursor: string | null): { updated_at: string; run_id: number } | null {
  if (!cursor) return null;
  try {
    const normalized = cursor.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const decoded = JSON.parse(atob(padded));
    if (typeof decoded.updated_at !== "string" || !Number.isSafeInteger(Number(decoded.run_id))) throw new Error("invalid cursor");
    return { updated_at: decoded.updated_at, run_id: Number(decoded.run_id) };
  } catch {
    throw new Error("invalid cursor");
  }
}

function decodeResultCursor(cursor: string | null): { captured_at: string; result_id: string } | null {
  if (!cursor) return null;
  try {
    const normalized = cursor.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const decoded = JSON.parse(atob(padded));
    if (typeof decoded.captured_at !== "string" || typeof decoded.result_id !== "string" || !decoded.result_id) throw new Error("invalid cursor");
    return { captured_at: decoded.captured_at, result_id: decoded.result_id };
  } catch {
    throw new Error("invalid cursor");
  }
}

function encodeResultCursor(capturedAt: string, resultId: string): string {
  return btoa(JSON.stringify({ captured_at: capturedAt, result_id: resultId }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function pageLimit(params: URLSearchParams, fallback: number): number {
  const raw = params.get("limit");
  if (raw === null || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > 100) throw new Error("invalid limit");
  return value;
}

function syncIsStale(sync: Row | null): boolean {
  const lastSuccess = sync?.last_success_at;
  if (!lastSuccess) return true;
  const timestamp = Date.parse(String(lastSuccess));
  return !Number.isFinite(timestamp) || Date.now() - timestamp > 45 * 60 * 1000;
}

export function encodeCursor(updatedAt: string, runId: number): string {
  return btoa(JSON.stringify({ updated_at: updatedAt, run_id: runId }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function toRun(row: Row): Run {
  return {
    run_id: numberValue(row.run_id),
    workflow_id: numberValue(row.workflow_id),
    workflow_name: String(row.workflow_name || "Unknown workflow"),
    name: String(row.name || "Unnamed run"),
    status: String(row.status || "unknown"),
    conclusion: nullableString(row.conclusion),
    event: String(row.event || "unknown"),
    branch: String(row.branch || "unknown"),
    commit_sha: String(row.commit_sha || ""),
    actor: String(row.actor || "unknown"),
    run_number: numberValue(row.run_number),
    run_attempt: numberValue(row.run_attempt, 1),
    created_at: String(row.created_at || ""),
    updated_at: String(row.updated_at || ""),
    started_at: nullableString(row.started_at),
    completed_at: nullableString(row.completed_at),
    duration_seconds: nullableNumber(row.duration_seconds),
    html_url: String(row.html_url || ""),
    parser_status: (String(row.parser_status || "unclassified") as Run["parser_status"]),
    artifact_count: numberValue(row.artifact_count),
    result_count: numberValue(row.result_count),
  };
}

function toWorkflow(row: Row): Workflow {
  let triggers: string[] = [];
  try {
    const parsed = JSON.parse(String(row.triggers_json || "[]"));
    if (Array.isArray(parsed)) triggers = parsed.map(String);
  } catch {
    triggers = [];
  }
  return {
    workflow_id: numberValue(row.workflow_id),
    name: String(row.name || "Unknown workflow"),
    path: String(row.path || ""),
    state: String(row.state || "unknown"),
    triggers,
    parser_key: String(row.parser_key || "generic"),
    parser_status: String(row.parser_status || "unclassified") as Workflow["parser_status"],
    first_seen_at: String(row.first_seen_at || ""),
    last_seen_at: String(row.last_seen_at || ""),
    run_count: numberValue(row.run_count),
    success_count: numberValue(row.success_count),
    failure_count: numberValue(row.failure_count),
  };
}

function toJob(row: Row): Job {
  let steps: Job["steps"] = [];
  try {
    const parsed = JSON.parse(String(row.steps_json || "[]"));
    if (Array.isArray(parsed)) steps = parsed as Job["steps"];
  } catch {
    steps = [];
  }
  return {
    job_id: numberValue(row.job_id),
    run_id: numberValue(row.run_id),
    name: String(row.name || "Unnamed job"),
    status: String(row.status || "unknown"),
    conclusion: nullableString(row.conclusion),
    started_at: nullableString(row.started_at),
    completed_at: nullableString(row.completed_at),
    duration_seconds: nullableNumber(row.duration_seconds),
    runner_name: nullableString(row.runner_name),
    html_url: String(row.html_url || ""),
    steps,
  };
}

function toArtifact(row: Row): Artifact {
  return {
    artifact_id: numberValue(row.artifact_id),
    run_id: numberValue(row.run_id),
    name: String(row.name || "Unnamed artifact"),
    size_bytes: numberValue(row.size_bytes),
    created_at: String(row.created_at || ""),
    expires_at: nullableString(row.expires_at),
    expired: Boolean(numberValue(row.expired)),
    archive_state: String(row.archive_state || "indexed") as Artifact["archive_state"],
    archive_key: nullableString(row.archive_key),
    content_type: nullableString(row.content_type),
    parser_status: String(row.parser_status || "unclassified") as Artifact["parser_status"],
    source_url: String(row.source_url || ""),
  };
}

function toResult(row: Row): ResultMetric {
  let evidence: ResultMetric["evidence"] = {};
  try {
    const parsed = JSON.parse(String(row.evidence_json || "{}"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) evidence = parsed;
  } catch {
    evidence = {};
  }
  return {
    result_id: String(row.result_id || ""),
    run_id: numberValue(row.run_id),
    artifact_id: nullableNumber(row.artifact_id),
    result_kind: String(row.result_kind || "unknown"),
    parser_key: String(row.parser_key || "generic"),
    parser_version: String(row.parser_version || "unknown"),
    status: String(row.status || "unclassified") as ResultMetric["status"],
    metric_key: String(row.metric_key || "unknown"),
    metric_value: nullableNumber(row.metric_value),
    value_text: nullableString(row.value_text),
    unit: nullableString(row.unit),
    phase: nullableString(row.phase),
    period_start: nullableString(row.period_start),
    period_end: nullableString(row.period_end),
    baseline: nullableString(row.baseline),
    cost_model: nullableString(row.cost_model),
    candidate_id: nullableString(row.candidate_id),
    passed: row.passed === null || row.passed === undefined ? null : Boolean(numberValue(row.passed)),
    source_path: nullableString(row.source_path),
    evidence,
    captured_at: String(row.captured_at || ""),
  };
}

export async function queryRuns(env: Env, params: URLSearchParams) {
  const requested = pageLimit(params, 25);
  const cursor = decodeCursor(params.get("cursor"));
  const conditions: string[] = [];
  const bindings: unknown[] = [];
  const add = (condition: string, ...values: unknown[]) => { conditions.push(condition); bindings.push(...values); };

  const status = params.get("status");
  if (status) {
    const conclusionStatuses = new Set(["success", "failure", "cancelled", "skipped", "neutral", "timed_out", "action_required"]);
    add(conclusionStatuses.has(status) ? "conclusion = ?" : "status = ?", status);
  }
  if (params.get("conclusion")) add("conclusion = ?", params.get("conclusion"));
  if (params.get("workflow_id")) {
    const workflowId = Number(params.get("workflow_id"));
    if (!Number.isSafeInteger(workflowId) || workflowId <= 0) throw new Error("invalid workflow_id");
    add("workflow_id = ?", workflowId);
  }
  if (params.get("branch")) add("branch = ?", params.get("branch"));
  if (params.get("event")) add("event = ?", params.get("event"));
  if (params.get("q")) add("(name LIKE ? OR workflow_name LIKE ? OR branch LIKE ?)", `%${params.get("q")}%`, `%${params.get("q")}%`, `%${params.get("q")}%`);
  if (cursor) {
    conditions.push("(updated_at < ? OR (updated_at = ? AND run_id < ?))");
    bindings.push(cursor.updated_at, cursor.updated_at, cursor.run_id);
  }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  const [result, sync] = await Promise.all([
    env.DB.prepare("SELECT * FROM runs " + where + " ORDER BY updated_at DESC, run_id DESC LIMIT ?")
      .bind(...bindings, requested + 1)
      .all<Row>(),
    env.DB.prepare("SELECT last_success_at FROM sync_state WHERE key = 'default'").first<Row>(),
  ]);
  const found = rows(result);
  const hasMore = found.length > requested;
  const items = found.slice(0, requested).map(toRun);
  const last = items[items.length - 1];
  return { schema_version: 1 as const, items, next_cursor: hasMore && last ? encodeCursor(last.updated_at, last.run_id) : null, stale: syncIsStale(sync) };
}

export async function queryOverview(env: Env) {
  const active = await env.DB.prepare("SELECT * FROM runs WHERE status != 'completed' ORDER BY updated_at DESC, run_id DESC LIMIT 8").all<Row>();
  const recent = await env.DB.prepare("SELECT * FROM runs ORDER BY updated_at DESC, run_id DESC LIMIT 8").all<Row>();
  const totals = await env.DB.prepare(`SELECT
    (SELECT COUNT(*) FROM workflows) AS workflows,
    (SELECT COUNT(*) FROM runs) AS runs,
    (SELECT COUNT(*) FROM runs WHERE status != 'completed') AS active_runs,
    (SELECT COUNT(*) FROM artifacts) AS artifacts,
    (SELECT COUNT(*) FROM results WHERE status = 'parsed') AS parsed_results`).first<Row>();
  const conclusions = await env.DB.prepare("SELECT COALESCE(conclusion, status) AS label, COUNT(*) AS count FROM runs GROUP BY COALESCE(conclusion, status) ORDER BY count DESC").all<Row>();
  const archive = await env.DB.prepare(`SELECT
    COALESCE(SUM(CASE WHEN archive_state = 'archived' THEN size_bytes ELSE 0 END), 0) AS used_bytes,
    COALESCE(SUM(CASE WHEN archive_state = 'archived' THEN 1 ELSE 0 END), 0) AS archived_files,
    COALESCE(SUM(CASE WHEN archive_state IN ('source_only', 'quota_blocked') THEN 1 ELSE 0 END), 0) AS source_only_files,
    COALESCE(SUM(CASE WHEN archive_state = 'error' THEN 1 ELSE 0 END), 0) AS error_files
    FROM artifacts`).first<Row>();
  const sync = await env.DB.prepare("SELECT * FROM sync_state WHERE key = 'default'").first<Row>();
  const quota = numberValue(sync?.quota_bytes, 7516192768);
  const stale = syncIsStale(sync);
  return {
    schema_version: 1 as const,
    stale,
    generated_at: new Date().toISOString(),
    active_runs: rows(active).map(toRun),
    recent_runs: rows(recent).map(toRun),
    totals: {
      workflows: numberValue(totals?.workflows),
      runs: numberValue(totals?.runs),
      active_runs: numberValue(totals?.active_runs),
      artifacts: numberValue(totals?.artifacts),
      parsed_results: numberValue(totals?.parsed_results),
    },
    conclusions: rows(conclusions).map((row) => ({ label: String(row.label), count: numberValue(row.count) })),
    archive: {
      used_bytes: numberValue(sync?.r2_bytes_used, numberValue(archive?.used_bytes)),
      quota_bytes: quota,
      archived_files: numberValue(archive?.archived_files),
      source_only_files: numberValue(archive?.source_only_files),
      error_files: numberValue(archive?.error_files),
    },
    sync: {
      last_started_at: nullableString(sync?.last_started_at),
      last_success_at: nullableString(sync?.last_success_at),
      last_error: nullableString(sync?.last_error),
    },
  };
}

export async function queryRunDetail(env: Env, runId: number): Promise<RunDetail | null> {
  const run = await env.DB.prepare("SELECT * FROM runs WHERE run_id = ?").bind(runId).first<Row>();
  if (!run) return null;
  const [jobs, artifacts, results, sync] = await Promise.all([
    env.DB.prepare("SELECT * FROM jobs WHERE run_id = ? ORDER BY started_at ASC, job_id ASC").bind(runId).all<Row>(),
    env.DB.prepare("SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at DESC, artifact_id DESC").bind(runId).all<Row>(),
    env.DB.prepare("SELECT * FROM results WHERE run_id = ? ORDER BY captured_at DESC, result_id ASC").bind(runId).all<Row>(),
    env.DB.prepare("SELECT last_success_at FROM sync_state WHERE key = 'default'").first<Row>(),
  ]);
  return { schema_version: 1, stale: syncIsStale(sync), run: toRun(run), jobs: rows(jobs).map(toJob), artifacts: rows(artifacts).map(toArtifact), results: rows(results).map(toResult) };
}

export async function queryWorkflows(env: Env) {
  const [result, sync] = await Promise.all([
    env.DB.prepare("SELECT * FROM workflows ORDER BY last_seen_at DESC, name ASC").all<Row>(),
    env.DB.prepare("SELECT last_success_at FROM sync_state WHERE key = 'default'").first<Row>(),
  ]);
  return { schema_version: 1 as const, items: rows(result).map(toWorkflow), next_cursor: null, stale: syncIsStale(sync) };
}

export async function queryArtifacts(env: Env, params: URLSearchParams) {
  const limit = pageLimit(params, 25);
  const cursor = decodeCursor(params.get("cursor"));
  const conditions: string[] = [];
  const bindings: unknown[] = [];
  if (params.get("archive_state")) { conditions.push("archive_state = ?"); bindings.push(params.get("archive_state")); }
  if (params.get("run_id")) {
    const runId = Number(params.get("run_id"));
    if (!Number.isSafeInteger(runId) || runId <= 0) throw new Error("invalid run_id");
    conditions.push("run_id = ?");
    bindings.push(runId);
  }
  if (params.get("q")) { conditions.push("name LIKE ?"); bindings.push("%" + params.get("q") + "%"); }
  if (cursor) {
    conditions.push("(created_at < ? OR (created_at = ? AND artifact_id < ?))");
    bindings.push(cursor.updated_at, cursor.updated_at, cursor.run_id);
  }
  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  const [result, sync] = await Promise.all([
    env.DB.prepare("SELECT * FROM artifacts " + where + " ORDER BY created_at DESC, artifact_id DESC LIMIT ?").bind(...bindings, limit + 1).all<Row>(),
    env.DB.prepare("SELECT last_success_at FROM sync_state WHERE key = 'default'").first<Row>(),
  ]);
  const found = rows(result);
  const items = found.slice(0, limit).map(toArtifact);
  const last = items[items.length - 1];
  return { schema_version: 1 as const, items, next_cursor: found.length > limit && last ? encodeCursor(last.created_at, last.artifact_id) : null, stale: syncIsStale(sync) };
}

export async function queryResults(env: Env, params: URLSearchParams) {
  const limit = pageLimit(params, 50);
  const cursor = decodeResultCursor(params.get("cursor"));
  const conditions: string[] = [];
  const bindings: unknown[] = [];
  for (const key of ["metric_key", "phase", "parser_key", "result_kind", "status"]) {
    if (params.get(key)) { conditions.push(`${key} = ?`); bindings.push(params.get(key)); }
  }
  if (cursor) {
    conditions.push("(captured_at < ? OR (captured_at = ? AND result_id > ?))");
    bindings.push(cursor.captured_at, cursor.captured_at, cursor.result_id);
  }
  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  const [result, sync] = await Promise.all([
    env.DB.prepare("SELECT * FROM results " + where + " ORDER BY captured_at DESC, result_id ASC LIMIT ?").bind(...bindings, limit + 1).all<Row>(),
    env.DB.prepare("SELECT last_success_at FROM sync_state WHERE key = 'default'").first<Row>(),
  ]);
  const found = rows(result);
  const items = found.slice(0, limit).map(toResult);
  const last = items[items.length - 1];
  return { schema_version: 1 as const, items, next_cursor: found.length > limit && last ? encodeResultCursor(last.captured_at, last.result_id) : null, stale: syncIsStale(sync) };
}

export async function queryHealth(env: Env, version: string) {
  const overview = await queryOverview(env);
  return { schema_version: 1 as const, ok: true, version, generated_at: overview.generated_at, stale: overview.stale, sync: overview.sync, archive: overview.archive };
}
