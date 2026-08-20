import { describe, expect, it } from "vitest";
import { authorizePath, authorizeSync } from "./auth";
import { encodeCursor } from "./db";

describe("dashboard Worker access", () => {
  it("rejects paths without the exact secret segment", () => {
    expect(authorizePath("/s/wrong/api/health", "right").ok).toBe(false);
    expect(authorizePath("/api/health", "right").ok).toBe(false);
  });

  it("accepts the secret and preserves the API suffix", () => {
    expect(authorizePath("/s/right/api/runs", "right")).toEqual({ ok: true, suffix: "/api/runs" });
  });

  it("uses a URL-safe cursor for run pagination", () => {
    const cursor = encodeCursor("2026-08-20T08:00:00Z", 123);
    expect(cursor).not.toContain("+");
    expect(cursor).not.toContain("/");
    expect(cursor).not.toContain("=");
  });

  it("requires the separate ingestion token", () => {
    const request = new Request("https://example.test/internal/sync/batch", { headers: { Authorization: "Bearer sync-secret" } });
    expect(authorizeSync(request, "sync-secret")).toBe(true);
    expect(authorizeSync(request, "other-secret")).toBe(false);
  });
});
