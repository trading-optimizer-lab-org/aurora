interface ErrorStateProps {
  title?: string;
  detail: string;
  onRetry?: () => void;
}

export function ErrorState({ title = "No se han podido cargar los datos", detail, onRetry }: ErrorStateProps) {
  return <div className="error-state"><div className="error-mark">!</div><div><h3>{title}</h3><p>{detail}</p>{onRetry && <button className="button button-ghost" onClick={onRetry}>Reintentar</button>}</div></div>;
}
