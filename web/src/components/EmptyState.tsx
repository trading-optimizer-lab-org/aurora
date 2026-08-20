interface EmptyStateProps {
  title: string;
  detail: string;
}

export function EmptyState({ title, detail }: EmptyStateProps) {
  return <div className="empty-state"><div className="empty-mark">—</div><h3>{title}</h3><p>{detail}</p></div>;
}
