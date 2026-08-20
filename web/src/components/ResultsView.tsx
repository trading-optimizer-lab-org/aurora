import { useMemo, useState } from "react";
import type { Page, ResultMetric } from "../types";
import { formatDate, metricValue } from "../format";
import { EmptyState } from "./EmptyState";

export function ResultsView({ page, onLoadMore, loadingMore = false }: { page: Page<ResultMetric> | null; onLoadMore?: () => void; loadingMore?: boolean }) {
  const [phase, setPhase] = useState("all");
  const [metric, setMetric] = useState("all");
  const items = page?.items || [];
  const phases = useMemo(() => ["all", ...Array.from(new Set(items.map((item) => item.phase).filter(Boolean) as string[]))], [items]);
  const metrics = useMemo(() => ["all", ...Array.from(new Set(items.map((item) => item.metric_key)))], [items]);
  const filtered = items.filter((item) => (phase === "all" || item.phase === phase) && (metric === "all" || item.metric_key === metric));

  return <div className="section-page">
    <div className="section-heading">
      <div><span className="eyebrow">RESULTS REGISTRY</span><h1>Backtests y resultados</h1><p>Métricas normalizadas con fase, unidad, periodo, baseline, coste, candidato y procedencia visible. No se comparan métricas con contratos incompatibles.</p></div>
      <div className="filter-row"><select aria-label="Filtrar por fase" value={phase} onChange={(event) => setPhase(event.target.value)}>{phases.map((item) => <option key={item} value={item}>{item === "all" ? "Todas las fases" : item}</option>)}</select><select aria-label="Filtrar por métrica" value={metric} onChange={(event) => setMetric(event.target.value)}>{metrics.map((item) => <option key={item} value={item}>{item === "all" ? "Todas las métricas" : item}</option>)}</select></div>
    </div>
    {filtered.length ? <div className="results-grid">{filtered.map((item) => <ResultCard key={item.result_id} item={item} />)}</div> : <EmptyState title="No hay resultados" detail="No hay métricas que coincidan con los filtros actuales." />}
    {page?.next_cursor && onLoadMore ? <div className="table-more"><button className="text-button" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? "Cargando más..." : "Cargar más resultados →"}</button></div> : null}
  </div>;
}

function ResultCard({ item }: { item: ResultMetric }) {
  const period = item.period_start || item.period_end ? `${item.period_start || "?"} → ${item.period_end || "?"}` : null;
  return <article className="result-card">
    <div className="result-card-top"><span className="result-kind">{item.result_kind}</span><span className={item.passed === true ? "pass-mark" : item.passed === false ? "fail-mark" : "neutral-mark"}>{item.passed === true ? "PASS" : item.passed === false ? "FAIL" : "—"}</span></div>
    <div className="result-metric-name">{item.metric_key}</div>
    <div className="result-value">{metricValue(item)} <small>{item.unit || "sin unidad"}</small></div>
    <div className="result-context"><span>{item.phase || "fase no indicada"}</span><span>{item.baseline || "sin baseline"}</span><a className="result-run-link" href={"#run/" + item.run_id}>run {item.run_id} ↗</a></div>
    <div className="result-details">
      {period ? <span><b>Periodo</b>{period}</span> : null}
      {item.cost_model ? <span><b>Coste</b>{item.cost_model}</span> : null}
      {item.candidate_id ? <span><b>Candidato</b>{item.candidate_id}</span> : null}
      {item.artifact_id ? <span><b>Artefacto</b>#{item.artifact_id}</span> : null}
    </div>
    <div className="result-source">{item.parser_key} v{item.parser_version} · {formatDate(item.captured_at)}{item.source_path ? ` · ${item.source_path}` : ""}</div>
    {Object.keys(item.evidence).length ? <details className="result-evidence"><summary>Ver procedencia</summary><pre>{JSON.stringify(item.evidence, null, 2)}</pre></details> : null}
  </article>;
}
