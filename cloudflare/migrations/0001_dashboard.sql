CREATE TABLE IF NOT EXISTS workflows (
  workflow_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  state TEXT NOT NULL,
  triggers_json TEXT NOT NULL DEFAULT '[]',
  parser_key TEXT NOT NULL DEFAULT 'generic',
  parser_status TEXT NOT NULL DEFAULT 'generic',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  run_count INTEGER NOT NULL DEFAULT 0,
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY,
  workflow_id INTEGER NOT NULL,
  workflow_name TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  conclusion TEXT,
  event TEXT NOT NULL,
  branch TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  actor TEXT NOT NULL,
  run_number INTEGER NOT NULL,
  run_attempt INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  duration_seconds INTEGER,
  html_url TEXT NOT NULL,
  parser_status TEXT NOT NULL DEFAULT 'unclassified',
  artifact_count INTEGER NOT NULL DEFAULT 0,
  result_count INTEGER NOT NULL DEFAULT 0,
  raw_manifest_key TEXT,
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  job_id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  conclusion TEXT,
  started_at TEXT,
  completed_at TEXT,
  duration_seconds INTEGER,
  runner_name TEXT,
  html_url TEXT NOT NULL,
  steps_json TEXT NOT NULL DEFAULT '[]',
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  expired INTEGER NOT NULL DEFAULT 0,
  archive_state TEXT NOT NULL DEFAULT 'indexed',
  archive_key TEXT,
  content_type TEXT,
  parser_status TEXT NOT NULL DEFAULT 'unclassified',
  source_url TEXT NOT NULL,
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
  result_id TEXT PRIMARY KEY,
  run_id INTEGER NOT NULL,
  artifact_id INTEGER,
  result_kind TEXT NOT NULL,
  parser_key TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  status TEXT NOT NULL,
  metric_key TEXT NOT NULL,
  metric_value REAL,
  value_text TEXT,
  unit TEXT,
  phase TEXT,
  period_start TEXT,
  period_end TEXT,
  baseline TEXT,
  cost_model TEXT,
  candidate_id TEXT,
  passed INTEGER,
  source_path TEXT,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
  key TEXT PRIMARY KEY,
  cursor_json TEXT NOT NULL DEFAULT '{}',
  last_started_at TEXT,
  last_success_at TEXT,
  last_error TEXT,
  runs_seen INTEGER NOT NULL DEFAULT 0,
  jobs_seen INTEGER NOT NULL DEFAULT 0,
  artifacts_seen INTEGER NOT NULL DEFAULT 0,
  results_seen INTEGER NOT NULL DEFAULT 0,
  r2_bytes_used INTEGER NOT NULL DEFAULT 0,
  quota_bytes INTEGER NOT NULL DEFAULT 7516192768,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_updated ON runs(updated_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, conclusion);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_state ON artifacts(archive_state);
CREATE INDEX IF NOT EXISTS idx_results_metric_phase ON results(metric_key, phase);
CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id, captured_at DESC);
