import type { Page, Run } from "../types";
import { formatDate, formatDuration, isActiveRun, relativeTime, shortSha } from "../format";
import { StatusPill } from "./StatusPill";
import { EmptyState } from "./EmptyState";

interface RunTableProps {
  page: Page<Run> | null;
  onOpen: (runId: number) => void;
  compact?: boolean;
}

export function RunTable({ page, onOpen, compact = false }: RunTableProps) {
  if (!page || !page.items.length) return <EmptyState title="No hay ejecuciones" detail="Cuando GitHub produzca un run, aparecerá aquí con su estado y procedencia." />;
  return <div className={`data-table-wrap ${compact ? "table-compact" : ""}`}>
    <table className="data-table"><caption className="sr-only">Ejecuciones de GitHub Actions</caption><thead><tr><th>Workflow / run</th><th>Estado</th><th>Rama</th><th>Evento</th><th>Duración</th><th>Actualizado</th><th /></tr></thead><tbody>
      {page.items.map((run) => <tr key={run.run_id} className="click-row" onClick={() => onOpen(run.run_id)}>
        <td><div className="run-cell"><span className={`run-type-dot ${run.parser_status}`} /><div><strong>{run.workflow_name}</strong><span>#{run.run_number} · {run.name !== run.workflow_name ? run.name : shortSha(run.commit_sha)}</span></div></div></td>
        <td><StatusPill status={run.conclusion || run.status} label={isActiveRun(run) ? "En curso" : undefined} /></td>
        <td><span className="branch-chip">{run.branch}</span></td>
        <td><span className="event-text">{run.event}</span></td>
        <td className="numeric">{formatDuration(run.duration_seconds)}</td>
        <td><span className="date-cell" title={formatDate(run.updated_at)}>{relativeTime(run.updated_at)}</span></td>
        <td><button className="row-open" aria-label={`Abrir run ${run.run_id}`} onClick={(event) => { event.stopPropagation(); onOpen(run.run_id); }}>→</button></td>
      </tr>)}
    </tbody></table>
    {page.next_cursor && <div className="table-more">Hay más ejecuciones disponibles. Usa la paginación para continuar.</div>}
  </div>;
}
