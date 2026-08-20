import { demoArtifacts, demoHealth, demoOverview, demoResults, demoRunDetail, demoRuns, demoWorkflows } from "./fixtures";
import type { DashboardApi, Health, Overview, Page, ResultMetric, Run, RunDetail, Artifact, Workflow } from "./types";

function dashboardPrefix(): string {
  if (typeof window === "undefined") return "";
  const parts = window.location.pathname.split("/").filter(Boolean);
  const secretIndex = parts.indexOf("s");
  if (secretIndex >= 0 && parts[secretIndex + 1]) return `/s/${parts[secretIndex + 1]}`;
  return "";
}

export function archiveUrl(key: string): string {
  const prefix = dashboardPrefix();
  const encodedKey = key.split("/").map((part) => encodeURIComponent(part)).join("/");
  return prefix + "/api/archive/" + encodedKey;
}

function demoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "true";
}

function toQuery(filters?: Record<string, string | number | null>): string {
  if (!filters) return "";
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export class DashboardClient implements DashboardApi {
  private readonly prefix: string;
  private readonly demo: boolean;

  constructor(prefix = dashboardPrefix(), demo = demoMode()) {
    this.prefix = prefix;
    this.demo = demo;
  }

  private async get<T>(path: string, filters?: Record<string, string | number | null>): Promise<T> {
    if (this.demo) return this.demoResponse<T>(path, filters);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetch(`${this.prefix}/api/${path}${toQuery(filters)}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
      return response.json() as Promise<T>;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  private demoResponse<T>(path: string, filters?: Record<string, string | number | null>): T {
    if (path === "overview") return demoOverview as T;
    if (path === "health") return demoHealth as T;
    if (path === "runs") {
      const status = filters?.status;
      const query = String(filters?.q || "").toLowerCase();
      const items = demoRuns.items.filter((run) => {
        const matchesStatus = !status || run.status === status || run.conclusion === status;
        const haystack = (run.name + " " + run.workflow_name + " " + run.branch + " " + run.actor).toLowerCase();
        return matchesStatus && (!query || haystack.includes(query));
      });
      return { ...demoRuns, items } as T;
    }
    if (path.startsWith("runs/")) return demoRunDetail as T;
    if (path === "results") return demoResults as T;
    if (path === "artifacts") return demoArtifacts as T;
    if (path === "workflows") return demoWorkflows as T;
    throw new Error(`No demo response for ${path}`);
  }

  getOverview(): Promise<Overview> { return this.get<Overview>("overview"); }
  getRuns(filters?: Record<string, string | number | null>): Promise<Page<Run>> { return this.get<Page<Run>>("runs", filters); }
  getRunDetail(runId: number): Promise<RunDetail> { return this.get<RunDetail>(`runs/${runId}`); }
  getResults(filters?: Record<string, string | number | null>): Promise<Page<ResultMetric>> { return this.get<Page<ResultMetric>>("results", filters); }
  getArtifacts(filters?: Record<string, string | number | null>): Promise<Page<Artifact>> { return this.get<Page<Artifact>>("artifacts", filters); }
  getWorkflows(): Promise<Page<Workflow>> { return this.get<Page<Workflow>>("workflows"); }
  getHealth(): Promise<Health> { return this.get<Health>("health"); }
}

export const dashboardClient = new DashboardClient();
