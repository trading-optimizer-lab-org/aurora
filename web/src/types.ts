export type Status = string;

export type ArchiveState =
  | "indexed"
  | "archived"
  | "source_only"
  | "expired"
  | "quota_blocked"
  | "error";

export type ParserStatus = "specialized" | "generic" | "unclassified" | "error";
export type CompletionType = "actual" | "estimated" | "unknown";
export type CompletionBasis = "workflow" | "global" | "actual" | "none";

export interface Page<T> {
  schema_version: 1;
  items: T[];
  next_cursor: string | null;
  stale: boolean;
  total_count?: number;
}

export interface Workflow {
  workflow_id: number;
  name: string;
  path: string;
  state: string;
  triggers: string[];
  parser_key: string;
  parser_status: ParserStatus;
  first_seen_at: string;
  last_seen_at: string;
  run_count: number;
  success_count: number;
  failure_count: number;
}

export interface Run {
  run_id: number;
  workflow_id: number;
  workflow_name: string;
  name: string;
  status: Status;
  conclusion: string | null;
  event: string;
  branch: string;
  commit_sha: string;
  actor: string;
  run_number: number;
  run_attempt: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  completion_at: string | null;
  completion_type: CompletionType;
  completion_basis: CompletionBasis;
  html_url: string;
  parser_status: ParserStatus;
  artifact_count: number;
  result_count: number;
}

export interface JobStep {
  name: string;
  status: Status;
  conclusion: string | null;
  number: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface Job {
  job_id: number;
  run_id: number;
  name: string;
  status: Status;
  conclusion: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  runner_name: string | null;
  html_url: string;
  steps: JobStep[];
}

export interface JobLogs {
  schema_version: 1;
  job_id: number;
  content: string;
  content_type: string;
}

export interface Artifact {
  artifact_id: number;
  run_id: number;
  name: string;
  size_bytes: number;
  created_at: string;
  expires_at: string | null;
  expired: boolean;
  archive_state: ArchiveState;
  archive_key: string | null;
  content_type: string | null;
  parser_status: ParserStatus;
  source_url: string;
}

export interface ResultMetric {
  result_id: string;
  run_id: number;
  artifact_id: number | null;
  result_kind: string;
  parser_key: string;
  parser_version: string;
  status: "parsed" | "partial" | "unclassified" | "error";
  metric_key: string;
  metric_value: number | null;
  value_text: string | null;
  unit: string | null;
  phase: string | null;
  period_start: string | null;
  period_end: string | null;
  baseline: string | null;
  cost_model: string | null;
  candidate_id: string | null;
  passed: boolean | null;
  source_path: string | null;
  evidence: Record<string, string | number | boolean | null>;
  captured_at: string;
}

export interface RunDetail {
  schema_version: 1;
  stale: boolean;
  run: Run;
  jobs: Job[];
  artifacts: Artifact[];
  results: ResultMetric[];
}

export interface ConclusionCount {
  label: string;
  count: number;
}

export interface Overview {
  schema_version: 1;
  stale: boolean;
  generated_at: string;
  active_runs: Run[];
  recent_runs: Run[];
  totals: {
    workflows: number;
    runs: number;
    active_runs: number;
    artifacts: number;
    parsed_results: number;
  };
  conclusions: ConclusionCount[];
  archive: {
    used_bytes: number;
    quota_bytes: number;
    archived_files: number;
    source_only_files: number;
    error_files: number;
  };
  sync: {
    last_started_at: string | null;
    last_success_at: string | null;
    last_error: string | null;
  };
}

export interface Health {
  schema_version: 1;
  ok: boolean;
  version: string;
  generated_at: string;
  stale: boolean;
  sync: Overview["sync"];
  archive: Overview["archive"];
}

export interface DashboardApi {
  getOverview(): Promise<Overview>;
  getRuns(filters?: Record<string, string | number | null>): Promise<Page<Run>>;
  getRunDetail(runId: number): Promise<RunDetail>;
  getJobLogs(jobId: number): Promise<JobLogs>;
  getResults(filters?: Record<string, string | number | null>): Promise<Page<ResultMetric>>;
  getArtifacts(filters?: Record<string, string | number | null>): Promise<Page<Artifact>>;
  getWorkflows(): Promise<Page<Workflow>>;
  getHealth(): Promise<Health>;
}
