import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, routeFromHash } from "./App";
import { demoArtifacts, demoHealth, demoOverview, demoResults, demoRunDetail, demoRuns, demoWorkflows } from "./fixtures";
import type { DashboardApi } from "./types";

const demoApi: DashboardApi = {
  getOverview: async () => demoOverview,
  getRuns: async () => demoRuns,
  getRunDetail: async () => demoRunDetail,
  getJobLogs: async (jobId) => ({ schema_version: 1, job_id: jobId, content: "demo logs", content_type: "text/plain" }),
  getResults: async () => demoResults,
  getArtifacts: async () => demoArtifacts,
  getWorkflows: async () => demoWorkflows,
  getHealth: async () => demoHealth,
};

describe("Aurora dashboard", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  afterEach(() => {
    window.location.hash = "";
  });

  it("interpreta las rutas públicas del enlace secreto", () => {
    expect(routeFromHash("#runs")).toEqual({ view: "runs" });
    expect(routeFromHash("#run/32337129192")).toEqual({ view: "detail", runId: 32337129192 });
    expect(routeFromHash("#no-existe")).toEqual({ view: "overview" });
  });

  it("muestra el resumen y permite abrir el histórico y el detalle de un run", async () => {
    render(<App client={demoApi} />);

    expect(await screen.findByRole("heading", { name: "Aurora research control" })).toBeInTheDocument();
    expect(screen.getAllByText("Runs activos").length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole("button", { name: /Todos los runs/ }));
    expect(await screen.findByRole("heading", { name: "Todos los runs" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Abrir run 32337129192" }));
    expect(await screen.findByRole("heading", { name: "SP500 Atlas Static Run" })).toBeInTheDocument();
    expect(screen.getByText("Solo lectura")).toBeInTheDocument();
  });

  it("permite cargar la siguiente página del histórico", async () => {
    const getRuns = vi.fn(async (filters?: Record<string, string | number | null>) => filters?.cursor
      ? { ...demoRuns, items: [{ ...demoRuns.items[0], run_id: 999999999 }], next_cursor: null }
      : { ...demoRuns, next_cursor: "cursor-2" });
    const pagedApi: DashboardApi = { ...demoApi, getRuns };
    window.location.hash = "#runs";

    render(<App client={pagedApi} />);

    expect(await screen.findByRole("heading", { name: "Todos los runs" })).toBeInTheDocument();
    getRuns.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Cargar más ejecuciones/ }));
    await waitFor(() => expect(getRuns).toHaveBeenCalledTimes(1));
    expect(getRuns.mock.calls[0][0]).toMatchObject({ cursor: "cursor-2", limit: 50 });
  });

  it("carga los logs desde el detalle de un run", async () => {
    const getJobLogs = vi.fn(async (jobId: number) => ({
      schema_version: 1 as const,
      job_id: jobId,
      content: "linea de log del job",
      content_type: "text/plain",
    }));
    const logsApi: DashboardApi = { ...demoApi, getJobLogs };
    window.location.hash = "#run/32337129192";

    render(<App client={logsApi} />);

    expect(await screen.findByRole("heading", { name: "SP500 Atlas Static Run" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Ver logs" })[0]);
    expect(await screen.findByText("linea de log del job")).toBeInTheDocument();
    expect(getJobLogs).toHaveBeenCalledWith(901);
  });
});
