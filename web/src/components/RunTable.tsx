import type { Page, Run } from "../types";
import { formatDate, formatDuration, isActiveRun, relativeTime, shortSha } from "../format";
import { StatusPill } from "./StatusPill";
import { EmptyState } from "./EmptyState";

interface RunTableProps {
  page: Page<Run> | null;
  onOpen: (runId: number) => void;
  compact?: boolean;
  onLoadMore?: () => void;
  loadingMore?: boolean;
}

export function RunTable({ page, onOpen, compact = false, onLoadMore, loadingMore = false }: RunTableProps) {
  if (!page || !page.items.length) return <EmptyState title="No hay ejecuciones" detail="Cuando GitHub produzca un run, aparecerá aquí con su estado y procedencia." />;
  return <div className={`data-table-wrap ${compact ? "table-compact" : ""}`}>
    <table className="data-table"><caption className="sr-only">Ejecuciones de GitHub Actions</caption><thead><tr><th>Ejecución</th><th>Estado</th><th>Finalización</th><th>Duración</th><th>Actualizado</th><th /></tr></thead><tbody>
      {page.items.map((run) => <tr key={run.run_id} className="click-row" onClick={() => onOpen(run.run_id)}>
        <td><div className="run-cell"><span className={`run-type-dot ${run.parser_status}`} /><div><strong>{run.workflow_name}</strong><span>#{run.run_number} · {run.name !== run.workflow_name ? run.name : shortSha(run.commit_sha)} · {run.branch}</span></div></div></td>
        <td><StatusPill status={run.conclusion || run.status} label={isActiveRun(run) ? "En curso" : undefined} /></td>
        <td><CompletionCell run={run} /></td>
        <td className="numeric">{formatDuration(run.duration_seconds)}</td>
        <td><span className="date-cell" title={formatDate(run.updated_at)}>{relativeTime(run.updated_at)}</span></td>
        <td><button className="row-open" aria-label={`Abrir run ${run.run_id}`} onClick={(event) => { event.stopPropagation(); onOpen(run.run_id); }}>→</button></td>
      </tr>)}
    </tbody></table>
    {page.next_cursor && <div className="table-more">{onLoadMore ? <button className="text-button" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? "Cargando más..." : "Cargar más ejecuciones →"}</button> : "Hay más ejecuciones disponibles."}</div>}
  </div>;
}

function CompletionCell({ run }: { run: Run }) {
  const overdue = run.completion_type === "estimated" && run.completion_at && Date.parse(run.completion_at) < Date.now();
  const label = run.completion_type === "actual" ? "Finalizó" : run.completion_type === "estimated" ? overdue ? "Estimación superada" : run.completion_basis === "workflow" ? "Estimación del proceso" : "Estimación general" : "Sin estimación";
  return <div className={`completion-cell completion-${run.completion_type}${overdue ? " completion-overdue" : ""}`}><strong>{run.completion_at ? formatDate(run.completion_at) : "—"}</strong><span>{label}</span></div>;
}
