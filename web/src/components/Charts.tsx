import type { Job, Run } from "../types";
import { formatDuration, statusTone } from "../format";

export function ConclusionBars({ values }: { values: { label: string; count: number }[] }) {
  const max = Math.max(...values.map((value) => value.count), 1);
  return <div className="bar-chart" aria-label="Distribución de conclusiones">
    {values.map((value) => <div className="bar-row" key={value.label}>
      <div className="bar-label"><span>{value.label}</span><strong>{value.count}</strong></div>
      <div className="bar-track"><span className={`bar-fill bar-${statusTone(value.label)}`} style={{ width: `${Math.max(4, (value.count / max) * 100)}%` }} /></div>
    </div>)}
  </div>;
}

export function RunSparkline({ runs }: { runs: Run[] }) {
  const points = runs.slice().reverse().map((run, index) => {
    const value = run.duration_seconds || 0;
    return { x: 8 + index * (184 / Math.max(1, runs.length - 1)), y: 76 - Math.min(62, (value / Math.max(...runs.map((item) => item.duration_seconds || 1))) * 62) };
  });
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const lastPoint = points.length ? points[points.length - 1] : undefined;
  return <svg className="sparkline" viewBox="0 0 200 84" role="img" aria-label="Duración de las ejecuciones recientes"><path className="spark-grid" d="M8 76H192M8 44H192M8 12H192" /><path className="spark-line" d={path || "M8 76H192"} /><circle className="spark-point" cx={lastPoint?.x || 192} cy={lastPoint?.y || 76} r="3" /></svg>;
}

export function JobTimeline({ jobs }: { jobs: Job[] }) {
  if (!jobs.length) return <div className="muted">No hay jobs registrados.</div>;
  return <div className="job-timeline">
    {jobs.map((job) => <div className="job-row" key={job.job_id}>
      <div className={`job-marker marker-${statusTone(job.conclusion || job.status)}`} />
      <div className="job-main"><strong>{job.name}</strong><span>{job.runner_name || "runner no indicado"}</span></div>
      <StatusLabel status={job.conclusion || job.status} />
      <span className="job-duration">{formatDuration(job.duration_seconds)}</span>
    </div>)}
  </div>;
}

function StatusLabel({ status }: { status: string | null }) {
  return <span className={`timeline-status status-text-${statusTone(status)}`}>{status || "—"}</span>;
}
