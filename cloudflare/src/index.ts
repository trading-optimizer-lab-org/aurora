import { authorizePath } from "./auth";
import { handleApi, responseHeaders } from "./api";
import type { Env } from "./env";

async function serveArchive(request: Request, env: Env, suffix: string): Promise<Response> {
  const prefix = suffix.startsWith("/api/archive/") ? "/api/archive/" : "/archive/";
  let key = "";
  try {
    key = decodeURIComponent(suffix.slice(prefix.length));
  } catch {
    return new Response("Not found", { status: 404 });
  }
  if (!key || key.includes("..") || key.includes("\\")) return new Response("Not found", { status: 404 });
  const object = await env.ARCHIVE.get(key);
  if (!object || !object.body) return new Response("Not found", { status: 404 });
  const headers = new Headers(responseHeaders());
  headers.set("Content-Type", object.httpMetadata?.contentType || "application/octet-stream");
  headers.set("Cache-Control", "private, max-age=60");
  if (object.size !== undefined) headers.set("Content-Length", String(object.size));
  return new Response(object.body, { headers });
}

const worker: ExportedHandler<Env> = {
  async fetch(request, env) {
    const url = new URL(request.url);
    const auth = authorizePath(url.pathname, env.DASHBOARD_LINK_SECRET);
    if (!auth.ok || !auth.suffix) return new Response("Not found", { status: 404 });
    if (auth.suffix.startsWith("/archive/") || auth.suffix.startsWith("/api/archive/")) return serveArchive(request, env, auth.suffix);
    if (auth.suffix.startsWith("/api/") || auth.suffix.startsWith("/internal/")) {
      return handleApi(request, env, auth.suffix);
    }

    const assetUrl = new URL(request.url);
    assetUrl.pathname = auth.suffix === "/" ? "/" : auth.suffix;
    const assetResponse = await env.ASSETS.fetch(new Request(assetUrl, request));
    const headers = new Headers(assetResponse.headers);
    for (const [key, value] of responseHeaders()) headers.set(key, value);
    return new Response(assetResponse.body, { status: assetResponse.status, headers });
  },
};

export default worker;
