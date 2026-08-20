import { authorizeSync } from "./auth";
import type { Env } from "./env";
import { archiveQuotaBytes } from "./env";

type UnknownRecord = Record<string, unknown>;

export interface SyncArchive {
  key: string;
  content_base64: string;
  content_type: string;
  size_bytes: number;
  sha256?: string;
}

export interface SyncBatch {
  schema_version: 1;
  captured_at: string;
  cursor: UnknownRecord;
  next_cursor: UnknownRecord | null;
  workflows: UnknownRecord[];
  runs: UnknownRecord[];
  jobs: UnknownRecord[];
  artifacts: UnknownRecord[];
  results: UnknownRecord[];
  archives: SyncArchive[];
}

export interface SyncError {
  schema_version: 1;
  captured_at: string;
  cursor?: UnknownRecord | null;
  error: string;
}

function text(value: unknown, fallback = ""): string {
  return value === null || value === undefined ? fallback : String(value);
}

function integer(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : fallback;
}

function nullableInteger(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function nullableText(value: unknown): string | null {
  return value === null || value === undefined || value === "" ? null : String(value);
}

function jsonText(value: unknown, fallback: unknown): string {
  try {
    return JSON.stringify(value === undefined ? fallback : value);
  } catch {
    return JSON.stringify(fallback);
  }
}

function booleanInt(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  return value === true || value === 1 || value === "1" || value === "true" ? 1 : 0;
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function assertBatch(value: unknown): SyncBatch {
  if (!value || typeof value !== "object") throw new Error("sync body must be an object");
  const body = value as UnknownRecord;
  const arrays = ["workflows", "runs", "jobs", "artifacts", "results", "archives"];
  if (body.schema_version !== 1) throw new Error("unsupported sync schema");
  for (const key of arrays) {
    if (!Array.isArray(body[key])) throw new Error(`${key} must be an array`);
    if ((body[key] as unknown[]).length > 500) throw new Error(`${key} batch too large`);
  }
  let encodedArchiveBytes = 0;
  for (const item of body.archives as UnknownRecord[]) {
    if (typeof item.content_base64 !== "string" || item.content_base64.length > 12 * 1024 * 1024) throw new Error("archive payload too large");
    encodedArchiveBytes += item.content_base64.length;
  }
  if (encodedArchiveBytes > 32 * 1024 * 1024) throw new Error("archive batch too large");
  return body as unknown as SyncBatch;
}

function assertSyncError(value: unknown): SyncError {
  if (!value || typeof value !== "object") throw new Error("sync error body must be an object");
  const body = value as UnknownRecord;
  if (body.schema_version !== 1) throw new Error("unsupported sync error schema");
  if (typeof body.error !== "string" || !body.error.trim()) throw new Error("sync error message is required");
  if (body.error.length > 2_000) throw new Error("sync error message too long");
  return body as unknown as SyncError;
}

export async function recordSyncError(env: Env, value: unknown): Promise<Record<string, unknown>> {
  const body = assertSyncError(value);
  const capturedAt = typeof body.captured_at === "string" && body.captured_at ? body.captured_at : new Date().toISOString();
  await env.DB.prepare("INSERT INTO sync_state (key, cursor_json, last_started_at, last_success_at, last_error, runs_seen, jobs_seen, artifacts_seen, results_seen, r2_bytes_used, quota_bytes, updated_at) VALUES ('default', ?, ?, NULL, ?, 0, 0, 0, 0, 0, ?, ?) ON CONFLICT(key) DO UPDATE SET cursor_json=excluded.cursor_json, last_started_at=excluded.last_started_at, last_error=excluded.last_error, updated_at=excluded.updated_at")
    .bind(jsonText(body.cursor || {}, {}), capturedAt, body.error.trim(), archiveQuotaBytes(env), capturedAt)
    .run();
  return { schema_version: 1, ok: false, last_error: body.error.trim(), captured_at: capturedAt };
}

async function executeInChunks(env: Env, statements: D1PreparedStatement[]): Promise<void> {
  for (let offset = 0; offset < statements.length; offset += 100) {
    await env.DB.batch(statements.slice(offset, offset + 100));
  }
}

export async function ingestBatch(env: Env, value: unknown): Promise<Record<string, unknown>> {
  const batch = assertBatch(value);
  const state = await env.DB.prepare("SELECT * FROM sync_state WHERE key = 'default'").first<UnknownRecord>();
  let usedBytes = integer(state?.r2_bytes_used);
  const quotaBytes = integer(state?.quota_bytes, archiveQuotaBytes(env));
  let storedCursor: UnknownRecord = {};
  try {
    const parsed = JSON.parse(String(state?.cursor_json || "{}"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) storedCursor = parsed as UnknownRecord;
  } catch {
    storedCursor = {};
  }
  const storedPage = integer(storedCursor.page);
  const batchPage = integer(batch.cursor?.page, 1);
  const checkpoint = batchPage === 1 && storedPage > 1
    ? storedCursor
    : (batch.next_cursor || { page: 1 });
  const archiveStates = new Map<number, { state: string; key: string | null }>();
  const markArchive = (archive: SyncArchive, stateValue: string, key: string | null = null) => {
    const idMatch = archive.key.match(/\/artifacts\/(\d+)\//);
    if (idMatch) archiveStates.set(Number(idMatch[1]), { state: stateValue, key });
  };
  let archivedFiles = 0;
  let quotaBlockedFiles = 0;
  let archiveErrors = 0;

  for (const archive of batch.archives) {
    if (!archive.key) {
      archiveErrors += 1;
      continue;
    }
    if (archive.size_bytes < 0) {
      markArchive(archive, "error");
      archiveErrors += 1;
      continue;
    }
    try {
      const bytes = decodeBase64(archive.content_base64);
      if (bytes.byteLength > 8 * 1024 * 1024) {
        markArchive(archive, "source_only");
        continue;
      }
      if (usedBytes + bytes.byteLength > quotaBytes) {
        markArchive(archive, "quota_blocked");
        quotaBlockedFiles += 1;
        continue;
      }
      const existing = await env.ARCHIVE.head(archive.key);
      if (existing) {
        markArchive(archive, "archived", archive.key);
        continue;
      }
      await env.ARCHIVE.put(archive.key, bytes, { httpMetadata: { contentType: archive.content_type || "application/octet-stream" } });
      usedBytes += bytes.byteLength;
      archivedFiles += 1;
      markArchive(archive, "archived", archive.key);
    } catch {
      markArchive(archive, "error");
      archiveErrors += 1;
    }
  }

  const statements: D1PreparedStatement[] = [];
  for (const workflow of batch.workflows) {
    statements.push(env.DB.prepare(`INSERT INTO workflows (workflow_id, name, path, state, triggers_json, parser_key, parser_status, first_seen_at, last_seen_at, run_count, success_count, failure_count)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(workflow_id) DO UPDATE SET name=excluded.name, path=excluded.path, state=excluded.state, triggers_json=excluded.triggers_json, parser_key=excluded.parser_key, parser_status=excluded.parser_status, last_seen_at=excluded.last_seen_at, run_count=excluded.run_count, success_count=excluded.success_count, failure_count=excluded.failure_count`)
      .bind(integer(workflow.workflow_id), text(workflow.name, "Unknown workflow"), text(workflow.path), text(workflow.state, "unknown"), jsonText(workflow.triggers, []), text(workflow.parser_key, "generic"), text(workflow.parser_status, "generic"), text(workflow.first_seen_at, batch.captured_at), text(workflow.last_seen_at, batch.captured_at), integer(workflow.run_count), integer(workflow.success_count), integer(workflow.failure_count)));
  }
  for (const run of batch.runs) {
    statements.push(env.DB.prepare(`INSERT INTO runs (run_id, workflow_id, workflow_name, name, status, conclusion, event, branch, commit_sha, actor, run_number, run_attempt, created_at, updated_at, started_at, completed_at, duration_seconds, html_url, parser_status, artifact_count, result_count, raw_manifest_key, captured_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(run_id) DO UPDATE SET workflow_id=excluded.workflow_id, workflow_name=excluded.workflow_name, name=excluded.name, status=excluded.status, conclusion=excluded.conclusion, event=excluded.event, branch=excluded.branch, commit_sha=excluded.commit_sha, actor=excluded.actor, run_number=excluded.run_number, run_attempt=excluded.run_attempt, created_at=excluded.created_at, updated_at=excluded.updated_at, started_at=excluded.started_at, completed_at=excluded.completed_at, duration_seconds=excluded.duration_seconds, html_url=excluded.html_url, parser_status=excluded.parser_status, artifact_count=excluded.artifact_count, result_count=excluded.result_count, raw_manifest_key=excluded.raw_manifest_key, captured_at=excluded.captured_at`)
      .bind(integer(run.run_id), integer(run.workflow_id), text(run.workflow_name, "Unknown workflow"), text(run.name, "Unnamed run"), text(run.status, "unknown"), nullableText(run.conclusion), text(run.event, "unknown"), text(run.branch, "unknown"), text(run.commit_sha), text(run.actor, "unknown"), integer(run.run_number), integer(run.run_attempt, 1), text(run.created_at, batch.captured_at), text(run.updated_at, batch.captured_at), nullableText(run.started_at), nullableText(run.completed_at), nullableInteger(run.duration_seconds), text(run.html_url), text(run.parser_status, "unclassified"), integer(run.artifact_count), integer(run.result_count), nullableText(run.raw_manifest_key), text(run.captured_at, batch.captured_at)));
  }
  for (const job of batch.jobs) {
    statements.push(env.DB.prepare(`INSERT INTO jobs (job_id, run_id, name, status, conclusion, started_at, completed_at, duration_seconds, runner_name, html_url, steps_json, captured_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(job_id) DO UPDATE SET run_id=excluded.run_id, name=excluded.name, status=excluded.status, conclusion=excluded.conclusion, started_at=excluded.started_at, completed_at=excluded.completed_at, duration_seconds=excluded.duration_seconds, runner_name=excluded.runner_name, html_url=excluded.html_url, steps_json=excluded.steps_json, captured_at=excluded.captured_at`)
      .bind(integer(job.job_id), integer(job.run_id), text(job.name, "Unnamed job"), text(job.status, "unknown"), nullableText(job.conclusion), nullableText(job.started_at), nullableText(job.completed_at), nullableInteger(job.duration_seconds), nullableText(job.runner_name), text(job.html_url), jsonText(job.steps, []), text(job.captured_at, batch.captured_at)));
  }
  for (const artifact of batch.artifacts) {
    const id = integer(artifact.artifact_id);
    const stored = archiveStates.get(id);
    const stateValue = stored?.state || text(artifact.archive_state, "indexed");
    statements.push(env.DB.prepare(`INSERT INTO artifacts (artifact_id, run_id, name, size_bytes, created_at, expires_at, expired, archive_state, archive_key, content_type, parser_status, source_url, captured_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(artifact_id) DO UPDATE SET run_id=excluded.run_id, name=excluded.name, size_bytes=excluded.size_bytes, created_at=excluded.created_at, expires_at=excluded.expires_at, expired=excluded.expired, archive_state=excluded.archive_state, archive_key=excluded.archive_key, content_type=excluded.content_type, parser_status=excluded.parser_status, source_url=excluded.source_url, captured_at=excluded.captured_at`)
      .bind(id, integer(artifact.run_id), text(artifact.name, `artifact-${id}`), integer(artifact.size_bytes), text(artifact.created_at, batch.captured_at), nullableText(artifact.expires_at), booleanInt(artifact.expired) || 0, stateValue, stored?.key || nullableText(artifact.archive_key), nullableText(artifact.content_type), text(artifact.parser_status, "unclassified"), text(artifact.source_url), text(artifact.captured_at, batch.captured_at)));
  }
  const parsedArtifactIds = new Set(
    batch.results
      .map((result) => integer(result.artifact_id))
      .filter((artifactId) => artifactId > 0),
  );
  for (const artifactId of parsedArtifactIds) {
    // A parser batch can be capped. Replace the previous projection for the
    // artifact so reingestion cannot leave stale or colliding metric rows.
    statements.push(env.DB.prepare("DELETE FROM results WHERE artifact_id = ?").bind(artifactId));
  }
  for (const result of batch.results) {
    statements.push(env.DB.prepare(`INSERT INTO results (result_id, run_id, artifact_id, result_kind, parser_key, parser_version, status, metric_key, metric_value, value_text, unit, phase, period_start, period_end, baseline, cost_model, candidate_id, passed, source_path, evidence_json, captured_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(result_id) DO UPDATE SET run_id=excluded.run_id, artifact_id=excluded.artifact_id, result_kind=excluded.result_kind, parser_key=excluded.parser_key, parser_version=excluded.parser_version, status=excluded.status, metric_key=excluded.metric_key, metric_value=excluded.metric_value, value_text=excluded.value_text, unit=excluded.unit, phase=excluded.phase, period_start=excluded.period_start, period_end=excluded.period_end, baseline=excluded.baseline, cost_model=excluded.cost_model, candidate_id=excluded.candidate_id, passed=excluded.passed, source_path=excluded.source_path, evidence_json=excluded.evidence_json, captured_at=excluded.captured_at`)
      .bind(text(result.result_id), integer(result.run_id), nullableInteger(result.artifact_id), text(result.result_kind, "unknown"), text(result.parser_key, "generic"), text(result.parser_version, "unknown"), text(result.status, "unclassified"), text(result.metric_key, "unknown"), result.metric_value === null || result.metric_value === undefined ? null : Number(result.metric_value), nullableText(result.value_text), nullableText(result.unit), nullableText(result.phase), nullableText(result.period_start), nullableText(result.period_end), nullableText(result.baseline), nullableText(result.cost_model), nullableText(result.candidate_id), booleanInt(result.passed), nullableText(result.source_path), jsonText(result.evidence, {}), text(result.captured_at, batch.captured_at)));
  }
  statements.push(env.DB.prepare(`INSERT INTO sync_state (key, cursor_json, last_started_at, last_success_at, last_error, runs_seen, jobs_seen, artifacts_seen, results_seen, r2_bytes_used, quota_bytes, updated_at)
    VALUES ('default', ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET cursor_json=excluded.cursor_json, last_started_at=excluded.last_started_at, last_success_at=excluded.last_success_at, last_error=NULL, runs_seen=sync_state.runs_seen + excluded.runs_seen, jobs_seen=sync_state.jobs_seen + excluded.jobs_seen, artifacts_seen=sync_state.artifacts_seen + excluded.artifacts_seen, results_seen=sync_state.results_seen + excluded.results_seen, r2_bytes_used=excluded.r2_bytes_used, quota_bytes=excluded.quota_bytes, updated_at=excluded.updated_at`)
    .bind(jsonText(checkpoint, {}), text(batch.captured_at), text(batch.captured_at), batch.runs.length, batch.jobs.length, batch.artifacts.length, batch.results.length, usedBytes, quotaBytes, text(batch.captured_at)));

  for (const workflow of batch.workflows) {
    statements.push(env.DB.prepare("UPDATE workflows SET run_count = (SELECT COUNT(*) FROM runs WHERE workflow_id = ?), success_count = (SELECT COUNT(*) FROM runs WHERE workflow_id = ? AND conclusion = 'success'), failure_count = (SELECT COUNT(*) FROM runs WHERE workflow_id = ? AND conclusion IN ('failure', 'timed_out')) WHERE workflow_id = ?")
      .bind(integer(workflow.workflow_id), integer(workflow.workflow_id), integer(workflow.workflow_id), integer(workflow.workflow_id)));
  }
  for (const run of batch.runs) {
    statements.push(env.DB.prepare("UPDATE runs SET artifact_count = (SELECT COUNT(*) FROM artifacts WHERE run_id = ?), result_count = (SELECT COUNT(*) FROM results WHERE run_id = ?) WHERE run_id = ?")
      .bind(integer(run.run_id), integer(run.run_id), integer(run.run_id)));
  }
  await executeInChunks(env, statements);
  return {
    schema_version: 1,
    ok: true,
    runs: batch.runs.length,
    jobs: batch.jobs.length,
    artifacts: batch.artifacts.length,
    results: batch.results.length,
    archived_files: archivedFiles,
    quota_blocked_files: quotaBlockedFiles,
    archive_errors: archiveErrors,
    next_cursor: batch.next_cursor,
    r2_bytes_used: usedBytes,
    quota_bytes: quotaBytes,
  };
}

export { assertBatch, assertSyncError };
