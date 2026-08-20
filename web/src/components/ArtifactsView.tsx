import { useMemo, useState } from "react";
import type { Artifact, Page } from "../types";
import { archiveUrl } from "../api";
import { formatBytes, formatDate } from "../format";
import { EmptyState } from "./EmptyState";

export function ArtifactsView({ page, onLoadMore, loadingMore = false }: { page: Page<Artifact> | null; onLoadMore?: () => void; loadingMore?: boolean }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("all");
  const items = page?.items || [];
  const filtered = useMemo(() => items.filter((item) => item.name.toLowerCase().includes(query.toLowerCase()) && (state === "all" || item.archive_state === state)), [items, query, state]);

  return <div className="section-page">
    <div className="section-heading">
      <div><span className="eyebrow">ARCHIVOS</span><h1>Archivos producidos</h1><p>Todo lo que generan las ejecuciones de GitHub, con su estado real.{page?.total_count ? ` GitHub informa ${page.total_count.toLocaleString("es-ES")} archivos.` : ""}</p></div>
      <div className="filter-row"><input aria-label="Buscar artefacto" placeholder="Buscar nombre..." value={query} onChange={(event) => setQuery(event.target.value)} /><select aria-label="Filtrar archivado" value={state} onChange={(event) => setState(event.target.value)}><option value="all">Todos los estados</option><option value="archived">Archivados</option><option value="source_only">Solo fuente</option><option value="quota_blocked">Cuota bloqueada</option><option value="expired">Caducados</option><option value="error">Errores</option></select></div>
    </div>
    {filtered.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Artefacto</th><th>Run</th><th>Tamaño</th><th>Estado</th><th>Parser</th><th>Creado</th><th>Enlaces</th></tr></thead><tbody>{filtered.map((artifact) => <tr key={artifact.artifact_id}><td><div className="artifact-file"><span className="file-icon">{artifact.content_type?.includes("json") ? "{}" : "▤"}</span><div><strong>{artifact.name}</strong><span>#{artifact.artifact_id}</span></div></div></td><td className="mono">{artifact.run_id}</td><td>{formatBytes(artifact.size_bytes)}</td><td><span className={"archive-badge archive-" + artifact.archive_state}>{archiveLabel(artifact.archive_state)}</span></td><td>{artifact.parser_status}</td><td title={formatDate(artifact.created_at)}>{formatDate(artifact.created_at, false)}</td><td className="link-cell">{artifact.archive_key ? <a className="row-open" href={archiveUrl(artifact.archive_key)} target="_blank" rel="noreferrer" aria-label={"Abrir archivo de " + artifact.name}>↓</a> : null}{artifact.source_url ? <a className="row-open" href={artifact.source_url} target="_blank" rel="noreferrer" aria-label={"Abrir fuente de " + artifact.name}>↗</a> : null}</td></tr>)}</tbody></table>{page?.next_cursor && onLoadMore && <div className="table-more"><button className="text-button" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? "Cargando más..." : "Cargar más artefactos →"}</button></div>}</div> : <EmptyState title="No hay artefactos" detail="Ajusta el filtro o espera a la siguiente sincronización." />}
  </div>;
}

function archiveLabel(state: string): string {
  return ({ archived: "Archivado", source_only: "Solo fuente", quota_blocked: "Cuota", expired: "Caducado", error: "Error", indexed: "Indexado" } as Record<string, string>)[state] || state;
}
