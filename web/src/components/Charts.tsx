import { useState } from "react";
import type { Job, JobLogs, Run } from "../types";
import { formatDuration, statusTone } from "../format";

export function ConclusionBars({ values }: { values: { label: string; count: number }[] }) {
  const max = Math.max(...values.map((value) => value.count), 1);
  return <div className="bar-chart" aria-label="Distribución de conclusiones">
    {values.map((value) => <div className="bar-row" key={value.label}>
      <div className="bar-label"><span>{value.label}</span><strong>{value.count}</strong></div>
      <div className="bar-track"><span className={"bar-fill bar-" + statusTone(value.label)} style={{ width: Math.max(4, (value.count / max) * 100) + "%" }} /></div>
    </div>)}
  </div>;
}

export function RunSparkline({ runs }: { runs: Run[] }) {
  const points = runs.slice().reverse().map((run, index) => {
    const value = run.duration_seconds || 0;
    return { x: 8 + index * (184 / Math.max(1, runs.length - 1)), y: 76 - Math.min(62, (value / Math.max(...runs.map((item) => item.duration_seconds || 1))) * 62) };
  });
  const path = points.map((point, index) => (index === 0 ? "M" : "L") + point.x.toFixed(1) + "," + point.y.toFixed(1)).join(" ");
  const lastPoint = points.length ? points[points.length - 1] : undefined;
  return <svg className="sparkline" viewBox="0 0 200 84" role="img" aria-label="Duración de las ejecuciones recientes"><path className="spark-grid" d="M8 76H192M8 44H192M8 12H192" /><path className="spark-line" d={path || "M8 76H192"} /><circle className="spark-point" cx={lastPoint?.x || 192} cy={lastPoint?.y || 76} r="3" /></svg>;
}

export function JobTimeline({ jobs, onLoadLogs }: { jobs: Job[]; onLoadLogs?: (jobId: number) => Promise<JobLogs> }) {
  if (!jobs.length) return <div className="muted">No hay jobs registrados.</div>;
  return <div className="job-timeline">
    {jobs.map((job) => <div className="job-block" key={job.job_id}>
      <div className="job-row">
        <div className={"job-marker marker-" + statusTone(job.conclusion || job.status)} />
        <div className="job-main"><strong>{job.name}</strong><span>{job.runner_name || "runner no indicado"}</span></div>
        <StatusLabel status={job.conclusion || job.status} />
        <span className="job-duration">{formatDuration(job.duration_seconds)}</span>
        <a className="source-link" href={job.html_url} target="_blank" rel="noreferrer">GitHub ↗</a>
      </div>
      {job.steps.length ? <details className="job-steps"><summary>{job.steps.length} pasos</summary><div className="step-list">{job.steps.map((step) => <div className="step-line" key={step.number}><span className={"step-dot marker-" + statusTone(step.conclusion || step.status)} /><span>{step.name}</span><StatusLabel status={step.conclusion || step.status} /></div>)}</div></details> : null}
      {onLoadLogs ? <JobLogViewer jobId={job.job_id} onLoadLogs={onLoadLogs} /> : null}
    </div>)}
  </div>;
}

function JobLogViewer({ jobId, onLoadLogs }: { jobId: number; onLoadLogs: (jobId: number) => Promise<JobLogs> }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (content !== null || loading) return;
    setLoading(true);
    setError(null);
    try {
      const logs = await onLoadLogs(jobId);
      setContent(logs.content);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "No se pudieron cargar los logs");
    } finally {
      setLoading(false);
    }
  };

  return <div className="job-log-viewer"><button className="text-button job-log-toggle" type="button" onClick={() => void toggle()} aria-expanded={open}>{open ? "Ocultar logs" : "Ver logs"}</button>{open ? <div className="job-log-body">{loading ? <span className="muted">Cargando logs…</span> : error ? <span className="log-error">{error}</span> : <pre className="job-log-content">{content}</pre>}</div> : null}</div>;
}

function StatusLabel({ status }: { status: string | null }) {
  return <span className={"timeline-status status-text-" + statusTone(status)}>{status || "—"}</span>;
}
