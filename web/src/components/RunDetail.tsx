import type { JobLogs, RunDetail } from "../types";
import { archiveUrl } from "../api";
import { formatBytes, formatDate, formatDuration, metricValue, shortSha } from "../format";
import { StatusPill } from "./StatusPill";
import { JobTimeline } from "./Charts";
import { EmptyState } from "./EmptyState";

export function RunDetailView({ detail, onBack, onLoadLogs }: { detail: RunDetail; onBack: () => void; onLoadLogs: (jobId: number) => Promise<JobLogs> }) {
  const { run } = detail;
  return <div className="detail-page">
    <button className="back-link" onClick={onBack}>← Volver a ejecuciones</button>
    {detail.stale && <div className="notice notice-warning detail-notice"><span className="notice-mark">!</span><div><strong>Detalle potencialmente desactualizado</strong><span>La última sincronización no está dentro de la ventana esperada.</span></div></div>}
    <div className="detail-hero"><div><div className="eyebrow">RUN #{run.run_number} · {run.workflow_name}</div><h1>{run.name}</h1><div className="detail-subtitle"><StatusPill status={run.conclusion || run.status} label={run.status !== "completed" ? "En curso" : undefined} /><span>{run.event}</span><span>{run.branch}</span><span className="mono">{shortSha(run.commit_sha)}</span></div></div><a className="button button-ghost" href={run.html_url} target="_blank" rel="noreferrer">Ver en GitHub ↗</a></div>
    <div className="detail-stats"><Stat label="Creado" value={formatDate(run.created_at)} /><Stat label="Actualizado" value={formatDate(run.updated_at)} /><Stat label="Duración" value={formatDuration(run.duration_seconds)} /><Stat label={run.completion_type === "actual" ? "Finalizó" : "Termina aprox."} value={formatDate(run.completion_at)} /></div>
    {run.completion_type === "estimated" && <p className="detail-estimate-note">Estimación basada en la duración media de ejecuciones anteriores {run.completion_basis === "workflow" ? "de este mismo proceso" : "del conjunto de procesos"}. Puede cambiar mientras avanza.</p>}
    <div className="detail-grid"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">EJECUCIÓN</span><h2>Pasos y registro</h2></div><span className="panel-count">{detail.jobs.length}</span></div><JobTimeline jobs={detail.jobs} onLoadLogs={onLoadLogs} /></section><section className="panel"><div className="panel-heading"><div><span className="eyebrow">RESULTADOS</span><h2>Métricas interpretadas</h2></div><span className="panel-count">{detail.results.length}</span></div>{detail.results.length ? <div className="result-list">{detail.results.map((result) => <div className="result-line" key={result.result_id}><div><strong>{result.metric_key}</strong><span>{result.phase || "fase no indicada"} · {result.unit || "unidad no indicada"} · {result.baseline || "sin baseline"}</span></div><b>{metricValue(result)}</b></div>)}</div> : <EmptyState title="Sin métricas interpretadas" detail="El run está indexado, pero no contiene resultados reconocidos por los parsers actuales." />}</section></div>
    <section className="panel"><div className="panel-heading"><div><span className="eyebrow">ARCHIVOS</span><h2>Archivos de esta ejecución</h2></div><span className="panel-count">{detail.artifacts.length}</span></div>{detail.artifacts.length ? <div className="artifact-list">{detail.artifacts.map((artifact) => <div className="artifact-line" key={artifact.artifact_id}><div className="artifact-file"><span className="file-icon">{artifact.content_type?.includes("json") ? "{}" : "▤"}</span><div><strong>{artifact.name}</strong><span>{formatBytes(artifact.size_bytes)} · {artifact.parser_status}</span></div></div><ArchiveBadge state={artifact.archive_state} />{artifact.archive_key ? <a className="source-link" href={archiveUrl(artifact.archive_key)} target="_blank" rel="noreferrer">Archivo ↗</a> : null}{artifact.source_url ? <a className="source-link" href={artifact.source_url} target="_blank" rel="noreferrer">Fuente ↗</a> : null}</div>)}</div> : <EmptyState title="Sin archivos" detail="Esta ejecución no ha producido archivos indexados." />}</section>
  </div>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="detail-stat"><span>{label}</span><strong>{value}</strong></div>;
}

function ArchiveBadge({ state }: { state: string }) {
  const labels: Record<string, string> = { archived: "Archivado", source_only: "Solo fuente", indexed: "Indexado", quota_blocked: "Cuota", expired: "Caducado", error: "Error" };
  return <span className={"archive-badge archive-" + state}>{labels[state] || state}</span>;
}
