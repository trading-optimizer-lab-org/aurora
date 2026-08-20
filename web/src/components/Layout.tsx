import type { ReactNode } from "react";
import type { Overview } from "../types";
import { formatBytes, formatDate } from "../format";

export type ViewName = "overview" | "runs" | "results" | "artifacts" | "workflows" | "detail";

const navItems: Array<{ id: ViewName; label: string; icon: string }> = [
  { id: "overview", label: "Inicio", icon: "⌂" },
  { id: "runs", label: "Todos los runs", icon: "↗" },
  { id: "results", label: "Backtests", icon: "∿" },
  { id: "artifacts", label: "Artefactos", icon: "□" },
  { id: "workflows", label: "Workflows", icon: "◈" },
];

interface LayoutProps {
  view: ViewName;
  onNavigate: (view: ViewName) => void;
  overview: Overview | null;
  children: ReactNode;
  isDemo: boolean;
}

export function Layout({ view, onNavigate, overview, children, isDemo }: LayoutProps) {
  const archivePercent = overview ? Math.min(100, Math.round((overview.archive.used_bytes / Math.max(1, overview.archive.quota_bytes)) * 100)) : 0;
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-orbit" /><div><strong>AURORA</strong><small>RUNS CONTROL</small></div></div>
      <div className="sidebar-section-label">RESEARCH OPERATIONS</div>
      <nav className="main-nav" aria-label="Navegación principal">
        {navItems.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? "nav-active" : ""}`} onClick={() => onNavigate(item.id)}><span className="nav-icon">{item.icon}</span>{item.label}{item.id === "runs" && overview?.totals.active_runs ? <span className="nav-count">{overview.totals.active_runs}</span> : null}</button>)}
      </nav>
      <div className="sidebar-footer">
        <div className="archive-mini"><div className="mini-head"><span>ARCHIVE</span><strong>{archivePercent}%</strong></div><div className="mini-track"><span style={{ width: `${archivePercent}%` }} /></div><small>{overview ? `${formatBytes(overview.archive.used_bytes)} / ${formatBytes(overview.archive.quota_bytes)}` : "cargando"}</small></div>
        <div className="read-only"><span className="read-only-dot" /> Solo lectura</div>
      </div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div className="mobile-brand"><span className="brand-orbit" /><strong>AURORA</strong></div><div className="topbar-meta"><span className={`live-indicator ${overview?.totals.active_runs ? "is-live" : ""}`}><i /> {overview?.totals.active_runs ? `${overview.totals.active_runs} activo${overview.totals.active_runs === 1 ? "" : "s"}` : "Sin activos"}</span><span className="topbar-separator" /><span className="sync-time">Actualizado {overview?.sync.last_success_at ? formatDate(overview.sync.last_success_at) : "—"}</span>{isDemo && <span className="demo-badge">DEMO LOCAL</span>}</div></header>
      <div className="page-wrap">{children}</div>
    </main>
  </div>;
}
