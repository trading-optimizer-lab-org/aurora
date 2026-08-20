import { statusLabel, statusTone } from "../format";

interface StatusPillProps {
  status: string | null;
  label?: string;
  dot?: boolean;
}

export function StatusPill({ status, label, dot = true }: StatusPillProps) {
  const tone = statusTone(status);
  return <span className={`status-pill status-${tone}`}>{dot && <span className="status-dot" aria-hidden="true" />}{label || statusLabel(status)}</span>;
}
