import type { ReactNode } from "react";

interface MetricCardProps {
  label: string;
  value: string;
  detail?: string;
  icon?: ReactNode;
  tone?: "cyan" | "violet" | "orange" | "green";
}

export function MetricCard({ label, value, detail, icon, tone = "cyan" }: MetricCardProps) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div className="metric-card-head"><span>{label}</span>{icon && <span className="metric-icon">{icon}</span>}</div>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </article>
  );
}
