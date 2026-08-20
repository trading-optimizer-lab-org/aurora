import type { D1Database, Fetcher, R2Bucket } from "@cloudflare/workers-types";

export interface Env {
  ASSETS: Fetcher;
  DB: D1Database;
  ARCHIVE: R2Bucket;
  DASHBOARD_LINK_SECRET: string;
  DASHBOARD_SYNC_TOKEN?: string;
  REPO_OWNER: string;
  REPO_NAME: string;
  ARCHIVE_QUOTA_BYTES: string;
  APP_VERSION: string;
}

export function archiveQuotaBytes(env: Env): number {
  const value = Number.parseInt(env.ARCHIVE_QUOTA_BYTES || "7516192768", 10);
  return Number.isFinite(value) && value > 0 ? value : 7516192768;
}
