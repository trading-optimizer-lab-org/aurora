import { authorizeSync } from "./auth";
import { queryArtifacts, queryHealth, queryJob, queryJobLogs, queryOverview, queryResults, queryRunDetail, queryRuns, querySyncState, queryWorkflows } from "./db";
import type { Env } from "./env";
import { ingestBatch, recordSyncError } from "./sync";

function json(data: unknown, status = 200, extra: HeadersInit = {}): Response {
  const headers = new Headers(extra);
  headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Cache-Control", "no-store");
  headers.set("Referrer-Policy", "no-referrer");
  return new Response(JSON.stringify(data), { status, headers });
}

function error(message: string, status: number): Response {
  return json({ schema_version: 1, error: message }, status);
}

async function read<T>(producer: () => Promise<T>): Promise<Response> {
  try {
    return json(await producer());
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : "service unavailable";
    if (["run not found", "job not found", "job logs not found"].includes(message)) return error(message, 404);
    return message.startsWith("invalid ") ? error(message, 400) : error("service unavailable", 503);
  }
}

export async function handleApi(request: Request, env: Env, apiPath: string): Promise<Response> {
  const url = new URL(request.url);
  if (apiPath === "/api/health" && request.method === "GET") return read(() => queryHealth(env, env.APP_VERSION));
  if (apiPath === "/api/overview" && request.method === "GET") return read(() => queryOverview(env));
  if (apiPath === "/api/workflows" && request.method === "GET") return read(() => queryWorkflows(env));
  if (apiPath === "/api/runs" && request.method === "GET") return read(() => queryRuns(env, url.searchParams));
  if (apiPath.startsWith("/api/runs/") && request.method === "GET") {
    const id = Number(apiPath.slice("/api/runs/".length));
    if (!Number.isSafeInteger(id) || id <= 0) return error("invalid run id", 400);
    return read(async () => {
      const detail = await queryRunDetail(env, id);
      if (!detail) throw new Error("run not found");
      return detail;
    });
  }
  if (apiPath.startsWith("/api/jobs/") && request.method === "GET") {
    const suffix = apiPath.slice("/api/jobs/".length);
    const [rawId, action] = suffix.split("/");
    const id = Number(rawId);
    if (!Number.isSafeInteger(id) || id <= 0 || (action && action !== "logs")) return error("invalid job id", 400);
    if (action === "logs") return read(() => queryJobLogs(env, id));
    return read(() => queryJob(env, id));
  }
  if (apiPath === "/api/artifacts" && request.method === "GET") return read(() => queryArtifacts(env, url.searchParams));
  if (apiPath === "/api/results" && request.method === "GET") return read(() => queryResults(env, url.searchParams));
  if (apiPath === "/internal/sync/state" && request.method === "GET") {
    if (!authorizeSync(request, env.DASHBOARD_SYNC_TOKEN)) return error("not found", 404);
    return read(() => querySyncState(env));
  }
  if (apiPath === "/internal/sync/batch" && request.method === "POST") {
    if (!authorizeSync(request, env.DASHBOARD_SYNC_TOKEN)) return error("not found", 404);
    try {
      const contentLength = Number(request.headers.get("Content-Length") || 0);
      if (contentLength > 40 * 1024 * 1024) return error("sync body too large", 413);
      const body = await request.json();
      return json(await ingestBatch(env, body));
    } catch (exc) {
      return error(exc instanceof Error ? exc.message : "invalid sync batch", 400);
    }
  }
  if (apiPath === "/internal/sync/error" && request.method === "POST") {
    if (!authorizeSync(request, env.DASHBOARD_SYNC_TOKEN)) return error("not found", 404);
    try {
      const contentLength = Number(request.headers.get("Content-Length") || 0);
      if (contentLength > 100_000) return error("sync error body too large", 413);
      const body = await request.json();
      return json(await recordSyncError(env, body));
    } catch (exc) {
      return error(exc instanceof Error ? exc.message : "invalid sync error", 400);
    }
  }
  if (apiPath.startsWith("/internal/")) return error("not found", 404);
  return error("not found", 404);
}

export function responseHeaders(): Headers {
  const headers = new Headers();
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'");
  return headers;
}
