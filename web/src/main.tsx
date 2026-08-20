import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorState } from "./components/ErrorState";
import "./styles.css";

class AppErrorBoundary extends React.Component<React.PropsWithChildren, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("Aurora dashboard render error", error);
  }

  render() {
    if (this.state.error) return <div className="page-wrap"><ErrorState detail={this.state.error.message} onRetry={() => window.location.reload()} /></div>;
    return this.props.children;
  }
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("No se ha encontrado el elemento raíz de Aurora.");

createRoot(rootElement).render(
  <React.StrictMode>
    <AppErrorBoundary><App /></AppErrorBoundary>
  </React.StrictMode>,
);
