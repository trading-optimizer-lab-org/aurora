import type { ResultMetric, Run } from "./types";

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("es-ES", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value;
  let index = -1;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes} min ${String(rest).padStart(2, "0")} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

export function formatDate(value: string | null | undefined, withTime = true): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-ES", withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(date);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "sin fecha";
  const date = new Date(value).getTime();
  const difference = Date.now() - date;
  const minutes = Math.round(Math.abs(difference) / 60000);
  if (minutes < 1) return "ahora";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} d`;
}

export function shortSha(value: string): string {
  return value ? value.slice(0, 8) : "—";
}

export function metricValue(metric: ResultMetric): string {
  if (metric.value_text) return metric.value_text;
  if (metric.metric_value === null) return "—";
  if (metric.unit === "boolean") return metric.metric_value === 1 ? "Sí" : "No";
  if (metric.unit === "percent" || metric.unit === "%") return `${formatNumber(metric.metric_value)}%`;
  return formatNumber(metric.metric_value);
}

export function isActiveRun(run: Run): boolean {
  return run.status !== "completed" && !run.conclusion;
}

export function statusLabel(status: string | null): string {
  const labels: Record<string, string> = {
    in_progress: "En curso",
    queued: "En cola",
    waiting: "Esperando",
    requested: "Solicitado",
    pending: "Pendiente",
    completed: "Completado",
    success: "Correcto",
    failure: "Fallido",
    cancelled: "Cancelado",
    skipped: "Omitido",
    neutral: "Neutro",
    timed_out: "Tiempo agotado",
    action_required: "Acción requerida",
  };
  return status ? labels[status] || status.replace(/_/g, " ") : "Sin conclusión";
}

export function statusTone(status: string | null): "success" | "danger" | "warning" | "info" | "muted" {
  if (status === "success") return "success";
  if (status === "failure" || status === "timed_out") return "danger";
  if (status === "cancelled" || status === "skipped") return "muted";
  if (status === "in_progress" || status === "queued") return "info";
  if (status === "waiting" || status === "pending" || status === "action_required") return "warning";
  return "muted";
}
