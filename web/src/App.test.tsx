import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { App, routeFromHash } from "./App";
import { demoArtifacts, demoHealth, demoOverview, demoResults, demoRunDetail, demoRuns, demoWorkflows } from "./fixtures";
import type { DashboardApi } from "./types";

const demoApi: DashboardApi = {
  getOverview: async () => demoOverview,
  getRuns: async () => demoRuns,
  getRunDetail: async () => demoRunDetail,
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
});
