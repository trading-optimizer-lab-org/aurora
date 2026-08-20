import { useCallback, useEffect, useMemo, useState } from "react";
import { dashboardClient } from "./api";
import type { DashboardApi, Overview, Page, ResultMetric, Run, RunDetail, Artifact, Workflow } from "./types";
import type { ViewName } from "./components/Layout";
import { Layout } from "./components/Layout";
import { MetricCard } from "./components/MetricCard";
import { RunTable } from "./components/RunTable";
import { ResultsView } from "./components/ResultsView";
import { ArtifactsView } from "./components/ArtifactsView";
import { WorkflowsView } from "./components/WorkflowsView";
import { RunDetailView } from "./components/RunDetail";
import { ConclusionBars, RunSparkline } from "./components/Charts";
import { EmptyState } from "./components/EmptyState";
import { ErrorState } from "./components/ErrorState";
import { formatBytes, formatCompact, formatDate, relativeTime } from "./format";

export interface AppProps {
  client?: DashboardApi;
}

export interface RouteState {
  view: ViewName;
  runId?: number;
}

export function routeFromHash(hash = typeof window === "undefined" ? "" : window.location.hash): RouteState {
  const value = hash.replace(/^#/, "");
  if (value.startsWith("run/")) {
    const runId = Number(value.slice(4));
    if (Number.isSafeInteger(runId) && runId > 0) return { view: "detail", runId };
  }
  if (value === "runs" || value === "results" || value === "artifacts" || value === "workflows") {
    return { view: value };
  }
  return { view: "overview" };
}

function emptyPage<T>(items: T[] = []): Page<T> {
  return { schema_version: 1, items, next_cursor: null, stale: false };
}

function LoadingState({ label = "Cargando datos" }: { label?: string }) {
  return <div className="loading-state"><span className="loading-orbit" /><span>{label}</span></div>;
}

export function App({ client = dashboardClient }: AppProps) {
  const [route, setRoute] = useState<RouteState>(() => routeFromHash());
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [runsPage, setRunsPage] = useState<Page<Run> | null>(null);
  const [resultsPage, setResultsPage] = useState<Page<ResultMetric> | null>(null);
  const [artifactsPage, setArtifactsPage] = useState<Page<Artifact> | null>(null);
  const [workflowsPage, setWorkflowsPage] = useState<Page<Workflow> | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [runSearch, setRunSearch] = useState("");
  const [runStatus, setRunStatus] = useState("all");
  const [runFilters, setRunFilters] = useState({ q: "", status: "" });
  const [runsLoadingMore, setRunsLoadingMore] = useState(false);
  const [resultsLoadingMore, setResultsLoadingMore] = useState(false);
  const [artifactsLoadingMore, setArtifactsLoadingMore] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const isDemo = import.meta.env.VITE_DEMO_MODE === "true";

  const navigate = useCallback((view: ViewName) => {
    const nextHash = view === "overview" ? "" : view;
    if (window.location.hash === (nextHash ? `#${nextHash}` : "")) {
      setRoute({ view });
      return;
    }
    window.location.hash = nextHash;
  }, []);

  const openRun = useCallback((runId: number) => {
    window.location.hash = `run/${runId}`;
  }, []);

  const reload = useCallback(() => setRefreshKey((value) => value + 1), []);

  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadOverview = async () => {
      try {
        const next = await client.getOverview();
        if (!cancelled) {
          setOverview(next);
          setOverviewError(null);
        }
      } catch (error) {
        if (!cancelled) setOverviewError(error instanceof Error ? error.message : "Error desconocido");
      }
    };
    void loadOverview();
    const timer = window.setInterval(() => void loadOverview(), 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [client, refreshKey]);

  useEffect(() => {
    let cancelled = false;
    const loadPage = async () => {
      setPageError(null);
      if (route.view === "overview") {
        setPageLoading(false);
        return;
      }
      setPageLoading(true);
      try {
        if (route.view === "runs") {
          const next = await client.getRuns({ q: runFilters.q, status: runFilters.status, limit: 50 });
          if (!cancelled) setRunsPage(next);
        } else if (route.view === "results") {
          const next = await client.getResults({ limit: 100 });
          if (!cancelled) setResultsPage(next);
        } else if (route.view === "artifacts") {
          const next = await client.getArtifacts({ limit: 100 });
          if (!cancelled) setArtifactsPage(next);
        } else if (route.view === "workflows") {
          const next = await client.getWorkflows();
          if (!cancelled) setWorkflowsPage(next);
        } else if (route.view === "detail" && route.runId) {
          const next = await client.getRunDetail(route.runId);
          if (!cancelled) setDetail(next);
        }
      } catch (error) {
        if (!cancelled) setPageError(error instanceof Error ? error.message : "Error desconocido");
      } finally {
        if (!cancelled) setPageLoading(false);
      }
    };
    void loadPage();
    return () => {
      cancelled = true;
    };
  }, [client, route, runFilters, refreshKey]);

  const activePage = useMemo(() => emptyPage(overview?.active_runs || []), [overview]);
  const recentPage = useMemo(() => emptyPage(overview?.recent_runs || []), [overview]);
  const navView: ViewName = route.view === "detail" ? "runs" : route.view;

  const submitRunFilters = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRunFilters({ q: runSearch.trim(), status: runStatus === "all" ? "" : runStatus });
  };

  const loadMoreRuns = useCallback(async () => {
    if (!runsPage?.next_cursor || runsLoadingMore) return;
    setRunsLoadingMore(true);
    try {
      const next = await client.getRuns({ q: runFilters.q, status: runFilters.status, limit: 50, cursor: runsPage.next_cursor });
      setRunsPage((current) => current ? { ...next, items: [...current.items, ...next.items] } : next);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Error desconocido");
    } finally {
      setRunsLoadingMore(false);
    }
  }, [client, runFilters, runsLoadingMore, runsPage]);

  const loadMoreResults = useCallback(async () => {
    if (!resultsPage?.next_cursor || resultsLoadingMore) return;
    setResultsLoadingMore(true);
    try {
      const next = await client.getResults({ limit: 100, cursor: resultsPage.next_cursor });
      setResultsPage((current) => current ? { ...next, items: [...current.items, ...next.items] } : next);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Error desconocido");
    } finally {
      setResultsLoadingMore(false);
    }
  }, [client, resultsLoadingMore, resultsPage]);

  const loadMoreArtifacts = useCallback(async () => {
    if (!artifactsPage?.next_cursor || artifactsLoadingMore) return;
    setArtifactsLoadingMore(true);
    try {
      const next = await client.getArtifacts({ limit: 100, cursor: artifactsPage.next_cursor });
      setArtifactsPage((current) => current ? { ...next, items: [...current.items, ...next.items] } : next);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Error desconocido");
    } finally {
      setArtifactsLoadingMore(false);
    }
  }, [artifactsLoadingMore, artifactsPage, client]);

  const archivePercent = overview ? Math.min(100, Math.round((overview.archive.used_bytes / Math.max(1, overview.archive.quota_bytes)) * 100)) : 0;
  const archiveDetail = overview ? `${formatBytes(overview.archive.used_bytes)} de ${formatBytes(overview.archive.quota_bytes)} reservados` : "Sin datos de archivo";

  const renderOverview = () => {
    if (!overview) {
      if (overviewError) return <ErrorState detail={overviewError} onRetry={reload} />;
      return <LoadingState label="Conectando con Aurora" />;
    }
    return <div className="dashboard-page">
      <div className="hero-heading"><div><span className="eyebrow">OPERATIONS OVERVIEW</span><h1>Aurora research control</h1><p>Runs, backtests y artefactos de GitHub Actions en una vista única, con su estado y procedencia.</p></div><div className="hero-meta"><span className="hero-meta-label">ÚLTIMA SINCRONIZACIÓN</span><strong>{overview.sync.last_success_at ? relativeTime(overview.sync.last_success_at) : "sin sincronizar"}</strong><span>{overview.generated_at ? formatDate(overview.generated_at) : "—"}</span></div></div>
      {(overview.stale || overview.sync.last_error) && <div className="notice notice-warning"><span className="notice-mark">!</span><div><strong>Datos potencialmente desactualizados</strong><span>{overview.sync.last_error || "La última sincronización no ha terminado correctamente."}</span></div></div>}
      <div className="metric-grid"><MetricCard label="Runs activos" value={formatCompact(overview.totals.active_runs)} detail="actualizados automáticamente" tone="cyan" icon="↗" /><MetricCard label="Runs indexados" value={formatCompact(overview.totals.runs)} detail={`${formatCompact(overview.totals.workflows)} workflows`} tone="violet" icon="◈" /><MetricCard label="Artefactos" value={formatCompact(overview.totals.artifacts)} detail="inventario GitHub" tone="violet" icon="□" /><MetricCard label="Resultados" value={formatCompact(overview.totals.parsed_results)} detail="métricas interpretadas" tone="green" icon="∿" /><MetricCard label="Archivo" value={`${archivePercent}%`} detail={archiveDetail} tone="orange" icon="▣" /></div>
      <div className="dashboard-grid dashboard-grid-top"><section className="panel active-panel"><div className="panel-heading"><div><span className="eyebrow">LIVE QUEUE</span><h2>Runs activos</h2></div><button className="text-button" onClick={() => navigate("runs")}>Ver todos →</button></div><RunTable page={activePage} onOpen={openRun} compact /></section><section className="panel chart-panel"><div className="panel-heading"><div><span className="eyebrow">OUTCOME MIX</span><h2>Conclusiones</h2></div><span className="panel-note">histórico indexado</span></div>{overview.conclusions.length ? <ConclusionBars values={overview.conclusions} /> : <EmptyState title="Sin conclusiones" detail="Aún no hay resultados históricos para representar." />}</section></div>
      <div className="dashboard-grid dashboard-grid-bottom"><section className="panel recent-panel"><div className="panel-heading"><div><span className="eyebrow">RECENT ACTIVITY</span><h2>Actividad reciente</h2></div><button className="text-button" onClick={() => navigate("runs")}>Abrir histórico →</button></div><RunTable page={recentPage} onOpen={openRun} /></section><section className="panel latency-panel"><div className="panel-heading"><div><span className="eyebrow">RUNTIME SIGNAL</span><h2>Duración de runs</h2></div><span className="panel-note">últimos {overview.recent_runs.length}</span></div><RunSparkline runs={overview.recent_runs} /><div className="chart-foot"><span>Más rápido</span><span>Más lento</span></div></section></div>
    </div>;
  };

  const renderPage = () => {
    if (route.view === "overview") return renderOverview();
    if (pageLoading && !runsPage && !resultsPage && !artifactsPage && !workflowsPage && !detail) return <LoadingState />;
    if (pageError) return <ErrorState detail={pageError} onRetry={reload} />;
    if (route.view === "runs") return <div className="section-page"><div className="section-heading"><div><span className="eyebrow">RUN REGISTRY</span><h1>Todos los runs</h1><p>Histórico completo de ejecuciones, desde CI hasta investigación y validación.</p></div><form className="filter-row" onSubmit={submitRunFilters}><input aria-label="Buscar run" placeholder="Buscar workflow, rama o actor..." value={runSearch} onChange={(event) => setRunSearch(event.target.value)} /><select aria-label="Filtrar estado" value={runStatus} onChange={(event) => setRunStatus(event.target.value)}><option value="all">Todos los estados</option><option value="in_progress">En curso</option><option value="completed">Completados</option><option value="success">Correctos</option><option value="failure">Fallidos</option></select><button className="button button-primary" type="submit">Filtrar</button></form></div><RunTable page={runsPage} onOpen={openRun} onLoadMore={loadMoreRuns} loadingMore={runsLoadingMore} /></div>;
    if (route.view === "results") return <ResultsView page={resultsPage} onLoadMore={loadMoreResults} loadingMore={resultsLoadingMore} />;
    if (route.view === "artifacts") return <ArtifactsView page={artifactsPage} onLoadMore={loadMoreArtifacts} loadingMore={artifactsLoadingMore} />;
    if (route.view === "workflows") return <WorkflowsView page={workflowsPage} />;
    if (route.view === "detail" && detail) return <RunDetailView detail={detail} onBack={() => navigate("runs")} onLoadLogs={(jobId) => client.getJobLogs(jobId)} />;
    return <LoadingState />;
  };

  return <Layout view={navView} onNavigate={navigate} overview={overview} isDemo={isDemo}>{renderPage()}</Layout>;
}
